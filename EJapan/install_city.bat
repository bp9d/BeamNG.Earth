@echo off
rem Install a PLATEAU city's buildings into BeamNG.Earth.
rem Drag a city's CityGML zip onto this file, or run:
rem   install_city.bat path\to\city.zip
rem   install_city.bat --list
rem It converts the zip into EJapan\plateau_data and bumps the data version, so the
rem server rebuilds the affected map cells on its next start.
cd /d "%~dp0.."
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" "EJapan\install_city.py" %*
) else (
  py -3 "EJapan\install_city.py" %*
)
echo.
pause
