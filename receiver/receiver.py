"""Media Broadcast receiver (Vercel polling edition).

Runs invisibly in the background. Polls <BROADCAST_URL>/api/latest every few seconds.
When a NEW broadcast appears it downloads the file from Vercel Blob, opens a fullscreen
window and shows it. The window disappears again when a video ends, when the operator
presses Esc, or after IMAGE_SECONDS for images (if set). Plain HTTPS only.

Settings come from environment variables or from a local file named receiver.env
next to this script (KEY=VALUE per line, never committed to git).
"""
import json
import logging
import os
import queue
import socket
import sys
import threading
import time
from urllib.parse import urlparse

HERE = os.path.dirname(os.path.abspath(__file__))


def load_local_env():
    """Read receiver.env (if present). Real environment variables win over the file."""
    try:
        with open(os.path.join(HERE, "receiver.env"), encoding="utf-8-sig") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    except FileNotFoundError:
        pass


load_local_env()

# ---------------- Configuration ----------------
BROADCAST_URL = os.environ.get("BROADCAST_URL", "").rstrip("/")   # e.g. https://your-app.vercel.app
RECEIVER_KEY = os.environ.get("RECEIVER_KEY", "")                 # same as RECEIVER_KEY on Vercel (optional)
POLL_SECONDS = float(os.environ.get("POLL_SECONDS", "3"))
IMAGE_SECONDS = float(os.environ.get("IMAGE_SECONDS", "0"))        # 0 = image stays until Esc or next broadcast
SHOW_LAST_ON_START = os.environ.get("SHOW_LAST_ON_START", "0") == "1"
LOCK_PORT = int(os.environ.get("LOCK_PORT", "47653"))             # single-instance guard
CACHE_DIR = os.path.join(os.path.expanduser("~"), ".media_broadcast_cache")
LOG_FILE = os.path.join(CACHE_DIR, "receiver.log")
CACHE_MAX_AGE_DAYS = 7
os.makedirs(CACHE_DIR, exist_ok=True)

