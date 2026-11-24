"""Versión 3: diseño de racks (z[m]), modos A/B/C, costeo, evidencia estadística y paquete del artículo."""

import copy
import io
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from openpyxl import load_workbook

from conftest import catalogo_sintetico, resumen_sintetico
from modulos import plantillas
from modulos.cargar_local import leer_plantilla_local, local_de_ejemplo, local_vacio
from modulos.costeo import calcular, informe_word, tabla_inicial, tir_anual
from modulos.diseno_racks import cargar_catalogo_racks, generar_candidatos, tipos_utilizables
from modulos.evidencia import analizar, contraste, validacion_tecnica, veredicto
from modulos.indicadores import linea_base_alfabetica, validar_solucion
from modulos.interpretar_local import (PREGUNTAS_CONFIRMACION_LOCAL, ampliar, hay_errores_graves, parametros_geometria_por_defecto,
                                       puede_confirmar_local, se_cruzan, validar_local)
from modulos.modelo_optimo import optimizar_diseno, resolver


def local_10x8():
    local = local_vacio()
    local.update(nombre="prueba 10 × 8", largo_m=10.0, ancho_m=8.0, altura_libre_m=3.0)
    local["obstaculos"] = [{"id": "C1", "tipo": "columna", "x_m": 5.0, "y_m": 4.0, "largo_m": 0.4, "ancho_m": 0.4, "alto_m": 3.0},
                           {"id": "P1", "tipo": "puerta", "x_m": 4.0, "y_m": 0.0, "largo_m": 1.2, "ancho_m": 0.2, "alto_m": 2.2},
                           {"id": "S1", "tipo": "salida_emergencia", "x_m": 9.8, "y_m": 3.0, "largo_m": 0.2, "ancho_m": 1.2, "alto_m": 2.2}]
    local["zonas"] = [{"id": "Z1", "tipo": "despacho", "x_m": 0.0, "y_m": 0.0, "largo_m": 2.0, "ancho_m": 1.5}]
    local["pasillos"] = [{"uso": "peatonal", "ancho_min_m": 0.9}]
    local["equipos"] = [{"tipo": "manual", "radio_giro_m": 0, "altura_max_m": 1.9}]
    return local


def ventas_sinteticas(catalogo, pedidos=300, semilla=3):
    rng = np.random.default_rng(semilla)
    ids = catalogo["id_producto"].tolist()
    probabilidad = np.linspace(1, 0.05, len(ids))
    probabilidad /= probabilidad.sum()
    filas = []
    for k in range(pedidos):
        for pid in rng.choice(ids, int(rng.integers(1, 4)), replace=False, p=probabilidad):
            filas.append({"comprobante": f"B{k:04d}", "id_producto": pid, "cantidad": 1.0, "total": 8.0,
                          "fecha_hora": pd.Timestamp("2026-01-01") + pd.Timedelta(days=k % 60)})
    return pd.DataFrame(filas)


@pytest.fixture(scope="module")
def caso():
    catalogo = catalogo_sintetico([{"producto": f"P{k}", "largo_cm": 8 + k % 4, "ancho_cm": 8, "alto_cm": 15, "peso_kg": 0.4}
                                   for k in range(24)])
    resumen = resumen_sintetico(catalogo, [round(2.0 - 0.08 * k, 2) for k in range(24)])
    local = local_10x8()
    parametros = parametros_geometria_por_defecto(local)
    solucion = optimizar_diseno(catalogo, resumen, local, parametros, [], None, "almacen", tiempo_limite=20)
    antes = linea_base_alfabetica(solucion["productos"], solucion["pares"], solucion["validas"], solucion["local"])
    return {"catalogo": catalogo, "resumen": resumen, "local": local, "parametros": parametros, "solucion": solucion,
            "antes": antes, "ventas": ventas_sinteticas(catalogo)}


# --------------------------------------------------------------------------------------
# Fase 2. Entradas
# --------------------------------------------------------------------------------------

