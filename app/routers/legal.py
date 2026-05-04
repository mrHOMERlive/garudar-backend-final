from fastapi import APIRouter, HTTPException, Depends, Query
from app.s3_client import get_s3_client, S3Client, generate_legal_s3_key

router = APIRouter(prefix="/api/v1/legal", tags=["Legal Documents"])


@router.get("/privacy-policy")
async def get_privacy_policy(
    language: str = Query(default="en", description="Language code: 'en' or 'id'"),
    s3_client: S3Client = Depends(get_s3_client)
):
    """
    Получить ссылку на Privacy Policy
    
    Args:
        language: Код языка ('en' - английский, 'id' - индонезийский/bahasa)
    
    Returns:
        JSON с presigned URL для скачивания документа
    """
    if language == "id":
        filename = "provacy_bahasa.pdf"
    elif language == "en":
        filename = "privacy-policy- PT GAN.pdf"
    else:
        raise HTTPException(
            status_code=400, 
            detail=f"Unsupported language: {language}. Use 'en' or 'id'"
        )
    
    key = generate_legal_s3_key(filename)
    
    if not await s3_client.file_exists(key):
        raise HTTPException(
            status_code=404, 
            detail=f"Privacy Policy document not found for language: {language}"
        )
    
    url = await s3_client.generate_presigned_url(key, expiration=86400)
    return {
        "url": url,
        "language": language,
        "filename": filename
    }


@router.get("/obligations")
async def get_obligations(
    s3_client: S3Client = Depends(get_s3_client)
):
    """
    Получить ссылку на документ Obligations Management Password and User ID
    """
    filename = "Obligations Management Password and User ID PT GAN.pdf"
    key = generate_legal_s3_key(filename)

    if not await s3_client.file_exists(key):
        raise HTTPException(
            status_code=404,
            detail="Obligations document not found"
        )

    url = await s3_client.generate_presigned_url(key, expiration=86400)
    return {
        "url": url,
        "filename": filename
    }


@router.get("/terms-and-conditions")
async def get_terms_and_conditions(
    s3_client: S3Client = Depends(get_s3_client)
):
    """
    Получить ссылку на Terms & Conditions
    
    Returns:
        JSON с presigned URL для скачивания документа
    """
    filename = "T&C_order.pdf"
    key = generate_legal_s3_key(filename)
    
    if not await s3_client.file_exists(key):
        raise HTTPException(
            status_code=404, 
            detail="Terms & Conditions document not found"
        )
    
    url = await s3_client.generate_presigned_url(key, expiration=86400)
    return {
        "url": url,
        "filename": filename
    }
