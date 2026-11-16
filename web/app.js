"use strict";
/* Fahrplan verstehen – Bildfahrplan, Kursbuch, Kreuzungen, Knotenlupe, Anschlüsse
   für eine frei gewählte Strecke und ein Datum. Alles im Browser aus data/fahrplan.json.gz. */

// ---------------- Hilfen ----------------
const NS = "http://www.w3.org/2000/svg";
const el = (n, a = {}, p) => { const e = document.createElementNS(NS, n); for (const k in a) e.setAttribute(k, a[k]); if (p) p.appendChild(e); return e; };
const h = (tag, html, cls) => { const e = document.createElement(tag); if (html != null) e.innerHTML = html; if (cls) e.className = cls; return e; };
const $ = id => document.getElementById(id);
const fmt = m => m == null ? "" : String(Math.floor(Math.round(m) / 60) % 24).padStart(2, "0") + ":" + String(Math.round(m) % 60).padStart(2, "0");
const esc = s => String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const WD = ["So", "Mo", "Di", "Mi", "Do", "Fr", "Sa"];
const dateDE = s => { const [y, m, d] = s.split("-"); return `${+d}.${+m}.${y}`; };
const addDays = (s, n) => { const d = new Date(s + "T12:00:00Z"); d.setUTCDate(d.getUTCDate() + n); return d.toISOString().slice(0, 10); };
const dayDiff = (a, b) => Math.round((new Date(a + "T12:00:00Z") - new Date(b + "T12:00:00Z")) / 864e5);
const hav = (a, b) => { if (a.lat == null || b.lat == null) return 0; const R = Math.PI / 180, la1 = a.lat * R, la2 = b.lat * R;
  const x = Math.sin((la2 - la1) / 2) ** 2 + Math.cos(la1) * Math.cos(la2) * Math.sin((b.lon - a.lon) * R / 2) ** 2; return 12742 * Math.asin(Math.sqrt(x)); };
const tim = e => e[1] != null ? e[1] : e[2];
const timD = e => e[2] != null ? e[2] : e[1];

// ---------------- Daten ----------------
let D = null;            // {meta, S:[{uic,name,lat,lon,abbr}], T:[trip], byStation: Map}
async function loadData() {
  let r = await fetch("data/fahrplan.json.gz"), buf;
  if (r.ok) buf = new Uint8Array(await r.arrayBuffer());
  else {   // Ersatz für Hosts, die keine .gz-Dateien ausliefern: gleiche Datei base64-kodiert
    r = await fetch("data/fahrplan.b64.txt");
    if (!r.ok) throw new Error("Fahrplandaten nicht gefunden (" + r.status + ")");
    const b64 = (await r.text()).trim(); const bin = atob(b64); buf = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) buf[i] = bin.charCodeAt(i);
  }
  let text;
  if (buf[0] === 0x1f && buf[1] === 0x8b) {
    const ds = new Blob([buf]).stream().pipeThrough(new DecompressionStream("gzip"));
    text = await new Response(ds).text();
  } else text = new TextDecoder().decode(buf);
  const raw = JSON.parse(text);
  const S = raw.st.map(([uic, name, lat, lon, abbr]) => ({ uic, name, lat, lon, abbr }));
  const T = raw.tr.map(([fnr, admin, cat, line, bf, flat], i) => {
    const st = [], arr = [], dep = [], pass = [];
    for (let k = 0; k < flat.length; k += 4) { st.push(flat[k]); arr.push(flat[k + 1]); dep.push(flat[k + 2]); pass.push(!!flat[k + 3]); }
    return { i, fnr, admin, cat, line, bf, st, arr, dep, pass };
  });
  const byStation = new Map();
  T.forEach(t => new Set(t.st).forEach(s => { if (!byStation.has(s)) byStation.set(s, []); byStation.get(s).push(t.i); }));
  // Bitfelder als Bytes vorbereiten
  const byFnr = new Map();
  T.forEach(t => { const k = t.fnr; if (!byFnr.has(k)) byFnr.set(k, []); byFnr.get(k).push(t); });
  D = { meta: raw.meta, S, T, byStation, byFnr, BF: raw.bf };
}
function runsOn(t, date) {
  if (!t.bf) return true;
  const hexs = D.BF[t.bf]; if (hexs == null) return true;
  const i = dayDiff(date, D.meta.start) + D.meta.offset;
  if (i < 0 || i >= hexs.length * 4) return false;
  return !!(parseInt(hexs[i >> 2], 16) & (8 >> (i & 3)));
}
function series(t) {
  const c = t.cat || "", l = (t.line || "").trim();
  if (!l) return c || "?";
  if (/^\d+$/.test(l)) return c + l;              // IC 1 -> IC1, S 1 -> S1, RE 9 -> RE9
  if (/^\d+[A-Z]$/.test(l)) return c;             // TGV 612E -> TGV
  return l;                                       // P8, R21 …
}
const tLabel = t => `${series(t)} ${String(t.fnr).replace(/^0+/, "").replace(/\+\d+$/, "")}`;

// ---------------- Bahnhofssuche ----------------
let nameIdx = null;
function buildNames() {
  nameIdx = new Map();
  const dl = $("bhf"); const frag = document.createDocumentFragment();
  const served = [...D.byStation.keys()].sort((x, y) => D.S[x].name.localeCompare(D.S[y].name));
  for (const s of served) {
    const S = D.S[s]; nameIdx.set(S.name.toLowerCase(), s); if (S.abbr) nameIdx.set(S.abbr.toLowerCase(), s);
    nameIdx.set(String(S.uic), s);
    const o = document.createElement("option"); o.value = S.name; if (S.abbr) o.label = S.abbr; frag.appendChild(o);
  }
  dl.appendChild(frag);
}
function findStation(q) {
  if (!q) return null; q = q.trim().toLowerCase();
  if (nameIdx.has(q)) return nameIdx.get(q);
  for (const [k, v] of nameIdx) if (k.startsWith(q)) return v;
  return null;
}

// ---------------- Strecke zusammensetzen ----------------
// Liefert {ids:[stationIdx], km:[], variants:[...]} oder null
function pieceTrips(a, b, via) {
  const set = new Set(D.byStation.get(a) || []); const out = [];
  for (const ti of D.byStation.get(b) || []) {
    if (!set.has(ti)) continue;
    const t = D.T[ti]; const ia = t.st.indexOf(a), ib = t.st.indexOf(b);
    if (ia < 0 || ib < 0 || ia === ib) continue;
    let seq = ia < ib ? t.st.slice(ia, ib + 1) : t.st.slice(ib, ia + 1).reverse();
    if (via != null) { const iv = seq.indexOf(via); if (iv <= 0 || iv >= seq.length - 1) continue; }
    out.push(seq);
  }
  return out;
}
function corridorDirect(a, b, via) {
  const seqs = pieceTrips(a, b, via);
  if (!seqs.length) return null;
  // Basis: die Folge, in die die meisten Fahrten passen (geordnete Teilfolge), bei Gleichstand die längere
  const cnt = new Map();
  for (const sq of seqs) { const k = sq.join(","); cnt.set(k, (cnt.get(k) || 0) + 1); }
  const fam = [...cnt.entries()].map(([k, c]) => ({ s: k.split(",").map(Number), c }));
  const isSub = (small, big) => { let j = 0; for (const x of big) if (x === small[j]) j++; return j === small.length; };
  let base = null, bestScore = -1;
  for (const f of fam) { let sc = 0; for (const g of fam) if (g.s.length <= f.s.length && isSub(g.s, f.s)) sc += g.c;
    const score = sc * 1000 + f.s.length; if (score > bestScore) { bestScore = score; base = f.s; } }
  // Weitere Halte einfügen, die zwischen zwei benachbarten Basis-Bahnhöfen liegen
  let ids = base.slice(); const variants = new Map();
  for (const [k, c] of cnt) {
    const s = k.split(",").map(Number);
    let lastPos = 0, pending = [];
    for (let j = 1; j < s.length; j++) {
      const p = ids.indexOf(s[j]);
      if (p < 0) { pending.push(s[j]); continue; }
      if (pending.length) {
        if (p === lastPos + 1) { ids.splice(p, 0, ...pending); lastPos = p + pending.length; }
        else { const key = D.S[pending[0]].name; variants.set(key, (variants.get(key) || 0) + c); lastPos = p; }
        pending = [];
      } else lastPos = p;
    }
  }
  return { ids, variants: [...variants.entries()].sort((x, y) => y[1] - x[1]).slice(0, 4), n: seqs.length };
}
// Zwischenhalte ergänzen: Fahrten, die zwei benachbarte Bahnhöfe der Strecke verbinden und dazwischen halten
function densify(c) {
  const out = [c.ids[0]];
  for (let k = 0; k + 1 < c.ids.length; k++) {
    const u = c.ids[k], v = c.ids[k + 1]; const direct = hav(D.S[u], D.S[v]);
    const setU = new Set(D.byStation.get(u) || []); const cand = new Map();
    for (const ti of D.byStation.get(v) || []) { if (!setU.has(ti)) continue; const t = D.T[ti];
      const iu = t.st.indexOf(u), iv = t.st.indexOf(v); if (iu < 0 || iv < 0 || Math.abs(iu - iv) < 2 || Math.abs(iu - iv) > 25) continue;
      const inner = iu < iv ? t.st.slice(iu + 1, iv) : t.st.slice(iv + 1, iu).reverse();
      if (inner.includes(u) || inner.includes(v) || inner.some(x => c.ids.includes(x))) continue;
      const key = inner.join(","); cand.set(key, (cand.get(key) || 0) + 1); }
    let best = null;
    for (const [key, n] of cand) { const inner = key.split(",").map(Number); const path = [u, ...inner, v];
      let len = 0; for (let j = 1; j < path.length; j++) len += hav(D.S[path[j - 1]], D.S[path[j]]);
      if (len > direct * 1.5 + 3) continue;
      const sc = inner.length * 1000 + n; if (!best || sc > best.sc) best = { sc, inner }; }
    if (best) out.push(...best.inner);
    out.push(v);
  }
  c.ids = out; return c;
}
function buildCorridor(a, b, via) {
  const c = buildCorridor0(a, b, via); return c ? densify(c) : null;
}
function buildCorridor0(a, b, via) {
  let c = corridorDirect(a, b, via);
  if (c) return c;
  if (via != null) {     // über: aus zwei Teilen
    const c1 = corridorDirect(a, via, null), c2 = corridorDirect(via, b, null);
    if (c1 && c2) return { ids: c1.ids.concat(c2.ids.slice(1)), variants: [], n: c1.n + c2.n, joined: [via] };
    return null;
  }
  // kein durchgehender Zug: Umsteigebahnhof suchen, der beide Teile verbindet
  const fromA = new Map(), toB = new Map();
  for (const ti of D.byStation.get(a) || []) { const t = D.T[ti]; for (const s of t.st) fromA.set(s, (fromA.get(s) || 0) + 1); }
  for (const ti of D.byStation.get(b) || []) { const t = D.T[ti]; for (const s of t.st) toB.set(s, (toB.get(s) || 0) + 1); }
  let best = null;
  for (const [s, n] of fromA) { if (s === a || s === b || !toB.has(s)) continue;
    const sc = Math.min(n, toB.get(s)) / (1 + (hav(D.S[a], D.S[s]) + hav(D.S[s], D.S[b])) / Math.max(1, hav(D.S[a], D.S[b])) * 3);
    if (!best || sc > best.sc) best = { s, sc }; }
  if (!best) return null;
  const c1 = corridorDirect(a, best.s, null), c2 = corridorDirect(best.s, b, null);
  if (!c1 || !c2) return null;
  return { ids: c1.ids.concat(c2.ids.slice(1)), variants: [], n: c1.n + c2.n, joined: [best.s] };
}

