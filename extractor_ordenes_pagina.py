# -*- coding: utf-8 -*-
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QThread, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QButtonGroup, QFileDialog, QFrame, QHBoxLayout, QLabel, QMessageBox,
    QProgressBar, QPushButton, QRadioButton, QScrollArea, QTextEdit,
    QVBoxLayout, QWidget,
)
from extractor_ordenes import cargar_consolidado, cargar_lista_codigos, extraer_registros
from fondo_modulos import FondoModulosWidget


class TrabajadorExtraccion(QObject):
    progreso = Signal(int)
    terminado = Signal(object)
    error = Signal(str)
    cancelado = Signal()

    def __init__(self, consolidado, lista, tipo, carpeta):
        super().__init__()
        self.datos = consolidado, lista, tipo, carpeta
        self.detener = False

    @Slot()
    def ejecutar(self):
        try:
            resultado = extraer_registros(
                *self.datos, progreso=self.progreso.emit, cancelado=lambda: self.detener
            )
            self.terminado.emit(resultado)
        except InterruptedError:
            self.cancelado.emit()
        except Exception as exc:
            self.error.emit(str(exc))


class PaginaExtractorOrdenes(QScrollArea):
    senal_volver = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.consolidado = self.lista = self.resultado = None
        self.carpeta_salida = ""
        self.hilo = self.trabajador = None
        self.setObjectName("areaPrincipal")
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self._construir()

    def _boton(self, texto, accion, primario=False):
        boton = QPushButton(texto)
        boton.setObjectName("botonPrimario" if primario else "")
        boton.clicked.connect(accion)
        return boton

    def _seccion(self, principal, titulo):
        panel = QFrame()
        panel.setObjectName("panel")
        caja = QVBoxLayout(panel)
        caja.setContentsMargins(14, 10, 14, 12)
        caja.setSpacing(6)
        etiqueta = QLabel(titulo)
        etiqueta.setObjectName("tituloPanel")
        cuerpo = QWidget()
        caja.addWidget(etiqueta)
        caja.addWidget(cuerpo)
        principal.addWidget(panel)
        disposicion = QVBoxLayout(cuerpo)
        disposicion.setContentsMargins(0, 0, 0, 0)
        disposicion.setSpacing(8)
        return disposicion

    def _construir(self):
        lienzo, central = FondoModulosWidget(), QWidget()
        central.setObjectName("contenedorCentral")
        central.setMinimumWidth(680)
        central.setMaximumWidth(840)
        exterior = QHBoxLayout(lienzo)
        exterior.setContentsMargins(18, 14, 18, 14)
        exterior.addStretch()
        exterior.addWidget(central)
        exterior.addStretch()
        self.setWidget(lienzo)
        principal = QVBoxLayout(central)
        principal.setContentsMargins(0, 0, 0, 0)
        principal.setSpacing(8)

        encabezado = QFrame()
        encabezado.setObjectName("encabezadoExtractor")
        encabezado.setStyleSheet("""
            QFrame#encabezadoExtractor {
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:0,
                    stop:0 #166534,
                    stop:0.52 #15803d,
                    stop:1 #0f766e
                );
                border: 1px solid #14532d;
                border-radius: 8px;
            }
            QFrame#encabezadoExtractor QLabel#titulo {
                color: #ffffff;
                font-size: 20px;
                font-weight: 700;
                background: transparent;
            }
            QFrame#encabezadoExtractor QLabel#subtitulo {
                color: #dcfce7;
                background: transparent;
            }
        """)
        caja = QVBoxLayout(encabezado)
        caja.setContentsMargins(18, 12, 18, 12)
        caja.setSpacing(2)
        titulo = QLabel("EXTRACTOR DE ÓRDENES")
        titulo.setObjectName("titulo")
        titulo.setAlignment(Qt.AlignCenter)
        subtitulo = QLabel("Busca códigos exactos en un consolidado TXT.")
        subtitulo.setObjectName("subtitulo")
        subtitulo.setAlignment(Qt.AlignCenter)
        caja.addWidget(titulo)
        caja.addWidget(subtitulo)
        principal.addWidget(encabezado)

        entrada = self._seccion(principal, "ARCHIVOS DE BÚSQUEDA")
        fila = QHBoxLayout()
        fila.setSpacing(10)
        fila.addWidget(self._boton("Cargar consolidado TXT", self.seleccionar_consolidado))
        self.info_consolidado = QLabel("Archivo: --\nRegistros detectados: 0")
        self.info_consolidado.setWordWrap(True)
        fila.addWidget(self.info_consolidado, 1)
        entrada.addLayout(fila)

        fila = QHBoxLayout()
        fila.setSpacing(10)
        fila.addWidget(self._boton("Cargar lista de códigos", self.seleccionar_lista))
        self.info_codigos = QLabel("Archivo: --\nCódigos detectados: 0")
        self.info_codigos.setWordWrap(True)
        fila.addWidget(self.info_codigos, 1)
        entrada.addLayout(fila)

        opciones = self._seccion(principal, "CONFIGURACIÓN")
        fila = QHBoxLayout()
        fila.setSpacing(18)
        fila.addWidget(QLabel("Buscar por:"))
        self.grupo_tipo = QButtonGroup(self)
        for texto in ("NIS", "OT", "OS"):
            radio = QRadioButton(texto)
            radio.setChecked(texto == "OT")
            self.grupo_tipo.addButton(radio)
            fila.addWidget(radio)
        fila.addStretch()
        opciones.addLayout(fila)

        fila = QHBoxLayout()
        fila.setSpacing(10)
        fila.addWidget(self._boton("Carpeta de salida", self.seleccionar_carpeta))
        self.info_salida = QLabel("Ruta: RESULTADOS_BUSQUEDA junto al consolidado")
        self.info_salida.setWordWrap(True)
        fila.addWidget(self.info_salida, 1)
        opciones.addLayout(fila)

        fila = QHBoxLayout()
        self.boton_buscar = self._boton("BUSCAR Y EXTRAER REGISTROS", self.iniciar, True)
        self.boton_cancelar = self._boton("Cancelar búsqueda", self.cancelar)
        self.boton_cancelar.setEnabled(False)
        self.boton_buscar.setMinimumHeight(38)
        fila.addWidget(self.boton_buscar)
        fila.addWidget(self.boton_cancelar)
        fila.addWidget(self._boton("Volver", self.senal_volver.emit))
        principal.addLayout(fila)
        self.estado = QLabel("Estado: listo")
        self.estado.setAlignment(Qt.AlignCenter)
        self.progreso = QProgressBar()
        self.progreso.setFormat("%p %")
        self.progreso.setMaximumHeight(18)
        principal.addWidget(self.estado)
        principal.addWidget(self.progreso)

        resumen = self._seccion(principal, "RESUMEN DEL PROCESO")
        self.texto_resumen = QTextEdit()
        self.texto_resumen.setReadOnly(True)
        self.texto_resumen.setMinimumHeight(120)
        self.texto_resumen.setMaximumHeight(135)
        self.texto_resumen.setPlainText(self._resumen_inicial())
        resumen.addWidget(self.texto_resumen)

        fila = QHBoxLayout()
        fila.setSpacing(8)
        self.boton_abrir = self._boton("Abrir resultado", lambda: self._abrir("ruta_encontrados"))
        self.boton_faltantes = self._boton("Abrir no encontrados", lambda: self._abrir("ruta_no_encontrados"))
        self.boton_carpeta = self._boton("Abrir carpeta", lambda: self._abrir("carpeta_salida"))
        for boton in (self.boton_abrir, self.boton_faltantes, self.boton_carpeta):
            fila.addWidget(boton)
        fila.addWidget(self._boton("Limpiar módulo", self.limpiar))
        principal.addLayout(fila)
        principal.addStretch()
        self._habilitar_resultados(False)

    def _resumen_inicial(self):
        return ("Tipo de búsqueda: OT\nRegistros del consolidado: 0\nCódigos solicitados: 0\n"
                "Códigos encontrados: 0\nCódigos no encontrados: 0\nFilas extraídas: 0\n"
                "Códigos repetidos: 0\nCódigos con múltiples coincidencias: 0\nResultado: --")

    def _error(self, texto):
        QMessageBox.warning(self, "Extractor de órdenes", texto)

    def seleccionar_consolidado(self):
        ruta, _ = QFileDialog.getOpenFileName(self, "Cargar consolidado TXT", "", "TXT (*.txt);;Todos (*.*)")
        if not ruta:
            return
        try:
            self.consolidado = cargar_consolidado(ruta)
            separador = {"\t": "tabulación", ";": "punto y coma", "|": "barra vertical"}.get(
                self.consolidado.separador, "espacios múltiples")
            self.info_consolidado.setText(
                f"Archivo: {Path(ruta).name}\nRegistros detectados: {self.consolidado.total_registros} · {separador}")
        except Exception as exc:
            self.consolidado = None
            self._error(str(exc))

    def seleccionar_lista(self):
        ruta, _ = QFileDialog.getOpenFileName(self, "Cargar lista de códigos", "", "TXT (*.txt);;Todos (*.*)")
        if not ruta:
            return
        try:
            self.lista = cargar_lista_codigos(ruta)
            self.info_codigos.setText(
                f"Archivo: {Path(ruta).name}\nCódigos detectados: {len(self.lista.codigos)} "
                f"· Duplicados ignorados: {self.lista.repetidos}")
        except Exception as exc:
            self.lista = None
            self._error(str(exc))

    def seleccionar_carpeta(self):
        ruta = QFileDialog.getExistingDirectory(self, "Seleccionar carpeta de resultados")
        if ruta:
            self.carpeta_salida = ruta
            self.info_salida.setText(f"Ruta: {ruta}")

    def iniciar(self):
        if not self.consolidado or not self.lista:
            self._error("Cargue el consolidado principal y la lista de códigos antes de buscar.")
            return
        radio = self.grupo_tipo.checkedButton()
        if not radio:
            self._error("Seleccione NIS, OT u OS.")
            return
        self.resultado = None
        self._habilitar_resultados(False)
        self.estado.setText("Estado: buscando registros…")
        self.boton_buscar.setEnabled(False)
        self.boton_cancelar.setEnabled(True)
        self.hilo = QThread(self)
        self.trabajador = TrabajadorExtraccion(
            self.consolidado, self.lista, radio.text(), self.carpeta_salida or None)
        self.trabajador.moveToThread(self.hilo)
        self.hilo.started.connect(self.trabajador.ejecutar)
        self.trabajador.progreso.connect(self.progreso.setValue)
        self.trabajador.terminado.connect(self._terminado)
        self.trabajador.error.connect(self._fallo)
        self.trabajador.cancelado.connect(self._cancelado)
        for señal in (self.trabajador.terminado, self.trabajador.error, self.trabajador.cancelado):
            señal.connect(self.hilo.quit)
        self.hilo.finished.connect(self._liberar)
        self.hilo.start()

    def cancelar(self):
        if self.trabajador:
            self.trabajador.detener = True
            self.estado.setText("Estado: cancelando…")

    @Slot(object)
    def _terminado(self, r):
        self.resultado = r
        self.progreso.setValue(100)
        self.estado.setText("Estado: proceso finalizado")
        self.texto_resumen.setPlainText(
            f"Tipo de búsqueda: {r.tipo_busqueda}\nRegistros del consolidado: {r.total_registros}\n"
            f"Códigos solicitados: {r.total_solicitados}\nCódigos encontrados: {r.codigos_encontrados}\n"
            f"Códigos no encontrados: {r.codigos_no_encontrados}\nFilas extraídas: {r.filas_extraidas}\n"
            f"Códigos repetidos: {r.codigos_repetidos}\n"
            f"Códigos con múltiples coincidencias: {r.codigos_con_multiples_coincidencias}\n"
            f"Resultado: {r.ruta_encontrados}")
        self._habilitar_resultados(True)

    @Slot(str)
    def _fallo(self, texto):
        self.estado.setText("Estado: error")
        self._error(texto)

    @Slot()
    def _cancelado(self):
        self.estado.setText("Estado: búsqueda cancelada")

    @Slot()
    def _liberar(self):
        self.trabajador.deleteLater()
        self.hilo.deleteLater()
        self.trabajador = self.hilo = None
        self.boton_buscar.setEnabled(True)
        self.boton_cancelar.setEnabled(False)

    def _habilitar_resultados(self, valor):
        for boton in (self.boton_abrir, self.boton_faltantes, self.boton_carpeta):
            boton.setEnabled(valor)

    def _abrir(self, atributo):
        ruta = getattr(self.resultado, atributo, None) if self.resultado else None
        if ruta and Path(ruta).exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(ruta)))
        else:
            self._error("El archivo o la carpeta ya no existe.")

    def limpiar(self):
        if self.hilo:
            self._error("Cancele la búsqueda antes de limpiar.")
            return
        self.consolidado = self.lista = self.resultado = None
        self.carpeta_salida = ""
        self.info_consolidado.setText("Archivo: --\nRegistros detectados: 0")
        self.info_codigos.setText("Archivo: --\nCódigos detectados: 0")
        self.info_salida.setText("Ruta: RESULTADOS_BUSQUEDA junto al consolidado")
        for radio in self.grupo_tipo.buttons():
            radio.setChecked(radio.text() == "OT")
        self.progreso.setValue(0)
        self.estado.setText("Estado: listo")
        self.texto_resumen.setPlainText(self._resumen_inicial())
        self._habilitar_resultados(False)
