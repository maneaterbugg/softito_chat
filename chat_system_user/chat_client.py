#!/usr/bin/env python3
import os
import socket, threading, datetime
from pathlib import Path

# Hangi kullanıcı ad(lar)ı admin olarak rezerve? (PIN zorunlu)
RESERVED_ADMIN_NAMES = {"Admin"}

# Admin gizli anahtarı: önce ortam değişkeni, yoksa admin_secret.txt
ADMIN_SECRET = os.environ.get("ADMIN_SECRET")
if not ADMIN_SECRET:
    sec_path = Path(__file__).parent / "admin_secret.txt"
    if sec_path.exists():
        ADMIN_SECRET = sec_path.read_text(encoding="utf-8", errors="replace").strip()
        if not ADMIN_SECRET:
            ADMIN_SECRET = None

# Bağlantı bazlı admin rol bilgisi
admin_conns = set()

clients = {}  # conn -> username

# --- Kurallar dosyasını yükle ---
RULES_VERSION = "1"
RULES_LINES = []
try:
    rules_path = Path(__file__).parent / "rules.txt"
    if rules_path.exists():
        raw = rules_path.read_text(encoding="utf-8", errors="replace").splitlines()
        # İsteğe bağlı sürüm satırı: "# RULES_VERSION=3"
        if raw and raw[0].lstrip().startswith("#") and "RULES_VERSION=" in raw[0]:
            RULES_VERSION = raw[0].split("RULES_VERSION=", 1)[1].strip() or RULES_VERSION
            RULES_LINES = raw[1:]
        else:
            RULES_LINES = raw
    else:
        print("[UYARI] rules.txt bulunamadı; onay aşaması atlanacak.")
except Exception as e:
    print(f"[UYARI] rules.txt okunamadı: {e}")

def valid_name(u: str) -> bool:
    # 3–20 karakter, satır kırıcı yok; Türkçe dahil
    return (3 <= len(u) <= 20) and ("\n" not in u and "\r" not in u)

def send_line(conn, text: str):
    try:
        conn.send((text + "\n").encode("utf-8"))
    except:
        pass

def recv_line(conn, timeout_sec=None):
    """Tek satır oku; timeout olursa None döner."""
    old_to = conn.gettimeout()
    try:
        conn.settimeout(timeout_sec)
        buf = b""
        while True:
            chunk = conn.recv(1024)
            if not chunk:
                return None
            buf += chunk
            if b"\n" in buf:
                line, _rest = buf.split(b"\n", 1)
                return line.decode("utf-8", errors="replace").strip()
    except socket.timeout:
        return None
    finally:
        conn.settimeout(old_to)

def broadcast(text: str):
    print(text)  # sade sunucu logu
    dead = []
    for c in list(clients.keys()):
        try:
            send_line(c, text)
        except:
            dead.append(c)
    for c in dead:
        try: c.close()
        except: pass
        clients.pop(c, None)
        admin_conns.discard(c)

def log_rules(username: str, peer_ip: str, result: str):
    """result: ACCEPT / DENY / TIMEOUT / SKIP"""
    try:
        logp = Path(__file__).parent / "rules_accept.log"
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with logp.open("a", encoding="utf-8") as f:
            f.write(f"{ts} user={username} ip={peer_ip} rules_v={RULES_VERSION} result={result}\n")
    except Exception as e:
        print(f"[UYARI] rules_accept.log yazılamadı: {e}")

