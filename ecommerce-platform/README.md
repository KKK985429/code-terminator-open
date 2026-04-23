# Ecommerce Platform

独立于仓库现有运行时的电商订单平台子项目，用于演示微服务、异步任务、预埋 Bug 与后续自动修复场景。

当前阶段已调整范围：

- 实现电商平台主体、基础设施、监控、压测与预埋 Bug
- 保留 `/api/agent/*` 接口契约与网关占位响应
- 不实现真实 Agent 服务、PR 自动化和飞书通知逻辑

## 目录

- `services/`: 四个 FastAPI 微服务与共享代码
- `celery_app/`: Celery 配置与任务
- `nginx/`: 网关与 `/api/agent/*` 预留接口
- `monitoring/`: Prometheus 配置
- `traffic/`: Locust 流量脚本
- `contracts/`: 预留的 Agent API 契约
- `scripts/`: 初始化、切流、健康检查脚本

## 启动

1. 进入目录：`cd ecommerce-platform`
2. 复制环境变量：`cp .env.example .env`
3. 启动：`docker compose up -d`
4. 初始化数据：`docker compose exec order-service-a python /app/scripts/init_db.py`

## 测试

```bash
pytest
```

## 预留接口

网关已经保留 `/api/agent/*` 路径，当前统一返回 `501 reserved`。详细契约见 `contracts/agent-openapi.yaml`。
