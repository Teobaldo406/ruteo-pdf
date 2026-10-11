# -*- coding: utf-8 -*-
"""Exportación de los cuatro TXT y los dos libros de revisión visibles."""

from __future__ import annotations

import csv
import os
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Sequence, Tuple
from xml.sax.saxutils import escape

from .configuracion import ConfiguracionProcesamiento, ContratoTxt
from .modelos import (
    CategoriaResultado,
    EstadoFila,
    ProcesoBloqueadoError,
    RegistroProcesamiento,
)
from .normalizacion import normalizar_decimal


ENCABEZADOS_BLOQUE_OPERATIVO = {
    "NULL": "OT",
    "COLUMNA_51": "OS",
    "COLUMNA_52": "FECHA",
    "COLUMNA_53": "HI",
    "COLUMNA_54": "HF",
    "COLUMNA_55": "ACC",
    "COLUMNA_56": "CO",
    "COLUMNA_57": "OBS",
    "COLUMNA_58": "LECT",
}

COLUMNAS_DATA_FILTRADA_REVISION = (
    ("TIPO", "TIPO"),
    ("OBS TIPO", "OBS_TIPO"),
    ("NIS_RAD", "NIS"),
)


@dataclass(frozen=True)
class RutasSalida:
    raiz: Path
    cierres: Path
    reaperturas: Path
    # Alias conservados para no romper consumidores existentes. Todos apuntan
    # a las dos carpetas públicas; ya no crean directorios técnicos separados.
    data_filtrada: Path
    errores_validacion: Path
    accion_invalida: Path
    revisar_lectura: Path
    cierres_listos: Path
    entregable_cierres: Path
    reaperturas_listas: Path
    entregable_reaperturas: Path
    auditoria: Path


def crear_estructura_salida(
    carpeta_base: Path,
    id_ejecucion: str,
    fecha: str,
    *,
    incluir_cierres: bool = True,
    crear_reaperturas: bool = True,
) -> RutasSalida:
    del id_ejecucion  # La salida pública se agrupa solo por la fecha elegida.
    fecha_limpia = ""
    for formato in ("%Y-%m-%d", "%Y%m%d", "%d/%m/%Y", "%d%m%Y"):
        try:
            fecha_limpia = datetime.strptime(fecha, formato).strftime("%d%m%Y")
            break
        except ValueError:
            continue
    if not fecha_limpia:
        digitos = "".join(caracter for caracter in fecha if caracter.isdigit())
        fecha_limpia = digitos or datetime.now().strftime("%d%m%Y")
    raiz = Path(carpeta_base) / f"SALIDA_{fecha_limpia}"
    cierres = raiz / "CIERRES"
    reaperturas = raiz / "REAPERTURAS"
    if incluir_cierres:
        cierres.mkdir(parents=True, exist_ok=True)
    if crear_reaperturas:
        reaperturas.mkdir(parents=True, exist_ok=True)
    return RutasSalida(
        raiz=raiz,
        cierres=cierres,
        reaperturas=reaperturas,
        data_filtrada=raiz,
        errores_validacion=raiz,
        accion_invalida=raiz,
        revisar_lectura=raiz,
        cierres_listos=cierres,
        entregable_cierres=cierres,
        reaperturas_listas=reaperturas,
        entregable_reaperturas=reaperturas,
        auditoria=raiz,
    )


def ruta_unica(carpeta: Path, nombre: str) -> Path:
    carpeta.mkdir(parents=True, exist_ok=True)
    candidata = carpeta / nombre
    if not candidata.exists():
        return candidata
    base, sufijo = candidata.stem, candidata.suffix
    correlativo = 2
    while True:
        candidata = carpeta / f"{base}_{correlativo}{sufijo}"
        if not candidata.exists():
            return candidata
        correlativo += 1


def _formatear_fecha(valor: str, formato: str) -> str:
    if not valor:
        return ""
    try:
        return datetime.strptime(valor, "%Y-%m-%d").strftime(formato)
    except ValueError:
        return valor


def _formatear_hora(valor: str, formato: str) -> str:
    if not valor:
        return ""
    try:
        return datetime.strptime(valor, "%H:%M").strftime(formato)
    except ValueError:
        return valor


