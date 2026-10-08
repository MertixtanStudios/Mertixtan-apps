# Flowly

MertixtanStudios sosyal medya uygulaması. Gerçek kullanıcılar, gerçek içerik, canlı yayın ve **flow** para birimi.

Flowly iki dosyadan oluşur:

| Dosya | Görevi |
|-------|--------|
| `index.html` | Uygulamanın tamamı (arayüz, tasarım, kod) |
| `server.py` | Sunucu: hesaplar, içerikler, flow, DM, canlı yayın bağlantıları. Yalnızca Python gerekir, ek paket yok. |

Veriler `data/` klasöründe tutulur (`data/db.json` ve yüklenen dosyalar için `data/media/`).

## Çalıştırma

### Android (Termux)

```bash
pkg install -y python curl
mkdir -p ~/flowly && cd ~/flowly
curl -L -o index.html https://raw.githubusercontent.com/MertixtanStudios/Mertixtan-apps/main/flowly/index.html
curl -L -o server.py https://raw.githubusercontent.com/MertixtanStudios/Mertixtan-apps/main/flowly/server.py
python server.py
```

Chrome'da **localhost:8080** adresini aç. Sunucuyu durdurmak için `Ctrl + C`.

Sonraki seferlerde: `cd ~/flowly && python server.py`

> "Address already in use" hatası alırsan eski sunucu açık kalmıştır: `pkill -f server.py` yazıp tekrar başlat.

### Bilgisayar

```bash
cd flowly
python server.py        # Windows: python, Mac/Linux: python3
```

## Diğer cihazlardan bağlanma (aynı Wi-Fi)

Sunucunun çalıştığı cihazın IP adresini öğren (ör. `192.168.1.35`) ve diğer cihazda `http://192.168.1.35:8080` adresini aç.

**Kamera, mikrofon ve ekran paylaşımı** tarayıcılarda yalnızca güvenli bağlantıda çalışır:

- Sunucunun çalıştığı cihazda `localhost` zaten güvenlidir: yayın açmak için bir sorun yok.
- Diğer cihazlar yayını **izleyebilir**, sohbet edebilir, flow gönderebilir. Ama yayın açmak ya da sohbet yayınına sesli/görüntülü katılmak için HTTPS gerekir:

```bash
pkg install -y openssl-tool        # Termux
cd ~/flowly
openssl req -x509 -newkey rsa:2048 -nodes -keyout key.pem -out cert.pem -days 365 -subj "/CN=flowly"
python server.py
```

`cert.pem` ve `key.pem` varsa sunucu otomatik olarak HTTPS açar. Diğer cihazlarda `https://192.168.1.35:8080` adresine gir; tarayıcının "güvenli değil" uyarısında **Gelişmiş → Yine de devam et** de (sertifika senin kendi cihazına ait).

## Özellikler

### Keşfet
- **Video Keşfet**, **Shorts Keşfet**, **Karışık Keşfet** modları, kategori filtreleri, arama (içerik ve kişiler).
- Video oynatıcı (yorumlar, beğeni, kaydet, paylaş, destek), dikey kaydırmalı Shorts oynatıcı, yazı + fotoğraf gönderileri.
- Görüntülenme ve beğeni sayıları gerçek kullanıcılardan gelir; sahte içerik yoktur.

### Oluştur (+)
Video yükle · Short yükle (en fazla 3 dk) · Canlı yayın · Gönderi.

### Flow (para birimi)
Herkes **35 flow** ile başlar (owner panelinden değiştirilebilir). Flow ile yapılabilen 5 şey:

1. **Canlı yayında flow gönder** — izleyici istediği kadar flow'u yayıncıya hediye eder.
2. **Desteği güçlendir** — desteklenen üreticiye flow ver; toplam 10 flow ile *Akış*, 50 flow ile *Neon* destek seviyesi.
3. **Parlayan mesaj (5 flow)** — canlı sohbette mesaj altın renkte parlar ve sabitlenir.
4. **İçeriği öne çıkar (20 flow)** — video/short 24 saat Keşfet'in en üstünde.
5. **DM ile flow gönder** — mesajlarda doğrudan flow yolla.

### Destekler
Abonelik yerine destek: desteklediğin üreticilerin yeni içeriklerinden ve canlı yayınlarından bildirim alırsın.

### Onur Panelleri
Flow Cömertleri · Yayın Yıldızları · En Çok Desteklenenler · Akışın Zirvesi. Hepsi gerçek hareketlerden hesaplanır.

### Canlı yayın
- **Sohbet Yayını:** izleyiciler istek atar, yayıncı kabul ederse sesli ya da görüntülü yayına katılır (en fazla 3 konuk). Konuklar herkes tarafından görülür ve duyulur.
- **Klasik Yayın:** kamera ile yayın, ön/arka kamera çevirme.
- **Ekran Yayını:** cihazın tüm ekranı paylaşılır.
- **Yayın ayarları:** başlık, açıklama, kategori, kapak fotoğrafı, sohbet aç/kapat, katılma istekleri, konuk sınırı. Yayın sırasında da değiştirilebilir.
- **Kontrol paneli:** beğeni, flow, izleyici sayacı, yayın süresi, yayını durdur/devam et, ses aç/kapat, yayını kapat.
- **Üstte göster:** kontrol paneli küçük pencerede (resim içinde resim) Flowly'den çıkınca da görünür.

> Ekran yayını tarayıcının ekran paylaşımı desteğine bağlıdır. Bazı Android tarayıcıları ekran paylaşımını desteklemez; bu durumda seçenek kapalı görünür.

### DM, bildirimler, profil
Gerçek zamanlı mesajlaşma (fotoğraf ve flow gönderme), bildirimler (beğeni, yorum, destek, flow, yeni içerik, canlı yayın), profil fotoğrafı ve biyografi, kaydedilenler.

## Owner hesapları ve Admin Panel

| Kullanıcı adı | E-posta |
|---------------|---------|
| MertixtanStudios | mertozokur@gmail.com |
| Kaplan10_p2 | — |

Şifreler `server.py` içinde düz metin olarak değil, PBKDF2 özeti olarak tutulur. Kullanıcı şifreleri de aynı şekilde saklanır.

**Admin Panel** yalnızca bu iki hesapta görünür ve 15 özellik içerir:

1. Genel bakış (istatistikler, kullanıcı listesi)
2. Flow ver
3. Flow al
4. Herkese flow dağıt
5. Başlangıç flow miktarı
6. Doğrulama rozeti ver/kaldır
7. Kullanıcı sustur/aç
8. Kullanıcı yasakla/kaldır
9. İçerik sil
10. İçerik öne çıkar
11. Canlı yayını sonlandır
12. Duyuru yayınla
13. Bakım modu
14. Yeni kayıtları aç/kapat
15. İşlem kayıtları (owner işlemleri ve flow hareketleri)
