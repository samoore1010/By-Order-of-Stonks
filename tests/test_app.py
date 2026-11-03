import asyncio
import os
import time
import pytest
from fastapi.testclient import TestClient
from backend.app import create_app
from backend.store import Store
from backend.service import Services
from backend.models import BacktestRequest, ResearchRequest, Schedule

HEAD={'X-Stonks-Request':'1'}


@pytest.fixture
def service(tmp_path,monkeypatch):
    monkeypatch.setenv('APP_ENV','development')
    monkeypatch.delenv('APP_PASSWORD',raising=False)
    monkeypatch.delenv('OPENAI_API_KEY',raising=False)
    monkeypatch.delenv('KALSHI_API_KEY_ID',raising=False)
    monkeypatch.delenv('KALSHI_PRIVATE_KEY_PEM',raising=False)
    monkeypatch.setenv('KALSHI_ENV','production')
    return Services(Store('sqlite:///'+str(tmp_path/'test.db')))


@pytest.fixture
def client(service):
    with TestClient(create_app(service)) as c:
        yield c


def test_production_fails_closed(monkeypatch,service):
    monkeypatch.setenv('APP_ENV','production')
    monkeypatch.delenv('SESSION_SECRET',raising=False)
    with pytest.raises(RuntimeError):create_app(service)


def test_authentication_and_logout(monkeypatch,service):
    monkeypatch.setenv('APP_ENV','production')
    monkeypatch.setenv('APP_PASSWORD','correct-password-12345')
    monkeypatch.setenv('SESSION_SECRET','secret-for-testing-only-'*3)
    with TestClient(create_app(service),base_url='https://testserver') as c:
        assert c.get('/api/overview').status_code==401
        assert c.post('/api/login',json={'password':'bad'},headers=HEAD).status_code==401
        assert c.post('/api/login',json={'password':'correct-password-12345'},headers=HEAD).status_code==200
        assert c.get('/api/overview').status_code==200
        assert c.post('/api/logout',headers=HEAD).status_code==200
        assert c.get('/api/overview').status_code==401


def test_csrf_header_and_origin(client):
    assert client.post('/api/strategies',json={'config':{}}).status_code==403
    assert client.post('/api/strategies',json={'config':{}},headers={**HEAD,'Origin':'https://evil.test'}).status_code==403


def test_health_and_frontend(client):
    assert client.get('/healthz').status_code==200
    assert 'By Order of Stonks' in client.get('/').text
    assert client.get('/assets/app.js').status_code==200
    assert client.get('/api/overview').json()['capabilities']['live_execution'] is False


def test_strategy_versioning(client):
    r=client.post('/api/strategies',json={'config':{'name':'Edited'},'parent_id':'strategy-longshot-v1'},headers=HEAD)
    assert r.status_code==200 and r.json()['version']==2
    assert client.get('/api/records/strategy-longshot-v1').json()['config']['name']=='Longshot counterparty'


def test_backtest_job_completes(client):
    r=client.post('/api/backtests',json=BacktestRequest().model_dump(mode='json'),headers=HEAD)
    assert r.status_code==202
    for _ in range(60):
        j=client.get('/api/records/'+r.json()['id']).json()
        if j['status']=='completed':break
        time.sleep(.05)
    assert j['status']=='completed'
    result=client.get('/api/records/'+j['result_id']).json()
    assert result['source']=='synthetic'
    assert client.get('/api/export/'+result['id']+'?format=csv').status_code==200


def test_research_cannot_validate_synthetic(service):
    r=ResearchRequest(question='Does this template survive validation?')
    j=service.enqueue('research',r.model_dump(mode='json'))
    result=service.research(j['id'],j['payload'])
    assert result['status']=='not_validated'
    assert not result['checks'][0]['passed']
    assert result['trials']==4
    assert result['purged_events']>0
    assert len(service.store.get(j['id'])['events'])==5


def test_schedule_does_not_retest_unchanged_data(service):
    service.store.write('setting',Schedule(enabled=True).model_dump(),'schedule')
    service.maybe_schedule()
    n=len(service.store.list('job'))
    old=service.store.get('schedule');old['last_checked']='2020-01-01T00:00:00+00:00'
    service.store.write('setting',old,'schedule')
    service.maybe_schedule()
    assert len(service.store.list('job'))==n


def test_paper_order_idempotency_and_conflict(client):
    request={'client_order_id':'test-order-1234','ticker':'DEMO-1','side':'no','quantity':10,'limit_price':.94,'source':'synthetic','confirm':True}
    r=client.post('/api/paper/orders',json=request,headers=HEAD)
    assert r.status_code==200 and r.json()['filled_quantity']==10
    assert client.post('/api/paper/orders',json=request,headers=HEAD).json()['id']==r.json()['id']
    request['quantity']=11
    assert client.post('/api/paper/orders',json=request,headers=HEAD).status_code==400
    o=client.get('/api/overview').json()
    assert len(o['orders'])==1


def test_paper_sandbox_settlement(client):
    request={'client_order_id':'test-order-1234','ticker':'DEMO-1','side':'no','quantity':10,'limit_price':.94,'source':'synthetic','confirm':True}
    client.post('/api/paper/orders',json=request,headers=HEAD)
    r=client.post('/api/paper/sandbox-settle',json={'ticker':'DEMO-1','outcome':'no'},headers=HEAD)
    assert r.status_code==200 and r.json()['settled']==1
    assert client.post('/api/paper/synthetic/reconcile',json={},headers=HEAD).json()['settled']==0


def test_deployment_requires_explicit_opt_in(client):
    request={'strategy_id':'strategy-longshot-v1','source':'synthetic'}
    assert client.post('/api/deployments',json=request,headers=HEAD).status_code==400
    request['confirm']=True
    assert client.post('/api/deployments',json=request,headers=HEAD).status_code==200


def test_automatic_paper_scan_executes_once(service):
    config=service.store.get('strategy-longshot-v1')['config']
    service.store.write('deployment',{'strategy':config,'source':'synthetic','series':'','enabled':True,'last_scan':None})
    asyncio.run(service.scan_deployments())
    first=len(service.store.list('paper_order'))
    assert first>0
    asyncio.run(service.scan_deployments())
    assert len(service.store.list('paper_order'))==first


def test_live_orders_always_blocked(client,monkeypatch):
    monkeypatch.setenv('LIVE_TRADING_ENABLED','true')
    assert client.post('/api/live/orders',json={},headers=HEAD).status_code==403


def test_local_copilot_does_not_invent_ai(client):
    r=client.post('/api/copilot',json={'message':'Help','context':{},'session_id':'test-session-123'},headers=HEAD)
    assert r.status_code==200 and r.json()['mode']=='local'
    assert 'no language model' in r.json()['text'].lower()


def test_combo_dependence_bounds(client):
    r=client.post('/api/combo/analyze',json={'probabilities':[.6,.7]},headers=HEAD).json()
    assert r['lower_bound']==pytest.approx(.3)
    assert r['upper_bound']==.6
    assert r['independence_scenario']==pytest.approx(.42)
    assert r['executable'] is False


def test_restart_marks_running_jobs_interrupted(service):
    j=service.enqueue('backtest',BacktestRequest().model_dump(mode='json'))
    service.store.write('job',{**j,'status':'running'},j['id'])
    service.initialize()
    assert service.store.get(j['id'])['status']=='interrupted'
