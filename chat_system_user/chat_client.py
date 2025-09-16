#!/usr/bin/env python3
import socket, curses, threading, locale

locale.setlocale(locale.LC_ALL, '')

SERVER_IP = "127.0.0.1"
SERVER_PORT = 1161

# ---------- küçük yardımcılar ----------
def draw_box_ascii(win):
    try:
        win.border('|','|','-','-','+','+','+','+')
    except curses.error:
        pass

def safe_addstr(win, s):
    try:
        maxy, maxx = win.getmaxyx()
        for line in s.splitlines():
            win.addnstr(line, maxx - 1)
            win.addstr("\n")
        win.refresh()
    except curses.error:
        pass

# ---------- recv döngüsü ----------
def recv_loop(sock, msg_win, user_win, lock):
    buf = b""
    while True:
        try:
            data = sock.recv(4096)
            if not data:
                with lock:
                    safe_addstr(msg_win, "[Bağlantı kapandı]")
                break
            buf += data
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                text = line.decode("utf-8", errors="replace").strip()

                if text == "CTRL:CLEAR":
                    with lock:
                        msg_win.erase()
                        safe_addstr(msg_win, "— Admin sohbet penceresini temizledi —")
                    continue

                if text.startswith("USERLIST:"):
                    users = [u for u in text.split(":",1)[1].split(",") if u]
                    with lock:
                        user_win.erase()
                        draw_box_ascii(user_win)
                        try:
                            user_win.addstr(1, 2, "Users:")
                            y = 2
                            w = user_win.getmaxyx()[1] - 3
                            for u in users:
                                user_win.addnstr(y, 2, u, w)
                                y += 1
                        except curses.error:
                            pass
                        user_win.refresh()
                    continue

                if text == "CTRL:KICKED":
                    with lock:
                        safe_addstr(msg_win, "[Sistem] Admin tarafından çıkarıldınız.")
                    try: sock.close()
                    except: pass
                    return

                if text.startswith("NOTICE:"):
                    with lock:
                        safe_addstr(msg_win, "[Sunucu] " + text.split(":",1)[1])
                    continue

                with lock:
                    safe_addstr(msg_win, text)
        except Exception:
            break

# ---------- handshake yardımcıları ----------
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
    curses.flushinp()                 # çok kritik: artıkları temizle
    buf = ""
    while True:
        hand_inp.erase(); draw_box_ascii(hand_inp)
        try:
            hand_inp.addstr(1, 2, prompt)
            if not secret:
                hand_inp.addnstr(1, 2+len(prompt), buf, hand_inp.getmaxyx()[1]-len(prompt)-4)
        except curses.error:
            pass
        hand_inp.refresh()
        ch = hand_inp.get_wch()
        if isinstance(ch, str):
            if ch == "\n": return buf
            elif ch in ("\x08", "\x7f"): buf = buf[:-1]
            else: buf += ch
        else:
            if ch in (curses.KEY_BACKSPACE, curses.KEY_DC): buf = buf[:-1]

# ---------- handshake (iki pencere) ----------
def handshake(stdscr, sock):
    stdscr.erase(); stdscr.refresh()
    maxy, maxx = stdscr.getmaxyx()
    inp_h = 3
    hand_top = curses.newwin(maxy - inp_h, maxx, 0, 0)
    hand_inp = curses.newwin(inp_h, maxx, maxy - inp_h, 0)
    # çerçeveler
    draw_box_ascii(hand_top); hand_top.refresh()
    draw_box_ascii(hand_inp); hand_inp.refresh()

    buf = b""
    lines = []

    while True:
        data = sock.recv(4096)
        if not data:
            raise ConnectionError("Sunucudan veri gelmiyor.")
        buf += data

        while b"\n" in buf:
            raw, buf = buf.split(b"\n", 1)
            text = raw.decode("utf-8", errors="replace").strip()
            up = text.upper()

            if up.startswith("DENIED:"):
                raise ConnectionError(text)

            if up.startswith("USERNAME?"):
                username = h_input(hand_inp, "Isminiz > ")
                sock.send((username + "\n").encode("utf-8"))
                continue

            if up.startswith("ADMINKEY?"):
                pin = h_input(hand_inp, "Admin PIN > ", secret=True)
                sock.send((pin + "\n").encode("utf-8"))
                continue

            # ACCEPT? metnin neresinde olursa olsun
            if "ACCEPT?" in up:
                ans = h_input(hand_inp, "Kabul (OK/EXIT) > ")
                sock.send((ans + "\n").encode("utf-8"))
                continue

            if up.startswith("WELCOME "):
                hand_top.erase(); hand_top.refresh()
                hand_inp.erase(); hand_inp.refresh()
                stdscr.erase(); stdscr.refresh()
                return text  # "WELCOME <username>"

            # kurallar / bilgi satırlarını üst pencereye yaz
            lines.append(text)
            h_print(hand_top, lines)

# ---------- main ----------
def main(stdscr):
    curses.curs_set(1)
    curses.noecho()
    curses.cbreak()
    stdscr.keypad(True)

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((SERVER_IP, SERVER_PORT))

    # 1) el sıkışma
    welcome_line = handshake(stdscr, sock)

    # 2) sohbet düzeni
    stdscr.erase(); stdscr.refresh()
    maxy, maxx = stdscr.getmaxyx()
    user_w = 24
    msg_h  = maxy - 3
    msg_win = curses.newwin(msg_h, maxx - user_w, 0, 0)
    user_win = curses.newwin(msg_h, user_w, 0, maxx - user_w)
    inp_win  = curses.newwin(3, maxx, msg_h, 0)
    msg_win.scrollok(True)
    draw_box_ascii(user_win); user_win.addstr(1,2,"Users:"); user_win.refresh()
    draw_box_ascii(inp_win);  inp_win.refresh()

    safe_addstr(msg_win, welcome_line)

    lock = threading.Lock()
    threading.Thread(target=recv_loop, args=(sock, msg_win, user_win, lock),
                     daemon=True).start()

    # giriş döngüsü
    buf = ""
    while True:
        inp_win.erase(); draw_box_ascii(inp_win)
        try:
            inp_win.addstr(1, 2, ">" + buf)
        except curses.error:
            pass
        inp_win.refresh()

        ch = inp_win.get_wch()
        if isinstance(ch, str):
            if ch == "\n":
                text = buf.strip(); buf = ""
                if text.startswith("/"):
                    if text == "/help":
                        with lock:
                            safe_addstr(msg_win,
                                        "Kullanılabilir komutlar:\n"
                                        "  /help   → Bu yardım ekranını gösterir\n"
                                        "  /clear  → (Admin) Sohbeti temizler\n"
                                        "  /kick X → (Admin) Kullanıcıyı atar\n"
                                        "  /quit   → Sohbetten çık")
                        continue
                    if text == "/quit":
                        try: sock.send(b"/quit\n")
                        except: pass
                        with lock:
                            safe_addstr(msg_win, "[Sistem] Sohbetten çıkılıyor...")
                        try: sock.close()
                        except: pass
                        break
                try:
                    sock.send((text + "\n").encode("utf-8"))
                except BrokenPipeError:
                    with lock:
                        safe_addstr(msg_win, "[Bağlantı koptu]")
                    break
            elif ch in ("\x08", "\x7f"):
                buf = buf[:-1]
            else:
                buf += ch
        else:
            if ch in (curses.KEY_BACKSPACE, curses.KEY_DC):
                buf = buf[:-1]

    try:
        sock.close()
    except:
        pass

if __name__ == "__main__":
    curses.wrapper(main)
