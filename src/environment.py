from __future__ import annotations

import json
import logging
import os
import uuid
from pathlib import Path
from typing import Any, Dict, Set, Tuple

from .ledger_query import LedgerQueryEngine
from .models import (
    Action,
    AuditObservation,
    CompanyData,
    IssueVerdictAction,
    LinkEvidenceAction,
    NavigateAction,
    QueryLedgerAction,
    VerdictPayload,
)
from .tasks import get_grader

MAX_STEPS = 15
# Support both local dev (data/ next to src/) and container (data/ in WORKDIR)
_default_data = Path(__file__).parent.parent / "data"
if not _default_data.exists():
    _default_data = Path("data")
DATA_DIR = Path(os.getenv("DATA_DIR", str(_default_data)))

COMPANY_MAP = {
    "TechCorp":        "company_1",
    "RetailCo":        "company_2",
    "ManufacturingInc": "company_3",
    "FinanceHub":      "company_4",
    "HealthcarePlus":  "company_5",
    "company_1":       "company_1",
    "company_2":       "company_2",
    "company_3":       "company_3",
    "company_4":       "company_4",
    "company_5":       "company_5",
}

ANOMALY_ALERTS: Dict[str, list[str]] = {
    "company_1": ["AR spike detected: Accounts Receivable increased 40% YoY"],
    "company_2": ["12 duplicate invoice payments detected in Accounts Payable"],
    "company_3": ["Narrative claims strong cash generation but OCF is negative"],
    "company_4": [],
    "company_5": [],
}

AVAILABLE_ACTIONS = [
    "navigate_to(income_statement)",
    "navigate_to(balance_sheet)",
    "navigate_to(cashflow)",
    "navigate_to(general_ledger)",
    "navigate_to(sub_ledger)",
    "navigate_to(narrative)",
    "query_ledger(filters={})",
    "link_evidence(source_id, target_id, relationship)",
    "issue_verdict(conclusion, rationale, evidence_chain)",
]


# ---------------------------------------------------------------------------
# RewardComputer
# ---------------------------------------------------------------------------

class RewardComputer:
    CLAMP_MIN: float = -2.0
    CLAMP_MAX: float = 3.0

    def delta_navigate(self, view: str, visited: Set[str]) -> float:
        return 0.1 if view not in visited else 0.0

    def delta_query(self, row_count: int) -> float:
        return 0.3 if row_count > 0 else -0.05

    def delta_link_evidence(self, link: Dict[str, Any], scratchpad: list[Dict]) -> float:
        if self._is_contradictory(link, scratchpad):
            return -0.15
        return 0.2

    def delta_loop(self, action_repr: str, history: list[str]) -> float:
        return -0.1 if action_repr in history else 0.0

    def delta_verdict(self, task_score: float, evidence_complete: bool) -> float:
        if task_score > 0.5:
            return 1.0 if evidence_complete else 0.5
        return 0.0

    # ------------------------------------------------------------------
    # Upgrade 2: Six Sigma Redundancy Reward
    # Reward +0.3 when agent verifies the same financial fact across
    # multiple independent data sources (GL + narrative, or CF + BS).
    # This trains agents toward High-Reliability Organization (HRO) standards.
    # ------------------------------------------------------------------

    def delta_redundancy(self, source_id: str, scratchpad: list[Dict]) -> float:
        """
        +0.3 if this link corroborates a fact already in the scratchpad
        from a different data source (cross-system verification).
        """
        CROSS_SOURCE_PAIRS = [
            ("income_statement", "narrative"),
            ("cashflow", "balance_sheet"),
            ("general_ledger", "sub_ledger"),
            ("general_ledger", "narrative"),
            ("cashflow", "narrative"),
        ]
        src_lower = source_id.lower()
        for existing in scratchpad:
            existing_src = str(existing.get("source_id", "")).lower()
            for a, b in CROSS_SOURCE_PAIRS:
                if (a in src_lower and b in existing_src) or (b in src_lower and a in existing_src):
                    return 0.3
        return 0.0

    def clamp(self, reward: float) -> float:
        return max(self.CLAMP_MIN, min(self.CLAMP_MAX, reward))

    def _is_contradictory(self, link: Dict[str, Any], scratchpad: list[Dict]) -> bool:
        src = link.get("source_id", "")
        tgt = link.get("target_id", "")
        rel = link.get("relationship", "")
        for existing in scratchpad:
            if existing.get("source_id") == src and existing.get("target_id") == tgt:
                existing_rel = existing.get("relationship", "")
                if existing_rel and existing_rel != rel:
                    return True
        return False


