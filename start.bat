@echo off
title Stock Check
cd /d "%~dp0"

echo Starting cache warmup in background...
start "Cache Warmup" /min python warmup.py

start "" http://localhost:8501
streamlit run app.py --server.port 8501 --server.headless true --browser.gatherUsageStats false
pause
