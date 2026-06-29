# -*- coding: utf-8 -*-
from __future__ import annotations

import io
import json
import os
import re
import socket
import threading
import time
import zipfile
from dataclasses import dataclass
from datetime import datetime
from http.client import IncompleteRead
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from workbook_models import SheetModel, WorkbookModel


INCOMPLETE_READ_MESSAGE = "No se pudo completar la lectura del Google Sheets. Verifica tu conexión e intenta nuevamente."


class _RetryableDownloadError(RuntimeError):
    pass


def extract_spreadsheet_id(url: str) -> str:
    text = (url or "").strip()
    match = re.search(r"https://docs\.google\.com/spreadsheets/d/([A-Za-z0-9_-]+)", text)
    if not match:
        raise ValueError("El enlace ingresado no parece ser un enlace válido de Google Sheets.")
    return match.group(1)


def _safe_text(value) -> str:
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


def _col_letter_to_index(letter: str) -> int:
    text = re.sub(r"[^A-Za-z]", "", str(letter or "")).upper()
    if not text:
        return 0
    value = 0
    for char in text:
        value = value * 26 + (ord(char) - ord("A") + 1)
    return value - 1


def _cell_ref_to_row_col(ref: str) -> Tuple[int, int]:
    match = re.match(r"([A-Za-z]+)(\d+)", ref or "")
    if not match:
        return 0, 0
    return int(match.group(2)) - 1, _col_letter_to_index(match.group(1))


@dataclass
class _XlsxSheetInfo:
    name: str
    path: str


class _XlsxWorkbookBytesReader:
    NS_MAIN = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    NS_REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"

    def __init__(self, content: bytes):
        self.content = content
        self._shared_strings: Optional[List[str]] = None

    def _open_zip(self) -> zipfile.ZipFile:
        return zipfile.ZipFile(io.BytesIO(self.content))

    def list_sheets(self) -> List[_XlsxSheetInfo]:
        with self._open_zip() as z:
            workbook_xml = z.read("xl/workbook.xml")
            rels_xml = z.read("xl/_rels/workbook.xml.rels")

        rel_map: Dict[str, str] = {}
        rel_root = ET.fromstring(rels_xml)
        for rel in rel_root:
            rel_id = rel.attrib.get("Id")
            target = rel.attrib.get("Target", "")
            if not rel_id or "worksheets/" not in target:
                continue
            target = target.lstrip("/")
            if not target.startswith("xl/"):
                target = "xl/" + target
            rel_map[rel_id] = target

        root = ET.fromstring(workbook_xml)
        sheets_node = root.find(self.NS_MAIN + "sheets")
        sheets: List[_XlsxSheetInfo] = []
        if sheets_node is None:
            return sheets
        for sheet in sheets_node.findall(self.NS_MAIN + "sheet"):
            name = sheet.attrib.get("name", "")
            rel_id = sheet.attrib.get(self.NS_REL + "id", "")
            path = rel_map.get(rel_id, "")
            if name and path:
                sheets.append(_XlsxSheetInfo(name=name, path=path))
        return sheets

    def _load_shared_strings(self) -> List[str]:
        if self._shared_strings is not None:
            return self._shared_strings

        strings: List[str] = []
        with self._open_zip() as z:
            if "xl/sharedStrings.xml" not in z.namelist():
                self._shared_strings = []
                return self._shared_strings
            with z.open("xl/sharedStrings.xml") as f:
                for _event, elem in ET.iterparse(f, events=("end",)):
                    if elem.tag == self.NS_MAIN + "si":
                        parts = []
                        for text_node in elem.iter(self.NS_MAIN + "t"):
                            if text_node.text:
                                parts.append(text_node.text)
                        strings.append("".join(parts))
                        elem.clear()

        self._shared_strings = strings
        return strings

    def read_sheet(self, sheet_path: str) -> List[List[str]]:
        shared_strings = self._load_shared_strings()
        row_maps: Dict[int, Dict[int, str]] = {}
        max_row = -1
        max_col = -1

        with self._open_zip() as z:
            with z.open(sheet_path) as f:
                for _event, elem in ET.iterparse(f, events=("end",)):
                    if elem.tag != self.NS_MAIN + "row":
                        continue
                    row_number = int(elem.attrib.get("r", str(max_row + 2))) - 1
                    row_values: Dict[int, str] = {}
                    next_col = 0
                    for cell in elem.findall(self.NS_MAIN + "c"):
                        ref = cell.attrib.get("r", "")
                        _row_idx, col_idx = _cell_ref_to_row_col(ref) if ref else (row_number, next_col)
                        next_col = col_idx + 1
                        value = self._read_cell_value(cell, shared_strings)
                        if value:
                            row_values[col_idx] = value
                            max_col = max(max_col, col_idx)
                    if row_values:
                        row_maps[row_number] = row_values
                        max_row = max(max_row, row_number)
                    elem.clear()

        if max_row < 0 or max_col < 0:
            return []

        rows: List[List[str]] = []
        for row_idx in range(max_row + 1):
            values = row_maps.get(row_idx, {})
            rows.append([values.get(col_idx, "") for col_idx in range(max_col + 1)])

        while rows and not any(_safe_text(value) for value in rows[-1]):
            rows.pop()
        return rows

    def _read_cell_value(self, cell, shared_strings: List[str]) -> str:
        cell_type = cell.attrib.get("t")
        if cell_type == "inlineStr":
            parts = []
            for text_node in cell.iter(self.NS_MAIN + "t"):
                if text_node.text:
                    parts.append(text_node.text)
            return _safe_text("".join(parts))

        value_node = cell.find(self.NS_MAIN + "v")
        raw = value_node.text if value_node is not None else ""
        if raw is None:
            return ""

        if cell_type == "s":
            try:
                idx = int(raw)
                return _safe_text(shared_strings[idx] if idx < len(shared_strings) else raw)
            except Exception:
                return _safe_text(raw)
        if cell_type == "b":
            return "TRUE" if raw == "1" else "FALSE"
        return _safe_text(raw)


