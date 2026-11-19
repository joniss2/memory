# Checkliste vor dem Dreh

CSC und Build stehen noch nicht fest. Am USB hängt kein Samsung, `adb devices` ist leer, und Smartphone-Link hat kein Gerät. Zuerst das Kabel mit Dateiübertragung und USB-Debugging, dann `.\prep-geraet.ps1`. Die ausgegebene CSC gilt für Bifrost. Die Firmware für SM-A146P plus diese CSC kommt nach `firmware\`, bevor der Bootloader aufgeht, damit ein Bootloop im Video rettbar ist. Eine CSC nicht raten.

## PC

- [x] Samsung-USB-Treiber installiert. Das angeschlossene Gerät erscheint als `SAMSUNG Mobile USB Modem`, Treiberpaket `ssudadb` 2.21.4.0
- [x] Odin 3.14.1 aus dem XDA-Thread „Patched Odin“: `tools\odin-patched\extracted\Odin3 v3.14.1_3B_PatcheD.exe` (Produktversion 3.14.1.3B). In der danebenliegenden `Odin3.ini` steht Auto Reboot auf aus
- [x] Die Fassung `Downloads\Odin3_v3.14.4` nicht öffnen. Produktversion 3.14.4.0, dazu liegt `cpprest141_2_10.dll` im selben Ordner. Läuft sie schon, kein Start drücken und das Fenster schließen
- [x] Bifrost 2.1.4 unter `tools\bifrost\bin\Bifrost.exe`. Firmware erst laden, wenn `prep-geraet.ps1` die CSC ausgibt
- [x] `tools\Magisk-v31.1.apk` ist die Release von topjohnwu. SHA-256 `89cefac0a318afa39fb3880c45c87b036c05bc1ebf02a7a715b7f8d7c26ac6e7`, Größe 10679283 Byte. Magisk 31.1 zeigt beim ersten `su` keinen Dialog. Die Freigabe sitzt im Reiter Superuser
- [x] Datenkabel, kein reines Ladekabel. In einer früheren Sitzung erschien das Handy als Samsung-Modem, also trägt das Kabel Daten. Jetzt ist es nicht eingesteckt
- [x] scrcpy 5.0.1 installiert (`winget install --id Genymobile.scrcpy -e`)
- [x] OBS-Skript liegt unter `obs/usb-handy-spiegel.py`. In OBS unter Werkzeuge, Skripte laden. Vor Odin alle Spiegel stoppen. Nicht gleichzeitig mit `record-display.ps1`
- [x] `.\verify-prep.ps1` prüft Odin, Magisk-Hash, Bifrost, Treiber, `geraet.txt` und `firmware\`
- [ ] USB-Debugging an. Nach dem Einstecken den Dialog mit **Immer von diesem Computer zulassen** bestätigen. USB-Modus: Dateiübertragung
- [ ] `.\prep-geraet.ps1` → `geraet.txt` mit Modell, Build, CSC
- [ ] `.\open-bifrost.ps1` → Firmware nach `firmware\`
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

## Unlock filmen

Kapitel in dieser Reihenfolge, Sätze aus `DREHBUCH.md`:

- [ ] `warnung`
- [ ] `modell` — bei `KG STATE: Prenormal` abbrechen
- [ ] `oem` — fehlt der Schalter, Aufnahme beenden
- [ ] Unlock-Wipe mit zweiter Kamera, danach `unlock` und `OEM LOCK: OFF`

## Magisk filmen

- [ ] `magisk` — nur `tools\Magisk-v31.1.apk`, eigene AP patchen
- [ ] `odin` — Auto Reboot aus, BL/AP/CP/CSC, danach Recovery-Factory-Reset
- [ ] `root` — Magisk Superuser für Termux, dann `uid=0(root)`

## Dashboard filmen

- [ ] `debian` — Termux + Debian, Nginx 8080, Glances `0.0.0.0`
- [ ] `dashboard` — `phone/index.html` mit Handy-IP, vom Laptop öffnen
- [ ] `dauerbetrieb` — Wake-Lock, uneingeschränkter Akku, Display aus, Seite bleibt
- [ ] `ausblick` — Pi 5, kein Minecraft-Start, Tailscale nur wenn schon eingeloggt
- [ ] Lokale Vorschau ohne Handy: `.\serve-dashboard.ps1`

## Wenn eine Szene scheitert

- OEM-Schalter fehlt oder `KG STATE: Prenormal`: Aufnahme beenden. Warten, bis das Gerät nach einer WLAN-Verbindung `Checking` oder entsperrbar zeigt. Kein Workaround, kein anderes Tool.
- Odin `FAIL` oder Bootloop: die originalen BL, AP, CP und CSC flashen, Auto Reboot aus, danach der Recovery-Wipe. Nichts weiter ausprobieren.
- Magisk ist nach dem Neustart leer: App öffnen, die angebotene Zusatz-Einrichtung bestätigen, neu starten.
- Nginx oder Glances sind nur auf dem Handy erreichbar: den Dienst an `0.0.0.0` binden, nicht an `127.0.0.1`. Gäste-WLAN und AP-Isolation im Router sind die andere häufige Ursache.
- Das Handy wird im Test heiß: den Dienst stoppen. Das gehört als Satz ins Video.
