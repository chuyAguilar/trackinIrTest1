# trackinIrTest1

Detecta y mide LEDs IR con cualquier webcam: cuántos ve, distancia entre 2 LEDs y prueba de difusores.

> La webcam debe ser **sin filtro IR** (NoIR). Con una webcam normal solo verás LEDs visibles.

## Requisito: Python 3.12

Descarga **Python 3.12.10**: https://www.python.org/downloads/release/python-31210/
(Windows: "Windows installer (64-bit)"). Al instalar, marca **"Add python.exe to PATH"**.

## Instalar (solo la primera vez, en PowerShell)

```
git clone https://github.com/chuyAguilar/trackinIrTest1.git
cd trackinIrTest1
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Si `activate` da error de permisos (ExecutionPolicy), corre esto una vez y repite `activate`:
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`

## Correr

```
cd trackinIrTest1
.venv\Scripts\activate
python main.py
```

Verás `(.venv)` al inicio de la línea cuando esté activado. En Linux/macOS: `source .venv/bin/activate`.

Otra cámara: `python main.py --listar` y luego `python main.py --camara 1`. Más opciones: `python main.py --help`.

## Teclas

| Tecla | Acción |
|---|---|
| `1` `2` `3` | Modo: Conteo / Distancia 2 LEDs / Difusor |
| `s` | Guardar medición (escribe la etiqueta en la consola) → `resultados/` |
| `z` | Fijar referencia 0° (modo Difusor) |
| `r` | Reiniciar estadística |
| `[` `]` | Exposición (AltGr en teclado español) |
| `u` `j` | Subir / bajar umbral de detección |
| `h` | Ayuda en pantalla |
| `q` | Salir |

Si detecta demasiadas manchas: oscurece el cuarto, baja la exposición con `[` o sube el umbral con `u`.

## LEDs (ESP32)

Carga `firmware/leds_ir/leds_ir.ino` con Arduino IDE (core ESP32 v3.x). En el Monitor Serie (115200): `100` = todos a brillo 100, `2 80` = LED 2 a 80, `off`, `id`.
