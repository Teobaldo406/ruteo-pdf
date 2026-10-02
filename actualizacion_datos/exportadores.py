# -*- coding: utf-8 -*-
"""Exportación interna y TXT externos con contratos explícitos."""

from __future__ import annotations

import csv
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

from .auditoria import escribir_auditoria_csv, escribir_historial_csv, escribir_manifiesto
from .configuracion import ConfiguracionProcesamiento, ContratoTxt
from .modelos import (
    CategoriaResultado,
    ContextoEjecucion,
    EstadoFila,
    ProcesoBloqueadoError,
    RegistroProcesamiento,
)


@dataclass(frozen=True)
class RutasSalida:
    raiz: Path
    data_filtrada: Path
    errores_validacion: Path
    accion_invalida: Path
    revisar_lectura: Path
    cierres_listos: Path
    entregable_cierres: Path
    reaperturas_listas: Path
    entregable_reaperturas: Path
    auditoria: Path


def crear_estructura_salida(carpeta_base: Path, id_ejecucion: str, fecha: str) -> RutasSalida:
    fecha_limpia = "".join(caracter for caracter in fecha if caracter.isdigit()) or datetime.now().strftime("%Y%m%d")
    raiz = Path(carpeta_base) / f"SALIDA_{fecha_limpia}" / f"EJECUCION_{id_ejecucion}"
    nombres = {
        "data_filtrada": "01_DATA_FILTRADA",
        "errores_validacion": "02_ERRORES_VALIDACION",
        "accion_invalida": "03_ACCION_INVALIDA",
        "revisar_lectura": "04_REVISAR_LECTURA",
        "cierres_listos": "05_CIERRES_LISTOS",
        "entregable_cierres": "06_ENTREGABLE_CIERRES",
        "reaperturas_listas": "07_REAPERTURAS_LISTAS",
        "entregable_reaperturas": "08_ENTREGABLE_REAPERTURAS",
        "auditoria": "09_AUDITORIA",
    }
    rutas = {clave: raiz / nombre for clave, nombre in nombres.items()}
    for ruta in rutas.values():
        ruta.mkdir(parents=True, exist_ok=True)
    return RutasSalida(raiz=raiz, **rutas)


def ruta_unica(carpeta: Path, nombre: str) -> Path:
    carpeta.mkdir(parents=True, exist_ok=True)
    candidata = carpeta / nombre
    if not candidata.exists():
        return candidata
    base, sufijo = candidata.stem, candidata.suffix
    correlativo = 2
    while True:
        candidata = carpeta / f"{base}_{correlativo}{sufijo}"
        if not candidata.exists():
            return candidata
        correlativo += 1


def _formatear_fecha(valor: str, formato: str) -> str:
    if not valor:
        return ""
    try:
        return datetime.strptime(valor, "%Y-%m-%d").strftime(formato)
    except ValueError:
        return valor


def _formatear_hora(valor: str, formato: str) -> str:
    if not valor:
        return ""
    try:
        return datetime.strptime(valor, "%H:%M").strftime(formato)
    except ValueError:
        return valor


def _filas_contrato(
    registros: Sequence[RegistroProcesamiento], contrato: ContratoTxt
) -> List[List[str]]:
    if not contrato.confirmado:
        raise ProcesoBloqueadoError(
            f"El formato '{contrato.nombre}' está BLOQUEADO: falta confirmar columnas, encabezado y formato."
        )
    if not contrato.columnas:
        raise ProcesoBloqueadoError(f"El formato '{contrato.nombre}' no tiene columnas configuradas.")
    mapeo = dict(contrato.mapeo_columnas)
    filas: List[List[str]] = []
    for registro in registros:
        salida: List[str] = []
        for columna in contrato.columnas:
            interna = mapeo.get(columna, columna)
            if interna not in registro.datos_normalizados:
                raise ProcesoBloqueadoError(
                    f"El contrato '{contrato.nombre}' requiere '{columna}' y no define su origen interno."
                )
            valor = str(registro.datos_normalizados.get(interna, ""))
            if interna == "FECHA":
                valor = _formatear_fecha(valor, contrato.formato_fecha)
            elif interna in {"HI", "HF"}:
                valor = _formatear_hora(valor, contrato.formato_hora)
            salida.append(valor)
        filas.append(salida)
    return filas


def _escribir_atomico(
    ruta: Path,
    columnas: Sequence[str],
    filas: Sequence[Sequence[str]],
    contrato: ContratoTxt,
) -> Path:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporal = tempfile.mkstemp(prefix=f".{ruta.stem}_", suffix=".tmp", dir=ruta.parent)
    os.close(descriptor)
    ruta_temporal = Path(temporal)
    try:
        with ruta_temporal.open("w", encoding=contrato.codificacion, newline="") as archivo:
            escritor = csv.writer(
                archivo, delimiter=contrato.delimitador, quotechar='"',
                quoting=csv.QUOTE_MINIMAL, lineterminator="\n",
            )
            if contrato.incluir_encabezado:
                escritor.writerow(columnas)
            escritor.writerows(filas)
        if ruta.exists():
            raise FileExistsError(f"No se sobrescribirá el archivo existente '{ruta}'.")
        ruta_temporal.replace(ruta)
    finally:
        if ruta_temporal.exists():
            ruta_temporal.unlink()
    return ruta


