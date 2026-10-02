# -*- coding: utf-8 -*-

import csv
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from actualizacion_datos.configuracion import ConfiguracionProcesamiento
from actualizacion_datos.exportadores import exportar_tabla_interna
from actualizacion_datos.modelos import (
    CategoriaResultado,
    EstadoFila,
    RegistroProcesamiento,
)
from actualizacion_datos.reglas_provisionales import aplicar_reglas_provisionales


class PruebasReglasProvisionales(unittest.TestCase):
    def test_no_inyecta_reglas_y_habilita_cuatro_contratos(self):
        configuracion = ConfiguracionProcesamiento.predeterminada()
        aplicar_reglas_provisionales(configuracion)
        self.assertFalse(configuracion.modo_reglas_provisionales)
        self.assertEqual(configuracion.reglas_accion, [])
        self.assertTrue(configuracion.contrato_cierres_sistema.confirmado)
        self.assertTrue(configuracion.contrato_entregable_cierres.provisional)
        self.assertEqual(configuracion.contrato_entregable_cierres.columnas[0], "nis_rad")

    def test_conserva_reglas_externas_ya_cargadas(self):
        from actualizacion_datos.configuracion import ReglaAccion
        configuracion = ConfiguracionProcesamiento.predeterminada()
        configuracion.agregar_reglas_accion([
            ReglaAccion(id_regla="EXTERNA", tipo="C", accion_ejecutada="511")
        ])
        aplicar_reglas_provisionales(configuracion)
        self.assertEqual([regla.id_regla for regla in configuracion.reglas_accion], ["EXTERNA"])

    def test_exportacion_de_revision_incluye_columnas_obligatorias(self):
        registro = RegistroProcesamiento(
            id_fila="1", archivo_origen="muestra.csv", numero_fila_origen=2,
            datos_originales={}, estado=EstadoFila.EN_REVISION,
            datos_normalizados={"OT": "OT1", "OS": "OS1", "NIS": "N1"},
            categoria_final=CategoriaResultado.REVISION_MANUAL,
            regla_final="PRUEBA-01", etapa_final="PRUEBA", motivo_final="REVISAR",
        )
        with TemporaryDirectory() as temporal:
            ruta = exportar_tabla_interna([registro], Path(temporal), "REVISION", "ID")
            with ruta.open(encoding="utf-8-sig", newline="") as archivo:
                encabezados = next(csv.reader(archivo, delimiter=";"))
        for columna in ("ETAPA", "CATEGORIA", "REGLA", "MOTIVO", "DESTINO", "OT", "OS", "NIS_RAD"):
            self.assertIn(columna, encabezados)


if __name__ == "__main__":
    unittest.main()
