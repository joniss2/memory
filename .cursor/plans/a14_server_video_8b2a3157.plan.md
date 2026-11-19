---
name: A14 Server Video
overview: Ein filmbares Drehbuch, mit dem du das SM-A146P per Bootloader-Unlock und Magisk rootest und danach ein Debian-Dashboard im Heimnetz zeigst. Minecraft und der Raspberry Pi bleiben der Ausblick, weil dieses Handy der Lern- und Monitor-Knoten ist.
todos:
  - id: prep-firmware
    content: "Vor dem Dreh: CSC und Build ablesen, passende SM-A146P-Firmware, Odin 3.14.1 und Samsung-Treiber auf den PC legen"
    status: completed
  - id: film-unlock
    content: Warnung, Modellbeweis, OEM-Unlock und Bootloader-Wipe filmen; bei Prenormal abbrechen
    status: completed
  - id: film-magisk
    content: Eigene AP mit offiziellem Magisk patchen, Odin ohne Auto-Reboot, Recovery-Factory-Reset, su als Beweis
    status: completed
  - id: film-dashboard
    content: Termux-Debian, Nginx auf 8080, Glances, eigene Startseite vom Laptop öffnen, Dauerbetrieb mit ausgeschaltetem Display zeigen
    status: completed
isProject: false
---

# A14 als Linux-Server: Drehbuch

Du filmst **ein Video**: Warnung, Modellbeweis, Bootloader auf, Magisk, Debian, Dashboard im Browser. Der Raspberry Pi und ein dauerhafter Minecraft-Server kommen als letzte Szene nur als Ausblick. Das SM-A146P/DSN lässt sich entsperren (auf XDA gibt es einen erfolgreichen Lauf genau mit SM-A146P/DSN). `/DSN` ist nur die Dual-SIM-Verkaufsvariante. Die Firmware hängt an **SM-A146P plus CSC**.

Das A146P hat den **MediaTek Dimensity 700**, nicht den Exynos 1330. Samsung hat **kein Fastboot**. Geflasht wird nur mit Odin. Fertige Root-TARs und mtkclient-Anleitungen bleiben aus dem Video: dabei ist auf diesem Gerät schon die Baseband/IMEI verloren gegangen.

## Was du anders machst als in der Duck.ai-Liste

