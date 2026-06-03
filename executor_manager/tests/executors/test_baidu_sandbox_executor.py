# SPDX-FileCopyrightText: 2025 Weibo, Inc.
#
# SPDX-License-Identifier: Apache-2.0

from unittest.mock import MagicMock

from executor_manager.executors.baidu_sandbox.client import BaiduSandboxClient
from executor_manager.executors.baidu_sandbox.ducc_config import build_user_config
from executor_manager.executors.baidu_sandbox.executor import BaiduSandboxExecutor
from executor_manager.executors.baidu_sandbox.token_provider import (
    BaiduSandboxTokenProvider,
)
from shared.utils.crypto import encrypt_git_token


class FakeSandbox:
    sandbox_id = "sbx123"

    def __init__(self):
        self.killed = False

    def kill(self):
        self.killed = True


class FakeRunResult:
    def __init__(self, stdout="", stderr="", exit_code=0):
        self.stdout = stdout
        self.stderr = stderr
        self.exit_code = exit_code


class FakeClient:
    def __init__(self):
        self.created = []
        self.commands = []
        self.files = []
        self.killed = []

    def create(self, *, template, timeout, metadata, envs):
        self.created.append(
            {
                "template": template,
                "timeout": timeout,
                "metadata": metadata,
                "envs": envs,
            }
        )
        return FakeSandbox()

    def wait_ready(self, sandbox_id, timeout=60):
        return {"sandbox_id": sandbox_id, "status": "running"}

    def run(self, sandbox_id, command, timeout=None):
        self.commands.append(
            {"sandbox_id": sandbox_id, "command": command, "timeout": timeout}
        )
        if "ducc -p" in command:
            return FakeRunResult(stdout="DUCC OK")
        if "ls-remote --exit-code --heads" in command:
            return FakeRunResult(stdout="abcdef refs/heads/probe-branch")
        return FakeRunResult(stdout="ready")

    def write_file(self, sandbox_id, path, data, timeout=None):
        self.files.append(
            {"sandbox_id": sandbox_id, "path": path, "data": data, "timeout": timeout}
        )

    def kill(self, sandbox_id):
        self.killed.append(sandbox_id)


class FakeCommandResultException(Exception):
    def __init__(self, stdout="", stderr="", exit_code=1):
        self.stdout = stdout
        self.stderr = stderr
        self.exit_code = exit_code


class FakeCommands:
    def __init__(self):
        self.calls = []

    def run(self, command, **kwargs):
        self.calls.append((command, kwargs))
        raise FakeCommandResultException(stderr="branch not found", exit_code=128)


class FakeSuccessfulCommands:
    def __init__(self):
        self.calls = []

    def run(self, command, **kwargs):
        self.calls.append((command, kwargs))
        return FakeRunResult(stdout="ready")


class FakeSdkSandbox:
    sandbox_id = "sbx123"

    def __init__(self):
        self.commands = FakeCommands()


class FakeFiles:
    def __init__(self):
        self.calls = []

    def write(self, path, data, **kwargs):
        self.calls.append((path, data, kwargs))
        return {"path": path}


class FakeSdkSandboxWithFiles(FakeSdkSandbox):
    def __init__(self):
        super().__init__()
        self.files = FakeFiles()


class FakeSdkSandboxWithSuccessfulCommands(FakeSdkSandbox):
    def __init__(self):
        self.commands = FakeSuccessfulCommands()


class FakeLegacyFiles:
    def __init__(self):
        self.calls = []

    def write(self, path, data):
        self.calls.append((path, data))
        return {"path": path}


class FakeSdkSandboxWithLegacyFiles(FakeSdkSandbox):
    def __init__(self):
        super().__init__()
        self.files = FakeLegacyFiles()


class FakeSandboxClass:
    created = []
    connected = []

    @classmethod
    def create(cls, **kwargs):
        cls.created.append(kwargs)
        return FakeSandbox()

    @classmethod
    def connect(cls, **kwargs):
        cls.connected.append(kwargs)
        return FakeSandbox()


class RealSdkLikeSandboxClass:
    created = []

    @classmethod
    def create(cls, **kwargs):
        from e2b.api import validate_api_key

        validate_api_key(kwargs["api_key"])
        cls.created.append(kwargs)
        return FakeSandbox()


class FakeTokenProvider:
    def get_access_token(self, task):
        return "access-token"

    def get_model_token(self):
        return "model-token"


class MissingTokenProvider(FakeTokenProvider):
    def get_model_token(self):
        raise ValueError("missing model token")


class GitCredentialTokenProvider(FakeTokenProvider):
    def get_git_credentials(self, task):
        return {
            "git_domain": "icode.baidu.com",
            "username": "icode-user",
            "password": "fake-git-password",
        }


class GitRuntimeOnlyTokenProvider(FakeTokenProvider):
    def get_git_credentials(self, task):
        return {
            "git_domain": "icode.baidu.com",
            "username": "icode-user",
            "password": "fake-git-password",
        }

    def get_ugate_token(self, task):
        return "ugate-access-token"


