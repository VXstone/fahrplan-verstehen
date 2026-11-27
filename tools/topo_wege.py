"""Wege durchs Gleisnetz aus VXstone/topo-daten (OSM-Extrakt schweiz_bahn.json.gz, Release «daten»).

Für Züge ohne Zwischenpunkte (siehe durchfahrt.py) wird der schnellste Weg im Gleisnetz gesucht:
Gewicht = Länge / Höchstgeschwindigkeit (OSM maxspeed, sonst nach usage/service geschätzt).
Dann werden die Betriebspunkte des Fahrplans gesucht, an denen der Weg vorbeiführt (≤ NAH_KM vom Weg),
in der Reihenfolge entlang des Wegs, mit dem Zeitanteil bis dorthin.

Grenzen: Der Extrakt endet an der Landesgrenze; Punktpaare im Ausland bleiben bei durchfahrt.py (Fahrplangraph).
"""
import gzip
import heapq
import json
import math
from collections import defaultdict

FANG_KM = 0.35      # Bahnhof → nächster Gleisknoten
SICHER_KM = 0.035   # Betriebspunkt liegt sicher am Weg: Abstand Weg–Gleis (+ Abstand Bahnhofskoordinate–Gleis)
NAH_KM = 0.12       # bis hier nur, wenn der Fahrplan den Punkt mit dem Nachbarpunkt verbindet
                    # (Frutigen am Basistunnel ja, Roggwil-Wynau neben der Neubaustrecke nein)
UMWEG = 1.6         # Weg höchstens so lang wie Luftlinie × UMWEG + 3 km


def _speed(tags):
    ms = tags.get("maxspeed", "")
    try:
        v = float(ms.split()[0].split(";")[0])
        if "mph" in ms:
            v *= 1.609
        if v >= 20:
            return v
    except (ValueError, IndexError):
        pass
    svc = tags.get("service")
    if svc in ("yard", "siding", "spur"):
        return 25.0
    if svc == "crossover":
        return 40.0
    if tags.get("railway") == "narrow_gauge":
        return 55.0
    return {"main": 110.0, "branch": 80.0}.get(tags.get("usage"), 50.0)


def _km(a, b):
    kx = 111.32 * math.cos(math.radians((a[0] + b[0]) / 2))
    return math.hypot((a[1] - b[1]) * kx, (a[0] - b[0]) * 111.32)


def _seg(p, a, b):
    """Abstand Punkt–Strecke in km und Lage 0..1 auf der Strecke."""
    kx = 111.32 * math.cos(math.radians(p[0]))
    ax, ay = (a[1] - p[1]) * kx, (a[0] - p[0]) * 111.32
    bx, by = (b[1] - p[1]) * kx, (b[0] - p[0]) * 111.32
    dx, dy = bx - ax, by - ay
    L = dx * dx + dy * dy
    t = max(0.0, min(1.0, -(ax * dx + ay * dy) / L)) if L else 0.0
    return math.hypot(ax + t * dx, ay + t * dy), t


def _spuren(tags):
    """Spurweiten-Netz(e) eines Gleises: «N» Normalspur, «S» Schmalspur (Meterspur u. a.)."""
    if tags.get("railway") == "narrow_gauge":
        return ("S",)
    g = [x.strip() for x in tags.get("gauge", "1435").split(";")]
    out = tuple(sorted({"N" if x in ("1435", "1453") else "S" for x in g if x}))
    return out or ("N",)


def lade(path):
    return json.load(gzip.open(path, "rt", encoding="utf-8"))


class Netz:
    """Gleisgraph eines Spurweiten-Netzes («N» oder «S») aus dem OSM-Extrakt (lade())."""

    def __init__(self, d, art="N"):
        self.pos = {}
        adj = defaultdict(dict)
        for e in d["elements"]:
            if e.get("type") != "way":
                continue
            t = e.get("tags", {})
            if t.get("railway") not in ("rail", "narrow_gauge") or not e.get("geometry"):
                continue
            if art not in _spuren(t):
                continue
            v = _speed(t)
            ns, gs = e["nodes"], e["geometry"]
            for i, n in enumerate(ns):
                if gs[i]:
                    self.pos[n] = (gs[i]["lat"], gs[i]["lon"])
            for a, b in zip(ns, ns[1:]):
                if a not in self.pos or b not in self.pos:
                    continue
                L = _km(self.pos[a], self.pos[b])
                w = L / v * 60
                if w < adj[a].get(b, (1e9,))[0]:
                    adj[a][b] = (w, L)
                    adj[b][a] = (w, L)
        self.adj = adj
        # Gitter für die Suche nach Knoten
        self.grid = defaultdict(list)
        for n, p in self.pos.items():
            if n in adj:
                self.grid[(int(p[0] * 100), int(p[1] * 100))].append(n)

    def naechster(self, lat, lon, maxkm=FANG_KM):
        best, bd = None, maxkm
        gi, gj = int(lat * 100), int(lon * 100)
        for i in (gi - 1, gi, gi + 1):
            for j in (gj - 1, gj, gj + 1):
                for n in self.grid.get((i, j), ()):
                    dd = _km((lat, lon), self.pos[n])
                    if dd < bd:
                        best, bd = n, dd
        return best

    def weg(self, a, b, maxkm):
        """Schnellster Weg a→b (Knotenliste) innerhalb einer Ellipse; None wenn keiner."""
        pb = self.pos[b]
        pa = self.pos[a]
        dist, prev, pq = {a: 0.0}, {}, [(0.0, a)]
        while pq:
            du, x = heapq.heappop(pq)
            if x == b:
                break
            if du > dist[x]:
                continue
            for y, (w, _) in self.adj[x].items():
                py = self.pos[y]
                if _km(pa, py) + _km(py, pb) > maxkm:
                    continue
                nd = du + w
                if nd < dist.get(y, 1e18):
                    dist[y], prev[y] = nd, x
                    heapq.heappush(pq, (nd, y))
        if b not in dist:
            return None
        p = [b]
        while p[-1] != a:
            p.append(prev[p[-1]])
        return p[::-1]


