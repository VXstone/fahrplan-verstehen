"""Güterzug-Liste aus dem publizierten Fahrplan (grafische Fahrpläne) – Verkehrstage Mo–So, Muster, Achse.

  python tools/gz_list.py --pub web/data/publikation.json.gz --fahrplan web/data/fahrplan.json.gz \
                          --nge lib/nge --out web/data

Eingaben
  publikation.json.gz  aus build_pub.py: {meta, st_add, tr:[[zug, kat, felder, vp, flat]]}
  fahrplan.json.gz     Jahresdaten der Seite (Stationsliste "st"; st_add der Publikation wird angehängt)
  --nge                Checkout von VXstone/NGE-fahrplan (für tools/grafapla_vp.py, VP-Entschlüsselung)

Ausgabe  <out>/gueterzuege.json, gueterzuege.csv, und gueterzuege.xlsx (nur wenn openpyxl da ist)
  Eine Zeile je Zuglauf mit den Spalten der Güterzug-Tabelle (Claude Sheet «Güterzüge Schweiz –
  publizierter Fahrplan <Jahr> (Mo–So)», Blatt «Güterzüge», Spalten A–X).

Regeln (wie in der Legende der Tabelle)
  - Güterzug = Kategorie G mit Nummer 4xxxx–6xxxx (optional ein Buchstabe, z. B. 67871F), bei der RhB jede
    G-Linie. Zusatz «mod» = Variante für einen Teil des Jahres: Nummer ohne «mod», als zeitweise.
  - Verkehrstage aus der VP; «+» und Abfahrt nach Mitternacht auf den Kalendertag der Abfahrt geschoben.
  - Teilstücke derselben Nummer mit gleichen Tagen, die ≤ 240′ nach dem Ende des vorigen beginnen, werden
    verkettet («Laufweg lückenhaft»). Danach Varianten derselben Nummer mit gleicher Relation und
    Abfahrt ±10′ zu einer Zeile zusammengefasst.
  - Klasse: täglich / werktags (≥ 4 von Mo–Fr, ≤ 1 Wochenendtag) / Wochenende (nur Sa, So) /
    einzelne Tage (1–2 Tage) / teilweise (Rest).
  - Achse nach Fahrplanfeld (540/541/531 Gotthard, 351/352/391 Lötschberg, 222/223 Simplon) und nach
    durchfahrenen Betriebspunkten (Gotthard, Luino, Chiasso); RhB-Felder → RhB; Pischahorn–Piz Fless →
    «Autoverlad Vereina».
Quelle der PDFs: Systemaufgabe Kundeninformation (SKI), oev-info.ch – Lizenz ungeklärt.
"""
import argparse
import collections
import csv
import gzip
import json
import re
import sys
from pathlib import Path

WD = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
KLASSEN = ["täglich", "werktags", "Wochenende", "teilweise", "einzelne Tage"]
HUBS = ["Basel SBB RB", "Basel Bad", "Pratteln", "Muttenz", "Olten", "Aarau", "Brugg", "Lenzburg", "Othmarsingen",
        "Zürich RB Limmattal", "Killwangen", "Zürich", "Winterthur", "Schaffhausen", "Romanshorn", "St. Margrethen",
        "Buchs SG", "Sargans", "Chur", "Rotkreuz", "Arth-Goldau", "Immensee", "Erstfeld", "Biasca", "Bellinzona",
        "Cadenazzo", "Luino", "Lugano", "Chiasso", "Bern", "Thun", "Spiez", "Frutigen", "Visp", "Brig", "Iselle",
        "Domodossola", "Biel", "Solothurn", "Langenthal", "Neuchâtel", "Yverdon", "Daillens", "Lausanne-Triage",
        "Lausanne", "Vallorbe", "Genève", "La Praille", "Fribourg", "Delémont", "Rothrist", "Wanzwil"]
ZUGLAUF = "https://vxstone.github.io/fahrplan-verstehen/?zug="
# Spalten der Tabelle (A–X): Überschrift, Feld
SPALTEN = ([("Zug", "zug"), ("Zuglauf", None), ("Verkehrstage", "tage"), ("Klasse", "klasse"), ("Achse", "achse"),
            ("Von", "von"), ("Ab", "ab"), ("Nach", "nach")] + [(w, w) for w in WD]
           + [("An", "an"), ("Fahrzeit min", "dauer"), ("über", "via"), ("zeitweise (*)", "zeitweise"),
              ("Feiertage", "feiertage"), ("Zeiten", "zeiten"), ("Laufweg lückenhaft", "luecke"),
              ("VP roh", "vp"), ("Fahrplanfelder", "felder")])


