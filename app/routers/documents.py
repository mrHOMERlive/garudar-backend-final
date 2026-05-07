"""
Роутер для управления документами POBO
Строгий контроль доступа, последовательности и immutability
"""
from datetime import datetime
from typing import Optional
import json
import mimetypes
from io import BytesIO

from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db import get_db
from app.models import User, OrderPobo, OrderDocument, Client, Role, AuditLog, AppSetting
from app.schemas import OrderDocumentDto, DocumentUploadResponse, PresignedUrlResponse, ErrorResponse
from app.deps import get_current_active_user
from app.enums import DocumentType, DocumentSequence, AllowedDocTypes
from app.s3_client import get_s3_client, generate_s3_key, S3Client
from app.file_validators import validate_pdf_not_encrypted

router = APIRouter(tags=["Documents"])


# ========== Helper Functions ==========

def is_staff_or_admin(user: User) -> bool:
    """Проверка является ли пользователь staff/admin"""
    return user.role in [Role.ADMIN.value, Role.STAFF.value] if hasattr(Role, 'STAFF') else user.role == Role.ADMIN.value


async def get_max_upload_size_mb(db: AsyncSession) -> int:
    """Получить максимальный размер файла из настроек"""
    result = await db.execute(
        select(AppSetting).where(AppSetting.key == "max_upload_mb")
    )
    setting = result.scalar_one_or_none()
    return int(setting.value) if setting else 50  # По умолчанию 50 МБ


async def check_order_access(
    order_id: str,
    user: User,
    db: AsyncSession,
) -> OrderPobo:
    """
    Проверить доступ пользователя к заказу
    
    - STAFF/ADMIN: доступ ко всем заказам
    - CLIENT: только к своим заказам
    
    Raises:
        HTTPException: 404 если заказ не найден, 403 если нет доступа
    """
    order_result = await db.execute(
        select(OrderPobo).where(OrderPobo.order_id == order_id)
    )
    order = order_result.scalar_one_or_none()
    
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    # STAFF/ADMIN имеют доступ ко всем заказам
    if is_staff_or_admin(user):
        return order
    
    # CLIENT только к своим заказам
    client_result = await db.execute(
        select(Client).where(Client.user_id == user.user_id)
    )
    client = client_result.scalar_one_or_none()
    
    if not client or order.client_id != client.client_id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    return order


def check_doc_type_permission(doc_type: str, user: User):
    """
    Проверить может ли пользователь загружать данный тип документа
    
    Raises:
        HTTPException: 403 если нет прав
    """
    try:
        doc_type_enum = DocumentType(doc_type)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid doc_type: {doc_type}")
    
    if is_staff_or_admin(user):
        # STAFF может загружать все unsigned, signed_staff, mt103, transaction_status
        allowed = AllowedDocTypes.STAFF_UPLOAD
    else:
        # CLIENT может загружать только определенные типы
        allowed = AllowedDocTypes.CLIENT_UPLOAD
    
    if doc_type_enum not in allowed:
        raise HTTPException(
            status_code=403,
            detail=f"You are not allowed to upload {doc_type} documents"
        )


async def check_final_document(
    order_id: str,
    doc_type: str,
    replace_reason: Optional[str],
    user: User,
    db: AsyncSession,
):
    """
    Проверить попытку замены FINAL документа
    
    FINAL документы (*_signed_staff):
    - immutable (нельзя заменить без cause)
    - только STAFF/ADMIN может заменить
    - обязателен replace_reason
    
    Raises:
        HTTPException: 409 если нарушены правила
    """
    # Проверяем существует ли уже документ данного типа
    result = await db.execute(
        select(OrderDocument).where(
            OrderDocument.order_id == order_id,
            OrderDocument.doc_type == doc_type
        )
    )
    existing_doc = result.scalar_one_or_none()
    
    if not existing_doc:
        return  # Новый документ, всё ок
    
    # Документ существует - это замена
    try:
        doc_type_enum = DocumentType(doc_type)
    except ValueError:
        return
    
    # Если это FINAL документ
    if DocumentSequence.is_final(doc_type_enum):
        if not is_staff_or_admin(user):
            raise HTTPException(
                status_code=409,
                detail=f"Cannot replace FINAL document {doc_type}: only staff allowed"
            )
        
        if not replace_reason or not replace_reason.strip():
            raise HTTPException(
                status_code=409,
                detail=f"Cannot replace FINAL document {doc_type}: replace_reason required"
            )


