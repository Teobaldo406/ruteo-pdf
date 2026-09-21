# -*- coding: utf-8 -*-
from __future__ import annotations

import csv
import io
import re
import unicodedata
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Tuple
from xml.etree import ElementTree as ET

from reportlab.graphics.barcode import code128
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas


FuncionProgreso = Callable[[int, int], None]
FuncionRegistro = Callable[[str], None]


@dataclass
class InformacionHoja:
    nombre: str
    rel_id: str
    ruta: str


@dataclass
class DatosCargados:
    encabezados: List[str]
    filas: List[List[str]]
    hoja_origen: str


@dataclass
class ResultadoOrdenesCyr:
    exportados: int
    errores: int
    carpeta_destino: Path


@dataclass(frozen=True)
class CampoPlantillaCyr:
    nombre: str
    x: int
    y: int
    tamano: int = 10


COLUMNA_MAXIMA_PLANTILLA_CYR = "AG"
FILA_MAXIMA_LECTURA_CYR = 200000

# Coordenadas tomadas de la logica antigua que rellenaba formato/cyr.pdf.
CAMPOS_PLANTILLA_CYR: Tuple[CampoPlantillaCyr, ...] = (
    CampoPlantillaCyr("os", 506, 770, 14),
    CampoPlantillaCyr("carga", 490, 750),
    CampoPlantillaCyr("nis", 55, 735),
    CampoPlantillaCyr("ot", 230, 735),
    CampoPlantillaCyr("cus", 450, 735),
    CampoPlantillaCyr("ruta", 235, 724),
    CampoPlantillaCyr("itin", 358, 724),
    CampoPlantillaCyr("aol", 450, 724),
    CampoPlantillaCyr("tipologia", 100, 712),
    CampoPlantillaCyr("fechaemision", 465, 712),
    CampoPlantillaCyr("observaciones", 100, 701),
    CampoPlantillaCyr("operario", 100, 691),
    CampoPlantillaCyr("sector", 458, 701),
    CampoPlantillaCyr("n.cliente", 110, 650),
    CampoPlantillaCyr("direccion", 110, 631),
    CampoPlantillaCyr("urb", 110, 621),
    CampoPlantillaCyr("referencia", 110, 611),
    CampoPlantillaCyr("distrito", 110, 601),
    CampoPlantillaCyr("cua", 330, 601),
    CampoPlantillaCyr("n.medidor", 110, 590),
    CampoPlantillaCyr("diametro", 250, 590),
    CampoPlantillaCyr("cota", 330, 590),
    CampoPlantillaCyr("accion", 108, 412),
    CampoPlantillaCyr("fecha", 160, 412),
    CampoPlantillaCyr("lectura", 270, 412),
    CampoPlantillaCyr("codigo", 350, 412),
    CampoPlantillaCyr("h.inicial", 420, 412),
    CampoPlantillaCyr("h.final", 500, 412),
    CampoPlantillaCyr("firma", 435, 290, 5),
    CampoPlantillaCyr("dni", 480, 280, 5),
)

def letra_columna_a_indice(letra: str) -> int:
    texto = re.sub(r"[^A-Za-z]", "", str(letra or "")).upper()
    if not texto:
        raise ValueError("Columna vacia")
    valor = 0
    for caracter in texto:
        valor = valor * 26 + (ord(caracter) - ord("A") + 1)
    return valor - 1


def referencia_celda_a_fila_columna(referencia: str) -> Tuple[int, int]:
    coincidencia = re.match(r"([A-Za-z]+)(\d+)", referencia or "")
    if not coincidencia:
        return 0, 0
    return int(coincidencia.group(2)) - 1, letra_columna_a_indice(coincidencia.group(1))


def texto_seguro(valor) -> str:
    if valor is None:
        return ""
    texto = str(valor).strip()
    if texto.endswith(".0"):
        try:
            numero = float(texto)
            if numero.is_integer():
                return str(int(numero))
        except Exception:
            pass
    return texto


def limpiar_nombre_archivo(texto: str, respaldo: str = "SIN_NOMBRE") -> str:
    texto = texto_seguro(texto) or respaldo
    texto = re.sub(r'[\\/:*?"<>|#%{}~&]', "_", texto)
    texto = re.sub(r"\s+", " ", texto).strip()
    return texto[:120] or respaldo


