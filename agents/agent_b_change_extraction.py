"""
Agent B - Change Extraction

Four responsibilities (aligned with Capstone Proposal):
  1. Structured Change Extraction      — convert unstructured regulatory publications
                                         into machine-readable requirement changes using
                                         multi-keyword obligation pattern matching across
                                         all change types (must, shall, required to, etc.)
  2. Confidence Scoring & Validation   — score each change on multiple factors; detect
                                         ambiguous regulatory language and flag it for
                                         legal review with specific ambiguity reasons
  3. Bounding Box Coordinates          — output page and character-offset position data
                                         for every extracted requirement, enabling source
                                         traceability and legal evidence verification;
                                         enriched with real page coords when PDF available
  4. Robust Multi-section Aggregation  — classify and aggregate changes across preamble,
                                         articles, and schedules ensuring full coverage
                                         across all document segments

Outputs:
  output/change_register.json
"""

import re
from pathlib import Path

from agents.utils import (
    INPUT_DIR, OUTPUT_DIR,
    read_json, write_json, make_id, timestamp,
    load_policy_pack,
)

BASE_DIR = Path(__file__).resolve().parents[1]


# ═══════════════════════════════════════════════════════════════════════════════
# CONSTANTS
# ═══════════════════════════════════════════════════════════════════════════════

# Obligation checks — ordered by specificity (longer phrases first)
# Each entry: (regex_pattern, confidence_boost)
_OBLIGATION_CHECKS: list[tuple[str, float]] = [
    (r"\bmust not\b",        0.14),   # negative prohibition
    (r"\bshall not\b",       0.14),   # negative prohibition
    (r"\bprohibited from\b", 0.12),   # negative prohibition
    (r"\bmust\b",            0.15),   # strongest positive obligation
    (r"\bshall\b",           0.15),   # strongest positive obligation
    (r"\bare required to\b", 0.13),   # positive obligation
    (r"\brequired to\b",     0.12),   # positive obligation
    (r"\bare required\b",    0.12),   # positive obligation
    (r"\bobligated to\b",    0.12),   # positive obligation
    (r"\bobligated\b",       0.10),   # positive obligation
    (r"\bprohibited\b",      0.10),   # prohibition (standalone)
    (r"\bforbidden\b",       0.08),   # prohibition (standalone)
]

# Temporal markers that increase specificity and confidence
_TEMPORAL_MARKERS = [
    r"\bwithin\s+\d+\s+(days?|hours?|minutes?|seconds?|months?|weeks?)\b",
    r"\bno later than\b",
    r"\bimmediately\b",
    r"\bby\b.{1,20}\bdeadline\b",
    r"\bevery\s+\d+\s+(days?|months?|years?)\b",
    r"\bat least\s+(once|twice|\d+)\b",
    r"\bprior to\b",
]

# Ambiguity patterns that lower confidence and trigger legal review
# Each entry: (regex_pattern, confidence_penalty, human_readable_label)
_AMBIGUITY_PATTERNS: list[tuple[str, float, str]] = [
    (r"\bmay\b(?!\s+not)",           0.10, "permissive 'may' — obligation unclear"),
    (r"\bcould\b",                   0.08, "uncertain 'could'"),
    (r"\bwhere\s+applicable\b",      0.10, "conditional scope — applicability undefined"),
    (r"\bas\s+appropriate\b",        0.08, "vague standard of care"),
    (r"\bin\s+certain\s+circumstances\b", 0.12, "undefined circumstances"),
    (r"\bwhere\s+possible\b",        0.10, "conditional effort — not binding"),
    (r"\bshould\b",                  0.08, "advisory 'should' — not mandatory"),
    (r"\bgenerally\b",               0.05, "non-binding 'generally'"),
    (r"\btypically\b",               0.05, "non-binding 'typically'"),
    (r"\bif\s+necessary\b",          0.08, "conditional trigger — undefined threshold"),
    (r"\breasonable\s+steps\b",      0.08, "vague standard — 'reasonable steps'"),
]

