"""Financial rules for the local-first personal finance app.

Amounts are integer kuruş. Every repository operation is scoped to an explicit
account id; cross-account transfers are intentionally outside the first release.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import uuid4


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id() -> str:
    return str(uuid4())


def money_to_minor(value: Any) -> int:
    """Parse a nonnegative TRY amount into kuruş, rejecting excess precision."""
    if isinstance(value, bool) or value is None:
        raise ValueError("Geçerli bir tutar girin.")
    raw = str(value).strip().replace("₺", "").replace("TL", "").replace(" ", "")
    if not raw:
        raise ValueError("Tutar boş olamaz.")
    # Turkish form: 1.234,56. Inputs with only a dot use dot as decimal separator.
    if "," in raw:
        raw = raw.replace(".", "").replace(",", ".")
    try:
        amount = Decimal(raw)
    except InvalidOperation as exc:
        raise ValueError("Tutar biçimi geçersiz.") from exc
    if not amount.is_finite() or amount < 0:
        raise ValueError("Tutar negatif olamaz.")
    if amount != amount.quantize(Decimal("0.01")):
        raise ValueError("Tutar en fazla iki ondalık basamak içerebilir.")
    return int(amount * 100)


def format_money(minor: int) -> str:
    sign = "−" if minor < 0 else ""
    whole, cents = divmod(abs(int(minor)), 100)
    return f"{sign}{whole:,}".replace(",", ".") + f",{cents:02d} ₺"


def valid_date(value: str) -> str:
    try:
        return date.fromisoformat(value).isoformat()
    except (TypeError, ValueError) as exc:
        raise ValueError("Geçerli bir tarih seçin.") from exc


def account_summary(data: dict, account_id: str) -> dict[str, int]:
    account = next((a for a in data["accounts"] if a["id"] == account_id), None)
    if not account:
        raise ValueError("Hesap bulunamadı.")
    txns = [t for t in data["transactions"] if t["account_id"] == account_id]
    debts = [d for d in data["debts"] if d["account_id"] == account_id and not d.get("cancelled")]
    payments = [p for p in data["debt_payments"] if p["account_id"] == account_id]
    receivables = [x for x in data["receivables"] if x["account_id"] == account_id and not x.get("cancelled")]
    collections = [c for c in data["collections"] if c["account_id"] == account_id]
    income = sum(t["amount"] for t in txns if t["kind"] == "income")
    expenses = sum(t["amount"] for t in txns if t["kind"] == "expense")
    # Debt payment transaction rows are actual expenses and are counted once here.
    debt_total = sum(d["amount"] for d in debts)
    debt_paid = sum(p["amount"] for p in payments)
    receivable_total = sum(r["amount"] for r in receivables)
    collected = sum(c["amount"] for c in collections)
    realized = account["opening_balance"] + income - expenses
    remaining_debt = max(0, debt_total - debt_paid)
    return {
        "income": income, "expenses": expenses, "realized": realized,
        "debt_total": debt_total, "debt_paid": debt_paid,
        "remaining_debt": remaining_debt, "available": realized - remaining_debt,
        "receivable_total": receivable_total, "collected": collected,
        "remaining_receivable": max(0, receivable_total - collected),
    }


def monthly_summary(data: dict, account_id: str, month_key: str) -> dict[str, Any]:
    """Return a selected account's realized month figures in integer kuruş."""
    account = next((a for a in data["accounts"] if a["id"] == account_id), None)
    if not account:
        raise ValueError("Hesap bulunamadı.")
    try:
        month_start = date.fromisoformat(month_key + "-01")
    except (TypeError, ValueError) as exc:
        raise ValueError("Ay YYYY-AA biçiminde olmalıdır.") from exc
    if month_start.strftime("%Y-%m") != month_key:
        raise ValueError("Seçilen ay geçersiz.")
    next_month = date(month_start.year + (month_start.month == 12),
                      1 if month_start.month == 12 else month_start.month + 1, 1)
    previous_month = date(month_start.year - (month_start.month == 1),
                          12 if month_start.month == 1 else month_start.month - 1, 1)
    aid = account_id
    txns = [t for t in data["transactions"] if t["account_id"] == aid]
    month_txns = [t for t in txns if month_key <= t["date"][:7] < next_month.strftime("%Y-%m")]
    prev_key = previous_month.strftime("%Y-%m")
    prev_expenses = sum(t["amount"] for t in txns if t["kind"] == "expense" and t["date"][:7] == prev_key)
    income = sum(t["amount"] for t in month_txns if t["kind"] == "income")
    expenses = sum(t["amount"] for t in month_txns if t["kind"] == "expense")
    categories: dict[str, int] = {}
    for txn in month_txns:
        if txn["kind"] == "expense":
            category = txn.get("category", "").strip() or "Kategorisiz"
            categories[category] = categories.get(category, 0) + txn["amount"]
    payments = [p for p in data["debt_payments"] if p["account_id"] == aid and month_key <= p["date"][:7] < next_month.strftime("%Y-%m")]
    collections = [c for c in data["collections"] if c["account_id"] == aid and month_key <= c["date"][:7] < next_month.strftime("%Y-%m")]
    opening = account["opening_balance"] + sum(
        t["amount"] if t["kind"] == "income" else -t["amount"]
        for t in txns if t["date"] < month_start.isoformat())
    return {
        "month": month_key,
        "income": income,
        "expenses": expenses,
        "net": income - expenses,
        "opening_balance": opening,
        "realized_balance": account_summary(data, aid)["realized"],
        "debt_payments": sum(p["amount"] for p in payments),
        "collections": sum(c["amount"] for c in collections),
        "previous_month": prev_key,
        "previous_expenses": prev_expenses,
        "expense_change": expenses - prev_expenses,
        "expense_change_percent": ((expenses - prev_expenses) * 100 / prev_expenses) if prev_expenses else None,
        "top_categories": [
            {"name": name, "amount": amount}
            for name, amount in sorted(categories.items(), key=lambda item: (-item[1], item[0].casefold()))[:3]
        ],
    }


def empty_database() -> dict:
    return {"version": 1, "accounts": [], "transactions": [], "debts": [],
            "debt_payments": [], "receivables": [], "collections": [],
            "categories": [], "applied_imports": []}
