# -*- coding: utf-8 -*-

from pathlib import Path
import unittest

from actualizacion_datos.configuracion import ConfiguracionProcesamiento, ReglaAccion
from actualizacion_datos.modelos import (
    EstadoFila, FormatoArchivo, ProcesoBloqueadoError, RegistroProcesamiento, TablaDatos,
)
from actualizacion_datos.reaperturas import procesar_reaperturas


def registro_reapertura(accion="611", lectura="120"):
    return RegistroProcesamiento(
        id_fila="general:2", archivo_origen="general.csv", numero_fila_origen=2,
        datos_originales={}, estado=EstadoFila.DATA_FILTRADA,
        datos_normalizados={
            "OT": "OT-R", "OS": "OS-R", "NIS": "N1", "TIPO": "R",
            "ACC": accion, "LECT": lectura, "OBS": "Reapertura válida",
        },
    )


def entregable(filas):
    return TablaDatos(
        ruta=Path("actualizado.txt"),
        encabezados=["nis_rad", "FEJECUCION", "ACCION", "LECT"],
        filas=filas,
        formato=FormatoArchivo("txt", columnas=("nis_rad", "FEJECUCION", "ACCION", "LECT")),
    )


class PruebasReaperturas(unittest.TestCase):
    def setUp(self):
        self.configuracion = ConfiguracionProcesamiento.predeterminada()
        self.configuracion.agregar_reglas_accion([
            ReglaAccion("CIERRE-511", "C", "511", acciones_reapertura=("611",)),
        ])

    def test_permanece_bloqueada_sin_entregable(self):
        with self.assertRaisesRegex(ProcesoBloqueadoError, "BLOQUEADAS"):
            procesar_reaperturas([registro_reapertura()], None, configuracion=self.configuracion)

    def test_reapertura_lista_en_limite_20(self):
        tabla = entregable([
            {"nis_rad": "N1", "FEJECUCION": "20/09/2026", "ACCION": "511", "LECT": "100"},
        ])
        resultado = procesar_reaperturas(
            [registro_reapertura(lectura="120")], tabla, configuracion=self.configuracion
        )
        self.assertEqual(len(resultado.listas), 1)
        self.assertEqual(resultado.listas[0].datos_normalizados["DIFERENCIA"], "20")

    def test_accion_invalida_y_diferencia_mayor_van_a_revision(self):
        tabla = entregable([
            {"nis_rad": "N1", "FEJECUCION": "20/09/2026", "ACCION": "511", "LECT": "100"},
        ])
        invalida = registro_reapertura(accion="619", lectura="110")
        diferencia = registro_reapertura(accion="611", lectura="121")
        resultado = procesar_reaperturas(
            [invalida, diferencia], tabla, configuracion=self.configuracion
        )
        self.assertEqual([fila.motivo_final for fila in resultado.revisiones], ["ACCION_INVALIDA", "REVISAR_LECTURA"])

    def test_empate_de_fecha_no_se_resuelve_por_inferencia(self):
        tabla = entregable([
            {"nis_rad": "N1", "FEJECUCION": "20/09/2026", "ACCION": "511", "LECT": "100"},
            {"nis_rad": "N1", "FEJECUCION": "20/09/2026", "ACCION": "511", "LECT": "101"},
        ])
        resultado = procesar_reaperturas(
            [registro_reapertura()], tabla, configuracion=self.configuracion
        )
        self.assertEqual(resultado.revisiones[0].motivo_final, "CIERRE_MAS_RECIENTE_AMBIGUO")

    def test_accion_600_no_se_usa_como_cierre(self):
        tabla = entregable([
            {"nis_rad": "N1", "FEJECUCION": "20/09/2026", "ACCION": "611", "LECT": "100"},
        ])
        resultado = procesar_reaperturas(
            [registro_reapertura()], tabla, configuracion=self.configuracion
        )
        self.assertEqual(resultado.revisiones[0].motivo_final, "CIERRE_EFECTIVO_NO_CONFIGURADO")

    def test_reglas_del_mismo_cierre_con_equivalencia_identica_no_son_ambiguas(self):
        self.configuracion.agregar_reglas_accion([
            ReglaAccion("CIERRE-511-V", "V", "511", acciones_reapertura=("611",)),
        ])
        tabla = entregable([
            {"nis_rad": "N1", "FEJECUCION": "20/09/2026", "ACCION": "511", "LECT": "100"},
        ])
        resultado = procesar_reaperturas(
            [registro_reapertura()], tabla, configuracion=self.configuracion
        )
        self.assertEqual(len(resultado.listas), 1)


if __name__ == "__main__":
    unittest.main()
