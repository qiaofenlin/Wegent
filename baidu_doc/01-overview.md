# 01 — 总体概览

## 1.1 背景

Wegent 当前默认使用 `DockerExecutor`，在单机或小规模集群上以本地 Docker daemon 运行沙箱。该方案在以下场景受限：

- 缺少 Code Interpreter / Browser Use 等高级运行时
- 单机资源受限，扩缩容困难
- 沙箱网络暴露依赖路径代理（`/proxy/{id}/{port}/{path}`），对前端 SPA / dev server 兼容性差
- 缺少与百度 DevOps 体系（icode、iCafe、Zulu、Ducc）的原生集成

## 1.2 目标

让 Wegent 在百度内网部署形态下，将沙箱执行后端切换为 **百度 Agent Sandbox**（`agent-sandbox.baidu-int.com`），获得以下能力：

- 托管的 K8s 集群与扩缩容（无需自运维）
- 内置 FullStack / Browser / Code / Code Agent 四类模板
- 泛域名暴露 `https://{port}-{sandbox_id}.agent-sandbox.baidu-int.com`
- 用户身份与 icode 权限自动注入

## 1.3 非目标

明确**不在本期范围**内的事项：

- ❌ 公网开源部署的兼容（外部用户无百度 UUAP 身份，无法使用百度沙箱网关）
- ❌ 自建 K8s 集群 / 自建 Code Interpreter / 自建 Browser Use
- ❌ 替换或下线现有 `DockerExecutor`（保留作为本地开发场景）
- ❌ Wegent 侧自建泛域名网关
- ❌ 实现百度沙箱平台已有的产品壳层（模板广场、计费、空间管理）

## 1.4 高层架构

```
百度员工浏览器（已登录 UUAP）
    │
    ├──→ wegent.baidu-int.com（Wegent 前端）
    │       │
    │       ↓ WebSocket / HTTP
    │     Wegent Backend
    │       │ E2B_API_KEY
    │       ↓
    │     百度 Sandbox 控制面 API
    │       │
    │       └─→ 创建沙箱（注入用户 access-token）
    │
    └──→ iframe / 跳转
         https://{port}-{sandbox_id}.agent-sandbox.baidu-int.com
         （浏览器自动带 UUAP Cookie 通过百度网关鉴权）
```

**关键决策**：Wegent 仅承担**控制面**职责，**数据面**（HTTP 流量、Web 预览、Code/Browser 交互）由用户浏览器直连百度域名，Wegent 不做反向代理。

## 1.5 设计原则

1. **复用 Strategy 模式**：通过新增 `BaiduSandboxExecutor`，不破坏现有 Executor 抽象
2. **配置驱动切换**：通过 `EXECUTOR_DISPATCHER_MODE` / `EXECUTOR_CONFIG` 切换后端，不强制全量迁移
3. **协议层零改造**：复用 Wegent 已实现的 E2B 兼容接口（`routers/e2b.py`）
4. **数据面外推**：不在 Wegent 侧做泛域名/CORS/证书工作
