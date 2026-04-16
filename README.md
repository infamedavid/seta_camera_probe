# SETA Camera Probe

**seta Camera Probe** es una herramienta de línea de comandos para testear la compativilidad de  camaras DSRL y seta

**Funcion:**

1. **comprobar dependencias del sistema**
2. **detectar una cámara USB compatible**
3. **probar captura de foto**
4. **probar live preview por USB**
5. **pedir validación humana**
6. **generar un perfil de compatibilidad**
7. **generar un driver Python para seta motion si la cámara pasa las pruebas**

--

no es necesario para dispositivos moviles 
--

## Requisitos

En Ubuntu/Debian, lo normal es necesitar:

- `python3`
- `gphoto2`
- `ffmpeg`

`run_probe.sh` puede ofrecer instalarlas con `sudo`.

---

## Uso básico

### 1) Extraer el ZIP

Extrae el contenido del paquete en una carpeta.



### 2) Dar permiso de ejecución al wrapper

- clic derecho
- Propiedades
- Permitir ejecutar como un programa 

### 3) Abrir terminal en esa carpeta

En Linux puedes hacerlo así:

- abre la carpeta extraída
- clic derecho
- **Open in Terminal** / **Abrir en terminal**

### 4) Ejecutar el probe

Comando mínimo:

```bash
./run_probe.sh
```

Eso lanza el proceso completo usando los valores por defecto.

## Proceso de prueba:

El probe puede:

- detectar la cámara
- leer su configuración
- tomar una o más fotos de prueba
- abrir una ventana de `Live Preview` para mostrar preview por USB
- preguntarte si viste correctamente el stream y si fue usable
- generar archivos de salida con logs, reporte y driver

Durante la prueba **no cierres la cámara**, **no desconectes el cable USB**, y evita abrir otros programas que puedan tomar el control de la cámara.

---

## Si faltan dependencias

Si falta algo como `gphoto2` o `ffmpeg`, `run_probe.sh` puede ofrecer instalarlo automáticamente.


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

Útil cuando la máquina tarda en abrir ffmpeg o en llenar buffer.

---

#### `--capture-retries`
Número de reintentos para captura de foto si una captura falla.

Ejemplo:

```bash
./run_probe.sh --capture-retries 3
```

Útil para cámaras que a veces quedan ocupadas o tardan.

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
- driver generado, si la prueba fue positiva <<esto es lo que te intereza

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

Ese fue el archivo generado cuando mi Canon EOS 4000D pasó correctamente la prueba.  

---

## Qué hacer si la prueba es positiva

Si el resultado final es positivo y el driver fue generado:

1. ubica el archivo generado en:
   ```text
   probe_runs/<timestamp>/generated/
   ```

2. copia ese archivo a la carpeta de drivers del addon SETA

```text
seta/drivers/
```

Después de eso, reinicia Blender

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

Si un intento falla puiedes correr el programa nuevamente ajustando  parametros para beneficiar el funcionamiento correcto de la camara.

______________


