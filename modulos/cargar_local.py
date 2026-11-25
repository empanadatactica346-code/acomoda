"""Lee el local desde la plantilla Excel, un archivo DXF o los trazos hechos sobre una
imagen/PDF, y lo deja en un solo formato (un diccionario) que usa el resto del programa.

Todas las medidas del local están en METROS. El origen (0,0) es la esquina inferior
izquierda del plano; X crece a la derecha y Y hacia arriba.
"""

import copy
import io
import tempfile
from pathlib import Path

import pandas as pd

from modulos.comun import a_numero, a_si_no, cargar_ajustes, vacio
from modulos.plantillas import HOJAS_LOCAL, validar_plantilla

# Capas DXF que se reconocen por su nombre (sin tildes, en mayúsculas)
CAPAS_CONOCIDAS = {
    "CONTORNO": "contorno", "LOCAL": "contorno", "MUROS": "muro", "MURO": "muro", "PAREDES": "muro",
    "COLUMNAS": "columna", "COLUMNA": "columna", "PUERTAS": "puerta", "PUERTA": "puerta",
    "ESTANTES": "estante", "ESTANTE": "estante", "ESTANTERIA": "estante", "GONDOLAS": "estante", "RACKS": "estante",
    "ESCALERAS": "escalera", "ESCALERA": "escalera", "TABLEROS": "tablero", "TABLERO": "tablero",
    "EXTINTORES": "extintor", "EXTINTOR": "extintor", "SALIDAS": "salida_emergencia",
    "SALIDA": "salida_emergencia", "EVACUACION": "salida_emergencia", "LUMINARIAS": "luminaria",
    "ROCIADORES": "rociador", "DESPACHO": "zona_despacho", "RECEPCION": "zona_recepcion", "CAJA": "zona_caja",
}
TIPOS_CAPA = ["ignorar", "contorno", "muro", "columna", "puerta", "estante", "escalera", "tablero", "extintor",
              "salida_emergencia", "luminaria", "rociador", "zona_despacho", "zona_recepcion", "zona_caja", "zona_ingreso"]

# Colores de trazo para dibujar sobre imagen: cada tipo tiene su color
COLORES_TRAZO = {
    "contorno": "#000000", "estante": "#1f77b4", "columna": "#7f7f7f", "muro": "#8c564b",
    "puerta": "#2ca02c", "salida_emergencia": "#d62728", "extintor": "#ff0000", "tablero": "#ff7f0e",
    "escalera": "#9467bd", "zona_despacho": "#17becf", "zona_caja": "#bcbd22",
}

UNIDADES_DXF = {1: ("pulgadas", 0.0254), 2: ("pies", 0.3048), 4: ("milímetros", 0.001),
                5: ("centímetros", 0.01), 6: ("metros", 1.0)}


def local_vacio():
    return {"nombre": "", "largo_m": None, "ancho_m": None, "altura_libre_m": None,
            "capacidad_piso_kg_m2": None, "fuente": "excel", "es_ejemplo": False,
            "obstaculos": [], "zonas": [], "estantes": [], "equipos": [], "pasillos": [],
            "preferencias": preferencias_por_defecto(), "avisos_lectura": []}


def preferencias_por_defecto():
    """Modo de diseño A (desde cero), sin tope de presupuesto, todos los tipos disponibles, equipo manual."""
    return {"modo_diseno": "A", "presupuesto_max_soles": None, "tipos_permitidos": [], "acepta_comprar": "si",
            "equipo_manipulacion": "manual", "cobertura_total": False,
            "cobertura_porcentaje": float(cargar_ajustes()["diseno"].get("cobertura_defecto", 0.4))}


def preferencias_de(local):
    return dict(preferencias_por_defecto(), **(local.get("preferencias") or {}))


def _estante(id_, x, y, orientacion, tipo="gondola", largo=2.4, fondo=0.5, alto=2.0, niveles=5,
             capacidad=80, costo=450, controlada="no", peligrosos="no", alturas=""):
    return {"id": id_, "tipo": tipo, "x_m": x, "y_m": y, "largo_m": largo, "fondo_m": fondo, "alto_m": alto,
            "niveles": niveles, "alturas_niveles_m": alturas, "capacidad_kg_nivel": capacidad,
            "orientacion": orientacion, "costo_soles": costo, "zona_controlada": controlada,
            "permite_peligrosos": peligrosos, "estimado": False}


