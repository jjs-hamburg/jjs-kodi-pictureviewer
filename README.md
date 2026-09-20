# JJS Picture Viewer

**Aktueller Referenzstand: 0.1.42**

JJS Picture Viewer ist ein schneller, fernbedienungstauglicher Bildbetrachter für Kodi. Er benutzt zum Browsen weiterhin Kodis normales **Bilder-Fenster**, öffnet ein ausgewähltes Bild aber in einem eigenen Viewer. Dadurch wird nicht Kodis native Slideshow gestartet und der Ordner wird beim Öffnen eines Bildes nicht komplett vorgeladen.

Der Viewer ist auf große Bildordner und Netzwerkquellen ausgelegt, zeigt immer nur das aktuelle Bild an und kann optional genau **ein Folgebild vorladen**. Galerie- und Vollbilddarstellung, Diashow, Hintergrund, weißer Rand, Schatten und mehrere Übergänge lassen sich direkt im linken Seitenmenü einstellen.

## Installation

Das installierbare Kodi-ZIP wird über GitHub Actions aus dem Quellstand dieses Repositories erzeugt.

1. In GitHub **Actions → Build Kodi add-on ZIP** öffnen.
2. Einen erfolgreichen Build auswählen.
3. Das Artifact `script.jjs.pictureviewer-<Version>` herunterladen.
4. In Kodi **Add-ons → Aus ZIP-Datei installieren** wählen und das erzeugte ZIP installieren.

Das Add-on benötigt Kodi mit Python 3 (`xbmc.python >= 3.0.0`) und das Kodi-Modul `script.module.pil >= 5.1.0`. Beide Abhängigkeiten sind in `addon.xml` deklariert.

## Start und Bildauswahl

Beim normalen Start aktiviert JJS Picture Viewer Kodis originales **Bilder-Fenster** und stellt dort eine JJS-Bildquelle bereit. Die oberste Ebene zeigt die in Kodi eingerichteten Bildquellen. Ordner und Bilder werden im normalen Kodi-Bilderbrowser angezeigt und können wie gewohnt mit der eingestellten Ansicht und dem Kodi-Seitenmenü durchsucht werden.

Ein Klick auf ein Bild startet direkt den JJS Viewer. Kodis natives Slideshow-Fenster wird dabei nicht geöffnet.

Unterstützte Dateiendungen:

`.jpg`, `.jpeg`, `.png`, `.webp`, `.bmp`, `.gif`, `.tif`, `.tiff`

Die zuletzt im Kodi-Bilderfenster gelistete und sortierte Bildliste wird zwischengespeichert. Wird unmittelbar danach ein Bild geöffnet, kann der Viewer diese Liste wiederverwenden und muss einen großen NAS-/SMB-/NFS-Ordner nicht ein zweites Mal einlesen. Der Listen-Cache ist maximal 30 Minuten gültig.

Beim Verlassen des Viewers wird der Cursor im Kodi-Bilderfenster auf das **zuletzt tatsächlich angezeigte Bild** zurückgesetzt. Dafür wird der exakte Bildpfad verwendet, nicht eine berechnete Listenposition.

## Bedienung im Viewer

| Taste / Aktion | Funktion |
| --- | --- |
| **Links** | Vorheriges Bild |
| **Rechts** | Nächstes Bild |
| **Hoch** | Diashow starten; bei laufender Diashow Pause/Fortsetzen |
| **Runter** | Diashow stoppen |
| **OK / Select** | Linkes Seitenmenü öffnen |
| **Context Menu** | Linkes Seitenmenü öffnen; bei geöffnetem Menü wieder schließen |
| **Back / Zurück** | Viewer schließen und in die Kodi-Bilderliste zurückkehren |
| **Play/Pause** | Wie Hoch: Start → Pause → Fortsetzen |
| **Pause** | Laufende Diashow pausieren bzw. fortsetzen; bei gestoppter Diashow ohne Wirkung |
| **Stop** | Diashow stoppen |

Links und Rechts bewegen sich immer um **genau ein Bild**. Die Navigation ist zirkulär: hinter dem letzten Bild folgt wieder das erste und vor dem ersten das letzte.

Die frühere Sprungweiten-Funktion existiert seit 0.1.35 nicht mehr. Hoch und Runter sind fest für die Diashow reserviert.

### Diashow-Statussymbole

Beim Starten oder Fortsetzen wird das Play-Symbol für etwa zwei Sekunden eingeblendet. Während einer Pause bleibt das Pause-Symbol sichtbar. Beim Stoppen erscheint das Stop-Symbol für etwa zwei Sekunden.

