# -*- coding: utf-8 -*-

from pathlib import Path
import unittest

from actualizacion_datos.configuracion import ConfiguracionProcesamiento
from actualizacion_datos.modelos import (
    EstadoFila, FormatoArchivo, ProcesoBloqueadoError, RegistroProcesamiento, TablaDatos,
)
from actualizacion_datos.reaperturas import procesar_reaperturas
from actualizacion_datos.reglas_gio import MatrizReglasGio, MatrizTipologias, ReglaTipologia


def registro_reapertura(accion="611", lectura="110"):
    return RegistroProcesamiento(
        id_fila="general:2", archivo_origen="general.csv", numero_fila_origen=2,
        datos_originales={}, estado=EstadoFila.DATA_FILTRADA,
        datos_normalizados={
            "OT": "OT-R", "OS": "OS-R", "NIS": "N1", "TIPO": "R",
            "ACC": accion, "LECT": lectura, "OBS": "Reapertura válida",
            "FECHA": "2026-09-21", "HI": "10:00", "HF": "10:00",
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
        self.matriz = MatrizReglasGio(
            (), frozenset(), ("MATRIZ_TIPOLOGIAS",), tipologias=MatrizTipologias((
                ReglaTipologia("C", "511", "511", "611", "CIERRE_VALIDO", "", True, 2),
            )),
        )

    def test_permanece_bloqueada_sin_entregable(self):
        with self.assertRaisesRegex(ProcesoBloqueadoError, "BLOQUEADAS"):
            procesar_reaperturas(
                [registro_reapertura()], None, configuracion=self.configuracion,
                matriz_gio=self.matriz,
            )

    def test_puede_continuar_sin_entregable_si_usuario_omite_cruce(self):
        fila = registro_reapertura()
        resultado = procesar_reaperturas(
            [fila], None, configuracion=self.configuracion,
            considerar_entregable_actualizado=False, matriz_gio=self.matriz,
        )
        self.assertEqual(len(resultado.listas), 1)
        self.assertEqual(
            resultado.listas[0].datos_normalizados["VALIDACION_ENTREGABLE_ACTUALIZADO"],
            "OMITIDA_POR_DECISION_USUARIO",
        )

    def test_reapertura_en_limite_14(self):
        tabla = entregable([
            {"nis_rad": "N1", "FEJECUCION": "20/09/2026", "ACCION": "511", "LECT": "100"},
        ])
        resultado = procesar_reaperturas(
            [registro_reapertura(lectura="114")], tabla,
            configuracion=self.configuracion, matriz_gio=self.matriz,
        )
        self.assertEqual(len(resultado.listas), 1)
        self.assertEqual(resultado.listas[0].datos_normalizados["DIFERENCIA"], "14")

    def test_accion_invalida_y_diferencia_mayor_van_a_revision(self):
        tabla = entregable([
            {"nis_rad": "N1", "FEJECUCION": "20/09/2026", "ACCION": "511", "LECT": "100"},
        ])
        invalida = registro_reapertura(accion="619", lectura="110")
        diferencia = registro_reapertura(accion="611", lectura="121")
        resultado = procesar_reaperturas(
            [invalida, diferencia], tabla,
            configuracion=self.configuracion, matriz_gio=self.matriz,
        )
        self.assertEqual(
            [fila.motivo_final for fila in resultado.revisiones],
            ["REAPERTURA_NO_EQUIVALENTE", "DIFERENCIA_MAYOR_14"],
        )

    def test_empate_de_fecha_conserva_el_orden_fisico_del_entregable(self):
        tabla = entregable([
            {"nis_rad": "N1", "FEJECUCION": "20/09/2026", "ACCION": "511", "LECT": "100"},
            {"nis_rad": "N1", "FEJECUCION": "20/09/2026", "ACCION": "511", "LECT": "101"},
        ])
        resultado = procesar_reaperturas(
            [registro_reapertura()], tabla,
            configuracion=self.configuracion, matriz_gio=self.matriz,
        )
        self.assertEqual(len(resultado.listas), 1)
        self.assertEqual(
            resultado.listas[0].datos_normalizados["LECTURA_CIERRE_ANTERIOR"],
            "100",
        )

    def test_entregable_se_ordena_por_fecha_antes_del_cruce(self):
        tabla = entregable([
            {"nis_rad": "N1", "FEJECUCION": "18/09/2026", "ACCION": "511", "LECT": "90"},
            {"nis_rad": "N1", "FEJECUCION": "20/09/2026", "ACCION": "511", "LECT": "100"},
            {"nis_rad": "N1", "FEJECUCION": "19/09/2026", "ACCION": "511", "LECT": "95"},
        ])
        resultado = procesar_reaperturas(
            [registro_reapertura()], tabla,
            configuracion=self.configuracion, matriz_gio=self.matriz,
        )
        self.assertEqual(len(resultado.listas), 1)
        self.assertEqual(
            resultado.listas[0].datos_normalizados["LECTURA_CIERRE_ANTERIOR"],
            "100",
        )

    def test_no_salta_antecedente_reciente_por_falta_de_tipologia(self):
        tabla = entregable([
            {"nis_rad": "N1", "FEJECUCION": "20/09/2026", "ACCION": "506", "LECT": "100"},
            {"nis_rad": "N1", "FEJECUCION": "19/09/2026", "ACCION": "511", "LECT": "99"},
        ])
        resultado = procesar_reaperturas(
            [registro_reapertura()], tabla,
            configuracion=self.configuracion, matriz_gio=self.matriz,
        )
        self.assertEqual(resultado.revisiones[0].motivo_final, "TIPO_ACC_NO_CONFIGURADO")
        self.assertEqual(
            resultado.revisiones[0].datos_normalizados["ACCION_CIERRE_ANTERIOR"],
            "506",
        )
        fila = resultado.revisiones[0].datos_normalizados
        self.assertEqual(fila["ACCION_REAPERTURA_ORIGINAL"], "611")
        self.assertEqual(fila["ACCION_REAPERTURA_VALIDADA"], "611")
        self.assertEqual(fila["CLAVE_MATRIZ_TIPOLOGIAS"], "|506")
        self.assertEqual(fila["VALOR_MATRIZ_TIPOLOGIAS"], "NO_ENCONTRADO")
        self.assertEqual(fila["DIFERENCIA"], "10")

    def test_accion_600_no_se_usa_como_cierre(self):
        tabla = entregable([
            {"nis_rad": "N1", "FEJECUCION": "20/09/2026", "ACCION": "611", "LECT": "100"},
        ])
        resultado = procesar_reaperturas(
            [registro_reapertura()], tabla,
            configuracion=self.configuracion, matriz_gio=self.matriz,
        )
        self.assertEqual(resultado.revisiones[0].motivo_final, "TIPO_ACC_NO_CONFIGURADO")

    def test_reglas_del_mismo_cierre_con_equivalencia_identica_no_son_ambiguas(self):
        tabla = entregable([
            {"nis_rad": "N1", "FEJECUCION": "20/09/2026", "ACCION": "511", "LECT": "100"},
        ])
        resultado = procesar_reaperturas(
            [registro_reapertura()], tabla,
            configuracion=self.configuracion, matriz_gio=self.matriz,
        )
        self.assertEqual(len(resultado.listas), 1)


if __name__ == "__main__":
    unittest.main()
