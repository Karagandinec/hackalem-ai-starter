"""JSON Schema для Structured Outputs — модель обязана вернуть ровно такую форму.

Правила strict-режима OpenAI (иначе будет ошибка 400):
  * у каждого объекта "additionalProperties": false;
  * ВСЕ ключи из properties перечислены в "required" (необязательных нет —
    если поле может отсутствовать, разреши ему быть null: "type": ["string", "null"]).

Схемы заточены под трек «Добывающая промышленность». Свой кейс — добавляй рядом.
"""

# Разметка единицы техники: риск отказа. Используется в POST /api/ai/enrich.
ENRICH_SCHEMA: dict = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "label": {
            "type": "string",
            "enum": ["низкий", "средний", "высокий", "критический"],
            "description": "Риск отказа в ближайшую неделю",
        },
        "score": {"type": "number", "description": "Оценка риска от 0 до 1"},
        "reason": {"type": "string", "description": "Одно предложение: почему такой риск"},
        "action": {"type": "string", "description": "Что сделать: осмотр узла, вывести в ТО, наблюдать"},
    },
    "required": ["label", "score", "reason", "action"],
}

# Аналитика по парку: выводы и что делать. Используется в POST /api/ai/insights.
INSIGHT_SCHEMA: dict = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "summary": {"type": "string", "description": "Одно предложение: что происходит с парком"},
        "insights": {
            "type": "array",
            "description": "От 2 до 4 наблюдений",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "title": {"type": "string"},
                    "detail": {"type": "string"},
                    "severity": {"type": "string", "enum": ["info", "warning", "critical"]},
                    "metric": {"type": ["string", "null"], "description": "На какую цифру опирается"},
                },
                "required": ["title", "detail", "severity", "metric"],
            },
        },
        "recommendation": {"type": "string", "description": "Что конкретно сделать дальше"},
    },
    "required": ["summary", "insights", "recommendation"],
}

# Разбор произвольного текста: заявка от мастера, запись из журнала, рация.
CLASSIFY_SCHEMA: dict = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "category": {
            "type": "string",
            "enum": ["отказ", "плановое ТО", "простой", "авария", "нарушение ТБ", "прочее"],
        },
        "unit": {"type": ["string", "null"], "description": "Какая техника упомянута, если названа"},
        "urgency": {"type": "string", "enum": ["низкая", "средняя", "высокая"]},
        "downtime_hours_estimate": {"type": "number", "description": "Оценка простоя в часах"},
        "reason": {"type": "string", "description": "Почему именно так"},
    },
    "required": ["category", "unit", "urgency", "downtime_hours_estimate", "reason"],
}