Pause und Stop brechen einen bereits laufenden Bildübergang nicht mitten in der Animation ab. Die laufende Animation wird sauber beendet; nur der automatische Bildwechsel wird angehalten.

## Seitenmenü und Einstellungen

Alle Viewer-Einstellungen liegen im linken Seitenmenü und werden dauerhaft in

`special://profile/addon_data/script.jjs.pictureviewer/viewer_settings.json`

gespeichert. Änderungen an Darstellung, Rand oder Schatten werden auf Basis des bereits dekodierten Bildes neu gerendert; das Originalbild muss dafür normalerweise nicht erneut vom NAS gelesen werden.

### Darstellung

| Option | Werte | Neuinstallations-Default | Bedeutung |
| --- | --- | --- | --- |
| **Darstellung** | Galerie / Vollbild | **Galerie** | Galerie zeigt das Bild vor einem wählbaren Hintergrund. Vollbild nutzt die gesamte 1920×1080-Viewerfläche unter Beibehaltung des Seitenverhältnisses und deaktiviert Rand/Schatten/Hintergrunddarstellung. |
| **Galeriegröße** | 60, 65, 70, 75, 80, 82, 85, 88, 90, 92, 95 % | **85 %** | Maximale Fläche für Bild plus Rand in der Galerieansicht. |
| **Hintergrund** | PictureViewer Default / Skin-Wallpaper / Schwarz / Eigenes Bild | **PictureViewer Default** | Hintergrund der Galerieansicht. |
| **Eigenes Hintergrundbild** | Bilddatei | mitgeliefertes Defaultbild | Wählt ein eigenes Hintergrundbild und schaltet automatisch auf „Eigenes Bild“. |

**PictureViewer Default** ist das mitgelieferte Hintergrundbild und kann jederzeit wieder ausgewählt werden. **Skin-Wallpaper** versucht das aktuelle Hintergrundbild des verwendeten Skins zu übernehmen; bei Confluence/Confluence Custom werden auch die dort verwendeten Custom-Background-Einstellungen berücksichtigt.

### Weißer Rand

| Option | Bereich | Default |
| --- | ---: | ---: |
| **Weißer Rand** | Ein / Aus | **Ein** |
| **Randbreite** | 0–100 px | **10 px** |

Der Rand wird nur in der Galerieansicht verwendet.

### Schatten

| Option | Bereich | Default |
| --- | ---: | ---: |
| **Schatten** | Ein / Aus | **Ein** |
| **Schattenbreite** | 0–150 px | **24 px** |
| **Schattenversatz** | 0–100 px | **30 px** |
| **Schattenstärke** | 0–100 % | **90 %** |

Auch der Schatten wird nur in der Galerieansicht verwendet.

### Diashow

| Option | Werte / Bereich | Default |
| --- | --- | --- |
| **Diashow** | Starten / Stoppen | gestoppt |
| **Diashow-Intervall** | 1–3600 s | **5 s** |
| **Nächstes Bild vorladen** | Ein / Aus | **Ein** |

Beim Starten oder Fortsetzen erhält das aktuell sichtbare Bild immer ein vollständiges neues Intervall.

Das Vorladen arbeitet im Hintergrund und betrifft höchstens das nächste Bild. Die Navigation wartet niemals synchron auf einen laufenden Prefetch. Falls das Vorladen eines Bildes festhängt, wird es nach **12 Sekunden** für die aktuelle Viewer-Sitzung als defekt behandelt. Solange der festhängende Worker noch lebt, wird weiteres Prefetching vorübergehend deaktiviert, damit keine blockierten Threads angesammelt werden.

Auch normale Lese- oder Dekodierfehler markieren ein Bild nur für die aktuelle Viewer-Sitzung als defekt. Bei Links/Rechts wird dann automatisch zum nächsten verwendbaren Bild weitergesprungen.

### Bildübergang

Verfügbare Übergänge:

- **Aus**
- **Überblenden**
- **Sanftes Zoom**
- **Einschieben**
- **Diaprojektor** — Default

Verfügbare Übergangsdauern:

`120`, `180`, `250`, `350`, `500`, `700`, `1000`, `1500 ms`

Neuinstallations-Default ist **Diaprojektor / 700 ms**.

Der Diaprojektor-Effekt verwendet getrennte Bild- und Ghost-Layer für ein stabiles Herausschieben des alten und Hereinschieben des neuen Bildes. Seit 0.1.42 wird die abschließende Transition-Bereinigung ausschließlich im WindowXML-GUI-Thread ausgeführt; damit wird der Deadlock vermieden, der zuvor sporadisch zu einer dauerhaft leeren Bildfläche führen konnte.

## Musik und Media-Tasten