class GoogleSheetsWorkbookSourceService:
    XLSX_MIME_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    DOWNLOAD_TIMEOUT_SECONDS = 180
    DOWNLOAD_RETRIES = 3
    DOWNLOAD_CHUNK_SIZE = 1024 * 512

    def __init__(self, oauth_client_secret_path: Optional[Path] = None, oauth_token_path: Optional[Path] = None):
        appdata = Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming")))
        self.oauth_client_secret_path = oauth_client_secret_path or Path(
            os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET", appdata / "RuteoApp" / "google_oauth_client.json")
        )
        self.oauth_token_path = oauth_token_path or Path(
            os.environ.get("GOOGLE_OAUTH_TOKEN", appdata / "RuteoApp" / "google_token.json")
        )

    def load_workbook(self, source_url: str) -> WorkbookModel:
        spreadsheet_id = extract_spreadsheet_id(source_url)
        content = self._download_xlsx(spreadsheet_id)
        reader = _XlsxWorkbookBytesReader(content)
        sheet_infos = reader.list_sheets()
        sheets = []
        for info in sheet_infos:
            raw_rows = reader.read_sheet(info.path)
            sheets.append(self._sheet_model_from_rows(info.name, raw_rows))

        if not sheets:
            raise ValueError("Google Sheets no devolvió hojas para cargar.")

        print_sheet = self._choose_print_sheet(sheets)
        workbook_name = f"Google Sheets {spreadsheet_id[:8]}"
        return WorkbookModel(
            source_type="GoogleSheets",
            source_url=source_url,
            source_path="",
            workbook_name=workbook_name,
            loaded_at=datetime.now().isoformat(timespec="seconds"),
            sheets=sheets,
            active_sheet_name=print_sheet,
            print_sheet_name=print_sheet,
        )

    def _download_xlsx(self, spreadsheet_id: str) -> bytes:
        oauth_error = None
        if self.oauth_client_secret_path.exists():
            try:
                return self._download_with_retries(
                    lambda: self._download_xlsx_with_oauth_once(spreadsheet_id),
                    "OAuth",
                )
            except Exception as exc:
                oauth_error = exc

        try:
            return self._download_with_retries(
                lambda: self._download_public_xlsx_once(spreadsheet_id),
                "enlace compartido",
            )
        except Exception as exc:
            if str(exc) == INCOMPLETE_READ_MESSAGE:
                raise RuntimeError(INCOMPLETE_READ_MESSAGE) from exc
            if oauth_error:
                if str(oauth_error) == INCOMPLETE_READ_MESSAGE:
                    raise RuntimeError(INCOMPLETE_READ_MESSAGE) from exc
                raise RuntimeError(
                    "No se pudo cargar Google Sheets con OAuth ni como archivo compartido. "
                    f"OAuth: {oauth_error}. Compartido: {exc}"
                ) from exc
            raise

    def _download_with_retries(self, download_action, source_label: str) -> bytes:
        last_error: Optional[Exception] = None
        for attempt in range(1, self.DOWNLOAD_RETRIES + 1):
            try:
                content = download_action()
                self._validate_xlsx_content(content)
                return content
            except IncompleteRead as exc:
                last_error = exc
            except _RetryableDownloadError as exc:
                last_error = exc
            except (socket.timeout, TimeoutError) as exc:
                last_error = exc
            except URLError as exc:
                if isinstance(exc.reason, IncompleteRead):
                    last_error = exc
                else:
                    raise RuntimeError("No se pudo conectar con Google Sheets. Revisa la conexión a internet.") from exc

            if attempt < self.DOWNLOAD_RETRIES:
                time.sleep(min(1.5 * attempt, 4.0))

        if isinstance(last_error, IncompleteRead) or (
            isinstance(last_error, URLError) and isinstance(last_error.reason, IncompleteRead)
        ):
            raise RuntimeError(INCOMPLETE_READ_MESSAGE) from last_error
        if last_error:
            raise RuntimeError(
                f"No se pudo descargar el Google Sheets desde {source_label} después de {self.DOWNLOAD_RETRIES} intentos. "
                "Verifica tu conexión e intenta nuevamente."
            ) from last_error
        raise RuntimeError("No se pudo descargar el Google Sheets. Intenta nuevamente.")

    def _validate_xlsx_content(self, content: bytes) -> None:
        sample = content[:300].lstrip().lower()
        if sample.startswith(b"<!doctype") or sample.startswith(b"<html"):
            raise RuntimeError("Google devolvió una página HTML en lugar del Excel. Revisa permisos del enlace.")
        if not zipfile.is_zipfile(io.BytesIO(content)):
            raise _RetryableDownloadError("Google no devolvió un archivo Excel válido.")

    def _read_response_content(self, response) -> bytes:
        chunks = []
        while True:
            try:
                chunk = response.read(self.DOWNLOAD_CHUNK_SIZE)
            except IncompleteRead as exc:
                if exc.partial:
                    chunks.append(exc.partial)
                raise
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks)

    def _download_public_xlsx_once(self, spreadsheet_id: str) -> bytes:
        export_url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/export?format=xlsx"
        request = Request(export_url, headers={"User-Agent": "RuteoPDF/1.0"})
        try:
            with urlopen(request, timeout=self.DOWNLOAD_TIMEOUT_SECONDS) as response:
                return self._read_response_content(response)
        except HTTPError as exc:
            raise RuntimeError(
                "Google no permitió descargar el libro. Verifica que el archivo esté compartido o configura OAuth."
            ) from exc

    def _download_xlsx_with_oauth_once(self, spreadsheet_id: str) -> bytes:
        try:
            from google.auth.transport.requests import Request as GoogleAuthRequest
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
            from googleapiclient.discovery import build
            from googleapiclient.http import MediaIoBaseDownload
        except Exception as exc:
            raise RuntimeError(
                "Faltan librerías Google. Instala google-api-python-client, google-auth y google-auth-oauthlib."
            ) from exc

        scopes = ["https://www.googleapis.com/auth/drive.readonly"]
        credentials = None
        if self.oauth_token_path.exists():
            credentials = Credentials.from_authorized_user_file(str(self.oauth_token_path), scopes)
        if credentials and credentials.expired and credentials.refresh_token:
            credentials.refresh(GoogleAuthRequest())
        if not credentials or not credentials.valid:
            flow = InstalledAppFlow.from_client_secrets_file(str(self.oauth_client_secret_path), scopes)
            credentials = flow.run_local_server(port=0)
        self.oauth_token_path.parent.mkdir(parents=True, exist_ok=True)
        self.oauth_token_path.write_text(credentials.to_json(), encoding="utf-8")

        service = build("drive", "v3", credentials=credentials)
        request = service.files().export_media(fileId=spreadsheet_id, mimeType=self.XLSX_MIME_TYPE)
        buffer = io.BytesIO()
        downloader = MediaIoBaseDownload(buffer, request)
        done = False
        while not done:
            _status, done = downloader.next_chunk()
        return buffer.getvalue()

    def _sheet_model_from_rows(self, name: str, raw_rows: List[List[str]]) -> SheetModel:
        if not raw_rows:
            return SheetModel(name=name, dataframe=[], headers=[], row_count=0, column_count=0, visible_rows=[])

        max_width = max(len(row) for row in raw_rows)
        normalized = [row + [""] * (max_width - len(row)) for row in raw_rows]
        headers = normalized[0]
        rows = [row for row in normalized[1:] if any(_safe_text(value) for value in row)]
        return SheetModel(
            name=name,
            dataframe=rows,
            headers=headers,
            row_count=len(rows),
            column_count=max_width,
            visible_rows=list(range(len(rows))),
        )

    def _choose_print_sheet(self, sheets: List[SheetModel]) -> str:
        names = [sheet.name for sheet in sheets]
        for preferred in ("CARGO (3)", "RUTEO"):
            if preferred in names:
                return preferred
        return names[0]


