import uuid
import json
from datetime import date, datetime
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from app.db import get_db
from app.models import User, Client, AuditLog, ClientRequestBadge, AmlCustomer
from app.schemas import CreateClientRequest, ClientResponse, ClientDto, UpdateClientRequest
from app.deps import require_admin, get_current_active_user
from app.security import get_password_hash
from app.email import send_credentials_email, is_email_configured

RISK_PRIORITY = {"high": 3, "medium": 2, "low": 1, "unknown": 0}

router = APIRouter(tags=["Clients"])


async def generate_client_id(db: AsyncSession) -> tuple[str, int]:
    result = await db.execute(
        select(func.max(Client.last_id))
    )
    last_id = result.scalar() or 0
    next_id = last_id + 1
    return f"CL{next_id}", next_id


@router.post("/clients", response_model=ClientResponse)
async def create_client(
    data: CreateClientRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    user = User(
        user_id=str(uuid.uuid4()),
        username=data.username,
        password=get_password_hash(data.password),
        email=data.client_mail,
        role="USER",
        is_active=data.is_active,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow()
    )
    db.add(user)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=400, detail=f"Username '{data.username}' already exists")

    client_code, last_id = await generate_client_id(db)

    client = Client(
        client_id=client_code,
        client_name=data.client_name,
        client_alias_1=data.client_alias_1,
        client_alias_2=data.client_alias_2,
        client_alias_3=data.client_alias_3,
        client_reg_number=data.client_reg_number,
        client_tax_number=data.client_tax_number,
        client_reg_country=data.client_reg_country,
        client_director=data.client_director,
        client_mail=data.client_mail,
        doc_id=data.doc_id,
        status_sign=data.status_sign or "not_sent",
        date_signing=data.date_signing or date.today(),
        group_id=data.group_id,
        group_name=data.group_name,
        last_id=last_id,
        description=data.description,
        user_id=user.user_id,
        kyc_status="created",
        nda_status="not_started"
    )
    db.add(client)
    
    audit_log = AuditLog(
        entity="clients",
        entity_id=client.client_id,
        action="CREATE",
        old_value=None,
        new_value=json.dumps({
            "client_id": client.client_id,
            "client_name": data.client_name,
            "client_mail": data.client_mail,
            "username": data.username,
            "is_active": data.is_active,
            "client_reg_country": data.client_reg_country,
            "status_sign": client.status_sign,
            "kyc_status": client.kyc_status,
            "nda_status": client.nda_status
        }, ensure_ascii=False),
        created_by=current_user.username,
        created_at=datetime.utcnow()
    )
    db.add(audit_log)
    
    await db.commit()
    await db.refresh(user)
    await db.refresh(client)

    if data.client_mail and is_email_configured():
        background_tasks.add_task(send_credentials_email, data.client_mail, data.username, data.password)

    return ClientResponse(
        user_id=user.user_id,
        client_id=client.client_id
    )


@router.get("/clients/me", response_model=ClientDto)
async def get_my_client(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Client, User.username, User.is_active)
        .join(User, Client.user_id == User.user_id)
        .where(Client.user_id == current_user.user_id)
    )
    row = result.first()
    
    if row is None:
        raise HTTPException(status_code=404, detail="Client not found")
    
    client, username, is_active = row
    
    active_badges_result = await db.execute(
        select(func.count(ClientRequestBadge.id))
        .where(
            ClientRequestBadge.client_id == client.client_id,
            ClientRequestBadge.is_active == True
        )
    )
    active_badges_count = active_badges_result.scalar() or 0
    
    attention_required_result = await db.execute(
        select(func.count(ClientRequestBadge.id))
        .where(
            ClientRequestBadge.client_id == client.client_id,
            ClientRequestBadge.is_active == True,
            ClientRequestBadge.status.in_(['pending', 'need_signing'])
        )
    )
    attention_required_count = attention_required_result.scalar() or 0
    
    client_dict = {
        **client.__dict__,
        "username": username,
        "is_active": is_active,
        "active_badges_count": active_badges_count,
        "attention_required_count": attention_required_count
    }
    
    return ClientDto.model_validate(client_dict, from_attributes=True)


