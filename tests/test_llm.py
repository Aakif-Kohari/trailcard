from datetime import date, time
from types import SimpleNamespace

import pytest

import llm
from planner import compute_plan


@pytest.fixture
def plan():
    return compute_plan(
        trail_name="Test Trail",
        on_date=date(2026, 10, 10),
        start_time=time(8, 0),
        distance_km=10,
        elevation_gain_m=300,
        group_size=2,
        latitude=47.6,
        longitude=-122.3,
        utc_offset_hours=-7,
    )


def good_text(plan):
    return (
        "Summary:\n- A 10 km loop.\n- Bring friends.\n\n"
        f"Timeline:\n- Start at {plan['start_time']}.\n- Back by {plan['finish_time']}.\n\n"
        "Pack list:\n- Water\n- Snacks\n\n"
        f"Turnaround rule:\n- Turn back at {plan['hard_turnaround_time']}.\n\n"
        "If you get lost:\n- Stay calm.\n\n"
        "Leave No Trace:\n- Pack it out.\n"
    )


def fake_chat(text):
    def _chat(**kwargs):
        return {"message": {"content": text}}

    return _chat


def titles(card):
    return [s["title"] for s in card.sections]


def test_template_sections_are_complete_and_use_plan_numbers(plan):
    sections = llm.template_sections(plan)
    assert [s["title"] for s in sections] == list(llm.SECTION_TITLES)
    joined = " ".join(" ".join(s["lines"]) for s in sections)
    assert plan["hard_turnaround_time"] in joined
    assert plan["sunset"] in joined
    # The template itself must never mention a time that is not in the plan.
    assert llm.find_unknown_times(joined, plan) == []


def test_use_ai_false_skips_ollama(plan, monkeypatch):
    def boom(**kwargs):
        raise AssertionError("ollama.chat must not be called")

    monkeypatch.setattr(llm.ollama, "chat", boom)
    card = llm.generate_card(plan, use_ai=False)
    assert card.source == "template" and card.warning is None


def test_model_output_is_used_when_valid(plan, monkeypatch):
    monkeypatch.setattr(llm.ollama, "chat", fake_chat(good_text(plan)))
    card = llm.generate_card(plan, model="gemma3")
    assert card.source == "model"
    assert card.model == "gemma3"
    assert card.warning is None
    assert titles(card) == list(llm.SECTION_TITLES)
    assert card.sections[0]["lines"] == ["A 10 km loop.", "Bring friends."]


def test_markdown_noise_is_cleaned(plan, monkeypatch):
    text = good_text(plan).replace("Summary:", "## **Summary**").replace("- Water", "* **Water**")
    monkeypatch.setattr(llm.ollama, "chat", fake_chat(text))
    card = llm.generate_card(plan)
    assert card.source == "model"
    assert "Water" in card.sections[2]["lines"]


def test_hallucinated_time_triggers_fallback(plan, monkeypatch):
    text = good_text(plan).replace(plan["hard_turnaround_time"], "03:17")
    monkeypatch.setattr(llm.ollama, "chat", fake_chat(text))
    card = llm.generate_card(plan)
    assert card.source == "template"
    assert "03:17" in card.warning


def test_missing_sections_are_filled_from_template(plan, monkeypatch):
    text = "Summary:\n- Short.\n\nTimeline:\n- Early start.\n\nPack list:\n- Water.\n"
    monkeypatch.setattr(llm.ollama, "chat", fake_chat(text))
    card = llm.generate_card(plan)
    assert card.source == "model"
    assert titles(card) == list(llm.SECTION_TITLES)
    assert "Turnaround rule" in card.warning


def test_unparseable_output_falls_back(plan, monkeypatch):
    monkeypatch.setattr(llm.ollama, "chat", fake_chat("Have a lovely walk!"))
    card = llm.generate_card(plan)
    assert card.source == "template"
    assert card.warning


def test_empty_output_falls_back(plan, monkeypatch):
    monkeypatch.setattr(llm.ollama, "chat", fake_chat("   "))
    card = llm.generate_card(plan)
    assert card.source == "template"


def test_unreachable_ollama_falls_back(plan, monkeypatch):
    def boom(**kwargs):
        raise ConnectionError("connection refused")

    monkeypatch.setattr(llm.ollama, "chat", boom)
    card = llm.generate_card(plan, model="gemma3")
    assert card.source == "template"
    assert "connection refused" in card.warning


def test_object_style_response_is_supported(plan, monkeypatch):
    response = SimpleNamespace(message=SimpleNamespace(content=good_text(plan)))
    monkeypatch.setattr(llm.ollama, "chat", lambda **kwargs: response)
    assert llm.generate_card(plan).source == "model"


def test_find_unknown_times_normalises(plan):
    assert llm.find_unknown_times("Meet at 9:05 and 8:00", plan) == ["09:05"]


def test_available_models_handles_both_response_shapes(monkeypatch):
    new = SimpleNamespace(models=[SimpleNamespace(model="gemma3:latest"), SimpleNamespace(model="llama3.2")])
    monkeypatch.setattr(llm.ollama, "list", lambda: new)
    assert llm.available_models() == ["gemma3:latest", "llama3.2"]

    old = {"models": [{"name": "gemma:2b"}, {"model": "qwen3"}]}
    monkeypatch.setattr(llm.ollama, "list", lambda: old)
    assert llm.available_models() == ["gemma:2b", "qwen3"]


def test_available_models_returns_empty_when_unreachable(monkeypatch):
    def boom():
        raise ConnectionError("nope")

    monkeypatch.setattr(llm.ollama, "list", boom)
    assert llm.available_models() == []


def test_default_model_prefers_env_then_gemma(monkeypatch):
    monkeypatch.delenv(llm.MODEL_ENV_VAR, raising=False)
    assert llm.default_model(["llama3.2", "gemma3:4b"]) == "gemma3:4b"
    assert llm.default_model([]) == llm.DEFAULT_MODEL
    monkeypatch.setenv(llm.MODEL_ENV_VAR, "my-model")
    assert llm.default_model(["gemma3:4b"]) == "my-model"
