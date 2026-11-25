"""EL modelo de optimización de Acomoda: asignación generalizada de productos a
posiciones de estante (programación lineal entera, PuLP + CBC).

Variables
  x[i,j] ∈ {0,1}  el producto i va en la posición j
  y[i]  ∈ [0,1]   el producto i no se pudo ubicar (holgura muy penalizada; es entera
                  en la práctica porque Σ x + y = 1 con x binaria)
  u[c,e] ∈ {0,1}  la categoría c usa el estante e (para incompatibilidades y para agrupar)
  s[p,e] ∈ [0,1]  los dos productos del par p (vendidos juntos) están en el estante e

Modo almacén: minimizar Σ rotación·costo_acceso·x  + penalizaciones
Modo tienda : maximizar Σ margen_esperado·exposición·x (se minimiza su negativo)
"""

import copy
import math
import os
import re
import shutil
import tempfile
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pulp

from modulos.comun import CARPETA_PROCESADOS, cargar_ajustes, cargar_perfiles
from modulos.interpretar_local import distancia_rects, huella_estante

EQUIPOS_CARGA = {"transpaleta", "apilador", "montacargas"}


# --------------------------------------------------------------------------------------
# 1. Datos de productos y posiciones
# --------------------------------------------------------------------------------------

def preparar_productos(catalogo, resumen, parametros, modo="almacen", ajustes=None):
    """Tabla de productos con lo que necesita el modelo (cantidad a ubicar, unidad de manejo, etc.)."""
    ajustes = ajustes or cargar_ajustes()
    tabla = catalogo.merge(resumen[["id_producto", "rotacion_diaria", "ventas_soles", "margen_unitario", "margen_diario",
                                    "clase_abc", "participacion"]], on="id_producto", how="left")
    tabla[["rotacion_diaria", "ventas_soles", "margen_unitario", "margen_diario", "participacion"]] = \
        tabla[["rotacion_diaria", "ventas_soles", "margen_unitario", "margen_diario", "participacion"]].fillna(0.0)
    tabla["clase_abc"] = tabla["clase_abc"].fillna("SIN ROTACIÓN")
    dias = parametros.get("dias_cobertura") or 0
    unidades = np.maximum(1, np.ceil(tabla["rotacion_diaria"] * dias)).astype(int) if dias else np.ones(len(tabla), dtype=int)
    tabla["stock_minimo"] = unidades
    # Unidad de manejo: en modo almacén se usa la caja del proveedor si tiene medidas reales
    def numero(columna, defecto):
        if columna not in tabla:
            return pd.Series(defecto, index=tabla.index, dtype=float)
        return pd.to_numeric(tabla[columna], errors="coerce").fillna(defecto)
    upc = numero("unidades_por_caja", 1).clip(lower=1)
    usa_caja = pd.Series(modo == "almacen", index=tabla.index) & upc.gt(1)
    for columna in ("largo_caja_cm", "ancho_caja_cm", "alto_caja_cm"):
        usa_caja &= numero(columna, 0).gt(0)
    tabla["usa_caja"] = usa_caja
    tabla["m_largo"] = np.where(usa_caja, numero("largo_caja_cm", 0), tabla["largo_cm"])
    tabla["m_ancho"] = np.where(usa_caja, numero("ancho_caja_cm", 0), tabla["ancho_cm"])
    tabla["m_alto"] = np.where(usa_caja, numero("alto_caja_cm", 0), tabla["alto_cm"])
    tabla["m_peso"] = np.where(usa_caja, tabla["peso_kg"] * upc, tabla["peso_kg"])
    tabla["m_cantidad"] = np.where(usa_caja, np.ceil(unidades / upc), unidades).astype(int)
    tabla["m_rotacion"] = np.where(usa_caja, tabla["rotacion_diaria"] / upc, tabla["rotacion_diaria"])
    tabla["m_apilado"] = np.where(tabla["apilable"].eq("si"), tabla["maximo_apilado"].clip(lower=1), 1).astype(int)
    tabla["categoria_modelo"] = tabla["categoria"].astype(str).str.upper()
    maximo = max(tabla["m_rotacion"].max(), 1e-9)
    maximo_margen = max(tabla["margen_diario"].max(), 1e-9)
    tabla["prioridad"] = 0.5 * tabla["m_rotacion"] / maximo + 0.5 * tabla["margen_diario"] / maximo_margen
    return tabla.reset_index(drop=True)


def _ergonomia(altura, ajustes):
    ergo = ajustes["ergonomia"]
    if altura < ergo["altura_cadera_m"]:
        return ergo["costo_piso"] * (ergo["altura_cadera_m"] - altura) / ergo["altura_cadera_m"]
    if altura > ergo["altura_hombros_m"]:
        return ergo["costo_sobre_hombros"] * min(1.0, (altura - ergo["altura_hombros_m"]) / 0.6)
    return 0.0


def _exposicion_altura(altura, factores):
    if 1.2 <= altura <= 1.65:
        return factores["altura_ojos"]
    if 0.75 <= altura < 1.2:
        return factores["altura_manos"]
    if altura < 0.75:
        return factores["bajo"]
    return factores["alto"]


def calcular_costos_posiciones(posiciones, pesos=None, perfil_id="bazar", ajustes=None):
    """Agrega costo_acceso (modo almacén) y factor_exposicion (modo tienda) a cada posición."""
    ajustes = ajustes or cargar_ajustes()
    pesos = pesos or ajustes["objetivo"]
    perfiles = cargar_perfiles()["perfiles"]
    factores = (perfiles.get(perfil_id) or perfiles["bazar"])["factores_exposicion"]
    tabla = posiciones.copy()
    distancia_max = max(tabla["distancia_m"].max(), 1e-6)
    ingreso_max = max(tabla["distancia_ingreso_m"].max(), 1e-6)
    tabla["costo_ergonomico"] = tabla["altura_centro_m"].map(lambda h: _ergonomia(h, ajustes))
    tabla["costo_acceso"] = (pesos["peso_distancia"] * tabla["distancia_m"] / distancia_max +
                             pesos["peso_ergonomia"] * tabla["costo_ergonomico"]).round(4)
    tabla["factor_exposicion"] = (tabla["altura_centro_m"].map(lambda h: _exposicion_altura(h, factores)) +
                                  factores["bonus_cabecera"] * tabla["cabecera"].astype(float) +
                                  factores["bonus_caja"] * (1 - tabla["distancia_m"] / distancia_max) +
                                  factores["bonus_flujo"] * (1 - tabla["distancia_ingreso_m"] / ingreso_max)).round(4)
    return tabla


# --------------------------------------------------------------------------------------
# 2. Pares producto-posición posibles (se descartan los imposibles ANTES de optimizar)
# --------------------------------------------------------------------------------------

def _orientaciones(largo, ancho, alto, girar):
    """(frente, fondo, alto) permitidos. Siempre se puede girar sobre la base."""
    opciones = [(largo, ancho, alto), (ancho, largo, alto)]
    if girar:
        opciones += [(largo, alto, ancho), (alto, largo, ancho), (ancho, alto, largo), (alto, ancho, largo)]
    return opciones


def _ajuste(dimensiones, girar, cantidad, ancho, fondo, alto, holgura):
    """Para cada posición (arreglos en cm) calcula el menor ancho que ocupa la cantidad pedida,
    probando las orientaciones permitidas. Devuelve (ancho, frentes, unidades_caben, orientacion, cabe_alto)."""
    largo_p, ancho_p, alto_p, apilado = dimensiones
    n = len(ancho)
    mejor_ancho = np.full(n, np.inf)
    mejor_frentes = np.zeros(n, dtype=int)
    mejor_caben = np.zeros(n, dtype=int)
    mejor_orientacion = np.array([""] * n, dtype=object)
    cabe_alto = np.zeros(n, dtype=bool)
    for frente_cm, fondo_cm, alto_cm in _orientaciones(largo_p, ancho_p, alto_p, girar):
        entra = (alto_cm + holgura <= alto) & (fondo_cm <= fondo)
        cabe_alto |= entra
        por_fondo = np.floor(fondo / fondo_cm)
        capas = np.clip(np.minimum(apilado, np.floor((alto - holgura) / alto_cm)), 1, None)
        por_frente = np.maximum(por_fondo * capas, 1)
        frentes = np.ceil(cantidad / por_frente)
        ocupado = frentes * frente_cm
        entra &= ocupado <= ancho
        mejora = entra & (ocupado < mejor_ancho)
        mejor_ancho = np.where(mejora, ocupado, mejor_ancho)
        mejor_frentes = np.where(mejora, frentes, mejor_frentes)
        mejor_caben = np.where(mejora, frentes * por_frente, mejor_caben)
        mejor_orientacion = np.where(mejora, f"{frente_cm:g}×{fondo_cm:g}×{alto_cm:g} cm", mejor_orientacion)
    return mejor_ancho, mejor_frentes, mejor_caben, mejor_orientacion, cabe_alto


