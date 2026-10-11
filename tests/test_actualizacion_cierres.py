# -*- coding: utf-8 -*-

from pathlib import Path
import unittest

from actualizacion_datos.cierres import procesar_cierres
from actualizacion_datos.configuracion import ConfiguracionProcesamiento, ReglaAccion
from actualizacion_datos.modelos import EstadoFila, FormatoArchivo, RegistroProcesamiento, TablaDatos


def registro_cierre(diferencia, tipo="C", hi="13:00", hf="13:30", obs=None):
    lectura_toma = 100
    observacion = obs if obs is not None else f"HI: {hi} HF: {hf} OBS: texto posterior"
    return RegistroProcesamiento(
        id_fila=f"fila-{tipo}-{diferencia}", archivo_origen="general.csv", numero_fila_origen=2,
        datos_originales={"OBS": observacion},
        datos_normalizados={
            "OT": "OT1", "OS": "OS1", "NIS": "N1", "TIPO": tipo,
            "ACC": "511", "HI": hi, "HF": hf, "OBS": observacion,
            "LECT": str(lectura_toma + diferencia),
        },
        estado=EstadoFila.DATA_FILTRADA,
    )


def tabla_lecturas(valores=("100",)):
    return TablaDatos(
        ruta=Path("lecturas.xlsx"), encabezados=["NIS_RAD", "LECT"],
        filas=[{"NIS_RAD": "N1", "LECT": valor} for valor in valores],
        formato=FormatoArchivo("xlsx", columnas=("NIS_RAD", "LECT")),
    )


