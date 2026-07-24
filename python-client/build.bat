@echo off
REM Build script for Secure Chat Desktop Client
REM Run from python-client directory

echo Building Secure Chat Client...

REM Check if pyinstaller is installed
py -m PyInstaller --version >nul 2>&1
if errorlevel 1 (
    echo Installing PyInstaller...
    pip install pyinstaller
)

REM Create icon if not exists (placeholder)
if not exist icon.ico (
    echo Creating placeholder icon...
    python -c "
from PIL import Image, ImageDraw
img = Image.new('RGBA', (256, 256), (26, 26, 46))
d = ImageDraw.Draw(img)
d.rounded_rectangle([32, 32, 224, 224], radius=32, fill=(37, 99, 235))
d.text((128, 128), 'SC', fill=(255,255,255), anchor='mm', font_size=96)
img.save('icon.ico', format='ICO', sizes=[(256,256), (128,128), (64,64), (32,32), (16,16)])
" 2>nul || echo Note: Install pillow for icon generation: pip install pillow
)

echo Building executable...
pyinstaller ^
    --onefile ^
    --windowed ^
    --name "SecureChat" ^
    --icon "icon.ico" ^
    --add-data "README.md;." ^
    --hidden-import "websockets" ^
    --hidden-import "cryptography" ^
    --hidden-import "aiohttp" ^
    --hidden-import "win32gui" ^
    --hidden-import "win32con" ^
    --hidden-import "win32api" ^
    --hidden-import "win32process" ^
    --collect-all "cryptography" ^
    --collect-all "websockets" ^
    secure_chat.py

if errorlevel 1 (
    echo Build failed!
    exit /b 1
)

echo.
echo Build successful!
echo Output: dist\SecureChat.exe
echo.
echo To test: dist\SecureChat.exe