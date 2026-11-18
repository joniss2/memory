# Teleprompter

Ein Kapitel nach dem anderen. Die Sätze bleiben stehen, sie werden nicht live eingesprochen. Das Display läuft stumm über USB nach `aufnahmen/`, die Stimme kommt später als Voiceover auf dieses Bild. Befehle nur aus den Blöcken abtippen. `Prenormal`, ein fehlender Schalter „OEM-Entsperrung“ und Odin `FAIL` beenden die Aufnahme. Download-Modus und Odin filmt die zweite Kamera, vorher scrcpy schließen.

Schnitt in der Beschreibung: Warnung, Modell, Unlock, Magisk, Odin, Root-Beweis, Debian, Dashboard, Dauerbetrieb, Ausblick Pi.

## Hook und Warnung

**Bild:** Laptop-Browser noch leer, Handy am Kabel.

**Satz zum Einsprechen:**

> Aus diesem Samsung A14 5G wird ein kleiner Linux-Server. Das Gerät ist nicht mein Alltagshandy. Gleich werden alle Daten gelöscht, und der Knox-Zähler springt dauerhaft auf 0x1. Samsung Pay, der sichere Ordner und viele Banking-Apps laufen danach nicht mehr. Zurück auf Garantie geht nicht.

**Schritte:**

- Handy und den leeren Browser gleichzeitig im Bild halten.
- Den Satz in einem Zug sprechen. In dieser Szene noch kein Odin und keine Firmware-Datei öffnen.

## Modell

**Bild:** Einstellungen, Telefoninfo, langsam durchgehen. Danach ein kurzer Blick in den Download-Modus, ohne die Lauter-Taste lange zu halten.

**Satz zum Einsprechen:**

> Die Dateien auf dem PC sind genau für diese Build. Eine Root-Datei aus dem Internet flashe ich nicht.

**Schritte:**

- Modellname `SM-A146P` zeigen. `/DSN` ist nur die Dual-SIM-Verkaufsvariante. Die Firmware hängt an SM-A146P plus CSC.
- Build-Nummer zeigen, zum Beispiel `A146PXX...`.
- Android-Version zeigen. Aktueller Stand dieses Modells ist Android 15 mit One UI 7.
- RAM und Speicher zeigen. Das A146P hat den MediaTek Dimensity 700, nicht den Exynos 1330.
- Einstellungen, Telefoninfo, Softwareinformationen, Dienstanbieter-SW-Version öffnen. Die CSC steht in der Zeile, oft als dritter Code, zum Beispiel `DBT` oder `EUX`.
- Download-Modus nur kurz: Handy aus, beide Lautstärketasten halten, USB einstecken. Die Zeilen `OEM LOCK` und `KG STATE` filmen. Vol+ nicht lange halten, sonst beginnt der Unlock.

**Schnitt wenn:** `KG STATE: Prenormal`, oder der Schalter „OEM-Entsperrung“ fehlt. Video hier beenden und warten, bis das Gerät nach einer WLAN-Verbindung `Checking` oder entsperrbar zeigt. Kein Workaround, kein anderes Tool.

## Backup und OEM

**Bild:** Galerie und Konten, schon leer oder gesichert. Danach die Entwickleroptionen.

**Satz zum Einsprechen:**

> Fotos und Konten sind gesichert, die Bildschirmsperre ist aus. Ich tippe siebenmal auf die Build-Nummer, schalte die OEM-Entsperrung ein und aktiviere USB-Debugging.

**Schritte:**

- Zeigen, dass Fotos und Konten weg sind oder gesichert wurden.
- Entwickleroptionen öffnen: siebenmal auf die Build-Nummer tippen.
- OEM-Entsperrung einschalten.
- USB-Debugging einschalten.

**Schnitt wenn:** Der Schalter „OEM-Entsperrung“ fehlt. Dieses Kapitel ist das Ende der Aufnahme.

## Bootloader

**Bild:** Warnhinweis im Download-Modus auf dem Handy-Display. Nach dem Wipe die Ersteinrichtung, danach noch einmal `OEM LOCK: OFF`.

**Satz zum Einsprechen:**

> Ich halte beide Lautstärketasten, stecke das Kabel ein und bestätige die Warnung mit langer Lauter-Taste und noch einmal Lauter. Das Handy löscht sich und startet neu. Knox ist ab hier offen. Nach der Einrichtung steht die OEM-Entsperrung an und ist ausgegraut. Im Download-Modus steht OEM LOCK auf OFF.

