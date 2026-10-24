"""Работа с GigaChat API: получение токена, запрос к модели, разбор ответа.

Ключ авторизации читается из файла .env и НИКОГДА не попадает в ответы
приложения и в журналы (в журнал пишутся только коды ответов и тексты ошибок).
"""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any

import requests

from env_config import load_env

# Читаем .env рядом с этим файлом - так настройки находятся при любом запуске.
load_env()

# Адреса сервиса GigaChat (актуальная документация разработчиков Sber).
TOKEN_URL = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
CHAT_URL = "https://api.giga.chat/v1/chat/completions"

API_KEY = os.getenv("GIGACHAT_API_KEY", "").strip()
SCOPE = os.getenv("GIGACHAT_SCOPE", "GIGACHAT_API_PERS").strip() or "GIGACHAT_API_PERS"
MODEL = os.getenv("GIGACHAT_MODEL", "GigaChat-2-Max").strip() or "GigaChat-2-Max"

# Сертификаты российского УЦ Минцифры. GigaChat работает на сертификатах НУЦ Минцифры,
# а их корня нет в стандартном наборе, которым пользуется requests, - без этого файла
# проверка защищённого соединения не проходит. Файл взят с официального адреса
# УЦ и сверен по отпечатку SHA-256.
CA_BUNDLE = Path(__file__).resolve().parent / "certs" / "russian_trusted_root_ca.pem"

# Проверять сертификаты сервера (True) или отключить проверку (False).
# В .env можно задать GIGACHAT_VERIFY_SSL=false, но это снижает безопасность.
_verify_setting = os.getenv("GIGACHAT_VERIFY_SSL", "").strip().lower()
if _verify_setting in ("0", "false", "no", "off"):
    VERIFY_SSL: bool | str = False
elif CA_BUNDLE.exists():
    VERIFY_SSL = str(CA_BUNDLE)
else:
    VERIFY_SSL = True

TOKEN_TTL_SECONDS = 30 * 60  # токен GigaChat живёт 30 минут
REFRESH_MARGIN_SECONDS = 60  # обновляем токен за минуту до истечения
CONNECT_TIMEOUT = 15
READ_TIMEOUT = 120
MAX_TEXT_LENGTH = 20000


class GigaChatError(Exception):
    """Ошибка с понятным сообщением для пользователя и деталями для журнала."""

    def __init__(self, user_message: str, detail: str = "", status_code: int | None = None) -> None:
        super().__init__(user_message)
        self.user_message = user_message
        self.detail = detail
        self.status_code = status_code


_token: str | None = None
_token_expires_at: float = 0.0


def is_configured() -> bool:
    """Задан ли ключ авторизации."""
    return bool(API_KEY)


def config_info() -> dict[str, Any]:
    """Сведения о настройках - без секретов."""
    return {
        "key_configured": is_configured(),
        "model": MODEL,
        "scope": SCOPE,
    }


def _invalidate_token() -> None:
    global _token, _token_expires_at
    _token = None
    _token_expires_at = 0.0


def _get_token() -> str:
    """Получить токен доступа (с кэшем на 30 минут)."""
    global _token, _token_expires_at

    if _token and time.time() < _token_expires_at - REFRESH_MARGIN_SECONDS:
        return _token

    if not API_KEY:
        raise GigaChatError(
            "Не задан ключ авторизации GigaChat.",
            "В файле .env пустое значение GIGACHAT_API_KEY",
        )

    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
        "RqUID": str(uuid.uuid4()),
        "Authorization": f"Basic {API_KEY}",
    }

    try:
        response = requests.post(
            TOKEN_URL,
            data={"scope": SCOPE},
            headers=headers,
            timeout=(CONNECT_TIMEOUT, 30),
            verify=VERIFY_SSL,
        )
    except requests.Timeout:
        raise GigaChatError(
            "Нет связи с сервисом GigaChat.",
            "Таймаут при получении токена доступа",
        )
    except requests.exceptions.SSLError as exc:
        raise GigaChatError(
            "Не удалось проверить сертификат сервиса GigaChat.",
            f"Ошибка TLS: {type(exc).__name__}. Проверьте файл certs/russian_trusted_root_ca.pem",
        )
    except requests.RequestException as exc:
        raise GigaChatError(
            "Не удалось связаться с сервисом GigaChat.",
            f"Ошибка сети при получении токена: {type(exc).__name__}",
        )

    if response.status_code == 401:
        raise GigaChatError(
            "Ключ авторизации отклонён.",
            "Сервис авторизации GigaChat вернул HTTP 401",
            status_code=401,
        )
    if response.status_code != 200:
        raise GigaChatError(
            "Сервис GigaChat временно недоступен.",
            f"HTTP {response.status_code} при получении токена",
            status_code=response.status_code,
        )

    try:
        payload = response.json()
    except ValueError:
        raise GigaChatError(
            "Сервис GigaChat вернул непонятный ответ.",
            "Ответ сервиса авторизации не является JSON",
        )

    token = payload.get("access_token")
    if not isinstance(token, str) or not token:
        raise GigaChatError(
            "Сервис GigaChat не вернул токен доступа.",
            "В ответе сервиса нет поля access_token",
        )

    expires_at_ms = payload.get("expires_at")
    if isinstance(expires_at_ms, (int, float)):
        _token_expires_at = float(expires_at_ms) / 1000
    else:
        _token_expires_at = time.time() + TOKEN_TTL_SECONDS

    _token = token
    return token