def pares_factibles(productos, posiciones, parametros, local, modo="almacen", ajustes=None):
    """Devuelve (pares, motivos_sin_lugar).
    pares: DataFrame con i, j (primer tramo), cubre (tramos usados), ancho_ocupado_m, volumen_m3, peso_kg, frentes, unidades_caben, orientacion, coef
    motivos_sin_lugar: {i: texto} para productos que no caben en ninguna posición."""
    ajustes = ajustes or cargar_ajustes()
    pesos = ajustes["objetivo"]
    holgura = ajustes["geometria"]["holgura_altura_cm"]
    validas = posiciones[posiciones["valida"]].reset_index(drop=True)
    ancho = validas["ancho_m"].to_numpy() * 100
    fondo = validas["fondo_m"].to_numpy() * 100
    alto = validas["alto_libre_m"].to_numpy() * 100
    base = validas["base_m"].to_numpy()
    centro = validas["altura_centro_m"].to_numpy()
    capacidad = validas["capacidad_kg_nivel"].to_numpy()
    tipo = validas["tipo_estante"].astype(str).to_numpy()
    controlada = validas["zona_controlada"].to_numpy(dtype=bool)
    peligrosos = validas["permite_peligrosos"].to_numpy(dtype=bool)
    nivel = validas["nivel"].to_numpy()
    niveles = validas["niveles_estante"].to_numpy()
    costo = validas["costo_acceso"].to_numpy()
    exposicion = validas["factor_exposicion"].to_numpy()
    es_frio = np.isin(tipo, ["refrigerador"])
    es_congelador = np.isin(tipo, ["congelador"])
    ergo = ajustes["ergonomia"]
    zona_dorada = (centro >= ergo["altura_cadera_m"]) & (centro <= ergo["altura_hombros_m"])
    limite = parametros.get("limite_peso_kg")
    hay_equipo = bool({e.get("tipo") for e in local.get("equipos", [])} & EQUIPOS_CARGA)
    umbral_pesado = parametros.get("umbral_pesado_kg")
    altura_ninos = parametros.get("ninos_altura_max_m")

    con_ventas = productos.loc[productos["m_rotacion"] > 0, "m_rotacion"]
    referencia_rot = float(con_ventas.median()) if len(con_ventas) else 1.0
    con_margen = productos.loc[productos["margen_diario"] > 0, "margen_diario"]
    referencia_margen = float(con_margen.median()) if len(con_margen) else 1.0

    # Grupos de tramos contiguos de un mismo nivel (para productos que necesitan más de un tramo)
    grupos_nivel = []
    for _, grupo in validas.groupby(["estante", "nivel"]):
        grupo = grupo.sort_values("tramo")
        bloque = [grupo.index[0]]
        for anterior, actual in zip(grupo.index[:-1], grupo.index[1:]):
            if validas.at[actual, "tramo"] == validas.at[anterior, "tramo"] + 1:
                bloque.append(actual)
            else:
                grupos_nivel.append(bloque)
                bloque = [actual]
        grupos_nivel.append(bloque)
    # Arreglos de los grupos (vectorizado): primer tramo, tamaño, ancho por tramo y grupo de cada posición
    grupo_j0 = np.array([b[0] for b in grupos_nivel], dtype=int)
    grupo_n = np.array([len(b) for b in grupos_nivel], dtype=int)
    grupo_ancho = np.array([sum(ancho[t] for t in b) / len(b) for b in grupos_nivel])
    grupo_de = np.zeros(len(validas), dtype=int)
    for g, b in enumerate(grupos_nivel):
        grupo_de[b] = g
    maximo_tramos = int(grupo_n.max()) if len(grupo_n) else 0

    filas, motivos, restricciones = [], {}, {}
    for i, producto in productos.iterrows():
        q = int(producto["m_cantidad"])
        girar = producto.get("se_puede_girar") == "si"
        dimensiones = (producto["m_largo"], producto["m_ancho"], producto["m_alto"], producto["m_apilado"])
        mejor_ancho, mejor_frentes, mejor_caben, mejor_orientacion, cabe_alto = _ajuste(
            dimensiones, girar, q, ancho, fondo, alto, holgura)
        cabe = np.isfinite(mejor_ancho)
        peso_total = q * float(producto["m_peso"])
        regla = np.ones(len(validas), dtype=bool)
        motivo_regla = []
        temperatura = producto.get("temperatura_requerida") or "ambiente"
        if temperatura == "refrigerado":
            regla &= es_frio
            motivo_regla.append("requiere refrigerador")
        elif temperatura == "congelado":
            regla &= es_congelador
            motivo_regla.append("requiere congelador")
        else:
            regla &= ~(es_frio | es_congelador)
        if parametros.get("valor_alto_controlado") and producto.get("valor_alto") == "si":
            regla &= controlada
            motivo_regla.append("es de alto valor y solo va en zona controlada")
        if producto.get("peligroso") == "si":
            regla &= peligrosos
            motivo_regla.append("es peligroso y solo va en estantes habilitados")
        if limite is not None and producto["m_peso"] > limite:
            if hay_equipo:
                regla &= base <= 0.3
                motivo_regla.append(f"pesa {producto['m_peso']:.1f} kg (> {limite} kg) y solo va al nivel del piso")
            else:
                regla &= False
                motivo_regla.append(f"pesa {producto['m_peso']:.1f} kg por unidad, más que el límite ergonómico de {limite} kg, "
                                    "y el local no tiene equipo de carga")
        peso_ok = peso_total <= capacidad
        factible = cabe & regla & peso_ok
        directas = np.nonzero(factible)[0]
        opciones = []
        if (cabe_alto & regla & peso_ok & ~factible).any():
            # Niveles donde no entra en un tramo: se prueba con 2, 3… tramos contiguos del mismo nivel (todos los
            # tramos de un nivel miden igual, así que basta probar cada largo de bloque una vez por grupo)
            con_directa = np.bincount(grupo_de[factible], minlength=len(grupos_nivel)) > 0
            pendientes = cabe_alto[grupo_j0] & regla[grupo_j0] & peso_ok[grupo_j0] & ~con_directa
            for largo_bloque in range(2, maximo_tramos + 1):
                seleccion = np.nonzero(pendientes & (grupo_n >= largo_bloque))[0]
                if not len(seleccion):
                    if not (pendientes & (grupo_n > largo_bloque)).any():
                        break
                    continue
                j0s = grupo_j0[seleccion]
                r = _ajuste(dimensiones, girar, q, largo_bloque * grupo_ancho[seleccion], fondo[j0s], alto[j0s], holgura)
                for k in np.nonzero(np.isfinite(r[0]))[0]:
                    bloque = grupos_nivel[seleccion[k]]
                    # Inicios alineados (0, L, 2L… y el último) para no multiplicar opciones casi iguales
                    inicios = sorted(set(range(0, len(bloque) - largo_bloque + 1, largo_bloque)) | {len(bloque) - largo_bloque})
                    for inicio in inicios:
                        cubre = tuple(int(t) for t in bloque[inicio:inicio + largo_bloque])
                        opciones.append((cubre[0], cubre, r[0][k], r[1][k], r[2][k], r[3][k]))
                    pendientes[seleccion[k]] = False
        if not opciones and not len(directas):
            medidas_texto = f"{producto['m_largo']:g}×{producto['m_ancho']:g}×{producto['m_alto']:g} cm"
            if not regla.any():
                motivos[i] = "No hay posición permitida: " + "; ".join(motivo_regla)
            elif not (cabe_alto & regla).any():
                motivos[i] = f"Es demasiado alto o profundo para todos los niveles ({medidas_texto})."
            elif not (cabe_alto & regla & peso_ok).any():
                motivos[i] = f"Su peso ({peso_total:.1f} kg) supera la capacidad de los niveles donde cabe."
            else:
                motivos[i] = f"El stock mínimo ({q} u.) no cabe a lo ancho de ningún nivel completo ({medidas_texto})."
            continue
        if motivo_regla:
            restricciones[i] = "; ".join(motivo_regla)
        # Opciones en arreglos (vectorizado): primero las de un solo tramo, luego las de varios tramos
        indices = np.concatenate([directas, np.array([o[0] for o in opciones], dtype=int)]).astype(int)
        cubres = [(int(j),) for j in directas] + [o[1] for o in opciones]
        ocupados = np.concatenate([mejor_ancho[directas], np.array([o[2] for o in opciones], dtype=float)])
        frentes_o = np.concatenate([mejor_frentes[directas], np.array([o[3] for o in opciones], dtype=int)])
        caben_o = np.concatenate([mejor_caben[directas], np.array([o[4] for o in opciones], dtype=int)])
        orientaciones_o = np.concatenate([mejor_orientacion[directas], np.array([o[5] for o in opciones], dtype=object)])
        costo_opcion = np.concatenate([costo[directas], np.array([costo[list(o[1])].mean() for o in opciones], dtype=float)])
        exposicion_opcion = np.concatenate([exposicion[directas],
                                            np.array([exposicion[list(o[1])].mean() for o in opciones], dtype=float)])
        # Penalizaciones de reglas blandas (en las mismas unidades que el costo)
        penal = np.zeros(len(indices))
        if umbral_pesado is not None and producto["m_peso"] >= umbral_pesado:
            penal += (producto["m_peso"] / umbral_pesado) * base[indices]
        if parametros.get("fragil_no_debajo") and producto.get("fragil") == "si":
            penal += (niveles[indices] - nivel[indices]) / np.maximum(niveles[indices], 1)
        if parametros.get("fefo") and producto.get("perecible") == "si":
            penal += 0.5 * (~zona_dorada[indices])
        if altura_ninos is not None and bool(producto.get("para_ninos")):
            penal += 1.0 * (base[indices] > altura_ninos)
        if modo == "tienda":
            peso_producto = max(float(producto["margen_diario"]), referencia_margen * 0.05)
            coef = -float(producto["margen_diario"]) * exposicion_opcion + pesos["peso_reglas_blandas"] * peso_producto * penal
        else:
            peso_producto = max(float(producto["m_rotacion"]), referencia_rot * 0.05)
            coef = float(producto["m_rotacion"]) * costo_opcion + pesos["peso_reglas_blandas"] * peso_producto * penal
        volumen = q * producto["m_largo"] * producto["m_ancho"] * producto["m_alto"] / 1e6
        n = len(indices)
        filas.append((np.full(n, i), indices.astype(int), cubres, np.asarray(ocupados, dtype=float) / 100, np.full(n, volumen),
                      np.full(n, peso_total), np.asarray(frentes_o).astype(int), np.asarray(caben_o).astype(int),
                      np.asarray(orientaciones_o, dtype=object), np.asarray(coef, dtype=float)))
    columnas_pares = ["i", "j", "cubre", "ancho_ocupado_m", "volumen_m3", "peso_kg", "frentes", "unidades_caben", "orientacion", "coef"]
    if filas:
        datos = {}
        for k, columna in enumerate(columnas_pares):
            if columna == "cubre":
                datos[columna] = [c for fila in filas for c in fila[k]]
            else:
                datos[columna] = np.concatenate([fila[k] for fila in filas])
        pares = pd.DataFrame(datos, columns=columnas_pares)
    else:
        pares = pd.DataFrame(columns=columnas_pares)
    pares.attrs["restricciones"] = restricciones
    return pares, motivos, validas