**Schritte:**

- Handy aus. Beide Lautstärketasten halten, USB anschließen, den Warnhinweis abfilmen.
- Lange Vol+, dann zur Bestätigung noch einmal Vol+.
- Das Handy löscht sich und startet neu.
- Ersteinrichtung: WLAN, und das Google-Konto wegen FRP.
- Entwickleroptionen wieder einschalten.
- OEM-Entsperrung steht an und ist ausgegraut. Das ist der Beweis, dass der Unlock sitzt.
- Download-Modus noch einmal öffnen und `OEM LOCK: OFF` filmen.

## AP patchen

**Bild:** Freier Speicher, die Magisk-App von GitHub, die eigene AP-Datei, danach die gepatchte TAR auf dem PC.

**Satz zum Einsprechen:**

> Magisk kommt nur von der offiziellen GitHub-Seite von topjohnwu. Ich kopiere die AP-Datei meiner eigenen Firmware aufs Handy, lasse Magisk genau diese Datei patchen und hole die neue TAR zurück auf den PC.

**Schritte:**

- Magisk-APK von GitHub installieren, die aktuelle Release von topjohnwu: [github.com/topjohnwu/Magisk](https://github.com/topjohnwu/Magisk).
- Die Datei `AP_...tar.md5` aufs Handy kopieren. Sie ist mehrere GB groß. Vorher den freien Speicher zeigen.
- Liegt die Datei als `.tar.md5` da und Magisk meckert, die Endung auf `.tar` kürzen.
- Magisk, Installieren, Eine Datei patchen, die AP-Datei wählen.
- Die neue Datei liegt unter `Download/magisk_patched-....tar`. Zurück auf den PC kopieren. Sie bleibt `.tar`.

## Odin

**Bild:** Odin als Administrator, die COM-Anzeige ist blau, Auto Reboot ist aus. Download-Modus und Odin vom Handy-Display filmen, den PC-Bildschirm separat. scrcpy und Odin teilen sich den USB-Anschluss.

**Satz zum Einsprechen:**

> Auto Reboot ist aus. BL, CP und CSC sind die originalen Dateien, AP ist die gepatchte TAR. HOME_CSC benutze ich nicht. Nach PASS gehe ich direkt ins Recovery und mache den Factory Reset.

**Schritte:**

- Odin als Administrator starten. Das Handy ist im Download-Modus.
- Samsung hat hier kein Fastboot. Geflasht wird nur mit Odin. Fertige Root-TARs und mtkclient bleiben aus dem Video.
- Auto Reboot aus.
- BL ist die originale BL.
- AP ist die gepatchte TAR.
- CP ist die originale CP.
- CSC ist die originale `CSC_...`, nicht `HOME_CSC`.
- Start drücken und `PASS` filmen.
- Sofort, solange das Kabel steckt: Vol− und Power etwa 7 Sekunden. Sobald das Bild ausgeht, Vol+ und Power halten, bis das Recovery kommt.
- Dort Factory data reset wählen, danach Reboot system now.

**Schnitt wenn:** Odin zeigt `FAIL`. Nichts weiter ausprobieren. Die originalen BL, AP, CP und CSC flashen, wieder mit Auto Reboot aus, und danach den Recovery-Reset machen. Dasselbe gilt bei einem Bootloop.

## Root-Beweis

**Bild:** Magisk mit dem Status „Installiert“, dann Termux von F-Droid und die Zeile `uid=0(root)`.

**Satz zum Einsprechen:**

> Ich richte das Handy noch einmal ein und öffne Magisk. Die App will oft noch eine Zusatz-Einrichtung und einen Neustart. Danach steht dort Installiert. Termux hole ich von F-Droid, nicht aus dem Play Store. Wenn dort uid=0(root) steht, ist der Root-Teil zu Ende.

**Schritte:**

- Die Ersteinrichtung noch einmal durchlaufen.
- Magisk öffnen. Die angebotene Zusatz-Einrichtung bestätigen und neu starten, wenn die App danach fragt.
- Danach steht dort „Installiert“.
- Termux von F-Droid installieren.
- Die Befehle in Termux ausführen. Magisk fragt beim ersten `su` nach der Freigabe. Das mitfilmen.

```bash
pkg update && pkg upgrade -y
pkg install tsu -y
su
id
```

- `uid=0(root)` ist die Szene, die den Root-Teil abschließt.

## Debian und Dashboard

**Bild:** Termux, danach der Laptop-Browser mit der eigenen Seite auf Port 8080 und mit Glances auf Port 61208.

**Satz zum Einsprechen:**

> Ein volles PC-Linux wird das Handy nicht. systemd und Docker lasse ich weg. Was ich bekomme, ist ein Debian, in dem ich Dienste starte, und Root, damit Android sie nicht sofort beendet.

**Schritte:**

- In Termux Debian holen. Linux Deploy nicht verwenden.

```bash
pkg install proot-distro -y
proot-distro install debian
proot-distro login debian
```

- Im Debian Nginx auf 8080 legen und Glances an alle Schnittstellen binden. Glances läuft für die Aufnahme im Vordergrund. Die IP steht in den WLAN-Details des Handys.

```bash
apt update && apt upgrade -y
apt install -y nginx python3 python3-pip
sed -i 's/listen 80/listen 8080/' /etc/nginx/sites-enabled/default
nginx
pip install --break-system-packages "glances[web]"
glances -w -B 0.0.0.0
```

- `phone/index.html` live nach `/var/www/html/index.html` legen. Den Platzhalter durch die IP des Handys ersetzen. Die Seite heißt „A14 Server“ und verlinkt diese Seite auf Port 8080 und Glances auf Port 61208.
- Vom Laptop `http://<handy-ip>:8080` öffnen. Das ist die Nginx-Seite.
- Vom Laptop `http://<handy-ip>:61208` öffnen. Das ist Glances.
- Uptime Kuma kommt in dieser Folge nicht vor.
- Port 80 nur als zweite Aufnahme, und nur wenn 8080 schon läuft: kurz `su` und einen Redirect versuchen. Klappt es nicht, bleibt 8080 das Ergebnis, und das sagst du laut.
- Docker nicht versprechen. Der Samsung-Kernel hat die nötigen Funktionen dafür nicht.

## Dauerbetrieb

**Bild:** Akku-Einstellungen, danach das dunkle Display, und der Laptop, der die Seite neu lädt.

**Satz zum Einsprechen:**

> Einmalig schalte ich die Überwachung der Phantom-Prozesse aus, damit Android die Dienste nicht sofort beendet. Termux bekommt einen Wake-Lock und uneingeschränkten Akku. Das Handy bleibt am Netzteil, mit Luft dahinter, nicht unter einem Kissen. Display aus, Laptop neu laden: die Seite muss noch da sein.

**Schritte:**

- Mit Root, einmalig:

```bash
su -c 'settings put global settings_enable_monitor_phantom_procs false'
```

- In Termux den Wake-Lock holen:

```bash
termux-wake-lock
```

- Akku, Termux, Uneingeschränkt.
- Akku, Akku schützen, Grenze etwa 85 Prozent. Das Handy bleibt am Netzteil, mit Luft dahinter, nicht unter einem Kissen.
- WLAN, erweitert, WLAN im Ruhezustand aktiv lassen.
- Termux:Boot von F-Droid installieren. `phone/start.sh` als `~/.termux/boot/start.sh` ablegen. Die Datei holt den Wake-Lock und startet im Debian Nginx und Glances im Hintergrund.
- Display ausschalten. Auf dem Laptop die Seite neu laden. Sie muss noch da sein. Das ist der Schlusstest.

## Ausblick

**Bild:** Glances auf dem Laptop, das Handy daneben. Den Raspberry Pi nicht anschließen und Minecraft nicht starten.

**Satz zum Einsprechen:**

> Minecraft und alles, was dauerhaft laufen soll, kommt auf einen Raspberry Pi 5 mit 8 GB, Aktivkühlung und SSD. Dieses Handy bleibt der Knoten, den ich hier in Glances sehe. Von unterwegs erreiche ich es später über Tailscale, ohne Ports am Router zu öffnen.

**Schritte:**

- Etwa 30 bis 40 Sekunden. Der Dimensity 700 und 4 bis 6 GB RAM reichen für einen kurzen Test, nicht für den Server, der später mit Freunden laufen soll.
- Tailscale etwa 20 Sekunden zeigen, wenn die App schon eingeloggt ist.
- Eine Portfreigabe für 8080 oder 25565 nicht filmen.
