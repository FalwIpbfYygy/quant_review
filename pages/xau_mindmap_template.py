# -*- coding: utf-8 -*-
"""
 思维导图 · 知识库教学智能体 —— 前端 HTML 模板常量
URL: /xau/mindmap
后端 API:
  GET /api/xau/mindmap/modules            -> 14 个模块清单（侧边栏）
  GET /api/xau/mindmap/module?mid=M03     -> 单模块全部规则
  POST /api/xau/mindmap/chat {q, top_k}   -> 检索 + 回答 + 来源引用

铁律：本页只做【知识检索 / 规则解释 / 案例问答】，严禁输出任何交易信号或方向建议。
"""

HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta http-equiv="Cache-Control" content="no-store, no-cache, must-revalidate">
<meta http-equiv="Pragma" content="no-cache">
<meta http-equiv="Expires" content="0">
<title> 思维导图 · 知识库智能体</title>
<link rel="stylesheet" href="/static/components/topnav.css">
<script src="/static/components/topnav.js" defer></script>
<script src="/vendors/marked.min.js"></script>
<script src="/vendors/purify.min.js"></script>
<script>
  /* Markdown → HTML：marked 解析 + DOMPurify 过滤（XSS 安全） */
  function renderMD(text){
    if (text == null) return '';
    var raw = String(text);
    try {
      if (window.marked && window.marked.parse) {
        raw = window.marked.parse(raw, { gfm: true, breaks: true, headerIds: false, mangle: false });
      }
    } catch(e){ /* marked 不可用时回退原文 */ }
    try {
      if (window.DOMPurify && DOMPurify.sanitize) {
        return DOMPurify.sanitize(raw, { ADD_TAGS:['font','mark'], ADD_ATTR:['color','data-mid','data-rule'] });
      }
    } catch(e){}
    return raw;
  }
</script>
<style>
:root{
  --bg:#f5f6fa; --card:#fff; --ink:#1a1d2e; --sub:#5a6178; --acc:#2962ff;
  --warn:#ff9800; --good:#e53935; --bad:#2ecc71; --line:#e9ecf3; --line2:#d9dde7;
  --soft:#f0f3f9; --mono:#0f1420;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
  font-family:-apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;font-size:14px}
.wrap{max-width:1320px;margin:0 auto;padding:14px 16px 40px}

/* ---------- 顶部横幅 ---------- */
.banner{background:#fff8e1;border:1px solid #ffe082;color:#8d6e00;border-radius:8px;
  padding:9px 14px;font-size:12.5px;line-height:1.7;margin-bottom:12px}
