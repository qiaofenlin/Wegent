# SPDX-FileCopyrightText: 2025 Weibo, Inc.
#
# SPDX-License-Identifier: Apache-2.0

"""Tests for user git metadata in TaskRequestBuilder."""

from types import SimpleNamespace

from app.services.execution.request_builder import TaskRequestBuilder


class TestRequestBuilderUserInfo:
    """Tests for building execution user metadata."""

    def test_build_user_info_includes_icode_ugate_token(self, test_db):
        builder = TaskRequestBuilder(test_db)
        user = SimpleNamespace(
            id=1,
            user_name="admin",
            git_info=[
                {
                    "git_domain": "github.com",
                    "git_token": "github-token",
                    "git_id": "github-user",
                    "git_login": "github-user",
                    "git_email": "github@example.com",
                },
                {
                    "git_domain": "icode.baidu.com",
                    "git_token": "icode-http-password",
                    "git_id": "icode-user",
                    "git_login": "icode-user",
                    "git_email": "icode@example.com",
                    "ugate_token": "ugate-jwt-token",
                },
            ],
        )

        user_info = builder._build_user_info(user, "icode.baidu.com")

        assert user_info["git_domain"] == "icode.baidu.com"
        assert user_info["git_token"] == "icode-http-password"
        assert user_info["git_login"] == "icode-user"
        assert user_info["ugate_token"] == "ugate-jwt-token"

    def test_build_user_info_defaults_ugate_token_to_none(self, test_db):
        builder = TaskRequestBuilder(test_db)
        user = SimpleNamespace(
            id=1,
            user_name="admin",
            git_info=[
                {
                    "git_domain": "github.com",
                    "git_token": "github-token",
                    "git_login": "github-user",
                }
            ],
        )

        user_info = builder._build_user_info(user, "github.com")

        assert user_info["git_domain"] == "github.com"
        assert user_info["ugate_token"] is None
