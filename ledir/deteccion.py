"""
deteccion.py — Detección de blobs de LEDs IR y su estadística (funciones puras, sin cámara).

Funciona con imágenes de 8 bits (webcam, uint8) y de 16 bits (Femto, uint16).
"""

from collections import deque

import cv2
import numpy as np

MAX_CANDIDATOS = 200          # tope de componentes a procesar por cuadro (escena muy iluminada)
MIN_MUESTRAS = 5              # muestras mínimas para dar un resumen


# ---------------------------------------------------------------------------
# Detección de varios blobs
# ---------------------------------------------------------------------------
def _a_gris(img):
    """Asegura imagen 2D (convierte BGR/BGRA a gris)."""
    if img.ndim == 3:
        if img.shape[2] == 1:
            return img[:, :, 0]
        codigo = cv2.COLOR_BGRA2GRAY if img.shape[2] == 4 else cv2.COLOR_BGR2GRAY
        return cv2.cvtColor(img, codigo)
    return img


def detectar_blobs(gris, min_sobre_fondo=40.0, area_min=3, saturacion=None, fraccion_umbral=0.5, margen_roi=4):
    """Regresa (fondo, lista de blobs) ordenada por pico descendente.
    gris: 2D uint8 o uint16 (también acepta 3 canales). saturacion=None -> máximo del dtype."""
    gris = _a_gris(np.asarray(gris))
    if saturacion is None:
        saturacion = np.iinfo(gris.dtype).max if np.issubdtype(gris.dtype, np.integer) else 255
    fondo = float(np.median(gris[::8, ::8]))
    candidatos = (gris > fondo + min_sobre_fondo).astype(np.uint8)
    n, etiquetas_img, stats, _ = cv2.connectedComponentsWithStats(candidatos, connectivity=8)

    # Componentes a procesar: si hay demasiados, solo los de mayor área
    ids = np.arange(1, n)
    if len(ids) > MAX_CANDIDATOS:
        ids = ids[np.argsort(stats[ids, cv2.CC_STAT_AREA])[::-1][:MAX_CANDIDATOS]]

    alto, ancho = gris.shape
    blobs = []
    for i in ids:
        x, y, w, h, _ = stats[i]
        x0, y0 = max(x - margen_roi, 0), max(y - margen_roi, 0)
        x1, y1 = min(x + w + margen_roi, ancho), min(y + h + margen_roi, alto)
        roi = gris[y0:y1, x0:x1].astype(np.float64)

        # Pico dentro del propio componente (no del vecino que caiga en la ROI)
        propio = etiquetas_img[y0:y1, x0:x1] == i
        py, px = np.unravel_index(int(np.argmax(np.where(propio, roi, -1.0))), roi.shape)
        pico = roi[py, px]
        umbral = fondo + fraccion_umbral * (pico - fondo)
        mascara = (roi >= umbral).astype(np.uint8)
        _, etiquetas = cv2.connectedComponents(mascara, connectivity=8)
        blob = etiquetas == etiquetas[py, px]
        area = int(blob.sum())
        if area < area_min:
            continue  # ruido de 1-2 px

        pesos = np.where(blob, np.clip(roi - fondo, 0, None), 0.0)
        suma = pesos.sum()
        if suma <= 0:
            continue
        ys, xs = np.mgrid[0:roi.shape[0], 0:roi.shape[1]]
        mx, my = (pesos * xs).sum() / suma, (pesos * ys).sum() / suma
        # Forma del blob: segundos momentos -> elongación (1 = redondo)
        cxx = (pesos * (xs - mx) ** 2).sum() / suma
        cyy = (pesos * (ys - my) ** 2).sum() / suma
        cxy = (pesos * (xs - mx) * (ys - my)).sum() / suma
        ev = np.linalg.eigvalsh([[cxx, cxy], [cxy, cyy]])
        elong = float(np.sqrt(ev[1] / ev[0])) if ev[0] > 1e-9 else 99.0
        blobs.append({
            "centroide": (float(mx) + x0, float(my) + y0),
            "pico": int(pico),
            "area": area,
            "suma": float(suma),
            "elongacion": elong,
            "saturados": int((roi[blob] >= saturacion).sum()),
        })

    blobs.sort(key=lambda b: b["pico"], reverse=True)
    return fondo, blobs


