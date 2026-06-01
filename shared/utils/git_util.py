# SPDX-FileCopyrightText: 2025 Weibo, Inc.
#
# SPDX-License-Identifier: Apache-2.0

import os
import shutil
import subprocess
from urllib.parse import quote, urlparse

from shared.logger import setup_logger
from shared.utils.crypto import decrypt_git_token, is_token_encrypted

logger = setup_logger(__name__)

ICODE_CLI_INSTALL_URL = "http://icode-cli.bj.bcebos.com/install.sh"
ICODE_CLI_DEFAULT_PATH = os.path.expanduser("~/.icode/bin/icode")


def mask_url_credentials(url: str) -> str:
    """
    Mask credentials (username:password/token) in a URL for safe logging.

    Args:
        url: URL that may contain credentials in format protocol://user:token@host/path

    Returns:
        URL with credentials masked, e.g., https://***:***@github.com/repo
    """
    if "://" not in url:
        return url

    protocol, rest = url.split("://", 1)

    # Check if URL contains credentials (user:pass@host format)
    if "@" in rest:
        credentials_and_host = rest.split("@", 1)
        if len(credentials_and_host) == 2:
            host_and_path = credentials_and_host[1]
            return f"{protocol}://***:***@{host_and_path}"

    return url


def get_repo_name_from_url(url):
    # Remove .git suffix if exists
    if url.endswith(".git"):
        url = url[:-4]  # Correctly remove '.git' suffix

    # Handle special path formats containing '/-/' (like tree structure or merge requests)
    if "/-/" in url:
        url = url.split("/-/")[0]

    parts = url.split("/")

    repo_name = parts[-1] if parts[-1] else parts[-2]
    return repo_name


def clone_repo(
    project_url, branch, project_path, user_name=None, token=None, ugate_token=None
):
    """
    Clone repository to specified path

    Returns:
        Tuple (success, message):
        - On success: (True, None)
        - On failure: (False, error_message)
    """
    if not token or token == "***":
        token = get_git_token_from_url(project_url)
    elif is_token_encrypted(token):
        logger.debug(f"Decrypting git token for cloning repository")
        token = decrypt_git_token(token)

    if ugate_token and is_token_encrypted(ugate_token):
        ugate_token = decrypt_git_token(ugate_token)

    if user_name is None:
        user_name = "token"
    logger.info(
        f"get git token from url: {project_url}, branch:{branch}, project:{project_path}"
    )
    if token:
        return clone_repo_with_token(
            project_url, branch, project_path, user_name, token, ugate_token
        )
    return False, "Token is not provided"


def get_domain_from_url(url):
    if "/-/" in url:
        url = url.split("/-/")[0]

    # Handle SSH format (ssh://git@domain.com:port/...)
    if url.startswith("ssh://"):
        url = url[6:]  # Remove ssh:// prefix

    # Handle git@domain.com: format
    if "@" in url and ":" in url:
        # Extract domain:port part
        return url.split("@")[1].split(":")[0]

    # Parse standard URL using urlparse
    parsed = urlparse("https://" + url if "://" not in url else url)

    return parsed.hostname if parsed.netloc else ""


def is_gerrit_url(url):
    """
    Check if the URL is a Gerrit repository URL.
    Gerrit URLs typically contain 'gerrit' in the domain name.

    Args:
        url: Git repository URL

    Returns:
        True if likely a Gerrit URL, False otherwise
    """

    url_lower = url.lower()

    # Gerrit URLs typically contain 'gerrit' in the domain
    # Examples: gerrit.example.com, code-review-gerrit.company.com, review.gerrit.internal
    # icode (Baidu's internal Gerrit-based platform) is also handled like Gerrit
    if "gerrit" in url_lower or "icode" in url_lower:
        return True

    return False


def is_icode_url(url):
    """
    Check if the URL belongs to Baidu's icode platform.

    icode is Baidu's internal Gerrit-based code platform that requires
    special handling via icode-cli for authentication and hooks.

    Args:
        url: Git repository URL

    Returns:
        True if URL is on icode.baidu.com, False otherwise
    """
    if not url:
        return False
    return "icode.baidu.com" in url.lower()


