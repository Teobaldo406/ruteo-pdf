# -*- coding: utf-8 -*-
"""Dependencia del entregable actualizado y procesamiento de reaperturas."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Callable, Dict, List, Optional, Tuple

from .configuracion import ConfiguracionProcesamiento
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
from .reglas_gio import (
    MatrizReglasGio, ReglaTipologia, normalizar_accion_gio, normalizar_texto_gio,
)


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
    filas_ordenables: List[tuple[datetime, int, Dict[str, str]]] = []
    advertencias: List[str] = []
    for numero, fila in enumerate(tabla.filas, 2):
        datos = normalizar_fila(fila, columnas)
        nis = datos.get("NIS", "")
        if not nis:
            advertencias.append(f"Fila {numero}: NIS vacío; no puede asociarse a una reapertura.")
            continue
        marca = _marca_temporal(datos)
        if marca is None:
            advertencias.append(
                f"Fila {numero}: fecha inválida; no puede ordenarse como antecedente."
            )
            continue
        filas_ordenables.append((marca, numero, datos))
    # Orden global previo al cruce. El ordenamiento es estable: si dos filas
    # tienen la misma FECHA, conserva su posición física en el entregable.
    filas_ordenables.sort(key=lambda item: item[0], reverse=True)
    por_nis: Dict[str, List[Dict[str, str]]] = defaultdict(list)
    for _marca, _numero, datos in filas_ordenables:
        por_nis[datos["NIS"]].append(datos)
    return dict(por_nis), advertencias


def _marca_temporal(datos: Dict[str, str]) -> Optional[datetime]:
    """Devuelve la fecha operativa sin usar HI/HF para desempatar antecedentes."""
    try:
        fecha = normalizar_fecha(datos.get("FECHA", ""))
        return datetime.strptime(fecha, "%Y-%m-%d")
    except (ValueError, TypeError):
        return None


def _indice_tipos_anteriores(
    registros: Optional[List[RegistroProcesamiento]],
) -> Dict[tuple[str, str, str, str], set[str]]:
    indice: Dict[tuple[str, str, str, str], set[str]] = defaultdict(set)
    for registro in registros or []:
        if not registro.tipo:
            continue
        accion = normalizar_accion_gio(registro.datos_normalizados.get("ACC", ""))
        clave = (registro.nis, registro.ot, registro.os, accion)
        indice[clave].add(registro.tipo)
    return indice


def _resolver_tipo_anterior(
    cierre: Dict[str, str],
    indice_tipos: Dict[tuple[str, str, str, str], set[str]],
    matriz_gio: MatrizReglasGio,
) -> str:
    tipo = str(cierre.get("TIPO", "") or "").strip().upper()
    if tipo:
        return tipo
    accion = normalizar_accion_gio(cierre.get("ACC", ""))
    clave = (cierre.get("NIS", ""), cierre.get("OT", ""), cierre.get("OS", ""), accion)
    tipos = indice_tipos.get(clave, set())
    if len(tipos) == 1:
        return next(iter(tipos))
    if matriz_gio.tipologias:
        tipos_matriz = matriz_gio.tipologias.tipos_activos_para_accion(accion)
        if len(tipos_matriz) == 1:
            return tipos_matriz[0]
    return ""


def _consultar_tipologia(
    tipo: str, accion: str, matriz_gio: MatrizReglasGio
) -> tuple[Optional[ReglaTipologia], str]:
    coincidencias = matriz_gio.tipologias.buscar(tipo, accion) if matriz_gio.tipologias else ()
    if not coincidencias:
        return None, "TIPO_ACC_NO_CONFIGURADO"
    activas = [regla for regla in coincidencias if regla.activa]
    if not activas:
        return None, "REGLA_TIPOLOGICA_INACTIVA"
    if len(activas) != 1:
        return None, "CIERRE_ANTERIOR_AMBIGUO"
    return activas[0], ""


def _cierre_anterior_es_efectivo(
    accion: str,
    regla_tipologica: Optional[ReglaTipologia],
    matriz_gio: MatrizReglasGio,
) -> bool:
    """Comprueba efectividad usando solamente reglas activas de la matriz."""
    if regla_tipologica is not None:
        resultado = normalizar_texto_gio(regla_tipologica.resultado)
        if regla_tipologica.cierre_efectivo or resultado in {
            "CIERRE_VALIDO", "REVISION_CONFIRMA_CIERRE",
        }:
            return True
        if resultado == "NO_EFECTIVO":
            return False
    accion_normalizada = normalizar_accion_gio(accion)
    for regla in matriz_gio.reglas_activas:
        if normalizar_texto_gio(regla.resultado) != "VALIDO_EFECTIVO":
            continue
        if regla.condicion_acc == "LISTA" and accion_normalizada in regla.acc_lista:
            return True
        if regla.condicion_acc != "RANGO":
            continue
        try:
            numero = Decimal(accion_normalizada)
        except InvalidOperation:
            continue
        if (
            regla.acc_min is not None and regla.acc_max is not None
            and regla.acc_min <= numero <= regla.acc_max
        ):
            return True
    return False


def _enviar_revision(
    registro: RegistroProcesamiento,
    regla: str,
    motivo_tecnico: str,
    motivo_usuario: str,
    recibido: object = "",
    esperado: object = "",
) -> None:
    registro.datos_normalizados["MOTIVO_REVISION_MANUAL"] = motivo_usuario
    registro.registrar(
        regla, "REAPERTURAS", CategoriaResultado.REVISION_MANUAL,
        motivo_tecnico, recibido, esperado,
    )


def procesar_reaperturas(
    registros: List[RegistroProcesamiento],
    tabla_entregable_actualizado: Optional[TablaDatos],
    *,
    configuracion: Optional[ConfiguracionProcesamiento] = None,
    matriz_gio: Optional[MatrizReglasGio] = None,
    considerar_entregable_actualizado: bool = True,
    progreso: Optional[Callable[[str, int, int], None]] = None,
    registros_anteriores: Optional[List[RegistroProcesamiento]] = None,
) -> ResultadoRama:
    configuracion = configuracion or ConfiguracionProcesamiento.predeterminada()
    if matriz_gio is None or matriz_gio.tipologias is None:
        raise ProcesoBloqueadoError(
            "REAPERTURAS BLOQUEADAS: falta la hoja MATRIZ_TIPOLOGIAS en la matriz de reglas."
        )
    if considerar_entregable_actualizado:
        por_nis, advertencias = validar_entregable_actualizado(
            tabla_entregable_actualizado, configuracion
        )
    else:
        por_nis, advertencias = {}, [
            "Validación contra entregable actualizado omitida por decisión del usuario."
        ]
    entradas = [registro for registro in registros if registro.tipo in configuracion.tipos_reapertura]
    listas: List[RegistroProcesamiento] = []
    revisiones: List[RegistroProcesamiento] = []
    exclusiones: List[RegistroProcesamiento] = []
    bloqueos = list(advertencias)
    indice_tipos = _indice_tipos_anteriores(registros_anteriores)
    total = max(1, len(entradas))
    for indice, registro in enumerate(entradas, 1):
        if progreso:
            progreso("Cruzando reaperturas por NIS_RAD", indice, total)
        registro.datos_normalizados["ENTREGABLE_ACTUALIZADO_CONSIDERADO"] = (
            "SI" if considerar_entregable_actualizado else "NO"
        )
        registro.datos_normalizados["VALIDACION_ENTREGABLE_ACTUALIZADO"] = (
            "EJECUTADA" if considerar_entregable_actualizado
            else "OMITIDA_POR_DECISION_USUARIO"
        )
        if not considerar_entregable_actualizado:
            registro.registrar(
                "REA-OMIT-01", "ENTREGABLE_ACTUALIZADO",
                CategoriaResultado.CONTINUA,
                "VALIDACION_OMITIDA_POR_DECISION_USUARIO",
                "NO UTILIZADO", "Cruce contra cierre actualizado",
            )
            if not validar_longitud_observacion(
                registro, configuracion, configuracion.limite_obs_reapertura
            ):
                revisiones.append(registro)
                continue
            registro.marcar_continua(
                EstadoFila.REAPERTURA_LISTA, "REA-OMIT-01", "REAPERTURAS_LISTAS",
                "Reapertura lista sin cruce de entregable por decisión del usuario.",
            )
            listas.append(registro)
            continue
        marca_reapertura = _marca_temporal(registro.datos_normalizados)
        candidatos_previos = []
        for orden_origen, candidato in enumerate(por_nis.get(registro.nis, [])):
            marca_cierre = _marca_temporal(candidato)
            if marca_cierre is None or marca_reapertura is None or marca_cierre > marca_reapertura:
                continue
            tipo_anterior = _resolver_tipo_anterior(candidato, indice_tipos, matriz_gio)
            candidatos_previos.append(
                (marca_cierre, orden_origen, candidato, tipo_anterior)
            )
        if not candidatos_previos:
            _enviar_revision(
                registro, "REA-01", "CIERRE_ANTERIOR_NO_ENCONTRADO",
                "CIERRE_ANTERIOR_NO_ENCONTRADO", registro.nis,
                "Registro anterior a la reapertura",
            )
            revisiones.append(registro)
            continue
        # El cruce toma estrictamente la primera coincidencia después del orden
        # global por FECHA descendente. No busca una fila más antigua solo
        # porque esta tenga una regla tipológica configurada.
        _, _, cierre, tipo_anterior = candidatos_previos[0]
        accion_cierre_original = cierre.get("ACC", "")
        accion_cierre = normalizar_accion_gio(accion_cierre_original)
        lectura_cierre_cruda = cierre.get("LECT", "")
        accion_reapertura = registro.datos_normalizados.get("ACC", "")
        accion_reapertura_normalizada = normalizar_accion_gio(accion_reapertura)
        registro.datos_normalizados["TIPO_CIERRE_ANTERIOR"] = tipo_anterior
        registro.datos_normalizados["ACCION_CIERRE_ANTERIOR_ORIGINAL"] = (
            accion_cierre_original
        )
        registro.datos_normalizados["ACCION_CIERRE_ANTERIOR"] = accion_cierre
        registro.datos_normalizados["ACCION_REAPERTURA_ORIGINAL"] = accion_reapertura
        registro.datos_normalizados["ACCION_REAPERTURA_VALIDADA"] = (
            accion_reapertura_normalizada
        )
        registro.datos_normalizados["CLAVE_MATRIZ_TIPOLOGIAS"] = (
            f"{tipo_anterior}|{accion_cierre}"
        )
        registro.datos_normalizados["LECTURA_CIERRE_ANTERIOR"] = lectura_cierre_cruda
        # Alias internos conservados para contratos y auditorías ya existentes.
        registro.datos_normalizados["ACCION_CIERRE"] = accion_cierre
        registro.datos_normalizados["LECTURA_CIERRE"] = lectura_cierre_cruda
        try:
            lectura_actual_auditoria = normalizar_decimal(
                registro.datos_normalizados.get("LECT", "")
            )
            lectura_cierre_auditoria = normalizar_decimal(lectura_cierre_cruda)
        except ValueError:
            lectura_actual_auditoria = lectura_cierre_auditoria = None
        if lectura_actual_auditoria is not None and lectura_cierre_auditoria is not None:
            registro.datos_normalizados["DIFERENCIA"] = str(
                lectura_actual_auditoria - lectura_cierre_auditoria
            )
        regla_tipologica, motivo_tipologia = _consultar_tipologia(
            tipo_anterior, accion_cierre, matriz_gio
        )
        if regla_tipologica is not None:
            registro.datos_normalizados["VALOR_MATRIZ_TIPOLOGIAS"] = (
                f"fila={regla_tipologica.numero_fila};TIPO={regla_tipologica.tipo};"
                f"ACC={regla_tipologica.accion};"
                f"CIERRE_EFECTIVO={regla_tipologica.cierre_efectivo};"
                f"REAPERTURA_ESPERADA={regla_tipologica.reapertura_esperada};"
                f"ACTIVO={'SI' if regla_tipologica.activa else 'NO'}"
            )
        else:
            registro.datos_normalizados["VALOR_MATRIZ_TIPOLOGIAS"] = "NO_ENCONTRADO"
        regla_accion_actual, _motivo_accion_actual = _consultar_tipologia(
            registro.tipo, accion_reapertura, matriz_gio
        )
        es_imposibilidad = bool(
            regla_accion_actual
            and regla_accion_actual.clasificacion == "IMPOSIBILIDAD_REAPERTURA"
        )
        if es_imposibilidad:
            registro.datos_normalizados["CLASIFICACION_TIPOLOGICA"] = (
                regla_accion_actual.clasificacion
            )
            cierre_efectivo = _cierre_anterior_es_efectivo(
                accion_cierre, regla_tipologica, matriz_gio
            )
            if regla_accion_actual.requiere_cierre_efectivo and not cierre_efectivo:
                _enviar_revision(
                    registro, "REA-IMP-01", "CIERRE_EFECTIVO_NO_DEFINIDO",
                    "CIERRE_EFECTIVO_NO_DEFINIDO", accion_cierre,
                    "Cierre anterior efectivo o confirmado por revisión",
                )
                revisiones.append(registro)
                continue
            if (
                not regla_accion_actual.validar_equivalencia
                and not regla_accion_actual.validar_diferencia
            ):
                registro.datos_normalizados["ID_REGLA_EQUIVALENCIA"] = (
                    f"MATRIZ_TIPOLOGIAS:{regla_accion_actual.numero_fila}"
                )
                registro.datos_normalizados["RESULTADO_TIPOLOGICO"] = (
                    regla_accion_actual.resultado
                )
                registro.datos_normalizados["CONDICION_TIPOLOGICA"] = (
                    regla_accion_actual.condicion
                )
                if not validar_longitud_observacion(
                    registro, configuracion, configuracion.limite_obs_reapertura
                ):
                    registro.datos_normalizados["MOTIVO_REVISION_MANUAL"] = (
                        "Observación mayor de 150 caracteres"
                    )
                    revisiones.append(registro)
                    continue
                registro.marcar_continua(
                    EstadoFila.REAPERTURA_LISTA, "REA-IMP-02", "REAPERTURAS_LISTAS",
                    "Imposibilidad de reapertura aprobada por MATRIZ_TIPOLOGIAS.",
                )
                listas.append(registro)
                continue
        if regla_tipologica is None:
            _enviar_revision(
                registro, "REA-03", motivo_tipologia,
                motivo_tipologia,
                f"{tipo_anterior}/{accion_cierre}",
                "TIPO + ACC activo en MATRIZ_TIPOLOGIAS",
            )
            revisiones.append(registro)
            continue
        registro.datos_normalizados["CIERRE_EFECTIVO"] = regla_tipologica.cierre_efectivo
        registro.datos_normalizados["REAPERTURA_ESPERADA"] = regla_tipologica.reapertura_esperada
        registro.datos_normalizados["RESULTADO_TIPOLOGICO"] = regla_tipologica.resultado
        registro.datos_normalizados["CONDICION_TIPOLOGICA"] = regla_tipologica.condicion
        if not regla_tipologica.cierre_efectivo:
            _enviar_revision(
                registro, "REA-04", "CIERRE_EFECTIVO_NO_DEFINIDO",
                "CIERRE_EFECTIVO_NO_DEFINIDO", f"{tipo_anterior}/{accion_cierre}",
                "CIERRE_EFECTIVO informado",
            )
            revisiones.append(registro)
            continue
        if not regla_tipologica.reapertura_esperada:
            _enviar_revision(
                registro, "REA-05", "REAPERTURA_ESPERADA_NO_DEFINIDA",
                "REAPERTURA_ESPERADA_NO_DEFINIDA", f"{tipo_anterior}/{accion_cierre}",
                "REAPERTURA_ESPERADA informada",
            )
            revisiones.append(registro)
            continue
        if accion_reapertura_normalizada != regla_tipologica.reapertura_esperada:
            _enviar_revision(
                registro, "REA-06", "REAPERTURA_NO_EQUIVALENTE",
                "REAPERTURA_NO_EQUIVALENTE", accion_reapertura,
                regla_tipologica.reapertura_esperada,
            )
            revisiones.append(registro)
            continue
        try:
            ejecutada = normalizar_decimal(registro.datos_normalizados.get("LECT", ""))
            lectura_cierre = normalizar_decimal(lectura_cierre_cruda)
        except ValueError:
            ejecutada = lectura_cierre = None
        if lectura_cierre is None:
            _enviar_revision(
                registro, "REA-07", "LECTURA_ANTERIOR_NO_DISPONIBLE",
                "LECTURA_ANTERIOR_NO_DISPONIBLE", lectura_cierre_cruda, "Lectura numérica",
            )
            revisiones.append(registro)
            continue
        if ejecutada is None:
            _enviar_revision(
                registro, "REA-07", "LECTURA_ANTERIOR_NO_DISPONIBLE",
                "LECTURA_ANTERIOR_NO_DISPONIBLE",
                registro.datos_normalizados.get("LECT", ""), "Lectura numérica",
            )
            revisiones.append(registro)
            continue
        diferencia = ejecutada - lectura_cierre
        registro.datos_normalizados["DIFERENCIA"] = str(diferencia)
        if diferencia < 0:
            _enviar_revision(
                registro, "REA-08", "DIFERENCIA_NEGATIVA",
                "DIFERENCIA_NEGATIVA", diferencia, "0 a 14",
            )
            revisiones.append(registro)
            continue
        if diferencia > configuracion.limite_diferencia_reapertura:
            _enviar_revision(
                registro, "REA-09", "DIFERENCIA_MAYOR_14",
                "DIFERENCIA_MAYOR_14", diferencia,
                f"0 a {configuracion.limite_diferencia_reapertura}",
            )
            revisiones.append(registro)
            continue
        registro.datos_normalizados["ID_REGLA_EQUIVALENCIA"] = (
            f"MATRIZ_TIPOLOGIAS:{regla_tipologica.numero_fila}"
        )
        if not validar_longitud_observacion(
            registro, configuracion, configuracion.limite_obs_reapertura
        ):
            registro.datos_normalizados["MOTIVO_REVISION_MANUAL"] = (
                "Observación mayor de 150 caracteres"
            )
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
