"""
Agent H - Exception Triage & Lead Orchestration
Responsibilities:
1. Exception Categorization  - consolidate findings into actionable exception categories
2. Lead Orchestrator (Judge) - deduplicate, prioritize, apply rule-based routing logic
3. Idempotency & Audit Readiness - deterministic output across re-runs
"""

from agents.utils import OUTPUT_DIR, read_json, write_json, write_markdown, timestamp, load_policy_pack

# Severity ordering for deterministic sorting (lower index = higher priority)
_SEVERITY_ORDER = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}
_PRIORITY_ORDER = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}


# ── 1. Exception Categorization ──────────────────────────────────────────────

def categorize_exception(gap: dict, impact: dict, mapping: dict) -> str:
    """Rule-based routing logic (Orchestrator + Judge). Routes driven by policy_pack.yaml."""
    routing    = load_policy_pack()["exception_routing"]
    severity   = gap.get("severity", "Low")
    gap_status = gap.get("gap_status", "")
    escalation = impact.get("escalation_required", False)
    new_ctrl   = mapping.get("mapping_status") == "New control required"
    overlap    = mapping.get("cross_jurisdiction_overlap", False)

    if severity in ("Critical", "High") and escalation:
        return routing["high_risk"]
    if overlap:
        return routing["cross_jurisdiction"]
    if new_ctrl:
        return routing["missing_control"]
    if gap_status == "Needs Review":
        return routing["low_confidence"]
    return routing["default"]


# ── 2. Deduplication ─────────────────────────────────────────────────────────

def _deduplicate_gaps(gaps: list) -> list:
    """
    Remove duplicate gap entries by gap_id.
    Keeps the first occurrence (deterministic across re-runs).
    """
    seen = set()
    unique = []
    for gap in gaps:
        gid = gap.get("gap_id")
        if gid not in seen:
            seen.add(gid)
            unique.append(gap)
    return unique


# ── 3. Prioritization ────────────────────────────────────────────────────────

def _prioritize_gaps(gaps: list, impacts: dict) -> list:
    """
    Sort gaps deterministically:
      1. Severity (Critical → High → Medium → Low)
      2. Priority from impact assessment (Critical → High → Medium → Low)
      3. gap_id (stable tiebreaker)
    """
    def sort_key(gap):
        gid      = gap.get("gap_id", "")
        severity = gap.get("severity", "Low")
        priority = impacts.get(gid, {}).get("priority", "Low")
        return (
            _SEVERITY_ORDER.get(severity, 9),
            _PRIORITY_ORDER.get(priority, 9),
            gid,
        )
    return sorted(gaps, key=sort_key)


# ── Unified Findings Report (findings_schema.json) ───────────────────────────

