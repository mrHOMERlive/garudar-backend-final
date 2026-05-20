from pathlib import Path
from fastapi_mail import ConnectionConfig, FastMail, MessageSchema, MessageType
from fastapi_mail.schemas import EmailStr
from app.config import settings
import html
import logging

logger = logging.getLogger(__name__)


def is_email_configured() -> bool:
    """
    Проверяет, настроены ли SMTP параметры
    """
    return (
        settings.MAIL_FROM and 
        "@" in settings.MAIL_FROM and
        settings.SMTP_USER and 
        settings.SMTP_PASSWORD and 
        settings.MAIL_TO_ADMIN and
        "@" in settings.MAIL_TO_ADMIN
    )


def get_email_config() -> ConnectionConfig:
    """
    Создает конфигурацию для fastapi-mail из переменных окружения
    """
    return ConnectionConfig(
        MAIL_USERNAME=settings.SMTP_USER,
        MAIL_PASSWORD=settings.SMTP_PASSWORD,
        MAIL_FROM=settings.MAIL_FROM,
        MAIL_PORT=settings.SMTP_PORT,
        MAIL_SERVER=settings.SMTP_HOST,
        MAIL_FROM_NAME=settings.MAIL_FROM_NAME,
        MAIL_STARTTLS=settings.MAIL_STARTTLS,
        MAIL_SSL_TLS=settings.MAIL_SSL_TLS,
        USE_CREDENTIALS=settings.USE_CREDENTIALS,
        VALIDATE_CERTS=settings.VALIDATE_CERTS
    )


async def send_credentials_email(email: str, username: str, password: str):
    """
    Отправляет письмо клиенту с учётными данными и PDF документом об обязательствах

    Args:
        email: Email клиента
        username: Логин клиента
        password: Пароль в открытом виде (только для отправки)
    """
    if not is_email_configured():
        logger.warning(
            f"Credentials email skipped for {email} — SMTP not configured"
        )
        return

    pdf_path = Path(__file__).parent / "template" / "Obligations Management Password and User ID PT GAN.pdf"

    try:
        conf = get_email_config()

        html_body = f"""
        <html>
            <head>
                <style>
                    body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                    .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                    .header {{ background-color: #1e3a5f; color: white; padding: 24px; text-align: center; border-radius: 8px 8px 0 0; }}
                    .content {{ padding: 24px; background-color: #f9f9f9; border: 1px solid #e0e0e0; }}
                    .credentials {{ background-color: #fff; border: 1px solid #d0d7de; border-radius: 6px; padding: 16px; margin: 16px 0; }}
                    .label {{ font-weight: bold; color: #555; font-size: 13px; }}
                    .value {{ font-family: monospace; font-size: 15px; color: #1e3a5f; }}
                    .note {{ background-color: #fff8e1; border-left: 4px solid #f5a623; padding: 12px; margin: 16px 0; font-size: 13px; }}
                    .footer {{ text-align: center; padding: 16px; font-size: 12px; color: #777; }}
                    a {{ color: #1e3a5f; }}
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="header">
                        <h2 style="margin:0">Welcome to Garudar B2B</h2>
                        <p style="margin:4px 0 0">PT Garuda Arma Nusa</p>
                    </div>
                    <div class="content">
                        <p>Dear Customer,</p>
                        <p>Your account has been created. Please find your login credentials below:</p>
                        <div class="credentials">
                            <p><span class="label">Website: </span><a href="https://garudar.id">https://garudar.id</a></p>
                            <p><span class="label">Username: </span><span class="value">{html.escape(username)}</span></p>
                            <p><span class="label">Password: </span><span class="value">{html.escape(password)}</span></p>
                        </div>
                        <div class="note">
                            <strong>⚠ Important:</strong> Please change your password immediately after your first login.
                            Keep your credentials confidential and do not share them with anyone.
                        </div>
                        <hr style="border:none;border-top:1px solid #e0e0e0;margin:20px 0">
                        <p>Pelanggan yang terhormat,</p>
                        <p>Akun Anda telah dibuat. Berikut adalah kredensial login Anda:</p>
                        <div class="credentials">
                            <p><span class="label">Website: </span><a href="https://garudar.id">https://garudar.id</a></p>
                            <p><span class="label">Username: </span><span class="value">{html.escape(username)}</span></p>
                            <p><span class="label">Password: </span><span class="value">{html.escape(password)}</span></p>
                        </div>
                        <div class="note">
                            <strong>⚠ Penting:</strong> Harap segera ganti password Anda setelah login pertama.
                            Jaga kerahasiaan kredensial Anda dan jangan bagikan kepada siapapun.
                        </div>
                        <p style="margin-top:20px">
                            Please review the attached <strong>Obligations Management Password and User ID</strong> document.
                            You will be asked to accept these obligations upon your first login.
                        </p>
                    </div>
                    <div class="footer">
                        <p>PT Garuda Arma Nusa &mdash; <a href="mailto:info@garudar.id">info@garudar.id</a> &mdash; +6281117796126</p>
                        <p>Ruko Pollux Meisterstadt Blok SH D-10, Batam Center, Kepulauan Riau 29461</p>
                    </div>
                </div>
            </body>
        </html>
        """

        attachments = []
        if pdf_path.exists():
            attachments = [
                {
                    "file": str(pdf_path),
                    "headers": {
                        "Content-Disposition": 'attachment; filename="Obligations Management Password and User ID PT GAN.pdf"',
                        "Content-Type": "application/pdf",
                    },
                }
            ]
        else:
            logger.warning(f"Obligations PDF not found at {pdf_path}, sending email without attachment")

        message = MessageSchema(
            subject="Your Garudar B2B Account Credentials / Kredensial Akun Garudar B2B Anda",
            recipients=[email],
            body=html_body,
            subtype=MessageType.html,
            attachments=attachments,
        )

        fm = FastMail(conf)
        await fm.send_message(message)
        logger.info(f"Credentials email sent to {email} for user {username}")

    except Exception as e:
        logger.error(f"Failed to send credentials email to {email}: {str(e)}", exc_info=True)


