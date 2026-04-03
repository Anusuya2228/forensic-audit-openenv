from __future__ import annotations

import json
import random
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

# Ground-truth duplicate TX IDs for Task 2 (RetailCo / company_2)
DUPLICATE_TX_IDS: List[str] = [
    "tx_00245", "tx_00391", "tx_00627", "tx_00884", "tx_01052", "tx_01293",
    "tx_01547", "tx_01829", "tx_02103", "tx_02456", "tx_02718", "tx_02991",
]

ACCOUNTS = [
    "Accounts Payable", "Accounts Receivable", "Cash", "Revenue",
    "Cost of Goods Sold", "Operating Expenses", "Payroll", "Depreciation",
    "Interest Expense", "Tax Expense",
]

VENDORS = [f"vendor_{i:03d}" for i in range(1, 51)]


@dataclass
class CompanySpec:
    company_id: str
    name: str
    anomaly: Optional[str]  # "ar_spike" | "duplicate_invoices" | "negative_ocf" | None


COMPANIES: List[CompanySpec] = [
    CompanySpec("company_1", "TechCorp",        "ar_spike"),
    CompanySpec("company_2", "RetailCo",         "duplicate_invoices"),
    CompanySpec("company_3", "ManufacturingInc", "negative_ocf"),
    CompanySpec("company_4", "FinanceHub",       "task1_kpi"),
    CompanySpec("company_5", "HealthcarePlus",   None),
]


