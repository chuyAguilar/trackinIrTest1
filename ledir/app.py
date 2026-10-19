"""
app.py — Herramienta de LEDs IR con cualquier webcam (una sola ventana, 3 modos).

Uso (desde la raíz del repo):
    python main.py                      # cámara 0
    python main.py --listar             # ver qué cámaras hay
    python main.py --camara 1 --ancho 1280 --alto 720
    python main.py --sep 50.8 --dist 600 --fov 70

Modos (teclas 1/2/3, Tab para ciclar):
  1 CONTEO     cuántos LEDs se ven; pico, área y centroide de cada uno, y el fondo.
  2 DISTANCIA  los 2 LEDs más brillantes (A/B): distancia en px ± std y Z estimada.
  3 DIFUSOR    el LED más brillante: zoom, pico/flujo/área/elongación, temblor y
               corrimiento del centroide respecto a una referencia (tecla 'z' a 0°).

Teclas (con la ventana activa):
  q / Esc  salir                      1 / 2 / 3 / Tab  cambiar de modo
  r        reiniciar estadística      s  guardar fila en resultados/<modo>.csv
  z        fijar referencia (modo 3)  + / -  brillo de visualización (solo visual)
  [ / ]    bajar / subir exposición   u / j  subir / bajar umbral de detección (de 5 en 5)
  h        mostrar / ocultar la ayuda en pantalla

Nota: las webcams normales traen filtro IR; si no ves los LEDs, usa una cámara sin
filtro IR (NoIR) o pruébalo con un LED visible.
"""

import argparse
import csv
import math
import sys
import time
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from ledir.camara import Camara, intrinsecos, listar_camaras
from ledir.deteccion import (EstadisticaDifusor, EstadisticaPar, corrimiento, detectar_blobs,
                             distancia, seleccionar_par)

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------
VENTANA = "LEDs IR"
RAIZ = Path(__file__).resolve().parent.parent          # raíz del repo (no el cwd)
CARPETA_RESULTADOS = RAIZ / "resultados"
CSV_POR_MODO = {1: "conteo.csv", 2: "dos_leds.csv", 3: "difusor.csv"}
NOMBRE_MODO = {1: "1 CONTEO", 2: "2 DISTANCIA 2 LEDs", 3: "3 DIFUSOR"}
FACTORES_BRILLO = [0.25, 0.5, 1.0, 2.0, 4.0, 8.0, 16.0]  # x1 = imagen original en color
BRILLO_INICIAL = 2
PASO_UMBRAL = 5
VENTANA_ESTADISTICA = 60                                 # cuadros (~2 s a 30 fps)
ELONG_MAX = 3.0            # un LED se ve casi redondo; manchas más alargadas son reflejos/bordes
MUCHOS_BLOBS = 20          # más que esto = escena muy iluminada, no LEDs

# Colores BGR
VERDE, ROJO, AMARILLO = (0, 220, 0), (0, 0, 255), (0, 255, 255)
CIAN, MAGENTA, BLANCO = (255, 255, 0), (255, 0, 255), (255, 255, 255)
FUENTE = cv2.FONT_HERSHEY_SIMPLEX

AYUDA_CORTA = ("q salir | 1/2/3 Tab modo | r reiniciar | s guardar | z ref | "
               "+/- brillo | [ ] exposicion | u/j umbral | h ayuda")
AYUDA_LARGA = [  # (tecla, descripción)
    ("q / Esc", "salir"),
    ("1 2 3", "modo conteo / distancia 2 LEDs / difusor"),
    ("Tab", "siguiente modo"),
    ("r", "reiniciar estadistica"),
    ("s", "guardar fila CSV (etiqueta en la consola)"),
    ("z", "fijar referencia 0 grados (modo 3)"),
    ("+ / -", "brillo de visualizacion (no cambia la medicion)"),
    ("[ / ]", "bajar / subir exposicion de la camara"),
    ("u / j", "subir / bajar umbral de deteccion"),
    ("h", "ocultar esta ayuda"),
]
MENSAJE_INICIO = """
=== LEDs IR ===
Teclas (con la ventana de video activa):
  q/Esc salir | 1/2/3 o Tab cambiar modo | r reiniciar estadística | s guardar CSV
  z referencia 0° (modo difusor) | +/- brillo visual | [ ] exposición | u/j umbral | h ayuda
Los CSV se guardan en: {carpeta}

Las webcams normales traen filtro IR; si no ves los LEDs, usa una cámara sin filtro IR (NoIR) o pruébalo con un LED visible.
"""


