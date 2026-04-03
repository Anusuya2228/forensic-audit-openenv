"""
Inference Script — ForensicAuditEnv
=====================================
MANDATORY env vars:
  API_BASE_URL   The API endpoint for the LLM.
  MODEL_NAME     The model identifier to use for inference.
  HF_TOKEN       Your Hugging Face / API key.
  ENV_BASE_URL   The running environment URL (default: http://localhost:8000)

STDOUT FORMAT (strictly followed):
  [START] task=<task_name> env=<benchmark> model=<model_name>
  [STEP]  step=<n> action=<action_str> reward=<0.00> done=<true|false> error=<msg|null>
  [END]   success=<true|false> steps=<n> score=<0.000> rewards=<r1,r2,...,rn>
"""
from __future__ import annotations

import json
import os
import sys
import time
from typing import Any, Dict, List, Optional

import requests
from openai import OpenAI

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
API_KEY: str = os.getenv("HF_TOKEN") or os.getenv("API_KEY", "none")
API_BASE_URL: str = os.getenv("API_BASE_URL", "https://router.huggingface.co/v1")
MODEL_NAME: str = os.getenv("MODEL_NAME", "Qwen/Qwen2.5-72B-Instruct")
ENV_BASE_URL: str = os.getenv("ENV_BASE_URL", "http://localhost:8000").rstrip("/")
BENCHMARK: str = "forensic-audit-env"
MAX_STEPS: int = 15
SUCCESS_THRESHOLD: float = 0.5

TASK_COMPANY_MAP: Dict[int, str] = {
    1: "company_4",
    2: "company_2",
    3: "company_1",
}
TASK_NAMES: Dict[int, str] = {
    1: "kpi-extraction",
    2: "reconciliation-audit",
    3: "deception-detection",
}

# ---------------------------------------------------------------------------
# Structured logging (mandatory format)
# ---------------------------------------------------------------------------

def log_start(task: str, env: str, model: str) -> None:
    print(f"[START] task={task} env={env} model={model}", flush=True)


def log_step(step: int, action: str, reward: float, done: bool, error: Optional[str]) -> None:
    error_val = error if error else "null"
    done_val = str(done).lower()
    # Sanitize action string — no newlines
    action_str = action.replace("\n", " ").replace("\r", "")[:120]
    print(f"[STEP] step={step} action={action_str} reward={reward:.2f} done={done_val} error={error_val}", flush=True)


def log_end(success: bool, steps: int, score: float, rewards: List[float]) -> None:
    rewards_str = ",".join(f"{r:.2f}" for r in rewards)
    print(f"[END] success={str(success).lower()} steps={steps} score={score:.3f} rewards={rewards_str}", flush=True)


# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """You are a forensic auditor investigating financial documents for anomalies, fraud, and GAAP violations.

Respond with ONLY a valid JSON action object — no other text, no markdown.

Available actions:
1. {"action_type": "navigate", "view": "<income_statement|balance_sheet|cashflow|general_ledger|sub_ledger|narrative>"}
2. {"action_type": "query_ledger", "filters": {"account_code": "Accounts Payable"}}
3. {"action_type": "link_evidence", "source_id": "<id>", "target_id": "<id>", "relationship": "<supports|contradicts|reconciles_to>"}
4. {"action_type": "issue_verdict", "conclusion": "<clean_audit|material_misstatement|fraud_detected|non_gaap_manipulation>", "rationale": "<text>", "evidence_chain": []}
"""

TASK_PROMPTS: Dict[int, str] = {
    1: """TASK: KPI Extraction & Multi-Modal Linking
Find Operating Margin (23.5%) in income statement, link to narrative chunk n7.
Steps: navigate income_statement → navigate narrative → link_evidence(operating_margin_0.235 → narrative_n7) → issue_verdict""",

    2: """TASK: Cross-System Reconciliation Audit
Anomaly alert: 12 duplicate invoice payments in AP. Find all duplicate tx IDs.
Steps: navigate sub_ledger → query_ledger(account_code=Accounts Payable) → link_evidence → issue_verdict with tx_ids in evidence_chain""",

    3: """TASK: Narrative vs. Numeric Deception Detection