class PruebasCierres(unittest.TestCase):
    def setUp(self):
        self.configuracion = ConfiguracionProcesamiento.predeterminada()
        self.configuracion.agregar_reglas_accion([
            ReglaAccion("ACC-C-511", "C", "511", aplica_lectura=True, acciones_reapertura=("611",)),
            ReglaAccion("ACC-V-511", "V", "511", aplica_lectura=True, acciones_reapertura=("611",)),
        ])

    def test_limites_de_diferencia(self):
        entradas = [registro_cierre(valor) for valor in (-1, 0, 280, 300, 301)]
        resultado = procesar_cierres(
            entradas, configuracion=self.configuracion, tabla_lecturas=tabla_lecturas()
        )
        diferencias_listas = [fila.datos_normalizados["DIFERENCIA"] for fila in resultado.listas]
        self.assertEqual(diferencias_listas, ["0", "280", "300"])
        self.assertEqual(
            [fila.motivo_final for fila in resultado.revisiones],
            ["LECTURA_NEGATIVA", "DIFERENCIA_MAYOR_300"],
        )

    def test_lectura_toma_no_disponible_por_niple_continua_sin_diferencia(self):
        cierre = registro_cierre(25, obs="HI: 10:00 HF: 11:00 OBS: evidencia libre")
        resultado = procesar_cierres(
            [cierre], configuracion=self.configuracion,
            tabla_lecturas=tabla_lecturas(("#N/D",)),
        )
        self.assertEqual(resultado.listas, [cierre])
        self.assertEqual(resultado.revisiones, [])
        self.assertEqual(cierre.datos_normalizados["LECT"], "125")
        self.assertEqual(cierre.datos_normalizados["LECTURA_TOMA"], "#N/D")
        self.assertEqual(cierre.datos_normalizados["DIFERENCIA"], "")
        self.assertEqual(cierre.datos_normalizados["VALIDACION_LECTURA"], "NO_APLICA_POR_NIPLE")
        self.assertEqual(
            cierre.datos_normalizados["MOTIVO_LECTURA"],
            "SIN_LECTURA_ANTERIOR_POR_CONDICION_NIPLE",
        )
        self.assertEqual(cierre.datos_normalizados["RESULTADO_LECTURA"], "CONTINUAR")

    def test_nis_sin_coincidencia_equivale_al_nd_del_cruce_manual(self):
        cierre = registro_cierre(25)
        tabla_vacia = TablaDatos(
            ruta=Path("lecturas.xlsx"), encabezados=["NIS_RAD", "LECT"], filas=[],
            formato=FormatoArchivo("xlsx", columnas=("NIS_RAD", "LECT")),
        )
        resultado = procesar_cierres(
            [cierre], configuracion=self.configuracion, tabla_lecturas=tabla_vacia,
        )
        self.assertEqual(resultado.listas, [cierre])
        self.assertEqual(cierre.datos_normalizados["LECTURA_TOMA"], "#N/D")
        self.assertEqual(cierre.datos_normalizados["DIFERENCIA"], "")

    def test_corrige_solo_tipo_c_y_preserva_texto_posterior(self):
        cierre = registro_cierre(10, tipo="C", hi="14:00", hf="15:30")
        resultado = procesar_cierres(
            [cierre], configuracion=self.configuracion, tabla_lecturas=tabla_lecturas()
        )
        self.assertEqual(len(resultado.listas), 1)
        self.assertEqual(cierre.datos_normalizados["HI"], "12")
        self.assertEqual(cierre.datos_normalizados["HF"], "12")
        self.assertEqual(cierre.datos_normalizados["HI_FINAL"], "12")
        self.assertEqual(cierre.datos_normalizados["HF_FINAL"], "12")
        self.assertEqual(
            cierre.datos_normalizados["MOTIVO_CORRECCION_HORA"],
            "TIPO_C_HORA_IGUAL_O_SUPERIOR_14_00",
        )
        self.assertEqual(cierre.datos_normalizados["OBS"], "HI: 12:00 HF: 12:00 OBS: texto posterior")

        visita = registro_cierre(10, tipo="V", hi="14:00", hf="15:30")
        procesar_cierres([visita], configuracion=self.configuracion, tabla_lecturas=tabla_lecturas())
        self.assertEqual(visita.datos_normalizados["HI"], "14:00")
        self.assertEqual(visita.datos_normalizados["HI_FINAL"], "14:00")
        self.assertEqual(
            visita.datos_normalizados["MOTIVO_CORRECCION_HORA"],
            "NO_APLICA_TIPO_DISTINTO_C",
        )

        antes_limite = registro_cierre(10, tipo="C", hi="13,46", hf="13,46")
        antes_limite.datos_normalizados["HI_ORIGINAL"] = "13,46"
        antes_limite.datos_normalizados["HF_ORIGINAL"] = "13,46"
        procesar_cierres(
            [antes_limite], configuracion=self.configuracion,
            tabla_lecturas=tabla_lecturas(),
        )
        self.assertEqual(antes_limite.datos_normalizados["HI_FINAL"], "13,46")
        self.assertEqual(antes_limite.datos_normalizados["HF_FINAL"], "13,46")
        self.assertEqual(
            antes_limite.datos_normalizados["MOTIVO_CORRECCION_HORA"],
            "NO_REQUIERE_CORRECCION_ANTES_DE_14_00",
        )

    def test_sin_matriz_no_inventa_accion(self):
        resultado = procesar_cierres(
            [registro_cierre(0)], configuracion=ConfiguracionProcesamiento.predeterminada(),
            tabla_lecturas=tabla_lecturas(),
        )
        self.assertFalse(resultado.listas)
        self.assertEqual(resultado.revisiones[0].motivo_final, "ACCION_SIN_REGLA_CONFIGURADA")
        self.assertTrue(resultado.bloqueos)

    def test_lectura_duplicada_y_obs_excedida_van_a_revision(self):
        duplicada = registro_cierre(0)
        resultado = procesar_cierres(
            [duplicada], configuracion=self.configuracion, tabla_lecturas=tabla_lecturas(("100", "101"))
        )
        self.assertEqual(resultado.revisiones[0].motivo_final, "LECTURA_TOMA_DUPLICADA")

        larga = registro_cierre(0, obs="HI: 10:00 HF: 11:00 OBS: " + "x" * 151)
        resultado = procesar_cierres(
            [larga], configuracion=self.configuracion, tabla_lecturas=tabla_lecturas()
        )
        self.assertEqual(resultado.revisiones[0].motivo_final, "OBS_EXCEDE_150_CARACTERES")


if __name__ == "__main__":
    unittest.main()
