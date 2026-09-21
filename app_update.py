# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import re
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Dict, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


# Cambiar esto cuando el proyecto ya exista en GitHub:
# Ejemplo: "tu_usuario/ruteo-pdf"
APP_GITHUB_REPOSITORY = "Teobaldo406/ruteo-pdf"


def _read_version() -> str:
    version_file = Path(__file__).resolve().parent / "VERSION"
    if not version_file.exists():
        return "0.0.0"
    return version_file.read_text(encoding="utf-8").strip() or "0.0.0"


CURRENT_VERSION = _read_version()


def _version_tuple(value: str) -> Tuple[int, ...]:
    parts = re.findall(r"\d+", value or "")
    return tuple(int(part) for part in parts[:4]) or (0,)


def check_for_updates(repository: str = APP_GITHUB_REPOSITORY, current_version: str = CURRENT_VERSION) -> Dict[str, object]:
    if not repository:
        return {
            "configured": False,
            "update_available": False,
            "current_version": current_version,
            "message": "Actualizaciones no configuradas. Falta colocar el repositorio GitHub en app_update.py.",
        }

    api_url = f"https://api.github.com/repos/{repository}/releases/latest"
    request = Request(api_url, headers={"User-Agent": "RuteoPDF-Updater/1.0"})
    try:
        with urlopen(request, timeout=25) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise RuntimeError("No se pudo consultar GitHub Releases. Verifica que el repositorio tenga releases.") from exc
    except URLError as exc:
        raise RuntimeError("No se pudo conectar con GitHub. Revisa tu conexión a internet.") from exc

    latest_version = str(payload.get("tag_name") or payload.get("name") or "").lstrip("vV")
    release_url = str(payload.get("html_url") or "")
    assets = payload.get("assets") if isinstance(payload.get("assets"), list) else []
    download_url = ""
    for archivo in assets:
        nombre = str(archivo.get("name") or "")
        if nombre.lower().endswith(".zip"):
            download_url = str(archivo.get("browser_download_url") or "")
            break

    update_available = _version_tuple(latest_version) > _version_tuple(current_version)
    return {
        "configured": True,
        "update_available": update_available,
        "current_version": current_version,
        "latest_version": latest_version,
        "release_url": release_url,
        "download_url": download_url,
        "message": "Hay una actualización disponible." if update_available else "Ya tienes la última versión.",
    }


def preparar_actualizacion_automatica(
    url_descarga: str,
    carpeta_instalacion: Path,
    nombre_ejecutable: str = "Aplicativo CyR.exe",
) -> Dict[str, str]:
    """Descarga, valida y prepara el reemplazo seguro de la aplicación."""
    if not url_descarga.lower().endswith(".zip"):
        raise RuntimeError("La publicación nueva no contiene un archivo ZIP compatible.")

    carpeta_temporal = Path(tempfile.mkdtemp(prefix="actualizacion_cyr_"))
    archivo_zip = carpeta_temporal / "actualizacion.zip"
    carpeta_extraida = carpeta_temporal / "contenido"
    carpeta_extraida.mkdir()

    solicitud = Request(url_descarga, headers={"User-Agent": "Aplicativo-CyR-Updater/1.0"})
    try:
        with urlopen(solicitud, timeout=60) as respuesta, archivo_zip.open("wb") as destino:
            shutil.copyfileobj(respuesta, destino)
    except (HTTPError, URLError, OSError) as exc:
        shutil.rmtree(carpeta_temporal, ignore_errors=True)
        raise RuntimeError("No se pudo descargar la actualización. Revisa la conexión a internet.") from exc

    try:
        with zipfile.ZipFile(archivo_zip) as paquete:
            raiz_segura = carpeta_extraida.resolve()
            for elemento in paquete.infolist():
                destino = (carpeta_extraida / elemento.filename).resolve()
                if raiz_segura != destino and raiz_segura not in destino.parents:
                    raise RuntimeError("El ZIP de actualización contiene una ruta no segura.")
            archivo_danado = paquete.testzip()
            if archivo_danado:
                raise RuntimeError(f"El ZIP descargado está dañado: {archivo_danado}")
            paquete.extractall(carpeta_extraida)
    except (zipfile.BadZipFile, OSError) as exc:
        shutil.rmtree(carpeta_temporal, ignore_errors=True)
        raise RuntimeError("El archivo descargado no es un ZIP válido.") from exc

    carpetas_candidatas = [
        ruta.parent
        for ruta in carpeta_extraida.rglob(nombre_ejecutable)
        if ruta.is_file()
    ]
    if len(carpetas_candidatas) != 1:
        shutil.rmtree(carpeta_temporal, ignore_errors=True)
        raise RuntimeError("El ZIP no contiene exactamente una copia válida del aplicativo.")

    carpeta_nueva = carpetas_candidatas[0]
    archivo_version = carpeta_nueva / "VERSION"
    if not archivo_version.exists():
        shutil.rmtree(carpeta_temporal, ignore_errors=True)
        raise RuntimeError("La actualización no contiene el archivo VERSION.")

    ruta_script = carpeta_temporal / "instalar_actualizacion.ps1"
    ruta_script.write_text(
        """param(
    [Parameter(Mandatory=$true)][int]$IdProceso,
    [Parameter(Mandatory=$true)][string]$CarpetaActual,
    [Parameter(Mandatory=$true)][string]$CarpetaNueva,
    [Parameter(Mandatory=$true)][string]$NombreEjecutable
)
$ErrorActionPreference = 'Stop'
$CarpetaAnterior = $CarpetaActual + '_anterior'
try {
    Wait-Process -Id $IdProceso -ErrorAction SilentlyContinue
    if (Test-Path -LiteralPath $CarpetaAnterior) {
        Remove-Item -LiteralPath $CarpetaAnterior -Recurse -Force
    }
    Move-Item -LiteralPath $CarpetaActual -Destination $CarpetaAnterior
    Move-Item -LiteralPath $CarpetaNueva -Destination $CarpetaActual

    $ConfiguracionAnterior = Join-Path $CarpetaAnterior 'config'
    $ConfiguracionNueva = Join-Path $CarpetaActual 'config'
    if (Test-Path -LiteralPath $ConfiguracionAnterior) {
        New-Item -ItemType Directory -Path $ConfiguracionNueva -Force | Out-Null
        Copy-Item -Path (Join-Path $ConfiguracionAnterior '*') -Destination $ConfiguracionNueva -Recurse -Force
    }

    Start-Process -FilePath (Join-Path $CarpetaActual $NombreEjecutable)
} catch {
    if (-not (Test-Path -LiteralPath $CarpetaActual) -and (Test-Path -LiteralPath $CarpetaAnterior)) {
        Move-Item -LiteralPath $CarpetaAnterior -Destination $CarpetaActual
    }
    Add-Type -AssemblyName PresentationFramework
    [System.Windows.MessageBox]::Show(
        "No se pudo instalar la actualización.`n`n$($_.Exception.Message)",
        'Aplicativo CyR'
    ) | Out-Null
}
""",
        encoding="utf-8-sig",
    )

    return {
        "script": str(ruta_script),
        "carpeta_actual": str(carpeta_instalacion.resolve()),
        "carpeta_nueva": str(carpeta_nueva.resolve()),
        "nombre_ejecutable": nombre_ejecutable,
    }
