#!/usr/bin/env python3
"""Baut einen Belegindex auf Basis des PDF-INHALTS, nicht des Ordnernamens.

Anlass 05.08.2026: Belege liegen nachweislich in falschen Lieferantenordnern
(eine Make-Rechnung unter anthropic/, eine weitere unter telekom/, ein
Wistia-Beleg unter circle/). Der Ordnername ist damit als Zuordnungskriterium
unbrauchbar.

Erfasst je Beleg: erkannter Aussteller, alle Betraege, alle Daten, Waehrung.
"""
import json
import os
import re
import subprocess
import sys
import unicodedata
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime
from pathlib import Path

BASE = Path(os.environ.get("ACCOUNTING_ROOT", "./documents"))

# Aussteller-Erkennung am PDF-Text. Reihenfolge zaehlt, spezifisch vor allgemein.
AUSSTELLER = [
    ("make",            [r"billing@make\.com", r"celonis inc", r"make\.com"]),
    ("anthropic",       [r"anthropic pbc", r"anthropic,? inc", r"anthropic\b"]),
    ("openai",          [r"openai,? (llc|inc)", r"openai\b"]),
    ("google",          [r"google (cloud|ireland|llc|workspace)", r"google\b"]),
    ("meta-facebook",   [r"meta platforms", r"facebook ireland", r"meta ireland"]),
    ("apple",           [r"apple distribution", r"apple inc", r"itunes"]),
    ("typeform",        [r"typeform"]),
    ("wistia",          [r"wistia"]),
    ("circle",          [r"circle\.so", r"circle internet"]),
    ("manychat",        [r"manychat"]),
    ("addevent",        [r"addevent"]),
    ("replicate",       [r"replicate,? inc", r"replicate\b"]),
    ("onepage",         [r"onepage", r"one page gmbh"]),
    ("slack",           [r"slack technologies"]),
    ("microsoft",       [r"microsoft (ireland|corporation)"]),
    ("atlassian",       [r"atlassian"]),
    ("midjourney",      [r"midjourney"]),
    ("united-domains",  [r"united[- ]domains"]),
    ("erecht24",        [r"erecht24", r"e-recht24"]),
    ("webflow",         [r"webflow"]),
    ("airtable",        [r"airtable"]),
    ("telekom",         [r"telekom deutschland", r"deutsche telekom"]),
    ("lexware",         [r"lexware", r"haufe"]),
    ("datev",           [r"datev eg"]),
    ("zoom",            [r"zoom video", r"zoom communications"]),
    ("stripe",          [r"stripe payments", r"stripe,? inc"]),
    ("paddle",          [r"paddle\.com", r"paddle\b"]),
    ("webinarjam",      [r"webinarjam", r"genesis digital"]),
    ("cloudconvert",    [r"cloudconvert"]),
    ("perplexity",      [r"perplexity"]),
    ("openrouter",      [r"openrouter"]),
    ("elevenlabs",      [r"elevenlabs", r"eleven labs"]),
    ("descript",        [r"descript"]),
    ("canva",           [r"canva"]),
    ("notion",          [r"notion labs"]),
    ("vercel",          [r"vercel"]),
    ("supabase",        [r"supabase"]),
    ("hostinger",       [r"hostinger"]),
    ("epidemic",        [r"epidemic sound"]),
    ("contentstudio",   [r"contentstudio"]),
    ("airbnb",          [r"airbnb"]),
    # Nachgetragen: diese Aussteller wurden
    # bisher gar nicht erkannt, ihre Belege lagen ungenutzt im Index.
    ("ninett-krause",   [r"ninett", r"success ?coach"]),
    ("ann-katrin",      [r"ann-katrin", r"ann katrin", r"kettner"]),
    ("navigare",        [r"navigare"]),
    ("amazon",          [r"amazon", r"evershop", r"eoto-?light"]),
    ("medienanstalt",   [r"medienanstalt"]),
    ("5-sterne-team",   [r"5 sterne team", r"fuenf sterne"]),
    ("port",            [r"port gmbh", r"gewinner community"]),
    ("bundeskasse",     [r"bundeskasse"]),
    ("finanzamt",       [r"finanzamt", r"säumniszuschlag"]),
]

