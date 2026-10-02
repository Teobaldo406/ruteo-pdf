# -*- coding: utf-8 -*-
"""Modelos compartidos por todas las etapas de actualización de datos."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


class EstadoEtapa(str, Enum):
    PENDIENTE = "PENDIENTE"
    LISTO = "LISTO"
    PROCESANDO = "PROCESANDO"
    COMPLETADO = "COMPLETADO"
    CON_ERRORES = "CON_ERRORES"
    BLOQUEADO = "BLOQUEADO"


class CategoriaResultado(str, Enum):
    CONTINUA = "CONTINUA"
    PROCESADA = "PROCESADA"
    EXCLUSION_OPERATIVA = "EXCLUSION_OPERATIVA"
    REVISION_MANUAL = "REVISION_MANUAL"
    ERROR_TECNICO = "ERROR_TECNICO"


class EstadoFila(str, Enum):
    RECIBIDA = "RECIBIDA"
    NORMALIZADA = "NORMALIZADA"
    DATA_FILTRADA = "DATA_FILTRADA"
    CIERRE_LISTO = "CIERRE_LISTO"
    REAPERTURA_LISTA = "REAPERTURA_LISTA"
    EXCLUIDA = "EXCLUIDA"
    EN_REVISION = "EN_REVISION"
    ERROR = "ERROR"
    EXPORTADA = "EXPORTADA"


@dataclass(frozen=True)
class FormatoArchivo:
    tipo: str
    codificacion: str = "utf-8-sig"
    delimitador: str = "\t"
    tiene_encabezado: bool = True
    fila_encabezado: int = 1
    columnas: tuple[str, ...] = ()
    formato_fecha: str = ""
    formato_hora: str = ""


@dataclass
class TablaDatos:
    ruta: Path
    encabezados: List[str]
    filas: List[Dict[str, str]]
    formato: FormatoArchivo
    hoja: str = ""
    advertencias: List[str] = field(default_factory=list)

    @property
    def total_filas(self) -> int:
        return len(self.filas)


@dataclass
class ResultadoValidacion:
    regla_aplicada: str
    etapa: str
    categoria: CategoriaResultado
    motivo: str
    valor_recibido: str = ""
    valor_esperado: str = ""
    fecha_hora: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    def como_diccionario(self) -> Dict[str, str]:
        datos = asdict(self)
        datos["categoria"] = self.categoria.value
        return datos


@dataclass
class RegistroProcesamiento:
    id_fila: str
    archivo_origen: str
    numero_fila_origen: int
    datos_originales: Dict[str, str]
    datos_normalizados: Dict[str, str] = field(default_factory=dict)
    estado: EstadoFila = EstadoFila.RECIBIDA
    categoria_final: CategoriaResultado = CategoriaResultado.CONTINUA
    motivo_final: str = ""
    regla_final: str = ""
    etapa_final: str = "ENTRADA"
    archivo_destino: str = ""
    historial: List[ResultadoValidacion] = field(default_factory=list)

    @property
    def ot(self) -> str:
        return self.datos_normalizados.get("OT", "")

    @property
    def os(self) -> str:
        return self.datos_normalizados.get("OS", "")

    @property
    def nis(self) -> str:
        return self.datos_normalizados.get("NIS", "")

    @property
    def tipo(self) -> str:
        return self.datos_normalizados.get("TIPO", "").upper()

    def registrar(
        self,
        regla: str,
        etapa: str,
        categoria: CategoriaResultado,
        motivo: str,
        recibido: object = "",
        esperado: object = "",
    ) -> ResultadoValidacion:
        validacion = ResultadoValidacion(
            regla_aplicada=regla,
            etapa=etapa,
            categoria=categoria,
            motivo=motivo,
            valor_recibido="" if recibido is None else str(recibido),
            valor_esperado="" if esperado is None else str(esperado),
        )
        self.historial.append(validacion)
        if categoria != CategoriaResultado.CONTINUA:
            self.categoria_final = categoria
            self.motivo_final = motivo
            self.regla_final = regla
            self.etapa_final = etapa
            if categoria == CategoriaResultado.EXCLUSION_OPERATIVA:
                self.estado = EstadoFila.EXCLUIDA
            elif categoria == CategoriaResultado.REVISION_MANUAL:
                self.estado = EstadoFila.EN_REVISION
            elif categoria == CategoriaResultado.ERROR_TECNICO:
                self.estado = EstadoFila.ERROR
        return validacion

    def marcar_continua(self, estado: EstadoFila, regla: str, etapa: str, motivo: str) -> None:
        self.estado = estado
        self.registrar(regla, etapa, CategoriaResultado.CONTINUA, motivo)

    def como_fila_auditoria(self, id_ejecucion: str) -> Dict[str, str]:
        return {
            "ID_EJECUCION": id_ejecucion,
            "ID_FILA": self.id_fila,
            "ARCHIVO_ORIGEN": self.archivo_origen,
            "FILA_ORIGEN": str(self.numero_fila_origen),
            "FILA_ORIGINAL": str(self.numero_fila_origen),
            "ETAPA": self.etapa_final,
            "REGLA_APLICADA": self.regla_final,
            "REGLA": self.regla_final,
            "CATEGORIA": self.categoria_final.value,
            "MOTIVO": self.motivo_final,
            "OT": self.ot,
            "OS": self.os,
            "NIS": self.nis,
            "NIS_RAD": self.nis,
            "COO_ORIGINAL": self.datos_normalizados.get("COO_ORIGINAL", ""),
            "COO_ORIGINAL_SYSACAO": self.datos_normalizados.get("COO_ORIGINAL_SYSACAO", ""),
            "COO_FINAL_GIO": self.datos_normalizados.get("COO_FINAL_GIO", ""),
            "ESTADO_CONVERSION": self.datos_normalizados.get("ESTADO_CONVERSION", ""),
            "ESTADO_FILA": self.estado.value,
            "ARCHIVO_DESTINO": self.archivo_destino,
            "DESTINO": self.archivo_destino or self.estado.value,
            "REGLA_PROVISIONAL": self.datos_normalizados.get("REGLA_PROVISIONAL", "NO"),
            "RGLA_ORIGINAL": self.datos_normalizados.get("RGLA_ORIGINAL", ""),
            "OBSERVACION_ORIGINAL": self.datos_normalizados.get("OBSERVACION_ORIGINAL", ""),
            "NCOD_CAUSA_ORIGINAL": self.datos_normalizados.get("NCOD_CAUSA_ORIGINAL", ""),
            "NCOD_CAUSA_CONTROL_GIO": self.datos_normalizados.get("NCOD_CAUSA_CONTROL_GIO", ""),
            "OBSERVACION_CONTROL_GIO": self.datos_normalizados.get("OBSERVACION_CONTROL_GIO", ""),
            "ID_REGLA_GIO": self.datos_normalizados.get("ID_REGLA_GIO", ""),
            "PRIORIDAD_REGLA_GIO": self.datos_normalizados.get("PRIORIDAD_REGLA_GIO", ""),
            "RESULTADO_REGLA_GIO": self.datos_normalizados.get("RESULTADO_REGLA_GIO", ""),
            "CATEGORIA_REGLA_GIO": self.datos_normalizados.get("CATEGORIA_REGLA_GIO", ""),
            "MOTIVO_REGLA_GIO": self.datos_normalizados.get("MOTIVO_REGLA_GIO", ""),
            "DESTINO_REGLA_GIO": self.datos_normalizados.get("DESTINO_REGLA_GIO", ""),
            "ESTADO_VALIDACION_GIO": self.datos_normalizados.get("ESTADO_VALIDACION_GIO", ""),
            "VALIDACION_LECTURA": self.datos_normalizados.get("VALIDACION_LECTURA", ""),
            "MOTIVO_LECTURA": self.datos_normalizados.get("MOTIVO_LECTURA", ""),
            "RESULTADO_LECTURA": self.datos_normalizados.get("RESULTADO_LECTURA", ""),
        }


@dataclass
class ResumenEtapa:
    etapa: str
    entradas: int = 0
    continuan: int = 0
    procesadas: int = 0
    exclusiones_operativas: int = 0
    revisiones: int = 0
    errores_tecnicos: int = 0

    @property
    def total_clasificado(self) -> int:
        return (
            self.continuan
            + self.procesadas
            + self.exclusiones_operativas
            + self.revisiones
            + self.errores_tecnicos
        )


@dataclass
class ContextoEjecucion:
    id_ejecucion: str
    fecha_procesamiento: str
    carpeta_salida: Path
    fecha_hora_inicio: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    entradas: Dict[str, str] = field(default_factory=dict)
    huellas: Dict[str, str] = field(default_factory=dict)
    estados_etapas: Dict[str, EstadoEtapa] = field(default_factory=dict)
    resumenes: Dict[str, ResumenEtapa] = field(default_factory=dict)
    archivos_generados: Dict[str, str] = field(default_factory=dict)
    configuracion_aplicada: Dict[str, Any] = field(default_factory=dict)
    metadatos_entradas: Dict[str, Any] = field(default_factory=dict)
    entregable_cierres: str = ""
    entregable_actualizado: str = ""

    def cambiar_estado(self, etapa: str, estado: EstadoEtapa) -> None:
        self.estados_etapas[etapa] = estado


@dataclass
class ResultadoFlujoComun:
    registros: List[RegistroProcesamiento]
    data_filtrada: List[RegistroProcesamiento]
    resumen: ResumenEtapa
    bloqueos: List[str] = field(default_factory=list)


@dataclass
class ResultadoRama:
    nombre: str
    entradas: List[RegistroProcesamiento]
    listas: List[RegistroProcesamiento]
    revisiones: List[RegistroProcesamiento]
    exclusiones: List[RegistroProcesamiento] = field(default_factory=list)
    bloqueos: List[str] = field(default_factory=list)


@dataclass
class ResultadoProceso:
    contexto: ContextoEjecucion
    flujo_comun: Optional[ResultadoFlujoComun] = None
    cierres: Optional[ResultadoRama] = None
    reaperturas: Optional[ResultadoRama] = None


class ProcesoBloqueadoError(RuntimeError):
    """La etapa no puede continuar porque falta una decisión o dependencia."""


def contar_categorias(registros: Iterable[RegistroProcesamiento], etapa: str) -> ResumenEtapa:
    filas = list(registros)
    resumen = ResumenEtapa(etapa=etapa, entradas=len(filas))
    for registro in filas:
        if registro.categoria_final == CategoriaResultado.CONTINUA:
            resumen.continuan += 1
        elif registro.categoria_final == CategoriaResultado.PROCESADA:
            resumen.procesadas += 1
        elif registro.categoria_final == CategoriaResultado.EXCLUSION_OPERATIVA:
            resumen.exclusiones_operativas += 1
        elif registro.categoria_final == CategoriaResultado.REVISION_MANUAL:
            resumen.revisiones += 1
        else:
            resumen.errores_tecnicos += 1
    return resumen
