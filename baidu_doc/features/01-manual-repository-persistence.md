# 01 — 手动 URL 仓库持久化变更

**状态**：In Progress  
**记录时间**：2026-06-01 20:46:29 +0800

## 1. 背景

当前 Code 页面支持通过 `URL` 手动添加 `icode / Gerrit` 仓库，但该能力仅在当前页面会话内有效：

- 用户通过弹窗输入 clone URL 和 branch 后，可以立即发起任务
- 但刷新页面、重新进入 Code 页面或重新登录后，仓库选择器中不会再次显示该仓库

这会导致用户对手动补录仓库的心智预期不一致。对百度内使用场景而言，`icode` 仓库很多时候本来就无法通过 REST API 列举，因此“手动补录并可复用”是必要能力。

## 2. 本次需求

目标：让用户通过 URL 手动添加的仓库在后续访问时仍然可见，并可再次选择。

本次只解决：

1. 手动 URL 仓库的持久化
2. 仓库选择器中的恢复展示
3. 刷新页面 / 重新登录 / 换设备后的可见性

本次不解决：

1. 手动仓库的删除入口
2. 手动仓库的重命名
3. 团队级共享
4. 独立仓库资源管理页

## 3. 方案选择

采用 **方案 A：存入用户 preferences**。

### 3.1 为什么不用 localStorage

`localStorage` 只能覆盖当前浏览器，不能跨设备同步，也不能被后端读取，不满足“下次访问还能看到”的长期需求。

### 3.2 为什么不先建独立表

独立表更重，需要引入额外模型、接口和管理逻辑。当前需求的本质更像“用户偏好里的手动补录仓库”，适合先放入 `users.preferences`，后续再视需求量升级。

## 4. 数据设计

新增 `users.preferences.manual_repositories` 字段，结构如下：

```json
{
  "manual_repositories": [
    {
      "type": "icode",
      "git_domain": "icode.baidu.com",
      "git_repo": "baidu/hi/openclaw_infoflow",
      "git_url": "https://icode.baidu.com/baidu/hi/openclaw_infoflow",
      "display_name": "openclaw_infoflow",
      "default_branch": null,
      "is_manual": true
    }
  ]
}
```

### 4.1 唯一键

使用以下组合做去重：

```text
type + git_domain + git_repo
```

原因：

- `git_repo_id` 对手动仓库是前端 hash 生成，不适合作为长期主键
- 同名仓库可能分布在不同 provider / domain 下

## 5. 前端行为设计

### 5.1 保存时机

用户在 “通过 URL 添加仓库” 弹窗中点击确认后：

1. 当前页面继续选中该仓库和 branch
2. 同时调用 `updatePreferences`，将仓库写入 `manual_repositories`

### 5.2 展示策略

仓库选择器加载数据时：

1. 先读取 provider API 返回的仓库列表
2. 再读取 `user.preferences.manual_repositories`
3. 进行合并和去重
4. 手动仓库保留在合并结果中，保证下次可见

### 5.3 恢复策略

恢复“上次选中的仓库”时，优先按完整 identity 匹配：

```text
type + git_domain + git_repo_id + git_repo
```

避免仅按 `repoId` 恢复导致误命中。

## 6. 后端影响

本次不新增独立接口，继续复用：

```text
PUT /api/users/me
```

因此后端只需要：

1. 在 `UserPreferences` schema 中增加 `manual_repositories`
2. 保证与已有 `quick_access`、`default_execution_target` 合并时不互相覆盖

## 7. 自测建议

开发完成后，建议按以下步骤验证：

### 7.1 基本持久化

1. 进入 Code 页面
2. 打开仓库选择器
3. 点击“通过 URL 添加仓库”
4. 输入一个合法 `icode` 或 `gerrit` clone URL，分支可选
5. 确认后能看到当前任务已选中该仓库
6. 刷新页面
7. 再次打开仓库选择器
8. 确认该手动仓库仍然存在

### 7.2 跨登录恢复

1. 添加一个手动仓库
2. 退出登录
3. 重新登录同一账号
4. 打开 Code 页面仓库选择器
5. 确认该仓库仍然可见

### 7.3 去重行为

1. 对同一个 URL 连续添加两次
2. 确认仓库列表中只保留一份记录

### 7.4 不影响已有功能

1. 普通 GitHub/GitLab 仓库仍能正常列出
2. 搜索仓库仍可用
3. `无需代码仓库` 选项行为不变

## 8. 后续扩展

后续如果需求继续增加，可以考虑：

1. 增加手动仓库删除按钮
2. 增加“手动添加”分组标题
3. 增加最近使用时间
4. 升级为独立后端资源模型
