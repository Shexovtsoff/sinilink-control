@echo off
chcp 65001 > nul
echo Запуск Sinilink Web Master...

if exist ".\.venv\Scripts\python.exe" (
    ".\.venv\Scripts\python.exe" app.py
) else (
    python app.py
)

pause
