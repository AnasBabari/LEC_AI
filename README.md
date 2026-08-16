# Faultline — AI-Assisted Detective for Software Outages

> Faultline gathers conflicting clues about why a system broke, works out what probably went wrong, compares several possible repairs with different trade-offs, and ranks the safest one — without executing anything automatically.

[![CI](https://github.com/AnasBabari/LEC_AI/actions/workflows/ci.yml/badge.svg)](https://github.com/AnasBabari/LEC_AI/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python: 3.11+](https://img.shields.io/badge/Python-3.11+-3776AB.svg?logo=python&logoColor=white)](https://python.org)
[![React](https://img.shields.io/badge/React-19-61DAFB.svg?logo=react&logoColor=black)](https://react.dev)

**Start here:** [What it solves](#what-problem-does-faultline-solve) · [Example investigation](#a-simple-example) · [Three possible repairs](#three-possible-repairs) · [Architecture](#how-faultline-works) · [Run it](#try-it-yourself) · [Inside Faultline](#inside-faultline)

---

## What problem does Faultline solve?

Large websites depend on many parts working together: databases, caches, message queues, gateways. When something goes wrong, monitoring tools often give **conflicting clues**.

One tool might say *"the database is overloaded."*
Another might say *"the database is perfectly healthy."*
A third might report *"a background worker has stopped."*

A human engineer now has to decide:

- Which clues matter?
- Which clues disagree, and why?
- What actually caused the problem?
- Which of several possible repairs is safest to try first?

Faultline automates the investigation. It collects clues from independent sources, identifies where they conflict, scores possible causes against the evidence, compares competing repairs with different trade-offs, and ranks them — then hands everything to a human operator to decide what to do.

> **Faultline recommends actions. It never executes them.**
>
> It can say *"restart this worker first,"* but it cannot press the button itself. A human must approve and perform any repair.

---

## A simple example

### The website suddenly becomes slow

A monitoring alert fires: *"API response times are spiking. The database looks overwhelmed."*

Faultline investigates.

**Clue 1 — The symptoms.**
Website response times have jumped to 2400 ms. The database is handling a huge number of connections (92% of its capacity). The *cache* — a small shelf of frequently used information that lets the system answer common requests quickly — has dropped from 92% useful to just 34%.

At first, the database looks guilty.

**Clue 2 — A direct health check.**
Faultline sends a direct test query to the database. It responds in 1.8 ms with low CPU usage.

So the database engine itself is not broken. Something else is flooding it with work.

**Clue 3 — The real culprit.**
A *background worker* — a small program that quietly handles jobs behind the scenes — was responsible for keeping the cache up to date. It crashed 18 minutes ago. Since then, 42,000 pending update messages have piled up.

**Clue 4 — The chain reaction.**
Because the cache is stale, thousands of requests that would normally be answered instantly are being sent straight to the database instead. The database is healthy but overwhelmed by upstream failure.

**The clues appear to disagree — but both are true.**
The database can be healthy when tested directly while still being overwhelmed by thousands of real user requests. Faultline calls this kind of situation a *"scope tension"*: two measurements that seem contradictory because they are looking at different angles of the same component.

---

## Three possible repairs

Faultline now has to choose between several plausible actions. Three stand out:

| Choice | Why it looks attractive | Main problem | Result |
|---|---|---|---|
| **Restart the failed cache worker and drain its backlog** | Fixes the source of the stale cache | The backlog takes time to clear | **#1** |
| **Temporarily slow down incoming traffic** | Quickly reduces pressure on the database and surrounding system | Treats the symptom rather than repairing the failed worker | **#2** |
| **Flush and restart the cache** | Fastest action | Could create a cache stampede and worsen database load | **#3** |

**The fastest repair is not the winner.** Faultline chooses the first option because it addresses the root cause while keeping operational risk acceptable.

This is the central challenge Faultline is designed around: the most obvious repair is not always the best one. Restarting the cache is faster, and throttling traffic reduces pressure quickly, but recovering the failed worker is ranked first because it fixes the underlying cause with lower downstream risk.

Faultline evaluates a full repair catalogue — `RECOVER_CONSUMER_AND_DRAIN`, `THROTTLE_TRAFFIC`, `RESTART_CACHE`, `REBUILD_DATABASE_INDEX`, `FAILOVER_DATABASE`. These three choices illustrate the most important trade-off in the main scenario.

---

## How Faultline works

### 1. System Overview & Monitored Application

How the **Web Dashboard**, **Decision Engine**, **AI Assistants**, and **Monitored App** work together:

```mermaid
flowchart TB
    subgraph UI["🖥️ Web Dashboard (React)"]
        Dash["Observability Dashboard<br/><i>Timeline, Clue Inspector,<br/>Repair Matrix & Safety Gate</i>"]
    end

    subgraph Backend["⚙️ Faultline Decision Engine (Python)"]
        Orchestrator["Investigation Coordinator"]
        Ledger["Recorded Evidence Ledger"]
        Engine["Scoring Rules & Conflict Detector"]
        Validator["Safety & Verification Gate"]
        Orchestrator --> Ledger --> Engine --> Validator
    end

    subgraph AI["🧠 AI Assistants (Google Gemini / OpenRouter)"]
        subgraph LiveMode["Live AI Models"]
            Primary["Primary: Gemini 3.7"]
            Backup["Backup: Gemini 3.6"]
            Tertiary["Third-Tier: OpenRouter"]
            Primary -. If Busy .-> Backup -. If Offline .-> Tertiary
        end
        subgraph OfflineMode["Offline Mode"]
            Offline["Built-in Simulator<br/><i>(Zero API Keys)</i>"]
        end
    end

    subgraph Target["🏢 Simulated Web Application (E-Commerce)"]
        GW["API Gateway<br/><i>e.g. 2.4s response</i>"]
        Cache["Redis Cache<br/><i>e.g. 34% hit rate</i>"]
        MQ["Message Queue<br/><i>e.g. 42k backlog</i>"]
        DB["PostgreSQL DB<br/><i>e.g. 92% load</i>"]
    end

    User["👤 Human Engineer"] <-->|Reviews & Approves| UI
    UI <-->|Web Requests| Orchestrator
    Orchestrator <-->|Reasoning Prompts| Primary
    Orchestrator -->|Checks Diagnostics<br/><i>Traffic · Probes · Logs</i>| Target
```

> **Key takeaway:** AI assistants suggest diagnostic queries and draft plain-English explanations; Python computes all scores, verifies evidence, and enforces strict safety rules.

---

### 2. Step-by-Step Investigation Flow

The 6 core stages of an automated investigation:

```mermaid
flowchart TD
    subgraph S1["1. Incident Alert"]
        Alert["🚨 Outage Detected<br/><i>e.g. High latency alerts<br/>and database timeouts</i>"]
    end

    subgraph S2["2. Collect Clues"]
        Telemetry["📊 Traffic Telemetry<br/><i>e.g. Slow user requests<br/>and degraded latency</i>"]
        Probes["🩺 Direct Health Tests<br/><i>e.g. Fast ping tests<br/>to database & cache</i>"]
        Logs["📜 Background Logs<br/><i>e.g. Worker crashes<br/>and queue depth</i>"]
    end

    subgraph S3["3. Spot Contradictions"]
        Tension["⚖️ Reconcile Conflicting Clues<br/><i>e.g. Direct test is 1.8ms (OK) while<br/>customer queries stall (92% load)</i>"]
    end

    subgraph S4["4. Find the Root Cause"]
        Causes["🔍 Score Suspected Causes<br/><i>Weigh clue reliability, freshness,<br/>and direct causal connection</i>"]
    end

    subgraph S5["5. Compare Solutions"]
        Repairs["🎯 Weigh Competing Fixes<br/><i>Balance relief speed, long-term<br/>safety, and system risk</i>"]
    end

    subgraph S6["6. Safety Check & Human Decision"]
        Approval["🛡️ Safety Rules & Human Sign-Off<br/><i>Code verifies all rules;<br/>engineer makes final decision</i>"]
    end

    Alert --> Telemetry
    Alert --> Probes
    Alert --> Logs

    Telemetry --> Tension
    Probes --> Tension
    Logs --> Tension

    Tension --> Causes
    Causes --> Repairs
    Repairs --> Approval
```

> **Key takeaway:** Faultline pinpoints what broke by reconciling contradictory clues and ranks repairs by weighing trade-offs before passing through safety checks for human approval.

---

### 3. Who Does What: Decision & Trust Boundary

How AI exploration and fixed safety rules interact:

```mermaid
flowchart LR
    Incident["🚨 Problem Alert"]
    Investigate["🔍 Investigate"]
    Evidence["📜 Record Clues"]
    Causes["⚖️ Score Causes"]
    Repairs["🎯 Rank Repairs"]
    Explain["📝 Explain Decision"]
    Validate["🛡️ Verify Safety"]
    Human["👤 Human Engineer"]

    AI["🧠 AI Assistant<br/><i>(Gemini / OpenRouter)</i>"]
    Rules["📐 Fixed Safety Rules<br/><i>(Scoring & Fact-Checking)</i>"]

    Incident --> Investigate --> Evidence --> Causes --> Repairs --> Explain --> Validate --> Human

    AI -.->|Suggests tools| Investigate
    AI -.->|Drafts explanation| Explain
    Rules --> Causes
    Rules --> Repairs
    Rules --> Validate
```

> **Key takeaway:** Python owns the decision pipeline (solid arrows), while AI assists with tool suggestions and plain-English explanations (dotted arrows). All outputs pass through safety checks before reaching the engineer.

---


## Inside Faultline

### AI investigates, Python decides

Faultline pairs AI reasoning models (Google Gemini with multi-tier OpenRouter fallback) with deterministic Python code, with clearly separated jobs.

The AI model helps decide:

- which diagnostics to inspect;
- which allowed root causes are worth investigating;
- how to explain the result to a human.

Python owns:

- evidence IDs;
- whether evidence actually exists;
- whether evidence actually supports a cause;
- conflict classification;
- numeric scores;
- strategy ranking;
- safety checks;
- final validation.

> The AI model assists with reasoning, but deterministic Python owns decision authority.

Here, *deterministic* simply means that the same evidence and the same fixed rules produce the same numerical result. Every run over the same data produces identical scores and rankings.

### How clues are scored

A clue becomes stronger when it is:

- trustworthy;
- recent;
- directly related to the suspected problem.

```text
Evidence Strength =
Reliability + Freshness + Directness
```

| Part | What it measures | Values |
| :--- | :--- | :--- |
| **Reliability** | How trustworthy the source is | Verified (3) · Aggregated (2) · Advisory (1) |
| **Freshness** | How close in time to the incident | Current (2) · Recent (1) · Stale (0) |
| **Directness** | How directly it connects to the cause | Direct (3) · Indirect (2) · Contextual (1) |

### The source-group cap

Ten measurements produced by the same monitoring system should not automatically count like ten independent opinions. Ten people repeating the same rumour are not the same as ten independent witnesses.

Faultline therefore limits how much evidence from the same source group can contribute to the numerical score — the `source-group cap`. Additional correlated measurements are still recorded as clues, but they cannot inflate a cause's score.

### Support vs opposition

```text
Net Evidence =
max(0, Support - Opposition)
```

Evidence supporting a cause increases its score. Evidence contradicting that cause reduces it. If the opposition becomes stronger than the support, Faultline treats that cause as having zero usable evidence rather than a negative score.

### Decision weights

Decision weights are policy-derived ratios, not probabilities. In the canonical incident, 73.7% of the positive policy-weighted evidence points toward the stalled cache-invalidation worker. That describes how the evidence is split between candidate causes — it is not a claim that the cause is "73.7% likely" to be right.

### How repairs are ranked

Each repair is judged on four questions:

1. Will it solve the real problem? *(Impact)*
2. Is it safe? *(Safety)*
3. How quickly can it help? *(Speed)*
4. How expensive or difficult is it? *(Cost)*

| Factor | Weight |
| :--- | ---: |
| Impact | 60% |
| Safety | 20% |
| Speed | 15% |
| Cost | 5% |

Impact receives the largest weight because a very fast repair for the wrong problem is still the wrong repair.

### Why the canonical ranking lands as it does

**Restart the failed cache worker and drain its backlog — #1.** It wins because it addresses the root cause, is backed by strong evidence for a stalled consumer, avoids destructive cache behaviour, and carries reasonable operational safety.

**Temporarily slow down incoming traffic — #2.** It is useful because it reduces immediate system pressure, is relatively safe, and fairly fast. It loses because it does not repair the stalled worker, and the workload returns once throttling is removed.

**Flush and restart the cache — #3.** It is attractive because it is the fastest option. It loses because it does not repair the consumer, it discards useful cached data, and an empty cache can send a request stampede against an already-strained database.

### Report validation

Faultline does not trust its own generated report simply because the pipeline produced it. Before returning an answer, Python checks again:

- evidence references;
- cause scores;
- repair calculations;
- ranking order;
- safety flags.

If the structured result disagrees with the fixed rules, the report is rejected. This gate lives in `ReportValidator` (`src/faultline/validation.py`).

### Model setup: three-tier live cascade + deterministic offline mode

Faultline uses a resilient, three-tier live provider cascade with bounded retries and exponential backoff, plus an explicit deterministic offline mode:

- **Live Tier 1 (Primary)**: `gemini-3.7-flash` (or `GEMINI_MODEL`) via Google GenAI SDK.
- **Live Tier 2 (Gemini Fallback)**: `gemini-3.6-flash` (or `GEMINI_FALLBACK_MODEL`) if the primary model encounters rate limits (429), capacity issues (503), or transient network timeouts.
- **Live Tier 3 (OpenRouter Fallback)**: `google/gemini-2.0-flash-001` (or `OPENROUTER_FALLBACK_MODEL`) via OpenRouter's OpenAI-compatible API (`OPENROUTER_API_KEY`) if Google Gemini endpoints are unreachable or quota-exhausted.
- **Deterministic Offline Mode**: Built-in deterministic reasoning provider (`FakeGeminiProvider`) for hermetic CI builds, local development, and zero-credential assessment when API keys are omitted.

**Session stickiness:** When a live fallback tier succeeds, subsequent diagnostic and narrative calls in that investigation session stay on the working provider to eliminate retry latency.

**Strict error sanitization:** Secrets, API keys, and authorization headers are never logged or returned in error payloads. Non-transient client errors (such as 400 Bad Request or 401 Unauthorized) fail fast without triggering invalid fallbacks.

### Testing

```bash
uv run pytest -v
uv run ruff check src/ tests/
uv run mypy src/ tests/
cd frontend && npm run verify
docker build -t faultline .
```

GitHub Actions runs the verification suite automatically on pushes to `main`.

---

## Safety

Faultline's most important safety rule is simple:

> **It never executes repairs.**
>
> `execution_status = "not_executed"` · `operator_approval_required = True`

Suggested commands (like `kubectl rollout restart ...`) are display-only illustrations. There is no code in Faultline that runs shell commands, calls subprocess, or executes repairs. A human operator must review the recommendation and act on it independently.

---

## What you can see in the dashboard

Faultline includes a React web dashboard that shows:

- the initial incident alert;
- a step-by-step investigation timeline;
- all collected evidence with source, status, and values;
- conflicting clues and how they are resolved;
- scored root-cause hypotheses;
- ranked repair strategies with scores;
- a written explanation defending the recommendation;
- operator safety status.

---

## Try it yourself

### Prerequisites

- Python 3.11+ (with [`uv`](https://docs.astral.sh/uv/) package manager)
- Node.js 20+ (for the frontend dashboard)
- *(Optional)* API key for live AI reasoning (`GEMINI_API_KEY` for Google Gemini or `OPENROUTER_API_KEY` for OpenRouter) — runs fully deterministic in offline mode without any keys

### Local setup

```bash
# Clone the repository
git clone https://github.com/AnasBabari/LEC_AI.git
cd LEC_AI

# Install locked Python dependencies
uv sync --frozen --all-extras

# (Optional) Export live API keys
export GEMINI_API_KEY="your-gemini-key"          # Primary (3.7) & Secondary (3.6)
export OPENROUTER_API_KEY="your-openrouter-key"  # Tertiary fallback

# Run an offline analysis from the command line
uv run faultline analyze --offline --scenario cache_invalidation_lag

# Start the backend API server
uv run uvicorn faultline.app:app --host 0.0.0.0 --port 8000

# In a separate terminal, start the React frontend
cd frontend && npm ci && npm run dev
# Open http://localhost:5173
```

### Docker

```bash
docker build -t faultline .
docker run -p 8000:8000 \
  -e GEMINI_API_KEY="your-gemini-key-optional" \
  -e OPENROUTER_API_KEY="your-openrouter-key-optional" \
  faultline
# Open http://localhost:8000
```

---

## Limits of this demo

Faultline is a working decision-support prototype, not a production control plane.

- Diagnostic sources are deterministic scenario simulators, not live Prometheus, database, cache, or queue integrations.
- Repair commands are illustrative strings. They are never executed.
- Evidence and strategy weights are explicit policy choices, not learned probabilities or guarantees of recovery.
- AI models are optional. A multi-tier fallback cascade (Gemini Primary -> Gemini Secondary -> OpenRouter Tertiary) handles transient live issues, while offline mode makes the full workflow reproducible for assessment and CI without credentials.
- Structured claims are checked, but a human operator must still review the written explanation and approve any real-world action.

These boundaries are deliberate: the assessment focuses on reasoning through conflicting diagnostics and defending a repair ranking.

---

## Scenarios

Faultline includes six tested scenario fixtures:

- **`cache_invalidation_lag`** (Canonical Incident) — A stalled invalidation queue consumer causes stale cache entries and cascading database query overload. Winner: `RECOVER_CONSUMER_AND_DRAIN`.
- **`index_regression`** — A release accidentally drops a database index. Direct health probes pass, but user workload queries degrade severely. Winner: `REBUILD_DATABASE_INDEX`.
- **`flash_sale_surge`** — Extreme promotional traffic overwhelms backend worker pools and ingress gateways. Winner: `THROTTLE_TRAFFIC`.
- **`cache_cluster_outage`** — A primary Redis node crashes and fails over, causing transient cache misses and connection pool saturation. Winner: `RESTART_CACHE`.
- **`replica_replication_lag`** — High write volumes cause read replica synchronization lag, surfacing stale data reads. Winner: `THROTTLE_TRAFFIC`.
- **`database_capacity_exhaustion`** — Unoptimized long-running transactions exhaust connection pools and locks. Winner: `FAILOVER_DATABASE`.

### What I would build next

- Dynamic scenario generator using synthetic chaos engineering faults.
- Automated post-mortem exporter to Markdown or GitHub Issues.
- Direct Prometheus / OpenTelemetry OTLP telemetry ingestion.

---

## AI assistance disclosure

AI tools, including Gemini 3.7 Flash High via Antigravity, assisted with planning, implementation, code review, debugging, testing, and iteration. I reviewed and tested the shipped architecture, deterministic scoring policy, evidence-validation boundaries, and safety constraints, and can explain and defend the resulting implementation and its trade-offs.

---

## Links

- **Repository:** [github.com/AnasBabari/LEC_AI](https://github.com/AnasBabari/LEC_AI)
- **Dashboard:** `http://localhost:5173` (local) or `http://localhost:8000` (Docker)
- **Reference output:** [`examples/canonical-report.offline.json`](examples/canonical-report.offline.json)
