"""
Audit log viewer endpoints (ТЗ §4.12).

`audit_log` пишется из множества мест (clients/kyc/orders/payeer/...).
Раньше его можно было читать только напрямую из БД — теперь staff UI
может фильтровать, искать, экспортировать события.

Только admin: compliance trail чувствителен, staff-уровня недостаточно.
"""
import csv
import io
import json
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select, func, or_, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import require_admin
from app.models import AuditLog, User
from app.schemas import (
    AuditLogDto,
    AuditLogDetailDto,
    AuditLogPageDto,
    AuditLogDistinctValuesDto,
)

logger = logging.getLogger("garudar_api")

router = APIRouter(prefix="/api/v1/audit", tags=["Audit"])


def _parse_json_field(raw: Optional[str]) -> Optional[dict]:
    """JSON-поля хранятся как Text. Парсим в dict, не падаем на мусоре."""
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, (dict, list)) else {"value": parsed}
    except (json.JSONDecodeError, TypeError):
        # В некоторых старых записях может быть просто строка — оборачиваем.
        return {"raw": raw}


def _row_to_dto(row: AuditLog) -> AuditLogDto:
    return AuditLogDto(
        id=row.id,
        entity=row.entity,
        entity_id=row.entity_id,
        action=row.action,
        created_by=row.created_by,
        created_at=row.created_at,
        # На list-уровне отдаём только has_old/has_new, чтобы payload не разрастался.
        has_old_value=bool(row.old_value),
        has_new_value=bool(row.new_value),
    )


def _build_filter_clauses(
    entity: Optional[str],
    entity_id: Optional[str],
    action: Optional[str],
    created_by: Optional[str],
    since: Optional[datetime],
    until: Optional[datetime],
    q: Optional[str],
):
    """Возвращает list of WHERE-clauses для AuditLog query."""
    clauses = []
    if entity:
        clauses.append(AuditLog.entity == entity)
    if entity_id:
        clauses.append(AuditLog.entity_id == entity_id)
    if action:
        clauses.append(AuditLog.action == action)
    if created_by:
        clauses.append(AuditLog.created_by == created_by)
    if since:
        clauses.append(AuditLog.created_at >= since)
    if until:
        clauses.append(AuditLog.created_at <= until)
    if q:
        # Free-text поиск по entity_id и created_by — самые человекочитаемые
        # поля. Полнотекстовый поиск по old/new_value лучше делать через
        # явный entity_id фильтр (точечно).
        like = f"%{q}%"
        clauses.append(or_(
            AuditLog.entity_id.ilike(like),
            AuditLog.created_by.ilike(like),
        ))
    return clauses


