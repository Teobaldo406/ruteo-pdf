# -*- coding: utf-8 -*-

import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox, QScrollArea

from actualizacion_datos.modelos import (
    ContextoEjecucion,
    EstadoEtapa,
    RegistroProcesamiento,
    ResultadoFlujoComun,
    ResultadoProceso,
    ResultadoRama,
    ResumenEtapa,
)
from actualizacion_datos.reglas_gio import MatrizReglasGio
from actualizacion_datos.trabajadores import TrabajadorActualizacion
from actualizacion_datos_pagina import PaginaProcesamientoActualizaciones


class PruebasInterfazActualizacion(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.aplicacion = QApplication.instance() or QApplication([])

    def test_pagina_inicia_con_dependencias_bloqueadas(self):
        pagina = PaginaProcesamientoActualizaciones()
        self.assertFalse(pagina.boton_cierres.isEnabled())
        self.assertFalse(pagina.boton_entregable.isEnabled())
        self.assertFalse(pagina.boton_reaperturas.isEnabled())
        self.assertIn("BLOQUEADO", pagina.etiquetas_etapa["REAPERTURAS"].text())
        self.assertTrue(pagina.opcion_entregable_acumulado.isChecked())
        self.assertTrue(pagina.opcion_entregable_actualizado.isChecked())
        pagina.close()

    def test_entregable_acumulado_desactivado_no_es_obligatorio(self):
        pagina = PaginaProcesamientoActualizaciones()
        self.assertIn("desmarque para desactivar", pagina.opcion_entregable_acumulado.text())
        pagina.rutas["entregable_acumulado"] = "anterior.csv"
        with patch.object(pagina, "_confirmar_accion", return_value=True):
            pagina.opcion_entregable_acumulado.setChecked(False)
        self.assertFalse(pagina.botones_selector["entregable_acumulado"].isEnabled())
        self.assertEqual(
            pagina.etiquetas_ruta["entregable_acumulado"].text(), "NO UTILIZADO"
        )
        self.assertEqual(
            pagina.estado_opcion_entregable_acumulado.text(), "DESACTIVADO"
        )
        self.assertNotIn("entregable_acumulado", pagina.rutas)
        self.assertTrue(pagina._confirmacion_sin_entregable)
        pagina.rutas.update({
            "csv_sansys": "sansys.csv",
            "control_gio": "gio.csv",
            "libro_reglas": "reglas.xlsx",
            "matriz_gio": "matriz.xlsx",
            "carpeta_salida": "salida",
        })
        pagina.matriz_gio_previsualizada = MatrizReglasGio(
            reglas=(), combinaciones=frozenset(), hojas=(), ruta="matriz.xlsx"
        )
        rutas = pagina._rutas_entradas()
        self.assertIsNone(rutas.ruta_entregable_acumulado)
        self.assertFalse(rutas.considerar_entregable_acumulado)
        pagina.close()

    def test_cancelar_desactivacion_conserva_opcion_ruta_y_selector(self):
        pagina = PaginaProcesamientoActualizaciones()
        pagina.rutas["entregable_acumulado"] = "acumulado.csv"
        with patch.object(pagina, "_confirmar_accion", return_value=False):
            pagina.opcion_entregable_acumulado.setChecked(False)
        self.assertTrue(pagina.opcion_entregable_acumulado.isChecked())
        self.assertTrue(pagina.botones_selector["entregable_acumulado"].isEnabled())
        self.assertEqual(pagina.rutas["entregable_acumulado"], "acumulado.csv")
        self.assertFalse(pagina._confirmacion_sin_entregable)
        pagina.close()

    def test_escape_equivale_a_cancelar_y_boton_seguro_es_predeterminado(self):
        pagina = PaginaProcesamientoActualizaciones()
        observado = {}

        def cancelar_con_escape():
            dialogo = QApplication.activeModalWidget()
            observado["predeterminado"] = dialogo.defaultButton().text()
            QTest.keyClick(dialogo, Qt.Key.Key_Escape)

        QTimer.singleShot(0, cancelar_con_escape)
        confirmado = pagina._confirmar_accion(
            "Prueba", "Consecuencia", "Sí, continuar", "No, regresar"
        )
        self.assertFalse(confirmado)
        self.assertEqual(observado["predeterminado"], "No, regresar")
        pagina.close()

    def test_reemplazar_archivo_pide_confirmacion_y_conserva_el_actual_si_cancela(self):
        pagina = PaginaProcesamientoActualizaciones()
        pagina.rutas["csv_sansys"] = "actual.csv"
        with (
            patch(
                "actualizacion_datos_pagina.QFileDialog.getOpenFileName",
                return_value=("nuevo.csv", ""),
            ),
            patch.object(pagina, "_confirmar_accion", return_value=False) as confirmar,
            patch.object(pagina, "_iniciar_operacion") as iniciar,
        ):
            pagina._seleccionar_archivo("csv_sansys")
        confirmar.assert_called_once()
        iniciar.assert_not_called()
        self.assertEqual(pagina.rutas["csv_sansys"], "actual.csv")
        pagina.close()

    def test_cancelar_confirmacion_final_no_inicia_qthread_ni_crea_salida(self):
        pagina = PaginaProcesamientoActualizaciones()
        with TemporaryDirectory() as temporal:
            salida = Path(temporal) / "salida"
            pagina.rutas["carpeta_salida"] = str(salida)
            with (
                patch.object(pagina, "_confirmar_entregable_omitido", return_value=False),
                patch.object(pagina, "_iniciar_operacion") as iniciar,
                patch.object(pagina, "_confirmar_accion", return_value=True),
                patch.object(pagina, "_rutas_entradas", return_value=object()),
            ):
                pagina._cambio_opcion_interno = True
                pagina.opcion_entregable_acumulado.setChecked(False)
                pagina._cambio_opcion_interno = False
                pagina._iniciar_flujo_comun()
            iniciar.assert_not_called()
            self.assertFalse(salida.exists())
        pagina.close()

    def test_cancelar_confirmacion_de_proceso_no_inicia_qthread(self):
        pagina = PaginaProcesamientoActualizaciones()
        with (
            patch.object(pagina, "_rutas_entradas", return_value=object()),
            patch.object(pagina, "_confirmar_accion", return_value=False),
            patch.object(pagina, "_iniciar_operacion") as iniciar,
        ):
            pagina._iniciar_flujo_comun()
        iniciar.assert_not_called()
        pagina.close()

    def test_cancelar_proceso_en_ejecucion_requiere_confirmacion(self):
        pagina = PaginaProcesamientoActualizaciones()
        trabajador = TrabajadorActualizacion(lambda progreso: None)
        pagina.trabajador = trabajador
        with patch.object(pagina, "_confirmar_accion", return_value=False):
            pagina._cancelar()
        self.assertFalse(trabajador._cancelar)
        pagina.trabajador = None
        pagina.close()

    def test_entregable_actualizado_permanece_obligatorio(self):
        pagina = PaginaProcesamientoActualizaciones()
        self.assertIn("obligatorio", pagina.opcion_entregable_actualizado.text())
        self.assertTrue(pagina.opcion_entregable_actualizado.isEnabled())
        with patch("actualizacion_datos_pagina.QMessageBox.warning"):
            pagina.opcion_entregable_actualizado.setChecked(False)
        self.assertTrue(pagina.opcion_entregable_actualizado.isChecked())
        self.assertFalse(pagina.boton_entregable.isEnabled())
        pagina.close()

    def test_reaperturas_muestran_etapa_inicial_correcta(self):
        pagina = PaginaProcesamientoActualizaciones()
        with (
            patch.object(pagina, "_iniciar_operacion") as iniciar,
            patch.object(pagina, "_rutas_entradas", return_value=object()),
            patch.object(pagina.servicio, "contexto_es_vigente", return_value=True),
            patch.object(pagina, "_confirmar_accion", return_value=True),
        ):
            pagina._iniciar_reaperturas()
        self.assertEqual(
            iniciar.call_args.kwargs["texto_inicial"], "Preparando reaperturas..."
        )
        pagina.close()

    def test_carga_entregable_finaliza_modal_y_habilita_reaperturas(self):
        pagina = PaginaProcesamientoActualizaciones()
        pagina._dialogos["progreso_proceso"].show()
        with patch("actualizacion_datos_pagina.QTimer.singleShot") as temporizador:
            pagina._entregable_terminado(None)
        self.assertTrue(pagina.boton_reaperturas.isEnabled())
        self.assertEqual(pagina.progreso_proceso.value(), 100)
        self.assertEqual(pagina.etiqueta_porcentaje_proceso.text(), "100 %")
        temporizador.assert_called_once_with(
            350, pagina._dialogos["progreso_proceso"].accept
        )
        pagina.close()

    def test_reaperturas_generadas_abren_resultados_con_archivos_fisicos(self):
        pagina = PaginaProcesamientoActualizaciones()
        with TemporaryDirectory() as temporal:
            carpeta = Path(temporal)
            sistema = carpeta / "REAPERTURAS_SISTEMA.txt"
            entregable = carpeta / "ENTREGABLE_REAPERTURAS.txt"
            sistema.write_text("fila\n", encoding="utf-8")
            entregable.write_text("encabezado\nfila\n", encoding="utf-8")
            registro = RegistroProcesamiento(
                id_fila="1", archivo_origen="sansys.csv", numero_fila_origen=2,
                datos_originales={}, datos_normalizados={"OT": "1", "OS": "2"},
            )
            contexto = ContextoEjecucion(
                id_ejecucion="prueba", fecha_procesamiento="16/09/2026",
                carpeta_salida=temporal,
            )
            contexto.archivos_generados.update({
                "reaperturas_sistema": str(sistema),
                "entregable_reaperturas": str(entregable),
            })
            pagina._ultimo_resultado = ResultadoProceso(
                contexto=contexto,
                reaperturas=ResultadoRama(
                    nombre="REAPERTURAS", entradas=[registro], listas=[registro],
                    revisiones=[],
                ),
            )
            pagina.servicio.rutas_salida = SimpleNamespace(raiz=carpeta)
            with patch.object(pagina, "_abrir_dialogo_resultados") as abrir:
                pagina._mostrar_resultado_final_reaperturas()
                abrir.assert_called_once()
            self.assertIn("1 reaperturas generadas", pagina.etiqueta_estado.text())
        pagina.close()

    def test_reaperturas_sin_aprobadas_muestran_revision(self):
        pagina = PaginaProcesamientoActualizaciones()
        registro = RegistroProcesamiento(
            id_fila="1", archivo_origen="sansys.csv", numero_fila_origen=2,
            datos_originales={}, datos_normalizados={"OT": "1", "OS": "2"},
        )
        contexto = ContextoEjecucion(
            id_ejecucion="prueba", fecha_procesamiento="16/09/2026",
            carpeta_salida="C:/temporal",
        )
        contexto.archivos_generados["reaperturas_revision_manual"] = "revision.xlsx"
        pagina._ultimo_resultado = ResultadoProceso(
            contexto=contexto,
            reaperturas=ResultadoRama(
                nombre="REAPERTURAS", entradas=[registro], listas=[],
                revisiones=[registro],
            ),
        )
        with patch("actualizacion_datos_pagina.QMessageBox.warning") as aviso:
            pagina._mostrar_resultado_final_reaperturas()
            aviso.assert_called_once()
            self.assertIn("revision.xlsx", aviso.call_args.args[2])
        pagina.close()

    def test_desactivar_entregable_pide_confirmacion(self):
        pagina = PaginaProcesamientoActualizaciones()
        with patch.object(
            pagina, "_confirmar_accion", return_value=True
        ) as pregunta:
            self.assertTrue(pagina._confirmar_entregable_omitido())
        self.assertIn(
            "podría incluir registros que ya fueron actualizados",
            pregunta.call_args.args[1],
        )
        pagina.close()

    def test_cuatro_combinaciones_de_opciones_se_transmiten_al_servicio(self):
        pagina = PaginaProcesamientoActualizaciones()
        pagina.rutas.update({
            "csv_sansys": "sansys.csv", "control_gio": "gio.csv",
            "entregable_acumulado": "acumulado.csv",
            "libro_reglas": "reglas.xlsx", "matriz_gio": "matriz.xlsx",
            "carpeta_salida": "salida",
        })
        pagina.matriz_gio_previsualizada = MatrizReglasGio(
            reglas=(), combinaciones=frozenset(), hojas=(), ruta="matriz.xlsx"
        )
        for usar_acumulado in (True, False):
            with patch.object(pagina, "_confirmar_accion", return_value=True):
                pagina.opcion_entregable_acumulado.setChecked(usar_acumulado)
                rutas = pagina._rutas_entradas()
                self.assertEqual(
                    rutas.considerar_entregable_acumulado, usar_acumulado
                )
                self.assertTrue(rutas.considerar_entregable_actualizado)
                self.assertEqual(
                    rutas.ruta_entregable_acumulado is not None, usar_acumulado
                )
        pagina.close()

    def test_panel_principal_no_tiene_desplazamiento_vertical(self):
        pagina = PaginaProcesamientoActualizaciones()
        self.assertIsInstance(pagina, QScrollArea)
        self.assertEqual(
            pagina.verticalScrollBarPolicy(), Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.assertEqual(
            pagina.horizontalScrollBarPolicy(), Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        pagina.resize(900, 600)
        pagina.show()
        self.aplicacion.processEvents()
        self.assertFalse(pagina.verticalScrollBar().isVisible())
        pagina.close()

    def test_dialogos_son_unicos_y_se_reutilizan(self):
        pagina = PaginaProcesamientoActualizaciones()
        pagina.show()
        self.aplicacion.processEvents()
        referencia = pagina._dialogos["carga"]
        pagina._abrir_dialogo_carga()
        self.aplicacion.processEvents()
        pagina._abrir_dialogo_carga()
        self.aplicacion.processEvents()
        self.assertIs(referencia, pagina._dialogos["carga"])
        self.assertEqual(len(pagina._dialogos), 9)
        self.assertTrue(referencia.isModal())
        self.assertTrue(pagina._dialogos["reglas"].isModal())
        pagina.close()

    def test_botones_principales_abren_sus_ventanas_hijas(self):
        pagina = PaginaProcesamientoActualizaciones()
        pagina.show()
        self.aplicacion.processEvents()
        casos = (
            (pagina.boton_cargar_archivos, "carga"),
            (pagina.boton_abrir_dialogo_cierres, "cierres"),
            (pagina.boton_abrir_dialogo_entregable, "entregable"),
            (pagina.boton_abrir_dialogo_reaperturas, "reaperturas"),
            (pagina.boton_revisiones, "revisiones"),
        )
        for boton, clave in casos:
            for dialogo in pagina._dialogos.values():
                dialogo.hide()
            QTest.mouseClick(boton, Qt.MouseButton.LeftButton)
            self.aplicacion.processEvents()
            self.assertTrue(pagina._dialogos[clave].isVisible(), clave)
        pagina.close()

    def test_cambio_visual_de_estado_no_cambia_reglas(self):
        pagina = PaginaProcesamientoActualizaciones()
        pagina._cambiar_etapa("CIERRES", EstadoEtapa.PROCESANDO)
        self.assertIn("PROCESANDO", pagina.etiquetas_etapa["CIERRES"].text())
        self.assertEqual(pagina.servicio.configuracion.reglas_accion, [])
        pagina.close()

    def test_seleccion_de_archivo_y_carpeta(self):
        pagina = PaginaProcesamientoActualizaciones()
        with TemporaryDirectory() as temporal:
            archivo = str(Path(temporal) / "sansys.csv")
            with patch(
                "actualizacion_datos_pagina.QFileDialog.getOpenFileName",
                return_value=(archivo, ""),
            ), patch.object(
                pagina,
                "_iniciar_operacion",
                side_effect=lambda _operacion, terminar, modo_visual="proceso": terminar(1),
            ):
                pagina._seleccionar_archivo("csv_sansys")
            with patch("actualizacion_datos_pagina.QFileDialog.getExistingDirectory", return_value=temporal):
                pagina._seleccionar_salida()
            self.assertEqual(pagina.rutas["csv_sansys"], archivo)
            self.assertEqual(pagina.rutas["carpeta_salida"], temporal)
            self.assertIn("sansys.csv", pagina.etiquetas_ruta["csv_sansys"].text())
        pagina.close()

    def test_matriz_valida_muestra_resumen_y_habilita_vista(self):
        pagina = PaginaProcesamientoActualizaciones()
        ruta = "matriz_prueba.xlsx"
        matriz_prueba = MatrizReglasGio(
            reglas=(), combinaciones=frozenset(),
            hojas=("RESUMEN", "REGLAS_GIO", "COMBINACIONES_GIO", "GUIA_USO"),
            ruta=ruta, fecha_modificacion="01/10/2026 00:00:00",
        )
        with patch(
            "actualizacion_datos_pagina.QFileDialog.getOpenFileName",
            return_value=(ruta, ""),
        ), patch(
            "actualizacion_datos_pagina.leer_matriz_reglas_gio",
            return_value=matriz_prueba,
        ), patch.object(
            pagina,
            "_iniciar_operacion",
            side_effect=lambda _operacion, terminar, modo_visual="proceso": terminar(0),
        ):
            pagina._seleccionar_archivo("matriz_gio")
        texto = pagina.etiquetas_ruta["matriz_gio"].text()
        self.assertIn("MATRIZ VÁLIDA", texto)
        self.assertIn("reglas activas", texto)
        detalle = pagina.etiquetas_ruta["matriz_gio"].toolTip()
        self.assertIn("Reglas inactivas:", detalle)
        self.assertIn("Fecha de modificación:", detalle)
        self.assertTrue(pagina.boton_ver_reglas.isEnabled())
        with patch("actualizacion_datos_pagina.QDialog.exec", return_value=0):
            pagina._ver_reglas_cargadas()
        self.assertIsNotNone(pagina.tabla_reglas_cargadas)
        self.assertEqual(pagina.tabla_reglas_cargadas.columnCount(), 9)
        pagina.close()

    def test_matriz_con_error_bloquea_el_proceso(self):
        pagina = PaginaProcesamientoActualizaciones()
        with patch(
            "actualizacion_datos_pagina.leer_matriz_reglas_gio",
            side_effect=ValueError("MATRIZ CON ERRORES: ID_REGLA duplicado"),
        ):
            pagina._validar_matriz_seleccionada(Path("matriz_invalida.xlsx"))
        self.assertIn("MATRIZ CON ERRORES", pagina.etiquetas_ruta["matriz_gio"].text())
        self.assertFalse(pagina.boton_ver_reglas.isEnabled())
        pagina.close()

    def test_muestra_csv_sansys_y_un_solo_libro_de_reglas(self):
        pagina = PaginaProcesamientoActualizaciones()
        textos = [boton.text() for boton in pagina.findChildren(type(pagina.boton_flujo))]
        unidos = " | ".join(textos)
        self.assertIn("Seleccionar CSV SANSYS", unidos)
        self.assertIn("Seleccionar libro de reglas y actualización", unidos)
        self.assertNotIn("Seleccionar data general", unidos)
        self.assertNotIn("Seleccionar catálogo de actividades", unidos)
        self.assertNotIn("Seleccionar tabla de operarios", unidos)
        self.assertNotIn("Seleccionar tabla de lecturas", unidos)
        pagina.close()

    def test_progreso_cancelacion_error_y_vista_previa(self):
        pagina = PaginaProcesamientoActualizaciones()
        pagina._mostrar_progreso("Leyendo archivos", 3, 4)
        self.assertEqual(pagina.progreso.value(), 75)
        self.assertIn("Leyendo archivos", pagina.etiqueta_estado.text())

        trabajador = TrabajadorActualizacion(lambda progreso: None)
        pagina.trabajador = trabajador
        with patch.object(pagina, "_confirmar_accion", return_value=True):
            pagina._cancelar()
        self.assertTrue(trabajador._cancelar)
        self.assertIn("cancelando", pagina.etiqueta_estado.text())

        registro = RegistroProcesamiento(
            id_fila="1", archivo_origen="data.xlsx", numero_fila_origen=2,
            datos_originales={}, datos_normalizados={"OT": "1", "OS": "2"},
            motivo_final="PRUEBA",
        )
        pagina._mostrar_registros([registro])
        self.assertEqual(pagina.tabla.rowCount(), 1)
        self.assertGreaterEqual(pagina.tabla.columnCount(), 3)

        with TemporaryDirectory() as temporal:
            pagina.rutas["carpeta_salida"] = temporal
            with patch("actualizacion_datos_pagina.QMessageBox.critical") as mensaje:
                pagina._operacion_fallida("Fallo controlado", "detalle técnico")
                mensaje.assert_called_once()
            ruta_log = Path(temporal) / "error_procesamiento_actualizaciones.log"
            self.assertTrue(ruta_log.exists())
            self.assertIn("detalle técnico", ruta_log.read_text(encoding="utf-8"))
        self.assertIn("Fallo controlado", pagina.texto_resumen.toPlainText())
        pagina.trabajador = None
        pagina.close()

    def test_vista_previa_se_limita_a_500_filas(self):
        pagina = PaginaProcesamientoActualizaciones()
        registros = [
            RegistroProcesamiento(
                id_fila=str(indice), archivo_origen="data.csv",
                numero_fila_origen=indice + 2, datos_originales={},
                datos_normalizados={"OT": str(indice), "OS": str(indice)},
            )
            for indice in range(650)
        ]
        pagina._mostrar_registros(registros)
        self.assertEqual(pagina.tabla.rowCount(), 500)
        pagina.close()

    def test_error_fecha_inexistente_no_crea_log(self):
        pagina = PaginaProcesamientoActualizaciones()
        with TemporaryDirectory() as temporal:
            pagina.rutas["carpeta_salida"] = temporal
            mensaje = (
                "La fecha seleccionada no existe en la data. "
                "Seleccione una fecha disponible."
            )
            with patch("actualizacion_datos_pagina.QMessageBox.warning") as aviso:
                pagina._operacion_fallida(mensaje, "detalle")
                aviso.assert_called_once()
            self.assertFalse(
                (Path(temporal) / "error_procesamiento_actualizaciones.log").exists()
            )
        pagina.close()

    def test_inspeccion_visual_de_csv_informa_etapas_y_cantidad(self):
        pagina = PaginaProcesamientoActualizaciones()
        with TemporaryDirectory() as temporal:
            ruta = Path(temporal) / "entrada.csv"
            ruta.write_text("OT,OS\n1,10\n2,20\n", encoding="utf-8")
            etapas = []
            cantidad = pagina._inspeccionar_archivo_seleccionado(
                "csv_sansys",
                ruta,
                lambda etapa, actual, total: etapas.append((etapa, actual, total)),
            )
        self.assertEqual(cantidad, 2)
        self.assertEqual(etapas[0][0], "Leyendo archivo...")
        self.assertEqual(etapas[-1][0], "Carga completada ✓")
        pagina.close()

    def test_modal_de_progreso_refleja_porcentaje_y_error_de_carga(self):
        pagina = PaginaProcesamientoActualizaciones()
        pagina._modo_operacion = "carga_archivo"
        pagina._mostrar_progreso("Validando estructura...", 3, 5)
        self.assertEqual(pagina.progreso_carga_archivo.value(), 60)
        self.assertIn("Validando", pagina.etiqueta_estado_carga_archivo.text())

        pagina._clave_archivo_pendiente = "csv_sansys"
        pagina._ruta_archivo_pendiente = Path("entrada.csv")
        with patch("actualizacion_datos_pagina.QMessageBox.critical") as mensaje:
            pagina._operacion_fallida("Archivo inválido", "detalle")
            mensaje.assert_called_once()
        self.assertIn("Error al cargar", pagina.etiquetas_ruta["csv_sansys"].text())
        pagina.close()

    def test_apertura_de_carpeta_de_salida(self):
        pagina = PaginaProcesamientoActualizaciones()
        with TemporaryDirectory() as temporal:
            pagina.servicio.rutas_salida = SimpleNamespace(raiz=Path(temporal))
            with patch("actualizacion_datos_pagina.QDesktopServices.openUrl", return_value=True) as abrir:
                pagina._abrir_resultados()
                abrir.assert_called_once()
        pagina.close()

    def test_advierte_cuando_la_fecha_no_produce_data_filtrada(self):
        pagina = PaginaProcesamientoActualizaciones()
        contexto = ContextoEjecucion(
            id_ejecucion="prueba", fecha_procesamiento="27/09/2026",
            carpeta_salida="C:/temporal",
        )
        contexto.estados_etapas["FLUJO_COMUN"] = EstadoEtapa.COMPLETADO
        flujo = ResultadoFlujoComun(
            registros=[], data_filtrada=[],
            resumen=ResumenEtapa(etapa="FLUJO_COMUN"),
        )
        resultado = ResultadoProceso(contexto=contexto, flujo_comun=flujo)
        pagina.servicio.rutas_salida = SimpleNamespace(raiz=Path("C:/temporal/resultados"))
        with patch("actualizacion_datos_pagina.QMessageBox.warning") as mensaje:
            pagina._flujo_comun_terminado(resultado)
            mensaje.assert_called_once()
        self.assertFalse(pagina._procesar_cierres_automaticamente)
        self.assertFalse(pagina.boton_cierres.isEnabled())
        self.assertIn("no hay registros", pagina.etiqueta_estado.text())
        pagina.close()

    def test_advierte_cuando_no_hay_cierres_listos_para_txt(self):
        pagina = PaginaProcesamientoActualizaciones()
        contexto = ContextoEjecucion(
            id_ejecucion="prueba", fecha_procesamiento="27/09/2026",
            carpeta_salida="C:/temporal",
        )
        contexto.estados_etapas["CIERRES"] = EstadoEtapa.CON_ERRORES
        revision = RegistroProcesamiento(
            id_fila="1", archivo_origen="sansys.csv", numero_fila_origen=2,
            datos_originales={}, datos_normalizados={"OT": "1", "OS": "2"},
            motivo_final="ACCION_SIN_REGLA_CONFIGURADA",
        )
        resultado = ResultadoProceso(
            contexto=contexto,
            cierres=ResultadoRama(
                nombre="CIERRES", entradas=[revision], listas=[], revisiones=[revision]
            ),
        )
        pagina.servicio.rutas_salida = SimpleNamespace(raiz=Path("C:/temporal/resultados"))
        with patch("actualizacion_datos_pagina.QMessageBox.warning") as mensaje:
            pagina._cierres_terminados(resultado)
            mensaje.assert_called_once()
        self.assertIn("sin filas aptas", pagina.etiqueta_estado.text())
        pagina.close()


if __name__ == "__main__":
    unittest.main()
