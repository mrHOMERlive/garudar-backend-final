"""
Авто-скрининг AML при одобрении KYC.
Скринит компанию, директора и всех UBO/акционеров через ComplyAdvantage.
"""
import uuid
import logging
from datetime import datetime
from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Client, OnboardingKycProfile, OnboardingKycUbo,
    AmlCustomer, AmlScreening, AmlAlert,
)
from app.enums import AmlCustomerType, AmlRiskLevel, AmlAlertStatus, AmlScreeningType
from app.services.comply_advantage import comply_advantage_client

logger = logging.getLogger("garudar_api")


def determine_risk_from_aml_types(aml_types: list[str]) -> str:
    """Определить risk_level по списку aml_types из ComplyAdvantage"""
    types_lower = [t.lower() for t in aml_types]
    if any(t == "sanction" for t in types_lower):
        return "high"
    if any(t.startswith("pep") for t in types_lower):
        return "medium"
    if aml_types:
        return "medium"
    return "unknown"


def _step_output(raw: dict, step_name: str) -> dict:
    """Извлечь step_output из ответа workflow create-and-screen"""
    return raw.get("step_details", {}).get(step_name, {}).get("step_output", {})


def _parse_ca_response(raw: dict) -> dict:
    """Извлечь ключевые поля из ответа ComplyAdvantage create-and-screen workflow"""
    creation = _step_output(raw, "customer-creation")
    customer_id = creation.get("customer_identifier")

    risk = _step_output(raw, "initial-risk-scoring")
    overall_level = (risk.get("overall_level") or "UNKNOWN").upper()
    level_map = {"LOW-RISK": "low", "MEDIUM-RISK": "medium", "HIGH-RISK": "high", "PROHIBITED": "high"}
    risk_level = level_map.get(overall_level, "unknown")

    screening = _step_output(raw, "customer-screening")
    screening_result = screening.get("screening_result")

    # Fallback если Risk Model не настроена (SKIPPED) — только при реальном ответе API
    if risk_level == "unknown" and screening_result is not None:
        if screening_result == "HAS_PROFILES":
            risk_level = "medium"
        elif screening_result == "NO_PROFILES":
            risk_level = "low"

    return {
        "customer_identifier": str(customer_id) if customer_id else None,
        "risk_level": risk_level,
        "screening_result": screening_result,
    }


def _extract_alerts(raw: dict) -> list[dict]:
    """Извлечь алерты из ответа workflow create-and-screen"""
    alerts = []
    alerting = _step_output(raw, "alerting")
    for a in alerting.get("alerts", []):
        if isinstance(a, dict):
            alert_id = a.get("identifier") or a.get("id") or ""
            alerts.append({
                "external_alert_id": str(alert_id),
                "title": a.get("title") or "Screening Match",
                "description": a.get("description"),
                "match_type": a.get("match_type") or "screening",
            })
    if not alerts:
        screening = _step_output(raw, "customer-screening")
        aml_types = screening.get("aml_types", [])
        if aml_types and screening.get("screening_result") == "HAS_PROFILES":
            alerts.append({
                "external_alert_id": "",
                "title": "Screening Match: " + ", ".join(aml_types[:3]),
                "description": f"Matched AML types: {', '.join(aml_types)}",
                "match_type": "screening",
            })
    return alerts


async def _screen_and_save(
    db: AsyncSession,
    client_id: str,
    name: str,
    customer_type: str,
    screen_fn,
    screen_kwargs: dict,
    created_by: Optional[str] = None,
) -> AmlCustomer:
    """Общая логика: вызвать скрининг → сохранить AmlCustomer + AmlScreening + AmlAlert"""
    raw = {}
    try:
        raw = await screen_fn(**screen_kwargs)
    except RuntimeError as e:
        logger.warning(f"ComplyAdvantage не настроен: {e}")
    except Exception as e:
        logger.error(f"Ошибка ComplyAdvantage скрининга ({name}): {e}")

    # Обогащение: получить детали рисков из всех алертов для определения aml_types
    enriched_aml_types = []
    all_alert_risks = []
    alerting = _step_output(raw, "alerting")
    alert_list = alerting.get("alerts", [])
    for alert_item in alert_list:
        if not isinstance(alert_item, dict):
            continue
        alert_id = alert_item.get("identifier")
        if not alert_id:
            continue
        try:
            alert_risks_data = await comply_advantage_client.get_alert_risks(alert_id)
            for risk in alert_risks_data.get("risks", []):
                ri = risk.get("detail", {}).get("profile", {}).get("risk_indicators", {})
                enriched_aml_types.extend(ri.get("aml_types", []))
            all_alert_risks.append(alert_risks_data)
        except Exception as e:
            logger.warning(f"Не удалось получить детали рисков для alert {alert_id}: {e}")
    if all_alert_risks:
        raw["_enriched_alert_risks"] = all_alert_risks

    parsed = _parse_ca_response(raw)

    # Переопределить risk_level на основе реальных aml_types
    if enriched_aml_types:
        parsed["risk_level"] = determine_risk_from_aml_types(enriched_aml_types)

    customer = AmlCustomer(
        client_id=client_id,
        customer_identifier=parsed["customer_identifier"],
        external_identifier=screen_kwargs.get("external_id"),
        name=name,
        type=customer_type,
        risk_level=parsed["risk_level"],
        monitored=False,
        screening_result=parsed["screening_result"],
        raw_response=raw or None,
        created_at=datetime.utcnow(),
    )
    db.add(customer)
    await db.flush()

    screening = AmlScreening(
        aml_customer_id=customer.id,
        screening_type=AmlScreeningType.INITIAL.value,
        match_count=len(_extract_alerts(raw)),
        status=parsed["screening_result"],
        raw_response=raw or None,
        created_by=created_by,
        created_at=datetime.utcnow(),
    )
    db.add(screening)

    for alert_data in _extract_alerts(raw):
        alert = AmlAlert(
            aml_customer_id=customer.id,
            external_alert_id=alert_data["external_alert_id"],
            title=alert_data["title"],
            description=alert_data["description"],
            match_type=alert_data["match_type"],
            status=AmlAlertStatus.PENDING.value,
            created_at=datetime.utcnow(),
        )
        db.add(alert)

    return customer


