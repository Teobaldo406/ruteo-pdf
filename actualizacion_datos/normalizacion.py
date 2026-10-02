# -*- coding: utf-8 -*-
"""Normalización conservadora de encabezados, identificadores, fechas y horas."""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Dict, Mapping, Optional, Sequence

from .configuracion import ConfiguracionProcesamiento


def normalizar_encabezado(valor: object) -> str:
    texto = "" if valor is None else str(valor).strip()
    texto = "".join(
        caracter for caracter in unicodedata.normalize("NFKD", texto)
        if not unicodedata.combining(caracter)
    )
    texto = re.sub(r"[^A-Za-z0-9]+", "_", texto).strip("_")
    return texto.upper()


def normalizar_identificador(valor: object) -> str:
    texto = re.sub(r"\s+", "", "" if valor is None else str(valor))
    coincidencia = re.fullmatch(r"([+-]?\d+)\.0+", texto)
    if coincidencia:
        return coincidencia.group(1)
    # Excel suele serializar identificadores largos con notación científica.
    # Solo se expande cuando representa un entero; nunca se redondea.
    if re.fullmatch(r"[+-]?\d+(?:\.\d+)?[Ee][+-]?\d+", texto):
        try:
            numero = Decimal(texto)
        except InvalidOperation:
            return texto
        if numero == numero.to_integral_value():
            return format(numero, "f").split(".", 1)[0]
    return texto


def normalizar_texto(valor: object) -> str:
    return re.sub(r"\s+", " ", "" if valor is None else str(valor)).strip()


def normalizar_decimal(valor: object) -> Optional[Decimal]:
    texto = normalizar_texto(valor)
    if not texto:
        return None
    texto = texto.replace(" ", "")
    if texto.count(",") == 1 and texto.count(".") == 0:
        texto = texto.replace(",", ".")
    try:
        return Decimal(texto)
    except InvalidOperation as error:
        raise ValueError(f"El valor '{valor}' no es numérico.") from error


def normalizar_fecha(valor: object) -> str:
    if isinstance(valor, datetime):
        return valor.date().isoformat()
    if isinstance(valor, date):
        return valor.isoformat()
    texto = normalizar_texto(valor)
    if not texto:
        return ""
    if re.fullmatch(r"\d+(?:\.0+)?", texto):
        numero = int(Decimal(texto))
        if 1 <= numero <= 2958465:
            return (datetime(1899, 12, 30) + timedelta(days=numero)).date().isoformat()
    formatos = (
        "%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%Y/%m/%d",
        "%d/%m/%y", "%d-%m-%y",
    )
    for formato in formatos:
        try:
            return datetime.strptime(texto, formato).date().isoformat()
        except ValueError:
            continue
    raise ValueError(f"La fecha '{valor}' no tiene un formato reconocido.")


def normalizar_hora(valor: object) -> str:
    if isinstance(valor, datetime):
        return valor.strftime("%H:%M")
    texto = normalizar_texto(valor)
    if not texto:
        return ""
    if re.fullmatch(r"\d{1,2}", texto):
        hora = int(texto)
        if 0 <= hora <= 23:
            return f"{hora:02d}:00"
    if re.fullmatch(r"0?\.\d+", texto):
        fraccion = Decimal(texto)
        minutos = int(fraccion * 24 * 60)
        return f"{minutos // 60:02d}:{minutos % 60:02d}"
    # Los CSV exportados con configuración regional española utilizan coma
    # como separador entre hora y minuto (por ejemplo, ``14,58``).
    coincidencia = re.fullmatch(r"(\d{1,2})[:.,](\d{2})", texto)
    if coincidencia:
        hora, minuto = map(int, coincidencia.groups())
        if 0 <= hora <= 23 and 0 <= minuto <= 59:
            return f"{hora:02d}:{minuto:02d}"
    if re.fullmatch(r"\d{1,2}\.\d", texto):
        raise ValueError(
            f"La hora '{valor}' es ambigua: falta confirmar si el decimal representa minutos."
        )
    raise ValueError(f"La hora '{valor}' no tiene un formato reconocido.")


def hora_a_minutos(valor: object) -> int:
    hora = normalizar_hora(valor)
    if not hora:
        raise ValueError("La hora está vacía.")
    horas, minutos = map(int, hora.split(":"))
    return horas * 60 + minutos


def resolver_columnas(
    encabezados: Sequence[str], configuracion: ConfiguracionProcesamiento
) -> Dict[str, str]:
    normalizados: Dict[str, str] = {}
    for encabezado in encabezados:
        clave = normalizar_encabezado(encabezado)
        normalizados.setdefault(clave, encabezado)
    resultado: Dict[str, str] = {}
    for canonica, alias in configuracion.alias_columnas.items():
        for candidato in (canonica, *alias):
            encontrada = normalizados.get(normalizar_encabezado(candidato))
            if encontrada is not None:
                resultado[canonica] = encontrada
                break
    return resultado


def normalizar_fila(
    fila: Mapping[str, object],
    columnas: Mapping[str, str],
) -> Dict[str, str]:
    datos: Dict[str, str] = {}
    for canonica, original in columnas.items():
        valor = fila.get(original, "")
        if canonica in {"OT", "OS", "NIS", "ACC", "COO", "ACTIVIDAD"}:
            datos[canonica] = normalizar_identificador(valor)
        elif canonica in {"TIPO", "TIPO_OS", "ESTADO"}:
            datos[canonica] = normalizar_texto(valor).upper()
        elif canonica == "FECHA":
            try:
                datos[canonica] = normalizar_fecha(valor)
            except ValueError:
                datos[canonica] = normalizar_texto(valor)
        elif canonica in {"HI", "HF"}:
            try:
                datos[canonica] = normalizar_hora(valor)
            except ValueError:
                # Se conserva el valor recibido para que la etapa de reglas lo
                # envíe a revisión con evidencia, sin ocultarlo ni inventarlo.
                datos[canonica] = normalizar_texto(valor)
        else:
            datos[canonica] = normalizar_texto(valor)
    observacion = datos.get("OBS", "")
    horas_observacion = re.search(
        r"HI\s*:\s*(\d{1,2}:\d{2})\s*HF\s*:\s*(\d{1,2}:\d{2})",
        observacion,
        re.IGNORECASE,
    )
    if horas_observacion:
        for indice, campo in enumerate(("HI", "HF"), start=1):
            recibido = datos.get(campo, "")
            ambiguo = re.fullmatch(r"(\d{1,2})[.,](\d)", recibido)
            confirmado = horas_observacion.group(indice)
            if not ambiguo:
                continue
            hora_recibida, decena_minuto = map(int, ambiguo.groups())
            hora_confirmada, minuto_confirmado = map(int, confirmado.split(":"))
            if hora_recibida == hora_confirmada and decena_minuto == minuto_confirmado // 10:
                datos[campo] = confirmado
    return datos