.banner b{color:#c62828}

/* ---------- 两栏骨架 ---------- */
.layout{display:grid;grid-template-columns:290px 1fr;gap:14px;align-items:start}
@media (max-width:900px){.layout{grid-template-columns:1fr}}

/* ---------- 左侧知识树 ---------- */
.side{background:var(--card);border:1px solid var(--line);border-radius:8px;overflow:hidden}
.side h3{margin:0;padding:12px 14px;font-size:13px;border-bottom:1px solid var(--line);
  display:flex;align-items:center;gap:8px;background:var(--soft)}
.side h3 .cnt{font-size:11px;color:var(--sub);font-weight:400;background:#fff;
  padding:1px 7px;border-radius:9px;border:1px solid var(--line2)}
.side .srch{padding:10px 12px;border-bottom:1px solid var(--line)}
.side .srch input{width:100%;border:1px solid var(--line2);border-radius:6px;padding:7px 10px;
  font-size:12.5px;outline:none;background:#fff;color:var(--ink)}
.side .srch input:focus{border-color:var(--acc)}
.modlist{max-height:64vh;overflow:auto}
.mod{display:flex;gap:9px;padding:9px 12px;border-bottom:1px solid #f4f6fa;cursor:pointer;
  align-items:flex-start;transition:background .12s}
.mod:hover{background:var(--soft)}
.mod.on{background:#eaf0ff;box-shadow:inset 3px 0 0 var(--acc)}
.mod .mid{font-size:10.5px;color:#fff;background:#8a94ad;border-radius:4px;padding:2px 5px;
  font-weight:700;flex:0 0 auto;margin-top:1px}
.mod.on .mid{background:var(--acc)}
.mod .mt{font-size:12.8px;font-weight:600;line-height:1.45}
.mod .ms{font-size:11px;color:var(--sub);line-height:1.5;margin-top:3px}
.mod .rc{font-size:10.5px;color:var(--sub);margin-top:3px}

/* ---------- 右侧主区 ---------- */
.main{background:var(--card);border:1px solid var(--line);border-radius:8px;overflow:hidden;
  display:flex;flex-direction:column;min-height:78vh}
.tabs{display:flex;border-bottom:1px solid var(--line);background:var(--soft)}
.tab{padding:11px 20px;font-size:13px;cursor:pointer;color:var(--sub);border-bottom:2px solid transparent;
  font-weight:600}
.tab.on{color:var(--ink);border-bottom-color:var(--acc);background:#fff}
.tab .dot{font-size:10px;color:var(--sub);font-weight:400;margin-left:5px}
.tab.warn.on{color:#c62828;border-bottom-color:#e53935}
.tab.warn .dot{background:#fdecea;color:#c62828;border:1px solid #f5b5b5;border-radius:7px;padding:0 5px}

/* ---------- 行情对话 ---------- */
.mwarn{background:#fdecea;border:1px solid #f5b5b5;color:#8e2c24;border-radius:8px;
  padding:9px 14px;font-size:12.5px;line-height:1.75;margin:12px 18px 0}
.mwarn b{color:#c62828}
.facts{background:#0f1420;color:#d8e0f0;border-radius:7px;padding:12px 14px;font-size:12px;
  line-height:1.8;white-space:pre-wrap;overflow-x:auto;font-family:ui-monospace,Consolas,monospace}
.bub .facts{margin-top:9px}
.mkt-meta{margin-top:9px;padding-top:8px;border-top:1px dashed var(--line2);font-size:11px;color:var(--sub)}
.badge.mkt{background:#fdecea;color:#c62828;border:1px solid #f5b5b5}

/* ---------- 对话区 ---------- */
.chat{flex:1;overflow:auto;padding:16px 18px;background:#fbfcfe}
.msg{margin-bottom:16px;display:flex;gap:10px}
.msg.me{flex-direction:row-reverse}
.av{width:28px;height:28px;border-radius:6px;flex:0 0 auto;display:flex;align-items:center;
  justify-content:center;font-size:11px;color:#fff;font-weight:700}
.av.bot{background:var(--acc)} .av.me{background:#8a94ad} .av.mk{background:#e53935}
.qs .q.act{border-color:#f5b5b5;background:#fff5f5;color:#c62828}
.qs .q.act:hover{background:#fdecea;border-color:#e53935}
.bub{max-width:78%;background:#fff;border:1px solid var(--line);border-radius:8px;padding:11px 14px;
  font-size:13.5px;line-height:1.85;white-space:pre-wrap;word-break:break-word}
.msg.me .bub{background:#eaf0ff;border-color:#c9d8ff}
.bub .meta{margin-top:9px;padding-top:8px;border-top:1px dashed var(--line2);font-size:11px;color:var(--sub)}
.bub .srcs{margin-top:7px;display:flex;flex-wrap:wrap;gap:6px}
.chip{font-size:10.5px;background:var(--soft);border:1px solid var(--line2);color:var(--sub);
  padding:2px 7px;border-radius:9px;cursor:pointer}
.chip:hover{border-color:var(--acc);color:var(--acc)}
.badge{display:inline-block;font-size:10px;padding:1px 6px;border-radius:8px;margin-left:6px}
.badge.llm{background:#e8f5e9;color:#2e7d32;border:1px solid #c8e6c9}
.badge.fb{background:#fff3e0;color:#e65100;border:1px solid #ffd180}
.badge.blk{background:#fdecea;color:#c62828;border:1px solid #f5b5b5}
.empty{color:var(--sub);font-size:13px;text-align:center;padding:44px 10px;line-height:2}
.qs{display:flex;flex-wrap:wrap;gap:7px;padding:10px 18px;border-top:1px solid var(--line);background:#fff}
.qs .q{font-size:12px;border:1px solid var(--line2);background:var(--soft);border-radius:14px;
  padding:5px 12px;cursor:pointer;color:var(--sub)}
.qs .q:hover{border-color:var(--acc);color:var(--acc);background:#eaf0ff}
.composer{display:flex;gap:9px;padding:12px 16px;border-top:1px solid var(--line);background:#fff}
.composer textarea{flex:1;border:1px solid var(--line2);border-radius:7px;padding:10px 12px;
  font-size:13.5px;resize:none;height:52px;outline:none;font-family:inherit;color:var(--ink)}
.composer textarea:focus{border-color:var(--acc)}
.btn{background:var(--acc);color:#fff;border:0;border-radius:7px;padding:0 22px;font-size:14px;
  cursor:pointer;font-weight:600}
.btn:disabled{background:#9aaeed;cursor:wait}
.btn.ghost{background:var(--soft);color:var(--ink);padding:0 14px;font-weight:500}
.typing{color:var(--sub);font-size:12.5px}

/* ---------- 浏览区 ---------- */
.browse{padding:16px 18px;overflow:auto;flex:1;background:#fbfcfe}
.b-head{background:#fff;border:1px solid var(--line);border-radius:8px;padding:14px 16px;margin-bottom:12px}
.b-head .t{font-size:16px;font-weight:700}
.b-head .s{font-size:12.5px;color:var(--sub);margin-top:5px;line-height:1.7}
.b-head .src{font-size:11px;color:var(--sub);margin-top:6px}
.rule{background:#fff;border:1px solid var(--line);border-radius:7px;padding:11px 14px;margin-bottom:9px}
.rule .rh{display:flex;gap:9px;align-items:baseline;margin-bottom:6px}
.rule .rid{font-size:10.5px;color:#fff;background:#8a94ad;border-radius:4px;padding:2px 6px;font-weight:700}
.rule .rn{font-size:13.5px;font-weight:600}
.rule .rd{font-size:13px;line-height:1.85;color:#33394d;white-space:pre-wrap}
.rule .rc2{margin-top:7px;display:flex;flex-wrap:wrap;gap:6px}
.kw{font-size:10.5px;background:var(--soft);border:1px solid var(--line2);color:var(--sub);
  padding:2px 7px;border-radius:9px}
.hide{display:none}
.err{background:#fff5f5;border:1px solid #f5b5b5;color:#c62828;padding:10px 14px;border-radius:6px;font-size:13px}

/* ====== Markdown 渲染样式（仅作用于对话气泡内） ====== */
.bub h1,.bub h2,.bub h3,.bub h4{margin:14px 0 8px;font-weight:600;color:var(--ink);line-height:1.35}
.bub h1{font-size:18px;border-bottom:1px solid var(--line2);padding-bottom:6px}
.bub h2{font-size:15.5px}
.bub h3{font-size:14px;color:var(--sub)}
.bub h4{font-size:13.5px;color:var(--sub)}
.bub p{margin:6px 0;line-height:1.65}
.bub ul,.bub ol{margin:6px 0 6px 22px;line-height:1.7}
.bub li{margin:3px 0}
.bub code{background:var(--soft);padding:1px 6px;border-radius:3px;font-size:12px;
  font-family:ui-monospace,Consolas,monospace;color:#c7254e;border:1px solid var(--line2)}
.bub pre{background:#0f1115;color:#e6edf3;padding:12px 14px;border-radius:6px;overflow-x:auto;
  font-size:12.5px;line-height:1.55;margin:8px 0}
.bub pre code{background:transparent;border:0;padding:0;color:inherit;font-size:12.5px}
.bub blockquote{margin:8px 0;padding:6px 12px;border-left:3px solid var(--acc);
  background:var(--soft);color:#444;font-size:13px;border-radius:0 4px 4px 0}
.bub hr{border:0;border-top:1px dashed var(--line2);margin:12px 0}
.bub table{border-collapse:collapse;margin:8px 0;font-size:12.5px;width:auto;max-width:100%}
.bub table th,.bub table td{border:1px solid var(--line2);padding:5px 10px;text-align:left;vertical-align:top}
.bub table th{background:var(--soft);font-weight:600;color:var(--ink)}
.bub table tr:nth-child(even) td{background:#fafbfc}
.bub strong{font-weight:600;color:var(--ink)}
.bub em{font-style:italic;color:#444}
.bub a{color:var(--acc);text-decoration:none;border-bottom:1px solid #bcd}
.bub a:hover{border-bottom-color:var(--acc)}
.bub del{color:#999}
.bub mark{background:#fff59d;color:#333;padding:0 3px;border-radius:2px}
</style>
</head>
<body>
<topnav-bar data-active="/mindmap"></topnav-bar>

<div class="wrap">
  <div class="banner">
    <b>⚠ 边界声明：</b>本页是<b>知识库检索型教学智能体</b>——只回答「规则是什么 / 怎么识别 / 为什么这样设」。
    它<b>不读取任何实时行情、不连接 Binance、不参与 TRAE 信号链路，也绝不给出买卖方向、点位或仓位建议</b>。
    所有回答均附来源引用（模块 / 规则编号），可回到思维导图原图逐条核对。
  </div>

  <div class="layout">
    <!-- 左：知识树 -->
    <div class="side">
      <h3>📚 思维导图知识库 <span class="cnt" id="totalCnt">—</span></h3>
      <div class="srch"><input id="modSearch" placeholder="过滤模块（如：止损 / OODA / 形态）"></div>
      <div class="modlist" id="modList"><div style="padding:14px;color:#8a94ad;font-size:12.5px">加载中…</div></div>
    </div>

    <!-- 右：对话 / 浏览 -->
    <div class="main">
      <div class="tabs">
        <div class="tab on" data-tab="chat">💬 知识库问答</div>
        <div class="tab" data-tab="browse">🗂 知识库浏览 <span class="dot" id="browseName"></span></div>
        <div class="tab warn" data-tab="market">📈 行情对话 <span class="dot">AI</span></div>
      </div>

      <!-- 对话 -->
      <div id="paneChat" style="display:flex;flex-direction:column;flex:1;min-height:0">
        <div class="chat" id="chatBox">
          <div class="empty">
            你好，我是你的 <b> 思维导图知识库智能体</b>。<br>
            我可以帮你查：5 种核心 K 线形态怎么识别、止损怎么设、W 底 / M 顶颈线、
            POC 一致性、缺口、多周期共振、50 中线、做市商收割、划痕式交易、OODA 循环、NQ 5 分钟突破 8 步……<br>
            <span style="color:#c62828">我不提供任何交易信号。试着问一句，或点下面的快捷问题。</span>
          </div>
        </div>
        <div class="qs" id="quickQs">
          <div class="q">平顶上、平顶下、平顶加分别怎么识别？</div>
          <div class="q">各形态的止损怎么设？</div>
          <div class="q">什么是 POC 一致性？</div>
          <div class="q">W 底和 M 顶的颈线怎么画？</div>
          <div class="q">OODA 循环四个阶段是什么？</div>
          <div class="q">做市商是怎么收割散户的？</div>
          <div class="q">多周期共振怎么排？</div>
          <div class="q">NQ 5 分钟突破策略的 8 个步骤？</div>
        </div>
        <div class="composer">
          <textarea id="qInput" placeholder="输入你的问题（Enter 发送 / Shift+Enter 换行）"></textarea>
          <button class="btn" id="sendBtn">发送</button>
        </div>
      </div>

      <!-- 浏览 -->
      <div id="paneBrowse" class="browse hide">
        <div id="browseBody">
          <div class="empty">← 点击左侧任意模块，查看该模块的全部规则原文。</div>
        </div>
      </div>

      <!-- 行情对话（AI 分析师 · 实验） -->
      <div id="paneMarket" class="hide" style="display:flex;flex-direction:column;flex:1;min-height:0">
        <div class="mwarn">
          <b>⚠️ AI 行情观点（实验模块）</b>：本 tab 会拉取 <b>Binance  实时 K 线</b>（只含已收盘，无未来函数），
          结合你的思维导图规则，由大模型给出<b>方向 / 进场 / 止损 / 止盈</b>。
          它<b>只读行情、只输出文字，不写信号库、不触发下单、不接入 TRAE 实盘链路</b>。
          输出属参考观点，非交易系统信号，风险自负。
        </div>
        <div class="chat" id="mktBox">
          <div class="empty">
            点下方按钮开始：<b>拉取当前  盘面事实</b>（多周期客观数据，不需要 LLM），
            或直接<b>让 AI 给出交易方案</b>（需要配置 BAILIAN_API_KEY）。
          </div>
        </div>
        <div class="qs" id="mktQs">
          <div class="q act" id="btnFacts">📊 拉取盘面事实（不调 LLM）</div>
          <div class="q act" id="btnPlan">🎯 AI 给出完整交易方案</div>
          <div class="q act" id="btnStruct">🧭 当前是什么结构？W底/M顶/区间？</div>
          <div class="q act" id="btnRisk">🛡 如果按你的方案做，失效条件是什么？</div>
        </div>
        <div class="qs" style="margin-top:0">
          <div class="q act" id="newsToggle" title="结合金十消息面（数据窗口/实时快讯），点击可开关，做纯技术面对照">📰 结合消息面</div>
        </div>
        <div class="composer">
          <textarea id="mktInput" placeholder="问行情（Enter 发送）。例：现在 4H 是什么阶段？4360 能撑住吗？"></textarea>
          <button class="btn warn" id="mktSend">发送</button>
        </div>
      </div>
    </div>
  </div>
</div>

<script>
(function(){
  'use strict';
  var MODS = [], curMid = null;

  function el(id){ return document.getElementById(id); }
  function esc(s){ return String(s==null?'':s).replace(/[&<>"]/g,function(c){
    return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]; }); }
  function jget(u){ return fetch(u,{headers:{'Cache-Control':'no-cache'}}).then(function(r){return r.json();}); }

  /* ---------- 侧边栏 ---------- */
  function renderMods(filter){
    var box = el('modList'); filter = (filter||'').trim().toLowerCase();
    var html = '';
    for (var i=0;i<MODS.length;i++){
      var m = MODS[i];
      if (filter && (m.title+' '+m.summary+' '+m.mid).toLowerCase().indexOf(filter) < 0) continue;
      html += '<div class="mod'+(m.mid===curMid?' on':'')+'" data-mid="'+esc(m.mid)+'">'
            +   '<div class="mid">'+esc(m.mid)+'</div>'
            +   '<div><div class="mt">'+esc(m.title)+'</div>'
            +     '<div class="ms">'+esc(m.summary)+'</div>'
            +     '<div class="rc">'+m.rule_count+' 条规则</div></div>'
            + '</div>';
    }
    box.innerHTML = html || '<div style="padding:14px;color:#8a94ad;font-size:12.5px">无匹配模块</div>';
    var nodes = box.querySelectorAll('.mod');
    for (var k=0;k<nodes.length;k++){
      nodes[k].addEventListener('click', function(){ openModule(this.getAttribute('data-mid')); });
    }
  }

  jget('/api/xau/mindmap/modules').then(function(r){
    MODS = (r && r.data) || [];
    var n = 0; for (var i=0;i<MODS.length;i++) n += MODS[i].rule_count;
    el('totalCnt').textContent = MODS.length + ' 模块 / ' + n + ' 规则';
    renderMods('');
  }).catch(function(e){
    el('modList').innerHTML = '<div class="err">模块加载失败：'+esc(e)+'</div>';
  });

  el('modSearch').addEventListener('input', function(){ renderMods(this.value); });

  /* ---------- Tab 切换 ---------- */
  var tabs = document.querySelectorAll('.tab');
  for (var t=0;t<tabs.length;t++){
    tabs[t].addEventListener('click', function(){
      for (var x=0;x<tabs.length;x++) tabs[x].classList.remove('on');
      this.classList.add('on');
      var name = this.getAttribute('data-tab');
      var panes = {chat:'paneChat', browse:'paneBrowse', market:'paneMarket'};
      for (var key in panes){
        var p = el(panes[key]);
        p.classList.toggle('hide', key !== name);
        p.style.display = (key === name) ? (key === 'browse' ? 'block' : 'flex') : 'none';
      }
    });
  }
  function switchTo(tab){
    for (var x=0;x<tabs.length;x++){
      if (tabs[x].getAttribute('data-tab') === tab) tabs[x].click();
    }
  }

  /* ---------- 模块浏览 ---------- */
  function openModule(mid){
    curMid = mid; renderMods(el('modSearch').value); switchTo('browse');
    var body = el('browseBody');
    body.innerHTML = '<div style="color:#8a94ad;font-size:12.5px">加载中…</div>';
    jget('/api/xau/mindmap/module?mid='+encodeURIComponent(mid)).then(function(r){
      var d = (r && r.data) || {};
      el('browseName').textContent = d.title ? ('· '+d.title) : '';
      var h = '<div class="b-head"><div class="t">'+esc(d.mid)+' · '+esc(d.title)+'</div>'
            + '<div class="s">'+esc(d.summary)+'</div>'
            + '<div class="src">来源：'+esc(d.source)+'　规则数：'+((d.rules||[]).length)+'</div></div>';
      var rs = d.rules || [];
      for (var i=0;i<rs.length;i++){
        var x = rs[i];
        h += '<div class="rule"><div class="rh"><span class="rid">'+esc(x.id)+'</span>'
           + '<span class="rn">'+esc(x.name)+'</span></div>'
           + '<div class="rd">'+esc(x.detail)+'</div>';
        var kws = x.keywords || [];
        if (kws.length){
          h += '<div class="rc2">';
          for (var j=0;j<kws.length;j++) h += '<span class="kw">'+esc(kws[j])+'</span>';
          h += '</div>';
        }
        h += '</div>';
      }
      body.innerHTML = h;
      el('paneBrowse').scrollTop = 0;
    }).catch(function(e){
      body.innerHTML = '<div class="err">加载失败：'+esc(e)+'</div>';
    });
  }

  /* ---------- 对话 ---------- */
  var box = el('chatBox');
  function addBubble(who, html){
    var d = document.createElement('div'); d.className = 'msg ' + who;
    d.innerHTML = '<div class="av '+(who==='me'?'me':'bot')+'">'+(who==='me'?'我':'KB')+'</div>'
                + '<div class="bub">'+html+'</div>';
    box.appendChild(d); box.scrollTop = box.scrollHeight; return d;
  }
  function clearEmpty(){ var e = box.querySelector('.empty'); if (e) e.remove(); }

  function send(q){
    q = (q||'').trim(); if (!q) return;
    clearEmpty();
    addBubble('me', esc(q));
    el('qInput').value = '';
    var wait = addBubble('bot', '<span class="typing">正在检索知识库…</span>');
    el('sendBtn').disabled = true;
    box.scrollTop = box.scrollHeight;

    fetch('/api/xau/mindmap/chat', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({q:q, top_k:6})
    }).then(function(r){ return r.json(); })
      .then(function(r){
        var d = (r && r.data) || {};
        var mode = d.mode || 'fallback';
        var badge = (mode === 'llm')
          ? '<span class="badge llm">LLM 生成</span>'
          : (mode === 'blocked'
             ? '<span class="badge blk">⛔ 已拦截（不出交易建议）</span>'
             : '<span class="badge fb">确定性检索（未接 LLM）</span>');
        var meta = '';
        if (d.latency_ms != null) meta += fmtLatency(d.latency_ms) + '　';
        meta += '命中 ' + ((d.hits||[]).length) + ' 条';
        var srcs = '';
        var ss = d.sources || [];
        if (ss.length){
          srcs = '<div class="srcs">';
          for (var i=0;i<ss.length;i++){
            srcs += '<span class="chip" data-mid="'+esc(ss[i].module)+'">'
                  + esc(ss[i].rule)+' · '+esc(ss[i].rule_name || ss[i].title || '')+'</span>';
          }
          srcs += '</div>';
        }
        wait.querySelector('.bub').innerHTML = renderMD(d.answer || '（无回答）') + srcs
          + '<div class="meta">'+badge+'　'+esc(meta)+'</div>';
        var chips = wait.querySelectorAll('.chip');
        for (var c=0;c<chips.length;c++){
          chips[c].addEventListener('click', function(){ openModule(this.getAttribute('data-mid')); });
        }
        box.scrollTop = box.scrollHeight;
      })
      .catch(function(e){
        wait.querySelector('.bub').innerHTML = '<span style="color:#c62828">请求失败：'+esc(e)+'</span>';
      })
      .then(function(){ el('sendBtn').disabled = false; });
  }

  el('sendBtn').addEventListener('click', function(){ send(el('qInput').value); });
  el('qInput').addEventListener('keydown', function(e){
    if (e.key === 'Enter' && !e.shiftKey){ e.preventDefault(); send(this.value); }
  });
  var qs = document.querySelectorAll('#quickQs .q');
  for (var i=0;i<qs.length;i++){
    qs[i].addEventListener('click', function(){ send(this.textContent); });
  }

  /* ---------- 行情对话（AI 分析师 · 实验） ---------- */
  var mbox = el('mktBox');
  var withNews = true;   // 📰 结合消息面 开关（默认开）
  function mBubble(who, html){
    clearEmptyMkt();
    var d = document.createElement('div'); d.className = 'msg ' + who;
    d.innerHTML = '<div class="av '+(who==='me'?'me':'mk')+'">'+(who==='me'?'我':'AI')+'</div>'
                + '<div class="bub">'+html+'</div>';
    mbox.appendChild(d); mbox.scrollTop = mbox.scrollHeight; return d;
  }
  function clearEmptyMkt(){ var e = mbox.querySelector('.empty'); if (e) e.remove(); }

  // 耗时：毫秒 -> "X 分 Y 秒" / "Y 秒"（>1 分钟才显示分）
  function fmtLatency(ms) {
    if (ms == null) return '';
    var s = Math.round(ms / 1000);
    if (s < 1) return '耗时 < 1 秒';
    if (s < 60) return '耗时 ' + s + ' 秒';
    var m = Math.floor(s / 60), r = s % 60;
    return '耗时 ' + m + ' 分' + (r > 0 ? (' ' + r + ' 秒') : '');
  }

  function mSend(q, factsOnly){
    clearEmptyMkt();
    if (q) mBubble('me', esc(q));
    el('mktInput').value = '';
    var wait = mBubble('bot', '<span class="typing">⏳ 正在拉取  实时行情并生成方案…<br>'
      + '<span style="color:#8a94ad">（首次生成约需 60–90 秒，请稍候，不要重复点击）</span></span>');
    el('mktSend').disabled = true;
    fetch('/api/xau/mindmap/market', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({q: q || '', facts_only: !!factsOnly, top_k: 6, with_news: withNews})
    }).then(function(r){ return r.json(); })
      .then(function(r){
        var d = (r && r.data) || {};
        var mode = d.mode || 'error';
        var badge = (mode === 'llm') ? '<span class="badge mkt">🤖 AI 观点</span>'
                  : (mode === 'facts') ? '<span class="badge fb">📊 客观事实（未调 LLM）</span>'
                  : (mode === 'no_key') ? '<span class="badge fb">⚠️ 未配置 LLM Key</span>'
                  : '<span class="badge blk">✗ 失败</span>';
        var meta = (d.latency_ms != null ? fmtLatency(d.latency_ms) + '　' : '')
                 + (d.model ? '模型 ' + esc(d.model) + '　' : '')
                 + ((d.sources||[]).length ? '引用规则 ' + d.sources.length + ' 条' : '');
        var html = '';
        if (d.answer && d.answer.trim()){
          html += '<div class="md-body">'+renderMD(d.answer)+'</div>';
        } else if (mode === 'llm' || (d.latency_ms != null && d.latency_ms > 5000)){
          // LLM 调用成功但 content 为空（典型场景：推理模型把 token 都花在 thinking 上）
          html += '<div class="err" style="background:#fff8e1;border:1px solid #ffd54f;padding:10px 12px;border-radius:6px;color:#6d4c00;margin-bottom:8px">'
                + '<b>⚠ AI 本次未输出文字</b><br>'
                + '原因：模型 reasoning（内部思考）占满了 token 预算，导致 content 为空（finish_reason=length）。<br>'
                + '建议：① 换用 <code>kimi-k2.7-code</code> / <code>qwen3-max</code> 等非推理模型；② 或在 <code>config.py</code> 把 <code>BAILIAN_MODEL</code> 改回非推理模型。'
                + '</div>';
        }
        if (r.msg && (mode === 'no_key' || mode === 'error')){
          html += '<div class="err">'+esc(r.msg)+'</div>';
        }
        if (d.facts_text){
          html += '<details'+(mode==='facts'?' open':'')+'><summary style="cursor:pointer;font-size:12.5px;color:#2962ff;font-weight:600;padding:6px 0">'
                + '📊 查看客观盘面事实（可审计原始数据）</summary>'
                + '<div class="facts md-body">'+renderMD(d.facts_text)+'</div></details>';
        }
        if (d.news_text){
          html += '<details'+(mode==='facts'?' open':'')+'><summary style="cursor:pointer;font-size:12.5px;color:#e65100;font-weight:600;padding:6px 0">'
                + '📰 查看消息面事实（金十，可审计）</summary>'
                + '<div class="news md-body">'+renderMD(d.news_text)+'</div></details>';
        }
        if ((d.sources||[]).length){
          html += '<div class="srcs">';
          for (var i=0;i<d.sources.length;i++){
            html += '<span class="chip" data-mid="'+esc(d.sources[i].module)+'">'
                  + esc(d.sources[i].rule)+' · '+esc(d.sources[i].rule_name)+'</span>';
          }
          html += '</div>';
        }
        html += '<div class="mkt-meta">'+badge+'　'+esc(meta)+'</div>';
        wait.querySelector('.bub').innerHTML = html;
        var chips = wait.querySelectorAll('.chip');
        for (var c=0;c<chips.length;c++){
          chips[c].addEventListener('click', function(){ openModule(this.getAttribute('data-mid')); });
        }
        mbox.scrollTop = mbox.scrollHeight;
      })
      .catch(function(e){
        wait.querySelector('.bub').innerHTML = '<span style="color:#c62828">请求失败：'+esc(e)+'</span>';
      })
      .then(function(){ el('mktSend').disabled = false; });
  }

  el('mktSend').addEventListener('click', function(){ mSend(el('mktInput').value, false); });
  el('mktInput').addEventListener('keydown', function(e){
    if (e.key === 'Enter' && !e.shiftKey){ e.preventDefault(); mSend(this.value, false); }
  });
  el('btnFacts').addEventListener('click', function(){ mSend('拉取当前盘面客观事实', true); });
  el('btnPlan').addEventListener('click', function(){ mSend('请分析当前  盘面并给出完整交易方案（方向/进场/止损/止盈/仓位）', false); });
  el('btnStruct').addEventListener('click', function(){ mSend('当前盘面是什么结构？W底、M顶还是区间震荡？依据是什么？', false); });
  el('btnRisk').addEventListener('click', function(){ mSend('如果按你给的方案执行，失效条件是什么？什么情况说明判断错了？', false); });
  el('newsToggle').addEventListener('click', function(){ withNews = !withNews; this.classList.toggle('act', withNews); });
})();
</script>
</body>
</html>
"""
