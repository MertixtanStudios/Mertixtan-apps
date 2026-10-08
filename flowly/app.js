(() => {
  "use strict";

  const INTRO_MS = 3500; // açılış animasyonu toplam süresi
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
      passHash: "ae7e57ed59cd34fa5189ba2ce16a3ac65f8f6f2857b5c263c7db9fbffc7242f5",
    },
  ];

  // ---------- Yardımcılar ----------
  const $ = (sel) => document.querySelector(sel);
  const normalize = (s) => s.trim().replace(/\s+/g, " ").toLocaleLowerCase("tr-TR");

  // Saf JS SHA-256: crypto.subtle yalnızca güvenli bağlamda (https / localhost) vardır,
  // telefondan http://192.168.x.x ile açıldığında bu yedek kullanılır.
  function sha256Fallback(bytes) {
    const K = [];
    for (let n = 2, c = 0; c < 64; n++) {
      let prime = true;
      for (let d = 2; d * d <= n; d++) if (n % d === 0) { prime = false; break; }
      if (prime) K[c++] = (Math.cbrt(n) % 1) * 2 ** 32 | 0;
    }
    const H = [0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19];
    const len = bytes.length;
    const total = ((len + 9 + 63) >> 6) << 6;
    const m = new Uint8Array(total);
    m.set(bytes);
    m[len] = 0x80;
    const dv = new DataView(m.buffer);
    dv.setUint32(total - 4, len * 8);
    dv.setUint32(total - 8, Math.floor(len / 0x20000000));
    const w = new Int32Array(64);
    const rotr = (x, r) => (x >>> r) | (x << (32 - r));
    for (let off = 0; off < total; off += 64) {
      for (let i = 0; i < 16; i++) w[i] = dv.getInt32(off + i * 4);
      for (let i = 16; i < 64; i++) {
        const s0 = rotr(w[i - 15], 7) ^ rotr(w[i - 15], 18) ^ (w[i - 15] >>> 3);
        const s1 = rotr(w[i - 2], 17) ^ rotr(w[i - 2], 19) ^ (w[i - 2] >>> 10);
        w[i] = (w[i - 16] + s0 + w[i - 7] + s1) | 0;
      }
      let [a, b, c, d, e, f, g, h] = H;
      for (let i = 0; i < 64; i++) {
        const t1 = (h + (rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25)) + ((e & f) ^ (~e & g)) + K[i] + w[i]) | 0;
        const t2 = ((rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22)) + ((a & b) ^ (a & c) ^ (b & c))) | 0;
        h = g; g = f; f = e; e = (d + t1) | 0;
        d = c; c = b; b = a; a = (t1 + t2) | 0;
      }
      [a, b, c, d, e, f, g, h].forEach((v, i) => (H[i] = (H[i] + v) | 0));
    }
    return H.map((v) => (v >>> 0).toString(16).padStart(8, "0")).join("");
  }

  async function sha256(text) {
    const bytes = new TextEncoder().encode(text);
    if (!window.crypto?.subtle) return sha256Fallback(bytes);
    const buf = await crypto.subtle.digest("SHA-256", bytes);
    return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("");
  }
  const passwordHash = (id, password) => sha256(`flowly|${id}:${password}`);

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

  // Owner hesaplarını sisteme kaydet
  function seedOwners() {
    for (const o of OWNERS) upsertUser({ ...o, role: "owner" });
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

  // ---------- Giriş ----------
  $("#loginForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const data = new FormData(e.target);
    const ident = normalize(data.get("name"));
    const password = data.get("password");

    const candidates = readUsers().filter(
      (u) => normalize(u.name) === ident || (u.firstName && normalize(u.firstName) === ident)
    );

    for (const u of candidates) {
      if (u.passHash && (await passwordHash(u.id, password)) === u.passHash) {
        e.target.reset();
        enter(u);
        return;
      }
    }
    toast("Ad veya şifre hatalı.", true);
  });

  // ---------- Kayıt ----------
  $("#registerForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const data = new FormData(e.target);
    const firstName = data.get("firstName").trim();
    const lastName = data.get("lastName").trim();
    const name = `${firstName} ${lastName}`;
    const id = normalize(name);

    if (findById(id)) {
      toast("Bu ad soyad ile zaten bir hesap var. Giriş yapın.", true);
      return;
    }
    const user = {
      id,
      firstName,
      lastName,
      name,
      passHash: await passwordHash(id, data.get("password")),
      role: "user",
      createdAt: new Date().toISOString(),
    };
    upsertUser(user);
    e.target.reset();
    enter(user);
  });

  // ---------- Ana ekran ----------
  function enter(user) {
    setSession(user.id);
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
    const id = getSession();
    const user = id && findById(id);
    if (user) enter(user);
    else show("choice");
  }, INTRO_MS);
})();
