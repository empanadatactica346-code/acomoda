
import copy
import hashlib
import json
import threading
import time
from pathlib import Path
from datetime import datetime

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from modulos import plantillas
from modulos.analisis_ventas import (estadisticas_pedidos, filtrar_periodo, pares_comprobante, resumen_por_producto,
                                     ventas_por_mes, ventas_por_unidad_tiempo)
from modulos.cargar_catalogo import cargar_catalogo
from modulos.cargar_local import (COLORES_TRAZO, TIPOS_CAPA, analizar_dxf, imagen_desde_archivo, leer_dxf,
                                  leer_plantilla_local, local_a_tablas, local_de_ejemplo, local_desde_trazos,
                                  longitud_linea_px, tablas_a_local)
from modulos.cargar_ventas import (CAMPOS_VENTAS, aplicar_mapeo, ejemplo_fecha_legible, guardar_mapeo, leer_reporte,
                                   proponer_mapeo, texto_original_fecha, unir_con_catalogo)
from modulos.comun import (CARPETA_ENTRADA, CARPETA_RESULTADOS, PASOS, cargar_ajustes, cargar_perfiles, formato_soles,
                           pasos_a_invalidar, puede_abrir_paso, registrar_acta)
from modulos.indicadores import (NOMBRES_KPI, evaluar, kpi_con_costos_base, linea_base_actual,
                                 linea_base_aleatoria, linea_base_alfabetica, lista_reubicacion, sensibilidad,
                                 tabla_antes_despues, validar_solucion)
from modulos.interpretar_local import (PREGUNTAS_CONFIRMACION_LOCAL, agregar_estante_libre, generar_posiciones,
                                       medir_distancias, proponer_solucion, puede_confirmar_local, resumen_local,
                                       validar_local)
from modulos.cargar_local import _estante, local_vacio, preferencias_de
from modulos.articulo import decision, generar_paquete
from modulos.costeo import (calcular as calcular_costeo, cargar_escenarios as cargar_escenarios_costeo,
                            con_subtotales as calcular_costeo_tabla, guardar_escenarios as guardar_escenarios_costeo,
                            informe_excel, informe_word, tabla_inicial as tabla_costeo_inicial)
from modulos.diseno_racks import (ROTULO_PRECIOS, altura_disponible, ancho_pasillo_requerido_diseno, cargar_catalogo_racks,
                                  guardar_catalogo_racks, tipos_utilizables)
from modulos.evidencia import (ahorro_mensual_soles, analizar as analizar_evidencia, diagnostico, es_reproducible,
                               limites_evidencia, sensibilidad_conclusiones, validacion_tecnica, veredicto)
from modulos.medidas import indice_confiabilidad
from modulos.modelo_optimo import optimizar, optimizar_diseno
from modulos.normas import (CUMPLE, NO_APLICA, NO_CUMPLE, POR_VERIFICAR, cambiar_activa, cambiar_parametro,
                            cambiar_parametro_regla, estado_inicial, incompatibilidades_activas, parametros_activos,
                            reporte_final, resumen as resumen_normas, semaforo_local, texto_regla)
from modulos import guia, persistencia, reportes
from modulos.visual_2d import plano_2d
from modulos.visual_3d import figura_3d, guardar_html, recorrido_pedido

st.set_page_config(page_title="Acomoda", page_icon="📦", layout="wide")

AJUSTES = cargar_ajustes()
PERFILES = cargar_perfiles()["perfiles"]
ICONOS = {"confirmado": "✅", "advertencias": "⚠️", "pendiente": "⏳", "bloqueado": "🔒"}
COLOR_SEMAFORO = {CUMPLE: "green", NO_CUMPLE: "red", POR_VERIFICAR: "orange", NO_APLICA: "gray"}
CATALOGO_PRUEBA = CARPETA_ENTRADA / "lista_de_productos_limpio.xlsx"
VENTAS_PRUEBA = next(iter(sorted(CARPETA_ENTRADA.glob("reporte_ventas_producto_*.xlsx"))), None)

def iniciar_estado():
    valores = {"paso": 1, "confirmados": {}, "advertencias": {}, "perfil": "bazar", "modo": PERFILES["bazar"]["modo_sugerido"],
               "catalogo": None, "calidad": None, "resultado_catalogo": None, "origen_catalogo": None,
               "local": None, "origen_local": None, "correcciones_local": [], "correccion": None,
               "tabla_ventas": None, "origen_ventas": None, "mapeo_ventas": None, "ventas": None, "ventas_dentro": None,
               "resumen_union": None, "top_fuera": None, "estadisticas_mapeo": None,
               "normas": None, "solucion": None, "antes": None, "kpis": None, "escenarios": None, "tabla_sensibilidad": None,
               "economia": None, "figura_3d_local": None}
    for clave, valor in valores.items():
        st.session_state.setdefault(clave, valor)
    st.session_state.setdefault("id_sesion", st.session_state.get("_proyecto") or datetime.now().strftime("%Y%m%d-%H%M%S"))
    if st.session_state.normas is None:
        st.session_state.normas = estado_inicial(st.session_state.perfil)


def invalidar(paso):
    """Un cambio en el paso `paso` obliga a confirmar de nuevo ese paso y los siguientes."""
    for p in pasos_a_invalidar(paso):
        st.session_state.confirmados[p] = False
    if paso <= 5:
        st.session_state.solucion = None
        st.session_state.kpis = None
        st.session_state.escenarios = None
        st.session_state.tabla_sensibilidad = None
    if paso <= 7:
        for clave in ("evidencia", "sensibilidad_ev", "costeo", "costeo_resultado", "costeo_resultados", "informe_gerencial",
                      "paquete_articulo", "entregables"):
            st.session_state[clave] = None


def estado_paso(paso):
    if st.session_state.confirmados.get(paso):
        return "advertencias" if st.session_state.advertencias.get(paso) else "confirmado"
    return "pendiente" if puede_abrir_paso(paso, st.session_state.confirmados) else "bloqueado"


def responsable():
    return str(st.session_state.get("responsable", "")).strip()


def confirmar(paso, detalle=None, con_advertencias=False):
    registrar_acta(f"{paso}. {PASOS[paso]}", responsable(), True, detalle or {}, st.session_state.id_sesion)
    st.session_state.confirmados[paso] = True
    st.session_state.advertencias[paso] = con_advertencias
    if paso < 8:
        st.session_state.paso = paso + 1
    st.rerun()


def boton_confirmar(paso, texto_casilla, detalle=None, bloqueo=None, con_advertencias=False, clave=None):
    """Casilla + botón de confirmación con todas las verificaciones."""
    st.divider()
    marcado = st.checkbox(texto_casilla, key=clave or f"casilla_{paso}")
    motivo = bloqueo
    if not motivo and not responsable():
        motivo = "Escriba el nombre del responsable en la barra lateral (queda en el acta)."
    if not motivo and not marcado:
        motivo = "Marque la casilla de confirmación."
    if motivo:
        st.caption(f"🔒 {motivo}")
    if st.button("Confirmar y continuar ➜", type="primary", disabled=bool(motivo), key=f"confirmar_{paso}"):
        confirmar(paso, detalle, con_advertencias)


def factor_local():
    local = st.session_state.local
    if not local:
        return 1.0
    return AJUSTES["confiabilidad_local"].get(local.get("fuente", "excel"), 1.0)


def resumen_productos():
    """Resumen de ventas por producto con el periodo y la base elegidos en el Paso 3."""
    if st.session_state.ventas_dentro is None or st.session_state.catalogo is None:
        return None
    periodo = st.session_state.get("periodo_elegido")
    desde, hasta = (periodo if periodo and len(periodo) == 2 else (None, None))
    base = "recientes" if str(st.session_state.get("base_elegida", "")).startswith("Últimos") else "periodo"
    meses = st.session_state.get("meses_elegidos", 3)
    clave = (id(st.session_state.ventas_dentro), str(desde), str(hasta), base, meses, id(st.session_state.catalogo))
    if st.session_state.get("_clave_resumen") != clave:
        st.session_state._resumen = resumen_por_producto(st.session_state.ventas_dentro, st.session_state.catalogo, desde, hasta,
                                                         base, meses)
        st.session_state._clave_resumen = clave
    return st.session_state._resumen


def ventas_del_periodo():
    periodo = st.session_state.get("periodo_elegido")
    desde, hasta = (periodo if periodo and len(periodo) == 2 else (None, None))
    return filtrar_periodo(st.session_state.ventas_dentro, desde, hasta)


@st.cache_data(show_spinner=False)
def plantilla_vacia(tipo):
    if tipo == "catalogo":
        return plantillas.generar_plantilla_catalogo()
    if tipo == "ventas":
        return plantillas.generar_plantilla_ventas()
    return plantillas.generar_plantilla_local()


def parametros_actuales():
    return parametros_activos(st.session_state.normas, st.session_state.modo, st.session_state.local)

def cambiar_perfil():
    st.session_state.normas = estado_inicial(st.session_state.perfil)
    st.session_state.modo = PERFILES[st.session_state.perfil]["modo_sugerido"]
    if st.session_state.resultado_catalogo is not None:
        st.session_state.origen_catalogo = None  # se vuelve a estimar con las medidas típicas del nuevo rubro
    invalidar(1)


@st.cache_data(show_spinner=False)
def manual_en_cache():
    return guia.manual_docx()


@st.dialog("Recorrido de Acomoda", width="large")
def recorrido():
    i = st.session_state.get("_recorrido", 0)
    icono, titulo, texto, elementos = guia.RECORRIDO[i]
    puntos = "".join(f'<span class="{"act" if k == i else ""}">●</span>' for k in range(len(guia.RECORRIDO)))
    st.html(f'<div class="ac-icono">{icono}</div><div class="ac-puntos">{puntos}</div>')
    st.subheader(titulo)
    st.markdown(texto)
    for etiqueta, explicacion in elementos:
        st.html(f'<div class="ac-tarjeta"><b>{etiqueta}</b><br>{explicacion}</div>')
    atras, saltar, siguiente = st.columns([1, 1, 1.4])
    if i > 0 and atras.button("⬅️ Anterior", width="stretch", key="tour_atras"):
        st.session_state._recorrido = i - 1
        st.rerun()
    if i < len(guia.RECORRIDO) - 1:
        if saltar.button("Saltar", width="stretch", key="tour_saltar"):
            cerrar_recorrido()
        if siguiente.button("Siguiente ➜", type="primary", width="stretch", key="tour_siguiente"):
            st.session_state._recorrido = i + 1
            st.rerun()
    elif siguiente.button("🚀 Empezar", type="primary", width="stretch", key="tour_fin"):
        cerrar_recorrido()


def cerrar_recorrido():
    guia.marcar_vista()
    st.session_state._recorrido = None
    st.rerun()


def barra_lateral():
    with st.sidebar:
        st.title("📦 Acomoda")
        if st.button("📘 Tutorial paso a paso", width="stretch", key="abrir_tutorial"):
            st.session_state._ver_tutorial = True
            st.rerun()
        columna_a, columna_b = st.columns(2)
        if columna_a.button("🎓 Recorrido", width="stretch", key="abrir_recorrido",
                            help="Vuelve a mostrar la presentación de bienvenida: qué hace cada botón y sección."):
            st.session_state._recorrido = 0
            st.rerun()
        columna_b.download_button("⬇️ Manual", data=manual_en_cache(), file_name="Manual_Acomoda.docx",
                                  mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                                  width="stretch", key="descargar_manual",
                                  help="Descarga el manual detallado del software en Word (para imprimir o compartir).")
        st.caption("Distribución óptima de productos en estantes · modelo de asignación (PuLP + CBC)")
        st.text_input("Responsable (queda en el acta)", key="responsable", placeholder="Nombre y apellido")
        st.selectbox("Perfil de rubro", list(PERFILES), key="perfil", format_func=lambda p: PERFILES[p]["nombre"],
                     on_change=cambiar_perfil, help="Precarga normas, reglas, medidas típicas y factores de exhibición.")
        st.radio("Modo", ["almacen", "tienda"], key="modo", horizontal=True,
                 format_func=lambda m: "Almacén (picking)" if m == "almacen" else "Tienda (exhibición)",
                 on_change=lambda: invalidar(4))
        st.divider()
        st.markdown("**Pasos**")
        for numero, nombre in PASOS.items():
            estado = estado_paso(numero)
            if st.button(f"{ICONOS[estado]} {numero}. {nombre}", key=f"ir_{numero}", disabled=estado == "bloqueado",
                         type="primary" if st.session_state.paso == numero else "secondary", width="stretch"):
                st.session_state.paso = numero
                st.rerun()
        st.caption("✅ confirmado · ⚠️ con advertencias · ⏳ pendiente · 🔒 bloqueado")
        st.divider()
        st.markdown("**💾 Su progreso se guarda solo**")
        st.caption("Todo se guarda solo en esta computadora (nada sale a internet). Al volver a abrir Acomoda "
                   "continúa el último proyecto.")
        st.code(f"Código de proyecto: {st.session_state.get('_proyecto', '')}", language=None)
        if st.button("Empezar un proyecto nuevo", help="Abre un proyecto vacío. El actual sigue guardado con su código."):
            nuevo_proyecto()
        if st.button("Reiniciar todo", help="Borra los datos de ESTE proyecto (no se pueden recuperar)."):
            persistencia.borrar(st.session_state.get("_proyecto"))
            for clave in list(st.session_state.keys()):
                if clave != "responsable" and not str(clave).startswith("_"):
                    del st.session_state[clave]
            st.rerun()


def encabezado():
    paso = st.session_state.paso
    columna_titulo, columna_indice = st.columns([3, 1])
    columna_titulo.title(f"Paso {paso}. {PASOS[paso]}")
    columna_titulo.html(guia.barra_progreso(paso, {p for p, v in st.session_state.confirmados.items() if v}))
    confiabilidad = indice_confiabilidad(st.session_state.catalogo, resumen_productos(), factor_local())
    columna_indice.metric("Índice de confiabilidad", f"{confiabilidad['indice']:.0f} %",
                          help=f"% de las ventas en soles con medidas reales ({confiabilidad['medidas_reales']:.0f} %, base: "
                               f"{confiabilidad['base']}) × precisión de la fuente del local ({confiabilidad['factor_local']:.0%}).")
    if confiabilidad["indice"] < 50 and st.session_state.catalogo is not None:
        st.warning(f"Confiabilidad baja ({confiabilidad['indice']:.0f} %): la propuesta usa muchas medidas estimadas. "
                   "Mida primero los productos que más venden (plantilla prellenada del Paso 1 o 3).")
    if st.session_state.local and st.session_state.local.get("es_ejemplo"):
        st.error("Se está usando el LOCAL DE EJEMPLO — EJEMPLO, NO ES REAL. Úselo solo para aprender el programa.")

@st.cache_data(show_spinner=False, max_entries=4)
def catalogo_en_cache(contenido, nombre, perfil):
    """Lectura del catálogo en caché: se repite solo si cambia el archivo (su contenido) o el perfil."""
    return cargar_catalogo(contenido, nombre, perfil)


def procesar_catalogo(contenido, nombre, origen):
    with st.spinner("Leyendo y limpiando el catálogo…"):
        resultado = copy.deepcopy(catalogo_en_cache(contenido, nombre, st.session_state.perfil))
    st.session_state.resultado_catalogo = resultado
    st.session_state.catalogo_bytes = contenido
    st.session_state.catalogo_nombre = nombre
    st.session_state.catalogo = resultado["catalogo"]
    st.session_state.calidad = resultado["calidad"]
    st.session_state.origen_catalogo = origen
    st.session_state.plantilla_prellenada = None
    invalidar(1)


def paso_1():
    st.write("Suba su catálogo con las **medidas de los productos** (largo, ancho y alto en cm, peso en kg). "
             "Descargue la plantilla, llénela en Excel y súbala. Si solo tiene el catálogo de su sistema, súbalo tal cual: "
             "el programa le devolverá la plantilla **prellenada** para que mida lo que falta.")
    izquierda, derecha = st.columns(2)
    with izquierda:
        st.download_button("⬇️ Descargar plantilla de catálogo", plantilla_vacia("catalogo"), "plantilla_catalogo.xlsx",
                           width="stretch")
        st.caption("La plantilla trae INSTRUCCIONES, DATOS (con listas desplegables) y EJEMPLO.")
        if CATALOGO_PRUEBA.exists() and st.button("Usar el catálogo de prueba (tienda de Juliaca)", width="stretch"):
            procesar_catalogo(CATALOGO_PRUEBA.read_bytes(), CATALOGO_PRUEBA.name, ("prueba", CATALOGO_PRUEBA.name))
    with derecha:
        archivo = st.file_uploader("Subir catálogo (plantilla llena o catálogo propio)", type=["xlsx", "xlsm", "xls", "csv"])
        if archivo is not None and st.session_state.origen_catalogo != (archivo.name, archivo.size):
            procesar_catalogo(archivo.getvalue(), archivo.name, (archivo.name, archivo.size))
    with st.expander("✍️ ¿No tiene archivo? Escriba sus productos aquí"):
        st.caption("Un renglón por producto. Las medidas son de UNA unidad. Si no sabe una medida, déjela vacía: el programa la estima.")
        tabla = st.session_state.get("catalogo_manual")
        if tabla is None:
            tabla = pd.DataFrame([{"codigo_barras": "", "producto": "", "categoria": "", "precio_venta": None, "stock": None,
                                   "largo_cm": None, "ancho_cm": None, "alto_cm": None, "peso_kg": None}])
        editada = st.data_editor(tabla, num_rows="dynamic", hide_index=True, key="editor_catalogo_manual", column_config={
            "codigo_barras": st.column_config.TextColumn("Código de barras", help="Igual al de su sistema de ventas."),
            "producto": st.column_config.TextColumn("Nombre del producto"),
            "categoria": st.column_config.TextColumn("Categoría", help="BEBIDAS, LIMPIEZA, HOGAR…"),
            "precio_venta": st.column_config.NumberColumn("Precio (S/)", min_value=0.0, step=0.1),
            "stock": st.column_config.NumberColumn("Stock (unidades)", min_value=0, step=1),
            "largo_cm": st.column_config.NumberColumn("Largo (cm)", min_value=0.0),
            "ancho_cm": st.column_config.NumberColumn("Ancho (cm)", min_value=0.0),
            "alto_cm": st.column_config.NumberColumn("Alto (cm)", min_value=0.0),
            "peso_kg": st.column_config.NumberColumn("Peso (kg)", min_value=0.0)})
        if st.button("Usar estos productos", type="primary"):
            filas = editada[editada["producto"].astype(str).str.strip() != ""]
            if filas.empty:
                st.error("Escriba al menos un producto con nombre.")
            else:
                st.session_state.catalogo_manual = editada
                procesar_catalogo(filas.to_csv(index=False).encode("utf-8"), "catalogo_formulario.csv",
                                  ("formulario", datetime.now().isoformat()))
                st.rerun()
    if st.session_state.origen_catalogo is None and st.session_state.get("catalogo_bytes") is not None:
        procesar_catalogo(st.session_state.catalogo_bytes, st.session_state.catalogo_nombre, ("re-estimado", "perfil"))
    resultado = st.session_state.resultado_catalogo
    if resultado is None:
        st.info("Aún no se ha subido el catálogo.")
        return
    bloqueo = None
    validacion = resultado.get("validacion")
    if validacion and validacion["rechazada"]:
        st.error(validacion["rechazada"])
        return
    for aviso in resultado["avisos"]:
        st.info(aviso)
    if resultado["catalogo"] is None:
        st.error("No se pudo leer el catálogo. Use la plantilla.")
        return
    if validacion and validacion["errores"]:
        st.error(f"La plantilla tiene {len(validacion['errores'])} celdas con error:")
        st.dataframe(pd.DataFrame({"Error": [plantillas.describir_error(e) for e in validacion["errores"]]}), height=220)
        st.download_button("⬇️ Descargar el archivo con los errores marcados en rojo",
                           plantillas.archivo_con_errores(st.session_state.catalogo_bytes, validacion["errores"]),
                           "catalogo_con_errores.xlsx")
        if not st.checkbox("Continuar de todas formas: las celdas con error se tratarán como vacías (se estimarán)."):
            bloqueo = "Corrija los errores de la plantilla o acepte tratarlos como vacíos."
    if resultado["mapeo"]:
        with st.expander("Columnas reconocidas en su catálogo"):
            st.dataframe(pd.DataFrame([{"Dato de Acomoda": k, "Columna de su archivo": v} for k, v in resultado["mapeo"].items()]),
                         hide_index=True)
    reporte_calidad_catalogo()
    catalogo = st.session_state.catalogo
    faltan = int((catalogo["origen_medidas"] != "real").sum())
    st.subheader("Medidas que faltan")
    usar_estimadas = True
    if faltan:
        st.write(f"**{faltan} de {len(catalogo)} productos** no tienen las cuatro medidas reales.")
        plantilla_prellenada(catalogo)
        usar_estimadas = st.toggle("Continuar por ahora con medidas ESTIMADAS para lo que falta", value=True,
                                   help="El estimador lee el nombre (625ML, 36G, X20, 7 PCS…) y usa medidas típicas del rubro. "
                                        "Todo lo estimado queda marcado y baja el índice de confiabilidad.")
        if not usar_estimadas:
            bloqueo = bloqueo or "Faltan medidas reales: complete la plantilla prellenada o permita usar estimadas."
    with st.expander("Ver el catálogo interpretado"):
        columnas = ["id_producto", "producto", "categoria", "origen_categoria", "precio_venta", "stock", "largo_cm", "ancho_cm",
                    "alto_cm", "peso_kg", "origen_medidas", "metodo_medidas", "fragil", "peligroso", "valor_alto", "perecible"]
        st.dataframe(catalogo[columnas], height=320, hide_index=True)
    calidad = st.session_state.calidad
    boton_confirmar(1, "Confirmo que los datos del catálogo son correctos",
                    {"archivo": st.session_state.catalogo_nombre, "productos": calidad["productos"],
                     "medidas_reales": calidad["con_medida_real"], "medidas_estimadas": calidad["sin_medida_real"],
                     "codigos_repetidos": calidad["repeticiones"]},
                    bloqueo=bloqueo, con_advertencias=faltan > 0)