def local_de_ejemplo():
    """Local ficticio de 16 × 12 m para probar el programa. EJEMPLO, NO ES REAL."""
    local = local_vacio()
    local.update({"nombre": "EJEMPLO, NO ES REAL", "largo_m": 16.0, "ancho_m": 12.0, "altura_libre_m": 3.2,
                  "capacidad_piso_kg_m2": 500, "fuente": "ejemplo", "es_ejemplo": True})
    local["obstaculos"] = [
        {"id": "P1", "tipo": "puerta", "x_m": 6.5, "y_m": 0.0, "largo_m": 2.0, "ancho_m": 0.2, "alto_m": 2.4},
        {"id": "S1", "tipo": "salida_emergencia", "x_m": 15.8, "y_m": 5.5, "largo_m": 0.2, "ancho_m": 1.2, "alto_m": 2.2},
        {"id": "X1", "tipo": "extintor", "x_m": 0.0, "y_m": 5.0, "largo_m": 0.3, "ancho_m": 0.3, "alto_m": 1.5},
        {"id": "X2", "tipo": "extintor", "x_m": 15.7, "y_m": 8.0, "largo_m": 0.3, "ancho_m": 0.3, "alto_m": 1.5},
        {"id": "T1", "tipo": "tablero", "x_m": 0.0, "y_m": 9.5, "largo_m": 0.2, "ancho_m": 0.8, "alto_m": 1.8},
        {"id": "C1", "tipo": "columna", "x_m": 7.1, "y_m": 5.3, "largo_m": 0.4, "ancho_m": 0.4, "alto_m": 3.2},
        {"id": "C2", "tipo": "columna", "x_m": 7.1, "y_m": 7.7, "largo_m": 0.4, "ancho_m": 0.4, "alto_m": 3.2},
        {"id": "R1", "tipo": "rociador", "x_m": 4.0, "y_m": 6.0, "largo_m": 0.1, "ancho_m": 0.1, "alto_m": 3.1},
        {"id": "R2", "tipo": "rociador", "x_m": 11.0, "y_m": 6.0, "largo_m": 0.1, "ancho_m": 0.1, "alto_m": 3.1},
    ]
    local["zonas"] = [
        {"id": "Z1", "tipo": "despacho", "x_m": 0.3, "y_m": 0.3, "largo_m": 2.5, "ancho_m": 1.5},
        {"id": "Z2", "tipo": "ingreso", "x_m": 6.5, "y_m": 0.0, "largo_m": 2.0, "ancho_m": 1.2},
        {"id": "Z3", "tipo": "caja", "x_m": 9.5, "y_m": 0.3, "largo_m": 2.5, "ancho_m": 1.4},
        {"id": "Z4", "tipo": "recepcion", "x_m": 12.5, "y_m": 10.0, "largo_m": 3.2, "ancho_m": 1.8},
    ]
    estantes = []
    numero = 1
    columnas_x = [1.5, 3.9, 8.1, 10.5]
    # Tres góndolas dobles (dos estantes espalda con espalda) con pasillos de 1.4 m
    for y_base in (2.6, 5.0, 7.4):
        for y, orientacion in ((y_base, 0), (y_base + 0.5, 180)):
            for x in columnas_x:
                estantes.append(_estante(f"E{numero}", x, y, orientacion, alturas="0.42;0.36;0.33;0.33;0.33"))
                numero += 1
    # Fila pegada a la pared superior, mirando hacia abajo
    for x in (1.5, 3.9, 6.3, 8.7):
        estantes.append(_estante(f"E{numero}", x, 11.5, 0, tipo="estante_metalico", capacidad=120, alto=2.1,
                                 alturas="0.50;0.40;0.35;0.30;0.30", peligrosos="si" if x == 8.7 else "no"))
        numero += 1
    # Vitrina con llave junto a la caja: zona controlada
    estantes.append(_estante("V1", 12.5, 0.2, 180, tipo="vitrina", largo=1.8, fondo=0.5, alto=1.2,
                             niveles=3, capacidad=30, costo=900, controlada="si"))
    local["estantes"] = estantes
    local["equipos"] = [{"tipo": "manual", "radio_giro_m": 0.0, "altura_max_m": 1.9}]
    local["pasillos"] = [{"uso": "peatonal", "ancho_min_m": 0.9}, {"uso": "clientes", "ancho_min_m": 1.2},
                         {"uso": "evacuacion", "ancho_min_m": 1.2}]
    return local


# --------------------------------------------------------------------------------------
# Conversión entre el diccionario del local y las tablas de la plantilla
# --------------------------------------------------------------------------------------

