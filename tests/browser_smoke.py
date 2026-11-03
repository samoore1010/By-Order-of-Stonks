"""Browser + actual FastAPI integration via an in-process transport, with no network.
This does NOT validate Railway TLS, container build or authenticated external providers.
Run: APP_ENV=development python tests/browser_smoke.py
"""
from pathlib import Path
import os
import re
import sys
import tempfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
os.environ['APP_ENV']='development'
for name in ('APP_PASSWORD','OPENAI_API_KEY','KALSHI_API_KEY_ID','KALSHI_PRIVATE_KEY_PEM'):
    os.environ.pop(name,None)
from fastapi.testclient import TestClient
from playwright.sync_api import sync_playwright
from backend.app import create_app
from backend.service import Services
from backend.store import Store

ROOT=Path(__file__).resolve().parents[1]


def run():
    with tempfile.TemporaryDirectory() as tmp:
        s=Services(Store('sqlite:///'+str(Path(tmp)/'browser.db')))
        with TestClient(create_app(s)) as client,sync_playwright() as p:
            executable=os.getenv('CHROMIUM_PATH')
            if not executable and Path('/usr/bin/chromium').exists():executable='/usr/bin/chromium'
            browser=p.chromium.launch(headless=True,executable_path=executable,args=['--no-sandbox'])
            page=browser.new_page(viewport={'width':1600,'height':1050})
            errors=[]
            page.on('pageerror',lambda e:errors.append(str(e)))
            def transport(url,options):
                response=client.request(options.get('method','GET'),url,content=options.get('body'),headers=options.get('headers',{}))
                return {'status':response.status_code,'body':response.text,'headers':dict(response.headers)}
            page.expose_function('testBackend',transport)
            html=re.sub(r'<link[^>]+>','',(ROOT/'frontend/index.html').read_text())
            html=re.sub(r'<script.*?</script>','',html,flags=re.S)
            page.set_content(html)
            page.add_style_tag(content=(ROOT/'frontend/style.css').read_text())
            page.evaluate('''window.fetch=async(url,opts={})=>{const r=await window.testBackend(url,opts);return new Response(r.body,{status:r.status,headers:r.headers});};
                if(!crypto.randomUUID)crypto.randomUUID=()=>"test-"+Math.random().toString(16).slice(2);
                Object.defineProperty(window,'sessionStorage',{value:{getItem:()=>null,setItem:()=>{}}});''')
            page.add_script_tag(content=(ROOT/'frontend/app.js').read_text(),type='module')
            page.wait_for_selector('h1:has-text("Research first")')
            for tab in ('scanner','research','strategies','backtests','builder','trading','portfolio','agents','data','integrations','settings'):
                page.locator(f'nav [data-id="{tab}"]').click()
                assert page.locator('main h1').count()==1
            page.locator('nav [data-id="strategies"]').click()
            page.locator('[data-action="preset-longshot"]').click()
            assert 'unlikely YES outcomes' in page.locator('#strategy-form [name=name]').input_value()
            page.locator('#strategy-form [name=name]').fill('Browser-tested strategy')
            page.locator('#strategy-form [type=submit]').click()
            page.wait_for_selector('h3:has-text("Browser-tested strategy")')
            page.locator('nav [data-id="scanner"]').click()
            # Explicitly opt into practice data; real Kalshi is now the default.
            page.locator('#market-form [name="source"]').select_option('synthetic')
            page.locator('#market-form button').click()
            page.wait_for_selector('text=Phoenix high temperature above 100°F?')
            page.locator('#market-filters [name="topic"]').select_option('Sports')
            assert page.locator('#market-count').inner_text().startswith('2 matching markets')
            page.locator('[data-action="clear-market-filters"]').click()
            assert page.locator('#market-count').inner_text().startswith('6 matching markets')
            page.locator('[data-action=ticket][data-id="DEMO-1"]').click()
            page.wait_for_selector('#ticket-form')
            page.locator('#ticket-form [name=confirm]').check()
            page.locator('#ticket-form [type=submit]').click()
            page.wait_for_selector('h1:has-text("Paper capital")')
            assert len(s.store.list('paper_order'))==1
            page.locator('nav [data-id="backtests"]').click()
            page.locator('#backtest-form [type=submit]').click()
            page.wait_for_timeout(4500)
            assert len(s.store.list('run'))>=2
            page.locator('nav [data-id="research"]').click()
            page.locator('#research-form [type=submit]').click()
            page.wait_for_selector('h1:has-text("A research desk")')
            page.wait_for_timeout(4500)
            assert len(s.store.list('research'))==1
            page.locator('#chat-input').fill('Explain the selected backtest and its limitations.')
            page.locator('#send-chat').click()
            page.wait_for_function("!document.querySelector('#send-chat').disabled")
            assert page.locator('#messages .message').count()==3
            page.set_viewport_size({'width':390,'height':844})
            assert page.evaluate('document.documentElement.scrollWidth')==390
            page.locator('#menu').click()
            assert page.locator('.sidebar').is_visible()
            page.locator('nav [data-id="overview"]').click()
            assert not page.locator('.sidebar').is_visible()
            artifacts=ROOT/'artifacts';artifacts.mkdir(exist_ok=True)
            page.screenshot(path=str(artifacts/'mobile.png'),full_page=True)
            page.set_viewport_size({'width':1600,'height':1050})
            page.screenshot(path=str(artifacts/'overview.png'),full_page=True)
            assert errors==[],errors
            browser.close()
            print('PASS: 12 workspaces, strategy save, paper ticket, queued backtest, research validation, copilot, mobile layout; no browser errors.')


if __name__=='__main__':run()
