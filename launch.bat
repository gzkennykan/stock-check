@echo off
REM 等待网络就绪（开机后延迟10秒）
timeout /t 10 /nobreak >nul
cd /d "D:\CC\CC TEST"
set STREAMLIT_SERVER_HEADLESS=true
start "" http://localhost:8501
streamlit run app.py --server.port 8501
