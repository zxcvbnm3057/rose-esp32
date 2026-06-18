"""Custom command CRUD + execution endpoints."""
import json
import time
import asyncio
import logging
from fastapi import APIRouter, Depends, Path, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.database import get_session
from ..db import crud
from ..services import bridge_service
from ..services.cmd_executor import execute_command
from ..models.schemas import (
    ApiResponse, CustomCmdCreate, CustomCmdUpdate, CustomCmdExecuteRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/cmds", tags=["custom_cmds"])


def _cmd_to_dict(cmd) -> dict:
    steps = json.loads(cmd.steps_json) if cmd.steps_json else []
    return {
        "id": cmd.id,
        "slug": cmd.slug,
        "name": cmd.name,
        "description": cmd.description,
        "enabled": bool(cmd.enabled),
        "step_count": len(steps),
        "steps": steps,
        "external_url": f"/cmd/{cmd.slug}",
        "created_at": cmd.created_at.isoformat() if cmd.created_at else None,
        "updated_at": cmd.updated_at.isoformat() if cmd.updated_at else None,
        "last_executed_at": cmd.last_executed_at.isoformat() if cmd.last_executed_at else None,
        "execution_count": cmd.execution_count or 0,
    }


@router.get("")
async def list_commands(db: AsyncSession = Depends(get_session)):
    cmds = await crud.list_commands(db)
    return ApiResponse(
        success=True,
        data={"commands": [_cmd_to_dict(c) for c in cmds]},
        timestamp=time.time(),
    )


@router.post("")
async def create_command(req: CustomCmdCreate, db: AsyncSession = Depends(get_session)):
    existing = await crud.get_by_slug(db, req.slug)
    if existing:
        raise HTTPException(status_code=409, detail=f"Slug '{req.slug}' already exists")

    cmd = await crud.create_command(db, req.model_dump())
    return ApiResponse(success=True, data=_cmd_to_dict(cmd), timestamp=time.time())


@router.get("/{slug}")
async def get_command(slug: str = Path(...), db: AsyncSession = Depends(get_session)):
    cmd = await crud.get_by_slug(db, slug)
    if not cmd:
        raise HTTPException(status_code=404, detail="Command not found")
    return ApiResponse(success=True, data=_cmd_to_dict(cmd), timestamp=time.time())


@router.put("/{slug}")
async def update_command(slug: str = Path(...), req: CustomCmdUpdate = None, db: AsyncSession = Depends(get_session)):
    update_data = req.model_dump(exclude_unset=True)
    if "steps" in update_data:
        update_data["steps"] = [s.model_dump() for s in req.steps]

    cmd = await crud.update_command(db, slug, update_data)
    if not cmd:
        raise HTTPException(status_code=404, detail="Command not found")
    return ApiResponse(success=True, data=_cmd_to_dict(cmd), timestamp=time.time())


@router.delete("/{slug}")
async def delete_command(slug: str = Path(...), db: AsyncSession = Depends(get_session)):
    ok = await crud.delete_command(db, slug)
    if not ok:
        raise HTTPException(status_code=404, detail="Command not found")
    return ApiResponse(success=True, data={"slug": slug, "deleted": True}, timestamp=time.time())


@router.post("/{slug}/execute")
async def execute_internal(slug: str = Path(...), req: CustomCmdExecuteRequest = None, db: AsyncSession = Depends(get_session)):
    """Execute a custom command (internal API)."""
    cmd = await crud.get_by_slug(db, slug)
    if not cmd:
        raise HTTPException(status_code=404, detail="Command not found")
    if not cmd.enabled:
        return ApiResponse(success=False, error="Command is disabled", timestamp=time.time())

    steps = json.loads(cmd.steps_json)
    start = time.time()

    try:
        results = await execute_command(steps, req.params if req else {})
        duration_ms = int((time.time() - start) * 1000)
        await crud.record_execution(db, cmd.id, results, True, duration_ms=duration_ms)
        await crud.bump_execution_count(db, slug)
        return ApiResponse(
            success=True,
            data={"slug": slug, "steps_executed": len(steps), "results": results, "duration_ms": duration_ms},
            timestamp=time.time(),
        )
    except Exception as e:
        duration_ms = int((time.time() - start) * 1000)
        await crud.record_execution(db, cmd.id, [], False, str(e), duration_ms)
        return ApiResponse(success=False, error=str(e), timestamp=time.time())


# Dedicated public router — no prefix, maps POST /{slug} only
public_router = APIRouter(tags=["public_cmds"])


@public_router.post("/{slug}")
async def execute_public(slug: str = Path(...), db: AsyncSession = Depends(get_session)):
    """Public custom command execution via /cmd/{slug}."""
    cmd = await crud.get_by_slug(db, slug)
    if not cmd:
        raise HTTPException(status_code=404, detail="Command not found")
    if not cmd.enabled:
        return ApiResponse(success=False, error="Command is disabled", timestamp=time.time())

    steps = json.loads(cmd.steps_json)
    start = time.time()

    try:
        results = await execute_command(steps, {})
        duration_ms = int((time.time() - start) * 1000)
        await crud.record_execution(db, cmd.id, results, True, duration_ms=duration_ms)
        await crud.bump_execution_count(db, slug)
        return ApiResponse(
            success=True,
            data={"slug": slug, "steps_executed": len(steps), "results": results, "duration_ms": duration_ms},
            timestamp=time.time(),
        )
    except Exception as e:
        duration_ms = int((time.time() - start) * 1000)
        await crud.record_execution(db, cmd.id, [], False, str(e), duration_ms)
        return ApiResponse(success=False, error=str(e), timestamp=time.time())
