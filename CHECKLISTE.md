# Checkliste vor dem Dreh

CSC und Build stehen noch nicht fest. `adb devices` ist leer: USB-Debugging fehlt noch. CrossDevice/Smartphone-Link sieht das Gerät als `Sushi.test` (Dateizugriff), aber ohne adb keine CSC. Zuerst das Kabel mit Dateiübertragung und USB-Debugging, dann `.\warte-auf-handy.ps1`. Die ausgegebene CSC gilt für Bifrost. Die Firmware für SM-A146P plus diese CSC kommt nach `firmware\`, bevor der Bootloader aufgeht, damit ein Bootloop im Video rettbar ist. Eine CSC nicht raten.

Auf dem Handy unter `Documents/A14` liegen schon `Magisk-v31.1.apk`, `index.html`, `start.sh` und `debian-setup.sh` (über CrossDevice).

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
- [x] `TAKES.md` listet die Takes für Unlock, Magisk und Dashboard
- [x] `warte-auf-handy.ps1` wartet auf USB-Debugging und startet danach Bifrost
- [x] `push-phone-kit.ps1` legt Magisk und `phone/*` nach Documents/A14 (adb oder CrossDevice). Stand: Dateien liegen auf `Sushi.test` unter Documents/A14
- [x] PC-Prep-Werkzeuge liegen bereit (Treiber, Odin 3.14.1 Auto Reboot aus, Magisk-Hash, Bifrost, verify/warte/push)
- [ ] USB-Debugging an. Nach dem Einstecken den Dialog mit **Immer von diesem Computer zulassen** bestätigen. USB-Modus: Dateiübertragung
- [ ] `.\warte-auf-handy.ps1` → `geraet.txt` und Bifrost, Firmware nach `firmware\` (10-Minuten-Warteversuch ohne adb beendet)
- [ ] Kurztest ohne Datei: `.\record-display.ps1 -NurAnzeigen`. Das Display steht im Fenster, bevor eine Aufnahme startet
- [ ] Aufnahme ohne Ton nach `TAKES.md`, ein Kapitel pro Datei. Stoppen mit Strg+C
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

Takes 1–4 in `TAKES.md`. Sätze aus `DREHBUCH.md`. Drehkit (Teleprompter, Abbruch, Aufnahmebefehle) ist bereit. Häkchen setzen, wenn der Take im Kasten ist.

- [x] Drehbuch + Take-Liste für `warnung` / `modell` / `oem` / `unlock`
- [ ] `warnung` aufgenommen
- [ ] `modell` aufgenommen — bei `KG STATE: Prenormal` abbrechen
- [ ] `oem` aufgenommen — fehlt der Schalter, Aufnahme beenden
- [ ] Unlock-Wipe mit zweiter Kamera, danach `unlock` und `OEM LOCK: OFF`

## Magisk filmen

Takes 5–7 in `TAKES.md`. Magisk nur als `tools\Magisk-v31.1.apk` (liegt auch unter Documents/A14).

- [x] Drehbuch + Take-Liste für `magisk` / `odin` / `root`
- [ ] `magisk` aufgenommen — eigene AP patchen
- [ ] `odin` aufgenommen — Auto Reboot aus, BL/AP/CP/CSC, danach Recovery-Factory-Reset
- [ ] `root` aufgenommen — Magisk Superuser für Termux, dann `uid=0(root)`

## Dashboard filmen

Takes 8–11 in `TAKES.md`. Skripte: `phone/debian-setup.sh`, `phone/index.html`, `phone/start.sh`.

- [x] Drehbuch + Take-Liste + Skripte für Debian/Dashboard/Dauerbetrieb/Ausblick
- [x] Lokale Vorschau ohne Handy: `.\serve-dashboard.ps1` (Titel „A14 Server“, Port 8080)
- [ ] `debian` aufgenommen — Termux → Debian, Nginx 8080, Glances `0.0.0.0`
- [ ] `dashboard` aufgenommen — `phone/index.html` mit Handy-IP, vom Laptop öffnen
- [ ] `dauerbetrieb` aufgenommen — Wake-Lock, uneingeschränkter Akku, Display aus, Seite bleibt
- [ ] `ausblick` aufgenommen — Pi 5, kein Minecraft-Start, Tailscale nur wenn schon eingeloggt

## Wenn eine Szene scheitert

- OEM-Schalter fehlt oder `KG STATE: Prenormal`: Aufnahme beenden. Warten, bis das Gerät nach einer WLAN-Verbindung `Checking` oder entsperrbar zeigt. Kein Workaround, kein anderes Tool.
- Odin `FAIL` oder Bootloop: die originalen BL, AP, CP und CSC flashen, Auto Reboot aus, danach der Recovery-Wipe. Nichts weiter ausprobieren.
- Magisk ist nach dem Neustart leer: App öffnen, die angebotene Zusatz-Einrichtung bestätigen, neu starten.
- Nginx oder Glances sind nur auf dem Handy erreichbar: den Dienst an `0.0.0.0` binden, nicht an `127.0.0.1`. Gäste-WLAN und AP-Isolation im Router sind die andere häufige Ursache.
- Das Handy wird im Test heiß: den Dienst stoppen. Das gehört als Satz ins Video.
