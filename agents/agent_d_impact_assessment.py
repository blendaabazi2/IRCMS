"""
Agent D - Impact Assessment
Responsibilities:
- Read gap_analysis.json (Agent C output) and process/control inventories
- Score each gap by system impact (1-5), regulatory risk (0-100), deadline risk, complexity
- Map impacted processes, systems, business units, and headcount
- Write impact_assessment.json and impact_matrix.csv
"""

import csv
import json
from datetime import datetime, timezone
from typing import Optional

import anthropic
import pandas as pd
from pydantic import BaseModel, Field

from agents.utils import (
    INPUT_DIR, OUTPUT_DIR, read_json, write_json, make_id, timestamp
)


# ── Pydantic Schema ──────────────────────────────────────────────────────────

class RemediationComplexity(str):
    """Low | Medium | High"""


class DeadlineRisk(str):
    """Low | Medium | High | Critical"""


class Priority(str):
    """Low | Medium | High | Critical"""


class AffectedProcess(BaseModel):
    process_id: str
    process_name: str
    system: str
    business_unit: str
    owner: str


class ImpactAssessment(BaseModel):
    impact_id: str
    gap_id: str
    change_id: str
    policy_area: str

    # Core scores
    system_impact_score: int = Field(
        ..., ge=1, le=5,
        description="1=negligible, 2=minor, 3=moderate, 4=significant, 5=critical infrastructure"
    )
    regulatory_risk_score: int = Field(
        ..., ge=0, le=100,
        description="Composite regulatory risk if gap is not closed before effective_date"
    )
    remediation_complexity: str = Field(..., description="Low | Medium | High")
    deadline_risk: str = Field(..., description="Low | Medium | High | Critical")

    # Organisational impact
    affected_processes: list[AffectedProcess]
    business_units_affected: list[str]
    headcount_affected: int = Field(..., ge=0, description="Estimated staff count impacted")
    dependency_systems: list[str] = Field(
        default_factory=list,
        description="Other systems that depend on or integrate with the impacted system"
    )

    # Derived priority
    priority: str = Field(..., description="Low | Medium | High | Critical")

    # Narrative
    impact_summary: str

    # Oversight
    human_review_required: bool
    escalation_required: bool = Field(
        ..., description="True when deadline_risk is Critical or High and severity is High"
    )

    # Metadata
    metadata: dict = Field(default_factory=dict)


class ImpactReport(BaseModel):
    run_id: str
    generated_at: str
    regulation_source: str
    jurisdiction: str
    total_assessments: int
    priority_summary: dict
    deadline_risk_summary: dict
    assessments: list[ImpactAssessment]


# ── Claude prompt ────────────────────────────────────────────────────────────

CLAUDE_MODEL = "claude-sonnet-4-6"

_PROMPT_TEMPLATE = """\
You are a senior regulatory impact analyst.

## Gap Under Assessment
Gap ID        : {gap_id}
Change ID     : {change_id}
Policy Area   : {policy_area}
Gap Status    : {gap_status}
Severity      : {severity}
Gap Description: {gap_description}

## Regulatory Requirement
Source Section : {source_section}
Effective Date : {effective_date}
Days to Deadline: {days_to_deadline}
Requirement    : {requirement_text}

## Affected Process & System
Process ID    : {process_id}
Process Name  : {process_name}
System        : {system}
Primary Business Unit: {business_unit}
Process Owner : {owner}

## Organisation Scope
All Business Units in scope: {all_business_units}
Jurisdiction: {jurisdiction}

## Your Task
Assess the operational and regulatory impact of this compliance gap.
Return ONLY a JSON object with exactly these fields — no markdown, no extra text:

{{
  "system_impact_score": <integer 1-5>,
  "regulatory_risk_score": <integer 0-100>,
  "remediation_complexity": "<Low|Medium|High>",
  "deadline_risk": "<Low|Medium|High|Critical>",
  "business_units_affected": ["<unit1>", ...],
  "headcount_affected": <integer>,
  "dependency_systems": ["<system name>", ...],
  "impact_summary": "<2-3 sentences describing the organisational impact>",
  "human_review_required": <true|false>,
  "escalation_required": <true|false>
}}

Scoring guide:
- system_impact_score: 1=config change only, 2=single system update, 3=multiple system updates,
  4=cross-department process change, 5=core infrastructure or customer-facing change
- regulatory_risk_score: 0=no risk, 100=immediate enforcement action / licence risk
- deadline_risk: Critical=<30 days, High=30-60 days, Medium=60-90 days, Low=>90 days
- headcount_affected: total staff who must change workflows or be retrained
- escalation_required: true when deadline_risk is Critical OR (High AND system_impact_score >= 4)
"""


