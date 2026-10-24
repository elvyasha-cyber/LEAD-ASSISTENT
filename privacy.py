"""Обезличивание персональных данных перед отправкой в нейросеть.

Модуль работает как отдельный слой между формой и GigaChat:

    masked, mapping = privacy.anonymize(text)
    ... запрос к модели с текстом masked ...
    result = privacy.restore_result(result, mapping)

Соответствие «метка -> реальное значение» возвращается вызывающему коду.
Модуль ничего не хранит: ни файлов, ни глобальных переменных, ни журналов.
Словарь живёт ровно столько, сколько живёт текущий запрос, и уничтожается
вместе с ним.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

# ---------------------------------------------------------------------------
# Виды данных и формат меток
# ---------------------------------------------------------------------------

KIND_NAME = "ИМЯ"
KIND_PHONE = "ТЕЛЕФОН"
KIND_EMAIL = "EMAIL"
KIND_ADDRESS = "АДРЕС"
KIND_PASSPORT = "ПАСПОРТ"
KIND_SNILS = "СНИЛС"
KIND_INN = "ИНН"
KIND_CARD = "КАРТА"
KIND_BIRTHDATE = "ДАТА_РОЖДЕНИЯ"
KIND_MESSENGER = "МЕССЕНДЖЕР"

KIND_LABELS = {
    KIND_NAME: "имена",
    KIND_PHONE: "телефоны",
    KIND_EMAIL: "адреса почты",
    KIND_ADDRESS: "адреса",
    KIND_PASSPORT: "паспортные данные",
    KIND_SNILS: "СНИЛС",
    KIND_INN: "ИНН",
    KIND_CARD: "номера карт",
    KIND_BIRTHDATE: "даты рождения",
    KIND_MESSENGER: "мессенджеры",
}


# ---------------------------------------------------------------------------
# Русские имена: словарь для эвристики
# ---------------------------------------------------------------------------

MALE_NAMES = (
    "Александр", "Алексей", "Анатолий", "Андрей", "Антон", "Аркадий", "Арсений",
    "Артём", "Артем", "Артур", "Богдан", "Борис", "Вадим", "Валентин", "Валерий",
    "Василий", "Виктор", "Виталий", "Владимир", "Владислав", "Всеволод",
    "Вячеслав", "Геннадий", "Георгий", "Герман", "Глеб", "Григорий", "Даниил",
    "Данил", "Денис", "Дмитрий", "Евгений", "Егор", "Иван", "Игнат", "Игорь",
    "Илья", "Иннокентий", "Кирилл", "Константин", "Лев", "Леонид", "Максим",
    "Марк", "Матвей", "Михаил", "Никита", "Николай", "Олег", "Павел", "Пётр",
    "Петр", "Платон", "Прохор", "Роман", "Ростислав", "Руслан", "Рустам",
    "Савелий", "Святослав", "Семён", "Семен", "Серафим", "Сергей", "Станислав",
    "Степан", "Тарас", "Тимофей", "Тимур", "Трофим", "Фёдор", "Федор", "Филипп",
    "Эдуард", "Эльдар", "Юрий", "Яков", "Ян",
)

FEMALE_NAMES = (
    "Александра", "Алина", "Алиса", "Алла", "Анастасия", "Ангелина", "Анна",
    "Антонина", "Арина", "Валентина", "Валерия", "Варвара", "Вера", "Вероника",
    "Виктория", "Галина", "Дарья", "Диана", "Евгения", "Екатерина", "Елена",
    "Елизавета", "Жанна", "Зинаида", "Зоя", "Инна", "Ирина", "Карина", "Кира",
    "Клавдия", "Кристина", "Ксения", "Лариса", "Лидия", "Лилия", "Любовь",
    "Людмила", "Маргарита", "Марина", "Мария", "Милана", "Надежда", "Наталья",
    "Наталия", "Нина", "Оксана", "Олеся", "Ольга", "Полина", "Раиса", "Регина",
    "Римма", "Светлана", "Снежана", "София", "Софья", "Станислава", "Таисия",
    "Тамара", "Татьяна", "Ульяна", "Эвелина", "Элина", "Эльвира", "Юлия", "Яна",
)

SHORT_NAMES = (
    "Саша", "Женя", "Валя", "Слава", "Дима", "Миша", "Паша", "Коля", "Ваня",
    "Петя", "Гоша", "Лёша", "Леша", "Стёпа", "Степа", "Тёма", "Тема", "Макс",
    "Боря", "Витя", "Юра", "Гриша", "Маша", "Оля", "Наташа", "Ира", "Лена",
    "Таня", "Катя", "Аня", "Даша", "Соня", "Юля", "Света", "Надя", "Люда",
    "Галя", "Ксюша", "Вика", "Настя", "Кристина", "Рома", "Серёжа", "Сережа",
)

FIRST_NAMES = MALE_NAMES + FEMALE_NAMES + SHORT_NAMES

# Слова с заглавной буквы, которые похожи на фамилию или имя, но ими не являются.
NOT_NAMES = {
    "ООО", "ОАО", "ЗАО", "ПАО", "АО", "ИП", "НКО", "ТД", "ГК", "КФХ",
    "Москва", "Московская", "Санкт-Петербург", "Петербург", "Россия",
    "Русский", "Российская", "Европа", "Сибирь", "Урал", "Крым",
    "Менеджер", "Директор", "Клиент", "Клиентка", "Заказчик", "Покупатель",
    "Господин", "Госпожа", "Гражданин", "Гражданка", "Компания", "Фирма",
    "Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота",
    "Воскресенье", "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
    "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
    "Тест", "Заявка", "Тема", "Важно", "Срочно", "Сегодня", "Завтра",
}

# Окончания русских фамилий в разных падежах.
_SURNAME_ENDINGS: list[str] = []
for _stem in ("ов", "ев", "ёв", "ин", "ын"):
    for _tail in ("", "а", "у", "е", "ой", "ым", "ую", "ых", "ые", "ого", "ому", "ою"):
        _SURNAME_ENDINGS.append(_stem + _tail)
for _stem in ("ск", "цк"):
    for _tail in ("ий", "ая", "ое", "ого", "ому", "им", "ой", "ом", "ие", "их", "ими"):
        _SURNAME_ENDINGS.append(_stem + _tail)
_SURNAME_ENDINGS += ["ых", "их", "ко", "ук", "юк", "ян", "енко", "чук", "ич"]

SURNAME_PATTERN = "(?:" + "|".join(
    sorted(set(_SURNAME_ENDINGS), key=len, reverse=True)
) + ")"


# ---------------------------------------------------------------------------
# Регулярные выражения
# ---------------------------------------------------------------------------

EMAIL_RE = re.compile(r"\b[\w.+\-]+@[\w\-]+(?:\.[\w\-]+)*\.[A-Za-zА-Яа-яЁё]{2,}\b")

PHONE_RE = re.compile(
    r"(?<![\d])"
    r"(?:"
    r"(?:\+7|8)[\s\-]?\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}"
    r"|\(?\d{3}\)?[\s\-]\d{3}[\s\-]\d{2}[\s\-]\d{2}"
    r"|\(\d{3}\)[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}"
    r")"
    r"(?![\d])"
)

CARD_RE = re.compile(r"(?<![\d])(?:\d[ \-]?){15,18}\d(?![\d])")

SNILS_RE = re.compile(r"(?<![\d])\d{3}-\d{3}-\d{3}[ \-]?\d{2}(?![\d])")

PASSPORT_RE = re.compile(
    r"(?i)(?:паспорт\w*|серия\s+и\s+номер|серия)\s*[:№]?\s*"
    r"(\d{2}\s?\d{2}\s?(?:№\s?)?\d{6})"
)

INN_RE = re.compile(r"(?i)(?:ИНН|ОГРНИП|ОГРН)\s*[:№]?\s*(\d{10,15})")

BIRTHDATE_RE = re.compile(
    r"(?i)(?:дата\s+рождения|родил(?:ся|ась)|д\.\s?р\.)\s*[:№\-]?\s*"
    r"(\d{1,2}[./]\d{1,2}[./]\d{2,4}|\d{1,2}\s+[а-яё]+\s+\d{4})"
)

MESSENGER_RE = re.compile(
    r"(?:https?://)?(?:www\.)?(?:t\.me|wa\.me|viber\.me|vk\.com|instagram\.com|tiktok\.com)/[\w.\-/?=&%]+"
    r"|(?<![\w.])@[A-Za-z0-9_]{4,}"
)

ADDRESS_START = (
    r"(?:"
    r"(?:[А-ЯЁ][а-яё\-]+\s+(?:обл\.|область|край|респ\.|республика))"
    r"|(?:(?:г\.|город)\s*[А-ЯЁ][а-яё\-]+)"
    r"|(?:(?:ул\.|улица|пр-т|проспект|пер\.|переулок|б-р|бульвар|ш\.|шоссе"
    r"|наб\.|набережная|пл\.|площадь|мкр\.|микрорайон)\s+[^,;\n]{2,60})"
    r"|(?:(?:пос\.|посёлок|поселок|дер\.|деревня|с\.)\s+[А-ЯЁ][а-яё\-]+)"
    r"|(?:(?:д\.|дом)\s*\d+[А-Яа-я]?(?:\s*,\s*(?:кв\.|квартира)\s*\d+)?)"
    r")"
)

ADDRESS_RE = re.compile(ADDRESS_START + r"(?:\s*,\s*[^,;\n]{1,60}){0,6}")

# Сокращения, после которых точка не завершает предложение.
_ADDRESS_ABBREVIATIONS = {
    "ул", "д", "кв", "обл", "г", "пер", "мкр", "пос", "стр", "корп", "наб",
    "пл", "пр", "ш", "с", "дер", "респ", "оф", "пом", "бул", "туп", "проезд",
    "р", "п", "им", "мкр-н", "пр-т",
}


def _cut_sentence(value: str) -> int:
    """Где заканчивается адрес: точка с пробелом и заглавной буквой после неё.

    Сокращения («ул.», «д.», «кв.») границей не считаются.
    """
    for match in re.finditer(r"\.(?=\s+[А-ЯЁ])", value):
        word = re.split(r"[^\w\-]+", value[:match.start()])[-1].lower()
        if word not in _ADDRESS_ABBREVIATIONS:
            return match.start()

    if value.endswith("."):
        word = re.split(r"[^\w\-]+", value[:-1])[-1].lower()
        if word not in _ADDRESS_ABBREVIATIONS:
            return len(value) - 1

    return len(value)

POSTAL_RE = re.compile(
    r"(?<![\d])\d{6}(?![\d])\s*,?\s*(?:обл\.|область|край|респ\.|республика)"
)

NAME_LABEL_RE = re.compile(r"(?im)^\s*Имя\s*:\s*([^\n]+)$")
PHONE_LABEL_RE = re.compile(r"(?im)^\s*Телефон\s*:\s*([^\n]+)$")
EMAIL_LABEL_RE = re.compile(r"(?im)^\s*E-?mail\s*:\s*([^\n]+)$")

FULL_NAME_RE = re.compile(
    r"\b[А-ЯЁ][а-яё\-]+\s+[А-ЯЁ][а-яё\-]+\s+[А-ЯЁ][а-яё\-]*"
    r"(?:ович|евич|ич|овна|евна|ична|инична)\b"
)

NAME_THEN_SURNAME_RE = re.compile(
    r"\b(" + "|".join(sorted(FIRST_NAMES, key=len, reverse=True)) + r")\b"
    r"\s+[А-ЯЁ][а-яё\-]*" + SURNAME_PATTERN + r"\b"
)

SURNAME_THEN_NAME_RE = re.compile(
    r"\b[А-ЯЁ][а-яё\-]*" + SURNAME_PATTERN + r"\s+"
    r"(" + "|".join(sorted(FIRST_NAMES, key=len, reverse=True)) + r")\b"
)

FIRST_NAME_RE = re.compile(
    r"\b(" + "|".join(sorted(FIRST_NAMES, key=len, reverse=True)) + r")\b"
)

SURNAME_ONLY_RE = re.compile(
    r"\b[А-ЯЁ][а-яё\-]{2,}" + SURNAME_PATTERN + r"\b"
)

MASK_PATTERN = r"\[\s*{kind}\s*[_\-–:]?\s*(\d{{1,3}})\s*\]"


# ---------------------------------------------------------------------------
# Правила
# ---------------------------------------------------------------------------

@dataclass
class Rule:
    kind: str
    pattern: re.Pattern
    group: int = 0
    validate: Callable[[str], bool] | None = None


def luhn_ok(digits: str) -> bool:
    """Проверка контрольной суммы банковской карты."""
    numbers = [int(ch) for ch in digits if ch.isdigit()]
    if not 13 <= len(numbers) <= 19:
        return False
    checksum = 0
    for index, number in enumerate(reversed(numbers)):
        if index % 2 == 1:
            number *= 2
            if number > 9:
                number -= 9
        checksum += number
    return checksum % 10 == 0


_STOPWORDS = {word.lower() for word in NOT_NAMES}


def is_real_name(value: str) -> bool:
    """Отсеять слова с заглавной буквы, которые только похожи на имя."""
    return value.strip().strip(".,;:!?)(").lower() not in _STOPWORDS


def looks_like_card(value: str) -> bool:
    """Карта - это номер с верной контрольной суммой или 16 цифр по группам.

    Опечатка в контрольной сумме не должна приводить к утечке, поэтому
    классическая запись 4+4+4+4 цифрами через пробел или дефис маскируется
    и без проверки Луна.
    """
    digits = re.sub(r"\D", "", value)
    if not 13 <= len(digits) <= 19:
        return False
    if luhn_ok(digits):
        return True
    return len(digits) == 16 and bool(re.search(r"[ \-]", value))


RULES: list[Rule] = [
    # Явные подписи из формы - самый надёжный источник.
    Rule(KIND_NAME, NAME_LABEL_RE, group=1),
    Rule(KIND_PHONE, PHONE_LABEL_RE, group=1),
    Rule(KIND_EMAIL, EMAIL_LABEL_RE, group=1),
    # Специфичные форматы.
    Rule(KIND_EMAIL, EMAIL_RE),
    Rule(KIND_MESSENGER, MESSENGER_RE),
    Rule(KIND_CARD, CARD_RE, validate=looks_like_card),
    Rule(KIND_SNILS, SNILS_RE),
    Rule(KIND_PASSPORT, PASSPORT_RE, group=1),
    Rule(KIND_INN, INN_RE, group=1),
    Rule(KIND_BIRTHDATE, BIRTHDATE_RE, group=1),
    Rule(KIND_ADDRESS, POSTAL_RE),
    Rule(KIND_PHONE, PHONE_RE),
    # Адреса.
    Rule(KIND_ADDRESS, ADDRESS_RE),
    # Имена.
    Rule(KIND_NAME, FULL_NAME_RE),
    Rule(KIND_NAME, NAME_THEN_SURNAME_RE),
    Rule(KIND_NAME, SURNAME_THEN_NAME_RE),
    Rule(KIND_NAME, FIRST_NAME_RE, validate=is_real_name),
    Rule(KIND_NAME, SURNAME_ONLY_RE, validate=is_real_name),
]


# ---------------------------------------------------------------------------
# Результат обезличивания
# ---------------------------------------------------------------------------

@dataclass
class MaskedText:
    """Обезличенный текст и его расшифровка.

    mapping: {метка: реальное значение} - только в памяти текущего запроса.
    """

    text: str
    mapping: dict[str, str]
    counts: dict[str, int] = field(default_factory=dict)

    @property
    def total(self) -> int:
        return sum(self.counts.values())


def _normalize_key(kind: str, value: str) -> str:
    """Ключ для склейки одинаковых значений в одну метку."""
    if kind in (KIND_PHONE, KIND_CARD, KIND_SNILS, KIND_INN):
        return re.sub(r"\D", "", value)
    return re.sub(r"\s+", " ", value.strip().lower())


def _collect(text: str, rules: Iterable[Rule]) -> list[tuple[int, int, int, str, str]]:
    found: list[tuple[int, int, int, str, str]] = []
    for order, rule in enumerate(rules):
        for match in rule.pattern.finditer(text):
            try:
                value = match.group(rule.group)
            except IndexError:
                continue
            if not value or not value.strip():
                continue
            if rule.validate is not None and not rule.validate(value):
                continue
            if rule.group:
                start, end = match.start(rule.group), match.end(rule.group)
            else:
                start, end = match.start(), match.end()
            if rule.kind == KIND_ADDRESS:
                original_len = len(value)
                value = value[:_cut_sentence(value)].rstrip(" .,;:")
                end -= original_len - len(value)
                if not value.strip():
                    continue
            found.append((start, end, order, rule.kind, value))
    return found


def _select(found: list[tuple[int, int, int, str, str]]) -> list[tuple[int, int, int, str, str]]:
    """Разрешить пересечения: при равном начале выигрывает более длинное совпадение."""
    found.sort(key=lambda item: (item[0], -(item[1] - item[0]), item[2]))
    selected: list[tuple[int, int, int, str, str]] = []
    last_end = -1
    for item in found:
        start, end = item[0], item[1]
        if start < last_end:
            continue
        selected.append(item)
        last_end = end
    return selected


def anonymize(text: str) -> MaskedText:
    """Заменить персональные данные метками.

    Возвращает MaskedText: обезличенный текст, словарь «метка -> значение»
    и количество замен по видам. Словарь нигде не сохраняется.
    """
    if not text:
        return MaskedText(text=text or "", mapping={}, counts={})

    selected = _select(_collect(text, RULES))

    counters: dict[str, int] = {}
    tokens: dict[tuple[str, str], str] = {}
    mapping: dict[str, str] = {}
    pieces: list[str] = []
    cursor = 0

    for start, end, _order, kind, value in selected:
        key = (kind, _normalize_key(kind, value))
        token = tokens.get(key)
        if token is None:
            counters[kind] = counters.get(kind, 0) + 1
            token = f"[{kind}_{counters[kind]}]"
            tokens[key] = token
            mapping[token] = value
        pieces.append(text[cursor:start])
        pieces.append(token)
        cursor = end

    pieces.append(text[cursor:])
    return MaskedText(text="".join(pieces), mapping=mapping, counts=counters)


# ---------------------------------------------------------------------------
# Восстановление
# ---------------------------------------------------------------------------

TOKEN_RE = re.compile(
    r"\[\s*(ИМЯ|ТЕЛЕФОН|EMAIL|АДРЕС|ПАСПОРТ|СНИЛС|ИНН|КАРТА|ДАТА[\s_]*РОЖДЕНИЯ|МЕССЕНДЖЕР)"
    r"\s*[_\-–:]?\s*(\d{1,3})\s*\]",
    re.IGNORECASE,
)

LOOSE_TOKEN_RE = re.compile(
    r"(?<!\[)\b(ИМЯ|ТЕЛЕФОН|EMAIL|АДРЕС|ПАСПОРТ|СНИЛС|ИНН|КАРТА|ДАТА[\s_]*РОЖДЕНИЯ|МЕССЕНДЖЕР)"
    r"[_\-–:](\d{1,3})\b(?!\])",
    re.IGNORECASE,
)


def _restore_with(pattern: re.Pattern, text: str, mapping: dict[str, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        kind = re.sub(r"[\s_]+", "_", match.group(1).upper())
        token = f"[{kind}_{match.group(2)}]"
        return mapping.get(token, match.group(0))

    return pattern.sub(replace, text)


def restore(text: str, mapping: dict[str, str]) -> str:
    """Подставить реальные значения вместо меток.

    Терпит искажения ответа модели: другой регистр, пробел или дефис вместо
    подчёркивания, потерянные квадратные скобки.
    """
    if not text or not mapping or not isinstance(text, str):
        return text
    text = _restore_with(TOKEN_RE, text, mapping)
    return _restore_with(LOOSE_TOKEN_RE, text, mapping)


def restore_result(result: dict[str, Any], mapping: dict[str, str]) -> dict[str, Any]:
    """Восстановить значения во всех текстовых полях карточки результата."""
    if not mapping:
        return result

    def walk(value: Any) -> Any:
        if isinstance(value, str):
            return restore(value, mapping)
        if isinstance(value, list):
            return [walk(item) for item in value]
        if isinstance(value, dict):
            return {key: walk(item) for key, item in value.items()}
        return value

    return {key: walk(value) for key, value in result.items()}


def describe(counts: dict[str, int]) -> str:
    """Человеческое описание замен: «имена: 1, телефоны: 1»."""
    parts = [
        f"{KIND_LABELS.get(kind, kind)}: {count}"
        for kind, count in sorted(counts.items())
    ]
    return ", ".join(parts)
