from __future__ import annotations

from typing import Any, Dict

from fastapi import Body, FastAPI, HTTPException

from .environment import (
    CompanyNotFoundError,
    EpisodeActiveError,
    EpisodeDoneError,
    ForensicAuditEnv,
    NoActiveEpisodeError,
)
from .models import (
    Action,
    AuditObservation,
    IssueVerdictAction,
    LinkEvidenceAction,
    NavigateAction,
    QueryLedgerAction,
    ResetRequest,
    StepResponse,
)

app = FastAPI(title="ForensicAuditEnv", version="1.0.0")
env = ForensicAuditEnv()


@app.get("/")
def health() -> Dict[str, Any]:
    return {"status": "ok", "name": "forensic-audit-env", "version": "1.0.0"}


@app.post("/reset", response_model=AuditObservation)
def reset(request: ResetRequest) -> AuditObservation:
    try:
        return env.reset(request.company_id, request.task_id, force=request.force)
    except EpisodeActiveError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except CompanyNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@app.post("/step", response_model=StepResponse)
def step(action: Dict[str, Any] = Body(...)) -> StepResponse:
    """Accept any action dict and dispatch via discriminated union."""
    action_type = action.get("action_type")
    try:
        if action_type == "navigate":
            parsed: Action = NavigateAction(**action)
        elif action_type == "query_ledger":
            parsed = QueryLedgerAction(**action)
        elif action_type == "link_evidence":
            parsed = LinkEvidenceAction(**action)
        elif action_type == "issue_verdict":
            parsed = IssueVerdictAction(**action)
        else:
            raise HTTPException(
                status_code=422,
                detail=f"Unknown action_type '{action_type}'. Must be one of: navigate, query_ledger, link_evidence, issue_verdict",
            )
    except Exception as e:
        if isinstance(e, HTTPException):
            raise
        raise HTTPException(status_code=422, detail=str(e))

    try:
        obs, reward, done, info = env.step(parsed)
        return StepResponse(observation=obs, reward=reward, done=done, info=info)
    except NoActiveEpisodeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except EpisodeDoneError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/state", response_model=AuditObservation)
def state() -> AuditObservation:
    return env.get_state()
