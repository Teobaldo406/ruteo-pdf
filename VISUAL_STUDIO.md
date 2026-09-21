# Abrir el proyecto en Visual Studio Community

1. Instala **Visual Studio Community 2022** con la carga de trabajo **Desarrollo de Python**. Visual Studio puede ofrecer instalarla automáticamente desde `.vsconfig`.
2. Abre `RUTEO_PYTHON_APP.sln`.
3. En **Entornos de Python**, crea o selecciona un entorno virtual basado en Python 3.12 o posterior.
4. Abre una terminal dentro de Visual Studio y ejecuta:

   ```powershell
   python -m pip install --upgrade pip
   python -m pip install -r requirements.txt
   ```

5. Confirma que `main.py` esté marcado como archivo de inicio.
6. Pulsa **F5** para depurar o **Ctrl+F5** para ejecutar sin depuración.

## Prueba rápida

```powershell
python -m unittest discover -s tests -v
```

Si Visual Studio no reconoce el proyecto, abre **Visual Studio Installer**, selecciona **Modificar** y activa **Desarrollo de Python**.
