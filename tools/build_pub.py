"""Publizierten Fahrplan (grafische Fahrpläne SBB) für die Seite aufbereiten.

  python tools/build_pub.py --zuege grafapla_2026_zuege.json.gz --fahrplan web/data/fahrplan.json.gz \
                            --stations stations.csv --out web/data

Eingaben
  grafapla_<Jahr>_zuege.json.gz  aus VXstone/NGE-fahrplan (Release grafapla-<Jahr>): je Fahrplanfeld und
                                 Kategorie (R Reise, G Güter, L Lok/Leer) die Züge mit VP und Betriebspunkten
  fahrplan.json.gz               Jahresdaten der Seite (für die Stationsliste)
  stations.csv                   Stationen/Betriebspunkte (NGE-fahrplan, Release fahrplandaten) für Punkte,
                                 die in der HRDF fehlen (Abzweigungen, Güterbahnhöfe)

Ausgabe  <out>/publikation.json.gz
  { "meta": {quelle, felder, erzeugt},
    "st_add": [[uic, name, lat, lon, kürzel], …],     // wird an "st" der Jahresdaten angehängt
    "tr": [[zugnr, kat, felder, vp, [station, an, ab, durchfahrt, …]], …] }
  Zeiten in Minuten ab Mitternacht des Referenztags (Folgetag > 1440), auf 0,1 min.
  vp: Verkehrsperiode(n) wie im grafischen Fahrplan (z. B. "15", "+269*", mehrere mit «|»), Auswertung im Browser.
"""
import argparse
import csv
import datetime as dt
import gzip
import json
from collections import defaultdict

ap = argparse.ArgumentParser()
ap.add_argument("--zuege", required=True)
ap.add_argument("--fahrplan", required=True)
ap.add_argument("--stations", required=True)
ap.add_argument("--out", required=True)
a = ap.parse_args()

pub = json.load(gzip.open(a.zuege, "rt", encoding="utf-8"))
fp = json.load(gzip.open(a.fahrplan, "rt", encoding="utf-8"))
idx = {}
for i, s in enumerate(fp["st"]):
    if s[4]:
        idx.setdefault(s[4], i)
csvst = {}
for r in csv.DictReader(open(a.stations, encoding="utf-8")):
    if r["abbr"] and r["abbr"] not in csvst:
        try:
            csvst[r["abbr"]] = (int(r["number"]), r["name"], float(r["lat"]), float(r["lon"]))
        except ValueError:
            pass
st_add, fehlend = [], defaultdict(int)


def sidx(abbr):
    if abbr in idx:
        return idx[abbr]
    if abbr not in csvst:
        fehlend[abbr] += 1
        return None
    uic, name, lat, lon = csvst[abbr]
    idx[abbr] = len(fp["st"]) + len(st_add)
    st_add.append([uic, name, lat, lon, abbr])
    return idx[abbr]


# HRDF-Zeiten je Zugnummer (für die Plausibilisierung der Reisezüge)
H = defaultdict(list)
HL = defaultdict(list)
for fnr, adm, cat, line, bf, flat in fp["tr"]:
    n = fnr.split("+")[0].lstrip("0")
    nz = lambda a, b: (a if a is not None else b) % 1440  # noqa: E731
    H[n].append({fp["st"][flat[k]][4]: (nz(flat[k + 1], flat[k + 2]), nz(flat[k + 2], flat[k + 1]))
                 for k in range(0, len(flat), 4) if fp["st"][flat[k]][4] and (flat[k + 1] is not None or flat[k + 2] is not None)})
    HL[n].append((H[n][-1], [(fp["st"][flat[k]][2], fp["st"][flat[k]][3]) for k in range(0, len(flat), 4)
                              if fp["st"][flat[k]][2] is not None]))


HST = {s[4] for s in fp["st"] if s[4]}


def cd(x, y):
    d = abs(x - y) % 1440
    return min(d, 1440 - d)


# Stücke je Fahrplanfeld sammeln, nur anschliessende Stücke gleicher Nummer verbinden
P = defaultdict(list)
for f in pub["felder"]:
    for kat, blk in f.get("kat", {}).items():
        for z in blk["zuege"]:
            P[(kat, z["zug"])].append(dict(feld=f["feld"], vps=z.get("vps") or {z["vp"]: 1},
                                           pts=[(s, an % 1440, ab % 1440) for s, an, ab in z["halte"]]))
verworfen = defaultdict(int)


import math

POS = {}
for s_ in fp["st"]:
    if s_[4] and s_[2] is not None:
        POS.setdefault(s_[4], (s_[2], s_[3]))
for k_, v_ in csvst.items():
    POS.setdefault(k_, (v_[2], v_[3]))


def seg_dist(p, a, b):
    """Abstand Punkt–Strecke in km (lokal eben)."""
    kx = 111.3 * math.cos(math.radians(p[0]))
    ax, ay = (a[1] - p[1]) * kx, (a[0] - p[0]) * 111.3
    bx, by = (b[1] - p[1]) * kx, (b[0] - p[0]) * 111.3
    dx, dy = bx - ax, by - ay
    L = dx * dx + dy * dy
    t = 0 if L == 0 else max(0, min(1, -(ax * dx + ay * dy) / L))
    return math.hypot(ax + t * dx, ay + t * dy)