def hm(m):
    m = int(round(m))
    return f"{m // 60 % 24:02d}:{m % 60:02d}"


def tm(x):
    h, m = map(int, x.split(":"))
    return h * 60 + m


def cdist(a, b):
    d = abs(a - b) % 1440
    return min(d, 1440 - d)


def label(days):
    d = sorted(set(days))
    if not d:
        return "unklar"
    if len(d) == 7:
        return "täglich"
    s = set(d)
    for start in range(1, 8):  # zyklisch zusammenhängend → Spanne
        run = [(start - 1 + i) % 7 + 1 for i in range(len(d))]
        if set(run) == s and ((start - 2) % 7 + 1) not in s:
            return WD[run[0] - 1] if len(run) == 1 else f"{WD[run[0] - 1]}–{WD[run[-1] - 1]}"
    if len(d) == 6:
        return "täglich ausser " + WD[[x for x in range(1, 8) if x not in s][0] - 1]
    return ", ".join(WD[x - 1] for x in d)


def klasse(days):
    s = set(days)
    wk = len(s & {1, 2, 3, 4, 5})
    we = len(s & {6, 7})
    if not s:
        return "unklar"
    if len(s) == 7:
        return "täglich"
    if wk >= 4 and we <= 1:
        return "werktags"
    if s <= {6, 7}:
        return "Wochenende"
    if len(s) <= 2:
        return "einzelne Tage"
    return "teilweise"


def hubs(stl):
    out = []
    for n in stl:
        h = next((h for h in HUBS if n.startswith(h)), None)
        if h and (not out or out[-1] != h):
            out.append(h)
    return out


def achse(stl, felder, zug):
    t = " ".join(stl)
    f = set(felder)
    if "Pischahorn" in t and "Piz Fless" in t and not re.fullmatch(r"5\d{3}", zug):  # RhB-Güterzüge G 5xxx nicht
        return "Autoverlad Vereina"
    a = []
    if f & {"540", "541", "531"} or any(k in t for k in ("Pollegio", "Biasca", "Erstfeld", "Rynächt", "Göschenen",
                                                         "Airolo")) \
            or ("Arth-Goldau" in t and any(k in t for k in ("Bellinzona", "Castione", "Cadenazzo", "Giubiasco"))):
        a.append("Gotthard")
    if f & {"351", "352", "391"} or any(k in t for k in ("Frutigen", "Kandersteg", "Goppenstein", "Ferden")):
        a.append("Lötschberg")
    if f & {"222", "223"} or any(k in t for k in ("Iselle", "Domodossola")):
        a.append("Simplon")
    if "Luino" in t:
        a.append("Luino")
    if "Chiasso" in t or "Balerna" in t:
        a.append("Chiasso")
    if any(x.startswith("RhB") for x in f):
        a.append("RhB")
    return " / ".join(a)


