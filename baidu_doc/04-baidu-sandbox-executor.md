# 04 — BaiduSandboxExecutor 详细设计

## 4.1 类继承关系

```
executor_manager/executors/base.py
    Executor (abstract)
        ↑
        ├── DockerExecutor (existing)
        └── BaiduSandboxExecutor (new)
```

复用 `Executor` 抽象基类的 8 个核心方法，零修改基类。

## 4.2 文件结构

```
executor_manager/executors/baidu_sandbox/
├── __init__.py
├── executor.py          # BaiduSandboxExecutor (实现 Executor 抽象)
├── client.py            # E2BClientWrapper (封装 e2b SDK)
├── template_mapper.py   # ShellTemplateMapper
├── token_provider.py    # UserTokenProvider (从 backend 拉 token)
└── exceptions.py        # 百度沙箱专属异常
```

## 4.3 `BaiduSandboxExecutor` 接口实现

```python
# executor_manager/executors/baidu_sandbox/executor.py
from executor_manager.executors.base import Executor
from executor_manager.models.sandbox import Sandbox, SandboxStatus
from .client import E2BClientWrapper
from .template_mapper import ShellTemplateMapper
from .token_provider import UserTokenProvider


class BaiduSandboxExecutor(Executor):
    """Baidu Agent Sandbox executor.

    Delegates lifecycle and command dispatch to Baidu's hosted sandbox service
    via the E2B-compatible SDK (e2b==1.11.2+baidu).

    Wegent retains only control-plane responsibilities; data-plane traffic
    flows directly between user browsers and Baidu's wildcard subdomains.
    """

    def __init__(self):
        self._client = E2BClientWrapper()
        self._template_mapper = ShellTemplateMapper()
        self._token_provider = UserTokenProvider()
        # Track sandbox_id → owner_user_id for accounting
        self._registry: Dict[str, int] = {}

    async def submit_executor(self, task) -> Sandbox:
        """Create a new Baidu sandbox for the given task."""
        user_token = await self._token_provider.get_token(task.user_id)
        template = self._template_mapper.resolve(task.shell_type)

        baidu_sbx = await self._client.create(
            template=template,
            timeout=task.timeout_seconds or 3600,
            metadata={
                "agent-sandbox/access-token": user_token,
                "agent-sandbox/name": f"wegent-{task.id}",
                "codeBean": json.dumps({"username": task.user.icode_username}),
            },
            envs={"COMATE_AUTH_TOKEN": user_token},
        )

        sandbox_id = baidu_sbx.sandbox_id
        self._registry[sandbox_id] = task.user_id

        return Sandbox(
            sandbox_id=sandbox_id,
            container_name=f"baidu-{sandbox_id}",
            shell_type=task.shell_type,
            user_id=task.user_id,
            user_name=task.user.username,
            base_url=f"https://8080-{sandbox_id}.agent-sandbox.baidu-int.com",
            status=SandboxStatus.PENDING,
            metadata={"task_id": task.id, "baidu_template": template},
        )

    async def create_instance(self, sandbox: Sandbox) -> None:
        """No-op: Baidu manages instance creation atomically with submit."""
        pass

    async def wait_instance_ready(self, sandbox: Sandbox, timeout: int = 60) -> bool:
        """Poll Baidu sandbox status until RUNNING or timeout."""
        return await self._client.wait_ready(sandbox.sandbox_id, timeout)

    async def dispatch_task_to_instance(self, sandbox: Sandbox, task) -> None:
        """Send the task prompt to the sandbox via commands.run."""
        await self._client.run_command(
            sandbox_id=sandbox.sandbox_id,
            command=self._build_command(task),
            background=True,
        )

    async def get_container_status(self, sandbox: Sandbox) -> SandboxStatus:
        baidu_status = await self._client.get_status(sandbox.sandbox_id)
        return self._map_status(baidu_status)

    async def delete_executor(self, sandbox: Sandbox) -> None:
        await self._client.kill(sandbox.sandbox_id)
        self._registry.pop(sandbox.sandbox_id, None)

    async def get_executor_count(self) -> int:
        return len(self._registry)

    async def get_current_task_ids(self) -> List[str]:
        return list(self._registry.keys())

    @staticmethod
    def _map_status(baidu_status: str) -> SandboxStatus:
        return {
            "pending": SandboxStatus.PENDING,
            "running": SandboxStatus.RUNNING,
            "killed": SandboxStatus.TERMINATED,
            "failed": SandboxStatus.FAILED,
        }.get(baidu_status, SandboxStatus.PENDING)
```

## 4.4 `E2BClientWrapper`

封装 e2b SDK，统一异常处理和重试：