def normalizar_clave(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto_seguro(texto))
    texto = "".join(caracter for caracter in texto if not unicodedata.combining(caracter))
    texto = re.sub(r"[^a-zA-Z0-9]+", "", texto)
    return texto.lower()


class LectorXlsxRapido:
    NS_PRINCIPAL = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    NS_RELACION = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"

    def __init__(self, archivo: str | Path):
        self.archivo = str(archivo)
        self._textos_compartidos: Optional[List[str]] = None

    def listar_hojas(self) -> List[InformacionHoja]:
        with zipfile.ZipFile(self.archivo) as comprimido:
            xml_libro = comprimido.read("xl/workbook.xml")
            xml_relaciones = comprimido.read("xl/_rels/workbook.xml.rels")

        mapa_relaciones: Dict[str, str] = {}
        raiz_relaciones = ET.fromstring(xml_relaciones)
        for relacion in raiz_relaciones:
            rel_id = relacion.attrib.get("Id")
            destino = relacion.attrib.get("Target", "")
            if rel_id and "worksheets/" in destino:
                destino = destino.lstrip("/")
                if not destino.startswith("xl/"):
                    destino = "xl/" + destino
                mapa_relaciones[rel_id] = destino

        raiz = ET.fromstring(xml_libro)
        nodo_hojas = raiz.find(self.NS_PRINCIPAL + "sheets")
        hojas: List[InformacionHoja] = []
        if nodo_hojas is not None:
            for hoja in nodo_hojas.findall(self.NS_PRINCIPAL + "sheet"):
                nombre = hoja.attrib.get("name", "")
                rel_id = hoja.attrib.get(self.NS_RELACION + "id", "")
                ruta = mapa_relaciones.get(rel_id, "")
                if nombre and ruta:
                    hojas.append(InformacionHoja(nombre=nombre, rel_id=rel_id, ruta=ruta))
        return hojas

    def _cargar_textos_compartidos(self) -> List[str]:
        if self._textos_compartidos is not None:
            return self._textos_compartidos

        textos: List[str] = []
        with zipfile.ZipFile(self.archivo) as comprimido:
            if "xl/sharedStrings.xml" not in comprimido.namelist():
                self._textos_compartidos = []
                return self._textos_compartidos
            with comprimido.open("xl/sharedStrings.xml") as archivo:
                for _evento, elemento in ET.iterparse(archivo, events=("end",)):
                    if elemento.tag == self.NS_PRINCIPAL + "si":
                        partes = [t.text or "" for t in elemento.iter(self.NS_PRINCIPAL + "t")]
                        textos.append("".join(partes))
                        elemento.clear()

        self._textos_compartidos = textos
        return textos

    def leer_rango_hoja(
        self,
        nombre_hoja: str,
        fila_minima: int = 1,
        fila_maxima: int = FILA_MAXIMA_LECTURA_CYR,
        columna_minima: str = "A",
        columna_maxima: str = COLUMNA_MAXIMA_PLANTILLA_CYR,
    ) -> List[List[str]]:
        hojas = {hoja.nombre: hoja for hoja in self.listar_hojas()}
        if nombre_hoja not in hojas:
            raise ValueError(f"No existe la hoja: {nombre_hoja}")

        indice_columna_minima = letra_columna_a_indice(columna_minima)
        indice_columna_maxima = letra_columna_a_indice(columna_maxima)
        ancho = indice_columna_maxima - indice_columna_minima + 1
        filas_por_numero: Dict[int, List[str]] = {}
        textos_compartidos = self._cargar_textos_compartidos()

        with zipfile.ZipFile(self.archivo) as comprimido:
            with comprimido.open(hojas[nombre_hoja].ruta) as archivo:
                for _evento, elemento in ET.iterparse(archivo, events=("end",)):
                    if elemento.tag != self.NS_PRINCIPAL + "row":
                        continue
                    numero_fila = int(elemento.attrib.get("r", "0"))
                    if numero_fila < fila_minima or numero_fila > fila_maxima:
                        elemento.clear()
                        continue

                    valores_fila = [""] * ancho
                    for celda in elemento.findall(self.NS_PRINCIPAL + "c"):
                        referencia = celda.attrib.get("r", "")
                        _fila, indice_columna = referencia_celda_a_fila_columna(referencia)
                        if indice_columna < indice_columna_minima or indice_columna > indice_columna_maxima:
                            continue
                        tipo_celda = celda.attrib.get("t", "")
                        valor = ""
                        if tipo_celda == "inlineStr":
                            texto_en_linea = celda.find(self.NS_PRINCIPAL + "is")
                            if texto_en_linea is not None:
                                valor = "".join(t.text or "" for t in texto_en_linea.iter(self.NS_PRINCIPAL + "t"))
                        else:
                            nodo_valor = celda.find(self.NS_PRINCIPAL + "v")
                            if nodo_valor is not None and nodo_valor.text is not None:
                                crudo = nodo_valor.text
                                if tipo_celda == "s":
                                    try:
                                        valor = textos_compartidos[int(crudo)]
                                    except Exception:
                                        valor = crudo
                                elif tipo_celda == "b":
                                    valor = "TRUE" if crudo == "1" else "FALSE"
                                else:
                                    valor = crudo
                        valores_fila[indice_columna - indice_columna_minima] = texto_seguro(valor)

                    filas_por_numero[numero_fila] = valores_fila
                    elemento.clear()

        return [filas_por_numero[fila] for fila in sorted(filas_por_numero)]


