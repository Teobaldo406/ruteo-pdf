# -*- coding: utf-8 -*-
"""
Aplicativo CyR - Sin Excel, sin macros VBA.

Qué hace:
- Lee archivos .xlsx / .xlsm / .csv sin abrir Microsoft Excel.
- Permite filtrar por TURNO u otra columna.
- Si filtras un solo turno/valor, SOLO genera PDFs de ese filtro.
- Agrupa por la columna E por defecto, como la macro original.
- Guarda PDFs en carpetas locales.

Requisitos externos:
    pip install reportlab PySide6

Ejecutar:
    python main.py
"""

from __future__ import annotations

import atexit
import csv
import collections.abc
import ctypes
import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import traceback
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple
from xml.etree import ElementTree as ET


def _guardar_error_inicio(tipo, valor, traza):
    """Conserva el error de arranque cuando el ejecutable no tiene consola."""
    try:
        carpeta = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
        detalle = "".join(traceback.format_exception(tipo, valor, traza))
        (carpeta / "error_inicio.txt").write_text(detalle, encoding="utf-8")
    except Exception:
        pass


sys.excepthook = _guardar_error_inicio

try:
    from PySide6.QtCore import QEvent, QObject, QSize, Qt, QThread, QTimer, QUrl, Signal, Slot
    from PySide6.QtGui import QAction, QActionGroup, QColor, QDesktopServices, QFont, QFontDatabase, QIcon, QPainter, QPixmap
    from PySide6.QtWidgets import (
        QApplication,
        QComboBox,
        QFileDialog,
        QFrame,
        QGridLayout,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QMainWindow,
        QMenu,
        QMessageBox,
        QProgressBar,
        QPushButton,
        QScrollArea,
        QAbstractItemView,
        QHeaderView,
        QSizePolicy,
        QSpinBox,
        QStackedWidget,
        QStyle,
        QTabWidget,
        QTableWidget,
        QTableWidgetItem,
        QTextEdit,
        QToolBar,
        QToolButton,
        QVBoxLayout,
        QWidget,
    )
except Exception as exc:  # pragma: no cover
    _guardar_error_inicio(type(exc), exc, exc.__traceback__)
    print("Falta instalar PySide6. Ejecuta: pip install PySide6")
    print("Detalle:", exc)
    sys.exit(1)

try:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_LEFT
    from reportlab.lib.pagesizes import A4, letter, landscape
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import Image as RLImage, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
except Exception:
    tipo, valor, traza = sys.exc_info()
    _guardar_error_inicio(tipo, valor, traza)
    print("Falta instalar ReportLab. Ejecuta: pip install reportlab")
    raise

from pdf_template_editor import PdfTemplateEditorWindow, PdfTemplateModel, PdfTemplateService
from google_sheets_import import GoogleSheetsConnectWindow, GoogleSheetsWorkbookSourceService
from modulo_txt_cyr import ResultadoTxtCyr, buscar_hoja, generar_txt_cyr
from extractor_ordenes_pagina import PaginaExtractorOrdenes
from depuracion_ot_pagina import PaginaDepuracionOT
from fondo_modulos import FondoModulosWidget
from workbook_models import SheetModel, WorkbookModel
from app_update import CURRENT_VERSION, check_for_updates, preparar_actualizacion_automatica


NOMBRE_MUTEX_APLICACION = r"Local\Aplicativo_CyR_Unica_Instancia"
_manejador_mutex_instancia = None
_biblioteca_kernel32 = None


def _traer_ventana_existente_al_frente():
    """Restaura y enfoca la ventana abierta cuando Windows lo permite."""
    if not sys.platform.startswith("win"):
        return
    try:
        usuario32 = ctypes.WinDLL("user32", use_last_error=True)
        usuario32.FindWindowW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
        usuario32.FindWindowW.restype = ctypes.c_void_p
        titulo = f"Aplicativo CyR v{CURRENT_VERSION} - cierres y reaperturas"
        ventana = usuario32.FindWindowW(None, titulo)
        if not ventana:
            return
        usuario32.ShowWindow(ventana, 9)  # SW_RESTORE
        usuario32.BringWindowToTop(ventana)
        if not usuario32.SetForegroundWindow(ventana):
            usuario32.FlashWindow(ventana, True)
    except Exception:
        pass


def _liberar_mutex_instancia():
    global _manejador_mutex_instancia
    if _manejador_mutex_instancia and _biblioteca_kernel32:
        _biblioteca_kernel32.CloseHandle(_manejador_mutex_instancia)
        _manejador_mutex_instancia = None


def asegurar_instancia_unica() -> bool:
    """Devuelve False si ya existe otra instancia de Aplicativo CyR."""
    global _manejador_mutex_instancia, _biblioteca_kernel32
    if not sys.platform.startswith("win"):
        return True

    _biblioteca_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _biblioteca_kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
    _biblioteca_kernel32.CreateMutexW.restype = ctypes.c_void_p
    _biblioteca_kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    _biblioteca_kernel32.CloseHandle.restype = ctypes.c_bool

    manejador = _biblioteca_kernel32.CreateMutexW(None, False, NOMBRE_MUTEX_APLICACION)
    if not manejador:
        return True

    if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
        _biblioteca_kernel32.CloseHandle(manejador)
        _traer_ventana_existente_al_frente()
        return False

    _manejador_mutex_instancia = manejador
    atexit.register(_liberar_mutex_instancia)
    return True


def resource_path(*parts: str) -> Path:
    base_path = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base_path.joinpath(*parts)


def load_app_icon() -> QIcon:
    for icon_path in (
        resource_path("assets", "app_icon_v3.png"),
        resource_path("assets", "app_icon.ico"),
        resource_path("assets", "app_icon.png"),
    ):
        if icon_path.exists():
            return QIcon(str(icon_path))
    return QIcon()


def configure_windows_taskbar_icon():
    if not sys.platform.startswith("win"):
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("AplicativoCyR.Generador.IconoV3")
    except Exception:
        pass


# =========================
# Utilidades de columnas
# =========================

def col_letter_to_index(letter: str) -> int:
    """Convierte A -> 0, B -> 1, AA -> 26."""
    text = re.sub(r"[^A-Za-z]", "", str(letter or "")).upper()
    if not text:
        raise ValueError("Columna vacía")
    value = 0
    for char in text:
        value = value * 26 + (ord(char) - ord("A") + 1)
    return value - 1


def index_to_col_letter(index: int) -> str:
    index += 1
    letters = ""
    while index:
        index, rem = divmod(index - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def cell_ref_to_row_col(ref: str) -> Tuple[int, int]:
    m = re.match(r"([A-Za-z]+)(\d+)", ref or "")
    if not m:
        return 0, 0
    col = col_letter_to_index(m.group(1))
    row = int(m.group(2)) - 1
    return row, col


def safe_text(value) -> str:
    if value is None:
        return ""
    text = str(value)
    if text.endswith(".0"):
        try:
            number = float(text)
            if number.is_integer():
                return str(int(number))
        except Exception:
            pass
    return text.strip()


def clean_filename(text: str, fallback: str = "SIN_NOMBRE") -> str:
    text = safe_text(text) or fallback
    text = re.sub(r'[\\/:*?"<>|#%{}~&]', "_", text)
    text = re.sub(r"\s+", " ", text).strip()
    return (text[:120] or fallback)


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", safe_text(text)).strip().upper()


# =========================
# Lector rápido XLSX/XLSM sin Excel
# =========================

@dataclass
class SheetInfo:
    name: str
    rel_id: str
    path: str


class FastXlsxReader:
    """Lector OOXML simple para .xlsx/.xlsm. No usa Excel ni openpyxl."""

    NS_MAIN = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    NS_REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
    NS_PKG_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"

    def __init__(self, filename: str | Path):
        self.filename = str(filename)
        self._shared_strings: Optional[List[str]] = None

    def list_sheets(self) -> List[SheetInfo]:
        with zipfile.ZipFile(self.filename) as z:
            workbook_xml = z.read("xl/workbook.xml")
            rels_xml = z.read("xl/_rels/workbook.xml.rels")

        rel_map: Dict[str, str] = {}
        rel_root = ET.fromstring(rels_xml)
        for rel in rel_root:
            rel_id = rel.attrib.get("Id")
            target = rel.attrib.get("Target", "")
            if rel_id and "worksheets/" in target:
                target = target.lstrip("/")
                if not target.startswith("xl/"):
                    target = "xl/" + target
                rel_map[rel_id] = target

        root = ET.fromstring(workbook_xml)
        sheets_node = root.find(self.NS_MAIN + "sheets")
        sheets: List[SheetInfo] = []
        if sheets_node is not None:
            for sheet in sheets_node.findall(self.NS_MAIN + "sheet"):
                name = sheet.attrib.get("name", "")
                rel_id = sheet.attrib.get(self.NS_REL + "id", "")
                path = rel_map.get(rel_id, "")
                if name and path:
                    sheets.append(SheetInfo(name=name, rel_id=rel_id, path=path))
        return sheets

    def _load_shared_strings(self) -> List[str]:
        if self._shared_strings is not None:
            return self._shared_strings

        strings: List[str] = []
        with zipfile.ZipFile(self.filename) as z:
            if "xl/sharedStrings.xml" not in z.namelist():
                self._shared_strings = []
                return self._shared_strings
            with z.open("xl/sharedStrings.xml") as f:
                # iterparse para no cargar el XML completo en memoria como árbol gigante
                for event, elem in ET.iterparse(f, events=("end",)):
                    if elem.tag == self.NS_MAIN + "si":
                        parts = []
                        for t in elem.iter(self.NS_MAIN + "t"):
                            if t.text:
                                parts.append(t.text)
                        strings.append("".join(parts))
                        elem.clear()

        self._shared_strings = strings
        return strings

    def read_sheet_range(
        self,
        sheet_name: str,
        min_row: int,
        max_row: int,
        min_col_letter: str = "A",
        max_col_letter: str = "Z",
        skip_hidden_rows: bool = False,
    ) -> List[List[str]]:
        """Lee un rango rectangular. Filas en formato humano 1,2,3..."""
        sheets = {s.name: s for s in self.list_sheets()}
        if sheet_name not in sheets:
            raise ValueError(f"No existe la hoja: {sheet_name}")

        min_col = col_letter_to_index(min_col_letter)
        max_col = col_letter_to_index(max_col_letter)
        width = max_col - min_col + 1
        out: Dict[int, List[str]] = {}
        shared = self._load_shared_strings()
        sheet_path = sheets[sheet_name].path

        with zipfile.ZipFile(self.filename) as z:
            with z.open(sheet_path) as f:
                for event, elem in ET.iterparse(f, events=("end",)):
                    if elem.tag == self.NS_MAIN + "row":
                        row_num = int(elem.attrib.get("r", "0"))
                        if row_num < min_row or row_num > max_row:
                            elem.clear()
                            continue
                        if skip_hidden_rows and elem.attrib.get("hidden") == "1":
                            elem.clear()
                            continue

                        row_values = [""] * width
                        for c in elem.findall(self.NS_MAIN + "c"):
                            ref = c.attrib.get("r", "")
                            _, col_idx = cell_ref_to_row_col(ref)
                            if col_idx < min_col or col_idx > max_col:
                                continue
                            cell_type = c.attrib.get("t", "")
                            value = ""

                            if cell_type == "inlineStr":
                                is_node = c.find(self.NS_MAIN + "is")
                                if is_node is not None:
                                    parts = [t.text or "" for t in is_node.iter(self.NS_MAIN + "t")]
                                    value = "".join(parts)
                            else:
                                v_node = c.find(self.NS_MAIN + "v")
                                if v_node is not None and v_node.text is not None:
                                    raw = v_node.text
                                    if cell_type == "s":
                                        try:
                                            value = shared[int(raw)]
                                        except Exception:
                                            value = raw
                                    elif cell_type == "b":
                                        value = "TRUE" if raw == "1" else "FALSE"
                                    else:
                                        value = raw

                            row_values[col_idx - min_col] = safe_text(value)

                        out[row_num] = row_values
                        elem.clear()

        # Devuelve solo las filas leídas. Mantiene huecos si hay filas sin nodos.
        rows = []
        for row_num in range(min_row, max_row + 1):
            if row_num in out:
                rows.append(out[row_num])
        return rows


# =========================
# Carga de datos
# =========================

@dataclass
class LoadedData:
    headers: List[str]
    rows: List[List[str]]
    source_sheet: str


def read_csv_file(path: str | Path) -> LoadedData:
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        sample = f.read(4096)
        f.seek(0)
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        reader = csv.reader(f, dialect)
        all_rows = [[safe_text(x) for x in row] for row in reader]

    if not all_rows:
        raise ValueError("El CSV está vacío")
    max_width = max(len(r) for r in all_rows)
    all_rows = [r + [""] * (max_width - len(r)) for r in all_rows]
    return LoadedData(headers=all_rows[0], rows=all_rows[1:], source_sheet="CSV")


def read_workbook_data(
    path: str | Path,
    sheet_name: str,
    header_row: int = 1,
    data_start_row: int = 2,
    data_end_row: int = 4001,
    min_col: str = "A",
    max_col: str = "Z",
    skip_hidden_rows: bool = False,
) -> LoadedData:
    reader = FastXlsxReader(path)
    raw = reader.read_sheet_range(
        sheet_name=sheet_name,
        min_row=header_row,
        max_row=data_end_row,
        min_col_letter=min_col,
        max_col_letter=max_col,
        skip_hidden_rows=skip_hidden_rows,
    )
    if not raw:
        raise ValueError("No se pudo leer el rango indicado")
    headers = raw[0]
    rows = raw[max(0, data_start_row - header_row):]
    # Filtra filas totalmente vacías
    rows = [r for r in rows if any(safe_text(x) for x in r)]
    return LoadedData(headers=headers, rows=rows, source_sheet=sheet_name)


def loaded_data_to_sheet_model(data: LoadedData) -> SheetModel:
    max_width = max([len(data.headers)] + [len(row) for row in data.rows] + [0])
    headers = list(data.headers) + [""] * (max_width - len(data.headers))
    rows = [list(row) + [""] * (max_width - len(row)) for row in data.rows]
    return SheetModel(
        name=data.source_sheet,
        dataframe=rows,
        headers=headers,
        row_count=len(rows),
        column_count=max_width,
        visible_rows=list(range(len(rows))),
    )


def sheet_model_to_loaded_data(sheet: SheetModel) -> LoadedData:
    return LoadedData(headers=list(sheet.headers), rows=[list(row) for row in sheet.dataframe], source_sheet=sheet.name)


def choose_print_sheet_name(sheet_names: List[str]) -> str:
    for preferred in ("CARGO (3)", "RUTEO"):
        if preferred in sheet_names:
            return preferred
    return sheet_names[0] if sheet_names else ""


def workbook_signature(workbook: WorkbookModel) -> str:
    payload = []
    for sheet in workbook.sheets:
        payload.append({
            "name": sheet.name,
            "headers": sheet.headers,
            "rows": sheet.dataframe,
        })
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def read_local_workbook_model(
    path: str | Path,
    header_row: int = 1,
    data_start_row: int = 2,
    data_end_row: int = 4001,
    min_col: str = "A",
    max_col: str = "Z",
    skip_hidden_rows: bool = False,
) -> WorkbookModel:
    path = Path(path)
    loaded_at = datetime.now().isoformat(timespec="seconds")

    if path.suffix.lower() == ".csv":
        data = read_csv_file(path)
        sheet = loaded_data_to_sheet_model(data)
        return WorkbookModel(
            source_type="CSV",
            source_url="",
            source_path=str(path),
            workbook_name=path.name,
            loaded_at=loaded_at,
            sheets=[sheet],
            active_sheet_name=sheet.name,
            print_sheet_name=sheet.name,
        )

    reader = FastXlsxReader(path)
    sheets = []
    for sheet_info in reader.list_sheets():
        raw = reader.read_sheet_range(
            sheet_name=sheet_info.name,
            min_row=header_row,
            max_row=data_end_row,
            min_col_letter=min_col,
            max_col_letter=max_col,
            skip_hidden_rows=skip_hidden_rows,
        )
        if raw:
            headers = raw[0]
            rows = raw[max(0, data_start_row - header_row):]
            rows = [row for row in rows if any(safe_text(value) for value in row)]
        else:
            headers = []
            rows = []
        sheets.append(loaded_data_to_sheet_model(LoadedData(headers=headers, rows=rows, source_sheet=sheet_info.name)))

    if not sheets:
        raise ValueError("No se encontraron hojas en el archivo.")

    print_sheet_name = choose_print_sheet_name([sheet.name for sheet in sheets])
    return WorkbookModel(
        source_type="ExcelLocal",
        source_url="",
        source_path=str(path),
        workbook_name=path.name,
        loaded_at=loaded_at,
        sheets=sheets,
        active_sheet_name=print_sheet_name,
        print_sheet_name=print_sheet_name,
    )


def find_header_col(headers: List[str], candidates: Iterable[str]) -> Optional[int]:
    target = [normalize(c) for c in candidates]
    for i, h in enumerate(headers):
        h_norm = normalize(h)
        if h_norm in target:
            return i
    # búsqueda suave: contiene
    for i, h in enumerate(headers):
        h_norm = normalize(h)
        if any(t and t in h_norm for t in target):
            return i
    return None


def unique_values(rows: List[List[str]], col_idx: int) -> List[str]:
    seen = set()
    out = []
    for row in rows:
        value = safe_text(row[col_idx] if col_idx < len(row) else "")
        if not value:
            continue
        key = normalize(value)
        if key in {"#N/A", "#ERROR!", "#REF!"}:
            continue
        if key not in seen:
            seen.add(key)
            out.append(value)
    return out


# =========================
# Generador PDF
# =========================

# Anchos reales A:Z leidos de la plantilla Excel "CARGO (3)".
# Se escalan al ancho imprimible del PDF para conservar las proporciones.
EXCEL_TEMPLATE_COL_WIDTHS = [
    22.7109375, 32.42578125, 32.5703125, 39.0, 55.0, 35.28515625,
    47.28515625, 58.5703125, 42.42578125, 31.5703125, 64.140625, 31.7109375,
    70.7109375, 48.7109375, 50.7109375, 130.7109375, 74.85546875,
    91.28515625, 58.42578125, 50.140625, 50.85546875, 46.28515625,
    38.42578125, 47.140625, 47.140625, 95.7109375,
]

EXCEL_PRINT_TITLE = "CARGO DE TRABAJO ACCIONES PERSUASIVAS"
EXCEL_PRINT_NOTES = [
    "NOTA: LA INFORMACION A CONSIGNAR EN LA HOJA DE RUTA DEBERA SER FIEL REFLEJO DE LO ENCONTRADO Y/O EJECUTADO EN CAMPO, EN CASO DE CONSIGNAR INFORMACION ERRONEA SERA SUJETO A LAS SANCIONES SEGUN LA NORMATIVA DE TRABAJO CORRESPONDIENTE.",
    "AL DIGITAR LA INFORMACION DEBERA REGISTRASE TODOS LOS CAMPOS CORRECTAMENTE TANTO LA EJECUCION COMO LA OBSERVACION",
    "DEJAR ESQUELA POR CIERRE, REAPERTURA O REVISION, SEGUN SEA EL CASO A USUARIO O DEBAJO DE PUERTA EN AUSENCIA, PARA DAR A CONOCIMIENTO EL TRABAJO REALIZADO.",
]

EXCEL_TEMPLATE_COLUMNS = [
    ("Nª", ["Nª", "N°", "Nº", "NRO", "NO"], 0),
    ("CUS", ["CUS"], 1),
    ("MZN", ["MZN", "MANZANA"], 2),
    ("COD", ["COD", "CODIGO", "CÓDIGO"], 3),
    ("NOMOPE", ["NOMOPE", "NOM OPE", "OPERARIO"], 4),
    ("TURNO", ["TURNO"], 5),
    ("OBS", ["OBS"], 6),
    ("NIS", ["NIS"], 7),
    ("OT", ["OT"], 8),
    ("DIAM", ["DIAM", "DIÁM", "DIAMETRO", "DIÁMETRO"], 9),
    ("MEDIDOR", ["MEDIDOR"], 10),
    ("COTA", ["COTA"], 11),
    ("CLIENTE", ["CLIENTE"], 12),
    ("MUNICIPIO", ["MUNICIPIO"], 13),
    ("LOCALIDAD", ["LOCALIDAD"], 14),
    ("DIRECCION", ["DIRECCION", "DIRECCIÓN"], 15),
    ("ALTA", ["ALTA", "FECHA"], 16),
    ("DESCRIPCION", ["DESCRIPCION", "DESCRIPCIÓN"], 17),
    ("cel", ["CEL", "CELULAR", "TELEFONO", "TELÉFONO"], 18),
    ("ZONA PELIGROSA", ["ZONA PELIGROSA", "ZONA PELIG"], 19),
    ("FECHA", ["FECHA"], 20),
    ("ACC/LECT", ["ACC/LECT", "ACC/LECTU", "ACCLECTU", "ACC LECT"], 21),
    ("CODIGO", ["CODIGO", "CÓDIGO"], 22),
    ("HI", ["HI"], 23),
    ("HF", ["HF"], 24),
    ("PRECINTO Y OBSERVACION", ["PRECINTO Y OBSERVACION", "PRECINTO Y OBSERVACIÓN", "OBSERVACION", "OBSERVACIÓN"], 25),
]

EXCEL_TEMPLATE_TEXT_HEADERS = {
    "NOMOPE",
    "OBS",
    "CLIENTE",
    "MUNICIPIO",
    "LOCALIDAD",
    "DIRECCION",
    "DESCRIPCION",
    "ZONA PELIGROSA",
    "PRECINTO Y OBSERVACION",
}

EXCEL_ERROR_VALUES = {
    "#DIV/0!",
    "#ERROR!",
    "#N/A",
    "#NAME?",
    "#NULL!",
    "#NUM!",
    "#REF!",
    "#VALUE!",
}

EXCEL_DATE_HEADERS = {"ALTA", "FECHA"}
EXCEL_DECIMAL_HEADERS = {"COTA"}


def _normalize_header_name(text: object) -> str:
    return re.sub(r"[^A-Z0-9]+", " ", normalize(safe_text(text))).strip()


def _format_compact_number(text: str, max_decimals: int = 2) -> str:
    value = safe_text(text)
    if not re.fullmatch(r"-?\d+(?:\.\d+)?", value):
        return value
    if "." not in value:
        return value
    try:
        number = float(value)
    except Exception:
        return value
    if abs(number - round(number)) < 0.000001:
        return str(int(round(number)))
    if len(value.split(".", 1)[1]) <= max_decimals:
        return value
    return f"{number:.{max_decimals}f}".rstrip("0").rstrip(".")


def _excel_serial_to_datetime_text(text: str) -> str:
    value = safe_text(text)
    if not re.fullmatch(r"\d+(?:\.\d+)?", value):
        return value
    try:
        serial = float(value)
    except Exception:
        return value
    if not 20_000 <= serial <= 80_000:
        return value
    minutes = int(round(serial * 24 * 60))
    dt = datetime(1899, 12, 30) + timedelta(minutes=minutes)
    return f"{dt.day}/{dt.month:02d}/{dt.year} {dt.hour:02d}:{dt.minute:02d}"


def _professional_pdf_text(text: object) -> str:
    value = safe_text(text)
    if normalize(value) in EXCEL_ERROR_VALUES:
        return ""
    value = re.sub(r"[✓✔☑☒■□]", "", value)
    return _format_compact_number(value.strip())


def _format_template_value(label: str, value: object) -> str:
    header_key = normalize(label)
    raw_text = safe_text(value)
    if normalize(raw_text) in EXCEL_ERROR_VALUES:
        return ""
    raw_text = re.sub(r"[✓✔☑☒■□]", "", raw_text).strip()
    if header_key in EXCEL_DATE_HEADERS:
        return _excel_serial_to_datetime_text(raw_text)
    text = _professional_pdf_text(raw_text)
    if header_key in EXCEL_DECIMAL_HEADERS:
        return _format_compact_number(text, max_decimals=2)
    return text


def _pdf_paragraph(text: object, style: ParagraphStyle) -> Paragraph:
    return Paragraph(clean_xml(_professional_pdf_text(text)), style)


def _pdf_text_paragraph(text: object, style: ParagraphStyle) -> Paragraph:
    return Paragraph(clean_xml(safe_text(text)), style)


def _reportlab_color(value: str, fallback: str) -> colors.Color:
    try:
        return colors.HexColor(value or fallback)
    except Exception:
        return colors.HexColor(fallback)


def _reportlab_font(font_family: str, bold: bool = False) -> str:
    family = normalize(font_family)
    if "COURIER" in family:
        return "Courier-Bold" if bold else "Courier"
    if "TIMES" in family:
        return "Times-Bold" if bold else "Times-Roman"
    return "Helvetica-Bold" if bold else "Helvetica"


def _resolve_template_columns(headers: List[str], max_cols: int) -> List[Tuple[str, Optional[int]]]:
    limit = min(max_cols, len(headers))
    by_name: Dict[str, int] = {}
    for idx, header in enumerate(headers[:limit]):
        key = _normalize_header_name(header)
        if key and key not in by_name:
            by_name[key] = idx

    resolved: List[Tuple[str, Optional[int]]] = []
    for label, aliases, fallback_idx in EXCEL_TEMPLATE_COLUMNS:
        source_idx: Optional[int] = None
        for alias in aliases:
            key = _normalize_header_name(alias)
            if key in by_name:
                source_idx = by_name[key]
                break
        if source_idx is None and fallback_idx < limit:
            source_idx = fallback_idx
        resolved.append((label, source_idx))
    return resolved


def _helper_table(data: List[List[object]], col_widths: List[float], style: ParagraphStyle) -> Table:
    table_data = [[_pdf_paragraph(cell, style) for cell in row] for row in data]
    table = Table(table_data, colWidths=col_widths)
    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.35, colors.black),
        ("BOX", (0, 0), (-1, -1), 0.55, colors.black),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 1.2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 1.2),
        ("TOPPADDING", (0, 0), (-1, -1), 0.8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0.8),
    ]))
    return table