def wege(S, paare, N, kandidaten, kanten=frozenset()):
    """S: Stationen [[uic, name, lat, lon, abk], …]; paare: Iterable (u, v) mit u < v; N: Netz;
    kandidaten: Stationsindizes, die als Zwischenpunkt in Frage kommen (keine virtuellen Punkte);
    kanten: Paare (u < v), die im Fahrplan direkt aufeinander folgen.
    Gibt {(u, v): ([Zwischenpunkte], [Zeitanteile])} für Paare mit mindestens einem Zwischenpunkt
    und set() der Paare, die im Netz gefunden wurden (auch ohne Zwischenpunkt) zurück."""
    knoten = {}
    for s in set(kandidaten) | {x for p in paare for x in p}:
        if S[s][2] is not None:
            n = N.naechster(S[s][2], S[s][3])
            if n is not None:
                knoten[s] = n
    # Abstand Bahnhofskoordinate–Gleis (wird zur Toleranz «liegt am Weg» addiert)
    versatz = {s: _km((S[s][2], S[s][3]), N.pos[n]) for s, n in knoten.items()}
    # Kandidaten im Gitter (für «liegt am Weg»)
    kg = defaultdict(list)
    for s in kandidaten:
        if s in knoten:
            kg[(int(S[s][2] * 100), int(S[s][3] * 100))].append(s)
    out, gefunden = {}, set()
    for u, v in paare:
        if u not in knoten or v not in knoten:
            continue
        luft = _km((S[u][2], S[u][3]), (S[v][2], S[v][3]))
        p = N.weg(knoten[u], knoten[v], luft * UMWEG + 3)
        if not p:
            continue
        gefunden.add((u, v))
        # Zeit entlang des Wegs; Stützpunkte alle ~0,3 km für die Suche nach Betriebspunkten
        cum = [0.0]
        for x, y in zip(p, p[1:]):
            cum.append(cum[-1] + N.adj[x][y][0])
        tot = cum[-1] or 1
        P = [N.pos[n] for n in p]
        treffer = {}
        for k in range(len(P) - 1):
            a, b = P[k], P[k + 1]
            L = _km(a, b)
            m = max(1, int(L / 0.3) + 1)
            cells = {(int((a[0] + (b[0] - a[0]) * i / m) * 100), int((a[1] + (b[1] - a[1]) * i / m) * 100)) for i in range(m + 1)}
            seen = set()
            for gi, gj in cells:
                for i in (gi - 1, gi, gi + 1):
                    for j in (gj - 1, gj, gj + 1):
                        for s in kg.get((i, j), ()):
                            if s in (u, v) or s in seen:
                                continue
                            seen.add(s)
                            q = (S[s][2], S[s][3])
                            dd, f = _seg(q, a, b)
                            dd -= versatz[s]
                            if dd <= NAH_KM and (s not in treffer or dd < treffer[s][0]):
                                treffer[s] = (dd, cum[k] + (cum[k + 1] - cum[k]) * f)
        if not treffer:
            continue
        inner = sorted(treffer, key=lambda s: treffer[s][1])
        # unsichere Punkte nur mit Fahrplanverbindung zum vorigen oder nächsten Punkt
        kante = lambda x, y: (min(x, y), max(x, y)) in kanten
        kette = [u] + inner + [v]
        inner = [s for k, s in enumerate(inner, 1)
                 if treffer[s][0] <= SICHER_KM or kante(kette[k - 1], s) or kante(s, kette[k + 1])]
        if not inner:
            continue
        ant = [round(treffer[s][1] / tot, 3) for s in inner]
        out[(u, v)] = (inner, ant)
    return out, gefunden
