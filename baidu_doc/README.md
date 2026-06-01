# Wegent 接入百度 Agent Sandbox 设计文档

本目录包含 Wegent 集成百度 Agent Sandbox 的全部设计文档。

## 文档清单

### 总体设计

- [01-overview.md](./01-overview.md) — 总体目标、范围、架构总览
- [02-architecture.md](./02-architecture.md) — 控制面 / 数据面架构与鉴权模型
- [03-roadmap.md](./03-roadmap.md) — 分阶段落地路线图与工作量评估
- [04-baidu-sandbox-executor.md](./04-baidu-sandbox-executor.md) — `BaiduSandboxExecutor` 详细设计
- [05-template-mapping.md](./05-template-mapping.md) — Wegent Shell ↔ 百度 Sandbox 模板映射
- [06-frontend-preview.md](./06-frontend-preview.md) — 前端沙箱预览改造
- [07-open-questions.md](./07-open-questions.md) — 待确认事项与联系人
- [08-auth-baidu-sso.md](./08-auth-baidu-sso.md) — 登录体系切换百度 UUAP 评估

### Feature 需求记录

- [features/README.md](./features/README.md) — 需求记录目录说明
- [features/01-manual-repository-persistence.md](./features/01-manual-repository-persistence.md) — 手动 URL 仓库持久化变更

可使用以下脚本自动创建新需求文档并更新索引：

```bash
python3 baidu_doc/scripts/new_feature_doc.py "需求标题"
```

## 适用范围

- **部署形态**：百度内网部署
- **用户群体**：百度内网员工（已登录 UUAP）
- **沙箱后端**：百度 Agent Sandbox（不再使用本地 Docker 模式）
- **不在范围内**：公网开源部署、跨厂商沙箱、自建 K8s 集群

## 文档状态

`Draft` — 待 Reviewer 评审。
