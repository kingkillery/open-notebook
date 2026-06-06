"""Surreal-commands job for NotebookLM Studio artifact generation.

Studio artifacts (audio overview, report, ...) take minutes to generate on
Google's side, so generation runs as an async background job: create the
artifact remotely, poll until it is ready, then pull the result into Open
Notebook (reports become Notes; audio is downloaded and attached as a Source).

Requires the surreal-commands worker to be running and the optional
``notebooklm`` extra to be installed.
"""

import asyncio
import time
import uuid
from pathlib import Path
from typing import Optional

from loguru import logger
from surreal_commands import CommandInput, CommandOutput, command

from open_notebook.config import DATA_FOLDER
from open_notebook.domain.notebook import Asset, Note, Notebook, Source

# Studio types this job knows how to create + attach. Extend here as more
# artifact types are wired through (video, infographic, slide_deck, ...).
SUPPORTED_TYPES = {"report", "audio"}

# Terminal poll states from notebooklm_tools.
_DONE = {"completed", "failed"}

POLL_INTERVAL_SECONDS = 6
POLL_TIMEOUT_SECONDS = 600  # studio generation can take several minutes


class StudioGenerationInput(CommandInput):
    remote_notebook_id: str
    artifact_type: str
    profile: Optional[str] = None
    target_notebook_id: Optional[str] = None  # ON notebook to attach to
    title: Optional[str] = None
    # Type-specific options
    report_format: str = "Briefing Doc"
    focus_prompt: str = ""
    language: str = "en"


class StudioGenerationOutput(CommandOutput):
    success: bool
    artifact_type: str
    artifact_id: Optional[str] = None
    notebook_id: Optional[str] = None
    note_id: Optional[str] = None
    source_id: Optional[str] = None
    file_path: Optional[str] = None
    processing_time: float = 0.0
    error_message: Optional[str] = None


def _existing_ids(client, remote_notebook_id: str, artifact_type: str) -> set:
    """Snapshot artifact ids of a type so we can spot the newly created one."""
    try:
        arts = client.poll_studio_status(remote_notebook_id) or []
    except Exception:
        return set()
    return {a.get("artifact_id") for a in arts if a.get("type") == artifact_type}


def _create(client, input_data: StudioGenerationInput):
    """Kick off the remote generation for the requested artifact type."""
    rid = input_data.remote_notebook_id
    if input_data.artifact_type == "report":
        return client.create_report(
            rid,
            report_format=input_data.report_format,
            custom_prompt=input_data.focus_prompt,
            language=input_data.language,
        )
    if input_data.artifact_type == "audio":
        return client.create_audio_overview(
            rid,
            language=input_data.language,
            focus_prompt=input_data.focus_prompt,
        )
    raise ValueError(f"Unsupported artifact type: {input_data.artifact_type}")


def _find_artifact(client, remote_notebook_id, artifact_type, before_ids):
    """Return the freshest artifact of the type, preferring newly created ones."""
    arts = [
        a
        for a in (client.poll_studio_status(remote_notebook_id) or [])
        if a.get("type") == artifact_type
    ]
    fresh = [a for a in arts if a.get("artifact_id") not in before_ids]
    pool = fresh or arts
    if not pool:
        return None
    # Prefer a terminal one, else the first.
    for a in pool:
        if a.get("status") in _DONE:
            return a
    return pool[0]