# Section segment classification patterns (checked against lowercased header)
_SEGMENT_PATTERNS: dict[str, list[str]] = {
    "preamble":  [r"^preamble\b", r"^whereas\b", r"^recital\s*\d*\b", r"^introduction\b", r"^background\b"],
    "schedule":  [r"^schedule\s+\w", r"^annex\s+\w", r"^appendix\s+\w", r"^exhibit\s+\w"],
    "article":   [r"^article\s+\d", r"^section\s+[\d.]+"],
}

# Chars per page estimate for TXT/HTML sources
_CHARS_PER_PAGE = 3000

# Synthetic fallback dataset used when real extraction yields no results
_SYNTHETIC_FALLBACK = [
    {
        "requirement":    "Financial institutions must complete enhanced due diligence for all high-risk clients within 30 days of onboarding.",
        "source_section": "Synthetic - Section 2.1 - Enhanced Due Diligence",
        "segment_type":   "article",
        "page":           1,
        "char_offset":    0,
    },
    {
        "requirement":    "Institutions must implement real-time transaction monitoring systems capable of flagging suspicious activity within 60 seconds.",
        "source_section": "Synthetic - Section 3.4 - Real-Time Transaction Monitoring",
        "segment_type":   "article",
        "page":           1,
        "char_offset":    200,
    },
    {
        "requirement":    "Institutions must verify and record beneficial ownership for all corporate clients within 14 days.",
        "source_section": "Synthetic - Section 4.7 - Beneficial Ownership Verification",
        "segment_type":   "article",
        "page":           2,
        "char_offset":    0,
    },
    {
        "requirement":    "Compliance teams must file suspicious activity reports within 24 hours of detection.",
        "source_section": "Synthetic - Section 5.2 - Suspicious Activity Reporting",
        "segment_type":   "article",
        "page":           2,
        "char_offset":    200,
    },
    {
        "requirement":    "All compliance staff must complete AML certification training every 6 months.",
        "source_section": "Synthetic - Section 6.1 - Staff Training and Certification",
        "segment_type":   "article",
        "page":           3,
        "char_offset":    0,
    },
]


# ═══════════════════════════════════════════════════════════════════════════════
# 4. ROBUST MULTI-SECTION AGGREGATION
# ═══════════════════════════════════════════════════════════════════════════════

def _classify_segment(section_header: str) -> str:
    """
    Classify a section header into one of: preamble | article | schedule | general.
    Enables multi-section aggregation across all document structures.
    """
    header_lower = section_header.strip().lower()
    for segment, patterns in _SEGMENT_PATTERNS.items():
        if any(re.match(p, header_lower) for p in patterns):
            return segment
    return "general"


def _split_sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]


def _has_obligation(text: str) -> bool:
    """Return True if the sentence contains any recognisable obligation keyword."""
    tl = text.lower()
    return any(re.search(pattern, tl) for pattern, _ in _OBLIGATION_CHECKS)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. STRUCTURED CHANGE EXTRACTION
# ═══════════════════════════════════════════════════════════════════════════════

def extract_changes(evidence_index: list, context_packet: dict) -> list:
    """
    Extract regulatory requirement changes from all evidence sections.

    Each evidence record represents one document segment (preamble/article/schedule).
    Multi-section aggregation ensures changes are captured and labelled across the
    full document structure, not only from the main body sections.
    """
    jurisdiction   = context_packet["metadata"].get("jurisdiction", "Unknown")
    effective_date = context_packet["metadata"].get("effective_date", "Unknown")
    changes        = []
    counter        = 1

    for evidence in evidence_index:
        excerpt        = evidence.get("text_excerpt", "")
        source_section = evidence.get("source_section", "")
        segment_type   = _classify_segment(source_section)
        base_page      = evidence.get("page_estimate", 1)

        sentences = _split_sentences(excerpt)
        char_cursor = 0

        for sentence in sentences:
            if not _has_obligation(sentence):
                char_cursor += len(sentence) + 1
                continue
            if len(sentence.split()) < 5:
                char_cursor += len(sentence) + 1
                continue

            confidence, legal_review, ambiguity_flags = _score_confidence(sentence)
            bounding_box = _compute_bounding_box(base_page, char_cursor, len(sentence))

            changes.append({
                "change_id":             make_id("CHG", counter),
                "requirement":           sentence,
                "jurisdiction":          jurisdiction,
                "effective_date":        effective_date,
                "source_section":        source_section,
                "segment_type":          segment_type,
                "evidence_id":           evidence.get("evidence_id"),
                "confidence":            confidence,
                "legal_review_required": legal_review,
                "ambiguity_flags":       ambiguity_flags,
                "bounding_box":          bounding_box,
                "extraction_method":     "rule_based",
                "extracted_at":          timestamp(),
            })
            counter += 1
            char_cursor += len(sentence) + 1

    return changes


