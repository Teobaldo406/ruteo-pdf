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
    limite: Optional[int] = None,
) -> bool:
    limite_aplicable = configuracion.limite_obs if limite is None else limite
    observacion = registro.datos_normalizados.get("OBS", "")
    if len(observacion) <= limite_aplicable:
        registro.registrar(
            "OBS-01", "VALIDACION_OBS", CategoriaResultado.CONTINUA,
            "La observación cumple el límite permitido.", len(observacion), limite_aplicable,
        )
        return True
    registro.registrar(
        "OBS-01", "VALIDACION_OBS", CategoriaResultado.REVISION_MANUAL,
        f"OBS_EXCEDE_{limite_aplicable}_CARACTERES", len(observacion), limite_aplicable,
    )
    return False


def corregir_horario_tipo_c(registro: RegistroProcesamiento) -> bool:
    """Corrige solo tipo C; un formato ambiguo se conserva para revisión."""
    datos = registro.datos_normalizados
    hi = datos.get("HI", "")
    hf = datos.get("HF", "")
    hi_original = datos.get("HI_ORIGINAL", hi)
    hf_original = datos.get("HF_ORIGINAL", hf)
    datos["HI_FINAL"] = hi_original
    datos["HF_FINAL"] = hf_original
    if registro.tipo != "C":
        datos["MOTIVO_CORRECCION_HORA"] = "NO_APLICA_TIPO_DISTINTO_C"
        registro.registrar(
            "HOR-03", "CORRECCION_HORARIO", CategoriaResultado.CONTINUA,
            "La corrección horaria no aplica a este tipo.", registro.tipo, "C",
        )
        return True
    try:
        minutos_hi = hora_a_minutos(hi)
        minutos_hf = hora_a_minutos(hf)
    except ValueError as error:
        datos["MOTIVO_CORRECCION_HORA"] = "HORARIO_AMBIGUO_O_INVALIDO"
        registro.registrar(
            "HOR-04", "CORRECCION_HORARIO", CategoriaResultado.REVISION_MANUAL,
            "HORARIO_AMBIGUO_O_INVALIDO", f"HI={hi}; HF={hf}", str(error),
        )
        return False
    if minutos_hi < 14 * 60 and minutos_hf < 14 * 60:
        datos["MOTIVO_CORRECCION_HORA"] = "NO_REQUIERE_CORRECCION_ANTES_DE_14_00"
        registro.registrar(
            "HOR-01", "CORRECCION_HORARIO", CategoriaResultado.CONTINUA,
            "El horario de tipo C no requiere corrección.", f"HI={hi}; HF={hf}", "Ambas antes de 14:00",
        )
        return True

    observacion = registro.datos_normalizados.get("OBS", "")
    if not PATRON_HORAS_OBS.search(observacion):
        datos["MOTIVO_CORRECCION_HORA"] = "OBS_SIN_PATRON_HI_HF"
        registro.registrar(
            "HOR-04", "CORRECCION_HORARIO", CategoriaResultado.REVISION_MANUAL,
            "OBS_SIN_PATRON_HI_HF", observacion, "Fragmento HI: HH:MM HF: HH:MM",
        )
        return False
    datos["OBS_ORIGINAL"] = observacion
    datos["HI"] = "12"
    datos["HF"] = "12"
    datos["HI_FINAL"] = "12"
    datos["HF_FINAL"] = "12"
    datos["HI_NORMALIZADA"] = "12:00"
    datos["HF_NORMALIZADA"] = "12:00"
    datos["MOTIVO_CORRECCION_HORA"] = "TIPO_C_HORA_IGUAL_O_SUPERIOR_14_00"
    datos["OBS"] = PATRON_HORAS_OBS.sub(
        "HI: 12:00 HF: 12:00", observacion, count=1
    )
    registro.registrar(
        "HOR-02", "CORRECCION_HORARIO", CategoriaResultado.CONTINUA,
        "Horario tipo C corregido preservando el resto de OBS.",
        f"HI={hi}; HF={hf}", "HI=12; HF=12; OBS HI/HF=12:00",
    )
    return True
