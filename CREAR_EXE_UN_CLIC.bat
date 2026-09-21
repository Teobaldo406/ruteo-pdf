@echo off
setlocal
chcp 65001 >nul
title Crear Aplicativo CyR

cd /d "%~dp0"

echo ============================================================
echo        CREAR APLICATIVO CyR - PROCESO AUTOMATICO
echo ============================================================
echo.

where py >nul 2>nul
if errorlevel 1 (
    echo ERROR: No se encontro Python.
    echo Instale Python 3.13 de 64 bits y marque la opcion
    echo "Add Python to PATH" durante la instalacion.
    goto :error
)

py -3.13 -c "import sys; assert sys.maxsize ^> 2**32" >nul 2>nul
if errorlevel 1 (
    echo ERROR: Se necesita Python 3.13 de 64 bits.
    echo Puede descargarlo desde https://www.python.org/downloads/
    goto :error
)

if not exist ".venv-build313\Scripts\python.exe" (
    echo [1/6] Creando el entorno de compilacion...
    py -3.13 -m venv ".venv-build313"
    if errorlevel 1 goto :error
) else (
    echo [1/6] El entorno de compilacion ya existe.
)

set "PYTHON_EXE=%CD%\.venv-build313\Scripts\python.exe"

echo [2/6] Actualizando las herramientas de instalacion...
"%PYTHON_EXE%" -m pip install --upgrade pip
if errorlevel 1 goto :error

echo [3/6] Instalando las dependencias compatibles...
"%PYTHON_EXE%" -m pip install -r requirements.txt
if errorlevel 1 goto :error

echo [4/6] Ejecutando las pruebas automaticas...
"%PYTHON_EXE%" -m unittest discover -s tests -v
if errorlevel 1 goto :error

echo [5/6] Generando el archivo EXE...
"%PYTHON_EXE%" crear_instalable.py
if errorlevel 1 goto :error

echo [6/6] Generando y verificando el archivo ZIP...
"%PYTHON_EXE%" crear_zip_release.py
if errorlevel 1 goto :error
"%PYTHON_EXE%" verificar_release.py
if errorlevel 1 goto :error

echo.
echo ============================================================
echo PROCESO TERMINADO CORRECTAMENTE
echo ============================================================
echo El EXE esta dentro de: dist\Aplicativo CyR
echo El ZIP para compartir esta en esta misma carpeta.
echo.
explorer.exe /select,"%CD%\dist\Aplicativo CyR\Aplicativo CyR.exe"
pause
exit /b 0

:error
echo.
echo ============================================================
echo NO SE PUDO CREAR EL EXE
echo Revise el mensaje de error mostrado arriba.
echo ============================================================
echo.
pause
exit /b 1
