"""NotebookLM bridge service.

Business logic for the optional Google NotebookLM integration. Wraps the
synchronous ``notebooklm_tools`` client with ``asyncio.to_thread`` so it plays
nicely with the async API layer, and maps NotebookLM data onto Open Notebook's
own ``Notebook`` / ``Source`` / ``Note`` domain models.

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
    get_client,
    is_available,
)

# =============================================================================
# Status / auth
# =============================================================================


async def get_status() -> Dict[str, Any]:
    """Report integration availability and live authentication state."""
    if not is_available():
        return {
            "available": False,
            "authenticated": False,
            "message": (
                "NotebookLM integration not installed. "
                "Run: uv sync --extra notebooklm"
            ),
        }

    def _probe() -> Dict[str, Any]:
        try:
            client = get_client()
        except NotebookLMNotAuthenticatedError as e:
            return {"available": True, "authenticated": False, "message": str(e)}
        except NotebookLMNotAvailableError as e:
            return {"available": False, "authenticated": False, "message": str(e)}

        try:
            # A cheap authenticated RPC doubles as a liveness check.
            client.list_notebooks()
            return {
                "available": True,
                "authenticated": True,
                "message": "Connected to Google NotebookLM.",
            }
        except Exception as e:  # AuthenticationError or transport failure
            msg = str(e)
            if "Authentication" in msg or "expired" in msg.lower():
                msg = (
                    "Google session expired. Run 'nlm login' to refresh your "
                    "NotebookLM cookies."
                )
            return {"available": True, "authenticated": False, "message": msg}

    return await asyncio.to_thread(_probe)


# =============================================================================
# Internal client helpers
# =============================================================================


def _client_or_raise():
    """Build a client in the calling (worker) thread, mapping errors to ValueError."""
    try:
        return get_client()
    except NotebookLMNotAvailableError as e:
        raise ValueError(str(e)) from e
    except NotebookLMNotAuthenticatedError as e:
        raise ValueError(str(e)) from e


# =============================================================================
# Remote browsing
# =============================================================================


async def list_remote_notebooks() -> List[Dict[str, Any]]:
    """List the user's NotebookLM notebooks."""

    def _run() -> List[Dict[str, Any]]:
        client = _client_or_raise()
        notebooks = client.list_notebooks()
        out: List[Dict[str, Any]] = []
        for nb in notebooks:
            out.append(
                {
                    "id": getattr(nb, "id", None),
                    "title": getattr(nb, "title", "") or "Untitled",
                    "source_count": getattr(nb, "source_count", 0) or 0,
                    "is_owned": getattr(nb, "is_owned", True),
                    "is_shared": getattr(nb, "is_shared", False),
                    "created_at": getattr(nb, "created_at", None),
                    "modified_at": getattr(nb, "modified_at", None),
                    "url": getattr(nb, "url", None),
                }
            )
        return out

    return await asyncio.to_thread(_run)


async def list_remote_sources(remote_notebook_id: str) -> List[Dict[str, Any]]:
    """List sources (with type info) for a remote notebook."""

    def _run() -> List[Dict[str, Any]]:
        client = _client_or_raise()
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
) -> Dict[str, Any]:
    """Ask a question grounded in a remote notebook's sources."""

    def _run() -> Dict[str, Any]:
        client = _client_or_raise()
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
# Import (NotebookLM -> Open Notebook)
# =============================================================================


async def import_notebook(
    remote_notebook_id: str,
    target_notebook_id: Optional[str] = None,
    import_sources: bool = True,
    import_notes: bool = True,
    embed: bool = False,
) -> Dict[str, Any]:
    """Import a NotebookLM notebook's sources and notes into Open Notebook.

    Network/blocking fetches against NotebookLM run in worker threads; the
    Open Notebook DB writes stay on the event loop (the domain layer is async).
    """
    warnings: List[str] = []

    # --- Fetch remote metadata + payloads in a worker thread -----------------
    def _fetch() -> Dict[str, Any]:
        client = _client_or_raise()

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
        f"sources={sources_imported} notes={notes_imported} "
        f"warnings={len(warnings)}"
    )

    return {
        "notebook_id": notebook_id,
        "created_notebook": created,
        "sources_imported": sources_imported,
        "notes_imported": notes_imported,
        "warnings": warnings,
    }
