# -*- coding: utf-8 -*-
"""Dependencia del entregable actualizado y procesamiento de reaperturas."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Optional, Sequence, Tuple

from .configuracion import ConfiguracionProcesamiento, ReglaAccion
from .modelos import (
    CategoriaResultado,
    EstadoFila,
    ProcesoBloqueadoError,
    RegistroProcesamiento,
    ResultadoRama,
    TablaDatos,
)
from .normalizacion import normalizar_decimal, normalizar_fecha, normalizar_fila, resolver_columnas
from .reglas import validar_longitud_observacion
from .reglas_gio import MatrizReglasGio, evaluar_regla_gio


def validar_entregable_actualizado(
    tabla: Optional[TablaDatos], configuracion: ConfiguracionProcesamiento
) -> Tuple[Dict[str, List[Dict[str, str]]], List[str]]:
    if tabla is None:
        raise ProcesoBloqueadoError(
            "REAPERTURAS BLOQUEADAS: cargue el entregable actualizado de cierres."
        )
    columnas = resolver_columnas(tabla.encabezados, configuracion)
    faltantes = [campo for campo in ("NIS", "FECHA", "ACC", "LECT") if campo not in columnas]
    if faltantes:
        raise ProcesoBloqueadoError(
            "REAPERTURAS BLOQUEADAS: el entregable actualizado no contiene "
            + ", ".join(faltantes)
            + "."
        )
    por_nis: Dict[str, List[Dict[str, str]]] = defaultdict(list)
    advertencias: List[str] = []
    for numero, fila in enumerate(tabla.filas, 2):
        datos = normalizar_fila(fila, columnas)
        nis = datos.get("NIS", "")
        if not nis:
            advertencias.append(f"Fila {numero}: NIS vacío; no puede asociarse a una reapertura.")
            continue
        por_nis[nis].append(datos)
    return dict(por_nis), advertencias


def _seleccionar_cierre_reciente(
    registro: RegistroProcesamiento,
    candidatos: Sequence[Dict[str, str]],
    configuracion: ConfiguracionProcesamiento,
) -> Tuple[Optional[Dict[str, str]], Optional[ReglaAccion]]:
    efectivos: List[Tuple[datetime, Dict[str, str], ReglaAccion]] = []
    for candidato in candidatos:
        accion = candidato.get("ACC", "")
        if accion.startswith("6"):
            continue
        reglas = configuracion.reglas_por_accion_cierre(accion)
        equivalencias = {regla.acciones_reapertura for regla in reglas}
        if not reglas or len(equivalencias) != 1:
            continue
        try:
            fecha = datetime.strptime(normalizar_fecha(candidato.get("FECHA", "")), "%Y-%m-%d")
        except ValueError:
            continue
        efectivos.append((fecha, candidato, reglas[0]))

    if not efectivos:
        registro.registrar(
            "REA-07", "SELECCION_CIERRE", CategoriaResultado.REVISION_MANUAL,
            "CIERRE_EFECTIVO_NO_CONFIGURADO", registro.nis,
            "Cierre con fecha y equivalencia aprobada",
        )
        return None, None
    efectivos.sort(key=lambda elemento: elemento[0], reverse=True)
    fecha_maxima = efectivos[0][0]
    empatados = [elemento for elemento in efectivos if elemento[0] == fecha_maxima]
    if len(empatados) != 1:
        registro.registrar(
            "REA-06", "SELECCION_CIERRE", CategoriaResultado.REVISION_MANUAL,
            "CIERRE_MAS_RECIENTE_AMBIGUO", fecha_maxima.date().isoformat(),
            "Regla de desempate confirmada",
        )
        return None, None
    _, cierre, regla = efectivos[0]
    if regla.provisional:
        registro.datos_normalizados["REGLA_PROVISIONAL"] = "SI"
        registro.datos_normalizados["FUENTE_REGLA"] = regla.fuente
        registro.registrar(
            "CFG-PROV-02", "VALIDACION_EQUIVALENCIA", CategoriaResultado.CONTINUA,
            "La equivalencia cierre–reapertura proviene de evidencia provisional.",
            cierre.get("ACC", ""), ",".join(regla.acciones_reapertura),
        )
    return cierre, regla


def procesar_reaperturas(
    registros: List[RegistroProcesamiento],
    tabla_entregable_actualizado: Optional[TablaDatos],
    *,
    configuracion: Optional[ConfiguracionProcesamiento] = None,
    matriz_gio: Optional[MatrizReglasGio] = None,
) -> ResultadoRama:
    configuracion = configuracion or ConfiguracionProcesamiento.predeterminada()
    por_nis, advertencias = validar_entregable_actualizado(tabla_entregable_actualizado, configuracion)
    entradas = [registro for registro in registros if registro.tipo in configuracion.tipos_reapertura]
    listas: List[RegistroProcesamiento] = []
    revisiones: List[RegistroProcesamiento] = []
    exclusiones: List[RegistroProcesamiento] = []
    bloqueos = list(advertencias)
    if matriz_gio is None and not configuracion.reglas_accion:
        bloqueos.append("No existe una matriz aprobada de equivalencias cierre–reapertura.")

    for registro in entradas:
        if matriz_gio is not None:
            regla_gio = evaluar_regla_gio(registro, matriz_gio)
            if regla_gio is None or regla_gio.resultado in {"REVISION", "ERROR"}:
                revisiones.append(registro)
                continue
            if regla_gio.resultado == "VALIDO_NO_EFECTIVO":
                registro.registrar(
                    regla_gio.id_regla, "VALIDACION_REGLAS_GIO",
                    CategoriaResultado.EXCLUSION_OPERATIVA,
                    regla_gio.motivo,
                    registro.datos_normalizados.get("NCOD_CAUSA_ORIGINAL", ""),
                    "Acción no efectiva: no exportar como reapertura",
                )
                exclusiones.append(registro)
                continue
        if configuracion.modo_reglas_provisionales:
            registro.datos_normalizados["REGLA_PROVISIONAL"] = "SI"
            registro.registrar(
                "CFG-PROV-02", "VALIDACION_EQUIVALENCIA", CategoriaResultado.CONTINUA,
                "La reapertura depende de equivalencias provisionales centralizadas.",
                registro.datos_normalizados.get("ACC", ""), "Matriz oficial pendiente",
            )
        candidatos = por_nis.get(registro.nis, [])
        if not candidatos:
            registro.registrar(
                "REA-05", "SELECCION_CIERRE", CategoriaResultado.REVISION_MANUAL,
                "CIERRE_NO_ENCONTRADO_PARA_NIS", registro.nis, "Cierre actualizado",
            )
            revisiones.append(registro)
            continue
        cierre, regla = _seleccionar_cierre_reciente(registro, candidatos, configuracion)
        if cierre is None or regla is None:
            revisiones.append(registro)
            continue

        accion_reapertura = registro.datos_normalizados.get("ACC", "")
        if accion_reapertura not in regla.acciones_reapertura:
            registro.registrar(
                "REA-08", "VALIDACION_EQUIVALENCIA", CategoriaResultado.REVISION_MANUAL,
                "ACCION_INVALIDA", accion_reapertura,
                ",".join(regla.acciones_reapertura) or "Equivalencia aprobada",
            )
            revisiones.append(registro)
            continue
        try:
            ejecutada = normalizar_decimal(registro.datos_normalizados.get("LECT", ""))
            lectura_cierre = normalizar_decimal(cierre.get("LECT", ""))
        except ValueError:
            ejecutada = lectura_cierre = None
        if ejecutada is None or lectura_cierre is None:
            registro.registrar(
                "REA-08", "LECTURA_REAPERTURA", CategoriaResultado.REVISION_MANUAL,
                "LECTURA_REAPERTURA_INVALIDA",
                f"Ejecutada={registro.datos_normalizados.get('LECT', '')}; Cierre={cierre.get('LECT', '')}",
                "Lecturas numéricas",
            )
            revisiones.append(registro)
            continue
        diferencia = ejecutada - lectura_cierre
        registro.datos_normalizados["ACCION_CIERRE"] = cierre.get("ACC", "")
        registro.datos_normalizados["LECTURA_CIERRE"] = str(lectura_cierre)
        registro.datos_normalizados["DIFERENCIA"] = str(diferencia)
        if diferencia < 0 or diferencia > configuracion.limite_diferencia_reapertura:
            registro.registrar(
                "REA-07", "LECTURA_REAPERTURA", CategoriaResultado.REVISION_MANUAL,
                "REVISAR_LECTURA", diferencia, f"0 a {configuracion.limite_diferencia_reapertura}",
            )
            revisiones.append(registro)
            continue
        if not validar_longitud_observacion(registro, configuracion):
            revisiones.append(registro)
            continue
        registro.marcar_continua(
            EstadoFila.REAPERTURA_LISTA, "REA-06", "REAPERTURAS_LISTAS",
            "Reapertura lista para exportación.",
        )
        listas.append(registro)

    return ResultadoRama(
        nombre="REAPERTURAS", entradas=entradas, listas=listas,
        revisiones=revisiones, exclusiones=exclusiones, bloqueos=bloqueos,
    )
