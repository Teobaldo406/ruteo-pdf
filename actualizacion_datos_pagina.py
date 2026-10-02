# -*- coding: utf-8 -*-
"""Página PySide6 del módulo Procesamiento de actualizaciones."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, Optional

from PySide6.QtCore import QDate, QThread, QTimer, Qt, QUrl, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView, QDateEdit, QDialog, QFileDialog, QFrame, QHeaderView,
    QHBoxLayout, QLabel,
    QMessageBox, QProgressBar, QPushButton, QScrollArea, QTableWidget,
    QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget,
)

from actualizacion_datos.lectores import leer_matriz_reglas_gio
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
        self.matriz_gio_previsualizada: Optional[MatrizReglasGio] = None
        self.errores_matriz_gio: list[str] = []
        self.tabla_reglas_cargadas: Optional[QTableWidget] = None
        self.setObjectName("areaPrincipal")
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
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
        fila = QHBoxLayout()
        boton = self._boton(
            texto, lambda _marcado=False: self._seleccionar_archivo(clave, filtro)
        )
        etiqueta = QLabel("Opcional: --" if opcional else "Archivo: --")
        etiqueta.setWordWrap(True)
        self.etiquetas_ruta[clave] = etiqueta
        fila.addWidget(boton)
        fila.addWidget(etiqueta, 1)
        disposicion.addLayout(fila)

    def _construir_interfaz(self) -> None:
        lienzo, central = QWidget(), QWidget()
        lienzo.setStyleSheet("background:#eef4f8;")
        central.setObjectName("contenedorCentral")
        central.setMinimumWidth(980)
        central.setMaximumWidth(1420)
        central.setStyleSheet("""
            QWidget#contenedorCentral { color:#17365d; }
            QFrame#tarjeta, QFrame#tarjetaVerde, QFrame#tarjetaAzul,
            QFrame#tarjetaGris, QFrame#panelEstado {
                background:rgba(255,255,255,245); border:1px solid #b9d2e8;
                border-radius:9px;
            }
            QFrame#tarjetaVerde { border:2px solid #49ad69; }
            QFrame#tarjetaAzul { border:1px solid #4698d1; }
            QFrame#tarjetaGris { border:1px solid #b5bdc7; background:#f5f7f9; }
            QLabel#tituloTarjeta { font-size:15px; font-weight:700; color:#174d76; }
            QLabel#tituloVerde { font-size:15px; font-weight:700; color:#13783b; }
            QLabel#tituloGris { font-size:15px; font-weight:700; color:#66717e; }
            QPushButton { min-height:29px; padding:3px 10px; border:1px solid #9fb9cf;
                border-radius:5px; background:#ffffff; color:#17365d; }
            QPushButton:hover { background:#edf6fd; border-color:#2785c2; }
            QPushButton#botonPrimario { background:#087fc5; color:white; border-color:#0870af;
                font-weight:700; min-height:34px; }
            QPushButton:disabled { background:#e3e7eb; color:#929aa3; border-color:#ccd2d8; }
            QProgressBar { border:1px solid #a8bfce; border-radius:5px; height:13px;
                text-align:center; background:#eef3f7; }
            QProgressBar::chunk { background:#19a25b; border-radius:4px; }
        """)
        exterior = QHBoxLayout(lienzo)
        exterior.setContentsMargins(12, 8, 12, 10)
        exterior.addStretch()
        exterior.addWidget(central, 1)
        exterior.addStretch()
        self.setWidget(lienzo)
        principal = QVBoxLayout(central)
        principal.setContentsMargins(0, 0, 0, 0)
        principal.setSpacing(10)

        encabezado = QFrame()
        encabezado.setObjectName("encabezadoActualizaciones")
        encabezado.setStyleSheet("""
            QFrame#encabezadoActualizaciones {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 #ffffff, stop:0.58 #f5fbff, stop:1 #1388ca);
                border: 1px solid #8dbad8; border-radius: 8px;
            }
            QFrame#encabezadoActualizaciones QLabel#titulo {
                color:#102f55; font-size:25px; font-weight:800; background:transparent;
            }
            QFrame#encabezadoActualizaciones QLabel#subtitulo {
                color:#244b70; font-size:15px; background:transparent;
            }
        """)
        caja = QVBoxLayout(encabezado)
        caja.setContentsMargins(20, 12, 20, 12)
        titulo = QLabel("ACTUALIZACIÓN AUTOMÁTICA")
        titulo.setObjectName("titulo")
        subtitulo = QLabel("Flujo de procesamiento operativo")
        subtitulo.setObjectName("subtitulo")
        caja.addWidget(titulo)
        caja.addWidget(subtitulo)
        principal.addWidget(encabezado)

        cuerpo = QHBoxLayout()
        cuerpo.setSpacing(10)
        columna_flujo = QVBoxLayout()
        columna_flujo.setSpacing(10)
        cuerpo.addLayout(columna_flujo, 4)

        tarjeta_flujo = QFrame()
        tarjeta_flujo.setObjectName("tarjeta")
        caja_flujo = QVBoxLayout(tarjeta_flujo)
        caja_flujo.setContentsMargins(14, 11, 14, 12)
        titulo_flujo = QLabel("▣  Flujo común de procesamiento")
        titulo_flujo.setObjectName("tituloTarjeta")
        caja_flujo.addWidget(titulo_flujo)
        pasos = QHBoxLayout()
        self.etiquetas_etapa: Dict[str, QLabel] = {}
        nombres = (
            ("CARGA", "Cargar\narchivos"),
            ("NORMALIZACION", "Preparar CSV\nSANSYS"),
            ("FLUJO_COMUN", "Filtrar fecha y\nvalidar OT–OS"),
            ("DATA_FILTRADA", "DATA FILTRADA"),
        )
        for indice, (clave, nombre) in enumerate(nombres):
            etiqueta = QLabel(f"{nombre}\nPENDIENTE")
            etiqueta.setAlignment(Qt.AlignmentFlag.AlignCenter)
            etiqueta.setMinimumHeight(62)
            etiqueta.setStyleSheet(self._estilo_estado(EstadoEtapa.PENDIENTE))
            pasos.addWidget(etiqueta, 1)
            self.etiquetas_etapa[clave] = etiqueta
            if indice < len(nombres) - 1:
                flecha = QLabel("➜")
                flecha.setStyleSheet("color:#1ba45a; font-size:20px; font-weight:700;")
                pasos.addWidget(flecha)
        caja_flujo.addLayout(pasos)

        entradas = QFrame()
        entradas.setStyleSheet("background:#f8fbfd; border:1px solid #d4e3ee; border-radius:6px;")
        archivos = QVBoxLayout(entradas)
        archivos.setContentsMargins(10, 8, 10, 8)
        archivos.addWidget(QLabel("Archivos de entrada"))
        self.etiquetas_ruta: Dict[str, QLabel] = {}
        self._selector_archivo(
            archivos, "csv_sansys", "Seleccionar CSV SANSYS",
            filtro="CSV SANSYS (*.csv);;Muestra de comparación (*.xlsx *.xlsm);;Todos (*.*)",
        )
        self._selector_archivo(archivos, "control_gio", "Seleccionar control GIO")
        self._selector_archivo(archivos, "entregable_acumulado", "Seleccionar entregable acumulado")
        self._selector_archivo(
            archivos, "libro_reglas", "Seleccionar libro de reglas y actualización",
            filtro="Libro de reglas y actualización (*.xlsx *.xlsm);;Todos (*.*)",
        )
        self._selector_archivo(
            archivos, "matriz_gio", "Seleccionar matriz de reglas GIO",
            filtro="Matriz de reglas GIO (*.xlsx *.xlsm);;Todos (*.*)",
        )
        self.boton_ver_reglas = self._boton(
            "VER REGLAS CARGADAS", self._ver_reglas_cargadas
        )
        self.boton_ver_reglas.setEnabled(False)
        archivos.addWidget(self.boton_ver_reglas)
        caja_flujo.addWidget(entradas)

        fila = QHBoxLayout()
        fila.addWidget(QLabel("Fecha de procesamiento:"))
        self.fecha = QDateEdit(QDate.currentDate())
        self.fecha.setCalendarPopup(True)
        self.fecha.setDisplayFormat("dd/MM/yyyy")
        fila.addWidget(self.fecha)
        self.boton_salida = self._boton("Seleccionar carpeta de salida", self._seleccionar_salida)
        self.etiqueta_salida = QLabel("Ruta: --")
        self.etiqueta_salida.setWordWrap(True)
        fila.addWidget(self.boton_salida)
        fila.addWidget(self.etiqueta_salida, 1)
        caja_flujo.addLayout(fila)
        fila_acciones = QHBoxLayout()
        self.boton_flujo = self._boton("PROCESAR Y GENERAR CIERRES", self._iniciar_flujo_comun, True)
        self.boton_cancelar = self._boton("Cancelar", self._cancelar)
        fila_acciones.addWidget(self.boton_flujo)
        fila_acciones.addWidget(self.boton_cancelar)
        fila_acciones.addStretch()
        caja_flujo.addLayout(fila_acciones)
        columna_flujo.addWidget(tarjeta_flujo)

        ramas = QHBoxLayout()
        ramas.setSpacing(10)
        tarjeta_cierres = QFrame()
        tarjeta_cierres.setObjectName("tarjetaVerde")
        caja_cierres = QVBoxLayout(tarjeta_cierres)
        titulo_cierres = QLabel("▤  CIERRES Y REVISIONES · C / CD / V")
        titulo_cierres.setObjectName("tituloVerde")
        caja_cierres.addWidget(titulo_cierres)
        for texto in ("✓  Validar horas y acciones", "✓  Cruzar lecturas y operarios", "✓  Generar TXT del sistema", "✓  Generar TXT para entregable"):
            etiqueta = QLabel(texto)
            etiqueta.setStyleSheet("padding:5px; color:#24613d;")
            caja_cierres.addWidget(etiqueta)
        self.etiquetas_etapa["CIERRES"] = QLabel("CIERRES\nPENDIENTE")
        self.etiquetas_etapa["CIERRES"].setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.etiquetas_etapa["CIERRES"].setStyleSheet(self._estilo_estado(EstadoEtapa.PENDIENTE))
        caja_cierres.addWidget(self.etiquetas_etapa["CIERRES"])
        self.boton_cierres = self._boton("PROCESAR CIERRES", self._iniciar_cierres, True)
        caja_cierres.addWidget(self.boton_cierres)
        ramas.addWidget(tarjeta_cierres, 1)

        tarjeta_entregable = QFrame()
        tarjeta_entregable.setObjectName("tarjetaAzul")
        caja_entregable = QVBoxLayout(tarjeta_entregable)
        titulo_entregable = QLabel("▣  Entregable actualizado requerido")
        titulo_entregable.setObjectName("tituloTarjeta")
        caja_entregable.addWidget(titulo_entregable)
        explicacion = QLabel("Antes de procesar las reaperturas, actualice los cierres en el sistema y cargue el entregable que contiene esos cierres.")
        explicacion.setWordWrap(True)
        caja_entregable.addWidget(explicacion)
        self.etiquetas_etapa["ENTREGABLE"] = QLabel("ENTREGABLE\nBLOQUEADO")
        self.etiquetas_etapa["ENTREGABLE"].setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.etiquetas_etapa["ENTREGABLE"].setStyleSheet(self._estilo_estado(EstadoEtapa.BLOQUEADO))
        caja_entregable.addWidget(self.etiquetas_etapa["ENTREGABLE"])
        self.boton_entregable = self._boton("Cargar entregable para reaperturas", self._iniciar_carga_entregable, True)
        caja_entregable.addWidget(self.boton_entregable)
        aviso = QLabel("● La rama de reaperturas se habilitará después de validar este archivo.")
        aviso.setWordWrap(True)
        aviso.setStyleSheet("color:#145b91; font-size:11px;")
        caja_entregable.addWidget(aviso)
        caja_entregable.addStretch()
        ramas.addWidget(tarjeta_entregable, 1)

        tarjeta_reaperturas = QFrame()
        tarjeta_reaperturas.setObjectName("tarjetaGris")
        caja_reaperturas = QVBoxLayout(tarjeta_reaperturas)
        titulo_reaperturas = QLabel("▣  REAPERTURAS · R / RD")
        titulo_reaperturas.setObjectName("tituloGris")
        caja_reaperturas.addWidget(titulo_reaperturas)
        for texto in ("●  Cruzar cierre anterior", "●  Validar acción y diferencia", "●  Generar TXT de reaperturas"):
            etiqueta = QLabel(texto)
            etiqueta.setStyleSheet("padding:7px; color:#7d858e;")
            caja_reaperturas.addWidget(etiqueta)
        self.etiquetas_etapa["REAPERTURAS"] = QLabel("REAPERTURAS\nBLOQUEADO")
        self.etiquetas_etapa["REAPERTURAS"].setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.etiquetas_etapa["REAPERTURAS"].setStyleSheet(self._estilo_estado(EstadoEtapa.BLOQUEADO))
        caja_reaperturas.addWidget(self.etiquetas_etapa["REAPERTURAS"])
        self.boton_reaperturas = self._boton("PROCESAR REAPERTURAS", self._iniciar_reaperturas)
        caja_reaperturas.addWidget(self.boton_reaperturas)
        caja_reaperturas.addStretch()
        ramas.addWidget(tarjeta_reaperturas, 1)
        columna_flujo.addLayout(ramas)

        self.boton_cierres.setEnabled(False)
        self.boton_entregable.setEnabled(False)
        self.boton_reaperturas.setEnabled(False)
        self.boton_cancelar.setEnabled(False)
        self.progreso = QProgressBar()
        self.progreso.setRange(0, 100)
        self.etiqueta_estado = QLabel("Estado: listo")
        columna_flujo.addWidget(self.etiqueta_estado)
        columna_flujo.addWidget(self.progreso)

        panel_estado = QFrame()
        panel_estado.setObjectName("panelEstado")
        panel_estado.setMinimumWidth(245)
        panel_estado.setMaximumWidth(310)
        lateral = QVBoxLayout(panel_estado)
        lateral.setContentsMargins(13, 12, 13, 12)
        titulo_estado = QLabel("▥  Estado del proceso")
        titulo_estado.setObjectName("tituloTarjeta")
        lateral.addWidget(titulo_estado)
        lateral.addWidget(QLabel("Data filtrada:      Pendiente"))
        lateral.addWidget(QLabel("Cierres y revisiones: Pendiente"))
        lateral.addWidget(QLabel("TXT del sistema:    Pendiente"))
        lateral.addWidget(QLabel("TXT para entregable: Pendiente"))
        lateral.addWidget(QLabel("Reaperturas:        Esperando archivo"))
        aviso_lateral = QLabel("⚠  No cierre el programa. Puede continuar cuando tenga el entregable actualizado.")
        aviso_lateral.setWordWrap(True)
        aviso_lateral.setStyleSheet("background:#fff5cf; border:1px solid #e5bd45; border-radius:6px; padding:9px; color:#70510a;")
        lateral.addWidget(aviso_lateral)
        self.texto_resumen = QTextEdit()
        self.texto_resumen.setReadOnly(True)
        self.texto_resumen.setMinimumHeight(170)
        self.texto_resumen.setPlainText(
            "Filas cargadas: 0\nDATA_FILTRADA: 0\nCierres listos: 0\n"
            "Reaperturas listas: 0\nRevisiones: 0\nBloqueos: formatos y reglas pendientes se mostrarán aquí."
        )
        lateral.addWidget(self.texto_resumen, 1)
        self.boton_abrir = self._boton("Abrir carpeta de resultados", self._abrir_resultados)
        self.boton_abrir.setEnabled(False)
        lateral.addWidget(self.boton_abrir)
        cuerpo.addWidget(panel_estado, 1)
        principal.addLayout(cuerpo)

        vista = self._seccion(principal, "VISTA PREVIA (MÁXIMO 100 FILAS)")
        self.tabla = QTableWidget(0, 0)
        self.tabla.setMinimumHeight(175)
        vista.addWidget(self.tabla)

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
        if ruta:
            self.rutas[clave] = ruta
            self.etiquetas_ruta[clave].setText(f"Archivo: {Path(ruta).name}\nRuta: {ruta}")
            if clave == "matriz_gio":
                self._validar_matriz_seleccionada(Path(ruta))

    def _validar_matriz_seleccionada(self, ruta: Path) -> None:
        """Valida la matriz al seleccionarla y muestra un resumen verificable."""
        try:
            matriz = leer_matriz_reglas_gio(ruta)
        except Exception as error:
            self.matriz_gio_previsualizada = None
            self.errores_matriz_gio = [linea for linea in str(error).splitlines() if linea.strip()]
            self.boton_ver_reglas.setEnabled(False)
            detalle = "\n".join(self.errores_matriz_gio) or "Error de configuración no especificado."
            self.etiquetas_ruta["matriz_gio"].setText(
                f"Archivo: {ruta.name}\nRuta: {ruta}\nErrores de configuración:\n{detalle}"
                "\nEstado: MATRIZ CON ERRORES"
            )
            self.etiquetas_ruta["matriz_gio"].setStyleSheet("color:#991b1b;")
            return

        self.matriz_gio_previsualizada = matriz
        self.errores_matriz_gio = []
        self.boton_ver_reglas.setEnabled(True)
        self.etiquetas_ruta["matriz_gio"].setText(
            f"Archivo: {ruta.name}\nRuta: {ruta}\n"
            f"Reglas activas: {len(matriz.reglas_activas)} | "
            f"Reglas inactivas: {len(matriz.reglas_inactivas)}\n"
            f"Fecha de modificación: {matriz.fecha_modificacion or 'No disponible'}\n"
            "Errores de configuración: Ninguno\nEstado: MATRIZ VÁLIDA"
        )
        self.etiquetas_ruta["matriz_gio"].setStyleSheet("color:#166534;")

    def _ver_reglas_cargadas(self) -> None:
        """Muestra las reglas de la matriz en una tabla estrictamente de solo lectura."""
        matriz = self.matriz_gio_previsualizada
        if matriz is None:
            QMessageBox.warning(self, "Matriz no válida", "Cargue primero una matriz GIO válida.")
            return
        dialogo = QDialog(self)
        dialogo.setWindowTitle("Reglas GIO cargadas")
        dialogo.resize(1050, 520)
        disposicion = QVBoxLayout(dialogo)
        resumen = QLabel(
            f"{Path(matriz.ruta).name if matriz.ruta else 'Matriz GIO'} — "
            f"{len(matriz.reglas_activas)} activas / {len(matriz.reglas_inactivas)} inactivas"
        )
        disposicion.addWidget(resumen)
        columnas = (
            "ID_REGLA", "PRIORIDAD", "RGLA", "PATRON_OBS", "CONDICION_ACC",
            "ACCIÓN / RANGO", "RESULTADO", "DESTINO", "ACTIVO",
        )
        tabla = QTableWidget(len(matriz.reglas), len(columnas), dialogo)
        tabla.setHorizontalHeaderLabels(columnas)
        tabla.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        tabla.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
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
        disposicion.addWidget(tabla)
        self.tabla_reglas_cargadas = tabla
        dialogo.exec()

    def _seleccionar_salida(self) -> None:
        ruta = QFileDialog.getExistingDirectory(self, "Seleccionar carpeta de salida")
        if ruta:
            self.rutas["carpeta_salida"] = ruta
            self.etiqueta_salida.setText(f"Ruta: {ruta}")

    def _rutas_entradas(self) -> RutasEntradasActualizacion:
        requeridas = (
            "csv_sansys", "control_gio", "entregable_acumulado", "libro_reglas",
            "matriz_gio",
            "carpeta_salida",
        )
        faltantes = [clave for clave in requeridas if not self.rutas.get(clave)]
        if faltantes:
            raise ValueError("Faltan archivos o carpeta: " + ", ".join(faltantes))
        if self.matriz_gio_previsualizada is None:
            detalle = "; ".join(self.errores_matriz_gio) or "La matriz no ha sido validada."
            raise ValueError("La matriz GIO tiene errores de configuración: " + detalle)
        return RutasEntradasActualizacion(
            ruta_csv_sansys=Path(self.rutas["csv_sansys"]),
            ruta_control_gio=Path(self.rutas["control_gio"]),
            ruta_entregable_acumulado=Path(self.rutas["entregable_acumulado"]),
            ruta_libro_reglas=Path(self.rutas["libro_reglas"]),
            carpeta_salida=Path(self.rutas["carpeta_salida"]),
            ruta_matriz_gio=Path(self.rutas["matriz_gio"]),
            configuracion_json=Path(self.rutas["configuracion_json"]) if self.rutas.get("configuracion_json") else None,
        )

    def _iniciar_operacion(self, operacion, al_terminar) -> None:
        if self.hilo:
            QMessageBox.information(self, "Proceso en ejecución", "Espere a que termine la etapa actual.")
            return
        self._al_terminar = al_terminar
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
        self.boton_flujo.setEnabled(False)
        self.hilo.start()

    def _iniciar_flujo_comun(self) -> None:
        try:
            rutas = self._rutas_entradas()
        except ValueError as error:
            QMessageBox.warning(self, "Faltan entradas", str(error))
            return
        self._procesar_cierres_automaticamente = False
        self._cambiar_etapa("CARGA", EstadoEtapa.PROCESANDO)
        fecha = self.fecha.date().toString("dd/MM/yyyy")
        self._iniciar_operacion(
            lambda progreso: self.servicio.procesar_flujo_comun(rutas, fecha, progreso),
            self._flujo_comun_terminado,
        )

    def _iniciar_cierres(self) -> None:
        self._cambiar_etapa("CIERRES", EstadoEtapa.PROCESANDO)
        self._iniciar_operacion(
            lambda progreso: self.servicio.procesar_cierres(progreso), self._cierres_terminados
        )

    def _iniciar_carga_entregable(self) -> None:
        ruta, _ = QFileDialog.getOpenFileName(
            self, "Cargar entregable actualizado de cierres", "",
            "Archivos admitidos (*.txt *.csv *.xlsx *.xlsm);;Todos (*.*)",
        )
        if not ruta:
            return
        self._cambiar_etapa("ENTREGABLE", EstadoEtapa.PROCESANDO)
        self._iniciar_operacion(
            lambda progreso: self.servicio.cargar_entregable_actualizado(Path(ruta)),
            self._entregable_terminado,
        )

    def _iniciar_reaperturas(self) -> None:
        self._cambiar_etapa("REAPERTURAS", EstadoEtapa.PROCESANDO)
        self._iniciar_operacion(
            lambda progreso: self.servicio.procesar_reaperturas(progreso), self._reaperturas_terminadas
        )

    @Slot(str, int, int)
    def _mostrar_progreso(self, etapa: str, actual: int, total: int) -> None:
        self.etiqueta_estado.setText(f"Estado: {etapa}")
        self.progreso.setValue(int(actual * 100 / max(1, total)))

    @Slot(object)
    def _operacion_terminada(self, resultado) -> None:
        if self._al_terminar:
            self._al_terminar(resultado)

    @Slot(str, str)
    def _operacion_fallida(self, mensaje: str, detalle: str) -> None:
        self._procesar_cierres_automaticamente = False
        self.etiqueta_estado.setText("Estado: error")
        self.texto_resumen.append(f"\nERROR: {mensaje}")
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
        self.etiqueta_estado.setText("Estado: operación cancelada")

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
        self.boton_flujo.setEnabled(True)
        if self._procesar_cierres_automaticamente:
            self._procesar_cierres_automaticamente = False
            self.boton_flujo.setEnabled(False)
            QTimer.singleShot(0, self._iniciar_cierres)

    def _cancelar(self) -> None:
        if self.trabajador:
            self.trabajador.solicitar_cancelacion()
            self.etiqueta_estado.setText("Estado: cancelando en el siguiente punto seguro…")

    def _flujo_comun_terminado(self, resultado: ResultadoProceso) -> None:
        self._cambiar_etapa("CARGA", EstadoEtapa.COMPLETADO)
        self._cambiar_etapa("NORMALIZACION", EstadoEtapa.COMPLETADO)
        self._cambiar_etapa("FLUJO_COMUN", resultado.contexto.estados_etapas["FLUJO_COMUN"])
        self._cambiar_etapa("DATA_FILTRADA", EstadoEtapa.COMPLETADO)
        self._cambiar_etapa("CIERRES", EstadoEtapa.LISTO)
        self._cambiar_etapa("REAPERTURAS", EstadoEtapa.BLOQUEADO)
        self.boton_cierres.setEnabled(True)
        self.boton_abrir.setEnabled(True)
        self._actualizar_resumen(resultado)
        self._mostrar_registros(resultado.flujo_comun.data_filtrada if resultado.flujo_comun else [])
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
                "del CSV SANSYS. La auditoría y las exclusiones quedaron guardadas en:\n"
                f"{carpeta}",
            )
            return
        self.etiqueta_estado.setText("Estado: DATA_FILTRADA lista; generando cierres y entregable…")
        self._procesar_cierres_automaticamente = True

    def _cierres_terminados(self, resultado: ResultadoProceso) -> None:
        estado = resultado.contexto.estados_etapas.get("CIERRES", EstadoEtapa.CON_ERRORES)
        self._cambiar_etapa("CIERRES", estado)
        entregable_generado = bool(resultado.contexto.entregable_cierres)
        self.boton_entregable.setEnabled(entregable_generado)
        self._cambiar_etapa("ENTREGABLE", EstadoEtapa.LISTO if entregable_generado else EstadoEtapa.BLOQUEADO)
        self._actualizar_resumen(resultado)
        self._mostrar_registros(resultado.cierres.listas if resultado.cierres else [])
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
                "Ahora puede cargar el entregable actualizado para procesar las reaperturas.",
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
                f"Resultados y auditoría: {carpeta}\n\n"
                "Revise el panel de resumen y los archivos de validación; las filas no "
                "fueron eliminadas silenciosamente.",
            )

    def _entregable_terminado(self, _tabla) -> None:
        self._cambiar_etapa("ENTREGABLE", EstadoEtapa.COMPLETADO)
        self._cambiar_etapa("REAPERTURAS", EstadoEtapa.LISTO)
        self.boton_reaperturas.setEnabled(True)
        self.etiqueta_estado.setText("Estado: entregable actualizado cargado")

    def _reaperturas_terminadas(self, resultado: ResultadoProceso) -> None:
        estado = resultado.contexto.estados_etapas.get("REAPERTURAS", EstadoEtapa.CON_ERRORES)
        self._cambiar_etapa("REAPERTURAS", estado)
        self._actualizar_resumen(resultado)
        self._mostrar_registros(resultado.reaperturas.listas if resultado.reaperturas else [])

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
        ]
        bloqueos = []
        for objeto in (flujo, cierres, reaperturas):
            bloqueos.extend(getattr(objeto, "bloqueos", []) if objeto else [])
        lineas.append("Bloqueos:")
        lineas.extend(f"- {texto}" for texto in bloqueos if texto)
        if not bloqueos:
            lineas.append("- Ninguno en las etapas ejecutadas.")
        self.texto_resumen.setPlainText("\n".join(lineas))
        self.etiqueta_estado.setText("Estado: etapa terminada")
        self.progreso.setValue(100)

    def _mostrar_registros(self, registros) -> None:
        filas = list(registros)[:100]
        columnas = []
        vistos = set()
        for registro in filas:
            for columna in registro.datos_normalizados:
                if columna not in vistos:
                    vistos.add(columna)
                    columnas.append(columna)
        columnas = ["MOTIVO", *columnas]
        self.tabla.clear()
        self.tabla.setRowCount(len(filas))
        self.tabla.setColumnCount(len(columnas))
        self.tabla.setHorizontalHeaderLabels(columnas)
        for fila_indice, registro in enumerate(filas):
            valores = {"MOTIVO": registro.motivo_final, **registro.datos_normalizados}
            for columna_indice, columna in enumerate(columnas):
                self.tabla.setItem(fila_indice, columna_indice, QTableWidgetItem(str(valores.get(columna, ""))))
        self.tabla.resizeColumnsToContents()

    def _abrir_resultados(self) -> None:
        if self.servicio.rutas_salida and self.servicio.rutas_salida.raiz.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.servicio.rutas_salida.raiz)))
        else:
            QMessageBox.warning(self, "Resultados", "Aún no existe una carpeta de resultados.")
