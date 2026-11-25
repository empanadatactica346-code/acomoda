"""Diseño de racks (Cambio 1).

Este módulo NO es otro modelo de optimización: aplica reglas geométricas para preparar los
datos del único modelo (modelo_optimo.py):

  1. Catálogo de tipos de rack (configuracion/catalogo_racks.json), editable en pantalla.
  2. Módulos candidatos: dónde PODRÍA ir cada tipo de rack, en 0° y 90° (frente hacia los
     cuatro lados), sobre una cuadrícula de 50 cm. Un candidato que choca con una columna,
     tapa una puerta, una salida, un extintor o un tablero, invade una zona funcional, o que
     deja un pasillo menor al mínimo NO SE GENERA.
  3. Conflictos: pares de candidatos que no pueden instalarse juntos (se solapan o uno tapa
     el pasillo del otro). El modelo los respeta con z[m] + z[m'] ≤ 1.
  4. Posiciones de cada candidato (nivel × tramo), con su distancia caminando al despacho.
  5. Selección inicial por heurística (la "propuesta rápida" y el arranque en caliente).
"""

import copy
import math

import numpy as np
import pandas as pd

from modulos.comun import CARPETA_CONFIGURACION, a_numero, cargar_ajustes, cargar_json, guardar_json
from modulos.interpretar_local import (OBSTACULOS_SOLIDOS, Grilla, altura_maxima_mercaderia, ampliar,
                                       ancho_pasillo_requerido, contorno, frente_estante, huella_estante,
                                       huella_obstaculo, niveles_estante, punto_origen, rect, rect_frente, rect_tramo,
                                       se_cruzan)

RUTA_CATALOGO_RACKS = CARPETA_CONFIGURACION / "catalogo_racks.json"
ROTULO_PRECIOS = "valores típicos, confirmar con el proveedor"
COLUMNAS_TIPO = ["id", "nombre", "uso", "largo_m", "fondo_m", "alto_m", "niveles", "alturas_niveles_m",
                 "capacidad_kg_nivel", "equipo", "precio_soles", "montaje_soles", "vida_util_anios",
                 "permite_peligrosos", "disponible"]
NUMERICAS = ["largo_m", "fondo_m", "alto_m", "niveles", "capacidad_kg_nivel", "precio_soles", "montaje_soles",
             "vida_util_anios"]
EQUIPOS_MECANICOS = {"transpaleta", "apilador", "montacargas"}


# --------------------------------------------------------------------------------------
# 1. Catálogo de racks
# --------------------------------------------------------------------------------------

def cargar_catalogo_racks():
    """Tabla (DataFrame) con los tipos de rack del archivo de configuración."""
    datos = cargar_json(RUTA_CATALOGO_RACKS)
    return pd.DataFrame(datos["tipos"], columns=COLUMNAS_TIPO)


def validar_tipos(tabla):
    """Devuelve (tabla_limpia, errores). Un tipo con medidas o precios inválidos no se usa."""
    errores = []
    filas = []
    vistos = set()
    for numero, fila in enumerate(tabla.to_dict("records"), start=1):
        identificador = str(fila.get("id") or "").strip()
        if not identificador:
            if any(str(v).strip() not in ("", "None", "nan") for v in fila.values()):
                errores.append(f"Fila {numero}: falta el identificador del tipo.")
            continue
        if identificador in vistos:
            errores.append(f"Tipo {identificador}: identificador repetido.")
            continue
        vistos.add(identificador)
        limpio = dict(fila, id=identificador)
        for columna in NUMERICAS:
            valor = a_numero(fila.get(columna))
            if valor is None or valor < 0 or (valor == 0 and columna not in ("precio_soles", "montaje_soles")):
                errores.append(f"Tipo {identificador}: «{columna}» debe ser un número mayor que 0.")
                valor = None
            limpio[columna] = valor
        if any(limpio[c] is None for c in NUMERICAS):
            continue
        limpio["niveles"] = int(limpio["niveles"])
        limpio["nombre"] = str(fila.get("nombre") or identificador)
        limpio["uso"] = str(fila.get("uso") or "almacen")
        limpio["equipo"] = "mecanico" if str(fila.get("equipo") or "").lower().startswith("mec") else "manual"
        limpio["permite_peligrosos"] = "si" if str(fila.get("permite_peligrosos")).lower() in ("si", "sí", "true") else "no"
        limpio["disponible"] = bool(fila.get("disponible")) and str(fila.get("disponible")).lower() not in ("false", "no", "0")
        limpio["alturas_niveles_m"] = "" if fila.get("alturas_niveles_m") in (None, "nan") else str(fila.get("alturas_niveles_m"))
        filas.append(limpio)
    return pd.DataFrame(filas, columns=COLUMNAS_TIPO), errores


