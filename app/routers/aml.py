"""
AML (Anti-Money Laundering) — роутер для интеграции с ComplyAdvantage
"""
import asyncio
import logging
import uuid
from datetime import datetime
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_db
from app.deps import require_staff_or_admin
from app.models import (
    User, Role, AmlCustomer, AmlScreening, AmlAlert, AmlCase,
    AmlCaseComment, AmlRiskOverride,
)
from app.enums import (
    AmlCustomerType, AmlRiskLevel, AmlAlertStatus, AmlCaseStatus, AmlScreeningType,
)
from app.schemas import (
    ScreenPersonRequest, ScreenCompanyRequest,
    AmlCustomerDto, AmlAlertDto, AmlAlertDetailsDto, AmlCaseDto, AmlCaseCommentDto,
    AmlScreeningDto, AmlRiskScoreDto, AmlOverrideRiskRequest,
    AmlCaseCommentRequest, AmlUpdateCaseRequest, AmlMonitoringRequest,
    AmlSummaryDto,
    AmlCustomerAuditLogDto, AmlAuditLogsPageDto, AmlScreeningReportDto,
)
from app.services.comply_advantage import comply_advantage_client
from app.services.aml_auto_screening import determine_risk_from_aml_types
from app.s3_client import s3_client

logger = logging.getLogger("garudar_api")

router = APIRouter(prefix="/api/v1/aml", tags=["AML"])


# ── Helpers ──────────────────────────────────────────────────────────

def _step_output(raw: dict, step_name: str) -> dict:
    """Извлечь step_output из ответа workflow create-and-screen"""
    return raw.get("step_details", {}).get(step_name, {}).get("step_output", {})


def _parse_ca_response(raw: dict, customer_type: str) -> dict:
    """Извлечь ключевые поля из ответа ComplyAdvantage create-and-screen workflow"""
    # customer_identifier из step_details.customer-creation.step_output
    creation = _step_output(raw, "customer-creation")
    customer_id = creation.get("customer_identifier")

    # risk level из step_details.initial-risk-scoring.step_output
    risk = _step_output(raw, "initial-risk-scoring")
    overall_level = (risk.get("overall_level") or "UNKNOWN").upper()
    # Маппинг: SKIPPED→unknown, LOW-RISK→low, MEDIUM-RISK→medium, HIGH-RISK→high, PROHIBITED→high
    level_map = {"LOW-RISK": "low", "MEDIUM-RISK": "medium", "HIGH-RISK": "high", "PROHIBITED": "high"}
    risk_level = level_map.get(overall_level, "unknown")

    # screening_result из step_details.customer-screening.step_output
    screening = _step_output(raw, "customer-screening")
    screening_result = screening.get("screening_result")  # NO_PROFILES или HAS_PROFILES
    aml_types = screening.get("aml_types", [])

    # Fallback если Risk Model не настроена (SKIPPED) — только при реальном ответе API
    if risk_level == "unknown" and screening_result is not None:
        if screening_result == "HAS_PROFILES":
            risk_level = "medium"
        elif screening_result == "NO_PROFILES":
            risk_level = "low"

    # case_identifier из step_details.case-creation.step_output
    case_creation = _step_output(raw, "case-creation")
    case_identifier = case_creation.get("case_identifier")

    # workflow_instance_identifier для fallback-опроса через GET /v2/workflows/{id}
    workflow_instance_identifier = raw.get("workflow_instance_identifier")

    return {
        "customer_identifier": str(customer_id) if customer_id else None,
        "risk_level": risk_level,
        "screening_result": screening_result,
        "aml_types": aml_types,
        "case_identifier": str(case_identifier) if case_identifier else None,
        "workflow_instance_identifier": str(workflow_instance_identifier) if workflow_instance_identifier else None,
    }


def _extract_alerts_from_response(raw: dict) -> list[dict]:
    """Извлечь алерты из ответа workflow create-and-screen"""
    alerts = []
    # Алерты из step_details.alerting.step_output.alerts
    alerting = _step_output(raw, "alerting")
    alert_list = alerting.get("alerts", [])
    if isinstance(alert_list, list):
        for a in alert_list:
            alert_id = a.get("identifier") or a.get("id") or ""
            alerts.append({
                "external_alert_id": str(alert_id),
                "title": a.get("title") or "Screening Match",
                "description": a.get("description"),
                "match_type": a.get("match_type") or "screening",
            })

    # Если алерты есть в screening result (aml_types), но нет alert объектов — создаём из aml_types
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


async def _save_aml_case(customer: AmlCustomer, parsed: dict, customer_name: str, db) -> None:
    """Создать AmlCase в БД.

    Стратегия:
    1. Пробуем взять case_identifier из sync-ответа workflow (case-creation шаг).
    2. Если не получили (last_sync_step=ALERTING останавливает до case-creation) —
       делаем отдельный запрос GET /v2/cases?customer_id=… к CA API.
    3. Если кейс найден — сохраняем в БД (идемпотентно).
    """
    case_identifier = parsed.get("case_identifier")

    # Fallback: case-creation шаг мог быть ещё IN-PROGRESS при sync-ответе
    # (last_sync_step=ALERTING завершается ДО case-creation).
    # Опрашиваем GET /v2/workflows/{id} — точнее чем GET /v2/cases?customer_id=...
    if not case_identifier and parsed.get("workflow_instance_identifier") and parsed.get("screening_result") == "HAS_PROFILES":
        wf_id = parsed["workflow_instance_identifier"]
        for attempt in range(5):
            if attempt > 0:
                await asyncio.sleep(2)
            try:
                wf = await comply_advantage_client.get_workflow(wf_id)
                cc_step = wf.get("step_details", {}).get("case-creation", {})
                cc_status = cc_step.get("status", "")
                cc_output = cc_step.get("step_output", {})
                case_identifier = cc_output.get("case_identifier")
                if case_identifier:
                    case_identifier = str(case_identifier)
                    logger.info(f"AML: получен case_identifier={case_identifier} из workflow (попытка {attempt + 1})")
                    break
                elif cc_status in ("SKIPPED", "ERRORED"):
                    logger.info(f"AML: case-creation status={cc_status} — кейс не будет создан")
                    return
                else:
                    logger.info(f"AML: case-creation status={cc_status or 'IN-PROGRESS'} (попытка {attempt + 1}/5), wf={wf_id}")
            except Exception as e:
                logger.warning(f"AML: ошибка запроса workflow (попытка {attempt + 1}/5): {e}")

    if not case_identifier:
        logger.warning(f"AML: не удалось получить case_identifier после 5 попыток, wf={parsed.get('workflow_instance_identifier')}")
        return

    # Идемпотентность
    from sqlalchemy import select as sa_select
    existing = await db.execute(sa_select(AmlCase).where(AmlCase.external_case_id == case_identifier))
    if existing.scalar_one_or_none():
        logger.info(f"AML: кейс {case_identifier} уже существует, пропускаем")
        return

    aml_case = AmlCase(
        aml_customer_id=customer.id,
        external_case_id=case_identifier,
        title=f"Initial Screening: {customer_name}",
        description=(
            f"Automatically created during screening. "
            f"Result: {parsed['screening_result']}. "
            f"Risk: {parsed['risk_level']}."
        ),
        status=AmlCaseStatus.OPEN.value,
        risk_level=parsed["risk_level"],
        aml_types=parsed.get("aml_types") or [],
        created_at=datetime.utcnow(),
    )
    db.add(aml_case)