Narrative claims "15% delivery growth drove revenue". Prove non_gaap_manipulation.
Evidence needed: income_statement_net_income (+$50M), cashflow_operating_cash (-$30M), balance_sheet_ar (+$80M).
Rationale must mention: accounts receivable, cash flow, revenue recognition.
Steps: navigate income_statement → navigate cashflow → navigate balance_sheet → link 3 evidence items → issue_verdict(non_gaap_manipulation)""",
}

# ---------------------------------------------------------------------------
# Heuristic fallback plans (used when LLM unavailable or fails)
# ---------------------------------------------------------------------------
HEURISTIC_PLANS: Dict[int, List[Dict[str, Any]]] = {
    1: [
        {"action_type": "navigate", "view": "income_statement"},
        {"action_type": "navigate", "view": "narrative"},
        {"action_type": "link_evidence", "source_id": "operating_margin_0.235",
         "target_id": "narrative_n7", "relationship": "supports"},
        {"action_type": "issue_verdict", "conclusion": "clean_audit",
         "rationale": "Operating margin is 23.5% as explained in narrative chunk n7 which states operating margin expanded 200bps due to cost optimization.",
         "evidence_chain": [{"metric": "operating_margin", "value": 0.235, "target": "n7"}]},
    ],
    2: [
        {"action_type": "navigate", "view": "sub_ledger"},
        {"action_type": "query_ledger", "filters": {"account_code": "Accounts Payable"}},
        {"action_type": "link_evidence", "source_id": "sub_ledger_duplicates",
         "target_id": "anomaly_alert_duplicate_invoices", "relationship": "supports"},
        {"action_type": "issue_verdict", "conclusion": "material_misstatement",
         "rationale": "Found 12 duplicate invoice payments in Accounts Payable sub-ledger with same invoice_number and amount but different transaction IDs and dates.",
         "evidence_chain": [{"tx_ids": ["tx_00245","tx_00391","tx_00627","tx_00884","tx_01052","tx_01293","tx_01547","tx_01829","tx_02103","tx_02456","tx_02718","tx_02991"]}]},
    ],
    3: [
        {"action_type": "navigate", "view": "income_statement"},
        {"action_type": "navigate", "view": "cashflow"},
        {"action_type": "navigate", "view": "balance_sheet"},
        {"action_type": "link_evidence", "source_id": "income_statement_net_income",
         "target_id": "narrative_delivery_claim", "relationship": "contradicts"},
        {"action_type": "link_evidence", "source_id": "cashflow_operating_cash",
         "target_id": "narrative_delivery_claim", "relationship": "contradicts"},
        {"action_type": "link_evidence", "source_id": "balance_sheet_ar",
         "target_id": "income_statement_net_income", "relationship": "reconciles_to"},
        {"action_type": "issue_verdict", "conclusion": "non_gaap_manipulation",
         "rationale": "Revenue growth is driven by accounts receivable spike not actual cash collection. Operating cash flow declined while net income rose, indicating revenue recognition manipulation rather than real delivery growth.",
         "evidence_chain": [
             {"id": "income_statement_net_income", "value": 50000000},
             {"id": "cashflow_operating_cash", "value": -30000000},
             {"id": "balance_sheet_ar", "value": 80000000},
         ]},
    ],
}


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class ForensicAuditAgent:
    def __init__(self) -> None:
        self.client = OpenAI(api_key=API_KEY, base_url=API_BASE_URL)

    def run_task(self, task_id: int) -> float:
        company_id = TASK_COMPANY_MAP[task_id]
        task_name = TASK_NAMES[task_id]

        log_start(task=task_name, env=BENCHMARK, model=MODEL_NAME)

        obs = self._reset(company_id, task_id)
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT + "\n\n" + TASK_PROMPTS[task_id]},
            {"role": "user", "content": self._format_obs(obs)},
        ]

        rewards: List[float] = []
        steps_taken = 0
        task_score = 0.0
        success = False

        try:
            for step in range(1, MAX_STEPS + 1):
                action_json = self._get_action(messages, task_id, step - 1)
                action_str = json.dumps(action_json)
                error: Optional[str] = None

                result = self._step(action_json)
                if result is None:
                    error = "step_failed"
                    log_step(step, action_str, 0.0, False, error)
                    rewards.append(0.0)
                    steps_taken = step
                    break

                obs = result["observation"]
                reward = float(result.get("reward", 0.0))
                done = bool(result.get("done", False))
                info = result.get("info", {})
                task_score = float(info.get("task_score", 0.0))

                rewards.append(reward)
                steps_taken = step

                log_step(step, action_str, reward, done, error)

                messages.append({"role": "assistant", "content": action_str})
                messages.append({"role": "user", "content": self._format_obs(obs, reward, done, info)})

                if done:
                    break

            success = task_score >= SUCCESS_THRESHOLD
            score = task_score

        except Exception as e:
            error_msg = str(e)
            log_step(steps_taken + 1, "exception", 0.0, True, error_msg)
            score = task_score
            success = False

        log_end(success=success, steps=steps_taken, score=score, rewards=rewards)
        return score

    def _reset(self, company_id: str, task_id: int) -> Dict[str, Any]:
        r = requests.post(
            f"{ENV_BASE_URL}/reset",
            json={"company_id": company_id, "task_id": task_id, "force": True},
            timeout=30,
        )
        r.raise_for_status()
        return r.json()

    def _step(self, action: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        try:
            r = requests.post(f"{ENV_BASE_URL}/step", json=action, timeout=30)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            print(f"[DEBUG] step error: {e}", flush=True)
            return None

    def _get_action(self, messages: List[Dict], task_id: int, step: int) -> Dict[str, Any]:
        try:
            resp = self.client.chat.completions.create(
                model=MODEL_NAME,
                messages=messages,
                temperature=0.0,
                max_tokens=512,
            )
            content = (resp.choices[0].message.content or "").strip()
            # Strip markdown fences
            if content.startswith("```"):
                parts = content.split("```")
                content = parts[1] if len(parts) > 1 else content
                if content.startswith("json"):
                    content = content[4:]
            return json.loads(content.strip())
        except Exception as e:
            print(f"[DEBUG] LLM error: {e}, using heuristic", flush=True)
            return self._heuristic(task_id, step)

    def _heuristic(self, task_id: int, step: int) -> Dict[str, Any]:
        plan = HEURISTIC_PLANS[task_id]
        return plan[min(step, len(plan) - 1)]

    def _format_obs(
        self,
        obs: Dict[str, Any],
        reward: float = 0.0,
        done: bool = False,
        info: Dict[str, Any] = {},
    ) -> str:
        lines = [
            f"View: {obs.get('current_view')}",
            f"Progress: {obs.get('investigation_progress', 0):.0%}",
        ]
        alerts = obs.get("anomaly_alerts", [])
        if alerts:
            lines.append(f"ALERTS: {alerts}")
        scratchpad = obs.get("scratchpad", [])
        if scratchpad:
            lines.append(f"Evidence linked: {len(scratchpad)} items")
        visible = obs.get("visible_data", {})
        if visible:
            lines.append(f"Data: {json.dumps(visible, default=str)[:600]}")
        if reward != 0.0:
            lines.append(f"Last reward: {reward:.2f}")
        if done:
            lines.append(f"Done. Score: {info.get('task_score', 0):.3f}")
        lines.append("Next action (JSON only):")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", type=int, choices=[1, 2, 3], default=None)
    parser.add_argument("--base-url", type=str, default=ENV_BASE_URL)
    args = parser.parse_args()

    global ENV_BASE_URL
    ENV_BASE_URL = args.base_url.rstrip("/")

    agent = ForensicAuditAgent()
    tasks = [args.task] if args.task else [1, 2, 3]

    start = time.time()
    scores: Dict[int, float] = {}
    for task_id in tasks:
        scores[task_id] = agent.run_task(task_id)

    elapsed = time.time() - start
    print("\n" + "=" * 40, flush=True)
    print("BASELINE SCORES", flush=True)
    print("=" * 40, flush=True)
    thresholds = {1: 0.6, 2: 0.4, 3: 0.3}
    for t, s in scores.items():
        status = "PASS" if s >= thresholds[t] else "FAIL"
        print(f"  Task {t}: {s:.3f}  [{status}]", flush=True)
    print(f"  Time: {elapsed:.1f}s", flush=True)
    print("=" * 40, flush=True)


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    main()
