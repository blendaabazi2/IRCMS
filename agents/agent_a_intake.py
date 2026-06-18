"""
Agent A - Regulatory Feed Intake (Gatekeeper)

Four responsibilities:
  1. Regulatory Processing Gateway  — load TXT/PDF/HTML, classify each change type
  2. Context Packet Construction    — metadata + prior change history + policy references
                                      + jurisdiction scope + derived risk signals
  3. Universal Evidence Index       — link every change to its source paragraph (page + section)
  4. Risk Detection & Filtering     — flag penalty risks and short effective windows (< 60 days);
                                      filter irrelevant items from classified_changes output

Outputs:
  output/classified_changes.json   (relevant changes only — irrelevant items excluded)
  output/context_packet.json
  output/evidence_index.json
  output/risk_flags.json           (penalty + short-window + irrelevant flags)
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
    load_policy_pack,
)

BASE_DIR = Path(__file__).resolve().parents[1]


# ═══════════════════════════════════════════════════════════════════════════════
# MANIFEST VALIDATION
# ═══════════════════════════════════════════════════════════════════════════════

def validate_manifest() -> dict:
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

    manifest["generated_at"] = timestamp()
    with open(manifest_path, "w", encoding="utf-8") as f:
        yaml.dump(manifest, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    print(f"[agent_a] manifest.yaml validated — bundle_id: {manifest.get('bundle_id')}")
    return manifest


# ═══════════════════════════════════════════════════════════════════════════════
# 1. REGULATORY PROCESSING GATEWAY
# ═══════════════════════════════════════════════════════════════════════════════

_CHANGE_TYPE_PATTERNS: dict[str, list[str]] = {
    "new_requirement": [r"\bmust\b", r"\bshall\b", r"\brequired to\b", r"\bare required\b", r"\bobligated\b"],
    "amendment":       [r"\bamended\b", r"\bupdated\b", r"\bmodified\b", r"\breplaced by\b"],
    "revocation":      [r"\brevoked\b", r"\bsuperseded\b", r"\bno longer applies\b", r"\bnull and void\b"],
    "clarification":   [r"\bclarif\w+\b", r"\bfor the purposes of\b", r"\bmeans\b", r"\bdefined as\b"],
    "guidance":        [r"\bshould\b", r"\brecommend\b", r"\bencourage\b", r"\bbest practice\b"],
}


def _find_regulation_file() -> Path:
    for pattern in ("*.txt", "*.pdf", "*.html", "*.htm"):
        matches = list(INPUT_DIR.glob(pattern))
        if matches:
            return matches[0]
    raise FileNotFoundError("No regulation file found in input/ (expected .txt, .pdf, or .html)")


def _normalize_pdf_text(text: str) -> str:
    """
    Clean up common pypdf extraction artifacts so downstream regex patterns
    work reliably on PDF-sourced text.
    """
    # Soft-hyphen line breaks: "institu-\ntion" → "institution"
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)
    # Common ligatures that pypdf may leave un-decoded
    for old, new in [("ﬁ", "fi"), ("ﬂ", "fl"), ("ﬀ", "ff"), ("ﬃ", "ffi"), ("ﬄ", "ffl")]:
        text = text.replace(old, new)
    # Collapse runs of spaces/tabs while keeping newlines
    text = re.sub(r"[ \t]+", " ", text)
    # Reduce three or more blank lines to two
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _load_text(path: Path) -> str:
    suffix = path.suffix.lower()

    if suffix == ".pdf":
        try:
            from pypdf import PdfReader
            reader = PdfReader(str(path))
            pages = [page.extract_text() or "" for page in reader.pages]
            raw = "\n".join(pages)
            return _normalize_pdf_text(raw)
        except ImportError:
            print("[agent_a] pypdf not installed — reading PDF as raw text.")
            return path.read_text(encoding="utf-8", errors="ignore")

    if suffix in (".html", ".htm"):
        import html as _html
        raw = path.read_text(encoding="utf-8", errors="ignore")
        # Remove script/style blocks first, then strip all tags
        raw = re.sub(r"<(script|style)[^>]*>.*?</(script|style)>", " ", raw, flags=re.DOTALL | re.IGNORECASE)
        stripped = re.sub(r"<[^>]+>", " ", raw)
        # Collapse whitespace while preserving paragraph breaks
        stripped = re.sub(r"[ \t]+", " ", stripped)
        stripped = re.sub(r"\n{3,}", "\n\n", stripped)
        return _html.unescape(stripped).strip()

    return read_text_file(path)


def _classify_change_type(text: str) -> str:
    tl = text.lower()
    for change_type, patterns in _CHANGE_TYPE_PATTERNS.items():
        if any(re.search(p, tl) for p in patterns):
            return change_type
    return "general"


def build_classified_changes(evidence_index: list) -> list:
    """
    Classify each sentence in the evidence index into a typed change record.
    Returns ALL sentences (relevant and irrelevant) so that risk filtering
    can inspect the full set. Caller filters irrelevant items before writing.
    """
    classified = []
    counter = 1
    for ev in evidence_index:
        sentences = re.split(r"(?<=[.!?])\s+", ev.get("text_excerpt", ""))
        for sentence in sentences:
            stripped = sentence.strip()
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


def _load_change_history() -> list:
    """
    Load prior run metadata from existing context_packet.json if present.
    Enables the system to track re-runs and build an incremental change history.
    """
    path = OUTPUT_DIR / "context_packet.json"
    if not path.exists():
        return []
    try:
        prev = json.loads(path.read_text(encoding="utf-8"))
        meta = prev.get("metadata", {})
        return [{
            "run_at":         meta.get("processed_at", "Unknown"),
            "document":       meta.get("document_title", "Unknown"),
            "jurisdiction":   meta.get("jurisdiction", "Unknown"),
            "evidence_count": prev.get("evidence_count", 0),
            "status":         prev.get("status", "completed"),
        }]
    except Exception:
        return []


def _derive_risk_signals(text: str) -> list:
    """Extract risk signal keywords actually present in the document."""
    keywords = load_policy_pack()["risk_detection"]["risk_signal_keywords"]
    tl = text.lower()
    return [kw for kw in keywords if kw in tl]


def build_context_packet(
    metadata: dict,
    evidence_index: list,
    jurisdiction_scope: dict,
    policy_refs: list,
    change_history: list,
    risk_signals: list,
    filtered_count: int = 0,
) -> dict:
    return {
        "context_packet_id":   "CTX-001",
        "metadata":            metadata,
        "jurisdiction_scope":  jurisdiction_scope,
        "policy_references":   policy_refs,
        "evidence_count":      len(evidence_index),
        "risk_signals":        risk_signals,
        "change_history":      change_history,
        "filtered_irrelevant": filtered_count,
        "status":              "created",
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 3. UNIVERSAL EVIDENCE INDEX
# ═══════════════════════════════════════════════════════════════════════════════

# Matches regulatory section headers across common document styles.
# Order: more specific multi-word forms before bare keywords.
_SECTION_SPLIT_RE = re.compile(
    r"\n(?=(?:Section|Article|Clause|Chapter|Rule|Part|Regulation|Annex|Schedule|Appendix)\s+[\d.]+)",
    re.IGNORECASE,
)

_SECTION_START_RE = re.compile(
    r"^(?:Section|Article|Clause|Chapter|Rule|Part|Regulation|Annex|Schedule|Appendix)\s+[\d.]+",
    re.IGNORECASE,
)


def _build_evidence_by_paragraphs(text: str, source_file: str) -> list:
    """
    Fallback for PDFs with no recognisable section headers.
    Each substantial paragraph becomes one evidence record labelled "Paragraph N".
    Paragraphs shorter than 8 words (page numbers, footers, etc.) are skipped.
    """
    paragraphs = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]
    evidence   = []
    char_offset = 0
    counter    = 1

    for para in paragraphs:
        if len(para.split()) < 8:
            char_offset += len(para) + 2
            continue
        evidence.append({
            "evidence_id":      make_id("EV", counter),
            "source_section":   f"Paragraph {counter}",
            "source_file":      source_file,
            "paragraph_number": 1,
            "page_estimate":    max(1, char_offset // 3000 + 1),
            "text_excerpt":     para,
            "content_hash":     stable_hash(para),
        })
        char_offset += len(para) + 2
        counter += 1

    return evidence


def build_evidence_index(text: str, source_file: str) -> list:
    """
    Split document on section headers (Section / Article / Clause / Chapter /
    Rule / Part / Regulation / Annex / Schedule / Appendix + number).
    Each paragraph within a section becomes a separate evidence record.

    Falls back to paragraph-based splitting when no recognised headers are found
    (common in raw PDF extractions without structural markup).
    """
    sections = _SECTION_SPLIT_RE.split(text)

    # If no section-style headers were detected, use paragraph fallback
    if not any(_SECTION_START_RE.match(s.strip()) for s in sections):
        return _build_evidence_by_paragraphs(text, source_file)

    evidence    = []
    char_offset = 0
    counter     = 1

    for section in sections:
        stripped = section.strip()
        if not _SECTION_START_RE.match(stripped):
            char_offset += len(section)
            continue

        lines      = stripped.splitlines()
        first_line = lines[0].strip()
        body       = "\n".join(lines[1:]).strip()

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

_IRRELEVANT_PATTERNS = [
    r"^\s*$",
    r"^section\s+[\d.]+\s*[-–]",
    r"^(regulatory publication|jurisdiction|regulator|effective date)\s*:",
]


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
    Inspect ALL classified changes (including irrelevant items) and flag those that:
      - contain penalty / enforcement language
      - fall within the configured short_window_days effective window
      - are structurally irrelevant (headers, label lines)

    Items are flagged here, not removed from the pipeline. classified_changes.json
    is separately filtered to exclude irrelevant items.
    """
    rd = load_policy_pack()["risk_detection"]
    penalty_keywords   = rd["penalty_keywords"]
    short_window_days  = rd["short_window_days"]

    days = _days_until(effective_date)
    flags = []
    counter = 1

    for ch in classified_changes:
        tl = ch["text"].lower()

        has_penalty   = any(kw in tl for kw in penalty_keywords)
        short_window  = days is not None and days < short_window_days
        is_irrel      = _is_irrelevant(ch["text"])
        high_impact   = ch["change_type"] == "new_requirement" and (has_penalty or short_window)

        if not (has_penalty or short_window or is_irrel or high_impact):
            continue

        flags.append({
            "flag_id":          make_id("FLAG", counter),
            "classified_id":    ch["classified_id"],
            "evidence_id":      ch["evidence_id"],
            "source_section":   ch["source_section"],
            "text":             ch["text"],
            "change_type":      ch["change_type"],
            "penalty_risk":     has_penalty,
            "short_window":     short_window,
            "days_to_deadline": days,
            "is_irrelevant":    is_irrel,
            "high_impact":      high_impact,
            "flagged_at":       timestamp(),
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

    # Step 3 — evidence index (needed by all other steps)
    evidence_index = build_evidence_index(text, source_label)

    # Step 1 — classify every sentence (all items, including irrelevant)
    all_classified = build_classified_changes(evidence_index)

    # Filter irrelevant items from the output — they appear only in risk_flags
    classified_changes = [c for c in all_classified if not _is_irrelevant(c["text"])]
    filtered_count = len(all_classified) - len(classified_changes)

    # Step 2 — build context packet
    metadata           = _extract_metadata(text, source_label)
    jurisdiction_scope = _load_jurisdiction_scope()
    policy_refs        = _load_policy_references()
    change_history     = _load_change_history()
    risk_signals       = _derive_risk_signals(text)

    context_packet = build_context_packet(
        metadata, evidence_index, jurisdiction_scope, policy_refs,
        change_history, risk_signals, filtered_count,
    )

    # Step 4 — flag risks (inspects ALL items, including irrelevant)
    risk_flags = build_risk_flags(all_classified, metadata.get("effective_date", ""))

    write_json(OUTPUT_DIR / "context_packet.json",     context_packet)
    write_json(OUTPUT_DIR / "evidence_index.json",     evidence_index)
    write_json(OUTPUT_DIR / "classified_changes.json", classified_changes)
    write_json(OUTPUT_DIR / "risk_flags.json",         risk_flags)

    print(f"[agent_a] Evidence sections  : {len(evidence_index)}")
    print(f"[agent_a] Classified changes : {len(classified_changes)} (filtered {filtered_count} irrelevant)")
    print(f"[agent_a] Risk flags         : {len(risk_flags)}")
    print(f"[agent_a] Risk signals found : {risk_signals}")
    print(f"[agent_a] Prior runs in hist : {len(change_history)}")

    return context_packet, evidence_index, classified_changes, risk_flags


if __name__ == "__main__":
    run()
