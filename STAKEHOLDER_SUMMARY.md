# To: Head of Data Analytics
## Vessel performance investigation and data correction

### 1. About the web app

I built the Vessel Performance Monitor, a Dash web application that helps analysts investigate vessel Power and Speed KPIs and correct the underlying report data. Vessel, reporting-period and voyage-type filters apply together to two stacked time-series charts and an editable report table. The charts plot Power and Speed percentages over time, with separate colours for records marked "Yes" or "No" by the source anomaly flags.

The app connects visual investigation to report-level correction in one workspace. Analysts can inspect report details, edit source fields and save changes with an audit trail. The current implementation uses local SQLite storage to demonstrate the writeback workflow; governed Databricks storage remains a second-phase action.

### 2. Selection-to-table flow

1. **Filter the reports.** Choose a vessel, reporting period and voyage type (CARGO, BALLAST or Both). Both charts and the table use those filters.
2. **Select chart points.** Use lasso or box selection on either chart. Each point carries an internal row key that links it to its exact source record. Selections from the two charts combine: the table shows records selected in either chart.
3. **Inspect the matching rows.** The table exposes report identifiers, timestamps, vessel and voyage details, baseline information and KPI values. Analysts can sort and filter columns. With no chart points selected, the table shows all reports matching the active filters, including records with missing percentages that cannot appear as plotted points. Double-clicking a chart clears its selection.
4. **Correct and save.** Edit cells, enter an analyst name and click **Save changes**. Successful saves update SQLite, write field-level audit entries and reload the charts and table with selections cleared. Validation failures display an error and prevent the save.

Save before changing filters or selections because reloading the table discards unsaved edits. **Refresh** reloads saved data; **Reset filters** also restores the default vessel, full reporting period and both voyage types, and clears chart selections and table filters.

### 3. Source data and handling inaccuracies

The source CSV contains **1,230 records across three vessels**, covering **1 March to 21 September 2026**, with 615 Power records and 615 Speed records. Each row describes one KPI, so blanks in fields belonging to the other KPI are expected and are preserved.

The source also contains specific data-quality issues:

| Issue | How it is handled |
| --- | --- |
| One missing `Power_%` value for MV PACIFIC PIONEER on 5 May 2026 | Preserved without estimating a replacement. The record remains accessible in the table when no chart points are selected; field validation highlights the missing required value. |
| A `Speed_%` value of -12.0 for MV HORIZON TRADER on 31 March 2026 | Preserved for investigation and highlighted as invalid in the table. New negative percentage edits are rejected. |
| One duplicated `Report_ID`, shared by two rows | Both rows are retained. A unique internal `row_id` keeps selection and correction tied to the intended record. Changes to report IDs must not introduce or retain a duplicate for the edited ID. |

I retained these records for analyst review. The app does not automatically repair existing inaccuracies, and validation focuses on changed fields and affected relationships, allowing unrelated corrections to proceed while existing issues remain visible.

Corrections are checked in the browser and again on the server for required values, numeric limits, dates, identifiers and allowed categories. Related-field checks prevent a baseline start after its end and engine running hours exceeding report duration. When a KPI percentage or its relevant baseline changes, the corresponding deviation is recalculated unless the analyst explicitly edits the deviation too. The 0-250 percentage limits and deviation formulas are implementation assumptions that require confirmation with operations. Source anomaly flags remain unchanged unless an analyst edits them because their business logic was not provided.

Each successful save records the internal row key, report ID, field, old and new values, entered analyst name and UTC timestamp. Updates and audit entries commit together; a failed save rolls back the entire batch. Record-version checks reject stale edits to prevent overwriting another saved correction. The original CSV remains unchanged, and the entered analyst name is not yet an authenticated identity.

### Second-phase actions

1. Confirm KPI baseline formulas, anomaly-flag rules and validation limits with operations.
2. Connect the app to governed Databricks tables with transactional writeback and identity-aware audit logs.
3. Add permissions and an audit-history viewer.
4. Run the existing automated tests in a continuous integration (CI) pipeline.
