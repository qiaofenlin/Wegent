# 03 — 落地路线图

## 3.1 阶段总览

| Phase | 内容 | 工作量 | 阻塞项 |
|---|---|---|---|
| 1 | 协议探活 + 鉴权机制确认 | 1 天 | 需要百度 API Key + 用户 token 获取方式 |
| 2 | `BaiduSandboxExecutor` 实现 | 3-5 天 | Phase 1 完成 |
| 3 | UUAP Token 接入（档位 A，详见 08-auth-baidu-sso.md） | 5 天 | Phase 1 确认 token 类型 |
| 4 | 模板映射 | 1-2 天 | Phase 2 完成 |
| 5 | 前端预览页改造 | 1-2 天 | Phase 4 完成 |
| **合计** | | **~12 天** | |

## 3.2 Phase 1：协议探活（1 天）

**目标**：在不改 Wegent 代码的前提下，验证可行性。

**任务**：

1. 找百度沙箱平台申请 API Key
2. 找 yangwencai@baidu.com 申请「沙箱个人身份注入接入说明」文档权限
3. 写独立测试脚本（不依赖 Wegent）：
   ```python
   # baidu_doc/scripts/probe.py
   from e2b_code_interpreter import Sandbox
   sbx = Sandbox(template="code-agent", metadata={...})
   result = sbx.commands.run("echo hello")
   sbx.kill()
   ```
4. 在浏览器打开 `https://8080-{sandbox_id}.agent-sandbox.baidu-int.com`，确认能否访问
5. 测试 access-token 注入：分别用自己的 token 和别人的 token，验证是否正确鉴权

**交付物**：

- 探活脚本 `baidu_doc/scripts/probe.py`
- 兼容性报告（哪些字段 Wegent 已对齐、哪些需要补）
- 用户 token 获取方式确认

**判断标准**：5 个测试点全部通过 → 可进入 Phase 2。

## 3.3 Phase 2：BaiduSandboxExecutor（3-5 天）

**新增文件**：

```
executor_manager/executors/baidu_sandbox/
├── __init__.py
├── executor.py          # BaiduSandboxExecutor 主类
├── client.py            # 封装 e2b SDK 调用
├── template_mapper.py   # Shell → 百度模板映射
└── token_provider.py    # 用户 token 获取抽象
```

**改动文件**：

- `executor_manager/config/config.py`：新增 `BAIDU_SANDBOX_API_KEY`、`BAIDU_SANDBOX_DOMAIN` 配置项
- `executor_manager/executors/dispatcher.py`：无需改动（已支持配置驱动）

详见 [04-baidu-sandbox-executor.md](./04-baidu-sandbox-executor.md)。

## 3.4 Phase 3：UUAP Token 接入（0.5-3 天）

**先调研**：检查 Wegent backend 是否已接入 OIDC：

```bash
grep -r "oidc\|uuap\|OAuth2" backend/app/
```

**两种情况**：

| 现状 | 工作 | 工作量 |
|---|---|---|
| 已有 OIDC，仅需配置 issuer 为 UUAP | 改配置 + 用户表加 `uuap_access_token` 字段 | 0.5 天 |
| 无 OIDC，需要从头接入 | 加 OIDC middleware + 登录回调 + 加密存储 token | 2-3 天 |

**改动文件（预估）**：

- `backend/app/api/auth.py`：UUAP 登录回调
- `backend/app/models/user.py`：加密的 `baidu_access_token` 字段
- `backend/app/services/user_token_service.py`：token 刷新与解密
- `executor_manager/executors/baidu_sandbox/token_provider.py`：从 backend 拉取 user token

## 3.5 Phase 4：模板映射（1-2 天）

详见 [05-template-mapping.md](./05-template-mapping.md)。核心：通过 `Shell` CRD 的 `shellType` 字段映射到百度 4 类模板。

## 3.6 Phase 5：前端预览页（1-2 天）

详见 [06-frontend-preview.md](./06-frontend-preview.md)。核心：

- `models/sandbox.py:224` 的 `base_url` 改为指向百度泛域名
- 前端预览组件改为 iframe 直链
- 移除/绕过 `wegent_e2b_proxy.py` 路径代理（仅在 docker 模式下保留）

## 3.7 风险与缓解

| 风险 | 影响 | 缓解 |
|---|---|---|
| 百度 access-token 机制不支持服务端代签 | Phase 3 工作量翻倍 | Phase 1 优先验证，必要时降级用模式 B 白名单 |
| 百度 SDK 与 Wegent 现有 e2b 兼容层冲突 | 协议层可能要重写 | 在独立 venv 中验证，不污染主依赖 |
| iframe 嵌入被百度网关 X-Frame-Options 阻止 | 预览只能跳新窗口 | Phase 1 验证，必要时联系百度调整 CSP |
| 百度沙箱限流/配额问题 | 高峰期任务排队 | 按 user_id 维度限流，提前与百度确认 quota |

## 3.8 回滚策略

- 配置层切换：将 `EXECUTOR_DISPATCHER_MODE` 改回 `docker`，立即回退
- 代码层：`BaiduSandboxExecutor` 完全独立，不修改既有 DockerExecutor
- 数据层：用户表新增字段允许 null，不影响存量用户
