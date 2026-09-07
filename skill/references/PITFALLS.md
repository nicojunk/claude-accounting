# Pitfalls

Every entry here is a bug that shipped, or came within a day of shipping. They are in the
code as guards; this file is why.

## The target encoding takes umlauts, so write umlauts

DATEV EXTF is cp1252. It carries ä, ö, ü and ß without complaint. Transliterating
defensively produces booking texts reading "Erloes" instead of "Erlös", and it does it
1,991 times in a quarter without a single error message.

Caught the evening before the batch went to the tax office. `build_extf.py` writes cp1252
directly and never transliterates. Check generated files with:

```python
re.findall(r'\b\w*(?:ae|oe|ue|ss)\w*\b', text)
```

Real words match too (Fitness, Steuersatz), so review the hits rather than replacing them.

## A document can only be claimed once

Same day, two charges of 51.43 EUR, two invoices numbered 0118 and 0119. Without a claim
list, both charges grab whichever document matched first, which is a double booking that
balances perfectly and is therefore invisible.

`match_transactions.py` keeps a claim list and parks collisions as unresolved.

## Foreign currency needs a narrow corridor

USD invoices carry no EUR amount, so the match runs on exact date plus FX rate. The real
corridor across two quarters was 0.84 to 0.87.

Widening it to 0.82 through 0.95 produced a false match on the first run: a 44.00 USD
invoice dated 9 July fit a 27.83 EUR charge from 9 June on the arithmetic alone. Anything
outside 0.83 to 0.89 is a warning, not a hit.

## Subscription invoices carry two dates

Invoice date and next billing date both appear in the document. Treat them alike and last
month's invoice appears to match this month's charge through its renewal date.

The earliest date in the document is the invoice date.

## Amounts and dates are not keys

One ad platform bills the same amount over and over because of its spend limit, so neither
amount nor date identifies anything. The provider's reference string appears verbatim in
both the bank statement and the document, and that is the only reliable key.

A parser that read the campaign start date out of the body text filed a January charge
against an April invoice, and the numbers looked plausible.

## Folder names are not evidence

299 of 684 documents sat in the wrong vendor folder. One vendor's folder held another
vendor's invoices, insurance paperwork and a letter from a law firm.

Issuer comes from the PDF text. `index_documents.py` never reads the path.

## Many invoices are not files

Several vendors send the receipt as an HTML email with no attachment. A search filtered by
attachment never sees them and reports them as missing. In one quarter, 329 documents
existed only in a message body and had to be rebuilt into PDFs from the HTML.

## The reconciliation is a gate, not a report

Sum of entries must equal the payout on the statement. Off by a cent, nothing is written.
A batch that is almost right is worse than no batch, because it imports cleanly.
