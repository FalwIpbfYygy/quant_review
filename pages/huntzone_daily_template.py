# -*- coding: utf-8 -*-
"""狩猎区每日效果图 · /huntzone-daily 页面 HTML 模板常量。

最简单版本：30m K线 + 9档阶梯线 + 狩猎区色带 + 方向箭头。
不展示持仓/挂单/止盈止损/事件/P&L。
"""

HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta http-equiv="Cache-Control" content="no-store, no-cache, must-revalidate">
<meta http-equiv="Pragma" content="no-cache">
<meta http-equiv="Expires" content="0">
<title>狩猎区每日效果图 · 30m</title>
<link rel="stylesheet" href="/static/components/topnav.css">
<script src="/vendors/vue.global.prod.js"></script>
<script src="/vendors/echarts.min.js"></script>
<style>
:root{--bg:#f6f7fb;--card:#fff;--ink:#1a1d2e;--sub:#5a6178;--acc:#2962ff}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font-family:-apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;font-size:14px}
.wrap{max-width:1200px;margin:0 auto;padding:16px}
h1{font-size:20px;margin:0 0 8px}
.sub{color:var(--sub);font-size:13px;margin-bottom:14px}
.card{background:var(--card);border:1px solid #eef0f4;border-radius:8px;padding:14px}
.chart-box{width:100%;height:560px}
.controls{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:12px}
input[type=date]{padding:7px 10px;border:1px solid #d9dde7;border-radius:6px;font-size:14px}
.btn{background:var(--acc);color:#fff;border:0;padding:8px 18px;border-radius:6px;font-size:14px;cursor:pointer;font-weight:600}
.btn:hover{background:#1d4fd1}
.btn:disabled{background:#9aaeed;cursor:wait}
.chip{font-size:12px;background:#f0f3f9;color:var(--ink);padding:5px 10px;border-radius:6px;border:1px solid #d9dde7}
.err{color:#c62828;background:#fff5f5;border:1px solid #f5b5b5;padding:8px 12px;border-radius:6px;font-size:13px}
.leg{display:flex;gap:18px;flex-wrap:wrap;margin-top:10px;font-size:12px;color:var(--sub)}
.badge{display:inline-block;padding:2px 10px;border-radius:10px;font-size:12px;font-weight:600}
.short{background:#ffe3f1;color:#c2185b}
.long{background:#e3fbe9;color:#1b7a3d}
.empty{padding:40px;text-align:center;color:var(--sub)}
</style>
</head>
<body>
<div class="topnav">
  <a class="tn-home" href="/">📊 quant_review</a>
  <topnav-bar class="topnav-links" data-active="/huntzone-daily"></topnav-bar>
  <span class="tn-spacer"></span>
  <span class="tn-tag">Binance Futures ·  · 狩猎区30分</span>
</div>

<div class="wrap" id="app">
  <h1>狩猎区每日效果图 · 30m</h1>
  <div class="sub">选择日期，展示当日 30m K线 + 狩猎区 9 档 + 色带 + 方向。不展示持仓/挂单/止盈止损/事件。</div>

  <div class="card">
    <div class="controls">
      <input type="date" v-model="date">
      <button class="btn" @click="load" :disabled="busy">
        <span v-if="busy">生成中…</span><span v-else>🎯 生成</span>
      </button>
      <span class="chip" v-if="data && !data.missing">{{ data.source }} · {{ data.direction_cn }} · S={{ f2(data.S) }} ±{{ f2(data.S_mae) }}</span>
    </div>
    <div v-if="err" class="err">⚠ {{ err }}</div>
    <div v-if="!data && !err" class="empty">选择日期后点击「🎯 生成」</div>
    <div v-if="data && data.missing" class="err">⚠ {{ data.reason }}</div>
    <div v-if="data && !data.missing">
      <div id="chart" class="chart-box"></div>
      <div class="leg">
        <span><span class="badge" :class="data.direction">{{ data.direction_cn }}</span> 方向</span>
        <span style="color:#BA7517">■ 橙实线 = 狩猎区边界 38.2 / 61.8</span>
        <span style="color:#ff6fae;background:rgba(255,111,174,0.15);padding:0 6px;border-radius:3px">■ 粉色区 = 做空狩猎区 [38.2,61.8]</span>
        <span style="color:#2ecc71;background:rgba(46,204,113,0.12);padding:0 6px;border-radius:3px">■ 绿色区 = 做多狩猎区 [38.2,61.8]</span>
        <span style="color:#A32D2D">— 红线 = 止损 19.1</span>
        <span style="color:#0F6E56">— 绿线 = 衰竭 161.8 / 261.8</span>
        <span style="color:#185FA5">— 蓝线 = 开盘价 100.0</span>
      </div>
    </div>
  </div>
</div>

<script src="/static/components/topnav.js" defer></script>
<script>
(function () {
  var API = '/api/huntzone-daily/data';

  function f2(v) {
    return (v === null || v === undefined || isNaN(v)) ? '—' : Number(v).toFixed(2);
  }
  function fmtTs(ms) {
    var d = new Date(ms);
    function p(n){ return (n<10?'0':'')+n; }
    return p(d.getUTCHours()) + ':' + p(d.getUTCMinutes());
  }

  var app = Vue.createApp({
    data: function () {
      var today = new Date();
      function p(n){ return (n<10?'0':'')+n; }
      var ds = today.getFullYear() + '-' + p(today.getMonth()+1) + '-' + p(today.getDate());
      return { date: ds, data: null, busy: false, err: '', chart: null };
    },
    mounted: function () { this.load(); },
    methods: {
      f2: f2,
      load: function () {
        var self = this;
        self.busy = true; self.err = '';
        fetch(API + '?date=' + self.date, { cache: 'no-store' })
          .then(function (r) { return r.json(); })
          .then(function (d) {
            if (!d) { self.err = '接口返回异常'; self.data = null; return; }
            if (d.code === 502) { self.err = d.error || '取数失败'; self.data = null; return; }
            self.data = d;
            if (!d.missing) self.$nextTick(self.renderChart.bind(self));
          })
          .catch(function (e) { self.err = '请求失败：' + e; self.data = null; })
          .then(function () { self.busy = false; });
      },
      renderChart: function () {
        var d = this.data;
        var dom = document.getElementById('chart');
        if (!dom || !d || d.missing) return;
        if (this.chart) { this.chart.dispose(); }
        this.chart = echarts.init(dom, null, { renderer: 'canvas' });
        var candles = d.candles_30m || [];
        var labels = candles.map(function (c) { return fmtTs(c[0]); });
        var cdata = candles.map(function (c) { return [c[1], c[4], c[3], c[2]]; });

        var ml = [];
        (d.levels || []).forEach(function (lv) {
          var r = lv.ratio, color, width = 1, dash = 'solid';
          if (r === 0) { color = '#888780'; dash = 'dashed'; width = 0.8; }
          else if (r === 0.191) { color = '#A32D2D'; width = 1.5; }
          else if (r === 0.382 || r === 0.618) { color = '#BA7517'; width = 1.3; }
          else if (r === 0.5) { color = '#BA7517'; width = 1; dash = 'dashed'; }
          else if (r === 0.809) { color = '#BA7517'; width = 0.9; dash = 'dashed'; }
          else if (r === 1.0) { color = '#185FA5'; width = 1.5; }
          else { color = '#0F6E56'; width = 1.2; }
          ml.push({
            yAxis: lv.price, name: lv.name,
            lineStyle: { color: color, type: dash, width: width },
            label: { show: true, position: 'insideStartTop',
              formatter: lv.name + ' ' + lv.price.toFixed(1),
              color: '#fff', backgroundColor: color,
              padding: [2, 4], fontSize: 10, borderRadius: 2 }
          });
        });

        this.chart.setOption({
          backgroundColor: '#fff',
          grid: { left: 62, right: 28, top: 28, bottom: 42 },
          tooltip: { trigger: 'axis', axisPointer: { type: 'cross' } },
          xAxis: {
            type: 'category', data: labels, boundaryGap: true,
            axisLabel: { fontSize: 10, color: '#5a6178' },
            axisLine: { lineStyle: { color: '#d9dde7' } }
          },
          yAxis: {
            scale: true,
            axisLabel: { fontSize: 10, color: '#5a6178' },
            splitLine: { lineStyle: { color: '#eef0f4' } }
          },
          dataZoom: [
            { type: 'inside', start: 0, end: 100 },
            { type: 'slider', start: 0, end: 100, height: 18, bottom: 18 }
          ],
          series: [{
            type: 'candlestick', name: ' 30m', data: cdata,
            itemStyle: {
              color: '#e53935', color0: '#2ecc71',
              borderColor: '#e53935', borderColor0: '#2ecc71'
            },
            markLine: { symbol: 'none', silent: true, data: ml },
            markArea: {
              silent: true,
              itemStyle: { color: d.direction === 'short'
                ? 'rgba(255,111,174,0.12)' : 'rgba(46,204,113,0.12)' },
              data: [[{ yAxis: d.zone_lo }, { yAxis: d.zone_hi }]]
            },
            markPoint: {
              data: [{
                coord: [0, d.open_px],
                symbol: 'triangle',
                symbolRotate: d.direction === 'short' ? 180 : 0,
                symbolSize: 18,
                itemStyle: { color: d.direction === 'short' ? '#c2185b' : '#1b7a3d' },
                label: { show: true, formatter: d.direction_cn, position: 'right',
                  color: d.direction === 'short' ? '#c2185b' : '#1b7a3d',
                  fontSize: 12, fontWeight: 'bold' }
              }]
            }
          }]
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
