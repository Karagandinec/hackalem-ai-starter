"""JSON Schema для Structured Outputs — модель обязана вернуть ровно такую форму.

Правила strict-режима OpenAI (иначе будет ошибка 400):
  * у каждого объекта "additionalProperties": false;
  * ВСЕ ключи из properties перечислены в "required" (необязательных нет —
    если поле может отсутствовать, разреши ему быть null: "type": ["string", "null"]).

Это два примера под типовые задачи хакатона. Свой кейс — добавляй схему рядом.
"""

# Аналитика по данным дашборда: 3 инсайта + рекомендация.
INSIGHT_SCHEMA: dict = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "summary": {"type": "string", "description": "Одно предложение: что происходит с данными"},
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
                    "metric": {"type": ["string", "null"], "description": "На какую метрику опирается"},
                },
                "required": ["title", "detail", "severity", "metric"],
            },
        },
        "recommendation": {"type": "string", "description": "Что конкретно сделать дальше"},
    },
    "required": ["summary", "insights", "recommendation"],
}

# Классификация произвольного текста — заявки, отзыва, сообщения.
CLASSIFY_SCHEMA: dict = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "category": {"type": "string", "description": "Категория одним словом"},
        "priority": {"type": "string", "enum": ["low", "medium", "high"]},
        "sentiment": {"type": "string", "enum": ["negative", "neutral", "positive"]},
        "reason": {"type": "string", "description": "Почему именно так"},
        "tags": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["category", "priority", "sentiment", "reason", "tags"],
}


# Разметка одной записи из базы: используется в POST /api/ai/enrich.
ENRICH_SCHEMA: dict = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "label": {"type": "string", "description": "Короткая метка, 1-2 слова"},
        "score": {"type": "number", "description": "Уверенность или оценка от 0 до 1"},
        "reason": {"type": "string", "description": "Одно предложение: почему такая метка"},
    },
    "required": ["label", "score", "reason"],
}