# Logging is configured BEFORE the other imports so that a missing VLC/Pillow shows up in the log
# (under pythonw there is no console, so the error would otherwise be invisible).
logging.basicConfig(filename=LOG_FILE, level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("receiver")

try:
    import tkinter as tk
    import requests
    import vlc
    from PIL import Image, ImageTk
except Exception:
    log.exception("Failed to import a required module (tkinter, requests, python-vlc, pillow, or VLC itself)")
    raise


class AuthError(Exception):
    pass


def acquire_single_instance():
    """Bind a local port; a second copy of the receiver fails to bind and exits."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", LOCK_PORT))
    except OSError:
        s.close()
        return None
    s.listen(1)
    return s


def prune_cache():
    cutoff = time.time() - CACHE_MAX_AGE_DAYS * 86400
    for name in os.listdir(CACHE_DIR):
        path = os.path.join(CACHE_DIR, name)
        try:
            if name != "receiver.log" and os.path.isfile(path) and os.path.getmtime(path) < cutoff:
                os.remove(path)
        except OSError:
            pass


class Receiver:
    def __init__(self):
        self.events = queue.Queue()
        self.root = tk.Tk()
        self.root.title("Media Receiver")
        self.root.configure(bg="black", cursor="none")
        self.root.withdraw()                                   # invisible until a broadcast arrives
        self.root.bind("<Escape>", lambda e: self.close_window())   # operator: dismiss
        self.root.bind("<Control-Shift-Q>", lambda e: self.quit())  # operator: stop the receiver

        self.label = tk.Label(self.root, bg="black")
        self.video_frame = tk.Frame(self.root, bg="black")
        self.notice = tk.Label(self.root, bg="black", fg="#cccccc", font=("Segoe UI", 20), wraplength=1000)
        self.photo = None
        self.visible = False
        self._hide_job = None
        self.vlc_instance = vlc.Instance("--no-xlib") if sys.platform.startswith("linux") else vlc.Instance()
        self.player = self.vlc_instance.media_player_new()
        em = self.player.event_manager()
        em.event_attach(vlc.EventType.MediaPlayerEndReached,
                        lambda e: self.events.put(("video_end", None)))
        self.latest_token = 0  # newest event wins if downloads overlap

    # ---------- networking (background threads) ----------
    def listen_loop(self):
        """Poll /api/latest forever; back off on errors. Never touches the UI directly."""
        if not BROADCAST_URL.startswith("http"):
            log.error("BROADCAST_URL is missing or invalid (got %r). Edit receiver.env.", BROADCAST_URL)
            self.events.put(("notice", ("Receiver not configured: BROADCAST_URL is missing.\nEdit receiver.env", 15)))
            return
        url = BROADCAST_URL + "/api/latest"
        params = {"k": RECEIVER_KEY} if RECEIVER_KEY else None
        last_id = None
        first_poll = True
        connected = False
        auth_notified = False
        delay = POLL_SECONDS
        log.info("Polling %s every %ss", url, POLL_SECONDS)
        while True:
            try:
                r = requests.get(url, params=params, timeout=(10, 20))
                if r.status_code == 401:
                    raise AuthError("401 Unauthorized - RECEIVER_KEY does not match the one on Vercel")
                r.raise_for_status()
                if not connected:
                    connected = True
                    log.info("Connected to %s", url)
                delay = POLL_SECONDS
                if r.status_code == 200:
                    data = r.json()
                    event_id = data.get("id")
                    if event_id and event_id != last_id:
                        last_id = event_id
                        if first_poll and not SHOW_LAST_ON_START:
                            log.info("Ignoring event that already existed at startup: %s", event_id)
                        else:
                            log.info("Event: %s", data)
                            self.handle_event(data)
                first_poll = False
            except AuthError as exc:
                log.error("%s", exc)
                if not auth_notified:
                    auth_notified = True
                    self.events.put(("notice", ("Receiver key rejected by server.\nCheck RECEIVER_KEY in receiver.env", 15)))
                delay = 30
            except Exception as exc:
                connected = False
                log.error("Poll failed: %s (retry in %ss)", exc, delay)
                delay = min(delay * 2, 30)
            time.sleep(delay)

    def handle_event(self, data):
        if not isinstance(data, dict) or not data.get("url") or data.get("type") not in ("image", "video"):
            log.error("Ignoring malformed event: %s", data)
            return
        self.latest_token += 1
        token = self.latest_token
        threading.Thread(target=self.download, args=(data, token), daemon=True).start()

    def download(self, data, token):
        try:
            name = os.path.basename(urlparse(data["url"]).path)
            path = os.path.join(CACHE_DIR, name)
            if not os.path.exists(path):
                tmp = path + ".part"
                with requests.get(data["url"], stream=True, timeout=(10, 60)) as r:
                    r.raise_for_status()
                    with open(tmp, "wb") as f:
                        for chunk in r.iter_content(1024 * 256):
                            f.write(chunk)
                os.replace(tmp, path)
            if token == self.latest_token:  # drop if a newer event arrived meanwhile
                self.events.put(("show", (path, data["type"])))
        except Exception as exc:
            log.error("Download failed: %s", exc)

    # ---------- UI (main thread only) ----------
    def poll(self):
        latest_show = None
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "show":
                    latest_show = payload
                elif kind == "video_end":
                    self.close_window()
                elif kind == "notice":
                    self.show_notice(*payload)
        except queue.Empty:
            pass
        if latest_show:
            self.show(*latest_show)
        self.root.after(200, self.poll)

    def _cancel_hide(self):
        if self._hide_job:
            self.root.after_cancel(self._hide_job)
            self._hide_job = None

    def _clear_content(self):
        self.player.stop()
        self.label.pack_forget()
        self.video_frame.pack_forget()
        self.notice.place_forget()

    def open_window(self):
        if not self.visible:
            self.root.deiconify()
            self.root.attributes("-fullscreen", True)
            self.root.attributes("-topmost", True)
            self.visible = True
        self.root.lift()
        self.root.focus_force()
        self.root.update_idletasks()

    def close_window(self):
        """Hide the window again; the receiver keeps running in the background."""
        self._cancel_hide()
        self._clear_content()
        self.root.withdraw()
        self.visible = False

    def show_notice(self, text, seconds):
        self._cancel_hide()
        self._clear_content()
        self.open_window()
        self.notice.configure(text=text)
        self.notice.place(relx=0.5, rely=0.5, anchor="center")
        self._hide_job = self.root.after(int(seconds * 1000), self.close_window)

    def show(self, path, media_type):
        self._cancel_hide()
        self._clear_content()
        self.open_window()
        try:
            if media_type == "image":
                self.show_image(path)
                if IMAGE_SECONDS > 0:
                    self._hide_job = self.root.after(int(IMAGE_SECONDS * 1000), self.close_window)
            else:
                self.show_video(path)
        except Exception as exc:
            log.error("Display failed: %s", exc)
            self.close_window()

    def show_image(self, path):
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        img = Image.open(path)
        img.thumbnail((sw, sh), Image.LANCZOS)  # preserves aspect ratio
        self.photo = ImageTk.PhotoImage(img)
        self.label.configure(image=self.photo)
        self.label.pack(expand=True, fill="both")

    def show_video(self, path):
        self.video_frame.pack(expand=True, fill="both")
        self.root.update_idletasks()
        wid = self.video_frame.winfo_id()
        if sys.platform.startswith("win"):
            self.player.set_hwnd(wid)
        elif sys.platform.startswith("linux"):
            self.player.set_xwindow(wid)
        elif sys.platform == "darwin":
            self.player.set_nsobject(wid)
        self.player.set_media(self.vlc_instance.media_new(path))
        self.player.play()

    def quit(self):
        try:
            self.player.stop()
        finally:
            self.root.destroy()

    def run(self):
        prune_cache()
        threading.Thread(target=self.listen_loop, daemon=True).start()
        self.root.after(200, self.poll)
        self.root.mainloop()


if __name__ == "__main__":
    lock = acquire_single_instance()
    if lock is None:
        log.info("Another receiver is already running; exiting.")
        sys.exit(0)
    try:
        Receiver().run()
    except Exception:
        log.exception("Fatal error")
        raise
