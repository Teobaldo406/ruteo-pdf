# -*- coding: utf-8 -*-

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import zipfile

from actualizacion_datos.configuracion import ConfiguracionProcesamiento, ContratoTxt
from actualizacion_datos.exportadores import (
    crear_estructura_salida,
    exportar_cierres,
    exportar_revision_manual_cierres,
    exportar_revision_manual_reaperturas,
)
from actualizacion_datos.lectores import leer_xlsx
from actualizacion_datos.modelos import ProcesoBloqueadoError, RegistroProcesamiento


def registro_listo():
    return RegistroProcesamiento(
        id_fila="general:2", archivo_origen="general.csv", numero_fila_origen=2,
        datos_originales={"nro_ot": "0001"},
        datos_normalizados={
            "NIS": "0000123", "OT": "0001", "OS": "OS-1", "FECHA": "2026-09-21",
            "HI": "12:00", "HF": "12:00", "HI_ORIGINAL": "9,18",
            "HF_ORIGINAL": "09:18:00", "ACC": "511", "CODIGO": "G1",
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

    def test_exporta_dos_txt_con_nombres_fijos_sin_perder_ceros(self):
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
            campos = sistema.read_text(encoding="utf-8-sig").splitlines()[0].split("\t")
            self.assertEqual(campos[3:5], ["9,18", "09:18:00"])

            segundo, _ = exportar_cierres([registro_listo()], configuracion, rutas, "ID1")
            self.assertEqual(segundo, sistema)
            self.assertEqual(segundo.name, "CIERRES_SISTEMA.txt")
            self.assertEqual(
                {ruta.name for ruta in rutas.raiz.rglob("*") if ruta.is_file()},
                {"CIERRES_SISTEMA.txt", "ENTREGABLE_CIERRES.txt"},
            )

    def test_revision_cierres_con_originales_cuatro_temporales_y_nd(self):
        registro = registro_listo()
        registro.motivo_final = "ACCION_REQUIERE_REVISION"
        registro.datos_originales = {
            "vtipo_os": "TIPO-FUENTE",
            "null": "0001",
            "COLUMNA_51": "OS-1",
            "COLUMNA_57": "Texto original",
            "COLUMNA_58": "0",
        }
        registro.datos_normalizados.update({
            "TIPO": "C", "OBS_TIPO": "Cierre simple", "NIS": "N-1",
            "LECTURA_TOMA": "0", "DIFERENCIA": "", "VALIDACION_LECTURA": "",
        })
        with TemporaryDirectory(dir=Path.cwd() / ".tmp_tests") as temporal:
            rutas = crear_estructura_salida(Path(temporal), "ID1", "2026-09-21")
            ruta = exportar_revision_manual_cierres([registro], rutas.cierres, [registro])
            tabla = leer_xlsx(ruta, hoja="REVISIONES")
            with zipfile.ZipFile(ruta) as libro:
                hoja_xml = libro.read("xl/worksheets/sheet1.xml").decode("utf-8")
                estilos_xml = libro.read("xl/styles.xml").decode("utf-8")
        posicion = tabla.encabezados.index("vtipo_os")
        self.assertEqual(
            tabla.encabezados[posicion:posicion + 5],
            ["vtipo_os", "TIPO", "OBS TIPO", "NIS_RAD", "OT"],
        )
        self.assertEqual(tabla.encabezados[-4:], [
            "TEMPORAL_LECTURA_ANTERIOR", "TEMPORAL_DIFERENCIA",
            "TEMPORAL_VALIDACION", "TEMPORAL_MOTIVO_REVISION",
        ])
        self.assertEqual(tabla.filas[0]["TEMPORAL_LECTURA_ANTERIOR"], "0")
        self.assertEqual(tabla.filas[0]["TEMPORAL_DIFERENCIA"], "#N/D")
        self.assertEqual(tabla.filas[0]["TEMPORAL_VALIDACION"], "#N/D")
        self.assertIn('width="11"', hoja_xml)
        self.assertNotIn('width="55"', hoja_xml)
        self.assertIn('<row r="1" ht="28" customHeight="1">', hoja_xml)
        self.assertIn('<row r="2" ht="20" customHeight="1">', hoja_xml)
        self.assertIn('wrapText="1" vertical="center"', estilos_xml)

    def test_revision_reaperturas_renombra_bloque_calcula_y_usa_nd(self):
        originales = {
            "vtipo_os": "TIPO-FUENTE",
            "TIPO": "VALOR_ANTIGUO",
            "OBS TIPO": "VALOR_ANTIGUO",
            "nis_rad": "VALOR_ANTIGUO",
            "null": "OT-1",
            "COLUMNA_51": "OS-1",
            "COLUMNA_52": "07/10/2026",
            "COLUMNA_53": "10,00",
            "COLUMNA_54": "10,05",
            "COLUMNA_55": "611",
            "COLUMNA_56": "CO-1",
            "COLUMNA_57": "Observación original",
            "COLUMNA_58": "158",
            "COLUMNA_59": "",
        }

        def crear(indice, actual, anterior, accion="511"):
            datos = dict(originales)
            datos["null"] = f"OT-{indice}"
            datos["COLUMNA_51"] = f"OS-{indice}"
            datos["COLUMNA_58"] = str(actual)
            normalizados = {
                "TIPO": "R",
                "OBS_TIPO": "Reapertura consumidor normal",
                "NIS": f"N-{indice}",
                "LECT": str(actual),
            }
            if anterior is not None:
                normalizados.update({
                    "ACCION_CIERRE_ANTERIOR": accion,
                    "LECTURA_CIERRE_ANTERIOR": str(anterior),
                })
            return RegistroProcesamiento(
                id_fila=f"fila-{indice}",
                archivo_origen="sansys.csv",
                numero_fila_origen=indice + 1,
                datos_originales=datos,
                datos_normalizados=normalizados,
                motivo_final="REAPERTURA_NO_EQUIVALENTE",
            )

        registros = [
            crear(1, 158, 157),
            crear(2, 0, 105),
            crear(3, 709, 709),
            crear(4, 93, 0),
            crear(5, 10, None, accion=""),
        ]
        with TemporaryDirectory(dir=Path.cwd() / ".tmp_tests") as temporal:
            carpeta = Path(temporal)
            txt = carpeta / "REAPERTURAS_SISTEMA.txt"
            txt.write_bytes(b"contenido-operativo-intacto\n")
            contenido_antes = txt.read_bytes()
            ruta = exportar_revision_manual_reaperturas(
                registros, carpeta, registros
            )
            tabla = leer_xlsx(ruta, hoja="REVISIONES")
            with zipfile.ZipFile(ruta) as libro:
                hoja_xml = libro.read("xl/worksheets/sheet1.xml").decode("utf-8")
            contenido_despues = txt.read_bytes()

        self.assertEqual(len(tabla.filas), len(registros))
        posicion = tabla.encabezados.index("vtipo_os")
        self.assertEqual(
            tabla.encabezados[posicion:posicion + 5],
            ["vtipo_os", "TIPO", "OBS TIPO", "NIS_RAD", "OT"],
        )
        self.assertEqual(tabla.filas[0]["TIPO"], "R")
        self.assertEqual(
            tabla.filas[0]["OBS TIPO"], "Reapertura consumidor normal"
        )
        self.assertEqual(tabla.filas[0]["NIS_RAD"], "N-1")
        self.assertEqual(tabla.encabezados.count("NIS_RAD"), 1)
        self.assertNotIn("COLUMNA_59", tabla.encabezados)
        self.assertFalse(any(
            encabezado == "null" or encabezado.startswith("COLUMNA_")
            for encabezado in tabla.encabezados
        ))
        self.assertEqual(
            [fila["TEMPORAL_DIFERENCIA"] for fila in tabla.filas],
            ["1", "-105", "0", "93", "#N/D"],
        )
        self.assertEqual(
            tabla.filas[-1]["TEMPORAL_ACCION_CIERRE_ANTERIOR"], "#N/D"
        )
        self.assertEqual(
            tabla.filas[-1]["TEMPORAL_LECTURA_CIERRE_ANTERIOR"], "#N/D"
        )
        self.assertNotIn(">NA<", hoja_xml)
        self.assertIn(">#N/D<", hoja_xml)
        self.assertIn("<v>0</v>", hoja_xml)
        self.assertEqual(contenido_despues, contenido_antes)

    def test_exporta_horas_originales_sin_dos_puntos_ni_apostrofo(self):
        configuracion = ConfiguracionProcesamiento.predeterminada()
        columnas = ("OT", "OS", "FECHA", "HI", "HF", "ACC", "CODIGO", "OBS", "LECT")
        configuracion.contrato_cierres_sistema = ContratoTxt(
            "CIERRES_SISTEMA", columnas, confirmado=True, incluir_encabezado=False,
        )
        configuracion.contrato_entregable_cierres = ContratoTxt(
            "ENTREGABLE_CIERRES", ("NIS", *columnas), confirmado=True,
            incluir_encabezado=False,
        )
        for hi, hf in (("18.26", "18.30"), ("12", "9.09"), ("8.5", "8.5")):
            registro = registro_listo()
            registro.datos_normalizados["HI_ORIGINAL"] = hi
            registro.datos_normalizados["HF_ORIGINAL"] = hf
            with TemporaryDirectory() as temporal:
                rutas = crear_estructura_salida(Path(temporal), "ID1", "20260921")
                sistema, _ = exportar_cierres(
                    [registro], configuracion, rutas, "ID1"
                )
                campos = sistema.read_bytes().decode("utf-8-sig").splitlines()[0].split("\t")
                self.assertEqual(campos[3], hi)
                self.assertEqual(campos[4], hf)
                self.assertFalse(campos[3].startswith("'"))
                self.assertFalse(campos[4].startswith("'"))

    def test_txt_de_cierre_prefiere_hora_final_corregida(self):
        configuracion = ConfiguracionProcesamiento.predeterminada()
        columnas = ("OT", "OS", "FECHA", "HI", "HF", "ACC", "CODIGO", "OBS", "LECT")
        configuracion.contrato_cierres_sistema = ContratoTxt(
            "CIERRES_SISTEMA", columnas, confirmado=True, incluir_encabezado=False,
        )
        configuracion.contrato_entregable_cierres = ContratoTxt(
            "ENTREGABLE_CIERRES", ("NIS", *columnas), confirmado=True,
            incluir_encabezado=False,
        )
        registro = registro_listo()
        registro.datos_normalizados.update({
            "HI_ORIGINAL": "18,37", "HF_ORIGINAL": "18,38",
            "HI_FINAL": "12", "HF_FINAL": "12",
            "OBS": "HI: 12:00 HF: 12:00 OBS: evidencia",
        })
        with TemporaryDirectory() as temporal:
            rutas = crear_estructura_salida(Path(temporal), "ID1", "20260921")
            sistema, _ = exportar_cierres([registro], configuracion, rutas, "ID1")
            campos = sistema.read_bytes().decode("utf-8-sig").splitlines()[0].split("\t")
        self.assertEqual(campos[3:5], ["12", "12"])
        self.assertEqual(campos[7], "HI: 12:00 HF: 12:00 OBS: evidencia")


if __name__ == "__main__":
    unittest.main()
