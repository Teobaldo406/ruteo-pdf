# -*- coding: utf-8 -*-
"""Contratos provisionales de salida mientras se confirma el formato definitivo.

Las decisiones de acciones no viven en este archivo: se cargan exclusivamente
desde la hoja REGLAS_GIO de la matriz seleccionada por el usuario.
"""

from __future__ import annotations

from .configuracion import ConfiguracionProcesamiento, ContratoTxt

COLUMNAS_SISTEMA = (
    "OT", "OS", "FEJECUCION", "HI", "HF", "ACCION", "CODIGO", "OBSERVACION", "LECT",
)
COLUMNAS_ENTREGABLE = ("nis_rad", *COLUMNAS_SISTEMA)
MAPEO_SALIDA = (
    ("FEJECUCION", "FECHA"),
    ("ACCION", "ACC"),
    ("CODIGO", "COO_FINAL_GIO"),
    ("OBSERVACION", "OBS"),
    ("nis_rad", "NIS"),
)


def aplicar_reglas_provisionales(
    configuracion: ConfiguracionProcesamiento,
) -> None:
    """Completa únicamente contratos de exportación, nunca reglas de negocio."""
    configuracion.modo_reglas_provisionales = False

    contratos = (
        ("contrato_cierres_sistema", "CIERRES_SISTEMA", COLUMNAS_SISTEMA, False),
        ("contrato_entregable_cierres", "ENTREGABLE_CIERRES", COLUMNAS_ENTREGABLE, True),
        ("contrato_reaperturas_sistema", "REAPERTURAS_SISTEMA", COLUMNAS_SISTEMA, False),
        ("contrato_entregable_reaperturas", "ENTREGABLE_REAPERTURAS", COLUMNAS_ENTREGABLE, True),
    )
    for atributo, nombre, columnas, encabezado in contratos:
        actual = getattr(configuracion, atributo)
        if actual.confirmado and actual.columnas:
            continue
        setattr(configuracion, atributo, ContratoTxt(
            nombre=nombre,
            columnas=columnas,
            confirmado=True,
            incluir_encabezado=encabezado,
            mapeo_columnas=MAPEO_SALIDA,
            provisional=True,
        ))