def test_local_sin_estantes_se_confirma():
    local = local_10x8()
    avisos = validar_local(local)
    assert not hay_errores_graves(avisos), avisos
    assert puede_confirmar_local([True] * len(PREGUNTAS_CONFIRMACION_LOCAL), avisos, "Ana")[0]
    leido, validacion = leer_plantilla_local(plantillas.generar_plantilla_local(local))
    assert not validacion["errores"] and leido["estantes"] == [] and leido["preferencias"]["modo_diseno"] == "A"


def test_plantilla_local_vieja_se_rechaza_con_guia_de_migracion():
    libro = load_workbook(io.BytesIO(plantillas.generar_plantilla_local()))
    libro["INSTRUCCIONES"]["B2"] = "2.0"
    salida = io.BytesIO()
    libro.save(salida)
    resultado = plantillas.validar_plantilla(salida.getvalue(), "local")
    assert "versión antigua" in resultado["rechazada"] and "ESTANTES_EXISTENTES" in resultado["rechazada"]


def test_hojas_opcionales_pueden_faltar():
    libro = load_workbook(io.BytesIO(plantillas.generar_plantilla_local(local_10x8())))
    del libro["ESTANTES_EXISTENTES"]
    salida = io.BytesIO()
    libro.save(salida)
    local, validacion = leer_plantilla_local(salida.getvalue())
    assert local is not None and not validacion["errores"]


# --------------------------------------------------------------------------------------
# Fase 3. Catálogo de racks y candidatos
# --------------------------------------------------------------------------------------

def test_candidatos_no_cruzan_columna_ni_puerta_ni_dejan_pasillo_angosto():
    local = local_10x8()
    parametros = parametros_geometria_por_defecto(local)
    tipos, _ = tipos_utilizables(cargar_catalogo_racks(), local, parametros)
    candidatos, conflictos, info = generar_candidatos(local, parametros, tipos)
    assert len(candidatos) > 50 and len(conflictos) > 0
    columna = (5.0, 4.0, 5.4, 4.4)
    puerta = ampliar((4.0, 0.0, 5.2, 0.2), 1.0)
    for r in candidatos.itertuples():
        huella, pasillo = (r.x0, r.y0, r.x1, r.y1), (r.ax0, r.ay0, r.ax1, r.ay1)
        assert not se_cruzan(huella, columna) and not se_cruzan(huella, puerta)
        assert not se_cruzan(pasillo, columna)
        assert min(r.ax1 - r.ax0, r.ay1 - r.ay0) >= info["requerido_m"] - 1e-6  # el pasillo tiene el ancho mínimo
        assert pasillo[0] >= -0.01 and pasillo[1] >= -0.01 and pasillo[2] <= 10.01 and pasillo[3] <= 8.01


def test_tipo_mas_alto_que_la_altura_libre_se_ajusta():
    local = dict(local_10x8(), altura_libre_m=1.9)
    parametros = parametros_geometria_por_defecto(local)
    tipos, avisos = tipos_utilizables(cargar_catalogo_racks(), local, parametros)
    assert all(t["alto_m"] <= 1.9 - 0.3 + 1e-6 for t in tipos)
    assert any("altura disponible" in a for a in avisos)


# --------------------------------------------------------------------------------------
# Fase 4. Modelo ampliado con z[m]
# --------------------------------------------------------------------------------------

def _caso_a_mano():
    """Dos módulos: A (cerca) con posiciones 0 y 1, B (lejos) con 2 y 3. Dos productos de 0.8 m: cada uno necesita su posición."""
    validas = pd.DataFrame({"ancho_m": [1.0] * 4, "fondo_m": [0.5] * 4, "alto_libre_m": [0.4] * 4, "estante": ["A", "A", "B", "B"],
                            "nivel": [1, 2, 1, 2], "capacidad_kg_nivel": [100.0] * 4, "modulo": ["A", "A", "B", "B"]})
    pares = pd.DataFrame({"i": [0, 0, 0, 0, 1, 1, 1, 1], "j": [0, 1, 2, 3] * 2, "cubre": [(0,), (1,), (2,), (3,)] * 2,
                          "ancho_ocupado_m": [0.8] * 8, "volumen_m3": [0.01] * 8, "peso_kg": [1.0] * 8,
                          "coef": [1.0, 1.0, 3.0, 3.0, 2.0, 2.0, 4.0, 4.0]})
    productos = pd.DataFrame({"id_producto": ["p0", "p1"], "producto": ["P0", "P1"], "prioridad": [1.0, 0.5],
                              "categoria_modelo": ["SIN CATEGORÍA"] * 2, "m_rotacion": [2.0, 1.0], "margen_diario": [1.0, 1.0],
                              "ventas_soles": [10.0, 5.0], "m_largo": [80.0] * 2, "m_ancho": [10.0] * 2, "m_alto": [10.0] * 2})
    pesos = {"peso_distancia": 1, "peso_ergonomia": 0, "peso_agrupar_categoria": 0, "peso_pares_comprobante": 0, "peso_reglas_blandas": 0}
    return validas, pares, productos, pesos