# ── Fallback logic ───────────────────────────────────────────────────────────

def _days_to_deadline(effective_date: str) -> int:
    try:
        target = datetime.fromisoformat(effective_date).replace(tzinfo=timezone.utc)
        now = datetime.now(tz=timezone.utc)
        return max(0, (target - now).days)
    except ValueError:
        return 90


def _priority_from_scores(reg_risk: int, deadline_risk: str) -> str:
    if reg_risk >= 85 or deadline_risk == "Critical":
        return "Critical"
    if reg_risk >= 65 or deadline_risk == "High":
        return "High"
    if reg_risk >= 45:
        return "Medium"
    return "Low"


def _rule_based_impact(gap: dict, process: Optional[dict], days: int) -> dict:
    """Deterministic fallback used when Claude API is unavailable."""
    severity   = gap.get("severity", "Medium")
    gap_status = gap.get("gap_status", "Needs Review")
    effort     = gap.get("remediation", {}).get("effort_estimate", "Medium")

    # System impact score
    score_map = {"Critical": 5, "High": 4, "Medium": 3, "Low": 2}
    sys_score = score_map.get(severity, 3)
    if gap_status == "Partial":
        sys_score = max(1, sys_score - 1)

    # Regulatory risk score
    reg_risk = {"Critical": 90, "High": 75, "Medium": 50, "Low": 25}.get(severity, 50)

    # Deadline risk
    if days < 30:
        deadline_risk = "Critical"
    elif days < 60:
        deadline_risk = "High"
    elif days < 90:
        deadline_risk = "Medium"
    else:
        deadline_risk = "Low"

    # Business units and headcount
    bu = process.get("business_unit", "Unknown") if process else "Unknown"
    headcount = {"High": 25, "Medium": 12, "Low": 5}.get(severity, 10)

    dep_sys = [process.get("system", "Unknown")] if process else []

    priority = _priority_from_scores(reg_risk, deadline_risk)

    area = gap.get("policy_area", "Unknown")
    impact_summary = (
        f"The {area} gap ({gap['gap_id']}) is assessed as {severity} severity with a "
        f"system impact score of {sys_score}/5. "
        f"Regulatory risk is {reg_risk}/100 with {days} days remaining to the compliance deadline. "
        f"Estimated {headcount} staff members will need workflow or system changes."
    )

    return {
        "system_impact_score": sys_score,
        "regulatory_risk_score": reg_risk,
        "remediation_complexity": effort,
        "deadline_risk": deadline_risk,
        "business_units_affected": [bu],
        "headcount_affected": headcount,
        "dependency_systems": dep_sys,
        "impact_summary": impact_summary,
        "human_review_required": True,
        "escalation_required": deadline_risk in ("Critical", "High") and sys_score >= 4,
        "_source": "fallback",
    }


# ── Claude call ──────────────────────────────────────────────────────────────

