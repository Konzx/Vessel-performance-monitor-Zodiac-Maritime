"""Real Chrome interaction tests, enabled with RUN_BROWSER_TESTS=1."""
import os
import threading

import pytest
from werkzeug.serving import make_server

import database as db

pytestmark = pytest.mark.skipif(os.getenv('RUN_BROWSER_TESTS') != '1', reason='Set RUN_BROWSER_TESTS=1 to run Chrome tests')


@pytest.fixture
def page(isolated_database):
    from playwright.sync_api import sync_playwright
    from app import server

    http = make_server('127.0.0.1', 0, server, threaded=True)
    thread = threading.Thread(target=http.serve_forever, daemon=True)
    thread.start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel='chrome', headless=True)
            page = browser.new_page(viewport={'width': 1440, 'height': 1200})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('console', lambda message: errors.append(message.text) if message.type == 'error' else None)
            page.goto(f'http://127.0.0.1:{http.server_port}')
            page.wait_for_function('() => window.dash_ag_grid')
            page.evaluate("async () => { await dash_ag_grid.getApiAsync('grid'); }")
            wait_rows(page, 410)
            page.locator('#analyst').fill('browser-analyst')
            yield page
            browser.close()
            assert errors == [], '\n'.join(errors)
    finally:
        http.shutdown()
        thread.join(timeout=5)


def rows(page):
    return page.evaluate("""async () => {
        const result = [];
        (await dash_ag_grid.getApiAsync('grid')).forEachNode(node => result.push(node.data));
        return result;
    }""")


def wait_rows(page, count):
    try:
        page.wait_for_function("count => dash_ag_grid.getApi('grid').getDisplayedRowCount() === count", arg=count, timeout=10000)
    except Exception:
        print('Expected row count:', count, 'Actual:', page.evaluate("() => dash_ag_grid.getApi('grid').getDisplayedRowCount()"))
        raise


def select_chart(page, kind, mode='select'):
    chart_id = kind.lower() + '-chart'
    page.locator('#' + chart_id).scroll_into_view_if_needed()
    box = page.evaluate("""async ({id, mode}) => {
        const graph = document.querySelector('#' + id + ' .js-plotly-plot');
        await Plotly.relayout(graph, {dragmode: mode});
        graph.once('plotly_selected', event => {
            window.testSelectedIds = event.points.map(point => point.customdata[0]);
        });
        window.testSelectedIds = null;
        const rect = graph.getBoundingClientRect(), size = graph._fullLayout._size;
        return {x: rect.x + size.l + 3, y: rect.y + size.t + 3,
                w: size.w * 0.3, h: size.h - 6};
    }""", {'id': chart_id, 'mode': mode})
    page.mouse.move(box['x'], box['y'])
    page.mouse.down()
    page.mouse.move(box['x'] + box['w'], box['y'], steps=8)
    page.mouse.move(box['x'] + box['w'], box['y'] + box['h'], steps=8)
    if mode == 'lasso':
        page.mouse.move(box['x'], box['y'] + box['h'], steps=8)
        page.mouse.move(box['x'], box['y'], steps=8)
    page.mouse.up()
    page.wait_for_function('() => window.testSelectedIds && window.testSelectedIds.length > 0')
    return set(page.evaluate('window.testSelectedIds'))


def edit_cell(page, row_id, field, value, finish=True):
    page.evaluate("""async ({id, field}) => {
        const api = await dash_ag_grid.getApiAsync('grid');
        const node = api.getRowNode('report-' + id);
        api.paginationGoToPage(Math.floor(node.rowIndex / api.paginationGetPageSize()));
        api.ensureColumnVisible(field);
        api.startEditingCell({rowIndex: node.rowIndex, colKey: field});
    }""", {'id': row_id, 'field': field})
    editor = page.locator('#grid .ag-cell-inline-editing input')
    editor.fill(str(value))
    if finish:
        editor.press('Enter')


def dropdown(page, component_id, value):
    control = page.locator('#' + component_id)
    control.click()
    page.get_by_role('option', name=value, exact=True).click()


