# -*- coding: utf-8 -*-
"""Lectura y evaluación de la matriz oficial RGLA + OBSERVACION + ncod_causa."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
import re
import unicodedata
from typing import Dict, Iterable, Optional

from .modelos import CategoriaResultado, RegistroProcesamiento, TablaDatos


HOJAS_MATRIZ_GIO = {
    "RESUMEN", "REGLAS_GIO", "COMBINACIONES_GIO", "GUIA_USO", "MATRIZ_TIPOLOGIAS"
}

COLUMNAS_MATRIZ_TIPOLOGIAS = {
    "TIPO", "ACC", "CIERRE_EFECTIVO", "REAPERTURA_ESPERADA",
    "RESULTADO", "ACTIVO", "CONDICION",
}


def normalizar_texto_gio(valor: object) -> str:
    texto = "" if valor is None else str(valor).strip().upper()
    texto = "".join(
        caracter for caracter in unicodedata.normalize("NFKD", texto)
        if not unicodedata.combining(caracter)
    )
    return re.sub(r"\s+", " ", texto)


def normalizar_accion_gio(valor: object) -> str:
    texto = "" if valor is None else str(valor).strip()
    # Algunos orígenes representan los códigos operativos separando la
    # centena con punto o guion (5.06 / 5-06). Se reconstruye el código como
    # texto y se conserva su familia: 5xx nunca se transforma en 6xx.
    codigo_separado = re.fullmatch(r"(\d)[.-](\d{2})", texto)
    if codigo_separado:
        return "".join(codigo_separado.groups())
    if re.fullmatch(r"[+-]?\d+\.0", texto):
        return texto[:-2]
    if "E" in texto.upper():
        try:
            decimal = Decimal(texto)
            if decimal == decimal.to_integral_value():
                return format(decimal.quantize(Decimal("1")), "f")
        except InvalidOperation:
            pass
    return texto


@dataclass(frozen=True)
class ReglaGio:
    id_regla: str
    prioridad: int
    regla: str
    coincidencia_obs: str
    patron_obs: str
    condicion_acc: str
    acc_lista: tuple[str, ...]
    acc_min: Optional[Decimal]
    acc_max: Optional[Decimal]
    resultado: str
    categoria: str
    motivo: str
    destino: str
    activa: bool
    accion_cierre: str = ""
    acciones_reapertura: tuple[str, ...] = ()

    @property
    def descripcion_accion(self) -> str:
        if self.condicion_acc == "LISTA":
            return " | ".join(self.acc_lista)
        if self.condicion_acc == "RANGO":
            return f"{self.acc_min} a {self.acc_max}"
        return self.condicion_acc

    @property
    def es_residual(self) -> bool:
        """Indica una regla final de revisión, no una aprobación de negocio."""
        return (
            normalizar_texto_gio(self.regla) == "*"
            and self.coincidencia_obs == "CUALQUIERA"
            and self.condicion_acc == "CUALQUIERA"
            and normalizar_texto_gio(self.resultado) in {"REVISION", "ERROR"}
        )

    def coincide(self, regla: str, observacion: str, accion: str) -> bool:
        alternativas = {normalizar_texto_gio(v) for v in self.regla.split("|")}
        if "*" not in alternativas and regla not in alternativas:
            return False
        if self.coincidencia_obs == "VACIO" and observacion:
            return False
        if self.coincidencia_obs == "CONTIENE" and normalizar_texto_gio(self.patron_obs) not in observacion:
            return False
        if self.condicion_acc == "VACIO":
            return not accion
        if self.condicion_acc == "LISTA":
            return accion in self.acc_lista
        if self.condicion_acc == "RANGO":
            try:
                numero = Decimal(accion)
            except InvalidOperation:
                return False
            return (
                self.acc_min is not None and self.acc_max is not None
                and self.acc_min <= numero <= self.acc_max
            )
        return self.condicion_acc == "CUALQUIERA"


@dataclass(frozen=True)
class ReglaTipologia:
    tipo: str
    accion: str
    cierre_efectivo: str
    reapertura_esperada: str
    resultado: str
    condicion: str
    activa: bool
    numero_fila: int
    clasificacion: str = ""
    requiere_cierre_anterior: bool = False
    requiere_cierre_efectivo: bool = False
    validar_equivalencia: bool = True
    validar_diferencia: bool = True

    @property
    def tipos(self) -> tuple[str, ...]:
        return tuple(
            normalizar_texto_gio(valor)
            for valor in self.tipo.split("|") if valor.strip()
        )


@dataclass(frozen=True)
class MatrizTipologias:
    reglas: tuple[ReglaTipologia, ...]

    def buscar(self, tipo: str, accion: str) -> tuple[ReglaTipologia, ...]:
        tipo_normalizado = normalizar_texto_gio(tipo)
        accion_normalizada = normalizar_accion_gio(accion)
        return tuple(
            regla for regla in self.reglas
            if tipo_normalizado in regla.tipos and regla.accion == accion_normalizada
        )

    def tipos_activos_para_accion(self, accion: str) -> tuple[str, ...]:
        accion_normalizada = normalizar_accion_gio(accion)
        return tuple(sorted({
            tipo
            for regla in self.reglas if regla.activa and regla.accion == accion_normalizada
            for tipo in regla.tipos
        }))

@dataclass(frozen=True)
class MatrizReglasGio:
    reglas: tuple[ReglaGio, ...]
    combinaciones: frozenset[tuple[str, str, str]]
    hojas: tuple[str, ...]
    ruta: str = ""
    fecha_modificacion: str = ""
    tipologias: Optional[MatrizTipologias] = None
    tablas: Dict[str, TablaDatos] = field(default_factory=dict, compare=False, repr=False)

    @property
    def reglas_activas(self) -> tuple[ReglaGio, ...]:
        return tuple(regla for regla in self.reglas if regla.activa)

    @property
    def reglas_inactivas(self) -> tuple[ReglaGio, ...]:
        return tuple(regla for regla in self.reglas if not regla.activa)


def _valor(fila: dict[str, str], nombre: str) -> str:
    return str(fila.get(nombre, "") or "").strip()


def construir_matriz_gio(
    reglas: TablaDatos,
    combinaciones: TablaDatos,
    hojas: Iterable[str],
    ruta: Optional[Path] = None,
    tabla_tipologias: Optional[TablaDatos] = None,
    tablas: Optional[Dict[str, TablaDatos]] = None,
) -> MatrizReglasGio:
    resultado = []
    errores: list[str] = []
    identificadores: dict[str, int] = {}
    for numero_fila, fila in enumerate(reglas.filas, 2):
        if not any(_valor(fila, columna) for columna in reglas.encabezados):
            continue
        valor_activo = normalizar_texto_gio(_valor(fila, "ACTIVO"))
        if valor_activo not in {"SI", "NO"}:
            errores.append(
                f"Fila {numero_fila}: ACTIVO debe ser SI o NO; se recibió '{_valor(fila, 'ACTIVO')}'."
            )
        activo = valor_activo == "SI"
        identificador = _valor(fila, "ID_REGLA")
        if not identificador:
            errores.append(f"Fila {numero_fila}: ID_REGLA está vacío.")
        elif identificador in identificadores:
            errores.append(
                f"ID_REGLA duplicado '{identificador}' en filas "
                f"{identificadores[identificador]} y {numero_fila}."
            )
        else:
            identificadores[identificador] = numero_fila
        try:
            prioridad_decimal = Decimal(_valor(fila, "PRIORIDAD"))
            if prioridad_decimal != prioridad_decimal.to_integral_value() or prioridad_decimal <= 0:
                raise InvalidOperation
            prioridad = int(prioridad_decimal)
        except (InvalidOperation, ValueError):
            errores.append(
                f"Fila {numero_fila}: PRIORIDAD inválida '{_valor(fila, 'PRIORIDAD')}'."
            )
            prioridad = 0
        def decimal_opcional(nombre: str) -> Optional[Decimal]:
            valor = _valor(fila, nombre)
            if not valor:
                return None
            try:
                return Decimal(valor)
            except InvalidOperation:
                errores.append(f"Fila {numero_fila}: {nombre} inválido '{valor}'.")
                return None
        coincidencia_obs = normalizar_texto_gio(_valor(fila, "COINCIDENCIA_OBS"))
        condicion_acc = normalizar_texto_gio(_valor(fila, "CONDICION_ACC"))
        if coincidencia_obs not in {"VACIO", "CONTIENE", "CUALQUIERA"}:
            errores.append(f"Fila {numero_fila}: COINCIDENCIA_OBS inválida '{coincidencia_obs}'.")
        if condicion_acc not in {"VACIO", "LISTA", "RANGO", "CUALQUIERA"}:
            errores.append(f"Fila {numero_fila}: CONDICION_ACC inválida '{condicion_acc}'.")
        if coincidencia_obs == "CONTIENE" and not _valor(fila, "PATRON_OBS"):
            errores.append(f"Fila {numero_fila}: PATRON_OBS es obligatorio para CONTIENE.")
        lista_acciones = tuple(
            normalizar_accion_gio(v) for v in _valor(fila, "ACC_LISTA").split("|") if v.strip()
        )
        if condicion_acc == "LISTA" and not lista_acciones:
            errores.append(f"Fila {numero_fila}: ACC_LISTA está vacía para una condición LISTA.")
        minimo = decimal_opcional("ACC_MIN")
        maximo = decimal_opcional("ACC_MAX")
        if condicion_acc == "RANGO" and (
            minimo is None or maximo is None or minimo > maximo
        ):
            errores.append(
                f"Fila {numero_fila}: rango incoherente ACC_MIN={_valor(fila, 'ACC_MIN')} "
                f"ACC_MAX={_valor(fila, 'ACC_MAX')}."
            )
        resultado.append(ReglaGio(
            id_regla=identificador, prioridad=prioridad,
            regla=_valor(fila, "RGLA"),
            coincidencia_obs=coincidencia_obs,
            patron_obs=_valor(fila, "PATRON_OBS"),
            condicion_acc=condicion_acc, acc_lista=lista_acciones,
            acc_min=minimo, acc_max=maximo,
            resultado=_valor(fila, "RESULTADO"), categoria=_valor(fila, "CATEGORIA"),
            motivo=_valor(fila, "MOTIVO"), destino=_valor(fila, "DESTINO"), activa=activo,
            accion_cierre=normalizar_accion_gio(_valor(fila, "ACCION_CIERRE")),
            acciones_reapertura=tuple(
                normalizar_accion_gio(valor)
                for valor in re.split(r"[|,;]", _valor(fila, "ACCIONES_REAPERTURA"))
                if valor.strip()
            ),
        ))
    if errores:
        raise ValueError("MATRIZ CON ERRORES:\n- " + "\n- ".join(errores))
    resultado.sort(key=lambda regla: regla.prioridad)
    contradicciones = _buscar_contradicciones(resultado)
    if contradicciones:
        raise ValueError("MATRIZ CON ERRORES:\n- " + "\n- ".join(contradicciones))
    observadas = frozenset(
        (
            normalizar_texto_gio(_valor(fila, "RGLA")),
            normalizar_texto_gio(_valor(fila, "OBSERVACION")),
            normalizar_accion_gio(_valor(fila, "ncod_causa")),
        )
        for fila in combinaciones.filas
    )
    ruta_matriz = Path(ruta) if ruta else None
    fecha_modificacion = (
        datetime.fromtimestamp(ruta_matriz.stat().st_mtime).strftime("%d/%m/%Y %H:%M:%S")
        if ruta_matriz and ruta_matriz.exists() else ""
    )
    tipologias = construir_matriz_tipologias(tabla_tipologias) if tabla_tipologias else None
    return MatrizReglasGio(
        tuple(resultado), observadas, tuple(hojas),
        str(ruta_matriz) if ruta_matriz else "", fecha_modificacion,
        tipologias, dict(tablas or {}),
    )


def construir_matriz_tipologias(tabla: TablaDatos) -> MatrizTipologias:
    faltantes = sorted(COLUMNAS_MATRIZ_TIPOLOGIAS - set(tabla.encabezados))
    if faltantes:
        raise ValueError(
            "La hoja MATRIZ_TIPOLOGIAS no contiene las columnas obligatorias: "
            + ", ".join(faltantes)
        )
    reglas: list[ReglaTipologia] = []
    errores: list[str] = []
    for numero, fila in enumerate(tabla.filas, 2):
        if not any(_valor(fila, columna) for columna in tabla.encabezados):
            continue
        activo = normalizar_texto_gio(_valor(fila, "ACTIVO"))
        if activo not in {"SI", "NO"}:
            errores.append(
                f"MATRIZ_TIPOLOGIAS fila {numero}: ACTIVO debe ser SI o NO."
            )
        tipo = normalizar_texto_gio(_valor(fila, "TIPO"))
        accion = normalizar_accion_gio(_valor(fila, "ACC"))
        if not tipo or not accion:
            errores.append(
                f"MATRIZ_TIPOLOGIAS fila {numero}: TIPO y ACC son obligatorios."
            )
        clasificacion = normalizar_texto_gio(_valor(fila, "CLASIFICACION"))
        controles = {}
        if clasificacion == "IMPOSIBILIDAD_REAPERTURA":
            for columna in (
                "REQUIERE_CIERRE_ANTERIOR", "REQUIERE_CIERRE_EFECTIVO",
                "VALIDAR_EQUIVALENCIA", "VALIDAR_DIFERENCIA",
            ):
                valor = normalizar_texto_gio(_valor(fila, columna))
                if valor not in {"SI", "NO"}:
                    errores.append(
                        f"MATRIZ_TIPOLOGIAS fila {numero}: {columna} debe ser SI o NO "
                        "para IMPOSIBILIDAD_REAPERTURA."
                    )
                controles[columna] = valor == "SI"
        reglas.append(ReglaTipologia(
            tipo=tipo,
            accion=accion,
            cierre_efectivo=normalizar_accion_gio(_valor(fila, "CIERRE_EFECTIVO")),
            reapertura_esperada=normalizar_accion_gio(_valor(fila, "REAPERTURA_ESPERADA")),
            resultado=_valor(fila, "RESULTADO"),
            condicion=_valor(fila, "CONDICION"),
            activa=activo == "SI",
            numero_fila=numero,
            clasificacion=clasificacion,
            requiere_cierre_anterior=controles.get("REQUIERE_CIERRE_ANTERIOR", False),
            requiere_cierre_efectivo=controles.get("REQUIERE_CIERRE_EFECTIVO", False),
            validar_equivalencia=controles.get("VALIDAR_EQUIVALENCIA", True),
            validar_diferencia=controles.get("VALIDAR_DIFERENCIA", True),
        ))
    activas: dict[tuple[str, str], ReglaTipologia] = {}
    for regla in reglas:
        if not regla.activa:
            continue
        for tipo in regla.tipos:
            clave = (tipo, regla.accion)
            anterior = activas.get(clave)
            if anterior:
                errores.append(
                    "MATRIZ_TIPOLOGIAS contiene reglas activas ambiguas para "
                    f"TIPO={tipo}, ACC={regla.accion} en filas "
                    f"{anterior.numero_fila} y {regla.numero_fila}."
                )
            else:
                activas[clave] = regla
    if errores:
        raise ValueError("MATRIZ CON ERRORES:\n- " + "\n- ".join(errores))
    return MatrizTipologias(tuple(reglas))


def _buscar_contradicciones(reglas: list[ReglaGio]) -> list[str]:
    activas = [regla for regla in reglas if regla.activa]
    errores = []
    for indice, primera in enumerate(activas):
        for segunda in activas[indice + 1:]:
            if primera.prioridad != segunda.prioridad:
                continue
            if _reglas_se_superponen(primera, segunda):
                errores.append(
                    f"Prioridad {primera.prioridad}: reglas activas contradictorias "
                    f"'{primera.id_regla}' y '{segunda.id_regla}'."
                )
    return errores


def _reglas_se_superponen(primera: ReglaGio, segunda: ReglaGio) -> bool:
    def tipos(regla: ReglaGio) -> set[str]:
        return {normalizar_texto_gio(valor) for valor in regla.regla.split("|")}
    tipos_a, tipos_b = tipos(primera), tipos(segunda)
    if "*" not in tipos_a and "*" not in tipos_b and tipos_a.isdisjoint(tipos_b):
        return False
    if not _observaciones_se_superponen(primera, segunda):
        return False
    return _acciones_se_superponen(primera, segunda)


def _observaciones_se_superponen(primera: ReglaGio, segunda: ReglaGio) -> bool:
    if "CUALQUIERA" in {primera.coincidencia_obs, segunda.coincidencia_obs}:
        return True
    if primera.coincidencia_obs == "VACIO" or segunda.coincidencia_obs == "VACIO":
        return primera.coincidencia_obs == segunda.coincidencia_obs
    return True  # Un texto puede contener ambos patrones.


def _acciones_se_superponen(primera: ReglaGio, segunda: ReglaGio) -> bool:
    if "CUALQUIERA" in {primera.condicion_acc, segunda.condicion_acc}:
        return True
    if primera.condicion_acc == "VACIO" or segunda.condicion_acc == "VACIO":
        return primera.condicion_acc == segunda.condicion_acc
    if primera.condicion_acc == segunda.condicion_acc == "LISTA":
        return not set(primera.acc_lista).isdisjoint(segunda.acc_lista)
    if primera.condicion_acc == segunda.condicion_acc == "RANGO":
        return max(primera.acc_min, segunda.acc_min) <= min(primera.acc_max, segunda.acc_max)
    lista = primera if primera.condicion_acc == "LISTA" else segunda
    rango = segunda if primera.condicion_acc == "LISTA" else primera
    for accion in lista.acc_lista:
        try:
            numero = Decimal(accion)
        except InvalidOperation:
            continue
        if rango.acc_min <= numero <= rango.acc_max:
            return True
    return False


def evaluar_regla_gio(
    registro: RegistroProcesamiento,
    matriz: MatrizReglasGio,
) -> Optional[ReglaGio]:
    datos = registro.datos_normalizados
    regla_original = datos.get("RGLA_GIO", datos.get("TIPO", ""))
    observacion_original = datos.get("OBSERVACION_GIO", datos.get("OBS_TIPO", ""))
    fuentes_observacion = []
    for nombre in ("OBSERVACION_GIO", "OBS_TIPO", "OBS"):
        valor = datos.get(nombre, "")
        if valor and valor not in fuentes_observacion:
            fuentes_observacion.append(valor)
    accion_original = datos.get("NCOD_CAUSA_EJECUTADA", datos.get("ACC", ""))
    regla = normalizar_texto_gio(regla_original)
    observaciones_normalizadas = tuple(
        normalizar_texto_gio(valor) for valor in fuentes_observacion
    )
    observacion = " | ".join(observaciones_normalizadas)
    accion = normalizar_accion_gio(accion_original)
    datos.update({
        "RGLA_ORIGINAL": regla_original,
        "OBSERVACION_ORIGINAL": observacion_original,
        "CONTEXTO_OBSERVACION_GIO": observacion,
        "NCOD_CAUSA_ORIGINAL": accion_original,
    })
    encontrada = next(
        (candidata for candidata in matriz.reglas if candidata.activa and candidata.coincide(regla, observacion, accion)),
        None,
    )
    if encontrada and not encontrada.es_residual:
        _registrar_decision(registro, encontrada)
        return encontrada

    observada = any(
        (regla, candidata, accion) in matriz.combinaciones
        for candidata in observaciones_normalizadas
    )
    motivo = "REGLA_GIO_NO_CONFIGURADA"
    datos.update({
        "ID_REGLA_GIO": encontrada.id_regla if encontrada else "",
        "PRIORIDAD_REGLA_GIO": str(encontrada.prioridad) if encontrada else "",
        "RESULTADO_REGLA_GIO": "REVISION",
        "CATEGORIA_REGLA_GIO": "SIN_REGLA",
        "MOTIVO_REGLA_GIO": motivo,
        "DESTINO_REGLA_GIO": "ERRORES_VALIDACION",
        "ESTADO_VALIDACION_GIO": "OBSERVADA_SIN_APROBACION" if observada else "NO_RECONOCIDA",
    })
    registro.registrar(
        encontrada.id_regla if encontrada else "GIO-SIN-REGLA",
        "VALIDACION_REGLAS_GIO", CategoriaResultado.REVISION_MANUAL,
        motivo, f"{regla}|{observacion}|{accion}", "Regla GIO activa aprobada",
    )
    return None


def _registrar_decision(registro: RegistroProcesamiento, regla: ReglaGio) -> None:
    datos = registro.datos_normalizados
    datos.update({
        "ID_REGLA_GIO": regla.id_regla,
        "PRIORIDAD_REGLA_GIO": str(regla.prioridad),
        "RESULTADO_REGLA_GIO": regla.resultado,
        "CATEGORIA_REGLA_GIO": regla.categoria,
        "MOTIVO_REGLA_GIO": regla.motivo,
        "DESTINO_REGLA_GIO": regla.destino,
        "ESTADO_VALIDACION_GIO": "COINCIDE_REGLA_ACTIVA",
    })
    if regla.resultado in {"REVISION", "ERROR"}:
        # RESULTADO=ERROR en la matriz identifica un dato rechazado por GIO,
        # no una excepción técnica del aplicativo. Debe quedar en revisión.
        categoria = CategoriaResultado.REVISION_MANUAL
    else:
        categoria = CategoriaResultado.CONTINUA
    registro.registrar(
        regla.id_regla, "VALIDACION_REGLAS_GIO", categoria, regla.motivo,
        datos.get("NCOD_CAUSA_ORIGINAL", ""), regla.resultado,
    )
