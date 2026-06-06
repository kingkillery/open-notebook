"""NotebookLM bridge service.

Business logic for the optional Google NotebookLM integration. Wraps the
synchronous ``notebooklm_tools`` client with ``asyncio.to_thread`` so it plays
nicely with the async API layer, and maps NotebookLM data onto Open Notebook's
own ``Notebook`` / ``Source`` / ``Note`` domain models.

Multi-account: each Google account is a named ``profile`` in the
``notebooklm_tools`` store (created via ``nlm login --profile <name>``). Every
function takes an optional ``profile``; listing with ``profile=None`` aggregates
across all connected accounts, tagging each notebook with its owning profile so
imports route back to the right account.

All functions raise ``ValueError`` for business/availability errors; routers
convert those to HTTP responses.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

from loguru import logger

from open_notebook.domain.notebook import Asset, Note, Notebook, Source
from open_notebook.integrations.notebooklm import (
    NotebookLMNotAuthenticatedError,
    NotebookLMNotAvailableError,
    get_account_email,
    get_client,
    is_available,
    list_profiles,
)

_NOT_INSTALLED_MSG = (
    "NotebookLM integration not installed. Run: uv sync --extra notebooklm"
)


def _friendly_auth_error(msg: str) -> str:
    """Normalise expired-session errors into an actionable hint."""
    if "Authentication" in msg or "expired" in msg.lower():
        return (
            "Google session expired. Run 'nlm login --profile <name>' to "
            "refresh this account's cookies."
        )
    return msg


# =============================================================================
# Accounts / status
# =============================================================================


def _probe_account(profile: str) -> Dict[str, Any]:
    """Synchronously check one profile's live auth state (worker-thread only)."""
    email = get_account_email(profile)
    try:
        client = get_client(profile)
        client.list_notebooks()  # cheap authenticated RPC = liveness check
        return {
            "profile": profile,
            "email": email,
            "authenticated": True,
            "message": "Connected.",
        }
    except (NotebookLMNotAuthenticatedError, NotebookLMNotAvailableError) as e:
        return {
            "profile": profile,
            "email": email,
            "authenticated": False,
            "message": str(e),
        }
    except Exception as e:
        return {
            "profile": profile,
            "email": email,
            "authenticated": False,
            "message": _friendly_auth_error(str(e)),
        }


async def list_accounts() -> List[Dict[str, Any]]:
    """List every connected NotebookLM account with its live auth state."""
    if not is_available():
        return []

    def _run() -> List[Dict[str, Any]]:
        return [_probe_account(p) for p in list_profiles()]

    return await asyncio.to_thread(_run)


async def get_status() -> Dict[str, Any]:
    """Report integration availability and whether *any* account is connected."""
    if not is_available():
        return {
            "available": False,
            "authenticated": False,
            "message": _NOT_INSTALLED_MSG,
            "accounts": [],
        }

    accounts = await list_accounts()
    if not accounts:
        return {
            "available": True,
            "authenticated": False,
            "message": (
                "No NotebookLM accounts connected. Run 'nlm login' (or "
                "'nlm login --profile <name>' for additional accounts)."
            ),
            "accounts": [],
        }

    connected = [a for a in accounts if a["authenticated"]]
    if connected:
        emails = ", ".join(a["email"] or a["profile"] for a in connected)
        message = f"Connected: {emails}"
    else:
        message = (
            "All connected accounts have expired sessions. Run "
            "'nlm login --profile <name>' to refresh."
        )
    return {
        "available": True,
        "authenticated": bool(connected),
        "message": message,
        "accounts": accounts,
    }


# =============================================================================
# Internal client helpers
# =============================================================================


def _client_or_raise(profile: Optional[str] = None):
    """Build a client in the worker thread, mapping errors to ValueError."""
    try:
        return get_client(profile)
    except (NotebookLMNotAvailableError, NotebookLMNotAuthenticatedError) as e:
        raise ValueError(str(e)) from e


# =============================================================================
# Remote browsing
# =============================================================================


def _notebook_to_dict(nb: Any, profile: str, account: Optional[str]) -> Dict[str, Any]:
    return {
        "id": getattr(nb, "id", None),
        "title": getattr(nb, "title", "") or "Untitled",
        "source_count": getattr(nb, "source_count", 0) or 0,
        "is_owned": getattr(nb, "is_owned", True),
        "is_shared": getattr(nb, "is_shared", False),
        "created_at": getattr(nb, "created_at", None),
        "modified_at": getattr(nb, "modified_at", None),
        "url": getattr(nb, "url", None),
        "profile": profile,
        "account": account,
    }


