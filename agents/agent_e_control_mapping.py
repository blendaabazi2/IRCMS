"""
Agent E - Control Mapping
Responsibilities:
- Map regulatory changes/gaps to existing controls
- Identify missing controls
- Generate control_mapping.json
"""

import pandas as pd
from agents.utils import INPUT_DIR, OUTPUT_DIR, read_json, write_json, make_id


def run():
    gaps = read_json(OUTPUT_DIR / "gap_analysis.json", default=[])
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

        mappings.append({
            "mapping_id": make_id("MAP", idx),
            "gap_id": gap["gap_id"],
            "change_id": gap["change_id"],
            "control_id": control_id,
            "control_name": control_name,
            "mapping_status": mapping_status,
            "cross_jurisdiction_overlap": False,
            "owner": gap.get("owner", "Unknown"),
            "evidence_id": gap.get("evidence_id"),
            "recommendation": recommendation
        })

    write_json(OUTPUT_DIR / "control_mapping.json", mappings)
    return mappings


if __name__ == "__main__":
    run()
