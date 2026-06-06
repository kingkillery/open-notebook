"""Bridge to Google NotebookLM via the `notebooklm_tools` package.

This is an *optional* integration. The heavy lifting (reverse-engineered
NotebookLM private API + cookie auth) lives in the external
``notebooklm_tools`` package, installed via the ``notebooklm`` extra::

    uv sync --extra notebooklm

Authentication reuses that package's own credential store
(``~/.notebooklm-mcp-cli/profiles/<profile>/``), which is populated by
running ``nlm login`` once in a browser. Open Notebook never handles the
Google password flow itself.

All public helpers here degrade gracefully when the package is missing:
:func:`is_available` returns ``False`` and :func:`get_client` raises a
clear, actionable error instead of an opaque ``ImportError``.
"""

from open_notebook.integrations.notebooklm.bridge import (
    NotebookLMNotAuthenticatedError,
    NotebookLMNotAvailableError,
    get_account_email,
    get_client,
    is_available,
    list_profiles,
)

__all__ = [
    "NotebookLMNotAvailableError",
    "NotebookLMNotAuthenticatedError",
    "get_account_email",
    "get_client",
    "is_available",
    "list_profiles",
]
