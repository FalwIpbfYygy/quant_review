# -*- coding: utf-8 -*-
"""狩猎区画廊 · /huntzone-gallery 页面 HTML 模板常量

为什么内联成常量而不是独立 .html：同 huntv2_template（独立 .html 会被同步工具循环覆写导致白屏）。
数据契约：严格对齐 /api/huntzone-gallery/slides 与 /api/huntzone-gallery/day 的真实返回体
          （见 huntzone_gallery_core.GALLERY_SCHEMA）。

纪律（与 M1 引擎一致）：
  严格因果、零未来函数；1m→1h 聚合只用已逝 bar；取数失败明确报错，绝不猜 S。
  本页系统自取日线 / 顺势方向 / 冻结回归 S / build 正解几何，零人工输入。

交互：横向 scroll-snap 轮播，◀▶ / 圆点 / ←→ 键切换；IntersectionObserver 懒加载 ECharts
     （同屏至多 3 个实例）；"看 1m 细部" 按钮按需拉取当日 1m 并重绘。
"""

HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta http-equiv="Cache-Control" content="no-store, no-cache, must-revalidate">
<meta http-equiv="Pragma" content="no-cache">
<meta http-equiv="Expires" content="0">
<title>狩猎区画廊 · 多日滑动</title>
<link rel="stylesheet" href="/static/components/topnav.css">
<script src="/vendors/vue.global.prod.js"></script>
<script src="/vendors/echarts.min.js"></script>
<style>
:root{
  --bg:#f6f7fb; --card:#fff; --ink:#1a1d2e; --sub:#5a6178; --acc:#2962ff;
  --up:#e53935; --dn:#2ecc71; --warn:#ff9800; --line:#eef0f4;
  --line2:#d9dde7; --soft:#f0f3f9;
  --green-z:#2ecc71; --pink-z:#ff6fae;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
  font-family:-apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;font-size:14px}
.wrap{max-width:1180px;margin:0 auto;padding:16px}
.topnav{background:#fff;border-bottom:1px solid var(--line);padding:0 24px;display:flex;
  align-items:center;gap:6px;min-height:48px;height:auto;flex-wrap:wrap;position:sticky;top:0;z-index:10}
.tn-home{font-weight:700;color:var(--ink);margin-right:18px;text-decoration:none;font-size:15px}
.tn-spacer{flex:1}
.tn-tag{font-size:11px;background:var(--soft);color:var(--sub);padding:3px 9px;border-radius:10px}
.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:16px;margin-bottom:14px}
.card h2{margin:0 0 12px;font-size:16px;display:flex;align-items:center;gap:8px}
.card h2 .h-tag{font-size:11px;font-weight:400;color:var(--sub);background:var(--soft);
  padding:2px 8px;border-radius:8px}
.cb{display:flex;flex-wrap:wrap;gap:10px;align-items:center}
.label{font-size:12px;color:var(--sub)}
.chip{font-size:12px;background:var(--soft);color:var(--ink);padding:6px 10px;border-radius:6px;
  border:1px solid var(--line2);font-family:Menlo,Consolas,monospace}
.btn{background:var(--acc);color:#fff;border:0;padding:9px 18px;border-radius:6px;font-size:14px;
  cursor:pointer;font-weight:600}