# ---------------------------------------------------------------------------
# EpisodeLogger
# ---------------------------------------------------------------------------

class EpisodeLogger:
    def __init__(self) -> None:
        self._logger = logging.getLogger("forensic_audit_env")
        if not self._logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(logging.Formatter("%(message)s"))
            self._logger.addHandler(handler)
            self._logger.setLevel(logging.INFO)

    def log_start(self, episode_id: str, company: str, task_id: int) -> None:
        self._logger.info(json.dumps({
            "tag": "[START]", "episode_id": episode_id,
            "company": company, "task_id": task_id,
        }))

    def log_step(self, step: int, action_type: str, reward_delta: float) -> None:
        self._logger.info(json.dumps({
            "tag": "[STEP]", "step": step,
            "action_type": action_type, "reward_delta": round(reward_delta, 4),
        }))

    def log_end(self, episode_id: str, total_reward: float, task_score: float, reason: str) -> None:
        self._logger.info(json.dumps({
            "tag": "[END]", "episode_id": episode_id,
            "total_reward": round(total_reward, 4),
            "task_score": round(task_score, 4), "reason": reason,
        }))


# ---------------------------------------------------------------------------
# ForensicAuditEnv
# ---------------------------------------------------------------------------

class ForensicAuditEnv:
    def __init__(self, data_dir: Path = DATA_DIR) -> None:
        self._data_dir = data_dir
        self._reward = RewardComputer()
        self._logger = EpisodeLogger()
        self._reset_state()

    def _reset_state(self) -> None:
        self._episode_id: str = ""
        self._step_count: int = 0
        self._cumulative_reward: float = 0.0
        self._visited_views: Set[str] = set()
        self._action_history: list[str] = []
        self._scratchpad: list[Dict[str, Any]] = []
        self._current_view: str = "income_statement"
        self._active: bool = False
        self._done: bool = False
        self._company_data: CompanyData | None = None
        self._task_id: int = 1
        self._task_score: float = 0.0
        self._ledger_engine: LedgerQueryEngine | None = None
        self._sub_ledger_engine: LedgerQueryEngine | None = None

    def reset(self, company_id: str, task_id: int, force: bool = False) -> AuditObservation:
        if self._active and not force:
            raise EpisodeActiveError("Episode in progress. Use force=true to reset.")

        # Close existing DB connections
        if self._ledger_engine:
            self._ledger_engine.close()
        if self._sub_ledger_engine:
            self._sub_ledger_engine.close()

        self._reset_state()

        cid = COMPANY_MAP.get(company_id)
        if cid is None:
            raise CompanyNotFoundError(f"Company '{company_id}' not found")
        if task_id not in (1, 2, 3):
            raise ValueError("task_id must be 1, 2, or 3")

        company_dir = self._data_dir / cid
        self._company_data = self._load_company(cid, company_dir)
        self._task_id = task_id
        self._episode_id = str(uuid.uuid4())
        self._active = True
        self._current_view = "income_statement"

        self._ledger_engine = LedgerQueryEngine(self._company_data.ledger_db_path)
        self._sub_ledger_engine = LedgerQueryEngine(self._company_data.sub_ledger_db_path)

        self._logger.log_start(self._episode_id, cid, task_id)
        return self._build_observation()

    def step(self, action: Action) -> Tuple[AuditObservation, float, bool, Dict[str, Any]]:
        if not self._active:
            raise NoActiveEpisodeError("No active episode. Call /reset first.")
        if self._done:
            raise EpisodeDoneError("Episode is complete. Call /reset to start a new episode.")

        action_repr = action.model_dump_json()
        loop_delta = self._reward.delta_loop(action_repr, self._action_history)
        self._action_history.append(action_repr)
        self._cumulative_reward += loop_delta

        delta = 0.0
        done = False
        info: Dict[str, Any] = {}

        if isinstance(action, NavigateAction):
            delta = self._handle_navigate(action)
        elif isinstance(action, QueryLedgerAction):
            delta = self._handle_query(action)
        elif isinstance(action, LinkEvidenceAction):
            delta = self._handle_link(action)
        elif isinstance(action, IssueVerdictAction):
            delta, done, info = self._handle_verdict(action)

        self._cumulative_reward += delta
        self._step_count += 1

        if self._step_count >= MAX_STEPS and not done:
            done = True
            self._logger.log_end(
                self._episode_id,
                self._reward.clamp(self._cumulative_reward),
                self._task_score,
                "step_limit",
            )

        if done:
            self._done = True
            self._active = False

        total_delta = loop_delta + delta
        self._logger.log_step(self._step_count, action.action_type, total_delta)

        clamped = self._reward.clamp(self._cumulative_reward)
        obs = self._build_observation()
        return obs, clamped, done, info

    def get_state(self) -> AuditObservation:
        return self._build_observation()

    # ------------------------------------------------------------------
    # Action handlers
    # ------------------------------------------------------------------

    def _handle_navigate(self, action: NavigateAction) -> float:
        delta = self._reward.delta_navigate(action.view, self._visited_views)
        self._visited_views.add(action.view)
        self._current_view = action.view
        return delta

    def _handle_query(self, action: QueryLedgerAction) -> float:
        engine = (
            self._sub_ledger_engine
            if self._current_view == "sub_ledger"
            else self._ledger_engine
        )
        table = "sub_ledger" if self._current_view == "sub_ledger" else "transactions"
        if engine is None:
            return -0.05
        rows = engine.query(action.filters, table=table)
        self._visible_query_results = rows
        return self._reward.delta_query(len(rows))

    def _handle_link(self, action: LinkEvidenceAction) -> float:
        link = {
            "source_id": action.source_id,
            "target_id": action.target_id,
            "relationship": action.relationship,
        }
        delta = self._reward.delta_link_evidence(link, self._scratchpad)
        # Upgrade 2: Six Sigma redundancy reward for cross-source verification
        delta += self._reward.delta_redundancy(action.source_id, self._scratchpad)
        self._scratchpad.append(link)
        return delta

    def _handle_verdict(
        self, action: IssueVerdictAction
    ) -> Tuple[float, bool, Dict[str, Any]]:
        payload = VerdictPayload(
            conclusion=action.conclusion,
            rationale=action.rationale,
            evidence_chain=action.evidence_chain,
            scratchpad=self._scratchpad,
            task_id=self._task_id,
            flagged_tx_ids=self._extract_tx_ids(action),
        )
        grader = get_grader(self._task_id)
        score = grader.grade(payload)
        self._task_score = score

        evidence_complete = len(self._scratchpad) >= 3
        verdict_delta = self._reward.delta_verdict(score, evidence_complete)

        self._logger.log_end(
            self._episode_id,
            self._reward.clamp(self._cumulative_reward + verdict_delta),
            score,
            "verdict",
        )
        return verdict_delta, True, {"task_score": score, "verdict": action.conclusion}

    def _extract_tx_ids(self, action: IssueVerdictAction) -> list[str]:
        ids: list[str] = []
        for entry in action.evidence_chain:
            tx = entry.get("tx_id") or entry.get("transaction_id")
            if tx:
                ids.append(str(tx))
            for key in ("tx_ids", "duplicate_ids", "flagged_ids"):
                val = entry.get(key)
                if isinstance(val, list):
                    ids.extend(str(v) for v in val)
        return ids

    # ------------------------------------------------------------------
    # Observation builder
    # ------------------------------------------------------------------

    def _build_observation(self) -> AuditObservation:
        visible = self._get_visible_data()
        cid = self._company_data.company_id if self._company_data else "company_1"
        alerts = ANOMALY_ALERTS.get(cid, [])
        progress = min(1.0, self._step_count / MAX_STEPS)

        return AuditObservation(
            current_view=self._current_view,
            visible_data=visible,
            scratchpad=list(self._scratchpad),
            available_actions=AVAILABLE_ACTIONS,
            anomaly_alerts=alerts,
            investigation_progress=progress,
        )

    def _get_visible_data(self) -> Dict[str, Any]:
        if self._company_data is None:
            return {}
        cd = self._company_data
        view = self._current_view

        if view == "income_statement":
            data = cd.income_statement.model_dump()
            # Upgrade 3: enrich with narrative description for unstructured reasoning
            data["_narrative_summary"] = (
                f"Revenue of ${data['revenue']/1e6:.1f}M with operating margin "
                f"{data['operating_margin']*100:.1f}%. Net income ${data['net_income']/1e6:.1f}M."
            )
            return data
        elif view == "balance_sheet":
            data = cd.balance_sheet.model_dump()
            data["_narrative_summary"] = (
                f"Total assets ${data['total_assets']/1e6:.1f}M. "
                f"Accounts receivable ${data['accounts_receivable']/1e6:.1f}M "
                f"({data['accounts_receivable']/data['total_assets']*100:.1f}% of assets). "
                f"Equity ${data['equity']/1e6:.1f}M."
            )
            return data
        elif view == "cashflow":
            data = cd.cashflow.model_dump()
            ocf = data["operating_cash_flow"]
            data["_narrative_summary"] = (
                f"Operating cash flow ${ocf/1e6:.1f}M "
                f"({'positive — healthy cash generation' if ocf > 0 else 'NEGATIVE — cash burn despite reported profits'}). "
                f"Investing ${data['investing_cash_flow']/1e6:.1f}M, "
                f"Financing ${data['financing_cash_flow']/1e6:.1f}M."
            )
            return data
        elif view == "narrative":
            data = cd.narrative.model_dump()
            # Upgrade 3: add a flat text summary of all chunks for easier agent parsing
            data["_full_text"] = " | ".join(
                f"[{c['chunk_id']}] {c['text']}" for c in data.get("chunks", [])
            )
            return data
        elif view in ("general_ledger", "sub_ledger"):
            results = getattr(self, "_visible_query_results", [])
            return {
                "rows": results,
                "row_count": len(results),
                "hint": "Use query_ledger action to filter transactions. Filters: account_code, date_from, date_to, amount_min, amount_max, vendor_id",
            }
        return {}

    # ------------------------------------------------------------------
    # Data loader
    # ------------------------------------------------------------------

    def _load_company(self, company_id: str, company_dir: Path) -> CompanyData:
        from .models import BalanceSheet, CashFlow, IncomeStatement, Narrative

        def load(fname: str) -> dict:
            return json.loads((company_dir / fname).read_text())

        name_map = {
            "company_1": "TechCorp",
            "company_2": "RetailCo",
            "company_3": "ManufacturingInc",
            "company_4": "FinanceHub",
            "company_5": "HealthcarePlus",
        }

        return CompanyData(
            company_id=company_id,
            company_name=name_map.get(company_id, company_id),
            income_statement=IncomeStatement(**load("income_statement.json")),
            balance_sheet=BalanceSheet(**load("balance_sheet.json")),
            cashflow=CashFlow(**load("cashflow.json")),
            narrative=Narrative(**load("narrative.json")),
            ledger_db_path=company_dir / "ledger.db",
            sub_ledger_db_path=company_dir / "sub_ledger.db",
        )


# ---------------------------------------------------------------------------
# Custom exceptions (used by FastAPI layer)
# ---------------------------------------------------------------------------

class EpisodeActiveError(Exception):
    pass

class NoActiveEpisodeError(Exception):
    pass

class EpisodeDoneError(Exception):
    pass

class CompanyNotFoundError(Exception):
    pass
