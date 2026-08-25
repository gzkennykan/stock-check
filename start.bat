@echo off
title Stock Check
cd /d "%~dp0"

REM 先跑缓存预热，完成后释放 DuckDB 锁，再启动 app，避免两个进程争抢同一个数据库文件。
REM warm_cache 内部已 try/except，个别预热失败不影响后续启动。
python warmup.py

start "" http://localhost:8501
streamlit run app.py --server.port 8501 --server.headless true --browser.gatherUsageStats false
pause
