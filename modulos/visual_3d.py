"""Vista 3D interactiva con Plotly (Mesh3d). Se usa en la confirmación del local (versión
simple) y en resultados (con productos), y se exporta a un HTML que abre con doble clic.

En el HTML hay botones de cámara (planta, frontal, isométrica, a la altura de los ojos),
de vista (después / antes / solo estantes / mapa de calor), filtro por clase ABC, recorrido
de picking y un deslizador para ver nivel por nivel."""

import re

import plotly.graph_objects as go

from modulos.comun import cargar_ajustes
from modulos.interpretar_local import ampliar, frente_estante, huella_estante, huella_obstaculo, niveles_estante
from modulos.visual_2d import COLORES_ABC, COLORES_OBSTACULO, COLORES_ZONA

# Triángulos de una caja (8 vértices)
_I = [0, 0, 4, 4, 0, 0, 1, 1, 0, 0, 3, 3]
_J = [1, 2, 5, 6, 1, 5, 2, 6, 3, 7, 2, 6]
_K = [2, 3, 6, 7, 5, 4, 6, 5, 7, 4, 6, 7]
_ARISTAS = [(0, 1), (1, 2), (2, 3), (3, 0), (4, 5), (5, 6), (6, 7), (7, 4), (0, 4), (1, 5), (2, 6), (3, 7)]
CAMARAS = {
    "Isométrica": dict(eye=dict(x=1.05, y=-1.05, z=0.85), up=dict(x=0, y=0, z=1)),
    "Planta": dict(eye=dict(x=0.0, y=-0.001, z=2.4), up=dict(x=0, y=1, z=0)),
    "Frontal": dict(eye=dict(x=0.0, y=-2.3, z=0.35), up=dict(x=0, y=0, z=1)),
    "Ojos": dict(eye=dict(x=0.25, y=-0.95, z=-0.05), center=dict(x=0, y=0, z=-0.12), up=dict(x=0, y=0, z=1)),
}


class Cajas:
    """Acumula muchas cajas en una sola malla (es mucho más rápido que una traza por caja)."""

    def __init__(self):
        self.x, self.y, self.z, self.i, self.j, self.k, self.texto, self.intensidad = [], [], [], [], [], [], [], []

    def agregar(self, x0, y0, z0, x1, y1, z1, texto="", intensidad=0.0):
        x0, y0, z0, x1, y1, z1 = (round(float(v), 3) for v in (x0, y0, z0, x1, y1, z1))
        base = len(self.x)
        self.x += [x0, x1, x1, x0, x0, x1, x1, x0]
        self.y += [y0, y0, y1, y1, y0, y0, y1, y1]
        self.z += [z0, z0, z0, z0, z1, z1, z1, z1]
        self.i += [base + v for v in _I]
        self.j += [base + v for v in _J]
        self.k += [base + v for v in _K]
        self.texto += [texto] * 8
        self.intensidad += [round(float(intensidad), 3)] * 8

    def vacia(self):
        return not self.x

    def malla(self, nombre, color=None, opacidad=1.0, hover=True, escala=None, mostrar_leyenda=True, visible=True, grupo=None):
        argumentos = dict(x=self.x, y=self.y, z=self.z, i=self.i, j=self.j, k=self.k, name=nombre, opacity=opacidad,
                          flatshading=True, showlegend=bool(mostrar_leyenda), visible=bool(visible), legendgroup=grupo or nombre,
                          lighting=dict(ambient=0.6, diffuse=0.7, specular=0.1), showscale=False)
        if escala:
            argumentos.update(intensity=self.intensidad, colorscale=escala, cmin=0, cmax=1, showscale=True,
                              colorbar=dict(title=dict(text=nombre), len=0.5))
        else:
            argumentos["color"] = color
        if hover:
            argumentos.update(hovertext=self.texto, hoverinfo="text")
        else:
            argumentos["hoverinfo"] = "skip"
        return go.Mesh3d(**argumentos)


def _aristas(cajas_xyz, nombre, color, guion="solid", visible=True):
    xs, ys, zs = [], [], []
    for caja in cajas_xyz:
        x0, y0, z0, x1, y1, z1 = (round(float(v), 3) for v in caja)
        vertices = [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0), (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]
        for a, b in _ARISTAS:
            xs += [vertices[a][0], vertices[b][0], None]
            ys += [vertices[a][1], vertices[b][1], None]
            zs += [vertices[a][2], vertices[b][2], None]
    return go.Scatter3d(x=xs, y=ys, z=zs, mode="lines", line=dict(color=color, width=1, dash=guion), name=nombre,
                        hoverinfo="skip", visible=visible, showlegend=True)


