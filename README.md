# README — SETA Camera Probe

## Qué es esto

**SETA Camera Probe** es una herramienta de línea de comandos compuesta por:

- un **script Python** que usa **`gphoto2` del sistema** y **`ffplay` del sistema**
- un **wrapper shell** (`run_probe.sh`) para que ejecutarlo sea más simple en Linux

Su objetivo es:

1. **comprobar dependencias del sistema**
2. **detectar una cámara USB compatible con gphoto2**
3. **probar captura de foto**
4. **probar live preview por USB en ffplay**
5. **pedir validación humana**
6. **generar un perfil de compatibilidad**
7. **generar un driver Python para SETA** si la cámara pasa las pruebas

No usa bindings de Python para gphoto2.  
Habla con la cámara exactamente como lo hace SETA: **llamando al binario `gphoto2` del sistema**.

---

## Qué incluye el paquete

El paquete contiene estos archivos:

- `seta_camera_probe.py`  
  Script principal del probe

- `run_probe.sh`  
  Wrapper para ejecutar el probe de forma más simple

- `README.md`  
  Instrucciones de uso

---

## Qué hace el probe

El probe realiza estas pruebas:

- detección de cámara con `gphoto2`
- lectura de información básica
- inspección de settings/config paths
- prueba de captura de foto
- prueba de live preview / streaming por USB usando `ffplay`
- validación humana del resultado

Si todo sale bien, además genera un **driver Python** para SETA.

---

## Requisitos

En Ubuntu/Debian, lo normal es necesitar:

- `python3`
- `gphoto2`
- `ffmpeg`  
  (`ffplay` viene dentro de ese paquete)

Si faltan dependencias, `run_probe.sh` puede ofrecer instalarlas con `sudo`.

---

## Uso básico

### 1) Extraer el ZIP

Extrae el contenido del paquete en una carpeta.

Por ejemplo, si descargaste `seta_camera_probe_bundle_v5.zip`, descomprímelo en cualquier ubicación cómoda.

---

### 2) Abrir terminal en esa carpeta

En Linux puedes hacerlo así:

- abre la carpeta extraída
- clic derecho
- **Open in Terminal** / **Abrir en terminal**

O desde una terminal ya abierta:

```bash
cd /ruta/a/la/carpeta_extraida
```

---

### 3) Dar permiso de ejecución al wrapper

La primera vez:

```bash
chmod +x run_probe.sh
```

---

### 4) Ejecutar el probe

Comando mínimo:

```bash
./run_probe.sh
```

Eso lanza el proceso completo usando los valores por defecto.

---

## Qué esperar durante la prueba

El probe puede:

- detectar la cámara
- leer su configuración
- tomar una o más fotos de prueba
- abrir una ventana de `ffplay` para mostrar preview por USB
- preguntarte si viste correctamente el stream y si fue usable
- generar archivos de salida con logs, reporte y driver

Durante la prueba **no cierres la cámara**, **no desconectes el cable USB**, y evita abrir otros programas que puedan tomar el control de la cámara.

---

## Si faltan dependencias

Si falta algo como `gphoto2` o `ffplay`, `run_probe.sh` puede ofrecer instalarlo automáticamente.

Ejemplo típico en Ubuntu/Debian:

```bash
sudo apt-get update
sudo apt-get install -y python3 gphoto2 ffmpeg
```

---

## Uso con opciones

El probe acepta parámetros opcionales para ajustar tiempos y reintentos.

Ejemplo:

```bash
./run_probe.sh --movie-seconds 20 --capture-retries 3 --stream-recipe-retries 2 --settle-seconds 2 --retry-delay-seconds 6
```

### Qué hace cada opción

#### `--movie-seconds`
Duración del preview/stream de prueba en segundos.

Ejemplo:

```bash
./run_probe.sh --movie-seconds 20
```

Útil cuando la máquina tarda en abrir ffplay o en llenar buffer.

---

#### `--capture-retries`
Número de reintentos para captura de foto si una captura falla.

Ejemplo:

```bash
./run_probe.sh --capture-retries 3
```

Útil para cámaras que a veces quedan ocupadas o tardan en asentarse.

---

#### `--stream-recipe-retries`
Número de reintentos por cada receta de stream antes de pasar a otra receta equivalente.

Ejemplo:

```bash
./run_probe.sh --stream-recipe-retries 2
```

Útil cuando una receta de preview funciona, pero no siempre al primer intento.

---

#### `--settle-seconds`
Pequeña pausa entre operaciones críticas para dejar que la cámara se estabilice.

