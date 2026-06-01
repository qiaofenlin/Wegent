# Feature 需求记录

本目录用于存放百度场景下的功能需求记录，遵循：

- 一条需求一个文档
- 一个文档只描述一个明确需求或一组强相关变更
- 文档包含背景、方案、影响范围、自测方式和后续扩展
- 新需求默认先在这里落文档，再进入开发

## 命名建议

建议使用以下格式：

```text
NN-feature-name.md
```

例如：

- `01-manual-repository-persistence.md`
- `02-sandbox-runtime-recovery.md`

## 与上层文档的关系

- `baidu_doc/01-08` 主要记录整体设计、架构、路线图和开放问题
- `baidu_doc/features/` 主要记录逐条需求和变更

如果某条需求已经稳定沉淀为通用架构约束，再考虑把结论回写到上层总设计文档。

## 自动生成方式

可以使用脚本自动创建新需求文档并更新 `baidu_doc/README.md` 索引：

```bash
python3 baidu_doc/scripts/new_feature_doc.py "手动 URL 仓库持久化"
```

脚本会自动：

1. 计算下一个编号
2. 基于 `TEMPLATE.md` 生成文档
3. 将新文档写入 `baidu_doc/features/`
4. 更新 `baidu_doc/README.md` 中的 feature 列表
