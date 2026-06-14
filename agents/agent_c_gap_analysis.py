"""
Agent C - Gap Analysis
Responsibilities:
- Compare extracted regulatory changes against current internal policies using Claude
- Identify compliance gaps with semantic understanding (not just keyword matching)
- Score severity and confidence, flag ambiguities for human review
- Generate gap_analysis.json with full traceable evidence and human oversight fields
"""

import json
import pandas as pd
from datetime import datetime, timedelta
from typing import Optional
from enum import Enum

from pydantic import BaseModel, Field

import anthropic
from agents.utils import (
    INPUT_DIR, OUTPUT_DIR, read_json, write_json, make_id, timestamp
)


# ── Pydantic Schema ──────────────────────────────────────────────────────────

class GapStatus(str, Enum):
    NON_COMPLIANT = "Non-compliant"
    PARTIAL       = "Partial"
    NEEDS_REVIEW  = "Needs Review"
    COMPLIANT     = "Compliant"


class Severity(str, Enum):
    CRITICAL = "Critical"
    HIGH     = "High"
    MEDIUM   = "Medium"
    LOW      = "Low"


class EffortEstimate(str, Enum):
    LOW    = "Low"
    MEDIUM = "Medium"
    HIGH   = "High"


class EvidencePointer(BaseModel):
    """
    Mandatory evidence pointer — every gap must trace back to a source document.
    Auditors use source_quote to verify the conclusion without re-reading the full doc.
    """
    evidence_id:    str
    source_section: str
    source_file:    str
    source_quote:   str = Field(..., description="Verbatim excerpt from the regulation")
    content_hash:   Optional[str] = None


class CurrentPolicyRef(BaseModel):
    policy_id:  str
    text:       str
    owner:      str
    jurisdiction: str


class RequiredChange(BaseModel):
    requirement_text: str
    source_section:   str
    effective_date:   str
    jurisdiction:     str


class RemediationPlan(BaseModel):
    recommended_action: str
    effort_estimate:    EffortEstimate
    suggested_owner:    str
    target_deadline:    str = Field(..., description="ISO date; 30 days before effective_date")


class HumanOversight(BaseModel):
    """
    Promotes human review wherever automation lacks full certainty.
    open_questions are sent to legal/compliance SMEs before remediation starts.
    """
    review_required:     bool
    review_reason:       str = ""
    open_questions:      list[str] = Field(default_factory=list)
    flagged_ambiguities: list[str] = Field(default_factory=list)


class GapFinding(BaseModel):
    gap_id:          str
    change_id:       str
    policy_area:     str
    gap_status:      GapStatus
    severity:        Severity
    confidence:      float = Field(..., ge=0.0, le=1.0)
    gap_description: str
    current_policy:  CurrentPolicyRef
    required_change: RequiredChange
    evidence:        EvidencePointer
    remediation:     RemediationPlan
    human_oversight: HumanOversight
    metadata:        dict = Field(default_factory=dict)


class GapAnalysisReport(BaseModel):
    run_id:            str
    generated_at:      str
    regulation_source: str
    jurisdiction:      str
    total_gaps:        int
    gap_summary:       dict
    gaps:              list[GapFinding]


# ── Claude prompt ────────────────────────────────────────────────────────────

CLAUDE_MODEL = "claude-sonnet-4-6"

_PROMPT_TEMPLATE = """\
You are a senior regulatory compliance analyst performing a gap analysis.

## Regulatory Change
Change ID      : {change_id}
Source Section : {source_section}
Effective Date : {effective_date}
Jurisdiction   : {jurisdiction}
Requirement    : {requirement}

## Current Internal Policy
Policy ID   : {policy_id}
Policy Area : {policy_area}
Policy Text : {current_policy}
Owner       : {owner}

## Your Task
Determine the compliance gap between the regulatory requirement and the current policy.
Return ONLY a JSON object with exactly these fields — no markdown, no extra text:

{{
  "gap_status": "<Non-compliant | Partial | Needs Review | Compliant>",
  "severity": "<Critical | High | Medium | Low>",
  "confidence": <float 0.0-1.0>,
  "gap_description": "<one or two sentences describing exactly what is missing or misaligned>",
  "recommended_action": "<concrete, actionable remediation step>",
  "effort_estimate": "<Low | Medium | High>",
  "suggested_owner": "<team or role best placed to execute the remediation>",
  "human_review_required": <true | false>,
  "review_reason": "<why a human must review this, or empty string if not required>",
  "open_questions": ["<legal/regulatory question that needs SME input>", ...],
  "flagged_ambiguities": ["<exact phrase from the regulation that is vague>", ...]
}}

Classification guide:
- Non-compliant : policy directly contradicts or ignores the requirement
- Partial        : policy partially satisfies the requirement (some element missing)
- Needs Review   : relationship is unclear without further legal interpretation
- Compliant      : policy already satisfies the requirement (no gap)
- human_review_required = true whenever confidence < 0.80 or language is ambiguous
"""


