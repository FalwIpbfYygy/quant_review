# -*- coding: utf-8 -*-
"""狩猎区 v2 · /huntv2 页面 HTML 模板常量

为什么内联成常量而不是独立 .html：
   仓库里的独立 .html 曾被同步 / Notion 工具循环覆写导致白屏（见 wuyuan_template.py 头部）。
   因此关键页面一律走 .py 常量。

数据契约：严格对齐 /api/huntv2/ladder 的真实返回体（build 正解几何 + S_MODEL_FROZEN 冻结回归）。
  成功 → ok / direction_cn / open_px / S / S_mae / R / zone_* / stop / exh1 / exh2 / t1 /
         prev_close / special_gap / base / base_kind / levels[]{ratio,name,price,role,dist_pt,dist_bp}
         / live{px,note} / note / disclaimer
  无信号 → ok:False + reason
  取数失败 → 502 + error

纪律：
   本页系统自取日线、顺势方向、冻结回归 S、build 正解几何，**零人工输入**。
   取数失败明确报错，绝不猜 S。现价为 fapi 期货参考价，与官方现货存在基差，仅显示距离。
   S 为低置信度预测（±LOO MAE ≈ 21.95 点），档位按区间使用——警示面板强制展示。
"""

HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta http-equiv="Cache-Control" content="no-store, no-cache, must-revalidate">
<meta http-equiv="Pragma" content="no-cache">
<meta http-equiv="Expires" content="0">
<title>狩猎区 v2 · 档位图</title>
<link rel="stylesheet" href="/static/components/topnav.css">
<script src="/vendors/vue.global.prod.js"></script>
<script src="/vendors/echarts.min.js"></script>
<style>
:root{
  --bg:#f6f7fb; --card:#fff; --ink:#1a1d2e; --sub:#5a6178; --acc:#2962ff;
  --up:#e53935; --dn:#2ecc71; --warn:#ff9800; --line:#eef0f4;
  --line2:#d9dde7; --soft:#f0f3f9;
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
.cb .label{font-size:12px;color:var(--sub);margin-right:2px}
.chip{font-size:12px;background:var(--soft);color:var(--ink);padding:6px 10px;border-radius:6px;
  border:1px solid var(--line2);font-family:Menlo,Consolas,monospace}
.btn{background:var(--acc);color:#fff;border:0;padding:9px 18px;border-radius:6px;font-size:14px;
  cursor:pointer;font-weight:600}
.btn:hover{background:#1d4fd1}
.btn:disabled{background:#9aaeed;cursor:wait}
.btn.ghost{background:var(--soft);color:var(--ink)}
.btn.ghost:hover{background:#e2e7f2}
.btn.sm{padding:6px 12px;font-size:12.5px;font-weight:500}
.err{background:#fff5f5;border:1px solid #f5b5b5;color:#c62828;padding:10px 14px;
  border-radius:6px;margin:10px 0;font-size:13px}
.warn-row{background:#fff8e1;border:1px solid #ffe082;padding:8px 12px;border-radius:6px;
  margin-bottom:8px;font-size:13px;line-height:1.6}
.warn-row.bad{background:#fdecea;border-color:#f5b5b5;color:#c62828}
.warn-row.blue{background:#eaf2ff;border-color:#bcd4f7;color:#0c447c}
.sum{display:grid;grid-template-columns:repeat(5,1fr);gap:10px}
.sum .tile{background:var(--soft);padding:10px 12px;border-radius:6px}
.sum .tile .k{font-size:11px;color:var(--sub);margin-bottom:4px}
.sum .tile .v{font-size:18px;font-weight:700;font-family:Menlo,Consolas,monospace}
.sum .tile .s{font-size:11px;color:var(--sub);margin-top:2px}
table{width:100%;border-collapse:collapse;font-size:13px}
table th,table td{padding:7px 10px;border-bottom:1px solid var(--line);text-align:right}
table th{background:var(--soft);color:var(--sub);font-weight:600;font-size:12px}
table th:first-child,table td:first-child,
table th:last-child,table td:last-child{text-align:left}
td.mono{font-family:Menlo,Consolas,monospace}
tr.key-st td{background:#fdf3f3}
tr.key-hi td{background:#fffaf0}
tr.key-t1 td{background:#f4f9ec}
tr.key-live td{background:#f0f7ff}
tr.key-void td{background:#f7f7f7;color:#6e6e73}
.foot{font-size:12px;color:var(--sub);border-top:1px solid var(--line);padding-top:10px;
  margin-top:10px;line-height:1.7}
.empty{color:var(--sub);padding:20px;text-align:center;font-size:13px}
.chart-box{width:100%;height:540px}
@media (max-width:820px){.sum{grid-template-columns:repeat(2,1fr)}}
</style>
</head>
<body>
<div class="topnav">
  <a class="tn-home" href="/">📊 quant_review</a>
  <topnav-bar class="topnav-links" data-active="/huntv2"></topnav-bar>
  <span class="tn-spacer"></span>
  <span class="tn-tag">Binance Futures · </span>
</div>

<div class="wrap">
<div id="app">

  <h1 style="font-size:22px;margin:0 0 8px">狩猎区 v2 · 档位图</h1>
  <div style="color:var(--sub);font-size:13px;margin-bottom:14px">
    口径：<b>100.0 档 = 当日开盘价</b> ｜ 狩猎区 = 38.2 ~ 61.8 档 ｜ 止损 = 19.1 档 ｜
    第一目标 = 昨收 ｜ 衰竭目标 = 161.8 / 261.8 档 ｜
    方向 = 顺势（昨收 vs SMA10）｜ S = 冻结回归预测
  </div>

  <!-- ① 强制警示面板（始终可见） -->
  <div class="card">
    <h2>① 算法说明与免责 <span class="h-tag">强制展示，不可隐去</span></h2>
    <div class="warn-row blue">
      <b>档位几何可信</b>：比例档位（0/19.1/38.2/50/61.8/80.9/100/161.8/261.8/423.6）为官方已确证结构，
      由「开盘价 + 跨度 S + 方向」正解得出。
    </div>
    <div class="warn-row">
      <b>⚠ S 低置信度</b>：跨度 S 无法被官方中枢回归层精确推导，本页用 17 张历史卡冻结回归系数预测，
      留一法 MAE ≈ 21.95 点（占 S 中位数约 32%）。S 应按 <b>±MAE 区间</b>使用，不是精确点。
    </div>
    <div class="warn-row">
      <b>⚠ 基差提示</b>：现价为 fapi  <b>期货参考价</b>，与官方现货口径存在基差（实测 −98 ~ +24 点），
      仅用于显示"距档位多少 bp"，<b>不参与档位计算</b>。
    </div>
  </div>

  <!-- ② 控制 + 生成 -->
  <div class="card">
    <h2>② 今日狩猎区 <span class="h-tag">系统自取日线，零输入</span></h2>
    <div class="cb">
      <span class="chip">品种 </span>
      <button class="btn" @click="loadLadder" :disabled="busy">
        <span v-if="busy">生成中…</span><span v-else>🎯 生成今日狩猎区</span>
      </button>
      <button class="btn ghost sm" @click="refreshLive" :disabled="busy"
              style="margin-left:auto">刷新现价</button>
    </div>
    <div v-if="err" class="err">⚠ {{ err }}</div>
    <div v-if="res && !res.ok && res.reason" class="warn-row">{{ res.reason }}</div>
    <div v-if="res && res.mode === 'self_sufficient'" class="warn-row">
      引擎：{{ res.engine }} ｜ 数据源：{{ res.source }} ｜
      特征：前日实体 {{ res.body1 }} / 前日收盘位置 {{ res.pos1 }}
    </div>
  </div>

  <!-- ③ 摘要 -->
  <template v-if="res && res.ok">
    <div class="card">
      <h2>③ 摘要 <span class="h-tag">{{ res.direction_cn }}</span></h2>
      <div class="sum">
        <div class="tile"><div class="k">方向</div><div class="v">{{ res.direction_cn }}</div>
          <div class="s">顺势（昨收 vs SMA10）</div></div>
        <div class="tile"><div class="k">开盘价 = 100.0 档</div>
          <div class="v">{{ f2(res.open_px) }}</div><div class="s">官方口径</div></div>
        <div class="tile"><div class="k">跨度 S ±MAE</div><div class="v">{{ f2(res.S) }}</div>
          <div class="s">±{{ f2(res.S_mae) }} 点（低置信度）</div></div>
        <div class="tile"><div class="k">R = 止损距离</div><div class="v">{{ f2(res.R) }}</div>
          <div class="s">0.191 × S</div></div>
        <div class="tile"><div class="k">狩猎区宽</div><div class="v">{{ f2(res.zone_width) }}</div>
          <div class="s">{{ f2(res.zone_lo) }} ~ {{ f2(res.zone_hi) }}</div></div>
      </div>
      <div v-if="res.special_gap" class="warn-row bad" style="margin-top:10px">
        <b>跳空特殊日：</b>衰竭① {{ f2(res.exh1) }} 与昨收 {{ f2(res.prev_close) }} 错侧
        ⇒ 不减仓博弈，直接到衰竭位走平。
      </div>
    </div>

    <!-- ④ 1h K线 + 全档位叠加 -->
    <div class="card">
      <h2>④ 1h K线 + 档位叠加 <span class="h-tag">橙=狩猎区 青=止损/目标 蓝=开盘/现价</span></h2>
      <div id="chart" class="chart-box"></div>
      <div class="foot">
        <span style="color:#BA7517">橙实线 = 狩猎区 / 开盘锚</span> ｜
        <span style="color:#A32D2D">红 = 止损(19.1)</span> ｜
        <span style="color:#0F6E56">绿 = 目标①(昨收) / 衰竭</span> ｜
        <span style="color:#185FA5">蓝 = 开盘价 / 现价</span>
      </div>
    </div>

    <!-- ⑤ 档位表 -->
    <div class="card">
      <h2>⑤ 档位表 <span class="h-tag">距离基准：{{ baseLabel }}</span></h2>
      <table>
        <thead><tr>
          <th>档位</th><th>价格</th><th>角色</th>
          <th>距基准(点)</th><th>距基准(bp)</th><th style="text-align:left">相对基准</th>
        </tr></thead>
        <tbody>
          <tr v-for="l in res.levels" :key="l.name" :class="rowClass(l)">
            <td>{{ l.name }}</td>
            <td class="mono">{{ f2(l.price) }}</td>
            <td>{{ l.role || '—' }}</td>
            <td class="mono">{{ sign(l.dist_pt) }}</td>
            <td class="mono">{{ l.dist_bp == null ? '—' : sign(l.dist_bp, 1) }}</td>
            <td>{{ l.dist_pt >= 0 ? '上方' : '下方' }} {{ f2(Math.abs(l.dist_pt)) }} 点</td>
          </tr>
        </tbody>
      </table>
      <div class="foot">
        目标 / 风险（以<span class="mono">区中 {{ f2(res.zone_mid) }}</span> 为入场参考）：
        <b>到昨收 {{ rrText(res.t1) }}</b> ｜
        <b>到衰竭① {{ rrText(res.exh1) }}</b> ｜
        <b>到衰竭② {{ rrText(res.exh2) }}</b>
        （数值 = 距离 ÷ R，R = {{ f2(res.R) }}）
      </div>
      <div class="foot">
        {{ res.note }}<br>{{ res.disclaimer }}
      </div>
    </div>
  </template>

  <div v-if="!res && !err" class="empty">点击「🎯 生成今日狩猎区」开始</div>
</div>
</div>

<script src="/static/components/topnav.js" defer></script>
<script>
(function () {
  var LADDER_API = '/api/huntv2/ladder';
  var KLINE_API = '/api/realtime/klines';

  function num(v) {
    if (v === null || v === undefined || v === '') return null;
    var n = parseFloat(String(v).replace(/[^0-9.\-]/g, ''));
    return isNaN(n) ? null : n;
  }

  function lineStyleFor(item) {
    var r = item.ratio;
    if (r === null) return { color: '#0F6E56', type: 'dashed', width: 1.4 }; // 目标①
    r = Math.round(r * 1000) / 1000;
    if (r === 0) return { color: '#888780', type: 'dashed', width: 1 };
    if (r === 0.191) return { color: '#A32D2D', type: 'solid', width: 1.5 };
    if (r === 0.382 || r === 0.5 || r === 0.618) return { color: '#BA7517', type: 'solid', width: 1.2 };
    if (r === 1) return { color: '#185FA5', type: 'solid', width: 1.5 };
    if (r === 1.618 || r === 2.618) return { color: '#0F6E56', type: 'solid', width: 1.2 };
    return { color: '#B4B2A9', type: 'dashed', width: 0.8 };
  }

  var app = Vue.createApp({
    data: function () {
      return {
        res: null,
        busy: false,
        err: '',
        kData: [],   // [ts, o, h, l, c]
        chart: null
      };
    },
    computed: {
      baseLabel: function () {
        if (!this.res) return '—';
        return this.res.base_kind === 'live'
          ? ('现价 ' + this.f2(this.res.base) + '（期货参考价）')
          : ('狩猎区中值 ' + this.f2(this.res.base));
      }
    },
    mounted: function () {
      this.loadLadder();
    },
    methods: {
      f2: function (v) {
        return (v === null || v === undefined || isNaN(v)) ? '—' : Number(v).toFixed(2);
      },
      sign: function (v, dp) {
        if (v === null || v === undefined || isNaN(v)) return '—';
        var n = Number(v);
        return (n >= 0 ? '+' : '') + n.toFixed(dp === undefined ? 2 : dp);
      },
      rowClass: function (l) {
        if (l.ratio === null) return 'key-t1';   // 目标①（昨收）
        var r = Math.round(Number(l.ratio) * 1000) / 1000;
        if (r === 0) return 'key-void';
        if (r === 0.191) return 'key-st';
        if (r === 0.382 || r === 0.5 || r === 0.618) return 'key-hi';
        if (r === 1.618 || r === 2.618) return 'key-t1';
        return '';
      },
      rrText: function (tgt) {
        if (!this.res || tgt === null || tgt === undefined) return '—';
        var R = Number(this.res.R);
        if (!R) return '—';
        var d = Math.abs(Number(this.res.zone_mid) - Number(tgt));
        return d.toFixed(2) + ' 点 = ' + (d / R).toFixed(2) + 'R';
      },

      loadLadder: function () {
        var self = this;
        self.busy = true;
        self.err = '';
        fetch(LADDER_API + '?live=1', { cache: 'no-store' })
          .then(function (r) { return r.json(); })
          .then(function (d) {
            if (!d || d.code !== 200) {
              self.err = (d && d.error) ? d.error
                : ('接口返回异常 (code=' + (d && d.code) + ')');
              self.res = (d && d.ok === false) ? d : null;
              return;
            }
            self.res = d;
            self.loadKlines();
          })
          .catch(function (e) {
            self.err = '请求失败：' + e;
            self.res = null;
            console.error('[huntv2] ladder failed', e);
          })
          .then(function () { self.busy = false; });
      },

      refreshLive: function () {
        // 重新拉档位（档位不变，只更新现价与距离列 + 重画图表现价线）
        this.loadLadder();
      },

      loadKlines: function () {
        var self = this;
        fetch(KLINE_API + '?symbol=&interval=1h&limit=200', { cache: 'no-store' })
          .then(function (r) { return r.json(); })
          .then(function (d) {
            if (!d || d.code !== 200 || !d.data) {
              console.error('[huntv2] klines failed', d);
              return;
            }
            self.kData = d.data.map(function (r) {
              return [Number(r[0]), Number(r[1]), Number(r[2]), Number(r[3]), Number(r[4])];
            });
            self.renderChart();
          })
          .catch(function (e) {
            console.error('[huntv2] klines failed', e);
          });
      },

      buildMarkLines: function () {
        var self = this;
        var data = [];
        (self.res.levels || []).forEach(function (l) {
          var st = lineStyleFor(l);
          data.push({
            yAxis: Number(l.price),
            name: l.name,
            lineStyle: { color: st.color, type: st.type, width: st.width },
            label: {
              show: true, position: 'insideStartTop',
              formatter: l.name + ' ' + Number(l.price).toFixed(1),
              color: '#fff', backgroundColor: st.color,
              padding: [2, 4], fontSize: 10, borderRadius: 2
            }
          });
        });
        if (self.res.t1 !== null && self.res.t1 !== undefined) {
          var t1 = Number(self.res.t1);
          data.push({
            yAxis: t1, name: '目标①',
            lineStyle: { color: '#0F6E56', type: 'dashed', width: 1.4 },
            label: { show: true, position: 'insideStartTop',
              formatter: '目标① ' + t1.toFixed(1), color: '#fff',
              backgroundColor: '#0F6E56', padding: [2, 4], fontSize: 10, borderRadius: 2 }
          });
        }
        if (self.res.live && self.res.live.px !== null && self.res.live.px !== undefined) {
          var px = Number(self.res.live.px);
          data.push({
            yAxis: px, name: '现价',
            lineStyle: { color: '#185FA5', type: 'solid', width: 2 },
            label: { show: true, position: 'insideStartTop',
              formatter: '现价 ' + px.toFixed(1), color: '#fff',
              backgroundColor: '#185FA5', padding: [2, 4], fontSize: 10, borderRadius: 2 }
          });
        }
        return data;
      },

      renderChart: function () {
        var self = this;
        if (!self.kData.length) return;
        var dom = document.getElementById('chart');
        if (!dom) return;
        if (!self.chart) {
          self.chart = echarts.init(dom, null, { renderer: 'canvas' });
        }
        var dates = self.kData.map(function (r) {
          var dt = new Date(r[0]);
          function p(n){ return (n < 10 ? '0' : '') + n; }
          return p(dt.getMonth() + 1) + '-' + p(dt.getDate()) + ' ' + p(dt.getHours());
        });
        var candle = self.kData.map(function (r) {
          return [r[1], r[4], r[3], r[2]]; // o,c,l,h
        });
        self.chart.setOption({
          backgroundColor: '#fff',
          grid: { left: 60, right: 20, top: 20, bottom: 50 },
          tooltip: { trigger: 'axis', axisPointer: { type: 'cross' } },
          xAxis: {
            type: 'category', data: dates, boundaryGap: true,
            axisLabel: { fontSize: 10, color: '#5a6178' },
            axisLine: { lineStyle: { color: '#d9dde7' } }
          },
          yAxis: {
            scale: true, type: 'value',
            axisLabel: { fontSize: 10, color: '#5a6178' },
            splitLine: { lineStyle: { color: '#eef0f4' } }
          },
          dataZoom: [
            { type: 'inside', start: 60, end: 100 },
            { type: 'slider', start: 60, end: 100, height: 18, bottom: 18 }
          ],
          series: [{
            type: 'candlestick', name: ' 1h', data: candle,
            itemStyle: {
              color: '#e53935', color0: '#2ecc71',
              borderColor: '#e53935', borderColor0: '#2ecc71'
            },
            markLine: {
              symbol: 'none', silent: true,
              data: self.buildMarkLines()
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
