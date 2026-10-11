# -*- coding: utf-8 -*-

from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest
from unittest.mock import patch
import zipfile

from actualizacion_datos.lectores import leer_libro_reglas
from actualizacion_datos.modelos import EstadoEtapa, FormatoArchivo, TablaDatos
from actualizacion_datos.reglas_gio import MatrizReglasGio, MatrizTipologias, ReglaTipologia
from actualizacion_datos.servicio import RutasEntradasActualizacion, ServicioProcesamientoActualizaciones


def crear_libro_reglas(ruta: Path, nombres=None) -> None:
    tipos = "http://schemas.openxmlformats.org/package/2006/content-types"
    relaciones = "http://schemas.openxmlformats.org/package/2006/relationships"
    datos_hojas = {
        "ACTIVIDAD": [["C", "TIPO", "FUENTE", "TIPO_2"], ["TO-C", "C", "C", "Cierre"], ["TO-R", "R", "R", "Reapertura"]],
        "OPERARIO": [["Auxiliar"], ["OPER", "CODIGO GIO", "CODIGO SYSACAO"], ["ANA", "G1", "S1"]],
        "LECT": [["Auxiliar"], ["NIS_RAD", "LECT"], ["N-C", "100"]],
    }
    nombres = nombres or {clave: clave for clave in datos_hojas}
    hojas = {nombres[clave]: filas for clave, filas in datos_hojas.items() if clave in nombres}

    def xml_hoja(filas):
        partes = ['<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>']
        for numero, fila in enumerate(filas, 1):
            partes.append(f'<row r="{numero}">')
            for indice, valor in enumerate(fila):
                columna = chr(65 + indice)
                partes.append(f'<c r="{columna}{numero}" t="inlineStr"><is><t>{valor}</t></is></c>')
            partes.append("</row>")
        partes.append("</sheetData></worksheet>")
        return "".join(partes)

    with zipfile.ZipFile(ruta, "w") as archivo:
        archivo.writestr("[Content_Types].xml", f'<Types xmlns="{tipos}"><Default Extension="xml" ContentType="application/xml"/></Types>')
        lista = "".join(
            f'<sheet name="{nombre}" sheetId="{i}" r:id="rId{i}"/>'
            for i, nombre in enumerate(hojas, 1)
        )
        archivo.writestr(
            "xl/workbook.xml",
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            f"<sheets>{lista}</sheets></workbook>",
        )
        relaciones_xml = "".join(
            f'<Relationship Id="rId{i}" Type="x" Target="worksheets/sheet{i}.xml"/>'
            for i in range(1, len(hojas) + 1)
        )
        archivo.writestr("xl/_rels/workbook.xml.rels", f'<Relationships xmlns="{relaciones}">{relaciones_xml}</Relationships>')
        for i, filas in enumerate(hojas.values(), 1):
            archivo.writestr(f"xl/worksheets/sheet{i}.xml", xml_hoja(filas))


