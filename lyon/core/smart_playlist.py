"""Smart playlist rule model, JSON serialization, and SQL compiler."""
from __future__ import annotations

import json
from dataclasses import dataclass, field


# (display_label, db_column, value_type)
FIELDS: list[tuple[str, str, str]] = [
    ("Title",       "title",      "text"),
    ("Artist",      "artist",     "text"),
    ("Album",       "album",      "text"),
    ("Genre",       "genre",      "text"),
    ("Year",        "year",       "int"),
    ("Rating",      "rating",     "int"),
    ("Play Count",  "play_count", "int"),
    ("Bitrate",     "bitrate",    "int"),
    ("Duration",    "duration",   "int"),
    ("Liked",       "liked",      "bool"),
]

FIELD_MAP: dict[str, tuple[str, str, str]] = {col: (disp, col, vtype) for disp, col, vtype in FIELDS}

TEXT_OPS: list[tuple[str, str]] = [
    ("contains",     "Contains"),
    ("not_contains", "Does not contain"),
    ("starts_with",  "Starts with"),
    ("ends_with",    "Ends with"),
    ("is",           "Is"),
    ("is_not",       "Is not"),
]

INT_OPS: list[tuple[str, str]] = [
    ("is",      "Is"),
    ("is_not",  "Is not"),
    ("gt",      ">"),
    ("gte",     "≥"),
    ("lt",      "<"),
    ("lte",     "≤"),
    ("between", "Between"),
]

BOOL_OPS: list[tuple[str, str]] = [
    ("is", "Is"),
]

OPS_FOR_TYPE: dict[str, list[tuple[str, str]]] = {
    "text": TEXT_OPS,
    "int":  INT_OPS,
    "bool": BOOL_OPS,
}

ORDER_BY_OPTIONS: list[tuple[str, str]] = [
    ("title",      "Title"),
    ("artist",     "Artist"),
    ("album",      "Album"),
    ("year",       "Year"),
    ("rating",     "Rating"),
    ("play_count", "Play Count"),
    ("duration",   "Duration"),
    ("bitrate",    "Bitrate"),
    ("last_played","Last Played"),
]

_ORDER_BY_COLS: frozenset[str] = frozenset(col for col, _ in ORDER_BY_OPTIONS)


@dataclass
class Rule:
    field: str
    op: str
    value: str
    value2: str = ""


@dataclass
class SmartPlaylistSpec:
    match: str = "all"
    rules: list[Rule] = field(default_factory=list)
    limit: int = 0
    order_by: str = "title"
    order_desc: bool = False


def spec_to_json(spec: SmartPlaylistSpec) -> str:
    return json.dumps({
        "match": spec.match,
        "rules": [
            {"field": r.field, "op": r.op, "value": r.value, "value2": r.value2}
            for r in spec.rules
        ],
        "limit": spec.limit,
        "order_by": spec.order_by,
        "order_desc": spec.order_desc,
    })


def spec_from_json(s: str) -> SmartPlaylistSpec:
    try:
        data = json.loads(s)
    except Exception:
        return SmartPlaylistSpec()
    rules = [
        Rule(
            field=str(r.get("field", "title")),
            op=str(r.get("op", "contains")),
            value=str(r.get("value", "")),
            value2=str(r.get("value2", "")),
        )
        for r in (data.get("rules") or [])
        if isinstance(r, dict)
    ]
    return SmartPlaylistSpec(
        match=str(data.get("match") or "all"),
        rules=rules,
        limit=max(0, int(data.get("limit") or 0)),
        order_by=str(data.get("order_by") or "title"),
        order_desc=bool(data.get("order_desc", False)),
    )


def spec_to_where(spec: SmartPlaylistSpec) -> tuple[str, list]:
    """Compile spec rules into a (WHERE clause, params) tuple for the tracks table."""
    parts: list[str] = []
    params: list = []

    for rule in spec.rules:
        finfo = FIELD_MAP.get(rule.field)
        if finfo is None:
            continue
        _, col, vtype = finfo
        clause, rule_params = _rule_to_sql(col, rule.op, rule.value, rule.value2, vtype)
        if clause:
            parts.append(clause)
            params.extend(rule_params)

    if not parts:
        return "1=1", []
    joiner = " AND " if spec.match == "all" else " OR "
    return joiner.join(f"({p})" for p in parts), params


def spec_order_and_limit(spec: SmartPlaylistSpec) -> tuple[str, str]:
    """Return (ORDER BY clause, LIMIT clause) strings (no leading spaces)."""
    col = spec.order_by if spec.order_by in _ORDER_BY_COLS else "title"
    direction = "DESC" if spec.order_desc else "ASC"
    order = f"{col} {direction}"
    limit = f"LIMIT {spec.limit}" if spec.limit > 0 else ""
    return order, limit


def _rule_to_sql(
    col: str, op: str, value: str, value2: str, vtype: str
) -> tuple[str, list]:
    if vtype == "text":
        if op == "contains":
            return f"{col} LIKE ?", [f"%{value}%"]
        if op == "not_contains":
            return f"{col} NOT LIKE ?", [f"%{value}%"]
        if op == "starts_with":
            return f"{col} LIKE ?", [f"{value}%"]
        if op == "ends_with":
            return f"{col} LIKE ?", [f"%{value}"]
        if op == "is":
            return f"lower({col}) = lower(?)", [value]
        if op == "is_not":
            return f"lower({col}) != lower(?)", [value]

    elif vtype == "int":
        try:
            iv = int(value)
        except (ValueError, TypeError):
            return "", []
        if op == "is":
            return f"{col} = ?", [iv]
        if op == "is_not":
            return f"{col} != ?", [iv]
        if op == "gt":
            return f"{col} > ?", [iv]
        if op == "gte":
            return f"{col} >= ?", [iv]
        if op == "lt":
            return f"{col} < ?", [iv]
        if op == "lte":
            return f"{col} <= ?", [iv]
        if op == "between":
            try:
                iv2 = int(value2)
            except (ValueError, TypeError):
                return "", []
            return f"{col} BETWEEN ? AND ?", [iv, iv2]

    elif vtype == "bool":
        bv = 1 if value.lower() in ("1", "true", "yes") else 0
        if op == "is":
            return f"{col} = ?", [bv]

    return "", []
