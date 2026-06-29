# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import re
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
    if assets:
        download_url = str(assets[0].get("browser_download_url") or "")

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