def _build_reference_tables(
    style: ParagraphStyle,
    note_style: ParagraphStyle,
    cargo3_exact: bool = False,
) -> Table:
    widths_cierres = [10, 75, 10, 75] if cargo3_exact else [10, 70, 10, 70]
    widths_imposibilidades = [18, 122] if cargo3_exact else [18, 132]
    widths_mensajes = [43, 52] if cargo3_exact else [50, 60]
    cierres_reaperturas = _helper_table([
        ["ACCION", "DESCRIPCION", "ACCION", "DESCRIPCION"],
        ["PARA CIERRES Y REVISIONES", "", "PARA REAPERTURAS", ""],
        ["500", "ANULACION DE CIERRE / REVISION", "", "SE REAPERTURA"],
        ["506", "CIERRE DRASTICO CON DISPOSITIVO INTRUSIVO", "611", "REAPERTURA SIMPLE / REAPERTURA BUNKER"],
        ["508", "SE ASEGURO CIERRE SIMPLE (SOLO EN REVISIONES)", "606", "REAPERTURA DRASTICA DE DISPOSITIVO INTRUSIVO"],
        ["511", "CIERRE SIMPLE / CIERRE TIPO BUNKER (SOLO EN CIERRES)", "618", "REAPERTURA DE TUERCA BOCINA Y CAMPANA"],
        ["518", "CIERRE CON TUERCA BOCINA Y CAMPANA (SOLO EN CIERRES)", "621", "SE ENCONTRO ABIERTO O VIGENTE"],
        ["521", "CON CIERRE SIMPLE", "633", "IMPEDIMENTO FISICO"],
        ["529", "CON RETIRO DE 1/2 METRO DE TUBERIA", "640", "OPOSICION A LA REAPERTURA"],
    ], widths_cierres, style)
    cierres_reaperturas.setStyle(TableStyle([
        ("SPAN", (0, 1), (1, 1)),
        ("SPAN", (2, 1), (3, 1)),
        ("ALIGN", (0, 0), (-1, 1), "CENTER"),
        ("LINEBELOW", (0, 0), (-1, 1), 0.55, colors.black),
    ]))

    imposibilidades = _helper_table([
        ["IMPOSIBILIDADES PARA CIERRES Y REVISIONES", ""],
        ["ACCION", "DESCRIPCION"],
        ["531", "ZONA PELIGROSA E INACCESIBLE"],
        ["533", "IMPEDIMENTO TEMPORAL / ANIMAL / OTROS"],
        ["534", "SUMINISTRO NO CORRESPONDE, SE ABASTECE DE OTRO SUMINISTRO"],
        ["539", "CON RECLAMO SACS"],
        ["540", "NO SE CERRO - PRESENTO FACTURA (DEUDA TOTAL)"],
        ["550", "SE OPUSO AL CIERRE"],
        ["561", "SERVICIO TAPADO CAJA VISIBLE"],
        ["562", "SERVICIO TAPADO CAJA NO VISIBLE"],
        ["571", "NO UBICADO EL PREDIO"],
        ["572", "NO UBICADO LA CONEXION"],
        ["580", "SERVICIO EN EL INTERIOR / CERCADO / REJAS"],
    ], widths_imposibilidades, style)
    imposibilidades.setStyle(TableStyle([
        ("SPAN", (0, 0), (1, 0)),
        ("ALIGN", (0, 0), (-1, 1), "CENTER"),
        ("LINEBELOW", (0, 0), (-1, 1), 0.55, colors.black),
    ]))

    mensajes = _helper_table([
        ["MENSAJE MOVIL", "DESCRIPCION"],
        ["CS", "CIERRE SIMPLE"],
        ["RS", "REAPERTURA SIMPLE"],
        ["CD", "CIERRE DRASTICO"],
        ["RD", "REAPERTURA DRASTICA"],
        ["VS", "REVISION SIMPLE"],
        ["CIA", "CIERRE SIMPLE"],
        ["CIERRE EQUIVOCADO", "ORDEN DE REAPERTURA"],
        ["RECLAMO", "ORDEN DE REAPERTURA"],
    ], widths_mensajes, style)

    right_block = [
        mensajes,
        Spacer(1, 8),
        _pdf_paragraph("EJEM:", note_style),
        _pdf_paragraph("RS/5T NIS: 4024929 ......", note_style),
    ]

    layout_widths = [64, 170, 273, 140, 26, 95] if cargo3_exact else [48, 160, 240, 150, 25, 110]
    layout = Table(
        [["", cierres_reaperturas, "", imposibilidades, "", right_block]],
        colWidths=layout_widths,
    )
    if cargo3_exact:
        layout.hAlign = "LEFT"
    layout.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return layout


def build_modern_pdf_for_group(
    output_pdf: Path,
    title: str,
    headers: List[str],
    rows: List[List[str]],
    source_name: str,
    selected_filter_label: str = "",
    max_cols: int = 26,
    template: Optional[PdfTemplateModel] = None,
):
    if template is None:
        raise ValueError("No se recibió la plantilla moderna guardada.")

    output_pdf.parent.mkdir(parents=True, exist_ok=True)

    page_size = landscape(letter)
    doc = SimpleDocTemplate(
        str(output_pdf),
        pagesize=page_size,
        leftMargin=8,
        rightMargin=8,
        topMargin=12,
        bottomMargin=12,
    )
    available_width = page_size[0] - doc.leftMargin - doc.rightMargin
    styles = getSampleStyleSheet()
    base_font = _reportlab_font(template.FontFamily)
    bold_font = _reportlab_font(template.FontFamily, bold=True)
    primary = _reportlab_color(template.PrimaryColor, "#0f172a")
    secondary = _reportlab_color(template.SecondaryColor, "#dbeafe")
    soft_line = colors.HexColor("#cbd5e1")

    company_style = ParagraphStyle(
        "ModernCompany",
        parent=styles["BodyText"],
        fontName=bold_font,
        fontSize=max(9, min(16, template.HeaderFontSize or 14)),
        leading=max(11, min(18, (template.HeaderFontSize or 14) + 2)),
        textColor=colors.white,
    )
    header_small = ParagraphStyle(
        "ModernHeaderSmall",
        parent=styles["BodyText"],
        fontName=base_font,
        fontSize=7,
        leading=8.5,
        textColor=colors.HexColor("#e5eefb"),
    )
    meta_style = ParagraphStyle(
        "ModernMeta",
        parent=styles["BodyText"],
        alignment=TA_LEFT,
        fontName=bold_font,
        fontSize=7,
        leading=8.5,
        textColor=colors.white,
    )
    title_style = ParagraphStyle(
        "ModernTitle",
        parent=styles["Title"],
        alignment=TA_CENTER,
        fontName=bold_font,
        fontSize=14,
        leading=16,
        textColor=primary,
        spaceAfter=2,
    )
    subtitle_style = ParagraphStyle(
        "ModernSubtitle",
        parent=styles["BodyText"],
        alignment=TA_CENTER,
        fontName=base_font,
        fontSize=8,
        leading=10,
        textColor=colors.HexColor("#334155"),
        spaceAfter=6,
    )
    info_style = ParagraphStyle(
        "ModernInfo",
        parent=styles["BodyText"],
        fontName=base_font,
        fontSize=7,
        leading=8.5,
        textColor=colors.HexColor("#1f2937"),
    )
    table_header_style = ParagraphStyle(
        "ModernTableHeader",
        parent=styles["BodyText"],
        alignment=TA_CENTER,
        fontName=bold_font,
        fontSize=3.65,
        leading=4.1,
        textColor=primary,
        wordWrap="CJK",
    )
    table_center_style = ParagraphStyle(
        "ModernTableCenter",
        parent=styles["BodyText"],
        alignment=TA_CENTER,
        fontName=base_font,
        fontSize=max(3.6, min(4.8, (template.BodyFontSize or 9) * 0.52)),
        leading=max(4.0, min(5.4, (template.BodyFontSize or 9) * 0.60)),
        textColor=colors.HexColor("#111827"),
        wordWrap="CJK",
    )
    table_left_style = ParagraphStyle(
        "ModernTableLeft",
        parent=table_center_style,
        alignment=TA_LEFT,
    )
    reference_style = ParagraphStyle(
        "ModernReference",
        parent=styles["BodyText"],
        alignment=TA_LEFT,
        fontName=bold_font,
        fontSize=3.75,
        leading=4.3,
        textColor=colors.HexColor("#111827"),
        wordWrap="CJK",
    )
    reference_note_style = ParagraphStyle(
        "ModernReferenceNote",
        parent=reference_style,
        fontSize=3.75,
        leading=4.45,
    )

    def logo_flowable():
        if template.ShowLogo and template.LogoPath and Path(template.LogoPath).exists():
            try:
                return RLImage(template.LogoPath, width=58, height=42, kind="proportional")
            except Exception:
                pass
        if template.ShowLogo:
            placeholder_style = ParagraphStyle(
                "ModernLogoPlaceholder",
                parent=meta_style,
                alignment=TA_CENTER,
                textColor=primary,
            )
            placeholder = Table([[_pdf_text_paragraph("LOGO", placeholder_style)]], colWidths=[58], rowHeights=[42])
            placeholder.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), colors.white),
                ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#dbeafe")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]))
            return placeholder
        return ""

    company_lines = [
        _pdf_text_paragraph(template.CompanyName or "RUTEO PDF", company_style),
        _pdf_text_paragraph(f"RUC: {template.Ruc}" if template.Ruc else "", header_small),
        _pdf_text_paragraph(" / ".join(x for x in [template.Area, template.ProjectName] if x), header_small),
    ]
    meta_lines = []
    if template.ShowDate:
        meta_lines.append(_pdf_text_paragraph(f"Fecha: {datetime.now().strftime('%d/%m/%Y')}", meta_style))
    if template.ShowTotalAssigned:
        meta_lines.append(_pdf_text_paragraph(f"TOTAL ASIGNADO: {len(rows)}", meta_style))
    if selected_filter_label:
        meta_lines.append(_pdf_text_paragraph(selected_filter_label, meta_style))
    if not meta_lines:
        meta_lines.append(_pdf_text_paragraph("Plantilla moderna", meta_style))

    logo_width = 72 if template.ShowLogo else 8
    header_table = Table(
        [[logo_flowable(), company_lines, meta_lines]],
        colWidths=[logo_width, available_width - logo_width - 178, 178],
        rowHeights=[64],
    )
    header_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), primary),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("LINEBELOW", (0, 0), (-1, -1), 4, secondary),
    ]))

    template_cols = _resolve_template_columns(headers, max_cols)
    table_data: List[List[Paragraph]] = [[_pdf_text_paragraph(label, table_header_style) for label, _idx in template_cols]]
    for row in rows:
        body_row = []
        for label, source_idx in template_cols:
            header_key = normalize(label)
            style = table_left_style if header_key in EXCEL_TEMPLATE_TEXT_HEADERS else table_center_style
            value = row[source_idx] if source_idx is not None and source_idx < len(row) else ""
            body_row.append(_pdf_text_paragraph(_format_template_value(label, value), style))
        table_data.append(body_row)

    col_widths = [
        EXCEL_TEMPLATE_COL_WIDTHS[idx] if idx < len(EXCEL_TEMPLATE_COL_WIDTHS) else 24.0
        for idx, _column in enumerate(template_cols)
    ]
    total_col_width = sum(col_widths) or available_width
    col_widths = [width * (available_width / total_col_width) for width in col_widths]
    data_table = Table(table_data, repeatRows=1, colWidths=col_widths)
    table_style = [
        ("BACKGROUND", (0, 0), (-1, 0), secondary),
        ("TEXTCOLOR", (0, 0), (-1, 0), primary),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.25, soft_line),
        ("BOX", (0, 0), (-1, -1), 0.6, primary),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
        ("LEFTPADDING", (0, 0), (-1, -1), 1.1),
        ("RIGHTPADDING", (0, 0), (-1, -1), 1.1),
        ("TOPPADDING", (0, 0), (-1, -1), 1.0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.0),
    ]
    for used_pos, (label, source_idx) in enumerate(template_cols):
        header_key = normalize(label)
        if header_key in EXCEL_TEMPLATE_TEXT_HEADERS:
            table_style.append(("ALIGN", (used_pos, 1), (used_pos, -1), "LEFT"))
        if header_key == "DESCRIPCION":
            for row_pos, row in enumerate(rows, start=1):
                text = normalize(row[source_idx] if source_idx is not None and source_idx < len(row) else "")
                if "REAPERTURA" in text:
                    table_style.extend([
                        ("BACKGROUND", (used_pos, row_pos), (used_pos, row_pos), colors.HexColor("#dcfce7")),
                        ("TEXTCOLOR", (used_pos, row_pos), (used_pos, row_pos), colors.HexColor("#166534")),
                    ])
    data_table.setStyle(TableStyle(table_style))

    info_text = []
    if template.ResponsibleName:
        info_text.append(f"Responsable: {template.ResponsibleName}")
    if source_name:
        info_text.append(f"Origen: {source_name}")
    if selected_filter_label:
        info_text.append(selected_filter_label)

    story = [
        header_table,
        Spacer(1, 7),
        _pdf_text_paragraph(template.ReportTitle or title or "CARGO DE TRABAJO", title_style),
    ]
    if template.Subtitle:
        story.append(_pdf_text_paragraph(template.Subtitle, subtitle_style))
    if info_text:
        story.extend([
            Table(
                [[_pdf_text_paragraph(" | ".join(info_text), info_style)]],
                colWidths=[available_width],
            ),
            Spacer(1, 7),
        ])
    story.append(data_table)
    if template.ObservationsText:
        story.extend([
            Spacer(1, 8),
            _pdf_text_paragraph(template.ObservationsText, info_style),
        ])
    reference_tables = _build_reference_tables(reference_style, reference_note_style)
    reference_tables.hAlign = "CENTER"
    story.extend([
        Spacer(1, 9),
        KeepTogether([reference_tables]),
    ])
    if template.ShowOperatorSignature or template.ShowSupervisorSignature:
        sig_cells = []
        if template.ShowOperatorSignature:
            sig_cells.append(_pdf_text_paragraph("____________________________\nFirma operario", info_style))
        if template.ShowSupervisorSignature:
            sig_cells.append(_pdf_text_paragraph("____________________________\nFirma supervisor", info_style))
        sig_table = Table([sig_cells], colWidths=[available_width / len(sig_cells)] * len(sig_cells))
        sig_table.setStyle(TableStyle([
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 18),
        ]))
        story.append(KeepTogether([Spacer(1, 10), sig_table]))

    def draw_footer(canvas, _doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 6)
        canvas.setFillColor(colors.HexColor("#64748b"))
        canvas.drawString(doc.leftMargin, 12, safe_text(source_name)[:100])
        canvas.drawRightString(page_size[0] - doc.rightMargin, 12, f"Pag. {canvas.getPageNumber()}")
        canvas.restoreState()

    doc.build(story, onFirstPage=draw_footer, onLaterPages=draw_footer)


