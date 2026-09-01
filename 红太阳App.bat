@echo off
cd /d "%~dp0"
python -c "from PySide6.QtWidgets import QApplication; from main_window_web import MainWindow; app=QApplication([]); window=MainWindow(); window.showMaximized(); app.exec()"
pause