def _call_claude(
    client: anthropic.Anthropic,
    gap: dict,
    process: Optional[dict],
    days: int,
    jurisdiction_scope: dict,
) -> dict:
    proc = process or {}
    all_bus = ", ".join(jurisdiction_scope.get("business_units", []))

    prompt = _PROMPT_TEMPLATE.format(
        gap_id=gap["gap_id"],
        change_id=gap["change_id"],
        policy_area=gap.get("policy_area", "General"),
        gap_status=gap.get("gap_status", ""),
        severity=gap.get("severity", ""),
        gap_description=gap.get("gap_description", ""),
        source_section=gap.get("required_change", {}).get("source_section", ""),
        effective_date=gap.get("required_change", {}).get("effective_date", ""),
        days_to_deadline=days,
        requirement_text=gap.get("required_change", {}).get("requirement_text", "")[:300],
        process_id=proc.get("process_id", "N/A"),
        process_name=proc.get("process_name", "Unknown"),
        system=proc.get("system", "Unknown"),
        business_unit=proc.get("business_unit", "Unknown"),
        owner=proc.get("owner", "Unknown"),
        all_business_units=all_bus,
        jurisdiction=jurisdiction_scope.get("jurisdictions", ["EU"])[0],
    )

    try:
        message = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        result = json.loads(message.content[0].text.strip())
        result["_source"] = "claude"
        return result
    except (
        anthropic.BadRequestError, anthropic.AuthenticationError,
        anthropic.PermissionDeniedError, anthropic.APIConnectionError,
        anthropic.RateLimitError,
    ) as exc:
        print(f"[agent_d] Claude unavailable ({type(exc).__name__}). Using rule-based fallback.")
        return _rule_based_impact(gap, process, days)


# ── Process matching ─────────────────────────────────────────────────────────

_AREA_KEYWORDS = {
    "KYC":        ["kyc", "customer due diligence", "customer"],
    "Monitoring":  ["transaction", "monitoring", "suspicious"],
    "Audit":       ["audit", "evidence", "retention", "document"],
}


def _match_process(policy_area: str, process_df: pd.DataFrame) -> Optional[dict]:
    keywords = _AREA_KEYWORDS.get(policy_area, [policy_area.lower()])
    for kw in keywords:
        mask = process_df["process_name"].str.lower().str.contains(kw, na=False)
        if mask.any():
            return process_df[mask].iloc[0].to_dict()
    return None


# ── CSV writer ───────────────────────────────────────────────────────────────

_CSV_FIELDS = [
    "impact_id", "gap_id", "change_id", "policy_area",
    "affected_process", "affected_system", "business_units_affected",
    "system_impact_score", "regulatory_risk_score",
    "remediation_complexity", "deadline_risk",
    "headcount_affected", "priority", "escalation_required",
    "analysis_source",
]


def _write_csv(assessments: list[ImpactAssessment]) -> None:
    path = OUTPUT_DIR / "impact_matrix.csv"
    rows = []
    for a in assessments:
        primary_proc = a.affected_processes[0] if a.affected_processes else None
        rows.append({
            "impact_id":               a.impact_id,
            "gap_id":                  a.gap_id,
            "change_id":               a.change_id,
            "policy_area":             a.policy_area,
            "affected_process":        primary_proc.process_name if primary_proc else "Unknown",
            "affected_system":         primary_proc.system if primary_proc else "Unknown",
            "business_units_affected": "; ".join(a.business_units_affected),
            "system_impact_score":     a.system_impact_score,
            "regulatory_risk_score":   a.regulatory_risk_score,
            "remediation_complexity":  a.remediation_complexity,
            "deadline_risk":           a.deadline_risk,
            "headcount_affected":      a.headcount_affected,
            "priority":                a.priority,
            "escalation_required":     a.escalation_required,
            "analysis_source":         a.metadata.get("analysis_source", "unknown"),
        })

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


# ── Entry point ──────────────────────────────────────────────────────────────

