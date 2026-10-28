"""SQLite repository; replace this adapter with Delta MERGE in phase two."""
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd
from validation import FIELD_RULES, missing, same_value, validate_field, validate_relationships

ROOT = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv('DB_PATH', str(ROOT / 'vessels.sqlite3')))
CSV_PATH = ROOT / 'data' / 'vessel_kpi_reports.csv'

@contextmanager
def connect():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def initialize():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with connect() as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS reports (
          row_id INTEGER PRIMARY KEY AUTOINCREMENT,
          IMO INTEGER, Vessel_Name TEXT, Report_ID TEXT, To_Timestamp TEXT,
          KPI TEXT, Voyage_Type TEXT, Report_Duration REAL, SP_BSL_Start TEXT,
          SP_BSL_End TEXT, SP_BSL_Reports INTEGER, PWR_BSL_SAM REAL,
          SPD_BSL_SAM REAL, SPD_BSL_OOS REAL, Power_ME REAL,
          "Power_%" REAL, Power_Deviation REAL, "Speed_%" REAL,
          Speed_Deviation REAL, ME_Running_Hours REAL,
          Power_Filter_Flag TEXT, Speed_Filter TEXT, Dual_Fuel_Mode_str TEXT,
          version INTEGER NOT NULL DEFAULT 0)''')
        conn.execute('''CREATE TABLE IF NOT EXISTS audit_log (
          audit_id INTEGER PRIMARY KEY AUTOINCREMENT, row_id INTEGER NOT NULL,
          Report_ID TEXT NOT NULL, field TEXT NOT NULL,
          old_value TEXT, new_value TEXT, changed_by TEXT NOT NULL,
          changed_at TEXT NOT NULL)''')
        if conn.execute('SELECT COUNT(*) FROM reports').fetchone()[0] == 0:
            d = pd.read_csv(CSV_PATH)
            d['To_Timestamp'] = pd.to_datetime(d['To_Timestamp'], format='%Y-%m-%d %I:%M %p').dt.strftime('%Y-%m-%dT%H:%M:%S')
            cols = list(d.columns)
            placeholders = ','.join('?' for _ in cols)
            quoted = ','.join('"'+c+'"' for c in cols)
            rows = [(None if pd.isna(x) else x.item() if hasattr(x,'item') else x) for row in d.itertuples(index=False,name=None) for x in row]
            width=len(cols)
            conn.executemany(f'INSERT INTO reports ({quoted}) VALUES ({placeholders})', [rows[i:i+width] for i in range(0,len(rows),width)])
        conn.commit()


def get_reports():
    with connect() as conn:
        return pd.read_sql_query('SELECT * FROM reports ORDER BY To_Timestamp, row_id', conn)


def save_edits(original_rows, edited_rows, user):
    """Validate, persist, and audit every edited source field in one transaction."""
    if not isinstance(user, str) or not user.strip():
        raise ValueError('Enter an analyst name to save changes.')
    if len(user.strip()) > 120 or any(ord(character) < 32 for character in user.strip()):
        raise ValueError('Analyst name must be at most 120 characters and contain no control characters.')
    baseline = {int(r['row_id']): r for r in original_rows}
    submissions = []
    seen = set()
    for row in edited_rows or []:
        rid = int(row['row_id'])
        if rid not in baseline or rid in seen:
            raise ValueError('Unexpected row ID in submission.')
        seen.add(rid)
        prev = baseline[rid]
        if set(row) - set(FIELD_RULES) - {'row_id', 'version'}:
            raise ValueError('Unexpected field in submission.')
        if row.get('version', prev['version']) != prev['version']:
            raise ValueError('The internal record version cannot be edited.')
        changes = {field: row[field] for field in FIELD_RULES
                   if field in row and not same_value(prev.get(field), row[field])}
        if changes:
            submissions.append((rid, prev, changes))
    if not submissions:
        return 0
    with connect() as conn:
        try:
            conn.execute('BEGIN IMMEDIATE')
            count = 0
            changed_ids = []
            for rid, prev, changes in submissions:
                current = conn.execute('SELECT * FROM reports WHERE row_id=?', (rid,)).fetchone()
                if current is None or current['version'] != int(prev['version']):
                    raise ValueError(f'Row {rid} changed since it was loaded. Refresh before editing.')
                candidate = dict(current)
                candidate.update(changes)
                try:
                    for field, value in changes.items():
                        candidate[field] = validate_field(field, value, candidate)
                    validate_relationships(candidate, set(changes))
                    for kind, base in [('Power', 'PWR_BSL_SAM'), ('Speed', 'SPD_BSL_OOS')]:
                        percentage, deviation = f'{kind}_%', f'{kind}_Deviation'
                        if {percentage, base} & changes.keys() and deviation not in changes:
                            if candidate['KPI'] == kind or not (missing(candidate[percentage]) or missing(candidate[base])):
                                if missing(candidate[base]) or missing(candidate[percentage]):
                                    raise ValueError(f'{percentage} and {base} are required to calculate {deviation}.')
                                candidate[deviation] = validate_field(
                                    deviation, round(float(candidate[percentage]) - float(candidate[base]), 1), candidate)
                except (ValueError, TypeError, OverflowError) as exc:
                    raise ValueError(f'Row {rid}: {exc}') from None
                updates = {field: candidate[field] for field in FIELD_RULES
                           if not same_value(current[field], candidate[field])}
                if not updates:
                    continue
                assignments = ', '.join(f'"{field}"=?' for field in updates)
                conn.execute(f'UPDATE reports SET {assignments}, version=version+1 WHERE row_id=?',
                             [*updates.values(), rid])
                now = datetime.now(timezone.utc).isoformat()
                for field, value in updates.items():
                    conn.execute('INSERT INTO audit_log (row_id,Report_ID,field,old_value,new_value,changed_by,changed_at) VALUES (?,?,?,?,?,?,?)',
                                 (rid, current['Report_ID'], field,
                                  None if missing(current[field]) else str(current[field]),
                                  None if missing(value) else str(value), user.strip(), now))
                if 'Report_ID' in updates:
                    changed_ids.append(candidate['Report_ID'])
                count += 1
            for report_id in changed_ids:
                if conn.execute('SELECT COUNT(*) FROM reports WHERE Report_ID=?', (report_id,)).fetchone()[0] > 1:
                    raise ValueError('Report_ID must not duplicate another report. Existing source duplicates are preserved until corrected.')
            conn.commit()
            return count
        except Exception:
            conn.rollback()
            raise
