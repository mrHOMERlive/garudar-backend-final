"""
S3 клиент для MinIO
"""
from typing import BinaryIO
import aioboto3
import os
import re
from botocore.exceptions import ClientError
from app.config import settings


def sanitize_filename(filename: str) -> str:
    """Убрать path traversal и спецсимволы из имени файла"""
    filename = os.path.basename(filename)
    filename = re.sub(r'[^\w\s\-.]', '_', filename)
    return filename or 'unnamed'


class S3Client:
    """Асинхронный S3 клиент для работы с MinIO"""
    
    def __init__(self):
        self.endpoint_url = settings.S3_ENDPOINT_URL
        self.public_endpoint_url = settings.S3_PUBLIC_ENDPOINT_URL
        self.access_key = settings.S3_ACCESS_KEY
        self.secret_key = settings.S3_SECRET_KEY
        self.bucket_name = settings.S3_BUCKET_NAME
        self.region = settings.S3_REGION
        
        self.session = aioboto3.Session(
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key,
        )
    
    async def ensure_bucket_exists(self):
        """Создать bucket если не существует"""
        async with self.session.client(
            "s3",
            endpoint_url=self.endpoint_url,
            region_name=self.region,
        ) as s3:
            try:
                await s3.head_bucket(Bucket=self.bucket_name)
            except ClientError:
                await s3.create_bucket(Bucket=self.bucket_name)
    
    async def upload_file(
        self,
        file: BinaryIO,
        key: str,
        content_type: str,
    ) -> str:
        """
        Загрузить файл в S3
        
        Args:
            file: Бинарный файл
            key: S3 ключ (путь)
            content_type: MIME тип
        
        Returns:
            S3 key загруженного файла
        """
        await self.ensure_bucket_exists()
        
        async with self.session.client(
            "s3",
            endpoint_url=self.endpoint_url,
            region_name=self.region,
        ) as s3:
            await s3.put_object(
                Bucket=self.bucket_name,
                Key=key,
                Body=file,
                ContentType=content_type,
            )
            return key
    
    async def generate_presigned_url(
        self,
        key: str,
        expiration: int = 900,
    ) -> str:
        """
        Генерировать presigned URL для скачивания
        
        Args:
            key: S3 ключ
            expiration: Время жизни URL в секундах (по умолчанию 15 минут)
        
        Returns:
            Presigned URL
        """
        async with self.session.client(
            "s3",
            endpoint_url=self.public_endpoint_url,
            region_name=self.region,
        ) as s3:
            url = await s3.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.bucket_name, "Key": key},
                ExpiresIn=expiration,
            )
            return url
    
    async def delete_file(self, key: str):
        """Удалить файл из S3"""
        async with self.session.client(
            "s3",
            endpoint_url=self.endpoint_url,
            region_name=self.region,
        ) as s3:
            await s3.delete_object(
                Bucket=self.bucket_name,
                Key=key,
            )
    
    async def file_exists(self, key: str) -> bool:
        """Проверить существование файла"""
        async with self.session.client(
            "s3",
            endpoint_url=self.endpoint_url,
            region_name=self.region,
        ) as s3:
            try:
                await s3.head_object(Bucket=self.bucket_name, Key=key)
                return True
            except ClientError:
                return False


# Singleton инстанс
s3_client = S3Client()


def get_s3_client() -> S3Client:
    """Dependency для получения S3 клиента"""
    return s3_client


def generate_s3_key(order_id: str, doc_type: str, filename: str) -> str:
    """
    Генерировать детерминированный S3 ключ

    Format: orders/{order_id}/{doc_type}/{filename}
    """
    return f"orders/{order_id}/{doc_type}/{sanitize_filename(filename)}"


def generate_kyc_s3_key(client_id: str, doc_type: str, filename: str) -> str:
    """
    Генерировать уникальный S3 ключ для KYC документов

    Format: kyc/{client_id}/{doc_type}/{YYYYMMDDHHMMSSffffff}_{filename}

    Префикс из UTC-времени гарантирует уникальность ключа при загрузке
    нескольких файлов с одинаковым именем (multi-file per doc_type).
    """
    from datetime import datetime
    prefix = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
    return f"kyc/{client_id}/{doc_type}/{prefix}_{sanitize_filename(filename)}"


def generate_legal_s3_key(filename: str) -> str:
    """
    Генерировать S3 ключ для легальных документов
    
    Format: legal/{filename}
    """
    return f"legal/{sanitize_filename(filename)}"


async def upload_legal_documents_on_startup():
    """
    Загрузить легальные документы в S3 при старте приложения
    Только если они еще не существуют
    """
    import os
    from pathlib import Path
    
    template_dir = Path(__file__).parent / "template"
    legal_docs = {
        "privacy-policy- PT GAN.pdf": "application/pdf",
        "provacy_bahasa.pdf": "application/pdf",
        "T&C_order.pdf": "application/pdf",
        "Obligations Management Password and User ID PT GAN.pdf": "application/pdf",
    }
    
    await s3_client.ensure_bucket_exists()
    
    for filename, content_type in legal_docs.items():
        filepath = template_dir / filename
        s3_key = generate_legal_s3_key(filename)
        
        if not filepath.exists():
            print(f"Warning: Legal document not found: {filepath}")
            continue
        
        if await s3_client.file_exists(s3_key):
            print(f"Legal document already exists in S3: {s3_key}")
            continue
        
        try:
            with open(filepath, "rb") as f:
                await s3_client.upload_file(f, s3_key, content_type)
            print(f"Successfully uploaded legal document: {s3_key}")
        except Exception as e:
            print(f"Failed to upload legal document {filename}: {e}")
