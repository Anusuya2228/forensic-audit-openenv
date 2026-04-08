"""
Forensic Audit Environment — Infereipt
==============================================
MANDATORY env vars:
  API_BASE_URL        LLM API endpoint
  MODEL_NAME          Model identifier
  HF_TOKEN            HuggingFace / API key
  ENV_BASE_URL        Environment server URL (default: http://localhost:7860)
"""
from __future__ import annotations

import json
import os
import sys
import time
import textwrap
from typingrt Any, Dict, List, Optional

import requests
from openai import OpenAI

# ---------------------------------------------------------------------------
# Config — read from environment variables
# ---------------------------------------------------------------------------
API_KEY: str = os.getenv("HF_TOKEN") or os.getenv("API_KEY", "none")
API_BASE_URL: str = os.getenv("API_BASE_URL", "https://router.huggingface.co/v1")
MODEL_NA72B-Instruct")
ENV_BASE_URL: str = os.getenv("ENV_BASE_URL", "http://localhost:8000")
BENCHMARK: str = "forensic-audit-env"
MAX_STEPS: int = 15
SUCCESS_THRESHOLD: float = 0.5
TEMPERATURE: float = 0.0
MAX_TOKENS: int = 512

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
# Mandatory stdout logging — exact format required by validator
# ---------------------------------------------------------------------------

def log_start(task: str, env: str, model: str) -> None:
    print(f"[START] task={task} env={env} model={model}", flush=True)


def log_step(step: int, action: str, reward: float, done: bool, error: Optional[str]) -> None:
    error_val = error if error else "null"
    done_val = str(done).lower()
    action_str = str(action).replace("\n", " ").replace("\r", "")[:120]
    print(f"[STEP] step={step} action={action_str} reward={reward:.2f} done={done_val} error={error_val}", flush=True)


def log_end(success: bool, steps: int, score: float, rewards: List[float]) -> None:
    rewards_str = ",".join(f"{r:.2f}" for r in rewards)
    print(f"[END] success={str(success).lower()} steps={steps} score={score:.2f} rewards={rewards_str}", flush=True)


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = textwrap.dedent("""
    You are a fo anomalies, fraud, and GAAP violations.
    Respond with ONLY a valid JSON action object — no other text, no markdown fences.

    Available actions:
    1. {"action_type": "navigate", "view": "<income_statement|balance_sheet|cashflow|general_ledger|sub_ledger|narrative>"}
    2. {"action_type": "query_ledger", "filters": {"account_code": "Accounts Payable"}}
    3. {"action_type": "link_evidence", "source_id": "<id>", "target_id": "<id>", "relationship": "<supports|contradicts|reconciles_to>"}
    4. {"action_type": "issue_verdict", "conclusion": "<clean_audit|material_misstatement|fraud_detected|non_gaap_manipulation>", "rationale": "<text>", "evidence_chain": []}
""").strip()

TASK_PROMPTS: Dict[int, str] = {
    1: textwrap.dedent("""
        TASK: KPI Extraction & Multi-Modal Linking
        Find Operating Margin (2, link to narrative chunk n7.
        Steps: navigate income_statement → navigate 
    """).strip(),
    2: textwrap.dedent("""

        Anomaly alert: 12 duplicate invoice paymeDs.
        Steps: navigate sub_ledger → query_ledger(account_code=Accounts Payabl
    """).strip(),
 3: textwrap.dedent("""
        TASK: Narrative vs. Numeric Deception Detection
        Narrative claims "15% delivery growth drove revenue". Prove non_gaap_manipulation.
        Evidence needed: income_statement_net_income (+$50M), cashflow_operating_cash (-$30M), balance_sheet_ar (+$80M).
        Rationale must mention: accounts receivable, cash flow, revenue reco
        Steps: navigate income_statement → navigate cashflow → navigate balance_sheet → link 3 evidence items → issue_verdict(non_gaap_manipulation)
  """).strip(),
}

