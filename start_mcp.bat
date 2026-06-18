@echo off
cd /d "%~dp0"

echo Starting Kapsula MCP Server...
echo MCP  -^> http://localhost:8002

:: Activate virtual environment and run
call .venv\Scripts\activate.bat

:: Force HTTP transport for client connectivity
set KAPSULA_TRANSPORT=http
set KAPSULA_HOST=127.0.0.1
set KAPSULA_PORT=8002

python run_mcp.py

pause