def _build_match_details(raw: dict) -> list[dict]:
    """Извлечь match_details по каждому алерту из _enriched_alert_risks.
    Возвращает список dict — по одному на каждый alert_identifier (в том же порядке).

    Формат (backward-compatible: старые ключи aml_types/entities сохранены):
      {
        "aml_types": ["SANCTION", "PEP_CLASS_1", ...],
        "entities": [{"name": "...", "sources": [...]}],
        "profile": {
            "matching_name": str,
            "aliases": [{"name": str, "type": str}],
            "date_of_birth": str | None,
            "nationality": [str] | None,
            "person_details": dict | None,
            "company_details": dict | None,
        },
        "sanctions": [{"name", "regulator", "date_added", "status", "description"}],
        "pep": [{"position", "country", "from", "to"}],
        "adverse_media": [{"title", "url", "published", "snippet"}],
        "sources": [{"name", "url"}],
      }

    Всё, кроме aml_types/entities, — опциональные ключи; если данных нет, ключ отсутствует или []. Фронтенд
    должен рендерить defensive-стилем: optional chaining + fallback "No data".
    """
    enriched = raw.get("_enriched_alert_risks", [])
    result = []
    for alert_risks in enriched:
        aml_types: list[str] = []
        entities: list[dict] = []
        # Агрегируем по одному алерту: один alert может нести несколько risks (разные profiles).
        profile_summary: Optional[dict] = None
        aliases: list[dict] = []
        sanctions: list[dict] = []
        pep: list[dict] = []
        adverse_media: list[dict] = []
        sources_seen: dict[str, dict] = {}  # dedupe по (name, url)

        for risk in alert_risks.get("risks", []):
            profile = risk.get("detail", {}).get("profile", {}) or {}
            # ── Имя matching/person/company ───────────────────────
            person = profile.get("person") or {}
            company = profile.get("company") or {}
            person_names = person.get("names") or []
            company_names = company.get("names") or []
            matching_name = profile.get("matching_name")
            primary_name = (
                (person_names[0].get("name") if person_names and isinstance(person_names[0], dict) else None)
                or (company_names[0].get("name") if company_names and isinstance(company_names[0], dict) else None)
                or matching_name
            )

            # ── Risk indicators ──────────────────────────────────
            ri = profile.get("risk_indicators") or {}
            raw_types = ri.get("aml_types") or []
            types = [t.upper().replace("-", "_") for t in raw_types if isinstance(t, str)]
            aml_types.extend(types)

            # ── Entity sources (старый формат — не ломаем) ───────
            entity_sources = [s.get("name") for s in (ri.get("sanctions") or []) if isinstance(s, dict) and s.get("name")]
            if primary_name or entity_sources:
                entities.append({"name": primary_name, "sources": entity_sources})

            # ── Profile-summary (первый непустой risk определяет) ──
            if profile_summary is None:
                profile_summary = {
                    "matching_name": matching_name,
                    "date_of_birth": person.get("date_of_birth") or person.get("dob"),
                    "nationality": person.get("nationality") or person.get("nationalities"),
                    "person_details": person or None,
                    "company_details": company or None,
                }

            # ── Aliases (все names кроме первого с type != "primary") ──
            for n in person_names[1:] + company_names[1:]:
                if isinstance(n, dict) and n.get("name"):
                    aliases.append({"name": n.get("name"), "type": n.get("type") or "aka"})

            # ── Sanctions details ────────────────────────────────
            # CA возвращает sanctions с полями name, country_codes, listing_started_utc,
            # listing_ended_utc, url, related_urls, fields[]. "Регулятор" обычно country_code
            # (ISO2), "дата" = listing_started_utc, "активно" = listing_ended_utc is None,
            # "описание" берём из fields[] по tag/name ("Designation Act"/"Reason" и т.п.).
            def _field_by(ss, tag_or_name):
                for f in ss.get("fields") or []:
                    if not isinstance(f, dict):
                        continue
                    if f.get("tag") == tag_or_name or f.get("name") == tag_or_name:
                        return f.get("value")
                return None

            for s in ri.get("sanctions") or []:
                if not isinstance(s, dict):
                    continue
                # status: active если listing_ended_utc пустой
                is_current = s.get("is_current")
                ended = s.get("listing_ended_utc")
                if s.get("status"):
                    s_status = s.get("status")
                elif is_current is True or (is_current is None and not ended):
                    s_status = "active"
                else:
                    s_status = "inactive"
                country_codes = s.get("country_codes") or []
                regulator = (
                    s.get("regulator")
                    or s.get("regulatory_body")
                    or _field_by(s, "Designation Act")
                    or (country_codes[0] if country_codes else None)
                )
                description = (
                    s.get("description")
                    or s.get("reason")
                    or _field_by(s, "Reason")
                    or _field_by(s, "Designation Act")
                )
                sanctions.append({
                    "name": s.get("name"),
                    "regulator": regulator,
                    "date_added": s.get("date_added") or s.get("listed_at") or s.get("since") or s.get("listing_started_utc"),
                    "status": s_status,
                    "description": description,
                })
                src_name = s.get("name")
                if src_name and src_name not in sources_seen:
                    sources_seen[src_name] = {"name": src_name, "url": s.get("url") or s.get("source_url")}

            # ── PEP ───────────────────────────────────────────────
            # CA возвращает это в ключе "peps" (мн.ч.). Плюс на всякий случай — старые
            # ключи.
            for p in (ri.get("peps") or ri.get("pep") or []) + (ri.get("political_positions") or []):
                if not isinstance(p, dict):
                    continue
                pep.append({
                    "position": p.get("position") or p.get("title") or p.get("role") or p.get("name"),
                    "country": p.get("country") or p.get("country_name")
                               or (p.get("country_codes")[0] if p.get("country_codes") else None),
                    "from": p.get("from") or p.get("start_date") or p.get("since") or p.get("listing_started_utc"),
                    "to": p.get("to") or p.get("end_date") or p.get("until") or p.get("listing_ended_utc"),
                })

            # ── Adverse media ─────────────────────────────────────
            # CA возвращает это в ключе "media".
            for m in (ri.get("media") or ri.get("adverse_media") or []):
                if not isinstance(m, dict):
                    continue
                adverse_media.append({
                    "title": m.get("title") or m.get("headline"),
                    "url": m.get("url") or m.get("source_url"),
                    "published": m.get("date") or m.get("published") or m.get("published_at") or m.get("snippet_date"),
                    "snippet": m.get("snippet") or m.get("description") or m.get("summary"),
                })
                src_name = m.get("source_name") or m.get("source") or m.get("publisher") or m.get("snippet_source")
                src_url = m.get("url") or m.get("source_url")
                if src_name and src_name not in sources_seen:
                    sources_seen[src_name] = {"name": src_name, "url": src_url}

        result.append({
            "aml_types": list(dict.fromkeys(aml_types)),  # dedupe, preserve order
            "entities": entities,
            "profile": profile_summary,
            "aliases": aliases or None,
            "sanctions": sanctions or None,
            "pep": pep or None,
            "adverse_media": adverse_media or None,
            "sources": list(sources_seen.values()) or None,
        })
    return result


