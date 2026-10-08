@echo off
cd /d "%~dp0"
rem Edit the server address below, then place a shortcut to this file in:
rem   Win+R -> shell:startup
set BROADCAST_SERVER=http://192.168.1.100:5000
start "" pythonw receiver.py