def _parse_icode_repo_from_url(url):
    """
    Extract the three-level repo path required by `icode-cli git clone --repo`.

    icode-cli expects format like `baidu/hi/openclaw_infoflow`. This function
    strips protocol, credentials, host, `/a/` auth prefix, and `.git` suffix.

    Args:
        url: icode repository URL

    Returns:
        Three-level repo path string

    Raises:
        ValueError: If the URL cannot be parsed into a valid icode repo path
    """
    if not url:
        raise ValueError("Empty icode URL")

    raw = url.strip()

    # Strip .git suffix
    if raw.endswith(".git"):
        raw = raw[:-4]

    # Drop /-/ tree/MR-style paths
    if "/-/" in raw:
        raw = raw.split("/-/")[0]

    # Extract path component
    if raw.startswith("ssh://"):
        # ssh://git@icode.baidu.com:8235/baidu/hi/openclaw_infoflow
        rest = raw[len("ssh://") :]
        # Drop user@ part
        if "@" in rest:
            rest = rest.split("@", 1)[1]
        # Drop host[:port]
        if "/" in rest:
            path = rest.split("/", 1)[1]
        else:
            path = ""
    elif raw.startswith("http://") or raw.startswith("https://"):
        protocol, rest = raw.split("://", 1)
        # Drop credentials
        if "@" in rest:
            rest = rest.split("@", 1)[1]
        # Drop host
        if "/" in rest:
            path = rest.split("/", 1)[1]
        else:
            path = ""
    elif "@" in raw and ":" in raw:
        # git@icode.baidu.com:baidu/hi/openclaw_infoflow
        path = raw.split(":", 1)[1]
    else:
        path = raw

    # Strip leading slash and `/a/` auth prefix
    path = path.lstrip("/")
    if path.startswith("a/"):
        path = path[2:]

    # Validate three-level path
    parts = [p for p in path.split("/") if p]
    if len(parts) < 3:
        raise ValueError(
            f"Invalid icode URL, expected three-level repo path, got: {url}"
        )

    return "/".join(parts[:3])


def _ensure_icode_cli_installed():
    """
    Ensure the icode CLI is installed and return its executable path.

    The official install script installs the binary as ``icode`` (and only
    sets up an ``icode-cli`` shell alias, which is unavailable in
    non-interactive subprocesses). So we look up ``icode`` on PATH first,
    then fall back to the default install location ``~/.icode/bin/icode``.

    Returns:
        Absolute path to the icode executable

    Raises:
        RuntimeError: If installation fails or executable cannot be located
    """
    cli_path = shutil.which("icode")
    if cli_path:
        return cli_path

    if os.path.isfile(ICODE_CLI_DEFAULT_PATH) and os.access(
        ICODE_CLI_DEFAULT_PATH, os.X_OK
    ):
        return ICODE_CLI_DEFAULT_PATH

    logger.info("icode not found, installing via official script")
    install_cmd = f"curl -fsSL {ICODE_CLI_INSTALL_URL} | bash -s -- --no-skills"
    try:
        result = subprocess.run(
            install_cmd,
            shell=True,
            capture_output=True,
            text=True,
            check=True,
            timeout=300,
        )
        logger.info(f"icode install stdout: {result.stdout[-500:]}")
    except subprocess.CalledProcessError as e:
        error_msg = e.stderr if e.stderr else str(e)
        raise RuntimeError(f"Failed to install icode: {error_msg}")
    except subprocess.TimeoutExpired:
        raise RuntimeError("icode installation timed out")

    # Re-check after install
    cli_path = shutil.which("icode")
    if cli_path:
        return cli_path
    if os.path.isfile(ICODE_CLI_DEFAULT_PATH) and os.access(
        ICODE_CLI_DEFAULT_PATH, os.X_OK
    ):
        return ICODE_CLI_DEFAULT_PATH

    raise RuntimeError(
        f"icode installed but executable not found at {ICODE_CLI_DEFAULT_PATH} or on PATH"
    )