def plausibel(kat, zug, pts):
    """Reisezug-Stück gegen die HRDF derselben Nummer prüfen: die Punkte des Stücks müssen am Laufweg
    einer HRDF-Fahrt dieser Nummer liegen (≤ 1,5 km, 80 %), und gemeinsame Bahnhöfe müssen zeitlich
    stimmen (±3 min, 60 %). Nummern ohne HRDF-Fahrt und Stücke ohne Koordinaten bleiben ungeprüft."""
    if kat != "R":
        return True
    hs = HL.get(zug.lstrip("0"))
    pp = [(s, an, ab) for s, an, ab in pts if s in POS]
    if not hs or not pp:
        return True
    for h, line in hs:
        if len(line) < 2:
            continue
        near = sum(1 for s, _, _ in pp if min(seg_dist(POS[s], line[i], line[i + 1]) for i in range(len(line) - 1)) <= 1.5)
        if near / len(pp) < 0.8:
            continue
        com = [(s, an, ab) for s, an, ab in pts if s in h]
        if not com or sum(1 for s, an, ab in com if min(cd(an, h[s][0]), cd(ab, h[s][1])) <= 3) / len(com) >= 0.6:
            return True
    return False


def cluster(pieces):
    groups = []
    for pc in pieces:
        hit = [g for g in groups if any(a == b and cd(ta, tb) <= 3 for a, ta, _ in pc["pts"] for gp in g for b, tb, _ in gp["pts"])]
        if not hit:
            groups.append([pc])
        else:
            hit[0].append(pc)
            for g in hit[1:]:
                hit[0] += g
                groups.remove(g)
    return groups


def join_clusters(groups):
    """Teilstücke derselben Nummer verbinden, wenn sie zeitlich aneinander passen (Feldwechsel mit
    anderem Kürzel am Übergang): Lücke ≤ 60 min, keine Station mit widersprüchlicher Zeit."""
    def span(g):
        ts = unwrap([x for pc in g for x in pc["pts"]])
        return ts[0][1], ts[-1][2], {s: an for s, an, _ in ts}
    changed = True
    while changed and len(groups) > 1:
        changed = False
        for i in range(len(groups)):
            for j in range(len(groups)):
                if i == j:
                    continue
                a0, a1, sa = span(groups[i])
                b0, b1, sb = span(groups[j])
                gap = (b0 - a1) % 1440
                if gap <= 60 and not any(s in sa and cd(sa[s], t) > 3 for s, t in sb.items()):
                    groups[i] += groups[j]
                    groups.pop(j)
                    changed = True
                    break
            if changed:
                break
    return groups


def unwrap(pts):
    pts = sorted(pts, key=lambda x: x[1])
    gaps = [((pts[(i + 1) % len(pts)][1] - pts[i][1]) % 1440, i) for i in range(len(pts))]
    _, i = max(gaps)
    pts = pts[i + 1:] + pts[:i + 1]
    out, add, last = [], 0, None
    for s, an, ab in pts:
        if last is not None and an + add < last - 1:
            add += 1440
        an2, ab2 = an + add, ab + add
        if ab2 < an2:
            ab2 += 1440
        out.append((s, an2, ab2))
        last = an2
    return out


tr = []
for (kat, zug), pieces in P.items():
    good = [pc for pc in pieces if plausibel(kat, zug, pc["pts"])]
    verworfen[kat] += len(pieces) - len(good)
    for g in join_clusters(cluster(good)):
        pts = []
        for s, an, ab in sorted([x for pc in g for x in pc["pts"]], key=lambda x: x[1]):
            j = next((k for k, q in enumerate(pts) if q[0] == s and cd(an, q[1]) < 2.5), None)
            if j is None:
                pts.append((s, an, ab))
            else:
                q = pts[j]
                pts[j] = (s, q[1] if cd(q[1], an) < 0.01 else min(q[1], an), max(q[2], ab))
        if len(pts) < 2:
            continue
        pts = unwrap(pts)
        vps = defaultdict(int)
        for pc in g:
            for v, n in pc["vps"].items():
                vps[v] += n
        # Teilstücke können verschiedene VP tragen (z. B. 15* und 57*): alle behalten, im Browser vereinigt
        base = sorted({v for v in vps if v and v[0] not in "+-"})
        vp = "|".join(base) if base else "|".join(sorted({v for v in vps if v}))
        flat = []
        for s, an, ab in pts:
            k = sidx(s)
            if k is None:
                continue
            flat += [k, round(an, 1), round(ab, 1), 1 if (kat != "R" and ab - an < 0.5) else 0]
        if len(flat) >= 8:
            tr.append([zug, kat, sorted({pc["feld"] for pc in g}), vp, flat])

meta = dict(quelle=pub.get("quelle", "grafische Fahrpläne SBB"), felder=len(pub["felder"]),
            zuege={k: sum(1 for t in tr if t[1] == k) for k in "RGL"},
            erzeugt=dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            verworfen=dict(verworfen), fehlende_kuerzel=dict(sorted(fehlend.items(), key=lambda x: -x[1])[:40]))
with gzip.open(f"{a.out}/publikation.json.gz", "wt", encoding="utf-8", compresslevel=9) as f:
    json.dump(dict(meta=meta, st_add=st_add, tr=tr), f, ensure_ascii=False, separators=(",", ":"))
print(json.dumps(meta, ensure_ascii=False, indent=1))