# --------------------------------------------------------------------------------------
# 3. Restricciones que dependen de varias posiciones
# --------------------------------------------------------------------------------------

def distancias_estantes(local):
    huellas = {e["id"]: huella_estante(e) for e in local.get("estantes", [])}
    return {(a, b): distancia_rects(ha, hb) for a, ha in huellas.items() for b, hb in huellas.items()}


def pares_estantes_incompatibles(incompatibilidades, distancias):
    """{(cat_a, cat_b): [(e1, e2), ...]} estantes demasiado cercanos para ese par de categorías."""
    resultado = {}
    for a, b, minima, _motivo in incompatibilidades:
        resultado[(a, b)] = [(e1, e2) for (e1, e2), d in distancias.items() if d < minima]
    return resultado


class Capacidad:
    """Lleva la cuenta de lo ocupado (para la heurística y las líneas base)."""

    def __init__(self, validas, local):
        self.ancho = validas["ancho_m"].to_numpy().copy()
        self.volumen = (validas["ancho_m"] * validas["fondo_m"] * validas["alto_libre_m"]).to_numpy().copy()
        self.nivel_de = list(zip(validas["estante"], validas["nivel"]))
        self.estante_de = validas["estante"].tolist()
        self.peso_nivel = {}
        for clave, capacidad in zip(self.nivel_de, validas["capacidad_kg_nivel"]):
            self.peso_nivel[clave] = capacidad
        self.peso_piso = {}
        capacidad_piso = local.get("capacidad_piso_kg_m2")
        if capacidad_piso:
            for estante in local.get("estantes", []):
                x0, y0, x1, y1 = huella_estante(estante)
                self.peso_piso[estante["id"]] = capacidad_piso * (x1 - x0) * (y1 - y0)
        self.categorias = {}

    def entra(self, cubre, ancho, volumen, peso):
        j = cubre[0]
        n = len(cubre)
        return (all(ancho / n <= self.ancho[t] + 1e-9 and volumen / n <= self.volumen[t] + 1e-9 for t in cubre) and
                peso <= self.peso_nivel[self.nivel_de[j]] + 1e-9 and
                peso <= self.peso_piso.get(self.estante_de[j], math.inf) + 1e-9)

    def ocupar(self, cubre, ancho, volumen, peso, categoria):
        j = cubre[0]
        for t in cubre:
            self.ancho[t] -= ancho / len(cubre)
            self.volumen[t] -= volumen / len(cubre)
        self.peso_nivel[self.nivel_de[j]] -= peso
        if self.estante_de[j] in self.peso_piso:
            self.peso_piso[self.estante_de[j]] -= peso
        self.categorias.setdefault(self.estante_de[j], set()).add(categoria)

    def compatible(self, j, categoria, incompatibilidades, distancias):
        estante = self.estante_de[j]
        for a, b, minima, _ in incompatibilidades:
            if categoria not in (a, b):
                continue
            otra = b if categoria == a else a
            for otro_estante, cats in self.categorias.items():
                if otra in cats and distancias[(estante, otro_estante)] < minima:
                    return False
        return True


def heuristica(productos, pares, validas, local, incompatibilidades, modo="almacen"):
    """Heurística de respaldo: ordena por rotación (o margen) y llena por costo de acceso."""
    return heuristica_rapida(productos, pares, validas, local, incompatibilidades, modo)


def heuristica_rapida(productos, pares, validas, local, incompatibilidades, modo="almacen", permitidas=None):
    """Misma heurística con arreglos de numpy (sin recorrer filas de pandas). `permitidas` es una máscara
    booleana por posición de `validas` (por ejemplo, solo las de los módulos elegidos)."""
    distancias = distancias_estantes(local) if incompatibilidades else {}
    capacidad = Capacidad(validas, local)
    criterio = "margen_diario" if modo == "tienda" else "m_rotacion"
    volumen_unit = productos["m_largo"] * productos["m_ancho"] * productos["m_alto"]
    orden = productos.assign(_v=volumen_unit).sort_values([criterio, "ventas_soles", "_v"], ascending=False).index
    if not len(pares):
        return {}
    costo_pos = validas["costo_acceso"].to_numpy()
    i_par = pares["i"].to_numpy()
    j_par = pares["j"].to_numpy()
    sin_rotacion = (productos[criterio].to_numpy() <= 0)[i_par]
    # Sin rotación: van a las posiciones de peor acceso para dejar libres las buenas
    clave = np.where(sin_rotacion, -costo_pos[j_par], pares["coef"].to_numpy())
    orden_pares = np.lexsort((clave, i_par))
    if permitidas is not None:
        orden_pares = orden_pares[permitidas[j_par[orden_pares]]]
    i_ordenado = i_par[orden_pares]
    inicios = np.searchsorted(i_ordenado, np.arange(len(productos)), side="left")
    finales = np.searchsorted(i_ordenado, np.arange(len(productos)), side="right")
    cubre = pares["cubre"].to_numpy()
    anchos = pares["ancho_ocupado_m"].to_numpy()
    volumenes = pares["volumen_m3"].to_numpy()
    pesos = pares["peso_kg"].to_numpy()
    categorias = productos["categoria_modelo"].to_numpy()
    tramos_usados = np.array([len(c) for c in cubre])
    posicion_de = {i: k for k, i in enumerate(productos.index)}
    asignacion = {}
    for i in orden:
        k = posicion_de[i]
        categoria = categorias[k]
        opciones = orden_pares[inicios[k]:finales[k]]
        if len(opciones) > 8:  # descarte rápido: el primer tramo debe tener el ancho libre necesario
            opciones = opciones[capacidad.ancho[j_par[opciones]] + 1e-9 >= anchos[opciones] / tramos_usados[opciones]]
        for p in opciones:
            if capacidad.entra(cubre[p], anchos[p], volumenes[p], pesos[p]) and \
                    capacidad.compatible(j_par[p], categoria, incompatibilidades, distancias):
                capacidad.ocupar(cubre[p], anchos[p], volumenes[p], pesos[p], categoria)
                asignacion[i] = int(j_par[p])
                break
    return asignacion


# --------------------------------------------------------------------------------------
# 4. Modelo entero
# --------------------------------------------------------------------------------------

def _candidatos(pares, productos, asignacion_inicial, k):
    """Se conservan, por producto, las k mejores posiciones, varias repartidas en el resto
    y la posición de la heurística (para que la solución inicial siempre sea factible)."""
    elegidos = []
    mejores = max(1, int(k * 2 / 3))
    repartidas = max(1, k - mejores)
    for i, grupo in pares.groupby("i"):
        if productos.at[i, "m_rotacion"] <= 0 and productos.at[i, "margen_diario"] <= 0:
            grupo = grupo.sort_values("coef", ascending=False)
        else:
            grupo = grupo.sort_values("coef")
        primeros = grupo.head(mejores)
        resto = grupo.iloc[mejores:]
        if len(resto) > repartidas:
            pasos = np.linspace(0, len(resto) - 1, repartidas).astype(int)
            resto = resto.iloc[pasos]
        seleccion = pd.concat([primeros, resto])
        if i in asignacion_inicial and asignacion_inicial[i] not in set(seleccion["j"]):
            seleccion = pd.concat([seleccion, grupo[grupo["j"] == asignacion_inicial[i]]])
        elegidos.append(seleccion)
    if not elegidos:
        return pares.iloc[0:0]
    return pd.concat(elegidos).drop_duplicates(["i", "j"]).reset_index(drop=True)


def _leer_log(ruta):
    """Extrae de la bitácora de CBC el resultado, la cota y la brecha."""
    datos = {"resultado": "", "objetivo": None, "cota": None, "brecha": None}
    if not Path(ruta).exists():
        return datos
    texto = Path(ruta).read_text(errors="ignore")
    if (m := re.search(r"Result - (.+)", texto)):
        datos["resultado"] = m.group(1).strip()
    if (m := re.search(r"Objective value:\s+(-?[\d.eE+-]+)", texto)):
        datos["objetivo"] = float(m.group(1))
    if (m := re.search(r"Lower bound:\s+(-?[\d.eE+-]+)", texto)):
        datos["cota"] = float(m.group(1))
    if (m := re.search(r"Gap:\s+(-?[\d.eE+-]+)", texto)):
        datos["brecha"] = float(m.group(1))
    return datos


