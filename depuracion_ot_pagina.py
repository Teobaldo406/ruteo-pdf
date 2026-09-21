# -*- coding: utf-8 -*-
"""Página del módulo Depuración OT."""

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog, QFrame, QHBoxLayout, QLabel, QMessageBox, QPushButton,
    QScrollArea, QTextEdit, QVBoxLayout, QWidget,
)

from depuracion_ot import depurar_ordenes
from fondo_modulos import FondoModulosWidget


class PaginaDepuracionOT(QScrollArea):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.ruta_reaperturas = self.ruta_accion = self.ruta_plantilla = ""
        self.ruta_salida = ""
        self.resultado = None
        self.etiquetas_archivos = []
        self.setObjectName("areaPrincipal")
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self._construir_interfaz()

    def _crear_boton(self, texto, accion, primario=False):
        boton = QPushButton(texto)
        boton.setObjectName("botonPrimario" if primario else "")
        boton.clicked.connect(accion)
        return boton

    def _crear_seccion(self, principal, titulo):
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

    def _agregar_selector(self, disposicion, texto, atributo_ruta):
        fila = QHBoxLayout()
        fila.setSpacing(10)
        etiqueta = QLabel("Archivo: --")
        etiqueta.setWordWrap(True)
        self.etiquetas_archivos.append(etiqueta)
        boton = self._crear_boton(
            texto, lambda _marcado=False: self._seleccionar_archivo(atributo_ruta, etiqueta))
        fila.addWidget(boton)
        fila.addWidget(etiqueta, 1)
        disposicion.addLayout(fila)

    def _construir_interfaz(self):
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
        encabezado.setObjectName("encabezadoDepuracion")
        encabezado.setStyleSheet("""
            QFrame#encabezadoDepuracion {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #166534, stop:0.52 #15803d, stop:1 #0f766e);
                border: 1px solid #14532d;
                border-radius: 8px;
            }
            QFrame#encabezadoDepuracion QLabel#titulo {
                color: #ffffff; font-size: 20px; font-weight: 700; background: transparent;
            }
            QFrame#encabezadoDepuracion QLabel#subtitulo {
                color: #dcfce7; background: transparent;
            }
        """)
        caja_encabezado = QVBoxLayout(encabezado)
        caja_encabezado.setContentsMargins(18, 12, 18, 12)
        caja_encabezado.setSpacing(2)
        titulo = QLabel("DEPURACIÓN OT")
        titulo.setObjectName("titulo")
        titulo.setAlignment(Qt.AlignCenter)
        subtitulo = QLabel("Depura Acción contra Reaperturas y filtra la Plantilla por número de OT.")
        subtitulo.setObjectName("subtitulo")
        subtitulo.setAlignment(Qt.AlignCenter)
        caja_encabezado.addWidget(titulo)
        caja_encabezado.addWidget(subtitulo)
        principal.addWidget(encabezado)

        archivos = self._crear_seccion(principal, "ARCHIVOS DEL PROCESO")
        self._agregar_selector(archivos, "Seleccionar Reaperturas", "ruta_reaperturas")
        self._agregar_selector(archivos, "Seleccionar Acción", "ruta_accion")
        self._agregar_selector(archivos, "Seleccionar Plantilla", "ruta_plantilla")

        configuracion = self._crear_seccion(principal, "CONFIGURACIÓN")
        fila_salida = QHBoxLayout()
        fila_salida.setSpacing(10)
        fila_salida.addWidget(self._crear_boton("Carpeta de salida", self._seleccionar_salida))
        self.etiqueta_salida = QLabel("Ruta: --")
        self.etiqueta_salida.setWordWrap(True)
        fila_salida.addWidget(self.etiqueta_salida, 1)
        configuracion.addLayout(fila_salida)

        self.boton_depurar = self._crear_boton("DEPURAR ÓRDENES", self._ejecutar_depuracion, True)
        self.boton_depurar.setMinimumHeight(38)
        principal.addWidget(self.boton_depurar)
        self.etiqueta_estado = QLabel("Estado: listo")
        self.etiqueta_estado.setAlignment(Qt.AlignCenter)
        principal.addWidget(self.etiqueta_estado)

        resumen = self._crear_seccion(principal, "RESUMEN DEL PROCESO")
        self.texto_resumen = QTextEdit()
        self.texto_resumen.setReadOnly(True)
        self.texto_resumen.setMinimumHeight(120)
        self.texto_resumen.setMaximumHeight(135)
        self.texto_resumen.setPlainText(self._resumen_inicial())
        resumen.addWidget(self.texto_resumen)

        principal.addStretch()

    @staticmethod
    def _resumen_inicial():
        return (
            "Acción original: 0\nAcción eliminada: 0\nAcción conservada: 0\n"
            "Plantilla original: 0\nPlantilla eliminada: 0\nPlantilla conservada: 0\n"
            "Resultado: --"
        )

    def _seleccionar_archivo(self, atributo_ruta, etiqueta):
        ruta, _ = QFileDialog.getOpenFileName(
            self, "Seleccionar archivo CSV o TXT", "",
            "Archivos CSV o TXT (*.csv *.txt);;Todos los archivos (*.*)")
        if ruta:
            setattr(self, atributo_ruta, ruta)
            etiqueta.setText(f"Archivo: {Path(ruta).name}\nRuta: {ruta}")

    def _seleccionar_salida(self):
        carpeta = QFileDialog.getExistingDirectory(self, "Seleccionar carpeta de salida")
        if carpeta:
            self.ruta_salida = carpeta
            self.etiqueta_salida.setText(f"Ruta: {carpeta}")

    def _ejecutar_depuracion(self):
        if not all((self.ruta_reaperturas, self.ruta_accion, self.ruta_plantilla)):
            QMessageBox.warning(self, "Depuración OT", "Seleccione los tres archivos CSV o TXT.")
            return
        if not self.ruta_salida:
            QMessageBox.warning(self, "Depuración OT", "Seleccione la carpeta de salida.")
            return

        self.etiqueta_estado.setText("Estado: depurando órdenes…")
        self.boton_depurar.setEnabled(False)
        self.resultado = None
        try:
            resultado = depurar_ordenes(
                Path(self.ruta_reaperturas), Path(self.ruta_accion),
                Path(self.ruta_plantilla), Path(self.ruta_salida))
        except Exception as error:
            self.etiqueta_estado.setText("Estado: error")
            QMessageBox.warning(self, "Depuración OT", str(error))
            return
        finally:
            self.boton_depurar.setEnabled(True)

        self.resultado = resultado
        eliminadas_accion = resultado.total_accion_original - resultado.filas_accion
        eliminadas_plantilla = resultado.total_plantilla_original - resultado.filas_plantilla
        self.texto_resumen.setPlainText(
            f"Acción original: {resultado.total_accion_original}\n"
            f"Acción eliminada: {eliminadas_accion}\n"
            f"Acción conservada: {resultado.filas_accion}\n"
            f"Plantilla original: {resultado.total_plantilla_original}\n"
            f"Plantilla eliminada: {eliminadas_plantilla}\n"
            f"Plantilla conservada: {resultado.filas_plantilla}\n"
            f"Resultado: {self.ruta_salida}")
        self.etiqueta_estado.setText("Estado: proceso finalizado")
        QMessageBox.information(self, "Depuración OT", "Proceso terminado correctamente.")
