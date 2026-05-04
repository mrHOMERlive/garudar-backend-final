from datetime import datetime
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import Optional
from app.db import get_db
from app.models import User, AppSetting, Role
from app.deps import get_current_active_user

router = APIRouter(tags=["Settings"])


class SettingUpdateDto(BaseModel):
    value: Optional[str] = None


def is_staff_or_admin(user: User) -> bool:
    return user.role in [Role.STAFF.value, Role.ADMIN.value]


@router.get(
    "",
    summary="Получить все настройки приложения",
)
async def get_settings(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(AppSetting))
    settings = result.scalars().all()
    return [
        {
            "key": s.key,
            "value": s.value,
            "updated_at": s.updated_at.isoformat() if s.updated_at else None,
        }
        for s in settings
    ]


@router.put(
    "/{key}",
    summary="Обновить настройку (только staff/admin)",
)
async def update_setting(
    key: str,
    dto: SettingUpdateDto,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    if not is_staff_or_admin(current_user):
        return JSONResponse(status_code=403, content={"error": "Staff access required"})
    
    result = await db.execute(select(AppSetting).where(AppSetting.key == key))
    setting = result.scalar_one_or_none()
    
    if setting is None:
        setting = AppSetting(key=key, value=dto.value, updated_at=datetime.utcnow())
        db.add(setting)
    else:
        setting.value = dto.value
        setting.updated_at = datetime.utcnow()
    
    await db.commit()
    await db.refresh(setting)
    
    return {
        "key": setting.key,
        "value": setting.value,
        "updated_at": setting.updated_at.isoformat() if setting.updated_at else None,
    }
