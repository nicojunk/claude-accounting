#!/usr/bin/env python3
"""Zuordnungs-Matcher v5, basierend auf index-inhalt.json.

Grundlage: der Aussteller wird aus dem PDF-Text bestimmt, nicht aus dem
Ordnernamen. 299 von 684 Belegen lagen im falschen Ordner (05.08.2026).

Regeln je Kontoumsatz:
  A) EUR-Beleg: Betrag exakt, Rechnungsdatum 0 bis 40 Tage vor Abbuchung.
  B) USD-Beleg: Rechnungsdatum 0 bis 3 Tage vor Abbuchung, Kurs 0,82 bis 0,95.
Gewinner ist der Kandidat mit dem kleinsten Abstand zum Buchungsdatum.
Bei Gleichstand bleibt der Fall mehrdeutig.
Jeder Beleg wird hoechstens einmal vergeben.
"""
import json
import os
import re
import unicodedata
from datetime import datetime
from pathlib import Path

BASE = Path(os.environ.get("ACCOUNTING_ROOT", "./documents"))
KURS_MIN, KURS_MAX = 0.83, 0.89

# Bankempfaenger -> Aussteller im Index
EMPF_ZU_AUSSTELLER = {
    "anthropic": "anthropic", "claude.ai": "anthropic", "claude sub": "anthropic",
    "www.make.com": "make", "make.com": "make",
    "apple.com/bill": "apple", "itunes": "apple",
    "manychat": "manychat", "onepage": "onepage", "addevent": "addevent",
    "circle.so": "circle", "replicate": "replicate", "typeform": "typeform",
    "wistia": "wistia", "facebk": "meta-facebook", "meta plat": "meta-facebook",
    "google": "google", "slack": "slack", "microsoft": "microsoft",
    "atlassian": "atlassian", "openai": "openai", "midjourney": "midjourney",
    "united domains": "united-domains", "uniteddomains": "united-domains",
    "erecht24": "erecht24", "webflow": "webflow", "airtable": "airtable",
    "hostinger": "hostinger", "epidemic": "epidemic",
    "perplexity": "perplexity", "openrouter": "openrouter",
    "elevenlabs": "elevenlabs", "descript": "descript", "canva": "canva",
    "notion": "notion", "vercel": "vercel", "supabase": "supabase",
    # Ergaenzt 05.08.2026: Empfaenger aus der Kontoauswertung, deren Belege
    # vorlagen, aber keinem Aussteller zugeordnet waren.
    "ninett": "ninett-krause", "krause": "ninett-krause",
    "ann-katrin": "ann-katrin", "kettner": "ann-katrin",
    "navigare": "navigare", "amazon": "amazon",
    "medienanstalt": "medienanstalt", "bundeskasse": "bundeskasse",
    "5 sterne": "5-sterne-team", "sterne team": "5-sterne-team",
}


def norm(s):
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", s or "").lower()).strip()


def betrag_num(s):
    if isinstance(s, (int, float)):
        return float(s)
    s = (s or "").strip().replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


def parse_datum(s):
    for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime((s or "").strip(), fmt)
        except ValueError:
            pass
    return None


def aussteller_fuer(empf):
    e = norm(empf)
    for muster, a in EMPF_ZU_AUSSTELLER.items():
        if muster in e:
            return a
    return None


