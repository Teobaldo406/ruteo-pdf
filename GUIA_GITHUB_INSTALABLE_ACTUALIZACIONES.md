# Aplicativo CyR - GitHub, EXE y actualizaciones

## Objetivo

El usuario final no debe usar archivos BAT ni instalar Python. La entrega debe ser un ZIP con:

- `Aplicativo CyR.exe`
- `LEEME_PRIMERO.txt`
- `VERSION`

El EXE se crea con PyInstaller en modo `--onefile`, por eso incluye Python y las dependencias dentro del ejecutable.

## Flujo recomendado

1. Desarrollar cambios en esta carpeta.
2. Cambiar el numero de version en `VERSION`.
3. Crear el EXE:

```powershell
python crear_instalable.py
```

4. Crear el ZIP para GitHub Releases:

```powershell
python crear_zip_release.py
```

5. Subir cambios a GitHub.
6. Publicar el ZIP generado en GitHub Releases.

## Primera vez: preparar Git

Si esta carpeta todavia no es un repo valido:

```powershell
git init
git add .
git commit -m "Version inicial Aplicativo CyR"
git branch -M main
git remote add origin https://github.com/TU_USUARIO/ruteo-pdf.git
git push -u origin main
```

## Configurar actualizaciones dentro de la app

Abrir `app_update.py` y cambiar:

```python
APP_GITHUB_REPOSITORY = ""
```

por:

```python
APP_GITHUB_REPOSITORY = "TU_USUARIO/ruteo-pdf"
```

Luego volver a crear el EXE y el ZIP.

## Crear nueva version

1. Cambiar `VERSION`, por ejemplo `0.1.1`.
2. Compilar:

```powershell
python crear_instalable.py
```

3. Crear ZIP:

```powershell
python crear_zip_release.py
```

4. Subir a GitHub:

```powershell
git add .
git commit -m "Version 0.1.1"
git tag v0.1.1
git push
git push origin v0.1.1
```

5. En GitHub:
   - Ir a `Releases`.
   - Crear release con tag `v0.1.1`.
   - Adjuntar `Aplicativo CyR_v0.1.1.zip`.

## Como recibe actualizaciones el usuario

El usuario abre la app y usa:

`Ayuda > Buscar actualizaciones`

Si hay una version nueva, la app abre la pagina de GitHub Releases para descargar el ZIP.

## Importante

- No se entregan archivos BAT.
- No se pide instalar Python al usuario final.
- El EXE incluye dependencias.
- La app no actualiza sola sin permiso.
- Las actualizaciones de Google Sheets son independientes y se manejan en el visualizador.