def local_a_tablas(local):
    """Diccionario del local -> {hoja: DataFrame} con las columnas de la plantilla."""
    tablas = {}
    datos_local = {c["nombre"]: local.get(c["nombre"]) for c in HOJAS_LOCAL["LOCAL"]}
    datos_local["nombre_local"] = local.get("nombre", "")
    tablas["LOCAL"] = pd.DataFrame([datos_local])
    claves = {"OBSTACULOS": "obstaculos", "ZONAS": "zonas", "ESTANTES_EXISTENTES": "estantes", "EQUIPOS": "equipos",
              "PASILLOS": "pasillos"}
    preferencias = preferencias_de(local)
    preferencias["tipos_permitidos"] = ";".join(preferencias.get("tipos_permitidos") or [])
    preferencias["cobertura_total"] = "si" if preferencias.get("cobertura_total") else "no"
    preferencias["cobertura_porcentaje"] = round(float(preferencias.get("cobertura_porcentaje") or 0.4) * 100, 1)
    tablas["PREFERENCIAS_Y_PRESUPUESTO"] = pd.DataFrame([{c["nombre"]: preferencias.get(c["nombre"])
                                                          for c in HOJAS_LOCAL["PREFERENCIAS_Y_PRESUPUESTO"]}])
    for hoja, clave in claves.items():
        nombres = [c["nombre"] for c in HOJAS_LOCAL[hoja]]
        filas = [{n: fila.get(n) for n in nombres} for fila in local.get(clave, [])]
        tablas[hoja] = pd.DataFrame(filas, columns=nombres)
    return tablas


def tablas_a_local(tablas, fuente="excel"):
    """{hoja: DataFrame} -> diccionario del local (con valores ya convertidos)."""
    local = local_vacio()
    local["fuente"] = fuente
    if "LOCAL" in tablas and len(tablas["LOCAL"]):
        fila = tablas["LOCAL"].iloc[0].to_dict()
        local["nombre"] = "" if vacio(fila.get("nombre_local")) else str(fila.get("nombre_local"))
        for clave in ("largo_m", "ancho_m", "altura_libre_m", "capacidad_piso_kg_m2"):
            local[clave] = a_numero(fila.get(clave))
    claves = {"OBSTACULOS": "obstaculos", "ZONAS": "zonas", "ESTANTES_EXISTENTES": "estantes", "EQUIPOS": "equipos",
              "PASILLOS": "pasillos"}
    preferencias = tablas.get("PREFERENCIAS_Y_PRESUPUESTO")
    if preferencias is not None and len(preferencias):
        fila = preferencias.iloc[0].to_dict()
        modo = str(fila.get("modo_diseno") or "").strip().upper()
        tipos = "" if vacio(fila.get("tipos_permitidos")) else str(fila.get("tipos_permitidos"))
        local["preferencias"] = {
            "modo_diseno": modo if modo in ("A", "B", "C") else "A",
            "presupuesto_max_soles": a_numero(fila.get("presupuesto_max_soles")),
            "tipos_permitidos": [t.strip() for t in tipos.replace(",", ";").split(";") if t.strip()],
            "acepta_comprar": a_si_no(fila.get("acepta_comprar")) or "si",
            "equipo_manipulacion": "mecanico" if str(fila.get("equipo_manipulacion") or "").lower().startswith("mec") else "manual",
            "cobertura_total": a_si_no(fila.get("cobertura_total")) == "si"}
        porcentaje = a_numero(fila.get("cobertura_porcentaje"))
        if porcentaje is not None:
            porcentaje = porcentaje / 100 if porcentaje > 1 else porcentaje
            local["preferencias"]["cobertura_porcentaje"] = min(0.9, max(0.1, porcentaje))
        if local["preferencias"]["acepta_comprar"] == "no":
            local["preferencias"]["modo_diseno"] = "B"
    for hoja, clave in claves.items():
        tabla = tablas.get(hoja)
        if tabla is None:
            continue
        nombres = [c for c in HOJAS_LOCAL[hoja]]
        for fila in tabla.to_dict("records"):
            if all(vacio(fila.get(c["nombre"])) for c in nombres):
                continue
            registro = {}
            for col in nombres:
                valor = fila.get(col["nombre"])
                if col["tipo"] in ("numero", "numero_pos", "numero_no_neg", "entero_pos"):
                    valor = a_numero(valor)
                    if col["tipo"] == "entero_pos" and valor is not None:
                        valor = int(valor)
                elif col["tipo"] == "si_no":
                    valor = a_si_no(valor) or "no"
                elif vacio(valor):
                    valor = ""
                else:
                    valor = str(valor).strip()
                registro[col["nombre"]] = valor
            if hoja == "ESTANTES_EXISTENTES":
                registro["orientacion"] = int(a_numero(registro.get("orientacion")) or 0)
                registro["existente"] = True
                registro["estimado"] = bool(fila.get("estimado", False)) if not vacio(fila.get("estimado")) else False
            local[clave].append(registro)
    return local


