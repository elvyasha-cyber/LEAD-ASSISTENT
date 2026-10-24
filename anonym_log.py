"""Журнал обезличивания заявок.

Пишет в CSV только статистику: когда, сколько и каких меток найдено, сколько
символов было в заявке и чем закончилась обработка. Сами персональные данные
(имена, телефоны, адреса) в журнал НЕ попадают - иначе он стал бы утечкой.

Файл по умолчанию: D:\\LEAD-ASSISTENT\\Журнал_анонимизации.csv
Другой путь можно задать переменной окружения ANON_LOG_PATH.
"""

from __future__ import annotations

import csv
import logging
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Mapping

log = logging.getLogger("anonym")

PROJECT_DIR = Path(__file__).resolve().parent
DEFAULT_PATH = PROJECT_DIR / "Журнал_анонимизации.csv"

FIELDS = ["дата_время", "всего_меток", "по_типам", "символов_в_заявке", "статус"]

_lock = threading.Lock()


def log_path() -> Path:
    """Куда писать журнал."""
    custom = (os.getenv("ANON_LOG_PATH") or "").strip()
    return Path(custom) if custom else DEFAULT_PATH


def _breakdown(counts: Mapping[str, int]) -> str:
    parts = [f"{kind}:{count}" for kind, count in sorted(counts.items()) if count]
    return ", ".join(parts)


def ensure_file() -> None:
    """Создать журнал с заголовком, чтобы файл был виден до первой заявки."""
    path = log_path()
    try:
        with _lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists() or path.stat().st_size == 0:
                with path.open("a", encoding="utf-8-sig", newline="") as handle:
                    csv.writer(handle, delimiter=";").writerow(FIELDS)
    except OSError as exc:
        log.warning("Не удалось создать журнал обезличивания (%s).", type(exc).__name__)


def record(counts: Mapping[str, int], text_length: int, status: str) -> None:
    """Добавить строку в журнал. Ошибки журнала не ломают обработку заявки."""
    path = log_path()
    total = sum(counts.values())
    row = [
        datetime.now().astimezone().isoformat(timespec="seconds"),
        str(total),
        _breakdown(counts),
        str(int(text_length)),
        status,
    ]
    try:
        with _lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            is_new = not path.exists() or path.stat().st_size == 0
            with path.open("a", encoding="utf-8-sig", newline="") as handle:
                writer = csv.writer(handle, delimiter=";")
                if is_new:
                    writer.writerow(FIELDS)
                writer.writerow(row)
    except OSError as exc:
        log.warning("Не удалось записать журнал обезличивания (%s).", type(exc).__name__)
