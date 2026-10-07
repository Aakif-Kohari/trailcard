"""TrailCard: an offline trail-day planner. Run with: streamlit run app.py"""

from __future__ import annotations

from datetime import time

import streamlit as st
import streamlit.components.v1 as components

import gpx_utils
import llm
import planner
from render import render_card_html, slugify

st.set_page_config(page_title="TrailCard", page_icon="🥾", layout="wide")

st.title("🥾 TrailCard")
st.caption(
    "Plan the trail day here, print the card, then close the laptop and go outside. "
    "Advisory only: always check conditions, carry navigation and use your judgment."
)

# ----------------------------------------------------------------- sidebar --
with st.sidebar:
    st.header("Local AI model")
    installed = llm.available_models()
    use_ai = st.toggle("Write the card text with a local model", value=True)

    if installed:
        preferred = llm.default_model(installed)
        index = installed.index(preferred) if preferred in installed else 0
        model = st.selectbox("Installed Ollama model", installed, index=index, disabled=not use_ai)
        st.success("Ollama is running locally.")
    else:
        model = st.text_input(
            "Model name",
            value=llm.default_model([]),
            disabled=not use_ai,
            help="No models were found. Start Ollama and run `ollama pull gemma3`.",
        )
        st.warning("Ollama not detected. A template-only card will be used.")

    st.caption(
        "Everything runs on this machine. No trail data is sent to any server. "
        "Times, water and turnaround are calculated by plain Python; the model only writes the advice."
    )

# -------------------------------------------------------------------- form --
with st.form("trailcard"):
    st.subheader("Trail")
    trail_name = st.text_input("Trail name", value="Example Ridge Loop")

    col1, col2, col3 = st.columns(3)
    with col1:
        on_date = st.date_input("Date")
        start_time = st.time_input("Start time", value=time(8, 0))
        group_size = st.number_input("Group size", min_value=1, value=2, step=1)
    with col2:
        route_type = st.radio("Route type", planner.ROUTE_TYPES, horizontal=True)
        break_minutes = st.number_input(
            "Planned breaks (minutes)", min_value=0, max_value=480, value=planner.DEFAULT_BREAK_MINUTES, step=5
        )
        emergency_number = st.text_input(
            "Local emergency number",
            value=planner.DEFAULT_EMERGENCY_NUMBER,
            help="112 works on most mobile networks worldwide. Use your local number if you know it.",
        )
    with col3:
        latitude = st.number_input("Latitude", min_value=-90.0, max_value=90.0, value=47.6062, format="%.5f")
        longitude = st.number_input("Longitude", min_value=-180.0, max_value=180.0, value=-122.3321, format="%.5f")
        utc_offset = st.number_input(
            "UTC offset (hours)",
            min_value=-12.0,
            max_value=14.0,
            value=-7.0,
            step=0.25,
            help="Hours from UTC at the trail on the hike date, e.g. 5.5 for India, 1 or 2 for central Europe "
            "(winter/summer), -8 or -7 for US Pacific. Sunset times depend on this being right.",
        )

    st.subheader("Route")
    gpx_file = st.file_uploader("Optional GPX file (overrides the numbers below)", type=["gpx"])
    col4, col5 = st.columns(2)
    with col4:
        distance_km = st.number_input(
            "Total distance (km, full route)", min_value=0.1, value=10.0, step=0.1, format="%.1f"
        )
    with col5:
        elevation_gain_m = st.number_input("Total elevation gain (m)", min_value=0.0, value=300.0, step=10.0, format="%.0f")

    submitted = st.form_submit_button("Plan my trail day", type="primary")

st.caption("Default values are an example. Replace them with your own trail before relying on the card.")

# ------------------------------------------------------------------ submit --
if submitted:
    distance_to_use = float(distance_km)
    elevation_to_use = float(elevation_gain_m)
    gpx_note = None

    if gpx_file is not None:
        try:
            parsed = gpx_utils.parse_gpx(gpx_file.getvalue())
            distance_to_use = parsed["distance_km"]
            elevation_to_use = parsed["elevation_gain_m"]
            gpx_note = (
                f"GPX file used: {distance_to_use:.1f} km and {elevation_to_use:.0f} m of climbing "
                "(small GPS altitude wiggles are filtered out)."
            )
        except ValueError as exc:
            st.warning(f"{exc} Using the numbers typed into the form instead.")

    try:
        plan = planner.compute_plan(
            trail_name=trail_name,
            on_date=on_date,
            start_time=start_time,
            distance_km=distance_to_use,
            elevation_gain_m=elevation_to_use,
            group_size=int(group_size),
            latitude=float(latitude),
            longitude=float(longitude),
            utc_offset_hours=float(utc_offset),
            break_minutes=int(break_minutes),
            route_type=route_type,
            emergency_number=emergency_number,
        )
    except ValueError as exc:
        st.error(f"Could not compute the plan: {exc}")
        st.stop()

    with st.spinner("Writing your trail card..."):
        card = llm.generate_card(plan, model=model or None, use_ai=use_ai)

    st.session_state["trailcard_result"] = {
        "plan": plan,
        "card": card,
        "html": render_card_html(plan, card),
        "filename": f"{slugify(plan['trail_name'])}-trailcard.html",
        "gpx_note": gpx_note,
    }

# ----------------------------------------------------------------- results --
result = st.session_state.get("trailcard_result")
if result:
    plan, card = result["plan"], result["card"]

    if result["gpx_note"]:
        st.info(result["gpx_note"])
    for item in plan["warnings"]:
        st.warning(item)
    if card.warning:
        st.warning(card.warning)

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Walking + breaks", f"{plan['total_time_hours']} h")
    m2.metric("Turn back by", plan["hard_turnaround_time"])
    m3.metric("Planned finish", plan["finish_time"])
    m4.metric("Sunset", plan["sunset"])
    m5.metric("Water (group)", f"{plan['water_liters']:g} L")

    st.download_button(
        "Download card (HTML, open it and print or save as PDF)",
        data=result["html"].encode("utf-8"),
        file_name=result["filename"],
        mime="text/html",
    )
    components.html(result["html"], height=1150, scrolling=True)
