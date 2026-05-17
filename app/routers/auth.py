from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db import get_db
from app.models import User
from app.schemas import LoginRequestDto, TokenResponse, ErrorResponse, RefreshTokenRequest, LogoutRequest
from app.security import (
    verify_password,
    create_access_token,
    create_refresh_token,
    save_refresh_token,
    verify_refresh_token,
    revoke_refresh_token
)
from app.config import settings
from app.deps import get_current_user
from app.rate_limit import limiter

router = APIRouter(tags=["Authentication"])

_SECURE_COOKIE = not settings.DEBUG


def _set_auth_cookies(response: JSONResponse, access_token: str, refresh_token: str):
    """Set HttpOnly cookies for access and refresh tokens."""
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        secure=_SECURE_COOKIE,
        samesite="lax",
        path="/api",
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=_SECURE_COOKIE,
        samesite="lax",
        path="/api/v1/auth",
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400,
    )


def _clear_auth_cookies(response: JSONResponse):
    """Remove auth cookies."""
    response.delete_cookie(key="access_token", path="/api")
    response.delete_cookie(key="refresh_token", path="/api/v1/auth")


@router.post(
    "/login",
    response_model=TokenResponse,
    responses={
        401: {"model": ErrorResponse, "description": "Неверные логин или пароль"},
        429: {"description": "Слишком много попыток входа"},
    },
    summary="Авторизация и получение JWT токена",
    description="Принимает логин и пароль, возвращает JWT токен при успешной аутентификации. Лимит: 5 попыток в минуту.",
)
@limiter.limit(settings.AUTH_LOGIN_RATE_LIMIT)
async def login(
    request: Request,
    dto: LoginRequestDto,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.username == dto.username))
    user = result.scalar_one_or_none()
    
    if user is None:
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"error": "Invalid credentials"},
        )
    
    if user.is_active is False:
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"error": "User disabled"},
        )
    
    if not verify_password(dto.password, user.password):
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"error": "Invalid credentials"},
        )
    
    # Создать оба токена
    access_token = create_access_token(username=user.username, role=user.role or "USER")
    refresh_token = create_refresh_token()

    # Сохранить refresh token в БД
    await save_refresh_token(db, user.user_id, refresh_token)

    response = JSONResponse(content={
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    })
    _set_auth_cookies(response, access_token, refresh_token)
    return response


@router.post(
    "/refresh",
    response_model=TokenResponse,
    responses={
        401: {"model": ErrorResponse, "description": "Неверный или истекший refresh token"},
        429: {"description": "Слишком много запросов"},
    },
    summary="Обновление токенов",
    description="Обновляет пару access/refresh токенов используя refresh token",
)
@limiter.limit(settings.AUTH_REFRESH_RATE_LIMIT)
async def refresh_tokens(
    request: Request,
    token_request: RefreshTokenRequest = None,
    db: AsyncSession = Depends(get_db),
):
    """
    Обновить токены используя refresh token.

    Реализует ротацию токенов: старый refresh token отзывается,
    выдается новая пара. Принимает refresh_token из cookie или JSON body.
    """
    # Try cookie first, then JSON body
    raw_refresh = request.cookies.get("refresh_token")
    if not raw_refresh and token_request:
        raw_refresh = token_request.refresh_token

    if not raw_refresh:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing refresh token"
        )

    # Проверить refresh token
    user_id = await verify_refresh_token(db, raw_refresh)

    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token"
        )

    # Получить пользователя
    result = await db.execute(select(User).where(User.user_id == user_id))
    user = result.scalar_one_or_none()

    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive"
        )

    # Ротация: отозвать старый refresh token
    await revoke_refresh_token(db, raw_refresh)

    # Создать новую пару токенов
    new_access_token = create_access_token(username=user.username, role=user.role or "USER")
    new_refresh_token = create_refresh_token()

    # Сохранить новый refresh token
    await save_refresh_token(db, user.user_id, new_refresh_token)

    response = JSONResponse(content={
        "access_token": new_access_token,
        "refresh_token": new_refresh_token,
        "token_type": "bearer",
        "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    })
    _set_auth_cookies(response, new_access_token, new_refresh_token)
    return response


@router.post(
    "/logout",
    responses={
        200: {"description": "Успешный выход"},
    },
    summary="Выход из системы",
    description="Отзывает refresh token и завершает сессию",
)
async def logout(
    request: Request,
    body: LogoutRequest = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Выйти из системы - отозвать refresh token.

    После этого refresh token больше нельзя использовать для обновления.
    Access token останется валидным до истечения.
    Принимает refresh_token из cookie или JSON body.
    """
    raw_refresh = request.cookies.get("refresh_token")
    if not raw_refresh and body:
        raw_refresh = body.refresh_token

    if raw_refresh:
        await revoke_refresh_token(db, raw_refresh)

    response = JSONResponse(content={"message": "Successfully logged out"})
    _clear_auth_cookies(response)
    return response


@router.post(
    "/accept-terms",
    summary="Принять условия использования",
    description="Фиксирует согласие пользователя с Obligations Management документом при первом входе",
)
async def accept_terms(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    current_user.terms_accepted = True
    current_user.terms_accepted_at = datetime.utcnow()
    await db.commit()
    await db.refresh(current_user)
    return {"ok": True, "terms_accepted": current_user.terms_accepted}
