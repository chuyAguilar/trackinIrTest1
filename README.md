# LED IR — detectar y medir LEDs infrarrojos con una webcam

Programa sencillo que usa **cualquier webcam** para ver LEDs infrarrojos (IR) y medirlos:

- **Conteo**: cuántos LEDs ve la cámara y qué tan brillantes son.
- **Distancia entre 2 LEDs**: mide la separación entre dos LEDs (en píxeles y en mm).
- **Difusor**: caracteriza un difusor (la "bolita" que cubre el LED) midiendo cómo cambia el brillo al girarlo.

Incluye también el firmware para encender los LEDs con un ESP32.

---

## 1. Requisitos

- **Python 3.10 o más nuevo** ([python.org](https://www.python.org/downloads/)). En Windows, al instalarlo marca la casilla **"Add Python to PATH"**.
- **Git** ([git-scm.com](https://git-scm.com/downloads)).
- **Una webcam** (USB o la integrada).

> **AVISO IMPORTANTE — filtro IR**
> Casi todas las webcams normales traen un **filtro de corte IR**: no ven la luz infrarroja.
> Necesitas una cámara **sin filtro IR**, por ejemplo:
> - una cámara "**NoIR**" o "**night vision**" que **no** tenga iluminador IR propio (o con el iluminador apagado, porque deslumbra), o
> - una webcam a la que le hayas **quitado el filtro IR**.
>
> **Para probar** que el programa funciona, sirve cualquier webcam con un **LED visible** (de color).

---

## 2. Instalación (solo la primera vez)

### Windows (PowerShell)

```powershell
git clone https://github.com/chuyAguilar/trackinIrTest1.git
cd trackinIrTest1
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

**Si al activar sale un error rojo de "la ejecución de scripts está deshabilitada" (ExecutionPolicy)**, ejecuta esto una sola vez y vuelve a activar:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

O bien, sin activar nada, usa directamente el Python del entorno:

```powershell
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe main.py
```

### Linux / macOS (Terminal)

```bash
git clone https://github.com/chuyAguilar/trackinIrTest1.git
cd trackinIrTest1
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

> Cada vez que abras una terminal nueva, entra a la carpeta y **activa el entorno** otra vez
> (`.venv\Scripts\Activate.ps1` en Windows, `source .venv/bin/activate` en Linux/macOS).

---

## 3. Uso

```bash
python main.py                 # abre la cámara 0 (la predeterminada)
python main.py --listar        # muestra qué cámaras hay disponibles
python main.py --camara 1      # usa la cámara 1 (por ejemplo una USB externa)
```

Más ejemplos:

```bash
python main.py --sep 30                      # los 2 LEDs están separados 30 mm
python main.py --dist 400                    # la cámara está a unos 400 mm de los LEDs
python main.py --ancho 1280 --alto 720       # pide esa resolución a la cámara
python main.py --fov 60                      # campo de visión horizontal de la cámara: 60°
python main.py --calibracion mi_camara.json  # usa una calibración de la cámara (más preciso)
```

### Modos

Cambia de modo con las teclas **1**, **2**, **3** o **Tab**.

| Tecla | Modo | Qué mide |
|---|---|---|
| **1** | Conteo | Número de LEDs detectados, posición y brillo de cada uno. |
| **2** | Distancia 2 LEDs | Separación entre los 2 LEDs en píxeles y en mm, y distancia aproximada a la cámara (Z). |
| **3** | Difusor | Brillo y tamaño del punto de luz respecto a una referencia, para comparar ángulos. |

**Flujo de trabajo del difusor (modo 3):**

1. Coloca el LED con el difusor **de frente a la cámara (0°)**.
2. Pulsa **z** para guardar esa posición como **referencia**.
3. Gira el difusor a **15°**, pulsa **r** (reinicia la estadística), **espera ~3 segundos** y pulsa **s** para guardar la fila (escribe la etiqueta en la consola, p. ej. `15`).
4. Repite el paso 3 para **30°, 45°, 60° y 75°**.

### Teclas

| Tecla | Acción |
|---|---|
| **q** / **Esc** | Salir |
| **1** / **2** / **3** / **Tab** | Cambiar de modo |
| **r** | Reiniciar la estadística (promedios) |
| **s** | Guardar una fila en el CSV (pide una etiqueta en la consola) |
| **z** | Guardar referencia (modo 3, difusor) |
| **+** / **-** | Más / menos brillo de la **visualización** (no afecta la medición) |
| **[** / **]** | Bajar / subir la **exposición** de la cámara (en teclado español: **AltGr**) |
| **u** / **j** | Subir / bajar el **umbral** de detección (de 5 en 5) |
| **h** | Mostrar / ocultar la ayuda en pantalla |

### Argumentos

| Argumento | Por defecto | Qué hace |
|---|---|---|
| `--camara N` | `0` | Número de la cámara a usar |
| `--listar` | — | Lista las cámaras disponibles y sale |
| `--ancho` / `--alto` | (los de la cámara) | Resolución a pedir a la cámara |
| `--sep MM` | `50.8` | Separación real entre los 2 LEDs, en mm |
| `--dist MM` | `600` | Distancia aproximada cámara–LEDs, en mm |
| `--fov GRADOS` | `70` | Campo de visión horizontal de la cámara |
| `--calibracion RUTA` | — | Archivo JSON con la calibración de la cámara |
| `--umbral N` | `40` | Umbral de brillo para detectar un LED (0–255) |

---

## 4. Resultados

Al pulsar **s** se agrega una fila a un archivo CSV dentro de la carpeta `resultados/`:

| Modo | Archivo |
|---|---|
| Conteo | `resultados/conteo.csv` |
| Distancia 2 LEDs | `resultados/dos_leds.csv` |
| Difusor | `resultados/difusor.csv` |

Se pueden abrir con Excel o LibreOffice. Esta carpeta **no se sube a git** (son tus datos locales).

**Sobre la precisión:** sin calibración, la distancia Z y los mm son **aproximados** (se calculan a partir del FOV de `--fov`).
Para mejores resultados usa `--calibracion` con un archivo JSON como este:

```json
{ "fx": 600.0, "fy": 600.0, "cx": 320.0, "cy": 240.0, "width": 640, "height": 480 }
```

---

## 5. Firmware (ESP32)

El archivo `firmware/leds_ir/leds_ir.ino` controla 5 LEDs (pines 25, 21, 32, 33, 22) con brillo independiente.
Para cambiar la cantidad de LEDs o los pines, edita `NUM_LEDS` y `PINES` al inicio del archivo.

1. Instala **Arduino IDE** y el soporte para **ESP32** (Gestor de tarjetas → "esp32" de Espressif, **versión 3.x**).
2. Abre `firmware/leds_ir/leds_ir.ino`, elige tu placa ESP32 y el puerto, y pulsa **Subir**.
3. Abre el **Monitor Serie** a **115200** baudios con la opción **"New Line"**.

| Comando | Qué hace |
|---|---|
| `120` | Todos los LEDs a brillo 120 (0–255) |
| `2 80` | Solo el LED 2 a brillo 80 |
| `0` o `off` | Apaga todos |
| `id` | Enciende un LED a la vez, cambiando cada segundo (para identificarlos) |
| `estado` | Muestra el brillo de cada LED |

Al encender el ESP32, todos los LEDs arrancan **apagados**.

> **Seguridad ocular:** la luz IR **no se ve**, aunque el LED esté encendido a máximo brillo.
> **No mires los LEDs de cerca** ni directamente; usa brillos bajos mientras pruebas.

---

## 6. Solución de problemas

| Problema | Qué hacer |
|---|---|
| **"No se pudo abrir la cámara"** | Cierra otras apps que usen la cámara (Zoom, Teams, la app Cámara...). Prueba `python main.py --listar` y luego `--camara 1`, `--camara 2`... |
| **No veo los LEDs** | Revisa que la cámara **no tenga filtro IR** (ver Requisitos). Sube la exposición con **]** y baja el umbral con **j**. |
| **Detecta decenas de "LEDs"** / aviso *Demasiadas manchas brillantes* | Con una webcam normal en un cuarto iluminado cualquier reflejo cuenta. Oscurece el cuarto, baja la exposición con **[** y/o sube el umbral con **u** hasta que solo queden los LEDs. |
| **Todo sale saturado / rojo** | Baja el brillo del LED (p. ej. `30` en el Monitor Serie) o baja la exposición con **[**. |
| **La exposición no cambia** | Algunas webcams no permiten controlarla desde el programa; es una limitación del driver de la cámara. |
| **`python` no se reconoce** | Reinstala Python marcando "Add Python to PATH", o en Windows usa `py` en lugar de `python`. |

---

## 7. Estructura del repositorio

```
main.py                 -> punto de entrada (python main.py)
ledir/
  app.py                -> ventana, modos, teclas y CSV
  camara.py             -> abrir y configurar la webcam
  deteccion.py          -> detección y medición de los LEDs
firmware/
  leds_ir/leds_ir.ino   -> firmware del ESP32
cad/difusores/          -> modelos STL de difusores para imprimir en 3D
tests/                  -> pruebas automáticas
resultados/             -> aquí se guardan tus CSV
```

Modelos en `cad/difusores/`: `Esfera1_14mm.STL`, `Esfera_12mm_v1.STL`, `Esfera_15mm_v1.STL`, `Esfera_15mm_v2.STL`,
`Esfero_15mm_Tapa.STL`, `Esfero_15mm_Tapa_v2.STL`, `ID_Cancer.STL`, `LED_1mm.STL`, `PruebaBase.STL`.

---

## 8. Pruebas (opcional, para desarrolladores)

```bash
pip install -r requirements-dev.txt
python -m pytest
```