@router.get(
    "",
    response_model=AuditLogPageDto,
    summary="Список audit-событий с фильтрами и пагинацией",
)
async def list_audit_logs(
    entity: Optional[str] = Query(None, description="Filter by entity (e.g. 'clients')"),
    entity_id: Optional[str] = Query(None, description="Filter by exact entity_id"),
    action: Optional[str] = Query(None, description="Filter by action (e.g. 'CREATE')"),
    created_by: Optional[str] = Query(None, description="Filter by exact username"),
    since: Optional[datetime] = Query(None, description="created_at >= since"),
    until: Optional[datetime] = Query(None, description="created_at <= until"),
    q: Optional[str] = Query(None, description="Free-text search in entity_id / created_by"),
    limit: int = Query(25, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Постранично возвращает события `audit_log`.

    Поведение по умолчанию: 25 записей, сортировка по created_at desc.
    Любой из фильтров можно комбинировать. `q` — общий free-text поиск
    по entity_id и created_by (case-insensitive substring).
    """
    clauses = _build_filter_clauses(
        entity=entity, entity_id=entity_id, action=action,
        created_by=created_by, since=since, until=until, q=q,
    )

    # Общее число — один COUNT, тот же фильтр.
    count_stmt = select(func.count()).select_from(AuditLog)
    if clauses:
        count_stmt = count_stmt.where(and_(*clauses))
    total = (await db.execute(count_stmt)).scalar() or 0

    stmt = select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit).offset(offset)
    if clauses:
        stmt = stmt.where(and_(*clauses))

    rows = (await db.execute(stmt)).scalars().all()

    return AuditLogPageDto(
        items=[_row_to_dto(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/distinct-values",
    response_model=AuditLogDistinctValuesDto,
    summary="Уникальные entity/action/created_by для UI фильтров",
)
async def get_distinct_values(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Возвращает уникальные значения для filter chips на фронте.

    На больших таблицах (>1M строк) этот endpoint может быть медленным —
    пока БД <100k строк это норма. Если понадобится оптимизация — кешим
    в Redis на 5 минут или делаем материализованное представление.
    """
    entities = (await db.execute(
        select(AuditLog.entity).where(AuditLog.entity.isnot(None)).distinct().order_by(AuditLog.entity)
    )).scalars().all()
    actions = (await db.execute(
        select(AuditLog.action).where(AuditLog.action.isnot(None)).distinct().order_by(AuditLog.action)
    )).scalars().all()
    users = (await db.execute(
        select(AuditLog.created_by).where(AuditLog.created_by.isnot(None)).distinct().order_by(AuditLog.created_by)
    )).scalars().all()

    return AuditLogDistinctValuesDto(
        entities=list(entities),
        actions=list(actions),
        users=list(users),
    )


@router.get(
    "/{audit_id}",
    response_model=AuditLogDetailDto,
    summary="Детали одного audit-события с распарсенными old/new",
)
async def get_audit_log_detail(
    audit_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Возвращает запись + JSON-распарсенные old_value/new_value.

    На list-уровне отдаются только флаги has_old_value/has_new_value,
    чтобы payload листа был лёгким. Здесь — полные данные.
    """
    row = await db.get(AuditLog, audit_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Audit record not found")

    return AuditLogDetailDto(
        id=row.id,
        entity=row.entity,
        entity_id=row.entity_id,
        action=row.action,
        created_by=row.created_by,
        created_at=row.created_at,
        old_value=_parse_json_field(row.old_value),
        new_value=_parse_json_field(row.new_value),
        old_value_raw=row.old_value,
        new_value_raw=row.new_value,
    )


@router.get(
    "/export/csv",
    summary="Экспорт audit-лога в CSV с теми же фильтрами",
)
async def export_audit_csv(
    entity: Optional[str] = Query(None),
    entity_id: Optional[str] = Query(None),
    action: Optional[str] = Query(None),
    created_by: Optional[str] = Query(None),
    since: Optional[datetime] = Query(None),
    until: Optional[datetime] = Query(None),
    q: Optional[str] = Query(None),
    limit: int = Query(10000, ge=1, le=50000),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Streamed CSV-экспорт. Для регуляторных выгрузок.

    Hard cap 50k строк за раз — больше может убить worker. На больших
    выгрузках лучше уточнить фильтры (например period since/until
    помесячно).
    """
    clauses = _build_filter_clauses(
        entity=entity, entity_id=entity_id, action=action,
        created_by=created_by, since=since, until=until, q=q,
    )

    stmt = select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)
    if clauses:
        stmt = stmt.where(and_(*clauses))
    rows = (await db.execute(stmt)).scalars().all()

    # Buffer-based: для 10-50k строк проще держать в памяти, чем стримить.
    # Если упрёмся в RAM на больших файлах — переписать на async-генератор
    # с асинхронной выдачей чанками. Сейчас типичный экспорт < 1MB.
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow([
        "id", "created_at", "created_by", "entity", "entity_id",
        "action", "old_value", "new_value",
    ])
    for r in rows:
        writer.writerow([
            r.id,
            r.created_at.isoformat() if r.created_at else "",
            r.created_by or "",
            r.entity or "",
            r.entity_id or "",
            r.action or "",
            r.old_value or "",
            r.new_value or "",
        ])

    buf.seek(0)
    filename = f"audit-log-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