@command("generate_studio_artifact", app="open_notebook", retry={"max_attempts": 1})
async def generate_studio_artifact_command(
    input_data: StudioGenerationInput,
) -> StudioGenerationOutput:
    """Create a NotebookLM studio artifact, poll to completion, attach to ON."""
    start = time.time()
    artifact_type = input_data.artifact_type

    def _fail(msg: str) -> StudioGenerationOutput:
        logger.error(f"Studio generation failed: {msg}")
        return StudioGenerationOutput(
            success=False,
            artifact_type=artifact_type,
            processing_time=time.time() - start,
            error_message=msg,
        )

    if artifact_type not in SUPPORTED_TYPES:
        return _fail(
            f"Unsupported artifact type '{artifact_type}'. "
            f"Supported: {sorted(SUPPORTED_TYPES)}"
        )

    # --- Build client (worker thread) ----------------------------------------
    try:
        from open_notebook.integrations.notebooklm import get_client

        client = await asyncio.to_thread(get_client, input_data.profile)
    except Exception as e:
        return _fail(f"NotebookLM unavailable: {e}")

    rid = input_data.remote_notebook_id

    # --- Create + poll -------------------------------------------------------
    try:
        before = await asyncio.to_thread(
            _existing_ids, client, rid, artifact_type
        )
        await asyncio.to_thread(_create, client, input_data)
    except Exception as e:
        return _fail(f"Failed to start generation: {e}")

    artifact = None
    deadline = time.time() + POLL_TIMEOUT_SECONDS
    while time.time() < deadline:
        await asyncio.sleep(POLL_INTERVAL_SECONDS)
        try:
            artifact = await asyncio.to_thread(
                _find_artifact, client, rid, artifact_type, before
            )
        except Exception as e:
            logger.warning(f"Studio poll error (continuing): {e}")
            continue
        if artifact and artifact.get("status") in _DONE:
            break

    if not artifact:
        return _fail("No artifact was produced (timed out).")
    if artifact.get("status") == "failed":
        return _fail("NotebookLM reported generation failed.")
    if artifact.get("status") not in _DONE:
        return _fail("Timed out waiting for the artifact to finish.")

    artifact_id = artifact.get("artifact_id")
    title = input_data.title or artifact.get("title") or f"NotebookLM {artifact_type}"

    # --- Resolve/create the target ON notebook -------------------------------
    try:
        if input_data.target_notebook_id:
            notebook = await Notebook.get(input_data.target_notebook_id)
        else:
            notebook = Notebook(
                name=title,
                description="Generated via Google NotebookLM",
            )
            await notebook.save()
        notebook_id = str(notebook.id)
    except Exception as e:
        return _fail(f"Could not resolve target notebook: {e}")

    # --- Attach result -------------------------------------------------------
    try:
        if artifact_type == "report":
            # download_report extracts the canonical markdown body ([7][0]);
            # the poll status' report_content field ([7][1][0]) is unreliable
            # (often just the format label), so prefer the download.
            content = ""
            tmp = Path(DATA_FOLDER) / "notebooklm" / f"{uuid.uuid4()}.md"
            tmp.parent.mkdir(parents=True, exist_ok=True)
            try:
                await asyncio.to_thread(
                    client.download_report, rid, str(tmp), artifact_id
                )
                content = tmp.read_text(encoding="utf-8", errors="ignore")
            except Exception as e:
                logger.warning(f"download_report failed, falling back to poll: {e}")
            finally:
                tmp.unlink(missing_ok=True)
            # Fallback to the polled content only if download yielded nothing
            # substantial.
            if not content or len(content.strip()) < 40:
                content = artifact.get("report_content") or content
            if not content or not content.strip():
                return _fail("Report had no content.")
            note = Note(title=title, content=content, note_type="ai")
            await note.save()
            await note.add_to_notebook(notebook_id)
            return StudioGenerationOutput(
                success=True,
                artifact_type=artifact_type,
                artifact_id=artifact_id,
                notebook_id=notebook_id,
                note_id=str(note.id),
                processing_time=time.time() - start,
            )

        if artifact_type == "audio":
            out_dir = Path(DATA_FOLDER) / "notebooklm" / notebook_id.replace(":", "_")
            out_dir.mkdir(parents=True, exist_ok=True)
            out_path = out_dir / f"{uuid.uuid4()}.mp4"
            # download_audio is async in notebooklm_tools.
            await client.download_audio(rid, str(out_path), artifact_id)
            source = Source(
                title=title,
                full_text=f"Audio overview generated by NotebookLM: {title}",
                asset=Asset(file_path=str(out_path)),
            )
            await source.save()
            await source.add_to_notebook(notebook_id)
            return StudioGenerationOutput(
                success=True,
                artifact_type=artifact_type,
                artifact_id=artifact_id,
                notebook_id=notebook_id,
                source_id=str(source.id),
                file_path=str(out_path),
                processing_time=time.time() - start,
            )
    except Exception as e:
        return _fail(f"Failed to attach artifact: {e}")

    return _fail("Unhandled artifact type at attach stage.")
