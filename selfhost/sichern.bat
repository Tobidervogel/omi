@echo off
rem Sichert Omi (Selbstbetrieb) aufs NAS. Fuer die Windows-Aufgabenplanung, z. B. taeglich um 3:30 Uhr:
rem   sichern.bat \\jacobnas\JacobNAS\Tobi\Omi-Sicherung
rem Stoppt Omi fuer ein bis zwei Minuten: Beim Beenden schreibt der Datenbank-Emulator eine
rem vollstaendige Sicherung, und keine Datei wird waehrend des Kopierens veraendert.
rem recorder.py haelt seine Auftraege so lange fest und schickt sie danach.
setlocal
set ZIEL=%~1
if "%ZIEL%"=="" (
    echo Ziel fehlt, z. B.: sichern.bat \\jacobnas\JacobNAS\Tobi\Omi-Sicherung
    exit /b 2
)
cd /d "%~dp0"
docker compose stop || goto fehler
robocopy daten "%ZIEL%\daten" /MIR /XD ollama redis /R:2 /W:5 /NP /NFL /NDL
set RC=%ERRORLEVEL%
copy /Y .env "%ZIEL%\.env" >nul
set RC2=%ERRORLEVEL%
docker compose start
if %RC% GEQ 8 goto fehler
if %RC2% NEQ 0 goto fehler
echo Gesichert nach %ZIEL%
exit /b 0

:fehler
echo Sicherung fehlgeschlagen. Ist das NAS erreichbar?
docker compose start
exit /b 1