def _task():
    return {
        "task_id": 65,
        "subtask_id": 98,
        "prompt": "hello",
        "user": {
            "name": "admin",
            "git_login": "github-user",
            "baidu_username": "icode-user",
        },
        "sandbox_metadata": {"template": "code-agent", "timeout": 120},
    }


def test_ducc_user_config_shape():
    config = build_user_config("secret-token")

    assert config["env"]["ANTHROPIC_AUTH_TOKEN"] == "secret-token"
    assert config["env"]["ANTHROPIC_MODEL"] == "auto"
    assert config["env"]["DISABLE_BAIDU_CLAUDE_UPDATE"] == "1"


def test_token_provider_decrypts_task_user_baidu_access_token(monkeypatch):
    monkeypatch.delenv("BAIDU_SANDBOX_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("UGATE_TOKEN", raising=False)
    monkeypatch.delenv("UUAP_ACCESS_TOKEN", raising=False)
    provider = BaiduSandboxTokenProvider()

    token = provider.get_access_token(
        {"user": {"baidu_access_token": encrypt_git_token("ugate-plain-token")}}
    )

    assert token == "ugate-plain-token"


def test_token_provider_reads_openai_metadata_user_baidu_access_token(monkeypatch):
    monkeypatch.delenv("BAIDU_SANDBOX_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("UGATE_TOKEN", raising=False)
    monkeypatch.delenv("UUAP_ACCESS_TOKEN", raising=False)
    provider = BaiduSandboxTokenProvider()

    token = provider.get_access_token(
        {
            "metadata": {
                "task_id": 65,
                "user": {
                    "baidu_access_token": encrypt_git_token("metadata-ugate-token")
                },
            }
        }
    )

    assert token == "metadata-ugate-token"


def test_token_provider_prefers_plain_env_access_token(monkeypatch):
    monkeypatch.setenv("BAIDU_SANDBOX_ACCESS_TOKEN", "env-plain-token")
    provider = BaiduSandboxTokenProvider()

    token = provider.get_access_token(
        {"user": {}}
    )

    assert token == "env-plain-token"


def test_token_provider_prefers_task_baidu_access_token_over_env(monkeypatch):
    monkeypatch.setenv("BAIDU_SANDBOX_ACCESS_TOKEN", "stale-env-token")
    provider = BaiduSandboxTokenProvider()

    token = provider.get_access_token(
        {"user": {"baidu_access_token": encrypt_git_token("db-sandbox-token")}}
    )

    assert token == "db-sandbox-token"


def test_token_provider_decrypts_git_credentials_from_openai_metadata():
    provider = BaiduSandboxTokenProvider()

    credentials = provider.get_git_credentials(
        {
            "metadata": {
                "task_id": 65,
                "user": {
                    "git_domain": "icode.baidu.com",
                    "git_login": "icode-user",
                    "git_token": encrypt_git_token("plain-git-password"),
                },
            }
        }
    )

    assert credentials == {
        "git_domain": "icode.baidu.com",
        "username": "icode-user",
        "password": "plain-git-password",
    }


def test_client_uses_sdk_create_and_connect(monkeypatch):
    monkeypatch.setenv("E2B_API_KEY", "fake-key")
    FakeSandboxClass.created = []
    FakeSandboxClass.connected = []
    client = BaiduSandboxClient(sandbox_class=FakeSandboxClass)

    sandbox = client.create(template="code-agent", timeout=60, metadata={}, envs={})
    connected = client.connect("sbx123")
    client.kill("sbx123")

    assert sandbox.sandbox_id == "sbx123"
    assert connected.sandbox_id == "sbx123"
    assert sandbox.killed is True
    assert FakeSandboxClass.created[0]["template"] == "code-agent"
    assert FakeSandboxClass.connected == []


def test_client_allows_baidu_api_key_format_for_baidu_domain(monkeypatch):
    monkeypatch.setattr(
        "executor_manager.config.config.BAIDU_SANDBOX_API_KEY",
        "baidu-key-without-e2b-prefix",
    )
    monkeypatch.setattr(
        "executor_manager.config.config.BAIDU_SANDBOX_DOMAIN",
        "agent-sandbox.baidu-int.com",
    )
    monkeypatch.setenv("E2B_DOMAIN", "agent-sandbox.baidu-int.com")
    BaiduSandboxClient._sdk_patched = False
    RealSdkLikeSandboxClass.created = []

    client = BaiduSandboxClient(sandbox_class=RealSdkLikeSandboxClass)
    client._patch_baidu_sdk_api_key_validation()
    sandbox = client.create(template="code-agent", timeout=60, metadata={}, envs={})

    assert sandbox.sandbox_id == "sbx123"
    assert RealSdkLikeSandboxClass.created[0]["api_key"] == (
        "baidu-key-without-e2b-prefix"
    )
    assert RealSdkLikeSandboxClass.created[0]["domain"] == (
        "agent-sandbox.baidu-int.com"
    )


def test_client_keeps_e2b_api_key_validation_for_non_baidu_domain(monkeypatch):
    from e2b.exceptions import AuthenticationException

    monkeypatch.setattr(
        "executor_manager.config.config.BAIDU_SANDBOX_API_KEY",
        "baidu-key-without-e2b-prefix",
    )
    monkeypatch.setattr(
        "executor_manager.config.config.BAIDU_SANDBOX_DOMAIN",
        "e2b.app",
    )
    monkeypatch.setenv("E2B_DOMAIN", "e2b.app")
    BaiduSandboxClient._sdk_patched = False
    client = BaiduSandboxClient(sandbox_class=RealSdkLikeSandboxClass)
    client._patch_baidu_sdk_api_key_validation()

    try:
        client.create(template="code-agent", timeout=60, metadata={}, envs={})
    except AuthenticationException as exc:
        assert "Invalid API key format" in str(exc)
    else:
        raise AssertionError("Expected E2B API key validation to remain enabled")


def test_client_skips_api_key_patch_when_sdk_has_no_validator(monkeypatch):
    import e2b.api as e2b_api

    monkeypatch.delattr(e2b_api, "validate_api_key", raising=False)
    BaiduSandboxClient._sdk_patched = False
    client = BaiduSandboxClient(sandbox_class=FakeSandboxClass)

    client._patch_baidu_sdk_api_key_validation()

    assert BaiduSandboxClient._sdk_patched is True


def test_client_returns_command_result_exception(monkeypatch):
    monkeypatch.setenv("E2B_API_KEY", "fake-key")
    client = BaiduSandboxClient(sandbox_class=FakeSandboxClass)
    sandbox = FakeSdkSandbox()
    client._remember_sandbox(sandbox)

    result = client.run("sbx123", "git clone repo")

    assert result.exit_code == 128
    assert result.stderr == "branch not found"


def test_client_run_sets_request_timeout(monkeypatch):
    monkeypatch.setenv("E2B_API_KEY", "fake-key")
    client = BaiduSandboxClient(sandbox_class=FakeSandboxClass)
    sandbox = FakeSdkSandboxWithSuccessfulCommands()
    client._remember_sandbox(sandbox)

    client.run("sbx123", "echo ready", timeout=12)

    assert sandbox.commands.calls[0][1]["timeout"] == 12
    assert sandbox.commands.calls[0][1]["request_timeout"] == 12


def test_client_write_file_uses_sdk_files_api(monkeypatch):
    monkeypatch.setenv("E2B_API_KEY", "fake-key")
    client = BaiduSandboxClient(sandbox_class=FakeSandboxClass)
    sandbox = FakeSdkSandboxWithFiles()
    client._remember_sandbox(sandbox)

    client.write_file("sbx123", "/tmp/archive.tar.gz", b"archive", timeout=12)

    assert sandbox.files.calls[0][0] == "/tmp/archive.tar.gz"
    assert sandbox.files.calls[0][1] == b"archive"
    assert sandbox.files.calls[0][2]["request_timeout"] == 12
    assert "use_octet_stream" not in sandbox.files.calls[0][2]


def test_client_write_file_supports_legacy_sdk_signature(monkeypatch):
    monkeypatch.setenv("E2B_API_KEY", "fake-key")
    client = BaiduSandboxClient(sandbox_class=FakeSandboxClass)
    sandbox = FakeSdkSandboxWithLegacyFiles()
    client._remember_sandbox(sandbox)

    client.write_file("sbx123", "/tmp/archive.tar.gz", b"archive", timeout=12)

    assert sandbox.files.calls == [("/tmp/archive.tar.gz", b"archive")]


def test_submit_executor_creates_sandbox_and_callbacks(monkeypatch):
    fake_client = FakeClient()
    requests = MagicMock()
    requests.post.return_value.status_code = 200
    monkeypatch.setattr(
        "executor_manager.config.config.TASK_API_DOMAIN",
        "http://backend.local",
    )

    executor = BaiduSandboxExecutor(
        client=fake_client,
        token_provider=FakeTokenProvider(),
        requests_module=requests,
    )
    result = executor.submit_executor(_task())

    assert result["status"] == "success"
    assert result["executor_namespace"] == "baidu_sandbox"
    assert fake_client.created[0]["template"] == "code-agent"
    assert fake_client.created[0]["metadata"]["agent-sandbox/access-token"]
    assert "codeBean" not in fake_client.created[0]["metadata"]
    assert fake_client.created[0]["envs"]["ANTHROPIC_AUTH_TOKEN"] == "model-token"
    assert any("ducc -p hello" in item["command"] for item in fake_client.commands)
    assert requests.post.call_count >= 1


def test_submit_executor_does_not_inject_codebean_from_baidu_username(monkeypatch):
    fake_client = FakeClient()
    requests = MagicMock()
    requests.post.return_value.status_code = 200
    monkeypatch.setattr(
        "executor_manager.config.config.TASK_API_DOMAIN",
        "http://backend.local",
    )
    task = _task()

    executor = BaiduSandboxExecutor(
        client=fake_client,
        token_provider=FakeTokenProvider(),
        requests_module=requests,
    )
    result = executor.submit_executor(task)

    assert result["status"] == "success"
    assert "codeBean" not in fake_client.created[0]["metadata"]


def test_submit_executor_ignores_explicit_codebean_username(monkeypatch):
    fake_client = FakeClient()
    requests = MagicMock()
    requests.post.return_value.status_code = 200
    monkeypatch.setattr(
        "executor_manager.config.config.TASK_API_DOMAIN",
        "http://backend.local",
    )
    task = _task()
    task["user"]["baidu_sandbox_codebean_username"] = "explicit-user"

    executor = BaiduSandboxExecutor(
        client=fake_client,
        token_provider=FakeTokenProvider(),
        requests_module=requests,
    )
    result = executor.submit_executor(task)

    assert result["status"] == "success"
    assert "codeBean" not in fake_client.created[0]["metadata"]


def test_extract_prompt_reads_openai_input_string():
    executor = BaiduSandboxExecutor(
        client=FakeClient(),
        token_provider=FakeTokenProvider(),
        requests_module=MagicMock(),
    )

    prompt = executor._extract_prompt(
        {
            "input": "hello from responses input",
            "metadata": {"task_id": 65, "subtask_id": 98},
        }
    )

    assert prompt == "hello from responses input"


def test_extract_prompt_reads_last_user_message_from_openai_input():
    executor = BaiduSandboxExecutor(
        client=FakeClient(),
        token_provider=FakeTokenProvider(),
        requests_module=MagicMock(),
    )

    prompt = executor._extract_prompt(
        {
            "input": [
                {"role": "user", "content": "first user prompt"},
                {"role": "assistant", "content": "assistant reply"},
                {"role": "user", "content": "latest user prompt"},
            ],
            "metadata": {"task_id": 65, "subtask_id": 98},
        }
    )

    assert prompt == "latest user prompt"


def test_extract_prompt_reads_openai_content_blocks():
    executor = BaiduSandboxExecutor(
        client=FakeClient(),
        token_provider=FakeTokenProvider(),
        requests_module=MagicMock(),
    )

    prompt = executor._extract_prompt(
        {
            "input": [
                {"type": "input_text", "text": "first block"},
                {"type": "input_image", "image_url": "data:image/png;base64,abc"},
                {"type": "text", "text": "second block"},
            ],
            "metadata": {"task_id": 65, "subtask_id": 98},
        }
    )

    assert prompt == "first block\nsecond block"


def test_dispatch_rejects_empty_prompt_before_ducc():
    fake_client = FakeClient()
    executor = BaiduSandboxExecutor(
        client=fake_client,
        token_provider=FakeTokenProvider(),
        requests_module=MagicMock(),
    )

    try:
        executor.dispatch_task_to_instance(
            {"input": "", "metadata": {"task_id": 65, "subtask_id": 98}},
            "baidu-sandbox-sbx123",
            {"sandbox_id": "sbx123"},
        )
    except ValueError as exc:
        assert "prompt is empty" in str(exc)
    else:
        raise AssertionError("Expected empty prompt to be rejected")

    assert len(fake_client.commands) == 1
    assert not any("ducc -p" in item["command"] for item in fake_client.commands)


def test_dispatch_prepares_workspace_before_ducc_from_openai_metadata():
    fake_client = FakeClient()
    executor = BaiduSandboxExecutor(
        client=fake_client,
        token_provider=FakeTokenProvider(),
        requests_module=MagicMock(),
    )

    result = executor.dispatch_task_to_instance(
        {
            "input": "read README",
            "metadata": {
                "task_id": 65,
                "subtask_id": 98,
                "git_url": "https://github.com/wecode-ai/Wegent.git",
                "branch_name": "dev",
            },
        },
        "baidu-sandbox-sbx123",
        {"sandbox_id": "sbx123"},
    )

    assert result["status"] == "success"
    assert len(fake_client.commands) == 3
    workspace_command = fake_client.commands[1]["command"]
    assert "workspace_timeout=" in workspace_command
    assert "GIT_TERMINAL_PROMPT=0" in workspace_command
    assert "ls-remote --exit-code --heads" in workspace_command
    assert "clone --depth 1 --branch" in workspace_command
    assert "https://github.com/wecode-ai/Wegent.git" in workspace_command
    assert 'branch_name=dev' in workspace_command
    ducc_command = fake_client.commands[2]["command"]
    assert "cd /workspace" in ducc_command
    assert "timeout 300 ducc" in ducc_command
    assert "ducc -p 'read README'" in ducc_command
    assert "--permission-mode dontAsk" in ducc_command
    assert "--allowedTools 'Bash Write Edit MultiEdit Read Glob Grep LS'" in ducc_command


def test_prepare_workspace_rewrites_git_url(monkeypatch):
    monkeypatch.setattr(
        "executor_manager.config.config.BAIDU_SANDBOX_GIT_URL_REWRITES",
        '{"https://github.com/": "https://gitclone.com/github.com/"}',
    )
    fake_client = FakeClient()
    executor = BaiduSandboxExecutor(
        client=fake_client,
        token_provider=FakeTokenProvider(),
        requests_module=MagicMock(),
    )

    executor.dispatch_task_to_instance(
        {
            "input": "read README",
            "metadata": {
                "task_id": 65,
                "subtask_id": 98,
                "git_url": "https://github.com/wecode-ai/Wegent.git",
                "branch_name": "main",
            },
        },
        "baidu-sandbox-sbx123",
        {"sandbox_id": "sbx123"},
    )

    workspace_command = fake_client.commands[1]["command"]
    assert "https://gitclone.com/github.com/wecode-ai/Wegent.git" in (
        workspace_command
    )


def test_prepare_workspace_uses_git_askpass_for_matching_private_repo():
    fake_client = FakeClient()
    executor = BaiduSandboxExecutor(
        client=fake_client,
        token_provider=GitCredentialTokenProvider(),
        requests_module=MagicMock(),
    )

    executor.dispatch_task_to_instance(
        {
            "input": "read README",
            "metadata": {
                "task_id": 65,
                "subtask_id": 98,
                "git_url": "https://icode.baidu.com/baidu/hi/openclaw_infoflow",
                "branch_name": "main",
            },
        },
        "baidu-sandbox-sbx123",
        {"sandbox_id": "sbx123"},
    )

    assert fake_client.files[0]["path"] == "/tmp/wegent-git-askpass-65-98.sh"
    askpass_payload = fake_client.files[0]["data"].decode("utf-8")
    assert "icode-user" in askpass_payload
    assert "fake-git-password" in askpass_payload
    assert fake_client.files[1]["path"] == "/tmp/wegent-git-credentials-65-98"

    workspace_command = fake_client.commands[1]["command"]
    assert "GIT_ASKPASS=\"$git_askpass_path\"" in workspace_command
    assert "fake-git-password" not in workspace_command
    assert "https://icode.baidu.com/baidu/hi/openclaw_infoflow" in workspace_command

    git_runtime_command = fake_client.commands[2]["command"]
    assert "cp /tmp/wegent-git-credentials-65-98 /root/.git-credentials" in (
        git_runtime_command
    )
    assert "git config --global credential.helper store" in git_runtime_command
    assert "icode login --method ugate --token access-token" not in git_runtime_command
    assert "icode login --method ugate --token" not in git_runtime_command

    ducc_command = fake_client.commands[3]["command"]
    assert "GIT_ASKPASS=\"$git_askpass_path\"" in ducc_command
    assert "fake-git-password" not in ducc_command


def test_dispatch_ducc_uses_git_askpass_for_matching_private_repo():
    fake_client = FakeClient()
    executor = BaiduSandboxExecutor(
        client=fake_client,
        token_provider=GitCredentialTokenProvider(),
        requests_module=MagicMock(),
    )

    executor.dispatch_task_to_instance(
        {
            "input": "commit and push validation branch",
            "metadata": {
                "task_id": 65,
                "subtask_id": 98,
                "git_url": "https://icode.baidu.com/baidu/hi/openclaw_infoflow",
                "branch_name": "main",
            },
        },
        "baidu-sandbox-sbx123",
        {"sandbox_id": "sbx123"},
    )

    assert fake_client.files[0]["path"] == "/tmp/wegent-git-askpass-65-98.sh"
    assert fake_client.files[1]["path"] == "/tmp/wegent-git-credentials-65-98"
    assert fake_client.files[2]["path"] == "/tmp/wegent-git-askpass-65-98.sh"

    ducc_command = fake_client.commands[3]["command"]
    assert "export GIT_TERMINAL_PROMPT=0" in ducc_command
    assert "GIT_ASKPASS=\"$git_askpass_path\"" in ducc_command
    assert "fake-git-password" not in ducc_command
    assert "ducc -p 'commit and push validation branch'" in ducc_command
    assert "--permission-mode dontAsk" in ducc_command
    assert "--allowedTools 'Bash Write Edit MultiEdit Read Glob Grep LS'" in ducc_command


def test_prepare_git_runtime_configures_credential_store_and_icode_login():
    fake_client = FakeClient()
    executor = BaiduSandboxExecutor(
        client=fake_client,
        token_provider=GitRuntimeOnlyTokenProvider(),
        requests_module=MagicMock(),
    )

    executor.dispatch_task_to_instance(
        {
            "input": "commit and push validation branch",
            "metadata": {
                "task_id": 65,
                "subtask_id": 98,
                "git_url": "https://icode.baidu.com/baidu/hi/openclaw_infoflow",
                "branch_name": "main",
            },
        },
        "baidu-sandbox-sbx123",
        {"sandbox_id": "sbx123"},
    )

    assert fake_client.files[1]["path"] == "/tmp/wegent-git-credentials-65-98"
    credential_payload = fake_client.files[1]["data"].decode("utf-8")
    assert "icode-user:fake-git-password@icode.baidu.com" in credential_payload

    git_runtime_command = fake_client.commands[2]["command"]
    assert "cp /tmp/wegent-git-credentials-65-98 /root/.git-credentials" in (
        git_runtime_command
    )
    assert "git config --global credential.helper store" in git_runtime_command
    assert "icode login --method ugate --token ugate-access-token" in (
        git_runtime_command
    )
    assert "fake-git-password" not in git_runtime_command

    ducc_command = fake_client.commands[3]["command"]
    assert "ducc -p 'commit and push validation branch'" in ducc_command


def test_dispatch_verifies_requested_git_push_branch():
    fake_client = FakeClient()
    executor = BaiduSandboxExecutor(
        client=fake_client,
        token_provider=GitCredentialTokenProvider(),
        requests_module=MagicMock(),
    )

    result = executor.dispatch_task_to_instance(
        {
            "input": "\n".join(
                [
                    "请完成提交并推送。",
                    "git checkout -B probe-branch",
                    "git push origin probe-branch",
                ]
            ),
            "metadata": {
                "task_id": 65,
                "subtask_id": 98,
                "git_url": "https://icode.baidu.com/baidu/hi/openclaw_infoflow",
                "branch_name": "main",
            },
        },
        "baidu-sandbox-sbx123",
        {"sandbox_id": "sbx123"},
    )

    assert result["status"] == "success"
    verification_command = next(
        item["command"]
        for item in fake_client.commands
        if "Wegent git push verification OK" in item["command"]
    )
    assert "branch=probe-branch" in verification_command
    assert "ls-remote --exit-code --heads" in verification_command
    assert "GIT_ASKPASS=\"$git_askpass_path\"" in verification_command
    assert "abcdef refs/heads/probe-branch" in result["output"]


def test_dispatch_fails_when_requested_git_push_is_not_remote():
    class PushMissingClient(FakeClient):
        def run(self, sandbox_id, command, timeout=None):
            self.commands.append(
                {"sandbox_id": sandbox_id, "command": command, "timeout": timeout}
            )
            if "ducc -p" in command:
                return FakeRunResult(stdout="DUCC OK")
            if "Wegent git push verification OK" in command:
                return FakeRunResult(stderr="remote branch not found", exit_code=2)
            return FakeRunResult(stdout="ready")

    fake_client = PushMissingClient()
    executor = BaiduSandboxExecutor(
        client=fake_client,
        token_provider=GitCredentialTokenProvider(),
        requests_module=MagicMock(),
    )

    try:
        executor.dispatch_task_to_instance(
            {
                "input": "\n".join(
                    [
                        "请完成提交并上传代码。",
                        "新分支：probe-branch",
                    ]
                ),
                "metadata": {
                    "task_id": 65,
                    "subtask_id": 98,
                    "git_url": "https://icode.baidu.com/baidu/hi/openclaw_infoflow",
                    "branch_name": "main",
                },
            },
            "baidu-sandbox-sbx123",
            {"sandbox_id": "sbx123"},
        )
    except RuntimeError as exc:
        assert "Requested git push was not verified" in str(exc)
        assert "probe-branch" in str(exc)
    else:
        raise AssertionError("Expected missing pushed branch to fail")

    assert any(
        "rm -f /tmp/wegent-git-askpass-65-98.sh" in item["command"]
        for item in fake_client.commands
    )


def test_build_ducc_command_supports_configurable_permission_flags(monkeypatch):
    monkeypatch.setattr(
        "executor_manager.config.config.BAIDU_SANDBOX_DUCC_PERMISSION_MODE",
        "dontAsk",
    )
    monkeypatch.setattr(
        "executor_manager.config.config.BAIDU_SANDBOX_DUCC_ALLOWED_TOOLS",
        "Read Grep",
    )

    executor = BaiduSandboxExecutor(
        client=FakeClient(),
        token_provider=FakeTokenProvider(),
        requests_module=MagicMock(),
    )
    command = executor._build_ducc_command("inspect files")

    assert "--permission-mode dontAsk" in command
    assert "--allowedTools 'Read Grep'" in command


def test_build_ducc_command_can_omit_permission_flags(monkeypatch):
    monkeypatch.setattr(
        "executor_manager.config.config.BAIDU_SANDBOX_DUCC_PERMISSION_MODE",
        "",
    )
    monkeypatch.setattr(
        "executor_manager.config.config.BAIDU_SANDBOX_DUCC_ALLOWED_TOOLS",
        "",
    )

    executor = BaiduSandboxExecutor(
        client=FakeClient(),
        token_provider=FakeTokenProvider(),
        requests_module=MagicMock(),
    )
    command = executor._build_ducc_command("inspect files")

    assert "--permission-mode" not in command
    assert "--allowedTools" not in command


def test_prepare_workspace_ignores_git_credentials_for_domain_mismatch():
    fake_client = FakeClient()
    executor = BaiduSandboxExecutor(
        client=fake_client,
        token_provider=GitCredentialTokenProvider(),
        requests_module=MagicMock(),
    )

    executor.dispatch_task_to_instance(
        {
            "input": "read README",
            "metadata": {
                "task_id": 65,
                "subtask_id": 98,
                "git_url": "https://github.com/wecode-ai/Wegent.git",
                "branch_name": "main",
            },
        },
        "baidu-sandbox-sbx123",
        {"sandbox_id": "sbx123"},
    )

    assert fake_client.files == []
    workspace_command = fake_client.commands[1]["command"]
    assert "GIT_ASKPASS=/bin/false" in workspace_command
    assert "fake-git-password" not in workspace_command


def test_prepare_workspace_uses_local_archive_fallback_for_clone_network_error(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(
        "executor_manager.config.config.BAIDU_SANDBOX_WORKSPACE_UPLOAD_FALLBACK",
        True,
    )
    monkeypatch.setattr(
        "executor_manager.config.config.BAIDU_SANDBOX_WORKSPACE_ARCHIVE_MAX_BYTES",
        1024 * 1024,
    )

    class CloneFailingClient(FakeClient):
        def run(self, sandbox_id, command, timeout=None):
            self.commands.append(
                {"sandbox_id": sandbox_id, "command": command, "timeout": timeout}
            )
            if "clone --depth" in command:
                return FakeRunResult(
                    stderr=(
                        "fatal: unable to access "
                        "'https://github.com/wecode-ai/Wegent.git/': "
                        "Operation too slow"
                    ),
                    exit_code=128,
                )
            if "tar -xzf" in command:
                return FakeRunResult(stdout="extracted")
            if "ducc -p" in command:
                return FakeRunResult(stdout="DUCC OK")
            return FakeRunResult(stdout="ready")

    fake_client = CloneFailingClient()
    executor = BaiduSandboxExecutor(
        client=fake_client,
        token_provider=FakeTokenProvider(),
        requests_module=MagicMock(),
    )
    archive_path = tmp_path / "workspace.tar.gz"
    archive_path.write_bytes(b"archive")
    monkeypatch.setattr(
        executor,
        "_build_local_workspace_archive",
        lambda git_url, branch_name, target, git_credentials=None: target.write_bytes(
            archive_path.read_bytes()
        ),
    )

    executor.dispatch_task_to_instance(
        {
            "input": "read README",
            "metadata": {
                "task_id": 65,
                "subtask_id": 98,
                "git_url": "https://github.com/wecode-ai/Wegent.git",
                "branch_name": "main",
            },
        },
        "baidu-sandbox-sbx123",
        {"sandbox_id": "sbx123"},
    )

    assert fake_client.files[0]["path"] == "/tmp/wegent-workspace.tar.gz"
    assert any("tar -xzf" in item["command"] for item in fake_client.commands)
    assert any("ducc -p 'read README'" in item["command"] for item in fake_client.commands)


def test_prepare_workspace_does_not_fallback_for_repository_mismatch(monkeypatch):
    monkeypatch.setattr(
        "executor_manager.config.config.BAIDU_SANDBOX_WORKSPACE_UPLOAD_FALLBACK",
        True,
    )

    class MismatchClient(FakeClient):
        def run(self, sandbox_id, command, timeout=None):
            self.commands.append(
                {"sandbox_id": sandbox_id, "command": command, "timeout": timeout}
            )
            if "clone --depth" in command:
                return FakeRunResult(
                    stderr="Workspace already contains a different git repository.",
                    exit_code=2,
                )
            return FakeRunResult(stdout="ready")

    fake_client = MismatchClient()
    executor = BaiduSandboxExecutor(
        client=fake_client,
        token_provider=FakeTokenProvider(),
        requests_module=MagicMock(),
    )

    try:
        executor.dispatch_task_to_instance(
            {
                "input": "hello",
                "metadata": {
                    "task_id": 65,
                    "subtask_id": 98,
                    "git_url": "https://github.com/wecode-ai/Wegent.git",
                },
            },
            "baidu-sandbox-sbx123",
            {"sandbox_id": "sbx123"},
        )
    except RuntimeError as exc:
        assert "Workspace preparation failed" in str(exc)
    else:
        raise AssertionError("Expected repository mismatch to fail")

    assert fake_client.files == []


def test_dispatch_skips_workspace_prepare_without_git_url():
    fake_client = FakeClient()
    executor = BaiduSandboxExecutor(
        client=fake_client,
        token_provider=FakeTokenProvider(),
        requests_module=MagicMock(),
    )

    executor.dispatch_task_to_instance(
        {"input": "hello", "metadata": {"task_id": 65, "subtask_id": 98}},
        "baidu-sandbox-sbx123",
        {"sandbox_id": "sbx123"},
    )

    assert len(fake_client.commands) == 2
    assert not any("git clone" in item["command"] for item in fake_client.commands)


def test_dispatch_rejects_workspace_git_url_with_embedded_credentials():
    fake_client = FakeClient()
    executor = BaiduSandboxExecutor(
        client=fake_client,
        token_provider=FakeTokenProvider(),
        requests_module=MagicMock(),
    )

    try:
        executor.dispatch_task_to_instance(
            {
                "input": "hello",
                "metadata": {
                    "task_id": 65,
                    "subtask_id": 98,
                    "git_url": "https://token@github.com/wecode-ai/Wegent.git",
                },
            },
            "baidu-sandbox-sbx123",
            {"sandbox_id": "sbx123"},
        )
    except ValueError as exc:
        assert "embedded credentials" in str(exc)
    else:
        raise AssertionError("Expected embedded credentials to be rejected")

    assert len(fake_client.commands) == 1


def test_submit_executor_reuses_existing_sandbox(monkeypatch):
    fake_client = FakeClient()
    requests = MagicMock()
    requests.post.return_value.status_code = 200
    monkeypatch.setattr(
        "executor_manager.config.config.TASK_API_DOMAIN",
        "http://backend.local",
    )

    task = _task()
    task["executor_name"] = "baidu-sandbox-sbx123"
    task["prompt"] = "follow up"
    executor = BaiduSandboxExecutor(
        client=fake_client,
        token_provider=FakeTokenProvider(),
        requests_module=requests,
    )

    result = executor.submit_executor(task)

    assert result["status"] == "success"
    assert result["executor_name"] == "baidu-sandbox-sbx123"
    assert fake_client.created == []
    assert any(
        item["sandbox_id"] == "sbx123" and "ducc -p 'follow up'" in item["command"]
        for item in fake_client.commands
    )
    assert requests.post.call_count >= 1


def test_submit_executor_uses_backend_url_for_callback(monkeypatch):
    fake_client = FakeClient()
    requests = MagicMock()
    requests.post.return_value.status_code = 200
    monkeypatch.setattr(
        "executor_manager.config.config.TASK_API_DOMAIN",
        "http://stale-backend.local",
    )
    task = _task()
    task["backend_url"] = "http://fresh-backend.local"

    executor = BaiduSandboxExecutor(
        client=fake_client,
        token_provider=FakeTokenProvider(),
        requests_module=requests,
    )
    result = executor.submit_executor(task)

    assert result["status"] == "success"
    assert requests.post.call_args[0][0] == (
        "http://fresh-backend.local/api/internal/callback"
    )


def test_delete_executor_accepts_executor_name():
    fake_client = FakeClient()
    executor = BaiduSandboxExecutor(
        client=fake_client,
        token_provider=FakeTokenProvider(),
        requests_module=MagicMock(),
    )

    result = executor.delete_executor("baidu-sandbox-sbx123")

    assert result["status"] == "success"
    assert fake_client.killed == ["sbx123"]


def test_submit_executor_failure_does_not_report_success_executor():
    requests = MagicMock()
    requests.post.return_value.status_code = 200
    executor = BaiduSandboxExecutor(
        client=FakeClient(),
        token_provider=MissingTokenProvider(),
        requests_module=requests,
    )

    result = executor.submit_executor(_task())

    assert result["status"] == "failed"
    assert result["executor_name"] == ""
    assert "missing model token" in result["error_msg"]
    requests.post.assert_called_once()


def test_submit_executor_failure_callback_uses_actual_sandbox_executor_name():
    class DuccFailingClient(FakeClient):
        def run(self, sandbox_id, command, timeout=None):
            self.commands.append(
                {"sandbox_id": sandbox_id, "command": command, "timeout": timeout}
            )
            if "ducc -p" in command:
                return FakeRunResult(stderr="timed out", exit_code=124)
            return FakeRunResult(stdout="ready")

    requests = MagicMock()
    requests.post.return_value.status_code = 200
    executor = BaiduSandboxExecutor(
        client=DuccFailingClient(),
        token_provider=FakeTokenProvider(),
        requests_module=requests,
    )

    result = executor.submit_executor(_task())

    assert result["status"] == "failed"
    assert result["executor_name"] == ""
    payload = requests.post.call_args.kwargs["json"]
    assert payload["executor_name"] == "baidu-sandbox-sbx123"
    assert payload["executor_namespace"] == "baidu_sandbox"


def test_submit_executor_background_failure_defers_callback_to_queue():
    requests = MagicMock()
    requests.post.return_value.status_code = 200
    task = _task()
    task["background"] = True
    executor = BaiduSandboxExecutor(
        client=FakeClient(),
        token_provider=MissingTokenProvider(),
        requests_module=requests,
    )

    result = executor.submit_executor(task)

    assert result["status"] == "failed"
    assert result["executor_name"] == ""
    requests.post.assert_not_called()