DATUM_MUSTER = [
    (r"\b(\d{1,2})\.(\d{1,2})\.(20\d{2})\b", "dmy"),
    (r"\b(20\d{2})-(\d{2})-(\d{2})\b", "ymd"),
    (r"\b(january|february|march|april|may|june|july|august|september|october|november|december)\s+(\d{1,2}),?\s+(20\d{2})\b", "mdy_en"),
    (r"\b(\d{1,2})\s+(januar|februar|märz|april|mai|juni|juli|august|september|oktober|november|dezember)\s+(20\d{2})\b", "dmy_de"),
]
EN = ["january", "february", "march", "april", "may", "june", "july",
      "august", "september", "october", "november", "december"]
DE = ["januar", "februar", "märz", "april", "mai", "juni", "juli",
      "august", "september", "oktober", "november", "dezember"]


def norm(s):
    return unicodedata.normalize("NFC", s or "").lower()


def analysiere(pfad_str):
    pfad = Path(pfad_str)
    try:
        r = subprocess.run(["pdftotext", "-layout", str(pfad), "-"],
                           capture_output=True, timeout=40)
        txt = norm(r.stdout.decode("utf-8", "replace"))
    except Exception as e:
        return {"pfad": str(pfad), "datei": pfad.name, "fehler": str(e)}

    aussteller = None
    for name, muster in AUSSTELLER:
        if any(re.search(m, txt) for m in muster):
            aussteller = name
            break

    betraege = set()
    for m in re.finditer(r"(?<![\d.,])(\d{1,3}(?:[.,]\d{3})*[.,]\d{2})(?![\d])", txt):
        s = m.group(1)
        if s.count(",") == 1 and (s.rfind(",") > s.rfind(".")):
            v = s.replace(".", "").replace(",", ".")
        else:
            v = s.replace(",", "")
        try:
            f = float(v)
            if 0.01 <= f <= 500000:
                betraege.add(round(f, 2))
        except ValueError:
            pass

    daten = set()
    for muster, art in DATUM_MUSTER:
        for m in re.finditer(muster, txt):
            try:
                if art == "dmy":
                    d = datetime(int(m.group(3)), int(m.group(2)), int(m.group(1)))
                elif art == "ymd":
                    d = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
                elif art == "mdy_en":
                    d = datetime(int(m.group(3)), EN.index(m.group(1)) + 1, int(m.group(2)))
                else:
                    d = datetime(int(m.group(3)), DE.index(m.group(2)) + 1, int(m.group(1)))
                if 2024 <= d.year <= 2027:
                    daten.add(d.strftime("%Y-%m-%d"))
            except (ValueError, IndexError):
                pass

    # Wenn im PDF-Text kein Datum steht, aus dem Dateinamen lesen.
    # 1517 von 3032 Belegen hatten kein Textdatum, viele tragen es im Namen
    # (20260118_..., Jan_24__2026_..., Aug 24_ 2025_...).
    if not daten:
        n = pfad.name
        m = re.search(r"(20\d{2})(\d{2})(\d{2})", n)
        if m:
            try:
                d = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
                if 2024 <= d.year <= 2027:
                    daten.add(d.strftime("%Y-%m-%d"))
            except ValueError:
                pass
        if not daten:
            nn = norm(n).replace("_", " ")
            m = re.search(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+(\d{1,2})\D+(20\d{2})", nn)
            if m:
                kurz = ["jan", "feb", "mar", "apr", "may", "jun",
                        "jul", "aug", "sep", "oct", "nov", "dec"]
                try:
                    d = datetime(int(m.group(3)), kurz.index(m.group(1)) + 1, int(m.group(2)))
                    if 2024 <= d.year <= 2027:
                        daten.add(d.strftime("%Y-%m-%d"))
                except (ValueError, IndexError):
                    pass

    # Explizites Zahlungs- oder Rechnungsdatum hat Vorrang vor allen anderen
    # Daten im Text. Ohne das gewinnt bei Wistia der Abrechnungszeitraum-Beginn
    # (09.05.) statt des Zahltags (09.06.), und die Zuordnung schlaegt fehl.
    zahldatum = None
    for muster in [r"date paid:?\s*([a-z]+ \d{1,2},? 20\d{2})",
                   r"paid on\s*([a-z]+ \d{1,2},? 20\d{2})",
                   r"(?:rechnungs-?/?zahlungsdatum|rechnungsdatum|invoice date|date of issue)"
                   r":?\s*(\d{1,2}\.\d{1,2}\.20\d{2}|[a-z]+ \d{1,2},? 20\d{2})"]:
        m = re.search(muster, txt)
        if not m:
            continue
        roh = m.group(1).replace(",", "")
        for fmt in ("%B %d %Y", "%d.%m.%Y"):
            try:
                zahldatum = datetime.strptime(roh.strip().title() if "%B" in fmt else roh.strip(), fmt)
                break
            except ValueError:
                pass
        if zahldatum:
            break
    if zahldatum and 2024 <= zahldatum.year <= 2027:
        daten = {zahldatum.strftime("%Y-%m-%d")} | daten

    waehrung = "USD" if re.search(r"\$|\busd\b", txt) else ("EUR" if re.search(r"€|\beur\b", txt) else "?")

    return {
        "pfad": str(pfad), "datei": pfad.name, "ordner": pfad.parent.name,
        "q": "Q1" if "/Q1/" in str(pfad) else ("Q2" if "/Q2/" in str(pfad) else "?"),
        "aussteller": aussteller, "waehrung": waehrung,
        "betraege": sorted(betraege, reverse=True)[:12],
        "daten": sorted(daten),
        "zahldatum": zahldatum.strftime("%Y-%m-%d") if zahldatum else None,
        "datum_quelle": "text" if re.search(r"\d{1,2}\.\d{1,2}\.20\d{2}|20\d{2}-\d{2}-\d{2}", txt) else "dateiname",
        "kopf": re.sub(r"\s+", " ", txt[:400]),
    }


def main():
    wurzeln = [
    ]
    pdfs = []
    for w in wurzeln:
        if w.exists():
            pdfs += [str(p) for p in w.rglob("*.pdf")]
    # Dubletten " 2.pdf" / " 3.pdf" ueberspringen, sie enthalten dasselbe
    pdfs = [p for p in pdfs if not re.search(r" \d+\.pdf$", p)]
    pdfs = sorted(set(pdfs))
    print(f"{len(pdfs)} PDFs werden gelesen ...", flush=True)

    ergebnis = []
    with ProcessPoolExecutor(max_workers=8) as ex:
        for i, r in enumerate(ex.map(analysiere, pdfs, chunksize=8), 1):
            ergebnis.append(r)
            if i % 200 == 0:
                print(f"  {i}/{len(pdfs)}", flush=True)

    (BASE / "index-inhalt.json").write_text(json.dumps(ergebnis, ensure_ascii=False, indent=1))

    from collections import Counter
    erkannt = [r for r in ergebnis if r.get("aussteller")]
    print(f"\nfertig: {len(ergebnis)} Belege, davon {len(erkannt)} mit erkanntem Aussteller")
    falsch = [r for r in erkannt if r.get("ordner") and r["aussteller"] != r["ordner"]]
    print(f"Ordner weicht vom Aussteller ab: {len(falsch)}")
    for r in falsch[:20]:
        print(f"  {r['ordner']:20s} -> {r['aussteller']:16s} {r['datei'][:44]}")


if __name__ == "__main__":
    main()
