# -*- coding: utf-8 -*-
"""Flujo común: desde el CSV SANSYS hasta DATA_FILTRADA."""

from __future__ import annotations

from collections import Counter, defaultdict
import re
from typing import Dict, List, Optional, Set, Tuple

from .auditoria import resumir_etapa, verificar_conservacion
from .configuracion import ConfiguracionProcesamiento
from .modelos import (
    CategoriaResultado,
    EstadoFila,
    RegistroProcesamiento,
    ResultadoFlujoComun,
    TablaDatos,
)
from .normalizacion import (
    normalizar_decimal,
    normalizar_encabezado,
    normalizar_fecha,
    normalizar_fila,
    normalizar_hora,
    normalizar_identificador,
    resolver_columnas,
)


CAMPOS_BLOQUE_OPERATIVO = ("OT", "OS", "FECHA", "HI", "HF", "ACC", "COO", "OBS", "LECT")


def _crear_registros(
    tabla: TablaDatos,
    configuracion: ConfiguracionProcesamiento,
) -> List[RegistroProcesamiento]:
    columnas = resolver_columnas(tabla.encabezados, configuracion)
    inicio_bloque = _posicion_columna_null(tabla)
    registros: List[RegistroProcesamiento] = []
    desplazamiento = tabla.formato.fila_encabezado + 1 if tabla.formato.tiene_encabezado else 1
    for indice, fila in enumerate(tabla.filas, desplazamiento):
        datos_normalizados = normalizar_fila(fila, columnas)
        error_bloque = ""
        if inicio_bloque is not None:
            bloques = []
            for inicio in (inicio_bloque, inicio_bloque + 1):
                bloque = _leer_bloque_operativo(fila, tabla.encabezados, inicio)
                if bloque is not None:
                    bloques.append(bloque)
            bloques_unicos = {
                tuple(bloque[campo] for campo in CAMPOS_BLOQUE_OPERATIVO): bloque
                for bloque in bloques
            }
            if len(bloques_unicos) == 1:
                datos_normalizados.update(next(iter(bloques_unicos.values())))
            elif not bloques_unicos:
                error_bloque = "BLOQUE_OPERATIVO_NO_RECONOCIBLE"
            else:
                error_bloque = "BLOQUE_OPERATIVO_AMBIGUO"
        registro = RegistroProcesamiento(
            id_fila=f"{tabla.ruta.name}:{indice}",
            archivo_origen=str(tabla.ruta),
            numero_fila_origen=indice,
            datos_originales={clave: "" if valor is None else str(valor) for clave, valor in fila.items()},
            datos_normalizados=datos_normalizados,
        )
        if error_bloque:
            registro.registrar(
                "SAN-01", "PREPARACION_BLOQUE", CategoriaResultado.REVISION_MANUAL,
                error_bloque,
                _valores_sector_operativo(fila, tabla.encabezados, inicio_bloque),
                "OT|OS|FECHA|HI|HF|ACC|COO|OBS|LECT inequívocos",
            )
        else:
            registro.marcar_continua(
                EstadoFila.NORMALIZADA, "NOR-01", "NORMALIZACION",
                "Fila normalizada conservando el original.",
            )
        registros.append(registro)
    return registros


def _posicion_columna_null(tabla: TablaDatos) -> Optional[int]:
    for indice, encabezado in enumerate(tabla.encabezados):
        if normalizar_encabezado(encabezado) == "NULL":
            return indice
    return None


def _leer_bloque_operativo(
    fila: Dict[str, str], encabezados: List[str], inicio: int,
) -> Optional[Dict[str, str]]:
    if inicio < 0 or inicio + len(CAMPOS_BLOQUE_OPERATIVO) > len(encabezados):
        return None
    columnas = {
        campo: encabezados[inicio + desplazamiento]
        for desplazamiento, campo in enumerate(CAMPOS_BLOQUE_OPERATIVO)
    }
    datos = normalizar_fila(fila, columnas)
    identificador = re.compile(r"[A-Za-z0-9_-]+")
    if not identificador.fullmatch(datos.get("OT", "")):
        return None
    if not identificador.fullmatch(datos.get("OS", "")):
        return None
    try:
        datos["FECHA"] = normalizar_fecha(datos.get("FECHA", ""))
        datos["HI"] = normalizar_hora(datos.get("HI", ""))
        datos["HF"] = normalizar_hora(datos.get("HF", ""))
        if datos.get("LECT", ""):
            normalizar_decimal(datos["LECT"])
    except ValueError:
        return None
    if not datos["FECHA"] or not datos["HI"] or not datos["HF"]:
        return None
    if not re.fullmatch(r"\d+", datos.get("ACC", "")):
        return None
    if not identificador.fullmatch(datos.get("COO", "")):
        return None
    return {campo: datos.get(campo, "") for campo in CAMPOS_BLOQUE_OPERATIVO}


