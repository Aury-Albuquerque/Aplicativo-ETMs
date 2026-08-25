@echo off
chcp 65001 >nul
setlocal

set "APPDIR=%LOCALAPPDATA%\Programs\ETM Grid Co"
set "EXE=%APPDIR%\ETM-GridCo.exe"
set "SRC=%~dp0ETM-GridCo.exe"

echo ============================================
echo   Instalando o ETM Grid Co
echo ============================================
echo.

if not exist "%SRC%" (
    echo ERRO: nao encontrei o arquivo ETM-GridCo.exe na mesma pasta deste .bat.
    echo Certifique-se de que os dois arquivos estao juntos, na mesma pasta.
    echo.
    pause
    exit /b 1
)

if not exist "%APPDIR%" mkdir "%APPDIR%"

echo Copiando o programa...
copy /y "%SRC%" "%EXE%" >nul
if errorlevel 1 (
    echo ERRO: nao foi possivel copiar o arquivo.
    echo Se o ETM Grid Co estiver aberto, feche e tente novamente.
    echo.
    pause
    exit /b 1
)

echo Criando atalho na Area de Trabalho...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$s = New-Object -ComObject WScript.Shell;" ^
    "$lnk = $s.CreateShortcut((Join-Path ([Environment]::GetFolderPath('Desktop')) 'ETM Grid Co.lnk'));" ^
    "$lnk.TargetPath = '%EXE%';" ^
    "$lnk.WorkingDirectory = '%APPDIR%';" ^
    "$lnk.IconLocation = '%EXE%';" ^
    "$lnk.Save()"

echo Criando atalho no Menu Iniciar...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$dir = Join-Path ([Environment]::GetFolderPath('StartMenu')) 'Programs\ETM Grid Co';" ^
    "if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir | Out-Null };" ^
    "$s = New-Object -ComObject WScript.Shell;" ^
    "$lnk = $s.CreateShortcut((Join-Path $dir 'ETM Grid Co.lnk'));" ^
    "$lnk.TargetPath = '%EXE%';" ^
    "$lnk.WorkingDirectory = '%APPDIR%';" ^
    "$lnk.IconLocation = '%EXE%';" ^
    "$lnk.Save()"

echo.
echo ============================================
echo   Instalacao concluida!
echo ============================================
echo.
echo Abrindo o ETM Grid Co...
start "" "%EXE%"

timeout /t 3 >nul
endlocal
