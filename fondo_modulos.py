# -*- coding: utf-8 -*-
"""Fondo adaptable compartido por los módulos operativos."""

import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtWidgets import QWidget


def ruta_recurso(*partes: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base.joinpath(*partes)


class FondoModulosWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._imagen = QPixmap(str(ruta_recurso("assets", "fondo_modulos_hd.png")))

    def paintEvent(self, evento):
        super().paintEvent(evento)
        if self._imagen.isNull():
            return
        pintor = QPainter(self)
        fondo = self._imagen.scaled(
            self.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        x = (self.width() - fondo.width()) // 2
        y = (self.height() - fondo.height()) // 2
        pintor.drawPixmap(x, y, fondo)