def validate_file_format(filename: str) -> str:
    """
    Валидация формата файла
    
    Разрешены: PDF, DOC, DOCX, XLS, XLSX, ZIP
    
    Returns:
        Content-Type
    
    Raises:
        HTTPException: 400 если формат не разрешен
    """
    allowed_extensions = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".zip"}
    ext = None
    
    for allowed_ext in allowed_extensions:
        if filename.lower().endswith(allowed_ext):
            ext = allowed_ext
            break
    
    if not ext:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file format. Allowed: {', '.join(allowed_extensions)}"
        )
    
    content_type, _ = mimetypes.guess_type(filename)
    return content_type or "application/octet-stream"


async def validate_file_size(file: UploadFile, max_mb: int):
    """
    Валидация размера файла
    
    Raises:
        HTTPException: 400 если размер превышает лимит
    """
    file.file.seek(0, 2)  # Переместить в конец
    size = file.file.tell()
    file.file.seek(0)  # Вернуть в начало
    
    max_bytes = max_mb * 1024 * 1024
    
    if size > max_bytes:
        raise HTTPException(
            status_code=400,
            detail=f"File size {size} bytes exceeds limit {max_bytes} bytes ({max_mb} MB)"
        )
    
    return size


async def log_document_audit(
    db: AsyncSession,
    doc_id: int,
    action: str,
    old_file_url: Optional[str],
    new_file_url: str,
    user_id: str,
    replace_reason: Optional[str] = None,
):
    """
    Записать аудит операции с документом
    
    КРИТИЧНО: Без аудита регулятор не примет систему
    """
    old_value = None
    if old_file_url:
        old_value = json.dumps({"file_url": old_file_url}, ensure_ascii=False)
    
    new_value_dict = {"file_url": new_file_url}
    if replace_reason:
        new_value_dict["replace_reason"] = replace_reason
    new_value = json.dumps(new_value_dict, ensure_ascii=False)
    
    audit_entry = AuditLog(
        entity="order_documents",
        entity_id=str(doc_id),
        action=action,
        old_value=old_value,
        new_value=new_value,
        created_by=user_id,
        created_at=datetime.utcnow(),
    )
    db.add(audit_entry)


# ========== API Endpoints ==========

