#!/usr/bin/env python3
import socket, curses, threading, locale
import os, mimetypes, glob, subprocess

locale.setlocale(locale.LC_ALL, '')

SERVER_IP = "127.0.0.1"
SERVER_PORT = 1161

# ===== Ayarlar =====
PREVIEW_MODE = "none"      # inline önizleme kapalı
AUTO_PREVIEW = False

MEDIA_EXTS = {
    ".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp",
    ".mp4", ".mkv", ".mov", ".webm", ".avi", ".m4v"
}
def is_image_name(name: str) -> bool:
    return os.path.splitext(name)[1].lower() in {
        ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"
    }

SEND_SEARCH_DIRS = [os.getcwd()]
if os.environ.get("MEDIA_DIR"):
    md = os.environ["MEDIA_DIR"]
    if os.path.isdir(md): SEND_SEARCH_DIRS.append(md)

LAST_FILE_URL = None
LAST_URL_FILE = os.path.expanduser("~/.chatclient_lasturl")

# ===== Yardımcılar =====
def draw_box_ascii(win):
    try: win.border('|','|','-','-','+','+','+','+')
    except curses.error: pass

def safe_addstr(win, s):
    try:
        maxy, maxx = win.getmaxyx()
        for line in s.splitlines():
            win.addnstr(line, maxx - 1); win.addstr("\n")
        win.refresh()
    except curses.error: pass

def eat_escape_sequence(win):
    try:
        win.nodelay(True)
        while True:
            ch = win.getch()
            if ch == -1: break
    finally:
        try: win.nodelay(False)
        except: pass

# ===== Alım döngüsü =====
def recv_loop(sock, msg_win, user_win, lock, stdscr, inp_win):
    global LAST_FILE_URL
    buf = b""
    while True:
        try:
            data = sock.recv(4096)
            if not data:
                with lock: safe_addstr(msg_win, "[Bağlantı kapandı]")
                break
            buf += data
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                text = line.decode("utf-8", errors="replace").strip()

                if text.startswith("FILEURL "):
                    info = text.split()
                    from_ = next((p.split("=",1)[1] for p in info if p.startswith("from=")), "?")
                    name  = next((p.split("=",1)[1] for p in info if p.startswith("name=")), "?")
                    url   = next((p.split("=",1)[1] for p in info if p.startswith("url=")),  "?")

                    LAST_FILE_URL = url
                    try:
                        with open(LAST_URL_FILE, "w", encoding="utf-8") as f:
                            f.write(url)
                    except Exception:
                        pass

                    with lock:
                        msg_win.addstr(f"[Dosya] {from_} → {name}\n")
                        msg_win.addstr(f"        İndir: {url}\n")
                        msg_win.refresh()
                    continue

                if text.startswith("[FILE] "):
                    with lock: msg_win.addstr(text + "\n"); msg_win.refresh()
                    continue

                if text == "CTRL:CLEAR":
                    with lock:
                        msg_win.erase()
                        safe_addstr(msg_win, "— Admin sohbet penceresini temizledi —")
                    continue

                if text.startswith("USERLIST:"):
                    users = [u for u in text.split(":",1)[1].split(",") if u]
                    with lock:
                        user_win.erase(); draw_box_ascii(user_win)
                        try:
                            user_win.addstr(1, 2, "Users:")
                            y, w = 2, user_win.getmaxyx()[1]-3
                            for u in users:
                                user_win.addnstr(y, 2, u, w); y += 1
                        except curses.error: pass
                        user_win.refresh()
                    continue

                if text == "CTRL:KICKED":
                    with lock: safe_addstr(msg_win, "[Sistem] Admin tarafından çıkarıldınız.")
                    try: sock.close()
                    except: pass
                    return

                if text.startswith("NOTICE:"):
                    with lock: safe_addstr(msg_win, "[Sunucu] " + text.split(":",1)[1])
                    continue

                with lock: safe_addstr(msg_win, text)
        except Exception as e:
            with lock: safe_addstr(msg_win, f"[Hata: recv_loop] {e}")
            break

