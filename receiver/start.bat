@echo off
cd /d "%~dp0"
rem Settings live in receiver.env (copy receiver.env.example to receiver.env and edit it).
rem Put a shortcut to THIS file in the Startup folder (Win+R -> shell:startup).
rem pythonw runs with no console window; the receiver stays hidden until a broadcast arrives.
start "" pythonw receiver.py
