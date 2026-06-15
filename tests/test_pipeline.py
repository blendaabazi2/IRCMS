"""
IRCMS Pipeline Tests
Tests that each agent produces the correct output structure and required fields.
Run with: python -m pytest tests/ -v
"""

import json
import sys
from pathlib import Path

import pytest

# Make sure project root is on the path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OUTPUT_DIR = ROOT / "output"
INPUT_DIR  = ROOT / "input"


# ── Helpers ───────────────────────────────────────────────────────────────────

def load(filename):
    path = OUTPUT_DIR / filename
    assert path.exists(), f"Missing output file: {filename} — run python run_pipeline.py first"
    return json.loads(path.read_text(encoding="utf-8"))


def as_list(raw, key):
    if isinstance(raw, list):
        return raw
    return raw.get(key, [])


# ── Agent A Tests ─────────────────────────────────────────────────────────────

class TestAgentA:
    def test_context_packet_exists(self):
        data = load("context_packet.json")
        assert data, "context_packet.json is empty"

    def test_context_packet_required_fields(self):
        data = load("context_packet.json")
        for field in ["context_packet_id", "metadata", "jurisdiction_scope"]:
            assert field in data, f"Missing field: {field}"

    def test_context_packet_metadata(self):
        meta = load("context_packet.json")["metadata"]
        for field in ["document_title", "jurisdiction", "effective_date", "processed_at"]:
            assert field in meta, f"Missing metadata field: {field}"

    def test_evidence_index_exists(self):
        data = load("evidence_index.json")
        assert isinstance(data, list), "evidence_index.json should be a list"
        assert len(data) > 0, "evidence_index.json is empty"

    def test_evidence_index_fields(self):
        records = load("evidence_index.json")
        for rec in records:
            assert "evidence_id" in rec, "Evidence record missing evidence_id"
            assert "source_file" in rec, "Evidence record missing source_file"

    def test_change_register_exists(self):
        data = load("change_register.json")
        assert isinstance(data, list), "change_register.json should be a list"
        assert len(data) > 0, "change_register.json is empty"


# ── Agent B Tests ─────────────────────────────────────────────────────────────

class TestAgentB:
    def test_change_register_required_fields(self):
        changes = load("change_register.json")
        for change in changes:
            for field in ["change_id", "requirement", "source_section",
                          "effective_date", "jurisdiction", "evidence_id"]:
                assert field in change, f"Change missing field: {field}"

    def test_change_ids_unique(self):
        changes = load("change_register.json")
        ids = [c["change_id"] for c in changes]
        assert len(ids) == len(set(ids)), "Duplicate change_ids found"

    def test_evidence_ids_reference_index(self):
        changes = load("change_register.json")
        evidence = load("evidence_index.json")
        ev_ids = {e["evidence_id"] for e in evidence}
        for c in changes:
            assert c["evidence_id"] in ev_ids, (
                f"change {c['change_id']} references unknown evidence_id {c['evidence_id']}"
            )


# ── Agent C Tests ─────────────────────────────────────────────────────────────

class TestAgentC:
    def test_gap_analysis_exists(self):
        data = load("gap_analysis.json")
        assert data, "gap_analysis.json is empty"

    def test_gaps_is_list(self):
        raw = load("gap_analysis.json")
        gaps = as_list(raw, "gaps")
        assert len(gaps) > 0, "No gaps found in gap_analysis.json"

    def test_gap_required_fields(self):
        raw  = load("gap_analysis.json")
        gaps = as_list(raw, "gaps")
        for gap in gaps:
            for field in ["gap_id", "change_id", "policy_area",
                          "gap_status", "severity", "confidence"]:
                assert field in gap, f"Gap missing field: {field}"

    def test_gap_severity_valid(self):
        raw  = load("gap_analysis.json")
        gaps = as_list(raw, "gaps")
        valid = {"Critical", "High", "Medium", "Low"}
        for gap in gaps:
            assert gap["severity"] in valid, f"Invalid severity: {gap['severity']}"

    def test_gap_confidence_range(self):
        raw  = load("gap_analysis.json")
        gaps = as_list(raw, "gaps")
        for gap in gaps:
            assert 0.0 <= float(gap["confidence"]) <= 1.0, (
                f"Confidence out of range: {gap['confidence']}"
            )

    def test_gap_ids_unique(self):
        raw  = load("gap_analysis.json")
        gaps = as_list(raw, "gaps")
        ids  = [g["gap_id"] for g in gaps]
        assert len(ids) == len(set(ids)), "Duplicate gap_ids found"