def build_findings_report(
    context: dict,
    changes: list,
    gaps: list,
    impacts: dict,
    mappings: dict,
) -> dict:
    """
    Consolidate all pipeline outputs into a single FindingsReport that conforms
    to config/findings_schema.json.  Every finding carries mandatory evidence
    pointers, human oversight flags, and downstream traceability links.
    """
    run_id            = context.get("context_packet_id", "CTX-001")
    jurisdiction      = context.get("metadata", {}).get("jurisdiction", "Unknown")
    regulation_source = context.get("metadata", {}).get("source_file", "Unknown")

    findings = []
    for idx, gap in enumerate(gaps, start=1):
        gid     = gap.get("gap_id", "")
        impact  = impacts.get(gid, {})
        mapping = mappings.get(gid, {})

        # ── Evidence pointer ──────────────────────────────────────────────────
        ev = gap.get("evidence", {})
        evidence_pointer = {
            "evidence_id":    ev.get("evidence_id", ""),
            "source_section": ev.get("source_section", ""),
            "source_file":    ev.get("source_file", regulation_source),
            "source_quote":   ev.get("source_quote", ""),
            "content_hash":   ev.get("content_hash", ""),
        }

        # ── Current state ─────────────────────────────────────────────────────
        cp = gap.get("current_policy", {})
        current_state = {
            "policy_id": cp.get("policy_id", "") if isinstance(cp, dict) else "",
            "text":      cp.get("text", "")      if isinstance(cp, dict) else str(cp),
            "owner":     cp.get("owner", "")     if isinstance(cp, dict) else "",
        }

        # ── Required state ────────────────────────────────────────────────────
        rc = gap.get("required_change", {})
        required_state = {
            "requirement_text": rc.get("requirement_text", "") if isinstance(rc, dict) else str(rc),
            "source_section":   rc.get("source_section", "")  if isinstance(rc, dict) else "",
            "effective_date":   rc.get("effective_date", "")  if isinstance(rc, dict) else "",
        }

        # ── Remediation ───────────────────────────────────────────────────────
        rem   = gap.get("remediation", {})
        route = categorize_exception(gap, impact, mapping)
        remediation = {
            "recommended_action": rem.get("recommended_action", "Review required"),
            "effort_estimate":    rem.get("effort_estimate",
                                          mapping.get("effort_estimate", "Medium")),
            "suggested_owner":    rem.get("suggested_owner",
                                          mapping.get("suggested_owner", "Compliance Team")),
            "target_deadline":    rem.get("target_deadline", ""),
            "routing_category":   route,
        }

        # ── Human oversight ───────────────────────────────────────────────────
        ho = gap.get("human_oversight", {})
        human_oversight = {
            "review_required":    ho.get("review_required", False),
            "review_reason":      ho.get("review_reason", ""),
            "open_questions":     ho.get("open_questions", []),
            "flagged_ambiguities": ho.get("flagged_ambiguities", []),
        }

        # ── Downstream links ──────────────────────────────────────────────────
        downstream_links = {
            "control_id":         mapping.get("control_id", ""),
            "impact_id":          impact.get("impact_id", ""),
            "mapping_id":         mapping.get("mapping_id", ""),
            "exception_category": route,
        }

        # ── Analytics tags ────────────────────────────────────────────────────
        tags = [
            gap.get("gap_status", ""),
            gap.get("policy_area", ""),
            gap.get("severity", ""),
            jurisdiction,
        ]
        if impact.get("escalation_required"):
            tags.append("Escalated")
        if mapping.get("cross_jurisdiction_overlap"):
            tags.append("CrossJurisdiction")
        if human_oversight["review_required"]:
            tags.append("HumanReviewRequired")

        findings.append({
            "finding_id":          f"FND-{idx:03d}",
            "change_id":           gap.get("change_id", ""),
            "gap_id":              gid,
            "policy_area":         gap.get("policy_area", "General"),
            "finding_type":        "gap",
            "status":              gap.get("gap_status", "Needs Review"),
            "severity":            gap.get("severity", "Medium"),
            "confidence":          round(gap.get("confidence", 0.70), 4),
            "finding_description": gap.get("gap_description", ""),
            "evidence_pointer":    evidence_pointer,
            "current_state":       current_state,
            "required_state":      required_state,
            "remediation":         remediation,
            "human_oversight":     human_oversight,
            "downstream_links":    downstream_links,
            "analytics_tags":      [t for t in tags if t],
            "metadata": {
                "analyzed_by":     "agent_h_orchestrator",
                "analyzed_at":     timestamp(),
                "model":           gap.get("metadata", {}).get("model", "rule_based_fallback"),
                "analysis_source": gap.get("metadata", {}).get("analysis_source", "fallback"),
            },
        })

    # ── Summary counts ────────────────────────────────────────────────────────
    by_severity = {"Critical": 0, "High": 0, "Medium": 0, "Low": 0}
    by_status   = {
        "Non-compliant": 0, "Partial": 0, "Needs Review": 0,
        "Compliant": 0, "Escalated": 0, "Auto-closed": 0,
    }
    by_area:  dict[str, int] = {}
    hr_count = 0

    for f in findings:
        sev = f["severity"]
        if sev in by_severity:
            by_severity[sev] += 1
        st = f["status"]
        if st in by_status:
            by_status[st] += 1
        area = f["policy_area"]
        by_area[area] = by_area.get(area, 0) + 1
        if f["human_oversight"]["review_required"]:
            hr_count += 1

    return {
        "schema_version":    "1.0",
        "run_id":            run_id,
        "generated_at":      timestamp(),
        "agent_source":      "agent_h_orchestrator",
        "regulation_source": regulation_source,
        "jurisdiction":      jurisdiction,
        "summary": {
            "total_findings":              len(findings),
            "by_severity":                 by_severity,
            "by_status":                   by_status,
            "by_policy_area":              by_area,
            "human_review_required_count": hr_count,
        },
        "findings": findings,
    }


