# -*- coding: utf-8 -*-
"""Auditoría y conciliación: ninguna fila puede desaparecer sin motivo."""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Iterable, List, Sequence

from .modelos import (
    CategoriaResultado,
    ContextoEjecucion,
    RegistroProcesamiento,
    ResumenEtapa,
)


COLUMNAS_AUDITORIA = (
    "ID_EJECUCION", "ID_FILA", "ARCHIVO_ORIGEN", "FILA_ORIGEN", "FILA_ORIGINAL", "ETAPA",
    "REGLA_APLICADA", "REGLA", "CATEGORIA", "MOTIVO", "DESTINO", "OT", "OS", "NIS", "NIS_RAD",
    "COO_ORIGINAL", "COO_ORIGINAL_SYSACAO", "COO_FINAL_GIO", "ESTADO_CONVERSION",
    "RGLA_ORIGINAL", "OBSERVACION_ORIGINAL", "NCOD_CAUSA_ORIGINAL",
    "NCOD_CAUSA_CONTROL_GIO", "OBSERVACION_CONTROL_GIO",
    "ID_REGLA_GIO", "PRIORIDAD_REGLA_GIO", "RESULTADO_REGLA_GIO",
    "CATEGORIA_REGLA_GIO", "MOTIVO_REGLA_GIO", "DESTINO_REGLA_GIO",
    "ESTADO_VALIDACION_GIO", "VALIDACION_LECTURA", "MOTIVO_LECTURA", "RESULTADO_LECTURA",
    "REGLA_PROVISIONAL", "ESTADO_FILA", "ARCHIVO_DESTINO",
)


def calcular_huella_archivo(ruta: Path, bloque: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with ruta.open("rb") as archivo:
        while contenido := archivo.read(bloque):
            digest.update(contenido)
    return digest.hexdigest()


def crear_id_ejecucion(fecha_procesamiento: str) -> str:
    ahora = datetime.now()
    fecha = "".join(caracter for caracter in fecha_procesamiento if caracter.isdigit()) or ahora.strftime("%Y%m%d")
    return f"{fecha}_{ahora:%H%M%S_%f}"[:24]


def crear_contexto(fecha_procesamiento: str, carpeta_salida: Path) -> ContextoEjecucion:
    return ContextoEjecucion(
        id_ejecucion=crear_id_ejecucion(fecha_procesamiento),
        fecha_procesamiento=fecha_procesamiento,
        carpeta_salida=carpeta_salida,
    )


def resumir_etapa(etapa: str, registros: Iterable[RegistroProcesamiento]) -> ResumenEtapa:
    filas = list(registros)
    resumen = ResumenEtapa(etapa=etapa, entradas=len(filas))
    for fila in filas:
        categoria = fila.categoria_final
        if categoria == CategoriaResultado.CONTINUA:
            resumen.continuan += 1
        elif categoria == CategoriaResultado.PROCESADA:
            resumen.procesadas += 1
        elif categoria == CategoriaResultado.EXCLUSION_OPERATIVA:
            resumen.exclusiones_operativas += 1
        elif categoria == CategoriaResultado.REVISION_MANUAL:
            resumen.revisiones += 1
        else:
            resumen.errores_tecnicos += 1
    return resumen


def verificar_conservacion(registros_entrada: Sequence[RegistroProcesamiento]) -> None:
    ids = [fila.id_fila for fila in registros_entrada]
    repetidos = [identificador for identificador, cantidad in Counter(ids).items() if cantidad > 1]
    if repetidos:
        raise ValueError(f"La auditoría contiene ID_FILA repetidos: {', '.join(repetidos[:5])}.")
    sin_clasificar = [fila.id_fila for fila in registros_entrada if not fila.estado]
    if sin_clasificar:
        raise ValueError(f"Hay filas sin estado auditable: {', '.join(sin_clasificar[:5])}.")


def escribir_auditoria_csv(
    ruta: Path,
    id_ejecucion: str,
    registros: Sequence[RegistroProcesamiento],
) -> Path:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    originales: List[str] = []
    vistos = set(COLUMNAS_AUDITORIA)
    for registro in registros:
        for columna in registro.datos_originales:
            nombre = f"ORIGINAL_{columna}"
            if nombre not in vistos:
                originales.append(nombre)
                vistos.add(nombre)
    columnas = list(COLUMNAS_AUDITORIA) + originales
    with ruta.open("w", encoding="utf-8-sig", newline="") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=columnas, delimiter=";", extrasaction="ignore")
        escritor.writeheader()
        for registro in registros:
            fila = registro.como_fila_auditoria(id_ejecucion)
            fila.update({f"ORIGINAL_{clave}": valor for clave, valor in registro.datos_originales.items()})
            escritor.writerow(fila)
    return ruta


def escribir_historial_csv(
    ruta: Path,
    id_ejecucion: str,
    registros: Sequence[RegistroProcesamiento],
) -> Path:
    columnas = (
        "ID_EJECUCION", "ID_FILA", "ORDEN", "FECHA_HORA", "ETAPA", "REGLA_APLICADA",
        "CATEGORIA", "MOTIVO", "VALOR_RECIBIDO", "VALOR_ESPERADO",
    )
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with ruta.open("w", encoding="utf-8-sig", newline="") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=columnas, delimiter=";", extrasaction="ignore")
        escritor.writeheader()
        for registro in registros:
            for orden, validacion in enumerate(registro.historial, 1):
                fila = validacion.como_diccionario()
                escritor.writerow({
                    "ID_EJECUCION": id_ejecucion,
                    "ID_FILA": registro.id_fila,
                    "ORDEN": orden,
                    "FECHA_HORA": fila["fecha_hora"],
                    "ETAPA": fila["etapa"],
                    "REGLA_APLICADA": fila["regla_aplicada"],
                    "CATEGORIA": fila["categoria"],
                    "MOTIVO": fila["motivo"],
                    "VALOR_RECIBIDO": fila["valor_recibido"],
                    "VALOR_ESPERADO": fila["valor_esperado"],
                })
    return ruta


def escribir_manifiesto(ruta: Path, contexto: ContextoEjecucion) -> Path:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    contenido = asdict(contexto)
    contenido["carpeta_salida"] = str(contexto.carpeta_salida)
    contenido["estados_etapas"] = {
        clave: valor.value for clave, valor in contexto.estados_etapas.items()
    }
    ruta.write_text(json.dumps(contenido, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return ruta
