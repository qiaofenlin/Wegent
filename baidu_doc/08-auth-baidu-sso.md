# 08 — 登录体系切换百度 UUAP 评估

## 8.1 背景

百度 Agent Sandbox 数据面鉴权依赖用户的"个人身份 token"（详见 02-architecture.md 模式 A）。要把这个 token 自动注入到沙箱 metadata，**Wegent 必须能拿到当前用户的百度身份凭证**。

最自然的做法：让用户登录 Wegent 时直接走百度统一身份（UUAP），登录过程中拿到的 access-token 就是百度沙箱要的那个 token。

## 8.2 好消息：Wegent 已有 OIDC 实现

经代码审计，Wegent 后端已经有完整的 OIDC 服务：

| 组件 | 位置 | 状态 |
|---|---|---|
| OIDC 服务 | `backend/app/services/oidc.py` | ✅ 完整实现（authlib + Discovery + ID Token 校验） |
| 配置项 | `OIDC_CLIENT_ID` / `OIDC_CLIENT_SECRET` / `OIDC_DISCOVERY_URL` / `OIDC_REDIRECT_URI` | ✅ 已支持 |
| 授权码流程 | 标准 PKCE | ✅ 已支持 |
| CLI 登录 | `OIDC_CLI_REDIRECT_URI` | ✅ 已支持 |
| Scope | `openid email profile` | ⚠️ 可能需调整 |
| 用户信息端点 | `userinfo_endpoint` 调用 | ✅ 已支持 |

**结论**：UUAP 本身是标准 OIDC 协议，**不需要重新写认证逻辑**，主要是配置 + 数据模型扩展。

## 8.3 改造范围分级

按"目的"分三档，按需取用：

### 档位 A：最小集成（只为 BaiduSandbox 拿 token，3-5 天）

**目标**：用户保留现有登录方式，仅当使用百度沙箱功能时按需触发 UUAP 授权。

**改动**：

- `backend/app/models/user.py`：新增 `baidu_access_token`（加密）+ `baidu_token_expires_at` 字段
- `backend/app/services/oidc.py`：新增"绑定百度账号"流程（已有 OIDC 客户端基础上加配置）
- 用户在「设置」页点击「绑定百度账号」→ 走 UUAP OIDC 授权 → 存 access-token
- `BaiduSandboxExecutor` 创建沙箱前从此字段取 token

**优点**：
- ✅ 不动现有登录系统，零回归风险
- ✅ 支持渐进迁移，老用户继续用密码登录
- ✅ 本地开发用密码，生产用百度，灵活

**缺点**：
- ⚠️ 用户需主动绑定一次（有引导成本）
- ⚠️ token 过期后需要重新授权（除非接 refresh token）

### 档位 B：UUAP 作为主登录（5-8 天）

**目标**：登录页主入口为「百度账号登录」按钮，密码登录降为 fallback。

**改动**：

- 配置层：`OIDC_DISCOVERY_URL` 指向 UUAP 的 OIDC Discovery 端点
- 用户表加 `oidc_subject` / `oidc_issuer` 字段，登录回调时用 `sub` 关联或自动创建用户
- 前端登录页：「百度账号登录」按钮置顶，密码登录折叠为「其他方式」
- 登录成功后 access-token 自动入库，给 BaiduSandboxExecutor 用

**优点**：
- ✅ 用户体验自然（一次登录，全功能可用）
- ✅ 沙箱集成无感知
- ✅ 适合内网常态部署

**缺点**：
- ⚠️ 老用户需要绑定（首次 UUAP 登录时按 email 自动 merge）
- ⚠️ 密码登录路径仍存在，长期维护成本

### 档位 C：完全替换（仅保留 UUAP，10-15 天）

**目标**：移除所有密码登录入口，全平台只能 UUAP。

**额外改动**（在 B 基础上）：

- 移除 `backend/app/api/endpoints/auth.py` 的密码登录端点
- 移除前端密码登录表单
- 数据迁移：现有密码用户必须二次绑定，否则锁定
- E2E 测试全部改为 UUAP 流程（需 OIDC mock server 用于 CI）
- 文档更新：废弃密码登录，OIDC 配置为强制项

**优点**：
- ✅ 单一身份源，安全审计简单

**缺点**：
- ❌ 本地开发友好度下降（要么搭 mock，要么走真 UUAP）
- ❌ 老用户锁定风险大
- ❌ 与开源社区版本（无 UUAP）形成分支

## 8.4 推荐方案

**采用档位 A**（最小集成），理由：

1. **风险最低**：完全不改既有登录链路，回滚成本为零
2. **聚焦**：本期目标是百度沙箱集成，不是登录系统重构
3. **可延展**：未来需要时随时升级到档位 B/C，不会重写
4. **本地开发友好**：开发者在本地用密码登录，连本地 Docker 沙箱，无需 UUAP

**升级路径**：等百度沙箱在生产稳定运行 1-2 个迭代，再决定是否升档位 B。

## 8.5 档位 A 详细工作量

| 任务 | 工作量 |
|---|---|
| 用户表加 `baidu_access_token` / `baidu_token_expires_at` 字段（加密） | 0.5 天 |
| `oidc.py` 新增「百度账号绑定」流程（独立配置 + 独立回调路由） | 1 天 |
| 「设置」页面增加绑定入口 + 状态展示 | 1 天 |
| `BaiduSandboxExecutor` 集成 token 读取 + 过期检测 | 0.5 天 |
| Refresh token 自动续期（如 UUAP 支持） | 1 天 |
| 单元测试 + 文档 | 1 天 |
| **合计** | **5 天** |

## 8.6 配置示例

档位 A 下，新增独立的「百度绑定」配置（与现有 OIDC 互不影响）：

```bash
# 现有登录系统保持不变
OIDC_CLIENT_ID=...
OIDC_DISCOVERY_URL=https://existing-issuer/.well-known/openid-configuration

# 新增：百度账号绑定（专用于 Sandbox 鉴权）
BAIDU_OIDC_ENABLED=true
BAIDU_OIDC_CLIENT_ID=<UUAP 应用 ID>
BAIDU_OIDC_CLIENT_SECRET=<UUAP secret>
BAIDU_OIDC_DISCOVERY_URL=https://uuap.baidu.com/.well-known/openid-configuration
BAIDU_OIDC_REDIRECT_URI=https://wegent.baidu-int.com/api/auth/baidu/callback
BAIDU_OIDC_SCOPE="openid email profile <额外的 sandbox scope>"
```

**关键 scope**：需找百度沙箱团队（yangwencai）确认 access-token 是否需要特定 scope 才能用于 `agent-sandbox/access-token` 注入。

## 8.7 待确认（与 07-open-questions.md 联动）

| # | 问题 | 影响 |
|---|---|---|
| Q9 | UUAP 是否提供标准 OIDC Discovery 端点？ | 决定配置工作量 |
| Q10 | UUAP access-token 默认 TTL？是否支持 refresh_token？ | 决定是否需要刷新机制 |
| Q11 | 沙箱 access-token 注入需要的 scope 是什么？ | 决定 scope 配置 |
| Q12 | Wegent 是否已经在 UUAP 注册过 OIDC 应用？ | 决定是否需要走应用申请流程 |

## 8.8 决策记录补充

| ID | 决策 | 状态 |
|---|---|---|
| DR-8 | 采用档位 A（最小集成） | ✅ 推荐 |
| DR-9 | 不在本期移除密码登录 | ✅ 推荐 |
| DR-10 | UUAP token 加密存储，复用现有 `shared/cryptography/` 机制 | ✅ 推荐 |
