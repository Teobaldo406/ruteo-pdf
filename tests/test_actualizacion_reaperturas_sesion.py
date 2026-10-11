# -*- coding: utf-8 -*-

from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from actualizacion_datos.configuracion import ConfiguracionProcesamiento
from actualizacion_datos.exportadores import exportar_revision_manual_reaperturas
from actualizacion_datos.lectores import leer_xlsx
from actualizacion_datos.modelos import EstadoFila, FormatoArchivo, RegistroProcesamiento, TablaDatos
from actualizacion_datos.reaperturas import procesar_reaperturas
from actualizacion_datos.reglas_gio import (
    MatrizReglasGio, MatrizTipologias, ReglaGio, ReglaTipologia,
)
from actualizacion_datos.servicio import ServicioProcesamientoActualizaciones


def reapertura(
    identificador: str, accion: str, lectura: str, tipo: str = "R"
) -> RegistroProcesamiento:
    originales = {
        "OT": f"OT-{identificador}", "OS": f"OS-{identificador}",
        "NIS_RAD": identificador, "TIPO": tipo, "ACC": accion,
        "LECT": lectura, "HI": "9.09", "HF": "9.09", "OBS": "Reapertura",
    }
    return RegistroProcesamiento(
        id_fila=f"sansys:{identificador}", archivo_origen="sansys.csv",
        numero_fila_origen=2, datos_originales=originales.copy(),
        datos_normalizados={
            "OT": originales["OT"], "OS": originales["OS"], "NIS": identificador,
            "TIPO": tipo, "ACC": accion, "LECT": lectura, "OBS": "Reapertura",
            "FECHA": "2026-10-02", "HI": "09:09", "HF": "09:09",
        },
        estado=EstadoFila.DATA_FILTRADA,
    )


def entregable(*filas: dict[str, str]) -> TablaDatos:
    return TablaDatos(
        Path("entregable_actualizado.txt"),
        ["NIS_RAD", "FECHA", "ACCION", "LECT"], list(filas),
        FormatoArchivo("txt"),
    )


def matriz_equivalencias(*pares: tuple[str, str]) -> MatrizReglasGio:
    reglas = tuple(
        ReglaTipologia(
            "C", cierre, cierre, apertura, "CIERRE_VALIDO", "", True, indice + 1,
        )
        for indice, (cierre, apertura) in enumerate(pares, 1)
    )
    return MatrizReglasGio(
        (), frozenset(), ("REGLAS_GIO", "MATRIZ_TIPOLOGIAS"),
        tipologias=MatrizTipologias(reglas),
    )