@router.get("/clients", response_model=list[ClientDto])
async def get_all_clients(
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    skip: int = Query(0, ge=0, description="Пропустить N записей"),
    limit: int = Query(100, ge=1, le=500, description="Макс. кол-во записей"),
):
    result = await db.execute(
        select(Client, User.username, User.is_active)
        .join(User, Client.user_id == User.user_id)
        .order_by(Client.last_id.desc())
        .offset(skip).limit(limit)
    )
    rows = result.all()
    
    # Собрать AML risk levels для всех клиентов одним запросом
    aml_result = await db.execute(
        select(AmlCustomer.client_id, AmlCustomer.risk_level)
        .where(AmlCustomer.client_id.isnot(None))
    )
    aml_rows = aml_result.all()
    # Для каждого client_id — наивысший risk
    aml_risk_map: dict[str, str] = {}
    for cid, rlevel in aml_rows:
        current = aml_risk_map.get(cid)
        if current is None or RISK_PRIORITY.get(rlevel, 0) > RISK_PRIORITY.get(current, 0):
            aml_risk_map[cid] = rlevel

    clients_data = []
    for client, username, is_active in rows:
        active_badges_result = await db.execute(
            select(func.count(ClientRequestBadge.id))
            .where(
                ClientRequestBadge.client_id == client.client_id,
                ClientRequestBadge.is_active == True
            )
        )
        active_badges_count = active_badges_result.scalar() or 0

        attention_required_result = await db.execute(
            select(func.count(ClientRequestBadge.id))
            .where(
                ClientRequestBadge.client_id == client.client_id,
                ClientRequestBadge.is_active == True,
                ClientRequestBadge.status.in_(['pending', 'need_signing'])
            )
        )
        attention_required_count = attention_required_result.scalar() or 0

        client_dict = {
            **client.__dict__,
            "username": username,
            "is_active": is_active,
            "active_badges_count": active_badges_count,
            "attention_required_count": attention_required_count,
            "aml_risk_level": aml_risk_map.get(client.client_id),
        }
        clients_data.append(ClientDto.model_validate(client_dict, from_attributes=True))

    return clients_data


@router.get("/clients/{client_id}", response_model=ClientDto)
async def get_client_by_id(
    client_id: str,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Client, User.username, User.is_active)
        .join(User, Client.user_id == User.user_id)
        .where(Client.client_id == client_id)
    )
    row = result.first()
    
    if row is None:
        raise HTTPException(status_code=404, detail="Client not found")
    
    client, username, is_active = row
    
    active_badges_result = await db.execute(
        select(func.count(ClientRequestBadge.id))
        .where(
            ClientRequestBadge.client_id == client.client_id,
            ClientRequestBadge.is_active == True
        )
    )
    active_badges_count = active_badges_result.scalar() or 0
    
    attention_required_result = await db.execute(
        select(func.count(ClientRequestBadge.id))
        .where(
            ClientRequestBadge.client_id == client.client_id,
            ClientRequestBadge.is_active == True,
            ClientRequestBadge.status.in_(['pending', 'need_signing'])
        )
    )
    attention_required_count = attention_required_result.scalar() or 0

    # AML risk
    aml_result = await db.execute(
        select(AmlCustomer.risk_level).where(AmlCustomer.client_id == client_id)
    )
    aml_levels = [r[0] for r in aml_result.all()]
    aml_risk = max(aml_levels, key=lambda l: RISK_PRIORITY.get(l, 0)) if aml_levels else None

    client_dict = {
        **client.__dict__,
        "username": username,
        "is_active": is_active,
        "active_badges_count": active_badges_count,
        "attention_required_count": attention_required_count,
        "aml_risk_level": aml_risk,
    }

    return ClientDto.model_validate(client_dict, from_attributes=True)


