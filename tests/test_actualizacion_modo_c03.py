# -*- coding: utf-8 -*-

import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from PySide6.QtCore import QDate

from actualizacion_datos.modelos import ProcesoBloqueadoError
from actualizacion_datos.reglas_gio import MatrizReglasGio, MatrizTipologias, ReglaTipologia
from actualizacion_datos.servicio import RutasEntradasActualizacion, ServicioProcesamientoActualizaciones
from actualizacion_datos_pagina import PaginaProcesamientoActualizaciones
from test_actualizacion_integracion_flujo import crear_libro_reglas


def _crear_entradas(raiz: Path) -> RutasEntradasActualizacion:
    sansys = raiz / "sansys.csv"
    sansys.write_text(
        "OT;OS;NIS;FECHA;HI;HF;ACC;COO;OBS;LECT;TIPO\n"
        "OT-C;OS-C;N-C;21/09/2026;10:00;11:00;511;S1;Cierre;110;C\n"
        "OT-R;OS-R;N-C;21/09/2026;12:00;12:10;611;S1;Reapertura general;120;R\n",
        encoding="utf-8",
    )
    control = raiz / "gio.txt"
    control.write_text(
        "nro_ot\tnnum_os\tnis_rad\testado\tvtipo_os\tactividad\tdesc_actividad\n"
        "OT-C\tOS-C\tN-C\tTRAB\tTO-C\t291\tCierre\n"
        "OT-R\tOS-R\tN-C\tTRAB\tTO-R\t777\tReapertura sin texto C03\n",
        encoding="utf-8",
    )
    historico = raiz / "historico.txt"
    historico.write_text(
        "nis_rad\tOT\tOS\tFEJECUCION\tHI\tHF\tACCION\tCODIGO\tOBSERVACION\tLECT\n"
        "N-C\tOT-C\tOS-C\t20/09/2026\t10\t11\t511\tG1\tCierre anterior\t110\n",
        encoding="utf-8-sig",
    )
    reglas = raiz / "reglas.xlsx"
    crear_libro_reglas(reglas)
    configuracion = raiz / "configuracion.json"
    columnas = ["OT", "OS", "FECHA", "HI", "HF", "ACC", "CODIGO_GIO", "OBS", "LECT"]
    configuracion.write_text(json.dumps({
        "contratos": {
            "reaperturas_sistema": {"nombre": "REAPERTURAS_SISTEMA", "columnas": columnas, "confirmado": True},
            "entregable_reaperturas": {"nombre": "ENTREGABLE_REAPERTURAS", "columnas": ["NIS", *columnas], "confirmado": True},
        }
    }), encoding="utf-8")
    return RutasEntradasActualizacion(
        ruta_csv_sansys=sansys,
        ruta_control_gio=control,
        ruta_entregable_acumulado=None,
        ruta_libro_reglas=reglas,
        carpeta_salida=raiz / "salida",
        configuracion_json=configuracion,
        considerar_entregable_acumulado=False,
        modo_c03=True,
        ruta_entregable_historico=historico,
    )


