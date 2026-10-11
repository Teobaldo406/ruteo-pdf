# -*- coding: utf-8 -*-
"""Coordinador de etapas. No importa PySide6 ni contiene decisiones visuales."""

from __future__ import annotations

from collections import Counter
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
    exportar_cierres,
    exportar_reaperturas,
    exportar_revision_manual_cierres,
    exportar_revision_manual_reaperturas,
)
from .flujo_comun import _crear_registros, procesar_flujo_comun
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
from .normalizacion import normalizar_fecha, normalizar_fila, resolver_columnas
from .reaperturas import procesar_reaperturas
from .reglas_provisionales import aplicar_reglas_provisionales
from .reglas_gio import MatrizReglasGio


Progreso = Callable[[str, int, int], None]


@dataclass(frozen=True)
class RutasEntradasActualizacion:
    ruta_csv_sansys: Path
    ruta_control_gio: Path
    ruta_entregable_acumulado: Optional[Path]
    ruta_libro_reglas: Path
    carpeta_salida: Path
    ruta_matriz_gio: Optional[Path] = None
    configuracion_json: Optional[Path] = None
    considerar_entregable_acumulado: bool = True
    considerar_entregable_actualizado: bool = True
    confirmacion_sin_entregable: bool = False
    modo_c03: bool = False
    ruta_entregable_historico: Optional[Path] = None