class _CBCEnCarpeta(pulp.PULP_CBC_CMD):
    """CBC que escribe sus archivos de trabajo en una carpeta propia de cada corrida (sin cambiar la carpeta del proceso).
    keepFiles=True es necesario en Windows para el arranque en caliente; la carpeta se borra al terminar."""

    def __init__(self, carpeta, **opciones):
        super().__init__(**opciones)
        self._carpeta = str(carpeta)

    def create_tmp_files(self, name, *args):
        rutas = [os.path.join(self._carpeta, f"{name}-pulp.{n}") for n in args]
        if os.name == "nt":
            # CBC 2.10.3 en Windows antepone ".\\" a la ruta del archivo de arranque en caliente (-mips): con una ruta
            # absoluta no lo encuentra y pierde la solución inicial. Se usan rutas relativas a la carpeta actual.
            try:
                rutas = [os.path.relpath(r) for r in rutas]
            except ValueError:  # otra unidad de disco: se dejan absolutas
                pass
        return iter(rutas)

    def copy(self):
        copia = super().copy()
        copia._carpeta = self._carpeta
        return copia


def valor_objetivo(asignacion, pares):
    """Suma de coeficientes de la asignación (parte principal del objetivo)."""
    if not asignacion:
        return 0.0
    indice = dict(zip(zip(pares["i"].to_numpy(), pares["j"].to_numpy()), pares["coef"].to_numpy()))
    return float(sum(indice.get((i, j), 0.0) for i, j in asignacion.items()))


def resolver(productos, pares, validas, local, incompatibilidades, pares_venta=None, modo="almacen",
             tiempo_limite=None, brecha=None, ajustes=None, pesos=None, avance=None, inicial=None, modulos=None):
    """Arma y resuelve el modelo. Devuelve un diccionario con la solución y su diagnóstico.

    `modulos` (opcional, diseño de racks) = {"modulo_de": arreglo con el módulo de cada posición de `validas`,
    "peso_inversion": {m: λ × costo anualizado}, "costo_inversion": {m: precio + montaje}, "fijos": {m},
    "conflictos": [(m, m')], "presupuesto": soles o None, "inicial": {m}}. Con él se agrega z[m] ∈ {0,1}."""
    ajustes = ajustes or cargar_ajustes()
    pesos = pesos or ajustes["objetivo"]
    tiempo_limite = tiempo_limite or ajustes["solver"]["tiempo_limite_s"]
    brecha = ajustes["solver"]["brecha_relativa"] if brecha is None else brecha
    inicio = time.time()
    if avance:
        avance(0.05, "Calculando la solución inicial con la heurística…")
    if inicial is None:
        inicial = heuristica(productos, pares, validas, local, incompatibilidades, modo)
    objetivo_heuristica = valor_objetivo(inicial, pares)
    candidatos = _candidatos(pares, productos, inicial, ajustes["solver"]["candidatos_por_producto"])
    if avance:
        avance(0.15, f"Armando el modelo: {len(candidatos):,} pares producto-posición posibles…")

    modelo = pulp.LpProblem("modelo_acomoda", pulp.LpMinimize)
    claves = list(zip(candidatos["i"], candidatos["j"]))
    x = {clave: pulp.LpVariable(f"x_{clave[0]}_{clave[1]}", cat="Binary") for clave in claves}
    productos_con_pares = sorted(set(candidatos["i"]))
    y = {i: pulp.LpVariable(f"y_{i}", lowBound=0, upBound=1) for i in productos_con_pares}
    escala = max(1.0, float(candidatos["coef"].abs().max() or 1.0))
    penal_no_ubicado = ajustes["solver"]["penalizacion_no_ubicado"] * escala
    coef = dict(zip(claves, candidatos["coef"]))
    objetivo = [coef[c] * x[c] for c in claves]
    objetivo += [penal_no_ubicado * (1 + float(productos.at[i, "prioridad"])) * y[i] for i in productos_con_pares]

    # (1) Cada producto en una sola posición o queda sin ubicar
    por_producto = candidatos.groupby("i")
    for i, grupo in por_producto:
        modelo += pulp.lpSum(x[(i, j)] for j in grupo["j"]) + y[i] == 1, f"uno_{i}"
    # (2) Ancho y volumen por posición; (3) peso por nivel y por piso
    volumen_pos = (validas["ancho_m"] * validas["fondo_m"] * validas["alto_libre_m"]).to_numpy()
    uso_ancho, uso_volumen = {}, {}
    for r in candidatos.itertuples():
        for t in r.cubre:  # un producto que usa varios tramos reparte su ancho entre ellos
            uso_ancho.setdefault(t, []).append((r.ancho_ocupado_m / len(r.cubre), x[(r.i, r.j)]))
            uso_volumen.setdefault(t, []).append((r.volumen_m3 / len(r.cubre), x[(r.i, r.j)]))
    for t, terminos in uso_ancho.items():
        modelo += pulp.lpSum(a * v for a, v in terminos) <= validas.at[t, "ancho_m"], f"ancho_{t}"
        modelo += pulp.lpSum(a * v for a, v in uso_volumen[t]) <= volumen_pos[t], f"vol_{t}"
    candidatos = candidatos.assign(estante=validas["estante"].to_numpy()[candidatos["j"]],
                                   nivel=validas["nivel"].to_numpy()[candidatos["j"]])
    capacidad_nivel = validas.groupby(["estante", "nivel"])["capacidad_kg_nivel"].first()
    for (estante, nivel), grupo in candidatos.groupby(["estante", "nivel"]):
        modelo += pulp.lpSum(r.peso_kg * x[(r.i, r.j)] for r in grupo.itertuples()) <= capacidad_nivel[(estante, nivel)], \
            f"peso_{estante}_{nivel}"
    capacidad_piso = local.get("capacidad_piso_kg_m2")
    if capacidad_piso:
        for estante in local.get("estantes", []):
            grupo = candidatos[candidatos["estante"] == estante["id"]]
            if len(grupo):
                x0, y0, x1, y1 = huella_estante(estante)
                modelo += pulp.lpSum(r.peso_kg * x[(r.i, r.j)] for r in grupo.itertuples()) <= \
                    capacidad_piso * (x1 - x0) * (y1 - y0), f"piso_{estante['id']}"

    # (5) Categorías: u[c,e] = la categoría c usa el estante e
    candidatos["categoria"] = productos["categoria_modelo"].to_numpy()[candidatos["i"]]
    categorias_incompatibles = {c for a, b, _, _ in incompatibilidades for c in (a, b)}
    agrupar = pesos.get("peso_agrupar_categoria", 0) > 0
    u = {}
    for (categoria, estante), grupo in candidatos.groupby(["categoria", "estante"]):
        if categoria in categorias_incompatibles or (agrupar and categoria != "SIN CATEGORÍA"):
            u[(categoria, estante)] = pulp.LpVariable(f"u_{len(u)}", cat="Binary")
            n = grupo["i"].nunique()
            modelo += pulp.lpSum(x[(r.i, r.j)] for r in grupo.itertuples()) <= n * u[(categoria, estante)], f"usa_{len(u)}"
    distancias = distancias_estantes(local)
    numero = 0
    for (a, b), cercanos in pares_estantes_incompatibles(incompatibilidades, distancias).items():
        for e1, e2 in cercanos:
            if (a, e1) in u and (b, e2) in u:
                modelo += u[(a, e1)] + u[(b, e2)] <= 1, f"incompat_{numero}"
                numero += 1
    escala_objetivo = float(candidatos.groupby("i")["coef"].min().abs().mean() or 1.0)
    if agrupar:
        objetivo += [pesos["peso_agrupar_categoria"] * escala_objetivo * var for (c, _), var in u.items() if c != "SIN CATEGORÍA"]

    # Productos vendidos juntos (dato de entrada del costo): premio si comparten estante
    s = {}
    if pares_venta is not None and len(pares_venta) and pesos.get("peso_pares_comprobante", 0) > 0:
        id_a_indice = {v: k for k, v in productos["id_producto"].items()}
        maximo_veces = pares_venta["veces"].max()
        estantes_de = candidatos.groupby("i")["estante"].apply(set).to_dict()
        for numero_par, par in enumerate(pares_venta.itertuples()):
            ia, ib = id_a_indice.get(par.id_a), id_a_indice.get(par.id_b)
            if ia is None or ib is None or ia not in estantes_de or ib not in estantes_de:
                continue
            for estante in estantes_de[ia] & estantes_de[ib]:
                var = pulp.LpVariable(f"s_{numero_par}_{estante}", lowBound=0, upBound=1)
                s[(numero_par, estante)] = var
                modelo += var <= pulp.lpSum(x[(r.i, r.j)] for r in candidatos[(candidatos["i"] == ia) & (candidatos["estante"] == estante)].itertuples())
                modelo += var <= pulp.lpSum(x[(r.i, r.j)] for r in candidatos[(candidatos["i"] == ib) & (candidatos["estante"] == estante)].itertuples())
                objetivo.append(-pesos["peso_pares_comprobante"] * escala_objetivo * (par.veces / maximo_veces) * var)
    # Diseño de racks: z[m] = se instala el módulo m
    z = {}
    if modulos is not None:
        modulo_de = modulos["modulo_de"]
        usados = sorted({modulo_de[j] for j in candidatos["j"]} | set(modulos["fijos"]))
        for m in usados:
            z[m] = pulp.LpVariable(f"z_{m}", cat="Binary")
            if m in modulos["fijos"]:  # (4) modos B y C: los estantes existentes quedan instalados (PuLP ignora la cota de un binario)
                modelo += z[m] == 1, f"fijo_{m}"
        # (1) x[i,j] ≤ z[módulo de j]: no se ubica nada en un módulo no instalado
        for numero, (i, j) in enumerate(claves):
            modelo += x[(i, j)] <= z[modulo_de[j]], f"instalado_{numero}"
        # (2) z[m] + z[m'] ≤ 1 si los candidatos se solapan o uno tapa el pasillo del otro
        for numero, (a, b) in enumerate(modulos["conflictos"]):
            if a in z and b in z:
                modelo += z[a] + z[b] <= 1, f"conflicto_{numero}"
        # (3) Presupuesto
        if modulos.get("presupuesto") is not None:
            modelo += pulp.lpSum(modulos["costo_inversion"].get(m, 0.0) * z[m] for m in z
                                 if m not in modulos["fijos"]) <= modulos["presupuesto"], "presupuesto"
        objetivo += [modulos["peso_inversion"].get(m, 0.0) * z[m] for m in z if m not in modulos["fijos"]]
    modelo += pulp.lpSum(objetivo)

    # Solución inicial (arranque en caliente)
    for m, variable in z.items():
        variable.setInitialValue(1 if (m in modulos["fijos"] or m in modulos["inicial"]) else 0)
    for clave, variable in x.items():
        variable.setInitialValue(1 if inicial.get(clave[0]) == clave[1] else 0)
    for i, variable in y.items():
        variable.setInitialValue(0 if i in inicial else 1)
    for (categoria, estante), variable in u.items():
        variable.setInitialValue(int(any(inicial.get(r.i) == r.j for r in candidatos[(candidatos["categoria"] == categoria) &
                                                                                         (candidatos["estante"] == estante)].itertuples())))
    # El tiempo límite cubre todo el proceso: CBC recibe lo que queda después de armar el modelo (mínimo 5 s)
    tiempo_limite = max(5, int(tiempo_limite - (time.time() - inicio)))
    if avance:
        avance(0.3, f"Resolviendo con CBC ({len(x):,} variables binarias, quedan {tiempo_limite} s)…")
    # Cada corrida usa su propia carpeta temporal: así dos usuarios (o dos clics) nunca pelean por el mismo archivo
    # y no se cambia la carpeta de trabajo del proceso (que en un servidor web es compartida por todos).
    carpeta_trabajo = Path(tempfile.mkdtemp(prefix="cbc_", dir=CARPETA_PROCESADOS))
    ruta_log = carpeta_trabajo / "bitacora_cbc.log"
    # CBC 2.10.3 se cae (segmentation fault) en algunos modelos grandes si se combina el arranque en caliente con su
    # preprocesamiento: se usa el arranque en caliente SIN preprocesamiento y, si aun así falla, se reintenta sin él.
    intentos = [dict(warmStart=True, options=["preprocess off"]), dict(warmStart=False, options=[])]
    estado_solucion, mensaje_error = None, ""
    for intento in intentos:
        solver = _CBCEnCarpeta(carpeta_trabajo, msg=False, timeLimit=tiempo_limite, gapRel=brecha, keepFiles=True,
                               logPath=str(ruta_log), **intento)
        try:
            modelo.solve(solver)
            estado_solucion = modelo.sol_status
            break
        except Exception as error:  # el solver no pudo correr: se prueba el siguiente intento
            estado_solucion = None
            mensaje_error = str(error)
    log = _leer_log(ruta_log)
    if not os.environ.get("ACOMODA_DEPURAR_CBC"):
        shutil.rmtree(carpeta_trabajo, ignore_errors=True)
    duracion = time.time() - inicio
    if estado_solucion in (pulp.LpSolutionOptimal, pulp.LpSolutionIntegerFeasible):
        asignacion = {i: j for (i, j), var in x.items() if var.value() is not None and var.value() > 0.5}
        estado = "Óptimo" if estado_solucion == pulp.LpSolutionOptimal and "time" not in log["resultado"].lower() \
            else "Factible (se detuvo por tiempo)"
        fuente = "modelo"
    else:
        asignacion = inicial
        estado = "Sin solución del modelo: se usa la heurística" + (f" ({mensaje_error})" if estado_solucion is None else f" (CBC: {log['resultado'] or estado_solucion})")
        fuente = "heuristica"
    objetivo_modelo = valor_objetivo(asignacion, pares)
    if fuente == "modelo" and len(asignacion) < len(inicial):
        # Por seguridad: nunca entregar menos productos ubicados que la heurística
        asignacion, fuente = inicial, "heuristica"
        estado += " — la heurística ubicó más productos y se conserva"
        objetivo_modelo = objetivo_heuristica
    brecha_final = log["brecha"]
    if brecha_final is None and log["objetivo"] is not None and log["cota"] is not None and log["objetivo"] != 0:
        brecha_final = abs(log["objetivo"] - log["cota"]) / abs(log["objetivo"])
    if estado.startswith("Óptimo") and brecha_final is None:
        brecha_final = 0.0
    instalados = None
    if modulos is not None:
        if fuente == "modelo":
            instalados = {m for m, var in z.items() if var.value() is not None and var.value() > 0.5}
        else:
            instalados = set(modulos["fijos"]) | set(modulos["inicial"])
    if avance:
        avance(1.0, "Listo.")
    return {
        "modulos_instalados": instalados,
        "asignacion": asignacion, "asignacion_heuristica": inicial, "estado": estado, "fuente": fuente,
        "tiempo_s": round(duracion, 1), "brecha": brecha_final, "objetivo": objetivo_modelo,
        "objetivo_heuristica": objetivo_heuristica, "variables": len(x), "restricciones": modelo.numConstraints(),
        "pares_totales": len(pares), "pares_modelo": len(candidatos), "resultado_cbc": log["resultado"],
    }


