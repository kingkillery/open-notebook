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


def _load_tokens(profile: Optional[str] = None):
    """Load cached auth tokens from the notebooklm_tools profile store.

    ``profile`` falls back to the package's configured default profile, or to
    the ``NOTEBOOKLM_PROFILE`` env var, when not provided.
    """
    from notebooklm_tools.core.auth import load_cached_tokens

    profile = profile or os.environ.get("NOTEBOOKLM_PROFILE")
    try:
        # load_cached_tokens accepts an optional profile in recent versions;
        # fall back to the no-arg form for older builds.
        return load_cached_tokens(profile) if profile else load_cached_tokens()
    except TypeError:
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
