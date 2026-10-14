#  规则化量化复盘与日内决策系统（quant_review）

> 基于 FastAPI 的黄金（）K 线复盘、因果回测与日内决策工具。内置**严格因果回测引擎（杜绝未来函数）**、阿里云百炼 LLM 每日分析报告，以及狩猎区斐波那契档位引擎。

## ✨ 特性

- **因果回测引擎**：严格 `asof` 截断，信号形成全程不触碰未来数据；PDH/PDL 突破跟随、ATR 止损、1R/1.8R 分段止盈、半仓管理，含成本/滑点建模与月度收益分布。
- **LLM 每日分析**：聚合计划 + 宏观（6 外汇 ICE 公式合成 DXY）+ 金十消息面，生成每日 Markdown 报告（阿里云百炼兼容 OpenAI 接口）。
- **狩猎区斐波那契档位引擎**：纯计算、零人工输入自研腿、布防即锁定不复算；未验证策略强制带 `verdict/tradable` 风险警示，不隐去不确定性。
- **多页面复盘前端**：K 线复盘、狩猎区画廊、日内决策、心理记录等，前端依赖 **vendored 本地化**（ECharts / Marked / DOMPurify / Vue），**无构建步骤**。
- **零硬编码密钥**：所有密钥 / 代理 / 端点 / 数据库凭据均通过环境变量注入（`config.py`），源码不含任何明文凭据。

## 🧱 技术栈

- **后端**：Python 3.10+ / FastAPI / Uvicorn
- **数据**：Binance U 本位合约行情（`fapi`）、TwelveData、金十（jin10）、本地 MySQL
- **前端**：原生 HTML + ECharts + Marked + DOMPurify + Vue（CDN 本地化，无构建）
- **LLM**：阿里云百炼（兼容 OpenAI 接口）

## 📁 目录结构

```
quant_review/
├── main.py                 # 应用入口（FastAPI），启动即加载全部页面路由
├── config.py               # 统一配置层：从环境变量读取密钥/代理/端点/DB（零明文）
├── core/                   # 业务引擎层
│   ├── xau_report.py       #   ★ 每日计划核心引擎（asof 截断、未来函数闸门）
│   ├── wuyuan_core.py      #   ★ 乌圆自然数学派档位引擎（纯计算）
│   ├── backtest.py         #   本地库回测引擎
│   ├── xau_stage.py        #   周期阶段判定（真值源移植自 docs/t1.py）
│   ├── xau_mindmap*.py     #   思维导图 / 市场推演
│   ├── ai_report.py / ai_store.py / daily_report_ai.py / daily_plan.py  # LLM 报告与计划
│   └── psych.py / month_cal.py   # 心理记录 / 月度消息面日历
├── data/                   # 数据层
│   ├── db.py / data_sync.py      # MySQL 访问 / 行情同步
│   ├── binance_src.py / market.py # Binance 实时回测 / 市场总览
│   └── jin10.py / xau_macro.py / xau_news.py  # 金十消息面 / TwelveData 宏观(DXY 合成) / 新闻
├── huntzone/               # 狩猎区家族
│   ├── hz_engine.py / hz_signal.py  # ★ 斐波那契档位引擎 + 方向信号模型
│   ├── huntback_sim.py     #   狩猎区回测模拟器
│   └── huntv2_core.py / huntzone_*_core.py  # 各狩猎区页面/复盘核心逻辑
├── pages/                  # 页面模板（Python 内联 HTML 常量）
├── web/                    # 独立 HTML 页面（index/realtime/replay/review/market/psych/habits + mockups/）
├── research/               # 独立研究脚本（rs_backtest / rs_reversal_probe 反转探针）
├── docs/                   # 设计文档、PRD、排错记录、阶段判定真值源 t1.py、周期研判手册
├── tests/                  # pytest 单元测试（狩猎区引擎因果闸门等）
├── scripts/                # 工具脚本（服务管理 server_ctl / 数据解析 / 报告校验）
├── static/                 # 前端组件（topnav 等）
├── vendors/                # 第三方库（echarts/marked/purify/vue，本地化）
├── DataBase/               # MySQL 入库脚本
├── outputs/                # 生成的月度/日历报告
├── deliverables/           # 设计归档（engineering-assurance）
├── .env.example            # 环境变量模板（复制为 .env 后填入自己的密钥）
├── requirements.txt
└── LICENSE
```

## 🚀 快速开始

```bash
pip install -r requirements.txt
cp .env.example .env        # 填入你自己的密钥（.env 不会被提交）
python main.py              # 默认 http://localhost:8000
```

- **本地出网需代理**：在 `.env` 设 `KLINE_PROXY=`（默认直连，符合线上零代理纪律）。
- **数据源**：默认拉取 `` U 本位合约行情；宏观经 TwelveData，消息面经金十。

## 🔐 配置（.env）

参见 `.env.example`，主要字段：

| 变量 | 说明 |
|---|---|
| `DASHSCOPE_API_KEY` / `BAILIAN_API_KEY` | 阿里云百炼 API Key |
| `BAILIAN_BASE_URL` / `BAILIAN_WORKSPACE_ID` / `BAILIAN_MODEL` | 百炼网关、私有空间 ID、模型名 |
| `TWELVEDATA_API_KEY` | TwelveData Key |
| `JIN10_TOKEN` | 金十 MCP Token |
| `FEISHU_WEBHOOK` | 飞书机器人 Webhook（推送用） |
| `DB_HOST` / `DB_USER` / `DB_PASS` / `DB_NAME` | 本地 MySQL 连接 |
| `KLINE_PROXY` | 可选，本地出网代理地址 |

> 本项目**不含任何明文密钥**；克隆后必须自行配置 `.env` 才能启用 LLM / 数据库 / 推送等外部能力。

## 🧪 测试

```bash
pytest tests/
```

## ⚠️ 免责声明

本项目仅供**技术研究与个人复盘**使用。所有信号、报告、档位均为规则化算法的输出，**不构成任何投资建议**。量化交易存在重大风险，入市需谨慎，责任自负。

## 📄 License

[MIT](LICENSE)