class PruebasIntegracionFlujoActualizaciones(unittest.TestCase):
    def test_fecha_inexistente_no_crea_salida(self):
        with TemporaryDirectory() as temporal:
            raiz = Path(temporal)
            archivos = {
                nombre: raiz / nombre
                for nombre in ("sansys.csv", "gio.csv", "reglas.xlsx", "matriz.xlsx")
            }
            for ruta in archivos.values():
                ruta.write_text("prueba", encoding="utf-8")
            salida = raiz / "salida_no_debe_crearse"
            rutas = RutasEntradasActualizacion(
                ruta_csv_sansys=archivos["sansys.csv"],
                ruta_control_gio=archivos["gio.csv"],
                ruta_entregable_acumulado=None,
                ruta_libro_reglas=archivos["reglas.xlsx"],
                carpeta_salida=salida,
                ruta_matriz_gio=archivos["matriz.xlsx"],
                considerar_entregable_acumulado=False,
            )
            tabla = TablaDatos(
                ruta=archivos["sansys.csv"],
                encabezados=["OT", "OS", "FECHA"],
                filas=[{"OT": "1", "OS": "2", "FECHA": "15/09/2026"}],
                formato=FormatoArchivo("csv", columnas=("OT", "OS", "FECHA")),
            )
            servicio = ServicioProcesamientoActualizaciones()
            with patch.object(servicio, "_leer_sansys", return_value=tabla):
                with self.assertRaisesRegex(ValueError, "fecha seleccionada no existe"):
                    servicio.procesar_flujo_comun(rutas, "16/09/2026")
            self.assertFalse(salida.exists())

    def test_libro_unico_detecta_hojas_y_encabezados(self):
        with TemporaryDirectory() as temporal:
            ruta = Path(temporal) / "reglas.xlsx"
            crear_libro_reglas(ruta, {
                "ACTIVIDAD": " actividad ", "OPERARIO": "Operario", "LECT": " lect ",
            })
            libro = leer_libro_reglas(ruta)
            self.assertEqual(libro.metadatos["ACTIVIDAD"]["fila_encabezado"], 1)
            self.assertEqual(libro.metadatos["OPERARIO"]["fila_encabezado"], 2)
            self.assertEqual(libro.metadatos["LECT"]["fila_encabezado"], 2)
            self.assertEqual(len(libro.operarios.filas), 1)
            self.assertEqual(libro.lecturas.filas[0]["NIS_RAD"], "N-C")

    def test_libro_sin_hoja_obligatoria_se_bloquea(self):
        with TemporaryDirectory() as temporal:
            ruta = Path(temporal) / "reglas_incompletas.xlsx"
            crear_libro_reglas(ruta, {"ACTIVIDAD": "ACTIVIDAD", "OPERARIO": "OPERARIO"})
            with self.assertRaisesRegex(ValueError, "LECT"):
                leer_libro_reglas(ruta)

    def test_flujo_cierres_entregable_actualizado_reaperturas(self):
        with TemporaryDirectory() as temporal:
            raiz = Path(temporal)
            general = raiz / "general.csv"
            general.write_text(
                "OT;OS;NIS;FECHA;HI;HF;ACC;COO;OBS;LECT;TIPO\n"
                "OT-C;OS-C;N-C;21/09/2026;10:00;11:00;511;S1;HI: 10:00 HF: 11:00 OBS: cierre;110;C\n"
                "OT-R;OS-R;N-C;21/09/2026;10:00;11:00;611;S1;Reapertura;120;R\n",
                encoding="utf-8",
            )
            control = raiz / "gio.txt"
            control.write_text(
                "nro_ot\tnnum_os\tnis_rad\testado\tvtipo_os\tactividad\tdesc_actividad\n"
                "OT-C\tOS-C\tN-C\tTRAB\tTO-C\t291\tCierre\n"
                "OT-R\tOS-R\tN-C\tTRAB\tTO-R\t291\tReapertura\n",
                encoding="utf-8",
            )
            acumulado = raiz / "acumulado.txt"
            acumulado.write_text(
                "nis_rad\tOT\tOS\tFEJECUCION\tHI\tHF\tACCION\tCODIGO\tOBSERVACION\tLECT\n",
                encoding="utf-8-sig",
            )
            libro_reglas = raiz / "reglas.xlsx"
            crear_libro_reglas(libro_reglas)
            configuracion = raiz / "configuracion.json"
            columnas = ["OT", "OS", "FECHA", "HI", "HF", "ACC", "CODIGO_GIO", "OBS", "LECT"]
            configuracion.write_text(json.dumps({
                "reglas_accion": [{
                    "id_regla": "CIERRE-C-511", "tipo": "C", "accion_ejecutada": "511",
                    "aplica_lectura": True, "acciones_reapertura": ["611"],
                }],
                "contratos": {
                    "cierres_sistema": {"nombre": "CIERRES_SISTEMA", "columnas": columnas, "confirmado": True},
                    "entregable_cierres": {"nombre": "ENTREGABLE_CIERRES", "columnas": ["NIS", *columnas], "confirmado": True},
                    "reaperturas_sistema": {"nombre": "REAPERTURAS_SISTEMA", "columnas": columnas, "confirmado": True},
                    "entregable_reaperturas": {"nombre": "ENTREGABLE_REAPERTURAS", "columnas": ["NIS", *columnas], "confirmado": True},
                },
            }, ensure_ascii=False), encoding="utf-8")
            rutas = RutasEntradasActualizacion(
                ruta_csv_sansys=general, ruta_control_gio=control,
                ruta_entregable_acumulado=acumulado, ruta_libro_reglas=libro_reglas,
                carpeta_salida=raiz / "salida",
                configuracion_json=configuracion,
            )
            servicio = ServicioProcesamientoActualizaciones()
            resultado = servicio.procesar_flujo_comun(rutas, "21/09/2026")
            self.assertEqual(len(resultado.flujo_comun.data_filtrada), 2)
            self.assertEqual(len(resultado.flujo_comun.cierres_preparados), 1)
            self.assertEqual(len(resultado.flujo_comun.reaperturas_preparadas), 1)
            fotografia = [fila.datos_normalizados.copy() for fila in resultado.flujo_comun.data_filtrada]
            self.assertIn("csv_sansys", resultado.contexto.entradas)
            self.assertIn("libro_reglas", resultado.contexto.entradas)
            self.assertNotIn("catalogo_actividades", resultado.contexto.entradas)
            self.assertEqual(
                resultado.contexto.metadatos_entradas["libro_reglas"]["LECT"]["fila_encabezado"],
                2,
            )
            resultado = servicio.procesar_cierres()
            self.assertEqual(len(resultado.cierres.listas), 1)
            self.assertTrue(Path(resultado.contexto.entregable_cierres).exists())

            actualizado = raiz / "entregable_actualizado.txt"
            actualizado.write_text(
                "nis_rad\tFEJECUCION\tACCION\tLECT\nN-C\t21/09/2026\t511\t110\n",
                encoding="utf-8-sig",
            )
            progreso_entregable = []
            servicio.cargar_entregable_actualizado(
                actualizado,
                lambda etapa, actual, total: progreso_entregable.append(
                    (etapa, actual, total)
                ),
            )
            self.assertEqual(
                [etapa for etapa, _actual, _total in progreso_entregable],
                [
                    "Leyendo entregable actualizado",
                    "Validando estructura del entregable",
                    "Preparando reaperturas",
                    "Entregable actualizado cargado",
                ],
            )
            servicio.matriz_gio = MatrizReglasGio(
                (), frozenset(), ("MATRIZ_TIPOLOGIAS",),
                tipologias=MatrizTipologias((
                    ReglaTipologia(
                        "C", "511", "511", "611", "CIERRE_VALIDO", "",
                        True, 2,
                    ),
                )),
            )
            resultado = servicio.procesar_reaperturas()
            self.assertEqual(len(resultado.reaperturas.listas), 1)
            self.assertEqual(resultado.contexto.estados_etapas["REAPERTURAS"], EstadoEtapa.COMPLETADO)
            self.assertTrue(Path(resultado.contexto.archivos_generados["reaperturas_sistema"]).exists())
            self.assertTrue((servicio.rutas_salida.auditoria).exists())
            self.assertEqual(servicio.cantidad_lecturas_sansys, 1)
            self.assertEqual(
                [fila.datos_normalizados for fila in resultado.flujo_comun.data_filtrada],
                fotografia,
            )


if __name__ == "__main__":
    unittest.main()
