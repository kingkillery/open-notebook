from typing import List

from fastapi import APIRouter, HTTPException
from loguru import logger

from api.models import (
    ContextRequest,
    DefaultPromptResponse,
    DefaultPromptUpdate,
    NotebookTransformationExecuteRequest,
    NotebookTransformationExecuteResponse,
    NoteResponse,
    TransformationCreate,
    TransformationExecuteRequest,
    TransformationExecuteResponse,
    TransformationResponse,
    TransformationUpdate,
)
from api.routers.context import get_notebook_context
from open_notebook.ai.models import Model, ModelManager
from open_notebook.domain.notebook import Note, Notebook
from open_notebook.domain.transformation import DefaultPrompts, Transformation
from open_notebook.exceptions import InvalidInputError, OpenNotebookError
from open_notebook.graphs.transformation import graph as transformation_graph

router = APIRouter()


@router.get("/transformations", response_model=List[TransformationResponse])
async def get_transformations():
    """Get all transformations."""
    try:
        transformations = await Transformation.get_all(order_by="name asc")

        return [
            TransformationResponse(
                id=transformation.id or "",
                name=transformation.name,
                title=transformation.title,
                description=transformation.description,
                prompt=transformation.prompt,
                apply_default=transformation.apply_default,
                created=str(transformation.created),
                updated=str(transformation.updated),
            )
            for transformation in transformations
        ]
    except Exception as e:
        logger.error(f"Error fetching transformations: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Error fetching transformations: {str(e)}"
        )


@router.post("/transformations", response_model=TransformationResponse)
async def create_transformation(transformation_data: TransformationCreate):
    """Create a new transformation."""
    try:
        new_transformation = Transformation(
            name=transformation_data.name,
            title=transformation_data.title,
            description=transformation_data.description,
            prompt=transformation_data.prompt,
            apply_default=transformation_data.apply_default,
        )
        await new_transformation.save()

        return TransformationResponse(
            id=new_transformation.id or "",
            name=new_transformation.name,
            title=new_transformation.title,
            description=new_transformation.description,
            prompt=new_transformation.prompt,
            apply_default=new_transformation.apply_default,
            created=str(new_transformation.created),
            updated=str(new_transformation.updated),
        )
    except InvalidInputError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error creating transformation: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Error creating transformation: {str(e)}"
        )


@router.post("/transformations/execute", response_model=TransformationExecuteResponse)
async def execute_transformation(execute_request: TransformationExecuteRequest):
    """Execute a transformation on input text."""
    try:
        # Validate transformation exists
        transformation = await Transformation.get(execute_request.transformation_id)
        if not transformation:
            raise HTTPException(status_code=404, detail="Transformation not found")

        # Validate model exists
        model = await Model.get(execute_request.model_id)
        if not model:
            raise HTTPException(status_code=404, detail="Model not found")

        # Execute the transformation
        result = await transformation_graph.ainvoke(
            dict(  # type: ignore[arg-type]
                input_text=execute_request.input_text,
                transformation=transformation,
            ),
            config=dict(configurable={"model_id": execute_request.model_id}),
        )

        return TransformationExecuteResponse(
            output=result["output"],
            transformation_id=execute_request.transformation_id,
            model_id=execute_request.model_id,
        )

    except HTTPException:
        raise
    except OpenNotebookError:
        raise  # Let global exception handlers return proper status codes
    except Exception as e:
        logger.error(f"Error executing transformation: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Error executing transformation: {str(e)}"
        )


def _context_to_markdown(context_data: dict) -> str:
    sections: list[str] = []
    sources = context_data.get("sources") or []
    notes = context_data.get("notes") or []

    if sources:
        source_lines = ["# Sources"]
        for index, source in enumerate(sources, start=1):
            source_lines.append(f"## Source {index}")
            source_lines.append(str(source))
        sections.append("\n\n".join(source_lines))

    if notes:
        note_lines = ["# Notes"]
        for index, note in enumerate(notes, start=1):
            note_lines.append(f"## Note {index}")
            note_lines.append(str(note))
        sections.append("\n\n".join(note_lines))

    return "\n\n".join(sections).strip()


