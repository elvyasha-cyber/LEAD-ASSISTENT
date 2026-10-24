"""Финальная проверка LEAD-ASSISTENT: четыре сценария + анонимизация.

Запуск (сервер уже должен работать на 127.0.0.1:8000):

    .venv\\Scripts\\python.exe tools\\final_check.py

Скрипт не печатает адрес вебхука и не пишет его в файлы.
Итог сохраняется в JSON (путь в переменной FINAL_CHECK_OUT)
и в коротком виде печатается в консоль.
"""

from __future__ import annotations

import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import bitrix24_client
import privacy

APP_URL = "http://127.0.0.1:8000/api/analyze"
LOG_PATH = Path(os.getenv("FINAL_CHECK_LOG", r"C:\Users\shame\AppData\Local\Temp\opencode\app_err.log"))
OUT_PATH = Path(os.getenv("FINAL_CHECK_OUT", r"C:\Users\shame\AppData\Local\Temp\opencode\final_check.json"))

PRICE_RE = re.compile(r"\d[\d\s.,]*\s*(руб|₽|\bр\.|тыс|млн|миллион|тысяч)", re.IGNORECASE)
TERM_RE = re.compile(
    r"(\d+\s*(дн|день|дня|дней|недел|месяц|час)|\bв течение\b|\bзавтра\b|\bпослезавтра\b)",
    re.IGNORECASE,
)
PROMISE_RE = re.compile(r"(гарантиру|скидк|обязательно\s+верн|верн[её]м\s+деньги)", re.IGNORECASE)
BLAME_RE = re.compile(r"(компенсац|верн[её]м|возврат\s+денег|виноват)", re.IGNORECASE)

SCENARIOS = [
    {
        "id": 1,
        "title": "1. Целевой лид",
        "example": "Офис на 40 мест, столы, кресла, шкафы, бюджет 1,5 млн, переезд в начале месяца",
        "name": "Марина Соколова",
        "phone": "+7 (916) 402-18-35",
        "email": "m.sokolova@alfalogistika.ru",
        "text": (
            "Здравствуйте! Я офис-менеджер компании \"Альфа-Логистик\". Мы переезжаем "
            "в новый офис на 40 рабочих мест и хотим заказать поставку и сборку офисной "
            "мебели: столы, кресла и шкафы. Переезд - в начале следующего месяца, бюджет "
            "около 1,5 млн рублей. Пришлите, пожалуйста, коммерческое предложение."
        ),
    },
    {
        "id": 2,
        "title": "2. Нецелевой",
        "example": "«Ищем подрядчика на разработку мобильного приложения»",
        "name": "Сергей Волков",
        "phone": "+7 (925) 310-77-12",
        "email": "s.volkov@example.ru",
        "text": (
            "Здравствуйте! Ищем подрядчика на разработку мобильного приложения для "
            "доставки еды. Нужна оценка сроков и стоимости работ, готовы обсудить "
            "сотрудничество."
        ),
    },
    {
        "id": 3,
        "title": "3. Жалоба",
        "example": "Сорван срок доставки, угроза возврата предоплаты",
        "name": "Дмитрий Орлов",
        "phone": "+7 (985) 119-30-47",
        "email": "d.orlov@techprom-group.ru",
        "text": (
            "Это уже третье письмо! Заказ должны были привезти в понедельник, сейчас "
            "четверг - ни мебели, ни звонка. Менеджер не берёт трубку. Если завтра "
            "ничего не изменится, будем отказываться и требовать возврат предоплаты."
        ),
    },
    {
        "id": 4,
        "title": "4. Недостаточно данных",
        "example": "«Сколько стоят офисные кресла? Нужно несколько штук»",
        "name": "Ольга Ким",
        "phone": "+7 (903) 555-14-20",
        "email": "",
        "text": "Добрый день, сколько у вас стоят офисные кресла? Нужно несколько штук.",
    },
]


def compose(name: str, phone: str, email: str, text: str) -> str:
    lines = []
    if name:
        lines.append("Имя: " + name)
    if phone:
        lines.append("Телефон: " + phone)
    if email:
        lines.append("E-mail: " + email)
    if lines:
        lines.append("")
    lines.append("Текст заявки:")
    lines.append(text.strip())
    return "\n".join(lines)


