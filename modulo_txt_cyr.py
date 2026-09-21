# -*- coding: utf-8 -*-
from __future__ import annotations

import csv
import io
import re
import zipfile
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile

from workbook_models import SheetModel, WorkbookModel


ENCABEZADOS_SYSACO = [
    "nrocarga",
    "actividad",
    "nroorden",
    "codigopersonal",
    "nrosuministro",
    "fechaprogramacion",
    "ruta",
    "auxiliar",
]
ENCABEZADOS_ERRORES = ["NRO_OT", "NIS_RAD", "RUTA", "motivo_error"]
COLUMNAS_OBLIGATORIAS_SANSYS = ["NNUM_OS", "NRO_OT", "NIS_RAD", "RUTA"]
CODIFICACIONES_ENTRADA_TXT = ("utf-8-sig", "utf-8", "cp1252")


@dataclass
class ResultadoTxtCyr:
    total: int
    validos: int
    errores: int
    generados: int
    operarios_encontrados: int
    operarios_no_encontrados: int
    carpeta_salida: Path
    ruta_sansys: Path
    ruta_sysaco: Path
    ruta_reporte_errores: Optional[Path]


def limpiar_texto(valor: object) -> str:
    return str(valor if valor is not None else "").strip()


def normalizar_encabezado(valor: object) -> str:
    texto = limpiar_texto(valor).upper()
    return re.sub(r"[^A-Z0-9_]+", "_", texto).strip("_")


def indice_columna_desde_letras(letras: str) -> int:
    valor = 0
    for caracter in limpiar_texto(letras).upper():
        if "A" <= caracter <= "Z":
            valor = valor * 26 + (ord(caracter) - ord("A") + 1)
    return valor - 1


def obtener_celda(fila: List[str], indice: int) -> str:
    if 0 <= indice < len(fila):
        return limpiar_texto(fila[indice])
    return ""


def normalizar_identificador_numerico(valor: object) -> str:
    texto = limpiar_texto(valor)
    if not texto:
        return ""
    if not any(caracter in texto for caracter in ".,Ee"):
        return texto

    texto_numerico = texto.replace(" ", "").replace(",", ".")
    if not re.fullmatch(r"[+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?", texto_numerico):
        return texto

    try:
        numero = Decimal(texto_numerico)
    except InvalidOperation:
        return texto

    if numero == numero.to_integral_value():
        return format(numero.to_integral_value(), "f")
    return texto


def buscar_hoja(libro: WorkbookModel, nombre_hoja: str) -> Optional[SheetModel]:
    objetivo = normalizar_encabezado(nombre_hoja)
    for hoja in libro.sheets:
        if normalizar_encabezado(hoja.name) == objetivo:
            return hoja
    return None


def leer_texto_txt_con_codificacion_dinamica(ruta_txt: Path) -> str:
    contenido = ruta_txt.read_bytes()
    ultimo_error: Optional[UnicodeDecodeError] = None
    for codificacion in CODIFICACIONES_ENTRADA_TXT:
        try:
            return contenido.decode(codificacion)
        except UnicodeDecodeError as exc:
            ultimo_error = exc
            continue
    raise ValueError("No se pudo leer el TXT SANSYS con UTF-8, UTF-8 BOM ni Windows-1252.") from ultimo_error


def construir_mapa_operarios_ruteo(hoja: SheetModel) -> Dict[str, str]:
    indice_aq = indice_columna_desde_letras("AQ")
    indice_aw = indice_columna_desde_letras("AW")
    mapa: Dict[str, str] = {}
    todas_las_filas = [hoja.headers] + hoja.dataframe
    for fila in todas_las_filas:
        clave_nnum_os = normalizar_identificador_numerico(obtener_celda(fila, indice_aq))
        if not clave_nnum_os or clave_nnum_os in mapa:
            continue
        mapa[clave_nnum_os] = normalizar_identificador_numerico(obtener_celda(fila, indice_aw))
    return mapa


