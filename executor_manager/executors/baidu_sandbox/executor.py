# SPDX-FileCopyrightText: 2025 Weibo, Inc.
#
# SPDX-License-Identifier: Apache-2.0

"""Baidu Agent Sandbox executor."""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import tarfile
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional, Union
from urllib.parse import quote, urlsplit

import requests

from executor_manager.config import config
from executor_manager.executors.baidu_sandbox.client import BaiduSandboxClient
from executor_manager.executors.baidu_sandbox.ducc_config import serialize_user_config
from executor_manager.executors.baidu_sandbox.token_provider import (
    BaiduSandboxTokenProvider,
)
from executor_manager.executors.base import Executor
from executor_manager.utils.executor_name import generate_executor_name
from shared.logger import setup_logger
from shared.models.execution import ExecutionRequest
from shared.models.openai_converter import get_metadata_field
from shared.models.responses_api import ResponsesAPIEventBuilder
from shared.status import TaskStatus
from shared.utils.http_client import traced_session
from shared.utils.url_util import domains_match

logger = setup_logger(__name__)

SANDBOX_WORKSPACE_ARCHIVE_PATH = "/tmp/wegent-workspace.tar.gz"


class BaiduSandboxExecutor(Executor):
    """Run Wegent tasks in Baidu Agent Sandbox through DUCC."""

    def __init__(
        self,
        client: Optional[BaiduSandboxClient] = None,
        token_provider: Optional[BaiduSandboxTokenProvider] = None,
        requests_module=None,
    ):
        self.client = client or BaiduSandboxClient()
        self.token_provider = token_provider or BaiduSandboxTokenProvider()
        self.requests = requests_module or traced_session()

    def submit_executor(
        self,
        task: Union[Dict[str, Any], ExecutionRequest],
        callback: Optional[callable] = None,
    ) -> Dict[str, Any]:
        """Create a sandbox, write DUCC config, run the prompt, and callback."""
        task_dict = task.to_dict() if isinstance(task, ExecutionRequest) else task
        task_info = self._extract_task_info(task_dict)
        requested_executor_name = task_info["executor_name"] or generate_executor_name(
            task_info["task_id"],
            task_info["subtask_id"],
            task_info["user_name"],
        )

        status = {
            "status": "success",
            "progress": 100,
            "error_msg": "",
            "callback_status": TaskStatus.SUCCESS.value,
            "executor_name": requested_executor_name,
            "executor_namespace": "baidu_sandbox",
        }
        actual_executor_name = ""

        try:
            if self._is_sandbox_executor_name(requested_executor_name):
                executor_name = requested_executor_name
                task_dict["_baidu_sandbox_id"] = self._sandbox_id_from_executor_name(
                    executor_name
                )
                logger.info(
                    "[BaiduSandboxExecutor] Reusing sandbox task_id=%s sandbox_id=%s",
                    task_info["task_id"],
                    task_dict["_baidu_sandbox_id"],
                )
            else:
                self.create_instance(task_dict, task_info, requested_executor_name)
                sandbox_id = task_dict.get("_baidu_sandbox_id")
                if not sandbox_id:
                    raise RuntimeError("Baidu sandbox creation returned no sandbox_id")
                executor_name = self._executor_name_from_sandbox_id(sandbox_id)

            actual_executor_name = executor_name
            status["executor_name"] = executor_name
            ready_info = self.wait_instance_ready(executor_name)
            dispatch_result = self.dispatch_task_to_instance(
                task_dict, executor_name, ready_info
            )
            output = dispatch_result.get("output", "")
            self._send_success_callback(task_dict, executor_name, output)
        except Exception as exc:
            error_msg = str(exc)
            status.update(
                {
                    "status": "failed",
                    "error_msg": error_msg,
                    "callback_status": TaskStatus.FAILED.value,
                    "executor_name": "",
                }
            )
            logger.exception(
                "[BaiduSandboxExecutor] Task failed task_id=%s executor=%s",
                task_info["task_id"],
                actual_executor_name or requested_executor_name,
            )
            if self._should_send_failure_callback(task_dict):
                self._send_error_callback(
                    task_dict,
                    actual_executor_name or requested_executor_name,
                    error_msg,
                )

        return self._create_result_response(status)

    def create_instance(
        self, task: Dict[str, Any], task_info: Dict[str, Any], executor_name: str
    ) -> None:
        """Create a Baidu sandbox and bind its id to executor_name."""
        model_token = self.token_provider.get_model_token()
        access_token = self.token_provider.get_access_token(task)
        metadata = self._build_metadata(task, task_info, executor_name, access_token)
        envs = self._build_envs(access_token, model_token)
        template = self._resolve_template(task)

        logger.info(
            "[BaiduSandboxExecutor] Creating sandbox template=%s task_id=%s",
            template,
            task_info["task_id"],
        )
        logger.info(
            "[BaiduSandboxExecutor] Sandbox auth metadata task_id=%s "
            "codebean=%s access_token=%s",
            task_info["task_id"],
            "disabled",
            "set" if access_token else "missing",
        )
        sandbox = self.client.create(
            template=template,
            timeout=self._resolve_timeout(task),
            metadata=metadata,
            envs=envs,
        )
        sandbox_id = getattr(sandbox, "sandbox_id", None)
        if not sandbox_id:
            raise RuntimeError("Baidu sandbox creation returned no sandbox_id")

        task["_baidu_sandbox_id"] = sandbox_id
        task["_baidu_model_token"] = model_token
        logger.info(
            "[BaiduSandboxExecutor] Created sandbox task_id=%s sandbox_id=%s",
            task_info["task_id"],
            sandbox_id,
        )

    def wait_instance_ready(self, executor_name: str) -> Dict[str, Any]:
        """Resolve sandbox id from executor_name and wait until ready."""
        sandbox_id = self._sandbox_id_from_executor_name(executor_name)
        return self.client.wait_ready(sandbox_id, timeout=60)

    def dispatch_task_to_instance(
        self,
        task: Dict[str, Any],
        executor_name: str,
        ready_info: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Write DUCC config and submit the task prompt."""
        sandbox_id = ready_info.get("sandbox_id") or self._sandbox_id_from_executor_name(
            executor_name
        )
        model_token = (
            task.get("_baidu_model_token") or self.token_provider.get_model_token()
        )
        self._write_ducc_config(sandbox_id, model_token)
        self._prepare_workspace(sandbox_id, task)
        self._prepare_git_runtime(sandbox_id, task)
        ducc_git_askpass_path = self._prepare_ducc_git_askpass(sandbox_id, task)

        try:
            prompt = self._extract_prompt(task)
            if not prompt.strip():
                raise ValueError(
                    "Baidu sandbox prompt is empty; expected OpenAI Responses input "
                    "or ExecutionRequest.prompt"
                )
            logger.info(
                "[BaiduSandboxExecutor] Dispatching DUCC task_id=%s subtask_id=%s "
                "prompt_length=%s",
                get_metadata_field(task, "task_id", 0),
                get_metadata_field(task, "subtask_id", 0),
                len(prompt),
            )
            command = self._build_ducc_command(prompt, ducc_git_askpass_path)
            result = self.client.run(
                sandbox_id,
                command,
                timeout=config.BAIDU_SANDBOX_DUCC_TIMEOUT + 30,
            )
            stdout = (getattr(result, "stdout", "") or "").strip()
            stderr = (getattr(result, "stderr", "") or "").strip()
            self._raise_if_command_failed(result, "DUCC command")

            output_parts = [part for part in (stdout or stderr,) if part]
            verification_output = self._verify_requested_git_push(
                sandbox_id,
                prompt,
                ducc_git_askpass_path,
            )
            if verification_output:
                output_parts.append(verification_output)

            output = "\n\n".join(output_parts)
            if not output:
                output = "DUCC finished without output."
            return {"status": "success", "output": output, "stderr": stderr}
        finally:
            self._cleanup_sandbox_file(sandbox_id, ducc_git_askpass_path)

    def delete_executor(self, pod_name: str) -> Dict[str, Any]:
        """Kill the Baidu sandbox mapped by executor name or sandbox id."""
        sandbox_id = self._sandbox_id_from_executor_name(pod_name, default=pod_name)
        try:
            self.client.kill(sandbox_id)
            return {"status": "success"}
        except Exception as exc:
            return {"status": "failed", "error_msg": str(exc)}

    def get_current_task_ids(
        self, label_selector: Optional[str] = None
    ) -> Dict[str, Any]:
        """Listing remote sandboxes is not supported by the MVP SDK path."""
        return {"task_ids": []}

    def get_executor_count(
        self, label_selector: Optional[str] = None
    ) -> Dict[str, Any]:
        """Return best-effort active count."""
        return {"running": 0}

    def get_container_status(self, executor_name: str) -> Dict[str, Any]:
        """Return best-effort sandbox status."""
        sandbox_id = self._sandbox_id_from_executor_name(
            executor_name, default=executor_name
        )
        try:
            self.client.run(sandbox_id, "echo status", timeout=10)
            return {
                "exists": True,
                "status": "running",
                "oom_killed": False,
                "exit_code": 0,
                "error_msg": "",
            }
        except Exception as exc:
            return {
                "exists": False,
                "status": "unknown",
                "oom_killed": False,
                "exit_code": None,
                "error_msg": str(exc),
            }

    def _extract_task_info(self, task: Dict[str, Any]) -> Dict[str, Any]:
        task_id = get_metadata_field(task, "task_id", 0)
        subtask_id = get_metadata_field(task, "subtask_id", 0)
        user_config = get_metadata_field(task, "user", {}) or {}
        user_name = user_config.get("name") or user_config.get("user_name") or "unknown"
        return {
            "task_id": task_id,
            "subtask_id": subtask_id,
            "user_name": user_name,
            "executor_name": get_metadata_field(task, "executor_name"),
        }

    def _build_metadata(
        self,
        task: Dict[str, Any],
        task_info: Dict[str, Any],
        executor_name: str,
        access_token: Optional[str],
    ) -> Dict[str, str]:
        metadata = {
            "agent-sandbox/name": executor_name,
            "wegent/task-id": str(task_info["task_id"]),
            "wegent/subtask-id": str(task_info["subtask_id"]),
        }
        if access_token:
            metadata["agent-sandbox/access-token"] = access_token

        return metadata

    def _build_envs(
        self, access_token: Optional[str], model_token: str
    ) -> Dict[str, str]:
        envs = {"ANTHROPIC_AUTH_TOKEN": model_token}
        if access_token:
            envs["COMATE_AUTH_TOKEN"] = access_token
        return envs

    def _resolve_template(self, task: Dict[str, Any]) -> str:
        sandbox_metadata = get_metadata_field(task, "sandbox_metadata", {}) or {}
        return (
            sandbox_metadata.get("template")
            or get_metadata_field(task, "baidu_sandbox_template")
            or config.BAIDU_SANDBOX_TEMPLATE
        )

    def _resolve_timeout(self, task: Dict[str, Any]) -> int:
        sandbox_metadata = get_metadata_field(task, "sandbox_metadata", {}) or {}
        timeout = sandbox_metadata.get("timeout") or config.BAIDU_SANDBOX_TIMEOUT
        return int(timeout)

    def _extract_prompt(self, task: Dict[str, Any]) -> str:
        prompt = get_metadata_field(task, "prompt", None)
        prompt_text = self._input_to_prompt_text(prompt)
        if prompt_text.strip():
            return prompt_text
        return self._input_to_prompt_text(task.get("input", ""))

    @classmethod
    def _input_to_prompt_text(cls, input_data: Any) -> str:
        if input_data is None:
            return ""
        if isinstance(input_data, str):
            return input_data
        if isinstance(input_data, list):
            if cls._is_message_list(input_data):
                return cls._messages_to_prompt_text(input_data)
            return cls._content_blocks_to_text(input_data)
        return str(input_data)

    @staticmethod
    def _is_message_list(items: list[Any]) -> bool:
        return any(isinstance(item, dict) and "role" in item for item in items)

    @classmethod
    def _messages_to_prompt_text(cls, messages: list[Any]) -> str:
        last_user_content: Any = ""
        for message in messages:
            if isinstance(message, dict) and message.get("role") == "user":
                last_user_content = message.get("content", "")
        return cls._input_to_prompt_text(last_user_content)

    @staticmethod
    def _content_blocks_to_text(blocks: list[Any]) -> str:
        texts: list[str] = []
        for block in blocks:
            if isinstance(block, str):
                texts.append(block)
                continue
            if not isinstance(block, dict):
                continue
            block_type = block.get("type")
            if block_type not in ("input_text", "text", "output_text"):
                continue
            text = block.get("text") or block.get("content") or ""
            if isinstance(text, str) and text:
                texts.append(text)
        return "\n".join(texts)

    def _prepare_workspace(self, sandbox_id: str, task: Dict[str, Any]) -> None:
        workspace = self._extract_workspace(task)
        git_url = workspace.get("git_url", "")
        if not git_url:
            return
        if self._has_embedded_credentials(git_url):
            raise ValueError(
                "Baidu sandbox workspace git_url must not contain embedded credentials"
            )
        clone_url = self._rewrite_git_url(git_url)
        if self._has_embedded_credentials(clone_url):
            raise ValueError(
                "Baidu sandbox rewritten git_url must not contain embedded credentials"
            )

        timeout = int(config.BAIDU_SANDBOX_WORKSPACE_TIMEOUT)
        git_credentials = self._resolve_git_credentials(task, clone_url)
        git_askpass_path = ""
        if git_credentials:
            git_askpass_path = self._git_askpass_path(task)
            self._write_git_askpass_script(
                sandbox_id=sandbox_id,
                path=git_askpass_path,
                credentials=git_credentials,
                timeout=timeout,
            )
            logger.info(
                "[BaiduSandboxExecutor] Workspace git credentials enabled "
                "task_id=%s git_url_host=%s",
                get_metadata_field(task, "task_id", 0),
                urlsplit(clone_url).netloc or "<unknown>",
            )

        command = self._build_workspace_prepare_command(
            git_url=clone_url,
            branch_name=workspace.get("branch_name", ""),
            git_askpass_path=git_askpass_path,
        )
        result = self.client.run(
            sandbox_id,
            command,
            timeout=timeout + 30,
        )
        if not self._command_failed(result):
            return

        if not self._should_use_local_archive_fallback(result):
            self._raise_if_command_failed(result, "Workspace preparation")

        failure = self._command_failure_message(result)
        logger.warning(
            "[BaiduSandboxExecutor] Sandbox git clone failed; trying local "
            "archive fallback. git_url_host=%s branch=%s error=%s",
            urlsplit(git_url).netloc or "<unknown>",
            workspace.get("branch_name") or "<default>",
            failure,
        )
        try:
            self._prepare_workspace_from_local_archive(
                sandbox_id=sandbox_id,
                git_url=git_url,
                branch_name=workspace.get("branch_name", ""),
                git_credentials=git_credentials,
            )
        except Exception as exc:
            raise RuntimeError(
                f"Workspace preparation failed in sandbox ({failure}); "
                f"local archive fallback also failed: {exc}"
            ) from exc

    def _prepare_ducc_git_askpass(self, sandbox_id: str, task: Dict[str, Any]) -> str:
        workspace = self._extract_workspace(task)
        git_url = workspace.get("git_url", "")
        if not git_url or self._has_embedded_credentials(git_url):
            return ""

        clone_url = self._rewrite_git_url(git_url)
        if self._has_embedded_credentials(clone_url):
            return ""

        git_credentials = self._resolve_git_credentials(task, clone_url)
        if not git_credentials:
            return ""

        git_askpass_path = self._git_askpass_path(task)
        self._write_git_askpass_script(
            sandbox_id=sandbox_id,
            path=git_askpass_path,
            credentials=git_credentials,
            timeout=int(config.BAIDU_SANDBOX_DUCC_TIMEOUT),
        )
        logger.info(
            "[BaiduSandboxExecutor] DUCC git credentials enabled "
            "task_id=%s git_url_host=%s",
            get_metadata_field(task, "task_id", 0),
            urlsplit(clone_url).netloc or "<unknown>",
        )
        return git_askpass_path

    def _extract_workspace(self, task: Dict[str, Any]) -> Dict[str, str]:
        workspace = get_metadata_field(task, "workspace", {}) or {}
        repository = workspace.get("repository") or {}
        git_url = (
            get_metadata_field(task, "git_url")
            or workspace.get("git_url")
            or workspace.get("gitUrl")
            or repository.get("gitUrl")
            or ""
        )
        branch_name = (
            get_metadata_field(task, "branch_name")
            or workspace.get("branch_name")
            or workspace.get("branch")
            or repository.get("branchName")
            or ""
        )
        return {"git_url": str(git_url).strip(), "branch_name": str(branch_name).strip()}

    def _prepare_git_runtime(self, sandbox_id: str, task: Dict[str, Any]) -> None:
        workspace = self._extract_workspace(task)
        git_url = workspace.get("git_url", "")
        if not git_url:
            return

        clone_url = self._rewrite_git_url(git_url)
        git_credentials = self._resolve_git_credentials(task, clone_url)
        ugate_token = ""
        get_ugate_token = getattr(self.token_provider, "get_ugate_token", None)
        if callable(get_ugate_token):
            ugate_token = get_ugate_token(task) or ""
        if not git_credentials and not ugate_token:
            return

        credential_store_path = ""
        if git_credentials:
            credential_store_path = self._git_credentials_store_path(task)
            self._write_git_credentials_store(
                sandbox_id=sandbox_id,
                path=credential_store_path,
                git_url=clone_url,
                credentials=git_credentials,
                timeout=int(config.BAIDU_SANDBOX_WORKSPACE_TIMEOUT),
            )

        command = self._build_git_runtime_prepare_command(
            credential_store_path=credential_store_path,
            ugate_token=ugate_token,
        )
        result = self.client.run(
            sandbox_id,
            command,
            timeout=int(config.BAIDU_SANDBOX_WORKSPACE_TIMEOUT) + 30,
        )
        self._raise_if_command_failed(result, "Baidu sandbox git runtime prepare")

        logger.info(
            "[BaiduSandboxExecutor] Prepared git runtime task_id=%s git_url_host=%s "
            "credential_store=%s ugate_login=%s",
            get_metadata_field(task, "task_id", 0),
            urlsplit(clone_url).netloc or "<unknown>",
            "enabled" if credential_store_path else "disabled",
            "enabled" if ugate_token else "disabled",
        )

    @staticmethod
    def _build_workspace_prepare_command(
        git_url: str, branch_name: str = "", git_askpass_path: str = ""
    ) -> str:
        git_url_value = shlex.quote(git_url)
        branch_value = shlex.quote(branch_name)
        askpass_value = shlex.quote(git_askpass_path)
        timeout = int(config.BAIDU_SANDBOX_WORKSPACE_TIMEOUT)
        timeout_value = shlex.quote(str(timeout))
        return "\n".join(
            [
                "set -eu",
                "workspace_dir=/workspace",
                f"git_url={git_url_value}",
                f"branch_name={branch_value}",
                f"git_askpass_path={askpass_value}",
                f"workspace_timeout={timeout_value}",
                "export GIT_TERMINAL_PROMPT=0",
                'if [ -n "$git_askpass_path" ]; then',
                '  chmod 700 "$git_askpass_path"',
                '  export GIT_ASKPASS="$git_askpass_path"',
                "  trap 'rm -f \"$git_askpass_path\"' EXIT",
                "else",
                "  export GIT_ASKPASS=/bin/false",
                "fi",
                'mkdir -p "$workspace_dir"',
                'if [ -d "$workspace_dir/.git" ]; then',
                '  cd "$workspace_dir"',
                '  existing_url="$(git config --get remote.origin.url || true)"',
                '  if [ "$existing_url" != "$git_url" ]; then',
                '    echo "Workspace already contains a different git repository." >&2',
                "    exit 2",
                "  fi",
                '  if [ -n "$branch_name" ]; then',
                '    current_branch="$(git rev-parse --abbrev-ref HEAD || true)"',
                '    if [ "$current_branch" != "$branch_name" ]; then',
                '      timeout "$workspace_timeout" git -c http.lowSpeedLimit=1 -c http.lowSpeedTime=15 checkout "$branch_name"',
                "    fi",
                "  fi",
                "else",
                '  find "$workspace_dir" -mindepth 1 -maxdepth 1 -exec rm -rf {} +',
                '  if [ -n "$branch_name" ]; then',
                '    timeout "$workspace_timeout" git -c http.lowSpeedLimit=1 -c http.lowSpeedTime=15 ls-remote --exit-code --heads "$git_url" "$branch_name" >/dev/null',
                '    timeout "$workspace_timeout" git -c http.lowSpeedLimit=1 -c http.lowSpeedTime=15 clone --depth 1 --branch "$branch_name" "$git_url" "$workspace_dir"',
                "  else",
                '    timeout "$workspace_timeout" git -c http.lowSpeedLimit=1 -c http.lowSpeedTime=15 clone --depth 1 "$git_url" "$workspace_dir"',
                "  fi",
                "fi",
            ]
        )

    @staticmethod
    def _build_git_runtime_prepare_command(
        credential_store_path: str = "",
        ugate_token: Optional[str] = None,
    ) -> str:
        commands = [
            "set -eu",
            "mkdir -p /root",
        ]

        if credential_store_path:
            credential_store_value = shlex.quote(credential_store_path)
            commands.extend(
                [
                    f"cp {credential_store_value} /root/.git-credentials",
                    "chmod 600 /root/.git-credentials",
                    "git config --global credential.helper store",
                ]
            )

        if ugate_token:
            ugate_value = shlex.quote(ugate_token)
            commands.extend(
                [
                    'if command -v icode >/dev/null 2>&1; then',
                    (
                        "  timeout 30 icode login --method ugate --token "
                        f"{ugate_value} >/tmp/wegent-icode-login.log 2>&1 || true"
                    ),
                    "fi",
                ]
            )

        return "\n".join(commands)

    def _write_git_credentials_store(
        self,
        sandbox_id: str,
        path: str,
        git_url: str,
        credentials: Dict[str, str],
        timeout: int,
    ) -> None:
        host = urlsplit(git_url).hostname or credentials.get("git_domain") or ""
        encoded_username = quote(credentials["username"], safe="")
        encoded_password = quote(credentials["password"], safe="")
        payload = (
            f"https://{encoded_username}:{encoded_password}@{host}\n".encode("utf-8")
        )
        self.client.write_file(sandbox_id, path, payload, timeout=timeout + 30)

    @staticmethod
    def _has_embedded_credentials(git_url: str) -> bool:
        if "://" not in git_url:
            return False
        parsed = urlsplit(git_url)
        return bool(parsed.username or parsed.password)

    @staticmethod
    def _rewrite_git_url(git_url: str) -> str:
        rewrites = config.BAIDU_SANDBOX_GIT_URL_REWRITES.strip()
        if not rewrites:
            return git_url
        try:
            rules = json.loads(rewrites)
        except json.JSONDecodeError as exc:
            raise ValueError(
                "BAIDU_SANDBOX_GIT_URL_REWRITES must be a JSON object"
            ) from exc
        if not isinstance(rules, dict):
            raise ValueError("BAIDU_SANDBOX_GIT_URL_REWRITES must be a JSON object")
        for source_prefix, target_prefix in rules.items():
            if not isinstance(source_prefix, str) or not isinstance(target_prefix, str):
                raise ValueError(
                    "BAIDU_SANDBOX_GIT_URL_REWRITES keys and values must be strings"
                )
            if source_prefix and git_url.startswith(source_prefix):
                return f"{target_prefix}{git_url[len(source_prefix):]}"
        return git_url

    def _prepare_workspace_from_local_archive(
        self,
        sandbox_id: str,
        git_url: str,
        branch_name: str,
        git_credentials: Optional[Dict[str, str]] = None,
    ) -> None:
        timeout = int(config.BAIDU_SANDBOX_WORKSPACE_TIMEOUT)
        with tempfile.TemporaryDirectory(prefix="wegent-baidu-workspace-") as tmp_dir:
            archive_path = Path(tmp_dir) / "workspace.tar.gz"
            self._build_local_workspace_archive(
                git_url, branch_name, archive_path, git_credentials
            )
            self._enforce_workspace_archive_size(archive_path)
            with archive_path.open("rb") as archive_file:
                self.client.write_file(
                    sandbox_id,
                    SANDBOX_WORKSPACE_ARCHIVE_PATH,
                    archive_file,
                    timeout=timeout + 30,
                )
        result = self.client.run(
            sandbox_id,
            self._build_workspace_extract_command(SANDBOX_WORKSPACE_ARCHIVE_PATH),
            timeout=timeout + 30,
        )
        self._raise_if_command_failed(result, "Workspace archive extraction")

    def _build_local_workspace_archive(
        self,
        git_url: str,
        branch_name: str,
        archive_path: Path,
        git_credentials: Optional[Dict[str, str]] = None,
    ) -> None:
        timeout = int(config.BAIDU_SANDBOX_WORKSPACE_TIMEOUT)
        with tempfile.TemporaryDirectory(prefix="wegent-baidu-clone-") as tmp_dir:
            repo_dir = Path(tmp_dir) / "repo"
            clone_command = [
                "git",
                "-c",
                "http.lowSpeedLimit=1",
                "-c",
                "http.lowSpeedTime=15",
                "clone",
                "--depth",
                "1",
            ]
            if branch_name:
                clone_command.extend(["--branch", branch_name])
            clone_command.extend([git_url, str(repo_dir)])
            env = os.environ.copy()
            env["GIT_TERMINAL_PROMPT"] = "0"
            if git_credentials:
                askpass_path = Path(tmp_dir) / "git-askpass.sh"
                askpass_path.write_text(
                    self._build_git_askpass_script(git_credentials),
                    encoding="utf-8",
                )
                askpass_path.chmod(0o700)
                env["GIT_ASKPASS"] = str(askpass_path)
            else:
                env.pop("GIT_ASKPASS", None)
            try:
                subprocess.run(
                    clone_command,
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    env=env,
                )
            except subprocess.CalledProcessError as exc:
                detail = (exc.stderr or exc.stdout or "").strip()
                raise RuntimeError(
                    f"local git clone failed with exit_code={exc.returncode}: {detail}"
                ) from exc
            except subprocess.TimeoutExpired as exc:
                raise RuntimeError(
                    f"local git clone timed out after {timeout}s"
                ) from exc

            self._write_tar_archive(repo_dir, archive_path)

    def _resolve_git_credentials(
        self, task: Dict[str, Any], git_url: str
    ) -> Optional[Dict[str, str]]:
        get_credentials = getattr(self.token_provider, "get_git_credentials", None)
        if not callable(get_credentials):
            return None

        credentials = get_credentials(task)
        if not credentials:
            return None

        username = credentials.get("username")
        password = credentials.get("password")
        credential_domain = credentials.get("git_domain")
        git_host = urlsplit(git_url).hostname or ""
        if not username or not password or not credential_domain or not git_host:
            return None
        if not domains_match(credential_domain, git_host):
            return None
        return {"username": username, "password": password}

    def _write_git_askpass_script(
        self,
        sandbox_id: str,
        path: str,
        credentials: Dict[str, str],
        timeout: int,
    ) -> None:
        payload = self._build_git_askpass_script(credentials).encode("utf-8")
        self.client.write_file(sandbox_id, path, payload, timeout=timeout + 30)

    @staticmethod
    def _build_git_askpass_script(credentials: Dict[str, str]) -> str:
        username = shlex.quote(credentials["username"])
        password = shlex.quote(credentials["password"])
        return "\n".join(
            [
                "#!/bin/sh",
                'case "$1" in',
                f"  *Username*|*username*) printf '%s\\n' {username} ;;",
                f"  *Password*|*password*) printf '%s\\n' {password} ;;",
                "  *) printf '\\n' ;;",
                "esac",
                "",
            ]
        )

    @staticmethod
    def _git_askpass_path(task: Dict[str, Any]) -> str:
        task_id = BaiduSandboxExecutor._safe_path_component(
            get_metadata_field(task, "task_id", 0)
        )
        subtask_id = BaiduSandboxExecutor._safe_path_component(
            get_metadata_field(task, "subtask_id", 0)
        )
        return f"/tmp/wegent-git-askpass-{task_id}-{subtask_id}.sh"

    @staticmethod
    def _git_credentials_store_path(task: Dict[str, Any]) -> str:
        task_id = BaiduSandboxExecutor._safe_path_component(
            get_metadata_field(task, "task_id", 0)
        )
        subtask_id = BaiduSandboxExecutor._safe_path_component(
            get_metadata_field(task, "subtask_id", 0)
        )
        return f"/tmp/wegent-git-credentials-{task_id}-{subtask_id}"

    @staticmethod
    def _safe_path_component(value: Any) -> str:
        text = str(value)
        cleaned = "".join(
            char if char.isalnum() or char in ("-", "_") else "_" for char in text
        )
        return cleaned or "0"

    @staticmethod
    def _write_tar_archive(source_dir: Path, archive_path: Path) -> None:
        with tarfile.open(archive_path, "w:gz") as archive:
            for item in source_dir.iterdir():
                archive.add(item, arcname=item.name, recursive=True)

    @staticmethod
    def _enforce_workspace_archive_size(archive_path: Path) -> None:
        max_bytes = int(config.BAIDU_SANDBOX_WORKSPACE_ARCHIVE_MAX_BYTES)
        size = archive_path.stat().st_size
        if size > max_bytes:
            raise RuntimeError(
                f"workspace archive is too large: {size} bytes exceeds {max_bytes}"
            )

    @staticmethod
    def _build_workspace_extract_command(archive_path: str) -> str:
        archive_value = shlex.quote(archive_path)
        return "\n".join(
            [
                "set -eu",
                "workspace_dir=/workspace",
                f"archive_path={archive_value}",
                'mkdir -p "$workspace_dir"',
                'find "$workspace_dir" -mindepth 1 -maxdepth 1 -exec rm -rf {} +',
                'tar -xzf "$archive_path" -C "$workspace_dir"',
                'rm -f "$archive_path"',
            ]
        )

    @staticmethod
    def _should_use_local_archive_fallback(result: Any) -> bool:
        if not config.BAIDU_SANDBOX_WORKSPACE_UPLOAD_FALLBACK:
            return False
        exit_code = BaiduSandboxExecutor._command_exit_code(result)
        if exit_code == 2:
            return False
        output = BaiduSandboxExecutor._command_failure_message(result).lower()
        return exit_code in (124, 128) or any(
            marker in output
            for marker in (
                "unable to access",
                "operation too slow",
                "failed to connect",
                "could not resolve",
                "network",
                "timed out",
            )
        )

    def _write_ducc_config(self, sandbox_id: str, model_token: str) -> None:
        payload = shlex.quote(serialize_user_config(model_token))
        command = (
            "mkdir -p /root/.baidu-cc && "
            f"printf %s {payload} > /root/.baidu-cc/user.json && "
            "chmod 600 /root/.baidu-cc/user.json"
        )
        result = self.client.run(sandbox_id, command, timeout=30)
        self._raise_if_command_failed(result, "DUCC config write")

    def _build_ducc_command(self, prompt: str, git_askpass_path: str = "") -> str:
        timeout = int(config.BAIDU_SANDBOX_DUCC_TIMEOUT)
        askpass_value = shlex.quote(git_askpass_path)
        ducc_command = self._build_ducc_invocation(prompt, timeout)
        return "\n".join(
            [
                "set -eu",
                "mkdir -p /workspace",
                "cd /workspace",
                f"git_askpass_path={askpass_value}",
                "export GIT_TERMINAL_PROMPT=0",
                'if [ -n "$git_askpass_path" ]; then',
                '  chmod 700 "$git_askpass_path"',
                '  export GIT_ASKPASS="$git_askpass_path"',
                "fi",
                ducc_command,
            ]
        )

    @staticmethod
    def _build_ducc_invocation(prompt: str, timeout: int) -> str:
        command_parts = [
            "timeout",
            str(timeout),
            "ducc",
            "-p",
            shlex.quote(prompt),
        ]
        permission_mode = config.BAIDU_SANDBOX_DUCC_PERMISSION_MODE
        if permission_mode:
            command_parts.extend(
                ["--permission-mode", shlex.quote(permission_mode)]
            )
        allowed_tools = config.BAIDU_SANDBOX_DUCC_ALLOWED_TOOLS
        if allowed_tools:
            command_parts.extend(["--allowedTools", shlex.quote(allowed_tools)])
        command_parts.extend(["--output-format", "text"])
        return " ".join(command_parts)

    def _verify_requested_git_push(
        self, sandbox_id: str, prompt: str, git_askpass_path: str
    ) -> str:
        branch = self._extract_requested_push_branch(prompt)
        if not branch:
            return ""

        logger.info(
            "[BaiduSandboxExecutor] Verifying requested git push sandbox_id=%s "
            "branch=%s",
            sandbox_id,
            branch,
        )
        command = self._build_git_push_verification_command(
            branch,
            git_askpass_path,
        )
        result = self.client.run(
            sandbox_id,
            command,
            timeout=int(config.BAIDU_SANDBOX_WORKSPACE_TIMEOUT) + 30,
        )
        if self._command_failed(result):
            raise RuntimeError(
                "Requested git push was not verified on origin branch "
                f"{branch}: {self._command_failure_message(result)}"
            )

        stdout = (getattr(result, "stdout", "") or "").strip()
        return stdout

    @classmethod
    def _extract_requested_push_branch(cls, prompt: str) -> str:
        if not cls._prompt_requests_git_push(prompt):
            return ""

        for line in prompt.splitlines():
            branch = cls._extract_git_push_origin_branch(line)
            if branch:
                return branch

        branch_pattern = r"([A-Za-z0-9][A-Za-z0-9._/-]{0,255})"
        patterns = (
            rf"(?:新分支|远端分支|目标分支|branch|branch_name)\s*[:：]\s*{branch_pattern}",
            rf"git\s+ls-remote\s+--heads\s+origin\s+{branch_pattern}",
        )
        for pattern in patterns:
            match = re.search(pattern, prompt, flags=re.IGNORECASE)
            if match:
                branch = cls._normalize_push_ref(match.group(1))
                if branch:
                    return branch
        return ""

    @staticmethod
    def _prompt_requests_git_push(prompt: str) -> bool:
        lowered = prompt.lower()
        return any(
            marker in lowered
            for marker in (
                "git push",
                "push origin",
                "推送",
                "上传代码",
                "上传",
            )
        )

    @classmethod
    def _extract_git_push_origin_branch(cls, line: str) -> str:
        lowered = line.lower()
        start = lowered.find("git push")
        if start < 0:
            return ""

        command = line[start:]
        try:
            parts = shlex.split(command)
        except ValueError:
            parts = command.split()
        if len(parts) < 4 or parts[0] != "git" or parts[1] != "push":
            return ""

        for index, part in enumerate(parts[2:], start=2):
            if part != "origin":
                continue
            if index + 1 >= len(parts):
                return ""
            return cls._normalize_push_ref(parts[index + 1])
        return ""

    @staticmethod
    def _normalize_push_ref(ref: str) -> str:
        branch = ref.strip().strip("`'\"，,。.;；")
        if branch.startswith("HEAD:refs/heads/"):
            branch = branch[len("HEAD:refs/heads/") :]
        elif branch.startswith("refs/heads/"):
            branch = branch[len("refs/heads/") :]
        elif ":" in branch:
            branch = branch.split(":", 1)[1]
            if branch.startswith("refs/heads/"):
                branch = branch[len("refs/heads/") :]

        if not branch or branch.startswith("-"):
            return ""
        if any(char.isspace() for char in branch):
            return ""
        if any(char in branch for char in ("\\", "~", "^", ":", "?")):
            return ""
        return branch

    @staticmethod
    def _build_git_push_verification_command(
        branch: str, git_askpass_path: str = ""
    ) -> str:
        branch_value = shlex.quote(branch)
        askpass_value = shlex.quote(git_askpass_path)
        timeout_value = shlex.quote(str(int(config.BAIDU_SANDBOX_WORKSPACE_TIMEOUT)))
        return "\n".join(
            [
                "set -eu",
                "cd /workspace",
                f"branch={branch_value}",
                f"git_askpass_path={askpass_value}",
                f"verify_timeout={timeout_value}",
                "export GIT_TERMINAL_PROMPT=0",
                'if [ -n "$git_askpass_path" ]; then',
                '  chmod 700 "$git_askpass_path"',
                '  export GIT_ASKPASS="$git_askpass_path"',
                "fi",
                "git rev-parse --is-inside-work-tree >/dev/null",
                'remote_url="$(git config --get remote.origin.url || true)"',
                'if [ -z "$remote_url" ]; then',
                '  echo "Workspace has no origin remote." >&2',
                "  exit 2",
                "fi",
                'echo "Wegent git push verification OK:"',
                (
                    'timeout "$verify_timeout" git -c http.lowSpeedLimit=1 '
                    '-c http.lowSpeedTime=15 ls-remote --exit-code --heads '
                    'origin "$branch"'
                ),
            ]
        )

    def _cleanup_sandbox_file(self, sandbox_id: str, path: str) -> None:
        if not path:
            return

        try:
            result = self.client.run(
                sandbox_id,
                f"rm -f {shlex.quote(path)}",
                timeout=10,
            )
            if self._command_failed(result):
                logger.warning(
                    "[BaiduSandboxExecutor] Failed to cleanup sandbox file %s: %s",
                    path,
                    self._command_failure_message(result),
                )
        except Exception as exc:
            logger.warning(
                "[BaiduSandboxExecutor] Failed to cleanup sandbox file %s: %s",
                path,
                exc,
            )

    @staticmethod
    def _raise_if_command_failed(result: Any, label: str) -> None:
        exit_code = BaiduSandboxExecutor._command_exit_code(result)
        if exit_code not in (0, None):
            raise RuntimeError(
                f"{label} failed with exit_code={exit_code}: "
                f"{BaiduSandboxExecutor._command_failure_message(result)}"
            )

    @staticmethod
    def _command_failed(result: Any) -> bool:
        return BaiduSandboxExecutor._command_exit_code(result) not in (0, None)

    @staticmethod
    def _command_exit_code(result: Any) -> Any:
        exit_code = getattr(result, "exit_code", None)
        if exit_code is None:
            exit_code = getattr(result, "return_code", 0)
        return exit_code

    @staticmethod
    def _command_failure_message(result: Any) -> str:
        stdout = (getattr(result, "stdout", "") or "").strip()
        stderr = (getattr(result, "stderr", "") or "").strip()
        return stderr or stdout

    def _send_success_callback(
        self, task: Dict[str, Any], executor_name: str, output: str
    ) -> None:
        task_id = int(get_metadata_field(task, "task_id", 0))
        subtask_id = int(get_metadata_field(task, "subtask_id", 0))
        builder = ResponsesAPIEventBuilder(subtask_id=subtask_id, model="ducc")
        events = [
            builder.response_created(shell_type="BaiduSandbox"),
            builder.output_item_added(),
            builder.content_part_added(),
            builder.text_delta(output),
            builder.text_done(output),
            builder.response_completed(content=output),
        ]
        callback_base_url = self._resolve_callback_base_url(task)
        self._post_callback_events(
            task_id, subtask_id, executor_name, events, callback_base_url
        )

    def _send_error_callback(
        self, task: Dict[str, Any], executor_name: str, error_msg: str
    ) -> None:
        task_id = int(get_metadata_field(task, "task_id", 0))
        subtask_id = int(get_metadata_field(task, "subtask_id", 0))
        builder = ResponsesAPIEventBuilder(subtask_id=subtask_id, model="ducc")
        callback_base_url = self._resolve_callback_base_url(task)
        self._post_callback_events(
            task_id,
            subtask_id,
            executor_name,
            [builder.error(error_msg, code="baidu_sandbox_error")],
            callback_base_url,
        )

    @staticmethod
    def _should_send_failure_callback(task: Dict[str, Any]) -> bool:
        """Return whether this executor should emit an immediate failure callback."""
        return not bool(task.get("background"))

    def _post_callback_events(
        self,
        task_id: int,
        subtask_id: int,
        executor_name: str,
        events: list[dict],
        callback_base_url: str,
    ) -> None:
        if task_id <= 0 or subtask_id <= 0:
            return

        callback_url = f"{callback_base_url.rstrip('/')}/api/internal/callback"
        for event in events:
            event_type = event.get("type")
            payload = {
                "event_type": event_type,
                "task_id": task_id,
                "subtask_id": subtask_id,
                "executor_name": executor_name,
                "executor_namespace": "baidu_sandbox",
                "data": event,
            }
            try:
                response = self.requests.post(
                    callback_url,
                    json=payload,
                    timeout=config.API_TIMEOUT,
                )
                if response.status_code >= 400:
                    logger.warning(
                        "[BaiduSandboxExecutor] Callback failed status=%s event=%s",
                        response.status_code,
                        event_type,
                    )
            except requests.RequestException as exc:
                logger.warning(
                    "[BaiduSandboxExecutor] Callback request failed event=%s: %s",
                    event_type,
                    exc,
                )

    @staticmethod
    def _resolve_callback_base_url(task: Dict[str, Any]) -> str:
        return (
            get_metadata_field(task, "callback_url")
            or get_metadata_field(task, "backend_url")
            or os.getenv("TASK_API_DOMAIN")
            or config.TASK_API_DOMAIN
        )

    def _create_result_response(self, status: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "status": status["status"],
            "executor_name": status["executor_name"],
            "executor_namespace": status.get("executor_namespace"),
            "progress": status["progress"],
            "error_msg": status.get("error_msg", ""),
            "callback_status": status.get("callback_status"),
        }

    @staticmethod
    def _sandbox_id_from_executor_name(
        executor_name: str, default: Optional[str] = None
    ) -> str:
        if BaiduSandboxExecutor._is_sandbox_executor_name(executor_name):
            return executor_name.removeprefix("baidu-sandbox-")
        if default:
            return default
        raise ValueError(f"Executor name does not contain sandbox id: {executor_name}")

    @staticmethod
    def _is_sandbox_executor_name(executor_name: Optional[str]) -> bool:
        return bool(executor_name and executor_name.startswith("baidu-sandbox-"))

    @staticmethod
    def _executor_name_from_sandbox_id(sandbox_id: str) -> str:
        return f"baidu-sandbox-{sandbox_id}"
