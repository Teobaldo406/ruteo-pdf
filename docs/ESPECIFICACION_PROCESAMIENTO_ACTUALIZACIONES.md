# Especificación maestra — Procesamiento de actualizaciones

## Corrección oficial de entradas — 22/09/2026

Esta sección reemplaza cualquier referencia anterior a tres archivos separados de
actividades, operarios y lecturas.

Las entradas productivas del flujo común son exclusivamente:

1. **CSV SANSYS**, archivo principal del procesamiento (`ruta_csv_sansys`).
2. **Control GIO** (`ruta_control_gio`).
3. **Entregable acumulado** (`ruta_entregable_acumulado`).
4. **Libro de reglas y actualización** (`ruta_libro_reglas`).
5. Fecha de procesamiento.
6. Carpeta de salida.

El libro de reglas es un único XLSX y debe contener las hojas `ACTIVIDAD`,
`OPERARIO` y `LECT`. Sus nombres se comparan sin distinguir mayúsculas,
minúsculas ni espacios exteriores. El lector detecta la fila real de encabezado,
elimina únicamente filas completamente vacías y bloquea el proceso si falta una
hoja o no puede reconocer su encabezado.

La configuración JSON sigue siendo avanzada y opcional. No reemplaza el libro
Excel ni puede aprobar reglas de negocio pendientes. Para reaperturas se solicita
el entregable actualizado solamente después de completar cierres y generar el
entregable correspondiente.

Las muestras XLSX con una hoja equivalente a la entrada principal se conservan
solo para validación histórica; la entrada productiva es CSV SANSYS.

### Dirección definitiva del cruce de operarios

La hoja `OPERARIO` es una tabla de conversión parcial, no un catálogo completo.
El COO se busca únicamente en `CODIGO SYSACAO`. Si existe una equivalencia única
y completa, se reemplaza por `CODIGO GIO`. Si no existe, el COO se conserva y la
fila continúa con `SIN_CONVERSION_REQUERIDA`. Solo se envía a revisión por COO
vacío o ilegible, código GIO vacío o equivalencias SYSACAO contradictorias. La
auditoría conserva `COO_ORIGINAL`, `COO_ORIGINAL_SYSACAO`, `COO_FINAL_GIO` y
`ESTADO_CONVERSION`.

## Estado y autoridad del documento

- **Aplicación:** Aplicativo CyR.
- **Módulo provisional:** Procesamiento de actualizaciones.
- **Estado:** especificación funcional y técnica; implementación todavía no autorizada.
- **Línea base estable:** commit `c6f6c76`, «Respaldo estable antes del módulo de procesamiento de actualizaciones».
- **Fecha de consolidación:** 2026-09-21.
- **Autoridad:** este documento consolida el requerimiento original, la revisión de arquitectura, la inspección de archivos reales, el informe corregido y todas las correcciones posteriores. Será la fuente oficial para desarrollar el módulo.

Antes de comenzar cada fase, el responsable debe leer este documento completo para conocer las dependencias, pero solo puede modificar los archivos pertenecientes a la fase expresamente autorizada.

Cuando este documento marque algo como **PENDIENTE DE CONFIRMACIÓN**, no se puede convertir en regla automática ni inferir una respuesta a partir de frecuencias históricas. Las dos formulaciones en conflicto deben conservarse hasta recibir la muestra o decisión indicada.

## Índice

