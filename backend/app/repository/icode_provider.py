# SPDX-FileCopyrightText: 2025 Weibo, Inc.
#
# SPDX-License-Identifier: Apache-2.0

"""
icode (Baidu internal Gerrit-based) repository provider.

icode is derived from Gerrit but its public web/API endpoints are protected by
Baidu's UUAP SSO and do NOT accept HTTP password Basic Auth (every request to
``https://icode.baidu.com/a/...`` is redirected to UUAP login). The HTTP
password generated in icode Settings is only honoured by the git smart-HTTP
endpoint used for ``git clone`` / ``git ls-remote``.

Implications for this provider:

- ``validate_token`` cannot reuse Gerrit's ``/a/accounts/self/`` REST call; it
  validates by running ``git ls-remote`` against a sentinel repo and inspecting
  the error message ("401 Unauthorized" => bad password, anything else => the
  password is at least accepted by the server).
- ``get_repositories`` / ``get_branches`` / ``search_repositories`` are not
  available without UUAP / ugate-token authentication. They return empty
  results so the rest of Wegent can still operate; users must paste a full
  icode clone URL when creating a Workspace.
- The actual ``git clone`` flow already works because
  ``shared/utils/git_util.is_gerrit_url`` recognises ``icode`` URLs and the
  executor builds ``https://<user>:<token>@icode.baidu.com/...``.
"""

import logging
import re
import subprocess
from typing import Any, Dict, List

from fastapi import HTTPException

from app.models.user import User
from app.repository.gerrit_provider import GerritProvider

# Sentinel repo path used purely to probe credentials. The repo does not need
# to exist - we only care whether icode rejects the password (401) or accepts
# it and replies with some other error (1007 not found, 1403 no permission,
# etc.).
_SENTINEL_PATH = "baidu/wegent/credential-probe"

# Regex that matches an authentication failure in git's stderr.
_AUTH_FAILED_RE = re.compile(
    r"(401|Authentication failed|Unauthorized)", re.IGNORECASE
)


class IcodeProvider(GerritProvider):
    """
    Provider for Baidu icode.

    Inherits from ``GerritProvider`` only for plumbing (token decryption,
    type registration). All Gerrit REST API entry points are explicitly
    short-circuited because icode does not expose them to HTTP-password
    clients.
    """

    def __init__(self) -> None:
        super().__init__()
        self.domain = "icode"
        self.type = "icode"
        self.logger = logging.getLogger(__name__)

    # ------------------------------------------------------------------
    # Token validation via git ls-remote
    # ------------------------------------------------------------------
    def validate_token(
        self,
        token: str,
        git_domain: str = None,
        user_name: str = None,
        auth_type: str = "basic",
    ) -> Dict[str, Any]:
        """
        Validate an icode HTTP password by probing the git smart-HTTP endpoint.

        ``git_domain`` defaults to ``icode.baidu.com`` if not supplied.
        ``auth_type`` is accepted for signature parity with GerritProvider but
        is unused: icode's git endpoint always speaks Basic Auth.
        """
        if not token or not user_name:
            raise HTTPException(
                status_code=400,
                detail="icode credentials (token, user_name) are required",
            )

        domain = (git_domain or "icode.baidu.com").strip()
        # Strip protocol if user pasted one
        domain = re.sub(r"^https?://", "", domain).rstrip("/")

        decrypt_token = self.decrypt_token(token)
        probe_url = f"https://{user_name}:{decrypt_token}@{domain}/{_SENTINEL_PATH}"

        try:
            result = subprocess.run(
                ["git", "ls-remote", probe_url],
                capture_output=True,
                text=True,
                timeout=15,
                env={"GIT_TERMINAL_PROMPT": "0"},
            )
        except subprocess.TimeoutExpired:
            self.logger.warning(
                "icode token validation timed out (domain=%s, user=%s)",
                domain,
                user_name,
            )
            raise HTTPException(
                status_code=504,
                detail="icode validation timeout - check network connectivity",
            )
        except FileNotFoundError as exc:
            # git binary not installed in the backend container/host
            raise HTTPException(
                status_code=500, detail=f"git CLI not available: {exc}"
            )

        stderr = result.stderr or ""
        # Auth failure -> wrong password
        if _AUTH_FAILED_RE.search(stderr):
            self.logger.warning(
                "icode token validation failed: 401 (domain=%s, user=%s)",
                domain,
                user_name,
            )
            return {
                "valid": False,
                "error": "auth_failed",
                "message": "icode authentication failed. Please check your "
                "username and HTTP password.",
            }

        # Any other outcome (success / repo-not-found / no-permission) means
        # the credentials were accepted by the server.
        return {
            "valid": True,
            "user": {
                "id": user_name,
                "login": user_name,
                "name": user_name,
                "avatar_url": "",
                "email": f"{user_name}@baidu.com",
            },
        }

    # ------------------------------------------------------------------
    # Repository / branch listing - not available without UUAP
    # ------------------------------------------------------------------
    async def get_repositories(
        self, user: User, page: int = 1, limit: int = 100
    ) -> List[Dict[str, Any]]:
        """icode does not expose a list-projects API to HTTP-password clients."""
        return []

    async def search_repositories(
        self,
        user: User,
        query: str,
        timeout: int = 30,
        fullmatch: bool = False,
    ) -> List[Dict[str, Any]]:
        """icode does not expose a search-projects API to HTTP-password clients."""
        return []

    async def get_branches(
        self, user: User, repo_name: str, git_domain: str
    ) -> List[Dict[str, Any]]:
        """icode does not expose a list-branches API to HTTP-password clients."""
        return []
