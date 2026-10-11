from __future__ import annotations

import json
import os
import copy
from datetime import datetime
from pathlib import Path
from threading import RLock
from typing import Any
from urllib.parse import parse_qs
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from finance import account_summary, empty_database, format_money, monthly_summary, money_to_minor, new_id, now, valid_date

ROOT = Path(__file__).resolve().parent
STORE = Path(os.environ.get("FINANCE_DATA_FILE", str(ROOT / "data.json")))
LOCK = RLock()


def read_db() -> dict:
    if not STORE.exists():
        return empty_database()
    try:
        value = json.loads(STORE.read_text(encoding="utf-8"))
        base = empty_database()
        if not isinstance(value, dict) or value.get("version") != 1:
            raise ValueError("Yedek sürümü desteklenmiyor.")
        for key in base:
            if key in value and isinstance(value[key], list):
                base[key] = value[key]
        return base
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("Yerel veri dosyası okunamadı; dosya korunarak işlem durduruldu.") from exc


def write_db(data: dict) -> None:
    STORE.parent.mkdir(parents=True, exist_ok=True)
    temp = STORE.with_suffix(STORE.suffix + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    os.replace(temp, STORE)


def account(data: dict, aid: str) -> dict:
    item = next((a for a in data["accounts"] if a["id"] == aid), None)
    if item is None:
        raise ValueError("Hesap bulunamadı.")
    return item


def active_account(data: dict, aid: str) -> dict:
    item = account(data, aid)
    if item.get("archived"):
        raise ValueError("Arşivlenmiş hesaba yeni finansal kayıt eklenemez.")
    return item


def validate_database(data: dict) -> None:
    account_ids = {x.get("id") for x in data["accounts"]}
    if None in account_ids or len(account_ids) != len(data["accounts"]):
        raise ValueError("Yedekte hesap kimlikleri eksik veya yinelenmiş.")
    for key in ("transactions", "debts", "debt_payments", "receivables", "collections", "categories"):
        seen = set()
        for row in data[key]:
            rid = row.get("id")
            if not rid or rid in seen:
                raise ValueError("Yedekte yinelenen veya eksik kayıt kimliği var.")
            seen.add(rid)
            if row.get("account_id") not in account_ids:
                raise ValueError("Yedekte bulunmayan hesaba bağlı kayıt var.")
    debts = {x["id"]: x for x in data["debts"]}
    receivables = {x["id"]: x for x in data["receivables"]}
    for row in data["debt_payments"]:
        if row.get("debt_id") not in debts or debts[row["debt_id"]]["account_id"] != row["account_id"]:
            raise ValueError("Yedekte borç ödeme ilişkisi geçersiz.")
    for row in data["collections"]:
        if row.get("receivable_id") not in receivables or receivables[row["receivable_id"]]["account_id"] != row["account_id"]:
            raise ValueError("Yedekte tahsilat ilişkisi geçersiz.")
    for row in data["transactions"]:
        if row.get("linked_type") == "debt_payment":
            linked = next((p for p in data["debt_payments"] if p["id"] == row.get("linked_id")), None)
            if not linked or linked["account_id"] != row["account_id"] or linked["amount"] != row["amount"]:
                raise ValueError("Yedekte borç gider hareketi ilişkisi geçersiz.")
        if row.get("linked_type") == "collection":
            linked = next((p for p in data["collections"] if p["id"] == row.get("linked_id")), None)
            if not linked or linked["account_id"] != row["account_id"] or linked["amount"] != row["amount"]:
                raise ValueError("Yedekte tahsilat gelir hareketi ilişkisi geçersiz.")


def item_by(items: list, item_id: str) -> dict:
    result = next((x for x in items if x["id"] == item_id), None)
    if result is None:
        raise ValueError("Kayıt bulunamadı.")
    return result


def create_tx(data: dict, aid: str, kind: str, amount: int, day: str, description: str,
              category: str = "", note: str = "", linked_type: str = "", linked_id: str = "") -> dict:
    row = {"id": new_id(), "account_id": aid, "date": valid_date(day), "description": description.strip(),
           "kind": kind, "amount": amount, "category": category.strip(), "note": note.strip(),
           "linked_type": linked_type, "linked_id": linked_id, "created_at": now(), "updated_at": now()}
    if not row["description"]:
        raise ValueError("Açıklama boş olamaz.")
    data["transactions"].append(row)
    return row


def api_get(path: str, query: dict) -> Any:
    data = read_db()
    if path == "/api/state":
        aid = query.get("account", [""])[0]
        current = next((a for a in data["accounts"] if a["id"] == aid), None)
        if not current:
            current = next((a for a in data["accounts"] if not a.get("archived")), None)
        if current:
            aid = current["id"]
        else:
            aid = ""
        month_key = query.get("month", [""])[0]
        if not month_key:
            month_key = datetime.now().astimezone().strftime("%Y-%m")
        return {"accounts": data["accounts"], "current_account": aid,
                "summary": account_summary(data, aid) if aid else None,
                "monthly_summary": monthly_summary(data, aid, month_key) if aid else None,
                "transactions": [x for x in data["transactions"] if x["account_id"] == aid],
                "debts": [x for x in data["debts"] if x["account_id"] == aid and not x.get("cancelled")],
                "debt_payments": [x for x in data["debt_payments"] if x["account_id"] == aid],
                "receivables": [x for x in data["receivables"] if x["account_id"] == aid and not x.get("cancelled")],
                "collections": [x for x in data["collections"] if x["account_id"] == aid],
                "categories": [x for x in data["categories"] if x["account_id"] == aid]}
    if path == "/api/backup":
        return data
    raise ValueError("İstenen adres bulunamadı.")


def api_post(body: dict) -> Any:
    action = body.get("action")
    with LOCK:
        data = read_db()
        if action == "restore":
            incoming = body.get("data")
            if not isinstance(incoming, dict) or incoming.get("version") != 1:
                raise ValueError("Yedek biçimi geçersiz veya desteklenmiyor.")
            # Imports are idempotent: restore merges by stable IDs and records the backup fingerprint.
            import_id = body.get("import_id")
            if import_id and import_id in data["applied_imports"]:
                return {"ok": True, "duplicate": True}
            merged = copy.deepcopy(data)
            for key in ("accounts", "transactions", "debts", "debt_payments", "receivables", "collections", "categories"):
                if not isinstance(incoming.get(key, []), list):
                    raise ValueError("Yedek içeriği bozuk.")
                known = {x.get("id") for x in merged[key]}
                merged[key].extend(x for x in incoming.get(key, []) if x.get("id") not in known)
            validate_database(merged)
            if import_id:
                merged["applied_imports"].append(import_id)
            write_db(merged)
            return {"ok": True}
        if action == "account.create":
            name = str(body.get("name", "")).strip()
            if not name:
                raise ValueError("Hesap adı boş olamaz.")
            item = {"id": new_id(), "name": name, "description": str(body.get("description", "")).strip(),
                    "opening_balance": money_to_minor(body.get("opening_balance", "0")),
                    "created_at": valid_date(body.get("created_at", "")), "archived": False,
                    "created_ts": now(), "updated_at": now()}
            data["accounts"].append(item)
            result_account_id = item["id"]
        elif action == "account.update":
            item = account(data, body.get("account_id", ""))
            item.update(name=str(body.get("name", item["name"])).strip(),
                        description=str(body.get("description", item.get("description", ""))).strip(),
                        opening_balance=money_to_minor(body.get("opening_balance", item["opening_balance"] / 100)),
                        updated_at=now())
            if not item["name"]:
                raise ValueError("Hesap adı boş olamaz.")
        elif action == "account.archive":
            item = account(data, body.get("account_id", ""))
            item["archived"] = True
            item["updated_at"] = now()
        elif action == "account.restore":
            item = account(data, body.get("account_id", ""))
            item["archived"] = False
            item["updated_at"] = now()
        elif action == "account.delete":
            aid = body.get("account_id", "")
            account(data, aid)
            for key in ("transactions", "debts", "debt_payments", "receivables", "collections", "categories"):
                data[key] = [row for row in data[key] if row["account_id"] != aid]
            data["accounts"] = [row for row in data["accounts"] if row["id"] != aid]
        elif action == "transaction.create":
            aid = body.get("account_id", "")
            active_account(data, aid)
            create_tx(data, aid, body["kind"], money_to_minor(body.get("amount")), body.get("date", ""),
                      body.get("description", ""), body.get("category", ""), body.get("note", ""))
            result_account_id = aid
        elif action == "transaction.update":
            row = item_by(data["transactions"], body.get("id", ""))
            if row["account_id"] != body.get("account_id") or row.get("linked_type"):
                raise ValueError("Bağlantılı veya başka hesaba ait işlem düzenlenemez.")
            active_account(data, body.get("account_id", ""))
            row.update(date=valid_date(body.get("date", "")), description=str(body.get("description", "")).strip(),
                       kind=body.get("kind"), amount=money_to_minor(body.get("amount")),
                       category=str(body.get("category", "")).strip(), note=str(body.get("note", "")).strip(), updated_at=now())
            if row["kind"] not in ("income", "expense") or not row["description"]:
                raise ValueError("İşlem alanlarını kontrol edin.")
        elif action == "transaction.delete":
            row = item_by(data["transactions"], body.get("id", ""))
            if row["account_id"] != body.get("account_id") or row.get("linked_type"):
                raise ValueError("Bağlantılı veya başka hesaba ait işlem silinemez.")
            active_account(data, body.get("account_id", ""))
            data["transactions"].remove(row)
        elif action == "debt.create":
            aid = body.get("account_id", ""); active_account(data, aid)
            desc = str(body.get("description", "")).strip()
            if not desc: raise ValueError("Borç açıklaması boş olamaz.")
            data["debts"].append({"id": new_id(), "account_id": aid, "description": desc,
                "creditor": str(body.get("creditor", "")).strip(), "date": valid_date(body.get("date", "")),
                "due_date": valid_date(body["due_date"]) if body.get("due_date") else "",
                "amount": money_to_minor(body.get("amount")), "note": str(body.get("note", "")).strip(),
                "cancelled": False, "created_at": now(), "updated_at": now()})
            result_account_id = aid
        elif action == "debt.pay":
            aid = body.get("account_id", ""); active_account(data, aid)
            debt = item_by(data["debts"], body.get("debt_id", ""))
            if debt["account_id"] != aid or debt.get("cancelled"):
                raise ValueError("Borç bu hesaba ait değil veya iptal edilmiş.")
            amount = money_to_minor(body.get("amount"))
            paid = sum(p["amount"] for p in data["debt_payments"] if p["debt_id"] == debt["id"])
            if amount <= 0 or amount > debt["amount"] - paid:
                raise ValueError("Ödeme, kalan borçtan fazla olamaz ve sıfırdan büyük olmalıdır.")
            payment_id = new_id()
            data["debt_payments"].append({"id": payment_id, "account_id": aid, "debt_id": debt["id"],
                "amount": amount, "date": valid_date(body.get("date", "")), "note": str(body.get("note", "")).strip(), "created_at": now()})
            create_tx(data, aid, "expense", amount, body.get("date", ""), "Borç ödemesi · " + debt["description"],
                      "Borç ödemesi", body.get("note", ""), "debt_payment", payment_id)
            result_account_id = aid
        elif action == "debt.cancel":
            aid = body.get("account_id", ""); debt = item_by(data["debts"], body.get("debt_id", ""))
            if debt["account_id"] != aid: raise ValueError("Borç bu hesaba ait değil.")
            active_account(data, aid)
            if any(p["debt_id"] == debt["id"] for p in data["debt_payments"]):
                raise ValueError("Ödemesi olan borç iptal edilemez; ödemeleri silip tekrar deneyin.")
            debt["cancelled"] = True; debt["updated_at"] = now()
        elif action == "debt.payment.delete":
            aid = body.get("account_id", ""); payment = item_by(data["debt_payments"], body.get("id", ""))
            if payment["account_id"] != aid: raise ValueError("Ödeme bu hesaba ait değil.")
            active_account(data, aid)
            linked = next((t for t in data["transactions"] if t.get("linked_id") == payment["id"]), None)
            if linked: data["transactions"].remove(linked)
            data["debt_payments"].remove(payment)
        elif action == "receivable.create":
            aid = body.get("account_id", ""); active_account(data, aid)
            desc = str(body.get("description", "")).strip()
            if not desc: raise ValueError("Alacak açıklaması boş olamaz.")
            data["receivables"].append({"id": new_id(), "account_id": aid, "description": desc,
                "debtor": str(body.get("debtor", "")).strip(), "date": valid_date(body.get("date", "")),
                "amount": money_to_minor(body.get("amount")), "note": str(body.get("note", "")).strip(),
                "cancelled": False, "created_at": now(), "updated_at": now()})
            result_account_id = aid
        elif action == "receivable.collect":
            aid = body.get("account_id", ""); active_account(data, aid)
            rec = item_by(data["receivables"], body.get("receivable_id", ""))
            if rec["account_id"] != aid or rec.get("cancelled"): raise ValueError("Alacak bu hesaba ait değil veya iptal edilmiş.")
            amount = money_to_minor(body.get("amount")); collected = sum(c["amount"] for c in data["collections"] if c["receivable_id"] == rec["id"])
            if amount <= 0 or amount > rec["amount"] - collected: raise ValueError("Tahsilat, kalan alacaktan fazla olamaz.")
            cid = new_id()
            data["collections"].append({"id": cid, "account_id": aid, "receivable_id": rec["id"], "amount": amount,
                "date": valid_date(body.get("date", "")), "note": str(body.get("note", "")).strip(), "created_at": now()})
            create_tx(data, aid, "income", amount, body.get("date", ""), "Alacak tahsilatı · " + rec["description"],
                      "Alacak tahsilatı", body.get("note", ""), "collection", cid)
            result_account_id = aid
        elif action == "receivable.cancel":
            aid = body.get("account_id", ""); rec = item_by(data["receivables"], body.get("receivable_id", ""))
            if rec["account_id"] != aid: raise ValueError("Alacak bu hesaba ait değil.")
            active_account(data, aid)
            if any(c["receivable_id"] == rec["id"] for c in data["collections"]): raise ValueError("Tahsilatı olan alacak iptal edilemez.")
            rec["cancelled"] = True; rec["updated_at"] = now()
        elif action == "collection.delete":
            aid = body.get("account_id", ""); coll = item_by(data["collections"], body.get("id", ""))
            if coll["account_id"] != aid: raise ValueError("Tahsilat bu hesaba ait değil.")
            active_account(data, aid)
            linked = next((t for t in data["transactions"] if t.get("linked_id") == coll["id"]), None)
            if linked: data["transactions"].remove(linked)
            data["collections"].remove(coll)
        elif action == "category.create":
            aid = body.get("account_id", ""); active_account(data, aid)
            label = str(body.get("name", "")).strip(); kind = body.get("kind")
            if not label or kind not in ("income", "expense"): raise ValueError("Kategori alanlarını kontrol edin.")
            if any(c["account_id"] == aid and c["name"].casefold() == label.casefold() and c["kind"] == kind for c in data["categories"]):
                raise ValueError("Bu kategori zaten var.")
            data["categories"].append({"id": new_id(), "account_id": aid, "name": label, "kind": kind, "created_at": now()})
            result_account_id = aid
        else:
            raise ValueError("İşlem tanınmadı.")
        write_db(data)
        result = {"ok": True}
        if "result_account_id" in locals(): result["account_id"] = result_account_id
        return result


class Handler(BaseHTTPRequestHandler):
    def send_json(self, value: Any, status=200):
        raw = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status); self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw))); self.send_header("Cache-Control", "no-store")
        self.end_headers(); self.wfile.write(raw)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if self.path.startswith("/api/"):
            try:
                with LOCK:
                    if not STORE.exists(): write_db(empty_database())
                    self.send_json(api_get(path, parse_qs(self.path.partition("?")[2])))
            except Exception as exc: self.send_json({"error": str(exc)}, 400)
            return
        target = ROOT / ("index.html" if path == "/" else path.lstrip("/"))
        if target.parent != ROOT or not target.is_file():
            self.send_error(404); return
        content = target.read_bytes(); content_type = "text/html; charset=utf-8" if target.suffix == ".html" else "text/plain; charset=utf-8"
        if target.suffix == ".js": content_type = "text/javascript; charset=utf-8"
        if target.suffix == ".css": content_type = "text/css; charset=utf-8"
        if target.suffix == ".svg": content_type = "image/svg+xml"
        self.send_response(200); self.send_header("Content-Type", content_type); self.send_header("Content-Length", str(len(content)))
        if target.name == "sw.js": self.send_header("Service-Worker-Allowed", "/")
        self.end_headers(); self.wfile.write(content)

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length > 5_000_000: raise ValueError("İstek boyutu çok büyük.")
            body = json.loads(self.rfile.read(length) or b"{}")
            if not STORE.exists():
                with LOCK:
                    if not STORE.exists(): write_db(empty_database())
            self.send_json(api_post(body))
        except Exception as exc:
            self.send_json({"error": str(exc)}, 400)

    def log_message(self, fmt, *args):
        print("[%s] %s" % (self.log_date_time_string(), fmt % args))


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", int(os.environ.get("PORT", "8765"))), Handler)
    print("Kişisel Muhasebe hazır: http://127.0.0.1:%s" % server.server_port)
    try: server.serve_forever()
    except KeyboardInterrupt: print("\nSunucu durduruldu.")
