"""
AML Webhooks — приём уведомлений от ComplyAdvantage.
Endpoint без авторизации (ComplyAdvantage не отправляет bearer token).
Регистрация webhook выполняется на проде через POST /api/v1/aml/webhooks/register.
"""
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import require_staff_or_admin
from app.models import User, AmlCustomer, AmlAlert, AmlCase
from app.enums import AmlAlertStatus, AmlCaseStatus
from app.services.comply_advantage import comply_advantage_client
from app.services.aml_auto_screening import determine_risk_from_aml_types

logger = logging.getLogger("garudar_api")

router = APIRouter(prefix="/api/v1/aml/webhooks", tags=["AML Webhooks"])


@router.post("/comply-advantage")
async def handle_comply_advantage_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Приём webhook уведомлений от ComplyAdvantage.
    Без авторизации — ComplyAdvantage не шлёт bearer token.
    Всегда возвращает 200 (иначе ComplyAdvantage ретраит).
    """
    try:
        payload = await request.json()
    except Exception:
        logger.warning("AML webhook: невалидный JSON")
        return {"status": "ok"}

    # CA использует `webhook_type` (v1/v2/v3). Старый код смотрел на `type`, что
    # некорректно — оставляем fallback для совместимости с кастомными fixtures.
    event_type = payload.get("webhook_type") or payload.get("type", "UNKNOWN")
    logger.info(f"AML webhook получен: type={event_type}")
    logger.debug(f"AML webhook payload: {payload}")

    try:
        if event_type == "WORKFLOW_COMPLETED":
            await _handle_workflow_completed(payload, db)
        elif event_type == "CASE_CREATED":
            await _handle_case_created(payload, db)
        elif event_type == "CASE_ALERT_LIST_UPDATED":
            await _handle_alert_list_updated(payload, db)
        elif event_type in ("CUSTOMER_RISK_SCORE_CHANGED",
                            "CUSTOMER_RISK_LEVEL_INCREASED",
                            "CUSTOMER_RISK_LEVEL_DECREASED"):
            await _handle_risk_score_event(payload, db, event_type)
        else:
            logger.info(f"AML webhook: неизвестный тип {event_type}, игнорируем")
    except Exception as e:
        logger.error(f"AML webhook ошибка обработки ({event_type}): {e}", exc_info=True)

    return {"status": "ok"}


async def _handle_risk_score_event(payload: dict, db: AsyncSession, event_type: str):
    """Обработка webhook'ов CUSTOMER_RISK_SCORE_CHANGED и _LEVEL_*.

    CA v3-payload (flat): `customer_external_identifier`, `risk_score`,
    `previous_risk_score`. Находим клиента по external_identifier, обновляем
    risk_level + сохраняем сырой score blob в risk_score_breakdown.

    LEVEL_INCREASED по HIGH — автоматически holdим клиента в Garudar
    (как делает существующий _handle_workflow_completed).
    """
    external_identifier = payload.get("customer_external_identifier")
    if not external_identifier:
        logger.warning(f"AML webhook {event_type}: нет customer_external_identifier")
        return

    risk_score = payload.get("risk_score") or {}
    previous = payload.get("previous_risk_score") or {}
    new_level = (risk_score.get("level") or "").lower()
    previous_level = (previous.get("level") or "").lower() if previous else None

    logger.info(
        f"AML webhook {event_type}: customer={external_identifier} "
        f"level={previous_level or '?'}→{new_level or '?'}"
    )

    # CA "level" enum: LOW/MEDIUM/HIGH/PROHIBITED/SKIPPED. Маппинг в наш enum
    # (low/medium/high/unknown) — PROHIBITED → high, SKIPPED/None → unknown.
    level_map = {"low": "low", "medium": "medium", "high": "high", "prohibited": "high"}
    normalized_level = level_map.get(new_level)

    result = await db.execute(
        select(AmlCustomer).where(AmlCustomer.external_identifier == external_identifier)
    )
    customer = result.scalar_one_or_none()
    if not customer:
        logger.warning(f"AML webhook {event_type}: клиент external_id={external_identifier} не найден")
        return

    # Обновляем risk_level только если CA прислал валидный level и он отличается.
    if normalized_level and normalized_level != customer.risk_level:
        customer.risk_level = normalized_level

    # Всегда сохраняем свежий risk_score blob — UI возьмёт breakdown оттуда.
    customer.risk_score_breakdown = risk_score
    customer.updated_at = datetime.utcnow()
    await db.commit()

    # Автоматический hold при эскалации до HIGH (как в WORKFLOW_COMPLETED).
    if (
        event_type == "CUSTOMER_RISK_LEVEL_INCREASED"
        and normalized_level == "high"
        and customer.client_id
    ):
        from app.models import Client
        client_result = await db.execute(
            select(Client).where(Client.client_id == customer.client_id)
        )
        client = client_result.scalar_one_or_none()
        if client and client.account_status != "hold":
            client.account_status = "hold"
            client.account_hold_reason = "AML monitoring: risk level increased to HIGH"
            await db.commit()
            logger.warning(
                f"AML webhook {event_type}: клиент {customer.client_id} переведён в hold"
            )


async def _handle_workflow_completed(payload: dict, db: AsyncSession):
    """Мониторинг завершил пере-скрининг клиента"""
    data = payload.get("data", {})
    customer_identifier = data.get("customer_identifier")
    workflow_type = data.get("workflow_type")

    if not customer_identifier:
        logger.warning("AML webhook WORKFLOW_COMPLETED: нет customer_identifier")
        return

    logger.info(f"AML webhook WORKFLOW_COMPLETED: customer={customer_identifier}, type={workflow_type}")

    # Найти клиента в нашей БД
    result = await db.execute(
        select(AmlCustomer).where(AmlCustomer.customer_identifier == customer_identifier)
    )
    customer = result.scalar_one_or_none()
    if not customer:
        logger.warning(f"AML webhook: клиент {customer_identifier} не найден в БД")
        return

    # Получить обновлённый risk score из ComplyAdvantage
    try:
        ca_customer = await comply_advantage_client.get_customer(customer_identifier)
        risk_score_data = ca_customer.get("risk_score", {})
        overall_level = (risk_score_data.get("overall_level") or "").upper()

        level_map = {"LOW-RISK": "low", "MEDIUM-RISK": "medium", "HIGH-RISK": "high", "PROHIBITED": "high"}
        new_risk = level_map.get(overall_level, None)

        if new_risk and new_risk != customer.risk_level:
            old_risk = customer.risk_level
            customer.risk_level = new_risk
            customer.updated_at = datetime.utcnow()
            await db.commit()
            logger.info(f"AML webhook: обновлён risk_level {customer_identifier}: {old_risk} → {new_risk}")

            # Если high risk — check client hold
            if new_risk == "high" and customer.client_id:
                from app.models import Client
                client_result = await db.execute(
                    select(Client).where(Client.client_id == customer.client_id)
                )
                client = client_result.scalar_one_or_none()
                if client and client.account_status != "hold":
                    client.account_status = "hold"
                    client.account_hold_reason = "AML monitoring: high risk detected"
                    await db.commit()
                    logger.warning(f"AML webhook: клиент {customer.client_id} переведён в hold (monitoring)")
    except Exception as e:
        logger.error(f"AML webhook: ошибка получения данных клиента {customer_identifier}: {e}")


async def _handle_case_created(payload: dict, db: AsyncSession):
    """Новый кейс от мониторинга — создаём запись в БД"""
    data = payload.get("data", {})
    case_identifier = data.get("case_identifier")
    customer_identifier = data.get("customer_identifier")
    case_type = data.get("case_type", "UNKNOWN")

    logger.info(
        f"AML webhook CASE_CREATED: case={case_identifier}, "
        f"customer={customer_identifier}, type={case_type}"
    )

    if not case_identifier or not customer_identifier:
        return

    # Найти клиента в нашей БД
    result = await db.execute(
        select(AmlCustomer).where(AmlCustomer.customer_identifier == customer_identifier)
    )
    customer = result.scalar_one_or_none()
    if not customer:
        logger.warning(f"AML webhook CASE_CREATED: клиент {customer_identifier} не найден в БД")
        return

    # Идемпотентность: не создавать дубль
    existing = await db.execute(
        select(AmlCase).where(AmlCase.external_case_id == case_identifier)
    )
    if existing.scalar_one_or_none():
        logger.info(f"AML webhook CASE_CREATED: кейс {case_identifier} уже существует, пропускаем")
        return

    aml_case = AmlCase(
        aml_customer_id=customer.id,
        external_case_id=case_identifier,
        title=f"Monitoring Case ({case_type})",
        description=f"Case created by ComplyAdvantage monitoring. Type: {case_type}.",
        status=AmlCaseStatus.OPEN.value,
        created_at=datetime.utcnow(),
    )
    db.add(aml_case)
    await db.commit()
    logger.info(
        f"AML webhook CASE_CREATED: кейс {case_identifier} сохранён "
        f"для клиента {customer_identifier}"
    )


async def _handle_alert_list_updated(payload: dict, db: AsyncSession):
    """Новые алерты в кейсе от мониторинга"""
    data = payload.get("data", {})
    case_identifier = data.get("case_identifier")
    customer_identifier = data.get("customer_identifier")
    alerts = data.get("alerts", [])

    logger.info(
        f"AML webhook CASE_ALERT_LIST_UPDATED: case={case_identifier}, "
        f"customer={customer_identifier}, alerts_count={len(alerts)}"
    )

    if not customer_identifier or not alerts:
        return

    # Найти клиента
    result = await db.execute(
        select(AmlCustomer).where(AmlCustomer.customer_identifier == customer_identifier)
    )
    customer = result.scalar_one_or_none()
    if not customer:
        logger.warning(f"AML webhook ALERT_LIST_UPDATED: клиент {customer_identifier} не найден")
        return

    # Создать алерты для новых
    for alert_data in alerts:
        alert_id = alert_data.get("identifier", "")
        # Проверить что алерт ещё не существует
        existing = await db.execute(
            select(AmlAlert).where(
                AmlAlert.aml_customer_id == customer.id,
                AmlAlert.external_alert_id == str(alert_id),
            )
        )
        if existing.scalar_one_or_none():
            continue

        alert = AmlAlert(
            aml_customer_id=customer.id,
            external_alert_id=str(alert_id),
            title="Monitoring Alert",
            description=f"New alert from ongoing monitoring (case: {case_identifier})",
            match_type="monitoring",
            status=AmlAlertStatus.PENDING.value,
            created_at=datetime.utcnow(),
        )
        db.add(alert)

    await db.commit()
    logger.info(f"AML webhook: алерты сохранены для {customer_identifier}")


# ── Management endpoints (staff only) ───────────────────────────────

@router.post("/register")
async def register_webhook(
    request: Request,
    _: User = Depends(require_staff_or_admin),
):
    """
    Регистрация webhook URL в ComplyAdvantage.
    Вызывать на проде после деплоя.
    Body: { "base_url": "https://your-domain.com" }
    """
    body = await request.json()
    base_url = body.get("base_url", "").rstrip("/")
    if not base_url:
        raise HTTPException(400, detail="base_url обязателен")

    webhook_url = f"{base_url}/api/v1/aml/webhooks/comply-advantage"
    results = []

    event_types = [
        ("WORKFLOW_COMPLETED", "Garudar Workflow Completed"),
        ("CASE_CREATED", "Garudar Case Created"),
        ("CASE_ALERT_LIST_UPDATED", "Garudar Alert List Updated"),
    ]

    for event_type, name in event_types:
        try:
            result = await comply_advantage_client.register_webhook(
                url=webhook_url, event_type=event_type, name=name,
            )
            results.append({"type": event_type, "status": "ok", "id": result.get("identifier")})
            logger.info(f"Webhook зарегистрирован: {event_type} → {webhook_url}")
        except Exception as e:
            results.append({"type": event_type, "status": "error", "error": str(e)})
            logger.error(f"Ошибка регистрации webhook {event_type}: {e}")

    return {"webhook_url": webhook_url, "results": results}


@router.get("/list")
async def list_webhooks(
    _: User = Depends(require_staff_or_admin),
):
    """Список зарегистрированных webhooks в ComplyAdvantage"""
    try:
        return await comply_advantage_client.list_webhooks()
    except Exception as e:
        raise HTTPException(500, detail=f"Ошибка: {e}")
