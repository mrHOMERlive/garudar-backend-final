"""
Авто-скрининг AML на двух событиях KYC-флоу:

  • KYC submit  → `pre_screen_kyc_on_submit` — БЕСПЛАТНЫЙ локальный матч против
    таблицы entries (DTTOT/DPPSPM/UN-AQ). Запускается ДО staff-approve, чтобы
    сотрудник видел санкционные хиты до того как тратить квоту ComplyAdvantage.
    UI-only: account_status НЕ меняется, KYC статус остаётся `submitted`.

  • KYC approve → `auto_screen_on_kyc_approval` — полный ComplyAdvantage-флоу
    (компания + директор + UBO) + повторный локальный матч (на случай если за
    период между submit и approve PPATK обновили списки). Если результат high
    risk — ставит account_status='hold'. Перед запуском чистит pre-screen-записи
    (lightweight AmlCustomer без customer_identifier) чтобы они не висели как
    дубли в AML UI.
"""
import json
import logging
from datetime import datetime
from typing import Optional

from sqlalchemy import select, func, delete as sa_delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Client, OnboardingKycProfile, OnboardingKycUbo,
    AmlCustomer, AmlScreening, AmlAlert,
    AuditLog,
)
from app.enums import AmlCustomerType, AmlRiskLevel, AmlAlertStatus, AmlScreeningType
from app.services.comply_advantage import comply_advantage_client
from app.services.local_sanctions_screening import (
    screen_name_against_local,
    severity_from_source,
    alert_external_id_for_entry,
)

logger = logging.getLogger("garudar_api")


# Маркер lightweight-AmlCustomer, созданного pre-screen-флоу. Используется как
# двойная защита (вместе с customer_identifier IS NULL) при cleanup, чтобы
# ни при каких обстоятельствах не удалить CA-данные.
PRESCREEN_MARKER = "PRESCREEN_ONLY"


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


async def run_local_prescreen_for_customer(
    db: AsyncSession,
    customer: AmlCustomer,
    name: str,
    customer_type: str,
    screening: Optional[AmlScreening] = None,
    seen_entries: Optional[set[int]] = None,
) -> bool:
    """
    Локальный PPATK-матч для уже созданного `AmlCustomer`.

    Создаёт по одному `AmlAlert` на каждый уникальный entry_id (set-based
    dedup через `seen_entries`, если передан — необходимо для pre-screen где
    одно entry может матчить и company, и подписанта, и UBO).

    Если матч high-severity — апгрейдит `customer.risk_level → HIGH`.
    Если передан `screening` — увеличивает `screening.match_count`.

    Returns: True если найден хотя бы один high-severity match.
    """
    local_entry_type = (
        "Individual" if customer_type == AmlCustomerType.PERSON.value else "Entity"
    )
    try:
        local_matches = await screen_name_against_local(
            db=db, name=name, entry_type=local_entry_type
        )
    except Exception as e:
        # Локальный скрининг не должен ломать вызывающий флоу (CA или submit-handler).
        # При деплое миграции pg_trgm этого не должно происходить; если случилось —
        # нужен фикс на стороне БД/миграций.
        logger.warning(
            f"Локальный PPATK-скрининг упал для '{name}' (customer {customer.id}): {e}"
        )
        return False

    local_high_risk = False
    seen = seen_entries if seen_entries is not None else set()
    added_count = 0

    for m in local_matches:
        if m.entry_id in seen:
            continue
        seen.add(m.entry_id)
        added_count += 1
        db.add(AmlAlert(
            aml_customer_id=customer.id,
            external_alert_id=alert_external_id_for_entry(m.entry_id),
            title=f"PPATK match: {m.source_list}",
            description=(
                f"Local sanctions list match. Source: {m.source_list}. "
                f"Matched name: '{m.matched_name}' "
                f"(similarity {m.similarity:.2f}). Entry ID: {m.entry_id}."
            ),
            match_type="ppatk_local",
            match_details={
                "source_list": m.source_list,
                "entry_id": m.entry_id,
                "matched_name": m.matched_name,
                "full_name": m.full_name,
                "similarity": m.similarity,
                "entry_type": m.entry_type,
            },
            status=AmlAlertStatus.PENDING.value,
            created_at=datetime.utcnow(),
        ))
        if severity_from_source(m.source_list) == "high":
            local_high_risk = True

    if local_high_risk and customer.risk_level != AmlRiskLevel.HIGH.value:
        customer.risk_level = AmlRiskLevel.HIGH.value
    if screening is not None and added_count:
        screening.match_count = (screening.match_count or 0) + added_count

    return local_high_risk


