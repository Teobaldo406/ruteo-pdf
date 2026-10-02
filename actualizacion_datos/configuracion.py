# -*- coding: utf-8 -*-
"""Configuración explícita de reglas; no contiene decisiones ocultas en la UI."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Set


@dataclass(frozen=True)
class ContratoTxt:
    nombre: str
    columnas: tuple[str, ...]
    confirmado: bool = False
    delimitador: str = "\t"
    codificacion: str = "utf-8-sig"
    incluir_encabezado: bool = True
    formato_fecha: str = "%d/%m/%Y"
    formato_hora: str = "%H:%M"
    mapeo_columnas: tuple[tuple[str, str], ...] = ()
    provisional: bool = False


@dataclass(frozen=True)
class ReglaAccion:
    id_regla: str
    tipo: str
    accion_ejecutada: str
    tipos_os: tuple[str, ...] = ()
    actividades: tuple[str, ...] = ()
    textos_actividad: tuple[str, ...] = ()
    textos_tipo: tuple[str, ...] = ()
    clasificacion: str = "EFECTIVA"
    aplica_lectura: bool = False
    acciones_reapertura: tuple[str, ...] = ()
    activa: bool = True
    provisional: bool = False
    fuente: str = ""

    def coincide_contexto(self, datos: Mapping[str, str]) -> bool:
        if not self.activa or datos.get("TIPO", "").upper() != self.tipo.upper():
            return False
        if str(datos.get("ACC", "")) != self.accion_ejecutada:
            return False
        if self.tipos_os and datos.get("TIPO_OS", "").upper() not in {
            valor.upper() for valor in self.tipos_os
        }:
            return False
        if self.actividades and datos.get("ACTIVIDAD", "") not in self.actividades:
            return False
        texto_actividad = datos.get("DESC_ACTIVIDAD", "").upper()
        if self.textos_actividad and not any(texto.upper() in texto_actividad for texto in self.textos_actividad):
            return False
        texto_tipo = datos.get("OBS_TIPO", "").upper()
        if self.textos_tipo and not any(texto.upper() in texto_tipo for texto in self.textos_tipo):
            return False
        return True


@dataclass
class ConfiguracionProcesamiento:
    alias_columnas: Dict[str, tuple[str, ...]]
    estados_continuar: Set[str] = field(default_factory=lambda: {"TRAB", "TRABAJANDO"})
    estados_exclusion: Set[str] = field(
        default_factory=lambda: {"RESUL", "RESUELTA", "ANUL", "ANULADA", "PEND", "PENDIENTE"}
    )
    valores_estado_no_disponible: Set[str] = field(default_factory=lambda: {"", "NA", "N/A", "NO ENCONTRADA"})
    tipos_cierre: Set[str] = field(default_factory=lambda: {"C", "CD", "V"})
    tipos_reapertura: Set[str] = field(default_factory=lambda: {"R", "RD"})
    tipos_bloqueados: Set[str] = field(default_factory=lambda: {"B", "VD"})
    reglas_accion: List[ReglaAccion] = field(default_factory=list)
    limite_obs: int = 150
    limite_diferencia_cierre: int = 300
    limite_diferencia_reapertura: int = 20
    contrato_cierres_sistema: ContratoTxt = field(default_factory=lambda: ContratoTxt("CIERRES_SISTEMA", ()))
    contrato_entregable_cierres: ContratoTxt = field(default_factory=lambda: ContratoTxt("ENTREGABLE_CIERRES", ()))
    contrato_reaperturas_sistema: ContratoTxt = field(default_factory=lambda: ContratoTxt("REAPERTURAS_SISTEMA", ()))
    contrato_entregable_reaperturas: ContratoTxt = field(default_factory=lambda: ContratoTxt("ENTREGABLE_REAPERTURAS", ()))
    modo_reglas_provisionales: bool = False

    @classmethod
    def predeterminada(cls) -> "ConfiguracionProcesamiento":
        alias = {
            "OT": ("OT", "NRO_OT", "NRO OT", "ORDEN_TRABAJO"),
            "OS": ("OS", "NNUM_OS", "NRO_OS", "NRO OS"),
            "NIS": ("NIS", "NIS_RAD", "NISRA", "IDRA"),
            "FECHA": ("FECHA", "FEJECUCION", "FECHA_EJECUCION", "FECHA EJECUCION"),
            "HI": ("HI", "HORA_INICIO"),
            "HF": ("HF", "HORA_FIN"),
            "ACC": ("ACC", "ACCION", "ACCIÓN", "CODIGO_ACCION"),
            "COO": ("COO", "CODIGO", "OPER", "OPERARIO", "NCOD_CUADRILLA"),
            "OBS": ("OBS", "OBSERVACION", "OBSERVACIÓN"),
            "LECT": ("LECT", "LECTURA", "LECTURA_EJECUTADA"),
            "TIPO": ("TIPO", "TIPO_ORDEN"),
            "OBS_TIPO": ("OBS_TIPO", "OBS TIPO", "DESCRIPCION_TIPO"),
            "TIPO_OS": ("TIPO_OS", "TIPO OS", "VTIPO_OS"),
            "ACTIVIDAD": ("ACTIVIDAD",),
            "DESC_ACTIVIDAD": ("DESC_ACTIVIDAD", "DESC ACTIVIDAD", "DESCRIPCION_ACTIVIDAD"),
            "ESTADO": ("ESTADO", "ESTADO_OS", "ESTDADO_OS", "NEST_OT"),
            "LECTURA_TOMA": ("LECTURA_TOMA", "LECT TOMA"),
            "ACCION_CIERRE": ("ACCION_CIERRE", "ACCION CIERRE", "ACION CIERRE"),
            "LECTURA_CIERRE": ("LECTURA_CIERRE", "LECT CIERR"),
            "NCOD_CAUSA_GIO": ("NCOD_CAUSA", "NCOD CAUSA"),
            "OBSERVACION_CONTROL_GIO": ("OBSERVACION",),
        }
        return cls(alias_columnas=alias)

    def agregar_reglas_accion(self, reglas: Iterable[ReglaAccion]) -> None:
        existentes = {regla.id_regla for regla in self.reglas_accion}
        for regla in reglas:
            if regla.id_regla in existentes:
                raise ValueError(f"La regla de acción '{regla.id_regla}' está repetida.")
            self.reglas_accion.append(regla)
            existentes.add(regla.id_regla)

    def reglas_para_registro(self, datos: Mapping[str, str]) -> List[ReglaAccion]:
        return [regla for regla in self.reglas_accion if regla.coincide_contexto(datos)]

    def reglas_por_accion_cierre(self, accion: str) -> List[ReglaAccion]:
        return [
            regla for regla in self.reglas_accion
            if regla.activa and regla.accion_ejecutada == str(accion) and regla.acciones_reapertura
        ]

    def como_diccionario(self) -> Dict[str, object]:
        return {
            "alias_columnas": {clave: list(valores) for clave, valores in self.alias_columnas.items()},
            "estados_continuar": sorted(self.estados_continuar),
            "estados_exclusion": sorted(self.estados_exclusion),
            "valores_estado_no_disponible": sorted(self.valores_estado_no_disponible),
            "tipos_cierre": sorted(self.tipos_cierre),
            "tipos_reapertura": sorted(self.tipos_reapertura),
            "tipos_bloqueados": sorted(self.tipos_bloqueados),
            "reglas_accion": [asdict(regla) for regla in self.reglas_accion],
            "limite_obs": self.limite_obs,
            "limite_diferencia_cierre": self.limite_diferencia_cierre,
            "limite_diferencia_reapertura": self.limite_diferencia_reapertura,
            "modo_reglas_provisionales": self.modo_reglas_provisionales,
            "contratos": {
                "cierres_sistema": asdict(self.contrato_cierres_sistema),
                "entregable_cierres": asdict(self.contrato_entregable_cierres),
                "reaperturas_sistema": asdict(self.contrato_reaperturas_sistema),
                "entregable_reaperturas": asdict(self.contrato_entregable_reaperturas),
            },
        }


def cargar_configuracion_json(
    ruta: Path,
    base: Optional[ConfiguracionProcesamiento] = None,
) -> ConfiguracionProcesamiento:
    """Carga únicamente campos explícitos; los ausentes conservan el valor base."""
    configuracion = base or ConfiguracionProcesamiento.predeterminada()
    datos = json.loads(Path(ruta).read_text(encoding="utf-8-sig"))
    for nombre in (
        "estados_continuar", "estados_exclusion", "valores_estado_no_disponible",
        "tipos_cierre", "tipos_reapertura", "tipos_bloqueados",
    ):
        if nombre in datos:
            setattr(configuracion, nombre, {str(valor).upper() for valor in datos[nombre]})
    for nombre in ("limite_obs", "limite_diferencia_cierre", "limite_diferencia_reapertura"):
        if nombre in datos:
            setattr(configuracion, nombre, int(datos[nombre]))
    if "reglas_accion" in datos:
        configuracion.reglas_accion = []
        configuracion.agregar_reglas_accion([
            ReglaAccion(
                id_regla=str(fila["id_regla"]),
                tipo=str(fila["tipo"]),
                accion_ejecutada=str(fila["accion_ejecutada"]),
                tipos_os=tuple(str(v) for v in fila.get("tipos_os", [])),
                actividades=tuple(str(v) for v in fila.get("actividades", [])),
                textos_actividad=tuple(str(v) for v in fila.get("textos_actividad", [])),
                textos_tipo=tuple(str(v) for v in fila.get("textos_tipo", [])),
                clasificacion=str(fila.get("clasificacion", "EFECTIVA")),
                aplica_lectura=bool(fila.get("aplica_lectura", False)),
                acciones_reapertura=tuple(str(v) for v in fila.get("acciones_reapertura", [])),
                activa=bool(fila.get("activa", True)),
                provisional=bool(fila.get("provisional", False)),
                fuente=str(fila.get("fuente", "")),
            )
            for fila in datos["reglas_accion"]
        ])
    nombres_contrato = {
        "cierres_sistema": "contrato_cierres_sistema",
        "entregable_cierres": "contrato_entregable_cierres",
        "reaperturas_sistema": "contrato_reaperturas_sistema",
        "entregable_reaperturas": "contrato_entregable_reaperturas",
    }
    for clave, atributo in nombres_contrato.items():
        if clave not in datos.get("contratos", {}):
            continue
        fila = datos["contratos"][clave]
        contrato_actual = getattr(configuracion, atributo)
        setattr(configuracion, atributo, ContratoTxt(
            nombre=str(fila.get("nombre", contrato_actual.nombre)),
            columnas=tuple(str(v) for v in fila.get("columnas", [])),
            confirmado=bool(fila.get("confirmado", False)),
            delimitador=str(fila.get("delimitador", "\t")),
            codificacion=str(fila.get("codificacion", "utf-8-sig")),
            incluir_encabezado=bool(fila.get("incluir_encabezado", True)),
            formato_fecha=str(fila.get("formato_fecha", "%d/%m/%Y")),
            formato_hora=str(fila.get("formato_hora", "%H:%M")),
            mapeo_columnas=tuple(
                (str(par[0]), str(par[1])) for par in fila.get("mapeo_columnas", [])
            ),
            provisional=bool(fila.get("provisional", False)),
        ))
    return configuracion