def clone_icode_repo(
    project_url, branch, project_path, token, username="", ugate_token=None
):
    """
    Clone an icode repository.

    Attempts icode-cli first (for commit-msg hooks), falls back to plain
    git clone with credential store if icode-cli is unavailable or login fails.
    The token must be an icode HTTP password (from icode Settings page).

    Args:
        project_url: Full icode URL
        branch: Branch to checkout (optional)
        project_path: Local directory to clone into
        token: HTTP password from icode Settings page
        username: icode username for credential store
        ugate_token: JWT token for icode-cli login (from uuap.baidu.com/agent/token)

    Returns:
        Tuple (success, error_message):
        - On success: (True, None)
        - On failure: (False, error_message)
    """
    try:
        repo = _parse_icode_repo_from_url(project_url)
    except ValueError as e:
        logger.error(f"Failed to parse icode repo path: {e}")
        return False, str(e)

    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"

    # Configure git credential store with the HTTP password.
    cred_user = username or "user"
    encoded_cred_user = quote(cred_user, safe="")
    encoded_token = quote(token, safe="")
    cred_line = f"https://{encoded_cred_user}:{encoded_token}@icode.baidu.com"
    try:
        cred_file = os.path.expanduser("~/.git-credentials")
        with open(cred_file, "w") as f:
            f.write(cred_line + "\n")
        subprocess.run(
            ["git", "config", "--global", "credential.helper", "store"],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
            env=env,
        )
        logger.info("Git credential store configured for icode (user=%s)", cred_user)
    except (OSError, subprocess.CalledProcessError) as e:
        logger.warning(f"Failed to configure credential store: {e}")

    # Perform icode login with ugate token if provided
    if ugate_token:
        try:
            icode_path = _ensure_icode_cli_installed()
            login_cmd = [
                icode_path,
                "login",
                "--method",
                "ugate",
                "--token",
                ugate_token,
            ]
            subprocess.run(
                login_cmd,
                capture_output=True,
                text=True,
                check=True,
                timeout=30,
                env=env,
            )
            logger.info("icode login with ugate token succeeded")
        except (RuntimeError, subprocess.CalledProcessError) as e:
            logger.warning(f"icode login failed (will proceed with git clone): {e}")
        except subprocess.TimeoutExpired:
            logger.warning("icode login timed out (will proceed with git clone)")

    # Clone the repository using plain git clone with embedded credentials.
    clone_url = f"https://{encoded_cred_user}:{encoded_token}@icode.baidu.com/{repo}"
    logger.info(f"Cloning icode repo={repo} path={project_path}")
    clone_cmd = ["git", "clone", clone_url, project_path]
    try:
        subprocess.run(
            clone_cmd,
            capture_output=True,
            text=True,
            check=True,
            timeout=600,
            env=env,
        )
    except subprocess.CalledProcessError as e:
        error_msg = e.stderr if e.stderr else str(e)
        logger.error(f"icode clone failed: {error_msg}")
        return False, f"icode clone failed: {error_msg}"
    except subprocess.TimeoutExpired:
        return False, "icode clone timed out"

    # Checkout requested branch if specified
    if branch and branch.strip():
        try:
            subprocess.run(
                ["git", "-C", project_path, "checkout", branch],
                capture_output=True,
                text=True,
                check=True,
                timeout=120,
                env=env,
            )
            logger.info(f"Checked out branch {branch}")
        except subprocess.CalledProcessError as e:
            error_msg = e.stderr if e.stderr else str(e)
            logger.error(f"git checkout {branch} failed: {error_msg}")
            return False, f"checkout branch {branch} failed: {error_msg}"
        except subprocess.TimeoutExpired:
            return False, f"checkout branch {branch} timed out"

    setup_git_hooks(project_path)

    return True, None


def clone_repo_with_token(
    project_url, branch, project_path, username, token, ugate_token=None
):
    # icode (Baidu's internal Gerrit) requires icode-cli to handle
    # credential helpers and commit-msg hooks; plain `git clone` hangs
    # in containers without a credential helper configured.
    if is_icode_url(project_url):
        return clone_icode_repo(
            project_url, branch, project_path, token, username, ugate_token
        )

    if project_url.startswith("https://") or project_url.startswith("http://"):
        protocol, rest = project_url.split("://", 1)

        # Only URL encode credentials for Gerrit repositories
        # Gerrit passwords may contain special characters like '/' that need encoding
        # GitHub, GitLab, and Gitee don't have this issue
        if is_gerrit_url(project_url):
            # URL encode username and token to handle special characters
            # safe='' means encode all special characters including /
            encoded_username = quote(username, safe="")
            encoded_token = quote(token, safe="")
            auth_url = f"{protocol}://{encoded_username}:{encoded_token}@{rest}"
            logger.info(f"Auth URL: {mask_url_credentials(auth_url)}")
        else:
            # For non-Gerrit repos (GitHub, GitLab, etc.), use credentials as-is
            auth_url = f"{protocol}://{username}:{token}@{rest}"
    else:
        auth_url = project_url

    logger.info(
        f"Git clone {mask_url_credentials(auth_url)} to {project_path}, branch: {branch if branch else '(default)'}"
    )

    # Build basic command
    cmd = ["git", "clone"]

    # Add branch parameter only if branch is specified and not empty
    # When branch is empty/None, git will clone the repository's default branch
    if branch and branch.strip():
        cmd.extend(["--branch", branch, "--single-branch"])

    # Add URL and path
    cmd.extend([auth_url, project_path])
    try:
        # Use subprocess.run to capture output and errors
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        logger.info(f"git clone url: {project_url}, code: {result.returncode}")

        # Setup git hooks after successful clone
        setup_git_hooks(project_path)

        return True, None
    except subprocess.CalledProcessError as e:
        error_msg = e.stderr if e.stderr else str(e)
        logger.error(f"git clone failed: {error_msg}")
        return False, error_msg
    except Exception as e:
        logger.error(f"git clone failed with unexpected error: {e}")
        return False, str(e)


