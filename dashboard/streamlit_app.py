import json
from pathlib import Path

import pandas as pd
import streamlit as st

BASE_DIR  = Path(__file__).resolve().parents[1]
OUTPUT_DIR = BASE_DIR / "output"
INPUT_DIR  = BASE_DIR / "input"

st.set_page_config(page_title="IRCMS Dashboard", layout="wide")
st.title("IRCMS - Intelligent Regulatory Change Management System")
st.caption("6-Agent Compliance Pipeline Dashboard")


# ── Loaders ──────────────────────────────────────────────────────────────────

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


def as_list(raw, list_key: str) -> list:
    """Return the list payload from either a bare list or a {list_key: [...]} dict."""
    if isinstance(raw, list):
        return raw
    return raw.get(list_key, [])


# ── Flatten helpers ───────────────────────────────────────────────────────────

def flatten_gaps(gaps: list) -> pd.DataFrame:
    rows = []
    for g in gaps:
        rows.append({
            "gap_id":          g.get("gap_id", ""),
            "change_id":       g.get("change_id", ""),
            "policy_area":     g.get("policy_area", ""),
            "gap_status":      g.get("gap_status", ""),
            "severity":        g.get("severity", ""),
            "confidence":      g.get("confidence", ""),
            "gap_description": g.get("gap_description", ""),
            "current_policy":  (g.get("current_policy") or {}).get("text") or g.get("current_policy", ""),
            "required_change": (g.get("required_change") or {}).get("requirement_text") or g.get("required_policy", ""),
            "target_deadline": (g.get("remediation") or {}).get("target_deadline", ""),
            "owner":           (g.get("current_policy") or {}).get("owner") or g.get("owner", ""),
            "evidence_id":     (g.get("evidence") or {}).get("evidence_id") or g.get("evidence_id", ""),
            "human_review":    (g.get("human_oversight") or {}).get("review_required", ""),
            "analysis_source": (g.get("metadata") or {}).get("analysis_source", ""),
        })
    return pd.DataFrame(rows)


def flatten_impacts(impacts: list) -> pd.DataFrame:
    rows = []
    for a in impacts:
        procs = a.get("affected_processes", [])
        proc  = procs[0] if procs else {}
        rows.append({
            "impact_id":             a.get("impact_id", ""),
            "gap_id":                a.get("gap_id", ""),
            "policy_area":           a.get("policy_area", ""),
            "affected_process":      proc.get("process_name") or a.get("affected_process", ""),
            "affected_system":       proc.get("system")       or a.get("affected_system", ""),
            "business_unit":         proc.get("business_unit") or a.get("business_unit", ""),
            "system_impact_score":   a.get("system_impact_score", ""),
            "regulatory_risk_score": a.get("regulatory_risk_score", ""),
            "remediation_complexity":a.get("remediation_complexity", ""),
            "deadline_risk":         a.get("deadline_risk", ""),
            "headcount_affected":    a.get("headcount_affected", ""),
            "priority":              a.get("priority", ""),
            "escalation_required":   a.get("escalation_required", ""),
            "analysis_source":       (a.get("metadata") or {}).get("analysis_source", ""),
        })
    return pd.DataFrame(rows)


# ── Load all outputs ──────────────────────────────────────────────────────────

context         = load_json("context_packet.json", {})
changes         = load_json("change_register.json", [])
gaps_raw        = load_json("gap_analysis.json", [])
impacts_raw     = load_json("impact_assessment.json", [])
mappings        = load_json("control_mapping.json", [])
metrics         = load_json("metrics.json", {})
approval_packet = load_json("approval_packet.json", {})

gaps    = as_list(gaps_raw,    "gaps")
impacts = as_list(impacts_raw, "assessments")


# ── Top metrics ───────────────────────────────────────────────────────────────

col1, col2, col3, col4 = st.columns(4)
col1.metric("Total Changes",   metrics.get("total_changes", len(changes)))
col2.metric("Total Gaps",      metrics.get("total_gaps",    len(gaps)))
col3.metric("High Risk Gaps",  metrics.get("high_risk_gaps", 0))
col4.metric("Matched Controls",metrics.get("matched_controls", 0))

st.divider()

# ── Input document ────────────────────────────────────────────────────────────

with st.expander("Input Document", expanded=True):
    input_path = INPUT_DIR / "regulation.txt"
    if input_path.exists():
        st.text_area("Regulatory Input", input_path.read_text(encoding="utf-8"), height=220)
    else:
        st.warning("No input/regulation.txt found.")

with st.expander("Context Packet"):
    st.json(context)

# ── Agent outputs ─────────────────────────────────────────────────────────────

st.subheader("Extracted Changes (Agent B)")
if changes:
    st.dataframe(pd.DataFrame(changes), use_container_width=True)
else:
    st.info("No changes generated yet.")

st.subheader("Gap Analysis (Agent C)")
if gaps:
    st.dataframe(flatten_gaps(gaps), use_container_width=True)
    with st.expander("Raw JSON"):
        st.json(gaps_raw)
else:
    st.info("No gap analysis generated yet.")

st.subheader("Impact Assessment (Agent D)")
if impacts:
    st.dataframe(flatten_impacts(impacts), use_container_width=True)
    col_a, col_b = st.columns(2)
    with col_a:
        priority_data = impacts_raw.get("priority_summary", {}) if isinstance(impacts_raw, dict) else {}
        if priority_data:
            st.bar_chart(priority_data)
    with col_b:
        deadline_data = impacts_raw.get("deadline_risk_summary", {}) if isinstance(impacts_raw, dict) else {}
        if deadline_data:
            st.bar_chart(deadline_data)
    with st.expander("Raw JSON"):
        st.json(impacts_raw)
else:
    st.info("No impact assessment generated yet.")

st.subheader("Control Mapping (Agent E)")
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
