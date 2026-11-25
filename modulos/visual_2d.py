"""Plano de planta 2D (Plotly): contorno, obstáculos, zonas, despejes prohibidos y estantes
coloreados por tipo, por clase ABC o como mapa de calor de rotación / costo de acceso."""

import plotly.graph_objects as go

from modulos.interpretar_local import ampliar, huella_estante, huella_obstaculo, rect_frente

COLORES_OBSTACULO = {"columna": "#5f6b7a", "muro": "#8c564b", "puerta": "#2ca02c", "escalera": "#9467bd",
                     "tablero": "#ff7f0e", "extintor": "#e00000", "salida_emergencia": "#00a651",
                     "luminaria": "#f1c40f", "rociador": "#1f77b4"}
COLORES_ZONA = {"recepcion": "#9edae5", "despacho": "#17becf", "devoluciones": "#c5b0d5", "cuarentena": "#ff9896",
                "caja": "#dbdb8d", "ingreso": "#98df8a", "picking": "#aec7e8", "reserva": "#c7c7c7", "controlada": "#f7b6d2"}
COLORES_ABC = {"A": "#d1495b", "B": "#edae49", "C": "#66a182", "SIN ROTACIÓN": "#9e9e9e", "VACÍO": "#e8eef5"}


def _poligono(r):
    x0, y0, x1, y1 = r
    return [x0, x1, x1, x0, x0], [y0, y0, y1, y1, y0]


def _agregar_rect(figura, r, color, nombre, texto, opacidad=0.8, borde="#333333", grosor=1, grupo=None, mostrar=True, guion=None):
    xs, ys = _poligono(r)
    figura.add_trace(go.Scatter(x=xs, y=ys, fill="toself", fillcolor=color, opacity=opacidad, mode="lines",
                                line=dict(color=borde, width=grosor, dash=guion), name=nombre, legendgroup=grupo or nombre,
                                showlegend=mostrar, hoverinfo="text", text=texto, hoveron="fills"))