# --------------------------------------------------------------------------------------
# 5. Orquestación y explicación de lo que no cupo
# --------------------------------------------------------------------------------------

def tabla_ubicaciones(asignacion, productos, pares, validas, motivos):
    """Una fila por producto: dónde quedó (o por qué no se ubicó)."""
    indice = pares.set_index(["i", "j"])
    restricciones = pares.attrs.get("restricciones", {})
    filas = []
    for i, producto in productos.iterrows():
        base = {"id_producto": producto["id_producto"], "producto": producto["producto"], "categoria": producto["categoria"],
                "clase_abc": producto["clase_abc"], "rotacion_diaria": round(float(producto["rotacion_diaria"]), 3),
                "stock_minimo": int(producto["stock_minimo"]), "origen_medidas": producto["origen_medidas"]}
        if i in asignacion:
            j = asignacion[i]
            par = indice.loc[(i, j)]
            posicion = validas.loc[j]
            cubre = par["cubre"]
            identificador = posicion["id_posicion"]
            if len(cubre) > 1:
                identificador += f"…T{int(validas.at[cubre[-1], 'tramo'])}"
            base.update({"id_posicion": identificador, "estante": posicion["estante"], "nivel": int(posicion["nivel"]),
                         "tramo": int(posicion["tramo"]), "tramos_usados": len(cubre), "frentes": int(par["frentes"]),
                         "unidades_caben": int(par["unidades_caben"]) * (int(producto.get("unidades_por_caja") or 1) if producto["usa_caja"] else 1),
                         "orientacion": par["orientacion"], "ancho_ocupado_m": round(float(par["ancho_ocupado_m"]), 3),
                         "distancia_m": float(posicion["distancia_m"]), "costo_acceso": float(posicion["costo_acceso"]),
                         "factor_exposicion": float(posicion["factor_exposicion"]), "ubicado": True,
                         "motivo": _motivo_ubicacion(producto, posicion)})
        else:
            base.update({"id_posicion": "", "estante": "", "nivel": None, "tramo": None, "tramos_usados": 0, "frentes": 0,
                         "unidades_caben": 0,
                         "orientacion": "", "ancho_ocupado_m": 0.0, "distancia_m": None, "costo_acceso": None,
                         "factor_exposicion": None, "ubicado": False,
                         "motivo": motivos.get(i) or _motivo_sin_espacio(restricciones.get(i))})
        filas.append(base)
    return pd.DataFrame(filas)


def _motivo_sin_espacio(restriccion):
    if restriccion:
        return f"No alcanzó el espacio en las posiciones permitidas para él: {restriccion}."
    return "No alcanzó el espacio: tiene menor prioridad que los productos ubicados."


def _motivo_ubicacion(producto, posicion):
    partes = []
    clase = producto["clase_abc"]
    if clase == "A":
        partes.append("clase A: alta rotación, cerca del despacho")
    elif clase == "SIN ROTACIÓN":
        partes.append("sin ventas: posición de menor acceso")
    else:
        partes.append(f"clase {clase}")
    if producto.get("valor_alto") == "si":
        partes.append("alto valor → zona controlada")
    if producto.get("peligroso") == "si":
        partes.append("peligroso → estante habilitado")
    if producto["m_peso"] >= 5:
        partes.append("pesado → nivel bajo")
    if producto.get("fragil") == "si":
        partes.append("frágil")
    return "; ".join(partes)


