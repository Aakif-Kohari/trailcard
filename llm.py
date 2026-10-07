"""Local language-model text for TrailCard, via Ollama, with a safe fallback.

Design rules:

* The model only *writes words*. Every number comes from ``planner.py``.
* The model's output is parsed into the six card sections.
* Any clock time the model mentions that is not in the plan is treated as a
  hallucination, and the card falls back to the deterministic template.
* If Ollama is not running, the card is still produced from the template.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field

import ollama

from planner import TIME_KEYS

DEFAULT_MODEL = "gemma3"
MODEL_ENV_VAR = "TRAILCARD_MODEL"

SECTION_TITLES = (
    "Summary",
    "Timeline",
    "Pack list",
    "Turnaround rule",
    "If you get lost",
    "Leave No Trace",
)

SYSTEM_PROMPT = (
    "You write short, practical trail cards for hikers. "
    "Use ONLY the facts in the JSON the user sends. "
    "Never invent times, distances, weather, wildlife or place names. "
    "Output plain text only: no markdown, no asterisks, no # symbols. "
    "Use exactly these section headings, each on its own line and ending with a colon: "
    + ", ".join(f"{t}:" for t in SECTION_TITLES)
    + ". Under each heading write 2 to 5 short lines that each start with '- '. "
    "Keep the whole card under 300 words in plain language."
)

_HEADING_RE = re.compile(
    r"^\W*(" + "|".join(re.escape(t) for t in SECTION_TITLES) + r")\W*?(?::\s*(.*))?$",
    re.IGNORECASE,
)
_TIME_RE = re.compile(r"\b([01]?\d|2[0-3]):([0-5]\d)\b")


@dataclass
class Card:
    """The text content of a trail card."""

    sections: list[dict] = field(default_factory=list)  # [{"title": str, "lines": [str]}]
    source: str = "template"  # "model" or "template"
    model: str | None = None
    warning: str | None = None


# --------------------------------------------------------------------------- #
# Model discovery
# --------------------------------------------------------------------------- #
def available_models() -> list[str]:
    """Names of models installed in the local Ollama, or ``[]`` if unreachable."""
    try:
        response = ollama.list()
    except Exception:
        return []

    items = response["models"] if isinstance(response, dict) else getattr(response, "models", [])
    names: list[str] = []
    for item in items or []:
        if isinstance(item, dict):
            name = item.get("model") or item.get("name")
        else:
            name = getattr(item, "model", None) or getattr(item, "name", None)
        if name:
            names.append(str(name))
    return names


def default_model(installed: list[str] | None = None) -> str:
    """Pick a model: env var, else an installed Gemma, else ``DEFAULT_MODEL``."""
    env = os.getenv(MODEL_ENV_VAR)
    if env:
        return env
    installed = installed or []
    gemma = [name for name in installed if name.lower().startswith("gemma")]
    if gemma:
        return gemma[0]
    return installed[0] if installed else DEFAULT_MODEL


# --------------------------------------------------------------------------- #
# Parsing and validation
# --------------------------------------------------------------------------- #
def _clean_line(line: str) -> str:
    line = line.strip()
    line = re.sub(r"^[-*\u2022\u25cf]+\s*", "", line)  # bullet markers
    line = re.sub(r"^\d+[.)]\s+", "", line)  # "1. " numbering
    line = line.replace("**", "").replace("__", "").replace("`", "")
    return line.strip()


def parse_sections(text: str) -> dict[str, list[str]]:
    """Split model output into ``{section title: [lines]}`` (known titles only)."""
    sections: dict[str, list[str]] = {}
    current: str | None = None

    for raw in text.splitlines():
        stripped = raw.strip().strip("#").strip()
        match = _HEADING_RE.match(stripped.replace("**", ""))
        if match:
            title = next(t for t in SECTION_TITLES if t.lower() == match.group(1).lower())
            current = title
            sections.setdefault(current, [])
            rest = (match.group(2) or "").strip()
            if rest:
                sections[current].append(_clean_line(rest))
            continue
        if current is None:
            continue
        cleaned = _clean_line(raw)
        if cleaned:
            sections[current].append(cleaned)

    return {title: lines for title, lines in sections.items() if lines}


def find_unknown_times(text: str, plan: dict) -> list[str]:
    """Clock times in ``text`` that do not appear anywhere in the plan."""
    allowed = {plan[key] for key in TIME_KEYS if plan.get(key)}
    found = {f"{int(h):02d}:{m}" for h, m in _TIME_RE.findall(text)}
    return sorted(found - allowed)


# --------------------------------------------------------------------------- #
# Deterministic template (also the offline fallback)
# --------------------------------------------------------------------------- #
def template_sections(plan: dict) -> list[dict]:
    """Build the card sections purely from the plan numbers."""
    p = plan
    turn_word = "far end" if p.get("route_type") == "out-and-back" else "halfway point"
    return [
        {
            "title": "Summary",
            "lines": [
                f"{p['trail_name']} on {p['date']} ({p['route_type']}), group of {p['group_size']}.",
                f"{p['distance_km']} km with {p['elevation_gain_m']} m of climbing.",
                f"About {p['walking_time_hours']} h of walking plus {p['break_minutes']} min of breaks.",
            ],
        },
        {
            "title": "Timeline",
            "lines": [
                f"Start {p['start_time']}, sunrise {p['sunrise']}, sunset {p['sunset']} ({p['utc_offset']}).",
                f"Planned halfway point: {p['midpoint_time']}.",
                f"Planned finish: {p['finish_time']}. Aim to be done by {p['target_finish']}.",
                f"Latest safe start for this route: {p['latest_safe_start']}.",
            ],
        },
        {
            "title": "Pack list",
            "lines": [
                f"Water: {p['water_per_person_liters']:g} L per person ({p['water_liters']:g} L for the group).",
                "Food for the whole trip plus a little extra.",
                "Warm and rain layers, headlamp, first-aid kit, whistle.",
                "Offline map or GPX track, and a charged phone or power bank.",
            ],
        },
        {
            "title": "Turnaround rule",
            "lines": [
                f"If you have not reached the {turn_word} by {p['hard_turnaround_time']}, turn back or shorten the route.",
                "Turn back earlier if anyone is struggling or the weather changes.",
                "Daylight does not wait: do not trade safety for the summit.",
            ],
        },
        {
            "title": "If you get lost",
            "lines": [
                "Stop, stay calm, and do not wander further off the path.",
                f"Your planned location: {p['latitude']}, {p['longitude']}.",
                f"Emergency number: {p['emergency_number']}. Call early and keep your battery for it.",
            ],
        },
        {
            "title": "Leave No Trace",
            "lines": [
                "Pack out all rubbish, including food scraps.",
                "Stay on the trail and keep a respectful distance from wildlife.",
                "Leave plants, rocks and cultural features as you found them.",
            ],
        },
    ]


# --------------------------------------------------------------------------- #
# Generation
# --------------------------------------------------------------------------- #
def _message_content(response) -> str:
    """Extract the text from an ollama chat response (dict or object)."""
    message = response["message"] if isinstance(response, dict) else response.message
    content = message["content"] if isinstance(message, dict) else message.content
    return (content or "").strip()


def generate_card(plan: dict, model: str | None = None, use_ai: bool = True) -> Card:
    """Produce the card text, using the local model when possible."""
    fallback = template_sections(plan)

    if not use_ai:
        return Card(sections=fallback, source="template")

    model = model or default_model()
    try:
        response = ollama.chat(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(plan, ensure_ascii=False)},
            ],
            options={"temperature": 0.2},
        )
        text = _message_content(response)
    except Exception as exc:
        return Card(
            sections=fallback,
            source="template",
            warning=(
                f"Could not reach the local model '{model}' ({exc}). "
                "Showing the template-only card. Is Ollama running and the model pulled?"
            ),
        )

    if not text:
        return Card(
            sections=fallback,
            source="template",
            warning="The model returned an empty answer, so the template-only card is shown.",
        )

    unknown = find_unknown_times(text, plan)
    if unknown:
        return Card(
            sections=fallback,
            source="template",
            warning=(
                "The model mentioned times that are not in the plan ("
                + ", ".join(unknown)
                + "), so the template-only card is shown instead."
            ),
        )

    parsed = parse_sections(text)
    if len(parsed) < 3:
        return Card(
            sections=fallback,
            source="template",
            warning="The model's answer could not be read as a trail card, so the template-only card is shown.",
        )

    fallback_by_title = {s["title"]: s for s in fallback}
    sections = [
        {"title": title, "lines": parsed[title]} if title in parsed else fallback_by_title[title]
        for title in SECTION_TITLES
    ]
    filled = [t for t in SECTION_TITLES if t not in parsed]
    warning = (
        "The model skipped some sections, which were filled from the template: " + ", ".join(filled) + "."
        if filled
        else None
    )
    return Card(sections=sections, source="model", model=model, warning=warning)
