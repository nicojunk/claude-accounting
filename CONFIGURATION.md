# Configuration

Two files, both copied from an example. Neither is in version control.

## `accounting.json`

```bash
cp accounting.example.json accounting.json
```

| Key | What it is |
|---|---|
| `consultant_number` | Your accountant's DATEV consultant number |
| `client_number` | Your client number with them |
| `accounts.clearing` | The clearing account the payout is booked against |
| `accounts.revenue` | Revenue account per country code, plus a `default` |
| `accounts.fee` | Where payment fees land |
| `accounts.refund` / `accounts.dispute` | Refunds and chargebacks, separately |
| `tax_keys` | DATEV tax key per country code |
| `fx_corridor` | Accepted FX range for foreign-currency matching |

Ask your accountant for the account numbers and tax keys. They depend on your chart of
accounts (SKR03 and SKR04 differ) and on whether you are registered for OSS.

## `vendors.json`

```bash
cp skill/vendors.example.json vendors.json
```

Maps what your bank statement shows to a vendor name. The example ships 53 common SaaS
vendors. Add your own: the left side is the string as it appears on the statement, the
right side is the name used in the document index.

## Environment

| Variable | Default | Meaning |
|---|---|---|
| `ACCOUNTING_ROOT` | `./documents` | Where the invoice PDFs live |
| `ACCOUNTING_CONFIG` | `accounting.json` | Path to the config file |
| `ACCOUNTING_OUT` | `./out` | Where EXTF batches are written |

## What this needs from you

`pdftotext` for reading PDFs, from poppler:

```bash
brew install poppler
```

Nothing else. No API keys, no accounts, no network access.
