# -*- coding: utf-8 -*-
"""Página PySide6 del módulo Procesamiento de actualizaciones."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, Optional

from PySide6.QtCore import QDate, QThread, QTimer, Qt, QUrl, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QDateEdit, QDialog, QFileDialog, QFrame, QHeaderView,
    QGridLayout, QHBoxLayout, QLabel,
    QMessageBox, QProgressBar, QPushButton, QScrollArea, QTableWidget,
    QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget,
)

from actualizacion_datos.lectores import leer_libro_reglas, leer_matriz_reglas_gio, leer_tabla
from actualizacion_datos.modelos import EstadoEtapa, ResultadoProceso
from actualizacion_datos.reglas_gio import MatrizReglasGio
from actualizacion_datos.servicio import (
    RutasEntradasActualizacion,
    ServicioProcesamientoActualizaciones,
)
from actualizacion_datos.trabajadores import TrabajadorActualizacion


class PaginaProcesamientoActualizaciones(QScrollArea):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.servicio = ServicioProcesamientoActualizaciones()
        self.rutas: Dict[str, str] = {}
        self.hilo: Optional[QThread] = None
        self.trabajador: Optional[TrabajadorActualizacion] = None
        self._al_terminar: Optional[Callable[[object], None]] = None
        self._procesar_cierres_automaticamente = False
        self._procesar_reaperturas_automaticamente = False
        self.modo_c03 = False
        self.matriz_gio_previsualizada: Optional[MatrizReglasGio] = None
        self.errores_matriz_gio: list[str] = []
        self.tabla_reglas_cargadas: Optional[QTableWidget] = None
        self._dialogos: Dict[str, QDialog] = {}
        self._ultimo_resultado: Optional[ResultadoProceso] = None
        self._modo_operacion = ""
        self._clave_archivo_pendiente = ""
        self._ruta_archivo_pendiente: Optional[Path] = None
        self._cambio_opcion_interno = False
        self._confirmacion_sin_entregable = False
        self._cierres_confirmados = False
        self._confirmacion_c03_vigente = False
        self.setObjectName("areaPrincipal")
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setMinimumSize(930, 590)
        self._construir_interfaz()

    def _boton(self, texto: str, accion, primario: bool = False) -> QPushButton:
        boton = QPushButton(texto)
        boton.setObjectName("botonPrimario" if primario else "")
        boton.clicked.connect(accion)
        return boton

    def _seccion(self, principal: QVBoxLayout, titulo: str) -> QVBoxLayout:
        panel = QFrame()
        panel.setObjectName("panel")
        caja = QVBoxLayout(panel)
        caja.setContentsMargins(14, 10, 14, 12)
        caja.setSpacing(7)
        etiqueta = QLabel(titulo)
        etiqueta.setObjectName("tituloPanel")
        cuerpo = QWidget()
        caja.addWidget(etiqueta)
        caja.addWidget(cuerpo)
        principal.addWidget(panel)
        disposicion = QVBoxLayout(cuerpo)
        disposicion.setContentsMargins(0, 0, 0, 0)
        disposicion.setSpacing(7)
        return disposicion

    def _selector_archivo(
        self, disposicion, clave: str, texto: str, opcional: bool = False,
        filtro: str = "Archivos admitidos (*.csv *.txt *.tsv *.xlsx *.xlsm);;Todos (*.*)",
    ) -> None:
        bloque = QFrame()
        bloque.setObjectName("filaSelector")
        bloque.setStyleSheet(
            "QFrame#filaSelector { background:#f8fbfd; border:1px solid #d4e3ee; "
            "border-radius:6px; }"
        )
        fila = QHBoxLayout(bloque)
        fila.setContentsMargins(8, 6, 8, 6)
        fila.setSpacing(10)
        boton = self._boton(
            texto, lambda _marcado=False: self._seleccionar_archivo(clave, filtro)
        )
        boton.setMinimumWidth(230)
        boton.setMaximumWidth(260)
        etiqueta = QLabel("Opcional: sin seleccionar" if opcional else "Sin archivo seleccionado")
        etiqueta.setWordWrap(True)
        etiqueta.setMinimumWidth(360)
        self.etiquetas_ruta[clave] = etiqueta
        self.botones_selector[clave] = boton
        self.bloques_selector[clave] = bloque
        fila.addWidget(boton)
        fila.addWidget(etiqueta, 1)
        disposicion.addWidget(bloque)

    def _construir_interfaz(self) -> None:
        lienzo, central = QWidget(), QWidget()
        lienzo.setStyleSheet("background:#eef4f8;")
        central.setObjectName("contenedorCentral")
        central.setStyleSheet("""
            QWidget#contenedorCentral { color:#17365d; }
            QFrame#tarjeta, QFrame#tarjetaVerde, QFrame#tarjetaAzul,
            QFrame#tarjetaGris, QFrame#panelEstado {
                background:#ffffff; border:1px solid #b9d2e8; border-radius:8px;
            }
            QFrame#tarjetaVerde { border-color:#49ad69; }
            QFrame#tarjetaGris { background:#f5f7f9; }
            QLabel#tituloTarjeta { font-size:14px; font-weight:700; color:#174d76; }
            QLabel#tituloVerde { font-size:14px; font-weight:700; color:#13783b; }
            QLabel#tituloGris { font-size:14px; font-weight:700; color:#66717e; }
            QPushButton { min-height:28px; padding:3px 9px; border:1px solid #9fb9cf;
                border-radius:5px; background:#ffffff; color:#17365d; }
            QPushButton:hover { background:#edf6fd; border-color:#2785c2; }
            QPushButton#botonPrimario { background:#087fc5; color:white;
                border-color:#0870af; font-weight:700; min-height:31px; }
            QPushButton:disabled { background:#e3e7eb; color:#929aa3; border-color:#ccd2d8; }
            QProgressBar { border:1px solid #a8bfce; border-radius:4px; height:12px;
                text-align:center; background:#eef3f7; }
            QProgressBar::chunk { background:#19a25b; border-radius:3px; }
        """)
        exterior = QHBoxLayout(lienzo)
        exterior.setContentsMargins(16, 10, 16, 12)
        exterior.addWidget(central)
        self.setWidget(lienzo)
        principal = QVBoxLayout(central)
        principal.setContentsMargins(0, 0, 0, 0)
        principal.setSpacing(8)

        encabezado = QFrame()
        encabezado.setObjectName("encabezadoActualizaciones")
        encabezado.setMaximumHeight(96)
        encabezado.setStyleSheet("""
            QFrame#encabezadoActualizaciones { background:qlineargradient(x1:0,y1:0,x2:1,y2:0,
                stop:0 #ffffff, stop:0.62 #f5fbff, stop:1 #1388ca);
                border:1px solid #8dbad8; border-radius:8px; }
            QLabel#titulo { color:#102f55; font-size:22px; font-weight:800; background:transparent; }
            QLabel#subtitulo { color:#244b70; font-size:13px; background:transparent; }
        """)
        caja_encabezado = QVBoxLayout(encabezado)
        caja_encabezado.setContentsMargins(17, 8, 17, 8)
        caja_encabezado.setSpacing(1)
        titulo = QLabel("ACTUALIZACIÓN AUTOMÁTICA")
        titulo.setObjectName("titulo")
        subtitulo = QLabel("Panel de control del procesamiento operativo")
        subtitulo.setObjectName("subtitulo")
        caja_encabezado.addWidget(titulo)
        caja_encabezado.addWidget(subtitulo)
        self.indicador_modo_c03 = QLabel(
            "MODO C03 ACTIVO — Solo procesamiento de reaperturas"
        )
        self.indicador_modo_c03.setStyleSheet(
            "background:#fff3cd; color:#7a4d00; border:1px solid #dcae35; "
            "border-radius:4px; padding:3px 8px; font-weight:700;"
        )
        self.indicador_modo_c03.hide()
        caja_encabezado.addWidget(self.indicador_modo_c03)
        principal.addWidget(encabezado)

        cuerpo = QHBoxLayout()
        cuerpo.setSpacing(12)
        columna_flujo = QVBoxLayout()
        columna_flujo.setSpacing(10)
        cuerpo.addLayout(columna_flujo, 5)

        tarjeta_flujo = QFrame()
        tarjeta_flujo.setObjectName("tarjeta")
        caja_flujo = QVBoxLayout(tarjeta_flujo)
        caja_flujo.setContentsMargins(11, 8, 11, 9)
        caja_flujo.setSpacing(5)
        titulo_flujo = QLabel("▣  Flujo común hasta DATA_FILTRADA")
        titulo_flujo.setObjectName("tituloTarjeta")
        caja_flujo.addWidget(titulo_flujo)
        pasos = QHBoxLayout()
        pasos.setSpacing(5)
        self.etiquetas_etapa = {}
        nombres = (
            ("CARGA", "Cargar\narchivos"),
            ("NORMALIZACION", "Preparar CSV\nSANSYS"),
            ("FLUJO_COMUN", "Fecha y\nOT–OS"),
            ("DATA_FILTRADA", "DATA FILTRADA"),
        )
        for indice, (clave, nombre) in enumerate(nombres):
            etiqueta = QLabel(f"{nombre}\nPENDIENTE")
            etiqueta.setAlignment(Qt.AlignmentFlag.AlignCenter)
            etiqueta.setMinimumHeight(55)
            etiqueta.setStyleSheet(self._estilo_estado(EstadoEtapa.PENDIENTE))
            pasos.addWidget(etiqueta, 1)
            self.etiquetas_etapa[clave] = etiqueta
            if indice < len(nombres) - 1:
                flecha = QLabel("➜")
                flecha.setStyleSheet("color:#1ba45a; font-size:18px; font-weight:700;")
                pasos.addWidget(flecha)
        caja_flujo.addLayout(pasos)
        self.boton_cargar_archivos = self._boton(
            "Cargar archivos y ejecutar flujo común", self._abrir_dialogo_carga, True
        )
        caja_flujo.addWidget(self.boton_cargar_archivos)
        columna_flujo.addWidget(tarjeta_flujo, 2)

        ramas = QHBoxLayout()
        ramas.setSpacing(12)
        tarjeta_cierres = self._crear_tarjeta_rama(
            "▤  CIERRES · C / CD / V", "CIERRES", EstadoEtapa.PENDIENTE,
            "Abrir procesamiento de cierres", self._abrir_dialogo_cierres, "tarjetaVerde",
        )
        ramas.addWidget(tarjeta_cierres, 1)
        tarjeta_entregable = self._crear_tarjeta_rama(
            "▣  ENTREGABLE ACTUALIZADO", "ENTREGABLE", EstadoEtapa.BLOQUEADO,
            "Cargar entregable actualizado", self._abrir_dialogo_entregable, "tarjetaAzul",
        )
        ramas.addWidget(tarjeta_entregable, 1)
        tarjeta_reaperturas = self._crear_tarjeta_rama(
            "▣  REAPERTURAS · R / RD", "REAPERTURAS", EstadoEtapa.BLOQUEADO,
            "Abrir procesamiento de reaperturas", self._abrir_dialogo_reaperturas, "tarjetaGris",
        )
        ramas.addWidget(tarjeta_reaperturas, 1)
        columna_flujo.addLayout(ramas, 3)

        self.progreso = QProgressBar()
        self.progreso.setRange(0, 100)
        self.etiqueta_estado = QLabel("Estado: listo")
        columna_flujo.addWidget(self.etiqueta_estado)
        columna_flujo.addWidget(self.progreso)

        panel_estado = QFrame()
        panel_estado.setObjectName("panelEstado")
        panel_estado.setMinimumWidth(245)
        panel_estado.setMaximumWidth(300)
        lateral = QVBoxLayout(panel_estado)
        lateral.setContentsMargins(10, 9, 10, 9)
        lateral.setSpacing(6)
        titulo_estado = QLabel("▥  Resumen del proceso")
        titulo_estado.setObjectName("tituloTarjeta")
        lateral.addWidget(titulo_estado)
        self.texto_resumen = QTextEdit()
        self.texto_resumen.setReadOnly(True)
        self.texto_resumen.setMinimumHeight(125)
        self.texto_resumen.setPlainText(
            "Filas cargadas: 0\nDATA_FILTRADA: 0\nCierres listos: 0\n"
            "Reaperturas listas: 0\nRevisiones: 0"
        )
        lateral.addWidget(self.texto_resumen, 1)
        self.boton_ver_reglas_principal = self._boton("Reglas cargadas", self._ver_reglas_cargadas)
        self.boton_revisiones = self._boton("Revisiones y errores", self._abrir_dialogo_revisiones)
        self.boton_resultados = self._boton("Resultados", self._abrir_dialogo_resultados)
        lateral.addWidget(self.boton_ver_reglas_principal)
        lateral.addWidget(self.boton_revisiones)
        lateral.addWidget(self.boton_resultados)
        aviso = QLabel("Las reaperturas permanecen bloqueadas hasta validar el entregable actualizado.")
        aviso.setWordWrap(True)
        aviso.setStyleSheet("background:#fff5cf; border:1px solid #e5bd45; border-radius:5px; padding:7px; color:#70510a;")
        lateral.addWidget(aviso)
        cuerpo.addWidget(panel_estado, 1)
        principal.addLayout(cuerpo, 1)

        self._construir_dialogos()
        self.boton_cierres.setEnabled(False)
        self.boton_entregable.setEnabled(False)
        self.boton_reaperturas.setEnabled(False)
        self.boton_cancelar.setEnabled(False)
        self.boton_abrir.setEnabled(False)
        self.boton_ver_reglas_principal.setEnabled(False)

    def _crear_tarjeta_rama(
        self, titulo: str, clave: str, estado: EstadoEtapa, texto_boton: str,
        accion, nombre_objeto: str,
    ) -> QFrame:
        tarjeta = QFrame()
        tarjeta.setObjectName(nombre_objeto)
        caja = QVBoxLayout(tarjeta)
        caja.setContentsMargins(10, 9, 10, 9)
        etiqueta_titulo = QLabel(titulo)
        etiqueta_titulo.setObjectName("tituloVerde" if clave == "CIERRES" else "tituloGris")
        caja.addWidget(etiqueta_titulo)
        textos = {
            "CIERRES": "Validar horas, acciones, lecturas y operarios",
            "ENTREGABLE": "Paso obligatorio antes de procesar reaperturas",
            "REAPERTURAS": "Cruzar cierre anterior, acción y diferencia",
        }
        detalle = QLabel(textos[clave])
        detalle.setWordWrap(True)
        detalle.setStyleSheet("color:#66717e;")
        caja.addWidget(detalle)
        etiqueta_estado = QLabel(f"{clave}\n{estado.value}")
        etiqueta_estado.setAlignment(Qt.AlignmentFlag.AlignCenter)
        etiqueta_estado.setStyleSheet(self._estilo_estado(estado))
        self.etiquetas_etapa[clave] = etiqueta_estado
        caja.addWidget(etiqueta_estado)
        boton = self._boton(texto_boton, accion, clave == "CIERRES")
        caja.addWidget(boton)
        if clave == "CIERRES":
            self.boton_abrir_dialogo_cierres = boton
        elif clave == "ENTREGABLE":
            self.boton_abrir_dialogo_entregable = boton
        else:
            self.boton_abrir_dialogo_reaperturas = boton
        return tarjeta

    def _nuevo_dialogo(self, clave: str, titulo: str, ancho: int, alto: int, modal: bool) -> tuple[QDialog, QVBoxLayout]:
        dialogo = QDialog(self)
        dialogo.setObjectName(f"dialogo_{clave}")
        dialogo.setWindowTitle(titulo)
        dialogo.resize(ancho, alto)
        dialogo.setModal(True)
        dialogo.setStyleSheet(self.widget().findChild(QWidget, "contenedorCentral").styleSheet())
        disposicion = QVBoxLayout(dialogo)
        disposicion.setContentsMargins(14, 12, 14, 12)
        disposicion.setSpacing(7)
        self._dialogos[clave] = dialogo
        return dialogo, disposicion

    def _construir_dialogos(self) -> None:
        self._construir_dialogo_carga()
        self._construir_dialogo_carga_archivo()
        self._construir_dialogo_progreso_proceso()
        self._construir_dialogo_reglas()
        self._construir_dialogo_cierres()
        self._construir_dialogo_entregable()
        self._construir_dialogo_reaperturas()
        self._construir_dialogo_revisiones()
        self._construir_dialogo_resultados()

    def _construir_dialogo_carga(self) -> None:
        _, caja = self._nuevo_dialogo("carga", "Cargar archivos", 900, 610, True)
        introduccion = QLabel("Seleccione las entradas necesarias para el procesamiento.")
        introduccion.setStyleSheet("color:#526b7d;")
        caja.addWidget(introduccion)
        self.etiquetas_ruta = {}
        self.botones_selector: Dict[str, QPushButton] = {}
        self.bloques_selector: Dict[str, QFrame] = {}

        caja.addWidget(self._titulo_grupo_dialogo("ENTRADAS PRINCIPALES"))
        entradas = QVBoxLayout()
        entradas.setSpacing(5)
        self._selector_archivo(entradas, "csv_sansys", "Seleccionar CSV SANSYS", filtro="CSV SANSYS (*.csv);;Muestra de comparación (*.xlsx *.xlsm);;Todos (*.*)")
        self._selector_archivo(entradas, "control_gio", "Seleccionar control GIO")
        self._selector_archivo(entradas, "entregable_acumulado", "Seleccionar entregable acumulado")
        self._selector_archivo(
            entradas,
            "entregable_historico",
            "Seleccionar entregable histórico de cierres",
        )
        self.bloques_selector["entregable_historico"].hide()
        fila_opcion_acumulado = QHBoxLayout()
        self.opcion_entregable_acumulado = QCheckBox(
            "Usar entregable acumulado (desmarque para desactivar)"
        )
        self.opcion_entregable_acumulado.setChecked(True)
        self.estado_opcion_entregable_acumulado = QLabel("ACTIVO")
        self.estado_opcion_entregable_acumulado.setStyleSheet(
            "color:#167544; font-weight:700;"
        )
        self.opcion_entregable_acumulado.toggled.connect(
            self._alternar_entregable_acumulado
        )
        fila_opcion_acumulado.addWidget(self.opcion_entregable_acumulado)
        fila_opcion_acumulado.addStretch()
        fila_opcion_acumulado.addWidget(self.estado_opcion_entregable_acumulado)
        self.fila_opcion_acumulado = fila_opcion_acumulado
        self.widget_opcion_acumulado = QWidget()
        self.widget_opcion_acumulado.setLayout(fila_opcion_acumulado)
        entradas.addWidget(self.widget_opcion_acumulado)
        caja.addLayout(entradas)

        caja.addWidget(self._titulo_grupo_dialogo("REGLAS"))
        reglas = QVBoxLayout()
        reglas.setSpacing(5)
        self._selector_archivo(reglas, "libro_reglas", "Seleccionar libro de reglas y actualización", filtro="Libro de reglas y actualización (*.xlsx *.xlsm);;Todos (*.*)")
        self._selector_archivo(reglas, "matriz_gio", "Seleccionar matriz de reglas GIO", filtro="Matriz de reglas GIO (*.xlsx *.xlsm);;Todos (*.*)")
        caja.addLayout(reglas)

        caja.addWidget(self._titulo_grupo_dialogo("SALIDA"))
        salida = QFrame()
        salida.setObjectName("filaSelector")
        salida.setStyleSheet(
            "QFrame#filaSelector { background:#f8fbfd; border:1px solid #d4e3ee; "
            "border-radius:6px; }"
        )
        fila_fecha = QHBoxLayout(salida)
        fila_fecha.setContentsMargins(8, 6, 8, 6)
        fila_fecha.setSpacing(10)
        fila_fecha.addWidget(QLabel("Fecha:"))
        self.fecha = QDateEdit(QDate.currentDate())
        self.fecha.setCalendarPopup(True)
        self.fecha.setDisplayFormat("dd/MM/yyyy")
        fila_fecha.addWidget(self.fecha)
        self.boton_salida = self._boton("Seleccionar carpeta de salida", self._seleccionar_salida)
        self.etiqueta_salida = QLabel("Sin carpeta seleccionada")
        self.etiqueta_salida.setWordWrap(True)
        fila_fecha.addWidget(self.boton_salida)
        fila_fecha.addWidget(self.etiqueta_salida, 1)
        caja.addWidget(salida)
        fila = QHBoxLayout()
        self.boton_ver_reglas = self._boton("VER REGLAS CARGADAS", self._ver_reglas_cargadas)
        self.boton_ver_reglas.setEnabled(False)
        self.boton_flujo = self._boton("PROCESAR Y GENERAR CIERRES", self._iniciar_flujo_comun, True)
        self.boton_cancelar = self._boton("Cancelar", self._cancelar)
        fila.addWidget(self.boton_ver_reglas)
        fila.addStretch()
        fila.addWidget(self.boton_cancelar)
        fila.addWidget(self.boton_flujo)
        caja.addLayout(fila)

    @staticmethod
    def _titulo_grupo_dialogo(texto: str) -> QLabel:
        etiqueta = QLabel(texto)
        etiqueta.setStyleSheet(
            "color:#174d76; font-weight:700; font-size:11px; padding-top:3px;"
        )
        return etiqueta

    def _construir_dialogo_carga_archivo(self) -> None:
        dialogo, caja = self._nuevo_dialogo(
            "carga_archivo", "Cargando archivo", 520, 210, True
        )
        dialogo.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, False)
        self.etiqueta_archivo_cargando = QLabel("Preparando carga...")
        self.etiqueta_archivo_cargando.setObjectName("tituloTarjeta")
        self.etiqueta_archivo_cargando.setWordWrap(True)
        self.etiqueta_estado_carga_archivo = QLabel("Leyendo archivo...")
        self.progreso_carga_archivo = QProgressBar()
        self.progreso_carga_archivo.setRange(0, 0)
        self.boton_cancelar_carga_archivo = self._boton("Cancelar", self._cancelar)
        self.boton_cancelar_carga_archivo.setEnabled(False)
        caja.addWidget(self.etiqueta_archivo_cargando)
        caja.addWidget(self.etiqueta_estado_carga_archivo)
        caja.addWidget(self.progreso_carga_archivo)
        caja.addWidget(self.boton_cancelar_carga_archivo)

    def _construir_dialogo_progreso_proceso(self) -> None:
        dialogo, caja = self._nuevo_dialogo(
            "progreso_proceso", "Procesando actualizaciones", 570, 235, True
        )
        dialogo.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, False)
        titulo = QLabel("El aplicativo está trabajando")
        titulo.setObjectName("tituloTarjeta")
        self.etiqueta_etapa_proceso = QLabel("Preparando datos...")
        self.etiqueta_etapa_proceso.setWordWrap(True)
        self.progreso_proceso = QProgressBar()
        self.progreso_proceso.setRange(0, 100)
        self.etiqueta_porcentaje_proceso = QLabel("0 %")
        self.etiqueta_porcentaje_proceso.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.boton_cancelar_proceso = self._boton("Cancelar", self._cancelar)
        self.boton_cancelar_proceso.setEnabled(False)
        caja.addWidget(titulo)
        caja.addWidget(self.etiqueta_etapa_proceso)
        caja.addWidget(self.progreso_proceso)
        caja.addWidget(self.etiqueta_porcentaje_proceso)
        caja.addWidget(self.boton_cancelar_proceso)

    def _construir_dialogo_reglas(self) -> None:
        _, caja = self._nuevo_dialogo("reglas", "Reglas GIO cargadas", 900, 560, True)
        self.etiqueta_resumen_reglas = QLabel("Cargue primero una matriz GIO válida.")
        caja.addWidget(self.etiqueta_resumen_reglas)
        self.tabla_reglas_cargadas = QTableWidget(0, 9)
        self.tabla_reglas_cargadas.setHorizontalHeaderLabels(("ID_REGLA", "PRIORIDAD", "RGLA", "PATRON_OBS", "CONDICION_ACC", "ACCIÓN / RANGO", "RESULTADO", "DESTINO", "ACTIVO"))
        self.tabla_reglas_cargadas.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tabla_reglas_cargadas.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        caja.addWidget(self.tabla_reglas_cargadas)

    def _construir_dialogo_cierres(self) -> None:
        _, caja = self._nuevo_dialogo("cierres", "Procesar cierres", 640, 330, True)
        caja.addWidget(QLabel("Ejecución de cierres C, CD y V"))
        self.etiqueta_contadores_cierres = QLabel("Entradas: 0   |   Listos: 0   |   Revisiones: 0")
        caja.addWidget(self.etiqueta_contadores_cierres)
        self.etiqueta_progreso_cierres = QLabel("Estado: pendiente")
        self.progreso_cierres = QProgressBar()
        self.progreso_cierres.setRange(0, 100)
        caja.addWidget(self.etiqueta_progreso_cierres)
        caja.addWidget(self.progreso_cierres)
        fila = QHBoxLayout()
        self.boton_cierres = self._boton("PROCESAR CIERRES", self._iniciar_cierres, True)
        self.boton_cancelar_cierres = self._boton("Cancelar", self._cancelar)
        self.boton_cancelar_cierres.setEnabled(False)
        fila.addWidget(self.boton_cancelar_cierres)
        fila.addWidget(self.boton_cierres, 1)
        caja.addLayout(fila)

    def _construir_dialogo_entregable(self) -> None:
        _, caja = self._nuevo_dialogo("entregable", "Cargar entregable actualizado", 590, 230, True)
        explicacion = QLabel("Antes de procesar reaperturas, actualice los cierres en el sistema y cargue el entregable actualizado.")
        explicacion.setWordWrap(True)
        caja.addWidget(explicacion)
        self.opcion_entregable_actualizado = QCheckBox(
            "Usar entregable actualizado (obligatorio para reaperturas)"
        )
        self.opcion_entregable_actualizado.setChecked(True)
        self.estado_opcion_entregable_actualizado = QLabel("ACTIVO")
        self.estado_opcion_entregable_actualizado.setStyleSheet(
            "color:#167544; font-weight:700;"
        )
        self.opcion_entregable_actualizado.toggled.connect(
            self._alternar_entregable_actualizado
        )
        fila_opcion = QHBoxLayout()
        fila_opcion.addWidget(self.opcion_entregable_actualizado)
        fila_opcion.addStretch()
        fila_opcion.addWidget(self.estado_opcion_entregable_actualizado)
        caja.addLayout(fila_opcion)
        self.boton_entregable = self._boton("Seleccionar y validar entregable actualizado", self._iniciar_carga_entregable, True)
        caja.addWidget(self.boton_entregable)

    def _construir_dialogo_reaperturas(self) -> None:
        _, caja = self._nuevo_dialogo("reaperturas", "Procesar reaperturas", 640, 330, True)
        caja.addWidget(QLabel("Ejecución de reaperturas R y RD"))
        self.etiqueta_contadores_reaperturas = QLabel("Entradas: 0   |   Listas: 0   |   Revisiones: 0")
        caja.addWidget(self.etiqueta_contadores_reaperturas)
        self.etiqueta_progreso_reaperturas = QLabel("Estado: bloqueado")
        self.progreso_reaperturas = QProgressBar()
        self.progreso_reaperturas.setRange(0, 100)
        caja.addWidget(self.etiqueta_progreso_reaperturas)
        caja.addWidget(self.progreso_reaperturas)
        fila = QHBoxLayout()
        self.boton_reaperturas = self._boton("PROCESAR REAPERTURAS", self._iniciar_reaperturas, True)
        self.boton_cancelar_reaperturas = self._boton("Cancelar", self._cancelar)
        self.boton_cancelar_reaperturas.setEnabled(False)
        fila.addWidget(self.boton_cancelar_reaperturas)
        fila.addWidget(self.boton_reaperturas, 1)
        caja.addLayout(fila)

    def _construir_dialogo_revisiones(self) -> None:
        _, caja = self._nuevo_dialogo("revisiones", "Revisiones y errores", 920, 560, True)
        self.tabla = QTableWidget(0, 0)
        self.tabla.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tabla.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        caja.addWidget(self.tabla)

    def _construir_dialogo_resultados(self) -> None:
        _, caja = self._nuevo_dialogo("resultados", "Resultados", 680, 400, True)
        self.texto_resultados = QTextEdit()
        self.texto_resultados.setReadOnly(True)
        self.texto_resultados.setPlainText("Aún no se han generado archivos.")
        caja.addWidget(self.texto_resultados)
        self.boton_abrir = self._boton("Abrir carpeta de resultados", self._abrir_resultados, True)
        caja.addWidget(self.boton_abrir)

    def _mostrar_dialogo(self, clave: str) -> None:
        dialogo = self._dialogos[clave]
        if dialogo.isVisible():
            dialogo.raise_()
            dialogo.activateWindow()
            return
        referencia = self.window().frameGeometry()
        geometria = dialogo.frameGeometry()
        geometria.moveCenter(referencia.center())
        dialogo.move(geometria.topLeft())
        dialogo.open() if dialogo.isModal() else dialogo.show()

    def _abrir_dialogo_carga(self) -> None:
        if (
            self._ultimo_resultado
            and self._ultimo_resultado.cierres is not None
            and not self.hilo
        ):
            self.opcion_entregable_acumulado.setChecked(True)
            self.opcion_entregable_actualizado.setChecked(True)
        self._mostrar_dialogo("carga")

    def _alternar_entregable_acumulado(self, activo: bool) -> None:
        if not activo and not self._cambio_opcion_interno:
            confirmado = self._confirmar_accion(
                "Desactivar control de actualizados del día",
                "ATENCIÓN\n\nEstá desactivando el control de registros actualizados "
                "del día.\n\nEl sistema no podrá identificar los cierres o "
                "imposibilidades que ya fueron actualizados y asumirá que todos "
                "los registros continúan pendientes. Esto podría hacer que un "
                "registro ya actualizado vuelva a incluirse en el procesamiento.\n\n"
                "¿Está seguro de que desea desactivar esta validación?",
                "Sí, desactivar",
                "No, mantener activada",
                critica=True,
            )
            if not confirmado:
                self._cambio_opcion_interno = True
                self.opcion_entregable_acumulado.setChecked(True)
                self._cambio_opcion_interno = False
                return
            self.rutas.pop("entregable_acumulado", None)
            self._confirmacion_sin_entregable = True
        elif activo:
            self._confirmacion_sin_entregable = False
        self.estado_opcion_entregable_acumulado.setText(
            "ACTIVO" if activo else "DESACTIVADO"
        )
        self.estado_opcion_entregable_acumulado.setStyleSheet(
            "color:#167544; font-weight:700;"
            if activo
            else "color:#9a3412; font-weight:700;"
        )
        boton = self.botones_selector.get("entregable_acumulado")
        etiqueta = self.etiquetas_ruta.get("entregable_acumulado")
        if boton:
            boton.setEnabled(activo)
        if etiqueta:
            etiqueta.setEnabled(activo)
            if not activo:
                etiqueta.setText("NO UTILIZADO")
            elif self.rutas.get("entregable_acumulado"):
                ruta = Path(self.rutas["entregable_acumulado"])
                etiqueta.setText(f"✓ {ruta.name}")
            else:
                etiqueta.setText("Ningún archivo seleccionado")

    def _alternar_entregable_actualizado(self, activo: bool) -> None:
        if not activo:
            self._cambio_opcion_interno = True
            self.opcion_entregable_actualizado.setChecked(True)
            self._cambio_opcion_interno = False
            QMessageBox.warning(
                self,
                "Entregable obligatorio",
                "El entregable actualizado es obligatorio para localizar el cierre "
                "anterior de las reaperturas y no puede desactivarse.",
            )
            return
        self.estado_opcion_entregable_actualizado.setText(
            "ACTIVO" if activo else "DESACTIVADO"
        )
        self.estado_opcion_entregable_actualizado.setStyleSheet(
            "color:#167544; font-weight:700;"
            if activo
            else "color:#9a3412; font-weight:700;"
        )
        cierres_disponibles = bool(
            self._ultimo_resultado and self._ultimo_resultado.cierres
        )
        self.boton_entregable.setEnabled(activo and cierres_disponibles)
        self.servicio.considerar_entregable_actualizado = activo
        if cierres_disponibles:
            self._cambiar_etapa(
                "ENTREGABLE",
                EstadoEtapa.LISTO if activo else EstadoEtapa.COMPLETADO,
            )
            self._cambiar_etapa("REAPERTURAS", EstadoEtapa.LISTO)
            self.boton_reaperturas.setEnabled(True)

    def _confirmar_accion(
        self, titulo: str, texto: str, texto_confirmar: str, texto_cancelar: str,
        *, critica: bool = False,
    ) -> bool:
        mensaje = QMessageBox(self)
        mensaje.setWindowTitle(titulo)
        mensaje.setText(texto)
        mensaje.setIcon(
            QMessageBox.Icon.Warning if critica else QMessageBox.Icon.Question
        )
        boton_confirmar = mensaje.addButton(
            texto_confirmar, QMessageBox.ButtonRole.AcceptRole
        )
        boton_cancelar = mensaje.addButton(
            texto_cancelar, QMessageBox.ButtonRole.RejectRole
        )
        mensaje.setDefaultButton(boton_cancelar)
        mensaje.setEscapeButton(boton_cancelar)
        mensaje.exec()
        return mensaje.clickedButton() is boton_confirmar

    def mostrar_ajustes(self) -> None:
        """Abre la configuración de sesión sin persistir el Modo C03."""
        dialogo = self._dialogos.get("ajustes")
        if dialogo is None:
            dialogo, caja = self._nuevo_dialogo(
                "ajustes", "Ajustes", 470, 210, True
            )
            titulo = QLabel("Configuración del procesamiento")
            titulo.setObjectName("tituloTarjeta")
            self.interruptor_modo_c03 = QCheckBox("Modo C03")
            self.interruptor_modo_c03.setChecked(False)
            self.interruptor_modo_c03.toggled.connect(self._solicitar_cambio_modo_c03)
            explicacion = QLabel(
                "Procesa todas las reaperturas de la fecha y omite el flujo de cierres."
            )
            explicacion.setWordWrap(True)
            explicacion.setStyleSheet("color:#526b7d;")
            cerrar = self._boton("Cerrar", dialogo.accept)
            caja.addWidget(titulo)
            caja.addWidget(self.interruptor_modo_c03)
            caja.addWidget(explicacion)
            caja.addStretch()
            caja.addWidget(cerrar)
        self._mostrar_dialogo("ajustes")

    def _solicitar_cambio_modo_c03(self, activar: bool) -> None:
        if self._cambio_opcion_interno or activar == self.modo_c03:
            return
        if activar:
            confirmado = self._confirmar_accion(
                "ATENCIÓN — ACTIVAR MODO C03",
                "ATENCIÓN — ACTIVAR MODO C03\n\nEste modo omitirá completamente "
                "el procesamiento de cierres y procesará todas las reaperturas de "
                "la fecha seleccionada.\n\nEl entregable histórico/acumulado será "
                "obligatorio para localizar los cierres anteriores.\n\n¿Está seguro "
                "de que desea activar este modo?",
                "Sí, activar",
                "No, mantener modo normal",
                critica=True,
            )
        else:
            confirmado = self._confirmar_accion(
                "Volver al modo normal",
                "¿Desea volver al procesamiento completo de cierres y reaperturas?",
                "Sí, volver al modo normal",
                "No, mantener Modo C03",
            )
        if not confirmado:
            self._cambio_opcion_interno = True
            self.interruptor_modo_c03.setChecked(self.modo_c03)
            self._cambio_opcion_interno = False
            return
        self._aplicar_modo_c03(activar)

    def _aplicar_modo_c03(self, activo: bool) -> None:
        self.modo_c03 = activo
        self.indicador_modo_c03.setVisible(activo)
        self.bloques_selector["entregable_acumulado"].setVisible(not activo)
        self.widget_opcion_acumulado.setVisible(not activo)
        self.bloques_selector["entregable_historico"].setVisible(activo)
        self.boton_flujo.setText(
            "PROCESAR REAPERTURAS" if activo else "PROCESAR Y GENERAR CIERRES"
        )
        self.boton_cargar_archivos.setText(
            "Cargar archivos y procesar reaperturas"
            if activo
            else "Cargar archivos y ejecutar flujo común"
        )
        if activo:
            self.etiquetas_etapa["CIERRES"].setText(
                "CIERRES: NO APLICA\nModo C03"
            )
            self.etiquetas_etapa["CIERRES"].setStyleSheet(
                self._estilo_estado(EstadoEtapa.COMPLETADO)
            )
            self.etiquetas_etapa["ENTREGABLE"].setText(
                "ENTREGABLE DEL DÍA\nNO APLICA"
            )
            self.boton_abrir_dialogo_cierres.setEnabled(False)
            self.boton_abrir_dialogo_entregable.setEnabled(False)
        else:
            self.etiquetas_etapa["CIERRES"].setText("CIERRES\nPENDIENTE")
            self.etiquetas_etapa["CIERRES"].setStyleSheet(
                self._estilo_estado(EstadoEtapa.PENDIENTE)
            )
            self.etiquetas_etapa["ENTREGABLE"].setText("ENTREGABLE\nBLOQUEADO")
            self.boton_abrir_dialogo_cierres.setEnabled(True)

    def _confirmar_entregable_omitido(self) -> bool:
        confirmado = self._confirmar_accion(
            "Entregable del día no utilizado",
            "ENTREGABLE DEL DÍA NO UTILIZADO\n\nNo se utilizará el control de "
            "registros ya actualizados. El sistema procesará los cierres e "
            "imposibilidades como pendientes y podría incluir registros que ya "
            "fueron actualizados.\n\n¿Desea continuar con el procesamiento?",
            "Sí, continuar",
            "No, regresar",
            critica=True,
        )
        self._confirmacion_sin_entregable = confirmado
        return confirmado

    def _abrir_dialogo_cierres(self) -> None:
        self._mostrar_dialogo("cierres")

    def _abrir_dialogo_entregable(self) -> None:
        self._mostrar_dialogo("entregable")

    def _abrir_dialogo_reaperturas(self) -> None:
        self._mostrar_dialogo("reaperturas")

    def _abrir_dialogo_revisiones(self) -> None:
        self._mostrar_dialogo("revisiones")

    def _abrir_dialogo_resultados(self) -> None:
        self._actualizar_dialogo_resultados()
        self._mostrar_dialogo("resultados")

    @staticmethod
    def _estilo_estado(estado: EstadoEtapa) -> str:
        colores = {
            EstadoEtapa.PENDIENTE: ("#f1f5f9", "#475569"),
            EstadoEtapa.LISTO: ("#dbeafe", "#1d4ed8"),
            EstadoEtapa.PROCESANDO: ("#fef3c7", "#92400e"),
            EstadoEtapa.COMPLETADO: ("#dcfce7", "#166534"),
            EstadoEtapa.CON_ERRORES: ("#fee2e2", "#991b1b"),
            EstadoEtapa.BLOQUEADO: ("#e2e8f0", "#475569"),
        }
        fondo, texto = colores[estado]
        return f"background:{fondo}; color:{texto}; border:1px solid {texto}; border-radius:6px; padding:4px; font-weight:600;"

    def _cambiar_etapa(self, clave: str, estado: EstadoEtapa) -> None:
        etiqueta = self.etiquetas_etapa.get(clave)
        if not etiqueta:
            return
        nombre = etiqueta.text().split("\n", 1)[0]
        etiqueta.setText(f"{nombre}\n{estado.value}")
        etiqueta.setStyleSheet(self._estilo_estado(estado))

    def _seleccionar_archivo(self, clave: str, filtro: str = "Archivos admitidos (*.csv *.txt *.tsv *.xlsx *.xlsm);;Todos (*.*)") -> None:
        ruta, _ = QFileDialog.getOpenFileName(self, "Seleccionar archivo", "", filtro)
        if not ruta:
            return
        if self.hilo:
            QMessageBox.information(
                self, "Proceso en ejecución", "Espere a que termine la operación actual."
            )
            return
        ruta_archivo = Path(ruta)
        ruta_anterior = self.rutas.get(clave)
        if ruta_anterior and Path(ruta_anterior) != ruta_archivo:
            if not self._confirmar_accion(
                "Reemplazar archivo cargado",
                f"Ya existe un archivo cargado para esta entrada:\n"
                f"{Path(ruta_anterior).name}\n\nSerá reemplazado por:\n"
                f"{ruta_archivo.name}\n\n¿Desea continuar?",
                "Sí, reemplazar",
                "No, conservar actual",
            ):
                return
        self._clave_archivo_pendiente = clave
        self._ruta_archivo_pendiente = ruta_archivo
        self.etiquetas_ruta[clave].setText(f"⟳ {ruta_archivo.name}\nLeyendo archivo...")
        self.etiquetas_ruta[clave].setToolTip(str(ruta_archivo))
        self.etiquetas_ruta[clave].setStyleSheet("color:#92400e;")
        self.etiqueta_archivo_cargando.setText(ruta_archivo.name)
        self.etiqueta_estado_carga_archivo.setText("Leyendo archivo...")
        self.progreso_carga_archivo.setRange(0, 0)
        self.boton_cancelar_carga_archivo.setEnabled(True)
        self._mostrar_dialogo("carga_archivo")
        self._iniciar_operacion(
            lambda progreso: self._inspeccionar_archivo_seleccionado(
                clave, ruta_archivo, progreso
            ),
            lambda cantidad: self._archivo_seleccionado_cargado(
                clave, ruta_archivo, cantidad
            ),
            modo_visual="carga_archivo",
        )

    def _inspeccionar_archivo_seleccionado(self, clave: str, ruta: Path, progreso) -> int:
        """Lee la entrada en segundo plano para informar su carga; no cambia sus datos."""
        progreso("Leyendo archivo...", 1, 5)
        progreso("Transformando datos...", 2, 5)
        if clave == "csv_sansys":
            cantidad = self.servicio._leer_sansys(ruta).total_filas
        elif clave == "control_gio":
            cantidad = self.servicio._leer_control_gio(ruta).total_filas
        elif clave == "entregable_acumulado":
            cantidad = self.servicio._leer_acumulado(
                ruta, self.servicio.configuracion
            ).total_filas
        elif clave == "libro_reglas":
            libro = leer_libro_reglas(ruta)
            cantidad = (
                libro.actividad.total_filas
                + libro.operarios.total_filas
                + libro.lecturas.total_filas
            )
        elif clave == "matriz_gio":
            cantidad = len(leer_matriz_reglas_gio(ruta).reglas)
        else:
            cantidad = leer_tabla(ruta).total_filas
        progreso("Validando estructura...", 3, 5)
        progreso("Preparando información...", 4, 5)
        progreso("Carga completada ✓", 5, 5)
        return cantidad

    def _archivo_seleccionado_cargado(
        self, clave: str, ruta: Path, cantidad: int
    ) -> None:
        self.rutas[clave] = str(ruta)
        self.etiquetas_ruta[clave].setText(
            f"✓ {ruta.name}\n{cantidad:,} registros cargados"
        )
        self.etiquetas_ruta[clave].setToolTip(str(ruta))
        self.etiquetas_ruta[clave].setStyleSheet("color:#166534;")
        if clave == "matriz_gio":
            self._validar_matriz_seleccionada(ruta)
        self.etiqueta_estado_carga_archivo.setText("Carga completada ✓")
        self.progreso_carga_archivo.setRange(0, 100)
        self.progreso_carga_archivo.setValue(100)
        self.boton_cancelar_carga_archivo.setEnabled(False)
        QTimer.singleShot(450, self._dialogos["carga_archivo"].accept)
        self._clave_archivo_pendiente = ""
        self._ruta_archivo_pendiente = None

    def _validar_matriz_seleccionada(self, ruta: Path) -> None:
        """Valida la matriz al seleccionarla y muestra un resumen verificable."""
        try:
            matriz = leer_matriz_reglas_gio(ruta)
        except Exception as error:
            self.matriz_gio_previsualizada = None
            self.errores_matriz_gio = [linea for linea in str(error).splitlines() if linea.strip()]
            self.boton_ver_reglas.setEnabled(False)
            self.boton_ver_reglas_principal.setEnabled(False)
            detalle = "\n".join(self.errores_matriz_gio) or "Error de configuración no especificado."
            self.etiquetas_ruta["matriz_gio"].setText(
                f"✕ {ruta.name}\nMATRIZ CON ERRORES"
            )
            self.etiquetas_ruta["matriz_gio"].setToolTip(
                f"Ruta: {ruta}\nErrores de configuración:\n{detalle}"
            )
            self.etiquetas_ruta["matriz_gio"].setStyleSheet("color:#991b1b;")
            return

        self.matriz_gio_previsualizada = matriz
        self.errores_matriz_gio = []
        self.boton_ver_reglas.setEnabled(True)
        self.boton_ver_reglas_principal.setEnabled(True)
        self.etiquetas_ruta["matriz_gio"].setText(
            f"✓ {ruta.name}\n{len(matriz.reglas_activas):,} reglas activas · MATRIZ VÁLIDA"
        )
        self.etiquetas_ruta["matriz_gio"].setToolTip(
            f"Ruta: {ruta}\n"
            f"Reglas activas: {len(matriz.reglas_activas)}\n"
            f"Reglas inactivas: {len(matriz.reglas_inactivas)}\n"
            f"Fecha de modificación: {matriz.fecha_modificacion or 'No disponible'}"
        )
        self.etiquetas_ruta["matriz_gio"].setStyleSheet("color:#166534;")

    def _ver_reglas_cargadas(self) -> None:
        """Muestra las reglas de la matriz en una tabla estrictamente de solo lectura."""
        matriz = self.matriz_gio_previsualizada
        if matriz is None:
            QMessageBox.warning(self, "Matriz no válida", "Cargue primero una matriz GIO válida.")
            return
        self.etiqueta_resumen_reglas.setText(
            f"{Path(matriz.ruta).name if matriz.ruta else 'Matriz GIO'} — "
            f"{len(matriz.reglas_activas)} activas / {len(matriz.reglas_inactivas)} inactivas"
        )
        columnas = (
            "ID_REGLA", "PRIORIDAD", "RGLA", "PATRON_OBS", "CONDICION_ACC",
            "ACCIÓN / RANGO", "RESULTADO", "DESTINO", "ACTIVO",
        )
        tabla = self.tabla_reglas_cargadas
        tabla.clearContents()
        tabla.setRowCount(len(matriz.reglas))
        tabla.setColumnCount(len(columnas))
        tabla.setHorizontalHeaderLabels(columnas)
        for fila, regla in enumerate(matriz.reglas):
            valores = (
                regla.id_regla, str(regla.prioridad), regla.regla, regla.patron_obs,
                regla.condicion_acc, regla.descripcion_accion, regla.resultado,
                regla.destino, "SI" if regla.activa else "NO",
            )
            for columna, valor in enumerate(valores):
                tabla.setItem(fila, columna, QTableWidgetItem(valor))
        tabla.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        tabla.horizontalHeader().setStretchLastSection(True)
        self._mostrar_dialogo("reglas")

    def _seleccionar_salida(self) -> None:
        ruta = QFileDialog.getExistingDirectory(self, "Seleccionar carpeta de salida")
        if ruta:
            self.rutas["carpeta_salida"] = ruta
            self.etiqueta_salida.setText(f"✓ {Path(ruta).name or ruta}")
            self.etiqueta_salida.setToolTip(ruta)

    def _rutas_entradas(self) -> RutasEntradasActualizacion:
        requeridas = [
            "csv_sansys", "control_gio", "libro_reglas", "matriz_gio",
            "carpeta_salida",
        ]
        if self.modo_c03:
            requeridas.append("entregable_historico")
        elif self.opcion_entregable_acumulado.isChecked():
            requeridas.append("entregable_acumulado")
        faltantes = [clave for clave in requeridas if not self.rutas.get(clave)]
        if faltantes:
            raise ValueError("Faltan archivos o carpeta: " + ", ".join(faltantes))
        if self.matriz_gio_previsualizada is None:
            detalle = "; ".join(self.errores_matriz_gio) or "La matriz no ha sido validada."
            raise ValueError("La matriz GIO tiene errores de configuración: " + detalle)
        return RutasEntradasActualizacion(
            ruta_csv_sansys=Path(self.rutas["csv_sansys"]),
            ruta_control_gio=Path(self.rutas["control_gio"]),
            ruta_entregable_acumulado=(
                Path(self.rutas["entregable_acumulado"])
                if self.opcion_entregable_acumulado.isChecked() and not self.modo_c03
                else None
            ),
            ruta_libro_reglas=Path(self.rutas["libro_reglas"]),
            carpeta_salida=Path(self.rutas["carpeta_salida"]),
            ruta_matriz_gio=Path(self.rutas["matriz_gio"]),
            configuracion_json=Path(self.rutas["configuracion_json"]) if self.rutas.get("configuracion_json") else None,
            considerar_entregable_acumulado=(
                self.opcion_entregable_acumulado.isChecked() and not self.modo_c03
            ),
            considerar_entregable_actualizado=self.opcion_entregable_actualizado.isChecked(),
            confirmacion_sin_entregable=self._confirmacion_sin_entregable,
            modo_c03=self.modo_c03,
            ruta_entregable_historico=(
                Path(self.rutas["entregable_historico"])
                if self.modo_c03 and self.rutas.get("entregable_historico")
                else None
            ),
        )

    def _iniciar_operacion(
        self,
        operacion,
        al_terminar,
        modo_visual: str = "proceso",
        texto_inicial: str = "Preparando datos...",
    ) -> None:
        if self.hilo:
            QMessageBox.information(self, "Proceso en ejecución", "Espere a que termine la etapa actual.")
            return
        self._al_terminar = al_terminar
        self._modo_operacion = modo_visual
        self.hilo = QThread(self)
        self.trabajador = TrabajadorActualizacion(operacion)
        self.trabajador.moveToThread(self.hilo)
        self.hilo.started.connect(self.trabajador.ejecutar)
        self.trabajador.progreso.connect(self._mostrar_progreso)
        self.trabajador.terminado.connect(self._operacion_terminada)
        self.trabajador.error.connect(self._operacion_fallida)
        self.trabajador.cancelado.connect(self._operacion_cancelada)
        for senal in (self.trabajador.terminado, self.trabajador.error, self.trabajador.cancelado):
            senal.connect(self.hilo.quit)
        self.hilo.finished.connect(self._liberar_hilo)
        self.boton_cancelar.setEnabled(True)
        self.boton_cancelar_cierres.setEnabled(True)
        self.boton_cancelar_reaperturas.setEnabled(True)
        self.boton_cancelar_carga_archivo.setEnabled(True)
        self.boton_cancelar_proceso.setEnabled(True)
        self.boton_flujo.setEnabled(False)
        self.boton_cierres.setEnabled(False)
        self.boton_reaperturas.setEnabled(False)
        if modo_visual == "proceso":
            self.etiqueta_estado.show()
            self.progreso.show()
            self.progreso.setValue(0)
            self.etiqueta_estado.setText(f"Estado: {texto_inicial}")
            self.progreso_proceso.setValue(0)
            self.etiqueta_porcentaje_proceso.setText("0 %")
            self.etiqueta_etapa_proceso.setText(texto_inicial)
            self._mostrar_dialogo("progreso_proceso")
        self.hilo.start()

    def _iniciar_flujo_comun(self) -> None:
        try:
            rutas = self._rutas_entradas()
        except ValueError as error:
            QMessageBox.warning(self, "Faltan entradas", str(error))
            return
        titulo_confirmacion = "PROCESAR MODO C03" if self.modo_c03 else "Procesar cierres"
        texto_confirmacion = (
            "PROCESAR MODO C03\n\nSe procesarán todas las reaperturas de la fecha "
            "seleccionada. No se procesarán ni generarán cierres.\n\n¿Desea continuar?"
            if self.modo_c03
            else "Se ejecutará el flujo común, se evaluarán los cierres y se generarán "
            "los archivos de salida para la fecha seleccionada.\n\n¿Desea continuar?"
        )
        if not self._confirmar_accion(
            titulo_confirmacion,
            texto_confirmacion,
            "Sí, procesar" if self.modo_c03 else "Sí, procesar cierres",
            "No, regresar",
        ):
            return
        self._confirmacion_c03_vigente = self.modo_c03
        if (
            not self.modo_c03
            and not self.opcion_entregable_acumulado.isChecked()
            and not self._confirmar_entregable_omitido()
        ):
            return
        if not self.modo_c03 and not self.opcion_entregable_acumulado.isChecked():
            rutas = self._rutas_entradas()
        self._procesar_cierres_automaticamente = False
        self._procesar_reaperturas_automaticamente = False
        self._cierres_confirmados = True
        self._cambiar_etapa("CARGA", EstadoEtapa.PROCESANDO)
        fecha = self.fecha.date().toString("dd/MM/yyyy")
        self._iniciar_operacion(
            lambda progreso: self.servicio.procesar_flujo_comun(rutas, fecha, progreso),
            self._flujo_comun_terminado,
        )

    def _iniciar_cierres(self) -> None:
        if not self._cierres_confirmados and not self._confirmar_accion(
            "Procesar cierres",
            "Se procesarán los registros C, CD y V y se generarán las salidas "
            "correspondientes.\n\n¿Desea continuar?",
            "Sí, procesar cierres",
            "No, regresar",
        ):
            return
        self._cierres_confirmados = False
        self._cambiar_etapa("CIERRES", EstadoEtapa.PROCESANDO)
        self._iniciar_operacion(
            lambda progreso: self.servicio.procesar_cierres(progreso),
            self._cierres_terminados,
            texto_inicial="Preparando cierres...",
        )

    def _iniciar_carga_entregable(self) -> None:
        if not self.opcion_entregable_actualizado.isChecked():
            return
        try:
            rutas = self._rutas_entradas()
            fecha = self.fecha.date().toString("dd/MM/yyyy")
        except ValueError:
            rutas = None
            fecha = ""
        if rutas is None or not self.servicio.contexto_es_vigente(rutas, fecha):
            QMessageBox.warning(
                self, "Proceso requerido", "Primero procese la fecha y genere los cierres"
            )
            return
        ruta, _ = QFileDialog.getOpenFileName(
            self, "Cargar entregable actualizado de cierres", "",
            "Archivos admitidos (*.txt *.csv *.xlsx *.xlsm);;Todos (*.*)",
        )
        if not ruta:
            return
        ruta_anterior = (
            self.servicio.resultado.contexto.entregable_actualizado
            if self.servicio.resultado
            else ""
        )
        if ruta_anterior and Path(ruta_anterior) != Path(ruta):
            if not self._confirmar_accion(
                "Reemplazar entregable actualizado",
                f"El entregable actualizado cargado ({Path(ruta_anterior).name}) "
                f"será reemplazado por {Path(ruta).name}.\n\n¿Desea continuar?",
                "Sí, reemplazar",
                "No, conservar actual",
            ):
                return
        self._cambiar_etapa("ENTREGABLE", EstadoEtapa.PROCESANDO)
        self._iniciar_operacion(
            lambda progreso: self.servicio.cargar_entregable_actualizado(
                Path(ruta), progreso
            ),
            self._entregable_terminado,
            texto_inicial="Validando entregable actualizado...",
        )

    def _iniciar_reaperturas(self) -> None:
        considerar = self.opcion_entregable_actualizado.isChecked()
        if not considerar:
            QMessageBox.warning(
                self,
                "Entregable requerido",
                "Las reaperturas requieren cargar el entregable actualizado de cierres.",
            )
            return
        try:
            rutas = self._rutas_entradas()
            fecha = self.fecha.date().toString("dd/MM/yyyy")
        except ValueError:
            rutas = None
            fecha = ""
        if rutas is None or not self.servicio.contexto_es_vigente(rutas, fecha):
            QMessageBox.warning(
                self, "Proceso requerido", "Primero procese la fecha y genere los cierres"
            )
            return
        if not self._confirmacion_c03_vigente and not self._confirmar_accion(
            "Procesar reaperturas",
            "Se evaluarán las reaperturas R y RD contra el entregable actualizado "
            "cargado y se generarán sus archivos de salida.\n\n¿Desea continuar?",
            "Sí, procesar reaperturas",
            "No, regresar",
        ):
            return
        self._confirmacion_c03_vigente = False
        self.servicio.considerar_entregable_actualizado = considerar
        self._cambiar_etapa("REAPERTURAS", EstadoEtapa.PROCESANDO)
        self._iniciar_operacion(
            lambda progreso: self.servicio.procesar_reaperturas(progreso),
            self._reaperturas_terminadas,
            texto_inicial="Preparando reaperturas...",
        )

    @Slot(str, int, int)
    def _mostrar_progreso(self, etapa: str, actual: int, total: int) -> None:
        porcentaje = int(actual * 100 / max(1, total))
        if self._modo_operacion == "carga_archivo":
            self.etiqueta_estado_carga_archivo.setText(etapa)
            self.progreso_carga_archivo.setRange(0, 100)
            self.progreso_carga_archivo.setValue(porcentaje)
            return
        self.etiqueta_estado.show()
        self.progreso.show()
        self.etiqueta_estado.setText(f"Estado: {etapa}")
        self.progreso.setValue(porcentaje)
        self.etiqueta_etapa_proceso.setText(etapa)
        self.progreso_proceso.setValue(porcentaje)
        self.etiqueta_porcentaje_proceso.setText(f"{porcentaje} %")
        self.etiqueta_progreso_cierres.setText(f"Estado: {etapa}")
        self.etiqueta_progreso_reaperturas.setText(f"Estado: {etapa}")
        self.progreso_cierres.setValue(porcentaje)
        self.progreso_reaperturas.setValue(porcentaje)

    @Slot(object)
    def _operacion_terminada(self, resultado) -> None:
        if self._al_terminar:
            self._al_terminar(resultado)

    @Slot(str, str)
    def _operacion_fallida(self, mensaje: str, detalle: str) -> None:
        self._procesar_cierres_automaticamente = False
        self._cierres_confirmados = False
        if self._modo_operacion == "carga_archivo":
            clave = self._clave_archivo_pendiente
            if clave and clave in self.etiquetas_ruta:
                self.etiquetas_ruta[clave].setText("✕ Error al cargar archivo")
                self.etiquetas_ruta[clave].setStyleSheet("color:#991b1b;")
            self.etiqueta_estado_carga_archivo.setText("✕ Error al cargar archivo")
            self.progreso_carga_archivo.setRange(0, 100)
            self.progreso_carga_archivo.setValue(0)
            self.boton_cancelar_carga_archivo.setEnabled(False)
            QTimer.singleShot(900, self._dialogos["carga_archivo"].reject)
            self._clave_archivo_pendiente = ""
            self._ruta_archivo_pendiente = None
            QMessageBox.critical(self, "Carga de archivo", mensaje)
            return
        self.etiqueta_estado.show()
        self.progreso.show()
        self.etiqueta_estado.setText("Estado: error")
        self.etiqueta_etapa_proceso.setText("Error durante el procesamiento")
        self._dialogos["progreso_proceso"].reject()
        self.texto_resumen.append(f"\nERROR: {mensaje}")
        if mensaje.startswith("La fecha seleccionada no existe en la data"):
            QMessageBox.warning(self, "Fecha sin registros", mensaje)
            self.texto_resumen.setToolTip(detalle)
            return
        ruta_log = self._guardar_log_tecnico(mensaje, detalle)
        QMessageBox.critical(
            self,
            "Procesamiento de actualizaciones",
            f"{mensaje}\n\nDetalle técnico guardado en:\n{ruta_log}",
        )
        self.texto_resumen.setToolTip(detalle)

    def _guardar_log_tecnico(self, mensaje: str, detalle: str) -> Path:
        carpeta = Path(self.rutas.get("carpeta_salida") or Path.cwd())
        carpeta.mkdir(parents=True, exist_ok=True)
        ruta_log = carpeta / "error_procesamiento_actualizaciones.log"
        marca_tiempo = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with ruta_log.open("a", encoding="utf-8") as archivo:
            archivo.write(
                f"[{marca_tiempo}] {mensaje}\n"
                f"{detalle}\n"
                + "-" * 80
                + "\n"
            )
        return ruta_log

    @Slot()
    def _operacion_cancelada(self) -> None:
        self._procesar_cierres_automaticamente = False
        self._cierres_confirmados = False
        self.etiqueta_estado.setText("Estado: operación cancelada")
        if self._modo_operacion == "carga_archivo":
            clave = self._clave_archivo_pendiente
            if clave and clave in self.etiquetas_ruta:
                self.etiquetas_ruta[clave].setText("Carga cancelada")
                self.etiquetas_ruta[clave].setStyleSheet("color:#92400e;")
            self._dialogos["carga_archivo"].reject()
        else:
            self._dialogos["progreso_proceso"].reject()

    @Slot()
    def _liberar_hilo(self) -> None:
        if self.trabajador:
            self.trabajador.deleteLater()
        if self.hilo:
            self.hilo.deleteLater()
        self.trabajador = None
        self.hilo = None
        self._al_terminar = None
        self.boton_cancelar.setEnabled(False)
        self.boton_cancelar_cierres.setEnabled(False)
        self.boton_cancelar_reaperturas.setEnabled(False)
        self.boton_cancelar_carga_archivo.setEnabled(False)
        self.boton_cancelar_proceso.setEnabled(False)
        self.boton_flujo.setEnabled(True)
        self.boton_cierres.setEnabled(
            not self.modo_c03
            and bool(self._ultimo_resultado and self._ultimo_resultado.flujo_comun)
        )
        self.boton_reaperturas.setEnabled(
            bool(self.servicio.tabla_entregable_actualizado)
        )
        if self._procesar_cierres_automaticamente:
            self._procesar_cierres_automaticamente = False
            self.boton_flujo.setEnabled(False)
            self._cierres_confirmados = True
            QTimer.singleShot(0, self._iniciar_cierres)
        elif self._procesar_reaperturas_automaticamente:
            self._procesar_reaperturas_automaticamente = False
            self.boton_flujo.setEnabled(False)
            QTimer.singleShot(0, self._iniciar_reaperturas)

    def _cancelar(self) -> None:
        if self.trabajador and self._confirmar_accion(
            "Cancelar proceso en ejecución",
            "La operación se detendrá en el siguiente punto seguro. Los resultados "
            "de esta etapa podrían no generarse.\n\n¿Desea cancelar el proceso?",
            "Sí, cancelar proceso",
            "No, continuar procesando",
            critica=True,
        ):
            self.trabajador.solicitar_cancelacion()
            self.etiqueta_estado.setText("Estado: cancelando en el siguiente punto seguro…")

    def limpiar_sesion(self) -> None:
        """Elimina el estado temporal después de que el trabajador haya terminado."""
        if self.hilo is not None and self.hilo.isRunning():
            raise RuntimeError("No se puede limpiar la sesión con un QThread activo.")
        for dialogo in self._dialogos.values():
            dialogo.close()
        self.rutas.clear()
        self.servicio = ServicioProcesamientoActualizaciones()
        self._ultimo_resultado = None
        self.matriz_gio_previsualizada = None
        self.errores_matriz_gio.clear()
        self._procesar_cierres_automaticamente = False
        self._procesar_reaperturas_automaticamente = False
        self._confirmacion_c03_vigente = False
        self._confirmacion_sin_entregable = False
        self._cierres_confirmados = False
        self._clave_archivo_pendiente = ""
        self._ruta_archivo_pendiente = None
        if hasattr(self, "interruptor_modo_c03"):
            self._cambio_opcion_interno = True
            self.interruptor_modo_c03.setChecked(False)
            self._cambio_opcion_interno = False
        self._cambio_opcion_interno = True
        self.opcion_entregable_acumulado.setChecked(True)
        self.opcion_entregable_actualizado.setChecked(True)
        self._cambio_opcion_interno = False
        self._aplicar_modo_c03(False)
        for etiqueta in self.etiquetas_ruta.values():
            etiqueta.setText("Sin archivo seleccionado")
            etiqueta.setToolTip("")
            etiqueta.setStyleSheet("")
        self.etiqueta_salida.setText("Sin carpeta seleccionada")
        self.etiqueta_salida.setToolTip("")
        self.texto_resumen.setPlainText(
            "Filas cargadas: 0\nDATA_FILTRADA: 0\nCierres listos: 0\n"
            "Reaperturas listas: 0\nRevisiones: 0"
        )
        self.texto_resultados.setPlainText("Aún no se han generado archivos.")
        self.tabla.clear()
        self.tabla.setRowCount(0)
        self.tabla.setColumnCount(0)
        if self.tabla_reglas_cargadas is not None:
            self.tabla_reglas_cargadas.clearContents()
            self.tabla_reglas_cargadas.setRowCount(0)
        for clave in ("CARGA", "NORMALIZACION", "FLUJO_COMUN", "DATA_FILTRADA"):
            self._cambiar_etapa(clave, EstadoEtapa.PENDIENTE)
        self._cambiar_etapa("CIERRES", EstadoEtapa.PENDIENTE)
        self._cambiar_etapa("ENTREGABLE", EstadoEtapa.BLOQUEADO)
        self._cambiar_etapa("REAPERTURAS", EstadoEtapa.BLOQUEADO)
        self.boton_cierres.setEnabled(False)
        self.boton_entregable.setEnabled(False)
        self.boton_reaperturas.setEnabled(False)
        self.boton_ver_reglas.setEnabled(False)
        self.boton_ver_reglas_principal.setEnabled(False)
        self.boton_abrir.setEnabled(False)
        self.etiqueta_estado.setText("Estado: listo")
        self.progreso.setValue(0)

    def _flujo_comun_terminado(self, resultado: ResultadoProceso) -> None:
        self._ultimo_resultado = resultado
        self._cambiar_etapa("CARGA", EstadoEtapa.COMPLETADO)
        self._cambiar_etapa("NORMALIZACION", EstadoEtapa.COMPLETADO)
        self._cambiar_etapa("FLUJO_COMUN", resultado.contexto.estados_etapas["FLUJO_COMUN"])
        self._cambiar_etapa("DATA_FILTRADA", EstadoEtapa.COMPLETADO)
        self._cambiar_etapa("CIERRES", EstadoEtapa.LISTO)
        self._cambiar_etapa("REAPERTURAS", EstadoEtapa.BLOQUEADO)
        self.boton_cierres.setEnabled(True)
        self.boton_abrir.setEnabled(True)
        self._actualizar_resumen(resultado)
        revisiones = []
        if resultado.flujo_comun:
            revisiones = [
                registro for registro in resultado.flujo_comun.registros
                if registro.categoria_final.value in {"REVISION_MANUAL", "ERROR_TECNICO"}
            ]
        self._mostrar_registros(revisiones)
        cantidad_filtrada = (
            len(resultado.flujo_comun.data_filtrada) if resultado.flujo_comun else 0
        )
        if cantidad_filtrada == 0:
            self._cambiar_etapa("CIERRES", EstadoEtapa.BLOQUEADO)
            self.boton_cierres.setEnabled(False)
            self.etiqueta_estado.setText(
                "Estado: no hay registros para la fecha seleccionada"
            )
            self._procesar_cierres_automaticamente = False
            self._cierres_confirmados = False
            carpeta = (
                self.servicio.rutas_salida.raiz
                if self.servicio.rutas_salida
                else self.rutas.get("carpeta_salida", "--")
            )
            QMessageBox.warning(
                self,
                "Sin registros para procesar",
                "El flujo sí se ejecutó, pero DATA_FILTRADA quedó vacía para la fecha "
                f"{self.fecha.date().toString('dd/MM/yyyy')}.\n\n"
                "Revise que la fecha corresponda a la columna FECHA del bloque operativo "
                "del CSV SANSYS. La carpeta de resultados es:\n"
                f"{carpeta}",
            )
            self._dialogos["progreso_proceso"].accept()
            return
        if self.modo_c03:
            self.etiquetas_etapa["CIERRES"].setText(
                "CIERRES: NO APLICA\nModo C03"
            )
            self.etiquetas_etapa["CIERRES"].setStyleSheet(
                self._estilo_estado(EstadoEtapa.COMPLETADO)
            )
            self.etiquetas_etapa["ENTREGABLE"].setText(
                "ENTREGABLE DEL DÍA\nNO APLICA"
            )
            self.etiquetas_etapa["ENTREGABLE"].setStyleSheet(
                self._estilo_estado(EstadoEtapa.COMPLETADO)
            )
            self._cambiar_etapa("REAPERTURAS", EstadoEtapa.LISTO)
            self.boton_cierres.setEnabled(False)
            self.boton_entregable.setEnabled(False)
            self.boton_reaperturas.setEnabled(True)
            self.etiqueta_estado.setText(
                "Estado: DATA_FILTRADA lista; procesando reaperturas en Modo C03…"
            )
            self._procesar_reaperturas_automaticamente = True
            return
        self.etiqueta_estado.setText("Estado: DATA_FILTRADA lista; generando cierres y entregable…")
        self._procesar_cierres_automaticamente = True

    def _cierres_terminados(self, resultado: ResultadoProceso) -> None:
        self._ultimo_resultado = resultado
        estado = resultado.contexto.estados_etapas.get("CIERRES", EstadoEtapa.CON_ERRORES)
        self._cambiar_etapa("CIERRES", estado)
        entregable_generado = bool(resultado.contexto.entregable_cierres)
        usar_entregable = self.opcion_entregable_actualizado.isChecked()
        self.servicio.considerar_entregable_actualizado = usar_entregable
        self.boton_entregable.setEnabled(entregable_generado and usar_entregable)
        self._cambiar_etapa(
            "ENTREGABLE",
            (EstadoEtapa.LISTO if usar_entregable else EstadoEtapa.COMPLETADO)
            if entregable_generado else EstadoEtapa.BLOQUEADO,
        )
        self._actualizar_resumen(resultado)
        self._mostrar_registros(resultado.cierres.revisiones if resultado.cierres else [])
        self.boton_abrir.setEnabled(True)
        self.boton_flujo.setEnabled(True)
        carpeta = self.servicio.rutas_salida.raiz if self.servicio.rutas_salida else "--"
        if entregable_generado and self.servicio.rutas_salida:
            QMessageBox.information(
                self,
                "Archivos generados",
                "El procesamiento de cierres terminó correctamente.\n\n"
                f"Cierres listos: {len(resultado.cierres.listas) if resultado.cierres else 0}\n"
                f"Resultados: {self.servicio.rutas_salida.raiz}\n\n"
                + (
                    "Ahora puede cargar el entregable actualizado para procesar las reaperturas."
                    if usar_entregable
                    else "Active el entregable actualizado para continuar con reaperturas."
                ),
            )
        else:
            cantidad_revisiones = len(resultado.cierres.revisiones) if resultado.cierres else 0
            cantidad_entradas = len(resultado.cierres.entradas) if resultado.cierres else 0
            self.etiqueta_estado.setText(
                "Estado: cierres procesados sin filas aptas para generar TXT"
            )
            QMessageBox.warning(
                self,
                "No se generó el TXT de cierres",
                "El procesamiento terminó, pero ninguna fila quedó lista para el TXT.\n\n"
                f"Cierres evaluados: {cantidad_entradas}\n"
                f"Filas enviadas a revisión: {cantidad_revisiones}\n"
                f"Resultados: {carpeta}\n\n"
                "Revise el panel de resumen y REVISION_CIERRES.xlsx; las filas no "
                "fueron eliminadas silenciosamente.",
            )
        self.etiqueta_etapa_proceso.setText("Finalizando...")
        self.progreso_proceso.setValue(100)
        self.etiqueta_porcentaje_proceso.setText("100 %")
        QTimer.singleShot(350, self._dialogos["progreso_proceso"].accept)

    def _entregable_terminado(self, _tabla) -> None:
        self._cambiar_etapa("ENTREGABLE", EstadoEtapa.COMPLETADO)
        self._cambiar_etapa("REAPERTURAS", EstadoEtapa.LISTO)
        self.boton_reaperturas.setEnabled(True)
        self.etiqueta_estado.setText("Estado: entregable actualizado cargado")
        self.etiqueta_etapa_proceso.setText("Carga completada")
        self.progreso_proceso.setValue(100)
        self.etiqueta_porcentaje_proceso.setText("100 %")
        self.boton_cancelar_proceso.setEnabled(False)
        QTimer.singleShot(350, self._dialogos["progreso_proceso"].accept)

    def _reaperturas_terminadas(self, resultado: ResultadoProceso) -> None:
        self._ultimo_resultado = resultado
        estado = resultado.contexto.estados_etapas.get("REAPERTURAS", EstadoEtapa.CON_ERRORES)
        self._cambiar_etapa("REAPERTURAS", estado)
        self._actualizar_resumen(resultado)
        self._mostrar_registros(resultado.reaperturas.revisiones if resultado.reaperturas else [])
        self.etiqueta_etapa_proceso.setText("Finalizando...")
        self.progreso_proceso.setValue(100)
        self.etiqueta_porcentaje_proceso.setText("100 %")
        QTimer.singleShot(350, self._dialogos["progreso_proceso"].accept)
        QTimer.singleShot(450, self._mostrar_resultado_final_reaperturas)

    def _mostrar_resultado_final_reaperturas(self) -> None:
        resultado = self._ultimo_resultado
        rama = resultado.reaperturas if resultado else None
        if resultado is None or rama is None:
            return
        rutas = {
            clave: Path(resultado.contexto.archivos_generados.get(clave, ""))
            for clave in ("reaperturas_sistema", "entregable_reaperturas")
        }
        generados = {
            clave: ruta for clave, ruta in rutas.items()
            if str(ruta) not in {"", "."} and ruta.is_file()
        }
        self.boton_abrir.setEnabled(bool(generados) or bool(self.servicio.rutas_salida))
        if rama.listas and len(generados) != 2:
            faltantes = [
                clave for clave in ("reaperturas_sistema", "entregable_reaperturas")
                if clave not in generados
            ]
            mensaje = (
                "El procesamiento terminó, pero no se encontraron físicamente todos "
                "los TXT de reaperturas. Faltan: " + ", ".join(faltantes)
            )
            ruta_log = self._guardar_log_tecnico(mensaje, repr(resultado.contexto.archivos_generados))
            self.etiqueta_estado.setText("Estado: error al generar archivos de reaperturas")
            QMessageBox.critical(
                self, "Error al generar reaperturas",
                f"{mensaje}\n\nDetalle técnico guardado en:\n{ruta_log}",
            )
            return
        if len(generados) == 2:
            self.etiqueta_estado.setText(
                f"Estado: {len(rama.listas)} reaperturas generadas correctamente"
            )
            self._abrir_dialogo_resultados()
            return
        ruta_revision = resultado.contexto.archivos_generados.get(
            "reaperturas_revision_manual", "No generado"
        )
        self.etiqueta_estado.setText(
            "Estado: no hay reaperturas aptas; revise las observaciones"
        )
        QMessageBox.warning(
            self, "No se generaron TXT de reaperturas",
            "El proceso sí terminó, pero ninguna fila quedó aprobada para los TXT.\n\n"
            f"Reaperturas evaluadas: {len(rama.entradas)}\n"
            f"Filas en revisión: {len(rama.revisiones)}\n"
            f"Archivo de revisión: {ruta_revision}",
        )

    def _actualizar_resumen(self, resultado: ResultadoProceso) -> None:
        flujo = resultado.flujo_comun
        cierres = resultado.cierres
        reaperturas = resultado.reaperturas
        lineas = [
            f"CSV SANSYS: {Path(self.rutas['csv_sansys']).name if self.rutas.get('csv_sansys') else '--'}",
            f"Libro de reglas y actualización: {Path(self.rutas['libro_reglas']).name if self.rutas.get('libro_reglas') else '--'}",
            f"Filas cargadas: {len(flujo.registros) if flujo else 0}",
            f"DATA_FILTRADA: {len(flujo.data_filtrada) if flujo else 0}",
            f"Cierres listos: {len(cierres.listas) if cierres else 0}",
            f"Reaperturas listas: {len(reaperturas.listas) if reaperturas else 0}",
            f"Revisiones comunes: {flujo.resumen.revisiones if flujo else 0}",
            f"Revisiones de cierres: {len(cierres.revisiones) if cierres else 0}",
            f"Revisiones de reaperturas: {len(reaperturas.revisiones) if reaperturas else 0}",
            "Entregable de actualizados del día: "
            + (
                "NO APLICA — Modo C03"
                if self.modo_c03
                else (
                    "UTILIZADO"
                    if self.opcion_entregable_acumulado.isChecked()
                    else "NO UTILIZADO"
                )
            ),
            "Modo de procesamiento: "
            + ("C03 — Solo reaperturas" if self.modo_c03 else "Normal"),
            "Continuación autorizada por el usuario: "
            + ("SÍ" if self._confirmacion_sin_entregable else "NO APLICA"),
        ]
        bloqueos = []
        for objeto in (flujo, cierres, reaperturas):
            bloqueos.extend(getattr(objeto, "bloqueos", []) if objeto else [])
        lineas.append("Bloqueos:")
        lineas.extend(f"- {texto}" for texto in bloqueos if texto)
        if not bloqueos:
            lineas.append("- Ninguno en las etapas ejecutadas.")
        self.texto_resumen.setPlainText("\n".join(lineas))
        if cierres:
            self.etiqueta_contadores_cierres.setText(
                f"Entradas: {len(cierres.entradas)}   |   Listos: {len(cierres.listas)}   |   "
                f"Revisiones: {len(cierres.revisiones)}"
            )
        if reaperturas:
            self.etiqueta_contadores_reaperturas.setText(
                f"Entradas: {len(reaperturas.entradas)}   |   Listas: {len(reaperturas.listas)}   |   "
                f"Revisiones: {len(reaperturas.revisiones)}"
            )
        self._actualizar_dialogo_resultados()
        self.etiqueta_estado.hide()
        self.progreso.hide()
        if cierres:
            self.etiqueta_progreso_cierres.setText("Estado: etapa terminada")
            self.progreso_cierres.setValue(100)
        if reaperturas:
            self.etiqueta_progreso_reaperturas.setText("Estado: etapa terminada")
            self.progreso_reaperturas.setValue(100)

    def _actualizar_dialogo_resultados(self) -> None:
        if not self.servicio.rutas_salida:
            self.texto_resultados.setPlainText("Aún no se han generado archivos.")
            return
        raiz = self.servicio.rutas_salida.raiz
        archivos = sorted(ruta for ruta in raiz.rglob("*") if ruta.is_file()) if raiz.exists() else []
        lineas = [f"Carpeta: {raiz}", "", "Archivos generados:"]
        for ruta in archivos:
            tamano = ruta.stat().st_size
            unidad = (
                f"{tamano / (1024 * 1024):.2f} MB"
                if tamano >= 1024 * 1024
                else f"{tamano / 1024:.1f} KB"
            )
            lineas.append(f"- {ruta.relative_to(raiz)} — {unidad}")
        if not archivos:
            lineas.append("- Aún no hay archivos disponibles.")
        self.texto_resultados.setPlainText("\n".join(lineas))

    def _mostrar_registros(self, registros) -> None:
        filas = list(registros)[:500]
        columnas = ["OT", "OS", "ETAPA", "CATEGORIA", "REGLA", "MOTIVO", "DESTINO"]
        vistos = set(columnas)
        for registro in filas:
            for columna in registro.datos_normalizados:
                if columna not in vistos:
                    vistos.add(columna)
                    columnas.append(columna)
        self.tabla.clear()
        self.tabla.setRowCount(len(filas))
        self.tabla.setColumnCount(len(columnas))
        self.tabla.setHorizontalHeaderLabels(columnas)
        for fila_indice, registro in enumerate(filas):
            valores = {
                **registro.datos_normalizados,
                "OT": registro.ot,
                "OS": registro.os,
                "ETAPA": registro.etapa_final,
                "CATEGORIA": registro.categoria_final.value,
                "REGLA": registro.regla_final,
                "MOTIVO": registro.motivo_final,
                "DESTINO": registro.archivo_destino,
            }
            for columna_indice, columna in enumerate(columnas):
                self.tabla.setItem(fila_indice, columna_indice, QTableWidgetItem(str(valores.get(columna, ""))))
        self.tabla.resizeColumnsToContents()

    def _abrir_resultados(self) -> None:
        if self.servicio.rutas_salida and self.servicio.rutas_salida.raiz.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.servicio.rutas_salida.raiz)))
        else:
            QMessageBox.warning(self, "Resultados", "Aún no existe una carpeta de resultados.")