# ── Agent D Tests ─────────────────────────────────────────────────────────────

class TestAgentD:
    def test_impact_assessment_exists(self):
        data = load("impact_assessment.json")
        assert data, "impact_assessment.json is empty"

    def test_assessments_list(self):
        raw         = load("impact_assessment.json")
        assessments = as_list(raw, "assessments")
        assert len(assessments) > 0, "No assessments found"

    def test_assessment_required_fields(self):
        raw         = load("impact_assessment.json")
        assessments = as_list(raw, "assessments")
        for a in assessments:
            for field in ["impact_id", "gap_id", "system_impact_score",
                          "regulatory_risk_score", "priority", "deadline_risk"]:
                assert field in a, f"Assessment missing field: {field}"

    def test_system_impact_score_range(self):
        raw         = load("impact_assessment.json")
        assessments = as_list(raw, "assessments")
        for a in assessments:
            assert 1 <= int(a["system_impact_score"]) <= 5, (
                f"system_impact_score out of range: {a['system_impact_score']}"
            )

    def test_regulatory_risk_score_range(self):
        raw         = load("impact_assessment.json")
        assessments = as_list(raw, "assessments")
        for a in assessments:
            assert 0 <= int(a["regulatory_risk_score"]) <= 100, (
                f"regulatory_risk_score out of range: {a['regulatory_risk_score']}"
            )

    def test_every_gap_has_assessment(self):
        raw_gaps    = load("gap_analysis.json")
        gaps        = as_list(raw_gaps, "gaps")
        raw_impacts = load("impact_assessment.json")
        assessments = as_list(raw_impacts, "assessments")
        assessed_gap_ids = {a["gap_id"] for a in assessments}
        for gap in gaps:
            assert gap["gap_id"] in assessed_gap_ids, (
                f"Gap {gap['gap_id']} has no impact assessment"
            )


# ── Agent E Tests ─────────────────────────────────────────────────────────────

class TestAgentE:
    def test_control_mapping_exists(self):
        data = load("control_mapping.json")
        assert isinstance(data, list), "control_mapping.json should be a list"
        assert len(data) > 0, "control_mapping.json is empty"

    def test_mapping_required_fields(self):
        mappings = load("control_mapping.json")
        for m in mappings:
            for field in ["mapping_id", "gap_id", "change_id", "control_id",
                          "mapping_status", "owner", "recommendation",
                          "effort_estimate", "evidence_requirements",
                          "cross_jurisdiction_overlap"]:
                assert field in m, f"Mapping missing field: {field}"

    def test_mapping_status_valid(self):
        mappings = load("control_mapping.json")
        valid = {"Existing control mapped", "New control required"}
        for m in mappings:
            assert m["mapping_status"] in valid, (
                f"Invalid mapping_status: {m['mapping_status']}"
            )

    def test_effort_estimate_valid(self):
        mappings = load("control_mapping.json")
        valid = {"Low", "Medium", "High"}
        for m in mappings:
            assert m["effort_estimate"] in valid, (
                f"Invalid effort_estimate: {m['effort_estimate']}"
            )

    def test_evidence_requirements_is_list(self):
        mappings = load("control_mapping.json")
        for m in mappings:
            assert isinstance(m["evidence_requirements"], list), (
                f"evidence_requirements should be a list in {m['mapping_id']}"
            )
            assert len(m["evidence_requirements"]) > 0, (
                f"evidence_requirements is empty in {m['mapping_id']}"
            )

    def test_cross_jurisdiction_overlap_is_bool(self):
        mappings = load("control_mapping.json")
        for m in mappings:
            assert isinstance(m["cross_jurisdiction_overlap"], bool), (
                f"cross_jurisdiction_overlap should be bool in {m['mapping_id']}"
            )

    def test_every_gap_has_mapping(self):
        raw_gaps = load("gap_analysis.json")
        gaps     = as_list(raw_gaps, "gaps")
        mappings = load("control_mapping.json")
        mapped_gap_ids = {m["gap_id"] for m in mappings}
        for gap in gaps:
            assert gap["gap_id"] in mapped_gap_ids, (
                f"Gap {gap['gap_id']} has no control mapping"
            )

    def test_mapping_ids_unique(self):
        mappings = load("control_mapping.json")
        ids = [m["mapping_id"] for m in mappings]
        assert len(ids) == len(set(ids)), "Duplicate mapping_ids found"


