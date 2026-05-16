from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.gzip import GZipMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from app.routers import auth, users, orders, entries, dicts, settings, clients, documents, payeer_accounts, kyc, badges, leads, nda, legal, service_agreement, customer_report, transaction_report, aml, aml_webhooks, audit
from app.config import settings as app_settings
from app.logger import setup_logger, get_safe_error_details
import asyncio
from app.s3_client import upload_legal_documents_on_startup
from app.services.sanctions_scheduler import run_sanctions_scheduler
from app.rate_limit import limiter
from typing import List


# Инициализация логгера
logger = setup_logger(
    "garudar_api",
    level=app_settings.LOG_LEVEL,
    debug=app_settings.DEBUG
)


def get_cors_origins() -> List[str]:
    """Получить список разрешенных CORS origins из конфигурации"""
    origins_str = app_settings.CORS_ORIGINS
    
    # Если указан "*", возвращаем как есть (только для разработки)
    if origins_str == "*":
        return ["*"]
    
    # Парсим список доменов, разделенных запятыми
    return [origin.strip() for origin in origins_str.split(",") if origin.strip()]


app = FastAPI(
    title="OpenAPI definition",
    version="v0",
    docs_url="/docs" if app_settings.DEBUG else None,
    redoc_url="/redoc" if app_settings.DEBUG else None,
    openapi_url="/openapi.json" if app_settings.DEBUG else None,
    openapi_tags=[
        {"name": "Authentication", "description": "Auth endpoints"},
        {"name": "Users", "description": "Управление пользователями"},
        {"name": "Clients", "description": "Управление клиентами"},
        {"name": "Client Badges", "description": "Управление бейджами запросов клиентов"},
        {"name": "Payment Orders", "description": "Управление платежными поручениями"},
        {"name": "Documents", "description": "Управление документами POBO"},
        {"name": "Entries", "description": "Управление записями"},
        {"name": "Dictionaries", "description": "Справочники"},
        {"name": "Settings", "description": "Настройки приложения"},
        {"name": "Payeer Accounts", "description": "Управление Payeer аккаунтами"},
        {"name": "KYC", "description": "Управление KYC профилями клиентов"},
        {"name": "leads", "description": "B2B Lead Generation with Honeypot Protection"},
        {"name": "NDA", "description": "Управление NDA заявками"},
        {"name": "Service Agreement", "description": "Генерация Service Agreement из шаблона"},
        {"name": "Legal Documents", "description": "Легальные документы: Privacy Policy, Terms & Conditions"},
        {"name": "Customer Report", "description": "Отчеты по клиентам (Data Nasabah)"},
        {"name": "Transaction Report", "description": "Отчеты по транзакциям (Data Transaksi)"},
        {"name": "AML", "description": "AML скрининг и мониторинг (ComplyAdvantage)"},
    ],
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Обработчик ошибок валидации для детальной диагностики"""
    logger.warning(
        f"Validation error: {request.method} {request.url.path} - {exc.errors()}"
    )
    
    # Детальное логирование только в режиме отладки
    if app_settings.DEBUG:
        logger.debug(f"Validation error body: {exc.body}")
    
    # exc.errors() может содержать в `ctx.error` оригинальный Exception
    # (например, ValueError из @field_validator), который json.dumps
    # сериализовать не умеет — превращаем через jsonable_encoder.
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=jsonable_encoder({
            "detail": exc.errors(),
            "message": "Ошибка валидации запроса"
        })
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Глобальный обработчик всех необработанных исключений"""
    error_details = get_safe_error_details(exc, debug=app_settings.DEBUG)
    
    logger.error(
        f"Unhandled exception: {request.method} {request.url.path} - "
        f"{error_details['type']}: {error_details['message']}"
    )
    
    # Трейсбек логируется только в DEBUG режиме
    if app_settings.DEBUG and "traceback" in error_details:
        logger.debug(f"Traceback:\n{error_details['traceback']}")
    
    content = {"message": "Внутренняя ошибка сервера"}
    if app_settings.DEBUG:
        content["type"] = error_details['type']

    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=content,
    )

# Получаем CORS origins из конфигурации
cors_origins = get_cors_origins()

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True if cors_origins != ["*"] else False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(GZipMiddleware, minimum_size=1000)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if not app_settings.DEBUG:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response


app.add_middleware(SecurityHeadersMiddleware)

app.include_router(auth.router, prefix="/api/v1/auth")
app.include_router(users.router, prefix="/api/v1/users")
app.include_router(clients.router, prefix="/api/v1")
app.include_router(badges.router, prefix="/api/v1")
app.include_router(orders.router, prefix="/api/v1/orders")
app.include_router(documents.router, prefix="/api/v1")
app.include_router(entries.router, prefix="/api/v1/entries")
app.include_router(dicts.router, prefix="/api/v1/dicts")
app.include_router(settings.router, prefix="/api/v1/settings")
app.include_router(payeer_accounts.router, prefix="/api/v1")
app.include_router(kyc.router)
app.include_router(leads.router)
app.include_router(nda.router, prefix="/api/v1")
app.include_router(service_agreement.router, prefix="/api/v1")
app.include_router(legal.router)
app.include_router(customer_report.router, prefix="/api/v1")
app.include_router(transaction_report.router, prefix="/api/v1")
app.include_router(aml.router)
app.include_router(aml_webhooks.router)
app.include_router(audit.router)


@app.on_event("startup")
async def startup_event():
    """Инициализация при старте приложения"""
    logger.info("Starting up application...")
    try:
        await upload_legal_documents_on_startup()
        logger.info("Legal documents initialization completed")
    except Exception as e:
        logger.error(f"Failed to upload legal documents on startup: {e}")

    # Запуск ежедневной синхронизации санкционных списков
    asyncio.create_task(run_sanctions_scheduler())


@app.get("/")
async def root():
    return {"message": "Garudar API"}


@app.get("/health")
async def health():
    return {"status": "ok"}
