"""
Agent E - Control Mapping Engine
Responsibilities:
1. Existing Control Mapping  - link gaps to existing controls
2. New Control Identification - flag gaps with no coverage
3. Cross-Jurisdiction Overlap Detection - detect same requirement across jurisdictions
4. Control Evidence and Documentation - control gap register with effort, owner, evidence
"""

import pandas as pd
from agents.utils import INPUT_DIR, OUTPUT_DIR, read_json, write_json, make_id, timestamp

# Severity → effort estimate
_EFFORT_MAP = {"Critical": "High", "High": "High", "Medium": "Medium", "Low": "Low"}

# Severity → evidence requirements
_EVIDENCE_REQ = {
    "Critical": ["Policy document", "System audit log", "Legal sign-off", "Board approval"],
    "High":     ["Policy document", "System audit log", "Manager sign-off"],
    "Medium":   ["Policy document", "Peer review sign-off"],
    "Low":      ["Policy document"],
}


def _extract_gaps(raw) -> list:
    if isinstance(raw, list):
        return raw
    return raw.get("gaps", [])


def _detect_cross_jurisdiction_overlap(gap: dict, all_gaps: list, scope_jurisdictions: list) -> dict:
    """
    A gap has a cross-jurisdiction overlap when:
    - The same policy_area appears in more than one jurisdiction, OR
    - The project scope covers multiple jurisdictions and this gap's requirement
      text references multi-jurisdiction keywords.
    Returns a dict with overlap flag and details.
    """
    policy_area = gap.get("policy_area", "")
    gap_jurisdiction = (
        gap.get("required_change", {}).get("jurisdiction")
        or gap.get("jurisdiction", "Unknown")
    )

    overlapping_jurisdictions = set()

    # Check if other gaps share the same policy_area but different jurisdiction
    for other in all_gaps:
        if other.get("gap_id") == gap.get("gap_id"):
            continue
        if other.get("policy_area") == policy_area:
            other_jurisdiction = (
                other.get("required_change", {}).get("jurisdiction")
                or other.get("jurisdiction", "Unknown")
            )
            if other_jurisdiction != gap_jurisdiction:
                overlapping_jurisdictions.add(other_jurisdiction)

    # Check scope: if scope has multiple jurisdictions and requirement mentions cross-border terms
    req_text = (
        gap.get("required_change", {}).get("requirement_text", "")
        or gap.get("requirement", "")
    ).lower()

    cross_border_keywords = ["cross-border", "international", "global", "multi-jurisdiction",
                              "third country", "passporting", "mutual recognition"]
    text_signals_overlap = any(kw in req_text for kw in cross_border_keywords)

    if text_signals_overlap and len(scope_jurisdictions) > 1:
        overlapping_jurisdictions.update(j for j in scope_jurisdictions if j != gap_jurisdiction)

    has_overlap = bool(overlapping_jurisdictions)
    return {
        "has_overlap": has_overlap,
        "jurisdictions_affected": sorted(overlapping_jurisdictions) if has_overlap else [],
        "overlap_note": (
            f"Same requirement detected across jurisdictions: {', '.join(sorted(overlapping_jurisdictions))}"
            if has_overlap else "No cross-jurisdiction overlap detected"
        ),
    }


