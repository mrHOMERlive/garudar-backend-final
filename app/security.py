from datetime import datetime, timedelta
from jose import JWTError, jwt
import bcrypt
import secrets
import hashlib
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.config import settings


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(
            plain_password.encode('utf-8'),
            hashed_password.encode('utf-8')
        )
    except Exception:
        return False


def get_password_hash(password: str) -> str:
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')


def create_access_token(username: str, role: str) -> str:
    expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode = {
        "sub": username,
        "role": role,
        "exp": expire,
        "type": "access"  # Тип токена для дополнительной проверки
    }
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt


def create_refresh_token() -> str:
    """Создать случайный refresh token (64 байта в URL-safe base64)"""
    return secrets.token_urlsafe(64)


def hash_token(token: str) -> str:
    """Хешировать токен для безопасного хранения в БД"""
    return hashlib.sha256(token.encode()).hexdigest()


async def save_refresh_token(db: AsyncSession, user_id: str, token: str) -> None:
    """Сохранить refresh token в БД"""
    from app.models import RefreshToken
    
    token_hash = hash_token(token)
    expires_at = datetime.utcnow() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    
    refresh_token = RefreshToken(
        user_id=user_id,
        token_hash=token_hash,
        expires_at=expires_at,
        created_at=datetime.utcnow()
    )
    
    db.add(refresh_token)
    await db.commit()


async def verify_refresh_token(db: AsyncSession, token: str) -> Optional[str]:
    """Проверить refresh token и вернуть user_id если валиден"""
    from app.models import RefreshToken
    
    token_hash = hash_token(token)
    
    result = await db.execute(
        select(RefreshToken)
        .where(RefreshToken.token_hash == token_hash)
        .where(RefreshToken.revoked == False)
        .where(RefreshToken.expires_at > datetime.utcnow())
    )
    
    refresh_token = result.scalar_one_or_none()
    
    if not refresh_token:
        return None
    
    return refresh_token.user_id


async def revoke_refresh_token(db: AsyncSession, token: str) -> None:
    """Отозвать refresh token"""
    from app.models import RefreshToken
    
    token_hash = hash_token(token)
    
    result = await db.execute(
        select(RefreshToken).where(RefreshToken.token_hash == token_hash)
    )
    
    refresh_token = result.scalar_one_or_none()
    
    if refresh_token:
        refresh_token.revoked = True
        refresh_token.revoked_at = datetime.utcnow()
        await db.commit()


async def revoke_all_user_tokens(db: AsyncSession, user_id: str) -> None:
    """Отозвать все refresh токены пользователя (например, при смене пароля)"""
    from app.models import RefreshToken
    from sqlalchemy import update
    
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id)
        .where(RefreshToken.revoked == False)
        .values(revoked=True, revoked_at=datetime.utcnow())
    )
    await db.commit()


def decode_access_token(token: str) -> dict | None:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        return payload
    except JWTError:
        return None