# ═══════════════════════════════════════════════════════════════════════════════
# 2. CONFIDENCE SCORING & VALIDATION
# ═══════════════════════════════════════════════════════════════════════════════

def _score_confidence(sentence: str) -> tuple[float, bool, list[str]]:
    """
    Score extraction confidence for a single requirement sentence.

    Factors:
      + Obligation strength (must/shall → boost, required to → boost, etc.)
      + Temporal specificity (within N days/hours → temporal_marker_boost)
      + Sentence length / detail (>8 words → sentence_length_boost)
      - Ambiguous language (may / could / where applicable → penalty per flag)

    All numeric thresholds are driven by policy_pack.yaml change_extraction.confidence.
    Returns:
      confidence            : float clamped to [min_score, max_score]
      legal_review_required : True when confidence < legal_review_threshold OR ambiguity found
      ambiguity_flags       : list of human-readable ambiguity descriptions
    """
    cfg = load_policy_pack()["change_extraction"]["confidence"]
    tl = sentence.lower()
    score = cfg["base_score"]

    # Obligation strength — apply only the first (strongest) match
    for pattern, boost in _OBLIGATION_CHECKS:
        if re.search(pattern, tl):
            score += boost
            break

    # Temporal specificity boost
    if any(re.search(p, tl) for p in _TEMPORAL_MARKERS):
        score += cfg["temporal_marker_boost"]

    # Sentence length / specificity boost
    if len(sentence.split()) > 8:
        score += cfg["sentence_length_boost"]

    # Ambiguity penalties — accumulate all matching flags
    ambiguity_flags = []
    for pattern, penalty, label in _AMBIGUITY_PATTERNS:
        if re.search(pattern, tl):
            score -= penalty
            ambiguity_flags.append(label)

    score = round(max(cfg["min_score"], min(score, cfg["max_score"])), 2)
    legal_review = score < cfg["legal_review_threshold"] or len(ambiguity_flags) > 0

    return score, legal_review, ambiguity_flags


# ═══════════════════════════════════════════════════════════════════════════════
# 3. BOUNDING BOX COORDINATES
# ═══════════════════════════════════════════════════════════════════════════════

def _position_label(char_offset: int) -> str:
    """Estimate vertical position on page from character offset within the page."""
    ratio = (char_offset % _CHARS_PER_PAGE) / _CHARS_PER_PAGE
    if ratio < 0.33:
        return "top_third"
    if ratio < 0.66:
        return "middle"
    return "bottom_third"


def _compute_bounding_box(page: int, char_offset: int, char_length: int) -> dict:
    """
    Produce a bounding box descriptor for a text span.

    For TXT and HTML sources: character-offset based position estimate within the page.
    For PDF sources: same structure, optionally enriched by _enrich_with_pdf_bboxes().

    Fields:
      page               — page number (1-based)
      char_offset_start  — character offset from start of page content
      char_offset_end    — char_offset_start + length of requirement text
      position_estimate  — 'top_third' | 'middle' | 'bottom_third'
      source             — 'char_offset_estimate' | 'pypdf' (set by enrichment)
    """
    return {
        "page":              page,
        "char_offset_start": char_offset,
        "char_offset_end":   char_offset + char_length,
        "position_estimate": _position_label(char_offset),
        "source":            "char_offset_estimate",
    }


