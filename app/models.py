import enum
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional
from sqlalchemy import String, BigInteger, Integer, CHAR, Date, DateTime, Text, Boolean, Numeric, Index, ForeignKey, JSON, event
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db import Base
from app.enums import KYCStatus, NDAStatus, AmlCustomerType, AmlRiskLevel, AmlAlertStatus, AmlCaseStatus, AmlScreeningType


class Role(str, enum.Enum):
    USER = "USER"
    ADMIN = "ADMIN"
    CLIENT = "CLIENT"
    STAFF = "STAFF"
    KYC_OPERATOR = "KYC_OPERATOR"


# ======================================================================
# BASIC REFERENCE TABLES
# ======================================================================

class Country(Base):
    __tablename__ = "countries"

    ctry_cd: Mapped[str] = mapped_column(CHAR(2), primary_key=True)
    country_name: Mapped[str] = mapped_column(String(150), unique=True, nullable=False)


class Currency(Base):
    __tablename__ = "currencies"

    code: Mapped[str] = mapped_column(String(10), primary_key=True)
    name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)


class OrgDirectory(Base):
    __tablename__ = "org_directory"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    version: Mapped[int] = mapped_column(Integer, default=1)

    bic_swift_cd: Mapped[Optional[str]] = mapped_column(String(12), nullable=True)
    chips_uid: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    nm: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    org_national_cd: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    branch_nm: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    addr_1: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    addr_2: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    addr_3: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    city_nm: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    substate_nm: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    state_nm: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    postcode: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    idx: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    is_delete: Mapped[bool] = mapped_column(Boolean, default=False)
    is_inactive: Mapped[bool] = mapped_column(Boolean, default=False)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)

    created_by: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    created_dt: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    updated_by: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    updated_dt: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    ctry_cd: Mapped[Optional[str]] = mapped_column(CHAR(2), ForeignKey("countries.ctry_cd"), nullable=True)
    national_org_dir_cd: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    inter_bank_connection_sts: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    is_active_mars: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    __table_args__ = (
        Index("idx_orgdir_bic", "bic_swift_cd"),
        Index("idx_orgdir_country", "ctry_cd"),
    )


# ======================================================================
# AUTH / ROLES
# ======================================================================

class User(Base):
    __tablename__ = "users"

    user_id: Mapped[str] = mapped_column(String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()), primary_key=True)
    username: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    role: Mapped[Optional[str]] = mapped_column(String(50), default="USER", nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    terms_accepted: Mapped[bool] = mapped_column(Boolean, default=False)
    terms_accepted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    token_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        Index("idx_refresh_token_hash", "token_hash"),
        Index("idx_refresh_user_id", "user_id"),
        Index("idx_refresh_expires", "expires_at"),
    )


# ======================================================================
# MASTER DATA
# ======================================================================

class Client(Base):
    __tablename__ = "clients"

    client_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    client_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    client_alias_1: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    client_alias_2: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    client_alias_3: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    client_reg_number: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    client_tax_number: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    client_reg_country: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    doc_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    status_sign: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    date_signing: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    group_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    group_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    client_director: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    client_mail: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    last_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    orders_count: Mapped[int] = mapped_column(BigInteger, default=0, nullable=True)
    kyc_status: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, default=KYCStatus.CREATED.value)
    kyc_submitted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    kyc_decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    kyc_decided_by: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.user_id"), nullable=True)
    # Админ-флаг: разрешает клиенту создавать заявки в обход проверки kyc_status='approved'.
    # Используется для исключительных случаев (миграция legacy-клиентов, временный
    # доступ под надзором). По умолчанию False — KYC обязателен.
    kyc_override: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    nda_status: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, default=NDAStatus.NOT_STARTED.value)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    account_status: Mapped[str] = mapped_column(String(50), nullable=False, default="active")
    account_hold_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False)

    __table_args__ = (
        Index("idx_client_user", "user_id"),
    )


class ClientRequestBadge(Base):
    __tablename__ = "client_request_badges"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    client_id: Mapped[str] = mapped_column(String(255), ForeignKey("clients.client_id"), nullable=False)
    badge_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="not_required")
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    staff_comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    document_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    submitted_document_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_badge_client", "client_id"),
        Index("idx_badge_client_type", "client_id", "badge_type", unique=True),
        Index("idx_badge_active", "is_active"),
    )


