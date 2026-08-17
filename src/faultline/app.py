"""FastAPI Application for Faultline Incident Decision-Support Service."""

import logging
import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncGenerator, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from faultline.diagnostics import ScenarioRepository
from faultline.gemini import FakeGeminiProvider, GeminiProvider, LLMProviderProtocol
from faultline.generator import IncidentSynthesisEngine
from faultline.models import (
    AnalysisResult,
    AnalysisTimeoutError,
    AnalyzeRequest,
    GenerateIncidentRequest,
    GenerateIncidentResponse,
    InsufficientEvidenceError,
    InvalidModelOutputError,
    ModelAuthenticationError,
    ModelRequestError,
    ModelUnavailableError,
)
from faultline.orchestrator import IncidentOrchestrator, OrchestratorError
from faultline.reasoning import PolicyEngine
from faultline.validation import ValidationError

# Load .env file automatically at startup
load_dotenv()

logger = logging.getLogger("faultline.app")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")


def sanitize_error_message(msg: Any) -> str:
    """Strip any accidental authorization tokens, api keys, or sensitive text from error details."""
    import re

    cleaned = re.sub(r"(?:Bearer\s+|key=)[A-Za-z0-9_\-\.]{10,}", "[REDACTED_SECRET]", str(msg))
    cleaned = re.sub(r"sk-[A-Za-z0-9_\-]{10,}", "[REDACTED_SECRET]", cleaned)
    cleaned = re.sub(r"AIza[A-Za-z0-9_\-]{10,}", "[REDACTED_SECRET]", cleaned)
    return cleaned


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Lifespan context resolving model availability and policy engine at startup."""
    if not hasattr(app.state, "policy") or app.state.policy is None:
        app.state.policy = PolicyEngine()
    if not hasattr(app.state, "scenario_repo") or app.state.scenario_repo is None:
        app.state.scenario_repo = ScenarioRepository()

    existing_provider = getattr(app.state, "provider", None)
    if existing_provider is None:
        gemini_key = os.getenv("GEMINI_API_KEY")
        openrouter_key = os.getenv("OPENROUTER_API_KEY")
        is_offline = os.getenv("FAULTLINE_OFFLINE", "").lower() in ("1", "true", "yes")
        is_dummy_key = bool(gemini_key and (gemini_key.lower().startswith("dummy") or "your-api-key" in gemini_key.lower()))
        provider: LLMProviderProtocol
        if (gemini_key or openrouter_key) and os.getenv("FAULTLINE_ENV") != "test" and not is_offline and not is_dummy_key:
            provider = GeminiProvider(api_key=gemini_key, openrouter_api_key=openrouter_key)
        else:
            logger.info("Starting in deterministic offline mode with FakeGeminiProvider.")
            provider = FakeGeminiProvider()
        app.state.provider = provider

    if not hasattr(app.state, "orchestrator") or app.state.orchestrator is None:
        app.state.orchestrator = IncidentOrchestrator(
            provider=app.state.provider,
            policy=app.state.policy,
            scenario_repo=app.state.scenario_repo,
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
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health_check() -> dict[str, Any]:
    """Health check endpoint indicating server readiness and provider configuration."""
    api_key_configured = bool(os.getenv("GEMINI_API_KEY"))
    openrouter_key_configured = bool(os.getenv("OPENROUTER_API_KEY"))
    provider = getattr(app.state, "provider", None)
    model_name = provider.primary_model if provider else "unknown"
    fallback_name = getattr(provider, "fallback_model", None) if provider else None
    openrouter_model = getattr(provider, "openrouter_model", None) if provider else None
    discovered = getattr(provider, "discovered_accessible", True) if provider else True
    model_resolution_status = (
        getattr(provider, "model_resolution_status", "verified" if discovered else "unavailable")
        if provider
        else "offline"
    )

    if api_key_configured and isinstance(provider, GeminiProvider):
        mode = "live_gemini"
    elif openrouter_key_configured and isinstance(provider, GeminiProvider):
        mode = "live_openrouter"
    else:
        mode = "deterministic_fake"

    analysis_ready = (mode == "deterministic_fake") or (
        model_resolution_status in ("verified", "fallback_active", "openrouter_standby")
    )

    return {
        "status": "healthy",
        "service": "faultline",
        "version": "0.1.0",
        "analysis_ready": analysis_ready,
        "gemini_configured": api_key_configured,
        "openrouter_configured": openrouter_key_configured,
        "provider_mode": mode,
        "runtime_model": model_name,
        "fallback_model": fallback_name,
        "openrouter_model": openrouter_model if openrouter_key_configured else None,
        "discovered_accessible": discovered,
        "model_resolution_status": model_resolution_status,
    }


@app.get("/api/scenarios")
def list_scenarios() -> list[dict[str, Any]]:
    """List all available incident scenarios in the catalogue."""
    repo: ScenarioRepository = app.state.scenario_repo
    return repo.list_scenarios()


@app.post("/api/incidents/generate", response_model=GenerateIncidentResponse)
@app.post("/api/scenarios/generate", response_model=GenerateIncidentResponse)
def generate_incident(req: Optional[GenerateIncidentRequest] = None) -> GenerateIncidentResponse:
    """Generate a dynamic, realistic system failure incident on demand."""
    seed = req.seed if req else None
    archetype = req.archetype if req else None
    engine = IncidentSynthesisEngine(seed=seed)
    incident_data = engine.generate_incident(archetype=archetype)

    repo: ScenarioRepository = app.state.scenario_repo
    incident_id = repo.register_dynamic_scenario(incident_data)

    return GenerateIncidentResponse(
        id=incident_id,
        title=incident_data["title"],
        description=incident_data["description"],
        affected_components=incident_data["affected_components"],
        incident_at=incident_data["incident_at"],
        is_dynamic=True,
    )



@app.post("/api/analyze", response_model=AnalysisResult)
def analyze_incident(req: AnalyzeRequest) -> AnalysisResult:
    """Run synchronous diagnostic investigation and strategy ranking for a scenario."""
    orchestrator: IncidentOrchestrator = app.state.orchestrator
    try:
        result = orchestrator.analyze_scenario(req.scenario_id)
        return result
    except (FileNotFoundError, ValueError) as fnf:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Scenario '{req.scenario_id}' was not found in the scenario repository.",
        ) from fnf
    except ModelRequestError as mre:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Upstream model request invalid: {sanitize_error_message(mre)}",
        ) from mre
    except (InsufficientEvidenceError, InvalidModelOutputError) as val_err:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Analysis validation error: {sanitize_error_message(val_err)}",
        ) from val_err
    except (ModelAuthenticationError, ModelUnavailableError) as mue:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Model provider is currently unavailable: {sanitize_error_message(mue)}",
        ) from mue
    except AnalysisTimeoutError as ate:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=f"Analysis timed out: {sanitize_error_message(ate)}",
        ) from ate
    except OrchestratorError as oe:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Orchestration engine failure: {sanitize_error_message(oe)}",
        ) from oe
    except ValidationError as ve:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Final report validation failed: {sanitize_error_message(ve)}",
        ) from ve
    except Exception as e:
        error_id = f"ERR-{uuid.uuid4().hex[:8].upper()}"
        logger.exception(f"Unexpected error [{error_id}] during analysis of '{req.scenario_id}': {sanitize_error_message(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal incident analysis failure. Incident reference ID: {error_id}",
        ) from e


# Static Frontend Hosting (when frontend is built)
frontend_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if frontend_dist.exists():
    assets_dir = frontend_dist / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/{full_path:path}")
    def serve_frontend(full_path: str) -> Any:
        # Prevent API routes from serving the frontend HTML
        if full_path.startswith("api/") or full_path == "api":
            raise HTTPException(status_code=404, detail=f"API endpoint '/{full_path}' not found")

        # Strictly resolve path against frontend_dist and prevent traversal escapes
        resolved_dist = frontend_dist.resolve()
        try:
            target_path = (frontend_dist / full_path).resolve()
            if not target_path.is_relative_to(resolved_dist):
                raise HTTPException(status_code=404, detail="File not found")
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(status_code=404, detail="File not found")

        if target_path.is_file():
            return FileResponse(target_path)
        return FileResponse(frontend_dist / "index.html")