def _modulos(validas, inversion, anual, conflictos=(), presupuesto=None, fijos=()):
    return {"modulo_de": validas["modulo"].to_numpy(), "costo_inversion": inversion, "peso_inversion": anual,
            "fijos": set(fijos), "conflictos": list(conflictos), "presupuesto": presupuesto, "inicial": set()}


def test_modelo_pequeno_con_z_coincide_con_el_calculo_a_mano():
    validas, pares, productos, pesos = _caso_a_mano()
    # A mano: ambos en A → 1 + 2 + costo(A)=1 → 4; con B: 3 + 4 + 1 = 8; mezclar cuesta 1 + 4 + 2 = 7 → óptimo: todo en A
    s = resolver(productos, pares, validas, {}, [], pesos=pesos, tiempo_limite=10,
                 modulos=_modulos(validas, {"A": 10, "B": 10}, {"A": 1.0, "B": 1.0}), inicial={})
    assert s["estado"] == "Óptimo" and s["modulos_instalados"] == {"A"}
    assert {validas.at[j, "modulo"] for j in s["asignacion"].values()} == {"A"} and len(s["asignacion"]) == 2
    assert abs(s["objetivo"] - 3.0) < 1e-6


def test_lambda_presupuesto_y_conflictos_cambian_la_eleccion():
    validas, pares, productos, pesos = _caso_a_mano()
    # λ alto en A: A cuesta 100 → con A: 3 + 100; con B: 7 + 0.1 → se instala B
    s = resolver(productos, pares, validas, {}, [], pesos=pesos, tiempo_limite=10,
                 modulos=_modulos(validas, {"A": 10, "B": 10}, {"A": 100.0, "B": 0.1}), inicial={})
    assert s["modulos_instalados"] == {"B"}
    # Presupuesto: A cuesta S/ 10 y B S/ 0.4; con tope S/ 5 solo cabe B
    s = resolver(productos, pares, validas, {}, [], pesos=pesos, tiempo_limite=10,
                 modulos=_modulos(validas, {"A": 10, "B": 0.4}, {"A": 1.0, "B": 1.0}, presupuesto=5), inicial={})
    assert s["modulos_instalados"] == {"B"}
    # Conflicto + módulo fijo (modo B/C): B existente fijo y en conflicto con A → nunca se instala A
    s = resolver(productos, pares, validas, {}, [], pesos=pesos, tiempo_limite=10,
                 modulos=_modulos(validas, {"A": 10, "B": 0}, {"A": 1.0, "B": 0.0}, conflictos=[("A", "B")], fijos=["B"]),
                 inicial={})
    assert s["modulos_instalados"] == {"B"}


def test_modos_a_b_c_y_validador(ejemplo):
    catalogo = catalogo_sintetico([{"producto": f"P{k}", "largo_cm": 10, "ancho_cm": 10, "alto_cm": 20, "peso_kg": 0.5}
                                   for k in range(30)])
    resumen = resumen_sintetico(catalogo, [round(2 - 0.05 * k, 2) for k in range(30)])
    resultados = {}
    for modo_diseno in "ABC":
        local = copy.deepcopy(ejemplo)
        local["preferencias"]["modo_diseno"] = modo_diseno
        parametros = parametros_geometria_por_defecto(local)
        s = optimizar_diseno(catalogo, resumen, local, parametros, [], None, "almacen", tiempo_limite=15)
        validacion = validar_solucion(s["asignacion"], s["productos"], s["validas"], s["local"], s["pares"], parametros, [])
        assert not validacion["duros"], validacion["duros"][:3]
        assert len(s["asignacion"]) == 30
        resultados[modo_diseno] = s
    assert resultados["A"]["modulos_nuevos"] > 0 and resultados["A"]["modulos_existentes"] == 0
    assert resultados["B"]["modulos_nuevos"] == 0 and len(resultados["B"]["lista_compra"]) == 0  # en B nunca se compran racks
    assert resultados["C"]["modulos_existentes"] == len(ejemplo["estantes"])


