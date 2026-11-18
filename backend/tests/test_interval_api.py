import json
import random

import fakeredis
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

import redis as redis_module

_FAKE = fakeredis.FakeRedis()
redis_module.Redis.from_url = classmethod(lambda cls, *a, **k: _FAKE)

from src.config.database import Base, Session, engine  # noqa: E402
from src.main import app  # noqa: E402
from src.models.observation import Observation  # noqa: E402
from src.models.run import Run  # noqa: E402
from src.models.study import Study  # noqa: E402
from src.models.user import User  # noqa: E402
from src.services.algorithm import calculate  # noqa: E402
from src.utils.security import hash_password  # noqa: E402


@pytest.fixture(scope='module')
def client():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with Session() as db:
        for role in ('admin', 'analyst', 'viewer'):
            db.add(User(email=role + '@demo.local', role=role,
                        password_hash=hash_password('Research2026!')))
        db.commit()
    _FAKE.flushall()
    with TestClient(app) as c:
        yield c


def login(client, role):
    r = client.post('/auth/login', json={'email': role + '@demo.local', 'password': 'Research2026!'})
    assert r.status_code == 200, r.text
    return {'Authorization': 'Bearer ' + r.json()['token']}


def make_study(client, headers, name):
    r = client.post('/studies', json={'name': name, 'source_filename': 'lab.csv'}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()['id']


def add_rows(client, headers, study_id, lows, highs, porosity):
    for i, (lo, hi, p) in enumerate(zip(lows, highs, porosity)):
        r = client.post(f'/studies/{study_id}/observations', headers=headers, json={
            'source_key': f'R{i:03d}',
            'values': {'porosity': p, 'absorption': {'low': lo, 'high': hi}},
        })
        assert r.status_code == 200, r.text


def run_job(run_id):
    """Mimic the standalone worker for one queued interval job."""
    with Session() as db:
        run = db.get(Run, run_id)
        run.status = 'running'; db.commit()
        result = calculate(run.snapshot, run.parameters)
        result['input_sha256'] = run.checksum
        run.result = result; run.status = 'completed'; db.commit()


def test_interval_run_end_to_end_and_bounds_visible(client):
    analyst = login(client, 'analyst')
    sid = make_study(client, analyst, '区间批次 A')
    lows = [0.0, 1.0, 2.0, 3.0, 4.0, 5.0]
    highs = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
    add_rows(client, analyst, sid, lows, highs, [6, 5, 4, 3, 2, 1])
    r = client.post('/runs', headers=analyst, json={
        'study_id': sid, 'name': '开区间研究 A',
        'parameters': {'mode': 'interval', 'overlap_capacity': 8},
    })
    assert r.status_code == 200, r.text
    rid = r.json()['id']
    pending = client.get(f'/runs/{rid}', headers=analyst).json()
    assert pending['status'] == 'queued' and pending['result'] is None
    run_job(rid)
    done = client.get(f'/runs/{rid}', headers=analyst).json()
    assert done['status'] == 'completed'
    bounds = done['result']['bounds']
    assert bounds['lower']['rho'] == pytest.approx(-1.0)
    assert bounds['upper']['rho'] == pytest.approx(-1.0)
    for side in ('lower', 'upper'):
        assert len(bounds[side]['values']) == 6
        assert len(set(bounds[side]['values'])) == 6


def test_overlap_over_capacity_rejected_before_queue(client):
    analyst = login(client, 'analyst')
    sid = make_study(client, analyst, '超容量批次')
    n = 40
    add_rows(client, analyst, sid, [0.0] * n, [1.0] * n, [float(i) for i in range(n)])
    before = len(client.get('/runs', headers=analyst).json())
    depth = _FAKE.llen('analysis-queue')
    r = client.post('/runs', headers=analyst, json={
        'study_id': sid, 'name': '应被拒绝',
        'parameters': {'mode': 'interval', 'overlap_capacity': 8},
    })
    assert r.status_code == 422
    assert '超过容量' in r.json()['detail']
    assert len(client.get('/runs', headers=analyst).json()) == before
    assert _FAKE.llen('analysis-queue') == depth
    with Session() as db:
        assert db.scalar(select(Run).where(Run.name == '应被拒绝')) is None


def test_upstream_edits_do_not_change_frozen_interval_input(client):
    analyst = login(client, 'analyst')
    sid = make_study(client, analyst, '并发修订批次')
    lows = [0.0, 1.0, 2.0, 3.0, 4.0, 5.0]
    highs = [0.9, 1.9, 2.9, 3.9, 4.9, 5.9]
    add_rows(client, analyst, sid, lows, highs, [1, 2, 3, 4, 5, 6])
    r = client.post('/runs', headers=analyst, json={
        'study_id': sid, 'name': '冻结后修订',
        'parameters': {'mode': 'interval', 'overlap_capacity': 8},
    })
    rid = r.json()['id']
    frozen = client.get(f'/runs/{rid}', headers=analyst).json()['snapshot']
    # Concurrent update of every observation after the run was queued.
    with Session() as db:
        rows = list(db.scalars(select(Observation).where(Observation.study_id == sid)))
        for row in rows:
            row.values = {'porosity': 99.0, 'absorption': {'low': 90.0, 'high': 95.0}}
        db.commit()
    run_job(rid)
    done = client.get(f'/runs/{rid}', headers=analyst).json()
    assert done['status'] == 'completed'
    assert done['snapshot'] == frozen
    assert done['result']['bounds']['max_overlap'] == 1
    # Recomputing from the frozen snapshot reproduces the stored bounds.
    again = calculate(frozen, {'mode': 'interval', 'overlap_capacity': 8})
    assert again['bounds']['lower']['rho'] == pytest.approx(done['result']['bounds']['lower']['rho'])
    assert again['bounds']['upper']['rho'] == pytest.approx(done['result']['bounds']['upper']['rho'])


def test_incomplete_interval_result_is_not_shown(client):
    analyst = login(client, 'analyst')
    sid = make_study(client, analyst, '不完整结果批次')
    add_rows(client, analyst, sid, [0.0, 1.0, 2.0, 3.0, 4.0, 5.0],
             [1.0, 2.0, 3.0, 4.0, 5.0, 6.0], [1, 2, 3, 4, 5, 6])
    rid = client.post('/runs', headers=analyst, json={
        'study_id': sid, 'name': '缺上界',
        'parameters': {'mode': 'interval', 'overlap_capacity': 8},
    }).json()['id']
    with Session() as db:
        run = db.get(Run, rid)
        run.status = 'completed'
        run.result = {'mode': 'interval', 'bounds': {'lower': {'rho': -1, 'rho_recomputed': -1,
                      'values': ['1'] * 6, 'positions': [1, 2, 3, 4, 5, 6]}},
                      'metrics': {}}
        db.commit()
    got = client.get(f'/runs/{rid}', headers=analyst).json()
    assert got['status'] == 'failed'
    assert got['result'] is None
    assert '未展示' in got['error']
    assert client.get(f'/runs/{rid}/export', headers=analyst).status_code == 409


def test_viewer_cannot_queue_interval_run(client):
    viewer = login(client, 'viewer')
    assert client.post('/runs', headers=viewer, json={
        'study_id': 1, 'name': '观察员禁止',
        'parameters': {'mode': 'interval'},
    }).status_code == 403


def test_schema_incompatible_row_is_rejected(client):
    analyst = login(client, 'analyst')
    r = client.post('/studies/1/observations', headers=analyst, json={
        'source_key': 'BAD-1', 'values': {'porosity': 1.0, 'absorption': 2.0}})
    assert r.status_code == 200  # exact-value row is still valid input
    r = client.post('/studies/1/observations', headers=analyst, json={
        'source_key': 'BAD-2', 'values': {'porosity': 1.0, 'absorption': {'low': 3.0, 'high': 2.0}}})
    assert r.status_code == 422
