"""
Локальный скрининг по таблице `entries` (PPATK: DTTOT, DPPSPM, UN-AQ).

Используется параллельно с ComplyAdvantage в `auto_screen_on_kyc_approval`,
а также из ручки `POST /api/v1/aml/client/{id}/rescreen-ppatk` для
ручной перепроверки клиента после обновления PPATK-списков.

Что делаем:
- pg_trgm `similarity()` против всех "именных" колонок Entry
  (name1..name4 и alias) — берём максимум.
- Фильтруем `source_list IN ('DTTOT', 'DPPSPM', 'UN-AQ')`.
- Опционально: точный матч по `identity_no` (NIK) или `passport_no`,
  чтобы поймать переименования с тем же документом.
- Возвращаем top-20 совпадений выше порога `SIMILARITY_THRESHOLD`.

ComplyAdvantage не покрывает индонезийские PPATK-списки, поэтому без
этого сервиса DTTOT/DPPSPM-данные, которые ежедневно качает
`sanctions_scheduler`, не используются в KYC-флоу.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sqlalchemy import select, or_, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Entry

# Источники, по которым проводим локальный матч.
# Соответствует тому, что складывает `entry_importer._derive_source_list`.
LOCAL_SOURCES: tuple[str, ...] = ("DTTOT", "DPPSPM", "UN-AQ")

# Минимальный порог pg_trgm similarity (0..1). Подбирался эмпирически:
# 0.55 ловит транслитерации и пропуски одной буквы, при этом редко даёт
# ложные срабатывания на коротких корпоративных названиях.
SIMILARITY_THRESHOLD: float = 0.55

# Жёсткий лимит на размер выдачи. При превышении staff увидит "many matches"
# и должен прицельно искать через StaffKYC. На практике >5 совпадений
# означает плохо нормализованный input (например, имя из одного слова).
MAX_MATCHES: int = 20


@dataclass(frozen=True)
class LocalMatch:
    entry_id: int
    source_list: str           # 'DTTOT' | 'DPPSPM' | 'UN-AQ'
    matched_name: str          # фактически совпавшая строка
    full_name: str             # каноническое имя из entries
    similarity: float          # 0..1
    entry_type: str            # 'Individual' | 'Entity'


async def screen_name_against_local(
    db: AsyncSession,
    name: str,
    entry_type: Optional[str] = None,
    identity_no: Optional[str] = None,
) -> list[LocalMatch]:
    """
    Ищет в таблице `entries` записи, чьё имя нечётко совпадает с `name`.

    Args:
        db: активная AsyncSession.
        name: строка для поиска. Whitespace strip'ается, регистр не важен.
        entry_type: 'Individual' или 'Entity' — если задано, отсекает
            записи противоположного типа. Это важно потому что директор
            компании ABC Holdings (физлицо) не должен матчиться против
            строки entries с entry_type=Entity и full_name="ABC Holdings".
        identity_no: NIK или passport_no — точный матч (case-sensitive
            в пределах VARCHAR). Полезно когда у клиента известен ID, а
            написание имени отличается.

    Returns:
        Список совпадений отсортированный по similarity по убыванию.
        Пустой список — если совпадений нет или name пустое.
    """
    if not name or not name.strip():
        return []
    needle = name.strip()

    # `func.similarity` использует pg_trgm.similarity — требует EXTENSION pg_trgm.
    # Расширение и GIN-индексы создаются миграцией
    # alembic/versions/<hash>_pg_trgm_for_entries.py.
    sim_cols = [
        func.coalesce(func.similarity(Entry.name1, needle), 0),
        func.coalesce(func.similarity(Entry.name2, needle), 0),
        func.coalesce(func.similarity(Entry.name3, needle), 0),
        func.coalesce(func.similarity(Entry.name4, needle), 0),
        func.coalesce(func.similarity(Entry.alias, needle), 0),
    ]
    best_sim = func.greatest(*sim_cols).label("sim")

    # Базовое условие: similarity выше порога ИЛИ (если задан identity_no)
    # точный матч по NIK/passport. or_(...) даёт правильную семантику —
    # точный матч по документу важнее, чем низкая similarity по имени.
    similarity_clause = best_sim >= SIMILARITY_THRESHOLD
    if identity_no:
        match_clause = or_(
            similarity_clause,
            Entry.identity_no == identity_no,
            Entry.passport_no == identity_no,
        )
    else:
        match_clause = similarity_clause

    stmt = (
        select(Entry, best_sim)
        .where(Entry.source_list.in_(LOCAL_SOURCES))
        .where(match_clause)
    )
    if entry_type:
        stmt = stmt.where(Entry.entry_type == entry_type)

    stmt = stmt.order_by(best_sim.desc()).limit(MAX_MATCHES)

    rows = (await db.execute(stmt)).all()
    return [
        LocalMatch(
            entry_id=entry.id,
            source_list=entry.source_list or "",
            matched_name=entry.full_name or entry.name1 or "",
            full_name=entry.full_name or "",
            similarity=float(sim or 0),
            entry_type=entry.entry_type or "Unknown",
        )
        for (entry, sim) in rows
    ]


def severity_from_source(source_list: str) -> str:
    """
    Уровень риска по источнику.

    DTTOT (терроризм), DPPSPM (proliferation financing) и UN-AQ
    (Al-Qaeda Sanctions List) — все считаются high. Если в LOCAL_SOURCES
    добавятся менее критичные источники, здесь должен появиться маппинг.
    """
    if source_list in ("DTTOT", "DPPSPM", "UN-AQ"):
        return "high"
    return "medium"


def alert_external_id_for_entry(entry_id: int) -> str:
    """
    Канонический `external_alert_id` для локального PPATK-матча.

    Используется для идемпотентности: повторный rescan того же
    `(aml_customer, entry)` не должен создавать дубль `AmlAlert`.
    Префикс "LOCAL-" отличает локальные алерты от CA (у тех — UUID).
    """
    return f"LOCAL-{entry_id}"