def reporte_calidad_catalogo():
    calidad = st.session_state.calidad
    st.subheader("Reporte de calidad")
    columnas = st.columns(4)
    columnas[0].metric("Productos", f"{calidad['productos']:,}")
    columnas[1].metric("Filas vacías descartadas", f"{calidad['filas_vacias_descartadas']:,}",
                       help=f"De {calidad['filas_leidas']:,} filas leídas.")
    columnas[2].metric("Códigos repetidos consolidados", calidad["repeticiones"], help="Se sumó su stock.")
    columnas[3].metric("Sin medida real", f"{calidad['sin_medida_real']:,}")
    columnas = st.columns(4)
    columnas[0].metric("Categoría del archivo", calidad["categoria_dato"])
    columnas[1].metric("Categoría por palabras del nombre", calidad["categoria_regla"])
    columnas[2].metric("SIN CATEGORÍA", calidad["sin_categoria"])
    columnas[3].metric("Precio de venta en cero", len(calidad["precio_venta_cero"]))
    detalles = [("Códigos repetidos (consolidados)", calidad["codigos_repetidos"]),
                ("Medidas imposibles (se descartaron)", calidad["medidas_imposibles"]),
                ("Valores atípicos", calidad["atipicos"]), ("Precio de venta en cero", calidad["precio_venta_cero"]),
                ("Precio de venta menor que el de compra", calidad["venta_menor_compra"]),
                ("Filas sin nombre de producto", calidad["sin_nombre"])]
    for titulo, lista in detalles:
        if lista:
            with st.expander(f"{titulo}: {len(lista)}"):
                st.dataframe(pd.DataFrame(lista), hide_index=True)


def plantilla_prellenada(catalogo):
    resumen = resumen_productos()
    if resumen is not None:
        importancia, nota = resumen[["id_producto", "ventas_soles"]], None
    else:
        importancia = catalogo[["id_producto"]].assign(
            ventas_soles=(catalogo["stock"].fillna(0) * catalogo["precio_venta"].fillna(0)).values)
        nota = ("Orden provisional por valor del stock (stock × precio): aún no se subieron las ventas. "
                "En el Paso 3 podrá descargarla ordenada por ventas reales.")
    if resumen is not None:
        total = resumen["ventas_soles"].sum()
        ordenado = resumen.merge(catalogo[["id_producto", "origen_medidas"]], on="id_producto").sort_values("ventas_soles", ascending=False)
        acumulado = ordenado["ventas_soles"].cumsum() / total if total else ordenado["ventas_soles"] * 0
        medir = ordenado[(acumulado.shift(fill_value=0) < 0.8) & (ordenado["origen_medidas"] != "real")]
        st.write(f"Para cubrir el **80 % de las ventas** hay que medir **{len(medir)} productos** "
                 f"(ya ordenados de mayor a menor venta en la plantilla).")
    else:
        st.caption(nota)
    if st.button("Preparar plantilla prellenada"):
        with st.spinner("Generando…"):
            st.session_state.plantilla_prellenada = plantillas.generar_plantilla_catalogo(catalogo, importancia, nota)
    if st.session_state.get("plantilla_prellenada"):
        st.download_button("⬇️ Descargar plantilla prellenada (ordenada por importancia)",
                           st.session_state.plantilla_prellenada, "plantilla_catalogo_prellenada.xlsx", type="primary")


# ======================================================================================
# Paso 2. Local
# ======================================================================================

def poner_local(local, origen):
    st.session_state.local = local
    st.session_state.origen_local = origen
    st.session_state.correcciones_local = []
    st.session_state.correccion = None
    st.session_state.figura_3d_local = None
    invalidar(2)


def paso_2():
    st.write("Entregue el plano o las medidas del local por una de estas vías. Todas terminan en la pantalla "
             "**«Esto es lo que entendí»**, donde usted revisa y confirma.")
    via = st.radio("¿Cómo entregará el local?", ["Formulario paso a paso (lo más fácil)", "A. Plantilla Excel",
                                                  "B. Archivo DXF (AutoCAD u otro CAD)",
                                                  "C. Imagen o PDF del plano (menos precisa)",
                                                  "D. Local de ejemplo (EJEMPLO, NO ES REAL)"], horizontal=False)
    if via.startswith("Formulario"):
        via_formulario()
    elif via.startswith("A"):
        via_excel()
    elif via.startswith("B"):
        via_dxf()
    elif via.startswith("C"):
        via_imagen()
    else:
        st.info("Local ficticio de 16 × 12 m con 29 estantes, columnas, extintores, salida de emergencia y zonas.")
        if st.button("Cargar el local de ejemplo"):
            poner_local(local_de_ejemplo(), ("ejemplo",))
    if st.session_state.local:
        st.divider()
        pantalla_entendi()


def via_excel():
    izquierda, derecha = st.columns(2)
    izquierda.download_button("⬇️ Descargar plantilla del local", plantilla_vacia("local"), "plantilla_local.xlsx", width="stretch")
    izquierda.caption("Hojas: LOCAL, OBSTACULOS, ZONAS, EQUIPOS, PASILLOS, PREFERENCIAS_Y_PRESUPUESTO y ESTANTES_EXISTENTES "
                      "(opcional: solo si tiene estantes que conservar). No hace falta medir estantes: el programa diseña los racks.")
    archivo = derecha.file_uploader("Subir plantilla del local llena", type=["xlsx"], key="subir_local")
    if archivo is not None and st.session_state.origen_local != ("excel", archivo.name, archivo.size):
        local, validacion = leer_plantilla_local(archivo.getvalue())
        st.session_state.validacion_local = validacion
        st.session_state.local_bytes = archivo.getvalue()
        if local is not None:
            poner_local(local, ("excel", archivo.name, archivo.size))
        else:
            st.error(validacion["rechazada"])
    validacion = st.session_state.get("validacion_local")
    if validacion and validacion["errores"] and st.session_state.origen_local and st.session_state.origen_local[0] == "excel":
        st.error(f"La plantilla del local tiene {len(validacion['errores'])} celdas con error (esas celdas se leyeron vacías):")
        st.dataframe(pd.DataFrame({"Error": [plantillas.describir_error(e) for e in validacion["errores"]]}), height=200)
        st.download_button("⬇️ Descargar el archivo con los errores marcados en rojo",
                           plantillas.archivo_con_errores(st.session_state.local_bytes, validacion["errores"]), "local_con_errores.xlsx")


PAREDES = {"abajo (frente)": "abajo", "derecha": "derecha", "arriba (fondo)": "arriba", "izquierda": "izquierda"}
ESQUINAS = {"abajo a la izquierda": (0, 0), "abajo a la derecha": (1, 0), "arriba a la izquierda": (0, 1), "arriba a la derecha": (1, 1)}


def _en_pared(local, id_, tipo, pared, distancia, ancho):
    """Puerta o salida de `ancho` metros sobre una pared, a `distancia` metros de la esquina izquierda/inferior."""
    largo_local, ancho_local, grosor = local["largo_m"], local["ancho_m"], 0.2
    if pared in ("abajo", "arriba"):
        x, y, lx, ly = min(distancia, largo_local - ancho), 0.0 if pared == "abajo" else ancho_local - grosor, ancho, grosor
    else:
        x, y, lx, ly = 0.0 if pared == "izquierda" else largo_local - grosor, min(distancia, ancho_local - ancho), grosor, ancho
    return {"id": id_, "tipo": tipo, "x_m": round(max(x, 0), 2), "y_m": round(max(y, 0), 2), "largo_m": lx, "ancho_m": ly, "alto_m": 2.2}


def via_formulario():
    """Asistente de 4 preguntas: no hace falta Excel ni coordenadas; el programa acomoda los estantes solo."""
    paso = st.session_state.setdefault("form_paso", 1)
    st.progress(paso / 4, text=f"Pregunta {paso} de 4")
    datos = st.session_state.setdefault("form_local", {})
    if paso == 1:
        st.markdown("#### 1. ¿Cuánto mide el local? (en metros)")
        st.caption("Mida de pared a pared por dentro. Ejemplo: un local de 16 metros de fondo por 12 de frente.")
        columnas = st.columns(3)
        datos["largo_m"] = columnas[0].number_input("Largo (metros)", 1.0, 200.0, float(datos.get("largo_m", 10.0)), 0.1)
        datos["ancho_m"] = columnas[1].number_input("Ancho (metros)", 1.0, 200.0, float(datos.get("ancho_m", 8.0)), 0.1)
        datos["altura_libre_m"] = columnas[2].number_input("Altura hasta el techo (metros)", 1.5, 20.0,
                                                           float(datos.get("altura_libre_m", 3.0)), 0.1)
    elif paso == 2:
        st.markdown("#### 2. Puertas y salida de emergencia")
        columnas = st.columns(3)
        datos["puerta_pared"] = columnas[0].selectbox("¿En qué pared está la puerta principal?", list(PAREDES),
                                                      index=list(PAREDES).index(datos.get("puerta_pared", "abajo (frente)")))
        datos["puerta_dist"] = columnas[1].number_input("Distancia desde la esquina (metros)", 0.0, 200.0,
                                                        float(datos.get("puerta_dist", 1.0)), 0.1)
        datos["puerta_ancho"] = columnas[2].number_input("Ancho de la puerta (metros)", 0.6, 10.0, float(datos.get("puerta_ancho", 1.2)), 0.1)
        datos["tiene_salida"] = st.checkbox("Tengo una salida de emergencia aparte de la puerta principal",
                                            value=datos.get("tiene_salida", False))
        if datos["tiene_salida"]:
            columnas = st.columns(3)
            datos["salida_pared"] = columnas[0].selectbox("Pared de la salida de emergencia", list(PAREDES),
                                                          index=list(PAREDES).index(datos.get("salida_pared", "arriba (fondo)")))
            datos["salida_dist"] = columnas[1].number_input("Distancia desde la esquina (metros) ", 0.0, 200.0,
                                                            float(datos.get("salida_dist", 1.0)), 0.1)
            datos["salida_ancho"] = columnas[2].number_input("Ancho (metros) ", 0.6, 10.0, float(datos.get("salida_ancho", 1.2)), 0.1)
        else:
            st.caption("Se usará la puerta principal como salida de emergencia.")
        datos["despacho"] = st.selectbox("¿Dónde está la caja o el despacho?", list(ESQUINAS),
                                         index=list(ESQUINAS).index(datos.get("despacho", "abajo a la izquierda")))
    elif paso == 3:
        st.markdown("#### 3. ¿Tiene estantes que quiere conservar? (opcional)")
        st.caption("NO hace falta: el programa diseña los racks. Solo si quiere conservar estantes que ya tiene, escriba un renglón "
                   "por cada TIPO e indique cuántos hay; el programa los acomoda dejando pasillos y salidas libres. Deje la tabla "
                   "vacía para diseñar desde cero.")
        tabla = datos.get("estantes_tabla")
        if tabla is None:
            tabla = pd.DataFrame(columns=["cantidad", "tipo", "largo_m", "fondo_m", "alto_m", "niveles", "capacidad_kg_nivel"])
        tipos = next(c["lista"] for c in plantillas.HOJAS_LOCAL["ESTANTES_EXISTENTES"] if c["nombre"] == "tipo")
        datos["estantes_tabla"] = st.data_editor(tabla, num_rows="dynamic", hide_index=True, key="form_estantes", column_config={
            "cantidad": st.column_config.NumberColumn("¿Cuántos?", min_value=1, step=1, required=True),
            "tipo": st.column_config.SelectboxColumn("Tipo", options=tipos, required=True),
            "largo_m": st.column_config.NumberColumn("Largo (metros)", min_value=0.3, step=0.1, required=True),
            "fondo_m": st.column_config.NumberColumn("Fondo (metros)", min_value=0.2, step=0.05, required=True),
            "alto_m": st.column_config.NumberColumn("Alto (metros)", min_value=0.3, step=0.1, required=True),
            "niveles": st.column_config.NumberColumn("Niveles (bandejas)", min_value=1, step=1, required=True),
            "capacidad_kg_nivel": st.column_config.NumberColumn("Peso por nivel (kg)", min_value=1.0, step=5.0,
                                                                help="Si no lo sabe, deje 80 kg.")})
    else:
        st.markdown("#### 4. ¿Hay columnas, extintores o tableros eléctricos?")
        st.caption("Opcional. Indique la posición midiendo desde la esquina de abajo a la izquierda (x = hacia la derecha, "
                   "y = hacia arriba). Si no tiene, deje la tabla vacía.")
        tabla = datos.get("obstaculos_tabla")
        if tabla is None:
            tabla = pd.DataFrame(columns=["tipo", "x_m", "y_m"])
        datos["obstaculos_tabla"] = st.data_editor(tabla, num_rows="dynamic", hide_index=True, key="form_obstaculos", column_config={
            "tipo": st.column_config.SelectboxColumn("Qué es", options=["columna", "extintor", "tablero"], required=True),
            "x_m": st.column_config.NumberColumn("x (metros)", min_value=0.0, step=0.1, required=True),
            "y_m": st.column_config.NumberColumn("y (metros)", min_value=0.0, step=0.1, required=True)})
    columnas = st.columns([1, 1, 3])
    if paso > 1 and columnas[0].button("⬅️ Atrás", key="form_atras"):
        st.session_state.form_paso -= 1
        st.rerun()
    if paso < 4 and columnas[1].button("Siguiente ➡️", type="primary", key="form_siguiente"):
        st.session_state.form_paso += 1
        st.rerun()
    if paso == 4 and columnas[1].button("✅ Crear mi local", type="primary", key="form_crear"):
        with st.spinner("Acomodando los estantes en el local…"):
            local, faltaron = local_desde_formulario(datos)
        poner_local(local, ("formulario", datetime.now().isoformat()))
        if faltaron:
            st.session_state.local.setdefault("avisos_lectura", []).append(
                f"No entraron {faltaron} estantes en el espacio libre: revise las medidas del local o de los estantes.")
        st.rerun()


def local_desde_formulario(datos):
    local = local_vacio()
    local.update(nombre="Mi local", largo_m=datos["largo_m"], ancho_m=datos["ancho_m"], altura_libre_m=datos["altura_libre_m"],
                 fuente="excel")
    local["obstaculos"].append(_en_pared(local, "P1", "puerta", PAREDES[datos["puerta_pared"]], datos["puerta_dist"], datos["puerta_ancho"]))
    if datos.get("tiene_salida"):
        local["obstaculos"].append(_en_pared(local, "S1", "salida_emergencia", PAREDES[datos["salida_pared"]], datos["salida_dist"],
                                             datos["salida_ancho"]))
    else:
        salida = _en_pared(local, "S1", "salida_emergencia", PAREDES[datos["puerta_pared"]], datos["puerta_dist"], datos["puerta_ancho"])
        local["obstaculos"].append(salida)
    tamanos = {"columna": (0.4, 0.4, local["altura_libre_m"]), "extintor": (0.3, 0.2, 1.5), "tablero": (0.6, 0.2, 1.8)}
    obstaculos = datos.get("obstaculos_tabla")
    if obstaculos is not None:
        for numero, fila in enumerate(obstaculos.dropna(subset=["tipo", "x_m", "y_m"]).to_dict("records"), start=1):
            lx, ly, alto = tamanos[fila["tipo"]]
            local["obstaculos"].append({"id": f"{fila['tipo'][0].upper()}{numero}", "tipo": fila["tipo"], "x_m": float(fila["x_m"]),
                                        "y_m": float(fila["y_m"]), "largo_m": lx, "ancho_m": ly, "alto_m": alto})
    ex, ey = ESQUINAS[datos["despacho"]]
    local["zonas"].append({"id": "Z1", "tipo": "despacho", "x_m": round(ex * (local["largo_m"] - 2.0), 2),
                           "y_m": round(ey * (local["ancho_m"] - 1.5), 2), "largo_m": 2.0, "ancho_m": 1.5})
    local["pasillos"] = [{"uso": "peatonal", "ancho_min_m": 0.9}, {"uso": "evacuacion", "ancho_min_m": 1.2}]
    local["equipos"] = [{"tipo": "manual", "radio_giro_m": 0, "altura_max_m": 1.9}]
    parametros = parametros_activos(st.session_state.normas, st.session_state.modo, local)
    tabla = datos.get("estantes_tabla")
    if tabla is not None and len(tabla.dropna(how="all")):
        local["preferencias"]["modo_diseno"] = "C"  # declaró estantes que quiere conservar
    faltaron, numero = 0, 1
    tabla = datos.get("estantes_tabla")
    filas = [] if tabla is None else tabla.dropna(subset=["cantidad", "largo_m", "fondo_m", "alto_m"]).to_dict("records")
    for fila in filas:
        for _ in range(int(fila["cantidad"])):
            modelo = _estante(f"E{numero}", 0, 0, 0, tipo=fila.get("tipo") or "gondola", largo=float(fila["largo_m"]),
                              fondo=float(fila["fondo_m"]), alto=float(fila["alto_m"]), niveles=int(fila.get("niveles") or 5),
                              capacidad=float(fila.get("capacidad_kg_nivel") or 80))
            local, nuevo = agregar_estante_libre(local, parametros, paso=0.25, modelo=modelo, nuevo_id=f"E{numero}")
            if nuevo is not None:
                nuevo["existente"] = True
            if nuevo is None:
                faltaron += 1
            numero += 1
    return local, faltaron


