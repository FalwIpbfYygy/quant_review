# -*- coding: utf-8 -*-
"""白银 XAGUSD 狩猎区复盘 · /huntzone-review-xag 页面 HTML 模板常量。

视觉与交互 1:1 对齐 /huntzone-review（每交易日一列：左侧 30m K线 + 右侧 ladder 色带），
唯一差异：
  - 数据与标题改为 XAGUSDT（Binance fapi）；
  - 顶部增加「S 标定」控件：默认走 XAU 冻结模型（原逻辑），可一键切「白银自适应 S」；
  - 增加数量级错配免责声明（冻结模型 S 区间 36~117 美元点 vs 白银 ~$40）。
"""

HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta http-equiv="Cache-Control" content="no-store, no-cache, must-revalidate">
<meta http-equiv="Pragma" content="no-cache">
<meta http-equiv="Expires" content="0">
<title>XAG / ETH / BTC 狩猎区复盘 · 30m</title>
<link rel="stylesheet" href="/static/components/topnav.css">
<script src="/vendors/vue.global.prod.js"></script>
<script src="/vendors/echarts.min.js"></script>
<style>
:root{--bg:#f6f7fb;--card:#fff;--ink:#1a1d2e;--sub:#5a6178;--acc:#2962ff}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font-family:-apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;font-size:14px}
.wrap{max-width:1280px;margin:0 auto;padding:16px}
h1{font-size:20px;margin:0 0 8px}
.sub{color:var(--sub);font-size:13px;margin-bottom:14px}
.card{background:var(--card);border:1px solid #eef0f4;border-radius:8px;padding:14px}
.chart-scroll{width:100%;overflow-x:auto;border:1px solid #eef0f4;border-radius:6px;background:#fff}
.chart-inner{height:720px}
.controls{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:12px}
input[type=date]{padding:7px 10px;border:1px solid #d9dde7;border-radius:6px;font-size:14px}
.btn{background:var(--acc);color:#fff;border:0;padding:8px 16px;border-radius:6px;font-size:14px;cursor:pointer;font-weight:600}
.btn:hover{background:#1d4fd1}
.btn:disabled{background:#9aaeed;cursor:wait}
.btn.ghost{background:#eef1f7;color:var(--ink)}
.btn.ghost.active{background:var(--acc);color:#fff}
.btn.warn{background:#fff4e5;color:#b26a00;border:1px solid #f0c98a}
.chip{font-size:12px;background:#f0f3f9;color:var(--ink);padding:5px 10px;border-radius:6px;border:1px solid #d9dde7}
.err{color:#c62828;background:#fff5f5;border:1px solid #f5b5b5;padding:8px 12px;border-radius:6px;font-size:13px}
.disc{color:#8a5a00;background:#fff8ec;border:1px solid #f3d9a6;padding:8px 12px;border-radius:6px;font-size:12.5px;margin-bottom:12px;line-height:1.6}
.leg{display:flex;gap:18px;flex-wrap:wrap;margin-top:10px;font-size:12px;color:var(--sub)}
.badge{display:inline-block;padding:2px 10px;border-radius:10px;font-size:12px;font-weight:600}
.short{background:#e3fbe9;color:#1b7a3d}
.long{background:#ffe3f1;color:#c2185b}
.slider-wrap{display:flex;align-items:center;gap:10px;margin-top:12px;flex-wrap:wrap}
.slider-wrap input[type=range]{flex:1;min-width:220px}
.focus-info{font-size:13px;color:var(--ink)}
.empty{padding:40px;text-align:center;color:var(--sub)}
.status{font-size:12px;color:var(--sub);margin-top:8px}
.s-input{width:120px;padding:6px 8px;border:1px solid #d9dde7;border-radius:6px;font-size:14px}
</style>
</head>
<body>
<div class="topnav">
  <a class="tn-home" href="/">📊 quant_review</a>
  <topnav-bar class="topnav-links" data-active="/huntzone-review-xag"></topnav-bar>
  <span class="tn-spacer"></span>
  <span class="tn-tag">{{ symbol }} · 狩猎区复盘 · Binance fapi</span>
</div>

<div class="wrap" id="app">
  <h1>XAG / ETH / BTC 狩猎区复盘 · 30m</h1>
  <div class="sub">每个交易日一列：左侧 30m K线，右侧叠加 ladder（警戒线 / 狩猎区 / 衰竭线）。横向滚动或拖动滑动条浏览。数据源：Binance USDT-M 永续（XAGUSDT / ETHUSDT / BTCUSDT）。</div>

  <div class="disc">
    ⚠ <b>S 标定说明</b>：档位几何（<code>hz_engine.build</code>）与方向逻辑完全复用 XAU 原逻辑。
    跨度 <b>S</b> <b>默认走「自适应」</b>——按每根日线「当日及以前」的真实波幅(TR)中位数标定（<b>零未来函数</b>），
    狩猎区因此落在价格附近、正常显示。自适应 S 对 XAG / ETH / BTC 均适用。
    <b>「原逻辑 S」</b> = XAU 冻结回归模型 <code>S_MODEL_FROZEN</code>（按黄金 $4000 标定，S 区间 36~117），
    仅黄金语境有意义，套到 XAG/ETH/BTC 会<b>数量级错配</b>（狩猎区飞到屏幕外、看不到），仅供对照、请勿用于实盘。
  </div>

  <div class="card">
    <div class="controls">
      <span class="chip">币种</span>
      <button class="btn ghost" :class="{active: symbol==='XAGUSDT'}" @click="setSymbol('XAGUSDT')">XAG 白银</button>
      <button class="btn ghost" :class="{active: symbol==='ETHUSDT'}" @click="setSymbol('ETHUSDT')">ETH 以太坊</button>
      <button class="btn ghost" :class="{active: symbol==='BTCUSDT'}" @click="setSymbol('BTCUSDT')">BTC 比特币</button>
      <button class="btn ghost" :class="{active: rangeMode==='3'}" @click="preset(3)">最近 3 天</button>
      <button class="btn ghost" :class="{active: rangeMode==='7'}" @click="preset(7)">最近 7 天</button>
      <span class="chip">自定义</span>
      <input type="date" v-model="start">
      <span style="color:var(--sub)">至</span>
      <input type="date" v-model="end">
      <span class="chip">S 标定</span>
      <button class="btn ghost" :class="{active: mode==='adaptive'}" @click="setMode('adaptive')">自适应 S<span v-if="suggestedS">（{{ suggestedS }}）</span></button>
      <button class="btn ghost" :class="{active: mode==='frozen'}" @click="setMode('frozen')">原逻辑 S（黄金冻结·仅对照）</button>
      <input class="s-input" type="number" step="0.01" v-model="manualS" placeholder="手动 S" @keyup.enter="load">
      <button class="btn" @click="load" :disabled="busy">
        <span v-if="busy">生成中…</span><span v-else>🎯 生成</span>
      </button>
      <span class="chip" v-if="data && data.ok">{{ data.symbol }} · {{ data.panels.length }} 日</span>
      <span class="chip" v-if="manualS">手动 S={{ manualS }}</span>
      <span class="chip" v-else-if="mode==='frozen'">原逻辑 S</span>
      <span class="chip" v-else>自适应 S</span>
    </div>

    <div v-if="err" class="err">⚠ {{ err }}</div>
    <div v-if="!data && !err" class="empty">选择范围后点击「🎯 生成」</div>
    <div v-if="data && !data.ok" class="err">⚠ {{ data.reason }}</div>

    <div v-if="data && data.ok">
      <div class="chart-scroll" ref="scrollBox">
        <div id="chart" class="chart-inner" ref="chartBox"></div>
      </div>

      <div class="slider-wrap" v-if="data.panels.length">
        <span class="focus-info">滑动浏览：<b>{{ focusPanel.date }}</b>
          <span v-if="focusPanel.has_signal" class="badge" :class="focusPanel.direction">{{ focusPanel.direction_cn }}</span>
          <span v-else class="badge" style="background:#eee;color:#999">无信号</span>
          <span v-if="focusPanel.has_signal"> 开 {{ focusPanel.open_px }} ｜ S {{ focusPanel.S }} ｜ 狩猎区 {{ focusPanel.zone_lo }}~{{ focusPanel.zone_hi }}</span>
        </span>
        <input type="range" min="0" :max="data.panels.length-1" step="1" v-model.number="focusIdx" @input="scrollToFocus">
      </div>

      <div class="leg">
        <span><span class="badge" style="background:#e53935;color:#fff">涨</span> 红涨 / <span class="badge" style="background:#2ecc71;color:#fff">跌</span> 绿跌</span>
        <span style="color:#1b7a3d;background:rgba(27,122,61,0.12);padding:0 6px;border-radius:3px">■ 绿色 = 做空狩猎区</span>
        <span style="color:#c2185b;background:rgba(194,24,89,0.12);padding:0 6px;border-radius:3px">■ 红色 = 做多狩猎区</span>
        <span style="color:#9c27b0">— 警戒线 = 80.9 档</span>
        <span style="color:#888">— 衰竭线 = 161.8 / 261.8</span>
        <span style="color:#185FA5">— 蓝线 = 开盘价 100.0</span>
      </div>
      <div class="status" v-if="data.missing_days.length">30m 缺失日：{{ data.missing_days.join('，') }}</div>
    </div>
  </div>
</div>

<script src="/static/components/topnav.js" defer></script>
<script>
(function () {
  var API = '/api/huntzone-review-xag/data';
  var COL_W = 330;  // 每列像素宽度（放大 K 线）

  function pad(n){ return (n<10?'0':'')+n; }
  function f2(v){ return (v===null||v===undefined||isNaN(v)) ? '—' : Number(v).toFixed(2); }
  function utcDateStr(d){ return d.getUTCFullYear()+'-'+pad(d.getUTCMonth()+1)+'-'+pad(d.getUTCDate()); }
  function fmtTime(ms){
    var d = new Date(ms + 8 * 60 * 60 * 1000); // 1m/30m 数据为 UTC，显示转 UTC+8 北京时间
    return pad(d.getUTCHours())+':'+pad(d.getUTCMinutes());
  }
  function niceInterval(raw){
    if (raw <= 0 || !isFinite(raw)) return 0.1;
    var pow10 = Math.pow(10, Math.floor(Math.log10(raw)));
    var frac = raw / pow10;
    var nice = frac <= 1 ? 1 : frac <= 2 ? 2 : frac <= 2.5 ? 2.5 : frac <= 5 ? 5 : 10;
    return nice * pow10;
  }

  function levelPrice(p, ratio){
    if (!p || !p.levels) return null;
    for (var i=0;i<p.levels.length;i++){
      var lv=p.levels[i];
      if (Math.abs(Math.round(lv.ratio*1000)/1000 - ratio) < 0.001) return lv.price;
    }
    return null;
  }

  function buildSeries(p, idx, n){
    var candles = p.candles_30m || [];
    var labels = candles.map(function (c){ return fmtTime(c[0]); });
    var cdata = candles.map(function (c){ return [c[1], c[4], c[3], c[2]]; });
    var lastIdx = Math.max(0, candles.length - 1);

    var isLong = p.direction === 'long';
    var zoneColor = isLong ? 'rgba(229,57,53,0.18)' : 'rgba(46,204,113,0.18)';
    var lineColor = isLong ? '#e53935' : '#2ecc71';

    var markLines = [];

    var jg = levelPrice(p, 0.809);
    if (jg !== null) {
      markLines.push({ yAxis: jg,
        lineStyle: { color: lineColor, width: 1.5 },
        label: { show: true, position: 'insideStartTop',
          formatter: '警戒线【' + jg.toFixed(2) + '】',
          color: '#fff', backgroundColor: lineColor,
          padding: [2,4], fontSize: 10, borderRadius: 2 }
      });
    }

    [1.618, 2.618].forEach(function (r){
      var pr = levelPrice(p, r);
      if (pr !== null) {
        markLines.push({ yAxis: pr,
          lineStyle: { color: '#888', width: 1, type: 'dashed' },
          label: { show: true, position: 'insideEndTop',
            formatter: '衰竭线【' + pr.toFixed(2) + '】',
            color: '#fff', backgroundColor: '#888',
            padding: [2,4], fontSize: 10, borderRadius: 2 }
        });
      }
    });

    var op = levelPrice(p, 1.0);
    if (op !== null) {
      markLines.push({ yAxis: op,
        lineStyle: { color: '#185FA5', width: 1, type: 'dashed' },
        label: { show: false }
      });
    }

    var leg = levelPrice(p, 0.0);
    if (leg !== null) {
      markLines.push({ yAxis: leg,
        lineStyle: { color: '#888780', width: 0.8, type: 'dashed' },
        label: { show: false }
      });
    }

    var stop = levelPrice(p, 0.191);
    if (stop !== null) {
      markLines.push({ yAxis: stop,
        lineStyle: { color: '#A32D2D', width: 1.2 },
        label: { show: true,
          position: p.direction === 'short' ? 'insideStartTop' : 'insideStartBottom',
          formatter: '止损【' + stop.toFixed(2) + '】',
          color: '#fff', backgroundColor: '#A32D2D',
          padding: [2,4], fontSize: 10, borderRadius: 2 }
      });
    }

    var markAreaData = [];
    if (p.has_signal && p.zone_lo !== null && p.zone_hi !== null) {
      markAreaData.push([
        { xAxis: 0, yAxis: p.zone_lo },
        { xAxis: lastIdx, yAxis: p.zone_hi }
      ]);
      var mid = (p.zone_lo + p.zone_hi) / 2;
      markLines.push({ yAxis: mid,
        lineStyle: { color: 'transparent', width: 0 },
        label: { show: true, position: 'insideStartTop',
          formatter: '狩猎区【' + p.zone_lo.toFixed(2) + '-' + p.zone_hi.toFixed(2) + '】',
          color: '#fff', backgroundColor: lineColor,
          padding: [2,4], fontSize: 10, borderRadius: 2 }
      });
    } else {
      var gLo = Infinity, gHi = -Infinity;
      for (var gi = 0; gi < cdata.length; gi++) {
        var cc = cdata[gi];
        if (cc[2] < gLo) gLo = cc[2];
        if (cc[3] > gHi) gHi = cc[3];
      }
      if (isFinite(gLo) && isFinite(gHi) && gHi > gLo) {
        markAreaData.push([
          { xAxis: 0, yAxis: gLo, itemStyle: { color: 'rgba(46,204,113,0.18)' } },
          { xAxis: lastIdx, yAxis: gHi }
        ]);
        markLines.push({ yAxis: gHi,
          lineStyle: { color: 'transparent', width: 0 },
          label: { show: true, position: 'insideStartTop',
            formatter: '无信号·绿区',
            color: '#fff', backgroundColor: '#2ecc71',
            padding: [2,4], fontSize: 10, borderRadius: 2 }
        });
      }
    }

    return {
      xAxisIndex: idx, yAxisIndex: idx,
      type: 'candlestick', name: p.date, data: cdata,
      itemStyle: {
        color: '#e53935', color0: '#2ecc71',
        borderColor: '#e53935', borderColor0: '#2ecc71'
      },
      markLine: { symbol: 'none', silent: true, data: markLines },
      markArea: {
        silent: true,
        itemStyle: { color: zoneColor },
        data: markAreaData
      }
    };
  }

  var app = Vue.createApp({
    data: function () {
      var now = new Date();
      var end = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate()));
      var start = new Date(end.getTime() - 6*86400000);
      return {
        start: utcDateStr(start), end: utcDateStr(end),
        rangeMode: '7',
        symbol: 'XAGUSDT',
        mode: 'adaptive',
        data: null, busy: false, err: '',
        chart: null, focusIdx: 0,
        manualS: '', suggestedS: null
      };
    },
    computed: {
      focusPanel: function () {
        if (!this.data || !this.data.panels.length) return {date:''};
        var i = Math.min(this.focusIdx, this.data.panels.length-1);
        return this.data.panels[i] || this.data.panels[0];
      }
    },
    mounted: function () { this.load(); },
    methods: {
      f2: f2,
      preset: function (n) {
        this.rangeMode = String(n);
        var now = new Date();
        var end = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate()));
        var start = new Date(end.getTime() - (n-1)*86400000);
        this.end = utcDateStr(end); this.start = utcDateStr(start);
        this.load();
      },
      setMode: function (m) {
        this.mode = m; this.manualS = ''; this.load();
      },
      setSymbol: function (s) {
        this.symbol = s; this.manualS = '';
        this.load();
      },
      load: function () {
        var self = this; self.busy = true; self.err = '';
        var url = API + '?start=' + self.start + '&end=' + self.end
                 + '&symbol=' + self.symbol + '&mode=' + self.mode;
        if (self.manualS !== '' && !isNaN(parseFloat(self.manualS))) {
          url += '&S=' + parseFloat(self.manualS);
        }
        fetch(url, { cache: 'no-store' })
          .then(function (r){ return r.json(); })
          .then(function (d) {
            if (!d) { self.err = '接口返回异常'; self.data = null; return; }
            if (d.code === 502) { self.err = d.error || '取数失败'; self.data = null; return; }
            self.data = d;
            self.suggestedS = (d.suggested_S != null) ? d.suggested_S : self.suggestedS;
            if (d.ok) self.focusIdx = 0;
            if (d.ok) self.$nextTick(self.renderChart.bind(self));
          })
          .catch(function (e){ self.err = '请求失败：' + e; self.data = null; })
          .then(function (){ self.busy = false; });
      },
      scrollToFocus: function () {
        var box = this.$refs.scrollBox;
        if (!box) return;
        box.scrollLeft = this.focusIdx * COL_W;
      },
      renderChart: function () {
        var d = this.data;
        var dom = this.$refs.chartBox;
        if (!dom || !d || !d.ok) return;

        var panels = d.panels || [];
        var n = panels.length || 1;
        dom.style.width = (10 + n * COL_W) + 'px';

        if (this.chart) { this.chart.dispose(); }
        this.chart = echarts.init(dom, null, { renderer: 'canvas' });

        var grids = [], xAxes = [], yAxes = [], series = [], titles = [];

        var candleMin = Infinity, candleMax = -Infinity;
        var levelMin = Infinity, levelMax = -Infinity;
        panels.forEach(function (p){
          var candles = p.candles_30m || [];
          candles.forEach(function (c){
            if (c[3] < candleMin) candleMin = c[3];
            if (c[2] > candleMax) candleMax = c[2];
          });
          (p.levels || []).forEach(function (lv){
            if (lv.price !== null && !isNaN(lv.price)) {
              if (lv.price < levelMin) levelMin = lv.price;
              if (lv.price > levelMax) levelMax = lv.price;
            }
          });
        });
        if (!isFinite(candleMin) || !isFinite(candleMax) || candleMax <= candleMin) {
          candleMin = 0; candleMax = 1;
        }
        var dataRange = candleMax - candleMin;
        var hardMin = candleMin - dataRange;
        var hardMax = candleMax + dataRange;
        var globalMin = Math.min(candleMin, Math.max(levelMin, hardMin)) - dataRange * 0.08;
        var globalMax = Math.max(candleMax, Math.min(levelMax, hardMax)) + dataRange * 0.08;
        var yInterval = niceInterval((globalMax - globalMin) / 8);
        if (!(yInterval > 0)) yInterval = 0.1;
        globalMin = Math.floor(globalMin / yInterval) * yInterval;
        globalMax = Math.ceil(globalMax / yInterval) * yInterval;

        panels.forEach(function (p, i){
          var left = 10 + i * COL_W;
          grids.push({ left: left, width: COL_W - 20, top: 44, bottom: 44 });
          xAxes.push({ gridIndex: i, type: 'category', data: [], boundaryGap: true,
            axisLabel: { show: false }, axisLine: { show: false }, splitLine: { show: false } });
          yAxes.push({ gridIndex: i, scale: false, min: globalMin, max: globalMax, interval: yInterval,
            axisLabel: { fontSize: 10, color: '#5a6178',
              formatter: function (v){ return Number(v).toFixed(2); } },
            splitLine: { lineStyle: { color: '#f0f0f0' } } });

          var titleText = p.date + '\n';
          if (p.has_signal) titleText += p.direction_cn + ' S=' + f2(p.S);
          else titleText += '无信号';
          titles.push({ text: titleText, left: left + 6, top: 14,
            textStyle: { fontSize: 11, color: p.has_signal ? (p.direction==='long'?'#c2185b':'#1b7a3d'):'#888' } });

          series.push(buildSeries(p, i, n));
          xAxes[i].data = (p.candles_30m || []).map(function (c){ return fmtTime(c[0]); });
        });

        this.chart.setOption({
          backgroundColor: '#fff',
          title: titles,
          tooltip: { trigger: 'axis', axisPointer: { type: 'cross' } },
          grid: grids,
          xAxis: xAxes,
          yAxis: yAxes,
          series: series
        }, true);
      }
    }
  });
  app.mount('#app');
})();
</script>
</body>
</html>
"""
