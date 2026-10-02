# -*- coding: utf-8 -*-

from pathlib import Path
from tempfile import TemporaryDirectory
import csv
import unittest

from actualizacion_datos.auditoria import (
    crear_contexto,
    escribir_auditoria_csv,
    escribir_historial_csv,
    verificar_conservacion,
)
from actualizacion_datos.configuracion import ConfiguracionProcesamiento, ReglaAccion
from actualizacion_datos.modelos import (
    CategoriaResultado,
    EstadoFila,
    RegistroProcesamiento,
)


class PruebasModelosAuditoriaActualizacion(unittest.TestCase):
    def crear_registro(self, identificador="origen:2"):
        return RegistroProcesamiento(
            id_fila=identificador,
            archivo_origen="origen.csv",
            numero_fila_origen=2,
            datos_originales={"nro_ot": "001.0", "nnum_os": "OS-1"},
            datos_normalizados={
                "OT": "001", "OS": "OS-1", "NIS": "0005",
                "COO_ORIGINAL": "3111153", "COO_ORIGINAL_SYSACAO": "3111153",
                "COO_FINAL_GIO": "172725", "ESTADO_CONVERSION": "CONVERTIDO_SYSACAO_A_GIO",
            },
        )

    def test_registra_historial_y_resultado_final(self):
        registro = self.crear_registro()
        registro.marcar_continua(EstadoFila.NORMALIZADA, "NOR-01", "NORMALIZACION", "Fila normalizada.")
        registro.registrar(
            "PAR-03", "VALIDACION_OT_OS", CategoriaResultado.REVISION_MANUAL,
            "INCONSISTENCIA_OT_OS", "OT-1", "OT-2",
        )
        self.assertEqual(registro.estado, EstadoFila.EN_REVISION)
        self.assertEqual(registro.motivo_final, "INCONSISTENCIA_OT_OS")
        self.assertEqual(len(registro.historial), 2)

    def test_auditoria_conserva_original_e_historial(self):
        registro = self.crear_registro()
        registro.registrar(
            "COM-03", "ENTREGABLE_ACUMULADO", CategoriaResultado.EXCLUSION_OPERATIVA,
            "YA_ACTUALIZADA_EN_ENTREGABLE", "001", "OT ausente",
        )
        with TemporaryDirectory() as temporal:
            raiz = Path(temporal)
            contexto = crear_contexto("21/09/2026", raiz)
            ruta_auditoria = escribir_auditoria_csv(raiz / "auditoria.csv", contexto.id_ejecucion, [registro])
            ruta_historial = escribir_historial_csv(raiz / "historial.csv", contexto.id_ejecucion, [registro])
            with ruta_auditoria.open(encoding="utf-8-sig", newline="") as archivo:
                fila = next(csv.DictReader(archivo, delimiter=";"))
            self.assertEqual(fila["ORIGINAL_nro_ot"], "001.0")
            self.assertEqual(fila["MOTIVO"], "YA_ACTUALIZADA_EN_ENTREGABLE")
            self.assertEqual(fila["COO_ORIGINAL_SYSACAO"], "3111153")
            self.assertEqual(fila["COO_FINAL_GIO"], "172725")
            self.assertEqual(fila["ESTADO_CONVERSION"], "CONVERTIDO_SYSACAO_A_GIO")
            self.assertIn("COM-03", ruta_historial.read_text(encoding="utf-8-sig"))

    def test_conservacion_detecta_id_repetido(self):
        uno = self.crear_registro("igual")
        dos = self.crear_registro("igual")
        with self.assertRaisesRegex(ValueError, "ID_FILA repetidos"):
            verificar_conservacion([uno, dos])

    def test_configuracion_no_inventa_reglas_de_accion(self):
        configuracion = ConfiguracionProcesamiento.predeterminada()
        self.assertEqual(configuracion.reglas_accion, [])
        configuracion.agregar_reglas_accion([
            ReglaAccion("ACC-PRUEBA", "C", "511", aplica_lectura=True),
        ])
        encontradas = configuracion.reglas_para_registro({"TIPO": "C", "ACC": "511"})
        self.assertEqual([regla.id_regla for regla in encontradas], ["ACC-PRUEBA"])


if __name__ == "__main__":
    unittest.main()