# ---------------------------------------------------------------------------
# Estado de la aplicación (sin globales)
# ---------------------------------------------------------------------------
class Estado:
    """Lo que cambia con las teclas + datos fijos de la sesión (cámara, intrínsecos)."""

    def __init__(self, indice_camara, ancho, alto, intr, sep_mm, dist_mm, umbral):
        self.indice_camara = indice_camara
        self.ancho, self.alto = ancho, alto
        self.intr = intr
        self.sep_mm = sep_mm
        self.dist_mm = dist_mm
        self.umbral = float(umbral)
        self.modo = 1
        self.brillo_idx = BRILLO_INICIAL
        self.ayuda = False
        self.ref = None                 # (cx, cy) del difusor a 0°
        self.exposicion = None
        self.fps = 0.0
        self.aviso = ""                 # mensaje temporal en pantalla
        self.aviso_hasta = 0.0

    @property
    def brillo(self):
        return FACTORES_BRILLO[self.brillo_idx]

    @property
    def intr_aprox(self):
        """True si fx/fy salen del FOV supuesto y no de una calibración."""
        return "fov" in str(self.intr.get("fuente", "")).lower()

    @property
    def mm_por_px(self):
        return self.dist_mm / self.intr["fx"]

    def avisar(self, texto, segundos=3.0):
        self.aviso, self.aviso_hasta = texto, time.time() + segundos
        print(f"  {texto}")


class Medicion:
    """Resultado de procesar un cuadro."""

    def __init__(self, fondo, blobs, par, res_par, blob_dif, res_dif):
        self.fondo, self.blobs = fondo, blobs
        self.par, self.res_par = par, res_par
        self.blob_dif, self.res_dif = blob_dif, res_dif


def procesar(gris, estado, est_par, est_dif):
    """Detecta blobs y alimenta la estadística del modo activo."""
    fondo, blobs = detectar_blobs(gris, min_sobre_fondo=estado.umbral)
    blobs = [b for b in blobs if b["elongacion"] <= ELONG_MAX]
    par = seleccionar_par(blobs)
    blob_dif = blobs[0] if blobs else None
    if estado.modo == 2 and len(par) == 2:
        est_par.agregar(par)
    if estado.modo == 3 and blob_dif is not None:
        est_dif.agregar(blob_dif)
    return Medicion(fondo, blobs, par, est_par.resumen(), blob_dif, est_dif.resumen())


# ---------------------------------------------------------------------------
# Utilidades de dibujo
# ---------------------------------------------------------------------------
def escala_fuente(img):
    """Tamaño de letra según el alto (legible en 480p y 1080p)."""
    return max(0.45, img.shape[0] / 1000.0)


def grosor(fs):
    return max(1, int(round(fs * 2)))


def es_valido(v):
    return v is not None and not (isinstance(v, float) and math.isnan(v))


def caja_texto(img, lineas, x, y, fs, color=CIAN, alfa=0.55, colores=None):
    """Dibuja líneas de texto sobre un rectángulo oscuro semitransparente.
    (x, y) = esquina superior izquierda. Regresa la y donde termina la caja."""
    if not lineas:
        return y
    g = grosor(fs)
    tam = [cv2.getTextSize(t, FUENTE, fs, g) for t in lineas]
    alto_linea = int(max(s[0][1] + s[1] for s in tam) * 1.45)
    ancho = max(s[0][0] for s in tam) + 16
    alto = alto_linea * len(lineas) + 10
    x1, y1 = min(x + ancho, img.shape[1]), min(y + alto, img.shape[0])
    if x1 > x and y1 > y:
        sub = img[y:y1, x:x1]
        sub[:] = (sub * (1 - alfa)).astype(np.uint8)
    for i, t in enumerate(lineas):
        c = colores[i] if colores else color
        base = y + 5 + alto_linea * (i + 1) - int(alto_linea * 0.3)
        cv2.putText(img, t, (x + 8, base), FUENTE, fs, c, g, cv2.LINE_AA)
    return y + alto


def texto_contorno(img, texto, org, fs, color, g=None):
    """Texto con contorno negro (para etiquetas sobre la imagen)."""
    g = g or grosor(fs)
    cv2.putText(img, texto, org, FUENTE, fs, (0, 0, 0), g + 3, cv2.LINE_AA)
    cv2.putText(img, texto, org, FUENTE, fs, color, g, cv2.LINE_AA)


def partir_ayuda(texto, ancho_max, fs):
    """Parte la ayuda en varias líneas (por ' | ') para que quepa en el ancho."""
    g = grosor(fs)
    lineas, actual = [], ""
    for parte in texto.split(" | "):
        prueba = parte if not actual else actual + " | " + parte
        if actual and cv2.getTextSize(prueba, FUENTE, fs, g)[0][0] + 16 > ancho_max:
            lineas.append(actual)
            actual = parte
        else:
            actual = prueba
    if actual:
        lineas.append(actual)
    return lineas


def preparar_vista(bgr, gris, brillo):
    """x1 = imagen original en color; otro factor = gris escalado linealmente con clip."""
    if brillo == 1.0 and bgr is not None:
        return bgr.copy()
    vis = np.clip(gris.astype(np.float32) * brillo, 0, 255).astype(np.uint8)
    return cv2.cvtColor(vis, cv2.COLOR_GRAY2BGR)


def punto(b):
    return int(round(b["centroide"][0])), int(round(b["centroide"][1]))


