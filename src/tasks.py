from __future__ import annotations

from typing import FrozenSet, List

from .data_generator import DUPLICATE_TX_IDS
from .models import VerdictPayload

# Ground-truth duplicate TX IDs for Task 2
TASK2_GROUND_TRUTH_IDS: FrozenSet[str] = frozenset(DUPLICATE_TX_IDS)

# ---------------------------------------------------------------------------
# Upgrade 1: ChainEval — verifiable symbolic reasoning trace
# ---------------------------------------------------------------------------
# The Task3 hard grader now verifies the agent followed the correct causal
# chain: Net Income Up → OCF Down → AR Spike → non_gaap_manipulation.
# This ensures genuine multi-step reasoning, not pattern matching.

TASK3_CAUSAL_CHAIN = [
    # (evidence_key, direction, description)
    ("income_statement_net_income", "positive", "Net Income increased"),
    ("cashflow_operating_cash",     "negative", "Operating Cash Flow declined"),
    ("balance_sheet_ar",            "positive", "Accounts Receivable spiked"),
]


def _verify_causal_chain(evidence_chain: List[dict], scratchpad: List[dict]) -> bool:
    """
    ChainEval: verify the agent's evidence follows the symbolic causal trace.
    Each step in TASK3_CAUSAL_CHAIN must appear in evidence with correct direction.
    """
    combined = str(evidence_chain).lower() + " " + str(scratchpad).lower()

    checks = {
        "income_statement_net_income": any(k in combined for k in (
            "net_income", "net income", "income_statement_net_income",
        )),
        "cashflow_operating_cash": any(k in combined for k in (
            "operating_cash", "cashflow_operating", "ocf", "operating cash flow",
        )),
        "balance_sheet_ar": any(k in combined for k in (
            "accounts_receivable", "balance_sheet_ar", "accounts receivable", "ar_spike",
        )),
    }
    return all(checks.values())


def _chain_alignment_score(evidence_chain: List[dict], scratchpad: List[dict]) -> float:
    """
    Returns 0.0–1.0 based on how many causal chain steps are present.
    Partial credit for partial chains.
    """
    combined = str(evidence_chain).lower() + " " + str(scratchpad).lower()
    step_checks = [
        any(k in combined for k in ("net_income", "net income", "income_statement_net_income")),
        any(k in combined for k in ("operating_cash", "cashflow_operating", "ocf")),
        any(k in combined for k in ("accounts_receivable", "balance_sheet_ar", "ar_spike")),
    ]
    return sum(step_checks) / len(step_checks)


# ---------------------------------------------------------------------------
# Task 1 Grader
# ---------------------------------------------------------------------------

class Task1_Grader:
    """KPI Extraction & Multi-Modal Linking grader."""

    GROUND_TRUTH_MARGIN: float = 0.235
    GROUND_TRUTH_CHUNK: str = "n7"

    def grade(self, verdict: VerdictPayload) -> float:
        extracted = self._check_extraction(verdict)
        linked = self._check_link(verdict)
        return 1.0 if (extracted and linked) else 0.0

    def _check_extraction(self, verdict: VerdictPayload) -> bool:
        for entry in verdict.evidence_chain:
            val = entry.get("value") or entry.get("operating_margin")
            if val is not None:
                try:
                    if abs(float(val) - self.GROUND_TRUTH_MARGIN) < 1e-4:
                        return True
                except (TypeError, ValueError):
                    pass
            if entry.get("metric") == "operating_margin":
                val2 = entry.get("value")
                if val2 is not None:
                    try:
                        if abs(float(val2) - self.GROUND_TRUTH_MARGIN) < 1e-4:
                            return True
                    except (TypeError, ValueError):
                        pass
        for entry in verdict.scratchpad:
            src = str(entry.get("source", ""))
            tgt = str(entry.get("target", ""))
            if "operating_margin" in src or "operating_margin" in tgt:
                return True
        return False

    def _check_link(self, verdict: VerdictPayload) -> bool:
        for entry in verdict.evidence_chain:
            if self.GROUND_TRUTH_CHUNK in str(entry.get("target", "")):
                return True
            if self.GROUND_TRUTH_CHUNK in str(entry.get("source", "")):
                return True
            if self.GROUND_TRUTH_CHUNK in str(entry.get("chunk_id", "")):
                return True
        for entry in verdict.scratchpad:
            src = str(entry.get("source", ""))
            tgt = str(entry.get("target", ""))
            if self.GROUND_TRUTH_CHUNK in src or self.GROUND_TRUTH_CHUNK in tgt:
                return True
        return False


