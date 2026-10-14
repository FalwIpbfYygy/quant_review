# D:/quant_review/trade_template.py
# 新 URL /trade 的干净 Vue 3 模板常量。
# 与 dailyplan_template.py 解耦，避免任何历史 HTML 缓存干扰。

HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title> 交易计划 · 可实盘生成器</title>
<style>
*{box-sizing:border-box}
html,body{margin:0;padding:0;font:14px/1.55 -apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif;background:#f5f6f8;color:#1f2330}
a{color:#1f6feb;text-decoration:none}
.wrap{max-width:1120px;margin:0 auto;padding:18px 14px 80px}
.topnav{display:flex;gap:6px;align-items:center;padding:10px 14px;background:#fff;border-bottom:1px solid #e3e6eb;position:sticky;top:0;z-index:10;overflow-x:auto;white-space:nowrap}
.topnav a{display:inline-flex;align-items:center;gap:6px;padding:6px 12px;border-radius:8px;color:#4a5070;font-size:13px;font-weight:500}
.topnav a.active{background:#1f6feb;color:#fff}
.card{background:#fff;border:1px solid #e3e6eb;border-radius:12px;padding:16px 18px;margin-bottom:14px;box-shadow:0 1px 2px rgba(0,0,0,.04)}
.card h2{margin:0 0 12px;font-size:16px;font-weight:600;color:#1f2330;display:flex;align-items:center;gap:8px}
.card h2 .tag{font-size:11px;font-weight:500;padding:2px 8px;background:#eef2ff;color:#4a50b0;border-radius:6px}
.empty{padding:24px;text-align:center;color:#8a8fa3}
.btn{padding:8px 16px;border:0;border-radius:8px;background:#1f6feb;color:#fff;font-size:14px;cursor:pointer;font-weight:500}
.btn:hover{background:#1857c0}
.btn.ghost{background:#eef0f4;color:#4a5070}
.btn:disabled{opacity:.5;cursor:wait}
.warn{padding:10px 14px;border-radius:8px;margin-bottom:8px;font-size:13px;background:#fff8e6;border:1px solid #f5e2a8;color:#7a5c00}
.warn.bad{background:#ffe9e7;border-color:#f3b8b4;color:#a62b25}
.warn b{font-weight:600}
.grid{display:grid;gap:12px}
.g4{grid-template-columns:repeat(4,1fr)}
.g3{grid-template-columns:repeat(3,1fr)}
@media(max-width:780px){.g4,.g3{grid-template-columns:repeat(2,1fr)}}
.kpi{padding:12px;background:#f8f9fb;border:1px solid #eef0f4;border-radius:10px}
.kpi .k{font-size:11px;color:#8a8fa3;text-transform:uppercase;letter-spacing:.5px;margin-bottom:6px}
.kpi .v{font-size:20px;font-weight:600;margin-bottom:4px}
.kpi .v.small{font-size:14px}
.kpi .n{font-size:11px;color:#8a8fa3}
.mono{font-family:"SF Mono","Cascadia Code","JetBrains Mono",Menlo,monospace;font-variant-numeric:tabular-nums}
.up{color:#d63031}
.down{color:#0b9b3f}
.neutral{color:#8a8fa3}
.plancard{border-left:4px solid #1f6feb;padding:14px 16px;background:#f8fbff;border-radius:8px;margin-bottom:10px}
.plancard.short{border-left-color:#d63031;background:#fff6f5}
.plancard b{display:inline-block;min-width:50px}
.tbl{width:100%;border-collapse:collapse;font-size:12px;margin-top:8px}
.tbl th,.tbl td{padding:6px 8px;border-bottom:1px solid #eef0f4;text-align:left;font-variant-numeric:tabular-nums}
.tbl th{color:#8a8fa3;font-weight:500;font-size:11px;text-transform:uppercase}
.tbl td.up{color:#d63031;font-weight:600}
.tbl td.down{color:#0b9b3f;font-weight:600}
.chart{height:340px;width:100%}
.mchart{height:200px;width:100%}
.riskbox{padding:14px;background:#ffe9e7;border:3px solid #d63031;border-radius:8px;margin-bottom:14px;color:#7a1e18;font-size:13px;line-height:1.7}
.riskbox .ttl{font-weight:700;font-size:14px;margin-bottom:6px;color:#a62b25}
.ctrl{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.ctrl input[type=date],.ctrl input[type=text]{padding:7px 10px;border:1px solid #d4d8e0;border-radius:7px;font-size:13px}
.spin{display:inline-block;width:14px;height:14px;border:2px solid #d4d8e0;border-top-color:#1f6feb;border-radius:50%;animation:s .8s linear infinite;vertical-align:middle}
@keyframes s{to{transform:rotate(360deg)}}
.foot{font-size:12px;color:#8a8fa3;border-top:1px solid #eef0f4;padding-top:10px;margin-top:10px;line-height:1.7}
.md{font-size:14px;line-height:1.8;color:#1f2330;word-break:break-word}
.md h2{font-size:17px;font-weight:700;margin:18px 0 8px;padding-left:10px;border-left:4px solid #1f6feb;color:#1f2330}
.md h3{font-size:15px;font-weight:600;margin:14px 0 6px;color:#2a2f40}
.md h4{font-size:14px;font-weight:600;margin:10px 0 4px;color:#2a2f40}
.md p{margin:6px 0}
.md ul,.md ol{margin:6px 0;padding-left:22px}
.md li{margin:3px 0}
.md b,.md strong{color:#1f2330;font-weight:700}
.md a{color:#1f6feb}
</style>
</head>
<body>
<div class="topnav">
  <a href="/">首页</a>
  <a href="/replay">复盘</a>
  <a href="/realtime">实时</a>
  <a href="/market">市场</a>
  <a href="/review">四分屏</a>
  <a href="/psych">心理</a>
  <a href="/habits">习惯</a>
  <a href="/ai_history">AI 记录</a>
  <a href="/trade" class="active">交易计划</a>
</div>
<div class="wrap">

  <div class="riskbox">
    <div class="ttl">⚠️ 重要风险提示</div>
    本报告仅为交易逻辑知识分享，不构成任何投资建议。 现货黄金属高风险金融产品，杠杆交易可能放大亏损，极端行情下存在本金全部亏损的风险。所有价位必须以你所在的经纪商  图表上复核后再下单；回测与派单数据来源为 Binance 现货 PAXGUSDT + 固定 12 美元偏移，与真实  存在浮动基差（通常 10–25 美元）。请投资者结合自身风险承受能力独立决策，入市前请充分了解产品规则。
  </div>

  <div class="card">
    <h2>决策时点<span class="tag">asof 北京时间</span></h2>
    <span v-if="plan &amp;&amp; plan.asof_str" class="sub" style="margin:0 0 6px">决策时点 {{ plan.asof_str }} · 数据源 Binance PAXGUSDT + 12 偏移对齐 </span>
    <div class="ctrl" style="margin-top:8px">
      <input type="date" v-model="date">
      <input type="text" v-model="time" placeholder="HH:MM" size="6">
      <button class="btn" @click="loadPlan" :disabled="busy">生成计划</button>
      <button class="btn ghost" @click="useNow" :disabled="busy">用当前时间</button>
      <button class="btn ghost" @click="loadBt" :disabled="busy">运行回测</button>
      <button class="btn" @click="loadReport" :disabled="busy || reportBusy">生成 AI 报告</button>
    </div>
  </div>

  <div v-if="busy" class="card empty"><span class="spin"></span> 计算中…</div>

  <div v-if="warns.length" style="margin-bottom:14px">
    <div v-for="(w,i) in warns" :key="i" :class="['warn', isObj(w) ? (w.level || '') : '']">
      <b v-if="isObj(w)">{{ w.t }}</b>
      <template v-if="isObj(w)">{{ ' ' + (w.m || '') }}</template>
      <template v-else>{{ w }}</template>
    </div>
  </div>

  <div v-if="errorMsg" class="warn bad"><b>错误</b> {{ errorMsg }}</div>

  <div v-if="plan &amp;&amp; plan.ok">
    <div class="card">
      <h2>决策读数 <span class="tag">外汇交易日 · 纽约 17:00 收市</span></h2>
      <div class="grid g4">
        <div class="kpi"><div class="k">现价</div><div class="v mono">{{ plan.cur }}</div><div class="n">{{ plan.asof_str }} 快照</div></div>
        <div class="kpi"><div class="k">ATR14（日）</div><div class="v mono">{{ plan.atr14 }}</div><div class="n">{{ atrPct }}% of price</div></div>
        <div class="kpi"><div class="k">前一交易日</div><div class="v mono small">{{ plan.prev_day.day }}</div><div class="n">{{ biasText }} · 距现价 {{ distCurAtr }} ATR</div></div>
        <div class="kpi"><div class="k">PDH / PDL</div><div class="v mono"><span class="up">{{ plan.prev_day.high }}</span> / <span class="down">{{ plan.prev_day.low }}</span></div><div class="n">多头触发 / 空头触发</div></div>
        <div class="kpi"><div class="k">前日开</div><div class="v mono">{{ plan.prev_day.open }}</div></div>
        <div class="kpi"><div class="k">前日收</div><div class="v mono">{{ plan.prev_day.close }}</div></div>
        <div class="kpi"><div class="k">数据样本</div><div class="v mono">{{ plan.bars_used }}</div><div class="n">5m bar</div></div>
        <div class="kpi"><div class="k">日线样本</div><div class="v mono">{{ plan.daily_used }}</div><div class="n">外汇日</div></div>
      </div>
      <div v-if="too_close" class="warn" style="margin-top:10px"><b>区间过窄</b> PDH/PDL 与现价距离均小于 0.05 ATR，突破信号比较低，建议当日观望。</div>
    </div>

    <div v-if="plan.primary" class="card">
      <h2>A · 主计划 <span class="tag">{{ plan.primary.side === 'long' ? '突破做多' : '突破做空' }}</span></h2>
      <div :class="['plancard', plan.primary.side === 'short' ? 'short' : '']">
        <div><b>触发</b> {{ plan.primary.side === 'long' ? '向上突破 PDH ' + plan.primary.trigger : '向下跌破 PDL ' + plan.primary.trigger }} <span class="mono up" v-if="plan.primary.side==='long'">↑</span><span class="mono down" v-else>↓</span></div>
        <div><b>止损</b> <span class="mono down">{{ plan.primary.stop }}</span> <span class="neutral">(R = {{ plan.primary.risk }})</span></div>
        <div><b>TP1</b> <span class="mono up">{{ plan.primary.tp1 }}</span> (1.0R)</div>
        <div><b>TP2</b> <span class="mono up">{{ plan.primary.tp2 }}</span> (1.8R)</div>
        <div><b>建议</b> {{ plan.primary.lots }} 手（基于单笔 0.2R 风控）</div>
        <div><b>有效期</b> {{ plan.primary.deadline }}</div>
      </div>
    </div>

    <div v-if="plan.secondary" class="card">
      <h2>B · 备选计划 <span class="tag">{{ plan.secondary.side === 'long' ? '突破做多' : '突破做空' }}</span></h2>
      <div :class="['plancard', plan.secondary.side === 'short' ? 'short' : '']">
        <div><b>触发</b> {{ plan.secondary.side === 'long' ? '向上突破 PDH ' + plan.secondary.trigger : '向下跌破 PDL ' + plan.secondary.trigger }}</div>
        <div><b>止损</b> <span class="mono down">{{ plan.secondary.stop }}</span> <span class="neutral">(R = {{ plan.secondary.risk }})</span></div>
        <div><b>TP1</b> <span class="mono up">{{ plan.secondary.tp1 }}</span> (1.0R)</div>
        <div><b>TP2</b> <span class="mono up">{{ plan.secondary.tp2 }}</span> (1.8R)</div>
      </div>
    </div>

    <div class="card">
      <h2>5分钟 K 线 <span class="tag">前 3 个交易日</span></h2>
      <div id="kchart" class="chart"></div>
    </div>

    <div class="card">
      <h2>回测统计 <span class="tag">{{ bt ? bt.n_trades + ' 笔 · ' + (bt.win_rate*100).toFixed(1) + '% 胜率' : '' }}</span></h2>
      <div v-if="bt">
        <div class="grid g3" style="margin-bottom:10px">
          <div class="kpi"><div class="k">样本</div><div class="v mono">{{ bt.n_trades }} 笔</div><div class="n">{{ bt.start }} ~ {{ bt.end }}</div></div>
          <div class="kpi"><div class="k">期望值</div><div :class="['v mono', bt.ev_r>=0?'up':'down']">{{ fmtR(bt.ev_r) }} R</div><div class="n">单笔期望</div></div>
          <div class="kpi"><div class="k">盈亏比</div><div class="v mono">{{ bt.profit_factor.toFixed(2) }}</div><div class="n">PF</div></div>
        </div>
        <div id="mchart" class="mchart"></div>
        <details style="margin-top:10px"><summary style="cursor:pointer;color:#4a5070">最近 15 笔明细</summary>
          <table class="tbl" style="margin-top:8px">
            <thead><tr><th>时间</th><th>方向</th><th>R</th><th>持仓(bar)</th></tr></thead>
            <tbody>
              <tr v-for="(r,i) in bt.recent" :key="i">
                <td>{{ r.day }} {{ r.time }}</td>
                <td :class="r.r>=0?'up':'down'">{{ r.r>=0?'+':'' }}{{ fmtR(r.r) }} R</td>
                <td :class="r.r>=0?'up':'down'">{{ r.r>=0?'+':'' }}{{ fmtR(r.r) }}</td>
                <td>{{ r.bars }}</td>
              </tr>
            </tbody>
          </table>
        </details>
      </div>
      <div v-else class="empty">尚无数据，请点击「运行回测」。</div>
    </div>

    <div class="card">
      <h2>AI 分析师报告 <span class="tag">大模型生成 · 仅供参考</span></h2>
      <div v-if="reportBusy" class="empty"><span class="spin"></span> AI 正在撰写报告（约 1–2 分钟，模型越大越慢）…</div>
      <div v-else-if="report" class="md" v-html="renderedReport"></div>
      <div v-else class="empty">点击上方「生成 AI 报告」生成当日  交易计划报告（调用阿里云百炼大模型）。</div>
    </div>
  </div>

  <div v-else-if="plan &amp;&amp; !plan.ok" class="card empty">无计划：{{ plan.reason }}（'信号失效或数据不足'）</div>

  <div class="foot">
    数据口径：行情来自 Binance 现货 PAXGUSDT + 12 美元偏移对齐 ，非经纪商盘面，基差为浮动值，实测与  相差可达 10–25 美元——所有价位必须以你所在的经纪商  图表上复核后再下单。<br>
    日线切分：外汇交易日（纽约 17:00 收市；夏令时北京时间 05:00，冬令时 06:00），已按美国 DST 规则校时计算。<br>
    已识局限：加密盘 7×24 无周末跳空，但  周末休市——回测的"最差单笔"低估了跳空价差风险，建议周五收盘前平仓，不持仓过周末；日内根 K 线内无法约定 SL/TP 先后，统一按保守假设（突破当下根的 close 计入）。<br>
    <br>
    ▲ <b>风险提示与免责声明</b>：本页面内容仅为基于公开与本地数据的分析讨论，不构成任何投资建议、理财建议或交易邀约。市场有风险，投资需谨慎。
  </div>

</div>

<script src="/vendors/echarts.min.js"></script>
<script src="/vendors/marked.min.js"></script>
<script src="/vendors/purify.min.js"></script>
<script src="/vendors/vue.global.prod.js"></script>
<script>
const { createApp } = Vue;
createApp({
  data(){
    return {
      date:'', time:'09:00', busy:false,
      plan:null, kl:[], warns:[], errorMsg:'',
      btStart:'2026-02-01', btEnd:'2026-09-04', bt:null,
      chart:null, mchart:null,
      report:'', reportBusy:false
    };
  },
  computed:{
    atrPct(){ var p=this.plan; return (p && p.cur && p.atr14) ? (p.atr14/p.cur*100).toFixed(2) : '\u2014'; },
    distCurAtr(){
      var p=this.plan; if(!p || !p.cur || !p.atr14 || !p.prev_day) return '\u2014';
      var ph=p.prev_day.high, pl=p.prev_day.low;
      if(ph==null || pl==null) return '\u2014';
      var d=Math.min(Math.abs(ph-p.cur), Math.abs(pl-p.cur));
      return (d/p.atr14).toFixed(3);
    },
    biasText(){
      var m={'neutral':'\u4e2d\u6027','long':'\u504f\u591a','short':'\u504f\u7a7a'};
      return m[this.plan && this.plan.bias] || '\u2014';
    },
    too_close(){
      var p=this.plan; if(!p || !p.cur || !p.atr14) return false;
      var d=this.distCurAtr; if(d==='\u2014') return false;
      return Number(d) < 0.05;
    },
    renderedReport(){
      if(!this.report) return '';
      try{
        var raw = (window.marked ? marked.parse(this.report) : this.report);
        return window.DOMPurify ? DOMPurify.sanitize(raw) : raw;
      }catch(e){ return this.report; }
    }
  },
  mounted(){
    this.useNow();
    var self=this;
    window.addEventListener('resize', function(){ if(self.chart) self.chart.resize(); if(self.mchart) self.mchart.resize(); });
  },
  methods:{
    isObj(x){ return x && typeof x === 'object'; },
    fmtR(v){ if(v==null || isNaN(v)) return '\u2014'; return (v>=0?'+':'')+Number(v).toFixed(3); },
    loadReport(){
      this.reportBusy=true; this.errorMsg='';
      var self=this;
      fetch('/api/dailyplan/report?asof='+encodeURIComponent(this.date+' '+this.time), {cache:'no-store'})
        .then(function(r){ if(!r.ok) throw new Error('HTTP '+r.status); return r.json(); })
        .then(function(j){
          if(!j || j.code!==200){ self.report=''; self.errorMsg=(j && j.msg) || '\u62a5\u544a\u751f\u6210\u5931\u8d25'; return; }
          self.report=j.report || '';
        })
        .catch(function(e){ console.error('report err', e); self.errorMsg=String(e && e.message || e); self.report=''; })
        .then(function(){ self.reportBusy=false; });
    },
    useNow(){
      var n=new Date();
      this.date = n.getFullYear()+'-'+String(n.getMonth()+1).padStart(2,'0')+'-'+String(n.getDate()).padStart(2,'0');
      var mm = Math.floor(n.getMinutes()/5)*5;
      this.time = String(n.getHours()).padStart(2,'0')+':'+String(mm).padStart(2,'0');
    },
    loadPlan(){
      this.busy=true; this.errorMsg='';
      var self=this;
      fetch('/api/dailyplan/plan?asof='+encodeURIComponent(this.date+' '+this.time), {cache:'no-store'})
        .then(function(r){ if(!r.ok) throw new Error('HTTP '+r.status); return r.json(); })
        .then(function(j){
          if(!j || j.code!==200){ self.plan=null; self.warns=[]; self.errorMsg=(j && j.msg) || '\u751f\u6210\u5931\u8d25'; return; }
          self.plan=j.plan || null;
          self.kl=j.klines || [];
          self.warns=j.warns || [];
          self.$nextTick(function(){ self.drawK(); });
        })
        .catch(function(e){ console.error('plan err', e); self.errorMsg=String(e && e.message || e); self.plan=null; })
        .then(function(){ self.busy=false; });
    },
    loadBt(){
      this.busy=true; this.errorMsg='';
      var self=this;
      fetch('/api/dailyplan/backtest?start='+this.btStart+'&end='+this.btEnd, {cache:'no-store'})
        .then(function(r){ if(!r.ok) throw new Error('HTTP '+r.status); return r.json(); })
        .then(function(j){
          if(!j || j.code!==200){ self.bt=null; self.errorMsg=(j && j.msg) || '\u56de\u6d4b\u5931\u8d25'; return; }
          self.bt=j;
          self.$nextTick(function(){ self.drawM(); });
        })
        .catch(function(e){ console.error('bt err', e); self.errorMsg=String(e && e.message || e); self.bt=null; })
        .then(function(){ self.busy=false; });
    },
    drawK(){
      var self=this;
      try{
        var el=document.getElementById('kchart'); if(!el || !self.kl || !self.kl.length) return;
        self.chart = echarts.init(el);
        var times=self.kl.map(function(b){return b.t;});
        var ohlc=self.kl.map(function(b){return [b.o,b.c,b.l,b.h];});
        var mq=self.kl.map(function(b){return b.c;});
        self.chart.setOption({
          grid:{left:50,right:20,top:20,bottom:30},
          xAxis:{type:'category',data:times,axisLabel:{fontSize:10}},
          yAxis:{scale:true},
          tooltip:{trigger:'axis'},
          dataZoom:[{type:'inside'},{type:'slider',height:18}],
          series:[{type:'candlestick',data:ohlc,name:'5m'},
                  {type:'line',data:mq,smooth:true,showSymbol:false,lineStyle:{width:1,color:'#888'},name:'close'}]
        });
      }catch(e){ console.error('drawK err', e); }
    },
    drawM(){
      var self=this;
      try{
        var el=document.getElementById('mchart'); if(!el || !self.bt || !self.bt.monthly || !self.bt.monthly.length) return;
        self.mchart = echarts.init(el);
        var x=self.bt.monthly.map(function(m){return m.month;});
        var y=self.bt.monthly.map(function(m){return Number(m.ev.toFixed(3));});
        self.mchart.setOption({
          grid:{left:50,right:20,top:30,bottom:30},
          xAxis:{type:'category',data:x},
          yAxis:{type:'value',name:'R'},
          tooltip:{trigger:'axis'},
          series:[{type:'bar',data:y.map(function(v){return {value:v,itemStyle:{color:v>=0?'#d63031':'#0b9b3f'}};})}]
        });
      }catch(e){ console.error('drawM err', e); }
    }
  }
}).mount('#app');
</script>
</body>
</html>
"""
