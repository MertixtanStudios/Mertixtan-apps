#!/usr/bin/env python3
"""
Flowly sunucusu — yalnızca Python standart kütüphanesi ile çalışır.

    python server.py            # http://localhost:8080
    python server.py 8090       # başka port

Aynı Wi-Fi'deki diğer cihazlar http://<bu-cihazın-ip>:8080 adresinden bağlanır.
Kamera / mikrofon / ekran paylaşımı için tarayıcılar güvenli bağlam ister:
bu cihazda localhost zaten güvenlidir; diğer cihazlar için README'deki HTTPS
adımlarına bakın (cert.pem + key.pem varsa sunucu otomatik HTTPS açar).
"""

import errno
import hashlib
import hmac
import json
import os
import queue
import re
import secrets
import ssl
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(ROOT, "data")
MEDIA_DIR = os.path.join(DATA_DIR, "media")
DB_PATH = os.path.join(DATA_DIR, "db.json")

PBKDF2_ROUNDS = 200_000
MAX_VIDEO = 512 * 1024 * 1024
MAX_IMAGE = 10 * 1024 * 1024
HOST_GRACE_SECONDS = 20
RECONNECT_GRACE_SECONDS = 6

# Flow fiyatları
HIGHLIGHT_COST = 5
PROMOTE_COST = 20
PROMOTE_SECONDS = 24 * 3600

CATEGORIES = {"oyun", "muzik", "teknoloji", "spor", "komedi", "egitim", "seyahat", "yemek", "sanat", "diger"}
LIVE_TYPES = {"chat", "classic", "screen"}

# Owner hesapları (şifreler PBKDF2 özeti olarak saklanır, düz metin yoktur)
OWNERS = [
    {
        "id": "mertixtanstudios",
        "name": "MertixtanStudios",
        "email": "mertozokur@gmail.com",
        "salt": "f10w1y-0wn3r-m5",
        "hash": "24eda46f610aa3ecb3a305e29327805af30c7f51f419b4263e859b658cb210bb",
    },
    {
        "id": "kaplan10_p2",
        "name": "Kaplan10_p2",
        "email": "",
        "salt": "f10w1y-0wn3r-k10",
        "hash": "3d88212f1cb432a466af405b4a2f9186e937df6acd0b90f69620314242fff990",
    },
]


def now_ms():
    return int(time.time() * 1000)


def new_id(n=8):
    return secrets.token_hex(n)


def normalize(s):
    s = re.sub(r"\s+", " ", str(s or "")).strip()
    # Türkçe küçük harf
    return s.replace("I", "ı").replace("İ", "i").lower()


def hash_pw(password, salt):
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), PBKDF2_ROUNDS).hex()


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


# ---------------------------------------------------------------- Veri tabanı
LOCK = threading.RLock()
DB = {}


def load_db():
    global DB
    os.makedirs(MEDIA_DIR, exist_ok=True)
    if os.path.exists(DB_PATH):
        with open(DB_PATH, encoding="utf-8") as f:
            DB = json.load(f)
    DB.setdefault("config", {})
    DB["config"].setdefault("startingFlows", 35)
    DB["config"].setdefault("announcement", "")
    DB["config"].setdefault("maintenance", False)
    DB["config"].setdefault("registrationOpen", True)
    DB["config"].setdefault("featured", None)
    for key in ("users", "sessions", "content", "media", "notifications"):
        DB.setdefault(key, {})
    for key in ("supports", "dms", "tx", "audit"):
        DB.setdefault(key, [])
    for o in OWNERS:
        u = DB["users"].get(o["id"])
        if not u:
            u = new_user(o["id"], o["name"], "", "", DB["config"]["startingFlows"])
            DB["users"][o["id"]] = u
        u.update(role="owner", name=o["name"], email=o["email"], salt=o["salt"], hash=o["hash"], banned=False)
    save_db()


def save_db():
    tmp = DB_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(DB, f, ensure_ascii=False)
    os.replace(tmp, DB_PATH)


def new_user(uid, name, first, last, flows):
    return {
        "id": uid, "name": name, "firstName": first, "lastName": last,
        "role": "user", "salt": "", "hash": "", "flows": flows,
        "bio": "", "avatarId": None, "verified": False, "muted": False, "banned": False,
        "saved": [], "createdAt": now_ms(),
    }


def audit(by, action, detail):
    DB["audit"].append({"at": now_ms(), "by": by, "action": action, "detail": detail})
    DB["audit"] = DB["audit"][-500:]


def notify(user_id, kind, from_id=None, ref=None, text=""):
    if not user_id or user_id == from_id or user_id not in DB["users"]:
        return
    lst = DB["notifications"].setdefault(user_id, [])
    lst.append({"id": new_id(6), "type": kind, "from": from_id, "ref": ref, "text": text, "at": now_ms(), "read": False})
    DB["notifications"][user_id] = lst[-100:]
    emit_users([user_id], "notify", {"type": kind, "from": from_id, "text": text})


def transfer(from_id, to_id, amount, kind, ref=None):
    """Flow aktarımı. from_id/to_id None ise sistem."""
    try:
        amount = int(amount)
    except (TypeError, ValueError):
        raise ApiError(400, "Geçersiz flow miktarı.")
    if amount < 1 or amount > 100000:
        raise ApiError(400, "Flow miktarı 1 ile 100000 arasında olmalı.")
    if from_id:
        u = DB["users"][from_id]
        if u["flows"] < amount:
            raise ApiError(400, f"Yetersiz flow. Bakiyen: {u['flows']}")
        u["flows"] -= amount
    if to_id:
        DB["users"][to_id]["flows"] += amount
    DB["tx"].append({"id": new_id(6), "from": from_id, "to": to_id, "amount": amount, "kind": kind, "ref": ref, "at": now_ms()})
    DB["tx"] = DB["tx"][-5000:]
    for uid in {from_id, to_id} - {None}:
        emit_users([uid], "sync", {})
    return amount