JJS Picture Viewer trennt Bild- und Audio-Steuerung bewusst:

- **Im normalen Kodi-Bilderfenster** steuern Play/Pause/Stop ausschließlich einen bereits laufenden Audioplayer. Wenn keine Musik läuft, passiert nichts. Ein markiertes Bild wird dadurch niemals als generisches Playable gestartet.
- **Im JJS Viewer** steuern dieselben Media-Tasten ausschließlich die Diashow. Sie werden nicht an den Audioplayer weitergereicht; laufende Musik bleibt daher unbeeinflusst.

Dafür installiert das Add-on eine dauerhafte Pictures-Keymap und während des geöffneten Viewer-Dialogs zusätzlich eine temporäre, exakt an dessen Window-ID gebundene Keymap. Die temporäre Keymap wird beim Schließen wieder entfernt; eine nach einem Absturz übrig gebliebene Viewer-Keymap wird beim nächsten Start bereinigt.

## Performance und Stabilität

Der Viewer rendert die Fotos intern auf eine 1920×1080-Fläche. Kodi skaliert diese auf die tatsächliche Ausgabeauflösung. EXIF-Orientierung wird beim Dekodieren berücksichtigt.

Bereits dekodierte, EXIF-korrigierte Bilder werden während der Sitzung in einem kleinen RAM-Cache gehalten. Dadurch können Änderungen an Galeriegröße, Rand und Schatten ohne erneutes Lesen der Originaldatei dargestellt werden.

Die dynamischen Foto-/Projektor-Flächen laden die bereits lokal gerenderten PNGs über Kodis normalen Texture-Loader. Nur das Hintergrundbild verwendet den Large-Texture-Background-Loader.

Version 0.1.42 beseitigt den bislang kritischsten sporadischen Fehler: Die Diaprojektor-Bereinigung führt keine synchronen GUI-Property-Aufrufe mehr aus dem Timerthread aus. Stattdessen übergibt der Timer eine interne Action an den WindowXML-Thread; eine Transition-Seriennummer verhindert zusätzlich, dass eine verspätete Cleanup-Action eine neuere Animation beendet.

## Neuinstallations-Defaults

Eine frische Installation startet mit:

| Einstellung | Wert |
| --- | --- |
| Darstellung | Galerie |
| Galeriegröße | 85 % |
| Hintergrund | PictureViewer Default |
| Weißer Rand | Ein |
| Randbreite | 10 px |
| Schatten | Ein |
| Schattenbreite | 24 px |
| Schattenversatz | 30 px |
| Schattenstärke | 90 % |
| Diashow-Intervall | 5 s |
| Nächstes Bild vorladen | Ein |
| Übergang | Diaprojektor |
| Übergangsdauer | 700 ms |

Beim Update einer bestehenden Installation werden gespeicherte Benutzereinstellungen grundsätzlich beibehalten. Die Versionsmigrationen ändern nur Einstellungen, die für eine bestimmte alte Default-Konfiguration oder eine entfernte Funktion eindeutig identifiziert werden können.

## Projektstruktur

Der installierbare Add-on-Baum liegt vollständig unter:

`script.jjs.pictureviewer/`

Damit entspricht die Verzeichnisstruktur im Repository direkt der Struktur im Kodi-Installations-ZIP.

Wichtige Dateien:

- `addon.xml` — Add-on-ID, Version, Abhängigkeiten und Kodi-Metadaten
- `default.py` — Einstiegspunkt
- `resources/lib/viewer.py` — Browser-/Viewer-/Rendering-/Slideshow-Logik
- `resources/skins/Default/1080i/PictureViewer.xml` — WindowXML-Oberfläche und Übergangsanimationen
- `resources/media/` — Hintergrund und Medienressourcen
- `README.txt` — historische Versionsnotizen des Add-ons

## Build

Der Workflow `.github/workflows/build-addon.yml` prüft unter anderem:

- Add-on-ID und Versionsnummer aus `addon.xml`
- Python-Syntax
- Vorhandensein der erforderlichen Laufzeitdateien
- korrekte ZIP-Struktur mit `script.jjs.pictureviewer/` als oberstem Add-on-Ordner

Das erzeugte Artifact heißt:

`script.jjs.pictureviewer-<Version>`

und enthält das direkt in Kodi installierbare ZIP:

`script.jjs.pictureviewer-<Version>.zip`

## Versionshistorie

Die ursprüngliche, fortlaufend gepflegte technische Versionshistorie befindet sich unverändert in `script.jjs.pictureviewer/README.txt`.

Der aktuelle Referenzstand dieses Repositories ist **0.1.42 – projector deadlock fix**.
