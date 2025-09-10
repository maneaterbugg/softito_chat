import socket, curses, threading, locale

# --- Unicode/Türkçe için locale'i etkinleştir ---
locale.setlocale(locale.LC_ALL, '')

SERVER_IP = "127.0.0.1"   # sunucunun IP'sini yaz
SERVER_PORT = 1161        # sunucu portu

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
    """
    Tek satır giriş. Unicode için get_wch() kullanılır.
    get_wch() -> karakter ise str, özel tuş ise int döner.
    """
    buf = ""
    draw_prompt(inp_win, label, buf)
    curses.curs_set(1)
    while True:
        ch = stdscr.get_wch()  # <-- Unicode güvenli okuma
        if isinstance(ch, str):
            if ch == "\n":            # Enter
                return buf
            elif ch in ("\x08", "\x7f"):  # Backspace/Delete (bazı terminaller)
                buf = buf[:-1]
            else:
                buf += ch             # Türkçe karakterler dahil
        else:
            # Özel tuşlar (örn. Backspace bazı terminallerde KEY_BACKSPACE)
            if ch in (curses.KEY_BACKSPACE, curses.KEY_DC):
                buf = buf[:-1]
            # Diğer özel tuşları (oklar vs.) yoksay
        draw_prompt(inp_win, label, buf)

def handshake(stdscr, sock, msg_win, inp_win):
    """
    Sunucudan satır satır oku. 'USERNAME?' görünce bir kere isim sorup gönder.
    'WELCOME ' gelirse biter; 'ERROR' gelirse döngü devam eder (sunucu tekrar USERNAME? yollayacak).
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
                msg_win.addstr(text + "\n"); msg_win.refresh()
                up = text.upper()
                if up.startswith("WELCOME "):
                    return
                if up.startswith("USERNAME?"):
                    expecting_username = True
                    break
                # ERROR satırları sadece ekrana yazılır; USERNAME? beklenir
        if expecting_username:
            username = input_line(stdscr, inp_win, "Isminiz >")
            sock.send((username + "\n").encode("utf-8"))
            expecting_username = False  # cevap beklemek için tekrar recv'e dön

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

    # İsim alma (onaysız)
    handshake(stdscr, sock, msg_win, inp_win)

    # Mesajları arka planda al
    lock = threading.Lock()
    threading.Thread(target=recv_loop, args=(sock, msg_win, lock), daemon=True).start()

    # Sohbet giriş döngüsü: ham satır ekrana basılmaz
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