async def _enrich_from_alerts(raw: dict) -> list[str]:
    """Получить aml_types из alert risks API для точного определения risk_level.

    Побочный эффект: складывает обогащённые risks в raw["_enriched_alert_risks"].
    Каждый блок risks помечается "_alert_id": идентификатором исходного алерта,
    чтобы GET /aml/alerts/{id}/details мог найти нужный блок по external_alert_id.
    """
    enriched_aml_types = []
    alerting = _step_output(raw, "alerting")
    alert_list = alerting.get("alerts", [])
    all_alert_risks = []
    for alert_item in alert_list:
        if not isinstance(alert_item, dict):
            continue
        alert_id = alert_item.get("identifier")
        if not alert_id:
            continue
        try:
            alert_risks = await comply_advantage_client.get_alert_risks(alert_id)
            # Помечаем блок alert_id чтобы потом найти по external_alert_id в БД
            if isinstance(alert_risks, dict):
                alert_risks["_alert_id"] = str(alert_id)
            for risk in alert_risks.get("risks", []):
                ri = risk.get("detail", {}).get("profile", {}).get("risk_indicators", {})
                enriched_aml_types.extend(ri.get("aml_types", []))
            all_alert_risks.append(alert_risks)
        except Exception as e:
            logger.warning(f"Не удалось получить детали рисков для alert {alert_id}: {e}")
    if all_alert_risks:
        raw["_enriched_alert_risks"] = all_alert_risks
    return enriched_aml_types


# ── Screening ────────────────────────────────────────────────────────

@router.post("/screen/person", response_model=AmlCustomerDto)
async def screen_person(
    body: ScreenPersonRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_staff_or_admin),
):
    """Скрининг физического лица через ComplyAdvantage"""
    external_id = body.external_id or f"person-{uuid.uuid4().hex[:12]}"

    # Проверка дубликата по external_id
    if body.external_id:
        existing = await db.execute(
            select(AmlCustomer).where(AmlCustomer.external_identifier == body.external_id)
        )
        if existing.scalar_one_or_none():
            raise HTTPException(409, detail=f"Customer with external_id '{body.external_id}' already exists")

    # Проверка дубликата по имени (case insensitive)
    existing_by_name = await db.execute(
        select(AmlCustomer).where(
            func.lower(AmlCustomer.name) == body.name.strip().lower(),
            AmlCustomer.type == AmlCustomerType.PERSON.value,
        )
    )
    if existing_by_name.scalars().first():
        raise HTTPException(409, detail=f"Customer '{body.name}' already screened. Use Re-screen for re-check.")

    # Парсим имя
    parts = body.name.strip().split(maxsplit=1)
    first_name = parts[0] if parts else body.name
    last_name = parts[1] if len(parts) > 1 else None

    dob = None
    if body.date_of_birth:
        try:
            d = datetime.strptime(body.date_of_birth, "%Y-%m-%d")
            dob = {"day": d.day, "month": d.month, "year": d.year}
        except ValueError:
            pass

    nationality = [body.nationality.upper()] if body.nationality else None

    # Вызов ComplyAdvantage
    raw = {}
    try:
        raw = await comply_advantage_client.screen_person(
            external_id=external_id,
            first_name=first_name,
            last_name=last_name,
            full_name=body.name if not last_name else None,
            date_of_birth=dob,
            nationality=nationality,
        )
    except RuntimeError as e:
        logger.warning(f"ComplyAdvantage не настроен: {e}")
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 409:
            raise HTTPException(409, detail="Customer with this identifier already exists in ComplyAdvantage")
        logger.error(f"Ошибка ComplyAdvantage screen_person: {e}")
    except Exception as e:
        logger.error(f"Ошибка ComplyAdvantage screen_person: {e}")

    # Обогащение: получить aml_types из alert risks
    enriched_aml_types = await _enrich_from_alerts(raw)

    parsed = _parse_ca_response(raw, "person")
    if enriched_aml_types:
        parsed["risk_level"] = determine_risk_from_aml_types(enriched_aml_types)
        parsed["aml_types"] = list(dict.fromkeys(t.upper().replace("-", "_") for t in enriched_aml_types))

    # Сохраняем в БД
    customer = AmlCustomer(
        customer_identifier=parsed["customer_identifier"],
        external_identifier=external_id,
        name=body.name,
        type=AmlCustomerType.PERSON.value,
        risk_level=parsed["risk_level"],
        monitored=False,
        screening_result=parsed["screening_result"],
        raw_response=raw or None,
        created_at=datetime.utcnow(),
    )
    db.add(customer)
    await db.flush()

    # Сохраняем скрининг
    screening = AmlScreening(
        aml_customer_id=customer.id,
        screening_type=AmlScreeningType.INITIAL.value,
        match_count=len(_extract_alerts_from_response(raw)),
        status=parsed["screening_result"],
        raw_response=raw or None,
        created_by=current_user.user_id,
        created_at=datetime.utcnow(),
    )
    db.add(screening)

    # Создаём кейс (с fallback через CA API если sync не вернул case_identifier)
    await _save_aml_case(customer, parsed, body.name, db)

    # Сохраняем алерты
    alert_datas = _extract_alerts_from_response(raw)
    match_details_list = _build_match_details(raw)
    for i, alert_data in enumerate(alert_datas):
        alert = AmlAlert(
            aml_customer_id=customer.id,
            external_alert_id=alert_data["external_alert_id"],
            title=alert_data["title"],
            description=alert_data["description"],
            match_type=alert_data["match_type"],
            match_details=match_details_list[i] if i < len(match_details_list) else None,
            status=AmlAlertStatus.PENDING.value,
            created_at=datetime.utcnow(),
        )
        db.add(alert)

    await db.commit()
    await db.refresh(customer)
    return AmlCustomerDto.model_validate(customer)


