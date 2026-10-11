# -*- coding: utf-8 -*-

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import zipfile

from actualizacion_datos.lectores import leer_matriz_reglas_gio
from actualizacion_datos.modelos import (
    CategoriaResultado,
    FormatoArchivo,
    RegistroProcesamiento,
    TablaDatos,
)
from actualizacion_datos.reglas_gio import (
    construir_matriz_gio,
    evaluar_regla_gio,
    normalizar_accion_gio,
)
from actualizacion_datos.cierres import procesar_cierres


COLUMNAS_REGLAS = [
    "ID_REGLA", "PRIORIDAD", "RGLA", "COINCIDENCIA_OBS", "PATRON_OBS",
    "CONDICION_ACC", "ACC_LISTA", "ACC_MIN", "ACC_MAX", "RESULTADO",
    "CATEGORIA", "MOTIVO", "DESTINO", "ACTIVO",
]
COLUMNAS_TIPOLOGIAS = [
    "TIPO", "ACC", "CIERRE_EFECTIVO", "REAPERTURA_ESPERADA",
    "RESULTADO", "ACTIVO", "CONDICION",
]


def regla(
    identificador, prioridad, tipo, condicion_obs, patron, condicion_acc,
    lista="", minimo="", maximo="", resultado="VALIDO_EFECTIVO", activo="SI",
):
    return dict(zip(COLUMNAS_REGLAS, [
        identificador, str(prioridad), tipo, condicion_obs, patron,
        condicion_acc, lista, str(minimo), str(maximo), resultado,
        "PRUEBA", identificador, "CONTINUAR", activo,
    ]))


def matriz(reglas, combinaciones=()):
    tabla_reglas = TablaDatos(Path("reglas.xlsx"), COLUMNAS_REGLAS, list(reglas), FormatoArchivo("xlsx"))
    columnas = ["RGLA", "OBSERVACION", "ncod_causa"]
    filas = [dict(zip(columnas, valores)) for valores in combinaciones]
    tabla_combinaciones = TablaDatos(Path("reglas.xlsx"), columnas, filas, FormatoArchivo("xlsx"))
    return construir_matriz_gio(
        tabla_reglas, tabla_combinaciones,
        ("RESUMEN", "REGLAS_GIO", "COMBINACIONES_GIO", "GUIA_USO"),
    )


def registro(tipo, observacion, accion):
    return RegistroProcesamiento(
        "fila-1", "sansys.csv", 2, {},
        {"TIPO": tipo, "OBS_TIPO": observacion, "ACC": accion},
    )


def crear_libro_incompleto(ruta, hojas=None, encabezados_personalizados=None):
    hojas = hojas or ("RESUMEN", "COMBINACIONES_GIO", "GUIA_USO")
    encabezados_personalizados = encabezados_personalizados or {}
    with zipfile.ZipFile(ruta, "w") as archivo:
        archivo.writestr(
            "[Content_Types].xml",
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>'
        )
        lista = "".join(
            f'<sheet name="{nombre}" sheetId="{indice}" r:id="rId{indice}"/>'
            for indice, nombre in enumerate(hojas, 1)
        )
        archivo.writestr(
            "xl/workbook.xml",
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            f"<sheets>{lista}</sheets></workbook>",
        )
        relaciones = "".join(
            f'<Relationship Id="rId{indice}" Type="x" Target="worksheets/sheet{indice}.xml"/>'
            for indice in range(1, len(hojas) + 1)
        )
        archivo.writestr(
            "xl/_rels/workbook.xml.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f"{relaciones}</Relationships>",
        )
        for indice in range(1, len(hojas) + 1):
            nombre = hojas[indice - 1]
            encabezados = encabezados_personalizados.get(nombre)
            if encabezados is None:
                encabezados = {
                    "REGLAS_GIO": COLUMNAS_REGLAS,
                    "COMBINACIONES_GIO": ["RGLA", "OBSERVACION", "ncod_causa"],
                    "MATRIZ_TIPOLOGIAS": COLUMNAS_TIPOLOGIAS,
                }.get(nombre, [])
            celdas = "".join(
                f'<c r="{chr(65 + posicion)}1" t="inlineStr"><is><t>{valor}</t></is></c>'
                for posicion, valor in enumerate(encabezados)
            )
            fila = f'<row r="1">{celdas}</row>' if celdas else ""
            archivo.writestr(
                f"xl/worksheets/sheet{indice}.xml",
                '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                f'<sheetData>{fila}</sheetData></worksheet>',
            )


