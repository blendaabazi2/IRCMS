import json
from pathlib import Path

import pandas as pd
import streamlit as st

BASE_DIR = Path(__file__).resolve().parents[1]
OUTPUT_DIR = BASE_DIR / "output"
INPUT_DIR = BASE_DIR / "input"

st.set_page_config(page_title="IRCMS Dashboard", layout="wide")

st.title("IRCMS - Intelligent Regulatory Change Management System")
st.caption("6-Agent Compliance Pipeline Dashboard")


def load_json(filename, default):
    path = OUTPUT_DIR / filename
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def load_markdown(filename):
    path = OUTPUT_DIR / filename
    if not path.exists():
        return "File not generated yet. Run `python run_pipeline.py` first."
    return path.read_text(encoding="utf-8")


context = load_json("context_packet.json", {})
changes = load_json("change_register.json", [])
gaps = load_json("gap_analysis.json", [])
impacts = load_json("impact_assessment.json", [])
mappings = load_json("control_mapping.json", [])
metrics = load_json("metrics.json", {})
approval_packet = load_json("approval_packet.json", {})

col1, col2, col3, col4 = st.columns(4)
col1.metric("Total Changes", metrics.get("total_changes", 0))
col2.metric("Total Gaps", metrics.get("total_gaps", 0))
col3.metric("High Risk Gaps", metrics.get("high_risk_gaps", 0))
col4.metric("Matched Controls", metrics.get("matched_controls", 0))

st.divider()

with st.expander("Input Document", expanded=True):
    input_path = INPUT_DIR / "regulation.txt"
    if input_path.exists():
        st.text_area("Regulatory Input", input_path.read_text(encoding="utf-8"), height=220)
    else:
        st.warning("No input/regulation.txt found.")

with st.expander("Context Packet"):
    st.json(context)

st.subheader("Extracted Changes")
if changes:
    st.dataframe(pd.DataFrame(changes), use_container_width=True)
else:
    st.info("No changes generated yet.")

st.subheader("Gap Analysis")
if gaps:
    st.dataframe(pd.DataFrame(gaps), use_container_width=True)
else:
    st.info("No gap analysis generated yet.")

st.subheader("Impact Assessment")
if impacts:
    st.dataframe(pd.DataFrame(impacts), use_container_width=True)
else:
    st.info("No impact assessment generated yet.")

st.subheader("Control Mapping")
if mappings:
    st.dataframe(pd.DataFrame(mappings), use_container_width=True)
else:
    st.info("No control mapping generated yet.")

st.subheader("Approval Packet")
st.json(approval_packet)

st.subheader("Remediation Plan")
st.markdown(load_markdown("remediation_plan.md"))

st.subheader("Exceptions")
st.markdown(load_markdown("exceptions.md"))

st.subheader("Audit Log")
st.markdown(load_markdown("audit_log.md"))
