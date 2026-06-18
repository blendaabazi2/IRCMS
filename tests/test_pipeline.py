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

    def test_routing_summary_valid_categories(self):
        data = load("approval_packet.json")
        valid = {
            "Compliance Lead Escalation",
            "Legal Review",
            "Control Owner Review",
            "Policy Owner Remediation",
        }
        routing = data.get("routing_summary", {})
        assert len(routing) > 0, "routing_summary is empty"
        for cat in routing:
            assert cat in valid, f"routing_summary contains unknown category: {cat}"

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


# ── Findings Report Tests (findings_schema.json) ──────────────────────────────

class TestFindingsReport:
    def test_findings_report_exists(self):
        data = load("findings_report.json")
        assert data, "findings_report.json is empty"

    def test_schema_version(self):
        data = load("findings_report.json")
        assert data.get("schema_version") == "1.0", "schema_version must be '1.0'"

    def test_top_level_required_fields(self):
        data = load("findings_report.json")
        for field in ["schema_version", "run_id", "generated_at", "agent_source",
                      "regulation_source", "jurisdiction", "summary", "findings"]:
            assert field in data, f"findings_report.json missing top-level field: {field}"

    def test_run_id_matches_context(self):
        report  = load("findings_report.json")
        context = load("context_packet.json")
        assert report["run_id"] == context["context_packet_id"], (
            "findings_report run_id does not match context_packet_id"
        )

    def test_findings_is_list(self):
        data = load("findings_report.json")
        assert isinstance(data["findings"], list), "findings must be a list"
        assert len(data["findings"]) > 0, "findings list is empty"

    def test_finding_ids_unique(self):
        data = load("findings_report.json")
        ids  = [f["finding_id"] for f in data["findings"]]
        assert len(ids) == len(set(ids)), "Duplicate finding_ids in findings_report"

    def test_finding_required_fields(self):
        data = load("findings_report.json")
        required = [
            "finding_id", "change_id", "gap_id", "policy_area",
            "finding_type", "status", "severity", "confidence",
            "finding_description", "evidence_pointer", "current_state",
            "required_state", "remediation", "human_oversight",
            "downstream_links", "analytics_tags", "metadata",
        ]
        for finding in data["findings"]:
            for field in required:
                assert field in finding, (
                    f"Finding {finding.get('finding_id')} missing field: {field}"
                )

    def test_evidence_pointer_mandatory(self):
        """Every finding must have a populated evidence_pointer with evidence_id and source_quote."""
        data = load("findings_report.json")
        for finding in data["findings"]:
            ep = finding["evidence_pointer"]
            for field in ["evidence_id", "source_section", "source_file", "source_quote", "content_hash"]:
                assert field in ep, (
                    f"Finding {finding['finding_id']} evidence_pointer missing: {field}"
                )
            assert ep["evidence_id"], (
                f"Finding {finding['finding_id']} has empty evidence_id"
            )
            assert ep["source_quote"], (
                f"Finding {finding['finding_id']} has empty source_quote — traceability broken"
            )

    def test_human_oversight_present(self):
        data = load("findings_report.json")
        for finding in data["findings"]:
            ho = finding["human_oversight"]
            assert "review_required" in ho, (
                f"Finding {finding['finding_id']} missing human_oversight.review_required"
            )
            assert isinstance(ho["review_required"], bool), (
                f"review_required must be bool in {finding['finding_id']}"
            )

    def test_confidence_range(self):
        data = load("findings_report.json")
        for finding in data["findings"]:
            c = float(finding["confidence"])
            assert 0.0 <= c <= 1.0, (
                f"Confidence out of range [{c}] in {finding['finding_id']}"
            )

    def test_severity_valid(self):
        data  = load("findings_report.json")
        valid = {"Critical", "High", "Medium", "Low"}
        for finding in data["findings"]:
            assert finding["severity"] in valid, (
                f"Invalid severity '{finding['severity']}' in {finding['finding_id']}"
            )

    def test_finding_type_valid(self):
        data  = load("findings_report.json")
        valid = {"gap", "control_gap", "impact", "exception"}
        for finding in data["findings"]:
            assert finding["finding_type"] in valid, (
                f"Invalid finding_type '{finding['finding_type']}' in {finding['finding_id']}"
            )

    def test_status_valid(self):
        data  = load("findings_report.json")
        valid = {"Non-compliant", "Partial", "Needs Review", "Compliant", "Escalated", "Auto-closed"}
        for finding in data["findings"]:
            assert finding["status"] in valid, (
                f"Invalid status '{finding['status']}' in {finding['finding_id']}"
            )

    def test_downstream_links_present(self):
        data = load("findings_report.json")
        for finding in data["findings"]:
            dl = finding["downstream_links"]
            for field in ["control_id", "impact_id", "mapping_id", "exception_category"]:
                assert field in dl, (
                    f"Finding {finding['finding_id']} downstream_links missing: {field}"
                )

    def test_analytics_tags_is_list(self):
        data = load("findings_report.json")
        for finding in data["findings"]:
            assert isinstance(finding["analytics_tags"], list), (
                f"analytics_tags must be a list in {finding['finding_id']}"
            )
            assert len(finding["analytics_tags"]) > 0, (
                f"analytics_tags is empty in {finding['finding_id']}"
            )

    def test_summary_totals_consistent(self):
        data    = load("findings_report.json")
        summary = data["summary"]
        assert summary["total_findings"] == len(data["findings"]), (
            "summary.total_findings does not match actual findings count"
        )

    def test_summary_severity_counts_consistent(self):
        data      = load("findings_report.json")
        by_sev    = data["summary"]["by_severity"]
        computed  = {"Critical": 0, "High": 0, "Medium": 0, "Low": 0}
        for f in data["findings"]:
            sev = f["severity"]
            if sev in computed:
                computed[sev] += 1
        assert by_sev == computed, (
            f"summary.by_severity {by_sev} does not match computed {computed}"
        )

    def test_human_review_count_consistent(self):
        data     = load("findings_report.json")
        expected = sum(1 for f in data["findings"] if f["human_oversight"]["review_required"])
        assert data["summary"]["human_review_required_count"] == expected, (
            f"human_review_required_count {data['summary']['human_review_required_count']} "
            f"!= computed {expected}"
        )

    def test_gap_id_references_gap_analysis(self):
        """Each finding.gap_id must reference a real gap in gap_analysis.json."""
        report   = load("findings_report.json")
        raw_gaps = load("gap_analysis.json")
        gap_ids  = {g["gap_id"] for g in as_list(raw_gaps, "gaps")}
        for f in report["findings"]:
            assert f["gap_id"] in gap_ids, (
                f"Finding {f['finding_id']} references unknown gap_id {f['gap_id']}"
            )

    def test_change_id_references_change_register(self):
        """Each finding.change_id must reference a real change in change_register.json."""
        report     = load("findings_report.json")
        changes    = load("change_register.json")
        change_ids = {c["change_id"] for c in changes}
        for f in report["findings"]:
            assert f["change_id"] in change_ids, (
                f"Finding {f['finding_id']} references unknown change_id {f['change_id']}"
            )


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