def via_dxf():
    archivo = st.file_uploader("Subir archivo DXF", type=["dxf"], key="subir_dxf")
    if archivo is None:
        st.caption("Capas reconocidas automáticamente: MUROS, COLUMNAS, PUERTAS, ESTANTES, SALIDAS, EXTINTORES, TABLEROS, "
                   "ESCALERAS, CONTORNO. Si sus capas tienen otros nombres, el asistente le dejará asignarlas.")
        return
    if st.session_state.get("dxf_origen") != (archivo.name, archivo.size):
        try:
            st.session_state.dxf_info = analizar_dxf(archivo.getvalue())
            st.session_state.dxf_origen = (archivo.name, archivo.size)
        except Exception as error:
            st.error(f"No se pudo leer el DXF: {error}")
            return
    info = st.session_state.dxf_info
    st.write(f"Capas encontradas: **{len(info['capas'])}**. Unidad detectada: **{info['unidad']}** (por {info['detectada_por']}).")
    tabla = pd.DataFrame([{"Capa": c, "Entidades": n, "Es": info["mapeo"].get(c, "ignorar")} for c, n in info["capas"].items()])
    editada = st.data_editor(tabla, hide_index=True, disabled=["Capa", "Entidades"],
                             column_config={"Es": st.column_config.SelectboxColumn("Qué representa", options=TIPOS_CAPA, required=True)})
    unidades = {"milímetros": 0.001, "centímetros": 0.01, "metros": 1.0, "pulgadas": 0.0254, "pies": 0.3048}
    columnas = st.columns(2)
    unidad = columnas[0].selectbox("Confirme la unidad del dibujo", list(unidades), index=list(unidades).index(info["unidad"]))
    altura = columnas[1].number_input("Altura libre útil del local (m)", 1.5, 20.0, 3.0, 0.1)
    if st.button("Leer el DXF con estas capas y esta unidad"):
        mapeo = dict(zip(editada["Capa"], editada["Es"]))
        local = leer_dxf(archivo.getvalue(), mapeo, unidades[unidad], altura)
        poner_local(local, ("dxf", archivo.name, unidad, json.dumps(mapeo)))


def via_imagen():
    st.warning("Esta vía es la menos precisa: el índice de confiabilidad se multiplica por "
               f"{AJUSTES['confiabilidad_local']['imagen']:.0%}. Use la plantilla Excel si puede medir el local.")
    archivo = st.file_uploader("Subir imagen (PNG/JPG) o PDF del plano", type=["png", "jpg", "jpeg", "pdf"], key="subir_imagen")
    if archivo is None:
        return
    try:
        from streamlit_drawable_canvas import st_canvas
    except Exception as error:  # el componente no está disponible
        st.error(f"No se pudo cargar el lienzo de dibujo ({error}). Use la plantilla Excel.")
        return
    imagen = imagen_desde_archivo(archivo.getvalue(), archivo.name)
    ancho_lienzo = 900
    alto_lienzo = int(imagen.height * ancho_lienzo / imagen.width)
    imagen = imagen.resize((ancho_lienzo, alto_lienzo))
    st.markdown("**1) Calibre la escala:** dibuje una línea entre dos puntos cuya distancia real conozca (por ejemplo, un muro).")
    calibracion = st_canvas(stroke_width=3, stroke_color="#ff00ff", background_image=imagen, height=alto_lienzo,
                            width=ancho_lienzo, drawing_mode="line", key="lienzo_escala")
    lineas = [o for o in ((calibracion.json_data or {}).get("objects", [])) if o.get("type") == "line"]
    distancia = st.number_input("Distancia real de la línea (m)", 0.1, 500.0, 5.0, 0.1)
    if not lineas:
        st.caption("Dibuje la línea de calibración para continuar.")
        return
    pixeles = longitud_linea_px(lineas[-1])
    metros_por_pixel = distancia / max(pixeles, 1)
    st.success(f"Escala: {pixeles:.0f} px = {distancia} m → 1 px = {metros_por_pixel * 100:.2f} cm")
    st.markdown("**2) Trace los elementos:** elija el tipo y dibuje rectángulos. El color indica el tipo.")
    tipo = st.selectbox("Tipo de elemento a dibujar", list(COLORES_TRAZO), format_func=lambda t: t.replace("_", " "))
    trazos = st_canvas(stroke_width=2, stroke_color=COLORES_TRAZO[tipo], fill_color="rgba(0,0,0,0.05)", background_image=imagen,
                       height=alto_lienzo, width=ancho_lienzo, drawing_mode="rect", key="lienzo_trazos")
    altura = st.number_input("Altura libre útil del local (m) ", 1.5, 20.0, 3.0, 0.1)
    objetos = (trazos.json_data or {}).get("objects", [])
    st.caption(f"{len(objetos)} elementos dibujados. Leyenda: " + ", ".join(f"{t.replace('_', ' ')} = {c}" for t, c in COLORES_TRAZO.items()))
    if st.button("Convertir los trazos en el local"):
        poner_local(local_desde_trazos(objetos, metros_por_pixel, altura), ("imagen", archivo.name, len(objetos)))


def pantalla_entendi():
    local = st.session_state.local
    parametros = parametros_actuales()
    avisos = validar_local(local, parametros)
    st.session_state.avisos_local = avisos
    posiciones = generar_posiciones(local, parametros) if local.get("estantes") and local.get("largo_m") else None
    st.header("Esto es lo que entendí")
    for aviso in local.get("avisos_lectura", []):
        st.info(aviso)
    izquierda, derecha = st.columns([1, 2])
    with izquierda:
        st.dataframe(resumen_local(local, posiciones), hide_index=True, height=520)
    with derecha:
        pestana_2d, pestana_3d = st.tabs(["Plano 2D", "Vista 3D previa"])
        with pestana_2d:
            ids = {a["id"] for a in avisos if a["tabla"] == "ESTANTES"}
            st.plotly_chart(plano_2d(local, ids_con_aviso=ids, parametros=parametros), key="plano_local")
        with pestana_3d:
            if not (local.get("largo_m") and local.get("ancho_m")):
                st.info("Faltan el largo y el ancho del local para dibujar el 3D.")
                clave = None
            else:
                clave = hashlib.md5(json.dumps(local, sort_keys=True, default=str).encode()).hexdigest()
            if clave and (st.session_state.figura_3d_local is None or st.session_state.figura_3d_local[0] != clave):
                st.session_state.figura_3d_local = (clave, figura_3d(local, parametros, titulo="Vista 3D del local interpretado"))
            if clave:
                st.plotly_chart(st.session_state.figura_3d_local[1], key="tres_d_local")
    st.subheader("Advertencias")
    graves = [a for a in avisos if a["gravedad"] == "grave"]
    if not avisos:
        st.success("No se encontraron problemas geométricos.")
    if graves:
        if st.button(f"🪄 Corregir automáticamente los {len(graves)} errores graves", type="primary"):
            corregir_todo_automatico(parametros)
    for numero, aviso in enumerate(avisos):
        columna_texto, columna_boton = st.columns([6, 1])
        icono = "⛔" if aviso["gravedad"] == "grave" else "⚠️"
        columna_texto.markdown(f"{icono} **{aviso['gravedad'].upper()}** — {aviso['mensaje']}")
        if columna_boton.button("Corregir", key=f"corregir_{numero}"):
            st.session_state.aviso_a_corregir = aviso
            st.session_state.correccion = None
    aviso = st.session_state.get("aviso_a_corregir")
    if aviso and aviso in avisos:
        panel_solucion(aviso, parametros)
    with st.expander("✏️ Editar medidas a mano (avanzado)", expanded=bool(st.session_state.correccion)):
        botones = st.columns(6)
        for posicion, (hoja, texto) in enumerate([("LOCAL", "Dimensiones"), ("ESTANTES_EXISTENTES", "Estantes existentes"),
                                                  ("OBSTACULOS", "Obstáculos"),
                                                  ("ZONAS", "Zonas"), ("PASILLOS", "Pasillos"), ("EQUIPOS", "Equipos")]):
            if botones[posicion].button(texto, key=f"editar_{hoja}", width="stretch"):
                st.session_state.correccion = (hoja, "-")
        if st.session_state.correccion:
            formulario_correccion(*st.session_state.correccion)
    preferencias_local = preferencias_de(local)
    st.caption(f"Preferencias y presupuesto: modo de diseño {preferencias_local['modo_diseno']}, presupuesto "
               f"{'sin tope' if not preferencias_local['presupuesto_max_soles'] else formato_soles(preferencias_local['presupuesto_max_soles'])}, "
               f"equipo {preferencias_local['equipo_manipulacion']}. Se pueden cambiar en el Paso 5.")
    st.download_button("⬇️ Descargar el local tal como está (Excel)", plantillas.generar_plantilla_local(local), "local_actual.xlsx")
    st.subheader("Confirmaciones")
    casillas = [st.checkbox(pregunta, key=f"pregunta_local_{k}") for k, pregunta in enumerate(PREGUNTAS_CONFIRMACION_LOCAL)]
    habilitado, motivo = puede_confirmar_local(casillas, avisos, responsable())
    if motivo:
        st.caption(f"🔒 {motivo}")
    if graves:
        st.error(f"Hay {len(graves)} error(es) grave(s): use «Corregir» para resolverlos.")
    if st.button("Confirmo que el local está bien interpretado", type="primary", disabled=not habilitado):
        detalle = {"fuente": local.get("fuente"), "dimensiones": f"{local['largo_m']} × {local['ancho_m']} × {local['altura_libre_m']} m",
                   "estantes_existentes": len(local.get("estantes", [])), "modo_diseno": preferencias_de(local)["modo_diseno"], "advertencias_aceptadas": len(avisos),
                   "correcciones": "; ".join(st.session_state.correcciones_local) or "ninguna",
                   "es_ejemplo": local.get("es_ejemplo", False), "preguntas": " / ".join(PREGUNTAS_CONFIRMACION_LOCAL)}
        confirmar(2, detalle, con_advertencias=bool(avisos))


def aplicar_local_corregido(nuevo, texto):
    st.session_state.local = nuevo
    st.session_state.correcciones_local.append(f"{texto} ({datetime.now():%H:%M})")
    st.session_state.aviso_a_corregir = None
    st.session_state.correccion = None
    st.session_state.figura_3d_local = None
    invalidar(2)
    st.rerun()


def panel_solucion(aviso, parametros):
    """Al pulsar «Corregir» el programa propone cómo resolver el problema; el usuario solo elige y aplica."""
    local = st.session_state.local
    with st.container(border=True):
        st.markdown(f"**💡 Cómo resolver:** {aviso['mensaje']}")
        with st.spinner("Buscando una solución…"):
            propuestas = proponer_solucion(local, aviso, parametros)
        if not propuestas:
            st.info("Este aviso es solo informativo: el programa ya lo tiene en cuenta y no necesita que haga nada. "
                    "Si quiere cambiar el dato, use «Editar a mano».")
        else:
            elegida = st.radio("Soluciones propuestas (la primera es la recomendada):", range(len(propuestas)),
                               format_func=lambda i: ("⭐ " if i == 0 else "") + propuestas[i]["texto"], key="propuesta_elegida")
            st.plotly_chart(plano_2d(propuestas[elegida]["local"], parametros=parametros), key="plano_propuesta")
            st.caption("Así quedaría el plano con esta solución.")
        columnas = st.columns(3)
        if propuestas and columnas[0].button("✅ Aplicar esta solución", type="primary", key="aplicar_propuesta"):
            aplicar_local_corregido(propuestas[elegida]["local"], propuestas[elegida]["texto"])
        if columnas[1].button("✏️ Prefiero editar a mano", key="editar_a_mano"):
            st.session_state.correccion = (aviso["tabla"], aviso["id"] if aviso["id"] not in ("-",) else "-")
            st.session_state.aviso_a_corregir = None
            st.rerun()
        if columnas[2].button("Cerrar", key="cerrar_propuesta"):
            st.session_state.aviso_a_corregir = None
            st.rerun()


def corregir_todo_automatico(parametros):
    local = st.session_state.local
    aplicadas = []
    for _ in range(40):
        graves = [a for a in validar_local(local, parametros) if a["gravedad"] == "grave"]
        if not graves:
            break
        propuestas = proponer_solucion(local, graves[0], parametros)
        if not propuestas:
            break
        local = propuestas[0]["local"]
        aplicadas.append(propuestas[0]["texto"])
    if aplicadas:
        st.session_state.ultimas_correcciones = aplicadas
        aplicar_local_corregido(local, f"Corrección automática: {len(aplicadas)} cambios")


def formulario_correccion(hoja, identificador):
    local = st.session_state.local
    hoja = "ESTANTES_EXISTENTES" if hoja == "ESTANTES" else hoja
    clave = {"LOCAL": None, "ESTANTES_EXISTENTES": "estantes", "OBSTACULOS": "obstaculos", "ZONAS": "zonas", "PASILLOS": "pasillos",
             "EQUIPOS": "equipos"}.get(hoja)
    tablas = local_a_tablas(local)
    with st.container(border=True):
        titulo = f"Corregir {hoja.lower()}" + (f" — {identificador}" if identificador not in ("-", "local") else "")
        st.markdown(f"**{titulo}**")
        tabla = tablas[hoja]
        if identificador not in ("-", "local") and "id" in tabla:
            tabla = tabla[tabla["id"] == identificador]
            st.caption("Corrija la fila marcada. Para ver todos, use los botones «Corregir …» de arriba.")
        configuracion = {}
        for columna in plantillas.HOJAS_LOCAL[hoja]:
            if columna["lista"]:
                configuracion[columna["nombre"]] = st.column_config.SelectboxColumn(columna["nombre"], options=columna["lista"],
                                                                                    help=columna["descripcion"])
            elif columna["tipo"].startswith(("numero", "entero")):
                configuracion[columna["nombre"]] = st.column_config.NumberColumn(columna["nombre"], help=columna["descripcion"],
                                                                                 format="%.2f" if columna["tipo"] != "entero_pos" else "%d")
        if "orientacion" in tabla:
            tabla = tabla.assign(orientacion=tabla["orientacion"].astype(str))
        editada = st.data_editor(tabla, hide_index=True, num_rows="dynamic" if hoja != "LOCAL" else "fixed",
                                 column_config=configuracion, key=f"editor_{hoja}_{identificador}")
        columnas = st.columns(2)
        if columnas[0].button("Aplicar corrección y recalcular", type="primary", key=f"aplicar_{hoja}_{identificador}"):
            nuevo = tablas_a_local({hoja: editada, "LOCAL": tablas["LOCAL"]} if hoja != "LOCAL" else {"LOCAL": editada})
            if hoja == "LOCAL":
                for campo in ("largo_m", "ancho_m", "altura_libre_m", "capacidad_piso_kg_m2", "nombre"):
                    local[campo] = nuevo[campo]
            elif identificador not in ("-", "local"):
                restantes = [e for e in local[clave] if e.get("id") != identificador]
                local[clave] = restantes + nuevo[clave]
            else:
                local[clave] = nuevo[clave]
            st.session_state.correcciones_local.append(f"{hoja} {identificador} corregido {datetime.now():%H:%M}")
            st.session_state.correccion = None
            st.session_state.figura_3d_local = None
            invalidar(2)
            st.rerun()
        if columnas[1].button("Cerrar", key=f"cerrar_{hoja}_{identificador}"):
            st.session_state.correccion = None
            st.rerun()


# ======================================================================================
# Paso 3. Ventas
# ======================================================================================

def leer_ventas(contenido, nombre, origen):
    barra = st.progress(0.0, text="Leyendo el reporte de ventas…")
    tabla, desde_cache = leer_reporte(contenido, nombre, lambda f, texto: barra.progress(min(f, 1.0), text=texto))
    barra.empty()
    st.session_state.tabla_ventas = tabla
    st.session_state.origen_ventas = origen
    st.session_state.mapeo_ventas = None
    st.session_state.ventas_dentro = None
    if desde_cache:
        st.toast("Reporte leído desde datos_procesados (el archivo no cambió).")
    invalidar(3)


def paso_3():
    st.write("Suba el reporte de ventas de su sistema (Excel o CSV) o la plantilla de ventas llena. "
             "Solo se usan las ventas de productos que están en el catálogo.")
    izquierda, derecha = st.columns(2)
    with izquierda:
        st.download_button("⬇️ Descargar plantilla de ventas", plantilla_vacia("ventas"), "plantilla_ventas.xlsx", width="stretch")
        if VENTAS_PRUEBA is not None and st.button("Usar el reporte de prueba (Juliaca, ~124 600 líneas)", width="stretch"):
            leer_ventas(VENTAS_PRUEBA.read_bytes(), VENTAS_PRUEBA.name, ("prueba", VENTAS_PRUEBA.name))
    with derecha:
        archivo = st.file_uploader("Subir reporte de ventas", type=["xlsx", "csv"], key="subir_ventas")
        if archivo is not None and st.session_state.origen_ventas != (archivo.name, archivo.size):
            contenido = archivo.getvalue()
            if archivo.name.endswith(".xlsx") and plantillas.es_plantilla(contenido):
                validacion = plantillas.validar_plantilla(contenido, "ventas")
                if validacion["rechazada"]:
                    st.error(validacion["rechazada"])
                    return
                if validacion["errores"]:
                    st.error(f"La plantilla de ventas tiene {len(validacion['errores'])} celdas con error (esas filas se descartan).")
                    st.dataframe(pd.DataFrame({"Error": [plantillas.describir_error(e) for e in validacion["errores"][:500]]}), height=200)
                    st.download_button("⬇️ Descargar con errores marcados", plantillas.archivo_con_errores(contenido, validacion["errores"]),
                                       "ventas_con_errores.xlsx")
            leer_ventas(contenido, archivo.name, (archivo.name, archivo.size))
    tabla = st.session_state.tabla_ventas
    if tabla is None:
        st.info("Aún no se ha subido el reporte de ventas.")
        return
    asistente_columnas(tabla)
    if st.session_state.ventas_dentro is None:
        return
    analisis_ventas_pantalla()