# ---------------------------------------------------------------- Gerçek zamanlı (SSE)
CLIENTS = {}  # cid -> {"user": uid, "q": Queue}
LIVES = {}  # bellek içi canlı yayınlar


def emit_raw(cids, event, data):
    payload = json.dumps({"event": event, "data": data}, ensure_ascii=False)
    for cid in cids:
        c = CLIENTS.get(cid)
        if c:
            c["q"].put(payload)


def emit_users(user_ids, event, data):
    ids = set(user_ids)
    emit_raw([cid for cid, c in list(CLIENTS.items()) if c["user"] in ids], event, data)


def emit_all(event, data):
    emit_raw(list(CLIENTS.keys()), event, data)


def user_online(uid):
    return any(c["user"] == uid for c in CLIENTS.values())


# ---------------------------------------------------------------- Kamuya açık görünümler
def public_user(u, viewer):
    sup = sum(1 for s in DB["supports"] if s["to"] == u["id"])
    out = {
        "id": u["id"], "name": u["name"], "role": u["role"], "bio": u["bio"],
        "avatarId": u["avatarId"], "verified": u["verified"], "supporters": sup,
        "online": user_online(u["id"]), "createdAt": u["createdAt"],
    }
    if viewer and viewer["role"] == "owner":
        out.update(flows=u["flows"], banned=u["banned"], muted=u["muted"])
    return out


def public_content(c, viewer):
    return {
        "id": c["id"], "kind": c["kind"], "title": c["title"], "description": c["description"],
        "category": c["category"], "mediaId": c.get("mediaId"), "posterId": c.get("posterId"),
        "duration": c.get("duration", 0), "authorId": c["authorId"], "createdAt": c["createdAt"],
        "likes": len(c["likes"]), "liked": bool(viewer) and viewer["id"] in c["likes"],
        "views": len(c["views"]), "comments": len(c["comments"]),
        "saved": bool(viewer) and c["id"] in viewer["saved"],
        "boosted": c.get("boostedUntil", 0) > now_ms(),
    }


def public_live(l):
    return {
        "id": l["id"], "hostId": l["hostId"], "type": l["type"], "title": l["title"],
        "description": l["description"], "coverId": l["coverId"], "category": l["category"],
        "startedAt": l["startedAt"], "viewers": len(set(l["viewers"].values())), "likes": l["likes"],
        "flows": l["flows"], "paused": l["paused"], "hostMuted": l["hostMuted"], "chatEnabled": l["chatEnabled"],
        "allowRequests": l["allowRequests"], "maxGuests": l["maxGuests"], "guests": l["guests"],
        "pinned": l["pinned"],
    }


def visible_content(viewer):
    banned = {uid for uid, u in DB["users"].items() if u["banned"]}
    is_owner = viewer and viewer["role"] == "owner"
    return [c for c in DB["content"].values() if is_owner or c["authorId"] not in banned]


def leaderboards():
    def top(counter, n=10):
        return [{"userId": k, "value": v} for k, v in sorted(counter.items(), key=lambda kv: -kv[1])[:n] if k in DB["users"]]

    generous, stars = {}, {}
    for t in DB["tx"]:
        if t["kind"] in ("gift", "highlight", "boost", "transfer") and t["from"]:
            generous[t["from"]] = generous.get(t["from"], 0) + t["amount"]
        if t["kind"] in ("gift", "highlight") and t["to"]:
            stars[t["to"]] = stars.get(t["to"], 0) + t["amount"]
    supported = {}
    for s in DB["supports"]:
        supported[s["to"]] = supported.get(s["to"], 0) + 1
    content = sorted((c for c in DB["content"].values() if c["likes"]), key=lambda c: -len(c["likes"]))[:10]
    return {
        "generous": top(generous),
        "stars": top(stars),
        "supported": top(supported),
        "content": [{"contentId": c["id"], "value": len(c["likes"])} for c in content],
    }


# ---------------------------------------------------------------- HTTP
ROUTES = []


def route(method, pattern, auth=True, owner=False, open_in_maintenance=False):
    def deco(fn):
        ROUTES.append((method, re.compile(f"^{pattern}$"), fn, auth, owner, open_in_maintenance))
        return fn
    return deco


