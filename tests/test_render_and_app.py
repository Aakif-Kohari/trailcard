from datetime import date, time
from pathlib import Path

from streamlit.testing.v1 import AppTest

import llm
from planner import compute_plan
from render import render_card_html, slugify


APP = Path(__file__).resolve().parents[1] / "app.py"


def make_plan(**kw):
    args = dict(
        trail_name="Ridge <b>Loop</b>",
        on_date=date(2026, 10, 10),
        start_time=time(8, 0),
        distance_km=10,
        elevation_gain_m=300,
        group_size=2,
        latitude=47.6,
        longitude=-122.3,
        utc_offset_hours=-7,
    )
    args.update(kw)
    return compute_plan(**args)


def test_slugify():
    assert slugify("Example Ridge!") == "Example-Ridge"
    assert slugify("???") == "trail-card"


def test_render_escapes_html_and_includes_numbers():
    plan = make_plan()
    html = render_card_html(plan, llm.generate_card(plan, use_ai=False))
    assert "<b>Loop</b>" not in html  # user text must be escaped
    assert "&lt;b&gt;Loop&lt;/b&gt;" in html
    assert plan["hard_turnaround_time"] in html
    assert "no AI model used" in html


def test_render_warns_for_unsafe_plan():
    plan = make_plan(start_time=time(16, 0))
    html = render_card_html(plan, llm.generate_card(plan, use_ai=False))
    assert "Heads up" in html


def test_streamlit_app_end_to_end(monkeypatch):
    monkeypatch.setattr(llm, "available_models", lambda: [])
    monkeypatch.setattr(
        llm,
        "generate_card",
        lambda plan, model=None, use_ai=True: llm.Card(sections=llm.template_sections(plan), source="template"),
    )
    at = AppTest.from_file(str(APP), default_timeout=30).run()
    assert not at.exception

    submit = [b for b in at.button if b.label == "Plan my trail day"][0]
    submit.click().run()
    assert not at.exception
    assert not at.error
    assert "trailcard_result" in at.session_state
    assert len(at.metric) == 5
