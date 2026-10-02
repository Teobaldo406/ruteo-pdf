# -*- coding: utf-8 -*-

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import zipfile

from actualizacion_datos.configuracion import ConfiguracionProcesamiento
from actualizacion_datos.lectores import leer_archivo_delimitado, leer_xlsx
from actualizacion_datos.normalizacion import (
    hora_a_minutos,
    normalizar_fila,
    normalizar_hora,
    normalizar_identificador,
    resolver_columnas,
)


def crear_xlsx_minimo(ruta: Path) -> None:
    tipos = "http://schemas.openxmlformats.org/package/2006/content-types"
    relaciones = "http://schemas.openxmlformats.org/package/2006/relationships"
    hoja = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<sheetData>'
        '<row r="1"><c r="A1" t="inlineStr"><is><t>nro_ot</t></is></c>'
        '<c r="B1" t="inlineStr"><is><t>nis_rad</t></is></c></row>'
        '<row r="2"><c r="A2" t="inlineStr"><is><t>0001</t></is></c>'
        '<c r="B2"><v>123</v></c></row>'
        '</sheetData></worksheet>'
    )
    with zipfile.ZipFile(ruta, "w") as archivo:
        archivo.writestr(
            "[Content_Types].xml",
            f'<Types xmlns="{tipos}"><Default Extension="xml" ContentType="application/xml"/></Types>',
        )
        archivo.writestr(
            "xl/workbook.xml",
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="DATOS" sheetId="1" r:id="rId1"/></sheets></workbook>',
        )
        archivo.writestr(
            "xl/_rels/workbook.xml.rels",
            f'<Relationships xmlns="{relaciones}"><Relationship Id="rId1" '
            'Type="x" Target="worksheets/sheet1.xml"/></Relationships>',
        )
        archivo.writestr("xl/worksheets/sheet1.xml", hoja)


class PruebasLectoresNormalizacion(unittest.TestCase):
    def test_lee_txt_cp1252_y_conserva_columnas_adicionales(self):
        with TemporaryDirectory() as temporal:
            ruta = Path(temporal) / "datos.txt"
            ruta.write_bytes("nro_ot\tnis_rad\tdescripción\n1\t2\tVálida\textra\n".encode("cp1252"))
            tabla = leer_archivo_delimitado(ruta)
            self.assertEqual(tabla.formato.delimitador, "\t")
            self.assertEqual(tabla.filas[0]["COLUMNA_EXTRA_1"], "extra")
            self.assertTrue(tabla.advertencias)

    def test_lee_txt_sin_encabezado_con_orden_explicito(self):
        with TemporaryDirectory() as temporal:
            ruta = Path(temporal) / "acumulado.txt"
            ruta.write_text("N1\tOT1\tOS1\n", encoding="utf-8-sig")
            tabla = leer_archivo_delimitado(
                ruta, tiene_encabezado=False, columnas_sin_encabezado=("nis_rad", "OT", "OS")
            )
            self.assertEqual(tabla.filas[0], {"nis_rad": "N1", "OT": "OT1", "OS": "OS1"})

    def test_lee_xlsx_sin_openpyxl(self):
        with TemporaryDirectory() as temporal:
            ruta = Path(temporal) / "datos.xlsx"
            crear_xlsx_minimo(ruta)
            tabla = leer_xlsx(ruta, hoja="DATOS")
            self.assertEqual(tabla.encabezados, ["nro_ot", "nis_rad"])
            self.assertEqual(tabla.filas[0]["nro_ot"], "0001")

    def test_normaliza_alias_identificadores_fecha_y_hora(self):
        configuracion = ConfiguracionProcesamiento.predeterminada()
        columnas = resolver_columnas(
            ["nro_ot", "nnum_os", "nis_rad", "FEJECUCION", "acción", "HI", "HF"], configuracion
        )
        fila = normalizar_fila(
            {
                "nro_ot": " 001.0 ", "nnum_os": " OS 9 ", "nis_rad": "0007",
                "FEJECUCION": "1/9/2026", "acción": "511.0", "HI": "9,56", "HF": "10,01",
            },
            columnas,
        )
        self.assertEqual(fila["OT"], "001")
        self.assertEqual(fila["OS"], "OS9")
        self.assertEqual(fila["NIS"], "0007")
        self.assertEqual(fila["FECHA"], "2026-09-01")
        self.assertEqual(fila["ACC"], "511")
        self.assertEqual(fila["HI"], "09:56")
        self.assertEqual(fila["HF"], "10:01")
        self.assertEqual(normalizar_hora("14.05"), "14:05")
        self.assertEqual(normalizar_hora("14,05"), "14:05")
        self.assertEqual(normalizar_hora("9,56"), "09:56")
        self.assertEqual(hora_a_minutos("14:00"), 840)

    def test_no_inventa_significado_de_hora_ambigua(self):
        with self.assertRaisesRegex(ValueError, "ambigua"):
            normalizar_hora("8.5")

    def test_confirma_hora_decimal_truncada_con_la_observacion(self):
        configuracion = ConfiguracionProcesamiento.predeterminada()
        columnas = resolver_columnas(["HI", "HF", "OBS"], configuracion)
        fila = normalizar_fila(
            {
                "HI": "16,2",
                "HF": "16,3",
                "OBS": "Texto HI: 16:20 HF: 16:30 OBS: evidencia",
            },
            columnas,
        )
        self.assertEqual(fila["HI"], "16:20")
        self.assertEqual(fila["HF"], "16:30")

    def test_no_completa_hora_ambigua_si_observacion_no_coincide(self):
        configuracion = ConfiguracionProcesamiento.predeterminada()
        columnas = resolver_columnas(["HI", "HF", "OBS"], configuracion)
        fila = normalizar_fila(
            {"HI": "8,5", "HF": "8,5", "OBS": "HI: 08:05 HF: 08:05"},
            columnas,
        )
        self.assertEqual(fila["HI"], "8,5")
        self.assertEqual(fila["HF"], "8,5")

    def test_expande_identificador_cientifico_sin_redondear(self):
        self.assertEqual(normalizar_identificador("7.1932613E7"), "71932613")
        self.assertEqual(normalizar_identificador("8.15996033E8"), "815996033")


if __name__ == "__main__":
    unittest.main()
