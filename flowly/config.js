/*
 * Flowly yapılandırması.
 *
 * Boş bırakılan servisler "demo modunda" çalışır:
 *  - Google: gerçek Google penceresi yerine Gmail adresi soran bir pencere açılır.
 *  - E-posta: doğrulama kodu e-posta yerine ekranda bildirim olarak gösterilir.
 *
 * Gerçek kullanım için aşağıdaki değerleri doldurun (README.md'ye bakın).
 */
window.FLOWLY_CONFIG = {
  // Google Cloud Console > APIs & Services > Credentials > OAuth 2.0 Client ID (Web)
  googleClientId: "",

  // https://www.emailjs.com — şablonda {{to_email}}, {{to_name}} ve {{code}} değişkenleri kullanılmalı
  emailjs: {
    publicKey: "",
    serviceId: "",
    templateId: "",
  },
};
