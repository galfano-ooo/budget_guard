@echo off
setlocal

rem BudgetGuard UE project installer launcher.
rem Opens the GUI installer (installer\install_ue_project_gui.py) using whatever
rem Python is already on this machine - no extra dependencies to install.

set GUI_SCRIPT=%~dp0install_ue_project_gui.py

where py >nul 2>nul
if %ERRORLEVEL%==0 (
    py "%GUI_SCRIPT%"
    goto :end
)

where python >nul 2>nul
if %ERRORLEVEL%==0 (
    python "%GUI_SCRIPT%"
    goto :end
)

echo No Python installation found on this machine.
echo Install Python 3 from https://www.python.org/downloads/ and try again.
pause

:end
endlocal