class Counterparty(Base):
    __tablename__ = "counterparties"

    counterparty_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    counterparty_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    counterparty_alias_1: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    counterparty_alias_2: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    counterparty_alias_3: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    counterparty_reg_number: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    counterparty_reg_country: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    last_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)


class PayeerAccount(Base):
    __tablename__ = "payeer_accounts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    account_no: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    alias: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    currency: Mapped[Optional[str]] = mapped_column(String(10), ForeignKey("currencies.code"), nullable=True)
    status: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    bank_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    bank_address: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    bank_corr_account: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    bank_bic: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    bank_country: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)


# ======================================================================
# DICTIONARIES / SETTINGS
# ======================================================================

class Threshold(Base):
    __tablename__ = "thresholds"

    currency: Mapped[str] = mapped_column(String(10), ForeignKey("currencies.code"), primary_key=True)
    amount_threshold: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


# ======================================================================
# CMS / PUBLIC SITE CONTENT
# ======================================================================

class SalesLead(Base):
    __tablename__ = "sales_leads"

    lead_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    company: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class FaqItem(Base):
    __tablename__ = "faq_items"

    faq_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    question: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    answer: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class ContentBlock(Base):
    __tablename__ = "content_blocks"

    block_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    page: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    block_key: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


# ======================================================================
# BANK STATEMENTS
# ======================================================================

class MandiriStatement(Base):
    __tablename__ = "mandiri_statement"

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    account_no: Mapped[Optional[str]] = mapped_column(String(255), ForeignKey("payeer_accounts.account_no", onupdate="CASCADE"), nullable=True)
    currency: Mapped[Optional[str]] = mapped_column(String(10), ForeignKey("currencies.code"), nullable=True)

    date_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    value_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    transaction_code: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    transaction_code_desc: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    description_main: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    description_extra: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    client_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    debit: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)
    credit: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)
    opening_balance: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)
    balance: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)

    order_id_auto: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    order_id_manual: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    description_auto: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    description_manual: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    order_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    client_id: Mapped[Optional[str]] = mapped_column(String(255), ForeignKey("clients.client_id"), nullable=True)
    counterparty_id: Mapped[Optional[str]] = mapped_column(String(255), ForeignKey("counterparties.counterparty_id"), nullable=True)

    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        Index("idx_mandiri_client", "client_id"),
        Index("idx_mandiri_account", "account_no"),
        Index("idx_mandiri_value_date", "value_date"),
    )


class OtherBankStatement(Base):
    __tablename__ = "other_bank_statements"

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    account_no: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    currency: Mapped[Optional[str]] = mapped_column(String(10), ForeignKey("currencies.code"), nullable=True)
    jurisdiction: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    date: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    value_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    transaction_remark: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    beneficiary_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    payer_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    client_id: Mapped[Optional[str]] = mapped_column(String(255), ForeignKey("clients.client_id"), nullable=True)
    debit: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)
    credit: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)

    order_retrived_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    order_retrived_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    order_id_auto: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    order_id_manual: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    description_auto: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    description_manual: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    order_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        Index("idx_other_bank_client", "client_id"),
    )


class MandiriOrderOverride(Base):
    __tablename__ = "mandiri_order_overrides"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    mandiri_statement_id: Mapped[Optional[str]] = mapped_column(String(255), ForeignKey("mandiri_statement.id"), nullable=True)
    order_id_manual: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    description_manual: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class OtherBankOrderOverride(Base):
    __tablename__ = "other_bank_order_overrides"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    other_statement_id: Mapped[Optional[str]] = mapped_column(String(255), ForeignKey("other_bank_statements.id"), nullable=True)
    order_id_manual: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    description_manual: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


# ======================================================================
# ORDERS: POBO
# ======================================================================