@pytest.mark.parametrize('kind,baseline', [('Power', 'PWR_BSL_SAM'), ('Speed', 'SPD_BSL_OOS')])
def test_selection_edit_save_refresh_and_audit(page, kind, baseline):
    from playwright.sync_api import expect

    fields = page.evaluate("async () => (await dash_ag_grid.getApiAsync('grid')).getColumnDefs().map(column => column.field)")
    assert set(db.get_reports().columns) - {'version'} == set(fields)

    power_ids = select_chart(page, 'Power')
    wait_rows(page, len(power_ids))
    assert {r['row_id'] for r in rows(page)} == power_ids
    speed_ids = select_chart(page, 'Speed', mode='lasso')
    wait_rows(page, len(power_ids | speed_ids))
    assert {r['row_id'] for r in rows(page)} == power_ids | speed_ids

    field, deviation = f'{kind}_%', f'{kind}_Deviation'
    original = next(r for r in rows(page) if r['KPI'] == kind and r[field] is not None and r[field] >= 0)
    rid = original['row_id']
    for invalid in ['', '-1', '251']:
        edit_cell(page, rid, field, invalid)
        expect(page.locator('#validation-message')).to_contain_text('Edit rejected')
        assert next(r for r in rows(page) if r['row_id'] == rid)[field] == original[field]

    value = 0  # A valid endpoint that also creates a negative deviation to inspect.
    edit_cell(page, rid, field, value, finish=False)
    page.locator('#save').click()  # The click must finish the active editor before saving.
    expect(page.locator('#message')).to_contain_text('Saved changes to 1 report(s)')
    wait_rows(page, 410)
    page.wait_for_function("""() => ['power-chart', 'speed-chart'].every(id =>
        document.querySelector('#' + id + ' .js-plotly-plot')._fullData.every(trace => trace.selectedpoints == null))
    """)
    saved = db.get_reports().set_index('row_id').loc[rid]
    assert saved[field] == pytest.approx(value)
    assert saved[deviation] == pytest.approx(round(value - original[baseline], 1))
    page.evaluate("""async ({id, field}) => {
        const api = await dash_ag_grid.getApiAsync('grid'), node = api.getRowNode('report-' + id);
        api.paginationGoToPage(Math.floor(node.rowIndex / api.paginationGetPageSize()));
        api.ensureColumnVisible(field);
    }""", {'id': rid, 'field': deviation})
    expect(page.locator(f"#grid [row-id='report-{rid}'] [col-id='{deviation}']")).to_have_css('background-color', 'rgb(255, 226, 226)')
    with db.connect() as connection:
        audits = connection.execute('SELECT * FROM audit_log WHERE row_id=?', (rid,)).fetchall()
    assert {audit['field'] for audit in audits} == {field, deviation}
    assert all(audit['changed_by'] == 'browser-analyst' for audit in audits)

    edit_cell(page, rid, field, value + 1)
    page.locator('#refresh').click()
    expect(page.locator('#message')).to_contain_text('unsaved edits discarded')
    page.wait_for_function("""({id, value, field}) =>
        dash_ag_grid.getApi('grid').getRowNode('report-' + id).data[field] === value
    """, arg={'id': rid, 'value': value, 'field': field})
    assert db.get_reports().set_index('row_id').loc[rid][field] == pytest.approx(value)

    selected = select_chart(page, 'Speed')
    wait_rows(page, len(selected))
    page.locator('#refresh').click()
    wait_rows(page, 410)
    page.reload()
    page.wait_for_function('() => window.dash_ag_grid')
    page.evaluate("async () => { await dash_ag_grid.getApiAsync('grid'); }")
    wait_rows(page, 410)
    assert next(r for r in rows(page) if r['row_id'] == rid)[field] == pytest.approx(value)


def test_filters_clear_selection_and_compose(page):
    import app

    assert page.locator('#kpi').count() == 0
    assert {r['KPI'] for r in rows(page)} == {'Power', 'Speed'}
    selected = select_chart(page, 'Power')
    wait_rows(page, len(selected))
    dropdown(page, 'voyage', 'CARGO')
    expected = app.filtered(app.vessels[0], app.start_date, app.end_date, 'CARGO')
    wait_rows(page, len(expected))
    assert {r['row_id'] for r in rows(page)} == set(expected.row_id)
    dropdown(page, 'vessel', app.vessels[1])
    expected = app.filtered(app.vessels[1], app.start_date, app.end_date, 'CARGO')
    wait_rows(page, len(expected))
    assert {r['row_id'] for r in rows(page)} == set(expected.row_id)

    # Use the public Dash setter to change dates without depending on calendar styling.
    page.evaluate("""() => dash_clientside.set_props('dates', {
        start_date: '2026-04-01', end_date: '2026-04-30'
    })""")
    expected = app.filtered(app.vessels[1], '2026-04-01', '2026-04-30', 'CARGO')
    wait_rows(page, len(expected))
    assert {r['row_id'] for r in rows(page)} == set(expected.row_id)


