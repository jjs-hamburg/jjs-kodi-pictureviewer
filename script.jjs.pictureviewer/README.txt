JJS Kodi Picture Viewer 0.1.43
- Sichtbarer Add-on-Name auf "JJS Kodi Picture Viewer" vereinheitlicht; Add-on-ID script.jjs.pictureviewer bleibt unveraendert.
- Play/Pause/Stop werden vom Picture Viewer nicht mehr abgefangen. Die Diashow wird ausschliesslich mit Hoch (Start/Pause/Fortsetzen) und Runter (Stop) gesteuert, damit Media-Tasten der normalen Kodi-Musikwiedergabe gehoeren.
- Beim ersten Start nach dem Update werden die von 0.1.28-0.1.42 angelegten JJS-Media-Keymaps zz_jjs_pictureviewer.xml und zzz_jjs_pictureviewer_active.xml geloescht und Kodis Keymaps neu geladen.
- Rendering, Prefetch, Uebergaenge und der 0.1.42-Deadlock-Fix bleiben unveraendert.

JJS Picture Viewer 0.1.42
- Deadlock-Fix fuer sporadisch dauerhaft leere Bildflaechen: Die Diaprojektor-Bereinigung fuehrt keine synchronen SetProperty(..., wait=True)-Aufrufe mehr aus dem Timerthread aus. Der Hintergrundthread stellt nur noch eine interne GUI-Action zu; JJSPhotoLayer/JJSProjectorActive/JJSTransitionMode werden anschliessend im normalen WindowXML-onAction-Thread bereinigt. Eine Transition-Seriennummer verhindert, dass eine verspätete Cleanup-Action eine neuere Animation beendet.
- Die in 0.1.41 verwendeten normalen Texture-Loader fuer die vier dynamischen Foto-/Projektor-Flaechen bleiben unveraendert.

JJS Picture Viewer 0.1.41
- Fix fuer dauerhaft leere Bildflaeche auf Android/Shield: background=true wurde nur bei den vier dynamischen Foto-/Projektor-Controls 1005/1007/1008/1009 entfernt. Das Hintergrund-Control 1002 bleibt unveraendert. Rendering, Prefetch, Bad-Image-Watchdog und setImage(..., useCache=False) bleiben wie in 0.1.40.

0.1.39
- Stabilitaetsfix fuer sporadisch leere Bildflaechen: Die vier eigentlichen Foto-/Projektor-Controls laden die gerenderten 1920x1080-Bilder jetzt mit Kodis Large-Texture-Loader (background=true) statt synchron ueber den normalen Texture-Loader. Prefetch, Rendering und Bedienlogik bleiben unveraendert.

0.1.38
- Stabilitaets-Rebase auf der vom Nutzer als stabil bestaetigten 0.1.30-songchange-prefetch-fix. Die spaeter gewuenschten Funktionen (Hoch/Runter Diashow, Statussymbole, Freund-Defaults, PictureViewer-Default-Hintergrund) wurden gezielt wieder aufgesetzt.
- Wichtiger Fix: Das zeitgesteuerte Ausblenden des Play/Stop-Symbols wartet aus dem Hintergrundthread nicht mehr synchron auf Kodis GUI-Thread. Dadurch kann der Timerthread nicht mehr an ClearProperty(..., wait=True) haengen und den Projektor-Zustand blockieren.

0.1.37
- Hintergrund-Dialog um „PictureViewer Default“ erweitert. Das mitgelieferte defaultBackground.jpg ist damit nach einer eigenen Bildwahl jederzeit wieder anwählbar.

JJS Picture Viewer 0.1.35

- Startet das originale Kodi-Fenster "Bilder" (Confluence MyPics.xml).
- Ordner-/Dateiauswahl, Ansichten und Seitenmenü sind deshalb unverändert Kodi/Confluence.
- Ein Bildklick in der JJS-Bildquelle startet direkt den JJS Viewer; Kodis Slideshow-Viewer wird nicht gestartet.
- Der JJS Viewer lädt jeweils nur das aktuelle Bild; kein Bilder-Preloading.
- Links/Rechts: +/- 1 Bild.
- Hoch: Diashow starten / pausieren / fortsetzen.
- Runter: Diashow stoppen.
- OK/Context: Seitenmenü mit echten Kodi-XML-Buttons im Confluence-Stil.
- Back: zurück in die originale Bilderliste.
- Galerie/Vollbild, Hintergrund, weißer Rand und Schatten.
- 1920x1080 XML-Koordinatensystem; Kodi skaliert auf die physische Ausgabe.

0.1.5: zirkulaere Bildnavigation; natives WindowXML-Menue ohne doppelte Action-Verarbeitung; SideBladeLeft-Geometrie und Confluence-Texturen; staerkerer 9-Slice-Schatten.

0.1.7: EXIF-Orientierung wird bei der Rahmengeometrie berücksichtigt; Bildwechsel leert die Foto-Textur nicht mehr, Kodi hält das vorige Bild bis das neue geladen ist.


0.1.8: Schatten-Alpha beim 9-Slice-Aufbau und beim Compositing nicht mehr mehrfach multipliziert; atomarer Bild/Rahmen-Wechsel aus 0.1.7 bleibt unverändert.


