from __future__ import annotations

import json
from typing import Any

from orchestrator.contracts.manifests import ContentSchema


def _normalize_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, dict):
        parts: list[str] = []
        for key in ("title", "label", "name"):
            if value.get(key):
                parts.append(str(value[key]).strip())
        for key in ("value", "text", "description", "summary", "unit"):
            if value.get(key):
                parts.append(str(value[key]).strip())
        if parts:
            return " - ".join(part for part in parts if part)
        preferred_keys = ("label", "title", "name", "value", "text", "description", "persona", "summary")
        for key in preferred_keys:
            nested = value.get(key)
            if nested:
                text = _normalize_text(nested)
                if text:
                    return text
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    if isinstance(value, (list, tuple, set)):
        items = [_normalize_text(item) for item in value]
        items = [item for item in items if item]
        return "; ".join(items)
    return str(value).strip()


def _normalize_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, dict):
        preferred_keys = ("items", "values", "options", "pillars", "kpis", "points", "entries")
        for key in preferred_keys:
            nested = value.get(key)
            if nested is not None:
                items = _normalize_list(nested)
                if items:
                    return items
        text = _normalize_text(value)
        return [text] if text else []
    if isinstance(value, (list, tuple, set)):
        flattened: list[str] = []
        for item in value:
            if isinstance(item, (list, tuple, set)):
                flattened.extend(_normalize_list(item))
                continue
            text = _normalize_text(item)
            if text:
                flattened.append(text)
        return flattened
    text = _normalize_text(value)
    return [text] if text else []


def build_content_schema(schema_raw: Any) -> ContentSchema:
    if isinstance(schema_raw, ContentSchema):
        return schema_raw
    if not isinstance(schema_raw, dict):
        return ContentSchema()

    return ContentSchema(
        strategic_pillars=_normalize_list(schema_raw.get("strategic_pillars")),
        kpis=_normalize_list(schema_raw.get("kpis")),
        target_audience=_normalize_text(schema_raw.get("target_audience")),
        vision_statement=_normalize_text(schema_raw.get("vision_statement")),
        timeline=_normalize_text(schema_raw.get("timeline")),
    )