# ── Core functions ───────────────────────────────────────────────────────────

def _classify_area(requirement: str) -> str:
    text = requirement.lower()
    if "kyc" in text or "customer" in text:
        return "KYC"
    if "transaction" in text or "suspicious" in text:
        return "Monitoring"
    if "evidence" in text or "audit" in text or "retain" in text:
        return "Audit"
    return "General"


def _target_deadline(effective_date: str) -> str:
    try:
        dt = datetime.fromisoformat(effective_date)
        return (dt - timedelta(days=30)).date().isoformat()
    except ValueError:
        return effective_date


def _rule_based_gap(change: dict, policy: dict) -> dict:
    """Deterministic fallback used when the Claude API is unavailable."""
    import re

    # Use only the body of the requirement (skip the first line which is the section header)
    req_lines = change["requirement"].strip().splitlines()
    req_body = " ".join(req_lines[1:]).lower() if len(req_lines) > 1 else req_lines[0].lower()
    pol = policy.get("current_policy", "").lower()

    # Extract numbers that are followed by a time unit — avoids capturing section numbers
    _time_nums = re.compile(r"(\d+)\s*(?:months?|years?|days?|hours?|weeks?)")

    req_time = _time_nums.findall(req_body)
    pol_time = _time_nums.findall(pol)

    # Detect frequency-word mismatches (daily vs weekly, etc.)
    _freq_order = ["hourly", "daily", "weekly", "monthly", "quarterly", "annually"]
    req_freq = next((f for f in _freq_order if f in req_body), None)
    pol_freq = next((f for f in _freq_order if f in pol), None)

    high_risk_language = any(t in req_body for t in ["must", "within", "high-risk", "mandatory"])

    if pol == "no matching policy found":
        gap_status = "Non-compliant"
        gap_desc = "No internal policy exists for this regulatory requirement."
        severity = "High"
        effort = "High"
        action = f"Draft a new policy to satisfy: {req_lines[-1][:120]}"
        human = True
        reason = "No existing policy — legal drafting required before remediation can start."

    elif req_time and pol_time and req_time[0] != pol_time[0]:
        gap_status = "Non-compliant"
        gap_desc = (
            f"Time-period mismatch: regulation requires {req_time[0]} "
            f"but current policy specifies {pol_time[0]}."
        )
        severity = "High" if high_risk_language else "Medium"
        effort = "Medium"
        action = (
            f"Update '{policy.get('policy_id', 'policy')}' to change the retention/review period "
            f"from {pol_time[0]} to {req_time[0]} as required by {change['source_section']}."
        )
        human = False
        reason = ""

    elif req_freq and pol_freq and _freq_order.index(req_freq) < _freq_order.index(pol_freq):
        gap_status = "Non-compliant"
        gap_desc = (
            f"Frequency mismatch: regulation requires {req_freq} action "
            f"but current policy only specifies {pol_freq}."
        )
        severity = "High" if high_risk_language else "Medium"
        effort = "High"
        action = (
            f"Update '{policy.get('policy_id', 'policy')}' and supporting systems "
            f"to increase monitoring frequency from {pol_freq} to {req_freq}."
        )
        human = True
        reason = "Frequency increase may require system or workflow changes; human sign-off needed."

    else:
        gap_status = "Needs Review"
        gap_desc = "Policy exists but semantic alignment with the requirement needs manual verification."
        severity = "Medium"
        effort = "Low"
        action = "Perform a manual policy review against the regulatory requirement text."
        human = True
        reason = "Rule-based fallback could not determine gap with confidence — human review required."

    return {
        "gap_status": gap_status,
        "severity": severity,
        "confidence": 0.70,
        "gap_description": gap_desc,
        "recommended_action": action,
        "effort_estimate": effort,
        "suggested_owner": policy.get("owner", "Compliance Team"),
        "human_review_required": human,
        "review_reason": reason,
        "open_questions": [],
        "flagged_ambiguities": [],
    }


