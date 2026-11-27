# fahrplan-verstehen

**Eine Bahnstrecke schnell verstehen:** zwei Bahnhöfe (optional «über») und ein Datum wählen,
dann zeigt die Seite für diesen Tag:

- **Bildfahrplan** (Weg-Zeit-Diagramm): Strecke waagrecht nach km, Zeit nach unten, jeder Zug eine Linie.
  Weiterfahrt auf anderen Strecken kurz verlängert und punktiert, vermutete Wenden mit ↺,
  Züge, die die Strecke nur in einem Bahnhof berühren, als Stummel.
- **Knotenlupe**: einen Halt antippen → alle Züge am Bahnhof ±40 min mit Aufenthalt und Anschlüssen.
- **Kursbuch** beider Richtungen (an/ab, „|“ Durchfahrt, Striche für Beginn/Ende, ↑/↓ andere Strecke).
- **Kreuzungen** auf eingleisigen Abschnitten mit Puffer je Richtung.
- **Anschlüsse** an einem wählbaren Bahnhof.
- **Publikation / Vergleich**: Umschalter neben dem Datum. «Publikation» zeigt den publizierten Fahrplan aus den
  grafischen Fahrplänen der SBB (mit **Güterzügen** und Lok-/Leerfahrten) für den Wochentag des gewählten Datums.
  «Vergleich» legt den Tagesfahrplan (HRDF) über die Publikation: wie publiziert, abweichend (> 3′),
  publiziert aber heute nicht, heute zusätzlich – mit Liste.

Seite: GitHub Pages dieses Repos. Alles läuft im Browser, ohne Server.

