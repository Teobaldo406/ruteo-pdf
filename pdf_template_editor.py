# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import os
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import Qt, QRectF, QSize
from PySide6.QtGui import QColor, QColorConstants, QFont, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


@dataclass
class PdfTemplateModel:
    TemplateId: str
    TemplateName: str
    TemplateType: str
    IsDefault: bool
    CompanyName: str
    Ruc: str
    Area: str
    ProjectName: str
    ReportTitle: str
    Subtitle: str
    ResponsibleName: str
    LogoPath: str
    PrimaryColor: str
    SecondaryColor: str
    FontFamily: str
    HeaderFontSize: int
    BodyFontSize: int
    ShowLogo: bool
    ShowDate: bool
    ShowTotalAssigned: bool
    ShowOperatorSignature: bool
    ShowSupervisorSignature: bool
    ObservationsText: str
    HeaderStyle: str
    UpdatedAt: str


class PdfTemplateService:
    def __init__(self, storage_path: Optional[Path] = None):
        self.storage_path = storage_path or self._default_storage_path()

    def _default_storage_path(self) -> Path:
        base = os.environ.get("APPDATA")
        if base:
            return Path(base) / "RuteoApp" / "Templates" / "pdf_templates.json"
        return Path.home() / "AppData" / "Roaming" / "RuteoApp" / "Templates" / "pdf_templates.json"

    def LoadTemplates(self) -> List[PdfTemplateModel]:
        if not self.storage_path.exists():
            return []
        try:
            raw = json.loads(self.storage_path.read_text(encoding="utf-8"))
        except Exception:
            return []
        templates = []
        for item in raw if isinstance(raw, list) else []:
            try:
                templates.append(PdfTemplateModel(**item))
            except TypeError:
                continue
        return templates

    def SaveTemplate(self, template: PdfTemplateModel) -> None:
        template.UpdatedAt = datetime.now().isoformat(timespec="seconds")
        templates = self.LoadTemplates()
        replaced = False
        for idx, existing in enumerate(templates):
            if existing.TemplateId == template.TemplateId:
                templates[idx] = template
                replaced = True
                break
        if not replaced:
            templates.append(template)
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self.storage_path.write_text(
            json.dumps([asdict(t) for t in templates], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def GetModernTemplate(self) -> Optional[PdfTemplateModel]:
        modern = [t for t in self.LoadTemplates() if t.TemplateType == "Modern"]
        defaults = [t for t in modern if t.IsDefault]
        return defaults[0] if defaults else (modern[0] if modern else None)

    def GetNormalTemplate(self) -> Optional[PdfTemplateModel]:
        normal = [t for t in self.LoadTemplates() if t.TemplateType == "Normal"]
        defaults = [t for t in normal if t.IsDefault]
        return defaults[0] if defaults else (normal[0] if normal else None)

    def SetDefaultTemplate(self, templateId: str) -> None:
        templates = self.LoadTemplates()
        selected_type = ""
        for template in templates:
            if template.TemplateId == templateId:
                selected_type = template.TemplateType
                break
        if not selected_type:
            return
        for template in templates:
            if template.TemplateType == selected_type:
                template.IsDefault = template.TemplateId == templateId
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self.storage_path.write_text(
            json.dumps([asdict(t) for t in templates], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def TemplateExists(self, templateType: str) -> bool:
        return any(t.TemplateType == templateType for t in self.LoadTemplates())

    def default_modern_template(self) -> PdfTemplateModel:
        return PdfTemplateModel(
            TemplateId=str(uuid.uuid4()),
            TemplateName="Plantilla moderna",
            TemplateType="Modern",
            IsDefault=True,
            CompanyName="",
            Ruc="",
            Area="",
            ProjectName="",
            ReportTitle="CARGO DE TRABAJO",
            Subtitle="",
            ResponsibleName="",
            LogoPath="",
            PrimaryColor="#0f172a",
            SecondaryColor="#dbeafe",
            FontFamily="Segoe UI",
            HeaderFontSize=14,
            BodyFontSize=9,
            ShowLogo=True,
            ShowDate=True,
            ShowTotalAssigned=True,
            ShowOperatorSignature=True,
            ShowSupervisorSignature=True,
            ObservationsText="",
            HeaderStyle="Moderno",
            UpdatedAt=datetime.now().isoformat(timespec="seconds"),
        )


def _safe_color(value: str, fallback: str) -> QColor:
    color = QColor(value or fallback)
    return color if color.isValid() else QColor(fallback)


class PdfTemplatePreview(QWidget):
    def __init__(self, template: PdfTemplateModel, parent=None):
        super().__init__(parent)
        self.template = template
        self.zoom = 1.0
        self.setMinimumSize(820, 620)

    def sizeHint(self) -> QSize:
        return QSize(920, 680)

    def set_template(self, template: PdfTemplateModel):
        self.template = template
        self.update()

    def set_zoom(self, zoom: float):
        self.zoom = max(0.65, min(1.5, zoom))
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor("#e8eef5"))

        page_w, page_h = 792.0, 612.0
        padding = 28
        scale = min((self.width() - padding * 2) / page_w, (self.height() - padding * 2) / page_h) * self.zoom
        scale = max(0.45, scale)
        draw_w = page_w * scale
        draw_h = page_h * scale
        page_x = (self.width() - draw_w) / 2
        page_y = max(18, (self.height() - draw_h) / 2)
        page_rect = QRectF(page_x, page_y, draw_w, draw_h)

        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(0, 0, 0, 35))
        painter.drawRect(QRectF(page_x + 6, page_y + 8, draw_w, draw_h))
        painter.setBrush(QColorConstants.White)
        painter.drawRect(page_rect)
        painter.setPen(QPen(QColor("#b6c2d1"), 1))
        painter.drawRect(page_rect)

        def rx(x: float) -> float:
            return page_x + x * scale

        def ry(y: float) -> float:
            return page_y + y * scale

        def rr(x: float, y: float, w: float, h: float) -> QRectF:
            return QRectF(rx(x), ry(y), w * scale, h * scale)

        def draw_text(rect: QRectF, text: str, size: int, color: QColor, bold=False, italic=False, align=Qt.AlignLeft):
            font = QFont(self.template.FontFamily or "Segoe UI")
            font.setPointSizeF(max(4.0, size * scale))
            font.setBold(bold)
            font.setItalic(italic)
            painter.setFont(font)
            painter.setPen(color)
            painter.drawText(rect.adjusted(4, 2, -4, -2), align | Qt.AlignVCenter | Qt.TextWordWrap, text or "")

        margin = 34
        content_w = page_w - margin * 2
        primary = _safe_color(self.template.PrimaryColor, "#0f172a")
        secondary = _safe_color(self.template.SecondaryColor, "#dbeafe")

        header_h = 92
        painter.setPen(Qt.NoPen)
        painter.setBrush(primary)
        painter.drawRect(rr(margin, margin, content_w, header_h))
        painter.setBrush(secondary)
        painter.drawRect(rr(margin, margin + header_h - 18, content_w, 18))

        logo_rect = rr(margin + 14, margin + 16, 60, 48)
        if self.template.ShowLogo and self.template.LogoPath and Path(self.template.LogoPath).exists():
            pixmap = QPixmap(self.template.LogoPath)
            if not pixmap.isNull():
                painter.drawPixmap(logo_rect.toRect(), pixmap)
            else:
                painter.setBrush(QColor("#f8fafc"))
                painter.drawRect(logo_rect)
        elif self.template.ShowLogo:
            painter.setBrush(QColor("#f8fafc"))
            painter.drawRect(logo_rect)
            draw_text(logo_rect, "LOGO", 8, QColor("#64748b"), True, align=Qt.AlignCenter)

        x_text = margin + 88 if self.template.ShowLogo else margin + 14
        draw_text(rr(x_text, margin + 12, content_w - 110, 22), self.template.CompanyName or "EMPRESA", self.template.HeaderFontSize, QColorConstants.White, True)
        draw_text(rr(x_text, margin + 36, content_w - 120, 18), f"RUC: {self.template.Ruc}" if self.template.Ruc else "RUC", 8, QColor("#e2e8f0"))
        area_project = " / ".join([x for x in [self.template.Area, self.template.ProjectName] if x])
        draw_text(rr(x_text, margin + 55, content_w - 120, 18), area_project or "AREA / PROYECTO", 8, QColor("#e2e8f0"))
        if self.template.ShowDate:
            draw_text(rr(margin + content_w - 120, margin + 14, 105, 18), "Fecha: ____/____/____", 7, QColor("#e2e8f0"), align=Qt.AlignRight)

        y = margin + header_h + 24
        draw_text(rr(margin, y, content_w, 25), self.template.ReportTitle or "CARGO DE TRABAJO", 16, QColor("#0f172a"), True, align=Qt.AlignCenter)
        draw_text(rr(margin, y + 28, content_w, 20), self.template.Subtitle or "Subtitulo", 10, QColor("#334155"), align=Qt.AlignCenter)
        draw_text(rr(margin, y + 58, content_w, 18), f"Responsable: {self.template.ResponsibleName or '__________'}", 9, QColor("#0f172a"))

        table_y = y + 88
        painter.setPen(QPen(QColor("#94a3b8"), 1))
        painter.setBrush(QColor("#f8fafc"))
        painter.drawRect(rr(margin, table_y, content_w, 135))
        draw_text(rr(margin, table_y + 48, content_w, 25), "Aqui se insertara automaticamente la tabla de registros", 11, QColor("#64748b"), True, align=Qt.AlignCenter)
        if self.template.ShowTotalAssigned:
            draw_text(rr(margin, table_y + 10, content_w - 12, 18), "TOTAL ASIGNADO: ___", 9, QColor("#0f172a"), True, align=Qt.AlignRight)

        obs_y = table_y + 150
        if self.template.ObservationsText:
            draw_text(rr(margin, obs_y, content_w, 42), self.template.ObservationsText, self.template.BodyFontSize, QColor("#0f172a"))
            obs_y += 50

        sig_y = obs_y + 34
        painter.setPen(QPen(QColor("#334155"), 1))
        if self.template.ShowOperatorSignature:
            painter.drawLine(rx(margin + 80), ry(sig_y), rx(margin + 260), ry(sig_y))
            draw_text(rr(margin + 80, sig_y + 3, 180, 18), "Firma operario", 8, QColor("#334155"), align=Qt.AlignCenter)
        if self.template.ShowSupervisorSignature:
            painter.drawLine(rx(margin + content_w - 260), ry(sig_y), rx(margin + content_w - 80), ry(sig_y))
            draw_text(rr(margin + content_w - 260, sig_y + 3, 180, 18), "Firma supervisor", 8, QColor("#334155"), align=Qt.AlignCenter)


class PdfTemplateEditorWindow(QDialog):
    def __init__(self, parent=None, service: Optional[PdfTemplateService] = None):
        super().__init__(parent)
        self.service = service or PdfTemplateService()
        self.template = self.service.GetModernTemplate() or self.service.default_modern_template()
        self._zoom = 1.0

        self.setWindowTitle("Editor de plantilla PDF moderna")
        self.resize(1280, 840)
        self.setMinimumSize(1120, 720)

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        self.tabs = QTabWidget()
        self.tabs.setFixedHeight(82)
        self.tabs.addTab(self._crear_tab_inicio(), "Inicio")
        self.tabs.addTab(self._crear_tab_insertar(), "Insertar")
        self.tabs.addTab(self._crear_tab_diseno(), "Diseno")
        self.tabs.addTab(self._crear_tab_vista(), "Vista")
        root.addWidget(self.tabs)

        body = QHBoxLayout()
        body.setSpacing(10)
        root.addLayout(body, 1)

        panel = QFrame()
        panel.setObjectName("panel")
        panel.setFixedWidth(330)
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(12, 10, 12, 10)
        panel_layout.setSpacing(8)
        panel_layout.addWidget(QLabel("Datos de plantilla"))

        form = QGridLayout()
        form.setHorizontalSpacing(8)
        form.setVerticalSpacing(7)
        panel_layout.addLayout(form)

        self.empresa = self._line(self.template.CompanyName)
        self.ruc = self._line(self.template.Ruc)
        self.area = self._line(self.template.Area)
        self.proyecto = self._line(self.template.ProjectName)
        self.titulo = self._line(self.template.ReportTitle)
        self.subtitulo = self._line(self.template.Subtitle)
        self.responsable = self._line(self.template.ResponsibleName)
        self.logo = self._line(self.template.LogoPath)
        self.color_primario = self._line(self.template.PrimaryColor)
        self.color_secundario = self._line(self.template.SecondaryColor)
        self.estilo = QComboBox()
        self.estilo.addItems(["Clasico", "Moderno", "Corporativo"])
        self.estilo.setCurrentText(self.template.HeaderStyle if self.template.HeaderStyle in {"Clasico", "Moderno", "Corporativo"} else "Moderno")
        self.observaciones = QTextEdit(self.template.ObservationsText)
        self.observaciones.setFixedHeight(72)
        self.check_logo = QCheckBox("Mostrar logo")
        self.check_fecha = QCheckBox("Mostrar fecha")
        self.check_total = QCheckBox("Mostrar total asignado")
        self.check_operario = QCheckBox("Firma operario")
        self.check_supervisor = QCheckBox("Firma supervisor")
        self.check_logo.setChecked(self.template.ShowLogo)
        self.check_fecha.setChecked(self.template.ShowDate)
        self.check_total.setChecked(self.template.ShowTotalAssigned)
        self.check_operario.setChecked(self.template.ShowOperatorSignature)
        self.check_supervisor.setChecked(self.template.ShowSupervisorSignature)

        row = 0
        for label, widget in [
            ("Empresa", self.empresa),
            ("RUC", self.ruc),
            ("Area / unidad", self.area),
            ("Proyecto / servicio", self.proyecto),
            ("Titulo principal", self.titulo),
            ("Subtitulo", self.subtitulo),
            ("Responsable", self.responsable),
            ("Ruta logo", self.logo),
            ("Color principal", self.color_primario),
            ("Color secundario", self.color_secundario),
            ("Estilo encabezado", self.estilo),
        ]:
            form.addWidget(QLabel(label), row, 0)
            form.addWidget(widget, row, 1)
            row += 1
        form.addWidget(QLabel("Observaciones"), row, 0)
        form.addWidget(self.observaciones, row, 1)
        row += 1

        for check in [self.check_logo, self.check_fecha, self.check_total, self.check_operario, self.check_supervisor]:
            form.addWidget(check, row, 0, 1, 2)
            row += 1

        panel_layout.addStretch(1)
        body.addWidget(panel)

        self.preview = PdfTemplatePreview(self.template)
        scroll = QScrollArea()
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.preview)
        body.addWidget(scroll, 1)

        bottom = QHBoxLayout()
        root.addLayout(bottom)
        bottom.addStretch(1)
        btn_preview = QPushButton("Vista previa")
        btn_save = QPushButton("Guardar plantilla")
        btn_cancel = QPushButton("Cancelar")
        btn_save.setObjectName("botonPrimario")
        btn_preview.clicked.connect(self._actualizar_preview)
        btn_save.clicked.connect(self._guardar)
        btn_cancel.clicked.connect(self.reject)
        bottom.addWidget(btn_preview)
        bottom.addWidget(btn_save)
        bottom.addWidget(btn_cancel)

        self._conectar_cambios()
        self._actualizar_preview()

    def _line(self, value: str) -> QLineEdit:
        line = QLineEdit(value or "")
        line.setFixedHeight(30)
        return line

    def _tool_tab(self, labels: List[str]) -> QWidget:
        tab = QWidget()
        layout = QHBoxLayout(tab)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        for label in labels:
            button = QPushButton(label)
            button.setMinimumHeight(30)
            layout.addWidget(button)
            if label == "Insertar logo":
                button.clicked.connect(self._elegir_logo)
            elif label == "Color principal":
                button.clicked.connect(lambda _=False: self._elegir_color(self.color_primario))
            elif label == "Color secundario":
                button.clicked.connect(lambda _=False: self._elegir_color(self.color_secundario))
            elif label == "Zoom +":
                button.clicked.connect(self._zoom_in)
            elif label == "Zoom -":
                button.clicked.connect(self._zoom_out)
            elif label == "Pagina completa":
                button.clicked.connect(self._zoom_reset)
        layout.addStretch(1)
        return tab

    def _crear_tab_inicio(self) -> QWidget:
        return self._tool_tab(["Negrita", "Cursiva", "Subrayado", "Fuente", "Tamano", "Color texto", "Color fondo", "Izquierda", "Centrar", "Derecha"])

    def _crear_tab_insertar(self) -> QWidget:
        return self._tool_tab(["Insertar logo", "Insertar empresa", "Insertar RUC", "Insertar titulo", "Insertar subtitulo", "Insertar responsable", "Insertar fecha", "Linea separadora", "Texto personalizado"])

    def _crear_tab_diseno(self) -> QWidget:
        return self._tool_tab(["Color principal", "Color secundario", "Clasico", "Moderno", "Corporativo", "Mostrar logo", "Mostrar firmas", "Observaciones"])

    def _crear_tab_vista(self) -> QWidget:
        return self._tool_tab(["Vista previa", "Zoom +", "Zoom -", "Pagina completa"])

    def _conectar_cambios(self):
        widgets = [
            self.empresa,
            self.ruc,
            self.area,
            self.proyecto,
            self.titulo,
            self.subtitulo,
            self.responsable,
            self.logo,
            self.color_primario,
            self.color_secundario,
        ]
        for widget in widgets:
            widget.textChanged.connect(self._actualizar_preview)
        self.estilo.currentTextChanged.connect(self._actualizar_preview)
        self.observaciones.textChanged.connect(self._actualizar_preview)
        for check in [self.check_logo, self.check_fecha, self.check_total, self.check_operario, self.check_supervisor]:
            check.stateChanged.connect(self._actualizar_preview)

    def _modelo_desde_campos(self) -> PdfTemplateModel:
        self.template.CompanyName = self.empresa.text().strip()
        self.template.Ruc = self.ruc.text().strip()
        self.template.Area = self.area.text().strip()
        self.template.ProjectName = self.proyecto.text().strip()
        self.template.ReportTitle = self.titulo.text().strip()
        self.template.Subtitle = self.subtitulo.text().strip()
        self.template.ResponsibleName = self.responsable.text().strip()
        self.template.LogoPath = self.logo.text().strip()
        self.template.PrimaryColor = self.color_primario.text().strip() or "#0f172a"
        self.template.SecondaryColor = self.color_secundario.text().strip() or "#dbeafe"
        self.template.HeaderStyle = self.estilo.currentText()
        self.template.ObservationsText = self.observaciones.toPlainText().strip()
        self.template.ShowLogo = self.check_logo.isChecked()
        self.template.ShowDate = self.check_fecha.isChecked()
        self.template.ShowTotalAssigned = self.check_total.isChecked()
        self.template.ShowOperatorSignature = self.check_operario.isChecked()
        self.template.ShowSupervisorSignature = self.check_supervisor.isChecked()
        return self.template

    def _actualizar_preview(self):
        self.preview.set_template(self._modelo_desde_campos())

    def _guardar(self):
        self.service.SaveTemplate(self._modelo_desde_campos())
        self.accept()

    def _elegir_logo(self):
        path, _ = QFileDialog.getOpenFileName(self, "Seleccionar logo", "", "Imagenes (*.png *.jpg *.jpeg *.bmp);;Todos (*.*)")
        if path:
            self.logo.setText(path)

    def _elegir_color(self, target: QLineEdit):
        color = QColorDialog.getColor(_safe_color(target.text(), "#0f172a"), self, "Elegir color")
        if color.isValid():
            target.setText(color.name())

    def _zoom_in(self):
        self._zoom += 0.1
        self.preview.set_zoom(self._zoom)

    def _zoom_out(self):
        self._zoom -= 0.1
        self.preview.set_zoom(self._zoom)

    def _zoom_reset(self):
        self._zoom = 1.0
        self.preview.set_zoom(self._zoom)
