# -*- coding: utf-8 -*-
"""Cruces de archivos CSV para el módulo Depuración OT."""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Sequence, Tuple


@dataclass(frozen=True)
class ResultadoDepuracion:
    ruta_accion_depurada: Path
    ruta_plantilla_depurada: Path
    filas_accion: int
    filas_plantilla: int
    total_accion_original: int
    total_plantilla_original: int


def normalizar_identificador(valor: object) -> str:
    """Normaliza espacios y la conversión numérica que agrega un decimal .0."""
    texto = re.sub(r"\s+", "", "" if valor is None else str(valor))
    coincidencia = re.fullmatch(r"([+-]?\d+)\.0+", texto)
    return coincidencia.group(1) if coincidencia else texto


def _leer_csv(ruta: Path) -> Tuple[List[str], List[Dict[str, str]], csv.Dialect]:
    contenido = None
    for codificacion in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            contenido = ruta.read_text(encoding=codificacion)
            break
        except UnicodeDecodeError:
            continue
    if contenido is None:
        raise ValueError(f"No se pudo leer el archivo {ruta.name}.")

    muestra = contenido[:8192]
    encabezado = contenido.splitlines()[0] if contenido.splitlines() else ""
    separadores = ("\t", ";", ",", "|")
    separador_encabezado = max(separadores, key=encabezado.count)
    try:
        if encabezado.count(separador_encabezado):
            dialecto = csv.Sniffer().sniff(encabezado, delimiters=separador_encabezado)
        else:
            dialecto = csv.Sniffer().sniff(muestra, delimiters=",;\t|")
    except csv.Error:
        dialecto = csv.excel

    lector = csv.DictReader(io.StringIO(contenido), dialect=dialecto)
    columnas = lector.fieldnames or []
    if not columnas:
        raise ValueError(f"El archivo {ruta.name} no tiene encabezados.")
    return columnas, list(lector), dialecto


def _buscar_columna(columnas: Sequence[str], requerida: str, archivo: str) -> str:
    equivalencias = {columna.lstrip("\ufeff").strip().lower(): columna for columna in columnas}
    encontrada = equivalencias.get(requerida.lower())
    if encontrada is None:
        raise ValueError(f"Falta la columna '{requerida}' en {archivo}.")
    return encontrada


def _escribir_csv(
    ruta: Path,
    columnas: Sequence[str],
    filas: Sequence[Dict[str, str]],
    dialecto: csv.Dialect,
) -> None:
    with ruta.open("w", encoding="utf-8-sig", newline="") as archivo:
        escritor = csv.DictWriter(
            archivo,
            fieldnames=columnas,
            delimiter=dialecto.delimiter,
            quotechar='"',
            quoting=csv.QUOTE_MINIMAL,
            lineterminator="\n",
            extrasaction="ignore",
        )
        escritor.writeheader()
        escritor.writerows(filas)


def depurar_ordenes(
    ruta_reaperturas: Path,
    ruta_accion: Path,
    ruta_plantilla: Path,
    carpeta_salida: Path | None = None,
) -> ResultadoDepuracion:
    columnas_reaperturas, reaperturas, _ = _leer_csv(ruta_reaperturas)
    columnas_accion, accion, dialecto_accion = _leer_csv(ruta_accion)
    columnas_plantilla, plantilla, dialecto_plantilla = _leer_csv(ruta_plantilla)

    nis_reaperturas = _buscar_columna(columnas_reaperturas, "nis_rad", "REAPERTURAS")
    nis_accion = _buscar_columna(columnas_accion, "nis_rad", "ACCIÓN")
    ot_accion = _buscar_columna(columnas_accion, "nro_ot", "ACCIÓN")
    ot_plantilla = _buscar_columna(columnas_plantilla, "nro_ot", "PLANTILLA")

    identificadores_reabiertos = {
        normalizar_identificador(fila.get(nis_reaperturas)) for fila in reaperturas
    }
    accion_depurada = [
        fila
        for fila in accion
        if normalizar_identificador(fila.get(nis_accion)) not in identificadores_reabiertos
    ]

    ordenes_depuradas = {
        normalizar_identificador(fila.get(ot_accion)) for fila in accion_depurada
    }
    plantilla_depurada = [
        fila
        for fila in plantilla
        if normalizar_identificador(fila.get(ot_plantilla)) in ordenes_depuradas
    ]

    destino = carpeta_salida if carpeta_salida is not None else ruta_accion.parent
    destino.mkdir(parents=True, exist_ok=True)
    salida_accion = destino / "ACCION_DEPURADA.csv"
    salida_plantilla = destino / "PLANTILLA_DEPURADA.csv"
    originales = {ruta.resolve() for ruta in (ruta_reaperturas, ruta_accion, ruta_plantilla)}
    if salida_accion.resolve() in originales or salida_plantilla.resolve() in originales:
        raise ValueError("Un archivo original tiene el mismo nombre que un archivo de salida.")

    _escribir_csv(salida_accion, columnas_accion, accion_depurada, dialecto_accion)
    _escribir_csv(salida_plantilla, columnas_plantilla, plantilla_depurada, dialecto_plantilla)
    return ResultadoDepuracion(
        ruta_accion_depurada=salida_accion,
        ruta_plantilla_depurada=salida_plantilla,
        filas_accion=len(accion_depurada),
        filas_plantilla=len(plantilla_depurada),
        total_accion_original=len(accion),
        total_plantilla_original=len(plantilla),
    )
