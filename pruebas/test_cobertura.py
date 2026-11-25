"""Modo «llenar todo el local» (cobertura total): racks repartidos por todo el local hasta el % de área útil pedido."""

import copy

import pytest

from conftest import catalogo_sintetico, resumen_sintetico
from modulos import diseno_racks as dr
from modulos.cargar_local import local_vacio, preferencias_de
from modulos.interpretar_local import huella_estante, parametros_geometria_por_defecto, se_cruzan
from modulos.modelo_optimo import optimizar_diseno

PORCENTAJE = 0.4


def local_grande():
    local = local_vacio()
    local.update(nombre="prueba 20 × 14", largo_m=20.0, ancho_m=14.0, altura_libre_m=3.0)
    local["obstaculos"] = [{"id": "C1", "tipo": "columna", "x_m": 10.0, "y_m": 7.0, "largo_m": 0.4, "ancho_m": 0.4, "alto_m": 3.0},
                           {"id": "P1", "tipo": "puerta", "x_m": 4.0, "y_m": 0.0, "largo_m": 1.2, "ancho_m": 0.2, "alto_m": 2.2},
                           {"id": "S1", "tipo": "salida_emergencia", "x_m": 19.8, "y_m": 6.0, "largo_m": 0.2, "ancho_m": 1.2,
                            "alto_m": 2.2},
                           {"id": "X1", "tipo": "extintor", "x_m": 0.0, "y_m": 7.0, "largo_m": 0.3, "ancho_m": 0.3, "alto_m": 1.5}]
    local["zonas"] = [{"id": "Z1", "tipo": "despacho", "x_m": 0.0, "y_m": 0.0, "largo_m": 2.0, "ancho_m": 1.5}]
    local["pasillos"] = [{"uso": "peatonal", "ancho_min_m": 0.9}]
    local["equipos"] = [{"tipo": "manual", "radio_giro_m": 0, "altura_max_m": 1.9}]
    return local


def _area(e):
    x0, y0, x1, y1 = huella_estante(e)
    return (x1 - x0) * (y1 - y0)


@pytest.fixture(scope="module")
def casos():
    catalogo = catalogo_sintetico([{"producto": f"P{k}", "largo_cm": 10, "ancho_cm": 8, "alto_cm": 12, "peso_kg": 0.3}
                                   for k in range(8)])
    resumen = resumen_sintetico(catalogo, [round(1.5 - 0.1 * k, 2) for k in range(8)])
    normal = local_grande()
    normal["preferencias"] = dict(preferencias_de(normal), cobertura_total=False)
    parametros = parametros_geometria_por_defecto(normal)
    lleno = copy.deepcopy(normal)
    lleno["preferencias"] = dict(preferencias_de(lleno), cobertura_total=True, cobertura_porcentaje=PORCENTAJE)
    sol_normal = optimizar_diseno(catalogo, resumen, normal, parametros, [], None, "almacen", rapido=True)
    sol_lleno = optimizar_diseno(catalogo, resumen, lleno, parametros, [], None, "almacen", rapido=True)
    return {"local": normal, "parametros": parametros, "normal": sol_normal, "lleno": sol_lleno}


def test_desactivada_elige_pocos_modulos(casos):
    assert not casos["normal"]["cobertura"]["activa"]
    assert casos["normal"]["modulos_nuevos"] <= 3
    assert not casos["normal"]["modulos_vacios"]


def test_area_cubierta_cerca_del_porcentaje(casos):
    sol = casos["lleno"]
    area_util = dr.area_util(casos["local"], casos["parametros"])
    cubierta = sum(_area(e) for e in sol["local"]["estantes"])
    assert abs(cubierta / area_util - PORCENTAJE) <= 0.10
    assert sol["modulos_nuevos"] > casos["normal"]["modulos_nuevos"]
    assert sol["modulos_vacios"]
    assert len(sol["lista_compra"]) and int(sol["lista_compra"]["cantidad"].sum()) == sol["modulos_nuevos"]


def test_racks_repartidos_por_el_local(casos):
    estantes = casos["lleno"]["local"]["estantes"]
    huellas = [huella_estante(e) for e in estantes]
    x0, y0 = min(h[0] for h in huellas), min(h[1] for h in huellas)
    x1, y1 = max(h[2] for h in huellas), max(h[3] for h in huellas)
    assert (x1 - x0) * (y1 - y0) > 0.25 * 20.0 * 14.0