async def send_lead_notification(lead_data: dict):
    """
    Отправляет email-уведомление администратору о новом лиде
    
    Args:
        lead_data: Данные лида для отправки
    """
    
    # Проверяем, настроены ли SMTP параметры
    if not is_email_configured():
        logger.warning(
            f"Email notification skipped for lead ID={lead_data.get('id')} - "
            "SMTP settings not configured. Please set MAIL_FROM, SMTP_USER, "
            "SMTP_PASSWORD, and MAIL_TO_ADMIN in .env file"
        )
        return
    
    try:
        conf = get_email_config()
        
        html_body = f"""
        <html>
            <head>
                <style>
                    body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                    .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                    .header {{ background-color: #4CAF50; color: white; padding: 20px; text-align: center; }}
                    .content {{ padding: 20px; background-color: #f9f9f9; }}
                    .field {{ margin-bottom: 15px; }}
                    .label {{ font-weight: bold; color: #555; }}
                    .value {{ color: #333; }}
                    .footer {{ text-align: center; padding: 20px; font-size: 12px; color: #777; }}
                    .products {{ background-color: #e8f5e9; padding: 10px; border-radius: 5px; }}
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="header">
                        <h1>🎯 New B2B Lead!</h1>
                    </div>
                    <div class="content">
                        <div class="field">
                            <span class="label">Company:</span>
                            <span class="value">{html.escape(str(lead_data.get('company_name', 'N/A')))}</span>
                        </div>
                        <div class="field">
                            <span class="label">Country:</span>
                            <span class="value">{html.escape(str(lead_data.get('country', 'N/A')))}</span>
                        </div>
                        <div class="field">
                            <span class="label">Contact Person:</span>
                            <span class="value">{html.escape(str(lead_data.get('contact_person', 'N/A')))}</span>
                        </div>
                        <div class="field">
                            <span class="label">Email:</span>
                            <span class="value">{html.escape(str(lead_data.get('business_email', 'N/A')))}</span>
                        </div>
                        <div class="field">
                            <span class="label">Phone:</span>
                            <span class="value">{html.escape(str(lead_data.get('phone', 'N/A')))}</span>
                        </div>
                        <div class="field">
                            <span class="label">Monthly Volume:</span>
                            <span class="value">{html.escape(str(lead_data.get('monthly_volume', 'N/A')))}</span>
                        </div>
                        <div class="field">
                            <span class="label">Products of Interest:</span>
                            <div class="products">
                                {html.escape(', '.join(lead_data.get('products_interested', [])))}
                            </div>
                        </div>
                        <div class="field">
                            <span class="label">Message:</span>
                            <div class="value">{html.escape(str(lead_data.get('message', 'N/A')))}</div>
                        </div>
                    </div>
                    <div class="footer">
                        <p>This is an automated notification from Garudar B2B System</p>
                        <p>Received: {html.escape(str(lead_data.get('created_at', 'N/A')))}</p>
                    </div>
                </div>
            </body>
        </html>
        """
        
        message = MessageSchema(
            subject=f"🎯 New B2B Lead from {html.escape(str(lead_data.get('company_name', 'N/A')))}",
            recipients=[settings.MAIL_TO_ADMIN],
            body=html_body,
            subtype=MessageType.html
        )
        
        fm = FastMail(conf)
        await fm.send_message(message)
        
        logger.info(f"Email notification sent successfully for lead ID={lead_data.get('id')}")

    except Exception as e:
        logger.error(
            f"Failed to send email notification for lead ID={lead_data.get('id')}: {str(e)}",
            exc_info=True
        )


async def send_service_agreement_status_email(
    email: str,
    client_name: str,
    status: str,
    comment: str | None = None,
) -> None:
    """Уведомление клиента о смене статуса Service Agreement.

    Заглушка: полная реализация (HTML-шаблон, brand-стиль, локализация)
    запланирована в рамках общего email-блока (аудит-пункт №60). Сейчас
    отправляем минимальное plain-text сообщение, чтобы был аудит-trail
    события и dev-видимость в логах. Молча no-op-ает, если SMTP не
    настроен (см. is_email_configured()).
    """
    if not is_email_configured() or not email or "@" not in email:
        logger.info(
            "SA status email skipped (no SMTP or invalid recipient): "
            f"client={client_name}, status={status}"
        )
        return

    try:
        conf = get_email_config()
        subject = f"Service Agreement — статус '{status}'"
        body_lines = [
            f"Здравствуйте, {html.escape(client_name)}.",
            "",
            f"Статус Service Agreement обновлён: {html.escape(status)}.",
        ]
        if comment:
            body_lines.extend(["", f"Комментарий: {html.escape(comment)}"])
        body_lines.extend(["", "С уважением,", "Команда Garudar"])
        body = "<br>".join(body_lines)

        message = MessageSchema(
            subject=subject,
            recipients=[email],
            body=body,
            subtype=MessageType.html,
        )
        fm = FastMail(conf)
        await fm.send_message(message)
        logger.info(f"SA status email sent: client={client_name}, status={status}")
    except Exception as e:
        logger.error(
            f"Failed to send SA status email (client={client_name}, status={status}): {e}",
            exc_info=True,
        )