def leer_plantilla_local(contenido):
    """Lee plantilla_local.xlsx. Devuelve (local o None, resultado_validacion)."""
    validacion = validar_plantilla(contenido, "local")
    if validacion["rechazada"]:
        return None, validacion
    local = tablas_a_local(validacion["tablas"], fuente="excel")
    return local, validacion


# --------------------------------------------------------------------------------------
# DXF (AutoCAD u otro CAD)
# --------------------------------------------------------------------------------------

def _abrir_dxf(contenido):
    from ezdxf import recover
    with tempfile.NamedTemporaryFile(suffix=".dxf", delete=False) as temporal:
        temporal.write(contenido)
        ruta = temporal.name
    try:
        documento, _auditor = recover.readfile(ruta)
    finally:
        Path(ruta).unlink(missing_ok=True)
    return documento


def _cajas_por_capa(documento):
    """Devuelve {capa: [(x0, y0, x1, y1), ...]} en unidades del dibujo."""
    from ezdxf import bbox
    from modulos.comun import sin_tildes
    cajas = {}
    for entidad in documento.modelspace():
        if entidad.dxftype() in ("TEXT", "MTEXT", "DIMENSION", "HATCH", "POINT"):
            continue
        try:
            caja = bbox.extents([entidad])
        except Exception:
            continue
        if not caja.has_data:
            continue
        capa = sin_tildes(entidad.dxf.layer)
        cajas.setdefault(capa, []).append((caja.extmin.x, caja.extmin.y, caja.extmax.x, caja.extmax.y))
    return cajas


def analizar_dxf(contenido):
    """Primera lectura del DXF: capas encontradas, propuesta de mapeo y unidad detectada."""
    documento = _abrir_dxf(contenido)
    cajas = _cajas_por_capa(documento)
    codigo_unidad = documento.header.get("$INSUNITS", 0)
    todas = [c for lista in cajas.values() for c in lista]
    if not todas:
        return {"capas": {}, "mapeo": {}, "unidad": "metros", "factor": 1.0, "detectada_por": "sin entidades"}
    ancho_total = max(c[2] for c in todas) - min(c[0] for c in todas)
    if codigo_unidad in UNIDADES_DXF:
        unidad, factor = UNIDADES_DXF[codigo_unidad]
        detectada = "encabezado del archivo ($INSUNITS)"
    else:
        # Sin unidad declarada: se adivina por el tamaño del dibujo
        if ancho_total > 2000:
            unidad, factor = "milímetros", 0.001
        elif ancho_total > 200:
            unidad, factor = "centímetros", 0.01
        else:
            unidad, factor = "metros", 1.0
        detectada = f"tamaño del dibujo ({ancho_total:,.0f} unidades de ancho)"
    mapeo = {capa: CAPAS_CONOCIDAS.get(capa, "ignorar") for capa in cajas}
    return {"capas": {capa: len(lista) for capa, lista in cajas.items()}, "mapeo": mapeo,
            "unidad": unidad, "factor": factor, "detectada_por": detectada}


