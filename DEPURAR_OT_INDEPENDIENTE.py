# -*- coding: utf-8  CODIFICACION

# EXPLICACION  PASO PASO

import pandas as pd # IMPORTAMOS PANDAS BAJO EL ALIAS (pd) 
from pathlib import Path # IMPORTAMOS pathlib. PARA QUE SE USA PATHLIB? NOS AYUDA A TRABAJAR CON CARPETAS Y RUTAS


# ==============================================================
# 1 ESCRIBIR AQUÍ LAS RUTAS DE LOS ARCHIVOS
# ==============================================================

ruta_reaperturas = Path(r"C:\Users\ctcor\Downloads\REAPERTURAS.txt")
ruta_accion = Path(r"C:\Users\ctcor\Downloads\RESUELTAS_ACC.txt")
ruta_plantilla = Path(r"C:\Users\ctcor\Downloads\RESUELTAS_PLAN.txt")
ruta_salida = Path(r"C:\Users\ctcor\Downloads\RESULTADOS_DEPURACION_OT")


# ==============================================================
# 2 LEER LOS TRES ARCHIVOS TXT
# ==============================================================

# sep="\t" significa que las columnas están separadas por tabulaciones.
# dtype=str permite leer NIS y OT como identificadores de texto.
reaperturas = pd.read_csv(ruta_reaperturas, sep="\t", dtype=str, encoding="latin-1")
accion = pd.read_csv(ruta_accion, sep="\t", dtype=str, encoding="latin-1")
plantilla = pd.read_csv(ruta_plantilla, sep="\t", dtype=str, encoding="latin-1")


# ==============================================================
# 3 VALIDAR LAS COLUMNAS NECESARIAS
# ==============================================================

if "nis_rad" not in reaperturas.columns:
    raise ValueError("Falta la columna nis_rad en REAPERTURAS")

if "nis_rad" not in accion.columns or "nro_ot" not in accion.columns:
    raise ValueError("Falta nis_rad o nro_ot en ACCIÓN")

if "nro_ot" not in plantilla.columns:
    raise ValueError("Falta la columna nro_ot en PLANTILLA")


# ==============================================================
# 4 LIMPIAR LOS IDENTIFICADORES
# ==============================================================

# Se crean listas limpias para comparar sin cambiar las columnas originales.
nis_reaperturas = reaperturas["nis_rad"].fillna("").str.replace(" ", "").str.replace(r"\.0+$", "", regex=True)
nis_accion = accion["nis_rad"].fillna("").str.replace(" ", "").str.replace(r"\.0+$", "", regex=True)
ot_accion = accion["nro_ot"].fillna("").str.replace(" ", "").str.replace(r"\.0+$", "", regex=True)
ot_plantilla = plantilla["nro_ot"].fillna("").str.replace(" ", "").str.replace(r"\.0+$", "", regex=True)


# ==============================================================
# 5 PRIMER CRUCEDEPURAR ACCIÓN
# ===================================================================================

# Conserva solamente los NIS de ACCIÓN que no aparecen en REAPERTURAS
accion_depurada = accion[~nis_accion.isin(nis_reaperturas)]


# ==============================================================_____________________________
# 6 SEGUNDO CRUCE DEPURAR PLANTILLA
# ==============================================================

# Conserva las filas de PLANTILLA cuya OT aparece en ACCIÓN DEPURADA.
ot_accion_depurada = ot_accion[accion_depurada.index]
plantilla_depurada = plantilla[ot_plantilla.isin(ot_accion_depurada)]


# ==============================================================
# 7 GUARDAMOS  LOS RESULTADOS
# ==============================================================

ruta_salida.mkdir(parents=True, exist_ok=True)

archivo_accion = ruta_salida / "ACCION_DEPURADA.csv"
archivo_plantilla = ruta_salida / "PLANTILLA_DEPURADA.csv"

accion_depurada.to_csv(archivo_accion, index=False, encoding="utf-8-sig")
plantilla_depurada.to_csv(archivo_plantilla, index=False, encoding="utf-8-sig")


# ==============================================================
# 8 FINALMENTE  MOSTRAMOS EL  RESUMEN
# ==============================================================

print("PROCESO TERMINADO CORRECTAMENTE")
print("Acción original:", len(accion))
print("Acción depurada:", len(accion_depurada))
print("Plantilla original:", len(plantilla))
print("Plantilla depurada:", len(plantilla_depurada))
print("Archivo generado:", archivo_accion)
print("Archivo generado:", archivo_plantilla)


  