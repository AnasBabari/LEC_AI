"""Procedural Realistic Incident Synthesis Engine for Faultline.

Generates realistic, physically plausible distributed system outages on the fly across:
- API Gateway
- Redis Cache
- Message Queue
- PostgreSQL Database
- Worker Pools

Each generated incident synthesizes:
- Dynamic timestamps anchored to real or offset time.
- Realistic telemetry streams with physical jitter and metric correlations.
- Direct health probes vs workload scope tensions (contradictions).
- Operational events, worker logs, and background noise.
"""

import random
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from faultline.models import (
    ComponentEnum,
    HealthDimension,
    HealthStatus,
    ReliabilityLevel,
)


class IncidentSynthesisEngine:
    """Generates realistic distributed system incidents on demand with randomized variability."""

    ARCHETYPES = [
        "CACHE_INVALIDATION_CONSUMER_STALLED",
        "DATABASE_INDEX_REGRESSION",
        "FLASH_SALE_SURGE",
        "CACHE_CLUSTER_OUTAGE",
        "REPLICA_REPLICATION_LAG",
        "DATABASE_CAPACITY_DEGRADATION",
    ]

    ARCHETYPE_METADATA = {
        "CACHE_INVALIDATION_CONSUMER_STALLED": {
            "title": "Cache Invalidation Consumer Stall & DB Cascading Load",
            "description": "Message queue consumer for cache invalidation events has halted. Stale cache entries trigger a query cascade, saturating the database connection pool.",
            "affected_components": ["message_queue", "cache", "database", "api_gateway"],
            "primary_cause": "CACHE_INVALIDATION_CONSUMER_STALLED",
            "expected_repair": "RECOVER_CONSUMER_AND_DRAIN",
        },
        "DATABASE_INDEX_REGRESSION": {
            "title": "Missing Database Index & Query Latency Degradation",
            "description": "A database index was dropped or bypassed after a migration. Direct health probes pass instantly, but real user queries stall under full table scans.",
            "affected_components": ["database", "api_gateway"],
            "primary_cause": "DATABASE_INDEX_REGRESSION",
            "expected_repair": "REBUILD_DATABASE_INDEX",
        },
        "FLASH_SALE_SURGE": {
            "title": "Extreme Traffic Surge & Ingress Gateway Saturation",
            "description": "Unexpected spike in user checkout requests overwhelms the API Gateway and worker threads, causing request timeouts and 5xx errors.",
            "affected_components": ["api_gateway", "database"],
            "primary_cause": "FLASH_SALE_SURGE",
            "expected_repair": "THROTTLE_TRAFFIC",
        },
        "CACHE_CLUSTER_OUTAGE": {
            "title": "Redis Cache Cluster Failover & Stampede",
            "description": "Primary Redis cache node experienced a transient crash and failover. Connection dropouts and cache misses cause an immediate stampede to PostgreSQL.",
            "affected_components": ["cache", "database", "api_gateway"],
            "primary_cause": "CACHE_CLUSTER_OUTAGE",
            "expected_repair": "RESTART_CACHE",
        },
        "REPLICA_REPLICATION_LAG": {
            "title": "Database Replica Synchronization Lag & Stale Reads",
            "description": "High write volumes on the primary database lead to severe replication lag on read replicas, surfacing stale data reads and retry loops.",
            "affected_components": ["database", "api_gateway"],
            "primary_cause": "REPLICA_REPLICATION_LAG",
            "expected_repair": "THROTTLE_TRAFFIC",
        },
        "DATABASE_CAPACITY_DEGRADATION": {
            "title": "Database Connection Pool & Lock Contention Exhaustion",
            "description": "Unoptimized long-running database transactions hold exclusive locks, exhausting all connection pools and bringing API response times to a standstill.",
            "affected_components": ["database", "api_gateway"],
            "primary_cause": "DATABASE_CAPACITY_DEGRADATION",
            "expected_repair": "THROTTLE_TRAFFIC",
        },
    }

    def __init__(self, seed: Optional[int] = None) -> None:
        self.rng = random.Random(seed)

    def generate_incident(
        self,
        archetype: Optional[str] = None,
        incident_time: Optional[datetime] = None,
        incident_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Generate a complete, fully populated incident fixture with realistic variability."""
        if archetype is None or archetype not in self.ARCHETYPE_METADATA:
            archetype = self.rng.choice(self.ARCHETYPES)

        meta = self.ARCHETYPE_METADATA[archetype]
        if incident_time is None:
            incident_time = datetime.now(timezone.utc) - timedelta(minutes=self.rng.randint(5, 25))
        elif incident_time.tzinfo is None:
            incident_time = incident_time.replace(tzinfo=timezone.utc)

        if incident_id is None:
            rand_suffix = self.rng.randint(1000, 9999)
            incident_id = f"inc_{archetype.lower()}_{rand_suffix}"

        telemetry = self._generate_telemetry(archetype)
        health_probes = self._generate_health_probes(archetype)
        operational_events = self._generate_operational_events(archetype)

        reported_time = incident_time + timedelta(seconds=self.rng.randint(15, 60))

        initial_fault = {
            "source": self.rng.choice(["pagerduty_alert", "datadog_apm_alert", "cloudwatch_alarm"]),
            "severity": "CRITICAL",
            "headline": f"{meta['title']} ({', '.join(meta['affected_components'][:2])})",
            "reported_at": reported_time.isoformat(),
            "details": meta["description"],
        }

        return {
            "id": incident_id,
            "title": meta["title"],
            "description": meta["description"],
            "affected_components": meta["affected_components"],
            "incident_at": incident_time.isoformat(),
            "initial_fault_report": initial_fault,
            "diagnostics": {
                "telemetry": telemetry,
                "health_probe": health_probes,
                "operational_events": operational_events,
            },
            "ground_truth": {
                "root_cause": meta["primary_cause"],
                "recommended_strategy": meta["expected_repair"],
            },
        }

    def _generate_telemetry(self, archetype: str) -> list[dict[str, Any]]:
        """Synthesize time-series telemetry items with metric jitter."""
        items: list[dict[str, Any]] = []

        # 1. API Gateway Telemetry
        if archetype == "FLASH_SALE_SURGE":
            gw_p99 = round(self.rng.uniform(2800.0, 4800.0), 1)
            gw_err = round(self.rng.uniform(14.0, 28.0), 1)
            gw_tput = round(self.rng.uniform(14000.0, 28000.0), 1)
            items.append({
                "component": ComponentEnum.API_GATEWAY.value,
                "signal": "gateway_throughput",
                "dimension": HealthDimension.THROUGHPUT.value,
                "status": HealthStatus.DEGRADED.value,
                "value": gw_tput,
                "unit": "req/sec",
                "offset_minutes": -self.rng.randint(1, 4),
                "window_duration_seconds": 300,
                "scope": "workload",
                "reliability": ReliabilityLevel.VERIFIED.value,
                "details": f"API Gateway request throughput surged past ingress limit at {gw_tput} req/sec.",
            })
        elif archetype == "CACHE_INVALIDATION_CONSUMER_STALLED":
            gw_p99 = round(self.rng.uniform(2100.0, 3200.0), 1)
            gw_err = round(self.rng.uniform(6.0, 14.0), 1)
        elif archetype == "DATABASE_INDEX_REGRESSION":
            gw_p99 = round(self.rng.uniform(2400.0, 4200.0), 1)
            gw_err = round(self.rng.uniform(5.0, 12.0), 1)
        elif archetype == "CACHE_CLUSTER_OUTAGE":
            gw_p99 = round(self.rng.uniform(1900.0, 3100.0), 1)
            gw_err = round(self.rng.uniform(8.0, 16.0), 1)
        else:
            gw_p99 = round(self.rng.uniform(2000.0, 3600.0), 1)
            gw_err = round(self.rng.uniform(8.0, 18.0), 1)
            gw_tput = round(self.rng.uniform(2400.0, 4800.0), 1)
            items.append({
                "component": ComponentEnum.API_GATEWAY.value,
                "signal": "gateway_throughput",
                "dimension": HealthDimension.THROUGHPUT.value,
                "status": HealthStatus.HEALTHY.value,
                "value": gw_tput,
                "unit": "req/sec",
                "offset_minutes": -self.rng.randint(1, 4),
                "window_duration_seconds": 300,
                "scope": "workload",
                "reliability": ReliabilityLevel.VERIFIED.value,
                "details": f"API Gateway request throughput normal at {gw_tput} req/sec.",
            })

        items.append({
            "component": ComponentEnum.API_GATEWAY.value,
            "signal": "http_p99_latency_ms",
            "dimension": HealthDimension.LATENCY.value,
            "status": HealthStatus.DEGRADED.value,
            "value": gw_p99,
            "unit": "ms",
            "offset_minutes": -self.rng.randint(2, 6),
            "window_duration_seconds": 300,
            "scope": "workload",
            "reliability": ReliabilityLevel.VERIFIED.value,
            "details": f"API Gateway p99 response time degraded to {gw_p99}ms under current user load.",
        })

        items.append({
            "component": ComponentEnum.API_GATEWAY.value,
            "signal": "http_5xx_rate_pct",
            "dimension": HealthDimension.AVAILABILITY.value,
            "status": HealthStatus.DEGRADED.value if gw_err > 5.0 else HealthStatus.HEALTHY.value,
            "value": gw_err,
            "unit": "%",
            "offset_minutes": -self.rng.randint(1, 4),
            "window_duration_seconds": 300,
            "scope": "workload",
            "reliability": ReliabilityLevel.VERIFIED.value,
            "details": f"API Gateway 5xx error rate measured at {gw_err}%.",
        })

        # 2. Redis Cache Telemetry
        if archetype == "CACHE_INVALIDATION_CONSUMER_STALLED":
            cache_hit = round(self.rng.uniform(28.0, 42.0), 1)
            cache_stale = round(self.rng.uniform(35.0, 58.0), 1)
            items.append({
                "component": ComponentEnum.CACHE.value,
                "signal": "cache_hit_ratio_pct",
                "dimension": HealthDimension.AVAILABILITY.value,
                "status": HealthStatus.DEGRADED.value,
                "value": cache_hit,
                "unit": "%",
                "offset_minutes": -self.rng.randint(3, 8),
                "window_duration_seconds": 300,
                "scope": "workload",
                "reliability": ReliabilityLevel.VERIFIED.value,
                "details": f"Redis cache hit ratio dropped to {cache_hit}% due to stale invalidation keys.",
            })
            items.append({
                "component": ComponentEnum.CACHE.value,
                "signal": "stale_read_rate_pct",
                "dimension": HealthDimension.FRESHNESS.value,
                "status": HealthStatus.DEGRADED.value,
                "value": cache_stale,
                "unit": "%",
                "offset_minutes": -self.rng.randint(2, 6),
                "window_duration_seconds": 300,
                "scope": "workload",
                "reliability": ReliabilityLevel.VERIFIED.value,
                "details": f"Stale cache key read rate elevated at {cache_stale}%.",
            })
        elif archetype == "CACHE_CLUSTER_OUTAGE":
            cache_hit = round(self.rng.uniform(10.0, 25.0), 1)
            items.append({
                "component": ComponentEnum.CACHE.value,
                "signal": "cache_hit_ratio_pct",
                "dimension": HealthDimension.AVAILABILITY.value,
                "status": HealthStatus.FAILED.value,
                "value": cache_hit,
                "unit": "%",
                "offset_minutes": -self.rng.randint(4, 9),
                "window_duration_seconds": 300,
                "scope": "workload",
                "reliability": ReliabilityLevel.VERIFIED.value,
                "details": f"Redis cluster hit ratio collapsed to {cache_hit}% following node drop.",
            })
        else:
            cache_hit = round(self.rng.uniform(88.0, 96.0), 1)
            items.append({
                "component": ComponentEnum.CACHE.value,
                "signal": "cache_hit_ratio_pct",
                "dimension": HealthDimension.AVAILABILITY.value,
                "status": HealthStatus.HEALTHY.value,
                "value": cache_hit,
                "unit": "%",
                "offset_minutes": -self.rng.randint(4, 10),
                "window_duration_seconds": 300,
                "scope": "workload",
                "reliability": ReliabilityLevel.VERIFIED.value,
                "details": f"Redis cache hit ratio healthy at {cache_hit}%.",
            })

        # 3. Database Telemetry (Workload Scope)
        if archetype == "DATABASE_INDEX_REGRESSION":
            scan_rate = round(self.rng.uniform(380.0, 680.0), 1)
            items.append({
                "component": ComponentEnum.DATABASE.value,
                "signal": "database_table_scan_rate",
                "dimension": HealthDimension.QUERY_EFFICIENCY.value,
                "status": HealthStatus.DEGRADED.value,
                "value": scan_rate,
                "unit": "scans/sec",
                "offset_minutes": -self.rng.randint(1, 4),
                "window_duration_seconds": 300,
                "scope": "workload",
                "reliability": ReliabilityLevel.VERIFIED.value,
                "details": f"High sequential full table scan rate detected on 'orders' table ({scan_rate} scans/sec).",
            })
        elif archetype == "REPLICA_REPLICATION_LAG":
            rep_lag = float(self.rng.randint(90, 240))
            items.append({
                "component": ComponentEnum.DATABASE.value,
                "signal": "replica_lag_seconds",
                "dimension": HealthDimension.FRESHNESS.value,
                "status": HealthStatus.DEGRADED.value,
                "value": rep_lag,
                "unit": "seconds",
                "offset_minutes": -self.rng.randint(1, 4),
                "window_duration_seconds": 300,
                "scope": "workload",
                "reliability": ReliabilityLevel.VERIFIED.value,
                "details": f"Replication stream delay between primary database and read replicas reached {rep_lag} seconds.",
            })
        else:
            if archetype == "DATABASE_CAPACITY_DEGRADATION":
                db_load = round(self.rng.uniform(95.0, 99.8), 1)
                db_lat = round(self.rng.uniform(2800.0, 4800.0), 1)
            elif archetype == "CACHE_INVALIDATION_CONSUMER_STALLED":
                db_load = round(self.rng.uniform(88.0, 96.0), 1)
                db_lat = round(self.rng.uniform(1400.0, 2600.0), 1)
            else:
                db_load = round(self.rng.uniform(80.0, 92.0), 1)
                db_lat = round(self.rng.uniform(800.0, 2200.0), 1)

            items.append({
                "component": ComponentEnum.DATABASE.value,
                "signal": "connection_pool_load_pct",
                "dimension": HealthDimension.LATENCY.value,
                "status": HealthStatus.DEGRADED.value if db_load > 80.0 else HealthStatus.HEALTHY.value,
                "value": db_load,
                "unit": "%",
                "offset_minutes": -self.rng.randint(2, 6),
                "window_duration_seconds": 300,
                "scope": "workload",
                "reliability": ReliabilityLevel.VERIFIED.value,
                "details": f"PostgreSQL active connection pool utilization saturated at {db_load}%.",
            })

            items.append({
                "component": ComponentEnum.DATABASE.value,
                "signal": "workload_query_latency_ms",
                "dimension": HealthDimension.LATENCY.value,
                "status": HealthStatus.DEGRADED.value if db_lat > 500.0 else HealthStatus.HEALTHY.value,
                "value": db_lat,
                "unit": "ms",
                "offset_minutes": -self.rng.randint(1, 5),
                "window_duration_seconds": 300,
                "scope": "workload",
                "reliability": ReliabilityLevel.VERIFIED.value,
                "details": f"Application query execution latency averaged {db_lat}ms across active connections.",
            })


        # 4. Message Queue Telemetry
        if archetype == "CACHE_INVALIDATION_CONSUMER_STALLED":
            mq_backlog = float(self.rng.randint(32000, 58000))
            items.append({
                "component": ComponentEnum.MESSAGE_QUEUE.value,
                "signal": "invalidation_queue_backlog_count",
                "dimension": HealthDimension.BACKLOG.value,
                "status": HealthStatus.DEGRADED.value,
                "value": mq_backlog,
                "unit": "messages",
                "offset_minutes": -self.rng.randint(3, 8),
                "window_duration_seconds": 300,
                "scope": "workload",
                "reliability": ReliabilityLevel.VERIFIED.value,
                "details": f"Cache invalidation queue backlog accumulated to {int(mq_backlog):,} unconsumed messages.",
            })
        elif archetype == "FLASH_SALE_SURGE":
            mq_backlog = float(self.rng.randint(15000, 30000))
            items.append({
                "component": ComponentEnum.MESSAGE_QUEUE.value,
                "signal": "order_processing_queue_backlog",
                "dimension": HealthDimension.BACKLOG.value,
                "status": HealthStatus.DEGRADED.value,
                "value": mq_backlog,
                "unit": "messages",
                "offset_minutes": -self.rng.randint(2, 5),
                "window_duration_seconds": 300,
                "scope": "workload",
                "reliability": ReliabilityLevel.VERIFIED.value,
                "details": f"Order processing queue backlog elevated at {int(mq_backlog):,} messages.",
            })
        else:
            items.append({
                "component": ComponentEnum.MESSAGE_QUEUE.value,
                "signal": "queue_backlog_count",
                "dimension": HealthDimension.BACKLOG.value,
                "status": HealthStatus.HEALTHY.value,
                "value": float(self.rng.randint(50, 400)),
                "unit": "messages",
                "offset_minutes": -self.rng.randint(4, 12),
                "window_duration_seconds": 300,
                "scope": "workload",
                "reliability": ReliabilityLevel.VERIFIED.value,
                "details": "Message queue depth healthy with normal consumption rate.",
            })

        return items

    def _generate_health_probes(self, archetype: str) -> list[dict[str, Any]]:
        """Synthesize direct health probes creating realistic scope tensions."""
        items: list[dict[str, Any]] = []

        # Database Direct Synthetic Probe
        if archetype == "DATABASE_CAPACITY_DEGRADATION":
            probe_lat = round(self.rng.uniform(3200.0, 5800.0), 1)
            probe_status = HealthStatus.DEGRADED.value
            probe_details = f"Direct database health probe latency severely elevated to {probe_lat}ms due to capacity exhaustion."
        else:
            # Scope tension: Direct ping is healthy (1.2ms - 2.8ms), while user workload is degraded!
            probe_lat = round(self.rng.uniform(1.2, 2.8), 1)
            probe_status = HealthStatus.HEALTHY.value
            probe_details = f"Direct database synthetic ping passed in {probe_lat}ms (engine is responsive to point queries)."

        items.append({
            "component": ComponentEnum.DATABASE.value,
            "signal": "synthetic_ping_latency_ms",
            "dimension": HealthDimension.LATENCY.value,
            "status": probe_status,
            "value": probe_lat,
            "unit": "ms",
            "offset_minutes": -self.rng.randint(1, 3),
            "window_duration_seconds": 60,
            "scope": "synthetic_probe",
            "reliability": ReliabilityLevel.VERIFIED.value,
            "details": probe_details,
        })

        # Cache Direct Health Probe
        if archetype == "CACHE_CLUSTER_OUTAGE":
            cache_lat = round(self.rng.uniform(450.0, 1500.0), 1)
            cache_status = HealthStatus.FAILED.value
            cache_details = f"Redis ping probe timed out after {cache_lat}ms on primary node."
        else:
            cache_lat = round(self.rng.uniform(0.4, 1.1), 1)
            cache_status = HealthStatus.HEALTHY.value
            cache_details = f"Redis synthetic ping passed in {cache_lat}ms."

        items.append({
            "component": ComponentEnum.CACHE.value,
            "signal": "synthetic_ping_latency_ms",
            "dimension": HealthDimension.LATENCY.value,
            "status": cache_status,
            "value": cache_lat,
            "unit": "ms",
            "offset_minutes": -self.rng.randint(1, 3),
            "window_duration_seconds": 60,
            "scope": "synthetic_probe",
            "reliability": ReliabilityLevel.VERIFIED.value,
            "details": cache_details,
        })

        # Message Queue Worker Health Probe
        if archetype == "CACHE_INVALIDATION_CONSUMER_STALLED":
            items.append({
                "component": ComponentEnum.MESSAGE_QUEUE.value,
                "signal": "consumer_heartbeat_status",
                "dimension": HealthDimension.AVAILABILITY.value,
                "status": HealthStatus.FAILED.value,
                "value": 0.0,
                "unit": "status",
                "offset_minutes": -self.rng.randint(2, 6),
                "window_duration_seconds": 60,
                "scope": "worker_probe",
                "reliability": ReliabilityLevel.VERIFIED.value,
                "details": "Cache invalidation worker consumer heartbeat missed for >300s. Process appears frozen.",
            })
        else:
            items.append({
                "component": ComponentEnum.MESSAGE_QUEUE.value,
                "signal": "consumer_heartbeat_status",
                "dimension": HealthDimension.AVAILABILITY.value,
                "status": HealthStatus.HEALTHY.value,
                "value": 1.0,
                "unit": "status",
                "offset_minutes": -self.rng.randint(2, 6),
                "window_duration_seconds": 60,
                "scope": "worker_probe",
                "reliability": ReliabilityLevel.VERIFIED.value,
                "details": "Message queue consumer worker heartbeats active.",
            })

        return items

    def _generate_operational_events(self, archetype: str) -> list[dict[str, Any]]:
        """Synthesize operational logs, deployment events, and background noise."""
        items: list[dict[str, Any]] = []

        if archetype == "CACHE_INVALIDATION_CONSUMER_STALLED":
            items.append({
                "component": ComponentEnum.MESSAGE_QUEUE.value,
                "signal": "consumer_process_exit",
                "dimension": HealthDimension.AVAILABILITY.value,
                "status": HealthStatus.FAILED.value,
                "value": 1.0,
                "unit": "event",
                "offset_minutes": -self.rng.randint(12, 22),
                "window_duration_seconds": 60,
                "scope": "system_logs",
                "reliability": ReliabilityLevel.AGGREGATED.value,
                "details": "Process monitor logged silent exit on worker thread 'cache-evictor-03' due to unhandled serialization exception.",
            })
        elif archetype == "DATABASE_INDEX_REGRESSION":
            items.append({
                "component": ComponentEnum.DATABASE.value,
                "signal": "schema_migration_event",
                "dimension": HealthDimension.LATENCY.value,
                "status": HealthStatus.DEGRADED.value,
                "value": 1.0,
                "unit": "event",
                "offset_minutes": -self.rng.randint(15, 30),
                "window_duration_seconds": 600,
                "scope": "migration_history",
                "reliability": ReliabilityLevel.VERIFIED.value,
                "details": "Schema migration DDL 'V4.12__drop_legacy_indexes.sql' dropped index 'idx_orders_customer_lookup'.",
            })
        elif archetype == "FLASH_SALE_SURGE":
            items.append({
                "component": ComponentEnum.API_GATEWAY.value,
                "signal": "traffic_surge_alert",
                "dimension": HealthDimension.THROUGHPUT.value,
                "status": HealthStatus.DEGRADED.value,
                "value": float(self.rng.randint(35000, 60000)),
                "unit": "rps",
                "offset_minutes": -self.rng.randint(8, 16),
                "window_duration_seconds": 60,
                "scope": "ingress_logs",
                "reliability": ReliabilityLevel.VERIFIED.value,
                "details": "Ingress rate limiter engaged: incoming request volume surged past capacity limits.",
            })
        elif archetype == "CACHE_CLUSTER_OUTAGE":
            items.append({
                "component": ComponentEnum.CACHE.value,
                "signal": "node_failover_event",
                "dimension": HealthDimension.AVAILABILITY.value,
                "status": HealthStatus.FAILED.value,
                "value": 1.0,
                "unit": "event",
                "offset_minutes": -self.rng.randint(10, 20),
                "window_duration_seconds": 60,
                "scope": "cluster_logs",
                "reliability": ReliabilityLevel.VERIFIED.value,
                "details": "Redis sentinel triggered failover after primary node pod was terminated by OOM killer.",
            })
        elif archetype == "REPLICA_REPLICATION_LAG":
            items.append({
                "component": ComponentEnum.DATABASE.value,
                "signal": "replication_delay_seconds",
                "dimension": HealthDimension.FRESHNESS.value,
                "status": HealthStatus.DEGRADED.value,
                "value": float(self.rng.randint(45, 120)),
                "unit": "seconds",
                "offset_minutes": -self.rng.randint(5, 15),
                "window_duration_seconds": 60,
                "scope": "replication_logs",
                "reliability": ReliabilityLevel.VERIFIED.value,
                "details": "Read replica replication delay exceeded SLA threshold (measured at >60s).",
            })
        elif archetype == "DATABASE_CAPACITY_DEGRADATION":
            items.append({
                "component": ComponentEnum.DATABASE.value,
                "signal": "db_cpu_saturation_event",
                "dimension": HealthDimension.LATENCY.value,
                "status": HealthStatus.DEGRADED.value,
                "value": round(self.rng.uniform(96.0, 100.0), 1),
                "unit": "%",
                "offset_minutes": -self.rng.randint(4, 12),
                "window_duration_seconds": 60,
                "scope": "resource_monitor",
                "reliability": ReliabilityLevel.VERIFIED.value,
                "details": "Primary database CPU and IOPS saturated at 100% under runaway analytical load.",
            })
            items.append({
                "component": ComponentEnum.DATABASE.value,
                "signal": "lock_wait_timeout_count",
                "dimension": HealthDimension.LATENCY.value,
                "status": HealthStatus.FAILED.value,
                "value": float(self.rng.randint(24, 75)),
                "unit": "timeouts",
                "offset_minutes": -self.rng.randint(4, 12),
                "window_duration_seconds": 60,
                "scope": "db_slow_logs",
                "reliability": ReliabilityLevel.VERIFIED.value,
                "details": "Database transaction log reported lock wait timeouts on table 'inventory_allocations'.",
            })

        # Add realistic non-causal background noise (red herring)
        items.append({
            "component": ComponentEnum.API_GATEWAY.value,
            "signal": "routine_certificate_rotation",
            "dimension": HealthDimension.AVAILABILITY.value,
            "status": HealthStatus.HEALTHY.value,
            "value": 1.0,
            "unit": "event",
            "offset_minutes": -self.rng.randint(45, 90),
            "window_duration_seconds": 60,
            "scope": "audit_logs",
            "reliability": ReliabilityLevel.ADVISORY.value,
            "details": "TLS certificate automated renewal completed successfully by cert-manager.",
        })

        return items
