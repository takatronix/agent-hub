"""Single-page web UI (vanilla JS, served inline).

Design goals: simple, beautiful, responsive (phone / tablet / desktop), animated.
"""
INDEX_HTML = r"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><title>agent-hub</title>
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#0b0d12">
<link rel="preconnect" href="https://fonts.googleapis.com"><link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Noto+Sans+JP:wght@400;500;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
:root{--bg:#0b0d12;--bg2:#12151c;--card:#161a23;--card2:#1c212c;--line:#262c39;--fg:#e8ebf1;--mut:#8b93a5;--dim:#5c6478;
 --acc:#5b8cff;--acc2:#8b5cf6;--ok:#22c55e;--bad:#ef4444;--warn:#f59e0b;
 --claude:#f97316;--codex:#14b8a6;--api:#a78bfa;--kimi:#ec4899;--command:#38bdf8;--cursor:#e2e8f0;--fake:#6b7280;--hub:#94a3b8;
 --r:16px;--sans:"Inter","Noto Sans JP",-apple-system,"Hiragino Sans",system-ui,sans-serif;--mono:"JetBrains Mono",ui-monospace,Menlo,monospace}
:root[data-theme="light"]{--bg:#f4f6fb;--bg2:#ffffff;--card:#ffffff;--card2:#f1f4fa;--line:#e2e6ef;--fg:#141824;--mut:#606a7e;--dim:#9aa3b5}
.theme{cursor:pointer;font-size:15px;opacity:.7;transition:.2s;user-select:none}.theme:hover{opacity:1;transform:rotate(20deg)}
*{box-sizing:border-box}html{background:var(--bg);scroll-behavior:smooth}
body{margin:0;font:14px/1.6 var(--sans);color:var(--fg);min-height:100vh;background:var(--bg);overflow-x:hidden}
body:before{content:"";position:fixed;inset:0;z-index:-1;background:radial-gradient(900px 500px at 15% -10%,rgba(91,140,255,.22),transparent 60%),radial-gradient(800px 500px at 100% 0%,rgba(139,92,246,.18),transparent 55%);animation:drift 24s ease-in-out infinite alternate}
@keyframes drift{from{transform:translate3d(0,0,0)}to{transform:translate3d(-3%,2%,0) scale(1.05)}}
a{color:var(--acc);text-decoration:none}
header{display:flex;gap:12px;align-items:center;padding:12px 18px;border-bottom:1px solid var(--line);background:color-mix(in srgb,var(--bg) 75%,transparent);backdrop-filter:blur(14px);position:sticky;top:0;z-index:5}
header .logo{font-weight:700;font-size:17px;background:linear-gradient(90deg,#7aa2ff,#b388ff);-webkit-background-clip:text;background-clip:text;color:transparent}
header .crumb{color:var(--mut);font-size:13px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}header .sp{flex:1}
.live{font-size:12px;color:var(--mut);display:flex;align-items:center;gap:6px;white-space:nowrap}.live b{width:8px;height:8px;border-radius:50%;background:var(--dim);display:inline-block;transition:.3s}.live.on b{background:var(--ok);box-shadow:0 0 0 4px rgba(34,197,94,.15);animation:beat 2s infinite}
@keyframes beat{0%,100%{box-shadow:0 0 0 3px rgba(34,197,94,.15)}50%{box-shadow:0 0 0 7px rgba(34,197,94,0)}}
main{max-width:1500px;margin:0 auto;padding:18px}@media(max-width:640px){main{padding:12px}}
.grid{display:grid;grid-template-columns:320px 1fr;gap:18px;align-items:start}.grid>*{min-width:0}@media(max-width:980px){.grid{grid-template-columns:1fr}}
.card{background:var(--card);border:1px solid var(--line);border-radius:var(--r);padding:16px 18px;margin-bottom:16px;box-shadow:0 10px 30px rgba(0,0,0,.18);animation:rise .45s cubic-bezier(.2,.7,.2,1) both}
.card:nth-child(2){animation-delay:.06s}.card:nth-child(3){animation-delay:.12s}
@keyframes rise{from{opacity:0;transform:translateY(12px)}to{opacity:1;transform:none}}
@keyframes fadein{from{opacity:0}to{opacity:1}}
@keyframes slidein{from{opacity:0;transform:translateX(-8px)}to{opacity:1;transform:none}}
@keyframes pop{0%{transform:scale(.6);opacity:0}70%{transform:scale(1.08)}100%{transform:scale(1);opacity:1}}
@keyframes shimmer{from{background-position:200% 0}to{background-position:-200% 0}}
.card h2{margin:0 0 2px;font-size:15px;font-weight:600}.card .sub{color:var(--mut);font-size:12.5px;margin-bottom:12px}
.step{display:flex;gap:10px;align-items:baseline;margin:16px 0 8px}.step .n{width:24px;height:24px;border-radius:50%;background:linear-gradient(135deg,var(--acc),var(--acc2));color:#fff;font-weight:700;font-size:12px;display:inline-flex;align-items:center;justify-content:center;flex:none;transform:translateY(5px)}.step h3{margin:0;font-size:14px;font-weight:600}.step span{color:var(--mut);font-size:12px}
textarea,input,select{font:inherit;color:var(--fg);background:var(--bg2);border:1px solid var(--line);border-radius:12px;padding:11px 13px;width:100%;outline:none;transition:.2s}textarea:focus,input:focus,select:focus{border-color:var(--acc);box-shadow:0 0 0 4px rgba(91,140,255,.15)}
textarea{min-height:120px;resize:vertical;line-height:1.55}
button{font:inherit;font-weight:600;padding:11px 20px;border-radius:12px;border:0;background:linear-gradient(135deg,var(--acc),var(--acc2));color:#fff;cursor:pointer;box-shadow:0 8px 22px rgba(91,140,255,.28);transition:.2s;-webkit-tap-highlight-color:transparent}
button:hover:not(:disabled){transform:translateY(-1px);box-shadow:0 12px 28px rgba(91,140,255,.38)}button:active:not(:disabled){transform:translateY(0) scale(.98)}button:disabled{opacity:.35;cursor:not-allowed;box-shadow:none}
button.ghost{background:transparent;border:1px solid var(--line);color:var(--fg);box-shadow:none}button.ghost:hover{border-color:var(--acc)}
.tiny{font-size:12px;color:var(--mut)}.mono{font-family:var(--mono)}
/* agents */
.host{margin-bottom:12px}.host .hn{font-size:11px;letter-spacing:1px;text-transform:uppercase;color:var(--dim);margin:0 0 6px 4px;display:flex;justify-content:space-between}
.ag{display:flex;gap:10px;align-items:center;min-height:52px;padding:8px 10px;border-radius:12px;border:1px solid transparent;cursor:pointer;transition:.18s;user-select:none;animation:slidein .35s both}
.ag:hover{background:var(--card2)}.ag.sel{border-color:var(--acc);background:rgba(91,140,255,.09)}.ag.off{opacity:.42;cursor:default}
.av{width:32px;height:32px;border-radius:10px;display:inline-flex;align-items:center;justify-content:center;font-weight:700;font-size:12px;color:#fff;flex:none;position:relative;box-shadow:inset 0 -6px 12px rgba(0,0,0,.25)}
.ag .nm{font-weight:600;font-size:13px;line-height:1.25}.ag .ds{font-size:11px;color:var(--mut)}.ag .chk{margin-left:auto;font-size:12px;color:var(--acc);font-weight:700;animation:pop .3s both}
.dot{width:8px;height:8px;border-radius:50%;background:var(--dim);display:inline-block;margin-left:auto;flex:none}.dot.on{background:var(--ok)}.dot.busy{background:var(--warn);animation:beat 1.2s infinite}
.c-claude{background:var(--claude)}.c-codex{background:var(--codex)}.c-api{background:var(--api)}.c-kimi{background:var(--kimi)}.c-command{background:var(--command)}.c-cursor{background:var(--cursor);color:#111}.c-fake{background:var(--fake)}.c-hub{background:var(--hub)}
.t-claude{color:var(--claude)}.t-codex{color:var(--codex)}.t-api{color:var(--api)}.t-kimi{color:var(--kimi)}.t-command{color:var(--command)}.t-cursor{color:var(--cursor)}.t-fake{color:var(--fake)}.t-hub{color:var(--hub)}
@media(max-width:980px){aside .card{padding:12px}#agents{display:flex;gap:12px;overflow-x:auto;padding-bottom:4px;scroll-snap-type:x mandatory}.host{min-width:240px;scroll-snap-align:start;flex:none}}
/* recipes */
.recipes{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px}.rc{border:1px solid var(--line);border-radius:14px;padding:12px 14px;cursor:pointer;background:var(--bg2);transition:.18s}.rc:hover{border-color:var(--dim);transform:translateY(-1px)}.rc.sel{border-color:var(--acc);background:rgba(91,140,255,.09);box-shadow:0 0 0 3px rgba(91,140,255,.12)}.rc b{display:block;margin-bottom:3px}.rc span{font-size:12px;color:var(--mut)}
.picked{display:flex;gap:6px;flex-wrap:wrap;min-height:32px;align-items:center}.chip{display:inline-flex;gap:6px;align-items:center;background:var(--card2);border:1px solid var(--line);border-radius:999px;padding:3px 10px 3px 4px;font-size:12px;animation:pop .25s both}.chip .av{width:22px;height:22px;border-radius:7px;font-size:9px}.chip a{color:var(--mut)}
.row{display:flex;gap:10px;flex-wrap:wrap;align-items:center}.row>*{flex:1;min-width:180px}
/* runs list */
.run{display:grid;grid-template-columns:auto 1fr auto;gap:12px;align-items:center;padding:12px 14px;border:1px solid var(--line);border-radius:14px;margin-bottom:8px;background:var(--bg2);cursor:pointer;transition:.18s;animation:slidein .35s both}.run:hover{border-color:var(--acc);transform:translateX(2px)}
.run .ti{font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.run .me{font-size:12px;color:var(--mut)}.avs{display:flex}.avs .av{width:26px;height:26px;border-radius:8px;font-size:9px;margin-left:-7px;border:2px solid var(--bg2)}.avs .av:first-child{margin-left:0}
@media(max-width:640px){.run{grid-template-columns:auto 1fr}.run .avs{grid-column:2;justify-content:flex-end}}
.pill{display:inline-block;padding:2px 9px;border-radius:999px;font-size:11px;font-weight:600;border:1px solid var(--line);color:var(--mut);white-space:nowrap}
.pill.done{color:var(--ok);border-color:rgba(34,197,94,.4);background:rgba(34,197,94,.08)}.pill.failed,.pill.cancelled{color:var(--bad);border-color:rgba(239,68,68,.4)}.pill.running{color:var(--warn);border-color:rgba(245,158,11,.4);background:rgba(245,158,11,.08)}.pill.queued{color:var(--mut)}
/* run page */
.flow{display:flex;align-items:stretch;margin:14px 0 8px;overflow-x:auto;padding:4px 2px;gap:0}.fs{flex:1;min-width:150px;padding:12px 14px;border:1px solid var(--line);border-radius:14px;background:var(--bg2);position:relative;transition:.3s}.fs+.fs{margin-left:26px}.fs+.fs:before{content:"";position:absolute;left:-26px;top:50%;width:26px;height:2px;background:var(--line)}
.fs.cur{border-color:var(--warn);box-shadow:0 0 0 3px rgba(245,158,11,.12)}.fs.cur:after{content:"";position:absolute;inset:0;border-radius:14px;background:linear-gradient(90deg,transparent,rgba(245,158,11,.08),transparent);background-size:200% 100%;animation:shimmer 2s linear infinite;pointer-events:none}
.fs.past{border-color:rgba(34,197,94,.5)}.fs .fh{font-weight:600;font-size:13px;display:flex;justify-content:space-between}.fs .fd{font-size:11.5px;color:var(--mut);margin:2px 0 8px}
.bar{height:4px;border-radius:99px;background:var(--line);overflow:hidden;margin-top:8px}.bar i{display:block;height:100%;background:linear-gradient(90deg,var(--acc),var(--acc2));width:0;transition:width .6s cubic-bezier(.2,.7,.2,1)}
.cols{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:14px}@media(max-width:640px){.cols{grid-template-columns:1fr}}
.col{background:var(--card);border:1px solid var(--line);border-radius:var(--r);display:flex;flex-direction:column;min-height:100px;overflow:hidden;animation:rise .4s both}
.col h3{margin:0;padding:10px 14px;border-bottom:1px solid var(--line);font-size:13px;display:flex;gap:10px;align-items:center;background:var(--card2)}
.col .body{padding:10px 14px;overflow:auto;max-height:70vh;font-size:13px}@media(max-width:640px){.col .body{max-height:60vh}}
.msg{margin:6px 0;padding:8px 10px;border-radius:10px;border-left:3px solid var(--line);white-space:pre-wrap;word-break:break-word;background:rgba(255,255,255,.02);animation:slidein .3s both}
.msg.assistant{border-left-color:var(--acc);white-space:normal}.msg.result{border-left-color:var(--ok)}.msg.thinking{color:var(--mut);font-style:italic;border-left-color:var(--dim)}
.msg.tool_use{border-left-color:var(--warn);font-family:var(--mono);font-size:12px}.msg.tool_result{color:var(--mut);font-family:var(--mono);font-size:12px;border-left-color:var(--dim)}
.msg.stderr{border-left-color:var(--bad);color:#fca5a5;font-family:var(--mono);font-size:12px}.msg.system{color:var(--dim);font-size:11.5px;font-family:var(--mono);border-left-color:transparent;background:none}
details summary{cursor:pointer;color:var(--mut);font-size:12px;padding:3px 0;list-style:none}details summary::-webkit-details-marker{display:none}details summary:before{content:"▸ ";color:var(--dim)}details[open] summary:before{content:"▾ "}details .msg{margin-left:10px}
.ts{color:var(--dim);font-size:11px;margin-right:6px;font-family:var(--mono)}
.tabs{display:flex;gap:6px;margin:6px 0 12px;overflow-x:auto}.tab{padding:7px 14px;border-radius:999px;border:1px solid var(--line);cursor:pointer;font-size:13px;color:var(--mut);white-space:nowrap;transition:.18s}.tab.cur{border-color:var(--acc);color:var(--fg);background:rgba(91,140,255,.1)}
.final{border:1px solid rgba(34,197,94,.35);background:linear-gradient(180deg,rgba(34,197,94,.07),transparent 40%),var(--card)}
.typing{display:inline-flex;gap:4px;align-items:center;padding:6px 2px}.typing i{width:6px;height:6px;border-radius:50%;background:var(--mut);animation:tb 1.2s infinite}.typing i:nth-child(2){animation-delay:.2s}.typing i:nth-child(3){animation-delay:.4s}
@keyframes tb{0%,80%,100%{transform:translateY(0);opacity:.4}40%{transform:translateY(-5px);opacity:1}}
/* markdown */
.md{line-height:1.7;overflow-wrap:anywhere}.md h1,.md h2,.md h3{margin:16px 0 6px;font-size:15px;font-weight:700;padding-bottom:4px;border-bottom:1px solid var(--line)}.md h3{font-size:14px;border:0}.md p{margin:6px 0}.md ul,.md ol{margin:6px 0;padding-left:22px}.md li{margin:2px 0}
.md pre{background:#0a0c11;color:#e8ebf1;border:1px solid var(--line);border-radius:12px;padding:12px 14px;overflow-x:auto;font-family:var(--mono);font-size:12.5px;line-height:1.5;margin:8px 0}.md code{font-family:var(--mono);font-size:12.5px;background:rgba(127,127,127,.15);padding:1px 5px;border-radius:5px}.md pre code{background:none;padding:0}
.md blockquote{border-left:3px solid var(--acc2);margin:8px 0;padding:2px 12px;color:var(--mut)}.md table{border-collapse:collapse;margin:8px 0;max-width:100%;display:block;overflow-x:auto}.md td,.md th{border:1px solid var(--line);padding:4px 8px}
.stat{display:flex;gap:16px;flex-wrap:wrap;font-size:12px;color:var(--mut)}.stat b{color:var(--fg);font-weight:600}
.empty{padding:26px;text-align:center;color:var(--dim)}
.skel{height:14px;border-radius:6px;background:linear-gradient(90deg,var(--card2),var(--line),var(--card2));background-size:200% 100%;animation:shimmer 1.4s linear infinite;margin:8px 0}
.toast{position:fixed;left:50%;bottom:24px;transform:translateX(-50%) translateY(20px);background:var(--card2);border:1px solid var(--line);padding:10px 16px;border-radius:12px;opacity:0;transition:.3s;z-index:9;box-shadow:0 10px 30px rgba(0,0,0,.3)}.toast.show{opacity:1;transform:translateX(-50%)}
</style></head><body>
<header><a class="logo" href="/" onclick="event.preventDefault();go('/')">agent-hub</a><span id="crumb" class="crumb"></span><span class="sp"></span><span id="live" class="live"><b></b>offline</span><span class="theme" id="theme" title="テーマ切替">☾</span></header>
<main id="app"><div class="card"><div class="skel" style="width:40%"></div><div class="skel"></div><div class="skel" style="width:70%"></div></div></main>
<div class="toast" id="toast"></div>
<script>
const $=s=>document.querySelector(s);
(function(){let t=null;try{t=localStorage.getItem('theme')}catch(e){}if(t)document.documentElement.dataset.theme=t;document.addEventListener('DOMContentLoaded',()=>{const b=$('#theme');const sync=()=>b.textContent=document.documentElement.dataset.theme==='light'?'☀':'☾';sync();b.onclick=()=>{const n=document.documentElement.dataset.theme==='light'?'dark':'light';document.documentElement.dataset.theme=n;try{localStorage.setItem('theme',n)}catch(e){}sync()}})})();const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
let TOKEN=new URLSearchParams(location.search).get('token');try{if(TOKEN)localStorage.setItem('hub_token',TOKEN);else TOKEN=localStorage.getItem('hub_token')}catch(e){}const Q=TOKEN?'?token='+TOKEN:'';
if(TOKEN&&!location.search.includes('token='))history.replaceState({},'',location.pathname+Q);
const go=p=>{history.pushState({},'',p+Q);route()};
const toast=t=>{const e=$('#toast');e.textContent=t;e.classList.add('show');clearTimeout(e._t);e._t=setTimeout(()=>e.classList.remove('show'),2600)};
const api=async(p,body)=>{const h={'Content-Type':'application/json'};if(TOKEN)h['Authorization']='Bearer '+TOKEN;const r=await fetch(p,{method:body?'POST':'GET',headers:h,body:body?JSON.stringify(body):undefined});const j=await r.json();if(!r.ok)throw new Error(j.error||r.status);return j};
const KIND={claude:['Claude Code','ファイル・コマンド OK'],codex:['Codex CLI','ファイル・コマンド OK'],command:['CLI','ファイル・コマンド OK'],cursor:['Cursor CLI','ファイル・コマンド OK'],kimi:['Kimi CLI','ファイル・コマンド OK'],api:['API / ローカル LLM','テキストのみ'],fake:['ダミー','配線テスト用'],hub:['hub','']};
const CAT_JA={algorithm:'アルゴリズム',robotics:'ロボット/ROS',debugging:'デバッグ',design:'設計',docs:'文書/仕様',math:'数理',data:'データ',web:'Web',infra:'インフラ',other:'その他'};
const RECIPES=[['review_panel','三者評価','全員が独立に解く → 互いにレビュー → 統合役がまとめる'],['parallel','並列','同じ課題を全員に投げて回答を並べる'],['single','単独','1人に1つ頼む']];
const PHASES={review_panel:[['solve','解く','全員が独立に回答'],['review','相互レビュー','他人の回答を批評'],['synthesize','統合','最終回答をまとめる']],parallel:[['run','実行','全員が回答']],single:[['run','実行','']]};
const kindOf=n=>{const a=agents.find(x=>x.name===n);if(a)return a.kind;if(n==='hub')return'hub';for(const k of['claude','codex','kimi','cursor','qwen','grok','fake'])if(n.startsWith(k))return (k==='qwen'||k==='grok')?'api':k;return'command'};
const initials=n=>({claude:'C',codex:'X',api:'A',kimi:'K',cursor:'U',command:'T',fake:'F',hub:'H'}[kindOf(n)]||'?');
const av=(n,cls='')=>`<span class="av c-${kindOf(n)} ${cls}" title="${esc(n)}">${initials(n)}</span>`;
const fmtTs=t=>t?t.slice(11,19):'';const fmtDt=t=>t?t.replace('T',' ').slice(5,16):'';const pill=s=>`<span class="pill ${s}">${({done:'完了',failed:'失敗',cancelled:'中止',running:'実行中',queued:'待機'}[s]||s)}</span>`;
let agents=[],es=null;
function connect(runId){if(es)es.close();es=new EventSource('/api/stream'+(runId?'?run_id='+runId:'')+(TOKEN?(runId?'&':'?')+'token='+TOKEN:''));es.onopen=()=>{$('#live').className='live on';$('#live').innerHTML='<b></b>live'};es.onerror=()=>{$('#live').className='live';$('#live').innerHTML='<b></b>reconnecting'};return es}
function route(){const m=location.pathname.match(/^\/runs\/([^/]+)/);if(m)return showRun(m[1]);showHome()}
/* markdown (escape first, then format) */
function md(src){let t=esc(src||'');const blocks=[];t=t.replace(/```([\w+-]*)\n([\s\S]*?)```/g,(m,l,c)=>{blocks.push(`<pre><code>${c.replace(/\n$/,'')}</code></pre>`);return`\uE000${blocks.length-1}\uE000`});
 t=t.replace(/`([^`\n]+)`/g,'<code>$1</code>').replace(/^#{3,6} (.*)$/gm,'<h3>$1</h3>').replace(/^## (.*)$/gm,'<h2>$1</h2>').replace(/^# (.*)$/gm,'<h1>$1</h1>')
 .replace(/\*\*([^*\n]+)\*\*/g,'<strong>$1</strong>').replace(/(^|[^*\w])\*([^*\n]+)\*/g,'$1<em>$2</em>').replace(/^&gt; ?(.*)$/gm,'<blockquote>$1</blockquote>').replace(/\[([^\]]+)\]\((https?:[^)]+)\)/g,'<a href="$2" target="_blank" rel="noopener">$1</a>');
 const out=[];let list=null;for(const ln of t.split('\n')){const ul=ln.match(/^\s*[-*・] (.*)$/),ol=ln.match(/^\s*\d+[.)] (.*)$/);const typ=ul?'ul':ol?'ol':null;
  if(typ){if(list!==typ){if(list)out.push(`</${list}>`);out.push(`<${typ}>`);list=typ}out.push(`<li>${(ul||ol)[1]}</li>`)}
  else{if(list){out.push(`</${list}>`);list=null}if(/^<(h\d|pre|blockquote)/.test(ln)||/^\uE000\d+\uE000$/.test(ln))out.push(ln);else if(ln.trim()==='')out.push('');else out.push(`<p>${ln}</p>`)}}
 if(list)out.push(`</${list}>`);return out.join('\n').replace(/\uE000(\d+)\uE000/g,(m,i)=>blocks[+i])}
/* ---------------- home ---------------- */
let selected=[],recipe='review_panel',models={};
const MODELS={claude:['','opus','fable','sonnet','haiku'],codex:['','gpt-5.5','gpt-5.5-codex','o4-mini'],api:['']};
function modelSel(n){const k=kindOf(n);const opts=MODELS[k];if(!opts||opts.length<2)return'';const a=agents.find(x=>x.name===n);const def=(a&&a.meta&&a.meta.model)||'既定';return`<select class="msel" title="この run で使うモデル（既定: ${def}）" onclick="event.stopPropagation()" onchange="models['${n}']=this.value||undefined;updateForm()" style="width:auto;padding:2px 6px;border-radius:8px;font-size:11px;background:var(--bg2);border:1px solid var(--line);color:${models[n]?'var(--acc)':'var(--mut)'}">${opts.map(o=>`<option value="${o}" ${(models[n]||'')===o?'selected':''}>${o||def}</option>`).join('')}</select>`}
async function showHome(){$('#crumb').textContent='';const [a,r]=await Promise.all([api('/api/agents'),api('/api/runs?limit=100')]);agents=a.agents;selected=selected.filter(n=>agents.some(x=>x.name===n&&x.online));
 $('#app').innerHTML=`<div class="grid">
 <aside><div class="card"><h2>エージェント</h2><div class="sub">タップして参加者に追加</div><div id="agents"></div></div></aside>
 <section>
  <div class="card"><h2>新しいミッション</h2><div class="sub">課題を書く → 誰に頼むか選ぶ → 開始。AI 同士のやりとりは全部記録されます</div>
   <div class="step"><span class="n">1</span><h3>課題</h3><span>やってほしいこと</span></div>
   <textarea id="prompt" placeholder="例：/home/aspa1/aspa-navigation の localization が周期的に飛ぶ原因を特定し、修正案とテスト手順を示せ"></textarea>
   <div class="row" style="margin-top:8px"><input id="workdir" placeholder="作業ディレクトリ（実行マシン上のパス／ファイルを触らないなら空）"><input id="project" placeholder="project 名（省略可）" style="flex:0 1 220px"></div>
   <div class="step"><span class="n">2</span><h3>誰に頼むか</h3><span>左のエージェントをタップ、または</span><button class="ghost" id="cast" style="padding:4px 12px;font-size:12px">✨ おすすめの顔ぶれ</button><span class="tiny" id="castnote"></span></div>
   <div class="picked" id="picked"></div>
   <div class="step"><span class="n">3</span><h3>進め方</h3></div>
   <div class="recipes" id="recipes"></div>
   <div class="row" id="synthrow" style="margin-top:10px"><label style="flex:0 1 420px"><span class="tiny">統合役（最終回答をまとめる人。Claude / Codex 推奨）</span><select id="synth"></select></label></div>
   <div style="margin-top:16px;display:flex;gap:12px;align-items:center;flex-wrap:wrap"><button id="start">🚀 開始</button><span class="tiny" id="hint"></span></div>
  </div>
  <div class="card"><h2>ミッション履歴</h2><div class="sub">過去のやりとりは全部ここに残ります</div><div id="runs"></div></div>
  <div class="card"><h2>成績表 <span class="tiny">匿名審査リーグ</span></h2><div class="sub">レビュー時は回答者を伏せて採点。誰が何に強いかが溜まっていき、「おすすめの顔ぶれ」に使われます</div><div id="board"></div></div>
 </section></div>`;
 renderAgents();renderRuns(r.runs);renderRecipes();updateForm();renderBoard();
 $('#start').onclick=start;
 $('#cast').onclick=async()=>{const prompt=$('#prompt').value.trim();if(!prompt)return toast('先に課題を書いてください（内容からカテゴリを判定します）');const j=await api('/api/recommend',{prompt,k:3});const rec=j.recommend;selected=rec.solvers.filter(n=>agents.some(a=>a.name===n&&a.online));recipe='review_panel';renderRecipes();renderAgents();updateForm();if(rec.synthesizer)$('#synth').value=rec.synthesizer;$('#castnote').textContent=`カテゴリ「${CAT_JA[rec.category]||rec.category}」の成績から選びました`;toast('顔ぶれを提案しました')};
 const s=connect(null);s.addEventListener('run',async()=>{renderRuns((await api('/api/runs?limit=100')).runs)});s.addEventListener('agent',async()=>{agents=(await api('/api/agents')).agents;renderAgents()})}
function renderRecipes(){$('#recipes').innerHTML=RECIPES.map(([k,n,d])=>`<div class="rc ${recipe===k?'sel':''}" onclick="recipe='${k}';renderRecipes();updateForm()"><b>${n}</b><span>${d}</span></div>`).join('')}
function updateForm(){$('#synthrow').style.display=recipe==='review_panel'?'flex':'none';const sy=$('#synth');const cur=sy.value;sy.innerHTML=selected.map(n=>`<option value="${n}">${n}</option>`).join('');if(selected.includes(cur))sy.value=cur;
 $('#picked').innerHTML=selected.length?selected.map(n=>`<span class="chip">${av(n)}${esc(n)}${modelSel(n)}<a href="#" onclick="toggleAgent('${n}');return false">✕</a></span>`).join(''):'<span class="tiny">まだ誰も選ばれていません</span>';
 const need=recipe==='review_panel'?2:1;$('#start').disabled=selected.length<need;$('#hint').textContent=selected.length<need?`あと ${need-selected.length} 人選んでください`:(recipe==='single'?`${selected[0]} に頼みます`:`${selected.length} 人で実行します`)}
function toggleAgent(n){const i=selected.indexOf(n);if(i>=0)selected.splice(i,1);else selected.push(n);renderAgents();updateForm()}
async function forgetAgent(n){if(!confirm(n+' を一覧から消しますか？'))return;await api('/api/agents/'+encodeURIComponent(n)+'/delete',{});agents=(await api('/api/agents')).agents;renderAgents();toast('消しました')}
function renderAgents(){const el=$('#agents');if(!el)return;if(!agents.length){el.innerHTML='<div class="empty">runner が未接続</div>';return}
 const hosts=[...new Set(agents.map(a=>a.host||'?'))];let i=0;
 el.innerHTML=hosts.map(h=>`<div class="host"><div class="hn"><span>🖥 ${esc(h)}</span><span>${agents.filter(a=>a.host===h&&a.online).length}/${agents.filter(a=>a.host===h).length}</span></div>`+agents.filter(a=>(a.host||'?')===h).map(a=>{const on=a.online,sel=selected.includes(a.name),k=KIND[a.kind]||[a.kind,''];
  return`<div class="ag ${sel?'sel':''} ${on?'':'off'}" style="animation-delay:${(i++)*40}ms" onclick="${on?`toggleAgent('${a.name}')`:''}">${av(a.name)}<div style="min-width:0"><div class="nm">${esc(a.name)}</div><div class="ds">${esc(k[0])}${MODELS[a.kind]&&MODELS[a.kind].length>1?' · '+modelSel(a.name):(a.meta&&a.meta.model?' · '+esc(a.meta.model):'')}</div></div>${sel?'<span class="chk">✓</span>':on?`<span class="dot ${a.status==='busy'?'busy':'on'}" title="${a.status==='busy'?'作業中':'待機中'}"></span>`:`<a href="#" class="chk" style="color:var(--dim)" onclick="event.stopPropagation();forgetAgent('${a.name}');return false">✕</a>`}</div>`}).join('')+`</div>`).join('')}
async function renderBoard(){const el=$('#board');if(!el)return;const j=await api('/api/leaderboard');const b=j.leaderboard;const names=Object.keys(b);if(!names.length){el.innerHTML='<div class="empty">まだ採点データがありません。三者評価を 1 回走らせると埋まります</div>';return}
 const cats=[...new Set(names.flatMap(n=>Object.keys(b[n])))].filter(c=>c!=='all');cats.sort();
 const cell=d=>d?`<b>${d.avg!=null?d.avg.toFixed(1):'–'}</b><span class="tiny"> /${d.n}${d.best?' ★'+d.best:''}${d.adopted?' ✔'+d.adopted:''}</span>`:'<span class="tiny">–</span>';
 names.sort((x,y)=>((b[y].all||{}).avg||0)-((b[x].all||{}).avg||0));
 el.innerHTML=`<div style="overflow-x:auto"><table style="border-collapse:collapse;width:100%;font-size:13px"><thead><tr><th style="text-align:left;padding:6px 8px;color:var(--mut);font-weight:500">エージェント</th><th style="text-align:left;padding:6px 8px;color:var(--mut);font-weight:500">総合</th>${cats.map(c=>`<th style="text-align:left;padding:6px 8px;color:var(--mut);font-weight:500">${CAT_JA[c]||c}</th>`).join('')}</tr></thead><tbody>${names.map(n=>`<tr style="border-top:1px solid var(--line)"><td style="padding:6px 8px;white-space:nowrap">${av(n)} <b class="t-${kindOf(n)}">${esc(n)}</b></td><td style="padding:6px 8px">${cell(b[n].all)}</td>${cats.map(c=>`<td style="padding:6px 8px">${cell(b[n][c])}</td>`).join('')}</tr>`).join('')}</tbody></table></div><div class="tiny" style="margin-top:6px">平均点 /件数 ・ ★ 最良に選ばれた回数 ・ ✔ 統合で採用された回数</div>`}
function renderRuns(runs){const el=$('#runs');if(!el)return;if(!runs.length){el.innerHTML='<div class="empty">まだミッションがありません</div>';return}
 el.innerHTML=runs.map((r,i)=>{const parts=r.spec.solvers||r.spec.agents||(r.spec.agent?[r.spec.agent]:[]);const ph=(PHASES[r.recipe]||[]).find(p=>p[0]===r.state.phase);
  return`<div class="run" style="animation-delay:${i*30}ms" onclick="go('/runs/${r.id}')"><div>${pill(r.status)}</div><div style="min-width:0"><div class="ti">${esc(r.title)}</div><div class="me">${RECIPES.find(x=>x[0]===r.recipe)?.[1]||r.recipe}${r.status==='running'&&ph?' · '+ph[1]+'中':''} · ${esc(r.project)} · ${fmtDt(r.created_at)}</div></div><div class="avs">${parts.map(n=>av(n)).join('')}</div></div>`}).join('')}
async function start(){const prompt=$('#prompt').value.trim();if(!prompt)return toast('課題を書いてください');
 const spec={prompt,workdir:$('#workdir').value||null,models:Object.fromEntries(selected.filter(n=>models[n]).map(n=>[n,models[n]]))};if(recipe==='review_panel'){spec.solvers=selected;spec.synthesizer=$('#synth').value||selected[0]}else if(recipe==='parallel')spec.agents=selected;else spec.agent=selected[0];
 try{const j=await api('/api/runs',{recipe,project:$('#project').value||'default',title:prompt.split('\n')[0].slice(0,70),spec,created_by:'web'});toast('開始しました');go('/runs/'+j.run.id)}catch(e){toast(e.message)}}
/* ---------------- run ---------------- */
let RUN=null,MSGS=[],lastId=0,view='cols';
async function showRun(id){agents=(await api('/api/agents')).agents;const j=await api('/api/runs/'+id);RUN=j.run;MSGS=(await api(`/api/runs/${id}/messages`)).messages;lastId=MSGS.length?MSGS[MSGS.length-1].id:0;view=RUN.status==='done'?'results':'cols';
 $('#crumb').innerHTML=`/ <a href="/" onclick="event.preventDefault();go('/')">missions</a> / ${esc(RUN.title.slice(0,40))}`;
 $('#app').innerHTML=`<div class="card"><div style="display:flex;gap:12px;align-items:center;flex-wrap:wrap"><h2 style="font-size:17px;flex:1 1 300px">${esc(RUN.title)}</h2>${pill(RUN.status)}${RUN.status==='running'?'<button class="ghost" id="cancel">中止</button>':''}</div>
  <div class="tiny">${RECIPES.find(x=>x[0]===RUN.recipe)?.[1]||RUN.recipe} · ${esc(RUN.project)} · ${fmtDt(RUN.created_at)}</div>
  <div class="flow" id="flow"></div><div class="stat" id="stat"></div>
  <details style="margin-top:8px"><summary>課題プロンプトを見る</summary><div class="msg system" style="white-space:pre-wrap;color:var(--mut)">${esc(RUN.spec.prompt||'')}</div></details></div>
  <div id="final"></div>
  <div class="tabs"><span class="tab" data-v="results">結論だけ</span><span class="tab" data-v="cols">エージェント別（全過程）</span><span class="tab" data-v="time">時系列</span></div><div id="body"></div>`;
 document.querySelectorAll('.tab').forEach(t=>t.onclick=()=>{view=t.dataset.v;renderRun()});
 const c=$('#cancel');if(c)c.onclick=async()=>{if(confirm('中止しますか？'))await api(`/api/runs/${id}/cancel`,{})};
 renderRun();
 const s=connect(id);s.addEventListener('message',e=>{const m=JSON.parse(e.data).message;if(m.id>lastId){MSGS.push(m);lastId=m.id;appendMsg(m)}});
 s.addEventListener('task',e=>{const t=JSON.parse(e.data).task;const i=RUN.tasks.findIndex(x=>x.id===t.id);if(i>=0)RUN.tasks[i]=t;else RUN.tasks.push(t);renderRun()});
 s.addEventListener('run',e=>{const r=JSON.parse(e.data).run;const was=RUN.status;Object.assign(RUN,{status:r.status,state:r.state,summary:r.summary});if(was==='running'&&r.status!=='running'){view='results';toast(r.status==='done'?'✅ ミッション完了':'ミッション終了: '+r.status);window.scrollTo({top:0,behavior:'smooth'})}renderRun()})}
function renderRun(){const ph=PHASES[RUN.recipe]||[];const cur=RUN.state.phase;const ci=ph.findIndex(p=>p[0]===cur);const finished=RUN.status!=='running';
 $('#flow').innerHTML=ph.map((p,i)=>{const ts=RUN.tasks.filter(t=>t.step===p[0]);const done=ts.filter(t=>t.status==='done').length;const st=finished||i<ci?'past':i===ci?'cur':'';
  return`<div class="fs ${st}"><div class="fh"><span>${p[1]}</span><span class="tiny">${ts.length?`${done}/${ts.length}`:''}</span></div><div class="fd">${p[2]}</div><div class="avs">${ts.map(t=>`<span class="av c-${kindOf(t.agent)}" title="${esc(t.agent)}: ${t.status}" style="opacity:${t.status==='done'?1:t.status==='running'?.95:.35};${t.status==='running'?'outline:2px solid var(--warn);animation:beat 1.2s infinite':''}">${initials(t.agent)}</span>`).join('')}</div><div class="bar"><i style="width:${ts.length?Math.round(done/ts.length*100):(st==='past'?100:0)}%"></i></div></div>`}).join('');
 const sumCost=f=>RUN.tasks.filter(f).reduce((s,t)=>s+((t.meta.usage||{}).total_cost_usd||0),0);const costSub=sumCost(t=>(t.meta.kind||kindOf(t.agent))!=='api'),costApi=sumCost(t=>(t.meta.kind||kindOf(t.agent))==='api');const dur=RUN.tasks.reduce((s,t)=>s+(t.meta.duration_s||0),0);
 $('#stat').innerHTML=`<span>参加 <b>${[...new Set(RUN.tasks.map(t=>t.agent))].length}</b></span>${RUN.state.category?`<span>カテゴリ <b>${CAT_JA[RUN.state.category]||RUN.state.category}</b></span>`:''}<span>タスク <b>${RUN.tasks.filter(t=>t.status==='done').length}/${RUN.tasks.length}</b></span><span>AI 稼働 <b>${Math.round(dur)}s</b></span>${costApi?`<span title="API 従量課金（Grok など）の実費">API 実費 <b>$${costApi.toFixed(3)}</b></span>`:''}${costSub?`<span title="Claude Code の推定額。Max/Pro サブスクなら課金されず利用枠を消費">Claude 推定 <b>$${costSub.toFixed(2)}</b> <span class="tiny">(枠)</span></span>`:''}`;
 $('#final').innerHTML=finished&&RUN.summary?`<div class="card final"><h2>${RUN.status==='done'?'✅ 最終結果':'結果'}</h2><div class="md">${md(RUN.summary)}</div></div>`:'';
 document.querySelectorAll('.tab').forEach(x=>x.classList.toggle('cur',x.dataset.v===view));renderBody()}
function msgHtml(m,withActor){if(m.role==='result'&&!m.content)return`<div class="msg result tiny">✔ 完了${m.data&&m.data.total_cost_usd!=null?' · $'+m.data.total_cost_usd.toFixed(3):''}</div>`;
 const actor=withActor?`${av(m.actor)} <b class="t-${kindOf(m.actor)}">${esc(m.actor)}</b> `:'';const body=m.role==='assistant'||m.role==='result'?`<div class="md">${md(m.content.length>8000?m.content.slice(0,8000)+'…':m.content)}</div>`:esc(m.content.length>6000?m.content.slice(0,6000)+'…':m.content);
 if(m.role==='tool_result'||m.role==='thinking'||m.role==='stderr'||m.role==='system')return`<details><summary><span class="ts">${fmtTs(m.ts)}</span>${withActor?esc(m.actor)+' · ':''}${{tool_result:'結果',thinking:'思考',stderr:'stderr',system:'system'}[m.role]}${m.data&&m.data.is_error?' ⚠':''} · ${esc(m.content.slice(0,90).replace(/\n/g,' '))}</summary><div class="msg ${m.role}">${body}</div></details>`;
 return`<div class="msg ${m.role}"><span class="ts">${fmtTs(m.ts)}</span>${actor}${body}</div>`}
function aliasOf(n){const al=(RUN&&RUN.state.aliases)||{};return Object.keys(al).find(k=>al[k]===n)||''}
function scoreOf(n){const r=(RUN&&RUN.state.results)||{};const d=r[n];if(!d)return'';return`<span class="pill" style="color:var(--fg)" title="匿名審査の平均点/件数">${d.avg!=null?d.avg.toFixed(1)+'点':'–'}/${d.n}${d.best?' ★'+d.best:''}${d.adopted?' ✔採用':''}</span>`}
function colHead(t){const meta=t.meta||{};const al=aliasOf(t.agent);return`<h3>${av(t.agent)}<span class="t-${kindOf(t.agent)}" style="font-weight:700">${esc(t.agent)}</span>${al&&t.step==='solve'?`<span class="tiny mono" title="レビュー時の匿名記号">回答 ${al}</span>`:''}${t.step==='solve'?scoreOf(t.agent):''}${meta.model?`<span class="tiny mono">${esc(meta.model)}</span>`:''}${pill(t.status)}<span class="tiny" style="margin-left:auto">${meta.duration_s?meta.duration_s+'s':''}${meta.usage&&meta.usage.total_cost_usd!=null?' · $'+meta.usage.total_cost_usd.toFixed(2):''}</span></h3>`}
const typing='<div class="typing"><i></i><i></i><i></i></div>';
function renderBody(){const b=$('#body');const ph=PHASES[RUN.recipe]||[];const label=s=>(ph.find(p=>p[0]===s)||[s,s])[1];const steps=[...new Set(RUN.tasks.map(t=>t.step))];
 const sec=(step,inner)=>`<div class="step"><span class="n">${ph.findIndex(p=>p[0]===step)+1||'•'}</span><h3>${label(step)}</h3></div><div class="cols">${inner}</div>`;
 if(view==='results'){b.innerHTML=steps.map(step=>sec(step,RUN.tasks.filter(t=>t.step===step).map(t=>`<div class="col">${colHead(t)}<div class="body">${t.result?`<div class="md">${md(t.result)}</div>`:t.error?`<div class="msg stderr">${esc(t.error)}</div>`:'<div class="empty">'+(t.status==='running'?typing:'待機中')+'</div>'}</div></div>`).join(''))).join('');return}
 if(view==='time'){b.innerHTML=`<div class="card" id="tl">${MSGS.map(m=>msgHtml(m,true)).join('')||'<div class="empty">まだ何も起きていません</div>'}</div>`;return}
 b.innerHTML=steps.map(step=>sec(step,RUN.tasks.filter(t=>t.step===step).map(t=>`<div class="col" data-task="${t.id}">${colHead(t)}<div class="body">${MSGS.filter(m=>m.task_id===t.id).map(m=>msgHtml(m,false)).join('')||'<div class="empty">'+(t.status==='running'?typing:'待機中')+'</div>'}${t.status==='running'?'<div class="live-typing">'+typing+'</div>':''}</div></div>`).join(''))).join('')
 +(MSGS.some(m=>!m.task_id)?`<div class="step"><span class="n">H</span><h3>hub</h3></div><div class="card">${MSGS.filter(m=>!m.task_id).map(m=>msgHtml(m,true)).join('')}</div>`:'');
 document.querySelectorAll('.col .body').forEach(el=>el.scrollTop=el.scrollHeight)}
function appendMsg(m){if(view==='time'){const tl=$('#tl');if(tl){tl.insertAdjacentHTML('beforeend',msgHtml(m,true));tl.lastElementChild?.scrollIntoView({block:'nearest',behavior:'smooth'})}return}
 if(view==='cols'){const col=document.querySelector(`.col[data-task="${m.task_id}"] .body`);if(col){col.querySelector('.empty')?.remove();const lt=col.querySelector('.live-typing');if(lt)lt.insertAdjacentHTML('beforebegin',msgHtml(m,false));else col.insertAdjacentHTML('beforeend',msgHtml(m,false));col.scrollTop=col.scrollHeight;return}}
 renderBody()}
window.onpopstate=route;route();
</script></body></html>
"""