def _post_chat(payload: dict[str, Any], token: str) -> str:
    """Отправить запрос к модели и вернуть текст ответа."""
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": f"Bearer {token}",
    }

    for attempt in range(2):
        try:
            response = requests.post(
                CHAT_URL,
                json=payload,
                headers=headers,
                timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
                verify=VERIFY_SSL,
            )
        except requests.Timeout:
            raise GigaChatError(
                "GigaChat не ответил вовремя.",
                "Таймаут при обращении к модели",
            )
        except requests.exceptions.SSLError as exc:
            raise GigaChatError(
                "Не удалось проверить сертификат сервиса GigaChat.",
                f"Ошибка TLS: {type(exc).__name__}. Проверьте файл certs/russian_trusted_root_ca.pem",
            )
        except requests.RequestException as exc:
            raise GigaChatError(
                "Не удалось связаться с сервисом GigaChat.",
                f"Ошибка сети при обращении к модели: {type(exc).__name__}",
            )

        if response.status_code == 401 and attempt == 0:
            # Токен мог протухнуть - обновляем и повторяем один раз.
            _invalidate_token()
            token = _get_token()
            headers["Authorization"] = f"Bearer {token}"
            continue

        if response.status_code == 401:
            raise GigaChatError(
                "Ключ авторизации отклонён.",
                "Модель вернула HTTP 401",
                status_code=401,
            )
        if response.status_code == 429:
            raise GigaChatError(
                "Слишком много запросов к GigaChat.",
                "Сервис вернул HTTP 429",
                status_code=429,
            )
        if response.status_code >= 500:
            raise GigaChatError(
                "Сервис GigaChat временно недоступен.",
                f"Модель вернула HTTP {response.status_code}",
                status_code=response.status_code,
            )
        if response.status_code != 200:
            raise GigaChatError(
                "GigaChat отклонил запрос.",
                f"Модель вернула HTTP {response.status_code}",
                status_code=response.status_code,
            )

        try:
            data = response.json()
        except ValueError:
            raise GigaChatError(
                "GigaChat вернул непонятный ответ.",
                "Ответ модели не является JSON",
            )

        choices = data.get("choices") or []
        if not choices:
            raise GigaChatError(
                "GigaChat не вернул ответ.",
                "Пустой список choices в ответе модели",
            )

        message = choices[0].get("message") or {}
        content = message.get("content")
        if isinstance(content, list):
            content = "".join(
                part.get("text", "") for part in content if isinstance(part, dict)
            )
        if not isinstance(content, str) or not content.strip():
            raise GigaChatError(
                "GigaChat вернул пустой ответ.",
                "Пустое поле content в ответе модели",
            )
        return content

    raise GigaChatError(
        "Не удалось получить ответ от GigaChat.",
        "Повторная авторизация не помогла",
    )


def ask_model(
    messages: list[dict[str, Any]],
    json_schema: dict[str, Any] | None = None,
) -> str:
    """Спросить модель и вернуть текст ответа.

    Если задан json_schema, используется документированный режим структурированного
    вывода (beta). Если сервис такой запрос отклоняет, делаем повтор без схемы.
    """
    payload: dict[str, Any] = {
        "model": MODEL,
        "messages": messages,
        "temperature": 0.1,
    }

    if json_schema is not None:
        payload["response_format"] = {
            "type": "json_schema",
            "schema": json_schema,
            "strict": True,
        }
        try:
            return _post_chat(payload, _get_token())
        except GigaChatError as exc:
            if exc.status_code not in (400, 404, 415, 422):
                raise
            # Сервис не принял structured output - пробуем обычный режим.
            payload.pop("response_format", None)

    return _post_chat(payload, _get_token())


def parse_json_object(text: str) -> dict[str, Any]:
    """Разобрать ответ модели как JSON-объект (с запасными вариантами)."""
    cleaned = text.strip()
    cleaned = re.sub(r"^```[a-zA-Z]*\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned).strip()

    data: Any = None
    try:
        data = json.loads(cleaned)
    except ValueError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise GigaChatError(
                "AI вернул ответ в неожиданном формате.",
                "В ответе модели не найден JSON-объект",
            )
        try:
            data = json.loads(cleaned[start : end + 1])
        except ValueError as exc:
            raise GigaChatError(
                "AI вернул некорректный ответ.",
                f"JSON из ответа модели не разбирается: {exc}",
            )

    if not isinstance(data, dict):
        raise GigaChatError(
            "AI вернул ответ в неожиданном формате.",
            "Ожидался JSON-объект, а получено другое",
        )
    return data