def listar_nombres_hojas(ruta_archivo: str | Path) -> List[str]:
    ruta_archivo = Path(ruta_archivo)
    if ruta_archivo.suffix.lower() == ".csv":
        return ["CSV"]
    return [hoja.nombre for hoja in LectorXlsxRapido(ruta_archivo).listar_hojas()]


def leer_archivo_csv(ruta_archivo: str | Path) -> DatosCargados:
    with open(ruta_archivo, "r", encoding="utf-8-sig", newline="") as archivo:
        muestra = archivo.read(4096)
        archivo.seek(0)
        try:
            dialecto = csv.Sniffer().sniff(muestra, delimiters=",;\t|")
        except Exception:
            dialecto = csv.excel
        filas = [[texto_seguro(celda) for celda in fila] for fila in csv.reader(archivo, dialecto)]
    if not filas:
        raise ValueError("El CSV esta vacio")
    ancho = max(len(fila) for fila in filas)
    filas = [fila + [""] * (ancho - len(fila)) for fila in filas]
    filas_datos = [fila for fila in filas[1:] if any(texto_seguro(valor) for valor in fila)]
    return DatosCargados(encabezados=filas[0], filas=filas_datos, hoja_origen="CSV")


def leer_datos_libro(ruta_archivo: str | Path, nombre_hoja: str) -> DatosCargados:
    ruta_archivo = Path(ruta_archivo)
    if ruta_archivo.suffix.lower() == ".csv":
        return leer_archivo_csv(ruta_archivo)
    crudo = LectorXlsxRapido(ruta_archivo).leer_rango_hoja(
        nombre_hoja,
        fila_minima=1,
        fila_maxima=FILA_MAXIMA_LECTURA_CYR,
        columna_minima="A",
        columna_maxima=COLUMNA_MAXIMA_PLANTILLA_CYR,
    )
    if not crudo:
        raise ValueError("No se pudo leer el rango indicado")
    encabezados = crudo[0]
    filas = [fila for fila in crudo[1:] if any(texto_seguro(valor) for valor in fila)]
    return DatosCargados(encabezados=encabezados, filas=filas, hoja_origen=nombre_hoja)


def _crear_lector_fila(encabezados: List[str], fila: List[str]):
    indices_por_clave = {normalizar_clave(encabezado): indice for indice, encabezado in enumerate(encabezados)}
    alias = {
        "fechaemision": ["fechaemision", "emision"],
        "ncliente": ["ncliente", "nombrecliente", "cliente"],
        "nmedidor": ["nmedidor", "medidor"],
        "hinicial": ["hinicial", "horainicial"],
        "hfinal": ["hfinal", "horafinal"],
    }

    def obtener(nombre: str) -> str:
        clave = normalizar_clave(nombre)
        for candidato in [clave] + alias.get(clave, []):
            indice = indices_por_clave.get(candidato)
            if indice is not None and indice < len(fila):
                return texto_seguro(fila[indice])
        return ""

    return obtener


