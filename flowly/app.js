(() => {
  "use strict";

  const CONFIG = window.FLOWLY_CONFIG || {};
  const INTRO_MS = 3500; // açılış animasyonu toplam süresi
  const CODE_TTL_MS = 10 * 60 * 1000;
  const USERS_KEY = "flowly.users";
  const SESSION_KEY = "flowly.session";

  /*
   * Sistemde tanımlı owner hesapları.
   * Şifreler düz metin olarak değil, SHA-256 özeti olarak saklanır:
   *   sha256("flowly|" + id + ":" + şifre)
   */
  const OWNERS = [
    {
      id: "mertixtanstudios",
      name: "MertixtanStudios",
      email: "mertozokur@gmail.com",
      passHash: "c52b41c2c720c20c6bbdc0238e412e5f7d92630bd71f63e037be6b3a80a9337b",
    },
    {
      id: "kaplan10_p2",
      name: "Kaplan10_p2",
      email: "",
      passHash: "ae7e57ed59cd34fa5189ba2ce16a3ac65f8f6f2857b5c263c7db9fbffc7242f5",
    },
  ];

  // ---------- Yardımcılar ----------
  const $ = (sel) => document.querySelector(sel);

  async function sha256(text) {
    const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
    return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("");
  }
  const passwordHash = (id, password) => sha256(`flowly|${id}:${password}`);

  function loadScript(src) {
    return new Promise((resolve, reject) => {
      const s = document.createElement("script");
      s.src = src;
      s.onload = resolve;
      s.onerror = () => reject(new Error(`Yüklenemedi: ${src}`));
      document.head.appendChild(s);
    });
  }

  let toastTimer;
  function toast(msg, isError = false, ms = 3500) {
    const el = $("#toast");
    el.textContent = msg;
    el.classList.toggle("error", isError);
    el.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.classList.remove("show"), ms);
  }

  // ---------- Depolama ----------
  function readUsers() {
    try {
      return JSON.parse(localStorage.getItem(USERS_KEY)) || [];
    } catch {
      return [];
    }
  }
  function writeUsers(users) {
    localStorage.setItem(USERS_KEY, JSON.stringify(users));
  }
  function upsertUser(user) {
    const users = readUsers();
    const i = users.findIndex((u) => u.id === user.id);
    if (i >= 0) users[i] = user;
    else users.push(user);
    writeUsers(users);
  }
  const findById = (id) => readUsers().find((u) => u.id === id);
  const findByEmail = (email) =>
    readUsers().find((u) => u.email && u.email.toLowerCase() === email.toLowerCase());

  // Owner hesaplarını sisteme kaydet
  function seedOwners() {
    for (const o of OWNERS) {
      upsertUser({ ...o, role: "owner", provider: "system", verified: true });
    }
  }

  const getSession = () => {
    try { return localStorage.getItem(SESSION_KEY); } catch { return null; }
  };
  const setSession = (id) =>
    id ? localStorage.setItem(SESSION_KEY, id) : localStorage.removeItem(SESSION_KEY);

  // ---------- Ekran yönetimi ----------
  function show(id) {
    document.querySelectorAll(".screen").forEach((s) => s.classList.toggle("active", s.id === id));
  }

  document.addEventListener("click", (e) => {
    const go = e.target.closest("[data-go]");
    if (go) {
      e.preventDefault();
      show(go.dataset.go);
    }
  });

  // ---------- E-posta doğrulama ----------
  let pending = null; // { userId, code, expires }

  async function sendCode(user) {
    const code = String(Math.floor(100000 + Math.random() * 900000));
    pending = { userId: user.id, code, expires: Date.now() + CODE_TTL_MS };
    $("#verifyEmail").textContent = user.email;
    $("#verifyForm").reset();

    const ej = CONFIG.emailjs || {};
    if (ej.publicKey && ej.serviceId && ej.templateId) {
      try {
        if (!window.emailjs) {
          await loadScript("https://cdn.jsdelivr.net/npm/@emailjs/browser@4.4.1/dist/email.min.js");
          window.emailjs.init({ publicKey: ej.publicKey });
        }
        await window.emailjs.send(ej.serviceId, ej.templateId, {
          to_email: user.email,
          to_name: user.name,
          code,
        });
        toast("Doğrulama kodu e-postana gönderildi.");
      } catch (err) {
        console.error(err);
        toast("E-posta gönderilemedi. Lütfen tekrar deneyin.", true);
        return;
      }
    } else {
      toast(`Demo modu — doğrulama kodun: ${code}`, false, 12000);
    }
    show("verify");
  }

  $("#verifyForm").addEventListener("submit", (e) => {
    e.preventDefault();
    const code = new FormData(e.target).get("code").trim();
    if (!pending) return show("choice");
    if (Date.now() > pending.expires) {
      toast("Kodun süresi doldu. Yeni kod gönder.", true);
      return;
    }
    if (code !== pending.code) {
      toast("Kod hatalı.", true);
      return;
    }
    const user = findById(pending.userId);
    pending = null;
    if (!user) return show("choice");
    user.verified = true;
    upsertUser(user);
    enter(user);
  });

  $("#resendCode").addEventListener("click", (e) => {
    e.preventDefault();
    const user = pending && findById(pending.userId);
    if (user) sendCode(user);
  });

  // ---------- Giriş ----------
  $("#loginForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const data = new FormData(e.target);
    const ident = data.get("name").trim().toLowerCase();
    const password = data.get("password");

    const candidates = readUsers().filter(
      (u) =>
        u.name.toLowerCase() === ident ||
        (u.firstName && u.firstName.toLowerCase() === ident) ||
        (u.email && u.email.toLowerCase() === ident)
    );

    let user = null;
    for (const u of candidates) {
      if (u.passHash && (await passwordHash(u.id, password)) === u.passHash) {
        user = u;
        break;
      }
    }
    if (!user) {
      toast("Ad veya şifre hatalı.", true);
      return;
    }
    e.target.reset();
    // Owner hesapları doğrudan girer, diğer hesaplar e-posta doğrulamasından geçer
    if (user.role === "owner") enter(user);
    else sendCode(user);
  });

  // ---------- Kayıt ----------
  $("#registerForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const data = new FormData(e.target);
    const firstName = data.get("firstName").trim();
    const lastName = data.get("lastName").trim();
    const email = data.get("email").trim().toLowerCase();
    const password = data.get("password");

    if (findByEmail(email)) {
      toast("Bu e-posta ile zaten bir hesap var. Giriş yapın.", true);
      return;
    }
    const user = {
      id: email,
      firstName,
      lastName,
      name: `${firstName} ${lastName}`,
      email,
      passHash: await passwordHash(email, password),
      provider: "email",
      role: "user",
      verified: false,
      createdAt: new Date().toISOString(),
    };
    upsertUser(user);
    e.target.reset();
    sendCode(user);
  });

  // ---------- Google ----------
  async function googleProfile() {
    if (CONFIG.googleClientId) {
      if (!window.google?.accounts?.oauth2) {
        await loadScript("https://accounts.google.com/gsi/client");
      }
      const token = await new Promise((resolve, reject) => {
        const client = window.google.accounts.oauth2.initTokenClient({
          client_id: CONFIG.googleClientId,
          scope: "openid email profile",
          callback: (res) => (res.error ? reject(new Error(res.error)) : resolve(res.access_token)),
          error_callback: (err) => reject(new Error(err.type || "google_error")),
        });
        client.requestAccessToken();
      });
      const res = await fetch("https://www.googleapis.com/oauth2/v3/userinfo", {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) throw new Error("userinfo");
      const p = await res.json();
      return { name: p.name || p.email, email: p.email.toLowerCase(), firstName: p.given_name, lastName: p.family_name };
    }

    // Demo modu
    const dlg = $("#googleDialog");
    $("#googleForm").reset();
    dlg.showModal();
    return new Promise((resolve) => {
      dlg.addEventListener(
        "close",
        () => {
          if (dlg.returnValue !== "ok") return resolve(null);
          const d = new FormData($("#googleForm"));
          resolve({ name: d.get("name").trim(), email: d.get("email").trim().toLowerCase() });
        },
        { once: true }
      );
    });
  }

  document.querySelectorAll("[data-google]").forEach((btn) =>
    btn.addEventListener("click", async () => {
      let profile;
      try {
        profile = await googleProfile();
      } catch (err) {
        console.error(err);
        toast("Google ile bağlantı kurulamadı.", true);
        return;
      }
      if (!profile) return;

      const existing = findByEmail(profile.email);
      if (btn.dataset.google === "login") {
        if (!existing) {
          toast("Bu Google hesabına bağlı bir Flowly hesabı yok. Önce kayıt olun.", true);
          return;
        }
        if (existing.role === "owner" || existing.verified) enter(existing);
        else sendCode(existing);
        return;
      }

      // Google ile hesap oluştur
      if (existing) {
        toast("Bu e-posta ile zaten bir hesap var. Giriş yapın.", true);
        return;
      }
      const [first, ...rest] = profile.name.split(" ");
      const user = {
        id: profile.email,
        firstName: profile.firstName || first,
        lastName: profile.lastName || rest.join(" "),
        name: profile.name,
        email: profile.email,
        passHash: null,
        provider: "google",
        role: "user",
        verified: false,
        createdAt: new Date().toISOString(),
      };
      upsertUser(user);
      sendCode(user);
    })
  );

  // ---------- Ana ekran ----------
  function enter(user) {
    setSession(user.id);
    $("#toast").classList.remove("show");
    $("#userName").textContent = user.name;
    $("#ownerBadge").hidden = user.role !== "owner";
    show("home");
  }

  $("#logout").addEventListener("click", () => {
    setSession(null);
    show("choice");
  });

  // ---------- Başlangıç ----------
  seedOwners();
  setTimeout(() => {
    const user = getSession() && findById(getSession());
    if (user && (user.verified || user.role === "owner")) enter(user);
    else show("choice");
  }, INTRO_MS);
})();
