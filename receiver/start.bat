@echo off
cd /d "%~dp0"
rem 1) Set BROADCAST_URL to your deployed Vercel site (no trailing slash).
rem 2) If you set RECEIVER_KEY in Vercel, put the same value here. Otherwise leave it empty.
rem 3) Put a shortcut to this file in the Startup folder (Win+R -> shell:startup).
set BROADCAST_URL=https://lab-broadcast-sender.vercel.app
set RECEIVER_KEY=
set POLL_SECONDS=3
start "" pythonw receiver.py