@router.post("/screen/company", response_model=AmlCustomerDto)
async def screen_company(
    body: ScreenCompanyRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_staff_or_admin),
):
    """Скрининг юридического лица через ComplyAdvantage"""
    external_id = body.external_id or f"company-{uuid.uuid4().hex[:12]}"

    # Проверка дубликата по external_id
    if body.external_id:
        existing = await db.execute(
            select(AmlCustomer).where(AmlCustomer.external_identifier == body.external_id)
        )
        if existing.scalar_one_or_none():
            raise HTTPException(409, detail=f"Customer with external_id '{body.external_id}' already exists")

    # Проверка дубликата по имени (case insensitive)
    existing_by_name = await db.execute(
        select(AmlCustomer).where(
            func.lower(AmlCustomer.name) == body.name.strip().lower(),
            AmlCustomer.type == AmlCustomerType.COMPANY.value,
        )
    )
    if existing_by_name.scalars().first():
        raise HTTPException(409, detail=f"Company '{body.name}' already screened. Use Re-screen for re-check.")

    raw = {}
    try:
        raw = await comply_advantage_client.screen_company(
            external_id=external_id,
            legal_name=body.name,
            registration_number=body.registration_number,
            country=body.incorporation_country.upper() if body.incorporation_country else None,
        )
    except RuntimeError as e:
        logger.warning(f"ComplyAdvantage не настроен: {e}")
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 409:
            raise HTTPException(409, detail="Customer with this identifier already exists in ComplyAdvantage")
        logger.error(f"Ошибка ComplyAdvantage screen_company: {e}")
    except Exception as e:
        logger.error(f"Ошибка ComplyAdvantage screen_company: {e}")

    # Обогащение: получить aml_types из alert risks
    enriched_aml_types = await _enrich_from_alerts(raw)

    parsed = _parse_ca_response(raw, "company")
    if enriched_aml_types:
        parsed["risk_level"] = determine_risk_from_aml_types(enriched_aml_types)
        parsed["aml_types"] = list(dict.fromkeys(t.upper().replace("-", "_") for t in enriched_aml_types))

    customer = AmlCustomer(
        customer_identifier=parsed["customer_identifier"],
        external_identifier=external_id,
        name=body.name,
        type=AmlCustomerType.COMPANY.value,
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
        match_count=len(_extract_alerts_from_response(raw)),
        status=parsed["screening_result"],
        raw_response=raw or None,
        created_by=current_user.user_id,
        created_at=datetime.utcnow(),
    )
    db.add(screening)

    # Создаём кейс (с fallback через CA API если sync не вернул case_identifier)
    await _save_aml_case(customer, parsed, body.name, db)

    alert_datas = _extract_alerts_from_response(raw)
    match_details_list = _build_match_details(raw)
    for i, alert_data in enumerate(alert_datas):
        alert = AmlAlert(
            aml_customer_id=customer.id,
            external_alert_id=alert_data["external_alert_id"],
            title=alert_data["title"],
            description=alert_data["description"],
            match_type=alert_data["match_type"],
            match_details=match_details_list[i] if i < len(match_details_list) else None,
            status=AmlAlertStatus.PENDING.value,
            created_at=datetime.utcnow(),
        )
        db.add(alert)

    await db.commit()
    await db.refresh(customer)
    return AmlCustomerDto.model_validate(customer)


# ── Customers ────────────────────────────────────────────────────────

@router.get("/customers", response_model=list[AmlCustomerDto])
async def list_customers(
    search: Optional[str] = Query(None),
    type: Optional[str] = Query(None),
    risk_level: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_staff_or_admin),
):
    """Список AML-клиентов с фильтрами"""
    q = select(AmlCustomer).order_by(AmlCustomer.created_at.desc())
    if search:
        q = q.where(or_(
            AmlCustomer.name.ilike(f"%{search}%"),
            AmlCustomer.external_identifier.ilike(f"%{search}%"),
        ))
    if type:
        q = q.where(AmlCustomer.type == type)
    if risk_level:
        q = q.where(AmlCustomer.risk_level == risk_level)

    result = await db.execute(q.limit(200))
    return [AmlCustomerDto.model_validate(c) for c in result.scalars().all()]


@router.get("/customers/{customer_id}", response_model=AmlCustomerDto)
async def get_customer(
    customer_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_staff_or_admin),
):
    """Детали AML-клиента"""
    result = await db.execute(select(AmlCustomer).where(AmlCustomer.id == customer_id))
    customer = result.scalar_one_or_none()
    if not customer:
        raise HTTPException(status_code=404, detail="AML customer not found")
    return AmlCustomerDto.model_validate(customer)


@router.get("/customers/{customer_id}/cases", response_model=list[AmlCaseDto])
async def get_customer_cases(
    customer_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_staff_or_admin),
):
    """Кейсы клиента"""
    result = await db.execute(
        select(AmlCase).where(AmlCase.aml_customer_id == customer_id)
        .order_by(AmlCase.created_at.desc())
    )
    return [AmlCaseDto.model_validate(c) for c in result.scalars().all()]


@router.get("/customers/{customer_id}/alerts", response_model=list[AmlAlertDto])
async def get_customer_alerts(
    customer_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_staff_or_admin),
):
    """Алерты клиента"""
    result = await db.execute(
        select(AmlAlert).where(AmlAlert.aml_customer_id == customer_id)
        .order_by(AmlAlert.created_at.desc())
    )
    alerts = result.scalars().all()

    # Получаем имя клиента для UI
    cust_result = await db.execute(select(AmlCustomer.name).where(AmlCustomer.id == customer_id))
    cust_name = cust_result.scalar_one_or_none()

    dtos = []
    for a in alerts:
        dto = AmlAlertDto.model_validate(a)
        dto.customer_name = cust_name
        dtos.append(dto)
    return dtos


@router.get("/customers/{customer_id}/risk", response_model=AmlRiskScoreDto)
async def get_customer_risk(
    customer_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_staff_or_admin),
):
    """Risk score клиента"""
    result = await db.execute(select(AmlCustomer).where(AmlCustomer.id == customer_id))
    customer = result.scalar_one_or_none()
    if not customer:
        raise HTTPException(status_code=404, detail="AML customer not found")

    raw = customer.raw_response or {}
    risk_step = raw.get("step_details", {}).get("initial-risk-scoring", {}).get("step_output", {})
    overall_level = (risk_step.get("overall_level") or "").upper()
    # Не показываем score если Risk Model не настроена (SKIPPED)
    score = None if overall_level == "SKIPPED" else risk_step.get("overall_value")

    # Факторы из enriched alerts: уникальные aml_types по всем рискам
    enriched = raw.get("_enriched_alert_risks", [])
    aml_type_set: list[str] = []
    for alert_risks in enriched:
        for risk in alert_risks.get("risks", []):
            ri = risk.get("detail", {}).get("profile", {}).get("risk_indicators", {})
            for t in ri.get("aml_types", []):
                normalized = t.upper().replace("-", "_")
                if normalized not in aml_type_set:
                    aml_type_set.append(normalized)
    factors = [{"label": t} for t in aml_type_set] if aml_type_set else None

    # Risk score breakdown по категориям (P1): свежий запрос к CA если клиент
    # связан, с сохранением blob'а в БД. Graceful degradation — любая ошибка
    # CA даёт `breakdown=None`, основные поля остаются (endpoint не ломается
    # из-за внешней системы).
    breakdown: Optional[dict] = customer.risk_score_breakdown
    if customer.customer_identifier:
        try:
            fresh = await comply_advantage_client.get_customer_scores(customer.customer_identifier)
            breakdown = fresh
            customer.risk_score_breakdown = fresh
            await db.commit()
        except RuntimeError:
            # CA не настроен — используем кешированный blob (может быть None).
            pass
        except httpx.HTTPStatusError as e:
            logger.warning(
                "CA /scores HTTP %s for customer %s — falling back to cached breakdown",
                e.response.status_code, customer.customer_identifier,
            )
        except Exception as e:
            logger.warning("CA /scores unexpected error for customer %s: %s", customer.customer_identifier, e)

    return AmlRiskScoreDto(
        risk_level=customer.risk_level,
        score=score,
        factors=factors,
        last_updated=customer.updated_at or customer.created_at,
        breakdown=breakdown,
    )


