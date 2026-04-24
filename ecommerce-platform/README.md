# Ecommerce Platform

独立于仓库现有运行时的电商订单平台子项目，用于演示微服务、真实流量、统一日志、预埋故障与“根据 traceback 进行热修复”。

当前范围：

- 已实现订单、库存、支付、用户四个服务
- 已实现本地网关、监控大屏、持续流量模拟、统一 JSONL 日志、日志回放
- 已保留 `/api/agent/*` 接口契约与网关占位响应
- 不实现真实 Agent 修复、PR 自动化和飞书通知逻辑

## 目录

- `services/`: 四个 FastAPI 微服务与共享基础设施
- `scripts/local_gateway.py`: 本地网关和监控入口
- `scripts/traffic_simulator.py`: 双十一风格持续流量模拟器
- `scripts/replay_log.py`: 日志回放脚本
- `scripts/generate_log_dataset.py`: 百万级日志集生成器
- `logs/`: 统一运行日志、回放结果和离线数据集输出目录
- `contracts/agent-openapi.yaml`: `/api/agent/*` 预留契约

## 快速启动

1. 进入目录：`cd ecommerce-platform`
2. 准备环境：`cp .env.example .env`
3. 安装依赖：`python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`
4. 启动本地热重载栈：`bash scripts/run_local_reload_stack.sh`
5. 启动持续流量：`.venv/bin/python scripts/traffic_simulator.py --base-url http://127.0.0.1:58080`

如果默认端口被占用，启动脚本会自动改用空闲端口，并把实际端口写到 `.runtime/local-stack/ports.env`。

## 本地调试入口

- 网关首页：`/`
- 监控大屏：`/monitor`
- 监控摘要：`/api/monitor/summary`
- SSE 实时流：`/api/monitor/stream`
- 统一日志：`logs/ecommerce-debug.jsonl`

停止本地栈：

```bash
bash scripts/stop_local_reload_stack.sh
```

## 热修复演示流程

1. 启动本地热重载栈。
2. 打开 `.runtime/local-stack/ports.env`，确认实际网关端口。
3. 按需打开一个故障开关后重启对应服务，或直接在代码里临时改坏实现。
4. 通过浏览器、流量模拟器或日志回放触发请求。
5. 在 `logs/ecommerce-debug.jsonl` 中查看 `service_exception` 记录与完整 traceback。
6. 修改对应服务代码，`uvicorn --reload` 会自动热重载。
7. 再次触发同一路径，确认 500 消失、流量恢复正常。

## 预埋故障与 Traceback 类型

默认情况下全部关闭，系统可正常跑通并持续接流量。打开开关后才会进入故障路径。

| 开关 | 路径 | 主要异常 | 触发方式 |
| --- | --- | --- | --- |
| `BUG_INDEX_ERROR=true` | `services/order/service.py` | `IndexError` | `GET /api/v1/orders/user/{new_user}` |
| `BUG_ORDER_COUPON_KEY=true` | `services/order/service.py` | `KeyError` | `POST /api/v1/orders` 且使用未知 `coupon_code` |
| `BUG_RACE_CONDITION=true` | `services/inventory/service.py` | 并发超卖，常见业务异常为 `InsufficientStockError` | 高频并发下单 |
| `BUG_INVENTORY_MISSING_ROW=true` | `services/inventory/service.py` | `AttributeError` | `GET /api/v1/inventory/{BUG_INVENTORY_BROKEN_PRODUCT_ID}` |
| `BUG_FLOAT_PRECISION=true` | `services/payment/service.py` | 财务金额偏差，无 traceback，适合对账类问题 | `GET /api/v1/payments/calculate` |
| `BUG_PAYMENT_GATEWAY_KEY=true` | `services/payment/service.py` | `KeyError` | `GET /api/v1/payments/calculate?...&coupon_discount=10` |
| `BUG_NULL_VIP=true` | `services/user/service.py` | `TypeError` | 新注册用户后请求 `/api/v1/users/{id}/discount` |