def construir_mapa_operarios_ruteo_desde_excel(ruta_excel: Path) -> Dict[str, str]:
    lector = _LectorXlsxMinimo(ruta_excel)
    filas = lector.leer_rango_hoja("RUTEO", "AQ", "AW")
    mapa: Dict[str, str] = {}
    for fila in filas:
        clave_nnum_os = normalizar_identificador_numerico(obtener_celda(fila, 0))
        if not clave_nnum_os or clave_nnum_os in mapa:
            continue
        mapa[clave_nnum_os] = normalizar_identificador_numerico(obtener_celda(fila, 6))
    return mapa


def leer_txt_sansys(ruta_txt: Path) -> Tuple[List[str], List[Dict[str, str]], List[List[str]]]:
    texto = leer_texto_txt_con_codificacion_dinamica(ruta_txt)
    lector = csv.reader(io.StringIO(texto), delimiter="\t")
    filas_crudas = [[limpiar_texto(celda) for celda in fila] for fila in lector]

    while filas_crudas and not any(filas_crudas[0]):
        filas_crudas.pop(0)

    if not filas_crudas or not any(filas_crudas[0]):
        raise ValueError("El TXT SANSYS no tiene encabezados validos.")

    encabezados = filas_crudas[0]
    encabezados_normalizados = [normalizar_encabezado(encabezado) for encabezado in encabezados]
    if not any(encabezados_normalizados):
        raise ValueError("El TXT SANSYS no tiene encabezados validos.")

    registros: List[Dict[str, str]] = []
    filas_originales: List[List[str]] = []
    ancho = len(encabezados)

    for fila in filas_crudas[1:]:
        if not any(fila):
            continue
        fila_completa = fila + [""] * max(0, ancho - len(fila))
        filas_originales.append(fila_completa[:ancho])
        registros.append(
            {
                encabezados_normalizados[indice]: limpiar_texto(fila_completa[indice]) if indice < len(fila_completa) else ""
                for indice in range(ancho)
                if encabezados_normalizados[indice]
            }
        )

    return encabezados, registros, filas_originales


def validar_encabezados_sansys(encabezados: List[str]) -> None:
    normalizados = {normalizar_encabezado(encabezado) for encabezado in encabezados}
    mensajes = {
        "NNUM_OS": "El TXT SANSYS no contiene la columna NNUM_OS.",
        "NRO_OT": "El TXT SANSYS no contiene la columna NRO_OT.",
        "NIS_RAD": "El TXT SANSYS no contiene la columna NIS_RAD.",
        "RUTA": "El TXT SANSYS no contiene la columna RUTA.",
    }
    for columna in COLUMNAS_OBLIGATORIAS_SANSYS:
        if columna not in normalizados:
            raise ValueError(mensajes[columna])


def asegurar_columna_operario_sansys(
    encabezados: List[str],
    filas_originales: List[List[str]],
) -> Tuple[List[str], List[List[str]], int]:
    normalizados = [normalizar_encabezado(encabezado) for encabezado in encabezados]
    if "CD_EQUIPE_INTEGRACAO" in normalizados:
        return encabezados, filas_originales, normalizados.index("CD_EQUIPE_INTEGRACAO")

    encabezados_actualizados = encabezados + ["CD_EQUIPE_INTEGRACAO"]
    filas_actualizadas = [fila + [""] for fila in filas_originales]
    return encabezados_actualizados, filas_actualizadas, len(encabezados_actualizados) - 1


def guardar_archivo_tabulado(ruta: Path, encabezados: List[str], filas: List[List[str]]) -> None:
    with ruta.open("w", encoding="utf-8", newline="") as archivo:
        escritor = csv.writer(archivo, delimiter="\t", lineterminator="\r\n")
        escritor.writerow(encabezados)
        escritor.writerows(filas)


def crear_ruta_txt_con_correlativo(carpeta_salida: Path, nombre_base: str, fecha_archivo: str) -> Path:
    ruta = carpeta_salida / f"{nombre_base}_{fecha_archivo}.txt"
    if not ruta.exists():
        return ruta

    correlativo = 1
    while True:
        ruta_con_correlativo = carpeta_salida / f"{nombre_base}_{fecha_archivo}_{correlativo}.txt"
        if not ruta_con_correlativo.exists():
            return ruta_con_correlativo
        correlativo += 1


