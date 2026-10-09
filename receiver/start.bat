@echo off
cd /d "%~dp0"
set BROADCAST_URL=https://lab-broadcast-sender.vercel.app
set RECEIVER_KEY=123456789silv
set POLL_SECONDS=3
set IMAGE_SECONDS=5
start "" pythonw receiver.py
