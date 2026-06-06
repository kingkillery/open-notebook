"""Router for the optional Google NotebookLM bridge (multi-account)."""

from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from loguru import logger

from api import notebooklm_service
from api.models import (
    NotebookLMAccount,
    NotebookLMImportRequest,
    NotebookLMImportResponse,
    NotebookLMQueryRequest,
    NotebookLMQueryResponse,
    NotebookLMRemoteNotebook,
    NotebookLMRemoteSource,
    NotebookLMStatusResponse,
)

router = APIRouter()


@router.get("/notebooklm/status", response_model=NotebookLMStatusResponse)
async def notebooklm_status():
    """Report install state plus every connected account's auth state."""
    try:
        return await notebooklm_service.get_status()
    except Exception as e:
        logger.error(f"NotebookLM status check failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/notebooklm/accounts", response_model=List[NotebookLMAccount])
async def notebooklm_accounts():
    """List all connected NotebookLM accounts with live auth state."""
    try:
        return await notebooklm_service.list_accounts()
    except Exception as e:
        logger.error(f"NotebookLM accounts failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/notebooklm/notebooks", response_model=List[NotebookLMRemoteNotebook])
async def notebooklm_list_notebooks(
    profile: Optional[str] = Query(
        None, description="Limit to one account; omit to aggregate across all"
    ),
):
    """List NotebookLM notebooks for one account, or all accounts if omitted."""
    try:
        return await notebooklm_service.list_remote_notebooks(profile=profile)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"NotebookLM list failed: {e}")
        raise HTTPException(status_code=502, detail=f"NotebookLM error: {e}")


@router.get(
    "/notebooklm/notebooks/{remote_notebook_id}/sources",
    response_model=List[NotebookLMRemoteSource],
)
async def notebooklm_list_sources(
    remote_notebook_id: str,
    profile: Optional[str] = Query(None, description="Account that owns the notebook"),
):
    """List sources for a remote NotebookLM notebook."""
    try:
        return await notebooklm_service.list_remote_sources(
            remote_notebook_id, profile=profile
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"NotebookLM sources failed: {e}")
        raise HTTPException(status_code=502, detail=f"NotebookLM error: {e}")


@router.post("/notebooklm/query", response_model=NotebookLMQueryResponse)
async def notebooklm_query(request: NotebookLMQueryRequest):
    """Ask a source-grounded question against a remote notebook."""
    try:
        return await notebooklm_service.query_remote(
            remote_notebook_id=request.remote_notebook_id,
            query_text=request.query,
            conversation_id=request.conversation_id,
            profile=request.profile,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"NotebookLM query failed: {e}")
        raise HTTPException(status_code=502, detail=f"NotebookLM error: {e}")


@router.post("/notebooklm/import", response_model=NotebookLMImportResponse)
async def notebooklm_import(request: NotebookLMImportRequest):
    """Import a NotebookLM notebook's sources and notes into Open Notebook."""
    try:
        return await notebooklm_service.import_notebook(
            remote_notebook_id=request.remote_notebook_id,
            target_notebook_id=request.target_notebook_id,
            import_sources=request.import_sources,
            import_notes=request.import_notes,
            embed=request.embed,
            profile=request.profile,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"NotebookLM import failed: {e}")
        raise HTTPException(status_code=502, detail=f"NotebookLM error: {e}")