def guardar_reporte_errores_xlsx(ruta: Path, filas: List[List[str]]) -> None:
    valores = [ENCABEZADOS_ERRORES] + filas
    filas_xml = []
    for indice_fila, fila in enumerate(valores, start=1):
        celdas = []
        for indice_columna, valor in enumerate(fila, start=1):
            referencia = f"{_letra_columna_xlsx(indice_columna)}{indice_fila}"
            celdas.append(f'<c r="{referencia}" t="inlineStr"><is><t>{escape(limpiar_texto(valor))}</t></is></c>')
        filas_xml.append(f'<row r="{indice_fila}">{"".join(celdas)}</row>')

    hoja_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<sheetData>{"".join(filas_xml)}</sheetData></worksheet>'
    )
    libro_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="Errores" sheetId="1" r:id="rId1"/></sheets></workbook>'
    )
    relaciones_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="xl/workbook.xml"/></Relationships>'
    )
    relaciones_libro_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        'Target="worksheets/sheet1.xml"/></Relationships>'
    )
    tipos_contenido_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '</Types>'
    )

    with ZipFile(ruta, "w", compression=ZIP_DEFLATED) as archivo_zip:
        archivo_zip.writestr("[Content_Types].xml", tipos_contenido_xml)
        archivo_zip.writestr("_rels/.rels", relaciones_xml)
        archivo_zip.writestr("xl/workbook.xml", libro_xml)
        archivo_zip.writestr("xl/_rels/workbook.xml.rels", relaciones_libro_xml)
        archivo_zip.writestr("xl/worksheets/sheet1.xml", hoja_xml)


def _letra_columna_xlsx(indice: int) -> str:
    letras = ""
    while indice:
        indice, residuo = divmod(indice - 1, 26)
        letras = chr(ord("A") + residuo) + letras
    return letras