@router.post(
    "/notebooks/{notebook_id}/transformations/{transformation_id}/execute",
    response_model=NotebookTransformationExecuteResponse,
)
async def execute_notebook_transformation(
    notebook_id: str,
    transformation_id: str,
    execute_request: NotebookTransformationExecuteRequest,
):
    """Execute a transformation against notebook context and optionally save it as a note."""
    try:
        notebook = await Notebook.get(notebook_id)
        if not notebook:
            raise HTTPException(status_code=404, detail="Notebook not found")

        transformation = await Transformation.get(transformation_id)
        if not transformation:
            raise HTTPException(status_code=404, detail="Transformation not found")

        model_manager = ModelManager()
        defaults = await model_manager.get_defaults()
        model_id = defaults.default_transformation_model or defaults.default_chat_model
        if not model_id:
            raise HTTPException(
                status_code=422,
                detail="No default transformation or chat model is configured.",
            )

        model = await Model.get(model_id)
        if not model:
            raise HTTPException(status_code=404, detail="Default transformation model not found")

        context_response = await get_notebook_context(
            notebook_id,
            ContextRequest(
                notebook_id=notebook_id,
                context_config=execute_request.context_config,
            ),
        )
        input_text = _context_to_markdown(
            {
                "sources": context_response.sources,
                "notes": context_response.notes,
            }
        )
        if not input_text:
            raise HTTPException(
                status_code=400,
                detail="Notebook context is empty. Select at least one source or note.",
            )

        result = await transformation_graph.ainvoke(
            dict(  # type: ignore[arg-type]
                input_text=input_text,
                transformation=transformation,
            ),
            config=dict(configurable={"model_id": model_id}),
        )

        note_response = None
        if execute_request.save_as_note:
            note = Note(
                title=execute_request.note_title or transformation.title,
                content=result["output"],
                note_type="ai",
            )
            command_id = await note.save()
            await note.add_to_notebook(notebook_id)
            note_response = NoteResponse(
                id=note.id or "",
                title=note.title,
                content=note.content,
                note_type=note.note_type,
                created=str(note.created),
                updated=str(note.updated),
                command_id=str(command_id) if command_id else None,
            )

        return NotebookTransformationExecuteResponse(
            output=result["output"],
            transformation_id=transformation_id,
            model_id=model_id,
            notebook_id=notebook_id,
            note=note_response,
        )

    except HTTPException:
        raise
    except OpenNotebookError:
        raise
    except Exception as e:
        logger.error(f"Error executing notebook transformation: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error executing notebook transformation: {str(e)}",
        )


@router.get("/transformations/default-prompt", response_model=DefaultPromptResponse)
async def get_default_prompt():
    """Get the default transformation prompt."""
    try:
        default_prompts: DefaultPrompts = await DefaultPrompts.get_instance()  # type: ignore[assignment]

        return DefaultPromptResponse(
            transformation_instructions=default_prompts.transformation_instructions
            or ""
        )
    except Exception as e:
        logger.error(f"Error fetching default prompt: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Error fetching default prompt: {str(e)}"
        )


@router.put("/transformations/default-prompt", response_model=DefaultPromptResponse)
async def update_default_prompt(prompt_update: DefaultPromptUpdate):
    """Update the default transformation prompt."""
    try:
        default_prompts: DefaultPrompts = await DefaultPrompts.get_instance()  # type: ignore[assignment]

        default_prompts.transformation_instructions = (
            prompt_update.transformation_instructions
        )
        await default_prompts.update()

        return DefaultPromptResponse(
            transformation_instructions=default_prompts.transformation_instructions
        )
    except Exception as e:
        logger.error(f"Error updating default prompt: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Error updating default prompt: {str(e)}"
        )


@router.get(
    "/transformations/{transformation_id}", response_model=TransformationResponse
)
async def get_transformation(transformation_id: str):
    """Get a specific transformation by ID."""
    try:
        transformation = await Transformation.get(transformation_id)
        if not transformation:
            raise HTTPException(status_code=404, detail="Transformation not found")

        return TransformationResponse(
            id=transformation.id or "",
            name=transformation.name,
            title=transformation.title,
            description=transformation.description,
            prompt=transformation.prompt,
            apply_default=transformation.apply_default,
            created=str(transformation.created),
            updated=str(transformation.updated),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching transformation {transformation_id}: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Error fetching transformation: {str(e)}"
        )


@router.put(
    "/transformations/{transformation_id}", response_model=TransformationResponse
)
async def update_transformation(
    transformation_id: str, transformation_update: TransformationUpdate
):
    """Update a transformation."""
    try:
        transformation = await Transformation.get(transformation_id)
        if not transformation:
            raise HTTPException(status_code=404, detail="Transformation not found")

        # Update only provided fields
        if transformation_update.name is not None:
            transformation.name = transformation_update.name
        if transformation_update.title is not None:
            transformation.title = transformation_update.title
        if transformation_update.description is not None:
            transformation.description = transformation_update.description
        if transformation_update.prompt is not None:
            transformation.prompt = transformation_update.prompt
        if transformation_update.apply_default is not None:
            transformation.apply_default = transformation_update.apply_default

        await transformation.save()

        return TransformationResponse(
            id=transformation.id or "",
            name=transformation.name,
            title=transformation.title,
            description=transformation.description,
            prompt=transformation.prompt,
            apply_default=transformation.apply_default,
            created=str(transformation.created),
            updated=str(transformation.updated),
        )
    except HTTPException:
        raise
    except InvalidInputError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error updating transformation {transformation_id}: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Error updating transformation: {str(e)}"
        )


@router.delete("/transformations/{transformation_id}")
async def delete_transformation(transformation_id: str):
    """Delete a transformation."""
    try:
        transformation = await Transformation.get(transformation_id)
        if not transformation:
            raise HTTPException(status_code=404, detail="Transformation not found")

        await transformation.delete()

        return {"message": "Transformation deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting transformation {transformation_id}: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Error deleting transformation: {str(e)}"
        )
