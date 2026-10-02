# -*- coding: utf-8 -*-
"""Motor del módulo Procesamiento de actualizaciones.

La interfaz gráfica vive fuera de este paquete. Los módulos de negocio no
dependen de PySide6 para que puedan probarse y reutilizarse de forma segura.
"""

from .configuracion import ConfiguracionProcesamiento
from .modelos import (
    CategoriaResultado,
    ContextoEjecucion,
    EstadoEtapa,
    EstadoFila,
    RegistroProcesamiento,
    ResultadoValidacion,
)

__all__ = [
    "CategoriaResultado",
    "ConfiguracionProcesamiento",
    "ContextoEjecucion",
    "EstadoEtapa",
    "EstadoFila",
    "RegistroProcesamiento",
    "ResultadoValidacion",
]