class GoogleSheetsConnectWindow(QDialog):
    load_finished = Signal(object)
    load_failed = Signal(str)

    def __init__(self, parent=None, service: Optional[GoogleSheetsWorkbookSourceService] = None):
        super().__init__(parent)
        self.setWindowTitle("GoogleSheetsConnectWindow")
        self.setModal(True)
        self.resize(620, 240)
        self.service = service or GoogleSheetsWorkbookSourceService()
        self.loaded_workbook: Optional[WorkbookModel] = None
        self._current_thread: Optional[threading.Thread] = None

        self.load_finished.connect(self._on_load_finished)
        self.load_failed.connect(self._on_load_failed)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)

        info = QLabel("Pega el enlace del archivo de Google Sheets compartido")
        info.setWordWrap(True)
        layout.addWidget(info)

        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("Enlace de Google Sheets")
        layout.addWidget(self.url_input)

        self.status_label = QLabel("Sin conectar")
        self.status_label.setObjectName("estado")
        layout.addWidget(self.status_label)

        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        layout.addWidget(self.progress)

        buttons = QHBoxLayout()
        self.connect_button = QPushButton("Conectar con Google")
        self.load_button = QPushButton("Cargar libro")
        self.cancel_button = QPushButton("Cancelar")
        self.load_button.setObjectName("botonPrimario")
        self.connect_button.clicked.connect(self._validate_link)
        self.load_button.clicked.connect(self._load_workbook)
        self.cancel_button.clicked.connect(self.reject)
        buttons.addStretch(1)
        buttons.addWidget(self.connect_button)
        buttons.addWidget(self.load_button)
        buttons.addWidget(self.cancel_button)
        layout.addLayout(buttons)

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        layout.addWidget(line)

        note = QLabel("La ventana solo obtiene el libro; la tabla, filtros y PDFs siguen usando el flujo principal.")
        note.setAlignment(Qt.AlignLeft)
        note.setWordWrap(True)
        layout.addWidget(note)

    def _validate_link(self) -> Optional[str]:
        try:
            spreadsheet_id = extract_spreadsheet_id(self.url_input.text())
        except ValueError as exc:
            QMessageBox.warning(self, "Enlace inválido", str(exc))
            self.status_label.setText(str(exc))
            return None
        self.status_label.setText(f"Enlace válido. Spreadsheet ID: {spreadsheet_id}")
        return spreadsheet_id

    def _load_workbook(self):
        spreadsheet_id = self._validate_link()
        if not spreadsheet_id:
            return
        source_url = self.url_input.text().strip()
        self.loaded_workbook = None
        self._set_loading(True)

        def runner():
            try:
                workbook = self.service.load_workbook(source_url)
            except Exception as exc:
                self.load_failed.emit(str(exc))
            else:
                self.load_finished.emit(workbook)

        self._current_thread = threading.Thread(target=runner, daemon=True)
        self._current_thread.start()

    def _set_loading(self, loading: bool):
        self.connect_button.setEnabled(not loading)
        self.load_button.setEnabled(not loading)
        self.url_input.setEnabled(not loading)
        self.load_button.setText("Cargando..." if loading else "Cargar libro")
        self.progress.setRange(0, 0 if loading else 1)
        if not loading:
            self.progress.setValue(0)
        self.status_label.setText("Cargando libro completo desde Google Sheets..." if loading else self.status_label.text())

    def _on_load_finished(self, workbook: WorkbookModel):
        self._set_loading(False)
        self.loaded_workbook = workbook
        self.status_label.setText(f"Libro cargado: {len(workbook.sheets)} hoja(s)")
        self.accept()

    def _on_load_failed(self, message: str):
        self._set_loading(False)
        self.loaded_workbook = None
        self.status_label.setText(message or "No se pudo cargar el libro.")
        self.load_button.setText("Volver a intentar")
        QMessageBox.critical(self, "Google Sheets", message)
