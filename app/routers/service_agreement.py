import uuid
from io import BytesIO
from typing import Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db import get_db
from app.deps import get_current_active_user, require_admin
from app.models import User, Client
from app.s3_client import get_s3_client, S3Client
from app.services import service_agreement_generator

router = APIRouter(tags=["Service Agreement"])

# Маппинг полей модели Client -> ключей полей в шаблоне (FIELD_MAPPING values).
# Используется для автозаполнения данных клиента при генерации документа.
CLIENT_FIELD_MAPPING: Dict[str, str] = {
    "client_name": "company_name",
    "client_reg_country": "country",
    "client_reg_number": "registration_number",
    "client_director": "signatory_name",
    "client_mail": "email",
}


async def _populate_fields_from_client(
    fields: Dict,
    client_id: Optional[str],
    db: AsyncSession,
) -> Dict:
    """
    Если передан client_id, загружает данные клиента из БД
    и дополняет fields значениями из модели Client.
    Заполняет только пустые/отсутствующие поля — явно переданные не перезаписываются.
    """
    if not client_id:
        return fields

    result = await db.execute(
        select(Client).where(Client.client_id == client_id)
    )
    client = result.scalar_one_or_none()

    if not client:
        return fields

    merged = dict(fields)
    for model_attr, field_key in CLIENT_FIELD_MAPPING.items():
        # Заполняем только если поле отсутствует или пустое
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
    summary="Сгенерировать Service Agreement и скачать DOCX",
    response_class=Response,
)
async def generate_service_agreement(
    request: ServiceAgreementGenerateRequest,
    client_id: Optional[str] = Query(None, description="ID клиента"),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Генерирует заполненный Service Agreement из шаблона и возвращает DOCX файл.

    - Если `upload_to_s3=false` (по умолчанию) — возвращает файл напрямую для скачивания.
    - Если `upload_to_s3=true` — загружает в S3 и возвращает JSON с presigned URL.
    - Если передан `client_id`, данные клиента автоматически подставляются
      в пустые поля `fields`.

    Поля `fields` должны соответствовать плейсхолдерам в шаблоне (см. FIELD_MAPPING
    в `app/services/service_agreement_generator.py`).
    """
    fields = await _populate_fields_from_client(request.fields, client_id, db)

    try:
        docx_bytes = service_agreement_generator.generate(fields)
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка генерации документа: {str(e)}",
        )

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
    summary="Сгенерировать Service Agreement, загрузить в S3 и вернуть URL",
)
async def generate_and_upload_service_agreement(
    request: ServiceAgreementGenerateRequest,
    client_id: Optional[str] = Query(None, description="ID клиента"),
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    s3: S3Client = Depends(get_s3_client),
):
    """
    Генерирует Service Agreement, сохраняет в S3 и возвращает presigned URL.
    Только для ADMIN/STAFF — используется для создания мастер-документа,
    который затем прикрепляется к бейджу клиента через `document_url`.

    Если передан `client_id`, данные клиента автоматически подставляются
    в пустые поля `fields`.
    """
    fields = await _populate_fields_from_client(request.fields, client_id, db)

    try:
        docx_bytes = service_agreement_generator.generate(fields)
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка генерации документа: {str(e)}",
        )

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

    file_url = await s3.generate_presigned_url(key=s3_key, expiration=86400)

    return ServiceAgreementGenerateResponse(
        file_url=file_url,
        file_name=filename,
        file_size=len(docx_bytes),
        s3_key=s3_key,
    )