def _estructura(local, parametros, simple=False):
    """Trazas de piso, muros, techo, obstáculos, zonas, despejes y estantes."""
    trazas = []
    largo, ancho = float(local["largo_m"]), float(local["ancho_m"])
    altura = float(local.get("altura_libre_m") or 3.0)
    piso = Cajas()
    piso.agregar(0, 0, -0.02, largo, ancho, 0, f"Piso {largo} × {ancho} m")
    trazas.append(piso.malla("Piso", "#d9d9d9", 1.0, mostrar_leyenda=False))
    muros = Cajas()
    grosor = 0.08
    for caja in [(-grosor, -grosor, largo + grosor, 0), (-grosor, ancho, largo + grosor, ancho + grosor),
                 (-grosor, 0, 0, ancho), (largo, 0, largo + grosor, ancho)]:
        muros.agregar(caja[0], caja[1], 0, caja[2], caja[3], altura, "Muro")
    trazas.append(muros.malla("Muros", "#bdbdbd", 0.25, hover=False))
    techo = Cajas()
    techo.agregar(0, 0, altura, largo, ancho, altura + 0.01, f"Altura libre {altura} m")
    trazas.append(techo.malla("Techo (altura libre)", "#9ecae1", 0.06, hover=True))
    por_tipo = {}
    for obstaculo in local.get("obstaculos", []):
        x0, y0, x1, y1 = huella_obstaculo(obstaculo)
        tipo = obstaculo["tipo"]
        alto_obs = float(obstaculo.get("alto_m") or altura)
        z0, z1 = 0, alto_obs
        if tipo in ("rociador", "luminaria"):
            z0, z1 = alto_obs - 0.08, alto_obs
        elif tipo == "extintor":
            z0, z1 = 0.6, min(alto_obs, 1.5)
        elif tipo in ("puerta", "salida_emergencia"):
            z1 = min(alto_obs, 2.2)
        por_tipo.setdefault(tipo, Cajas()).agregar(x0, y0, z0, x1, y1, z1, f"{obstaculo['id']}: {tipo.replace('_', ' ')}")
    for tipo, cajas in por_tipo.items():
        opacidad = 0.5 if tipo in ("puerta", "salida_emergencia") else 0.95
        trazas.append(cajas.malla(tipo.replace("_", " ").capitalize(), COLORES_OBSTACULO.get(tipo, "#444444"), opacidad))
    zonas = {}
    for zona in local.get("zonas", []):
        zonas.setdefault(zona["tipo"], Cajas()).agregar(zona["x_m"], zona["y_m"], 0.0, zona["x_m"] + zona["largo_m"],
                                                        zona["y_m"] + zona["ancho_m"], 0.02, f"{zona['id']}: zona {zona['tipo']}")
    for tipo, cajas in zonas.items():
        trazas.append(cajas.malla(f"Zona {tipo}", COLORES_ZONA.get(tipo, "#cccccc"), 0.6))
    prohibidas = Cajas()
    margenes = {"salida_emergencia": parametros.get("despeje_salida_m"), "extintor": parametros.get("despeje_extintor_m"),
                "tablero": parametros.get("despeje_tablero_m")}
    for obstaculo in local.get("obstaculos", []):
        margen = margenes.get(obstaculo["tipo"])
        if margen:
            x0, y0, x1, y1 = ampliar(huella_obstaculo(obstaculo), margen)
            prohibidas.agregar(max(x0, 0), max(y0, 0), 0, min(x1, largo), min(y1, ancho), 2.0,
                               f"Zona prohibida: despeje de {obstaculo['tipo']} {obstaculo['id']} ({margen} m)")
    if not prohibidas.vacia():
        trazas.append(prohibidas.malla("Zonas prohibidas", "#ff0000", 0.12))
    ajustes = cargar_ajustes()
    # Una sola malla por categoría de color: racks propuestos (nuevos) y racks existentes
    grupos = {}
    for estante in local.get("estantes", []):
        nuevo = "vacio" if estante.get("vacio") else estante.get("existente") is False
        grupos.setdefault(nuevo, []).append(estante)
    for nuevo, estantes in grupos.items():
        trazas += _trazas_estantes(estantes, ajustes, simple, nuevo)
    return trazas


