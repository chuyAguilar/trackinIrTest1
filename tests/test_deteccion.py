"""Pruebas de ledir.deteccion con imágenes sintéticas."""

import math

import cv2
import numpy as np
import pytest

from ledir.deteccion import (EstadisticaDifusor, EstadisticaPar, corrimiento, detectar_blobs, distancia,
                             seleccionar_par, z_estimada_mm)

ALTO, ANCHO = 480, 640


def imagen(leds, fondo=10.0, ruido=1.5, dtype=np.uint8, semilla=0, alto=ALTO, ancho=ANCHO):
    """Fondo + ruido + gaussianas. leds = [(x, y, amplitud, sigma), ...]."""
    rng = np.random.default_rng(semilla)
    img = np.full((alto, ancho), fondo, dtype=np.float64) + rng.normal(0, ruido, (alto, ancho))
    for x, y, amp, s in leds:
        r = int(6 * s) + 2
        x0, x1 = max(int(x) - r, 0), min(int(x) + r + 1, ancho)
        y0, y1 = max(int(y) - r, 0), min(int(y) + r + 1, alto)
        ys, xs = np.mgrid[y0:y1, x0:x1]
        img[y0:y1, x0:x1] += amp * np.exp(-((xs - x) ** 2 + (ys - y) ** 2) / (2 * s * s))
    tope = np.iinfo(dtype).max
    return np.clip(np.round(img), 0, tope).astype(dtype)


def blob(x, y, pico=200, area=20, suma=1000.0, elong=1.0, sat=0):
    return {"centroide": (x, y), "pico": pico, "area": area, "suma": suma, "elongacion": elong, "saturados": sat}


# ---------------------------------------------------------------------------
# detectar_blobs
# ---------------------------------------------------------------------------
def test_dos_leds_centroides_subpixel():
    leds = [(200.3, 150.7, 180, 2.5), (420.8, 300.2, 120, 2.0)]
    fondo, blobs = detectar_blobs(imagen(leds))
    assert abs(fondo - 10) <= 1
    assert len(blobs) == 2
    # orden por pico descendente
    assert blobs[0]["pico"] >= blobs[1]["pico"]
    for b, (x, y, _, _) in zip(blobs, leds):
        assert abs(b["centroide"][0] - x) < 0.1
        assert abs(b["centroide"][1] - y) < 0.1
        assert b["saturados"] == 0
        assert b["area"] >= 3
        assert b["suma"] > 0
        assert 1.0 <= b["elongacion"] < 1.3


def test_claves_exactas():
    _, blobs = detectar_blobs(imagen([(100.0, 100.0, 150, 2.0)]))
    assert set(blobs[0]) == {"centroide", "pico", "area", "suma", "elongacion", "saturados"}
    assert isinstance(blobs[0]["pico"], int) and isinstance(blobs[0]["area"], int)
    assert isinstance(blobs[0]["centroide"][0], float)


def test_saturados_uint8():
    _, blobs = detectar_blobs(imagen([(300.0, 200.0, 600, 3.0)]))
    assert len(blobs) == 1
    assert blobs[0]["pico"] == 255
    assert blobs[0]["saturados"] > 1
    assert abs(blobs[0]["centroide"][0] - 300) < 0.1
    assert abs(blobs[0]["centroide"][1] - 200) < 0.1


def test_descarta_pixeles_sueltos():
    img = imagen([(320.4, 240.6, 150, 2.0)])
    img[50, 50] = 255                 # pixel caliente aislado
    img[400, 600:602] = 200           # par de pixeles
    _, blobs = detectar_blobs(img, area_min=3)
    assert len(blobs) == 1
    assert abs(blobs[0]["centroide"][0] - 320.4) < 0.1
    # con area_min=1 sí aparecen
    _, todos = detectar_blobs(img, area_min=1)
    assert len(todos) == 3


def test_elongacion_blob_alargado():
    img = np.full((200, 200), 10, dtype=np.float64)
    ys, xs = np.mgrid[0:200, 0:200]
    img += 150 * np.exp(-((xs - 100) ** 2 / (2 * 6.0 ** 2) + (ys - 100) ** 2 / (2 * 2.0 ** 2)))
    _, blobs = detectar_blobs(img.astype(np.uint8))
    assert len(blobs) == 1
    assert blobs[0]["elongacion"] > 2.5


def test_imagen_tres_canales():
    gris = imagen([(250.2, 120.9, 160, 2.5)])
    bgr = cv2.cvtColor(gris, cv2.COLOR_GRAY2BGR)
    _, b1 = detectar_blobs(gris)
    _, b3 = detectar_blobs(bgr)
    assert len(b3) == 1
    assert b3[0]["centroide"] == pytest.approx(b1[0]["centroide"], abs=1e-6)


