"""Datos de prueba compartidos."""

import sys
from pathlib import Path

import pandas as pd
import pytest

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from modulos.cargar_local import _estante, local_de_ejemplo, local_vacio  # noqa: E402
from modulos.medidas import completar_catalogo  # noqa: E402

CATALOGO_REAL = RAIZ / "datos_entrada" / "lista_de_productos_limpio.xlsx"
VENTAS_REAL = next(iter(sorted((RAIZ / "datos_entrada").glob("reporte_ventas_producto_*.xlsx"))), None)


def catalogo_sintetico(filas):
    """filas: lista de dicts con producto, categoria, largo_cm, ancho_cm, alto_cm, peso_kg (medidas reales)."""
    registros = []
    for numero, fila in enumerate(filas, start=1):
        registro = {"codigo_barras": f"77000000{numero:05d}", "sku": f"P{numero}", "producto": f"PRODUCTO {numero}",
                    "categoria": "HOGAR", "precio_compra": 5.0, "precio_venta": 8.0, "stock": 10, "fecha_vencimiento": None,
                    "unidades_por_caja": None, "largo_caja_cm": None, "ancho_caja_cm": None, "alto_caja_cm": None,
                    "apilable": "no", "maximo_apilado": 1, "se_puede_girar": "no", "fragil": "no", "perecible": "no",
                    "peligroso": "no", "valor_alto": "no", "temperatura_requerida": "ambiente", "ubicacion_actual": None,
                    "origen_categoria": "dato"}
        registro.update(fila)
        registro["id_producto"] = registro["codigo_barras"]
        registros.append(registro)
    return completar_catalogo(pd.DataFrame(registros), "bazar")


def resumen_sintetico(catalogo, rotaciones):
    tabla = catalogo[["id_producto", "producto", "categoria"]].copy()
    tabla["rotacion_diaria"] = rotaciones
    tabla["unidades"] = tabla["rotacion_diaria"] * 100
    tabla["ventas_soles"] = tabla["unidades"] * 8
    tabla["margen_unitario"] = 3.0
    tabla["margen_diario"] = tabla["rotacion_diaria"] * 3
    tabla["clase_abc"] = ["A" if r > 0 else "SIN ROTACIÓN" for r in rotaciones]
    tabla["participacion"] = tabla["ventas_soles"] / max(tabla["ventas_soles"].sum(), 1)
    tabla["dias_periodo"] = 100
    return tabla


def local_un_estante(niveles=3, largo=2.4, capacidad=200):
    """Local de 6 × 4 m con un solo estante de 4 tramos y `niveles` niveles (12 posiciones por defecto)."""
    local = local_vacio()
    local.update({"nombre": "prueba", "largo_m": 6.0, "ancho_m": 4.0, "altura_libre_m": 3.0, "fuente": "excel"})
    local["estantes"] = [_estante("E1", 1.0, 3.0, 0, largo=largo, fondo=0.5, alto=1.6, niveles=niveles, capacidad=capacidad,
                                  alturas=";".join(["0.45"] * niveles))]
    local["zonas"] = [{"id": "Z1", "tipo": "despacho", "x_m": 0.2, "y_m": 0.2, "largo_m": 1.0, "ancho_m": 1.0}]
    local["obstaculos"] = [{"id": "S1", "tipo": "salida_emergencia", "x_m": 5.8, "y_m": 0.5, "largo_m": 0.2, "ancho_m": 1.0, "alto_m": 2.1},
                           {"id": "X1", "tipo": "extintor", "x_m": 0.0, "y_m": 1.5, "largo_m": 0.2, "ancho_m": 0.2, "alto_m": 1.5}]
    local["equipos"] = [{"tipo": "manual", "radio_giro_m": 0, "altura_max_m": 1.9}]
    local["pasillos"] = [{"uso": "peatonal", "ancho_min_m": 0.9}]
    return local


@pytest.fixture
def ejemplo():
    return local_de_ejemplo()


@pytest.fixture(autouse=True)
def _proyectos_aislados(tmp_path, monkeypatch):
    """Cada prueba guarda sus proyectos en una carpeta temporal (la versión local reanuda el último proyecto)."""
    from modulos import guia, persistencia
    carpeta = tmp_path / "proyectos"
    carpeta.mkdir()
    monkeypatch.setattr(persistencia, "CARPETA_PROYECTOS", carpeta)
    monkeypatch.setattr(guia, "MARCA_BIENVENIDA", tmp_path / "bienvenida_vista.txt")