def _trazas_estantes(estantes, ajustes, simple, nuevo):
    """Mallas de los postes y bandejas de un grupo de estantes (nuevos = naranja claro, existentes = gris azulado)."""
    trazas = []
    marcos, bandejas = Cajas(), Cajas()
    for estante in estantes:
        x0, y0, x1, y1 = huella_estante(estante)
        alto = float(estante["alto_m"])
        poste = 0.04
        for px, py in ((x0, y0), (x1 - poste, y0), (x0, y1 - poste), (x1 - poste, y1 - poste)):
            marcos.agregar(px, py, 0, px + poste, py + poste, alto, f"Estante {estante['id']}")
        texto = f"Estante {estante['id']} ({estante['tipo']}): {estante['niveles']} niveles, {estante['capacidad_kg_nivel']} kg/nivel"
        for numero, (base, alto_libre) in enumerate(niveles_estante(estante, ajustes), start=1):
            bandejas.agregar(x0, y0, base - 0.03, x1, y1, base, f"{texto}<br>Nivel {numero}: base {base:.2f} m, libre {alto_libre:.2f} m")
        bandejas.agregar(x0, y0, alto - 0.02, x1, y1, alto, texto)
    if not marcos.vacia():
        if nuevo == "vacio":
            trazas.append(marcos.malla("Racks propuestos (vacíos) — estructura", "#2e7d32", 1.0, hover=False))
            trazas.append(bandejas.malla("Racks propuestos (vacíos)", "#a5d6a7", 0.6))
        elif nuevo:
            trazas.append(marcos.malla("Racks propuestos (estructura)", "#8a5a00", 1.0, hover=False))
            trazas.append(bandejas.malla("Racks propuestos (bandejas)", "#f6c177", 0.85))
        else:
            trazas.append(marcos.malla("Estantes (estructura)", "#4a4a4a", 1.0, hover=False))
            trazas.append(bandejas.malla("Bandejas de estante", "#8fa9c4" if simple else "#b0bec5", 0.85))
    return trazas


def _medidas_orientacion(texto):
    numeros = [float(n) for n in re.findall(r"[\d.]+", str(texto))]
    return numeros[:3] if len(numeros) >= 3 else None