Ejemplo:

```bash
./run_probe.sh --settle-seconds 2
```

---

#### `--retry-delay-seconds`
Pausa más larga después de un fallo, antes de reintentar.

Ejemplo:

```bash
./run_probe.sh --retry-delay-seconds 6
```

---

#### Ejemplo completo recomendado

```bash
./run_probe.sh --movie-seconds 20 --capture-retries 3 --stream-recipe-retries 2 --settle-seconds 2 --retry-delay-seconds 6
```

Ese es un buen punto de partida para cámaras que a veces fallan por estado transitorio.

---

## Qué archivos genera

Cada ejecución crea una carpeta nueva dentro de `probe_runs/`, con timestamp.

Ejemplo típico:

```text
probe_runs/20260416_190220/
```

Ahí se guardan:

- logs
- reportes
- capturas de prueba
- resultados de validación
- driver generado, si la prueba fue positiva

---

## Dónde se guarda el driver generado

Si la cámara pasa como válida para SETA, el driver se guarda en:

```text
probe_runs/<timestamp>/generated/<driver_id>.py
```

Ejemplo real validado por el probe:

```text
probe_runs/20260416_190220/generated/canon_eos_4000d.py
```

Ese fue el archivo generado cuando la Canon EOS 4000D pasó correctamente la prueba.  
El contenido del driver generado sigue el formato declarativo esperado por SETA, heredando de `GPhoto2CameraDriver`.

---

## Qué hacer si la prueba es positiva

Si el resultado final es positivo y el driver fue generado:

1. ubica el archivo generado en:
   ```text
   probe_runs/<timestamp>/generated/
   ```

2. copia ese archivo a la carpeta de drivers del addon SETA

La referencia práctica es la misma carpeta donde viven drivers como:

```text
drivers/canon_eos_3000d_4000d.py
```

En muchos setups eso será algo parecido a:

```text
seta/drivers/
```

o la carpeta `drivers/` dentro del addon, según cómo tengas organizado tu repo o instalación.

### Paso final típico

```bash
cp probe_runs/20260416_190220/generated/canon_eos_4000d.py /ruta/a/tu/addon/seta/drivers/
```

Después de eso, reinicia Blender o recarga el addon si hace falta.

---

## Qué significa una prueba exitosa

Una cámara se considera realmente válida cuando:

- fue detectada correctamente
- la captura de foto funcionó
- el stream/live preview funcionó
- validaste visualmente que el preview sirve
- el probe pudo construir el driver

Ejemplo real de resultado positivo:

- `Final status: FULLY_USABLE_FOR_SETA`
- driver generado: `probe_runs/20260416_190220/generated/canon_eos_4000d.py`

---

## Qué pasa si una prueba falla

No todo fallo significa “cámara no soportada”.

Puede fallar por cosas como:

- cámara ocupada
- estado transitorio del dispositivo
- operaciones muy seguidas
- preview y captura pisándose
- tiempo de espera insuficiente
- otro proceso usando la cámara

Por eso el probe incluye:

- reintentos
- pausas entre operaciones
- varias recetas equivalentes de preview/stream

Y si aun así falla, el reporte puede sugerir volver a ejecutar el probe desde cero.

---

## Recomendaciones prácticas

Antes de correr el probe:

- conecta la cámara por USB
- enciéndela
- ponla en modo foto si aplica
- evita abrir otros programas que usen la cámara
- deja puesta batería suficiente
- asegúrate de que la cámara no esté apagándose sola

Si un intento falla y luego otro funciona, eso normalmente apunta a un **estado transitorio**, no necesariamente a falta de soporte real.

---

## Resumen rápido

### Ejecutar

```bash
chmod +x run_probe.sh
./run_probe.sh
```

### Ejecutar con ajustes

```bash
./run_probe.sh --movie-seconds 20 --capture-retries 3 --stream-recipe-retries 2 --settle-seconds 2 --retry-delay-seconds 6
```

### Driver generado

```text
probe_runs/<timestamp>/generated/<driver_id>.py
```

### Paso final

Copiar ese `.py` a la carpeta de drivers del addon SETA.

---

## Resultado esperado

Si todo sale bien, terminas con:

- una prueba técnica real de compatibilidad
- validación visual del preview
- logs y reportes
- un **driver Python listo para meter en SETA**

Eso convierte el probe en algo más que un tester:  
lo vuelve una herramienta para **verificar compatibilidad real y construir el driver resultante**.
