# /review 页面「形态/架构」多选改造 · PRD（评审稿）

> 项目：`D:\quant_review`
> 关联页面：`review.html`（前端原生 Vue3，无构建）
> 版本：v0.1（评审稿，待用户审核签字后进入开发）
> 状态：**已开发完成（2026-09-29），仅前端 `review.html` 单文件改动，三道闸 ALL PASS**
> 约束：纯前端改动；后端 `/api/backtest`、`/api/backtest/binance` 不改；回测结果口径不变

---

## 1. 背景与目标

`/review` 当前有两处「形态/架构」相关的筛选器，都是**单选 `<select>`**：

- **A 回测前过滤**（参数行，标签「形态/架构」）：决定哪些信号送进回测。选了某形态 → ②④⑤⑥⑦ 全部只反映该形态。
- **B ⑥仅显示过滤**（⑥逐笔交割单表头，标签「只看形态」）：回测照全跑，只在 ⑥ 表格里按形态隐藏行。

现状痛点：只能选**一个**形态。用户想一次对比多个形态（例如同时看 `MSS` + `FVG` + `OB` 的合计表现），必须反复重跑或反复切。

**目标**：把两处都改成**多选**，可勾选任意数量形态组合，支持「全选 / 清空」语义，且不破坏现有默认行为（不选 = 全部）。

---

## 2. 现状审计（代码级溯源）

| 项 | 位置（review.html） | 当前实现 |
|----|--------------------|----------|
| A 模型 | L746 `const patternFilter = ref('all')` | 字符串，默认 `'all'` |
| A 选项 | L747-751 `patternOptions` | 从粘贴信号去重得到的形态列表 |
| A 控件 | L294-299 `<select v-model="patternFilter">` | 单选下拉，含「全部形态」+ 各形态 |
| A 过滤逻辑 | L752-755 `filterByPattern()` | `row.pattern === patternFilter.value` 精确相等 |
| A 调用点 | L780 / L810 `filtered = filterByPattern(filtered)` | 在 `runBacktest` / `runBacktestBinance` 回测前过滤 |
| B 模型 | L756 `const patternViewFilter = ref('all')` | 字符串，默认 `'all'` |
| B 选项 | L757-761 `patternViewOptions` | 从回测结果 trades 去重得到的形态列表 |
| B 控件 | L404-410 `<select v-model="patternViewFilter">` | 单选下拉，含「全部」+ 各形态 |
| B 过滤逻辑 | L762-765 `filteredTrades` | `t.pattern === patternViewFilter.value` 精确相等 |
| 暴露 | L1079 `return {}` | 已暴露 `patternFilter/patternOptions/patternViewFilter/patternViewOptions/filteredTrades` |

**关键结论**：
1. 两处都是「单字符串 === 单值」匹配，改为「数组 includes 多值」即可支持多选。
2. 信号在**送后端前**已被前端 `filterByPattern` 过滤（L780/810），后端收到的已是子集 → **后端零改动**。
3. 改动范围严格限定在 `review.html` 一个文件（模型 + 控件 + 过滤函数 + `return{}` 暴露）。

---

## 3. 范围

**In Scope**
- A（参数行「形态/架构」）从单选改为多选
- B（⑥「只看形态」）从单选改为多选
- 多选的「全选 / 清空」语义与默认行为（不选 = 全部）
- UI 控件替换为多选交互

**Out of Scope（本期不做）**
- 后端接口改动
- 回测算法 / 统计口径改动
- 新增「形态组合」作为新分组维度的聚合统计（如需，另立 PRD）
- 跨页（index/replay/realtime/ai_history）改动

---

## 4. 方案设计

### 4.1 数据模型变更

| 变量 | 改前 | 改后 | 默认语义 |
|------|------|------|----------|
| `patternFilter` (A) | `ref('all')` 字符串 | `ref([])` 数组 | 空数组 = 全部形态 |
| `patternViewFilter` (B) | `ref('all')` 字符串 | `ref([])` 数组 | 空数组 = 全部 |
| `patternOptions` / `patternViewOptions` | 不变（仍是去重后的字符串列表） | 不变 | — |

### 4.2 过滤逻辑变更

```js
// A：回测前过滤（替换 L752-755）
const filterByPattern = (signals) => {
    if (!patternFilter.value.length) return signals               // 空 = 全选
    const set = new Set(patternFilter.value)
    return signals.filter(row => set.has(row.pattern))
}

// B：⑥仅显示过滤（替换 L762-765）
const filteredTrades = computed(() => {
    if (!patternViewFilter.value.length) return trades.value      // 空 = 全选
    const set = new Set(patternViewFilter.value)
    return trades.value.filter(t => set.has(t.pattern))
})
```

> 语义保持：默认空数组 → 与现版 `'all'` 行为完全一致（全部）；勾选 N 个 → 仅这 N 个。

### 4.3 UI 控件（需用户拍板，见第 6 节决策点）