@router.get("/customers/{customer_id}/screenings", response_model=list[AmlScreeningDto])
async def get_customer_screenings(
    customer_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_staff_or_admin),
):
    """История скринингов клиента"""
    result = await db.execute(
        select(AmlScreening).where(AmlScreening.aml_customer_id == customer_id)
        .order_by(AmlScreening.created_at.desc())
    )
    return [AmlScreeningDto.model_validate(s) for s in result.scalars().all()]


async def _do_rescreen(customer: AmlCustomer, db: AsyncSession, created_by: Optional[str]) -> AmlScreening:
    """Настоящий rescreen через CA `workflows/sync/rescreen` (DELTA).

    В отличие от старой реализации НЕ создаёт нового CA-клиента — использует
    существующий `customer_identifier`, получает только новые/изменившиеся
    hit'ы (DELTA), сохраняет continuity в audit trail у CA.

    Требует: `customer.customer_identifier` задан.
    """
    if not customer.customer_identifier:
        raise HTTPException(
            status_code=400,
            detail="Customer has no CA identifier — rescreen requires initial screening first",
        )

    idempotency_key = f"rescreen-{customer.id}-{int(datetime.utcnow().timestamp())}"
    raw: dict = {}
    try:
        raw = await comply_advantage_client.rescreen_customer(
            customer.customer_identifier,
            idempotency_key=idempotency_key,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 403:
            # Rescreen endpoint требует CA entitlement "monitor on demand",
            # которого у нашего аккаунта может не быть. Fallback:
            # create-and-screen с новым external_identifier — это создаёт
            # нового клиента в CA (непрерывности audit trail нет), но даёт
            # свежие hit'ы в нашей БД. Когда CA активирует entitlement —
            # этот branch перестанет срабатывать сам собой.
            logger.warning(
                "CA rescreen not available for customer %s, "
                "falling back to create-and-screen (entitlement missing)",
                customer.id,
            )
            ext_id = f"rescreen-{customer.id}-{int(datetime.utcnow().timestamp())}"
            try:
                if customer.type == AmlCustomerType.COMPANY.value:
                    raw = await comply_advantage_client.screen_company(
                        external_id=ext_id, legal_name=customer.name,
                    )
                else:
                    raw = await comply_advantage_client.screen_person(
                        external_id=ext_id, full_name=customer.name,
                    )
            except Exception as fb_e:
                logger.error("Fallback create-and-screen also failed: %s", fb_e)
                raise HTTPException(
                    status_code=502,
                    detail=f"ComplyAdvantage unavailable (both rescreen and fallback failed): {fb_e}",
                )
        else:
            logger.error("CA rescreen HTTP %s: %s", e.response.status_code, e.response.text[:300])
            raise HTTPException(
                status_code=502,
                detail=f"ComplyAdvantage rescreen error: HTTP {e.response.status_code}",
            )
    except Exception as e:
        logger.error("CA rescreen unexpected error: %s", e)
        raise HTTPException(status_code=502, detail=f"ComplyAdvantage unavailable: {e}")

    # Enrichment и парсинг аналогично первичному screen_person.
    enriched_aml_types = await _enrich_from_alerts(raw)
    parsed = _parse_ca_response(raw, customer.type)
    if enriched_aml_types:
        parsed["risk_level"] = determine_risk_from_aml_types(enriched_aml_types)
        parsed["aml_types"] = list(dict.fromkeys(t.upper().replace("-", "_") for t in enriched_aml_types))

    # Обновляем customer с сохранением customer_identifier (он тот же).
    customer.risk_level = parsed["risk_level"]
    customer.screening_result = parsed["screening_result"]
    customer.raw_response = raw or None
    customer.updated_at = datetime.utcnow()
    customer.last_rescreen_at = datetime.utcnow()

    screening = AmlScreening(
        aml_customer_id=customer.id,
        screening_type=AmlScreeningType.RESCREEN.value,
        match_count=len(_extract_alerts_from_response(raw)),
        status=parsed.get("screening_result"),
        raw_response=raw or None,
        created_by=created_by,
        created_at=datetime.utcnow(),
    )
    db.add(screening)

    alert_datas = _extract_alerts_from_response(raw)
    match_details_list = _build_match_details(raw)
    for i, alert_data in enumerate(alert_datas):
        alert = AmlAlert(
            aml_customer_id=customer.id,
            external_alert_id=alert_data["external_alert_id"],
            title=alert_data["title"],
            description=alert_data["description"],
            match_type=alert_data["match_type"],
            match_details=match_details_list[i] if i < len(match_details_list) else None,
            status=AmlAlertStatus.PENDING.value,
            created_at=datetime.utcnow(),
        )
        db.add(alert)

    await _save_aml_case(customer, parsed, customer.name, db)
    await db.commit()
    await db.refresh(screening)
    return screening


@router.post("/customers/{customer_id}/rescreen", response_model=AmlScreeningDto)
async def rescreen_customer(
    customer_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_staff_or_admin),
):
    """Повторный скрининг клиента через CA /workflows/sync/rescreen (DELTA).

    В отличие от старой реализации — НЕ создаёт нового CA-клиента. Использует
    существующий `customer.customer_identifier`, получает только новые/изменившиеся
    hit'ы и создаёт alerts только на них.
    """
    result = await db.execute(select(AmlCustomer).where(AmlCustomer.id == customer_id))
    customer = result.scalar_one_or_none()
    if not customer:
        raise HTTPException(status_code=404, detail="AML customer not found")

    screening = await _do_rescreen(customer, db, created_by=current_user.user_id)
    return AmlScreeningDto.model_validate(screening)


@router.patch("/customers/{customer_id}/monitoring")
async def toggle_monitoring(
    customer_id: int,
    body: AmlMonitoringRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_staff_or_admin),
):
    """Включить/выключить мониторинг"""
    result = await db.execute(select(AmlCustomer).where(AmlCustomer.id == customer_id))
    customer = result.scalar_one_or_none()
    if not customer:
        raise HTTPException(status_code=404, detail="AML customer not found")

    # Вызов ComplyAdvantage
    if customer.customer_identifier:
        try:
            await comply_advantage_client.update_monitoring(customer.customer_identifier, body.enabled)
        except Exception as e:
            logger.error(f"Ошибка toggle_monitoring: {e}")

    customer.monitored = body.enabled
    customer.updated_at = datetime.utcnow()
    await db.commit()
    return {"success": True, "monitored": customer.monitored}


@router.post("/customers/{customer_id}/risk/override")
async def override_risk(
    customer_id: int,
    body: AmlOverrideRiskRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_staff_or_admin),
):
    """Ручная корректировка уровня риска"""
    result = await db.execute(select(AmlCustomer).where(AmlCustomer.id == customer_id))
    customer = result.scalar_one_or_none()
    if not customer:
        raise HTTPException(status_code=404, detail="AML customer not found")

    override = AmlRiskOverride(
        aml_customer_id=customer.id,
        old_risk_level=customer.risk_level,
        new_risk_level=body.risk_level,
        reason=body.reason,
        created_by=current_user.user_id,
        created_at=datetime.utcnow(),
    )
    db.add(override)

    customer.risk_level = body.risk_level
    customer.updated_at = datetime.utcnow()
    await db.commit()
    return {"success": True}


