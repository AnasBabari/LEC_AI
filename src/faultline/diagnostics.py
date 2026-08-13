"""Evidence Ledger and Diagnostic Tool Adapters for Faultline."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from faultline.models import (
    ComponentEnum,
    EvidenceObservation,
    HealthDimension,
    HealthStatus,
    ReliabilityLevel,
    SourceGroup,
)


class EvidenceLedger:
    """Per-investigation append-only ledger providing sequential, immutable evidence IDs."""

    def __init__(self, incident_at: datetime) -> None:
        self.incident_at = incident_at
        self._observations: list[EvidenceObservation] = []
        self._next_id = 1

    def append_observation(
        self,
        source_group: SourceGroup,
        source: str,
        component: ComponentEnum,
        signal: str,
        dimension: HealthDimension,
        status: HealthStatus,
        value: float,
        unit: str,
        observed_at: datetime,
        window_duration_seconds: int,
        scope: str,
        reliability: ReliabilityLevel,
        details: str,
    ) -> EvidenceObservation:
        """Append a new observation and assign a sequential, immutable EV-xxx ID."""
        evidence_id = f"EV-{self._next_id:03d}"
        self._next_id += 1

        window_end = observed_at
        window_start = observed_at - timedelta(seconds=window_duration_seconds)

        obs = EvidenceObservation(
            id=evidence_id,
            source_group=source_group,
            source=source,
            component=component,
            signal=signal,
            dimension=dimension,
            status=status,
            value=value,
            unit=unit,
            observed_at=observed_at,
            window_start=window_start,
            window_end=window_end,
            scope=scope,
            reliability=reliability,
            details=details,
        )
        self._observations.append(obs)
        return obs

    def record_raw(self, observation: EvidenceObservation) -> None:
        """Record an existing EvidenceObservation directly into the ledger."""
        self._observations.append(observation)

    def get_observations(self) -> list[EvidenceObservation]:
        """Return snapshot of all recorded observations."""
        return list(self._observations)

    def get_observation_ids(self) -> set[str]:
        """Return set of all valid observation IDs recorded in this ledger."""
        return {obs.id for obs in self._observations}

    def get_by_id(self, evidence_id: str) -> Optional[EvidenceObservation]:
        """Look up observation by EV-xxx ID."""
        for obs in self._observations:
            if obs.id == evidence_id:
                return obs
        return None

    def get_by_source_group(self, source_group: SourceGroup) -> list[EvidenceObservation]:
        """Return all observations belonging to a source group."""
        return [obs for obs in self._observations if obs.source_group == source_group]

    def get_by_component(self, component: ComponentEnum) -> list[EvidenceObservation]:
        """Return all observations for a specific component."""
        return [obs for obs in self._observations if obs.component == component]

    @property
    def successful_source_groups(self) -> set[SourceGroup]:
        """Set of unique source groups with recorded observations."""
        return {obs.source_group for obs in self._observations}


class ScenarioRepository:
    """Loads and provides access to scenario fixtures."""

    def __init__(self, data_dir: Optional[Path] = None) -> None:
        if data_dir is None:
            self.data_dir = Path(__file__).resolve().parents[2] / "data"
        else:
            self.data_dir = data_dir
        self.scenarios_dir = (self.data_dir / "scenarios").resolve()

    def list_scenarios(self) -> list[dict[str, Any]]:
        """List all available scenario metadata."""
        results: list[dict[str, Any]] = []
        if not self.scenarios_dir.exists():
            return results
        for path in sorted(self.scenarios_dir.glob("*.json")):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                results.append(
                    {
                        "id": data["id"],
                        "title": data["title"],
                        "description": data["description"],
                        "affected_components": data["affected_components"],
                    }
                )
        return results

    def get_scenario(self, scenario_id: str) -> dict[str, Any]:
        """Load a specific scenario fixture by ID with path-traversal protection."""
        import re

        if not re.match(r"^[a-zA-Z0-9_-]+$", scenario_id):
            raise ValueError(f"Invalid scenario ID format: '{scenario_id}'")

        file_path = (self.scenarios_dir / f"{scenario_id}.json").resolve()
        if not str(file_path).startswith(str(self.scenarios_dir)):
            raise ValueError(f"Scenario path traversal detected: '{scenario_id}'")

        if not file_path.exists():
            raise FileNotFoundError(f"Scenario '{scenario_id}' not found at {file_path}")
        with open(file_path, "r", encoding="utf-8") as f:
            data: dict[str, Any] = json.load(f)
            return data


class DiagnosticService:
    """Executes diagnostic queries against scenario fixtures and records observations to the ledger."""

    def __init__(self, scenario_data: dict[str, Any], ledger: EvidenceLedger) -> None:
        self.scenario_data = scenario_data
        self.ledger = ledger
        self.incident_at = self._parse_iso_timestamp(scenario_data["incident_at"])

    @staticmethod
    def _parse_iso_timestamp(ts_str: str) -> datetime:
        """Parse ISO timestamp ensuring UTC timezone awareness."""
        dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt

    def _resolve_observation_time(self, offset_minutes: int) -> datetime:
        """Calculate observation timestamp anchored to scenario incident time."""
        return self.incident_at + timedelta(minutes=offset_minutes)

    def query_telemetry(
        self,
        component: Optional[str] = None,
        dimension: Optional[str] = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Query time-series telemetry metrics across system components."""
        raw_items = self.scenario_data.get("diagnostics", {}).get("telemetry", [])
        new_records = []

        for item in raw_items:
            if component and item["component"] != component:
                continue
            if dimension and item["dimension"] != dimension:
                continue

            observed_at = self._resolve_observation_time(item["offset_minutes"])
            obs = self.ledger.append_observation(
                source_group=SourceGroup.TELEMETRY,
                source="query_telemetry",
                component=ComponentEnum(item["component"]),
                signal=item["signal"],
                dimension=HealthDimension(item["dimension"]),
                status=HealthStatus(item["status"]),
                value=float(item["value"]),
                unit=item["unit"],
                observed_at=observed_at,
                window_duration_seconds=int(item["window_duration_seconds"]),
                scope=item["scope"],
                reliability=ReliabilityLevel(item["reliability"]),
                details=item["details"],
            )
            new_records.append(obs)

        return {
            "source_group": SourceGroup.TELEMETRY.value,
            "observations_count": len(new_records),
            "records": [r.model_dump(mode="json") for r in new_records],
            "summary": f"Retrieved {len(new_records)} telemetry metrics across {len(set(r.component for r in new_records))} components.",
        }

    def run_health_probes(
        self,
        component: Optional[str] = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Run synthetic point-in-time health probes and pings."""
        raw_items = self.scenario_data.get("diagnostics", {}).get("health_probe", [])
        new_records = []

        for item in raw_items:
            if component and item["component"] != component:
                continue

            observed_at = self._resolve_observation_time(item["offset_minutes"])
            obs = self.ledger.append_observation(
                source_group=SourceGroup.HEALTH_PROBE,
                source="run_health_probes",
                component=ComponentEnum(item["component"]),
                signal=item["signal"],
                dimension=HealthDimension(item["dimension"]),
                status=HealthStatus(item["status"]),
                value=float(item["value"]),
                unit=item["unit"],
                observed_at=observed_at,
                window_duration_seconds=int(item["window_duration_seconds"]),
                scope=item["scope"],
                reliability=ReliabilityLevel(item["reliability"]),
                details=item["details"],
            )
            new_records.append(obs)

        return {
            "source_group": SourceGroup.HEALTH_PROBE.value,
            "observations_count": len(new_records),
            "records": [r.model_dump(mode="json") for r in new_records],
            "summary": f"Executed synthetic health probes: {len(new_records)} probe results recorded.",
        }

    def fetch_operational_events(
        self,
        component: Optional[str] = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Fetch worker lifecycle heartbeats, queue depths, and operational logs."""
        raw_items = self.scenario_data.get("diagnostics", {}).get("operational_events", [])
        new_records = []

        for item in raw_items:
            if component and item["component"] != component:
                continue

            observed_at = self._resolve_observation_time(item["offset_minutes"])
            obs = self.ledger.append_observation(
                source_group=SourceGroup.OPERATIONAL_EVENTS,
                source="fetch_operational_events",
                component=ComponentEnum(item["component"]),
                signal=item["signal"],
                dimension=HealthDimension(item["dimension"]),
                status=HealthStatus(item["status"]),
                value=float(item["value"]),
                unit=item["unit"],
                observed_at=observed_at,
                window_duration_seconds=int(item["window_duration_seconds"]),
                scope=item["scope"],
                reliability=ReliabilityLevel(item["reliability"]),
                details=item["details"],
            )
            new_records.append(obs)

        return {
            "source_group": SourceGroup.OPERATIONAL_EVENTS.value,
            "observations_count": len(new_records),
            "records": [r.model_dump(mode="json") for r in new_records],
            "summary": f"Retrieved {len(new_records)} operational event records.",
        }