def test_layout_and_mobile_width(page, tmp_path):
    from playwright.sync_api import expect

    expect(page.locator('h1')).to_have_css('text-align', 'center')
    assert page.locator('.instructions > li').count() == 3
    assert page.locator('#stats, .metric-card').count() == 0
    assert page.locator('.brand-logo').evaluate('(image) => image.complete && image.naturalWidth > 0')
    power = page.locator('#power-chart').bounding_box()
    speed = page.locator('#speed-chart').bounding_box()
    assert power['width'] > 1200
    assert speed['y'] >= power['y'] + power['height']
    assert abs(speed['width'] - power['width']) < 1
    page.screenshot(path=str(tmp_path / 'dashboard-desktop.png'), full_page=True)
    page.set_viewport_size({'width': 390, 'height': 844})
    page.wait_for_function('() => document.documentElement.scrollWidth <= window.innerWidth')
    page.wait_for_function("() => Array.from(document.querySelectorAll('.js-plotly-plot')).every(graph => graph._fullLayout.width <= graph.clientWidth + 1)")
    assert page.locator('#power-chart').bounding_box()['width'] < 390
    page.screenshot(path=str(tmp_path / 'dashboard-mobile.png'), full_page=True)


def test_editing_text_dates_ids_and_counts(page):
    from playwright.sync_api import expect

    original = next(r for r in rows(page) if r['KPI'] == 'Power')
    rid = original['row_id']
    for field, invalid in [('Vessel_Name', ''), ('Report_ID', 'not-a-uuid'),
                           ('To_Timestamp', '2026-02-30 12:00'), ('IMO', 123),
                           ('SP_BSL_Reports', 1.5), ('ME_Running_Hours', 99)]:
        edit_cell(page, rid, field, invalid)
        expect(page.locator('#validation-message')).to_contain_text('Edit rejected')
        assert next(r for r in rows(page) if r['row_id'] == rid)[field] == original[field]

    updates = {'Vessel_Name': 'MV NEW NAME',
               'Report_ID': 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
               'To_Timestamp': '2026-04-15 12:30', 'IMO': 9199991, 'SP_BSL_Reports': 125}
    for field, value in updates.items():
        edit_cell(page, rid, field, value)
    page.locator('#save').click()
    expect(page.locator('#message')).to_contain_text('Saved changes to 1 report(s)')
    wait_rows(page, 409)
    dropdown(page, 'vessel', 'MV NEW NAME')
    wait_rows(page, 1)
    saved = rows(page)[0]
    assert saved['Vessel_Name'] == 'MV NEW NAME'
    assert saved['Report_ID'] == updates['Report_ID']
    assert saved['To_Timestamp'] == '2026-04-15T12:30:00'
    assert saved['IMO'] == 9199991
    assert saved['SP_BSL_Reports'] == 125
    with db.connect() as connection:
        fields = {r['field'] for r in connection.execute('SELECT field FROM audit_log WHERE row_id=?', (rid,))}
    assert fields == set(updates)


