"""Acceso a cualquier webcam vía OpenCV (Windows, Linux, macOS).

- listar_camaras(): busca cámaras disponibles.
- Camara: abre una cámara, lee cuadros (BGR + gris) y controla exposición/ganancia (best-effort).
- intrinsecos(): parámetros de cámara desde un JSON de calibración o aproximados por FOV.

Prueba rápida:  python -m ledir.camara
"""

import contextlib
import json
import math
import os
import sys

# Antes de importar cv2: oculta los avisos internos de OpenCV al probar backends
os.environ.setdefault("OPENCV_LOG_LEVEL", "ERROR")

import cv2
import numpy as np

# Valores de CAP_PROP_AUTO_EXPOSURE (cada backend usa una convención distinta, es una rareza de OpenCV):
#   DirectShow (Windows): 0.25 = manual, 0.75 = auto (heredado de la vieja convención de V4L).
#   V4L2 (Linux): 1 = manual (V4L2_EXPOSURE_MANUAL), 3 = auto (V4L2_EXPOSURE_APERTURE_PRIORITY).
#   Otros backends (MSMF, AVFoundation): casi nunca lo soportan; probamos 0.25/0.75.
_AUTO_EXPO = {
    cv2.CAP_DSHOW: (0.25, 0.75),
    cv2.CAP_V4L2: (1.0, 3.0),
}


def _backends():
    """Backends a probar según el sistema operativo, en orden de preferencia."""
    if sys.platform.startswith("win"):
        # DSHOW primero: es el que permite controlar la exposición
        return [cv2.CAP_DSHOW, cv2.CAP_MSMF, cv2.CAP_ANY]
    if sys.platform == "darwin":
        return [cv2.CAP_AVFOUNDATION, cv2.CAP_ANY]
    return [cv2.CAP_V4L2, cv2.CAP_ANY]


def _nombre_backend(cap, api):
    try:
        return cap.getBackendName()
    except cv2.error:
        return {cv2.CAP_DSHOW: "DSHOW", cv2.CAP_MSMF: "MSMF", cv2.CAP_V4L2: "V4L2",
                cv2.CAP_AVFOUNDATION: "AVFOUNDATION"}.get(api, "ANY")


@contextlib.contextmanager
def _silencio():
    """Silencia los warnings de OpenCV mientras probamos cámaras."""
    # Según la versión de OpenCV la función está en cv2 o en cv2.utils.logging (0 = silencio)
    mod = cv2 if hasattr(cv2, "setLogLevel") else getattr(getattr(cv2, "utils", None), "logging", None)
    anterior = None
    if mod is not None:
        try:
            anterior = mod.getLogLevel()
            mod.setLogLevel(0)
        except Exception:  # noqa: BLE001
            anterior = None
    try:
        yield
    finally:
        if anterior is not None:
            mod.setLogLevel(anterior)


def _abrir(indice, api, ancho=None, alto=None, fps=None):
    """Intenta abrir con un backend. Regresa (cap, cuadro) o (None, None)."""
    cap = cv2.VideoCapture(indice, api)
    if not cap.isOpened():
        cap.release()
        return None, None
    if ancho:
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, ancho)
    if alto:
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, alto)
    if fps:
        cap.set(cv2.CAP_PROP_FPS, fps)
    # Algunas cámaras tardan unos cuadros en entregar imagen
    for _ in range(10):
        ok, cuadro = cap.read()
        if ok and cuadro is not None and cuadro.size > 0:
            return cap, cuadro
    cap.release()
    return None, None


def listar_camaras(max_indice=6):
    """Prueba índices 0..max_indice-1 y regresa las cámaras que entregan imagen."""
    encontradas = []
    with _silencio():
        for i in range(max_indice):
            for api in _backends():
                cap, cuadro = _abrir(i, api)
                if cap is None:
                    continue
                encontradas.append({"indice": i, "ancho": int(cuadro.shape[1]),
                                    "alto": int(cuadro.shape[0]), "backend": _nombre_backend(cap, api)})
                cap.release()
                break
    return encontradas


