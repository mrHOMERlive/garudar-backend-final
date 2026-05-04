from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db import get_db
from app.models import User, ClientRequestBadge, Client, Role
from app.schemas import (
    ClientRequestBadgeDto,
    ClientRequestBadgeUpdateRequest,
    ClientBadgeUserDto,
)
from app.deps import require_admin, get_current_active_user
from app.enums import NDAStatus, BadgeStatus
from typing import Optional

router = APIRouter(tags=["Client Badges"])


@router.get("/badges", response_model=list[ClientRequestBadgeDto])
async def list_badges_by_type(
    type: Optional[str] = None,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
    skip: int = Query(0, ge=0, description="Пропустить N записей"),
    limit: int = Query(100, ge=1, le=500, description="Макс. кол-во записей"),
):
    """
    Получить все бейджи по типу (для Staff Dashboard).
    - ADMIN / STAFF: полный список всех клиентов.
    - USER: только свои бейджи (фильтрует по client_id текущего пользователя).
    """
    query = select(ClientRequestBadge)

    if type:
        query = query.where(ClientRequestBadge.badge_type == type)

    if current_user.role == Role.USER.value:
        result = await db.execute(
            select(Client.client_id).where(Client.user_id == current_user.user_id)
        )
        user_client_ids = [row[0] for row in result.all()]
        query = query.where(ClientRequestBadge.client_id.in_(user_client_ids))

    query = query.order_by(ClientRequestBadge.updated_at.desc()).offset(skip).limit(limit)
    result = await db.execute(query)
    badges = result.scalars().all()

    if current_user.role == Role.USER.value:
        return [ClientBadgeUserDto.model_validate(b, from_attributes=True) for b in badges]

    return [ClientRequestBadgeDto.model_validate(b, from_attributes=True) for b in badges]


@router.get("/clients/{client_id}/badges")
async def get_client_badges(
    client_id: str,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Получить бейджи для клиента.
    - USER: только свои бейджи (проверка client.user_id), упрощённая DTO.
    - ADMIN / STAFF: любые клиенты, полная DTO.
    """
    result = await db.execute(
        select(Client).where(Client.client_id == client_id)
    )
    client = result.scalar_one_or_none()

    if client is None:
        raise HTTPException(status_code=404, detail="Client not found")

    if current_user.role == Role.USER.value:
        if client.user_id != current_user.user_id:
            raise HTTPException(status_code=403, detail="Access denied: you can only view your own badges")

    result = await db.execute(
        select(ClientRequestBadge)
        .where(ClientRequestBadge.client_id == client_id)
        .order_by(ClientRequestBadge.badge_type)
    )
    badges = result.scalars().all()

    if current_user.role == Role.USER.value:
        return [ClientBadgeUserDto.model_validate(badge, from_attributes=True) for badge in badges]

    return [ClientRequestBadgeDto.model_validate(badge, from_attributes=True) for badge in badges]


@router.put("/clients/{client_id}/badges/{badge_type}", response_model=ClientRequestBadgeDto)
async def upsert_client_badge(
    client_id: str,
    badge_type: str,
    data: ClientRequestBadgeUpdateRequest,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Создать или обновить бейдж определенного типа для клиента (Upsert).
    Только для ADMIN.
    """
    result = await db.execute(
        select(Client).where(Client.client_id == client_id)
    )
    client = result.scalar_one_or_none()
    
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found")
    
    result = await db.execute(
        select(ClientRequestBadge)
        .where(
            ClientRequestBadge.client_id == client_id,
            ClientRequestBadge.badge_type == badge_type
        )
    )
    badge = result.scalar_one_or_none()
    
    if badge is None:
        badge = ClientRequestBadge(
            client_id=client_id,
            badge_type=badge_type,
            status=data.status if data.status is not None else "not_required",
            is_active=data.is_active if data.is_active is not None else False,
            staff_comment=data.staff_comment,
            document_url=data.document_url,
            submitted_document_url=data.submitted_document_url,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        db.add(badge)
    else:
        update_data = data.model_dump(exclude_unset=True, exclude_none=True)
        for field, value in update_data.items():
            setattr(badge, field, value)
        badge.updated_at = datetime.utcnow()
    
    await db.commit()
    await db.refresh(badge)
    
    return ClientRequestBadgeDto.model_validate(badge, from_attributes=True)


@router.put("/badges/{badge_id}", response_model=ClientRequestBadgeDto)
async def update_badge(
    badge_id: int,
    data: ClientRequestBadgeUpdateRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Обновить бейдж по ID.
    - USER: может обновлять submitted_document_url, status.
      При смене status на 'submitted' для badge_type='other_submit' —
      обновляется nda_status клиента на 'signed_uploaded'.
    - ADMIN / STAFF: может обновлять любые поля, включая
      staff_comment, is_active, document_url, status.
    """
    result = await db.execute(
        select(ClientRequestBadge).where(ClientRequestBadge.id == badge_id)
    )
    badge = result.scalar_one_or_none()
    if badge is None:
        raise HTTPException(status_code=404, detail="Badge not found")

    result = await db.execute(
        select(Client).where(Client.client_id == badge.client_id)
    )
    client = result.scalar_one_or_none()
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found")

    is_staff_or_admin = current_user.role != Role.USER.value

    if current_user.role == Role.USER.value:
        if client.user_id != current_user.user_id:
            raise HTTPException(status_code=403, detail="Access denied")

    old_status = badge.status

    if is_staff_or_admin:
        # Staff/Admin могут обновлять все поля
        update_data = data.model_dump(exclude_unset=True, exclude_none=True)
        for field, value in update_data.items():
            setattr(badge, field, value)
    else:
        # Клиент может обновлять только определённые поля
        if data.submitted_document_url is not None:
            badge.submitted_document_url = data.submitted_document_url
        if data.status is not None:
            badge.status = data.status

    badge.updated_at = datetime.utcnow()

    # Бизнес-логика: при submitted бейджа other_submit -> обновить nda_status
    if (
        data.status == "submitted"
        and old_status != "submitted"
        and badge.badge_type == "other_submit"
    ):
        client.nda_status = NDAStatus.SIGNED_UPLOADED.value

    await db.commit()
    await db.refresh(badge)

    return ClientRequestBadgeDto.model_validate(badge, from_attributes=True)
