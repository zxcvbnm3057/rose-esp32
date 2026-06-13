"""CRUD operations for custom commands."""
from __future__ import annotations
import json
from datetime import datetime
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ..models.custom_cmd import CustomCommand, ExecutionLog


async def list_commands(db: AsyncSession) -> list[CustomCommand]:
    result = await db.execute(
        select(CustomCommand).order_by(CustomCommand.updated_at.desc())
    )
    return list(result.scalars().all())


async def get_by_slug(db: AsyncSession, slug: str) -> Optional[CustomCommand]:
    result = await db.execute(select(CustomCommand).where(CustomCommand.slug == slug))
    return result.scalar_one_or_none()


async def create_command(db: AsyncSession, data: dict) -> CustomCommand:
    cmd = CustomCommand(
        slug=data["slug"],
        name=data["name"],
        description=data.get("description", ""),
        steps_json=json.dumps(data["steps"], ensure_ascii=False),
        enabled=1,
    )
    db.add(cmd)
    await db.commit()
    await db.refresh(cmd)
    return cmd


async def update_command(db: AsyncSession, slug: str, data: dict) -> Optional[CustomCommand]:
    cmd = await get_by_slug(db, slug)
    if not cmd:
        return None
    for field in ("name", "description", "enabled"):
        if field in data and data[field] is not None:
            setattr(cmd, field, data[field])
    if "steps" in data and data["steps"] is not None:
        cmd.steps_json = json.dumps(data["steps"], ensure_ascii=False)
    cmd.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(cmd)
    return cmd


async def delete_command(db: AsyncSession, slug: str) -> bool:
    cmd = await get_by_slug(db, slug)
    if not cmd:
        return False
    await db.delete(cmd)
    await db.commit()
    return True


async def record_execution(db: AsyncSession, command_id: int, steps_results: list,
                           success: bool, error_message: str = "", duration_ms: int = 0):
    log = ExecutionLog(
        command_id=command_id,
        steps_results=json.dumps(steps_results, ensure_ascii=False, default=str),
        success=1 if success else 0,
        error_message=error_message,
        duration_ms=duration_ms,
    )
    db.add(log)
    await db.commit()


async def bump_execution_count(db: AsyncSession, slug: str):
    cmd = await get_by_slug(db, slug)
    if cmd:
        cmd.execution_count = (cmd.execution_count or 0) + 1
        cmd.last_executed_at = datetime.utcnow()
        await db.commit()
