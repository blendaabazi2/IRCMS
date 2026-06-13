"""
Run the full IRCMS 6-agent pipeline.
"""

from agents import agent_a_intake
from agents import agent_b_change_extraction
from agents import agent_c_gap_analysis
from agents import agent_d_impact_assessment
from agents import agent_e_control_mapping
from agents import agent_h_orchestrator


def main():
    print("Running Agent A - Regulatory Feed Intake...")
    agent_a_intake.run()

    print("Running Agent B - Change Extraction...")
    agent_b_change_extraction.run()

    print("Running Agent C - Gap Analysis...")
    agent_c_gap_analysis.run()

    print("Running Agent D - Impact Assessment...")
    agent_d_impact_assessment.run()

    print("Running Agent E - Control Mapping...")
    agent_e_control_mapping.run()

    print("Running Agent H - Exception Triage & Orchestration...")
    agent_h_orchestrator.run()

    print("Pipeline completed. Check the output/ folder.")


if __name__ == "__main__":
    main()
