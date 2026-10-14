# 排错：LLM 空回复 —— glm-5.2 推理模型 reasoning_tokens 吞噬 token 预算

> 记录一次 `/mindmap` 行情对话「AI 完全不生成回复」的完整排查与修复。
> 结论先行：**根因不是前端渲染、不是路由、不是接口报错，而是 `glm-5.2` 是推理模型（thinking/reasoning 类），`reasoning_tokens` 把整个 `max_tokens` 预算吃光，`content` 永远为空字符串。**

---

## 1. 背景

- `/mindmap` 的「行情对话」tab 接 LLM 做  真实行情分析：多周期取数（Binance fapi ）→ 算客观事实 → BM25 检索规则 → LLM 出观点，前端用 Markdown 渲染。
- LLM 配置统一走 `xau_mindmap.py: llm_config()`，读 `config.BAILIAN_API_KEY / BAILIAN_BASE_URL / BAILIAN_MODEL`。
- 用户曾自行把 `config.BAILIAN_MODEL` 从 `kimi-k2.7-code` 改成 `glm-5.2`（config.py 注释里保留了多个候选模型）。
- `market_chat()` 位于 `xau_mindmap_market.py:390`，调用时 `max_tokens` 默认 `1600`。

---

## 2. 症状（用户截图原话）

行情对话发了两条问题，AI 回复区**全程空白**：

- 顶部有「📊 查看客观盘面事实」折叠按钮（说明 `d.facts_text` 有值）
- 有规则 chips（`d.sources` 有 6 条，说明 BM25 检索正常）
- 有 meta 行（`模型 glm-5.2`、`耗时 42s / 37s`、`引用规则 6 条`）
- **唯独 `d.answer`（LLM 文字回复）整段缺失**

即：**LLM 调到了、规则引到了、耗时算到了，但 AI 文字一个字都没出来**。

---

## 3. 根因（关键）

**`glm-5.2` 是推理模型，把 `max_tokens` 预算全花在内部「思考（reasoning）」上，留给 `content` 的 token 为 0。**

链路：

1. `market_chat()` 真实跑通：取数成功 → facts 有真实行情数据 → 拼出长 prompt → 调 LLM。
2. glm-5.2 拿到真实数据后疯狂推理，`reasoning_tokens` 一路涨到顶满 `max_tokens`。
3. 预算耗尽，`finish_reason='length'`，`content` 是空字符串 `""`。
4. 前端 `if (d.answer)` 判断 falsy → 整段跳过 → 用户看到空白。

**为什么 mock 场景能返回、真实场景返回空？**

- 早期自测用「mock fetch 全失败」时，facts 全是占位、`facts_text` 很短，LLM 几乎无需推理，`reasoning_tokens` 极少，剩余 token 全给 content → 返回 840 字符，骗过了测试。
- 真实场景 facts 有完整行情，触发重度推理 → 预算全被吃掉 → 空字符串。**测试假象掩盖了真 bug。**

### 证据表（带 `usage.completion_tokens_details.reasoning_tokens`）

| max_tokens | reasoning_tokens | content 长度 | finish_reason | 结果 |
|---|---|---|---|---|
| 1600 | 1600 | **0** | length | ❌ 用户截图完全复现 |
| 4096 | 4096 | 0 | length | ❌ 仍空 |
| 16384 | — | — | — | ❌ API 拒绝（SIGTERM） |
| kimi-k2.7-code / 4096 | **302** | 完整 | stop | ✅ 正常 |

> 对照：非推理模型（kimi / qwen3-max）`reasoning_tokens` 极少（~300），`content` 完整返回。

---

## 4. 诊断三步（推理模型踩坑通用判据）

看到「LLM 调用成功但 content 为空」时，查返回结构：

1. 看 `resp.usage.completion_tokens_details.reasoning_tokens` —— 不为 0 即可疑（接近 max_tokens 即坐实）；
2. 看 `finish_reason` —— 等于 `'length'`（预算耗尽截断）；
3. 看 `resp.choices[0].message.content` —— 等于 `""`。

**三者齐备 = 踩中推理模型 token 预算陷阱。** 调大模型 + 加大 max_tokens 通常无效（如本例 1600→4096 仍空，16384 直接被拒），应换非推理模型或对推理模型单独约束。

---

## 5. 修复

| # | 改动 | 文件 | 说明 |
|---|------|------|------|
| 1 | `BAILIAN_MODEL = "kimi-k2.7-code"`（glm-5.2 注释保留） | `config.py` | 换回非推理模型，已实测真实场景 42s 内返回 ≥1500 字符标准交易方案 |
| 2 | `market_chat(..., max_tokens: int = 4096)` | `xau_mindmap_market.py:390` | 给长 prompt + 长回答留余量（kimi 也需安全空间） |
| 3 | 空 answer 时显示降级提示（「AI 本次未输出文字…」） | `xau_mindmap_template.py:481` | 即使再遇空也不静默吞，给明确反馈而非空白黑洞 |

---

## 6. 验证（按「先测试后报告」纪律全跑）

临时自检脚本（mock LLM/网络，跑完即删，不留项目垃圾）：

- ✅ 静态断言：3 处改动落地（config 生效 / max_tokens=4096 / 前端降级提示已加）
- ✅ Python 语法解析：5 个核心文件（`config / xau_mindmap / xau_mindmap_market / xau_mindmap_template / main`）`ast.parse` 通过
- ✅ `llm_config().model == 'kimi-k2.7-code'` 生效
- ✅ **真实端到端 × 2**（用 `main._fapi_fetch` 真实取数 + 真实 kimi）：
  - 「请分析当前  盘面并给出完整交易方案」→ answer **1565 字符**，含 `## 一、盘面定性`、`4h E 冲底失稳`、颈线 4385.30、M顶/孕线/平顶 等结构化内容
  - 「失效条件是什么…」→ answer **1554 字符**，含 `##` 结构 + 「失效」关键词
- ✅ 关键判据：`len(ans) > 200` 且 `'##' in ans` → 从空（0）修复到完整 Markdown

---

## 7. 防呆约定（经验沉淀）

- **推理模型（glm-5.2 / deepseek-r1 / o1 类）默认不在交易行情对话链路使用**，除非显式论证其 reasoning 价值 > 空回复风险。
- LLM 接入层统一加「空 answer 降级提示」闸门，杜绝「AI 没回复」式体验黑洞。
- **警惕 mock 全失败的自测假象**：推理模型在「无真实数据可推理」时 content 正常，真实数据下反而空——自测必须包含「真实取数 + 真实模型」的端到端用例。
- 模型切换后必须跑一次真实端到端（看 `usage.reasoning_tokens` / `finish_reason` / `content`），不能只看「调用没报错」就交付。