def plano_2d(local, posiciones=None, ubicaciones=None, color_por="tipo", ids_con_aviso=(), parametros=None, alto=560):
    """color_por: 'tipo', 'abc', 'rotacion' o 'costo'."""
    parametros = parametros or {}
    figura = go.Figure()
    largo, ancho = float(local.get("largo_m") or 1), float(local.get("ancho_m") or 1)
    _agregar_rect(figura, (0, 0, largo, ancho), "#ffffff", "Contorno del local", f"Local {largo} × {ancho} m",
                  opacidad=1, borde="#000000", grosor=3)
    vistos = set()
    for zona in local.get("zonas", []):
        r = (zona["x_m"], zona["y_m"], zona["x_m"] + zona["largo_m"], zona["y_m"] + zona["ancho_m"])
        nombre = f"Zona {zona['tipo']}"
        _agregar_rect(figura, r, COLORES_ZONA.get(zona["tipo"], "#dddddd"), nombre, f"{zona['id']}: {nombre}",
                      opacidad=0.45, borde="#888888", grupo=nombre, mostrar=nombre not in vistos)
        vistos.add(nombre)
    # Despejes obligatorios (zonas prohibidas para estantes)
    margenes = {"salida_emergencia": parametros.get("despeje_salida_m", 1.2), "extintor": parametros.get("despeje_extintor_m", 1.0),
                "tablero": parametros.get("despeje_tablero_m", 1.0)}
    primera = True
    for obstaculo in local.get("obstaculos", []):
        margen = margenes.get(obstaculo["tipo"])
        if margen:
            _agregar_rect(figura, ampliar(huella_obstaculo(obstaculo), margen), "rgba(255,0,0,0.08)", "Despeje obligatorio",
                          f"Zona libre frente a {obstaculo['tipo']} {obstaculo['id']} ({margen} m)", opacidad=1,
                          borde="#e00000", grupo="despeje", mostrar=primera, guion="dot")
            primera = False
    # Estantes / tramos
    datos_tramo = {}
    if posiciones is not None and ubicaciones is not None and len(ubicaciones):
        ubicados = ubicaciones[ubicaciones["ubicado"]]
        for fila in ubicados.itertuples():
            clave = (fila.estante, fila.tramo)
            dato = datos_tramo.setdefault(clave, {"rot": 0.0, "costo": [], "clases": {}, "n": 0})
            dato["rot"] += fila.rotacion_diaria
            dato["costo"].append(fila.costo_acceso)
            dato["clases"][fila.clase_abc] = dato["clases"].get(fila.clase_abc, 0) + max(fila.rotacion_diaria, 0.001)
            dato["n"] += 1
    maximo_rot = max([d["rot"] for d in datos_tramo.values()] + [1e-9])
    for estante in local.get("estantes", []):
        huella = huella_estante(estante)
        borde = "#e00000" if estante["id"] in ids_con_aviso else "#1f3b5a"
        grosor = 3 if estante["id"] in ids_con_aviso else 1
        if color_por == "tipo" or posiciones is None or not datos_tramo:
            texto = (f"{estante['id']} ({estante['tipo']})<br>{estante['largo_m']} × {estante['fondo_m']} × {estante['alto_m']} m, "
                     f"{estante['niveles']} niveles, {estante['capacidad_kg_nivel']} kg/nivel<br>orientación {estante['orientacion']}°")
            color = "#f6c177" if estante.get("existente") is False else ("#6baed6" if not estante.get("estimado") else "#c6dbef")
            nombre = "Rack propuesto" if estante.get("existente") is False else "Estante"
            if estante.get("vacio"):
                color, nombre, texto = "#a5d6a7", "Racks propuestos (vacíos)", texto + "<br>Capacidad disponible (vacío)"
            _agregar_rect(figura, huella, color, nombre, texto, borde=borde, grosor=grosor, grupo=nombre,
                          mostrar=nombre not in vistos)
            vistos.add(nombre)
        else:
            tramos = posiciones[(posiciones["estante"] == estante["id"]) & (posiciones["nivel"] == 1)]
            for tramo in tramos.itertuples():
                dato = datos_tramo.get((estante["id"], tramo.tramo))
                if color_por == "abc":
                    clase = max(dato["clases"], key=dato["clases"].get) if dato else "VACÍO"
                    color = COLORES_ABC[clase]
                    nombre = f"Clase {clase}" if clase != "VACÍO" else "Vacío"
                else:
                    valor = (dato["rot"] / maximo_rot) if (dato and color_por == "rotacion") else \
                        (sum(dato["costo"]) / len(dato["costo"]) / 1.6 if dato else 0)
                    color = _calor(valor if dato else None)
                    nombre = "Mapa de calor"
                texto = (f"{estante['id']} tramo {tramo.tramo}<br>{dato['n'] if dato else 0} productos<br>"
                         f"rotación total {dato['rot'] if dato else 0:.2f} u./día")
                _agregar_rect(figura, (tramo.x0, tramo.y0, tramo.x1, tramo.y1), color, nombre, texto, opacidad=0.95,
                              borde="#555555", grupo=nombre, mostrar=nombre not in vistos)
                vistos.add(nombre)
            xs, ys = _poligono(huella)
            figura.add_trace(go.Scatter(x=xs, y=ys, mode="lines", line=dict(color=borde, width=grosor + 1), showlegend=False,
                                        hoverinfo="skip"))
        # línea del frente
        frente = rect_frente(estante, 0, float(estante["largo_m"]), 0.0)
        figura.add_trace(go.Scatter(x=[frente[0], frente[2]], y=[frente[1], frente[3]], mode="lines",
                                    line=dict(color="#ffcc00", width=4), showlegend=estante is local["estantes"][0],
                                    name="Frente del estante", legendgroup="frente", hoverinfo="skip"))
        figura.add_annotation(x=(huella[0] + huella[2]) / 2, y=(huella[1] + huella[3]) / 2, text=estante["id"],
                              showarrow=False, font=dict(size=9, color="#111111"))
    for obstaculo in local.get("obstaculos", []):
        if obstaculo["tipo"] in ("luminaria", "rociador"):
            continue
        nombre = obstaculo["tipo"].replace("_", " ").capitalize()
        _agregar_rect(figura, huella_obstaculo(obstaculo), COLORES_OBSTACULO.get(obstaculo["tipo"], "#444444"), nombre,
                      f"{obstaculo['id']}: {nombre}", opacidad=0.95, borde="#000000", grupo=nombre, mostrar=nombre not in vistos)
        vistos.add(nombre)
    figura.update_layout(height=alto, margin=dict(l=10, r=10, t=30, b=10), plot_bgcolor="#f4f4f4",
                         xaxis=dict(title="X (m)", range=[-0.5, largo + 0.5], scaleanchor="y", scaleratio=1, showgrid=True,
                                    gridcolor="#dddddd", dtick=1),
                         yaxis=dict(title="Y (m)", range=[-0.5, ancho + 0.5], showgrid=True, gridcolor="#dddddd", dtick=1),
                         legend=dict(orientation="h", y=-0.12), title=dict(text="Plano de planta (vista desde arriba)", x=0.01))
    return figura


def _calor(valor):
    """Color de un mapa de calor de 0 (frío) a 1 (caliente)."""
    if valor is None:
        return COLORES_ABC["VACÍO"]
    valor = max(0.0, min(1.0, valor))
    paleta = [(0.0, (255, 245, 204)), (0.5, (253, 141, 60)), (1.0, (189, 0, 38))]
    for (a, ca), (b, cb) in zip(paleta[:-1], paleta[1:]):
        if valor <= b:
            t = (valor - a) / (b - a)
            r, g, b_ = (int(ca[k] + (cb[k] - ca[k]) * t) for k in range(3))
            return f"rgb({r},{g},{b_})"
    return "rgb(189,0,38)"
