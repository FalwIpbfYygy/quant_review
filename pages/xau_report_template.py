# -*- coding: utf-8 -*-
"""
 每日交易计划 —— 前端 HTML 模板常量
全新 URL: /xau; 全新文件名，避开 /dailyplan / /trade 的所有缓存
字段严格对齐 /api/xau/plan 与 /api/xau/backtest 的真实返回。
"""

HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta http-equiv="Cache-Control" content="no-store, no-cache, must-revalidate">
<meta http-equiv="Pragma" content="no-cache">
<meta http-equiv="Expires" content="0">
<title> 每日交易计划 · Binance Futures</title>
<link rel="stylesheet" href="/static/components/topnav.css">
<script src="/static/components/topnav.js" defer></script>
<style>
:root{
  --bg:#f6f7fb; --card:#fff; --ink:#1a1d2e; --sub:#5a6178; --acc:#2962ff;
  --good:#e53935; --bad:#2ecc71; --warn:#ff9800; --line:#eef0f4;
  --line2:#d9dde7; --soft:#f0f3f9;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font-family:-apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;font-size:14px}
.wrap{max-width:1200px;margin:0 auto;padding:16px}
.topnav{background:#fff;border-bottom:1px solid var(--line);padding:0 24px;display:flex;align-items:center;gap:6px;min-height:48px;height:auto;flex-wrap:wrap;position:sticky;top:0;z-index:10}
.tn-home{font-weight:700;color:var(--ink);margin-right:18px;text-decoration:none;font-size:15px}
.tn-link{color:var(--sub);text-decoration:none;padding:0 12px;height:48px;line-height:48px;border-bottom:2px solid transparent;font-size:13px}
.tn-link.active,.tn-link[aria-current="page"]{color:var(--ink);border-bottom-color:var(--acc);font-weight:600}
.tn-link:hover{color:var(--ink)}
.tn-spacer{flex:1}
.tn-tag{font-size:11px;background:var(--soft);color:var(--sub);padding:3px 9px;border-radius:10px}
.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:16px;margin-bottom:14px}
.card h2{margin:0 0 12px;font-size:16px;display:flex;align-items:center;gap:8px}
.card h2 .h-tag{font-size:11px;font-weight:400;color:var(--sub);background:var(--soft);padding:2px 8px;border-radius:8px}
.err{background:#fff5f5;border:1px solid #f5b5b5;color:#c62828;padding:10px 14px;border-radius:6px;margin:10px 0;font-size:13px}
.warn-row{display:flex;align-items:center;gap:8px;background:#fff8e1;border:1px solid #ffe082;padding:8px 12px;border-radius:6px;margin-bottom:10px;font-size:13px}
.warn-row.bad{background:#fdecea;border-color:#f5b5b5;color:#c62828}
.warn-row.ok{background:#e8f5e9;border-color:#c8e6c9;color:#2e7d32}
.warn-row b{font-weight:700}
.cb{display:flex;flex-wrap:wrap;gap:10px;align-items:center}
.cb .label{font-size:12px;color:var(--sub);margin-right:4px}
.btn{background:var(--acc);color:#fff;border:0;padding:9px 18px;border-radius:6px;font-size:14px;cursor:pointer;font-weight:600}
.btn:hover{background:#1d4fd1}
.btn:disabled{background:#9aaeed;cursor:wait}
.btn.ghost{background:var(--soft);color:var(--ink)}
.btn.warn{background:var(--warn);color:#fff}
input[type=date],input[type=time]{border:1px solid var(--line2);padding:8px 10px;border-radius:6px;font-size:13px;background:#fff;color:var(--ink)}
.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}
.grid .tile{background:var(--soft);padding:10px 12px;border-radius:6px}
.grid .tile .k{font-size:11px;color:var(--sub);margin-bottom:4px}
.grid .tile .v{font-size:18px;font-weight:700;color:var(--ink)}
.grid .tile .sub{font-size:11px;color:var(--sub);margin-top:2px}
.up{color:var(--good)} .dn{color:var(--bad)}
.plans{display:grid;grid-template-columns:1fr 1fr;gap:14px}
@media (max-width:780px){.grid{grid-template-columns:repeat(2,1fr)} .plans{grid-template-columns:1fr}}
.plan-side{border:2px solid var(--line);border-radius:8px;padding:14px}
.plan-side.long{border-color:#c62828}
.plan-side.short{border-color:#2e7d32}
.plan-side .ps-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:8px}
.plan-side .ps-id{font-weight:700;font-size:15px}
.plan-side .ps-tag{font-size:11px;background:var(--soft);padding:2px 8px;border-radius:8px;color:var(--sub)}
.plan-side .ps-body{display:grid;grid-template-columns:repeat(2,1fr);gap:8px;margin-top:8px}
.plan-side .ps-body .row{display:flex;justify-content:space-between;font-size:13px;padding:4px 0;border-bottom:1px dashed var(--line)}
.plan-side .ps-body .row:last-child{border-bottom:0}
.plan-side .ps-body .row .kk{color:var(--sub)}
.plan-side .ps-body .row .vv{font-weight:700;font-family:Menlo,Consolas,monospace}
.kbox{height:320px}
table{width:100%;border-collapse:collapse;font-size:13px}
table th,table td{padding:8px 10px;border-bottom:1px solid var(--line);text-align:right}
table th{background:var(--soft);color:var(--sub);font-weight:600;text-align:right;font-size:12px}
table th:first-child,table td:first-child{text-align:left}
.empty{color:var(--sub);padding:24px;text-align:center;font-size:13px}
.foot{font-size:12px;color:var(--sub);border-top:1px solid var(--line);padding-top:10px;margin-top:10px;line-height:1.7}
.mr{color:var(--good)} .mr.dn{color:var(--bad)}
.report{font-size:14px;line-height:1.8;color:var(--ink);word-break:break-word}
.report h1,.report h2,.report h3,.report h4{margin:18px 0 8px;line-height:1.4}
.report h2{border-left:4px solid var(--good);padding-left:10px;font-size:17px}
.report h3{font-size:15px;color:var(--acc)}
.report p{margin:8px 0}
.report ul,.report ol{margin:8px 0;padding-left:22px}
.report li{margin:4px 0}
.report strong{color:var(--good)}
.report table{border-collapse:collapse;width:100%;margin:10px 0;font-size:13px}
.report th,.report td{border:1px solid var(--line);padding:6px 8px;text-align:left}
.report code{background:var(--bg);padding:1px 5px;border-radius:4px;font-size:12px}
.report blockquote{border-left:3px solid var(--line);margin:8px 0;padding:4px 12px;color:var(--sub)}
/* 顶部风险提示：红框加粗 */
.report p:first-child, .report strong:first-child{color:var(--bad)}
</style>
</head>
<body>
<div class="topnav">
  <a class="tn-home" href="/">📊 quant_review</a>
  <topnav-bar class="topnav-links" data-active="/xau"></topnav-bar>
  <span class="tn-spacer"></span>
  <span class="tn-tag">Binance Futures · </span>
</div>

<div class="wrap">
<div id="app">

  <h1 style="font-size:22px;margin:0 0 8px"> 每日交易计划</h1>
<div style="color:var(--sub);font-size:13px;margin-bottom:14px">
  数据源: 价格接口基址  5m（<b>无 PAXG 偏移</b>）·
  决策时点: 北京时每日 09:00 · 严格 asof 截断（无未来函数）
</div>

<!-- 控制条 -->
<div class="card">
  <div class="cb">
    <span class="label">决策日期</span>
    <input type="date" v-model="dateStr">
    <span class="label">时间</span>
    <input type="time" v-model="timeStr" step="300">
    <button class="btn" @click="loadPlan" :disabled="busy">
      <span v-if="busy">计算中…</span>
      <span v-else>生成计划</span>
    </button>
    <button class="btn ghost" @click="setNow">用当前时间</button>
    <button class="btn primary" @click="loadReport" :disabled="reportBusy" style="margin-left:8px">
      <span v-if="reportBusy">AI 生成中…</span>
      <span v-else>生成 AI 报告</span>
    </button>
  </div>
  <div class="cb" style="margin-top:10px">
    <span class="label">回测区间</span>
    <input type="date" v-model="btStart">
    <span class="label">至</span>
    <input type="date" v-model="btEnd">
    <button class="btn ghost" @click="loadBt" :disabled="busy">运行回测</button>
    <span class="tn-tag" style="margin-left:auto" v-if="source">📡 {{ source }}</span>
  </div>
  <div v-if="errorMsg" class="err">⚠ {{ errorMsg }}</div>
</div>

<!-- 预警条 -->
<div v-if="warns && warns.length">
  <div v-for="(w, idx) in warns" :key="idx"
       :class="['warn-row', w.level === 'bad' ? 'bad' : (w.level === 'ok' ? 'ok' : '')]">
    <b>{{ isObj(w) ? w.t : '提醒' }}:</b>
    <span>{{ isObj(w) ? (w.m || '') : w }}</span>
  </div>
</div>

<!-- 决策读数 -->
<div v-if="plan && plan.ok === false && plan.reason" class="card">
  <h2>决策读数 <span class="h-tag">{{ plan.asof_str }} · 数据不足</span></h2>
  <div class="grid">
    <div class="tile"><div class="k">现价</div><div class="v">{{ plan.cur || '—' }}</div><div class="sub">USD/oz</div></div>
    <div class="tile"><div class="k">ATR14(5m)</div><div class="v">{{ plan.atr14 || '—' }}</div><div class="sub">USD/oz</div></div>
    <div class="tile"><div class="k">K 线</div><div class="v">{{ plan.bars_used || 0 }}</div><div class="sub">5m bar</div></div>
  </div>
  <div class="empty">⚠ {{ plan.reason }}</div>
</div>

<div v-else-if="plan && plan.ok" class="card">
  <h2>决策读数 <span class="h-tag">{{ plan.asof_str }} · BJ 决策时点</span></h2>
  <div class="grid">
    <div class="tile">
      <div class="k">现价</div>
      <div class="v">{{ plan.cur }}</div>
      <div class="sub">USD/oz</div>
    </div>
    <div class="tile">
      <div class="k">ATR14(5m)</div>
      <div class="v">{{ plan.atr14 }}</div>
      <div class="sub">{{ plan.atrPct }}% · 0.30×ATR = R</div>
    </div>
    <div class="tile">
      <div class="k">前日 {{ plan.prev_day.day }}</div>
      <div class="v">{{ plan.prev_day.high }} / {{ plan.prev_day.low }}</div>
      <div class="sub">H/L · 距中价 {{ plan.distCurAtr }} ATR · 倾向 {{ plan.bias }}</div>
    </div>
    <div class="tile">
      <div class="k">PDH / PDL</div>
      <div class="v" :class="plan.primary.side === 'long' ? 'up' : 'dn'">
        {{ plan.primary.side === 'long' ? plan.prev_day.high : plan.prev_day.low }}
      </div>
      <div class="sub">{{ plan.primary.side === 'long' ? '做多触发' : '做空触发' }}</div>
    </div>
    <div class="tile">
      <div class="k">前开</div>
      <div class="v">{{ plan.prev_day.open }}</div>
      <div class="sub">USD/oz</div>
    </div>
    <div class="tile">
      <div class="k">前收</div>
      <div class="v">{{ plan.prev_day.close }}</div>
      <div class="sub">USD/oz</div>
    </div>
    <div class="tile">
      <div class="k">数据样本</div>
      <div class="v">{{ plan.bars_used }}</div>
      <div class="sub">5m bar (可见)</div>
    </div>
    <div class="tile">
      <div class="k">日线样本</div>
      <div class="v">{{ plan.daily_used }}</div>
      <div class="sub">5m/日</div>
    </div>
  </div>
  <div v-if="plan.too_close" class="warn-row bad">
    <b>区间过窄:</b>
    <span>PDH/PDL 区间 &lt; 1.2R，无突破 alpha，建议当日观望。</span>
  </div>
</div>

<!-- 主+次计划 -->
<div v-if="plan && plan.primary" class="plans">
  <div class="plan-side" :class="plan.primary.side">
    <div class="ps-head">
      <div class="ps-id">A · 突破{{ plan.primary.side === 'long' ? '做多' : '做空' }}</div>
      <span class="ps-tag">主计划 · v2 跟随</span>
    </div>
    <div style="font-size:12px;color:var(--sub);margin-bottom:8px">
      现价 <b>{{ plan.cur }}</b> · 触发 <b :class="plan.primary.side === 'long' ? 'up' : 'dn'">{{ plan.primary.trigger }}</b>
      · 止损 <b class="dn">{{ plan.primary.stop }}</b> · R = {{ plan.primary.R }} 美元
    </div>
    <div class="ps-body">
      <div class="row"><span class="kk">入场</span><span class="vv">{{ plan.primary.entry }}</span></div>
      <div class="row"><span class="kk">触发</span><span class="vv">{{ plan.primary.trigger }}</span></div>
      <div class="row"><span class="kk">止损</span><span class="vv dn">{{ plan.primary.stop }}</span></div>
      <div class="row"><span class="kk">R 倍数</span><span class="vv">{{ plan.primary.R }} USD</span></div>
      <div class="row"><span class="kk">TP1</span><span class="vv up">{{ plan.primary.tp1 }}</span></div>
      <div class="row"><span class="kk">TP2</span><span class="vv up">{{ plan.primary.tp2 }}</span></div>
      <div class="row"><span class="kk">建议手数</span><span class="vv">{{ plan.primary.lots }} 手</span></div>
      <div class="row"><span class="kk">依据</span><span class="vv" style="font-size:11px">突破 PDH 做多 / 跌破 PDL 做空</span></div>
    </div>
  </div>
  <div v-if="plan.secondary" class="plan-side" :class="plan.secondary.side">
    <div class="ps-head">
      <div class="ps-id">B · 反向{{ plan.secondary.side === 'long' ? '做多' : '做空' }}</div>
      <span class="ps-tag">次计划 · 破坏即触发</span>
    </div>
    <div style="font-size:12px;color:var(--sub);margin-bottom:8px">
      破坏主计划触发位即反向入，止损 / TP 与主计划对称
    </div>
    <div class="ps-body">
      <div class="row"><span class="kk">反向触发</span><span class="vv">{{ plan.secondary.trigger }}</span></div>
      <div class="row"><span class="kk">方向</span><span class="vv">{{ plan.secondary.side === 'long' ? '做多' : '做空' }}</span></div>
      <div class="row"><span class="kk">说明</span><span class="vv" style="font-size:11px">{{ plan.secondary.note || '—' }}</span></div>
    </div>
  </div>
</div>

<!-- K 线 -->
<div v-if="klines && klines.length" class="card">
  <h2>5m K 线 · 近 3 日 <span class="h-tag">{{ klines.length }} 根</span></h2>
  <div id="kbox" class="kbox"></div>
</div>

<!-- 回测 -->
<div v-if="bt" class="card">
  <h2>回测 · {{ btStart }} ~ {{ btEnd }}
    <span class="h-tag" v-if="bt.n_trades">
      {{ bt.n_trades }} 笔 · 胜率 {{ (bt.win_rate*100).toFixed(1) }}% · EV {{ bt.ev_r }}R · PF {{ bt.profit_factor }}
    </span>
  </h2>
  <div v-if="bt.note" class="empty">{{ bt.note }}</div>
  <div v-else-if="bt.n_trades === 0" class="empty">该区间无触发（区间内 / 数据不足）</div>
  <div v-else>
    <div id="monthbox" class="kbox" style="height:200px"></div>
    <h2 style="margin-top:18px">最近 15 笔明细</h2>
    <table>
      <thead>
        <tr><th>日期</th><th>方向</th><th>入场</th><th>出场</th><th>出场原因</th><th>R 倍数</th></tr>
      </thead>
      <tbody>
        <tr v-for="(r, idx) in bt.recent" :key="idx">
          <td>{{ r.day }}</td>
          <td :class="r.side === 'long' ? 'up' : 'dn'">{{ r.side === 'long' ? '多' : '空' }}</td>
          <td>{{ r.entry_price }}</td>
          <td>{{ r.exit_price }}</td>
          <td>{{ r.reason }}</td>
          <td :class="r.ret_R >= 0 ? 'mr' : 'mr dn'">{{ r.ret_R >= 0 ? '+' : '' }}{{ r.ret_R }}</td>
        </tr>
      </tbody>
    </table>
  </div>
</div>

<!-- 实时阶段闸门 ABCDEF -->
<div class="card">
  <h2>📡 实时阶段闸门 · ABCDEF
    <span class="h-tag">4H 总开关 / 1H 微调</span>
    <button class="btn ghost" style="margin-left:auto" @click="loadStage" :disabled="stageBusy">刷新实时判定</button>
  </h2>
  <div v-if="stageError" class="err">⚠ {{ stageError }}</div>
  <div v-else-if="stage">
    <div class="grid">
      <div class="tile">
        <div class="k">4H 阶段（总开关）</div>
        <div class="v">{{ stage.stage_4h }}</div>
        <div class="sub">防抖稳定: {{ stage.stage_4h_stable }}</div>
      </div>
      <div class="tile">
        <div class="k">1H 阶段（微调）</div>
        <div class="v">{{ stage.stage_1h }}</div>
        <div class="sub">防抖稳定: {{ stage.stage_1h_stable }}</div>
      </div>
      <div class="tile">
        <div class="k">现价 </div>
        <div class="v">{{ stage.price }}</div>
        <div class="sub">USD/oz</div>
      </div>
      <div class="tile">
        <div class="k">决策时间（北京）</div>
        <div class="v" style="font-size:14px">{{ stage.time_bj }}</div>
      </div>
    </div>
    <div class="grid" style="margin-top:10px" v-if="stage.metrics">
      <div class="tile"><div class="k">4H ATR 比率</div><div class="v">{{ stage.metrics.atr_ratio_4h }}</div><div class="sub">ATR/ATR_ma60（&lt;1.1 箱体）</div></div>
      <div class="tile"><div class="k">1H ATR 比率</div><div class="v">{{ stage.metrics.atr_ratio_1h }}</div><div class="sub">ATR/ATR_ma60</div></div>
      <div class="tile"><div class="k">4H 近120根区间</div><div class="v" style="font-size:13px">{{ stage.metrics.range_4h }}</div></div>
      <div class="tile"><div class="k">交易时段</div><div class="v" style="font-size:13px">{{ stage.metrics.session }}</div></div>
    </div>
    <div class="warn-row" :class="stage.decision.cls">{{ stage.decision.verdict }}</div>
    <div class="cb" style="margin:8px 0"><span class="label">用哪套</span><b>{{ stage.decision.set }}</b></div>
    <div class="cb" style="margin:8px 0"><span class="label">开多大</span><b>{{ stage.decision.size }}</b></div>
    <div class="cb" style="margin:8px 0"><span class="label">理由</span><span style="color:var(--sub);font-size:13px">{{ stage.decision.why }}</span></div>
    <div class="cb" style="margin-top:12px">
      <button class="btn warn" @click="loadStageReport" :disabled="stageReportBusy">🤖 生成 AI 报告</button>
      <span class="sub" v-if="stageReportMeta">{{ stageReportMeta }}</span>
    </div>
    <div v-if="stageReportBusy" class="empty">AI 正在生成阶段闸门报告（基于实时 ABCDEF 判定，约 10–60 秒）…</div>
    <div v-else-if="stageReport" class="report" v-html="renderedStageReport" style="margin-top:10px"></div>
  </div>
  <div v-else class="empty">点击右上「刷新实时判定」获取当前 ABCDEF 阶段与开仓建议</div>
</div>

<!-- AI 分析师报告 -->
<div v-if="report" class="card">
  <h2>🤖 AI 分析师每日交易计划报告
    <span class="h-tag" v-if="reportMeta">{{ reportMeta }}</span>
    <button class="btn ghost" style="margin-left:auto" @click="loadReport" :disabled="reportBusy">重新生成</button>
  </h2>
  <div v-if="reportBusy" class="empty">AI 正在生成（基于实时  + TwelveData DXY/交叉盘数据，约 20–60 秒）…</div>
  <div v-else class="report" v-html="renderedReport"></div>
</div>

<div class="card">
  <div class="foot">
    ⚠ <b>重要风险提示:</b> 本报告仅基于 Binance USD-M 永续  历史 K 线（5m 周期）+ 简单 if-then-else
    规则（突破 PDH/PDL 跟随），不构成任何投资建议。 现货/期货交易属于高风险金融产品，杠杆交易
    可能放大亏损，极端行情下存在本金全部亏损的风险。实盘前需结合经纪商图表基差核对（fapi 期货价格 vs
    现货  存在小幅浮动基差），并完成 demo → 小仓 → 实盘的递进验证。回测数字：含双边成本约 1.0 USD/oz
    （spread 0.30 + slip 0.20 × 2），R 倍数 = 0.30 × ATR14。
  </div>
</div>

</div><!-- /#app -->
</div><!-- /.wrap -->

<script src="/vendors/vue.global.prod.js"></script>
<script src="/vendors/echarts.min.js"></script>
<script src="/vendors/marked.min.js"></script>
<script src="/vendors/purify.min.js"></script>
<script>
function fmt2(v){ if(v==null || isNaN(v)) return '—'; return Number(v).toFixed(2); }
function pad2(n){ return n<10 ? '0'+n : ''+n; }
function todayBJ(){
  var d=new Date(new Date().getTime()+8*3600*1000);
  return d.getUTCFullYear()+'-'+pad2(d.getUTCMonth()+1)+'-'+pad2(d.getUTCDate());
}
function nowBJ(){
  var d=new Date(new Date().getTime()+8*3600*1000);
  return pad2(d.getUTCHours())+':'+pad2(d.getUTCMinutes());
}
function pct(v){ if(v==null || isNaN(v)) return '—'; return (v*100).toFixed(1)+'%'; }

function drawK(klines){
  if(!window.echarts) return;
  var el=document.getElementById('kbox'); if(!el) return;
  var c=echarts.init(el); if(window.__kb) try{window.__kb.dispose()}catch(e){}
  window.__kb=c;
  var dates=klines.map(function(k){return k.t;});
  var vols=klines.map(function(k,i){
    var prev=i>0 ? klines[i-1].c : k.o;
    return {value:(k.c>=prev?1:-1)*Math.max(k.c-k.o,0.1), itemStyle:{color:k.c>=prev?'#e53935':'#2ecc71'}};
  });
  c.setOption({
    grid:[{left:50,right:30,top:20,height:180},{left:50,right:30,top:220,height:50}],
    xAxis:[{type:'category',data:dates,axisLabel:{fontSize:10}},{type:'category',data:dates,gridIndex:1,axisLabel:{show:false}}],
    yAxis:[{scale:true,axisLabel:{fontSize:10}},{gridIndex:1,axisLabel:{show:false}}],
    dataZoom:[
      {type:'inside',xAxisIndex:[0,1],start:Math.max(0,100-100*100/klines.length),end:100},
      {show:true,xAxisIndex:[0,1],type:'slider',bottom:10,height:14}
    ],
    series:[{
      type:'candlestick',data:klines.map(function(k){return [k.o,k.c,k.l,k.h];}),
      itemStyle:{color:'#e53935',color0:'#2ecc71',borderColor:'#e53935',borderColor0:'#2ecc71'}
    },{type:'bar',xAxisIndex:1,yAxisIndex:1,data:vols}]
  });
  window.addEventListener('resize',function(){c.resize();});
}

function drawMonth(monthly){
  if(!window.echarts) return;
  var el=document.getElementById('monthbox'); if(!el) return;
  var c=echarts.init(el); if(window.__mb) try{window.__mb.dispose()}catch(e){}
  window.__mb=c;
  c.setOption({
    grid:{left:50,right:20,top:20,bottom:30},
    xAxis:{type:'category',data:monthly.map(function(m){return m.month;})},
    yAxis:{type:'value',name:'R'},
    series:[{
      type:'bar',data:monthly.map(function(m){return m.ev;}),
      itemStyle:{
        color:function(p){return p.value>=0?'#e53935':'#2ecc71';}
      },
      label:{show:true,position:'top',formatter:function(p){return (p.value>=0?'+':'')+p.value;}}
    }]
  });
  window.addEventListener('resize',function(){c.resize();});
}

function isObj(x){ return x && typeof x === 'object'; }

var app=Vue.createApp({
  data:function(){
    return {
      busy:false,
      dateStr:todayBJ(),
      timeStr:nowBJ(),
      btStart:'2026-08-07',
      btEnd:'2026-09-04',
      plan:null, klines:[], warns:[], bt:null, source:'', errorMsg:'',
      report:'', reportBusy:false, reportMeta:'',
      stage:null, stageBusy:false, stageError:'',
      stageReport:'', stageReportBusy:false, stageReportMeta:''
    };
  },
  computed:{
    renderedStageReport:function(){
      if(!this.stageReport) return '';
      try{
        var raw = (window.marked && marked.parse) ? marked.parse(this.stageReport) : this.stageReport;
        if(window.DOMPurify){
          return DOMPurify.sanitize(raw, {ADD_TAGS:['font'], ADD_ATTR:['color']});
        }
        return raw;
      }catch(e){ return '<pre style="white-space:pre-wrap">'+this.stageReport+'</pre>'; }
    },
    renderedReport:function(){
      if(!this.report) return '';
      try{
        var raw = (window.marked && marked.parse) ? marked.parse(this.report) : this.report;
        if(window.DOMPurify){
          // 允许模型用 <font color="red/green"> 标注涨跌（国内交易配色习惯）
          return DOMPurify.sanitize(raw, {ADD_TAGS:['font'], ADD_ATTR:['color']});
        }
        return raw;
      }catch(e){ return '<pre style="white-space:pre-wrap">'+this.report+'</pre>'; }
    }
  },
  methods:{
    isObj:isObj,
    setNow:function(){
      this.dateStr=todayBJ();
      this.timeStr=nowBJ();
    },
    loadReport:function(){
      this.reportBusy=true;
      var asof=this.dateStr+' '+this.timeStr;
      var url='/api/xau/report?asof='+encodeURIComponent(asof);
      fetch(url,{cache:'no-store'}).then(this._chk).then(function(j){
        if(j.code!==200){ this.report='⚠ 生成失败：'+(j.error||('HTTP '+j.code)); this.reportMeta=''; return; }
        this.report=j.markdown||'（无内容）';
        this.reportMeta=(j.asof_str||'')+' · 数据源: '+((j.source||'').split(' ')[0]||'')+(j.macro && j.macro.ok ? ' + TwelveData DXY/交叉盘' : '');
      }.bind(this)).catch(function(e){ this.report='⚠ 网络异常: '+(e.message||e); }.bind(this))
      .finally(function(){ this.reportBusy=false; }.bind(this));
    },
    loadPlan:function(){
      this.busy=true; this.errorMsg='';
      var asof=this.dateStr+' '+this.timeStr;
      var url='/api/xau/plan?asof='+encodeURIComponent(asof);
      fetch(url,{cache:'no-store'}).then(this._chk).then(function(j){
        if(j.code!==200){ this.errorMsg=j.error||('HTTP '+j.code); return; }
        this.plan=j.plan; this.klines=j.klines||[]; this.warns=j.warns||[];
        this.source=j.source||''; this.errorMsg='';
        this.$nextTick(function(){
          if(this.klines && this.klines.length) drawK(this.klines);
        }.bind(this));
      }.bind(this)).catch(function(e){ this.errorMsg='网络异常: '+(e.message||e); }.bind(this))
      .finally(function(){ this.busy=false; }.bind(this));
    },
    loadBt:function(){
      this.busy=true; this.errorMsg='';
      var url='/api/xau/backtest?start='+encodeURIComponent(this.btStart)+'&end='+encodeURIComponent(this.btEnd);
      fetch(url,{cache:'no-store'}).then(this._chk).then(function(j){
        this.bt=j; this.source=j.source||this.source;
        if(j.code!==200) this.errorMsg=j.error||('HTTP '+j.code);
        if(j.monthly && j.monthly.length) drawMonth(j.monthly);
      }.bind(this)).catch(function(e){ this.errorMsg='网络异常: '+(e.message||e); }.bind(this))
      .finally(function(){ this.busy=false; }.bind(this));
    },
    _chk:function(r){
      if(!r.ok) return r.json().then(function(b){return {code:r.status,error:'HTTP '+r.status+' '+JSON.stringify(b).slice(0,200)};});
      return r.json();
    },
    loadStage:function(){
      this.stageBusy=true; this.stageError='';
      fetch('/api/xau/stage',{cache:'no-store'}).then(this._chk).then(function(j){
        if(j.code!==200){ this.stageError=j.error||('HTTP '+j.code); return; }
        this.stage=j; this.stageError='';
      }.bind(this)).catch(function(e){ this.stageError='网络异常: '+(e.message||e); }.bind(this))
      .finally(function(){ this.stageBusy=false; }.bind(this));
    },
    loadStageReport:function(){
      if(!this.stage){ this.loadStage(); return; }
      this.stageReportBusy=true; this.stageReport=''; this.stageReportMeta='';
      fetch('/api/xau/stage_report',{cache:'no-store'}).then(this._chk).then(function(j){
        if(j.code!==200){ this.stageReport='⚠ 生成失败：'+(j.error||('HTTP '+j.code)); return; }
        this.stageReport=j.markdown||'（无内容）';
        this.stageReportMeta=(j.time_bj||'')+' · 数据源: '+((j.source||'').split(' ')[0]||'');
      }.bind(this)).catch(function(e){ this.stageReport='⚠ 网络异常: '+(e.message||e); }.bind(this))
      .finally(function(){ this.stageReportBusy=false; }.bind(this));
    }
  }
}).mount('#app');
</script>
</body>
</html>"""
