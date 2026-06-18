# IRCMS - Intelligent Regulatory Change Management System

This project implements a 6-agent compliance pipeline for regulatory change management.

## Project Goal
IRCMS takes a regulatory document or change bundle as input, extracts regulatory changes, compares them against current policies, assesses impact, maps controls, triages exceptions, and produces audit-ready outputs.

## Required 6 Agents
1. Agent A - Regulatory Feed Intake
2. Agent B - Change Extraction
3. Agent C - Gap Analysis
4. Agent D - Impact Assessment
5. Agent E - Control Mapping
6. Agent H - Exception Triage & Orchestration

## Folder Structure
```text
IRCMS/
├── agents/
├── config/
├── input/
├── output/
├── dashboard/
├── notebooks/
├── tests/
├── run_pipeline.py
├── requirements.txt
└── README.md
```

## Main Deliverables
The pipeline generates:

```text
context_packet.json
evidence_index.json
change_register.json
gap_analysis.json
impact_assessment.json
control_mapping.json
remediation_plan.md
exceptions.md
approval_packet.json
audit_log.md
metrics.json
```

## How to Run Locally
Install dependencies:

```bash
pip install -r requirements.txt
```

Run the full pipeline:

```bash
python run_pipeline.py
```

Run dashboard:

```bash
streamlit run dashboard/streamlit_app.py
```
