from datetime import date
from typing import Optional
from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_
from app.db import get_db
from app.models import User, Entry, Role
from app.schemas import EntryDto, BulkEntryRequest, ErrorResponse
from app.deps import get_current_active_user

router = APIRouter(tags=["Entries"])


def is_admin(user: User) -> bool:
    return user.role == Role.ADMIN.value


def entry_to_dto(entry: Entry) -> dict:
    return {
        "id": entry.id,
        "sourceList": entry.source_list,
        "entryType": entry.entry_type,
        "fullName": entry.full_name,
        "name1": entry.name1,
        "name2": entry.name2,
        "name3": entry.name3,
        "name4": entry.name4,
        "tittle": entry.tittle,
        "jobTitle": entry.job_title,
        "dob": entry.dob,
        "pob": entry.pob,
        "alias": entry.alias,
        "nationality": entry.nationality,
        "passportNo": entry.passport_no,
        "identityNo": entry.identity_no,
        "address": entry.address,
        "additionalInfo": entry.additional_info,
        "loadDate": entry.load_date.isoformat() if entry.load_date else None,
    }


@router.get(
    "/search",
    response_model=list[EntryDto],
    summary="Поиск записей",
)
async def search_entries(
    query: Optional[str] = Query(None, description="Строка поиска"),
    entryType: int = Query(1, description="Тип записи. 1-Individual. 2-Corporate."),
    allSearch: str = Query("0", description="Искать по всем полям"),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
    skip: int = Query(0, ge=0, description="Пропустить N записей"),
    limit: int = Query(100, ge=1, le=500, description="Макс. кол-во записей"),
):
    if not query or not query.strip():
        return []
    
    q = query.strip()
    search_all = allSearch == "1"
    entry_type_value = "Individual" if entryType == 1 else "Entity"
    
    like_pattern = f"%{q}%"
    
    name_conditions = [
        Entry.full_name.ilike(like_pattern),
        Entry.name1.ilike(like_pattern),
        Entry.name2.ilike(like_pattern),
        Entry.name3.ilike(like_pattern),
        Entry.name4.ilike(like_pattern),
        Entry.alias.ilike(like_pattern),
    ]
    
    if search_all:
        all_conditions = name_conditions + [
            Entry.job_title.ilike(like_pattern),
            Entry.dob.ilike(like_pattern),
            Entry.pob.ilike(like_pattern),
            Entry.nationality.ilike(like_pattern),
            Entry.passport_no.ilike(like_pattern),
            Entry.identity_no.ilike(like_pattern),
            Entry.address.ilike(like_pattern),
            Entry.additional_info.ilike(like_pattern),
            Entry.source_list.ilike(like_pattern),
            Entry.tittle.ilike(like_pattern),
        ]
        stmt = select(Entry).where(
            Entry.entry_type == entry_type_value,
            or_(*all_conditions)
        )
    else:
        stmt = select(Entry).where(
            Entry.entry_type == entry_type_value,
            or_(*name_conditions)
        )
    
    stmt = stmt.offset(skip).limit(limit)
    result = await db.execute(stmt)
    entries = result.scalars().all()
    return [entry_to_dto(e) for e in entries]


@router.get(
    "/all",
    response_model=list[EntryDto],
    summary="Получить все записи (только для админа)",
)
async def get_all_entries(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
    skip: int = Query(0, ge=0, description="Пропустить N записей"),
    limit: int = Query(100, ge=1, le=500, description="Макс. кол-во записей"),
):
    if not is_admin(current_user):
        return JSONResponse(status_code=403, content={"error": "Admin access required"})

    result = await db.execute(select(Entry).offset(skip).limit(limit))
    entries = result.scalars().all()
    return [entry_to_dto(e) for e in entries]


@router.post(
    "/bulk",
    response_model=list[EntryDto],
    summary="Импортировать записи (bulk, только админ)",
)
async def import_entries(
    request: BulkEntryRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    if not is_admin(current_user):
        return JSONResponse(status_code=403, content={"error": "Admin access required"})
    
    if not request.entries:
        return JSONResponse(status_code=400, content={"error": "No entries provided"})
    
    import_date = date.today()
    saved_entries = []
    
    for dto in request.entries:
        entry = Entry(
            source_list=dto.sourceList,
            entry_type=dto.entryType,
            full_name=dto.fullName,
            name1=dto.name1,
            name2=dto.name2,
            name3=dto.name3,
            name4=dto.name4,
            tittle=dto.tittle,
            job_title=dto.jobTitle,
            dob=dto.dob,
            pob=dto.pob,
            alias=dto.alias,
            nationality=dto.nationality,
            passport_no=dto.passportNo,
            identity_no=dto.identityNo,
            address=dto.address,
            additional_info=dto.additionalInfo,
            load_date=import_date,
        )
        db.add(entry)
        saved_entries.append(entry)
    
    await db.commit()
    for e in saved_entries:
        await db.refresh(e)
    
    return [entry_to_dto(e) for e in saved_entries]


@router.get(
    "/{id}",
    response_model=EntryDto,
    summary="Получить запись по ID",
)
async def get_entry_by_id(
    id: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Entry).where(Entry.id == id))
    entry = result.scalar_one_or_none()
    if entry is None:
        return JSONResponse(status_code=404, content={"error": "Entry not found"})
    return entry_to_dto(entry)


@router.put(
    "/{id}",
    response_model=EntryDto,
    summary="Обновить запись (только для админа)",
)
async def update_entry(
    id: int,
    dto: EntryDto,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    if not is_admin(current_user):
        return JSONResponse(status_code=403, content={"error": "Admin access required"})
    
    result = await db.execute(select(Entry).where(Entry.id == id))
    entry = result.scalar_one_or_none()
    if entry is None:
        return JSONResponse(status_code=404, content={"error": "Entry not found"})
    
    if dto.sourceList is not None:
        entry.source_list = dto.sourceList
    if dto.entryType is not None:
        entry.entry_type = dto.entryType
    if dto.fullName is not None:
        entry.full_name = dto.fullName
    if dto.name1 is not None:
        entry.name1 = dto.name1
    if dto.name2 is not None:
        entry.name2 = dto.name2
    if dto.name3 is not None:
        entry.name3 = dto.name3
    if dto.name4 is not None:
        entry.name4 = dto.name4
    if dto.tittle is not None:
        entry.tittle = dto.tittle
    if dto.jobTitle is not None:
        entry.job_title = dto.jobTitle
    if dto.dob is not None:
        entry.dob = dto.dob
    if dto.pob is not None:
        entry.pob = dto.pob
    if dto.alias is not None:
        entry.alias = dto.alias
    if dto.nationality is not None:
        entry.nationality = dto.nationality
    if dto.passportNo is not None:
        entry.passport_no = dto.passportNo
    if dto.identityNo is not None:
        entry.identity_no = dto.identityNo
    if dto.address is not None:
        entry.address = dto.address
    if dto.additionalInfo is not None:
        entry.additional_info = dto.additionalInfo
    
    await db.commit()
    await db.refresh(entry)
    return entry_to_dto(entry)


@router.delete(
    "/{id}",
    status_code=204,
    summary="Удалить запись (только для админа)",
)
async def delete_entry(
    id: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    if not is_admin(current_user):
        return JSONResponse(status_code=403, content={"error": "Admin access required"})
    
    result = await db.execute(select(Entry).where(Entry.id == id))
    entry = result.scalar_one_or_none()
    if entry is None:
        return JSONResponse(status_code=404, content={"error": "Entry not found"})
    
    await db.delete(entry)
    await db.commit()
    return Response(status_code=204)
