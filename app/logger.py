import logging
import re
from typing import Any


class SensitiveDataFilter(logging.Filter):
    """Фильтр для удаления чувствительных данных из логов"""
    
    SENSITIVE_PATTERNS = [
        (re.compile(r'password["\']?\s*[:=]\s*["\']?([^"\'&\s]+)', re.IGNORECASE), 'password=***'),
        (re.compile(r'token["\']?\s*[:=]\s*["\']?([^"\'&\s]+)', re.IGNORECASE), 'token=***'),
        (re.compile(r'api[_-]?key["\']?\s*[:=]\s*["\']?([^"\'&\s]+)', re.IGNORECASE), 'api_key=***'),
        (re.compile(r'secret["\']?\s*[:=]\s*["\']?([^"\'&\s]+)', re.IGNORECASE), 'secret=***'),
        (re.compile(r'authorization:\s*bearer\s+([^\s]+)', re.IGNORECASE), 'Authorization: Bearer ***'),
        (re.compile(r'(sk_live_|sk_test_)[a-zA-Z0-9]+'), '***'),
        (re.compile(r'"password"\s*:\s*"[^"]*"', re.IGNORECASE), '"password": "***"'),
        (re.compile(r'"secret_key"\s*:\s*"[^"]*"', re.IGNORECASE), '"secret_key": "***"'),
    ]
    
    def filter(self, record: logging.LogRecord) -> bool:
        """Маскирует чувствительные данные в сообщениях"""
        if isinstance(record.msg, str):
            for pattern, replacement in self.SENSITIVE_PATTERNS:
                record.msg = pattern.sub(replacement, record.msg)
        return True


def setup_logger(name: str, level: str = "INFO", debug: bool = False) -> logging.Logger:
    """
    Настройка логгера с защитой от утечки чувствительных данных
    
    Args:
        name: Имя логгера
        level: Уровень логирования (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        debug: Режим отладки (если True, логирует полные трейсбеки)
        
    Returns:
        Настроенный логгер
    """
    logger = logging.getLogger(name)
    
    # Очищаем существующие обработчики
    logger.handlers.clear()
    
    # Устанавливаем уровень
    log_level = getattr(logging, level.upper(), logging.INFO)
    logger.setLevel(log_level)
    
    # Создаем обработчик для вывода в консоль
    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level)
    
    # Формат логов
    if debug:
        # В режиме разработки - подробный формат
        formatter = logging.Formatter(
            '[%(asctime)s] %(levelname)s [%(name)s:%(lineno)d] - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
    else:
        # В продакшене - краткий формат без номеров строк
        formatter = logging.Formatter(
            '[%(asctime)s] %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
    
    console_handler.setFormatter(formatter)
    
    # Добавляем фильтр для маскировки чувствительных данных
    console_handler.addFilter(SensitiveDataFilter())
    
    logger.addHandler(console_handler)
    
    return logger


def get_safe_error_details(exc: Exception, debug: bool = False) -> dict[str, Any]:
    """
    Получить безопасные детали ошибки для логирования
    
    Args:
        exc: Исключение
        debug: Режим отладки (если True, включает полный трейсбек)
        
    Returns:
        Словарь с деталями ошибки
    """
    import traceback
    
    details = {
        "type": type(exc).__name__,
        "message": str(exc),
    }
    
    # Полный трейсбек только в режиме разработки
    if debug:
        details["traceback"] = traceback.format_exc()
    
    return details
