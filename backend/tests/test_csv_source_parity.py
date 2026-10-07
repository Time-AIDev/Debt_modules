"""Equal source provenance must yield identical CSV bytes across read adapters."""
import copy
import csv
import io
import json

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routers import today


def test_csv_keeps_every_value_and_row_order_when_source_mapping_order_changes(monkeypatch):
    client = TestClient(app)
    response = client.get('/v1/workbook')
    assert response.status_code == 200
    data = response.json()
    source = {'identity': 'ODOO', 'snapshot': {'captured_on': '2026-09-14', 'cached': False},
              'note': 'ข้อมูลต้นทาง', 'unknown': None}
    left, right = copy.deepcopy(data), copy.deepcopy(data)
    for row in left['rows']:
        row['data_source'] = source
    reversed_source = dict(reversed(list(source.items())))
    reversed_source['snapshot'] = dict(reversed(list(source['snapshot'].items())))
    for row in right['rows']:
        row['data_source'] = reversed_source
    monkeypatch.setattr(today, '_workbook', lambda *args, **kwargs: left)
    first = client.get('/v1/workbook:export')
    monkeypatch.setattr(today, '_workbook', lambda *args, **kwargs: right)
    second = client.get('/v1/workbook:export')
    assert first.status_code == second.status_code == 200
    assert first.content == second.content
    rows = list(csv.DictReader(io.StringIO(first.content.decode('utf-8-sig'))))
    assert len(rows) == len(data['rows'])
    assert all(json.loads(row['data_source']) == source for row in rows)
    assert [row['volt_id'] for row in rows] == [row['case']['volt_id'] or '' for row in data['rows']]
    baseline = list(csv.reader(io.StringIO(today._csv_body(data))))
    changed = list(csv.reader(io.StringIO(first.content.decode('utf-8-sig'))))
    source_column = baseline[0].index('data_source')
    assert baseline[0] == changed[0]
    assert [[value for i, value in enumerate(row) if i != source_column] for row in baseline[1:]] == [
        [value for i, value in enumerate(row) if i != source_column] for row in changed[1:]]


@pytest.mark.parametrize('value', ['ODOO', 'SHEET', '', None])
def test_existing_scalar_source_cells_are_unchanged(value):
    assert today._data_source_cell(value) == value