def test_sin_presupuesto_suficiente_explica_y_propone_alternativas(caso):
    local = copy.deepcopy(caso["local"])
    local["preferencias"]["presupuesto_max_soles"] = 300.0  # alcanza para un solo módulo
    s = optimizar_diseno(caso["catalogo"], caso["resumen"], local, caso["parametros"], [], None, "almacen", rapido=True)
    assert s["inversion_racks"] <= 300.0
    assert s["faltante"] is not None and s["alternativas"]
    assert any("presupuesto" in a["alternativa"].lower() for a in s["alternativas"])


def test_lista_de_compra_rotula_precios_supuestos(caso):
    compra = caso["solucion"]["lista_compra"]
    assert len(compra) and (compra["nota"] == "valores típicos, confirmar con el proveedor").all()
    assert compra["cantidad"].sum() == caso["solucion"]["modulos_nuevos"]


# --------------------------------------------------------------------------------------
# Fase 5. Costeo y exportación
# --------------------------------------------------------------------------------------

def test_costeo_recalcula_rapido_y_calcula_tir(caso, tmp_path):
    tabla = tabla_inicial(caso["solucion"]["lista_compra"], 20)
    inicio = time.perf_counter()
    resultado = calcular(tabla, 150.0, 0.12, 24)
    assert (time.perf_counter() - inicio) < 0.3
    tabla.loc[0, "precio_unitario"] = 9999.0
    editado = calcular(tabla, 150.0, 0.12, 24)
    assert editado["inversion"] > resultado["inversion"]
    tir = tir_anual(1000, 100, 12)
    assert abs((1 + tir) ** (1 / 12) - 1 - 0.0292) < 0.001  # TIR mensual conocida ≈ 2.92 %
    datos = {"economia": editado, "problema": "p", "solucion": "s", "riesgos": "r", "normativo": "n", "supuestos": "su",
             "recomendacion": "rec", "empresa": "Prueba"}
    ruta = informe_word(datos, {"Costeo": tabla}, ruta=tmp_path / "informe.docx")
    from docx import Document
    texto = "\n".join(p.text for p in Document(ruta).paragraphs)
    assert f"S/ {editado['inversion']:,.2f}" in texto and "confirmar con el proveedor" in texto


# --------------------------------------------------------------------------------------
# Fase 6. Evidencia
# --------------------------------------------------------------------------------------

def test_contraste_detecta_una_reduccion_conocida():
    rng = np.random.default_rng(0)
    antes = rng.uniform(10, 30, 400)
    despues = antes * 0.8 + rng.normal(0, 0.5, 400)
    prueba = contraste(antes, despues, semilla=1)
    assert prueba["valor_p"] < 1e-6 and 17 < prueba["reduccion_pct"] < 23
    assert prueba["ic95_pct"][0] < prueba["reduccion_pct"] < prueba["ic95_pct"][1]
    igual = contraste(antes, antes, semilla=1)
    assert igual["valor_p"] == 1.0


def test_evidencia_reproducible_con_la_misma_semilla(caso):
    a = analizar(caso["solucion"], caso["antes"], caso["ventas"], 500, replicas=5)
    b = analizar(caso["solucion"], caso["antes"], caso["ventas"], 500, replicas=5)
    assert np.array_equal(a["diferencias"], b["diferencias"]) and np.array_equal(a["replicas"], b["replicas"])
    assert a["contraste"]["valor_p"] == b["contraste"]["valor_p"]
    assert a["info_pedidos"]["pedidos_totales"] == 300
    assert len(a["escenarios"]) == 4  # antes, réplicas, heurística, propuesta


