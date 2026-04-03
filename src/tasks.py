from __future__ import annotations

from typing import FrozenSet

from .data_generator import DUPLICATE_TX_IDS
from .models import VerdictPayload

# Ground-truth duplicate TX IDs for Task 2
TASK2_GROUND_TRUTH_IDS: FrozenSet[str] = frozenset(DUPLICATE_TX_IDS)


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
        # From flagged_tx_ids field
        if verdict.flagged_tx_ids:
            ids.update(verdict.flagged_tx_ids)
        # From evidence_chain entries
        for entry in verdict.evidence_chain:
            tx = entry.get("tx_id") or entry.get("transaction_id") or entry.get("id")
            if tx:
                ids.add(str(tx))
            # Also check lists
            for key in ("tx_ids", "duplicate_ids", "flagged_ids"):
                val = entry.get(key)
                if isinstance(val, list):
                    ids.update(str(v) for v in val)
        # From scratchpad
        for entry in verdict.scratchpad:
            tx = entry.get("tx_id") or entry.get("source") or entry.get("target")
            if tx and str(tx).startswith("tx_"):
                ids.add(str(tx))
        return frozenset(ids)


class Task3_Grader:
    """Narrative vs. Numeric Deception Detection grader (partial scoring)."""

    REQUIRED_CONCLUSION: str = "non_gaap_manipulation"
    RATIONALE_KEYWORDS: list[str] = ["accounts receivable", "cash flow", "revenue recognition"]

    def grade(self, verdict: VerdictPayload) -> float:
        has_evidence = self._check_evidence(verdict)
        correct_conclusion = verdict.conclusion == self.REQUIRED_CONCLUSION
        valid_rationale = self._check_rationale(verdict.rationale)

        if has_evidence and correct_conclusion and valid_rationale:
            return 1.0
        elif has_evidence and correct_conclusion:
            return 0.7
        elif has_evidence:
            return 0.4
        else:
            return 0.0

    def _check_evidence(self, verdict: VerdictPayload) -> bool:
        chain_str = str(verdict.evidence_chain).lower()
        scratchpad_str = str(verdict.scratchpad).lower()
        combined = chain_str + " " + scratchpad_str

        has_net_income = any(k in combined for k in (
            "net_income", "net income", "income_statement_net_income",
        ))
        has_ocf = any(k in combined for k in (
            "operating_cash", "cashflow_operating", "ocf", "operating cash flow",
        ))
        has_ar = any(k in combined for k in (
            "accounts_receivable", "balance_sheet_ar", "accounts receivable", "ar_spike",
        ))
        return has_net_income and has_ocf and has_ar

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