def asistente_columnas(tabla):
    st.subheader("Asistente de columnas")
    propuesta, origen = proponer_mapeo(tabla)
    if origen == "guardado":
        st.caption("Se usó el mapeo guardado la vez anterior para este formato de reporte.")
    st.write(f"Se leyeron **{len(tabla):,} líneas** y {len(tabla.columns)} columnas. Revise cómo se interpretó cada columna:")
    opciones = ["(no tiene)"] + list(tabla.columns)
    mapeo = {}
    columnas = st.columns(3)
    for posicion, (campo, (descripcion, obligatorio)) in enumerate(CAMPOS_VENTAS.items()):
        actual = propuesta.get(campo)
        mapeo[campo] = columnas[posicion % 3].selectbox(f"{descripcion}{' *' if obligatorio else ''}", opciones,
                                                         index=opciones.index(actual) if actual in opciones else 0,
                                                         key=f"mapeo_{campo}")
    mapeo = {k: (None if v == "(no tiene)" else v) for k, v in mapeo.items()}
    orden = st.radio("Orden de las fechas", ["día-mes-año (05-11-2026 = 5 de noviembre)", "mes-día-año (11-05-2026 = 5 de noviembre)"],
                     horizontal=True, key="orden_fechas")
    with st.expander("Vista previa de las primeras filas del archivo"):
        st.dataframe(tabla.head(8), hide_index=True)
    faltan = [CAMPOS_VENTAS[c][0] for c, (_, obligatorio) in CAMPOS_VENTAS.items() if obligatorio and not mapeo.get(c)
              and not (c == "codigo_barras" and mapeo.get("sku"))]
    if faltan:
        st.error("Falta indicar: " + ", ".join(faltan))
        return
    if st.button("Aplicar equivalencias", type="primary") or (st.session_state.mapeo_ventas == mapeo and st.session_state.ventas_dentro is None):
        with st.spinner("Interpretando fechas y cantidades y uniendo con el catálogo…"):
            ventas, estadisticas = aplicar_mapeo(tabla, mapeo, orden.startswith("día"))
            dentro, resumen_union, top_fuera = unir_con_catalogo(ventas, st.session_state.catalogo)
        guardar_mapeo(tabla.columns, mapeo)
        st.session_state.update(mapeo_ventas=mapeo, ventas=ventas, ventas_dentro=dentro, resumen_union=resumen_union,
                                top_fuera=top_fuera, estadisticas_mapeo=estadisticas, periodo_elegido=None)
        st.session_state.pop("w_periodo", None)
        invalidar(3)
        st.rerun()
    if st.session_state.mapeo_ventas and st.session_state.mapeo_ventas != mapeo:
        st.warning("Cambió las equivalencias: pulse «Aplicar equivalencias» para recalcular.")


def analisis_ventas_pantalla():
    union = st.session_state.resumen_union
    estadisticas = st.session_state.estadisticas_mapeo
    st.subheader("Cómo se interpretó")
    st.dataframe(st.session_state.ventas.head(6)[["fecha_hora", "comprobante", "codigo_barras", "producto", "cantidad",
                                                  "precio_unitario", "total"]], hide_index=True)
    columnas = st.columns(4)
    columnas[0].metric("Líneas leídas", f"{estadisticas['lineas_leidas']:,}",
                       help=f"Fechas no leídas: {estadisticas['fechas_invalidas']}; cantidades no leídas: {estadisticas['cantidades_invalidas']}")
    columnas[1].metric("Dentro del catálogo", f"{union['lineas_dentro']:,} líneas", formato_soles(union["soles_dentro"]), delta_color="off")
    columnas[2].metric("Fuera del catálogo (descartadas)", f"{union['lineas_fuera']:,} líneas", formato_soles(union["soles_fuera"]),
                       delta_color="off")
    columnas[3].metric("Días del periodo", union["dias_periodo"])
    columnas = st.columns(4)
    columnas[0].metric("Códigos vendidos", f"{union['codigos_vendidos']:,}")
    columnas[1].metric("Códigos fuera del catálogo", f"{union['codigos_fuera']:,}")
    columnas[2].metric("Productos del catálogo con ventas", f"{union['productos_con_ventas']:,}")
    columnas[3].metric("Productos sin ventas (SIN ROTACIÓN)", f"{union['productos_sin_ventas']:,}")
    with st.expander("Productos vendidos que NO están en el catálogo (los 50 de más soles)"):
        st.dataframe(st.session_state.top_fuera, hide_index=True)
    st.subheader("Periodo y rotación")
    minimo, maximo = union["fecha_min"].date(), union["fecha_max"].date()
    columnas = st.columns(3)
    # Los valores se copian a claves propias: Streamlit borra el estado de un widget cuando su pantalla no se muestra
    anterior = (st.session_state.get("periodo_elegido"), st.session_state.get("base_elegida"), st.session_state.get("meses_elegidos"))
    periodo = columnas[0].date_input("Periodo a usar", value=st.session_state.get("periodo_elegido") or (minimo, maximo),
                                     min_value=minimo, max_value=maximo, key="w_periodo")
    opciones_base = ["Promedio del periodo", "Últimos meses (para picos recientes)"]
    base = columnas[1].radio("Base de la rotación", opciones_base, key="w_base",
                             index=opciones_base.index(st.session_state.get("base_elegida") or opciones_base[0]))
    meses_recientes = columnas[1].number_input("Meses recientes", 1, 12, st.session_state.get("meses_elegidos") or 3, key="w_meses")
    st.session_state.periodo_elegido = tuple(periodo) if len(periodo) == 2 else st.session_state.get("periodo_elegido")
    st.session_state.base_elegida = base
    st.session_state.meses_elegidos = meses_recientes
    nuevo = (st.session_state.periodo_elegido, base, meses_recientes)
    if anterior[0] is not None and anterior != nuevo and st.session_state.confirmados.get(3):
        invalidar(3)
    unidad = columnas[2].selectbox("Unidad de tiempo del gráfico", ["Día", "Semana", "Mes"], index=2)
    periodo_ventas = ventas_del_periodo()
    serie = ventas_por_unidad_tiempo(periodo_ventas, {"Día": "D", "Semana": "W", "Mes": "M"}[unidad])
    st.plotly_chart(px.bar(serie, x="periodo", y="ventas_soles", labels={"periodo": unidad, "ventas_soles": "Ventas (S/)"},
                           title="Ventas de productos del catálogo"), key="grafico_ventas")
    resumen = resumen_productos()
    meses = ventas_por_mes(periodo_ventas)
    picos = meses[meses["indice_estacional"] >= 1.5]["mes"].tolist()
    if picos:
        st.info(f"Meses pico (≥ 1,5 veces el promedio): {', '.join(picos)}. Si su propuesta es para temporada alta, "
                "use «Últimos meses» como base de la rotación.")
    columnas = st.columns(4)
    for posicion, clase in enumerate(["A", "B", "C", "SIN ROTACIÓN"]):
        grupo = resumen[resumen["clase_abc"] == clase]
        columnas[posicion].metric(f"Clase {clase}", f"{len(grupo)} productos", formato_soles(grupo["ventas_soles"].sum()), delta_color="off")
    with st.expander("Análisis por producto (rotación, ABC, margen, lenta salida)"):
        st.dataframe(resumen[["producto", "categoria", "unidades", "ventas_soles", "rotacion_diaria", "margen_unitario", "clase_abc",
                              "lenta_salida"]], hide_index=True, height=300)
    with st.expander("Pares de productos que se venden juntos (mismo comprobante)"):
        pares = pares_comprobante(periodo_ventas, 20)
        nombres = st.session_state.catalogo.set_index("id_producto")["producto"]
        st.dataframe(pares.assign(producto_a=pares["id_a"].map(nombres), producto_b=pares["id_b"].map(nombres)), hide_index=True)
    with st.expander("Medir lo más importante primero"):
        plantilla_prellenada(st.session_state.catalogo)
    primera_fecha = st.session_state.ventas["fecha_hora"].iloc[0]
    texto = texto_original_fecha(st.session_state.tabla_ventas, st.session_state.mapeo_ventas)
    st.divider()
    fechas_ok = st.checkbox(f"¿La fecha «{texto}» es el {ejemplo_fecha_legible(primera_fecha)}?", key="confirma_fecha")
    cantidades_ok = st.checkbox("Las cantidades y los totales se interpretaron bien", key="confirma_cantidades")
    bloqueo = None if (fechas_ok and cantidades_ok) else "Confirme que fechas y cantidades se interpretaron bien."
    if len(periodo) != 2:
        bloqueo = "Elija la fecha de inicio y de fin del periodo."
    boton_confirmar(3, "Confirmo el reporte de ventas y el periodo elegido",
                    {"lineas_dentro": union["lineas_dentro"], "soles_dentro": union["soles_dentro"],
                     "lineas_fuera": union["lineas_fuera"], "soles_fuera": union["soles_fuera"],
                     "periodo": f"{periodo[0]} a {periodo[-1]}", "base_rotacion": base},
                    bloqueo=bloqueo)


# ======================================================================================
# Paso 4. Normativas
# ======================================================================================

def paso_4():
    estado = st.session_state.normas
    st.write("Las normas peruanas **ya vienen incluidas** en el programa: no tiene que subir nada. "
             "Solo marque cuáles quiere que se respeten (ya están marcadas las que corresponden a su rubro).")
    with st.container(border=True):
        st.markdown("#### ¿Qué normas desea considerar?")
        for norma in [n for n in estado["normas"] if n["aplicable"]]:
            marcada = st.checkbox(f"**{norma['numero']}** — {norma['nombre']}", value=norma["activa"], key=f"activa_{norma['id']}",
                                  help=f"A qué se aplica: {norma['aplica_a']}")
            st.caption(f"   {norma['aplica_a']}")
            if marcada != norma["activa"]:
                cambiar_activa(estado, norma["id"], marcada, responsable())
                invalidar(4)
                st.rerun()
    datos = resumen_normas(estado)
    columnas = st.columns(4)
    columnas[0].metric("Normas consideradas", datos["consideradas"])
    columnas[1].metric("Obligatorias", datos["obligatorias"])
    columnas[2].metric("Por verificar", datos["por_verificar"])
    columnas[3].metric("Perfil de rubro", PERFILES[st.session_state.perfil]["nombre"])
    parametros = parametros_actuales()
    local = st.session_state.local
    posiciones = generar_posiciones(local, parametros)
    avisos = validar_local(local, parametros)
    semaforo = {f["id"]: f for f in semaforo_local(estado, local, avisos, posiciones, st.session_state.catalogo, st.session_state.modo)}
    st.session_state.semaforo = list(semaforo.values())
    no_cumple = [f for f in semaforo.values() if f["resultado"] == NO_CUMPLE]
    if no_cumple:
        st.error("El local no cumple: " + " · ".join(f["detalle"] for f in no_cumple))
    else:
        st.success("Con las normas marcadas, el local confirmado no tiene incumplimientos detectados.")
    st.markdown("##### Ajustes avanzados (opcional)")
    st.caption("Solo si conoce el tema: valores de cada norma, reglas de negocio e incompatibilidades. Los valores por defecto ya sirven.")
    pestana_normas, pestana_reglas, pestana_incompatibles = st.tabs(["Valores de las normas", "Reglas de negocio", "Incompatibilidades"])
    with pestana_normas:
        aplicables = [n for n in estado["normas"] if n["aplicable"]]
        for norma in aplicables:
            tarjeta_norma(norma, semaforo.get(norma["id"]))
        otras = [n for n in estado["normas"] if not n["aplicable"]]
        if otras:
            with st.expander(f"Normas que no aplican al rubro elegido ({len(otras)})"):
                for norma in otras:
                    st.markdown(f"- **{norma['numero']}** — {norma['nombre']} (rubros: {', '.join(norma['rubros'] or [])})")
    with pestana_reglas:
        st.caption("Reglas de negocio: no son leyes; son buenas prácticas que el modelo aplica como restricciones o penalizaciones.")
        for regla in estado["reglas_negocio"]:
            with st.container(border=True):
                columnas = st.columns([4, 1])
                columnas[0].markdown(f"**{regla['nombre']}** — {texto_regla(regla)}")
                activa = columnas[1].toggle("Aplicar", value=regla["activa"], key=f"regla_{regla['id']}")
                if activa != regla["activa"]:
                    cambiar_activa(estado, regla["id"], activa, responsable())
                    invalidar(4)
                    st.rerun()
                for clave, parametro in regla["parametros"].items():
                    nuevo = st.number_input(f"{clave} ({parametro.get('unidad', '')})", value=float(parametro["valor"]),
                                            key=f"regla_{regla['id']}_{clave}", step=0.1 if parametro["valor"] < 5 else 1.0)
                    if nuevo != float(parametro["valor"]):
                        cambiar_parametro_regla(estado, regla["id"], clave, nuevo, responsable())
                        invalidar(4)
                        st.rerun()
    with pestana_incompatibles:
        st.caption("Matriz editable: dos categorías que deben quedar separadas al menos la distancia indicada (restricción dura).")
        categorias = sorted(set(st.session_state.catalogo["categoria"].astype(str)) |
                            {c for f in estado["incompatibilidades"] for c in (f["categoria_a"], f["categoria_b"])})
        tabla = pd.DataFrame(estado["incompatibilidades"], columns=["categoria_a", "categoria_b", "distancia_min_m", "motivo"])
        editada = st.data_editor(tabla, num_rows="dynamic", hide_index=True, column_config={
            "categoria_a": st.column_config.SelectboxColumn("Categoría A", options=categorias),
            "categoria_b": st.column_config.SelectboxColumn("Categoría B", options=categorias),
            "distancia_min_m": st.column_config.NumberColumn("Distancia mínima (m)", min_value=0.0, step=0.5)}, key="editor_incompat")
        if st.button("Guardar matriz de incompatibilidades"):
            estado["incompatibilidades"] = editada.dropna(subset=["categoria_a", "categoria_b"]).to_dict("records")
            estado["cambios"].append({"fecha": datetime.now().strftime("%Y-%m-%d %H:%M"), "norma": "Matriz de incompatibilidades",
                                      "cambio": f"{len(estado['incompatibilidades'])} pares", "original": "-", "responsable": responsable()})
            invalidar(4)
            st.rerun()
        activas = incompatibilidades_activas(estado)
        st.write("Incompatibilidades que aplicará el modelo:")
        st.dataframe(pd.DataFrame(activas, columns=["Categoría A", "Categoría B", "Distancia mínima (m)", "Motivo"]), hide_index=True)
    if estado["cambios"]:
        st.warning(f"Se registraron {len(estado['cambios'])} cambios a las normas y reglas (aparecerán en el acta y el reporte final).")
        st.dataframe(pd.DataFrame(estado["cambios"]), hide_index=True)
    boton_confirmar(4, "Confirmo las normativas que se aplicarán",
                    {"perfil": st.session_state.perfil, "modo": st.session_state.modo, "normas_consideradas": datos["consideradas"],
                     "por_verificar": datos["por_verificar"],
                     "cambios": "; ".join(f"{c['norma']}: {c['cambio']}" for c in estado["cambios"]) or "ninguno"},
                    con_advertencias=bool(estado["cambios"]) or any(f["resultado"] == NO_CUMPLE for f in semaforo.values()))


def tarjeta_norma(norma, semaforo):
    estado = st.session_state.normas
    with st.container(border=True):
        columnas = st.columns([5, 2])
        with columnas[0]:
            st.markdown(f"#### {norma['numero']}")
            st.markdown(f"**{norma['nombre']}**  \n*A qué se aplica:* {norma['aplica_a']}  \n"
                        f"*Regla en el modelo:* {texto_regla(norma)}  \n*Fuente oficial:* {norma['fuente']}")
        with columnas[1]:
            st.badge(norma["tipo"], color="blue" if norma["tipo"] == "obligatoria" else "gray")
            verificada = norma["estado"] == "verificada"
            st.badge(f"{norma['estado']}" + (f" ({norma['fecha_revision']})" if norma.get("fecha_revision") else " (sin revisar)"),
                     color="green" if verificada else "orange")
            if semaforo:
                st.badge(f"Local: {semaforo['resultado']}", color=COLOR_SEMAFORO[semaforo["resultado"]])
        if semaforo and semaforo["resultado"] != NO_APLICA:
            (st.error if semaforo["resultado"] == NO_CUMPLE else st.caption)(semaforo["detalle"])
        columnas = st.columns([1, 3])
        columnas[0].markdown("✅ Se aplica" if norma["activa"] else "⛔ No se aplica")
        if not norma["activa"]:
            columnas[1].warning("Norma DESACTIVADA por el usuario: quedará registrado en el acta y en el reporte final.")
        for clave, parametro in norma["parametros"].items():
            if parametro.get("opciones"):
                nuevo = columnas[1].selectbox(f"{clave} ({parametro['unidad']}) — {parametro['descripcion']}", parametro["opciones"],
                                              index=parametro["opciones"].index(parametro["valor"]) if parametro["valor"] in parametro["opciones"] else 0,
                                              key=f"norma_{norma['id']}_{clave}", disabled=not norma["activa"])
            else:
                nuevo = columnas[1].number_input(f"{clave} ({parametro['unidad']}) — {parametro['descripcion']}",
                                                 value=float(parametro["valor"]), step=0.05, key=f"norma_{norma['id']}_{clave}",
                                                 disabled=not norma["activa"])
            if nuevo != parametro["valor"]:
                cambiar_parametro(estado, norma["id"], clave, nuevo, responsable())
                invalidar(4)
                st.rerun()
            if parametro["valor"] != parametro["valor_original"]:
                columnas[1].caption(f"⚠️ Valor cambiado (original {parametro['valor_original']}). Registrado en el acta.")


# ======================================================================================
# Paso 5. Diseñar y optimizar
# ======================================================================================

MODOS_DISENO = {"A": "A. Diseñar desde cero (por defecto)", "B": "B. Reutilizar mis estantes existentes",
                "C": "C. Mixto: conservar los existentes y agregar módulos"}


def preferencias():
    local = st.session_state.local
    local["preferencias"] = preferencias_de(local)
    return local["preferencias"]


def registrar_tiempo(nombre, segundos):
    st.session_state.setdefault("tiempos", {})[nombre] = round(segundos, 2)


