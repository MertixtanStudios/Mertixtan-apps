# Flowly

MertixtanStudios sosyal medya uygulaması — açılış animasyonu, giriş / kayıt ve "Yakında" ekranı.

## Çalıştırma

```bash
cd flowly
python3 -m http.server 8080
# http://localhost:8080
```

## Akış

1. **Açılış (3,5 sn):** Siyah arka plan, italik *Flowly* yazısı küçükten büyüğe çıkar; RGB renkler sağdan sola akar, kenara çarpıp geri döner. Altından animasyonlu çizgi, onun altında **MertixtanStudios** belirir; ardından ekran yavaşça kaybolur.
2. **"Kayıt mı olacaksınız, giriş mi yapacaksınız?"** seçimi.
3. **Giriş:** Google ile giriş ya da ad (veya e-posta) + şifre → e-posta doğrulama kodu → giriş.
4. **Kayıt:** Google hesabı ile hesap oluştur ya da ad, soyad, e-posta, şifre → e-posta doğrulama → giriş.
5. **Ana ekran:** Neon "Yakında Geliyor" ekranı.

## Owner hesapları

| Ad | E-posta |
|----|---------|
| MertixtanStudios | mertozokur@gmail.com |
| Kaplan10_p2 | — |

Şifreler `app.js` içinde düz metin olarak değil, SHA-256 özeti olarak tutulur. Owner hesapları e-posta doğrulaması olmadan doğrudan girer ve "OWNER" rozeti görür.

## Gerçek Google ve e-posta servisleri

`config.js` boş bırakılırsa uygulama **demo modunda** çalışır (Google için Gmail soran pencere açılır, doğrulama kodu ekranda gösterilir).

- **Google:** Google Cloud Console'da bir OAuth 2.0 Web Client ID oluşturun, sitenin adresini "Authorized JavaScript origins" listesine ekleyin ve `googleClientId` alanına yazın.
- **E-posta:** [EmailJS](https://www.emailjs.com) hesabı açın; şablonda `{{to_email}}`, `{{to_name}}`, `{{code}}` değişkenlerini kullanın ve `emailjs` alanlarını doldurun.

> Not: Kullanıcılar şu an tarayıcının `localStorage` alanında saklanır (cihaza özel). Çok kullanıcılı gerçek bir sosyal ağ için bir sunucu / veritabanı (ör. Firebase) gerekir.
