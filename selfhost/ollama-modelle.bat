@echo off
rem Legt die Modelle an, die das Omi-Backend bei Ollama anfragt (Ollama fuer Windows muss laufen).
rem   ollama-modelle.bat                         qwen3:4b-instruct, 16384 Token Kontext
rem   ollama-modelle.bat qwen3:4b-instruct 8192  anderes Modell oder kleinerer Kontext
rem Omi fragt nach gpt-6-luna, gpt-5-nano und text-embedding-3-large. Diese Namen werden hier
rem zu Kopien des lokalen Modells; ein erneuter Aufruf ersetzt sie.
setlocal
set MODELL=%1
if "%MODELL%"=="" set MODELL=qwen3:4b-instruct
set KONTEXT=%2
if "%KONTEXT%"=="" set KONTEXT=16384
set EINBETTUNG=qwen3-embedding:0.6b

ollama pull %MODELL% || goto fehler
ollama pull %EINBETTUNG% || goto fehler
set DATEI=%TEMP%\omi-modell.Modelfile
> "%DATEI%" echo FROM %MODELL%
>> "%DATEI%" echo PARAMETER num_ctx %KONTEXT%
ollama create gpt-6-luna -f "%DATEI%" || goto fehler
ollama create gpt-5-nano -f "%DATEI%" || goto fehler
ollama cp %EINBETTUNG% text-embedding-3-large || goto fehler
del "%DATEI%"
echo.
echo Fertig: gpt-6-luna und gpt-5-nano = %MODELL% mit %KONTEXT% Token, text-embedding-3-large = %EINBETTUNG%
ollama list
exit /b 0

:fehler
echo Fehler. Laeuft Ollama? (Symbol unten rechts in der Taskleiste)
exit /b 1
