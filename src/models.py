from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Filter / query models
# ---------------------------------------------------------------------------

class LedgerFilters(BaseModel):
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    amount_min: Optional[float] = None
    amount_max: Optional[float] = None
    account_code: Optional[str] = None
    vendor_id: Optional[str] = None


# ---------------------------------------------------------------------------
# Observation
# ---------------------------------------------------------------------------

VALID_VIEWS = Literal[
    "income_statement",
    "balance_sheet",
    "cashflow",
    "general_ledger",
    "sub_ledger",
    "narrative",
]


class AuditObservation(BaseModel):
    current_view: VALID_VIEWS
    visible_data: Dict[str, Any]
    scratchpad: List[Dict[str, Any]]
    available_actions: List[str]
    anomaly_alerts: List[str]
    investigation_progress: float

    @field_validator("investigation_progress")
    @classmethod
    def clamp_progress(cls, v: float) -> float:
        if v < 0.0 or v > 1.0:
            raise ValueError("investigation_progress must be in [0.0, 1.0]")
        return v


# ---------------------------------------------------------------------------
# Action models
# ---------------------------------------------------------------------------

class NavigateAction(BaseModel):
    action_type: Literal["navigate"]
    view: VALID_VIEWS


class QueryLedgerAction(BaseModel):
    action_type: Literal["query_ledger"]
    filters: LedgerFilters


class LinkEvidenceAction(BaseModel):
    action_type: Literal["link_evidence"]
    source_id: str
    target_id: str
    relationship: str


class IssueVerdictAction(BaseModel):
    action_type: Literal["issue_verdict"]
    conclusion: Literal[
        "clean_audit",
        "material_misstatement",
        "fraud_detected",
        "non_gaap_manipulation",
    ]
    rationale: str
    evidence_chain: List[Dict[str, Any]]


Action = Annotated[
    NavigateAction | QueryLedgerAction | LinkEvidenceAction | IssueVerdictAction,
    Field(discriminator="action_type"),
]


# ---------------------------------------------------------------------------
# Financial document models
# ---------------------------------------------------------------------------

class IncomeStatement(BaseModel):
    company: str
    period: str
    revenue: float
    operating_income: float
    net_income: float
    operating_margin: float


class BalanceSheet(BaseModel):
    company: str
    period: str
    total_assets: float
    accounts_receivable: float
    total_liabilities: float
    equity: float
    accounts_payable: float


class CashFlow(BaseModel):
    company: str
    period: str
    operating_cash_flow: float
    investing_cash_flow: float
    financing_cash_flow: float


class NarrativeChunk(BaseModel):
    chunk_id: str
    text: str
    referenced_kpis: List[str]


class Narrative(BaseModel):
    company: str
    period: str
    chunks: List[NarrativeChunk]


# ---------------------------------------------------------------------------
# Grader / internal models
# ---------------------------------------------------------------------------

class VerdictPayload(BaseModel):
    conclusion: str
    rationale: str
    evidence_chain: List[Dict[str, Any]]
    scratchpad: List[Dict[str, Any]]
    task_id: int
    flagged_tx_ids: Optional[List[str]] = None


class CompanyData(BaseModel):
    company_id: str
    company_name: str
    income_statement: IncomeStatement
    balance_sheet: BalanceSheet
    cashflow: CashFlow
    narrative: Narrative
    ledger_db_path: Path
    sub_ledger_db_path: Path


# ---------------------------------------------------------------------------
# API request / response models
# ---------------------------------------------------------------------------

class ResetRequest(BaseModel):
    company_id: str
    task_id: int
    force: bool = False


class StepResponse(BaseModel):
    observation: AuditObservation
    reward: float
    done: bool
    info: Dict[str, Any]