```python
# executor_manager/executors/baidu_sandbox/client.py
import asyncio
from e2b_code_interpreter import Sandbox as E2BSandbox

class E2BClientWrapper:
    def __init__(self):
        # SDK reads from env vars: E2B_API_KEY, E2B_DOMAIN
        self._domain = settings.BAIDU_SANDBOX_DOMAIN

    async def create(self, *, template, timeout, metadata, envs) -> E2BSandbox:
        # SDK is sync; offload to thread pool
        return await asyncio.to_thread(
            E2BSandbox,
            template=template,
            timeout=timeout,
            metadata=metadata,
            envs=envs,
        )

    async def run_command(self, *, sandbox_id, command, background=False):
        sbx = await asyncio.to_thread(E2BSandbox, sandbox_id=sandbox_id)
        return await asyncio.to_thread(sbx.commands.run, command, background=background)

    async def wait_ready(self, sandbox_id: str, timeout: int) -> bool:
        # Poll get_info() until status=running or timeout
        ...

    async def get_status(self, sandbox_id: str) -> str:
        sbx = await asyncio.to_thread(E2BSandbox, sandbox_id=sandbox_id)
        info = await asyncio.to_thread(sbx.get_info)
        return info.get("status", "pending")

    async def kill(self, sandbox_id: str):
        sbx = await asyncio.to_thread(E2BSandbox, sandbox_id=sandbox_id)
        await asyncio.to_thread(sbx.kill)
```

## 4.5 `UserTokenProvider`

从 Wegent Backend 拉取用户的百度 access-token：

```python
# executor_manager/executors/baidu_sandbox/token_provider.py
class UserTokenProvider:
    """Fetches user's Baidu access-token from Wegent Backend.

    Backend stores encrypted UUAP tokens after user login. This provider
    queries the Backend internal API to retrieve a fresh token.
    """

    async def get_token(self, user_id: int) -> str:
        # Internal API call (within trusted network)
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{settings.WEGENT_BACKEND_URL}/internal/users/{user_id}/baidu-token",
                headers={"X-Internal-Auth": settings.INTERNAL_AUTH_SECRET},
            )
            resp.raise_for_status()
            return resp.json()["access_token"]
```

## 4.6 配置项

新增 `executor_manager/config/config.py`：

```python
# Baidu Sandbox configuration
BAIDU_SANDBOX_API_KEY = os.getenv("BAIDU_SANDBOX_API_KEY", "")
BAIDU_SANDBOX_DOMAIN = os.getenv("BAIDU_SANDBOX_DOMAIN", "agent-sandbox.baidu-int.com")
BAIDU_SANDBOX_DEFAULT_TEMPLATE = os.getenv("BAIDU_SANDBOX_DEFAULT_TEMPLATE", "code-agent")

# SDK reads these env vars internally
if BAIDU_SANDBOX_API_KEY:
    os.environ["E2B_API_KEY"] = BAIDU_SANDBOX_API_KEY
    os.environ["E2B_DOMAIN"] = BAIDU_SANDBOX_DOMAIN

# Wire up dispatcher
EXECUTOR_DISPATCHER_MODE = os.getenv("EXECUTOR_DISPATCHER_MODE", "docker")
EXECUTOR_CONFIG = os.getenv("EXECUTOR_CONFIG", json.dumps({
    "docker": "executor_manager.executors.docker.DockerExecutor",
    "baidu_sandbox": "executor_manager.executors.baidu_sandbox.executor.BaiduSandboxExecutor",
}))
```

## 4.7 测试策略

**单元测试**（mock e2b SDK）：

```
executor_manager/tests/executors/baidu_sandbox/
├── test_executor.py
├── test_client.py
├── test_template_mapper.py
└── test_token_provider.py
```

覆盖：
- 创建沙箱时正确组装 metadata
- 状态映射正确性
- token 获取失败的降级行为
- registry 在异常路径下不泄漏

**集成测试**（连接真实百度 sandbox，标记为 `@pytest.mark.baidu_integration`）：
- 端到端创建 → 命令执行 → 销毁
- 默认 CI 跳过，仅在专门 job 中运行

## 4.8 可观测性

复用 Wegent 现有 OpenTelemetry：

```python
@trace_async("baidu_sandbox.submit_executor")
async def submit_executor(self, task) -> Sandbox:
    ...
```

关键指标：

- `baidu_sandbox.create.duration` —— 创建耗时
- `baidu_sandbox.create.failure_rate` —— 创建失败率
- `baidu_sandbox.active_count` —— 活跃沙箱数
- `baidu_sandbox.token_fetch.failure` —— token 获取失败次数（关键告警）