0.1.10: Ein-Bild-Vorladen zur Beschleunigung, JPEG-Draft-Decoding, Diashow (Play Start/Stop, Intervall im Seitenmenü).


0.1.15: Ressourcen-/Lifecycle-Fix auf Basis 0.1.10; Prefetch sauber abbrechbar, Threads beim Schließen beendet, keine VFS-Quelldatei-Staging-Reste.

0.1.18: Übergänge neu als stabile A/B-Bildlayer im XML; keine setVisible-/Runtime-Animations-Tricks. Wählbar: Aus, Überblenden, sanftes Zoom, Einschieben. Ressourcen-Lifecycle aus 0.1.15 unverändert.


0.1.20: Diaprojektor stabilisiert: A/B-Dauerlayer bleiben neutral; separate Ghost-Layer schieben nur das alte Bild heraus. Keine Hidden-Schiebeanimation mehr auf den eigentlichen Bildlayern.

0.1.20: Schnellere Erstanzeige: Wiederverwendung der bereits im Kodi-Bilderbrowser gelesenen/sortierten Bildliste; kein doppelter NAS-Ordnerscan beim Bildklick. VFS-Bildleseblöcke auf 4 MiB vergrößert, Abbruchprüfung bleibt erhalten.

0.1.22: PLAY startet/fortsetzt Diashow; PAUSE pausiert/fortsetzt; STOP beendet; Cursor kehrt beim Schliessen zum zuletzt angezeigten Bild zurueck.

0.1.22: Shield Play/Pause Toggle; Stop trennt automatische NextPicture-Schritte von manueller Navigation und neutralisiert Übergänge; Cursor-Rücksprung über exakten JJSRealPath statt Positionsarithmetik.

0.1.25: Diaprojektor-Ghost-Zuordnung korrigiert (A/B ueber Kreuz) und automatische Transition-Bereinigung direkt nach Ablauf der Animation; verhindert Querformat-Ghost hinter Hochformatbildern.


0.1.26
- Diaprojektor: ausgehender Overlay-Layer hat richtungsabhaengige Offscreen-Grundposition; kein Zurueckspringen nach Animationsende.
- Rueckwaertsanimation spiegelbildlich stabilisiert.
- Bilderliste: echter Bildpfad nicht mehr als ListItem.Path; Play in der Dateiliste startet keine native Wiedergabe/Schwarzbild mehr.

0.1.29: Harte Media-Key-Kontexttrennung: Pictures steuert nur aktiven Audioplayer; der Viewer installiert fuer seine konkrete Dialog-ID eine temporaere Keymap und wandelt Play/Pause/Stop in viewer-eigene Number-Actions um. Kein Player-Action-Pfad im Viewer.
0.1.28: Media-Key-Relay: Pictures-Liste toggelt nur aktiven Audioplayer per JSON-RPC; im JJS Viewer steuern Play/Pause/Stop ausschließlich die Diashow. Kein Play des markierten Bild-Pluginitems mehr.


0.1.30: Songwechsel-/Prefetch-Fix: Vorwaertsnavigation wartet nicht mehr bis zu 60 Sekunden synchron auf ein laufendes VFS-Prefetch. Ist das Vorladen beim Kodi-Audio-Trackwechsel kurz blockiert, bleibt die Viewer-GUI frei; genau ein wartender +1-Schritt wird nach Ende des Prefetch automatisch nachgeholt.


0.1.31: Freund-/Neuinstallations-Defaults: mitgeliefertes blaues Hintergrundbild; Galerie 85 %; weisser Rand 10 px; Schatten 24 px / Versatz 30 px / Staerke 90 %; Diashow 5 s; Folgebild vorladen; Diaprojektor 700 ms. Bestehende gespeicherte Einstellungen werden nicht ueberschrieben.


0.1.35: Korrigierte Hauptlinie auf Basis 0.1.31. Hoch = Diashow Start/Pause/Fortsetzen, Runter = Stop; Links/Rechts bleiben +/- 1 Bild. Die versehentlich wieder hineingeratene alte Sprungweiten-Funktion wurde aus Code, Seitenmenue und gespeicherten Settings entfernt. Prefetch-Fix und Neuinstallations-Defaults aus 0.1.30/0.1.31 bleiben unveraendert.

0.1.36: Diashow-Statusanzeige aus dem frueheren korrekten 0.1.30-Zweig wiederhergestellt: Play erscheint 2 s beim Start/Fortsetzen, Pause bleibt waehrend der gesamten Pause sichtbar; Stop erscheint neu ebenfalls 2 s. Bedienlogik und Prefetch-Fix aus 0.1.35 bleiben unveraendert.


0.1.40: Defektbild-Schutz: Decode-/Lesefehler werden für die laufende Viewer-Sitzung markiert und bei Links/Rechts automatisch übersprungen. Ein festhängendes Folgebild-Prefetch wird nach 12 s als defekt behandelt; ein wartender Vorwärtsschritt wird auf das nächste verwendbare Bild weitergeleitet. Solange der festhängende Worker noch lebt, bleibt Prefetch deaktiviert, damit sich keine blockierten Worker ansammeln; nach seinem Ende wird Vorladen automatisch wieder freigegeben. 0.1.39 Large-Texture-Lader bleibt unverändert.
