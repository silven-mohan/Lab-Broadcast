"""LAN Media Broadcast - receiver (Tkinter + Pillow + VLC + Socket.IO client)."""
import logging
import os
import queue
import sys
import threading
import tkinter as tk
from urllib.parse import urlparse

import requests
import socketio
import vlc
from PIL import Image, ImageTk

# ---------------- Configuration ----------------
SERVER_URL = os.environ.get("BROADCAST_SERVER", "http://192.168.1.100:5000")  # <-- change me
CACHE_DIR = os.path.join(os.path.expanduser("~"), ".media_broadcast_cache")
LOG_FILE = os.path.join(CACHE_DIR, "receiver.log")
os.makedirs(CACHE_DIR, exist_ok=True)

logging.basicConfig(filename=LOG_FILE, level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("receiver")


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
        em.event_attach(vlc.EventType.MediaPlayerEndReached, lambda e: self.events.put(("video_end", None)))

        self.sio = socketio.Client(reconnection=True, reconnection_delay=2,
                                   reconnection_delay_max=15)
        self.sio.on("connect", lambda: log.info("Connected to %s", SERVER_URL))
        self.sio.on("disconnect", lambda: log.warning("Disconnected"))
        self.sio.on("new_media", self.on_new_media)

    # ---------- networking (background threads) ----------
    def connect_loop(self):
        while True:
            try:
                self.sio.connect(SERVER_URL)
                self.sio.wait()
            except Exception as exc:
                log.error("Connection failed: %s", exc)
                threading.Event().wait(5)

    def on_new_media(self, data):
        log.info("Event: %s", data)
        threading.Thread(target=self.download, args=(data,), daemon=True).start()

    def download(self, data):
        try:
            name = os.path.basename(urlparse(data["url"]).path)
            path = os.path.join(CACHE_DIR, name)
            if not os.path.exists(path):
                with requests.get(data["url"], stream=True, timeout=30) as r:
                    r.raise_for_status()
                    with open(path, "wb") as f:
                        for chunk in r.iter_content(1024 * 256):
                            f.write(chunk)
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
                    latest_show = payload       # newest event replaces older ones
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
            self.sio.disconnect()
        finally:
            self.root.destroy()

    def run(self):
        threading.Thread(target=self.connect_loop, daemon=True).start()
        self.root.after(200, self.poll)
        self.root.mainloop()


if __name__ == "__main__":
    try:
        Receiver().run()
    except Exception:
        log.exception("Fatal error")
        raise
