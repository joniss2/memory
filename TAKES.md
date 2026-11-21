# Takes — Reihenfolge für die Aufnahme

Ein Kapitel = eine Datei unter `aufnahmen/`. Stimme später als Voiceover. Sätze und Abbruchbedingungen stehen in `DREHBUCH.md`. Vor Odin scrcpy und OBS-Spiegel stoppen.

Vor Take 1: `.\verify-prep.ps1` muss grün sein (inkl. `geraet.txt` und BL/AP/CP/CSC). Fehlt adb: `.\warte-auf-handy.ps1`. Kit aufs Handy: `.\push-phone-kit.ps1`.

## Unlock (Todo film-unlock)

| Take | Befehl | Bild | Abbruch |
| --- | --- | --- | --- |
| 1 | `.\record-display.ps1 -Kapitel warnung` | Leerer Laptop-Browser, Handy am Kabel | — |
| 2 | `.\record-display.ps1 -Kapitel modell` | Telefoninfo, CSC, kurzer Download-Modus ohne lange Vol+ | `KG STATE: Prenormal` |
| 3 | `.\record-display.ps1 -Kapitel oem` | Backup leer/gesichert, OEM-Entsperrung, USB-Debugging | Schalter fehlt |
| 4 | Zweite Kamera, danach `.\record-display.ps1 -Kapitel unlock` | Unlock-Warnung, Wipe, OEM ausgegraut, `OEM LOCK: OFF` | — |

## Magisk (Todo film-magisk)

| Take | Befehl | Bild | Abbruch |
| --- | --- | --- | --- |
| 5 | `.\record-display.ps1 -Kapitel magisk` | Freier Speicher, `tools\Magisk-v31.1.apk`, eigene AP patchen, TAR zurück | — |
| 6 | Zweite Kamera + PC | Odin Auto Reboot aus, BL/AP/CP/CSC, `PASS`, Recovery Wipe | Odin `FAIL` → Stock flashen |
| 7 | `.\record-display.ps1 -Kapitel root` | Magisk „Installiert“, Superuser für Termux, `uid=0(root)` | — |

## Dashboard (Todo film-dashboard)

| Take | Befehl | Bild | Abbruch |
| --- | --- | --- | --- |
| 8 | `.\record-display.ps1 -Kapitel debian` | Termux → Debian, Nginx 8080, Glances `0.0.0.0` | Nur lokal erreichbar → Bind und Gast-WLAN prüfen |
| 9 | Laptop / `.\record-display.ps1 -Kapitel dashboard` | `phone/index.html` unter `http://<ip>:8080`, Glances `:61208` | — |
| 10 | `.\record-display.ps1 -Kapitel dauerbetrieb` | Wake-Lock, Akku uneingeschränkt, Display aus, Seite bleibt | Gerät heiß → Dienst stoppen |
| 11 | `.\record-display.ps1 -Kapitel ausblick` | Laptop lädt das Dashboard über die Tailscale-Adresse, Handy nicht im Heim-LAN. Glances, Ausblick Pi 5, kein Minecraft, keine Portfreigabe | — |

Vorschau ohne Handy: `.\serve-dashboard.ps1` → `http://127.0.0.1:8080`.