def guardar_catalogo_racks(tabla):
    """Guarda la tabla editada (solo las filas válidas). Devuelve la lista de errores."""
    limpia, errores = validar_tipos(tabla)
    datos = cargar_json(RUTA_CATALOGO_RACKS)
    datos["tipos"] = limpia.to_dict("records")
    guardar_json(datos, RUTA_CATALOGO_RACKS)
    return errores


def altura_disponible(local, parametros, ajustes=None):
    """Altura máxima de un rack: altura libre menos la holgura de techo (luminarias) y el despeje de rociadores."""
    ajustes = ajustes or cargar_ajustes()
    holgura = ajustes["diseno"]["holgura_techo_m"]
    return round(min(float(local.get("altura_libre_m") or 3.0) - holgura, altura_maxima_mercaderia(local, parametros)), 3)


def tipos_utilizables(tabla, local, parametros, ajustes=None):
    """Tipos permitidos para este local. Ajusta los que superan la altura disponible (quita niveles
    de arriba) y descarta los que piden equipo mecánico si el local trabaja a mano.
    Devuelve (lista de diccionarios, avisos)."""
    from modulos.cargar_local import preferencias_de
    ajustes = ajustes or cargar_ajustes()
    preferencias = preferencias_de(local)
    limpia, errores = validar_tipos(tabla)
    avisos = list(errores)
    permitidos = set(preferencias.get("tipos_permitidos") or [])
    mecanico = preferencias.get("equipo_manipulacion") == "mecanico" or bool(
        {e.get("tipo") for e in local.get("equipos", [])} & EQUIPOS_MECANICOS)
    maximo = altura_disponible(local, parametros, ajustes)
    primer = ajustes["geometria"]["altura_primer_nivel_m"]
    tipos = []
    for tipo in limpia.to_dict("records"):
        if not tipo["disponible"] or (permitidos and tipo["id"] not in permitidos):
            continue
        if tipo["equipo"] == "mecanico" and not mecanico:
            avisos.append(f"{tipo['nombre']}: necesita equipo mecánico y el local trabaja a mano; no se usa.")
            continue
        if tipo["alto_m"] > maximo + 1e-6:
            alto_nivel = (tipo["alto_m"] - primer) / tipo["niveles"]
            niveles = int(math.floor((maximo - primer) / alto_nivel + 1e-9))
            if niveles < 1:
                avisos.append(f"{tipo['nombre']}: no entra bajo la altura disponible de {maximo:.2f} m; no se usa.")
                continue
            avisos.append(f"{tipo['nombre']}: mide {tipo['alto_m']:.2f} m y la altura disponible es {maximo:.2f} m "
                          f"(altura libre menos holgura de techo y rociadores): se usa con {niveles} niveles.")
            tipo = dict(tipo, niveles=niveles, alto_m=round(primer + niveles * alto_nivel, 3), alturas_niveles_m="")
        tipo["costo_inversion"] = float(tipo["precio_soles"] + tipo["montaje_soles"])
        tipo["costo_anualizado"] = tipo["costo_inversion"] / max(float(tipo["vida_util_anios"]), 1.0)
        tipos.append(tipo)
    if not tipos:
        avisos.append("No hay ningún tipo de rack utilizable: marque al menos un tipo como disponible en el catálogo.")
    return tipos, avisos


# --------------------------------------------------------------------------------------
# 2. Módulos candidatos
# --------------------------------------------------------------------------------------

def _cruza(x0, y0, x1, y1, b, tolerancia=0.005):
    """Vector booleano: ¿cada rectángulo (x0..x1, y0..y1) se cruza con el rectángulo b?"""
    return (x0 < b[2] - tolerancia) & (b[0] < x1 - tolerancia) & (y0 < b[3] - tolerancia) & (b[1] < y1 - tolerancia)


