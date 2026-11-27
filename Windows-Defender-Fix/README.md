# Investigación de la alerta de Microsoft Defender

Estado: abierto, pendiente de clasificación por Microsoft. Esta carpeta documenta el incidente y los criterios de corrección.

## Incidente del 26 de noviembre de 2026

- Archivo: `J2BStudio.exe`, commit `c73c231697eb848a704225e9f0c4d8f8eae7a40a`.
- Código fuente compilado: `eef74aa522a622fdabc8afa786593b7447738a78`.
- SHA-256 del binario publicado: `b9de055fcd60fd1133c02b73591218a40a0261a6a660a939e1800678851a4879`.
- Detección: `Trojan:Win32/Bearfoos.A!ml`, ID `2147731250`, gravedad grave.
- Windows 11 Pro, build 26300; motor Defender 1.1.26100.4; inteligencia 1.463.485.0.
- Eventos 1116 y 1117: protección en tiempo real y cuarentena aplicada correctamente. `DidThreatExecute=True`, `IsActive=False` y `ActionSuccess=True`. Dos procesos fueron identificados. Estos datos no establecen si hubo acciones maliciosas.

## Evidencia técnica

El ejecutable original es un paquete autónomo PyInstaller 6.22.3 sin firma Authenticode. El cargador extrae componentes a una carpeta temporal al arrancar. Microsoft no publica detalles técnicos sobre esta firma de detección, por lo que todavía no se puede atribuir el bloqueo a ese diseño.

La revisión previa comparó los 40 módulos propios empaquetados con el código fuente y no encontró diferencias. Los recursos JSON también coincidieron. ClamAV 1.5.5, base diaria 28194 del 25 de noviembre, analizó el binario y su contenido extraído: 0 detecciones en 1.177 archivos. Esta comprobación complementaria no sustituye el dictamen de Defender.

## Resolución y validación

1. Mantener la copia detectada en cuarentena. Actualizar Defender y realizar un examen completo del equipo.
2. Presentar el binario publicado, identificado por su SHA-256, a [Microsoft Security Intelligence](https://www.microsoft.com/en-us/wdsi/filesubmission) como posible falso positivo. No es necesario restaurar la copia en cuarentena.
3. Registrar el dictamen de Microsoft. Si identifica contenido malicioso, corregir su origen y auditar las dependencias y la cadena de compilación antes de distribuir un nuevo binario.
4. Verificar el resultado con Defender actualizado y registrar el hash y la fecha de la validación. Hasta entonces, el ejecutable se considera pendiente de revisión.

Referencias: [ficha de detección](https://www.microsoft.com/en-us/wdsi/threats/malware-encyclopedia-description?name=Trojan%3AWin32%2FBearfoos.A%21ml), [eventos Defender](https://learn.microsoft.com/en-us/defender-endpoint/troubleshoot-microsoft-defender-antivirus), [funcionamiento de PyInstaller](https://pyinstaller.org/en/stable/operating-mode.html), [compilación original](https://github.com/alemuca2009-hue/J2B/actions/runs/45915276794).