class PruebasMatrizReglasGio(unittest.TestCase):
    def test_normaliza_codigos_separados_sin_cambiar_familia(self):
        casos = {
            "5-06": "506",
            "5.06": "506",
            "506": "506",
            "506.0": "506",
            "6-06": "606",
            "6.06": "606",
            "606": "606",
            "606.0": "606",
        }
        self.assertEqual(
            {valor: normalizar_accion_gio(valor) for valor in casos},
            casos,
        )

    def setUp(self):
        self.matriz = matriz([
            regla("GIO-010", 10, "C", "CONTIENE", "CIERRE SIMPLE", "LISTA", "511"),
            regla("GIO-011", 11, "CD", "CONTIENE", "DISPOSITIVO INTRUSIVO", "LISTA", "506"),
            regla("GIO-012", 12, "CD", "CONTIENE", "RETIRO DE 1/2 METRO", "LISTA", "519"),
            regla("GIO-032", 32, "RD", "CONTIENE", "DISPOSITIVO INTRUSIVO", "LISTA", "606"),
            regla("GIO-005", 5, "*", "CUALQUIERA", "", "RANGO", minimo="700", maximo="999999", resultado="ERROR"),
            regla("GIO-004", 4, "*", "CUALQUIERA", "", "VACIO", resultado="REVISION"),
            regla("GIO-090", 90, "*", "CUALQUIERA", "", "CUALQUIERA", resultado="REVISION"),
        ], [("C", "CIERRE SIMPLE", "508")])

    def comprobar(self, tipo, observacion, accion, identificador):
        fila = registro(tipo, observacion, accion)
        resultado = evaluar_regla_gio(fila, self.matriz)
        self.assertIsNotNone(resultado)
        self.assertEqual(resultado.id_regla, identificador)
        return fila

    def test_cierre_simple_511(self):
        self.comprobar("C", "Cierre simple", "511", "GIO-010")

    def test_cierre_simple_508_va_a_revision_observada(self):
        fila = registro("C", "CIERRE SIMPLE", "508")
        self.assertIsNone(evaluar_regla_gio(fila, self.matriz))
        self.assertEqual(fila.motivo_final, "REGLA_GIO_NO_CONFIGURADA")

    def test_respaldo_historico_no_aprueba_automaticamente(self):
        configurada = matriz(
            [regla("GIO-090", 90, "*", "CUALQUIERA", "", "CUALQUIERA", resultado="REVISION")],
            [("V", "VISITA ESPECIAL", "529")],
        )
        fila = registro("V", "visita especial", "529")
        self.assertIsNone(evaluar_regla_gio(fila, configurada))
        self.assertEqual(fila.datos_normalizados["ESTADO_VALIDACION_GIO"], "OBSERVADA_SIN_APROBACION")

    def test_accion_no_efectiva_continua_sin_validar_diferencia(self):
        configurada = matriz([
            regla(
                "GIO-020", 20, "C|CD|V", "CUALQUIERA", "", "RANGO",
                minimo="530", maximo="580", resultado="VALIDO_NO_EFECTIVO",
            ),
        ])
        fila = registro("C", "IMPOSIBILIDAD", "550")
        fila.datos_normalizados.update({
            "HI": "10:00", "HF": "11:00",
            "OBS": "HI: 10:00 HF: 11:00 OBS: imposibilidad",
        })
        resultado = procesar_cierres([fila], matriz_gio=configurada)
        self.assertEqual(resultado.listas, [fila])
        self.assertEqual(resultado.revisiones, [])
        self.assertEqual(resultado.exclusiones, [])
        self.assertNotIn("DIFERENCIA", fila.datos_normalizados)

    def test_cd_dispositivo_506(self):
        self.comprobar("CD", "Dispositivo intrusivo", "506", "GIO-011")

    def test_cd_retiro_519(self):
        self.comprobar("CD", "Retiro de 1/2 metro", "519", "GIO-012")

    def test_rd_dispositivo_606(self):
        self.comprobar("RD", "Dispositivo intrusivo", "606", "GIO-032")

    def test_accion_mayor_o_igual_a_700_es_revision(self):
        fila = self.comprobar("C", "CIERRE SIMPLE", "700", "GIO-005")
        self.assertEqual(fila.categoria_final, CategoriaResultado.REVISION_MANUAL)

    def test_accion_vacia_es_revision(self):
        fila = self.comprobar("C", "CIERRE SIMPLE", "", "GIO-004")
        self.assertEqual(fila.categoria_final, CategoriaResultado.REVISION_MANUAL)

    def test_combinacion_desconocida(self):
        fila = registro("V", "NO EXISTE", "529")
        self.assertIsNone(evaluar_regla_gio(fila, self.matriz))
        self.assertEqual(fila.motivo_final, "REGLA_GIO_NO_CONFIGURADA")

    def test_v_524_ausente_va_a_revision(self):
        configurada = matriz([
            regla("OTRA", 1, "V", "CONTIENE", "TARUGO AL RAS", "LISTA", "521"),
        ])
        fila = registro("V", "Revisión de suministro cerrado con tarugo al ras", "524")
        self.assertIsNone(evaluar_regla_gio(fila, configurada))
        self.assertEqual(fila.motivo_final, "REGLA_GIO_NO_CONFIGURADA")

    def test_v_524_activa_en_matriz_continua_sin_cambiar_python(self):
        configurada = matriz([
            regla("V-524", 1, "V", "CONTIENE", "TARUGO AL RAS", "LISTA", "524", resultado="CONTINUAR"),
        ])
        fila = registro("V", "Revisión de suministro cerrado con tarugo al ras", "524")
        encontrada = evaluar_regla_gio(fila, configurada)
        self.assertIsNotNone(encontrada)
        self.assertEqual(encontrada.id_regla, "V-524")

    def test_patron_puede_coincidir_en_observacion_original_sansys(self):
        configurada = matriz([
            regla("DINAMICA", 1, "V", "CONTIENE", "TARUGO AL RAS", "LISTA", "524", resultado="CONTINUAR"),
        ])
        fila = registro("V", "Revision de suministro cerrado CN 15 mm", "524")
        fila.datos_normalizados["OBS"] = "COD: 524 - Rev. de cierre con tarugo al ras"
        encontrada = evaluar_regla_gio(fila, configurada)
        self.assertIsNotNone(encontrada)
        self.assertEqual(encontrada.id_regla, "DINAMICA")

    def test_v_524_inactiva_va_a_revision(self):
        configurada = matriz([
            regla("V-524", 1, "V", "CONTIENE", "TARUGO AL RAS", "LISTA", "524", resultado="CONTINUAR", activo="NO"),
        ])
        fila = registro("V", "Revisión de suministro cerrado con tarugo al ras", "524")
        self.assertIsNone(evaluar_regla_gio(fila, configurada))
        self.assertEqual(fila.motivo_final, "REGLA_GIO_NO_CONFIGURADA")

    def test_una_accion_nueva_se_reconoce_solo_por_la_matriz(self):
        configurada = matriz([
            regla("NUEVA-612", 1, "RD", "CUALQUIERA", "", "LISTA", "612", resultado="CONTINUAR"),
        ])
        fila = registro("RD", "Actividad nueva", "612")
        self.assertEqual(evaluar_regla_gio(fila, configurada).id_regla, "NUEVA-612")

    def test_reglas_activas_superpuestas_con_misma_prioridad_bloquean(self):
        with self.assertRaisesRegex(ValueError, "PRIMERA.*SEGUNDA"):
            matriz([
                regla("PRIMERA", 1, "V", "CUALQUIERA", "", "LISTA", "524", resultado="CONTINUAR"),
                regla("SEGUNDA", 1, "V", "CUALQUIERA", "", "LISTA", "524", resultado="REVISION"),
            ])

    def test_id_regla_duplicado_bloquea(self):
        with self.assertRaisesRegex(ValueError, "ID_REGLA duplicado"):
            matriz([
                regla("DUPLICADA", 1, "V", "CUALQUIERA", "", "LISTA", "524"),
                regla("DUPLICADA", 2, "V", "CUALQUIERA", "", "LISTA", "525"),
            ])

    def test_activo_invalido_bloquea(self):
        with self.assertRaisesRegex(ValueError, "ACTIVO debe ser SI o NO"):
            matriz([regla("ACTIVO-MAL", 1, "V", "CUALQUIERA", "", "LISTA", "524", activo="QUIZAS")])

    def test_rango_incoherente_bloquea(self):
        with self.assertRaisesRegex(ValueError, "rango incoherente"):
            matriz([regla("RANGO-MAL", 1, "V", "CUALQUIERA", "", "RANGO", minimo="580", maximo="530")])

    def test_prioridad_gana_la_primera_coincidencia(self):
        configurada = matriz([
            regla("SEGUNDA", 20, "C", "CUALQUIERA", "", "LISTA", "511"),
            regla("PRIMERA", 10, "C", "CUALQUIERA", "", "LISTA", "511"),
        ])
        fila = registro("C", "texto", "511")
        self.assertEqual(evaluar_regla_gio(fila, configurada).id_regla, "PRIMERA")

    def test_regla_inactiva_no_se_ejecuta(self):
        configurada = matriz([
            regla("INACTIVA", 1, "C", "CUALQUIERA", "", "LISTA", "511", activo="NO"),
            regla("ACTIVA", 2, "C", "CUALQUIERA", "", "LISTA", "511"),
        ])
        fila = registro("C", "texto", "511")
        self.assertEqual(evaluar_regla_gio(fila, configurada).id_regla, "ACTIVA")

    def test_normaliza_mayusculas_espacios_tildes_y_decimal_excel(self):
        configurada = matriz([
            regla("NORMALIZADA", 1, "C", "CONTIENE", "OBTURACION", "LISTA", "511"),
        ])
        fila = registro(" c ", "  obturación   completa ", "511.0")
        self.assertEqual(evaluar_regla_gio(fila, configurada).id_regla, "NORMALIZADA")
        self.assertEqual(fila.datos_normalizados["OBSERVACION_ORIGINAL"], "  obturación   completa ")

    def test_libro_con_todas_las_hojas_se_carga(self):
        hojas = ("RESUMEN", "REGLAS_GIO", "COMBINACIONES_GIO", "GUIA_USO", "MATRIZ_TIPOLOGIAS")
        with TemporaryDirectory() as temporal:
            ruta = Path(temporal) / "matriz_prueba.xlsx"
            crear_libro_incompleto(ruta, hojas)
            cargada = leer_matriz_reglas_gio(ruta)
            self.assertEqual(set(cargada.hojas), set(hojas))
            self.assertIsNotNone(cargada.tipologias)
            self.assertEqual(set(cargada.tablas), set(hojas))

    def test_ausencia_de_reglas_gio_bloquea(self):
        with TemporaryDirectory() as temporal:
            ruta = Path(temporal) / "incompleta.xlsx"
            crear_libro_incompleto(ruta)
            with self.assertRaisesRegex(ValueError, "REGLAS_GIO"):
                leer_matriz_reglas_gio(ruta)

    def test_excel_sin_columnas_obligatorias_bloquea(self):
        hojas = ("RESUMEN", "REGLAS_GIO", "COMBINACIONES_GIO", "GUIA_USO", "MATRIZ_TIPOLOGIAS")
        with TemporaryDirectory() as temporal:
            ruta = Path(temporal) / "matriz_incompleta.xlsx"
            crear_libro_incompleto(
                ruta, hojas, {"MATRIZ_TIPOLOGIAS": ["TIPO", "ACC"]}
            )
            with self.assertRaisesRegex(ValueError, "MATRIZ_TIPOLOGIAS no contiene"):
                leer_matriz_reglas_gio(ruta)


if __name__ == "__main__":
    unittest.main()
