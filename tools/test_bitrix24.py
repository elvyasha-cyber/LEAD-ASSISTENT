"""Проверка интеграции с Битрикс24. Запуск:

    .venv\\Scripts\\python.exe tools\\test_bitrix24.py

Скрипт не ходит в интернет: запрос к Битрикс24 подменяется заглушкой.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import bitrix24_client

FAILED: list[str] = []
CHECKED = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global CHECKED
    CHECKED += 1
    if condition:
        print(f"  ok   {name}")
    else:
        FAILED.append(name)
        print(f"  FAIL {name}" + (f"\n       {detail}" if detail else ""))


FORM_TEXT = (
    "Имя: Марина Соколова\n"
    "Телефон: +7 (916) 402-18-35\n"
    "E-mail: m.sokolova@alfalogistika.ru\n\n"
    "Здравствуйте! Нужны столы и кресла для нового офиса, 40 рабочих мест."
)

RESULT = {
    "company": "Альфа-Логистик",
    "summary": "Запрос поставки офисной мебели для нового офиса.",
    "lead_type": "целевой",
    "key_data": ["Продукт: столы и кресла", "Количество рабочих мест: 40"],
    "missing_data": ["Бюджет"],
    "clarifying_questions": ["Какой бюджет?"],
    "next_step": "Отправить коммерческое предложение.",
    "reply_draft": "Добрый день! Подготовим предложение.",
    "needs_human": False,
    "human_reason": "не требуется",
}

print("Извлечение контактов из текста формы")
contacts = bitrix24_client.extract_contacts(FORM_TEXT)
check("имя", contacts.get("name") == "Марина Соколова", str(contacts))
check("телефон", contacts.get("phone") == "+7 (916) 402-18-35", str(contacts))
check("e-mail", contacts.get("email") == "m.sokolova@alfalogistika.ru", str(contacts))

bare = bitrix24_client.extract_contacts(
    "Позвоните по номеру 89164021835, почта ivan@example.ru, меня зовут Иван Иванов"
)
check("телефон без подписи поля", bare.get("phone") == "89164021835", str(bare))
check("e-mail без подписи поля", bare.get("email") == "ivan@example.ru", str(bare))
check("имя без подписи поля отсутствует", "name" not in bare, str(bare))

print("\nСборка полей лида")
fields = bitrix24_client.build_lead_fields(FORM_TEXT, RESULT)
check("заголовок содержит суть", "офисной мебели" in fields.get("TITLE", ""), fields.get("TITLE", ""))
check("имя разделено на части",
      fields.get("NAME") == "Марина" and fields.get("LAST_NAME") == "Соколова", str(fields))
check("телефон в мультиполе",
      fields.get("PHONE") == [{"VALUE": "+7 (916) 402-18-35", "VALUE_TYPE": "WORK"}],
      str(fields.get("PHONE")))
check("e-mail в мультиполе",
      fields.get("EMAIL") == [{"VALUE": "m.sokolova@alfalogistika.ru", "VALUE_TYPE": "WORK"}],
      str(fields.get("EMAIL")))
comments = fields.get("COMMENTS", "")
check("в комментарии есть исходный текст", "Нужны столы и кресла" in comments, comments[:200])
check("в комментарии есть карточка разбора", "Тип лида: целевой" in comments, comments[:200])
check("в комментарии есть черновик ответа", "Подготовим предложение" in comments, comments[:200])
check("в комментарии нет меток приватности",
      "[ИМЯ_" not in comments and "[ТЕЛЕФОН_" not in comments, comments[:200])
check("источник и открытость", fields.get("SOURCE_ID") == "WEBFORM" and fields.get("OPENED") == "Y",
      str(fields))

print("\nРазделение ФИО")
check("одно слово", bitrix24_client._split_name("Марина") == {"NAME": "Марина"},
      str(bitrix24_client._split_name("Марина")))
check("два слова", bitrix24_client._split_name("Марина Соколова") ==
      {"NAME": "Марина", "LAST_NAME": "Соколова"},
      str(bitrix24_client._split_name("Марина Соколова")))
check("три слова",
      bitrix24_client._split_name("Соколова Марина Ивановна") ==
      {"LAST_NAME": "Соколова", "NAME": "Марина", "SECOND_NAME": "Ивановна"},
      str(bitrix24_client._split_name("Соколова Марина Ивановна")))

print("\nОтправка")
calls: list[dict] = []


class FakeResponse:
    status_code = 200
    ok = True

    @staticmethod
    def json():
        return {"result": 4242, "time": {}}


def fake_post(url, json=None, timeout=None):
    calls.append({"url": url, "payload": json, "timeout": timeout})
    return FakeResponse()


real_post = bitrix24_client.requests.post
bitrix24_client.requests.post = fake_post

import os

os.environ["B24_WEBHOOK_URL"] = "https://example.bitrix24.ru/rest/1/secret"
bitrix24_client._send_lead(FORM_TEXT, RESULT)
check("запрос ушёл на crm.lead.add.json",
      calls and calls[0]["url"].endswith("/crm.lead.add.json"),
      calls[0]["url"] if calls else "запросов нет")
check("в запросе есть поля лида",
      calls and calls[0]["payload"]["fields"].get("TITLE"), str(calls[0]["payload"]) if calls else "")
check("таймаут задан", calls and calls[0]["timeout"] is not None, str(calls[0]["timeout"]) if calls else "")

print("\nУведомление менеджеру")
notify_calls = [c for c in calls if c["url"].endswith("/im.notify.json")]
check("после лида ушло уведомление", bool(notify_calls), str([c["url"] for c in calls]))
if notify_calls:
    message = notify_calls[0]["payload"].get("MESSAGE", "")
    check("в уведомлении номер лида и суть",
          "4242" in message and "офисной мебели" in message, message)
    check("в уведомлении нет телефона и почты",
          "402-18-35" not in message and "sokolova" not in message, message)
check("получатель уведомления задан",
      bool(notify_calls) and bool(notify_calls[0]["payload"].get("USER_ID")),
      str(notify_calls[0]["payload"]) if notify_calls else "уведомлений нет")

calls.clear()
conflict = dict(RESULT, needs_human=True, human_reason="Жалоба на срыв срока доставки")
bitrix24_client._send_lead(FORM_TEXT, conflict)
notify_calls = [c for c in calls if c["url"].endswith("/im.notify.json")]
conflict_message = notify_calls[0]["payload"].get("MESSAGE", "") if notify_calls else ""
check("для жалобы есть пометка и причина",
      "[Требуется человек]" in conflict_message and "срыв срока" in conflict_message,
      conflict_message)

calls.clear()
os.environ["B24_WEBHOOK_URL"] = ""
bitrix24_client._send_lead(FORM_TEXT, RESULT)
check("без адреса вебхука запрос не отправляется", not calls, str(calls))

calls.clear()
os.environ["B24_WEBHOOK_URL"] = "https://example.bitrix24.ru/rest/1/secret"


def failing_post(url, json=None, timeout=None):
    raise bitrix24_client.requests.exceptions.ConnectionError("net down")


bitrix24_client.requests.post = failing_post
try:
    bitrix24_client._send_lead(FORM_TEXT, RESULT)
    check("сетевая ошибка не пробрасывается", True)
except Exception as exc:
    check("сетевая ошибка не пробрасывается", False, repr(exc))

bitrix24_client.requests.post = real_post

print("\nПроверка содержимого на утечку")
comments = bitrix24_client.build_lead_fields(FORM_TEXT, RESULT)["COMMENTS"]
check("телефон и почта в лиде ожидаемы", "402-18-35" in comments)

print()
if FAILED:
    print(f"FAILED {len(FAILED)} of {CHECKED}: " + "; ".join(FAILED))
    sys.exit(1)
print(f"All checks passed: {CHECKED}")