async def auto_screen_on_kyc_approval(
    client_id: str,
    db: AsyncSession,
    triggered_by: Optional[str] = None,
) -> None:
    """
    Авто-скрининг при одобрении KYC.
    Скринит: 1) компанию, 2) директора, 3) всех UBO/акционеров.
    Если хотя бы один результат = high risk → ставит account_status=hold.
    """
    # 0. Проверить нет ли уже AML-записей для этого клиента (защита от дубликатов)
    existing = await db.execute(
        select(func.count()).select_from(AmlCustomer).where(AmlCustomer.client_id == client_id)
    )
    if (existing.scalar() or 0) > 0:
        logger.info(f"AML auto-screen: клиент {client_id} уже скринился, пропускаем")
        return

    # 1. Загрузить клиента
    result = await db.execute(select(Client).where(Client.client_id == client_id))
    client = result.scalar_one_or_none()
    if not client:
        logger.error(f"AML auto-screen: клиент {client_id} не найден")
        return

    # 2. Загрузить KYC профиль (для corporate данных)
    result = await db.execute(
        select(OnboardingKycProfile).where(OnboardingKycProfile.client_id == client_id)
    )
    profile = result.scalar_one_or_none()
    corporate = (profile.payload or {}).get("corporate", {}) if profile else {}

    # 3. Загрузить UBO
    ubos = []
    if profile:
        result = await db.execute(
            select(OnboardingKycUbo).where(OnboardingKycUbo.profile_id == profile.profile_id)
        )
        ubos = result.scalars().all()

    screened_customers: list[AmlCustomer] = []
    country = (
        corporate.get("incorporation_country")
        or client.client_reg_country
        or None
    )

    # 4. Скрининг компании
    if client.client_name:
        ext_id = f"{client_id}-company"
        cust = await _screen_and_save(
            db=db,
            client_id=client_id,
            name=client.client_name,
            customer_type=AmlCustomerType.COMPANY.value,
            screen_fn=comply_advantage_client.screen_company,
            screen_kwargs={
                "external_id": ext_id,
                "legal_name": client.client_name,
                "registration_number": client.client_reg_number,
                "country": country.upper() if country else None,
            },
            created_by=triggered_by,
        )
        screened_customers.append(cust)

    # 5. Скрининг директора
    if client.client_director:
        ext_id = f"{client_id}-director"
        cust = await _screen_and_save(
            db=db,
            client_id=client_id,
            name=client.client_director,
            customer_type=AmlCustomerType.PERSON.value,
            screen_fn=comply_advantage_client.screen_person,
            screen_kwargs={
                "external_id": ext_id,
                "full_name": client.client_director,
            },
            created_by=triggered_by,
        )
        screened_customers.append(cust)

    # 6. Скрининг каждого UBO
    for ubo in ubos:
        if not ubo.ubo_name:
            continue
        ext_id = f"{client_id}-ubo-{ubo.id}"
        nationality = [ubo.nationality.upper()] if ubo.nationality else None
        cust = await _screen_and_save(
            db=db,
            client_id=client_id,
            name=ubo.ubo_name,
            customer_type=AmlCustomerType.PERSON.value,
            screen_fn=comply_advantage_client.screen_person,
            screen_kwargs={
                "external_id": ext_id,
                "full_name": ubo.ubo_name,
                "nationality": nationality,
            },
            created_by=triggered_by,
        )
        screened_customers.append(cust)

    # 7. Проверить risk: если хотя бы один high → hold account
    has_high_risk = any(c.risk_level == AmlRiskLevel.HIGH.value for c in screened_customers)
    if has_high_risk:
        client.account_status = "hold"
        client.account_hold_reason = "AML screening: high risk detected"
        logger.warning(f"AML auto-screen: клиент {client_id} получил hold — обнаружен high risk")

    await db.flush()
    logger.info(
        f"AML auto-screen завершён для {client_id}: "
        f"{len(screened_customers)} сущностей просканировано, "
        f"high_risk={'yes' if has_high_risk else 'no'}"
    )
