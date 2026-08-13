# Faultline

**Faultline** is an evidence-driven decision-support agent that diagnoses operational incidents with conflicting diagnostic signals and ranks competing repair strategies with defensible written justifications.

## Features
- **Deterministic Provenance**: Per-investigation immutable evidence ledger (`EV-001`, `EV-002`, ...).
- **Conflict Classification**: Distinguishes direct contradictions, scope tensions, and temporal conflicts.
- **Evidence-Strength Scoring**: Reliability, freshness, and directness scoring with per-source-group caps to prevent correlated telemetry bias.
- **4D Strategy Ranking**: Weighted evaluation across Expected Impact (60%), Safety (20%), Recovery Speed (15%), and Affordability (5%).
- **Strict Validation**: Asserts invariants before any recommendation reaches operators.
- **Operator Safety Boundary**: Explicit `operator_approval_required=True` with no autonomous unverified execution.

## Quickstart
See installation and execution guides in the documentation.
