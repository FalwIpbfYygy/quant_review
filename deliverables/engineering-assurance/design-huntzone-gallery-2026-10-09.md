# 狩猎区场景轮播/滑动页 · 工程保障整合报告

**日期**：2026-10-09
**工作流**：系统设计（SOP 2）+ 需求基线 + 测试策略
**参与成员**：architect-2（设计）、tech-writer-2（PRD）、testing-expert-2（测试计划）

---

## 📌 TL;DR（执行摘要）

- 在保留现有 `/huntback` 单日下钻页前提下，新增 **`/huntzone-gallery` 多交易日滑动画廊**，复刻用户 MT4 截图的「连续多日 hunting zone ladder」观感。
- 数据面已锁定（D1）：不新建 `huntback_core.py`（仓库中不存在，Glob/Grep 核实）；新增 `huntzone_gallery_core.py` 作**唯一 import** 编排层，内部复用 `huntback_sim.py`（零改）+ `huntv2_core` + `db`。
- 三件套（PRD / 设计 / 测试计划）+ **可点击 HTML 效果图**（`huntzone_gallery_mockup.html`）均已落盘；几何/P&L 经 node 复算与 `huntback_sim.py` 一致。
- 待用户拍板 D2–D5 决策点后进入开发。

---

## 🎯 核心结论卡片

| 项目 | 内容 |
|------|------|
| 整体评级 | 🟡 有条件通过（方案完整，待用户签字进入开发） |
| 阻塞项数量 | 0（D1 已闭环；D2–D5 为可选配置，不阻塞 MVP） |
| 关键行动项 | 4 条决策点（D2–D5）+ 实施清单 |
| 建议下一步 | 用户确认 D2–D5 → 落地 `huntzone_gallery_core.py` + `template.py` + 3 路由 |

---

## 设计要点（architect-2 · design-huntzone-gallery-2026-10-09.md）

- 路由 `/huntzone-gallery`；横向 `scroll-snap` + 极简 vanilla JS（◀/▶ 按钮、指示点、`IntersectionObserver` 懒渲染）；**禁用图表内横向 dataZoom** 避免手势冲突。
- 每屏 = 1 天：头部(日期/方向徽章/状态/trigger) → 1h 聚合 K线(红涨绿跌) → 9 档斐波那契阶梯线 + 绿/粉 zone 色带 → 方向箭头 → 8 类事件标记 → 三区 P&L 面板 → 事件时间线 → 「看 1m 细部」开关。
- 性能：懒渲染使活跃 ECharts 实例 ≤3（200 天不爆内存）；默认 1h 粒度，1m 仅按需单日拉取。
- API：`/api/huntzone-gallery/slides`（整段 1 次请求）+ `/api/huntzone-gallery/day`（按需 1m 下钻），共用 L1 缓存 `(date,trigger,symbol)`。

## 数据面决策（D1 闭环）

- `huntback_core.py` **不存在**（已核实）；改用 `huntzone_gallery_core.py` 新编排层作页面唯一 import。
- `hz_engine.LADDER`（10 档含 0.809）与 MT4 9 档对应；`lad["levels"]` 价格已算好，画廊直接消费，**零重算**。
- 严格因果/零未来函数继承自信念内核 `huntback_sim`（仅用 ≤D-open 已收盘数据、1m 升序前向扫描）。

## 测试策略（testing-expert-2 · testplan-huntzone-gallery-2026-10-09.md）

- 金字塔分层：内核补缺口(单元) → 编排(单元) → 前端滑动/事件(单元) → FastAPI(集成) → E2E 视觉 → 性能边界。
- **P0 卡死项**：G1 long 方向覆盖、G2 公共 API 测试、G3 无未来函数移位不变式。
- 对齐 PRD §7 AC-1~4（可溯源/视觉/流畅/不二过）与 design §11（状态机、≤3 实例、错误码消费）。

## 风险

- **进行中当日**：复用 22:30(UTC14:30) `force_close` 封口；默认 `end`=最新已收盘日规避前瞻。
- **数据缺失**：逐日 status 机(ok/no_signal/missing/incomplete/live_only)，缺失日占位卡不崩整列、绝不静默造假。
- **性能**：懒渲染 + ≤3 实例；首屏不下发 1m 全量（200 天 ≈ <600KB@1h）。

---

## ✅ 行动清单（待用户拍板）

| # | 行动 | 负责角色 | 紧急度 | 预期完成 |
|---|------|---------|--------|---------|
| 1 | D2 路由名确认：`/huntzone-gallery` 或 `/huntback/gallery` | 用户 | P0 | 签字 |
| 2 | D3 阶梯是否含 80.9 档（默认仅 9 档） | 用户 | P1 | 签字 |
| 3 | D4 案例选择器形态（日历热力+权益曲线作入口） | 用户 | P1 | 签字 |
| 4 | D5 默认纳入天数（最近 30 个有信号日） | 用户 | P1 | 签字 |
| 5 | 进入开发：`huntzone_gallery_core.py` + `template.py` + 3 路由（纯新增、引擎零改） | 工程师 | P0（签字后） | — |

---

## ⚠️ 待完善 / 已知局限

- 真实页图表层用 **ECharts**（mockup 用轻量 SVG 演示零依赖，几何已对齐）。
- 完整 200 天虚拟化滚动为二期优化（N≤~60 无需虚拟化）。
- 80.9 档展示待 D3 拍板（渲染 `lad.levels` 子集即可）。

---

## 📚 数据来源 & 成员产出索引

- architect-2 设计草案：`D:/quant_review/docs/design-huntzone-gallery-2026-10-09.md`
- tech-writer-2 PRD（已按 D1 决议修订）：`D:/quant_review/docs/PRD-huntzone-gallery-2026-10-09.md`
- testing-expert-2 测试计划：`D:/quant_review/docs/testplan-huntzone-gallery-2026-10-09.md`
- 可点击效果图：`D:/quant_review/huntzone_gallery_mockup.html`
- 既有 `/huntback` 效果图（保留不改）：`D:/quant_review/huntback_mockup.html`

---

> 本报告由工程保障团队 AI 协作生成，关键决策请由人类工程负责人复核。
