"""Проверка слоя приватности. Запуск:

    .venv\\Scripts\\python.exe tools\\test_privacy.py

Скрипт не ходит в интернет и не трогает рабочие файлы.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import privacy
from privacy import anonymize, restore, restore_result

FAILED: list[str] = []
CHECKED = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global CHECKED
    CHECKED += 1
    if condition:
        print(f"  ок   {name}")
    else:
        FAILED.append(name)
        print(f"  СБОЙ {name}" + (f"\n       {detail}" if detail else ""))


def must_mask(name: str, text: str, kind: str, secret: str | None = None) -> None:
    result = anonymize(text)
    masked = result.text
    ok = f"[{kind}_1]" in masked
    if secret is not None:
        ok = ok and secret not in masked
    check(name, ok, f"получилось: {masked!r}; замены: {result.counts}")


def must_not_mask(name: str, text: str) -> None:
    result = anonymize(text)
    check(name, result.text == text, f"получилось: {result.text!r}; замены: {result.counts}")


print("Данные, которые обязаны маскироваться")
must_mask("телефон +7 со скобками", "Позвоните на +7 (916) 402-18-35", "ТЕЛЕФОН", "402-18-35")
must_mask("телефон 8 без разделителей", "Мой номер 89164021835", "ТЕЛЕФОН", "89164021835")
must_mask("телефон 8 через дефисы", "Тел. 8-916-402-18-35", "ТЕЛЕФОН", "402-18-35")
must_mask("телефон пробелами", "916 402 18 35", "ТЕЛЕФОН", "402")
must_mask("телефон в скобках", "(916) 402-18-35", "ТЕЛЕФОН", "402-18-35")
must_mask("e-mail", "Пишите: m.sokolova@alfalogistika.ru", "EMAIL", "m.sokolova@")
must_mask("имя и фамилия", "Меня зовут Марина Соколова", "ИМЯ", "Марина")
must_mask("фамилия и имя", "Соколова Марина звонила", "ИМЯ", "Соколова")
must_mask("ФИО с отчеством", "Соколов Иван Иванович", "ИМЯ", "Иванович")
must_mask("имя из поля формы", "Имя: Абдулло Рахмонов\nТекст заявки: нужен стол", "ИМЯ", "Абдулло")
must_mask("адрес город улица дом", "г. Москва, ул. Ленина, д. 5, кв. 12", "АДРЕС", "Ленина")
must_mask("адрес область", "Московская обл., г. Химки, ул. Победы, 3", "АДРЕС", "Победы")
must_mask("СНИЛС", "СНИЛС 123-456-789 00", "СНИЛС", "123-456-789")
must_mask("ИНН", "ИНН 7712345678", "ИНН", "7712345678")
must_mask("паспорт", "паспорт 45 09 123456", "ПАСПОРТ", "123456")
must_mask("банковская карта", "карта 4276 1234 5678 9010", "КАРТА", "4276 1234")
must_mask("дата рождения", "дата рождения: 12.03.1985", "ДАТА_РОЖДЕНИЯ", "12.03.1985")
must_mask("ник в телеграме", "мой ник @ivan_petrov", "МЕССЕНДЖЕР", "ivan_petrov")
must_mask("ссылка на телеграм", "https://t.me/ivan_petrov", "МЕССЕНДЖЕР", "ivan_petrov")

print("\nДанные, которые маскировать нельзя")
must_not_mask("сумма в миллионах", "Бюджет около 1,5 млн рублей")
must_not_mask("количество рабочих мест", "Нужно 40 рабочих мест")
must_not_mask("название теста", "Тест 1: полная заявка")
must_not_mask("название компании", "Альфа-Логистик")
must_not_mask("компания латиницей", "TechProm Group")
must_not_mask("оборот речи про месяц", "Переезд в начале следующего месяца")
must_not_mask("ООО Ромашка", "ООО Ромашка")
must_not_mask("номер заказа", "заказ № 12345")
must_not_mask("день недели", "Заказ должны были привезти в понедельник")
must_not_mask("жалоба на менеджера", "Менеджер не берёт трубку")
must_not_mask("название модели", "GigaChat-2-Max")
must_not_mask("дата без подписи", "12.03.1985")
must_not_mask("карта памяти", "Карта памяти на 64 ГБ")
must_not_mask("просто офис", "Мы переезжаем в новый офис на 40 рабочих мест")

print("\nСловарь и повторные значения")
text = "Марина Соколова, телефон +7 (916) 402-18-35, почта m.sokolova@alfalogistika.ru"
result = anonymize(text)
check("в тексте есть все три метки",
      all(k in result.text for k in ("[ИМЯ_1]", "[ТЕЛЕФОН_1]", "[EMAIL_1]")),
      result.text)
check("в тексте нет исходных данных",
      all(x not in result.text for x in ("Марина", "916", "m.sokolova")), result.text)
check("словарь хранит реальные значения",
      result.mapping.get("[ИМЯ_1]") == "Марина Соколова"
      and result.mapping.get("[ТЕЛЕФОН_1]") == "+7 (916) 402-18-35", str(result.mapping))
check("восстановление возвращает исходный текст", restore(result.text, result.mapping) == text,
      restore(result.text, result.mapping))

twice = anonymize("Звонить Марине Соколовой, телефон +7 916 402-18-35. И ещё раз +79164021835.")
check("одинаковый телефон - одна метка",
      twice.text.count("[ТЕЛЕФОН_1]") == 2 and "[ТЕЛЕФОН_2]" not in twice.text, twice.text)

two_phones = anonymize("Первый +7 916 402-18-35, второй +7 903 111-22-33")
check("разные телефоны - разные метки",
      "[ТЕЛЕФОН_1]" in two_phones.text and "[ТЕЛЕФОН_2]" in two_phones.text,
      two_phones.text)

print("\nОтвет модели: терпимость к искажениям меток")
mapping = {"[ТЕЛЕФОН_1]": "+7 916 402-18-35", "[ИМЯ_1]": "Марина Соколова"}
check("метка как есть", restore("Звонить [ТЕЛЕФОН_1]", mapping) == "Звонить +7 916 402-18-35")
check("метка в нижнем регистре", restore("Звонить [телефон 1]", mapping) == "Звонить +7 916 402-18-35")
check("дефис вместо подчёркивания", restore("[ТЕЛЕФОН-1]", mapping) == "+7 916 402-18-35")
check("пробел вместо подчёркивания", restore("[ТЕЛЕФОН 1]", mapping) == "+7 916 402-18-35")
check("метка без скобок", restore("Звонить ТЕЛЕФОН_1 сегодня", mapping) == "Звонить +7 916 402-18-35 сегодня")
check("неизвестная метка остаётся", restore("[ТЕЛЕФОН_7]", mapping) == "[ТЕЛЕФОН_7]")

print("\nВосстановление всей карточки")
card = {
    "client": {"name": "[ИМЯ_1]"},
    "summary": "Клиент [ИМЯ_1], телефон [ТЕЛЕФОН_1]",
    "key_data": ["Имя: [ИМЯ_1]", "Телефон: [ТЕЛЕФОН_1]"],
    "missing_data": [],
    "confidence": "high",
}
restored = restore_result(card, mapping)
check("строка", restored["summary"] == "Клиент Марина Соколова, телефон +7 916 402-18-35",
      restored["summary"])
check("список", restored["key_data"] == ["Имя: Марина Соколова", "Телефон: +7 916 402-18-35"],
      str(restored["key_data"]))
check("вложенный объект", restored["client"]["name"] == "Марина Соколова",
      str(restored["client"]))
check("остальные поля не тронуты", restored["confidence"] == "high" and restored["missing_data"] == [])
check("пустой словарь ничего не меняет", restore_result(card, {}) == card)

print("\nТестовые заявки приложения не меняются")
import prompts

for sample in prompts.SAMPLES:
    check(sample["title"], anonymize(sample["text"]).text == sample["text"])

print("\nЗапросы не смешиваются")
first = anonymize("Марина Соколова, +7 916 402-18-35")
second = anonymize("Иван Иванов, +7 903 111-22-33")
check("в первом запросе своя метка",
      first.mapping.get("[ИМЯ_1]") == "Марина Соколова" and "[ИМЯ_1]" in first.text)
check("во втором запросе своя метка",
      second.mapping.get("[ИМЯ_1]") == "Иван Иванов" and "[ИМЯ_1]" in second.text)
check("словари независимы",
      "Иван" not in str(first.mapping) and "Марина" not in str(second.mapping))

print("\nТекст, который собирает форма")
form = (
    "Имя: Марина Соколова\n"
    "Телефон: +7 (916) 402-18-35\n"
    "E-mail: m.sokolova@alfalogistika.ru\n\n"
    "Нужен стол в офис на ул. Ленина, д. 5."
)
form_result = anonymize(form)
check("все четыре метки на месте",
      all(tag in form_result.text for tag in ("[ИМЯ_1]", "[ТЕЛЕФОН_1]", "[EMAIL_1]", "[АДРЕС_1]")),
      form_result.text)
check("в запросе нет реальных данных",
      not any(x in form_result.text for x in ("Марина", "402-18-35", "m.sokolova", "Ленина")),
      form_result.text)
check("восстановление точное", restore(form_result.text, form_result.mapping) == form,
      restore(form_result.text, form_result.mapping))

print()
if FAILED:
    print(f"ПРОВАЛЕНО {len(FAILED)} из {CHECKED}: " + "; ".join(FAILED))
    sys.exit(1)
print(f"Все проверки пройдены: {CHECKED}")
