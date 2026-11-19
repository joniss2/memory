# Drehkit: A14 als Linux-Server

Diesen Ordner beim Dreh offen lassen. Er ist der Teleprompter und die Dateien fürs Handy. Geflasht wird nur am Schreibtisch, mit dem Telefon am Kabel. Hier liegt keine Firmware, und dieses Projekt startet kein Odin.

Das Display kommt über USB als stummes Video auf den PC. Erst das Bild prüfen, dann ein Kapitel aufnehmen. Die Stimme wird später darübergelegt. Vor Odin das scrcpy-Fenster schließen. Download-Modus und Odin filmt die zweite Kamera, weil dort kein USB-Debugging läuft.

Vor der Aufnahme `CHECKLISTE.md` abhaken. Liegt das Handy im USB-Debugging, liest `.\prep-geraet.ps1` Modell, Build und CSC und schreibt sie nach `geraet.txt`. Danach die passende SM-A146P-Firmware mit Bifrost nach `firmware\` laden. Die Sätze in `DREHBUCH.md` bleiben der Text für den späteren Voiceover.

| Datei | Wofür |
| --- | --- |
| `DREHBUCH.md` | Teleprompter, ein Abschnitt pro Kapitel |
| `CHECKLISTE.md` | PC, Handy, Firmware-Dateinamen, Unkenntlichmachen, Abbruch |
| `phone/debian-setup.sh` | Befehle für Termux und Debian, in der Nahaufnahme mitlesen |
| `phone/index.html` | Startseite „A14 Server“, live nach `/var/www/html/index.html` |
| `phone/start.sh` | später `~/.termux/boot/start.sh` |
| `verify-prep.ps1` | Treiber, Odin, Magisk, Bifrost, `geraet.txt`, firmware\ prüfen |
| `prep-geraet.ps1` | Modell, Build und CSC per adb, ohne Seriennummer |
| `open-bifrost.ps1` | Bifrost mit der CSC aus `geraet.txt`, Ziel `firmware\` |
| `serve-dashboard.ps1` | lokale Vorschau von `phone/index.html` auf Port 8080 |
| `record-display.ps1` | Display über USB ohne Ton nach `aufnahmen/` |
| `obs/usb-handy-spiegel.py` | Dieselben USB-Handys als Quelle in OBS |
| `tools\odin-patched\extracted\` | Odin 3.14.1 PatcheD, Auto Reboot aus |
| `tools\Magisk-v31.1.apk` | offizielle Magisk-Release, Prüfsumme gegen GitHub |
| `tools\bifrost\` | Bifrost 2.1.4, Firmware nach `firmware\` |
| `firmware\` | BL, AP, CP, CSC für genau diese Build |

Reihenfolge vor dem ersten Take:

```powershell
.\verify-prep.ps1
.\prep-geraet.ps1
.\open-bifrost.ps1
.\verify-prep.ps1
```

Aufnahme ohne Ton, ein Kapitel pro Datei. Stoppen mit Strg+C im selben Fenster.

```powershell
.\record-display.ps1 -NurAnzeigen
.\record-display.ps1 -Kapitel warnung
.\record-display.ps1 -Kapitel modell
.\record-display.ps1 -Kapitel oem
.\record-display.ps1 -Kapitel unlock
.\record-display.ps1 -Kapitel magisk
.\record-display.ps1 -Kapitel odin
.\record-display.ps1 -Kapitel root
.\record-display.ps1 -Kapitel debian
.\record-display.ps1 -Kapitel dashboard
.\record-display.ps1 -Kapitel dauerbetrieb
.\record-display.ps1 -Kapitel ausblick
```

Laptop-Browser vor dem echten Handy: `.\serve-dashboard.ps1`, dann `http://127.0.0.1:8080`.

Für OBS das Skript `obs/usb-handy-spiegel.py` unter Werkzeuge, Skripte laden. Python 3.12 64-bit ist installiert; unter Python-Einstellungen den Ordner `%LocalAppData%\Programs\Python\Python312` eintragen. Jedes USB-Handy wird eine Quelle `Handy <Modell>` in der aktuellen Szene. Das scrcpy-Fenster bleibt offen und wird nicht minimiert. Vor Odin im Skript **Alle Spiegel stoppen**. Nicht gleichzeitig mit `record-display.ps1` auf demselben Handy.

Odin ist die Datei `tools\odin-patched\extracted\Odin3 v3.14.1_3B_PatcheD.exe` aus dem XDA-Thread „Patched Odin“, Auto Reboot bleibt aus. Die Fassung unter `Downloads\Odin3_v3.14.4` nicht starten. Die vier Dateien sind BL, AP, CP und CSC. `HOME_CSC` kommt nicht ins Programm. Magisk nur als `tools\Magisk-v31.1.apk`, die offizielle Release von topjohnwu. Nginx hört auf Port **8080**, Glances mit `glances -w -B 0.0.0.0`.
