"""Independent Python processes serialize writes through PostgreSQL, not RAM."""
import os
import subprocess
import sys
from pathlib import Path
from sqlalchemy import text
from app import db, migrate

PROGRAM = '''
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app import session
from app.production_unit import ProductionUnitMiddleware
store = session.Store(dict, key="test.concurrent.process")
app = FastAPI()
@app.post("/v1/counter")
def increment():
    row = store.for_current()
    row["count"] = row.get("count", 0) + 1
    return row
app.add_middleware(ProductionUnitMiddleware, enabled=lambda: True)
client = TestClient(app)
for _ in range(10):
    response = client.post("/v1/counter")
    assert response.status_code == 200, response.text
'''


def test_two_processes_do_not_lose_updates(pg_url, pg_conn):
    migrate.apply(pg_conn)
    pg_conn.commit()
    environment = dict(os.environ, DATABASE_URL=pg_url, PYTHONPATH=str(Path(__file__).resolve().parents[1]), AUTH_MODE="off", ENV="test")
    processes = [subprocess.Popen([sys.executable, "-c", PROGRAM], env=environment,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(2)]
    try:
        for process in processes:
            stdout, stderr = process.communicate(timeout=30)
            assert process.returncode == 0, stdout + stderr
        from app import business_records
        state, found = business_records.load(pg_conn, "test.concurrent.process")
        assert found and state["count"] == 20
    finally:
        for process in processes:
            if process.poll() is None: process.kill()
