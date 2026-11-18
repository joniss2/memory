#!/data/data/com.termux/files/usr/bin/bash
# Termux und Debian, zum Vorlesen in der Nahaufnahme.
# Abschnittsweise ausführen. su und proot-distro login sind interaktiv.
# Termux kommt von F-Droid, nicht aus dem Play Store.
# Nginx hört auf 8080. Glances bindet das Web an 0.0.0.0, Port 61208.

# --- In Termux: Root zeigen ---
# Magisk fragt beim ersten su nach der Freigabe. Das mitfilmen.
# uid=0(root) schließt den Root-Teil ab.
pkg update && pkg upgrade -y
pkg install tsu -y
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

# --- Einmalig in Termux, mit Root ---
# Damit Android Nginx und Glances nicht sofort beendet.
# su -c 'settings put global settings_enable_monitor_phantom_procs false'