def dibujar_blobs(vis, blobs):
    """Círculo + número (1..N por brillo); rojo si saturado, verde si no."""
    fs = escala_fuente(vis) * 0.9
    esc = vis.shape[0] / 720.0
    for i, b in enumerate(blobs, start=1):
        color = ROJO if b["saturados"] > 0 else VERDE
        r = int(max(10 * esc, math.sqrt(b["area"]) * 1.2 + 8 * esc))
        x, y = punto(b)
        cv2.circle(vis, (x, y), r, color, grosor(fs), cv2.LINE_AA)
        texto_contorno(vis, str(i), (x + r + 2, y - r), fs, color)


def dibujar_cabecera(vis, n_leds, estado):
    """Arriba y grande: 'LEDs detectados: N' y el modo actual."""
    fs = escala_fuente(vis)
    g = grosor(fs * 1.8)
    texto = f"LEDs detectados: {n_leds}"
    (w, h), base = cv2.getTextSize(texto, FUENTE, fs * 1.8, g)
    sub = vis[0:h + base + 20, 0:min(w + 24, vis.shape[1])]
    sub[:] = (sub * 0.4).astype(np.uint8)
    cv2.putText(vis, texto, (12, h + 10), FUENTE, fs * 1.8, VERDE if n_leds else ROJO, g, cv2.LINE_AA)
    y = caja_texto(vis, [f"Modo {NOMBRE_MODO[estado.modo]}   (1/2/3 o Tab)"], 0, h + base + 22, fs, AMARILLO)
    if n_leds > MUCHOS_BLOBS:
        y = caja_texto(vis, ["Demasiadas manchas brillantes: oscurece el cuarto,",
                             "baja la exposicion con [ o sube el umbral con u"], 0, y + 4, fs, ROJO)
    return y + 4


def dibujar_barra_inferior(vis, estado):
    """Estado (FPS, resolución, exposición...) + ayuda corta de teclas."""
    fs = escala_fuente(vis) * 0.85
    expo = f"{estado.exposicion:g}" if es_valido(estado.exposicion) else "auto/N.D."
    info = (f"FPS {estado.fps:4.1f} | {estado.ancho}x{estado.alto} | exposicion {expo} | "
            f"umbral {estado.umbral:.0f} | brillo vis x{estado.brillo:g}")
    lineas = partir_ayuda(info, vis.shape[1], fs) + partir_ayuda(AYUDA_CORTA, vis.shape[1], fs)
    g = grosor(fs)
    alto_linea = int((cv2.getTextSize("Ag", FUENTE, fs, g)[0][1] + 8) * 1.45)
    y0 = vis.shape[0] - alto_linea * len(lineas) - 10
    colores = [BLANCO] * (len(lineas) - len(partir_ayuda(AYUDA_CORTA, vis.shape[1], fs)))
    colores += [CIAN] * (len(lineas) - len(colores))
    caja_texto(vis, lineas, 0, max(y0, 0), fs, colores=colores, alfa=0.65)


