import json as _json
import uuid
import mimetypes
from datetime import datetime
from io import BytesIO
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional, List
from pydantic import BaseModel, Field
from app.db import get_db
from app.models import User, Client, NdaRequest, NdaStatusHistory, ClientRequestBadge, Role, AuditLog
from app.schemas import NDARequestDto, NDARequestCreateDto, NDARequestUpdateDto, NDADecisionDto
from app.deps import get_current_active_user
from app.enums import NDAStatus
from app.s3_client import get_s3_client, S3Client
from app.file_validators import validate_pdf_not_encrypted
from app.services import nda_generator

router = APIRouter(tags=["NDA"])

# ТЗ Sec 5.5.2: presigned URL для NDA-документов должны жить 5-15 мин.
# 900 сек = 15 мин — верхняя граница; для скачивания подписанной NDA
# времени достаточно, brute-force-перебор URL по 32-байтному signature
# за 15 мин невозможен.
NDA_PRESIGNED_URL_TTL = 900

# Текущий шаблон NDA (только English). Когда понадобится несколько
# шаблонов — заменить на selector в форме и валидацию в endpoints.
DEFAULT_NDA_TEMPLATE_CODE = "NDA_ENG_V1"


def _build_generator_fields(nda: NdaRequest) -> dict:
    """Собирает словарь полей для nda_generator.generate()."""
    return {
        "effective_date": nda.effective_date,
        "partner_name_en": nda.partner_name_en,
        "partner_country_en": nda.partner_country_en,
        "partner_inn": nda.partner_inn,
        "partner_signatory_en": nda.partner_signatory_en,
        "partner_signatory_title_en": nda.partner_signatory_title_en,
        "partner_address_en": nda.partner_address_en,
        "partner_contact_email": nda.partner_contact_email,
    }


def _audit_nda(
    db: AsyncSession,
    nda: NdaRequest,
    action: str,
    user: User,
    old_value: Optional[dict] = None,
    new_value: Optional[dict] = None,
) -> None:
    """Запись в глобальный AuditLog для NDA-событий. ТЗ Sec 4.12."""
    db.add(AuditLog(
        entity="nda_request",
        entity_id=str(nda.nda_id),
        action=action,
        old_value=_json.dumps(old_value, ensure_ascii=False, default=str) if old_value else None,
        new_value=_json.dumps(new_value, ensure_ascii=False, default=str) if new_value else None,
        created_by=user.username,
        created_at=datetime.utcnow(),
    ))


class FileUploadResponse(BaseModel):
    file_url: str = Field(description="URL загруженного файла")
    file_name: str = Field(description="Имя файла")
    file_size: int = Field(description="Размер файла в байтах")


async def _get_client_for_user(
    client_id: str,
    current_user: User,
    db: AsyncSession,
) -> Client:
    """Получить клиента с проверкой прав доступа."""
    result = await db.execute(
        select(Client).where(Client.client_id == client_id)
    )
    client = result.scalar_one_or_none()
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found")

    if current_user.role == Role.USER.value:
        if client.user_id != current_user.user_id:
            raise HTTPException(status_code=403, detail="Access denied")

    return client