class OrderPobo(Base):
    __tablename__ = "orders_pobo"

    order_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    client_id: Mapped[Optional[str]] = mapped_column(String(255), ForeignKey("clients.client_id"), nullable=True)

    amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)
    currency: Mapped[Optional[str]] = mapped_column(String(10), ForeignKey("currencies.code"), nullable=True)

    counterparty_id: Mapped[Optional[str]] = mapped_column(String(255), ForeignKey("counterparties.counterparty_id"), nullable=True)
    beneficiary_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    beneficiary_adress: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    destination_account: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    beneficiary_country: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    bank_country: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    bank_bic: Mapped[Optional[str]] = mapped_column(String(11), nullable=True)
    bank_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    bank_address: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    remark: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    invocie_required: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    invocie_received: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    payment_proof: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    non_mandiri_execution: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    invoice_number: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    status: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    last_status: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    include: Mapped[bool] = mapped_column(Boolean, default=True)
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    executed: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Relationships (lazy="noload" — загрузка только через selectinload)
    client: Mapped[Optional["Client"]] = relationship("Client", foreign_keys=[client_id], lazy="noload")
    terms: Mapped[list["OrderPoboTerm"]] = relationship("OrderPoboTerm", foreign_keys="OrderPoboTerm.order_id", lazy="noload")

    __table_args__ = (
        Index("idx_order_pobo_client", "client_id"),
        Index("idx_order_pobo_deleted", "deleted"),
        Index("idx_order_pobo_status", "status"),
    )


class OrderPoboTerm(Base):
    __tablename__ = "order_pobo_terms"

    term_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    order_id: Mapped[Optional[str]] = mapped_column(String(255), ForeignKey("orders_pobo.order_id"), nullable=True)
    client_id: Mapped[Optional[str]] = mapped_column(String(255), ForeignKey("clients.client_id"), nullable=True)

    amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)
    currency: Mapped[Optional[str]] = mapped_column(String(10), ForeignKey("currencies.code"), nullable=True)

    client_payment_currency: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    date_paid: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    data_fixing: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    remuneration_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    remuneration_percentage: Mapped[Optional[Decimal]] = mapped_column(Numeric(9, 4), nullable=True)
    remuneration_fixed: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)

    amount_remuneration: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)
    amount_to_be_paid: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)

    exchange_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 8), nullable=True)
    exchange_rate_manual: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 8), nullable=True)

    bank_statement_in_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    bank_statement_in_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    bank_statement_out_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    bank_statement_out_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    amount_to_be_paid_target_cur: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)
    amount_paid_target_cur: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)

    doc_paid_no: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    doc_paid_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    payment_proof_no: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    payment_proof_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    GAN_bank_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    GAN_bank_account: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    date_report: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    conversion_method: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    base_currency: Mapped[Optional[str]] = mapped_column(String(10), ForeignKey("currencies.code"), nullable=True)
    FX: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    executing_bank: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    FX_executing_bank: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 8), nullable=True)
    status: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)

    __table_args__ = (
        Index("idx_order_pobo_term_order", "order_id"),
        Index("idx_order_pobo_term_client", "client_id"),
    )


@event.listens_for(OrderPoboTerm, 'before_insert')
@event.listens_for(OrderPoboTerm, 'before_update')
def calculate_amount_to_be_paid_target_cur_pobo(mapper, connection, target):
    if target.amount_to_be_paid is not None and target.exchange_rate is not None:
        target.amount_to_be_paid_target_cur = target.amount_to_be_paid * target.exchange_rate


# ======================================================================
# ORDERS: COBO
# ======================================================================

class OrderCobo(Base):
    __tablename__ = "orders_cobo"

    order_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    client_id: Mapped[Optional[str]] = mapped_column(String(255), ForeignKey("clients.client_id"), nullable=True)

    document_order_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)
    currency: Mapped[Optional[str]] = mapped_column(String(10), ForeignKey("currencies.code"), nullable=True)

    date_fixing: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    date_paid: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    date_received: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    counterparty_id: Mapped[Optional[str]] = mapped_column(String(255), ForeignKey("counterparties.counterparty_id"), nullable=True)
    payer_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    status: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    last_status: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        Index("idx_order_cobo_client", "client_id"),
        Index("idx_order_cobo_status", "status"),
    )


class OrderCoboTerm(Base):
    __tablename__ = "order_cobo_terms"

    term_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    order_id: Mapped[Optional[str]] = mapped_column(String(255), ForeignKey("orders_cobo.order_id"), nullable=True)
    client_id: Mapped[Optional[str]] = mapped_column(String(255), ForeignKey("clients.client_id"), nullable=True)

    amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)
    currency: Mapped[Optional[str]] = mapped_column(String(10), ForeignKey("currencies.code"), nullable=True)
    client_payout_currency: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)

    data_paid: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    data_fixing: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    remuneration: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)
    amount_remuneration: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)
    amount_to_be_paid: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)

    exchange_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 8), nullable=True)
    exchange_rate_manual: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 8), nullable=True)

    bank_statement_in_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    bank_statement_in_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    bank_statement_out_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    bank_statement_out_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    amount_to_be_paid_target_cur: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)
    amount_paid_target_cur: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)


