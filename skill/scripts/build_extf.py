#!/usr/bin/env python3
"""Turns payout line items into a DATEV EXTF batch.

The provider wires one amount. Bookkeeping needs every charge, refund and fee
inside it as its own journal entry, with the tax key that follows the buyer's
country rather than the payout.

Input:  a JSON list of line items (see line_items.example.json)
Output: one EXTF csv per month, cp1252, ready to import

The run aborts if the entries do not add up to the payout amount. Nobody finds
a bad row in two thousand by reading them, so the check has to block.
"""
import csv
import json
import os
import sys
from collections import defaultdict
import calendar
from datetime import datetime
from decimal import Decimal
from pathlib import Path

CONFIG = Path(os.environ.get("ACCOUNTING_CONFIG", "accounting.json"))


def load_config():
    if not CONFIG.exists():
        sys.exit(f"missing config: {CONFIG}. Copy accounting.example.json and fill it in.")
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def header(cfg, year, period, start, end, label):
    """EXTF header row. Field order is fixed by the format, do not reorder."""
    return [
        "EXTF", "700", "21", "Buchungsstapel", "13",
        datetime.now().strftime("%Y%m%d%H%M%S") + "000", "", "SO", label, "",
        cfg["consultant_number"], cfg["client_number"],
        f"{year}0101", "4", start, end, label, "", "1", "0", "0",
        cfg.get("currency", "EUR"), "", "", "", "", "", "",
    ]


COLUMNS = [
    "Umsatz (ohne Soll/Haben-Kz)", "Soll/Haben-Kennzeichen", "WKZ Umsatz", "Kurs",
    "Basis-Umsatz", "WKZ Basis-Umsatz", "Konto", "Gegenkonto (ohne BU-Schluessel)",
    "BU-Schluessel", "Belegdatum", "Belegfeld 1", "Belegfeld 2", "Skonto",
    "Buchungstext",
]


def account_for(item, cfg):
    """Revenue, fee and refund each land on their own account."""
    kind = item["kind"]
    if kind == "charge":
        country = item.get("country", "")
        return cfg["accounts"]["revenue"].get(country, cfg["accounts"]["revenue"]["default"])
    return cfg["accounts"][kind]


def tax_key(item, cfg):
    if item["kind"] != "charge":
        return ""
    return cfg["tax_keys"].get(item.get("country", ""), cfg["tax_keys"]["default"])


def to_rows(items, cfg):
    rows = []
    for it in items:
        amount = Decimal(str(it["amount"]))
        rows.append({
            "Umsatz (ohne Soll/Haben-Kz)": f"{abs(amount):.2f}".replace(".", ","),
            "Soll/Haben-Kennzeichen": "S" if amount < 0 else "H",
            "WKZ Umsatz": it.get("currency", "EUR"),
            "Kurs": "", "Basis-Umsatz": "", "WKZ Basis-Umsatz": "",
            "Konto": account_for(it, cfg),
            "Gegenkonto (ohne BU-Schluessel)": cfg["accounts"]["clearing"],
            "BU-Schluessel": tax_key(it, cfg),
            "Belegdatum": datetime.fromisoformat(it["date"]).strftime("%d%m"),
            "Belegfeld 1": it.get("reference", "")[:36],
            "Belegfeld 2": "", "Skonto": "",
            "Buchungstext": it.get("text", "")[:60],
        })
    return rows


def reconcile(items, payouts):
    """Sum of entries must equal the payout. Off by a cent, nothing is written."""
    per_payout = defaultdict(Decimal)
    for it in items:
        per_payout[it["payout_id"]] += Decimal(str(it["amount"]))
    problems = []
    for pid, expected in payouts.items():
        got = per_payout.get(pid, Decimal("0"))
        if got != Decimal(str(expected)):
            problems.append(f"{pid}: entries {got}, statement {expected}")
    return problems


def main():
    cfg = load_config()
    items = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    payouts = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))

    problems = reconcile(items, payouts)
    if problems:
        print("reconciliation failed, nothing written:")
        for p in problems:
            print("  " + p)
        sys.exit(1)

    by_month = defaultdict(list)
    for it in items:
        by_month[it["date"][:7]].append(it)

    outdir = Path(os.environ.get("ACCOUNTING_OUT", "./out"))
    outdir.mkdir(parents=True, exist_ok=True)

    for month, group in sorted(by_month.items()):
        year, mon = month.split("-")
        rows = to_rows(group, cfg)
        target = outdir / f"extf-{month}.csv"
        # cp1252 carries umlauts. Do not transliterate, "Erloes" is not a word.
        with target.open("w", encoding="cp1252", newline="") as fh:
            w = csv.writer(fh, delimiter=";", quoting=csv.QUOTE_ALL)
            last_day = calendar.monthrange(int(year), int(mon))[1]
            last = f"{year}{mon}{last_day:02d}"
            w.writerow(header(cfg, year, mon, f"{year}{mon}01", last, f"Payouts {month}"))
            w.writerow(COLUMNS + [""] * 23)
            for r in rows:
                w.writerow([r[c] for c in COLUMNS] + [""] * 23)
        print(f"{target}  {len(rows)} entries")


if __name__ == "__main__":
    main()