def run() -> ImpactReport:
    client = anthropic.Anthropic()

    # --- Load inputs ---
    gap_report        = read_json(OUTPUT_DIR / "gap_analysis.json", default={})
    process_df        = pd.read_csv(INPUT_DIR / "process_map.csv")
    jurisdiction_scope = read_json(INPUT_DIR / "jurisdiction_scope.json", default={})

    # Agent C writes {"run_id": ..., "gaps": [...]} — handle both old list and new dict format
    if isinstance(gap_report, list):
        gaps   = gap_report
        run_id = make_id("RUN", 1)
        reg_source = "regulation.txt"
        jurisdiction = "Unknown"
    else:
        gaps         = gap_report.get("gaps", [])
        run_id       = gap_report.get("run_id", make_id("RUN", 1))
        reg_source   = gap_report.get("regulation_source", "regulation.txt")
        jurisdiction  = gap_report.get("jurisdiction", "Unknown")

    priority_counts      = {"Critical": 0, "High": 0, "Medium": 0, "Low": 0}
    deadline_risk_counts = {"Critical": 0, "High": 0, "Medium": 0, "Low": 0}
    assessments: list[ImpactAssessment] = []

    for idx, gap in enumerate(gaps, start=1):
        policy_area    = gap.get("policy_area", "General")
        effective_date = gap.get("required_change", {}).get("effective_date", "2099-01-01")
        days           = _days_to_deadline(effective_date)
        proc           = _match_process(policy_area, process_df)

        result = _call_claude(client, gap, proc, days, jurisdiction_scope)

        priority = _priority_from_scores(
            result["regulatory_risk_score"],
            result["deadline_risk"],
        )

        affected_procs = []
        if proc:
            affected_procs.append(AffectedProcess(
                process_id=proc.get("process_id", "N/A"),
                process_name=proc.get("process_name", "Unknown"),
                system=proc.get("system", "Unknown"),
                business_unit=proc.get("business_unit", "Unknown"),
                owner=proc.get("owner", "Unknown"),
            ))

        assessment = ImpactAssessment(
            impact_id=make_id("IMP", idx),
            gap_id=gap["gap_id"],
            change_id=gap["change_id"],
            policy_area=policy_area,
            system_impact_score=int(result["system_impact_score"]),
            regulatory_risk_score=int(result["regulatory_risk_score"]),
            remediation_complexity=result["remediation_complexity"],
            deadline_risk=result["deadline_risk"],
            affected_processes=affected_procs,
            business_units_affected=result.get("business_units_affected", []),
            headcount_affected=int(result.get("headcount_affected", 0)),
            dependency_systems=result.get("dependency_systems", []),
            priority=priority,
            impact_summary=result.get("impact_summary", ""),
            human_review_required=bool(result.get("human_review_required", True)),
            escalation_required=bool(result.get("escalation_required", False)),
            metadata={
                "analyzed_by":     "agent_d_impact_assessment",
                "analyzed_at":     timestamp(),
                "model":           CLAUDE_MODEL if result.get("_source") == "claude" else "rule_based_fallback",
                "analysis_source": result.get("_source", "unknown"),
                "days_to_deadline": days,
            },
        )

        priority_counts[priority] += 1
        deadline_risk_counts[result["deadline_risk"]] += 1
        assessments.append(assessment)

    report = ImpactReport(
        run_id=run_id,
        generated_at=timestamp(),
        regulation_source=reg_source,
        jurisdiction=jurisdiction,
        total_assessments=len(assessments),
        priority_summary=priority_counts,
        deadline_risk_summary=deadline_risk_counts,
        assessments=assessments,
    )

    write_json(OUTPUT_DIR / "impact_assessment.json", report.model_dump())
    _write_csv(assessments)
    return report


if __name__ == "__main__":
    report = run()
    print(f"\n[agent_d] Impact Assessment complete — {report.total_assessments} gaps assessed.")
    print(f"  Priority summary  : {report.priority_summary}")
    print(f"  Deadline risk     : {report.deadline_risk_summary}")
    print(f"  Outputs written   : output/impact_assessment.json, output/impact_matrix.csv")
