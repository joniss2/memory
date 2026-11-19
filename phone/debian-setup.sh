#!/data/data/com.termux/files/usr/bin/bash
# Termux und Debian, zum Vorlesen in der Nahaufnahme.
# Abschnittsweise ausführen. su und proot-distro login sind interaktiv.
# Termux kommt von F-Droid, nicht aus dem Play Store.
# Nginx hört auf 8080. Glances bindet das Web an 0.0.0.0, Port 61208.
# Magisk ist v31.1. Die App zeigt beim ersten su keinen Dialog mehr.
# Die Freigabe sitzt im Reiter Superuser, bevor uid=0(root) kommt.

# --- In Termux: Root zeigen ---
pkg update && pkg upgrade -y
pkg install tsu -y
# Einmal su. Ohne Schalter in Magisk kommt kein root.
su
# Magisk öffnen, Reiter Superuser, Termux einschalten, zurück nach Termux.
su
id

# --- In Termux: Debian holen ---
# Linux Deploy nicht verwenden. systemd und Docker bleiben weg.
pkg install proot-distro -y
proot-distro install debian
proot-distro login debian

# --- Ab hier im Debian ---
apt update && apt upgrade -y
apt install -y nginx python3 python3-pip
# Port 80 auf 8080 legen. Die Szene klappt auch, wenn Port 80 blockiert bleibt.
sed -i 's/listen 80/listen 8080/' /etc/nginx/sites-enabled/default
nginx
pip install --break-system-packages "glances[web]"
# Läuft im Vordergrund. Für die Aufnahme reicht das.
glances -w -B 0.0.0.0

# --- Startseite (zweites Termux oder nach Stoppen von Glances) ---
# phone/index.html vom PC nach /var/www/html/index.html legen.
# Platzhalter 192.168.x.x durch die Handy-IP aus den WLAN-Details ersetzen.
# nano /var/www/html/index.html
# nginx -s reload
# Vom Laptop: http://<handy-ip>:8080 und http://<handy-ip>:61208

# --- Einmalig in Termux, mit Root ---
# Damit Android Nginx und Glances nicht sofort beendet.
# su -c 'settings put global settings_enable_monitor_phantom_procs false'

# --- Dauerbetrieb ---
# termux-wake-lock
# Akku: Termux uneingeschränkt, Akku schützen ~85 %, WLAN im Ruhezustand an
# Termux:Boot: phone/start.sh nach ~/.termux/boot/start.sh, chmod +x