# ── Agent H Tests ─────────────────────────────────────────────────────────────

class TestAgentH:
    def test_remediation_plan_exists(self):
        path = OUTPUT_DIR / "remediation_plan.md"
        assert path.exists(), "remediation_plan.md not generated"
        assert path.read_text(encoding="utf-8").strip(), "remediation_plan.md is empty"

    def test_exceptions_exists(self):
        path = OUTPUT_DIR / "exceptions.md"
        assert path.exists(), "exceptions.md not generated"
        assert path.read_text(encoding="utf-8").strip(), "exceptions.md is empty"

    def test_audit_log_exists(self):
        path = OUTPUT_DIR / "audit_log.md"
        assert path.exists(), "audit_log.md not generated"

    def test_approval_packet_required_fields(self):
        data = load("approval_packet.json")
        for field in ["project", "summary", "high_risk_gaps",
                      "approval_required", "routing_summary", "metrics_reference"]:
            assert field in data, f"approval_packet missing field: {field}"

    def test_routing_summary_has_all_categories(self):
        data = load("approval_packet.json")
        categories = [
            "Compliance Lead Escalation",
            "Legal Review",
            "Control Owner Review",
            "Policy Owner Remediation",
        ]
        routing = data.get("routing_summary", {})
        for cat in categories:
            assert cat in routing, f"routing_summary missing category: {cat}"

    def test_metrics_required_fields(self):
        data = load("metrics.json")
        for field in ["total_changes", "total_gaps", "gap_rate", "high_risk_gaps",
                      "matched_controls", "new_controls_required",
                      "traceability_enabled", "deterministic_rerun_ready"]:
            assert field in data, f"metrics.json missing field: {field}"

    def test_metrics_gap_rate_consistent(self):
        data = load("metrics.json")
        expected = round(data["total_gaps"] / data["total_changes"], 2) if data["total_changes"] else 0
        assert data["gap_rate"] == expected, (
            f"gap_rate {data['gap_rate']} != expected {expected}"
        )

    def test_traceability_enabled(self):
        data = load("metrics.json")
        assert data["traceability_enabled"] is True

    def test_deterministic_rerun_flag(self):
        data = load("metrics.json")
        assert data["deterministic_rerun_ready"] is True


# ── End-to-end traceability test ──────────────────────────────────────────────

class TestTraceability:
    def test_change_to_gap_to_mapping_chain(self):
        """Every change → gap → mapping chain must be complete."""
        changes  = load("change_register.json")
        raw_gaps = load("gap_analysis.json")
        gaps     = as_list(raw_gaps, "gaps")
        mappings = load("control_mapping.json")

        change_ids     = {c["change_id"] for c in changes}
        gap_change_ids = {g["change_id"] for g in gaps}
        map_gap_ids    = {m["gap_id"]    for m in mappings}
        gap_ids        = {g["gap_id"]    for g in gaps}

        # Every gap must reference a known change
        for gid in gap_change_ids:
            assert gid in change_ids, f"Gap references unknown change_id: {gid}"

        # Every mapping must reference a known gap
        for mid in map_gap_ids:
            assert mid in gap_ids, f"Mapping references unknown gap_id: {mid}"