@router.delete("/customers/{customer_id}", status_code=204)
async def delete_customer(
    customer_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_staff_or_admin),
):
    """Удалить AML-клиента со всеми алертами, кейсами и скринингами"""
    result = await db.execute(select(AmlCustomer).where(AmlCustomer.id == customer_id))
    customer = result.scalar_one_or_none()
    if not customer:
        raise HTTPException(status_code=404, detail="AML customer not found")
    await db.delete(customer)
    await db.commit()


# ── Alerts ───────────────────────────────────────────────────────────

@router.get("/alerts", response_model=list[AmlAlertDto])
async def list_alerts(
    alert_status: Optional[str] = Query(None, alias="status"),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_staff_or_admin),
):
    """Глобальный список алертов"""
    q = select(AmlAlert).order_by(AmlAlert.created_at.desc())
    if alert_status and alert_status != "all":
        q = q.where(AmlAlert.status == alert_status)

    result = await db.execute(q.limit(200))
    alerts = result.scalars().all()

    # Подгружаем имена клиентов
    customer_ids = list({a.aml_customer_id for a in alerts})
    cust_names = {}
    if customer_ids:
        cust_result = await db.execute(
            select(AmlCustomer.id, AmlCustomer.name).where(AmlCustomer.id.in_(customer_ids))
        )
        cust_names = {row.id: row.name for row in cust_result.all()}

    dtos = []
    for a in alerts:
        dto = AmlAlertDto.model_validate(a)
        dto.customer_name = cust_names.get(a.aml_customer_id)
        dtos.append(dto)
    return dtos


@router.get("/alerts/{alert_id}/details", response_model=AmlAlertDetailsDto)
async def get_alert_details(
    alert_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_staff_or_admin),
):
    """Полные детали одного алерта: расширенный match_details + raw_risks от ComplyAdvantage.

    Для нового скрининга match_details содержит profile/sanctions/pep/adverse_media.
    Для старых записей (до этого изменения) присутствуют только aml_types/entities — остальные
    поля отсутствуют. Фронтенд должен рендерить defensive-стилем ("No data" fallback).
    """
    result = await db.execute(select(AmlAlert).where(AmlAlert.id == alert_id))
    alert = result.scalar_one_or_none()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")

    # Находим блок _enriched_alert_risks с этим external_alert_id в raw_response клиента.
    raw_risks = None
    if alert.external_alert_id:
        cust_result = await db.execute(
            select(AmlCustomer).where(AmlCustomer.id == alert.aml_customer_id)
        )
        customer = cust_result.scalar_one_or_none()
        if customer and customer.raw_response:
            enriched = customer.raw_response.get("_enriched_alert_risks") or []
            for block in enriched:
                if not isinstance(block, dict):
                    continue
                if str(block.get("_alert_id") or "") == str(alert.external_alert_id):
                    raw_risks = block
                    break

    return AmlAlertDetailsDto(
        id=alert.id,
        aml_customer_id=alert.aml_customer_id,
        external_alert_id=alert.external_alert_id,
        title=alert.title,
        description=alert.description,
        match_type=alert.match_type,
        match_details=alert.match_details,
        raw_risks=raw_risks,
        status=alert.status,
        created_at=alert.created_at,
    )


async def _sync_alert_transition_to_ca(alert: AmlAlert, ca_state: str) -> bool:
    """Опциональный hook: синхронизируем alert state с CA.

    Возвращает True если синк прошёл, False — если пропущен/упал. Локальный
    флоу не ломается — ошибка только логируется warning'ом.
    """
    if not alert.external_alert_id:
        # Исторический alert без CA-id — нечего синкать.
        return False
    try:
        await comply_advantage_client.transition_alert(alert.external_alert_id, ca_state)
        return True
    except RuntimeError:
        # CA не настроен — пропускаем.
        return False
    except Exception as e:
        logger.warning(
            "CA transition_alert failed for alert %s (state=%s): %s",
            alert.external_alert_id, ca_state, e,
        )
        return False


@router.post("/alerts/{alert_id}/confirm")
async def confirm_alert(
    alert_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_staff_or_admin),
):
    """Подтвердить алерт (true positive) + синкнуть с CA (POSITIVE_END_STATE)."""
    result = await db.execute(select(AmlAlert).where(AmlAlert.id == alert_id))
    alert = result.scalar_one_or_none()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")

    alert.status = AmlAlertStatus.CONFIRMED.value
    alert.decided_by = current_user.user_id
    alert.decided_at = datetime.utcnow()
    await db.commit()

    # CA-синк идёт после commit'а локального изменения — не блокирует UX.
    ca_synced = await _sync_alert_transition_to_ca(alert, "POSITIVE_END_STATE")
    return {"success": True, "ca_synced": ca_synced}


@router.post("/alerts/{alert_id}/dismiss")
async def dismiss_alert(
    alert_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_staff_or_admin),
):
    """Отклонить алерт (false positive) + синкнуть с CA (NEGATIVE_END_STATE)."""
    result = await db.execute(select(AmlAlert).where(AmlAlert.id == alert_id))
    alert = result.scalar_one_or_none()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")

    alert.status = AmlAlertStatus.DISMISSED.value
    alert.decided_by = current_user.user_id
    alert.decided_at = datetime.utcnow()
    await db.commit()

    ca_synced = await _sync_alert_transition_to_ca(alert, "NEGATIVE_END_STATE")
    return {"success": True, "ca_synced": ca_synced}


# ── Cases ────────────────────────────────────────────────────────────

@router.post("/cases/{case_id}/comment", response_model=AmlCaseCommentDto)
async def add_case_comment(
    case_id: int,
    body: AmlCaseCommentRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_staff_or_admin),
):
    """Добавить комментарий к кейсу"""
    result = await db.execute(select(AmlCase).where(AmlCase.id == case_id))
    case = result.scalar_one_or_none()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    comment = AmlCaseComment(
        aml_case_id=case.id,
        comment=body.comment,
        created_by=current_user.user_id,
        created_at=datetime.utcnow(),
    )
    db.add(comment)
    await db.commit()
    await db.refresh(comment)

    # Синхронизировать с CA если есть external_case_id (fire-and-forget, не блокируем)
    if case.external_case_id:
        try:
            author = getattr(current_user, "email", None) or current_user.user_id
            await comply_advantage_client.add_case_note(
                case.external_case_id,
                f"[{author}] {body.comment}",
            )
        except Exception as e:
            logger.warning(
                f"AML: не удалось синхронизировать комментарий с CA "
                f"case={case.external_case_id}: {e}"
            )

    return AmlCaseCommentDto.model_validate(comment)


@router.patch("/cases/{case_id}")
async def update_case(
    case_id: int,
    body: AmlUpdateCaseRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_staff_or_admin),
):
    """Обновить статус кейса"""
    result = await db.execute(select(AmlCase).where(AmlCase.id == case_id))
    case = result.scalar_one_or_none()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    case.status = body.status
    if body.status == AmlCaseStatus.CLOSED.value:
        case.closed_by = current_user.user_id
        case.closed_at = datetime.utcnow()
    await db.commit()
    return {"success": True}