@router.get("/nda-requests", response_model=List[NDARequestDto])
async def list_nda_requests(
    client_id: Optional[str] = Query(None, description="Фильтр по client_id"),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Получить список NDA заявок.
    - USER: только свои (по client_id, привязанному к user_id).
    - ADMIN / STAFF: все или с фильтром по client_id.
    """
    query = select(NdaRequest)

    if current_user.role == Role.USER.value:
        # Найти client_id текущего пользователя
        result = await db.execute(
            select(Client.client_id).where(Client.user_id == current_user.user_id)
        )
        user_client_ids = [row[0] for row in result.all()]

        if client_id and client_id not in user_client_ids:
            raise HTTPException(status_code=403, detail="Access denied")

        if client_id:
            query = query.where(NdaRequest.client_id == client_id)
        else:
            query = query.where(NdaRequest.client_id.in_(user_client_ids))
    else:
        if client_id:
            query = query.where(NdaRequest.client_id == client_id)

    query = query.order_by(NdaRequest.nda_id.desc())
    result = await db.execute(query)
    nda_requests = result.scalars().all()

    return [NDARequestDto.model_validate(r, from_attributes=True) for r in nda_requests]


@router.post("/nda-requests", response_model=NDARequestDto, status_code=201)
async def create_nda_request(
    data: NDARequestCreateDto,
    client_id: str = Query(..., description="ID клиента"),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Создать новую NDA заявку со статусом 'draft'.
    """
    client = await _get_client_for_user(client_id, current_user, db)

    nda = NdaRequest(
        client_id=client_id,
        status=NDAStatus.DRAFT.value,
        effective_date=data.effective_date,
        template_code=data.template_code or DEFAULT_NDA_TEMPLATE_CODE,
        term_ru=data.term_ru,
        term_en=data.term_en,
        group_company_id=data.group_company_id,
        partner_inn=data.partner_inn,
        partner_name_ru=data.partner_name_ru,
        partner_name_en=data.partner_name_en,
        partner_address_ru=data.partner_address_ru,
        partner_address_en=data.partner_address_en,
        partner_signatory_ru=data.partner_signatory_ru,
        partner_signatory_en=data.partner_signatory_en,
        partner_signatory_title_en=data.partner_signatory_title_en,
        partner_country_en=data.partner_country_en,
        partner_contact_name=data.partner_contact_name,
        partner_contact_email=data.partner_contact_email,
        partner_contact_phone=data.partner_contact_phone,
        paper_copy_required=data.paper_copy_required or False,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(nda)

    # Обновить nda_status клиента
    if client.nda_status == NDAStatus.NOT_STARTED.value:
        client.nda_status = NDAStatus.DRAFT.value

    await db.commit()
    await db.refresh(nda)

    return NDARequestDto.model_validate(nda, from_attributes=True)


@router.put("/nda-requests/{nda_id}", response_model=NDARequestDto)
async def update_nda_request(
    nda_id: int,
    data: NDARequestUpdateDto,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Обновить NDA заявку.
    При смене статуса на 'submitted':
      - проставляется submitted_at
      - обновляется clients.nda_status
    """
    result = await db.execute(
        select(NdaRequest).where(NdaRequest.nda_id == nda_id)
    )
    nda = result.scalar_one_or_none()
    if nda is None:
        raise HTTPException(status_code=404, detail="NDA request not found")

    # Проверка прав
    client = await _get_client_for_user(nda.client_id, current_user, db)

    old_status = nda.status

    # Обновляем поля
    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if value is not None:
            setattr(nda, field, value)

    nda.updated_at = datetime.utcnow()

    new_status = data.status if data.status else nda.status

    # Бизнес-логика при смене статуса на submitted
    if data.status == NDAStatus.SUBMITTED.value and old_status != NDAStatus.SUBMITTED.value:
        nda.submitted_at = datetime.utcnow()
        client.nda_status = NDAStatus.SUBMITTED.value

    # Запись в историю статусов при изменении
    if data.status and data.status != old_status:
        history = NdaStatusHistory(
            nda_id=nda.nda_id,
            old_status=old_status,
            new_status=data.status,
            changed_by=current_user.user_id,
            changed_at=datetime.utcnow(),
        )
        db.add(history)

    await db.commit()
    await db.refresh(nda)

    return NDARequestDto.model_validate(nda, from_attributes=True)


@router.get("/nda-requests/{nda_id}", response_model=NDARequestDto)
async def get_nda_request(
    nda_id: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Получить NDA заявку по ID.
    """
    result = await db.execute(
        select(NdaRequest).where(NdaRequest.nda_id == nda_id)
    )
    nda = result.scalar_one_or_none()
    if nda is None:
        raise HTTPException(status_code=404, detail="NDA request not found")

    # Проверка прав
    await _get_client_for_user(nda.client_id, current_user, db)

    return NDARequestDto.model_validate(nda, from_attributes=True)


@router.post("/upload", response_model=FileUploadResponse)
async def upload_file(
    file: UploadFile = File(...),
    client_id: Optional[str] = Query(None, description="ID клиента"),
    nda_id: Optional[int] = Query(None, description="ID NDA заявки"),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
    s3: S3Client = Depends(get_s3_client),
):
    """
    Универсальный эндпоинт загрузки файлов в S3.
    Возвращает presigned URL загруженного файла.
    Путь в S3: nda/{client_id}/{nda_id}/{filename}
    Если client_id не передан — определяется автоматически из текущего пользователя.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename is required")

    allowed_extensions = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".zip", ".jpg", ".jpeg", ".png"}
    ext = None
    for allowed_ext in allowed_extensions:
        if file.filename.lower().endswith(allowed_ext):
            ext = allowed_ext
            break

    if not ext:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file format. Allowed: {', '.join(allowed_extensions)}"
        )

    file_content = await file.read()
    file_size = len(file_content)

    max_size = 50 * 1024 * 1024  # 50 MB
    if file_size > max_size:
        raise HTTPException(status_code=400, detail="File size exceeds 50 MB limit")

    # ТЗ Sec 5.5.3: парольно-защищённые PDF не принимаем —
    # staff не сможет открыть подписанный NDA.
    await validate_pdf_not_encrypted(file_content, file.filename)

    # Определяем client_id автоматически, если не передан
    cid = client_id
    if not cid:
        result = await db.execute(
            select(Client.client_id).where(Client.user_id == current_user.user_id)
        )
        row = result.first()
        cid = row[0] if row else current_user.user_id

    # Определяем nda_id: если не передан, ищем последнюю заявку клиента
    nid = str(nda_id) if nda_id else None
    if not nid:
        result = await db.execute(
            select(NdaRequest.nda_id)
            .where(NdaRequest.client_id == cid)
            .order_by(NdaRequest.nda_id.desc())
            .limit(1)
        )
        row = result.first()
        nid = str(row[0]) if row else "general"

    unique_id = uuid.uuid4().hex[:8]
    s3_key = f"nda/{cid}/{nid}/{unique_id}_{file.filename}"

    content_type, _ = mimetypes.guess_type(file.filename)
    content_type = content_type or "application/octet-stream"

    await s3.upload_file(
        file=BytesIO(file_content),
        key=s3_key,
        content_type=content_type,
    )

    # ТЗ Sec 5.5.2: presigned URL живёт 15 мин (см. NDA_PRESIGNED_URL_TTL).
    file_url = await s3.generate_presigned_url(key=s3_key, expiration=NDA_PRESIGNED_URL_TTL)

    return FileUploadResponse(
        file_url=file_url,
        file_name=file.filename,
        file_size=file_size,
    )


# ======================================================================
# NDA WORKFLOW ENDPOINTS
#
# Полный flow English-only NDA (см. план end-to-end NDA generator):
#   DRAFT → GENERATED → SIGNED_UPLOADED → SUBMITTED → ACCEPTED / REJECTED
#
# 1. /generate     — backend генерирует DOCX из шаблона, сохраняет в S3.
# 2. /upload-signed — клиент офлайн подписывает, заливает PDF/DOCX.
# 3. /submit       — клиент финализирует, заявка уходит в Staff Inbox.
# 4. /decision     — staff Accept / Reject, обновляется clients.nda_status.
#
# Каждый endpoint пишет:
#   - NdaStatusHistory (entity-level, для drawer'а)
#   - AuditLog NDA_* (cross-entity, для регулятора)
# ======================================================================


async def _load_nda_with_rights(
    nda_id: int,
    current_user: User,
    db: AsyncSession,
    *,
    require_staff: bool = False,
) -> tuple[NdaRequest, Client]:
    """Загрузить NdaRequest + Client с проверкой прав.

    Если require_staff=True — USER получит 403 (для /decision endpoint).
    """
    if require_staff and current_user.role == Role.USER.value:
        raise HTTPException(status_code=403, detail="Staff/Admin only")

    result = await db.execute(
        select(NdaRequest).where(NdaRequest.nda_id == nda_id)
    )
    nda = result.scalar_one_or_none()
    if nda is None:
        raise HTTPException(status_code=404, detail="NDA request not found")

    client = await _get_client_for_user(nda.client_id, current_user, db)
    return nda, client


@router.post("/nda-requests/{nda_id}/generate", response_model=NDARequestDto)
async def generate_nda(
    nda_id: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
    s3: S3Client = Depends(get_s3_client),
):
    """Сгенерировать DOCX из шаблона и сохранить в S3.

    Разрешено в статусах DRAFT, GENERATED (последний — re-generate после
    правок). Для SIGNED_UPLOADED/SUBMITTED/ACCEPTED/REJECTED — 409,
    чтобы не подменить документ задним числом.
    """
    nda, client = await _load_nda_with_rights(nda_id, current_user, db)

    # REJECTED тоже разрешён — клиент после reject правит поля и
    # генерирует заново. Принимать SIGNED_UPLOADED/SUBMITTED/ACCEPTED
    # не должны: подмена документа в этих состояниях обходит staff-ревью.
    allowed = {
        NDAStatus.DRAFT.value,
        NDAStatus.GENERATED.value,
        NDAStatus.NOT_STARTED.value,
        NDAStatus.REJECTED.value,
    }
    if nda.status not in allowed:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot generate NDA in status '{nda.status}'. Allowed: {sorted(allowed)}",
        )

    # Минимальная валидация: без partner_name_en/partner_address_en
    # документ генерируется с пустыми placeholders — это не блокирующая
    # ошибка, но пользователю удобнее увидеть 400 чем сгенерировать
    # бракованный DOCX.
    missing = [
        f for f in ("partner_name_en", "partner_address_en", "partner_signatory_en", "effective_date")
        if not getattr(nda, f)
    ]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Missing required fields for generation: {missing}",
        )

    fields = _build_generator_fields(nda)
    docx_bytes = nda_generator.generate(fields)

    s3_key = f"nda/{client.client_id}/{nda.nda_id}/generated/NDA_{nda.nda_id}.docx"
    await s3.upload_file(
        file=BytesIO(docx_bytes),
        key=s3_key,
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    presigned = await s3.generate_presigned_url(key=s3_key, expiration=NDA_PRESIGNED_URL_TTL)

    old_status = nda.status
    nda.generated_file_key = s3_key
    nda.generated_file_url = presigned
    nda.generated_file_name = f"NDA_{nda.nda_id}.docx"
    nda.generated_file_size = len(docx_bytes)
    nda.template_code = DEFAULT_NDA_TEMPLATE_CODE
    nda.status = NDAStatus.GENERATED.value
    nda.updated_at = datetime.utcnow()

    if old_status != NDAStatus.GENERATED.value:
        db.add(NdaStatusHistory(
            nda_id=nda.nda_id,
            old_status=old_status,
            new_status=NDAStatus.GENERATED.value,
            changed_by=current_user.user_id,
            changed_at=datetime.utcnow(),
        ))

    _audit_nda(
        db, nda, "NDA_GENERATED", current_user,
        old_value={"status": old_status},
        new_value={"status": NDAStatus.GENERATED.value, "file_key": s3_key, "size": len(docx_bytes)},
    )

    await db.commit()
    await db.refresh(nda)
    return NDARequestDto.model_validate(nda, from_attributes=True)


@router.post("/nda-requests/{nda_id}/upload-signed", response_model=NDARequestDto)
async def upload_signed_nda(
    nda_id: int,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
    s3: S3Client = Depends(get_s3_client),
):
    """Загрузить подписанный клиентом NDA (PDF/DOCX) в S3."""
    nda, client = await _load_nda_with_rights(nda_id, current_user, db)

    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename is required")

    allowed_ext = {".pdf", ".doc", ".docx"}
    ext = next((e for e in allowed_ext if file.filename.lower().endswith(e)), None)
    if not ext:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file format. Allowed: {sorted(allowed_ext)}",
        )

    content = await file.read()
    if len(content) > 50 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File exceeds 50 MB")

    await validate_pdf_not_encrypted(content, file.filename)

    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    s3_key = f"nda/{client.client_id}/{nda.nda_id}/signed/SIGNED_{ts}_{file.filename}"

    content_type, _ = mimetypes.guess_type(file.filename)
    await s3.upload_file(
        file=BytesIO(content),
        key=s3_key,
        content_type=content_type or "application/octet-stream",
    )
    presigned = await s3.generate_presigned_url(key=s3_key, expiration=NDA_PRESIGNED_URL_TTL)

    old_status = nda.status
    nda.signed_file_key = s3_key
    nda.signed_file_url = presigned
    nda.signed_file_name = file.filename
    nda.signed_file_size = len(content)
    nda.status = NDAStatus.SIGNED_UPLOADED.value
    nda.updated_at = datetime.utcnow()

    if old_status != NDAStatus.SIGNED_UPLOADED.value:
        db.add(NdaStatusHistory(
            nda_id=nda.nda_id,
            old_status=old_status,
            new_status=NDAStatus.SIGNED_UPLOADED.value,
            changed_by=current_user.user_id,
            changed_at=datetime.utcnow(),
        ))

    _audit_nda(
        db, nda, "NDA_SIGNED_UPLOADED", current_user,
        old_value={"status": old_status},
        new_value={"status": NDAStatus.SIGNED_UPLOADED.value, "file_key": s3_key, "size": len(content)},
    )

    await db.commit()
    await db.refresh(nda)
    return NDARequestDto.model_validate(nda, from_attributes=True)


@router.post("/nda-requests/{nda_id}/submit", response_model=NDARequestDto)
async def submit_nda(
    nda_id: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Финальная отправка NDA на review Staff."""
    nda, client = await _load_nda_with_rights(nda_id, current_user, db)

    if nda.status != NDAStatus.SIGNED_UPLOADED.value:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot submit NDA in status '{nda.status}'. Required: 'signed_uploaded'",
        )

    old_status = nda.status
    now = datetime.utcnow()
    nda.status = NDAStatus.SUBMITTED.value
    nda.submitted_at = now
    nda.updated_at = now
    client.nda_status = NDAStatus.SUBMITTED.value

    db.add(NdaStatusHistory(
        nda_id=nda.nda_id,
        old_status=old_status,
        new_status=NDAStatus.SUBMITTED.value,
        changed_by=current_user.user_id,
        changed_at=now,
    ))

    _audit_nda(
        db, nda, "NDA_SUBMITTED", current_user,
        old_value={"status": old_status},
        new_value={"status": NDAStatus.SUBMITTED.value, "submitted_at": now.isoformat()},
    )

    await db.commit()
    await db.refresh(nda)
    return NDARequestDto.model_validate(nda, from_attributes=True)


@router.post("/nda-requests/{nda_id}/decision", response_model=NDARequestDto)
async def staff_decision_nda(
    nda_id: int,
    decision: NDADecisionDto,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Staff/Admin: Accept или Reject NDA (с обязательным comment для reject)."""
    nda, client = await _load_nda_with_rights(nda_id, current_user, db, require_staff=True)

    if nda.status != NDAStatus.SUBMITTED.value:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot decide on NDA in status '{nda.status}'. Required: 'submitted'",
        )
    if decision.status == NDAStatus.REJECTED.value and not (decision.comment and decision.comment.strip()):
        raise HTTPException(status_code=400, detail="Comment is required for rejection")

    old_status = nda.status
    now = datetime.utcnow()
    nda.status = decision.status
    nda.updated_at = now
    client.nda_status = decision.status

    db.add(NdaStatusHistory(
        nda_id=nda.nda_id,
        old_status=old_status,
        new_status=decision.status,
        changed_by=current_user.user_id,
        changed_at=now,
        comment=decision.comment,
    ))

    action = "NDA_ACCEPTED" if decision.status == NDAStatus.ACCEPTED.value else "NDA_REJECTED"
    _audit_nda(
        db, nda, action, current_user,
        old_value={"status": old_status},
        new_value={"status": decision.status, "comment": decision.comment, "decided_at": now.isoformat()},
    )

    await db.commit()
    await db.refresh(nda)
    return NDARequestDto.model_validate(nda, from_attributes=True)


@router.get("/nda-requests/{nda_id}/history")
async def nda_history(
    nda_id: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """История смен статусов (для drawer'а на Staff/Client UI)."""
    nda, _ = await _load_nda_with_rights(nda_id, current_user, db)
    result = await db.execute(
        select(NdaStatusHistory)
        .where(NdaStatusHistory.nda_id == nda.nda_id)
        .order_by(NdaStatusHistory.changed_at.asc())
    )
    rows = result.scalars().all()
    return [
        {
            "id": r.id,
            "old_status": r.old_status,
            "new_status": r.new_status,
            "changed_by": r.changed_by,
            "changed_at": r.changed_at.isoformat() if r.changed_at else None,
            "comment": r.comment,
        }
        for r in rows
    ]
