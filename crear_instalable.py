# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
APP_NAME = "RUTEO_PDF"
DIST_DIR = ROOT / "dist"
EXE_PATH = DIST_DIR / f"{APP_NAME}.exe"


def _check_import(module_name: str, pip_name: str, missing: list[str]) -> None:
    try:
        __import__(module_name)
    except Exception:
        missing.append(pip_name)


def check_dependencies() -> None:
    missing: list[str] = []
    _check_import("PyInstaller", "pyinstaller", missing)
    _check_import("PySide6", "PySide6", missing)
    _check_import("reportlab", "reportlab", missing)
    _check_import("googleapiclient", "google-api-python-client", missing)
    _check_import("google.auth", "google-auth", missing)
    _check_import("google_auth_oauthlib", "google-auth-oauthlib", missing)
    if missing:
        deps = " ".join(missing)
        raise RuntimeError(
            "Faltan dependencias para compilar.\n"
            f"Instala una sola vez con: {sys.executable} -m pip install {deps}"
        )


def clean_previous_build() -> None:
    targets = [
        ROOT / "build",
        DIST_DIR,
        ROOT / f"{APP_NAME}.spec",
    ]
    for target in targets:
        if target.is_dir():
            shutil.rmtree(target)
        elif target.exists():
            target.unlink()


def build_exe() -> None:
    icon_path = ROOT / "assets" / "app_icon.ico"
    if not icon_path.exists():
        raise FileNotFoundError(f"No existe el icono: {icon_path}")

    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--windowed",
        "--name",
        APP_NAME,
        "--icon",
        str(icon_path),
        "--add-data",
        f"{ROOT / 'VERSION'}{os.pathsep}.",
        "--add-data",
        f"{ROOT / 'assets'}{os.pathsep}assets",
        str(ROOT / "app_ruteo_pdf.py"),
    ]
    subprocess.run(command, cwd=ROOT, check=True)

    if not EXE_PATH.exists():
        raise FileNotFoundError(f"No se generó el EXE esperado: {EXE_PATH}")

    for support_file in ("LEEME_PRIMERO.txt", "VERSION"):
        source = ROOT / support_file
        if source.exists():
            shutil.copy2(source, DIST_DIR / support_file)

    spec_path = ROOT / f"{APP_NAME}.spec"
    if spec_path.exists():
        spec_path.unlink()


def main() -> int:
    try:
        check_dependencies()
        clean_previous_build()
        build_exe()
    except Exception as exc:
        print("")
        print("ERROR: No se pudo crear el EXE.")
        print(exc)
        return 1

    print("")
    print("OK. EXE listo con dependencias incluidas:")
    print(EXE_PATH)
    print("")
    print("El usuario final solo debe abrir RUTEO_PDF.exe. No se necesita BAT ni Python instalado.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