def _valores_sector_operativo(
    fila: Dict[str, str], encabezados: List[str], inicio: Optional[int],
) -> str:
    if inicio is None:
        return "No existe la columna original null."
    fin = min(len(encabezados), inicio + len(CAMPOS_BLOQUE_OPERATIVO) + 1)
    return " | ".join(
        f"{encabezados[indice]}={fila.get(encabezados[indice], '')}"
        for indice in range(inicio, fin)
    )


def _valores_columna(tabla: TablaDatos, canonica: str, configuracion: ConfiguracionProcesamiento) -> List[str]:
    columnas = resolver_columnas(tabla.encabezados, configuracion)
    original = columnas.get(canonica)
    if original is None:
        return []
    return [normalizar_identificador(fila.get(original, "")) for fila in tabla.filas]


def _indice_control(
    tabla: TablaDatos,
    configuracion: ConfiguracionProcesamiento,
) -> Tuple[Dict[str, List[Dict[str, str]]], Dict[str, Set[str]]]:
    columnas = resolver_columnas(tabla.encabezados, configuracion)
    if "OS" not in columnas or "OT" not in columnas:
        raise ValueError("La data de control debe contener columnas de OS y OT.")
    por_os: Dict[str, List[Dict[str, str]]] = defaultdict(list)
    os_por_ot: Dict[str, Set[str]] = defaultdict(set)
    for fila in tabla.filas:
        datos = normalizar_fila(fila, columnas)
        por_os[datos.get("OS", "")].append(datos)
        os_por_ot[datos.get("OT", "")].add(datos.get("OS", ""))
    return dict(por_os), dict(os_por_ot)


def _indice_actividades(
    tabla: Optional[TablaDatos],
    configuracion: ConfiguracionProcesamiento,
) -> Dict[str, List[Dict[str, str]]]:
    if tabla is None:
        return {}
    columnas = resolver_columnas(tabla.encabezados, configuracion)
    encabezados = {normalizar_encabezado(nombre): nombre for nombre in tabla.encabezados}
    # Contrato observado en las muestras: C contiene TOxxx y TIPO_2 su descripción.
    # Se acepta únicamente cuando también existen TIPO y FUENTE, evitando tratar
    # cualquier columna aislada llamada C como tipo de OS.
    if "TIPO_OS" not in columnas and {"C", "TIPO", "FUENTE", "TIPO_2"}.issubset(encabezados):
        columnas["TIPO_OS"] = encabezados["C"]
        columnas.setdefault("OBS_TIPO", encabezados["TIPO_2"])
    por_tipo_os: Dict[str, List[Dict[str, str]]] = defaultdict(list)
    if "TIPO_OS" not in columnas:
        return {}
    for fila in tabla.filas:
        datos = normalizar_fila(fila, columnas)
        por_tipo_os[datos.get("TIPO_OS", "")].append(datos)
    return dict(por_tipo_os)


def _indice_operarios(tabla: Optional[TablaDatos]) -> Dict[str, List[Dict[str, str]]]:
    if tabla is None:
        return {}
    encabezados = {normalizar_encabezado(nombre): nombre for nombre in tabla.encabezados}
    nombres = {
        "OPER": encabezados.get("OPER") or encabezados.get("OPERARIO"),
        "CODIGO_GIO": encabezados.get("CODIGO_GIO"),
        "CODIGO_SYSACAO": encabezados.get("CODIGO_SYSACAO"),
    }
    indice: Dict[str, List[Dict[str, str]]] = defaultdict(list)
    for fila in tabla.filas:
        datos = {
            clave: normalizar_identificador(fila.get(columna, "")) if columna else ""
            for clave, columna in nombres.items()
        }
        # La dirección confirmada del cruce es exclusivamente SYSACAO -> GIO.
        # El nombre y el código GIO son valores de salida, no claves de busca.
        codigo_sysacao = datos["CODIGO_SYSACAO"]
        if codigo_sysacao:
            indice[codigo_sysacao].append(datos)
    return dict(indice)


