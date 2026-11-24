"""Gleiszahlen je Abschnitt aus VXstone/topo-daten übernehmen (nur lesen) → web/data/gleise.json.

  python tools/build_gleise.py --topo <ordner mit <region>_region_topologie.json> \
         --fahrplan web/data/fahrplan.json.gz [--pub web/data/publikation.json.gz] --out web/data

Quelle (topo-daten, Format von spurplan/code/straenge.py --topologie bzw. topologie_linien.py):
  nodes [{id, name, kind station|halt|junction|exit|end, x, y}] in Metern (lokal), edges [{a, b, tracks, length, refs}].
  `tracks` = Anzahl paralleler Streckengleise zwischen zwei Betriebspunkten (max. 4). Hier wird nichts an der
  Topologie gerechnet, nur zugeordnet: Betriebspunkt der Topologie → Station der Seite (UIC).

Zuordnung
  1. gleicher Name (normalisiert: Akzente, «(Abzw)», «Bf», Zusätze nach «/» weg);
  2. sonst Lage: x/y werden an den Namenstreffern auf Koordinaten eingepasst (affin, kleinste Quadrate) und dem
     nächsten Punkt ≤ 300 m (Abzweig ≤ 100 m) zugeordnet (Betriebspunkte aus fahrplan.json und st_add der Publikation).
Paare: zwischen zwei zugeordneten Punkten der Weg im Topologie-Graphen über höchstens 3 weitere zugeordnete Punkte
(Strecke der Seite kann Betriebspunkte überspringen); je Paar min./max. Gleiszahl und Länge.

Ausgabe gleise.json: {meta, ab: {"<uicA>-<uicB>" (A<B): [min, max, laenge_m, region]}}
Mit --pub zusätzlich gueterabschnitte.csv: alle von Güterzügen befahrenen Abschnitte (aufeinanderfolgende Punkte der
Publikation) mit Anzahl Züge und ob topo-daten den Abschnitt kennt – Prüfliste für topo-daten (fehlende Verbindung,
reine Güterabschnitte nach REGELN 1.21), keine Eingabe hier.
"""
import argparse
import collections
import csv
import gzip
import heapq
import json
import math
import re
import unicodedata
from pathlib import Path

MAX_M = 300
HOPS = 3


