import os
bind=f"0.0.0.0:{os.getenv('DATABRICKS_APP_PORT',os.getenv('PORT','8000'))}"
workers=1  # SQLite demo; avoid concurrent write complexity
threads=4
timeout=120
