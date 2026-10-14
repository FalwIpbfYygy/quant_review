// topnav.js — 共享顶部导航组件（单一权威数据源）
// 用法：
//   1) <link rel="stylesheet" href="/static/components/topnav.css">
//   2) <topnav-bar data-active="realtime"></topnav-bar>  （active 填当前页路径，比如 /  /replay /realtime /review /ai_history /psych /habits /market /xau）
//   3) <script src="/static/components/topnav.js" defer></script>
//
// 新增导航项只改这里 NAV 数组 → 所有页面自动同步，绝对不漏。
(function () {
  'use strict';

  // === 单一权威源：所有导航项在这里定义 ===
  // 每项：{ path, label, icon (24x24 SVG 内联) }
  var NAV = [
    { path: '/',          label: '四分屏复盘', icon: '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>' },
    { path: '/replay',    label: 'K线回放',    icon: '<polygon points="6 4 20 12 6 20 6 4"/>' },
    { path: '/realtime',  label: '实时图表',    icon: '<polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>' },
    { path: '/review',    label: '信号复盘',    icon: '<line x1="4" y1="20" x2="4" y2="10"/><line x1="10" y1="20" x2="10" y2="4"/><line x1="16" y1="20" x2="16" y2="14"/><line x1="20" y1="20" x2="20" y2="8"/>' },
    { path: '/ai_history',label: 'AI复盘库',    icon: '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>' },
    { path: '/psych',     label: '心锚',        icon: '<path d="M12 21s-7-4.5-9.5-9C1 9 2.5 5 6 5c2 0 3 1 4 2 1-1 2-2 4-2 3.5 0 5 4 3.5 7-2.5 4.5-9.5 9-9.5 9z"/>' },
    { path: '/habits',    label: '交易惯性',    icon: '<path d="M12 2.5 3.5 19.5a1 1 0 0 0 .88 1.5h15.24a1 1 0 0 0 .88-1.5L12 2.5z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>' },
    { path: '/market',    label: '市场看板',    icon: '<rect x="3" y="3" width="7" height="9"/><rect x="14" y="3" width="7" height="5"/><rect x="14" y="12" width="7" height="9"/><rect x="3" y="16" width="7" height="5"/>' },
    { path: '/xau',       label: ' 计划', icon: '<path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h14"/>' },
    { path: '/wuyuan',    label: '狩猎区',      icon: '<line x1="3" y1="5" x2="21" y2="5"/><line x1="3" y1="9.5" x2="21" y2="9.5"/><line x1="3" y1="14" x2="21" y2="14"/><line x1="3" y1="18.5" x2="21" y2="18.5"/>' },
    { path: '/huntv2',    label: '狩猎区v2',    icon: '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="4"/><line x1="12" y1="1" x2="12" y2="5"/><line x1="12" y1="19" x2="12" y2="23"/><line x1="1" y1="12" x2="5" y2="12"/><line x1="19" y1="12" x2="23" y2="12"/>' },
    { path: '/huntzone-gallery', label: '狩猎区画廊', icon: '<rect x="3" y="4" width="18" height="6" rx="1"/><rect x="3" y="14" width="18" height="6" rx="1"/>' },
    { path: '/huntzone-daily', label: '狩猎区30分', icon: '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>' },
    { path: '/huntzone-review', label: '狩猎区复盘', icon: '<g><rect x="3" y="3" width="18" height="7" rx="1"/><rect x="3" y="14" width="18" height="7" rx="1"/><line x1="3" y1="10.5" x2="21" y2="10.5"/></g>' },
    { path: '/huntzone-review-xag', label: '白银狩猎区', icon: '<path d="M12 2l3 7h7l-5.5 4 2 7L12 16l-6.5 4 2-7L2 9h7z"/>' },
    { path: '/mindmap',    label: '思维导图库',  icon: '<path d="M12 3v4"/><path d="M12 17v4"/><path d="M3 12h4"/><path d="M17 12h4"/><circle cx="12" cy="12" r="4"/><circle cx="6" cy="6" r="2"/><circle cx="18" cy="6" r="2"/><circle cx="6" cy="18" r="2"/><circle cx="18" cy="18" r="2"/>' }
  ];

  // 注册自定义元素
  if (customElements && customElements.define && !customElements.get('topnav-bar')) {
    var TopnavBar = function () {
      return Reflect.construct(HTMLElement, [], TopnavBar);
    };
    TopnavBar.prototype = Object.create(HTMLElement.prototype);
    TopnavBar.prototype.constructor = TopnavBar;
    TopnavBar.prototype.connectedCallback = function () {
      var active = (this.getAttribute('data-active') || location.pathname || '/').replace(/\/+$/, '') || '/';
      if (active.indexOf('/api/') === 0) active = '/';
      var html = '<nav class="topnav-links">';
      for (var i = 0; i < NAV.length; i++) {
        var n = NAV[i];
        var href = n.path;
        var cur  = href;
        var isActive = (active === cur) || (cur === '/' && active === '');
        html += '<a class="topnav-link' + (isActive ? ' active' : '') + '" href="' + href + '">'
              + '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round">' + n.icon + '</svg>'
              + '<span>' + n.label + '</span>'
              + '</a>';
      }
      html += '</nav>';
      this.innerHTML = html;
    };
    customElements.define('topnav-bar', TopnavBar);
  }

  // 兜底：对老式 <div id="topnav-mount"></div> 也注入（兼容历史页面）
  function mountFallback() {
    var mount = document.getElementById('topnav-mount');
    if (!mount) return;
    if (mount.dataset && mount.dataset.mounted === '1') return;
    var active = (mount.getAttribute('data-active') || location.pathname || '/').replace(/\/+$/, '') || '/';
    var html = '<nav class="topnav-links">';
    for (var i = 0; i < NAV.length; i++) {
      var n = NAV[i];
      var isActive = (active === n.path) || (n.path === '/' && active === '');
      html += '<a class="topnav-link' + (isActive ? ' active' : '') + '" href="' + n.path + '">'
            + '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round">' + n.icon + '</svg>'
            + '<span>' + n.label + '</span>'
            + '</a>';
    }
    html += '</nav>';
    mount.innerHTML = html;
    mount.dataset.mounted = '1';
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', mountFallback);
  } else {
    mountFallback();
  }
})();
