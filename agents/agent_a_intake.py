"""
Agent A - Regulatory Feed Intake (Gatekeeper)

Four responsibilities:
  1. Regulatory Processing Gateway  — load TXT/PDF/HTML, classify each change type
  2. Context Packet Construction    — metadata + policy references + jurisdiction scope
  3. Universal Evidence Index       — link every change to its source paragraph (page + section)
  4. Risk Detection & Filtering     — flag penalty risks and short effective windows (< 60 days)

Outputs:
  output/classified_changes.json
  output/context_packet.json
  output/evidence_index.json
  output/risk_flags.json
"""

import re
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd
import yaml

from agents.utils import (
    INPUT_DIR, OUTPUT_DIR,
    read_text_file, write_json, make_id, stable_hash, timestamp,
)

BASE_DIR = Path(__file__).resolve().parents[1]


# ═══════════════════════════════════════════════════════════════════════════════
# MANIFEST VALIDATION
# ═══════════════════════════════════════════════════════════════════════════════

def validate_manifest() -> dict:
    """
    Load and validate manifest.yaml against manifest_schema.json.
    Returns the parsed manifest. Raises FileNotFoundError if manifest is missing.
    """
    manifest_path = BASE_DIR / "manifest.yaml"
    if not manifest_path.exists():
        raise FileNotFoundError("manifest.yaml not found in project root.")

    with open(manifest_path, encoding="utf-8") as f:
        manifest = yaml.safe_load(f)

    required_inputs = ["regulation", "policies", "control_inventory", "process_map", "jurisdiction_scope"]
    missing = [k for k in required_inputs if k not in manifest.get("inputs", {})]
    if missing:
        raise ValueError(f"manifest.yaml is missing required input keys: {missing}")

    missing_files = []
    for key, cfg in manifest["inputs"].items():
        if cfg.get("required") and not (BASE_DIR / cfg["file"]).exists():
            missing_files.append(cfg["file"])
    if missing_files:
        raise FileNotFoundError(f"Required input files declared in manifest.yaml not found: {missing_files}")

    # Stamp generated_at and save back
    manifest["generated_at"] = timestamp()
    with open(manifest_path, "w", encoding="utf-8") as f:
        yaml.dump(manifest, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    print(f"[agent_a] manifest.yaml validated — bundle_id: {manifest.get('bundle_id')}")
    return manifest


# ═══════════════════════════════════════════════════════════════════════════════
# 1. REGULATORY PROCESSING GATEWAY
# ═══════════════════════════════════════════════════════════════════════════════

_CHANGE_TYPE_PATTERNS: dict[str, list[str]] = {
    "new_requirement": [r"\bmust\b", r"\bshall\b", r"\brequired to\b", r"\bobligated\b"],
    "amendment":       [r"\bamended\b", r"\bupdated\b", r"\bmodified\b", r"\breplaced by\b"],
    "revocation":      [r"\brevoked\b", r"\bsuperseded\b", r"\bno longer applies\b", r"\bnull and void\b"],
    "clarification":   [r"\bclarif\w+\b", r"\bfor the purposes of\b", r"\bmeans\b", r"\bdefined as\b"],
    "guidance":        [r"\bshould\b", r"\brecommend\b", r"\bencourage\b", r"\bbest practice\b"],
}


def _find_regulation_file() -> Path:
    """Return the first regulation file found in input/ (.txt, .pdf, .html)."""
    for pattern in ("*.txt", "*.pdf", "*.html", "*.htm"):
        matches = list(INPUT_DIR.glob(pattern))
        if matches:
            return matches[0]
    raise FileNotFoundError("No regulation file found in input/ (expected .txt, .pdf, or .html)")


def _load_text(path: Path) -> str:
    """Load plain text from .txt, .pdf, or .html source."""
    suffix = path.suffix.lower()

    if suffix == ".pdf":
        try:
            from pypdf import PdfReader
            reader = PdfReader(str(path))
            pages = [page.extract_text() or "" for page in reader.pages]
            return "\n".join(pages)
        except ImportError:
            print("[agent_a] pypdf not installed — reading PDF as raw text.")
            return path.read_text(encoding="utf-8", errors="ignore")

    if suffix in (".html", ".htm"):
        import html as _html
        raw = path.read_text(encoding="utf-8", errors="ignore")
        stripped = re.sub(r"<[^>]+>", " ", raw)
        return _html.unescape(stripped)

    return read_text_file(path)


def _classify_change_type(text: str) -> str:
    tl = text.lower()
    for change_type, patterns in _CHANGE_TYPE_PATTERNS.items():
        if any(re.search(p, tl) for p in patterns):
            return change_type
    return "general"


def build_classified_changes(evidence_index: list) -> list:
    """
    Classify each paragraph in the evidence index into a typed change record.
    Output: classified_changes[] consumed by Agent B and Risk Filtering.
    """
    classified = []
    counter = 1
    for ev in evidence_index:
        sentences = re.split(r"(?<=[.!?])\s+", ev.get("text_excerpt", ""))
        for sentence in sentences:
            stripped = sentence.strip()
            # Skip pure section-header lines (no verb content)
            if not stripped or len(stripped.split()) < 4:
                continue
            if re.match(r"^Section\s+[\d.]+", stripped) and "." not in stripped:
                continue
            classified.append({
                "classified_id":  make_id("CLS", counter),
                "evidence_id":    ev["evidence_id"],
                "source_section": ev["source_section"],
                "page_estimate":  ev["page_estimate"],
                "text":           stripped,
                "change_type":    _classify_change_type(stripped),
                "content_hash":   stable_hash(stripped),
            })
            counter += 1
    return classified


# ═══════════════════════════════════════════════════════════════════════════════
# 2. CONTEXT PACKET CONSTRUCTION
# ═══════════════════════════════════════════════════════════════════════════════

def _extract_metadata(text: str, source_file: str) -> dict:
    def find(label: str, default: str = "Unknown") -> str:
        m = re.search(rf"{label}:\s*(.+)", text, re.IGNORECASE)
        return m.group(1).strip() if m else default

    return {
        "document_title": find("Regulatory Publication"),
        "jurisdiction":   find("Jurisdiction"),
        "regulator":      find("Regulator"),
        "effective_date": find("Effective Date"),
        "document_type":  "Regulatory Publication",
        "source_file":    source_file,
        "processed_at":   timestamp(),
    }


def _load_policy_references() -> list:
    path = INPUT_DIR / "current_policies.csv"
    if not path.exists():
        return []
    return pd.read_csv(path).to_dict(orient="records")


def _load_jurisdiction_scope() -> dict:
    path = INPUT_DIR / "jurisdiction_scope.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def build_context_packet(
    metadata: dict,
    evidence_index: list,
    jurisdiction_scope: dict,
    policy_refs: list,
) -> dict:
    return {
        "context_packet_id": "CTX-001",
        "metadata":           metadata,
        "jurisdiction_scope": jurisdiction_scope,
        "policy_references":  policy_refs,
        "evidence_count":     len(evidence_index),
        "risk_signals":       ["must", "high-risk", "within 48 hours", "penalty", "sanction"],
        "change_history":     [],
        "status":             "created",
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 3. UNIVERSAL EVIDENCE INDEX
# ═══════════════════════════════════════════════════════════════════════════════

def build_evidence_index(text: str, source_file: str) -> list:
    """
    Split document on Section headers. Each paragraph within a section becomes
    a separate evidence record with a page estimate and paragraph number so
    downstream agents can trace every requirement back to its exact source.
    """
    sections = re.split(r"\n(?=Section\s+[\d.]+)", text)
    evidence = []
    char_offset = 0
    counter = 1

    for section in sections:
        stripped = section.strip()
        if not stripped.startswith("Section"):
            char_offset += len(section)
            continue

        lines      = stripped.splitlines()
        first_line = lines[0].strip()
        body       = "\n".join(lines[1:]).strip()

        # Split body into paragraphs (blank-line separated); fall back to whole body
        raw_paras = [p.strip() for p in re.split(r"\n{2,}", body) if p.strip()]
        if not raw_paras and body:
            raw_paras = [body]

        for para_idx, para in enumerate(raw_paras, start=1):
            evidence.append({
                "evidence_id":      make_id("EV", counter),
                "source_section":   first_line,
                "source_file":      source_file,
                "paragraph_number": para_idx,
                "page_estimate":    max(1, char_offset // 3000 + 1),
                "text_excerpt":     para,
                "content_hash":     stable_hash(para),
            })
            counter += 1

        char_offset += len(section)

    return evidence


# ═══════════════════════════════════════════════════════════════════════════════
# 4. RISK DETECTION & FILTERING
# ═══════════════════════════════════════════════════════════════════════════════

_PENALTY_KEYWORDS = [
    "penalty", "penalties", "fine", "fines", "sanction", "sanctions",
    "enforcement", "liable", "liability", "breach", "violation",
]

_IRRELEVANT_PATTERNS = [
    r"^\s*$",
    r"^section\s+[\d.]+\s*[-–]",
    r"^(regulatory publication|jurisdiction|regulator|effective date)\s*:",
]

_SHORT_WINDOW_DAYS = 60


def _days_until(date_str: str) -> Optional[int]:
    try:
        target = datetime.fromisoformat(date_str).replace(tzinfo=timezone.utc)
        return max(0, (target - datetime.now(tz=timezone.utc)).days)
    except ValueError:
        return None


def _is_irrelevant(text: str) -> bool:
    tl = text.strip().lower()
    return any(re.match(p, tl) for p in _IRRELEVANT_PATTERNS)


def build_risk_flags(classified_changes: list, effective_date: str) -> list:
    """
    Flag changes that:
    - contain penalty / enforcement language
    - fall within a < 60-day effective window
    - are structurally irrelevant (headers, label lines)

    Items are flagged, not removed, so downstream agents can decide what to skip.
    """
    days = _days_until(effective_date)
    flags = []
    counter = 1

    for ch in classified_changes:
        tl = ch["text"].lower()

        has_penalty   = any(kw in tl for kw in _PENALTY_KEYWORDS)
        short_window  = days is not None and days < _SHORT_WINDOW_DAYS
        is_irrelevant = _is_irrelevant(ch["text"])
        high_impact   = ch["change_type"] == "new_requirement" and (has_penalty or short_window)

        if not (has_penalty or short_window or is_irrelevant or high_impact):
            continue

        flags.append({
            "flag_id":           make_id("FLAG", counter),
            "classified_id":     ch["classified_id"],
            "evidence_id":       ch["evidence_id"],
            "source_section":    ch["source_section"],
            "text":              ch["text"],
            "change_type":       ch["change_type"],
            "penalty_risk":      has_penalty,
            "short_window":      short_window,
            "days_to_deadline":  days,
            "is_irrelevant":     is_irrelevant,
            "high_impact":       high_impact,
            "flagged_at":        timestamp(),
        })
        counter += 1

    return flags


# ═══════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════

def run():
    validate_manifest()

    reg_file     = _find_regulation_file()
    source_label = f"input/{reg_file.name}"
    text         = _load_text(reg_file)

    # Step 3 first — evidence index is needed by all other steps
    evidence_index      = build_evidence_index(text, source_label)

    # Step 1 — classify every sentence in the evidence index
    classified_changes  = build_classified_changes(evidence_index)

    # Step 2 — build context packet with policy refs + jurisdiction scope
    metadata            = _extract_metadata(text, source_label)
    jurisdiction_scope  = _load_jurisdiction_scope()
    policy_refs         = _load_policy_references()
    context_packet      = build_context_packet(metadata, evidence_index, jurisdiction_scope, policy_refs)

    # Step 4 — flag risks and irrelevant items
    risk_flags          = build_risk_flags(classified_changes, metadata.get("effective_date", ""))

    write_json(OUTPUT_DIR / "context_packet.json",     context_packet)
    write_json(OUTPUT_DIR / "evidence_index.json",     evidence_index)
    write_json(OUTPUT_DIR / "classified_changes.json", classified_changes)
    write_json(OUTPUT_DIR / "risk_flags.json",         risk_flags)

    print(f"[agent_a] Evidence sections  : {len(evidence_index)}")
    print(f"[agent_a] Classified changes : {len(classified_changes)}")
    print(f"[agent_a] Risk flags         : {len(risk_flags)}")

    return context_packet, evidence_index, classified_changes, risk_flags


if __name__ == "__main__":
    run()
