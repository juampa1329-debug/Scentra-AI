from __future__ import annotations

import re
from typing import Any


_AI_PREFIX_RE = re.compile(r"^(?:\s*IA:\s*)+", re.IGNORECASE)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n+")
_CLAUSE_SPLIT_RE = re.compile(
    r"\s+(?:pero|ademas|tambien)\s+|\s+y\s+(?=(?:tuvo|tiene|esta|ha|envio|necesita|pregunto|reitero|quiere|solicita|confirmo|pidio|se)\b)",
    re.IGNORECASE,
)


def _clean(value: Any, limit: int) -> str:
    return str(value or "").strip()[:limit]


def _note_key(value: Any) -> str:
    text_value = _AI_PREFIX_RE.sub("", _clean(value, 900))
    text_value = re.sub(r"\s+", " ", text_value).strip().casefold()
    return re.sub(r"[\W_]+", "", text_value, flags=re.UNICODE)[:600]


def _ai_note_units(value: Any, limit: int) -> list[str]:
    raw = _clean(value, limit).replace("\r", "\n")
    raw = re.sub(r"(?im)^(?:\s*IA:\s*)+", "", raw)
    units: list[str] = []
    for sentence in _SENTENCE_SPLIT_RE.split(raw):
        sentence = re.sub(r"\s+", " ", sentence).strip(" -\t")
        if not sentence:
            continue
        for clause in _CLAUSE_SPLIT_RE.split(sentence):
            clause = re.sub(r"\s+", " ", clause).strip(" -\t")
            key = _note_key(clause)
            if key:
                units.append(clause[:700].rstrip())
    return units[:40]


def compact_ai_notes(value: Any, limit: int = 5000) -> str:
    raw = _clean(value, limit)
    if not raw:
        return ""
    lines: list[str] = []
    seen_ai: set[str] = set()
    for line in raw.splitlines():
        line_value = line.strip()
        if not line_value:
            continue
        if _AI_PREFIX_RE.match(line_value):
            for unit in _ai_note_units(line_value, limit):
                key = _note_key(unit)
                if key and key not in seen_ai:
                    seen_ai.add(key)
                    lines.append(f"IA: {unit}")
        else:
            lines.append(line_value)
    return "\n".join(lines).strip()[:limit]


def merge_ai_note(existing: Any, incoming: Any, limit: int = 5000) -> str:
    merged = compact_ai_notes(existing, limit=limit)
    lines = [line for line in merged.splitlines() if line.strip()]
    seen_ai = {_note_key(line) for line in lines if _AI_PREFIX_RE.match(line.strip())}
    for unit in _ai_note_units(incoming, limit):
        key = _note_key(unit)
        if key and key not in seen_ai:
            seen_ai.add(key)
            lines.append(f"IA: {unit}")
    return "\n".join(lines).strip()[:limit]