def explicar_faltante(ubicaciones, productos, validas, local, ajustes=None):
    """Si algo quedó fuera, dice cuánto volumen falta y cuántos módulos de estante comprar."""
    ajustes = ajustes or cargar_ajustes()
    fuera = ubicaciones[~ubicaciones["ubicado"]]
    if not len(fuera):
        return None
    datos = productos.set_index("id_producto").loc[fuera["id_producto"]]
    volumen = float((datos["m_cantidad"] * datos["m_largo"] * datos["m_ancho"] * datos["m_alto"]).sum() / 1e6)
    estantes = local.get("estantes", [])
    if estantes:
        volumen_modulo = float((validas["ancho_m"] * validas["fondo_m"] * validas["alto_libre_m"]).sum() / max(len(estantes), 1))
        costo_modulo = float(np.mean([float(e.get("costo_soles") or ajustes["estante_por_defecto"]["costo_soles"]) for e in estantes]))
    else:
        defecto = ajustes["estante_por_defecto"]
        volumen_modulo = 2.4 * defecto["fondo_m"] * defecto["alto_m"] * 0.8
        costo_modulo = defecto["costo_soles"]
    modulos = math.ceil(volumen / max(volumen_modulo * 0.6, 1e-6))  # 60 % de llenado realista
    por_motivo = fuera["motivo"].str.split(":").str[0].value_counts().to_dict()
    consejos = []
    if fuera["motivo"].str.contains("peligroso").any():
        consejos.append("habilite otro estante para peligrosos (permite_peligrosos = si), lejos de alimentos")
    if fuera["motivo"].str.contains("alto valor").any():
        consejos.append("marque más estantes como zona controlada (zona_controlada = si)")
    if fuera["motivo"].str.contains("demasiado alto").any():
        consejos.append("suba la altura de algún nivel (alturas_niveles_m) para los productos altos")
    texto = (f"No cabe todo: faltan {volumen:,.2f} m³ para {len(fuera)} productos. "
             f"Se sugieren {modulos} módulo(s) de estante adicionales (≈ S/ {modulos * costo_modulo:,.0f}).")
    if consejos:
        texto += " Además: " + "; ".join(consejos) + "."
    return {"productos_fuera": int(len(fuera)), "volumen_faltante_m3": round(volumen, 2),
            "modulos_sugeridos": int(modulos), "costo_modulos": round(modulos * costo_modulo, 2),
            "volumen_modulo_m3": round(volumen_modulo, 2), "por_motivo": por_motivo, "consejos": consejos,
            "texto": texto}


def optimizar(catalogo, resumen, posiciones, local, parametros, incompatibilidades, pares_venta=None, modo="almacen",
              perfil_id="bazar", pesos=None, tiempo_limite=None, brecha=None, avance=None, ajustes=None):
    """Todo el proceso: costos, pares posibles, heurística, modelo y tabla de ubicaciones."""
    ajustes = ajustes or cargar_ajustes()
    pesos = pesos or ajustes["objetivo"]
    if "distancia_m" not in posiciones:
        from modulos.interpretar_local import medir_distancias
        posiciones = medir_distancias(posiciones, local, modo)
    posiciones = calcular_costos_posiciones(posiciones, pesos, perfil_id, ajustes)
    productos = preparar_productos(catalogo, resumen, parametros, modo, ajustes)
    if avance:
        avance(0.02, "Descartando pares producto-posición imposibles…")
    pares, motivos, validas = pares_factibles(productos, posiciones, parametros, local, modo, ajustes)
    if len(pares) == 0:
        solucion = {"asignacion": {}, "asignacion_heuristica": {}, "estado": "Ningún producto cabe en ninguna posición",
                    "fuente": "ninguna", "tiempo_s": 0, "brecha": None, "objetivo": 0, "objetivo_heuristica": 0,
                    "variables": 0, "restricciones": 0, "pares_totales": 0, "pares_modelo": 0, "resultado_cbc": ""}
    else:
        solucion = resolver(productos, pares, validas, local, incompatibilidades, pares_venta, modo, tiempo_limite, brecha,
                            ajustes, pesos, avance)
    ubicaciones = tabla_ubicaciones(solucion["asignacion"], productos, pares, validas, motivos)
    solucion.update({"productos": productos, "pares": pares, "validas": validas, "posiciones": posiciones,
                     "motivos": motivos, "ubicaciones": ubicaciones, "modo": modo,
                     "faltante": explicar_faltante(ubicaciones, productos, validas, local, ajustes)})
    return solucion


# --------------------------------------------------------------------------------------
# 6. Diseño de racks + ubicación (Cambio 1): sigue siendo UN solo modelo, con z[m]
# --------------------------------------------------------------------------------------

def _sin_solucion(texto, local, modo, extra=None):
    vacio = pd.DataFrame(columns=["id_producto", "producto", "categoria", "clase_abc", "ubicado", "motivo"])
    solucion = {"asignacion": {}, "asignacion_heuristica": {}, "estado": texto, "fuente": "ninguna", "tiempo_s": 0,
                "brecha": None, "objetivo": 0, "objetivo_heuristica": 0, "variables": 0, "restricciones": 0,
                "pares_totales": 0, "pares_modelo": 0, "resultado_cbc": "", "ubicaciones": vacio, "modo": modo,
                "local": local, "faltante": {"texto": texto, "productos_fuera": 0}, "factible": False,
                "lista_compra": pd.DataFrame(), "tabla_diseno": pd.DataFrame(), "alternativas": [], "avisos_diseno": [],
                "sin_solucion": True}
    solucion.update(extra or {})
    return solucion


def _unir_pares(pares_1, motivos_1, validas_1, pares_2, motivos_2, validas_2):
    """Junta dos tablas de pares calculadas sobre posiciones distintas (la segunda se corre al final)."""
    desplazamiento = len(validas_1)
    pares_2 = pares_2.copy()
    pares_2["j"] = pares_2["j"] + desplazamiento
    pares_2["cubre"] = [tuple(t + desplazamiento for t in c) for c in pares_2["cubre"]]
    pares = pd.concat([pares_1, pares_2], ignore_index=True)
    pares.attrs["restricciones"] = {**pares_2.attrs.get("restricciones", {}), **pares_1.attrs.get("restricciones", {})}
    validas = pd.concat([validas_1, validas_2], ignore_index=True)
    motivos = {i: m for i, m in motivos_1.items() if i in motivos_2}  # sin lugar en NINGUNA de las dos partes
    return pares, motivos, validas


def alternativas_si_falta(faltante, local, parametros, tipos, instalados, presupuesto, ajustes=None):
    """Si no cabe todo, propone alternativas con su costo estimado (en soles referenciales)."""
    from modulos.diseno_racks import altura_disponible
    ajustes = ajustes or cargar_ajustes()
    if not faltante:
        return []
    volumen = max(float(faltante.get("volumen_faltante_m3") or 0.0), 0.01) / ajustes["diseno"]["factor_llenado"]
    alternativas = []
    if tipos:
        mejor = min(tipos, key=lambda t: t["costo_inversion"] / (t["largo_m"] * t["fondo_m"] * t["alto_m"]))
        modulos = math.ceil(volumen / max(mejor["largo_m"] * mejor["fondo_m"] * (mejor["alto_m"] - 0.1), 1e-6))
        alternativas.append({"alternativa": "Ampliar el presupuesto" if presupuesto is not None else "Agregar módulos",
                             "detalle": f"≈ {modulos} módulos más de «{mejor['nombre']}» (si hay lugar libre)",
                             "costo_estimado_soles": round(modulos * mejor["costo_inversion"], 2)})
        disponible = altura_disponible(local, parametros, ajustes)
        mas_alto = max((float(e["alto_m"]) for e in instalados), default=0.0)
        if disponible - mas_alto >= 0.35:
            alternativas.append({"alternativa": "Permitir racks más altos",
                                 "detalle": f"la altura disponible es {disponible:.2f} m y el rack más alto mide {mas_alto:.2f} m: "
                                            "edite el catálogo para agregar niveles", "costo_estimado_soles": None})
    por_motivo = " ".join(faltante.get("por_motivo", {}))
    if "zona controlada" in por_motivo or "alto valor" in " ".join(faltante.get("consejos", [])):
        alternativas.append({"alternativa": "Definir una zona controlada",
                             "detalle": "los productos de alto valor solo van en una zona «controlada» (agréguela en ZONAS, "
                                        "por ejemplo junto a la caja); hoy no hay ninguna donde se puedan poner racks",
                             "costo_estimado_soles": None})
    for zona in [z for z in local.get("zonas", []) if z.get("tipo") in ajustes["diseno"]["zonas_sin_racks"]]:
        alternativas.append({"alternativa": f"Liberar la zona {zona['tipo']} {zona['id']}",
                             "detalle": f"{zona['largo_m'] * zona['ancho_m']:.1f} m² que hoy no admiten racks",
                             "costo_estimado_soles": None})
    if parametros.get("dias_cobertura"):
        alternativas.append({"alternativa": "Reducir el stock exhibido",
                             "detalle": f"bajar los días de cobertura ({parametros['dias_cobertura']}) en el Paso 4; "
                                        "implica reponer más seguido", "costo_estimado_soles": 0.0})
    return alternativas


