"""Zodiac vessel KPI exercise: graph selection -> editable report -> audited save."""
import os
import pandas as pd
import plotly.graph_objects as go
from dash import Dash, dcc, html, Input, Output, State, ctx, no_update
import dash_ag_grid as dag
from database import initialize, get_reports, save_edits
from validation import FIELD_RULES

initialize()
app = Dash(__name__, title='Vessel Performance Monitor')
server = app.server

DATA = get_reports()
vessels = sorted(DATA['Vessel_Name'].unique())
start_date=DATA['To_Timestamp'].min()[:10]
end_date=DATA['To_Timestamp'].max()[:10]

app.layout = html.Main([
    html.Div([
        html.A([html.Img(src=app.get_asset_url('zodiac/logo.png'),alt='Zodiac Maritime',className='brand-logo'),
                html.Span('Zodiac Maritime')],href='#top',className='brand'),
        html.Nav([html.A('Performance',href='#performance'),html.A('Report details',href='#reports')],className='workspace-nav'),
        html.Span('Vessel operations', className='workspace-label'),
    ], className='topbar'),
    html.Header([
        html.Div('ZODIAC MARITIME / OPERATIONS', className='eyebrow'),
        html.H1('Vessel Performance Monitor'),
        html.P('Performance at sea. Clarity on shore.'),
    ], className='page-header'),
    html.Section([
        html.Div([html.H2('Filter reports'),
                  html.Button('Reset filters',id='reset-filters',n_clicks=0,
                              title='Restore the default vessel, full reporting period and both voyage types. Discard unsaved edits.',
                              className='button button-secondary reset-button')], className='filter-heading'),
        html.Div([
            html.Div([html.Label('Vessel', htmlFor='vessel'), dcc.Dropdown(vessels, vessels[0], id='vessel', clearable=False)]),
            html.Div([html.Label('Reporting period'), dcc.DatePickerRange(id='dates', start_date=start_date,end_date=end_date,
                       display_format='DD MMM YYYY', minimum_nights=0)], className='date-filter'),
            html.Div([html.Label('Voyage type', htmlFor='voyage'), dcc.Dropdown(['Both','CARGO','BALLAST'],'Both',id='voyage',clearable=False)]),
        ], className='filters'),
    ], className='filter-panel panel'),
    html.Div([
        html.Section([
            html.Div([html.Div([html.Span('01', className='chart-number'), html.Div([
                html.H2('Power performance')])]),
                html.Span('POWER %', className='chart-tag')], className='chart-heading'),
            dcc.Graph(id='power-chart', responsive=True, config={'displayModeBar':True,'displaylogo':False}, style={'height':'370px'}),
        ], className='panel chart-panel'),
        html.Section([
            html.Div([html.Div([html.Span('02', className='chart-number'), html.Div([
                html.H2('Speed performance')])]),
                html.Span('SPEED %', className='chart-tag')], className='chart-heading'),
            dcc.Graph(id='speed-chart', responsive=True, config={'displayModeBar':True,'displaylogo':False}, style={'height':'370px'}),
        ], className='panel chart-panel'),
    ], id='performance',className='charts'),
    html.Section([
        html.Div(html.H2('Selected report details'), className='detail-heading'),
        html.Ul([
            html.Li('Select points to inspect; double-click to clear.'),
            html.Li('Click a cell to edit. Save before changing filters.'),
            html.Li('Refresh or reset discards unsaved edits.'),
        ], className='instructions'),
        html.Div([
            html.Div([html.Label('Analyst name', htmlFor='analyst'), dcc.Input(id='analyst',value='',placeholder='Enter your name',
                       required=True,debounce=True,maxLength=120)], className='analyst-field'),
            html.Div([html.Button('Refresh',id='refresh',n_clicks=0,className='button button-secondary'),
                      html.Button('Save changes',id='save',n_clicks=0,className='button button-primary')],className='action-buttons'),
        ], className='actions'),
        html.Div(id='message',role='status',className='save-message'),
        html.Div(id='validation-message',role='alert',className='validation-message'),
        dag.AgGrid(id='grid',columnDefs=[],rowData=[],
                   defaultColDef={'sortable':True,'filter':True,'resizable':True,'editable':True,'wrapHeaderText':True,'autoHeaderHeight':True},
                   getRowId="'report-' + params.data.row_id",
                   dashGridOptions={'pagination':True,'paginationPageSize':10,'paginationPageSizeSelector':[10,25,50],
                                    'rowSelection':{'mode':'multiRow'},'rowHeight':42,
                                    'singleClickEdit':True,'stopEditingWhenCellsLoseFocus':True},
                   className='ag-theme-alpine report-grid',style={'height':'530px','width':'100%'}),
        html.P('Saved changes are recorded in the audit history.',className='table-footnote'),
    ], id='reports',className='panel details-panel'),
    html.Footer([
        html.Div([html.Img(src=app.get_asset_url('zodiac/wordmark.svg'),alt='Zodiac Maritime',className='footer-logo'),
                  html.Div([html.P('Vessel performance'),html.A('Back to top ↑',href='#top')])],className='footer-main'),
        html.Div([html.Span('Zodiac Maritime'),html.Span('Operations workspace')],className='footer-bottom'),
    ],className='page-footer'),
    dcc.Store(id='snapshot'),
    dcc.Store(id='revision',data=0),
    dcc.Store(id='filter-reset',data=0),
],id='top',className='container')


