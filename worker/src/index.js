// A股板块预测 — 实时看板 Worker
// GET /            → 看板页面(内嵌)
// GET /api/state   → 聚合 pred:latest / live:latest / news:latest / meta:heartbeat
// KV 由 Python 侧写入(cloud/kv_client.py 盘前预测; intraday_puller.py 竞价实时+资讯)

const KEYS = {
  pred: "pred:latest", live: "live:latest", news: "news:latest", hb: "meta:heartbeat",
};

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (url.pathname === "/api/state") {
      const [prediction, live, news, heartbeat] = await Promise.all([
        env.ASHARE_KV.get(KEYS.pred, "json"),
        env.ASHARE_KV.get(KEYS.live, "json"),
        env.ASHARE_KV.get(KEYS.news, "json"),
        env.ASHARE_KV.get(KEYS.hb, "json"),
      ]);
      return new Response(
        JSON.stringify({ prediction, live, news, heartbeat, server_epoch: Math.floor(Date.now() / 1000) }),
        { headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" } }
      );
    }

    if (url.pathname === "/" || url.pathname === "") {
      return new Response(HTML, {
        headers: { "content-type": "text/html; charset=utf-8", "cache-control": "no-store" },
      });
    }
    return new Response("Not Found", { status: 404 });
  },
};

