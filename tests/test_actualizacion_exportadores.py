# -*- coding: utf-8 -*-

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from actualizacion_datos.configuracion import ConfiguracionProcesamiento, ContratoTxt
from actualizacion_datos.exportadores import crear_estructura_salida, exportar_cierres
from actualizacion_datos.modelos import ProcesoBloqueadoError, RegistroProcesamiento


def registro_listo():
    return RegistroProcesamiento(
        id_fila="general:2", archivo_origen="general.csv", numero_fila_origen=2,
        datos_originales={"nro_ot": "0001"},
        datos_normalizados={
            "NIS": "0000123", "OT": "0001", "OS": "OS-1", "FECHA": "2026-09-21",
            "HI": "12:00", "HF": "12:00", "ACC": "511", "CODIGO": "G1",
            "OBS": "Texto", "LECT": "100",
        },
    )


class PruebasExportadoresActualizacion(unittest.TestCase):
    def test_bloquea_formato_no_confirmado(self):
        configuracion = ConfiguracionProcesamiento.predeterminada()
        with TemporaryDirectory() as temporal:
            rutas = crear_estructura_salida(Path(temporal), "ID1", "20260921")
            with self.assertRaisesRegex(ProcesoBloqueadoError, "BLOQUEADO"):
                exportar_cierres([registro_listo()], configuracion, rutas, "ID1")

    def test_exporta_dos_txt_sin_perder_ceros_y_no_sobrescribe(self):
        configuracion = ConfiguracionProcesamiento.predeterminada()
        columnas_sistema = ("OT", "OS", "FEJECUCION", "HI", "HF", "ACCION", "CODIGO", "OBSERVACION", "LECT")
        mapeo_sistema = (
            ("FEJECUCION", "FECHA"), ("ACCION", "ACC"), ("OBSERVACION", "OBS"),
        )
        configuracion.contrato_cierres_sistema = ContratoTxt(
            "CIERRES_SISTEMA", columnas_sistema, confirmado=True,
            incluir_encabezado=False, mapeo_columnas=mapeo_sistema,
        )
        configuracion.contrato_entregable_cierres = ContratoTxt(
            "ENTREGABLE_CIERRES", ("nis_rad", *columnas_sistema), confirmado=True,
            mapeo_columnas=(("nis_rad", "NIS"), *mapeo_sistema),
        )
        with TemporaryDirectory() as temporal:
            rutas = crear_estructura_salida(Path(temporal), "ID1", "20260921")
            sistema, entregable = exportar_cierres([registro_listo()], configuracion, rutas, "ID1")
            self.assertTrue(sistema.exists())
            self.assertTrue(entregable.exists())
            self.assertTrue(sistema.read_text(encoding="utf-8-sig").startswith("0001\tOS-1"))
            self.assertIn("0000123", entregable.read_text(encoding="utf-8-sig"))

            segundo, _ = exportar_cierres([registro_listo()], configuracion, rutas, "ID1")
            self.assertNotEqual(segundo, sistema)
            self.assertTrue(segundo.name.endswith("_2.txt"))


if __name__ == "__main__":
    unittest.main()