def test_reset_filters_clears_selections_column_filters_and_unsaved_edits(page):
    import app

    dropdown(page, 'vessel', app.vessels[1])
    dropdown(page, 'voyage', 'CARGO')
    page.evaluate("""() => dash_clientside.set_props('dates', {
        start_date: '2026-04-01', end_date: '2026-04-30'
    })""")
    expected = app.filtered(app.vessels[1], '2026-04-01', '2026-04-30', 'CARGO')
    wait_rows(page, len(expected))
    page.wait_for_function("""prefix => ['power-chart', 'speed-chart'].every(id =>
        document.querySelector('#' + id + ' .js-plotly-plot').layout.uirevision.startsWith(prefix))
    """, arg=f'{app.vessels[1]}|2026-04-01|2026-04-30|CARGO|')
    selected = select_chart(page, 'Power')
    wait_rows(page, len(selected))
    original = next(r for r in rows(page) if r['KPI'] == 'Power')
    rid = original['row_id']
    edit_cell(page, rid, 'Power_ME', original['Power_ME'] + 100)
    page.evaluate("""() => dash_ag_grid.getApi('grid').setFilterModel({
        Report_ID: {filterType: 'text', type: 'contains', filter: 'no-matching-id'}
    })""")
    wait_rows(page, 0)
    page.locator('#reset-filters').click()
    wait_rows(page, 410)
    expected = app.filtered(app.vessels[0], app.start_date, app.end_date, 'Both')
    assert {r['row_id'] for r in rows(page)} == set(expected.row_id)
    assert 'Both' in page.locator('#voyage').inner_text()
    assert page.evaluate("() => dash_ag_grid.getApi('grid').getFilterModel()") == {}
    page.wait_for_function("""() => ['power-chart', 'speed-chart'].every(id =>
        document.querySelector('#' + id + ' .js-plotly-plot')._fullData.every(trace => trace.selectedpoints == null))
    """)
    assert db.get_reports().set_index('row_id').loc[rid]['Power_ME'] == original['Power_ME']

    # A second reset must also work when all filter values already equal their defaults.
    selected = select_chart(page, 'Power')
    wait_rows(page, len(selected))
    original = next(r for r in rows(page) if r['KPI'] == 'Power')
    rid = original['row_id']
    edit_cell(page, rid, 'Power_ME', original['Power_ME'] + 100)
    page.locator('#reset-filters').click()
    wait_rows(page, 410)
    assert next(r for r in rows(page) if r['row_id'] == rid)['Power_ME'] == original['Power_ME']
    with db.connect() as connection:
        assert connection.execute('SELECT COUNT(*) FROM audit_log').fetchone()[0] == 0


def test_named_saves_update_sqlite_and_record_each_analyst(page):
    from playwright.sync_api import expect

    original = next(r for r in rows(page) if r['KPI'] == 'Power')
    rid = original['row_id']
    page.locator('#analyst').fill('')
    edit_cell(page, rid, 'Power_ME', original['Power_ME'] + 100)
    assert db.get_reports().set_index('row_id').loc[rid]['Power_ME'] == original['Power_ME']
    page.locator('#save').click()
    expect(page.locator('#message')).to_contain_text('Enter an analyst name')
    with db.connect() as connection:
        assert connection.execute('SELECT COUNT(*) FROM audit_log').fetchone()[0] == 0

    for increment, analyst in [(100, 'Alice'), (200, 'Bob')]:
        if increment == 200:
            edit_cell(page, rid, 'Power_ME', original['Power_ME'] + increment)
        page.locator('#analyst').fill(analyst)
        page.locator('#save').click()
        version = original['version'] + increment // 100
        page.wait_for_function("""({id, version}) =>
            dash_ag_grid.getApi('grid').getRowNode('report-' + id).data.version === version
        """, arg={'id': rid, 'version': version})
        with db.connect() as connection:
            saved = connection.execute('SELECT Power_ME FROM reports WHERE row_id=?', (rid,)).fetchone()
            assert saved['Power_ME'] == original['Power_ME'] + increment
    with db.connect() as connection:
        audits = connection.execute('SELECT * FROM audit_log WHERE row_id=? ORDER BY audit_id', (rid,)).fetchall()
    assert [a['changed_by'] for a in audits] == ['Alice', 'Bob']
    assert all(a['field'] == 'Power_ME' and a['Report_ID'] == original['Report_ID'] and a['changed_at'] for a in audits)
    assert float(audits[0]['old_value']) == original['Power_ME']
    assert float(audits[0]['new_value']) == float(audits[1]['old_value']) == original['Power_ME'] + 100
    assert float(audits[1]['new_value']) == original['Power_ME'] + 200
    page.reload()
    page.wait_for_function('() => window.dash_ag_grid')
    page.evaluate("async () => { await dash_ag_grid.getApiAsync('grid'); }")
    wait_rows(page, 410)
    assert next(r for r in rows(page) if r['row_id'] == rid)['Power_ME'] == original['Power_ME'] + 200