def generar_txt_cyr(
    libro: WorkbookModel,
    ruta_txt_sansys: Path,
    carpeta_salida: Path,
    ruta_origen_libro: str = "",
    ahora: Optional[datetime] = None,
    registrar_proceso: Optional[Callable[[str], None]] = None,
) -> ResultadoTxtCyr:
    def registrar(mensaje: str) -> None:
        if registrar_proceso:
            registrar_proceso(mensaje)

    if libro is None:
        raise ValueError("Debe cargar primero el libro Excel con hoja RUTEO.")

    hoja_ruteo = buscar_hoja(libro, "RUTEO")
    if hoja_ruteo is None:
        raise ValueError("No se encontro la hoja RUTEO.")

    if not ruta_txt_sansys:
        raise ValueError("Debe seleccionar un TXT SANSYS.")
    ruta_txt_sansys = Path(ruta_txt_sansys)
    if not ruta_txt_sansys.exists():
        raise ValueError("Debe seleccionar un TXT SANSYS.")

    carpeta_salida = Path(carpeta_salida)
    if not str(carpeta_salida).strip():
        raise ValueError("Debe seleccionar una carpeta de salida.")
    carpeta_salida.mkdir(parents=True, exist_ok=True)

    registrar("Leyendo archivo...")
    encabezados, _registros, filas_originales = leer_txt_sansys(ruta_txt_sansys)
    validar_encabezados_sansys(encabezados)

    registrar("Procesando registros...")
    mapa_ruteo = construir_mapa_operarios_ruteo(hoja_ruteo)
    ruta_excel = Path(ruta_origen_libro or libro.source_path or "")
    if ruta_excel.exists() and ruta_excel.suffix.lower() in {".xlsx", ".xlsm"}:
        mapa_ruteo = construir_mapa_operarios_ruteo_desde_excel(ruta_excel)

    ahora = ahora or datetime.now()
    marca_tiempo = ahora.strftime("%Y%m%d_%H%M")
    fecha_archivo = ahora.strftime("%d%m%Y")
    fecha_programacion = ahora.strftime("%d/%m/%Y")
    ruta_sansys_salida = crear_ruta_txt_con_correlativo(carpeta_salida, "CR_SANSYS", fecha_archivo)
    ruta_sysaco_salida = crear_ruta_txt_con_correlativo(carpeta_salida, "CR_SYSACO", fecha_archivo)
    ruta_reporte_errores = carpeta_salida / f"REPORTE_ERRORES_CyR_{marca_tiempo}.xlsx"

    encabezados_salida, filas_salida_base, indice_operario = asegurar_columna_operario_sansys(encabezados, filas_originales)
    encabezados_normalizados = [normalizar_encabezado(encabezado) for encabezado in encabezados_salida]

    def indice(nombre: str) -> int:
        return encabezados_normalizados.index(nombre)

    indice_nnum_os = indice("NNUM_OS")
    indice_nro_ot = indice("NRO_OT")
    indice_nis_rad = indice("NIS_RAD")
    indice_ruta = indice("RUTA")

    filas_sansys_validas: List[List[str]] = []
    filas_sysaco: List[List[str]] = []
    filas_error: List[List[str]] = []
    operarios_encontrados = 0
    operarios_no_encontrados = 0
    contador_ruta_sysaco = 1

    for _indice_fila, fila in enumerate(filas_salida_base):
        nnum_os = normalizar_identificador_numerico(obtener_celda(fila, indice_nnum_os))
        nro_ot = obtener_celda(fila, indice_nro_ot)
        nis_rad = obtener_celda(fila, indice_nis_rad)
        ruta = obtener_celda(fila, indice_ruta)

        motivo = ""
        ope = ""
        if not nnum_os:
            motivo = "NNUM_OS vacio."
        elif nnum_os not in mapa_ruteo:
            motivo = "NNUM_OS no encontrado en RUTEO."
        else:
            ope = normalizar_identificador_numerico(mapa_ruteo[nnum_os])
            if not ope:
                motivo = "OPE vacio en RUTEO."

        if ope:
            operarios_encontrados += 1
        elif motivo in {"NNUM_OS vacio.", "NNUM_OS no encontrado en RUTEO.", "OPE vacio en RUTEO."}:
            operarios_no_encontrados += 1

        if not motivo and not nro_ot:
            motivo = "NRO_OT vacio."
        if not motivo and not nis_rad:
            motivo = "NIS_RAD vacio."

        if motivo:
            filas_error.append([nro_ot, nis_rad, ruta, motivo])
            continue

        fila_valida = fila[:]
        fila_valida[indice_operario] = ope
        filas_sansys_validas.append(fila_valida)
        filas_sysaco.append([
            "0",
            "CR",
            nro_ot,
            ope,
            nis_rad,
            fecha_programacion,
            str(contador_ruta_sysaco),
            "",
        ])
        contador_ruta_sysaco += 1

    registrar("Generando TXT...")
    guardar_archivo_tabulado(ruta_sansys_salida, encabezados_salida, filas_sansys_validas)
    guardar_archivo_tabulado(ruta_sysaco_salida, ENCABEZADOS_SYSACO, filas_sysaco)

    ruta_reporte_final: Optional[Path] = None
    if filas_error:
        guardar_reporte_errores_xlsx(ruta_reporte_errores, filas_error)
        ruta_reporte_final = ruta_reporte_errores

    registrar("Proceso terminado.")
    return ResultadoTxtCyr(
        total=len(filas_salida_base),
        validos=len(filas_sansys_validas),
        errores=len(filas_error),
        generados=len(filas_sysaco),
        operarios_encontrados=operarios_encontrados,
        operarios_no_encontrados=operarios_no_encontrados,
        carpeta_salida=carpeta_salida,
        ruta_sansys=ruta_sansys_salida,
        ruta_sysaco=ruta_sysaco_salida,
        ruta_reporte_errores=ruta_reporte_final,
    )


