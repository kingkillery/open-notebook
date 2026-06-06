"""Thin, guarded accessor for the external ``notebooklm_tools`` client.

The ``notebooklm_tools`` client is synchronous (``httpx.Client``). Callers in
the async API layer should wrap calls with ``asyncio.to_thread`` (see
``api/notebooklm_service.py``). This module deliberately keeps no global
client state: a fresh client is cheap to build and CSRF tokens auto-refresh
per-instance, which avoids sharing one ``httpx.Client`` across event-loop
threads.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Optional

from loguru import logger

if TYPE_CHECKING:  # pragma: no cover - typing only
    from notebooklm_tools.core.client import NotebookLMClient


class NotebookLMNotAvailableError(RuntimeError):
    """Raised when the optional ``notebooklm_tools`` package is not installed."""


class NotebookLMNotAuthenticatedError(RuntimeError):
    """Raised when no valid NotebookLM auth profile is available."""


_INSTALL_HINT = (
    "The NotebookLM integration requires the optional 'notebooklm_tools' "
    "package. Install it with: uv sync --extra notebooklm"
)

_LOGIN_HINT = (
    "No NotebookLM authentication found. Run 'nlm login' once in a browser to "
    "create a profile, then retry. If you have already logged in, your Google "
    "session cookies may have expired — run 'nlm login' again."
)


def _parse_cookie_string(cookie_str: str) -> dict[str, str]:
    """Parse a raw ``k=v; k2=v2`` cookie header into a dict."""
    cookies: dict[str, str] = {}
    for item in (cookie_str or "").split(";"):
        if "=" in item:
            key, value = item.split("=", 1)
            cookies[key.strip()] = value.strip()
    return cookies


def is_available() -> bool:
    """Return ``True`` if the ``notebooklm_tools`` package can be imported."""
    try:
        import notebooklm_tools  # noqa: F401

        return True
    except Exception:  # pragma: no cover - import probing
        return False


def list_profiles() -> list[str]:
    """List all available NotebookLM auth profiles (one per Google account).

    Returns an empty list when the package is missing or no profiles exist.
    """
    try:
        from notebooklm_tools.core.auth import AuthManager

        return AuthManager.list_profiles()
    except Exception as e:  # pragma: no cover - defensive
        logger.debug(f"list_profiles failed: {e}")
        return []


def get_account_email(profile: str) -> Optional[str]:
    """Return the Google account email stored for a profile, if known."""
    try:
        from notebooklm_tools.core.auth import AuthManager

        mgr = AuthManager(profile)
        if not mgr.profile_exists():
            return None
        return mgr.load_profile().email
    except Exception as e:  # pragma: no cover - defensive
        logger.debug(f"get_account_email({profile}) failed: {e}")
        return None


def _load_tokens(profile: Optional[str] = None):
    """Load cached auth tokens for a specific profile (Google account).

    A named ``profile`` is loaded directly via ``AuthManager`` — the package's
    ``load_cached_tokens()`` ignores its caller and always returns the default
    profile, so it cannot be used for multi-account. ``profile`` falls back to
    the ``NOTEBOOKLM_PROFILE`` env var, then to the configured default.
    """
    profile = profile or os.environ.get("NOTEBOOKLM_PROFILE")

    if profile:
        from notebooklm_tools.core.auth import AuthManager

        mgr = AuthManager(profile)
        if not mgr.profile_exists():
            return None
        # Profile exposes .cookies / .csrf_token / .session_id, matching the
        # AuthTokens shape get_client() consumes.
        return mgr.load_profile()

    from notebooklm_tools.core.auth import load_cached_tokens

    return load_cached_tokens()


def get_client(profile: Optional[str] = None) -> "NotebookLMClient":
    """Build an authenticated NotebookLM client.

    Args:
        profile: Optional auth profile name. Defaults to the package's
            configured default profile.

    Raises:
        NotebookLMNotAvailableError: The optional package is not installed.
        NotebookLMNotAuthenticatedError: No usable auth profile was found.
    """
    # Allow explicit cookies via env (handy for headless/CI), mirroring the
    # notebooklm_tools CLI behaviour.
    env_cookies = os.environ.get("NOTEBOOKLM_COOKIES")

    try:
        from notebooklm_tools.core.client import NotebookLMClient
    except Exception as e:  # ImportError or transitive failure
        logger.debug(f"notebooklm_tools import failed: {e}")
        raise NotebookLMNotAvailableError(_INSTALL_HINT) from e

    if env_cookies:
        return NotebookLMClient(cookies=_parse_cookie_string(env_cookies))

    tokens = _load_tokens(profile)
    if not tokens or not getattr(tokens, "cookies", None):
        raise NotebookLMNotAuthenticatedError(_LOGIN_HINT)

    return NotebookLMClient(
        cookies=tokens.cookies,
        csrf_token=getattr(tokens, "csrf_token", "") or "",
        session_id=getattr(tokens, "session_id", "") or "",
    )
