@echo off
rem 备份数据库到 backend\backups（保留最近 14 份）。可加参数：--out "D:\别的目录"
cd /d "%~dp0"
backend\.venv\Scripts\python.exe scripts\backup_db.py %*
pause