class _LectorXlsxMinimo:
    NS_PRINCIPAL = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    NS_RELACION = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"

    def __init__(self, archivo: Path):
        self.archivo = Path(archivo)
        self._textos_compartidos: Optional[List[str]] = None

    def _cargar_textos_compartidos(self) -> List[str]:
        if self._textos_compartidos is not None:
            return self._textos_compartidos

        textos: List[str] = []
        with zipfile.ZipFile(self.archivo) as archivo_zip:
            try:
                with archivo_zip.open("xl/sharedStrings.xml") as archivo:
                    for _evento, elemento in ET.iterparse(archivo, events=("end",)):
                        if elemento.tag != self.NS_PRINCIPAL + "si":
                            continue
                        textos.append("".join(t.text or "" for t in elemento.iter(self.NS_PRINCIPAL + "t")))
                        elemento.clear()
            except KeyError:
                pass

        self._textos_compartidos = textos
        return textos

    def _rutas_hojas(self) -> Dict[str, str]:
        with zipfile.ZipFile(self.archivo) as archivo_zip:
            raiz_libro = ET.fromstring(archivo_zip.read("xl/workbook.xml"))
            raiz_relaciones = ET.fromstring(archivo_zip.read("xl/_rels/workbook.xml.rels"))

        relaciones = {
            relacion.attrib["Id"]: relacion.attrib["Target"]
            for relacion in raiz_relaciones
            if relacion.tag.endswith("Relationship")
        }
        rutas: Dict[str, str] = {}
        nodo_hojas = raiz_libro.find(self.NS_PRINCIPAL + "sheets")
        if nodo_hojas is None:
            return rutas

        for hoja in nodo_hojas:
            nombre = hoja.attrib.get("name", "")
            id_relacion = hoja.attrib.get(self.NS_RELACION + "id", "")
            destino = relaciones.get(id_relacion, "")
            if not nombre or not destino:
                continue
            destino = destino.lstrip("/")
            rutas[normalizar_encabezado(nombre)] = destino if destino.startswith("xl/") else "xl/" + destino
        return rutas

    def leer_rango_hoja(self, nombre_hoja: str, columna_inicial: str, columna_final: str) -> List[List[str]]:
        rutas = self._rutas_hojas()
        ruta_hoja = rutas.get(normalizar_encabezado(nombre_hoja))
        if not ruta_hoja:
            raise ValueError("No se encontro la hoja RUTEO.")

        indice_inicial = indice_columna_desde_letras(columna_inicial)
        indice_final = indice_columna_desde_letras(columna_final)
        ancho = (indice_final - indice_inicial) + 1
        textos_compartidos = self._cargar_textos_compartidos()
        filas: List[List[str]] = []

        with zipfile.ZipFile(self.archivo) as archivo_zip:
            with archivo_zip.open(ruta_hoja) as archivo:
                for _evento, elemento in ET.iterparse(archivo, events=("end",)):
                    if elemento.tag != self.NS_PRINCIPAL + "row":
                        continue
                    valores_fila = [""] * ancho
                    tiene_valor = False
                    for celda in elemento.findall(self.NS_PRINCIPAL + "c"):
                        referencia = celda.attrib.get("r", "")
                        indice_columna = _indice_columna_desde_referencia(referencia)
                        if indice_columna < indice_inicial or indice_columna > indice_final:
                            continue
                        valor = _leer_valor_celda_xlsx(celda, textos_compartidos, self.NS_PRINCIPAL)
                        valores_fila[indice_columna - indice_inicial] = limpiar_texto(valor)
                        tiene_valor = tiene_valor or bool(limpiar_texto(valor))
                    if tiene_valor:
                        filas.append(valores_fila)
                    elemento.clear()

        return filas


def _indice_columna_desde_referencia(referencia: str) -> int:
    coincidencia = re.match(r"([A-Z]+)", limpiar_texto(referencia).upper())
    if coincidencia:
        return indice_columna_desde_letras(coincidencia.group(1))
    return -1


def _leer_valor_celda_xlsx(celda, textos_compartidos: List[str], ns_principal: str) -> str:
    tipo_celda = celda.attrib.get("t", "")
    if tipo_celda == "inlineStr":
        nodo_inline = celda.find(ns_principal + "is")
        if nodo_inline is None:
            return ""
        return "".join(t.text or "" for t in nodo_inline.iter(ns_principal + "t"))

    nodo_valor = celda.find(ns_principal + "v")
    if nodo_valor is None or nodo_valor.text is None:
        return ""

    valor_crudo = nodo_valor.text
    if tipo_celda == "s":
        try:
            return textos_compartidos[int(valor_crudo)]
        except Exception:
            return valor_crudo
    if tipo_celda == "b":
        return "TRUE" if valor_crudo == "1" else "FALSE"
    return valor_crudo
