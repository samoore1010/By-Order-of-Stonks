import asyncio
import base64
import json
import os
import pytest
import httpx
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import ed25519, rsa, padding
from backend.providers import Kalshi, normalize_market, parse_book
from backend.models import ImportRequest, ResearchRequest
from backend.store import Store
from backend.service import Services
from backend import copilot, agents


@pytest.mark.parametrize('kind',['rsa','ed25519'])
def test_signed_get_headers(monkeypatch,kind):
    key=ed25519.Ed25519PrivateKey.generate() if kind=='ed25519' else rsa.generate_private_key(public_exponent=65537,key_size=2048)
    pem=key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()).decode()
    monkeypatch.setenv('KALSHI_API_KEY_ID','test-key-id');monkeypatch.setenv('KALSHI_PRIVATE_KEY_PEM',pem)
    client=Kalshi();h=client.headers('/markets?limit=20')
    message=(h['KALSHI-ACCESS-TIMESTAMP']+'GET/trade-api/v2/markets').encode()
    sig=base64.b64decode(h['KALSHI-ACCESS-SIGNATURE'])
    if kind=='ed25519':key.public_key().verify(sig,message)
    else:key.public_key().verify(sig,message,padding.PSS(mgf=padding.MGF1(hashes.SHA256()),salt_length=padding.PSS.DIGEST_LENGTH),hashes.SHA256())


def test_fixed_point_market_prices():
    m=normalize_market({'ticker':'TEST','notional_value_dollars':'1.0000','yes_bid_dollars':'0.1234','yes_ask_dollars':'0.1500','volume_fp':'12.5'})
    assert m['binary_supported'] and m['yes_bid']==.1234 and m['volume']==12.5


@pytest.mark.parametrize('q',['nan','inf','-inf'])
def test_nonfinite_book_size_rejected(q):
    with pytest.raises(ValueError): parse_book({'orderbook_fp':{'yes_dollars':[['.50',q]]}})


def test_null_orderbook_sides():
    assert parse_book({'orderbook_fp':{'yes_dollars':None,'no_dollars':None}})['yes']==[]


def test_historical_import_uses_archive_and_candle_end(monkeypatch):
    monkeypatch.delenv('KALSHI_API_KEY_ID',raising=False)
    k=Kalshi();seen=[]
    async def get(path,params=None):
        seen.append(path)
        if path=='/historical/cutoff':return {'market_settled_ts':'2026-01-01T00:00:00Z'}
        if path=='/series/TEST':return {'series':{'category':'Weather'}}
        if path=='/markets/TEST-EVENT-MARKET':raise ValueError('404 archived')
        if path=='/historical/markets/TEST-EVENT-MARKET':return {'market':{'ticker':'TEST-EVENT-MARKET','event_ticker':'TEST-EVENT',
            'notional_value_dollars':'1.0000','status':'settled','result':'no','settlement_ts':'2025-01-02T00:00:00Z'}}
        return {'candlesticks':[{'end_period_ts':ts,'yes_bid':{'close_dollars':'.09'},'yes_ask':{'close_dollars':'.11'},'volume_fp':'100'} for ts in (1735689600,1735693200)]}
    k.get=get
    result=asyncio.run(k.import_history(ImportRequest(series='TEST',tickers=['TEST-EVENT-MARKET'],start='2025-01-01T00:00:00Z',end='2025-01-02T00:00:00Z')))
    assert '/historical/markets/TEST-EVENT-MARKET/candlesticks' in seen
    assert len(result['rows'])==2 and result['source']=='kalshi_candles'
    assert result['rows'][0]['available_at']=='2025-01-01T00:00:00Z'


def service(monkeypatch,tmp_path):
    monkeypatch.delenv('KALSHI_API_KEY_ID',raising=False)
    monkeypatch.delenv('KALSHI_PRIVATE_KEY_PEM',raising=False)
    monkeypatch.setenv('OPENAI_API_KEY','fake-test-value-not-a-real-key')
    monkeypatch.setenv('OPENAI_MAX_CALLS_PER_DAY','40')
    return Services(Store('sqlite:///'+str(tmp_path/'test.db')))


def mock_model(monkeypatch,handler):
    original=httpx.AsyncClient
    transport=httpx.MockTransport(handler)
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kw: original(transport=transport,**kw))


def test_copilot_tool_loop_queues_real_job(monkeypatch,tmp_path):
    s=service(monkeypatch,tmp_path);calls=[]
    def handler(request):
        data=json.loads(request.content);calls.append(data)
        if len(calls)==1:
            return httpx.Response(200,json={'output':[{'type':'function_call','name':'run_backtest','call_id':'call-1',
                'arguments':json.dumps({'strategy_id':'strategy-longshot-v1','dataset_id':'synthetic-v1','capital':5000})}]})
        assert any(i.get('type')=='function_call_output' for i in data['input'])
        return httpx.Response(200,json={'output':[{'type':'message','content':[{'type':'output_text','text':'Backtest queued, not yet completed.'}]}]})
    mock_model(monkeypatch,handler)
    r=asyncio.run(copilot.chat(s,'Run a backtest',{},'testing-session'))
    assert r['mode']=='model' and len(s.store.list('job'))==1
    assert len(s.store.list('model_call'))==2
    assert not any(t['name']=='execute_order' for t in calls[0]['tools'])


def test_llm_daily_budget_fails_closed(monkeypatch,tmp_path):
    s=service(monkeypatch,tmp_path);monkeypatch.setenv('OPENAI_MAX_CALLS_PER_DAY','0')
    with pytest.raises(ValueError,match='budget'):
        asyncio.run(copilot.chat(s,'Hello',{},'testing-session'))


def test_director_plan_does_not_receive_outcomes(monkeypatch,tmp_path):
    s=service(monkeypatch,tmp_path)
    payload=ResearchRequest(question='Test lower-priced NO contracts').model_dump(mode='json')
    j=s.enqueue('research',payload)
    def handler(request):
        data=json.loads(request.content)
        evidence=json.loads(data['input'])
        assert 'rows' not in evidence and 'partitions' not in evidence
        text=json.dumps({'family':'longshot','side':'no','min_probability':.02,'max_probability':.08,'min_edge':.04,'rationale':'Evaluate a narrower price band.'})
        return httpx.Response(200,json={'output':[{'type':'message','content':[{'type':'output_text','text':text}]}]})
    mock_model(monkeypatch,handler)
    result=asyncio.run(agents.plan(s,j))
    assert result['strategy']['max_probability']==.08
    assert s.store.get(j['id'])['original_payload']==payload


def test_qualitative_review_cannot_override_gate(monkeypatch,tmp_path):
    s=service(monkeypatch,tmp_path)
    payload=ResearchRequest(question='Test this strategy').model_dump(mode='json')
    j=s.enqueue('research',payload);result=s.research(j['id'],payload)
    def handler(request):
        text=json.dumps({'summary':'This synthetic test is not evidence of an edge.','concerns':['Synthetic data'], 'follow_up_tests':['Acquire real point-in-time data']})
        return httpx.Response(200,json={'output':[{'type':'message','content':[{'type':'output_text','text':text}]}]})
    mock_model(monkeypatch,handler)
    reviewed=asyncio.run(agents.review(s,j['id'],result))
    assert reviewed['status']=='not_validated'
    assert reviewed['checks']==result['checks']
    assert reviewed['qualitative_review']['concerns']==['Synthetic data']
