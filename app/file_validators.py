"""
Общие валидаторы загружаемых файлов.

Сюда выносятся проверки, которые должны применяться единообразно
во всех upload-эндпоинтах (KYC, NDA, документы заказов и т.д.),
чтобы регулятор видел согласованное поведение системы.
"""
import asyncio
import logging
from io import BytesIO

from fastapi import HTTPException
from PyPDF2 import PdfReader

logger = logging.getLogger(__name__)


async def validate_pdf_not_encrypted(content: bytes, filename: str) -> None:
    """
    Отклонить загрузку PDF с парольной защитой.

    ТЗ Sec 5.5.3: encrypted/password-protected PDFs не могут быть
    открыты staff'ом без пароля, поэтому система обязана отклонять их
    на этапе загрузки.

    No-op для:
    - не-PDF файлов (по расширению, case-insensitive)
    - PDF, которые PyPDF2 не смог распарсить (нестандартный формат
      или порча) — чтобы не ломать легитимные загрузки. Такие файлы
      пропускаются по принципу "fail open" — сценарий с энкрипцией
      обнаруживается у стандартных PDF, а корректность нестандартных
      проверяется отдельным AV/контент-сканированием (вне этой функции).

    Args:
        content: Сырые байты файла (уже прочитанные из UploadFile).
        filename: Имя файла — нужно только для определения расширения.

    Raises:
        HTTPException 400: если PDF явно зашифрован.
    """
    if not filename or not filename.lower().endswith(".pdf"):
        return

    try:
        pdf_reader = await asyncio.to_thread(PdfReader, BytesIO(content))
    except Exception as exc:
        logger.debug(
            "PDF parsing failed for %s, skipping encryption check: %s",
            filename, exc,
        )
        return

    if pdf_reader.is_encrypted:
        logger.warning("Rejected encrypted PDF upload: filename=%s", filename)
        raise HTTPException(
            status_code=400,
            detail=(
                "Password-protected PDF files are not allowed. "
                "Please remove the password before uploading."
            ),
        )
