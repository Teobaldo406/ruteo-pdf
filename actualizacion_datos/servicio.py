# -*- coding: utf-8 -*-
"""Coordinador de etapas. No importa PySide6 ni contiene decisiones visuales."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from .auditoria import calcular_huella_archivo, crear_contexto
from .auditoria import resumir_etapa
from .cierres import procesar_cierres
from .configuracion import ConfiguracionProcesamiento, cargar_configuracion_json
from .exportadores import (
    RutasSalida,
    crear_estructura_salida,
    exportar_auditoria_total,
    exportar_cierres,
    exportar_reaperturas,
    exportar_tabla_interna,
)
from .flujo_comun import procesar_flujo_comun
from .lectores import (
    leer_archivo_delimitado,
    leer_libro_reglas,
    leer_matriz_reglas_gio,
    leer_tabla,
)
from .modelos import (
    CategoriaResultado,
    EstadoEtapa,
    ProcesoBloqueadoError,
    ResultadoProceso,
    TablaDatos,
)
from .normalizacion import normalizar_fila, resolver_columnas
from .reaperturas import procesar_reaperturas
from .reglas_provisionales import aplicar_reglas_provisionales
from .reglas_gio import MatrizReglasGio


Progreso = Callable[[str, int, int], None]


@dataclass(frozen=True)
class RutasEntradasActualizacion:
    ruta_csv_sansys: Path
    ruta_control_gio: Path
    ruta_entregable_acumulado: Path
    ruta_libro_reglas: Path
    carpeta_salida: Path
    ruta_matriz_gio: Optional[Path] = None
    configuracion_json: Optional[Path] = None


class ServicioProcesamientoActualizaciones:
    def __init__(self, configuracion: Optional[ConfiguracionProcesamiento] = None):
        self.configuracion = configuracion or ConfiguracionProcesamiento.predeterminada()
        self.resultado: Optional[ResultadoProceso] = None
        self.rutas_salida: Optional[RutasSalida] = None
        self.tabla_lecturas: Optional[TablaDatos] = None
        self.tabla_entregable_actualizado: Optional[TablaDatos] = None
        self.matriz_gio: Optional[MatrizReglasGio] = None

    @staticmethod
    def _notificar(progreso: Optional[Progreso], etapa: str, actual: int, total: int) -> None:
        if progreso:
            progreso(etapa, actual, total)

    @staticmethod
    def _leer_hoja_o_primera(ruta: Path, hoja: str, fila_encabezado: int = 1) -> TablaDatos:
        if ruta.suffix.lower() in {".xlsx", ".xlsm"}:
            try:
                return leer_tabla(ruta, hoja=hoja, fila_encabezado=fila_encabezado)
            except ValueError as error:
                if "No existe la hoja" not in str(error):
                    raise
        return leer_tabla(ruta, fila_encabezado=fila_encabezado)

    @staticmethod
    def _leer_acumulado(ruta: Path, configuracion: ConfiguracionProcesamiento) -> TablaDatos:
        tabla = leer_tabla(ruta)
        encabezados = {encabezado.strip().upper() for encabezado in tabla.encabezados}
        alias_ot = {valor.upper() for valor in configuracion.alias_columnas["OT"]}
        if encabezados & alias_ot:
            return tabla
        columnas = (
            "nis_rad", "OT", "OS", "FEJECUCION", "HI", "HF",
            "ACCION", "CODIGO", "OBSERVACION", "LECT",
        )
        return leer_archivo_delimitado(
            ruta, tiene_encabezado=False, columnas_sin_encabezado=columnas
        )

    @staticmethod
    def _leer_control_gio(ruta: Path) -> TablaDatos:
        if ruta.suffix.lower() not in {".xlsx", ".xlsm"}:
            return leer_tabla(ruta)
        for hoja in ("GIO", "GIO_17092026_PRUEBA_AUTOMATIZAC", "CONTROL GIO"):
            try:
                return leer_tabla(ruta, hoja=hoja)
            except ValueError:
                continue
        return leer_tabla(ruta)

    @staticmethod
    def _leer_sansys(ruta: Path) -> TablaDatos:
        """CSV en producción; permite las hojas históricas solo para validación."""
        if ruta.suffix.lower() not in {".xlsx", ".xlsm"}:
            return leer_tabla(ruta)
        for hoja in ("DATA_GENERAL", "data_general", "DATA GENERAL"):
            try:
                return leer_tabla(ruta, hoja=hoja)
            except ValueError:
                continue
        return leer_tabla(ruta)

    def procesar_flujo_comun(
        self,
        rutas: RutasEntradasActualizacion,
        fecha_procesamiento: str,
        progreso: Optional[Progreso] = None,
    ) -> ResultadoProceso:
        if rutas.configuracion_json:
            self.configuracion = cargar_configuracion_json(rutas.configuracion_json, self.configuracion)
        aplicar_reglas_provisionales(self.configuracion)
        if rutas.ruta_matriz_gio:
            # La matriz Excel sustituye cualquier regla de acción heredada de
            # configuraciones antiguas. Los contratos de salida sí se conservan.
            self.configuracion.reglas_accion = []
            self.configuracion.modo_reglas_provisionales = False
        contexto = crear_contexto(fecha_procesamiento, rutas.carpeta_salida)
        contexto.configuracion_aplicada = self.configuracion.como_diccionario()
        contexto.metadatos_entradas["reglas_provisionales"] = {
            "activas": self.configuracion.modo_reglas_provisionales,
            "cantidad": sum(regla.provisional for regla in self.configuracion.reglas_accion),
            "motivo": (
                "Matriz oficial pendiente; se usan combinaciones observadas en muestras reales."
                if self.configuracion.modo_reglas_provisionales
                else "La matriz Excel cargada es la única fuente de reglas de acción."
            ),
        }
        contexto.cambiar_estado("FLUJO_COMUN", EstadoEtapa.PROCESANDO)
        archivos = {
            "csv_sansys": rutas.ruta_csv_sansys,
            "control_gio": rutas.ruta_control_gio,
            "entregable_acumulado": rutas.ruta_entregable_acumulado,
            "libro_reglas": rutas.ruta_libro_reglas,
        }
        if rutas.ruta_matriz_gio:
            archivos["matriz_reglas_gio"] = rutas.ruta_matriz_gio
        if rutas.configuracion_json:
            archivos["configuracion_json"] = rutas.configuracion_json
        for nombre, ruta in archivos.items():
            if not Path(ruta).is_file():
                raise FileNotFoundError(f"No existe el archivo requerido '{nombre}': {ruta}")
            contexto.entradas[nombre] = str(ruta)
            contexto.huellas[nombre] = calcular_huella_archivo(Path(ruta))

        self._notificar(progreso, "Leyendo CSV SANSYS", 1, 7)
        general = self._leer_sansys(rutas.ruta_csv_sansys)
        self._notificar(progreso, "Leyendo control GIO", 2, 7)
        control = self._leer_control_gio(rutas.ruta_control_gio)
        self._notificar(progreso, "Leyendo entregable acumulado", 3, 7)
        acumulado = self._leer_acumulado(rutas.ruta_entregable_acumulado, self.configuracion)
        self._notificar(progreso, "Leyendo libro de reglas", 4, 7)
        libro = leer_libro_reglas(rutas.ruta_libro_reglas)
        if rutas.ruta_matriz_gio:
            self._notificar(progreso, "Leyendo matriz de reglas GIO", 5, 7)
            self.matriz_gio = leer_matriz_reglas_gio(rutas.ruta_matriz_gio)
            contexto.metadatos_entradas["matriz_reglas_gio"] = {
                "archivo": rutas.ruta_matriz_gio.name,
                "hojas": list(self.matriz_gio.hojas),
                "reglas_activas": len(self.matriz_gio.reglas_activas),
                "reglas_inactivas": len(self.matriz_gio.reglas_inactivas),
                "fecha_modificacion": self.matriz_gio.fecha_modificacion,
                "combinaciones_observadas": len(self.matriz_gio.combinaciones),
            }
        else:
            self.matriz_gio = None
        actividades = libro.actividad
        operarios = libro.operarios
        self.tabla_lecturas = libro.lecturas
        contexto.metadatos_entradas["libro_reglas"] = libro.metadatos
        contexto.metadatos_entradas["csv_sansys"] = {
            "nombre": rutas.ruta_csv_sansys.name,
            "registros_cargados": len(general.filas),
            "formato": general.formato.tipo,
        }
        self._notificar(progreso, "Libro de reglas validado", 6, 7)
        self._notificar(progreso, "Aplicando validaciones comunes", 7, 7)
        flujo = procesar_flujo_comun(
            general, control, acumulado, fecha_procesamiento=fecha_procesamiento,
            configuracion=self.configuracion, tabla_operarios=operarios,
            tabla_actividades=actividades,
        )
        contexto.metadatos_entradas["conversion_operarios"] = {
            "convertidos_sysacao_a_gio": sum(
                fila.datos_normalizados.get("ESTADO_CONVERSION") == "CONVERTIDO_SYSACAO_A_GIO"
                for fila in flujo.registros
            ),
            "conservados_sin_conversion": sum(
                fila.datos_normalizados.get("ESTADO_CONVERSION") == "SIN_CONVERSION_REQUERIDA"
                for fila in flujo.registros
            ),
            "coo_vacios": sum(fila.motivo_final == "COO_VACIO" for fila in flujo.registros),
            "coo_ilegibles": sum(fila.motivo_final == "COO_ILEGIBLE" for fila in flujo.registros),
            "equivalencias_contradictorias": sum(
                fila.motivo_final == "EQUIVALENCIA_SYSACAO_CONTRADICTORIA"
                for fila in flujo.registros
            ),
        }
        contexto.resumenes["FLUJO_COMUN"] = flujo.resumen
        contexto.cambiar_estado(
            "FLUJO_COMUN", EstadoEtapa.CON_ERRORES if flujo.resumen.revisiones else EstadoEtapa.COMPLETADO
        )
        contexto.cambiar_estado("CIERRES", EstadoEtapa.LISTO)
        contexto.cambiar_estado("REAPERTURAS", EstadoEtapa.BLOQUEADO)
        self.rutas_salida = crear_estructura_salida(
            rutas.carpeta_salida, contexto.id_ejecucion, fecha_procesamiento
        )
        exportar_tabla_interna(
            flujo.data_filtrada, self.rutas_salida.data_filtrada,
            "DATA_FILTRADA", contexto.id_ejecucion,
        )
        exportar_tabla_interna(
            [fila for fila in flujo.registros if fila not in flujo.data_filtrada],
            self.rutas_salida.errores_validacion, "VALIDACIONES_COMUNES", contexto.id_ejecucion,
        )
        self.resultado = ResultadoProceso(contexto=contexto, flujo_comun=flujo)
        exportar_auditoria_total(contexto, flujo.registros, self.rutas_salida)
        return self.resultado

    def procesar_cierres(self, progreso: Optional[Progreso] = None) -> ResultadoProceso:
        if not self.resultado or not self.resultado.flujo_comun or not self.rutas_salida:
            raise ProcesoBloqueadoError("Primero debe completar el flujo común.")
        self.resultado.contexto.cambiar_estado("CIERRES", EstadoEtapa.PROCESANDO)
        self._notificar(progreso, "Validando cierres y revisiones", 1, 2)
        cierres = procesar_cierres(
            self.resultado.flujo_comun.data_filtrada,
            configuracion=self.configuracion, tabla_lecturas=self.tabla_lecturas,
            matriz_gio=self.matriz_gio,
        )
        self.resultado.cierres = cierres
        exportar_tabla_interna(
            cierres.revisiones, self.rutas_salida.errores_validacion,
            "REVISIONES_CIERRES", self.resultado.contexto.id_ejecucion,
        )
        exportar_tabla_interna(
            [
                fila for fila in cierres.revisiones
                if fila.motivo_final == "ACCION_SIN_REGLA_CONFIGURADA"
                or fila.datos_normalizados.get("DESTINO_REGLA_GIO") == "ACCION_INVALIDA"
            ],
            self.rutas_salida.accion_invalida, "ACCION_INVALIDA_CIERRES",
            self.resultado.contexto.id_ejecucion,
        )
        exportar_tabla_interna(
            [fila for fila in cierres.revisiones if "LECTURA" in fila.motivo_final],
            self.rutas_salida.revisar_lectura, "REVISAR_LECTURA_CIERRES",
            self.resultado.contexto.id_ejecucion,
        )
        self._notificar(progreso, "Generando archivos de cierres", 2, 2)
        if cierres.listas:
            try:
                sistema, entregable = exportar_cierres(
                    cierres.listas, self.configuracion, self.rutas_salida,
                    self.resultado.contexto.id_ejecucion,
                )
                self.resultado.contexto.archivos_generados["cierres_sistema"] = str(sistema)
                self.resultado.contexto.archivos_generados["entregable_cierres"] = str(entregable)
                self.resultado.contexto.entregable_cierres = str(entregable)
                self.resultado.contexto.cambiar_estado("CIERRES", EstadoEtapa.COMPLETADO)
            except ProcesoBloqueadoError as error:
                cierres.bloqueos.append(str(error))
                self.resultado.contexto.cambiar_estado("CIERRES", EstadoEtapa.BLOQUEADO)
        elif cierres.revisiones:
            self.resultado.contexto.cambiar_estado("CIERRES", EstadoEtapa.CON_ERRORES)
        else:
            self.resultado.contexto.cambiar_estado("CIERRES", EstadoEtapa.COMPLETADO)
        self.resultado.contexto.resumenes["CIERRES"] = resumir_etapa(
            "CIERRES", cierres.entradas
        )
        exportar_auditoria_total(
            self.resultado.contexto, self.resultado.flujo_comun.registros, self.rutas_salida
        )
        return self.resultado

    def marcar_solo_automaticos(
        self,
        ruta_referencia_manual: Path,
        hoja: str = "DATTTAAA_FILTRADA",
    ) -> Path:
        """Marca diferencias de validación sin convertir la referencia manual en regla."""
        if not self.resultado or not self.resultado.flujo_comun or not self.rutas_salida:
            raise ProcesoBloqueadoError("Primero debe completar el flujo común.")
        tabla = leer_tabla(ruta_referencia_manual, hoja=hoja)
        columnas = resolver_columnas(tabla.encabezados, self.configuracion)
        claves_manual = {
            (datos.get("OT", ""), datos.get("OS", ""))
            for datos in (normalizar_fila(fila, columnas) for fila in tabla.filas)
        }
        adicionales = []
        for registro in self.resultado.flujo_comun.data_filtrada:
            if (registro.ot, registro.os) in claves_manual:
                continue
            registro.datos_normalizados["COMPARACION_MANUAL"] = (
                "SOLO_AUTOMATICO_PENDIENTE_COMPARACION"
            )
            registro.registrar(
                "VAL-48", "COMPARACION_MANUAL", CategoriaResultado.CONTINUA,
                "SOLO_AUTOMATICO_PENDIENTE_COMPARACION",
                f"OT={registro.ot}; OS={registro.os}", "Referencia manual no autoritativa",
            )
            adicionales.append(registro)
        ruta = exportar_tabla_interna(
            adicionales, self.rutas_salida.auditoria,
            "SOLO_AUTOMATICO_PENDIENTE_COMPARACION", self.resultado.contexto.id_ejecucion,
        )
        self.resultado.contexto.metadatos_entradas["comparacion_manual"] = {
            "archivo": str(ruta_referencia_manual),
            "hoja": hoja,
            "solo_automaticos": len(adicionales),
            "resultado": "No se excluyen; continúan con las mismas reglas.",
        }
        self.resultado.contexto.archivos_generados["solo_automaticos"] = str(ruta)
        exportar_auditoria_total(
            self.resultado.contexto, self.resultado.flujo_comun.registros, self.rutas_salida
        )
        return ruta

    def cargar_entregable_actualizado(self, ruta: Path) -> TablaDatos:
        if not self.resultado:
            raise ProcesoBloqueadoError("No existe una ejecución activa.")
        if ruta.suffix.lower() in {".xlsx", ".xlsm"}:
            for hoja in ("ENTREGABLE_PARA_REAPERURAS", "ENTREGABLE_PARA_REAPERTURAS", "ENTREGABLE"):
                try:
                    self.tabla_entregable_actualizado = leer_tabla(ruta, hoja=hoja)
                    break
                except ValueError:
                    continue
            else:
                self.tabla_entregable_actualizado = leer_tabla(ruta)
        else:
            tabla = leer_tabla(ruta)
            columnas = resolver_columnas(tabla.encabezados, self.configuracion)
            if {"NIS", "FECHA", "ACC", "LECT"}.issubset(columnas):
                self.tabla_entregable_actualizado = tabla
            else:
                self.tabla_entregable_actualizado = self._leer_acumulado(
                    ruta, self.configuracion
                )
        # La validación profunda se ejecuta dentro de procesar_reaperturas.
        self.resultado.contexto.entregable_actualizado = str(ruta)
        self.resultado.contexto.entradas["entregable_actualizado"] = str(ruta)
        self.resultado.contexto.huellas["entregable_actualizado"] = calcular_huella_archivo(ruta)
        self.resultado.contexto.cambiar_estado("REAPERTURAS", EstadoEtapa.LISTO)
        return self.tabla_entregable_actualizado

    def procesar_reaperturas(self, progreso: Optional[Progreso] = None) -> ResultadoProceso:
        if not self.resultado or not self.resultado.flujo_comun or not self.rutas_salida:
            raise ProcesoBloqueadoError("Primero debe completar el flujo común.")
        self.resultado.contexto.cambiar_estado("REAPERTURAS", EstadoEtapa.PROCESANDO)
        self._notificar(progreso, "Validando reaperturas", 1, 2)
        reaperturas = procesar_reaperturas(
            self.resultado.flujo_comun.data_filtrada, self.tabla_entregable_actualizado,
            configuracion=self.configuracion, matriz_gio=self.matriz_gio,
        )
        self.resultado.reaperturas = reaperturas
        exportar_tabla_interna(
            reaperturas.revisiones, self.rutas_salida.errores_validacion,
            "REVISIONES_REAPERTURAS", self.resultado.contexto.id_ejecucion,
        )
        exportar_tabla_interna(
            [fila for fila in reaperturas.revisiones if fila.motivo_final == "ACCION_INVALIDA"],
            self.rutas_salida.accion_invalida, "ACCION_INVALIDA_REAPERTURAS",
            self.resultado.contexto.id_ejecucion,
        )
        exportar_tabla_interna(
            [fila for fila in reaperturas.revisiones if "LECTURA" in fila.motivo_final],
            self.rutas_salida.revisar_lectura, "REVISAR_LECTURA_REAPERTURAS",
            self.resultado.contexto.id_ejecucion,
        )
        self._notificar(progreso, "Generando archivos de reaperturas", 2, 2)
        if reaperturas.listas:
            try:
                sistema, entregable = exportar_reaperturas(
                    reaperturas.listas, self.configuracion, self.rutas_salida,
                    self.resultado.contexto.id_ejecucion,
                )
                self.resultado.contexto.archivos_generados["reaperturas_sistema"] = str(sistema)
                self.resultado.contexto.archivos_generados["entregable_reaperturas"] = str(entregable)
                self.resultado.contexto.cambiar_estado("REAPERTURAS", EstadoEtapa.COMPLETADO)
            except ProcesoBloqueadoError as error:
                reaperturas.bloqueos.append(str(error))
                self.resultado.contexto.cambiar_estado("REAPERTURAS", EstadoEtapa.BLOQUEADO)
        elif reaperturas.revisiones:
            self.resultado.contexto.cambiar_estado("REAPERTURAS", EstadoEtapa.CON_ERRORES)
        else:
            self.resultado.contexto.cambiar_estado("REAPERTURAS", EstadoEtapa.COMPLETADO)
        self.resultado.contexto.resumenes["REAPERTURAS"] = resumir_etapa(
            "REAPERTURAS", reaperturas.entradas
        )
        exportar_auditoria_total(
            self.resultado.contexto, self.resultado.flujo_comun.registros, self.rutas_salida
        )
        return self.resultado