// ---------------- Fahrten des Tages auf der Strecke ----------------
function dayTrips(date, stationSet) {
  // alle Fahrten des Tages, die die Strecke berühren; gleiche Zugnummer wird durchgebunden
  const seen = new Set(), list = [];
  for (const s of stationSet) for (const ti of D.byStation.get(s) || []) if (!seen.has(ti)) { seen.add(ti); const t = D.T[ti]; if (runsOn(t, date)) list.push(t); }
  // Durchbindung: gleiche Nummer + Verwaltung, Ende = Anfang
  const extra = new Map();
  for (const t of list) { const k = t.fnr; if (!extra.has(k)) extra.set(k, []); }
  for (const k of extra.keys()) extra.set(k, D.byFnr.get(k).filter(t => runsOn(t, date)));
  const joined = [], done = new Set();
  for (const [, ts] of extra) {
    const arr = ts.slice().sort((x, y) => (x.dep.find(v => v != null) ?? 0) - (y.dep.find(v => v != null) ?? 0));
    while (arr.length) {
      let t = arr.shift(); if (done.has(t.i)) continue; done.add(t.i);
      let cur = { ...t, parts: [t.i], st: t.st.slice(), arr: t.arr.slice(), dep: t.dep.slice(), pass: t.pass.slice(), cats: [series(t)] };
      let changed = true;
      while (changed) { changed = false;
        for (let j = 0; j < arr.length; j++) { const o = arr[j];
          if (o.st[0] === cur.st[cur.st.length - 1] && (o.dep[0] ?? 0) >= (cur.arr[cur.arr.length - 1] ?? 0)) {
            cur.dep[cur.dep.length - 1] = o.dep[0];
            cur.st.push(...o.st.slice(1)); cur.arr.push(...o.arr.slice(1)); cur.dep.push(...o.dep.slice(1)); cur.pass.push(...o.pass.slice(1));
            if (!cur.cats.includes(series(o))) cur.cats.push(series(o));
            done.add(o.i); arr.splice(j, 1); changed = true; break; } } }
      cur.series = cur.cats.length > 1 ? cur.cats.slice().sort().join("/") : cur.cats[0];
      cur.name = `${cur.series} ${String(cur.fnr).replace(/^0+/, "").replace(/\+\d+$/, "")}`;
      joined.push(cur);
    }
  }
  return joined;
}

// ---------------- Modell für Strecke + Tag ----------------
let C = null;          // aktuelles Modell
const state = { a: null, b: null, via: null, date: null, single: {} };
let on = {}, scale = 1, sel = null, SER = {}, SERIES = [];