**候选方案 1（推荐 · Pill 胶囊多选组）**
- 沿用现有 `.range-tabs` iOS 分段控件视觉，做成可多选的胶囊：
  - 首个胶囊固定为「全部形态 / 全部」：选中态 = 当前未勾选任何具体形态；点击它 = 清空所有勾选（回到全选）。
  - 其余每个形态一个胶囊，点击切换「选中/取消」。
- 优点：与现有时间范围 tab 视觉统一、直观、无需弹层。
- 风险：若信号表去重后形态数量很多（>8），会换行占竖向空间——可接受（参数行本就 flex 换行，range-tabs 已占一行）。

**候选方案 2（多选下拉 + 复选框）**
- 按钮显示「已选 N 个 / 全部」，点击展开 checkbox 列表，勾选后收起。
- 优点：形态很多时布局不膨胀，控件紧凑（尤其适合 ⑥ 表头右侧的窄位）。
- 缺点：需手写 popover/点击外部收起逻辑，代码量略大。

**候选方案 3（原生 `<select multiple>`）**
- 改动最小，但 Ctrl+多选交互反直觉、样式难统一，**不推荐**，仅作降级备选。

> 推荐：A（参数行，横向空间宽）用**方案 1 胶囊组**；B（⑥表头右侧，空间窄）用**方案 2 多选下拉**，保证两处都多选且各自最顺手。若用户要求两处完全一致，则统一用方案 1。

### 4.4 返回暴露（return{}）

`return {}`（L1079）需同步：模型已是 `ref`/`computed`，变量名不变，**无需新增暴露项**，仅确保新控件绑定的事件/计算属性都已在 return 中（改造后用 inline-vue-html-guard 三道闸校验，防静默失效）。

---

## 5. 默认行为与边界（明确口径，避免歧义）

1. **空选 = 全部**：进页面、未勾任何形态 → 与现版完全一致（全部信号 / 全部交割单）。
2. **「全部」胶囊**：当无任何具体形态被勾选时高亮；点击任一具体形态 → 取消「全部」高亮并加入该形态；再次点击该具体形态 → 取消；全部取消后自动回到「全部」高亮。
3. **与「时间范围」tab 独立叠加**：A 的多选形态 与 时间范围 tab 是「与」关系（先切时段、再按形态集合过滤），逻辑层已是 `filterByRange → filterByPattern` 链式，天然兼容。
4. **parseHint（可选增强 👉）**：现有提示「已解析 X 条 → 时段筛选后 Y 条」，可追加「→ 形态筛选后 Z 条」让多选结果可见。是否做待定。
5. **AI 复盘（genAiReport）**：基于 `lastResult`（= 已过滤信号的回测结果），A 多选后 AI 报告自动只覆盖所选形态，**无需改动**。

---

## 6. 需用户拍板的决策点（对齐用）

| # | 决策 | 推荐 | 备注 |
|---|------|------|------|
| D1 | A、B 是否**都**改多选？ | 都改 | 用户原话「之前的版本只能选一个」，两处均单选，建议统一 |
| D2 | 多选 UI 风格 | A=胶囊组 / B=多选下拉（或两处统一胶囊组） | 见 4.3 |
| D3 | parseHint 是否追加「形态筛选后 Z 条」 | 做（低成本高可见性） | 可选 |
| D4 | 是否保留「全部」作为独立可点胶囊（而非仅靠空选表示全选） | 保留 | 更直观，防止用户以为没选就失效 |

---

## 7. 验证清单（开发后必过，不二过）

1. `node --check` 内联 JS 语法 PASS。
2. **inline-vue-html-guard 三道闸**跑 `review.html` 全绿（句法 / 解构 / 模板↔暴露一致性）——重点防多选控件漏暴露导致静默失效。
3. 浏览器真实验证核心流程：
   - 默认空选 → 回测结果与现版一致（全部）；
   - 勾选 2 个形态 → ②④⑤⑥ 只含这 2 个；⑥ 表格行数 = 这 2 个形态之和；
   - B 多选 → ⑥ 表格只显示所选，②④⑤ 不变（B 不影响回测）；
   - 勾「全部」→ 回到全选；
   - 与时间范围 tab 叠加 → 正确求交。
4. 开 Console 确认无红色报错（尤其多选控件绑定）。
5. 纯前端改动，只需硬刷新浏览器，**无需重启 8000 进程**。

---

## 8. 交付文件清单

| 文件 | 改动 |
|------|------|
| `review.html` | 唯一改动文件：A/B 模型改数组、过滤逻辑改 `includes`、控件换多选交互、`return{}` 核对 |
| `docs/PRD_review_形态多选.md` | 本文档 |
| （无）`main.py` / `backtest.py` / `binance_src.py` | **不改** |

---

## 9. 一句话结论

把 `review.html` 里 A（参数行）与 B（⑥表头）两处「形态/架构」单选 `<select>` 改为多选（模型 `ref('all')`→`ref([])`、匹配 `===`→`includes`、控件换多选交互），**纯前端、后端零改动、默认行为不变**，改动限定单文件，开发后用 inline-vue-html-guard + 浏览器真实验证兜底。
