# -*- coding: utf-8 -*-

import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from actualizacion_datos.modelos import (
    ContextoEjecucion,
    EstadoEtapa,
    RegistroProcesamiento,
    ResultadoFlujoComun,
    ResultadoProceso,
    ResultadoRama,
    ResumenEtapa,
)
from actualizacion_datos.reglas_gio import MatrizReglasGio
from actualizacion_datos.trabajadores import TrabajadorActualizacion
from actualizacion_datos_pagina import PaginaProcesamientoActualizaciones


class PruebasInterfazActualizacion(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.aplicacion = QApplication.instance() or QApplication([])

    def test_pagina_inicia_con_dependencias_bloqueadas(self):
        pagina = PaginaProcesamientoActualizaciones()
        self.assertFalse(pagina.boton_cierres.isEnabled())
        self.assertFalse(pagina.boton_entregable.isEnabled())
        self.assertFalse(pagina.boton_reaperturas.isEnabled())
        self.assertIn("BLOQUEADO", pagina.etiquetas_etapa["REAPERTURAS"].text())
        pagina.close()

    def test_cambio_visual_de_estado_no_cambia_reglas(self):
        pagina = PaginaProcesamientoActualizaciones()
        pagina._cambiar_etapa("CIERRES", EstadoEtapa.PROCESANDO)
        self.assertIn("PROCESANDO", pagina.etiquetas_etapa["CIERRES"].text())
        self.assertEqual(pagina.servicio.configuracion.reglas_accion, [])
        pagina.close()

    def test_seleccion_de_archivo_y_carpeta(self):
        pagina = PaginaProcesamientoActualizaciones()
        with TemporaryDirectory() as temporal:
            archivo = str(Path(temporal) / "sansys.csv")
            with patch("actualizacion_datos_pagina.QFileDialog.getOpenFileName", return_value=(archivo, "")):
                pagina._seleccionar_archivo("csv_sansys")
            with patch("actualizacion_datos_pagina.QFileDialog.getExistingDirectory", return_value=temporal):
                pagina._seleccionar_salida()
            self.assertEqual(pagina.rutas["csv_sansys"], archivo)
            self.assertEqual(pagina.rutas["carpeta_salida"], temporal)
            self.assertIn("sansys.csv", pagina.etiquetas_ruta["csv_sansys"].text())
        pagina.close()

    def test_matriz_valida_muestra_resumen_y_habilita_vista(self):
        pagina = PaginaProcesamientoActualizaciones()
        ruta = "matriz_prueba.xlsx"
        matriz_prueba = MatrizReglasGio(
            reglas=(), combinaciones=frozenset(),
            hojas=("RESUMEN", "REGLAS_GIO", "COMBINACIONES_GIO", "GUIA_USO"),
            ruta=ruta, fecha_modificacion="01/10/2026 00:00:00",
        )
        with patch(
            "actualizacion_datos_pagina.QFileDialog.getOpenFileName",
            return_value=(ruta, ""),
        ), patch(
            "actualizacion_datos_pagina.leer_matriz_reglas_gio",
            return_value=matriz_prueba,
        ):
            pagina._seleccionar_archivo("matriz_gio")
        texto = pagina.etiquetas_ruta["matriz_gio"].text()
        self.assertIn("MATRIZ VÁLIDA", texto)
        self.assertIn("Reglas activas:", texto)
        self.assertIn("Reglas inactivas:", texto)
        self.assertIn("Fecha de modificación:", texto)
        self.assertTrue(pagina.boton_ver_reglas.isEnabled())
        with patch("actualizacion_datos_pagina.QDialog.exec", return_value=0):
            pagina._ver_reglas_cargadas()
        self.assertIsNotNone(pagina.tabla_reglas_cargadas)
        self.assertEqual(pagina.tabla_reglas_cargadas.columnCount(), 9)
        pagina.close()

    def test_matriz_con_error_bloquea_el_proceso(self):
        pagina = PaginaProcesamientoActualizaciones()
        with patch(
            "actualizacion_datos_pagina.leer_matriz_reglas_gio",
            side_effect=ValueError("MATRIZ CON ERRORES: ID_REGLA duplicado"),
        ):
            pagina._validar_matriz_seleccionada(Path("matriz_invalida.xlsx"))
        self.assertIn("MATRIZ CON ERRORES", pagina.etiquetas_ruta["matriz_gio"].text())
        self.assertFalse(pagina.boton_ver_reglas.isEnabled())
        pagina.close()

    def test_muestra_csv_sansys_y_un_solo_libro_de_reglas(self):
        pagina = PaginaProcesamientoActualizaciones()
        textos = [boton.text() for boton in pagina.findChildren(type(pagina.boton_flujo))]
        unidos = " | ".join(textos)
        self.assertIn("Seleccionar CSV SANSYS", unidos)
        self.assertIn("Seleccionar libro de reglas y actualización", unidos)
        self.assertNotIn("Seleccionar data general", unidos)
        self.assertNotIn("Seleccionar catálogo de actividades", unidos)
        self.assertNotIn("Seleccionar tabla de operarios", unidos)
        self.assertNotIn("Seleccionar tabla de lecturas", unidos)
        pagina.close()

    def test_progreso_cancelacion_error_y_vista_previa(self):
        pagina = PaginaProcesamientoActualizaciones()
        pagina._mostrar_progreso("Leyendo archivos", 3, 4)
        self.assertEqual(pagina.progreso.value(), 75)
        self.assertIn("Leyendo archivos", pagina.etiqueta_estado.text())

        trabajador = TrabajadorActualizacion(lambda progreso: None)
        pagina.trabajador = trabajador
        pagina._cancelar()
        self.assertTrue(trabajador._cancelar)
        self.assertIn("cancelando", pagina.etiqueta_estado.text())

        registro = RegistroProcesamiento(
            id_fila="1", archivo_origen="data.xlsx", numero_fila_origen=2,
            datos_originales={}, datos_normalizados={"OT": "1", "OS": "2"},
            motivo_final="PRUEBA",
        )
        pagina._mostrar_registros([registro])
        self.assertEqual(pagina.tabla.rowCount(), 1)
        self.assertGreaterEqual(pagina.tabla.columnCount(), 3)

        with TemporaryDirectory() as temporal:
            pagina.rutas["carpeta_salida"] = temporal
            with patch("actualizacion_datos_pagina.QMessageBox.critical") as mensaje:
                pagina._operacion_fallida("Fallo controlado", "detalle técnico")
                mensaje.assert_called_once()
            ruta_log = Path(temporal) / "error_procesamiento_actualizaciones.log"
            self.assertTrue(ruta_log.exists())
            self.assertIn("detalle técnico", ruta_log.read_text(encoding="utf-8"))
        self.assertIn("Fallo controlado", pagina.texto_resumen.toPlainText())
        pagina.trabajador = None
        pagina.close()

    def test_apertura_de_carpeta_de_salida(self):
        pagina = PaginaProcesamientoActualizaciones()
        with TemporaryDirectory() as temporal:
            pagina.servicio.rutas_salida = SimpleNamespace(raiz=Path(temporal))
            with patch("actualizacion_datos_pagina.QDesktopServices.openUrl", return_value=True) as abrir:
                pagina._abrir_resultados()
                abrir.assert_called_once()
        pagina.close()

    def test_advierte_cuando_la_fecha_no_produce_data_filtrada(self):
        pagina = PaginaProcesamientoActualizaciones()
        contexto = ContextoEjecucion(
            id_ejecucion="prueba", fecha_procesamiento="27/09/2026",
            carpeta_salida="C:/temporal",
        )
        contexto.estados_etapas["FLUJO_COMUN"] = EstadoEtapa.COMPLETADO
        flujo = ResultadoFlujoComun(
            registros=[], data_filtrada=[],
            resumen=ResumenEtapa(etapa="FLUJO_COMUN"),
        )
        resultado = ResultadoProceso(contexto=contexto, flujo_comun=flujo)
        pagina.servicio.rutas_salida = SimpleNamespace(raiz=Path("C:/temporal/resultados"))
        with patch("actualizacion_datos_pagina.QMessageBox.warning") as mensaje:
            pagina._flujo_comun_terminado(resultado)
            mensaje.assert_called_once()
        self.assertFalse(pagina._procesar_cierres_automaticamente)
        self.assertFalse(pagina.boton_cierres.isEnabled())
        self.assertIn("no hay registros", pagina.etiqueta_estado.text())
        pagina.close()

    def test_advierte_cuando_no_hay_cierres_listos_para_txt(self):
        pagina = PaginaProcesamientoActualizaciones()
        contexto = ContextoEjecucion(
            id_ejecucion="prueba", fecha_procesamiento="27/09/2026",
            carpeta_salida="C:/temporal",
        )
        contexto.estados_etapas["CIERRES"] = EstadoEtapa.CON_ERRORES
        revision = RegistroProcesamiento(
            id_fila="1", archivo_origen="sansys.csv", numero_fila_origen=2,
            datos_originales={}, datos_normalizados={"OT": "1", "OS": "2"},
            motivo_final="ACCION_SIN_REGLA_CONFIGURADA",
        )
        resultado = ResultadoProceso(
            contexto=contexto,
            cierres=ResultadoRama(
                nombre="CIERRES", entradas=[revision], listas=[], revisiones=[revision]
            ),
        )
        pagina.servicio.rutas_salida = SimpleNamespace(raiz=Path("C:/temporal/resultados"))
        with patch("actualizacion_datos_pagina.QMessageBox.warning") as mensaje:
            pagina._cierres_terminados(resultado)
            mensaje.assert_called_once()
        self.assertIn("sin filas aptas", pagina.etiqueta_estado.text())
        pagina.close()


if __name__ == "__main__":
    unittest.main()
