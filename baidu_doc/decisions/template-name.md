---
date: 2026-05-29
status: confirmed
---

# 百度沙箱模板名称

## 当前状态

模板名需手动指定，无自动发现 API。

已确认可用模板：`fenglin_ducc`（Phase 1 探活验证通过）

## 使用位置

- `Shell` CRD `spec.baiduSandbox.template` 字段（用户显式指定）
- `executor_manager/executors/baidu_sandbox/template_mapper.py` 默认映射表（兜底）

## 待优化

e2b SDK 没有列出可用模板的 API，后续可考虑：
1. 调用百度沙箱控制面 API 动态拉取模板列表，在 UI 创建 Shell 时提供下拉选择
2. 联系百度（yangwencai@baidu.com）确认是否有 list templates 接口
