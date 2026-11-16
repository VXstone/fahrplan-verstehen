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

Seite: GitHub Pages dieses Repos. Alles läuft im Browser, ohne Server.

## Daten

Der Workflow `Daten und Seite` (mittwochs und samstags, auf Knopfdruck und bei jedem Push auf `main`)

1. holt mit [VXstone/NGE-fahrplan](https://github.com/VXstone/NGE-fahrplan) die HRDF von
   [opentransportdata.swiss](https://opentransportdata.swiss) und schneidet alle Bahnfahrten des Fahrplanjahres heraus,
2. baut mit `tools/build_data.py` die kompakte Jahresdatei `web/data/fahrplan.json.gz` (mit Verkehrstagen),
3. legt sie zusätzlich ins Release `daten` und veröffentlicht `web/` auf GitHub Pages.

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