def _call_claude(client: anthropic.Anthropic, change: dict, policy: dict) -> dict:
    prompt = _PROMPT_TEMPLATE.format(
        change_id=change["change_id"],
        source_section=change["source_section"],
        effective_date=change["effective_date"],
        jurisdiction=change["jurisdiction"],
        requirement=change["requirement"],
        policy_id=policy.get("policy_id", "N/A"),
        policy_area=policy.get("policy_area", "General"),
        current_policy=policy.get("current_policy", "No matching policy found"),
        owner=policy.get("owner", "Unknown"),
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
    except (anthropic.BadRequestError, anthropic.AuthenticationError,
            anthropic.PermissionDeniedError, anthropic.APIConnectionError,
            anthropic.RateLimitError) as exc:
        print(f"[agent_c] Claude unavailable ({type(exc).__name__}): {exc}. Using rule-based fallback.")
        result = _rule_based_gap(change, policy)
        result["_source"] = "fallback"
        return result


def _build_finding(
    idx: int,
    change: dict,
    policy: dict,
    evidence: dict,
    claude: dict,
) -> GapFinding:
    return GapFinding(
        gap_id=make_id("GAP", idx),
        change_id=change["change_id"],
        policy_area=policy.get("policy_area", "General"),
        gap_status=GapStatus(claude["gap_status"]),
        severity=Severity(claude["severity"]),
        confidence=float(claude["confidence"]),
        gap_description=claude["gap_description"],
        current_policy=CurrentPolicyRef(
            policy_id=policy.get("policy_id", "N/A"),
            text=policy.get("current_policy", "No matching policy found"),
            owner=policy.get("owner", "Unknown"),
            jurisdiction=policy.get("jurisdiction", change.get("jurisdiction", "Unknown")),
        ),
        required_change=RequiredChange(
            requirement_text=change["requirement"],
            source_section=change["source_section"],
            effective_date=change["effective_date"],
            jurisdiction=change["jurisdiction"],
        ),
        evidence=EvidencePointer(
            evidence_id=change["evidence_id"],
            source_section=change["source_section"],
            source_file=evidence.get("source_file", ""),
            source_quote=evidence.get("text_excerpt", change["requirement"][:300]),
            content_hash=evidence.get("content_hash"),
        ),
        remediation=RemediationPlan(
            recommended_action=claude["recommended_action"],
            effort_estimate=EffortEstimate(claude["effort_estimate"]),
            suggested_owner=claude.get("suggested_owner", policy.get("owner", "Unknown")),
            target_deadline=_target_deadline(change["effective_date"]),
        ),
        human_oversight=HumanOversight(
            review_required=bool(claude["human_review_required"]),
            review_reason=claude.get("review_reason", ""),
            open_questions=claude.get("open_questions", []),
            flagged_ambiguities=claude.get("flagged_ambiguities", []),
        ),
        metadata={
            "analyzed_by": "agent_c_gap_analysis",
            "analyzed_at": timestamp(),
            "model": CLAUDE_MODEL if claude.get("_source") == "claude" else "rule_based_fallback",
            "analysis_source": claude.get("_source", "unknown"),
        },
    )


# ── Entry point ──────────────────────────────────────────────────────────────

def run() -> GapAnalysisReport:
    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from environment

    changes       = read_json(OUTPUT_DIR / "change_register.json", default=[])
    evidence_index = read_json(OUTPUT_DIR / "evidence_index.json", default=[])
    context_packet = read_json(OUTPUT_DIR / "context_packet.json", default={"metadata": {}})
    policies_df   = pd.read_csv(INPUT_DIR / "current_policies.csv")

    evidence_map = {ev["evidence_id"]: ev for ev in evidence_index}

    severity_counts = {s.value: 0 for s in Severity}
    status_counts   = {s.value: 0 for s in GapStatus}
    findings: list[GapFinding] = []

    for idx, change in enumerate(changes, start=1):
        area = _classify_area(change["requirement"])
        matched = policies_df[policies_df["policy_area"].str.lower() == area.lower()]
        policy = matched.iloc[0].to_dict() if not matched.empty else {
            "policy_id": "N/A",
            "policy_area": area,
            "current_policy": "No matching policy found",
            "owner": "Unknown",
            "jurisdiction": change.get("jurisdiction", "Unknown"),
        }

        evidence = evidence_map.get(change["evidence_id"], {})
        claude_result = _call_claude(client, change, policy)

        finding = _build_finding(idx, change, policy, evidence, claude_result)
        severity_counts[finding.severity.value] += 1
        status_counts[finding.gap_status.value] += 1
        findings.append(finding)

    meta = context_packet.get("metadata", {})
    report = GapAnalysisReport(
        run_id=context_packet.get("context_packet_id", make_id("RUN", 1)),
        generated_at=timestamp(),
        regulation_source=meta.get("source_file", "regulation.txt"),
        jurisdiction=meta.get("jurisdiction", "Unknown"),
        total_gaps=len(findings),
        gap_summary={**severity_counts, **status_counts},
        gaps=findings,
    )

    write_json(OUTPUT_DIR / "gap_analysis.json", report.model_dump())
    return report


if __name__ == "__main__":
    run()