class Handler(BaseHTTPRequestHandler):
    server_version = "Flowly/1.0"

    def log_message(self, fmt, *args):
        pass

    # --- yardımcılar
    def send_json(self, status, obj):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def read_json(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length > 256 * 1024:
            raise ApiError(413, "İstek çok büyük.")
        raw = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(raw or b"{}")
        except ValueError:
            raise ApiError(400, "Geçersiz JSON.")
        if not isinstance(data, dict):
            raise ApiError(400, "Geçersiz istek.")
        return data

    def current_user(self, token=None):
        auth = self.headers.get("Authorization", "")
        token = token or (auth[7:] if auth.startswith("Bearer ") else None)
        if not token:
            return None
        uid = DB["sessions"].get(token)
        u = DB["users"].get(uid) if uid else None
        if not u or u["banned"]:
            return None
        return u

    # --- yönlendirme
    def do_GET(self):
        self.dispatch("GET")

    def do_POST(self):
        self.dispatch("POST")

    def dispatch(self, method):
        url = urlparse(self.path)
        path = unquote(url.path)
        try:
            if method == "GET" and path in ("/", "/index.html"):
                return self.serve_file(os.path.join(ROOT, "index.html"), "text/html; charset=utf-8")
            if method == "GET" and path.startswith("/media/"):
                return self.serve_media(path[len("/media/"):])
            if method == "GET" and path == "/api/events":
                return self.serve_events(parse_qs(url.query))
            if method == "POST" and path == "/api/media":
                with LOCK:
                    user = self.current_user()
                if not user:
                    raise ApiError(401, "Oturum gerekli.")
                return self.upload_media(user, parse_qs(url.query))
            for m, rx, fn, need_auth, need_owner, open_maint in ROUTES:
                if m != method:
                    continue
                match = rx.match(path)
                if not match:
                    continue
                body = self.read_json() if method == "POST" else {}
                with LOCK:
                    user = self.current_user()
                    if need_auth and not user:
                        raise ApiError(401, "Oturum gerekli.")
                    if need_owner and (not user or user["role"] != "owner"):
                        raise ApiError(403, "Bu işlem yalnızca owner hesaplarına açık.")
                    if (DB["config"]["maintenance"] and method == "POST" and not open_maint
                            and not (user and user["role"] == "owner")):
                        raise ApiError(503, "Flowly şu an bakımda.")
                    result = fn(self, user, body, *match.groups())
                    if method == "POST":
                        save_db()
                return self.send_json(200, result if result is not None else {"ok": True})
            raise ApiError(404, "Bulunamadı.")
        except ApiError as e:
            self.send_json(e.status, {"error": e.message})
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:  # beklenmeyen hata
            import traceback
            traceback.print_exc()
            try:
                self.send_json(500, {"error": f"Sunucu hatası: {e}"})
            except Exception:
                pass

    # --- statik dosya
    def serve_file(self, path, ctype):
        with open(path, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def serve_media(self, mid):
        if not re.fullmatch(r"[0-9a-f]{16}", mid):
            raise ApiError(404, "Bulunamadı.")
        meta = DB["media"].get(mid)
        path = os.path.join(MEDIA_DIR, mid)
        if not meta or not os.path.exists(path):
            raise ApiError(404, "Bulunamadı.")
        size = os.path.getsize(path)
        start, end = 0, size - 1
        rng = self.headers.get("Range")
        status = 200
        if rng:
            m = re.match(r"bytes=(\d*)-(\d*)", rng)
            if m:
                if m.group(1):
                    start = int(m.group(1))
                    if m.group(2):
                        end = min(int(m.group(2)), size - 1)
                elif m.group(2):
                    start = max(0, size - int(m.group(2)))
                if start > end or start >= size:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.end_headers()
                    return
                status = 206
        length = end - start + 1
        self.send_response(status)
        self.send_header("Content-Type", meta["type"])
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "public, max-age=86400")
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        with open(path, "rb") as f:
            f.seek(start)
            left = length
            while left > 0:
                chunk = f.read(min(256 * 1024, left))
                if not chunk:
                    break
                self.wfile.write(chunk)
                left -= len(chunk)

    def upload_media(self, user, qs):
        if DB["config"]["maintenance"] and user["role"] != "owner":
            raise ApiError(503, "Flowly şu an bakımda.")
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if not re.fullmatch(r"(video|image)/[a-z0-9.+-]+", ctype):
            raise ApiError(400, "Yalnızca video ve görsel yüklenebilir.")
        limit = MAX_VIDEO if ctype.startswith("video/") else MAX_IMAGE
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            raise ApiError(400, "Boş dosya.")
        if length > limit:
            raise ApiError(413, f"Dosya çok büyük (en fazla {limit // (1024 * 1024)} MB).")
        mid = new_id(8)
        path = os.path.join(MEDIA_DIR, mid)
        left = length
        with open(path, "wb") as f:
            while left > 0:
                chunk = self.rfile.read(min(256 * 1024, left))
                if not chunk:
                    break
                f.write(chunk)
                left -= len(chunk)
        if left:
            os.remove(path)
            raise ApiError(400, "Yükleme yarıda kesildi.")
        with LOCK:
            DB["media"][mid] = {"id": mid, "type": ctype, "size": length, "ownerId": user["id"], "at": now_ms()}
            save_db()
        self.send_json(200, {"id": mid})

    # --- SSE
    def serve_events(self, qs):
        token = (qs.get("token") or [""])[0]
        cid = (qs.get("cid") or [""])[0]
        with LOCK:
            user = self.current_user(token)
        if not user or not re.fullmatch(r"[0-9a-zA-Z]{8,40}", cid):
            raise ApiError(401, "Oturum gerekli.")
        q = queue.Queue()
        with LOCK:
            was_online = user_online(user["id"])
            CLIENTS[cid] = {"user": user["id"], "q": q}
            if not was_online:
                emit_all("presence", {"userId": user["id"], "online": True})
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        try:
            self.wfile.write(b"retry: 2000\n\n")
            self.wfile.flush()
            while True:
                try:
                    msg = q.get(timeout=15)
                    self.wfile.write(f"data: {msg}\n\n".encode())
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            with LOCK:
                if CLIENTS.get(cid, {}).get("q") is q:
                    del CLIENTS[cid]
                    # Kısa kopmalarda (yeniden bağlanma) yayından düşürmemek için bekle
                    threading.Timer(RECONNECT_GRACE_SECONDS, maybe_gone, args=(cid, user["id"])).start()


def maybe_gone(cid, uid):
    with LOCK:
        if cid not in CLIENTS:
            client_gone(cid, uid)


def client_gone(cid, uid):
    for live in list(LIVES.values()):
        if cid in live["viewers"]:
            leave_live(live, cid)
        if live["hostCid"] == cid:
            live["hostLostAt"] = time.time()
            threading.Timer(HOST_GRACE_SECONDS, check_host, args=(live["id"], cid)).start()
    if not user_online(uid):
        emit_all("presence", {"userId": uid, "online": False})


def check_host(live_id, cid):
    with LOCK:
        live = LIVES.get(live_id)
        if live and live["hostCid"] == cid and cid not in CLIENTS:
            end_live(live, "Yayıncının bağlantısı koptu.")


# ---------------------------------------------------------------- Kimlik
@route("GET", "/api/ping", auth=False)
def api_ping(h, user, body):
    return {"ok": True, "app": "flowly"}


@route("POST", "/api/register", auth=False, open_in_maintenance=True)
def api_register(h, user, body):
    if not DB["config"]["registrationOpen"]:
        raise ApiError(403, "Yeni kayıtlar şu an kapalı.")
    first = re.sub(r"\s+", " ", str(body.get("firstName", ""))).strip()[:30]
    last = re.sub(r"\s+", " ", str(body.get("lastName", ""))).strip()[:30]
    pw = str(body.get("password", ""))
    if not first or not last:
        raise ApiError(400, "Ad ve soyad gerekli.")
    if len(pw) < 6:
        raise ApiError(400, "Şifre en az 6 karakter olmalı.")
    name = f"{first} {last}"
    uid = normalize(name)
    if uid in DB["users"]:
        raise ApiError(409, "Bu ad soyad ile zaten bir hesap var.")
    u = new_user(uid, name, first, last, DB["config"]["startingFlows"])
    u["salt"] = secrets.token_hex(12)
    u["hash"] = hash_pw(pw, u["salt"])
    DB["users"][uid] = u
    DB["tx"].append({"id": new_id(6), "from": None, "to": uid, "amount": u["flows"], "kind": "welcome", "ref": None, "at": now_ms()})
    token = secrets.token_hex(24)
    DB["sessions"][token] = uid
    emit_all("sync", {})
    return {"token": token}


@route("POST", "/api/login", auth=False, open_in_maintenance=True)
def api_login(h, user, body):
    ident = normalize(body.get("name", ""))
    pw = str(body.get("password", ""))
    candidates = [u for u in DB["users"].values()
                  if normalize(u["name"]) == ident or normalize(u.get("firstName", "")) == ident or u["id"] == ident]
    for u in candidates:
        if u["hash"] and hmac.compare_digest(hash_pw(pw, u["salt"]), u["hash"]):
            if u["banned"]:
                raise ApiError(403, "Bu hesap yasaklandı.")
            token = secrets.token_hex(24)
            DB["sessions"][token] = u["id"]
            return {"token": token}
    raise ApiError(401, "Ad veya şifre hatalı.")


@route("POST", "/api/logout", open_in_maintenance=True)
def api_logout(h, user, body):
    auth = h.headers.get("Authorization", "")[7:]
    DB["sessions"].pop(auth, None)


@route("GET", "/api/state")
def api_state(h, user, body):
    me = dict(public_user(user, user))
    me.update(flows=user["flows"], muted=user["muted"], saved=user["saved"])
    me["supporting"] = [{"to": s["to"], "flows": s["flows"], "since": s["since"]} for s in DB["supports"] if s["from"] == user["id"]]
    notes = DB["notifications"].get(user["id"], [])
    banned = {uid for uid, u in DB["users"].items() if u["banned"]}
    users = [public_user(u, user) for u in DB["users"].values() if user["role"] == "owner" or not u["banned"]]
    return {
        "me": me,
        "unread": sum(1 for n in notes if not n["read"]),
        "config": {k: DB["config"][k] for k in ("announcement", "maintenance", "registrationOpen", "startingFlows", "featured")},
        "users": users,
        "content": [public_content(c, user) for c in visible_content(user)],
        "lives": [public_live(l) for l in LIVES.values() if l["hostId"] not in banned],
        "leaderboards": leaderboards(),
    }


# ---------------------------------------------------------------- Profil
@route("POST", "/api/profile")
def api_profile(h, user, body):
    if "bio" in body:
        user["bio"] = str(body["bio"])[:300]
    if "avatarId" in body:
        mid = body["avatarId"]
        if mid is not None:
            m = DB["media"].get(mid)
            if not m or m["ownerId"] != user["id"] or not m["type"].startswith("image/"):
                raise ApiError(400, "Geçersiz profil fotoğrafı.")
        user["avatarId"] = mid
    emit_all("sync", {})


@route("GET", "/api/notifications")
def api_notifications(h, user, body):
    return {"items": list(reversed(DB["notifications"].get(user["id"], [])))}


@route("POST", "/api/notifications/read")
def api_notifications_read(h, user, body):
    for n in DB["notifications"].get(user["id"], []):
        n["read"] = True
    emit_users([user["id"]], "sync", {})


@route("GET", "/api/wallet")
def api_wallet(h, user, body):
    items = [t for t in DB["tx"] if user["id"] in (t["from"], t["to"])]
    return {"flows": user["flows"], "items": list(reversed(items[-100:]))}


# ---------------------------------------------------------------- İçerik
def get_content(cid):
    c = DB["content"].get(cid)
    if not c:
        raise ApiError(404, "İçerik bulunamadı.")
    return c


def own_media(user, mid, prefix):
    if mid is None:
        return None
    m = DB["media"].get(mid)
    if not m or m["ownerId"] != user["id"] or not m["type"].startswith(prefix):
        raise ApiError(400, "Geçersiz dosya.")
    return mid


@route("POST", "/api/content")
def api_content_create(h, user, body):
    kind = body.get("kind")
    if kind not in ("video", "short", "post"):
        raise ApiError(400, "Geçersiz içerik türü.")
    title = str(body.get("title", "")).strip()[:120]
    desc = str(body.get("description", "")).strip()[:3000]
    cat = body.get("category") if body.get("category") in CATEGORIES else "diger"
    if kind == "post":
        if not desc and not body.get("imageId"):
            raise ApiError(400, "Gönderi boş olamaz.")
        media = None
        poster = own_media(user, body.get("imageId"), "image/")
    else:
        if not title:
            raise ApiError(400, "Başlık gerekli.")
        media = own_media(user, body.get("mediaId"), "video/")
        if not media:
            raise ApiError(400, "Video dosyası gerekli.")
        poster = own_media(user, body.get("posterId"), "image/")
    cid = new_id(8)
    DB["content"][cid] = {
        "id": cid, "kind": kind, "title": title, "description": desc, "category": cat,
        "mediaId": media, "posterId": poster, "duration": max(0, int(body.get("duration") or 0)),
        "authorId": user["id"], "createdAt": now_ms(), "likes": [], "views": [], "comments": [],
        "boostedUntil": 0,
    }
    for s in DB["supports"]:
        if s["to"] == user["id"]:
            notify(s["from"], "content", user["id"], cid, title or desc[:60])
    emit_all("sync", {})
    return {"id": cid}


@route("POST", "/api/content/([0-9a-f]{16})/delete")
def api_content_delete(h, user, body, cid):
    c = get_content(cid)
    if c["authorId"] != user["id"] and user["role"] != "owner":
        raise ApiError(403, "Bu içeriği silemezsin.")
    for mid in (c.get("mediaId"), c.get("posterId")):
        if mid and mid in DB["media"]:
            del DB["media"][mid]
            try:
                os.remove(os.path.join(MEDIA_DIR, mid))
            except OSError:
                pass
    del DB["content"][cid]
    for u in DB["users"].values():
        if cid in u["saved"]:
            u["saved"].remove(cid)
    if DB["config"]["featured"] == cid:
        DB["config"]["featured"] = None
    if user["role"] == "owner" and c["authorId"] != user["id"]:
        audit(user["id"], "İçerik silindi", f"{c['title'] or c['description'][:40]} ({c['authorId']})")
    emit_all("sync", {})


@route("POST", "/api/content/([0-9a-f]{16})/like")
def api_like(h, user, body, cid):
    c = get_content(cid)
    if user["id"] in c["likes"]:
        c["likes"].remove(user["id"])
    else:
        c["likes"].append(user["id"])
        notify(c["authorId"], "like", user["id"], cid, c["title"] or c["description"][:60])
    emit_all("sync", {})
    return {"liked": user["id"] in c["likes"], "likes": len(c["likes"])}


@route("POST", "/api/content/([0-9a-f]{16})/view")
def api_view(h, user, body, cid):
    c = get_content(cid)
    if user["id"] not in c["views"]:
        c["views"].append(user["id"])
        emit_all("sync", {})
    return {"views": len(c["views"])}


@route("POST", "/api/content/([0-9a-f]{16})/save")
def api_save(h, user, body, cid):
    get_content(cid)
    if cid in user["saved"]:
        user["saved"].remove(cid)
    else:
        user["saved"].append(cid)
    emit_users([user["id"]], "sync", {})
    return {"saved": cid in user["saved"]}


@route("GET", "/api/content/([0-9a-f]{16})/comments")
def api_comments(h, user, body, cid):
    return {"items": get_content(cid)["comments"]}


@route("POST", "/api/content/([0-9a-f]{16})/comments")
def api_comment_add(h, user, body, cid):
    c = get_content(cid)
    if user["muted"]:
        raise ApiError(403, "Susturulduğun için yorum yapamazsın.")
    text = str(body.get("text", "")).strip()[:1000]
    if not text:
        raise ApiError(400, "Yorum boş olamaz.")
    item = {"id": new_id(6), "userId": user["id"], "text": text, "at": now_ms()}
    c["comments"].append(item)
    notify(c["authorId"], "comment", user["id"], cid, text[:80])
    emit_all("comment", {"contentId": cid, "item": item})
    emit_all("sync", {})
    return item


@route("POST", "/api/content/([0-9a-f]{16})/comments/([0-9a-f]{12})/delete")
def api_comment_delete(h, user, body, cid, comment_id):
    c = get_content(cid)
    item = next((x for x in c["comments"] if x["id"] == comment_id), None)
    if not item:
        raise ApiError(404, "Yorum bulunamadı.")
    if user["id"] not in (item["userId"], c["authorId"]) and user["role"] != "owner":
        raise ApiError(403, "Bu yorumu silemezsin.")
    c["comments"].remove(item)
    emit_all("comment", {"contentId": cid, "deleted": comment_id})
    emit_all("sync", {})


# Flow özelliği 4: içeriği öne çıkar
@route("POST", "/api/content/([0-9a-f]{16})/promote")
def api_promote(h, user, body, cid):
    c = get_content(cid)
    if c["authorId"] != user["id"]:
        raise ApiError(403, "Yalnızca kendi içeriğini öne çıkarabilirsin.")
    transfer(user["id"], None, PROMOTE_COST, "promote", cid)
    c["boostedUntil"] = max(c.get("boostedUntil", 0), now_ms()) + PROMOTE_SECONDS * 1000
    emit_all("sync", {})


# ---------------------------------------------------------------- Destek
def find_support(a, b):
    return next((s for s in DB["supports"] if s["from"] == a and s["to"] == b), None)


@route("POST", "/api/support/([^/]+)")
def api_support(h, user, body, target):
    if target not in DB["users"] or target == user["id"]:
        raise ApiError(400, "Geçersiz kullanıcı.")
    s = find_support(user["id"], target)
    if s:
        DB["supports"].remove(s)
    else:
        DB["supports"].append({"from": user["id"], "to": target, "flows": 0, "since": now_ms()})
        notify(target, "support", user["id"], None, "")
    emit_all("sync", {})
    return {"supporting": not s}


# Flow özelliği 2: desteği flow ile güçlendir
@route("POST", "/api/support/([^/]+)/boost")
def api_support_boost(h, user, body, target):
    if target not in DB["users"] or target == user["id"]:
        raise ApiError(400, "Geçersiz kullanıcı.")
    s = find_support(user["id"], target)
    if not s:
        s = {"from": user["id"], "to": target, "flows": 0, "since": now_ms()}
        DB["supports"].append(s)
    amount = transfer(user["id"], target, body.get("amount"), "boost", target)
    s["flows"] += amount
    notify(target, "boost", user["id"], None, f"{amount} flow")
    emit_all("sync", {})
    return {"flows": s["flows"]}


# ---------------------------------------------------------------- DM
@route("GET", "/api/dm")
def api_dm(h, user, body):
    return {"items": [m for m in DB["dms"] if user["id"] in (m["from"], m["to"])][-2000:]}


@route("POST", "/api/dm")
def api_dm_send(h, user, body):
    to = body.get("to")
    if to not in DB["users"] or to == user["id"] or DB["users"][to]["banned"]:
        raise ApiError(400, "Geçersiz alıcı.")
    if user["muted"]:
        raise ApiError(403, "Susturulduğun için mesaj gönderemezsin.")
    text = str(body.get("text", "")).strip()[:2000]
    image = own_media(user, body.get("imageId"), "image/")
    flows = 0
    if body.get("flows"):
        # Flow özelliği 5: DM ile flow gönder
        flows = transfer(user["id"], to, body.get("flows"), "transfer", to)
        notify(to, "flow", user["id"], None, f"{flows} flow")
    if not text and not image and not flows:
        raise ApiError(400, "Mesaj boş olamaz.")
    msg = {"id": new_id(6), "from": user["id"], "to": to, "text": text, "imageId": image, "flows": flows, "at": now_ms()}
    DB["dms"].append(msg)
    DB["dms"] = DB["dms"][-20000:]
    emit_users([user["id"], to], "dm", msg)
    return msg


# ---------------------------------------------------------------- Canlı yayın
def get_live(lid):
    l = LIVES.get(lid)
    if not l:
        raise ApiError(404, "Yayın bulunamadı ya da sona erdi.")
    return l


def live_cids(live):
    return [live["hostCid"], *live["viewers"].keys()]


def emit_live(live, event, data):
    data = dict(data, liveId=live["id"])
    emit_raw(live_cids(live), event, data)


def live_stats(live):
    emit_live(live, "live:stats", public_live(live))


def leave_live(live, cid):
    uid = live["viewers"].pop(cid, None)
    if uid is None:
        return
    still_here = uid in live["viewers"].values()
    if not still_here:
        live["requests"].pop(uid, None)
        if uid in live["guests"]:
            del live["guests"][uid]
            emit_live(live, "live:guests", {"guests": live["guests"]})
    emit_raw([live["hostCid"]], "live:viewer-leave", {"liveId": live["id"], "cid": cid, "userId": uid})
    emit_raw([live["hostCid"]], "live:requests", {"liveId": live["id"], "requests": live["requests"]})
    live_stats(live)


def end_live(live, reason=""):
    emit_live(live, "live:ended", {"reason": reason})
    LIVES.pop(live["id"], None)
    emit_all("sync", {})


def settings_from(body, live=None):
    out = {}
    if "title" in body or not live:
        title = str(body.get("title", "")).strip()[:100]
        if not title:
            raise ApiError(400, "Yayın başlığı gerekli.")
        out["title"] = title
    if "description" in body:
        out["description"] = str(body["description"]).strip()[:1000]
    if "category" in body:
        out["category"] = body["category"] if body["category"] in CATEGORIES else "diger"
    if "chatEnabled" in body:
        out["chatEnabled"] = bool(body["chatEnabled"])
    if "allowRequests" in body:
        out["allowRequests"] = bool(body["allowRequests"])
    if "maxGuests" in body:
        try:
            out["maxGuests"] = max(1, min(3, int(body["maxGuests"])))
        except (TypeError, ValueError):
            raise ApiError(400, "Geçersiz konuk sayısı.")
    return out


@route("POST", "/api/live/start")
def api_live_start(h, user, body):
    for old in list(LIVES.values()):
        if old["hostId"] == user["id"]:
            if old["hostCid"] in CLIENTS:
                raise ApiError(409, "Zaten açık bir yayının var.")
            end_live(old, "Yayın sona erdi.")  # sayfası yenilenmiş eski yayın
    ltype = body.get("type")
    if ltype not in LIVE_TYPES:
        raise ApiError(400, "Geçersiz yayın türü.")
    cid = str(body.get("cid", ""))
    if cid not in CLIENTS:
        raise ApiError(400, "Gerçek zamanlı bağlantı yok, sayfayı yenile.")
    s = settings_from(body)
    lid = new_id(8)
    live = {
        "id": lid, "hostId": user["id"], "hostCid": cid, "type": ltype,
        "title": s["title"], "description": s.get("description", ""), "category": s.get("category", "diger"),
        "coverId": own_media(user, body.get("coverId"), "image/"),
        "chatEnabled": s.get("chatEnabled", True), "allowRequests": s.get("allowRequests", ltype == "chat"),
        "maxGuests": s.get("maxGuests", 3), "startedAt": now_ms(), "paused": False, "hostMuted": False,
        "likes": 0, "flows": 0, "viewers": {}, "requests": {}, "guests": {}, "chat": [], "pinned": None,
        "likeTimes": {},
    }
    LIVES[lid] = live
    for s2 in DB["supports"]:
        if s2["to"] == user["id"]:
            notify(s2["from"], "live", user["id"], lid, live["title"])
    emit_all("sync", {})
    return {"id": lid}


@route("POST", "/api/live/([0-9a-f]{16})/settings")
def api_live_settings(h, user, body, lid):
    live = get_live(lid)
    if live["hostId"] != user["id"]:
        raise ApiError(403, "Yalnızca yayıncı ayarları değiştirebilir.")
    live.update(settings_from(body, live))
    if "coverId" in body:
        live["coverId"] = own_media(user, body.get("coverId"), "image/")
    live_stats(live)
    emit_all("sync", {})


@route("POST", "/api/live/([0-9a-f]{16})/state")
def api_live_state(h, user, body, lid):
    live = get_live(lid)
    if live["hostId"] != user["id"]:
        raise ApiError(403, "Yalnızca yayıncı.")
    if "paused" in body:
        live["paused"] = bool(body["paused"])
    if "hostMuted" in body:
        live["hostMuted"] = bool(body["hostMuted"])
    live_stats(live)
    emit_all("sync", {})


@route("POST", "/api/live/([0-9a-f]{16})/end")
def api_live_end(h, user, body, lid):
    live = get_live(lid)
    if live["hostId"] != user["id"] and user["role"] != "owner":
        raise ApiError(403, "Bu yayını kapatamazsın.")
    if live["hostId"] != user["id"]:
        audit(user["id"], "Yayın sonlandırıldı", f"{live['title']} ({live['hostId']})")
    end_live(live, "Yayın sona erdi." if live["hostId"] == user["id"] else "Yayın bir owner tarafından sonlandırıldı.")


@route("POST", "/api/live/([0-9a-f]{16})/join")
def api_live_join(h, user, body, lid):
    live = get_live(lid)
    cid = str(body.get("cid", ""))
    if cid not in CLIENTS or live["hostId"] == user["id"]:
        raise ApiError(400, "Yayına katılınamadı.")
    live["viewers"][cid] = user["id"]
    emit_raw([live["hostCid"]], "live:viewer-join", {"liveId": lid, "cid": cid, "userId": user["id"]})
    live_stats(live)
    return {"live": public_live(live), "chat": live["chat"][-60:], "hostCid": live["hostCid"]}


@route("POST", "/api/live/([0-9a-f]{16})/leave")
def api_live_leave(h, user, body, lid):
    live = LIVES.get(lid)
    if live:
        leave_live(live, str(body.get("cid", "")))


@route("POST", "/api/live/([0-9a-f]{16})/like")
def api_live_like(h, user, body, lid):
    live = get_live(lid)
    t = time.time()
    if t - live["likeTimes"].get(user["id"], 0) < 0.25:
        return {"likes": live["likes"]}
    live["likeTimes"][user["id"]] = t
    live["likes"] += 1
    live_stats(live)
    return {"likes": live["likes"]}


def push_chat(live, msg):
    live["chat"].append(msg)
    live["chat"] = live["chat"][-200:]
    emit_live(live, "live:chat", {"msg": msg})


@route("POST", "/api/live/([0-9a-f]{16})/chat")
def api_live_chat(h, user, body, lid):
    live = get_live(lid)
    if not live["chatEnabled"] and live["hostId"] != user["id"]:
        raise ApiError(403, "Bu yayında sohbet kapalı.")
    if user["muted"]:
        raise ApiError(403, "Susturulduğun için yazamazsın.")
    text = str(body.get("text", "")).strip()[:300]
    if not text:
        raise ApiError(400, "Mesaj boş olamaz.")
    highlight = bool(body.get("highlight"))
    if highlight:
        if live["hostId"] == user["id"]:
            raise ApiError(400, "Kendi yayınında parlayan mesaj gönderemezsin.")
        # Flow özelliği 3: parlayan (sabitlenen) mesaj
        transfer(user["id"], live["hostId"], HIGHLIGHT_COST, "highlight", lid)
        live["flows"] += HIGHLIGHT_COST
    msg = {"id": new_id(6), "userId": user["id"], "text": text, "highlight": highlight, "at": now_ms()}
    if highlight:
        live["pinned"] = msg
    push_chat(live, msg)
    live_stats(live)
    return msg


# Flow özelliği 1: canlı yayında flow gönder
@route("POST", "/api/live/([0-9a-f]{16})/gift")
def api_live_gift(h, user, body, lid):
    live = get_live(lid)
    if live["hostId"] == user["id"]:
        raise ApiError(400, "Kendine flow gönderemezsin.")
    amount = transfer(user["id"], live["hostId"], body.get("amount"), "gift", lid)
    live["flows"] += amount
    push_chat(live, {"id": new_id(6), "userId": user["id"], "gift": amount, "at": now_ms()})
    live_stats(live)


@route("POST", "/api/live/([0-9a-f]{16})/request")
def api_live_request(h, user, body, lid):
    live = get_live(lid)
    mode = body.get("mode")
    if live["type"] != "chat" or not live["allowRequests"]:
        raise ApiError(400, "Bu yayında katılma isteği kapalı.")
    if mode not in ("audio", "video"):
        raise ApiError(400, "Geçersiz istek türü.")
    if user["id"] not in live["viewers"].values():
        raise ApiError(400, "Önce yayına katıl.")
    if user["id"] in live["guests"]:
        raise ApiError(400, "Zaten yayındasın.")
    live["requests"][user["id"]] = mode
    emit_raw([live["hostCid"]], "live:requests", {"liveId": lid, "requests": live["requests"]})


@route("POST", "/api/live/([0-9a-f]{16})/request/cancel")
def api_live_request_cancel(h, user, body, lid):
    live = get_live(lid)
    live["requests"].pop(user["id"], None)
    emit_raw([live["hostCid"]], "live:requests", {"liveId": lid, "requests": live["requests"]})


@route("POST", "/api/live/([0-9a-f]{16})/request/([^/]+)/(accept|reject)")
def api_live_request_answer(h, user, body, lid, target, action):
    live = get_live(lid)
    if live["hostId"] != user["id"]:
        raise ApiError(403, "Yalnızca yayıncı.")
    mode = live["requests"].pop(target, None)
    if not mode:
        raise ApiError(404, "İstek bulunamadı.")
    if action == "accept":
        if len(live["guests"]) >= live["maxGuests"]:
            live["requests"][target] = mode
            raise ApiError(400, "Konuk sınırı dolu.")
        live["guests"][target] = mode
        emit_live(live, "live:accepted", {"userId": target, "mode": mode})
        emit_live(live, "live:guests", {"guests": live["guests"]})
    else:
        emit_live(live, "live:rejected", {"userId": target})
    emit_raw([live["hostCid"]], "live:requests", {"liveId": lid, "requests": live["requests"]})


@route("POST", "/api/live/([0-9a-f]{16})/guest/([^/]+)/remove")
def api_live_guest_remove(h, user, body, lid, target):
    live = get_live(lid)
    if user["id"] not in (live["hostId"], target):
        raise ApiError(403, "Yetkin yok.")
    if live["guests"].pop(target, None):
        emit_live(live, "live:guest-removed", {"userId": target})
        emit_live(live, "live:guests", {"guests": live["guests"]})


@route("POST", "/api/signal")
def api_signal(h, user, body):
    live = get_live(str(body.get("liveId", "")))
    to = str(body.get("to", ""))
    frm = str(body.get("cid", ""))
    members = set(live_cids(live))
    if to not in members or frm not in members or CLIENTS.get(frm, {}).get("user") != user["id"]:
        raise ApiError(403, "Geçersiz sinyal.")
    emit_raw([to], "signal", {"liveId": live["id"], "from": frm, "userId": user["id"], "data": body.get("data")})


# ---------------------------------------------------------------- Admin paneli (15 özellik)
def admin_target(uid, allow_owner=False):
    u = DB["users"].get(uid)
    if not u:
        raise ApiError(404, "Kullanıcı bulunamadı.")
    if u["role"] == "owner" and not allow_owner:
        raise ApiError(403, "Owner hesaplarına bu işlem uygulanamaz.")
    return u


@route("GET", "/api/admin/overview", owner=True)
def api_admin_overview(h, user, body):
    users = DB["users"].values()
    return {
        "stats": {
            "users": len(DB["users"]), "online": len({c["user"] for c in CLIENTS.values()}),
            "videos": sum(1 for c in DB["content"].values() if c["kind"] == "video"),
            "shorts": sum(1 for c in DB["content"].values() if c["kind"] == "short"),
            "posts": sum(1 for c in DB["content"].values() if c["kind"] == "post"),
            "lives": len(LIVES), "flows": sum(u["flows"] for u in users),
            "banned": sum(1 for u in users if u["banned"]), "muted": sum(1 for u in users if u["muted"]),
            "messages": len(DB["dms"]),
        },
        "audit": list(reversed(DB["audit"][-200:])),
        "tx": list(reversed(DB["tx"][-200:])),
    }


@route("POST", "/api/admin/flows", owner=True)
def api_admin_flows(h, user, body):
    target = admin_target(body.get("userId"), allow_owner=True)
    amount = int(body.get("amount") or 0)
    if body.get("mode") == "take":
        amount = min(amount, target["flows"])
        if amount < 1:
            raise ApiError(400, "Kullanıcının alınacak flow'u yok.")
        transfer(target["id"], None, amount, "admin-take")
        audit(user["id"], "Flow alındı", f"{target['name']}: -{amount}")
    else:
        transfer(None, target["id"], amount, "admin-give")
        notify(target["id"], "flow", user["id"], None, f"{amount} flow")
        audit(user["id"], "Flow verildi", f"{target['name']}: +{amount}")
    emit_all("sync", {})


@route("POST", "/api/admin/airdrop", owner=True)
def api_admin_airdrop(h, user, body):
    amount = int(body.get("amount") or 0)
    if amount < 1 or amount > 10000:
        raise ApiError(400, "Miktar 1 ile 10000 arasında olmalı.")
    n = 0
    for u in DB["users"].values():
        if not u["banned"]:
            transfer(None, u["id"], amount, "airdrop")
            n += 1
    emit_all("notify", {"type": "airdrop", "from": user["id"], "text": f"{amount} flow"})
    audit(user["id"], "Herkese flow dağıtıldı", f"{n} kullanıcıya {amount} flow")
    emit_all("sync", {})


@route("POST", "/api/admin/config", owner=True)
def api_admin_config(h, user, body):
    cfg = DB["config"]
    if "startingFlows" in body:
        v = int(body["startingFlows"])
        if v < 0 or v > 100000:
            raise ApiError(400, "Geçersiz değer.")
        cfg["startingFlows"] = v
        audit(user["id"], "Başlangıç flow'u", str(v))
    if "announcement" in body:
        cfg["announcement"] = str(body["announcement"]).strip()[:300]
        audit(user["id"], "Duyuru", cfg["announcement"] or "(kaldırıldı)")
    if "maintenance" in body:
        cfg["maintenance"] = bool(body["maintenance"])
        audit(user["id"], "Bakım modu", "açık" if cfg["maintenance"] else "kapalı")
    if "registrationOpen" in body:
        cfg["registrationOpen"] = bool(body["registrationOpen"])
        audit(user["id"], "Kayıtlar", "açık" if cfg["registrationOpen"] else "kapalı")
    if "featured" in body:
        fid = body["featured"]
        if fid is not None:
            get_content(fid)
        cfg["featured"] = fid
        audit(user["id"], "Öne çıkan içerik", fid or "(kaldırıldı)")
    emit_all("sync", {})


@route("POST", "/api/admin/user", owner=True)
def api_admin_user(h, user, body):
    target = admin_target(body.get("userId"), allow_owner=body.get("field") == "verified")
    field = body.get("field")
    value = bool(body.get("value"))
    if field not in ("verified", "muted", "banned"):
        raise ApiError(400, "Geçersiz alan.")
    target[field] = value
    labels = {"verified": "Doğrulama rozeti", "muted": "Susturma", "banned": "Yasaklama"}
    audit(user["id"], labels[field], f"{target['name']}: {'açık' if value else 'kapalı'}")
    if field == "banned" and value:
        for tok, uid in list(DB["sessions"].items()):
            if uid == target["id"]:
                del DB["sessions"][tok]
        for live in list(LIVES.values()):
            if live["hostId"] == target["id"]:
                end_live(live, "Yayın bir owner tarafından sonlandırıldı.")
        emit_users([target["id"]], "kicked", {"reason": "Hesabın yasaklandı."})
    emit_all("sync", {})


# ---------------------------------------------------------------- Başlat
def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    load_db()
    httpd = None
    for candidate in range(port, port + 20):
        try:
            httpd = ThreadingHTTPServer(("0.0.0.0", candidate), Handler)
            break
        except OSError as e:
            if e.errno not in (errno.EADDRINUSE, errno.EACCES):
                raise
            print(f"Port {candidate} dolu (eski bir sunucu açık kalmış olabilir), {candidate + 1} deneniyor…")
    if httpd is None:
        print(f"{port}-{port + 19} arasındaki portların hepsi dolu. Eski sunucuları kapat: pkill -f http.server; pkill -f server.py")
        sys.exit(1)
    port = httpd.server_address[1]
    httpd.daemon_threads = True
    cert, key = os.path.join(ROOT, "cert.pem"), os.path.join(ROOT, "key.pem")
    scheme = "http"
    if os.path.exists(cert) and os.path.exists(key):
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(cert, key)
        httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
        scheme = "https"
    print(f"Flowly çalışıyor: {scheme}://localhost:{port}")
    print("Durdurmak için Ctrl + C")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nFlowly kapatıldı.")


if __name__ == "__main__":
    main()