@event.listens_for(OrderCoboTerm, 'before_insert')
@event.listens_for(OrderCoboTerm, 'before_update')
def calculate_amount_to_be_paid_target_cur_cobo(mapper, connection, target):
    if target.amount_to_be_paid is not None and target.exchange_rate is not None:
        target.amount_to_be_paid_target_cur = target.amount_to_be_paid * target.exchange_rate


# ======================================================================
# STATUS HISTORY / DOCS / EXPORTS
# ======================================================================

class OrderStatusHistory(Base):
    __tablename__ = "order_status_history"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    order_id: Mapped[Optional[str]] = mapped_column(String(255), ForeignKey("orders_pobo.order_id"), nullable=True)
    old_status: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    new_status: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    changed_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    changed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("idx_status_history_order", "order_id"),
        Index("idx_status_history_changed_at", "changed_at"),
    )


class OrderDocument(Base):
    __tablename__ = "order_documents"

    doc_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    order_id: Mapped[Optional[str]] = mapped_column(String(255), ForeignKey("orders_pobo.order_id"), nullable=True)

    doc_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    file_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    file_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    file_size: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    uploaded_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    uploaded_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        Index("idx_order_docs_type", "order_id", "doc_type"),
    )


class InstructionExport(Base):
    __tablename__ = "instruction_exports"

    export_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    export_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    created_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    file_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    file_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    export_params: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class InstructionExportItem(Base):
    __tablename__ = "instruction_export_items"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    export_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("instruction_exports.export_id"), nullable=True)
    order_id: Mapped[Optional[str]] = mapped_column(String(255), ForeignKey("orders_pobo.order_id"), nullable=True)
    included: Mapped[bool] = mapped_column(Boolean, default=True)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    entity: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    entity_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    action: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    old_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    new_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        Index("idx_audit_entity", "entity", "entity_id"),
        Index("idx_audit_created_at", "created_at"),
    )


# ======================================================================
# EXECUTED ORDERS MODULE
# ======================================================================

class ExecutedOrder(Base):
    __tablename__ = "executed_orders"

    executed_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_order_id: Mapped[Optional[str]] = mapped_column(String(255), ForeignKey("orders_pobo.order_id"), nullable=True)

    doc_package_status: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    mt103_status: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    settled_status: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    refund_flag: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    staff_description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    mt103_file_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    mt103_no: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    mt103_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    
    transaction_status_file_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    transaction_status_no: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    transaction_status_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    transaction_status_status: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    
    act_report_file_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    act_report_no: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    act_report_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    moved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    moved_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    __table_args__ = (
        Index("idx_executed_source_order", "source_order_id"),
    )


# ======================================================================
# REFUNDS
# ======================================================================

class Refund(Base):
    __tablename__ = "refunds"

    refund_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    order_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)
    currency: Mapped[Optional[str]] = mapped_column(String(10), ForeignKey("currencies.code"), nullable=True)
    status_received: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    type_refund: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    cur_refund: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    rate_refund: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 8), nullable=True)
    amount_refund: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)
    remuneration_refund: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)
    amount_refund_base_cur: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)
    outstanding_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)
    closed: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        Index("idx_refund_order", "order_id"),
    )


# ======================================================================
# FX FIFO
# ======================================================================

class MandiriFxFifo(Base):
    __tablename__ = "mandiri_fx_fifo"

    id: Mapped[str] = mapped_column(String(255), primary_key=True)

    account_no: Mapped[Optional[str]] = mapped_column(String(255), ForeignKey("payeer_accounts.account_no", onupdate="CASCADE"), nullable=True)
    currency: Mapped[Optional[str]] = mapped_column(String(10), ForeignKey("currencies.code"), nullable=True)
    date_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    value_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    transaction_code: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    transaction_code_desc: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    description_main: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    client_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    description_extra: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reference: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    debit: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)
    credit: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)
    opening_balance: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)
    balance: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)

    order_id_auto: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    order_id_manual: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    manual_desc: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    order_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    auto_desc: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    desc: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    is_inhouse: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    forex_flag: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)

    open_fx_balance: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)
    fx_balance: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)
    fx_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 8), nullable=True)

    fx_used_from_fx: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)
    fx_used_from_direct: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)

    open_direct_balance: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)
    direct_balance: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)

    fx_lots_used: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    fx_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("idx_fx_fifo_account", "account_no"),
        Index("idx_fx_fifo_order", "order_id"),
    )