@router.put("/clients/{client_id}", response_model=ClientDto)
async def update_client(
    client_id: str,
    data: UpdateClientRequest,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Client).where(Client.client_id == client_id)
    )
    client = result.scalar_one_or_none()
    
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found")
    
    old_value = {
        "client_name": client.client_name,
        "client_alias_1": client.client_alias_1,
        "client_alias_2": client.client_alias_2,
        "client_alias_3": client.client_alias_3,
        "client_reg_number": client.client_reg_number,
        "client_tax_number": client.client_tax_number,
        "client_reg_country": client.client_reg_country,
        "client_director": client.client_director,
        "client_mail": client.client_mail,
        "doc_id": client.doc_id,
        "status_sign": client.status_sign,
        "date_signing": client.date_signing.isoformat() if client.date_signing else None,
        "group_id": client.group_id,
        "group_name": client.group_name,
        "description": client.description,
        "account_status": client.account_status,
        "account_hold_reason": client.account_hold_reason,
        "kyc_override": client.kyc_override,
    }
    
    update_data = data.model_dump(exclude_unset=True, exclude_none=True)

    is_active = update_data.pop("is_active", None)
    username = update_data.pop("username", None)
    password = update_data.pop("password", None)

    for field, value in update_data.items():
        setattr(client, field, value)

    # Если меняется client_mail — синхронизируем его в users.email,
    # чтобы /users/me (ProfileDrawer) не возвращал устаревшую почту.
    new_client_mail = update_data.get("client_mail")

    user_changes = {}
    if (
        is_active is not None
        or username is not None
        or password is not None
        or new_client_mail is not None
    ):
        user_result = await db.execute(
            select(User).where(User.user_id == client.user_id)
        )
        user = user_result.scalar_one_or_none()
        if user:
            if is_active is not None:
                old_value["is_active"] = user.is_active
                user.is_active = is_active
                user_changes["is_active"] = is_active

            if username is not None:
                old_value["username"] = user.username
                user.username = username
                user_changes["username"] = username

            if password is not None:
                user.password = get_password_hash(password)
                user_changes["password"] = "***"

            if new_client_mail is not None and user.email != new_client_mail:
                user_changes["user_email"] = new_client_mail
                user.email = new_client_mail

            user.updated_at = datetime.utcnow()
    
    new_value = old_value.copy()
    for field, value in update_data.items():
        new_value[field] = value.isoformat() if isinstance(value, date) else value
    for field, value in user_changes.items():
        new_value[field] = value
    
    audit_log = AuditLog(
        entity="clients",
        entity_id=client_id,
        action="UPDATE",
        old_value=json.dumps(old_value, ensure_ascii=False),
        new_value=json.dumps(new_value, ensure_ascii=False),
        created_by=current_user.username,
        created_at=datetime.utcnow()
    )
    db.add(audit_log)

    # Compliance-trail для KYC-override: отдельная запись с действием
    # KYC_OVERRIDE_TOGGLE пишется только когда флаг фактически меняется,
    # чтобы быстро находить эти события через WHERE action='KYC_OVERRIDE_TOGGLE'.
    if "kyc_override" in update_data:
        previous = old_value.get("kyc_override")
        current = update_data["kyc_override"]
        if previous != current:
            db.add(AuditLog(
                entity="clients",
                entity_id=client_id,
                action="KYC_OVERRIDE_TOGGLE",
                old_value=json.dumps({"kyc_override": previous}, ensure_ascii=False),
                new_value=json.dumps({"kyc_override": current}, ensure_ascii=False),
                created_by=current_user.username,
                created_at=datetime.utcnow(),
            ))

    await db.commit()
    await db.refresh(client)
    
    user_result = await db.execute(
        select(User.username, User.is_active).where(User.user_id == client.user_id)
    )
    username, current_is_active = user_result.first()
    
    active_badges_result = await db.execute(
        select(func.count(ClientRequestBadge.id))
        .where(
            ClientRequestBadge.client_id == client.client_id,
            ClientRequestBadge.is_active == True
        )
    )
    active_badges_count = active_badges_result.scalar() or 0
    
    attention_required_result = await db.execute(
        select(func.count(ClientRequestBadge.id))
        .where(
            ClientRequestBadge.client_id == client.client_id,
            ClientRequestBadge.is_active == True,
            ClientRequestBadge.status.in_(['pending', 'need_signing'])
        )
    )
    attention_required_count = attention_required_result.scalar() or 0
    
    client_dict = {
        **client.__dict__,
        "username": username,
        "is_active": current_is_active,
        "active_badges_count": active_badges_count,
        "attention_required_count": attention_required_count
    }
    
    return ClientDto.model_validate(client_dict, from_attributes=True)
