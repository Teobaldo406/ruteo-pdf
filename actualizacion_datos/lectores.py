# -*- coding: utf-8 -*-
"""Lectores sin dependencias externas para CSV, TXT delimitado y XLSX."""

from __future__ import annotations

import csv
from dataclasses import dataclass
import io
import re
import unicodedata
import zipfile
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple
from xml.etree import ElementTree as ET

from .modelos import FormatoArchivo, TablaDatos
from .reglas_gio import HOJAS_MATRIZ_GIO, MatrizReglasGio, construir_matriz_gio


CODIFICACIONES_LECTURA = ("utf-8-sig", "utf-8", "cp1252", "latin-1")
DELIMITADORES = ("\t", ";", ",", "|")


@dataclass(frozen=True)
class LibroReglasCargado:
    actividad: TablaDatos
    operarios: TablaDatos
    lecturas: TablaDatos
    metadatos: Dict[str, Dict[str, object]]


def leer_matriz_reglas_gio(ruta: Path) -> MatrizReglasGio:
    """Verifica las cuatro hojas y carga la matriz ejecutable y su respaldo."""
    ruta = Path(ruta)
    try:
        with zipfile.ZipFile(ruta) as archivo_zip:
            hojas = _mapa_hojas(archivo_zip)
    except (zipfile.BadZipFile, KeyError, ET.ParseError) as error:
        raise ValueError(f"El archivo '{ruta.name}' no es un XLSX válido.") from error
    normalizadas = {_nombre_comparable(nombre): nombre for nombre in hojas}
    faltantes = sorted(HOJAS_MATRIZ_GIO - set(normalizadas))
    if faltantes:
        raise ValueError(
            "La matriz GIO no contiene las hojas obligatorias: "
            + ", ".join(faltantes)
            + f". Hojas detectadas: {', '.join(hojas) or 'ninguna'}."
        )
    reglas = leer_xlsx(ruta, hoja=normalizadas["REGLAS_GIO"], fila_encabezado=1)
    combinaciones = leer_xlsx(
        ruta, hoja=normalizadas["COMBINACIONES_GIO"], fila_encabezado=1
    )
    requeridas_reglas = {
        "ID_REGLA", "PRIORIDAD", "RGLA", "COINCIDENCIA_OBS", "PATRON_OBS",
        "CONDICION_ACC", "ACC_LISTA", "ACC_MIN", "ACC_MAX", "RESULTADO",
        "CATEGORIA", "MOTIVO", "DESTINO", "ACTIVO",
    }
    faltantes_columnas = sorted(requeridas_reglas - set(reglas.encabezados))
    if faltantes_columnas:
        raise ValueError(
            "La hoja REGLAS_GIO no contiene las columnas: "
            + ", ".join(faltantes_columnas)
        )
    requeridas_combinaciones = {"RGLA", "OBSERVACION", "ncod_causa"}
    faltantes_combinaciones = sorted(
        requeridas_combinaciones - set(combinaciones.encabezados)
    )
    if faltantes_combinaciones:
        raise ValueError(
            "La hoja COMBINACIONES_GIO no contiene las columnas: "
            + ", ".join(faltantes_combinaciones)
        )
    return construir_matriz_gio(reglas, combinaciones, hojas.keys(), ruta=ruta)


def _leer_texto(ruta: Path) -> Tuple[str, str]:
    for codificacion in CODIFICACIONES_LECTURA:
        try:
            return ruta.read_text(encoding=codificacion), codificacion
        except UnicodeDecodeError:
            continue
    raise ValueError(f"No se pudo determinar la codificación de '{ruta.name}'.")


def detectar_delimitador(texto: str) -> str:
    lineas = [linea for linea in texto.splitlines() if linea.strip()][:8]
    if not lineas:
        return "\t"
    primera = lineas[0]
    conteos = {delimitador: primera.count(delimitador) for delimitador in DELIMITADORES}
    mejor = max(conteos, key=conteos.get)
    if conteos[mejor] == 0:
        try:
            return csv.Sniffer().sniff("\n".join(lineas), delimiters="\t;,|").delimiter
        except csv.Error as error:
            raise ValueError("No se pudo detectar el delimitador del archivo.") from error
    return mejor


