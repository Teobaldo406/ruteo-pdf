# -*- coding: utf-8 -*-
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

CODIFICACIONES = ("utf-8-sig", "utf-8", "cp1252")
SEPARADORES = ("\t", ";", "|")


@dataclass(frozen=True)
class Consolidado:
    ruta: Path
    codificacion: str
    separador: str
    lineas: list[str]
    tiene_encabezado: bool
    total_registros: int
    indices_busqueda: dict[str, int]


@dataclass(frozen=True)
class ListaCodigos:
    ruta: Path
    codigos: list[str]
    repetidos: int


@dataclass(frozen=True)
class ResultadoExtraccion:
    tipo_busqueda: str
    total_registros: int
    total_solicitados: int
    codigos_encontrados: int
    codigos_no_encontrados: int
    filas_extraidas: int
    codigos_repetidos: int
    codigos_con_multiples_coincidencias: int
    ruta_encontrados: Path
    ruta_no_encontrados: Path
    carpeta_salida: Path


def leer_texto(ruta: Path) -> tuple[str, str]:
    try:
        contenido = ruta.read_bytes()
    except OSError as exc:
        raise ValueError(f"No se pudo leer el archivo:\n{ruta}\n\n{exc}") from exc
    for codificacion in CODIFICACIONES:
        try:
            return contenido.decode(codificacion), codificacion
        except UnicodeDecodeError:
            pass
    raise ValueError("El archivo no usa UTF-8, UTF-8 con BOM ni Windows-1252.")


def detectar_separador(lineas: list[str]) -> str:
    muestras = [linea for linea in lineas if linea.strip()][:30]
    if not muestras:
        raise ValueError("El consolidado está vacío.")
    puntuaciones = {
        separador: sum(max(0, len(linea.split(separador)) - 1) for linea in muestras)
        for separador in SEPARADORES
    }
    mejor = max(SEPARADORES, key=lambda item: puntuaciones[item])
    if puntuaciones[mejor]:
        return mejor
    if any(re.search(r"\s{2,}", linea) for linea in muestras):
        return "espacios_multiples"
    raise ValueError("No se pudo detectar el separador del consolidado.")


def dividir_columnas(linea: str, separador: str) -> list[str]:
    return re.split(r"\s{2,}", linea.strip()) if separador == "espacios_multiples" else linea.split(separador)


ALIAS_COLUMNAS = {
    "NIS": {"NIS", "NISRAD", "NROSUMINISTRO"},
    "OT": {"OT", "NROOT", "NUMOT", "NUMEROOT"},
    "OS": {"OS", "NNUMOS", "NROOS", "NUMOS", "NUMEROOS"},
}


def identificar_columnas(linea: str, separador: str) -> dict[str, int]:
    encabezados = [
        re.sub(r"[^A-Z0-9]", "", valor.upper())
        for valor in dividir_columnas(linea, separador)
    ]
    indices: dict[str, int] = {}
    for tipo, alias in ALIAS_COLUMNAS.items():
        coincidencias = [indice for indice, encabezado in enumerate(encabezados) if encabezado in alias]
        if len(coincidencias) == 1:
            indices[tipo] = coincidencias[0]
    return indices


def cargar_consolidado(ruta: str | Path) -> Consolidado:
    ruta = Path(ruta)
    texto, codificacion = leer_texto(ruta)
    lineas = [linea for linea in texto.splitlines() if linea.strip()]
    separador = detectar_separador(lineas)
    for numero, linea in enumerate(lineas, start=1):
        if len(dividir_columnas(linea, separador)) < 3:
            raise ValueError(f"La línea {numero} no tiene las tres columnas mínimas requeridas.")
    indices_detectados = identificar_columnas(lineas[0], separador) if lineas else {}
    tiene_encabezado = len(indices_detectados) == 3
    indices_busqueda = indices_detectados if tiene_encabezado else {"NIS": 0, "OT": 1, "OS": 2}
    return Consolidado(
        ruta, codificacion, separador, lineas, tiene_encabezado,
        len(lineas) - int(tiene_encabezado), indices_busqueda,
    )


def cargar_lista_codigos(ruta: str | Path) -> ListaCodigos:
    ruta = Path(ruta)
    texto, _ = leer_texto(ruta)
    originales = [linea.strip() for linea in texto.splitlines() if linea.strip()]
    codigos = list(dict.fromkeys(originales))
    if not codigos:
        raise ValueError("La lista no contiene códigos válidos.")
    return ListaCodigos(ruta, codigos, len(originales) - len(codigos))


def ruta_incremental(carpeta: Path, nombre: str) -> Path:
    candidata = carpeta / nombre
    if not candidata.exists():
        return candidata
    base, extension = Path(nombre).stem, Path(nombre).suffix
    numero = 2
    while (carpeta / f"{base}_{numero}{extension}").exists():
        numero += 1
    return carpeta / f"{base}_{numero}{extension}"


def extraer_registros(
    consolidado: Consolidado,
    lista: ListaCodigos,
    tipo_busqueda: str,
    carpeta_salida: Optional[str | Path] = None,
    progreso: Optional[Callable[[int], None]] = None,
    cancelado: Optional[Callable[[], bool]] = None,
) -> ResultadoExtraccion:
    if tipo_busqueda not in consolidado.indices_busqueda:
        raise ValueError("Seleccione NIS, OT u OS.")
    carpeta = Path(carpeta_salida) if carpeta_salida else consolidado.ruta.parent / "RESULTADOS_BUSQUEDA"
    try:
        carpeta.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ValueError(f"No se pudo crear la carpeta:\n{carpeta}\n\n{exc}") from exc
    solicitados, conteo, encontradas = set(lista.codigos), Counter(), []
    registros = consolidado.lineas[1 if consolidado.tiene_encabezado else 0:]
    total = max(1, len(registros))
    for posicion, linea in enumerate(registros, start=1):
        if cancelado and cancelado():
            raise InterruptedError("Búsqueda cancelada.")
        valor = dividir_columnas(linea, consolidado.separador)[
            consolidado.indices_busqueda[tipo_busqueda]
        ].strip()
        if valor in solicitados:
            encontradas.append(linea)
            conteo[valor] += 1
        if progreso and (posicion == total or posicion % max(1, total // 100) == 0):
            progreso(min(100, posicion * 100 // total))
    hallados = set(conteo)
    faltantes = [codigo for codigo in lista.codigos if codigo not in hallados]
    ruta_encontrados = ruta_incremental(carpeta, "REGISTROS_ENCONTRADOS.txt")
    ruta_faltantes = ruta_incremental(carpeta, "CODIGOS_NO_ENCONTRADOS.txt")
    try:
        ruta_encontrados.write_text("\n".join(encontradas) + ("\n" if encontradas else ""), encoding="utf-8", newline="")
        ruta_faltantes.write_text("\n".join(faltantes) + ("\n" if faltantes else ""), encoding="utf-8", newline="")
    except OSError as exc:
        raise ValueError(f"No se pudieron guardar los resultados:\n{carpeta}\n\n{exc}") from exc
    return ResultadoExtraccion(
        tipo_busqueda, consolidado.total_registros, len(lista.codigos), len(hallados),
        len(faltantes), len(encontradas), lista.repetidos,
        sum(1 for cantidad in conteo.values() if cantidad > 1),
        ruta_encontrados, ruta_faltantes, carpeta,
    )
