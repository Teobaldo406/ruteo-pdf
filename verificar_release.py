# -*- coding: utf-8 -*-
"""Comprueba automáticamente el paquete generado para publicar."""

from __future__ import annotations

import hashlib
from pathlib import Path
from zipfile import BadZipFile, ZipFile


CARPETA_PROYECTO = Path(__file__).resolve().parent
NOMBRE_APLICACION = "Aplicativo CyR"
ARCHIVO_VERSION = CARPETA_PROYECTO / "VERSION"


def calcular_sha256(ruta: Path) -> str:
    resumen = hashlib.sha256()
    with ruta.open("rb") as archivo:
        for bloque in iter(lambda: archivo.read(1024 * 1024), b""):
            resumen.update(bloque)
    return resumen.hexdigest().upper()


def main() -> int:
    version = ARCHIVO_VERSION.read_text(encoding="utf-8").strip()
    ruta_zip = CARPETA_PROYECTO / f"{NOMBRE_APLICACION}_v{version}.zip"
    ejecutable = f"{NOMBRE_APLICACION}/{NOMBRE_APLICACION}.exe"
    version_interna = f"{NOMBRE_APLICACION}/VERSION"

    if not ruta_zip.exists():
        print(f"ERROR: No existe el paquete: {ruta_zip}")
        return 1

    try:
        with ZipFile(ruta_zip) as paquete:
            nombres = set(paquete.namelist())
            faltantes = [
                nombre for nombre in (ejecutable, version_interna)
                if nombre not in nombres
            ]
            archivo_danado = paquete.testzip()
    except BadZipFile:
        print("ERROR: El ZIP generado no es válido.")
        return 1

    if faltantes:
        print("ERROR: Faltan archivos indispensables en el ZIP:")
        for nombre in faltantes:
            print(f"- {nombre}")
        return 1

    if archivo_danado:
        print(f"ERROR: Hay un archivo dañado dentro del ZIP: {archivo_danado}")
        return 1

    print("OK. El ZIP está completo y no contiene archivos dañados.")
    print(f"Versión: {version}")
    print(f"SHA-256: {calcular_sha256(ruta_zip)}")
    print(f"Paquete: {ruta_zip}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