def paso_5():
    pref = preferencias()
    st.write("El programa **diseña los racks**: elige qué tipos usar, cuántos y dónde, deja libres los pasillos y despejes que "
             "piden las normas, ubica los productos y arma la lista de compra. Todo con **un solo modelo** de optimización.")
    modo = st.session_state.modo
    if modo == "almacen":
        st.markdown("**Objetivo (almacén):** minimizar Σ rotación × costo de acceso × x + λ × Σ costo anualizado del rack × z "
                    "+ penalizaciones.")
    else:
        st.markdown("**Objetivo (tienda):** maximizar Σ margen esperado × exposición × x − λ × Σ costo anualizado del rack × z.")
    with st.form("form_diseno"):
        columnas = st.columns(3)
        modo_diseno = columnas[0].radio("Modo de diseño", list(MODOS_DISENO), format_func=MODOS_DISENO.get,
                                        index=list(MODOS_DISENO).index(pref.get("modo_diseno", "A")))
        presupuesto = columnas[1].number_input("Presupuesto máximo para racks (S/; 0 = sin tope)", 0.0, 1e8,
                                               float(pref.get("presupuesto_max_soles") or 0.0), 100.0)
        equipo = columnas[2].radio("Equipo de manipulación", ["manual", "mecanico"],
                                   index=0 if pref.get("equipo_manipulacion") != "mecanico" else 1,
                                   format_func={"manual": "Manual (a mano o carretilla)", "mecanico": "Mecánico (transpaleta, montacargas)"}.get)
        columnas = st.columns(2)
        cobertura = columnas[0].checkbox("Llenar todo el local (mostrar capacidad máxima)", bool(pref.get("cobertura_total")),
                                         help="Sigue agregando racks por todo el local aunque el stock actual no los necesite. "
                                              "Los que sobran quedan vacíos como capacidad disponible.")
        porcentaje = columnas[1].slider("% de área útil a cubrir con racks", 10, 90,
                                        int(round(float(pref.get("cobertura_porcentaje") or
                                                        AJUSTES["diseno"].get("cobertura_defecto", 0.4)) * 100)), 5)
        lam = st.slider("Priorizar ahorro de recorrido  ⟵ λ ⟶  priorizar menor inversión", 0.0, 3.0,
                        float(st.session_state.get("lambda_diseno", AJUSTES["diseno"]["lambda_inversion"])), 0.1,
                        help="λ = 0: solo importa el recorrido. λ = 1: la inversión anualizada pesa lo mismo que el recorrido de la "
                             "propuesta rápida. λ alto: menos racks.")
        columnas = st.columns(3)
        tiempo = columnas[0].number_input("Tiempo límite del modelo (s)", 5, 1800,
                                          int(st.session_state.get("tiempo_diseno", AJUSTES["solver"]["tiempo_limite_s"])), 5)
        brecha = columnas[1].number_input("Brecha aceptada (%)", 0.0, 20.0,
                                          float(st.session_state.get("brecha_diseno", AJUSTES["solver"]["brecha_relativa"] * 100)), 0.5)
        columnas[2].caption("La brecha es cuánto puede alejarse la solución del óptimo demostrado.")
        if st.form_submit_button("Aplicar preferencias"):
            pref.update(modo_diseno=modo_diseno, presupuesto_max_soles=presupuesto or None, equipo_manipulacion=equipo,
                        acepta_comprar="no" if modo_diseno == "B" else "si", cobertura_total=bool(cobertura),
                        cobertura_porcentaje=porcentaje / 100)
            st.session_state.update(lambda_diseno=lam, tiempo_diseno=tiempo, brecha_diseno=brecha)
            invalidar(5)
            st.rerun()
    if pref.get("modo_diseno") in ("B", "C") and not st.session_state.local.get("estantes"):
        st.warning("Eligió reutilizar estantes, pero no declaró ninguno en el Paso 2 (hoja ESTANTES_EXISTENTES).")
    editor_racks()
    pesos = dict(AJUSTES["objetivo"])
    with st.expander("Pesos del objetivo (avanzado)"):
        columnas = st.columns(5)
        pesos["peso_distancia"] = columnas[0].number_input("Peso distancia", 0.0, 10.0, pesos["peso_distancia"], 0.1)
        pesos["peso_ergonomia"] = columnas[1].number_input("Peso ergonomía", 0.0, 10.0, pesos["peso_ergonomia"], 0.1)
        pesos["peso_reglas_blandas"] = columnas[2].number_input("Peso reglas blandas", 0.0, 10.0, pesos["peso_reglas_blandas"], 0.1)
        pesos["peso_agrupar_categoria"] = columnas[3].number_input("Peso agrupar categoría", 0.0, 5.0, pesos["peso_agrupar_categoria"], 0.05)
        pesos["peso_pares_comprobante"] = columnas[4].number_input("Peso vendidos juntos", 0.0, 5.0, pesos["peso_pares_comprobante"], 0.05)
    st.session_state.pesos = pesos
    columnas = st.columns(2)
    if columnas[0].button("⚡ Propuesta rápida (heurística, segundos)", width="stretch"):
        calcular(pesos, rapido=True)
    if columnas[1].button("Calcular propuesta completa (heurística + modelo)", type="primary", width="stretch"):
        calcular(pesos, rapido=False)
    solucion = st.session_state.solucion
    if solucion is None:
        st.info("Pulse «Propuesta rápida» para ver un diseño en segundos o «Calcular propuesta completa» para el óptimo del modelo.")
        return
    if solucion.get("sin_solucion"):
        st.error(solucion["estado"])
        for aviso in solucion.get("avisos_diseno", []):
            st.caption(aviso)
        return
    mostrar_estado_solver(solucion)
    mostrar_diseno(solucion)
    boton_confirmar(5, "Acepto esta propuesta para revisarla en detalle",
                    {"estado": solucion["estado"], "modo_diseno": solucion["modo_diseno"], "lambda": solucion["lambda"],
                     "modulos_nuevos": solucion["modulos_nuevos"], "inversion_racks": solucion["inversion_racks"],
                     "ubicados": int(solucion["ubicaciones"]["ubicado"].sum()),
                     "no_ubicados": int((~solucion["ubicaciones"]["ubicado"]).sum()), "tiempo_s": solucion["tiempo_s"],
                     "modo": solucion["modo"]},
                    con_advertencias=bool(solucion["faltante"]))


def editor_racks():
    with st.expander(f"🗄️ Catálogo de racks — precios: {ROTULO_PRECIOS}", expanded=False):
        st.caption("Marque los tipos que permite, cambie medidas y precios o agregue un tipo nuevo. Los valores iniciales son "
                   "referenciales: NO son precios reales. Un tipo más alto que la altura disponible se usa con menos niveles.")
        if st.session_state.get("tabla_racks") is None:
            st.session_state.tabla_racks = cargar_catalogo_racks()
        editada = st.data_editor(st.session_state.tabla_racks, num_rows="dynamic", hide_index=True, key="editor_racks", column_config={
            "disponible": st.column_config.CheckboxColumn("¿Permitido?"),
            "uso": st.column_config.SelectboxColumn("Uso", options=["tienda", "almacen"]),
            "equipo": st.column_config.SelectboxColumn("Equipo", options=["manual", "mecanico"]),
            "permite_peligrosos": st.column_config.SelectboxColumn("¿Peligrosos?", options=["si", "no"]),
            "precio_soles": st.column_config.NumberColumn("Precio (S/)*", min_value=0.0),
            "montaje_soles": st.column_config.NumberColumn("Montaje (S/)*", min_value=0.0),
            "vida_util_anios": st.column_config.NumberColumn("Vida útil (años)", min_value=1.0)})
        st.session_state.tabla_racks_editada = editada
        local = st.session_state.local
        tipos, avisos = tipos_utilizables(editada, local, parametros_actuales())
        st.caption(f"Altura disponible para racks: {altura_disponible(local, parametros_actuales()):.2f} m. "
                   f"Tipos utilizables: {', '.join(t['nombre'] for t in tipos) or 'ninguno'}.")
        for aviso in avisos:
            st.caption(f"⚠️ {aviso}")
        if st.button("Guardar catálogo de racks"):
            errores = guardar_catalogo_racks(editada)
            st.session_state.tabla_racks = cargar_catalogo_racks()
            (st.warning if errores else st.success)("; ".join(errores) or "Catálogo guardado en configuracion/catalogo_racks.json.")
            invalidar(5)


def argumentos_diseno(pesos, parametros=None, lam=None, resumen=None, tiempo=None):
    return dict(catalogo=st.session_state.catalogo, resumen=resumen if resumen is not None else resumen_productos(),
                local=st.session_state.local, parametros=parametros or parametros_actuales(),
                incompatibilidades=incompatibilidades_activas(st.session_state.normas),
                pares_venta=pares_comprobante(ventas_del_periodo(), AJUSTES["objetivo"]["pares_comprobante_max"]),
                modo=st.session_state.modo, perfil_id=st.session_state.perfil, pesos=pesos,
                tiempo_limite=tiempo or int(st.session_state.get("tiempo_diseno", AJUSTES["solver"]["tiempo_limite_s"])),
                brecha=float(st.session_state.get("brecha_diseno", AJUSTES["solver"]["brecha_relativa"] * 100)) / 100,
                tipos_tabla=st.session_state.get("tabla_racks_editada"),
                lam=float(st.session_state.get("lambda_diseno", AJUSTES["diseno"]["lambda_inversion"])) if lam is None else lam)


def ejecutar_en_hilo(funcion, barra):
    """Corre el solver en un hilo aparte y actualiza la barra de progreso mientras tanto."""
    estado = {"f": 0.0, "t": "Iniciando…", "resultado": None, "error": None}

    def trabajo():
        try:
            estado["resultado"] = funcion(lambda f, t: estado.update(f=f, t=t))
        except Exception as error:  # se muestra en la pantalla principal
            estado["error"] = error
    hilo = threading.Thread(target=trabajo, daemon=True)
    hilo.start()
    inicio = time.time()
    while hilo.is_alive():
        barra.progress(min(max(estado["f"], 0.0), 1.0), text=f"{estado['t']} ({time.time() - inicio:.0f} s)")
        hilo.join(0.3)
    if estado["error"] is not None:
        raise estado["error"]
    return estado["resultado"]


def calcular(pesos, rapido=False):
    invalidar(5)  # primero se borra la propuesta anterior y las confirmaciones siguientes
    barra = st.progress(0.0, text="Preparando…")
    argumentos = argumentos_diseno(pesos)
    inicio = time.time()
    solucion = optimizar_diseno(**argumentos, rapido=True, avance=lambda f, t: barra.progress(min(f, 1.0), text=t))
    registrar_tiempo("Propuesta rápida (heurística)", time.time() - inicio)
    if not rapido and not solucion.get("sin_solucion"):
        st.info(f"Propuesta rápida lista en {time.time() - inicio:.1f} s: {solucion['modulos_nuevos']} módulos nuevos y "
                f"{len(solucion['asignacion'])} productos ubicados. Refinando con el modelo completo…")
        inicio = time.time()
        solucion = ejecutar_en_hilo(lambda avance: optimizar_diseno(**argumentos, rapido=False, avance=avance), barra)
        registrar_tiempo("Optimización completa", time.time() - inicio)
    if solucion.get("sin_solucion"):
        st.session_state.solucion = solucion
        barra.empty()
        st.rerun()
    barra.progress(1.0, text="Calculando la línea base «antes» e indicadores…")
    terminar_calculo(solucion)
    barra.empty()
    st.rerun()


def lineas_base(solucion):
    productos, pares, validas, local = solucion["productos"], solucion["pares"], solucion["validas"], solucion["local"]
    antes = {"Antes (alfabético por categoría)": linea_base_alfabetica(productos, pares, validas, local),
             "Antes (aleatorio, semilla fija)": linea_base_aleatoria(productos, pares, validas, local)}
    actual = linea_base_actual(productos, pares, validas)
    if actual:
        antes = {"Antes (ubicación actual registrada)": actual, **antes}
    return antes


def terminar_calculo(solucion):
    productos, pares, validas, local = solucion["productos"], solucion["pares"], solucion["validas"], solucion["local"]
    antes = lineas_base(solucion)
    estadisticas = estadisticas_pedidos(ventas_del_periodo(), resumen_productos()["dias_periodo"].iloc[0])
    parametros = parametros_actuales()
    incompat = incompatibilidades_activas(st.session_state.normas)
    kpis = {nombre: evaluar(asig, productos, validas, local, pares, estadisticas, solucion["modo"], parametros=parametros,
                            incompatibilidades=incompat) for nombre, asig in antes.items()}
    kpis["Después (modelo)"] = evaluar(solucion["asignacion"], productos, validas, local, pares, estadisticas, solucion["modo"],
                                       parametros=parametros, incompatibilidades=incompat)
    st.session_state.update(solucion=solucion, antes=antes, kpis=kpis, estadisticas_pedidos=estadisticas,
                            validacion=validar_solucion(solucion["asignacion"], productos, validas, local, pares, parametros, incompat),
                            escenarios=None, tabla_sensibilidad=None)


def mostrar_estado_solver(solucion):
    ubicaciones = solucion["ubicaciones"]
    columnas = st.columns(5)
    columnas[0].metric("Estado del solver", solucion["estado"].split(" —")[0])
    columnas[1].metric("Brecha de optimalidad", "—" if solucion["brecha"] is None else f"{solucion['brecha'] * 100:.2f} %")
    columnas[2].metric("Tiempo", f"{solucion['tiempo_s']} s")
    columnas[3].metric("Productos ubicados", f"{int(ubicaciones['ubicado'].sum()):,} / {len(ubicaciones):,}")
    columnas[4].metric("Índice de confiabilidad",
                       f"{indice_confiabilidad(st.session_state.catalogo, resumen_productos(), factor_local())['indice']:.0f} %")
    if solucion["fuente"] == "heuristica" and not solucion.get("rapido"):
        st.warning(f"Se usa la solución de la heurística: {solucion['estado']}.")
    base, modelo = solucion["objetivo_heuristica"], solucion["objetivo"]
    mejora = (base - modelo) / abs(base) * 100 if base else 0.0
    if solucion["variables"]:
        st.caption(f"Modelo: {solucion['variables']:,} variables binarias x, {solucion['restricciones']:,} restricciones "
                   f"({solucion['pares_totales']:,} pares posibles; se conservaron {solucion['pares_modelo']:,}). CBC: "
                   f"{solucion['resultado_cbc'] or '—'}.")
        st.info(f"Comparación con la propuesta rápida (heurística): objetivo heurística = {base:,.3f}, modelo = {modelo:,.3f} → "
                f"mejora del modelo en la parte de recorrido: **{mejora:.2f} %**.")
    if solucion["faltante"]:
        st.error(solucion["faltante"]["texto"])
        st.dataframe(ubicaciones[~ubicaciones["ubicado"]][["producto", "categoria", "clase_abc", "stock_minimo", "motivo"]], hide_index=True)
    kpis = st.session_state.kpis
    if kpis:
        st.subheader("Antes y después (resumen)")
        st.dataframe(tabla_antes_despues(kpis), hide_index=True)


def mostrar_diseno(solucion):
    st.subheader("Diseño de racks propuesto")
    columnas = st.columns(4)
    columnas[0].metric("Módulos nuevos", solucion["modulos_nuevos"])
    columnas[1].metric("Estantes existentes conservados", solucion["modulos_existentes"])
    columnas[2].metric("Inversión en racks*", formato_soles(solucion["inversion_racks"]))
    columnas[3].metric("Costo anualizado*", formato_soles(solucion["costo_anualizado_racks"]))
    st.caption(f"* {ROTULO_PRECIOS}. Modo {solucion['modo_diseno']}, λ = {solucion['lambda']:.2f}, "
               f"{solucion['candidatos']:,} módulos candidatos generados por reglas geométricas.")
    if (solucion.get("cobertura") or {}).get("activa"):
        st.warning("Propuesta de **capacidad máxima** (llenar todo el local), no del stock actual: "
                   f"{solucion['cobertura']['modulos_vacios']} racks quedan vacíos (en verde en las vistas 2D/3D) y su costo "
                   "está incluido en la lista de compra y el costeo.")
    for aviso in solucion.get("avisos_diseno", []):
        st.caption(f"ℹ️ {aviso}")
    if len(solucion["lista_compra"]):
        st.markdown("**Lista de compra de racks**")
        st.dataframe(solucion["lista_compra"], hide_index=True)
    with st.expander("Ubicación de cada módulo (tipo, posición, orientación)"):
        st.dataframe(solucion["tabla_diseno"], hide_index=True, height=300)
    if solucion.get("alternativas"):
        st.markdown("**No cabe todo. Alternativas con su costo estimado:**")
        st.dataframe(pd.DataFrame(solucion["alternativas"]), hide_index=True)


def ejecutar_modelo(pesos, tiempo, brecha=None, local=None, parametros=None, modo=None, avance=None):
    """Vuelve a ubicar los productos en un diseño de racks FIJO (escenarios y sensibilidad de pesos)."""
    local = local or st.session_state.solucion["local"]
    modo = modo or st.session_state.modo
    parametros = parametros or parametros_actuales()
    posiciones = medir_distancias(generar_posiciones(local, parametros), local, modo)
    pares_venta = pares_comprobante(ventas_del_periodo(), AJUSTES["objetivo"]["pares_comprobante_max"])
    return optimizar(st.session_state.catalogo, resumen_productos(), posiciones, local, parametros,
                     incompatibilidades_activas(st.session_state.normas), pares_venta, modo, st.session_state.perfil, pesos,
                     tiempo, brecha, avance)


# ======================================================================================
# Paso 6. Resultados
# ======================================================================================

PESTANAS_6 = ["Vista 3D", "Plano 2D", "Ubicaciones", "Antes y después", "Escenarios", "Sensibilidad", "Reporte normativo"]


def local_resultado():
    return st.session_state.solucion["local"]


def paso_6():
    solucion = st.session_state.solucion
    calcular_reporte_normativo()
    pestana = st.radio("Ver", PESTANAS_6, horizontal=True, key="pestana_6",
                       help="Cada vista se calcula solo cuando se abre (la página responde más rápido).")
    if pestana == "Vista 3D":
        vista_3d(solucion)
    elif pestana == "Plano 2D":
        color = st.radio("Colorear por", ["abc", "rotacion", "costo"], horizontal=True,
                         format_func={"abc": "Clase ABC", "rotacion": "Mapa de calor de rotación", "costo": "Costo de acceso"}.get)
        st.plotly_chart(plano_2d(local_resultado(), solucion["posiciones"], solucion["ubicaciones"], color,
                                 parametros=parametros_actuales(), alto=640), key="plano_resultado")
        st.caption("Naranja = racks propuestos (nuevos); azul = estantes existentes.")
    elif pestana == "Ubicaciones":
        tabla = solucion["ubicaciones"]
        st.dataframe(tabla[["producto", "categoria", "clase_abc", "id_posicion", "estante", "nivel", "tramo", "frentes",
                            "unidades_caben", "stock_minimo", "orientacion", "distancia_m", "origen_medidas", "motivo"]],
                     hide_index=True, height=480)
        st.download_button("⬇️ Descargar ubicaciones (CSV)", tabla.to_csv(index=False).encode("utf-8-sig"), "ubicaciones.csv")
    elif pestana == "Antes y después":
        antes_despues()
    elif pestana == "Escenarios":
        escenarios()
    elif pestana == "Sensibilidad":
        pantalla_sensibilidad()
    else:
        reporte_normativo_pantalla()
    boton_confirmar(6, "He revisado los resultados")


def antes_despues():
    kpis = st.session_state.kpis
    tabla = tabla_antes_despues(kpis)
    st.dataframe(tabla, hide_index=True)
    largo = tabla[tabla["Indicador"].isin([NOMBRES_KPI["distancia_ponderada_m_dia"], NOMBRES_KPI["tiempo_por_pedido_s"],
                                            NOMBRES_KPI["costo_picking_mes_soles"]])].melt(id_vars="Indicador", var_name="Escenario",
                                                                                          value_name="Valor")
    st.plotly_chart(px.bar(largo, x="Indicador", y="Valor", color="Escenario", barmode="group"), key="grafico_antes")
    st.caption("El «antes» se mide sobre el mismo diseño de racks (llenado sin método) si no registró la ubicación actual. "
               "La evidencia con pedidos reales está en el Paso 7.")
    validacion = st.session_state.validacion
    if validacion["duros"]:
        st.error(f"El validador independiente encontró {len(validacion['duros'])} incumplimientos duros:")
        st.write(validacion["duros"][:30])
    else:
        st.success("Validador independiente: la propuesta no viola ninguna restricción dura.")
    if validacion["blandos"]:
        with st.expander(f"Reglas blandas no cumplidas ({len(validacion['blandos'])}) — son preferencias, no obligaciones"):
            st.write(validacion["blandos"])


