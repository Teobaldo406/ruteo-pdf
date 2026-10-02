# -*- coding: utf-8 -*-
"""Procesamiento de la rama de cierres y revisiones."""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from typing import Dict, List, Optional, Union

from .configuracion import ConfiguracionProcesamiento
from .modelos import (
    CategoriaResultado,
    EstadoFila,
    RegistroProcesamiento,
    ResultadoRama,
    TablaDatos,
)
from .normalizacion import normalizar_decimal, normalizar_identificador, resolver_columnas
from .reglas import corregir_horario_tipo_c, seleccionar_regla_accion, validar_longitud_observacion
from .reglas_gio import MatrizReglasGio, evaluar_regla_gio


def _registrar_condicion_niple(registro: RegistroProcesamiento) -> None:
    """Conserva la fila cuando el cruce de lectura produce #N/D."""
    registro.datos_normalizados.update({
        "LECTURA_TOMA": "#N/D",
        "DIFERENCIA": "",
        "VALIDACION_LECTURA": "NO_APLICA_POR_NIPLE",
        "MOTIVO_LECTURA": "SIN_LECTURA_ANTERIOR_POR_CONDICION_NIPLE",
        "RESULTADO_LECTURA": "CONTINUAR",
    })
    registro.registrar(
        "CIE-NIPLE", "LECTURA_CIERRE", CategoriaResultado.CONTINUA,
        "SIN_LECTURA_ANTERIOR_POR_CONDICION_NIPLE",
        "#N/D", "Continuar sin calcular diferencia",
    )


def _indice_lecturas(
    tabla: Optional[TablaDatos], configuracion: ConfiguracionProcesamiento
) -> Dict[str, List[Union[Decimal, str]]]:
    if tabla is None:
        return {}
    columnas = resolver_columnas(tabla.encabezados, configuracion)
    columna_nis = columnas.get("NIS")
    columna_lectura = columnas.get("LECTURA_TOMA") or columnas.get("LECT")
    if not columna_nis or not columna_lectura:
        return {}
    indice: Dict[str, List[Union[Decimal, str]]] = defaultdict(list)
    for fila in tabla.filas:
        nis = normalizar_identificador(fila.get(columna_nis, ""))
        valor_crudo = str(fila.get(columna_lectura, "") or "").strip()
        if valor_crudo.upper() == "#N/D":
            if nis:
                indice[nis].append("#N/D")
            continue
        try:
            lectura = normalizar_decimal(valor_crudo)
        except ValueError:
            continue
        if nis and lectura is not None:
            indice[nis].append(lectura)
    return dict(indice)


