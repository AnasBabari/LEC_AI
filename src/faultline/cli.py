"""Command Line Interface for Faultline."""

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from faultline.diagnostics import ScenarioRepository
from faultline.gemini import FakeGeminiProvider, GeminiProvider, LLMProviderProtocol
from faultline.orchestrator import IncidentOrchestrator
from faultline.reasoning import PolicyEngine

# Load .env file if present
load_dotenv()


def format_terminal_report(res_dict: dict) -> str:
    """Format an AnalysisResult JSON dict into a human-readable terminal report."""
    lines = []
    lines.append("=" * 80)
    lines.append("   FAULTLINE — OPERATIONAL INCIDENT DIAGNOSTIC & REPAIR RANKING REPORT")
    lines.append("=" * 80)
    lines.append(f"Run ID:        {res_dict['run_id']}")
    lines.append(f"Scenario:      {res_dict['scenario_id']}")
    lines.append(f"Lifecycle:     {res_dict['state']} (Validation Passed: {res_dict['validation_passed']})")
    lines.append(
        f"Runtime Model: {res_dict['model_execution']['model_used']} (Thinking: {res_dict['model_execution']['thinking_level']})"
    )
    lines.append("-" * 80)

    # Incident Alert
    inc = res_dict["incident"]
    lines.append("\n[1] INITIAL FAULT ALERT:")
    lines.append(f"    Headline: {inc['headline']}")
    lines.append(f"    Severity: {inc['severity']} | Reported At: {inc['reported_at']}")
    lines.append(f"    Details:  {inc['details']}")

    # Evidence Ledger
    lines.append("\n[2] APPEND-ONLY EVIDENCE LEDGER (Collected Across Independent Sources):")
    lines.append(f"    {'ID':<8} {'GROUP':<20} {'COMPONENT':<15} {'STATUS':<10} {'SIGNAL & VALUE'}")
    lines.append(f"    {'-' * 7} {'-' * 18} {'-' * 13} {'-' * 8} {'-' * 30}")
    for obs in res_dict["evidence"]:
        val_str = f"{obs['signal']} = {obs['value']} {obs['unit']}"
        lines.append(
            f"    {obs['id']:<8} {obs['source_group']:<20} {obs['component']:<15} {obs['status']:<10} {val_str}"
        )

    # Conflicts
    lines.append("\n[3] DETECTED CONTRADICTIONS & SCOPE TENSIONS:")
    for c in res_dict["conflicts"]:
        lines.append(f"    * [{c['id']}] {c['conflict_type']} on {c['component']}:")
        lines.append(f"      - Headline:    {c['headline']}")
        lines.append(f"      - Evidence:    {', '.join(c['evidence_ids'])}")
        lines.append(f"      - Implication: {c['operational_implication']}")

    # Hypotheses
    lines.append("\n[4] EVALUATED ROOT-CAUSE HYPOTHESES (Deterministic Scoring):")
    for hyp in res_dict["hypotheses"]:
        lines.append(f"    * {hyp['name']} [{hyp['strength_band']}]")
        lines.append(
            f"      - Net Score:       {hyp['net_evidence_score']} (Support: {hyp['supporting_score']}, Oppose: {hyp['opposing_score']})"
        )
        lines.append(f"      - Decision Weight: {hyp['decision_weight']}% (*Policy-derived weight, not probability)")
        lines.append(f"      - Summary:         {hyp['summary']}")

    # Strategy Ranking
    lines.append("\n[5] 4-DIMENSIONAL REPAIR STRATEGY RANKING:")
    lines.append(
        f"    {'RANK':<6} {'STRATEGY NAME':<45} {'IMPACT (60%)':<14} {'SAFETY (20%)':<14} {'SPEED (15%)':<12} {'COST (5%)':<10} {'FINAL SCORE'}"
    )
    lines.append(f"    {'-' * 4} {'-' * 43} {'-' * 12} {'-' * 12} {'-' * 10} {'-' * 8} {'-' * 11}")
    for s in res_dict["strategy_ranking"]:
        lines.append(
            f"    #{s['rank']:<5} {s['name']:<45} {s['expected_impact']:<14.1f} {s['safety']:<14.1f} {s['speed']:<12.1f} {s['affordability']:<10.1f} {s['final_score']:<11.1f}"
        )

    # Recommendation
    rec = res_dict["recommendation"]
    lines.append("\n[6] EXECUTIVE TRADE-OFF DEFENSE & JUSTIFICATION:")
    lines.append(f"    Executive Summary: {rec['executive_summary']}")
    alt = rec["trade_off_comparison"]
    lines.append(
        f"    Trade-Off Defense: Why #{res_dict['strategy_ranking'][0]['rank']} beats {alt['alternative_strategy_name']}:"
    )
    lines.append(f"      - Alternative Advantage: {alt['alternative_advantage']}")
    lines.append(f"      - Rejection Rationale:   {alt['rejection_rationale']}")
    lines.append(f"    Contradiction Analysis:    {rec['grounded_contradiction_analysis']}")
    if rec.get("remaining_uncertainties"):
        lines.append(f"    Remaining Uncertainties:   {', '.join(rec['remaining_uncertainties'])}")

    # Execution Boundary
    lines.append("\n[7] OPERATOR SAFETY BOUNDARY:")
    lines.append(f"    Status:                    {res_dict['execution']['execution_status'].upper()}")
    lines.append(f"    Operator Approval Req'd:   {res_dict['execution']['operator_approval_required']}")
    lines.append(f"    Suggested Action Command:  {res_dict['execution']['suggested_command']}")
    lines.append("    Note:                      Illustrative remediation stub — never executed by Faultline.")
    lines.append("=" * 80)
    return "\n".join(lines)


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Faultline Incident Decision-Support CLI")
    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # analyze command
    analyze_parser = subparsers.add_parser("analyze", help="Analyze an incident scenario")
    analyze_parser.add_argument(
        "--scenario",
        default="cache_invalidation_lag",
        help="Scenario ID to investigate (default: cache_invalidation_lag)",
    )
    analyze_parser.add_argument(
        "--offline", action="store_true", help="Run in deterministic offline mode with FakeGeminiProvider"
    )
    analyze_parser.add_argument("--json", action="store_true", help="Output raw JSON analysis")
    analyze_parser.add_argument("--output-file", type=str, help="Save report output to file")

    # list command
    subparsers.add_parser("list-scenarios", help="List available incident scenarios")

    args = parser.parse_args()

    if args.command == "list-scenarios":
        repo = ScenarioRepository()
        scenarios = repo.list_scenarios()
        print(f"Available scenarios ({len(scenarios)}):")
        for s in scenarios:
            print(f"  - [{s['id']}] {s['title']}")
        return

    if args.command == "analyze" or args.command is None:
        scenario_id = getattr(args, "scenario", "cache_invalidation_lag")
        api_key = os.getenv("GEMINI_API_KEY")
        use_offline = getattr(args, "offline", False) or os.getenv("FAULTLINE_OFFLINE", "").lower() in ("true", "1")
        provider: LLMProviderProtocol
        if use_offline or not api_key:
            provider = FakeGeminiProvider()
        else:
            provider = GeminiProvider(api_key=api_key)
        policy = PolicyEngine()
        repo = ScenarioRepository()
        orchestrator = IncidentOrchestrator(provider=provider, policy=policy, scenario_repo=repo)

        try:
            result = orchestrator.analyze_scenario(scenario_id)
            res_dict = result.model_dump(mode="json")

            if getattr(args, "json", False):
                out_content = json.dumps(res_dict, indent=2)
            else:
                out_content = format_terminal_report(res_dict)

            print(out_content)

            output_file = getattr(args, "output_file", None)
            if output_file:
                Path(output_file).parent.mkdir(parents=True, exist_ok=True)
                with open(output_file, "w", encoding="utf-8") as f:
                    f.write(json.dumps(res_dict, indent=2) if output_file.endswith(".json") else out_content)
                print(f"\nSaved report to: {output_file}")

        except Exception as e:
            print(f"Error executing analysis: {e}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()