async def _delete_prescreen_records(db: AsyncSession, client_id: str) -> int:
    """
    Удалить все pre-screen-записи (lightweight AmlCustomer без CA-идентификатора).

    Двойная защита: customer_identifier IS NULL AND screening_result='PRESCREEN_ONLY'.
    Так не убьём CA-данные даже если в БД случайно есть customer без customer_identifier
    (например, аварийная запись из старого error-handler).

    Удаляет связанные alerts/screenings явно (cascade на ORM-relationship'е работает
    только при ORM-load, не при bulk delete-statement). Возвращает число удалённых
    AmlCustomer.
    """
    prescreen_ids = (await db.execute(
        select(AmlCustomer.id).where(
            AmlCustomer.client_id == client_id,
            AmlCustomer.customer_identifier.is_(None),
            AmlCustomer.screening_result == PRESCREEN_MARKER,
        )
    )).scalars().all()

    if not prescreen_ids:
        return 0

    await db.execute(sa_delete(AmlAlert).where(AmlAlert.aml_customer_id.in_(prescreen_ids)))
    await db.execute(sa_delete(AmlScreening).where(AmlScreening.aml_customer_id.in_(prescreen_ids)))
    await db.execute(sa_delete(AmlCustomer).where(AmlCustomer.id.in_(prescreen_ids)))
    return len(prescreen_ids)


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

    # Локальный PPATK-матч (свежие данные, на случай если между submit и approve
    # PPATK обновил списки). Логика вынесена в общую функцию `run_local_prescreen_for_customer`
    # — она же переиспользуется на KYC submit через `pre_screen_kyc_on_submit`.
    # Здесь `seen_entries=None` (без dedup между customers) — каждый AmlCustomer
    # независим, может матчить одно и то же entry как разные роли.
    await run_local_prescreen_for_customer(
        db=db,
        customer=customer,
        name=name,
        customer_type=customer_type,
        screening=screening,
    )

    return customer