def _encabezados_unicos(encabezados: Sequence[object]) -> List[str]:
    resultado: List[str] = []
    usados: Dict[str, int] = {}
    for indice, valor in enumerate(encabezados, 1):
        base = str(valor).lstrip("\ufeff").strip() or f"COLUMNA_{indice}"
        usados[base] = usados.get(base, 0) + 1
        resultado.append(base if usados[base] == 1 else f"{base}_{usados[base]}")
    return resultado


def leer_archivo_delimitado(
    ruta: Path,
    *,
    tiene_encabezado: bool = True,
    columnas_sin_encabezado: Optional[Sequence[str]] = None,
    delimitador: Optional[str] = None,
) -> TablaDatos:
    ruta = Path(ruta)
    texto, codificacion = _leer_texto(ruta)
    separador = delimitador or detectar_delimitador(texto)
    lector = csv.reader(io.StringIO(texto), delimiter=separador)
    filas_crudas = list(lector)
    if not filas_crudas:
        raise ValueError(f"El archivo '{ruta.name}' está vacío.")

    if tiene_encabezado:
        encabezados = _encabezados_unicos(filas_crudas.pop(0))
    else:
        if not columnas_sin_encabezado:
            raise ValueError(
                f"El archivo '{ruta.name}' no tiene encabezado y no se indicó el orden de columnas."
            )
        encabezados = _encabezados_unicos(columnas_sin_encabezado)

    advertencias: List[str] = []
    filas: List[Dict[str, str]] = []
    ancho = len(encabezados)
    maximo = max((len(fila) for fila in filas_crudas), default=ancho)
    if maximo > ancho:
        for indice in range(ancho + 1, maximo + 1):
            encabezados.append(f"COLUMNA_EXTRA_{indice - ancho}")
        advertencias.append(
            "Se detectaron filas con columnas adicionales. Se conservaron como COLUMNA_EXTRA_n para revisión."
        )
        ancho = maximo

    for numero, fila in enumerate(filas_crudas, 2 if tiene_encabezado else 1):
        if len(fila) != ancho:
            advertencias.append(
                f"Fila {numero}: se esperaban {ancho} columnas y se recibieron {len(fila)}."
            )
        valores = list(fila) + [""] * max(0, ancho - len(fila))
        filas.append({encabezados[i]: valores[i] if i < len(valores) else "" for i in range(ancho)})

    return TablaDatos(
        ruta=ruta,
        encabezados=encabezados,
        filas=filas,
        formato=FormatoArchivo(
            tipo=ruta.suffix.lower().lstrip(".") or "txt",
            codificacion=codificacion,
            delimitador=separador,
            tiene_encabezado=tiene_encabezado,
            columnas=tuple(encabezados),
        ),
        advertencias=advertencias,
    )


def _indice_columna(referencia: str) -> int:
    letras = "".join(caracter for caracter in referencia if caracter.isalpha()).upper()
    resultado = 0
    for letra in letras:
        resultado = resultado * 26 + ord(letra) - 64
    return max(0, resultado - 1)


def _textos_compartidos(archivo_zip: zipfile.ZipFile) -> List[str]:
    if "xl/sharedStrings.xml" not in archivo_zip.namelist():
        return []
    raiz = ET.fromstring(archivo_zip.read("xl/sharedStrings.xml"))
    return ["".join(nodo.text or "" for nodo in elemento.iter() if nodo.tag.endswith("}t")) for elemento in raiz]


