"""Mertixtan yükleyici: tek seferlik, şifreli bağlantılı yükleme sayfası.
Tabletten paketi (.zip) ya da modeli (.gguf) seç, "Kabul et ve yayınla"ya bas: sunucu canlıya alır, sonra kapanır."""
import http.server, os, secrets, shutil, subprocess, sys, zipfile, socket, threading, urllib.request

PORT = int(os.environ.get("PORT", "8099"))
JETON = secrets.token_urlsafe(9)
KLASOR = "/opt/mertixtan"
EN_COK = 2 * 1024 ** 3  # 2 GB

SAYFA = """<!doctype html><html lang=tr><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>Mertixtan Yükleyici</title><style>body{font-family:system-ui,sans-serif;background:#0f172a;color:#e2e8f0;display:grid;place-items:center;min-height:100vh;margin:0;padding:16px}
.k{background:#1e293b;border-radius:20px;padding:28px;max-width:420px;width:100%}h1{margin:0 0 6px;font-size:22px}p{color:#94a3b8;font-size:14px}
input{width:100%;margin:16px 0;color:#e2e8f0}button{width:100%;padding:14px;border:0;border-radius:12px;background:linear-gradient(90deg,#10b981,#2563eb);color:#fff;font-weight:700;font-size:16px}
pre{white-space:pre-wrap;background:#020617;padding:12px;border-radius:10px;font-size:12px;max-height:50vh;overflow:auto}</style>
<div class=k><h1>Mertixtan Yükleyici</h1><p>Paketi (.zip) ya da MIMO modelini (.gguf) seç. Sunucu dosyayı alıp canlıya alacak.</p>
<form method=post enctype=multipart/form-data onsubmit="b.disabled=1;b.textContent='Yükleniyor ve kuruluyor… (sayfayı kapatma)'">
<input type=file name=dosya accept=".zip,.gguf" required><button id=b>Kabul et ve yayınla</button></form></div>"""


def ip():
    try: return urllib.request.urlopen("https://api.ipify.org", timeout=5).read().decode()
    except Exception:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.connect(("10.255.255.255", 1)); return s.getsockname()[0]


class Yukleyici(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def _izinli(self):
        if self.path.strip("/") != JETON:
            self.send_error(404); return False
        return True

    def do_GET(self):
        if not self._izinli(): return
        self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8"); self.end_headers()
        self.wfile.write(SAYFA.encode())

    def do_POST(self):
        if not self._izinli(): return
        n = int(self.headers.get("Content-Length", 0))
        tur = self.headers.get("Content-Type", "")
        if n <= 0 or n > EN_COK or "boundary=" not in tur:
            self.send_error(400, "Dosya yok ya da çok büyük"); return
        sinir = ("--" + tur.split("boundary=")[1].strip('"')).encode()
        govde = self.rfile.read(n)
        bas = govde.index(b"\r\n\r\n") + 4
        baslik = govde[:bas].decode("utf-8", "replace")
        ad = os.path.basename(baslik.split('filename="')[1].split('"')[0]) if 'filename="' in baslik else "dosya"
        veri = govde[bas:govde.index(sinir, bas) - 2]
        self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8"); self.end_headers()
        yaz = lambda s: (self.wfile.write(s.encode()), self.wfile.flush())
        yaz("<meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><body style='font-family:system-ui;background:#0f172a;color:#e2e8f0;padding:16px'><h2>Kuruluyor</h2><pre style='white-space:pre-wrap'>")
        yaz(f"{ad} alındı ({len(veri) / 1048576:.1f} MB)\n")
        try:
            os.makedirs(KLASOR, exist_ok=True)
            if ad.lower().endswith(".gguf"):
                os.makedirs("/opt/mimo", exist_ok=True)
                with open("/opt/mimo/mimo.gguf", "wb") as f: f.write(veri)
                try: shutil.chown("/opt/mimo/mimo.gguf", "mimo", "mimo")
                except (LookupError, OSError): pass
                r = subprocess.run(["systemctl", "restart", "mimo"], capture_output=True, text=True)
                yaz("Yeni MIMO modeli yüklendi ve yeniden başlatıldı.\n" if r.returncode == 0 else f"Model kaydedildi ama MIMO başlatılamadı: {r.stderr}\nÖnce paketi (.zip) yükle.\n")
            elif ad.lower().endswith(".zip"):
                hedef = os.path.join(KLASOR, "paket")
                shutil.rmtree(hedef, ignore_errors=True); os.makedirs(hedef)
                zp = os.path.join(KLASOR, "son_paket.zip")
                with open(zp, "wb") as f: f.write(veri)
                with zipfile.ZipFile(zp) as z:
                    for u in z.namelist():  # zip içinden klasör dışına yazma girişimlerini engelle
                        if u.startswith("/") or ".." in u.split("/"): raise ValueError("güvensiz dosya yolu: " + u)
                    z.extractall(hedef)
                kok = hedef
                if not os.path.exists(os.path.join(kok, "kur.sh")):
                    alt = [d for d in os.listdir(hedef) if os.path.exists(os.path.join(hedef, d, "kur.sh"))]
                    if not alt: raise ValueError("pakette kur.sh yok")
                    kok = os.path.join(hedef, alt[0])
                p = subprocess.Popen(["bash", os.path.join(kok, "kur.sh")], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=kok)
                for satir in p.stdout: yaz(satir.replace("<", "&lt;"))
                yaz("\nBİTTİ ✔\n" if p.wait() == 0 else f"\nHATA (çıkış kodu {p.returncode}). Yukarıdaki son satırlara bak.\n")
            else:
                yaz("Sadece .zip ya da .gguf kabul edilir.\n")
        except Exception as e:
            yaz(f"HATA: {e}\n")
        yaz("</pre><p>Yükleyici kapandı. Tekrar yüklemek için komutu yeniden çalıştır.</p>")
        threading.Thread(target=self.server.shutdown, daemon=True).start()


if __name__ == "__main__":
    if os.geteuid() != 0: sys.exit("root olarak çalıştır (sudo).")
    ufw = shutil.which("ufw") and "Status: active" in subprocess.run(["ufw", "status"], capture_output=True, text=True).stdout
    if ufw: subprocess.run(["ufw", "allow", f"{PORT}/tcp"], capture_output=True)
    s = http.server.ThreadingHTTPServer(("0.0.0.0", PORT), Yukleyici)
    print(f"\n  Tabletinde bu bağlantıyı aç:\n\n    http://{ip()}:{PORT}/{JETON}\n\n  (Dosyayı yükleyince kendiliğinden kapanır. İptal: Ctrl+C)\n", flush=True)
    try: s.serve_forever()
    except KeyboardInterrupt: pass
    if ufw: subprocess.run(["ufw", "delete", "allow", f"{PORT}/tcp"], capture_output=True)
