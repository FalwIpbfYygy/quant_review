# -*- coding: utf-8 -*-
"""乌圆狩猎区 · /wuyuan 页面 HTML 模板常量

为什么要内联成常量而不是独立 .html：
   仓库里的独立 .html 曾被同步 / Notion 工具循环覆写导致白屏（见 AGENTS.md 第 5 节坑 #2）。
   因此关键页面一律走 .py 常量。

数据契约：字段严格对齐 /api/wuyuan/ladder 的真实返回。
  档位表模式 → levels / zone_* / stop / exh1 / exh2 / t1 / invalid_line / live / position
  auto_leg 模式 → 上述 + auto{rule,lookback,r_bp,cost_floor_bp,tradable,trade_note,verdict}
                        + auto_warnings[]

纪律：本页**只有自研腿一个入口** —— 系统自己取日线算腿、判方向、出档位。
      他未公开的四线 / 单档 / 反推 S 等人工输入路径**已全部移除**。
      取数失败明确报错，**绝不猜一个 S 出来**。
      现价为 fapi 期货参考价，与官方现货存在基差。
"""

HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta http-equiv="Cache-Control" content="no-store, no-cache, must-revalidate">
<meta http-equiv="Pragma" content="no-cache">
<meta http-equiv="Expires" content="0">
<title>乌圆狩猎区 · 档位图</title>
<link rel="stylesheet" href="/static/components/topnav.css">
<script src="/vendors/vue.global.prod.js"></script>
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
.btn{background:var(--acc);color:#fff;border:0;padding:9px 18px;border-radius:6px;font-size:14px;
  cursor:pointer;font-weight:600}
