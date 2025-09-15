import socket, curses, threading, locale

# Unicode/Türkçe
locale.setlocale(locale.LC_ALL, '')

SERVER_IP = "127.0.0.1"
SERVER_PORT = 1161

def recv_loop(sock, msg_win, lock):
    buf = b""
    while True:
        try:
            data = sock.recv(4096)
            if not data:
                with lock:
                    msg_win.addstr("[Bağlantı kapandı]\n")
                    msg_win.refresh()
                break
            buf += data
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                text = line.decode("utf-8", errors="replace")

                # --- Admin temizleme sinyali ---
                if text.strip() == "CTRL:CLEAR":
                    with lock:
                        msg_win.erase()
                        msg_win.refresh()
                        msg_win.addstr("— Admin sohbet penceresini temizledi —\n")
                        msg_win.refresh()
                    continue
                # -------------------------------

                with lock:
                    msg_win.addstr(text + "\n")
                    msg_win.scrollok(True)
                    msg_win.refresh()
        except Exception:
            break

def draw_prompt(win, label, buf):
    win.erase()
    win.border()
    win.addstr(1, 2, f"{label} {buf}")
    win.refresh()

def input_line(stdscr, inp_win, label):
    """Unicode güvenli tek satır giriş (get_wch)."""
    buf = ""
    draw_prompt(inp_win, label, buf)
    curses.curs_set(1)
    while True:
        ch = stdscr.get_wch()
        if isinstance(ch, str):
            if ch == "\n":
                return buf
            elif ch in ("\x08", "\x7f"):
                buf = buf[:-1]
            else:
                buf += ch
        else:
            if ch in (curses.KEY_BACKSPACE, curses.KEY_DC):
                buf = buf[:-1]
        draw_prompt(inp_win, label, buf)
        
        
def input_secret(stdscr, inp_win, label):
    """Ekranda görünmeyen gizli giriş (ör. şifre)."""
    buf = ""
    inp_win.erase()
    inp_win.border()
    inp_win.addstr(1, 2, label)
    inp_win.refresh()
    curses.curs_set(1)

    while True:
        ch = stdscr.get_wch()
        if isinstance(ch, str):
            if ch == "\n":
                return buf
            elif ch in ("\x08", "\x7f"):  # backspace
                buf = buf[:-1]
            else:
                buf += ch
        else:
            if ch in (curses.KEY_BACKSPACE, curses.KEY_DC):
                buf = buf[:-1]
        # dikkat: burada hiçbir şey ekrana yazmıyoruz, sadece buffer tutuyoruz

def handshake(stdscr, sock, msg_win, inp_win):
    """
    USERNAME? -> isim gönder
    ADMINKEY? -> admin PIN gönder (yalnız admin adı için)
    ACCEPT?   -> OK/EXIT gönder
    WELCOME   -> el sıkışma biter (ekran temizlenir)
    """
    buf = b""
    expecting_username = False
    while True:
        if not expecting_username:
            data = sock.recv(4096)
            if not data:
                raise ConnectionError("Sunucudan veri gelmiyor.")
            buf += data
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                text = line.decode("utf-8", errors="replace").strip()

                # El sıkışma metinlerini göster
                msg_win.addstr(text + "\n")
                msg_win.refresh()

                up = text.upper()
                if up.startswith("WELCOME "):
                    # WELCOME gelince el sıkışma ekranını temizle
                    msg_win.erase()
                    msg_win.refresh()
                    msg_win.addstr(text + "\n")
                    msg_win.refresh()
                    return

                if up.startswith("USERNAME?"):
                    expecting_username = True
                    break

                if up.startswith("ADMINKEY?"):
                    pin = input_secret(stdscr, inp_win, "Admin PIN > ")
                    sock.send((pin + "\n").encode("utf-8"))

                if up.startswith("ACCEPT?"):
                    ans = input_line(stdscr, inp_win, "Kabul (OK/EXIT) >")
                    sock.send((ans + "\n").encode("utf-8"))

        if expecting_username:
            username = input_line(stdscr, inp_win, "Isminiz >")
            sock.send((username + "\n").encode("utf-8"))
            expecting_username = False


def main(stdscr):
    curses.curs_set(1)
    curses.noecho()
    curses.cbreak()
    stdscr.keypad(True)

    maxy, maxx = stdscr.getmaxyx()
    msg_h = maxy - 3
    msg_win = curses.newwin(msg_h, maxx, 0, 0)
    inp_win = curses.newwin(3, maxx, msg_h, 0)

    # Bağlan
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((SERVER_IP, SERVER_PORT))

    # El sıkışma (isim + varsa admin PIN + kurallar)
    handshake(stdscr, sock, msg_win, inp_win)

    # Mesajları arka planda al
    lock = threading.Lock()
    threading.Thread(target=recv_loop, args=(sock, msg_win, lock), daemon=True).start()

    # Sohbet döngüsü
    while True:
        text = input_line(stdscr, inp_win, ">")
        try:
            sock.send((text + "\n").encode("utf-8"))
        except BrokenPipeError:
            with lock:
                msg_win.addstr("[Bağlantı koptu]\n")
                msg_win.refresh()
            break

    try:
        sock.close()
    except:
        pass

if __name__ == "__main__":
    curses.wrapper(main)
