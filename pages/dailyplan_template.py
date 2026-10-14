# -*- coding: utf-8 -*-
"""
每日交易计划页面 HTML 模板（内联常量，避开 Notion/嵌入同步工具对 .html 的覆写）。
main.py 的 /dailyplan 路由直接返回 HTML 字符串。

字段严格对齐 daily_plan.run_day_v2 + /api/dailyplan/* 的真实返回：
- plan: {ok, asof_str, cur, atr14, prev_day:{day,open,high,low,close},
         primary|secondary:{side,trigger,stop,R,tp1,tp2,lots,risk_pct,dist_atr},
         bias, too_close, sma10, rsi14_5m, data_cut}
- warns: 列表，元素可以是 str 或 {level, t, m}
- klines: [{t,o,c,l,h}]
- bt: {n_trades, win_rate, ev_r, profit_factor, monthly:[{m,r,tot,n}],
       recent:[{day,side,fill,exit_reason,gross_r,cost_r,net_r,pnl_u}]}

原则：模板对任何字段访问都做 null/对象守卫，绝不抛错；按钮触发而非自动加载。
"""
HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>每日交易计划 · K线工具箱</title>
<script src="/vendors/vue.global.prod.js"></script>
<script src="/vendors/echarts.min.js"></script>
<style>
:root{
  --bg:#f0f2f7; --panel:#ffffff; --panel-2:#fafbfc; --border:#ebedf0; --border-soft:#f0f2f5;
  --text:#1d1d1f; --text-2:#424245; --text-muted:#6e6e73;
  --accent:#0a84ff; --accent-2:#0066cc; --accent-soft:#e8f1ff;
  --green:#34c759; --red:#ff3b30; --orange:#ff9500; --purple:#af52de;
  --shadow:0 1px 3px rgba(0,0,0,.04),0 4px 12px rgba(0,0,0,.04);
  --radius:16px; --radius-sm:10px; --radius-pill:999px;
  --font:-apple-system,BlinkMacSystemFont,"SF Pro Text","PingFang SC","Microsoft YaHei",system-ui,sans-serif;
}
*{margin:0;padding:0;box-sizing:border-box;}
body{background:var(--bg);color:var(--text);font-family:var(--font);font-size:13px;line-height:1.5;-webkit-font-smoothing:antialiased;}
.topnav{min-height:56px;height:auto;background:#fff;border-bottom:1px solid var(--border);display:flex;align-items:center;padding:0 24px;gap:6px;position:sticky;top:0;z-index:100;flex-wrap:wrap;}
.topnav-brand{font-weight:600;font-size:15px;margin-right:14px;}
.topnav a{color:var(--text-2);text-decoration:none;padding:6px 12px;border-radius:var(--radius-pill);font-size:13px;white-space:nowrap;}
.topnav a:hover{background:var(--border-soft);}
.topnav a.on{background:var(--accent-soft);color:var(--accent-2);font-weight:500;}
.wrap{max-width:1400px;margin:0 auto;padding:20px 24px 60px;}
.card{background:var(--panel);border:1px solid var(--border);border-radius:var(--radius);box-shadow:var(--shadow);padding:18px 20px;margin-bottom:16px;}
.card h2{font-size:15px;font-weight:600;margin-bottom:4px;display:flex;align-items:center;gap:8px;}
.card h2 .tag{font-size:11px;font-weight:500;padding:2px 8px;border-radius:var(--radius-pill);background:var(--accent-soft);color:var(--accent-2);}
.sub{color:var(--text-muted);font-size:12px;margin-bottom:14px;}
.row{display:flex;gap:12px;flex-wrap:wrap;align-items:flex-end;}
.grid{display:grid;gap:12px;}
.g4{grid-template-columns:repeat(4,1fr);}
@media(max-width:1000px){.g4{grid-template-columns:repeat(2,1fr);}}
@media(max-width:600px){.g4{grid-template-columns:1fr;}}
.kpi{background:var(--panel-2);border:1px solid var(--border-soft);border-radius:var(--radius-sm);padding:12px 14px;}
.kpi .k{color:var(--text-muted);font-size:11px;margin-bottom:4px;}
.kpi .v{font-size:19px;font-weight:600;font-variant-numeric:tabular-nums;}
.kpi .n{font-size:11px;color:var(--text-muted);margin-top:2px;}
.up{color:var(--red);} .down{color:var(--green);} .mono{font-variant-numeric:tabular-nums;}
table{width:100%;border-collapse:collapse;font-size:12.5px;}
th,td{padding:8px 10px;text-align:left;border-bottom:1px solid var(--border-soft);}
th{color:var(--text-muted);font-weight:500;font-size:11.5px;}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums;}
tr:last-child td{border-bottom:none;}
.btn{background:var(--accent);color:#fff;border:none;border-radius:var(--radius-pill);padding:8px 20px;font-size:13px;cursor:pointer;font-family:var(--font);}
.btn:hover{background:var(--accent-2);}
.btn:disabled{opacity:.5;cursor:not-allowed;}
.btn.ghost{background:#fff;color:var(--text-2);border:1px solid var(--border);}
input,select{font-family:var(--font);font-size:13px;padding:7px 11px;border:1px solid var(--border);border-radius:var(--radius-sm);background:#fff;color:var(--text);}
.chart{width:100%;height:420px;}
.chart-m{height:220px;}
.warn{background:#fff8e6;border:1px solid #ffe58f;border-radius:var(--radius-sm);padding:11px 14px;font-size:12.5px;color:#8a6100;margin-bottom:12px;}
.warn b{color:#6b4c00;}
.warn.bad{background:#fff1f0;border-color:#ffccc7;color:#a8071a;} .warn.bad b{color:#a8071a;}
.disc{background:#fafbfc;border:1px dashed var(--border);border-radius:var(--radius-sm);padding:14px 16px;font-size:12px;color:var(--text-muted);line-height:1.7;}
.disc b{color:var(--text-2);}
.empty{color:var(--text-muted);font-size:13px;padding:14px 0;}
.side-tag{display:inline-block;padding:1px 8px;border-radius:var(--radius-pill);font-size:11px;font-weight:600;margin-left:6px;}
.side-long{background:#fff1f0;color:#a8071a;}
.side-short{background:#e8f5e9;color:#1e6e1e;}
.no-signal{padding:20px;text-align:center;color:var(--text-muted);background:var(--panel-2);border-radius:var(--radius-sm);}
</style>
</head>
<body>
<div id="app">
  <div class="topnav">
    <div class="topnav-brand">每日交易计划</div>
    <a href="/">首页</a><a href="/replay">复盘</a><a href="/review">四分屏</a>
    <a href="/realtime">实时</a><a href="/market">市场</a><a href="/psych">心理</a>
    <a href="/habits">习惯</a><a href="/ai_history">AI记录</a><a href="/dailyplan" class="on">交易计划</a>
  </div>

  <div class="wrap">
    <div class="card">
      <h2>决策时点 <span class="tag">asof 硬截断</span></h2>
      <div class="sub">生成计划时，引擎只消费 close_time ≤ 该时刻的 K 线；此后的数据物理不可见。点击「生成计划」后才会向 API 发起请求，避免一加载就报错。</div>
      <div class="row">
        <div><div class="sub" style="margin:0 0 4px">日期</div><input type="date" v-model="date"></div>
        <div><div class="sub" style="margin:0 0 4px">时间（北京时间）</div><input type="time" v-model="time" step="300"></div>
        <button class="btn" @click="loadPlan" :disabled="busy">生成计划</button>
        <button class="btn ghost" @click="useNow">用当前时间</button>
        <button class="btn ghost" @click="loadBt" :disabled="busy">运行回测</button>
        <span v-if="plan &amp;&amp; plan.asof_str" class="sub" style="margin:0 0 6px">
          决策时点 {{ plan.asof_str }} · 数据源 Binance PAXGUSDT + 12 偏移对齐 
        </span>
      </div>
    </div>

    <div v-if="busy" class="card empty">计算中…</div>

    <div v-if="warns.length" style="margin-bottom:16px">
      <div v-for="(w,i) in warns" :key="i" :class="['warn', isObj(w)?w.level||'':'']">
        <b v-if="isObj(w)">{{ w.t }}</b>{{ isObj(w) ? ' ' + (w.m||'') : w }}
      </div>
    </div>

    <div v-if="errorMsg" class="warn bad"><b>错误</b> {{ errorMsg }}</div>

    <div v-if="plan &amp;&amp; plan.ok">
      <div class="card">
        <h2>决策读数 <span class="tag">外汇交易日 · 纽约 17:00 收市</span></h2>
        <div class="grid g4">
          <div class="kpi"><div class="k">现价</div><div class="v mono">{{ plan.cur }}</div><div class="n">{{ plan.asof_str }} 快照</div></div>
          <div class="kpi"><div class="k">ATR14（日）</div><div class="v mono">{{ plan.atr14 }}</div><div class="n">{{ atrPct }}% of price</div></div>
          <div class="kpi"><div class="k">前一交易日</div><div class="v mono" style="font-size:15px">{{ plan.prev_day.day }}</div><div class="n">{{ biasText }} · 距现价 {{ distCurAtr }} ATR</div></div>
          <div class="kpi"><div class="k">PDH / PDL</div><div class="v mono"><span class="up">{{ plan.prev_day.high }}</span> / <span class="down">{{ plan.prev_day.low }}</span></div><div class="n">多头触发 / 空头触发</div></div>
        </div>
        <div class="grid g4" style="margin-top:12px">
          <div class="kpi"><div class="k">前日开</div><div class="v mono">{{ plan.prev_day.open }}</div></div>
          <div class="kpi"><div class="k">前日收</div><div class="v mono">{{ plan.prev_day.close }}</div></div>
          <div class="kpi"><div class="k">数据样本</div><div class="v mono">{{ plan.bars_used }}</div><div class="n">5m bar</div></div>
          <div class="kpi"><div class="k">日线样本</div><div class="v mono">{{ plan.daily_used }}</div><div class="n">外汇日</div></div>
        </div>
        <div v-if="plan.too_close" class="warn" style="margin-top:12px"><b>区间过窄</b> PDH/PDL 与现价距离均小于 0.05 ATR，突破信噪比很低，建议当日观望。</div>
      </div>

      <template v-if="plan.primary">
        <div class="card">
          <h2>A · 突破做多 <span class="tag side-tag side-long">多</span> <span class="tag">{{ plan.primary.lots }} 手 · 风险 {{ plan.primary.risk_pct }}%</span></h2>
          <div class="sub">先触及 PDH 做多（v2 突破跟随，单边）；若先触及 PDL 则触发 B 计划。</div>
          <table>
            <tr><td>触发价（PDH）</td><td class="num mono up">{{ plan.primary.trigger }}</td></tr>
            <tr><td>止损</td><td class="num mono">{{ plan.primary.stop }}</td></tr>
            <tr><td>风险 R（美元/手）</td><td class="num mono">{{ plan.primary.R }}</td></tr>
            <tr><td>TP1（平半+移保本）</td><td class="num mono">{{ plan.primary.tp1 }}</td></tr>
            <tr><td>TP2（平剩余）</td><td class="num mono">{{ plan.primary.tp2 }}</td></tr>
            <tr><td>距现价</td><td class="num mono">{{ plan.primary.dist_atr }} ATR</td></tr>
          </table>
        </div>
      </template>

      <template v-if="plan.secondary">
        <div class="card">
          <h2>B · 突破做空 <span class="tag side-tag side-short">空</span> <span class="tag">{{ plan.secondary.lots }} 手 · 风险 {{ plan.secondary.risk_pct }}%</span></h2>
          <div class="sub">先触及 PDL 做空（v2 突破跟随，单边）；互斥触发——A 与 B 只会执行其一。</div>
          <table>
            <tr><td>触发价（PDL）</td><td class="num mono down">{{ plan.secondary.trigger }}</td></tr>
            <tr><td>止损</td><td class="num mono">{{ plan.secondary.stop }}</td></tr>
            <tr><td>风险 R（美元/手）</td><td class="num mono">{{ plan.secondary.R }}</td></tr>
            <tr><td>TP1（平半+移保本）</td><td class="num mono">{{ plan.secondary.tp1 }}</td></tr>
            <tr><td>TP2（平剩余）</td><td class="num mono">{{ plan.secondary.tp2 }}</td></tr>
            <tr><td>距现价</td><td class="num mono">{{ plan.secondary.dist_atr }} ATR</td></tr>
          </table>
        </div>
      </template>

      <div v-if="!plan.primary &amp;&amp; !plan.secondary" class="card no-signal">当日突破信号未触发（PDH/PDL 距离过窄或数据不足）。</div>

      <div class="card">
        <h2>近 3 日 5 分钟 K 线 <span class="tag">asof 前 864 根</span></h2>
        <div id="kchart" class="chart"></div>
      </div>

      <div class="card">
        <h2>v2 突破跟随 · walk-forward 回测 <span class="tag">5m · 含样本外</span></h2>
        <div class="row" style="margin-bottom:12px">
          <div><div class="sub" style="margin:0 0 4px">起始</div><input type="date" v-model="btStart"></div>
          <div><div class="sub" style="margin:0 0 4px">截止</div><input type="date" v-model="btEnd"></div>
          <button class="btn ghost" @click="loadBt" :disabled="busy">重跑回测</button>
        </div>
        <div v-if="bt &amp;&amp; bt.n_trades!==undefined" class="grid g4" style="margin-bottom:12px">
          <div class="kpi"><div class="k">样本数 n</div><div class="v mono">{{ bt.n_trades }}</div></div>
          <div class="kpi"><div class="k">胜率</div><div class="v mono">{{ (bt.win_rate*100).toFixed(1) }}%</div></div>
          <div class="kpi"><div class="k">EV（R 倍数）</div><div :class="['v','mono', (bt.ev_r&gt;=0?'up':'down')]">{{ fmtR(bt.ev_r) }}R</div><div class="n">单笔期望收益</div></div>
          <div class="kpi"><div class="k">盈利因子 PF</div><div class="v mono">{{ bt.profit_factor }}</div><div class="n">总盈利/总亏损</div></div>
        </div>
        <div v-if="bt &amp;&amp; bt.monthly &amp;&amp; bt.monthly.length">
          <div class="sub" style="margin:8px 0 4px">月度 R 汇总</div>
          <div id="mchart" class="chart chart-m"></div>
        </div>
        <div v-if="bt &amp;&amp; bt.recent &amp;&amp; bt.recent.length">
          <div class="sub" style="margin:12px 0 4px">最近 15 笔</div>
          <table>
            <thead><tr><th>交易日</th><th>方向</th><th class="num">成交价</th><th>出场</th><th class="num">毛 R</th><th class="num">成本 R</th><th class="num">净 R</th><th class="num">盈亏 USD</th></tr></thead>
            <tbody>
              <tr v-for="t in bt.recent" :key="t.day+t.side+t.fill">
                <td class="mono">{{ t.day }}</td>
                <td :class="t.side==='long'?'up':'down'">{{ t.side==='long'?'多':'空' }}</td>
                <td class="num mono">{{ t.fill }}</td>
                <td>{{ t.exit_reason }}</td>
                <td :class="['num','mono', (t.gross_r&gt;=0?'up':'down')]">{{ fmtR(t.gross_r) }}</td>
                <td class="num mono">{{ fmtR(t.cost_r) }}</td>
                <td :class="['num','mono', (t.net_r&gt;=0?'up':'down')]">{{ fmtR(t.net_r) }}</td>
                <td :class="['num','mono', (t.pnl_u&gt;=0?'up':'down')]">{{ fmtU(t.pnl_u) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <div class="card">
        <div class="disc">
          <b>数据口径：</b>行情来自 Binance 现货 <b>PAXGUSDT + 12 美元偏移</b> 对齐  口径，非经纪商直报。基差为浮动值，实测与  相差可达 10~25 美元 —— <b>所有价位必须在你的经纪商  图表上复核后再下单</b>。<br>
          <b>日线切分：</b>外汇交易日（纽约 17:00 收市；夏令时=北京 05:00 / 冬令时 06:00），已按美国 DST 规则精确计算。<br>
          <b>已知局限：</b>① 加密盘 7×24 无周末跳空，而真实  周末休市会跳空 —— 回测中的"最差单笔"低估了实盘跳空风险，<b>建议周五收盘前平仓，不持仓过周末</b>；② 同根 K 线内无法判定 SL/TP 先后，统一按保守假设；③ 样本为 2026-02~09 单一品种单一周期，未做跨品种验证；④ 成交按触发价+固定滑点近似，实盘快速突破时滑点可能更大。<br><br>
          <b>⚠️ 风险提示与免责声明：</b>本页面内容仅为基于公开与本地数据的分析讨论，<b>不构成任何投资建议、理财建议或交易邀约</b>。市场有风险，投资需谨慎。
        </div>
      </div>
    </div>

    <div v-else-if="!busy &amp;&amp; !plan" class="card empty">尚无数据，请点击「生成计划」或「用当前时间」。</div>
    <div v-else-if="!busy &amp;&amp; plan &amp;&amp; !plan.ok" class="card empty">无计划：{{ plan.reason || '信号失败或数据不足' }}</div>
  </div>
</div>

<script>
const { createApp } = Vue;
createApp({
  data(){
    return {
      date:'', time:'09:00', busy:false,
      plan:null, kl:[], warns:[], errorMsg:'',
      btStart:'2026-02-01', btEnd:'2026-09-04', bt:null,
      chart:null, mchart:null
    };
  },
  computed:{
    atrPct(){ return (this.plan &amp;&amp; this.plan.cur) ? (this.plan.atr14/this.plan.cur*100).toFixed(2) : '\u2014'; },
    distCurAtr(){
      if(!this.plan || !this.plan.cur || !this.plan.atr14) return '\u2014';
      var ph=this.plan.prev_day &amp;&amp; this.plan.prev_day.high;
      var pl=this.plan.prev_day &amp;&amp; this.plan.prev_day.low;
      if(ph==null || pl==null) return '\u2014';
      var d = Math.min(Math.abs(ph-this.plan.cur), Math.abs(pl-this.plan.cur));
      return (d/this.plan.atr14).toFixed(3);
    },
    biasText(){
      var m = {'neutral':'中性','long':'偏多','short':'偏空'};
      return m[this.plan &amp;&amp; this.plan.bias] || '\u2014';
    }
  },
  mounted(){
    // 仅初始化日期时间，不自动调用 API（避免 uvicorn worker 异常时页面进入就卡死报错）
    this.useNow();
    var self=this;
    window.addEventListener('resize', function(){
      if(self.chart) self.chart.resize();
      if(self.mchart) self.mchart.resize();
    });
  },
  methods:{
    isObj(x){ return x &amp;&amp; typeof x === 'object'; },
    fmtR(v){ if(v==null || isNaN(v)) return '\u2014'; return (v&gt;=0?'+':'')+Number(v).toFixed(3); },
    fmtU(v){ if(v==null || isNaN(v)) return '\u2014'; return (v&gt;=0?'+':'')+Number(v).toFixed(2); },
    useNow(){
      var n=new Date();
      this.date = n.getFullYear()+'-'+String(n.getMonth()+1).padStart(2,'0')+'-'+String(n.getDate()).padStart(2,'0');
      var mm = Math.floor(n.getMinutes()/5)*5;
      this.time = String(n.getHours()).padStart(2,'0')+':'+String(mm).padStart(2,'0');
    },
    loadPlan(){
      this.busy=true; this.errorMsg='';
      var self=this;
      fetch('/api/dailyplan/plan?asof='+encodeURIComponent(this.date+' '+this.time))
        .then(function(r){ if(!r.ok) throw new Error('HTTP '+r.status); return r.json(); })
        .then(function(j){
          if(!j || j.code!==200){ self.plan=null; self.warns=[]; self.errorMsg=(j &amp;&amp; j.msg) || '\u751f\u6210\u5931\u8d25'; return; }
          self.plan=j.plan || null;
          self.kl=j.klines || [];
          self.warns=j.warns || [];
          self.$nextTick(function(){ self.drawK(); });
        })
        .catch(function(e){ console.error('plan err', e); self.errorMsg=String(e &amp;&amp; e.message || e); self.plan=null; })
        .then(function(){ self.busy=false; });
    },
    loadBt(){
      this.busy=true; this.errorMsg='';
      var self=this;
      fetch('/api/dailyplan/backtest?start='+this.btStart+'&end='+this.btEnd)
        .then(function(r){ if(!r.ok) throw new Error('HTTP '+r.status); return r.json(); })
        .then(function(j){
          if(!j || j.code!==200){ self.bt=null; self.errorMsg=(j &amp;&amp; j.msg) || '\u56de\u6d4b\u5931\u8d25'; return; }
          self.bt=j;
          self.$nextTick(function(){ self.drawM(); });
        })
        .catch(function(e){ console.error('bt err', e); self.errorMsg=String(e &amp;&amp; e.message || e); self.bt=null; })
        .then(function(){ self.busy=false; });
    },
    drawK(){
      if(!this.kl.length || !this.plan || !this.plan.prev_day) return;
      var el=document.getElementById('kchart'); if(!el) return;
      this.chart = this.chart || echarts.init(el);
      var t=this.kl.map(function(b){return b.t;});
      var k=this.kl.map(function(b){return [b.o,b.c,b.l,b.h];});
      var pdh=this.plan.prev_day.high, pdl=this.plan.prev_day.low;
      var lines=[];
      var mk=function(v,c,lab){return {yAxis:v,lineStyle:{color:c,type:'dashed',width:1.4},
        label:{formatter:lab,position:'insideEndTop',color:c,fontSize:11}};};
      lines.push(mk(pdh,'#ff3b30','PDH \u591a\u89e6\u53d1'));
      lines.push(mk(pdl,'#34c759','PDL \u7a7a\u89e6\u53d1'));
      if(this.plan.primary){
        lines.push(mk(this.plan.primary.tp1,'#ff9500','TP1 \u591a'));
        lines.push(mk(this.plan.primary.stop,'#af52de','SL \u591a'));
      }
      if(this.plan.secondary){
        lines.push(mk(this.plan.secondary.tp1,'#ff9500','TP1 \u7a7a'));
        lines.push(mk(this.plan.secondary.stop,'#af52de','SL \u7a7a'));
      }
      this.chart.setOption({
        animation:false, grid:{left:58,right:90,top:36,bottom:56},
        tooltip:{trigger:'axis',axisPointer:{type:'cross'}},
        xAxis:{type:'category',data:t,axisLabel:{fontSize:10,color:'#6e6e73'}},
        yAxis:{scale:true,axisLabel:{fontSize:10,color:'#6e6e73'},splitLine:{lineStyle:{color:'#f0f2f5'}}},
        dataZoom:[{type:'inside'},{type:'slider',height:18,bottom:12}],
        series:[{type:'candlestick',data:k,
          itemStyle:{color:'#ff3b30',color0:'#34c759',borderColor:'#ff3b30',borderColor0:'#34c759'}
        },{type:'line',data:[],markLine:{silent:true,symbol:'none',data:lines}}]
      },true);
    },
    drawM(){
      if(!this.bt || !this.bt.monthly || !this.bt.monthly.length) return;
      var el=document.getElementById('mchart'); if(!el) return;
      this.mchart=this.mchart||echarts.init(el);
      var m=this.bt.monthly;
      this.mchart.setOption({
        animation:false, grid:{left:46,right:14,top:20,bottom:34},
        tooltip:{trigger:'axis'},
        xAxis:{type:'category',data:m.map(function(x){return x.m;}),axisLabel:{fontSize:10,color:'#6e6e73'}},
        yAxis:{axisLabel:{fontSize:10,color:'#6e6e73'},splitLine:{lineStyle:{color:'#f0f2f5'}}},
        series:[{type:'bar',data:m.map(function(x){return {value:x.r,itemStyle:{color:x.r&gt;=0?'#ff3b30':'#34c759'}};}),
          label:{show:true,position:'top',fontSize:10,formatter:function(p){return (p.value&gt;=0?'+':'')+p.value.toFixed(1);}}}]
      },true);
    }
  }
}).mount('#app');
</script>
</body>
</html>"""