# ── Monitoring ───────────────────────────────────────────────────────

@router.get("/monitored", response_model=list[AmlCustomerDto])
async def list_monitored(
    risk_level: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_staff_or_admin),
):
    """Список мониторируемых клиентов"""
    q = select(AmlCustomer).where(AmlCustomer.monitored == True).order_by(AmlCustomer.created_at.desc())
    if risk_level:
        q = q.where(AmlCustomer.risk_level == risk_level)

    result = await db.execute(q.limit(200))
    return [AmlCustomerDto.model_validate(c) for c in result.scalars().all()]


# ── Summary ──────────────────────────────────────────────────────────

@router.get("/summary", response_model=AmlSummaryDto)
async def get_summary(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_staff_or_admin),
):
    """Статистика AML дашборда"""
    total = (await db.execute(select(func.count()).select_from(AmlCustomer))).scalar() or 0
    high = (await db.execute(
        select(func.count()).select_from(AmlCustomer).where(AmlCustomer.risk_level == AmlRiskLevel.HIGH.value)
    )).scalar() or 0
    cases = (await db.execute(
        select(func.count()).select_from(AmlCase).where(AmlCase.status == AmlCaseStatus.OPEN.value)
    )).scalar() or 0
    alerts = (await db.execute(
        select(func.count()).select_from(AmlAlert).where(AmlAlert.status == AmlAlertStatus.PENDING.value)
    )).scalar() or 0
    monitored = (await db.execute(
        select(func.count()).select_from(AmlCustomer).where(AmlCustomer.monitored == True)
    )).scalar() or 0

    return AmlSummaryDto(
        total_customers=total,
        high_risk=high,
        open_cases=cases,
        open_alerts=alerts,
        monitored=monitored,
    )


# ── Client AML Status ───────────────────────────────────────────────

RISK_PRIORITY = {"high": 3, "medium": 2, "low": 1, "unknown": 0}


@router.get("/client/{client_id}/status")
async def get_client_aml_status(
    client_id: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_staff_or_admin),
):
    """AML-статус клиента: все связанные AML-записи + агрегированный риск"""
    result = await db.execute(
        select(AmlCustomer)
        .where(AmlCustomer.client_id == client_id)
        .order_by(AmlCustomer.created_at.desc())
    )
    customers = result.scalars().all()

    if not customers:
        return {"client_id": client_id, "aml_risk_level": None, "customers": []}

    # Наивысший risk
    worst = max(customers, key=lambda c: RISK_PRIORITY.get(c.risk_level, 0))

    return {
        "client_id": client_id,
        "aml_risk_level": worst.risk_level,
        "customers": [AmlCustomerDto.model_validate(c) for c in customers],
    }


# ======================================================================
# AML P1 — Batch rescreen для scheduled cron
# ======================================================================


@router.post("/rescreen/all-monitored")
async def rescreen_all_monitored(
    limit: int = Query(100, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_staff_or_admin),
):
    """Батч-рескрин всех monitored клиентов. Для cron'а / scheduled task.

    Итерируется по `AmlCustomer.monitored=True AND customer_identifier IS NOT NULL`,
    вызывает для каждого `_do_rescreen`. Ошибки отдельного клиента **не ломают**
    батч — они собираются в `errors[]` и возвращаются.

    Query:
    - `limit` (1..1000, default 100) — максимальное число клиентов за один прогон.
      Ограничение по умолчанию выбрано чтобы не выжечь CA daily-quota за один
      cron-запуск. Запускать раз в неделю из внешнего cron'а (см. CLAUDE.md).

    Returns: `{processed, succeeded, failed, errors[]}`.
    """
    # Читаем только admin (не все staff могут пускать bulk-операции).
    if current_user.role != Role.ADMIN.value:
        raise HTTPException(status_code=403, detail="Admin role required for bulk rescreen")

    result = await db.execute(
        select(AmlCustomer)
        .where(AmlCustomer.monitored.is_(True))
        .where(AmlCustomer.customer_identifier.is_not(None))
        .order_by(AmlCustomer.last_rescreen_at.asc().nulls_first())  # сначала те, кого дольше не перескринили
        .limit(limit)
    )
    customers = result.scalars().all()

    succeeded = 0
    failed = 0
    errors: list[dict] = []
    for customer in customers:
        try:
            await _do_rescreen(customer, db, created_by=current_user.user_id)
            succeeded += 1
        except HTTPException as he:
            failed += 1
            errors.append({"customer_id": customer.id, "status": he.status_code, "detail": he.detail})
        except Exception as e:
            failed += 1
            logger.error("Batch rescreen customer %s failed: %s", customer.id, e)
            errors.append({"customer_id": customer.id, "status": 500, "detail": str(e)})

    return {
        "processed": len(customers),
        "succeeded": succeeded,
        "failed": failed,
        "errors": errors,
    }


# ======================================================================
# AML Audit (P0) — Customer audit logs proxy + Screening reports (PDF)
# См. план: регуляторный AML-трейл из CA + PDF-сертификаты скрининга.
# ======================================================================

def _flatten_audit_log(raw: dict) -> dict:
    """Нормализует один CA audit-log в плоский AmlCustomerAuditLogDto.

    CA отдаёт `actioned_by = {type: SYSTEM|USER, identifier: uuid|null}` и
    `detail` как discriminated union. Мы плющим actioned_by и оставляем detail
    как есть.
    """
    actioned_by = raw.get("actioned_by") or {}
    return {
        "identifier": raw.get("identifier"),
        "occurred_at": raw.get("occurred_at"),
        "type": raw.get("type"),
        "actionedByType": actioned_by.get("type"),
        "actionedByIdentifier": actioned_by.get("identifier"),
        "detail": raw.get("detail"),
    }


