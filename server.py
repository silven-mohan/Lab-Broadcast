"""LAN Media Broadcast - central server (Flask + Flask-SocketIO)."""
import os
import uuid

from flask import Flask, jsonify, render_template, request, send_from_directory
from flask_socketio import SocketIO
from werkzeug.utils import secure_filename

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MEDIA_DIR = os.path.join(BASE_DIR, "media")
os.makedirs(MEDIA_DIR, exist_ok=True)

IMAGE_EXT = {"jpg", "jpeg", "png", "gif", "bmp", "webp"}
VIDEO_EXT = {"mp4", "mkv", "avi", "mov", "webm"}
ALLOWED_EXT = IMAGE_EXT | VIDEO_EXT

# Optional shared secret. If set (environment variable BROADCAST_TOKEN),
# uploads must send it in the X-Token header. Leave unset to disable.
TOKEN = os.environ.get("BROADCAST_TOKEN", "")

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024  # 500 MB limit
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")


def ext_of(filename):
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


@app.route("/")
def index():
    return render_template("index.html", token_required=bool(TOKEN))


@app.route("/upload", methods=["POST"])
def upload():
    if TOKEN and request.headers.get("X-Token") != TOKEN:
        return jsonify(error="Unauthorized"), 401

    file = request.files.get("file")
    if not file or not file.filename:
        return jsonify(error="No file provided"), 400

    original = secure_filename(file.filename)
    ext = ext_of(original)
    if ext not in ALLOWED_EXT:
        return jsonify(error=f"Unsupported file type: .{ext}"), 400

    stored = f"{uuid.uuid4().hex}.{ext}"
    file.save(os.path.join(MEDIA_DIR, stored))

    media_type = "image" if ext in IMAGE_EXT else "video"
    payload = {
        "url": f"{request.host_url}media/{stored}",
        "type": media_type,
        "filename": original,
    }
    socketio.emit("new_media", payload)
    print(f"[BROADCAST] {payload}")
    return jsonify(status="sent", **payload)


@app.route("/media/<path:filename>")
def media(filename):
    return send_from_directory(MEDIA_DIR, filename)


@socketio.on("connect")
def on_connect():
    print(f"[CONNECT] {request.sid}")


@socketio.on("disconnect")
def on_disconnect():
    print(f"[DISCONNECT] {request.sid}")


if __name__ == "__main__":
    print("Open http://localhost:5000 (or http://<this-PC-LAN-IP>:5000 from others)")
    socketio.run(app, host="0.0.0.0", port=5000, allow_unsafe_werkzeug=True)
