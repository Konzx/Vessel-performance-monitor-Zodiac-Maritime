# Vessel Performance Monitor

Dash dashboard for Power/Speed analysis and audited report editing.

## Preview

<p align="center">
  <a href="docs/images/dashboard-preview.png">
    <img src="docs/images/dashboard-preview.png" alt="Vessel Performance Monitor showing vessel filters, Power and Speed charts, and the editable report table" width="640">
  </a>
</p>

Click the preview to view the full-size screenshot.

## Run

Python 3.11/3.12, Windows PowerShell:

```powershell
python -m venv .venv312
.\.venv312\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python app.py
```

Open http://localhost:8000. The existing `.venv312` is ready to use.

Linux/macOS: activate with `source .venv312/bin/activate`, then run the command from `app.yaml`:

```bash
gunicorn --config gunicorn_conf.py app:server
```

## Use

- Vessel/date/voyage filters apply together. Box/lasso selections combine; no selection shows all matching reports.
- Edit cells, enter your name, and click **Save changes**.
- **Refresh** discards edits; **Reset filters** restores defaults and clears selections/table filters. Save before changing filters or selections.

## Notes

- **Storage:** `vessels.sqlite3` holds reports and `audit_log` (report ID, field, old/new values, analyst, UTC timestamp). Saves are atomic; the CSV stays unchanged.
- **Validation:** See `validation.py`. Percentage limits (0-250) and deviation formulas are assumptions. Expected KPI blanks and source anomalies are preserved until edited; duplicate IDs use internal row keys. Explicit deviation overrides are allowed; flags are edited manually.
- **Databricks:** `app.yaml` defines Gunicorn/environment settings; `gunicorn_conf.py` uses the injected `DATABRICKS_APP_PORT`. This is a stub, with local SQLite demo storage. Next: authenticated users, durable storage, confirmed business rules.

**Tests:** `python -m pytest -q` uses temporary databases. Browser tests require Chrome and `RUN_BROWSER_TESTS=1`.