def procesar_cierres(
    registros: List[RegistroProcesamiento],
    *,
    configuracion: Optional[ConfiguracionProcesamiento] = None,
    tabla_lecturas: Optional[TablaDatos] = None,
    matriz_gio: Optional[MatrizReglasGio] = None,
) -> ResultadoRama:
    configuracion = configuracion or ConfiguracionProcesamiento.predeterminada()
    entradas = [registro for registro in registros if registro.tipo in configuracion.tipos_cierre]
    lecturas = _indice_lecturas(tabla_lecturas, configuracion)
    listas: List[RegistroProcesamiento] = []
    revisiones: List[RegistroProcesamiento] = []
    exclusiones: List[RegistroProcesamiento] = []
    bloqueos: List[str] = []
    if matriz_gio is None and not configuracion.reglas_accion:
        bloqueos.append("No existe una matriz de acciones aprobada; las filas quedan en revisión manual.")

    for registro in entradas:
        if matriz_gio is not None:
            regla_gio = evaluar_regla_gio(registro, matriz_gio)
            if regla_gio is None or regla_gio.resultado in {"REVISION", "ERROR"}:
                revisiones.append(registro)
                continue
            if regla_gio.resultado == "VALIDO_NO_EFECTIVO":
                aplica_lectura = False
            else:
                # Una regla activa aprobada permite continuar. La necesidad de
                # validar lectura depende después del ACC real recibido (506–529),
                # nunca de un código reemplazado ni de una lista fija en Python.
                aplica_lectura = True
        else:
            regla = seleccionar_regla_accion(registro, configuracion)
            if regla is None:
                revisiones.append(registro)
                continue
            aplica_lectura = regla.aplica_lectura
        try:
            numero_accion = int(registro.datos_normalizados.get("ACC", ""))
        except (TypeError, ValueError):
            numero_accion = -1
        aplica_lectura = aplica_lectura and 506 <= numero_accion <= 529
        if not corregir_horario_tipo_c(registro):
            revisiones.append(registro)
            continue
        if not validar_longitud_observacion(registro, configuracion):
            revisiones.append(registro)
            continue

        if aplica_lectura:
            nis = registro.nis
            candidatas = lecturas.get(nis, [])
            if not nis:
                registro.registrar(
                    "CIE-08", "LECTURA_CIERRE", CategoriaResultado.REVISION_MANUAL,
                    "NIS_VACIO_PARA_CRUCE_LECTURA", nis, "NIS informado",
                )
                revisiones.append(registro)
                continue
            if not candidatas:
                # Es el equivalente del #N/D que devuelve el cruce manual:
                # existe NIS, pero no hay lectura anterior utilizable.
                _registrar_condicion_niple(registro)
            elif len(candidatas) != 1:
                registro.registrar(
                    "CIE-08", "LECTURA_CIERRE", CategoriaResultado.REVISION_MANUAL,
                    "LECTURA_TOMA_DUPLICADA", nis, "Una lectura por NIS",
                )
                revisiones.append(registro)
                continue
            elif candidatas[0] == "#N/D":
                _registrar_condicion_niple(registro)
            else:
                try:
                    ejecutada = normalizar_decimal(registro.datos_normalizados.get("LECT", ""))
                except ValueError:
                    ejecutada = None
                if ejecutada is None:
                    registro.registrar(
                        "CIE-08", "LECTURA_CIERRE", CategoriaResultado.REVISION_MANUAL,
                        "LECTURA_EJECUTADA_INVALIDA", registro.datos_normalizados.get("LECT", ""), "Número",
                    )
                    revisiones.append(registro)
                    continue
                diferencia = ejecutada - candidatas[0]
                registro.datos_normalizados.update({
                    "LECTURA_TOMA": str(candidatas[0]),
                    "DIFERENCIA": str(diferencia),
                    "VALIDACION_LECTURA": "DIFERENCIA_NUMERICA",
                })
                if diferencia < 0:
                    registro.datos_normalizados.update({
                        "MOTIVO_LECTURA": "LECTURA_NEGATIVA",
                        "RESULTADO_LECTURA": "REVISION",
                    })
                    registro.registrar(
                        "CIE-02", "LECTURA_CIERRE", CategoriaResultado.REVISION_MANUAL,
                        "LECTURA_NEGATIVA", diferencia, "0 a 300",
                    )
                    revisiones.append(registro)
                    continue
                if diferencia > configuracion.limite_diferencia_cierre:
                    registro.datos_normalizados.update({
                        "MOTIVO_LECTURA": "DIFERENCIA_MAYOR_300",
                        "RESULTADO_LECTURA": "REVISION",
                    })
                    registro.registrar(
                        "CIE-05", "LECTURA_CIERRE", CategoriaResultado.REVISION_MANUAL,
                        "DIFERENCIA_MAYOR_300", diferencia,
                        f"0 a {configuracion.limite_diferencia_cierre}",
                    )
                    revisiones.append(registro)
                    continue
                registro.datos_normalizados.update({
                    "MOTIVO_LECTURA": "DIFERENCIA_EN_RANGO",
                    "RESULTADO_LECTURA": "CONTINUAR",
                })
                registro.registrar(
                    "CIE-03", "LECTURA_CIERRE", CategoriaResultado.CONTINUA,
                    "La diferencia de cierre está dentro del rango permitido.",
                    diferencia, f"0 a {configuracion.limite_diferencia_cierre}",
                )

        registro.marcar_continua(
            EstadoFila.CIERRE_LISTO, "CIE-09", "CIERRES_LISTOS",
            "Cierre listo para exportación.",
        )
        listas.append(registro)

    return ResultadoRama(
        nombre="CIERRES", entradas=entradas, listas=listas, revisiones=revisiones,
        exclusiones=exclusiones, bloqueos=bloqueos,
    )
