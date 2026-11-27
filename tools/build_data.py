"""Jahresdaten für die Web-App bauen.

  python tools/build_data.py --nge <pfad NGE-fahrplan> --roh <ordner> --out web/data

Liest das Ergebnis von NGE-fahrplan/tools/fahrplandaten.py:
  <roh>/stations.csv                 Bahnhöfe (UIC, Kürzel, Name, Koordinaten)
  <roh>/roh/trips_alle_tage.json.gz  alle Bahnfahrten des Fahrplanjahres mit Bitfeld-Nummer
  <roh>/roh/*hrdf*.zip               HRDF (für BITFELD und ECKDATEN)

Schreibt:
  <out>/fahrplan.json.gz   kompakte Jahresdaten (siehe README, Abschnitt Datenformat)
  <out>/stand.json         Erzeugungszeit, Quelle, Grössen, Plausibilitätszahlen
"""
import argparse
import csv
import datetime as dt
import gzip
import json
import os
import sys
from collections import Counter
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("--nge", required=True)
ap.add_argument("--roh", required=True)
ap.add_argument("--out", required=True)
a = ap.parse_args()

sys.path.insert(0, a.nge)
from nge_fahrplan import hrdf  # noqa: E402

roh = Path(a.roh)
out = Path(a.out)
out.mkdir(parents=True, exist_ok=True)

hrdf_zip = next(iter(sorted((roh / "roh").glob("*hrdf*.zip"))))
alle = roh / "roh" / "trips_alle_tage.json.gz"
h = hrdf.HRDF(hrdf_zip)
d = hrdf.load_trips(alle)

# Bit-Verschiebung wie in NGE-fahrplan bestimmen (Sonntage müssen am schwächsten sein)
ref = h.start + (h.end - h.start) / 2
ref = ref - dt.timedelta(days=ref.weekday()) + dt.timedelta(days=1)   # Dienstag in der Mitte
offset, protokoll = hrdf.calibrate_offset(h, d, ref)

# Bahnhöfe
stations = {}
with open(roh / "stations.csv", encoding="utf-8") as f:
    for r in csv.DictReader(f):
        stations[int(r["number"])] = r

used = []
idx = {}


def sidx(num):
    if num not in idx:
        r = stations.get(num, {})
        lat = round(float(r["lat"]), 5) if r.get("lat") else None
        lon = round(float(r["lon"]), 5) if r.get("lon") else None
        idx[num] = len(used)
        used.append([num, r.get("name") or str(num), lat, lon, r.get("abbr") or ""])
    return idx[num]


bf_used = {}
trips = []
for t in d["trips"]:
    stops = []
    for s in t["stops"]:
        stops += [sidx(s["num"]), s["arr"], s["dep"], 1 if s.get("pass") else 0]
    bf = t.get("bitfield")
    bfid = ""
    if bf and int(bf) != 0:
        hexs = h.bitfields.get(bf)
        if hexs is not None:
            bf_used[bf] = hexs.rstrip("0") or "0"
            bfid = bf
    trips.append([t["fnr"], t.get("admin", ""), t["cat"], t.get("line", ""), bfid, stops])

meta = {
    "start": str(h.start), "end": str(h.end), "offset": offset, "hrdf": hrdf_zip.name,
    "erzeugt": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    "lauf": f"{os.environ.get('GITHUB_SERVER_URL', '')}/{os.environ.get('GITHUB_REPOSITORY', '')}"
            f"/actions/runs/{os.environ.get('GITHUB_RUN_ID', '')}",
}
# Wege für Züge ohne Zwischenpunkte (vermutete Durchfahrten, siehe tools/durchfahrt.py)
sys.path.insert(0, str(Path(__file__).resolve().parent))
import durchfahrt  # noqa: E402
dw = durchfahrt.tabelle(used, trips)
data = {"meta": meta, "st": used, "bf": bf_used, "tr": trips, "dw": dw}
target = out / "fahrplan.json.gz"
with gzip.open(target, "wt", encoding="utf-8", compresslevel=9) as f:
    json.dump(data, f, ensure_ascii=False, separators=(",", ":"))


def runs(bfid, day):
    if not bfid:
        return True
    hexs = bf_used[bfid]
    i = (day - h.start).days + offset
    if i < 0 or i >= len(hexs) * 4:
        return False
    return bool(int(hexs[i // 4], 16) & (8 >> (i % 4)))


mon = ref - dt.timedelta(days=ref.weekday())
stand = dict(meta, fahrten=len(trips), bahnhoefe=len(used), bitfelder=len(bf_used), durchfahrtswege=len(dw),
             groesse_mb=round(target.stat().st_size / 1e6, 2),
             nach_gattung=dict(Counter(t[2] for t in trips).most_common(25)),
             fahrten_je_tag={str(mon + dt.timedelta(k)): sum(1 for t in trips if runs(t[4], mon + dt.timedelta(k)))
                             for k in range(7)},
             offset_protokoll=protokoll)
(out / "stand.json").write_text(json.dumps(stand, ensure_ascii=False, indent=1), encoding="utf-8")
print(json.dumps({k: v for k, v in stand.items() if k != "offset_protokoll"}, ensure_ascii=False, indent=1))