async def pre_screen_kyc_on_submit(
    client_id: str,
    db: AsyncSession,
    triggered_by: Optional[str] = None,
) -> dict:
    """
    Бесплатный локальный PPATK pre-screen на KYC submit.

    Запускается ДО approve, СИНХРОННО в submit-handler'е. CA не вызывается
    (платно). pg_trgm-матч на 5-10 именах против ~50k entries < 1 секунды.

    Idempotent: при повторном submit (после needs_fix → правка → resubmit)
    старые pre-screen-записи удаляются ПОЛНОСТЬЮ перед запуском нового.
    Двойная защита `customer_identifier IS NULL AND screening_result='PRESCREEN_ONLY'`
    гарантирует что CA-данные не пострадают.

    Скринит:
      • company_name из payload.corporate (как Entity)
      • authorized_person_name из payload.declaration (как Individual)
      • каждый ubo_name из onboarding_kyc_ubos (как Individual)

    Set-based dedup: одно entry создаёт максимум 1 AmlAlert даже если матчит
    несколько names (например, company и UBO с похожими именами).

    UI-only поведение: account_status НЕ меняется, KYC status остаётся submitted.
    Staff увидит red_flag-бейдж в очереди и матчи в drawer.

    Returns: {"status": "completed|error|skipped", "match_count": int, "red_flag": bool}
    """
    now = datetime.utcnow()

    # 1. Загрузить профиль
    result = await db.execute(
        select(OnboardingKycProfile).where(OnboardingKycProfile.client_id == client_id)
    )
    profile = result.scalar_one_or_none()
    if not profile:
        logger.warning(f"PPATK pre-screen: профиль для {client_id} не найден, skip")
        return {"status": "skipped", "match_count": 0, "red_flag": False}

    # 2. Cleanup старых pre-screen записей (idempotent resubmit)
    deleted_count = await _delete_prescreen_records(db, client_id)
    if deleted_count:
        logger.info(f"PPATK pre-screen: удалено {deleted_count} старых pre-screen-AmlCustomer для {client_id}")

    # 3. Помечаем pending — UI увидит indicator пока идёт работа.
    # На больших объёмах данных стоит вынести в background task; пока inline (<1 сек).
    profile.aml_local_screening_status = "pending"
    profile.aml_local_screening_at = now
    profile.aml_local_match_count = 0
    profile.aml_local_red_flag = False
    await db.flush()

    # AuditLog STARTED — отделяет «pre-screen упал до завершения» от «ещё не запускали».
    db.add(AuditLog(
        entity="clients",
        entity_id=client_id,
        action="AML_LOCAL_PRESCREEN_STARTED",
        old_value=None,
        new_value=json.dumps({"profile_id": profile.profile_id}, ensure_ascii=False),
        created_by=triggered_by,
        created_at=now,
    ))

    # 4. Собрать names для скрининга
    payload = profile.payload or {}
    corporate = payload.get("corporate") or {}
    declaration = payload.get("declaration") or {}

    names_to_screen: list[tuple[str, str, str]] = []  # (role, name, customer_type)

    company_name = (corporate.get("company_name") or "").strip()
    if company_name:
        names_to_screen.append(("company", company_name, AmlCustomerType.COMPANY.value))

    signatory = (declaration.get("authorized_person_name") or "").strip()
    if signatory:
        names_to_screen.append(("signatory", signatory, AmlCustomerType.PERSON.value))

    ubos_result = await db.execute(
        select(OnboardingKycUbo).where(OnboardingKycUbo.profile_id == profile.profile_id)
    )
    ubos = ubos_result.scalars().all()
    for ubo in ubos:
        ubo_name = (ubo.ubo_name or "").strip()
        if ubo_name:
            names_to_screen.append((f"ubo-{ubo.id}", ubo_name, AmlCustomerType.PERSON.value))

    if not names_to_screen:
        # Нечего скринить — клиент сабмитил пустой профиль. Помечаем completed
        # с 0 матчей чтобы UI не висел в pending.
        profile.aml_local_screening_status = "completed"
        profile.aml_local_match_count = 0
        profile.aml_local_red_flag = False
        await db.flush()
        return {"status": "completed", "match_count": 0, "red_flag": False}

    # 5. Прогон скрининга. Set-based dedup по entry_id — одно entry не должно
    # давать N алертов на N разных AmlCustomer'ов в пределах одного запуска.
    seen_entries: set[int] = set()
    any_red_flag = False

    try:
        for role, name, ctype in names_to_screen:
            customer = AmlCustomer(
                client_id=client_id,
                customer_identifier=None,  # маркер: CA НЕ вызывали
                external_identifier=f"{client_id}-prescreen-{role}",
                name=name,
                type=ctype,
                risk_level=AmlRiskLevel.UNKNOWN.value,
                monitored=False,
                screening_result=PRESCREEN_MARKER,  # второй маркер для cleanup-фильтра
                raw_response=None,
                created_at=now,
            )
            db.add(customer)
            await db.flush()  # нужен чтобы получить customer.id для AmlScreening/AmlAlert FK

            screening_record = AmlScreening(
                aml_customer_id=customer.id,
                screening_type=AmlScreeningType.LOCAL_PRESCREEN.value,
                match_count=0,
                status="LOCAL_PRESCREEN",
                raw_response=None,
                created_by=triggered_by,
                created_at=now,
            )
            db.add(screening_record)

            red_flag = await run_local_prescreen_for_customer(
                db=db,
                customer=customer,
                name=name,
                customer_type=ctype,
                screening=screening_record,
                seen_entries=seen_entries,
            )
            if red_flag:
                any_red_flag = True
    except Exception as e:
        logger.exception(f"PPATK pre-screen упал для {client_id}: {e}")
        profile.aml_local_screening_status = "error"
        profile.aml_local_screening_at = now
        profile.aml_local_match_count = len(seen_entries)
        profile.aml_local_red_flag = any_red_flag
        await db.flush()
        return {"status": "error", "match_count": len(seen_entries), "red_flag": any_red_flag}

    # 6. Финальный статус профиля
    total_matches = len(seen_entries)
    profile.aml_local_screening_status = "completed"
    profile.aml_local_screening_at = now
    profile.aml_local_match_count = total_matches
    profile.aml_local_red_flag = any_red_flag

    # 7. AuditLog COMPLETED
    db.add(AuditLog(
        entity="clients",
        entity_id=client_id,
        action="AML_LOCAL_PRESCREEN_COMPLETED",
        old_value=None,
        new_value=json.dumps({
            "match_count": total_matches,
            "red_flag": any_red_flag,
            "names_screened": len(names_to_screen),
        }, ensure_ascii=False),
        created_by=triggered_by,
        created_at=datetime.utcnow(),
    ))

    await db.flush()

    logger.info(
        f"PPATK pre-screen завершён для {client_id}: "
        f"{len(names_to_screen)} имён, {total_matches} матчей, red_flag={any_red_flag}"
    )

    return {"status": "completed", "match_count": total_matches, "red_flag": any_red_flag}