@router.post(
    "/orders/{order_id}/documents",
    response_model=DocumentUploadResponse,
    summary="Загрузить документ для заказа POBO",
)
async def upload_document(
    order_id: str,
    file: UploadFile = File(...),
    doc_type: str = Form(...),
    replace_reason: Optional[str] = Form(None),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
    s3: S3Client = Depends(get_s3_client),
):
    """
    Загрузить документ в S3 и создать запись в БД
    
    **Правила доступа:**
    - CLIENT может загружать: invoice, payment_proof, word_order_signed_client, act_report_signed_client, other
    - STAFF/ADMIN может загружать: все типы unsigned, signed_staff, mt103, transaction_status, sales_contract, other
    
    **FINAL документы (*_signed_staff):**
    - Immutable
    - Замена только STAFF с обязательным replace_reason
    - Все замены фиксируются в audit_log

    Документы можно загружать в любом порядке (sequence-валидация
    намеренно не применяется, бизнес-требование).
    """
    # 1. Проверить доступ к заказу
    order = await check_order_access(order_id, current_user, db)

    # 2. Проверить права на тип документа
    check_doc_type_permission(doc_type, current_user)

    # 3. Проверить замену FINAL документов
    await check_final_document(order_id, doc_type, replace_reason, current_user, db)

    # 4. Валидация файла
    max_mb = await get_max_upload_size_mb(db)
    content_type = validate_file_format(file.filename)
    file_size = await validate_file_size(file, max_mb)

    # Читаем bytes один раз — используем и для проверки шифрования,
    # и для S3-загрузки. Раньше бы проверка читала из UploadFile со
    # seek(0), теперь работаем с bytes уже из памяти.
    file_content = await file.read()
    await validate_pdf_not_encrypted(file_content, file.filename)

    # 5. Генерировать S3 ключ
    s3_key = generate_s3_key(order_id, doc_type, file.filename)

    # 6. Загрузить в S3
    await s3.upload_file(
        file=BytesIO(file_content),
        key=s3_key,
        content_type=content_type,
    )

    # 7. Проверить существующий документ для замены
    existing_doc_result = await db.execute(
        select(OrderDocument).where(
            OrderDocument.order_id == order_id,
            OrderDocument.doc_type == doc_type
        )
    )
    existing_doc = existing_doc_result.scalar_one_or_none()
    
    old_file_url = None
    action = "UPLOAD"
    
    if existing_doc:
        # Замена существующего документа
        old_file_url = existing_doc.file_url
        action = "REPLACE"
        
        existing_doc.file_url = s3_key
        existing_doc.file_name = file.filename
        existing_doc.file_size = file_size
        existing_doc.uploaded_by = current_user.user_id
        existing_doc.uploaded_at = datetime.utcnow()
        
        doc_id = existing_doc.doc_id
    else:
        # Новый документ
        new_doc = OrderDocument(
            order_id=order_id,
            doc_type=doc_type,
            file_url=s3_key,
            file_name=file.filename,
            file_size=file_size,
            uploaded_by=current_user.user_id,
            uploaded_at=datetime.utcnow(),
        )
        db.add(new_doc)
        await db.flush()
        doc_id = new_doc.doc_id
    
    # 8. ОБЯЗАТЕЛЬНЫЙ АУДИТ
    await log_document_audit(
        db=db,
        doc_id=doc_id,
        action=action,
        old_file_url=old_file_url,
        new_file_url=s3_key,
        user_id=current_user.user_id,
        replace_reason=replace_reason,
    )
    
    await db.commit()
    
    message = "Document uploaded successfully"
    if action == "REPLACE":
        message = f"Document replaced successfully. Reason: {replace_reason or 'N/A'}"
    
    return DocumentUploadResponse(
        doc_id=doc_id,
        doc_type=doc_type,
        file_name=file.filename,
        file_size=file_size,
        uploaded_at=datetime.utcnow(),
        message=message,
    )


@router.get(
    "/orders/{order_id}/documents",
    response_model=list[OrderDocumentDto],
    summary="Получить список документов заказа",
)
async def list_documents(
    order_id: str,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Получить список всех документов для заказа
    
    **Возвращает метаданные без file_url (S3 ключей)**
    
    - CLIENT: только документы своих заказов
    - STAFF/ADMIN: документы любых заказов
    """
    # Проверить доступ к заказу
    await check_order_access(order_id, current_user, db)
    
    # Получить все документы заказа
    result = await db.execute(
        select(OrderDocument)
        .where(OrderDocument.order_id == order_id)
        .order_by(OrderDocument.uploaded_at.desc())
    )
    documents = result.scalars().all()
    
    return [OrderDocumentDto.model_validate(doc, from_attributes=True) for doc in documents]


@router.get(
    "/orders/{order_id}/documents/{doc_id}",
    response_model=PresignedUrlResponse,
    summary="Получить presigned URL для скачивания документа",
)
async def download_document(
    order_id: str,
    doc_id: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
    s3: S3Client = Depends(get_s3_client),
):
    """
    Получить временный URL для скачивания документа
    
    **Безопасность:**
    - Проверка прав доступа к заказу
    - Presigned URL с TTL 15 минут (900 секунд)
    - Не отдаем прямые S3 URL
    
    **Возвращает:**
    - presigned_url: временный URL для скачивания
    - expires_in: время жизни URL в секундах
    - file_name: имя файла
    """
    # Проверить доступ к заказу
    await check_order_access(order_id, current_user, db)
    
    # Получить документ
    doc_result = await db.execute(
        select(OrderDocument).where(
            OrderDocument.doc_id == doc_id,
            OrderDocument.order_id == order_id
        )
    )
    document = doc_result.scalar_one_or_none()
    
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    
    # Генерировать presigned URL
    expiration = 900  # 15 минут
    presigned_url = await s3.generate_presigned_url(
        key=document.file_url,
        expiration=expiration,
    )
    
    return PresignedUrlResponse(
        presigned_url=presigned_url,
        expires_in=expiration,
        file_name=document.file_name,
        message="Presigned URL generated successfully. Valid for 15 minutes.",
    )