def test_sin_choques_ni_pasillos_menores(casos):
    local, parametros = casos["lleno"]["local"], casos["parametros"]
    base = copy.deepcopy(casos["local"])
    prohibidas = dr.zonas_prohibidas(base, parametros)
    requerido = prohibidas["requerido"]
    estantes = local["estantes"]
    for e in estantes:
        h = huella_estante(e)
        assert h[0] >= -1e-6 and h[1] >= -1e-6 and h[2] <= 20.0 + 1e-6 and h[3] <= 14.0 + 1e-6
        assert not any(se_cruzan(h, z) for z in prohibidas["huella"]), e["id"]
    for a in estantes:
        _, pasillo = dr._huella_y_pasillo(a["x_m"], a["y_m"], a["largo_m"], a["fondo_m"], a["orientacion"], requerido - 0.01)
        for b in estantes:
            if b is a:
                continue
            hb = huella_estante(b)
            assert not se_cruzan(huella_estante(a), hb), (a["id"], b["id"])
            assert not se_cruzan(pasillo, hb), (a["id"], b["id"])


def test_modelo_completo_conserva_racks_vacios(casos):
    catalogo = catalogo_sintetico([{"producto": f"P{k}", "largo_cm": 10, "ancho_cm": 8, "alto_cm": 12, "peso_kg": 0.3}
                                   for k in range(8)])
    resumen = resumen_sintetico(catalogo, [round(1.5 - 0.1 * k, 2) for k in range(8)])
    lleno = copy.deepcopy(casos["local"])
    lleno["preferencias"] = dict(preferencias_de(lleno), cobertura_total=True, cobertura_porcentaje=PORCENTAJE)
    sol = optimizar_diseno(catalogo, resumen, lleno, casos["parametros"], [], None, "almacen", tiempo_limite=20)
    assert sol["cobertura"]["activa"] and sol["modulos_vacios"]
    vacios = [e for e in sol["local"]["estantes"] if e.get("vacio")]
    assert len(vacios) == len(sol["modulos_vacios"])
    assert int(sol["ubicaciones"]["ubicado"].sum()) == len(catalogo)
    assert "capacidad disponible" in set(sol["tabla_diseno"]["estado"])


def local_34x15():
    local = local_vacio()
    local.update(nombre="tienda 34 × 15", largo_m=34.0, ancho_m=15.0, altura_libre_m=3.2)
    local["obstaculos"] = [{"id": "P1", "tipo": "puerta", "x_m": 15.0, "y_m": 0.0, "largo_m": 2.0, "ancho_m": 0.2, "alto_m": 2.4},
                           {"id": "S1", "tipo": "salida_emergencia", "x_m": 33.8, "y_m": 7.0, "largo_m": 0.2, "ancho_m": 1.2,
                            "alto_m": 2.2},
                           {"id": "C1", "tipo": "columna", "x_m": 11.0, "y_m": 7.3, "largo_m": 0.4, "ancho_m": 0.4, "alto_m": 3.2},
                           {"id": "C2", "tipo": "columna", "x_m": 22.0, "y_m": 7.3, "largo_m": 0.4, "ancho_m": 0.4, "alto_m": 3.2}]
    local["zonas"] = [{"id": "Z1", "tipo": "ingreso", "x_m": 15.0, "y_m": 0.0, "largo_m": 2.0, "ancho_m": 1.2},
                      {"id": "Z2", "tipo": "caja", "x_m": 18.5, "y_m": 0.3, "largo_m": 2.5, "ancho_m": 1.2},
                      {"id": "Z3", "tipo": "despacho", "x_m": 0.3, "y_m": 0.3, "largo_m": 2.5, "ancho_m": 1.5}]
    local["pasillos"] = [{"uso": "peatonal", "ancho_min_m": 0.9}]
    local["equipos"] = [{"tipo": "manual", "radio_giro_m": 0, "altura_max_m": 1.9}]
    return local


def test_tienda_34x15_racks_en_todo_el_local_y_entrada_libre():
    from modulos.comun import cargar_ajustes
    from modulos.interpretar_local import ampliar, rect
    catalogo = catalogo_sintetico([{"producto": f"P{k}", "largo_cm": 10, "ancho_cm": 8, "alto_cm": 12, "peso_kg": 0.3}
                                   for k in range(10)])
    resumen = resumen_sintetico(catalogo, [round(1.5 - 0.1 * k, 2) for k in range(10)])
    local = local_34x15()  # preferencias por defecto: cobertura activa
    parametros = parametros_geometria_por_defecto(local)
    sol = optimizar_diseno(catalogo, resumen, local, parametros, [], None, "tienda", rapido=True)
    estantes = sol["local"]["estantes"]
    assert estantes
    cuadrantes = set()
    for e in estantes:
        x0, y0, x1, y1 = huella_estante(e)
        cuadrantes.add((((x0 + x1) / 2) >= 17.0, ((y0 + y1) / 2) >= 7.5))
    assert len(cuadrantes) >= 3, cuadrantes
    despeje = cargar_ajustes()["diseno"]["despeje_ingreso_m"]
    entradas = [ampliar(rect(z["x_m"], z["y_m"], z["largo_m"], z["ancho_m"]), despeje) for z in local["zonas"]
                if z["tipo"] in ("ingreso", "caja")]
    for e in estantes:
        assert not any(se_cruzan(huella_estante(e), z) for z in entradas), e["id"]
    assert sol["cobertura"]["fraccion_lograda"] > 0.3