def leer_dxf(contenido, mapeo, factor, altura_libre_m=3.0):
    """Convierte el DXF en un local usando el mapeo capa -> tipo y el factor a metros."""
    ajustes = cargar_ajustes()
    por_defecto = ajustes["estante_por_defecto"]
    documento = _abrir_dxf(contenido)
    cajas = _cajas_por_capa(documento)
    local = local_vacio()
    local["fuente"] = "dxf"
    local["altura_libre_m"] = altura_libre_m
    utiles = [(capa, c) for capa, lista in cajas.items() if mapeo.get(capa, "ignorar") != "ignorar" for c in lista]
    if not utiles:
        local["avisos_lectura"].append("No se encontró ninguna entidad en las capas elegidas.")
        return local
    x_min = min(c[0] for _, c in utiles)
    y_min = min(c[1] for _, c in utiles)
    x_max = max(c[2] for _, c in utiles)
    y_max = max(c[3] for _, c in utiles)
    contornos = [c for capa, c in utiles if mapeo[capa] == "contorno"]
    if contornos:
        x_min = min(c[0] for c in contornos)
        y_min = min(c[1] for c in contornos)
        x_max = max(c[2] for c in contornos)
        y_max = max(c[3] for c in contornos)
    local["largo_m"] = round((x_max - x_min) * factor, 3)
    local["ancho_m"] = round((y_max - y_min) * factor, 3)
    contadores = {}
    for capa, (x0, y0, x1, y1) in utiles:
        tipo = mapeo[capa]
        if tipo == "contorno":
            continue
        x, y = (x0 - x_min) * factor, (y0 - y_min) * factor
        largo, ancho = (x1 - x0) * factor, (y1 - y0) * factor
        if tipo == "muro" and largo >= 0.8 * local["largo_m"] and ancho >= 0.8 * local["ancho_m"]:
            continue  # polilínea cerrada del perímetro: es el contorno, no un obstáculo
        contadores[tipo] = contadores.get(tipo, 0) + 1
        numero = contadores[tipo]
        if tipo == "estante":
            horizontal = largo >= ancho
            local["estantes"].append(_estante(
                f"E{numero}", round(x, 3), round(y, 3), 0 if horizontal else 90, tipo=por_defecto["tipo"],
                largo=round(max(largo, ancho), 3), fondo=round(min(largo, ancho), 3), alto=por_defecto["alto_m"],
                niveles=por_defecto["niveles"], capacidad=por_defecto["capacidad_kg_nivel"],
                costo=por_defecto["costo_soles"]))
            local["estantes"][-1]["estimado"] = True
        elif tipo.startswith("zona_"):
            local["zonas"].append({"id": f"Z{len(local['zonas']) + 1}", "tipo": tipo.replace("zona_", ""),
                                   "x_m": round(x, 3), "y_m": round(y, 3), "largo_m": round(max(largo, 0.3), 3),
                                   "ancho_m": round(max(ancho, 0.3), 3)})
        else:
            prefijo = {"muro": "M", "columna": "C", "puerta": "P", "escalera": "ES", "tablero": "T",
                       "extintor": "X", "salida_emergencia": "S", "luminaria": "L", "rociador": "R"}.get(tipo, "O")
            local["obstaculos"].append({"id": f"{prefijo}{numero}", "tipo": tipo, "x_m": round(x, 3), "y_m": round(y, 3),
                                        "largo_m": round(max(largo, 0.15), 3), "ancho_m": round(max(ancho, 0.15), 3),
                                        "alto_m": altura_libre_m})
    if local["estantes"]:
        local["avisos_lectura"].append(
            f"Los {len(local['estantes'])} estantes del DXF solo traen su huella. Se asumieron {por_defecto['niveles']} niveles, "
            f"{por_defecto['alto_m']} m de alto, {por_defecto['capacidad_kg_nivel']} kg por nivel y frente hacia Y menor: "
            "corríjalos en la pantalla de confirmación.")
    local["equipos"] = [{"tipo": "manual", "radio_giro_m": 0.0, "altura_max_m": 1.9}]
    local["pasillos"] = [{"uso": "peatonal", "ancho_min_m": ajustes["geometria"]["ancho_pasillo_por_defecto_m"]}]
    return local


# --------------------------------------------------------------------------------------
# Imagen o PDF del plano
# --------------------------------------------------------------------------------------

def imagen_desde_archivo(contenido, nombre_archivo):
    """Devuelve una imagen PIL a partir de PNG/JPG o de la primera página de un PDF."""
    from PIL import Image
    if nombre_archivo.lower().endswith(".pdf"):
        import pymupdf
        documento = pymupdf.open(stream=contenido, filetype="pdf")
        pagina = documento[0]
        imagen = pagina.get_pixmap(dpi=110)
        return Image.open(io.BytesIO(imagen.tobytes("png"))).convert("RGB")
    return Image.open(io.BytesIO(contenido)).convert("RGB")


def longitud_linea_px(objeto):
    """Largo en píxeles de una línea dibujada en el lienzo."""
    escala_x = objeto.get("scaleX", 1) or 1
    escala_y = objeto.get("scaleY", 1) or 1
    if "x1" in objeto and "x2" in objeto:
        dx = (objeto["x2"] - objeto["x1"]) * escala_x
        dy = (objeto["y2"] - objeto["y1"]) * escala_y
    else:
        dx = objeto.get("width", 0) * escala_x
        dy = objeto.get("height", 0) * escala_y
    return (dx ** 2 + dy ** 2) ** 0.5