def main():
    belege = json.loads((BASE / "index-inhalt.json").read_text())
    offen = json.loads((BASE / "offene-belege.json").read_text())["braucht_beleg"]

    nach_aussteller = {}
    for b in belege:
        a = b.get("aussteller")
        if not a:
            continue
        # Arbeitskopien in _zuordnung/ ueberspringen, sonst erscheint jeder
        # bereits zugeordnete Beleg doppelt und macht Faelle mehrdeutig.
        if "/_zuordnung/" in b["pfad"]:
            continue
        ds = sorted(d for d in (parse_datum(x) for x in b.get("daten", [])) if d)
        # Ein explizit ausgelesenes Zahldatum schlaegt das frueheste Datum.
        zd = parse_datum(b.get("zahldatum") or "")
        b["_rdatum"] = zd or (ds[0] if ds else None)
        b["_alle"] = ds
        nach_aussteller.setdefault(a, []).append(b)

    eindeutig, mehrdeutig, ohne = [], [], []

    for u in offen:
        soll = abs(betrag_num(u["betrag"]))
        udat = parse_datum(u["datum"])
        a = aussteller_fuer(u["empf"])
        if not udat or soll <= 0 or not a or a not in nach_aussteller:
            u["grund"] = "kein Aussteller erkannt" if not a else "kein Beleg dieses Ausstellers"
            ohne.append(u)
            continue

        usd_beleg_da = any(b.get("waehrung") == "USD" for b in nach_aussteller[a])
        kandidaten = []

        for b in nach_aussteller[a]:
            rd = b["_rdatum"]
            if not rd:
                continue
            abstand = (udat - rd).days
            treffer = None

            for cand in b.get("betraege", []):
                c = abs(float(cand))
                if c <= 0:
                    continue
                if abs(c - soll) < 0.015 and 0 <= abstand <= 40:
                    treffer = {"art": "eur-exakt", "belegbetrag": c, "kurs": None}
                    break
                if b.get("waehrung") == "USD" and 0 <= abstand <= 3:
                    kurs = soll / c
                    if KURS_MIN <= kurs <= KURS_MAX:
                        k = {"art": "usd-kurs", "belegbetrag": c, "kurs": round(kurs, 4)}
                        if not treffer or abs(k["kurs"] - 0.86) < abs((treffer.get("kurs") or 9) - 0.86):
                            treffer = k
            if not treffer:
                continue

            kandidaten.append({
                "pfad": b["pfad"], "datei": b["datei"], "aussteller": a,
                "ordner": b.get("ordner"), "q": b.get("q"), "abstand": abstand,
                "waehrung": b.get("waehrung"), **treffer,
                "rechnungsdatum": rd.strftime("%d.%m.%Y"),
                "alle_daten": [d.strftime("%d.%m.%Y") for d in b["_alle"]],
            })

        # Invoice und Receipt zum selben Vorgang zusammenfassen, Invoice gewinnt
        gruppen = {}
        for k in kandidaten:
            schl = f"{k['belegbetrag']:.2f}|{k['rechnungsdatum']}"
            ist_inv = bool(re.search(r"invoice|rechnung|^re[-_]|_re[-_]", k["datei"], re.I))
            vor = gruppen.get(schl)
            if vor is None or (ist_inv and not vor[1]):
                gruppen[schl] = (k, ist_inv)
        uniq = [v[0] for v in gruppen.values()]

        e = dict(u)
        if not uniq:
            e["grund"] = "kein passender Betrag/Datum"
            ohne.append(e)
            continue

        # Wenn es Belege desselben Ausstellers OHNE erkanntes Datum gibt,
        # ist die Datenlage unvollstaendig. Ein Treffer mit grossem Abstand
        # koennte dann nur deshalb gewinnen, weil der richtige Beleg kein
        # Datum hat. Solche Faelle nicht automatisch zuordnen.
        ohne_datum = sum(1 for b in nach_aussteller[a] if not b["_rdatum"])
        mn = min(k["abstand"] for k in uniq)
        if mn > 10 and ohne_datum:
            e["grund"] = f"Abstand {mn} Tage und {ohne_datum} Belege ohne Datum im Index"
            e["kandidaten"] = sorted(uniq, key=lambda x: x["abstand"])
            mehrdeutig.append(e)
            continue
        beste = [k for k in uniq if k["abstand"] == mn]
        # Bei Gleichstand im Datum entscheidet der plausiblere Kurs.
        # Beispiel Wistia 09.06.2026, 27,83 EUR: der Beleg ueber 32 USD ergibt
        # Kurs 0,870, der ueber 44 USD nur 0,633. Nur der erste ist richtig.
        if len(beste) > 1:
            mit_kurs = [k for k in beste if k.get("kurs")]
            if len(mit_kurs) == len(beste):
                beste.sort(key=lambda k: abs(k["kurs"] - 0.86))
                if abs(beste[0]["kurs"] - 0.86) < abs(beste[1]["kurs"] - 0.86) - 0.01:
                    beste = beste[:1]
        e["kandidaten"] = sorted(uniq, key=lambda x: x["abstand"])
        if len(beste) == 1:
            e["gewaehlt"] = beste[0]
            eindeutig.append(e)
        else:
            mehrdeutig.append(e)

    # Ein Beleg nur einmal vergeben
    vergeben, bereinigt, kollision = {}, [], []
    for e in sorted(eindeutig, key=lambda x: (x["datum"], x["betrag"])):
        p = e["gewaehlt"]["pfad"]
        if p in vergeben:
            ersatz = next((k for k in e["kandidaten"]
                           if k["pfad"] not in vergeben and k["abstand"] == e["gewaehlt"]["abstand"]), None)
            if ersatz:
                e["gewaehlt"] = ersatz
                vergeben[ersatz["pfad"]] = e["datum"]
                bereinigt.append(e)
            else:
                e["kollision_mit"] = vergeben[p]
                kollision.append(e)
            continue
        vergeben[p] = e["datum"]
        bereinigt.append(e)
    eindeutig = bereinigt

    for name, daten in [("match-eindeutig.json", eindeutig),
                        ("match-mehrdeutig.json", mehrdeutig),
                        ("match-ohne-beleg.json", ohne),
                        ("match-kollision.json", kollision)]:
        (BASE / name).write_text(json.dumps(daten, ensure_ascii=False, indent=1))

    print(f"offen gesamt:  {len(offen)}")
    print(f"EINDEUTIG:     {len(eindeutig)}")
    print(f"mehrdeutig:    {len(mehrdeutig)}")
    print(f"Kollision:     {len(kollision)}")
    print(f"kein Beleg:    {len(ohne)}")
    vol = sum(abs(betrag_num(e["betrag"])) for e in eindeutig)
    print(f"Volumen eindeutig: {vol:,.2f} EUR".replace(",", "X").replace(".", ",").replace("X", "."))

    print("\n--- EINDEUTIGE TREFFER ---")
    for e in sorted(eindeutig, key=lambda x: (x["quelle"], x["datum"])):
        k = e["gewaehlt"]
        z = f" kurs={k['kurs']}" if k["kurs"] else ""
        print(f"  {e['quelle']:7s} {e['datum']} {e['betrag']:>10} {e['empf'][:22]:22s} "
              f"<- {k['datei'][:40]:40s} d+{k['abstand']:<2d} [{k['art']}{z}]")


if __name__ == "__main__":
    main()