class DataGenerator:
    def __init__(self, seed: int = 42) -> None:
        self._seed = seed
        self._rng = random.Random(seed)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate_all(self, output_dir: Path) -> None:
        output_dir = Path(output_dir)
        for spec in COMPANIES:
            company_dir = output_dir / spec.company_id
            company_dir.mkdir(parents=True, exist_ok=True)
            self._rng = random.Random(self._seed + hash(spec.company_id) % 10000)
            self._generate_company(spec, company_dir)
        self._validate_planted_anomalies(output_dir)

    # ------------------------------------------------------------------
    # Per-company generation
    # ------------------------------------------------------------------

    def _generate_company(self, spec: CompanySpec, out: Path) -> None:
        is_task1  = spec.anomaly == "task1_kpi"
        is_task3  = spec.anomaly == "ar_spike"
        is_task2  = spec.anomaly == "duplicate_invoices"
        is_neg_ocf = spec.anomaly == "negative_ocf"

        # --- income statement ---
        revenue = round(self._rng.uniform(500e6, 2000e6), 2)
        if is_task1:
            op_margin = 0.235
            op_income = round(revenue * op_margin, 2)
        else:
            op_margin = round(self._rng.uniform(0.08, 0.30), 4)
            op_income = round(revenue * op_margin, 2)

        cogs = round(revenue * self._rng.uniform(0.35, 0.55), 2)
        op_expenses = round(revenue - cogs - op_income, 2)
        net_income_base = round(op_income * self._rng.uniform(0.6, 0.85), 2)
        if is_task3:
            net_income = round(net_income_base + 50_000_000, 2)
        else:
            net_income = net_income_base

        income_stmt = {
            "company": spec.name,
            "period": "FY2024",
            "revenue": revenue,
            "operating_income": op_income,
            "net_income": net_income,
            "operating_margin": op_margin,
        }
        self._write_json(out / "income_statement.json", income_stmt)

        # --- balance sheet ---
        total_assets = round(revenue * self._rng.uniform(0.8, 1.5), 2)
        ar_base = round(revenue * self._rng.uniform(0.08, 0.15), 2)
        if is_task3:
            accounts_receivable = round(ar_base + 80_000_000, 2)
        else:
            accounts_receivable = ar_base
        ap = round(revenue * self._rng.uniform(0.05, 0.12), 2)
        total_liabilities = round(total_assets * self._rng.uniform(0.35, 0.65), 2)
        equity = round(total_assets - total_liabilities, 2)

        balance_sheet = {
            "company": spec.name,
            "period": "FY2024",
            "total_assets": total_assets,
            "accounts_receivable": accounts_receivable,
            "total_liabilities": total_liabilities,
            "equity": equity,
            "accounts_payable": ap,
        }
        self._write_json(out / "balance_sheet.json", balance_sheet)

        # --- cash flow ---
        ocf_base = round(net_income * self._rng.uniform(0.7, 1.1), 2)
        if is_task3:
            ocf = round(ocf_base - 30_000_000, 2)
        elif is_neg_ocf:
            ocf = round(-abs(ocf_base) - self._rng.uniform(5e6, 20e6), 2)
        else:
            ocf = ocf_base
        icf = round(-revenue * self._rng.uniform(0.05, 0.15), 2)
        fcf = round(self._rng.uniform(-50e6, 50e6), 2)

        cashflow = {
            "company": spec.name,
            "period": "FY2024",
            "operating_cash_flow": ocf,
            "investing_cash_flow": icf,
            "financing_cash_flow": fcf,
        }
        self._write_json(out / "cashflow.json", cashflow)

        # --- narrative ---
        narrative = self._generate_narrative(spec, op_margin, net_income, ocf, accounts_receivable)
        self._write_json(out / "narrative.json", narrative)

        # --- ledger DB ---
        ledger_path = out / "ledger.db"
        self._generate_ledger_db(ledger_path, spec)

        # --- sub-ledger DB ---
        sub_ledger_path = out / "sub_ledger.db"
        self._generate_sub_ledger_db(sub_ledger_path, spec)

    # ------------------------------------------------------------------
    # Narrative generation
    # ------------------------------------------------------------------

    def _generate_narrative(
        self, spec: CompanySpec, op_margin: float, net_income: float, ocf: float, ar: float
    ) -> dict:
        is_task1   = spec.anomaly == "task1_kpi"
        is_task3   = spec.anomaly == "ar_spike"
        is_neg_ocf = spec.anomaly == "negative_ocf"

        chunks = []

        chunks.append({
            "chunk_id": "n1",
            "text": f"Revenue grew 15% YoY driven by strong demand across all segments.",
            "referenced_kpis": ["revenue"],
        })
        chunks.append({
            "chunk_id": "n2",
            "text": f"Net income reached ${net_income/1e6:.1f}M, reflecting disciplined cost management.",
            "referenced_kpis": ["net_income"],
        })
        chunks.append({
            "chunk_id": "n3",
            "text": "The company continued to invest in R&D and capital expenditures.",
            "referenced_kpis": [],
        })
        chunks.append({
            "chunk_id": "n4",
            "text": "Accounts payable increased modestly as supplier terms were renegotiated.",
            "referenced_kpis": ["accounts_payable"],
        })
        chunks.append({
            "chunk_id": "n5",
            "text": "Gross margin remained stable at approximately 45%, in line with prior year.",
            "referenced_kpis": ["gross_margin"],
        })
        chunks.append({
            "chunk_id": "n6",
            "text": "The balance sheet remains strong with a healthy equity ratio.",
            "referenced_kpis": ["equity"],
        })

        if is_task1:
            chunks.append({
                "chunk_id": "n7",
                "text": "Operating margin expanded 200bps due to cost optimization, reaching 23.5%.",
                "referenced_kpis": ["operating_margin"],
            })
        else:
            chunks.append({
                "chunk_id": "n7",
                "text": f"Operating margin was {op_margin*100:.1f}%, reflecting ongoing efficiency initiatives.",
                "referenced_kpis": ["operating_margin"],
            })

        if is_neg_ocf:
            chunks.append({
                "chunk_id": "n8",
                "text": "The company demonstrated strong cash generation with robust operating cash flows.",
                "referenced_kpis": ["operating_cash_flow"],
            })
        else:
            chunks.append({
                "chunk_id": "n8",
                "text": f"Operating cash flow was ${ocf/1e6:.1f}M, supporting ongoing investment activities.",
                "referenced_kpis": ["operating_cash_flow"],
            })

        if is_task3:
            chunks.append({
                "chunk_id": "n9",
                "text": "A healthy 15% increase in vehicle deliveries drove revenue growth this quarter.",
                "referenced_kpis": ["revenue", "deliveries"],
            })
            chunks.append({
                "chunk_id": "n10",
                "text": f"Accounts receivable increased to ${ar/1e6:.1f}M as new enterprise contracts were signed.",
                "referenced_kpis": ["accounts_receivable"],
            })
        else:
            chunks.append({
                "chunk_id": "n9",
                "text": "Customer acquisition costs declined year-over-year, improving unit economics.",
                "referenced_kpis": [],
            })
            chunks.append({
                "chunk_id": "n10",
                "text": "Management remains focused on long-term value creation for shareholders.",
                "referenced_kpis": [],
            })

        return {"company": spec.name, "period": "FY2024", "chunks": chunks}

    # ------------------------------------------------------------------
    # SQLite ledger generation
    # ------------------------------------------------------------------

    def _generate_ledger_db(self, db_path: Path, spec: CompanySpec) -> None:
        if db_path.exists():
            db_path.unlink()
        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE transactions (
                tx_id TEXT PRIMARY KEY,
                date TEXT NOT NULL,
                account TEXT NOT NULL,
                debit REAL NOT NULL DEFAULT 0,
                credit REAL NOT NULL DEFAULT 0,
                description TEXT,
                invoice_number TEXT
            )
        """)
        n_rows = self._rng.randint(500, 1000)
        rows = []
        for i in range(n_rows):
            tx_id = f"gl_{spec.company_id}_{i:05d}"
            date = self._random_date()
            account = self._rng.choice(ACCOUNTS)
            amount = round(self._rng.uniform(100, 500_000), 2)
            debit = amount if self._rng.random() > 0.5 else 0.0
            credit = amount if debit == 0.0 else 0.0
            desc = f"Transaction {i} for {account}"
            inv = f"INV-{self._rng.randint(10000, 99999)}"
            rows.append((tx_id, date, account, debit, credit, desc, inv))
        cur.executemany(
            "INSERT INTO transactions VALUES (?,?,?,?,?,?,?)", rows
        )
        conn.commit()
        conn.close()

    def _generate_sub_ledger_db(self, db_path: Path, spec: CompanySpec) -> None:
        if db_path.exists():
            db_path.unlink()
        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE sub_ledger (
                tx_id TEXT PRIMARY KEY,
                vendor TEXT NOT NULL,
                invoice_number TEXT NOT NULL,
                amount REAL NOT NULL,
                date TEXT NOT NULL,
                payment_date TEXT,
                status TEXT NOT NULL DEFAULT 'paid',
                account TEXT NOT NULL DEFAULT 'Accounts Payable'
            )
        """)
        n_rows = self._rng.randint(200, 400)
        rows = []
        used_ids: set = set()

        for i in range(n_rows):
            tx_id = f"sl_{spec.company_id}_{i:05d}"
            used_ids.add(tx_id)
            vendor = self._rng.choice(VENDORS)
            inv = f"INV-SL-{self._rng.randint(10000, 99999)}"
            amount = round(self._rng.uniform(500, 200_000), 2)
            date = self._random_date()
            payment_date = self._random_date()
            rows.append((tx_id, vendor, inv, amount, date, payment_date, "paid", "Accounts Payable"))

        if spec.anomaly == "duplicate_invoices":
            rows = self._plant_duplicate_invoices(rows, used_ids)

        cur.executemany(
            "INSERT INTO sub_ledger VALUES (?,?,?,?,?,?,?,?)", rows
        )
        conn.commit()
        conn.close()

    def _plant_duplicate_invoices(self, rows: list, used_ids: set) -> list:
        """Replace 12 rows with duplicate invoice payments (same invoice_number+amount, different tx_id+date)."""
        # Pick 12 base invoices to duplicate
        base_indices = self._rng.sample(range(len(rows)), 12)
        new_rows = list(rows)

        for i, base_idx in enumerate(base_indices):
            orig = list(new_rows[base_idx])
            dup_tx_id = DUPLICATE_TX_IDS[i]
            # Same invoice_number and amount, different tx_id and date
            dup_date = self._random_date()
            dup_row = (
                dup_tx_id,
                orig[1],   # vendor
                orig[2],   # invoice_number (same — this is the duplicate signal)
                orig[3],   # amount (same)
                dup_date,  # different date
                dup_date,
                "paid",
                "Accounts Payable",
            )
            new_rows.append(dup_row)

        return new_rows

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _random_date(self) -> str:
        month = self._rng.randint(1, 12)
        day = self._rng.randint(1, 28)
        return f"2024-{month:02d}-{day:02d}"

    @staticmethod
    def _write_json(path: Path, data: dict) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def _validate_planted_anomalies(self, output_dir: Path) -> None:
        """Assert all ground-truth values are present after generation."""
        # Task 1: FinanceHub operating_margin = 0.235
        fh = json.loads((output_dir / "company_4" / "income_statement.json").read_text())
        assert abs(fh["operating_margin"] - 0.235) < 1e-6, "Task1 ground truth missing"

        # Task 1: narrative chunk n7 exists for FinanceHub
        narr = json.loads((output_dir / "company_4" / "narrative.json").read_text())
        chunk_ids = {c["chunk_id"] for c in narr["chunks"]}
        assert "n7" in chunk_ids, "Task1 narrative chunk n7 missing"

        # Task 2: duplicate IDs in RetailCo sub_ledger
        conn = sqlite3.connect(str(output_dir / "company_2" / "sub_ledger.db"))
        cur = conn.cursor()
        for tx_id in DUPLICATE_TX_IDS:
            cur.execute("SELECT 1 FROM sub_ledger WHERE tx_id = ?", (tx_id,))
            assert cur.fetchone() is not None, f"Task2 duplicate tx_id {tx_id} missing"
        conn.close()

        # Task 3: TechCorp OCF should be lower than net_income (negative delta)
        tc_cf = json.loads((output_dir / "company_1" / "cashflow.json").read_text())
        tc_is = json.loads((output_dir / "company_1" / "income_statement.json").read_text())
        assert tc_cf["operating_cash_flow"] < tc_is["net_income"], "Task3 OCF anomaly missing"


if __name__ == "__main__":
    import sys
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent.parent / "data"
    print(f"Generating data in {out} ...")
    DataGenerator(seed=42).generate_all(out)
    print("Done.")
