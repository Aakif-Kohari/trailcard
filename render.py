"""Render the printable HTML trail card."""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from llm import Card

TEMPLATE_DIR = Path(__file__).parent / "templates"

_env = Environment(
    loader=FileSystemLoader(TEMPLATE_DIR),
    autoescape=select_autoescape(["html"]),
)


def slugify(text: str) -> str:
    """Filename-safe slug (``"Example Ridge!"`` -> ``"Example-Ridge"``)."""
    slug = "".join(ch if ch.isalnum() else "-" for ch in text)
    slug = "-".join(part for part in slug.split("-") if part)
    return slug or "trail-card"


def render_card_html(plan: dict, card: Card) -> str:
    """Return a self-contained HTML document for the card."""
    return _env.get_template("card.html").render(plan=plan, card=card)
