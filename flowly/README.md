# Flowly

MertixtanStudios sosyal medya uygulaması — açılış animasyonu, giriş / kayıt ve "Yakında" ekranı.

## Akış

1. **Açılış (3,5 sn):** Siyah arka plan, italik *Flowly* yazısı küçükten büyüğe çıkar; RGB renkler sağdan sola akar, kenara çarpıp geri döner. Altından animasyonlu çizgi, onun altında **MertixtanStudios** belirir; ardından ekran yavaşça kaybolur.
2. **"Kayıt mı olacaksınız, giriş mi yapacaksınız?"** seçimi.
3. **Kayıt:** Ad, soyad, şifre.
4. **Giriş:** Ad soyad (veya owner kullanıcı adı) + şifre.
5. **Ana ekran:** Neon "Yakında Geliyor" ekranı.

## Owner hesapları

| Kullanıcı adı | E-posta |
|---------------|---------|
| MertixtanStudios | mertozokur@gmail.com |
| Kaplan10_p2 | — |

Şifreler `index.html` içinde düz metin olarak değil, SHA-256 özeti olarak tutulur. Owner hesapları "OWNER" rozeti görür.

Uygulamanın tamamı (HTML, CSS, JS) tek bir `index.html` dosyasındadır.

## Bilgisayarda çalıştırma

```bash
cd flowly
python -m http.server 8080      # Mac/Linux: python3
# Tarayıcıda: http://localhost:8080
```

## Android'de çalıştırma

**A) Bilgisayardan, aynı Wi-Fi ile**

```bash
python -m http.server 8080 --bind 0.0.0.0
```

Bilgisayarın yerel IP'sini öğrenin (Windows: `ipconfig` → IPv4 Address, Mac/Linux: `ip a` / `ifconfig`) ve telefonda Chrome'dan `http://192.168.x.x:8080` adresini açın. Windows güvenlik duvarı sorarsa "Özel ağlar"a izin verin.

**B) Doğrudan telefonda (Termux)**

1. F-Droid'den **Termux** kurun.
2. ```bash
   pkg install python
   termux-setup-storage
   cd ~/storage/downloads/flowly   # index.html'i Downloads/flowly klasörüne koyun
   python -m http.server 8080
   ```
3. Chrome'da `http://localhost:8080` açın.

> Kullanıcılar tarayıcının `localStorage` alanında saklanır (cihaza ve tarayıcıya özel).
> Telefonda açılan hesaplar bilgisayarda görünmez; ortak hesaplar için sunucu / veritabanı gerekir.
