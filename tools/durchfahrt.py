"""Vermutete Durchfahrten ergänzen.

Viele Züge ohne Zwischenhalt stehen in der HRDF nur mit zwei Punkten (z. B. IC Bern–Thun ohne Münsingen).
Ohne Zwischenpunkte weiss die Seite nicht, welchen Weg der Zug nimmt: Er fehlt auf Strecken, die er nur
durchfährt (Ostermundigen–Uttigen), und wird auf Parallelstrecken gelegt, die er nicht befährt (Bern–Belp–Thun).

Vorgehen
  1. Alle aufeinanderfolgenden Punktpaare (u, v) der Fahrten sammeln, je Paar die kürzeste Fahrzeit.
  2. Ein Paar ist «zusammengesetzt», wenn es zwischen u und v einen Weg über andere Paare gibt, der höchstens
     ZUSAMMEN_FAKTOR · Luftlinie + ZUSAMMEN_KM lang ist und mindestens einen Zwischenpunkt hat; sonst «elementar».
  3. Für jedes zusammengesetzte Paar den Weg über elementare Paare mit der kürzesten Summe der kürzesten Fahrzeiten
     suchen (nicht den kürzesten in km: Bern–Thun ist über Belp in km kürzer, über Münsingen aber schneller),
     innerhalb von WEG_FAKTOR · Luftlinie + WEG_KM.
  4. In jede Fahrt mit einer solchen Lücke die Zwischenpunkte als Durchfahrt einfügen, Zeit nach dem Anteil
     an der kürzesten Fahrzeit verteilt. Markierung im Feld «durchfahrt»: 2 = vermutet (1 = aus der HRDF).

build_data.py legt nur die Wegtabelle als «dw» in fahrplan.json.gz (tabelle()); die Seite fügt die Punkte
beim Laden ein, so bleibt die Datei klein. ergaenzen() macht dasselbe in Python (zum Prüfen).
Arbeitet auf dem kompakten Format von fahrplan.json.gz (st, tr). Lokal prüfen:
  python tools/durchfahrt.py web/data/fahrplan.json.gz [--out neu.json.gz] [--zeige "Bern" "Thun"]
"""
import argparse
import gzip
import heapq
import json
import math
from collections import defaultdict

ZUSAMMEN_FAKTOR, ZUSAMMEN_KM = 1.2, 1.0
WEG_FAKTOR, WEG_KM = 1.35, 2.0
MIN_KM = 1.5          # kürzere Paare nie aufteilen
VERMUTET = 2


def _hav(S, a, b):
    A, B = S[a], S[b]
    if A[2] is None or B[2] is None:
        return None
    R = math.pi / 180
    la1, la2 = A[2] * R, B[2] * R
    x = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((B[3] - A[3]) * R / 2) ** 2
    return 12742 * math.asin(math.sqrt(x))


def _zeit(v):
    return v if isinstance(v, (int, float)) and v >= 0 else None


def _kanten(S, trips):
    """{(u, v): kürzeste Fahrzeit in min oder None}, ungerichtet (u < v)."""
    zt = {}
    for t in trips:
        f = t[5]
        for i in range(0, len(f) - 4, 4):
            u, v = f[i], f[i + 4]
            if u == v:
                continue
            k = (u, v) if u < v else (v, u)
            t0 = _zeit(f[i + 2]) if _zeit(f[i + 2]) is not None else _zeit(f[i + 1])
            t1 = _zeit(f[i + 5]) if _zeit(f[i + 5]) is not None else _zeit(f[i + 6])
            dz = t1 - t0 if t0 is not None and t1 is not None and t1 > t0 else None
            alt = zt.get(k, "neu")
            if alt == "neu" or (dz is not None and (alt is None or dz < alt)):
                zt[k] = dz
    return zt


def _dijkstra(adj, S, u, v, lim, gewicht, verboten=None):
    dist, prev, pq = {u: 0.0}, {}, [(0.0, u)]
    km = {u: 0.0}
    while pq:
        du, x = heapq.heappop(pq)
        if x == v:
            break
        if du > dist.get(x, 1e18):
            continue
        for y, (w_km, w_z) in adj[x].items():
            if verboten and (x, y) in verboten:
                continue
            nk = km[x] + w_km
            rest = _hav(S, y, v) or 0
            if nk + rest > lim:
                continue
            nd = du + (w_km if gewicht == "km" else w_z)
            if nd < dist.get(y, 1e18):
                dist[y], prev[y], km[y] = nd, x, nk
                heapq.heappush(pq, (nd, y))
    if v not in dist:
        return None
    p = [v]
    while p[-1] != u:
        p.append(prev[p[-1]])
    return p[::-1]