async def list_remote_notebooks(
    profile: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """List NotebookLM notebooks.

    With ``profile`` set, lists that one account. With ``profile=None``,
    aggregates across every connected account (accounts whose session has
    expired are skipped rather than failing the whole call).
    """

    def _run_single(p: str) -> List[Dict[str, Any]]:
        client = _client_or_raise(p)
        account = get_account_email(p)
        return [_notebook_to_dict(nb, p, account) for nb in client.list_notebooks()]

    def _run_all() -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for p in list_profiles():
            try:
                out.extend(_run_single(p))
            except Exception as e:
                logger.warning(f"NotebookLM account '{p}' skipped: {e}")
        return out

    if profile:
        return await asyncio.to_thread(_run_single, profile)
    return await asyncio.to_thread(_run_all)


async def list_remote_sources(
    remote_notebook_id: str, profile: Optional[str] = None
) -> List[Dict[str, Any]]:
    """List sources (with type info) for a remote notebook."""

    def _run() -> List[Dict[str, Any]]:
        client = _client_or_raise(profile)
        raw = client.get_notebook_sources_with_types(remote_notebook_id) or []
        out: List[Dict[str, Any]] = []
        for s in raw:
            if not isinstance(s, dict):
                continue
            out.append(
                {
                    "id": s.get("id") or s.get("source_id"),
                    "title": s.get("title") or s.get("name"),
                    "type": s.get("type") or s.get("source_type"),
                }
            )
        return [s for s in out if s["id"]]

    return await asyncio.to_thread(_run)


# =============================================================================
# Query (source-grounded chat)
# =============================================================================


async def query_remote(
    remote_notebook_id: str,
    query_text: str,
    conversation_id: Optional[str] = None,
    profile: Optional[str] = None,
) -> Dict[str, Any]:
    """Ask a question grounded in a remote notebook's sources."""

    def _run() -> Dict[str, Any]:
        client = _client_or_raise(profile)
        result = client.query(
            notebook_id=remote_notebook_id,
            query_text=query_text,
            conversation_id=conversation_id,
        )
        if not result:
            raise ValueError("NotebookLM returned no answer.")
        return {
            "answer": result.get("answer", ""),
            "conversation_id": result.get("conversation_id"),
        }

    return await asyncio.to_thread(_run)


# =============================================================================
# Studio artifact generation (async via the surreal-commands job queue)
# =============================================================================

# Artifact types the studio job can currently create + attach.
SUPPORTED_STUDIO_TYPES = ["report", "audio"]


async def list_studio_artifacts(
    remote_notebook_id: str, profile: Optional[str] = None
) -> List[Dict[str, Any]]:
    """List existing studio artifacts for a remote notebook."""

    def _run() -> List[Dict[str, Any]]:
        client = _client_or_raise(profile)
        arts = client.poll_studio_status(remote_notebook_id) or []
        out: List[Dict[str, Any]] = []
        for a in arts:
            if not isinstance(a, dict):
                continue
            out.append(
                {
                    "artifact_id": a.get("artifact_id"),
                    "title": a.get("title"),
                    "type": a.get("type"),
                    "status": a.get("status"),
                    "created_at": a.get("created_at"),
                }
            )
        return out

    return await asyncio.to_thread(_run)


async def generate_studio_artifact(
    remote_notebook_id: str,
    artifact_type: str,
    profile: Optional[str] = None,
    target_notebook_id: Optional[str] = None,
    title: Optional[str] = None,
    report_format: str = "Briefing Doc",
    focus_prompt: str = "",
    language: str = "en",
) -> Dict[str, Any]:
    """Submit a background job to generate a studio artifact and attach it.

    Returns the ``command_id`` to poll via ``GET /api/commands/{id}``.
    """
    if artifact_type not in SUPPORTED_STUDIO_TYPES:
        raise ValueError(
            f"Unsupported artifact type '{artifact_type}'. "
            f"Supported: {', '.join(SUPPORTED_STUDIO_TYPES)}"
        )
    if not is_available():
        raise ValueError(_NOT_INSTALLED_MSG)

    from surreal_commands import submit_command

    command_id = submit_command(
        "open_notebook",
        "generate_studio_artifact",
        {
            "remote_notebook_id": remote_notebook_id,
            "artifact_type": artifact_type,
            "profile": profile,
            "target_notebook_id": target_notebook_id,
            "title": title,
            "report_format": report_format,
            "focus_prompt": focus_prompt,
            "language": language,
        },
    )
    logger.info(
        f"Submitted studio generation job {command_id} "
        f"(type={artifact_type} notebook={remote_notebook_id})"
    )
    return {"command_id": str(command_id), "artifact_type": artifact_type}


# =============================================================================
# Import (NotebookLM -> Open Notebook)
# =============================================================================


async def import_notebook(
    remote_notebook_id: str,
    target_notebook_id: Optional[str] = None,
    import_sources: bool = True,
    import_notes: bool = True,
    embed: bool = False,
    profile: Optional[str] = None,
) -> Dict[str, Any]:
    """Import a NotebookLM notebook's sources and notes into Open Notebook.

    ``profile`` selects which connected Google account owns the notebook.
    Network/blocking fetches against NotebookLM run in worker threads; the
    Open Notebook DB writes stay on the event loop (the domain layer is async).
    """
    warnings: List[str] = []

    # --- Fetch remote metadata + payloads in a worker thread -----------------
    def _fetch() -> Dict[str, Any]:
        client = _client_or_raise(profile)

        # Resolve a title for a newly created notebook.
        title = "Imported from NotebookLM"
        try:
            for nb in client.list_notebooks():
                if getattr(nb, "id", None) == remote_notebook_id:
                    title = getattr(nb, "title", title) or title
                    break
        except Exception as e:  # non-fatal: fall back to default title
            warnings.append(f"Could not resolve notebook title: {e}")

        sources: List[Dict[str, Any]] = []
        if import_sources:
            for s in client.get_notebook_sources_with_types(remote_notebook_id) or []:
                if not isinstance(s, dict):
                    continue
                sid = s.get("id") or s.get("source_id")
                if not sid:
                    continue
                full_text = ""
                src_title = s.get("title") or s.get("name") or "Untitled source"
                try:
                    ft = client.get_source_fulltext(sid) or {}
                    full_text = ft.get("content") or ft.get("text") or ""
                    src_title = ft.get("title") or src_title
                except Exception as e:
                    warnings.append(f"Source '{src_title}' text unavailable: {e}")
                sources.append(
                    {"id": sid, "title": src_title, "full_text": full_text}
                )

        notes: List[Dict[str, Any]] = []
        if import_notes:
            try:
                for n in client.list_notes(remote_notebook_id) or []:
                    if not isinstance(n, dict):
                        continue
                    notes.append(
                        {
                            "title": n.get("title") or "Imported note",
                            "content": n.get("content") or "",
                        }
                    )
            except Exception as e:
                warnings.append(f"Notes unavailable: {e}")

        return {"title": title, "sources": sources, "notes": notes}

    payload = await asyncio.to_thread(_fetch)

    # --- Resolve / create the target Open Notebook notebook ------------------
    created = False
    if target_notebook_id:
        try:
            notebook = await Notebook.get(target_notebook_id)
        except Exception as e:
            raise ValueError(
                f"Target notebook {target_notebook_id} not found"
            ) from e
    else:
        notebook = Notebook(
            name=payload["title"],
            description="Imported from Google NotebookLM",
        )
        await notebook.save()
        created = True

    notebook_id = str(notebook.id)

    # --- Write sources -------------------------------------------------------
    sources_imported = 0
    for s in payload["sources"]:
        text = (s.get("full_text") or "").strip()
        if not text:
            warnings.append(f"Skipped empty source '{s.get('title')}'")
            continue
        source = Source(
            title=s.get("title"),
            full_text=text,
            asset=Asset(url=f"notebooklm://{remote_notebook_id}/source/{s['id']}"),
        )
        await source.save()
        await source.add_to_notebook(notebook_id)
        if embed:
            try:
                await source.vectorize()
            except Exception as e:
                warnings.append(f"Embedding failed for '{s.get('title')}': {e}")
        sources_imported += 1

    # --- Write notes ---------------------------------------------------------
    notes_imported = 0
    for n in payload["notes"]:
        content = (n.get("content") or "").strip()
        if not content:
            continue
        note = Note(title=n.get("title"), content=content, note_type="ai")
        await note.save()
        await note.add_to_notebook(notebook_id)
        notes_imported += 1

    logger.info(
        f"NotebookLM import complete: notebook={notebook_id} "
        f"profile={profile} sources={sources_imported} notes={notes_imported} "
        f"warnings={len(warnings)}"
    )

    return {
        "notebook_id": notebook_id,
        "created_notebook": created,
        "sources_imported": sources_imported,
        "notes_imported": notes_imported,
        "warnings": warnings,
    }