def norm(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    s = s.split("/")[0]
    s = re.sub(r"\((abzw|bif|diag|abzweigung|spw|dfp)\)|\bbf\b|\bsbb\b|\bcff\b|\bffs\b", " ", s)
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def fit(pairs):
    """affine Abbildung (x, y) → (lat, lon) aus Paaren, kleinste Quadrate ohne numpy."""
    def solve(rows, rhs):
        # Normalgleichungen 3×3
        A = [[sum(r[i] * r[j] for r in rows) for j in range(3)] for i in range(3)]
        b = [sum(r[i] * v for r, v in zip(rows, rhs)) for i in range(3)]
        for c in range(3):
            p = max(range(c, 3), key=lambda r: abs(A[r][c]))
            A[c], A[p], b[c], b[p] = A[p], A[c], b[p], b[c]
            for r in range(3):
                if r != c and A[c][c]:
                    f = A[r][c] / A[c][c]
                    A[r] = [x - f * y for x, y in zip(A[r], A[c])]
                    b[r] -= f * b[c]
        return [b[i] / A[i][i] for i in range(3)]
    rows = [(x, y, 1.0) for (x, y), _ in pairs]
    ca = solve(rows, [ll[0] for _, ll in pairs])
    co = solve(rows, [ll[1] for _, ll in pairs])
    return lambda x, y: (ca[0] * x + ca[1] * y + ca[2], co[0] * x + co[1] * y + co[2])


def dist_m(a, b):
    kx = 111320 * math.cos(math.radians(a[0]))
    return math.hypot((a[1] - b[1]) * kx, (a[0] - b[0]) * 110540)


def region(name, T, S, byname):
    nodes = {n["id"]: n for n in T["nodes"]}
    m, how = {}, {}
    for n in nodes.values():
        if n["kind"] in ("exit", "end"):
            continue
        c = byname.get(norm(n["name"]), [])
        if len(c) == 1:
            m[n["id"]], how[n["id"]] = c[0], "Name"
    pairs = [((nodes[i]["x"], nodes[i]["y"]), (S[u][2], S[u][3])) for i, u in m.items()]
    f = None
    if len(pairs) >= 3:
        f = fit(pairs)
        # Namenstreffer, die nicht zur Lage passen (gleicher Name anderswo), wieder weg
        for i in list(m):
            if dist_m(f(nodes[i]["x"], nodes[i]["y"]), (S[m[i]][2], S[m[i]][3])) > 2 * MAX_M:
                del m[i], how[i]
        pairs = [((nodes[i]["x"], nodes[i]["y"]), (S[u][2], S[u][3])) for i, u in m.items()]
        f = fit(pairs) if len(pairs) >= 3 else None
    if f:
        lat = [f(n["x"], n["y"])[0] for n in nodes.values()]
        lon = [f(n["x"], n["y"])[1] for n in nodes.values()]
        cand = [u for u, s in S.items() if min(lat) - .02 <= s[2] <= max(lat) + .02 and min(lon) - .03 <= s[3] <= max(lon) + .03]
        used = set(m.values())
        for n in nodes.values():
            if n["id"] in m or n["kind"] in ("exit", "end"):
                continue
            p = f(n["x"], n["y"])
            best = min(((dist_m(p, (S[u][2], S[u][3])), u) for u in cand if u not in used), default=None)
            if best and best[0] <= (100 if n["kind"] == "junction" else MAX_M):
                m[n["id"]], how[n["id"]] = best[1], f"Lage {best[0]:.0f} m"
                used.add(best[1])
    # Graph
    adj = collections.defaultdict(list)
    for e in T["edges"]:
        adj[e["a"]].append((e["b"], e))
        adj[e["b"]].append((e["a"], e))
    ab = {}
    for s0 in m:
        # Dijkstra nach Länge, Zustand (Knoten, Zahl durchfahrener zugeordneter Punkte)
        pq = [(0.0, s0, 0, 9, 0)]
        seen = set()
        while pq:
            d, v, hops, tmin, tmax = heapq.heappop(pq)
            if (v, hops) in seen:
                continue
            seen.add((v, hops))
            if v != s0 and v in m:
                ua, ub = sorted((S[m[s0]][0], S[m[v]][0]))
                k = f"{ua}-{ub}"
                if k not in ab or d < ab[k][2]:
                    ab[k] = [tmin, tmax, round(d), name]
                hops += 1
                if hops > HOPS:
                    continue
            for w, e in adj[v]:
                if nodes[w]["kind"] in ("exit", "end"):
                    continue
                heapq.heappush(pq, (d + e["length"], w, hops, min(tmin, e["tracks"]), max(tmax, e["tracks"])))
    zu = dict(knoten=sum(1 for n in nodes.values() if n["kind"] not in ("exit", "end")), zugeordnet=len(m),
              ueber_lage={nodes[i]["name"]: f"{S[m[i]][1]} ({h})" for i, h in sorted(how.items()) if h.startswith("Lage")},
              ohne=sorted(n["name"] for n in nodes.values() if n["kind"] not in ("exit", "end") and n["id"] not in m))
    return ab, zu


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--topo", required=True, help="Ordner mit *_topologie.json (eine Datei je Region)")
    ap.add_argument("--fahrplan", required=True)
    ap.add_argument("--pub")
    ap.add_argument("--stand", help="JSON mit Commit/Quelle je Region (optional)")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    fp = json.load(gzip.open(a.fahrplan, "rt", encoding="utf-8"))
    pub = json.load(gzip.open(a.pub, "rt", encoding="utf-8")) if a.pub else None
    st = fp["st"] + (pub["st_add"] if pub else [])
    S = {i: s for i, s in enumerate(st)}
    byname = collections.defaultdict(list)
    for i, s in S.items():
        byname[norm(s[1])].append(i)

    ab, regionen = {}, {}
    for p in sorted(Path(a.topo).glob("*_topologie.json")):
        r = p.name.split("_")[0]
        res, zu = region(r, json.load(open(p, encoding="utf-8")), S, byname)
        for k, v in res.items():
            if k not in ab or v[2] < ab[k][2]:
                ab[k] = v
        zu["paare"] = len(res)
        regionen[r] = zu
    meta = dict(quelle="VXstone/topo-daten (Regionstopologien, OSM © OpenStreetMap-Mitwirkende, ODbL)",
                regionen=regionen, paare=len(ab),
                gleise={str(n): sum(1 for v in ab.values() if v[0] == n) for n in range(1, 5)},
                hinweis="min/max = engster/weitester Teil des Abschnitts; Abschnitte ohne Eintrag: aus dem Fahrplan geschätzt")
    if a.stand:
        meta["stand"] = json.load(open(a.stand, encoding="utf-8"))
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    json.dump(dict(meta=meta, ab=ab), open(out / "gleise.json", "w", encoding="utf-8"), ensure_ascii=False,
              separators=(",", ":"))

    if pub:
        cnt, zuege = collections.Counter(), collections.defaultdict(set)
        for zug, kat, felder, vp, flat in pub["tr"]:
            if kat != "G":
                continue
            pts = [flat[k] for k in range(0, len(flat), 4)]
            for x, y in zip(pts, pts[1:]):
                if x == y:
                    continue
                k = tuple(sorted((x, y), key=lambda i: S[i][0]))
                cnt[k] += 1
                zuege[k].add(zug)
        with open(out / "gueterabschnitte.csv", "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["von", "nach", "von_abk", "nach_abk", "von_uic", "nach_uic", "luftlinie_m", "fahrten_publ",
                        "zuege", "topo_daten", "gleise_min", "gleise_max", "region"])
            for (x, y), n in sorted(cnt.items(), key=lambda t: -t[1]):
                k = f"{S[x][0]}-{S[y][0]}"
                g = ab.get(k)
                w.writerow([S[x][1], S[y][1], S[x][4], S[y][4], S[x][0], S[y][0],
                            round(dist_m((S[x][2], S[x][3]), (S[y][2], S[y][3]))), n, len(zuege[(x, y)]),
                            "ja" if g else "", g[0] if g else "", g[1] if g else "", g[3] if g else ""])
        meta["gueterabschnitte"] = dict(gesamt=len(cnt), in_topo=sum(1 for x, y in cnt if f"{S[x][0]}-{S[y][0]}" in ab))
    print(json.dumps(meta, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