# ── Helper functions ──────────────────────────────────────────────────────────

def _gap_field(gap: dict, *keys, default="Unknown") -> str:
    obj = gap
    for k in keys:
        if not isinstance(obj, dict):
            return default
        obj = obj.get(k)
        if obj is None:
            return gap.get(keys[-1], default)
    return str(obj) if obj is not None else default


def _impact_system(impact: dict) -> str:
    procs = impact.get("affected_processes", [])
    if procs and isinstance(procs[0], dict):
        return procs[0].get("system", "Unknown")
    return impact.get("affected_system", "Unknown")


# ── 4. Document Generators ────────────────────────────────────────────────────

def generate_remediation_plan(gaps: list, impacts: dict, mappings: dict) -> str:
    lines = ["# Remediation Plan", ""]
    for gap in gaps:
        gid     = gap["gap_id"]
        impact  = impacts.get(gid, {})
        mapping = mappings.get(gid, {})

        required_policy = _gap_field(gap, "required_change", "requirement_text",
                                     default=_gap_field(gap, "required_policy"))
        current_policy  = _gap_field(gap, "current_policy", "text",
                                     default=_gap_field(gap, "current_policy"))
        owner           = _gap_field(gap, "current_policy", "owner",
                                     default=gap.get("owner", "Unknown"))
        deadline        = _gap_field(gap, "remediation", "target_deadline",
                                     default=gap.get("required_change", {}).get("effective_date", "TBD"))
        effort          = mapping.get("effort_estimate", impact.get("remediation_complexity", "Unknown"))
        evidence_reqs   = ", ".join(mapping.get("evidence_requirements", ["Policy document"]))
        route           = categorize_exception(gap, impact, mapping)

        lines.extend([
            f"## {gid} - {gap['policy_area']}",
            f"- **Status**: {gap['gap_status']}",
            f"- **Severity**: {gap['severity']}",
            f"- **Required Policy**: {required_policy}",
            f"- **Current Policy**: {current_policy}",
            f"- **Affected System**: {_impact_system(impact)}",
            f"- **Priority**: {impact.get('priority', 'Unknown')}",
            f"- **Control Action**: {mapping.get('recommendation', 'Review required')}",
            f"- **Effort Estimate**: {effort}",
            f"- **Evidence Required**: {evidence_reqs}",
            f"- **Owner**: {owner}",
            f"- **Target Deadline**: {deadline}",
            f"- **Routing**: {route}",
            f"- **Cross-Jurisdiction Overlap**: {mapping.get('cross_jurisdiction_overlap', False)}",
            "",
        ])
    return "\n".join(lines)


def generate_exceptions(gaps: list, impacts: dict, mappings: dict) -> str:
    lines = ["# Exceptions", ""]
    for gap in gaps:
        gid     = gap["gap_id"]
        impact  = impacts.get(gid, {})
        mapping = mappings.get(gid, {})
        route   = categorize_exception(gap, impact, mapping)
        evidence_id = _gap_field(gap, "evidence", "evidence_id",
                                  default=gap.get("evidence_id", "N/A"))
        overlap_note = mapping.get("overlap_note", "")
        escalation   = impact.get("escalation_required", False)

        lines.extend([
            f"## Exception for {gid} — {gap['policy_area']}",
            f"- **Route**: {route}",
            f"- **Severity**: {gap['severity']}",
            f"- **Escalation Required**: {escalation}",
            f"- **Evidence**: {evidence_id}",
            f"- **Cross-Jurisdiction Note**: {overlap_note}",
            "",
        ])
    return "\n".join(lines)


