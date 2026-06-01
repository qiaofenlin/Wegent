# 02 — 架构与鉴权模型

## 2.1 控制面 vs 数据面分层

| 分层 | 职责 | 域名 | 鉴权方式 | 持有方 |
|---|---|---|---|---|
| **控制面** | 创建/销毁/命令派发/文件操作 | `agent-sandbox.baidu-int.com` | `E2B_API_KEY` | Wegent Backend |
| **数据面** | 用户浏览器访问沙箱内服务 / 预览页 | `{port}-{id}.agent-sandbox.baidu-int.com` | UUAP Cookie 或注入的 access-token | 用户浏览器 |

**严格隔离原则**：API Key 仅存在于 Backend，永不下发到浏览器；用户 token 仅在创建沙箱时通过 metadata 注入，不参与日常 API 调用。

## 2.2 控制面调用链

```
Wegent Backend
   │  (持有 E2B_API_KEY)
   │  e2b.Sandbox(template=..., metadata={...})
   ↓
agent-sandbox.baidu-int.com (E2B 协议)
   │
   ↓
百度 Sandbox 调度器
   │
   ↓
分配容器 → 返回 sandbox_id
```

实现层面 Wegent 调用的是百度 fork 的 e2b SDK：

```
e2b==1.11.2+baidu
e2b-code-interpreter==1.5.2
索引源: https://pip.baidu-int.com/simple/
```

## 2.3 数据面访问链

```
浏览器
   │  (UUAP Cookie 自动携带)
   │  GET https://3000-abc123.agent-sandbox.baidu-int.com/
   ↓
百度 Sandbox 网关
   │  ① 解析 Host 头 → 定位 sandbox_id
   │  ② 校验 UUAP 身份是否在沙箱 access-token 关联人范围
   │     - 若沙箱创建时注入了 metadata["agent-sandbox/access-token"]：
   │       校验当前用户是否就是该 token 持有人 → 允许
   │     - 否则走白名单模式
   │  ③ 转发到对应容器的 {port}
   ↓
沙箱内服务（如 dev server）
```

## 2.4 鉴权模式对比

百度官方文档提供两种数据面鉴权模式：

### 模式 A：个人身份注入（推荐）

```python
sbx = Sandbox(
    template="...",
    metadata={
        "agent-sandbox/access-token": user_uuap_token,
        "codeBean": json.dumps({"username": user.icode_username}),
    },
)
```

- ✅ 支持厂内任意员工，无需预报名单
- ✅ icode 权限随 token 自动透传
- ⚠️ 需要 Wegent 持有用户 UUAP token

### 模式 B：白名单

- 不传 access-token
- 提前提交允许使用的 username 列表给百度（联系 yangwencai@baidu.com）
- ✅ 实现简单
- ❌ 用户范围固定，新增用户需重新申请
- ❌ icode 权限需另行处理

**本设计采用模式 A**。理由：Wegent 已有用户系统，UUAP token 在用户登录时即可获取，不引入额外协调成本。

## 2.5 用户 UUAP Token 的来源

**两个关键问题需在 Phase 1 探活时确认**（详见 [07-open-questions.md](./07-open-questions.md)）：

1. 百度沙箱要求的 access-token 具体是什么类型（UUAP 票据 / iAM token / 自定义）？
2. token 有效期多长？过期后正在运行的沙箱内服务是否仍可访问？

**预期接入方式**：

```
用户浏览器 → wegent.baidu-int.com
    ↓ OIDC 重定向
UUAP 登录页
    ↓
Wegent Backend (拿到 ID Token + Access Token)
    ↓
存入用户会话 / 数据库 (加密存储)
    ↓
任务创建时 → BaiduSandboxExecutor → 注入 metadata
```

## 2.6 Executor 路由策略

继续利用 Wegent 现有的 `EXECUTOR_CONFIG` 机制，按 `task_type` / `shell_type` 路由：

```bash
EXECUTOR_DISPATCHER_MODE=baidu_sandbox
EXECUTOR_CONFIG='{
  "baidu_sandbox": "executor_manager.executors.baidu_sandbox.BaiduSandboxExecutor",
  "docker": "executor_manager.executors.docker.DockerExecutor"
}'
```

- 内网生产 → 默认 `baidu_sandbox`
- 本地开发 / CI → 保留 `docker`
- 单个 Wegent 实例可同时支持两种后端
