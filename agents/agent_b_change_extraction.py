"""
Agent B - Change Extraction
Responsibilities:
- Extract regulatory requirements
- Convert them into structured changes
- Add confidence score and evidence pointer
- Generate change_register.json
"""

import re
from agents.utils import INPUT_DIR, OUTPUT_DIR, read_text_file, read_json, write_json, make_id


def calculate_confidence(requirement: str) -> float:
    score = 0.70
    if "must" in requirement.lower():
        score += 0.15
    if any(term in requirement.lower() for term in ["within", "every", "at least"]):
        score += 0.06
    if len(requirement.split()) > 8:
        score += 0.04
    return round(min(score, 0.98), 2)


def extract_changes(text: str, evidence_index: list, context_packet: dict) -> list:
    changes = []
    counter = 1

    for evidence in evidence_index:
        excerpt = evidence.get("text_excerpt", "")
        sentences = re.split(r"(?<=[.!?])\s+", excerpt)
        for sentence in sentences:
            if "must" in sentence.lower():
                changes.append({
                    "change_id": make_id("CHG", counter),
                    "requirement": sentence.strip(),
                    "jurisdiction": context_packet["metadata"].get("jurisdiction", "Unknown"),
                    "effective_date": context_packet["metadata"].get("effective_date", "Unknown"),
                    "source_section": evidence.get("source_section"),
                    "evidence_id": evidence.get("evidence_id"),
                    "confidence": calculate_confidence(sentence),
                    "extraction_method": "rule_based_demo"
                })
                counter += 1

    return changes


def run():
    text = read_text_file(INPUT_DIR / "regulation.txt")
    evidence_index = read_json(OUTPUT_DIR / "evidence_index.json", default=[])
    context_packet = read_json(OUTPUT_DIR / "context_packet.json", default={"metadata": {}})

    changes = extract_changes(text, evidence_index, context_packet)
    write_json(OUTPUT_DIR / "change_register.json", changes)
    return changes


if __name__ == "__main__":
    run()