def vista_3d(solucion):
    productos = solucion["productos"]
    local = local_resultado()
    columnas = st.columns(4)
    vista = columnas[0].selectbox("Vista", ["Todo", "Un módulo"])
    modulo = columnas[0].selectbox("Módulo", [e["id"] for e in local["estantes"]]) if vista == "Un módulo" else None
    categorias = columnas[1].multiselect("Categorías", sorted(productos["categoria"].astype(str).unique()))
    clases = columnas[1].multiselect("Clase ABC", ["A", "B", "C", "SIN ROTACIÓN"])
    color = columnas[2].radio("Color", ["abc", "rotacion", "costo"],
                              format_func={"abc": "Clase ABC", "rotacion": "Calor: rotación", "costo": "Calor: costo de acceso"}.get)
    solo_incumplen = columnas[2].checkbox("Solo productos con reglas incumplidas")
    altura = columnas[3].slider("Ver hasta la altura (m)", 0.0, float(local["altura_libre_m"]), float(local["altura_libre_m"]), 0.1)
    comparar = columnas[3].radio("Antes / después", ["Después", "Antes", "Lado a lado"], horizontal=True)
    con_recorrido = st.checkbox("Mostrar el recorrido de picking de un pedido de ejemplo")
    recorrido = None
    if con_recorrido:
        pedidos = ventas_del_periodo().groupby("comprobante")["id_producto"].apply(lambda s: list(dict.fromkeys(s)))
        pedidos = pedidos[pedidos.str.len().between(3, 8)].head(40)
        if len(pedidos):
            elegido = st.selectbox("Pedido", list(pedidos.index), format_func=lambda c: f"{c} ({len(pedidos[c])} productos)")
            recorrido = recorrido_pedido(local, solucion["validas"], solucion["asignacion"], pedidos[elegido], productos, solucion["modo"])
    solo_ids = None
    if solo_incumplen:
        nombres = {texto.split(":")[0] for texto in st.session_state.validacion["blandos"] + st.session_state.validacion["duros"]}
        solo_ids = set(productos[productos["producto"].str[:40].isin(nombres)]["id_producto"])
    antes = next(iter(st.session_state.antes.values()))
    argumentos = dict(parametros=parametros_actuales(), solucion=solucion, categorias=categorias or None, clases=clases or None,
                      altura_max=altura if altura < float(local["altura_libre_m"]) else None,
                      solo_ids=solo_ids, modo_color=color, modulo=modulo, recorrido=recorrido)
    inicio = time.time()
    if comparar == "Lado a lado":
        izquierda, derecha = st.columns(2)
        izquierda.plotly_chart(figura_3d(local, asignacion=antes, titulo="Antes", alto=560, **argumentos), key="3d_antes")
        derecha.plotly_chart(figura_3d(local, titulo="Después", alto=560, **argumentos), key="3d_despues")
    else:
        figura = figura_3d(local, asignacion=antes if comparar == "Antes" else None, titulo=f"{comparar}: vista 3D", **argumentos)
        st.plotly_chart(figura, key="3d_resultado")
    registrar_tiempo("Generar la vista 3D", time.time() - inicio)
    st.caption("Naranja = racks propuestos; gris azulado = estantes existentes. Mouse: rotar; rueda: acercar; clic derecho: mover.")
    if st.button("Preparar visual_3d.html"):
        figura = figura_3d(local, parametros=parametros_actuales(), solucion=solucion, asignacion_antes=antes,
                           recorrido=recorrido, titulo="Acomoda — propuesta de distribución")
        guardar_html(figura, CARPETA_RESULTADOS / "visual_3d.html")
        st.session_state.html_3d = (CARPETA_RESULTADOS / "visual_3d.html").read_bytes()
    if st.session_state.get("html_3d"):
        st.download_button("⬇️ Descargar visual_3d.html (se abre con doble clic)", st.session_state.html_3d, "visual_3d.html", "text/html")


def escenarios():
    st.write("Compare la propuesta con otras situaciones sobre el MISMO diseño de racks (cada escenario vuelve a ubicar los productos).")
    columnas = st.columns(3)
    limite = columnas[0].selectbox("Otro límite de peso (kg)", [15, 25, 40], index=0)
    con_limite = columnas[0].checkbox("Escenario: otro límite de peso", value=True)
    con_estante = columnas[1].checkbox("Escenario: un estante más", value=True)
    con_objetivo = columnas[2].checkbox("Escenario: el otro objetivo (almacén ↔ tienda)", value=True)
    tiempo = st.number_input("Tiempo límite por escenario (s)", 5, 600, 20, 5)
    if st.button("Calcular escenarios"):
        base = st.session_state.solucion
        local = local_resultado()
        estadisticas = st.session_state.estadisticas_pedidos
        pesos = st.session_state.get("pesos", AJUSTES["objetivo"])
        resultados = {"Propuesta": st.session_state.kpis["Después (modelo)"]}
        barra = st.progress(0.0, text="Escenarios…")
        if con_limite:
            barra.progress(0.1, text=f"Límite de {limite} kg…")
            parametros = dict(parametros_actuales(), limite_peso_kg=limite)
            solucion = ejecutar_modelo(pesos, tiempo, parametros=parametros)
            resultados[f"Límite {limite} kg"] = kpi_con_costos_base(solucion, base, estadisticas, local, st.session_state.modo, parametros)
        if con_estante:
            barra.progress(0.4, text="Un estante más…")
            nuevo, estante = agregar_estante_libre(local, parametros_actuales())
            if estante:
                solucion = ejecutar_modelo(pesos, tiempo, local=nuevo)
                resultados[f"Estante extra {estante['id']} en ({estante['x_m']}, {estante['y_m']})"] = kpi_con_costos_base(
                    solucion, base, estadisticas, nuevo, st.session_state.modo)
            else:
                st.warning("No hay lugar libre para un estante más que respete pasillos y despejes.")
        if con_objetivo:
            otro = "tienda" if st.session_state.modo == "almacen" else "almacen"
            barra.progress(0.7, text=f"Objetivo {otro}…")
            solucion = ejecutar_modelo(pesos, tiempo, modo=otro, parametros=parametros_activos(st.session_state.normas, otro, local))
            resultados[f"Objetivo {otro}"] = kpi_con_costos_base(solucion, base, estadisticas, local, st.session_state.modo)
        barra.empty()
        st.session_state.escenarios = resultados
    if st.session_state.escenarios:
        st.dataframe(tabla_antes_despues(st.session_state.escenarios), hide_index=True)
        st.caption("Todos los escenarios se miden con los costos de acceso de la propuesta para que la comparación sea pareja.")


def pantalla_sensibilidad():
    st.write("Se vuelve a ubicar los productos variando **±20 %** cada peso del objetivo, uno a la vez (mismo diseño de racks). "
             "Si pocos productos cambian de lugar, la propuesta es robusta. La sensibilidad de las CONCLUSIONES (precios, "
             "rotación, límite de peso y λ) está en el Paso 7.")
    tiempo = st.number_input("Tiempo límite por corrida (s)", 5, 300, 15, 5, key="tiempo_sensibilidad")
    if st.button("Calcular sensibilidad"):
        barra = st.progress(0.0, text="Sensibilidad…")
        pesos = st.session_state.get("pesos", AJUSTES["objetivo"])
        st.session_state.tabla_sensibilidad = sensibilidad(
            lambda p: ejecutar_modelo(p, tiempo), st.session_state.solucion, st.session_state.estadisticas_pedidos,
            local_resultado(), st.session_state.modo, pesos, 0.2, lambda f, t: barra.progress(min(f, 1.0), text=t),
            parametros_actuales(), incompatibilidades_activas(st.session_state.normas))
        barra.empty()
    if st.session_state.tabla_sensibilidad is not None:
        tabla = st.session_state.tabla_sensibilidad
        st.dataframe(tabla, hide_index=True)
        st.plotly_chart(px.bar(tabla, x="% que cambia", y=tabla["Peso variado"] + " " + tabla["Variación"], orientation="h",
                               labels={"y": ""}, title="% de productos que cambian de lugar"), key="grafico_sensibilidad")


def calcular_reporte_normativo():
    local = local_resultado()
    parametros = parametros_actuales()
    posiciones = st.session_state.solucion["posiciones"]
    semaforo = semaforo_local(st.session_state.normas, local, validar_local(local, parametros), posiciones,
                              st.session_state.catalogo, st.session_state.modo)
    st.session_state.reporte_normativo = reporte_final(st.session_state.normas, semaforo, st.session_state.validacion,
                                                       st.session_state.solucion["ubicaciones"], st.session_state.catalogo)
    return st.session_state.reporte_normativo


def reporte_normativo_pantalla():
    estado = st.session_state.normas
    tabla = pd.DataFrame(st.session_state.reporte_normativo)

    def color(valor):
        return {CUMPLE: "background-color:#c6efce", NO_CUMPLE: "background-color:#ffc7ce",
                POR_VERIFICAR: "background-color:#ffeb9c"}.get(valor, "")
    st.caption("Reporte normativo de la PROPUESTA (racks diseñados + ubicaciones).")
    st.dataframe(tabla.style.map(color, subset=["Resultado de la propuesta"]), hide_index=True, height=420)
    conteo = tabla["Resultado de la propuesta"].value_counts()
    columnas = st.columns(4)
    for posicion, resultado in enumerate([CUMPLE, NO_CUMPLE, POR_VERIFICAR, NO_APLICA]):
        columnas[posicion].metric(resultado.capitalize(), int(conteo.get(resultado, 0)))
    st.subheader("Excepciones autorizadas por el usuario")
    if estado["cambios"]:
        st.dataframe(pd.DataFrame(estado["cambios"]), hide_index=True)
    else:
        st.write("Ninguna: se aplicaron los valores incluidos en el programa.")
    st.caption("«Por verificar» = el valor numérico es un supuesto prudente que debe confirmarse en el texto oficial vigente "
               "(ver LEEME.md). Las normas no reemplazan la inspección de un profesional.")


# ======================================================================================
# Paso 7. Evidencia
# ======================================================================================

def ajustes_evidencia():
    ajustes = json.loads(json.dumps(AJUSTES))
    ajustes["evidencia"].update(st.session_state.get("parametros_evidencia", {}))
    ajustes["evidencia"]["umbrales"] = umbrales()
    return ajustes


def umbrales():
    valores = dict(AJUSTES["evidencia"]["umbrales"])
    valores.update(st.session_state.get("umbrales_veredicto", {}))
    return valores


def nombre_antes():
    return next(iter(st.session_state.antes))


def pedidos_mes():
    return st.session_state.estadisticas_pedidos["pedidos_por_dia"] * AJUSTES["operacion"]["dias_operacion_mes"]


def paso_7():
    planteamiento = st.session_state.setdefault("planteamiento", {"empresa": st.session_state.local.get("nombre") or "la empresa",
                                                                  "rubro": PERFILES[st.session_state.perfil]["nombre"],
                                                                  "problema": "", "objetivo": ""})
    st.write("Aquí se **demuestra con datos** si la propuesta resuelve un problema real: se simulan los pedidos reales de la "
             "empresa antes y después y se aplica un contraste de hipótesis. No es otro modelo de optimización.")
    with st.expander("1. Planteamiento del problema", expanded=st.session_state.get("evidencia") is None):
        with st.form("form_planteamiento"):
            columnas = st.columns(2)
            empresa = columnas[0].text_input("Empresa", planteamiento["empresa"])
            rubro = columnas[1].text_input("Rubro", planteamiento["rubro"])
            problema = st.text_area("Problema observado (con sus palabras)", planteamiento["problema"],
                                    placeholder="Ej.: los vendedores tardan en encontrar los productos que más se venden…")
            objetivo = st.text_area("Objetivo", planteamiento["objetivo"],
                                    placeholder="Ej.: reducir el tiempo de recorrido por pedido sin incumplir las normas.")
            if st.form_submit_button("Guardar planteamiento"):
                planteamiento.update(empresa=empresa, rubro=rubro, problema=problema, objetivo=objetivo)
    with st.expander("Parámetros de la simulación (supuestos editables)"):
        with st.form("form_parametros_evidencia"):
            actuales = ajustes_evidencia()["evidencia"]
            columnas = st.columns(4)
            muestra = columnas[0].number_input("Pedidos en la muestra", 100, 200000, int(actuales["muestra_pedidos"]), 500)
            replicas = columnas[1].number_input("Réplicas aleatorias", 0, 200, int(actuales["replicas_aleatorias"]), 5)
            velocidad = columnas[2].number_input("Velocidad de caminata (m/s)", 0.2, 3.0, float(actuales["velocidad_caminata_m_s"]), 0.1)
            segundos = columnas[3].number_input("Segundos por producto", 0.0, 300.0, float(actuales["segundos_por_producto"]), 1.0)
            if st.form_submit_button("Aplicar parámetros"):
                st.session_state.parametros_evidencia = {"muestra_pedidos": muestra, "replicas_aleatorias": replicas,
                                                         "velocidad_caminata_m_s": velocidad, "segundos_por_producto": segundos}
                st.session_state.evidencia = None
                st.rerun()
    if st.button("Calcular la evidencia (simulación con pedidos reales)", type="primary"):
        calcular_evidencia()
    analisis = st.session_state.get("evidencia")
    if analisis is None:
        st.info("Pulse el botón para simular los pedidos reales antes y después.")
        recuadro_limites(None)
        return
    preparar_veredicto(analisis, planteamiento)
    tarjeta_decision()
    if st.toggle("Ver el detalle técnico (gráficos y estadística para el artículo)", key="ver_detalle_evidencia"):
        mostrar_evidencia(analisis, planteamiento)
        recuadro_limites(analisis)
    else:
        recuadro_limites(analisis, mostrar=False)
        st.caption("No necesita leer el detalle para decidir: todo lo que va al artículo se exporta en el Paso 8.")
    boton_confirmar(7, "Revisé la evidencia, el veredicto y sus límites",
                    {"reduccion_pct": analisis["contraste"]["reduccion_pct"], "valor_p": analisis["contraste"]["valor_p"],
                     "prueba": analisis["contraste"]["prueba"], "veredicto": st.session_state.get("veredicto_estado"),
                     "semilla": analisis["semilla"]},
                    con_advertencias=st.session_state.get("veredicto_estado") != "verde")


def calcular_evidencia():
    solucion = st.session_state.solucion
    ajustes = ajustes_evidencia()
    barra = st.progress(0.0, text="Preparando…")
    inicio = time.time()
    nombre = nombre_antes()
    analisis = analizar_evidencia(solucion, st.session_state.antes[nombre], ventas_del_periodo(), pedidos_mes(), st.session_state.kpis,
                                  nombre, ajustes, avance=lambda f, t: barra.progress(min(f, 1.0), text=t))
    registrar_tiempo("Evidencia (simulación completa)", time.time() - inicio)
    barra.progress(0.95, text="Comprobando reproducibilidad…")
    reproducible = es_reproducible(solucion, st.session_state.antes[nombre], ventas_del_periodo(), pedidos_mes(), ajustes)
    ventas = st.session_state.ventas
    validacion = validacion_tecnica(st.session_state.validacion, st.session_state.resumen_union, round(float(ventas["total"].sum()), 2),
                                    int(len(ventas)), reproducible)
    ahorro, horas = ahorro_mensual_soles(analisis, ajustes)
    reubicacion = lista_reubicacion(st.session_state.antes[nombre], solucion["asignacion"], solucion["productos"],
                                    solucion["validas"], solucion["modo"])
    tabla = tabla_costeo_inicial(solucion["lista_compra"], len(reubicacion))
    economia = calcular_costeo(tabla, ahorro, AJUSTES["operacion"]["tasa_anual"], AJUSTES["operacion"]["horizonte_meses"])
    st.session_state.update(evidencia=analisis, validacion_tecnica=validacion, ahorro_mensual=ahorro, horas_ahorradas=horas,
                            economia_base=economia, tabla_costeo_inicial=tabla, reubicacion=reubicacion, sensibilidad_ev=None,
                            costeo=None)
    barra.empty()
    st.rerun()


def ubicacion_real():
    return nombre_antes().startswith("Antes (ubicación actual")


def mostrar_evidencia(analisis, planteamiento):
    solucion = st.session_state.solucion
    nombre = nombre_antes()
    diagnostico_datos = diagnostico(analisis, solucion, st.session_state.antes[nombre], st.session_state.kpis.get(nombre),
                                    st.session_state.get("semaforo"), planteamiento["empresa"], ubicacion_real())
    st.session_state.diagnostico = diagnostico_datos
    st.subheader("Diagnóstico de la situación actual")
    columnas = st.columns(4)
    columnas[0].metric("Distancia media por pedido (antes)", f"{diagnostico_datos['distancia_media_m']:.1f} m")
    columnas[1].metric("Tiempo medio por pedido (antes)", f"{diagnostico_datos['tiempo_medio_s']:.0f} s")
    columnas[2].metric("Clase A en posiciones desfavorables",
                       "—" if diagnostico_datos["pct_clase_a_desfavorable"] is None else f"{diagnostico_datos['pct_clase_a_desfavorable']:.0f} %")
    columnas[3].metric("Pedidos al mes", f"{diagnostico_datos['pedidos_mes']:,}")
    st.info("**Problema:** " + diagnostico_datos["frase"] + (f" {planteamiento['problema']}" if planteamiento["problema"] else ""))
    info = analisis["info_pedidos"]
    st.subheader("2. Simulación con pedidos reales")
    st.caption(f"{info['pedidos_usados']:,} pedidos simulados de {info['pedidos_totales']:,}"
               + (f" (muestra aleatoria reproducible, semilla {info['semilla']})" if info["muestreado"] else " (todos)")
               + f"; {info['productos_por_pedido']:.2f} productos por pedido; {info['pedidos_de_una_linea']:,} pedidos de una sola línea. "
               f"Rutas por los pasillos (caminos mínimos) con la heurística del vecino más cercano desde y hacia el despacho.")
    st.dataframe(analisis["escenarios"], hide_index=True)
    izquierda, derecha = st.columns(2)
    replicas = analisis["replicas"]
    figura = go.Figure()
    if len(replicas):
        figura.add_histogram(x=replicas, name="Réplicas aleatorias", marker_color="#bdbdbd")
    figura.add_vline(x=analisis["media_propuesta"], line_width=3, annotation_text="Propuesta")
    figura.add_vline(x=float(analisis["distancias_antes"].mean()), line_dash="dash", annotation_text="Antes")
    figura.update_layout(title="¿Dónde cae la propuesta entre distribuciones al azar?", xaxis_title="Distancia media por pedido (m)",
                         yaxis_title="Réplicas", height=360)
    izquierda.plotly_chart(figura, key="grafico_replicas")
    figura = px.histogram(x=analisis["diferencias"], nbins=40, labels={"x": "Reducción por pedido (m)"},
                          title="Reducción de la distancia en cada pedido")
    figura.update_layout(height=360, yaxis_title="Pedidos")
    derecha.plotly_chart(figura, key="grafico_reduccion")
    if analisis["percentil_propuesta"] is not None:
        st.caption(f"La propuesta recorre menos que el {100 - analisis['percentil_propuesta']:.0f} % de las "
                   f"{analisis['replicas_n']} réplicas aleatorias factibles.")
    st.subheader("3. Contraste de hipótesis")
    prueba = analisis["contraste"]
    st.markdown(f"- **H₀:** {prueba['h0']}\n- **H₁:** {prueba['h1']}")
    columnas = st.columns(5)
    columnas[0].metric("Prueba", prueba["prueba"])
    columnas[1].metric("Valor p", f"{prueba['valor_p']:.3g}")
    columnas[2].metric(f"Efecto ({prueba['nombre_efecto']})", f"{prueba['efecto']:.2f}")
    columnas[3].metric("Reducción media", f"{prueba['reduccion_pct']:.1f} %", f"{prueba['reduccion_media_m']:.2f} m", delta_color="off")
    columnas[4].metric("IC 95 % (bootstrap)", f"{prueba['ic95_pct'][0]:.1f} a {prueba['ic95_pct'][1]:.1f} %")
    st.write(prueba["explicacion"])
    if prueba.get("aviso_n_grande"):
        st.warning(prueba["aviso_n_grande"])
    st.subheader("Sensibilidad de las conclusiones (±20 %)")
    st.caption("Varía precios de racks, rotación (ruido por producto), límite de peso y λ, y vuelve a diseñar con la propuesta rápida.")
    if st.button("Calcular sensibilidad de las conclusiones"):
        sensibilidad_conclusiones_pantalla()
    if st.session_state.get("sensibilidad_ev") is not None:
        st.dataframe(st.session_state.sensibilidad_ev, hide_index=True)
    st.subheader("Validación técnica")
    st.dataframe(st.session_state.validacion_tecnica, hide_index=True)
    veredicto_pantalla(analisis)


