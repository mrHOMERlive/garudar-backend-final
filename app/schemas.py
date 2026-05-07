from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from typing import Optional, Union

from app.validators import (
    normalize_text,
    normalize_country,
    validate_account_number,
    validate_bic,
)


class RoleEnum(str, Enum):
    USER = "USER"
    ADMIN = "ADMIN"


class LoginRequestDto(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # Секунды до истечения access token


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str


class ErrorResponse(BaseModel):
    error: str


class UserDto(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    email: Optional[str] = None
    role: Optional[RoleEnum] = None
    status: Optional[bool] = None
    terms_accepted: bool = False
    terms_accepted_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class EntryDto(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: Optional[int] = None
    sourceList: Optional[str] = Field(None, validation_alias="source_list")
    entryType: Optional[str] = Field(None, validation_alias="entry_type")
    fullName: Optional[str] = Field(None, validation_alias="full_name")
    name1: Optional[str] = None
    name2: Optional[str] = None
    name3: Optional[str] = None
    name4: Optional[str] = None
    tittle: Optional[str] = None
    jobTitle: Optional[str] = Field(None, validation_alias="job_title")
    dob: Optional[str] = None
    pob: Optional[str] = None
    alias: Optional[str] = None
    nationality: Optional[str] = None
    passportNo: Optional[str] = Field(None, validation_alias="passport_no")
    identityNo: Optional[str] = Field(None, validation_alias="identity_no")
    address: Optional[str] = None
    additionalInfo: Optional[str] = Field(None, validation_alias="additional_info")
    loadDate: Optional[date] = Field(None, validation_alias="load_date")


class BulkEntryRequest(BaseModel):
    entries: list[EntryDto]


class OrderPoboDto(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    orderId: Optional[str] = Field(None, validation_alias="order_id")
    clientId: Optional[str] = Field(None, validation_alias="client_id")
    
    amount: Optional[Decimal] = None
    currency: Optional[str] = None
    
    counterpartyId: Optional[str] = Field(None, validation_alias="counterparty_id")
    beneficiaryName: Optional[str] = Field(None, validation_alias="beneficiary_name")
    beneficiaryAdress: Optional[str] = Field(None, validation_alias="beneficiary_adress")
    destinationAccount: Optional[str] = Field(None, validation_alias="destination_account")
    beneficiaryCountry: Optional[str] = Field(None, validation_alias="beneficiary_country")
    
    bankCountry: Optional[str] = Field(None, validation_alias="bank_country")
    bankBic: Optional[str] = Field(None, validation_alias="bank_bic")
    bankName: Optional[str] = Field(None, validation_alias="bank_name")
    bankAddress: Optional[str] = Field(None, validation_alias="bank_address")
    bankManualOverride: bool = Field(
        default=False,
        validation_alias="bank_manual_override",
        description="Если False — bank_name/bank_address подставляются "
                    "из org_directory по BIC. Если True — клиент вводит вручную (audit-log).",
    )
    
    remark: Optional[str] = None
    clientPaymentCurrency: Optional[str] = Field(None, validation_alias="client_payment_currency")
    
    invocieRequired: Optional[bool] = Field(None, validation_alias="invocie_required")
    invocieReceived: Optional[bool] = Field(None, validation_alias="invocie_received")
    paymentProof: Optional[bool] = Field(None, validation_alias="payment_proof")
    nonMandiriExecution: Optional[bool] = Field(None, validation_alias="non_mandiri_execution")
    invoiceNumber: Optional[str] = Field(None, validation_alias="invoice_number")
    
    status: Optional[str] = None
    lastStatus: Optional[datetime] = Field(None, validation_alias="last_status")
    
    include: Optional[bool] = None
    deleted: Optional[bool] = None
    executed: Optional[bool] = None
    
    createdAt: Optional[datetime] = Field(None, validation_alias="created_at")
    updatedAt: Optional[datetime] = Field(None, validation_alias="updated_at")

    # ------------------------------------------------------------------
    # Backend-side validation (ТЗ Sec 7.1)
    # NFKC + trim для всех текстовых полей, чтобы:
    #  - визуально одинаковые символы из разных Unicode-блоков
    #    ложились в БД в одном виде (важно для sanction-сравнений);
    #  - в БД не попадали leading/trailing пробелы и двойные пробелы.
    # Country-коды нормализуем к UPPER.
    # IBAN MOD-97 и BIC+country проверяются ниже в model_validator,
    # потому что им нужны соседние поля (bank_country).
    # ------------------------------------------------------------------
    @field_validator(
        "beneficiaryName", "beneficiaryAdress", "bankName", "bankAddress",
        "remark", "invoiceNumber", "counterpartyId",
        mode="before",
    )
    @classmethod
    def _normalize_text_fields(cls, v):
        return normalize_text(v)

    @field_validator(
        "beneficiaryCountry", "bankCountry", "currency", "clientPaymentCurrency",
        mode="before",
    )
    @classmethod
    def _normalize_country_fields(cls, v):
        return normalize_country(v)

    @model_validator(mode="after")
    def _validate_account_and_bic(self):
        # destination_account: если введён, нормализуем и валидируем
        # (IBAN MOD-97 если страна IBAN-овская, иначе fallback-формат).
        if self.destinationAccount:
            try:
                self.destinationAccount = validate_account_number(
                    self.destinationAccount,
                    self.bankCountry,
                )
            except ValueError as exc:
                raise ValueError(f"destinationAccount: {exc}") from exc
        # bank_bic: если введён, нормализуем и проверяем формат.
        # Если есть bank_country — дополнительно сверяем страну.
        if self.bankBic:
            try:
                self.bankBic = validate_bic(self.bankBic, self.bankCountry)
            except ValueError as exc:
                raise ValueError(f"bankBic: {exc}") from exc
        return self


class CreateClientRequest(BaseModel):
    # Authorization Credentials
    username: str = Field(..., description="Login для авторизации")
    password: str = Field(..., description="Пароль пользователя")
    is_active: bool = Field(default=True, description="Активность пользователя")
    
    # Client Information
    client_name: str = Field(..., description="Название клиента (обязательное)")
    client_alias_1: Optional[str] = Field(None, description="Альтернативное имя 1")
    client_alias_2: Optional[str] = Field(None, description="Альтернативное имя 2")
    client_alias_3: Optional[str] = Field(None, description="Альтернативное имя 3")
    client_reg_number: Optional[str] = Field(None, description="Регистрационный номер")
    client_tax_number: Optional[str] = Field(None, description="Налоговый номер")
    client_reg_country: Optional[str] = Field(None, description="Страна регистрации")
    client_director: Optional[str] = Field(None, description="Имя директора")
    client_mail: str = Field(..., description="Email клиента (обязательное)")
    
    # Document & Signing
    doc_id: Optional[str] = Field(None, description="ID документа (например, AGG/1/20261201)")
    status_sign: Optional[str] = Field(default="not_sent", description="Статус подписания")
    date_signing: Optional[date] = Field(None, description="Дата подписания")
    
    # Group & Reference
    group_id: Optional[str] = Field(None, description="ID группы")
    group_name: Optional[str] = Field(None, description="Название группы")
    
    # Additional
    description: Optional[str] = Field(None, description="Дополнительные заметки")


class ClientResponse(BaseModel):
    user_id: str
    client_id: str


class UpdateClientRequest(BaseModel):
    # Authorization Credentials
    username: Optional[str] = Field(None, description="Login для авторизации")
    password: Optional[str] = Field(None, description="Пароль пользователя")
    is_active: Optional[bool] = Field(None, description="Активность пользователя")
    
    # Client Information
    client_name: Optional[str] = Field(None, description="Название клиента")
    client_alias_1: Optional[str] = Field(None, description="Альтернативное имя 1")
    client_alias_2: Optional[str] = Field(None, description="Альтернативное имя 2")
    client_alias_3: Optional[str] = Field(None, description="Альтернативное имя 3")
    client_reg_number: Optional[str] = Field(None, description="Регистрационный номер")
    client_tax_number: Optional[str] = Field(None, description="Налоговый номер")
    client_reg_country: Optional[str] = Field(None, description="Страна регистрации")
    client_director: Optional[str] = Field(None, description="Имя директора")
    client_mail: Optional[str] = Field(None, description="Email клиента")
    
    # Document & Signing
    doc_id: Optional[str] = Field(None, description="ID документа")
    status_sign: Optional[str] = Field(None, description="Статус подписания")
    date_signing: Optional[date] = Field(None, description="Дата подписания")
    
    # Group & Reference
    group_id: Optional[str] = Field(None, description="ID группы")
    group_name: Optional[str] = Field(None, description="Название группы")
    
    # Account Status
    account_status: Optional[str] = Field(None, description="Статус аккаунта: 'active' или 'hold'")
    account_hold_reason: Optional[str] = Field(None, description="Причина блокировки аккаунта")

    # KYC override (admin only)
    kyc_override: Optional[bool] = Field(
        None,
        description="Разрешить создание заявок без kyc_status='approved'. Только admin."
    )

    # Additional
    description: Optional[str] = Field(None, description="Дополнительные заметки")


class ClientDto(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    client_id: str
    client_name: Optional[str] = None
    client_alias_1: Optional[str] = None
    client_alias_2: Optional[str] = None
    client_alias_3: Optional[str] = None
    client_reg_number: Optional[str] = None
    client_tax_number: Optional[str] = None
    client_reg_country: Optional[str] = None
    doc_id: Optional[str] = None
    status_sign: Optional[str] = None
    date_signing: Optional[date] = None
    group_id: Optional[str] = None
    group_name: Optional[str] = None
    client_director: Optional[str] = None
    client_mail: Optional[str] = None
    last_id: Optional[int] = None
    kyc_status: Optional[str] = None
    kyc_submitted_at: Optional[datetime] = None
    kyc_decided_at: Optional[datetime] = None
    kyc_decided_by: Optional[str] = None
    kyc_override: bool = Field(default=False, description="Админ-флаг: разрешает создавать заявки без KYC approved")
    nda_status: Optional[str] = None
    account_status: Optional[str] = Field(default="active", description="Статус аккаунта")
    account_hold_reason: Optional[str] = Field(None, description="Причина блокировки")
    aml_risk_level: Optional[str] = Field(None, description="Наивысший уровень AML-риска (low/medium/high/unknown)")
    active_badges_count: Optional[int] = Field(default=0, description="Количество активных бейджей")
    attention_required_count: Optional[int] = Field(default=0, description="Количество бейджей требующих внимания")
    user_id: str
    username: Optional[str] = None
    is_active: Optional[bool] = None


class OrderPoboTermCreateUpdateRequest(BaseModel):
    """Схема для создания/обновления условий POBO заказа (от staff)"""
    remuneration_type: str = Field(..., description="Тип вознаграждения: 'percent' или 'fixed'")
    remuneration_percentage: Optional[Decimal] = Field(None, description="Процент вознаграждения (если type=percent)")
    remuneration_fixed: Optional[Decimal] = Field(None, description="Фиксированное вознаграждение (если type=fixed)")
    exchange_rate: Decimal = Field(..., description="Курс обмена (заполняется вручную)")
    client_payment_currency: Optional[str] = Field(None, description="Валюта оплаты клиента")
    date_paid: Optional[date] = Field(None, description="Дата оплаты")
    data_fixing: Optional[date] = Field(None, description="Дата фиксации")
    GAN_bank_name: Optional[str] = Field(None, description="Название банка GAN")
    GAN_bank_account: Optional[str] = Field(None, description="Номер счета GAN")
    date_report: Optional[date] = Field(None, description="Дата отчета")
    conversion_method: Optional[str] = Field(None, description="Метод конвертации (например, 'Central Bank official rate')")
    base_currency: Optional[str] = Field(None, description="Базовая валюта")
    FX: Optional[bool] = Field(None, description="Флаг валютной операции")
    executing_bank: Optional[str] = Field(None, description="Исполняющий банк (account_no из payeer_accounts)")
    FX_executing_bank: Optional[Decimal] = Field(None, description="Курс исполняющего банка")
    status: Optional[str] = Field(None, description="Статус")
    bank_statement_in_type: Optional[str] = Field(None, description="Тип входящей банковской выписки")
    bank_statement_in_id: Optional[str] = Field(None, description="ID входящей банковской выписки")
    bank_statement_out_type: Optional[str] = Field(None, description="Тип исходящей банковской выписки")
    bank_statement_out_id: Optional[str] = Field(None, description="ID исходящей банковской выписки")
    amount_to_be_paid_target_cur: Optional[Decimal] = Field(None, description="Сумма к оплате в целевой валюте")
    amount_paid_target_cur: Optional[Decimal] = Field(None, description="Оплаченная сумма в целевой валюте")
    doc_paid_no: Optional[str] = Field(None, description="Номер документа оплаты")
    doc_paid_date: Optional[date] = Field(None, description="Дата документа оплаты")
    payment_proof_no: Optional[str] = Field(None, description="Номер подтверждения оплаты")
    payment_proof_date: Optional[date] = Field(None, description="Дата подтверждения оплаты")
    description: Optional[str] = Field(None, description="Описание")


class OrderPoboTermDto(BaseModel):
    """Схема для ответа с условиями POBO заказа"""
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)
    
    termId: Optional[int] = Field(None, validation_alias="term_id")
    orderId: Optional[str] = Field(None, validation_alias="order_id")
    clientId: Optional[str] = Field(None, validation_alias="client_id")
    
    amount: Optional[Decimal] = None
    currency: Optional[str] = None
    
    clientPaymentCurrency: Optional[str] = Field(None, validation_alias="client_payment_currency")
    datePaid: Optional[date] = Field(None, validation_alias="date_paid")
    dataFixing: Optional[date] = Field(None, validation_alias="data_fixing")
    
    remunerationType: Optional[str] = Field(None, validation_alias="remuneration_type")
    remunerationPercentage: Optional[Decimal] = Field(None, validation_alias="remuneration_percentage")
    remunerationFixed: Optional[Decimal] = Field(None, validation_alias="remuneration_fixed")
    
    amountRemuneration: Optional[Decimal] = Field(None, validation_alias="amount_remuneration")
    amountToBePaid: Optional[Decimal] = Field(None, validation_alias="amount_to_be_paid")
    
    exchangeRate: Optional[Decimal] = Field(None, validation_alias="exchange_rate")
    exchangeRateManual: Optional[Decimal] = Field(None, validation_alias="exchange_rate_manual")
    
    GANBankName: Optional[str] = Field(None, validation_alias="GAN_bank_name")
    GANBankAccount: Optional[str] = Field(None, validation_alias="GAN_bank_account")
    dateReport: Optional[date] = Field(None, validation_alias="date_report")
    conversionMethod: Optional[str] = Field(None, validation_alias="conversion_method")
    baseCurrency: Optional[str] = Field(None, validation_alias="base_currency")
    FX: Optional[bool] = None
    executingBank: Optional[str] = Field(None, validation_alias="executing_bank")
    FXExecutingBank: Optional[Decimal] = Field(None, validation_alias="FX_executing_bank")
    status: Optional[str] = None
    
    bankStatementInType: Optional[str] = Field(None, validation_alias="bank_statement_in_type")
    bankStatementInId: Optional[str] = Field(None, validation_alias="bank_statement_in_id")
    bankStatementOutType: Optional[str] = Field(None, validation_alias="bank_statement_out_type")
    bankStatementOutId: Optional[str] = Field(None, validation_alias="bank_statement_out_id")
    amountToBePaidTargetCur: Optional[Decimal] = Field(None, validation_alias="amount_to_be_paid_target_cur")
    amountPaidTargetCur: Optional[Decimal] = Field(None, validation_alias="amount_paid_target_cur")
    docPaidNo: Optional[str] = Field(None, validation_alias="doc_paid_no")
    docPaidDate: Optional[date] = Field(None, validation_alias="doc_paid_date")
    paymentProofNo: Optional[str] = Field(None, validation_alias="payment_proof_no")
    paymentProofDate: Optional[date] = Field(None, validation_alias="payment_proof_date")
    description: Optional[str] = None


class ExportInstructionRequest(BaseModel):
    """Схема для запроса экспорта инструкций"""
    order_ids: list[str] = Field(..., description="Список order_id для экспорта")


class ExportInstructionResponse(BaseModel):
    """Схема для ответа после экспорта"""
    export_id: int
    file_name: str
    exported_count: int
    skipped_count: int
    message: str


# ========== Document Schemas ==========

class OrderDocumentDto(BaseModel):
    """DTO для отображения документа (без file_url)"""
    doc_id: int
    order_id: str
    doc_type: str
    file_name: str
    file_size: int
    uploaded_by: str
    uploaded_at: datetime
    
    model_config = ConfigDict(from_attributes=True)


class DocumentUploadResponse(BaseModel):
    """Ответ при загрузке документа"""
    doc_id: int
    doc_type: str
    file_name: str
    file_size: int
    uploaded_at: datetime
    message: str


class PresignedUrlResponse(BaseModel):
    """Ответ с presigned URL для скачивания"""
    presigned_url: str
    expires_in: int
    file_name: str
    message: str


# ========== PayeerAccount Schemas ==========

class PayeerAccountDto(BaseModel):
    """DTO для отображения Payeer аккаунта"""
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    account_no: str
    alias: Optional[str] = None
    currency: Optional[str] = None
    status: Optional[str] = None
    bank_name: Optional[str] = None
    bank_address: Optional[str] = None
    bank_corr_account: Optional[str] = None
    bank_bic: Optional[str] = None
    bank_country: Optional[str] = None


class PayeerAccountCreateRequest(BaseModel):
    """Схема для создания Payeer аккаунта"""
    account_no: str = Field(..., description="Номер счета Payeer")
    alias: Optional[str] = Field(None, description="Алиас для идентификации счёта")
    currency: Optional[str] = Field(None, description="Код валюты")
    status: Optional[str] = Field(None, description="Статус аккаунта")
    bank_name: Optional[str] = Field(None, description="Название банка")
    bank_address: Optional[str] = Field(None, description="Адрес банка")
    bank_corr_account: Optional[str] = Field(None, description="Корреспондентский счет банка")
    bank_bic: Optional[str] = Field(None, description="БИК банка")
    bank_country: Optional[str] = Field(None, description="Страна банка")


class PayeerAccountUpdateRequest(BaseModel):
    """Схема для обновления Payeer аккаунта"""
    account_no: Optional[str] = Field(None, description="Номер счета Payeer")
    alias: Optional[str] = Field(None, description="Алиас для идентификации счёта")
    currency: Optional[str] = Field(None, description="Код валюты")
    status: Optional[str] = Field(None, description="Статус аккаунта")
    bank_name: Optional[str] = Field(None, description="Название банка")
    bank_address: Optional[str] = Field(None, description="Адрес банка")
    bank_corr_account: Optional[str] = Field(None, description="Корреспондентский счет банка")
    bank_bic: Optional[str] = Field(None, description="БИК банка")
    bank_country: Optional[str] = Field(None, description="Страна банка")


# ========== ExecutedOrder Schemas ==========

class ExecutedOrderUpdateRequest(BaseModel):
    """Схема для обновления выполненного заказа (только для админов)"""
    doc_package_status: Optional[str] = Field(None, description="Статус пакета документов")
    mt103_status: Optional[str] = Field(None, description="Статус MT103")
    settled_status: Optional[str] = Field(None, description="Статус расчетов")
    refund_flag: Optional[str] = Field(None, description="Флаг возврата")
    staff_description: Optional[str] = Field(None, description="Описание от персонала")
    mt103_file_url: Optional[str] = Field(None, description="URL файла MT103")
    mt103_no: Optional[str] = Field(None, description="Номер MT103")
    mt103_date: Optional[date] = Field(None, description="Дата MT103")
    transaction_status_file_url: Optional[str] = Field(None, description="URL файла статуса транзакции")
    transaction_status_no: Optional[str] = Field(None, description="Номер статуса транзакции")
    transaction_status_date: Optional[date] = Field(None, description="Дата статуса транзакции")
    transaction_status_status: Optional[str] = Field(None, description="Статус транзакции")
    act_report_file_url: Optional[str] = Field(None, description="URL файла акта/отчета")
    act_report_no: Optional[str] = Field(None, description="Номер акта/отчета")
    act_report_date: Optional[date] = Field(None, description="Дата акта/отчета")


class ExecutedOrderDto(BaseModel):
    """DTO для отображения выполненного заказа"""
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)
    
    executedId: int = Field(..., validation_alias="executed_id")
    sourceOrderId: Optional[str] = Field(None, validation_alias="source_order_id")
    
    docPackageStatus: Optional[str] = Field(None, validation_alias="doc_package_status")
    mt103Status: Optional[str] = Field(None, validation_alias="mt103_status")
    settledStatus: Optional[str] = Field(None, validation_alias="settled_status")
    refundFlag: Optional[str] = Field(None, validation_alias="refund_flag")
    staffDescription: Optional[str] = Field(None, validation_alias="staff_description")
    
    mt103FileUrl: Optional[str] = Field(None, validation_alias="mt103_file_url")
    mt103No: Optional[str] = Field(None, validation_alias="mt103_no")
    mt103Date: Optional[date] = Field(None, validation_alias="mt103_date")
    
    transactionStatusFileUrl: Optional[str] = Field(None, validation_alias="transaction_status_file_url")
    transactionStatusNo: Optional[str] = Field(None, validation_alias="transaction_status_no")
    transactionStatusDate: Optional[date] = Field(None, validation_alias="transaction_status_date")
    transactionStatusStatus: Optional[str] = Field(None, validation_alias="transaction_status_status")
    
    actReportFileUrl: Optional[str] = Field(None, validation_alias="act_report_file_url")
    actReportNo: Optional[str] = Field(None, validation_alias="act_report_no")
    actReportDate: Optional[date] = Field(None, validation_alias="act_report_date")
    
    movedAt: Optional[datetime] = Field(None, validation_alias="moved_at")
    movedBy: Optional[str] = Field(None, validation_alias="moved_by")


class LastInstructionExportResponse(BaseModel):
    """Ответ с информацией о последнем экспорте txt инструкции"""
    order_id: str
    last_export_date: Optional[datetime] = Field(None, description="Дата последнего экспорта инструкции")
    export_count: int = Field(..., description="Количество раз, когда заказ был экспортирован")
    message: str


# ========== KYC Profile Schemas ==========

class KYCCorporateDetailsDto(BaseModel):
    """Корпоративные данные для KYC"""
    company_name: Optional[str] = Field(None, description="Полное наименование компании")
    trading_name: Optional[str] = Field(None, description="Торговое наименование")
    incorporation_date: Optional[date] = Field(None, description="Дата регистрации компании")
    incorporation_country: Optional[str] = Field(None, description="Страна регистрации")
    registration_number: Optional[str] = Field(None, description="Регистрационный номер компании")
    tax_id: Optional[str] = Field(None, description="Налоговый идентификатор (ИНН)")
    registered_address: Optional[str] = Field(None, description="Зарегистрированный адрес")
    telephone: Optional[str] = Field(None, description="Телефон")
    website: Optional[str] = Field(None, description="Веб-сайт")


class KYCBankingDetailsDto(BaseModel):
    """Банковские реквизиты для KYC"""
    principal_bankers: Optional[str] = Field(None, description="Основной банк")
    swift_bic: Optional[str] = Field(None, description="SWIFT/BIC код")
    bank_branch_address: Optional[str] = Field(None, description="Адрес отделения банка")
    bank_city_country: Optional[str] = Field(None, description="Город и страна банка")
    bank_account_name: Optional[str] = Field(None, description="Наименование счета")
    bank_account_currency: Optional[str] = Field(None, description="Валюта счета")
    bank_account_number: Optional[str] = Field(None, description="Номер счета")
    bank_manager_contact: Optional[str] = Field(None, description="Контакт менеджера банка")


class KYCDeclarationDto(BaseModel):
    """Данные декларации для KYC"""
    declaration_confirmed: Optional[bool] = Field(None, description="Декларация подтверждена")
    authorized_person_name: Optional[str] = Field(None, description="Имя уполномоченного лица")
    signature_date: Optional[date] = Field(None, description="Дата подписания")
    authorized_person_position: Optional[str] = Field(None, description="Должность уполномоченного лица")
    signature_location: Optional[str] = Field(None, description="Место подписания")
    signed_kyc_document_url: Optional[str] = Field(None, description="URL подписанного KYC документа")


class KYCProfilePayload(BaseModel):
    """Полная структура данных KYC профиля"""
    corporate: Optional[KYCCorporateDetailsDto] = Field(None, description="Корпоративные данные")
    banking: Optional[KYCBankingDetailsDto] = Field(None, description="Банковские реквизиты")
    declaration: Optional[KYCDeclarationDto] = Field(None, description="Декларация")


class KYCProfileUpdateRequest(BaseModel):
    """Запрос на создание/обновление KYC профиля"""
    company_name: Optional[str] = None
    trading_name: Optional[str] = None
    incorporation_date: Optional[date] = None
    incorporation_country: Optional[str] = None
    registration_number: Optional[str] = None
    tax_id: Optional[str] = None
    registered_address: Optional[str] = None
    telephone: Optional[str] = None
    website: Optional[str] = None
    principal_bankers: Optional[str] = None
    swift_bic: Optional[str] = None
    bank_branch_address: Optional[str] = None
    bank_city_country: Optional[str] = None
    bank_account_name: Optional[str] = None
    bank_account_currency: Optional[str] = None
    bank_account_number: Optional[str] = None
    bank_manager_contact: Optional[str] = None
    declaration_confirmed: Optional[bool] = None
    authorized_person_name: Optional[str] = None
    signature_date: Optional[date] = None
    authorized_person_position: Optional[str] = None
    signature_location: Optional[str] = None
    signed_kyc_document_url: Optional[str] = None

    # ТЗ Sec 7.1: NFKC + trim для всех текстовых полей KYC.
    # Особенно важно для company_name / authorized_person_name —
    # они идут в sanction-screening, где визуально одинаковые
    # символы из разных Unicode-блоков дают разные хэши.
    @field_validator(
        "company_name", "trading_name", "registration_number", "tax_id",
        "registered_address", "telephone", "website", "principal_bankers",
        "swift_bic", "bank_branch_address", "bank_city_country",
        "bank_account_name", "bank_account_currency", "bank_account_number",
        "bank_manager_contact", "authorized_person_name",
        "authorized_person_position", "signature_location",
        "incorporation_country",
        mode="before",
    )
    @classmethod
    def _normalize_kyc_text(cls, v):
        return normalize_text(v)


class KYCProfileResponse(BaseModel):
    """Ответ с данными KYC профиля"""
    model_config = ConfigDict(from_attributes=True)
    
    profile_id: int
    client_id: str
    status: str
    version: int
    data: KYCProfilePayload
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    submitted_at: Optional[datetime] = None
    decided_at: Optional[datetime] = None
    decided_by: Optional[str] = None
    decision_comment: Optional[str] = None


class KYCSubmitResponse(BaseModel):
    """Ответ после отправки KYC на проверку"""
    profile_id: int
    client_id: str
    status: str
    submitted_at: datetime
    message: str


# ========== UBO (Ultimate Beneficial Owners) Schemas ==========

class UBOCreateRequest(BaseModel):
    """Запрос на создание UBO"""
    ubo_name: str = Field(..., description="Имя конечного бенефициара")
    shareholding_percent: Decimal = Field(..., description="Процент владения (0-100)", ge=0, le=100)
    nationality: Optional[str] = Field(None, description="Гражданство")
    residence_country: Optional[str] = Field(None, description="Страна резидентства (2-буквенный код)")


class UBOUpdateRequest(BaseModel):
    """Запрос на обновление UBO"""
    ubo_name: Optional[str] = Field(None, description="Имя конечного бенефициара")
    shareholding_percent: Optional[Decimal] = Field(None, description="Процент владения (0-100)", ge=0, le=100)
    nationality: Optional[str] = Field(None, description="Гражданство")
    residence_country: Optional[str] = Field(None, description="Страна резидентства (2-буквенный код)")


class UBOResponse(BaseModel):
    """Ответ с данными UBO"""
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    profile_id: int
    ubo_name: Optional[str] = None
    shareholding_percent: Optional[Decimal] = None
    nationality: Optional[str] = None
    residence_country: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


# ========== KYC Documents Schemas ==========

class KYCDocumentDto(BaseModel):
    """DTO для отображения KYC документа"""
    model_config = ConfigDict(from_attributes=True)
    
    doc_id: int
    profile_id: int
    doc_type: str
    file_name: str
    file_size: int
    uploaded_by: Optional[str] = None
    uploaded_at: Optional[datetime] = None
    is_required: bool
    comment: Optional[str] = None


class KYCDocumentUploadResponse(BaseModel):
    """Ответ при загрузке KYC документа"""
    doc_id: int
    doc_type: str
    file_name: str
    file_size: int
    uploaded_at: datetime
    message: str


# ========== Admin KYC Schemas ==========

class KYCQueueItemDto(BaseModel):
    """DTO для элемента очереди KYC заявок (для админа)"""
    model_config = ConfigDict(from_attributes=True)
    
    profile_id: int
    client_id: str
    company_name: Optional[str] = Field(None, description="Название компании из corporate данных")
    client_name: Optional[str] = Field(None, description="Имя клиента из таблицы clients")
    client_email: Optional[str] = Field(None, description="Email клиента")
    submitted_at: Optional[datetime] = Field(None, description="Дата отправки на проверку")
    status: str = Field(..., description="Текущий статус KYC")


class KYCDecisionRequest(BaseModel):
    """Запрос на принятие решения по KYC (approve/reject)"""
    status: str = Field(..., description="Решение: 'approved' или 'rejected'")
    comment: Optional[str] = Field(None, description="Комментарий к решению (обязателен при отклонении)")


class KYCDecisionResponse(BaseModel):
    """Ответ после принятия решения по KYC"""
    profile_id: int
    client_id: str
    status: str
    decided_at: datetime
    decided_by: str
    decision_comment: Optional[str] = None
    message: str


# ========== Client Request Badges Schemas ==========

class ClientRequestBadgeDto(BaseModel):
    """DTO для отображения бейджа запроса клиента"""
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    client_id: str
    badge_type: str
    status: str
    is_active: bool
    staff_comment: Optional[str] = None
    document_url: Optional[str] = None
    submitted_document_url: Optional[str] = None
    updated_at: datetime


class ClientBadgeUserDto(BaseModel):
    """DTO для отображения бейджа клиенту (User Dashboard)"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    badge_type: str
    status: str
    is_active: bool
    staff_comment: Optional[str] = None
    document_url: Optional[str] = None
    submitted_document_url: Optional[str] = None


class ClientRequestBadgeUpdateRequest(BaseModel):
    """Запрос на создание/обновление бейджа (Upsert)"""
    status: Optional[str] = Field(None, description="Статус бейджа")
    is_active: Optional[bool] = Field(None, description="Активность бейджа")
    staff_comment: Optional[str] = Field(None, description="Комментарий сотрудника")
    document_url: Optional[str] = Field(None, description="Ссылка на шаблон/сгенерированный документ")
    submitted_document_url: Optional[str] = Field(None, description="Ссылка на загруженный клиентом документ")


# ======================================================================
# NDA SCHEMAS
# ======================================================================

_NDA_TEXT_FIELDS = (
    "template_code", "term_ru", "term_en", "partner_inn",
    "partner_name_ru", "partner_name_en", "partner_address_ru",
    "partner_address_en", "partner_signatory_ru", "partner_signatory_en",
    "partner_contact_name", "partner_contact_email", "partner_contact_phone",
)


class NDARequestCreateDto(BaseModel):
    """Запрос на создание NDA заявки"""
    effective_date: Optional[date] = Field(None, description="Дата вступления в силу")
    template_code: Optional[str] = Field(None, description="Код шаблона NDA")
    term_ru: Optional[str] = Field(None, description="Срок действия (рус)")
    term_en: Optional[str] = Field(None, description="Срок действия (англ)")
    group_company_id: Optional[int] = Field(None, description="ID компании группы")
    partner_inn: Optional[str] = Field(None, description="ИНН партнера")
    partner_name_ru: Optional[str] = Field(None, description="Наименование партнера (рус)")
    partner_name_en: Optional[str] = Field(None, description="Наименование партнера (англ)")
    partner_address_ru: Optional[str] = Field(None, description="Адрес партнера (рус)")
    partner_address_en: Optional[str] = Field(None, description="Адрес партнера (англ)")
    partner_signatory_ru: Optional[str] = Field(None, description="Подписант партнера (рус)")
    partner_signatory_en: Optional[str] = Field(None, description="Подписант партнера (англ)")
    partner_contact_name: Optional[str] = Field(None, description="Контактное лицо партнера")
    partner_contact_email: Optional[str] = Field(None, description="Email контактного лица")
    partner_contact_phone: Optional[str] = Field(None, description="Телефон контактного лица")
    paper_copy_required: Optional[bool] = Field(False, description="Требуется бумажная копия")

    # ТЗ Sec 7.1: NFKC + trim. partner_name_* / partner_signatory_*
    # участвуют в генерации NDA-документа, поэтому канонизация
    # критична — иначе в подписанном документе всплывут «странные»
    # пробелы или дубли.
    @field_validator(*_NDA_TEXT_FIELDS, mode="before")
    @classmethod
    def _normalize_nda_text(cls, v):
        return normalize_text(v)


class NDARequestUpdateDto(BaseModel):
    """Запрос на обновление NDA заявки"""
    status: Optional[str] = Field(None, description="Статус NDA")
    effective_date: Optional[date] = Field(None, description="Дата вступления в силу")
    template_code: Optional[str] = Field(None, description="Код шаблона NDA")
    term_ru: Optional[str] = Field(None, description="Срок действия (рус)")
    term_en: Optional[str] = Field(None, description="Срок действия (англ)")
    group_company_id: Optional[int] = Field(None, description="ID компании группы")
    partner_inn: Optional[str] = Field(None, description="ИНН партнера")
    partner_name_ru: Optional[str] = Field(None, description="Наименование партнера (рус)")
    partner_name_en: Optional[str] = Field(None, description="Наименование партнера (англ)")
    partner_address_ru: Optional[str] = Field(None, description="Адрес партнера (рус)")
    partner_address_en: Optional[str] = Field(None, description="Адрес партнера (англ)")
    partner_signatory_ru: Optional[str] = Field(None, description="Подписант партнера (рус)")
    partner_signatory_en: Optional[str] = Field(None, description="Подписант партнера (англ)")
    partner_contact_name: Optional[str] = Field(None, description="Контактное лицо партнера")
    partner_contact_email: Optional[str] = Field(None, description="Email контактного лица")
    partner_contact_phone: Optional[str] = Field(None, description="Телефон контактного лица")
    paper_copy_required: Optional[bool] = Field(None, description="Требуется бумажная копия")
    generated_file_url: Optional[str] = Field(None, description="URL сгенерированного PDF")

    @field_validator(*_NDA_TEXT_FIELDS, mode="before")
    @classmethod
    def _normalize_nda_text(cls, v):
        return normalize_text(v)


class NDARequestDto(BaseModel):
    """DTO для отображения NDA заявки"""
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: int = Field(validation_alias="nda_id", description="ID заявки NDA")
    client_id: str
    template_code: Optional[str] = None
    status: Optional[str] = None
    effective_date: Optional[date] = None
    term_ru: Optional[str] = None
    term_en: Optional[str] = None
    group_company_id: Optional[int] = None
    partner_inn: Optional[str] = None
    partner_name_ru: Optional[str] = None
    partner_name_en: Optional[str] = None
    partner_address_ru: Optional[str] = None
    partner_address_en: Optional[str] = None
    partner_signatory_ru: Optional[str] = None
    partner_signatory_en: Optional[str] = None
    partner_contact_name: Optional[str] = None
    partner_contact_email: Optional[str] = None
    partner_contact_phone: Optional[str] = None
    paper_copy_required: bool = False
    generated_file_key: Optional[str] = None
    generated_file_url: Optional[str] = None
    generated_file_name: Optional[str] = None
    generated_file_size: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    submitted_at: Optional[datetime] = None


# ======================================================================
# B2B LEADS SCHEMAS
# ======================================================================

class LeadCreate(BaseModel):
    company_name: str = Field(..., min_length=2, max_length=255)
    country: Optional[str] = Field(None, max_length=100)
    contact_person: str = Field(..., min_length=2, max_length=255)
    business_email: str = Field(..., pattern=r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')
    phone: Optional[str] = Field(None, max_length=50)
    products_interested: list[str] = Field(default_factory=list)
    monthly_volume: str = Field(..., min_length=1, max_length=100)
    message: Optional[str] = None
    is_agreed: bool = Field(..., description="User must agree to terms")
    
    website_url: Optional[str] = Field(default="", description="Honeypot field - should be empty")

    @field_validator('is_agreed')
    @classmethod
    def validate_agreement(cls, v):
        if not v:
            raise ValueError('You must agree to the terms')
        return v

    @field_validator('products_interested')
    @classmethod
    def validate_products(cls, v):
        if not v or len(v) == 0:
            raise ValueError('At least one product must be selected')
        return v


class LeadResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    company_name: str
    country: Optional[str]
    contact_person: str
    business_email: str
    phone: Optional[str]
    products_interested: Optional[list[str]]
    monthly_volume: str
    message: Optional[str]
    status: str
    created_at: datetime


class LeadSubmitResponse(BaseModel):
    success: bool
    message: str


# ======================================================================
# STAFF REPORTS SCHEMAS
# ======================================================================

class CustomerReportBase(BaseModel):
    """Базовая схема для Customer Report"""
    customer_type: Optional[str] = Field(None, max_length=50)
    registration_number: Optional[str] = Field(None, max_length=100)
    tax_number: Optional[str] = Field(None, max_length=100)
    legal_tax_number_type: Optional[str] = Field(None, max_length=50)
    legal_tax_number: Optional[str] = Field(None, max_length=100)
    name: str = Field(..., max_length=255)
    birth_place_date: Optional[str] = Field(None, max_length=255)
    address: Optional[str] = None
    indonesian_citizenship: bool = False
    director_name: Optional[str] = Field(None, max_length=255)
    occupation: Optional[str] = Field(None, max_length=255)
    gender: Optional[str] = Field(None, max_length=10)
    phone_number: Optional[str] = Field(None, max_length=50)
    recipient_name: Optional[str] = Field(None, max_length=255)
    recipient_address: Optional[str] = None
    pep_indicator: bool = False
    code_type: Optional[str] = Field(None, max_length=50)
    business_area: Optional[str] = Field(None, max_length=255)


class CustomerReportCreate(CustomerReportBase):
    """Схема для создания Customer Report"""
    pass


class CustomerReportUpdate(BaseModel):
    """Схема для обновления Customer Report"""
    customer_type: Optional[str] = Field(None, max_length=50)
    registration_number: Optional[str] = Field(None, max_length=100)
    tax_number: Optional[str] = Field(None, max_length=100)
    legal_tax_number_type: Optional[str] = Field(None, max_length=50)
    legal_tax_number: Optional[str] = Field(None, max_length=100)
    name: Optional[str] = Field(None, max_length=255)
    birth_place_date: Optional[str] = Field(None, max_length=255)
    address: Optional[str] = None
    indonesian_citizenship: Optional[bool] = None
    director_name: Optional[str] = Field(None, max_length=255)
    occupation: Optional[str] = Field(None, max_length=255)
    gender: Optional[str] = Field(None, max_length=10)
    phone_number: Optional[str] = Field(None, max_length=50)
    recipient_name: Optional[str] = Field(None, max_length=255)
    recipient_address: Optional[str] = None
    pep_indicator: Optional[bool] = None
    code_type: Optional[str] = Field(None, max_length=50)
    business_area: Optional[str] = Field(None, max_length=255)


class CustomerReportDto(CustomerReportBase):
    """DTO для отображения Customer Report"""
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    created_date: datetime
    created_by: Optional[str] = None
    updated_at: Optional[datetime] = None
    updated_by: Optional[str] = None


class TransactionReportBase(BaseModel):
    """Базовая схема для Transaction Report"""
    transaction_id: str = Field(..., max_length=100)
    date: date
    customer_report_id: Optional[int] = None
    sender_name: Optional[str] = Field(None, max_length=255)
    sender_address: Optional[str] = None
    sender_bank_bic: Optional[str] = Field(None, max_length=20)
    sender_bank_name: Optional[str] = Field(None, max_length=255)
    account_holder_name: Optional[str] = Field(None, max_length=255)
    account_number: Optional[str] = Field(None, max_length=100)
    transaction_type: Optional[str] = Field(None, max_length=50)
    transaction_purpose: Optional[str] = None
    fund_source: Optional[str] = Field(None, max_length=255)
    transaction_method: Optional[str] = Field(None, max_length=100)
    currency: Optional[str] = Field(None, max_length=10)
    amount: Optional[Decimal] = None
    recipient_name: Optional[str] = Field(None, max_length=255)
    recipient_address: Optional[str] = None
    transfer_fee: Optional[Decimal] = None
    beneficiary_type: Optional[str] = Field(None, max_length=50)
    risk_level: Optional[str] = Field(None, max_length=20)
    dttot_check: bool = False
    dpppspm_check: bool = False


class TransactionReportCreate(TransactionReportBase):
    """Схема для создания Transaction Report"""
    pass


class TransactionReportUpdate(BaseModel):
    """Схема для обновления Transaction Report"""
    model_config = ConfigDict(extra='ignore')

    transaction_id: Optional[str] = Field(None, max_length=100)
    date: Optional[str] = None
    customer_report_id: Optional[int] = None
    sender_name: Optional[str] = Field(None, max_length=255)
    sender_address: Optional[str] = None
    sender_bank_bic: Optional[str] = Field(None, max_length=20)
    sender_bank_name: Optional[str] = Field(None, max_length=255)
    account_holder_name: Optional[str] = Field(None, max_length=255)
    account_number: Optional[str] = Field(None, max_length=100)
    transaction_type: Optional[str] = Field(None, max_length=50)
    transaction_purpose: Optional[str] = None
    fund_source: Optional[str] = Field(None, max_length=255)
    transaction_method: Optional[str] = Field(None, max_length=100)
    currency: Optional[str] = Field(None, max_length=10)
    amount: Optional[Decimal] = None
    recipient_name: Optional[str] = Field(None, max_length=255)
    recipient_address: Optional[str] = None
    transfer_fee: Optional[Decimal] = None
    beneficiary_type: Optional[str] = Field(None, max_length=50)
    risk_level: Optional[str] = Field(None, max_length=20)
    dttot_check: Optional[bool] = None
    dpppspm_check: Optional[bool] = None


class TransactionReportDto(TransactionReportBase):
    """DTO для отображения Transaction Report"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_date: datetime
    created_by: Optional[str] = None
    updated_at: Optional[datetime] = None
    updated_by: Optional[str] = None


# ======================================================================
# AML (Anti-Money Laundering) — ComplyAdvantage
# ======================================================================

class ScreenPersonRequest(BaseModel):
    """Запрос на скрининг физ. лица"""
    name: str = Field(..., min_length=1, max_length=500)
    date_of_birth: Optional[str] = None  # формат YYYY-MM-DD
    nationality: Optional[str] = Field(None, max_length=2)  # ISO 2-letter
    external_id: Optional[str] = Field(None, max_length=255)


class ScreenCompanyRequest(BaseModel):
    """Запрос на скрининг юр. лица"""
    name: str = Field(..., min_length=1, max_length=500)
    registration_number: Optional[str] = Field(None, max_length=255)
    incorporation_country: Optional[str] = Field(None, max_length=2)  # ISO 2-letter
    external_id: Optional[str] = Field(None, max_length=255)


class AmlCustomerDto(BaseModel):
    """DTO для AML-клиента"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    client_id: Optional[str] = None
    customer_identifier: Optional[str] = None
    external_identifier: Optional[str] = None
    name: str
    type: str
    risk_level: str
    risk_score: Optional[Decimal] = None
    monitored: bool
    status: Optional[str] = None
    screening_result: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None


class AmlAlertDto(BaseModel):
    """DTO для AML-алерта"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    aml_customer_id: int
    external_alert_id: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    match_type: Optional[str] = None
    match_details: Optional[dict] = None
    status: str
    decided_by: Optional[str] = None
    decided_at: Optional[datetime] = None
    created_at: datetime
    customer_name: Optional[str] = None  # денормализованное поле для UI


class AmlAlertDetailsDto(BaseModel):
    """Детализированный DTO для одного AML-алерта.

    Возвращает расширенный match_details (profile/sanctions/pep/adverse_media/sources)
    плюс сырые enriched risks из raw_response.
    """
    model_config = ConfigDict(from_attributes=True)

    id: int
    aml_customer_id: int
    external_alert_id: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    match_type: Optional[str] = None
    match_details: Optional[dict] = None
    raw_risks: Optional[dict] = None  # _enriched_alert_risks[i] — advanced view
    status: str
    created_at: datetime


class AmlCaseDto(BaseModel):
    """DTO для AML-кейса"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    aml_customer_id: int
    external_case_id: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    status: str
    risk_level: Optional[str] = None
    aml_types: Optional[list] = None
    closed_by: Optional[str] = None
    closed_at: Optional[datetime] = None
    created_at: datetime


class AmlCaseCommentDto(BaseModel):
    """DTO для комментария к кейсу"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    aml_case_id: int
    comment: str
    created_by: Optional[str] = None
    created_at: datetime


class AmlScreeningDto(BaseModel):
    """DTO для скрининга"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    aml_customer_id: int
    screening_type: str
    match_count: int
    status: Optional[str] = None
    created_by: Optional[str] = None
    created_at: datetime
    # Признак того, что PDF-отчёт скачан и сохранён в MinIO.
    # UI рендерит «Download PDF» серым при null и «Download saved» при непустом.
    report_s3_key: Optional[str] = None
    report_generated_at: Optional[datetime] = None


# ========== AML Audit & Report DTOs ==========

class AmlCustomerAuditLogDto(BaseModel):
    """Один audit-log-элемент из ComplyAdvantage.

    CA отдаёт discriminated union по `type` — мы не нормализуем `detail`, а
    передаём как есть. UI сам решает, как рендерить (известные типы — понятным
    текстом, остальное — raw JSON в collapsible).
    """
    model_config = ConfigDict(populate_by_name=True)

    identifier: str
    occurredAt: datetime = Field(..., validation_alias="occurred_at")
    type: str
    actionedByType: Optional[str] = Field(None, description="SYSTEM или USER")
    actionedByIdentifier: Optional[str] = Field(None, description="UUID пользователя CA, если type=USER")
    detail: Optional[dict] = None


class AmlAuditLogsPageDto(BaseModel):
    """Пагинированный ответ на GET /customers/{id}/audit."""
    model_config = ConfigDict(populate_by_name=True)

    items: list[AmlCustomerAuditLogDto]
    totalCount: Optional[int] = None
    nextPageNumber: Optional[int] = Field(None, description="None если это последняя страница")


class AmlScreeningReportDto(BaseModel):
    """Ответ на POST /screenings/{id}/report и GET /screenings/{id}/report/download.

    `status`:
    - `ready` — отчёт доступен по `downloadUrl` (presigned URL на 24h)
    - `pending` — CA ещё генерирует, клиент должен попробовать через минуту
    """
    model_config = ConfigDict(populate_by_name=True)

    screeningId: int
    status: str = Field(..., description="ready | pending")
    downloadUrl: Optional[str] = None
    generatedAt: Optional[datetime] = None


class AmlRiskScoreDto(BaseModel):
    """DTO для risk score.

    `breakdown` — сырой CA-ответ с категориями (AML/COUNTRY/PRODUCT/CHANNEL),
    каждая со `score`, `weight`, `level`, `attribute_results[]`. Клиенту UI
    рендерит таблицу из `breakdown.category_results`. Null — если клиент без
    `customer_identifier` или если CA вернул 4xx/5xx (graceful degradation).
    """
    risk_level: str
    score: Optional[Decimal] = None
    factors: Optional[list] = None
    last_updated: Optional[datetime] = None
    breakdown: Optional[dict] = None


class AmlOverrideRiskRequest(BaseModel):
    """Запрос на корректировку уровня риска"""
    risk_level: str = Field(..., pattern="^(low|medium|high|unknown)$")
    reason: str = Field(..., min_length=1)


class AmlCaseCommentRequest(BaseModel):
    """Запрос на добавление комментария"""
    comment: str = Field(..., min_length=1)


class AmlUpdateCaseRequest(BaseModel):
    """Запрос на обновление кейса"""
    status: str = Field(..., pattern="^(open|closed)$")


class AmlMonitoringRequest(BaseModel):
    """Запрос на включение/выключение мониторинга"""
    enabled: bool


class AmlSummaryDto(BaseModel):
    """Статистика AML дашборда"""
    total_customers: int = 0
    high_risk: int = 0
    open_cases: int = 0
    open_alerts: int = 0
    monitored: int = 0
