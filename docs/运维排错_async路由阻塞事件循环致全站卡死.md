# 运维排错：async 路由阻塞事件循环 → 一个页面生成中，全站卡死

> 记录一次「画廊生成中（生成中…），/huntzone-daily 白屏、其它 huntzone 页面全部卡死」的完整排查。
> 结论先行：**根因不是浏览器、不是代理，而是 6 条数据 API 路由是 `async def` 但内部直接同步调用阻塞函数（fapi 取数），把 uvicorn 的事件循环整个卡住——单线程事件循环被占死，所有请求排队。**

---

## 1. 症状

- `/huntzone-gallery` 点「生成」后按钮转圈（请求 30~90s）；
- 期间打开 `/huntzone-daily` / `/huntzone-review` / `/huntzone-review-xag` 一律白屏/卡死，直到画廊请求完成才恢复。

## 2. 根因（FastAPI/uvicorn 并发模型）

- uvicorn 是**单线程事件循环**。`async def` 路由在事件循环里直接执行；
- `async def` 内部出现**同步阻塞调用**（`requests.get`、urlopen、LLM HTTP 等）时，事件循环被卡住 → **全站所有请求（包括纯静态页面）都挂起**；
- 对照：main.py 里正确的既有范式是 `await asyncio.to_thread(阻塞函数)` 或把路由写成普通 `def`（FastAPI 自动丢进线程池，默认 40 线程，互不阻塞）。

## 3. 诊断脚本（一次扫出全部病灶）

对 main.py 每个 `async def` 路由取函数体，若**无 await 且有阻塞调用**（`= xxx.build_... / fetch_... / requests.` 等）→ 病灶。本次扫出 6 条：

```
L1336 /api/huntv2/ladder          L1391 /api/huntzone-gallery/slides
L1415 /api/huntzone-gallery/day   L1456 /api/huntzone-daily/data
L1523 /api/huntzone-review-xag/data  L1553 /api/huntzone-review/data
```

## 4. 修复（最小改动，语义零变化）

把 6 条路由的 `async def` → `def`。FastAPI 对 sync 路由自动走线程池，`response: Response = None` 注入、函数内 import 等写法全部兼容，不用改函数体。

**判别准则（沉淀）**：
> 路由里做阻塞 IO（requests/urlopen/LLM/重试循环）→ 要么 `def`，要么 `await asyncio.to_thread(...)`；**绝不允许 `async def` 里裸调阻塞函数**。纯返回常量/字符串的页面路由用 `async def` 没问题。

## 5. 验证（并发对照测试，Python 线程模拟）

长请求在跑的同时计时其它页面：

| 请求 | 修复前 | 修复后 |
|---|---|---|
| /api/huntzone-gallery/slides（长） | 82.9s 独占 | 82.9s 不受影响 |
| /huntzone-daily | 卡死直到长请求结束 | **HTTP 200，4ms** |
| /huntzone-review-xag | 卡死 | **200，19ms** |
| /huntzone-gallery | 卡死 | **200，5ms** |
| /huntzone-review | 卡死 | **200，26ms** |
| /api/huntzone-daily/data | 卡死 | **200，3.1s（自身取数耗时，未被阻塞）** |

## 6. 关联问题：启动方式再次踩线

排查中发现实例是 `python -m uvicorn main:app --reload` 起的——**docs《运维排错_8000端口双实例抢请求》已明确禁止**（绕过端口清理、fork 子进程占 socket、本机 --reload 一改代码就崩）。已按约定杀掉（含 fork 子进程），改用唯一推荐方式：

```bash
cd D:/quant_review && D:\sortware\python_3_10\python.exe main.py
```

## 7. 代理端口迁移备注（2026-10-10）

本地双 v2rayN，出口统一迁到 `127.0.0.1:10809`。取数代码（data_sync.PROXIES / huntzone_review_hs_data._LOCAL_PROXY / x26 脚本）已全部 10809；fapi 实测通。后续新代码写代理一律 10809，勿再引用旧 10808。