def wege(S, trips):
    """{(u, v) gerichtet: [Zwischenpunkte], [Anteile 0..1]} für zusammengesetzte Paare."""
    zt = _kanten(S, trips)
    km = {k: _hav(S, *k) for k in zt}
    # Ersatzzeit, wo keine Fahrzeit bekannt: 1 min je km (60 km/h)
    adj = defaultdict(dict)
    for k, z in zt.items():
        if km[k] is None:
            continue
        u, v = k
        w = (km[k], z if z is not None else max(0.5, km[k]))
        adj[u][v] = w
        adj[v][u] = w
    zus = set()
    for (u, v), d in km.items():
        if d is None or d < MIN_KM:
            continue
        p = _dijkstra(adj, S, u, v, d * ZUSAMMEN_FAKTOR + ZUSAMMEN_KM, "km", verboten={(u, v), (v, u)})
        if p and len(p) > 2:
            zus.add((u, v))
    elem = defaultdict(dict)
    for x, nb in adj.items():
        for y, w in nb.items():
            if (min(x, y), max(x, y)) not in zus:
                elem[x][y] = w
    out = {}
    for (u, v) in zus:
        d = km[(u, v)]
        p = _dijkstra(elem, S, u, v, d * WEG_FAKTOR + WEG_KM, "zeit")
        if not p or len(p) < 3:
            continue
        z = [elem[a][b][1] for a, b in zip(p, p[1:])]
        tot = sum(z) or 1
        acc, ant = 0.0, []
        for x in z[:-1]:
            acc += x
            ant.append(acc / tot)
        out[(u, v)] = (p[1:-1], ant)
        out[(v, u)] = (p[-2:0:-1], [1 - a for a in reversed(ant)])
    return out


def tabelle(S, trips):
    """Wegtabelle für fahrplan.json.gz: [[u, v, [Zwischenpunkte], [Anteile]], …] nur in einer Richtung (u < v);
    die Seite fügt die Punkte beim Laden ein (beide Richtungen)."""
    W = wege(S, trips)
    return [[u, v, inner, [round(a, 3) for a in ant]] for (u, v), (inner, ant) in sorted(W.items()) if u < v]


def ergaenzen(S, trips):
    """Fügt vermutete Durchfahrten in trips ein (an Ort). Gibt (Fahrten geändert, Punkte eingefügt) zurück."""
    W = wege(S, trips)
    n_t = n_p = 0
    for t in trips:
        f = t[5]
        neu, geaendert = f[:4], False
        for i in range(0, len(f) - 4, 4):
            u, v = f[i], f[i + 4]
            w = W.get((u, v))
            if w:
                t0 = _zeit(f[i + 2]) if _zeit(f[i + 2]) is not None else _zeit(f[i + 1])
                t1 = _zeit(f[i + 5]) if _zeit(f[i + 5]) is not None else _zeit(f[i + 6])
                inner, ant = w
                if t0 is not None and t1 is not None and t1 >= t0 and not (set(inner) & set(f[0::4])):
                    for s, a in zip(inner, ant):
                        m = round(t0 + (t1 - t0) * a, 1)
                        neu += [s, m, m, VERMUTET]
                    n_p += len(inner)
                    geaendert = True
            neu += f[i + 4:i + 8]
        if geaendert:
            t[5] = neu
            n_t += 1
    return n_t, n_p


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("fahrplan")
    ap.add_argument("--out")
    ap.add_argument("--zeige", nargs=2, action="append", default=[], metavar=("VON", "NACH"))
    a = ap.parse_args()
    d = json.load(gzip.open(a.fahrplan, "rt", encoding="utf-8"))
    S = d["st"]
    W = wege(S, d["tr"])
    idx = {s[1]: i for i, s in enumerate(S)}
    for von, nach in a.zeige:
        w = W.get((idx.get(von), idx.get(nach)))
        print(von, "→", nach, ":", " – ".join(S[x][1] for x in w[0]) if w else "unverändert")
    print("Fahrten geändert, Punkte eingefügt:", ergaenzen(S, d["tr"]))
    if a.out:
        with gzip.open(a.out, "wt", encoding="utf-8", compresslevel=9) as f:
            json.dump(d, f, ensure_ascii=False, separators=(",", ":"))