def optimizar_diseno(catalogo, resumen, local, parametros, incompatibilidades, pares_venta=None, modo="almacen",
                     perfil_id="bazar", pesos=None, tiempo_limite=None, brecha=None, avance=None, ajustes=None,
                     tipos_tabla=None, lam=None, rapido=False):
    """Diseña los racks (modos A, B o C) y ubica los productos con el único modelo.
    rapido=True entrega la propuesta de la heurística (sin CBC)."""
    from modulos import diseno_racks as dr
    from modulos.cargar_local import preferencias_de
    from modulos.interpretar_local import Grilla, generar_posiciones, medir_distancias, punto_origen
    ajustes = ajustes or cargar_ajustes()
    pesos = pesos or ajustes["objetivo"]
    lam = ajustes["diseno"]["lambda_inversion"] if lam is None else lam
    inicio = time.time()
    avance = avance or (lambda f, t: None)
    preferencias = preferencias_de(local)
    modo_diseno = preferencias["modo_diseno"]
    presupuesto = preferencias.get("presupuesto_max_soles")
    cobertura = bool(preferencias.get("cobertura_total", ajustes["diseno"].get("cobertura_por_defecto", True))) and modo_diseno != "B"
    porcentaje_cobertura = float(preferencias.get("cobertura_porcentaje") or ajustes["diseno"].get("cobertura_defecto", 0.4))
    avisos = []
    existentes = [dict(e, existente=True) for e in local.get("estantes", [])] if modo_diseno in ("B", "C") else []
    if modo_diseno == "A" and local.get("estantes"):
        avisos.append(f"Modo A: los {len(local['estantes'])} estantes declarados no se conservan (diseño desde cero). "
                      "Use el modo C para conservarlos.")
    if modo_diseno == "B" and not existentes:
        return _sin_solucion("Modo B (solo reutilizar) sin estantes existentes: no hay dónde ubicar los productos. "
                             "Declare sus estantes o use el modo A o C.", local, modo)
    local_base = dr.local_con_estantes(local, existentes)
    tipos = []
    if modo_diseno != "B":
        tabla_tipos = tipos_tabla if tipos_tabla is not None else dr.cargar_catalogo_racks()
        tipos, avisos_tipos = dr.tipos_utilizables(tabla_tipos, local_base, parametros, ajustes)
        avisos += avisos_tipos
    avance(0.03, "Generando módulos candidatos (reglas geométricas)…")
    if tipos:
        ajustes_candidatos = ajustes
        if cobertura:
            # Para cubrir el local hacen falta más candidatos (filas espalda con espalda en todo el local)
            ajustes_candidatos = copy.deepcopy(ajustes)
            ajustes_candidatos["diseno"]["limite_candidatos"] = max(
                ajustes["diseno"]["limite_candidatos"], ajustes["diseno"].get("limite_candidatos_cobertura", 8000))
        candidatos, conflictos, info = dr.generar_candidatos(local_base, parametros, tipos, ajustes_candidatos)
    else:
        candidatos, conflictos, info = pd.DataFrame(), np.zeros((0, 2), dtype=int), {"generados": 0, "descartados": {}, "aviso": ""}
    if info.get("aviso"):
        avisos.append(info["aviso"])
    if not existentes and not len(candidatos):
        return _sin_solucion("No se pudo generar ningún módulo candidato (" + "; ".join(
            f"{k}: {v}" for k, v in info.get("descartados", {}).items()) + "). Revise zonas prohibidas, pasillos y tipos de rack.",
            local, modo, {"avisos_diseno": avisos})
    productos = preparar_productos(catalogo, resumen, parametros, modo, ajustes)
    # Pool de módulos que entran al modelo: una selección holgada de la heurística y los mejores alternativos
    # La ubicación de los racks NO depende de la distancia al despacho: se reparten por toda el área útil
    # (seleccionar_modulos_cobertura). La distancia solo se usa después, para asignar productos a posiciones.
    pool, holgada = [], []
    area_util_m2, huella_existente, fraccion_nueva = 0.0, 0.0, 0.0
    volumen_stock = dr.demanda_volumen(productos, ajustes) * ajustes["diseno"]["margen_capacidad"]
    if len(candidatos):
        area_util_m2 = dr.area_util(local_base, parametros, ajustes)
        huella_existente = sum((dr.huella_estante(e)[2] - dr.huella_estante(e)[0]) * (dr.huella_estante(e)[3] - dr.huella_estante(e)[1])
                               for e in existentes)
        if cobertura:
            fraccion_nueva = max(0.0, porcentaje_cobertura - huella_existente / max(area_util_m2, 1e-6))
        # Selección holgada: el área pedida (con margen) o el triple del volumen del stock, lo que sea mayor
        holgada = dr.seleccionar_modulos_cobertura(candidatos, conflictos, area_util_m2,
                                                   min(0.95, fraccion_nueva + 0.15) if cobertura else 0.0, None,
                                                   volumen_objetivo=volumen_stock * 3.0)
        pool = list(holgada)
        if not rapido:
            limite = max(ajustes["diseno"]["modulos_en_modelo"], len(pool))
            for k in candidatos.index:  # ya están ordenados por calidad
                if len(pool) >= limite:
                    break
                if k not in pool:
                    pool.append(int(k))
    fuera_de_la_holgada = set(candidatos.index) - set(holgada) if len(candidatos) else set()
    avance(0.12, f"Calculando posiciones de {len(pool):,} módulos posibles y {len(existentes)} estantes existentes…")
    grilla = Grilla(local_base)
    origen, _ = punto_origen(local_base, modo)
    distancia_origen, _ = grilla.dijkstra(*origen)
    ingreso = next(((z["x_m"] + z["largo_m"] / 2, z["y_m"] + z["ancho_m"] / 2)
                    for z in local_base.get("zonas", []) if z.get("tipo") == "ingreso"), origen)
    distancia_ingreso, _ = grilla.dijkstra(*ingreso)
    partes = []
    if existentes:
        propias = medir_distancias(generar_posiciones(local_base, parametros, ajustes), local_base, modo)
        partes.append(propias.assign(modulo=propias["estante"]))
    if pool:
        partes.append(dr.posiciones_de_candidatos(candidatos.loc[pool], local_base, parametros, grilla, distancia_origen,
                                                  distancia_ingreso, ajustes, modo))
    posiciones = calcular_costos_posiciones(pd.concat(partes, ignore_index=True), pesos, perfil_id, ajustes)
    # Los pares se calculan en dos partes: primero los módulos de la selección holgada (bastan para la heurística)
    # y, solo para el modelo completo, los módulos alternativos
    ids_holgada = set(e["id"] for e in existentes) | (set(candidatos.loc[holgada, "id"]) if holgada else set())
    primera = posiciones["modulo"].isin(ids_holgada)
    avance(0.2, "Descartando pares producto-posición imposibles…")
    pares, motivos, validas = pares_factibles(productos, posiciones[primera], parametros, local_base, modo, ajustes)
    n_primera = len(validas)
    if not rapido and (~primera).any():
        pares_2, motivos_2, validas_2 = pares_factibles(productos, posiciones[~primera], parametros, local_base, modo, ajustes)
        pares, motivos, validas = _unir_pares(pares, motivos, validas, pares_2, motivos_2, validas_2)
    if not len(pares):
        return _sin_solucion("Ningún producto cabe en ninguna posición posible.", local, modo, {"avisos_diseno": avisos})
    modulo_de = validas["modulo"].to_numpy()
    modulo_codigo, nombres_modulo = pd.factorize(validas["modulo"])  # códigos enteros: filtrar es mucho más rápido
    codigo_de = {m: k for k, m in enumerate(nombres_modulo)}
    ids_existentes = [e["id"] for e in existentes]
    estante_de = {e["id"]: e for e in existentes}
    if len(candidatos):
        estante_de.update(dict(zip(candidatos["id"], candidatos["estante"])))
    volumen_existente = float((validas[validas["modulo"].isin(ids_existentes)].eval("ancho_m * fondo_m * alto_libre_m")).sum())

    # Heurística: elegir módulos y llenarlos; si falta espacio, agregar más
    avance(0.3, "Propuesta rápida: eligiendo módulos y ubicando productos con la heurística…")
    objetivo_volumen = max(0.0, volumen_stock - volumen_existente)
    elegidos = dr.seleccionar_modulos_cobertura(candidatos, conflictos, area_util_m2, fraccion_nueva, presupuesto,
                                                excluir=fuera_de_la_holgada, volumen_objetivo=objetivo_volumen)         if len(candidatos) else []
    pares_primera = pares[pares["j"] < n_primera]  # la heurística solo usa los módulos de la selección holgada
    con_pares = set(pares_primera["i"])
    for _ in range(6):
        activos = set(ids_existentes) | {candidatos.at[k, "id"] for k in elegidos}
        permitidas = np.isin(modulo_codigo, [codigo_de[m] for m in activos])
        local_activo = dr.local_con_estantes(local_base, [estante_de[m] for m in activos])
        asignacion = heuristica_rapida(productos, pares_primera, validas, local_activo, incompatibilidades, modo, permitidas)
        faltan = list(con_pares - set(asignacion))
        if not faltan or not len(candidatos):
            break
        datos = productos.loc[faltan]
        volumen_faltante = float((datos["m_cantidad"] * datos["m_largo"] * datos["m_ancho"] * datos["m_alto"]).sum() / 1e6)
        # Lo que limita suele ser la fragmentación (niveles llenos), no el volumen: se crece desde lo ya elegido
        volumen_elegido = float(candidatos.loc[elegidos, "volumen_util_m3"].sum()) if elegidos else 0.0
        objetivo_volumen = max(objetivo_volumen, volumen_elegido) + max(volumen_faltante / ajustes["diseno"]["factor_llenado"], 0.5)
        nuevos = dr.seleccionar_modulos_cobertura(candidatos, conflictos, area_util_m2, fraccion_nueva, presupuesto,
                                                  ya_elegidos=elegidos, excluir=fuera_de_la_holgada,
                                                  volumen_objetivo=objetivo_volumen)
        if len(nuevos) == len(elegidos):
            break
        elegidos = nuevos
    usados = {modulo_de[j] for j in asignacion.values()}
    if not cobertura:
        elegidos = [k for k in elegidos if candidatos.at[k, "id"] in usados]  # sin cobertura, un módulo vacío no se compra
    heuristica_modulos = {candidatos.at[k, "id"] for k in elegidos}
    asignacion_heuristica = dict(asignacion)
    objetivo_h = valor_objetivo(asignacion, pares_primera)
    solucion_modelo = {"estado": "Propuesta rápida (heurística, sin CBC)", "fuente": "heuristica", "brecha": None,
                       "variables": 0, "restricciones": 0, "pares_modelo": 0, "resultado_cbc": "", "objetivo": objetivo_h,
                       "objetivo_heuristica": objetivo_h}
    instalados = set(ids_existentes) | heuristica_modulos
    if not rapido:
        # Módulos que entran al modelo: los de la heurística y los mejores alternativos
        conjunto = set(ids_existentes) | heuristica_modulos | {candidatos.at[k, "id"] for k in pool}
        en_conjunto = np.isin(modulo_codigo, [codigo_de[m] for m in conjunto if m in codigo_de])
        pares_modelo = pares[en_conjunto[pares["j"].to_numpy()]].reset_index(drop=True)
        pares_modelo.attrs = pares.attrs
        local_modelo = dr.local_con_estantes(local_base, [estante_de[m] for m in conjunto])
        ids = candidatos["id"].to_numpy() if len(candidatos) else np.array([])
        conflictos_modelo = [(ids[a], ids[b]) for a, b in conflictos if ids[a] in conjunto and ids[b] in conjunto]
        costo_inversion = dict(zip(candidatos["id"], candidatos["costo_inversion"])) if len(candidatos) else {}
        costo_anual = dict(zip(candidatos["id"], candidatos["costo_anualizado"])) if len(candidatos) else {}
        # λ se lleva a las unidades del recorrido: con λ = 1, la inversión de la heurística pesa lo mismo que su recorrido
        recorrido = abs(objetivo_h) or 1.0
        inversion_anual = sum(costo_anual[m] for m in heuristica_modulos) or max(list(costo_anual.values()) or [1.0])
        escala = recorrido / inversion_anual
        info_modulos = {"modulo_de": modulo_de, "costo_inversion": costo_inversion, "fijos": set(ids_existentes),
                        "peso_inversion": {m: lam * escala * c for m, c in costo_anual.items()},
                        "conflictos": conflictos_modelo, "presupuesto": presupuesto, "inicial": heuristica_modulos}
        avance(0.4, f"Modelo completo: {len(conjunto)} módulos posibles, {len(conflictos_modelo):,} conflictos…")
        # Se reserva tiempo para lo que viene después de CBC (leer la solución y medir el diseño final)
        limite_total = tiempo_limite or ajustes["solver"]["tiempo_limite_s"]
        restante = max(10, 0.9 * limite_total - (time.time() - inicio) - 3)
        solucion_modelo = resolver(productos, pares_modelo, validas, local_modelo, incompatibilidades, pares_venta, modo,
                                   restante, brecha, ajustes, pesos, lambda f, t: avance(0.4 + 0.5 * f, t),
                                   inicial=asignacion_heuristica, modulos=info_modulos)
        asignacion = solucion_modelo["asignacion"]
        usados = {modulo_de[j] for j in asignacion.values()}
        instalados = set(ids_existentes) | (set(solucion_modelo["modulos_instalados"] or set()) & usados)
    vacios = set()
    if cobertura and len(candidatos):
        # Se conservan los módulos con productos y se completan, sin chocar con ellos, hasta cubrir el área pedida.
        # Los que no reciben productos quedan vacíos («capacidad disponible») y el modelo no los vuelve a quitar.
        indice_de = {m: k for k, m in zip(candidatos.index, candidatos["id"])}
        ya = [indice_de[m] for m in instalados if m in indice_de]
        completos = dr.seleccionar_modulos_cobertura(candidatos, conflictos, area_util_m2, fraccion_nueva, presupuesto,
                                                     ya_elegidos=ya)
        instalados |= {candidatos.at[k, "id"] for k in completos}
        usados_final = {modulo_de[j] for j in asignacion.values()}
        vacios = {m for m in instalados if m in indice_de and m not in usados_final}
        estante_de.update({m: dict(estante_de[m], vacio=True) for m in vacios})
    nuevos_instalados = [estante_de[m] for m in instalados if m not in ids_existentes]
    cubierta = sum((dr.huella_estante(e)[2] - dr.huella_estante(e)[0]) * (dr.huella_estante(e)[3] - dr.huella_estante(e)[1])
                   for e in nuevos_instalados) + huella_existente
    info_cobertura = {"activa": bool(cobertura and len(candidatos)), "porcentaje": porcentaje_cobertura if cobertura else None,
                      "area_util_m2": round(area_util_m2, 2), "area_cubierta_m2": round(cubierta, 2),
                      "modulos_vacios": len(vacios), "fraccion_lograda": round(cubierta / max(area_util_m2, 1e-6), 3)}
    if info_cobertura["activa"]:
        avisos.append(f"Racks repartidos por toda el área útil: {cubierta:,.1f} m² de {area_util_m2:,.1f} m² útiles "
                      f"({info_cobertura['fraccion_lograda']:.0%}; pedido {porcentaje_cobertura:.0%}). Propuesta de capacidad "
                      f"del local, no solo del stock actual: {len(vacios)} racks quedan vacíos como capacidad disponible.")
        if info_cobertura["fraccion_lograda"] < porcentaje_cobertura - 0.05:
            avisos.append("No se alcanzó el área pedida: se agotaron el presupuesto o los lugares compatibles "
                          "(pasillos mínimos, salidas, despejes de ingreso y zonas prohibidas).")

    # Diseño final: distancias reales con los racks instalados
    avance(0.92, "Midiendo distancias reales con los racks instalados…")
    estantes_final = existentes + [estante_de[m] for m in (candidatos["id"] if len(candidatos) else []) if m in instalados]
    local_final = dr.local_con_estantes(local, estantes_final)
    posiciones_final = medir_distancias(generar_posiciones(local_final, parametros, ajustes), local_final, modo)
    posiciones_final = calcular_costos_posiciones(posiciones_final.assign(modulo=posiciones_final["estante"]), pesos,
                                                  perfil_id, ajustes)
    pares_final, motivos_final, validas_final = pares_factibles(productos, posiciones_final, parametros, local_final, modo, ajustes)
    indice_final = {p: j for j, p in validas_final["id_posicion"].items()}
    claves = set(zip(pares_final["i"], pares_final["j"]))

    def traducir(asig):
        resultado = {}
        for i, j in asig.items():
            nuevo = indice_final.get(validas.at[j, "id_posicion"])
            if nuevo is not None and (i, nuevo) in claves:
                resultado[i] = nuevo
        return resultado
    asignacion_final = traducir(asignacion)
    perdidos = len(asignacion) - len(asignacion_final)
    if perdidos:
        avisos.append(f"{perdidos} productos no pasaron la revisión final de su posición y quedaron sin ubicar.")
    motivos_todos = dict(motivos)
    motivos_todos.update(motivos_final)
    ubicaciones = tabla_ubicaciones(asignacion_final, productos, pares_final, validas_final, motivos_todos)
    faltante = explicar_faltante(ubicaciones, productos, validas_final, local_final, ajustes)
    compra = dr.lista_de_compra(estantes_final)
    inversion = float(compra["subtotal"].sum()) if len(compra) else 0.0
    costo_anual_total = sum(float(e.get("precio_soles", 0) + e.get("montaje_soles", 0)) / max(float(e.get("vida_util_anios") or 1), 1)
                            for e in estantes_final if not e.get("existente"))
    solucion = dict(solucion_modelo)
    solucion.update({
        "asignacion": asignacion_final, "asignacion_heuristica": traducir(asignacion_heuristica),
        "tiempo_s": round(time.time() - inicio, 1), "pares_totales": len(pares), "productos": productos, "pares": pares_final,
        "validas": validas_final, "posiciones": posiciones_final, "motivos": motivos_todos, "ubicaciones": ubicaciones,
        "modo": modo, "faltante": faltante, "local": local_final, "modo_diseno": modo_diseno, "lambda": lam,
        "lista_compra": compra, "tabla_diseno": dr.tabla_diseno(estantes_final), "inversion_racks": round(inversion, 2),
        "costo_anualizado_racks": round(costo_anual_total, 2), "presupuesto": presupuesto,
        "candidatos": int(len(candidatos)), "info_candidatos": info, "avisos_diseno": avisos,
        "modulos_nuevos": len(estantes_final) - len(existentes), "modulos_existentes": len(existentes),
        "factible": faltante is None, "rapido": rapido, "cobertura": info_cobertura,
        "modulos_vacios": sorted(vacios),
        "alternativas": alternativas_si_falta(faltante, local_final, parametros, tipos, estantes_final, presupuesto, ajustes),
    })
    if faltante is not None and presupuesto is not None and inversion >= presupuesto * 0.98:
        solucion["faltante"]["texto"] += f" El presupuesto máximo (S/ {presupuesto:,.0f}) se agotó."
    avance(1.0, "Listo.")
    return solucion
