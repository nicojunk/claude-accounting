#!/usr/bin/env python3
"""Tests for build_extf.py. Run: python3 tests/test_extf.py"""
import csv
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "skill" / "scripts" / "build_extf.py"
fails = []


def run(items, payouts, workdir):
    (workdir / "accounting.json").write_text(
        (ROOT / "accounting.example.json").read_text(encoding="utf-8"), encoding="utf-8")
    (workdir / "items.json").write_text(json.dumps(items), encoding="utf-8")
    (workdir / "payouts.json").write_text(json.dumps(payouts), encoding="utf-8")
    env = {**os.environ, "ACCOUNTING_CONFIG": str(workdir / "accounting.json"),
           "ACCOUNTING_OUT": str(workdir / "out")}
    return subprocess.run([sys.executable, str(SCRIPT), str(workdir / "items.json"),
                           str(workdir / "payouts.json")],
                          capture_output=True, text=True, env=env, cwd=workdir)


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name + ("" if cond else "  " + detail))
    if not cond:
        fails.append(name)


ITEMS = [
    {"payout_id": "po_1", "kind": "charge", "amount": "97.00", "currency": "EUR",
     "country": "DE", "date": "2026-04-03", "reference": "ch_1", "text": "Verkauf Erlös"},
    {"payout_id": "po_1", "kind": "charge", "amount": "97.00", "currency": "EUR",
     "country": "AT", "date": "2026-04-03", "reference": "ch_2", "text": "Verkauf"},
    {"payout_id": "po_1", "kind": "fee", "amount": "-3.42", "currency": "EUR",
     "date": "2026-04-03", "reference": "fee_1", "text": "Gebühr"},
]

print("build_extf")
with tempfile.TemporaryDirectory() as td:
    w = Path(td)
    r = run(ITEMS, {"po_1": "190.58"}, w)
    check("balanced batch is written", r.returncode == 0, r.stderr[:200])
    out = w / "out" / "extf-2026-04.csv"
    check("output file exists", out.exists())
    if out.exists():
        raw = out.read_bytes()
        check("encoding is cp1252", raw.decode("cp1252") is not None)
        text = raw.decode("cp1252")
        check("umlauts survive, not transliterated", "Erlös" in text and "Erloes" not in text)
        rows = list(csv.reader(text.splitlines(), delimiter=";"))
        check("header plus columns plus 3 entries", len(rows) == 5, f"got {len(rows)}")
        check("april period ends on the 30th", rows[0][15] == "20260430", rows[0][15])
        check("german sale carries no tax key", rows[2][8] == "", repr(rows[2][8]))
        check("austrian sale carries a tax key", rows[3][8] == "20", repr(rows[3][8]))
        check("fee is booked as debit", rows[4][1] == "S", rows[4][1])
        check("amount uses a decimal comma", rows[2][0] == "97,00", rows[2][0])

with tempfile.TemporaryDirectory() as td:
    w = Path(td)
    r = run(ITEMS, {"po_1": "999.99"}, w)
    check("unbalanced batch aborts", r.returncode == 1)
    check("nothing is written on abort", not (w / "out" / "extf-2026-04.csv").exists())
    check("the difference is reported", "999.99" in r.stdout and "190.58" in r.stdout, r.stdout[:150])

with tempfile.TemporaryDirectory() as td:
    w = Path(td)
    feb = [{**ITEMS[0], "date": "2026-02-11"}]
    r = run(feb, {"po_1": "97.00"}, w)
    rows = list(csv.reader((w / "out" / "extf-2026-02.csv").read_text(encoding="cp1252").splitlines(), delimiter=";"))
    check("february period ends on the 28th", rows[0][15] == "20260228", rows[0][15])

print()
if fails:
    print(f"{len(fails)} failed: {', '.join(fails)}")
    sys.exit(1)
print("all passed")
