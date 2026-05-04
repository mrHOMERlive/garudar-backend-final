from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db import get_db
from app.models import User, Currency, Country, OrgDirectory
from app.deps import get_current_active_user
from app.cache import cache

router = APIRouter(tags=["Dictionaries"])


@router.get(
    "/currencies",
    summary="Получить список доступных валют",
)
async def get_currencies(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    cached = await cache.get("currencies")
    if cached is not None:
        return cached
    result = await db.execute(select(Currency))
    currencies = result.scalars().all()
    data = [{"code": c.code, "name": c.name} for c in currencies]
    await cache.set("currencies", data, ttl_seconds=3600)
    return data


@router.get(
    "/countries",
    summary="Получить список доступных стран",
)
async def get_countries(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    cached = await cache.get("countries")
    if cached is not None:
        return cached
    result = await db.execute(select(Country))
    countries = result.scalars().all()
    data = [{"code": c.ctry_cd, "name": c.country_name} for c in countries]
    await cache.set("countries", data, ttl_seconds=3600)
    return data


@router.get(
    "/bic",
    summary="Получить список BIC кодов по стране",
)
async def get_bic_by_country(
    country: str = Query(..., description="Код страны (2 символа)", example="ID"),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(OrgDirectory).where(OrgDirectory.ctry_cd == country.upper())
    )
    orgs = result.scalars().all()
    return [
        {
            "id": o.id,
            "version": o.version,
            "bicSwiftCd": o.bic_swift_cd,
            "chipsUid": o.chips_uid,
            "nm": o.nm,
            "orgNationalCd": o.org_national_cd,
            "branchNm": o.branch_nm,
            "addr1": o.addr_1,
            "addr2": o.addr_2,
            "addr3": o.addr_3,
            "cityNm": o.city_nm,
            "substateNm": o.substate_nm,
            "stateNm": o.state_nm,
            "postcode": o.postcode,
            "idx": o.idx,
            "isDelete": o.is_delete,
            "isInactive": o.is_inactive,
            "isSystem": o.is_system,
            "createdBy": o.created_by,
            "createdDt": o.created_dt.isoformat() if o.created_dt else None,
            "updatedBy": o.updated_by,
            "updatedDt": o.updated_dt.isoformat() if o.updated_dt else None,
            "ctryCd": o.ctry_cd,
            "nationalOrgDirCd": o.national_org_dir_cd,
            "interBankConnectionSts": o.inter_bank_connection_sts,
            "isActiveMars": o.is_active_mars,
        }
        for o in orgs
    ]
