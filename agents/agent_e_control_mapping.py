"""
Agent E - Control Mapping
Responsibilities:
- Map regulatory changes/gaps to existing controls
- Identify missing controls
- Generate control_mapping.json
"""

import pandas as pd
from agents.utils import INPUT_DIR, OUTPUT_DIR, read_json, write_json, make_id


def _extract_gaps(raw) -> list:
    """Handle both old list format and new {'gaps': [...]} dict format."""
    if isinstance(raw, list):
        return raw
    return raw.get("gaps", [])


def run():
    raw_gaps = read_json(OUTPUT_DIR / "gap_analysis.json", default=[])
    gaps     = _extract_gaps(raw_gaps)
    controls = pd.read_csv(INPUT_DIR / "control_inventory.csv")
    mappings = []

    for idx, gap in enumerate(gaps, start=1):
        area = gap.get("policy_area")
        matched = controls[controls["control_area"] == area]

        if not matched.empty:
            row = matched.iloc[0]
            mapping_status = "Existing control mapped"
            control_id = row["control_id"]
            control_name = row["control_name"]
            recommendation = "Update existing control to meet new regulatory requirement"
        else:
            mapping_status = "New control required"
            control_id = make_id("NEW-CTRL", idx)
            control_name = f"New {area} Control"
            recommendation = "Create a new control and assign an owner"

        # Support both old flat fields and new nested schema from Agent C
        owner      = (gap.get("current_policy") or {}).get("owner") or gap.get("owner", "Unknown")
        evidence_id = (gap.get("evidence") or {}).get("evidence_id") or gap.get("evidence_id")

        mappings.append({
            "mapping_id": make_id("MAP", idx),
            "gap_id": gap["gap_id"],
            "change_id": gap["change_id"],
            "control_id": control_id,
            "control_name": control_name,
            "mapping_status": mapping_status,
            "cross_jurisdiction_overlap": False,
            "owner": owner,
            "evidence_id": evidence_id,
            "recommendation": recommendation
        })

    write_json(OUTPUT_DIR / "control_mapping.json", mappings)
    return mappings


if __name__ == "__main__":
    run()
