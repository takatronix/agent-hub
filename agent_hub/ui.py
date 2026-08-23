"""Single-page web UI (vanilla JS, served inline)."""
INDEX_HTML = r"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><title>agent-hub</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root{--bg:#f6f7f9;--fg:#1b1f24;--mut:#6b7280;--card:#fff;--line:#e3e6ea;--acc:#2563eb;--ok:#16a34a;--bad:#dc2626;--warn:#d97706;
 --claude:#c2410c;--codex:#0f766e;--kimi:#7c3aed;--hub:#475569;--fake:#64748b}
@media(prefers-color-scheme:dark){:root{--bg:#0f1115;--fg:#e6e8eb;--mut:#9aa3ae;--card:#171a21;--line:#2a2f3a;--acc:#60a5fa}}
*{box-sizing:border-box}body{margin:0;font:14px/1.5 -apple-system,"Hiragino Sans","Noto Sans JP",system-ui,sans-serif;background:var(--bg);color:var(--fg)}
a{color:var(--acc);text-decoration:none}a:hover{text-decoration:underline}
header{display:flex;gap:16px;align-items:center;padding:10px 18px;border-bottom:1px solid var(--line);background:var(--card);position:sticky;top:0;z-index:5}
header h1{font-size:16px;margin:0}header .sp{flex:1}header .live{font-size:12px;color:var(--mut)}
main{padding:16px 18px;max-width:1600px;margin:0 auto}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px;margin-bottom:12px}
table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line);vertical-align:top}th{color:var(--mut);font-weight:500;font-size:12px}
.pill{display:inline-block;padding:1px 8px;border-radius:999px;font-size:11px;border:1px solid var(--line);color:var(--mut)}
.pill.done{color:var(--ok);border-color:var(--ok)}.pill.failed,.pill.cancelled{color:var(--bad);border-color:var(--bad)}.pill.running{color:var(--warn);border-color:var(--warn)}.pill.queued{color:var(--mut)}
.dot{display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--mut);margin-right:6px}.dot.on{background:var(--ok)}
.agent{font-weight:600}.agent.claude{color:var(--claude)}.agent.codex{color:var(--codex)}.agent.kimi,.agent.command{color:var(--kimi)}.agent.hub{color:var(--hub)}.agent.fake{color:var(--fake)}
.phases{display:flex;gap:8px;flex-wrap:wrap;margin:8px 0}.phase{padding:6px 12px;border-radius:8px;border:1px solid var(--line);color:var(--mut)}.phase.cur{border-color:var(--acc);color:var(--acc);font-weight:600}.phase.past{color:var(--ok);border-color:var(--ok)}
.cols{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:12px}
.col{background:var(--card);border:1px solid var(--line);border-radius:10px;display:flex;flex-direction:column;min-height:120px}
.col h3{margin:0;padding:8px 12px;border-bottom:1px solid var(--line);font-size:13px;display:flex;gap:8px;align-items:center}
.col .body{padding:8px 12px;overflow:auto;max-height:70vh;font-size:13px}
.msg{margin:4px 0;padding:6px 8px;border-radius:6px;border-left:3px solid var(--line);white-space:pre-wrap;word-break:break-word}
.msg.assistant{border-left-color:var(--acc)}.msg.result{border-left-color:var(--ok);background:rgba(22,163,74,.06)}.msg.thinking{color:var(--mut);font-style:italic}
.msg.tool_use{border-left-color:var(--warn);font-family:ui-monospace,Menlo,monospace;font-size:12px}.msg.tool_result{color:var(--mut);font-family:ui-monospace,Menlo,monospace;font-size:12px}
.msg.stderr{border-left-color:var(--bad);color:var(--bad);font-family:ui-monospace,Menlo,monospace;font-size:12px}.msg.system{color:var(--mut);font-size:12px}
details summary{cursor:pointer;color:var(--mut);font-size:12px}details .msg{margin-left:8px}
.tabs{display:flex;gap:4px;margin-bottom:10px}.tab{padding:6px 12px;border-radius:6px;border:1px solid var(--line);cursor:pointer;background:var(--card)}.tab.cur{border-color:var(--acc);color:var(--acc)}
.summary{white-space:pre-wrap;font-size:14px;line-height:1.6}
.timeline .msg{max-width:100%}.ts{color:var(--mut);font-size:11px;margin-right:6px}
.tiny{font-size:12px;color:var(--mut)}.mono{font-family:ui-monospace,Menlo,monospace}
form.new{display:grid;gap:8px;grid-template-columns:1fr 1fr}form.new textarea{grid-column:1/-1;min-height:90px}form.new input,form.new textarea,form.new select{font:inherit;padding:6px 8px;border:1px solid var(--line);border-radius:6px;background:var(--bg);color:var(--fg)}
button{font:inherit;padding:6px 12px;border-radius:6px;border:1px solid var(--acc);background:var(--acc);color:#fff;cursor:pointer}button.sec{background:transparent;color:var(--acc)}
</style></head><body>
<header><h1><a href="/">agent-hub</a></h1><span id="crumb" class="tiny"></span><span class="sp"></span><span id="live" class="live">○ offline</span></header>
<main id="app">loading…</main>
<script>
const $=s=>document.querySelector(s);const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const TOKEN=new URLSearchParams(location.search).get('token');
const api=async(p,body)=>{const h={'Content-Type':'application/json'};if(TOKEN)h['Authorization']='Bearer '+TOKEN;const r=await fetch(p,{method:body?'POST':'GET',headers:h,body:body?JSON.stringify(body):undefined});const j=await r.json();if(!r.ok)throw new Error(j.error||r.status);return j};
const kindOf=(name,agents)=>{const a=agents.find(x=>x.name===name);if(a)return a.kind;if(name==='hub')return'hub';for(const k of['claude','codex','kimi','fake'])if(name.startsWith(k))return k;return'command'};
const fmtTs=t=>t?t.slice(11,19):'';const pill=s=>`<span class="pill ${s}">${s}</span>`;
let agents=[],es=null;
function route(){const m=location.pathname.match(/^\/runs\/([^/]+)/);if(m)return showRun(m[1]);showHome()}
function connect(runId){if(es)es.close();es=new EventSource('/api/stream'+(runId?'?run_id='+runId:'')+(TOKEN?(runId?'&':'?')+'token='+TOKEN:''));es.onopen=()=>$('#live').textContent='● live';es.onerror=()=>$('#live').textContent='○ reconnecting';return es}
/* ---------------- home ---------------- */
async function showHome(){$('#crumb').textContent='';const [a,r]=await Promise.all([api('/api/agents'),api('/api/runs?limit=100')]);agents=a.agents;
 const app=$('#app');app.innerHTML=`<div class="card"><h3 style="margin:0 0 6px">エージェント</h3><div id="agents"></div></div>
 <div class="card"><h3 style="margin:0 0 6px">新しい run</h3><form class="new" id="newrun">
  <select name="recipe"><option value="review_panel">三者評価 (review_panel)</option><option value="parallel">並列 (parallel)</option><option value="single">単独 (single)</option></select>
  <input name="project" placeholder="project (default)">
  <input name="agents" placeholder="agents: claude-a,codex,kimi" required>
  <input name="workdir" placeholder="workdir on runner machine (optional)">
  <textarea name="prompt" placeholder="課題 / プロンプト" required></textarea>
  <div><button>開始</button> <span class="tiny">synthesizer は agents の先頭</span></div></form></div>
 <div class="card"><h3 style="margin:0 0 6px">Runs</h3><table><thead><tr><th>status</th><th>recipe</th><th>title</th><th>project</th><th>created</th></tr></thead><tbody id="runs"></tbody></table></div>`;
 renderAgents();renderRuns(r.runs);
 $('#newrun').onsubmit=async e=>{e.preventDefault();const f=new FormData(e.target);const ag=f.get('agents').split(',').map(s=>s.trim()).filter(Boolean);const recipe=f.get('recipe');
  const spec={prompt:f.get('prompt'),workdir:f.get('workdir')||null};if(recipe==='review_panel')spec.solvers=ag;else if(recipe==='parallel')spec.agents=ag;else spec.agent=ag[0];
  try{const j=await api('/api/runs',{recipe,project:f.get('project')||'default',title:f.get('prompt').slice(0,60),spec,created_by:'web'});history.pushState({},'','/runs/'+j.run.id);route()}catch(err){alert(err.message)}};
 const s=connect(null);s.addEventListener('run',async()=>{renderRuns((await api('/api/runs?limit=100')).runs)});s.addEventListener('agent',async()=>{agents=(await api('/api/agents')).agents;renderAgents()})}
function renderAgents(){const el=$('#agents');if(!el)return;el.innerHTML=agents.length?agents.map(a=>`<span style="margin-right:18px"><span class="dot ${a.online?'on':''}"></span><span class="agent ${a.kind}">${esc(a.name)}</span> <span class="tiny">${esc(a.kind)} @${esc(a.host)} ${esc(a.status)}</span></span>`).join(''):'<span class="tiny">runner が未接続</span>'}
function renderRuns(runs){const el=$('#runs');if(!el)return;el.innerHTML=runs.map(r=>`<tr><td>${pill(r.status)}</td><td>${esc(r.recipe)}</td><td><a href="/runs/${r.id}" onclick="event.preventDefault();history.pushState({},'','/runs/${r.id}');route()">${esc(r.title)}</a></td><td>${esc(r.project)}</td><td class="tiny">${esc(r.created_at.replace('T',' ').slice(0,19))}</td></tr>`).join('')||'<tr><td colspan=5 class="tiny">まだ run がありません</td></tr>'}
/* ---------------- run ---------------- */
let RUN=null,MSGS=[],lastId=0,view='cols';
async function showRun(id){agents=(await api('/api/agents')).agents;const j=await api('/api/runs/'+id);RUN=j.run;MSGS=(await api(`/api/runs/${id}/messages`)).messages;lastId=MSGS.length?MSGS[MSGS.length-1].id:0;
 $('#crumb').innerHTML=`/ <a href="/" onclick="event.preventDefault();history.pushState({},'','/');route()">runs</a> / ${esc(RUN.id)}`;
 $('#app').innerHTML=`<div class="card"><div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap"><h2 style="margin:0;font-size:16px">${esc(RUN.title)}</h2>${pill(RUN.status)}<span class="tiny">${esc(RUN.recipe)} · ${esc(RUN.project)} · ${esc(RUN.created_at.replace('T',' ').slice(0,19))}</span><span class="sp" style="flex:1"></span>${RUN.status==='running'?'<button class="sec" id="cancel">cancel</button>':''}</div>
 <div class="phases" id="phases"></div><details><summary>課題プロンプト</summary><div class="msg system">${esc(RUN.spec.prompt||'')}</div></details></div>
 <div id="final"></div>
 <div class="tabs"><span class="tab ${view==='cols'?'cur':''}" data-v="cols">エージェント別</span><span class="tab ${view==='time'?'cur':''}" data-v="time">時系列</span><span class="tab" data-v="results">結論だけ</span></div><div id="body"></div>`;
 document.querySelectorAll('.tab').forEach(t=>t.onclick=()=>{view=t.dataset.v;document.querySelectorAll('.tab').forEach(x=>x.classList.toggle('cur',x===t));renderBody()});
 const c=$('#cancel');if(c)c.onclick=async()=>{if(confirm('cancel?')){await api(`/api/runs/${id}/cancel`,{});}};
 renderRun();
 const s=connect(id);s.addEventListener('message',e=>{const m=JSON.parse(e.data).message;if(m.id>lastId){MSGS.push(m);lastId=m.id;appendMsg(m)}});
 s.addEventListener('task',e=>{const t=JSON.parse(e.data).task;const i=RUN.tasks.findIndex(x=>x.id===t.id);if(i>=0)RUN.tasks[i]=t;else RUN.tasks.push(t);renderRun()});
 s.addEventListener('run',e=>{const r=JSON.parse(e.data).run;Object.assign(RUN,{status:r.status,state:r.state,summary:r.summary});renderRun()})}
function phaseList(){if(RUN.recipe==='review_panel')return['solve','review','synthesize','finished'];return['run','finished']}
function renderRun(){const cur=RUN.state.phase;const ph=phaseList();const ci=ph.indexOf(cur);$('#phases').innerHTML=ph.map((p,i)=>`<span class="phase ${i<ci?'past':i===ci?'cur':''}">${['解く','相互レビュー','統合','完了','実行','完了'][['solve','review','synthesize','finished','run','finished'].indexOf(p)]||p}</span>`).join('');
 $('#final').innerHTML=RUN.status!=='running'&&RUN.summary?`<div class="card"><h3 style="margin:0 0 6px">${RUN.status==='done'?'最終結果':'結果'}</h3><div class="summary">${esc(RUN.summary)}</div></div>`:'';
 renderBody()}
function msgHtml(m,withActor){if(m.role==='result'&&!m.content)return`<div class="msg result tiny">✔ 完了${m.data&&m.data.total_cost_usd!=null?' · $'+m.data.total_cost_usd.toFixed(3):''}</div>`;const k=kindOf(m.actor,agents);const actor=withActor?`<span class="agent ${k}">${esc(m.actor)}</span> `:'';const body=esc(m.content.length>6000?m.content.slice(0,6000)+'…':m.content);
 if(m.role==='tool_result'||m.role==='thinking'||m.role==='stderr')return`<details><summary><span class="ts">${fmtTs(m.ts)}</span>${actor}${m.role}${m.data&&m.data.is_error?' ⚠':''} · ${esc(m.content.slice(0,80).replace(/\n/g,' '))}</summary><div class="msg ${m.role}">${body}</div></details>`;
 return`<div class="msg ${m.role}"><span class="ts">${fmtTs(m.ts)}</span>${actor}${body}</div>`}
function renderBody(){const b=$('#body');if(view==='results'){b.innerHTML=`<div class="cols">${RUN.tasks.filter(t=>t.status!=='queued').map(t=>`<div class="col"><h3><span class="agent ${kindOf(t.agent,agents)}">${esc(t.agent)}</span><span class="tiny">${esc(t.step)}</span>${pill(t.status)}</h3><div class="body"><div class="summary">${esc(t.result||t.error||'(実行中)')}</div></div></div>`).join('')}</div>`;return}
 if(view==='time'){b.innerHTML=`<div class="card timeline" id="tl">${MSGS.map(m=>msgHtml(m,true)).join('')}</div>`;return}
 const steps=[...new Set(RUN.tasks.map(t=>t.step))];b.innerHTML=steps.map(step=>`<h4 style="margin:10px 0 6px;color:var(--mut)">${esc(step)}</h4><div class="cols">${RUN.tasks.filter(t=>t.step===step).map(t=>{const meta=t.meta||{};return`<div class="col" data-task="${t.id}"><h3><span class="agent ${kindOf(t.agent,agents)}">${esc(t.agent)}</span>${pill(t.status)}<span class="tiny">${t.claimed_by?esc(t.claimed_by):''}${meta.duration_s?' · '+meta.duration_s+'s':''}${meta.usage&&meta.usage.total_cost_usd!=null?' · $'+meta.usage.total_cost_usd.toFixed(3):''}</span></h3><div class="body">${MSGS.filter(m=>m.task_id===t.id).map(m=>msgHtml(m,false)).join('')||'<span class="tiny">待機中…</span>'}</div></div>`}).join('')}</div>`).join('')+(MSGS.filter(m=>!m.task_id).length?`<h4 style="margin:10px 0 6px;color:var(--mut)">hub</h4><div class="card">${MSGS.filter(m=>!m.task_id).map(m=>msgHtml(m,true)).join('')}</div>`:'');
 document.querySelectorAll('.col .body').forEach(el=>el.scrollTop=el.scrollHeight)}
function appendMsg(m){if(view==='time'){const tl=$('#tl');if(tl){tl.insertAdjacentHTML('beforeend',msgHtml(m,true));}return}
 if(view==='cols'){const col=document.querySelector(`.col[data-task="${m.task_id}"] .body`);if(col){if(col.querySelector('.tiny'))col.innerHTML='';col.insertAdjacentHTML('beforeend',msgHtml(m,false));col.scrollTop=col.scrollHeight;return}}
 renderBody()}
window.onpopstate=route;route();
</script></body></html>
"""
