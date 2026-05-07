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
from app.models import User, Client, NdaRequest, NdaStatusHistory, ClientRequestBadge, Role
from app.schemas import NDARequestDto, NDARequestCreateDto, NDARequestUpdateDto
from app.deps import get_current_active_user
from app.enums import NDAStatus
from app.s3_client import get_s3_client, S3Client
from app.file_validators import validate_pdf_not_encrypted

router = APIRouter(tags=["NDA"])


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
        template_code=data.template_code,
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

    file_url = await s3.generate_presigned_url(key=s3_key, expiration=86400)

    return FileUploadResponse(
        file_url=file_url,
        file_name=file.filename,
        file_size=file_size,
    )
