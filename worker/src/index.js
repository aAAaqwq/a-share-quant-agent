// A股板块预测 — 实时看板 Worker
// GET /            → 看板页面(内嵌)
// GET /api/state   → 从 KV 读 pred:latest / live:latest / meta:heartbeat 聚合 JSON
// KV 由 Python 侧 cloud/kv_client.py 写入(盘前预测 / 竞价盘中实时 / 心跳)

const KEYS = { pred: "pred:latest", live: "live:latest", hb: "meta:heartbeat" };

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (url.pathname === "/api/state") {
      const [prediction, live, heartbeat] = await Promise.all([
        env.ASHARE_KV.get(KEYS.pred, "json"),
        env.ASHARE_KV.get(KEYS.live, "json"),
        env.ASHARE_KV.get(KEYS.hb, "json"),
      ]);
      return new Response(
        JSON.stringify({ prediction, live, heartbeat, server_epoch: Math.floor(Date.now() / 1000) }),
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
  .wrap{max-width:1080px;margin:0 auto;padding:24px 20px 64px}
  header{display:flex;align-items:baseline;justify-content:space-between;
    gap:16px;flex-wrap:wrap;border-bottom:1px solid var(--line);padding-bottom:16px;margin-bottom:24px}
  h1{font-size:20px;margin:0;letter-spacing:.5px}
  h1 span{color:var(--dim);font-weight:400;font-size:14px;margin-left:8px}
  .pill{display:inline-flex;align-items:center;gap:8px;font-family:var(--mono);
    font-size:13px;padding:6px 12px;border-radius:999px;background:var(--panel);border:1px solid var(--line)}
  .dot{width:9px;height:9px;border-radius:50%;background:var(--dim);box-shadow:0 0 0 0 rgba(0,0,0,0)}
  .dot.live{background:var(--hit);animation:pulse 2s infinite}
  .dot.stale{background:var(--miss)}
  @keyframes pulse{0%{box-shadow:0 0 0 0 rgba(46,194,106,.5)}70%{box-shadow:0 0 0 8px rgba(46,194,106,0)}100%{box-shadow:0 0 0 0 rgba(46,194,106,0)}}
  .grid{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:16px}
  @media(max-width:720px){.grid{grid-template-columns:1fr}}
  .card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:18px 20px}
  .card h2{font-size:12px;letter-spacing:1.5px;text-transform:uppercase;color:var(--dim);margin:0 0 14px}
  .sectors{display:flex;flex-wrap:wrap;gap:10px}
  .chip{font-family:var(--mono);font-size:15px;padding:8px 14px;border-radius:8px;
    background:var(--panel2);border:1px solid var(--line);display:flex;align-items:center;gap:8px}
  .chip .rk{font-size:11px;color:var(--bg);background:var(--accent);border-radius:5px;padding:1px 6px;font-weight:700}
  .dir{font-size:34px;font-weight:800;font-family:var(--mono);letter-spacing:1px}
  .dir.up{color:var(--up)} .dir.down{color:var(--down)} .dir.neutral{color:var(--neutral)}
  .tracks{display:flex;gap:24px;margin-top:4px}
  .track{flex:1}
  .track .lbl{font-size:12px;color:var(--dim);margin-bottom:8px}
  .badge{display:inline-block;font-family:var(--mono);font-size:13px;font-weight:700;
    padding:4px 12px;border-radius:7px;letter-spacing:.5px}
  .badge.hit{background:rgba(46,194,106,.15);color:var(--hit);border:1px solid rgba(46,194,106,.35)}
  .badge.miss{background:rgba(255,93,93,.15);color:var(--miss);border:1px solid rgba(255,93,93,.35)}
  .badge.neutral{background:rgba(201,162,39,.15);color:var(--neutral);border:1px solid rgba(201,162,39,.35)}
  .badge.pending{background:var(--panel2);color:var(--dim);border:1px solid var(--line)}
  table{width:100%;border-collapse:collapse;font-size:14px}
  th{text-align:left;font-size:11px;letter-spacing:1px;text-transform:uppercase;color:var(--dim);
    font-weight:600;padding:0 10px 10px;border-bottom:1px solid var(--line)}
  td{padding:11px 10px;border-bottom:1px solid var(--line)}
  tr:last-child td{border-bottom:none}
  .code{font-family:var(--mono);color:var(--accent)}
  .sec{font-size:12px;color:var(--dim)}
  .reason{color:var(--dim);font-size:13px}
  .foot{margin-top:24px;color:var(--dim);font-size:12px;display:flex;justify-content:space-between;flex-wrap:wrap;gap:8px}
  .empty{color:var(--dim);font-family:var(--mono);padding:20px 0}
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
    <div class="card">
      <h2>主力方向</h2>
      <div id="direction" class="dir neutral">—</div>
    </div>
    <div class="card">
      <h2>双轨验证</h2>
      <div class="tracks">
        <div class="track"><div class="lbl">竞价当场</div><span id="t-auction" class="badge pending">待竞价</span></div>
        <div class="track"><div class="lbl">收盘复核</div><span id="t-close" class="badge pending">待收盘</span></div>
      </div>
    </div>
  </div>

  <div class="card" style="margin-bottom:16px">
    <h2>主力板块（预测）</h2>
    <div id="sectors" class="sectors"><span class="empty">等待盘前预测…</span></div>
  </div>

  <div class="card">
    <h2>候选涨停</h2>
    <div id="cand-wrap"><div class="empty">等待盘前预测…</div></div>
  </div>

  <div class="foot">
    <span>数据质量: <span id="dq" class="dq">—</span> · 状态: <span id="pstatus">—</span></span>
    <span>⚠️ 研究用途，非投资建议 · 每 15s 刷新</span>
  </div>
</div>

<script>
const DIR_TXT = {up:"↑ 进攻 / 做多", down:"↓ 退潮 / 防守", neutral:"→ 震荡"};
const OUT = {hit:["hit","命中"], miss:["miss","未中"], neutral:["neutral","中性"]};

function badge(el, outcome, pendingText){
  if(!outcome){ el.className="badge pending"; el.textContent=pendingText; return; }
  const [cls,txt] = OUT[outcome] || ["pending", outcome];
  el.className = "badge " + cls;
  el.textContent = txt + " · " + outcome;
}

async function tick(){
  let s;
  try{ s = await (await fetch("/api/state",{cache:"no-store"})).json(); }
  catch(e){ setStatus(false, "断线"); return; }

  // 死活灯
  const hb = s.heartbeat;
  const age = hb ? (s.server_epoch - hb.epoch) : 999;
  const alive = hb && age <= 60;
  setStatus(alive, hb ? ("最后更新 "+hb.last_update+" · "+age+"s前"+(hb.phase?" · "+hb.phase:"")) : "无数据");

  const p = s.prediction;
  if(!p){ return; }
  document.getElementById("date").textContent = " · " + (p.date||"");
  document.getElementById("pstatus").textContent = p.status||"—";
  document.getElementById("dq").textContent = p.data_quality_overall||"—";

  // 方向
  const dir = (p.main_direction||"neutral");
  const de = document.getElementById("direction");
  de.className = "dir " + dir; de.textContent = DIR_TXT[dir]||dir;

  // 板块
  const secWrap = document.getElementById("sectors");
  if(p.main_sectors && p.main_sectors.length){
    secWrap.innerHTML = p.main_sectors.map((s,i)=>
      '<span class="chip"><span class="rk">'+(i+1)+'</span>'+esc(s)+'</span>').join("");
  }

  // 候选表
  const cw = document.getElementById("cand-wrap");
  const cs = p.candidates||[];
  if(cs.length){
    cw.innerHTML = '<table><thead><tr><th>#</th><th>代码</th><th>名称</th><th>板块</th><th>逻辑</th></tr></thead><tbody>'
      + cs.map((c,i)=>'<tr><td class="sec">'+(c.rank||i+1)+'</td><td class="code">'+esc(c.code||"")
        +'</td><td>'+esc(c.name||"")+'</td><td class="sec">'+esc(c.sector||"")
        +'</td><td class="reason">'+esc(c.reason||"")+'</td></tr>').join("")
      + '</tbody></table>';
  }

  // 双轨评估
  const ev = p.evaluation||{};
  badge(document.getElementById("t-auction"), ev.auction && ev.auction.sector_outcome, "待竞价");
  badge(document.getElementById("t-close"), ev.close && ev.close.sector_outcome, "待收盘");
}

function setStatus(alive, txt){
  document.getElementById("dot").className = "dot " + (alive?"live":"stale");
  document.getElementById("status").textContent = txt;
}
function esc(s){ return String(s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c])); }

tick(); setInterval(tick, 15000);
</script>
</body>
</html>`;