def get_git_token_from_url(git_url):
    domain = get_domain_from_url(git_url)
    if not domain:
        logger.error(f"get domain from url failed: {git_url}")
        raise Exception(f"get domain from url failed: {git_url}")

    token_file = f"/root/.ssh/{domain}"
    try:
        with open(token_file, "r") as f:
            token = f.read().strip()
            # Check if token is encrypted and decrypt if needed
            if is_token_encrypted(token):
                logger.debug(f"Decrypting git token from file for domain: {domain}")
                return decrypt_git_token(token)
            return token
    except IOError:
        raise Exception(f"get domain from file failed: {git_url}, file: {token_file}")


def get_project_path_from_url(url):
    # Handle special path formats containing '/-/'
    if "/-/" in url:
        url = url.split("/-/")[0]

    # Remove .git suffix if exists
    if url.endswith(".git"):
        url = url[:-4]

    # Handle SSH format (git@domain.com:user/repo)
    if "@" in url and ":" in url:
        # Extract user/repo part
        return url.split(":")[-1]

    # Parse standard URL using urlparse
    parsed = urlparse("https://" + url if "://" not in url else url)

    # Remove leading slash
    path = parsed.path
    if path.startswith("/"):
        path = path[1:]

    return path


def setup_git_hooks(repo_path):
    """
    Setup git hooks for a repository by configuring core.hooksPath
    to use the .githooks directory if it exists in the repository.

    This enables pre-push quality checks automatically after cloning.

    Args:
        repo_path: Path to the git repository

    Returns:
        Tuple (success, message):
        - On success: (True, None)
        - On failure: (False, error_message)
    """
    import os

    try:
        # Check if .githooks directory exists in the repository
        githooks_path = os.path.join(repo_path, ".githooks")
        if not os.path.isdir(githooks_path):
            logger.debug(
                f"No .githooks directory found in {repo_path}, skipping hooks setup"
            )
            return True, None

        # Configure git to use .githooks directory
        cmd = ["git", "config", "core.hooksPath", ".githooks"]
        subprocess.run(cmd, cwd=repo_path, capture_output=True, text=True, check=True)

        logger.info(
            f"Git hooks configured successfully in {repo_path}: core.hooksPath=.githooks"
        )
        return True, None
    except subprocess.CalledProcessError as e:
        error_msg = e.stderr if e.stderr else str(e)
        logger.error(f"Failed to setup git hooks: {error_msg}")
        return False, error_msg
    except Exception as e:
        logger.error(f"Failed to setup git hooks with unexpected error: {e}")
        return False, str(e)


def set_git_config(repo_path, name, email):
    """
    Set git config user.name and user.email for a repository

    Args:
        repo_path: Path to the git repository
        name: Git user name to set
        email: Git user email to set

    Returns:
        Tuple (success, message):
        - On success: (True, None)
        - On failure: (False, error_message)
    """
    try:
        # Set both user.name and user.email in a single command
        cmd = f'git config user.name "{name}" && git config user.email "{email}"'
        result = subprocess.run(
            cmd, cwd=repo_path, shell=True, capture_output=True, text=True, check=True
        )

        logger.info(
            f"Git config set successfully in {repo_path}: user.name={name}, user.email={email}"
        )
        return True, None
    except subprocess.CalledProcessError as e:
        error_msg = e.stderr if e.stderr else str(e)
        logger.error(f"Failed to set git config: {error_msg}")
        return False, error_msg
    except Exception as e:
        logger.error(f"Failed to set git config with unexpected error: {e}")
        return False, str(e)