def build(pub, fp, decode):
    S = fp["st"] + pub["st_add"]
    rows = []
    for zug, kat, felder, vp, flat in pub["tr"]:
        if kat != "G":
            continue
        mod = zug.endswith("mod")
        if mod:
            zug = zug[:-3]
        if not (re.fullmatch(r"[4-6]\d{4}[A-Z]?", zug) or any(f.startswith("RhB") for f in felder)):
            continue
        stl = [S[flat[k]][1] for k in range(0, len(flat), 4)]
        t0 = flat[2] if flat[2] is not None else flat[1]
        t1 = flat[-3]
        days, zeit, wt = set(), mod, False
        for v in vp.split("|"):
            r = decode(v)
            zeit |= r["begrenzt"]
            wt |= r["wt"]
            shift = r["folgetag"] + (1 if t0 >= 1440 else 0)
            days |= {(x - 1 + shift) % 7 + 1 for x in r["tage"]}
        rows.append(dict(stl=stl, zug=zug, von=stl[0], ab=hm(t0), nach=stl[-1], an=hm(t1), dauer=round(t1 - t0),
                         days=days, zeitweise="ja" if zeit else "", feiertage="wie So" if wt else "",
                         vp=vp, felder=list(felder), luecke=""))

    # 1. Teilstücke derselben Nummer verketten (Halt im Rangierbahnhof, Abschnitt ohne grafischen Fahrplan)
    byz = collections.defaultdict(list)
    for r in rows:
        byz[r["zug"]].append(r)
    rows = []
    for rs in byz.values():
        rs.sort(key=lambda r: tm(r["ab"]))
        out = []
        for r in rs:
            prev = next((o for o in out if o["days"] == r["days"]
                         and 0 <= (tm(r["ab"]) - tm(o["an"])) % 1440 <= 240), None)
            if prev:
                prev.update(nach=r["nach"], an=r["an"], dauer=(tm(r["an"]) - tm(prev["ab"])) % 1440,
                            stl=prev["stl"] + r["stl"], felder=sorted(set(prev["felder"]) | set(r["felder"])),
                            luecke="ja")
            else:
                out.append(r)
        rows += out

    for r in rows:
        r["via"] = " – ".join(h for h in hubs(r["stl"]) if not r["von"].startswith(h) and not r["nach"].startswith(h))
        r["achse"] = achse(r["stl"], r["felder"], r["zug"])

    # 2. Varianten derselben Nummer, gleiche Relation, Abfahrt ±10′ zusammenfassen
    merged = []
    for r in sorted(rows, key=lambda r: (r["zug"], r["von"], r["nach"], r["ab"])):
        m = merged[-1] if merged else None
        if m and (m["zug"], m["von"], m["nach"]) == (r["zug"], r["von"], r["nach"]) \
                and cdist(tm(m["ab"]), tm(r["ab"])) <= 10:
            m["days"] |= r["days"]
            m["vp"] += "|" + r["vp"]
            m["zeitweise"] = m["zeitweise"] or r["zeitweise"]
            if r["ab"] != m["ab"]:
                m["zeiten"] = "je nach Tag ±10′"
            continue
        r["zeiten"] = ""
        merged.append(r)

    out = []
    for r in merged:
        d = r.pop("days")
        r.pop("stl")
        r.update(tage=label(d), klasse=klasse(d), vp="|".join(sorted(set(r["vp"].split("|")))),
                 felder=" ".join(r["felder"]), **{w: ("x" if i + 1 in d else "") for i, w in enumerate(WD)})
        out.append(r)
    out.sort(key=lambda r: (int(re.sub(r"\D", "", r["zug"]) or 0), r["ab"]))
    return out


def write_xlsx(rows, path, meta):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font
    wb = Workbook()
    ws = wb.active
    ws.title = "Güterzüge"
    ws.append([c for c, _ in SPALTEN])
    for i, r in enumerate(rows, start=2):
        line = []
        for _, k in SPALTEN:
            if k is None:
                line.append(f'=HYPERLINK("{ZUGLAUF}"&A{i},"Karte ↗")')
            else:
                line.append(r[k] if r[k] != "" else None)
        ws.append(line)
        for c in (1, 7, 16, 23):  # Zug, Ab, An, VP als Text
            ws.cell(i, c).number_format = "@"
    for c in ws[1]:
        c.font = Font(bold=True)
    for col in "IJKLMNO":
        for cell in ws[col][1:]:
            cell.alignment = Alignment(horizontal="center")
    ws.freeze_panes = "B2"
    lg = wb.create_sheet("Stand")
    for k, v in meta.items():
        lg.append([k, json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v])
    wb.save(path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pub", required=True)
    ap.add_argument("--fahrplan", required=True)
    ap.add_argument("--nge", required=True, help="Checkout VXstone/NGE-fahrplan (tools/grafapla_vp.py)")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    sys.path.insert(0, str(Path(a.nge) / "tools"))
    from grafapla_vp import decode

    pub = json.load(gzip.open(a.pub, "rt", encoding="utf-8"))
    fp = json.load(gzip.open(a.fahrplan, "rt", encoding="utf-8"))
    rows = build(pub, fp, decode)

    pro_tag = {w: sum(1 for r in rows if r[w]) for w in WD}
    meta = dict(quelle=pub["meta"].get("quelle"), publikation_erzeugt=pub["meta"].get("erzeugt"),
                zeilen=len(rows), pro_tag=pro_tag,
                klassen={k: sum(1 for r in rows if r["klasse"] == k) for k in KLASSEN + ["unklar"]},
                achsen=dict(collections.Counter(r["achse"] for r in rows if r["achse"]).most_common()),
                lizenz="Systemaufgabe Kundeninformation (SKI), oev-info.ch – Lizenz ungeklärt")
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    felder = [k for _, k in SPALTEN if k]
    json.dump(dict(meta=meta, spalten=felder, zeilen=[[r[k] for k in felder] for r in rows]),
              open(out / "gueterzuege.json", "w", encoding="utf-8"), ensure_ascii=False)
    with open(out / "gueterzuege.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow([c for c, k in SPALTEN if k])
        w.writerows([r[k] for k in felder] for r in rows)
    try:
        write_xlsx(rows, out / "gueterzuege.xlsx", meta)
    except ImportError:
        print("openpyxl fehlt – keine xlsx", file=sys.stderr)
    print(json.dumps(meta, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