def filtered(vessel,start,end,voyage):
    d=get_reports()
    d=d[d.Vessel_Name==vessel]
    if start: d=d[d.To_Timestamp.str[:10]>=start[:10]]
    if end: d=d[d.To_Timestamp.str[:10]<=end[:10]]
    if voyage!='Both': d=d[d.Voyage_Type==voyage]
    return d


@app.callback(Output('vessel','value'),Output('dates','start_date'),Output('dates','end_date'),
              Output('voyage','value'),Output('grid','filterModel'),Output('filter-reset','data'),
              Output('validation-message','children'),
              Input('reset-filters','n_clicks'),prevent_initial_call=True)
def reset_filters(clicks):
    data=get_reports()
    names=sorted(data.Vessel_Name.dropna().unique())
    first=data.To_Timestamp.min()[:10] if not data.empty else None
    last=data.To_Timestamp.max()[:10] if not data.empty else None
    return names[0] if names else None,first,last,'Both',{},clicks,''


def chart(df,kind,revision=None):
    col=f'{kind}_%'
    flag='Power_Filter_Flag' if kind=='Power' else 'Speed_Filter'
    fig=go.Figure()
    part=df[df.KPI==kind]
    for flagged,color in [('No','#00215c'),('Yes','#ff4819')]:
        p=part[part[flag]==flagged]
        fig.add_trace(go.Scatter(x=p.To_Timestamp,y=p[col],mode='markers',
                      name='Flagged' if flagged=='Yes' else 'Not flagged',
                      # Plain lists keep row IDs accessible to Dash's selection event serializer.
                      marker={'color':color,'size':7,'opacity':0.8,'line':{'color':'white','width':0.5}},customdata=p[['row_id']].to_numpy().tolist(),
                      hovertemplate='Report time: %{x}<br>Value: %{y:.1f}%<extra></extra>'))
    fig.update_layout(dragmode='lasso',template='plotly_white',
                      font={'family':'Arial, sans-serif','color':'#61708b','size':12},
                      xaxis={'title':None,'gridcolor':'#edf0f5','tickformat':'%d %b','zeroline':False},
                      yaxis={'title':f'{kind} %','gridcolor':'#edf0f5','ticksuffix':'%','zeroline':False},
                      uirevision=revision,selectionrevision=revision,
                      legend={'orientation':'h','x':1,'xanchor':'right','y':1.02,'yanchor':'bottom'},
                      hoverlabel={'bgcolor':'#00215c','font_color':'white'},
                      margin={'t':70,'b':40,'l':65,'r':25},paper_bgcolor='white',plot_bgcolor='white')
    if part.empty:
        fig.add_annotation(text='No reports match these filters',xref='paper',yref='paper',x=0.5,y=0.5,showarrow=False)
    return fig


def selected_ids(selection):
    return {int(p['customdata'][0]) for p in (selection or {}).get('points',[]) if p.get('customdata')}


def clean_records(df):
    # JSON safe records; don't cast nullable percentages to strings
    return df.astype(object).where(pd.notna(df),None).to_dict('records')


