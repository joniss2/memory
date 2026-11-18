#!/data/data/com.termux/files/usr/bin/bash
# Termux:Boot. Liegt auf dem Handy unter ~/.termux/boot/start.sh
# Wake-Lock holen, dann Nginx (8080) und Glances (0.0.0.0:61208) im Debian starten.

termux-wake-lock

# Hintergrund, damit das Boot-Skript nicht im Vordergrund hängen bleibt.
proot-distro login debian -- bash -lc 'nginx; glances -w -B 0.0.0.0' >/dev/null 2>&1 &
