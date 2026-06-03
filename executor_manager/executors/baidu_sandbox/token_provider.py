# SPDX-FileCopyrightText: 2025 Weibo, Inc.
#
# SPDX-License-Identifier: Apache-2.0

"""Token providers for Baidu Agent Sandbox MVP."""

import os
from typing import Any, Dict, Optional

from shared.models.openai_converter import get_metadata_field
from shared.utils.crypto import decrypt_git_token, is_token_encrypted


class BaiduSandboxTokenProvider:
    """Resolve Baidu sandbox and DUCC tokens from environment and task payload."""

    def get_access_token(self, task: Dict[str, Any]) -> Optional[str]:
        """Return the personal access token used by sandbox metadata/env."""
        user = get_metadata_field(task, "user", {}) or {}
        if not isinstance(user, dict):
            user = {}
        task_token = self._decrypt_if_needed(user.get("baidu_access_token"))
        if task_token:
            return task_token

        env_token = self._first_present(
            (
                os.getenv("BAIDU_SANDBOX_ACCESS_TOKEN"),
                os.getenv("UGATE_TOKEN"),
                os.getenv("UUAP_ACCESS_TOKEN"),
            )
        )
        if env_token:
            return env_token

        return self._decrypt_if_needed(
            self._first_present(
                (
                    user.get("ugate_token"),
                )
            )
        )

    def get_model_token(self) -> str:
        """Return the DUCC model token."""
        token = self._first_present(
            (
                os.getenv("BAIDU_CC_MODEL_TOKEN"),
                os.getenv("ANTHROPIC_AUTH_TOKEN"),
            )
        )
        if not token:
            raise ValueError(
                "Baidu Sandbox DUCC model token is missing. Set "
                "BAIDU_CC_MODEL_TOKEN or ANTHROPIC_AUTH_TOKEN."
            )
        return token

    def get_ugate_token(self, task: Dict[str, Any]) -> Optional[str]:
        """Return the ugate token used by icode-cli login."""
        user = get_metadata_field(task, "user", {}) or {}
        if not isinstance(user, dict):
            user = {}

        task_token = self._decrypt_if_needed(user.get("ugate_token"))
        if task_token:
            return task_token

        return self._first_present(
            (
                os.getenv("UGATE_TOKEN"),
                os.getenv("UUAP_ACCESS_TOKEN"),
            )
        )

    def get_git_credentials(self, task: Dict[str, Any]) -> Optional[Dict[str, str]]:
        """Return HTTP git credentials from the task user payload."""
        user = get_metadata_field(task, "user", {}) or {}
        if not isinstance(user, dict):
            return None

        token = self._decrypt_if_needed(user.get("git_token"))
        if not token:
            return None

        username = self._first_present(
            (
                user.get("git_login"),
                user.get("baidu_username"),
                user.get("git_id"),
                user.get("name"),
                user.get("user_name"),
            )
        )
        if not username:
            return None

        credentials = {
            "username": username,
            "password": token,
        }
        git_domain = self._first_present((user.get("git_domain"),))
        if git_domain:
            credentials["git_domain"] = git_domain
        return credentials

    @staticmethod
    def _decrypt_if_needed(token: Optional[str]) -> Optional[str]:
        if token and is_token_encrypted(token):
            decrypted = decrypt_git_token(token)
            return decrypted.strip() if isinstance(decrypted, str) else decrypted
        return token

    @staticmethod
    def _first_present(values) -> Optional[str]:
        for value in values:
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None