# ======================================================================
# EXCHANGE RATES
# ======================================================================

class ExchangeRate(Base):
    __tablename__ = "exchange_rates"

    date: Mapped[date] = mapped_column(Date, primary_key=True)
    usd_rub: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 8), nullable=True)
    eur_rub: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 8), nullable=True)
    cny_rub: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 8), nullable=True)

    usd: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 8), nullable=True)
    eur: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 8), nullable=True)
    cny: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 8), nullable=True)


# ======================================================================
# OVERLAPPING
# ======================================================================

class Overlapping(Base):
    __tablename__ = "overlapping"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    order_cobo_id: Mapped[Optional[str]] = mapped_column(String(255), ForeignKey("orders_cobo.order_id"), nullable=True)
    amount_cobo: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)
    currency_cobo: Mapped[Optional[str]] = mapped_column(String(10), ForeignKey("currencies.code"), nullable=True)
    date_paid_cobo: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    exchange_rate_cobo: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 8), nullable=True)

    amount_overlapped_cobo: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)

    exchange_rate_cobo_cur_to_pobo_cur_cobo_date: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 12), nullable=True)
    amount_target_currency_overlapped: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)
    exchange_rate_cobo_cur_to_pobo_cur_pobo_date: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 12), nullable=True)

    amount_resting_cobo: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)

    order_pobo_id: Mapped[Optional[str]] = mapped_column(String(255), ForeignKey("orders_pobo.order_id"), nullable=True)
    amount_to_be_paid: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)
    currency_pobo: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    date_paid_pobo: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    exchange_rate_pobo: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 8), nullable=True)

    amount_overlapped_pobo: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)
    exchange_rate_differences: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)

    amount_resting_pobo: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)

    profit_migrated_cobo_cur: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)
    profit_migrated_balance_cur: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)

    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


# ======================================================================
# BALANCE RECONCILIATION
# ======================================================================

class BalanceReconcile(Base):
    __tablename__ = "balance_reconcile"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    date: Mapped[date] = mapped_column(Date, unique=True, nullable=False)

    balance_openning: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)
    balance_fv_opening: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)
    balance_remuneration_opening: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)

    credit_fv: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)
    credit_remuneration: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)

    debit_cobo: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)
    amount_overlapped_cobo: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)
    debit_remuneration: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)
    debit_other_costs: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)

    exchange_rate_differences: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)

    deposit_movement_fv: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)
    deposit_revenue: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)

    balance_closing: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)
    balance_fv_closing: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)
    balance_remuneration_closing: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)

    ss_profit_fixed_rub: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)


# ======================================================================
# KYC
# ======================================================================

class KycIndividual(Base):
    __tablename__ = "kyc_individuals"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    reference: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    alias_1: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    alias_2: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    alias_3: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    alias_4: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    alias_5: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    occupation: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    nationality: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    passport_number: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    identity_number: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    date_of_birth: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    place_of_birth: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    address: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    additional_info: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    type_of_list: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    source: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_date: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class KycCompany(Base):
    __tablename__ = "kyc_companies"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    reference: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    alias_1: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    alias_2: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    alias_3: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    alias_4: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    alias_5: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    address_1: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    address_2: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    address_3: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    additional_info: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    type_of_list: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    source: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_date: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class KycSearchHistory(Base):
    __tablename__ = "kyc_search_history"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    searched_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    search_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    query: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    match_mode: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    threshold: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    sources: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class MembercheckReport(Base):
    __tablename__ = "membercheck_reports"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    search_history_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("kyc_search_history.id"), nullable=True)
    provider_scan_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    report_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    report_payload: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


# ======================================================================
# ONBOARDING KYC
# ======================================================================