# ===== Handshake =====
def h_print(hand_top, lines):
    hand_top.erase()
    maxy, maxx = hand_top.getmaxyx()
    start = max(0, len(lines) - maxy)
    y = 0
    for line in lines[start:]:
        try: hand_top.addnstr(y, 1, line, maxx - 2)
        except curses.error: pass
        y += 1
        if y >= maxy: break
    hand_top.refresh()

def h_input(hand_inp, prompt, secret=False):
    curses.flushinp()
    buf = ""
    while True:
        hand_inp.erase(); draw_box_ascii(hand_inp)
        try:
            hand_inp.addstr(1, 2, prompt)
            if not secret:
                hand_inp.addnstr(1, 2+len(prompt), buf, hand_inp.getmaxyx()[1]-len(prompt)-4)
        except curses.error: pass
        hand_inp.refresh()

        ch = hand_inp.get_wch()
        if not isinstance(ch, str): continue
        if ch == "\x1b": eat_escape_sequence(hand_inp); continue
        if ch == "\n":  return buf
        elif ch in ("\x08", "\x7f", "\b"): buf = buf[:-1]
        else: buf += ch

def handshake(stdscr, sock):
    stdscr.erase(); stdscr.refresh()
    maxy, maxx = stdscr.getmaxyx()
    inp_h = 3
    hand_top = curses.newwin(maxy - inp_h, maxx, 0, 0)
    hand_inp = curses.newwin(inp_h, maxx, maxy - inp_h, 0)
    hand_inp.keypad(True)
    draw_box_ascii(hand_top); hand_top.refresh()
    draw_box_ascii(hand_inp); hand_inp.refresh()

    buf = b""; lines = []
    while True:
        data = sock.recv(4096)
        if not data: raise ConnectionError("Sunucudan veri gelmiyor.")
        buf += data
        while b"\n" in buf:
            raw, buf = buf.split(b"\n", 1)
            text = raw.decode("utf-8", errors="replace").strip()
            up = text.upper()

            if up.startswith("DENIED:"): raise ConnectionError(text)
            if up.startswith("USERNAME?"):
                username = h_input(hand_inp, "Isminiz > ")
                sock.send((username + "\n").encode("utf-8")); continue
            if up.startswith("ADMINKEY?"):
                pin = h_input(hand_inp, "Admin PIN > ", secret=True)
                sock.send((pin + "\n").encode("utf-8")); continue
            if "ACCEPT?" in up:
                ans = h_input(hand_inp, "Kabul (OK/EXIT) > ")
                sock.send((ans + "\n").encode("utf-8")); continue
            if up.startswith("WELCOME "):
                hand_top.erase(); hand_top.refresh()
                hand_inp.erase(); hand_inp.refresh()
                stdscr.erase(); stdscr.refresh()
                return text

            lines.append(text); h_print(hand_top, lines)