class PruebasReaperturasSesion(unittest.TestCase):
    def setUp(self):
        self.configuracion = ConfiguracionProcesamiento.predeterminada()
        self.matriz = matriz_equivalencias(("511", "611"), ("506", "606"))

    def test_limites_cero_y_catorce_son_validos(self):
        filas = [reapertura("N0", "611", "100"), reapertura("N14", "606", "114")]
        tabla = entregable(
            {"NIS_RAD": "N0", "FECHA": "01/10/2026", "ACCION": "511", "LECT": "100"},
            {"NIS_RAD": "N14", "FECHA": "01/10/2026", "ACCION": "506", "LECT": "100"},
        )
        resultado = procesar_reaperturas(
            filas, tabla, configuracion=self.configuracion, matriz_gio=self.matriz
        )
        self.assertEqual([fila.nis for fila in resultado.listas], ["N0", "N14"])
        self.assertEqual([fila.datos_normalizados["DIFERENCIA"] for fila in resultado.listas], ["0", "14"])

    def test_negativa_mayor_catorce_y_rango_se_revisan_antes_de_equivalencia(self):
        filas = [
            reapertura("NEG", "999", "99"),
            reapertura("MAY", "999", "115"),
            reapertura("RNG", "999", "105"),
        ]
        tabla = entregable(
            {"NIS_RAD": "NEG", "FECHA": "01/10/2026", "ACCION": "511", "LECT": "100"},
            {"NIS_RAD": "MAY", "FECHA": "01/10/2026", "ACCION": "511", "LECT": "100"},
            {"NIS_RAD": "RNG", "FECHA": "01/10/2026", "ACCION": "700", "LECT": "100"},
        )
        resultado = procesar_reaperturas(
            filas, tabla, configuracion=self.configuracion, matriz_gio=self.matriz
        )
        self.assertEqual(
            [fila.motivo_final for fila in resultado.revisiones],
            ["REAPERTURA_NO_EQUIVALENTE", "REAPERTURA_NO_EQUIVALENTE", "TIPO_ACC_NO_CONFIGURADO"],
        )

    def test_equivalencia_no_configurada_permanece_en_revision(self):
        fila = reapertura("N1", "699", "105")
        resultado = procesar_reaperturas(
            [fila], entregable({
                "NIS_RAD": "N1", "FECHA": "01/10/2026", "ACCION": "511", "LECT": "100",
            }), configuracion=self.configuracion, matriz_gio=self.matriz,
        )
        self.assertEqual(resultado.revisiones[0].motivo_final, "REAPERTURA_NO_EQUIVALENTE")

    def test_excel_revision_solo_contiene_originales_y_cuatro_columnas(self):
        revision = reapertura("REV", "699", "105")
        lista = reapertura("OK", "611", "105")
        resultado = procesar_reaperturas(
            [revision, lista],
            entregable(
                {"NIS_RAD": "REV", "FECHA": "01/10/2026", "ACCION": "511", "LECT": "100"},
                {"NIS_RAD": "OK", "FECHA": "01/10/2026", "ACCION": "511", "LECT": "100"},
            ),
            configuracion=self.configuracion, matriz_gio=self.matriz,
        )
        with TemporaryDirectory(dir=Path.cwd() / ".tmp_tests") as temporal:
            ruta = exportar_revision_manual_reaperturas(
                resultado.revisiones, Path(temporal), resultado.entradas
            )
            tabla = leer_xlsx(ruta, hoja="REVISIONES")
        self.assertEqual(len(tabla.filas), 1)
        self.assertEqual(tabla.filas[0]["NIS_RAD"], "REV")
        self.assertEqual(
            tabla.encabezados[-4:],
            [
                "TEMPORAL_ACCION_CIERRE_ANTERIOR",
                "TEMPORAL_LECTURA_CIERRE_ANTERIOR",
                "TEMPORAL_DIFERENCIA",
                "TEMPORAL_MOTIVO_REVISION",
            ],
        )
        self.assertEqual(
            tabla.encabezados[:4], ["TIPO", "OBS TIPO", "NIS_RAD", "OT"]
        )
        self.assertEqual(tabla.encabezados.count("NIS_RAD"), 1)

    def test_subconjuntos_independientes_no_comparten_objetos(self):
        base = [reapertura("N1", "611", "105")]
        copia_a = deepcopy(base)
        copia_b = deepcopy(base)
        copia_a[0].datos_normalizados["ACC"] = "CAMBIO"
        self.assertEqual(base[0].datos_normalizados["ACC"], "611")
        self.assertEqual(copia_b[0].datos_normalizados["ACC"], "611")

    def test_lector_sansys_reutiliza_cache_si_el_archivo_no_cambio(self):
        with TemporaryDirectory(dir=Path.cwd() / ".tmp_tests") as temporal:
            ruta = Path(temporal) / "sansys.csv"
            ruta.write_text("OT;OS\n1;2\n", encoding="utf-8")
            servicio = ServicioProcesamientoActualizaciones()
            primera = servicio._leer_sansys(ruta)
            segunda = servicio._leer_sansys(ruta)
        self.assertIs(primera, segunda)
        self.assertEqual(servicio.cantidad_lecturas_sansys, 1)

    @staticmethod
    def _matriz_cd_506_rd_606() -> MatrizReglasGio:
        return MatrizReglasGio(
            (), frozenset(), ("MATRIZ_TIPOLOGIAS",),
            tipologias=MatrizTipologias((
                ReglaTipologia(
                    "CD", "506", "506", "606", "CIERRE_VALIDO",
                    "Reapertura 606 con retiro de dispositivo intrusivo",
                    True, 2,
                ),
                ReglaTipologia(
                    "RD", "606", "", "", "REAPERTURA_VALIDA",
                    "Requiere cierre anterior CD con acción 506",
                    True, 32,
                ),
            )),
        )

    def _procesar_cd_506_rd_606(
        self,
        *,
        accion_reapertura: str = "606",
        tipo_cierre: str = "CD",
        diferencia: int = 0,
        incluir_cierre: bool = True,
    ):
        fila = reapertura(
            "CD506-RD606", accion_reapertura, str(100 + diferencia), tipo="RD"
        )
        filas_cierre = []
        if incluir_cierre:
            filas_cierre.append({
                "NIS_RAD": "CD506-RD606", "FECHA": "01/10/2026",
                "TIPO": tipo_cierre, "ACCION": "506", "LECT": "100",
            })
        tabla = TablaDatos(
            Path("actualizado.txt"),
            ["NIS_RAD", "FECHA", "TIPO", "ACCION", "LECT"],
            filas_cierre, FormatoArchivo("txt"),
        )
        return procesar_reaperturas(
            [fila], tabla, configuracion=self.configuracion,
            matriz_gio=self._matriz_cd_506_rd_606(),
        )

    def test_cd_506_seguido_de_rd_606_con_diferencia_valida_se_aprueba(self):
        resultado = self._procesar_cd_506_rd_606()
        self.assertEqual(len(resultado.listas), 1)
        datos = resultado.listas[0].datos_normalizados
        self.assertEqual(datos["TIPO_CIERRE_ANTERIOR"], "CD")
        self.assertEqual(datos["ACCION_CIERRE_ANTERIOR"], "506")
        self.assertEqual(datos["ACCION_REAPERTURA_VALIDADA"], "606")
        self.assertEqual(datos["CLAVE_MATRIZ_TIPOLOGIAS"], "CD|506")
        self.assertEqual(datos["DIFERENCIA"], "0")

    def test_cd_506_seguido_de_accion_distinta_de_606_va_a_revision(self):
        resultado = self._procesar_cd_506_rd_606(accion_reapertura="611")
        self.assertEqual(
            resultado.revisiones[0].motivo_final, "REAPERTURA_NO_EQUIVALENTE"
        )

    def test_accion_506_con_tipo_anterior_distinto_de_cd_va_a_revision(self):
        resultado = self._procesar_cd_506_rd_606(tipo_cierre="V")
        self.assertEqual(
            resultado.revisiones[0].motivo_final, "TIPO_ACC_NO_CONFIGURADO"
        )

    def test_rd_606_sin_cierre_anterior_va_a_revision(self):
        resultado = self._procesar_cd_506_rd_606(incluir_cierre=False)
        self.assertEqual(
            resultado.revisiones[0].motivo_final, "CIERRE_ANTERIOR_NO_ENCONTRADO"
        )

    def test_rd_606_con_diferencia_fuera_del_rango_va_a_revision(self):
        resultado = self._procesar_cd_506_rd_606(diferencia=15)
        self.assertEqual(
            resultado.revisiones[0].motivo_final, "DIFERENCIA_MAYOR_14"
        )

    def test_matriz_configura_ambas_tipologias_sin_reglas_fijas(self):
        matriz = self._matriz_cd_506_rd_606().tipologias
        self.assertEqual(len(matriz.buscar("CD", "506")), 1)
        self.assertEqual(
            matriz.buscar("CD", "506")[0].reapertura_esperada, "606"
        )
        self.assertEqual(len(matriz.buscar("RD", "606")), 1)

    def _procesar_tipologia(self, tipo, accion_cierre, accion_reapertura, activa=True, diferencia=5):
        matriz = MatrizReglasGio(
            (), frozenset(), ("MATRIZ_TIPOLOGIAS",),
            tipologias=MatrizTipologias((ReglaTipologia(
                tipo, accion_cierre, "511", "611", "REVISION_CONFIRMA_CIERRE",
                "", activa, 2,
            ),)),
        )
        fila = reapertura("TIPO", accion_reapertura, str(100 + diferencia))
        tabla = TablaDatos(
            Path("actualizado.txt"),
            ["NIS_RAD", "FECHA", "TIPO", "ACCION", "LECT"],
            [{
                "NIS_RAD": "TIPO", "FECHA": "01/10/2026", "TIPO": tipo,
                "ACCION": accion_cierre, "LECT": "100",
            }], FormatoArchivo("txt"),
        )
        return procesar_reaperturas(
            [fila], tabla, configuracion=self.configuracion, matriz_gio=matriz,
        )

    def test_v_508_se_convierte_en_reapertura_611(self):
        resultado = self._procesar_tipologia("V", "508", "611")
        self.assertEqual(len(resultado.listas), 1)
        self.assertEqual(resultado.listas[0].datos_normalizados["CIERRE_EFECTIVO"], "511")

    def test_v_521_se_convierte_en_reapertura_611(self):
        resultado = self._procesar_tipologia("V", "521", "611")
        self.assertEqual(len(resultado.listas), 1)

    def test_tipo_incorrecto_con_accion_valida_va_a_revision(self):
        # La fuente dice V pero la única regla configurada es C+511.
        matriz = MatrizReglasGio(
            (), frozenset(), ("MATRIZ_TIPOLOGIAS",),
            tipologias=MatrizTipologias((
                ReglaTipologia("C", "511", "511", "611", "CIERRE_VALIDO", "", True, 2),
            )),
        )
        fila = reapertura("TIPO-MAL", "611", "105")
        tabla = TablaDatos(
            Path("actualizado.txt"), ["NIS_RAD", "FECHA", "TIPO", "ACCION", "LECT"],
            [{"NIS_RAD": "TIPO-MAL", "FECHA": "01/10/2026", "TIPO": "V", "ACCION": "511", "LECT": "100"}],
            FormatoArchivo("txt"),
        )
        revisado = procesar_reaperturas([fila], tabla, configuracion=self.configuracion, matriz_gio=matriz)
        self.assertEqual(revisado.revisiones[0].motivo_final, "TIPO_ACC_NO_CONFIGURADO")

    def test_regla_inactiva_se_informa(self):
        resultado = self._procesar_tipologia("V", "508", "611", activa=False)
        self.assertEqual(resultado.revisiones[0].motivo_final, "REGLA_TIPOLOGICA_INACTIVA")

    def test_diferencias_negativa_y_quince(self):
        negativa = self._procesar_tipologia("V", "508", "611", diferencia=-1)
        quince = self._procesar_tipologia("V", "508", "611", diferencia=15)
        self.assertEqual(negativa.revisiones[0].motivo_final, "DIFERENCIA_NEGATIVA")
        self.assertEqual(quince.revisiones[0].motivo_final, "DIFERENCIA_MAYOR_14")

    def test_reaperturas_no_vuelven_a_cruzar_actividad(self):
        with patch(
            "actualizacion_datos.flujo_comun._indice_actividades",
            side_effect=AssertionError("No debe ejecutarse"),
        ):
            resultado = self._procesar_tipologia("V", "508", "611")
        self.assertEqual(len(resultado.listas), 1)

    def _procesar_imposibilidad(self, accion_cierre, tipo_cierre, regla_cierre=None):
        reglas_tipologicas = [
            ReglaTipologia(
                "R|RD", "633", "", "", "REAPERTURA_IMPOSIBILIDAD_VALIDA",
                "No exige equivalencia ni diferencia", True, 40,
                clasificacion="IMPOSIBILIDAD_REAPERTURA",
                requiere_cierre_anterior=True,
                requiere_cierre_efectivo=True,
                validar_equivalencia=False,
                validar_diferencia=False,
            )
        ]
        if regla_cierre:
            reglas_tipologicas.insert(0, regla_cierre)
        regla_gio_506 = ReglaGio(
            id_regla="GIO-CD-506", prioridad=1, regla="CD",
            coincidencia_obs="CUALQUIERA", patron_obs="",
            condicion_acc="LISTA", acc_lista=("506",),
            acc_min=None, acc_max=None, resultado="VALIDO_EFECTIVO",
            categoria="CIERRE", motivo="CIERRE_EFECTIVO",
            destino="CIERRES_LISTOS", activa=True,
        )
        matriz = MatrizReglasGio(
            (regla_gio_506,), frozenset(), ("MATRIZ_TIPOLOGIAS",),
            tipologias=MatrizTipologias(tuple(reglas_tipologicas)),
        )
        fila = reapertura("IMP", "633", "999")
        tabla = TablaDatos(
            Path("actualizado.txt"),
            ["NIS_RAD", "FECHA", "TIPO", "ACCION", "LECT"],
            [{
                "NIS_RAD": "IMP", "FECHA": "01/10/2026", "TIPO": tipo_cierre,
                "ACCION": accion_cierre, "LECT": "1",
            }], FormatoArchivo("txt"),
        )
        return procesar_reaperturas(
            [fila], tabla, configuracion=self.configuracion, matriz_gio=matriz,
        )

    def test_imposibilidad_633_con_revision_521_aprobada(self):
        regla = ReglaTipologia(
            "V", "521", "511", "611", "REVISION_CONFIRMA_CIERRE", "", True, 2,
        )
        resultado = self._procesar_imposibilidad("521", "V", regla)
        self.assertEqual(len(resultado.listas), 1)

    def test_imposibilidad_633_con_cierre_511_aprobada(self):
        regla = ReglaTipologia(
            "C", "511", "511", "611", "CIERRE_VALIDO", "", True, 2,
        )
        resultado = self._procesar_imposibilidad("511", "C", regla)
        self.assertEqual(len(resultado.listas), 1)

    def test_imposibilidad_633_con_cierre_506_aprobada_por_matriz_gio(self):
        resultado = self._procesar_imposibilidad("506", "CD")
        self.assertEqual(len(resultado.listas), 1)

    def test_imposibilidad_633_con_cierre_no_efectivo_va_a_revision(self):
        regla = ReglaTipologia(
            "V", "533", "", "", "NO_EFECTIVO", "", True, 2,
        )
        resultado = self._procesar_imposibilidad("533", "V", regla)
        self.assertEqual(
            resultado.revisiones[0].motivo_final, "CIERRE_EFECTIVO_NO_DEFINIDO"
        )

    def test_imposibilidad_633_sin_cierre_anterior_va_a_revision(self):
        regla_imposibilidad = ReglaTipologia(
            "R|RD", "633", "", "", "REAPERTURA_IMPOSIBILIDAD_VALIDA",
            "", True, 40, clasificacion="IMPOSIBILIDAD_REAPERTURA",
            requiere_cierre_anterior=True, requiere_cierre_efectivo=True,
            validar_equivalencia=False, validar_diferencia=False,
        )
        resultado = procesar_reaperturas(
            [reapertura("SIN-CIERRE", "633", "10")], entregable(),
            configuracion=self.configuracion,
            matriz_gio=MatrizReglasGio(
                (), frozenset(), ("MATRIZ_TIPOLOGIAS",),
                tipologias=MatrizTipologias((regla_imposibilidad,)),
            ),
        )
        self.assertEqual(
            resultado.revisiones[0].motivo_final, "CIERRE_ANTERIOR_NO_ENCONTRADO"
        )

    def test_506_606_y_511_611_conservan_flujo_normal(self):
        matriz_506 = MatrizReglasGio(
            (), frozenset(), ("MATRIZ_TIPOLOGIAS",),
            tipologias=MatrizTipologias((ReglaTipologia(
                "CD", "506", "506", "606", "CIERRE_VALIDO", "", True, 2,
            ),)),
        )
        fila_506 = reapertura("NORMAL-506", "606", "105")
        tabla_506 = TablaDatos(
            Path("actualizado.txt"),
            ["NIS_RAD", "FECHA", "TIPO", "ACCION", "LECT"],
            [{
                "NIS_RAD": "NORMAL-506", "FECHA": "01/10/2026",
                "TIPO": "CD", "ACCION": "506", "LECT": "100",
            }], FormatoArchivo("txt"),
        )
        caso_506 = procesar_reaperturas(
            [fila_506], tabla_506, configuracion=self.configuracion,
            matriz_gio=matriz_506,
        )
        caso_511 = self._procesar_tipologia("C", "511", "611")
        self.assertEqual(len(caso_506.listas), 1)
        self.assertEqual(len(caso_511.listas), 1)

    def test_observacion_reapertura_160_valida_y_161_a_revision(self):
        matriz = MatrizReglasGio(
            (), frozenset(), ("MATRIZ_TIPOLOGIAS",),
            tipologias=MatrizTipologias((ReglaTipologia(
                "C", "511", "511", "611", "CIERRE_VALIDO", "", True, 2,
            ),)),
        )
        tabla = TablaDatos(
            Path("actualizado.txt"),
            ["NIS_RAD", "FECHA", "TIPO", "ACCION", "LECT"],
            [
                {"NIS_RAD": "OBS-160", "FECHA": "01/10/2026", "TIPO": "C", "ACCION": "511", "LECT": "100"},
                {"NIS_RAD": "OBS-161", "FECHA": "01/10/2026", "TIPO": "C", "ACCION": "511", "LECT": "100"},
            ], FormatoArchivo("txt"),
        )
        fila_160 = reapertura("OBS-160", "611", "105")
        fila_161 = reapertura("OBS-161", "611", "105")
        fila_160.datos_normalizados["OBS"] = "A" * 160
        fila_161.datos_normalizados["OBS"] = "A" * 161
        resultado = procesar_reaperturas(
            [fila_160, fila_161], tabla,
            configuracion=self.configuracion, matriz_gio=matriz,
        )
        self.assertEqual([fila.nis for fila in resultado.listas], ["OBS-160"])
        self.assertEqual(
            resultado.revisiones[0].motivo_final, "OBS_EXCEDE_160_CARACTERES"
        )


if __name__ == "__main__":
    unittest.main()