def sensibilidad_conclusiones_pantalla():
    solucion = st.session_state.solucion
    ajustes = ajustes_evidencia()
    base_antes = nombre_antes()
    barra = st.progress(0.0, text="Sensibilidad…")

    def rediseñar(cambio):
        parametros = dict(parametros_actuales())
        lam = solucion["lambda"]
        resumen = resumen_productos()
        if "rotacion" in cambio:
            factor = cambio["rotacion"]
            rng = np.random.default_rng(AJUSTES["semilla"])
            ruido = rng.uniform(min(1.0, factor), max(1.0, factor), len(resumen))
            resumen = resumen.assign(rotacion_diaria=resumen["rotacion_diaria"] * ruido, margen_diario=resumen["margen_diario"] * ruido)
        if "limite_peso" in cambio and parametros.get("limite_peso_kg") is not None:
            parametros["limite_peso_kg"] = parametros["limite_peso_kg"] * cambio["limite_peso"]
        if "lambda" in cambio:
            lam = lam * cambio["lambda"]
        nueva = optimizar_diseno(**argumentos_diseno(st.session_state.get("pesos", AJUSTES["objetivo"]), parametros, lam, resumen),
                                 rapido=True)
        if nueva.get("sin_solucion"):
            return {"reduccion_pct": 0.0, "inversion": 0.0, "recuperacion_meses": None}
        antes = lineas_base(nueva)
        clave = base_antes if base_antes in antes else next(iter(antes))
        resultado = analizar_evidencia(nueva, antes[clave], ventas_del_periodo(), pedidos_mes(), None, clave, ajustes, replicas=0,
                                       muestra=1000)
        ahorro, _ = ahorro_mensual_soles(resultado, ajustes)
        reubicar = lista_reubicacion(antes[clave], nueva["asignacion"], nueva["productos"], nueva["validas"], nueva["modo"])
        economia = calcular_costeo(tabla_costeo_inicial(nueva["lista_compra"], len(reubicar)), ahorro,
                                   AJUSTES["operacion"]["tasa_anual"], AJUSTES["operacion"]["horizonte_meses"])
        return {"reduccion_pct": resultado["contraste"]["reduccion_pct"], "inversion": economia["inversion"],
                "recuperacion_meses": economia["recuperacion_meses"]}
    st.session_state.sensibilidad_ev = sensibilidad_conclusiones(
        rediseñar, {"reduccion_pct": st.session_state.evidencia["contraste"]["reduccion_pct"]}, umbrales(),
        economia_actual(), 0.2, lambda f, t: barra.progress(min(f, 1.0), text=t))
    barra.empty()


def economia_actual():
    """La economía del escenario de costeo elegido en el Paso 8 (o la inicial si aún no se editó)."""
    costeo = st.session_state.get("costeo_resultado")
    return costeo or st.session_state.economia_base


def datos_veredicto(analisis):
    reporte = pd.DataFrame(st.session_state.reporte_normativo)
    resultados = reporte["Resultado de la propuesta"] if "Resultado de la propuesta" in reporte else pd.Series(dtype=str)
    ubicaciones = st.session_state.solucion["ubicaciones"]
    return {"reduccion_pct": analisis["contraste"]["reduccion_pct"], "valor_p": analisis["contraste"]["valor_p"],
            "duros": len(st.session_state.validacion["duros"]), "ubicados": int(ubicaciones["ubicado"].sum()),
            "total_productos": len(ubicaciones), "no_cumple": int((resultados == NO_CUMPLE).sum()),
            "por_verificar": int((resultados == POR_VERIFICAR).sum()),
            "confiabilidad": indice_confiabilidad(st.session_state.catalogo, resumen_productos(), factor_local())["indice"],
            "recuperacion_meses": economia_actual()["recuperacion_meses"]}


def veredicto_pantalla(analisis):
    st.subheader("4. ¿Resuelve el problema?")
    valores = umbrales()
    with st.expander("Umbrales del veredicto (editables)"):
        columnas = st.columns(4)
        nuevos = {"reduccion_distancia_pct": columnas[0].number_input("Reducción mínima (%)", 0.0, 100.0, float(valores["reduccion_distancia_pct"]), 1.0),
                  "valor_p": columnas[1].number_input("Significancia α", 0.001, 0.2, float(valores["valor_p"]), 0.005, format="%.3f"),
                  "confiabilidad_pct": columnas[2].number_input("Confiabilidad mínima (%)", 0.0, 100.0, float(valores["confiabilidad_pct"]), 5.0),
                  "recuperacion_max_meses": columnas[3].number_input("Recuperación máxima (meses)", 1.0, 240.0,
                                                                     float(valores["recuperacion_max_meses"]), 1.0)}
        if nuevos != valores:
            st.session_state.umbrales_veredicto = nuevos
            valores = nuevos
    tabla, texto, estado = veredicto(datos_veredicto(analisis), valores)
    st.session_state.update(veredicto_tabla=tabla, veredicto_texto=texto, veredicto_estado=estado)
    iconos = {"verde": "🟢", "amarillo": "🟡", "rojo": "🔴"}
    st.dataframe(tabla.assign(Estado=tabla["Estado"].map(lambda e: f"{iconos[e]} {e}")), hide_index=True)
    {"verde": st.success, "amarillo": st.warning, "rojo": st.error}[estado](f"**Veredicto:** {texto}")


def preparar_veredicto(analisis, planteamiento):
    """Calcula el diagnóstico y el veredicto aunque el usuario no abra el detalle técnico."""
    solucion = st.session_state.solucion
    nombre = nombre_antes()
    st.session_state.diagnostico = diagnostico(analisis, solucion, st.session_state.antes[nombre], st.session_state.kpis.get(nombre),
                                               st.session_state.get("semaforo"), planteamiento["empresa"], ubicacion_real())
    tabla, texto, estado = veredicto(datos_veredicto(analisis), umbrales())
    st.session_state.update(veredicto_tabla=tabla, veredicto_texto=texto, veredicto_estado=estado)


def contexto_decision():
    return {"evidencia": st.session_state.evidencia, "economia": economia_actual(), "umbrales": umbrales(),
            "ubicacion_real": ubicacion_real()}


def tarjeta_decision():
    """El resultado final en un solo recuadro: qué hacer, por qué y qué falta confirmar."""
    if st.session_state.get("evidencia") is None:
        return
    d = decision(contexto_decision())
    with st.container(border=True):
        st.markdown("### 🎯 Decisión")
        {"verde": st.success, "amarillo": st.warning, "rojo": st.error}[d["color"]](f"### {d['accion']}")
        st.markdown(f"**Por qué:** {d['por_que']}")
        columnas = st.columns(len(d["cifras"]))
        for columna, (etiqueta, valor, ayuda) in zip(columnas, d["cifras"]):
            columna.metric(etiqueta, valor, help=ayuda)
            columna.caption(ayuda)
        pasos = "\n".join(f"{k}. {t}" for k, t in enumerate(d["siguientes"], 1))
        st.markdown(f"**Qué hacer ahora:**\n\n{pasos}")


def recuadro_limites(analisis, mostrar=True):
    datos_normas = resumen_normas(st.session_state.normas)
    info = analisis["info_pedidos"] if analisis else {}
    limites = limites_evidencia(indice_confiabilidad(st.session_state.catalogo, resumen_productos(), factor_local()),
                                st.session_state.resumen_union, ubicacion_real(), datos_normas["por_verificar"], info)
    st.session_state.limites = limites
    if not mostrar:
        return
    with st.container(border=True):
        st.markdown("#### ⚠️ Límites de la evidencia")
        st.markdown("\n".join(f"- {t}" for t in limites))


# ======================================================================================
# Paso 8. Costeo y entregables
# ======================================================================================

def paso_8():
    if st.session_state.get("evidencia") is None:
        st.warning("Primero calcule la evidencia en el Paso 7.")
        return
    tarjeta_decision()
    exportar_articulo_pantalla()
    st.divider()
    st.subheader("Costeo editable (dos escenarios)")
    solucion_actual = st.session_state.get("solucion") or {}
    if (solucion_actual.get("cobertura") or {}).get("activa"):
        st.info("El costeo incluye TODOS los racks de la propuesta de capacidad máxima (también los vacíos): "
                "no corresponde solo al stock actual.")
    st.caption(f"Edite cantidades y precios: el total, el ahorro, la recuperación, el VAN y la TIR se recalculan al instante sin "
               f"volver a optimizar. Precios de racks: {ROTULO_PRECIOS}.")
    costeo_fragmento()
    st.divider()
    informe_gerencial_pantalla()
    st.divider()
    with st.expander("Más archivos (paquete completo, Excel de la propuesta, 3D, acta)"):
        paquete_articulo_pantalla()
        otros_entregables()


@st.fragment
def costeo_fragmento():
    if st.session_state.get("costeo") is None:
        guardado = cargar_escenarios_costeo(ruta_costeo())
        if guardado and len(guardado) >= 2 and st.session_state.get("usar_costeo_guardado"):
            st.session_state.costeo = guardado
        else:
            base = st.session_state.tabla_costeo_inicial
            st.session_state.costeo = {"Proveedor A": {"tabla": base.copy()}, "Proveedor B": {"tabla": base.copy()}}
    if (ruta_costeo().exists() and not st.session_state.get("usar_costeo_guardado")
            and st.button("Reabrir el costeo guardado")):
        st.session_state.usar_costeo_guardado = True
        st.session_state.version_costeo = st.session_state.get("version_costeo", 0) + 1
        st.session_state.costeo = None
        st.rerun(scope="fragment")
    columnas = st.columns(3)
    tasa = columnas[0].number_input("Tasa de descuento anual (%)", 0.0, 100.0, AJUSTES["operacion"]["tasa_anual"] * 100, 0.5,
                                    key="tasa_costeo") / 100
    horizonte = columnas[1].number_input("Horizonte (meses)", 1, 240, AJUSTES["operacion"]["horizonte_meses"], key="horizonte_costeo")
    ahorro = columnas[2].number_input("Ahorro mensual estimado (S/)", 0.0, 1e7, float(st.session_state.ahorro_mensual), 10.0,
                                      key="ahorro_costeo", help="Viene de la simulación del Paso 7 (menor tiempo × tarifa). Editable.")
    escenarios = st.session_state.costeo
    nombres = list(escenarios)[:2]
    resultados = {}
    columnas = st.columns(2)
    inicio = time.perf_counter()
    for posicion, (columna, nombre) in enumerate(zip(columnas, nombres)):
        with columna:
            st.markdown(f"**{nombre}**")
            editada = st.data_editor(escenarios[nombre]["tabla"], num_rows="dynamic", hide_index=True, key=f"costeo_{posicion}_{st.session_state.get('version_costeo', 0)}",
                                     column_config={"precio_unitario": st.column_config.NumberColumn("Precio unitario (S/)", min_value=0.0),
                                                    "cantidad": st.column_config.NumberColumn("Cantidad", min_value=0.0)})
            resultado = calcular_costeo(editada, ahorro, tasa, horizonte)
            resultados[nombre] = dict(resultado, tabla=editada)
            fila = st.columns(3)
            fila[0].metric("Inversión total", formato_soles(resultado["inversion"]))
            fila[1].metric("Recuperación", "no se recupera" if resultado["recuperacion_meses"] is None else f"{resultado['recuperacion_meses']} meses")
            fila[2].metric("Ahorro anual", formato_soles(resultado["ahorro_anual"]))
            fila = st.columns(2)
            fila[0].metric(f"VAN ({horizonte} meses)", formato_soles(resultado["van"]))
            fila[1].metric("TIR anual", "—" if resultado["tir_anual"] is None else f"{resultado['tir_anual'] * 100:.1f} %")
    duracion = (time.perf_counter() - inicio) * 1000
    registrar_tiempo("Recalcular el costeo (ms)", duracion)
    st.caption(f"Recalculado en {duracion:.0f} ms.")
    elegido = st.radio("Escenario para el informe y el veredicto", nombres, horizontal=True, key="escenario_informe")
    st.session_state.costeo_resultados = resultados
    st.session_state.costeo_resultado = {k: v for k, v in resultados[elegido].items() if k != "tabla"}
    if st.button("💾 Guardar costeo (para reabrirlo y seguir editando)"):
        ruta = guardar_escenarios_costeo({n: {"tabla": r["tabla"]} for n, r in resultados.items()}, ruta_costeo())
        st.success(f"Guardado en {ruta}.")


def datos_informe():
    solucion = st.session_state.solucion
    economia = st.session_state.costeo_resultado or st.session_state.economia_base
    prueba = st.session_state.evidencia["contraste"]
    planteamiento = st.session_state.get("planteamiento", {})
    reporte = pd.DataFrame(st.session_state.reporte_normativo)
    conteo = reporte["Resultado de la propuesta"].value_counts() if len(reporte) else {}
    return {"titulo": "Informe gerencial — redistribución del local", "empresa": planteamiento.get("empresa", ""),
            "responsable": responsable(), "economia": economia,
            "problema": st.session_state.diagnostico["frase"] + (" " + planteamiento.get("problema", "") if planteamiento.get("problema") else ""),
            "solucion": (f"Instalar {solucion['modulos_nuevos']} módulos de rack nuevos"
                         + (f" y conservar {solucion['modulos_existentes']} existentes" if solucion["modulos_existentes"] else "")
                         + f", y reubicar los productos según la propuesta optimizada. La distancia media por pedido baja de "
                           f"{prueba['media_antes_m']:.1f} m a {prueba['media_despues_m']:.1f} m ({prueba['reduccion_pct']:.1f} %, "
                           f"IC 95 % {prueba['ic95_pct'][0]:.1f} % a {prueba['ic95_pct'][1]:.1f} %; {prueba['prueba']}, p = {prueba['valor_p']:.3g})."),
            "riesgos": ("Precios de proveedor distintos a los supuestos; medidas estimadas de productos "
                        f"(confiabilidad {datos_veredicto(st.session_state.evidencia)['confiabilidad']:.0f} %); la mejora es simulada; "
                        "la reubicación interrumpe la operación durante unas horas."),
            "normativo": (f"{int(conteo.get(CUMPLE, 0))} normas cumplen, {int(conteo.get(NO_CUMPLE, 0))} no cumplen y "
                          f"{int(conteo.get(POR_VERIFICAR, 0))} están por verificar en el texto oficial."),
            "supuestos": (f"Velocidad de caminata {ajustes_evidencia()['evidencia']['velocidad_caminata_m_s']} m/s; "
                          f"{ajustes_evidencia()['evidencia']['segundos_por_producto']} s por producto; tarifa "
                          f"S/ {AJUSTES['operacion']['tarifa_hora_soles']}/h; precios de racks referenciales."),
            "recomendacion": st.session_state.get("recomendacion_texto") or st.session_state.get("veredicto_texto", "")}


def tablas_gerencia():
    solucion = st.session_state.solucion
    nombre = st.session_state.get("escenario_informe") or next(iter(st.session_state.costeo_resultados))
    costeo = calcular_costeo_tabla(st.session_state.costeo_resultados[nombre]["tabla"])
    return {"Costeo (precios supuestos)": costeo[["concepto", "cantidad", "precio_unitario", "subtotal", "supuesto"]],
            "Lista de compra de racks": solucion["lista_compra"] if len(solucion["lista_compra"]) else
            pd.DataFrame([{"nota": "No se compran racks."}]),
            "Antes y después (simulación)": st.session_state.evidencia["escenarios"][["Escenario", "Distancia media por pedido (m)",
                                                                                     "Tiempo medio por pedido (s)"]]}


def informe_gerencial_pantalla():
    st.subheader("Informe gerencial (1 a 2 páginas)")
    st.text_area("Recomendación (puede editarla)", st.session_state.get("veredicto_texto", ""), key="recomendacion_texto")
    if st.button("📄 Exportar informe gerencial", type="primary"):
        inicio = time.time()
        datos = datos_informe()
        tablas = tablas_gerencia()
        figura = reportes.figura_plano(local_resultado(), st.session_state.solucion["posiciones"], st.session_state.solucion["ubicaciones"],
                                       "abc", "Propuesta de distribución")
        ruta_png = CARPETA_RESULTADOS / "plano_informe_gerencial.png"
        figura.savefig(ruta_png, dpi=150, bbox_inches="tight")
        import matplotlib.pyplot as plt
        plt.close(figura)
        excel = informe_excel(datos, tablas)
        word = informe_word(datos, tablas, ruta_png)
        st.session_state.informe_gerencial = {"xlsx": excel.read_bytes(), "docx": word.read_bytes()}
        registrar_tiempo("Exportar informe gerencial", time.time() - inicio)
    if st.session_state.get("informe_gerencial"):
        columnas = st.columns(2)
        columnas[0].download_button("⬇️ informe_gerencial.docx", st.session_state.informe_gerencial["docx"], "informe_gerencial.docx")
        columnas[1].download_button("⬇️ informe_gerencial.xlsx", st.session_state.informe_gerencial["xlsx"], "informe_gerencial.xlsx")