def _revisar(
    registro: RegistroProcesamiento,
    regla: str,
    etapa: str,
    motivo: str,
    recibido: object = "",
    esperado: object = "",
) -> None:
    registro.registrar(
        regla, etapa, CategoriaResultado.REVISION_MANUAL, motivo, recibido, esperado
    )


def procesar_flujo_comun(
    tabla_general: TablaDatos,
    tabla_control: TablaDatos,
    tabla_entregable_acumulado: TablaDatos,
    *,
    fecha_procesamiento: str,
    configuracion: Optional[ConfiguracionProcesamiento] = None,
    tabla_operarios: Optional[TablaDatos] = None,
    tabla_actividades: Optional[TablaDatos] = None,
) -> ResultadoFlujoComun:
    """Ejecuta reglas comunes y conserva el destino auditable de cada fila."""
    configuracion = configuracion or ConfiguracionProcesamiento.predeterminada()
    fecha_objetivo = normalizar_fecha(fecha_procesamiento)
    registros = _crear_registros(tabla_general, configuracion)
    # La conciliación comienza con la fecha seleccionada. Las filas que tienen
    # otra fecha válida se descartan antes de aplicar reglas y no se cuentan
    # como exclusión, revisión o error. Una fecha vacía o ilegible se conserva
    # para que el defecto sí quede registrado y no desaparezca silenciosamente.
    registros_fecha: List[RegistroProcesamiento] = []
    for registro in registros:
        fecha_cruda = registro.datos_normalizados.get("FECHA", "")
        try:
            fecha_normalizada = normalizar_fecha(fecha_cruda)
        except ValueError:
            registros_fecha.append(registro)
            continue
        if not fecha_normalizada or fecha_normalizada == fecha_objetivo:
            registros_fecha.append(registro)
    registros = registros_fecha
    por_os, os_por_ot = _indice_control(tabla_control, configuracion)
    actividades = _indice_actividades(tabla_actividades, configuracion)
    operarios = _indice_operarios(tabla_operarios)

    columnas_acumulado = resolver_columnas(
        tabla_entregable_acumulado.encabezados, configuracion
    )
    if "OT" not in columnas_acumulado:
        raise ValueError("El entregable acumulado no contiene una columna OT reconocible.")
    ots_acumulado = _valores_columna(tabla_entregable_acumulado, "OT", configuracion)
    os_acumulado = set(_valores_columna(tabla_entregable_acumulado, "OS", configuracion))
    nis_acumulado = set(_valores_columna(tabla_entregable_acumulado, "NIS", configuracion))
    conteo_ots = Counter(ot for ot in ots_acumulado if ot)
    ots_unicas = {ot for ot, cantidad in conteo_ots.items() if cantidad == 1}
    ots_duplicadas = {ot for ot, cantidad in conteo_ots.items() if cantidad > 1}

    bloqueos: List[str] = []
    if tabla_actividades is None:
        bloqueos.append("No se cargó el catálogo de actividades; solo continuarán filas que ya tengan TIPO.")
    if tabla_operarios is None:
        bloqueos.append("No se cargó la tabla de operarios; los códigos no podrán validarse.")

    for registro in registros:
        if registro.estado == EstadoFila.EN_REVISION:
            continue
        datos = registro.datos_normalizados
        ot, os = datos.get("OT", ""), datos.get("OS", "")
        datos["ENTREGABLE_COINCIDE_OT"] = "SI" if ot and ot in conteo_ots else "NO"
        datos["ENTREGABLE_COINCIDE_OS"] = "SI" if os and os in os_acumulado else "NO"
        datos["ENTREGABLE_COINCIDE_NIS_RAD"] = (
            "SI" if datos.get("NIS") and datos.get("NIS") in nis_acumulado else "NO"
        )
        if not ot or not os:
            _revisar(
                registro, "PAR-00", "VALIDACION_OT_OS", "FALTA_IDENTIFICADOR_OT_OS",
                f"OT={ot}; OS={os}", "OT y OS informadas",
            )
            continue

        try:
            fecha_fila = normalizar_fecha(datos.get("FECHA", ""))
        except ValueError:
            _revisar(registro, "ENT-03", "FILTRO_FECHA", "FECHA_INVALIDA", datos.get("FECHA", ""), fecha_objetivo)
            continue
        if not fecha_fila:
            _revisar(registro, "ENT-03", "FILTRO_FECHA", "FECHA_VACIA", "", fecha_objetivo)
            continue
        datos["FECHA"] = fecha_fila
        if fecha_fila != fecha_objetivo:
            continue

        if ot in ots_duplicadas:
            _revisar(
                registro, "COM-05", "ENTREGABLE_ACUMULADO", "CLAVE_ENTREGABLE_DUPLICADA",
                ot, "OT única en el entregable acumulado",
            )
            continue
        if ot in ots_unicas:
            registro.registrar(
                "COM-03", "ENTREGABLE_ACUMULADO", CategoriaResultado.EXCLUSION_OPERATIVA,
                "YA_ACTUALIZADA_EN_ENTREGABLE", ot, "OT ausente del acumulado",
            )
            continue

        coincidencias = por_os.get(os, [])
        if not coincidencias:
            _revisar(registro, "PAR-06", "VALIDACION_OT_OS", "OS_NO_ENCONTRADA", os, "OS existente en control")
            continue
        ots_control = {fila.get("OT", "") for fila in coincidencias}
        if len(coincidencias) > 1 or len(ots_control) > 1:
            _revisar(
                registro, "PAR-05", "VALIDACION_OT_OS", "OS_DUPLICADA_EN_CONTROL",
                f"OS={os}; OT={','.join(sorted(ots_control))}", "Una OS asociada a una sola OT",
            )
            continue
        control = coincidencias[0]
        if control.get("OT", "") != ot:
            _revisar(
                registro, "PAR-03", "VALIDACION_OT_OS", "INCONSISTENCIA_OT_OS",
                f"OS {os} con OT {ot}", f"OT {control.get('OT', '')}",
            )
            continue
        if ot in os_por_ot and os not in os_por_ot[ot]:
            _revisar(registro, "PAR-04", "VALIDACION_OT_OS", "INCONSISTENCIA_OT_OS", os, ",".join(sorted(os_por_ot[ot])))
            continue

        for campo in ("NIS", "TIPO_OS", "ACTIVIDAD", "DESC_ACTIVIDAD"):
            if not datos.get(campo) and control.get(campo):
                datos[campo] = control[campo]
        # La acción ejecutada que decide la matriz GIO proviene del control
        # asociado por OS. ACC del CSV SANSYS se conserva como dato operativo
        # original, pero no sustituye ncod_causa.
        datos["NCOD_CAUSA_CONTROL_GIO"] = control.get("NCOD_CAUSA_GIO", "")
        datos["OBSERVACION_CONTROL_GIO"] = control.get("OBSERVACION_CONTROL_GIO", "")
        estado = control.get("ESTADO", "").upper()
        datos["ESTADO"] = estado
        if estado in configuracion.valores_estado_no_disponible:
            _revisar(registro, "EST-02", "VALIDACION_ESTADO", "ESTADO_NO_DISPONIBLE", estado, "TRAB/TRABAJANDO")
            continue
        if estado in configuracion.estados_exclusion:
            registro.registrar(
                "EST-03", "VALIDACION_ESTADO", CategoriaResultado.EXCLUSION_OPERATIVA,
                "ESTADO_NO_ACTUALIZABLE", estado, "TRAB/TRABAJANDO",
            )
            continue
        if estado not in configuracion.estados_continuar:
            _revisar(registro, "EST-04", "VALIDACION_ESTADO", "ESTADO_NO_CATALOGADO", estado, "Catálogo oficial de estados")
            continue

        tipo_os = datos.get("TIPO_OS", "")
        if not datos.get("TIPO") and tipo_os:
            candidatos = actividades.get(tipo_os, [])
            if tabla_actividades is not None and not candidatos:
                _revisar(
                    registro, "TIP-01", "CLASIFICACION_TIPO",
                    "TIPO_OS_NO_ENCONTRADO_EN_ACTIVIDAD", tipo_os,
                    "vtipo_os existente en la hoja ACTIVIDAD",
                )
                continue
            tipos = {fila.get("TIPO", "") for fila in candidatos if fila.get("TIPO")}
            if len(tipos) == 1:
                datos["TIPO"] = next(iter(tipos))
                descripcion = next((fila.get("OBS_TIPO", "") for fila in candidatos if fila.get("OBS_TIPO")), "")
                if descripcion:
                    datos["OBS_TIPO"] = descripcion
            elif len(tipos) > 1:
                _revisar(registro, "TIP-00", "CLASIFICACION_TIPO", "TIPO_AMBIGUO", tipo_os, ",".join(sorted(tipos)))
                continue

        tipo = datos.get("TIPO", "").upper()
        if tipo in configuracion.tipos_bloqueados:
            _revisar(registro, "TIP-03", "CLASIFICACION_TIPO", "TIPO_PENDIENTE_DE_CONFIRMACION", tipo, "C/CD/V/R/RD")
            continue
        if tipo not in configuracion.tipos_cierre | configuracion.tipos_reapertura:
            _revisar(registro, "TIP-04", "CLASIFICACION_TIPO", "TIPO_NO_CLASIFICADO", tipo, "C/CD/V/R/RD")
            continue

        datos["RGLA_GIO"] = datos.get("TIPO", "")
        datos["OBSERVACION_GIO"] = datos.get("OBS_TIPO", "")
        datos["NCOD_CAUSA_EJECUTADA"] = datos.get("ACC", "")

        codigo_operario = datos.get("COO", "")
        datos["COO_ORIGINAL"] = codigo_operario
        if not codigo_operario:
            _revisar(
                registro, "OPE-01", "VALIDACION_OPERARIO", "COO_VACIO",
                codigo_operario, "COO informado",
            )
            continue
        if not re.fullmatch(r"[A-Za-z0-9_-]+", codigo_operario):
            _revisar(
                registro, "OPE-01", "VALIDACION_OPERARIO", "COO_ILEGIBLE",
                codigo_operario, "Código alfanumérico legible",
            )
            continue

        equivalencias = operarios.get(codigo_operario, [])
        if not equivalencias:
            datos["COO_FINAL_GIO"] = codigo_operario
            datos["ESTADO_CONVERSION"] = "SIN_CONVERSION_REQUERIDA"
            registro.registrar(
                "OPE-03", "VALIDACION_OPERARIO", CategoriaResultado.CONTINUA,
                "COO conservado porque no requiere conversión SYSACAO.",
                codigo_operario, codigo_operario,
            )
            registro.marcar_continua(
                EstadoFila.DATA_FILTRADA, "COM-09", "DATA_FILTRADA",
                "La fila superó las validaciones comunes.",
            )
            continue

        codigos_gio = {fila.get("CODIGO_GIO", "") for fila in equivalencias}
        codigos_gio_informados = {codigo for codigo in codigos_gio if codigo}
        if len(codigos_gio_informados) > 1:
            _revisar(
                registro, "OPE-04", "VALIDACION_OPERARIO", "EQUIVALENCIA_SYSACAO_CONTRADICTORIA",
                codigo_operario, ",".join(sorted(codigos_gio_informados)),
            )
            continue
        equivalencia = equivalencias[0]
        datos["OPERARIO"] = equivalencia.get("OPER", "")
        datos["CODIGO_GIO"] = next(iter(codigos_gio_informados), "")
        datos["CODIGO_SYSACAO"] = equivalencia.get("CODIGO_SYSACAO", "")
        if not datos["CODIGO_GIO"] or "" in codigos_gio:
            _revisar(registro, "OPE-02", "VALIDACION_OPERARIO", "OPERARIO_SIN_CODIGO_GIO", codigo_operario, "CODIGO GIO informado")
            continue
        datos["COO_ORIGINAL_SYSACAO"] = codigo_operario
        datos["COO_FINAL_GIO"] = datos["CODIGO_GIO"]
        datos["ESTADO_CONVERSION"] = "CONVERTIDO_SYSACAO_A_GIO"
        datos["COO"] = datos["CODIGO_GIO"]

        registro.marcar_continua(
            EstadoFila.DATA_FILTRADA, "COM-09", "DATA_FILTRADA",
            "La fila superó las validaciones comunes.",
        )

    verificar_conservacion(registros)
    data_filtrada = [fila for fila in registros if fila.estado == EstadoFila.DATA_FILTRADA]
    resumen = resumir_etapa("FLUJO_COMUN", registros)
    return ResultadoFlujoComun(
        registros=registros,
        data_filtrada=data_filtrada,
        resumen=resumen,
        bloqueos=bloqueos,
    )
