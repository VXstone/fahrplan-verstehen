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

### Datenformat `fahrplan.json.gz`

```
{ "meta": {start, end, offset, hrdf, erzeugt, lauf},
  "st": [[uic, name, lat, lon, kürzel], …],
  "bf": {bitfeldnummer: hex, …},                 // Verkehrstage; Bit i = Tag (i - offset) ab start
  "tr": [[fnr, verwaltung, gattung, linie, bitfeld, [station, an, ab, durchfahrt, …]], …] }
```

Zeiten in Minuten ab Mitternacht (Folgetag > 1440), Station als Index in `st`.

## Was geschätzt ist

- **Kilometer**: Luftlinie zwischen aufeinanderfolgenden Halte- und Durchfahrtspunkten (geplant: Gleisgeometrie aus VXstone/topo-daten).
- **Ein-/Zweigleisigkeit**: aus dem Fahrplan geschätzt (Begegnung auf der Strecke ⇒ zweigleisig, nur Kreuzungen in Bahnhöfen ⇒ vermutlich eingleisig); im Band über dem Diagramm von Hand änderbar.
- **Durchfahrtszeiten** ohne Angabe linear nach km.
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
