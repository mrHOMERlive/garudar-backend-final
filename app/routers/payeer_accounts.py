from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from typing import List
from datetime import datetime
import json
from app.db import get_db
from app.models import User, PayeerAccount, AuditLog
from app.schemas import PayeerAccountDto, PayeerAccountCreateRequest, PayeerAccountUpdateRequest
from app.deps import require_admin

router = APIRouter(tags=["Payeer Accounts"])


@router.get("/payeer-accounts", response_model=List[PayeerAccountDto])
async def list_payeer_accounts(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Получить список всех Payeer аккаунтов (только для администратора)"""
    result = await db.execute(select(PayeerAccount))
    accounts = result.scalars().all()
    return [PayeerAccountDto.model_validate(acc, from_attributes=True) for acc in accounts]


@router.get("/payeer-accounts/{account_no}", response_model=PayeerAccountDto)
async def get_payeer_account(
    account_no: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Получить информацию о конкретном Payeer аккаунте (только для администратора)"""
    result = await db.execute(
        select(PayeerAccount).where(PayeerAccount.account_no == account_no)
    )
    account = result.scalar_one_or_none()
    
    if account is None:
        raise HTTPException(status_code=404, detail="Payeer account not found")
    
    return PayeerAccountDto.model_validate(account, from_attributes=True)


@router.post("/payeer-accounts", response_model=PayeerAccountDto, status_code=201)
async def create_payeer_account(
    data: PayeerAccountCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Создать новый Payeer аккаунт (только для администратора)"""
    result = await db.execute(
        select(PayeerAccount).where(PayeerAccount.account_no == data.account_no)
    )
    existing_account = result.scalar_one_or_none()
    
    if existing_account:
        raise HTTPException(
            status_code=400, 
            detail=f"Payeer account with account_no '{data.account_no}' already exists"
        )
    
    new_account = PayeerAccount(
        account_no=data.account_no,
        alias=data.alias,
        currency=data.currency,
        status=data.status,
        bank_name=data.bank_name,
        bank_address=data.bank_address,
        bank_corr_account=data.bank_corr_account,
        bank_bic=data.bank_bic,
        bank_country=data.bank_country
    )
    
    db.add(new_account)
    
    audit_log = AuditLog(
        entity="payeer_accounts",
        entity_id=data.account_no,
        action="CREATE",
        old_value=None,
        new_value=json.dumps({
            "account_no": data.account_no,
            "alias": data.alias,
            "currency": data.currency,
            "status": data.status,
            "bank_name": data.bank_name,
            "bank_address": data.bank_address,
            "bank_corr_account": data.bank_corr_account,
            "bank_bic": data.bank_bic,
            "bank_country": data.bank_country
        }),
        created_by=current_user.username,
        created_at=datetime.utcnow()
    )
    db.add(audit_log)
    
    await db.commit()
    await db.refresh(new_account)
    
    return PayeerAccountDto.model_validate(new_account, from_attributes=True)


@router.put("/payeer-accounts/{account_no}", response_model=PayeerAccountDto)
async def update_payeer_account(
    account_no: str,
    data: PayeerAccountUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Обновить Payeer аккаунт (только для администратора)"""
    result = await db.execute(
        select(PayeerAccount).where(PayeerAccount.account_no == account_no)
    )
    account = result.scalar_one_or_none()
    
    if account is None:
        raise HTTPException(status_code=404, detail="Payeer account not found")
    
    old_value = {
        "account_no": account.account_no,
        "alias": account.alias,
        "currency": account.currency,
        "status": account.status,
        "bank_name": account.bank_name,
        "bank_address": account.bank_address,
        "bank_corr_account": account.bank_corr_account,
        "bank_bic": account.bank_bic,
        "bank_country": account.bank_country
    }

    if data.account_no is not None:
        if data.account_no != account.account_no:
            existing = await db.execute(
                select(PayeerAccount).where(PayeerAccount.account_no == data.account_no)
            )
            if existing.scalar_one_or_none():
                raise HTTPException(
                    status_code=400,
                    detail=f"Payeer account with account_no '{data.account_no}' already exists"
                )
        account.account_no = data.account_no
    if data.currency is not None:
        account.currency = data.currency
    if data.status is not None:
        account.status = data.status
    if data.bank_name is not None:
        account.bank_name = data.bank_name
    if data.bank_address is not None:
        account.bank_address = data.bank_address
    if data.bank_corr_account is not None:
        account.bank_corr_account = data.bank_corr_account
    if data.bank_bic is not None:
        account.bank_bic = data.bank_bic
    if data.alias is not None:
        account.alias = data.alias
    if data.bank_country is not None:
        account.bank_country = data.bank_country

    new_value = {
        "account_no": account.account_no,
        "alias": account.alias,
        "currency": account.currency,
        "status": account.status,
        "bank_name": account.bank_name,
        "bank_address": account.bank_address,
        "bank_corr_account": account.bank_corr_account,
        "bank_bic": account.bank_bic,
        "bank_country": account.bank_country
    }
    
    audit_log = AuditLog(
        entity="payeer_accounts",
        entity_id=account_no,
        action="UPDATE",
        old_value=json.dumps(old_value),
        new_value=json.dumps(new_value),
        created_by=current_user.username,
        created_at=datetime.utcnow()
    )
    db.add(audit_log)
    
    await db.commit()
    await db.refresh(account)
    
    return PayeerAccountDto.model_validate(account, from_attributes=True)


@router.delete("/payeer-accounts/{account_no}", status_code=204)
async def delete_payeer_account(
    account_no: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Удалить Payeer аккаунт (только для администратора)"""
    result = await db.execute(
        select(PayeerAccount).where(PayeerAccount.account_no == account_no)
    )
    account = result.scalar_one_or_none()
    
    if account is None:
        raise HTTPException(status_code=404, detail="Payeer account not found")
    
    old_value = {
        "account_no": account.account_no,
        "alias": account.alias,
        "currency": account.currency,
        "status": account.status,
        "bank_name": account.bank_name,
        "bank_address": account.bank_address,
        "bank_corr_account": account.bank_corr_account,
        "bank_bic": account.bank_bic,
        "bank_country": account.bank_country
    }

    audit_log = AuditLog(
        entity="payeer_accounts",
        entity_id=account_no,
        action="DELETE",
        old_value=json.dumps(old_value),
        new_value=None,
        created_by=current_user.username,
        created_at=datetime.utcnow()
    )
    db.add(audit_log)
    
    await db.execute(
        delete(PayeerAccount).where(PayeerAccount.account_no == account_no)
    )
    await db.commit()
    
    return None