class ServicioProcesamientoActualizaciones:
    def __init__(self, configuracion: Optional[ConfiguracionProcesamiento] = None):
        self.configuracion = configuracion or ConfiguracionProcesamiento.predeterminada()
        self.resultado: Optional[ResultadoProceso] = None
        self.rutas_salida: Optional[RutasSalida] = None
        self.tabla_lecturas: Optional[TablaDatos] = None
        self.tabla_entregable_actualizado: Optional[TablaDatos] = None
        self.matriz_gio: Optional[MatrizReglasGio] = None
        self.considerar_entregable_actualizado = True
        self.cantidad_lecturas_sansys = 0
        self.modo_c03 = False
        self._cache_sansys: Optional[tuple[tuple[str, int, int], TablaDatos]] = None

    @staticmethod
    def _notificar(progreso: Optional[Progreso], etapa: str, actual: int, total: int) -> None:
        if progreso:
            progreso(etapa, actual, total)

    @staticmethod
    def _validar_conciliacion(nombre: str, entradas, listas, revisiones, exclusiones) -> dict:
        """Comprueba por ID_FILA y OT+OS que una rama no pierda ni duplique filas."""
        clasificados = [*listas, *revisiones, *exclusiones]
        ids_entrada = Counter(fila.id_fila for fila in entradas)
        ids_salida = Counter(fila.id_fila for fila in clasificados)
        pares_entrada = Counter((fila.ot, fila.os) for fila in entradas)
        pares_salida = Counter((fila.ot, fila.os) for fila in clasificados)
        if ids_entrada != ids_salida or pares_entrada != pares_salida:
            raise RuntimeError(
                f"La conciliación de {nombre} detectó pérdida o duplicación de registros."
            )
        return {
            "entradas": len(entradas),
            "sistema": len(listas),
            "revision": len(revisiones),
            "exclusiones": len(exclusiones),
            "perdidas": 0,
            "duplicados": 0,
        }

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

    def _leer_sansys(self, ruta: Path) -> TablaDatos:
        """CSV en producción; permite las hojas históricas solo para validación."""
        ruta = Path(ruta)
        estado = ruta.stat()
        firma = (str(ruta.resolve()), estado.st_size, estado.st_mtime_ns)
        if self._cache_sansys and self._cache_sansys[0] == firma:
            return self._cache_sansys[1]
        self.cantidad_lecturas_sansys += 1
        if ruta.suffix.lower() not in {".xlsx", ".xlsm"}:
            tabla = leer_tabla(ruta)
            self._cache_sansys = (firma, tabla)
            return tabla
        for hoja in ("DATA_GENERAL", "data_general", "DATA GENERAL"):
            try:
                tabla = leer_tabla(ruta, hoja=hoja)
                self._cache_sansys = (firma, tabla)
                return tabla
            except ValueError:
                continue
        tabla = leer_tabla(ruta)
        self._cache_sansys = (firma, tabla)
        return tabla

    @staticmethod
    def _firma_entradas(rutas: RutasEntradasActualizacion) -> dict[str, str]:
        firma = {
            "csv_sansys": str(Path(rutas.ruta_csv_sansys).resolve()),
            "control_gio": str(Path(rutas.ruta_control_gio).resolve()),
            "libro_reglas": str(Path(rutas.ruta_libro_reglas).resolve()),
            "matriz_gio": str(Path(rutas.ruta_matriz_gio).resolve()) if rutas.ruta_matriz_gio else "",
            "entregable_acumulado": (
                str(Path(rutas.ruta_entregable_acumulado).resolve())
                if rutas.considerar_entregable_acumulado and rutas.ruta_entregable_acumulado
                else "NO_UTILIZADO"
            ),
            "modo_c03": "SI" if rutas.modo_c03 else "NO",
            "entregable_historico": (
                str(Path(rutas.ruta_entregable_historico).resolve())
                if rutas.modo_c03 and rutas.ruta_entregable_historico
                else "NO_UTILIZADO"
            ),
        }
        for clave, valor in list(firma.items()):
            ruta = Path(valor)
            if clave != "modo_c03" and valor != "NO_UTILIZADO" and valor and ruta.exists():
                estado = ruta.stat()
                firma[clave] = f"{ruta}|{estado.st_size}|{estado.st_mtime_ns}"
        return firma

    def contexto_es_vigente(
        self, rutas: RutasEntradasActualizacion, fecha_procesamiento: str
    ) -> bool:
        return bool(
            self.resultado
            and self.resultado.flujo_comun
            and self.resultado.contexto.fecha_procesamiento == normalizar_fecha(fecha_procesamiento)
            and self.resultado.contexto.identidad_entradas == self._firma_entradas(rutas)
        )

    def _fecha_existe_en_general(
        self, tabla: TablaDatos, fecha_procesamiento: str
    ) -> bool:
        fecha_objetivo = normalizar_fecha(fecha_procesamiento)
        # SANSYS puede traer el bloque operativo desplazado y sin encabezados
        # explícitos. Se reutiliza exactamente el mismo detector del flujo común
        # para no rechazar fechas válidas por mirar una columna física equivocada.
        return any(
            registro.datos_normalizados.get("FECHA") == fecha_objetivo
            for registro in _crear_registros(tabla, self.configuracion)
        )

    def procesar_flujo_comun(
        self,
        rutas: RutasEntradasActualizacion,
        fecha_procesamiento: str,
        progreso: Optional[Progreso] = None,
    ) -> ResultadoProceso:
        if rutas.modo_c03 and not rutas.ruta_entregable_historico:
            raise ProcesoBloqueadoError(
                "No se pueden procesar las reaperturas sin el entregable "
                "histórico de cierres anteriores."
            )
        if rutas.modo_c03 and not Path(rutas.ruta_entregable_historico).is_file():
            raise FileNotFoundError(
                f"No existe el entregable histórico: {rutas.ruta_entregable_historico}"
            )
        self.modo_c03 = rutas.modo_c03
        if rutas.configuracion_json:
            self.configuracion = cargar_configuracion_json(rutas.configuracion_json, self.configuracion)
        aplicar_reglas_provisionales(self.configuracion)
        if rutas.ruta_matriz_gio:
            # La matriz Excel sustituye cualquier regla de acción heredada de
            # configuraciones antiguas. Los contratos de salida sí se conservan.
            self.configuracion.reglas_accion = []
            self.configuracion.modo_reglas_provisionales = False
        contexto = crear_contexto(fecha_procesamiento, rutas.carpeta_salida)
        contexto.fecha_procesamiento = normalizar_fecha(fecha_procesamiento)
        contexto.identidad_entradas = self._firma_entradas(rutas)
        self.considerar_entregable_actualizado = rutas.considerar_entregable_actualizado
        contexto.configuracion_aplicada = self.configuracion.como_diccionario()
        contexto.metadatos_entradas["opciones_entregables"] = {
            "considerar_entregable_acumulado": rutas.considerar_entregable_acumulado,
            "archivo_entregable_acumulado": (
                str(rutas.ruta_entregable_acumulado)
                if rutas.considerar_entregable_acumulado and rutas.ruta_entregable_acumulado
                else "NO UTILIZADO"
            ),
            "validacion_entregable_acumulado": (
                "EJECUTADA" if rutas.considerar_entregable_acumulado else "OMITIDA_POR_DECISION_USUARIO"
            ),
            "ENTREGABLE_CIERRES_DIA": (
                "UTILIZADO" if rutas.considerar_entregable_acumulado else "NO_UTILIZADO"
            ),
            "CONFIRMACION_SIN_ENTREGABLE": (
                "SI" if rutas.confirmacion_sin_entregable else "NO"
            ),
            "considerar_entregable_actualizado": rutas.considerar_entregable_actualizado,
            "archivo_entregable_actualizado": "PENDIENTE" if rutas.considerar_entregable_actualizado else "NO UTILIZADO",
            "validacion_entregable_actualizado": (
                "PENDIENTE" if rutas.considerar_entregable_actualizado else "OMITIDA_POR_DECISION_USUARIO"
            ),
        }
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
            "libro_reglas": rutas.ruta_libro_reglas,
        }
        if rutas.considerar_entregable_acumulado and rutas.ruta_entregable_acumulado:
            archivos["entregable_acumulado"] = rutas.ruta_entregable_acumulado
        else:
            contexto.entradas["entregable_acumulado"] = "NO UTILIZADO"
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
        if not self._fecha_existe_en_general(general, fecha_procesamiento):
            raise ValueError(
                "La fecha seleccionada no existe en la data. "
                "Seleccione una fecha disponible."
            )
        self._notificar(progreso, "Leyendo control GIO", 2, 7)
        control = self._leer_control_gio(rutas.ruta_control_gio)
        if rutas.considerar_entregable_acumulado and rutas.ruta_entregable_acumulado:
            self._notificar(progreso, "Leyendo entregable acumulado", 3, 7)
            acumulado = self._leer_acumulado(
                rutas.ruta_entregable_acumulado, self.configuracion
            )
        else:
            self._notificar(progreso, "Omitiendo entregable acumulado", 3, 7)
            acumulado = None
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
                "tipologias_activas": sum(
                    regla.activa for regla in self.matriz_gio.tipologias.reglas
                ) if self.matriz_gio.tipologias else 0,
                "tipologias_inactivas": sum(
                    not regla.activa for regla in self.matriz_gio.tipologias.reglas
                ) if self.matriz_gio.tipologias else 0,
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
            considerar_entregable_acumulado=rutas.considerar_entregable_acumulado,
            confirmacion_sin_entregable=rutas.confirmacion_sin_entregable,
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
        if rutas.modo_c03:
            self._notificar(progreso, "Leyendo entregable histórico", 7, 8)
            self.tabla_entregable_actualizado = self._leer_acumulado(
                Path(rutas.ruta_entregable_historico), self.configuracion
            )
            contexto.entregable_actualizado = str(rutas.ruta_entregable_historico)
            contexto.entradas["entregable_historico"] = str(
                rutas.ruta_entregable_historico
            )
            contexto.huellas["entregable_historico"] = calcular_huella_archivo(
                Path(rutas.ruta_entregable_historico)
            )
            contexto.metadatos_entradas["modo_c03"] = {
                "activo": True,
                "cierres": "NO_APLICA",
                "entregable_cierres_dia": "NO_APLICA",
            }
            contexto.cambiar_estado("CIERRES", EstadoEtapa.COMPLETADO)
            contexto.cambiar_estado("REAPERTURAS", EstadoEtapa.LISTO)
        self.rutas_salida = crear_estructura_salida(
            rutas.carpeta_salida,
            contexto.id_ejecucion,
            fecha_procesamiento,
            incluir_cierres=not rutas.modo_c03,
            crear_reaperturas=not rutas.modo_c03,
        )
        self.resultado = ResultadoProceso(contexto=contexto, flujo_comun=flujo)
        contexto.estado_proceso = "FLUJO_COMUN_COMPLETADO"
        return self.resultado

    def procesar_cierres(self, progreso: Optional[Progreso] = None) -> ResultadoProceso:
        if not self.resultado or not self.resultado.flujo_comun or not self.rutas_salida:
            raise ProcesoBloqueadoError("Primero debe completar el flujo común.")
        self.resultado.contexto.cambiar_estado("CIERRES", EstadoEtapa.PROCESANDO)
        self._notificar(progreso, "Validando cierres y revisiones", 1, 2)
        cierres = procesar_cierres(
            self.resultado.flujo_comun.cierres_preparados,
            configuracion=self.configuracion, tabla_lecturas=self.tabla_lecturas,
            matriz_gio=self.matriz_gio,
        )
        self.resultado.cierres = cierres
        conciliacion = self._validar_conciliacion(
            "CIERRES", cierres.entradas, cierres.listas,
            cierres.revisiones, cierres.exclusiones,
        )
        self.resultado.contexto.metadatos_entradas["conciliacion_cierres"] = conciliacion
        ruta_revision = exportar_revision_manual_cierres(
            cierres.revisiones, self.rutas_salida.cierres, cierres.entradas
        )
        self.resultado.contexto.archivos_generados["revision_cierres"] = str(ruta_revision)
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
        self.resultado.contexto.estado_proceso = "CIERRES_COMPLETADOS"
        return self.resultado

    def marcar_solo_automaticos(
        self,
        ruta_referencia_manual: Path,
        hoja: str = "DATTTAAA_FILTRADA",
    ) -> Path:
        """Marca diferencias de validación sin convertir la referencia manual en regla."""
        if not self.resultado or not self.resultado.flujo_comun or not self.rutas_salida:
            raise ProcesoBloqueadoError("Primero procese la fecha y genere los cierres")
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
        self.resultado.contexto.metadatos_entradas["comparacion_manual"] = {
            "archivo": str(ruta_referencia_manual),
            "hoja": hoja,
            "solo_automaticos": len(adicionales),
            "resultado": "No se excluyen; continúan con las mismas reglas.",
        }
        return self.rutas_salida.raiz

    def cargar_entregable_actualizado(
        self, ruta: Path, progreso: Optional[Progreso] = None
    ) -> TablaDatos:
        if not self.resultado or not self.resultado.cierres:
            raise ProcesoBloqueadoError("Primero procese la fecha y genere los cierres")
        self._notificar(progreso, "Leyendo entregable actualizado", 1, 4)
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
        self._notificar(progreso, "Validando estructura del entregable", 2, 4)
        # La validación profunda se ejecuta dentro de procesar_reaperturas.
        self.resultado.contexto.entregable_actualizado = str(ruta)
        self.resultado.contexto.entradas["entregable_actualizado"] = str(ruta)
        self.resultado.contexto.huellas["entregable_actualizado"] = calcular_huella_archivo(ruta)
        opciones = self.resultado.contexto.metadatos_entradas.setdefault(
            "opciones_entregables", {}
        )
        opciones["considerar_entregable_actualizado"] = True
        opciones["archivo_entregable_actualizado"] = str(ruta)
        opciones["validacion_entregable_actualizado"] = "EJECUTADA"
        self._notificar(progreso, "Preparando reaperturas", 3, 4)
        self.resultado.contexto.cambiar_estado("REAPERTURAS", EstadoEtapa.LISTO)
        self._notificar(progreso, "Entregable actualizado cargado", 4, 4)
        return self.tabla_entregable_actualizado

    def procesar_reaperturas(self, progreso: Optional[Progreso] = None) -> ResultadoProceso:
        if not self.resultado or not self.resultado.flujo_comun or not self.rutas_salida:
            raise ProcesoBloqueadoError("Primero procese la fecha y genere los cierres")
        if not self.resultado.cierres and not self.modo_c03:
            raise ProcesoBloqueadoError("Primero procese la fecha y genere los cierres")
        if self.tabla_entregable_actualizado is None:
            raise ProcesoBloqueadoError(
                "REAPERTURAS BLOQUEADAS: cargue el entregable actualizado de cierres."
            )
        self.resultado.contexto.cambiar_estado("REAPERTURAS", EstadoEtapa.PROCESANDO)
        opciones = self.resultado.contexto.metadatos_entradas.setdefault(
            "opciones_entregables", {}
        )
        opciones["considerar_entregable_actualizado"] = self.considerar_entregable_actualizado
        if not self.considerar_entregable_actualizado:
            opciones["archivo_entregable_actualizado"] = "NO UTILIZADO"
            opciones["validacion_entregable_actualizado"] = "OMITIDA_POR_DECISION_USUARIO"
        self._notificar(progreso, "Preparando REAPERTURAS_PREPARADAS", 1, 4)
        def notificar_filas(etapa: str, actual: int, total: int) -> None:
            if progreso:
                progreso(etapa, total + actual, max(1, total * 2))
        reaperturas = procesar_reaperturas(
            self.resultado.flujo_comun.reaperturas_preparadas,
            self.tabla_entregable_actualizado,
            configuracion=self.configuracion, matriz_gio=self.matriz_gio,
            considerar_entregable_actualizado=True,
            progreso=notificar_filas,
            registros_anteriores=self.resultado.flujo_comun.data_filtrada,
        )
        self.resultado.reaperturas = reaperturas
        conciliacion = self._validar_conciliacion(
            "REAPERTURAS", reaperturas.entradas, reaperturas.listas,
            reaperturas.revisiones, reaperturas.exclusiones,
        )
        self.resultado.contexto.metadatos_entradas["conciliacion_reaperturas"] = conciliacion
        if reaperturas.revisiones or not self.modo_c03:
            ruta_revision = exportar_revision_manual_reaperturas(
                reaperturas.revisiones,
                self.rutas_salida.reaperturas,
                reaperturas.entradas,
            )
            self.resultado.contexto.archivos_generados[
                "reaperturas_revision_manual"
            ] = str(ruta_revision)
        self._notificar(progreso, "Generando archivos de reaperturas", 3, 4)
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
        self.resultado.contexto.estado_proceso = "REAPERTURAS_COMPLETADAS"
        self._notificar(progreso, "Reaperturas finalizadas", 4, 4)
        return self.resultado