def local_desde_trazos(objetos, metros_por_pixel, altura_libre_m=3.0):
    """Convierte rectángulos dibujados (color = tipo) en un local. El rectángulo de tipo
    'contorno' define el origen y el tamaño; si no hay, se usa el área de todos los trazos."""
    ajustes = cargar_ajustes()
    por_defecto = ajustes["estante_por_defecto"]
    tipo_por_color = {color.lower(): tipo for tipo, color in COLORES_TRAZO.items()}
    rectangulos = []
    for objeto in objetos:
        if objeto.get("type") not in ("rect", "LabeledRect"):
            continue
        ancho_px = objeto.get("width", 0) * (objeto.get("scaleX", 1) or 1)
        alto_px = objeto.get("height", 0) * (objeto.get("scaleY", 1) or 1)
        tipo = tipo_por_color.get(str(objeto.get("stroke", "")).lower(), "estante")
        rectangulos.append((tipo, objeto.get("left", 0), objeto.get("top", 0), ancho_px, alto_px))
    local = local_vacio()
    local["fuente"] = "imagen"
    local["altura_libre_m"] = altura_libre_m
    if not rectangulos:
        local["avisos_lectura"].append("No se dibujó ningún rectángulo.")
        return local
    contorno = [r for r in rectangulos if r[0] == "contorno"]
    if contorno:
        _, izquierda, arriba, ancho_px, alto_px = contorno[0]
    else:
        izquierda = min(r[1] for r in rectangulos)
        arriba = min(r[2] for r in rectangulos)
        ancho_px = max(r[1] + r[3] for r in rectangulos) - izquierda
        alto_px = max(r[2] + r[4] for r in rectangulos) - arriba
        local["avisos_lectura"].append("No se dibujó el contorno: se usó el rectángulo que encierra todos los trazos.")
    fondo_px = arriba + alto_px  # borde inferior del contorno = Y 0
    local["largo_m"] = round(ancho_px * metros_por_pixel, 2)
    local["ancho_m"] = round(alto_px * metros_por_pixel, 2)
    contadores = {}
    for tipo, x_px, y_px, w_px, h_px in rectangulos:
        if tipo == "contorno":
            continue
        x = round((x_px - izquierda) * metros_por_pixel, 2)
        y = round((fondo_px - (y_px + h_px)) * metros_por_pixel, 2)
        largo = round(w_px * metros_por_pixel, 2)
        ancho = round(h_px * metros_por_pixel, 2)
        contadores[tipo] = contadores.get(tipo, 0) + 1
        numero = contadores[tipo]
        if tipo == "estante":
            horizontal = largo >= ancho
            estante = _estante(f"E{numero}", x, y, 0 if horizontal else 90, tipo=por_defecto["tipo"],
                               largo=max(largo, ancho), fondo=min(largo, ancho), alto=por_defecto["alto_m"],
                               niveles=por_defecto["niveles"], capacidad=por_defecto["capacidad_kg_nivel"],
                               costo=por_defecto["costo_soles"])
            estante["estimado"] = True
            local["estantes"].append(estante)
        elif tipo.startswith("zona_"):
            local["zonas"].append({"id": f"Z{len(local['zonas']) + 1}", "tipo": tipo.replace("zona_", ""),
                                   "x_m": x, "y_m": y, "largo_m": largo, "ancho_m": ancho})
        else:
            prefijo = {"muro": "M", "columna": "C", "puerta": "P", "escalera": "ES", "tablero": "T",
                       "extintor": "X", "salida_emergencia": "S"}.get(tipo, "O")
            local["obstaculos"].append({"id": f"{prefijo}{numero}", "tipo": tipo, "x_m": x, "y_m": y,
                                        "largo_m": largo, "ancho_m": ancho, "alto_m": altura_libre_m})
    local["avisos_lectura"].append("Plano trazado sobre imagen: es la vía menos precisa. Revise cada medida.")
    if local["estantes"]:
        local["avisos_lectura"].append("Los estantes trazados usan niveles, alto y capacidad supuestos: corríjalos.")
    local["equipos"] = [{"tipo": "manual", "radio_giro_m": 0.0, "altura_max_m": 1.9}]
    local["pasillos"] = [{"uso": "peatonal", "ancho_min_m": ajustes["geometria"]["ancho_pasillo_por_defecto_m"]}]
    return local


def copiar_local(local):
    return copy.deepcopy(local)
