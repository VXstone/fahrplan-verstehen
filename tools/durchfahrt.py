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

Mit --netz (schweiz_bahn.json.gz aus VXstone/topo-daten) gilt statt 2./3. der schnellste Weg im Gleisnetz
(topo_wege.py, Normal- und Schmalspur getrennt); der Fahrplangraph bleibt für Paare ausserhalb des Netzes.
build_data.py legt nur die Wegtabellen in fahrplan.json.gz (tabelle()); die Seite fügt die Punkte beim Laden ein,
so bleibt die Datei klein. ergaenzen() macht dasselbe in Python (zum Prüfen).
Arbeitet auf dem kompakten Format von fahrplan.json.gz (st, tr). Lokal prüfen:
  python tools/durchfahrt.py web/data/fahrplan.json.gz [--netz schweiz_bahn.json.gz] [--out neu.json.gz] [--zeige "Bern" "Thun"]
"""
import argparse
import gzip
import heapq
import json
import math
import re
from collections import Counter, defaultdict

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


def paare(S, trips):
    """Alle Punktpaare (u < v) aufeinanderfolgender Punkte, Luftlinie ≥ MIN_KM."""
    out = set()
    for t in trips:
        f = t[5]
        for i in range(0, len(f) - 4, 4):
            u, v = f[i], f[i + 4]
            if u != v:
                d = _hav(S, u, v)
                if d is not None and d >= MIN_KM:
                    out.add((min(u, v), max(u, v)))
    return out


FERNVERKEHR = re.compile(r"^(IC|ICN|ICE|IR|IRE|EC|EN|NJ|RJ|RJX|TGV|EXT|PE)$")


def fernverkehr(gattung):
    """Gattung des Fernverkehrs (dieselbe Regel steht in web/app.js)."""
    return bool(FERNVERKEHR.match(gattung or ""))


def gesamt(S, trips, netz=None, log=print):
    """Wege für alle Paare, getrennt nach Spurweite: {"N": {…}, "S": {…}, "F": {…}} mit (u, v) → (inner, ant), u < v.
    N/S: im Gleisnetz von topo-daten (netz = Pfad zu schweiz_bahn.json.gz), Normal- bzw. Schmalspur;
    F: Paare, die in keinem der beiden Netze liegen (Ausland, ohne Koordinaten), aus dem Fahrplangraph (wege()).
    «nur»: Betriebspunkte nur am Normal- bzw. nur am Schmalspurnetz. Dazu die Menge der Schmalspur-Fahrten (Index in trips)."""
    fp = {(u, v): w for (u, v), w in wege(S, trips).items() if u < v}
    if not netz:
        return {"N": {}, "S": {}, "X": {}, "F": fp}, set()
    import os
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import topo_wege
    roh = topo_wege.lade(netz)
    P = paare(S, trips)
    # Zwischenpunkte: Betriebspunkte in der Schweiz; virtuelle Punkte (Bahn-2000-Strecke, Basistunnel …)
    # liegen nur ungefähr auf der Strecke und bleiben weg
    kand = {s for t in trips for s in t[5][0::4] if S[s][2] is not None and str(S[s][0])[:2] == "85"}
    kanten = {(min(f[i], f[i + 4]), max(f[i], f[i + 4])) for t in trips for f in (t[5],) for i in range(0, len(f) - 4, 4)}
    netze = {art: topo_wege.Netz(roh, art) for art in ("N", "S")}
    del roh
    # Netz je Betriebspunkt vorläufig nach Lage: das nähere (beide, wenn ähnlich nah)
    ab = {}
    for s in kand:
        for art, N in netze.items():
            n = N.naechster(S[s][2], S[s][3])
            ab[(s, art)] = topo_wege._km((S[s][2], S[s][3]), N.pos[n]) if n is not None else None
    zu = {"N": set(), "S": set()}
    for s in kand:
        dn, ds = ab[(s, "N")], ab[(s, "S")]
        if dn is not None and (ds is None or dn <= ds + 0.005):
            zu["N"].add(s)
        if ds is not None and (dn is None or ds <= dn + 0.005):
            zu["S"].add(s)
    # Spurweite je Fahrt: welche ihrer Abschnitte liegen nur im Normal-, welche nur im Schmalspurnetz?
    # (AsM Langenthal–St. Urban neben der Neubaustrecke: nach Lage nicht zu trennen, nach Abschnitten schon)
    g0 = {art: topo_wege.wege(S, P, N, (), kanten)[1] for art, N in netze.items()}
    schmal = set()
    for i, t in enumerate(trips):
        f = t[5]
        ks = [(min(f[j], f[j + 4]), max(f[j], f[j + 4])) for j in range(0, len(f) - 4, 4)]
        n = sum(1 for k in ks if k in g0["N"] and k not in g0["S"])
        m = sum(1 for k in ks if k in g0["S"] and k not in g0["N"])
        if m == n:   # unentschieden: nach Lage der Punkte
            st = f[0::4]
            n = sum(1 for s in st if s in zu["N"] and s not in zu["S"])
            m = sum(1 for s in st if s in zu["S"] and s not in zu["N"])
        if m > n:
            schmal.add(i)
    # Netz je Betriebspunkt endgültig: die Fahrten, die ihn führen (Chur: beide; Chur Wiesental, Untervaz-Trimmis: RhB)
    zu = {"N": set(), "S": set()}
    for i, t in enumerate(trips):
        art = "S" if i in schmal else "N"
        zu[art].update(s for s in t[5][0::4] if ab.get((s, art)) is not None)
    out, gefunden = {}, set()
    for art, N in netze.items():
        W, g = topo_wege.wege(S, P, N, zu[art], kanten)
        log(f"Gleisnetz {art}: {len(P)} Paare, {len(g)} im Netz gefunden, {len(W)} mit Zwischenpunkten")
        # im Netz gefunden ohne Zwischenpunkte: leerer Eintrag – die Seite weiss dann, dass der Zug zwischen
        # den beiden Punkten an keinem anderen Betriebspunkt vorbeifährt (Rothrist–Olten durch den Born)
        for k in g:
            W.setdefault(k, ([], []))
        out[art] = W
        gefunden |= g
    # Fernverkehr (Normalspur): Bahnhöfe, die kein Fernverkehrszug führt, kosten einen Zuschlag – ein IC ohne Halt
    # Zürich HB–Winterthur fährt über Oerlikon, nicht über Stadelhofen–Stettbach (dort halten alle).
    # Nur die Paare, deren Weg sich dadurch ändert, kommen in die Tabelle «F».
    # «führt Fernverkehr» = mindestens 10 Fahrten (ohne Extrazüge EXT, die fast überall einmal vorbeikommen)
    fvz = Counter(s for i, t in enumerate(trips) if i not in schmal and fernverkehr(t[2]) and t[2] != "EXT"
                  for s in set(t[5][0::4]))
    fv = {s for s, n in fvz.items() if n >= 10}
    PF = {k for i, t in enumerate(trips) if i not in schmal and fernverkehr(t[2])
          for f in (t[5],) for j in range(0, len(f) - 4, 4) for k in [(min(f[j], f[j + 4]), max(f[j], f[j + 4]))] if k in P}
    WF, gF = topo_wege.wege(S, PF, netze["N"], zu["N"], kanten, strafe_bf=zu["N"] - fv)
    for k in gF:
        WF.setdefault(k, ([], []))
    out["X"] = {k: w for k, w in WF.items() if out["N"].get(k, ([], []))[0] != w[0]}
    log(f"Fernverkehr: {len(PF)} Paare, {len(out['X'])} mit anderem Weg")
    out["F"] = {k: w for k, w in fp.items() if k not in gefunden}
    log(f"Schmalspur-Fahrten: {len(schmal)}, Fahrplangraph für {len(out['F'])} Paare")
    out["nur"] = {"N": sorted(zu["N"] - zu["S"]), "S": sorted(zu["S"] - zu["N"])}
    return out, schmal


def _liste(W):
    return [[u, v, inner, [round(a, 3) for a in ant]] for (u, v), (inner, ant) in sorted(W.items())]


def tabelle(S, trips, netz=None, log=print):
    """Wegtabellen für fahrplan.json.gz: {"dw": […], "dws": […], "dwf": […], "schmal": [Fahrtindex, …]}.
    Einträge [u, v, [Zwischenpunkte], [Anteile]] nur in einer Richtung (u < v), im Netz auch ohne Zwischenpunkte
    (dann ist der Abschnitt «geprüft»: kein weiterer Betriebspunkt am Weg). «dw» Normalspur-, «dws» Schmalspurnetz,
    «dwf» Fahrplangraph für Paare ausserhalb beider Netze. Die Seite nimmt für eine Fahrt dw bzw. (Schmalspur) dws,
    sonst dwf, und fügt die Punkte beim Laden ein (beide Richtungen)."""
    W, schmal = gesamt(S, trips, netz, log)
    nur = W.pop("nur", {})
    return {"dw": _liste(W["N"]), "dws": _liste(W["S"]), "dwx": _liste(W["X"]), "dwf": _liste(W["F"]), "schmal": sorted(schmal),
            "nur_schmal": nur.get("S", []), "nur_normal": nur.get("N", [])}


def ergaenzen(S, trips, W, schmal=frozenset()):
    """Fügt vermutete Durchfahrten aus W (gesamt()) in trips ein (an Ort).
    Gibt (Fahrten geändert, Punkte eingefügt) zurück."""
    WW = {}
    for art, w in W.items():
        if art == "X":
            w = {**W["F"], **W["N"], **w}
        elif art != "F":
            w = {**W["F"], **w}
        d = dict(w)
        d.update({(v, u): (inner[::-1], [1 - a for a in ant[::-1]]) for (u, v), (inner, ant) in w.items()})
        WW[art] = d
    n_t = n_p = 0
    for ti, t in enumerate(trips):
        Wt = WW["S" if ti in schmal else "X" if fernverkehr(t[2]) else "N"]
        f = t[5]
        neu, geaendert = f[:4], False
        for i in range(0, len(f) - 4, 4):
            u, v = f[i], f[i + 4]
            w = Wt.get((u, v))
            if w and w[0]:
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
    ap.add_argument("--netz", help="schweiz_bahn.json.gz aus VXstone/topo-daten (Release daten)")
    ap.add_argument("--zeige", nargs=2, action="append", default=[], metavar=("VON", "NACH"))
    a = ap.parse_args()
    d = json.load(gzip.open(a.fahrplan, "rt", encoding="utf-8"))
    S = d["st"]
    W, schmal = gesamt(S, d["tr"], a.netz)
    nur = W.pop("nur", {})
    idx = {s[1]: i for i, s in enumerate(S)}
    for von, nach in a.zeige:
        u, v = idx.get(von), idx.get(nach)
        if u is None or v is None:
            print("?", von, nach)
            continue
        for art in W:
            w = W[art].get((min(u, v), max(u, v)))
            if not w:
                continue
            inner = w[0] if u < v else w[0][::-1]
            print(art, von, "→", nach, ":", " – ".join(S[x][1] for x in inner))
    if a.out:   # Originalfahrten + Wegtabellen, wie build_data.py sie schreibt
        d.update({"dw": _liste(W["N"]), "dws": _liste(W["S"]), "dwx": _liste(W["X"]), "dwf": _liste(W["F"]), "schmal": sorted(schmal),
                  "nur_schmal": nur.get("S", []), "nur_normal": nur.get("N", [])})
        with gzip.open(a.out, "wt", encoding="utf-8", compresslevel=9) as fh:
            json.dump(d, fh, ensure_ascii=False, separators=(",", ":"))
    print("Fahrten geändert, Punkte eingefügt:", ergaenzen(S, d["tr"], W, schmal))