def _cajas_productos(local, validas, pares, productos, asignacion, ajustes):
    """Calcula la caja 3D (x0, y0, z0, x1, y1, z1) de cada producto ubicado."""
    holgura = ajustes["geometria"]["holgura_altura_cm"] / 100
    estantes = {e["id"]: e for e in local.get("estantes", [])}
    claves = set(asignacion.items())
    indice = {(f["i"], f["j"]): f for f in pares[[c in claves for c in zip(pares["i"], pares["j"])]].to_dict("records")}
    datos_posicion = validas.to_dict("index")
    ocupado = {}
    cajas = []
    for i, j in sorted(asignacion.items(), key=lambda par: (par[1], par[0])):
        par = indice[(i, j)]
        posicion = datos_posicion[j]
        estante = estantes[posicion["estante"]]
        fx, fy, (dx, dy), (nx, ny) = frente_estante(estante)
        medidas = _medidas_orientacion(par["orientacion"]) or [par["ancho_ocupado_m"] * 100, 30, 20]
        frente_cm, fondo_cm, alto_cm = medidas
        por_frente = max(1, int(par["unidades_caben"] / max(par["frentes"], 1)))
        capas = max(1, min(int(productos.at[i, "m_apilado"]), int((posicion["alto_libre_m"] - holgura) * 100 // max(alto_cm, 0.1))))
        por_fondo = max(1, por_frente // capas)
        profundidad = min(por_fondo * fondo_cm / 100, posicion["fondo_m"])
        altura = min(capas * alto_cm / 100, posicion["alto_libre_m"])
        clave = posicion["estante"], posicion["nivel"], posicion["tramo"]
        desde = (posicion["tramo"] - 1) * posicion["ancho_m"] + ocupado.get(clave, 0.0)
        ancho_ocupado = float(par["ancho_ocupado_m"])
        ocupado[clave] = ocupado.get(clave, 0.0) + ancho_ocupado
        hasta = desde + ancho_ocupado * 0.98
        ax, ay = fx + dx * desde, fy + dy * desde
        bx, by = fx + dx * hasta, fy + dy * hasta
        cx, cy = ax - nx * profundidad, ay - ny * profundidad
        xs, ys = [ax, bx, cx], [ay, by, cy]
        z0 = float(posicion["base_m"])
        cajas.append((i, j, (min(xs), min(ys), z0, max(xs), max(ys), z0 + altura)))
    return cajas


def _texto_producto(producto, posicion):
    return (f"<b>{producto['producto'][:60]}</b><br>Código: {producto['id_producto']}<br>Categoría: {producto['categoria']}<br>"
            f"Clase ABC: {producto['clase_abc']} · rotación {producto['rotacion_diaria']:.2f} u./día<br>"
            f"Peso: {producto['peso_kg']:.2f} kg · medidas {producto['largo_cm']:g}×{producto['ancho_cm']:g}×{producto['alto_cm']:g} cm<br>"
            f"Estante {posicion['estante']}, nivel {posicion['nivel']}, tramo {posicion['tramo']}<br>"
            f"Medida: {'REAL' if producto['origen_medidas'] == 'real' else 'ESTIMADA'}")


def figura_3d(local, parametros=None, solucion=None, asignacion=None, asignacion_antes=None, recorrido=None,
              categorias=None, clases=None, altura_max=None, solo_ids=None, modo_color="abc", modulo=None,
              titulo="Vista 3D", alto=650):
    """Construye la figura 3D. Si no hay solución, muestra solo el local (pantalla de confirmación)."""
    ajustes = cargar_ajustes()
    parametros = parametros or {}
    figura = go.Figure()
    etiquetas = []  # (grupo, clase, nivel) de cada traza para los botones del HTML
    for traza in _estructura(local, parametros, simple=solucion is None):
        figura.add_trace(traza)
        etiquetas.append(("estructura", None, None))
    if solucion is not None:
        productos, validas, pares = solucion["productos"], solucion["validas"], solucion["pares"]
        asignacion = solucion["asignacion"] if asignacion is None else asignacion
        maximo_cajas = ajustes["visual"]["max_cajas_3d"]
        niveles = sorted(int(n) for n in validas["nivel"].unique())

        def filtrar(asig):
            resultado = {}
            for i, j in asig.items():
                producto = productos.loc[i]
                posicion = validas.loc[j]
                if categorias and producto["categoria"] not in categorias:
                    continue
                if clases and producto["clase_abc"] not in clases:
                    continue
                if altura_max is not None and posicion["base_m"] > altura_max:
                    continue
                if solo_ids is not None and producto["id_producto"] not in solo_ids:
                    continue
                if modulo and posicion["estante"] != modulo:
                    continue
                resultado[i] = j
            return resultado

        conjuntos = [("despues", filtrar(asignacion), True)]
        if asignacion_antes:
            conjuntos.append(("antes", filtrar(asignacion_antes), False))
        rot_max = max(float(productos["rotacion_diaria"].max()), 1e-9)
        datos_producto = productos.to_dict("index")
        datos_posicion = validas.to_dict("index")
        for nombre_conjunto, asig, visible in conjuntos:
            cajas = _cajas_productos(local, validas, pares, productos, asig, ajustes)
            agrupar = len(cajas) > maximo_cajas
            if agrupar:  # muchas cajas: una por posición para que siga fluido
                por_posicion = {}
                for i, j, caja in cajas:
                    actual = por_posicion.get(j)
                    por_posicion[j] = (i, j, caja if actual is None else tuple(
                        min(a, b) if k < 3 else max(a, b) for k, (a, b) in enumerate(zip(actual[2], caja))))
                cajas = list(por_posicion.values())
            es_antes = nombre_conjunto == "antes"
            for nivel in niveles:
                por_clase = {}
                for i, j, caja in cajas:
                    posicion = datos_posicion[j]
                    if posicion["nivel"] != nivel:
                        continue
                    producto = datos_producto[i]
                    clase = producto["clase_abc"]
                    if agrupar:
                        texto = f"Posición {posicion['id_posicion']} (agrupada)"
                    elif es_antes:
                        texto = f"ANTES: {producto['producto'][:50]}<br>{posicion['id_posicion']} · clase {clase}"
                    else:
                        texto = _texto_producto(producto, posicion)
                    valor = producto["rotacion_diaria"] / rot_max if modo_color != "costo" else posicion["costo_acceso"] / 1.6
                    grupo = por_clase.setdefault(clase, {"cajas": Cajas(), "x": [], "y": [], "z": [], "texto": []})
                    grupo["cajas"].agregar(*caja, intensidad=min(1.0, max(valor, 0) ** 0.5))
                    grupo["x"].append(round((caja[0] + caja[3]) / 2, 3))
                    grupo["y"].append(round((caja[1] + caja[4]) / 2, 3))
                    grupo["z"].append(round(caja[5], 3))
                    grupo["texto"].append(texto)
                for clase, grupo in por_clase.items():
                    etiqueta = f"{'Antes' if es_antes else 'Productos'} clase {clase}"
                    color = COLORES_ABC.get(clase, "#999999")
                    figura.add_trace(grupo["cajas"].malla(etiqueta, color, 1.0, hover=False, visible=visible and modo_color == "abc",
                                                          mostrar_leyenda=nivel == niveles[0], grupo=f"{nombre_conjunto}_{clase}"))
                    etiquetas.append((nombre_conjunto, clase, nivel))
                    # Un punto por producto para mostrar la ficha al pasar el mouse
                    figura.add_trace(go.Scatter3d(x=grupo["x"], y=grupo["y"], z=grupo["z"], mode="markers", name=etiqueta,
                                                  marker=dict(size=2.5, color=color, line=dict(width=0)), hovertext=grupo["texto"],
                                                  hoverinfo="text", showlegend=False, legendgroup=f"{nombre_conjunto}_{clase}",
                                                  visible=bool(visible)))
                    etiquetas.append((f"puntos_{nombre_conjunto}", clase, nivel))
                    figura.add_trace(grupo["cajas"].malla("Mapa de calor (rotación)" if modo_color != "costo" else "Mapa de calor (costo)",
                                                          escala="YlOrRd", hover=False, visible=visible and modo_color != "abc",
                                                          mostrar_leyenda=False, grupo="calor"))
                    etiquetas.append((f"calor_{nombre_conjunto}", clase, nivel))
            if es_antes:
                continue
            estimadas = [caja for i, _, caja in cajas if datos_producto[i]["origen_medidas"] != "real"]
            reales = [caja for i, _, caja in cajas if datos_producto[i]["origen_medidas"] == "real"]
            if estimadas and len(estimadas) <= maximo_cajas:
                figura.add_trace(_aristas(estimadas, "Borde punteado: medida estimada", "#6b6b6b", "dot", visible=visible))
                etiquetas.append((f"bordes_{nombre_conjunto}", None, None))
            if reales and len(reales) <= maximo_cajas:
                figura.add_trace(_aristas(reales, "Borde continuo: medida real", "#000000", "solid", visible=visible))
                etiquetas.append((f"bordes_{nombre_conjunto}", None, None))
    if recorrido:
        xs, ys = zip(*recorrido)
        figura.add_trace(go.Scatter3d(x=xs, y=ys, z=[0.05] * len(xs), mode="lines+markers", name="Recorrido de picking",
                                      line=dict(color="#0050ff", width=6), marker=dict(size=2), hoverinfo="name"))
        etiquetas.append(("recorrido", None, None))
    largo, ancho = float(local["largo_m"]), float(local["ancho_m"])
    altura = float(local.get("altura_libre_m") or 3)
    escala_z = max(0.25, min(1.0, altura / max(largo, ancho) * 2.2))
    figura.update_layout(
        title=dict(text=titulo, x=0.01), height=alto, margin=dict(l=0, r=0, t=40, b=0),
        scene=dict(aspectmode="manual", aspectratio=dict(x=largo / max(largo, ancho), y=ancho / max(largo, ancho), z=escala_z),
                   xaxis=dict(title="X (m)", range=[-0.3, largo + 0.3]), yaxis=dict(title="Y (m)", range=[-0.3, ancho + 0.3]),
                   zaxis=dict(title="Altura (m)", range=[0, altura + 0.1]), camera=CAMARAS["Isométrica"]),
        legend=dict(itemsizing="constant", font=dict(size=10)))
    figura._etiquetas_acomoda = etiquetas  # se usa al exportar los controles del HTML
    return figura


def agregar_controles_html(figura):
    """Botones y deslizador para el HTML independiente (funcionan sin Python)."""
    etiquetas = getattr(figura, "_etiquetas_acomoda", None) or [("estructura", None, None)] * len(figura.data)
    hay_antes = any(e[0] == "antes" for e in etiquetas)
    hay_recorrido = any(e[0] == "recorrido" for e in etiquetas)
    niveles = sorted({e[2] for e in etiquetas if e[2] is not None})

    def visibles(conjunto="despues", clase=None, nivel_max=None, calor=False, recorrido=True):
        lista = []
        for grupo, clase_traza, nivel in etiquetas:
            if grupo == "estructura":
                lista.append(True)
            elif grupo == "recorrido":
                lista.append(recorrido)
            elif grupo in (conjunto, f"calor_{conjunto}", f"puntos_{conjunto}"):
                es_calor = grupo.startswith("calor_")
                es_punto = grupo.startswith("puntos_")
                ok = (es_punto or es_calor == calor) and (clase is None or clase_traza == clase) and \
                     (nivel_max is None or nivel is None or nivel <= nivel_max)
                lista.append(ok)
            elif grupo == f"bordes_{conjunto}":
                lista.append(clase is None and nivel_max is None and not calor)
            else:
                lista.append(False)
        return lista

    botones_camara = [dict(label=nombre, method="relayout", args=[{"scene.camera": camara}]) for nombre, camara in CAMARAS.items()]
    botones_vista = [dict(label="Después", method="restyle", args=[{"visible": visibles("despues")}]),
                     dict(label="Mapa de calor", method="restyle", args=[{"visible": visibles("despues", calor=True)}])]
    if hay_antes:
        botones_vista.append(dict(label="Antes", method="restyle", args=[{"visible": visibles("antes")}]))
    botones_vista.append(dict(label="Solo estantes", method="restyle", args=[{"visible": visibles("ninguno", recorrido=False)}]))
    botones_clase = [dict(label="Todas las clases", method="restyle", args=[{"visible": visibles("despues")}])]
    for clase in ("A", "B", "C", "SIN ROTACIÓN"):
        if any(e[1] == clase for e in etiquetas):
            botones_clase.append(dict(label=f"Solo {clase}", method="restyle", args=[{"visible": visibles("despues", clase)}]))
    menus = [dict(type="buttons", direction="right", x=0.0, y=1.08, xanchor="left", buttons=botones_camara, showactive=True),
             dict(type="dropdown", x=0.42, y=1.08, xanchor="left", buttons=botones_vista, showactive=True),
             dict(type="dropdown", x=0.58, y=1.08, xanchor="left", buttons=botones_clase, showactive=True)]
    if hay_recorrido:
        menus.append(dict(type="buttons", x=0.76, y=1.08, xanchor="left", buttons=[
            dict(label="Recorrido sí/no", method="restyle", args=[{"visible": visibles("despues", recorrido=True)}],
                 args2=[{"visible": visibles("despues", recorrido=False)}])]))
    sliders = []
    if niveles:
        pasos = [dict(label=f"hasta nivel {n}", method="restyle", args=[{"visible": visibles("despues", nivel_max=n)}])
                 for n in niveles]
        sliders = [dict(active=len(pasos) - 1, currentvalue=dict(prefix="Altura: "), pad=dict(t=10), steps=pasos, y=0.02)]
    figura.update_layout(updatemenus=menus, sliders=sliders, margin=dict(t=90, l=0, r=0, b=0),
                         title=dict(x=0.99, xanchor="right", y=0.99))
    return figura


def guardar_html(figura, ruta):
    etiquetas = getattr(figura, "_etiquetas_acomoda", None)
    copia = go.Figure(figura)
    copia._etiquetas_acomoda = etiquetas
    agregar_controles_html(copia)
    copia.update_layout(height=None, autosize=True)
    copia.write_html(str(ruta), include_plotlyjs=True, full_html=True, config={"displaylogo": False, "responsive": True},
                     default_height="95vh")
    return ruta


def recorrido_pedido(local, validas, asignacion, ids_productos, productos, modo="almacen"):
    """Ruta de picking de un pedido: sale del despacho, visita cada producto (vecino más cercano) y vuelve."""
    from modulos.interpretar_local import Grilla, punto_origen
    origen, _ = punto_origen(local, modo)
    indice_por_id = {v: k for k, v in productos["id_producto"].items()}
    paradas = []
    for identificador in ids_productos:
        i = indice_por_id.get(identificador)
        if i is not None and i in asignacion:
            j = asignacion[i]
            paradas.append((float(validas.at[j, "x_acceso"]), float(validas.at[j, "y_acceso"])))
    if not paradas:
        return None
    grilla = Grilla(local)
    puntos, actual = [], origen
    pendientes = paradas[:]
    while pendientes:
        siguiente = min(pendientes, key=lambda p: (p[0] - actual[0]) ** 2 + (p[1] - actual[1]) ** 2)
        puntos += grilla.camino(actual, siguiente)
        actual = siguiente
        pendientes.remove(siguiente)
    puntos += grilla.camino(actual, origen)
    return puntos