@router.get(
    "/customers/{customer_id}/audit",
    response_model=AmlAuditLogsPageDto,
    summary="Audit-trail клиента из ComplyAdvantage",
)
async def get_customer_audit(
    customer_id: int,
    page_number: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    sort: str = Query("-occurred_at"),
    current_user: User = Depends(require_staff_or_admin),
    db: AsyncSession = Depends(get_db),
):
    """Прокси к CA `GET /v2/audit/customers/{customer_identifier}`.

    Возвращает события CUSTOMER_CREATED, CUSTOMER_SCREENED, CASE_CREATED,
    ALERT_MUTED_FOR_RISK и др. — нужно для регуляторного AML-трейла.
    """
    customer = await db.get(AmlCustomer, customer_id)
    if customer is None:
        raise HTTPException(status_code=404, detail="AML customer not found")
    if not customer.customer_identifier:
        raise HTTPException(
            status_code=404,
            detail="No CA customer linked (this customer predates the CA integration)",
        )

    # CA-api иногда отвечает network-error'ом (RemoteProtocolError / ReadTimeout)
    # на прокси-уровне — не из-за настоящей проблемы, а из-за transient hiccup.
    # Делаем retry-once именно для httpx.RequestError (НЕ для HTTPStatusError,
    # они означают реальную 4xx/5xx-ошибку от CA).
    ca_response = None
    last_error: Optional[Exception] = None
    for attempt in range(2):
        try:
            ca_response = await comply_advantage_client.get_customer_audit(
                customer.customer_identifier,
                page_number=page_number,
                page_size=page_size,
                sort=sort,
            )
            break
        except RuntimeError as e:
            # ComplyAdvantage не настроен — возвращаем 503 с понятным сообщением.
            raise HTTPException(status_code=503, detail=str(e))
        except httpx.HTTPStatusError as e:
            logger.error("CA audit HTTP %s: %s", e.response.status_code, e.response.text[:300])
            raise HTTPException(
                status_code=502,
                detail=f"ComplyAdvantage audit API error: HTTP {e.response.status_code}",
            )
        except httpx.RequestError as e:
            # Network-level error (timeout, connection reset, protocol) — retry.
            last_error = e
            logger.warning(
                "CA audit network error (%s) attempt=%s: %s",
                type(e).__name__, attempt + 1, e,
            )
            continue
        except Exception as e:
            logger.error(
                "CA audit unexpected error (%s): %s", type(e).__name__, e,
            )
            raise HTTPException(
                status_code=502,
                detail=f"ComplyAdvantage unavailable: {type(e).__name__}: {e}",
            )

    if ca_response is None:
        err_type = type(last_error).__name__ if last_error else "Unknown"
        logger.error("CA audit failed after retry: %s: %s", err_type, last_error)
        raise HTTPException(
            status_code=502,
            detail=f"ComplyAdvantage network error ({err_type}), please try again",
        )

    raw_logs = ca_response.get("audit_logs") or []
    flat_items = [_flatten_audit_log(l) for l in raw_logs]
    total_count = ca_response.get("total_count")
    # next_page_number — CA отдаёт `next` URL (или null). Мы просто увеличиваем
    # page_number если `next` непустой, иначе None.
    next_page = page_number + 1 if ca_response.get("next") else None

    # model_validate с validation_alias маппит occurred_at → occurredAt.
    return AmlAuditLogsPageDto(
        items=[AmlCustomerAuditLogDto.model_validate(i) for i in flat_items],
        totalCount=total_count,
        nextPageNumber=next_page,
    )


@router.post(
    "/screenings/{screening_id}/report",
    response_model=AmlScreeningReportDto,
    summary="Запросить screening-report (PDF) у CA, сохранить в MinIO, вернуть presigned URL",
)
async def generate_screening_report(
    screening_id: int,
    current_user: User = Depends(require_staff_or_admin),
    db: AsyncSession = Depends(get_db),
):
    """Идемпотентный эндпоинт:

    - Если `screening.report_s3_key` уже задан → возвращаем свежий presigned URL
      на 24h без обращения к CA.
    - Иначе: вызываем `POST /v2/customers/{id}/reports`, в цикле до 30s ждём
      `status: READY`, скачиваем PDF по `download_url`, кладём в MinIO
      `aml/{customer_id}/reports/screening-{id}.pdf`, сохраняем key в БД.
    """
    screening = await db.get(AmlScreening, screening_id)
    if screening is None:
        raise HTTPException(status_code=404, detail="Screening not found")

    # Идемпотентность: если PDF уже сохранён — просто обновляем presigned URL.
    if screening.report_s3_key:
        url = await s3_client.generate_presigned_url(
            screening.report_s3_key,
            expiration=86400,  # 24h
        )
        return AmlScreeningReportDto(
            screeningId=screening.id,
            status="ready",
            downloadUrl=url,
            generatedAt=screening.report_generated_at,
        )

    customer = await db.get(AmlCustomer, screening.aml_customer_id)
    if customer is None or not customer.customer_identifier:
        raise HTTPException(
            status_code=404,
            detail="No CA customer linked to this screening",
        )

    # Запрос к CA и опрос готовности (до 30 секунд: 10 попыток × 3 сек).
    download_url: Optional[str] = None
    for attempt in range(10):
        try:
            ca_response = await comply_advantage_client.generate_customer_report(
                customer.customer_identifier
            )
        except RuntimeError as e:
            raise HTTPException(status_code=503, detail=str(e))
        except httpx.HTTPStatusError as e:
            logger.error("CA report HTTP %s: %s", e.response.status_code, e.response.text[:300])
            raise HTTPException(status_code=502, detail=f"ComplyAdvantage report API error: HTTP {e.response.status_code}")
        except Exception as e:
            logger.error("CA report unexpected error: %s", e)
            raise HTTPException(status_code=502, detail=f"ComplyAdvantage unavailable: {e}")

        reports = ca_response.get("reports") or []
        first_report = reports[0] if reports else {}
        status_value = (first_report.get("status") or "").upper()

        if status_value == "READY" and first_report.get("download_url"):
            download_url = first_report["download_url"]
            break
        # NOT_READY → ждём 3 секунды и пробуем ещё раз.
        await asyncio.sleep(3)

    if not download_url:
        # CA не успел за 30s — отдаём 202-подобный ответ. Клиент дожмёт позже.
        return AmlScreeningReportDto(
            screeningId=screening.id,
            status="pending",
            downloadUrl=None,
            generatedAt=None,
        )

    # Скачиваем PDF и кладём в MinIO.
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            pdf_resp = await client.get(download_url)
            pdf_resp.raise_for_status()
            pdf_bytes = pdf_resp.content
    except Exception as e:
        logger.error("Failed to download CA PDF: %s", e)
        raise HTTPException(status_code=502, detail=f"Failed to download report PDF: {e}")

    s3_key = f"aml/{customer.id}/reports/screening-{screening.id}.pdf"
    # upload_file принимает BinaryIO — заворачиваем bytes в BytesIO.
    from io import BytesIO
    await s3_client.upload_file(
        file=BytesIO(pdf_bytes),
        key=s3_key,
        content_type="application/pdf",
    )

    screening.report_s3_key = s3_key
    screening.report_generated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(screening)

    url = await s3_client.generate_presigned_url(s3_key, expiration=86400)
    return AmlScreeningReportDto(
        screeningId=screening.id,
        status="ready",
        downloadUrl=url,
        generatedAt=screening.report_generated_at,
    )


@router.get(
    "/screenings/{screening_id}/report/download",
    response_model=AmlScreeningReportDto,
    summary="Получить свежий presigned URL для уже сохранённого отчёта",
)
async def download_screening_report(
    screening_id: int,
    current_user: User = Depends(require_staff_or_admin),
    db: AsyncSession = Depends(get_db),
):
    """Не обращается к CA. Только обновляет presigned URL для существующего PDF."""
    screening = await db.get(AmlScreening, screening_id)
    if screening is None:
        raise HTTPException(status_code=404, detail="Screening not found")
    if not screening.report_s3_key:
        raise HTTPException(
            status_code=404,
            detail="No report generated for this screening. Call POST /screenings/{id}/report first.",
        )

    url = await s3_client.generate_presigned_url(
        screening.report_s3_key,
        expiration=86400,
    )
    return AmlScreeningReportDto(
        screeningId=screening.id,
        status="ready",
        downloadUrl=url,
        generatedAt=screening.report_generated_at,
    )
