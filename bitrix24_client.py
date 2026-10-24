"""Интеграция с Битрикс24 через входящий вебхук.

Отправка лида выполняется в фоновом потоке, не блокирует ответ API.
При пустом B24_WEBHOOK_URL или ошибке отправка просто пропускается.
В логи не попадают персональные данные.
"""

from __future__ import annotations

import logging
import os
import re
import threading
from typing import Any

import requests

from env_config import load_env

load_env()

log = logging.getLogger("bitrix24")

EMAIL_RE = re.compile(r"[\w.+\-]+@[\w\-]+(?:\.[\w\-]+)*\.[A-Za-z]{2,}")
PHONE_RE = re.compile(
    r"(?<![\d])(?:\+7|8)[\s\-\(\)]*\d{3}[\s\-\(\)]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}(?![\d])"
)
NAME_LABEL_RE = re.compile(r"(?im)^\s*Имя\s*:\s*([^\n]+)$")
PHONE_LABEL_RE = re.compile(r"(?im)^\s*Телефон\s*:\s*([^\n]+)$")
EMAIL_LABEL_RE = re.compile(r"(?im)^\s*E-?mail\s*:\s*([^\n]+)$")

RUS_LETTERS = re.compile(r"[А-Яа-яЁё]")


def _get_webhook_url() -> str:
    url = os.getenv("B24_WEBHOOK_URL") or os.getenv("B24_URL") or ""
    return url.strip().rstrip("/")


def _get_assigned_by_id() -> str:
    return (os.getenv("B24_ASSIGNED_BY_ID") or "").strip()


def configured() -> bool:
    """Задан ли адрес входящего вебхука Битрикс24."""
    return bool(_get_webhook_url())


def extract_contacts(text: str) -> dict[str, str]:
    contacts: dict[str, str] = {}

    m = EMAIL_LABEL_RE.search(text)
    if m:
        email = m.group(1).strip()
        contacts["email"] = email
    else:
        emails = EMAIL_RE.findall(text)
        if emails:
            contacts["email"] = emails[0]

    m = PHONE_LABEL_RE.search(text)
    if m:
        phone = m.group(1).strip()
        contacts["phone"] = phone
    else:
        phones = PHONE_RE.findall(text)
        if phones:
            contacts["phone"] = phones[0]

    m = NAME_LABEL_RE.search(text)
    if m:
        name = m.group(1).strip()
        name = re.sub(r"\s+", " ", name)
        contacts["name"] = name

    return contacts


def _split_name(full_name: str) -> dict[str, str]:
    parts = [p.strip() for p in full_name.split() if p.strip()]
    result: dict[str, str] = {}
    if not parts:
        return result
    if len(parts) == 1:
        result["NAME"] = parts[0]
        return result
    if len(parts) == 2:
        result["NAME"] = parts[0]
        result["LAST_NAME"] = parts[1]
        return result
    result["LAST_NAME"] = parts[0]
    result["NAME"] = parts[1]
    if parts[2]:
        result["SECOND_NAME"] = parts[2]
    return result


def _format_result(result: dict[str, Any]) -> str:
    lines: list[str] = []
    labels = {
        "company": "Компания",
        "summary": "Суть запроса",
        "lead_type": "Тип лида",
        "key_data": "Известные данные",
        "missing_data": "Чего не хватает",
        "clarifying_questions": "Уточняющие вопросы",
        "next_step": "Следующий шаг",
        "reply_draft": "Черновик ответа",
        "needs_human": "Нужен человек",
        "human_reason": "Причина передачи человеку",
    }
    for key in ["company", "summary", "lead_type", "key_data", "missing_data",
                "clarifying_questions", "next_step", "reply_draft",
                "needs_human", "human_reason"]:
        if key not in result:
            continue
        value = result[key]
        label = labels.get(key, key)
        if isinstance(value, bool):
            lines.append(f"{label}: {'Да' if value else 'Нет'}")
        elif isinstance(value, list):
            if not value:
                if key in ("key_data",):
                    lines.append(f"{label}: нет")
                elif key in ("missing_data",):
                    lines.append(f"{label}: не требуется")
                elif key in ("clarifying_questions",):
                    lines.append(f"{label}: не задаются")
                else:
                    lines.append(f"{label}: нет")
            else:
                lines.append(f"{label}:")
                for item in value:
                    lines.append(f"  - {item}")
        else:
            text = str(value).strip()
            if text:
                lines.append(f"{label}: {text}")
    return "\n".join(lines)