def _mapa_hojas(archivo_zip: zipfile.ZipFile) -> Dict[str, str]:
    ns = {
        "m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
        "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
        "p": "http://schemas.openxmlformats.org/package/2006/relationships",
    }
    libro = ET.fromstring(archivo_zip.read("xl/workbook.xml"))
    relaciones = ET.fromstring(archivo_zip.read("xl/_rels/workbook.xml.rels"))
    destinos = {
        relacion.attrib["Id"]: relacion.attrib["Target"]
        for relacion in relaciones.findall("p:Relationship", ns)
    }
    hojas: Dict[str, str] = {}
    for hoja in libro.findall("m:sheets/m:sheet", ns):
        nombre = hoja.attrib["name"]
        relacion = hoja.attrib[f"{{{ns['r']}}}id"]
        destino = destinos[relacion].replace("\\", "/")
        if destino.startswith("/"):
            ruta = destino.lstrip("/")
        elif destino.startswith("xl/"):
            ruta = destino
        else:
            ruta = f"xl/{destino}"
        hojas[nombre] = ruta
    return hojas


def _valor_celda(celda: ET.Element, compartidos: Sequence[str]) -> str:
    tipo = celda.attrib.get("t", "")
    if tipo == "inlineStr":
        return "".join(nodo.text or "" for nodo in celda.iter() if nodo.tag.endswith("}t"))
    nodo_valor = next((nodo for nodo in celda if nodo.tag.endswith("}v")), None)
    if nodo_valor is None or nodo_valor.text is None:
        return ""
    valor = nodo_valor.text
    if tipo == "s":
        try:
            return compartidos[int(valor)]
        except (ValueError, IndexError):
            return valor
    if tipo == "b":
        return "VERDADERO" if valor == "1" else "FALSO"
    return valor


def _nombre_comparable(valor: object) -> str:
    texto = "" if valor is None else str(valor).strip()
    texto = "".join(
        caracter for caracter in unicodedata.normalize("NFKD", texto)
        if not unicodedata.combining(caracter)
    )
    return re.sub(r"[^A-Za-z0-9]+", "_", texto).strip("_").upper()


def _filas_crudas_xlsx(raiz: ET.Element, compartidos: Sequence[str]) -> Tuple[Dict[int, Dict[int, str]], int]:
    filas: Dict[int, Dict[int, str]] = {}
    max_columna = 0
    for fila in (nodo for nodo in raiz.iter() if nodo.tag.endswith("}row")):
        numero = int(fila.attrib.get("r", len(filas) + 1))
        valores: Dict[int, str] = {}
        for celda in (nodo for nodo in fila if nodo.tag.endswith("}c")):
            indice = _indice_columna(celda.attrib.get("r", "A1"))
            max_columna = max(max_columna, indice)
            valores[indice] = _valor_celda(celda, compartidos)
        filas[numero] = valores
    return filas, max_columna


def _tabla_desde_filas_xlsx(
    ruta: Path,
    nombre_hoja: str,
    filas: Dict[int, Dict[int, str]],
    max_columna: int,
    fila_encabezado: int,
) -> TablaDatos:
    if fila_encabezado not in filas:
        raise ValueError(f"La fila de encabezado {fila_encabezado} no existe en '{nombre_hoja}'.")
    encabezados = _encabezados_unicos([
        filas[fila_encabezado].get(indice, "") for indice in range(max_columna + 1)
    ])
    datos: List[Dict[str, str]] = []
    for numero in sorted(n for n in filas if n > fila_encabezado):
        valores = filas[numero]
        if not valores or not any(str(valor).strip() for valor in valores.values()):
            continue
        datos.append({encabezados[i]: valores.get(i, "") for i in range(len(encabezados))})
    return TablaDatos(
        ruta=ruta,
        encabezados=encabezados,
        filas=datos,
        formato=FormatoArchivo(
            tipo="xlsx", codificacion="binario-xlsx", tiene_encabezado=True,
            fila_encabezado=fila_encabezado, columnas=tuple(encabezados),
        ),
        hoja=nombre_hoja,
    )