def test_veredicto_cambia_con_los_umbrales():
    datos = {"reduccion_pct": 18.0, "valor_p": 0.001, "duros": 0, "ubicados": 10, "total_productos": 10, "no_cumple": 0,
             "por_verificar": 0, "confiabilidad": 80.0, "recuperacion_meses": 10.0}
    umbrales = {"reduccion_distancia_pct": 15, "valor_p": 0.05, "confiabilidad_pct": 70, "recuperacion_max_meses": 24}
    _, _, estado = veredicto(datos, umbrales)
    assert estado == "verde"
    _, texto, estado = veredicto(datos, dict(umbrales, reduccion_distancia_pct=40))
    assert estado == "rojo" and "Reducción" in texto
    _, _, estado = veredicto(dict(datos, confiabilidad=55), umbrales)
    assert estado == "amarillo"


def test_validacion_tecnica_de_totales():
    union = {"soles_dentro": 100.0, "soles_fuera": 50.0, "lineas_dentro": 10, "lineas_fuera": 5}
    ok = validacion_tecnica({"duros": [], "blandos": []}, union, 150.0, 15, True)
    assert (ok["Resultado"] == "pasa").all()
    mal = validacion_tecnica({"duros": ["x"], "blandos": []}, union, 151.0, 15, False)
    assert (mal["Resultado"] == "falla").all()


# --------------------------------------------------------------------------------------
# Fase 7. Paquete del artículo
# --------------------------------------------------------------------------------------

def test_paquete_del_articulo(caso, tmp_path):
    from modulos.articulo import generar_paquete
    from modulos.comun import cargar_ajustes
    from modulos.evidencia import diagnostico, limites_evidencia
    from modulos.normas import estado_inicial
    solucion = caso["solucion"]
    analisis = analizar(solucion, caso["antes"], caso["ventas"], 500, replicas=5)
    economia = calcular(tabla_inicial(solucion["lista_compra"], 10), 120.0, 0.12, 24)
    union = {"lineas_totales": 900, "lineas_dentro": 700, "lineas_fuera": 200, "soles_dentro": 5000.0, "soles_fuera": 900.0,
             "productos_con_ventas": 24, "fecha_min": pd.Timestamp("2026-01-01"), "fecha_max": pd.Timestamp("2026-03-01"),
             "dias_periodo": 60}
    resumen = caso["resumen"].assign(acumulado=lambda t: t["ventas_soles"].cumsum() / t["ventas_soles"].sum())
    confiabilidad = {"indice": 100.0, "medidas_reales": 100.0}
    contexto = {"union": union, "calidad": {"productos": 24, "con_medida_real": 24}, "confiabilidad": confiabilidad,
                "evidencia": analisis, "resumen": resumen, "local_base": caso["local"], "modo_diseno": "A", "pasillo_m": 0.9,
                "presupuesto": None, "lambda": 0.5, "ajustes": cargar_ajustes(), "parametros": caso["parametros"],
                "lista_compra": solucion["lista_compra"], "sensibilidad": None, "economia": economia,
                "reporte_normativo": pd.DataFrame([{"Norma": "N1", "Resultado de la propuesta": "cumple"}]), "solucion": solucion,
                "antes": caso["antes"], "nombre_antes": "Antes (alfabético por categoría)",
                "umbrales": cargar_ajustes()["evidencia"]["umbrales"], "empresa": "Prueba S.A.C.",
                "diagnostico": diagnostico(analisis, solucion, caso["antes"], None), "problema_usuario": "",
                "veredicto_texto": "Texto del veredicto.", "normas": estado_inicial("bazar"),
                "limites": limites_evidencia(confiabilidad, union, False, 8, analisis["info_pedidos"])}
    resumen_paquete = generar_paquete(contexto, tmp_path / "articulo")
    assert resumen_paquete["tablas"] == 9 and resumen_paquete["figuras"] == 8
    carpeta = tmp_path / "articulo"
    for archivo in ("tablas_articulo.xlsx", "tablas_articulo.docx", "resultados_para_redactar.md", "ficha_metodologica.md",
                    "normas_y_fuentes.md", "LEEME_articulo.md"):
        assert (carpeta / archivo).exists(), archivo
    assert len(list((carpeta / "figuras").glob("figura_*.png"))) == 8 and len(list((carpeta / "figuras").glob("figura_*.html"))) == 8
    # Las cifras del texto coinciden con la Tabla 6
    texto = (carpeta / "resultados_para_redactar.md").read_text(encoding="utf-8")
    tabla6 = pd.read_excel(carpeta / "tablas_articulo.xlsx", sheet_name="Tabla 6", skiprows=3)
    reduccion = tabla6.loc[tabla6["Elemento"] == "Reducción media (%)", "Resultado"].iloc[0]
    assert f"({reduccion} %" in texto
    assert f"S/ {economia['inversion']:,.2f}" in texto
    # No se inventan referencias bibliográficas
    fuentes = (carpeta / "normas_y_fuentes.md").read_text(encoding="utf-8")
    assert "et al." not in fuentes and "no sugiere libros" in fuentes
    # Borrador del artículo en Word y decisión en una página
    from docx import Document
    from modulos.articulo import decision
    assert (carpeta / "BORRADOR_articulo.docx").exists() and (carpeta / "DECISION.md").exists()
    borrador = "\n".join(p.text for p in Document(carpeta / "BORRADOR_articulo.docx").paragraphs)
    for seccion in ("Resumen", "1. Introducción", "2. Metodología", "3. Resultados", "4. Discusión", "5. Conclusiones"):
        assert seccion in borrador, seccion
    assert "[COMPLETAR" in borrador and f"{analisis['contraste']['media_antes_m']:.1f} m" in borrador
    d = decision(contexto)
    assert d["color"] in ("verde", "amarillo", "rojo") and d["accion"] in borrador


