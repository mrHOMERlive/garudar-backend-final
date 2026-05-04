"""
Ежедневная автоматическая загрузка и импорт санкционных списков.
Заменяет s3_entry_watcher. Скачивает 5 источников, парсит, обновляет БД.
"""
import asyncio
import logging
import ssl

import httpx
from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import async_session_maker
from app.models import Entry
from app.services.entry_importer import parse_excel
from app.services.ofac_parser import parse_ofac_zip
from app.services.un_parser import parse_un_xml

logger = logging.getLogger("garudar_api")

POLL_INTERVAL = 86400  # 24 часа
STARTUP_DELAY = 30     # секунд до первого запуска
DOWNLOAD_TIMEOUT = 1800  # секунд на скачивание одного файла (30 мин для OFAC 106 МБ)

# PostgreSQL advisory lock ID (отличается от старого entry watcher = 839271)
SANCTIONS_LOCK_ID = 839273

PPATK_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,*/*",
    "Referer": "https://www.ppatk.go.id/",
}

# Кастомный SSL контекст для PPATK серверов:
# ppatk.go.id имеет нестандартную TLS конфигурацию. Для совместимости нужно:
# 1) Явно задать cipher suites (меняет формат ClientHello)
# 2) OP_DONT_INSERT_EMPTY_FRAGMENTS (0x800) — эквивалент curl --ssl-allow-beast
# 3) OP_ALLOW_UNSAFE_LEGACY_RENEGOTIATION и OP_LEGACY_SERVER_CONNECT (Python 3.12+)
_ppatk_ssl_ctx = ssl.create_default_context()
_ppatk_ssl_ctx.check_hostname = False
_ppatk_ssl_ctx.verify_mode = ssl.CERT_NONE
_ppatk_ssl_ctx.set_ciphers("AES256-SHA:AES128-SHA:DES-CBC3-SHA:DEFAULT@SECLEVEL=0")
_ppatk_ssl_ctx.options |= 0x00000800  # SSL_OP_DONT_INSERT_EMPTY_FRAGMENTS
if hasattr(ssl, "OP_ALLOW_UNSAFE_LEGACY_RENEGOTIATION"):
    _ppatk_ssl_ctx.options |= ssl.OP_ALLOW_UNSAFE_LEGACY_RENEGOTIATION
if hasattr(ssl, "OP_LEGACY_SERVER_CONNECT"):
    _ppatk_ssl_ctx.options |= ssl.OP_LEGACY_SERVER_CONNECT

SOURCES = [
    {
        "name": "PPATK DPRK",
        "url": "https://www.ppatk.go.id/backend/assets/uploads/20241224112409.xlsx",
        "parser": "ppatk",
        "source_override": "DPRK",
        "source_lists": ["DPRK", "PPATK DPRK"],  # включает старый формат для очистки
    },
    {
        "name": "PPATK Iran",
        "url": "https://www.ppatk.go.id/backend/assets/uploads/20241224112633.xlsx",
        "parser": "ppatk",
        "source_override": "IRAN",
        "source_lists": ["IRAN", "PPATK IRAN"],  # включает старый формат для очистки

    },
    {
        "name": "PPATK DTTOT",
        "url": "https://ppatk.go.id/backend/assets/uploads/20260129052711.xlsx",
        "parser": "ppatk",
        "source_override": None,
        "source_lists": ["DTTOT", "UN-AQ", "DPPSPM"],

    },
    {
        "name": "OFAC SDN Enhanced",
        "url": "https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/SDN_ENHANCED.ZIP",
        "parser": "ofac",
        "source_override": None,
        "source_lists": ["OFAC-SDN"],

    },
    {
        "name": "UN SC Consolidated",
        "url": "https://scsanctions.un.org/resources/xml/en/consolidated.xml",
        "parser": "un",
        "source_override": None,
        "source_lists": ["UN-SC"],

    },
]


async def _download(url: str, verify_ssl: bool | ssl.SSLContext = True, headers: dict | None = None) -> bytes:
    """Скачивает файл по URL, возвращает байты."""
    async with httpx.AsyncClient(
        timeout=DOWNLOAD_TIMEOUT,
        follow_redirects=True,
        verify=verify_ssl,
        headers=headers or {},
    ) as client:
        logger.info(f"Downloading {url}")
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.content


async def _bulk_insert(db: AsyncSession, entries: list[Entry]) -> None:
    """Быстрая вставка через executemany (core INSERT) вместо медленного ORM add_all."""
    # Исключаем 'id' — autoincrement BigInteger, генерируется БД автоматически
    cols = [c.key for c in Entry.__table__.columns if c.key != "id"]
    rows = [
        {col: getattr(e, col) for col in cols}
        for e in entries
    ]
    await db.execute(Entry.__table__.insert(), rows)
    await db.commit()


async def _sync_source(source: dict, db: AsyncSession) -> int:
    """Скачивает, парсит и заменяет записи одного источника. Возвращает кол-во записей."""
    is_ppatk = source["parser"] == "ppatk"
    verify_ssl = _ppatk_ssl_ctx if is_ppatk else True
    headers = PPATK_HEADERS if is_ppatk else None
    file_bytes = await _download(source["url"], verify_ssl=verify_ssl, headers=headers)

    # Парсинг выполняется в thread pool чтобы не блокировать asyncio event loop:
    # ET.fromstring (OFAC) и openpyxl (PPATK) — CPU-bound синхронные операции.
    parser = source["parser"]
    if parser == "ppatk":
        entries = await asyncio.to_thread(parse_excel, file_bytes, source.get("source_override"))
    elif parser == "ofac":
        entries = await asyncio.to_thread(parse_ofac_zip, file_bytes)
    elif parser == "un":
        entries = await asyncio.to_thread(parse_un_xml, file_bytes)
    else:
        raise ValueError(f"Unknown parser: {parser}")

    if not entries:
        logger.warning(f"[{source['name']}] No entries parsed, skipping DB update")
        return 0

    # Заменяем только записи этого источника
    await db.execute(delete(Entry).where(Entry.source_list.in_(source["source_lists"])))
    await _bulk_insert(db, entries)

    logger.info(f"[{source['name']}] Imported {len(entries)} entries")
    return len(entries)


async def _run_sync_cycle():
    """Один цикл синхронизации всех источников с advisory lock."""
    async with async_session_maker() as lock_db:
        result = await lock_db.execute(
            text(f"SELECT pg_try_advisory_lock({SANCTIONS_LOCK_ID})")
        )
        if not result.scalar():
            logger.info("Sanctions sync skipped — another worker is already syncing")
            return

        try:
            total = 0
            for source in SOURCES:
                try:
                    async with async_session_maker() as db:
                        count = await _sync_source(source, db)
                        total += count
                except Exception as e:
                    logger.error(f"[{source['name']}] Sync failed: {e}", exc_info=True)
            logger.info(f"Sanctions sync complete. Total entries imported: {total}")
        finally:
            await lock_db.execute(
                text(f"SELECT pg_advisory_unlock({SANCTIONS_LOCK_ID})")
            )


async def run_sanctions_scheduler():
    """Основной цикл: запускается при старте, потом каждые 24 часа."""
    logger.info(f"Sanctions scheduler started (poll every {POLL_INTERVAL}s, startup delay={STARTUP_DELAY}s)")
    await asyncio.sleep(STARTUP_DELAY)

    while True:
        try:
            await _run_sync_cycle()
        except Exception as e:
            logger.error(f"Sanctions scheduler error: {e}", exc_info=True)
        await asyncio.sleep(POLL_INTERVAL)
