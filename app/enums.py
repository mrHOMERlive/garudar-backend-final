"""
Enums для приложения
"""
from enum import Enum


class DocumentType(str, Enum):
    """Строго определенные типы документов для POBO"""
    
    # Инвойсы и контракты
    INVOICE = "invoice"
    SALES_CONTRACT = "sales_contract"
    OTHER = "other"
    PAYMENT_PROOF = "payment_proof"
    
    # Word Order (последовательность)
    WORD_ORDER_UNSIGNED = "word_order_unsigned"
    WORD_ORDER_SIGNED_CLIENT = "word_order_signed_client"
    WORD_ORDER_SIGNED_STAFF = "word_order_signed_staff"  # FINAL
    
    # Act Report (последовательность)
    ACT_REPORT_UNSIGNED = "act_report_unsigned"
    ACT_REPORT_SIGNED_CLIENT = "act_report_signed_client"
    ACT_REPORT_SIGNED_STAFF = "act_report_signed_staff"  # FINAL
    
    # MT103 и статус транзакции
    MT103 = "mt103"
    TRANSACTION_STATUS = "transaction_status"


class DocumentSequence:
    """
    FINAL-документы (*_signed_staff) — immutable. Используется для защиты
    от замены без replace_reason в check_final_document().

    Sequence-валидация (unsigned → signed_client → signed_staff) удалена
    намеренно: документы можно загружать в любом порядке.
    """

    FINAL_DOCS = {
        DocumentType.WORD_ORDER_SIGNED_STAFF,
        DocumentType.ACT_REPORT_SIGNED_STAFF,
    }

    @classmethod
    def is_final(cls, doc_type: DocumentType) -> bool:
        """Является ли документ финальным (immutable без replace_reason)"""
        return doc_type in cls.FINAL_DOCS


class KYCStatus(str, Enum):
    """Статусы KYC клиента"""
    
    CREATED = "created"  # клиент создан в системе, KYC ещё не отправлен
    IN_PROGRESS = "in_progress"  # клиент заполняет KYC (есть черновик)
    SUBMITTED = "submitted"  # клиент отправил на проверку
    APPROVED = "approved"  # KYC принят
    REJECTED = "rejected"  # KYC отклонён (с комментарием)
    NEEDS_FIX = "needs_fix"  # возвращено на доработку


class KYCDocumentType(str, Enum):
    """Типы документов для KYC"""
    
    # Корпоративные документы
    CERT_INCORPORATION = "cert_incorporation"  # Сертификат регистрации
    REGISTER_OF_COMMERCE = "register_of_commerce"  # Торговый реестр
    COMPANY_COMMITTEE_LIST = "company_committee_list"  # Список комитета компании
    MEMORANDUM_ARTICLES = "memorandum_articles"  # Устав и учредительные документы
    SHAREHOLDERS_LIST = "shareholders_list"  # Список акционеров
    AUTHORIZED_SIGNATORIES_LIST = "authorized_signatories_list"  # Список уполномоченных подписантов
    PASSPORT_SIGNATORIES = "passport_signatories"  # Паспорта подписантов
    
    # Документы UBO
    UBO_PASSPORT = "ubo_passport"  # Паспорт UBO
    UBO_PROOF_OF_ADDRESS = "ubo_proof_of_address"  # Подтверждение адреса UBO
    
    # Финансовые документы
    BANK_STATEMENT = "bank_statement"  # Банковская выписка
    FINANCIAL_STATEMENTS = "financial_statements"  # Финансовая отчетность
    
    # Прочие
    POWER_OF_ATTORNEY = "power_of_attorney"  # Доверенность
    SIGNED_KYC_DOCUMENT = "signed_kyc_document"  # Подписанный KYC документ
    OTHER = "other"  # Прочее


class NDAStatus(str, Enum):
    """Статусы NDA клиента"""
    
    NOT_STARTED = "not_started"  # NDA ещё не начат
    DRAFT = "draft"  # Черновик
    GENERATED = "generated"  # Файл сформирован и скачан
    SIGNED_UPLOADED = "signed_uploaded"  # Подписанный файл загружен
    SUBMITTED = "submitted"  # Отправлен в staff
    ACCEPTED = "accepted"  # Staff принял
    REJECTED = "rejected"  # Staff отклонил


class AllowedDocTypes:
    """Разрешенные типы документов по ролям"""
    
    CLIENT_UPLOAD = {
        DocumentType.INVOICE,
        DocumentType.SALES_CONTRACT,
        DocumentType.PAYMENT_PROOF,
        DocumentType.WORD_ORDER_SIGNED_CLIENT,
        DocumentType.ACT_REPORT_SIGNED_CLIENT,
        DocumentType.OTHER,
    }
    
    STAFF_UPLOAD = {
        DocumentType.INVOICE,
        DocumentType.WORD_ORDER_UNSIGNED,
        DocumentType.WORD_ORDER_SIGNED_CLIENT,
        DocumentType.WORD_ORDER_SIGNED_STAFF,
        DocumentType.ACT_REPORT_UNSIGNED,
        DocumentType.ACT_REPORT_SIGNED_CLIENT,
        DocumentType.ACT_REPORT_SIGNED_STAFF,
        DocumentType.MT103,
        DocumentType.TRANSACTION_STATUS,
        DocumentType.SALES_CONTRACT,
        DocumentType.PAYMENT_PROOF,
        DocumentType.OTHER,
    }


class BadgeType(str, Enum):
    """Типы бейджей запросов клиента"""
    
    KYC = "kyc"
    SERVICE_AGREEMENT = "service_agreement"
    PLATFORM_TERMS = "platform_terms"
    SLA = "sla"
    DPA = "dpa"
    AML_KYC_COMPLIANCE = "aml_kyc_compliance"
    OTHER_SIGNING = "other_signing"
    OTHER_SUBMIT = "other_submit"


class BadgeStatus(str, Enum):
    """Статусы бейджей запросов"""
    
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    NEED_SIGNING = "need_signing"
    SUBMITTED = "submitted"
    COMPLETED = "completed"


class AccountStatus(str, Enum):
    """Статусы аккаунта клиента"""

    ACTIVE = "active"
    HOLD = "hold"


# ======================================================================
# AML (Anti-Money Laundering)
# ======================================================================

class AmlCustomerType(str, Enum):
    """Тип AML-клиента"""
    PERSON = "person"
    COMPANY = "company"


class AmlRiskLevel(str, Enum):
    """Уровень риска AML"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    UNKNOWN = "unknown"


class AmlAlertStatus(str, Enum):
    """Статус AML-алерта"""
    PENDING = "pending"
    CONFIRMED = "confirmed"
    DISMISSED = "dismissed"


class AmlCaseStatus(str, Enum):
    """Статус AML-кейса"""
    OPEN = "open"
    CLOSED = "closed"


class AmlScreeningType(str, Enum):
    """Тип скрининга"""
    INITIAL = "initial"
    RESCREEN = "rescreen"
