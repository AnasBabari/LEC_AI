"""FastAPI Application for Faultline Incident Decision-Support Service."""

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncGenerator

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from faultline.diagnostics import ScenarioRepository
from faultline.gemini import FakeGeminiProvider, GeminiProvider, LLMProviderProtocol
from faultline.models import AnalysisResult, AnalyzeRequest
from faultline.orchestrator import IncidentOrchestrator, OrchestratorError
from faultline.reasoning import PolicyEngine
from faultline.validation import ValidationError

logger = logging.getLogger("faultline.app")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Lifespan context resolving model availability and policy engine at startup."""
    policy = PolicyEngine()
    repo = ScenarioRepository()

    api_key = os.getenv("GEMINI_API_KEY")
    provider: LLMProviderProtocol
    if api_key:
        provider = GeminiProvider(api_key=api_key)
    else:
        logger.info("GEMINI_API_KEY not found; starting in deterministic offline mode with FakeGeminiProvider.")
        provider = FakeGeminiProvider()

    app.state.policy = policy
    app.state.scenario_repo = repo
    app.state.provider = provider
    app.state.orchestrator = IncidentOrchestrator(
        provider=provider,
        policy=policy,
        scenario_repo=repo,
    )
    yield


app = FastAPI(
    title="Faultline API",
    description="Operational Incident Decision-Support and Competing Repair Strategy Ranker",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health_check() -> dict[str, Any]:
    """Health check endpoint indicating server readiness and provider configuration."""
    api_key_configured = bool(os.getenv("GEMINI_API_KEY"))
    provider = getattr(app.state, "provider", None)
    model_name = provider.primary_model if provider else "unknown"
    return {
        "status": "healthy",
        "service": "faultline",
        "version": "0.1.0",
        "gemini_configured": api_key_configured,
        "runtime_model": model_name,
    }


@app.get("/api/scenarios")
def list_scenarios() -> list[dict[str, Any]]:
    """List all available incident scenarios in the catalogue."""
    repo: ScenarioRepository = app.state.scenario_repo
    return repo.list_scenarios()


@app.post("/api/analyze", response_model=AnalysisResult)
def analyze_incident(req: AnalyzeRequest) -> AnalysisResult:
    """Run synchronous diagnostic investigation and strategy ranking for a scenario."""
    orchestrator: IncidentOrchestrator = app.state.orchestrator
    try:
        result = orchestrator.analyze_scenario(req.scenario_id)
        return result
    except FileNotFoundError as fnf:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Scenario '{req.scenario_id}' was not found in the scenario repository.",
        ) from fnf
    except (ValidationError, OrchestratorError) as ve:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Analysis failed domain validation: {ve}",
        ) from ve
    except Exception as e:
        logger.exception(f"Unexpected error during analysis of '{req.scenario_id}': {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal incident analysis failure: {str(e)}",
        ) from e


# Static Frontend Hosting (when frontend is built)
frontend_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if frontend_dist.exists():
    app.mount("/assets", StaticFiles(directory=frontend_dist / "assets"), name="assets")

    @app.get("/{full_path:path}")
    def serve_frontend(full_path: str) -> Any:
        file_path = frontend_dist / full_path
        if file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(frontend_dist / "index.html")
