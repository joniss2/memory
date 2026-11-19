# Drehkit: A14 als Linux-Server

Diesen Ordner beim Dreh offen lassen. Er ist der Teleprompter und die Dateien fürs Handy. Geflasht wird nur am Schreibtisch, mit dem Telefon am Kabel. Hier liegt keine Firmware, und dieses Projekt startet kein Odin.

Das Display kommt über USB als stummes Video auf den PC. Erst das Bild prüfen, dann ein Kapitel aufnehmen. Die Stimme wird später darübergelegt. Vor Odin das scrcpy-Fenster schließen. Download-Modus und Odin filmt die zweite Kamera, weil dort kein USB-Debugging läuft.

Vor der Aufnahme `CHECKLISTE.md` abhaken. CSC und Build stehen noch nicht fest: beides am Handy ablesen, danach die passende SM-A146P-Firmware auf den PC legen. Die Sätze in `DREHBUCH.md` bleiben der Text für den späteren Voiceover.

| Datei | Wofür |
| --- | --- |
| `DREHBUCH.md` | Teleprompter, ein Abschnitt pro Kapitel |
| `CHECKLISTE.md` | PC, Handy, Firmware-Dateinamen, Unkenntlichmachen, Abbruch |
| `phone/debian-setup.sh` | Befehle für Termux und Debian, in der Nahaufnahme mitlesen |
| `phone/index.html` | Startseite „A14 Server“, live nach `/var/www/html/index.html` |
| `phone/start.sh` | später `~/.termux/boot/start.sh` |
| `record-display.ps1` | Display über USB ohne Ton nach `aufnahmen/` |
| `obs/usb-handy-spiegel.py` | Dieselben USB-Handys als Quelle in OBS |

```powershell
.\record-display.ps1 -NurAnzeigen
.\record-display.ps1 -Kapitel modell
```

Stoppen mit Strg+C im selben Fenster. Ein Kapitel pro Datei, zum Beispiel `warnung`, `modell`, `magisk`, `debian`, `dashboard`.

Für OBS das Skript `obs/usb-handy-spiegel.py` unter Werkzeuge, Skripte laden. Python 3.12 64-bit ist installiert; unter Python-Einstellungen den Ordner `%LocalAppData%\Programs\Python\Python312` eintragen. Jedes USB-Handy wird eine Quelle `Handy <Modell>` in der aktuellen Szene. Das scrcpy-Fenster bleibt offen und wird nicht minimiert. Vor Odin im Skript **Alle Spiegel stoppen**. Nicht gleichzeitig mit `record-display.ps1` auf demselben Handy.

Odin ist **3.14.1** aus dem XDA-Thread „Patched Odin“, Auto Reboot bleibt aus. Die vier Dateien sind BL, AP, CP und CSC. `HOME_CSC` kommt nicht ins Programm. Magisk nur von der offiziellen Release auf GitHub, topjohnwu. Nginx hört auf Port **8080**, Glances mit `glances -w -B 0.0.0.0`.
