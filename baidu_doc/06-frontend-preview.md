# 06 — 前端沙箱预览改造

## 6.1 当前实现

`executor_manager/models/sandbox.py:224` 的 `Sandbox.base_url` 字段在 Docker 模式下指向：

```
http://localhost:{mapped_port}
```

前端访问预览时通过 Wegent 反向代理：

```
GET /proxy/{sandbox_id}/{port}/{path}
  → wegent_e2b_proxy.py 转发
  → 容器内服务
```

## 6.2 切换百度模式后

`Sandbox.base_url` 改为指向百度泛域名：

```
https://8080-{sandbox_id}.agent-sandbox.baidu-int.com
```

**用户浏览器（已登录 UUAP）直连百度域名**，Wegent 不再做反向代理。

## 6.3 改动清单

### Backend / Executor Manager

**`executor_manager/executors/baidu_sandbox/executor.py`**：

```python
return Sandbox(
    ...
    base_url=f"https://8080-{sandbox_id}.agent-sandbox.baidu-int.com",
)
```

8080 是百度沙箱管理页面默认端口（VSCode/Browser/Terminal/Jupyter 多视图入口）。如果用户启动了自定义服务，应根据端口动态生成 URL：

```python
def preview_url(sandbox_id: str, port: int = 8080) -> str:
    return f"https://{port}-{sandbox_id}.agent-sandbox.baidu-int.com"
```

**`executor_manager/wegent_e2b_proxy.py`**：

百度模式下完全不需要路径代理。两种处理：

- **方案 1（推荐）**：保持代码不动，仅在 `EXECUTOR_DISPATCHER_MODE=baidu_sandbox` 时让前端不再调用 `/proxy/...` 路径
- **方案 2**：在路径代理路由开头加 302 跳转：
  ```python
  if executor_mode == "baidu_sandbox":
      return RedirectResponse(
          f"https://{port}-{sandbox_id}.agent-sandbox.baidu-int.com/{path}",
          status_code=307,
      )
  ```

## 6.4 Frontend

**核心改动**：预览组件读取 `sandbox.base_url`，直接 iframe 嵌入或新窗口打开。

```tsx
// frontend/src/features/sandbox/PreviewPanel.tsx
function PreviewPanel({ sandbox }: { sandbox: Sandbox }) {
  if (!sandbox.base_url) {
    return <EmptyState />
  }

  return (
    <iframe
      src={sandbox.base_url}
      className="w-full h-full"
      sandbox="allow-same-origin allow-scripts allow-forms"
      data-testid="sandbox-preview-iframe"
    />
  )
}
```

**关键点**：

- 用户浏览器已登录 UUAP，访问百度域名时 Cookie 自动携带，无需 Wegent 介入鉴权
- iframe 嵌入需要百度域名响应头允许：
  ```
  X-Frame-Options: ALLOWALL  或  Content-Security-Policy: frame-ancestors *.baidu-int.com
  ```
  此项需要 Phase 1 验证

## 6.5 多端口预览

用户可能同时启动多个服务（如 3000 dev server + 9229 调试端口）。

**方案**：前端提供端口选择器，动态拼 URL：

```tsx
const [port, setPort] = useState(8080)
const url = `https://${port}-${sandbox.sandbox_id}.agent-sandbox.baidu-int.com`
```

## 6.6 跨域调用沙箱 API

如果前端 JS 需要直接 fetch 沙箱内 API（非 iframe 渲染），存在跨域问题：

```js
// wegent.baidu-int.com 页面里
fetch('https://3000-abc.agent-sandbox.baidu-int.com/api/data')
// → CORS preflight，需要百度沙箱响应 Access-Control-Allow-Origin
```

**降级方案**：通过 Wegent Backend 代理：

```js
fetch('/api/sandbox-proxy/abc/3000/data')
// Backend 用 API Key 转发到百度
```

此为 fallback 路径，仅在百度域名不开 CORS 时启用。

## 6.7 预览跳转 vs iframe 选择

| 场景 | 推荐方式 |
|---|---|
| 沙箱管理页（VSCode/Terminal/Jupyter）| iframe（端口 8080）|
| 用户自启动的 Web 应用预览 | iframe |
| 长时间使用 / 需要大屏 | 提供「在新窗口打开」按钮 |
| 第三方应用接管 | 新窗口跳转 |

## 6.8 风险

- **X-Frame-Options 阻止 iframe**：Phase 1 必须验证。如阻止，降级为新窗口跳转
- **UUAP Cookie 跨子域**：`*.baidu-int.com` 通常共享 Cookie，但需确认 SameSite 策略
- **iframe 内的相对路径资源**：百度域名是子域根路径，沙箱内服务的相对路径资源应能正确加载（这正是泛域名相对于路径代理的优势）