function model() {
  const cor = buildCorridor(state.a, state.b, state.via);
  if (!cor) return null;
  const ids = cor.ids; const idx = new Map(ids.map((s, i) => [s, i]));
  const km = [0]; for (let i = 1; i < ids.length; i++) km.push(km[i - 1] + Math.max(0.3, hav(D.S[ids[i - 1]], D.S[ids[i]])));
  const trips = dayTrips(state.date, ids);
  const runs = [], touch = [];
  for (const t of trips) {
    const pos = []; t.st.forEach((s, i) => { if (idx.has(s)) pos.push(i); });
    if (!pos.length) continue;
    // in monotone Stücke teilen
    let pieces = [], cur = [pos[0]];
    for (let j = 1; j < pos.length; j++) {
      const p0 = idx.get(t.st[cur[cur.length - 1]]), p1 = idx.get(t.st[pos[j]]);
      const prevDir = cur.length > 1 ? Math.sign(idx.get(t.st[cur[cur.length - 1]]) - idx.get(t.st[cur[cur.length - 2]])) : 0;
      const d = Math.sign(p1 - p0);
      if (d === 0 || (prevDir && d !== prevDir)) { pieces.push(cur); cur = [pos[j]]; }
      else cur.push(pos[j]);
    }
    pieces.push(cur);
    for (const pc of pieces) {
      if (pc.length < 2) { const i = pc[0], k = idx.get(t.st[i]); if (!t.pass[i] && k > 0 && k < ids.length - 1) touch.push({ t, i, k }); continue; }
      const d = Math.sign(idx.get(t.st[pc[1]]) - idx.get(t.st[pc[0]]));
      const ev = new Map();
      for (const i of pc) ev.set(idx.get(t.st[i]), [t.arr[i], t.dep[i], !t.pass[i]]);
      for (let j = 0; j + 1 < pc.length; j++) {
        const ia = idx.get(t.st[pc[j]]), ib = idx.get(t.st[pc[j + 1]]);
        const t0 = t.dep[pc[j]] ?? t.arr[pc[j]], t1 = t.arr[pc[j + 1]] ?? t.dep[pc[j + 1]];
        if (t0 == null || t1 == null) continue;
        for (let k = ia + d; k !== ib; k += d) { const f = (km[k] - km[ia]) / (km[ib] - km[ia] || 1); const m = t0 + (t1 - t0) * f; ev.set(k, [m, m, false]); }
      }
      const keys = [...ev.keys()].sort((x, y) => d * (x - y));
      const i0 = pc[0], i1 = pc[pc.length - 1];
      const E = keys.map(k => [k, ...ev.get(k)]);
      if (i0 === 0) E[0][1] = null;
      if (i1 === t.st.length - 1) E[E.length - 1][2] = null;
      const r = { id: t.i + "-" + keys[0], t, name: t.name, series: t.series, fnr: t.name.split(" ").pop(), dir: d,
        von: D.S[t.st[0]].name, nach: D.S[t.st[t.st.length - 1]].name, ev: E };
      if (i0 > 0) { r.prev = [D.S[t.st[i0 - 1]].name, t.dep[i0 - 1]]; r.orig = [r.von, t.dep[0]]; }
      if (i1 < t.st.length - 1) { r.next = [D.S[t.st[i1 + 1]].name, t.arr[i1 + 1]]; r.dest = [r.nach, t.arr[t.arr.length - 1]]; }
      if (i1 === t.st.length - 1) r._end = [t.st[i1], t.arr[i1]];
      if (i0 === 0) r._start = [t.st[0], t.dep[0]];
      runs.push(r);
    }
  }
  // vermutete Wende (gleiche Linie, gleicher Bahnhof, 3–45′)
  const startsAt = new Map(), endsAt = new Map();
  for (const t of trips) { const s0 = t.st[0], s1 = t.st[t.st.length - 1];
    if (!startsAt.has(s0)) startsAt.set(s0, []); startsAt.get(s0).push(t);
    if (!endsAt.has(s1)) endsAt.set(s1, []); endsAt.get(s1).push(t); }
  for (const r of runs) {
    if (r._end) { const [s, ta] = r._end; const c = (startsAt.get(s) || []).filter(t => t.series === r.series && t.dep[0] != null && t.dep[0] >= ta + 3 && t.dep[0] <= ta + 45).sort((x, y) => x.dep[0] - y.dep[0])[0];
      if (c) r.cont = { name: c.name, key: c.i, dep: c.dep[0], nach: D.S[c.st[c.st.length - 1]].name, arr: c.arr[c.arr.length - 1] }; }
    if (r._start) { const [s, td] = r._start; const c = (endsAt.get(s) || []).filter(t => t.series === r.series && t.arr[t.arr.length - 1] != null && t.arr[t.arr.length - 1] <= td - 3 && t.arr[t.arr.length - 1] >= td - 45).sort((x, y) => y.arr[y.arr.length - 1] - x.arr[x.arr.length - 1])[0];
      if (c) r.from = { name: c.name, arr: c.arr[c.arr.length - 1], von: D.S[c.st[0]].name }; }
  }
  runs.sort((x, y) => timD(x.ev[0]) - timD(y.ev[0]));

  // Begegnungen
  const at = (r, k, w) => { const e = r.ev.find(x => x[0] === k); if (!e) return null; const v = e[1 + w]; return v != null ? v : e[2 - w]; };
  const meets = []; const segMeet = new Array(ids.length - 1).fill(0), segStation = new Array(ids.length - 1).fill(0);
  const up = runs.filter(r => r.dir === 1), dn = runs.filter(r => r.dir === -1);
  for (const u of up) { const ku = new Set(u.ev.map(e => e[0]));
    for (const w of dn) { const common = w.ev.map(e => e[0]).filter(k => ku.has(k)).sort((x, y) => x - y);
      if (!common.length) continue;
      let found = false;
      for (const k of common) { const ua = at(u, k, 0), ud = at(u, k, 1), wa = at(w, k, 0), wd = at(w, k, 1);
        if (ua <= wd && wa <= ud && (common.includes(k + 1) || common.includes(k - 1))) {
          meets.push({ k, up: u.id, dn: w.id, buf_up: ud - wa, buf_dn: wd - ua, t: Math.max(ua, wa), line: false });
          if (k > 0 && common.includes(k - 1)) segStation[k - 1]++; if (k < ids.length - 1 && common.includes(k + 1)) segStation[k]++;
          found = true; break; } }
      if (found) continue;
      for (const k of common) { if (!common.includes(k + 1)) continue;
        const u0 = at(u, k, 1), u1 = at(u, k + 1, 0), w0 = at(w, k + 1, 1), w1 = at(w, k, 0);
        if (u0 < w1 && w0 < u1) { const f = (w1 - u0) / ((u1 - u0) + (w1 - w0) || 1);
          meets.push({ k: k + f, kk: k, up: u.id, dn: w.id, t: u0 + (u1 - u0) * f, line: true }); segMeet[k]++; break; } } } }
  // Ein-/Zweigleisigkeit aus dem Fahrplan geschätzt: Begegnung auf der Strecke = zweigleisig
  const single = segMeet.map((m, k) => {
    const key = ids[k] + "-" + ids[k + 1];
    if (state.single[key] != null) return { v: state.single[key], src: "manuell" };
    if (m > 0) return { v: false, src: "Fahrplan: Begegnung auf der Strecke" };
    if (segStation[k] >= 2) return { v: true, src: "Fahrplan: Kreuzungen nur in Bahnhöfen" };
    return { v: null, src: "unbekannt" };
  });
  meets.forEach(m => { const k = m.line ? m.kk : m.k; m.single = m.line ? single[m.kk].v === true : ((k > 0 && single[k - 1].v === true) || (k < single.length && single[k] && single[k].v === true)); });

  // Hauptbahnhöfe: Enden, Ein-/Ausstiege von Fahrten, viele Halte
  const stopCnt = new Array(ids.length).fill(0), branch = new Array(ids.length).fill(0);
  for (const r of runs) { for (const e of r.ev) if (e[3]) stopCnt[e[0]]++; branch[r.ev[0][0]]++; branch[r.ev[r.ev.length - 1][0]]++; }
  touch.forEach(x => branch[x.k]++);
  const maxStop = Math.max(1, ...stopCnt);
  const major = new Set(ids.map((s, i) => i).filter(i => i === 0 || i === ids.length - 1 || branch[i] >= 2 || stopCnt[i] >= 0.8 * maxStop).map(i => D.S[ids[i]].name));
  return { ids, idx, km, stations: ids.map(s => D.S[s].name), runs, touch, meets, single, major, cor, trips };
}

// ---------------- Farben je Linie ----------------
const SLOTS = ["--s1", "--s2", "--s3", "--s4", "--s5", "--s6", "--s7"];
function assignSeries() {
  const cnt = new Map(); C.runs.forEach(r => cnt.set(r.series, (cnt.get(r.series) || 0) + Math.abs(C.km[r.ev[r.ev.length - 1][0]] - C.km[r.ev[0][0]])));
  const keys = [...cnt.entries()].sort((a, b) => b[1] - a[1]).map(x => x[0]);
  SERIES = keys.map((k, i) => ({ k, label: k, c: i < SLOTS.length ? SLOTS[i] : "--text-muted", dash: /^(TGV|ICE|EC|RJX?|NJ|EN)/.test(k) }));
  SER = Object.fromEntries(SERIES.map(s => [s.k, s]));
  for (const s of SERIES) if (on[s.k] == null) on[s.k] = true;
}

// ---------------- Panel / Auswahl ----------------
function showPanel(r) {
  const P = $("panel");
  if (!r) { P.innerHTML = '<span class="muted">Zug antippen: Laufweg und Zeiten erscheinen hier. Einen Halt antippen öffnet zusätzlich die Knotenlupe.</span>'; return; }
  const s = SER[r.series] || { c: "--text-muted" };
  P.innerHTML = `<b><span class="sw${s.dash ? " dash" : ""}" style="background:var(${s.c});color:var(${s.c});vertical-align:middle"></span> ${esc(r.name)}</b> <span class="muted">${esc(r.von)} → ${esc(r.nach)}</span>
  ${r.prev ? `<div class="muted">← von ${esc(r.orig[0])} ab ${fmt(r.orig[1])} · vorher ${esc(r.prev[0])} ${fmt(r.prev[1])}</div>` : ""}
  ${r.from ? `<div class="muted">↺ vermutlich aus ${esc(r.from.name)} (von ${esc(r.from.von)}, an ${fmt(r.from.arr)})</div>` : ""}
  <div class="stops">${r.ev.map(e => `<span class="${e[3] ? "" : "pass"}">${esc(C.stations[e[0]])} ${e[3] ? (e[1] != null && e[2] != null && Math.round(e[2]) - Math.round(e[1]) >= 2 ? fmt(e[1]) + "–" + fmt(e[2]) : fmt(tim(e))) : "| ~" + fmt(e[1])}</span>`).join("")}</div>
  ${r.next ? `<div class="muted">→ weiter: ${esc(r.next[0])} an ${fmt(r.next[1])} · Ziel ${esc(r.dest[0])} an ${fmt(r.dest[1])}</div>` : ""}
  ${r.cont ? `<div class="muted">↺ vermutlich weiter als ${esc(r.cont.name)} ab ${fmt(r.cont.dep)} → ${esc(r.cont.nach)} an ${fmt(r.cont.arr)} (Vermutung)</div>` : ""}`;
}
function select(id) {
  sel = (sel === id) ? null : id;
  document.querySelectorAll("#bfsvg .trn").forEach(g => g.classList.toggle("hl", g.dataset.id === sel));
  const sv = $("bfsvg"); if (sv) sv.classList.toggle("dim", !!sel);
  document.querySelectorAll("table.kb [data-id]").forEach(c => c.classList.toggle("hl", c.dataset.id === sel));
  showPanel(C.runs.find(r => r.id === sel));
}

// ---------------- Legende ----------------
function legend() {
  const L = $("legend"); L.innerHTML = "";
  for (const s of SERIES) {
    const b = h("button", `<span class="sw${s.dash ? " dash" : ""}" style="background:var(${s.c});color:var(${s.c})"></span>${esc(s.label)}`, "chip");
    b.setAttribute("aria-pressed", on[s.k]); b.onclick = () => { on[s.k] = !on[s.k]; renderViews(); }; L.appendChild(b);
  }
  const ctl = h("div", "Zeitmassstab ", "ctl");
  [1, 2, 4].forEach(f => { const b = h("button", f + "×"); b.setAttribute("aria-pressed", scale === f); b.onclick = () => { scale = f; renderViews(true); }; ctl.appendChild(b); });
  L.appendChild(ctl);
}
const runsOn_ = () => C.runs.filter(r => on[r.series]);

