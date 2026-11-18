# Checkliste vor dem Dreh

CSC und Build sind noch unbekannt. In diesem Ordner liegt keine Firmware, und sie wird von hier aus nicht geladen. Zuerst am Handy ablesen, dann die passende Firmware für SM-A146P plus diese CSC auf den PC legen. Das passiert, bevor der Bootloader aufgeht, damit ein Bootloop im Video rettbar ist.

## PC

- [ ] Samsung-USB-Treiber installiert
- [ ] Odin 3.14.1 aus dem XDA-Thread „Patched Odin“. Die im Netz kursierende „Odin 3.14.4“ weglassen
- [ ] Frija, Bifrost oder SamFw bereit
- [ ] Datenkabel, kein reines Ladekabel
- [ ] scrcpy installiert (`winget install --id Genymobile.scrcpy -e`)
- [ ] USB-Debugging an. Nach dem Einstecken den Dialog mit **Immer von diesem Computer zulassen** bestätigen. USB-Modus: Dateiübertragung
- [ ] Kurztest ohne Datei: `.\record-display.ps1 -NurAnzeigen`. Das Display steht im Fenster, bevor eine Aufnahme startet
- [ ] Aufnahme ohne Ton, ein Kapitel pro Datei: `.\record-display.ps1 -Kapitel modell`. Stoppen mit Strg+C
- [ ] Zweite Kamera für Download-Modus und Odin. Vorher das scrcpy-Fenster schließen. scrcpy und Odin teilen sich den USB-Anschluss, und im Download-Modus gibt es kein USB-Debugging

## Handy

Bevor irgendetwas gelöscht wird:

- [ ] Einstellungen, Telefoninfo: Modell ist `SM-A146P`. `/DSN` ist nur die Dual-SIM-Verkaufsvariante
- [ ] Build-Nummer abgelesen, zum Beispiel `A146PXX...`
- [ ] Android-Version abgelesen. Aktueller Stand dieses Modells ist Android 15 / One UI 7
- [ ] RAM und Speicher abgelesen
- [ ] Einstellungen, Telefoninfo, Softwareinformationen, Dienstanbieter-SW-Version. Die CSC aus der Zeile notiert, oft der dritte Code, zum Beispiel `DBT` oder `EUX`
- [ ] Bildschirmsperre entfernt
- [ ] Fotos und Konten gesichert. Das Google-Konto für die FRP-Anmeldung nach dem Wipe bereithalten

Das A146P hat den MediaTek Dimensity 700, nicht den Exynos 1330. Samsung hat kein Fastboot. Geflasht wird nur mit Odin. Fertige Root-TARs und mtkclient bleiben draußen: auf diesem Gerät ist dabei schon die Baseband und die IMEI verloren gegangen.

## Firmware-Dateien

Die Build auf dem PC muss zur Build auf dem Handy passen oder neuer sein. Ein Downgrade unter die aktuelle Binary schlägt fehl. Magisk kommt nur von [github.com/topjohnwu/Magisk](https://github.com/topjohnwu/Magisk). Gepatcht wird die eigene AP.

- [ ] `BL`
- [ ] `AP` (`AP_...tar.md5`, mehrere GB, freier Speicher auf dem Handy vorher prüfen)
- [ ] `CP`
- [ ] `CSC` (`CSC_...`)

`HOME_CSC` wird für diesen Lauf nicht verwendet.

In Odin ist Auto Reboot aus. Nach `PASS` direkt ins Recovery und dort Factory data reset, danach Reboot system now.

## Unkenntlich vor der Veröffentlichung

- [ ] Seriennummer
- [ ] IMEI
- [ ] Google-Konto
- [ ] WLAN-Name
- [ ] Volle lokale IP in den Einstellungsseiten
- [ ] COM-Nummer in Odin
- [ ] Öffentliche Tailscale-Adresse

## Wenn eine Szene scheitert

- OEM-Schalter fehlt oder `KG STATE: Prenormal`: Aufnahme beenden. Warten, bis das Gerät nach einer WLAN-Verbindung `Checking` oder entsperrbar zeigt. Kein Workaround, kein anderes Tool.
- Odin `FAIL` oder Bootloop: die originalen BL, AP, CP und CSC flashen, Auto Reboot aus, danach der Recovery-Wipe. Nichts weiter ausprobieren.
- Magisk ist nach dem Neustart leer: App öffnen, die angebotene Zusatz-Einrichtung bestätigen, neu starten.
- Nginx oder Glances sind nur auf dem Handy erreichbar: den Dienst an `0.0.0.0` binden, nicht an `127.0.0.1`. Gäste-WLAN und AP-Isolation im Router sind die andere häufige Ursache.
- Das Handy wird im Test heiß: den Dienst stoppen. Das gehört als Satz ins Video.
