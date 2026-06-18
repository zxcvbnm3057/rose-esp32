# Feature 模块编写说明

功能模块统一放在 `app/src/features`。

支持两种形态：

1. **单文件模块**
   - 例如：`app/src/features/gpio_snapshot.py`
2. **目录模块（包）**
   - 例如：`app/src/features/my_feature/__init__.py`
   - 若功能较复杂，可在该目录下继续拆分 `models.py`、`service.py`、`handlers.py` 等文件

系统会自动扫描 `app/src/features` 下所有非 `_` 开头的模块或目录包。

---

## 必要导出

每个功能模块需要提供以下二选一：

- `FEATURE = FeatureSpec(...)`
- `get_feature() -> FeatureSpec`

如果一个目录包内部想做更复杂初始化，推荐使用 `get_feature()`。

---

## 开关

模块内建议声明：

```python
ENABLED = True
```

然后：

```python
FEATURE = FeatureSpec(
    name="demo_feature",
    enabled=ENABLED,
    subscriptions=[
        EventSubscription("uart_rx", DeliveryMode.QUEUE, handler=handle),
    ],
)
```

关闭后会被自动跳过注册。

---

## 文件头说明

每个功能都应在入口文件头部补充说明注释：

- 单文件 feature：写在对应 `.py` 文件头部
- 目录包 feature：写在 `__init__.py` 文件头部

建议至少写清：

- 功能用途
- 暴露的触发方式或接口路径
- 关键请求参数
- 调用了哪些外部能力（如 UART、signal_tx、platform command 等）

推荐参考 `app/src/features/light_switch.py` 的写法，保持统一风格，便于后续维护和快速阅读。

---

## 最小示例（单文件）

```python
from __future__ import annotations

import logging
from app.src.models import FeatureContext, FeatureSpec, EventSubscription, DeliveryMode

ENABLED = True
logger = logging.getLogger(__name__)


async def handle(context: FeatureContext) -> None:
    logger.info("event=%s payload=%s", context.activation.event_type, context.activation.payload)


FEATURE = FeatureSpec(
    name="demo_feature",
    enabled=ENABLED,
    subscriptions=[
        EventSubscription("uart_rx", DeliveryMode.QUEUE, handler=handle),
    ],
)
```

---

## 目录模块示例

目录结构：

```text
app/src/features/my_feature/
├─ __init__.py
├─ handlers.py
└─ schemas.py
```

`__init__.py`：

```python
from .handlers import handle
from app.src.models import DeliveryMode, EventSubscription, FeatureSpec

ENABLED = True

FEATURE = FeatureSpec(
    name="my_feature",
    enabled=ENABLED,
    subscriptions=[
        EventSubscription("uart_rx", DeliveryMode.QUEUE, handler=handle),
    ],
)
```

---

## 可声明能力

所有触发方式统一写在 `subscriptions` 中，只是 `source` 不同。

### 1. 订阅 platform / 内部事件

```python
subscriptions=[
    EventSubscription.platform("uart_rx", DeliveryMode.QUEUE),
    EventSubscription.platform("connection_change", DeliveryMode.DEDUPE),
]
```

### 2. cron 定时任务

```python
subscriptions=[
    EventSubscription.timer(
        event_type="timer.refresh",
        cron="*/1 * * * *",
        delivery_mode=DeliveryMode.DEDUPE,
    ),
]
```

当前 cron 为五段式：

```text
minute hour day month weekday
```

支持：

- `*`
- `*/n`
- `a`
- `a,b,c`
- `a-b`

### 3. HTTP POST 触发

```python
from pydantic import BaseModel
from app.src.models import EventSubscription

class ExecuteRequest(BaseModel):
    gpio: int

subscriptions=[
    EventSubscription.http(
        path="/gpio/snapshot",
        request_model=ExecuteRequest,
        delivery_mode=DeliveryMode.QUEUE,
        description="Read GPIO snapshot",
    ),
]
```

这会自动生成：

- `POST /app/gpio/snapshot`

参数校验失败时统一返回 `503`。

---

## Handler 约定

Handler 签名：

```python
async def handle(context: FeatureContext) -> None:
    ...
```

可用对象：

- `context.activation`：当前激活事件
- `context.platform`：统一 platform SDK
- `context.scheduler`：调度器
- `context.feature_name`：当前功能名

### 每个订阅必须声明 handler

`FeatureSpec` 没有「兜底 handler」，每个 `EventSubscription` 都必须通过
`handler=` 显式声明自己的处理器。这样一个 feature 可以为不同事件执行不同逻辑，
事件与处理器的对应关系一目了然：

```python
FEATURE = FeatureSpec(
    name="home_presence",
    subscriptions=[
        EventSubscription.platform("ble_peer_connected", handler=handle_peer_connected),
        EventSubscription.platform("ble_peer_disconnected", handler=handle_peer_disconnected),
        EventSubscription.platform("ble_peers_list", handler=handle_peers_list),
    ],
)
```

如果多个事件共用同一段逻辑，显式指向同一个函数即可：

```python
subscriptions=[
    EventSubscription.internal("home.away", handler=handle_home),
    EventSubscription.internal("home.arrive", handler=handle_home),
]
```

约束：

- 任一订阅缺少 `handler` 都会在注册（甚至构造 `FeatureSpec`）时直接报错
- 同一 feature 的多个 handler 由调度器串行执行（共享一个 worker），
  因此读写 feature 内部状态时无需额外加锁

如果需要在 feature 内发布内部事件，可以使用：

```python
await context.emit_event(
    event_type="internal.refresh",
    payload={"source": context.feature_name},
)
```

限制：

- 仍然是发布订阅模式，不直接点名调用某个 feature
- 如果该事件会命中当前 feature 自己的订阅，调度器会断言拦截，避免循环触发

如果需要延时处理，可以直接在功能内部自己 `sleep`，例如：

```python
import asyncio

await asyncio.sleep(0.5)
```

这里单位是秒，按 `asyncio.sleep()` 的标准语义处理。

---

## 外部接口

如需调用硬件能力，优先通过 `app/src/platform_sdk.py` 中已封装的平台接口访问，避免在 feature 内直接散落底层调用细节。

---

## 测试建议

- 仅做触发器声明、参数透传、简单注册装配的 feature，一般无需单独测试，可默认信任框架能力
- 如果 feature 内包含独立业务逻辑，例如解析、状态管理、映射转换、协议拼装等，则必须补充测试
- feature 的测试应放在对应 feature 目录内部，例如 `app/src/features/my_feature/test_feature.py`
- 不要把 feature 专属测试放到外层公共 `app/tests/` 目录中

---

## 设计建议

- 一个功能尽量只做一件事
- 简单功能优先单文件
- 复杂功能使用目录包
- 业务状态尽量局部化在模块内部
- 不要在功能线程内直接长时间阻塞
- 需要重入保护时用 `DeliveryMode.DEDUPE`
- 需要串行积压时用 `DeliveryMode.QUEUE`

---

## 热加载建议

开发时新增或修改 `app/src/features` 下的文件或目录，开发服务器应能检测到变更并重载。
因此建议：

- 新功能直接新增一个 `.py` 文件
- 若逻辑复杂，再改为目录包
- 保持入口在模块顶层可导入