def _filas_contrato(
    registros: Sequence[RegistroProcesamiento], contrato: ContratoTxt
) -> List[List[str]]:
    if not contrato.confirmado:
        raise ProcesoBloqueadoError(
            f"El formato '{contrato.nombre}' está BLOQUEADO: falta confirmar columnas, encabezado y formato."
        )
    if not contrato.columnas:
        raise ProcesoBloqueadoError(f"El formato '{contrato.nombre}' no tiene columnas configuradas.")
    mapeo = dict(contrato.mapeo_columnas)
    filas: List[List[str]] = []
    for registro in registros:
        salida: List[str] = []
        for columna in contrato.columnas:
            interna = mapeo.get(columna, columna)
            if interna not in registro.datos_normalizados:
                raise ProcesoBloqueadoError(
                    f"El contrato '{contrato.nombre}' requiere '{columna}' y no define su origen interno."
                )
            valor = str(registro.datos_normalizados.get(interna, ""))
            if interna == "FECHA":
                valor = _formatear_fecha(valor, contrato.formato_fecha)
            elif interna in {"HI", "HF"}:
                valor = str(
                    registro.datos_normalizados.get(
                        f"{interna}_FINAL",
                        registro.datos_normalizados.get(f"{interna}_ORIGINAL", valor),
                    )
                )
            salida.append(valor)
        filas.append(salida)
    return filas


def _escribir_atomico(
    ruta: Path,
    columnas: Sequence[str],
    filas: Sequence[Sequence[str]],
    contrato: ContratoTxt,
) -> Path:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporal = tempfile.mkstemp(prefix=f".{ruta.stem}_", suffix=".tmp", dir=ruta.parent)
    os.close(descriptor)
    ruta_temporal = Path(temporal)
    try:
        with ruta_temporal.open("w", encoding=contrato.codificacion, newline="") as archivo:
            escritor = csv.writer(
                archivo, delimiter=contrato.delimitador, quotechar='"',
                quoting=csv.QUOTE_MINIMAL, lineterminator="\n",
            )
            if contrato.incluir_encabezado:
                escritor.writerow(columnas)
            escritor.writerows(filas)
        ruta_temporal.replace(ruta)
    finally:
        if ruta_temporal.exists():
            ruta_temporal.unlink()
    return ruta


def exportar_txt(
    registros: Sequence[RegistroProcesamiento],
    contrato: ContratoTxt,
    carpeta: Path,
    id_ejecucion: str,
    nombre_archivo: Optional[str] = None,
) -> Path:
    del id_ejecucion
    filas = _filas_contrato(registros, contrato)
    ruta = carpeta / (nombre_archivo or f"{contrato.nombre}.txt")
    return _escribir_atomico(ruta, contrato.columnas, filas, contrato)


def exportar_cierres(
    registros: Sequence[RegistroProcesamiento],
    configuracion: ConfiguracionProcesamiento,
    rutas: RutasSalida,
    id_ejecucion: str,
) -> Tuple[Path, Path]:
    # Ambos contratos se validan antes de escribir el primer archivo.
    _filas_contrato(registros, configuracion.contrato_cierres_sistema)
    _filas_contrato(registros, configuracion.contrato_entregable_cierres)
    sistema = exportar_txt(
        registros, configuracion.contrato_cierres_sistema, rutas.cierres_listos,
        id_ejecucion, "CIERRES_SISTEMA.txt",
    )
    entregable = exportar_txt(
        registros, configuracion.contrato_entregable_cierres, rutas.entregable_cierres,
        id_ejecucion, "ENTREGABLE_CIERRES.txt",
    )
    for registro in registros:
        registro.estado = EstadoFila.EXPORTADA
        registro.categoria_final = CategoriaResultado.PROCESADA
        registro.archivo_destino = str(sistema)
        registro.regla_final = "EXP-01"
        registro.etapa_final = "EXPORTACION_CIERRES"
        registro.motivo_final = "CIERRE_EXPORTADO"
        registro.registrar(
            "EXP-01", "EXPORTACION_CIERRES", CategoriaResultado.CONTINUA,
            "Cierre exportado para el sistema y el entregable.", str(sistema), str(entregable),
        )
    return sistema, entregable


def exportar_reaperturas(
    registros: Sequence[RegistroProcesamiento],
    configuracion: ConfiguracionProcesamiento,
    rutas: RutasSalida,
    id_ejecucion: str,
) -> Tuple[Path, Path]:
    _filas_contrato(registros, configuracion.contrato_reaperturas_sistema)
    _filas_contrato(registros, configuracion.contrato_entregable_reaperturas)
    sistema = exportar_txt(
        registros, configuracion.contrato_reaperturas_sistema, rutas.reaperturas_listas,
        id_ejecucion, "REAPERTURAS_SISTEMA.txt",
    )
    entregable = exportar_txt(
        registros, configuracion.contrato_entregable_reaperturas, rutas.entregable_reaperturas,
        id_ejecucion, "ENTREGABLE_REAPERTURAS.txt",
    )
    for registro in registros:
        registro.estado = EstadoFila.EXPORTADA
        registro.categoria_final = CategoriaResultado.PROCESADA
        registro.archivo_destino = str(sistema)
        registro.regla_final = "REA-09"
        registro.etapa_final = "EXPORTACION_REAPERTURAS"
        registro.motivo_final = "REAPERTURA_EXPORTADA"
        registro.registrar(
            "REA-09", "EXPORTACION_REAPERTURAS", CategoriaResultado.CONTINUA,
            "Reapertura exportada para el sistema y el entregable.", str(sistema), str(entregable),
        )
    return sistema, entregable