def seleccionar_par(blobs):
    """Toma los 2 más brillantes y los ordena por el eje en que están más separados:
    izquierda→derecha si están en horizontal, arriba→abajo si están en vertical (A, B)."""
    elegidos = list(blobs[:2])
    if len(elegidos) < 2:
        return elegidos
    xs = [b["centroide"][0] for b in elegidos]
    ys = [b["centroide"][1] for b in elegidos]
    eje = 0 if (max(xs) - min(xs)) >= (max(ys) - min(ys)) else 1
    return sorted(elegidos, key=lambda b: b["centroide"][eje])


def distancia(a, b):
    """Distancia en px entre centroides."""
    return float(np.hypot(a["centroide"][0] - b["centroide"][0], a["centroide"][1] - b["centroide"][1]))


def z_estimada_mm(a, b, fx, fy, sep_mm):
    """Distancia cámara-LEDs con el modelo pinhole: Z = separación real / separación normalizada.
    Válida si la línea entre los LEDs es paralela al plano de la cámara. None si no hay fx/fy."""
    if not fx or not fy:
        return None
    dx = (a["centroide"][0] - b["centroide"][0]) / fx
    dy = (a["centroide"][1] - b["centroide"][1]) / fy
    d = float(np.hypot(dx, dy))
    if d == 0:
        return None
    return float(sep_mm) / d


# ---------------------------------------------------------------------------
# Estadística (ventanas deslizantes)
# ---------------------------------------------------------------------------
class EstadisticaPar:
    """Ventana deslizante de pares (A, B): posición, temblor, distancia y Z."""

    def __init__(self, ventana=60, fx=None, fy=None, sep_mm=50.8):
        self.historial = deque(maxlen=ventana)
        self.fx, self.fy, self.sep_mm = fx, fy, sep_mm

    def agregar(self, par):
        self.historial.append((par[0], par[1]))

    def reiniciar(self):
        self.historial.clear()

    def resumen(self):
        h = self.historial
        if len(h) < MIN_MUESTRAS:
            return None
        arr = np.array([(a["centroide"][0], a["centroide"][1], a["pico"], a["area"], a["saturados"],
                         b["centroide"][0], b["centroide"][1], b["pico"], b["area"], b["saturados"],
                         distancia(a, b)) for a, b in h], dtype=np.float64)
        zs = [z_estimada_mm(a, b, self.fx, self.fy, self.sep_mm) for a, b in h]
        zs = [z for z in zs if z is not None]

        def lado(k):
            return {"cx": float(arr[:, k].mean()), "cy": float(arr[:, k + 1].mean()),
                    "std_x": float(arr[:, k].std()), "std_y": float(arr[:, k + 1].std()),
                    "pico": float(arr[:, k + 2].mean()), "area": float(arr[:, k + 3].mean()),
                    "sat": float(arr[:, k + 4].mean())}

        return {
            "n": len(arr),
            "A": lado(0),
            "B": lado(5),
            "dist": float(arr[:, 10].mean()),
            "dist_std": float(arr[:, 10].std()),
            "z": float(np.mean(zs)) if zs else float("nan"),
        }


class EstadisticaDifusor:
    """Ventana deslizante de un solo blob: posición, temblor, brillo y forma."""

    def __init__(self, ventana=60):
        self.historial = deque(maxlen=ventana)

    def agregar(self, blob):
        self.historial.append(blob)

    def reiniciar(self):
        self.historial.clear()

    def resumen(self):
        h = self.historial
        if len(h) < MIN_MUESTRAS:
            return None
        a = np.array([(b["centroide"][0], b["centroide"][1], b["pico"], b["suma"], b["area"],
                       b["elongacion"], b["saturados"]) for b in h], dtype=np.float64)
        return {"n": len(a), "cx": float(a[:, 0].mean()), "cy": float(a[:, 1].mean()),
                "std_x": float(a[:, 0].std()), "std_y": float(a[:, 1].std()),
                "pico": float(a[:, 2].mean()), "flujo": float(a[:, 3].mean()), "area": float(a[:, 4].mean()),
                "elong": float(a[:, 5].mean()), "sat": float(a[:, 6].mean())}


def corrimiento(resumen, ref):
    """(dx, dy, total) en px del centroide promedio respecto a ref=(x, y). None si no hay ref o resumen."""
    if ref is None or resumen is None:
        return None
    dx, dy = resumen["cx"] - ref[0], resumen["cy"] - ref[1]
    return float(dx), float(dy), float(np.hypot(dx, dy))