1. [Objetivo y alcance](#1-objetivo-y-alcance)
2. [Fuentes, precedencia y estados de las reglas](#2-fuentes-precedencia-y-estados-de-las-reglas)
3. [Arquitectura actual del aplicativo](#3-arquitectura-actual-del-aplicativo)
4. [Glosario](#4-glosario)
5. [Entradas requeridas](#5-entradas-requeridas)
6. [Archivos reales inspeccionados](#6-archivos-reales-inspeccionados)
7. [Flujo completo y dependencias](#7-flujo-completo-y-dependencias)
8. [Flujo común hasta DATA_FILTRADA](#8-flujo-común-hasta-data_filtrada)
9. [Separación por tipo](#9-separación-por-tipo)
10. [Rama de cierres y revisiones](#10-rama-de-cierres-y-revisiones)
11. [Dependencia del entregable actualizado](#11-dependencia-del-entregable-actualizado)
12. [Rama de reaperturas](#12-rama-de-reaperturas)
13. [Validación de acciones y matrices configurables](#13-validación-de-acciones-y-matrices-configurables)
14. [Auditoría, trazabilidad y conservación de filas](#14-auditoría-trazabilidad-y-conservación-de-filas)
15. [Carpetas y archivos de salida](#15-carpetas-y-archivos-de-salida)
16. [Formatos observados y formato pendiente de los TXT](#16-formatos-observados-y-formato-pendiente-de-los-txt)
17. [Modelos de datos](#17-modelos-de-datos)
18. [Arquitectura modular de Python](#18-arquitectura-modular-de-python)
19. [Interfaz PySide6](#19-interfaz-pyside6)
20. [Procesamiento con QThread](#20-procesamiento-con-qthread)
21. [Matriz de reglas confirmadas](#21-matriz-de-reglas-confirmadas)
22. [Reglas originales corregidas o en conflicto](#22-reglas-originales-corregidas-o-en-conflicto)
23. [Reglas pendientes de confirmación](#23-reglas-pendientes-de-confirmación)
24. [Plan de pruebas](#24-plan-de-pruebas)
25. [Plan de implementación por fases](#25-plan-de-implementación-por-fases)
26. [Riesgos técnicos](#26-riesgos-técnicos)
27. [Restricciones y protección de módulos existentes](#27-restricciones-y-protección-de-módulos-existentes)
28. [Criterios de aceptación del módulo](#28-criterios-de-aceptación-del-módulo)
29. [Control de cambios de esta especificación](#29-control-de-cambios-de-esta-especificación)

## 1. Objetivo y alcance

El módulo procesará datos operativos provenientes de CSV, TXT delimitado y XLSX para producir archivos de actualización de cierres y reaperturas.

En este contexto, **actualización** significa actualización de datos operativos. No significa actualizar la versión del programa, descargar versiones desde GitHub ni reemplazar el actualizador técnico existente.

El módulo debe permitir:

1. Cargar el CSV SANSYS y sus archivos auxiliares.
2. Conservar una copia íntegra de cada fila original.
3. Detectar problemas estructurales y normalizar encabezados e identificadores.
4. Seleccionar y filtrar la fecha que se procesará.
5. Excluir, con auditoría, las órdenes que ya aparezcan en el entregable acumulado.
6. Validar la pareja OT–OS, el estado, el operario, el tipo y la acción.
7. Construir una `DATA_FILTRADA` común.
8. Separar cierres/revisiones y reaperturas.
9. Procesar primero los cierres.
10. Generar el TXT del sistema y el entregable de cierres.
11. Pausar hasta que el usuario actualice el sistema externo y cargue el entregable actualizado.
12. Desbloquear y procesar las reaperturas.
13. Generar el TXT del sistema y el entregable de reaperturas.
14. Conservar todas las exclusiones, revisiones, errores y exportaciones con su motivo exacto.

El módulo será una página adicional dentro del `QStackedWidget` de la ventana principal. No abrirá una segunda ventana principal y no reutilizará el actualizador técnico del software.

## 2. Fuentes, precedencia y estados de las reglas

### 2.1 Fuentes consolidadas

Esta especificación utiliza conjuntamente:

1. El prompt funcional original del módulo.
2. La revisión de la arquitectura real de Aplicativo CyR.
3. El primer plan modular propuesto.
4. El informe técnico corregido.
5. La inspección de los TXT y XLSX reales disponibles.
6. La tabla consolidada de reglas.
7. Las correcciones posteriores sobre entregable acumulado, estados, pareja OT–OS, acciones, tipos, lecturas y horarios.
8. El plan obligatorio de implementación por fases.

### 2.2 Precedencia

Se aplicará este orden:

1. Corrección explícita posterior del usuario.
2. Regla explícita vigente del usuario.
3. Formato confirmado mediante un archivo canónico aceptado por el sistema externo.
4. Evidencia observada en muestras reales.
5. Propuesta técnica documentada.

Una muestra histórica demuestra que un valor existe, pero no lo convierte por sí sola en regla de negocio.

### 2.3 Estados

- **CONFIRMADA:** orden funcional vigente que puede implementarse cuando se autorice su fase.
- **OBSERVADA:** característica comprobada en una muestra real, todavía no necesariamente canónica.
- **PENDIENTE DE CONFIRMACIÓN:** necesita decisión expresa, catálogo oficial o archivo canónico.
- **SUPERADA:** formulación original reemplazada por una corrección posterior; se conserva para trazabilidad, pero no se implementa.
- **PROPUESTA TÉCNICA:** decisión de diseño recomendada que todavía no constituye regla de negocio.

## 3. Arquitectura actual del aplicativo

### 3.1 Tecnología comprobada

- Python 3.
- El proceso de compilación actual está preparado para Python 3.13 de 64 bits.
- PySide6 y Qt 6.
- Ventana principal `VentanaRuteo`, definida en `main.py`.
- Navegación principal con `QToolBar`, `QActionGroup` y `QStackedWidget`.
- Páginas operativas incrustadas en la misma ventana.
- Trabajadores con `QObject`, señales y `QThread` en los módulos que ya realizan procesos pesados.
- Empaquetado con PyInstaller mediante `crear_instalable.py`.
- Pruebas actuales con `unittest`; `pytest` está disponible como dependencia de desarrollo.
- El proyecto de Visual Studio `RUTEO_PYTHON_APP.pyproj` declara `main.py` como archivo de inicio.
- La versión publicada con esta implementación es `1.0.10`.

### 3.2 Inicio del programa

El punto de entrada activo es `main.py`. Antes de crear `QApplication` y `VentanaRuteo`, valida la instancia única de Windows. Luego configura el icono, crea la aplicación, instancia la ventana principal y ejecuta el bucle de Qt.

El constructor de `VentanaRuteo` llama a:

1. `_construir_menu()` para crear la barra superior.
2. `_construir_interfaz()` para crear el `QStackedWidget` y registrar sus páginas.

### 3.3 Navegación existente

Los módulos principales actuales son:

- Inicio.
- TXT CyR.
- Extractor de órdenes.
- Depuración OT.

Importar y Ayuda son acciones secundarias alineadas a la derecha. Cada acción principal selecciona una página del mismo `QStackedWidget`; el estado activo se conserva mediante acciones exclusivas marcables.

La integración futura deberá seguir exactamente ese patrón:

1. Importar la página nueva.
2. Crear una sola acción de navegación.
3. Conectarla a un método que seleccione la página.
4. Instanciar una sola página y agregarla a `stack_paginas`.
5. Respetar los bloqueos existentes cuando haya procesos activos.

### 3.4 Estilos y recursos

- La barra y los estilos generales se definen en `main.py`.
- Los módulos operativos utilizan `FondoModulosWidget` de `fondo_modulos.py` y `assets/fondo_modulos_hd.png`.
- La página nueva debe reutilizar los nombres de objeto, paneles, tipografía, colores, márgenes y fondo actuales. No debe introducir un tema general nuevo.

### 3.5 Patrón actual y patrón objetivo

El repositorio usa una separación práctica entre página y lógica en módulos como:

- `extractor_ordenes_pagina.py` / `extractor_ordenes.py`.
- `depuracion_ot_pagina.py` / `depuracion_ot.py`.

El nuevo módulo debe reforzar esa separación:

- Presentación y coordinación en `actualizacion_datos_pagina.py`.
- Reglas, lecturas, flujos, auditoría y exportación en el paquete `actualizacion_datos/`.
- Ninguna regla de negocio dentro de botones, diálogos o métodos de dibujo.

### 3.6 Dependencias actuales

`requirements.txt` no contiene actualmente `pandas` ni `openpyxl`. No se instalarán ni añadirán hasta la fase en que se autorice una decisión de lector. La especificación admite dos opciones:

1. Incorporarlas de manera explícita y actualizar también el empaquetado y sus pruebas.
2. Reutilizar o ampliar los lectores ligeros existentes cuando alcancen para el formato real.

La decisión queda **PENDIENTE DE CONFIRMACIÓN** antes de la Fase 2.

El empaquetado actual usa PyInstaller en modo `--onedir --windowed`, incorpora `assets/` y `VERSION`, y excluye componentes QtQuick/QML. Si posteriormente se autorizan dependencias tabulares nuevas, deberán declararse, comprobarse en el script de instalación y validarse dentro del EXE durante la Fase 9.

## 4. Glosario

- **ACC:** acción ejecutada.
- **Actividad:** código de actividad del control (`actividad`) y su texto (`desc_actividad`). Ambos forman contexto; ninguno debe usarse aisladamente.
- **CSV SANSYS:** archivo principal con las órdenes operativas.
- **Data de control/GIO:** fuente para validar OS, OT, estado y actividad.
- **DATA_FILTRADA:** filas que completaron el flujo común y quedan disponibles para separar ramas.
- **Entregable acumulado:** TXT histórico del usuario con órdenes ya actualizadas; se usa antes de separar ramas.
- **Entregable de cierres:** salida producida por este módulo para que el usuario realice la actualización externa.
- **Entregable actualizado de cierres:** archivo devuelto o completado después de la actualización externa; es requisito para procesar reaperturas.
- **Exclusión operativa:** fila válida que no corresponde procesar, por ejemplo ya actualizada o con estado conocido no actualizable. No es un error técnico.
- **Revisión manual:** fila cuyo significado o consistencia no permite una decisión automática segura.
- **Error técnico:** archivo ilegible, estructura imposible, dependencia ausente o fallo de ejecución.
- **OT, OS, NIS/`nis_rad`:** identificadores. Deben tratarse como texto.
- **Regla aplicada:** identificador estable de la decisión, por ejemplo `COM-03`.
- **Ejecución:** una corrida identificada de forma única, con configuración y archivos de entrada registrados.

## 5. Entradas requeridas

### 5.1 Entradas del flujo común

| Entrada | Momento | Función | Condición actual |
|---|---|---|---|
| CSV SANSYS | Inicio | Fuente de órdenes | La entrada productiva es CSV; XLSX se admite únicamente como muestra histórica de comparación. |
| Fecha de procesamiento | Inicio | Filtrar el CSV SANSYS | Obligatoria. Formato de presentación por definir en UI. |
| Entregable acumulado | Antes de separar ramas | Excluir órdenes ya actualizadas | TXT obligatorio; cruce inicial por OT. |
| Data de control/GIO | Flujo común | Validar OS–OT, estado y actividad | Buscar principalmente por OS y comprobar OT. |
| Catálogo de actividades | Flujo común | Relacionar tipo OS, TIPO y OBS TIPO/descripción | Libro canónico pendiente. |
| Tabla de operarios | Flujo común/cierres | Validar o convertir código de operario | Hay códigos GIO faltantes en la muestra. |
| Tabla de lecturas | Cierres | Obtener lectura de toma | Clave observada `NIS_RAD`; nombre definitivo pendiente. |
| Matriz de acciones | Ambas ramas | Determinar acciones esperadas, imposibilidades y equivalencias | La matriz histórica es auxiliar; falta matriz aprobada. |
| Carpeta de salida | Inicio | Alojar una ejecución sin sobrescribir otra | Obligatoria. |

### 5.2 Entrada diferida

| Entrada | Momento | Función | Condición |
|---|---|---|---|
| Entregable actualizado de cierres para reaperturas | Después de exportar cierres y de la actualización externa | Traer acción y lectura del cierre efectivo | Obligatorio para desbloquear reaperturas. Debe validarse y asociarse a la ejecución. |

### 5.3 Campos lógicos mínimos

La capa de normalización debe poder resolver estos campos sin destruir el encabezado original:

- OT.
- OS.
- FECHA/FEJECUCION.
- HI.
- HF.
- ACC/ACCION.
- COO/CODIGO de operario.
- OBS/OBSERVACION.
- LECT/lectura ejecutada.
- NIS, NISRA, IDRA o `nis_rad`, según decisión canónica.
- TIPO.
- OBS TIPO o descripción de tipo.
- `vtipo_os`.
- `actividad`.
- `desc_actividad`.
- Estado.

## 6. Archivos reales inspeccionados

| ARCHIVO | FUNCIÓN | HOJA | CLAVE | COLUMNAS UTILIZADAS | OBSERVACIONES |
|---|---|---|---|---|---|
| `GIO_17092026_PRUEBA_AUTOMATIZACION.txt` | Control de estado/proceso | No aplica | OS principal + OT de comprobación | `nro_ot`, `nis_rad`, `estado`, `nest_ot`, `actividad`, `desc_actividad`, `subactividad`, `desc_subactividad`, `vtipo_os`, `nnum_os` | TAB; 57 columnas; 51.845 filas; lectura tolerante ANSI occidental. Dos OS aparecen asociadas a más de una OT. |
| `C_extregable17072026.txt` | Entregable acumulado | No aplica | OT inicialmente | Diez posiciones de entregable | TAB; UTF-8 BOM; 230 filas; sin encabezado. NIS, OT y OS son únicos en esta muestra. |
| `ENTREGABLE PRUEBA.txt` | Referencia de entregable | No aplica | OT | `nis_rad`, `OT`, `OS`, `FEJECUCION`, `HI`, `HF`, `ACCION`, `CODIGO`, `OBSERVACION`, `LECT` | TAB; UTF-8 BOM; 54 filas; con encabezado. |
| `DATA_MUETTRAS.xlsx` | Muestra histórica equivalente al CSV SANSYS | `data_general` | OT, OS, NIS | Columnas generales | 36.449 registros declarados; no es la entrada productiva. |
| `DATA_MUETTRAS.xlsx` | Resultado manual de referencia | `DATA_FILTRADA` | OT–OS | TIPO, OBS TIPO, identificadores, fecha, horas, acción, operario, OBS, lectura y estados | Contiene el encabezado escrito `ESTDADO_OS`; no es contrato final. |
| `DATA_MUETTRAS.xlsx` | Copia de GIO | `GIO_17092026_PRUEBA_AUTOMATIZAC` | OS + OT | Estructura GIO | Misma familia del TXT de control. |
| `DATA PARA ACTUALIZADA(4).xlsx` | Prototipo manual | `DATTTAAA_FILTRADA` | OT–OS | Campos del flujo y validaciones manuales | 402 filas: V=287, R=76, C=14, RD=13, CD=12; no B. Encabezados duplicados y auxiliares ambiguos. |
| `DATA PARA ACTUALIZADA(4).xlsx` | Cierres manuales | `CIERRES y REVICIONES` | OT–OS | Tipo, acción, lecturas y diferencia | V=286, C=13, CD=8. Tres filas tienen una columna extra. |
| `DATA PARA ACTUALIZADA(4).xlsx` | Reaperturas manuales | `REAPERTURAS` | NIS/OT/OS | Acción/lectura de cierre y diferencia | R=18 y RD=2. |
| `DATA PARA ACTUALIZADA(4).xlsx` | Salida de referencia | `ENTREGABLE` | OT | Diez columnas del entregable | 335 filas. |
| `DATA PARA ACTUALIZADA(4).xlsx` | Actualización externa | `ACTUALIZAR_SYSACO` | OT | Diez columnas esperadas | Las filas contienen una columna auxiliar 11 sin encabezado; no exportarla por inferencia. |
| `DATA PARA ACTUALIZADA(4).xlsx` | Base de reaperturas | `ENTREGABLE_PARA_REAPERURAS` | NIS/OT/OS | Diez columnas esperadas | Cuatro filas tienen una columna 11 anómala. |
| `DATA PARA ACTUALIZAR (3).xlsx` | Clasificación | `ACTIVIDAD` | Tipo OS | Tipo OS, TIPO, fuente, descripción | Frecuencias observadas: C=19, R=19, RD=18, CD=16, V=14, VD=8; no B. Los encabezados son ambiguos. |
| `DATA PARA ACTUALIZAR (3).xlsx` | Operarios | `OPERARIO` | Operario | `OPER`, `CODIGO GIO`, `CODIGO SYSACAO` | Dos registros carecen de `CODIGO GIO`. |
| `DATA PARA ACTUALIZAR (3).xlsx` | Lecturas | `LECT` | `NIS_RAD` | `NIS_RAD`, `LECT` | La cabecera útil está en la fila 2; la fila 1 contiene auxiliares. |
| `Reglas_de_procesamiento_actualizacion.xlsx` | Posible configuración | `ACTIVIDAD`, `OPERARIO`, `LECT` | Según hoja | Mismas columnas anteriores | Estructura coincidente con `DATA PARA ACTUALIZAR (3).xlsx`; debe elegirse un canónico. |
| `MATRIZ_CODIGOS_PERSUASIVAS.xlsx` | Evidencia histórica de acciones | `Matriz` | Tipo OS + acción | Tipo OS, estados, código/descripcion, cantidad, porcentajes, principal, clasificación | 47 tipos OS, 56 códigos, 364 combinaciones. Varias acciones por tipo; texto con problemas de codificación. |
| `MATRIZ_CODIGOS_PERSUASIVAS.xlsx` | Calidad de matriz | `Calidad` | No aplica | Conteos de anchura | Registra filas excluidas por tener 50, 51 o 59 columnas en lugar del ancho esperado. |
| `REAPERTURAS.txt` | Muestra auxiliar GIO | No aplica | NIS/OT/OS | Estructura GIO | TAB; 57 columnas; 557 registros. |
| `RESUELTAS_ACC.txt` | Muestra auxiliar de resueltas | No aplica | NIS/OT/OS | Estructura GIO | 574 registros, todos `RESUL`. |
| `RESUELTAS_PLAN.txt` | Muestra auxiliar de plantilla | No aplica | NIS/OT/OS | 45 columnas | 1.082 registros. No define el contrato del módulo nuevo. |

### 6.1 Estados observados en GIO

| Código observado | Cantidad observada | Interpretación | Estado de la interpretación |
|---|---:|---|---|
| `TRAB` | 1.183 | TRABAJANDO | Debe formalizarse en catálogo. |
| `RESUL` | 21.122 | RESUELTA | Debe formalizarse en catálogo. |
| `ANUL` | 4.041 | ANULADA | Debe formalizarse en catálogo. |
| `PEND` | 1.320 | PENDIENTE | Debe formalizarse en catálogo. |
| `FAC` | 24.178 | Estado conocido no definido formalmente | PENDIENTE DE CONFIRMACIÓN. |
| `ATEN` | 1 | Estado conocido no definido formalmente | PENDIENTE DE CONFIRMACIÓN. |

Las cantidades son evidencia de una muestra y no deben fijarse como expectativas futuras.

## 7. Flujo completo y dependencias

La secuencia obligatoria es:

```text
Entradas comunes
  → lectura estructural y conservación del original
  → normalización
  → selección/filtro de fecha
  → cruce con entregable acumulado
  → validación OT–OS
  → clasificación del estado
  → validación de operario, actividad, tipo y contexto de acción
  → DATA_FILTRADA
  → separación C/CD/V y R/RD
      ├─ CIERRES Y REVISIONES
      │    → validar acciones/lecturas/horarios/OBS
      │    → TXT de cierres para el sistema
      │    → entregable de cierres
      │    → actualización externa realizada por el usuario
      │    → carga y validación del entregable actualizado
      └─ REAPERTURAS (bloqueada hasta el paso anterior)
           → seleccionar cierre efectivo más reciente
           → validar equivalencia y lectura
           → TXT de reaperturas para el sistema
           → entregable de reaperturas
  → cierre de auditoría y conciliación total de filas
```

### 7.1 Dependencias que nunca deben omitirse

1. La separación por tipo depende de `DATA_FILTRADA`.
2. `DATA_FILTRADA` depende del cruce previo con el entregable acumulado.
3. Los cierres se pueden procesar después del flujo común.
4. Las reaperturas pueden prepararse como subconjunto, pero no pueden completarse sin el entregable actualizado de cierres.
5. El entregable actualizado debe ser validado y vinculado a la ejecución. No se sustituirá silenciosamente por el entregable anterior.
6. Cada transición depende de que la etapa anterior tenga un resultado conciliado y auditable.

## 8. Flujo común hasta DATA_FILTRADA

### 8.1 Creación de la ejecución

Al comenzar se debe crear un identificador único de ejecución y registrar:

- Fecha y hora de inicio.
- Fecha operativa elegida.
- Usuario/equipo cuando sea técnicamente viable y no implique credenciales.
- Rutas, tamaño, fecha de modificación y huella de los archivos cargados.
- Versión de la configuración/matrices aplicada.
- Carpeta de salida.

### 8.2 Lectura estructural

1. Detectar tipo de archivo por extensión y contenido.
2. Para CSV/TXT, detectar o validar codificación, delimitador, encabezado y número de columnas.
3. Para XLSX, elegir la hoja configurada y detectar la fila real de encabezado.
4. Asignar a cada fila un `ID_FILA` estable que incluya archivo y número de fila.
5. Conservar la fila original antes de normalizar.
6. Detectar columnas desalineadas.
7. Corregir automáticamente solo si existe una correspondencia inequívoca y auditable. Una fila ambigua se conserva como error de lectura; no se desplazan valores por intuición.

La política exacta de reparación automática está **PENDIENTE DE CONFIRMACIÓN**.

### 8.3 Normalización

- Recortar espacios de encabezados y valores identificadores.
- Normalizar encabezados para búsquedas sin cambiar el encabezado original guardado.
- Tratar OT, OS, NIS, acciones y códigos como texto.
- Retirar exclusivamente terminaciones numéricas artificiales como `.0` cuando todo el valor sea un entero representado como decimal.
- Preservar ceros iniciales.
- No usar conversión flotante para identificadores.
- No generar notación científica.
- Resolver alias de columnas mediante configuración.
- Conservar columnas auxiliares en `datos_originales`, aunque se omitan de la tabla de trabajo.
- Normalizar fechas y horas a representaciones internas sin decidir todavía su formato de exportación.

### 8.4 Filtro de fecha

1. Presentar al usuario las fechas válidas detectadas o permitir elegir una fecha.
2. Filtrar solo la fecha seleccionada.
3. Las filas con fecha vacía o imposible deben ir a revisión/error de formato, nunca desaparecer.
4. Las filas de otra fecha constituyen una exclusión de alcance y deben quedar contabilizadas y auditadas si formaron parte del archivo cargado.

### 8.5 Cruce con el entregable acumulado

Este paso ocurre antes de separar cierres y reaperturas.

1. Leer y normalizar el entregable acumulado.
2. Verificar la existencia, completitud y unicidad de la clave.
3. Cruzar inicialmente por OT normalizada.
4. Si la OT aparece, excluirla del procesamiento nuevo.
5. Registrar el motivo `YA_ACTUALIZADA_EN_ENTREGABLE`.
6. Clasificarla como exclusión operativa, no como error.
7. Si no aparece, continuar.
8. Claves vacías, repetidas o que puedan multiplicar filas deben enviarse a revisión; no se permite un cruce muchos-a-muchos.

OT está confirmada como clave inicial y existe en las muestras, pero la clave canónica definitiva —OT sola o compuesta— permanece pendiente de una decisión final.

### 8.6 Validación de la pareja OT–OS

1. Prevalidar la unicidad de OS en el control.
2. Buscar principalmente por OS.
3. Recuperar la OT asociada a esa OS.
4. Compararla con la OT del CSV SANSYS.
5. Si ambas coinciden, la pareja es válida.
6. Si la OS existe pero pertenece a otra OT, enviar a `INCONSISTENCIA_OT_OS`.
7. Si la OT existe pero la OS no coincide, enviar también a `INCONSISTENCIA_OT_OS`.
8. Si la OS está duplicada o asociada a más de una OT, no escoger la primera coincidencia: enviar a revisión.
9. Si la OS no existe, enviar a revisión como OS no encontrada.

La inspección real refuta la suposición de unicidad perfecta: se observaron dos OS asociadas a varias OT. La validación de unicidad es obligatoria.

### 8.7 Tratamiento del estado

- `TRAB`/TRABAJANDO: continúa.
- NA, vacío u OS no encontrada: revisión manual.
- `RESUL`/RESUELTA, `ANUL`/ANULADA, `PEND`/PENDIENTE u otro estado conocido no actualizable: exclusión operativa auditada.
- Estado desconocido o no catalogado: no se interpreta por semejanza; la propuesta segura es revisión manual.
- Exclusiones operativas no se mezclan con errores técnicos.

La regla original «todo estado diferente de TRABAJANDO va a errores» queda SUPERADA.

### 8.8 Validación de operario

1. Resolver el operario contra la tabla de equivalencias.
2. Conservar código recibido, código GIO y código SYSACAO esperado.
3. Si no existe equivalencia, falta un código requerido o existe contradicción, enviar a revisión.
4. No inventar códigos ni tomar un valor de otra fila.

### 8.9 Contexto de actividad, tipo y acción

Antes de construir `DATA_FILTRADA`, relacionar:

- `vtipo_os`.
- `actividad` numérica.
- `desc_actividad` textual.
- TIPO.
- OBS TIPO/descripción.
- ACC ejecutada.
- Evidencia de la matriz de acciones.

La validación definitiva de ACC se desarrolla en la sección 13. Las ambigüedades deben impedir una aprobación automática, pero la fila puede preservarse en la categoría de revisión correspondiente.

### 8.10 Construcción de DATA_FILTRADA

`DATA_FILTRADA` contiene exclusivamente las filas que superaron las validaciones comunes y continúan al procesamiento de ramas. Debe conservar:

- Identificadores originales y normalizados.
- Campos operativos requeridos.
- Contexto de actividad/tipo.
- Código de operario resuelto.
- Historial de reglas aprobadas.
- Referencia a la fila original.

Al terminar la etapa se debe cumplir:

```text
filas_entrada_fecha
= filas_ya_actualizadas
 + exclusiones_estado
 + revisiones_validacion
 + errores_lectura
 + filas_DATA_FILTRADA
```

## 9. Separación por tipo

| Tipo | Rama | Estado |
|---|---|---|
| C | Cierres y revisiones | CONFIRMADA por reglas y muestras. |
| CD | Cierres y revisiones | CONFIRMADA por reglas y muestras. |
| V | Cierres y revisiones | CONFIRMADA por reglas y muestras. |
| R | Reaperturas | CONFIRMADA. |
| RD | Reaperturas | CONFIRMADA. |
| B | No procesar todavía | El prompt original lo incluyó en cierres, pero no existe evidencia real suficiente. PENDIENTE DE CONFIRMACIÓN. |
| VD | Rama no definida | Aparece en `ACTIVIDAD`, pero no en el resultado manual inspeccionado. PENDIENTE DE CONFIRMACIÓN. |
| Otro | Revisión | No asignar una rama por inferencia. |

Cada rama recibe una copia lógica de sus registros; la fila original y su identificador de auditoría se mantienen compartidos. La separación no debe duplicar una fila entre ramas.

## 10. Rama de cierres y revisiones

### 10.1 Alcance

Procesa C, CD y V. B queda explícitamente fuera hasta recibir evidencia y autorización.

### 10.2 Lectura de toma y diferencia

1. Obtener `LECTURA_TOMA` mediante el identificador NIS confirmado.
2. Validar que el cruce produzca como máximo una lectura inequívoca.
3. Calcular:

   `DIFERENCIA = LECTURA_EJECUTADA - LECTURA_TOMA`

4. Una lectura faltante, repetida, no numérica o ambigua no se reemplaza por cero: va a revisión.
5. Para las acciones a las que corresponda control de lectura:
   - Diferencia menor que 0: revisión, categoría `LECTURA_NEGATIVA`.
   - Diferencia de 0 a 300 inclusive: no excluir por esta regla.
   - Diferencia 280: válida por esta regla; no es un corte especial.
   - Diferencia mayor que 300: revisión, categoría `REVISAR_LECTURA`.

Existe un conflicto de alcance: el prompt original vinculó esta validación a determinadas acciones efectivas 506–529; la corrección confirmó los límites para cierres, pero exigió determinar la aplicabilidad usando tipo, descripción, actividad y matriz. Hasta recibir la matriz autorizada no se aplicará a todas las acciones por inferencia.

### 10.3 Corrección de HI/HF para tipo C

La corrección se aplica exclusivamente cuando:

- `TIPO == C`, y
- HI o HF representa 14:00 o una hora posterior.

Entonces debe:

1. Establecer tanto HI como HF en el valor interno equivalente a 12:00.
2. Sustituir solamente el fragmento de HI/HF dentro de OBS.
3. Preservar sin cambios el contenido posterior a `OBS:` y todo texto ajeno a ese fragmento.
4. Registrar valores antes/después y la regla aplicada.

No se aplica a CD, V, R ni RD.

Si OBS no contiene un patrón inequívoco o está incompleto, no se reconstruirá por intuición. El tratamiento final de este caso está pendiente; la opción segura propuesta es revisión manual.

La representación de exportación de las columnas permanece pendiente: las muestras usan punto (`12.00`) mientras la regla y OBS usan dos puntos (`12:00`).

### 10.4 Validación de acciones de cierre

La fila solo queda lista cuando la acción es coherente con:

- TIPO.
- OBS TIPO o descripción.
- `vtipo_os`.
- `actividad` y `desc_actividad`.
- Acción ejecutada.
- Matriz configurable aprobada.
- Clasificación de acción efectiva o imposibilidad permitida.

La matriz histórica se utiliza como evidencia, no como autoridad. Una contradicción debe ir a revisión mostrando acción recibida y esperada.

### 10.5 OBS

- Longitud máxima: 150 caracteres.
- Una OBS de 150 caracteres es aceptable.
- Una OBS de 151 o más va a revisión/error de OBS.
- La validación se realiza después de cualquier corrección autorizada, conservando también el texto original.

### 10.6 Resultados de cierres

Las filas se clasifican como mínimo en:

- Cierres listos para el sistema.
- Entregable de cierres.
- Acción inválida/revisión de acción.
- Lectura negativa.
- Revisar lectura.
- Error o revisión de OBS.
- Revisión por lectura faltante/ambigua.
- Error técnico, si el proceso no puede completar la fila.

Las filas listas se marcan como exportadas solo después de confirmar que el archivo fue escrito correctamente.

## 11. Dependencia del entregable actualizado

### 11.1 Secuencia obligatoria

1. Finalizar cierres y revisiones.
2. Generar el TXT de cierres para el sistema.
3. Generar el entregable de cierres.
4. El usuario actualiza el sistema externo.
5. El usuario carga el «Entregable actualizado de cierres para reaperturas».
6. El módulo valida el archivo y registra su vínculo con la ejecución.
7. Solo entonces cambia reaperturas de **Bloqueado** a **Listo**.

### 11.2 Validación del archivo actualizado

Antes de desbloquear, comprobar:

- Archivo legible.
- Estructura y columnas requeridas.
- Clave de cruce disponible.
- Fecha y acciones interpretables.
- Ausencia de multiplicación muchos-a-muchos.
- Identificación de que corresponde a la ejecución o al conjunto de cierres esperado, cuando el formato permita comprobarlo.

Si falta, está corrupto, usa otro formato no confirmado o no corresponde, la rama permanece bloqueada y se informa el motivo. No se reutiliza automáticamente el entregable acumulado ni el entregable previo de cierres.

### 11.3 Estado entre etapas

El motor debe mantener un contexto de ejecución con:

- Estado de cada etapa.
- Rutas y huellas de archivos.
- Contadores.
- Resultados intermedios.
- Configuración aplicada.
- Identificador del entregable de cierres producido.
- Identificador del entregable actualizado cargado.

La persistencia para reanudar después de cerrar la aplicación es una decisión pendiente. En cualquier caso, no se reanudará una ejecución usando archivos distintos sin advertirlo.

## 12. Rama de reaperturas

### 12.1 Preparación

1. Tomar R y RD desde la misma `DATA_FILTRADA`.
2. Mantenerlas bloqueadas hasta completar la sección 11.
3. Cargar el entregable actualizado validado.
4. Normalizar identificadores, acciones, fechas y lecturas sin alterar los originales.

### 12.2 Selección del cierre previo

1. Cruzar por el identificador NIS real que se confirme.
2. Identificar candidatos a cierre efectivo usando la matriz aprobada.
3. No interpretar una acción del grupo 600 como acción de cierre; corresponde a reapertura ejecutada.
4. El rango 506–529 y la acción 540 son candidatos mencionados originalmente, no una lista completa ni autoridad suficiente.
5. Ordenar candidatos por fecha de ejecución descendente.
6. Seleccionar el cierre efectivo más reciente.
7. Traer `ACCION_CIERRE` y `LECTURA_CIERRE`.

El desempate cuando existan dos cierres con la misma fecha/hora está pendiente de confirmación.

### 12.3 Validación de equivalencia

Comparar `ACCION_CIERRE` con `ACCION_REAPERTURA_EJECUTADA` mediante una matriz configurable. Una equivalencia no existente o contradictoria va a `ACCION_INVALIDA` y conserva ambos valores.

Las equivalencias originales 506→606, 508→611, 511→611, 540→621 y medio metro→619 se conservan como candidatas, pero no se codificarán hasta ser aprobadas en la matriz oficial.

### 12.4 Diferencia de lectura

Calcular:

`DIFERENCIA = LECTURA_EJECUTADA - LECTURA_CIERRE`

- De 0 a 20 inclusive, con acción equivalente: la reapertura puede quedar lista.
- Menor que 0 o mayor que 20: `REVISAR_LECTURA`.
- Lectura faltante, no numérica, duplicada o ambigua: revisión; no sustituir por cero.

### 12.5 OBS y exportación

- Aplicar el máximo de 150 caracteres a OBS.
- Generar el TXT de reaperturas para el sistema.
- Generar el entregable de reaperturas.
- Marcar las filas como procesadas/exportadas únicamente cuando la escritura termine correctamente.
- Toda fila restante asociada con un cierre candidato debe quedar en revisión con un motivo específico. La definición exacta de «restante» está pendiente.

## 13. Validación de acciones y matrices configurables

### 13.1 Principio

El intervalo 506–529 no es la lista completa de acciones válidas. Solo puede ayudar a seleccionar determinadas acciones efectivas y determinar si aplica una validación de lectura.

### 13.2 Fuentes de comparación

La decisión debe comparar simultáneamente:

1. Acción ejecutada recibida.
2. TIPO.
3. OBS TIPO o descripción de la orden.
4. Tipo OS (`vtipo_os`).
5. Código `actividad` del control.
6. Texto `desc_actividad`.
7. Acción o conjunto de acciones esperado según matriz aprobada.
8. Clasificación de acción efectiva, imposibilidad u otra categoría autorizada.

### 13.3 Resultado

- Coincidencia inequívoca: continuar.
- No coincidencia: revisión de acción.
- Matriz contradictoria, ambigua o con varias opciones sin criterio de prioridad: revisión.
- Matriz sin coincidencia: revisión, no rechazo automático no explicado.
- La auditoría debe mostrar `ACC_RECIBIDA`, `ACC_ESPERADA`, `TIPO`, `OBS_TIPO`, `ACTIVIDAD`, `DESC_ACTIVIDAD` y evidencia usada.

### 13.4 Esquema lógico propuesto para la matriz aprobada

| Campo | Finalidad |
|---|---|
| `ID_REGLA_ACCION` | Identificador estable. |
| `ACTIVA` | Permitir desactivar sin borrar historial. |
| `TIPO` | C, CD, V, R, RD u otro autorizado. |
| `TIPO_OS` | Valor o patrón permitido de `vtipo_os`. |
| `ACTIVIDAD` | Código esperado, opcional. |
| `DESCRIPCION_ACTIVIDAD` | Texto/patrón aprobado, opcional. |
| `OBS_TIPO` | Descripción de negocio esperada. |
| `ACCION_EJECUTADA` | Acción válida o conjunto autorizado. |
| `CLASIFICACION` | Efectiva, imposibilidad u otra. |
| `APLICA_LECTURA` | Define si debe calcularse y validarse diferencia. |
| `ACCION_REAPERTURA_ESPERADA` | Equivalencia cuando aplique. |
| `PRIORIDAD` | Resolver reglas solapadas de forma explícita. |
| `VIGENCIA_DESDE/HASTA` | Control temporal si negocio lo necesita. |
| `FUENTE_APROBACION` | Responsable/documento de aprobación. |

### 13.5 Reglas originales conservadas como candidatas

- Acción mayor o igual que 700 → error.
- Tipo C + acción 508 → inválida.
- Tipo C + 511 → ejemplo de cierre simple efectivo.
- Tipo CD + 506 → dispositivo intrusivo.
- Tipo CD + 519 → medio metro.
- Equivalencias de reapertura ya listadas.

Todas permanecen **PENDIENTES DE CONFIRMACIÓN EN MATRIZ APROBADA**. No se eliminan de la especificación y tampoco se presentan como reglas definitivas.

## 14. Auditoría, trazabilidad y conservación de filas

### 14.1 Invariante principal

Ninguna fila puede eliminarse silenciosamente.

Para cada etapa debe cumplirse:

```text
entradas de la etapa
= continúan
 + exportadas
 + exclusiones operativas
 + revisiones manuales
 + errores técnicos
```

Los cruces no pueden aumentar el total mediante relaciones muchos-a-muchos. Si un cruce no es uno-a-uno o muchos-a-uno de forma válida, la anomalía se separa para revisión.

### 14.2 Información mínima por fila

- `ID_EJECUCION`.
- `ID_FILA`.
- Archivo y número de fila de origen.
- Fecha/hora de la decisión.
- Etapa.
- Regla aplicada.
- Categoría.
- Motivo legible en español.
- OT y OS originales y normalizadas.
- Valor recibido.
- Valor esperado.
- Estado anterior y nuevo.
- Archivo de destino.
- Datos originales completos.
- Valores normalizados relevantes.
- Historial ordenado de validaciones.

### 14.3 Categorías separadas

1. **Procesada/exportada.**
2. **Exclusión operativa:** por ejemplo `YA_ACTUALIZADA_EN_ENTREGABLE` o estado conocido no actualizable.
3. **Revisión manual:** inconsistencia de datos o regla pendiente.
4. **Error técnico:** imposibilidad de leer, procesar o escribir.

No se mezclará una exclusión operativa con un error técnico.

### 14.4 Motivos ya definidos

- `YA_ACTUALIZADA_EN_ENTREGABLE`.
- `INCONSISTENCIA_OT_OS`.
- `ACCION_INVALIDA`.
- `LECTURA_NEGATIVA`.
- `REVISAR_LECTURA`.

### 14.5 Motivos cuyo nombre final está pendiente

- OS duplicada o asociada a varias OT.
- OS no encontrada/estado no disponible.
- Estado conocido no actualizable.
- Estado desconocido.
- Operario sin equivalencia.
- Lectura ausente/no numérica/duplicada.
- OBS excedida.
- Patrón HI/HF ambiguo.
- Fila desalineada no reparable.
- Tipo no clasificado.

### 14.6 Archivos de auditoría propuestos

Dentro de `09_AUDITORIA/`:

- `AUDITORIA_FILAS_<ID>.csv`: una fila por decisión final, más referencia al historial.
- `HISTORIAL_VALIDACIONES_<ID>.csv`: una fila por regla evaluada.
- `RESUMEN_EJECUCION_<ID>.csv`: conteos por etapa/categoría.
- `MANIFIESTO_EJECUCION_<ID>.json`: entradas, huellas, configuración, estados y salidas.
- `CONFIGURACION_APLICADA_<ID>.json`: fotografía de reglas/alias aplicada, sin credenciales.

Estos nombres y formatos son PROPUESTA TÉCNICA; no afectan el formato externo de los TXT.

## 15. Carpetas y archivos de salida

La estructura base solicitada se conserva y se añade un identificador de ejecución para evitar sobrescrituras:

```text
SALIDA_YYYYMMDD/
└── EJECUCION_YYYYMMDD_HHMMSS_<ID>/
    ├── 01_DATA_FILTRADA/
    ├── 02_ERRORES_VALIDACION/
    ├── 03_ACCION_INVALIDA/
    ├── 04_REVISAR_LECTURA/
    ├── 05_CIERRES_LISTOS/
    ├── 06_ENTREGABLE_CIERRES/
    ├── 07_REAPERTURAS_LISTAS/
    ├── 08_ENTREGABLE_REAPERTURAS/
    └── 09_AUDITORIA/
```

### 15.1 Contenido esperado

| Carpeta | Contenido |
|---|---|
| `01_DATA_FILTRADA` | Instantánea común lista para separar ramas. |
| `02_ERRORES_VALIDACION` | Revisiones generales, errores de lectura y archivos separados por categoría. |
| `03_ACCION_INVALIDA` | Discordancias de acción con recibido/esperado/contexto. |
| `04_REVISAR_LECTURA` | Lecturas negativas, fuera de rango, ausentes o ambiguas, diferenciadas por motivo. |
| `05_CIERRES_LISTOS` | TXT externo de cierres y, si se autoriza, vista de control interna. |
| `06_ENTREGABLE_CIERRES` | Entregable de cierres que el usuario actualizará externamente. |
| `07_REAPERTURAS_LISTAS` | TXT externo de reaperturas. |
| `08_ENTREGABLE_REAPERTURAS` | Entregable final de reaperturas. |
| `09_AUDITORIA` | Conciliación, exclusiones operativas, historial, manifiesto y configuración. |

La corrección posterior exige separar exclusiones operativas de errores técnicos. Para no cambiar arbitrariamente la numeración original, se crearán archivos diferenciados dentro de `02_ERRORES_VALIDACION` y `09_AUDITORIA`, salvo que el usuario autorice una carpeta adicional.

### 15.2 Nombres

Cada archivo debe incluir:

- Fecha de procesamiento.
- Tipo de resultado.
- Hora o identificador de ejecución.

Ejemplo conceptual:

`CIERRES_SISTEMA_20260921_143522_A1B2.txt`

No se sobrescriben archivos existentes. Si el nombre ya existe, debe generarse un correlativo o un nuevo ID.

## 16. Formatos observados y formato pendiente de los TXT

### 16.1 Observaciones confirmadas en muestras

| Elemento | Observación |
|---|---|
| Delimitador | TAB en los TXT reales inspeccionados. |
| Control GIO | 57 columnas; necesita lectura tolerante ANSI occidental/CP1252/Latin-1. |
| Entregables | UTF-8 con BOM en las muestras. |
| Orden observado | `nis_rad`, `OT`, `OS`, `FEJECUCION`, `HI`, `HF`, `ACCION`, `CODIGO`, `OBSERVACION`, `LECT`. |
| NISRA/IDRA | No aparecen en las muestras; aparece `nis_rad` en posición 1. |
| Fecha | Se observan `D/M/YYYY` y `DD/MM/YYYY`. |
| HI/HF | Columnas con punto y longitudes variables; OBS con `HH:MM`. |
| LECT | Entero textual en TXT y numérico en Excel. |
| Encabezado | Un entregable tiene encabezado y otro no. |

### 16.2 Contrato original y conflicto

El requerimiento original indicó:

- TXT del sistema con nueve columnas desde OT hasta LECTURA.
- TXT entregable con NISRA o IDRA adicional.

Las muestras de entregable muestran diez columnas totales con `nis_rad` primero. Esto es compatible conceptualmente con «nueve + identificador», pero no prueba que el TXT del sistema deba llevar exactamente las nueve restantes ni que todos los archivos usen encabezado.

### 16.3 Decisiones pendientes por cada tipo de TXT

Para **cierres del sistema**, **entregable de cierres**, **reaperturas del sistema**, **entregable de reaperturas** y **entregable acumulado** se debe confirmar por separado:

- Columnas exactas y orden.
- Encabezado sí/no.
- Delimitador.
- Codificación.
- Fin de línea.
- Formato de FECHA.
- Formato de HI/HF.
- Nombre del identificador NIS.
- Formato de LECT nula o decimal.
- Reglas de comillas/escape.

No se construirá un exportador definitivo hasta disponer de un TXT aceptado por el sistema para cierres y otro para reaperturas.

## 17. Modelos de datos

Los nombres de clases son una propuesta en español y podrán afinarse en Fase 1 sin cambiar sus responsabilidades.

### 17.1 `ConfiguracionProcesamiento`

- Alias de columnas.
- Catálogo de estados.
- Tipos por rama.
- Matriz de acciones.
- Equivalencias de reapertura.
- Matriz de operarios.
- Reglas de lectura.
- Contratos de salida.
- Versión o huella de configuración.

### 17.2 `FormatoArchivo`

- Tipo de archivo.
- Codificación.
- Delimitador.
- Tiene encabezado.
- Fila de encabezado.
- Orden de columnas.
- Formatos de fecha/hora/lectura.

### 17.3 `RegistroOriginal`

- `id_fila`.
- Archivo y fila de origen.
- Diccionario/lista completa de valores originales.
- Encabezados originales.

### 17.4 `RegistroProcesamiento`

- Referencia al original.
- Valores normalizados.
- OT, OS, NIS, tipo, acción y campos operativos.
- Estado de procesamiento.
- Rama asignada.
- Historial de validaciones.
- Motivo de exclusión.
- Archivo final.

### 17.5 `ResultadoValidacion`

- ID de regla.
- Etapa.
- Aprobada/no aprobada/no aplicable.
- Categoría.
- Motivo.
- Valor recibido.
- Valor esperado.
- Fecha/hora.

### 17.6 `ContextoEjecucion`

- ID de ejecución.
- Fecha operativa.
- Entradas y huellas.
- Carpeta de salida.
- Configuración aplicada.
- Estado de etapas.
- Contadores.
- Resultados intermedios.
- Entregable de cierres producido.
- Entregable actualizado cargado.

### 17.7 `ResumenEtapa` y `ResultadoProceso`

- Totales de entrada, continuación, exclusión, revisión, error y exportación.
- Rutas generadas.
- Advertencias.
- Error técnico si aplica.
- Conciliación final.

### 17.8 Estados de etapa para UI y motor

- `PENDIENTE`.
- `LISTO`.
- `PROCESANDO`.
- `COMPLETADO`.
- `CON_ERRORES`.
- `BLOQUEADO`.

## 18. Arquitectura modular de Python

### 18.1 Archivos nuevos previstos

```text
actualizacion_datos_pagina.py

actualizacion_datos/
    __init__.py
    modelos.py
    configuracion.py
    servicio.py
    lectores.py
    normalizacion.py
    flujo_comun.py
    reglas.py
    cierres.py
    reaperturas.py
    exportadores.py
    auditoria.py
    trabajadores.py

tests/
    test_modelos_actualizacion.py
    test_auditoria_actualizacion.py
    test_lectores_actualizacion.py
    test_normalizacion_actualizacion.py
    test_flujo_comun.py
    test_reglas_actualizacion.py
    test_cierres.py
    test_reaperturas.py
    test_exportadores_actualizacion.py
    test_trabajadores_actualizacion.py
    test_integracion_actualizacion.py
```

### 18.2 Responsabilidades

| Archivo | Responsabilidad |
|---|---|
| `actualizacion_datos_pagina.py` | Página PySide6, selección de archivos, estados visuales, vista previa y coordinación. Sin reglas de negocio. |
| `actualizacion_datos/modelos.py` | Modelos, enumeraciones y resultados. |
| `actualizacion_datos/configuracion.py` | Carga y validación de catálogos, alias y matrices; fotografía de configuración. |
| `actualizacion_datos/servicio.py` | Orquestación de etapas y dependencias sin importar PySide6; punto de entrada del motor para trabajadores y pruebas de integración. |
| `actualizacion_datos/lectores.py` | Lectura CSV/TXT/XLSX y diagnóstico estructural. |
| `actualizacion_datos/normalizacion.py` | Encabezados, identificadores, fechas, horas y alineación controlada. |
| `actualizacion_datos/flujo_comun.py` | Fecha, entregable acumulado, pareja OT–OS, estado, operario y `DATA_FILTRADA`. |
| `actualizacion_datos/reglas.py` | Evaluación centralizada de estados, acciones, tipos, lecturas y equivalencias. |
| `actualizacion_datos/cierres.py` | Rama C/CD/V, lectura, diferencia, horario y clasificación. |
| `actualizacion_datos/reaperturas.py` | Selección del cierre, equivalencias, diferencia y clasificación. |
| `actualizacion_datos/exportadores.py` | Escritura exacta, nombres únicos y protección de identificadores. |
| `actualizacion_datos/auditoria.py` | Historial, motivos, conciliaciones, manifiesto y salidas de revisión. |
| `actualizacion_datos/trabajadores.py` | Trabajadores `QObject`, señales, progreso, cancelación segura y errores. |

### 18.3 Archivos existentes que eventualmente podrían modificarse

- `main.py`: únicamente en Fase 8 para importar, registrar y navegar a la nueva página.
- `requirements.txt`: solo si una decisión autorizada incorpora nuevas dependencias.
- `crear_instalable.py`: solo en Fase 9 y únicamente si PyInstaller necesita declaraciones adicionales.
- `.gitignore`: solo si las nuevas salidas de ejecución requieren una exclusión específica y se autoriza.

### 18.4 Archivos que no deben tocarse para implementar la lógica

- `app_update.py`.
- `depuracion_ot.py` y `depuracion_ot_pagina.py`.
- `extractor_ordenes.py` y `extractor_ordenes_pagina.py`.
- `modulo_txt_cyr.py`.
- `ordenes_cyr_pagina.py` y `ordenes_cyr_pdf.py`.
- Lógica de Inicio, Importar, Ayuda y Google Sheets.
- `VERSION`, excepto en un proceso de versión autorizado distinto.

## 19. Interfaz PySide6

### 19.1 Ubicación

- Una página más del `QStackedWidget` existente.
- Misma `VentanaRuteo`.
- Sin diálogos principales duplicados.
- La navegación se integrará solo en la Fase 8.

### 19.2 Diseño por etapas

La página mostrará una cadena visual:

1. Carga de archivos.
2. Normalización.
3. Selección de fecha.
4. Validaciones generales.
5. DATA_FILTRADA.
6. División en:
   - Cierres y revisiones.
   - Reaperturas.

Después de cierres se mostrará explícitamente:

1. TXT del sistema generado.
2. Entregable de cierres generado.
3. Esperando actualización externa.
4. Cargar entregable actualizado.
5. Reaperturas desbloqueadas.

### 19.3 Estados visuales

Cada tarjeta/etapa debe mostrar, de manera discreta:

- Pendiente.
- Listo.
- Procesando.
- Completado.
- Con errores.
- Bloqueado.

### 19.4 Controles

- Selectores de cada archivo requerido.
- Ruta y nombre visibles.
- Selector de fecha.
- Selector de carpeta de salida.
- Acción para procesar flujo común.
- Acción para procesar cierres.
- Acción para cargar entregable actualizado.
- Acción para procesar reaperturas.
- Acción para abrir la carpeta de resultados.
- Cancelación cuando el trabajador lo permita de forma segura.

Los controles dependientes permanecerán deshabilitados hasta cumplir sus requisitos.

### 19.5 Información

- Filas cargadas.
- Filas de la fecha elegida.
- Filas válidas.
- Exclusiones operativas.
- Revisiones.
- Errores técnicos.
- Cierres listos.
- Reaperturas listas.
- Conteo por motivo.
- Tabla de vista previa.
- Motivo, valor recibido y esperado de cada fila excluida.

### 19.6 Estilo

Reutilizar `FondoModulosWidget`, paneles y estilos existentes. No cambiar el diseño general, la barra superior, el contenido de otros módulos ni los recursos compartidos durante la Fase 7. La nueva acción de navegación se añadirá posteriormente en Fase 8.

## 20. Procesamiento con QThread

### 20.1 Patrón

- Un trabajador `QObject` por operación pesada.
- Moverlo a un `QThread` creado por la página/controlador.
- Conectar `started` con el método de ejecución.
- Señales para progreso, estado, resumen, resultado, advertencia, error y cancelación.
- Al terminar, ordenar `quit`, `deleteLater` y liberar referencias.
- Nunca modificar widgets desde el trabajador.

### 20.2 Señales propuestas

- `progreso(etapa, actual, total)`.
- `estado_cambiado(etapa, estado)`.
- `resumen_actualizado(resumen)`.
- `terminado(resultado)`.
- `error(mensaje, detalle)`.
- `cancelado(resultado_parcial_seguro)`.

### 20.3 Seguridad de la ejecución

- Deshabilitar acciones incompatibles durante un proceso.
- No permitir dos trabajadores del módulo simultáneamente.
- Cancelar únicamente en puntos seguros.
- Escribir salidas mediante archivos temporales y reemplazo final controlado cuando corresponda.
- No marcar una fila como exportada antes de cerrar correctamente el archivo.
- Al fallar, conservar auditoría de lo procesado y no presentar la etapa como completada.

### 20.4 Estado entre etapas

El estado pertenece al motor/contexto, no a los colores de la UI. La página representa ese estado y solicita operaciones; no decide reglas ni fabrica resultados.

## 21. Matriz de reglas confirmadas

| ID_REGLA | ETAPA | CONDICIÓN | RESULTADO | CATEGORÍA | ESTADO |
|---|---|---|---|---|---|
| ENT-01 | Entrada | Archivo operativo CSV, TXT delimitado o XLSX | Intentar lectura mediante lector correspondiente | Entrada | CONFIRMADA |
| ENT-02 | Entrada | Se inicia una ejecución | Cargar entradas comunes y carpeta de salida | Entrada | CONFIRMADA |
| ENT-03 | Entrada | Usuario selecciona fecha | Filtrar CSV SANSYS por esa fecha | Alcance | CONFIRMADA |
| NOR-01 | Normalización | Encabezados/identificadores con diferencias de formato | Normalizar conservando el original | Normalización | CONFIRMADA |
| NOR-02 | Normalización | Identificador con espacios o `.0` artificial | Limpiar sin perder ceros iniciales | Normalización | CONFIRMADA |
| NOR-03 | Exportación | Identificador numérico aparente | Exportar como texto, sin notación científica | Protección de identificador | CONFIRMADA |
| COM-01 | Flujo común | Antes de separar ramas | Cargar entregable acumulado | Entrada común | CONFIRMADA |
| COM-02 | Flujo común | Clave inicial para acumulado | Usar OT normalizada | Cruce | CONFIRMADA provisionalmente |
| COM-03 | Flujo común | OT ya aparece en acumulado | Excluir, auditar y no tratar como error | `YA_ACTUALIZADA_EN_ENTREGABLE` | CONFIRMADA |
| COM-04 | Flujo común | OT no aparece | Continuar | Continúa | CONFIRMADA |
| COM-05 | Cruces | Clave vacía/duplicada puede multiplicar filas | Impedir muchos-a-muchos y revisar | Inconsistencia | CONFIRMADA |
| PAR-01 | OT–OS | Se consulta control | Buscar principalmente por OS y comprobar OT | Validación de pareja | CONFIRMADA |
| PAR-02 | OT–OS | OS y OT coinciden | Continuar | Continúa | CONFIRMADA |
| PAR-03 | OT–OS | OS existe con otra OT | Revisión con recibido/esperado | `INCONSISTENCIA_OT_OS` | CONFIRMADA |
| PAR-04 | OT–OS | OT aparece con otra OS | Revisión | `INCONSISTENCIA_OT_OS` | CONFIRMADA |
| PAR-05 | OT–OS | OS duplicada/multi-OT | No elegir la primera | Revisión de duplicidad | CONFIRMADA en comportamiento |
| EST-01 | Estado | `TRAB`/TRABAJANDO | Continuar | Continúa | CONFIRMADA |
| EST-02 | Estado | NA, vacío u OS no encontrada | Revisión manual | Estado no disponible | CONFIRMADA |
| EST-03 | Estado | RESUELTA, ANULADA, PENDIENTE u otro conocido no actualizable | Excluir y auditar separado de errores | Exclusión operativa | CONFIRMADA |
| OPE-01 | Operario | Existe equivalencia inequívoca | Conservar código resuelto | Continúa | CONFIRMADA |
| OPE-02 | Operario | Falta/no coincide equivalencia | Revisión | Operario sin equivalencia | CONFIRMADA |
| ACC-01 | Acción | ACC está entre 506 y 529 | Tratar como candidata, no como válida automáticamente | Candidata | CONFIRMADA |
| ACC-02 | Acción | Se evalúa validez | Comparar tipo, descripciones, actividad, ACC y matriz | Validación de acción | CONFIRMADA |
| ACC-03 | Acción | Recibida y esperada no coinciden | Revisión con ambos valores y contexto | `ACCION_INVALIDA`/revisión | CONFIRMADA |
| ACC-04 | Acción | Matriz empírica contradice actividad | No corregir automáticamente | Revisión | CONFIRMADA |
| TIP-01 | Separación | Tipo C, CD o V | Rama de cierres | Cierres | CONFIRMADA |
| TIP-02 | Separación | Tipo R o RD | Rama de reaperturas | Reaperturas | CONFIRMADA |
| TIP-03 | Separación | Tipo B | No implementarlo todavía | Pendiente de definición | CONFIRMADA como exclusión temporal |
| CIE-01 | Cierres | Lecturas disponibles y aplica control | Ejecutada menos toma | Diferencia de cierre | CONFIRMADA |
| CIE-02 | Cierres | Diferencia menor que 0 | Revisión | `LECTURA_NEGATIVA` | CONFIRMADA |
| CIE-03 | Cierres | Diferencia entre 0 y 300 inclusive | No excluir por diferencia | Continúa | CONFIRMADA |
| CIE-04 | Cierres | Diferencia igual a 280 | Aceptar por esta regla | Continúa | CONFIRMADA |
| CIE-05 | Cierres | Diferencia mayor que 300 | Revisión | `REVISAR_LECTURA` | CONFIRMADA |
| HOR-01 | Horario | Tipo C y HI o HF ≥ 14:00 | Establecer ambos a 12:00 | Corrección auditada | CONFIRMADA |
| HOR-02 | Horario | Se aplica HOR-01 | Reemplazar solo HI/HF en OBS y preservar texto posterior | Corrección auditada | CONFIRMADA |
| HOR-03 | Horario | Tipo CD, V, R o RD | No aplicar corrección | Sin corrección | CONFIRMADA |
| OBS-01 | Ambas ramas | OBS > 150 caracteres | Revisión/error de OBS | OBS excedida | CONFIRMADA |
| REA-01 | Reaperturas | Falta entregable actualizado | Mantener bloqueada la rama | Bloqueado | CONFIRMADA |
| REA-02 | Reaperturas | Entregable actualizado válido | Desbloquear | Listo | CONFIRMADA |
| REA-03 | Reaperturas | Se buscan cierres anteriores | Ordenar por fecha descendente y elegir efectivo más reciente | Selección de cierre | CONFIRMADA; desempate pendiente |
| REA-04 | Reaperturas | Acción pertenece al grupo 600 | No tratarla como cierre previo | Exclusión de candidato | CONFIRMADA |
| REA-05 | Reaperturas | Lecturas disponibles | Ejecutada menos lectura de cierre | Diferencia de reapertura | CONFIRMADA |
| REA-06 | Reaperturas | Diferencia 0..20 y equivalencia válida | Reapertura lista | Lista | CONFIRMADA |
| REA-07 | Reaperturas | Diferencia <0 o >20 | Revisión | `REVISAR_LECTURA` | CONFIRMADA |
| REA-08 | Reaperturas | Acción no equivale | Revisión | `ACCION_INVALIDA` | CONFIRMADA |
| REA-09 | Reaperturas | TXT escrito correctamente | Marcar fila como procesada/exportada | Procesada | CONFIRMADA |
| AUD-01 | Todas | Fila deja de continuar | Guardar original, motivo, regla, etapa y destino | Auditoría | CONFIRMADA |
| AUD-02 | Todas | Exclusión operativa | No mezclar con error técnico | Separación de categorías | CONFIRMADA |
| AUD-03 | Todas | Cierre de etapa | Conciliar todos los conteos | Integridad | CONFIRMADA |
| EXP-01 | Exportación | Nombre de salida ya existe | Generar nombre único; no sobrescribir | Protección de salida | CONFIRMADA |

## 22. Reglas originales corregidas o en conflicto

| TEMA | FORMULACIÓN ORIGINAL | CORRECCIÓN/EVIDENCIA POSTERIOR | ESTADO Y RESOLUCIÓN |
|---|---|---|---|
| Entregable acumulado | Solo se destacaba el entregable posterior para reaperturas | También debe cargarse antes de separar ramas y excluir lo ya actualizado | Corrección vigente CONFIRMADA. |
| Estados | Todo lo distinto de TRABAJANDO iba a errores | Vacío/NA/no encontrado va a revisión; estados conocidos no actualizables son exclusión operativa | Original SUPERADA. |
| Validación OT–OS | Cruces independientes OT/OT y OS/OS | Buscar por OS, confirmar su OT y evitar muchos-a-muchos | Corrección vigente. |
| Unicidad OS | OS se consideraba única | Dos OS reales están vinculadas a varias OT | Prevalidar unicidad; categoría final pendiente. |
| Tipos de cierre | C, CD, V y B | Solo C, CD y V tienen evidencia; no programar B | B PENDIENTE. |
| VD | No aparecía | Existe en catálogo, sin rama definida | PENDIENTE. |
| Rango 506–529 | Podía leerse como lista de acciones válidas/efectivas | Es rango auxiliar; la validez depende de contexto y matriz | Interpretación original SUPERADA. |
| Matriz de acciones | Reglas puntuales podían codificarse directamente | Matriz histórica no es absoluta; comparar actividad, tipo y descripción | Matriz aprobada pendiente. |
| Acción ≥700 | Error automático | Debe contrastarse con matriz aprobada antes de activarse | Conservar como candidata PENDIENTE. |
| C+508 | Inválida | Requiere matriz/contexto aprobado | Candidata PENDIENTE. |
| C+511 | Ejemplo de cierre simple | No convertir un ejemplo en regla sin matriz | Candidata PENDIENTE. |
| CD+506/CD+519 | Dispositivo/medio metro | Requiere descripción, actividad y matriz | Candidatas PENDIENTES. |
| Diferencia cierres | Aplicaba a acciones efectivas 506–529 | Límites confirmados, aplicabilidad depende de matriz/contexto | Alcance PENDIENTE. |
| Corrección de hora | Tipo C desde 14:00 | Confirmada solo para C; nunca CD/V/R/RD | CONFIRMADA. |
| Formato 12:00 | Se indicó `12:00` | Columnas reales usan punto; OBS usa dos puntos | PENDIENTE: `12.00` o `12:00` en columnas. |
| Identificador | NIS, NISRA o IDRA | Muestras usan `nis_rad` | Nombre oficial PENDIENTE. |
| TXT | Sistema 9 columnas; entregable añade identificador | Muestras de entregable tienen 10 columnas con `nis_rad` primero | Compatible conceptualmente, contrato exacto PENDIENTE. |
| Encabezado | No definido | Hay muestra con y sin encabezado | PENDIENTE por tipo de archivo. |
| Fecha | No definida | Hay `D/M/YYYY` y `DD/MM/YYYY` | PENDIENTE. |
| Codificación | No definida | GIO ANSI occidental; entregables UTF-8 BOM | Salidas PENDIENTES. |
| Equivalencias reapertura | Se dieron equivalencias puntuales | Deben validarse mediante matriz aprobada | PENDIENTES. |
| Cierre más reciente | Ordenar por fecha | No hay regla de desempate | PENDIENTE. |
| Reparar CSV | Detectar y corregir columnas desalineadas | No hay criterio para casos ambiguos | Solo reparar lo inequívoco; política PENDIENTE. |
| Filas restantes | Cierres efectivos restantes a revisión | No se define exactamente el conjunto ni motivo | PENDIENTE. |

## 23. Reglas pendientes de confirmación

| ID_PENDIENTE | DECISIÓN/ARCHIVO NECESARIO | QUÉ RESUELVE |
|---|---|---|
| PEN-01 | Entregar un CSV SANSYS productivo representativo | Confirmar encabezados reales de la entrada productiva. |
| PEN-02 | Confirmar el TXT GIO canónico | Estructura de control. |
| PEN-03 | Catálogo oficial de estados abreviados, incluidos FAC y ATEN | Continuación/exclusión/revisión. |
| PEN-04 | Elegir `DATA PARA ACTUALIZAR (3).xlsx` o `Reglas_de_procesamiento_actualizacion.xlsx` | Fuente canónica de actividad, operarios y lecturas. |
| PEN-05 | Matriz de acciones aprobada | Acciones válidas, efectivas, imposibilidades y aplicabilidad de lectura. |
| PEN-06 | Confirmar política para acción ≥700 y ejemplos C/CD | Validación de cierres. |
| PEN-07 | Matriz completa de equivalencias de reapertura | Comparación cierre–reapertura. |
| PEN-08 | Decisión o muestra real de tipo B | Incluir o mantener fuera. |
| PEN-09 | Decisión sobre VD | Rama y tratamiento. |
| PEN-10 | Política oficial para OS duplicada/multi-OT | Motivo y destino. |
| PEN-11 | Confirmar OT sola o clave compuesta para acumulado | Evitar falsos positivos. |
| PEN-12 | Confirmar `nis_rad` frente a NIS/NISRA/IDRA | Claves y encabezados de salida. |
| PEN-13 | TXT aceptado por el sistema para cierres | Contrato exacto de cierre. |
| PEN-14 | TXT aceptado por el sistema para reaperturas | Contrato exacto de reapertura. |
| PEN-15 | Confirmar `C_extregable17072026.txt` como acumulado canónico | Encabezado/formato del acumulado. |
| PEN-16 | Entregable de cierres antes y después de actualización externa | Dependencia y campos que cambian. |
| PEN-17 | Definir encabezado por cada TXT | Escritura exacta. |
| PEN-18 | Definir codificación y fin de línea por cada TXT | Compatibilidad externa. |
| PEN-19 | Definir FECHA (`D/M/YYYY` o `DD/MM/YYYY`) | Exportación. |
| PEN-20 | Definir HI/HF (`12.00` o `12:00`) en columnas | Corrección/exportación. |
| PEN-21 | Definir LECT nula, decimal y redondeo | Cálculos y exportación. |
| PEN-22 | Completar dos operarios sin código GIO o aprobar su revisión | Equivalencia de operario. |
| PEN-23 | Casos reales de OBS tipo C antes/después y sin patrón | Algoritmo seguro de reemplazo. |
| PEN-24 | Regla de desempate de cierres con misma fecha/hora | Selección determinista. |
| PEN-25 | Definir «cierres efectivos restantes» | Motivo de revisión final. |
| PEN-26 | Definir cuándo reparar una fila desalineada | Lector/normalización. |
| PEN-27 | Decidir persistencia/reanudación entre sesiones | Estado de etapas. |
| PEN-28 | Decidir pandas/openpyxl o lectores ligeros | Dependencias y empaquetado. |
| PEN-29 | Aprobar nombres finales de categorías propuestas | Archivos de errores/auditoría. |
| PEN-30 | Confirmar alcance exacto de la diferencia de cierre | Qué acciones requieren lectura. |

## 24. Plan de pruebas

### 24.1 Modelos, configuración y auditoría

- Creación de IDs de ejecución y fila.
- Conservación de originales y normalizados.
- Historial de varias reglas sobre la misma fila.
- Configuración válida, incompleta y contradictoria.
- Separación de exclusión operativa, revisión y error técnico.
- Conciliación exacta de conteos.

### 24.2 Lectores y normalización

- CSV, TXT y XLSX.
- TAB, coma, punto y coma y delimitador configurado.
- UTF-8, UTF-8 BOM y lectura tolerante CP1252/Latin-1.
- Con y sin encabezado según contrato.
- Fila con número correcto/incorrecto de columnas.
- Reparación inequívoca y rechazo de reparación ambigua.
- Alias de encabezados.
- Espacios, `.0`, ceros iniciales e identificadores grandes.
- Fecha y hora válidas/inválidas.

### 24.3 Flujo común

- Fecha seleccionada, otra fecha y fecha inválida.
- OT presente/ausente en acumulado.
- OT vacía o repetida.
- Prevención de muchos-a-muchos.
- OS única, duplicada y multi-OT.
- Pareja coincidente e inconsistente.
- OS no encontrada.
- `TRAB`, NA, vacío, estados conocidos y desconocidos.
- Operario válido, faltante y contradictorio.
- Construcción y conciliación de `DATA_FILTRADA`.

### 24.4 Acciones

- Acción coherente.
- Acción recibida distinta de esperada.
- Matriz ambigua.
- Matriz y actividad contradictorias.
- Tipo o descripción sin regla.
- Imposibilidad autorizada/no autorizada cuando exista matriz final.

### 24.5 Cierres

- Separación C, CD, V; B y VD no procesados sin autorización.
- Lectura encontrada, ausente, duplicada y no numérica.
- Diferencias `-1`, `0`, `280`, `300`, `301`.
- Tipo C con 13:59 y 14:00.
- HI que activa corrección y HF que la activa independientemente.
- Verificar que ambos campos pasan a 12:00 internamente.
- No aplicar a CD, V, R o RD.
- OBS con patrón, sin patrón y texto posterior a `OBS:`.
- Longitudes OBS 150 y 151.

### 24.6 Exportación de cierres

- Orden exacto de columnas cuando se confirme.
- Encabezado/codificación/fecha/hora exactos.
- Ceros iniciales y ausencia de notación científica.
- No sobrescritura.
- Escritura fallida no marca filas como exportadas.

### 24.7 Entregable actualizado y reaperturas

- Rama bloqueada inicialmente.
- Archivo ausente, inválido o de otra ejecución.
- Desbloqueo solo con archivo válido.
- Cierre único, varios cierres y empate.
- Acción 600 no seleccionada como cierre.
- Equivalencia válida/inválida/ambigua.
- Diferencias `-1`, `0`, `20`, `21`.
- OBS 150/151.
- Filas exportadas y restantes auditadas.

### 24.8 QThread e interfaz

- Ventana responsiva con archivo grande.
- Progreso y estados correctos.
- Error propagado sin cerrar la aplicación.
- Cancelación segura.
- Liberación de trabajador/hilo.
- Botones dependientes bloqueados/desbloqueados.
- Vista previa y motivos coherentes.

### 24.9 Integración y regresión

- Flujo común completo.
- Cierres y sus dos exportaciones.
- Pausa externa y carga del entregable actualizado.
- Reaperturas y sus dos exportaciones.
- Conservación total de filas y ausencia de duplicación.
- Inicio, TXT CyR, Extractor de órdenes, Depuración OT, Importar y Ayuda sin cambios funcionales.
- Actualizador técnico intacto.
- Instancia única e inactividad intactas.
- PyInstaller probado solo en Fase 9.

## 25. Plan de implementación por fases

### Fase 1 — Modelos, configuración y auditoría

- Crear modelos, enumeraciones, configuración y trazabilidad.
- Definir la conciliación de filas.
- Pruebas unitarias de la fase.
- Sin lectores reales, UI ni integración.

### Fase 2 — Lectores y normalización

- CSV, TXT y XLSX.
- Detección de formato, encabezados, alias e identificadores.
- Pruebas con muestras controladas y reales no sensibles.

### Fase 3 — Flujo común hasta DATA_FILTRADA

- Fecha.
- Entregable acumulado.
- OT–OS.
- Estado.
- Operario y contexto.
- Conciliación de `DATA_FILTRADA`.

### Fase 4 — Cierres y revisiones

- Tipos C/CD/V.
- Acciones.
- Lecturas/diferencias.
- Horarios y OBS.
- Clasificación de resultados.

### Fase 5 — Exportación de cierres y entregable

- Exportadores con contratos ya confirmados.
- Carpetas/nombres únicos.
- TXT del sistema y entregable de cierres.

### Fase 6 — Carga del entregable actualizado y reaperturas

- Validación de dependencia.
- Selección del cierre efectivo.
- Equivalencias y diferencias.
- Exportaciones de reaperturas.

### Fase 7 — Interfaz PySide6 y QThread

- Página autónoma, cadena visual, vista previa, contadores y trabajadores.
- Sin modificar aún la navegación de `main.py`.

### Fase 8 — Integración mínima con main.py

- Acción de navegación.
- Registro de la página en `QStackedWidget`.
- Método para mostrarla.
- Pruebas de navegación y regresión.

### Fase 9 — Pruebas completas y empaquetado

- Suite completa.
- Pruebas con muestras canónicas.
- Revisión de dependencias y PyInstaller.
- Generación de ejecutable únicamente cuando se autorice expresamente.

### 25.1 Disciplina obligatoria por fase

1. Leer esta especificación completa.
2. Ejecutar solo una fase autorizada.
3. Modificar únicamente archivos de esa fase.
4. Probar lo implementado.
5. Informar archivos y resultados.
6. Crear un commit separado al terminar la fase aprobada.
7. Detenerse y esperar autorización.
8. No hacer push.
9. No comenzar la fase siguiente.
10. No releer todo el repositorio si este documento ya contiene la dependencia necesaria.
11. Usar código, nombres, mensajes y comentarios en español comprensible.

## 26. Riesgos técnicos

| Riesgo | Consecuencia | Mitigación |
|---|---|---|
| Archivos grandes | Memoria alta o UI congelada | Lectura controlada, trabajadores QThread, progreso y pruebas de volumen. |
| Codificaciones diferentes | Texto corrupto o lectura fallida | Detección/contrato por archivo; conservar bytes/ruta y reportar elección. |
| Encabezados ambiguos | Cruce sobre columna incorrecta | Alias configurados, validación de columnas y confirmación del usuario. |
| Filas desalineadas | Datos asociados al campo equivocado | Solo reparación inequívoca; ambiguas a error con original completo. |
| Identificadores convertidos a número | Pérdida de ceros/precisión | Texto de extremo a extremo. |
| OS no realmente única | Duplicación o asociación incorrecta | Validación previa y bloqueo de muchos-a-muchos. |
| Matriz histórica errónea | Acción aceptada/rechazada incorrectamente | Matriz aprobada, comparación de múltiples fuentes y revisión ante contradicción. |
| Estados abreviados no catalogados | Exclusión equivocada | Catálogo oficial versionado. |
| Formato TXT no confirmado | Rechazo del sistema externo | No implementar exportador definitivo sin archivo aceptado. |
| Actualización externa manual | Archivo equivocado en reaperturas | Huellas, contexto de ejecución y validación antes de desbloquear. |
| Reglas dispersas en UI | Difícil mantenimiento y errores | Centralizar en configuración/reglas. |
| Dependencias nuevas | EXE incompleto o más pesado | Decidir en Fase 2, declarar en requirements y verificar en Fase 9. |
| Escritura parcial | Archivo corrupto marcado como válido | Escritura temporal/controlada y confirmación antes de cambiar estado. |
| Colisión de nombres | Pérdida de resultados | ID de ejecución y prohibición de sobrescritura. |
| Cancelación en mal momento | Estado incoherente | Puntos seguros y auditoría parcial explícita. |
| Cambios accidentales en módulos actuales | Regresión | Archivos aislados, integración tardía y pruebas de regresión. |

## 27. Restricciones y protección de módulos existentes

- No usar ni modificar `app_update.py` para este módulo.
- No sustituir el actualizador de GitHub.
- No cambiar `VERSION` durante el desarrollo de una fase salvo autorización separada.
- No modificar lógica de TXT CyR, Extractor de órdenes, Depuración OT, Inicio, Importar o Ayuda.
- No crear otra aplicación ni otra ventana principal.
- No duplicar procesos ni páginas.
- No cambiar estilos generales ni recursos compartidos para adaptar la página nueva.
- No instalar dependencias sin autorización de la fase correspondiente.
- No generar ejecutable antes de la Fase 9 autorizada.
- No borrar, limpiar ni revertir cambios ajenos.
- No usar muestras históricas como reglas absolutas.
- No incorporar credenciales, OAuth, `config/`, entornos, build/dist ni resultados al repositorio.
- Respetar el respaldo `c6f6c76`.

La integración en `main.py` debe ser mínima, localizada y diferida hasta la Fase 8.

## 28. Criterios de aceptación del módulo

El módulo estará completo únicamente cuando:

1. Lee los formatos canónicos autorizados.
2. Conserva identificadores sin pérdida.
3. Construye `DATA_FILTRADA` con reglas auditables.
4. Excluye órdenes ya actualizadas sin tratarlas como error.
5. Valida la pareja OT–OS sin muchos-a-muchos.
6. Separa estados operativos, revisiones y errores técnicos.
7. Procesa C/CD/V y mantiene B/VD según decisión final.
8. Aplica acciones mediante matriz aprobada.
9. Aplica correctamente límites de cierres y corrección exclusiva de C.
10. Genera los TXT de cierres exactamente aceptados por el sistema.
11. Mantiene bloqueadas las reaperturas hasta el entregable actualizado.
12. Selecciona el cierre correcto y valida equivalencias/diferencias.
13. Genera los TXT de reaperturas exactamente aceptados.
14. Ninguna fila desaparece: todos los conteos cuadran.
15. Cada fila tiene motivo, regla, etapa, recibido, esperado y destino.
16. La UI permanece responsiva y representa el estado real del motor.
17. Los módulos existentes pasan sus pruebas de regresión.
18. El paquete PyInstaller incluye todo lo requerido y abre correctamente.

## 29. Control de cambios de esta especificación

Toda decisión que cierre un pendiente debe:

1. Registrar el archivo o aprobación que la sustenta.
2. Actualizar la sección correspondiente.
3. Cambiar el estado de PENDIENTE a CONFIRMADA.
4. Actualizar la matriz de reglas y las pruebas esperadas.
5. Conservar la formulación anterior en el historial de conflictos cuando exista contradicción.
6. No cambiar silenciosamente una regla ya implementada.

Esta especificación no autoriza por sí sola la implementación. Cada fase requiere autorización independiente.