def dibujar_ayuda(vis):
    """Recuadro central con todas las teclas (dos columnas alineadas)."""
    fs = escala_fuente(vis)
    g = grosor(fs)
    col = max(cv2.getTextSize(k, FUENTE, fs, g)[0][0] for k, _ in AYUDA_LARGA) + int(30 * fs)
    ancho = col + max(cv2.getTextSize(d, FUENTE, fs, g)[0][0] for _, d in AYUDA_LARGA) + 24
    alto_linea = int(cv2.getTextSize("Ag", FUENTE, fs, g)[0][1] * 2.2)
    alto = alto_linea * (len(AYUDA_LARGA) + 1) + 12
    x = max((vis.shape[1] - ancho) // 2, 0)
    y = max((vis.shape[0] - alto) // 2, 0)
    sub = vis[y:y + alto, x:x + ancho]
    sub[:] = (sub * 0.2).astype(np.uint8)
    cv2.putText(vis, "TECLAS", (x + 12, y + alto_linea), FUENTE, fs, AMARILLO, g, cv2.LINE_AA)
    for i, (k, d) in enumerate(AYUDA_LARGA, start=2):
        yy = y + alto_linea * i
        cv2.putText(vis, k, (x + 12, yy), FUENTE, fs, CIAN, g, cv2.LINE_AA)
        cv2.putText(vis, d, (x + 12 + col, yy), FUENTE, fs, BLANCO, g, cv2.LINE_AA)


def dibujar_aviso(vis, estado):
    if estado.aviso and time.time() < estado.aviso_hasta:
        fs = escala_fuente(vis) * 1.1
        w = cv2.getTextSize(estado.aviso, FUENTE, fs, grosor(fs))[0][0] + 16
        caja_texto(vis, [estado.aviso], max((vis.shape[1] - w) // 2, 0), vis.shape[0] // 2, fs, AMARILLO, alfa=0.8)


def zoom_blob(gris, blob, lado):
    """Recorte 32x32 alrededor del blob, normalizado a su pico, con COLORMAP_INFERNO."""
    z = 16
    x, y = punto(blob)
    pad = cv2.copyMakeBorder(gris, z, z, z, z, cv2.BORDER_CONSTANT, value=0)
    rec = pad[y:y + 2 * z, x:x + 2 * z].astype(np.float32)   # (x,y) ya desplazados por el borde
    rec = np.clip(rec * (255.0 / max(blob["pico"], 1)), 0, 255).astype(np.uint8)
    rec = cv2.resize(rec, (lado, lado), interpolation=cv2.INTER_NEAREST)
    return cv2.applyColorMap(rec, cv2.COLORMAP_INFERNO)


# ---------------------------------------------------------------------------
# Dibujo por modo (escriben sobre vis a partir de la altura y)
# ---------------------------------------------------------------------------
def dibujar_conteo(vis, med, y):
    fs = escala_fuente(vis) * 0.85
    lineas = [f"Fondo: {med.fondo:.0f}"]
    colores = [CIAN]
    max_lineas = max(1, int((vis.shape[0] * 0.55) / (fs * 40)))
    for i, b in enumerate(med.blobs[:max_lineas], start=1):
        cx, cy = b["centroide"]
        lineas.append(f"{i}: pico {b['pico']}  area {b['area']} px  ({cx:.2f}, {cy:.2f})"
                      f"{'  SAT' if b['saturados'] else ''}")
        colores.append(ROJO if b["saturados"] else VERDE)
    if len(med.blobs) > max_lineas:
        lineas.append(f"... y {len(med.blobs) - max_lineas} mas")
        colores.append(CIAN)
    if not med.blobs:
        lineas.append("Sin LEDs: acerca el LED, sube exposicion (]) o baja el umbral (j)")
        colores.append(AMARILLO)
    caja_texto(vis, lineas, 0, y, fs, colores=colores)


def dibujar_dos_leds(vis, med, estado, y):
    fs = escala_fuente(vis) * 0.85
    lineas, colores = [f"Fondo: {med.fondo:.0f}   (separacion real {estado.sep_mm:g} mm)"], [CIAN]
    if len(med.par) == 2:
        a, b = med.par
        cv2.line(vis, punto(a), punto(b), MAGENTA, grosor(fs), cv2.LINE_AA)
        for nombre, led in zip("AB", med.par):
            cx, cy = led["centroide"]
            color = ROJO if led["saturados"] else VERDE
            x, yy = punto(led)
            texto_contorno(vis, nombre, (x - int(30 * fs), yy - int(25 * fs)), fs * 1.3, MAGENTA)
            lineas.append(f"{nombre}: pico {led['pico']}  area {led['area']} px  sat {led['saturados']}  "
                          f"({cx:.2f}, {cy:.2f})")
            colores.append(color)
        lineas.append(f"Distancia A-B: {distancia(a, b):.3f} px")
        colores.append(BLANCO)
        s = med.res_par
        if s:
            lineas.append(f"Estabilidad ({s['n']} cuadros): {s['dist']:.3f} +/- {s['dist_std']:.4f} px")
            colores.append(BLANCO)
            if es_valido(s.get("z")):
                aprox = " (aprox.: fx por FOV)" if estado.intr_aprox else ""
                lineas.append(f"Z estimada camara-LEDs: {s['z']:.0f} mm{aprox}")
                colores.append(BLANCO)
        if a["saturados"] or b["saturados"]:
            lineas.append("!! SATURADO: baja la exposicion ([) hasta que ambos circulos sean verdes")
            colores.append(ROJO)
    else:
        lineas.append(f"Faltan LEDs: veo {len(med.par)} de 2")
        colores.append(AMARILLO)
    caja_texto(vis, lineas, 0, y, fs, colores=colores)


def dibujar_difusor(vis, gris, med, estado, y):
    fs = escala_fuente(vis) * 0.85
    b, s = med.blob_dif, med.res_dif
    lineas, colores = [], []
    if b:
        x, yy = punto(b)
        color = ROJO if b["saturados"] else VERDE
        largo = int(20 * vis.shape[0] / 720.0)
        cv2.drawMarker(vis, (x, yy), color, cv2.MARKER_CROSS, largo, grosor(fs))
        lineas.append(f"pico {b['pico']}  flujo {b['suma']:.0f}  area {b['area']} px  "
                      f"elong {b['elongacion']:.2f}{'  SATURADO' if b['saturados'] else ''}")
        colores.append(color)
        if s:
            lineas.append(f"centroide ({s['cx']:.2f}, {s['cy']:.2f})  std ({s['std_x']:.3f}, {s['std_y']:.3f}) px")
            colores.append(BLANCO)
            corr = corrimiento(s, estado.ref) if estado.ref is not None else None
            if corr is not None:
                d = corr[2]
                lineas.append(f"corrimiento vs ref: {d:.3f} px  (~{d * estado.mm_por_px:.2f} mm a "
                              f"{estado.dist_mm:.0f} mm)")
                colores.append(BLANCO)
            else:
                lineas.append("Sin referencia: pon el difusor a 0 grados y presiona 'z'")
                colores.append(AMARILLO)
        # Zoom en la esquina superior derecha
        lado = max(128, int(256 * vis.shape[0] / 720.0))
        lado = min(lado, vis.shape[1] // 3, vis.shape[0] // 2)
        if lado >= 32:
            x0 = vis.shape[1] - lado - 10
            vis[10:10 + lado, x0:x0 + lado] = zoom_blob(gris, b, lado)
            cv2.rectangle(vis, (x0 - 1, 9), (x0 + lado, 10 + lado), BLANCO, 1)
            texto_contorno(vis, "zoom 32x32", (x0, 10 + lado + int(22 * fs)), fs * 0.8, BLANCO)
    else:
        lineas.append("Sin LED detectado")
        colores.append(AMARILLO)
    caja_texto(vis, lineas, 0, y, fs, colores=colores)


def componer(bgr, gris, med, estado):
    """Arma el cuadro completo que se muestra en la ventana."""
    vis = preparar_vista(bgr, gris, estado.brillo)
    dibujar_blobs(vis, med.blobs)
    y =dibujar_cabecera(vis, len(med.blobs), estado)
    if estado.modo == 1:
        dibujar_conteo(vis, med, y)
    elif estado.modo == 2:
        dibujar_dos_leds(vis, med, estado, y)
    else:
        dibujar_difusor(vis, gris, med, estado, y)
    dibujar_barra_inferior(vis, estado)
    if estado.ayuda:
        dibujar_ayuda(vis)
    dibujar_aviso(vis, estado)
    return vis


# ---------------------------------------------------------------------------
# CSV (uno por modo, en resultados/)
# ---------------------------------------------------------------------------
COLUMNAS_COMUNES = ["fecha", "etiqueta", "camara", "resolucion", "exposicion", "umbral"]


def _f(v, fmt):
    """Formatea un número; vacío si es None/NaN."""
    return format(v, fmt) if es_valido(v) else ""


def metadatos(estado, etiqueta):
    return [datetime.now().isoformat(timespec="seconds"), etiqueta, estado.indice_camara,
            f"{estado.ancho}x{estado.alto}", _f(estado.exposicion, "g"), f"{estado.umbral:.0f}"]


def escribir_filas(nombre, encabezado, filas, carpeta=None):
    """Agrega filas al CSV; escribe el encabezado solo si el archivo es nuevo."""
    carpeta = Path(carpeta) if carpeta else CARPETA_RESULTADOS
    carpeta.mkdir(parents=True, exist_ok=True)
    ruta = carpeta / nombre
    nuevo = not ruta.exists() or ruta.stat().st_size == 0
    with open(ruta, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if nuevo:
            w.writerow(encabezado)
        w.writerows(filas)
    return ruta


def guardar_conteo(med, estado, etiqueta, carpeta=None):
    """Una fila por LED detectado (si no hay ninguno, una fila con n_leds = 0)."""
    enc = COLUMNAS_COMUNES + ["fondo", "n_leds", "led", "cx", "cy", "pico", "area_px", "saturados", "elongacion"]
    meta = metadatos(estado, etiqueta) + [f"{med.fondo:.1f}", len(med.blobs)]
    filas = [meta + [i, f"{b['centroide'][0]:.3f}", f"{b['centroide'][1]:.3f}", b["pico"], b["area"],
                     b["saturados"], f"{b['elongacion']:.3f}"]
             for i, b in enumerate(med.blobs, start=1)]
    return escribir_filas(CSV_POR_MODO[1], enc, filas or [meta + [""] * 7], carpeta)


def guardar_dos_leds(med, estado, etiqueta, carpeta=None):
    s = med.res_par
    enc = COLUMNAS_COMUNES + ["n_cuadros", "dist_px", "dist_std_px", "z_estimada_mm", "intrinsecos", "sep_mm",
                              "A_cx", "A_cy", "A_std_x", "A_std_y", "A_pico", "A_area", "A_sat",
                              "B_cx", "B_cy", "B_std_x", "B_std_y", "B_pico", "B_area", "B_sat", "fondo"]
    fila = metadatos(estado, etiqueta) + [s["n"], f"{s['dist']:.3f}", f"{s['dist_std']:.4f}", _f(s.get("z"), ".1f"),
                                          estado.intr.get("fuente", ""), f"{estado.sep_mm:g}"]
    for k in ("A", "B"):
        d = s[k]
        fila += [f"{d['cx']:.3f}", f"{d['cy']:.3f}", f"{d['std_x']:.4f}", f"{d['std_y']:.4f}",
                 f"{d['pico']:.0f}", f"{d['area']:.1f}", f"{d['sat']:.1f}"]
    fila.append(f"{med.fondo:.1f}")
    return escribir_filas(CSV_POR_MODO[2], enc, [fila], carpeta)


def guardar_difusor(med, estado, etiqueta, carpeta=None):
    s = med.res_dif
    enc = COLUMNAS_COMUNES + ["n_cuadros", "pico", "flujo", "area_px", "elongacion", "saturados",
                              "cx", "cy", "std_x_px", "std_y_px", "corr_x_px", "corr_y_px", "corr_total_px",
                              "corr_total_mm_aprox", "dist_mm_supuesta"]
    corr = corrimiento(s, estado.ref) if estado.ref is not None else None
    dx, dy, tot = corr if corr is not None else (None, None, None)
    tot_mm = tot * estado.mm_por_px if tot is not None else None
    fila = metadatos(estado, etiqueta) + [
        s["n"], f"{s['pico']:.0f}", f"{s['flujo']:.0f}", f"{s['area']:.1f}", f"{s['elong']:.3f}", f"{s['sat']:.2f}",
        f"{s['cx']:.3f}", f"{s['cy']:.3f}", f"{s['std_x']:.4f}", f"{s['std_y']:.4f}",
        _f(dx, ".3f"), _f(dy, ".3f"), _f(tot, ".3f"), _f(tot_mm, ".3f"), f"{estado.dist_mm:.0f}"]
    return escribir_filas(CSV_POR_MODO[3], enc, [fila], carpeta)


def datos_listos(med, modo):
    """¿Hay datos suficientes para guardar en este modo?"""
    if modo == 1:
        return True
    return (med.res_par if modo == 2 else med.res_dif) is not None


GUARDAR_POR_MODO = {1: guardar_conteo, 2: guardar_dos_leds, 3: guardar_difusor}


# ---------------------------------------------------------------------------
# Consola
# ---------------------------------------------------------------------------
def resumen_consola(med, estado):
    """Línea corta para imprimir cada ~1 s (como el código viejo)."""
    if estado.modo == 1:
        picos = ", ".join(str(b["pico"]) for b in med.blobs[:6])
        return f"[conteo] LEDs {len(med.blobs)} | fondo {med.fondo:.0f} | picos {picos or '-'}"
    if estado.modo == 2:
        s, par = med.res_par, med.par
        if len(par) == 2 and s:
            z = f"{s['z']:.0f} mm" if es_valido(s.get("z")) else "-"
            return (f"[2 LEDs] blobs {len(med.blobs)} | A pico {par[0]['pico']} area {par[0]['area']} | "
                    f"B pico {par[1]['pico']} area {par[1]['area']} | dist {s['dist']:.3f} +/- {s['dist_std']:.4f} px | "
                    f"std A ({s['A']['std_x']:.3f}, {s['A']['std_y']:.3f}) B ({s['B']['std_x']:.3f}, "
                    f"{s['B']['std_y']:.3f}) px | Z {z} | sat A {par[0]['saturados']} B {par[1]['saturados']}")
        return f"[2 LEDs] blobs detectados: {len(med.blobs)} (esperados 2) | fondo {med.fondo:.0f}"
    s = med.res_dif
    if not s:
        return f"[difusor] sin datos suficientes | blobs {len(med.blobs)}"
    extra = ""
    corr = corrimiento(s, estado.ref) if estado.ref is not None else None
    if corr is not None:
        extra = f" | corr {corr[2]:.3f} px (~{corr[2] * estado.mm_por_px:.2f} mm)"
    return (f"[difusor] pico {s['pico']:.0f} | flujo {s['flujo']:.0f} | area {s['area']:.1f} | "
            f"elong {s['elong']:.2f} | std ({s['std_x']:.3f}, {s['std_y']:.3f}) px{extra} | blobs {len(med.blobs)}")


def pedir_etiqueta():
    try:
        return input("  Etiqueta (ej. 'LED 30', 'brillo 160, 1 m'): ").strip()
    except (EOFError, KeyboardInterrupt):
        return ""


# ---------------------------------------------------------------------------
# Argumentos
# ---------------------------------------------------------------------------
def crear_parser():
    p = argparse.ArgumentParser(
        prog="python main.py",
        description="Detecta y mide LEDs IR con cualquier webcam (conteo, distancia entre 2 LEDs, difusor).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        add_help=False,
        epilog="""ejemplos:
  python main.py                         usa la cámara 0
  python main.py --listar                lista las cámaras disponibles y sale
  python main.py --camara 1              usa la cámara 1
  python main.py --ancho 1280 --alto 720 pide 1280x720 a la cámara
  python main.py --sep 30 --dist 1000    LEDs a 30 mm; difusor a ~1 m
  python main.py --calibracion intrinsecos.json

teclas: q/Esc salir | 1/2/3/Tab modo | r reiniciar | s guardar CSV | z referencia (modo 3)
        +/- brillo visual | [ ] exposición | u/j umbral | h ayuda

Las webcams normales traen filtro IR; si no ves los LEDs, usa una cámara sin filtro IR (NoIR)
o pruébalo con un LED visible.""")
    p._optionals.title = "opciones"
    p.add_argument("-h", "--help", action="help", help="muestra esta ayuda y sale")
    p.add_argument("--camara", type=int, default=0, metavar="N", help="índice de la cámara (default 0)")
    p.add_argument("--listar", action="store_true", help="lista las cámaras disponibles y sale")
    p.add_argument("--ancho", type=int, default=None, help="ancho de imagen a pedir (ej. 1280)")
    p.add_argument("--alto", type=int, default=None, help="alto de imagen a pedir (ej. 720)")
    p.add_argument("--sep", type=float, default=50.8, metavar="MM",
                   help="separación real entre los 2 LEDs en mm (default 50.8)")
    p.add_argument("--dist", type=float, default=600.0, metavar="MM",
                   help="distancia aprox. cámara-difusor en mm, para convertir px a mm (default 600)")
    p.add_argument("--fov", type=float, default=70.0, metavar="GRADOS",
                   help="FOV horizontal de la cámara para aproximar fx (default 70)")
    p.add_argument("--calibracion", default=None, metavar="RUTA",
                   help="JSON opcional con intrínsecos (fx, fy, cx, cy) de la cámara")
    p.add_argument("--umbral", type=float, default=40.0, metavar="N",
                   help="cuánto debe superar un pixel al fondo para ser LED (default 40)")
    return p


def listar(max_indice=6):
    print("Buscando cámaras...")
    camaras = listar_camaras(max_indice=max_indice)
    if not camaras:
        print("No se encontró ninguna cámara.")
        return
    for c in camaras:
        print(f"  --camara {c['indice']}   {c['ancho']}x{c['alto']}   ({c['backend']})")


# ---------------------------------------------------------------------------
# Ventana y teclas
# ---------------------------------------------------------------------------
def crear_ventana(estado):
    cv2.namedWindow(VENTANA, cv2.WINDOW_NORMAL)
    # Ventana inicial que quepa en pantallas comunes
    f = min(1.0, 900.0 / max(estado.alto, 1), 1500.0 / max(estado.ancho, 1))
    cv2.resizeWindow(VENTANA, int(estado.ancho * f), int(estado.alto * f))
    try:
        cv2.createTrackbar("Umbral", VENTANA, int(estado.umbral), 255, lambda v: None)
        cv2.createTrackbar("Brillo vis", VENTANA, estado.brillo_idx, len(FACTORES_BRILLO) - 1, lambda v: None)
        cv2.setTrackbarMin("Umbral", VENTANA, 1)
        return True
    except cv2.error:
        return False


def sincronizar_trackbars(estado, ultimos):
    """Lee los trackbars; si el usuario los movió, actualiza el estado. Regresa los valores vistos."""
    try:
        u = cv2.getTrackbarPos("Umbral", VENTANA)
        b = cv2.getTrackbarPos("Brillo vis", VENTANA)
    except cv2.error:
        return ultimos
    if ultimos is not None:
        if u != ultimos[0] and u >= 1:
            estado.umbral = float(u)
        if b != ultimos[1]:
            estado.brillo_idx = b
    return u, b


def poner_trackbars(estado):
    try:
        cv2.setTrackbarPos("Umbral", VENTANA, int(min(max(estado.umbral, 1), 255)))
        cv2.setTrackbarPos("Brillo vis", VENTANA, estado.brillo_idx)
    except cv2.error:
        pass
    return int(min(max(estado.umbral, 1), 255)), estado.brillo_idx


def cambiar_modo(estado, modo, est_par, est_dif):
    if modo != estado.modo:
        estado.modo = modo
        est_par.reiniciar()
        est_dif.reiniciar()
        estado.avisar(f"Modo {NOMBRE_MODO[modo]}", 1.5)


def guardar_interactivo(bgr, gris, med, estado):
    """Pide la etiqueta por consola y guarda la fila del modo actual."""
    if not datos_listos(med, estado.modo):
        estado.avisar("Aun no hay suficientes cuadros con los LEDs detectados")
        return
    estado.aviso, estado.aviso_hasta = "Escribe la etiqueta en la consola", time.time() + 60
    cv2.imshow(VENTANA, componer(bgr, gris, med, estado))
    cv2.waitKey(1)
    print("\n  >> Escribe la etiqueta en la consola y presiona Enter")
    ruta = GUARDAR_POR_MODO[estado.modo](med, estado, pedir_etiqueta())
    estado.avisar(f"Guardado en resultados/{ruta.name}")


def manejar_tecla(t, cam, estado, est_par, est_dif, bgr, gris, med):
    """Aplica una tecla. Regresa False si hay que salir."""
    if t in (ord("q"), ord("Q"), 27):
        return False
    if t in (ord("1"), ord("2"), ord("3")):
        cambiar_modo(estado, t - ord("0"), est_par, est_dif)
    elif t == 9:  # Tab
        cambiar_modo(estado, estado.modo % 3 + 1, est_par, est_dif)
    elif t == ord("r"):
        est_par.reiniciar()
        est_dif.reiniciar()
        estado.avisar("Estadistica reiniciada", 1.5)
    elif t == ord("z"):
        if estado.modo != 3:
            estado.avisar("La referencia 'z' es del modo 3 (difusor)")
        elif med.res_dif:
            estado.ref = (med.res_dif["cx"], med.res_dif["cy"])
            estado.avisar(f"Referencia fijada en ({estado.ref[0]:.3f}, {estado.ref[1]:.3f})")
        else:
            estado.avisar("Espera unos cuadros con el LED detectado")
    elif t in (ord("+"), ord("=")):
        estado.brillo_idx = min(estado.brillo_idx + 1, len(FACTORES_BRILLO) - 1)
    elif t in (ord("-"), ord("_")):
        estado.brillo_idx = max(estado.brillo_idx - 1, 0)
    elif t in (ord("["), ord("]")):
        if not cam.soporta_exposicion():
            estado.avisar("Esta camara no permite cambiar la exposicion")
        else:
            nueva = cam.cambiar_exposicion(-1 if t == ord("[") else 1)
            estado.avisar(f"Exposicion: {nueva:g}" if es_valido(nueva) else "No se pudo cambiar la exposicion", 1.5)
    elif t == ord("u"):
        estado.umbral = min(estado.umbral + PASO_UMBRAL, 255)
        estado.avisar(f"Umbral: {estado.umbral:.0f}", 1.0)
    elif t == ord("j"):
        estado.umbral = max(estado.umbral - PASO_UMBRAL, 1)
        estado.avisar(f"Umbral: {estado.umbral:.0f}", 1.0)
    elif t == ord("h"):
        estado.ayuda = not estado.ayuda
    elif t == ord("s"):
        guardar_interactivo(bgr, gris, med, estado)
    return True


# ---------------------------------------------------------------------------
# Programa principal
# ---------------------------------------------------------------------------
def abrir_camara(args):
    try:
        return Camara(args.camara, ancho=args.ancho, alto=args.alto)
    except Exception as e:  # RuntimeError u otro error del backend
        detalle = "" if isinstance(e, RuntimeError) else f" ({e})"
        print(f"\nERROR: no se pudo abrir la cámara {args.camara}.{detalle}")
        print("  - Revisa que esté conectada y que ninguna otra app (Zoom, Teams, Cámara) la esté usando.")
        print("  - Para ver qué cámaras hay:  python main.py --listar")
        print("  - Luego elige una con:       python main.py --camara N")
        return None


def bucle(cam, estado):
    est_par = EstadisticaPar(ventana=VENTANA_ESTADISTICA, fx=estado.intr["fx"], fy=estado.intr["fy"],
                             sep_mm=estado.sep_mm)
    est_dif = EstadisticaDifusor(ventana=VENTANA_ESTADISTICA)
    crear_ventana(estado)
    trackbars = poner_trackbars(estado)
    t_prev, ultimo_print, fallos = time.time(), time.time(), 0

    while True:
        cuadro = cam.leer()
        if cuadro is None:
            fallos += 1
            if fallos > 100:
                print("ERROR: la cámara dejó de enviar imágenes.")
                return
            if cv2.waitKey(10) & 0xFF in (ord("q"), 27):
                return
            continue
        fallos = 0
        bgr, gris = cuadro

        ahora = time.time()
        dt = ahora - t_prev
        t_prev = ahora
        if dt > 0:
            estado.fps = 1.0 / dt if estado.fps == 0 else 0.9 * estado.fps + 0.1 / dt
        estado.exposicion = cam.exposicion()

        trackbars = sincronizar_trackbars(estado, trackbars)
        med = procesar(gris, estado, est_par, est_dif)
        cv2.imshow(VENTANA, componer(bgr, gris, med, estado))

        if ahora - ultimo_print >= 1.0:
            ultimo_print = ahora
            print(resumen_consola(med, estado))

        t = cv2.waitKey(1) & 0xFF
        if t != 255:
            if not manejar_tecla(t, cam, estado, est_par, est_dif, bgr, gris, med):
                return
            trackbars = poner_trackbars(estado)
        # Cerrar con la X de la ventana
        try:
            if cv2.getWindowProperty(VENTANA, cv2.WND_PROP_VISIBLE) < 1:
                return
        except cv2.error:
            return


def main(argv=None):
    args = crear_parser().parse_args(argv)
    if args.listar:
        listar()
        return 0

    cam = abrir_camara(args)
    if cam is None:
        sys.exit(1)

    try:
        if args.calibracion and not Path(args.calibracion).is_file():
            print(f"  Aviso: no existe {args.calibracion}; uso fx aproximado por FOV {args.fov:g}°.")
        try:
            intr = intrinsecos(cam.ancho, cam.alto, fov_h_deg=args.fov, ruta_json=args.calibracion)
        except RuntimeError as e:
            print(f"\nERROR: {e}")
            sys.exit(1)
        estado = Estado(args.camara, cam.ancho, cam.alto, intr, args.sep, args.dist, args.umbral)
        print(MENSAJE_INICIO.format(carpeta=CARPETA_RESULTADOS))
        print(f"Cámara {args.camara}: {cam.ancho}x{cam.alto} ({cam.backend}) | "
              f"fx {intr['fx']:.1f} fy {intr['fy']:.1f} ({intr.get('fuente', '')})\n")
        bucle(cam, estado)
    except KeyboardInterrupt:
        pass
    finally:
        cam.cerrar()
        cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    main()
