from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.responses import JSONResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db import get_db
from app.models import User, Role
from app.schemas import UserDto, ErrorResponse
from app.deps import get_current_active_user
from app.security import get_password_hash

router = APIRouter(tags=["Users"])


def user_to_dto(user: User) -> dict:
    return {
        "user_id": user.user_id,
        "username": user.username,
        "password": None,
        "email": user.email,
        "role": user.role,
        "status": user.is_active,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "updated_at": user.updated_at.isoformat() if user.updated_at else None,
        "terms_accepted": user.terms_accepted,
        "terms_accepted_at": user.terms_accepted_at.isoformat() if user.terms_accepted_at else None,
    }


def is_admin(user: User) -> bool:
    return user.role == Role.ADMIN.value


@router.get(
    "",
    response_model=list[UserDto] | UserDto,
    responses={
        400: {"model": ErrorResponse, "description": "Неверный запрос"},
        401: {"model": ErrorResponse, "description": "Не авторизован"},
        403: {"model": ErrorResponse, "description": "Нет доступа"},
    },
    summary="Получить список пользователей или одного по username",
)
async def get_users(
    username: Optional[str] = Query(None, description="Имя пользователя для поиска"),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    if is_admin(current_user):
        result = await db.execute(select(User))
        users = result.scalars().all()
        return [user_to_dto(u) for u in users]
    else:
        if not username or not username.strip():
            return JSONResponse(status_code=400, content={"error": "Username required"})
        result = await db.execute(select(User).where(User.username == username.strip()))
        user = result.scalar_one_or_none()
        if user is None:
            return JSONResponse(status_code=404, content={"error": "User not found"})
        return {"user_id": user.user_id, "username": user.username}


@router.post(
    "",
    response_model=UserDto,
    responses={
        403: {"model": ErrorResponse, "description": "Нет доступа"},
        409: {"model": ErrorResponse, "description": "Username уже существует"},
    },
    summary="Создать нового пользователя (только админ)",
)
async def create_user(
    user_dto: UserDto,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    if not is_admin(current_user):
        return JSONResponse(status_code=403, content={"error": "Admin access required"})
    
    result = await db.execute(select(User).where(User.username == user_dto.username))
    if result.scalar_one_or_none():
        return JSONResponse(status_code=409, content={"error": "Username already exists"})
    
    new_user = User(
        username=user_dto.username,
        password=get_password_hash(user_dto.password) if user_dto.password else "",
        role=user_dto.role.value if user_dto.role else Role.USER.value,
        is_active=user_dto.status if user_dto.status is not None else True,
    )
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)
    return user_to_dto(new_user)


@router.get(
    "/me",
    response_model=UserDto,
    responses={
        401: {"model": ErrorResponse, "description": "Не авторизован"},
    },
    summary="Получить информацию о текущем пользователе",
)
async def get_current_user_info(
    current_user: User = Depends(get_current_active_user),
):
    return user_to_dto(current_user)


@router.put(
    "/me",
    response_model=UserDto,
    responses={
        401: {"model": ErrorResponse, "description": "Не авторизован"},
    },
    summary="Обновить текущего пользователя",
)
async def update_current_user(
    user_dto: UserDto,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    if user_dto.username is not None:
        current_user.username = user_dto.username
    if user_dto.password is not None:
        current_user.password = get_password_hash(user_dto.password)
    
    await db.commit()
    await db.refresh(current_user)
    return user_to_dto(current_user)


@router.delete(
    "/me",
    status_code=204,
    responses={
        401: {"model": ErrorResponse, "description": "Не авторизован"},
    },
    summary="Удалить текущего пользователя",
)
async def delete_current_user(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    await db.delete(current_user)
    await db.commit()
    return Response(status_code=204)


@router.get(
    "/{user_id}",
    response_model=UserDto,
    responses={
        401: {"model": ErrorResponse, "description": "Не авторизован"},
        403: {"model": ErrorResponse, "description": "Нет доступа"},
        404: {"model": ErrorResponse, "description": "Пользователь не найден"},
    },
    summary="Получить пользователя по ID",
)
async def get_user_by_id(
    user_id: str,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.user_id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        return JSONResponse(status_code=404, content={"error": "User not found"})
    
    if not is_admin(current_user) and current_user.user_id != user_id:
        return JSONResponse(status_code=403, content={"error": "Access denied"})
    
    return user_to_dto(user)


@router.put(
    "/{user_id}",
    response_model=UserDto,
    responses={
        401: {"model": ErrorResponse, "description": "Не авторизован"},
        403: {"model": ErrorResponse, "description": "Нет доступа"},
        404: {"model": ErrorResponse, "description": "Пользователь не найден"},
    },
    summary="Обновить пользователя (только текущий или админ)",
)
async def update_user(
    user_id: str,
    user_dto: UserDto,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.user_id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        return JSONResponse(status_code=404, content={"error": "User not found"})
    
    admin = is_admin(current_user)
    if not admin and current_user.user_id != user_id:
        return JSONResponse(status_code=403, content={"error": "Access denied"})
    
    if admin:
        if user_dto.username is not None:
            user.username = user_dto.username
        if user_dto.password is not None:
            user.password = get_password_hash(user_dto.password)
        if user_dto.role is not None:
            user.role = user_dto.role.value
        if user_dto.status is not None:
            user.is_active = user_dto.status
    else:
        if user_dto.username is not None:
            user.username = user_dto.username
        if user_dto.password is not None:
            user.password = get_password_hash(user_dto.password)
    
    await db.commit()
    await db.refresh(user)
    return user_to_dto(user)


@router.delete(
    "/{user_id}",
    status_code=204,
    responses={
        401: {"model": ErrorResponse, "description": "Не авторизован"},
        403: {"model": ErrorResponse, "description": "Нет доступа"},
        404: {"model": ErrorResponse, "description": "Пользователь не найден"},
    },
    summary="Удалить пользователя (только админ)",
)
async def delete_user(
    user_id: str,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    if not is_admin(current_user):
        return JSONResponse(status_code=403, content={"error": "Admin access required"})
    
    result = await db.execute(select(User).where(User.user_id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        return JSONResponse(status_code=404, content={"error": "User not found"})
    
    await db.delete(user)
    await db.commit()
    return Response(status_code=204)