def _referencia_columna(indice: int) -> str:
    referencia = ""
    while indice:
        indice, resto = divmod(indice - 1, 26)
        referencia = chr(65 + resto) + referencia
    return referencia


def _valor_temporal(valor: object) -> str:
    """Representa ausencias como #N/D sin confundirlas con el cero real."""
    if valor is None or str(valor).strip() == "":
        return "#N/D"
    return str(valor)


def _encabezado_revision(columna: object) -> str:
    clave = "NULL" if columna is None else str(columna).strip().upper()
    return ENCABEZADOS_BLOQUE_OPERATIVO.get(clave, str(columna))


def _clave_encabezado_revision(columna: object) -> str:
    return str(columna).strip().upper().replace("_", " ")


def _columna_residual_vacia(
    columna: object, registros: Sequence[RegistroProcesamiento]
) -> bool:
    if str(columna).strip().upper() != "COLUMNA_59":
        return False
    return all(
        str(registro.datos_originales.get(columna, "") or "").strip() == ""
        for registro in registros
    )


def _diferencia_reapertura_para_revision(registro: RegistroProcesamiento) -> str:
    lectura_actual = registro.datos_normalizados.get("LECT")
    lectura_anterior = registro.datos_normalizados.get("LECTURA_CIERRE_ANTERIOR")
    try:
        actual = normalizar_decimal(lectura_actual)
        anterior = normalizar_decimal(lectura_anterior)
    except ValueError:
        return "#N/D"
    if actual is None or anterior is None:
        return "#N/D"
    diferencia = actual - anterior
    texto = format(diferencia, "f")
    if "." in texto:
        texto = texto.rstrip("0").rstrip(".")
    return texto or "0"


def _numero_excel_temporal(encabezado: str, valor: object) -> Optional[str]:
    if encabezado not in {
        "TEMPORAL_LECTURA_ANTERIOR",
        "TEMPORAL_LECTURA_CIERRE_ANTERIOR",
        "TEMPORAL_DIFERENCIA",
    }:
        return None
    if str(valor).strip().upper() == "#N/D":
        return None
    try:
        numero = normalizar_decimal(valor)
    except ValueError:
        return None
    if numero is None:
        return None
    return format(numero, "f")


def _ancho_columna_revision(encabezado: str) -> int:
    """Mantiene el libro compacto sin ocultar ni recortar la data original."""
    nombre = encabezado.strip().upper()
    if nombre in {"OBS TIPO", "DESC_ACTIVIDAD", "DESC_SUBACTIVIDAD", "VDESCRIPCION"}:
        return 16
    if nombre.startswith("TEMPORAL_"):
        return 18
    if nombre in {"FECHA", "LOTE RECEBIDO EM", "LOTE IMPORTADO EM", "EXECUTAR LOTE ATE"}:
        return 14
    if nombre in {"HI", "HF", "TIPO", "ACC", "CO", "LECT"}:
        return 9
    return 11