class Camara:
    def __init__(self, indice=0, ancho=None, alto=None, fps=None):
        self.indice = indice
        self.cap = None
        self._api = None
        cuadro = None
        with _silencio():
            for api in _backends():
                cap, cuadro = _abrir(indice, api, ancho, alto, fps)
                if cap is not None:
                    self.cap, self._api = cap, api
                    break
        if self.cap is None:
            raise RuntimeError(
                f"No se pudo abrir la cámara {indice}. Revisa que esté conectada y que ninguna otra "
                f"aplicación la esté usando. Prueba con --listar para ver las cámaras disponibles.")
        # Tamaño REAL (la cámara puede ignorar lo que pedimos)
        self.alto, self.ancho = int(cuadro.shape[0]), int(cuadro.shape[1])
        self.backend = _nombre_backend(self.cap, self._api)
        if (ancho and ancho != self.ancho) or (alto and alto != self.alto):
            print(f"  Aviso: se pidió {ancho}x{alto} pero la cámara entrega {self.ancho}x{self.alto}.")

    # --- con 'with' ---
    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.cerrar()

    def leer(self):
        """Regresa (bgr, gris uint8) o None si falla el cuadro."""
        if self.cap is None:
            return None
        ok, cuadro = self.cap.read()
        if not ok or cuadro is None or cuadro.size == 0:
            return None
        if cuadro.ndim == 2:  # algunas cámaras IR ya entregan gris
            gris = cuadro
            bgr = cv2.cvtColor(cuadro, cv2.COLOR_GRAY2BGR)
        else:
            bgr = cuadro
            gris = cv2.cvtColor(cuadro, cv2.COLOR_BGR2GRAY)
        if gris.dtype != np.uint8:
            gris = cv2.normalize(gris, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
        return bgr, gris

    # --- propiedades genéricas ---
    def _leer_prop(self, prop):
        if self.cap is None:
            return None
        try:
            v = self.cap.get(prop)
        except cv2.error:
            return None
        # OpenCV regresa 0 o -1 cuando no soporta la propiedad (ambiguo, pero es lo que hay)
        if v is None or (isinstance(v, float) and math.isnan(v)):
            return None
        return float(v)

    def _poner_prop(self, prop, valor):
        if self.cap is None:
            return False
        try:
            return bool(self.cap.set(prop, valor))
        except cv2.error:
            return False

    # --- exposición ---
    def soporta_exposicion(self):
        """True si la cámara parece aceptar cambios de exposición."""
        v = self._leer_prop(cv2.CAP_PROP_EXPOSURE)
        if v is None:
            return False
        # Probamos escribir el mismo valor: si lo acepta, la soporta
        return self._poner_prop(cv2.CAP_PROP_EXPOSURE, v) or v != 0

    def auto_exposicion(self, activar):
        """Activa/desactiva la auto-exposición. Best-effort; True si la cámara aceptó."""
        manual, auto = _AUTO_EXPO.get(self._api, (0.25, 0.75))
        return self._poner_prop(cv2.CAP_PROP_AUTO_EXPOSURE, auto if activar else manual)

    def exposicion(self):
        return self._leer_prop(cv2.CAP_PROP_EXPOSURE)

    def cambiar_exposicion(self, delta):
        """Suma delta a la exposición (apaga auto antes). En DSHOW la escala es log2 de segundos
        (típico -13..-1, pasos de 1: -6 = 1/64 s). Regresa el valor leído después o None."""
        actual = self.exposicion()
        if actual is None:
            return None
        self.auto_exposicion(False)
        if not self._poner_prop(cv2.CAP_PROP_EXPOSURE, actual + delta):
            return None
        return self.exposicion()

    # --- ganancia ---
    def ganancia(self):
        return self._leer_prop(cv2.CAP_PROP_GAIN)

    def cambiar_ganancia(self, delta):
        """Suma delta a la ganancia (apaga auto-exposición antes). Regresa el valor leído o None."""
        actual = self.ganancia()
        if actual is None:
            return None
        self.auto_exposicion(False)
        if not self._poner_prop(cv2.CAP_PROP_GAIN, actual + delta):
            return None
        return self.ganancia()

    def cerrar(self):
        if self.cap is not None:
            self.cap.release()
            self.cap = None


def intrinsecos(ancho, alto, fov_h_deg=70.0, ruta_json=None):
    """Intrínsecos de la cámara: del JSON de calibración si existe, si no aproximados por FOV."""
    distorsion = {k: 0.0 for k in ("k1", "k2", "k3", "k4", "k5", "k6", "p1", "p2")}
    if ruta_json and os.path.isfile(ruta_json):
        try:
            with open(ruta_json, encoding="utf-8") as f:
                d = json.load(f)
            cal = {**distorsion, **{k: float(d[k]) for k in distorsion if k in d}}
            fx, fy, cx, cy = (float(d[k]) for k in ("fx", "fy", "cx", "cy"))
            w0, h0 = int(d.get("width", ancho)), int(d.get("height", alto))
        except (OSError, ValueError, KeyError, TypeError) as e:
            raise RuntimeError(f"El archivo de calibración {ruta_json} no se pudo leer o le faltan datos "
                               f"(fx, fy, cx, cy): {e}") from e
        fuente = f"archivo {os.path.basename(ruta_json)}"
        if (w0, h0) != (ancho, alto):
            # Escalamos proporcionalmente al tamaño actual
            sx, sy = ancho / w0, alto / h0
            fx, cx, fy, cy = fx * sx, cx * sx, fy * sy, cy * sy
            fuente += f" (escalado de {w0}x{h0} a {ancho}x{alto})"
        cal.update(fx=fx, fy=fy, cx=cx, cy=cy, width=int(ancho), height=int(alto), fuente=fuente)
        return cal
    f = (ancho / 2.0) / math.tan(math.radians(fov_h_deg) / 2.0)
    return {**distorsion, "fx": f, "fy": f, "cx": ancho / 2.0, "cy": alto / 2.0,
            "width": int(ancho), "height": int(alto), "fuente": f"aprox. FOV {fov_h_deg:g}°"}


if __name__ == "__main__":
    print("Buscando cámaras...")
    camaras = listar_camaras()
    if not camaras:
        print("No se encontró ninguna cámara. Revisa que esté conectada y que no la use otra aplicación.")
        sys.exit(1)
    for c in camaras:
        print(f"  Cámara {c['indice']}: {c['ancho']}x{c['alto']} ({c['backend']})")
    indice = camaras[0]["indice"]
    try:
        with Camara(indice) as cam:
            print(f"\nCámara {indice} abierta: {cam.ancho}x{cam.alto}, backend {cam.backend}")
            ok = sum(cam.leer() is not None for _ in range(10))
            print(f"  Cuadros leídos: {ok}/10")
            print(f"  Soporta exposición: {cam.soporta_exposicion()}  (actual: {cam.exposicion()})")
            print(f"  Ganancia actual: {cam.ganancia()}")
            print(f"  cambiar_exposicion(-1) -> {cam.cambiar_exposicion(-1)}")
            print(f"  cambiar_exposicion(+1) -> {cam.cambiar_exposicion(+1)}")
            print(f"  auto_exposicion(True) -> {cam.auto_exposicion(True)}")
            k = intrinsecos(cam.ancho, cam.alto)
            print(f"  Intrínsecos ({k['fuente']}): fx={k['fx']:.1f} fy={k['fy']:.1f} cx={k['cx']:.1f} cy={k['cy']:.1f}")
    except RuntimeError as e:
        print(e)
        sys.exit(1)