def build_lead_fields(original_text: str, result: dict[str, Any]) -> dict[str, Any]:
    contacts = extract_contacts(original_text)
    comments_parts: list[str] = []
    comments_parts.append("=== LEAD-ASSISTENT ===")
    comments_parts.append("")
    comments_parts.append("=== Исходный текст заявки ===")
    comments_parts.append(original_text.strip())
    comments_parts.append("")
    comments_parts.append("=== Карточка разбора (GigaChat) ===")
    comments_parts.append(_format_result(result))
    comments = "\n".join(comments_parts)

    title = ""
    summary = result.get("summary")
    if isinstance(summary, str) and summary.strip() and summary.strip().lower() != "не указано":
        s = summary.strip()
        if len(s) > 120:
            s = s[:117].rstrip() + "..."
        title = f"Заявка LEAD-ASSISTENT: {s}"
    if not title:
        company = result.get("company")
        if isinstance(company, str) and company.strip() and company.strip().lower() != "не указано":
            title = f"Заявка LEAD-ASSISTENT: {company.strip()}"
    if not title:
        title = "Заявка LEAD-ASSISTENT"

    fields: dict[str, Any] = {
        "TITLE": title,
        "COMMENTS": comments,
        "SOURCE_ID": "WEBFORM",
        "OPENED": "Y",
    }

    if contacts.get("name"):
        fields.update(_split_name(contacts["name"]))
    if contacts.get("email"):
        fields["EMAIL"] = [{"VALUE": contacts["email"].strip(), "VALUE_TYPE": "WORK"}]
    if contacts.get("phone"):
        fields["PHONE"] = [{"VALUE": contacts["phone"].strip(), "VALUE_TYPE": "WORK"}]

    assigned = _get_assigned_by_id()
    if assigned:
        fields["ASSIGNED_BY_ID"] = assigned

    return fields


def _notify_manager(lead_id: str, result: dict[str, Any]) -> None:
    """Короткое уведомление ответственному менеджеру о новой заявке."""
    base = _get_webhook_url()
    if not base:
        return
    user_id = _get_assigned_by_id() or "1"

    summary = str(result.get("summary") or "").strip()
    message = "Новая заявка LEAD-ASSISTENT"
    if summary:
        message += f": {summary}"
    message += f"\nЛид №{lead_id}"

    if result.get("needs_human"):
        reason = str(result.get("human_reason") or "").strip()
        message = "[Требуется человек] " + message
        if reason and reason.lower() != "не требуется":
            message += f"\nПричина: {reason}"

    payload = {"USER_ID": user_id, "MESSAGE": message, "TYPE": "SYSTEM"}
    try:
        resp = requests.post(f"{base}/im.notify.json", json=payload, timeout=(3, 10))
        if resp.ok:
            log.info("Битрикс24: уведомление отправлено (лид №%s)", lead_id)
        else:
            log.warning("Битрикс24: уведомление не отправлено (HTTP %s).", resp.status_code)
    except Exception as exc:
        log.warning("Битрикс24: уведомление не отправлено (%s).", type(exc).__name__)


def _send_lead(original_text: str, result: dict[str, Any]) -> None:
    base = _get_webhook_url()
    if not base:
        return
    url = f"{base}/crm.lead.add.json"
    try:
        fields = build_lead_fields(original_text, result)
        payload = {"fields": fields, "params": {"REGISTER_SONET_EVENT": "Y"}}
        resp = requests.post(url, json=payload, timeout=(3, 10))
        try:
            data = resp.json()
        except ValueError:
            data = {}
        if resp.ok and isinstance(data, dict) and data.get("result"):
            lead_id = str(data["result"])
            log.info("Битрикс24: лид создан, номер %s", lead_id)
            _notify_manager(lead_id, result)
            return
        err = ""
        if isinstance(data, dict):
            err = data.get("error_description") or data.get("error") or ""
        log.warning("Битрикс24: лид не создан (HTTP %s). %s", resp.status_code, err)
    except requests.exceptions.RequestException as exc:
        log.warning("Битрикс24: нет связи с порталом (%s).", type(exc).__name__)
    except Exception as exc:
        log.warning("Битрикс24: непредвиденная ошибка (%s).", type(exc).__name__)


def enqueue_lead(original_text: str, result: dict[str, Any]) -> None:
    try:
        t = threading.Thread(target=_send_lead, args=(original_text, result), daemon=True)
        t.start()
    except Exception:
        pass