def _cargar_herramientas_pdf():
    try:
        from pypdf import PdfReader, PdfWriter

        return PdfReader, PdfWriter
    except Exception as exc:
        raise RuntimeError("Falta instalar pypdf. Ejecuta: python -m pip install pypdf") from exc


def generar_ordenes_cyr_pdf(
    encabezados: List[str],
    filas: Iterable[List[str]],
    plantilla_pdf: str | Path,
    carpeta_firmas: str | Path,
    carpeta_salida: str | Path,
    funcion_progreso: Optional[FuncionProgreso] = None,
    funcion_registro: Optional[FuncionRegistro] = None,
) -> ResultadoOrdenesCyr:
    plantilla_pdf = Path(plantilla_pdf)
    carpeta_firmas = Path(carpeta_firmas)
    carpeta_salida = Path(carpeta_salida)

    if not plantilla_pdf.exists():
        raise FileNotFoundError(f"No existe la plantilla PDF: {plantilla_pdf}")
    if not carpeta_firmas.exists():
        raise FileNotFoundError(f"No existe la carpeta de firmas: {carpeta_firmas}")

    filas = [list(fila) for fila in filas]
    if not filas:
        raise ValueError("No hay filas para generar ordenes.")

    carpeta_salida.mkdir(parents=True, exist_ok=True)
    lector_pdf, escritor_pdf = _cargar_herramientas_pdf()

    exportados = 0
    errores = 0
    total = len(filas)
    if funcion_progreso:
        funcion_progreso(0, total)

    for indice, fila in enumerate(filas, start=1):
        obtener = _crear_lector_fila(encabezados, fila)
        ot = obtener("ot")
        nis = obtener("nis")
        dni = obtener("dni")

        try:
            if not ot or not nis:
                raise ValueError("La fila no tiene OT o NIS.")
            if not dni:
                raise ValueError("La fila no tiene DNI para ubicar la firma.")

            ruta_firma = carpeta_firmas / f"D{dni}.jpg"
            if not ruta_firma.exists():
                raise FileNotFoundError(f"No existe la firma: {ruta_firma.name}")

            paquete = io.BytesIO()
            lienzo = canvas.Canvas(paquete, pagesize=A4)
            firma = ImageReader(str(ruta_firma))

            codigo_barras = code128.Code128(f"{ot}_{nis}", barHeight=40, barWidth=1.6)
            codigo_barras.drawOn(lienzo, 130, 780)
            for campo in CAMPOS_PLANTILLA_CYR:
                lienzo.setFont("Times-Roman", campo.tamano)
                lienzo.drawString(campo.x, campo.y, obtener(campo.nombre))
            lienzo.drawImage(firma, 465, 300, width=50, height=50)
            lienzo.save()
            paquete.seek(0)

            pdf_base = lector_pdf(str(plantilla_pdf))
            pdf_datos = lector_pdf(paquete)
            escritor = escritor_pdf()
            pagina = pdf_base.pages[0]
            pagina.merge_page(pdf_datos.pages[0])
            escritor.add_page(pagina)

            ruta_salida = carpeta_salida / f"{limpiar_nombre_archivo(ot)}_{limpiar_nombre_archivo(nis)}.pdf"
            with ruta_salida.open("wb") as archivo_salida:
                escritor.write(archivo_salida)

            exportados += 1
            if funcion_registro:
                funcion_registro(f"OK {indice}/{total}: {ruta_salida}")
        except Exception as exc:
            errores += 1
            if funcion_registro:
                etiqueta = f"{ot}_{nis}" if ot or nis else f"fila {indice}"
                funcion_registro(f"ERROR {indice}/{total} en {etiqueta}: {exc}")

        if funcion_progreso:
            funcion_progreso(indice, total)

    return ResultadoOrdenesCyr(exportados=exportados, errores=errores, carpeta_destino=carpeta_salida)
