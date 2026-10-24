"""Чтение файла .env с терпимостью к кодировкам.

Файл .env часто правят в «Блокноте» на русской Windows, и он сохраняется
в однобайтовой кодировке (cp1251). Стандартное чтение utf-8 на таком файле
падает с ошибкой, и программа не запускается. Поэтому здесь файл читается
последовательно в нескольких кодировках, пока не найдётся подходящая.
"""

from __future__ import annotations

import os
from io import StringIO
from pathlib import Path

from dotenv import dotenv_values

ENV_FILE = Path(__file__).resolve().parent / ".env"
ENCODINGS = ("utf-8-sig", "utf-8", "cp1251", "koi8-r")


def read_env_text(path: Path | None = None) -> str:
    """Прочитать текст файла .env в любой из известных кодировок."""
    target = path or ENV_FILE
    data = target.read_bytes()
    for encoding in ENCODINGS:
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def load_env(path: Path | None = None) -> dict[str, str]:
    """Прочитать .env и положить значения в окружение.

    Уже заданные переменные окружения не перезаписываются - как и раньше.
    """
    target = path or ENV_FILE
    if not target.exists():
        return {}
    values = dotenv_values(stream=StringIO(read_env_text(target)))
    for key, value in values.items():
        if value is None:
            continue
        os.environ.setdefault(key, value)
    return values
