import json
import xml.etree.ElementTree as ET
import os
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app
from finance import account_summary, empty_database, format_money, money_to_minor, monthly_summary


def account(db, name, opening):
    item = {"id": name, "name": name, "opening_balance": money_to_minor(opening), "created_at": "2026-10-11", "archived": False}
    db["accounts"].append(item)
    return item["id"]


class FinanceTests(unittest.TestCase):
 def test_money_uses_integer_kurus_and_locale(self):
    assert money_to_minor("1.693,36") == 169336
    assert money_to_minor("1,01") == 101
    assert format_money(169336) == "1.693,36 ₺"
    for invalid in ("-1", "1.001", "", "abc"):
        try:
            money_to_minor(invalid)
            assert False, invalid
        except ValueError:
            pass


 def test_opening_income_expense_debt_partial_full_payment(self):
    db = empty_database(); aid = account(db, "a", "1000")
    assert account_summary(db, aid)["realized"] == 100000
    app.create_tx(db, aid, "expense", 10000, "2026-10-11", "Harcama")
    assert account_summary(db, aid)["realized"] == 90000
    app.create_tx(db, aid, "income", 25000, "2026-10-11", "Gelir")
    assert account_summary(db, aid)["realized"] == 115000

    # Fresh fixture for the exact 1.000 / 300 / 100 / 200 debt examples.
    db = empty_database(); aid = account(db, "a", "1000")
    # Exercise the pure account formulas with a pending debt; API payment flow is tested separately.
    debt = {"id":"d","account_id":aid,"amount":30000,"cancelled":False};db["debts"].append(debt)
    assert account_summary(db, aid)["realized"] == 100000
    assert account_summary(db, aid)["remaining_debt"] == 30000
    assert account_summary(db, aid)["available"] == 70000
    db["debt_payments"].append({"id":"p1","account_id":aid,"debt_id":"d","amount":10000})
    app.create_tx(db, aid, "expense", 10000, "2026-10-11", "Borç ödemesi", linked_type="debt_payment", linked_id="p1")
    s = account_summary(db, aid)
    assert (s["realized"], s["remaining_debt"], s["available"]) == (90000, 20000, 70000)
    db["debt_payments"].append({"id":"p2","account_id":aid,"debt_id":"d","amount":20000})
    app.create_tx(db, aid, "expense", 20000, "2026-10-11", "Borç ödemesi", linked_type="debt_payment", linked_id="p2")
    s = account_summary(db, aid)
    assert (s["realized"], s["remaining_debt"], s["available"]) == (70000, 0, 70000)
    assert s["expenses"] == 30000


 def test_receivable_is_income_only_when_collected(self):
    db=empty_database(); aid=account(db,"a","1000")
    db["receivables"].append({"id":"r","account_id":aid,"amount":20000,"cancelled":False})
    assert account_summary(db,aid)["realized"]==100000
    db["collections"].append({"id":"c","account_id":aid,"receivable_id":"r","amount":20000})
    app.create_tx(db,aid,"income",20000,"2026-10-11","Tahsilat",linked_type="collection",linked_id="c")
    s=account_summary(db,aid)
    assert (s["realized"],s["remaining_receivable"])==(120000,0)


 def test_accounts_are_independent_and_edits_recalculate(self):
    db=empty_database(); a=account(db,"a","1000");b=account(db,"b","2000")
    app.create_tx(db,a,"expense",10000,"2026-10-11","Harcama")
    assert account_summary(db,a)["realized"]==90000
    assert account_summary(db,b)["realized"]==200000
    db["transactions"][0]["amount"]=15000
    assert account_summary(db,a)["realized"]==85000
    db["transactions"].clear()
    assert account_summary(db,a)["realized"]==100000


 def test_api_payment_is_atomic_scoped_and_persisted(self):
    with tempfile.TemporaryDirectory() as directory:
     store=Path(directory)/"data.json";app.STORE=store
     db=empty_database();aid=account(db,"a","1000");bid=account(db,"b","2000");app.write_db(db)
     app.api_post({"action":"debt.create","account_id":aid,"date":"2026-10-11","amount":"300","description":"Borç"})
     after=app.read_db();debt=after["debts"][0]
     app.api_post({"action":"debt.pay","account_id":aid,"debt_id":debt["id"],"date":"2026-10-11","amount":"100"})
     after=app.read_db();s=account_summary(after,aid)
     self.assertEqual((s["realized"],s["remaining_debt"],s["available"]),(90000,20000,70000))
     self.assertEqual((len(after["transactions"]),len(after["debt_payments"])),(1,1))
     self.assertEqual(account_summary(after,bid)["realized"],200000)
     with self.assertRaises(ValueError):
        app.api_post({"action":"debt.pay","account_id":bid,"debt_id":debt["id"],"date":"2026-10-11","amount":"100"})
     self.assertEqual(len(app.read_db()["transactions"]),1)


 def test_restore_merges_ids_and_repeat_import_is_idempotent(self):
    with tempfile.TemporaryDirectory() as directory:
     app.STORE=Path(directory)/"data.json"
     source=empty_database();aid=account(source,"a","12.34")
     backup={**source,"transactions":[{"id":"t1","account_id":aid,"amount":100,"kind":"income"}]}
     app.api_post({"action":"restore","data":backup,"import_id":"same"})
     app.api_post({"action":"restore","data":backup,"import_id":"same"})
     loaded=app.read_db()
     self.assertEqual((len(loaded["accounts"]),len(loaded["transactions"])),(1,1))


 def test_invalid_restore_does_not_partially_change_local_data(self):
    with tempfile.TemporaryDirectory() as directory:
     app.STORE=Path(directory)/"data.json"
     app.api_post({"action":"account.create","name":"Local","opening_balance":"5","created_at":"2026-10-11"})
     before=app.read_db()
     bad=empty_database();bad["transactions"].append({"id":"orphan","account_id":"missing","kind":"income","amount":1})
     with self.assertRaises(ValueError):
      app.api_post({"action":"restore","data":bad,"import_id":"invalid"})
     after=app.read_db()
     self.assertEqual(after,before)

 def test_monthly_summary_includes_realized_moves_once_and_scopes_account(self):
    db=empty_database();aid=account(db,"a","1000");other=account(db,"b","9000")
    db['transactions'] += [
     {"id":"prior","account_id":aid,"kind":"expense","amount":50000,"date":"2025-12-15","category":"Ev"},
     {"id":"income","account_id":aid,"kind":"income","amount":30000,"date":"2026-01-03","category":""},
     {"id":"expense","account_id":aid,"kind":"expense","amount":10000,"date":"2026-01-04","category":"Ulaşım"},
     {"id":"debt-expense","account_id":aid,"kind":"expense","amount":6000,"date":"2026-01-10","category":"Borç ödemesi","linked_type":"debt_payment","linked_id":"dp"},
     {"id":"collection-income","account_id":aid,"kind":"income","amount":5000,"date":"2026-01-12","category":"Alacak tahsilatı","linked_type":"collection","linked_id":"col"},
     {"id":"other","account_id":other,"kind":"expense","amount":800000,"date":"2026-01-02","category":"Başka hesap"},
    ]
    db['debt_payments'].append({"id":"dp","account_id":aid,"debt_id":"d","amount":6000,"date":"2026-01-10"})
    db['collections'].append({"id":"col","account_id":aid,"receivable_id":"r","amount":5000,"date":"2026-01-12"})
    result=monthly_summary(db,aid,"2026-01")
    self.assertEqual((result['income'],result['expenses'],result['net']),(35000,16000,19000))
    self.assertEqual(result['opening_balance'],50000)
    self.assertEqual(result['realized_balance'],69000)
    self.assertEqual((result['debt_payments'],result['collections']),(6000,5000))
    self.assertEqual(result['previous_expenses'],50000)
    self.assertEqual(result['expense_change'],-34000)
    self.assertEqual(result['top_categories'],[{'name':'Ulaşım','amount':10000},{'name':'Borç ödemesi','amount':6000}])

 def test_monthly_summary_empty_month_and_zero_previous_month(self):
    db=empty_database();aid=account(db,"a","123.45")
    result=monthly_summary(db,aid,"2026-02")
    self.assertEqual((result['income'],result['expenses'],result['net']),(0,0,0))
    self.assertEqual((result['opening_balance'],result['realized_balance']),(12345,12345))
    self.assertEqual(result['expense_change_percent'],None)
    self.assertEqual(result['top_categories'],[])

 def test_api_month_selection_is_account_scoped(self):
    with tempfile.TemporaryDirectory() as directory:
     app.STORE=Path(directory)/"data.json"
     db=empty_database();aid=account(db,"a","1000");other=account(db,"b","2000")
     app.create_tx(db,aid,"income",15000,"2026-03-02","Gelir")
     app.create_tx(db,other,"expense",99000,"2026-03-02","Başka hesap")
     app.write_db(db)
     response=app.api_get('/api/state',{'account':[aid],'month':['2026-03']})
     self.assertEqual(response['monthly_summary']['month'],'2026-03')
     self.assertEqual(response['monthly_summary']['income'],15000)
     self.assertEqual(response['monthly_summary']['expenses'],0)

 def test_theme_is_a_presentation_preference_and_backups_remain_available(self):
    root=Path(__file__).resolve().parents[1]
    js=(root/'app.js').read_text(encoding='utf-8')
    css=(root/'style.css').read_text(encoding='utf-8')
    html=(root/'index.html').read_text(encoding='utf-8')
    self.assertIn("localStorage.setItem('hesap-theme',theme)",js)
    self.assertIn("localStorage.getItem('hesap-theme')",js)
    self.assertIn('data-theme="dark"',css)
    self.assertIn('id="theme-toggle"',html)
    self.assertIn("'/api/backup'",js)
    self.assertIn("action==='restore'",js)
    self.assertIn("action==='export-csv'",js)

 def test_github_pages_assets_and_worker_are_repository_relative(self):
    root=Path(__file__).resolve().parents[1]
    html=(root/'index.html').read_text(encoding='utf-8')
    app_js=(root/'app.js').read_text(encoding='utf-8')
    worker=(root/'sw.js').read_text(encoding='utf-8')
    manifest=(root/'manifest.webmanifest').read_text(encoding='utf-8')
    self.assertIn('href="./style.css"',html)
    self.assertIn('src="./browser-store.js"',html)
    self.assertIn('src="./app.js"',html)
    self.assertNotIn('href="/style.css"',html)
    self.assertNotIn('src="/app.js"',html)
    self.assertIn("navigator.serviceWorker.register('./sw.js')",app_js)
    self.assertIn("new URL('./', self.registration.scope)",worker)
    self.assertIn('"start_url": "./"',manifest)
    self.assertIn('HesapBrowserStore.request',app_js)

 def test_logo_and_favicon_share_the_same_relative_svg(self):
    root=Path(__file__).resolve().parents[1]
    html=(root/'index.html').read_text(encoding='utf-8')
    worker=(root/'sw.js').read_text(encoding='utf-8')
    self.assertIn('href="./favicon.svg?v=1" type="image/svg+xml"',html)
    self.assertIn('src="./favicon.svg"',html)
    self.assertIn("'./favicon.svg'",worker)
    svg=ET.parse(root/'favicon.svg').getroot()
    self.assertEqual(svg.attrib['viewBox'],'0 0 64 64')
    self.assertEqual(svg.find('{http://www.w3.org/2000/svg}rect').attrib['fill'],'#198460')


 def test_http_flow_page_and_local_persistence(self):
  with tempfile.TemporaryDirectory() as directory:
    app.STORE=Path(directory)/"data.json"
    html=(Path(__file__).resolve().parents[1]/'index.html').read_text(encoding='utf-8')
    self.assertIn('Kişisel Muhasebe',html)
    created=app.api_post({"action":"account.create","name":"Test","description":"","opening_balance":"0","created_at":"2026-10-11"})
    self.assertTrue(created.get('account_id'))
    result=app.api_get('/api/state',{});aid=result['current_account']
    self.assertEqual(aid,created['account_id'])
    app.api_post({"action":"transaction.create","account_id":aid,"kind":"income","date":"2026-10-11","amount":"250,50","description":"İlk kayıt"})
    result=app.api_get('/api/state',{'account':[aid]})
    self.assertEqual((result['summary']['realized'],len(result['transactions'])),(25050,1))
    self.assertTrue((Path(directory)/'data.json').exists())


if __name__ == '__main__':
    unittest.main()