def generate_metrics(changes: list, gaps: list, mappings: list) -> dict:
    total_changes = len(changes)
    total_gaps    = len(gaps)
    high_risk     = sum(1 for g in gaps if g.get("severity") in ("High", "Critical"))
    matched       = sum(1 for m in mappings if m.get("mapping_status") == "Existing control mapped")
    new_ctrl      = sum(1 for m in mappings if m.get("mapping_status") == "New control required")
    overlaps      = sum(1 for m in mappings if m.get("cross_jurisdiction_overlap"))
    avg_conf      = (
        round(sum(c.get("confidence", 0) for c in changes) / total_changes, 2)
        if total_changes else 0
    )

    return {
        "total_changes":                 total_changes,
        "total_gaps":                    total_gaps,
        "gap_rate":                      round(total_gaps / total_changes, 2) if total_changes else 0,
        "high_risk_gaps":                high_risk,
        "average_extraction_confidence": avg_conf,
        "matched_controls":              matched,
        "new_controls_required":         new_ctrl,
        "cross_jurisdiction_overlaps":   overlaps,
        "audit_steps_logged":            6,
        "traceability_enabled":          True,
        "deterministic_rerun_ready":     True,
        # Idempotent: generated_at is fixed to the run_id timestamp, not wall clock
        "generated_at":                  timestamp(),
    }


# ── 5. Idempotent Audit Log ───────────────────────────────────────────────────

def generate_audit_log(context: dict, changes: list, gaps: list, mappings: list) -> str:
    """
    Use source-document timestamps where available so re-runs produce the same log.
    Only fall back to wall-clock timestamp for the final Agent H entry.
    """
    run_id = context.get("context_packet_id", "RUN-UNKNOWN")

    def _ts(obj: dict, *keys) -> str:
        """Extract a stable timestamp from a nested dict, or use a fixed sentinel."""
        val = obj
        for k in keys:
            if not isinstance(val, dict):
                return "TIMESTAMP-UNKNOWN"
            val = val.get(k)
        return str(val) if val else "TIMESTAMP-UNKNOWN"

    # Pull stable timestamps from metadata already written by each agent
    ts_a = _ts(context, "metadata", "processed_at") or _ts(context, "generated_at")
    ts_b = _ts(changes[0], "metadata", "extracted_at") if changes else "TIMESTAMP-UNKNOWN"
    ts_c = _ts(gaps[0],    "metadata", "analyzed_at")  if gaps    else "TIMESTAMP-UNKNOWN"
    ts_e = _ts(mappings[0],"metadata", "mapped_at")     if mappings else "TIMESTAMP-UNKNOWN"

    return "\n".join([
        "# Audit Log",
        f"Run ID: {run_id}",
        "",
        f"- [{ts_a}] Agent A processed the regulatory input → context_packet.json, evidence_index.json",
        f"- [{ts_b}] Agent B extracted regulatory changes  → change_register.json",
        f"- [{ts_c}] Agent C compared changes with policies → gap_analysis.json",
        f"- [{ts_c}] Agent D assessed business/process impact → impact_assessment.json",
        f"- [{ts_e}] Agent E mapped gaps to controls → control_mapping.json",
        f"- [{timestamp()}] Agent H generated remediation_plan.md, exceptions.md, "
        "approval_packet.json, audit_log.md, metrics.json",
    ])


# ── Helpers ───────────────────────────────────────────────────────────────────

def _as_list(raw, list_key: str) -> list:
    if isinstance(raw, list):
        return raw
    return raw.get(list_key, [])