// ---------------- Bildfahrplan ----------------
let BFL = null;   // Masse der zuletzt gezeichneten Grafik (für den Druck)
const shortName = n => n.replace(/ - .*$/, "").replace(/ \(.*\)$/, "");
function drawBF(scroll) {
  const host = $("bf"); host.innerHTML = "";
  const bh = h("div", null); bh.style.cssText = "display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin:22px 0 6px";
  bh.appendChild(h("h2", "Bildfahrplan <span style='font-weight:400;color:var(--text-muted);font-size:12px'>Strecke waagrecht nach km, Zeit nach unten · Band oben: ═ zweigleisig, ─ eingleisig, ┄ unbekannt (antippen zum Ändern)</span>")).style.margin = "0";
  const pv = h("button", "🖨 Ausschnitt drucken / PDF", "chip"); pv.onclick = () => printBF("view"); bh.appendChild(pv);
  const pd = h("button", "🖨 ganzer Tag als PDF", "chip"); pd.title = "mehrere Seiten A4 quer; mit Zeitmassstab 2× oder 4× werden es mehr Seiten mit mehr Platz"; pd.onclick = () => printBF("day"); bh.appendChild(pd);
  host.appendChild(bh);
  const head = h("div", null, "chartbox"); head.style.cssText = "overflow:hidden;border-bottom:0;border-radius:10px 10px 0 0";
  const box = h("div", null, "chartbox"); box.style.borderRadius = "0 0 10px 10px"; box.style.maxHeight = "70vh";
  host.appendChild(head); host.appendChild(box);
  const avail = Math.max(340, host.clientWidth || 900);
  const ML = 40, MR = 46, HT = 118, MT = 10, MB = 20, T0 = 4 * 60, T1 = 25 * 60;
  const W = avail - ML - MR - 2, PY = 1.15 * scale;
  const kmMax = C.km[C.km.length - 1] || 1;
  const X = k => ML + (k / kmMax) * W, Y = t => MT + (t - T0) * PY;
  const xk = kf => { const i = Math.floor(kf), f = kf - i; return i >= C.km.length - 1 ? X(C.km[C.km.length - 1]) : X(C.km[i] + (C.km[i + 1] - C.km[i]) * f); };
  const H = MT + (T1 - T0) * PY + MB;
  const hs = el("svg", { width: avail - 2, height: HT, "aria-hidden": "true" }, head);
  BFL = { ML, MT, HT, PY, T0, T1, W: avail - 2, box, hs };
  const svg = el("svg", { id: "bfsvg", width: avail - 2, height: H, role: "img", "aria-label": "Bildfahrplan" }, box);
  // Gleisband
  C.single.forEach((sg, k) => {
    const x1 = X(C.km[k]), x2 = X(C.km[k + 1]), g = el("g", { class: "seg" }, hs);
    if (sg.v === true) el("line", { x1, x2, y1: HT - 8, y2: HT - 8, stroke: "var(--text-secondary)", "stroke-width": 1.5 }, g);
    else if (sg.v === false) { el("line", { x1, x2, y1: HT - 10, y2: HT - 10, stroke: "var(--text-secondary)", "stroke-width": 1.5 }, g); el("line", { x1, x2, y1: HT - 6, y2: HT - 6, stroke: "var(--text-secondary)", "stroke-width": 1.5 }, g); }
    else el("line", { x1, x2, y1: HT - 8, y2: HT - 8, stroke: "var(--text-muted)", "stroke-width": 1.5, "stroke-dasharray": "2 3" }, g);
    el("rect", { x: x1, y: HT - 16, width: Math.max(2, x2 - x1), height: 16, fill: "transparent" }, g);
    el("title", {}, g).textContent = `${C.stations[k]} – ${C.stations[k + 1]}: ${sg.v === true ? "eingleisig" : sg.v === false ? "zweigleisig" : "unbekannt"} (${sg.src}) – antippen zum Ändern`;
    g.addEventListener("click", () => { const key = C.ids[k] + "-" + C.ids[k + 1]; const cur = sg.v; state.single[key] = cur === true ? false : cur === false ? null : true; if (state.single[key] == null) delete state.single[key]; recompute(); });
  });
  const drawn = C.stations.map(n => C.major.has(n));
  C.stations.forEach((n, i) => { if (!drawn[i]) { const x = X(C.km[i]); let near = false; for (let j = 0; j < C.stations.length; j++) if (j !== i && drawn[j] && Math.abs(X(C.km[j]) - x) < 12) near = true; drawn[i] = !near; } });
  // auch Nebenhalte nicht zu dicht
  let lastX = -99; C.stations.forEach((n, i) => { if (!drawn[i] || C.major.has(n)) return; const x = X(C.km[i]); if (x - lastX < 11) drawn[i] = false; else lastX = x; });
  C.stations.forEach((n, i) => { const x = X(C.km[i]), maj = C.major.has(n);
    el("circle", { cx: x, cy: HT - 8, r: maj ? 3.2 : 2.2, fill: "var(--surface-1)", stroke: "var(--text-secondary)", "stroke-width": 1.3 }, hs);
    if (!drawn[i]) return;
    const t = el("text", { transform: `translate(${x + 2},${HT - 17}) rotate(-55)`, class: maj ? "st-major" : "", style: "cursor:pointer" }, hs); t.textContent = shortName(n);
    t.addEventListener("click", () => { const mid = T0 + (box.scrollTop + box.clientHeight / 2 - MT) / PY; lupe(C.ids[i], mid); }); });
  el("text", { x: 4, y: HT - 4, style: "font-size:9px;fill:var(--text-muted)" }, hs).textContent = Math.round(kmMax) + " km";
  // Raster
  for (let m = T0; m <= T1; m += 60) {
    el("line", { x1: ML, x2: ML + W, y1: Y(m), y2: Y(m), stroke: "var(--grid-strong)", "stroke-width": 1 }, svg);
    el("text", { x: ML - 6, y: Y(m) + 4, "text-anchor": "end" }, svg).textContent = (m / 60 % 24) + "h";
    if (scale >= 2) for (const q of [10, 20, 30, 40, 50]) el("line", { x1: ML, x2: ML + W, y1: Y(m + q), y2: Y(m + q), stroke: "var(--grid)", "stroke-width": q === 30 ? 1 : .6 }, svg);
    else el("line", { x1: ML, x2: ML + W, y1: Y(m + 30), y2: Y(m + 30), stroke: "var(--grid)", "stroke-width": 1 }, svg);
  }
  C.stations.forEach((n, i) => { const x = X(C.km[i]); el("line", { x1: x, x2: x, y1: 0, y2: H - MB, stroke: C.major.has(n) ? "var(--grid-strong)" : "var(--grid)", "stroke-width": 1 }, svg); });
  // Züge
  for (const r of runsOn_()) {
    const s = SER[r.series]; const pts = [];
    for (const e of r.ev) { const x = X(C.km[e[0]]); if (e[1] != null) pts.push([x, Y(e[1])]); if (e[2] != null) pts.push([x, Y(e[2])]); }
    if (pts.length < 2) continue;
    const d = pts.map((p, i) => (i ? "L" : "M") + p[0].toFixed(1) + "," + p[1].toFixed(1)).join("");
    const g = el("g", { class: "trn", "data-id": r.id }, svg);
    el("path", { d, fill: "none", stroke: "var(--surface-1)", "stroke-width": 5, "stroke-linejoin": "round" }, g);
    el("path", { d, fill: "none", stroke: `var(${s.c})`, "stroke-width": 2, "stroke-linejoin": "round", "stroke-dasharray": s.dash ? "7 4" : "none" }, g);
    for (const e of r.ev) if (e[3]) el("circle", { cx: X(C.km[e[0]]), cy: Y(timD(e)), r: 1.8, fill: `var(${s.c})` }, g);
    const a = pts[0];
    el("text", { x: a[0] + (r.dir > 0 ? 4 : -4), y: a[1] - 3, "text-anchor": r.dir > 0 ? "start" : "end", class: "lbl" }, g).textContent = r.fnr;
    const hit = el("path", { d, fill: "none", stroke: "transparent", "stroke-width": 14, style: "cursor:pointer" });
    const ext = (p0, p1) => { let dx = p1[0] - p0[0], dy = p1[1] - p0[1]; const L = Math.hypot(dx, dy) || 1; dx /= L; dy /= L;
      const q1 = [p1[0] + dx * 6, p1[1] + dy * 6], q2 = [p1[0] + dx * 20, p1[1] + dy * 20];
      el("path", { d: `M${p1[0]},${p1[1]}L${q1[0]},${q1[1]}`, stroke: `var(${s.c})`, "stroke-width": 2, fill: "none" }, g);
      el("path", { d: `M${q1[0]},${q1[1]}L${q2[0]},${q2[1]}`, stroke: `var(${s.c})`, "stroke-width": 2, fill: "none", "stroke-dasharray": "1.5 3", "stroke-linecap": "round" }, g);
      return q2; };
    const nonVert = arr => { const e = arr[arr.length - 1]; for (let i = arr.length - 2; i >= 0; i--) if (Math.abs(arr[i][0] - e[0]) > .5) return arr[i]; return [e[0] - r.dir, e[1] - 1]; };
    let hd = d;
    if (r.next) { const q = ext(nonVert(pts), pts[pts.length - 1]); hd += `M${pts[pts.length - 1][0]},${pts[pts.length - 1][1]}L${q[0]},${q[1]}`; }
    if (r.prev) { const rv = pts.slice().reverse(); const q = ext(nonVert(rv), pts[0]); hd += `M${pts[0][0]},${pts[0][1]}L${q[0]},${q[1]}`; }
    hit.setAttribute("d", hd); g.appendChild(hit);
    const E1 = r.ev[r.ev.length - 1];
    if (r.cont) { el("text", { x: X(C.km[E1[0]]) + (r.dir > 0 ? 3 : -3), y: Y(tim(E1)) + 12, "text-anchor": r.dir > 0 ? "start" : "end", style: `font-size:11px;fill:var(${s.c});font-weight:700` }, g).textContent = "↺";
      const cr = C.runs.find(q => q.t.i === r.cont.key && q.ev.some(x => x[0] === E1[0]));
      if (cr && on[cr.series]) el("line", { x1: X(C.km[E1[0]]), x2: X(C.km[E1[0]]), y1: Y(tim(E1)), y2: Y(r.cont.dep), stroke: `var(${s.c})`, "stroke-width": 1.2, "stroke-dasharray": "1.5 2.5" }, g); }
    hit.addEventListener("mouseenter", () => { if (!sel) showPanel(r); });
    hit.addEventListener("click", ev => { ev.stopPropagation();
      const bb = svg.getBoundingClientRect(), mx = ev.clientX - bb.left, my = ev.clientY - bb.top; let best = null;
      for (const e of r.ev) { if (!e[3]) continue; const x = X(C.km[e[0]]);
        for (const t of [e[1], e[2]]) { if (t == null) continue; const dd = Math.hypot(x - mx, Y(t) - my); if (dd < 12 && (!best || dd < best.dd)) best = { dd, k: e[0], t }; } }
      if (sel !== r.id) select(r.id);
      if (best) lupe(C.ids[best.k], best.t, r.t.i, true); });
  }
  // Züge, die die Strecke nur in einem Bahnhof berühren
  for (const x of C.touch) { const t = x.t; if (on[t.series] === false) continue; const sc = SER[t.series] || { c: "--text-muted" };
    const X0 = X(C.km[x.k]), a = t.arr[x.i], dd = t.dep[x.i]; const g = el("g", { class: "trn" }, svg);
    if (a != null) el("path", { d: `M${X0 - 14},${Y(a) - 10}L${X0},${Y(a)}`, stroke: `var(${sc.c})`, "stroke-width": 2, fill: "none", "stroke-dasharray": "1.5 3", "stroke-linecap": "round" }, g);
    if (dd != null) el("path", { d: `M${X0},${Y(dd)}L${X0 - 14},${Y(dd) + 10}`, stroke: `var(${sc.c})`, "stroke-width": 2, fill: "none", "stroke-dasharray": "1.5 3", "stroke-linecap": "round" }, g);
    if (a != null && dd != null) el("line", { x1: X0, x2: X0, y1: Y(a), y2: Y(dd), stroke: `var(${sc.c})`, "stroke-width": 2 }, g);
    const t0 = a ?? dd, t1 = dd ?? a;
    const hit = el("rect", { x: X0 - 16, y: Y(t0) - 12, width: 20, height: Y(t1) - Y(t0) + 24, fill: "transparent", style: "cursor:pointer" }, g);
    hit.addEventListener("mouseenter", () => { if (!sel) $("panel").innerHTML = `<b><span class="sw" style="background:var(${sc.c})"></span> ${esc(t.name)}</b> <span class="muted">${esc(D.S[t.st[0]].name)} → ${esc(D.S[t.st[t.st.length - 1]].name)}</span><div class="stops">${esc(C.stations[x.k])}: ${a != null ? "an " + fmt(a) : ""} ${dd != null ? "ab " + fmt(dd) : ""} ${x.i > 0 ? "· von " + esc(D.S[t.st[x.i - 1]].name) : ""} ${x.i < t.st.length - 1 ? "· weiter " + esc(D.S[t.st[x.i + 1]].name) : ""}</div><div class="muted">Berührt die Strecke nur hier – antippen für die Knotenlupe</div>`; });
    hit.addEventListener("click", ev => { ev.stopPropagation(); lupe(C.ids[x.k], t0, t.i, true); });
  }
  // Kreuzungen
  const R = Object.fromEntries(C.runs.map(r => [r.id, r]));
  for (const m of C.meets) { if (!on[R[m.up].series] || !on[R[m.dn].series] || !m.single) continue;
    const x = xk(m.k), y = Y(m.t);
    if (m.line) el("text", { x, y: y + 4, "text-anchor": "middle", style: "fill:var(--bad);font-size:14px;font-weight:700" }, svg).textContent = "✕";
    else el("circle", { cx: x, cy: y, r: 4.5, fill: "none", stroke: "var(--meet)", "stroke-width": 1.6 }, svg); }
  // jetzt
  const today = new Date(); const iso = today.toISOString().slice(0, 10);
  const nm = today.getHours() * 60 + today.getMinutes();
  if (iso === state.date || true) { el("line", { x1: ML, x2: ML + W, y1: Y(nm), y2: Y(nm), stroke: "var(--now)", "stroke-width": 1.5, "stroke-dasharray": "5 3" }, svg);
    el("text", { x: ML + W, y: Y(nm) - 4, "text-anchor": "end", style: "fill:var(--now);font-size:10px" }, svg).textContent = (iso === state.date ? "jetzt " : "Uhrzeit ") + fmt(nm); }
  svg.addEventListener("click", () => { if (sel) select(sel); });
  if (scroll) box.scrollTop = Math.max(0, Y(Math.max(T0, Math.min(nm, T1)) - 60));
  host.appendChild(h("div", `<span>◯ Kreuzung auf Einspur</span><span style="color:var(--bad)">✕ Begegnung auf Einspur zwischen Bahnhöfen</span><span>• Halt, ohne Punkt = Durchfahrt</span><span>kurz verlängert, dann punktiert = fährt auf anderer Strecke weiter / kommt von dort</span><span>↺ endet, vermutlich weiter unter anderer Nummer</span><span style="color:var(--now)">- - Uhrzeit</span>`, "legend-sym"));
  if (sel) { const id = sel; sel = null; select(id); }
}

