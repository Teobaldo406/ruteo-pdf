from pathlib import Path
from tempfile import TemporaryDirectory
import csv
import unittest

from depuracion_ot import depurar_ordenes, normalizar_identificador


class PruebasDepuracionOT(unittest.TestCase):
    def test_normaliza_espacios_y_decimal(self):
        self.assertEqual(normalizar_identificador(" 123 456.0 "), "123456")
        self.assertEqual(normalizar_identificador("000123"), "000123")

    def test_realiza_los_dos_cruces_con_csv_y_txt(self):
        with TemporaryDirectory() as temporal:
            carpeta = Path(temporal)
            reaperturas = carpeta / "reaperturas.txt"
            accion = carpeta / "accion.csv"
            plantilla = carpeta / "plantilla.txt"
            salida = carpeta / "resultados"

            reaperturas.write_text("nis_rad\n100.0\n", encoding="utf-8")
            accion.write_text(
                "nis_rad;nro_ot;detalle\n100;OT-1;eliminar\n 200.0 ; OT-2 ;conservar\n",
                encoding="utf-8",
            )
            plantilla.write_text(
                "nro_ot\tdato\nOT-1\tfuera\nOT-2\tcompleto\n",
                encoding="utf-8",
            )

            resultado = depurar_ordenes(reaperturas, accion, plantilla, salida)

            self.assertEqual((resultado.filas_accion, resultado.filas_plantilla), (1, 1))
            self.assertEqual((resultado.total_accion_original, resultado.total_plantilla_original), (2, 2))
            self.assertEqual(resultado.ruta_accion_depurada.parent, salida)
            self.assertEqual(resultado.ruta_plantilla_depurada.parent, salida)
            with resultado.ruta_accion_depurada.open(encoding="utf-8-sig", newline="") as archivo:
                filas_accion = list(csv.DictReader(archivo, delimiter=";"))
            with resultado.ruta_plantilla_depurada.open(encoding="utf-8-sig", newline="") as archivo:
                filas_plantilla = list(csv.DictReader(archivo, delimiter="\t"))
            self.assertEqual(filas_accion[0]["detalle"], "conservar")
            self.assertEqual(filas_plantilla[0]["dato"], "completo")

    def test_detiene_el_proceso_si_falta_una_columna(self):
        with TemporaryDirectory() as temporal:
            carpeta = Path(temporal)
            reaperturas = carpeta / "reaperturas.csv"
            accion = carpeta / "accion.csv"
            plantilla = carpeta / "plantilla.csv"
            reaperturas.write_text("otra_columna\n1\n", encoding="utf-8")
            accion.write_text("nis_rad,nro_ot\n1,2\n", encoding="utf-8")
            plantilla.write_text("nro_ot\n2\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "nis_rad.*REAPERTURAS"):
                depurar_ordenes(reaperturas, accion, plantilla)


if __name__ == "__main__":
    unittest.main()
