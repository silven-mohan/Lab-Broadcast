"""Media Broadcast receiver (Vercel/Ably edition).

Listens to an Ably channel over Server-Sent Events (plain HTTPS, no SDK),
downloads the announced file from Vercel Blob and shows it fullscreen.
"""
import json
import logging
import os
import queue
import sys
import threading
import time
import tkinter as tk
from urllib.parse import urlparse

import requests
import vlc
from PIL import Image, ImageTk

# ---------------- Configuration ----------------
ABLY_SUBSCRIBE_KEY = os.environ.get("ABLY_SUBSCRIBE_KEY", "")  # "appId.keyId:secret" (subscribe-only key)
ABLY_CHANNEL = os.environ.get("ABLY_CHANNEL", "media")
CACHE_DIR = os.path.join(os.path.expanduser("~"), ".media_broadcast_cache")
LOG_FILE = os.path.join(CACHE_DIR, "receiver.log")
CACHE_MAX_AGE_DAYS = 7
os.makedirs(CACHE_DIR, exist_ok=True)

logging.basicConfig(filename=LOG_FILE, level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("receiver")


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
        self.root.attributes("-fullscreen", True)
        self.root.attributes("-topmost", True)
        self.root.bind("<Escape>", lambda e: self.quit())  # operator escape hatch

        self.label = tk.Label(self.root, bg="black")
        self.video_frame = tk.Frame(self.root, bg="black")
        self.photo = None
        self.vlc_instance = vlc.Instance("--no-xlib") if sys.platform.startswith("linux") else vlc.Instance()
        self.player = self.vlc_instance.media_player_new()
        em = self.player.event_manager()
        em.event_attach(vlc.EventType.MediaPlayerEndReached,
                        lambda e: self.events.put(("video_end", None)))
        self.download_lock = threading.Lock()
        self.latest_token = 0  # newest event wins if downloads overlap

    # ---------- networking (background threads) ----------
    def listen_loop(self):
        """Subscribe to Ably over SSE; reconnect forever with backoff."""
        if not ABLY_SUBSCRIBE_KEY or ":" not in ABLY_SUBSCRIBE_KEY:
            log.error("ABLY_SUBSCRIBE_KEY is missing or malformed")
            return
        key_name, key_secret = ABLY_SUBSCRIBE_KEY.split(":", 1)
        url = "https://realtime.ably.io/event-stream"
        delay = 2
        while True:
            try:
                with requests.get(url, params={"channels": ABLY_CHANNEL, "v": "1.2"},
                                  auth=(key_name, key_secret), stream=True,
                                  timeout=(10, 90)) as r:
                    r.raise_for_status()
                    log.info("Connected to Ably channel '%s'", ABLY_CHANNEL)
                    delay = 2
                    for raw in r.iter_lines(decode_unicode=True):
                        if raw and raw.startswith("data:"):
                            self.handle_sse(raw[5:].strip())
                log.warning("Stream ended; reconnecting")
            except Exception as exc:
                log.error("Connection error: %s (retry in %ss)", exc, delay)
            time.sleep(delay)
            delay = min(delay * 2, 30)

    def handle_sse(self, payload):
        try:
            msg = json.loads(payload)
            if msg.get("name") != "new_media":
                return
            data = msg["data"]
            if isinstance(data, str):
                data = json.loads(data)
            log.info("Event: %s", data)
            self.latest_token += 1
            token = self.latest_token
            threading.Thread(target=self.download, args=(data, token), daemon=True).start()
        except Exception as exc:
            log.error("Bad event: %s", exc)

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
                    self.idle()
        except queue.Empty:
            pass
        if latest_show:
            self.show(*latest_show)
        self.root.after(200, self.poll)

    def idle(self):
        self.player.stop()
        self.label.pack_forget()
        self.video_frame.pack_forget()

    def show(self, path, media_type):
        self.idle()
        try:
            if media_type == "image":
                self.show_image(path)
            else:
                self.show_video(path)
        except Exception as exc:
            log.error("Display failed: %s", exc)

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
    try:
        Receiver().run()
    except Exception:
        log.exception("Fatal error")
        raise
