@echo off
echo Cleaning Python cache...

rem Удаляем __pycache__
for /d /r %%i in (__pycache__) do (
    echo Removing %%i
    rmdir /s /q "%%i"
)

rem Удаляем *.pyc
for /r %%f in (*.pyc) do (
    echo Removing %%f
    del /q "%%f"
)

echo.
echo Starting server...
python -B -m llm_trading_system.api.server --log-level debug

echo.
pause