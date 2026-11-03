/* By Order of Stonks research-first interface. Real market data only. */
const $ = (q,root=document)=>root.querySelector(q);
const $$ = (q,root=document)=>[...root.querySelectorAll(q)];
const esc = v=>String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const num=v=>v==null?"N/A":new Intl.NumberFormat("en-US",{maximumFractionDigits:2}).format(Number(v));
const money=v=>v==null?"N/A":new Intl.NumberFormat("en-US",{style:"currency",currency:"USD"}).format(Number(v));
const pct=v=>v==null?"N/A":(Number(v)*100).toFixed(1)+"%";
const date=v=>v?new Date(v).toLocaleDateString("en-US",{month:"2-digit",day:"2-digit",year:"numeric"}):"Not available";
const when=v=>v?new Date(v).toLocaleString("en-US"):"Not yet";
const act=(label,action,id="",primary=false)=>'<button type="button" class="btn '+(primary?'primary':'secondary')+' small" data-action="'+esc(action)+'" data-id="'+esc(id)+'">'+esc(label)+'</button>';
const table=(columns,rows)=>'<div class="table-wrap"><table><thead><tr>'+columns.map(c=>'<th>'+esc(c)+'</th>').join('')+'</tr></thead><tbody>'+rows.join('')+'</tbody></table></div>';
const panel=(title,subtitle,body)=>'<section class="panel"><div class="panel-head"><div><h2>'+esc(title)+'</h2><p>'+esc(subtitle)+'</p></div></div>'+body+'</section>';
const notice=(text)=>'<div class="notice">'+esc(text)+'</div>';
const none=(title,text)=>'<div class="empty"><h3>'+esc(title)+'</h3><p>'+esc(text)+'</p></div>';
const head=(label,title,description)=>'<header class="page-header"><div class="eyebrow">'+esc(label)+'</div><h1>'+esc(title)+'</h1><p class="lede">'+esc(description)+'</p></header>';
const opt=(label,value,selected)=>'<option value="'+esc(value)+'" '+(String(value)===String(selected)?'selected':'')+'>'+esc(label)+'</option>';
const sel=(label,name,pairs,value)=>'<div><label>'+esc(label)+'</label><select name="'+esc(name)+'">'+pairs.map(p=>opt(p[1],p[0],value)).join('')+'</select></div>';
const metric=(label,value,note)=>'<div class="metric"><div class="metric-label">'+esc(label)+'</div><div class="metric-value">'+esc(value)+'</div><div class="metric-note">'+esc(note||'')+'</div></div>';
const safe=(url)=>{try{const u=new URL(url);return u.protocol==="https:"?u.href:"#";}catch{return "#";}};
const state={tab:"explore",data:null,markets:[],marketCount:0,marketOffset:0,
  query:"",category:"",status:"open",selectedMarket:null,quote:null,report:null,
  reportId:null,studyIndex:0,jobId:null,assistantHidden:window.innerWidth<1020};