def ask_rules_and_consent(conn, peer_ip: str, username: str) -> bool:
    """Kuralları gönder, OK onayı al. True=Kabul edildi, False=Reddedildi/koptu."""
    if not RULES_LINES:
        log_rules(username, peer_ip, "SKIP")
        return True

    send_line(conn, "========== KURALLAR ==========")
    for line in RULES_LINES:
        send_line(conn, line)
    send_line(conn, "==============================")
    send_line(conn, "ACCEPT? (OK/EXIT)")

    # 60 sn timeout, en fazla 3 deneme
    for _ in range(3):
        ans = recv_line(conn, timeout_sec=60)
        if ans is None:
            log_rules(username, peer_ip, "TIMEOUT")
            return False
        up = ans.strip().upper()
        if up in ("OK", "KABUL", "EVET"):
            log_rules(username, peer_ip, "ACCEPT")
            return True
        if up in ("EXIT", "HAYIR", "NO"):
            log_rules(username, peer_ip, "DENY")
            return False
        send_line(conn, "Lütfen OK ya da EXIT yazın. ACCEPT?")
    log_rules(username, peer_ip, "DENY")
    return False

def handle_client(conn, addr):
    peer_ip = addr[0] if isinstance(addr, tuple) else str(addr)
    try:
        # 1) İsim iste – doğrulama/benzersizlik
        send_line(conn, "USERNAME?")
        while True:
            raw = recv_line(conn, timeout_sec=120)
            if raw is None:
                conn.close(); return
            username = raw.strip()
            if not valid_name(username):
                send_line(conn, "ERROR: İsim 3-20 karakter olmalı. Tekrar deneyin.")
                send_line(conn, "USERNAME?");  continue
            if username in clients.values():
                send_line(conn, "ERROR: Bu isim kullanılıyor. Başka bir isim seçin.")
                send_line(conn, "USERNAME?");  continue

            # --- Admin adı rezerve ise PIN doğrulaması ---
            if username in RESERVED_ADMIN_NAMES:
                if not ADMIN_SECRET:
                    send_line(conn, "ERROR: Bu ad rezerve. Sunucu admin anahtarı yapılandırılmamış.")
                    send_line(conn, "USERNAME?")
                    continue
                send_line(conn, "ADMINKEY?")
                key = recv_line(conn, timeout_sec=60)
                if (key is None) or (key != ADMIN_SECRET):
                    send_line(conn, "ERROR: Admin anahtarı hatalı. Bu ad rezerve.")
                    send_line(conn, "USERNAME?")
                    continue
                # doğru PIN -> bu bağlantı admin olur
                admin_conns.add(conn)
            # ------------------------------------------------

            break

        # 2) Kuralları göster + onay al
        if not ask_rules_and_consent(conn, peer_ip, username):
            send_line(conn, "DENIED: Kurallar kabul edilmedi. Bağlantı kapanıyor.")
            try: conn.shutdown(socket.SHUT_RDWR)
            except: pass
            conn.close()
            return

        # 3) Hoş geldin + katılım yayını
        clients[conn] = username
        send_line(conn, f"WELCOME {username}")
        broadcast(f"🔵 {username} sohbete katıldı.")

        # 4) Mesaj döngüsü (+ admin /clear)
        while True:
            msg = recv_line(conn)
            if msg is None:
                break
            msg = msg.rstrip("\r")
            if not msg:
                continue

            # --- admin /clear komutu ---
            if (conn in admin_conns) and (msg.strip() == "/clear"):
                broadcast("CTRL:CLEAR")
                continue
            # ---------------------------

            ts = datetime.datetime.now().strftime("%H:%M:%S")
            broadcast(f"[{ts}] {clients[conn]}: {msg}")

    except Exception:
        pass
    finally:
        user = clients.pop(conn, None)
        admin_conns.discard(conn)
        try: conn.close()
        except: pass
        if user:
            broadcast(f"🔴 {user} sohbetten ayrıldı.")

def main():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    # Güvenli: sadece localhost (SSH tüneli ile erişim)
    server.bind(("127.0.0.1", 1161))
    server.listen()
    print("[SUNUCU ÇALIŞIYOR] 127.0.0.1:1161")

    while True:
        conn, addr = server.accept()
        threading.Thread(target=handle_client, args=(conn, addr), daemon=True).start()

if __name__ == "__main__":
    main()

