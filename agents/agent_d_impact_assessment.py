"""
Agent D - Impact Assessment
Responsibilities:
- Assess process/system/business impact
- Score risk and priority
- Generate impact_assessment.json
"""

import pandas as pd
from agents.utils import INPUT_DIR, OUTPUT_DIR, read_json, write_json, make_id


def risk_score(severity: str) -> int:
    return {
        "High": 90,
        "Medium": 60,
        "Low": 30
    }.get(severity, 40)


def priority_from_score(score: int) -> str:
    if score >= 80:
        return "Critical"
    if score >= 60:
        return "High"
    if score >= 40:
        return "Medium"
    return "Low"


def run():
    gaps = read_json(OUTPUT_DIR / "gap_analysis.json", default=[])
    process_map = pd.read_csv(INPUT_DIR / "process_map.csv")
    impact_items = []

    for idx, gap in enumerate(gaps, start=1):
        area = gap.get("policy_area")
        matched = process_map[process_map["process_name"].str.contains(area, case=False, na=False)]
        if matched.empty and area == "Monitoring":
            matched = process_map[process_map["process_name"].str.contains("Transaction", case=False, na=False)]
        if matched.empty and area == "Audit":
            matched = process_map[process_map["process_name"].str.contains("Audit", case=False, na=False)]

        row = matched.iloc[0] if not matched.empty else None
        score = risk_score(gap.get("severity"))

        impact_items.append({
            "impact_id": make_id("IMP", idx),
            "gap_id": gap["gap_id"],
            "change_id": gap["change_id"],
            "affected_process": row["process_name"] if row is not None else "Unknown",
            "affected_system": row["system"] if row is not None else "Unknown",
            "business_unit": row["business_unit"] if row is not None else "Unknown",
            "risk_score": score,
            "priority": priority_from_score(score),
            "remediation_complexity": "Medium" if score < 80 else "High"
        })

    write_json(OUTPUT_DIR / "impact_assessment.json", impact_items)
    return impact_items


if __name__ == "__main__":
    run()