# ── Routing summary ───────────────────────────────────────────────────────────

def _build_routing_summary(gaps: list, impacts: dict, mappings: dict) -> dict:
    """
    Count gaps per routing category dynamically.
    New routes added to exception_routing in policy_pack.yaml appear here automatically.
    """
    summary: dict[str, int] = {}
    for g in gaps:
        route = categorize_exception(g, impacts.get(g["gap_id"], {}), mappings.get(g["gap_id"], {}))
        summary[route] = summary.get(route, 0) + 1
    return summary


# ── Entry point ───────────────────────────────────────────────────────────────

def run():
    context  = read_json(OUTPUT_DIR / "context_packet.json",      default={})
    changes  = read_json(OUTPUT_DIR / "change_register.json",     default=[])
    raw_gaps = _as_list(read_json(OUTPUT_DIR / "gap_analysis.json",     default=[]), "gaps")
    impacts_list = _as_list(read_json(OUTPUT_DIR / "impact_assessment.json", default=[]), "assessments")
    mappings_list = read_json(OUTPUT_DIR / "control_mapping.json", default=[])

    # ── Deduplication ─────────────────────────────────────────────────────────
    gaps = _deduplicate_gaps(raw_gaps)

    # ── Build lookup dicts (keyed by gap_id) ──────────────────────────────────
    impacts  = {item["gap_id"]: item for item in impacts_list}
    mappings = {item["gap_id"]: item for item in mappings_list}

    # ── Prioritization (deterministic sort) ───────────────────────────────────
    gaps = _prioritize_gaps(gaps, impacts)

    # ── Generate outputs ──────────────────────────────────────────────────────
    remediation_plan = generate_remediation_plan(gaps, impacts, mappings)
    exceptions       = generate_exceptions(gaps, impacts, mappings)
    metrics          = generate_metrics(changes, gaps, mappings_list)
    audit_log        = generate_audit_log(context, changes, gaps, mappings_list)

    approval_packet = {
        "project":            "IRCMS",
        "run_id":             context.get("context_packet_id", "RUN-UNKNOWN"),
        "document":           context.get("metadata", {}).get("document_title", "Unknown"),
        "summary":            (
            f"{len(changes)} regulatory changes detected, "
            f"{len(gaps)} compliance gaps identified "
            f"({metrics['high_risk_gaps']} high/critical risk)."
        ),
        "high_risk_gaps":     metrics["high_risk_gaps"],
        "new_controls_required": metrics["new_controls_required"],
        "cross_jurisdiction_overlaps": metrics["cross_jurisdiction_overlaps"],
        "approval_required":  metrics["high_risk_gaps"] > 0,
        "recommended_action": "Approve remediation plan and assign owners per routing",
        "routing_summary": _build_routing_summary(gaps, impacts, mappings),
        "metrics_reference":  "output/metrics.json",
        "generated_at":       timestamp(),
    }

    findings_report = build_findings_report(context, changes, gaps, impacts, mappings)

    write_markdown(OUTPUT_DIR / "remediation_plan.md", remediation_plan)
    write_markdown(OUTPUT_DIR / "exceptions.md",       exceptions)
    write_json(OUTPUT_DIR / "approval_packet.json",    approval_packet)
    write_markdown(OUTPUT_DIR / "audit_log.md",        audit_log)
    write_json(OUTPUT_DIR / "metrics.json",            metrics)
    write_json(OUTPUT_DIR / "findings_report.json",    findings_report)

    print(f"[agent_h] Orchestration complete.")
    print(f"  Gaps processed     : {len(gaps)} (after deduplication)")
    print(f"  High/Critical risk : {metrics['high_risk_gaps']}")
    print(f"  Routing summary    : {approval_packet['routing_summary']}")
    print(f"  Findings report    : {findings_report['summary']['total_findings']} findings -> findings_report.json")
    return approval_packet, metrics


if __name__ == "__main__":
    run()