def _exportar_revision_xlsx(
    registros: Sequence[RegistroProcesamiento],
    registros_referencia: Sequence[RegistroProcesamiento],
    carpeta: Path,
    nombre_archivo: str,
    columnas_temporales: Sequence[Tuple[str, str]],
) -> Path:
    """Escribe un XLSX liviano con la fila original y cuatro datos temporales."""
    columnas_originales: List[object] = []
    vistas = set()
    for registro in [*registros_referencia, *registros]:
        for columna in registro.datos_originales:
            if _columna_residual_vacia(columna, registros):
                continue
            if columna not in vistas:
                vistas.add(columna)
                columnas_originales.append(columna)
    nombres_data_filtrada = {
        _clave_encabezado_revision(nombre)
        for nombre, _origen in COLUMNAS_DATA_FILTRADA_REVISION
    }
    columnas_originales = [
        columna
        for columna in columnas_originales
        if _clave_encabezado_revision(columna) not in nombres_data_filtrada
    ]
    posicion_vtipo = next(
        (
            indice + 1
            for indice, columna in enumerate(columnas_originales)
            if _clave_encabezado_revision(columna) == "VTIPO OS"
        ),
        None,
    )
    if posicion_vtipo is None:
        posicion_vtipo = next(
            (
                indice
                for indice, columna in enumerate(columnas_originales)
                if _encabezado_revision(columna) == "OT"
            ),
            len(columnas_originales),
        )
    descriptores_originales = [
        ("ORIGINAL", _encabezado_revision(columna), columna)
        for columna in columnas_originales
    ]
    for desplazamiento, (encabezado, origen) in enumerate(
        COLUMNAS_DATA_FILTRADA_REVISION
    ):
        descriptores_originales.insert(
            posicion_vtipo + desplazamiento,
            ("DATA_FILTRADA", encabezado, origen),
        )
    columnas_adicionales = [columna for columna, _origen in columnas_temporales]
    encabezados_originales = [
        encabezado for _tipo, encabezado, _origen in descriptores_originales
    ]
    columnas = encabezados_originales + columnas_adicionales
    filas = []
    for registro in registros:
        fila = []
        for tipo_origen, _encabezado, origen in descriptores_originales:
            if tipo_origen == "DATA_FILTRADA":
                fila.append(registro.datos_normalizados.get(origen, ""))
            else:
                fila.append(registro.datos_originales.get(origen, ""))
        for _columna, origen in columnas_temporales:
            if origen == "__MOTIVO_FINAL__":
                valor = registro.motivo_final
            elif origen == "__DIFERENCIA_REAPERTURA__":
                valor = _diferencia_reapertura_para_revision(registro)
            else:
                valor = registro.datos_normalizados.get(origen)
            fila.append(_valor_temporal(valor))
        filas.append(fila)

    def celda(
        referencia: str,
        valor: object,
        estilo: int = 0,
        numero: Optional[str] = None,
    ) -> str:
        if numero is not None:
            atributo = f' s="{estilo}"' if estilo else ""
            return f'<c r="{referencia}"{atributo}><v>{numero}</v></c>'
        texto = escape("" if valor is None else str(valor))
        atributo = f' s="{estilo}"' if estilo else ""
        return f'<c r="{referencia}" t="inlineStr"{atributo}><is><t xml:space="preserve">{texto}</t></is></c>'

    filas_xml = []
    encabezados_xml = []
    cantidad_originales = len(columnas_originales)
    for indice, valor in enumerate(columnas, 1):
        estilo = 1 if indice <= cantidad_originales else 2
        encabezados_xml.append(celda(f"{_referencia_columna(indice)}1", valor, estilo))
    filas_xml.append(
        '<row r="1" ht="28" customHeight="1">'
        + "".join(encabezados_xml)
        + "</row>"
    )
    for numero, valores in enumerate(filas, 2):
        celdas = []
        for indice, valor in enumerate(valores, 1):
            encabezado = columnas[indice - 1].upper()
            estilo = 3 if "OBS" in encabezado else 0
            numero_excel = _numero_excel_temporal(encabezado, valor)
            celdas.append(
                celda(
                    f"{_referencia_columna(indice)}{numero}",
                    valor,
                    estilo,
                    numero_excel,
                )
            )
        filas_xml.append(
            f'<row r="{numero}" ht="20" customHeight="1">'
            + "".join(celdas)
            + "</row>"
        )
    ultima_columna = _referencia_columna(len(columnas))
    anchos = "".join(
        f'<col min="{i}" max="{i}" width="{_ancho_columna_revision(columna)}" customWidth="1"/>'
        for i, columna in enumerate(columnas, 1)
    )
    hoja = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>'
        f'<cols>{anchos}</cols><sheetData>{"".join(filas_xml)}</sheetData>'
        f'<autoFilter ref="A1:{ultima_columna}{len(filas) + 1}"/>'
        '</worksheet>'
    )
    carpeta.mkdir(parents=True, exist_ok=True)
    ruta = carpeta / nombre_archivo
    descriptor, nombre_temporal = tempfile.mkstemp(
        prefix=f".{ruta.stem}_", suffix=".tmp", dir=carpeta
    )
    os.close(descriptor)
    ruta_temporal = Path(nombre_temporal)
    with zipfile.ZipFile(ruta_temporal, "w", zipfile.ZIP_DEFLATED) as libro:
        libro.writestr("[Content_Types].xml", '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/></Types>')
        libro.writestr("_rels/.rels", '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        libro.writestr("xl/workbook.xml", '<?xml version="1.0" encoding="UTF-8"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="REVISIONES" sheetId="1" r:id="rId1"/></sheets></workbook>')
        libro.writestr("xl/_rels/workbook.xml.rels", '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>')
        libro.writestr("xl/styles.xml", '<?xml version="1.0" encoding="UTF-8"?><styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><color rgb="FFFFFFFF"/><sz val="11"/><name val="Calibri"/></font></fonts><fills count="4"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FF17365D"/><bgColor indexed="64"/></patternFill></fill><fill><patternFill patternType="solid"><fgColor rgb="FFC65911"/><bgColor indexed="64"/></patternFill></fill></fills><borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="4"><xf numFmtId="49" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/><xf numFmtId="49" fontId="1" fillId="2" borderId="0" xfId="0" applyNumberFormat="1" applyFill="1" applyFont="1" applyAlignment="1"><alignment wrapText="1" vertical="center"/></xf><xf numFmtId="49" fontId="1" fillId="3" borderId="0" xfId="0" applyNumberFormat="1" applyFill="1" applyFont="1" applyAlignment="1"><alignment wrapText="1" vertical="center"/></xf><xf numFmtId="49" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1" applyAlignment="1"><alignment wrapText="1" vertical="top"/></xf></cellXfs></styleSheet>')
        libro.writestr("xl/worksheets/sheet1.xml", hoja)
    ruta_temporal.replace(ruta)
    return ruta


def exportar_revision_manual_cierres(
    registros: Sequence[RegistroProcesamiento],
    carpeta: Path,
    registros_referencia: Sequence[RegistroProcesamiento] = (),
) -> Path:
    return _exportar_revision_xlsx(
        registros,
        registros_referencia,
        carpeta,
        "REVISION_CIERRES.xlsx",
        (
            ("TEMPORAL_LECTURA_ANTERIOR", "LECTURA_TOMA"),
            ("TEMPORAL_DIFERENCIA", "DIFERENCIA"),
            ("TEMPORAL_VALIDACION", "VALIDACION_LECTURA"),
            ("TEMPORAL_MOTIVO_REVISION", "__MOTIVO_FINAL__"),
        ),
    )


def exportar_revision_manual_reaperturas(
    registros: Sequence[RegistroProcesamiento],
    carpeta: Path,
    registros_referencia: Sequence[RegistroProcesamiento] = (),
) -> Path:
    return _exportar_revision_xlsx(
        registros,
        registros_referencia,
        carpeta,
        "REVISION_REAPERTURAS.xlsx",
        (
            ("TEMPORAL_ACCION_CIERRE_ANTERIOR", "ACCION_CIERRE_ANTERIOR"),
            ("TEMPORAL_LECTURA_CIERRE_ANTERIOR", "LECTURA_CIERRE_ANTERIOR"),
            ("TEMPORAL_DIFERENCIA", "__DIFERENCIA_REAPERTURA__"),
            ("TEMPORAL_MOTIVO_REVISION", "MOTIVO_REVISION_MANUAL"),
        ),
    )


def exportar_tabla_interna(
    registros: Sequence[RegistroProcesamiento], carpeta: Path, nombre: str, id_ejecucion: str
) -> Path:
    columnas_datos: List[str] = []
    vistos = set()
    for registro in registros:
        for columna in registro.datos_normalizados:
            if columna not in vistos:
                vistos.add(columna)
                columnas_datos.append(columna)
    obligatorias = [
        "ID_FILA", "ETAPA", "CATEGORIA", "REGLA", "MOTIVO", "DESTINO",
        "OT", "OS", "NIS_RAD", "REGLA_PROVISIONAL",
    ]
    columnas = obligatorias + [columna for columna in columnas_datos if columna not in {
        "OT", "OS", "NIS", "REGLA_PROVISIONAL",
    }]
    ruta = ruta_unica(carpeta, f"{nombre}_{id_ejecucion}.csv")
    with ruta.open("w", encoding="utf-8-sig", newline="") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=columnas, delimiter=";", extrasaction="ignore")
        escritor.writeheader()
        for registro in registros:
            fila = {
                "ID_FILA": registro.id_fila,
                "ETAPA": registro.etapa_final,
                "CATEGORIA": registro.categoria_final.value,
                "MOTIVO": registro.motivo_final,
                "REGLA": registro.regla_final,
                "DESTINO": registro.archivo_destino or registro.estado.value,
                "OT": registro.ot,
                "OS": registro.os,
                "NIS_RAD": registro.nis,
                "REGLA_PROVISIONAL": registro.datos_normalizados.get("REGLA_PROVISIONAL", "NO"),
            }
            fila.update(registro.datos_normalizados)
            escritor.writerow(fila)
    return ruta