def zonas_prohibidas(local, parametros, ajustes=None):
    """Rectángulos donde NO se puede poner un rack y rectángulos que tampoco pueden cubrir los pasillos."""
    ajustes = ajustes or cargar_ajustes()
    requerido = ancho_pasillo_requerido_diseno(local, parametros, ajustes)
    solidos = [huella_obstaculo(o) for o in local.get("obstaculos", []) if o["tipo"] in OBSTACULOS_SOLIDOS]
    existentes = [ampliar(huella_estante(e), 0.02) for e in local.get("estantes", [])]
    margenes = {"salida_emergencia": parametros.get("despeje_salida_m") or 0.0,
                "extintor": parametros.get("despeje_extintor_m") or 0.0,
                "tablero": parametros.get("despeje_tablero_m") or 0.0,
                "puerta": ajustes["geometria"]["despeje_puerta_m"]}
    despejes = [ampliar(huella_obstaculo(o), margenes[o["tipo"]]) for o in local.get("obstaculos", []) if o["tipo"] in margenes]
    funcionales = [rect(z["x_m"], z["y_m"], z["largo_m"], z["ancho_m"]) for z in local.get("zonas", [])
                   if z.get("tipo") in ajustes["diseno"]["zonas_sin_racks"]]
    # Zona de entrada libre para los clientes: ningún rack a menos de despeje_ingreso_m del ingreso, la caja o una puerta
    despeje_ingreso = float(ajustes["diseno"].get("despeje_ingreso_m", 0.0) or 0.0)
    entradas = [ampliar(rect(z["x_m"], z["y_m"], z["largo_m"], z["ancho_m"]), despeje_ingreso) for z in local.get("zonas", [])
                if z.get("tipo") in ("ingreso", "caja")]
    entradas += [ampliar(huella_obstaculo(o), despeje_ingreso) for o in local.get("obstaculos", []) if o["tipo"] == "puerta"]
    funcionales += entradas if despeje_ingreso > 0 else []
    pasillos_existentes = [rect_frente(e, 0.02, float(e["largo_m"]) - 0.02, requerido) for e in local.get("estantes", [])]
    return {"huella": solidos + existentes + despejes + funcionales + pasillos_existentes, "pasillo": solidos + existentes,
            "requerido": requerido}


def ancho_pasillo_requerido_diseno(local, parametros, ajustes=None):
    """Ancho mínimo del pasillo frente a cada rack: norma, usos declarados y equipo (radio de giro)."""
    from modulos.cargar_local import preferencias_de
    ajustes = ajustes or cargar_ajustes()
    requerido = ancho_pasillo_requerido(local, parametros)
    if preferencias_de(local).get("equipo_manipulacion") == "mecanico":
        requerido = max(requerido, ajustes["diseno"]["pasillo_equipo_mecanico_m"])
    for equipo in local.get("equipos", []):
        radio = a_numero(equipo.get("radio_giro_m")) or 0.0
        if radio > 0:
            requerido = max(requerido, 2 * radio)
    return round(requerido, 3)


def _malla(inicio, fin, paso):
    if fin < inicio - 1e-9:
        return np.array([])
    valores = np.arange(inicio, fin + 1e-9, paso)
    if len(valores) == 0 or fin - valores[-1] > 0.02:
        valores = np.append(valores, fin)  # pegado a la pared del fondo
    return np.round(valores, 3)


def _huella_y_pasillo(x, y, largo, fondo, orientacion, requerido):
    """Arreglos con la huella (x0, y0, x1, y1) y el pasillo frente al rack, según la orientación."""
    if orientacion in (0, 180):
        x0, y0, x1, y1 = x, y, x + largo, y + fondo
    else:
        x0, y0, x1, y1 = x, y, x + fondo, y + largo
    if orientacion == 0:
        pasillo = (x0, y0 - requerido, x1, y0)
    elif orientacion == 180:
        pasillo = (x0, y1, x1, y1 + requerido)
    elif orientacion == 90:
        pasillo = (x1, y0, x1 + requerido, y1)
    else:
        pasillo = (x0 - requerido, y0, x0, y1)
    return (x0, y0, x1, y1), pasillo


def _patron(huella, local):
    """Nombre del patrón: perimetral si la espalda toca un muro; si no, fila o isla."""
    x0, y0, x1, y1 = huella
    largo, ancho = float(local["largo_m"]), float(local["ancho_m"])
    if min(x0, y0) < 0.05 or x1 > largo - 0.05 or y1 > ancho - 0.05:
        return "perimetral"
    return "fila/isla"


