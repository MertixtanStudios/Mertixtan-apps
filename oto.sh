#!/bin/bash
# Mertixtan otomatik güncelleyici kurulumu (bir kez çalıştırılır):
#   curl -sL https://raw.githubusercontent.com/MertixtanStudios/Mertixtan-apps/ccr-03677c4a-vw3wll/oto.sh | sudo bash
# Sunucu her 2 dakikada GitHub'daki canli/surum.txt'ye bakar; yeni sürüm varsa zip'i indirir,
# SHA-256 özetini doğrular ve kur.sh ile kurar. Kurulum günlüğü: /opt/mertixtan/oto/son_kurulum.log
set -e
[ "$(id -u)" = 0 ] || { echo "root olarak çalıştır: ... | sudo bash"; exit 1; }
mkdir -p /opt/mertixtan; chmod 755 /opt/mertixtan
cat > /opt/mertixtan/oto_guncelle.sh <<'BETIK'
#!/bin/bash
set -u
D=/opt/mertixtan/oto; mkdir -p "$D"; chmod 700 "$D"
URL="${OTO_URL:-https://raw.githubusercontent.com/MertixtanStudios/Mertixtan-apps/ccr-03677c4a-vw3wll/canli}"
YENI=$(curl -fsL --max-time 30 "$URL/surum.txt?t=$(date +%s)" | tr -dc 0-9a-f) || exit 0
[ ${#YENI} -eq 64 ] || exit 0
[ "$YENI" = "$(cat "$D/surum" 2>/dev/null)" ] && exit 0
echo "$(date '+%F %T') yeni sürüm bulundu: ${YENI:0:12}" >> "$D/gecmis.log"
curl -fsL --max-time 900 -o "$D/paket.zip" "$URL/Mertixtan-Canli.zip?t=$(date +%s)" || exit 0
echo "$YENI  $D/paket.zip" | sha256sum -c --quiet || { echo "$(date '+%F %T') özet tutmadı, kurulmadı" >> "$D/gecmis.log"; exit 0; }
rm -rf "$D/paket"; mkdir -m 700 "$D/paket"
python3 - "$D/paket.zip" "$D/paket" <<'PY' || exit 0
import sys, zipfile
z = zipfile.ZipFile(sys.argv[1])
for u in z.namelist():
    if u.startswith("/") or ".." in u.split("/"): sys.exit("güvensiz dosya yolu: " + u)
z.extractall(sys.argv[2])
PY
if (cd "$D/paket" && bash kur.sh) > "$D/son_kurulum.log" 2>&1; then
  echo "$YENI" > "$D/surum"; echo "$(date '+%F %T') kuruldu ✓" >> "$D/gecmis.log"
else
  echo "$(date '+%F %T') kurulum HATA verdi (son_kurulum.log)" >> "$D/gecmis.log"
fi
BETIK
chmod 700 /opt/mertixtan/oto_guncelle.sh
cat > /etc/systemd/system/mertixtan-oto.service <<'S'
[Unit]
Description=Mertixtan otomatik güncelleme
After=network-online.target
[Service]
Type=oneshot
ExecStart=/opt/mertixtan/oto_guncelle.sh
S
cat > /etc/systemd/system/mertixtan-oto.timer <<'S'
[Unit]
Description=Mertixtan otomatik güncelleme (2 dakikada bir)
[Timer]
OnBootSec=1min
OnUnitActiveSec=2min
[Install]
WantedBy=timers.target
S
systemctl daemon-reload
systemctl enable -q --now mertixtan-oto.timer
fuser -k 8099/tcp 2>/dev/null || true
echo
echo "=============================================================="
echo " Otomatik güncelleyici kuruldu ✓"
echo " İlk kurulum şimdi arka planda başlıyor (model inecekse 5-15 dk)."
echo " Durum:  sudo cat /opt/mertixtan/oto/gecmis.log"
echo " Ayrıntı: sudo tail -20 /opt/mertixtan/oto/son_kurulum.log"
echo " Kapatmak istersen: sudo systemctl disable --now mertixtan-oto.timer"
echo "=============================================================="
systemctl start --no-block mertixtan-oto.service