class OnboardingKycProfile(Base):
    __tablename__ = "onboarding_kyc_profiles"

    profile_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    client_id: Mapped[str] = mapped_column(String(255), ForeignKey("clients.client_id"), unique=True, nullable=False)
    status: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, default=KYCStatus.CREATED.value)
    payload: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    submitted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    decided_by: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.user_id"), nullable=True)
    decision_comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("idx_kyc_profile_client", "client_id"),
        Index("idx_kyc_profile_status", "status"),
    )


class OnboardingKycUbo(Base):
    __tablename__ = "onboarding_kyc_ubos"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    profile_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("onboarding_kyc_profiles.profile_id"), nullable=False)
    ubo_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    shareholding_percent: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), nullable=True)
    nationality: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    residence_country: Mapped[Optional[str]] = mapped_column(CHAR(2), nullable=True)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        Index("idx_kyc_ubo_profile", "profile_id"),
    )


class OnboardingKycDocument(Base):
    __tablename__ = "onboarding_kyc_documents"

    doc_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    profile_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("onboarding_kyc_profiles.profile_id"), nullable=False)
    doc_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    file_key: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    file_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    file_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    file_size: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    uploaded_by: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.user_id"), nullable=True)
    uploaded_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    is_required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("idx_kyc_doc_profile", "profile_id"),
        Index("idx_kyc_doc_type", "doc_type"),
    )


class OnboardingKycStatusHistory(Base):
    __tablename__ = "onboarding_kyc_status_history"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    profile_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("onboarding_kyc_profiles.profile_id"), nullable=False)
    old_status: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    new_status: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    changed_by: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.user_id"), nullable=True)
    changed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("idx_kyc_history_profile", "profile_id"),
        Index("idx_kyc_history_date", "changed_at"),
    )


# ======================================================================
# NDA (Non-Disclosure Agreement)
# ======================================================================

class NdaGroupCompany(Base):
    __tablename__ = "nda_group_companies"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    company_code: Mapped[Optional[str]] = mapped_column(String(50), unique=True, nullable=True)
    company_name_ru: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    company_name_en: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    inn: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    address_ru: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    address_en: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    signatory_ru: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    signatory_en: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class NdaRequest(Base):
    __tablename__ = "nda_requests"

    nda_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    client_id: Mapped[str] = mapped_column(String(255), ForeignKey("clients.client_id"), nullable=False)
    template_code: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    status: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, default=NDAStatus.NOT_STARTED.value)
    effective_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    term_ru: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    term_en: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    group_company_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("nda_group_companies.id"), nullable=True)
    partner_inn: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    partner_name_ru: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    partner_address_ru: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    partner_name_en: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    partner_address_en: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    partner_signatory_ru: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    partner_signatory_en: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    partner_contact_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    partner_contact_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    partner_contact_phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    paper_copy_required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    generated_file_key: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    generated_file_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    generated_file_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    generated_file_size: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    submitted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        Index("idx_nda_request_client", "client_id"),
        Index("idx_nda_request_status", "status"),
    )


class NdaDocument(Base):
    __tablename__ = "nda_documents"

    doc_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    nda_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("nda_requests.nda_id"), nullable=False)
    doc_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    file_key: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    file_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    file_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    file_size: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    uploaded_by: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.user_id"), nullable=True)
    uploaded_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        Index("idx_nda_doc_nda", "nda_id"),
        Index("idx_nda_doc_type", "doc_type"),
    )


class NdaStatusHistory(Base):
    __tablename__ = "nda_status_history"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    nda_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("nda_requests.nda_id"), nullable=False)
    old_status: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    new_status: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    changed_by: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.user_id"), nullable=True)
    changed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("idx_nda_history_nda", "nda_id"),
        Index("idx_nda_history_date", "changed_at"),
    )


# ======================================================================
# LEGACY MODELS (for backward compatibility with existing routers)
# ======================================================================

class PaymentOrder(Base):
    __tablename__ = "payment_order"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    order_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    client_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    beneficiary_name: Mapped[str] = mapped_column(String(70), nullable=False)
    beneficiary_address: Mapped[str] = mapped_column(String(105), nullable=False)
    destination_account: Mapped[str] = mapped_column(String(35), nullable=False)
    country_bank: Mapped[str] = mapped_column(String(2), nullable=False)
    bic: Mapped[Optional[str]] = mapped_column(String(11), nullable=True)
    bank_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    bank_address: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    transaction_remark: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    remark_mode: Mapped[str] = mapped_column(String(10), nullable=False, default="MANUAL")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="DRAFT")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_payment_order_client", "client_id"),
        Index("idx_payment_order_status", "status"),
        Index("idx_payment_order_bic", "bic"),
    )