def generar_candidatos(local, parametros, tipos, ajustes=None, avance=None):
    """Genera los módulos candidatos. Devuelve (candidatos DataFrame, conflictos array (k, 2), info dict).
    Cada candidato trae su 'estante' (diccionario igual al de un estante del local)."""
    ajustes = ajustes or cargar_ajustes()
    diseno = ajustes["diseno"]
    paso = diseno["paso_candidatos_m"]
    limite = diseno["limite_candidatos"]
    caja = contorno(local)
    prohibidas = zonas_prohibidas(local, parametros, ajustes)
    requerido = prohibidas["requerido"]
    grilla = Grilla(local)
    origen, _ = punto_origen(local)
    distancia_origen, _ = grilla.dijkstra(*origen)
    alcanzable = np.zeros_like(grilla.ocupada)
    for salida in [o for o in local.get("obstaculos", []) if o["tipo"] in ("salida_emergencia", "puerta")] or [None]:
        punto = origen if salida is None else (salida["x_m"] + salida["largo_m"] / 2, salida["y_m"] + salida["ancho_m"] / 2)
        distancia, _ = grilla.dijkstra(*punto)
        alcanzable |= np.isfinite(distancia)
    registros = []
    descartes = {"choca o invade una zona prohibida": 0, "pasillo menor al mínimo": 0, "sin acceso conectado a las salidas": 0}
    for tipo in tipos:
        for orientacion in (0, 180, 90, 270):
            ancho_x = tipo["largo_m"] if orientacion in (0, 180) else tipo["fondo_m"]
            ancho_y = tipo["fondo_m"] if orientacion in (0, 180) else tipo["largo_m"]
            xs = _malla(0.0, caja[2] - ancho_x, paso)
            ys = _malla(0.0, caja[3] - ancho_y, paso)
            if not len(xs) or not len(ys):
                continue
            X, Y = np.meshgrid(xs, ys)
            X, Y = X.ravel(), Y.ravel()
            (x0, y0, x1, y1), (ax0, ay0, ax1, ay1) = _huella_y_pasillo(X, Y, tipo["largo_m"], tipo["fondo_m"], orientacion, requerido)
            ok = np.ones(len(X), dtype=bool)
            for bloqueo in prohibidas["huella"]:
                ok &= ~_cruza(x0, y0, x1, y1, bloqueo)
            descartes["choca o invade una zona prohibida"] += int((~ok).sum())
            pasillo_ok = (ax0 >= caja[0] - 0.01) & (ay0 >= caja[1] - 0.01) & (ax1 <= caja[2] + 0.01) & (ay1 <= caja[3] + 0.01)
            for bloqueo in prohibidas["pasillo"]:
                pasillo_ok &= ~_cruza(ax0, ay0, ax1, ay1, bloqueo)
            descartes["pasillo menor al mínimo"] += int((ok & ~pasillo_ok).sum())
            ok &= pasillo_ok
            # Acceso: el centro del pasillo debe estar conectado con las salidas
            cx, cy = (ax0 + ax1) / 2, (ay0 + ay1) / 2
            columnas = np.clip((cx / grilla.resolucion).astype(int), 0, grilla.columnas - 1)
            filas = np.clip((cy / grilla.resolucion).astype(int), 0, grilla.filas - 1)
            conectado = alcanzable[filas, columnas]
            descartes["sin acceso conectado a las salidas"] += int((ok & ~conectado).sum())
            ok &= conectado
            distancia = distancia_origen[filas, columnas]
            for k in np.nonzero(ok)[0]:
                registros.append({"tipo": tipo["id"], "orientacion": orientacion, "x_m": float(X[k]), "y_m": float(Y[k]),
                                  "x0": float(x0[k]), "y0": float(y0[k]), "x1": float(x1[k]), "y1": float(y1[k]),
                                  "ax0": float(ax0[k]), "ay0": float(ay0[k]), "ax1": float(ax1[k]), "ay1": float(ay1[k]),
                                  "distancia_m": float(distancia[k]) if np.isfinite(distancia[k]) else 99.0})
    tabla = pd.DataFrame(registros)
    info = {"generados": len(tabla), "descartados": descartes, "reducidos": 0, "requerido_m": requerido, "paso_m": paso,
            "limite": limite, "aviso": ""}
    if not len(tabla):
        return tabla, np.zeros((0, 2), dtype=int), info
    por_tipo = {t["id"]: t for t in tipos}
    tabla["volumen_util_m3"] = [por_tipo[t]["largo_m"] * por_tipo[t]["fondo_m"] * (por_tipo[t]["alto_m"] - 0.1) for t in tabla["tipo"]]
    tabla["costo_inversion"] = [por_tipo[t]["costo_inversion"] for t in tabla["tipo"]]
    tabla["costo_anualizado"] = [por_tipo[t]["costo_anualizado"] for t in tabla["tipo"]]
    # Calidad (menor = mejor): SOLO aprovechamiento. Volumen por sol invertido y espalda apoyada contra un muro.
    # La distancia al despacho NO decide dónde van los racks: solo se usa después para asignar productos.
    eficiencia = tabla["volumen_util_m3"] / tabla["costo_anualizado"].clip(lower=1e-6)
    espalda_muro = [_patron((r.x0, r.y0, r.x1, r.y1), local) == "perimetral" for r in tabla.itertuples()]
    tabla["calidad"] = (-eficiencia / max(eficiencia.max(), 1e-9) - 0.5 * np.array(espalda_muro, dtype=float)).round(5)
    if len(tabla) > limite:
        # Recorte uniforme: por turnos, el mejor candidato de cada celda de 2 × 2 m, así sobreviven en todo el local
        tabla["_celda"] = (tabla["x0"] // 2).astype(int).astype(str) + "_" + (tabla["y0"] // 2).astype(int).astype(str)
        tabla = tabla.sort_values("calidad")
        tabla["_turno"] = tabla.groupby("_celda").cumcount()
        tabla = tabla.sort_values(["_turno", "calidad"]).head(limite).drop(columns=["_celda", "_turno"])
        info["reducidos"] = info["generados"] - limite
        info["aviso"] = (f"Se generaron {info['generados']:,} candidatos; se conservaron {limite:,} repartidos de forma "
                         "uniforme por todo el local (los de mejor aprovechamiento de cada zona de 2 × 2 m).")
    tabla = tabla.sort_values(["calidad"]).reset_index(drop=True)
    tabla["id"] = [f"M{k + 1:04d}" for k in range(len(tabla))]
    tabla["patron"] = [_patron((r.x0, r.y0, r.x1, r.y1), local) for r in tabla.itertuples()]
    tabla["estante"] = [_estante_de_candidato(r, por_tipo[r.tipo]) for r in tabla.itertuples()]
    if avance:
        avance(0.1, f"{len(tabla):,} módulos candidatos; calculando conflictos…")
    conflictos = calcular_conflictos(tabla)
    info["conflictos"] = int(len(conflictos))
    return tabla, conflictos, info


def _estante_de_candidato(fila, tipo):
    return {"id": fila.id, "tipo": tipo["id"], "x_m": round(fila.x_m, 3), "y_m": round(fila.y_m, 3),
            "largo_m": tipo["largo_m"], "fondo_m": tipo["fondo_m"], "alto_m": tipo["alto_m"], "niveles": int(tipo["niveles"]),
            "alturas_niveles_m": tipo.get("alturas_niveles_m") or "", "capacidad_kg_nivel": tipo["capacidad_kg_nivel"],
            "orientacion": int(fila.orientacion), "costo_soles": tipo["precio_soles"], "zona_controlada": "no",
            "permite_peligrosos": tipo.get("permite_peligrosos", "no"), "estimado": False, "existente": False,
            "tipo_rack": tipo["nombre"], "precio_soles": tipo["precio_soles"], "montaje_soles": tipo["montaje_soles"],
            "vida_util_anios": tipo["vida_util_anios"], "patron": getattr(fila, "patron", "")}


def calcular_conflictos(tabla):
    """Pares (a, b) de candidatos incompatibles: sus huellas se cruzan o uno tapa el pasillo del otro."""
    if len(tabla) < 2:
        return np.zeros((0, 2), dtype=int)
    t = 0.005
    H = tabla[["x0", "y0", "x1", "y1"]].to_numpy()
    P = tabla[["ax0", "ay0", "ax1", "ay1"]].to_numpy()

    def cruces(A, B):
        return ((A[:, None, 0] < B[None, :, 2] - t) & (B[None, :, 0] < A[:, None, 2] - t) &
                (A[:, None, 1] < B[None, :, 3] - t) & (B[None, :, 1] < A[:, None, 3] - t))
    pares = []
    bloque = 400  # por bloques para no usar mucha memoria
    for inicio in range(0, len(H), bloque):
        h, p = H[inicio:inicio + bloque], P[inicio:inicio + bloque]
        matriz = cruces(h, H) | cruces(h, P) | cruces(p, H)
        a, b = np.nonzero(matriz)
        a = a + inicio
        mascara = a < b
        pares.append(np.stack([a[mascara], b[mascara]], axis=1))
    return np.concatenate(pares) if pares else np.zeros((0, 2), dtype=int)


# --------------------------------------------------------------------------------------
# 3. Posiciones de los módulos
# --------------------------------------------------------------------------------------

def posiciones_de_candidatos(candidatos, local, parametros, grilla=None, distancia_origen=None, distancia_ingreso=None,
                             ajustes=None, modo="almacen"):
    """Posiciones (nivel × tramo) de todos los candidatos con su distancia caminando (sin bloquear por
    otros candidatos: el modelo aún no sabe cuáles se instalan; la distancia real se recalcula al final)."""
    ajustes = ajustes or cargar_ajustes()
    ancho_tramo = ajustes["geometria"]["ancho_tramo_m"]
    altura_max = altura_maxima_mercaderia(local, parametros)
    altura_min_piso = parametros.get("altura_minima_piso_m") or 0.0
    if grilla is None:
        grilla = Grilla(local)
        origen, _ = punto_origen(local, modo)
        distancia_origen, _ = grilla.dijkstra(*origen)
        ingreso = next(((z["x_m"] + z["largo_m"] / 2, z["y_m"] + z["ancho_m"] / 2)
                        for z in local.get("zonas", []) if z.get("tipo") == "ingreso"), origen)
        distancia_ingreso, _ = grilla.dijkstra(*ingreso)
    controladas = [rect(z["x_m"], z["y_m"], z["largo_m"], z["ancho_m"]) for z in local.get("zonas", []) if z.get("tipo") == "controlada"]
    filas = []
    for estante in candidatos["estante"]:
        largo = float(estante["largo_m"])
        tramos = max(1, int(round(largo / ancho_tramo)))
        ancho = largo / tramos
        huella = huella_estante(estante)
        controlado = any(se_cruzan(huella, z) for z in controladas)
        fx, fy, (dx, dy), (nx, ny) = frente_estante(estante)
        for numero_nivel, (base, alto_libre) in enumerate(niveles_estante(estante, ajustes), start=1):
            motivo = []
            if base + alto_libre > altura_max + 1e-6:
                motivo.append(f"supera la altura máxima de {altura_max:.2f} m")
            if base < altura_min_piso - 1e-6:
                motivo.append(f"está a menos de {altura_min_piso:.2f} m del piso")
            for numero_tramo in range(1, tramos + 1):
                desde, hasta = (numero_tramo - 1) * ancho, numero_tramo * ancho
                h = rect_tramo(estante, desde, hasta)
                medio = (desde + hasta) / 2
                filas.append({
                    "id_posicion": f"{estante['id']}-N{numero_nivel}-T{numero_tramo}", "estante": estante["id"],
                    "modulo": estante["id"], "tipo_estante": estante["tipo"], "nivel": numero_nivel, "tramo": numero_tramo,
                    "tramos_estante": tramos, "niveles_estante": int(estante["niveles"]), "ancho_m": round(ancho, 4),
                    "fondo_m": float(estante["fondo_m"]), "alto_libre_m": alto_libre, "base_m": base,
                    "altura_centro_m": round(base + alto_libre / 2, 3), "capacidad_kg_nivel": float(estante["capacidad_kg_nivel"]),
                    "x0": h[0], "y0": h[1], "x1": h[2], "y1": h[3],
                    "x_acceso": round(fx + dx * medio + nx * 0.45, 3), "y_acceso": round(fy + dy * medio + ny * 0.45, 3),
                    "zona_controlada": controlado, "permite_peligrosos": estante.get("permite_peligrosos") == "si",
                    "cabecera": numero_tramo in (1, tramos), "valida": not motivo, "motivo_eliminacion": "; ".join(motivo)})
    tabla = pd.DataFrame(filas)
    if not len(tabla):
        return tabla
    columnas = np.clip((tabla["x_acceso"] / grilla.resolucion).astype(int), 0, grilla.columnas - 1).to_numpy()
    filas_g = np.clip((tabla["y_acceso"] / grilla.resolucion).astype(int), 0, grilla.filas - 1).to_numpy()
    for nombre, matriz in (("distancia_m", distancia_origen), ("distancia_ingreso_m", distancia_ingreso)):
        valores = matriz[filas_g, columnas]
        tabla[nombre] = np.round(np.where(np.isfinite(valores), valores, 99.0), 2)
    return tabla


# --------------------------------------------------------------------------------------
# 4. Selección inicial (heurística)
# --------------------------------------------------------------------------------------

def demanda_volumen(productos, ajustes=None):
    """Volumen de estantería necesario (m³) para el stock a ubicar, con un factor de llenado realista."""
    ajustes = ajustes or cargar_ajustes()
    volumen = float((productos["m_cantidad"] * productos["m_largo"] * productos["m_ancho"] * productos["m_alto"]).sum() / 1e6)
    return volumen / ajustes["diseno"]["factor_llenado"]


def seleccionar_modulos(candidatos, conflictos, volumen_objetivo, presupuesto=None, lam=0.5, ya_elegidos=(), excluir=()):
    """Elige, en orden de calidad, candidatos que no choquen entre sí hasta cubrir el volumen objetivo
    o agotar el presupuesto. Devuelve la lista de índices elegidos (incluye `ya_elegidos`)."""
    if not len(candidatos):
        return list(ya_elegidos)
    vecinos = {}
    for a, b in conflictos:
        vecinos.setdefault(int(a), set()).add(int(b))
        vecinos.setdefault(int(b), set()).add(int(a))
    distancia = candidatos["distancia_m"] / max(candidatos["distancia_m"].max(), 1e-6)
    costo_volumen = candidatos["costo_anualizado"] / candidatos["volumen_util_m3"].clip(lower=1e-6)
    puntaje = distancia + lam * costo_volumen / max(costo_volumen.max(), 1e-9)
    elegidos = list(ya_elegidos)
    bloqueados = set(excluir)
    for k in elegidos:
        bloqueados |= vecinos.get(k, set())
    volumen = float(candidatos.loc[elegidos, "volumen_util_m3"].sum()) if elegidos else 0.0
    gasto = float(candidatos.loc[elegidos, "costo_inversion"].sum()) if elegidos else 0.0
    for k in puntaje.sort_values().index:
        if volumen >= volumen_objetivo:
            break
        if k in bloqueados or k in elegidos:
            continue
        costo = float(candidatos.at[k, "costo_inversion"])
        if presupuesto is not None and gasto + costo > presupuesto + 1e-6:
            continue
        elegidos.append(int(k))
        bloqueados |= vecinos.get(int(k), set())
        volumen += float(candidatos.at[k, "volumen_util_m3"])
        gasto += costo
    return elegidos


def area_util(local, parametros, ajustes=None, resolucion=0.1):
    """Área útil (m²): contorno del local menos zonas prohibidas, funcionales, despejes y obstáculos sólidos."""
    ajustes = ajustes or cargar_ajustes()
    caja = contorno(local)
    columnas = max(1, int(round((caja[2] - caja[0]) / resolucion)))
    filas = max(1, int(round((caja[3] - caja[1]) / resolucion)))
    ocupada = np.zeros((filas, columnas), dtype=bool)
    for r in zonas_prohibidas(local, parametros, ajustes)["huella"]:
        c0, c1 = int(max(0, math.floor(r[0] / resolucion))), int(min(columnas, math.ceil(r[2] / resolucion)))
        f0, f1 = int(max(0, math.floor(r[1] / resolucion))), int(min(filas, math.ceil(r[3] / resolucion)))
        if c1 > c0 and f1 > f0:
            ocupada[f0:f1, c0:c1] = True
    return round(float((~ocupada).sum()) * resolucion * resolucion, 3)


def _franja_espalda(tabla, grosor=0.06):
    """Franja delgada detrás de cada candidato (lado opuesto al pasillo): sirve para saber si la espalda se apoya."""
    x0, y0, x1, y1 = (tabla[c].to_numpy() for c in ("x0", "y0", "x1", "y1"))
    o = tabla["orientacion"].to_numpy() if "orientacion" in tabla else np.zeros(len(tabla))
    bx0 = np.where(o == 90, x0 - grosor, np.where(o == 270, x1, x0))
    bx1 = np.where(o == 90, x0, np.where(o == 270, x1 + grosor, x1))
    by0 = np.where(o == 0, y1, np.where(o == 180, y0 - grosor, y0))
    by1 = np.where(o == 0, y1 + grosor, np.where(o == 180, y0, y1))
    return bx0 + 0.01, by0 + 0.01, bx1 - 0.01, by1 - 0.01


def seleccionar_modulos_cobertura(candidatos, conflictos, area_util_m2, porcentaje, presupuesto=None, ya_elegidos=(),
                                  excluir=(), volumen_objetivo=0.0):
    """Modo «llenar todo el local»: agrega módulos compatibles, repartidos por todo el local, hasta que la suma de
    huellas (largo × fondo) alcance porcentaje × área útil, o se agote el presupuesto o los candidatos.

    Orden: un módulo por celda de 2 × 2 m por turnos (el mejor de cada celda primero, como en generar_candidatos),
    primero el patrón perimetral y luego filas/islas. Se prefieren los candidatos con la espalda apoyada (contra un
    muro o espalda con espalda con otro rack ya elegido), así cada pasillo sirve a dos frentes y el área se aprovecha.
    Los conflictos (choques y pasillos tapados) se respetan igual que en seleccionar_modulos.
    volumen_objetivo: si el stock necesita más volumen que el área pedida, se sigue agregando hasta cubrirlo.
    Devuelve la lista de índices elegidos (incluye `ya_elegidos`)."""
    if not len(candidatos):
        return list(ya_elegidos)
    vecinos = {}
    for a, b in conflictos:
        vecinos.setdefault(int(a), set()).add(int(b))
        vecinos.setdefault(int(b), set()).add(int(a))
    tabla = candidatos.copy()
    tabla["huella_m2"] = (tabla["x1"] - tabla["x0"]) * (tabla["y1"] - tabla["y0"])
    patron = tabla["patron"] if "patron" in tabla else pd.Series("fila/isla", index=tabla.index)
    tabla["_rango"] = np.where(patron == "perimetral", 0, 1)
    tabla["_celda"] = (tabla["x0"] // 2).astype(int).astype(str) + "_" + (tabla["y0"] // 2).astype(int).astype(str)
    tabla = tabla.sort_values(["_rango", "calidad"])
    tabla["_turno"] = tabla.groupby(["_rango", "_celda"]).cumcount()
    tabla = tabla.sort_values(["_rango", "_turno", "calidad"])
    indices = tabla.index.to_numpy()
    posicion_de = {k: n for n, k in enumerate(indices)}
    H = tabla[["x0", "y0", "x1", "y1"]].to_numpy()
    bx0, by0, bx1, by1 = _franja_espalda(tabla)
    # Espalda contra un muro: la franja de atrás sale del local
    xmin, ymin, xmax, ymax = H[:, 0].min(), H[:, 1].min(), H[:, 2].max(), H[:, 3].max()
    apoyada = (bx0 < xmin) | (by0 < ymin) | (bx1 > xmax) | (by1 > ymax)
    # Franjas a los costados: un rack al lado, con la misma orientación, continúa la fila
    orient = tabla["orientacion"].to_numpy() if "orientacion" in tabla else np.zeros(len(tabla))
    horizontal = np.isin(orient, (0, 180))
    sx0 = np.where(horizontal, H[:, 0] - 0.06, H[:, 0] + 0.01)
    sx1 = np.where(horizontal, H[:, 2] + 0.06, H[:, 2] - 0.01)
    sy0 = np.where(horizontal, H[:, 1] + 0.01, H[:, 1] - 0.06)
    sy1 = np.where(horizontal, H[:, 3] - 0.01, H[:, 3] + 0.06)
    en_fila = np.zeros(len(indices), dtype=bool)
    libre = np.ones(len(indices), dtype=bool)
    costo = tabla["costo_inversion"].to_numpy(dtype=float)
    huella = tabla["huella_m2"].to_numpy(dtype=float)
    objetivo = max(0.0, float(porcentaje)) * float(area_util_m2)
    elegidos = list(ya_elegidos)
    cubierta, gasto, volumen = 0.0, 0.0, 0.0
    volumenes = tabla["volumen_util_m3"].to_numpy(dtype=float) if "volumen_util_m3" in tabla else np.zeros(len(tabla))

    def tomar(k):
        nonlocal cubierta, gasto, volumen
        n = posicion_de.get(k)
        bloqueados = [posicion_de[v] for v in vecinos.get(k, ()) if v in posicion_de]
        libre[bloqueados] = False
        if n is None:
            return
        libre[n] = False
        cubierta += huella[n]
        gasto += costo[n]
        volumen += volumenes[n]
        h = H[n]
        apoyada[(bx0 < h[2]) & (h[0] < bx1) & (by0 < h[3]) & (h[1] < by1)] = True
        en_fila[(sx0 < h[2]) & (h[0] < sx1) & (sy0 < h[3]) & (h[1] < sy1) & (orient == orient[n])] = True

    for k in excluir:
        if k in posicion_de:
            libre[posicion_de[k]] = False
    for k in elegidos:
        tomar(int(k))
    while cubierta < objetivo or volumen < volumen_objetivo:
        disponibles = libre.copy()
        if presupuesto is not None:
            disponibles &= gasto + costo <= presupuesto + 1e-6
        if not disponibles.any():
            break
        n = None
        for preferidos in (disponibles & apoyada & en_fila, disponibles & apoyada, disponibles & en_fila, disponibles):
            if preferidos.any():
                n = int(np.argmax(preferidos))
                break
        k = int(indices[n])
        elegidos.append(k)
        tomar(k)
    return elegidos


def lista_de_compra(estantes_instalados):
    """Tabla de compra: un renglón por tipo de rack nuevo con cantidad y costo (precios referenciales)."""
    nuevos = [e for e in estantes_instalados if not e.get("existente")]
    if not nuevos:
        return pd.DataFrame(columns=["tipo", "nombre", "cantidad", "precio_unitario", "montaje_unitario", "subtotal", "nota"])
    tabla = pd.DataFrame([{"tipo": e["tipo"], "nombre": e.get("tipo_rack", e["tipo"]), "precio": float(e.get("precio_soles") or 0),
                           "montaje": float(e.get("montaje_soles") or 0)} for e in nuevos])
    compra = tabla.groupby(["tipo", "nombre"]).agg(cantidad=("precio", "size"), precio_unitario=("precio", "first"),
                                                   montaje_unitario=("montaje", "first")).reset_index()
    compra["subtotal"] = compra["cantidad"] * (compra["precio_unitario"] + compra["montaje_unitario"])
    compra["nota"] = ROTULO_PRECIOS
    vacios = tabla.assign(vacio=[bool(e.get("vacio")) for e in nuevos]).groupby(["tipo", "nombre"])["vacio"].sum()
    if vacios.any():
        compra["vacios_capacidad_disponible"] = [int(vacios.get((t, n), 0)) for t, n in zip(compra["tipo"], compra["nombre"])]
    return compra


def tabla_diseno(estantes_instalados):
    """Diseño de racks: qué tipo, dónde y con qué orientación."""
    filas = []
    for e in estantes_instalados:
        x0, y0, x1, y1 = huella_estante(e)
        filas.append({"modulo": e["id"], "tipo": e.get("tipo_rack") or e["tipo"], "origen": "existente" if e.get("existente") else "nuevo",
                      "x_m": e["x_m"], "y_m": e["y_m"], "huella": f"{x1 - x0:.2f} × {y1 - y0:.2f} m",
                      "alto_m": e["alto_m"], "niveles": e["niveles"], "capacidad_kg_nivel": e["capacidad_kg_nivel"],
                      "orientacion": e["orientacion"], "patron": e.get("patron", ""),
                      "estado": "capacidad disponible" if e.get("vacio") else "con productos"})
    return pd.DataFrame(filas)


def local_con_estantes(local, estantes):
    nuevo = copy.deepcopy(local)
    nuevo["estantes"] = [dict(e) for e in estantes]
    return nuevo