def test_uint16():
    leds = [(150.6, 220.1, 30000, 2.5), (500.2, 90.4, 70000, 3.0)]
    img = imagen(leds, fondo=500, ruido=20, dtype=np.uint16)
    fondo, blobs = detectar_blobs(img, min_sobre_fondo=2000)
    assert abs(fondo - 500) < 10
    assert len(blobs) == 2
    assert blobs[0]["pico"] == 65535 and blobs[0]["saturados"] > 0     # saturacion por defecto = 65535
    assert blobs[1]["saturados"] == 0
    assert abs(blobs[1]["centroide"][0] - 150.6) < 0.1
    assert abs(blobs[1]["centroide"][1] - 220.1) < 0.1


def test_imagen_vacia():
    fondo, blobs = detectar_blobs(imagen([]))
    assert blobs == []


def test_muchos_candidatos_limita():
    # Escena "ruidosa": ~1000 manchitas de 3x3 brillantes
    img = np.full((720, 1280), 10, dtype=np.uint8)
    img[5::20, 5::20] = 200
    img = cv2.dilate(img, np.ones((3, 3), np.uint8))
    _, blobs = detectar_blobs(img)
    assert 0 < len(blobs) <= 200


# ---------------------------------------------------------------------------
# Par, distancia, Z
# ---------------------------------------------------------------------------
def test_seleccionar_par_horizontal_y_vertical():
    a, b, c = blob(400, 100, pico=250), blob(100, 110, pico=240), blob(50, 50, pico=30)
    par = seleccionar_par([a, b, c])
    assert par == [b, a]                                  # izquierda -> derecha
    v1, v2 = blob(100, 300, pico=250), blob(105, 50, pico=200)
    assert seleccionar_par([v1, v2]) == [v2, v1]          # arriba -> abajo
    assert seleccionar_par([a]) == [a]
    assert seleccionar_par([]) == []


def test_distancia_y_z():
    a, b = blob(100, 100), blob(130, 140)
    assert distancia(a, b) == pytest.approx(50.0)
    assert z_estimada_mm(blob(0, 0), blob(50, 0), 500, 500, 50) == pytest.approx(500.0)
    assert z_estimada_mm(a, b, 500, 500, 50) == pytest.approx(500.0)
    assert z_estimada_mm(a, b, None, None, 50) is None
    assert z_estimada_mm(a, b, 0, 500, 50) is None
    assert z_estimada_mm(a, a, 500, 500, 50) is None


# ---------------------------------------------------------------------------
# Estadística
# ---------------------------------------------------------------------------
def test_estadistica_par():
    e = EstadisticaPar(ventana=10, fx=500, fy=500, sep_mm=50)
    for i in range(4):
        e.agregar([blob(100, 100), blob(150, 100)])
    assert e.resumen() is None
    for i in range(20):
        d = 0.5 if i % 2 else -0.5
        e.agregar([blob(100 + d, 100, pico=200, sat=2), blob(150, 100 + d, pico=100)])
    s = e.resumen()
    assert s["n"] == 10
    assert s["A"]["cx"] == pytest.approx(100) and s["A"]["std_x"] == pytest.approx(0.5)
    assert s["A"]["std_y"] == pytest.approx(0)
    assert s["B"]["cy"] == pytest.approx(100) and s["B"]["std_y"] == pytest.approx(0.5)
    assert s["A"]["pico"] == pytest.approx(200) and s["A"]["sat"] == pytest.approx(2)
    assert set(s["A"]) == {"cx", "cy", "std_x", "std_y", "pico", "area", "sat"}
    assert s["dist"] == pytest.approx(50, abs=0.05)
    assert s["z"] == pytest.approx(500, rel=1e-3)
    e.reiniciar()
    assert e.resumen() is None


def test_estadistica_par_sin_intrinsecos():
    e = EstadisticaPar()
    for _ in range(6):
        e.agregar([blob(0, 0), blob(10, 0)])
    s = e.resumen()
    assert math.isnan(s["z"])
    assert s["dist"] == pytest.approx(10)


def test_estadistica_difusor_y_corrimiento():
    e = EstadisticaDifusor(ventana=60)
    for i in range(4):
        e.agregar(blob(10, 20))
    assert e.resumen() is None
    e.agregar(blob(10, 20, suma=2000.0, elong=1.5, sat=5))
    s = e.resumen()
    assert set(s) == {"n", "cx", "cy", "std_x", "std_y", "pico", "flujo", "area", "elong", "sat"}
    assert s["n"] == 5 and s["cx"] == pytest.approx(10) and s["cy"] == pytest.approx(20)
    assert s["flujo"] == pytest.approx(1200) and s["elong"] == pytest.approx(1.1) and s["sat"] == pytest.approx(1)
    dx, dy, tot = corrimiento(s, (7.0, 16.0))
    assert (dx, dy, tot) == pytest.approx((3.0, 4.0, 5.0))
    assert corrimiento(s, None) is None
    e.reiniciar()
    assert e.resumen() is None