.btn:hover{background:#1d4fd1}
.btn:disabled{background:#9aaeed;cursor:wait}
.btn.ghost{background:var(--soft);color:var(--ink)}
.btn.ghost:hover{background:#e2e7f2}
.btn.sm{padding:6px 12px;font-size:12.5px;font-weight:500}
.seg{display:inline-flex;border:1px solid var(--line2);border-radius:6px;overflow:hidden}
.seg button{border:0;background:#fff;padding:7px 14px;cursor:pointer;font-size:13px;color:var(--sub)}
.seg button.on{background:var(--acc);color:#fff}
.err{background:#fff5f5;border:1px solid #f5b5b5;color:#c62828;padding:10px 14px;
  border-radius:6px;margin:10px 0;font-size:13px}
.empty{color:var(--sub);padding:20px;text-align:center;font-size:13px}

/* 摘要：权益曲线 + 热力图 */
.eq-wrap{display:flex;gap:16px;flex-wrap:wrap}
.eq-chart{width:100%;height:160px;flex:1 1 460px}
.heat{display:flex;flex-wrap:wrap;gap:3px;align-content:flex-start;flex:1 1 320px}
.heat .cell{width:18px;height:18px;border-radius:3px;cursor:pointer;position:relative;
  font-size:0;transition:transform .1s}
.heat .cell:hover{transform:scale(1.25);z-index:2}
.heat .cell .tip{display:none;position:absolute;bottom:22px;left:50%;transform:translateX(-50%);
  background:#1a1d2e;color:#fff;font-size:11px;padding:3px 6px;border-radius:4px;white-space:nowrap;z-index:5}
.heat .cell:hover .tip{display:block}
.stat-row{display:flex;gap:18px;flex-wrap:wrap;margin-top:10px}
.stat{font-size:12px;color:var(--sub)}
.stat b{font-size:18px;font-family:Menlo,Consolas,monospace;display:block;color:var(--ink)}

/* 轮播 */
.gallery{display:flex;gap:0;overflow-x:auto;scroll-snap-type:x mandatory;
  -webkit-overflow-scrolling:touch;scroll-behavior:smooth;padding-bottom:8px}
.gallery::-webkit-scrollbar{height:8px}
.gallery::-webkit-scrollbar-thumb{background:#cdd3e0;border-radius:4px}
.slide{flex:0 0 100%;scroll-snap-align:center;padding:4px 6px 0}
.slide-inner{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:14px}
.slide-head{display:flex;align-items:center;gap:10px;margin-bottom:10px}
.slide-head .date{font-size:17px;font-weight:700;font-family:Menlo,Consolas,monospace}
.badge{font-size:12px;padding:3px 10px;border-radius:12px;font-weight:600}
.badge.short{background:#ffe3f1;color:#c2185b}
.badge.long{background:#e3fbe9;color:#1b7a3d}
.badge.out{background:#eef0f4;color:#5a6178}
.chart-box{width:100%;height:420px}
.pnl{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-top:12px}
.pnl .z{background:var(--soft);padding:10px 12px;border-radius:6px}
.pnl .z .k{font-size:11px;color:var(--sub);margin-bottom:4px}
.pnl .z .v{font-size:16px;font-weight:700;font-family:Menlo,Consolas,monospace}
.pnl .z .s{font-size:11px;color:var(--sub);margin-top:2px}
.pos{color:var(--up)} .neg{color:var(--dn)}
.timeline{display:flex;gap:6px;flex-wrap:wrap;margin-top:12px}
.ev{font-size:11px;padding:3px 8px;border-radius:10px;background:#f0f3f9;color:var(--sub);
  font-family:Menlo,Consolas,monospace}
.ev .dot{display:inline-block;width:7px;height:7px;border-radius:50%;margin-right:5px;vertical-align:middle}
.drill-bar{margin-top:10px;display:flex;align-items:center;gap:10px}
.drill-bar .note{font-size:12px;color:var(--sub)}
.foot{font-size:12px;color:var(--sub);border-top:1px solid var(--line);padding-top:10px;
  margin-top:10px;line-height:1.7}

/* 控制条 */
.controls{display:flex;align-items:center;gap:16px;flex-wrap:wrap}
.controls input[type=range]{width:200px}
.idx{font-size:12px;color:var(--sub);font-family:Menlo,Consolas,monospace}
.nav-dots{display:flex;gap:6px;flex-wrap:wrap;margin-top:10px}
.nav-dots .dot{width:9px;height:9px;border-radius:50%;background:#cdd3e0;cursor:pointer;transition:.15s}
.nav-dots .dot.on{background:var(--acc);transform:scale(1.3)}
@media (max-width:820px){.pnl{grid-template-columns:repeat(2,1fr)}}
</style>
</head>
<body>
<div class="topnav">
  <a class="tn-home" href="/">📊 quant_review</a>
  <topnav-bar class="topnav-links" data-active="/huntzone-gallery"></topnav-bar>
  <span class="tn-spacer"></span>
  <span class="tn-tag">Binance Futures ·  · 狩猎区画廊</span>
</div>

<div class="wrap">
<div id="app">

  <h1 style="font-size:22px;margin:0 0 8px">狩猎区画廊 · 多日滑动</h1>
  <div style="color:var(--sub);font-size:13px;margin-bottom:14px">
    滑动浏览多个交易日的狩猎区实况：<b>1h K线 + 9 档叠加 + 狩猎区色带 + 方向箭头 + 事件标记</b>。
    方向=顺势（昨收 vs SMA10），S=冻结回归预测（±MAE 低置信度）。严格零未来函数。
  </div>

  <!-- 控制条 -->
  <div class="card">
    <h2>控制 <span class="h-tag">系统自取，零输入</span></h2>
    <div class="controls">
      <span class="chip">品种 </span>
      <button class="btn" @click="loadSlides" :disabled="loading">
        <span v-if="loading">生成中…</span><span v-else>🎯 生成最近有信号日</span>
      </button>
      <div class="cb">
        <span class="label">保本触发</span>
        <input type="range" min="8" max="26" step="1" v-model.number="trigger"
               @change="onTriggerChange">
        <span class="chip">{{ trigger }} 点</span>
      </div>
      <div class="seg">
        <button :class="{on: mode==='be'}" @click="mode='be'">保本(be)</button>
        <button :class="{on: mode==='origin'}" @click="mode='origin'">原始(origin)</button>
      </div>
      <div class="idx" v-if="range">第 {{ current+1 }} / {{ range.slides.length }} 日</div>
    </div>
    <div v-if="err" class="err">⚠ {{ err }}</div>
    <div v-if="range && !range.slides.length" class="warn-row" style="margin-top:10px">
      最近区间内无有信号日（方向均临界 / 数据不足）。
    </div>
  </div>

  <!-- 摘要：权益曲线 + 热力图 -->
  <div class="card" v-if="range && range.slides.length">
    <h2>总览 <span class="h-tag">{{ mode==='be' ? '保本口径' : '原始口径' }} · 共 {{ range.count }} 日（缺失 {{ range.missing_count }}）</span></h2>
    <div class="eq-wrap">
      <div id="eqChart" class="eq-chart"></div>
      <div class="heat">
        <div v-for="(s,i) in range.slides" :key="'h'+s.date" class="cell"
             :style="{background: heatColor(s.total[mode])}"
             @click="scrollTo(i)" :title="s.date">
          <span class="tip">{{ s.date }} · {{ fmt(s.total[mode]) }}</span>
        </div>
      </div>
    </div>
    <div class="stat-row">
      <div class="stat">累计 USD<b :class="cum>=0?'pos':'neg'">{{ fmt(cum) }}</b>{{ mode }} 口径</div>
      <div class="stat">胜率<b>{{ winRate }}%</b>{{ winN }} / {{ range.count }} 日盈利</div>
      <div class="stat">最佳日<b class="pos">{{ bestDate }} {{ fmt(bestVal) }}</b></div>
      <div class="stat">最差日<b class="neg">{{ worstDate }} {{ fmt(worstVal) }}</b></div>
    </div>
  </div>

  <!-- 轮播 -->
  <div class="card" v-if="range && range.slides.length">
    <h2>逐日狩猎区 <span class="h-tag">← → 键 / ◀▶ / 圆点切换</span></h2>
    <div class="gallery" ref="gallery" @scroll.passive="onScroll">
      <div class="slide" v-for="(s,i) in range.slides" :key="s.date">
        <div class="slide-inner">
          <div class="slide-head">
            <span class="date">{{ s.date }}</span>
            <span class="badge" :class="s.direction">{{ s.direction_cn }}</span>
            <span class="badge out">{{ s.outcome }}</span>
            <span class="idx" v-if="s.special_gap">跳空特殊日</span>
            <span class="idx" style="margin-left:auto">{{ s.source }}</span>
          </div>
          <div :id="'chart-'+s.date" class="chart-box"></div>
          <div class="pnl">
            <div class="z"><div class="k">zone_a</div>
              <div class="v" :class="pnlClass(s.zones_pnl.zone_a[mode])">{{ fmt(s.zones_pnl.zone_a[mode]) }}</div>
              <div class="s">入场 {{ fmt(s.zone_lo) }}~{{ fmt(s.zone_hi) }}</div></div>
            <div class="z"><div class="k">zone_mid</div>
              <div class="v" :class="pnlClass(s.zones_pnl.zone_mid[mode])">{{ fmt(s.zones_pnl.zone_mid[mode]) }}</div>
              <div class="s">区中 {{ fmt(s.zone_mid) }}</div></div>
            <div class="z"><div class="k">zone_b</div>
              <div class="v" :class="pnlClass(s.zones_pnl.zone_b[mode])">{{ fmt(s.zones_pnl.zone_b[mode]) }}</div>
              <div class="s">止损 {{ fmt(s.stop) }}</div></div>
            <div class="z"><div class="k">合计（3区）</div>
              <div class="v" :class="pnlClass(s.total[mode])">{{ fmt(s.total[mode]) }}</div>
              <div class="s">衰竭① {{ fmt(s.exh1) }}</div></div>
          </div>
          <div class="timeline">
            <span v-for="e in s.events" :key="e.ts_ms" class="ev">
              <span class="dot" :style="{background: evColor(e.type)}"></span>{{ e.time }} {{ evLabel(e) }}
            </span>
            <span v-if="!s.events.length" class="ev">无事件</span>
          </div>
          <div class="drill-bar">
            <button class="btn ghost sm" @click="toggleDrill(s)"
                    :disabled="drill[s.date] && drill[s.date].loading">
              {{ drilled(s) ? '收起 1m' : '看 1m 细部' }}
            </button>
            <span class="note" v-if="drill[s.date] && drill[s.date].loading">加载 1m…</span>
            <span class="note" v-if="drill[s.date] && drill[s.date].error">{{ drill[s.date].error }}</span>
            <span class="note" v-if="drilled(s)">已切换至 1m 粒度（事件标记对齐至分钟）</span>
          </div>
          <div class="foot">
            <span style="color:var(--green-z)">■ 绿带=做多狩猎区</span> ｜
            <span style="color:var(--pink-z)">■ 粉带=做空狩猎区</span> ｜
            9 档：0/19.1/38.2/50/61.8/80.9/100/161.8/261.8 ｜ 目标①=昨收 ｜ 跨度 S±MAE {{ fmt(s.S_mae) }}
          </div>
        </div>
      </div>
    </div>
    <div class="nav-dots">
      <span v-for="(s,i) in range.slides" :key="'d'+s.date" class="dot"
            :class="{on: i===current}" @click="scrollTo(i)"></span>
    </div>
    <div class="cb" style="margin-top:10px">
      <button class="btn ghost sm" @click="goPrev">◀ 上一日</button>
      <button class="btn ghost sm" @click="goNext">下一日 ▶</button>
    </div>
  </div>

  <div v-if="!range && !err" class="empty">点击「🎯 生成最近有信号日」开始</div>
</div>
</div>

<script src="/static/components/topnav.js" defer></script>
<script>
(function () {
  var SLIDES_API = '/api/huntzone-gallery/slides';
  var DAY_API = '/api/huntzone-gallery/day';

  function fmt(v) {
    if (v === null || v === undefined || isNaN(v)) return '—';
    var n = Number(v);
    return (n >= 0 ? '+' : '') + n.toFixed(1);
  }

  // 档位线样式（9 档 + 关键档）
  function lineStyleFor(ratio) {
    r = Math.round(Number(ratio) * 1000) / 1000;
    if (r === 0) return { color: '#888780', type: 'dashed', width: 1 };
    if (r === 0.191) return { color: '#A32D2D', type: 'solid', width: 1.5 };
    if (r === 0.382 || r === 0.5 || r === 0.618) return { color: '#BA7517', type: 'solid', width: 1.2 };
    if (r === 0.809) return { color: '#BA7517', type: 'dashed', width: 1 };
    if (r === 1) return { color: '#185FA5', type: 'solid', width: 1.5 };
    if (r === 1.618 || r === 2.618) return { color: '#0F6E56', type: 'solid', width: 1.2 };
    return { color: '#B4B2A9', type: 'dashed', width: 0.8 };
  }

  function evColor(type) {
    if (type === 'stop') return '#e53935';
    if (type === 'tp1' || type === 'tp2') return '#2ecc71';
    if (type === 'fill') return '#2962ff';
    if (type === 'be_arm' || type === 'be_out') return '#ff9800';
    if (type === 'force22' || type === 'force_sl2') return '#7e57c2';
    return '#5a6178';
  }
  function evLabel(e) {
    var m = { fill:'成交', tp1:'TP1', tp2:'TP2', stop:'止损', be_arm:'保本激活',
              be_out:'保本出场', force22:'收盘强平', force_sl2:'双止损强平' };
    return (m[e.type] || e.type) + ' ' + e.zone + ' ' + fmt(e.price);
  }

  function indexForTs(candles, ts, interval) {
    for (var i = 0; i < candles.length; i++) {
      if (candles[i][0] <= ts && ts < candles[i][0] + interval) return i;
    }
    var best = 0, bd = 1e18;
    for (var j = 0; j < candles.length; j++) {
      var d = Math.abs(candles[j][0] - ts);
      if (d < bd) { bd = d; best = j; }
    }
    return best;
  }

  function fmtTs(ms) {
    var dt = new Date(ms);
    function p(n){ return (n < 10 ? '0' : '') + n; }
    return p(dt.getUTCMonth()+1) + '-' + p(dt.getUTCDate()) + ' ' + p(dt.getUTCHours());
  }

  var app = Vue.createApp({
    data: function () {
      return {
        range: null,
        trigger: 20,
        mode: 'be',
        current: 0,
        loading: false,
        err: '',
        charts: {},   // date -> echarts instance
        drill: {},    // date -> {open, loading, error, candles_1m}
        eqChart: null
      };
    },
    mounted: function () {
      this.loadSlides();
      window.addEventListener('keydown', this.onKey);
    },
    beforeUnmount: function () {
      window.removeEventListener('keydown', this.onKey);
    },
    computed: {
      cum: function () {
        if (!this.range) return 0;
        var m = this.mode, s = 0;
        this.range.slides.forEach(function (sl) { s += Number(sl.total[m]) || 0; });
        return Math.round(s * 10) / 10;
      },
      winN: function () {
        if (!this.range) return 0;
        var m = this.mode, n = 0;
        this.range.slides.forEach(function (sl) { if ((Number(sl.total[m]) || 0) > 0) n++; });
        return n;
      },
      winRate: function () {
        if (!this.range || !this.range.count) return 0;
        return Math.round(this.winN / this.range.count * 100);
      },
      bestDate: function () {
        if (!this.range) return '—';
        var m = this.mode, b = null;
        this.range.slides.forEach(function (sl) {
          var v = Number(sl.total[m]) || 0;
          if (b === null || v > b.v) b = { v: v, d: sl.date };
        });
        return b ? b.d : '—';
      },
      bestVal: function () {
        if (!this.range) return 0;
        var m = this.mode, b = null;
        this.range.slides.forEach(function (sl) {
          var v = Number(sl.total[m]) || 0;
          if (b === null || v > b.v) b = v;
        });
        return b || 0;
      },
      worstDate: function () {
        if (!this.range) return '—';
        var m = this.mode, w = null;
        this.range.slides.forEach(function (sl) {
          var v = Number(sl.total[m]) || 0;
          if (w === null || v < w.v) w = { v: v, d: sl.date };
        });
        return w ? w.d : '—';
      },
      worstVal: function () {
        if (!this.range) return 0;
        var m = this.mode, w = null;
        this.range.slides.forEach(function (sl) {
          var v = Number(sl.total[m]) || 0;
          if (w === null || v < w.v) w = v;
        });
        return w || 0;
      }
    },
    methods: {
      fmt: fmt,
      pnlClass: function (v) { return (Number(v) || 0) >= 0 ? 'pos' : 'neg'; },
      evColor: evColor,
      evLabel: evLabel,
      heatColor: function (v) {
        var n = Number(v) || 0, a = Math.min(0.85, Math.abs(n) / 60);
        return n >= 0 ? ('rgba(229,57,53,' + a.toFixed(2) + ')')
                      : ('rgba(46,204,113,' + a.toFixed(2) + ')');
      },
      onKey: function (e) {
        if (!this.range || !this.range.slides.length) return;
        if (e.key === 'ArrowRight') this.goNext();
        else if (e.key === 'ArrowLeft') this.goPrev();
      },
      loadSlides: function () {
        var self = this;
        self.loading = true; self.err = '';
        Object.keys(self.charts).forEach(function (d) {
          try { self.charts[d].dispose(); } catch (e) {}
          delete self.charts[d];
        });
        fetch(SLIDES_API + '?trigger=' + self.trigger, { cache: 'no-store' })
          .then(function (r) { return r.json(); })
          .then(function (d) {
            if (!d || d.error) { self.err = (d && d.error) || '接口返回异常'; self.range = null; return; }
            if (d.code === 502) { self.err = d.error; self.range = null; return; }
            self.range = d; self.current = 0; self.mode = 'be';
            self.drill = {};
            self.$nextTick(function () {
              self.renderEq();
              self.scrollTo(0);
              self.renderVisible();
            });
          })
          .catch(function (e) { self.err = '请求失败：' + e; self.range = null; })
          .then(function () { self.loading = false; });
      },
      onTriggerChange: function () { this.loadSlides(); },
      onScroll: function () {
        var self = this;
        if (!self.$refs.gallery || !self.range) return;
        var w = self.$refs.gallery.clientWidth;
        var idx = Math.round(self.$refs.gallery.scrollLeft / w);
        idx = Math.max(0, Math.min(idx, self.range.slides.length - 1));
        if (idx !== self.current) { self.current = idx; }
        self.renderVisible();
      },
      scrollTo: function (i) {
        var self = this;
        if (!self.$refs.gallery || !self.range) return;
        i = Math.max(0, Math.min(i, self.range.slides.length - 1));
        var w = self.$refs.gallery.clientWidth;
        self.$refs.gallery.scrollTo({ left: i * w, behavior: 'smooth' });
        self.current = i;
        self.renderVisible();
      },
      goPrev: function () { this.scrollTo(this.current - 1); },
      goNext: function () { this.scrollTo(this.current + 1); },
      renderVisible: function () {
        if (!this.range) return;
        var self = this;
        this.range.slides.forEach(function (s, i) {
          if (Math.abs(i - self.current) <= 1) self.renderChart(s);
          else if (self.charts[s.date]) {
            try { self.charts[s.date].dispose(); } catch (e) {}
            delete self.charts[s.date];
          }
        });
      },
      renderChart: function (s) {
        var self = this;
        var dom = document.getElementById('chart-' + s.date);
        if (!dom) return;
        var is1m = !!(self.drill[s.date] && self.drill[s.date].candles_1m);
        var candles = is1m ? self.drill[s.date].candles_1m : s.candles_1h;
        if (!candles || !candles.length) return;
        if (self.charts[s.date]) {
          try { self.charts[s.date].dispose(); } catch (e) {}
          delete self.charts[s.date];
        }
        var chart = echarts.init(dom, null, { renderer: 'canvas' });
        self.charts[s.date] = chart;
        var interval = is1m ? 60000 : 3600000;
        var labels = candles.map(function (c) { return fmtTs(c[0]); });
        var cdata = candles.map(function (c) { return [c[1], c[4], c[3], c[2]]; });

        var ml = [];
        s.levels.forEach(function (l) {
          var st = lineStyleFor(l.ratio);
          ml.push({
            yAxis: l.price, name: l.name,
            lineStyle: { color: st.color, type: st.type, width: st.width },
            label: { show: false }
          });
        });
        [['止损', s.stop], ['衰竭①', s.exh1], ['衰竭②', s.exh2]].forEach(function (p) {
          if (p[1] == null) return;
          var r = p[1] === s.stop ? 0.191 : (p[1] === s.exh1 ? 1.618 : 2.618);
          var st = lineStyleFor(r);
          ml.push({ yAxis: p[1], name: p[0],
            lineStyle: { color: st.color, type: st.type, width: st.width },
            label: { show: true, position: 'end', formatter: p[0],
              color: st.color, fontSize: 10 } });
        });
        if (s.t1 != null) {
          ml.push({ yAxis: s.t1, name: '目标①',
            lineStyle: { color: '#0F6E56', type: 'dashed', width: 1.4 },
            label: { show: true, position: 'end', formatter: '目标①',
              color: '#0F6E56', fontSize: 10 } });
        }

        var mp = [];
        s.events.forEach(function (e) {
          var idx = indexForTs(candles, e.ts_ms, interval);
          mp.push({
            coord: [idx, e.price],
            symbol: (e.type === 'stop') ? 'circle' : (e.type === 'fill' ? 'circle' : 'pin'),
            symbolSize: e.type === 'stop' ? 11 : 13,
            itemStyle: { color: evColor(e.type) },
            label: { show: true, formatter: evLabel(e).split(' ')[0],
              position: 'top', color: '#fff', fontSize: 9,
              backgroundColor: evColor(e.type), padding: [1,3], borderRadius: 2 }
          });
        });
        // 方向箭头（首根 bar 的 open 价）
        if (candles.length) {
          mp.push({
            coord: [0, s.open_px],
            symbol: s.direction === 'long' ? 'triangle' : 'triangle',
            symbolRotate: s.direction === 'long' ? 0 : 180,
            symbolSize: 18,
            itemStyle: { color: s.direction === 'long' ? '#1b7a3d' : '#c2185b' },
            label: { show: true, formatter: s.direction_cn, position: 'right',
              color: s.direction === 'long' ? '#1b7a3d' : '#c2185b', fontSize: 11, fontWeight: 'bold' }
          });
        }

        var zoneColor = s.direction === 'long' ? 'rgba(46,204,113,0.10)' : 'rgba(255,111,174,0.12)';
        chart.setOption({
          backgroundColor: '#fff',
          grid: { left: 62, right: 16, top: 18, bottom: 28 },
          tooltip: { trigger: 'axis', axisPointer: { type: 'cross' } },
          xAxis: { type: 'category', data: labels, boundaryGap: true,
            axisLabel: { fontSize: 9, color: '#5a6178', interval: Math.ceil(labels.length/12) },
            axisLine: { lineStyle: { color: '#d9dde7' } } },
          yAxis: { scale: true, type: 'value',
            axisLabel: { fontSize: 9, color: '#5a6178' },
            splitLine: { lineStyle: { color: '#eef0f4' } } },
          series: [{
            type: 'candlestick', name: '', data: cdata,
            itemStyle: { color: '#e53935', color0: '#2ecc71',
              borderColor: '#e53935', borderColor0: '#2ecc71' },
            markLine: { symbol: 'none', silent: true, data: ml },
            markArea: { silent: true, itemStyle: { color: zoneColor },
              data: [[{ yAxis: s.zone_lo }, { yAxis: s.zone_hi }]] },
            markPoint: { data: mp }
          }]
        }, true);
      },
      renderEq: function () {
        var self = this;
        var dom = document.getElementById('eqChart');
        if (!dom || !self.range) return;
        if (!self.eqChart) self.eqChart = echarts.init(dom, null, { renderer: 'canvas' });
        var m = self.mode;
        var xs = [], ys = [], cum = 0;
        self.range.slides.forEach(function (sl) {
          xs.push(sl.date.slice(5));
          cum += Number(sl.total[m]) || 0;
          ys.push(Math.round(cum * 10) / 10);
        });
        self.eqChart.setOption({
          backgroundColor: '#fff',
          grid: { left: 44, right: 12, top: 14, bottom: 24 },
          tooltip: { trigger: 'axis' },
          xAxis: { type: 'category', data: xs, axisLabel: { fontSize: 9, color: '#5a6178' },
            axisLine: { lineStyle: { color: '#d9dde7' } } },
          yAxis: { type: 'value', axisLabel: { fontSize: 9, color: '#5a6178' },
            splitLine: { lineStyle: { color: '#eef0f4' } } },
          series: [{ type: 'line', data: ys, smooth: true, symbol: 'circle', symbolSize: 5,
            lineStyle: { color: '#2962ff', width: 2 },
            areaStyle: { color: 'rgba(41,98,255,0.10)' },
            itemStyle: { color: '#2962ff' } }]
        }, true);
      },
      drilled: function (s) {
        return !!(this.drill[s.date] && this.drill[s.date].candles_1m);
      },
      toggleDrill: function (s) {
        var self = this;
        if (self.drilled(s)) {
          delete self.drill[s.date].candles_1m;
          self.$nextTick(function () { self.renderChart(s); });
          return;
        }
        this.$set(this.drill, s.date, { open: false, loading: true, error: '', candles_1m: null });
        fetch(DAY_API + '?date=' + s.date + '&trigger=' + self.trigger, { cache: 'no-store' })
          .then(function (r) { return r.json(); })
          .then(function (d) {
            if (!d || d.error || d.missing) {
              self.drill[s.date].error = d && d.error ? d.error : '1m 数据缺失';
              self.drill[s.date].loading = false; return;
            }
            self.drill[s.date].candles_1m = d.candles_1m || [];
            self.drill[s.date].loading = false;
            self.$nextTick(function () { self.renderChart(s); });
          })
          .catch(function (e) {
            self.drill[s.date].error = '请求失败：' + e;
            self.drill[s.date].loading = false;
          });
      }
    },
    watch: {
      mode: function () { this.renderEq(); }
    }
  });
  app.mount('#app');
})();
</script>
</body>
</html>
"""