Übergabe für die Weiterarbeit (Arbeitsweise, Datenkette, Fallstricke, offene Schritte):
[UEBERGABE.md in VXstone/NGE-fahrplan](https://github.com/VXstone/NGE-fahrplan/blob/main/UEBERGABE.md).

## Daten

Der Workflow `Daten und Seite` (mittwochs und samstags, auf Knopfdruck und bei jedem Push auf `main`)

1. holt mit [VXstone/NGE-fahrplan](https://github.com/VXstone/NGE-fahrplan) die HRDF von
   [opentransportdata.swiss](https://opentransportdata.swiss) und schneidet alle Bahnfahrten des Fahrplanjahres heraus,
2. baut mit `tools/build_data.py` die kompakte Jahresdatei `web/data/fahrplan.json.gz` (mit Verkehrstagen),
3. legt sie zusätzlich ins Release `daten` und veröffentlicht `web/` auf GitHub Pages.

### Publikation `publikation.json.gz`

`tools/build_pub.py` nimmt die aus den grafischen Fahrplänen ausgelesenen Züge
(Release `grafapla-<Jahr>` von VXstone/NGE-fahrplan, Datei `grafapla_<Jahr>_zuege.json.gz`),
verbindet die Stücke je Zugnummer über die Fahrplanfelder und verwirft Reisezug-Stücke, deren Nummer
laut HRDF anderswo fährt (Fehllesungen). Wo sich Felder überlappen, wird jeder Betriebspunkt nur einmal
übernommen: gleiche Zeiten zusammengelegt, Ankunft (Stückende) + Abfahrt (Stückanfang) zu einem Halt,
bei Widerspruch gilt die Zeit, die die meisten Felder zeigen, sonst die des Stücks, das weiter innen liegt
(`meta.ueberlappung` zählt das). Format: `{meta, st_add, tr: [[zugnr, kat R|G|L, felder, vp, [station, an, ab, durchfahrt, …]]]}`;
`st_add` wird an `st` angehängt. Verkehrsperioden nach der Zeichenerklärung der SBB (`15` = Mo–Fr, `269` = Werktage Di–Sa,
`+` = Folgetag, `*` = zeitweise); eidg. Feiertage zählen als Sonntag.

### Güterzug-Liste `gueterzuege.json` / `.csv` / `.xlsx`

`tools/gz_list.py` macht aus der Publikation eine Liste aller Güterzüge (G 4xxxx–6xxxx, RhB G) mit
Verkehrstagen Mo–So, Musterklasse (täglich, werktags, Wochenende, teilweise, einzelne Tage), Alpenachse,
Von/Ab/Nach/An, Hauptknoten und Fahrplanfeldern: Teilstücke einer Nummer verkettet, Varianten ±10′ zusammengefasst.
Die Spalten entsprechen dem Blatt «Güterzüge» der Güterzug-Tabelle; die Regeln stehen im Kopf des Skripts.
Der Workflow legt die drei Dateien ins Release `daten`. Lokal:
`python tools/gz_list.py --pub web/data/publikation.json.gz --fahrplan web/data/fahrplan.json.gz --nge ../NGE-fahrplan --out web/data`

### Gleiszahlen `gleise.json`, Prüfliste `gueterabschnitte.csv`

`tools/build_gleise.py` übernimmt die Gleiszahl je Abschnitt aus [VXstone/topo-daten](https://github.com/VXstone/topo-daten)
(nur lesen; Regionstopologien `<region>_region_topologie.json` aus `spurplan/werkstatt/` und dem Ast `ergebnisse`).
Betriebspunkte der Topologie werden über den Namen, sonst über die Lage (≤ 300 m nach Einpassung) den Stationen
zugeordnet; je Stationspaar `ab["uicA-uicB"] = [min, max, Länge m, Region]`. Die Seite nimmt diese Zahl vor der
Schätzung (teilweise eingleisig ⇒ eingleisig). Abschnitte ausserhalb der Regionen bleiben geschätzt.
`gueterabschnitte.csv`: alle von Güterzügen befahrenen Abschnitte der Publikation mit Fahrten und ob topo-daten sie
kennt – Prüfliste für topo-daten (fehlende Verbindungen, reine Güterabschnitte), hier keine Eingabe. Lokal:
`python tools/build_gleise.py --topo <ordner> --fahrplan web/data/fahrplan.json.gz --pub web/data/publikation.json.gz --out web/data`

### Datenformat `fahrplan.json.gz`

```
{ "meta": {start, end, offset, hrdf, erzeugt, lauf},
  "st": [[uic, name, lat, lon, kürzel], …],
  "bf": {bitfeldnummer: hex, …},                 // Verkehrstage; Bit i = Tag (i - offset) ab start
  "tr": [[fnr, verwaltung, gattung, linie, bitfeld, [station, an, ab, durchfahrt, …]], …],
  "dw"/"dws"/"dwx"/"dwf": [[u, v, [zwischenpunkte], [zeitanteile 0..1]], …],   // vermutete Durchfahrten (tools/durchfahrt.py)
  "schmal": [fahrtindex, …], "nur_schmal"/"nur_normal": [station, …] }
```

Zeiten in Minuten ab Mitternacht (Folgetag > 1440), Station als Index in `st`.

## Was geschätzt ist

- **Kilometer**: Luftlinie zwischen aufeinanderfolgenden Halte- und Durchfahrtspunkten (geplant: Gleisgeometrie aus VXstone/topo-daten).
- **Ein-/Zweigleisigkeit**: aus topo-daten, wo eine Regionstopologie besteht (Band dunkel); sonst aus dem Fahrplan geschätzt (Begegnung auf der Strecke ⇒ zweigleisig, nur Kreuzungen in Bahnhöfen ⇒ vermutlich eingleisig; Band grau); im Band über dem Diagramm von Hand änderbar.
- **Durchfahrtszeiten** ohne Angabe linear nach km.
- **Weg von Zügen ohne Zwischenpunkte**: Die HRDF führt viele Schnellzüge nur mit ihren Halten (IC Bern–Thun ohne Münsingen).
  `tools/durchfahrt.py` sucht für jedes Punktpaar den schnellsten Weg im Gleisnetz von [VXstone/topo-daten](https://github.com/VXstone/topo-daten)
  (OSM-Extrakt `schweiz_bahn.json.gz`, Gewicht Länge/maxspeed, Normal- und Schmalspur getrennt, `tools/topo_wege.py`) und nimmt die
  Betriebspunkte am Weg als Durchfahrt: sicher bis 35 m vom Weg, bis 120 m nur mit Fahrplanverbindung zum Nachbarpunkt
  (Frutigen am Basistunnel ja, Roggwil-Wynau neben der Neubaustrecke nein); virtuelle Punkte (Bahn-2000-Strecke, Basistunnel) nicht.
  Paare ausserhalb des Netzes (Ausland) über den Fahrplangraph (schnellster Weg über Abschnitte mit Zwischenpunkten).
  Die Tabellen `dw` (Normalspur), `dws` (Schmalspur), `dwf` (Fahrplangraph) liegen in `fahrplan.json.gz`, dazu `schmal` (Fahrten)
  und `nur_schmal`/`nur_normal` (Betriebspunkte); die Seite fügt die Punkte beim Laden ein (im Zugfeld mit ~).
  Ein im Netz geprüfter Abschnitt ohne Zwischenpunkt heisst: der Zug fährt an keinem anderen Bahnhof vorbei – er wird nicht auf eine
  Strecke gelegt, die dazwischen Bahnhöfe desselben Netzes hat (Rothrist–Olten durch den Born, nicht über Aarburg-Oftringen).
  Spurweite je Fahrt nach den Abschnitten, die nur in einem Netz liegen (AsM Langenthal–St. Urban neben der Neubaustrecke),
  Betriebspunkte gehören zu den Netzen der Fahrten, die sie führen.
  Fernverkehr (IC, IR, EC, ICE …, Tabelle `dwx`): Bahnhöfe, die keine 10 Fernverkehrsfahrten führen, kosten 4 Minuten Zuschlag –
  ein IC ohne Halt Zürich HB–Winterthur fährt über Oerlikon–Wallisellen, nicht über Stadelhofen–Stettbach.
  Grenzen: wo zwei Wege ähnlich schnell sind, entscheidet maxspeed aus OSM; Betriebspunkte, an denen ein
  parallel geführtes Gleis eines anderen Netzes vorbeiführt, können fälschlich als Durchfahrt erscheinen.
- **Strecke**: Folgen mit Zickzack (S1 früh Bern–Wankdorf–Zollikofen–Ostermundigen) werden nicht zur Basis der Strecke, sondern als «über …» angeboten.
- **Durchbindungen** nach gleicher Zugnummer; **Wenden** (↺) sind Vermutungen (gleiche Linie, 3–45′).

## Lokal ausprobieren

```
curl -L -o web/data/fahrplan.json.gz https://github.com/VXstone/fahrplan-verstehen/releases/download/daten/fahrplan.json.gz
cd web && python3 -m http.server
```

## Lizenzen

Code: MIT. Fahrplandaten: opentransportdata.swiss (Nutzungsbedingungen der Plattform).
Publikation/Güterzüge: aus den grafischen Fahrplänen, veröffentlicht von der Systemaufgabe Kundeninformation (SKI)
auf [oev-info.ch](https://www.oev-info.ch/de/fahrplan-aktuell/grafische-fahrplaene), erstellt von SBB Infrastruktur
(Fahrplan & Netzdesign) bzw. den jeweiligen Bahnen. **Die Lizenz bzw. die Nutzungsbedingungen für die Weiterverwendung sind
ungeklärt**; die Daten sind automatisch ausgelesen und ohne Gewähr.
Gleiszahlen: VXstone/topo-daten, Daten © OpenStreetMap-Mitwirkende, ODbL.