const HTML = `<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>A股板块预测 · 实时看板</title>
<style>
  :root{
    --bg:#0b0e14; --panel:#141922; --panel2:#1b212c; --line:#232b38;
    --text:#e6edf3; --dim:#8b98a9; --accent:#4c8dff;
    --hit:#2ec26a; --miss:#ff5d5d; --neutral:#c9a227; --up:#ff5d5d; --down:#2ec26a;
    --mono:ui-monospace,"SF Mono",Menlo,Consolas,monospace;
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--text);
    font-family:system-ui,-apple-system,"Segoe UI","PingFang SC",sans-serif;
    -webkit-font-smoothing:antialiased;line-height:1.5}
  .wrap{max-width:1120px;margin:0 auto;padding:24px 20px 64px}
  header{display:flex;align-items:baseline;justify-content:space-between;
    gap:16px;flex-wrap:wrap;border-bottom:1px solid var(--line);padding-bottom:16px;margin-bottom:24px}
  h1{font-size:20px;margin:0;letter-spacing:.5px}
  h1 span{color:var(--dim);font-weight:400;font-size:14px;margin-left:8px}
  .pill{display:inline-flex;align-items:center;gap:8px;font-family:var(--mono);
    font-size:13px;padding:6px 12px;border-radius:999px;background:var(--panel);border:1px solid var(--line)}
  .dot{width:9px;height:9px;border-radius:50%;background:var(--dim)}
  .dot.live{background:var(--hit);animation:pulse 2s infinite}
  .dot.stale{background:var(--miss)}
  @keyframes pulse{0%{box-shadow:0 0 0 0 rgba(46,194,106,.5)}70%{box-shadow:0 0 0 8px rgba(46,194,106,0)}100%{box-shadow:0 0 0 0 rgba(46,194,106,0)}}
  .grid{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:16px}
  @media(max-width:760px){.grid{grid-template-columns:1fr}}
  .card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:18px 20px;margin-bottom:16px}
  .eyebrow{font-size:11px;letter-spacing:1.5px;text-transform:uppercase;color:var(--accent);margin-bottom:4px}
  .card h2{font-size:15px;margin:0 0 14px;display:flex;justify-content:space-between;align-items:baseline;gap:10px}
  .card h2 .meta{font-size:12px;color:var(--dim);font-weight:400;font-family:var(--mono)}
  .sectors{display:flex;flex-wrap:wrap;gap:10px}
  .chip{font-family:var(--mono);font-size:15px;padding:8px 14px;border-radius:8px;
    background:var(--panel2);border:1px solid var(--line);display:flex;align-items:center;gap:8px}
  .chip .rk{font-size:11px;color:var(--bg);background:var(--accent);border-radius:5px;padding:1px 6px;font-weight:700}
  .dir{font-size:32px;font-weight:800;font-family:var(--mono)}
  .dir.up{color:var(--up)} .dir.down{color:var(--down)} .dir.neutral{color:var(--neutral)}
  .tracks{display:flex;gap:24px}
  .track{flex:1}
  .track .lbl{font-size:12px;color:var(--dim);margin-bottom:8px}
  .badge{display:inline-block;font-family:var(--mono);font-size:13px;font-weight:700;padding:4px 12px;border-radius:7px}
  .badge.hit{background:rgba(46,194,106,.15);color:var(--hit);border:1px solid rgba(46,194,106,.35)}
  .badge.miss{background:rgba(255,93,93,.15);color:var(--miss);border:1px solid rgba(255,93,93,.35)}
  .badge.neutral{background:rgba(201,162,39,.15);color:var(--neutral);border:1px solid rgba(201,162,39,.35)}
  .badge.pending{background:var(--panel2);color:var(--dim);border:1px solid var(--line)}
  table{width:100%;border-collapse:collapse;font-size:14px}
  th{text-align:left;font-size:11px;letter-spacing:1px;text-transform:uppercase;color:var(--dim);
    font-weight:600;padding:0 10px 10px;border-bottom:1px solid var(--line)}
  td{padding:10px;border-bottom:1px solid var(--line);vertical-align:top}
  tr:last-child td{border-bottom:none}
  .code{font-family:var(--mono);color:var(--accent)}
  .sec{font-size:12px;color:var(--dim)}
  .reason{color:var(--dim);font-size:13px}
  .pct{font-family:var(--mono);font-weight:700;text-align:right}
  .pct.up{color:var(--up)} .pct.down{color:var(--down)} .pct.flat{color:var(--dim)}
  .tag-new{font-size:10px;background:var(--accent);color:var(--bg);border-radius:4px;padding:0 5px;margin-left:6px;font-weight:700}
  .st{font-size:11px;font-family:var(--mono);padding:1px 6px;border-radius:4px}
  .st.limit{background:rgba(255,93,93,.2);color:var(--up)} .st.strong{background:rgba(255,93,93,.12);color:var(--up)}
  .st.weak{background:rgba(46,194,106,.12);color:var(--down)} .st.flat{color:var(--dim)}
  .news-item{padding:14px;border:1px solid var(--line);border-radius:10px;background:var(--panel2);margin-bottom:10px}
  .news-item:last-child{margin-bottom:0}
  .news-head{display:flex;justify-content:space-between;gap:12px;align-items:flex-start}
  .news-title{font-size:14px;font-weight:600;line-height:1.5}
  .news-snip{color:var(--dim);font-size:13px;margin-top:6px;
    overflow:hidden;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical}
  .news-src{font-family:var(--mono);font-size:11px;color:var(--accent);white-space:nowrap}
  .news-link{color:var(--accent);font-size:12px;text-decoration:none;white-space:nowrap}
  .empty{color:var(--dim);font-family:var(--mono);padding:16px 0}
  .foot{margin-top:24px;color:var(--dim);font-size:12px;display:flex;justify-content:space-between;flex-wrap:wrap;gap:8px}
  .dq{font-family:var(--mono);font-size:12px;padding:2px 8px;border-radius:5px;background:var(--panel2);border:1px solid var(--line)}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>🐉 A股板块预测<span id="date">—</span></h1>
    <span class="pill"><span id="dot" class="dot"></span><span id="status">连接中…</span></span>
  </header>

  <div class="grid">
    <div class="card" style="margin-bottom:0">
      <div class="eyebrow">主力方向</div>
      <div id="direction" class="dir neutral">—</div>
    </div>
    <div class="card" style="margin-bottom:0">
      <div class="eyebrow">双轨验证</div>
      <div class="tracks">
        <div class="track"><div class="lbl">竞价当场</div><span id="t-auction" class="badge pending">待竞价</span></div>
        <div class="track"><div class="lbl">收盘复核</div><span id="t-close" class="badge pending">待收盘</span></div>
      </div>
    </div>
  </div>

  <div class="card">
    <div class="eyebrow">盘前预测</div>
    <h2>主力板块</h2>
    <div id="sectors" class="sectors"><span class="empty">等待盘前预测…</span></div>
  </div>

  <div class="card">
    <div class="eyebrow">动态候选（竞价实时刷新）</div>
    <h2>候选涨停 <span class="meta" id="cand-meta"></span></h2>
    <div id="cand-wrap"><div class="empty">等待盘前预测…</div></div>
  </div>

  <div class="card">
    <div class="eyebrow">资讯 · News Feed</div>
    <h2>相关资讯 <span class="meta" id="news-meta"></span></h2>
    <div id="news-wrap"><div class="empty">暂无资讯</div></div>
  </div>

  <div class="foot">
    <span>数据质量: <span id="dq" class="dq">—</span> · 状态: <span id="pstatus">—</span></span>
    <span>⚠️ 研究用途，非投资建议 · 每 15s 刷新 · 红涨绿跌</span>
  </div>
</div>

<script>
const DIR_TXT = {up:"↑ 进攻 / 做多", down:"↓ 退潮 / 防守", neutral:"→ 震荡"};
const OUT = {hit:"命中", miss:"未中", neutral:"中性"};

function badge(el, outcome, pendingText){
  if(!outcome){ el.className="badge pending"; el.textContent=pendingText; return; }
  el.className = "badge " + outcome; el.textContent = (OUT[outcome]||outcome)+" · "+outcome;
}
function pctCell(pct){
  if(pct===null||pct===undefined) return '<td class="pct flat">—</td>';
  const cls = pct>0?"up":(pct<0?"down":"flat");
  const s = (pct>0?"+":"")+pct.toFixed(2)+"%";
  return '<td class="pct '+cls+'">'+s+'</td>';
}

async function tick(){
  let s;
  try{ s = await (await fetch("/api/state",{cache:"no-store"})).json(); }
  catch(e){ setStatus(false,"断线"); return; }

  const hb = s.heartbeat;
  const age = hb ? (s.server_epoch - hb.epoch) : 999;
  setStatus(hb && age<=60, hb ? ("最后更新 "+hb.last_update+" · "+age+"s前"+(hb.phase?" · "+hb.phase:"")) : "无数据");

  const p = s.prediction, live = s.live;
  if(p){
    document.getElementById("date").textContent = " · " + (p.date||"");
    document.getElementById("pstatus").textContent = p.status||"—";
    document.getElementById("dq").textContent = p.data_quality_overall||"—";
    const dir=(p.main_direction||"neutral"), de=document.getElementById("direction");
    de.className="dir "+dir; de.textContent=DIR_TXT[dir]||dir;
    const sw=document.getElementById("sectors");
    if(p.main_sectors&&p.main_sectors.length)
      sw.innerHTML=p.main_sectors.map((x,i)=>'<span class="chip"><span class="rk">'+(i+1)+'</span>'+esc(x)+'</span>').join("");

    // 候选: 有 live 用竞价实时(动态), 否则用盘前静态
    const useLive = live && live.candidates_live && live.candidates_live.length;
    const cs = useLive ? live.candidates_live : (p.candidates||[]);
    const meta = document.getElementById("cand-meta");
    meta.textContent = useLive
      ? (live.as_of+" · 兑现率 "+(live.candidate_hit_rate!=null?Math.round(live.candidate_hit_rate*100)+"%":"—"))
      : "盘前名单";
    const cw=document.getElementById("cand-wrap");
    if(cs.length){
      cw.innerHTML='<table><thead><tr><th>#</th><th>代码</th><th>名称</th><th>板块</th>'
        +(useLive?'<th>状态</th><th style="text-align:right">竞价</th>':'<th>逻辑</th>')
        +'</tr></thead><tbody>'
        + cs.map((c,i)=>'<tr><td class="sec">'+(c.rank||i+1)+'</td><td class="code">'+esc(c.code||"")
          +'</td><td>'+esc(c.name||"")+(c.new?'<span class="tag-new">新</span>':'')
          +'</td><td class="sec">'+esc(c.sector||"")+'</td>'
          +(useLive?('<td><span class="st '+(c.status||"flat")+'">'+esc(c.status||"")+'</span></td>'+pctCell(c.pct))
                   :('<td class="reason">'+esc(c.reason||"")+'</td>'))
          +'</tr>').join("")+'</tbody></table>';
    }

    // 双轨: 竞价优先取 live, 否则取 prediction.evaluation.auction
    const ev=p.evaluation||{};
    const auc=(live&&live.auction_score)||ev.auction;
    badge(document.getElementById("t-auction"), auc&&auc.sector_outcome, "待竞价");
    badge(document.getElementById("t-close"), ev.close&&ev.close.sector_outcome, "待收盘");
  }

  // 资讯
  const news=s.news;
  const nw=document.getElementById("news-wrap");
  document.getElementById("news-meta").textContent = news&&news.as_of ? news.as_of.slice(11,16) : "";
  if(news&&news.items&&news.items.length){
    nw.innerHTML=news.items.map(n=>'<div class="news-item"><div class="news-head">'
      +'<div><div class="news-title">'+esc(n.title||"")+'</div>'
      +(n.snippet?'<div class="news-snip">'+esc(n.snippet)+'</div>':'')+'</div>'
      +'<div style="text-align:right"><div class="news-src">'+esc(n.source||"")+'</div>'
      +(n.url?'<a class="news-link" href="'+esc(n.url)+'" target="_blank" rel="noopener noreferrer">打开 ↗</a>':'')
      +'</div></div></div>').join("");
  }
}

function setStatus(alive,txt){
  document.getElementById("dot").className="dot "+(alive?"live":"stale");
  document.getElementById("status").textContent=txt;
}
function esc(s){return String(s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));}
tick(); setInterval(tick,15000);
</script>
</body>
</html>`;