.btn:hover{background:#1d4fd1}
.btn:disabled{background:#9aaeed;cursor:wait}
.btn.ghost{background:var(--soft);color:var(--ink)}
.btn.ghost:hover{background:#e2e7f2}
.btn.sm{padding:6px 12px;font-size:12.5px;font-weight:500}
input[type=text],input[type=number]{border:1px solid var(--line2);padding:8px 10px;border-radius:6px;
  font-size:13px;background:#fff;color:var(--ink);font-family:Menlo,Consolas,monospace}
input.w80{width:80px} input.w100{width:100px} input.w160{width:160px}
input.w320{width:320px}
select{border:1px solid var(--line2);padding:8px 10px;border-radius:6px;font-size:13px;
  background:#fff;color:var(--ink)}
.err{background:#fff5f5;border:1px solid #f5b5b5;color:#c62828;padding:10px 14px;
  border-radius:6px;margin:10px 0;font-size:13px}
.warn-row{background:#fff8e1;border:1px solid #ffe082;padding:8px 12px;border-radius:6px;
  margin-bottom:8px;font-size:13px}
.warn-row.bad{background:#fdecea;border-color:#f5b5b5;color:#c62828}
.sum{display:grid;grid-template-columns:repeat(5,1fr);gap:10px}
.sum .tile{background:var(--soft);padding:10px 12px;border-radius:6px}
.sum .tile .k{font-size:11px;color:var(--sub);margin-bottom:4px}
.sum .tile .v{font-size:18px;font-weight:700;font-family:Menlo,Consolas,monospace}
.sum .tile .s{font-size:11px;color:var(--sub);margin-top:2px}
.state-bar{margin-top:12px;padding:9px 13px;border-radius:6px;font-size:13px;font-weight:600;
  background:var(--soft);color:var(--ink);border:1px solid var(--line2)}
.state-bar.void{background:#fdecea;border-color:#f5b5b5;color:#c62828}
.state-bar.in_zone{background:#fff3e0;border-color:#ffcc80;color:#e65100}
#svgbox{overflow-x:auto}
#svgbox svg{display:block;max-width:100%}
table{width:100%;border-collapse:collapse;font-size:13px}
table th,table td{padding:7px 10px;border-bottom:1px solid var(--line);text-align:right}
table th{background:var(--soft);color:var(--sub);font-weight:600;font-size:12px}
table th:first-child,table td:first-child,
table th:last-child,table td:last-child{text-align:left}
td.mono{font-family:Menlo,Consolas,monospace}
tr.key-hi td{background:#fffaf0}
tr.key-st td{background:#fdf3f3}
tr.key-void td{background:#f7f7f7;color:#6e6e73}
tr.key-t1 td{background:#f4f9ec}
tr.key-live td{background:#f0f7ff}
.disci{font-size:13px;line-height:1.9;color:var(--sub);margin:0;padding-left:18px}
.disci li{margin:0}
.foot{font-size:12px;color:var(--sub);border-top:1px solid var(--line);padding-top:10px;
  margin-top:10px;line-height:1.7}
.empty{color:var(--sub);padding:20px;text-align:center;font-size:13px}
.sec{margin-top:16px;border-top:1px dashed var(--line2);padding-top:12px}
.sec .hd{font-size:13px;font-weight:600;color:var(--ink);margin-bottom:8px;cursor:pointer;
  display:flex;align-items:center;gap:6px}
.sec .hd .ar{color:var(--sub);font-weight:400}
@media (max-width:820px){.sum{grid-template-columns:repeat(2,1fr)}}
</style>
</head>
<body>
<div class="topnav">
  <a class="tn-home" href="/">📊 quant_review</a>
  <topnav-bar class="topnav-links" data-active="/wuyuan"></topnav-bar>
  <span class="tn-spacer"></span>
  <span class="tn-tag">Binance Futures · </span>
</div>

<div class="wrap">
<div id="app">

  <h1 style="font-size:22px;margin:0 0 8px">乌圆狩猎区 · 档位图</h1>
  <div style="color:var(--sub);font-size:13px;margin-bottom:14px">
    口径：<b>100.0 档 = 当日开盘价</b> ｜ 狩猎区 = 38.2 ~ 61.8 档 ｜ 止损 = 19.1 档 ｜
    第一目标 = 昨收 ｜ 衰竭目标 = 161.8 / 261.8 档 ｜
    <b style="color:#c62828">腿端（0.0 档）由系统自研规则自动计算</b>
  </div>

  <!-- ① 自研腿（唯一入口） -->
  <div class="card">
    <h2>① 自研腿 <span class="h-tag">系统自己算，零输入</span></h2>
    <div class="cb">
      <button class="btn" @click="loadAutoLeg" :disabled="busy">
        <span v-if="busy">计算中…</span><span v-else>🦾 计算今天的狩猎区</span>
      </button>
      <span class="label" style="margin-left:10px">
        腿端 = 近 {{ lookback }} 日方向性极值 ｜ 方向 = 跳空方向 ｜ 开盘价由系统自行获取
      </span>
      <button class="btn ghost sm" @click="refreshLive" :disabled="busy"
              style="margin-left:auto">刷新现价</button>
    </div>
    <div v-if="res && res.mode === 'auto_leg'" class="warn-row"
         style="border-left:3px solid #d97706">
      ⚠ <b>自研腿（{{ (res.auto && res.auto.tag) || '未验证' }}）</b>：
      本腿由我们自己的规则算出，不是他公布的数值。
      {{ (res.auto && res.auto.verdict) || '' }}
      （规则：腿端 = 近 {{ (res.auto && res.auto.lookback) || 5 }} 日方向性极值；方向 = 跳空方向）
    </div>
    <!-- 成本地板闸门：tradable=False 时必须显性告警，不得静默 -->
    <div v-if="res && res.mode === 'auto_leg' && res.auto && res.auto.tradable === false"
         class="warn-row" style="border-left:3px solid #dc2626;color:#dc2626">
      🚫 <b>不可交易</b>：{{ res.auto.trade_note }}
      <span v-if="res.auto.r_bp">
        （本腿止损 {{ res.auto.r_bp.toFixed(1) }}bp ／ 成本地板 {{ res.auto.cost_floor_bp }}bp）
      </span>
    </div>
    <div v-if="res && res.mode === 'auto_leg' && res.auto && res.auto.tradable === true"
         class="warn-row" style="border-left:3px solid #16a34a">
      ✅ 结构宽度 {{ res.auto.r_bp.toFixed(1) }}bp ≥ 成本地板 {{ res.auto.cost_floor_bp }}bp
      ⇒ 该腿在成本上**可交易**（但选腿规则本身仍未通过显著性检验）。
    </div>
    <!-- 自研腿专属警示：逐条渲染，避免只显示一句被忽略 -->
    <div v-for="(w, i) in (res && res.mode === 'auto_leg' ? (res.auto_warnings || []) : [])"
         :key="'aw'+i" class="warn-row">{{ w }}</div>
    <div v-if="err" class="err">⚠ {{ err }}</div>
    <div v-if="hint" class="warn-row">{{ hint }}</div>
    <div v-for="(w, i) in (res && res.warnings) || []" :key="'w'+i" class="warn-row">{{ w }}</div>
  </div>

  <!-- ② 摘要 + 结构图 -->
  <template v-if="res && res.mode === 'auto_leg'">
    <div class="card">
      <h2>② 摘要 <span class="h-tag">{{ res.direction_cn }} · {{ res.engine }}</span></h2>
      <div class="sum">
        <div class="tile"><div class="k">方向</div><div class="v">{{ res.direction_cn }}</div>
          <div class="s">自研腿（未验证）</div></div>
        <div class="tile"><div class="k">开盘价 = 100.0 档</div>
          <div class="v">{{ f2(res.open_px) }}</div><div class="s">官方口径</div></div>
        <div class="tile"><div class="k">跨度 S</div><div class="v">{{ f2(res.S) }}</div>
          <div class="s">腿长</div></div>
        <div class="tile"><div class="k">R = 止损距离</div><div class="v">{{ f2(res.R) }}</div>
          <div class="s">0.191 × S</div></div>
        <div class="tile"><div class="k">狩猎区宽</div><div class="v">{{ f2(res.zone_width) }}</div>
          <div class="s">{{ f2(res.zone_lo) }} ~ {{ f2(res.zone_hi) }}</div></div>
      </div>
      <div class="state-bar" :class="(res.position && res.position.state) || ''">
        {{ (res.position && res.position.text) || '—' }}
      </div>
      <div v-if="res.special_gap" class="warn-row bad" style="margin-top:10px">
        <b>跳空特殊日：</b>衰竭① {{ f2(res.exh1) }} 与昨收 {{ f2(res.prev_close) }} 错侧
        ⇒ 不减仓博弈，直接到衰竭位走平。
      </div>
    </div>

    <div class="card">
      <h2>③ 档位结构图 <span class="h-tag">按档位等距排列 · 真实比例见档位表</span></h2>
      <div id="svgbox" v-html="svg"></div>
      <div class="foot">
        色带 = 狩猎区（38.2 ~ 61.8 档）｜
        <span style="color:#A32D2D">红虚线 = 止损</span>｜
        <span style="color:#3B6D11">绿 = 目标（昨收 / 衰竭）</span>｜
        <span style="color:#888780">灰虚线 = 腿失效线</span>｜
        <span style="color:#185FA5">蓝 = 开盘价基准 / 现价游标</span>
      </div>
    </div>

    <div class="card">
      <h2>④ 档位表 <span class="h-tag">距离基准：{{ baseLabel }}</span></h2>
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
    </div>
  </template>

  <!-- ⑤ 纪律 -->
  <div class="card">
    <h2>⑤ 纪律 <span class="h-tag">来自讲解视频逐字稿</span></h2>
    <ul class="disci">
      <li v-for="(d, i) in discipline" :key="'d'+i">{{ d }}</li>
    </ul>
    <div class="foot">
      系统<b>不自动下单</b>、<b>不猜选腿</b>（S / 方向必须人工给定）；现价为
      Binance  <b>期货参考价</b>，与官方现货口径存在基差（实测 −98 ~ +24 点），
      仅用于显示"距狩猎区还有多少点"，<b>不参与档位计算</b>。
    </div>
  </div>

</div>
</div>

<script src="/static/components/topnav.js" defer></script>
<script>
(function () {
  var API = '/api/wuyuan/ladder';

  function num(v) {
    if (v === null || v === undefined || v === '') return null;
    var n = parseFloat(String(v).replace(/[^0-9.\-]/g, ''));
    return isNaN(n) ? null : n;
  }

  var app = Vue.createApp({
    data: function () {
      return {
        // 开盘价留空 = 交给服务端自行获取（推荐）；填了则作 overlay 覆盖
        openPx: '',
        lookback: 5,
        res: null,
        svg: '',
        busy: false,
        err: '',
        hint: '',
        discipline: [
          '单日最多 2 笔；连续两次止损当日收手',
          '狩猎区内三档各挂 1/3 仓位',
          '到昨收减半仓，止损同步移至保本',
          '衰竭位须等小时级收线 + 缓冲再反手',
          '系统不自动下单，只做档位计算与纪律提醒'
        ]
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
      this.loadAutoLeg();
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

      request: function (qs) {
        var self = this;
        self.busy = true;
        self.err = '';
        self.hint = '';
        fetch(API + '?' + qs, { cache: 'no-store' })
          .then(function (r) { return r.json(); })
          .then(function (d) {
            if (!d || d.code !== 200) {
              self.err = (d && d.error) ? d.error : ('接口返回异常 (code=' + (d && d.code) + ')');
              self.res = null;
              self.svg = '';
              return;
            }
            self.res = d;
            self.svg = self.buildSvg(d);
          })
          .catch(function (e) {
            self.err = '请求失败：' + e;
            self.res = null;
            self.svg = '';
            console.error('[wuyuan] load failed', e);
          })
          .then(function () { self.busy = false; });
      },

      // 唯一入口：自研腿。开盘价由服务端自行获取（也可传 open_px 覆盖）。
      loadAutoLeg: function () {
        var o = num(this.openPx);
        var qs = 'auto=1&live=1';
        if (o !== null) qs = 'auto=1&open_px=' + o + '&live=1';
        this.request(qs);
      },

      // 刷新现价：重新拉一次自研腿（档位与腿不变，只更新现价与距离列）
      refreshLive: function () {
        this.loadAutoLeg();
      },

      rowStyle: function (row) {
        if (row.kind === 'live') {
          return { s: 'stroke="#185FA5" stroke-width="1.5" stroke-dasharray="6 4"', c: '#185FA5' };
        }
        if (row.kind === 't1') {
          return { s: 'stroke="#639922" stroke-width="1" stroke-dasharray="3 2"', c: '#27500A' };
        }
        var r = Math.round(Number(row.ratio) * 1000) / 1000;
        if (r === 0) return { s: 'stroke="#888780" stroke-width="1" stroke-dasharray="5 3"', c: '#5F5E5A' };
        if (r === 0.191) return { s: 'stroke="#A32D2D" stroke-width="1.5" stroke-dasharray="7 3"', c: '#791F1F' };
        if (r === 0.5) return { s: 'stroke="#BA7517" stroke-width="0.5" stroke-dasharray="3 3"', c: '#854F0B' };
        if (r === 0.382 || r === 0.618) return { s: 'stroke="#BA7517" stroke-width="1"', c: '#854F0B' };
        if (r === 1) return { s: 'stroke="#185FA5" stroke-width="1.5"', c: '#0C447C' };
        if (r === 1.618 || r === 2.618) return { s: 'stroke="#3B6D11" stroke-width="1"', c: '#27500A' };
        return { s: 'stroke="#B4B2A9" stroke-width="0.5"', c: '#6e6e73' };
      },

      buildSvg: function (r) {
        var rows = [];
        (r.levels || []).forEach(function (l) {
          rows.push({
            kind: 'level', ratio: l.ratio, name: l.name,
            price: Number(l.price), role: l.role || ''
          });
        });
        if (r.t1 !== null && r.t1 !== undefined) {
          rows.push({ kind: 't1', name: '昨收', price: Number(r.t1),
                      role: '第一目标位 · 到价减仓 + 止损移保本' });
        }
        if (r.live && r.live.px !== null && r.live.px !== undefined) {
          rows.push({ kind: 'live', name: '现价', price: Number(r.live.px),
                      role: '期货参考价 · 与官方现货存在基差' });
        }
        rows.sort(function (a, b) { return b.price - a.price; });

        var X0 = 112, X1 = 300, XP = 104, XN = 308, XR = 360;
        var ROW = 38, TOP = 40, n = rows.length;
        var H = TOP + (n - 1) * ROW + 56;
        var self = this;
        var parts = [];
        var esc = function (t) {
          return String(t).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
        };

        parts.push('<svg viewBox="0 0 680 ' + H + '" width="100%" role="img" ' +
                   'xmlns="http://www.w3.org/2000/svg">');
        parts.push('<title>乌圆狩猎区档位结构图</title>');
        parts.push('<desc>' + esc(
          (r.direction_cn || '') + ' ｜ 开盘价 ' + this.f2(r.open_px) + ' ｜ S ' + this.f2(r.S) +
          ' ｜ 止损 ' + this.f2(r.stop) + ' ｜ 狩猎区 ' + this.f2(r.zone_lo) + ' ~ ' + this.f2(r.zone_hi) +
          ' ｜ 衰竭 ' + this.f2(r.exh1) + ' / ' + this.f2(r.exh2) +
          ' ｜ 腿失效线 ' + this.f2(r.invalid_line)) + '</desc>');
        parts.push('<defs><marker id="wyArrow" viewBox="0 0 10 10" refX="8" refY="5" ' +
                   'markerWidth="6" markerHeight="6" orient="auto-start-reverse">' +
                   '<path d="M2 1L8 5L2 9" fill="none" stroke="context-stroke" stroke-width="1.5" ' +
                   'stroke-linecap="round" stroke-linejoin="round"/></marker></defs>');

        // 狩猎区色带（跨越 38.2 ~ 61.8 三行）
        var zi = -1, zj = -1;
        rows.forEach(function (row, i) {
          if (row.kind !== 'level') return;
          var rt = Math.round(Number(row.ratio) * 1000) / 1000;
          if (rt === 0.382 && zi < 0) zi = i;
          if (rt === 0.618 && zj < 0) zj = i;
        });
        if (zi >= 0 && zj >= 0) {
          var a = Math.min(zi, zj), b = Math.max(zi, zj);
          var by = TOP + a * ROW - ROW / 2;
          parts.push('<rect x="' + (X0 - 4) + '" y="' + by + '" width="' + (X1 - X0 + 8) +
                     '" height="' + ((b - a + 1) * ROW) +
                     '" rx="4" fill="#FAEEDA" stroke="#EF9F27" stroke-width="0.5"/>');
        }

        rows.forEach(function (row, i) {
          var y = TOP + i * ROW;
          var st = self.rowStyle(row);
          parts.push('<line x1="' + X0 + '" y1="' + y + '" x2="' + X1 + '" y2="' + y +
                     '" ' + st.s + '/>');
          parts.push('<text x="' + XP + '" y="' + y + '" text-anchor="end" ' +
                     'dominant-baseline="central" font-size="12" fill="' + st.c + '">' +
                     row.price.toFixed(2) + '</text>');
          parts.push('<text x="' + XN + '" y="' + y + '" dominant-baseline="central" ' +
                     'font-size="11" fill="' + st.c + '">' + esc(row.name) + '</text>');
          if (row.role) {
            parts.push('<text x="' + XR + '" y="' + y + '" dominant-baseline="central" ' +
                       'font-size="11" fill="' + st.c + '">' + esc(row.role) + '</text>');
          }
        });
        parts.push('</svg>');
        return parts.join('');
      }
    }
  });
  app.mount('#app');
})();
</script>
</body>
</html>
"""
