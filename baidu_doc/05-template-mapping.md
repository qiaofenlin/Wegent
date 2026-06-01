# 05 — Shell 与百度模板映射

## 5.1 百度沙箱模板清单

| 模板 ID（约定） | 名称 | 能力 |
|---|---|---|
| `fullstack` | FullStack Sandbox | Browser + Code Interpreter + Terminal + MCP |
| `browser` | Browser Use Sandbox | 仅浏览器自动化 |
| `code` | Code Sandbox | 多语言代码执行 / 解释 |
| `code-agent` | Coding Agent | Zulu + Ducc + 百度 DevOps 工具链 |

实际模板名以平台「沙箱广场」为准，需要 Phase 1 探活时确认。

## 5.2 Wegent Shell 类型

| Wegent shellType | 当前实现 | 推荐百度模板 | 备注 |
|---|---|---|---|
| `ClaudeCode` | Claude Code SDK 容器 | `code-agent` | 需要 git/icode 工具链 |
| `Agno` | Agno 框架容器 | `code-agent` | 需要多语言运行时 |
| `Dify` | 外部 Dify API | — | 不走沙箱，跳过 |
| `Chat` | 直连 LLM | — | 不走沙箱，跳过 |

## 5.3 映射策略

### 方案 A：通过 Shell CRD 显式声明（推荐）

扩展 `Shell` CRD spec，新增可选字段：

```yaml
apiVersion: agent.wecode.io/v1
kind: Shell
spec:
  shellType: ClaudeCode
  baseImage: claude-code:latest
  # 新增字段
  baiduSandbox:
    template: code-agent       # 百度模板名
    cpuRequest: "2"            # 资源规格
    memoryRequest: "4Gi"
```

`ShellTemplateMapper` 优先读取 `spec.baiduSandbox.template`，缺失时回落到默认映射表。

### 方案 B：硬编码映射

`template_mapper.py` 内置映射表，无需改 CRD。简单但灵活性差。

```python
DEFAULT_MAPPING = {
    "ClaudeCode": "code-agent",
    "Agno": "code-agent",
}
```

**采用方案 A**：长期看，Shell 是用户可自定义的 CRD，必须支持声明式覆盖。短期默认值用方案 B 兜底。

## 5.4 `ShellTemplateMapper` 实现

```python
# executor_manager/executors/baidu_sandbox/template_mapper.py
class ShellTemplateMapper:
    DEFAULT_MAPPING = {
        "ClaudeCode": "code-agent",
        "Agno": "code-agent",
    }
    FALLBACK = "code-agent"

    def resolve(self, shell) -> str:
        # Priority 1: explicit spec.baiduSandbox.template on Shell CRD
        explicit = getattr(shell.spec, "baidu_sandbox", {}).get("template")
        if explicit:
            return explicit

        # Priority 2: default mapping
        return self.DEFAULT_MAPPING.get(shell.shell_type, self.FALLBACK)
```

## 5.5 自定义镜像

百度 Sandbox 支持「业务基于标准镜像构建自己的镜像并接入环境」。Wegent 现有 `Shell.spec.baseImage` 可作为自定义镜像入口。

**接入方式**（待 Phase 1 确认）：

- 用户在百度沙箱平台上传镜像，得到模板名
- Shell CRD 的 `baiduSandbox.template` 填入该模板名
- Wegent 的二进制注入机制（命名卷 + 符号链接）**不再需要**——百度模板已包含完整运行时

## 5.6 资源规格

百度模板可能预设 CPU/Memory/Disk 规格。如需自定义：

- 通过 `Shell.spec.baiduSandbox.cpuRequest` 等字段传递
- `BaiduSandboxExecutor` 在 `submit_executor` 时附带到 SDK 创建参数

具体字段名以百度 SDK 文档为准。
