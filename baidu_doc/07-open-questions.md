# 07 — 待确认事项

## 7.1 必须在 Phase 1 完成的确认

| # | 问题 | 影响 | 确认方式 |
|---|---|---|---|
| Q1 | `metadata["agent-sandbox/access-token"]` 接受的 token 是 UUAP 票据 / iAM token / 自定义 token？ | 影响 Phase 3 实现路径 | 申请「沙箱个人身份注入接入说明」文档权限 |
| Q2 | 用户 token 由谁签发？Wegent 后端能否用 API Key 代签短期 token？ | 影响是否需要用户主动登录刷新 | 同上 + 联系 yangwencai@baidu.com |
| Q3 | 用户 token 有效期多长？过期后正在运行的沙箱是否仍可访问？ | 影响沙箱长期任务可用性 | 文档 + 实测 |
| Q4 | 百度泛域名是否设置 `X-Frame-Options` 阻止 iframe 嵌入？ | 影响预览实现 | 浏览器实测 |
| Q5 | 百度泛域名 CORS 策略：是否允许跨子域 fetch？ | 影响前端 JS 直调能力 | 浏览器实测 |
| Q6 | Wegent 域名（如 `wegent.baidu-int.com`）和 `agent-sandbox.baidu-int.com` 是否共享 UUAP Cookie？ | 影响是否需要单独鉴权 | 浏览器实测 |
| Q7 | 沙箱 quota 上限：单用户并发数、单团队总数 | 影响容量规划 | 平台「API Key 管理」页面或联系百度 |
| Q8 | 百度模板的实际名称（fullstack / browser / code / code-agent 是否准确）？ | 影响 ShellTemplateMapper | 沙箱广场页面查看 |

## 7.2 联系人

| 角色 | 联系方式 |
|---|---|
| 主要联系人 | 苏琳（sulin01@baidu.com） |
| 接入支持 | 杨文才（yangwencai@baidu.com） |
| 用户群 | [百度Agent Sandbox用户群](https://applink-infoflow.baidu.com/share/contact/open/?token=qPvbu4WVwRrivHU9jCGv0PcaFTaZno3aJGjzHy3zvEc?t=mention&mt=doc&dt=sdk)（群号：12143597）|
| 通知服务号 | OneTool 服务号（接收实例创建失败、过期等通知） |

## 7.3 关键文档

- 主文档：[百度Agent Sandbox使用说明](https://ku.baidu-int.com/knowledge/HFVrC7hq1Q/_SKPgSwp2G/B8wSneaLSC/xBjsa6yz-ZsV4-)
- 身份注入：[沙箱个人身份注入接入说明](https://ku.baidu-int.com/knowledge/HFVrC7hq1Q/_SKPgSwp2G/B8wSneaLSC/D77sFE5rkrbOEI?t=mention&mt=doc&dt=doc)（**当前无访问权限，需申请**）
- aio SDK：[github.com/agent-infra/sandbox](https://github.com/agent-infra/sandbox)
- 平台入口：[https://console.cloud.baidu-int.com/aitools/sandbox-square](https://console.cloud.baidu-int.com/aitools/sandbox-square)

## 7.4 Wegent 侧待调研

| # | 项 | 调研方式 |
|---|---|---|
| W1 | Backend 是否已接入 OIDC？接入哪个 issuer？ | `grep -r "oidc\|OAuth2" backend/app/api/auth*` |
| W2 | 用户表是否已有 token 加密字段？现有加密机制？ | 查看 `backend/app/models/user.py` + `shared/cryptography/` |
| W3 | `Shell` CRD 是否已支持自定义 spec 扩展？ | 查看 `backend/app/schemas/shell.py` |
| W4 | 现有 e2b 兼容层（`routers/e2b.py`）是否会与百度 SDK 冲突？ | 在独立 venv 中并存运行验证 |
| W5 | 任务流中是否能拿到当前 user 对象（含 token）？ | 查看 `executor_manager/services/sandbox/manager.py` 调用链 |

## 7.5 决策记录（DR）

| ID | 决策 | 状态 |
|---|---|---|
| DR-1 | 仅支持百度内网部署形态 | ✅ 已确认 |
| DR-2 | 不实现自建 K8s 集群方案 | ✅ 已确认 |
| DR-3 | 不在 Wegent 侧做泛域名网关 | ✅ 已确认 |
| DR-4 | 采用模式 A（个人身份注入），不走白名单 | ✅ 已确认 |
| DR-5 | 保留 DockerExecutor 作为本地开发后端 | ✅ 已确认 |
| DR-6 | 优先采用 iframe 嵌入预览，受阻时降级为新窗口跳转 | ⏳ 待 Phase 1 验证 |
| DR-7 | Shell CRD 是否扩展 `baiduSandbox` 字段 | ⏳ 待评审 |
