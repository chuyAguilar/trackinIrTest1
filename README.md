# trackinIrTest1

Detecta y mide LEDs IR con cualquier webcam: cuántos ve, distancia entre 2 LEDs y prueba de difusores.

> La webcam debe ser **sin filtro IR** (NoIR). Con una webcam normal solo verás LEDs visibles.

## Instalar y correr (Windows)

```
git clone https://github.com/chuyAguilar/trackinIrTest1.git
cd trackinIrTest1
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe main.py
```

En Linux/macOS usa `.venv/bin/python` en lugar de `.venv\Scripts\python.exe`.

Otra cámara: `main.py --listar` y luego `main.py --camara 1`. Más opciones: `main.py --help`.

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
