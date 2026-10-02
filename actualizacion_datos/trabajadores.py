# -*- coding: utf-8 -*-
"""Trabajadores Qt: ejecutan el motor sin tocar widgets desde el hilo."""

from __future__ import annotations

import traceback
from typing import Callable

from PySide6.QtCore import QObject, Signal, Slot


class TrabajadorActualizacion(QObject):
    progreso = Signal(str, int, int)
    terminado = Signal(object)
    error = Signal(str, str)
    cancelado = Signal()

    def __init__(self, operacion: Callable[[Callable[[str, int, int], None]], object]):
        super().__init__()
        self._operacion = operacion
        self._cancelar = False

    def solicitar_cancelacion(self) -> None:
        self._cancelar = True

    def _informar_progreso(self, etapa: str, actual: int, total: int) -> None:
        if self._cancelar:
            raise InterruptedError("Proceso cancelado por el usuario.")
        self.progreso.emit(etapa, actual, total)

    @Slot()
    def ejecutar(self) -> None:
        try:
            resultado = self._operacion(self._informar_progreso)
            if self._cancelar:
                self.cancelado.emit()
            else:
                self.terminado.emit(resultado)
        except InterruptedError:
            self.cancelado.emit()
        except Exception as error:
            self.error.emit(str(error), traceback.format_exc())