def contexto_articulo():
    solucion = st.session_state.solucion
    nombre = nombre_antes()
    union = st.session_state.resumen_union
    return {"union": union, "calidad": st.session_state.calidad,
            "confiabilidad": indice_confiabilidad(st.session_state.catalogo, resumen_productos(), factor_local()),
            "evidencia": st.session_state.evidencia, "resumen": resumen_productos(), "local_base": st.session_state.local,
            "modo_diseno": solucion["modo_diseno"],
            "pasillo_m": (solucion.get("info_candidatos") or {}).get("requerido_m") or ancho_pasillo_requerido_diseno(
                st.session_state.local, parametros_actuales()),
            "presupuesto": solucion.get("presupuesto"), "lambda": solucion["lambda"], "ajustes": ajustes_evidencia(),
            "parametros": parametros_actuales(), "lista_compra": solucion["lista_compra"],
            "sensibilidad": st.session_state.get("sensibilidad_ev"), "economia": economia_actual(),
            "reporte_normativo": pd.DataFrame(st.session_state.reporte_normativo), "solucion": solucion,
            "antes": st.session_state.antes[nombre], "nombre_antes": nombre, "umbrales": umbrales(),
            "empresa": st.session_state.get("planteamiento", {}).get("empresa") or "la empresa",
            "diagnostico": st.session_state.diagnostico, "problema_usuario": st.session_state.get("planteamiento", {}).get("problema"),
            "veredicto_texto": st.session_state.get("veredicto_texto", ""), "ubicacion_real": ubicacion_real(), "limites": st.session_state.get("limites", []),
            "normas": st.session_state.normas, "responsable": responsable(),
            "archivo_catalogo": st.session_state.get("catalogo_nombre"),
            "archivo_ventas": (st.session_state.origen_ventas or ("", ""))[-1]}


def ruta_costeo():
    carpeta = CARPETA_RESULTADOS / "proyectos" / str(st.session_state.get("_proyecto") or "local")
    carpeta.mkdir(parents=True, exist_ok=True)
    return carpeta / "costeo.json"


def carpeta_articulo():
    return CARPETA_RESULTADOS / "proyectos" / str(st.session_state.get("_proyecto") or "local") / "articulo"


def exportar_articulo_pantalla():
    """Un solo botón con lo necesario para redactar: el borrador en Word, la decisión, tablas y figuras."""
    st.subheader("📝 Para su artículo")
    st.write("Un clic y descarga: **el borrador del artículo en Word** (con sus cifras ya escritas y lo que falta resaltado "
             "en amarillo), la **decisión en una página**, las **tablas** y las **figuras** listas para pegar.")
    if st.button("Preparar los archivos del artículo", type="primary", key="preparar_articulo"):
        generar_paquete_articulo()
    paquete = st.session_state.get("paquete_articulo")
    if paquete:
        columnas = st.columns(3)
        columnas[0].download_button("⬇️ Borrador del artículo (Word)", paquete["borrador"], "BORRADOR_articulo.docx",
                                    type="primary")
        columnas[1].download_button("⬇️ Tablas (Word)", paquete["tablas"], "tablas_articulo.docx")
        columnas[2].download_button("⬇️ Todo junto (.zip)", paquete["zip"], "paquete_articulo.zip")


def generar_paquete_articulo():
    inicio = time.time()
    with st.spinner("Escribiendo el borrador, las tablas y las figuras… (unos segundos)"):
        resumen = generar_paquete(contexto_articulo(), carpeta_articulo())
    carpeta = resumen["carpeta"]
    archivos = [carpeta / a for a in resumen["archivos"]]
    st.session_state.paquete_articulo = {"zip": reportes.zip_entregables(archivos), "resumen": resumen,
                                         "borrador": (carpeta / "BORRADOR_articulo.docx").read_bytes(),
                                         "tablas": (carpeta / "tablas_articulo.docx").read_bytes()}
    registrar_tiempo("Generar paquete del artículo", time.time() - inicio)


def paquete_articulo_pantalla():
    st.subheader("Paquete para redactar el artículo")
    st.caption("Tablas 1–9 (Excel y Word, estilo APA), figuras 1–8 (PNG 300 ppp y HTML), párrafos con las cifras reales, "
               "ficha metodológica, normas y fuentes, e índice. Se guarda en resultados/articulo/.")
    if st.button("📦 Generar paquete del artículo"):
        generar_paquete_articulo()
    if st.session_state.get("paquete_articulo"):
        resumen = st.session_state.paquete_articulo["resumen"]
        st.success(f"{resumen['tablas']} tablas y {resumen['figuras']} figuras.")
        st.download_button("⬇️ Paquete del artículo (.zip)", st.session_state.paquete_articulo["zip"], "paquete_articulo.zip")


def otros_entregables():
    solucion = st.session_state.solucion
    nombre = nombre_antes()
    reubicacion = st.session_state.reubicacion
    economia = economia_actual()
    st.subheader("Lista de reubicación (lo que más rinde primero)")
    st.dataframe(reubicacion.head(300), hide_index=True, height=260)
    if st.button("Generar todos los entregables", type="primary"):
        generar_entregables(reubicacion, economia, nombre)
    if st.session_state.get("entregables"):
        archivos = st.session_state.entregables
        st.success(f"Entregables guardados en la carpeta `{CARPETA_RESULTADOS}`.")
        columnas = st.columns(5)
        columnas[0].download_button("⬇️ propuesta_distribucion.xlsx", archivos["excel"], "propuesta_distribucion.xlsx")
        columnas[1].download_button("⬇️ visual_3d.html", archivos["html"], "visual_3d.html", "text/html")
        columnas[2].download_button("⬇️ Acta (Markdown)", archivos["acta"].encode("utf-8"), "acta_confirmaciones.md")
        columnas[3].download_button("⬇️ Lista de compra (CSV)", solucion["lista_compra"].to_csv(index=False).encode("utf-8-sig"),
                                    "lista_compra_racks.csv")
        columnas[4].download_button("⬇️ Figuras, tablas e informe (.zip)", archivos["zip"], "informe_acomoda.zip")
        boton_confirmar(8, "Entregables revisados", {"archivos": ", ".join(archivos["lista"])})


def generar_entregables(reubicacion, economia, nombre_antes_texto):
    solucion = st.session_state.solucion
    local, catalogo = local_resultado(), st.session_state.catalogo
    parametros = parametros_actuales()
    kpis = st.session_state.kpis
    resumen = resumen_productos()
    union = st.session_state.resumen_union
    confiabilidad = indice_confiabilidad(catalogo, resumen, factor_local())
    barra = st.progress(0.0, text="Excel de la propuesta…")
    tabla_kpi = tabla_antes_despues(kpis)
    resumen_tabla = reportes.tabla_resumen({
        "Fecha": datetime.now().strftime("%d/%m/%Y %H:%M"), "Responsable": responsable(),
        "Local": f"{local.get('nombre') or '-'} ({local['largo_m']} × {local['ancho_m']} m){' — EJEMPLO, NO ES REAL' if local.get('es_ejemplo') else ''}",
        "Modo": solucion["modo"], "Modo de diseño": solucion["modo_diseno"], "Perfil": PERFILES[st.session_state.perfil]["nombre"],
        "Módulos nuevos": solucion["modulos_nuevos"], "Inversión en racks (S/, supuesto)": solucion["inversion_racks"],
        "Tipo de propuesta": ("Capacidad máxima (llenar el local), no del stock actual; "
                              f"{len(solucion.get('modulos_vacios', []))} racks vacíos")
        if (solucion.get("cobertura") or {}).get("activa") else "Según el stock actual",
        "Estado del solver": solucion["estado"], "Brecha": "—" if solucion["brecha"] is None else f"{solucion['brecha'] * 100:.2f} %",
        "Tiempo (s)": solucion["tiempo_s"], "Productos ubicados": int(solucion["ubicaciones"]["ubicado"].sum()),
        "Productos sin ubicar": int((~solucion["ubicaciones"]["ubicado"]).sum()),
        "Índice de confiabilidad (%)": confiabilidad["indice"], "Comparado contra": nombre_antes_texto,
        "Ahorro mensual (S/)": economia["ahorro_mensual"], "Inversión total (S/)": economia["inversion"],
        "Recuperación (meses)": economia["recuperacion_meses"], "VAN (S/)": economia["van"],
        "Veredicto": st.session_state.get("veredicto_texto", ""),
        "Faltante": solucion["faltante"]["texto"] if solucion["faltante"] else "Todo cupo."})
    excel = reportes.excel_propuesta({
        "resumen": resumen_tabla, "diseno de racks": solucion["tabla_diseno"], "lista de compra": solucion["lista_compra"],
        "ubicaciones": solucion["ubicaciones"], "lista de reubicacion": reubicacion,
        "indicadores": tabla_kpi, "evidencia": st.session_state.evidencia["escenarios"],
        "reporte normativo": pd.DataFrame(st.session_state.reporte_normativo),
        "calidad de datos": reportes.tabla_calidad(st.session_state.calidad, union),
        "supuestos": reportes.tabla_supuestos(catalogo, local, AJUSTES, parametros), "acta": reportes.tabla_acta(st.session_state.id_sesion),
        "cambios a normas": pd.DataFrame(st.session_state.normas["cambios"], columns=["fecha", "norma", "cambio", "original", "responsable"])})
    barra.progress(0.3, text="Vista 3D…")
    antes = st.session_state.antes[nombre_antes_texto]
    figura = figura_3d(local, parametros=parametros, solucion=solucion, asignacion_antes=antes,
                       titulo="Acomoda — propuesta de distribución" + (" (EJEMPLO, NO ES REAL)" if local.get("es_ejemplo") else ""))
    ruta_html = guardar_html(figura, CARPETA_RESULTADOS / "visual_3d.html")
    barra.progress(0.5, text="Figuras para el informe…")
    meses = ventas_por_mes(ventas_del_periodo())
    rutas_figuras = reportes.figuras_informe(local, solucion, resumen, meses, kpis, st.session_state.tabla_sensibilidad)
    ruta_tablas = reportes.tablas_informe({"indicadores": tabla_kpi, "abc": resumen[["producto", "categoria", "ventas_soles",
                                                                                     "participacion", "acumulado", "clase_abc"]],
                                           "ventas por mes": meses, "economia": pd.DataFrame([economia]),
                                           "reporte normativo": pd.DataFrame(st.session_state.reporte_normativo)})
    barra.progress(0.8, text="Acta e informe…")
    acta = reportes.acta_markdown(st.session_state.normas["cambios"], st.session_state.id_sesion)
    limitaciones = list(st.session_state.get("limites", [])) + [
        "Cada producto ocupa una sola posición (o tramos contiguos de un mismo nivel); no se modela reposición desde reserva."]
    if local.get("es_ejemplo"):
        limitaciones.insert(0, "El local usado es el LOCAL DE EJEMPLO (EJEMPLO, NO ES REAL): mida el local verdadero.")
    economia_informe = {"movimientos": len(reubicacion), "horas_reubicacion": round(len(reubicacion) * AJUSTES["operacion"]["minutos_reubicar_producto"] / 60, 1),
                        "costo_reubicacion": economia["inversion"], "ahorro_mensual": economia["ahorro_mensual"],
                        "horas_ahorradas_mes": st.session_state.get("horas_ahorradas", 0), "recuperacion_meses": economia["recuperacion_meses"],
                        "horizonte_meses": economia["horizonte_meses"], "tasa_anual": economia["tasa_anual"], "van": economia["van"]}
    reportes.informe_markdown({
        "caso": local.get("nombre") or "tienda", "productos": len(catalogo), "con_ventas": union["productos_con_ventas"],
        "periodo": f"{union['fecha_min']:%d/%m/%Y} – {union['fecha_max']:%d/%m/%Y}", "dias": union["dias_periodo"],
        "local": f"{local['largo_m']} × {local['ancho_m']} m, altura libre {local['altura_libre_m']} m, {len(local['estantes'])} racks",
        "corte_a": f"{AJUSTES['abc']['corte_a']:.0%}", "corte_b": f"{AJUSTES['abc']['corte_b']:.0%}",
        "posiciones_validas": len(solucion["validas"]), "modo": solucion["modo"],
        "objetivo_texto": ("minimizar Σ rotación·costo_acceso·x + λ·Σ costo_anualizado·z + penalizaciones" if solucion["modo"] == "almacen"
                           else "maximizar Σ margen_esperado·exposición·x − λ·Σ costo_anualizado·z"),
        "limite_peso": parametros.get("limite_peso_kg"), "dias_cobertura": parametros.get("dias_cobertura"),
        "variables": solucion["variables"], "restricciones": solucion["restricciones"], "estado": solucion["estado"],
        "brecha": "—" if solucion["brecha"] is None else f"{solucion['brecha'] * 100:.2f} %", "tiempo": solucion["tiempo_s"],
        "confiabilidad": confiabilidad["indice"], "tabla_kpi_md": reportes.tabla_markdown(tabla_kpi),
        "movimientos": economia_informe["movimientos"], "horas_reubicacion": economia_informe["horas_reubicacion"],
        "costo_reubicacion": economia_informe["costo_reubicacion"], "ahorro_mensual": economia_informe["ahorro_mensual"],
        "horas_ahorradas": economia_informe["horas_ahorradas_mes"], "recuperacion": economia_informe["recuperacion_meses"],
        "horizonte": economia_informe["horizonte_meses"], "tasa": f"{economia_informe['tasa_anual']:.1%}", "van": economia_informe["van"],
        "limitaciones_md": "\n".join(f"- {t}" for t in limitaciones)})
    rutas_zip = rutas_figuras + [ruta_tablas, CARPETA_RESULTADOS / "informe_esqueleto.md", CARPETA_RESULTADOS / "acta_confirmaciones.md",
                                 CARPETA_RESULTADOS / "propuesta_distribucion.xlsx", ruta_html]
    st.session_state.entregables = {"excel": excel, "html": ruta_html.read_bytes(), "acta": acta, "zip": reportes.zip_entregables(rutas_zip),
                                    "lista": [r.name for r in rutas_zip]}
    barra.empty()
    st.rerun()


def panel_rendimiento():
    tiempos = st.session_state.get("tiempos")
    if tiempos:
        with st.sidebar.expander("⏱️ Rendimiento (última corrida)"):
            st.dataframe(pd.DataFrame([{"Operación": k, "Tiempo": f"{v:.0f} ms" if "(ms)" in k else f"{v:.2f} s"}
                                       for k, v in tiempos.items()]), hide_index=True)


# ======================================================================================
# Programa principal
# ======================================================================================

def evitar_traduccion():
    """El traductor automático del navegador (Chrome/Edge) cambia el texto de la página: rompe React
    («removeChild … no es un hijo de este nodo») y traduce mal unidades («1.2 m o más» → «1.2 meses más»).
    Se declara la página en español y se marca como «no traducir»."""
    st.html("""<script>
    const d = document;
    d.documentElement.lang = 'es';
    d.documentElement.setAttribute('translate', 'no');
    d.documentElement.classList.add('notranslate');
    d.body && d.body.setAttribute('translate', 'no');
    if (!d.querySelector('meta[name="google"]')) {
      const m = d.createElement('meta'); m.name = 'google'; m.content = 'notranslate'; d.head.appendChild(m);
    }
    </script>""", unsafe_allow_javascript=True)


# ======================================================================================
# Guardado automático del proyecto (sobrevive a recargar la página)
# ======================================================================================

def restaurar_proyecto():
    """Al abrir la página: si el enlace trae ?p=CODIGO y ese proyecto existe, se recupera todo su estado."""
    if st.session_state.get("_proyecto_listo"):
        return
    codigo = st.query_params.get("p") or persistencia.ultimo()
    if persistencia.existe(codigo):
        for clave, valor in (persistencia.cargar(codigo) or {}).items():
            if str(clave).startswith(BOTONES_NO_GUARDAR) or es_estado_de_tabla_editable(valor):
                continue  # proyectos guardados con versiones anteriores
            try:
                st.session_state[clave] = valor
            except Exception:  # p. ej. el estado de un botón: no se puede (ni hace falta) restaurar
                pass
    elif not persistencia.codigo_valido(codigo):
        codigo = persistencia.nuevo_codigo()
        st.query_params["p"] = codigo
        try:
            persistencia.limpiar_antiguos()
        except Exception:
            pass
    st.session_state._proyecto = codigo
    st.session_state._firmas = {}
    st.session_state._proyecto_listo = True


# Botones y cargadores de archivos: Streamlit no deja restaurar su valor, por eso no se guardan
BOTONES_NO_GUARDAR = ("FormSubmitter", "ir_", "boton_", "abrir_tutorial", "preparar_articulo", "aplicar_propuesta",
                      "cerrar_propuesta", "editar_a_mano", "confirmar_", "form_atras", "form_crear", "form_siguiente", "tour_", "descargar_", "abrir_recorrido",
                      "subir_", "editor_", "lienzo_")


def es_estado_de_tabla_editable(valor):
    """st.data_editor guarda {edited_rows, added_rows, deleted_rows}: Streamlit no deja restaurarlo."""
    try:
        return hasattr(valor, "keys") and {"edited_rows", "added_rows", "deleted_rows"} <= set(valor.keys())
    except Exception:
        return False


def guardar_proyecto():
    codigo = st.session_state.get("_proyecto")
    if not codigo:
        return
    if st.query_params.get("p") != codigo:
        st.query_params["p"] = codigo  # el enlace siempre muestra el código, para que el usuario lo pueda guardar
    estado = {clave: valor for clave, valor in st.session_state.items()
              if not str(clave).startswith("_") and not str(clave).startswith(BOTONES_NO_GUARDAR)
              and not es_estado_de_tabla_editable(valor)}
    try:
        persistencia.guardar(codigo, estado, st.session_state._firmas)
        persistencia.recordar_ultimo(codigo)
    except Exception as error:  # nunca interrumpir al usuario por un problema al guardar
        st.sidebar.warning(f"No se pudo guardar el progreso en esta computadora: {error}")


def nuevo_proyecto():
    for clave in list(st.session_state.keys()):
        if clave != "responsable":
            del st.session_state[clave]
    st.query_params.clear()
    st.query_params["p"] = persistencia.nuevo_codigo()
    st.rerun()


RUTA_TUTORIAL = Path(__file__).resolve().parent / "TUTORIAL.md"


def pagina_tutorial():
    if st.button("⬅️ Volver a mi proyecto", type="primary"):
        st.session_state._ver_tutorial = False
        if st.query_params.get("vista"):
            del st.query_params["vista"]
        st.rerun()
    st.caption("Enlace directo a este tutorial: agregue `?vista=tutorial` a la dirección de la app.")
    texto = RUTA_TUTORIAL.read_text(encoding="utf-8") if RUTA_TUTORIAL.exists() else "No se encontró TUTORIAL.md."
    st.markdown(texto)
    st.download_button("⬇️ Descargar el tutorial", texto.encode("utf-8"), "TUTORIAL_acomoda.md")


def principal():
    evitar_traduccion()
    st.html(guia.CSS)
    if st.query_params.get("vista") == "tutorial" and "_ver_tutorial" not in st.session_state:
        st.session_state._ver_tutorial = True
    restaurar_proyecto()
    iniciar_estado()
    if st.session_state.get("_ver_tutorial"):
        with st.sidebar:
            st.title("📦 Acomoda")
        pagina_tutorial()
        guardar_proyecto()
        return
    try:
        barra_lateral()
        paso = st.session_state.paso
        if not puede_abrir_paso(paso, st.session_state.confirmados):
            st.session_state.paso = paso = 1
        encabezado()
        pantallas = {1: paso_1, 2: paso_2, 3: paso_3, 4: paso_4, 5: paso_5, 6: paso_6, 7: paso_7, 8: paso_8}
        pantallas[paso]()
        panel_rendimiento()
        if "_recorrido" not in st.session_state:
            st.session_state._recorrido = 0 if guia.primera_vez() else None
        if st.session_state._recorrido is not None:
            recorrido()
    finally:
        guardar_proyecto()  # también corre cuando un botón pide st.rerun()


principal()
