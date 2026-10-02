# -*- coding: utf-8 -*-
"""Reglas de negocio configurables, sin dependencias de interfaz."""

from __future__ import annotations

import re
from typing import Optional

from .configuracion import ConfiguracionProcesamiento, ReglaAccion
from .modelos import CategoriaResultado, RegistroProcesamiento
from .normalizacion import hora_a_minutos


PATRON_HORAS_OBS = re.compile(
    r"HI\s*:\s*\d{1,2}(?:[:.]\d{1,2})?\s*HF\s*:\s*\d{1,2}(?:[:.]\d{1,2})?",
    re.IGNORECASE,
)


def seleccionar_regla_accion(
    registro: RegistroProcesamiento,
    configuracion: ConfiguracionProcesamiento,
) -> Optional[ReglaAccion]:
    if configuracion.modo_reglas_provisionales:
        registro.datos_normalizados["REGLA_PROVISIONAL"] = "SI"
        registro.registrar(
            "CFG-PROV-01", "VALIDACION_ACCION", CategoriaResultado.CONTINUA,
            "La validación usa una matriz provisional centralizada.",
            registro.datos_normalizados.get("ACC", ""), "Matriz oficial pendiente",
        )
    candidatas = configuracion.reglas_para_registro(registro.datos_normalizados)
    if not candidatas:
        registro.registrar(
            "ACC-05", "VALIDACION_ACCION", CategoriaResultado.REVISION_MANUAL,
            "ACCION_SIN_REGLA_CONFIGURADA",
            registro.datos_normalizados.get("ACC", ""),
            ",".join(sorted({
                regla.accion_ejecutada for regla in configuracion.reglas_accion
                if regla.tipo.upper() == registro.tipo
            })) or "Matriz de acciones aprobada",
        )
        return None
    if len(candidatas) > 1:
        registro.registrar(
            "ACC-06", "VALIDACION_ACCION", CategoriaResultado.REVISION_MANUAL,
            "ACCION_CON_REGLAS_AMBIGUAS",
            registro.datos_normalizados.get("ACC", ""),
            ",".join(regla.id_regla for regla in candidatas),
        )
        return None
    regla = candidatas[0]
    if regla.provisional:
        registro.datos_normalizados["REGLA_PROVISIONAL"] = "SI"
        registro.datos_normalizados["FUENTE_REGLA"] = regla.fuente
    registro.registrar(
        regla.id_regla, "VALIDACION_ACCION", CategoriaResultado.CONTINUA,
        "La acción coincide con una regla configurada.",
        registro.datos_normalizados.get("ACC", ""), regla.accion_ejecutada,
    )
    return regla


def validar_longitud_observacion(
    registro: RegistroProcesamiento,
    configuracion: ConfiguracionProcesamiento,
) -> bool:
    observacion = registro.datos_normalizados.get("OBS", "")
    if len(observacion) <= configuracion.limite_obs:
        registro.registrar(
            "OBS-01", "VALIDACION_OBS", CategoriaResultado.CONTINUA,
            "La observación cumple el límite permitido.", len(observacion), configuracion.limite_obs,
        )
        return True
    registro.registrar(
        "OBS-01", "VALIDACION_OBS", CategoriaResultado.REVISION_MANUAL,
        "OBS_EXCEDE_150_CARACTERES", len(observacion), configuracion.limite_obs,
    )
    return False


def corregir_horario_tipo_c(registro: RegistroProcesamiento) -> bool:
    """Corrige solo tipo C; un formato ambiguo se conserva para revisión."""
    if registro.tipo != "C":
        registro.registrar(
            "HOR-03", "CORRECCION_HORARIO", CategoriaResultado.CONTINUA,
            "La corrección horaria no aplica a este tipo.", registro.tipo, "C",
        )
        return True
    hi = registro.datos_normalizados.get("HI", "")
    hf = registro.datos_normalizados.get("HF", "")
    try:
        minutos_hi = hora_a_minutos(hi)
        minutos_hf = hora_a_minutos(hf)
    except ValueError as error:
        registro.registrar(
            "HOR-04", "CORRECCION_HORARIO", CategoriaResultado.REVISION_MANUAL,
            "HORARIO_AMBIGUO_O_INVALIDO", f"HI={hi}; HF={hf}", str(error),
        )
        return False
    if minutos_hi < 14 * 60 and minutos_hf < 14 * 60:
        registro.registrar(
            "HOR-01", "CORRECCION_HORARIO", CategoriaResultado.CONTINUA,
            "El horario de tipo C no requiere corrección.", f"HI={hi}; HF={hf}", "Ambas antes de 14:00",
        )
        return True

    observacion = registro.datos_normalizados.get("OBS", "")
    if not PATRON_HORAS_OBS.search(observacion):
        registro.registrar(
            "HOR-04", "CORRECCION_HORARIO", CategoriaResultado.REVISION_MANUAL,
            "OBS_SIN_PATRON_HI_HF", observacion, "Fragmento HI: HH:MM HF: HH:MM",
        )
        return False
    registro.datos_normalizados["HI_ORIGINAL"] = hi
    registro.datos_normalizados["HF_ORIGINAL"] = hf
    registro.datos_normalizados["OBS_ORIGINAL"] = observacion
    registro.datos_normalizados["HI"] = "12:00"
    registro.datos_normalizados["HF"] = "12:00"
    registro.datos_normalizados["OBS"] = PATRON_HORAS_OBS.sub(
        "HI: 12:00 HF: 12:00", observacion, count=1
    )
    registro.registrar(
        "HOR-02", "CORRECCION_HORARIO", CategoriaResultado.CONTINUA,
        "Horario tipo C corregido preservando el resto de OBS.",
        f"HI={hi}; HF={hf}", "HI=12:00; HF=12:00",
    )
    return True
