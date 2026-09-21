from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from extractor_ordenes import cargar_consolidado, cargar_lista_codigos, extraer_registros


class PruebasExtractorOrdenes(unittest.TestCase):
    def test_busqueda_en_las_tres_columnas(self):
        with TemporaryDirectory() as temporal:
            raiz = Path(temporal)
            consolidado = raiz / "consolidado.txt"
            consolidado.write_text(
                "OS\tOBS\tNIS\tOT\nOS-9\tTexto con espacios\t0001\t71056851\n",
                encoding="utf-8",
            )
            for tipo, codigo in (("NIS", "0001"), ("OT", "71056851"), ("OS", "OS-9")):
                lista = raiz / f"{tipo.replace('/', '_')}.txt"
                lista.write_text(codigo + "\n", encoding="utf-8")
                resultado = extraer_registros(
                    cargar_consolidado(consolidado), cargar_lista_codigos(lista),
                    tipo, raiz / tipo.replace("/", "_"),
                )
                self.assertEqual(resultado.filas_extraidas, 1)

    def test_duplicados_faltantes_y_multiples_coincidencias(self):
        with TemporaryDirectory() as temporal:
            raiz = Path(temporal)
            consolidado = raiz / "consolidado.txt"
            consolidado.write_text("1;A;X\n2;A;Y\n3;B;Z\n", encoding="cp1252")
            lista = raiz / "codigos.txt"
            lista.write_text("A\nA\nNO_EXISTE\n", encoding="utf-8-sig")
            resultado = extraer_registros(
                cargar_consolidado(consolidado), cargar_lista_codigos(lista),
                "OT", raiz / "salida",
            )
            self.assertEqual((resultado.total_solicitados, resultado.codigos_repetidos), (2, 1))
            self.assertEqual((resultado.filas_extraidas, resultado.codigos_con_multiples_coincidencias), (2, 1))
            self.assertEqual(resultado.ruta_no_encontrados.read_text(encoding="utf-8").strip(), "NO_EXISTE")

    def test_detecta_alias_reales_en_columnas_independientes(self):
        with TemporaryDirectory() as temporal:
            raiz = Path(temporal)
            consolidado = raiz / "sansys.txt"
            consolidado.write_text(
                "RUTA\tNNUM_OS\tNIS_RAD\tNRO_OT\tOBS\n"
                "R1\tOS-001\t000045\tOT-900\tRegistro completo\n",
                encoding="utf-8",
            )
            cargado = cargar_consolidado(consolidado)
            self.assertEqual(cargado.indices_busqueda, {"NIS": 2, "OT": 3, "OS": 1})
            for tipo, codigo in (("NIS", "000045"), ("OT", "OT-900"), ("OS", "OS-001")):
                lista = raiz / f"{tipo}.txt"
                lista.write_text(codigo, encoding="utf-8")
                resultado = extraer_registros(
                    cargado, cargar_lista_codigos(lista), tipo, raiz / f"salida_{tipo}",
                )
                self.assertEqual(resultado.filas_extraidas, 1)

    def test_archivo_grande_y_nombres_incrementales(self):
        with TemporaryDirectory() as temporal:
            raiz = Path(temporal)
            consolidado = raiz / "grande.txt"
            consolidado.write_text(
                "\n".join(f"{indice:05d}|OS{indice}|T{indice}|dato" for indice in range(10001)),
                encoding="utf-8",
            )
            lista = raiz / "codigos.txt"
            lista.write_text("00000\n10000\n", encoding="utf-8")
            cargado = cargar_consolidado(consolidado)
            self.assertEqual(cargado.total_registros, 10001)
            primero = extraer_registros(cargado, cargar_lista_codigos(lista), "NIS", raiz / "salida")
            segundo = extraer_registros(cargado, cargar_lista_codigos(lista), "NIS", raiz / "salida")
            self.assertEqual(primero.filas_extraidas, 2)
            self.assertEqual(segundo.ruta_encontrados.name, "REGISTROS_ENCONTRADOS_2.txt")


if __name__ == "__main__":
    unittest.main()
