@echo off
setlocal
cd /d "%~dp0"

if not exist "douyin-LiveRec-king.exe" (
  echo Cannot find douyin-LiveRec-king.exe.
  echo Please extract the complete ZIP package before running.
  pause
  exit /b 1
)

start "" "douyin-LiveRec-king.exe"
endlocal
