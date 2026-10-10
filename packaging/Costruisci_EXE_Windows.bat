@echo off
setlocal
title Costruttore jot per Windows
color 0B
cd /d "%~dp0\.."
echo =======================================================
echo     COSTRUTTORE ESEGUIBILE WINDOWS JOT
echo =======================================================
echo.
echo Nota prerequisito runtime:
echo   L'app finale richiede Microsoft Edge WebView2 Runtime sui PC Windows.
echo   Se manca, l'interfaccia non parte finche non viene installato.
echo.
where node >nul 2>nul
if errorlevel 1 (
    echo [ERRORE] Node.js non trovato! Installa Node.js da https://nodejs.org
    echo          Serve solo per compilare la WebUI, non agli utenti finali.
    pause
    exit /b 1
)

:: Cerca Python: prima il launcher py, poi python direttamente
set "PYTHON_CMD="
where py >nul 2>nul
if not errorlevel 1 (
    set "PYTHON_CMD=py -3"
) else (
    where python >nul 2>nul
    if not errorlevel 1 (
        set "PYTHON_CMD=python"
    )
)
if "%PYTHON_CMD%"=="" (
    echo [ERRORE] Python non trovato! Installa Python 3.x da https://www.python.org/downloads/
    echo          Durante l'installazione spunta "Add Python to PATH".
    pause
    exit /b 1
)
echo [OK] Python trovato: %PYTHON_CMD%

echo Creazione/attivazione ambiente virtuale (.venv)...
if not exist ".venv\Scripts\python.exe" (
    echo   - Creo .venv con %PYTHON_CMD%...
    %PYTHON_CMD% -m venv .venv
    if errorlevel 1 (
        echo [ERRORE] Impossibile creare l'ambiente virtuale.
        echo          Prova a eseguire manualmente: %PYTHON_CMD% -m venv .venv
        pause
        exit /b 1
    )
)
set "VENV_PYTHON=%CD%\.venv\Scripts\python.exe"
if not exist "%VENV_PYTHON%" (
    echo [ERRORE] Python del virtualenv non trovato: "%VENV_PYTHON%"
    pause
    exit /b 1
)
echo [OK] Virtualenv pronto: "%VENV_PYTHON%"

echo.
echo =======================================================
echo Compilazione WebUI in corso... Questo processo richiede 1-2 minuti.
echo Attendi pazientemente, non chiudere la finestra...
echo =======================================================
echo.

"%VENV_PYTHON%" scripts\build_release.py build --target windows --ui webui --install-deps --dev-deps
if errorlevel 1 (
    echo.
    echo =======================================================
    echo COMPILAZIONE NON RIUSCITA.
    echo =======================================================
    pause
    exit /b 1
)

echo.
echo =======================================================
echo COMPILAZIONE COMPLETATA CON SUCCESSO!
echo =======================================================
echo Troverai il tuo programma pronto all'uso "jot.exe"
echo all'interno della cartella "dist".
echo.
echo Ricorda solo questo prerequisito per Windows:
echo   Microsoft Edge WebView2 Runtime
echo   Download: https://go.microsoft.com/fwlink/p/?LinkId=2124703
echo.
pause
