---
name: accounting-payouts
description: >
  Turns aggregated payment-provider payouts into per-transaction journal entries and
  DATEV EXTF batches, and matches bank transactions against invoice documents.
  Use this skill whenever the request involves: payout reconciliation, Stripe payouts,
  bookkeeping export, DATEV, EXTF, Buchungsstapel, journal entries, VAT per country,
  OSS return, matching receipts to bank transactions, missing invoices, document
  indexing, or preparing a quarter for the tax accountant.
  Do NOT use it for invoicing customers, for payroll, or for tax advice. It prepares
  data for an accountant, it does not replace one.
---

# Accounting payouts

Three scripts, run in this order. Each one writes a file the next one reads, so a run can
be stopped and resumed.

## 1. `scripts/index_documents.py`

Builds an index of every invoice PDF by reading the **text inside the file**, never the
folder it sits in. Records issuer, all amounts, all dates and the currency.

The folder is not evidence: in one real quarter, 299 of 684 documents sat in the wrong
vendor folder. A matcher that filters by path is working on fiction.

```bash
ACCOUNTING_ROOT=./documents python3 scripts/index_documents.py
```

## 2. `scripts/match_transactions.py`

Matches bank transactions to indexed documents.

- EUR document: amount exact, invoice date 0 to 40 days before the charge.
- Foreign currency: date within 3 days, FX rate inside the configured corridor.
- Winner is the candidate closest to the booking date. A tie stays unresolved rather than
  being guessed.
- Every document can be claimed once. Collisions are parked, not resolved by coin flip.

```bash
python3 scripts/match_transactions.py
```

## 3. `scripts/build_extf.py`

Turns payout line items into DATEV EXTF batches, one file per month, cp1252.

```bash
python3 scripts/build_extf.py line_items.json payouts.json
```

**The run aborts if the entries do not add up to the payout on the bank statement.** This
is the point of the whole thing. Nobody finds a wrong row in two thousand by reading them.

## Configuration

Copy `accounting.example.json` to `accounting.json` and fill in consultant number, client
number, accounts and tax keys. Copy `vendors.example.json` and add your own vendors.
Nothing in this repo is specific to any client.

## Rules that are not negotiable

**Write umlauts.** EXTF is cp1252 and carries them. Transliterating "Erlös" to "Erloes"
defensively produced 1,991 wrong booking texts once. Check every generated file.

**Never write an unbalanced batch.** Reconciliation is a gate, not a report.

**Amounts and dates are not keys.** Use the reference string wherever the provider gives
one. See `references/PITFALLS.md` for the cases behind these rules.