def build_pdf_for_group(
    output_pdf: Path,
    title: str,
    headers: List[str],
    rows: List[List[str]],
    source_name: str,
    selected_filter_label: str = "",
    max_cols: int = 26,
    include_cargo2_header: bool = True,
    include_reference_tables: bool = True,
    page_size=None,
    excluded_template_columns: Optional[set[str]] = None,
    page_margins: Optional[Tuple[float, float, float, float]] = None,
    data_row_height: float = 39.0,
    cargo3_exact_layout: bool = False,
    max_table_width: Optional[float] = None,
):
    output_pdf.parent.mkdir(parents=True, exist_ok=True)

    page_size = page_size or landscape(letter)
    left_margin, right_margin, top_margin, bottom_margin = page_margins or (4.0, 4.0, 6.0, 6.0)
    doc = SimpleDocTemplate(
        str(output_pdf),
        pagesize=page_size,
        leftMargin=left_margin,
        rightMargin=right_margin,
        topMargin=top_margin,
        bottomMargin=bottom_margin,
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "ExcelPrintTitle",
        parent=styles["BodyText"],
        alignment=TA_CENTER,
        fontName="Helvetica-Bold",
        fontSize=7.6,
        leading=8.4,
        wordWrap="CJK",
    )
    meta_style = ParagraphStyle(
        "ExcelPrintMeta",
        parent=styles["BodyText"],
        alignment=TA_LEFT,
        fontName="Helvetica-Bold",
        fontSize=4.6,
        leading=5.2,
        wordWrap="CJK",
    )
    print_note_style = ParagraphStyle(
        "ExcelPrintNote",
        parent=styles["BodyText"],
        alignment=TA_LEFT,
        fontName="Helvetica-Bold",
        fontSize=4.25,
        leading=4.9,
        wordWrap="CJK",
    )
    header_style = ParagraphStyle(
        "ExcelHeaderCell",
        parent=styles["BodyText"],
        alignment=TA_CENTER,
        fontName="Helvetica-Bold",
        fontSize=3.35,
        leading=3.8,
        wordWrap="CJK",
    )
    body_center_style = ParagraphStyle(
        "ExcelBodyCenter",
        parent=styles["BodyText"],
        alignment=TA_CENTER,
        fontName="Helvetica-Bold",
        fontSize=4.15,
        leading=4.7,
        wordWrap="CJK",
    )
    body_left_style = ParagraphStyle(
        "ExcelBodyLeft",
        parent=styles["BodyText"],
        alignment=TA_LEFT,
        fontName="Helvetica-Bold",
        fontSize=4.15,
        leading=4.7,
        wordWrap="CJK",
    )
    cargo3_column_styles: Dict[str, ParagraphStyle] = {}
    if cargo3_exact_layout:
        cargo3_style_specs = {
            "NÂª": (5.3, False, TA_CENTER),
            "CUS": (6.6, True, TA_CENTER),
            "MZN": (6.6, True, TA_CENTER),
            "COD": (4.4, True, TA_CENTER),
            "NOMOPE": (4.4, False, TA_LEFT),
            "TURNO": (5.3, False, TA_CENTER),
            "OBS": (5.3, False, TA_LEFT),
            "NIS": (7.9, True, TA_CENTER),
            "OT": (5.0, True, TA_CENTER),
            "DIAM": (5.3, True, TA_CENTER),
            "MEDIDOR": (6.6, True, TA_CENTER),
            "COTA": (5.3, True, TA_CENTER),
            "CLIENTE": (6.1, True, TA_LEFT),
            "MUNICIPIO": (4.4, False, TA_LEFT),
            "LOCALIDAD": (5.0, False, TA_LEFT),
            "DIRECCION": (6.1, True, TA_LEFT),
            "ALTA": (5.3, False, TA_CENTER),
            "DESCRIPCION": (6.1, True, TA_LEFT),
            "CEL": (6.6, True, TA_CENTER),
            "ZONA PELIGROSA": (5.3, False, TA_CENTER),
            "ACC/LECT": (5.3, False, TA_CENTER),
            "HI": (5.3, False, TA_CENTER),
            "HF": (5.3, False, TA_CENTER),
            "PRECINTO Y OBSERVACION": (5.3, False, TA_CENTER),
        }
        for etiqueta, (tamano, negrita, alineacion) in cargo3_style_specs.items():
            cargo3_column_styles[normalize(etiqueta)] = ParagraphStyle(
                f"Cargo3_{normalize(etiqueta)}",
                parent=body_center_style,
                alignment=alineacion,
                fontName="Helvetica-Bold" if negrita else "Helvetica",
                fontSize=tamano,
                leading=tamano + 0.7,
                wordWrap="CJK",
            )
    helper_style = ParagraphStyle(
        "ExcelHelper",
        parent=styles["BodyText"],
        alignment=TA_LEFT,
        fontName="Helvetica-Bold",
        fontSize=3.75,
        leading=4.25,
        wordWrap="CJK",
    )
    note_style = ParagraphStyle(
        "ExcelNote",
        parent=helper_style,
        fontSize=3.75,
        leading=4.45,
    )
    summary_style = ParagraphStyle(
        "ExcelSummary",
        parent=helper_style,
        alignment=TA_CENTER,
        fontSize=5.8,
        leading=6.6,
    )

    # La plantilla profesional conserva la estructura A:X de la macro aunque el
    # archivo venga con columnas extra o encabezados ligeramente distintos.
    template_cols = _resolve_template_columns(headers, max_cols)
    if excluded_template_columns:
        excluded_normalized = {normalize(label) for label in excluded_template_columns}
        template_cols = [
            column for column in template_cols
            if normalize(column[0]) not in excluded_normalized
        ]

    table_data: List[List[Paragraph]] = []
    header_row = []
    for label, _source_idx in template_cols:
        if cargo3_exact_layout and normalize(label) == "OT":
            header_row.append(Paragraph(f"<u>{clean_xml(label)}</u>", ParagraphStyle(
                "Cargo3HeaderOT", parent=header_style, fontName="Helvetica",
            )))
        else:
            header_row.append(_pdf_paragraph(label, header_style))
    table_data.append(header_row)

    for row in rows:
        body_row = []
        for label, source_idx in template_cols:
            header_key = normalize(label)
            value = row[source_idx] if source_idx is not None and source_idx < len(row) else ""
            formatted_value = _format_template_value(label, value)
            if cargo3_exact_layout:
                style = cargo3_column_styles.get(header_key, body_center_style)
                if header_key == "OT":
                    body_row.append(Paragraph(f"<u>{clean_xml(formatted_value)}</u>", style))
                else:
                    body_row.append(_pdf_paragraph(formatted_value, style))
            else:
                style = body_left_style if header_key in EXCEL_TEMPLATE_TEXT_HEADERS else body_center_style
                body_row.append(_pdf_paragraph(formatted_value, style))
        table_data.append(body_row)

    available_width = page_size[0] - doc.leftMargin - doc.rightMargin
    requested_table_width = 810.0 if cargo3_exact_layout else max_table_width
    table_width = min(requested_table_width, available_width) if requested_table_width else available_width
    col_widths = [
        EXCEL_TEMPLATE_COL_WIDTHS[idx] if idx < len(EXCEL_TEMPLATE_COL_WIDTHS) else 24.0
        for idx, _column in enumerate(template_cols)
    ]
    total_col_width = sum(col_widths) or available_width
    scale = table_width / total_col_width
    col_widths = [w * scale for w in col_widths]
    row_heights = [6.8] + [data_row_height] * len(rows)

    table = Table(table_data, repeatRows=1, colWidths=col_widths, rowHeights=row_heights)
    style_commands = [
        ("TEXTCOLOR", (0, 0), (-1, -1), colors.black),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.black),
        ("BOX", (0, 0), (-1, -1), 0.55, colors.black),
        ("LEFTPADDING", (0, 0), (-1, -1), 1.0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 1.0),
        ("TOPPADDING", (0, 0), (-1, -1), 0.4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0.4),
    ]
    for used_pos, (label, source_idx) in enumerate(template_cols):
        header_key = normalize(label)
        if header_key in EXCEL_TEMPLATE_TEXT_HEADERS:
            style_commands.append(("ALIGN", (used_pos, 1), (used_pos, -1), "LEFT"))
        if header_key == "DESCRIPCION":
            for row_pos, row in enumerate(rows, start=1):
                text = normalize(row[source_idx] if source_idx is not None and source_idx < len(row) else "")
                if "REAPERTURA" in text:
                    style_commands.extend([
                        ("BACKGROUND", (used_pos, row_pos), (used_pos, row_pos), colors.HexColor("#C6EFCE")),
                        ("TEXTCOLOR", (used_pos, row_pos), (used_pos, row_pos), colors.HexColor("#008000")),
                    ])
    table.setStyle(TableStyle(style_commands))

    summary_table = Table(
        [[
            _pdf_paragraph(f"TOTAL ASIGNADO: {len(rows)}", summary_style),
        ]],
        colWidths=[190],
        rowHeights=[11],
    )
    summary_table.hAlign = "CENTER"
    summary_table.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))

    header_table = Table(
        [
            [
                "",
                _pdf_text_paragraph(EXCEL_PRINT_TITLE, title_style),
                "",
            ],
            [
                _pdf_text_paragraph("", meta_style),
                _pdf_text_paragraph("", meta_style),
                _pdf_text_paragraph(f"FECHA: {datetime.now().strftime('%d/%m/%Y')}     FIRMA: ________________________", meta_style),
            ],
            [_pdf_text_paragraph(EXCEL_PRINT_NOTES[0], print_note_style), "", ""],
            [_pdf_text_paragraph(EXCEL_PRINT_NOTES[1], print_note_style), "", ""],
            [_pdf_text_paragraph(EXCEL_PRINT_NOTES[2], print_note_style), "", ""],
        ],
        colWidths=[available_width * 0.12, available_width * 0.56, available_width * 0.32],
        rowHeights=[14, 10, 10, 10, 10],
    )
    header_table.setStyle(TableStyle([
        ("SPAN", (1, 0), (1, 0)),
        ("SPAN", (0, 2), (-1, 2)),
        ("SPAN", (0, 3), (-1, 3)),
        ("SPAN", (0, 4), (-1, 4)),
        ("ALIGN", (1, 0), (1, 0), "CENTER"),
        ("ALIGN", (2, 1), (2, 1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))

    story = []
    if include_cargo2_header:
        story.extend([header_table, Spacer(1, 4)])
    if cargo3_exact_layout:
        for inicio in range(0, len(rows), 14):
            fin = min(inicio + 14, len(rows))
            filas_pagina = rows[inicio:fin]
            datos_pagina = [table_data[0]] + table_data[inicio + 1:fin + 1]
            tabla_pagina = Table(
                datos_pagina,
                colWidths=col_widths,
                rowHeights=[6.8] + [data_row_height] * len(filas_pagina),
            )
            comandos_pagina = [
                ("TEXTCOLOR", (0, 0), (-1, -1), colors.black),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("GRID", (0, 0), (-1, -1), 0.35, colors.black),
                ("BOX", (0, 0), (-1, -1), 0.55, colors.black),
                ("LEFTPADDING", (0, 0), (-1, -1), 1.0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 1.0),
                ("TOPPADDING", (0, 0), (-1, -1), 0.4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0.4),
            ]
            for posicion, (etiqueta, indice_origen) in enumerate(template_cols):
                clave = normalize(etiqueta)
                if clave in EXCEL_TEMPLATE_TEXT_HEADERS:
                    comandos_pagina.append(("ALIGN", (posicion, 1), (posicion, -1), "LEFT"))
                if clave == "DESCRIPCION":
                    for posicion_fila, fila_origen in enumerate(filas_pagina, start=1):
                        texto = normalize(
                            fila_origen[indice_origen]
                            if indice_origen is not None and indice_origen < len(fila_origen)
                            else ""
                        )
                        if "REAPERTURA" in texto:
                            comandos_pagina.extend([
                                ("BACKGROUND", (posicion, posicion_fila), (posicion, posicion_fila), colors.HexColor("#C6EFCE")),
                                ("TEXTCOLOR", (posicion, posicion_fila), (posicion, posicion_fila), colors.HexColor("#008000")),
                            ])
            tabla_pagina.setStyle(TableStyle(comandos_pagina))
            if inicio:
                story.append(PageBreak())
            story.append(tabla_pagina)
    else:
        story.append(table)
    footer_items = [Spacer(1, 12 if cargo3_exact_layout else 7), summary_table]
    if include_reference_tables:
        footer_items.extend([
            Spacer(1, 12 if cargo3_exact_layout else 9),
            _build_reference_tables(helper_style, note_style, cargo3_exact_layout),
        ])
    story.append(KeepTogether(footer_items))
    doc.build(story)


def build_cargo3_pdf_for_group(
    output_pdf: Path,
    title: str,
    headers: List[str],
    rows: List[List[str]],
    source_name: str,
    selected_filter_label: str = "",
    max_cols: int = 26,
):
    build_pdf_for_group(
        output_pdf=output_pdf,
        title=title,
        headers=headers,
        rows=rows,
        source_name=source_name,
        selected_filter_label=selected_filter_label,
        max_cols=max_cols,
        include_cargo2_header=False,
        include_reference_tables=True,
        page_size=landscape(A4),
        excluded_template_columns={"FECHA", "CODIGO"},
        page_margins=(0.0, 0.0, 9.173, 0.0),
        data_row_height=37.8,
        cargo3_exact_layout=True,
    )


def clean_xml(text: str) -> str:
    text = safe_text(text)
    return (
        text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace("\n", "<br/>")
    )


class BusyOverlay(QWidget):
    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setObjectName("busyOverlay")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setWindowFlags(Qt.Widget)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setStyleSheet("""
            QWidget#busyOverlay {
                background: rgba(15, 23, 42, 145);
            }
            QFrame#busyCard {
                background: #ffffff;
                border: 1px solid #cbd5e1;
                border-radius: 10px;
            }
            QLabel#busyTitle {
                color: #0f172a;
                font-size: 16pt;
                font-weight: 800;
            }
            QLabel#busyMessage {
                color: #475569;
                font-size: 10pt;
            }
            QProgressBar {
                background: #e2e8f0;
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                min-height: 16px;
            }
            QProgressBar::chunk {
                background: #174ea6;
                border-radius: 5px;
            }
        """)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.addStretch(1)

        row = QHBoxLayout()
        row.addStretch(1)
        self.card = QFrame()
        self.card.setObjectName("busyCard")
        self.card.setFixedWidth(430)
        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(22, 20, 22, 20)
        card_layout.setSpacing(12)

        self.title_label = QLabel("")
        self.title_label.setObjectName("busyTitle")
        self.title_label.setAlignment(Qt.AlignCenter)
        self.message_label = QLabel("")
        self.message_label.setObjectName("busyMessage")
        self.message_label.setWordWrap(True)
        self.message_label.setAlignment(Qt.AlignCenter)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)

        card_layout.addWidget(self.title_label)
        card_layout.addWidget(self.message_label)
        card_layout.addWidget(self.progress)
        row.addWidget(self.card)
        row.addStretch(1)

        outer.addLayout(row)
        outer.addStretch(1)
        self.hide()

    def show_message(self, title: str, message: str, show_progress: bool = True):
        self.title_label.setText(title)
        self.message_label.setText(message)
        self.progress.setVisible(show_progress)
        self.setGeometry(self.parentWidget().rect())
        self.raise_()
        self.show()
        self.setFocus(Qt.OtherFocusReason)

    def update_message(self, message: str):
        self.message_label.setText(message)

    def mousePressEvent(self, event):
        event.accept()

    def mouseReleaseEvent(self, event):
        event.accept()

    def keyPressEvent(self, event):
        event.accept()


class GoogleSheetsCheckWorker(QObject):
    started = Signal()
    progress_message = Signal(str)
    finished = Signal(bool, object)
    error = Signal(str)

    def __init__(self, service: GoogleSheetsWorkbookSourceService, source_url: str, current_signature: str):
        super().__init__()
        self.service = service
        self.source_url = source_url
        self.current_signature = current_signature

    @Slot()
    def run(self):
        self.started.emit()
        try:
            self.progress_message.emit("Detectando cambios en Google Sheets, por favor espere...")
            workbook = self.service.load_workbook(self.source_url)
            has_changes = workbook_signature(workbook) != self.current_signature
        except Exception as exc:
            self.error.emit(str(exc))
            return
        self.finished.emit(has_changes, workbook)


class GoogleSheetsRefreshWorker(QObject):
    started = Signal()
    progress_message = Signal(str)
    finished = Signal(object)
    error = Signal(str)

    def __init__(self, service: GoogleSheetsWorkbookSourceService, source_url: str):
        super().__init__()
        self.service = service
        self.source_url = source_url

    @Slot()
    def run(self):
        self.started.emit()
        try:
            self.progress_message.emit("Actualizando información desde Google Sheets, por favor espere...")
            workbook = self.service.load_workbook(self.source_url)
        except Exception as exc:
            self.error.emit(str(exc))
            return
        self.finished.emit(workbook)


# =========================
# App PySide6
# =========================

class FondoInicioWidget(QWidget):
    """Lienzo que mantiene una imagen centrada y cubriendo toda la pantalla."""

    def __init__(self, image_path: Path, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._background = QPixmap(str(image_path))

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        if not self._background.isNull():
            fondo = self._background.scaled(
                self.size(),
                Qt.KeepAspectRatioByExpanding,
                Qt.SmoothTransformation,
            )
            x = (self.width() - fondo.width()) // 2
            y = (self.height() - fondo.height()) // 2
            painter.drawPixmap(x, y, fondo)


class VentanaRuteo(QMainWindow):
    TIEMPO_CIERRE_AUTOMATICO_MS = 5 * 60 * 60 * 1000
    TIEMPO_AVISO_CIERRE_MS = TIEMPO_CIERRE_AUTOMATICO_MS - (5 * 60 * 1000)
    HOJA_MACRO = "CARGO (3)"
    FILA_ENCABEZADO_MACRO = 1
    FILA_INICIO_MACRO = 2
    FILA_FIN_MACRO = 4001
    COL_INICIAL_MACRO = "A"
    COL_FINAL_MACRO = "Z"
    COL_AGRUPACION_MACRO = "E"
    COL_CARPETA_MACRO = "F"
    COL_ORDEN_CUS_MACRO = "B"
    COL_ORDEN_MANZANA_MACRO = "C"
    IGNORAR_FILAS_OCULTAS_MACRO = False
    CREAR_SUBCARPETA_MACRO = True

    senal_registro = Signal(str)
    senal_registro_txt = Signal(str)
    senal_progreso = Signal(int, int)
    senal_tarea_ok = Signal(object, object)
    senal_error = Signal(str, str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"Aplicativo CyR v{CURRENT_VERSION} - cierres y reaperturas")
        app_icon = load_app_icon()
        if not app_icon.isNull():
            self.setWindowIcon(app_icon)
        self.resize(980, 720)
        self.setMinimumSize(820, 560)

        self.sheets: List[SheetInfo] = []
        self.data: Optional[LoadedData] = None
        self.current_workbook: Optional[WorkbookModel] = None
        self.pending_google_workbook: Optional[WorkbookModel] = None
        self.filtered_rows_cache: List[List[str]] = []
        self.hoja_detectada = self.HOJA_MACRO
        self.pdf_template_service = PdfTemplateService()
        self.google_source_service = GoogleSheetsWorkbookSourceService()
        self._actualizando_tabs = False
        self.visualizador_libro_visible = True
        self.is_checking_changes = False
        self.is_refreshing_google = False
        self.is_busy = False
        self.busy_overlay: Optional[BusyOverlay] = None
        self._google_worker_thread: Optional[QThread] = None
        self._google_worker: Optional[QObject] = None
        self._pending_refresh_active_sheet = ""
        self._pending_refresh_print_sheet = ""
        self.ultima_revision_google = ""
        self.ultima_carga_google = ""
        self.google_changes_pending = False
        self.pdf_sort_mode = ""
        self.ruta_txt_cyr_sansys = ""
        self.ruta_carpeta_txt_cyr = ""
        self._cierre_automatico_en_curso = False

        self.senal_registro.connect(self._agregar_registro)
        self.senal_registro_txt.connect(self._agregar_registro_txt_cyr)
        self.senal_progreso.connect(self._actualizar_progreso)
        self.senal_tarea_ok.connect(self._finalizar_tarea)
        self.senal_error.connect(self._mostrar_error)

        self._construir_menu()
        self._construir_interfaz()
        self.write_log("Listo. Selecciona tu .xlsx/.xlsm exportado de Google Sheets o un CSV. Esta app NO usa Excel.")
        QTimer.singleShot(1800, self._buscar_actualizacion_al_iniciar)
        self._programar_cierre_por_inactividad()

    def _programar_cierre_por_inactividad(self):
        """Controla el cierre después de cinco horas sin actividad del usuario."""
        self.temporizador_aviso_inactividad = QTimer(self)
        self.temporizador_aviso_inactividad.setSingleShot(True)
        self.temporizador_aviso_inactividad.timeout.connect(self._avisar_cierre_automatico)

        self.temporizador_cierre_inactividad = QTimer(self)
        self.temporizador_cierre_inactividad.setSingleShot(True)
        self.temporizador_cierre_inactividad.timeout.connect(self._cerrar_por_tiempo_cumplido)

        aplicacion = QApplication.instance()
        if aplicacion:
            aplicacion.installEventFilter(self)
        self._reiniciar_temporizadores_inactividad()

    def _reiniciar_temporizadores_inactividad(self):
        if self._cierre_automatico_en_curso:
            return
        self.temporizador_aviso_inactividad.start(self.TIEMPO_AVISO_CIERRE_MS)
        self.temporizador_cierre_inactividad.start(self.TIEMPO_CIERRE_AUTOMATICO_MS)

    def eventFilter(self, objeto, evento):
        eventos_de_usuario = {
            QEvent.Type.KeyPress,
            QEvent.Type.MouseButtonPress,
            QEvent.Type.MouseButtonDblClick,
            QEvent.Type.MouseMove,
            QEvent.Type.Wheel,
            QEvent.Type.TouchBegin,
            QEvent.Type.TouchUpdate,
        }
        if evento.type() in eventos_de_usuario and hasattr(self, "temporizador_cierre_inactividad"):
            self._reiniciar_temporizadores_inactividad()
        return super().eventFilter(objeto, evento)

    def _avisar_cierre_automatico(self):
        QMessageBox.warning(
            self,
            "Cierre por inactividad",
            "Esta aplicación se cerrará automáticamente en 5 minutos por inactividad.\n\n"
            "Para continuar usándola, pulsa Aceptar o realiza cualquier acción.",
        )

    def _cerrar_por_tiempo_cumplido(self):
        self._cierre_automatico_en_curso = True
        self.write_log("Se cumplieron 5 horas sin actividad. Cerrando el aplicativo automáticamente.")
        self.close()

    def _construir_menu(self):
        self.accion_pagina_ruteo = QAction("Inicio", self)
        self.accion_pagina_txt_cyr = QAction("TXT CyR", self)
        self.accion_pagina_extractor = QAction("Extractor de órdenes", self)
        self.accion_pagina_depuracion_ot = QAction("Depuración OT", self)

        acciones_principales = (
            (self.accion_pagina_ruteo, "inicio"),
            (self.accion_pagina_txt_cyr, "texto"),
            (self.accion_pagina_extractor, "buscar"),
            (self.accion_pagina_depuracion_ot, "depurar"),
        )
        self.grupo_modulos = QActionGroup(self)
        self.grupo_modulos.setExclusive(True)
        for accion, nombre_icono in acciones_principales:
            accion.setCheckable(True)
            accion.setIcon(self._icono_navegacion(nombre_icono))
            self.grupo_modulos.addAction(accion)
        self.accion_pagina_ruteo.setChecked(True)

        self.accion_pagina_ruteo.triggered.connect(lambda _checked=False: self.mostrar_pagina_ruteo())
        self.accion_pagina_txt_cyr.triggered.connect(lambda _checked=False: self.mostrar_pagina_txt_cyr())
        self.accion_pagina_extractor.triggered.connect(lambda _checked=False: self.mostrar_pagina_extractor_ordenes())
        self.accion_pagina_depuracion_ot.triggered.connect(lambda _checked=False: self.mostrar_pagina_depuracion_ot())

        self.accion_importar_excel = QAction("Desde archivo Excel", self)
        self.accion_importar_google = QAction("Desde Google Sheets", self)
        self.accion_actualizar_google = QAction("Actualizar desde Google Sheets", self)
        self.accion_actualizar_google.setEnabled(False)
        self.accion_importar_excel.setIcon(self._icono("archivo"))
        self.accion_importar_google.setIcon(self._icono("nube"))
        self.accion_actualizar_google.setIcon(self._icono("actualizar"))

        self.accion_importar_excel.triggered.connect(lambda _checked=False: self.import_from_excel())
        self.accion_importar_google.triggered.connect(lambda _checked=False: self.import_from_google_sheets())
        self.accion_actualizar_google.triggered.connect(lambda _checked=False: self.refresh_from_google_sheets())

        menu_importar = QMenu("Importar", self)
        menu_importar.addAction(self.accion_importar_excel)
        menu_importar.addAction(self.accion_importar_google)
        menu_importar.addSeparator()
        menu_importar.addAction(self.accion_actualizar_google)

        self.accion_buscar_actualizaciones = QAction("Buscar actualizaciones", self)
        self.accion_acerca_de = QAction("Acerca de Aplicativo CyR", self)
        self.accion_buscar_actualizaciones.setIcon(self._icono("actualizar"))
        self.accion_buscar_actualizaciones.triggered.connect(lambda _checked=False: self.check_app_updates_thread())
        self.accion_acerca_de.triggered.connect(lambda _checked=False: self.show_about_dialog())
        menu_ayuda = QMenu("Ayuda", self)
        menu_ayuda.addAction(self.accion_buscar_actualizaciones)
        menu_ayuda.addAction(self.accion_acerca_de)

        self.barra_navegacion = QToolBar("Navegación principal", self)
        self.barra_navegacion.setObjectName("barraNavegacion")
        self.barra_navegacion.setMovable(False)
        self.barra_navegacion.setFloatable(False)
        self.barra_navegacion.setFixedHeight(38)
        self.barra_navegacion.setIconSize(QSize(15, 15))
        self.barra_navegacion.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        for accion, _nombre_icono in acciones_principales:
            self.barra_navegacion.addAction(accion)

        separador_flexible = QWidget(self.barra_navegacion)
        separador_flexible.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.barra_navegacion.addWidget(separador_flexible)

        self.boton_importar_navegacion = self._crear_boton_menu_navegacion(
            "Importar", "importar", menu_importar
        )
        self.boton_ayuda_navegacion = self._crear_boton_menu_navegacion(
            "Ayuda", "ayuda", menu_ayuda
        )
        self.boton_ayuda_navegacion.setObjectName("botonAyudaNavegacion")
        self.barra_navegacion.addWidget(self.boton_importar_navegacion)
        self.barra_navegacion.addWidget(self.boton_ayuda_navegacion)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, self.barra_navegacion)
        self.menuBar().setVisible(False)

    def _construir_interfaz(self):
        self._configurar_estilos()

        self.stack_paginas = QStackedWidget()
        self.setCentralWidget(self.stack_paginas)

        area_principal = QScrollArea()
        area_principal.setObjectName("areaPrincipal")
        area_principal.setWidgetResizable(True)
        area_principal.setFrameShape(QFrame.NoFrame)
        self.pagina_ruteo = area_principal
        self.stack_paginas.addWidget(self.pagina_ruteo)

        lienzo = FondoInicioWidget(resource_path("assets", "fondo_inicio_hd.png"))
        lienzo.setObjectName("fondoInicio")
        lienzo_layout = QHBoxLayout(lienzo)
        lienzo_layout.setContentsMargins(12, 10, 12, 10)
        lienzo_layout.setSpacing(0)
        area_principal.setWidget(lienzo)

        central = QWidget()
        central.setObjectName("contenedorCentral")
        central.setMinimumWidth(780)
        central.setMaximumWidth(1180)
        lienzo_layout.addStretch(1)
        lienzo_layout.addWidget(central, 4)
        lienzo_layout.addStretch(1)
        principal = QVBoxLayout(central)
        principal.setContentsMargins(0, 0, 0, 0)
        principal.setSpacing(10)

        encabezado = QFrame()
        encabezado.setObjectName("encabezado")
        encabezado_layout = QVBoxLayout(encabezado)
        encabezado_layout.setContentsMargins(14, 10, 14, 10)
        encabezado_layout.setSpacing(1)

        titulo = QLabel("Aplicativo CyR")
        titulo.setObjectName("titulo")
        subtitulo = QLabel("sistema lista para trabajar")
        subtitulo.setObjectName("subtitulo")
        encabezado_layout.addWidget(titulo)
        encabezado_layout.addWidget(subtitulo)
        principal.addWidget(encabezado)

        marco_archivo = self._crear_seccion(principal, "1. Archivo de datos")
        archivo_layout = QHBoxLayout(marco_archivo)
        archivo_layout.setContentsMargins(0, 0, 0, 0)
        archivo_layout.setSpacing(8)
        self.entrada_archivo = QLineEdit()
        self.entrada_archivo.setPlaceholderText("Selecciona un archivo .xlsx, .xlsm o .csv")
        archivo_layout.addWidget(self.entrada_archivo, 1)
        archivo_layout.addWidget(self._crear_boton("Seleccionar archivo", self.select_file, icono="archivo"))
        archivo_layout.addWidget(self._crear_boton("Desde Google Sheets", self.import_from_google_sheets, icono="nube"))
        archivo_layout.addWidget(self._crear_boton("Listar hojas", self.load_sheets, icono="tabla"))

        marco_libro = self._crear_seccion(principal, "Visualizador de libro")
        marco_libro.setObjectName("visualizadorLibro")
        libro_layout = QVBoxLayout(marco_libro)
        libro_layout.setContentsMargins(0, 0, 0, 0)
        libro_layout.setSpacing(8)

        fila_libro = QHBoxLayout()
        fila_libro.setContentsMargins(0, 0, 0, 0)
        fila_libro.setSpacing(8)
        self.etiqueta_libro = QLabel("Sin libro cargado")
        self.etiqueta_libro.setObjectName("estado")
        self.etiqueta_origen_libro = QLabel("Origen: --")
        self.etiqueta_origen_libro.setObjectName("chip")
        self.etiqueta_impresion_libro = QLabel("Impresión: --")
        self.etiqueta_impresion_libro.setObjectName("chipOk")
        self.boton_actualizar_google_visual = self._crear_boton("Actualizar", self.refresh_from_google_sheets, icono="actualizar")
        self.boton_actualizar_google_visual.setEnabled(False)
        self.boton_toggle_visualizador = self._crear_boton("Mostrar visualizador", self.toggle_workbook_viewer, icono="mostrar")
        self.boton_toggle_visualizador.setEnabled(False)
        fila_libro.addWidget(self.etiqueta_libro, 1)
        fila_libro.addWidget(self.etiqueta_origen_libro)
        fila_libro.addWidget(self.etiqueta_impresion_libro)
        fila_libro.addWidget(self.boton_actualizar_google_visual)
        fila_libro.addWidget(self.boton_toggle_visualizador)

        fila_estado_cambios = QHBoxLayout()
        fila_estado_cambios.setContentsMargins(0, 0, 0, 0)
        fila_estado_cambios.setSpacing(8)
        self.etiqueta_estado_cambios = QLabel("Estado: sin libro cargado")
        self.etiqueta_estado_cambios.setObjectName("estadoCambio")
        self.etiqueta_estado_cambios.setWordWrap(True)
        self.boton_verificar_cambios_google = self._crear_boton("Verificar cambios", self.check_google_sheets_changes, icono="actualizar")
        self.boton_verificar_cambios_google.setEnabled(False)
        self.boton_actualizar_cambio_google = self._crear_boton("Actualizar ahora", self.apply_pending_google_update, primario=True, icono="actualizar")
        self.boton_actualizar_cambio_google.setVisible(False)
        self.boton_actualizar_cambio_google.setEnabled(False)
        fila_estado_cambios.addWidget(self.etiqueta_estado_cambios, 1)
        fila_estado_cambios.addWidget(self.boton_verificar_cambios_google)
        fila_estado_cambios.addWidget(self.boton_actualizar_cambio_google)

        self.etiqueta_resumen_libro = QLabel("Carga un Excel, CSV o Google Sheets para ver las hojas del libro aquí.")
        self.etiqueta_resumen_libro.setObjectName("ayudaLibro")
        self.etiqueta_resumen_libro.setWordWrap(True)
        self.tabs_hojas = QTabWidget()
        self.tabs_hojas.setObjectName("tabsLibro")
        self.tabs_hojas.setMinimumHeight(300)
        self.tabs_hojas.setVisible(False)
        self.tabs_hojas.currentChanged.connect(self._on_sheet_tab_changed)
        libro_layout.addLayout(fila_libro)
        libro_layout.addLayout(fila_estado_cambios)
        libro_layout.addWidget(self.etiqueta_resumen_libro)
        libro_layout.addWidget(self.tabs_hojas)

        marco_configuracion = self._crear_seccion(principal, "2. Configuración")
        config_layout = QVBoxLayout(marco_configuracion)
        config_layout.setContentsMargins(0, 0, 0, 0)
        config_layout.setSpacing(8)
        texto_logica = QLabel(self._texto_logica_macro())
        texto_logica.setObjectName("resumenFijo")
        texto_logica.setWordWrap(True)
        fila_carga = QHBoxLayout()
        fila_carga.setContentsMargins(0, 0, 0, 0)
        fila_carga.setSpacing(8)
        self.boton_cargar = self._crear_boton("Cargar para PDFs", self.load_data_thread, primario=True, icono="cargar")
        self.boton_cargar.setMinimumWidth(155)
        fila_carga.addWidget(texto_logica, 1)
        fila_carga.addWidget(self.boton_cargar)
        config_layout.addLayout(fila_carga)

        marco_filtros = self._crear_seccion(principal, "3. Filtros")
        filtros_layout = QHBoxLayout(marco_filtros)
        filtros_layout.setContentsMargins(0, 0, 0, 0)
        filtros_layout.setSpacing(8)
        self.combo_col_filtro = self._crear_combo(editable=False)
        self.combo_col_filtro.setEnabled(False)
        self.combo_col_filtro.currentIndexChanged.connect(lambda _index: self.refresh_filter_values())
        self.combo_valor_filtro = self._crear_combo(["(TODOS)"], editable=False)
        self.combo_valor_filtro.currentIndexChanged.connect(lambda _index: self._on_filter_value_changed())
        self.combo_item = self._crear_combo(["(TODOS)"], editable=False)
        self.boton_orden_manzana = self._crear_boton(
            "Manzana A-Z",
            lambda _checked=False: self.set_pdf_sort_mode("MZN"),
            icono="orden",
        )
        self.boton_orden_cus = self._crear_boton(
            "CUS A-Z",
            lambda _checked=False: self.set_pdf_sort_mode("CUS"),
            icono="orden",
        )
        for boton in (self.boton_orden_manzana, self.boton_orden_cus):
            boton.setCheckable(True)
            boton.setEnabled(False)
            boton.setMinimumWidth(98)
        self.boton_orden_manzana.setToolTip("Ordena los registros del PDF por manzana de A a Z.")
        self.boton_orden_cus.setToolTip("Ordena los registros del PDF por CUS de A a Z.")
        orden_widget = QWidget()
        orden_layout = QHBoxLayout(orden_widget)
        orden_layout.setContentsMargins(0, 0, 0, 0)
        orden_layout.setSpacing(6)
        orden_layout.addWidget(self.boton_orden_manzana)
        orden_layout.addWidget(self.boton_orden_cus)
        filtros_layout.addWidget(self._crear_campo("Columna filtro", self.combo_col_filtro), 1)
        filtros_layout.addWidget(self._crear_campo("Valor filtro", self.combo_valor_filtro), 1)
        filtros_layout.addWidget(self._crear_campo("Solo operario/item", self.combo_item), 1)
        filtros_layout.addWidget(self._crear_campo("Orden PDF", orden_widget), 0)
        filtros_layout.addWidget(self._crear_boton("Actualizar valores", self.refresh_filter_values, icono="actualizar"), 0, Qt.AlignBottom)

        marco_salida = self._crear_seccion(principal, "4. Carpeta de salida")
        salida_layout = QHBoxLayout(marco_salida)
        salida_layout.setContentsMargins(0, 0, 0, 0)
        salida_layout.setSpacing(8)
        self.entrada_salida = QLineEdit(str(Path.home() / "Desktop" / "DRASTICOS BREÑA" / "OF"))
        salida_layout.addWidget(self.entrada_salida, 1)
        salida_layout.addWidget(self._crear_boton("Elegir carpeta", self.select_output_folder, icono="carpeta"))

        marco_acciones = self._crear_seccion(principal, "5. Generación")
        acciones_layout = QHBoxLayout(marco_acciones)
        acciones_layout.setContentsMargins(0, 0, 0, 0)
        acciones_layout.setSpacing(8)
        self.combo_plantilla_pdf = self._crear_combo(["Cargo (2)", "Cargo (3)", "Moderna"], editable=False)
        self.boton_generar = self._crear_boton("Generar PDFs", self.generate_pdfs_thread, primario=True, icono="pdf")
        self.boton_configurar_plantillas = self._crear_boton("Configurar plantillas PDF", self.open_pdf_template_editor, icono="plantilla")
        self.boton_abrir = self._crear_boton("Abrir carpeta", self.open_output_folder, icono="carpeta")
        self.progreso = QProgressBar()
        self.progreso.setRange(0, 0)
        self.progreso.setValue(0)
        self.progreso.setTextVisible(False)
        self.etiqueta_progreso = QLabel("0/0")
        self.etiqueta_progreso.setObjectName("estado")
        acciones_layout.addWidget(self._crear_campo("Plantilla PDF", self.combo_plantilla_pdf), 0)
        acciones_layout.addWidget(self.boton_generar)
        acciones_layout.addWidget(self.boton_configurar_plantillas)
        acciones_layout.addWidget(self.boton_abrir)
        acciones_layout.addWidget(self.progreso, 1)
        acciones_layout.addWidget(self.etiqueta_progreso)
        self._actualizar_progreso(0, 0)

        marco_registro = self._crear_seccion(principal, "Registro", expandir=True)
        registro_layout = QVBoxLayout(marco_registro)
        registro_layout.setContentsMargins(0, 0, 0, 0)
        self.registro = QTextEdit()
        self.registro.setObjectName("registro")
        self.registro.setReadOnly(True)
        registro_layout.addWidget(self.registro)
        principal.addStretch(0)
        self.pagina_txt_cyr = self._crear_pagina_txt_cyr()
        self.stack_paginas.addWidget(self.pagina_txt_cyr)
        self.pagina_extractor_ordenes = PaginaExtractorOrdenes(self)
        self.pagina_extractor_ordenes.senal_volver.connect(self.mostrar_pagina_ruteo)
        self.stack_paginas.addWidget(self.pagina_extractor_ordenes)
        self.pagina_depuracion_ot = PaginaDepuracionOT(self)
        self.stack_paginas.addWidget(self.pagina_depuracion_ot)
        self.stack_paginas.setCurrentWidget(self.pagina_ruteo)
        self.busy_overlay = BusyOverlay(self)

    def _crear_pagina_txt_cyr(self) -> QWidget:
        area = QScrollArea()
        area.setObjectName("areaPrincipal")
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.NoFrame)

        lienzo = FondoModulosWidget()
        lienzo_layout = QHBoxLayout(lienzo)
        lienzo_layout.setContentsMargins(12, 10, 12, 10)
        lienzo_layout.setSpacing(0)
        area.setWidget(lienzo)

        central = QWidget()
        central.setObjectName("contenedorCentral")
        central.setMinimumWidth(780)
        central.setMaximumWidth(980)
        lienzo_layout.addStretch(1)
        lienzo_layout.addWidget(central, 4)
        lienzo_layout.addStretch(1)

        principal = QVBoxLayout(central)
        principal.setContentsMargins(0, 0, 0, 0)
        principal.setSpacing(10)

        encabezado = QFrame()
        encabezado.setObjectName("encabezadoTxtCyr")
        encabezado_layout = QVBoxLayout(encabezado)
        encabezado_layout.setContentsMargins(14, 10, 14, 10)
        encabezado_layout.setSpacing(1)
        titulo = QLabel("TXT CyR")
        titulo.setObjectName("titulo")
        subtitulo = QLabel("Panel operativo para procesar TXT SANSYS, generar SYSACO y revisar errores.")
        subtitulo.setObjectName("subtitulo")
        subtitulo.setWordWrap(True)
        encabezado_layout.addWidget(titulo)
        encabezado_layout.addWidget(subtitulo)
        principal.addWidget(encabezado)

        marco_acciones = self._crear_seccion(principal, "Operacion TXT CyR")
        acciones_layout = QVBoxLayout(marco_acciones)
        acciones_layout.setContentsMargins(0, 0, 0, 0)
        acciones_layout.setSpacing(8)

        fila_acciones = QHBoxLayout()
        fila_acciones.setContentsMargins(0, 0, 0, 0)
        fila_acciones.setSpacing(8)
        self.boton_cargar_txt_cyr = self._crear_boton("Cargar TXT SANSYS", self.seleccionar_archivo_txt_cyr, icono="archivo")
        self.boton_generar_txt_cyr = self._crear_boton("Generar TXT CyR", self.generar_txt_cyr_en_hilo, primario=True, icono="tabla")
        self.boton_volver_pdf_txt_cyr = self._crear_boton("Volver", self.mostrar_pagina_ruteo, icono="mostrar")
        self.etiqueta_txt_cyr_archivo = QLabel("Archivo cargado: --")
        self.etiqueta_txt_cyr_archivo.setObjectName("estado")
        self.etiqueta_txt_cyr_archivo.setWordWrap(True)
        fila_acciones.addWidget(self.boton_cargar_txt_cyr)
        fila_acciones.addWidget(self.boton_generar_txt_cyr)
        fila_acciones.addWidget(self.boton_volver_pdf_txt_cyr)
        fila_acciones.addWidget(self.etiqueta_txt_cyr_archivo, 1)

        fila_carpeta = QHBoxLayout()
        fila_carpeta.setContentsMargins(0, 0, 0, 0)
        fila_carpeta.setSpacing(8)
        self.entrada_carpeta_txt_cyr = QLineEdit()
        self.entrada_carpeta_txt_cyr.setPlaceholderText("Carpeta de salida TXT")
        self.boton_elegir_carpeta_txt_cyr = self._crear_boton("Elegir carpeta TXT", self.seleccionar_carpeta_txt_cyr, icono="carpeta")
        fila_carpeta.addWidget(self._crear_campo("Carpeta de salida TXT", self.entrada_carpeta_txt_cyr), 1)
        fila_carpeta.addWidget(self.boton_elegir_carpeta_txt_cyr, 0, Qt.AlignBottom)

        acciones_layout.addLayout(fila_acciones)
        acciones_layout.addLayout(fila_carpeta)

        marco_resumen = self._crear_seccion(principal, "Estado del proceso")
        resumen_layout = QVBoxLayout(marco_resumen)
        resumen_layout.setContentsMargins(0, 0, 0, 0)
        self.resumen_txt_cyr = QTextEdit()
        self.resumen_txt_cyr.setObjectName("resumenTxtCyr")
        self.resumen_txt_cyr.setReadOnly(True)
        self.resumen_txt_cyr.setMinimumHeight(120)
        self.resumen_txt_cyr.setMaximumHeight(135)
        self.resumen_txt_cyr.setPlainText(self._texto_resumen_txt_cyr_inicial())
        resumen_layout.addWidget(self.resumen_txt_cyr)

        marco_registro = self._crear_seccion(principal, "Consola de proceso")
        registro_layout = QVBoxLayout(marco_registro)
        registro_layout.setContentsMargins(0, 0, 0, 0)
        self.registro_txt_cyr = QTextEdit()
        self.registro_txt_cyr.setObjectName("registroTxtCyr")
        self.registro_txt_cyr.setReadOnly(True)
        self.registro_txt_cyr.setMinimumHeight(95)
        self.registro_txt_cyr.setMaximumHeight(110)
        self.registro_txt_cyr.setPlainText("Los mensajes del proceso apareceran aqui durante la generacion.")
        registro_layout.addWidget(self.registro_txt_cyr)

        principal.addStretch(0)
        return area

    def _texto_resumen_txt_cyr_inicial(self) -> str:
        return (
            "Archivo cargado: --\n"
            "Estado: sin proceso\n"
            "Total registros: 0\n"
            "Generados: 0\n"
            "Encontrados: 0\n"
            "Operarios no encontrados: 0\n"
            "Errores: 0\n"
            "Ruta de archivos generados: --"
        )

    def _configurar_estilos(self):
        self.setStyleSheet("""
            QMainWindow {
                background: #edf2f7;
            }
            QScrollArea#areaPrincipal {
                background: #edf2f7;
                border: none;
            }
            QWidget#contenedorCentral {
                background: transparent;
            }
            QToolBar#barraNavegacion {
                background: #174ea6;
                border-bottom: 2px solid #0f3f86;
                spacing: 2px;
                padding: 1px 7px;
            }
            QToolBar#barraNavegacion QToolButton {
                color: #ffffff;
                background: transparent;
                border: none;
                border-bottom: 2px solid transparent;
                border-radius: 4px;
                padding: 2px 8px;
                font-weight: 600;
                min-height: 18px;
            }
            QToolBar#barraNavegacion QToolButton:hover {
                background: #2d63b4;
            }
            QToolBar#barraNavegacion QToolButton:pressed {
                background: #0f3f86;
            }
            QToolBar#barraNavegacion QToolButton:checked {
                background: #123f82;
                border-bottom: 2px solid #ffffff;
            }
            QToolBar#barraNavegacion QToolButton::menu-indicator {
                subcontrol-origin: padding;
                subcontrol-position: right center;
                right: 4px;
            }
            QMenu {
                background: #ffffff;
                border: 1px solid #cbd5e1;
                padding: 5px;
            }
            QMenu::item {
                padding: 6px 22px 6px 22px;
                border-radius: 5px;
            }
            QMenu::item:selected {
                background: #e8f0fe;
                color: #174ea6;
            }
            QWidget {
                color: #0f172a;
                font-family: "Segoe UI";
                font-size: 9.5pt;
            }
            QFrame#encabezado {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #174ea6, stop:1 #0f766e);
                border: 1px solid #155e75;
                border-radius: 8px;
            }
            QLabel#titulo {
                color: #ffffff;
                font-size: 20px;
                font-weight: 700;
            }
            QLabel#subtitulo {
                color: #dbeafe;
            }
            QFrame#encabezadoTxtCyr {
                background: #38bdf8;
                border: 1px solid #0284c7;
                border-radius: 8px;
            }
            QFrame#encabezadoTxtCyr QLabel#titulo {
                color: #0f172a;
                font-size: 20px;
                font-weight: 700;
            }
            QFrame#encabezadoTxtCyr QLabel#subtitulo {
                color: #0f172a;
            }
            QFrame#panel {
                background: #ffffff;
                border: 1px solid #d7dee8;
                border-radius: 8px;
            }
            QFrame#panel QLabel {
                background: transparent;
                border: none;
            }
            QLabel#tituloSeccion {
                color: #1f2937;
                font-weight: 700;
                font-size: 10pt;
            }
            QLabel#etiqueta, QLabel#estado {
                color: #475569;
            }
            QLabel#chip, QLabel#chipOk {
                border-radius: 10px;
                padding: 4px 9px;
                font-size: 8.7pt;
                font-weight: 600;
            }
            QLabel#chip {
                color: #334155;
                background: #eef2ff;
                border: 1px solid #c7d2fe;
            }
            QLabel#chipOk {
                color: #14532d;
                background: #dcfce7;
                border: 1px solid #86efac;
            }
            QLabel#ayudaLibro {
                color: #64748b;
                background: #f8fafc;
                border: 1px solid #e2e8f0;
                border-radius: 6px;
                padding: 7px 9px;
            }
            QLabel#estadoCambio {
                color: #475569;
                background: #f8fafc;
                border: 1px solid #e2e8f0;
                border-radius: 6px;
                padding: 7px 9px;
                font-weight: 600;
            }
            QLabel#etiquetaCampo {
                color: #334155;
                font-size: 9pt;
            }
            QLabel#resumenFijo {
                color: #334155;
                background: #f8fafc;
                border: 1px solid #dbe3ee;
                border-radius: 6px;
                padding: 7px 9px;
            }
            QLineEdit, QComboBox, QSpinBox {
                background: #ffffff;
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                padding: 4px 6px;
                min-height: 20px;
            }
            QLineEdit:focus, QComboBox:focus, QSpinBox:focus {
                border: 1px solid #2563eb;
            }
            QPushButton {
                background: #f8fafc;
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                padding: 5px 11px;
            }
            QPushButton:hover {
                background: #eef6ff;
                border-color: #93c5fd;
            }
            QPushButton:checked {
                background: #0f766e;
                color: #ffffff;
                border-color: #0f766e;
                font-weight: 700;
            }
            QPushButton:disabled {
                color: #94a3b8;
                background: #e2e8f0;
                border-color: #cbd5e1;
            }
            QPushButton#botonPrimario {
                background: #174ea6;
                color: #ffffff;
                border: 1px solid #174ea6;
                font-weight: 700;
            }
            QPushButton#botonPrimario:hover {
                background: #0f766e;
                border-color: #0f766e;
            }
            QTabWidget#tabsLibro::pane {
                border: 1px solid #d7dee8;
                border-radius: 8px;
                background: #ffffff;
                top: -1px;
            }
            QTabWidget#tabsLibro QTabBar::tab {
                background: #f8fafc;
                border: 1px solid #d7dee8;
                border-bottom: none;
                padding: 7px 12px;
                margin-right: 2px;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                color: #475569;
            }
            QTabWidget#tabsLibro QTabBar::tab:selected {
                background: #ffffff;
                color: #174ea6;
                font-weight: 700;
            }
            QTableWidget#tablaLibro {
                background: #ffffff;
                alternate-background-color: #f8fafc;
                border: none;
                gridline-color: #e2e8f0;
                selection-background-color: #dbeafe;
                selection-color: #0f172a;
            }
            QTableWidget#tablaLibro::item {
                padding: 4px 6px;
            }
            QHeaderView::section {
                background: #1f2937;
                color: #ffffff;
                border: none;
                border-right: 1px solid #334155;
                padding: 6px 8px;
                font-weight: 700;
            }
            QProgressBar {
                background: #e2e8f0;
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                min-height: 16px;
            }
            QProgressBar::chunk {
                background: #16a34a;
                border-radius: 5px;
            }
            QTextEdit#resumenTxtCyr {
                background: #f8fafc;
                color: #334155;
                border: 1px solid #dbe3ee;
                border-radius: 6px;
                font-family: "Segoe UI";
                font-size: 9.5pt;
                padding: 8px;
            }
            QTextEdit#registro {
                background: #0f172a;
                color: #e2e8f0;
                border: 1px solid #1e293b;
                border-radius: 6px;
                font-family: Consolas;
                font-size: 9pt;
                padding: 8px;
            }
            QTextEdit#registroTxtCyr {
                background: #ffffff;
                color: #0f172a;
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                font-family: Consolas;
                font-size: 9pt;
                padding: 8px;
            }
        """)

    def _crear_seccion(self, principal: QVBoxLayout, titulo: str, expandir: bool = False) -> QWidget:
        panel = QFrame()
        panel.setObjectName("panel")
        panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding if expandir else QSizePolicy.Minimum)
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(12, 10, 12, 12)
        panel_layout.setSpacing(8)

        etiqueta_titulo = QLabel(titulo)
        etiqueta_titulo.setObjectName("tituloSeccion")
        cuerpo = QWidget()
        cuerpo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding if expandir else QSizePolicy.Minimum)

        panel_layout.addWidget(etiqueta_titulo)
        panel_layout.addWidget(cuerpo, 1 if expandir else 0)
        principal.addWidget(panel, 1 if expandir else 0)
        return cuerpo

    def _texto_logica_macro(self) -> str:
        return (
            f"Lógica fija de macro (no modificable desde la ventana): hoja {self.HOJA_MACRO} | "
            f"rango {self.COL_INICIAL_MACRO}{self.FILA_ENCABEZADO_MACRO}:"
            f"{self.COL_FINAL_MACRO}{self.FILA_FIN_MACRO} | "
            f"datos desde fila {self.FILA_INICIO_MACRO} | "
            f"agrupa por columna {self.COL_AGRUPACION_MACRO} | "
            f"carpeta por columna {self.COL_CARPETA_MACRO}."
        )

    def _crear_campo(self, etiqueta: str, widget: QWidget) -> QWidget:
        campo = QWidget()
        campo.setObjectName("campo")
        campo.setMinimumHeight(58)
        layout = QVBoxLayout(campo)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)

        label = QLabel(etiqueta)
        label.setObjectName("etiquetaCampo")
        label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        layout.addWidget(label)
        layout.addWidget(widget)
        return campo

    def _icono(self, nombre: str):
        mapa = {
            "archivo": QStyle.StandardPixmap.SP_FileIcon,
            "nube": QStyle.StandardPixmap.SP_DriveNetIcon,
            "actualizar": QStyle.StandardPixmap.SP_BrowserReload,
            "tabla": QStyle.StandardPixmap.SP_FileDialogDetailedView,
            "cargar": QStyle.StandardPixmap.SP_DialogApplyButton,
            "carpeta": QStyle.StandardPixmap.SP_DirOpenIcon,
            "pdf": QStyle.StandardPixmap.SP_FileIcon,
            "plantilla": QStyle.StandardPixmap.SP_FileDialogContentsView,
            "ocultar": QStyle.StandardPixmap.SP_ArrowUp,
            "mostrar": QStyle.StandardPixmap.SP_ArrowDown,
            "orden": QStyle.StandardPixmap.SP_ArrowDown,
        }
        return self.style().standardIcon(mapa.get(nombre, QStyle.StandardPixmap.SP_FileIcon))

    def _icono_navegacion(self, nombre: str) -> QIcon:
        """Genera iconos compactos con la tipografía de Windows 10/11."""
        glifos = {
            "inicio": "\ue80f",
            "importar": "\ue8b5",
            "texto": "\ue8a5",
            "buscar": "\ue721",
            "depurar": "\ue71c",
            "ayuda": "\ue897",
        }
        if not hasattr(self, "_familia_iconos_navegacion"):
            self._familia_iconos_navegacion = ""
            for archivo_fuente in (
                Path("C:/Windows/Fonts/SegoeIcons.ttf"),
                Path("C:/Windows/Fonts/segmdl2.ttf"),
            ):
                if not archivo_fuente.exists():
                    continue
                identificador = QFontDatabase.addApplicationFont(str(archivo_fuente))
                familias = QFontDatabase.applicationFontFamilies(identificador)
                if familias:
                    self._familia_iconos_navegacion = familias[0]
                    break
        if not self._familia_iconos_navegacion:
            return self._icono("archivo")

        fuente = QFont(self._familia_iconos_navegacion)
        fuente.setPointSizeF(9.5)
        imagen = QPixmap(17, 17)
        imagen.fill(Qt.GlobalColor.transparent)
        pintor = QPainter(imagen)
        pintor.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        pintor.setFont(fuente)
        pintor.setPen(QColor("#ffffff"))
        pintor.drawText(imagen.rect(), Qt.AlignmentFlag.AlignCenter, glifos[nombre])
        pintor.end()
        return QIcon(imagen)

    def _crear_boton_menu_navegacion(self, texto: str, icono: str, menu: QMenu) -> QToolButton:
        boton = QToolButton(self)
        boton.setText(texto)
        boton.setIcon(self._icono_navegacion(icono))
        boton.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        boton.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        boton.setMenu(menu)
        return boton

    def _marcar_modulo_activo(self, accion_activa: QAction):
        accion_activa.setChecked(True)

    def _restaurar_modulo_activo(self):
        if not hasattr(self, "stack_paginas"):
            return
        pagina_actual = self.stack_paginas.currentWidget()
        mapa_paginas = (
            (getattr(self, "pagina_ruteo", None), self.accion_pagina_ruteo),
            (getattr(self, "pagina_txt_cyr", None), self.accion_pagina_txt_cyr),
            (getattr(self, "pagina_extractor_ordenes", None), self.accion_pagina_extractor),
            (getattr(self, "pagina_depuracion_ot", None), self.accion_pagina_depuracion_ot),
        )
        for pagina, accion in mapa_paginas:
            if pagina is pagina_actual:
                self._marcar_modulo_activo(accion)
                return

    def _crear_boton(self, texto: str, accion, primario: bool = False, icono: str = "") -> QPushButton:
        boton = QPushButton(texto)
        boton.setMinimumHeight(32)
        if icono:
            boton.setIcon(self._icono(icono))
        if primario:
            boton.setObjectName("botonPrimario")
        boton.clicked.connect(accion)
        return boton

    def _crear_combo(self, valores: Optional[List[str]] = None, editable: bool = False) -> QComboBox:
        combo = QComboBox()
        combo.setEditable(editable)
        combo.setMinimumWidth(150)
        combo.setFixedHeight(32)
        if valores:
            combo.addItems(valores)
        return combo

    def _crear_spin(self, valor: int) -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(1, 1_000_000)
        spin.setValue(valor)
        spin.setMinimumWidth(90)
        spin.setFixedHeight(32)
        return spin

    def _crear_entrada_corta(self, valor: str) -> QLineEdit:
        entrada = QLineEdit(valor)
        entrada.setMinimumWidth(90)
        entrada.setFixedHeight(32)
        return entrada

    def _ubicar_campo(self, grid: QGridLayout, etiqueta: str, widget: QWidget, fila: int, columna: int, expandir: bool = False):
        label = QLabel(etiqueta)
        label.setObjectName("etiqueta")
        label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        grid.addWidget(label, fila, columna)
        if expandir:
            widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        grid.addWidget(widget, fila, columna + 1)

    def _llenar_combo(self, combo: QComboBox, valores: List[str], actual: str = ""):
        actual = safe_text(actual) or combo.currentText()
        combo.blockSignals(True)
        combo.clear()
        combo.addItems(valores)
        if actual and actual in valores:
            combo.setCurrentText(actual)
        elif valores:
            combo.setCurrentIndex(0)
        else:
            combo.setEditText("")
        combo.blockSignals(False)

    def write_log(self, msg: str):
        self.senal_registro.emit(msg)

    @Slot(str)
    def _agregar_registro(self, msg: str):
        self.registro.append(msg)
        barra = self.registro.verticalScrollBar()
        barra.setValue(barra.maximum())

    @Slot(str)
    def _agregar_registro_txt_cyr(self, msg: str):
        if not hasattr(self, "registro_txt_cyr"):
            return
        self.registro_txt_cyr.append(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")
        barra = self.registro_txt_cyr.verticalScrollBar()
        barra.setValue(barra.maximum())

    @Slot(int, int)
    def _actualizar_progreso(self, valor: int, total: int):
        total = max(0, total)
        if total == 0:
            self.progreso.setRange(0, 1)
            self.progreso.setValue(0)
            self.etiqueta_progreso.setText("0/0")
            return
        self.progreso.setRange(0, total)
        self.progreso.setValue(valor)
        self.etiqueta_progreso.setText(f"{valor}/{total}")

    def show_busy_overlay(self, title: str, message: str, show_progress: bool = True):
        self.is_busy = True
        self._set_main_controls_enabled(False)
        if self.busy_overlay:
            self.busy_overlay.show_message(title, message, show_progress=show_progress)

    def update_busy_overlay(self, message: str):
        if self.busy_overlay:
            self.busy_overlay.update_message(message)

    def hide_busy_overlay(self):
        if self.busy_overlay:
            self.busy_overlay.hide()
        self.is_busy = False
        self._set_main_controls_enabled(True)

    def _set_main_controls_enabled(self, enabled: bool):
        if self.centralWidget():
            self.centralWidget().setEnabled(enabled)
        self.accion_importar_excel.setEnabled(enabled)
        self.accion_importar_google.setEnabled(enabled)
        if hasattr(self, "accion_pagina_ruteo"):
            self.accion_pagina_ruteo.setEnabled(enabled)
        if hasattr(self, "accion_pagina_txt_cyr"):
            self.accion_pagina_txt_cyr.setEnabled(enabled)
        if hasattr(self, "accion_pagina_depuracion_ot"):
            self.accion_pagina_depuracion_ot.setEnabled(enabled)
        self.accion_actualizar_google.setEnabled(
            enabled and bool(self.current_workbook and self.current_workbook.source_type == "GoogleSheets")
        )
        if enabled and hasattr(self, "boton_actualizar_google_visual"):
            is_google = bool(self.current_workbook and self.current_workbook.source_type == "GoogleSheets")
            self.boton_actualizar_google_visual.setEnabled(is_google)
            self.boton_verificar_cambios_google.setEnabled(is_google)
            self.boton_actualizar_cambio_google.setEnabled(is_google and self.boton_actualizar_cambio_google.isVisible())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.busy_overlay and self.busy_overlay.isVisible():
            self.busy_overlay.setGeometry(self.rect())

    def closeEvent(self, event):
        if self.is_busy and not self._cierre_automatico_en_curso:
            QMessageBox.information(self, "Proceso en ejecución", "Espere a que termine la actualización de datos.")
            event.ignore()
            return
        super().closeEvent(event)

    def import_from_excel(self):
        if self.select_file():
            self.load_data_thread()

    def _buscar_actualizacion_al_iniciar(self):
        """Busca una versión nueva y solo avisa cuando realmente existe."""
        self.check_app_updates_thread(automatico=True)

    def check_app_updates_thread(self, automatico: bool = False):
        if self.is_busy:
            if not automatico:
                QMessageBox.information(self, "Proceso en ejecución", "Ya hay un proceso en ejecución.")
            return
        self.accion_buscar_actualizaciones.setEnabled(False)
        if not automatico:
            self.write_log("Buscando actualizaciones en GitHub...")

        def consultar_actualizacion():
            try:
                return check_for_updates()
            except Exception as exc:
                return {"error": str(exc)}

        self._run_thread(
            consultar_actualizacion,
            lambda info: self._finalizar_busqueda_actualizaciones(info, automatico),
        )

    def _finalizar_busqueda_actualizaciones(self, info: Dict[str, object], automatico: bool = False):
        self.accion_buscar_actualizaciones.setEnabled(True)
        if info.get("error"):
            if not automatico:
                QMessageBox.warning(self, "Actualizaciones", str(info["error"]))
            return
        if not bool(info.get("configured")):
            if not automatico:
                QMessageBox.information(self, "Actualizaciones", str(info.get("message")))
            return
        if bool(info.get("update_available")):
            respuesta = QMessageBox.question(
                self,
                "Actualización disponible",
                f"Versión actual: {info.get('current_version')}\n"
                f"Nueva versión: {info.get('latest_version')}\n\n"
                "¿Deseas descargarla e instalarla automáticamente?\n\n"
                "El aplicativo se cerrará y volverá a abrir al terminar.",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes,
            )
            if respuesta == QMessageBox.Yes:
                if not info.get("download_url"):
                    QMessageBox.warning(
                        self,
                        "Actualización",
                        "La publicación nueva no contiene el ZIP del aplicativo.",
                    )
                    return
                self._descargar_actualizacion(info)
            return
        if automatico:
            return
        QMessageBox.information(
            self,
            "Actualizaciones",
            f"Ya tienes la última versión.\nVersión actual: {info.get('current_version')}",
        )

    def _descargar_actualizacion(self, info: Dict[str, object]):
        if not getattr(sys, "frozen", False):
            QMessageBox.information(
                self,
                "Actualización",
                "La instalación automática funciona desde el EXE compilado.",
            )
            return

        self.accion_buscar_actualizaciones.setEnabled(False)
        self.show_busy_overlay(
            "Actualizando aplicativo",
            "Descargando y verificando la nueva versión...",
            show_progress=False,
        )

        def preparar():
            ejecutable = Path(sys.executable).resolve()
            return preparar_actualizacion_automatica(
                str(info["download_url"]),
                ejecutable.parent,
                ejecutable.name,
            )

        self._run_thread(preparar, self._iniciar_instalacion_actualizacion)

    def _iniciar_instalacion_actualizacion(self, datos: Dict[str, str]):
        self.hide_busy_overlay()
        comando = [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            datos["script"],
            "-IdProceso",
            str(os.getpid()),
            "-CarpetaActual",
            datos["carpeta_actual"],
            "-CarpetaNueva",
            datos["carpeta_nueva"],
            "-NombreEjecutable",
            datos["nombre_ejecutable"],
        ]
        subprocess.Popen(
            comando,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            close_fds=True,
        )
        QMessageBox.information(
            self,
            "Actualización lista",
            "La descarga terminó correctamente.\n\n"
            "El aplicativo se cerrará para instalar la nueva versión.",
        )
        QApplication.quit()

    def show_about_dialog(self):
        QMessageBox.information(
            self,
            "Aplicativo CyR",
            f"Aplicativo CyR v{CURRENT_VERSION}\n\n"
            "Aplicativo para cierres y reaperturas.\n"
            "Las actualizaciones estaran disponibles cuando se publique una nueva version.",
        )

    def select_file(self) -> bool:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Seleccionar archivo",
            "",
            "Excel o CSV (*.xlsx *.xlsm *.csv);;Excel (*.xlsx *.xlsm);;CSV (*.csv);;Todos (*.*)",
        )
        if path:
            self.entrada_archivo.setText(path)
            if path.lower().endswith(".csv"):
                self.sheets = [SheetInfo("CSV", "", "")]
                self.hoja_detectada = "CSV"
                self.write_log("Archivo CSV detectado.")
            else:
                self.load_sheets()
            return True
        return False

    def import_from_google_sheets(self):
        dialog = GoogleSheetsConnectWindow(self, self.google_source_service)
        if dialog.exec() and dialog.loaded_workbook:
            self.set_current_workbook(dialog.loaded_workbook)

    def refresh_from_google_sheets(self):
        if self.is_busy:
            self._set_google_change_status("Ya hay un proceso en ejecución.", alert=False)
            return
        if not self.current_workbook or self.current_workbook.source_type != "GoogleSheets":
            QMessageBox.information(self, "Google Sheets", "El libro actual no viene de Google Sheets.")
            return
        self._start_google_refresh(
            title="Actualizando información",
            message="Actualizando información desde Google Sheets, por favor espere...",
            final_message="Información actualizada correctamente.",
            keep_pending_on_error=False,
        )

    def _start_google_refresh(
        self,
        title: str,
        message: str,
        final_message: str,
        keep_pending_on_error: bool = True,
    ):
        if self.is_busy:
            self._set_google_change_status("Ya hay un proceso en ejecución.", alert=False)
            return
        if not self.current_workbook or self.current_workbook.source_type != "GoogleSheets":
            return
        self.is_refreshing_google = True
        self._pending_refresh_active_sheet = self.current_workbook.active_sheet_name
        self._pending_refresh_print_sheet = self.current_workbook.print_sheet_name
        self._pending_refresh_final_message = final_message
        self._pending_refresh_keep_pending_on_error = keep_pending_on_error
        self._set_google_change_status("Estado: actualizando desde Google Sheets...", alert=False)
        self.show_busy_overlay(title, message)
        self.write_log("Actualizando libro completo desde Google Sheets...")
        worker = GoogleSheetsRefreshWorker(self.google_source_service, self.current_workbook.source_url)
        self._start_qthread_worker(
            worker=worker,
            finished_handler=self._finalizar_actualizacion_google,
            error_handler=self._error_actualizacion_google,
        )

    def _finalizar_actualizacion_google(self, workbook: WorkbookModel):
        previous_active = self._pending_refresh_active_sheet
        previous_print = self._pending_refresh_print_sheet
        final_message = getattr(self, "_pending_refresh_final_message", "Información actualizada correctamente.")
        self.is_refreshing_google = False
        self.hide_busy_overlay()
        self.set_current_workbook(workbook, preferred_active=previous_active, preferred_print=previous_print)
        self.pending_google_workbook = None
        now = datetime.now().strftime("%H:%M:%S")
        self.ultima_carga_google = now
        self.ultima_revision_google = now
        self.google_changes_pending = False
        self._set_google_change_status(
            f"Última carga: {self.ultima_carga_google} | Última revisión: {self.ultima_revision_google} | Cambios pendientes: No",
            alert=False,
        )
        QMessageBox.information(self, "Google Sheets", final_message)

    def _error_actualizacion_google(self, message: str):
        keep_pending = getattr(self, "_pending_refresh_keep_pending_on_error", True)
        self.is_refreshing_google = False
        self.hide_busy_overlay()
        if keep_pending and self.pending_google_workbook:
            self.google_changes_pending = True
            self._set_google_change_status("HUBO CAMBIO EN GOOGLE SHEETS. ACTUALIZAR.", alert=True)
            self.boton_actualizar_cambio_google.setVisible(True)
            self.boton_actualizar_cambio_google.setEnabled(True)
        else:
            self._set_google_change_status("Estado: no se pudo actualizar desde Google Sheets.", alert=False)
        self.write_log("ERROR actualizando Google Sheets: " + message)
        QMessageBox.critical(
            self,
            "Google Sheets",
            "No se pudo actualizar la información desde Google Sheets.\n\nSe mantendrán los datos cargados actualmente.",
        )

    def show_google_changes_notice(self):
        self._set_google_change_status("HUBO CAMBIO EN GOOGLE SHEETS. ACTUALIZAR.", alert=True)
        self.boton_actualizar_cambio_google.setVisible(True)
        self.boton_actualizar_cambio_google.setEnabled(True)

    def check_google_sheets_changes(self):
        if self.is_busy:
            self._set_google_change_status("Ya hay un proceso en ejecución.", alert=False)
            return
        if not self.current_workbook or self.current_workbook.source_type != "GoogleSheets":
            QMessageBox.information(self, "Google Sheets", "El libro actual no viene de Google Sheets.")
            return
        self.is_checking_changes = True
        self.pending_google_workbook = None
        self.boton_actualizar_cambio_google.setVisible(False)
        self.boton_actualizar_cambio_google.setEnabled(False)
        self._set_google_change_status("Estado: verificando cambios en Google Sheets...", alert=False)
        self.show_busy_overlay(
            "Detectando cambios",
            "Detectando cambios en Google Sheets, por favor espere...",
        )
        self.write_log("Verificando cambios en Google Sheets...")
        worker = GoogleSheetsCheckWorker(
            self.google_source_service,
            self.current_workbook.source_url,
            self._workbook_signature(self.current_workbook),
        )
        self._start_qthread_worker(
            worker=worker,
            finished_handler=self._finalizar_verificacion_google,
            error_handler=self._error_verificacion_google,
        )

    def _finalizar_verificacion_google(self, has_changes: bool, workbook: WorkbookModel):
        self.is_checking_changes = False
        self.hide_busy_overlay()
        if not self.current_workbook or self.current_workbook.source_type != "GoogleSheets":
            return

        if has_changes:
            self.pending_google_workbook = workbook
            self.ultima_revision_google = datetime.now().strftime("%H:%M:%S")
            self.google_changes_pending = True
            self._set_google_change_status("HUBO CAMBIO EN GOOGLE SHEETS. ACTUALIZAR.", alert=True)
            self.boton_actualizar_cambio_google.setVisible(True)
            self.boton_actualizar_cambio_google.setEnabled(True)
            self.write_log("Se detectaron cambios en Google Sheets.")
            QMessageBox.information(self, "Google Sheets", "Se detectaron cambios en Google Sheets.")
            return

        self.pending_google_workbook = None
        self.ultima_revision_google = datetime.now().strftime("%H:%M:%S")
        self.google_changes_pending = False
        self.boton_actualizar_cambio_google.setVisible(False)
        self.boton_actualizar_cambio_google.setEnabled(False)
        self._set_google_change_status(f"Estado: sin cambios. Última revisión: {self.ultima_revision_google}", alert=False)
        self.write_log("Google Sheets sin cambios.")
        QMessageBox.information(self, "Google Sheets", "No se detectaron cambios.")

    def _error_verificacion_google(self, message: str):
        self.is_checking_changes = False
        self.hide_busy_overlay()
        self._set_google_change_status("Estado: no se pudo verificar cambios.", alert=False)
        self.write_log("ERROR verificando Google Sheets: " + message)
        QMessageBox.critical(
            self,
            "Google Sheets",
            "No se pudo verificar cambios en Google Sheets.\n\nVerifica tu conexión a internet e intenta nuevamente.",
        )

    def apply_pending_google_update(self):
        if self.is_busy:
            self._set_google_change_status("Ya hay un proceso en ejecución.", alert=False)
            return
        if not self.current_workbook or self.current_workbook.source_type != "GoogleSheets":
            return
        pending_workbook = self.pending_google_workbook
        if pending_workbook is None:
            self._set_google_change_status("Estado: sin actualización pendiente. Verifica cambios primero.", alert=False)
            QMessageBox.information(self, "Google Sheets", "Primero verifica cambios en Google Sheets.")
            return

        previous_active = self.current_workbook.active_sheet_name
        previous_print = self.current_workbook.print_sheet_name
        self.write_log("Aplicando actualización ya verificada de Google Sheets sin volver a descargar.")
        self.set_current_workbook(pending_workbook, preferred_active=previous_active, preferred_print=previous_print)
        now = datetime.now().strftime("%H:%M:%S")
        self.ultima_carga_google = now
        self.ultima_revision_google = now
        self.google_changes_pending = False
        self.boton_actualizar_cambio_google.setVisible(False)
        self.boton_actualizar_cambio_google.setEnabled(False)
        self._set_google_change_status(
            f"Última carga: {self.ultima_carga_google} | Última revisión: {self.ultima_revision_google} | Cambios pendientes: No",
            alert=False,
        )
        QMessageBox.information(self, "Google Sheets", "Información actualizada correctamente.")

    def _set_google_change_status(self, text: str, alert: bool = False):
        if not hasattr(self, "etiqueta_estado_cambios"):
            return
        self.etiqueta_estado_cambios.setText(text)
        if alert:
            self.etiqueta_estado_cambios.setStyleSheet(
                "color: #b91c1c; background: #fef2f2; border: 1px solid #fca5a5; "
                "border-radius: 6px; padding: 7px 9px; font-weight: 800;"
            )
            return
        self.etiqueta_estado_cambios.setStyleSheet(
            "color: #475569; background: #f8fafc; border: 1px solid #e2e8f0; "
            "border-radius: 6px; padding: 7px 9px; font-weight: 600;"
        )

    def _workbook_signature(self, workbook: WorkbookModel) -> str:
        return workbook_signature(workbook)

    def _start_qthread_worker(self, worker: QObject, finished_handler, error_handler):
        thread = QThread(self)
        self._google_worker_thread = thread
        self._google_worker = worker
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        if hasattr(worker, "progress_message"):
            worker.progress_message.connect(self.update_busy_overlay)
        worker.finished.connect(finished_handler)
        worker.error.connect(error_handler)
        worker.finished.connect(lambda *_args: thread.quit())
        worker.error.connect(lambda *_args: thread.quit())
        worker.finished.connect(lambda *_args: worker.deleteLater())
        worker.error.connect(lambda *_args: worker.deleteLater())
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._cleanup_google_worker)
        thread.start()

    def _cleanup_google_worker(self):
        self._google_worker_thread = None
        self._google_worker = None

    def select_output_folder(self):
        path = QFileDialog.getExistingDirectory(self, "Elegir carpeta de salida")
        if path:
            self.entrada_salida.setText(path)

    def load_sheets(self):
        path = self.entrada_archivo.text().strip()
        if not path:
            QMessageBox.warning(self, "Falta archivo", "Selecciona un archivo primero.")
            return
        if self.current_workbook and self.current_workbook.source_type == "GoogleSheets" and path == self.current_workbook.source_url:
            self.sheets = [SheetInfo(sheet.name, "", "") for sheet in self.current_workbook.sheets]
            self.write_log("Hojas encontradas: " + ", ".join(sheet.name for sheet in self.current_workbook.sheets))
            return
        if path.startswith("https://docs.google.com/spreadsheets/"):
            QMessageBox.information(self, "Google Sheets", "Usa Importar > Desde Google Sheets para cargar el libro completo.")
            return
        if path.lower().endswith(".csv"):
            self.sheets = [SheetInfo("CSV", "", "")]
            self.hoja_detectada = "CSV"
            self.write_log("Archivo CSV detectado.")
            return
        try:
            reader = FastXlsxReader(path)
            self.sheets = reader.list_sheets()
            nombres = [s.name for s in self.sheets]
            self.hoja_detectada = self.HOJA_MACRO
            self.write_log("Hojas encontradas: " + ", ".join(nombres))
            if self.HOJA_MACRO not in nombres:
                QMessageBox.warning(
                    self,
                    "Hoja fija no encontrada",
                    f"La lógica de la macro usa la hoja {self.HOJA_MACRO} y no se permite cambiarla desde la ventana.",
                )
                self.write_log(f"AVISO: no se encontró la hoja fija de macro: {self.HOJA_MACRO}")
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"No pude listar hojas:\n{exc}")
            self.write_log(traceback.format_exc())

    def load_data_thread(self):
        if self.is_busy:
            QMessageBox.information(self, "Proceso en ejecución", "Ya hay un proceso en ejecución.")
            return
        valores = self._tomar_valores_carga()
        if not valores["path"]:
            QMessageBox.warning(self, "Falta archivo", "Selecciona un archivo primero.")
            return
        if str(valores["path"]).startswith("https://docs.google.com/spreadsheets/"):
            if (
                self.current_workbook
                and self.current_workbook.source_type == "GoogleSheets"
                and self.current_workbook.source_url == str(valores["path"])
            ):
                self.show_busy_overlay(
                    "Cargando información",
                    "Cargando información, por favor espere...",
                    show_progress=False,
                )
                QApplication.processEvents()
                try:
                    self._preparar_workbook_actual_para_pdfs()
                finally:
                    if self.is_busy:
                        self.hide_busy_overlay()
                return
            self.show_busy_overlay(
                "Cargando información",
                "Cargando información, por favor espere...",
                show_progress=False,
            )
            self.boton_cargar.setEnabled(False)
            self.write_log("Cargando libro completo desde Google Sheets...")
            self._run_thread(
                lambda: self.google_source_service.load_workbook(str(valores["path"])),
                lambda workbook: self._finalizar_carga({"workbook": workbook}),
            )
            return
        self.show_busy_overlay(
            "Cargando información",
            "Cargando información, por favor espere...",
            show_progress=False,
        )
        self.boton_cargar.setEnabled(False)
        self.write_log("Cargando datos...")
        self._run_thread(lambda: self._cargar_datos(valores), self._finalizar_carga)

    def _preparar_workbook_actual_para_pdfs(self):
        if not self.current_workbook:
            return
        active = self.current_workbook.active_sheet_name
        print_sheet = self.current_workbook.print_sheet_name
        self.set_current_workbook(self.current_workbook, preferred_active=active, preferred_print=print_sheet)
        self.write_log("Datos preparados para filtros y PDFs usando el libro ya cargado.")
        QMessageBox.information(self, "Listo", "Datos cargados para filtros y PDFs.")

    def _tomar_valores_carga(self) -> Dict[str, object]:
        return {
            "path": self.entrada_archivo.text().strip(),
            "sheet_name": self.hoja_detectada,
            "header_row": self.FILA_ENCABEZADO_MACRO,
            "start_row": self.FILA_INICIO_MACRO,
            "end_row": self.FILA_FIN_MACRO,
            "min_col": self.COL_INICIAL_MACRO,
            "max_col": self.COL_FINAL_MACRO,
            "skip_hidden": self.IGNORAR_FILAS_OCULTAS_MACRO,
        }

    def _cargar_datos(self, valores: Dict[str, object]) -> Dict[str, object]:
        path = str(valores["path"])
        workbook = read_local_workbook_model(
            path=path,
            header_row=int(valores["header_row"]),
            data_start_row=int(valores["start_row"]),
            data_end_row=int(valores["end_row"]),
            min_col=str(valores["min_col"]),
            max_col=str(valores["max_col"]),
            skip_hidden_rows=bool(valores["skip_hidden"]),
        )
        return {"workbook": workbook}

    def _finalizar_carga(self, resultado: Dict[str, object]):
        if self.is_busy:
            self.hide_busy_overlay()
        self.boton_cargar.setEnabled(True)
        workbook = resultado["workbook"]
        if not isinstance(workbook, WorkbookModel):
            raise TypeError("Resultado de carga inválido")
        self.set_current_workbook(workbook)

    def set_current_workbook(
        self,
        workbook: WorkbookModel,
        preferred_active: str = "",
        preferred_print: str = "",
    ):
        sheet_names = workbook.sheet_names()
        if not sheet_names:
            raise ValueError("El libro no contiene hojas.")

        if preferred_active and workbook.has_sheet(preferred_active):
            workbook.active_sheet_name = preferred_active
        elif not workbook.has_sheet(workbook.active_sheet_name):
            workbook.active_sheet_name = workbook.print_sheet_name if workbook.has_sheet(workbook.print_sheet_name) else sheet_names[0]

        if preferred_print and workbook.has_sheet(preferred_print):
            workbook.print_sheet_name = preferred_print
        elif not workbook.has_sheet(workbook.print_sheet_name):
            workbook.print_sheet_name = choose_print_sheet_name(sheet_names)

        print_sheet = workbook.get_sheet(workbook.print_sheet_name)
        if print_sheet is None:
            raise ValueError("No se pudo determinar la hoja de impresión.")

        self.current_workbook = workbook
        self.pending_google_workbook = None
        self.sheets = [SheetInfo(sheet.name, "", "") for sheet in workbook.sheets]
        self.hoja_detectada = print_sheet.name
        self.data = sheet_model_to_loaded_data(print_sheet)

        if workbook.source_type == "GoogleSheets":
            self.entrada_archivo.setText(workbook.source_url)
        else:
            self.entrada_archivo.setText(workbook.source_path)

        self._render_workbook_tabs(workbook)
        self._refresh_loaded_data_controls()
        is_google = workbook.source_type == "GoogleSheets"
        self.accion_actualizar_google.setEnabled(is_google)
        self.boton_actualizar_google_visual.setEnabled(is_google)
        self.boton_verificar_cambios_google.setEnabled(is_google)
        self.boton_actualizar_cambio_google.setVisible(False)
        self.boton_actualizar_cambio_google.setEnabled(False)
        self.boton_toggle_visualizador.setEnabled(True)
        if is_google:
            self.ultima_carga_google = datetime.now().strftime("%H:%M:%S")
            self.ultima_revision_google = ""
            self.google_changes_pending = False
            self._set_google_change_status(
                f"Última carga: {self.ultima_carga_google} | Última revisión: -- | Cambios pendientes: No",
                alert=False,
            )
        else:
            self.ultima_carga_google = ""
            self.ultima_revision_google = ""
            self.google_changes_pending = False
            self._set_google_change_status("Estado: archivo local cargado. Sin verificación de Google Sheets.", alert=False)
        self.write_log(
            f"Libro cargado. Origen: {workbook.source_type}. "
            f"Hojas: {len(workbook.sheets)}. Hoja de impresión: {workbook.print_sheet_name}."
        )

    def _refresh_loaded_data_controls(self):
        if not self.data:
            return
        encabezados_ui = []
        for i, header in enumerate(self.data.headers):
            label = safe_text(header) or index_to_col_letter(i)
            encabezados_ui.append(f"{index_to_col_letter(i)} - {label}")

        turno_idx = find_header_col(self.data.headers, ["TURNO", "TURNO TRABAJO"])
        if turno_idx is not None and turno_idx < len(encabezados_ui):
            filtro_actual = encabezados_ui[turno_idx]
        elif encabezados_ui:
            filtro_actual = encabezados_ui[0]
        else:
            filtro_actual = ""

        self._llenar_combo(self.combo_col_filtro, encabezados_ui, filtro_actual)
        self.combo_col_filtro.setEnabled(bool(encabezados_ui))
        self.refresh_filter_values()

    def _render_workbook_tabs(self, workbook: WorkbookModel):
        self._actualizando_tabs = True
        self.tabs_hojas.clear()
        for sheet in workbook.sheets:
            self.tabs_hojas.addTab(self._crear_vista_hoja(sheet), sheet.name)
        active_index = workbook.sheet_names().index(workbook.active_sheet_name) if workbook.active_sheet_name in workbook.sheet_names() else 0
        self.tabs_hojas.setCurrentIndex(active_index)
        self.visualizador_libro_visible = True
        self.tabs_hojas.setVisible(True)
        self.boton_toggle_visualizador.setText("Ocultar visualizador")
        self.boton_toggle_visualizador.setIcon(self._icono("ocultar"))
        self._actualizando_tabs = False
        self._update_workbook_status_label()

    def _crear_vista_hoja(self, sheet: SheetModel) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)

        preview_limit = 200
        visible_rows = sheet.dataframe[:preview_limit]
        label = QLabel(
            f"Hoja: {sheet.name} | Filas: {sheet.row_count} | Columnas: {sheet.column_count}"
            + (f" | Vista previa: {preview_limit} filas" if sheet.row_count > preview_limit else "")
        )
        label.setObjectName("estado")
        layout.addWidget(label)

        table = QTableWidget(len(visible_rows), len(sheet.headers))
        table.setObjectName("tablaLibro")
        table.setMinimumHeight(250)
        table.setHorizontalHeaderLabels([safe_text(h) or index_to_col_letter(i) for i, h in enumerate(sheet.headers)])
        table.verticalHeader().setVisible(False)
        table.setAlternatingRowColors(True)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setStretchLastSection(True)
        for row_idx, row in enumerate(visible_rows):
            for col_idx, value in enumerate(row[:len(sheet.headers)]):
                table.setItem(row_idx, col_idx, QTableWidgetItem(safe_text(value)))
        table.setSortingEnabled(True)
        layout.addWidget(table)
        return widget

    def toggle_workbook_viewer(self):
        if not self.current_workbook:
            return
        self.visualizador_libro_visible = not self.visualizador_libro_visible
        self.tabs_hojas.setVisible(self.visualizador_libro_visible)
        if self.visualizador_libro_visible:
            self.boton_toggle_visualizador.setText("Ocultar visualizador")
            self.boton_toggle_visualizador.setIcon(self._icono("ocultar"))
        else:
            self.boton_toggle_visualizador.setText("Mostrar visualizador")
            self.boton_toggle_visualizador.setIcon(self._icono("mostrar"))
        self._update_workbook_status_label()

    def _on_sheet_tab_changed(self, index: int):
        if self._actualizando_tabs or not self.current_workbook or index < 0:
            return
        self.current_workbook.active_sheet_name = self.tabs_hojas.tabText(index)
        self._update_workbook_status_label()

    def _update_workbook_status_label(self):
        if not self.current_workbook:
            self.etiqueta_libro.setText("Sin libro cargado")
            self.etiqueta_origen_libro.setText("Origen: --")
            self.etiqueta_impresion_libro.setText("Impresión: --")
            self.etiqueta_resumen_libro.setText("Carga un Excel, CSV o Google Sheets para ver las hojas del libro aquí.")
            self._set_google_change_status("Estado: sin libro cargado", alert=False)
            return
        self.etiqueta_libro.setText(
            f"{self.current_workbook.workbook_name} | "
            f"Activa: {self.current_workbook.active_sheet_name} | "
            f"Impresión/PDF: {self.current_workbook.print_sheet_name}"
        )
        self.etiqueta_origen_libro.setText(f"Origen: {self.current_workbook.source_type}")
        self.etiqueta_impresion_libro.setText(f"Impresión: {self.current_workbook.print_sheet_name}")
        estado = "visible" if self.visualizador_libro_visible else "oculto"
        self.etiqueta_resumen_libro.setText(
            f"{len(self.current_workbook.sheets)} hoja(s) cargada(s). "
            f"Visualizador {estado}; los filtros y PDFs usan la hoja de impresión."
        )

    def _column_from_combo_or_letter(self, text: str, default_letter: str = "A") -> int:
        text = safe_text(text)
        m = re.match(r"^([A-Z]+)\s*-", text, flags=re.I)
        if m:
            return col_letter_to_index(m.group(1))
        if text:
            try:
                return col_letter_to_index(text)
            except Exception:
                pass
        return col_letter_to_index(default_letter)

    def refresh_filter_values(self):
        if not self.data:
            self._update_pdf_sort_buttons_state()
            return
        try:
            filter_idx = self._column_from_combo_or_letter(self.combo_col_filtro.currentText(), "A")
            vals = ["(TODOS)"] + unique_values(self.data.rows, filter_idx)
            self._llenar_combo(self.combo_valor_filtro, vals, self.combo_valor_filtro.currentText())

            group_idx = col_letter_to_index(self.COL_AGRUPACION_MACRO)
            rows_filtered = self._apply_filter(self.data.rows, filter_idx, self.combo_valor_filtro.currentText())
            item_vals = ["(TODOS)"] + unique_values(rows_filtered, group_idx)
            self._llenar_combo(self.combo_item, item_vals, self.combo_item.currentText())
            self._update_pdf_sort_buttons_state()
            self.write_log(f"Valores actualizados. Filtro disponible: {len(vals)-1}. Items: {len(item_vals)-1}")
        except Exception as exc:
            self._update_pdf_sort_buttons_state()
            QMessageBox.warning(self, "Filtro inválido", str(exc))

    def _on_filter_value_changed(self):
        if not self.data:
            self._update_pdf_sort_buttons_state()
            return
        try:
            filter_idx = self._column_from_combo_or_letter(self.combo_col_filtro.currentText(), "A")
            group_idx = col_letter_to_index(self.COL_AGRUPACION_MACRO)
            rows_filtered = self._apply_filter(self.data.rows, filter_idx, self.combo_valor_filtro.currentText())
            item_vals = ["(TODOS)"] + unique_values(rows_filtered, group_idx)
            self._llenar_combo(self.combo_item, item_vals, self.combo_item.currentText())
        except Exception as exc:
            QMessageBox.warning(self, "Filtro inválido", str(exc))
        finally:
            self._update_pdf_sort_buttons_state()

    def _turno_seleccionado_para_orden(self) -> bool:
        if not self.data:
            return False
        filter_idx = self._column_from_combo_or_letter(self.combo_col_filtro.currentText(), "A")
        header = safe_text(self.data.headers[filter_idx] if filter_idx < len(self.data.headers) else "")
        turno_es_filtro = "TURNO" in normalize(header or self.combo_col_filtro.currentText())
        valor = safe_text(self.combo_valor_filtro.currentText())
        return turno_es_filtro and bool(valor) and valor != "(TODOS)"

    def _update_pdf_sort_buttons_state(self):
        if not hasattr(self, "boton_orden_manzana"):
            return
        enabled = self._turno_seleccionado_para_orden()
        if not enabled:
            self.pdf_sort_mode = ""
        self.boton_orden_manzana.setEnabled(enabled)
        self.boton_orden_cus.setEnabled(enabled)
        self.boton_orden_manzana.setChecked(enabled and self.pdf_sort_mode == "MZN")
        self.boton_orden_cus.setChecked(enabled and self.pdf_sort_mode == "CUS")

    def set_pdf_sort_mode(self, mode: str):
        if not self._turno_seleccionado_para_orden():
            self.pdf_sort_mode = ""
            self._update_pdf_sort_buttons_state()
            QMessageBox.information(self, "Orden PDF", "Primero selecciona un TURNO para habilitar el orden.")
            return
        self.pdf_sort_mode = mode if mode in {"MZN", "CUS"} else ""
        self._update_pdf_sort_buttons_state()
        if self.pdf_sort_mode == "MZN":
            self.write_log("Orden PDF seleccionado: Manzana A-Z.")
        elif self.pdf_sort_mode == "CUS":
            self.write_log("Orden PDF seleccionado: CUS A-Z.")

    def _apply_filter(self, rows: List[List[str]], col_idx: int, wanted: str) -> List[List[str]]:
        wanted = safe_text(wanted)
        if not wanted or wanted == "(TODOS)":
            return list(rows)
        wanted_norm = normalize(wanted)
        return [r for r in rows if normalize(r[col_idx] if col_idx < len(r) else "") == wanted_norm]

    def _resolve_pdf_sort_column(self, headers: List[str], mode: str) -> Optional[int]:
        if mode == "MZN":
            fallback = col_letter_to_index(self.COL_ORDEN_MANZANA_MACRO)
            found = find_header_col(headers, ["MZN", "MANZANA"])
        elif mode == "CUS":
            fallback = col_letter_to_index(self.COL_ORDEN_CUS_MACRO)
            found = find_header_col(headers, ["CUS"])
        else:
            return None
        if found is not None:
            return found
        return fallback if fallback < len(headers) else None

    def _pdf_sort_key(self, row: List[str], col_idx: int):
        text = safe_text(row[col_idx] if col_idx < len(row) else "")
        if not text:
            return (1, [])
        parts = re.split(r"(\d+)", normalize(text))
        key = []
        for part in parts:
            if not part:
                continue
            key.append((0, int(part)) if part.isdigit() else (1, part))
        return (0, key)

    def generate_pdfs_thread(self):
        if self.is_busy:
            QMessageBox.information(self, "Proceso en ejecución", "Espere a que termine la actualización de datos.")
            return
        if not self.data:
            QMessageBox.warning(self, "Faltan datos", "Primero carga los datos.")
            return
        valores = self._tomar_valores_generacion()
        if str(valores["pdf_template"]) == "Moderna":
            modern_template = self.pdf_template_service.GetModernTemplate()
            if modern_template is None:
                respuesta = QMessageBox.question(
                    self,
                    "Plantilla moderna",
                    "La plantilla moderna aún no está configurada.\n¿Deseas abrir el editor de plantillas ahora?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.Yes,
                )
                if respuesta == QMessageBox.Yes:
                    self.open_pdf_template_editor()
                return
            valores["pdf_template_model"] = modern_template

        self.boton_generar.setEnabled(False)
        self.boton_configurar_plantillas.setEnabled(False)
        self._actualizar_progreso(0, 0)
        self._run_thread(lambda: self._generar_pdfs(valores), self._finalizar_generacion)

    def open_pdf_template_editor(self):
        dialog = PdfTemplateEditorWindow(self, self.pdf_template_service)
        if dialog.exec() and self.pdf_template_service.GetModernTemplate():
            self.combo_plantilla_pdf.setCurrentText("Moderna")
            self.write_log("Plantilla moderna guardada y lista para generar PDFs.")

    def mostrar_pagina_ruteo(self):
        if hasattr(self, "stack_paginas") and hasattr(self, "pagina_ruteo"):
            self.stack_paginas.setCurrentWidget(self.pagina_ruteo)
            self._marcar_modulo_activo(self.accion_pagina_ruteo)

    def mostrar_pagina_txt_cyr(self):
        if self.is_busy:
            self._restaurar_modulo_activo()
            QMessageBox.information(self, "Proceso en ejecucion", "Espere a que termine el proceso actual.")
            return
        if hasattr(self, "stack_paginas") and hasattr(self, "pagina_txt_cyr"):
            self.stack_paginas.setCurrentWidget(self.pagina_txt_cyr)
            self._marcar_modulo_activo(self.accion_pagina_txt_cyr)

    def mostrar_pagina_extractor_ordenes(self):
        if self.is_busy:
            self._restaurar_modulo_activo()
            QMessageBox.information(self, "Proceso en ejecución", "Espere a que termine el proceso actual.")
            return
        if hasattr(self, "stack_paginas") and hasattr(self, "pagina_extractor_ordenes"):
            self.stack_paginas.setCurrentWidget(self.pagina_extractor_ordenes)
            self._marcar_modulo_activo(self.accion_pagina_extractor)

    def mostrar_pagina_depuracion_ot(self):
        if self.is_busy:
            self._restaurar_modulo_activo()
            QMessageBox.information(self, "Proceso en ejecución", "Espere a que termine el proceso actual.")
            return
        if hasattr(self, "stack_paginas") and hasattr(self, "pagina_depuracion_ot"):
            self.stack_paginas.setCurrentWidget(self.pagina_depuracion_ot)
            self._marcar_modulo_activo(self.accion_pagina_depuracion_ot)

    def seleccionar_archivo_txt_cyr(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Seleccionar TXT SANSYS",
            "",
            "TXT SANSYS (*.txt);;Todos (*.*)",
        )
        if not path:
            return
        self.ruta_txt_cyr_sansys = path
        self.etiqueta_txt_cyr_archivo.setText(f"Archivo cargado: {Path(path).name}")
        self._registrar_txt_cyr(f"TXT SANSYS cargado: {path}")
        self.write_log(f"TXT CyR: archivo SANSYS seleccionado: {path}")

    def seleccionar_carpeta_txt_cyr(self):
        path = QFileDialog.getExistingDirectory(self, "Elegir carpeta de salida TXT CyR")
        if not path:
            return
        self.ruta_carpeta_txt_cyr = path
        self.entrada_carpeta_txt_cyr.setText(path)
        self._registrar_txt_cyr(f"Carpeta de salida TXT seleccionada: {path}")
        self.write_log(f"TXT CyR: carpeta de salida seleccionada: {path}")

    def generar_txt_cyr_en_hilo(self):
        if self.is_busy:
            QMessageBox.information(self, "Proceso en ejecucion", "Espere a que termine el proceso actual.")
            return
        if not self.current_workbook:
            QMessageBox.warning(self, "TXT CyR", "Debe cargar primero el libro Excel con hoja RUTEO.")
            return
        if buscar_hoja(self.current_workbook, "RUTEO") is None:
            QMessageBox.warning(self, "TXT CyR", "No se encontro la hoja RUTEO.")
            return
        if not self.ruta_txt_cyr_sansys:
            QMessageBox.warning(self, "TXT CyR", "Debe seleccionar un TXT SANSYS.")
            return

        carpeta_salida = self.entrada_carpeta_txt_cyr.text().strip()
        if not carpeta_salida:
            QMessageBox.warning(self, "TXT CyR", "Seleccione una carpeta de salida para los archivos TXT CyR.")
            return
        self.ruta_carpeta_txt_cyr = carpeta_salida

        self.show_busy_overlay(
            "Generando TXT CyR",
            "Procesando TXT SANSYS y cruzando con hoja RUTEO, por favor espere...",
            show_progress=False,
        )
        self.write_log("TXT CyR: iniciando procesamiento.")
        if hasattr(self, "registro_txt_cyr"):
            self.registro_txt_cyr.clear()
        if hasattr(self, "resumen_txt_cyr"):
            self.resumen_txt_cyr.setPlainText(
                f"Archivo cargado: {Path(self.ruta_txt_cyr_sansys).name}\n"
                "Estado: procesando\n"
                "Total registros: --\n"
                "Generados: --\n"
                "Encontrados: --\n"
                "Operarios no encontrados: --\n"
                "Errores: --\n"
                f"Ruta de archivos generados: {carpeta_salida}"
            )

        self.boton_cargar_txt_cyr.setEnabled(False)
        self.boton_generar_txt_cyr.setEnabled(False)
        self.boton_elegir_carpeta_txt_cyr.setEnabled(False)

        self._run_thread(
            lambda: generar_txt_cyr(
                self.current_workbook,
                Path(self.ruta_txt_cyr_sansys),
                Path(self.ruta_carpeta_txt_cyr),
                ruta_origen_libro=self.entrada_archivo.text().strip(),
                registrar_proceso=self._registrar_txt_cyr,
            ),
            self._finalizar_txt_cyr,
        )

    def _finalizar_txt_cyr(self, resultado: ResultadoTxtCyr):
        if self.is_busy:
            self.hide_busy_overlay()

        self.boton_cargar_txt_cyr.setEnabled(True)
        self.boton_generar_txt_cyr.setEnabled(True)
        self.boton_elegir_carpeta_txt_cyr.setEnabled(True)

        archivos = [resultado.ruta_sansys.name, resultado.ruta_sysaco.name]
        if resultado.ruta_reporte_errores:
            archivos.append(resultado.ruta_reporte_errores.name)

        resumen = (
            f"Proceso TXT CyR terminado.\n\n"
            f"Archivo cargado: {Path(self.ruta_txt_cyr_sansys).name}\n"
            "Estado: proceso terminado\n"
            f"Total registros: {resultado.total}\n"
            f"Generados: {resultado.generados}\n"
            f"Encontrados: {resultado.operarios_encontrados}\n"
            f"Operarios no encontrados: {resultado.operarios_no_encontrados}\n"
            f"Errores: {resultado.errores}\n\n"
            "Archivos generados:\n"
            + "\n".join(f"- {archivo}" for archivo in archivos)
            + f"\n\nRuta de archivos generados: {resultado.carpeta_salida}"
        )
        self.resumen_txt_cyr.setPlainText(resumen)
        self._registrar_txt_cyr(
            f"Proceso terminado. Total: {resultado.total}. Generados: {resultado.generados}. Errores: {resultado.errores}."
        )
        self.write_log(
            f"TXT CyR terminado. Total: {resultado.total}. Generados: {resultado.generados}. "
            f"Errores: {resultado.errores}. Carpeta: {resultado.carpeta_salida}"
        )
        QMessageBox.information(self, "TXT CyR", "Proceso terminado sin errores.")

    def _registrar_txt_cyr(self, mensaje: str):
        self.senal_registro_txt.emit(mensaje)

    def _tomar_valores_generacion(self) -> Dict[str, object]:
        source_label = self.entrada_archivo.text().strip()
        if self.current_workbook:
            source_label = self.current_workbook.workbook_name
        return {
            "data": self.data,
            "file_path": self.entrada_archivo.text().strip(),
            "source_label": source_label,
            "output_folder": self.entrada_salida.text().strip(),
            "filter_col": self.combo_col_filtro.currentText(),
            "filter_value": self.combo_valor_filtro.currentText(),
            "selected_item": self.combo_item.currentText(),
            "group_col": self.COL_AGRUPACION_MACRO,
            "folder_col": self.COL_CARPETA_MACRO,
            "max_col": self.COL_FINAL_MACRO,
            "create_subfolder": self.CREAR_SUBCARPETA_MACRO,
            "pdf_template": self.combo_plantilla_pdf.currentText(),
            "pdf_template_model": None,
            "sort_mode": self.pdf_sort_mode if self._turno_seleccionado_para_orden() else "",
        }

    def _generar_pdfs(self, valores: Dict[str, object]) -> Dict[str, object]:
        data = valores["data"]
        if not isinstance(data, LoadedData):
            raise ValueError("Primero carga los datos")
        out_base = Path(str(valores["output_folder"]))
        out_base.mkdir(parents=True, exist_ok=True)

        filter_idx = self._column_from_combo_or_letter(str(valores["filter_col"]), "A")
        group_idx = col_letter_to_index(str(valores["group_col"]) or "E")
        folder_idx = col_letter_to_index(str(valores["folder_col"]) or "F")

        rows = self._apply_filter(data.rows, filter_idx, str(valores["filter_value"]))

        selected_item = safe_text(valores["selected_item"])
        if selected_item and selected_item != "(TODOS)":
            selected_norm = normalize(selected_item)
            rows = [r for r in rows if normalize(r[group_idx] if group_idx < len(r) else "") == selected_norm]

        if not rows:
            raise ValueError("No hay filas para exportar con ese filtro")

        sort_mode = safe_text(valores.get("sort_mode"))
        sort_idx = self._resolve_pdf_sort_column(data.headers, sort_mode)
        if sort_mode and sort_idx is not None:
            rows = sorted(rows, key=lambda row: self._pdf_sort_key(row, sort_idx))
            sort_label = "Manzana" if sort_mode == "MZN" else "CUS"
            self.write_log(f"Orden aplicado a PDFs: {sort_label} A-Z.")

        groups: Dict[str, List[List[str]]] = {}
        for row in rows:
            item = safe_text(row[group_idx] if group_idx < len(row) else "")
            if not item:
                continue
            groups.setdefault(item, []).append(row)

        if not groups:
            raise ValueError("No encontré valores en la columna de agrupación")

        # Carpeta como la macro: toma la columna F de la primera fila filtrada.
        first_folder_name = safe_text(rows[0][folder_idx] if folder_idx < len(rows[0]) else "") or "SIN_CARPETA"
        target_folder = out_base / clean_filename(first_folder_name) if bool(valores["create_subfolder"]) else out_base
        target_folder.mkdir(parents=True, exist_ok=True)

        total = len(groups)
        self.senal_progreso.emit(0, total)
        self.write_log(f"Generando {total} PDF(s) en: {target_folder}")
        self.write_log(f"Plantilla PDF seleccionada: {valores['pdf_template']}")
        self.write_log("Regla aplicada: solo filas del filtro actual. Si elegiste un TURNO, solo ese TURNO.")

        filter_label = ""
        if str(valores["filter_value"]) != "(TODOS)":
            filter_label = f"Filtro: {valores['filter_col']} = {valores['filter_value']}"
        if selected_item != "(TODOS)":
            filter_label = (filter_label + " | " if filter_label else "") + f"Item: {selected_item}"

        exported = 0
        errors = 0
        for idx, (item, group_rows) in enumerate(groups.items(), start=1):
            try:
                pdf_name = f"cyr_{clean_filename(item)}.pdf"
                pdf_path = target_folder / pdf_name
                source_name = f"{safe_text(valores.get('source_label')) or Path(str(valores['file_path'])).name} / {data.source_sheet}"
                pdf_template = str(valores["pdf_template"])
                if pdf_template == "Moderna":
                    template_model = valores.get("pdf_template_model")
                    if not isinstance(template_model, PdfTemplateModel):
                        raise ValueError("La plantilla moderna no está guardada. Abre el editor y guarda la plantilla.")
                    build_modern_pdf_for_group(
                        output_pdf=pdf_path,
                        title=f"RUTEO - {item}",
                        headers=data.headers,
                        rows=group_rows,
                        source_name=source_name,
                        selected_filter_label=filter_label,
                        max_cols=col_letter_to_index(str(valores["max_col"]) or "Z") + 1,
                        template=template_model,
                    )
                elif pdf_template == "Cargo (3)":
                    build_cargo3_pdf_for_group(
                        output_pdf=pdf_path,
                        title=f"RUTEO - {item}",
                        headers=data.headers,
                        rows=group_rows,
                        source_name=source_name,
                        selected_filter_label=filter_label,
                        max_cols=col_letter_to_index(str(valores["max_col"]) or "Z") + 1,
                    )
                else:
                    build_pdf_for_group(
                        output_pdf=pdf_path,
                        title=f"RUTEO - {item}",
                        headers=data.headers,
                        rows=group_rows,
                        source_name=source_name,
                        selected_filter_label=filter_label,
                        max_cols=col_letter_to_index(str(valores["max_col"]) or "Z") + 1,
                        page_size=landscape(A4),
                        excluded_template_columns={"FECHA", "CODIGO"},
                        page_margins=(0.0, 0.0, 9.173, 0.0),
                        data_row_height=37.8,
                        max_table_width=810.0,
                    )
                exported += 1
                self.write_log(f"OK {idx}/{total}: {pdf_path}")
            except Exception as exc:
                errors += 1
                self.write_log(f"ERROR {idx}/{total} en {item}: {exc}")

            self.senal_progreso.emit(idx, total)

        self.write_log(f"Proceso terminado. Exportados: {exported}. Errores: {errors}.")
        return {"exported": exported, "errors": errors, "target_folder": target_folder}

    def _finalizar_generacion(self, resultado: Dict[str, object]):
        self.boton_generar.setEnabled(True)
        self.boton_configurar_plantillas.setEnabled(True)
        QMessageBox.information(
            self,
            "Terminado",
            f"PDF exportados: {resultado['exported']}\nErrores: {resultado['errors']}\nCarpeta:\n{resultado['target_folder']}",
        )

    def open_output_folder(self):
        folder = Path(self.entrada_salida.text().strip())
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _run_thread(self, target, al_terminar=None):
        def runner():
            try:
                resultado = target()
            except Exception as exc:
                self.senal_error.emit(str(exc), traceback.format_exc())
            else:
                self.senal_tarea_ok.emit(al_terminar, resultado)

        threading.Thread(target=runner, daemon=True).start()

    @Slot(object, object)
    def _finalizar_tarea(self, al_terminar, resultado):
        try:
            if al_terminar:
                al_terminar(resultado)
        except Exception as exc:
            self._mostrar_error(str(exc), traceback.format_exc())

    @Slot(str, str)
    def _mostrar_error(self, mensaje: str, detalle: str):
        if self.is_busy:
            self.hide_busy_overlay()
            self.is_checking_changes = False
            self.is_refreshing_google = False
        if hasattr(self, "boton_generar"):
            self.boton_generar.setEnabled(True)
        if hasattr(self, "boton_configurar_plantillas"):
            self.boton_configurar_plantillas.setEnabled(True)
        if hasattr(self, "boton_cargar"):
            self.boton_cargar.setEnabled(True)
        if hasattr(self, "boton_cargar_txt_cyr"):
            self.boton_cargar_txt_cyr.setEnabled(True)
        if hasattr(self, "boton_generar_txt_cyr"):
            self.boton_generar_txt_cyr.setEnabled(True)
        if hasattr(self, "boton_elegir_carpeta_txt_cyr"):
            self.boton_elegir_carpeta_txt_cyr.setEnabled(True)
        if hasattr(self, "accion_actualizar_google"):
            self.accion_actualizar_google.setEnabled(
                bool(self.current_workbook and self.current_workbook.source_type == "GoogleSheets")
            )
        if hasattr(self, "boton_actualizar_google_visual"):
            self.boton_actualizar_google_visual.setEnabled(
                bool(self.current_workbook and self.current_workbook.source_type == "GoogleSheets")
            )
        if hasattr(self, "boton_verificar_cambios_google"):
            self.boton_verificar_cambios_google.setEnabled(
                bool(self.current_workbook and self.current_workbook.source_type == "GoogleSheets")
            )
        if hasattr(self, "accion_buscar_actualizaciones"):
            self.accion_buscar_actualizaciones.setEnabled(True)
        error_en_pagina_txt = (
            hasattr(self, "stack_paginas")
            and hasattr(self, "pagina_txt_cyr")
            and self.stack_paginas.currentWidget() == self.pagina_txt_cyr
        )
        if error_en_pagina_txt and hasattr(self, "registro_txt_cyr"):
            self._registrar_txt_cyr("ERROR: " + mensaje)
        if error_en_pagina_txt and hasattr(self, "resumen_txt_cyr"):
            self.resumen_txt_cyr.setPlainText(
                "Proceso TXT CyR detenido.\n\n"
                f"Estado: error\n"
                f"Detalle: {mensaje}"
            )
        self.write_log("ERROR: " + mensaje)
        self.write_log(detalle)
        QMessageBox.critical(self, "Error", mensaje)


RuteoApp = VentanaRuteo


if __name__ == "__main__":
    if not asegurar_instancia_unica():
        raise SystemExit(0)
    configure_windows_taskbar_icon()
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app_icon = load_app_icon()
    if not app_icon.isNull():
        app.setWindowIcon(app_icon)
    ventana = VentanaRuteo()
    ventana.show()
    if not app_icon.isNull():
        ventana.setWindowIcon(app_icon)
    sys.exit(app.exec())
