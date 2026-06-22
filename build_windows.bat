@echo off
setlocal
cd /d "%~dp0"

where uv >nul 2>nul
if errorlevel 1 (
  echo ERROR: uv is required for a clean Windows build.
  echo Install it from https://docs.astral.sh/uv/
  exit /b 1
)

if not exist ".build-venv\Scripts\python.exe" (
  uv python install 3.12
  uv venv --python 3.12 .build-venv
)

call ".build-venv\Scripts\activate.bat"
uv pip install --python ".build-venv\Scripts\python.exe" ".[dev]"

python -m PyInstaller ^
  --noconfirm ^
  --clean ^
  --windowed ^
  --name "douyin-LiveRec-king" ^
  --paths "src" ^
  --collect-data "streamget" ^
  --hidden-import "socksio" ^
  "main.py"

if exist "runtime\ffmpeg\bin\ffmpeg.exe" (
  xcopy /E /I /Y "runtime\ffmpeg" "dist\douyin-LiveRec-king\runtime\ffmpeg" >nul
)

if not exist "dist\douyin-LiveRec-king\config" mkdir "dist\douyin-LiveRec-king\config"
copy /Y "config\config.example.ini" "dist\douyin-LiveRec-king\config\config.example.ini" >nul
copy /Y "启动程序.bat" "dist\douyin-LiveRec-king\启动程序.bat" >nul

echo.
echo Build complete: dist\douyin-LiveRec-king\douyin-LiveRec-king.exe
endlocal
