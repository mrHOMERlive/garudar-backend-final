"""Service Agreement workflow (зеркало app/routers/nda.py).

End-to-end flow English-only Service Agreement:
  DRAFT → GENERATED → SIGNED_UPLOADED → SUBMITTED → ACCEPTED / REJECTED

Endpoints:
  POST /service-agreement-requests                       — создать SA-заявку
  GET  /service-agreement-requests                       — список (user видит свои, staff все)
  GET  /service-agreement-requests/{sa_id}               — детали заявки
  PUT  /service-agreement-requests/{sa_id}               — обновить поля
  POST /service-agreement-requests/{sa_id}/generate      — сгенерировать DOCX
  POST /service-agreement-requests/{sa_id}/upload-signed — загрузить подписанный файл
  POST /service-agreement-requests/{sa_id}/submit        — финализировать (→ Staff Inbox)
  POST /service-agreement-requests/{sa_id}/decision      — Staff Accept/Reject
  GET  /service-agreement-requests/{sa_id}/history       — история смен статусов

Backwards-compat:
  POST /service-agreement/generate           — устаревший free-form generator (оставлен для смягчения миграции).
  POST /service-agreement/generate-and-upload — устаревший admin-only generator.

Каждый workflow-endpoint пишет:
  - ServiceAgreementStatusHistory (entity-level, для drawer'а)
  - AuditLog SA_* (cross-entity, для регулятора, ТЗ Sec 4.12)
"""
import json as _json
import mimetypes
import uuid
from datetime import datetime
from io import BytesIO
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_current_active_user, require_admin
from app.enums import ServiceAgreementStatus
from app.file_validators import validate_pdf_not_encrypted
from app.models import (
    AuditLog,
    Client,
    Role,
    ServiceAgreementRequest,
    ServiceAgreementStatusHistory,
    User,
)
from app.s3_client import S3Client, get_s3_client
from app.schemas import (
    ServiceAgreementDecisionDto,
    ServiceAgreementRequestCreateDto,
    ServiceAgreementRequestDto,
    ServiceAgreementRequestUpdateDto,
)
from app.services import service_agreement_generator

router = APIRouter(tags=["Service Agreement"])

# ТЗ Sec 5.5.2: presigned URL для SA-документов 5-15 минут.
SA_PRESIGNED_URL_TTL = 900

# Текущий шаблон Service Agreement (только English).
DEFAULT_SA_TEMPLATE_CODE = "SA_ENG_V1"


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------

def _build_generator_fields(sa: ServiceAgreementRequest) -> dict:
    """Словарь полей для service_agreement_generator.generate()."""
    return {
        "effective_date": sa.effective_date,
        "company_name": sa.company_name,
        "country": sa.country,
        "address": sa.address,
        "signatory_name": sa.signatory_name,
        "signatory_title": sa.signatory_title,
        "registration_number": sa.registration_number,
        "tax_id": sa.tax_id,
        "contact_email": sa.contact_email,
        "term": sa.term,
    }


def _audit_sa(
    db: AsyncSession,
    sa: ServiceAgreementRequest,
    action: str,
    user: User,
    old_value: Optional[dict] = None,
    new_value: Optional[dict] = None,
) -> None:
    """Запись в AuditLog для SA-событий. ТЗ Sec 4.12."""
    db.add(AuditLog(
        entity="service_agreement_request",
        entity_id=str(sa.sa_id),
        action=action,
        old_value=_json.dumps(old_value, ensure_ascii=False, default=str) if old_value else None,
        new_value=_json.dumps(new_value, ensure_ascii=False, default=str) if new_value else None,
        created_by=user.username,
        created_at=datetime.utcnow(),
    ))


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


