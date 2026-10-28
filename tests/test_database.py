from datetime import datetime

import pytest
import database as db


def report(kind):
    data = db.get_reports()
    return data[(data.KPI == kind) & data[f'{kind}_%'].notna()].iloc[0].to_dict()


def audit_rows():
    with db.connect() as conn:
        return [dict(row) for row in conn.execute('SELECT * FROM audit_log ORDER BY audit_id')]


def test_import_preserves_source_anomalies_and_is_idempotent():
    db.initialize()
    data = db.get_reports()
    assert len(data) == 1230
    assert data.row_id.is_unique
    assert data.Report_ID.duplicated().sum() == 1
    assert data.loc[data.KPI == 'Power', 'Power_%'].isna().sum() == 1
    assert (data.loc[data.KPI == 'Speed', 'Speed_%'] < 0).sum() == 1


@pytest.mark.parametrize('kind,baseline', [('Power', 'PWR_BSL_SAM'), ('Speed', 'SPD_BSL_OOS')])
def test_edit_persists_with_complete_audit(kind, baseline):
    original = report(kind)
    field, deviation = f'{kind}_%', f'{kind}_Deviation'
    edited = dict(original, **{field: original[field] + 0.2})
    assert db.save_edits([original], [edited], ' test-analyst ') == 1
    db.initialize()
    saved = db.get_reports().set_index('row_id').loc[original['row_id']]
    assert saved[field] == pytest.approx(edited[field])
    assert saved[deviation] == pytest.approx(round(edited[field] - original[baseline], 1))
    assert saved['version'] == original['version'] + 1
    audits = audit_rows()
    assert {a['field'] for a in audits} == {field, deviation}
    for audit in audits:
        assert audit['row_id'] == original['row_id']
        assert audit['Report_ID'] == original['Report_ID']
        assert audit['changed_by'] == 'test-analyst'
        assert float(audit['old_value']) == pytest.approx(original[audit['field']])
        assert float(audit['new_value']) == pytest.approx(saved[audit['field']])
        assert datetime.fromisoformat(audit['changed_at']).utcoffset().total_seconds() == 0


@pytest.mark.parametrize('kind', ['Power', 'Speed'])
@pytest.mark.parametrize('value', [None, '', ' ', 'invalid', 'nan', float('inf'), -0.1, 250.1])
def test_invalid_edits_leave_database_and_audit_unchanged(kind, value):
    original = report(kind)
    field = f'{kind}_%'
    edited = dict(original, **{field: value})
    with pytest.raises(ValueError):
        db.save_edits([original], [edited], 'test-analyst')
    saved = db.get_reports().set_index('row_id').loc[original['row_id']]
    assert saved[field] == original[field]
    assert saved['version'] == original['version']
    assert audit_rows() == []


def test_missing_power_can_be_corrected_without_replacing_other_rows():
    data = db.get_reports()
    original = data[(data.KPI == 'Power') & data['Power_%'].isna()].iloc[0].to_dict()
    assert db.save_edits([original], [dict(original, **{'Power_%': 100})], 'analyst') == 1
    audit = next(a for a in audit_rows() if a['field'] == 'Power_%')
    assert audit['old_value'] is None
    assert audit['new_value'] == '100.0'
    assert len(db.get_reports()) == 1230


def test_duplicate_report_id_is_updated_by_internal_key_only():
    rows = db.get_reports()
    duplicates = rows[rows.Report_ID.duplicated(keep=False)]
    original, other = (r.to_dict() for _, r in duplicates.iterrows())
    field = f"{original['KPI']}_%"
    assert db.save_edits([original], [dict(original, **{field: 110})], 'analyst') == 1
    saved_other = db.get_reports().set_index('row_id').loc[other['row_id']]
    assert saved_other['version'] == other['version']
    assert saved_other[f"{other['KPI']}_%"] == other[f"{other['KPI']}_%"]


def test_late_conflict_rolls_back_earlier_updates_and_audits():
    first, second = report('Power'), report('Speed')
    speed_edit = dict(second, **{'Speed_%': second['Speed_%'] + 0.2})
    db.save_edits([second], [speed_edit], 'other-analyst')
    audits_before = audit_rows()
    with pytest.raises(ValueError, match='changed since it was loaded'):
        db.save_edits([first, second], [dict(first, **{'Power_%': first['Power_%'] + 1}), speed_edit], 'analyst')
    saved = db.get_reports().set_index('row_id').loc[first['row_id']]
    assert saved['Power_%'] == first['Power_%']
    assert saved['version'] == first['version']
    assert audit_rows() == audits_before


def test_analyst_is_required():
    original = report('Power')
    with pytest.raises(ValueError, match='analyst name'):
        db.save_edits([original], [dict(original, **{'Power_%': 100})], ' ')
    assert audit_rows() == []


@pytest.mark.parametrize('kind', ['Power', 'Speed'])
@pytest.mark.parametrize('value', [0, 250])
def test_range_endpoints_are_accepted(kind, value):
    original = report(kind)
    field = f'{kind}_%'
    assert db.save_edits([original], [dict(original, **{field: value})], 'analyst') == 1
    assert db.get_reports().set_index('row_id').loc[original['row_id']][field] == value


