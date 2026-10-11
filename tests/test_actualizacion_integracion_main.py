# -*- coding: utf-8 -*-

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from main import VentanaRuteo


class PruebasIntegracionMainActualizaciones(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.aplicacion = QApplication.instance() or QApplication([])

    def setUp(self):
        self.parche_actualizacion = patch.object(
            VentanaRuteo, "_buscar_actualizacion_al_iniciar"
        )
        self.parche_actualizacion.start()

    def tearDown(self):
        self.parche_actualizacion.stop()

    def test_modulo_usa_el_mismo_stack_y_ventana(self):
        ventana = VentanaRuteo()
        self.assertEqual(ventana.accion_pagina_actualizaciones.text(), "Procesamiento de actualizaciones")
        self.assertGreaterEqual(ventana.stack_paginas.indexOf(ventana.pagina_procesamiento_actualizaciones), 0)
        ventana.mostrar_pagina_procesamiento_actualizaciones()
        self.assertIs(
            ventana.stack_paginas.currentWidget(), ventana.pagina_procesamiento_actualizaciones
        )
        self.assertTrue(ventana.accion_pagina_actualizaciones.isChecked())
        ventana.deleteLater()

    def test_ventana_principal_conserva_marco_nativo_de_windows(self):
        ventana = VentanaRuteo()
        indicadores = ventana.windowFlags()
        for indicador in (
            Qt.WindowType.WindowTitleHint,
            Qt.WindowType.WindowSystemMenuHint,
            Qt.WindowType.WindowMinimizeButtonHint,
            Qt.WindowType.WindowMaximizeButtonHint,
            Qt.WindowType.WindowCloseButtonHint,
        ):
            self.assertTrue(indicadores & indicador)
        self.assertFalse(indicadores & Qt.WindowType.FramelessWindowHint)
        ventana.deleteLater()

    def test_cierre_sin_hilo_limpia_y_muestra_aviso_independiente(self):
        ventana = VentanaRuteo()
        ventana.temporizador_aviso_inactividad.stop()
        ventana.temporizador_cierre_inactividad.stop()
        pagina = ventana.pagina_procesamiento_actualizaciones
        pagina.rutas["csv_sansys"] = "temporal.csv"
        pagina._aplicar_modo_c03(True)
        pagina._ultimo_resultado = object()
        ventana._cerrar_por_tiempo_cumplido()
        self.assertFalse(ventana.isVisible())
        self.assertIsNotNone(ventana.dialogo_sesion_cerrada)
        self.assertTrue(
            ventana.dialogo_sesion_cerrada.windowFlags()
            & Qt.WindowType.WindowStaysOnTopHint
        )
        self.assertEqual(pagina.rutas, {})
        self.assertIsNone(pagina._ultimo_resultado)
        self.assertFalse(pagina.modo_c03)
        ventana.dialogo_sesion_cerrada._reabrir()
        self.assertFalse(ventana._cierre_sesion_pendiente)
        self.assertIs(
            ventana.stack_paginas.currentWidget(), ventana.pagina_ruteo
        )
        ventana.close()
        ventana.deleteLater()

    def test_cierre_con_qthread_solicita_cancelacion_y_espera(self):
        ventana = VentanaRuteo()
        ventana.temporizador_aviso_inactividad.stop()
        ventana.temporizador_cierre_inactividad.stop()
        pagina = ventana.pagina_procesamiento_actualizaciones

        def operacion(progreso):
            for indice in range(200):
                progreso("Prueba de cancelación", indice, 200)
                QTest.qWait(2)
            return object()

        pagina._iniciar_operacion(operacion, lambda _resultado: None)
        QTest.qWait(20)
        hilo_original = pagina.hilo
        ventana._cerrar_por_tiempo_cumplido()
        self.assertIsNotNone(hilo_original)
        self.assertTrue(ventana._cierre_sesion_pendiente)
        for _ in range(300):
            QTest.qWait(10)
            if pagina.hilo is None and ventana.dialogo_sesion_cerrada is not None:
                break
        self.assertIsNone(pagina.hilo)
        self.assertIsNotNone(ventana.dialogo_sesion_cerrada)
        ventana.dialogo_sesion_cerrada._reabrir()
        ventana.close()
        ventana.deleteLater()

    def test_x_en_aviso_termina_la_aplicacion(self):
        ventana = VentanaRuteo()
        ventana._cerrar_por_tiempo_cumplido()
        with patch("main.QApplication.quit") as salir:
            ventana.dialogo_sesion_cerrada.reject()
        salir.assert_called_once()
        ventana.deleteLater()


if __name__ == "__main__":
    unittest.main()
