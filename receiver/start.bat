@echo off
cd /d "%~dp0"
rem Paste your Ably SUBSCRIBE-ONLY key below (format: appId.keyId:secret).
rem Then put a shortcut to this file in the Startup folder (Win+R -> shell:startup).
set ABLY_SUBSCRIBE_KEY=PASTE_SUBSCRIBE_ONLY_KEY_HERE
set ABLY_CHANNEL=media
start "" pythonw receiver.py