@pytest.mark.parametrize('field,value', [
    ('IMO', 9000001), ('Vessel_Name', 'MV CORRECTED VESSEL'),
    ('Report_ID', 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'),
    ('To_Timestamp', '2026-04-15 12:30'), ('Voyage_Type', 'CARGO'),
    ('Report_Duration', 30), ('SP_BSL_Start', '2023-09-01 00:00'),
    ('SP_BSL_End', '2024-05-01 00:00'), ('SP_BSL_Reports', 120),
    ('PWR_BSL_SAM', 95), ('SPD_BSL_SAM', 92), ('SPD_BSL_OOS', 93),
    ('Power_ME', 4200), ('Power_%', 110), ('Power_Deviation', -5),
    ('Speed_%', 95), ('Speed_Deviation', -9), ('ME_Running_Hours', 20),
    ('Power_Filter_Flag', 'Yes'), ('Speed_Filter', 'Yes'),
    ('Dual_Fuel_Mode_str', 'Dual Fuel Capable'),
])
def test_every_source_field_can_be_edited_and_audited(field, value):
    original = report('Power')
    if field == 'Voyage_Type':
        value = 'CARGO' if original[field] == 'BALLAST' else 'BALLAST'
    if field == 'Dual_Fuel_Mode_str':
        value = 'Dual Fuel Capable' if original[field] == 'Non Dual Fuel Only' else 'Non Dual Fuel Only'
    assert db.save_edits([original], [dict(original, **{field: value})], 'analyst') == 1
    saved = db.get_reports().set_index('row_id').loc[original['row_id']]
    if field in ('To_Timestamp', 'SP_BSL_Start', 'SP_BSL_End'):
        assert saved[field] == value.replace(' ', 'T') + ':00'
    else:
        assert saved[field] == value
    assert field in {audit['field'] for audit in audit_rows()}


@pytest.mark.parametrize('field,value', [
    ('IMO', 123), ('IMO', 9199999.5), ('IMO', True),
    ('Vessel_Name', ''), ('Vessel_Name', 'A' * 121),
    ('Report_ID', 'invalid-id'), ('Report_ID', ''),
    ('To_Timestamp', '2026-02-30 12:00'), ('To_Timestamp', 'tomorrow'),
    ('To_Timestamp', '2026-04-01T12:00:00+05:30'), ('To_Timestamp', ''),
    ('KPI', 'Other'), ('Voyage_Type', 'LOADED'), ('Voyage_Type', ''),
    ('Report_Duration', 0), ('Report_Duration', 10),
    ('SP_BSL_Start', '2025-01-01'), ('SP_BSL_End', '2022-01-01'),
    ('SP_BSL_Reports', 1.5), ('SP_BSL_Reports', -1), ('SP_BSL_Reports', 2147483648),
    ('PWR_BSL_SAM', 251), ('SPD_BSL_SAM', -1), ('SPD_BSL_OOS', float('inf')),
    ('Power_ME', -1), ('Power_Deviation', -251), ('Speed_Deviation', 251),
    ('ME_Running_Hours', 30), ('ME_Running_Hours', -1),
    ('Power_Filter_Flag', 'Maybe'), ('Speed_Filter', 'Maybe'),
    ('Dual_Fuel_Mode_str', 'Unknown'), ('Dual_Fuel_Mode_str', ''),
])
def test_invalid_non_percentage_fields_are_rejected_atomically(field, value):
    original = report('Power')
    with pytest.raises(ValueError):
        db.save_edits([original], [dict(original, **{field: value})], 'analyst')
    saved = db.get_reports().set_index('row_id').loc[original['row_id']]
    assert saved['version'] == original['version']
    assert audit_rows() == []


def test_kpi_switch_requires_complete_new_kpi_fields():
    original = report('Power')
    with pytest.raises(ValueError, match='required'):
        db.save_edits([original], [dict(original, KPI='Speed')], 'analyst')
    edited = dict(original, KPI='Speed', SPD_BSL_SAM=90, SPD_BSL_OOS=91,
                  **{'Speed_%': 95, 'Speed_Deviation': 4, 'Speed_Filter': 'No'})
    assert db.save_edits([original], [edited], 'analyst') == 1
    saved = db.get_reports().set_index('row_id').loc[original['row_id']]
    assert saved['KPI'] == 'Speed'
    assert 'KPI' in {audit['field'] for audit in audit_rows()}


def test_explicit_deviation_override_is_preserved_with_percentage_change():
    original = report('Power')
    edited = dict(original, **{'Power_%': 100, 'Power_Deviation': -4.5})
    db.save_edits([original], [edited], 'analyst')
    assert db.get_reports().set_index('row_id').loc[original['row_id']]['Power_Deviation'] == -4.5


def test_new_duplicate_report_id_rolls_back_all_fields():
    original, other = report('Power'), report('Speed')
    edited = dict(original, Report_ID=other['Report_ID'], Vessel_Name='MV CHANGED')
    with pytest.raises(ValueError, match='duplicate'):
        db.save_edits([original], [edited], 'analyst')
    saved = db.get_reports().set_index('row_id').loc[original['row_id']]
    assert saved['Report_ID'] == original['Report_ID']
    assert saved['Vessel_Name'] == original['Vessel_Name']
    assert audit_rows() == []


def test_unrelated_text_edit_preserves_existing_invalid_source_value():
    rows = db.get_reports()
    original = rows[(rows.KPI == 'Speed') & (rows['Speed_%'] < 0)].iloc[0].to_dict()
    db.save_edits([original], [dict(original, Vessel_Name='MV CORRECTED')], 'analyst')
    saved = db.get_reports().set_index('row_id').loc[original['row_id']]
    assert saved['Speed_%'] == original['Speed_%']
    assert {audit['field'] for audit in audit_rows()} == {'Vessel_Name'}


def test_optional_other_kpi_field_can_be_cleared():
    original = report('Power')
    db.save_edits([original], [dict(original, **{'Speed_%': 95})], 'analyst')
    saved = db.get_reports().set_index('row_id', drop=False).loc[original['row_id']].to_dict()
    db.save_edits([saved], [dict(saved, **{'Speed_%': None})], 'analyst')
    assert db.get_reports().set_index('row_id').loc[original['row_id']]['Speed_%'] != 95
