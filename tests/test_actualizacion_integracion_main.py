# -*- coding: utf-8 -*-

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from main import VentanaRuteo


class PruebasIntegracionMainActualizaciones(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.aplicacion = QApplication.instance() or QApplication([])

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


if __name__ == "__main__":
    unittest.main()
