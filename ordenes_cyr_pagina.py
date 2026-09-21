# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
import threading
import traceback
from pathlib import Path

from PySide6.QtCore import QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ordenes_cyr_pdf import generar_ordenes_cyr_pdf, leer_datos_libro, listar_nombres_hojas


def ruta_recurso(*partes: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base.joinpath(*partes)


class PaginaOrdenesCyr(QWidget):
    senal_volver = Signal()
    senal_registro = Signal(str)
    senal_progreso = Signal(int, int)
    senal_finalizado = Signal(object)
    senal_error = Signal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.proceso_activo = False
        self.ultima_carpeta_salida = ""
        self.ruta_plantilla_original = ruta_recurso("assets", "plantillas", "cyr.pdf")
        self.ruta_plantilla_personalizada = ""

        self.setObjectName("paginaOrdenes")
        self.setMinimumSize(780, 560)

        self.senal_registro.connect(self._agregar_registro)
        self.senal_progreso.connect(self._actualizar_progreso)
        self.senal_finalizado.connect(self._finalizar_correcto)
        self.senal_error.connect(self._finalizar_error)

        self._construir_interfaz()

    def _construir_interfaz(self) -> None:
        pagina = QHBoxLayout(self)
        pagina.setContentsMargins(12, 10, 12, 10)
        pagina.setSpacing(0)

        contenedor = QWidget()
        contenedor.setObjectName("contenedorOrdenes")
        contenedor.setMinimumWidth(760)
        contenedor.setMaximumWidth(1080)
        pagina.addStretch(1)
        pagina.addWidget(contenedor, 4)
        pagina.addStretch(1)

        raiz = QVBoxLayout(contenedor)
        raiz.setContentsMargins(0, 0, 0, 0)
        raiz.setSpacing(10)

        encabezado = QFrame()
        encabezado.setObjectName("encabezadoOrdenes")
        encabezado_layout = QVBoxLayout(encabezado)
        encabezado_layout.setContentsMargins(14, 10, 14, 10)
        encabezado_layout.setSpacing(1)
        titulo = QLabel("Ordenes CyR")
        titulo.setObjectName("titulo")
        subtitulo = QLabel("generacion con plantilla PDF y firmas por DNI")
        subtitulo.setObjectName("subtitulo")
        encabezado_layout.addWidget(titulo)
        encabezado_layout.addWidget(subtitulo)
        raiz.addWidget(encabezado)

        grilla = QGridLayout()
        grilla.setContentsMargins(0, 0, 0, 0)
        grilla.setHorizontalSpacing(10)
        grilla.setVerticalSpacing(10)
        raiz.addLayout(grilla)

        self.entrada_excel = QLineEdit()
        self.entrada_excel.setPlaceholderText("Archivo .xlsx, .xlsm o .csv")
        self.combo_hoja = QComboBox()
        self.combo_hoja.setMinimumHeight(32)
        tarjeta_datos = self._crear_tarjeta("Datos")
        tarjeta_datos.layout().addLayout(self._fila_ruta(self.entrada_excel, "Seleccionar", self._seleccionar_excel))
        tarjeta_datos.layout().addLayout(self._fila_combo("Hoja", self.combo_hoja, "Leer hojas", self._cargar_hojas))
        grilla.addWidget(tarjeta_datos, 0, 0)

        tarjeta_plantilla = self._crear_tarjeta("Plantilla")
        self.grupo_plantilla = QButtonGroup(self)
        self.grupo_plantilla.setExclusive(True)
        self.boton_plantilla_original = QPushButton("Original")
        self.boton_plantilla_personalizada_tipo = QPushButton("Personalizada")
        for boton_tipo in (self.boton_plantilla_original, self.boton_plantilla_personalizada_tipo):
            boton_tipo.setCheckable(True)
            boton_tipo.setMinimumHeight(34)
        self.boton_plantilla_original.setObjectName("botonSegmentoIzquierdo")
        self.boton_plantilla_personalizada_tipo.setObjectName("botonSegmentoDerecho")
        self.boton_plantilla_original.setChecked(True)
        self.grupo_plantilla.addButton(self.boton_plantilla_original)
        self.grupo_plantilla.addButton(self.boton_plantilla_personalizada_tipo)

        fila_tipo_plantilla = QHBoxLayout()
        fila_tipo_plantilla.setContentsMargins(0, 0, 0, 0)
        fila_tipo_plantilla.setSpacing(0)
        fila_tipo_plantilla.addWidget(self.boton_plantilla_original)
        fila_tipo_plantilla.addWidget(self.boton_plantilla_personalizada_tipo)

        fila_archivo_plantilla = QHBoxLayout()
        fila_archivo_plantilla.setContentsMargins(0, 0, 0, 0)
        fila_archivo_plantilla.setSpacing(8)
        self.etiqueta_plantilla = QLabel()
        self.etiqueta_plantilla.setObjectName("etiquetaArchivo")
        self.boton_plantilla_personalizada = QPushButton("Cargar PDF")
        self.boton_plantilla_personalizada.clicked.connect(self._seleccionar_plantilla)
        fila_archivo_plantilla.addWidget(self.etiqueta_plantilla, 1)
        fila_archivo_plantilla.addWidget(self.boton_plantilla_personalizada)

        tarjeta_plantilla.layout().addLayout(fila_tipo_plantilla)
        tarjeta_plantilla.layout().addLayout(fila_archivo_plantilla)
        self.boton_plantilla_original.toggled.connect(self._actualizar_estado_plantilla)
        self.boton_plantilla_personalizada_tipo.toggled.connect(self._actualizar_estado_plantilla)
        self._actualizar_estado_plantilla()
        grilla.addWidget(tarjeta_plantilla, 0, 1)

        self.entrada_firmas = QLineEdit()
        self.entrada_firmas.setPlaceholderText("Carpeta de firmas")
        tarjeta_firmas = self._crear_tarjeta("Firmas")
        tarjeta_firmas.layout().addLayout(self._fila_ruta(self.entrada_firmas, "Seleccionar", self._seleccionar_firmas))
        grilla.addWidget(tarjeta_firmas, 1, 0)

        self.entrada_salida = QLineEdit()
        self.entrada_salida.setPlaceholderText("Carpeta de salida")
        tarjeta_salida = self._crear_tarjeta("Salida")
        tarjeta_salida.layout().addLayout(self._fila_ruta(self.entrada_salida, "Seleccionar", self._seleccionar_salida))
        grilla.addWidget(tarjeta_salida, 1, 1)

        tarjeta_generacion = self._crear_tarjeta("Generacion")
        fila_acciones = QHBoxLayout()
        fila_acciones.setContentsMargins(0, 0, 0, 0)
        fila_acciones.setSpacing(8)
        self.boton_generar = QPushButton("Generar ordenes")
        self.boton_generar.setObjectName("botonPrimario")
        self.boton_generar.clicked.connect(self._iniciar_generacion)
        self.boton_abrir_salida = QPushButton("Abrir salida")
        self.boton_abrir_salida.clicked.connect(self._abrir_carpeta_salida)
        self.boton_volver = QPushButton("Volver")
        self.boton_volver.clicked.connect(self.senal_volver.emit)
        self.progreso = QProgressBar()
        self.progreso.setRange(0, 1)
        self.progreso.setValue(0)
        self.etiqueta_progreso = QLabel("0/0")
        fila_acciones.addWidget(self.boton_generar)
        fila_acciones.addWidget(self.boton_abrir_salida)
        fila_acciones.addWidget(self.boton_volver)
        fila_acciones.addWidget(self.progreso, 1)
        fila_acciones.addWidget(self.etiqueta_progreso)
        tarjeta_generacion.layout().addLayout(fila_acciones)
        raiz.addWidget(tarjeta_generacion)

        self.registro = QTextEdit()
        self.registro.setObjectName("registro")
        self.registro.setReadOnly(True)
        self.registro.setMinimumHeight(180)
        raiz.addWidget(self.registro, 1)

        self.setStyleSheet("""
            QWidget#paginaOrdenes {
                background: #edf2f7;
            }
            QWidget#contenedorOrdenes {
                background: transparent;
            }
            QFrame#encabezadoOrdenes {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #174ea6, stop:1 #0f766e);
                border: 1px solid #155e75;
                border-radius: 8px;
            }
            QLabel#titulo {
                background: transparent;
                color: #ffffff;
                font-size: 17pt;
                font-weight: 700;
            }
            QLabel#subtitulo {
                background: transparent;
                color: #dbeafe;
                font-size: 9pt;
            }
            QFrame#tarjeta {
                background: #ffffff;
                border: 1px solid #d7dee8;
                border-radius: 8px;
            }
            QLabel#tituloTarjeta {
                background: transparent;
                color: #174ea6;
                font-weight: 700;
            }
            QLabel#etiquetaArchivo {
                min-height: 30px;
                border: 1px solid #d7dee8;
                border-radius: 5px;
                padding: 4px 8px;
                background: #f8fafc;
                color: #334155;
            }
            QLineEdit, QComboBox {
                min-height: 30px;
                border: 1px solid #cbd5e1;
                border-radius: 5px;
                padding: 4px 7px;
                background: #ffffff;
            }
            QPushButton {
                min-height: 31px;
                padding: 5px 11px;
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                background: #ffffff;
            }
            QPushButton:hover {
                background: #e8f0fe;
                color: #174ea6;
            }
            QPushButton#botonPrimario {
                background: #174ea6;
                border-color: #174ea6;
                color: #ffffff;
                font-weight: 700;
            }
            QPushButton#botonPrimario:hover {
                background: #0f3f86;
            }
            QPushButton#botonSegmentoIzquierdo,
            QPushButton#botonSegmentoDerecho {
                min-height: 32px;
                padding: 5px 10px;
                border: 1px solid #cbd5e1;
                border-radius: 0px;
                background: #f8fafc;
                color: #334155;
                font-weight: 600;
            }
            QPushButton#botonSegmentoIzquierdo {
                border-top-left-radius: 6px;
                border-bottom-left-radius: 6px;
            }
            QPushButton#botonSegmentoDerecho {
                border-top-right-radius: 6px;
                border-bottom-right-radius: 6px;
            }
            QPushButton#botonSegmentoIzquierdo:checked,
            QPushButton#botonSegmentoDerecho:checked {
                background: #174ea6;
                border-color: #174ea6;
                color: #ffffff;
            }
            QPushButton#botonSegmentoIzquierdo:hover:!checked,
            QPushButton#botonSegmentoDerecho:hover:!checked {
                background: #e8f0fe;
                color: #174ea6;
            }
            QTextEdit#registro {
                background: #0f172a;
                color: #e2e8f0;
                border-radius: 8px;
                padding: 8px;
                font-family: Consolas, "Courier New";
                font-size: 8.5pt;
            }
        """)

    def _crear_tarjeta(self, titulo: str) -> QFrame:
        tarjeta = QFrame()
        tarjeta.setObjectName("tarjeta")
        layout = QVBoxLayout(tarjeta)
        layout.setContentsMargins(12, 10, 12, 12)
        layout.setSpacing(8)
        etiqueta = QLabel(titulo)
        etiqueta.setObjectName("tituloTarjeta")
        layout.addWidget(etiqueta)
        return tarjeta

    def _fila_ruta(self, entrada: QLineEdit, texto_boton: str, accion) -> QHBoxLayout:
        fila = QHBoxLayout()
        fila.setContentsMargins(0, 0, 0, 0)
        fila.setSpacing(8)
        boton = QPushButton(texto_boton)
        boton.clicked.connect(accion)
        fila.addWidget(entrada, 1)
        fila.addWidget(boton)
        return fila

    def _fila_combo(self, texto_etiqueta: str, combo: QComboBox, texto_boton: str, accion) -> QHBoxLayout:
        fila = QHBoxLayout()
        fila.setContentsMargins(0, 0, 0, 0)
        fila.setSpacing(8)
        etiqueta = QLabel(texto_etiqueta)
        boton = QPushButton(texto_boton)
        boton.clicked.connect(accion)
        fila.addWidget(etiqueta)
        fila.addWidget(combo, 1)
        fila.addWidget(boton)
        return fila

    def _seleccionar_excel(self) -> None:
        ruta, _ = QFileDialog.getOpenFileName(
            self,
            "Seleccionar archivo",
            "",
            "Excel o CSV (*.xlsx *.xlsm *.csv);;Excel (*.xlsx *.xlsm);;CSV (*.csv);;Todos (*.*)",
        )
        if ruta:
            self.entrada_excel.setText(ruta)
            self._cargar_hojas()

    def _seleccionar_plantilla(self) -> None:
        ruta, _ = QFileDialog.getOpenFileName(self, "Seleccionar plantilla PDF", "", "PDF (*.pdf);;Todos (*.*)")
        if ruta:
            self.ruta_plantilla_personalizada = ruta
            self.boton_plantilla_personalizada_tipo.setChecked(True)
            self._actualizar_estado_plantilla()

    def _actualizar_estado_plantilla(self) -> None:
        usar_personalizada = self.boton_plantilla_personalizada_tipo.isChecked()
        self.boton_plantilla_personalizada.setEnabled(usar_personalizada)
        if usar_personalizada:
            nombre = Path(self.ruta_plantilla_personalizada).name if self.ruta_plantilla_personalizada else "Sin PDF seleccionado"
            self.etiqueta_plantilla.setText(nombre)
        elif self.ruta_plantilla_original.exists():
            self.etiqueta_plantilla.setText("cyr.pdf")
        else:
            self.etiqueta_plantilla.setText("Plantilla original no encontrada")

    def _obtener_ruta_plantilla(self) -> str:
        if self.boton_plantilla_original.isChecked():
            return str(self.ruta_plantilla_original)
        return self.ruta_plantilla_personalizada.strip()

    def _seleccionar_firmas(self) -> None:
        ruta = QFileDialog.getExistingDirectory(self, "Seleccionar carpeta de firmas")
        if ruta:
            self.entrada_firmas.setText(ruta)

    def _seleccionar_salida(self) -> None:
        ruta = QFileDialog.getExistingDirectory(self, "Seleccionar carpeta de salida")
        if ruta:
            self.entrada_salida.setText(ruta)

    def _cargar_hojas(self) -> None:
        ruta = self.entrada_excel.text().strip()
        if not ruta:
            QMessageBox.warning(self, "Falta archivo", "Selecciona el archivo de datos.")
            return
        try:
            nombres = listar_nombres_hojas(ruta)
            if not nombres:
                raise ValueError("No se encontraron hojas.")
            self.combo_hoja.clear()
            self.combo_hoja.addItems(nombres)
            self._agregar_registro("Hojas detectadas: " + ", ".join(nombres))
        except Exception as exc:
            QMessageBox.critical(self, "No se pudo leer el archivo", str(exc))

    def _validar_datos(self) -> Optional[dict]:
        valores = {
            "excel": self.entrada_excel.text().strip(),
            "hoja": self.combo_hoja.currentText().strip(),
            "plantilla": self._obtener_ruta_plantilla(),
            "firmas": self.entrada_firmas.text().strip(),
            "salida": self.entrada_salida.text().strip(),
        }
        if not valores["excel"]:
            QMessageBox.warning(self, "Falta archivo", "Selecciona el archivo de datos.")
            return None
        if not valores["hoja"]:
            QMessageBox.warning(self, "Falta hoja", "Selecciona la hoja del archivo.")
            return None
        if not valores["plantilla"]:
            QMessageBox.warning(self, "Falta plantilla", "Selecciona la plantilla PDF.")
            return None
        if not Path(valores["plantilla"]).exists():
            QMessageBox.warning(self, "Plantilla no encontrada", "No se encontro la plantilla PDF seleccionada.")
            return None
        if not valores["firmas"]:
            QMessageBox.warning(self, "Faltan firmas", "Selecciona la carpeta de firmas.")
            return None
        if not valores["salida"]:
            QMessageBox.warning(self, "Falta salida", "Selecciona la carpeta de salida.")
            return None
        return valores

    def _iniciar_generacion(self) -> None:
        if self.proceso_activo:
            QMessageBox.information(self, "Proceso en ejecucion", "Espera a que termine la generacion.")
            return
        configuracion = self._validar_datos()
        if not configuracion:
            return

        self.proceso_activo = True
        self.boton_generar.setEnabled(False)
        self.registro.clear()
        self._actualizar_progreso(0, 0)
        self._agregar_registro("Iniciando generacion...")
        threading.Thread(target=lambda: self._ejecutar_generacion(configuracion), daemon=True).start()

    def _ejecutar_generacion(self, configuracion: dict) -> None:
        try:
            datos = leer_datos_libro(configuracion["excel"], configuracion["hoja"])
            resultado = generar_ordenes_cyr_pdf(
                encabezados=datos.encabezados,
                filas=datos.filas,
                plantilla_pdf=configuracion["plantilla"],
                carpeta_firmas=configuracion["firmas"],
                carpeta_salida=configuracion["salida"],
                funcion_progreso=lambda hecho, total: self.senal_progreso.emit(hecho, total),
                funcion_registro=lambda mensaje: self.senal_registro.emit(mensaje),
            )
            self.senal_finalizado.emit(resultado)
        except Exception as exc:
            self.senal_error.emit(str(exc), traceback.format_exc())

    def _abrir_carpeta_salida(self) -> None:
        carpeta = self.ultima_carpeta_salida or self.entrada_salida.text().strip()
        if carpeta:
            Path(carpeta).mkdir(parents=True, exist_ok=True)
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(carpeta))))

    @Slot(str)
    def _agregar_registro(self, mensaje: str) -> None:
        self.registro.append(mensaje)
        barra = self.registro.verticalScrollBar()
        barra.setValue(barra.maximum())

    @Slot(int, int)
    def _actualizar_progreso(self, hecho: int, total: int) -> None:
        total = max(0, total)
        if total == 0:
            self.progreso.setRange(0, 1)
            self.progreso.setValue(0)
            self.etiqueta_progreso.setText("0/0")
            return
        self.progreso.setRange(0, total)
        self.progreso.setValue(hecho)
        self.etiqueta_progreso.setText(f"{hecho}/{total}")

    @Slot(object)
    def _finalizar_correcto(self, resultado) -> None:
        self.proceso_activo = False
        self.boton_generar.setEnabled(True)
        self.ultima_carpeta_salida = str(resultado.carpeta_destino)
        self._agregar_registro(f"Proceso terminado. Exportados: {resultado.exportados}. Errores: {resultado.errores}.")
        QMessageBox.information(
            self,
            "Terminado",
            f"PDF exportados: {resultado.exportados}\nErrores: {resultado.errores}\nCarpeta:\n{resultado.carpeta_destino}",
        )

    @Slot(str, str)
    def _finalizar_error(self, mensaje: str, detalle: str) -> None:
        self.proceso_activo = False
        self.boton_generar.setEnabled(True)
        self._agregar_registro("ERROR: " + mensaje)
        self._agregar_registro(detalle)
        QMessageBox.critical(self, "Error", mensaje)
