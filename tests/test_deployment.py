"""Verify runtime port binding without requiring Gunicorn on Windows."""
from pathlib import Path
import runpy

import pytest


@pytest.mark.parametrize('databricks_port,local_port,expected', [
    (None, None, '8000'),
    (None, '8123', '8123'),
    ('9943', None, '9943'),
    ('9943', '8123', '9943'),
])
def test_gunicorn_uses_injected_port(monkeypatch, databricks_port, local_port, expected):
    for name, value in [('DATABRICKS_APP_PORT', databricks_port), ('PORT', local_port)]:
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)
    config = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'gunicorn_conf.py'))
    assert config['bind'] == f'0.0.0.0:{expected}'