// ---------------- Knotenlupe ----------------
function stationEvents(s) {
  const out = [];
  for (const t of C.trips) { t.st.forEach((x, i) => { if (x !== s || t.pass[i]) return;
    const nm = j => D.S[t.st[j]].name;
    out.push({ key: t.i, name: t.name, series: t.series, arr: t.arr[i], dep: t.dep[i], von: nm(0), nach: nm(t.st.length - 1),
      prev: i > 0 ? nm(i - 1) : null, next: i < t.st.length - 1 ? nm(i + 1) : null, destArr: t.arr[t.arr.length - 1] }); }); }
  // Fahrten, die hier halten, aber die Strecke nicht berühren (andere Linien am Knoten)
  const have = new Set(C.trips.map(t => t.i));
  for (const ti of D.byStation.get(s) || []) { const t = D.T[ti]; if (have.has(ti) || !runsOn(t, state.date)) continue;
    t.st.forEach((x, i) => { if (x !== s || t.pass[i]) return; const nm = j => D.S[t.st[j]].name;
      out.push({ key: t.i, name: tLabel(t), series: series(t), arr: t.arr[i], dep: t.dep[i], von: nm(0), nach: nm(t.st.length - 1),
        prev: i > 0 ? nm(i - 1) : null, next: i < t.st.length - 1 ? nm(i + 1) : null, destArr: t.arr[t.arr.length - 1] }); }); }
  // vermutete Wende
  for (const e of out) if (!e.next && e.arr != null) { const c = out.filter(x => !x.prev && x.series === e.series && x.dep != null && x.dep >= e.arr + 3 && x.dep <= e.arr + 45).sort((a, b) => a.dep - b.dep)[0]; if (c) e.cont = c.key; }
  return out.sort((a, b) => (a.arr ?? a.dep) - (b.arr ?? b.dep));
}
function lupe(s, tc, hlKey, noScroll) {
  const host = $("lupe"); host.innerHTML = "";
  const n = D.S[s].name; const narrow = (host.clientWidth || 900) < 600;
  const span = narrow ? 22 : 40, t0 = Math.round(tc) - span, t1 = Math.round(tc) + span;
  const all = stationEvents(s);
  const evs = all.filter(e => on[e.series] !== false && (e.arr ?? e.dep) <= t1 && (e.dep ?? e.arr) >= t0);
  const head = h("div", null); head.style.cssText = "display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin:22px 0 6px";
  head.appendChild(h("h2", `Knotenlupe · ${esc(n)} · ${fmt(t0)}–${fmt(t1)}`)).style.margin = "0";
  const st = narrow ? 20 : 30;
  const mk = (lab, dt) => { const b = h("button", lab, "chip"); b.onclick = () => lupe(s, tc + dt, hlKey, true); head.appendChild(b); };
  mk("◀ " + st + "′", -st); mk(st + "′ ▶", st);
  const sl = h("select", null); sl.className = "chip"; C.ids.forEach((id, i) => { if (!C.major.has(C.stations[i]) && id !== s) return; const o = h("option", esc(C.stations[i])); o.value = id; if (id === s) o.selected = true; sl.appendChild(o); });
  sl.onchange = () => lupe(+sl.value, tc, hlKey, true); head.appendChild(sl);
  const x = h("button", "✕", "chip"); x.onclick = () => { host.innerHTML = ""; }; head.appendChild(x);
  host.appendChild(head);
  if (!evs.length) { host.appendChild(h("p", "Keine Züge in diesem Zeitfenster.", "note")); if (!noScroll) host.scrollIntoView({ behavior: "smooth", block: "nearest" }); return; }
  const box = h("div", null, "tblwrap"); host.appendChild(box);
  const Wd = Math.max(340, (host.clientWidth || 900) - 2), LL = narrow ? 104 : Math.min(230, Wd * .36), RR = narrow ? 92 : Math.min(150, Wd * .24), RH = narrow ? 34 : 30, TOP = 26;
  const X = t => LL + (t - t0) / (t1 - t0) * (Wd - LL - RR); const H = TOP + evs.length * RH + 10;
  const svg = el("svg", { width: Wd, height: H, role: "img", "aria-label": "Knotenlupe " + n }, box);
  for (let m = Math.ceil(t0 / 10) * 10; m <= t1; m += 10) { el("line", { x1: X(m), x2: X(m), y1: TOP - 6, y2: H - 6, stroke: m % 60 === 0 ? "var(--grid-strong)" : "var(--grid)" }, svg);
    el("text", { x: X(m), y: TOP - 10, "text-anchor": "middle", style: "font-size:10px" }, svg).textContent = fmt(m); }
  const row = new Map(); evs.forEach((e, i) => row.set(e.key, i)); const yR = i => TOP + i * RH + RH / 2;
  const conns = [];
  evs.forEach(a => { if (a.arr == null || !a.prev) return; const byNext = {};
    evs.forEach(d => { if (d.dep == null || !d.next || d.key === a.key || d.next === a.prev) return; if (a.next === d.next && a.dep != null) return;
      const w = d.dep - a.arr; if (w < 3 || w > 30) return; if (!byNext[d.next] || d.dep < byNext[d.next].dep) byNext[d.next] = d; });
    Object.values(byNext).forEach(d => conns.push([a, d, d.dep - a.arr, false]));
    if (a.cont != null) { const d = evs.find(q => q.key === a.cont); if (d) conns.push([a, d, d.dep - a.arr, true]); } });
  const cg = el("g", {}, svg);
  for (const [a, d, w, wende] of conns) { const xa = X(a.arr), xd = X(d.dep), ya = yR(row.get(a.key)), yd = yR(row.get(d.key));
    const col = wende ? "var(--text-secondary)" : w <= 10 ? "var(--good)" : w <= 20 ? "var(--warn)" : "var(--bad)";
    el("path", { d: `M${xa},${ya}C${(xa + xd) / 2},${ya} ${(xa + xd) / 2},${yd} ${xd},${yd}`, fill: "none", stroke: col, "stroke-width": 1.4, "stroke-dasharray": wende ? "2 3" : "none", opacity: .9 }, cg);
    el("text", { x: (xa + xd) / 2 + 3, y: (ya + yd) / 2 - 2, style: `font-size:10px;fill:${col};paint-order:stroke;stroke:var(--surface-1);stroke-width:3px` }, cg).textContent = (wende ? "↺ " : "") + Math.round(w) + "′"; }
  evs.forEach((e, i) => { const y = yR(i), sc = SER[e.series] || { c: "--text-muted" };
    if (e.key === hlKey) el("rect", { x: 0, y: y - RH / 2, width: Wd, height: RH, fill: `var(${sc.c})`, opacity: .16 }, svg);
    else if (i % 2) el("rect", { x: 0, y: y - RH / 2, width: Wd, height: RH, fill: "var(--surface-2)", opacity: .45 }, svg);
    el("text", { x: 6, y: y - 2, style: "font-size:11.5px;fill:var(--text-primary);font-weight:600" }, svg).textContent = e.name;
    el("text", { x: 6, y: y + 11, style: "font-size:10px" }, svg).textContent = e.prev ? ("von " + (narrow ? e.von : e.prev + (e.von !== e.prev ? " (" + e.von + ")" : ""))) : "beginnt hier";
    const a = e.arr ?? e.dep, d = e.dep ?? e.arr;
    el("line", { x1: X(Math.max(a, t0 - 2)), x2: X(Math.min(d, t1 + 2)), y1: y, y2: y, stroke: `var(${sc.c})`, "stroke-width": 6, "stroke-linecap": "round" }, svg);
    if (e.arr != null) el("text", { x: X(e.arr) - 6, y: y + 4, "text-anchor": "end", style: "font-size:10.5px;fill:var(--text-primary)" }, svg).textContent = fmt(e.arr);
    if (e.dep != null) el("text", { x: X(e.dep) + 6, y: y + 4, style: "font-size:10.5px;fill:var(--text-primary)" }, svg).textContent = fmt(e.dep);
    el("text", { x: Wd - 6, y: y - 2, "text-anchor": "end", style: "font-size:11px;fill:var(--text-primary)" }, svg).textContent = e.next ? "→ " + (narrow ? e.next.slice(0, 14) : e.next) : (e.cont != null ? "endet ↺" : "endet hier");
    el("text", { x: Wd - 6, y: y + 11, "text-anchor": "end", style: "font-size:10px" }, svg).textContent = e.next && e.nach !== e.next ? (narrow ? e.nach : "Ziel " + e.nach + " " + fmt(e.destArr)) : ""; });
  host.appendChild(h("p", "Balken = Aufenthalt (an–ab). Bögen = erster Anschluss je Richtung (3–30′): grün ≤10′, gelb ≤20′, rot länger. Gepunktet ↺ = vermutete Wende derselben Linie (keine Umlaufdaten). Öffnen: Halt eines Zuges im Bildfahrplan antippen oder Bahnhofsname oben.", "note"));
  if (!noScroll) host.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

// ---------------- Kursbuch ----------------
let kbAll = false;
function drawKB(target, printCols) {
  const host = target || $("kb"); host.innerHTML = "";
  const hd = h("div", null); hd.style.cssText = "display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin:22px 0 6px";
  hd.appendChild(h("h2", "Kursbuch")).style.margin = "0";
  const now = new Date(); const nm = now.getHours() * 60 + now.getMinutes();
  if (!printCols) { const tb = h("button", kbAll ? "nur ±3 h um jetzt" : "ganzer Tag", "chip"); tb.onclick = () => { kbAll = !kbAll; drawKB(); }; hd.appendChild(tb);
    const pk = h("button", "🖨 Kursbuch drucken / PDF", "chip"); pk.onclick = () => printKB(); hd.appendChild(pk); }
  host.appendChild(hd);
  for (const dir of [1, -1]) {
    const order = C.stations.map((n, i) => i); if (dir < 0) order.reverse();
    let runs = runsOn_().filter(r => r.dir === dir).sort((a, b) => timD(a.ev[0]) - timD(b.ev[0]));
    const total = runs.length;
    if (!kbAll) runs = runs.filter(r => timD(r.ev[r.ev.length - 1]) >= nm - 180 && timD(r.ev[0]) <= nm + 180);
    host.appendChild(h("h3", `${esc(C.stations[order[0]])} → ${esc(C.stations[order[order.length - 1]])} · ${kbAll ? total : runs.length + " von " + total} Fahrten`));
    if (!runs.length) continue;
    const allRuns = runs; const step = printCols || allRuns.length;
    for (let b0 = 0; b0 < allRuns.length; b0 += step) { runs = allRuns.slice(b0, b0 + step);
    const wrap = h("div", null, "tblwrap"), T = h("table", null, "kb"); wrap.appendChild(T); host.appendChild(wrap);
    let html = "<thead><tr><th class='st'></th>" + runs.map(r => `<th class="tr" data-id="${r.id}" style="--c:var(${SER[r.series].c})">${esc(r.series)}<br>${esc(r.fnr)}</th>`).join("") + "</tr></thead><tbody>";
    html += "<tr><td class='st anab'>von</td>" + runs.map(r => `<td class="vn" data-id="${r.id}">${r.von !== C.stations[r.ev[0][0]] ? esc(r.von) : ""}</td>`).join("") + "</tr>";
    for (const i of order) {
      const maj = C.major.has(C.stations[i]);
      const rows = maj ? [["an", 0], ["ab", 1]] : [["", 2]];
      if (!maj && !runs.some(r => r.ev.some(e => e[0] === i && e[3]))) continue;   // Durchfahrtspunkte ohne Halt weglassen
      rows.forEach(([lab, kind], ri) => {
        html += `<tr class="${maj && ri === 0 ? "major" : ""}"><td class="st">${ri === 0 ? esc(C.stations[i]) : ""} <span style="color:var(--text-muted);font-size:10px;float:right;margin-left:6px">${lab}</span></td>`;
        for (const r of runs) {
          const e = r.ev.find(x => x[0] === i); let v = "", cl = e && !e[3] ? "pass" : "", tt = "";
          if (e) {
            const first = e === r.ev[0], last = e === r.ev[r.ev.length - 1];
            if (!e[3]) v = kind === 0 ? "" : "|";
            else if (kind === 0) v = e[1] != null ? fmt(e[1]) : "";
            else if (kind === 1) v = e[2] != null ? fmt(e[2]) : "";
            else v = fmt(timD(e));
            const up = `<span class="arr" title="kommt von ${esc(r.prev ? r.prev[0] : "")} (ab ${fmt(r.prev ? r.prev[1] : null)}), Herkunft ${esc(r.orig ? r.orig[0] : "")}">↑</span>`;
            const dn = `<span class="arr" title="weiter nach ${esc(r.next ? r.next[0] : "")} (an ${fmt(r.next ? r.next[1] : null)}), Ziel ${esc(r.dest ? r.dest[0] : "")} ${fmt(r.dest ? r.dest[1] : null)}">↓</span>`;
            if (first) { if (r.prev) { if (kind !== 1 || e[1] == null) v = up + v; } else if (kind !== 0) { cl += " beg"; tt = r.from ? `vermutlich aus ${r.from.name} (an ${fmt(r.from.arr)})` : "beginnt hier"; } }
            if (last) { if (r.next) { if (kind !== 0 || e[2] == null) v = v + dn; } else if (kind !== 1) { cl += " end"; tt = r.cont ? `endet; vermutlich weiter als ${r.cont.name} ab ${fmt(r.cont.dep)}` : "endet hier"; if (r.cont) v += ' <span class="arr">↺</span>'; } }
          }
          html += `<td data-id="${r.id}" class="${cl}"${tt ? ` title="${esc(tt)}"` : ""}>${v}</td>`;
        }
        html += "</tr>";
      });
    }
    html += "<tr><td class='st anab'>nach</td>" + runs.map(r => `<td class="vn" data-id="${r.id}">${r.nach !== C.stations[r.ev[r.ev.length - 1][0]] ? esc(r.nach) : ""}</td>`).join("") + "</tr></tbody>";
    T.innerHTML = html;
    T.querySelectorAll("th.tr").forEach(th => th.onclick = () => { select(th.dataset.id); $("bf").scrollIntoView({ behavior: "smooth" }); });
    } }
  host.appendChild(h("p", "„|“ = Durchfahrt. Strich über der Zeit = Zug beginnt hier, Strich unter der Zeit = Zug endet hier (↺ = vermutlich Wende). ↑ = kommt von einer anderen Strecke, ↓ = fährt auf einer anderen Strecke weiter (Tooltip). Bahnhöfe ohne Halt sind ausgeblendet.", "note"));
}

// ---------------- Druck / PDF ----------------
function printHeader(what) {
  const d = state.date, wd = WD[new Date(d + "T12:00:00").getDay()];
  return h("div", `<div class="druckkopf"><b>${esc(what)} · ${esc(D.S[state.a].name)} → ${esc(D.S[state.b].name)}${state.via != null ? " über " + esc(D.S[state.via].name) : ""}</b> · ${wd} ${dateDE(d)}<br><span>Quelle: HRDF (opentransportdata.swiss), Stand ${esc(D.meta.erzeugt)} · Kilometer Luftlinie, Gleiszahl aus Fahrplan geschätzt · vxstone.github.io/fahrplan-verstehen</span></div>`);
}
function doPrint(node) {
  let P = $("druck"); if (P) P.remove();
  P = h("div", null); P.id = "druck"; P.appendChild(node); document.querySelector(".viz-root").appendChild(P);
  document.body.classList.add("drucken");
  const done = () => { document.body.classList.remove("drucken"); P.remove(); window.removeEventListener("afterprint", done); };
  window.addEventListener("afterprint", done);
  setTimeout(() => { try { window.print(); } catch (e) { done(); alert("Drucken ist hier nicht möglich – bitte die Seite direkt im Browser öffnen."); } }, 50);
}
function bfPage(y0, y1) {   // y0/y1 in Koordinaten der Grafik (ohne Kopf)
  const L = BFL, body = $("bfsvg"), Hh = y1 - y0;
  const out = el("svg", { viewBox: `0 0 ${L.W} ${L.HT + Hh}`, class: "druckbild", xmlns: NS });
  for (const c of L.hs.childNodes) out.appendChild(c.cloneNode(true));
  const inner = el("svg", { x: 0, y: L.HT, width: L.W, height: Hh, viewBox: `0 ${y0} ${L.W} ${Hh}` }, out);
  for (const c of body.childNodes) { const k = c.cloneNode(true); if (k.classList) k.classList.remove("hl"); inner.appendChild(k); }
  return out;
}
function printBF(mode) {
  const L = BFL, wrap = h("div", null);
  if (mode === "view") {
    const y0 = L.box.scrollTop, y1 = y0 + L.box.clientHeight;
    const t0 = L.T0 + (y0 - L.MT) / L.PY, t1 = L.T0 + (y1 - L.MT) / L.PY;
    const pg = h("div", null, "druckseite"); pg.appendChild(printHeader(`Bildfahrplan ${fmt(t0)}–${fmt(t1)}`)); pg.appendChild(bfPage(y0, y1)); wrap.appendChild(pg);
  } else {
    // nur Stunden mit Zügen; Stunden je Seite so, dass A4 quer gefüllt ist (hängt vom Zeitmassstab ab)
    const ts = C.runs.flatMap(r => r.ev.map(e => timD(e))).filter(v => v != null);
    const a = Math.max(L.T0, Math.floor(Math.min(...ts) / 60) * 60), b = Math.min(L.T1, Math.ceil(Math.max(...ts) / 60) * 60);
    const per = Math.max(60, Math.floor(((L.W / 1.5 - L.HT) / L.PY) / 60) * 60);
    for (let t = a; t < b; t += per) { const u = Math.min(b, t + per);
      const pg = h("div", null, "druckseite"); pg.appendChild(printHeader(`Bildfahrplan ${fmt(t)}–${fmt(u)}`));
      pg.appendChild(bfPage(L.MT + (t - L.T0) * L.PY - 4, L.MT + (u - L.T0) * L.PY + 4)); wrap.appendChild(pg); }
  }
  doPrint(wrap);
}
function printKB() {
  const wrap = h("div", null), pg = h("div", null, "druckseite");
  pg.appendChild(printHeader("Kursbuch")); const box = h("div", null); pg.appendChild(box); wrap.appendChild(pg);
  const keep = kbAll; kbAll = true; drawKB(box, 22); kbAll = keep;
  doPrint(wrap);
}

// ---------------- Kreuzungen ----------------
function drawKR() {
  const host = $("kr"); host.innerHTML = "";
  host.appendChild(h("h2", "Kreuzungen auf eingleisigen Abschnitten"));
  const R = Object.fromEntries(C.runs.map(r => [r.id, r]));
  const ms = C.meets.filter(m => m.single && on[R[m.up].series] && on[R[m.dn].series]).sort((a, b) => a.t - b.t);
  if (!ms.length) { host.appendChild(h("p", C.single.some(s => s.v === true) ? "Keine Kreuzungen im gewählten Angebot." : "Keine Abschnitte als eingleisig erkannt. Im Band über dem Bildfahrplan lässt sich ein Abschnitt antippen und als eingleisig markieren.", "note")); return; }
  const cls = v => v <= 2 ? "w-bad" : v <= 5 ? "w-warn" : "w-good";
  let html = "<div class='tblwrap'><table class='list' style='margin:4px 8px'><tr><th>Zeit</th><th>Ort</th><th>Zug →</th><th>Puffer</th><th>Zug ←</th><th>Puffer</th></tr>";
  for (const m of ms) { const u = R[m.up], d = R[m.dn];
    const ort = m.line ? `zwischen ${esc(C.stations[m.kk])} und ${esc(C.stations[m.kk + 1])} ✕` : esc(C.stations[m.k]);
    html += `<tr><td>${fmt(m.t)}</td><td>${ort}</td><td>${esc(u.name)}</td><td class="${m.line ? "" : cls(m.buf_up)}">${m.line ? "–" : Math.round(m.buf_up) + "′"}</td><td>${esc(d.name)}</td><td class="${m.line ? "" : cls(m.buf_dn)}">${m.line ? "–" : Math.round(m.buf_dn) + "′"}</td></tr>`; }
  host.appendChild(h("div", html + "</table></div>"));
  host.appendChild(h("p", "Puffer = Minuten, die der Gegenzug verspätet ankommen darf, bevor dieser Zug warten muss. ≤2′ rot, ≤5′ gelb. Ein-/Zweigleisigkeit aus dem Fahrplan geschätzt (Begegnung auf der Strecke ⇒ zweigleisig; nur Kreuzungen in Bahnhöfen ⇒ vermutlich eingleisig) oder von Hand gesetzt.", "note"));
}

// ---------------- Anschlüsse ----------------
let anStation = null;
function drawAN() {
  const host = $("an"); host.innerHTML = "";
  const hd = h("div", null); hd.style.cssText = "display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin:22px 0 6px";
  hd.appendChild(h("h2", "Anschlüsse")).style.margin = "0";
  const majors = C.ids.filter((s, i) => C.major.has(C.stations[i]));
  if (anStation == null || !C.ids.includes(anStation)) anStation = majors.find((s, i) => i > 0 && i < majors.length - 1) ?? majors[0];
  const sl = h("select", null); sl.className = "chip"; majors.forEach(s => { const o = h("option", esc(D.S[s].name)); o.value = s; if (s === anStation) o.selected = true; sl.appendChild(o); });
  sl.onchange = () => { anStation = +sl.value; drawAN(); }; hd.appendChild(sl); host.appendChild(hd);
  const MIN = 3, evs = stationEvents(anStation).filter(e => on[e.series] !== false);
  const dirs = [...new Set(evs.filter(e => e.next && e.dep != null).map(e => e.next))];
  const arrs = evs.filter(e => e.arr != null && e.prev);
  let html = "<div class='tblwrap'><table class='list' style='margin:4px 8px'><tr><th>an</th><th>Zug (von)</th>" + dirs.map(n => `<th>→ ${esc(n)}</th>`).join("") + "</tr>";
  for (const a of arrs) {
    html += `<tr><td>${fmt(a.arr)}</td><td>${esc(a.name)} <span class="muted">(${esc(a.von)})</span></td>`;
    for (const k of dirs) {
      if (a.prev === k) { html += `<td class="muted">·</td>`; continue; }
      if (a.next === k) { html += `<td class="muted">fährt weiter</td>`; continue; }
      const nx = evs.filter(e => e.next === k && e.dep != null && e.dep >= a.arr + MIN && e.key !== a.key).sort((x, y) => x.dep - y.dep)[0];
      const missed = evs.filter(e => e.next === k && e.dep != null && e.dep < a.arr + MIN && e.dep >= a.arr - 5 && e.key !== a.key).sort((x, y) => y.dep - x.dep)[0];
      if (!nx) { html += `<td class="muted">–</td>`; continue; }
      const w = Math.round(nx.dep - a.arr), c = w <= 10 ? "w-good" : w <= 20 ? "w-warn" : w <= 60 ? "w-bad" : "muted";
      html += `<td><span class="${c}">${w}′</span> ${fmt(nx.dep)} ${esc(nx.name)}${missed ? ` <span class="w-bad" title="knapp verpasst">⚠ ${fmt(missed.dep)}</span>` : ""}</td>`;
    }
    html += "</tr>";
  }
  host.appendChild(h("div", html + "</table></div>"));
  host.appendChild(h("p", `Erster Anschluss je nächstem Halt ab ${MIN}′ Umsteigezeit: grün ≤10′, gelb ≤20′, rot ≤60′, grau länger; · = zurück in Ankunftsrichtung; ⚠ = weniger als ${MIN}′ nach Ankunft (knapp verpasst). Alle Züge am Bahnhof, auch anderer Strecken.`, "note"));
}

// ---------------- Ablauf ----------------
function renderViews(scroll) { assignSeries(); legend(); drawBF(scroll); drawKB(); drawKR(); drawAN(); }
function recompute(scroll) {
  const t0 = performance.now();
  C = model();
  if (!C) { $("haupt").hidden = true; $("meldung").textContent = "Keine Fahrten gefunden, die diese Bahnhöfe verbinden. Versuche einen Bahnhof bei «Über»."; return; }
  $("haupt").hidden = false; sel = null;
  const d = state.date, wd = WD[new Date(d + "T12:00:00").getDay()];
  $("titel").textContent = `${D.S[state.a].name} → ${D.S[state.b].name}${state.via != null ? " über " + D.S[state.via].name : ""} · ${wd} ${dateDE(d)}`;
  let msg = `${C.runs.length} Fahrten auf ${Math.round(C.km[C.km.length - 1])} km`;
  if (C.cor.joined) msg += ` · zusammengesetzt über ${C.cor.joined.map(s => D.S[s].name).join(", ")}`;
  $("meldung").innerHTML = esc(msg);
  if (C.cor.variants.length) { const m = $("meldung"); m.appendChild(h("span", " · andere Wege: ", "muted"));
    C.cor.variants.forEach(([name, n]) => { const b = h("button", `über ${esc(name)} (${n})`, "chip"); b.onclick = () => { $("inV").value = name; go(); }; m.appendChild(b); }); }
  renderViews(scroll); showPanel(null); $("lupe").innerHTML = "";
  updateURL();
  console.debug("Modell", Math.round(performance.now() - t0), "ms");
}
function updateURL() {
  const p = new URLSearchParams(); p.set("von", D.S[state.a].name); p.set("nach", D.S[state.b].name);
  if (state.via != null) p.set("ueber", D.S[state.via].name); p.set("datum", state.date);
  const ov = Object.entries(state.single).map(([k, v]) => k + ":" + (v ? 1 : 2)).join(","); if (ov) p.set("gleise", ov);
  try { history.replaceState(null, "", "?" + p.toString()); } catch (e) { /* in eingebetteten Vorschauen nicht erlaubt */ }
}
function go() {
  const a = findStation($("inA").value), b = findStation($("inB").value), v = $("inV").value.trim() ? findStation($("inV").value) : null;
  if (a == null || b == null) { $("meldung").textContent = "Bahnhof nicht gefunden: " + (a == null ? $("inA").value : $("inB").value); return; }
  if ($("inV").value.trim() && v == null) { $("meldung").textContent = "Bahnhof nicht gefunden: " + $("inV").value; return; }
  if (a !== state.a || b !== state.b || v !== state.via) state.single = {};
  Object.assign(state, { a, b, via: v });
  $("inA").value = D.S[a].name; $("inB").value = D.S[b].name; if (v != null) $("inV").value = D.S[v].name;
  recompute(true);
}
function setDate(d) {
  if (d < D.meta.start) d = D.meta.start; if (d > D.meta.end) d = D.meta.end;
  state.date = d; $("inD").value = d; $("wtag").textContent = WD[new Date(d + "T12:00:00").getDay()];
  if (state.a != null) recompute(false);
}

(async function init() {
  try { await loadData(); } catch (e) { $("sub").textContent = "Fehler beim Laden: " + e.message; return; }
  buildNames();
  const m = D.meta;
  $("sub").innerHTML = `Bildfahrplan, Kursbuch, Kreuzungen, Knotenlupe und Anschlüsse für eine frei gewählte Strecke · Fahrplan ${dateDE(m.start)}–${dateDE(m.end)} (HRDF, opentransportdata.swiss) · Stand ${esc(m.erzeugt)}`;
  $("inD").min = m.start; $("inD").max = m.end;
  $("wahl").addEventListener("submit", e => { e.preventDefault(); go(); });
  $("tausch").onclick = () => { const x = $("inA").value; $("inA").value = $("inB").value; $("inB").value = x; if (state.a != null) go(); };
  $("inD").onchange = () => setDate($("inD").value);
  $("dPrev").onclick = () => setDate(addDays(state.date, -1));
  $("dNext").onclick = () => setDate(addDays(state.date, 1));
  $("dHeute").onclick = () => setDate(new Date().toISOString().slice(0, 10));
  $("note").innerHTML = "Quelle: HRDF (opentransportdata.swiss), aufbereitet mit VXstone/NGE-fahrplan. Enthält alle Bahnfahrten der Schweizer Fahrplandaten, auch grenznahe Strecken im Ausland. Kilometer: Luftlinie zwischen aufeinanderfolgenden Halte- und Durchfahrtspunkten. Durchfahrtszeiten ohne Angabe linear geschätzt. Durchbindungen nach gleicher Zugnummer; Wenden (↺) sind Vermutungen.";
  const p = new URLSearchParams(location.search);
  let d = p.get("datum") || new Date().toISOString().slice(0, 10);
  if (d < m.start || d > m.end) d = m.start > d ? m.start : m.end;
  state.date = d; $("inD").value = d; $("wtag").textContent = WD[new Date(d + "T12:00:00").getDay()];
  if (p.get("gleise")) p.get("gleise").split(",").forEach(x => { const [k, v] = x.split(":"); state.single[k] = v === "1"; });
  if (!(p.get("von") && p.get("nach"))) { const m = $("meldung"); m.appendChild(h("span", "Beispiele: ", "muted"));
    [["Andelot", "Saint-Claude"], ["Neuchâtel", "Frasne"], ["Biel/Bienne", "Moutier"], ["Bern", "Thun"]].forEach(([x, y]) => { const b = h("button", esc(x + " – " + y), "chip"); b.onclick = () => { $("inA").value = x; $("inB").value = y; $("inV").value = ""; go(); }; m.appendChild(b); }); }
  if (p.get("von") && p.get("nach")) { $("inA").value = p.get("von"); $("inB").value = p.get("nach"); $("inV").value = p.get("ueber") || ""; const keep = { ...state.single }; go(); if (Object.keys(keep).length) { state.single = keep; recompute(false); } }
})();