def _enrich_with_pdf_bboxes(changes: list, pdf_path: Path) -> list:
    """
    Attempt to refine bounding_box.page and offsets using pypdf page-level text.

    Matches each requirement against page text using the first 50 characters.
    Falls back silently if pypdf is unavailable or a match is not found.
    """
    try:
        from pypdf import PdfReader
        reader     = PdfReader(str(pdf_path))
        page_texts = [page.extract_text() or "" for page in reader.pages]

        for change in changes:
            target = change["requirement"]
            probe  = target[:50]
            for page_idx, page_text in enumerate(page_texts, start=1):
                pos = page_text.find(probe)
                if pos != -1:
                    change["bounding_box"]["page"]              = page_idx
                    change["bounding_box"]["char_offset_start"] = pos
                    change["bounding_box"]["char_offset_end"]   = pos + len(target)
                    change["bounding_box"]["position_estimate"] = _position_label(pos)
                    change["bounding_box"]["source"]            = "pypdf"
                    break
    except Exception:
        pass  # graceful degradation — original estimates remain intact

    return changes


# ═══════════════════════════════════════════════════════════════════════════════
# SYNTHETIC FALLBACK
# ═══════════════════════════════════════════════════════════════════════════════

def _build_synthetic_changes(context_packet: dict) -> list:
    """
    Return a minimal structured change register when real extraction yields nothing.
    Covers the core regulatory scenario so downstream agents can always proceed.
    """
    jurisdiction   = context_packet["metadata"].get("jurisdiction", "Unknown")
    effective_date = context_packet["metadata"].get("effective_date", "Unknown")
    changes = []

    for i, item in enumerate(_SYNTHETIC_FALLBACK, start=1):
        confidence, legal_review, flags = _score_confidence(item["requirement"])
        changes.append({
            "change_id":             make_id("CHG", i),
            "requirement":           item["requirement"],
            "jurisdiction":          jurisdiction,
            "effective_date":        effective_date,
            "source_section":        item["source_section"],
            "segment_type":          item["segment_type"],
            "evidence_id":           make_id("EV", i),
            "confidence":            confidence,
            "legal_review_required": legal_review,
            "ambiguity_flags":       flags,
            "bounding_box":          _compute_bounding_box(
                item["page"], item["char_offset"], len(item["requirement"])
            ),
            "extraction_method":     "synthetic_fallback",
            "extracted_at":          timestamp(),
        })

    return changes


# ═══════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════

def run():
    evidence_index = read_json(OUTPUT_DIR / "evidence_index.json", default=[])
    context_packet = read_json(OUTPUT_DIR / "context_packet.json", default={"metadata": {}})

    changes = extract_changes(evidence_index, context_packet)

    # Enrich bounding boxes with real PDF page positions when available
    pdf_files = list(INPUT_DIR.glob("*.pdf"))
    if pdf_files:
        changes = _enrich_with_pdf_bboxes(changes, pdf_files[0])

    # Synthetic fallback — ensures downstream agents always receive usable data
    if not changes:
        print("[agent_b] No obligations extracted — activating synthetic fallback.")
        changes = _build_synthetic_changes(context_packet)

    write_json(OUTPUT_DIR / "change_register.json", changes)

    legal_review_count = sum(1 for c in changes if c.get("legal_review_required"))
    segment_counts     = {}
    for c in changes:
        seg = c.get("segment_type", "general")
        segment_counts[seg] = segment_counts.get(seg, 0) + 1

    method = changes[0]["extraction_method"] if changes else "none"
    print(f"[agent_b] Changes extracted     : {len(changes)}  (method: {method})")
    print(f"[agent_b] Legal review required : {legal_review_count}")
    print(f"[agent_b] Segment breakdown     : {segment_counts}")

    return changes


if __name__ == "__main__":
    run()
