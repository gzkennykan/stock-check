@echo off
title Stock Check
cd /d "D:\CC\CC TEST"
start "" http://localhost:8501
streamlit run app.py --server.port 8501 --server.headless true --browser.gatherUsageStats false
pause
