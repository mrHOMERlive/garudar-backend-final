"""
Backend-side валидация полей платёжных данных.

ТЗ Sec 7.1 требует, чтобы критичные проверки (NFKC, IBAN MOD-97,
BIC+country) выполнялись не только на UI, но и на бэке — иначе
клиент может отправить «некорректные» данные напрямую через API,
минуя браузер.

Все валидаторы:
- идемпотентны (повторная нормализация даёт тот же результат);
- поднимают ValueError с человекочитаемым сообщением — Pydantic
  автоматически превратит в 422 с детализацией по полям.
"""
import re
import unicodedata
from typing import Optional


# IBAN length per ISO 13616. Зеркало UI-валидатора
# (site/garudar-frontend/src/components/remittance/utils/validators.jsx).
IBAN_LENGTHS: dict[str, int] = {
    "AD": 24, "AE": 23, "AL": 28, "AT": 20, "AZ": 28, "BA": 20, "BE": 16,
    "BG": 22, "BH": 22, "BR": 29, "BY": 28, "CH": 21, "CR": 22, "CY": 28,
    "CZ": 24, "DE": 22, "DK": 18, "DO": 28, "EE": 20, "EG": 29, "ES": 24,
    "FI": 18, "FO": 18, "FR": 27, "GB": 22, "GE": 22, "GI": 23, "GL": 18,
    "GR": 27, "GT": 28, "HR": 21, "HU": 28, "IE": 22, "IL": 23, "IS": 26,
    "IT": 27, "JO": 30, "KW": 30, "KZ": 20, "LB": 28, "LC": 32, "LI": 21,
    "LT": 20, "LU": 20, "LV": 21, "MC": 27, "MD": 24, "ME": 22, "MK": 19,
    "MR": 27, "MT": 31, "MU": 30, "NL": 18, "NO": 15, "PK": 24, "PL": 28,
    "PS": 29, "PT": 25, "QA": 29, "RO": 24, "RS": 22, "SA": 24, "SE": 24,
    "SI": 19, "SK": 24, "SM": 27, "TN": 24, "TR": 26, "UA": 29, "VA": 22,
    "VG": 24, "XK": 20,
}

_BIC_PATTERN = re.compile(r"^[A-Z]{6}[A-Z0-9]{2}([A-Z0-9]{3})?$")
_DOUBLE_SPACE_PATTERN = re.compile(r" {2,}")


def normalize_text(value: Optional[str]) -> Optional[str]:
    """
    NFKC-нормализация + trim + схлопывание двойных пробелов.

    NFKC ("Compatibility Decomposition, followed by Canonical
    Composition") нужен, чтобы визуально одинаковые символы из разных
    Unicode-блоков (например, «А» латинская vs «А» кириллическая или
    half-width vs full-width японские) сохранялись в БД в одном
    каноническом виде. Это критично для точного сравнения и поиска
    sanction-листов / KYC.

    None → None, пустая строка после трима → None (чтобы Optional
    поля сохраняли семантику «не задано», а не «пустая строка»).
    """
    if value is None:
        return None
    if not isinstance(value, str):
        return value  # Pydantic сам поднимет ошибку на не-строке
    normalized = unicodedata.normalize("NFKC", value).strip()
    normalized = _DOUBLE_SPACE_PATTERN.sub(" ", normalized)
    return normalized or None


def _iban_mod97(iban: str) -> int:
    """Вычислить остаток MOD-97 для уже подготовленной IBAN-строки."""
    rearranged = iban[4:] + iban[:4]
    # Каждую букву заменяем её позицией в алфавите + 9
    # (A=10, B=11, ..., Z=35 — стандарт ISO 13616).
    numeric = "".join(
        str(ord(ch) - 55) if ch.isalpha() else ch for ch in rearranged
    )
    remainder = 0
    for ch in numeric:
        remainder = (remainder * 10 + int(ch)) % 97
    return remainder


def validate_iban(iban: str) -> str:
    """
    Полная проверка IBAN: страна, длина, MOD-97.

    Возвращает каноническую форму (uppercase, без пробелов).
    Поднимает ValueError, если хотя бы одна проверка не прошла.
    """
    if not iban:
        raise ValueError("IBAN is required")
    cleaned = re.sub(r"\s+", "", iban).upper()
    if len(cleaned) < 2 or not cleaned[:2].isalpha():
        raise ValueError("IBAN must start with a 2-letter country code")
    country = cleaned[:2]
    expected_length = IBAN_LENGTHS.get(country)
    if expected_length is None:
        raise ValueError(f"Country '{country}' does not use IBAN")
    if len(cleaned) != expected_length:
        raise ValueError(
            f"IBAN length for {country} must be {expected_length}, got {len(cleaned)}"
        )
    if _iban_mod97(cleaned) != 1:
        raise ValueError("Invalid IBAN checksum")
    return cleaned


def looks_like_iban(value: str) -> bool:
    """Эвристика: «похож ли вход на IBAN» (страна из IBAN-списка)."""
    if not value or len(value) < 2:
        return False
    cleaned = re.sub(r"\s+", "", value).upper()
    return cleaned[:2].isalpha() and cleaned[:2] in IBAN_LENGTHS


def validate_account_number(account: str, country: Optional[str] = None) -> str:
    """
    Универсальная проверка номера счёта.

    - Если значение «похоже на IBAN» — прогоняем полный IBAN-валидатор.
    - Иначе — fallback (UI-совместимый): A-Z + 0-9, длина 5-35.

    Возвращает очищенную uppercase-форму.
    """
    if not account:
        raise ValueError("Account number is required")
    cleaned = re.sub(r"\s+", "", account).upper()
    if looks_like_iban(cleaned):
        return validate_iban(cleaned)
    if not re.fullmatch(r"[A-Z0-9]+", cleaned):
        raise ValueError("Account number may contain only letters A-Z and digits 0-9")
    if not (5 <= len(cleaned) <= 35):
        raise ValueError("Account number length must be 5-35 characters")
    return cleaned


def validate_bic(bic: str, country: Optional[str] = None) -> str:
    """
    Проверить BIC: 8 или 11 символов, формат, опционально соответствие
    стране (символы 5-6 в BIC должны совпадать с переданным country).

    Возвращает каноническую форму (uppercase, без пробелов).
    """
    if not bic:
        raise ValueError("BIC is required")
    cleaned = re.sub(r"\s+", "", bic).upper()
    if len(cleaned) not in (8, 11):
        raise ValueError("BIC must be 8 or 11 characters")
    if not _BIC_PATTERN.fullmatch(cleaned):
        raise ValueError("Invalid BIC format")
    if country:
        country_upper = country.strip().upper()
        bic_country = cleaned[4:6]
        if bic_country != country_upper:
            raise ValueError(
                f"BIC country '{bic_country}' does not match selected country '{country_upper}'"
            )
    return cleaned


def normalize_country(value: Optional[str]) -> Optional[str]:
    """Нормализовать ISO-код страны: trim + uppercase."""
    if value is None:
        return None
    cleaned = value.strip().upper()
    return cleaned or None