def crm(method: str, params: dict) -> dict:
    base = bitrix24_client._get_webhook_url()
    url = f"{base}/{method}.json?" + urllib.parse.urlencode(params, doseq=True)
    with urllib.request.urlopen(url, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def analyze(text: str) -> dict:
    body = json.dumps({"text": text}).encode("utf-8")
    attempts = 0
    last = {"http": 0, "elapsed": 0.0, "data": {}, "attempts": 0}
    while attempts < 3:
        attempts += 1
        req = urllib.request.Request(
            APP_URL, data=body, headers={"Content-Type": "application/json"}, method="POST"
        )
        started = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                code = resp.status
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            code = exc.code
            try:
                data = json.loads(exc.read().decode("utf-8"))
            except Exception:
                data = {"error": "нет тела ответа"}
        last = {
            "http": code,
            "elapsed": round(time.perf_counter() - started, 1),
            "data": data,
            "attempts": attempts,
        }
        if code == 200:
            return last
        time.sleep(8)
    return last


def text_of(value) -> str:
    if isinstance(value, list):
        return " ".join(str(v) for v in value)
    return str(value or "")


def lead_ids_after(max_id: int) -> list[str]:
    data = crm(
        "crm.lead.list",
        {
            "filter[>ID]": max_id,
            "order[ID]": "ASC",
            "limit": 50,
            "select[]": ["ID", "TITLE", "DATE_CREATE"],
        },
    )
    return [str(item["ID"]) for item in data.get("result", [])]


def lead_details(lead_id: str) -> dict:
    items = crm(
        "crm.lead.get",
        {"id": lead_id},
    ).get("result") or {}
    keep = {}
    for key in ("ID", "TITLE", "NAME", "LAST_NAME", "SECOND_NAME", "PHONE", "EMAIL",
                "SOURCE_ID", "OPENED", "STATUS_ID", "ASSIGNED_BY_ID", "COMMENTS"):
        keep[key] = items.get(key)
    return keep


def phone_values(lead: dict) -> list[str]:
    return [str(v.get("VALUE")) for v in (lead.get("PHONE") or []) if isinstance(v, dict)]


def email_values(lead: dict) -> list[str]:
    return [str(v.get("VALUE")) for v in (lead.get("EMAIL") or []) if isinstance(v, dict)]


def log_tail(start_offset: int) -> str:
    try:
        raw = LOG_PATH.read_bytes()[start_offset:]
        return raw.decode("utf-8", errors="replace")
    except OSError:
        return ""


def main() -> int:
    report: dict = {"scenarios": [], "checks": [], "anonymization": {}, "notifications": {}}
    failures = 0

    log_offset = LOG_PATH.stat().st_size if LOG_PATH.exists() else 0

    before = crm("crm.lead.list", {"order[ID]": "DESC", "limit": 1, "select[]": ["ID"]})
    max_id = int(before["result"][0]["ID"]) if before.get("result") else 0

    only = {p.strip() for p in os.getenv("FINAL_CHECK_ONLY", "").split(",") if p.strip()}

    for scenario in SCENARIOS:
        if only and str(scenario["id"]) not in only:
            continue
        text = compose(scenario["name"], scenario["phone"], scenario["email"], scenario["text"])
        run = analyze(text)
        result = (run["data"] or {}).get("result")
        record = {
            "id": scenario["id"],
            "title": scenario["title"],
            "example": scenario["example"],
            "phone": scenario["phone"],
            "email": scenario["email"],
            "http": run["http"],
            "elapsed": run["elapsed"],
            "attempts": run.get("attempts", 1),
            "text": text,
            "result": result,
            "error_body": None if result else run["data"],
            "raw_keys": sorted((run["data"] or {}).keys()),
        }
        report["scenarios"].append(record)
        print(f"scenario {scenario['id']}: HTTP {run['http']}, {run['elapsed']} s, "
              f"lead_type={ (result or {}).get('lead_type') }")

    time.sleep(5)
    ids = lead_ids_after(max_id)
    report["lead_ids"] = ids

    details = [(lead_id, lead_details(lead_id)) for lead_id in ids]

    def digits(value: str) -> str:
        return re.sub(r"\D", "", value or "")

    used: set[str] = set()
    for record in report["scenarios"]:
        phone = digits(record.get("phone", ""))
        email = str(record.get("email") or "").lower()
        record["lead_id"] = ""
        record["lead"] = None
        for lead_id, lead in details:
            if lead_id in used:
                continue
            lead_phones = [digits(v) for v in phone_values(lead)]
            lead_emails = [v.lower() for v in email_values(lead)]
            same_phone = bool(phone) and any(p.endswith(phone[-10:]) for p in lead_phones if p)
            same_email = bool(email) and email in lead_emails
            if same_phone or same_email:
                record["lead_id"] = lead_id
                record["lead"] = lead
                used.add(lead_id)
                break

    report["unmatched_leads"] = [lead_id for lead_id, _ in details if lead_id not in used]

    # --- проверки по сценариям ---------------------------------------------
    def add(scenario_id: int, name: str, ok: bool, detail: str = "") -> None:
        nonlocal failures
        if not ok:
            failures += 1
        report["checks"].append(
            {"scenario": scenario_id, "name": name, "ok": bool(ok), "detail": detail[:400]}
        )

    by_id = {r["id"]: r for r in report["scenarios"]}

    r1 = by_id[1]
    f1 = r1.get("result") or {}
    add(1, "HTTP 200", r1["http"] == 200, str(r1["http"]))
    add(1, "тип лида - целевой", f1.get("lead_type") == "целевой", text_of(f1.get("lead_type")))
    add(1, "известные данные заполнены", bool(f1.get("key_data")), text_of(f1.get("key_data")))
    add(1, "человек не нужен", f1.get("needs_human") is False, text_of(f1.get("needs_human")))
    add(1, "следующий шаг - предложение",
        any(w in text_of(f1.get("next_step")).lower() for w in ("кп", "коммерческ", "предложен")),
        text_of(f1.get("next_step")))
    lead1 = r1.get("lead") or {}
    add(1, "лид в CRM создан", bool(r1.get("lead_id")), str(r1.get("lead_id")))
    add(1, "в лиде есть телефон", bool(phone_values(lead1)), str(phone_values(lead1)))
    add(1, "в лиде есть e-mail", bool(email_values(lead1)), str(email_values(lead1)))
    add(1, "в лиде есть имя", bool(lead1.get("NAME") or lead1.get("LAST_NAME")),
        f"{lead1.get('LAST_NAME')} {lead1.get('NAME')}")
    add(1, "в комментарии лида есть карточка",
        "Карточка разбора" in str(lead1.get("COMMENTS") or ""), "")

    r2 = by_id[2]
    f2 = r2.get("result") or {}
    add(2, "HTTP 200", r2["http"] == 200, str(r2["http"]))
    add(2, "тип лида - нецелевой", f2.get("lead_type") == "нецелевой", text_of(f2.get("lead_type")))
    add(2, "нет обещаний", not PROMISE_RE.search(text_of(f2.get("reply_draft")) + " " +
                                                 text_of(f2.get("next_step"))),
        text_of(f2.get("reply_draft"))[:200])
    add(2, "нет цен", not PRICE_RE.search(text_of(f2.get("reply_draft"))),
        text_of(f2.get("reply_draft"))[:200])
    add(2, "лид в CRM создан", bool(r2.get("lead_id")), str(r2.get("lead_id")))

    r3 = by_id[3]
    f3 = r3.get("result") or {}
    reason3 = text_of(f3.get("human_reason")).lower()
    add(3, "HTTP 200", r3["http"] == 200, str(r3["http"]))
    add(3, "нужен человек", f3.get("needs_human") is True, text_of(f3.get("needs_human")))
    add(3, "причина про жалобу или конфликт",
        any(w in reason3 for w in ("жалоб", "конфликт", "срок", "возврат", "предоплат")),
        text_of(f3.get("human_reason")))
    add(3, "уточняющих вопросов нет", not f3.get("clarifying_questions"),
        text_of(f3.get("clarifying_questions")))
    add(3, "черновик нейтральный", not BLAME_RE.search(text_of(f3.get("reply_draft"))),
        text_of(f3.get("reply_draft"))[:200])
    add(3, "лид в CRM создан", bool(r3.get("lead_id")), str(r3.get("lead_id")))

    r4 = by_id[4]
    f4 = r4.get("result") or {}
    questions4 = f4.get("clarifying_questions") or []
    add(4, "HTTP 200", r4["http"] == 200, str(r4["http"]))
    add(4, "недостающие данные перечислены", bool(f4.get("missing_data")),
        text_of(f4.get("missing_data")))
    add(4, "задано 1-2 вопроса", 1 <= len(questions4) <= 2, text_of(questions4))
    add(4, "в черновике нет цен", not PRICE_RE.search(text_of(f4.get("reply_draft"))),
        text_of(f4.get("reply_draft"))[:200])
    add(4, "в черновике нет сроков", not TERM_RE.search(text_of(f4.get("reply_draft"))),
        text_of(f4.get("reply_draft"))[:200])

    # --- анонимизация -------------------------------------------------------
    sample = by_id[1]["text"]
    masked = privacy.anonymize(sample)
    restored = privacy.restore(masked.text, masked.mapping)
    anon = {
        "masked_text": masked.text,
        "labels": sorted(set(re.findall(r"\[[А-ЯЁ_0-9]+\]", masked.text))),
        "counts": masked.counts,
        "phone_hidden": "402-18-35" not in masked.text,
        "email_hidden": "sokolova" not in masked.text,
        "name_hidden": "Соколова" not in masked.text and "Марина" not in masked.text,
        "roundtrip": restored == sample,
    }
    report["anonymization"] = anon
    add(0, "в запрос к ИИ ушли только метки",
        anon["phone_hidden"] and anon["email_hidden"] and anon["name_hidden"] and bool(anon["labels"]),
        ", ".join(anon["labels"]))
    add(0, "реальные данные восстанавливаются точно", anon["roundtrip"],
        "тексты совпадают" if anon["roundtrip"] else "есть расхождение")

    # --- уведомления --------------------------------------------------------
    tail = log_tail(log_offset)
    created = len(re.findall(r"лид создан, номер", tail))
    notified = len(re.findall(r"уведомление отправлено", tail))
    failed = len(re.findall(r"уведомление не отправлено", tail))
    report["notifications"] = {
        "leads_created": created,
        "notifications_sent": notified,
        "notifications_failed": failed,
        "log_path": str(LOG_PATH),
    }
    matched = len([r for r in report["scenarios"] if r.get("lead_id")])
    add(0, "уведомления отправлены для всех лидов",
        notified >= matched and failed == 0 and matched > 0,
        f"лидов найдено {matched}, уведомлений {notified}, ошибок {failed}")

    report["failed_checks"] = failures
    report["total_checks"] = len(report["checks"])
    OUT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"DONE checks={report['total_checks']} failed={failures}")
    print(f"LEADS={','.join(ids)}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
