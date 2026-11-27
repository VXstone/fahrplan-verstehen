"""Weg je Zug aus der Publikation (grafische Fahrpläne SBB) als Grundgerüst für vermutete Durchfahrten.

  python tools/pub_wege.py --fahrplan web/data/fahrplan.json.gz --pub web/data/publikation.json.gz

Für jede Lücke u→v einer Fahrt (aufeinanderfolgende Punkte ohne Zwischenpunkt) wird der Zug gleicher Nummer in der
Publikation gesucht. Führt er zwischen u und v Betriebspunkte (Durchfahrten), gelten diese: Sie zeigen den Weg, den
dieser Zug im Jahresfahrplan nimmt (Born oder Aarburg-Oftringen, Oerlikon oder Flughafen). Übernommen werden nur
Punkte, die es in der HRDF gibt; was zwischen ihnen fehlt (Felder ohne Publikation), füllen die Wegtabellen aus dem
Gleisnetz (durchfahrt.py). Zeitanteile nach den publizierten Zeiten.

Ergebnis in fahrplan.json.gz (an Ort): "dwz": [[zugnr, u, v, [Zwischenpunkte], [Anteile]], …] nur dort, wo der Weg
von dem der Wegtabellen abweicht. Die Seite nimmt «dwz» vor den Wegtabellen. Die Publikation zeigt den Regelweg; an
Tagen mit Umleitung (Bauarbeiten) kann der wirkliche Weg anders sein.
"""
import argparse
import gzip
import json
from collections import defaultdict

from durchfahrt import fernverkehr


def nr(x):
    return str(x).lstrip("0").split("+")[0]


def karte(liste):
    m = {}
    for u, v, inner, ant in liste or []:
        m[(u, v)] = (inner, ant)
        m[(v, u)] = (inner[::-1], [round(1 - a, 3) for a in ant[::-1]])
    return m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fahrplan", required=True)
    ap.add_argument("--pub", required=True)
    a = ap.parse_args()
    d = json.load(gzip.open(a.fahrplan, "rt", encoding="utf-8"))
    p = json.load(gzip.open(a.pub, "rt", encoding="utf-8"))
    S = d["st"]
    nS = len(S)
    echt = lambda s: s < nS and S[s][2] is not None and str(S[s][0])[:2] == "85"
    DW = {"N": karte(d.get("dw")), "S": karte(d.get("dws")), "X": karte(d.get("dwx")), "F": karte(d.get("dwf"))}
    schmal = set(d.get("schmal", []))

    def tab(i, cat, k):
        if i in schmal:
            return DW["S"].get(k) or DW["F"].get(k)
        if fernverkehr(cat):
            return DW["X"].get(k) or DW["N"].get(k) or DW["F"].get(k)
        return DW["N"].get(k) or DW["F"].get(k)

    # Publikation: je Zugnummer die Reisezug-Läufe als Punktfolge mit Zeit
    pub = defaultdict(list)
    for z in p["tr"]:
        if z[1] != "R":
            continue
        f = z[4]
        pts = []
        for i in range(0, len(f), 4):
            t = f[i + 2] if f[i + 2] is not None else f[i + 1]
            pts.append((f[i], t))
        pub[nr(z[0])].append(pts)

    out, gesehen, n_luecken, n_pub = [], set(), 0, 0
    for i, t in enumerate(d["tr"]):
        zn = nr(t[0])
        laeufe = pub.get(zn)
        if not laeufe:
            continue
        f = t[5]
        for j in range(0, len(f) - 4, 4):
            u, v = f[j], f[j + 4]
            if u == v or (zn, u, v) in gesehen:
                continue
            gesehen.add((zn, u, v))
            n_luecken += 1
            treffer = None
            for pts in laeufe:
                st = [s for s, _ in pts]
                if u in st and v in st:
                    iu, iv = st.index(u), st.index(v)
                    if iu < iv - 1:
                        treffer = pts[iu:iv + 1]
                        break
            if not treffer:
                continue
            tu, tv = treffer[0][1], treffer[-1][1]
            mitte = [(s, tt) for s, tt in treffer[1:-1] if echt(s) and s not in (u, v)]
            if not mitte:
                continue
            # Anteile nach publizierter Zeit (sonst gleichmässig)
            n = len(mitte)
            if tu is not None and tv is not None and tv > tu and all(tt is not None and tu <= tt <= tv for _, tt in mitte):
                kette = [(u, 0.0)] + [(s, (tt - tu) / (tv - tu)) for s, tt in mitte] + [(v, 1.0)]
            else:
                kette = [(u, 0.0)] + [(s, (k + 1) / (n + 1)) for k, (s, _) in enumerate(mitte)] + [(v, 1.0)]
            # Lücken zwischen den publizierten Punkten aus den Wegtabellen füllen
            inner, ant = [], []
            for (x, ax), (y, ay) in zip(kette, kette[1:]):
                w = tab(i, t[2], (x, y))
                if w and w[0] and not (set(w[0]) & {s for s, _ in kette}) and not (set(w[0]) & set(inner)):
                    for s, aa in zip(w[0], w[1]):
                        inner.append(s)
                        ant.append(round(ax + (ay - ax) * aa, 3))
                if y != v:
                    inner.append(y)
                    ant.append(round(ay, 3))
            if len(set(inner)) != len(inner):
                continue
            alt = tab(i, t[2], (u, v))
            if alt and alt[0] == inner:
                continue
            out.append([zn, u, v, inner, ant])
            n_pub += 1
    d["dwz"] = out
    with gzip.open(a.fahrplan, "wt", encoding="utf-8", compresslevel=9) as fh:
        json.dump(d, fh, ensure_ascii=False, separators=(",", ":"))
    print(json.dumps({"luecken_mit_zug_in_publikation": n_luecken, "weg_aus_publikation": n_pub}))


if __name__ == "__main__":
    main()
