# Business App

这一层是面向业务逻辑的独立服务，运行在 `platform` 之上。

## 结构

- `platform_sdk.py`: 对 `platform/API.md` 中 `app` 可用的 REST 和 WebSocket 做统一封装
- `scheduler.py`: 主线程调度器，负责统一事件队列、事件缓存、cron 定时事件、功能线程激活
- `http_api.py`: 根据功能文件声明动态生成 POST HTTP 入口
- `features/`: 扁平化功能目录；每个功能一个独立文件
- `feature_loader.py`: 自动发现 `features/*.py` 中声明的功能
- `main.py`: FastAPI 启动入口

## 事件源

- `platform` WebSocket 事件
- 统一 cron 定时器事件（功能文件内声明 cron 表达式）
- HTTP 触发事件（功能文件内声明 URL 与 Pydantic 参数模型，统一 POST）

## 调度模型

每个功能为一个独立协程工作线程：

- 初始化时注册一个或多个激活事件
- 主调度器阻塞等待统一事件队列
- 收到事件后缓存最新事件，并遍历订阅者
- 若功能线程空闲，则投递激活事件
- 若功能线程忙碌：
  - `dedupe`: 忽略执行期间的新激活
  - `queue`: 暂存事件，待本轮执行结束后再处理

## 启动

```bash
cd app
..\.conda\python.exe -m uvicorn app.src.main:app --host 0.0.0.0 --port 9000 --reload
```

## HTTP 入口

- `GET /app/health`
- `POST /app/commands/execute`
- `POST /app/gpio/snapshot`

HTTP 参数校验失败时统一返回 `503`。

## 新增功能

在 `features/` 下新增一个 `.py` 文件即可被开发服务器热加载检测到。文件内声明：

- `ENABLED = True | False`：功能开关
- `FEATURE = FeatureSpec(...)` 或 `get_feature() -> FeatureSpec`
- `subscriptions`：统一订阅声明，platform / internal / timer / http 都在这里定义

不需要再修改聚合型 `base.py`。