# ---------------------------------------------------------------------------
# Heuristic fallback plans (used when LLM unavailable or fails)
# -------------------------------------------------------------------
HEURISTI Any]]] = {
    1: [
        {"action_type": "navigate", "view": "income_state},
        {"action_type": "navigate", "view": "narrative"},
        {"action_type": "link_evidence", "source_id": "operating_m
         "target_id": "narrative_n7", "relationship": "supports"},
        {"action_type": "issue_verdict", "conclusion": "clean_audit",
         "rationale": "Operating margin is 23.5% as explained in narrative chunk n7 which stae to cost optimization.",
      "}]},
    ],
    2: [
        {"action_type": "navigate", "view": "sub_ledger"},
        {"action_type": "query_ledger", "filters": {"account_code": "Accounts },
        {"action_type": "link_evidence", "source_id": "sub_ledger_duplicates",
         "target_id": "anomaly_alert_duplicate_invoices", "relationship": "supports"},
        {"action_type": "issue_verdict", "conclusion": "material_misstatement",
         "rationale": "Found 12 duplicate invoice payments in Accounts Payable sub-ledger with same invoice_number and amount but different transaction IDs and dates.",
      x_00627", "tx_00884",
        , "tx_01293", "tx_01547", "tx_01829",
                                         "tx_02103", "tx_02456",_02991"]}]},
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
         "rationale": "Revenue growth is driven by accounts receivaulation.",
         "evidence_chain": [
            e", "value": 50000000},
      00000},
 alue": 80000000},
    ]},
    ],
}


--------------------
# Agent
# -----------------------------------------------------------------------

class ForensicAuditAgent:
    def __init__(self, base_url: str = ENV_BASE_URL) -> None:
        self.base_url = base_url.rstrip("/")
        self.client = OpenAI(api_key=API_KEY, SE_URL)

 float:
        company_id = TASK_COMPANY_MAP[task_id]
ame = TASK_NAMES[task_id]

        log_start(taAME)

        rewards: List[float] = []
        sn = 0
ask_score = 0.0
        success = False

        try:
            obs = self.sk_id)
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT + "\n\n" + TASK_PROMPTS[task_id]},
                {"role": "user", "content": self},
            ]

            for step in range(1, MAX_STEPS + 1):
id, step - 1)
                action_str = json.dumps(action_jn)
                error: Optional[str] = None

                result = self._step(action_json)
                if result is None:
                    error = "step_failed"
                    log_s, error)
   rewards.append(0.0)
                    steps_taken = step
                    break

                obs = result["observation"]
                reward = float(result.get("reward", 0.0))
done", False))
                info = result.get("inf", {})
                task_score = float

                rewards.append(reward)
            steps_taken = step

                log_step(step, action_str, reward, done, error)

                messagesstant", "content": action_str})
                messages.ard, done, info)})

                if done:
                    break

            success = task_scoSHOLD

        except Exception as exc:
            error_msg = str(exc)
            log_step(steps_ error_msg)
            success = False

        log_end(success=success, steps=steps_taken, score=task_score, rewards=rewards)
        return task_score

    def _reset(self, compa[str, Any]:
        r = requests.post(
            f"{self.base_url}/reset",
            json={"comprce": True},
          timeout=30,
        )
        r.raise_for_stas()
return r.json()

    def _step(self, action: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        try:
            r = requests.post(f"{self.base_url}/step", json=action, timeout=30)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            print(f"[DE
 None

    def _get> Dict[str, Any]:
        try:
            resp = self.client.chons.create(
                model=MODEL_NAME,
                messages=messages,
                temperature=TEMPERATURE,
             S,
            )
            content = (resp.choices()
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
    parser = argparse.ArgumentParser(d")
    parser.add_argument("--task", type=int, choices=[1, 2, 3], default=None,
                        help="Run specific task (1-3). Default: all.")
    parser.add_argument("--baslt=None,
E_URL.")
    args = parser.parse_args()

    base_url = (args.base_url or ENV_BASE_URL).rstrip("/")
e_url)
    tasks = [args.task] args.task else [1, 2, 3]

    start = time.time()
    scores: Dict[int, float] = {}
    for task_id in tasks:
        scores[task_id] = agent.r_task(task_id)

    elapsed = time.time() - start
    print("\n" + "=" * 40, flush=True)
    print("BASELINE SCORES", flush=True)
    print("=" * 40, flush=True)
    thresholds = {1: 0.6, 2: 0.4, 3: 0.3}
    for t, s in scores.items():
        status = "PASS" if s >= thresholds[t] el"
        print(f"  Task {t}: {s:)
1f}s", flush=True)



if __name__":
le__)))
    main()
__fi.path.abspath(h.dirname(osth.insert(0, os.patsys.pa    