def _detectar_encabezado(
    filas: Dict[int, Dict[int, str]],
    grupos_requeridos: Sequence[Sequence[str]],
    nombre_hoja: str,
) -> int:
    for numero in sorted(filas)[:25]:
        nombres = {_nombre_comparable(valor) for valor in filas[numero].values() if str(valor).strip()}
        if all(any(_nombre_comparable(alias) in nombres for alias in grupo) for grupo in grupos_requeridos):
            return numero
    requeridos = ["/".join(grupo) for grupo in grupos_requeridos]
    raise ValueError(
        f"No se encontró la fila de encabezados de la hoja '{nombre_hoja}'. "
        f"Se esperaban columnas equivalentes a: {', '.join(requeridos)}."
    )


def leer_libro_reglas(ruta: Path) -> LibroReglasCargado:
    """Carga ACTIVIDAD, OPERARIO y LECT una sola vez y detecta sus encabezados."""
    ruta = Path(ruta)
    contratos = {
        # En la muestra real hay dos columnas físicas llamadas TIPO. La
        # segunda se vuelve TIPO_2 al hacer únicos los encabezados.
        "ACTIVIDAD": (("TIPO",), ("C", "TIPO_OS", "VTIPO_OS")),
        "OPERARIO": (("OPER", "OPERARIO"), ("CODIGO_GIO",), ("CODIGO_SYSACAO",)),
        "LECT": (("NIS_RAD", "NIS", "NISRA", "IDRA"), ("LECT", "LECTURA")),
    }
    try:
        with zipfile.ZipFile(ruta) as archivo_zip:
            compartidos = _textos_compartidos(archivo_zip)
            hojas = _mapa_hojas(archivo_zip)
            por_nombre = {_nombre_comparable(nombre): (nombre, destino) for nombre, destino in hojas.items()}
            faltantes = [nombre for nombre in contratos if nombre not in por_nombre]
            if faltantes:
                raise ValueError(
                    "El libro de reglas no contiene las hojas obligatorias: "
                    + ", ".join(faltantes)
                    + f". Hojas detectadas: {', '.join(hojas) or 'ninguna'}."
                )
            tablas: Dict[str, TablaDatos] = {}
            metadatos: Dict[str, Dict[str, object]] = {}
            for clave, grupos in contratos.items():
                nombre_real, destino = por_nombre[clave]
                raiz = ET.fromstring(archivo_zip.read(destino))
                filas, max_columna = _filas_crudas_xlsx(raiz, compartidos)
                encabezado = _detectar_encabezado(filas, grupos, nombre_real)
                tabla = _tabla_desde_filas_xlsx(
                    ruta, nombre_real, filas, max_columna, encabezado
                )
                encabezados_normalizados = {
                    _nombre_comparable(nombre): nombre for nombre in tabla.encabezados
                }
                claves_utiles = {
                    "ACTIVIDAD": ("C", "TIPO", "TIPO_2", "TIPO_OS"),
                    "OPERARIO": ("OPER", "OPERARIO", "CODIGO_GIO", "CODIGO_SYSACAO"),
                    "LECT": ("NIS_RAD", "NIS", "NISRA", "IDRA", "LECT", "LECTURA"),
                }[clave]
                columnas_utiles = [
                    encabezados_normalizados[nombre]
                    for nombre in claves_utiles if nombre in encabezados_normalizados
                ]
                tabla.filas = [
                    fila for fila in tabla.filas
                    if any(str(fila.get(columna, "")).strip() for columna in columnas_utiles)
                ]
                tablas[clave] = tabla
                metadatos[clave] = {
                    "hoja_detectada": nombre_real,
                    "fila_encabezado": encabezado,
                    "filas_fisicas": len(filas),
                    "filas_utiles": len(tabla.filas),
                    "ultima_fila_fisica": max(filas, default=0),
                }
    except (zipfile.BadZipFile, KeyError, ET.ParseError) as error:
        raise ValueError(f"El archivo '{ruta.name}' no es un XLSX válido.") from error
    encabezados_operario = {
        _nombre_comparable(nombre): nombre for nombre in tablas["OPERARIO"].encabezados
    }
    columna_operario = encabezados_operario.get("OPER") or encabezados_operario.get("OPERARIO")
    columna_gio = encabezados_operario.get("CODIGO_GIO")
    columna_sysacao = encabezados_operario.get("CODIGO_SYSACAO")
    filas_operario = tablas["OPERARIO"].filas
    valores_operario = [str(fila.get(columna_operario, "")).strip() for fila in filas_operario]
    valores_operario_informados = [valor for valor in valores_operario if valor]
    metadatos["OPERARIO"].update({
        "operarios_unicos": len({valor.upper() for valor in valores_operario_informados}),
        "operarios_duplicados": len(valores_operario_informados) - len({valor.upper() for valor in valores_operario_informados}),
        "sin_codigo_gio": sum(not str(fila.get(columna_gio, "")).strip() for fila in filas_operario),
        "sin_codigo_sysacao": sum(not str(fila.get(columna_sysacao, "")).strip() for fila in filas_operario),
    })
    conflictos = 0
    equivalencias: Dict[str, set[Tuple[str, str]]] = {}
    for fila in filas_operario:
        gio = str(fila.get(columna_gio, "")).strip()
        sysacao = str(fila.get(columna_sysacao, "")).strip()
        operario = str(fila.get(columna_operario, "")).strip()
        for codigo in (gio, sysacao):
            if codigo:
                equivalencias.setdefault(codigo, set()).add((operario, gio if codigo == sysacao else sysacao))
    conflictos = sum(len(valores) > 1 for valores in equivalencias.values())
    metadatos["OPERARIO"]["codigos_con_equivalencias_diferentes"] = conflictos

    return LibroReglasCargado(
        actividad=tablas["ACTIVIDAD"],
        operarios=tablas["OPERARIO"],
        lecturas=tablas["LECT"],
        metadatos=metadatos,
    )


