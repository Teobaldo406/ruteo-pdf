# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class SheetModel:
    name: str
    dataframe: List[List[str]]
    headers: List[str]
    row_count: int
    column_count: int
    active_filters: Dict[str, str] = field(default_factory=dict)
    visible_rows: List[int] = field(default_factory=list)


@dataclass
class WorkbookModel:
    source_type: str
    source_url: str
    source_path: str
    workbook_name: str
    loaded_at: str
    sheets: List[SheetModel]
    active_sheet_name: str
    print_sheet_name: str

    def sheet_names(self) -> List[str]:
        return [sheet.name for sheet in self.sheets]

    def get_sheet(self, name: str) -> Optional[SheetModel]:
        for sheet in self.sheets:
            if sheet.name == name:
                return sheet
        return None

    def has_sheet(self, name: str) -> bool:
        return self.get_sheet(name) is not None

