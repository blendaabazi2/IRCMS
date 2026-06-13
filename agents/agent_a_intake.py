"""
Agent A - Regulatory Feed Intake
Responsibilities:
- Read regulatory input
- Classify document
- Extract metadata
- Build context_packet.json
- Build evidence_index.json
"""

import re
from agents.utils import INPUT_DIR, OUTPUT_DIR, read_text_file, write_json, make_id, stable_hash, timestamp


def extract_metadata(text: str) -> dict:
    def find_value(label: str, default: str = "Unknown") -> str:
        match = re.search(rf"{label}:\s*(.+)", text, re.IGNORECASE)
        return match.group(1).strip() if match else default

    return {
        "document_title": find_value("Regulatory Publication"),
        "jurisdiction": find_value("Jurisdiction"),
        "regulator": find_value("Regulator"),
        "effective_date": find_value("Effective Date"),
        "document_type": "Regulatory Publication",
        "source_file": "input/regulation.txt",
        "processed_at": timestamp()
    }


def build_evidence_index(text: str) -> list:
    sections = re.split(r"\n(?=Section\s+\d+\.\d+)", text)
    evidence = []

    counter = 1
    for section in sections:
        if section.strip().startswith("Section"):
            first_line = section.strip().splitlines()[0]
            evidence.append({
                "evidence_id": make_id("EV", counter),
                "source_section": first_line,
                "source_file": "input/regulation.txt",
                "text_excerpt": section.strip(),
                "content_hash": stable_hash(section.strip())
            })
            counter += 1

    return evidence


def run():
    regulation_text = read_text_file(INPUT_DIR / "regulation.txt")
    metadata = extract_metadata(regulation_text)
    evidence_index = build_evidence_index(regulation_text)

    context_packet = {
        "context_packet_id": "CTX-001",
        "metadata": metadata,
        "jurisdiction_scope_file": "input/jurisdiction_scope.json",
        "evidence_count": len(evidence_index),
        "risk_signals": ["must", "high-risk", "within 48 hours"],
        "status": "created"
    }

    write_json(OUTPUT_DIR / "context_packet.json", context_packet)
    write_json(OUTPUT_DIR / "evidence_index.json", evidence_index)

    return context_packet, evidence_index


if __name__ == "__main__":
    run()
