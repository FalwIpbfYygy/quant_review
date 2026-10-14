# -*- coding: utf-8 -*-
"""
quant_review 统一配置层（单一事实来源 / single source of truth）。

设计原则（上线 GitHub 前必须满足）：
  - 所有密钥 / 代理 / 端点 / 数据库连接一律从「环境变量」读取，源码内禁止任何明文。
  - 本地开发：复制 `.env.example` 为 `.env` 填入真实值（`.env` 已被 .gitignore 忽略，不会上传）。
  - 部署到服务器：通过环境变量 / secrets 注入，不依赖 .env 文件。

迁移说明（2026-10-12 隐私清理）：
  - 旧版把 BAILIAN_API_KEY / TWELVEDATA_API_KEY / JIN10_TOKEN / FEISHU_WEBHOOK /
    BAILIAN_WORKSPACE_ID 等明文写死在源码，已全部移除，改为纯环境变量。
  - 旧版多处硬编码本地代理 ，现已统一为「默认直连」：
    本地 Windows 出网需要代理时，在 .env 设 KLINE_PROXY=
    （或沿用标准环境变量 HTTP_PROXY / HTTPS_PROXY）即可，源码不再保留任何代理地址。
"""
import os


def _load_dotenv(path=".env"):
    """极简 .env 加载器（零第三方依赖）。仅当环境变量尚未设置时才写入，避免覆盖 shell 注入。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                k, v = k.strip(), v.strip().strip('"').strip("'")
                if k and k not in os.environ:
                    os.environ[k] = v
    except FileNotFoundError:
        pass


_load_dotenv()


def _env(name, default=""):
    return os.environ.get(name, default)


# ───────────────────────────── 数据库 ─────────────────────────────
DB_HOST = _env("DB_HOST", "localhost")
DB_USER = _env("DB_USER", "root")
DB_PASS = _env("DB_PASS", "")
DB_NAME = _env("DB_NAME", "")

# 周期数据表映射（非敏感，保留为常量即可）
TABLE_MAP = {
    "1m": "kline_1m",
    "5m": "kline_5m",
    "15m": "kline_15m",
    "30m": "kline_30m",
}

TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
DATE_FORMAT = "%Y-%m-%d"

# ─────────────────────── 阿里云百炼（大模型复盘） ───────────────────────
# 密钥必须来自环境变量；仓库内不设任何默认值（旧版明文 sk-... 已删除）。
# 兼容 DASHSCOPE_API_KEY 别名。
BAILIAN_API_KEY = _env("BAILIAN_API_KEY") or _env("DASHSCOPE_API_KEY")
# 私有业务空间 ID（仅用于拼网关 URL，非密钥，但也不应写死源码）。
BAILIAN_WORKSPACE_ID = _env("BAILIAN_WORKSPACE_ID")
# 兼容 OpenAI 接口的网关地址：优先用显式 BAILIAN_BASE_URL，其次按 workspace 拼，再回退公共 DashScope。
BAILIAN_BASE_URL = _env("BAILIAN_BASE_URL") or (
    f"https://{BAILIAN_WORKSPACE_ID}.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
    if BAILIAN_WORKSPACE_ID
    else "https://dashscope.aliyuncs.com/compatible-mode/v1"
)
BAILIAN_MODEL = _env("BAILIAN_MODEL", "qwen3-max")

# ─────────────────────────── 金十 MCP ───────────────────────────
JIN10_URL = _env("JIN10_URL", "")
JIN10_TOKEN = _env("JIN10_TOKEN")
JIN10_PROTOCOL = _env("JIN10_PROTOCOL", "2025-11-25")

# ───────────────────────── Twelve Data ─────────────────────────
# xau_macro 链路用的 key
TWELVEDATA_API_KEY = _env("TWELVEDATA_API_KEY")
# huntzone / huntv2 链路用的 key（两处原本各写一份明文，现统一到此）
TWELVE_KEY = _env("TWELVE_KEY")
TD_BASE = _env("TWELVE_BASE", "")
TWELVE_API = _env("TWELVE_API", "/time_series")

# ───────────────────────── 飞书机器人 ─────────────────────────
# huntzone 复盘推送用
FEISHU_WEBHOOK = _env("FEISHU_WEBHOOK")
# 每月脉冲推送用
FEISHU_MC_WEBHOOK = _env("FEISHU_MC_WEBHOOK")

# ─────────────────────── 价格数据源端点（完全可配置） ───────────────────────
# 重要：本项目「不内置任何中心化交易所地址」。
# 请在你自己的 .env 中配置下面两个基址——可以是自建代理、你信任的交易所 API
# 或任何兼容 Binance 合约/现货 REST 格式的行情源：
#   BINANCE_FAPI_BASE = https://你自己的期货行情接口基址
#   BINANCE_SPOT_BASE = https://你自己的现货行情接口基址
# 不配置则无法拉取行情（这样可避免把任何硬编码域名写入源码，使用者自行决定数据源）。
BINANCE_FAPI_BASE = _env("BINANCE_FAPI_BASE")
BINANCE_SPOT_BASE = _env("BINANCE_SPOT_BASE")
# 由基址拼出的 K 线端点；基址未配置时留空字符串，由调用方在真正请求前再校验。
FAPI_KLINES = f"{BINANCE_FAPI_BASE}/fapi/v1/klines" if BINANCE_FAPI_BASE else ""
SPOT_KLINES = f"{BINANCE_SPOT_BASE}/api/v3/klines" if BINANCE_SPOT_BASE else ""

# ───────────────────────────── 代理 ─────────────────────────────
# 默认直连（符合线上零代理纪律）。
# 本地 Windows 出网需代理 → 在 .env 设 KLINE_PROXY=
#   或设置标准环境变量 HTTP_PROXY / HTTPS_PROXY。
# 不设置任何代理变量 = 直连；设为空串也 = 直连。
def _build_proxies():
    p = _env("KLINE_PROXY")
    if p:
        return {"http": p, "https": p}
    hp = _env("HTTPS_PROXY") or _env("https_proxy") or _env("HTTP_PROXY") or _env("http_proxy")
    if hp:
        return {"http": hp, "https": hp}
    return None


PROXIES = _build_proxies()
