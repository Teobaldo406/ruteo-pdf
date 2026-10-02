# -*- coding: utf-8 -*-

from pathlib import Path
import unittest

from actualizacion_datos.configuracion import ConfiguracionProcesamiento
from actualizacion_datos.flujo_comun import _crear_registros, procesar_flujo_comun
from actualizacion_datos.modelos import CategoriaResultado, FormatoArchivo, TablaDatos


def tabla(nombre, encabezados, filas):
    return TablaDatos(
        ruta=Path(nombre),
        encabezados=list(encabezados),
        filas=list(filas),
        formato=FormatoArchivo("csv", columnas=tuple(encabezados)),
    )


class PruebasFlujoComun(unittest.TestCase):
    def setUp(self):
        self.configuracion = ConfiguracionProcesamiento.predeterminada()
        self.operarios = tabla(
            "operarios.xlsx", ["OPER", "CODIGO GIO", "CODIGO SYSACAO"],
            [{"OPER": "ANA", "CODIGO GIO": "G1", "CODIGO SYSACAO": "S1"}],
        )
        self.acumulado = tabla(
            "acumulado.txt", ["nis_rad", "OT", "OS"],
            [{"nis_rad": "99", "OT": "OT-YA", "OS": "OS-YA"}],
        )

    def test_detecta_bloque_real_sin_encabezados(self):
        general = tabla(
            "DATA_GENERAL.xlsx",
            [
                "nro_ot", "nnum_os", "nis_rad", "ncod_cuadrilla", "null", "COLUMNA_5",
                "COLUMNA_6", "COLUMNA_7", "COLUMNA_8", "COLUMNA_9",
                "COLUMNA_10", "COLUMNA_11", "COLUMNA_12",
            ],
            [{
                "nro_ot": "11111111", "nnum_os": "222222222", "nis_rad": "3276052.0",
                "ncod_cuadrilla": "1548.0",
                "null": "7.1932613E7", "COLUMNA_5": "8.15996033E8",
                "COLUMNA_6": "46281.0", "COLUMNA_7": "16.28", "COLUMNA_8": "16.29",
                "COLUMNA_9": "611.0", "COLUMNA_10": "3111153.0",
                "COLUMNA_11": "OBSERVACION", "COLUMNA_12": "974.0",
            }],
        )
        registro = _crear_registros(general, self.configuracion)[0]
        self.assertEqual(registro.datos_normalizados["OT"], "71932613")
        self.assertEqual(registro.datos_normalizados["FECHA"], "2026-09-16")
        self.assertEqual(registro.datos_normalizados["COO"], "3111153")
        self.assertEqual(registro.datos_normalizados["NIS"], "3276052")
        self.assertNotEqual(registro.datos_normalizados["OS"], "222222222")

    def test_detecta_bloque_desplazado_solo_en_la_fila_afectada(self):
        encabezados = [
            "nro_ot", "nnum_os", "nis_rad", "vtipo_os", "null",
            *[f"COLUMNA_EXTRA_{i}" for i in range(1, 10)],
        ]
        general = tabla(
            "sansys.csv", encabezados,
            [
                {
                    "nro_ot": "OT-BASE-1", "nnum_os": "OS-BASE-1", "nis_rad": "000123",
                    "vtipo_os": "TO582", "null": "71900001", "COLUMNA_EXTRA_1": "214000001",
                    "COLUMNA_EXTRA_2": "27/09/2026", "COLUMNA_EXTRA_3": "10:01",
                    "COLUMNA_EXTRA_4": "10:02", "COLUMNA_EXTRA_5": "511",
                    "COLUMNA_EXTRA_6": "0017", "COLUMNA_EXTRA_7": "OBS NORMAL",
                    "COLUMNA_EXTRA_8": "25", "COLUMNA_EXTRA_9": "",
                },
                {
                    "nro_ot": "OT-BASE-2", "nnum_os": "OS-BASE-2", "nis_rad": "000124",
                    "vtipo_os": "TO582", "null": "RESIDUO", "COLUMNA_EXTRA_1": "71900002",
                    "COLUMNA_EXTRA_2": "214000002", "COLUMNA_EXTRA_3": "27/09/2026",
                    "COLUMNA_EXTRA_4": "11:01", "COLUMNA_EXTRA_5": "11:02",
                    "COLUMNA_EXTRA_6": "511", "COLUMNA_EXTRA_7": "0018",
                    "COLUMNA_EXTRA_8": "OBS DESPLAZADA", "COLUMNA_EXTRA_9": "30",
                },
            ],
        )
        registros = _crear_registros(general, self.configuracion)
        self.assertEqual(registros[0].datos_normalizados["OT"], "71900001")
        self.assertEqual(registros[0].datos_normalizados["OS"], "214000001")
        self.assertEqual(registros[1].datos_normalizados["OT"], "71900002")
        self.assertEqual(registros[1].datos_normalizados["OS"], "214000002")
        self.assertEqual(registros[1].datos_normalizados["NIS"], "000124")
        self.assertEqual(registros[1].datos_normalizados["TIPO_OS"], "TO582")
        self.assertEqual(registros[1].datos_normalizados["LECT"], "30")

    def test_bloque_no_reconocible_va_a_revision_con_fila_original(self):
        general = tabla(
            "sansys.csv",
            ["nro_ot", "nnum_os", "nis_rad", "null", *[f"COLUMNA_EXTRA_{i}" for i in range(1, 10)]],
            [{"nro_ot": "BASE", "nnum_os": "BASE-OS", "nis_rad": "9", "null": "basura"}],
        )
        registro = _crear_registros(general, self.configuracion)[0]
        self.assertEqual(registro.motivo_final, "BLOQUE_OPERATIVO_NO_RECONOCIBLE")
        self.assertEqual(registro.categoria_final, CategoriaResultado.REVISION_MANUAL)
        self.assertEqual(registro.como_fila_auditoria("X")["FILA_ORIGINAL"], "2")

    def test_reconoce_catalogo_real_de_actividades(self):
        general = tabla(
            "general.csv", ["OT", "OS", "NIS", "FECHA", "COO"],
            [{"OT": "1", "OS": "A", "NIS": "9", "FECHA": "21/09/2026", "COO": "S1"}],
        )
        control = tabla(
            "gio.txt", ["OT", "OS", "ESTADO", "TIPO_OS"],
            [{"OT": "1", "OS": "A", "ESTADO": "TRAB", "TIPO_OS": "TO204"}],
        )
        actividades = tabla(
            "actividades.xlsx", ["C", "TIPO", "FUENTE", "TIPO_2"],
            [{"C": "TO204", "TIPO": "CD", "FUENTE": "CD", "TIPO_2": "Cierre drástico"}],
        )
        resultado = procesar_flujo_comun(
            general, control, self.acumulado,
            fecha_procesamiento="21/09/2026", configuracion=self.configuracion,
            tabla_operarios=self.operarios, tabla_actividades=actividades,
        )
        self.assertEqual(len(resultado.data_filtrada), 1)
        self.assertEqual(resultado.data_filtrada[0].tipo, "CD")
        self.assertEqual(resultado.data_filtrada[0].datos_normalizados["OBS_TIPO"], "Cierre drástico")

    def test_tipo_os_ausente_en_actividad_va_a_revision_exacta(self):
        general = tabla(
            "general.csv", ["OT", "OS", "NIS", "FECHA", "COO", "vtipo_os"],
            [{"OT": "1", "OS": "A", "NIS": "9", "FECHA": "21/09/2026", "COO": "S1", "vtipo_os": "TO999"}],
        )
        control = tabla(
            "gio.txt", ["OT", "OS", "ESTADO"],
            [{"OT": "1", "OS": "A", "ESTADO": "TRAB"}],
        )
        actividades = tabla(
            "actividades.xlsx", ["C", "TIPO", "FUENTE", "TIPO_2"],
            [{"C": "TO204", "TIPO": "CD", "FUENTE": "CD", "TIPO_2": "Cierre drástico"}],
        )
        resultado = procesar_flujo_comun(
            general, control, self.acumulado,
            fecha_procesamiento="21/09/2026", configuracion=self.configuracion,
            tabla_operarios=self.operarios, tabla_actividades=actividades,
        )
        self.assertEqual(resultado.registros[0].motivo_final, "TIPO_OS_NO_ENCONTRADO_EN_ACTIVIDAD")
        self.assertEqual(resultado.registros[0].regla_final, "TIP-01")

    def test_convierte_390_filas_con_siete_codigos_sysacao(self):
        codigos = [(f"S{i}", f"G{i}") for i in range(7)]
        filas_general = []
        filas_control = []
        for indice in range(390):
            sysacao, _gio = codigos[indice % 7]
            filas_general.append({
                "OT": f"OT-{indice}", "OS": f"OS-{indice}", "NIS": str(indice),
                "FECHA": "21/09/2026", "TIPO": "C", "COO": sysacao,
            })
            filas_control.append({
                "OT": f"OT-{indice}", "OS": f"OS-{indice}", "ESTADO": "TRAB",
            })
        operarios = tabla(
            "operarios.xlsx", ["OPER", "CODIGO GIO", "CODIGO SYSACAO"],
            [
                {"OPER": f"OPERARIO {i}", "CODIGO GIO": gio, "CODIGO SYSACAO": sysacao}
                for i, (sysacao, gio) in enumerate(codigos)
            ],
        )
        resultado = procesar_flujo_comun(
            tabla("sansys.csv", filas_general[0].keys(), filas_general),
            tabla("gio.txt", filas_control[0].keys(), filas_control),
            self.acumulado, fecha_procesamiento="21/09/2026",
            configuracion=self.configuracion, tabla_operarios=operarios,
        )
        self.assertEqual(len(resultado.data_filtrada), 390)
        for registro in resultado.data_filtrada:
            self.assertTrue(registro.datos_normalizados["COO_ORIGINAL_SYSACAO"].startswith("S"))
            self.assertTrue(registro.datos_normalizados["COO_FINAL_GIO"].startswith("G"))
            self.assertEqual(registro.datos_normalizados["COO"], registro.datos_normalizados["COO_FINAL_GIO"])

    def test_cruce_operario_normaliza_codigos_y_no_busca_por_gio(self):
        valores = ["100.0", "3.111153E6", "00123", "G9", ""]
        general = tabla(
            "sansys.csv", ["OT", "OS", "NIS", "FECHA", "TIPO", "COO"],
            [
                {"OT": f"OT-{i}", "OS": f"OS-{i}", "NIS": str(i),
                 "FECHA": "21/09/2026", "TIPO": "C", "COO": valor}
                for i, valor in enumerate(valores)
            ],
        )
        control = tabla(
            "gio.txt", ["OT", "OS", "ESTADO"],
            [{"OT": f"OT-{i}", "OS": f"OS-{i}", "ESTADO": "TRAB"} for i in range(5)],
        )
        operarios = tabla(
            "operarios.xlsx", ["OPER", "CODIGO GIO", "CODIGO SYSACAO"],
            [
                {"OPER": "A", "CODIGO GIO": "G1", "CODIGO SYSACAO": "100"},
                {"OPER": "B", "CODIGO GIO": "G2", "CODIGO SYSACAO": "3111153"},
                {"OPER": "C", "CODIGO GIO": "G3", "CODIGO SYSACAO": "00123"},
                {"OPER": "D", "CODIGO GIO": "G9", "CODIGO SYSACAO": "999"},
            ],
        )
        resultado = procesar_flujo_comun(
            general, control, self.acumulado, fecha_procesamiento="21/09/2026",
            configuracion=self.configuracion, tabla_operarios=operarios,
        )
        self.assertEqual([r.datos_normalizados["COO"] for r in resultado.data_filtrada], ["G1", "G2", "G3", "G9"])
        self.assertEqual(resultado.data_filtrada[3].datos_normalizados["ESTADO_CONVERSION"], "SIN_CONVERSION_REQUERIDA")
        revisiones = {r.ot: r for r in resultado.registros if r.motivo_final}
        self.assertNotIn("OT-3", revisiones)
        self.assertEqual(revisiones["OT-4"].motivo_final, "COO_VACIO")

    def test_conserva_dieciocho_codigos_y_convierte_dos(self):
        conservados = [f"GIO-{i:02d}" for i in range(18)]
        valores = [*conservados, "SYS-1", "SYS-2", ""]
        general = tabla(
            "sansys.csv", ["OT", "OS", "NIS", "FECHA", "TIPO", "COO"],
            [{
                "OT": f"OT-{i}", "OS": f"OS-{i}", "NIS": str(i),
                "FECHA": "21/09/2026", "TIPO": "C", "COO": codigo,
            } for i, codigo in enumerate(valores)],
        )
        control = tabla(
            "gio.txt", ["OT", "OS", "ESTADO"],
            [{"OT": f"OT-{i}", "OS": f"OS-{i}", "ESTADO": "TRAB"} for i in range(len(valores))],
        )
        operarios = tabla(
            "operarios.xlsx", ["OPER", "CODIGO GIO", "CODIGO SYSACAO"],
            [
                {"OPER": "A", "CODIGO GIO": "FINAL-1", "CODIGO SYSACAO": "SYS-1"},
                {"OPER": "B", "CODIGO GIO": "FINAL-2", "CODIGO SYSACAO": "SYS-2"},
            ],
        )
        resultado = procesar_flujo_comun(
            general, control, self.acumulado, fecha_procesamiento="21/09/2026",
            configuracion=self.configuracion, tabla_operarios=operarios,
        )
        self.assertEqual(len(resultado.data_filtrada), 20)
        self.assertEqual(
            [r.datos_normalizados["COO"] for r in resultado.data_filtrada[:18]],
            conservados,
        )
        self.assertEqual(
            [r.datos_normalizados["COO"] for r in resultado.data_filtrada[18:]],
            ["FINAL-1", "FINAL-2"],
        )
        self.assertEqual(resultado.registros[-1].motivo_final, "COO_VACIO")

    def test_equivalencia_sysacao_contradictoria_va_a_revision(self):
        general = tabla(
            "sansys.csv", ["OT", "OS", "NIS", "FECHA", "TIPO", "COO"],
            [{"OT": "1", "OS": "A", "NIS": "9", "FECHA": "21/09/2026", "TIPO": "C", "COO": "SYS"}],
        )
        control = tabla("gio.txt", ["OT", "OS", "ESTADO"], [{"OT": "1", "OS": "A", "ESTADO": "TRAB"}])
        operarios = tabla(
            "operarios.xlsx", ["OPER", "CODIGO GIO", "CODIGO SYSACAO"],
            [
                {"OPER": "A", "CODIGO GIO": "G1", "CODIGO SYSACAO": "SYS"},
                {"OPER": "B", "CODIGO GIO": "G2", "CODIGO SYSACAO": "SYS"},
            ],
        )
        resultado = procesar_flujo_comun(
            general, control, self.acumulado, fecha_procesamiento="21/09/2026",
            configuracion=self.configuracion, tabla_operarios=operarios,
        )
        self.assertEqual(resultado.registros[0].motivo_final, "EQUIVALENCIA_SYSACAO_CONTRADICTORIA")

    def test_clasifica_sin_perder_filas(self):
        general = tabla(
            "general.csv",
            ["nro_ot", "nnum_os", "nis_rad", "FECHA", "TIPO", "ACC", "ncod_cuadrilla"],
            [
                {"nro_ot": "OT-1", "nnum_os": "OS-1", "nis_rad": "1", "FECHA": "21/09/2026", "TIPO": "C", "ACC": "511", "ncod_cuadrilla": "S1"},
                {"nro_ot": "OT-YA", "nnum_os": "OS-YA", "nis_rad": "99", "FECHA": "21/09/2026", "TIPO": "C", "ACC": "511", "ncod_cuadrilla": "S1"},
                {"nro_ot": "OT-3", "nnum_os": "OS-3", "nis_rad": "3", "FECHA": "21/09/2026", "TIPO": "C", "ACC": "511", "ncod_cuadrilla": "S1"},
                {"nro_ot": "OT-4", "nnum_os": "OS-4", "nis_rad": "4", "FECHA": "21/09/2026", "TIPO": "V", "ACC": "521", "ncod_cuadrilla": "S1"},
                {"nro_ot": "OT-5", "nnum_os": "OS-5", "nis_rad": "5", "FECHA": "21/09/2026", "TIPO": "B", "ACC": "511", "ncod_cuadrilla": "S1"},
            ],
        )
        control = tabla(
            "gio.txt",
            ["nro_ot", "nnum_os", "estado", "nis_rad", "vtipo_os", "actividad", "desc_actividad"],
            [
                {"nro_ot": "OT-1", "nnum_os": "OS-1", "estado": "TRAB", "nis_rad": "1", "vtipo_os": "TO1", "actividad": "291", "desc_actividad": "Cierre"},
                {"nro_ot": "OT-OTRA", "nnum_os": "OS-3", "estado": "TRAB", "nis_rad": "3", "vtipo_os": "TO1", "actividad": "291", "desc_actividad": "Cierre"},
                {"nro_ot": "OT-4", "nnum_os": "OS-4", "estado": "RESUL", "nis_rad": "4", "vtipo_os": "TO2", "actividad": "291", "desc_actividad": "Visita"},
                {"nro_ot": "OT-5", "nnum_os": "OS-5", "estado": "TRAB", "nis_rad": "5", "vtipo_os": "TO3", "actividad": "291", "desc_actividad": "Otro"},
            ],
        )
        resultado = procesar_flujo_comun(
            general, control, self.acumulado,
            fecha_procesamiento="21/09/2026", configuracion=self.configuracion,
            tabla_operarios=self.operarios,
        )
        self.assertEqual(len(resultado.registros), 5)
        self.assertEqual([fila.ot for fila in resultado.data_filtrada], ["OT-1"])
        motivos = {fila.ot: fila.motivo_final for fila in resultado.registros if fila.motivo_final}
        self.assertEqual(motivos["OT-YA"], "YA_ACTUALIZADA_EN_ENTREGABLE")
        self.assertEqual(motivos["OT-3"], "INCONSISTENCIA_OT_OS")
        self.assertEqual(motivos["OT-4"], "ESTADO_NO_ACTUALIZABLE")
        self.assertEqual(motivos["OT-5"], "TIPO_PENDIENTE_DE_CONFIRMACION")

    def test_os_duplicada_va_a_revision_sin_multiplicar(self):
        general = tabla(
            "general.csv", ["OT", "OS", "NIS", "FECHA", "TIPO", "COO"],
            [{"OT": "1", "OS": "A", "NIS": "9", "FECHA": "21/09/2026", "TIPO": "C", "COO": "S1"}],
        )
        control = tabla(
            "gio.txt", ["OT", "OS", "ESTADO"],
            [
                {"OT": "1", "OS": "A", "ESTADO": "TRAB"},
                {"OT": "2", "OS": "A", "ESTADO": "TRAB"},
            ],
        )
        resultado = procesar_flujo_comun(
            general, control, self.acumulado,
            fecha_procesamiento="21/09/2026", configuracion=self.configuracion,
            tabla_operarios=self.operarios,
        )
        self.assertEqual(len(resultado.registros), 1)
        self.assertEqual(resultado.registros[0].motivo_final, "OS_DUPLICADA_EN_CONTROL")
        self.assertEqual(resultado.registros[0].categoria_final, CategoriaResultado.REVISION_MANUAL)

    def test_estado_no_catalogado_va_a_revision(self):
        general = tabla(
            "general.csv", ["OT", "OS", "NIS", "FECHA", "TIPO", "COO"],
            [{"OT": "1", "OS": "A", "NIS": "9", "FECHA": "21/09/2026", "TIPO": "C", "COO": "S1"}],
        )
        control = tabla(
            "gio.txt", ["OT", "OS", "ESTADO"],
            [{"OT": "1", "OS": "A", "ESTADO": "FAC"}],
        )
        resultado = procesar_flujo_comun(
            general, control, self.acumulado,
            fecha_procesamiento="21/09/2026", configuracion=self.configuracion,
            tabla_operarios=self.operarios,
        )
        self.assertEqual(resultado.registros[0].motivo_final, "ESTADO_NO_CATALOGADO")


if __name__ == "__main__":
    unittest.main()
