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


def merge(g, stat):
    """Punkte der Stücke einer Gruppe zu einem Lauf vereinigen. Wo sich Fahrplanfelder überlappen,
    steht derselbe Betriebspunkt in mehreren Stücken (Schritt F):
      gleiche Zeit (±2,5′)          → ein Punkt
      Feldwechsel mit Halt          → Stück A endet mit der Ankunft, Stück B beginnt mit der Abfahrt
                                      (Lücke ≤ 60′) → ein Punkt mit An/Ab
      Widerspruch zwischen Feldern  → Punkt des Felds mit den meisten übereinstimmenden Feldern,
                                      bei Gleichstand des Stücks, das den Überlappungsbereich weiter
                                      innen hat (am Feldrand sind Linien oft abgeschnitten/falsch zugeordnet)
    Doppelte Punkte innerhalb eines Felds (echtes Wiederkehren, gleiche Nummer mit anderer Lage) bleiben."""
    obs = []
    for n, pc in enumerate(g):
        L = len(pc["pts"])
        for i, (s, an, ab) in enumerate(pc["pts"]):
            obs.append(dict(s=s, an=an, ab=ab, fe=pc["feld"], pc=n, rand=min(i, L - 1 - i), L=L,
                            erst=i == 0, letzt=i == L - 1))
    # je Betriebspunkt nach Zeit gruppieren
    halts = defaultdict(list)
    for o in sorted(obs, key=lambda o: o["an"]):
        hl = halts[o["s"]]
        h = next((h for h in hl if any(cd(o["an"], x["an"]) < 2.5 for x in h)), None)
        (h.append(o) if h is not None else hl.append([o]))
    # Feldwechsel mit Halt: Ankunft (Stückende) + Abfahrt (Stückanfang) zusammenlegen
    for s, hl in halts.items():
        changed = True
        while changed and len(hl) > 1:
            changed = False
            for h1 in hl:
                for h2 in hl:
                    if h1 is h2 or {x["pc"] for x in h1} & {x["pc"] for x in h2}:
                        continue
                    gap = (min(x["an"] for x in h2) - max(x["ab"] for x in h1)) % 1440
                    if (any(x["letzt"] for x in h1) and any(x["erst"] for x in h2)
                            and not any(x["erst"] for x in h1) and not any(x["letzt"] for x in h2)
                            and 0 < gap <= 60):
                        for x in h2:
                            x["ist_ab"] = True
                        h1 += h2
                        hl.remove(h2)
                        stat["feldwechsel"] += 1
                        changed = True
                        break
                if changed:
                    break
    # Widersprüche zwischen Feldern
    konf = {s: hl for s, hl in halts.items() if len(hl) > 1}
    tiefe = defaultdict(int)  # je Stück: wie weit innen liegen seine Punkte im Überlappungsbereich
    for hl in halts.values():
        if len({x["fe"] for h in hl for x in h}) > 1:
            for h in hl:
                for x in h:
                    tiefe[x["pc"]] += x["rand"]
    for s, hl in konf.items():
        fs = [{x["fe"] for x in h} for h in hl]
        sc = lambda k: (len(fs[k]), max(tiefe[x["pc"]] for x in hl[k]), max(x["L"] for x in hl[k]))  # noqa: E731
        keep = []
        for i, h in enumerate(hl):
            # nur gegen Gruppen aus anderen Feldern antreten; gleiches Feld → beide behalten
            rivalen = [j for j in range(len(hl)) if j != i and not fs[i] & fs[j]]
            if all(sc(i) > sc(j) or (sc(i) == sc(j) and i < j) for j in rivalen):
                keep.append(h)
            else:
                stat["verworfen_punkte"] += 1
        halts[s] = keep
    pts = []
    for s, hl in halts.items():
        for h in hl:
            # Ankunft nicht von Stückanfängen, Abfahrt nicht von Stückenden (am Feldrand oft abgeschnitten)
            ans = [x for x in h if not x["erst"] and not x.get("ist_ab")] or h
            abs_ = [x for x in h if not x["letzt"]] or h
            pts.append((s, waehle(ans, "an", tiefe, stat), waehle(abs_, "ab", tiefe, stat)))
    return pts


def waehle(xs, k, tiefe, stat):
    """Zeit k aus mehreren Beobachtungen: stimmen sie (±2,5′) überein, die früheste Ankunft bzw. späteste
    Abfahrt; sonst die Zeit, die die meisten Felder zeigen, bei Gleichstand die des Stücks, das weiter innen liegt."""
    ts = [x[k] for x in xs]
    if all(cd(t, ts[0]) <= 2.5 for t in ts):
        return min(ts, key=lambda t: (t - ts[0] + 720) % 1440) if k == "an" else max(ts, key=lambda t: (t - ts[0] + 720) % 1440)
    stat[f"widerspruch_{k}"] += 1
    best = max(xs, key=lambda x: (len({y["fe"] for y in xs if cd(y[k], x[k]) <= 2.5}), tiefe[x["pc"]], x["L"]))
    return best[k]


tr = []
mstat = defaultdict(int)
for (kat, zug), pieces in P.items():
    good = [pc for pc in pieces if plausibel(kat, zug, pc["pts"])]
    verworfen[kat] += len(pieces) - len(good)
    for g in join_clusters(cluster(good)):
        pts = merge(g, mstat)
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
            verworfen=dict(verworfen), ueberlappung=dict(mstat), fehlende_kuerzel=dict(sorted(fehlend.items(), key=lambda x: -x[1])[:40]))
with gzip.open(f"{a.out}/publikation.json.gz", "wt", encoding="utf-8", compresslevel=9) as f:
    json.dump(dict(meta=meta, st_add=st_add, tr=tr), f, ensure_ascii=False, separators=(",", ":"))
print(json.dumps(meta, ensure_ascii=False, indent=1))