def exportar_txt(
    registros: Sequence[RegistroProcesamiento],
    contrato: ContratoTxt,
    carpeta: Path,
    id_ejecucion: str,
) -> Path:
    filas = _filas_contrato(registros, contrato)
    ruta = ruta_unica(carpeta, f"{contrato.nombre}_{id_ejecucion}.txt")
    return _escribir_atomico(ruta, contrato.columnas, filas, contrato)


def exportar_cierres(
    registros: Sequence[RegistroProcesamiento],
    configuracion: ConfiguracionProcesamiento,
    rutas: RutasSalida,
    id_ejecucion: str,
) -> Tuple[Path, Path]:
    # Ambos contratos se validan antes de escribir el primer archivo.
    _filas_contrato(registros, configuracion.contrato_cierres_sistema)
    _filas_contrato(registros, configuracion.contrato_entregable_cierres)
    sistema = exportar_txt(
        registros, configuracion.contrato_cierres_sistema, rutas.cierres_listos, id_ejecucion
    )
    entregable = exportar_txt(
        registros, configuracion.contrato_entregable_cierres, rutas.entregable_cierres, id_ejecucion
    )
    for registro in registros:
        registro.estado = EstadoFila.EXPORTADA
        registro.categoria_final = CategoriaResultado.PROCESADA
        registro.archivo_destino = str(sistema)
        registro.regla_final = "EXP-01"
        registro.etapa_final = "EXPORTACION_CIERRES"
        registro.motivo_final = "CIERRE_EXPORTADO"
        registro.registrar(
            "EXP-01", "EXPORTACION_CIERRES", CategoriaResultado.CONTINUA,
            "Cierre exportado para el sistema y el entregable.", str(sistema), str(entregable),
        )
    return sistema, entregable


def exportar_reaperturas(
    registros: Sequence[RegistroProcesamiento],
    configuracion: ConfiguracionProcesamiento,
    rutas: RutasSalida,
    id_ejecucion: str,
) -> Tuple[Path, Path]:
    _filas_contrato(registros, configuracion.contrato_reaperturas_sistema)
    _filas_contrato(registros, configuracion.contrato_entregable_reaperturas)
    sistema = exportar_txt(
        registros, configuracion.contrato_reaperturas_sistema, rutas.reaperturas_listas, id_ejecucion
    )
    entregable = exportar_txt(
        registros, configuracion.contrato_entregable_reaperturas, rutas.entregable_reaperturas, id_ejecucion
    )
    for registro in registros:
        registro.estado = EstadoFila.EXPORTADA
        registro.categoria_final = CategoriaResultado.PROCESADA
        registro.archivo_destino = str(sistema)
        registro.regla_final = "REA-09"
        registro.etapa_final = "EXPORTACION_REAPERTURAS"
        registro.motivo_final = "REAPERTURA_EXPORTADA"
        registro.registrar(
            "REA-09", "EXPORTACION_REAPERTURAS", CategoriaResultado.CONTINUA,
            "Reapertura exportada para el sistema y el entregable.", str(sistema), str(entregable),
        )
    return sistema, entregable


def exportar_tabla_interna(
    registros: Sequence[RegistroProcesamiento], carpeta: Path, nombre: str, id_ejecucion: str
) -> Path:
    columnas_datos: List[str] = []
    vistos = set()
    for registro in registros:
        for columna in registro.datos_normalizados:
            if columna not in vistos:
                vistos.add(columna)
                columnas_datos.append(columna)
    obligatorias = [
        "ID_FILA", "ETAPA", "CATEGORIA", "REGLA", "MOTIVO", "DESTINO",
        "OT", "OS", "NIS_RAD", "REGLA_PROVISIONAL",
    ]
    columnas = obligatorias + [columna for columna in columnas_datos if columna not in {
        "OT", "OS", "NIS", "REGLA_PROVISIONAL",
    }]
    ruta = ruta_unica(carpeta, f"{nombre}_{id_ejecucion}.csv")
    with ruta.open("w", encoding="utf-8-sig", newline="") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=columnas, delimiter=";", extrasaction="ignore")
        escritor.writeheader()
        for registro in registros:
            fila = {
                "ID_FILA": registro.id_fila,
                "ETAPA": registro.etapa_final,
                "CATEGORIA": registro.categoria_final.value,
                "MOTIVO": registro.motivo_final,
                "REGLA": registro.regla_final,
                "DESTINO": registro.archivo_destino or registro.estado.value,
                "OT": registro.ot,
                "OS": registro.os,
                "NIS_RAD": registro.nis,
                "REGLA_PROVISIONAL": registro.datos_normalizados.get("REGLA_PROVISIONAL", "NO"),
            }
            fila.update(registro.datos_normalizados)
            escritor.writerow(fila)
    return ruta


def exportar_auditoria_total(
    contexto: ContextoEjecucion,
    registros: Sequence[RegistroProcesamiento],
    rutas: RutasSalida,
) -> Dict[str, Path]:
    identificador = contexto.id_ejecucion
    archivos = {
        "auditoria": escribir_auditoria_csv(
            rutas.auditoria / f"AUDITORIA_FILAS_{identificador}.csv", identificador, registros
        ),
        "historial": escribir_historial_csv(
            rutas.auditoria / f"HISTORIAL_VALIDACIONES_{identificador}.csv", identificador, registros
        ),
        "manifiesto": escribir_manifiesto(
            rutas.auditoria / f"MANIFIESTO_EJECUCION_{identificador}.json", contexto
        ),
    }
    return archivos