- Die **passende Stock-Firmware liegt auf dem PC, bevor** du entsperrst. Damit kannst du einen Bootloop im Video retten.
- Magisk kommt von [github.com/topjohnwu/Magisk](https://github.com/topjohnwu/Magisk). Du patchst die AP-Datei deiner eigenen Firmware.
- In Odin ist **Auto Reboot aus**. Nach PASS startest du direkt ins Recovery und machst einen Factory Reset. Dieser Schritt fehlt in der kurzen Anleitung und ist der übliche Bootloop-Grund.
- Linux danach ist **Termux + Debian (proot)**. Linux Deploy ist auf Android 15 unzuverlässig. Docker versprichst du nicht: der Samsung-Kernel hat die nötigen Funktionen dafür nicht.
- Root nutzt du für drei sichtbare Dinge: `su`, Hintergrundprozesse am Leben halten, Autostart. Nginx zeigst du auf Port **8080**, damit die Szene auch dann klappt, wenn Port 80 blockiert bleibt.
- Minecraft startest du in diesem Video nicht. Der Dimensity 700 und 4–6 GB RAM reichen für einen kurzen Test, nicht für den Server, den du später mit Freunden laufen lassen willst. Dafür ist ein Pi 5 mit 8 GB, Aktivkühlung und SSD der nächste Film.

## Vor dem Dreh (nicht live improvisieren)

Auf dem Windows-PC:

- Samsung-USB-Treiber
- Odin **3.14.1** aus dem bekannten XDA-Thread „Patched Odin“. Die im Netz kursierende „Odin 3.14.4“ lässt du weg
- Frija, Bifrost oder SamFw
- Datenkabel, kein reines Ladekabel
- Zweite Kamera oder das Handy im Stativ. **scrcpy und Odin teilen sich den USB-Anschluss.** Den Download-Modus und Odin filmst du vom Handy-Display, den PC-Bildschirm nimmst du separat auf

Auf dem Handy, bevor irgendetwas gelöscht wird:

- Einstellungen → Telefoninfo: Modell **SM-A146P**, Build-Nummer, Android-Version, RAM
- Einstellungen → Telefoninfo → Softwareinformationen → **Dienstanbieter-SW-Version**. Die CSC steht in der Zeile, oft als dritter Code (zum Beispiel `DBT` oder `EUX`)
- Bildschirmsperre entfernen, Google-Konto für die FRP-Anmeldung danach bereithalten
- Firmware **SM-A146P + diese CSC** laden. Die Build-Nummer muss zu der auf dem Handy passen oder neuer sein. Ein Downgrade unter die aktuelle Binary schlägt fehl. Aktueller Stand dieses Modells ist **Android 15 / One UI 7**
- Die vier Dateien bereitlegen: `BL`, `AP`, `CP`, `CSC` (die `HOME_CSC` brauchst du für diesen Lauf nicht)

Schnitt-Kapitel in der Beschreibung: Warnung, Modell, Unlock, Magisk, Odin, Root-Beweis, Debian, Dashboard, Dauerbetrieb, Ausblick Pi.

```mermaid
flowchart LR
  prep[Firmware und Backup] --> prove[Modell und CSC filmen]
  prove --> unlock[Bootloader unlock]
  unlock --> patch[AP mit Magisk patchen]
  patch --> odin[Odin ohne Auto Reboot]
  odin --> recovery[Recovery Wipe]
  recovery --> root[su Beweis]
  root --> debian[Termux Debian]
  debian --> dash[Dashboard im Browser]
```

## Kapitel 1 — Hook und Warnung (etwa 45 Sekunden)

Bild: Laptop-Browser noch leer, Handy am Kabel. Satz zum Einsprechen:

„Aus diesem Samsung A14 5G wird ein kleiner Linux-Server. Das Gerät ist nicht mein Alltagshandy. Gleich werden alle Daten gelöscht, und der Knox-Zähler springt dauerhaft auf 0x1. Samsung Pay, der sichere Ordner und viele Banking-Apps laufen danach nicht mehr. Zurück auf Garantie geht nicht.“

## Kapitel 2 — Beweisen, dass es das richtige Gerät ist

Filme langsam:

- Modellname `SM-A146P`
- Build-Nummer, zum Beispiel `A146PXX...`
- Android-Version
- RAM und Speicher
- Dienstanbieter-SW-Version mit der CSC

Sag dazu: „Die Dateien auf dem PC sind genau für diese Build. Eine Root-Datei aus dem Internet flashe ich nicht.“

Kurzer Blick in den Download-Modus, **ohne** lange Vol+ zu halten: Handy aus, beide Lautstärketasten halten, USB einstecken. Filme die Zeilen `OEM LOCK` und `KG STATE`. `Prenormal` oder ein fehlender Schalter „OEM-Entsperrung“ bedeutet: Video hier beenden und warten, bis das Gerät nach WLAN-Verbindung `Checking` oder entsperrbar zeigt. Kein Workaround, kein anderes Tool.

## Kapitel 3 — Backup und OEM-Entsperrung

Zeige, dass Fotos und Konten weg sind bzw. gesichert wurden. Dann:

- Entwickleroptionen: siebenmal auf die Build-Nummer
- **OEM-Entsperrung** an
- USB-Debugging an

Wenn der Schalter fehlt, ist Kapitel 3 das Ende dieser Aufnahme.

## Kapitel 4 — Bootloader entsperren (der Wipe)

Handy aus. Beide Lautstärketasten, USB dran, Warnhinweis abfilmen. **Lange Vol+**, dann zur Bestätigung noch einmal Vol+. Das Handy löscht sich und startet neu. Knox ist ab hier offen.

Nach der Ersteinrichtung (WLAN, Google-Konto wegen FRP):

- Entwickleroptionen wieder an
- OEM-Entsperrung steht an und ist ausgegraut. Das ist der Beweis, dass der Unlock sitzt
- Download-Modus noch einmal: `OEM LOCK: OFF`

## Kapitel 5 — AP patchen

1. Magisk-APK von GitHub installieren (aktuelle Release von topjohnwu).
2. Die `AP_...tar.md5` aufs Handy kopieren. Die Datei ist mehrere GB groß. Vorher freien Speicher zeigen. Liegt die Datei als `.tar.md5` da und Magisk meckert, die Endung auf `.tar` kürzen.
3. Magisk → Installieren → **Eine Datei patchen** → die AP-Datei.
4. Die neue Datei liegt unter `Download/magisk_patched-....tar`. Zurück auf den PC. Sie bleibt `.tar`.

## Kapitel 6 — Odin

Odin als Administrator. Das Handy ist im Download-Modus, die COM-Anzeige ist blau.

- **Auto Reboot aus**
- BL = originale BL
- AP = die gepatchte TAR
- CP = originale CP
- CSC = originale `CSC_...` (nicht HOME_CSC)
- Start

Filme `PASS`. Dann sofort, solange das Kabel steckt: **Vol− + Power** etwa 7 Sekunden, sobald das Bild ausgeht **Vol+ + Power**, bis das Recovery kommt. Dort **Factory data reset**, danach `Reboot system now`.

Kommt `FAIL`: nichts weiter ausprobieren. Die originalen BL, AP, CP und CSC flashen, wieder mit Auto Reboot aus und Recovery-Reset.

## Kapitel 7 — Root beweisen

Ersteinrichtung noch einmal. Magisk-App öffnen. Sie will oft noch einmal neu einrichten und neu starten. Danach steht dort „Installiert“.

Termux von **F-Droid** installieren, nicht aus dem Play Store. In Termux:

```bash
pkg update && pkg upgrade -y
pkg install tsu -y
su
id
```

`uid=0(root)` ist die Szene, die den Root-Teil abschließt. Magisk fragt beim ersten `su` nach der Freigabe, das mitfilmen.

## Kapitel 8 — Debian und das Dashboard

Einsprechen: „Ein volles PC-Linux wird das Handy nicht. systemd und Docker lasse ich weg. Was ich bekomme, ist ein Debian, in dem ich Dienste starte, und Root, damit Android sie nicht sofort beendet.“

```bash
pkg install proot-distro -y
proot-distro install debian
proot-distro login debian
```

Im Debian:

```bash
apt update && apt upgrade -y
apt install -y nginx python3 python3-pip
sed -i 's/listen 80/listen 8080/' /etc/nginx/sites-enabled/default
nginx
pip install --break-system-packages "glances[web]"
glances -w -B 0.0.0.0
```

Glances läuft im Vordergrund. Für die Aufnahme reicht das. Die IP steht in den WLAN-Details des Handys.

Vom Laptop:

- `http://<handy-ip>:8080` zeigt die Nginx-Seite
- `http://<handy-ip>:61208` zeigt Glances

Eine eigene `index.html` mit dem Titel „A14 Server“, der IP und den zwei Links machst du live in `/var/www/html/index.html`. Das ist das Dashboard, das du im Hook versprochen hast. Uptime Kuma brauchst du in dieser Folge nicht; Glances ist das Bild, das Zuschauer sofort verstehen.

Port 80 als Root-Experiment, nur wenn 8080 schon läuft: zweite Aufnahme, kurz `su` und einen Redirect versuchen. Klappt es nicht, bleibt 8080 das Ergebnis und du sagst das laut.

## Kapitel 9 — Damit es anbleibt, wenn das Display aus ist

Mit Root, einmalig:

```bash
su -c 'settings put global settings_enable_monitor_phantom_procs false'
```

Dazu im Video zeigen:

- Termux: `termux-wake-lock`
- Akku → Termux → **Uneingeschränkt**
- Akku → **Akku schützen**, Grenze etwa 85 Prozent. Das Handy bleibt am Netzteil, mit Luft dahinter, nicht unter einem Kissen
- WLAN → erweitert → WLAN im Ruhezustand aktiv lassen
- Termux:Boot von F-Droid und eine Datei `~/.termux/boot/start.sh`, die Debian startet und Nginx plus Glances hochfährt

Display aus, Laptop neu laden. Die Seite muss noch da sein. Das ist der Schlusstest.

## Kapitel 10 — Ausblick (30–40 Sekunden)

„Minecraft und alles, was dauerhaft laufen soll, kommt auf einen Raspberry Pi 5 mit 8 GB, Aktivkühlung und SSD. Dieses Handy bleibt der Knoten, den ich hier in Glances sehe. Von unterwegs erreiche ich es später über Tailscale, ohne Ports am Router zu öffnen.“

Tailscale kannst du in 20 Sekunden zeigen, wenn die App schon eingeloggt ist. Portfreigabe für 8080 oder 25565 filmen wir nicht.

## Wenn eine Szene scheitert

- OEM-Schalter fehlt oder `KG STATE: Prenormal`: Aufnahme beenden.
- Odin `FAIL` oder Bootloop: originale BL+AP+CP+CSC, Auto Reboot aus, Recovery-Wipe.
- Magisk leer nach dem Neustart: App öffnen, die angebotene Zusatz-Einrichtung bestätigen, neu starten.
- Nginx oder Glances nur auf dem Handy erreichbar: Dienst an `0.0.0.0` binden, nicht an `127.0.0.1`. Gäste-WLAN und AP-Isolation im Router sind die andere häufige Ursache.
- Handy wird im Test heiß: Dienst stoppen, das gehört als Satz ins Video.

## Was du vor der Veröffentlichung unkenntlich machst

Seriennummer, IMEI, Google-Konto, WLAN-Name und die volle lokale IP in den Einstellungsseiten. Die COM-Nummer in Odin und die öffentliche Tailscale-Adresse ebenfalls.