def run():
    raw_gaps          = read_json(OUTPUT_DIR / "gap_analysis.json", default=[])
    gaps              = _extract_gaps(raw_gaps)
    controls          = pd.read_csv(INPUT_DIR / "control_inventory.csv")
    jurisdiction_scope = read_json(INPUT_DIR / "jurisdiction_scope.json", default={})
    scope_jurisdictions = jurisdiction_scope.get("jurisdictions", ["EU"])

    # Load impact assessments for effort context (optional enrichment)
    raw_impacts = read_json(OUTPUT_DIR / "impact_assessment.json", default={})
    impact_list = raw_impacts.get("assessments", []) if isinstance(raw_impacts, dict) else raw_impacts
    impact_by_gap = {item["gap_id"]: item for item in impact_list}

    mappings = []

    for idx, gap in enumerate(gaps, start=1):
        area     = gap.get("policy_area")
        severity = gap.get("severity", "Medium")
        gap_id   = gap["gap_id"]

        # ── 1. Existing control mapping / new control identification ──────────
        matched = controls[controls["control_area"] == area]

        if not matched.empty:
            row            = matched.iloc[0]
            mapping_status = "Existing control mapped"
            control_id     = row["control_id"]
            control_name   = row["control_name"]
            control_owner  = row.get("owner", "Unknown")
            recommendation = "Update existing control to meet new regulatory requirement"
        else:
            mapping_status = "New control required"
            control_id     = make_id("NEW-CTRL", idx)
            control_name   = f"New {area} Control"
            control_owner  = "Compliance Team"
            recommendation = "Design and implement a new control; assign a dedicated owner"

        # ── 2. Owner resolution (gap → impact → control fallback chain) ───────
        gap_owner    = (gap.get("current_policy") or {}).get("owner") or gap.get("owner")
        impact_owner = (impact_by_gap.get(gap_id, {}).get("affected_processes") or [{}])[0].get("owner")
        owner        = gap_owner or impact_owner or control_owner or "Unknown"

        # ── 3. Evidence pointer ───────────────────────────────────────────────
        evidence_id = (
            (gap.get("evidence") or {}).get("evidence_id")
            or gap.get("evidence_id")
        )

        # ── 4. Effort estimate ────────────────────────────────────────────────
        # Prefer Agent D's remediation_complexity; fall back to severity map
        impact_complexity = impact_by_gap.get(gap_id, {}).get("remediation_complexity")
        effort_estimate   = impact_complexity or _EFFORT_MAP.get(severity, "Medium")

        # ── 5. Evidence requirements (what artefacts are needed to close gap) ─
        evidence_requirements = _EVIDENCE_REQ.get(severity, ["Policy document"])

        # ── 6. Cross-jurisdiction overlap ─────────────────────────────────────
        overlap_info = _detect_cross_jurisdiction_overlap(gap, gaps, scope_jurisdictions)

        mappings.append({
            "mapping_id":                  make_id("MAP", idx),
            "gap_id":                      gap_id,
            "change_id":                   gap["change_id"],
            "control_id":                  control_id,
            "control_name":                control_name,
            "mapping_status":              mapping_status,
            "owner":                       owner,
            "evidence_id":                 evidence_id,
            "recommendation":              recommendation,
            # ── Control Gap Register fields ──────────────────────────────────
            "effort_estimate":             effort_estimate,
            "evidence_requirements":       evidence_requirements,
            "suggested_owner":             owner,
            # ── Cross-jurisdiction overlap ────────────────────────────────────
            "cross_jurisdiction_overlap":  overlap_info["has_overlap"],
            "jurisdictions_affected":      overlap_info["jurisdictions_affected"],
            "overlap_note":                overlap_info["overlap_note"],
            # ── Metadata ─────────────────────────────────────────────────────
            "metadata": {
                "mapped_by":    "agent_e_control_mapping",
                "mapped_at":    timestamp(),
                "scope":        scope_jurisdictions,
            },
        })

    write_json(OUTPUT_DIR / "control_mapping.json", mappings)
    print(f"[agent_e] Control Mapping complete — {len(mappings)} mappings written.")
    new_controls = sum(1 for m in mappings if m["mapping_status"] == "New control required")
    overlaps     = sum(1 for m in mappings if m["cross_jurisdiction_overlap"])
    print(f"  Existing controls mapped : {len(mappings) - new_controls}")
    print(f"  New controls required    : {new_controls}")
    print(f"  Cross-jurisdiction overlaps: {overlaps}")
    return mappings


if __name__ == "__main__":
    run()
