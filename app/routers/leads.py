from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from datetime import datetime
import logging
from typing import Optional

from app.db import get_db
from app.models import Client, Lead, User
from app.schemas import (
    LeadCreate,
    LeadListResponse,
    LeadResponse,
    LeadStatus,
    LeadSubmitResponse,
    LeadUpdate,
)
from app.email import send_lead_notification
from app.rate_limit import limiter
from app.deps import require_admin

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["leads"])


@router.post("/leads", response_model=LeadSubmitResponse, status_code=status.HTTP_200_OK)
@limiter.limit("5/minute")
async def create_lead(
    request: Request,
    lead_data: LeadCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """
    Endpoint для создания нового B2B лида с защитой от спама (Honeypot).
    
    **Honeypot защита:**
    - Скрытое поле `website_url` не должно быть заполнено реальными пользователями
    - Если поле заполнено, это скорее всего бот - возвращаем успешный ответ без сохранения
    
    **Процесс:**
    1. Проверка honeypot поля
    2. Сохранение лида в базу данных
    3. Отправка уведомления администратору (в фоновом режиме)
    """
    
    # ========================================================================
    # HONEYPOT ЗАЩИТА
    # ========================================================================
    # Если скрытое поле website_url заполнено, это вероятно бот
    # Возвращаем успешный ответ, но ничего не сохраняем и не отправляем
    if lead_data.website_url:
        logger.warning(
            f"Honeypot triggered for email: {lead_data.business_email}, "
            f"website_url value: {lead_data.website_url}"
        )
        # Возвращаем успешный ответ, чтобы обмануть бота
        return LeadSubmitResponse(
            success=True,
            message="Thank you for your interest! We will contact you soon."
        )
    
    # ========================================================================
    # ВАЛИДАЦИЯ И СОХРАНЕНИЕ ЛИДА
    # ========================================================================
    try:
        # Создаем новый лид
        new_lead = Lead(
            company_name=lead_data.company_name,
            country=lead_data.country,
            contact_person=lead_data.contact_person,
            business_email=lead_data.business_email,
            phone=lead_data.phone,
            products_interested=lead_data.products_interested,
            monthly_volume=lead_data.monthly_volume,
            message=lead_data.message,
            is_agreed=lead_data.is_agreed,
            status="new",
            created_at=datetime.utcnow()
        )
        
        db.add(new_lead)
        await db.commit()
        await db.refresh(new_lead)
        
        logger.info(f"New lead created: ID={new_lead.id}, Email={new_lead.business_email}")
        
        # ========================================================================
        # ОТПРАВКА EMAIL УВЕДОМЛЕНИЯ (в фоновом режиме)
        # ========================================================================
        lead_dict = {
            "id": new_lead.id,
            "company_name": new_lead.company_name,
            "country": new_lead.country or "Not specified",
            "contact_person": new_lead.contact_person,
            "business_email": new_lead.business_email,
            "phone": new_lead.phone or "Not provided",
            "products_interested": new_lead.products_interested or [],
            "monthly_volume": new_lead.monthly_volume,
            "message": new_lead.message or "No message provided",
            "created_at": new_lead.created_at.strftime("%Y-%m-%d %H:%M:%S UTC")
        }
        
        # Добавляем задачу отправки email в фоновый режим
        background_tasks.add_task(send_lead_notification, lead_dict)
        
        return LeadSubmitResponse(
            success=True,
            message="Thank you for your interest! We will contact you soon."
        )
        
    except Exception as e:
        await db.rollback()
        logger.error(f"Error creating lead: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while processing your request. Please try again later."
        )


@router.get("/leads", response_model=LeadListResponse)
async def list_leads(
    status_filter: Optional[LeadStatus] = Query(default=None, alias="status"),
    limit: int = 100,
    offset: int = 0,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Список всех лидов с пагинацией и опциональным фильтром по статусу.
    Admin-only. Используется страницей StaffLeads.
    """
    # Clamp pagination params to safe bounds.
    limit = max(1, min(limit, 500))
    offset = max(0, offset)

    base_q = select(Lead).order_by(Lead.created_at.desc())
    count_q = select(func.count()).select_from(Lead)

    if status_filter is not None:
        base_q = base_q.where(Lead.status == status_filter.value)
        count_q = count_q.where(Lead.status == status_filter.value)

    total = (await db.execute(count_q)).scalar_one()
    rows = (await db.execute(base_q.limit(limit).offset(offset))).scalars().all()
    return LeadListResponse(items=list(rows), total=total)


@router.get("/leads/{lead_id}", response_model=LeadResponse)
async def get_lead(
    lead_id: int,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Получить информацию о лиде по ID (для внутреннего использования).
    """
    result = await db.execute(select(Lead).where(Lead.id == lead_id))
    lead = result.scalar_one_or_none()

    if not lead:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Lead with ID {lead_id} not found"
        )

    return lead


@router.patch("/leads/{lead_id}", response_model=LeadResponse)
async def update_lead(
    lead_id: int,
    payload: LeadUpdate,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Обновить статус лида и/или ссылку на сконвертированного Client'а.
    Используется страницей StaffLeads (inline status dropdown) и после
    успешного prefill-Convert в StaffClients (linking converted_client_id).
    Admin-only.
    """
    lead = (
        await db.execute(select(Lead).where(Lead.id == lead_id))
    ).scalar_one_or_none()
    if not lead:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Lead with ID {lead_id} not found",
        )

    if payload.status is not None:
        lead.status = payload.status.value

    if payload.converted_client_id is not None:
        client = (
            await db.execute(
                select(Client).where(Client.client_id == payload.converted_client_id)
            )
        ).scalar_one_or_none()
        if not client:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Client {payload.converted_client_id} not found",
            )
        lead.converted_client_id = payload.converted_client_id

    await db.commit()
    await db.refresh(lead)
    return lead