class BicDirectory(Base):
    __tablename__ = "bic_directory"

    bic: Mapped[str] = mapped_column(String(11), primary_key=True)
    bank_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    bank_address: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    country: Mapped[Optional[str]] = mapped_column(String(2), nullable=True)


class Entry(Base):
    __tablename__ = "entries"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_list: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    entry_type: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    full_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    name1: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    name2: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    name3: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    name4: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    tittle: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    job_title: Mapped[Optional[str]] = mapped_column(String(2048), nullable=True)
    dob: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    pob: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    alias: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    nationality: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    passport_no: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    identity_no: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    address: Mapped[Optional[str]] = mapped_column(String(4096), nullable=True)
    additional_info: Mapped[Optional[str]] = mapped_column(String(4096), nullable=True)
    load_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)


# ======================================================================
# B2B LEADS
# ======================================================================

class Lead(Base):
    __tablename__ = "leads"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    company_name: Mapped[str] = mapped_column(String(255), nullable=False)
    country: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    contact_person: Mapped[str] = mapped_column(String(255), nullable=False)
    business_email: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    products_interested: Mapped[Optional[list[str]]] = mapped_column(JSON, nullable=True)
    monthly_volume: Mapped[str] = mapped_column(String(100), nullable=False)
    message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_agreed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="new", server_default="new")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_lead_email", "business_email"),
        Index("idx_lead_status", "status"),
        Index("idx_lead_created", "created_at"),
    )


# ======================================================================
# STAFF REPORTS
# ======================================================================

class CustomerReport(Base):
    """Отчет по клиентам (Data Nasabah)"""
    __tablename__ = "customer_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    
    customer_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    registration_number: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    tax_number: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    legal_tax_number_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    legal_tax_number: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    birth_place_date: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    address: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    indonesian_citizenship: Mapped[bool] = mapped_column(Boolean, default=False)
    director_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    occupation: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    gender: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    phone_number: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    recipient_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    recipient_address: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    pep_indicator: Mapped[bool] = mapped_column(Boolean, default=False)
    code_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    business_area: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    
    created_date: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    created_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    updated_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    __table_args__ = (
        Index("idx_customer_reports_created_date", "created_date"),
    )


class TransactionReport(Base):
    """Отчет по транзакциям (Data Transaksi)"""
    __tablename__ = "transaction_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    
    transaction_id: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    customer_report_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("customer_reports.id"), nullable=True)

    sender_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    sender_address: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    sender_bank_bic: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    sender_bank_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    account_holder_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    account_number: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    transaction_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    transaction_purpose: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    fund_source: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    transaction_method: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    currency: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 2), nullable=True)

    recipient_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    recipient_address: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    transfer_fee: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 2), nullable=True)
    beneficiary_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    risk_level: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    dttot_check: Mapped[bool] = mapped_column(Boolean, default=False)
    dpppspm_check: Mapped[bool] = mapped_column(Boolean, default=False)

    customer_report: Mapped[Optional["CustomerReport"]] = relationship("CustomerReport")
    
    created_date: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    created_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    updated_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    __table_args__ = (
        Index("idx_transaction_reports_date", "date"),
        Index("idx_transaction_reports_transaction_id", "transaction_id"),
    )


# ======================================================================
# AML (Anti-Money Laundering) — ComplyAdvantage Integration
# ======================================================================

