import asyncio
import copy
from datetime import datetime, timedelta, timezone
import pytest
from backend.engine import fee, simulate, validate_rows
from backend.models import Observation, Strategy, BacktestRequest, PaperOrder
from backend.paper import account, execute, settle
from backend.providers import parse_book, price_field, normalize_market
from backend import fixtures


def observations():
    result=[]
    for n in range(3):
        result.append(dict(ticker="TEST",event_id="EVENT",category="Weather",observed_at=f"2025-01-01T0{n}:00:00Z",
            available_at=f"2025-01-01T0{n}:00:00Z",yes_bid=.09,yes_ask=.11,volume=1000,
            outcome="no",settled_at="2025-01-02T00:00:00Z"))
    return result


def quote():
    return parse_book({"orderbook_fp":{"yes_dollars":[["0.09","200"]],"no_dollars":[["0.89","200"]]}})


def market():
    return dict(ticker="TEST",event_id="EVENT",title="Test",status="open",source="synthetic",binary_supported=True)


def order(**kw):
    return PaperOrder(**dict(dict(client_order_id="unique-id-123",ticker="TEST",side="no",quantity=10,limit_price=.92,source="synthetic",confirm=True),**kw))


def test_fee_rounds_up():
    assert fee(1,.5)==.02
    assert fee(100,.5)==1.75
    assert fee(100,.1)==.63


@pytest.mark.parametrize("change",[{"yes_bid":.9},{"volume":-1},{"yes_ask":float('nan')},{"available_at":"2025-01-03T00:00:00Z"},
    {"model_probability":.2},{"model_probability":.2,"model_asof":"2026-01-01T00:00:00Z"},{"observed_at":"2025-01-01T00:00:00"}])
def test_bad_observations_rejected(change):
    row=observations()[0];row.update(change)
    with pytest.raises(ValueError): Observation.model_validate(row)


def test_duplicate_observations_rejected():
    with pytest.raises(ValueError):validate_rows([observations()[0]]*2)


def test_conflicting_outcomes_rejected():
    rows=observations();rows[1]['outcome']='yes'
    with pytest.raises(ValueError): validate_rows(rows)


def test_next_observation_not_same_bar():
    run=simulate(observations(),BacktestRequest(slippage=0))
    t=run['trades'][0]
    assert t['signal_at']<t['entered_at']
    assert t['entered_at']=='2025-01-01T01:00:00+00:00'
    assert t['price']==.91
    assert t['payout']==t['quantity']
    assert run['metrics']['ending_equity']==pytest.approx(10000+t['pnl'],abs=.001)


def test_fee_and_risk_budget():
    run=simulate(observations(),BacktestRequest())
    assert run['trades'][0]['cost']<=100
    assert run['metrics']['fees']>0
    assert all(x['cash']>=0 for x in run['equity_curve'])


def test_open_positions_at_test_end_not_settled():
    run=simulate(observations(),BacktestRequest(end='2025-01-01T02:00:00Z'))
    assert run['metrics']['closed_trades']==0
    assert run['metrics']['open_positions']==1
    assert run['metrics']['net_pnl']<0


def test_no_depth_no_fills():
    rows=observations()
    for row in rows: row['quote_size']=0
    run=simulate(rows,BacktestRequest())
    assert run['metrics']['closed_trades']==0


def test_kelly_requires_model():
    with pytest.raises(ValueError): Strategy(sizing='quarter_kelly')


def test_reproducible_runs():
    a=simulate(fixtures.dataset()['rows'],BacktestRequest(), 'synthetic')
    b=simulate(fixtures.dataset()['rows'],BacktestRequest(), 'synthetic')
    assert a==b
    assert a['warnings'][0].startswith('SYNTHETIC')


def test_model_without_evidence_does_not_trade():
    run=simulate(observations(),BacktestRequest(strategy=Strategy(family='model_edge')))
    assert run['metrics']['closed_trades']==0


def test_book_complements_and_old_schema():
    a=quote()
    b=parse_book({'orderbook':{'yes':[[9,200]],'no':[[89,200]]}})
    assert a['yes']==b['yes']==[[.11,200]]
    assert a['no']==b['no']==[[.91,200]]


@pytest.mark.parametrize('payload',[{}, {'orderbook_fp':{'yes_dollars':[['1.1','2']]}}, {'orderbook':{'no':[[4,-1]]}}])
def test_bad_book_rejected(payload):
    with pytest.raises(ValueError):parse_book(payload)


def test_price_units():
    assert price_field({'price_dollars':'0.15'},'price')==.15
    assert price_field({'price':15},'price')==.15
    assert price_field({'price':'0.15'},'price')==.15


def test_paper_does_not_mutate_input():
    a=account('synthetic');b,o=execute(a,order(),market(),quote())
    assert a['cash']==10000
    assert b['cash']==pytest.approx(10000-o['cost'])
    assert o['filled_quantity']==10


def test_paper_partial_fill_and_no_reusing_same_depth():
    q=quote();q['no']=[[.91,3]]
    a,o=execute(account('synthetic'),order(),market(),q)
    assert o['filled_quantity']==3 and o['cancelled_quantity']==7
    _,next_order=execute(a,order(client_order_id='next-order-id'),market(),q)
    assert next_order['filled_quantity']==0


@pytest.mark.parametrize('change',[{'confirm':False},{'quantity':1000},{'source':'kalshi'}])
def test_paper_rejects_unsafe_requests(change):
    with pytest.raises(ValueError): execute(account('synthetic'),order(**change),market(),quote())


def test_paper_pause():
    a=account('synthetic');a['halted']=True
    with pytest.raises(ValueError):execute(a,order(),market(),quote())


def test_paper_stale_quote():
    q=quote();q['received_at']='2020-01-01T00:00:00Z'
    with pytest.raises(ValueError): execute(account('synthetic'),order(),market(),q)


def test_nonbinary_blocked():
    m=market();m['binary_supported']=False
    with pytest.raises(ValueError): execute(account('synthetic'),order(),m,quote())


def test_settlement_is_idempotent():
    a,o=execute(account('synthetic'),order(),market(),quote())
    m={**market(),'status':'settled','result':'no','settlement_value':0}
    b,settlements=settle(a,{'TEST':m})
    c,again=settle(b,{'TEST':m})
    assert len(settlements)==1 and not again and b==c
    assert b['cash']==pytest.approx(10000+10-o['cost'])


def test_settlement_refuses_unknown_payout():
    a,_=execute(account('synthetic'),order(),market(),quote())
    b,settlements=settle(a,{'TEST':{**market(),'status':'settled','result':'no','settlement_value':.5}})
    assert b==a and not settlements