async def auto_screen_on_kyc_approval(
    client_id: str,
    db: AsyncSession,
    triggered_by: Optional[str] = None,
) -> None:
    """
    Полный авто-скрининг при одобрении KYC (ComplyAdvantage + локальный матч).

    Скринит: 1) компанию, 2) директора, 3) всех UBO/акционеров.
    Если хотя бы один результат = high risk → ставит account_status=hold.

    Перед запуском чистит pre-screen-записи (lightweight AmlCustomer от
    `pre_screen_kyc_on_submit`) чтобы они не висели как дубли в AML UI.
    """
    # 0.1. Загрузить KYC профиль (нужен и для cleanup, и для corporate-данных ниже).
    profile = await db.scalar(
        select(OnboardingKycProfile).where(OnboardingKycProfile.client_id == client_id)
    )

    # 0.2. Cleanup pre-screen-записей. Делаем ДО guard'а от повторного запуска,
    # чтобы любой повторный approve гарантированно приводил state в порядок —
    # даже если CA-скрининг уже был раньше, но pre-screen-records успели накопиться
    # (например, после ручного rescreen). Idempotent: cleanup сбрасывает счётчики
    # на профиле в тот же момент когда удаляет AmlCustomer/AmlAlert, чтобы
    # source-of-truth для queue-бейджа совпадал с реальным состоянием таблиц.
    deleted = await _delete_prescreen_records(db, client_id)
    if deleted:
        logger.info(f"AML auto-screen: удалено {deleted} pre-screen-записей перед CA-скринингом")
        if profile is not None:
            profile.aml_local_red_flag = False
            profile.aml_local_match_count = 0

    # 0.3. Защита от повторного запуска CA. Считаем дубликатом ТОЛЬКО CA-AmlCustomer'ы
    # (customer_identifier IS NOT NULL). Pre-screen lightweight-записи
    # (customer_identifier IS NULL) НЕ блокируют CA-скрининг — иначе после
    # pre-screen на submit CA никогда бы не запустился.
    existing = await db.execute(
        select(func.count()).select_from(AmlCustomer).where(
            AmlCustomer.client_id == client_id,
            AmlCustomer.customer_identifier.is_not(None),
        )
    )
    if (existing.scalar() or 0) > 0:
        logger.info(f"AML auto-screen: клиент {client_id} уже скринился CA, пропускаем")
        await db.flush()  # сохраняем cleanup-эффект (счётчики профиля), даже если CA skip
        return

    # 1. Загрузить клиента
    result = await db.execute(select(Client).where(Client.client_id == client_id))
    client = result.scalar_one_or_none()
    if not client:
        logger.error(f"AML auto-screen: клиент {client_id} не найден")
        return

    # 2. corporate-данные из уже загруженного профиля
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