推荐做修复演示时优先使用：

- `IndexError`
- `KeyError`
- `AttributeError`
- `TypeError`

这几类 traceback 更接近真实线上“代码改坏后直接 500”的场景。

## 日志

所有服务和本地网关都会把结构化事件写入统一 JSONL 文件，主要事件类型包括：

- `gateway_access`: 网关入口流量，包含正常流量、warning、error
- `service_request`: 服务侧请求完成记录
- `service_exception`: 服务侧未处理异常，包含 `exception_type` 和完整 `traceback`
- `*_warning`: 404/409/401/400 这类业务告警

日志适合两种用途：

1. 直接排障：从 `trace_id` 串联 gateway 和 service 记录
2. 离线回放：把历史 JSONL 重新打回网关

回放示例：

```bash
.venv/bin/python scripts/replay_log.py \
  --input logs/ecommerce-debug.jsonl \
  --base-url http://127.0.0.1:58080 \
  --limit 500
```

### 日志目录规则

`logs/` 整体已经加入 `.gitignore`，默认不提交任何运行日志、回放结果或离线数据集。

- `logs/ecommerce-debug.jsonl`: 本地网关和四个服务写入的统一运行日志
- `logs/replay-results.jsonl`: `scripts/replay_log.py` 的默认回放输出
- `logs/replay-*.jsonl`: 其他手工指定名称的回放结果
- `logs/datasets/<dataset-name>/manifest.json`: 数据集元信息，记录总量、分片和异常分布
- `logs/datasets/<dataset-name>/traffic-shard-01.jsonl` 到 `traffic-shard-XX.jsonl`: 按分片切开的原始 JSONL 流量

建议把每一批离线样本单独放到一个 `logs/datasets/<dataset-name>/` 目录里，不要混用不同批次的 `manifest.json` 和 `traffic-shard-*.jsonl`。

### 重新生成运行日志

运行日志不是离线脚本直接生成的，而是由真实请求自然写入：

```bash
bash scripts/run_local_reload_stack.sh
.venv/bin/python scripts/traffic_simulator.py --base-url http://127.0.0.1:58080
```

如果要重新开始一份干净的运行日志，可以先删掉旧文件：

```bash
rm -f logs/ecommerce-debug.jsonl logs/replay-results.jsonl logs/replay-*.jsonl
```

然后重新启动本地栈并重新打流量。

## 百万级日志集

如果需要大规模调试样本，可以生成新的百万级数据集：

```bash
.venv/bin/python scripts/generate_log_dataset.py \
  --output-dir logs/datasets/million-traffic-realistic \
  --gateway-records 1000000 \
  --shards 8 \
  --days 7 \
  --clean
```

目录命名建议：

- `logs/datasets/million-traffic-realistic`: 贴近当前服务真实 traceback 类型的数据集
- `logs/datasets/<date>-<purpose>`: 比如 `logs/datasets/2026-04-24-repair-drill`
- `logs/datasets/<dataset-name>/manifest.json` 一定和同目录下的 `traffic-shard-*.jsonl` 配套使用

如果要重建某一批数据集，直接删除对应目录后重新执行生成命令即可：

```bash
rm -rf logs/datasets/million-traffic-realistic
.venv/bin/python scripts/generate_log_dataset.py \
  --output-dir logs/datasets/million-traffic-realistic \
  --gateway-records 1000000 \
  --shards 8 \
  --days 7 \
  --clean
```

该数据集会同时包含：

- 正常流量
- warning 流量
- 带 traceback 的 error 流量
- 与真实故障路径一致的 `IndexError` / `KeyError` / `AttributeError` / `TypeError`

## 测试

```bash
pytest
```

## 预留接口

网关已经保留 `/api/agent/*` 路径，当前统一返回 `501 reserved`。详细契约见 `contracts/agent-openapi.yaml`。