def leer_xlsx(ruta: Path, *, hoja: Optional[str] = None, fila_encabezado: int = 1) -> TablaDatos:
    ruta = Path(ruta)
    try:
        with zipfile.ZipFile(ruta) as archivo_zip:
            compartidos = _textos_compartidos(archivo_zip)
            hojas = _mapa_hojas(archivo_zip)
            if not hojas:
                raise ValueError("El libro no contiene hojas.")
            nombre_hoja = hoja or next(iter(hojas))
            if nombre_hoja not in hojas:
                raise ValueError(
                    f"No existe la hoja '{nombre_hoja}'. Disponibles: {', '.join(hojas)}."
                )
            raiz = ET.fromstring(archivo_zip.read(hojas[nombre_hoja]))
    except (zipfile.BadZipFile, KeyError, ET.ParseError) as error:
        raise ValueError(f"El archivo '{ruta.name}' no es un XLSX válido.") from error

    filas_por_numero, max_columna = _filas_crudas_xlsx(raiz, compartidos)
    return _tabla_desde_filas_xlsx(
        ruta, nombre_hoja, filas_por_numero, max_columna, fila_encabezado
    )


def leer_tabla(
    ruta: Path,
    *,
    hoja: Optional[str] = None,
    fila_encabezado: int = 1,
    tiene_encabezado: bool = True,
    columnas_sin_encabezado: Optional[Sequence[str]] = None,
) -> TablaDatos:
    extension = Path(ruta).suffix.lower()
    if extension in {".xlsx", ".xlsm"}:
        return leer_xlsx(Path(ruta), hoja=hoja, fila_encabezado=fila_encabezado)
    if extension in {".csv", ".txt", ".tsv"}:
        return leer_archivo_delimitado(
            Path(ruta), tiene_encabezado=tiene_encabezado,
            columnas_sin_encabezado=columnas_sin_encabezado,
        )
    raise ValueError(f"Formato no admitido: '{extension or 'sin extensión'}'.")