let busyMarkets=false;
let toastTimer;
function toast(s,bad=false){let e=$("#toast");e.textContent=s;e.hidden=false;e.style.borderColor=bad?"#a25a5a":"#5a717c";clearTimeout(toastTimer);toastTimer=setTimeout(()=>e.hidden=true,8000);}
async function api(path,body){
  const opts={method:body===undefined?"GET":"POST",headers:{"Content-Type":"application/json","X-Stonks-Request":"1"}};
  if(body!==undefined)opts.body=JSON.stringify(body);
  const response=await fetch("/api"+path,opts);
  let data;try{data=await response.json();}catch{throw Error("Unexpected server response: HTTP "+response.status);}
  if(!response.ok){if(response.status===401){$("#app").hidden=true;$("#sign-in").hidden=false;}throw Error(typeof data.detail==="string"?data.detail:"Server error: "+response.status);}
  return data;
}
function tab(name){
  state.tab=["explore","research","trade"].includes(name)?name:"explore";
  history.replaceState(null,"","#"+state.tab);
  $$(".nav").forEach(x=>x.classList.toggle("active",x.dataset.nav===state.tab));
  $("#page-label").textContent=state.tab[0].toUpperCase()+state.tab.slice(1);
  $(".sidebar").classList.remove("open");
  render();window.scrollTo(0,0);
}
function render(){
  if(!state.data)return;
  $("#view").innerHTML=state.tab==="explore"?explore():state.tab==="research"?research():trade();
  const c=state.data.catalog;
  $("#source-health").textContent=c.markets_indexed?num(c.markets_indexed)+" Kalshi markets indexed":"Indexing Kalshi markets";
  $("#worker-status").textContent="Research: "+state.data.worker;
}
function jobList(){
  const jobs=state.data.jobs.filter(j=>["queued","running","failed"].includes(j.status)).slice(0,6);
  return jobs.length?'<ul class="clean">'+jobs.map(j=>'<li><strong>'+esc(j.question)+'</strong><small>'+esc(j.status.toUpperCase()+' · '+j.stage)+(j.error?' · '+esc(j.error):'')+'</small>'+act("View progress","job",j.id)+'</li>').join('')+'</ul>':
    none("Nothing queued","Ask any research question to start a data collection and quantitative analysis job.");
}
function marketTable(){
  return table(["Market and series","Status","YES ask","Volume","Action"],state.markets.map(m=>'<tr><td><strong>'+esc(m.title||m.ticker)+'</strong><small>'+esc(m.ticker)+' · '+esc(m.category||"Unclassified")+' · '+esc(m.series_ticker)+'</small></td><td>'+esc(m.status)+'</td><td>'+ (m.yes_ask==null?"No quote":(m.yes_ask*100).toFixed(1)+"¢")+'</td><td>'+num(m.volume)+'</td><td><div class="row wrap">'+act("Investigate","investigate",m.ticker)+ (m.status==="open"?act("Paper ticket","ticket",m.ticker,true):"")+'</div></td></tr>'));
}
function explore(){
  const c=state.data.catalog, reports=state.data.reports.slice(0,4);
  return head("EXPLORE","What do you want to investigate?",
    "Ask about any market, event, trading theory or comparison. The research desk finds relevant Kalshi data and runs the analysis without requiring manual imports.")+
    '<form id="explore-form" class="hero"><label for="question">Your research question</label>'+
    '<textarea id="question" name="question" rows="4" maxlength="1800" required placeholder="What inefficiencies might exist in prediction markets, and can we test them against history?"></textarea>'+
    '<div class="hero-bottom"><span class="help">Real Kalshi data. Open-ended questions. Transparent limits.</span><button class="btn primary" type="submit">Investigate ↗</button></div>'+
    '<details><summary>Optional research controls</summary><div class="form-grid" style="margin-top:15px">'+
    sel("Compare by","compare_by",[["auto","Let the desk decide"],["market_type","Market type"],["category","Category"],["series","Exchange series"]],"auto")+
    sel("Baseline rule","trading_rule",[["auto","Let the desk decide"],["buy_yes","Buy YES"],["buy_no","Buy NO"],["against_longshots","Buy NO against low-priced YES"],["buy_longshots","Buy low-priced YES"],["buy_favorites","Buy high-priced YES"]],"auto")+
    sel("Days before settlement","days_before",[[1,"1 day"],[2,"2 days"],[7,"7 days"],[14,"14 days"]],2)+
    sel("Historical market sample cap","max_markets",[[30,"30"],[60,"60"],[100,"100"]],60)+'</div></details></form>'+
    '<div class="metric-row">'+metric("Real markets indexed",num(c.markets_indexed),"Partial market catalogue")+
    metric("Historical candles",num(c.candles_indexed),"Exchange observations only")+
    metric("Research reports",num(state.data.reports.length),"Inconclusive results retained")+'</div>'+
    '<div class="split">'+panel("Active investigations","Actual jobs and failures, not simulated agent conversations.",jobList())+
    panel("Recent research","Select a report to inspect data, methods and limitations.",
      reports.length?reports.map(r=>'<button class="report-link" data-action="report" data-id="'+esc(r.id)+'"><strong>'+esc(r.question)+'</strong><small>'+date(r.created_at)+' · '+esc(r.status)+' · '+num(r.contracts_with_history)+' historical contracts</small></button>').join(''):
      none("No research reports","Your first question will create a saved investigation."))+'</div>'+
    panel("Search the market catalogue","Actual indexed Kalshi markets. No result only means no match in the indexed subset.",
    '<form id="market-form"><div class="form-grid"><div><label>Topic, event, ticker or series</label><input name="query" value="'+esc(state.query)+'" placeholder="Search indexed markets"></div>'+
    sel("Category","category",[["","All categories"],["Sports","Sports"],["Politics","Politics"],["Weather","Weather"],["Economics","Economics"],["Finance","Finance"]],state.category)+
    sel("Status","status",[["open","Open"],["settled","Settled"],["","All indexed"]],state.status)+
    '</div><div class="form-actions"><button type="submit" class="btn primary">Search</button><span class="help">Indexing is automatic, not a prerequisite you need to configure.</span></div></form>'+
    '<p class="note">'+num(state.marketCount)+' indexed matches. Showing '+num(state.markets.length)+'. Last refreshed: '+date(c.latest_indexed)+'.</p>'+
    (state.markets.length?marketTable():none("No indexed matches yet","Indexing may be running, or the requested market is not in the indexed subset."))+
    (state.marketOffset<state.marketCount?'<div class="form-actions">'+act("Load more","more")+'</div>':""))+
    notice("Market coverage is bounded, and historical quote candles do not prove that a trade could have been filled at the quoted price.");
}
function requirementsView(report){
  const c=report.completion;
  if(!c)return notice("Older report: no structured completion checks were saved. Treat findings as preliminary.");
  const rows=(c.requirements||[]).map(r=>'<li><strong>'+
    esc(r.status==="verified"?"✓ Verified: ":r.status==="partial"?"◐ Partial: ":"× Unmet: ")+
    esc(r.label)+'</strong><small>'+esc(r.reason||"No independent supporting evidence")+
    (r.evidence?.length?'<br>Evidence: '+esc(r.evidence.join(" · ")):"")+'</small></li>').join("");
  return panel("Did the investigation answer your request?",
    c.complete?"All required evidence checks were satisfied.":"Incomplete requests cannot be represented as trade recommendations or validated findings.",
    '<div class="notice '+(c.complete?"":"warning")+'"><strong>'+
      (c.complete?"Requirements verified":"This request has NOT been fulfilled")+
      '</strong><br>'+esc(c.warning||"Review all underlying evidence before acting.")+'</div>'+
    '<ul class="clean">'+rows+'</ul>');
}
function capabilityReport(r){
  const constraints=r.plan?.constraints||r.constraints||{};
  const event=r.verified_event;
  const tr=r.trade_review||{};
  const logs=tr.game_log_coverage||[];
  const candidates=tr.candidate_legs||[];
  const requested=constraints.requested_legs;
  let html=head("RESEARCH / "+(r.task_type==="trade_construction"?"TRADE CONSTRUCTION":"EVENT INVESTIGATION"),
    "Request requirements and verified evidence",
    "The desk preserves your actual question. It will not replace an unmet trade-building request with an unrelated historical simulation.");
  html+=panel("Your exact request","The following details are requirements, not optional suggestions.",
    '<h2>'+esc(r.question)+'</h2>'+
    '<div class="grid3" style="margin-top:18px">'+
      metric("Requested trade legs",requested?String(requested):"Not specified","An exact market for every leg is required")+
      metric("Desired joint probability",constraints.target_probability_min!=null?
        pct(constraints.target_probability_min)+"–"+pct(constraints.target_probability_max):"Not specified",
        "Must be based on a calibrated joint probability model")+
      metric("Historical lookback",constraints.lookback_games?
        constraints.lookback_games+" games":"Not specified","Actual boxscores, not a model's opinion")+
    '</div>');
  html+=panel("Verified event","Only source-verified teams and kickoff are considered. No guessed matchups.",
    event?'<div class="notice"><strong>'+esc(event.title)+'</strong><br>'+
      'Kickoff: '+esc(when(event.kickoff_utc))+'<br>'+
      'Teams: '+esc(event.teams.map(t=>t.name).join(" vs "))+'<br>'+
      '<a href="'+esc(safe(event.source))+'" target="_blank" rel="noopener noreferrer">Schedule source</a></div>':
      none("Event not verified","A unique event could not be proven from a provider record. Player statistics and trade construction are blocked."));
  if(r.task_type==="trade_construction"){
    html+=panel("Game-log evidence","Counts reflect actual completed games retrieved before the verified kickoff, not implied future win probabilities.",
      logs.length?table(["Team","Requested","Verified","Provider"],
        logs.map(x=>'<tr><td><strong>'+esc(x.team)+'</strong></td><td>'+
          num(x.games_requested)+'</td><td>'+num(x.games_verified)+'</td><td>'+
          (x.source?'<a href="'+esc(safe(x.source))+'" target="_blank" rel="noopener noreferrer">Data source</a>':"Unavailable")+'</td></tr>')):
        none("No game logs verified","The event or source player statistics were unavailable."));
    html+=panel("Potential contract candidates","An identified contract is NOT an endorsed trade leg. No unverified prop is added.",
      candidates.length?table(["Verified player / market","Historical prop results","Current contract","Research status"],
        candidates.map(x=>'<tr><td><strong>'+esc(x.player)+'</strong><small>'+
          esc(x.stat?.source_text||"")+'</small></td><td>'+
          num(x.last_games?.observed_games)+' / '+num(x.last_games?.requested_games)+' games'+
          (x.last_games?.observed_frequency!=null?'<small>Past-game frequency '+pct(x.last_games.observed_frequency)+' (not calibrated)</small>':"")+
          '</td><td><code>'+esc(x.ticker)+'</code></td><td>'+
          esc(x.last_games?.status==="verified"?"Historical data present":"Incomplete logs")+'</td></tr>')):
        none("No fully verified player-prop contracts","Without verified event-linked Kalshi markets, the system cannot claim that candidate trade legs exist."));
    const structure=tr.proposed_legs||[];
    html+=panel("Provisional trade structure",
      "These are evidence-backed research candidates, NOT approved or executable trade legs.",
      structure.length?table(["Player / condition","Observed recent frequency","Kalshi contract"],
        structure.map(x=>'<tr><td><strong>'+esc(x.player)+'</strong><small>'+
          esc(x.stat?.source_text||"")+'</small></td><td>'+pct(x.last_games?.observed_frequency)+
          ' (descriptive, not predictive)</td><td><code>'+esc(x.ticker)+'</code></td></tr>')):
        none("No verified leg structure","The exchange and statistical evidence were insufficient to select the requested number of legs."));
    html+=panel("Joint probability and execution",
      "A calculated scenario is not a calibrated forecast or an executable Kalshi combination.",
      '<div class="metric-row">'+metric("Verified joint probability","Unavailable","A calibrated multivariate model is required")+
      metric("Provisional legs",String(structure.length),"No real-money trade prepared")+
      metric("Native Kalshi quote","Unavailable","RFQ integration not implemented")+'</div>'+
      (tr.independence_scenario!=null?
        '<div class="notice warning"><strong>Uncalibrated illustrative scenario only:</strong> '+
        pct(tr.independence_scenario)+' under independence. Illustrative Frechet bounds: '+
        pct(tr.frechet_scenario?.[0])+' to '+pct(tr.frechet_scenario?.[1])+'. '+
        'These are not actual joint event probabilities or guaranteed quoted odds.</div>':'')+
      '<p>'+esc(tr.scenario_warning||"No defensible combined outcome probability can be calculated from current evidence.")+'</p>');
  }
  html+=requirementsView(r);
  if(r.external?.text){
    html+=panel("External research context","Never treated as a substitute for verified event identity or quantitative probabilities.",
      '<p>'+esc(r.external.text)+'</p>');
  }
  html+=panel("What can and cannot be concluded","A limitation is a blocker, not an invitation to invent an answer.",
    '<p>'+esc(r.conclusion)+'</p><ul class="clean">'+(r.limitations||[]).map(x=>'<li>'+esc(x)+'</li>').join("")+'</ul>'+
    (r.evidence?.length?'<details><summary>Provider documentation and evidence</summary><ul class="clean">'+
      r.evidence.map(x=>'<li><a href="'+esc(safe(x.url))+'" target="_blank" rel="noopener noreferrer">'+
      esc(x.title)+'</a></li>').join("")+'</ul></details>':"")+
    '<div class="form-actions">'+act("Discuss missing evidence","discuss","",true)+act("New investigation","nav","explore")+'</div>');
  return html;
}
function reportView(){
  const r=state.report;
  if(!r)return none("No report selected","Ask a question in Explore, or select a saved investigation.");
  if(r.task_type==="trade_construction"||r.task_type==="event_analysis")return capabilityReport(r);
  const ac=r.acquisition||{},studies=r.studies||[],index=Math.min(state.studyIndex,studies.length-1),study=studies[Math.max(0,index)];
  let html='<div class="panel"><div class="eyebrow">'+esc(r.status)+'</div><h2 style="font-size:23px;margin:11px 0">'+esc(r.question)+'</h2><p>'+esc(r.conclusion)+'</p>'+
    '<div class="metric-row">'+metric("Settled markets found",num(ac.settled_market_count),"Bounded historical universe")+
    metric("Markets with history",num(ac.contracts_with_candles),"Eligible quote candles")+
    metric("Candles obtained",num(ac.candles_loaded),"Actually stored")+'</div>'+
    '<p><strong>Research design:</strong> '+esc(r.plan?.analysis)+'</p>'+
    '<details><summary>Series identified and exact data coverage</summary><ul class="clean">'+
    (r.selected_series||[]).map(s=>'<li><strong>'+esc(s.title)+'</strong><small>'+esc(s.ticker)+' · '+esc(s.category)+'</small></li>').join('')+
    '</ul><pre>'+esc(JSON.stringify(ac,null,2))+'</pre></details></div>';
  if(study){
    const options=studies.map((v,i)=>[i,v.strategy_description]);
    html+=panel("Historical comparison","All strategies are measured using the same collected market universe, with documented assumptions.",
      '<div class="form-grid">'+sel("Simulation / research rule","study_index",options,index)+
      '<div><label>Decision rule</label><p class="note">'+esc(study.entry_rule)+'</p></div></div>'+
      '<div class="metric-row" style="margin-top:18px">'+metric("Eligible observations",num(study.observations),"At the chosen decision horizon")+
      metric("Distinct event IDs",num(study.independent_event_ids),"Not necessarily independent risk")+
      metric("Modeled net P&L",money(study.overall?.simulation?.net_pnl),"Assumed fills, not realized profit")+'</div>'+
      (study.groups?.length?
      table(["Comparison group","Contract / event sample","Calibration score","Hypothetical P&L","Quality"],
        study.groups.map(g=>'<tr><td><strong>'+esc(g.group)+'</strong><small>'+esc((g.classification||[]).join(", "))+'</small></td><td>'+num(g.n_contracts)+' / '+num(g.n_events)+'</td><td>'+num(g.calibration?.brier_score)+'</td><td>'+money(g.simulation?.net_pnl)+'<small>'+num(g.simulation?.total_trades)+' trades</small></td><td>'+esc(g.quality)+'</td></tr>')):
      none("Insufficient historical observations","There were not enough usable point-in-time quotes to compare outcomes."))+
      '<details><summary>Probability calibration by historical quote band</summary>'+
      table(["YES price band","Contracts","Observed YES frequency","Quoted mean probability"],
        (study.overall?.calibration?.bins||[]).map(b=>'<tr><td>'+esc(b.range)+'</td><td>'+num(b.contracts)+'</td><td>'+pct(b.observed_yes_frequency)+'</td><td>'+pct(b.mean_quoted_probability)+'</td></tr>'))+
      '</details><details><summary>Exact simulation metrics and warnings</summary><pre>'+esc(JSON.stringify(study.overall?.simulation||{},null,2))+'</pre></details>');
  }
  const related=(r.current_markets||[]).filter(m=>m.status==="open");
  html+=panel("Related current Kalshi contracts",
    "Real open markets found during this investigation. These are NOT automatically mispriced, ranked by edge or recommended trades.",
    related.length?table(["Market","YES bid / ask","Volume","Action"],
      related.slice(0,35).map(m=>'<tr><td><strong>'+esc(m.title||m.ticker)+'</strong><small>'+
      esc(m.ticker)+' · '+esc(m.category||"Unclassified")+'</small></td><td>'+
      (m.yes_bid==null?"No bid":(100*m.yes_bid).toFixed(1)+"¢")+' / '+
      (m.yes_ask==null?"No ask":(100*m.yes_ask).toFixed(1)+"¢")+'</td><td>'+
      num(m.volume)+'</td><td>'+act("Inspect paper ticket","ticket",m.ticker)+'</td></tr>')):
      none("No related current contracts found","The matching series may be entirely historical, or open contracts may be outside the bounded search."));
  html+=requirementsView(r);
  const external=r.external||{},sources=[...(external.sources||[]),...(r.evidence||[])];
  html+=panel("Independent research and sources","External context is not used as historical point-in-time evidence.",
    notice(external.status==="retrieved"?"Web research retrieved.":"Web search unavailable or not requested; exchange evidence remains valid.")+
    (external.text?'<p style="white-space:pre-wrap">'+esc(external.text)+'</p>':'')+
    '<ul class="clean">'+sources.map(s=>'<li><a href="'+esc(safe(s.url))+'" target="_blank" rel="noopener noreferrer">'+esc(s.title||s.url)+'</a></li>').join('')+'</ul>');
  html+=panel("What this research cannot establish","Independent limitations remain visible even when a strategy performs well.",
    '<ul class="clean">'+(r.limitations||[]).map(v=>'<li>'+esc(v)+'</li>').join('')+'</ul>'+
    '<div class="form-actions">'+act("Discuss these findings","discuss","",true)+act("Investigate something else","nav","explore")+'</div>');
  return html;
}
function research(){
  const reports=state.data.reports;
  return head("RESEARCH","Your investigations, with the assumptions exposed.",
    "Inspect market selection, historical evidence, calibration, comparisons and possible failure modes. Agent roles and data collection remain behind the scenes.")+
    '<div class="split">'+panel("Research archive","Select any completed study, including inconclusive ones.",
      reports.length?reports.map(r=>'<button class="report-link '+(state.reportId===r.id?'active':'')+'" data-action="report" data-id="'+esc(r.id)+'"><strong>'+esc(r.question)+'</strong><small>'+date(r.created_at)+' · '+esc(r.status)+' · '+num(r.contracts_with_history)+' markets with history</small></button>').join(''):
      none("No studies yet","Use Explore to ask your first research question."))+
    panel("What happens when you ask a question","No manual contract import or agent setup required.",
    '<ol class="steps"><li><div><strong>Find related real markets</strong><small>Series directory and market index.</small></div></li>'+
    '<li><div><strong>Collect the relevant history</strong><small>Settlements, archived quotes and available public context.</small></div></li>'+
    '<li><div><strong>Run comparable analysis</strong><small>Calibration and several common trading baselines.</small></div></li>'+
    '<li><div><strong>Challenge conclusions</strong><small>Sample size, correlation, liquidity and missing coverage.</small></div></li></ol>')+'</div>'+reportView();
}
function paperPositions(){
  const a=state.data.paper;
  if(!a)return none("Paper account initializing","No real exchange funds are held here.");
  return '<div class="metric-row">'+metric("Paper cash",money(a.cash),"Simulated, never exchange funds")+
    metric("Open positions",num(a.positions?.length||0),"Paper only")+
    metric("Settled paper P&L",money(a.realized_pnl),"Reconciled outcomes")+'</div>'+
    (a.positions?.length?table(["Market","Side","Contracts","Capital committed"],a.positions.map(p=>
    '<tr><td>'+esc(p.title||p.ticker)+'<small>'+esc(p.ticker)+'</small></td><td>'+esc(p.side.toUpperCase())+'</td><td>'+num(p.quantity)+'</td><td>'+money(p.cost)+'</td></tr>')):"");
}
function trade(){
  const m=state.selectedMarket,quote=state.quote;
  let ticket='<form id="find-ticket" class="form-actions"><div style="flex:1"><label>Exact Kalshi ticker</label><input name="ticker" placeholder="Choose a contract in Explore or enter its ticker" value="'+esc(m?.ticker||"")+'" required></div><button type="submit" class="btn secondary">Load contract</button></form>';
  if(m){
    ticket+='<div class="notice"><strong>'+esc(m.title||m.ticker)+'</strong><br>'+esc(m.ticker)+' · '+esc(m.status)+'</div>'+
      '<p>'+esc(m.rules||"Review the exact exchange settlement rules before paper trading.")+'</p>';
    if(quote){
      ticket+='<div class="grid2">'+metric("Best YES ask",quote.book?.yes?.length?money(quote.book.yes[0][0]):"No depth","Observed order book")+
        metric("Best NO ask",quote.book?.no?.length?money(quote.book.no[0][0]):"No depth","Observed order book")+'</div>';
    }
    if(m.status==="open"){
      ticket+='<form id="paper-form"><div class="form-grid">'+sel("Buy","side",[["yes","YES"],["no","NO"]],"yes")+
        '<div><label>Contracts</label><input name="quantity" type="number" min="1" max="10000" value="1" required></div>'+
        '<div><label>Maximum price per contract ($)</label><input name="limit_price" type="number" min="0.0001" max="0.9999" step="0.0001" value="'+esc(quote?.book?.yes?.[0]?.[0]||0.5)+'" required></div></div>'+
        notice("Immediate-or-cancel paper simulation. A fresh book is fetched at submission. Partial and zero fills are possible.")+
        '<label class="row"><input type="checkbox" name="confirm" style="width:auto" required> I approve this paper order with no real funds.</label>'+
        '<div class="form-actions"><button type="submit" class="btn primary">Submit paper trade ↗</button>'+act("Refresh price","ticket",m.ticker)+'</div></form>';
    }
  } else ticket+=none("No contract selected","Open Explore and select a current Kalshi market.");
  return head("TRADE","Simulate a real-market position.",
    "Prepare a reviewed paper order using a fresh Kalshi order book. Production trading is disabled even when your Kalshi key permits writes.")+
    paperPositions()+'<div class="split">'+panel("Order preparation","No live orders can be submitted.",ticket)+
    panel("Account risk controls","Deterministic account limits apply independently of the research assistant.",
      '<ul class="clean"><li>2% maximum per contract</li><li>5% maximum per exchange event</li><li>30% maximum aggregate commitment</li><li>Only ordinary $1 binary contracts supported</li><li>Cash and positions are paper-only</li></ul>'+
      '<div class="form-actions">'+act(state.data.paper?.halted?"Resume paper orders":"Pause new paper orders","halt",state.data.paper?.halted?"resume":"pause")+'</div>')+'</div>';
}
async function refresh(draw=true){
  state.data=await api("/desk/overview");
  const job=state.jobId&&state.data.jobs.find(j=>j.id===state.jobId);
  if(job&&job.status==="completed"&&job.report_id){
    state.jobId=null;state.report=await api("/desk/reports/"+encodeURIComponent(job.report_id));
    state.reportId=state.report.id;state.studyIndex=0;
    toast(state.report.completion?.complete?"Research completed; review the evidence.":"Research report ready: some requested requirements remain unresolved.",!state.report.completion?.complete);tab("research");return;
  }
  if(job&&job.status==="failed"){state.jobId=null;toast("Research failed: "+(job.error||"Unknown error"),true);}
  if(draw)render();
}
async function markets(reset=true){
  if(busyMarkets)return;busyMarkets=true;
  try{
    const offset=reset?0:state.marketOffset;
    const args=new URLSearchParams({query:state.query,category:state.category,status:state.status,offset:String(offset),limit:"80"});
    const result=await api("/desk/markets?"+args.toString());
    state.marketCount=result.count;
    state.markets=reset?result.markets:state.markets.concat(result.markets);
    state.marketOffset=offset+result.returned;
    render();
  }catch(e){toast(e.message,true);}finally{busyMarkets=false;}
}
function assistant(who,text){
  const node=document.createElement("article");node.className="bubble "+who;
  node.textContent=text;$("#thread").append(node);$("#thread").scrollTop=$("#thread").scrollHeight;
  return node;
}
async function researchJob(question,settings={}){
  if(question.trim().length<8)throw Error("Provide a research question with at least 8 characters.");
  const job=await api("/desk/research",{question:question.trim(),compare_by:settings.compare_by||"auto",
    trading_rule:settings.trading_rule||"auto",days_before:Number(settings.days_before||2),
    max_markets:Number(settings.max_markets||60),include_web:true});
  state.jobId=job.id;
  assistant("user",question);
  assistant("bot","Research queued. I will preserve your requirements, verify the relevant event and markets, use the appropriate evidence and analysis tools, then state explicitly which requirements were satisfied or blocked. No manual ticker import is needed.");
  toast("Research queued. Progress appears in Explore.");
  await refresh();return job;
}
async function selectMarket(ticker){
  const details=await api("/desk/market/"+encodeURIComponent(ticker));
  state.selectedMarket=details.market;state.quote=null;
  if(state.selectedMarket.status==="open"){
    try{state.quote=await api("/quote/"+encodeURIComponent(ticker)+"?source=kalshi");}
    catch(e){toast("Current order book unavailable: "+e.message,true);}
  }
  tab("trade");
}
async function report(id){state.report=await api("/desk/reports/"+encodeURIComponent(id));state.reportId=id;state.studyIndex=0;tab("research");}
async function action(name,id){
  if(name==="nav"){tab(id);return;}
  if(name==="report"){await report(id);return;}
  if(name==="more"){await markets(false);return;}
  if(name==="ticket"){await selectMarket(id);return;}
  if(name==="investigate"){
    const m=state.markets.find(x=>x.ticker===id);
    await researchJob("Investigate the Kalshi market "+id+": "+(m?.title||id)+". Examine related market history, quote calibration, public evidence and potential research hypotheses.");
    return;
  }
  if(name==="job"){
    const j=await api("/desk/jobs/"+encodeURIComponent(id));
    assistant("bot",(j.events||[]).map(x=>when(x.at)+" · "+x.stage+": "+x.message).join("\n")+(j.error?"\nError: "+j.error:""));
    return;
  }
  if(name==="discuss"){state.assistantHidden=false;updateAssistant();$("#assistant-input").value="Explain the most important findings, uncertainties and what could invalidate this research.";$("#assistant-input").focus();return;}
  if(name==="halt"){await api("/paper/kalshi/halt",{enabled:id==="pause"});await refresh();toast(id==="pause"?"New paper orders paused.":"Paper orders resumed.");}
}
document.addEventListener("click",async e=>{
  const target=e.target.closest("[data-action],[data-nav]");if(!target)return;
  e.preventDefault();
  if(target.dataset.nav){tab(target.dataset.nav);return;}
  target.disabled=true;
  try{await action(target.dataset.action,target.dataset.id||"");}
  catch(err){toast(err.message,true);}finally{target.disabled=false;}
});
document.addEventListener("change",e=>{
  if(e.target.name==="study_index"){state.studyIndex=Number(e.target.value);render();}
});
document.addEventListener("submit",async e=>{
  if(["login-form","assistant-form"].includes(e.target.id))return;
  e.preventDefault();
  const form=e.target,button=form.querySelector('[type="submit"]');
  if(button)button.disabled=true;
  try{
    const values=Object.fromEntries(new FormData(form).entries());
    if(form.id==="explore-form"){
      await researchJob(values.question,values);
      form.reset();
    } else if(form.id==="market-form"){
      state.query=values.query.trim();state.category=values.category;state.status=values.status;await markets();
    } else if(form.id==="find-ticket"){
      await selectMarket(values.ticker.trim().toUpperCase());
    } else if(form.id==="paper-form"){
      if(!state.selectedMarket)throw Error("Select a market first.");
      const order=await api("/desk/paper",{ticker:state.selectedMarket.ticker,
        side:values.side,quantity:Number(values.quantity),limit_price:Number(values.limit_price),
        confirm:values.confirm==="on",client_order_id:crypto.randomUUID()});
      toast("Paper "+order.status+": "+num(order.filled_quantity)+" contracts, "+money(order.cost)+" modeled cost.");
      await refresh();
    }
  }catch(err){toast(err.message,true);}finally{if(button)button.disabled=false;}
});
$("#assistant-form").addEventListener("submit",async e=>{
  e.preventDefault();
  const field=$("#assistant-input"),message=field.value.trim();if(!message)return;
  const button=$("#assistant-send");button.disabled=true;field.value="";
  assistant("user",message);
  const reply=assistant("bot","Working with the available research tools…");
  try{
    const result=await api("/desk/chat",{message,report_id:state.tab==="research"?state.reportId:null});
    reply.textContent=result.text||"Research queued.";
    if(result.job_id)state.jobId=result.job_id;
  }catch(err){reply.textContent=err.message;toast(err.message,true);}finally{button.disabled=false;}
});
$("#login-form").addEventListener("submit",async e=>{
  e.preventDefault();
  try{await api("/login",{password:new FormData(e.target).get("password")});e.target.reset();await start();}
  catch(err){$("#login-error").textContent=err.message;}
});
$("#logout").addEventListener("click",async()=>{await api("/logout",{});location.reload();});
function updateAssistant(){
  document.body.classList.toggle("assistant-closed",state.assistantHidden);
  $("#assistant").hidden=state.assistantHidden;
}
$("#close-assistant").addEventListener("click",()=>{state.assistantHidden=true;updateAssistant();});
$("#toggle-assistant").addEventListener("click",()=>{state.assistantHidden=!state.assistantHidden;updateAssistant();});
$("#mobile-nav").addEventListener("click",()=>$(".sidebar").classList.toggle("open"));
async function start(){
  const session=await api("/session");
  $("#app").hidden=!session.authenticated;$("#sign-in").hidden=session.authenticated;
  if(!session.authenticated)return;
  updateAssistant();
  await refresh(false);
  await markets();
  tab(location.hash.slice(1));
}
setInterval(()=>{
  if($("#app").hidden||document.hidden)return;
  const editing=["INPUT","TEXTAREA","SELECT"].includes(document.activeElement?.tagName);
  refresh(!editing).catch(e=>toast(e.message,true));
},6000);
start().catch(e=>{$("#app").hidden=false;$("#view").innerHTML=notice("Application error: "+e.message);});