def columns_for():
    shared=['row_id','Report_ID','To_Timestamp','IMO','Vessel_Name','KPI','Voyage_Type',
            'Report_Duration','SP_BSL_Start','SP_BSL_End','SP_BSL_Reports',
            'ME_Running_Hours','Dual_Fuel_Mode_str']
    power=['PWR_BSL_SAM','Power_ME','Power_%','Power_Deviation','Power_Filter_Flag']
    speed=['SPD_BSL_SAM','SPD_BSL_OOS','Speed_%','Speed_Deviation','Speed_Filter']
    cols=shared+power+speed
    result=[]
    for name in cols:
        c={'field':name,'minWidth':150,'width':170}
        if name=='row_id':
            result.append(dict(c,hide=True,editable=False))
            continue
        rule=FIELD_RULES[name]
        c.update({'editable':True,'context':{'validation':rule},
                  'valueSetter':{'function':'setReportValue(params)'},
                  'cellDataType':'number' if rule['type'] in ('number','integer') else 'text',
                  'headerTooltip':field_help(name,rule),
                  'tooltipValueGetter':{'function':'reportTooltip(params)'},
                  'cellStyle':{'function':'reportCellStyle(params)'}})
        if rule['type'] in ('number','integer'):
            params={key:rule[key] for key in ('min','max') if key in rule}
            if rule['type']=='integer': params.update(step=1)
            c.update(cellEditor='agNumberCellEditor',cellEditorParams=params)
        elif rule['type']=='enum':
            c.update(cellEditor='agSelectCellEditor',cellEditorParams={'values':['']+rule['values'] if rule.get('kpi') else rule['values']})
        else:
            c.update(cellEditor='agTextCellEditor',cellEditorParams={'maxLength':rule.get('maxLength',80)})
        if name=='Report_ID': c['width']=315
        if name=='Vessel_Name': c['width']=230
        if rule['type']=='datetime': c['width']=210
        if name=='Dual_Fuel_Mode_str': c['width']=230
        if name in ['Power_Deviation','Speed_Deviation']:
            c['cellStyle']={'function':'reportCellStyle(params)'}
        result.append(c)
    return result


def field_help(name,rule):
    if rule['type']=='datetime': return 'Date/time: YYYY-MM-DD HH:mm. Baseline start must be on or before baseline end.'
    if rule['type']=='enum': return 'Choose '+', '.join(rule['values'])+'.'
    if rule['type']=='uuid': return 'A valid UUID. New report IDs must be unique.'
    if rule['type']=='text': return f"Required text, up to {rule['maxLength']} characters."
    description='Whole number' if rule['type']=='integer' else 'Finite number'
    if 'min' in rule: description+=f"; {'greater than' if rule.get('exclusiveMin') else 'minimum'} {rule['min']}"
    if 'max' in rule: description+=f"; maximum {rule['max']}"
    return description+'.'


@app.callback(Output('power-chart','figure'),Output('speed-chart','figure'),
              Output('vessel','options'),
              Input('vessel','value'),Input('dates','start_date'),Input('dates','end_date'),
              Input('voyage','value'),Input('revision','data'),Input('filter-reset','data'))
def render_charts(vessel,start,end,voyage,revision_number,reset_number):
    d=filtered(vessel,start,end,voyage)
    revision=f'{vessel}|{start}|{end}|{voyage}|{revision_number}|{reset_number}'
    options=sorted(set(get_reports().Vessel_Name.dropna())|{vessel})
    return chart(d,'Power',revision),chart(d,'Speed',revision),options


@app.callback(Output('grid','rowData'),Output('grid','columnDefs'),Output('snapshot','data'),
              Output('power-chart','selectedData'),Output('speed-chart','selectedData'),
              Input('vessel','value'),Input('dates','start_date'),Input('dates','end_date'),
              Input('voyage','value'),Input('power-chart','selectedData'),
              Input('speed-chart','selectedData'),Input('revision','data'),Input('filter-reset','data'))
def render_table(vessel,start,end,voyage,power_selection,speed_selection,_,reset_number):
    d=filtered(vessel,start,end,voyage)
    reset=bool({'vessel','dates','voyage','revision','filter-reset'} & set(ctx.triggered_prop_ids.values()))
    if reset:
        power_selection=speed_selection=None
    # OR semantics across charts, rather than intersecting disjoint KPI rows
    ids=selected_ids(power_selection)|selected_ids(speed_selection)
    if ids:d=d[d.row_id.isin(ids)]
    records=clean_records(d)
    return records,columns_for(),records,None if reset else no_update,None if reset else no_update


@app.callback(Output('message','children'),Output('revision','data'),
              Input('save','n_clicks'),Input('refresh','n_clicks'),
              State('grid','rowData'),State('snapshot','data'),State('analyst','value'),State('revision','data'),
              prevent_initial_call=True)
def handle_save(_,__,edited,original,user,rev):
    if ctx.triggered_id=='refresh':return html.Div('Reports refreshed; unsaved edits discarded.',className='notice notice-info'),(rev or 0)+1
    try:
        n=save_edits(original or [],edited or [],user)
        return html.Div(f'Saved changes to {n} report(s). Audit history updated.',className='notice notice-success'),(rev or 0)+1
    except (ValueError,TypeError) as exc:
        return html.Div(f'Not saved: {exc}',className='notice notice-error'),no_update

if __name__=='__main__':
    app.run(debug=True,dev_tools_ui=False,host='0.0.0.0',port=int(os.getenv('DATABRICKS_APP_PORT',os.getenv('PORT','8000'))))