class AmlCustomer(Base):
    """Клиент AML-скрининга (физ. или юр. лицо)"""
    __tablename__ = "aml_customers"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    client_id: Mapped[Optional[str]] = mapped_column(String(255), ForeignKey("clients.client_id"), nullable=True)
    customer_identifier: Mapped[Optional[str]] = mapped_column(String(255), unique=True, nullable=True)
    external_identifier: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    type: Mapped[str] = mapped_column(String(50), nullable=False, default=AmlCustomerType.PERSON.value)
    risk_level: Mapped[str] = mapped_column(String(50), nullable=False, default=AmlRiskLevel.UNKNOWN.value)
    risk_score: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), nullable=True)
    monitored: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    screening_result: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    raw_response: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    # Risk-score breakdown по категориям (AML/COUNTRY/PRODUCT/CHANNEL и т.д.) —
    # сырой blob от CA `/v2/customers/{id}/scores`. Используется для обоснования
    # итогового risk_level в AML-аудите. Подгружается в GET /customers/{id}/risk.
    risk_score_breakdown: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    last_rescreen_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    screenings: Mapped[list["AmlScreening"]] = relationship("AmlScreening", back_populates="customer", cascade="all, delete-orphan")
    alerts: Mapped[list["AmlAlert"]] = relationship("AmlAlert", back_populates="customer", cascade="all, delete-orphan")
    cases: Mapped[list["AmlCase"]] = relationship("AmlCase", back_populates="customer", cascade="all, delete-orphan")
    risk_overrides: Mapped[list["AmlRiskOverride"]] = relationship("AmlRiskOverride", back_populates="customer", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_aml_customer_identifier", "customer_identifier"),
        Index("idx_aml_customer_external", "external_identifier"),
        Index("idx_aml_customer_risk", "risk_level"),
        Index("idx_aml_customer_monitored", "monitored"),
        Index("idx_aml_customer_client_id", "client_id"),
    )


class AmlScreening(Base):
    """История скринингов AML"""
    __tablename__ = "aml_screenings"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    aml_customer_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("aml_customers.id"), nullable=False)
    screening_type: Mapped[str] = mapped_column(String(50), nullable=False, default=AmlScreeningType.INITIAL.value)
    match_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    raw_response: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_by: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.user_id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    # ComplyAdvantage screening report (PDF) — сохраняется в MinIO после запроса
    # через POST /v2/customers/{id}/reports. Идемпотентно: если задано — отдаём
    # presigned URL без повторного обращения к CA.
    report_s3_key: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    report_generated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    customer: Mapped["AmlCustomer"] = relationship("AmlCustomer", back_populates="screenings")

    __table_args__ = (
        Index("idx_aml_screening_customer", "aml_customer_id"),
    )


class AmlAlert(Base):
    """AML-алерты"""
    __tablename__ = "aml_alerts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    aml_customer_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("aml_customers.id"), nullable=False)
    external_alert_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    title: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    match_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    match_details: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default=AmlAlertStatus.PENDING.value)
    decided_by: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.user_id"), nullable=True)
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    customer: Mapped["AmlCustomer"] = relationship("AmlCustomer", back_populates="alerts")

    __table_args__ = (
        Index("idx_aml_alert_customer", "aml_customer_id"),
        Index("idx_aml_alert_status", "status"),
    )


class AmlCase(Base):
    """AML-кейсы"""
    __tablename__ = "aml_cases"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    aml_customer_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("aml_customers.id"), nullable=False)
    external_case_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    title: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default=AmlCaseStatus.OPEN.value)
    risk_level: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    aml_types: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    closed_by: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.user_id"), nullable=True)
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    customer: Mapped["AmlCustomer"] = relationship("AmlCustomer", back_populates="cases")
    comments: Mapped[list["AmlCaseComment"]] = relationship("AmlCaseComment", back_populates="case", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_aml_case_customer", "aml_customer_id"),
        Index("idx_aml_case_status", "status"),
    )


class AmlCaseComment(Base):
    """Комментарии к AML-кейсам"""
    __tablename__ = "aml_case_comments"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    aml_case_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("aml_cases.id"), nullable=False)
    comment: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.user_id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    case: Mapped["AmlCase"] = relationship("AmlCase", back_populates="comments")

    __table_args__ = (
        Index("idx_aml_comment_case", "aml_case_id"),
    )


class AmlRiskOverride(Base):
    """Ручные корректировки уровня риска"""
    __tablename__ = "aml_risk_overrides"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    aml_customer_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("aml_customers.id"), nullable=False)
    old_risk_level: Mapped[str] = mapped_column(String(50), nullable=False)
    new_risk_level: Mapped[str] = mapped_column(String(50), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.user_id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    customer: Mapped["AmlCustomer"] = relationship("AmlCustomer", back_populates="risk_overrides")

    __table_args__ = (
        Index("idx_aml_risk_override_customer", "aml_customer_id"),
    )