def test_decision_es_clara_segun_los_datos():
    from modulos.articulo import decision
    umbrales = {"reduccion_distancia_pct": 15, "valor_p": 0.05, "confiabilidad_pct": 70, "recuperacion_max_meses": 24}

    def caso(reduccion, valor_p, inversion, meses):
        contraste = {"reduccion_pct": reduccion, "valor_p": valor_p, "media_antes_m": 50.0, "media_despues_m": 50 * (1 - reduccion / 100)}
        return decision({"evidencia": {"contraste": contraste}, "umbrales": umbrales,
                         "economia": {"inversion": inversion, "recuperacion_meses": meses, "ahorro_mensual": 300.0}})
    assert caso(30, 0.001, 2000, 8)["color"] == "verde"
    assert caso(30, 0.001, 0, None)["color"] == "verde"
    assert caso(4, 0.001, 9000, None)["accion"].startswith("NO compre")
    assert caso(8, 0.001, 500, 3)["color"] == "amarillo"
    assert caso(2, 0.40, 500, 3)["accion"].startswith("NO cambie")


def test_el_progreso_sobrevive_a_recargar_la_pagina(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest
    from modulos import persistencia
    monkeypatch.setattr(persistencia, "CARPETA_PROYECTOS", tmp_path)
    app = str(Path(__file__).resolve().parent.parent / "app.py")
    primera = AppTest.from_file(app, default_timeout=120)
    primera.run()
    codigo = primera.query_params["p"]
    codigo = codigo[0] if isinstance(codigo, list) else codigo
    primera.session_state["responsable"] = "Ana Prueba"
    primera.session_state["paso_guardado_prueba"] = 3
    primera.run()
    # "Recargar la página" = una sesión nueva con el mismo enlace
    segunda = AppTest.from_file(app, default_timeout=120)
    segunda.query_params["p"] = codigo
    segunda.run()
    assert segunda.session_state["paso_guardado_prueba"] == 3
    assert segunda.session_state["responsable"] == "Ana Prueba"
    # Versión local: abrir sin código continúa el último proyecto
    tercera = AppTest.from_file(app, default_timeout=120)
    tercera.run()
    assert not tercera.exception
    assert tercera.session_state["paso_guardado_prueba"] == 3