class PruebasModoC03(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.aplicacion = QApplication.instance() or QApplication([])

    def test_modo_inicia_desactivado_y_confirmacion_controla_el_cambio(self):
        pagina = PaginaProcesamientoActualizaciones()
        self.assertFalse(pagina.modo_c03)
        pagina.mostrar_ajustes()
        with patch.object(pagina, "_confirmar_accion", return_value=False):
            pagina.interruptor_modo_c03.setChecked(True)
        self.assertFalse(pagina.modo_c03)
        with patch.object(pagina, "_confirmar_accion", return_value=True):
            pagina.interruptor_modo_c03.setChecked(True)
        self.assertTrue(pagina.modo_c03)
        self.assertFalse(pagina.indicador_modo_c03.isHidden())
        self.assertIn("NO APLICA", pagina.etiquetas_etapa["CIERRES"].text())
        pagina.close()

    def test_sin_historico_bloquea_antes_de_crear_salida(self):
        with TemporaryDirectory() as temporal:
            raiz = Path(temporal)
            rutas = _crear_entradas(raiz)
            rutas = RutasEntradasActualizacion(
                **{**rutas.__dict__, "ruta_entregable_historico": None}
            )
            servicio = ServicioProcesamientoActualizaciones()
            with self.assertRaisesRegex(ProcesoBloqueadoError, "entregable histórico"):
                servicio.procesar_flujo_comun(rutas, "21/09/2026")
            self.assertFalse(rutas.carpeta_salida.exists())

    def test_c03_reutiliza_data_filtrada_y_no_crea_cierres(self):
        with TemporaryDirectory() as temporal:
            raiz = Path(temporal)
            rutas = _crear_entradas(raiz)
            servicio = ServicioProcesamientoActualizaciones()
            resultado = servicio.procesar_flujo_comun(rutas, "21/09/2026")
            self.assertEqual(servicio.cantidad_lecturas_sansys, 1)
            self.assertEqual(len(resultado.flujo_comun.reaperturas_preparadas), 1)
            self.assertFalse(servicio.rutas_salida.cierres.exists())
            servicio.matriz_gio = MatrizReglasGio(
                (), frozenset(), ("MATRIZ_TIPOLOGIAS",),
                tipologias=MatrizTipologias((ReglaTipologia(
                    "C", "511", "511", "611", "CIERRE_VALIDO", "", True, 1
                ),)),
            )
            resultado = servicio.procesar_reaperturas()
            self.assertEqual(len(resultado.reaperturas.listas), 1)
            self.assertEqual(servicio.cantidad_lecturas_sansys, 1)
            self.assertFalse(servicio.rutas_salida.cierres.exists())
            self.assertTrue(Path(resultado.contexto.archivos_generados["reaperturas_sistema"]).is_file())
            self.assertTrue(Path(resultado.contexto.archivos_generados["entregable_reaperturas"]).is_file())
            self.assertFalse(any("cierres" in clave for clave in resultado.contexto.archivos_generados))
            conciliacion = resultado.contexto.metadatos_entradas["conciliacion_reaperturas"]
            self.assertEqual(conciliacion["entradas"], 1)
            self.assertEqual(conciliacion["perdidas"], 0)
            self.assertEqual(conciliacion["duplicados"], 0)

    def test_ejecucion_c03_desde_interfaz_usa_qthread(self):
        with TemporaryDirectory() as temporal:
            raiz = Path(temporal)
            rutas = _crear_entradas(raiz)
            matriz = MatrizReglasGio(
                (), frozenset(), ("MATRIZ_TIPOLOGIAS",),
                tipologias=MatrizTipologias((ReglaTipologia(
                    "C", "511", "511", "611", "CIERRE_VALIDO", "", True, 1
                ),)),
            )
            matriz_fisica = raiz / "matriz.xlsx"
            matriz_fisica.write_bytes(b"matriz de prueba")
            pagina = PaginaProcesamientoActualizaciones()
            pagina._aplicar_modo_c03(True)
            pagina.rutas.update({
                "csv_sansys": str(rutas.ruta_csv_sansys),
                "control_gio": str(rutas.ruta_control_gio),
                "libro_reglas": str(rutas.ruta_libro_reglas),
                "matriz_gio": str(matriz_fisica),
                "entregable_historico": str(rutas.ruta_entregable_historico),
                "carpeta_salida": str(rutas.carpeta_salida),
                "configuracion_json": str(rutas.configuracion_json),
            })
            pagina.matriz_gio_previsualizada = matriz
            pagina.fecha.setDate(QDate(2026, 9, 21))
            with patch.object(pagina, "_confirmar_accion", return_value=True), patch(
                "actualizacion_datos.servicio.leer_matriz_reglas_gio",
                return_value=matriz,
            ):
                pagina._iniciar_flujo_comun()
                for _ in range(300):
                    QTest.qWait(20)
                    if pagina.hilo is None and pagina._ultimo_resultado and pagina._ultimo_resultado.reaperturas:
                        break
            self.assertIsNone(pagina.hilo)
            self.assertIsNotNone(pagina._ultimo_resultado.reaperturas)
            self.assertEqual(len(pagina._ultimo_resultado.reaperturas.listas), 1)
            self.assertEqual(pagina.servicio.cantidad_lecturas_sansys, 1)
            self.assertFalse(pagina.servicio.rutas_salida.cierres.exists())
            pagina.close()


if __name__ == "__main__":
    unittest.main()