async def _load_sa_with_rights(
    sa_id: int,
    current_user: User,
    db: AsyncSession,
    *,
    require_staff: bool = False,
) -> tuple[ServiceAgreementRequest, Client]:
    """Загрузить SA-заявку + Client с проверкой прав."""
    if require_staff and current_user.role == Role.USER.value:
        raise HTTPException(status_code=403, detail="Staff/Admin only")

    result = await db.execute(
        select(ServiceAgreementRequest).where(ServiceAgreementRequest.sa_id == sa_id)
    )
    sa = result.scalar_one_or_none()
    if sa is None:
        raise HTTPException(status_code=404, detail="Service Agreement request not found")

    client = await _get_client_for_user(sa.client_id, current_user, db)
    return sa, client


# ----------------------------------------------------------------------
# CRUD endpoints
# ----------------------------------------------------------------------

@router.get("/service-agreement-requests", response_model=List[ServiceAgreementRequestDto])
async def list_sa_requests(
    client_id: Optional[str] = Query(None, description="Фильтр по client_id"),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Список SA заявок.

    - USER: только свои.
    - ADMIN / STAFF: все или с фильтром по client_id.
    """
    query = select(ServiceAgreementRequest)

    if current_user.role == Role.USER.value:
        result = await db.execute(
            select(Client.client_id).where(Client.user_id == current_user.user_id)
        )
        user_client_ids = [row[0] for row in result.all()]

        if client_id and client_id not in user_client_ids:
            raise HTTPException(status_code=403, detail="Access denied")

        if client_id:
            query = query.where(ServiceAgreementRequest.client_id == client_id)
        else:
            query = query.where(ServiceAgreementRequest.client_id.in_(user_client_ids))
    else:
        if client_id:
            query = query.where(ServiceAgreementRequest.client_id == client_id)

    query = query.order_by(ServiceAgreementRequest.sa_id.desc())
    result = await db.execute(query)
    rows = result.scalars().all()
    return [ServiceAgreementRequestDto.model_validate(r, from_attributes=True) for r in rows]


@router.post(
    "/service-agreement-requests",
    response_model=ServiceAgreementRequestDto,
    status_code=201,
)
async def create_sa_request(
    data: ServiceAgreementRequestCreateDto,
    client_id: str = Query(..., description="ID клиента"),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Создать новую SA заявку со статусом 'draft'."""
    client = await _get_client_for_user(client_id, current_user, db)

    sa = ServiceAgreementRequest(
        client_id=client_id,
        status=ServiceAgreementStatus.DRAFT.value,
        template_code=data.template_code or DEFAULT_SA_TEMPLATE_CODE,
        effective_date=data.effective_date,
        company_name=data.company_name,
        country=data.country,
        address=data.address,
        signatory_name=data.signatory_name,
        signatory_title=data.signatory_title,
        registration_number=data.registration_number,
        tax_id=data.tax_id,
        contact_email=data.contact_email,
        contact_phone=data.contact_phone,
        term=data.term,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(sa)

    if client.service_agreement_status == ServiceAgreementStatus.NOT_STARTED.value:
        client.service_agreement_status = ServiceAgreementStatus.DRAFT.value

    await db.commit()
    await db.refresh(sa)
    return ServiceAgreementRequestDto.model_validate(sa, from_attributes=True)


@router.get(
    "/service-agreement-requests/{sa_id}",
    response_model=ServiceAgreementRequestDto,
)
async def get_sa_request(
    sa_id: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Получить SA заявку по ID."""
    sa, _ = await _load_sa_with_rights(sa_id, current_user, db)
    return ServiceAgreementRequestDto.model_validate(sa, from_attributes=True)


@router.put(
    "/service-agreement-requests/{sa_id}",
    response_model=ServiceAgreementRequestDto,
)
async def update_sa_request(
    sa_id: int,
    data: ServiceAgreementRequestUpdateDto,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Обновить SA заявку (поля + опционально status)."""
    sa, client = await _load_sa_with_rights(sa_id, current_user, db)

    old_status = sa.status
    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if value is not None:
            setattr(sa, field, value)

    sa.updated_at = datetime.utcnow()

    if data.status == ServiceAgreementStatus.SUBMITTED.value and old_status != ServiceAgreementStatus.SUBMITTED.value:
        sa.submitted_at = datetime.utcnow()
        client.service_agreement_status = ServiceAgreementStatus.SUBMITTED.value

    if data.status and data.status != old_status:
        db.add(ServiceAgreementStatusHistory(
            sa_id=sa.sa_id,
            old_status=old_status,
            new_status=data.status,
            changed_by=current_user.user_id,
            changed_at=datetime.utcnow(),
        ))

    await db.commit()
    await db.refresh(sa)
    return ServiceAgreementRequestDto.model_validate(sa, from_attributes=True)


# ----------------------------------------------------------------------
# WORKFLOW endpoints
# ----------------------------------------------------------------------

@router.post(
    "/service-agreement-requests/{sa_id}/generate",
    response_model=ServiceAgreementRequestDto,
)
async def generate_sa(
    sa_id: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
    s3: S3Client = Depends(get_s3_client),
):
    """Сгенерировать DOCX из шаблона и сохранить в S3."""
    sa, client = await _load_sa_with_rights(sa_id, current_user, db)

    allowed = {
        ServiceAgreementStatus.DRAFT.value,
        ServiceAgreementStatus.GENERATED.value,
        ServiceAgreementStatus.NOT_STARTED.value,
        ServiceAgreementStatus.REJECTED.value,
    }
    if sa.status not in allowed:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot generate SA in status '{sa.status}'. Allowed: {sorted(allowed)}",
        )

    missing = [
        f for f in ("company_name", "country", "address", "signatory_name", "effective_date")
        if not getattr(sa, f)
    ]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Missing required fields for generation: {missing}",
        )

    fields = _build_generator_fields(sa)
    docx_bytes = service_agreement_generator.generate(fields)

    s3_key = f"service-agreement/{client.client_id}/{sa.sa_id}/generated/SA_{sa.sa_id}.docx"
    await s3.upload_file(
        file=BytesIO(docx_bytes),
        key=s3_key,
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    presigned = await s3.generate_presigned_url(key=s3_key, expiration=SA_PRESIGNED_URL_TTL)

    old_status = sa.status
    sa.generated_file_key = s3_key
    sa.generated_file_url = presigned
    sa.generated_file_name = f"SA_{sa.sa_id}.docx"
    sa.generated_file_size = len(docx_bytes)
    sa.template_code = DEFAULT_SA_TEMPLATE_CODE
    sa.status = ServiceAgreementStatus.GENERATED.value
    sa.updated_at = datetime.utcnow()

    if old_status != ServiceAgreementStatus.GENERATED.value:
        db.add(ServiceAgreementStatusHistory(
            sa_id=sa.sa_id,
            old_status=old_status,
            new_status=ServiceAgreementStatus.GENERATED.value,
            changed_by=current_user.user_id,
            changed_at=datetime.utcnow(),
        ))

    _audit_sa(
        db, sa, "SA_GENERATED", current_user,
        old_value={"status": old_status},
        new_value={"status": ServiceAgreementStatus.GENERATED.value, "file_key": s3_key, "size": len(docx_bytes)},
    )

    await db.commit()
    await db.refresh(sa)
    return ServiceAgreementRequestDto.model_validate(sa, from_attributes=True)


@router.post(
    "/service-agreement-requests/{sa_id}/upload-signed",
    response_model=ServiceAgreementRequestDto,
)
async def upload_signed_sa(
    sa_id: int,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
    s3: S3Client = Depends(get_s3_client),
):
    """Загрузить подписанный клиентом SA (PDF/DOCX) в S3."""
    sa, client = await _load_sa_with_rights(sa_id, current_user, db)

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
    s3_key = f"service-agreement/{client.client_id}/{sa.sa_id}/signed/SIGNED_{ts}_{file.filename}"

    content_type, _ = mimetypes.guess_type(file.filename)
    await s3.upload_file(
        file=BytesIO(content),
        key=s3_key,
        content_type=content_type or "application/octet-stream",
    )
    presigned = await s3.generate_presigned_url(key=s3_key, expiration=SA_PRESIGNED_URL_TTL)

    old_status = sa.status
    sa.signed_file_key = s3_key
    sa.signed_file_url = presigned
    sa.signed_file_name = file.filename
    sa.signed_file_size = len(content)
    sa.status = ServiceAgreementStatus.SIGNED_UPLOADED.value
    sa.updated_at = datetime.utcnow()

    if old_status != ServiceAgreementStatus.SIGNED_UPLOADED.value:
        db.add(ServiceAgreementStatusHistory(
            sa_id=sa.sa_id,
            old_status=old_status,
            new_status=ServiceAgreementStatus.SIGNED_UPLOADED.value,
            changed_by=current_user.user_id,
            changed_at=datetime.utcnow(),
        ))

    _audit_sa(
        db, sa, "SA_SIGNED_UPLOADED", current_user,
        old_value={"status": old_status},
        new_value={"status": ServiceAgreementStatus.SIGNED_UPLOADED.value, "file_key": s3_key, "size": len(content)},
    )

    await db.commit()
    await db.refresh(sa)
    return ServiceAgreementRequestDto.model_validate(sa, from_attributes=True)


@router.post(
    "/service-agreement-requests/{sa_id}/submit",
    response_model=ServiceAgreementRequestDto,
)
async def submit_sa(
    sa_id: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Финальная отправка SA на review Staff."""
    sa, client = await _load_sa_with_rights(sa_id, current_user, db)

    if sa.status != ServiceAgreementStatus.SIGNED_UPLOADED.value:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot submit SA in status '{sa.status}'. Required: 'signed_uploaded'",
        )

    old_status = sa.status
    now = datetime.utcnow()
    sa.status = ServiceAgreementStatus.SUBMITTED.value
    sa.submitted_at = now
    sa.updated_at = now
    client.service_agreement_status = ServiceAgreementStatus.SUBMITTED.value

    db.add(ServiceAgreementStatusHistory(
        sa_id=sa.sa_id,
        old_status=old_status,
        new_status=ServiceAgreementStatus.SUBMITTED.value,
        changed_by=current_user.user_id,
        changed_at=now,
    ))

    _audit_sa(
        db, sa, "SA_SUBMITTED", current_user,
        old_value={"status": old_status},
        new_value={"status": ServiceAgreementStatus.SUBMITTED.value, "submitted_at": now.isoformat()},
    )

    await db.commit()
    await db.refresh(sa)
    return ServiceAgreementRequestDto.model_validate(sa, from_attributes=True)


@router.post(
    "/service-agreement-requests/{sa_id}/decision",
    response_model=ServiceAgreementRequestDto,
)
async def staff_decision_sa(
    sa_id: int,
    decision: ServiceAgreementDecisionDto,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Staff/Admin: Accept или Reject SA (с обязательным comment для reject)."""
    sa, client = await _load_sa_with_rights(sa_id, current_user, db, require_staff=True)

    if sa.status != ServiceAgreementStatus.SUBMITTED.value:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot decide on SA in status '{sa.status}'. Required: 'submitted'",
        )
    if decision.status == ServiceAgreementStatus.REJECTED.value and not (decision.comment and decision.comment.strip()):
        raise HTTPException(status_code=400, detail="Comment is required for rejection")

    old_status = sa.status
    now = datetime.utcnow()
    sa.status = decision.status
    sa.updated_at = now
    client.service_agreement_status = decision.status

    db.add(ServiceAgreementStatusHistory(
        sa_id=sa.sa_id,
        old_status=old_status,
        new_status=decision.status,
        changed_by=current_user.user_id,
        changed_at=now,
        comment=decision.comment,
    ))

    action = "SA_ACCEPTED" if decision.status == ServiceAgreementStatus.ACCEPTED.value else "SA_REJECTED"
    _audit_sa(
        db, sa, action, current_user,
        old_value={"status": old_status},
        new_value={"status": decision.status, "comment": decision.comment, "decided_at": now.isoformat()},
    )

    await db.commit()
    await db.refresh(sa)
    return ServiceAgreementRequestDto.model_validate(sa, from_attributes=True)


@router.get("/service-agreement-requests/{sa_id}/history")
async def sa_history(
    sa_id: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """История смен статусов (для drawer'а Staff/Client UI)."""
    sa, _ = await _load_sa_with_rights(sa_id, current_user, db)
    result = await db.execute(
        select(ServiceAgreementStatusHistory)
        .where(ServiceAgreementStatusHistory.sa_id == sa.sa_id)
        .order_by(ServiceAgreementStatusHistory.changed_at.asc())
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


# ----------------------------------------------------------------------
# LEGACY endpoints (free-form generator).
# Сохранены для смягчения миграции фронтенда; не пишут SA в БД.
# Будут удалены отдельной задачей после полной миграции UI.
# ----------------------------------------------------------------------

CLIENT_FIELD_MAPPING: Dict[str, str] = {
    "client_name": "company_name",
    "client_reg_country": "country",
    "client_reg_number": "registration_number",
    "client_director": "signatory_name",
    "client_mail": "contact_email",
}


async def _populate_fields_from_client(
    fields: Dict,
    client_id: Optional[str],
    db: AsyncSession,
) -> Dict:
    if not client_id:
        return fields
    result = await db.execute(select(Client).where(Client.client_id == client_id))
    client = result.scalar_one_or_none()
    if not client:
        return fields
    merged = dict(fields)
    for model_attr, field_key in CLIENT_FIELD_MAPPING.items():
        if not merged.get(field_key):
            value = getattr(client, model_attr, None)
            if value is not None:
                merged[field_key] = str(value)
    return merged


class ServiceAgreementGenerateRequest(BaseModel):
    fields: Dict
    upload_to_s3: Optional[bool] = False


class ServiceAgreementGenerateResponse(BaseModel):
    file_url: str
    file_name: str
    file_size: int
    s3_key: str


@router.post(
    "/service-agreement/generate",
    summary="[LEGACY] Free-form Service Agreement generator (без SA-сущности в БД)",
    response_class=Response,
)
async def generate_service_agreement_legacy(
    request: ServiceAgreementGenerateRequest,
    client_id: Optional[str] = Query(None),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    fields = await _populate_fields_from_client(request.fields, client_id, db)
    try:
        docx_bytes = service_agreement_generator.generate(fields)
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Generation error: {e}")

    filename = "Service_Agreement_GAN.docx"
    return Response(
        content=docx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Access-Control-Expose-Headers": "Content-Disposition",
        },
    )


@router.post(
    "/service-agreement/generate-and-upload",
    response_model=ServiceAgreementGenerateResponse,
    summary="[LEGACY] Admin-only: generate + S3 upload (без SA-сущности в БД)",
)
async def generate_and_upload_legacy(
    request: ServiceAgreementGenerateRequest,
    client_id: Optional[str] = Query(None),
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    s3: S3Client = Depends(get_s3_client),
):
    fields = await _populate_fields_from_client(request.fields, client_id, db)
    try:
        docx_bytes = service_agreement_generator.generate(fields)
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Generation error: {e}")

    cid = client_id
    if not cid:
        result = await db.execute(
            select(Client.client_id).where(Client.user_id == current_user.user_id)
        )
        row = result.first()
        cid = row[0] if row else current_user.user_id

    unique_id = uuid.uuid4().hex[:8]
    filename = f"Service_Agreement_GAN_{unique_id}.docx"
    s3_key = f"service-agreement/{cid}/{filename}"

    await s3.upload_file(
        file=BytesIO(docx_bytes),
        key=s3_key,
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    # ТЗ Sec 5.5.2: TTL=900 (legacy endpoint оставлен только для админ-операций
    # с мастер-документом, презентация для регулятора отдаётся именно через
    # него — короткий TTL даёт время скачать, без 24h-окна).
    file_url = await s3.generate_presigned_url(key=s3_key, expiration=SA_PRESIGNED_URL_TTL)
    return ServiceAgreementGenerateResponse(
        file_url=file_url,
        file_name=filename,
        file_size=len(docx_bytes),
        s3_key=s3_key,
    )
