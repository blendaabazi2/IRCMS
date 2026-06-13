"""
Agent C - Gap Analysis
Responsibilities:
- Compare extracted regulatory changes with current policies
- Identify compliance gaps
- Generate gap_analysis.json
"""

import pandas as pd
from agents.utils import INPUT_DIR, OUTPUT_DIR, read_json, write_json, make_id


def classify_area(requirement: str) -> str:
    text = requirement.lower()
    if "kyc" in text or "customer" in text:
        return "KYC"
    if "transaction" in text or "suspicious" in text:
        return "Monitoring"
    if "evidence" in text or "audit" in text or "retain" in text:
        return "Audit"
    return "General"


def determine_gap_status(requirement: str, current_policy: str) -> str:
    req = requirement.lower()
    pol = current_policy.lower()

    if "12 months" in req and "24 months" in pol:
        return "Non-compliant"
    if "daily" in req and "weekly" in pol:
        return "Non-compliant"
    if "5 years" in req and "3 years" in pol:
        return "Non-compliant"
    return "Needs Review"


def severity_from_gap(requirement: str, gap_status: str) -> str:
    if gap_status == "Non-compliant":
        if any(term in requirement.lower() for term in ["high-risk", "within 48 hours", "must"]):
            return "High"
        return "Medium"
    return "Low"


def run():
    changes = read_json(OUTPUT_DIR / "change_register.json", default=[])
    policies = pd.read_csv(INPUT_DIR / "current_policies.csv")
    gaps = []

    for idx, change in enumerate(changes, start=1):
        area = classify_area(change["requirement"])
        matched = policies[policies["policy_area"] == area]
        policy_text = matched.iloc[0]["current_policy"] if not matched.empty else "No matching policy found"
        owner = matched.iloc[0]["owner"] if not matched.empty else "Unknown"
        status = determine_gap_status(change["requirement"], policy_text)

        gaps.append({
            "gap_id": make_id("GAP", idx),
            "change_id": change["change_id"],
            "policy_area": area,
            "current_policy": policy_text,
            "required_policy": change["requirement"],
            "gap_status": status,
            "severity": severity_from_gap(change["requirement"], status),
            "owner": owner,
            "evidence_id": change["evidence_id"]
        })

    write_json(OUTPUT_DIR / "gap_analysis.json", gaps)
    return gaps


if __name__ == "__main__":
    run()