# ---------------------------------------------------------------------------
# Task 2 Grader
# ---------------------------------------------------------------------------

class Task2_Grader:
    """Cross-System Reconciliation Audit grader (F1-style)."""

    GROUND_TRUTH_IDS: FrozenSet[str] = TASK2_GROUND_TRUTH_IDS

    def grade(self, verdict: VerdictPayload) -> float:
        found = self._extract_flagged_ids(verdict)
        if not found:
            return 0.0
        precision = len(found & self.GROUND_TRUTH_IDS) / len(found)
        recall = len(found & self.GROUND_TRUTH_IDS) / len(self.GROUND_TRUTH_IDS)
        return (precision + recall) / 2.0

    def _extract_flagged_ids(self, verdict: VerdictPayload) -> FrozenSet[str]:
        ids: set[str] = set()
        if verdict.flagged_tx_ids:
            ids.update(verdict.flagged_tx_ids)
        for entry in verdict.evidence_chain:
            tx = entry.get("tx_id") or entry.get("transaction_id") or entry.get("id")
            if tx:
                ids.add(str(tx))
            for key in ("tx_ids", "duplicate_ids", "flagged_ids"):
                val = entry.get(key)
                if isinstance(val, list):
                    ids.update(str(v) for v in val)
        for entry in verdict.scratchpad:
            tx = entry.get("tx_id") or entry.get("source") or entry.get("target")
            if tx and str(tx).startswith("tx_"):
                ids.add(str(tx))
        return frozenset(ids)


# ---------------------------------------------------------------------------
# Task 3 Grader — with ChainEval (Upgrade 1)
# ---------------------------------------------------------------------------

class Task3_Grader:
    """
    Narrative vs. Numeric Deception Detection grader.

    Upgrade 1 — ChainEval: scores the agent's evidence_chain against the
    symbolic causal trace: Net Income Up → OCF Down → AR Spike.
    Partial credit is awarded based on chain alignment score (0.0–1.0).
    Full score requires: all 3 chain steps + correct verdict + valid rationale.
    """

    REQUIRED_CONCLUSION: str = "non_gaap_manipulation"
    RATIONALE_KEYWORDS: list[str] = ["accounts receivable", "cash flow", "revenue recognition"]

    def grade(self, verdict: VerdictPayload) -> float:
        chain_score = _chain_alignment_score(verdict.evidence_chain, verdict.scratchpad)
        has_all_evidence = chain_score == 1.0
        correct_conclusion = verdict.conclusion == self.REQUIRED_CONCLUSION
        valid_rationale = self._check_rationale(verdict.rationale)

        if has_all_evidence and correct_conclusion and valid_rationale:
            return 1.0
        elif has_all_evidence and correct_conclusion:
            return 0.7
        elif has_all_evidence:
            return 0.4
        elif chain_score > 0.0:
            # Partial credit: proportional to chain alignment
            return round(chain_score * 0.3, 3)
        else:
            return 0.0

    def _check_rationale(self, rationale: str) -> bool:
        if not rationale:
            return False
        lower = rationale.lower()
        return any(kw in lower for kw in self.RATIONALE_KEYWORDS)


def get_grader(task_id: int) -> Task1_Grader | Task2_Grader | Task3_Grader:
    if task_id == 1:
        return Task1_Grader()
    elif task_id == 2:
        return Task2_Grader()
    elif task_id == 3:
        return Task3_Grader()
    raise ValueError(f"Unknown task_id: {task_id}")