# ===== Tamamlama paneli =====
def show_completion_panel(stdscr, items, inp_h=3):
    if not items: return None
    maxy, maxx = stdscr.getmaxyx()
    h = min(len(items) + 2, max(5, maxy // 3))
    w = min(max((len(x) for x in items), default=10) + 4, maxx - 2)
    y = maxy - inp_h - h; x = 0
    win = curses.newwin(h, w, y, x)
    try:
        win.border('|','|','-','-','+','+','+','+')
        title = f"{len(items)} aday"
        try: win.addnstr(0, 2, title, w-4)
        except: pass
        row = 1
        for it in items[:h-2]:
            try: win.addnstr(row, 2, it, w-4)
            except: pass
            row += 1
        win.refresh()
    except curses.error: pass
    return win

def close_panel(panel):
    if panel:
        try: panel.erase(); panel.refresh()
        except: pass
    return None

def path_complete(token: str):
    if not token: token = ""
    expanded = os.path.expanduser(token)
    d = expanded if os.path.isdir(expanded) else (os.path.dirname(expanded) or ".")
    prefix = os.path.basename(expanded)
    pattern = os.path.join(d, prefix + "*")
    all_cands = sorted(glob.glob(pattern))
    cands = []
    for p in all_cands:
        if os.path.isdir(p): cands.append(p + os.sep)
        else:
            ext = os.path.splitext(p)[1].lower()
            if ext in MEDIA_EXTS: cands.append(p)
    return cands, d, prefix

def complete_send_buffer(buf: str, stdscr, panel, inp_h=3):
    try: base = buf.split(" ", 1)[1]
    except IndexError: base = ""
    cands, d, prefix = path_complete(base)
    if not cands:
        panel = close_panel(panel); return buf, panel
    if len(cands) == 1:
        c = cands[0]
        finished = os.path.join(os.path.dirname(base or ""), os.path.basename(c))
        if c.endswith(os.sep): finished += os.sep
        panel = close_panel(panel); return "/send " + finished, panel
    names = [os.path.basename(x.rstrip(os.sep)) + ("/" if x.endswith(os.sep) else "") for x in cands]
    common = os.path.commonprefix(names)
    new_base = os.path.join(os.path.dirname(base or ""), common)
    panel = close_panel(panel); panel = show_completion_panel(stdscr, names, inp_h=inp_h)
    return "/send " + new_base, panel

# ===== Dosya gönder =====
def resolve_send_path(arg: str) -> str | None:
    if not arg: return None
    cand = os.path.expanduser(arg)
    if os.path.isabs(cand) or os.path.exists(cand):
        return cand if os.path.isfile(cand) else None
    for d in SEND_SEARCH_DIRS:
        p = os.path.join(d, cand)
        if os.path.isfile(p): return p
    return None

def send_file(sock, path, msg_win=None, lock=None):
    if not path or not os.path.isfile(path):
        if msg_win and lock:
            with lock: msg_win.addstr(f"[Hata] Dosya yok: {path}\n"); msg_win.refresh()
        return
    size  = os.path.getsize(path)
    ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
    name  = os.path.basename(path)
    header = f"FILE name={name} size={size} type={ctype}\n\n"
    try:
        sock.sendall(header.encode("utf-8"))
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                sock.sendall(chunk)
        if msg_win and lock:
            with lock: msg_win.addstr(f"[Gönderildi] {name} ({size} bayt, {ctype})\n"); msg_win.refresh()
    except Exception as e:
        if msg_win and lock:
            with lock: msg_win.addstr(f"[Hata] Gönderim başarısız: {e}\n"); msg_win.refresh()

# ===== MAIN =====
def main(stdscr):
    global LAST_FILE_URL
    # Son linki yerelden yükle (varsa)
    try:
        if os.path.isfile(LAST_URL_FILE):
            with open(LAST_URL_FILE, "r", encoding="utf-8") as f:
                LAST_FILE_URL = f.read().strip() or None
    except Exception:
        LAST_FILE_URL = None

    curses.curs_set(1); curses.noecho(); curses.cbreak()
    stdscr.keypad(True); curses.mousemask(0)

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((SERVER_IP, SERVER_PORT))

    welcome_line = handshake(stdscr, sock)

    stdscr.erase(); stdscr.refresh()
    maxy, maxx = stdscr.getmaxyx()
    user_w = 24; msg_h = maxy - 3
    msg_win = curses.newwin(msg_h, maxx - user_w, 0, 0)
    user_win = curses.newwin(msg_h, user_w, 0, maxx - user_w)
    inp_win  = curses.newwin(3, maxx, msg_h, 0)
    msg_win.scrollok(True)
    draw_box_ascii(user_win); user_win.addstr(1,2,"Users:"); user_win.refresh()
    draw_box_ascii(inp_win);  inp_win.refresh()
    safe_addstr(msg_win, welcome_line)

    lock = threading.Lock()
    threading.Thread(target=recv_loop, args=(sock, msg_win, user_win, lock, stdscr, inp_win),
                     daemon=True).start()

    buf = ""; comp_panel = None
    while True:
        inp_win.erase(); draw_box_ascii(inp_win)
        try: inp_win.addstr(1, 2, ">" + buf)
        except curses.error: pass
        inp_win.refresh()

        ch = inp_win.get_wch()
        if not isinstance(ch, str): continue
        if ch == "\x1b":
            eat_escape_sequence(inp_win); comp_panel = close_panel(comp_panel); continue

        if ch == "\t":
            if buf.startswith("/send"):
                buf, comp_panel = complete_send_buffer(buf, stdscr, comp_panel, inp_h=3)
            continue

        comp_panel = close_panel(comp_panel)

        if ch == "\n":
            text = buf.strip(); buf = ""
            if text.startswith("/"):
                if text == "/help":
                    with lock:
                        safe_addstr(msg_win,
                            "Kullanılabilir komutlar:\n"
                            "  /help           → Bu yardım ekranını gösterir\n"
                            "  /clear          → (Admin) Sohbeti temizler\n"
                            "  /kick KULLANICI → (Admin) Kullanıcıyı atar\n"
                            "  /send PATH      → Dosya gönder (görsel/video)\n"
                            "  /cls            → Ekranı yerelde temizle\n"
                            "  /lasturl        → Son dosya linkini tekrar göster\n"
                            "  /open           → Son dosya linkini tarayıcıda aç\n"
                            "  /quit           → Sohbetten çık")
                    continue
                if text in ("/cls", "/clearme"):
                    msg_win.erase(); msg_win.refresh(); continue
                if text == "/lasturl":
                    with lock:
                        if LAST_FILE_URL:
                            msg_win.addstr(f"[Son link] {LAST_FILE_URL}\n")
                        else:
                            msg_win.addstr("[Bilgi] Henüz bir dosya linki yok.\n")
                        msg_win.refresh()
                    continue
                if text == "/open":
                    if LAST_FILE_URL:
                        try:
                            subprocess.Popen(
                                ["xdg-open", LAST_FILE_URL],
                                stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL,
                                close_fds=True,
                                start_new_session=True,
                            )
                            with lock: msg_win.addstr("[Bilgi] Link tarayıcıda açılıyor.\n"); msg_win.refresh()
                        except Exception as e:
                            with lock: msg_win.addstr(f"[Hata] Açılamadı: {e}\n"); msg_win.refresh()
                    else:
                        with lock: msg_win.addstr("[Bilgi] Henüz bir dosya linki yok.\n"); msg_win.refresh()
                    continue
                if text.startswith("/send"):
                    try: arg = text.split(" ",1)[1].strip()
                    except IndexError: arg = ""
                    path = resolve_send_path(arg)
                    if not path:
                        with lock:
                            msg_win.addstr("[Hata] Yol/isim bulunamadı. /send /tam/yol/dosya veya yalnızca isim.\n")
                            msg_win.refresh()
                        continue
                    send_file(sock, path, msg_win, lock); continue
                if text == "/quit":
                    try: sock.send(b"/quit\n")
                    except: pass
                    with lock: safe_addstr(msg_win, "[Sistem] Sohbetten çıkılıyor...")
                    try: sock.close()
                    except: pass
                    break
            try:
                sock.send((text + "\n").encode("utf-8"))
            except BrokenPipeError:
                with lock: safe_addstr(msg_win, "[Bağlantı koptu]")
                break
        elif ch in ("\x08", "\x7f", "\b"):
            buf = buf[:-1]
        else:
            buf += ch

    try: sock.close()
    except: pass

if __name__ == "__main__":
    curses.wrapper(main)

