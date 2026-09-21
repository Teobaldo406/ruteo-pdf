# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


ROOT = Path(__file__).resolve().parent
APP_NAME = "Aplicativo CyR"
APP_DIST_DIR = ROOT / "dist" / APP_NAME
EXE_PATH = APP_DIST_DIR / f"{APP_NAME}.exe"
VERSION_PATH = ROOT / "VERSION"
README_PATH = ROOT / "LEEME_PRIMERO.txt"


def main() -> int:
    if not EXE_PATH.exists():
        print("ERROR: No existe el EXE final.")
        print("Primero ejecuta: python crear_instalable.py")
        return 1

    version = VERSION_PATH.read_text(encoding="utf-8").strip() if VERSION_PATH.exists() else "0.0.0"
    zip_path = ROOT / f"{APP_NAME}_v{version}.zip"
    if zip_path.exists():
        zip_path.unlink()

    with ZipFile(zip_path, "w", compression=ZIP_DEFLATED) as archive:
        for path in APP_DIST_DIR.rglob("*"):
            if path.is_file():
                archive.write(path, path.relative_to(APP_DIST_DIR.parent))

    print("")
    print("OK. ZIP listo para GitHub Releases:")
    print(zip_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
