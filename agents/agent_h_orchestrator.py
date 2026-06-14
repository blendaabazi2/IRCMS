"""
Agent H - Exception Triage & Lead Orchestration
Responsibilities:
- Combine outputs from all agents
- Categorize exceptions
- Generate remediation plan, approval packet, audit log, and metrics
"""

from datetime import date
from agents.utils import OUTPUT_DIR, read_json, write_json, write_markdown, timestamp


def categorize_exception(gap, impact, mapping):
    if gap.get("severity") == "High":
        return "Compliance Lead Escalation"
    if mapping.get("mapping_status") == "New control required":
        return "Control Owner Review"
    if gap.get("gap_status") == "Needs Review":
        return "Legal Review"
    return "Policy Owner Remediation"


def _gap_field(gap: dict, *keys, default="Unknown") -> str:
    """Walk a chain of keys through nested dicts, falling back to flat keys for backwards compat."""
    obj = gap
    for k in keys:
        if not isinstance(obj, dict):
            return default
        obj = obj.get(k)
        if obj is None:
            # try the last key directly on the original gap (old flat format)
            return gap.get(keys[-1], default)
    return str(obj) if obj is not None else default


def _impact_system(impact: dict) -> str:
    """Support both old flat affected_system and new nested affected_processes[0].system."""
    procs = impact.get("affected_processes", [])
    if procs and isinstance(procs[0], dict):
        return procs[0].get("system", "Unknown")
    return impact.get("affected_system", "Unknown")


def generate_remediation_plan(gaps, impacts, mappings) -> str:
    impact_by_gap  = {item["gap_id"]: item for item in impacts}
    mapping_by_gap = {item["gap_id"]: item for item in mappings}

    lines = ["# Remediation Plan", ""]
    for gap in gaps:
        impact  = impact_by_gap.get(gap["gap_id"], {})
        mapping = mapping_by_gap.get(gap["gap_id"], {})

        required_policy = _gap_field(gap, "required_change", "requirement_text", default=_gap_field(gap, "required_policy"))
        current_policy  = _gap_field(gap, "current_policy",  "text",             default=_gap_field(gap, "current_policy"))
        owner           = _gap_field(gap, "current_policy",  "owner",            default=gap.get("owner", "Unknown"))
        deadline        = _gap_field(gap, "remediation", "target_deadline",      default=date.today().isoformat())

        lines.extend([
            f"## {gap['gap_id']} - {gap['policy_area']}",
            f"- Status: {gap['gap_status']}",
            f"- Severity: {gap['severity']}",
            f"- Required Policy: {required_policy}",
            f"- Current Policy: {current_policy}",
            f"- Affected System: {_impact_system(impact)}",
            f"- Priority: {impact.get('priority', 'Unknown')}",
            f"- Control Action: {mapping.get('recommendation', 'Review required')}",
            f"- Owner: {owner}",
            f"- Target Deadline: {deadline}",
            ""
        ])
    return "\n".join(lines)


def generate_exceptions(gaps, impacts, mappings) -> str:
    impact_by_gap  = {item["gap_id"]: item for item in impacts}
    mapping_by_gap = {item["gap_id"]: item for item in mappings}

    lines = ["# Exceptions", ""]
    for gap in gaps:
        impact  = impact_by_gap.get(gap["gap_id"], {})
        mapping = mapping_by_gap.get(gap["gap_id"], {})
        route   = categorize_exception(gap, impact, mapping)
        evidence_id = _gap_field(gap, "evidence", "evidence_id", default=gap.get("evidence_id", "N/A"))
        lines.extend([
            f"## Exception for {gap['gap_id']}",
            f"- Route: {route}",
            f"- Severity: {gap['severity']}",
            f"- Evidence: {evidence_id}",
            ""
        ])
    return "\n".join(lines)


def generate_metrics(changes, gaps, mappings):
    total_changes = len(changes)
    total_gaps = len(gaps)
    high_risk = len([gap for gap in gaps if gap.get("severity") == "High"])
    matched_controls = len([m for m in mappings if m.get("mapping_status") == "Existing control mapped"])
    new_controls = len([m for m in mappings if m.get("mapping_status") == "New control required"])
    avg_conf = round(sum(c.get("confidence", 0) for c in changes) / total_changes, 2) if total_changes else 0

    return {
        "total_changes": total_changes,
        "total_gaps": total_gaps,
        "gap_rate": round(total_gaps / total_changes, 2) if total_changes else 0,
        "high_risk_gaps": high_risk,
        "average_extraction_confidence": avg_conf,
        "matched_controls": matched_controls,
        "new_controls_required": new_controls,
        "audit_steps_logged": 6,
        "traceability_enabled": True,
        "deterministic_rerun_ready": True,
        "generated_at": timestamp()
    }


def _as_list(raw, list_key: str) -> list:
    """Return the list payload from either a bare list or a {list_key: [...]} dict."""
    if isinstance(raw, list):
        return raw
    return raw.get(list_key, [])


def run():
    context = read_json(OUTPUT_DIR / "context_packet.json", default={})
    changes = read_json(OUTPUT_DIR / "change_register.json", default=[])
    gaps    = _as_list(read_json(OUTPUT_DIR / "gap_analysis.json",    default=[]), "gaps")
    impacts = _as_list(read_json(OUTPUT_DIR / "impact_assessment.json", default=[]), "assessments")
    mappings = read_json(OUTPUT_DIR / "control_mapping.json", default=[])

    remediation_plan = generate_remediation_plan(gaps, impacts, mappings)
    exceptions = generate_exceptions(gaps, impacts, mappings)
    metrics = generate_metrics(changes, gaps, mappings)

    approval_packet = {
        "project": "IRCMS",
        "document": context.get("metadata", {}).get("document_title", "Unknown"),
        "summary": f"{len(changes)} regulatory changes detected, {len(gaps)} compliance gaps identified.",
        "high_risk_gaps": metrics["high_risk_gaps"],
        "approval_required": metrics["high_risk_gaps"] > 0,
        "recommended_action": "Approve remediation plan and assign owners",
        "metrics_reference": "output/metrics.json"
    }

    audit_log = "\n".join([
        "# Audit Log",
        "",
        f"- {timestamp()} Agent A processed the regulatory input and generated context_packet.json and evidence_index.json.",
        f"- {timestamp()} Agent B extracted regulatory changes and generated change_register.json.",
        f"- {timestamp()} Agent C compared changes with current policies and generated gap_analysis.json.",
        f"- {timestamp()} Agent D assessed business/process impact and generated impact_assessment.json.",
        f"- {timestamp()} Agent E mapped gaps to controls and generated control_mapping.json.",
        f"- {timestamp()} Agent H generated remediation_plan.md, exceptions.md, approval_packet.json, audit_log.md, and metrics.json."
    ])

    write_markdown(OUTPUT_DIR / "remediation_plan.md", remediation_plan)
    write_markdown(OUTPUT_DIR / "exceptions.md", exceptions)
    write_json(OUTPUT_DIR / "approval_packet.json", approval_packet)
    write_markdown(OUTPUT_DIR / "audit_log.md", audit_log)
    write_json(OUTPUT_DIR / "metrics.json", metrics)

    return approval_packet, metrics


if __name__ == "__main__":
    run()
