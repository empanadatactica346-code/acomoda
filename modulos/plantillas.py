"""Genera y valida las tres plantillas descargables: catálogo, local y ventas.

Cada plantilla tiene las hojas INSTRUCCIONES, DATOS (o varias hojas de datos en la del
local), EJEMPLO y LISTAS (oculta, con las opciones de las listas desplegables).
"""

import io
from datetime import datetime, date

import pandas as pd
from openpyxl import Workbook, load_workbook
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from modulos.comun import (CARPETA_PLANTILLAS, a_numero, a_si_no, cargar_ajustes,
                           vacio)

VERSION_PLANTILLA = cargar_ajustes()["version_plantilla"]

# Colores de las celdas de encabezado
COLOR_OBLIGATORIA = "F4B183"   # naranja: si falta, es error
COLOR_IMPORTANTE = "FFE699"    # amarillo: si falta, se estima y baja la confiabilidad
COLOR_OPCIONAL = "BDD7EE"      # celeste: opcional
COLOR_INFORMATIVA = "D9D9D9"   # gris: solo informativa, el programa la ignora
COLOR_ERROR = "FF7C80"

SI_NO = ["si", "no"]
TEMPERATURAS = ["ambiente", "refrigerado", "congelado"]
TIPOS_OBSTACULO = ["columna", "muro", "puerta", "escalera", "tablero", "extintor",
                   "salida_emergencia", "luminaria", "rociador"]
TIPOS_ZONA = ["recepcion", "despacho", "devoluciones", "cuarentena", "caja", "ingreso",
              "picking", "reserva", "controlada"]
TIPOS_ESTANTE = ["gondola", "estante_metalico", "rack_selectivo", "vitrina", "exhibidor_pared",
                 "refrigerador", "congelador", "gondola_tienda", "estante_ligero", "estante_archivo", "cantilever"]
TIPOS_EQUIPO = ["manual", "transpaleta", "apilador", "montacargas"]
USOS_PASILLO = ["peatonal", "clientes", "transpaleta", "montacargas", "evacuacion"]
ORIENTACIONES = ["0", "90", "180", "270"]
MODOS_DISENO = ["A", "B", "C"]
EQUIPOS_MANIPULACION = ["manual", "mecanico"]

# Hojas del local que se pueden omitir (si faltan, no es error)
HOJAS_OPCIONALES = {"ESTANTES_EXISTENTES", "PREFERENCIAS_Y_PRESUPUESTO"}

GUIA_MIGRACION_LOCAL = (
    "Guía de migración desde la plantilla 2.0: (1) descargue la plantilla nueva del local; (2) copie LOCAL, OBSTACULOS, "
    "ZONAS, EQUIPOS y PASILLOS tal cual; (3) la hoja ESTANTES ya no es obligatoria: si quiere CONSERVAR esos estantes, "
    "cópielos en ESTANTES_EXISTENTES y elija el modo B (solo reutilizar) o C (mixto) en PREFERENCIAS_Y_PRESUPUESTO; "
    "si no, déjela vacía y el programa diseñará los racks (modo A).")


def columna(nombre, nivel, tipo, descripcion, unidad="", ejemplo="", lista=None):
    """Describe una columna de plantilla.
    nivel: 'obligatoria', 'importante', 'opcional'.
    tipo: 'texto', 'numero', 'numero_pos', 'numero_no_neg', 'entero_pos', 'si_no', 'fecha', 'lista', 'lista_niveles'.
    """
    return {"nombre": nombre, "nivel": nivel, "tipo": tipo, "descripcion": descripcion,
            "unidad": unidad, "ejemplo": ejemplo, "lista": lista}


COLUMNAS_CATALOGO = [
    columna("codigo_barras", "obligatoria", "texto", "Código de barras tal como lo lee la lectora. Si no tiene, deje vacío y llene el SKU.", "", "7750000000017"),
    columna("sku", "opcional", "texto", "Código interno del producto.", "", "EJ-001"),
    columna("producto", "obligatoria", "texto", "Nombre del producto.", "", "PRODUCTO DE EJEMPLO 500ML"),
    columna("categoria", "importante", "texto", "Categoría (HOGAR, BEBIDAS, LIMPIEZA...). Si falta, se adivina por el nombre.", "", "BEBIDAS"),
    columna("precio_compra", "importante", "numero_no_neg", "Costo unitario de compra.", "soles", "1.20"),
    columna("precio_venta", "importante", "numero_no_neg", "Precio unitario de venta.", "soles", "2.00"),
    columna("stock", "importante", "numero_no_neg", "Unidades en existencia.", "unidades", "48"),
    columna("fecha_vencimiento", "opcional", "fecha", "Vencimiento más próximo (dd/mm/aaaa).", "", "31/12/2027"),
    columna("largo_cm", "importante", "numero_pos", "Lado más largo de la base de UNA unidad, visto de frente.", "cm", "7"),
    columna("ancho_cm", "importante", "numero_pos", "Profundidad de UNA unidad (de adelante hacia atrás).", "cm", "7"),
    columna("alto_cm", "importante", "numero_pos", "Altura de UNA unidad parada como se exhibe.", "cm", "22"),
    columna("peso_kg", "importante", "numero_pos", "Peso de UNA unidad con su envase.", "kg", "0.55"),
    columna("unidades_por_caja", "opcional", "entero_pos", "Cuántas unidades trae la caja del proveedor.", "unidades", "12"),
    columna("largo_caja_cm", "opcional", "numero_pos", "Largo de la caja del proveedor.", "cm", "30"),
    columna("ancho_caja_cm", "opcional", "numero_pos", "Ancho de la caja del proveedor.", "cm", "22"),
    columna("alto_caja_cm", "opcional", "numero_pos", "Alto de la caja del proveedor.", "cm", "24"),
    columna("apilable", "opcional", "si_no", "¿Se puede poner una unidad encima de otra?", "", "si", SI_NO),
    columna("maximo_apilado", "opcional", "entero_pos", "Cuántas unidades como máximo una encima de otra.", "unidades", "3"),
    columna("se_puede_girar", "opcional", "si_no", "¿Se puede echar o voltear (no solo girar sobre su base)?", "", "no", SI_NO),
    columna("fragil", "opcional", "si_no", "¿Se rompe con facilidad (vidrio, cerámica)?", "", "no", SI_NO),
    columna("perecible", "opcional", "si_no", "¿Tiene fecha de vencimiento corta (alimentos, bebidas)?", "", "si", SI_NO),
    columna("peligroso", "opcional", "si_no", "¿Es inflamable, tóxico o corrosivo (lejía, thinner, aerosoles)?", "", "no", SI_NO),
    columna("valor_alto", "opcional", "si_no", "¿Debe ir en zona controlada por su precio o riesgo de robo?", "", "no", SI_NO),
    columna("temperatura_requerida", "opcional", "lista", "ambiente, refrigerado o congelado.", "", "ambiente", TEMPERATURAS),
    columna("ubicacion_actual", "opcional", "texto", "Ubicación actual si la conoce (ejemplo E1-N2-T1 = estante E1, nivel 2, tramo 1). Sirve para medir el 'antes'.", "", "E1-N2-T1"),
]

COLUMNAS_VENTAS = [
    columna("fecha_hora", "obligatoria", "fecha", "Fecha y hora de la venta (dd-mm-aaaa HH:MM).", "", "05-11-2026 10:35"),
    columna("comprobante", "obligatoria", "texto", "Número de boleta o factura. Las líneas con el mismo número son un mismo pedido.", "", "B001-000123"),
    columna("codigo_barras", "obligatoria", "texto", "Código de barras del producto vendido (igual al del catálogo).", "", "7750000000017"),
    columna("producto", "opcional", "texto", "Nombre del producto (solo para revisar).", "", "PRODUCTO DE EJEMPLO 500ML"),
    columna("cantidad", "obligatoria", "numero", "Unidades vendidas en esa línea (negativo = devolución).", "unidades", "2"),
    columna("precio_unitario", "importante", "numero_no_neg", "Precio cobrado por unidad.", "soles", "2.00"),
    columna("total", "importante", "numero", "Importe de la línea (cantidad × precio − descuento).", "soles", "4.00"),
    columna("costo", "opcional", "numero_no_neg", "Costo unitario (si su sistema lo da).", "soles", "1.20"),
]

HOJAS_LOCAL = {
    "LOCAL": [
        columna("nombre_local", "opcional", "texto", "Nombre del local.", "", "Almacén principal"),
        columna("largo_m", "obligatoria", "numero_pos", "Largo interior del local (eje X, de izquierda a derecha).", "m", "18"),
        columna("ancho_m", "obligatoria", "numero_pos", "Ancho interior del local (eje Y, de abajo hacia arriba en el plano).", "m", "12"),
        columna("altura_libre_m", "obligatoria", "numero_pos", "Altura libre útil: del piso a lo más bajo del techo (vigas, luminarias).", "m", "3.2"),
        columna("capacidad_piso_kg_m2", "opcional", "numero_pos", "Carga máxima del piso, si la conoce.", "kg/m²", "500"),
    ],
    "OBSTACULOS": [
        columna("id", "obligatoria", "texto", "Nombre corto único (C1, P1, X1...).", "", "C1"),
        columna("tipo", "obligatoria", "lista", "Tipo de elemento.", "", "columna", TIPOS_OBSTACULO),
        columna("x_m", "obligatoria", "numero_no_neg", "Distancia desde el origen (0,0) hasta la esquina izquierda-inferior, en X.", "m", "6"),
        columna("y_m", "obligatoria", "numero_no_neg", "Distancia desde el origen hasta la esquina izquierda-inferior, en Y.", "m", "4"),
        columna("largo_m", "obligatoria", "numero_pos", "Tamaño en X.", "m", "0.4"),
        columna("ancho_m", "obligatoria", "numero_pos", "Tamaño en Y.", "m", "0.4"),
        columna("alto_m", "opcional", "numero_pos", "Altura (para el 3D). Rociadores y luminarias: altura a la que están.", "m", "3.2"),
    ],
    "ZONAS": [
        columna("id", "obligatoria", "texto", "Nombre corto único.", "", "Z1"),
        columna("tipo", "obligatoria", "lista", "Uso de la zona.", "", "despacho", TIPOS_ZONA),
        columna("x_m", "obligatoria", "numero_no_neg", "Esquina izquierda-inferior en X.", "m", "0"),
        columna("y_m", "obligatoria", "numero_no_neg", "Esquina izquierda-inferior en Y.", "m", "0"),
        columna("largo_m", "obligatoria", "numero_pos", "Tamaño en X.", "m", "3"),
        columna("ancho_m", "obligatoria", "numero_pos", "Tamaño en Y.", "m", "2"),
    ],
    "ESTANTES_EXISTENTES": [
        columna("id", "obligatoria", "texto", "OPCIONAL: llene esta hoja solo si tiene estantes que quiere conservar. Nombre corto único del estante.", "", "E1"),
        columna("tipo", "obligatoria", "lista", "Tipo de mueble.", "", "estante_metalico", TIPOS_ESTANTE),
        columna("x_m", "obligatoria", "numero_no_neg", "Esquina izquierda-inferior de la huella del estante en X.", "m", "2"),
        columna("y_m", "obligatoria", "numero_no_neg", "Esquina izquierda-inferior de la huella del estante en Y.", "m", "3"),
        columna("largo_m", "obligatoria", "numero_pos", "Largo del frente del estante.", "m", "2.4"),
        columna("fondo_m", "obligatoria", "numero_pos", "Profundidad del estante.", "m", "0.5"),
        columna("alto_m", "obligatoria", "numero_pos", "Altura total del estante.", "m", "2.0"),
        columna("niveles", "obligatoria", "entero_pos", "Número de niveles (bandejas) donde se coloca mercadería.", "", "5"),
        columna("alturas_niveles_m", "opcional", "lista_niveles", "Altura libre de cada nivel separada por punto y coma, de abajo hacia arriba. Vacío = todos iguales.", "m", "0.35;0.35;0.35;0.35;0.35"),
        columna("capacidad_kg_nivel", "obligatoria", "numero_pos", "Peso máximo que soporta cada nivel (dato del fabricante).", "kg", "80"),
        columna("orientacion", "obligatoria", "lista", "Hacia dónde mira el frente: 0 = frente hacia abajo del plano (Y menor), 90 = hacia la derecha, 180 = hacia arriba, 270 = hacia la izquierda.", "grados", "180", ORIENTACIONES),
        columna("costo_soles", "opcional", "numero_no_neg", "Costo de un módulo igual (para sugerir compras).", "soles", "450"),
        columna("zona_controlada", "opcional", "si_no", "¿Está en zona vigilada (cerca de caja, con llave)? Ahí van los productos de alto valor.", "", "no", SI_NO),
        columna("permite_peligrosos", "opcional", "si_no", "¿Se pueden poner aquí inflamables o corrosivos?", "", "no", SI_NO),
    ],
    "PREFERENCIAS_Y_PRESUPUESTO": [
        columna("modo_diseno", "opcional", "lista", "A = diseñar desde cero; B = solo reutilizar mis estantes existentes; C = mixto (conservar los existentes y agregar módulos nuevos).", "", "A", MODOS_DISENO),
        columna("presupuesto_max_soles", "opcional", "numero_no_neg", "Monto máximo para comprar y montar racks. Vacío = sin tope.", "soles", "8000"),
        columna("tipos_permitidos", "opcional", "texto", "Tipos de rack que acepta, separados por punto y coma (gondola_tienda; estante_ligero; rack_selectivo; estante_archivo; cantilever). Vacío = los disponibles del catálogo.", "", "estante_ligero;gondola_tienda"),
        columna("acepta_comprar", "opcional", "si_no", "¿Acepta comprar racks nuevos? 'no' obliga al modo B.", "", "si", SI_NO),
        columna("equipo_manipulacion", "opcional", "lista", "manual (a mano o carretilla) o mecanico (transpaleta, apilador, montacargas).", "", "manual", EQUIPOS_MANIPULACION),
        columna("cobertura_total", "opcional", "si_no", "'si' = llenar todo el local con racks (propuesta de capacidad máxima, no solo para el stock actual).", "", "no", SI_NO),
        columna("cobertura_porcentaje", "opcional", "numero_no_neg", "Porcentaje del área útil a cubrir con racks si cobertura_total = si (10 a 90).", "%", "40"),
    ],
    "EQUIPOS": [
        columna("tipo", "obligatoria", "lista", "Equipo con el que se mueve la mercadería.", "", "manual", TIPOS_EQUIPO),
        columna("radio_giro_m", "opcional", "numero_no_neg", "Radio de giro del equipo.", "m", "0"),
        columna("altura_max_m", "opcional", "numero_pos", "Altura máxima que alcanza el equipo o la persona.", "m", "1.9"),
    ],
    "PASILLOS": [
        columna("uso", "obligatoria", "lista", "Uso del pasillo.", "", "peatonal", USOS_PASILLO),
        columna("ancho_min_m", "obligatoria", "numero_pos", "Ancho mínimo libre que necesita ese uso.", "m", "0.9"),
    ],
}


def definicion(tipo_plantilla):
    """Devuelve {hoja: columnas} de la plantilla pedida."""
    if tipo_plantilla == "catalogo":
        return {"DATOS": COLUMNAS_CATALOGO}
    if tipo_plantilla == "ventas":
        return {"DATOS": COLUMNAS_VENTAS}
    if tipo_plantilla == "local":
        return HOJAS_LOCAL
    raise ValueError(f"Plantilla desconocida: {tipo_plantilla}")


# --------------------------------------------------------------------------------------
# Generación
# --------------------------------------------------------------------------------------

def _color_nivel(nivel):
    return {"obligatoria": COLOR_OBLIGATORIA, "importante": COLOR_IMPORTANTE}.get(nivel, COLOR_OPCIONAL)


def _escribir_encabezados(hoja, columnas, extras=()):
    for posicion, col in enumerate(columnas, start=1):
        celda = hoja.cell(row=1, column=posicion, value=col["nombre"])
        celda.font = Font(bold=True)
        celda.fill = PatternFill("solid", fgColor=_color_nivel(col["nivel"]))
        celda.alignment = Alignment(wrap_text=True, vertical="center")
        texto = f"{col['descripcion']}"
        if col["unidad"]:
            texto += f"\nUnidad: {col['unidad']}"
        texto += f"\n({col['nivel']})"
        celda.comment = Comment(texto, "Acomoda")
        hoja.column_dimensions[get_column_letter(posicion)].width = max(14, len(col["nombre"]) + 4)
    for desplazamiento, nombre in enumerate(extras, start=len(columnas) + 1):
        celda = hoja.cell(row=1, column=desplazamiento, value=nombre)
        celda.font = Font(bold=True, italic=True)
        celda.fill = PatternFill("solid", fgColor=COLOR_INFORMATIVA)
        hoja.column_dimensions[get_column_letter(desplazamiento)].width = 18
    hoja.freeze_panes = "A2"


def _agregar_listas(libro, hoja, columnas, filas=5000):
    """Agrega listas desplegables usando una hoja oculta LISTAS."""
    if "LISTAS" not in libro.sheetnames:
        hoja_listas = libro.create_sheet("LISTAS")
        hoja_listas.sheet_state = "hidden"
    hoja_listas = libro["LISTAS"]
    for posicion, col in enumerate(columnas, start=1):
        if not col["lista"]:
            continue
        columna_lista = hoja_listas.max_column + 1 if hoja_listas.max_row > 1 or hoja_listas["A1"].value else 1
        for fila, valor in enumerate(col["lista"], start=1):
            hoja_listas.cell(row=fila, column=columna_lista, value=valor)
        letra_lista = get_column_letter(columna_lista)
        rango = f"LISTAS!${letra_lista}$1:${letra_lista}${len(col['lista'])}"
        validacion = DataValidation(type="list", formula1=rango, allow_blank=True,
                                    showErrorMessage=True, errorTitle="Valor no permitido",
                                    error=f"Elija un valor de la lista: {', '.join(col['lista'])}")
        letra = get_column_letter(posicion)
        validacion.add(f"{letra}2:{letra}{filas}")
        hoja.add_data_validation(validacion)


def _hoja_instrucciones(libro, tipo_plantilla, titulo, parrafos):
    hoja = libro.active
    hoja.title = "INSTRUCCIONES"
    hoja["A1"] = titulo
    hoja["A1"].font = Font(bold=True, size=14)
    hoja["A2"], hoja["B2"] = "version_plantilla", VERSION_PLANTILLA
    hoja["A3"], hoja["B3"] = "tipo_plantilla", tipo_plantilla
    hoja["A2"].font = hoja["A3"].font = Font(bold=True)
    fila = 5
    for parrafo in parrafos:
        hoja.cell(row=fila, column=1, value=parrafo).alignment = Alignment(wrap_text=True)
        fila += 1
    fila += 1
    hoja.cell(row=fila, column=1, value="Colores de encabezado:").font = Font(bold=True)
    leyenda = [(COLOR_OBLIGATORIA, "Obligatoria: si falta, la fila tiene error."),
               (COLOR_IMPORTANTE, "Importante: si falta, el programa la estima y baja el índice de confiabilidad."),
               (COLOR_OPCIONAL, "Opcional."),
               (COLOR_INFORMATIVA, "Informativa: el programa no la lee.")]
    for color, texto in leyenda:
        fila += 1
        hoja.cell(row=fila, column=1, value="").fill = PatternFill("solid", fgColor=color)
        hoja.cell(row=fila, column=2, value=texto)
    for nombre_hoja, columnas in definicion(tipo_plantilla).items():
        fila += 2
        hoja.cell(row=fila, column=1, value=f"Hoja {nombre_hoja}").font = Font(bold=True, size=12)
        fila += 1
        for posicion, encabezado in enumerate(["Columna", "Nivel", "Unidad", "Qué poner", "Ejemplo", "Valores permitidos"], start=1):
            hoja.cell(row=fila, column=posicion, value=encabezado).font = Font(bold=True)
        for col in columnas:
            fila += 1
            valores = [col["nombre"], col["nivel"], col["unidad"], col["descripcion"], col["ejemplo"],
                       ", ".join(col["lista"]) if col["lista"] else ""]
            for posicion, valor in enumerate(valores, start=1):
                hoja.cell(row=fila, column=posicion, value=valor).alignment = Alignment(wrap_text=True, vertical="top")
            hoja.cell(row=fila, column=1).fill = PatternFill("solid", fgColor=_color_nivel(col["nivel"]))
    hoja.column_dimensions["A"].width = 28
    hoja.column_dimensions["B"].width = 14
    hoja.column_dimensions["C"].width = 10
    hoja.column_dimensions["D"].width = 70
    hoja.column_dimensions["E"].width = 22
    hoja.column_dimensions["F"].width = 40
    return hoja


INSTRUCCIONES_CATALOGO = [
    "1. Llene una fila por producto en la hoja DATOS. No cambie los nombres de los encabezados.",
    "2. Mida UNA unidad del producto, tal como se coloca en el estante: largo = frente, ancho = fondo, alto = altura parada.",
    "3. Use centímetros (cm) para las medidas y kilogramos (kg) para el peso. Use punto o coma decimal.",
    "4. Pese con una balanza de cocina o la balanza de la tienda. Si el producto viene en caja del proveedor, mida también la caja.",
    "5. Empiece por los productos que más venden: si la plantilla vino prellenada, ya están ordenados de mayor a menor venta.",
    "6. Las columnas sí/no tienen lista desplegable. Si no sabe, déjelas vacías: el programa propondrá un valor y lo marcará como estimado.",
    "7. La hoja EJEMPLO muestra filas falsas de ejemplo. No las copie.",
    "8. Guarde el archivo y súbalo en el Paso 1 del programa.",
]

INSTRUCCIONES_VENTAS = [
    "1. Una fila por línea de comprobante (un producto dentro de una boleta o factura).",
    "2. fecha_hora con el día primero: 05-11-2026 10:35 es el 5 de noviembre de 2026.",
    "3. El código de barras debe ser el mismo que usa en el catálogo; las ventas de códigos que no están en el catálogo se descartan y se informan.",
    "4. Si su sistema exporta otro formato, no hace falta usar esta plantilla: suba el reporte tal cual y el asistente de columnas lo adaptará.",
]

INSTRUCCIONES_LOCAL = [
    "1. Elija una esquina del local como origen (0,0): recomendamos la esquina inferior izquierda del plano, mirando con la puerta principal abajo.",
    "2. El eje X va a lo largo (hacia la derecha) y el eje Y a lo ancho (hacia arriba en el plano). Todas las medidas van en METROS.",
    "3. Cada elemento se ubica por su esquina más cercana al origen (izquierda-inferior) y su tamaño en X (largo_m) y en Y (ancho_m).",
    "4. Cómo medir: use huincha o medidor láser. Mida dos veces cada distancia. Mida desde los muros terminados, no desde los zócalos.",
    "5. Altura libre útil: del piso hasta lo más bajo que haya en el techo (viga, luminaria, ducto, rociador).",
    "6. NO necesita medir estantes: el programa DISEÑA los racks. Solo si tiene estantes que quiere conservar, regístrelos en ESTANTES_EXISTENTES (huella, altura, niveles y capacidad por nivel de la etiqueta del fabricante).",
    "7. orientacion: 0 si el frente del estante mira hacia Y menor (hacia abajo del plano), 180 si mira hacia Y mayor, 90 hacia X mayor, 270 hacia X menor.",
    "8. Registre columnas, muros interiores, puertas, escaleras, tableros eléctricos, extintores, salidas de emergencia, luminarias y rociadores en OBSTACULOS.",
    "9. Registre zonas de recepción, despacho, caja, ingreso, etc. en ZONAS. El programa mide las distancias de picking desde la zona 'despacho' (o 'caja' en modo tienda).",
    "10. En PASILLOS indique el ancho mínimo que necesita cada uso (por ejemplo peatonal 0.9 m, transpaleta 1.8 m).",
    "11. En PREFERENCIAS_Y_PRESUPUESTO elija el modo de diseño (A desde cero, B reutilizar, C mixto), el presupuesto máximo y el equipo de manipulación.",
]


def _hoja_ejemplo(libro, columnas_por_hoja, filas_ejemplo):
    for nombre_hoja, columnas in columnas_por_hoja.items():
        titulo = "EJEMPLO" if nombre_hoja == "DATOS" else f"EJEMPLO_{nombre_hoja}"
        hoja = libro.create_sheet(titulo)
        _escribir_encabezados(hoja, columnas)
        for numero, fila in enumerate(filas_ejemplo.get(nombre_hoja, []), start=2):
            for posicion, col in enumerate(columnas, start=1):
                hoja.cell(row=numero, column=posicion, value=fila.get(col["nombre"]))
        hoja.sheet_properties.tabColor = "A6A6A6"


def _guardar(libro, nombre_archivo):
    salida = io.BytesIO()
    libro.save(salida)
    contenido = salida.getvalue()
    (CARPETA_PLANTILLAS / nombre_archivo).write_bytes(contenido)
    return contenido


def generar_plantilla_catalogo(catalogo=None, importancia=None, nota_orden=None):
    """Crea plantilla_catalogo.xlsx. Si se da `catalogo` (DataFrame estándar), la prellena
    con los productos y deja vacías las magnitudes que no son reales.
    `importancia` es un DataFrame con id_producto y ventas_soles para ordenar."""
    libro = Workbook()
    parrafos = list(INSTRUCCIONES_CATALOGO)
    hoja = libro.create_sheet("DATOS")
    extras = ()
    if catalogo is not None:
        extras = ("orden_medicion", "ventas_soles_referencia")
        tabla = catalogo.copy()
        if importancia is not None and len(importancia):
            tabla = tabla.merge(importancia[["id_producto", "ventas_soles"]], on="id_producto", how="left")
        if "ventas_soles" not in tabla:
            tabla["ventas_soles"] = 0.0
        tabla["ventas_soles"] = tabla["ventas_soles"].fillna(0.0)
        tabla = tabla.sort_values("ventas_soles", ascending=False).reset_index(drop=True)
        total = tabla["ventas_soles"].sum()
        if total > 0:
            acumulado = tabla["ventas_soles"].cumsum() / total
            cubrir_80 = int((acumulado.shift(fill_value=0) < 0.80).sum())
            parrafos.insert(0, f"IMPORTANTE: mida primero las {cubrir_80} primeras filas; cubren el 80 % de sus ventas en soles.")
        if nota_orden:
            parrafos.insert(0, nota_orden)
        columnas_reales = {"largo_cm", "ancho_cm", "alto_cm", "peso_kg"}
        for numero, fila in enumerate(tabla.itertuples(index=False), start=2):
            registro = fila._asdict()
            for posicion, col in enumerate(COLUMNAS_CATALOGO, start=1):
                nombre = col["nombre"]
                valor = registro.get(nombre)
                if nombre in columnas_reales and registro.get("origen_medidas") != "real":
                    valor = None
                if nombre in ("apilable", "maximo_apilado", "se_puede_girar", "fragil", "perecible",
                              "peligroso", "valor_alto", "temperatura_requerida") and registro.get("origen_atributos") != "real":
                    valor = None
                if vacio(valor):
                    valor = None
                elif isinstance(valor, float) and valor.is_integer() and nombre not in ("precio_compra", "precio_venta", "peso_kg"):
                    valor = int(valor)
                hoja.cell(row=numero, column=posicion, value=valor)
            hoja.cell(row=numero, column=len(COLUMNAS_CATALOGO) + 1, value=numero - 1)
            hoja.cell(row=numero, column=len(COLUMNAS_CATALOGO) + 2, value=round(float(registro["ventas_soles"]), 2))
    _hoja_instrucciones(libro, "catalogo", "Plantilla de CATÁLOGO con magnitudes de los productos", parrafos)
    libro.move_sheet("DATOS", offset=0)
    _escribir_encabezados(hoja, COLUMNAS_CATALOGO, extras)
    _agregar_listas(libro, hoja, COLUMNAS_CATALOGO)
    _hoja_ejemplo(libro, {"DATOS": COLUMNAS_CATALOGO}, {"DATOS": [
        {"codigo_barras": "0000000000001", "sku": "EJ-001", "producto": "BEBIDA DE EJEMPLO 500ML (NO REAL)", "categoria": "BEBIDAS",
         "precio_compra": 1.2, "precio_venta": 2.0, "stock": 48, "largo_cm": 7, "ancho_cm": 7, "alto_cm": 22, "peso_kg": 0.55,
         "unidades_por_caja": 12, "largo_caja_cm": 28, "ancho_caja_cm": 21, "alto_caja_cm": 23, "apilable": "no", "maximo_apilado": 1,
         "se_puede_girar": "no", "fragil": "no", "perecible": "si", "peligroso": "no", "valor_alto": "no", "temperatura_requerida": "ambiente"},
        {"codigo_barras": "0000000000002", "sku": "EJ-002", "producto": "OLLA DE EJEMPLO 24CM (NO REAL)", "categoria": "COCINA",
         "precio_compra": 25, "precio_venta": 39.9, "stock": 6, "largo_cm": 30, "ancho_cm": 26, "alto_cm": 16, "peso_kg": 1.4,
         "apilable": "si", "maximo_apilado": 3, "se_puede_girar": "si", "fragil": "no", "perecible": "no", "peligroso": "no",
         "valor_alto": "no", "temperatura_requerida": "ambiente"},
    ]})
    orden = ["INSTRUCCIONES", "DATOS", "EJEMPLO", "LISTAS"]
    libro._sheets = [libro[n] for n in orden if n in libro.sheetnames]
    libro.active = 0
    nombre = "plantilla_catalogo_prellenada.xlsx" if catalogo is not None else "plantilla_catalogo.xlsx"
    return _guardar(libro, nombre)


def generar_plantilla_ventas():
    libro = Workbook()
    _hoja_instrucciones(libro, "ventas", "Plantilla de REPORTE DE VENTAS", INSTRUCCIONES_VENTAS)
    hoja = libro.create_sheet("DATOS")
    _escribir_encabezados(hoja, COLUMNAS_VENTAS)
    _agregar_listas(libro, hoja, COLUMNAS_VENTAS)
    _hoja_ejemplo(libro, {"DATOS": COLUMNAS_VENTAS}, {"DATOS": [
        {"fecha_hora": "05-11-2026 10:35", "comprobante": "B000-EJEMPLO1", "codigo_barras": "0000000000001",
         "producto": "BEBIDA DE EJEMPLO 500ML (NO REAL)", "cantidad": 2, "precio_unitario": 2.0, "total": 4.0, "costo": 1.2},
        {"fecha_hora": "05-11-2026 10:35", "comprobante": "B000-EJEMPLO1", "codigo_barras": "0000000000002",
         "producto": "OLLA DE EJEMPLO 24CM (NO REAL)", "cantidad": 1, "precio_unitario": 39.9, "total": 39.9, "costo": 25},
    ]})
    return _guardar(libro, "plantilla_ventas.xlsx")


def generar_plantilla_local(local=None):
    """Crea plantilla_local.xlsx. Si se da un local (diccionario), lo vuelca en las hojas."""
    from modulos.cargar_local import local_a_tablas
    libro = Workbook()
    _hoja_instrucciones(libro, "local", "Plantilla del LOCAL (plano y medidas)", INSTRUCCIONES_LOCAL)
    tablas = local_a_tablas(local) if local else {}
    for nombre_hoja, columnas in HOJAS_LOCAL.items():
        hoja = libro.create_sheet(nombre_hoja)
        _escribir_encabezados(hoja, columnas)
        _agregar_listas(libro, hoja, columnas, filas=300)
        tabla = tablas.get(nombre_hoja)
        if tabla is not None:
            for numero, fila in enumerate(tabla.to_dict("records"), start=2):
                for posicion, col in enumerate(columnas, start=1):
                    valor = fila.get(col["nombre"])
                    hoja.cell(row=numero, column=posicion, value=None if vacio(valor) else valor)
    from modulos.cargar_local import local_de_ejemplo
    tablas_ejemplo = local_a_tablas(local_de_ejemplo())
    _hoja_ejemplo(libro, {"LOCAL": HOJAS_LOCAL["LOCAL"], "ESTANTES_EXISTENTES": HOJAS_LOCAL["ESTANTES_EXISTENTES"]},
                  {"LOCAL": tablas_ejemplo["LOCAL"].to_dict("records"),
                   "ESTANTES_EXISTENTES": tablas_ejemplo["ESTANTES_EXISTENTES"].head(3).to_dict("records")})
    hojas = ["INSTRUCCIONES"] + list(HOJAS_LOCAL) + ["EJEMPLO_LOCAL", "EJEMPLO_ESTANTES_EXISTENTES", "LISTAS"]
    libro._sheets = [libro[n] for n in hojas if n in libro.sheetnames]
    libro.active = 0
    return _guardar(libro, "plantilla_local.xlsx" if local is None else "local_actual.xlsx")


def generar_todas():
    """Genera las tres plantillas vacías en plantillas_generadas/."""
    generar_plantilla_catalogo()
    generar_plantilla_ventas()
    generar_plantilla_local()


# --------------------------------------------------------------------------------------
# Validación
# --------------------------------------------------------------------------------------

def es_plantilla(contenido):
    """True si el archivo Excel tiene las hojas INSTRUCCIONES y DATOS/LOCAL de Acomoda."""
    try:
        libro = load_workbook(io.BytesIO(contenido), read_only=True)
        nombres = libro.sheetnames
        libro.close()
        return "INSTRUCCIONES" in nombres and ("DATOS" in nombres or "LOCAL" in nombres)
    except Exception:
        return False


def _leer_version(libro):
    hoja = libro["INSTRUCCIONES"]
    version, tipo = None, None
    for fila in hoja.iter_rows(min_row=1, max_row=6, max_col=2, values_only=True):
        if fila[0] == "version_plantilla":
            version = str(fila[1])
        if fila[0] == "tipo_plantilla":
            tipo = str(fila[1])
    return version, tipo


def _validar_celda(valor, col):
    """Devuelve (valor_convertido, mensaje_error o None)."""
    if vacio(valor):
        if col["nivel"] == "obligatoria":
            return None, "es obligatoria y está vacía"
        return None, None
    tipo = col["tipo"]
    if tipo == "texto":
        texto = str(valor).strip()
        if isinstance(valor, float) and valor.is_integer():
            texto = str(int(valor))
        return texto, None
    if tipo in ("numero", "numero_pos", "numero_no_neg", "entero_pos"):
        numero = a_numero(valor)
        if numero is None:
            return None, "debe ser un número"
        if tipo == "numero_pos" and numero <= 0:
            return None, "debe ser un número mayor que 0"
        if tipo == "numero_no_neg" and numero < 0:
            return None, "debe ser un número mayor o igual que 0"
        if tipo == "entero_pos" and (numero <= 0 or not float(numero).is_integer()):
            return None, "debe ser un número entero mayor que 0"
        return numero, None
    if tipo == "si_no":
        respuesta = a_si_no(valor)
        if not respuesta:
            return None, "debe ser 'si' o 'no'"
        return respuesta, None
    if tipo == "lista":
        texto = str(valor).strip().lower()
        if isinstance(valor, float) and valor.is_integer():
            texto = str(int(valor))
        if texto not in [str(v).lower() for v in col["lista"]]:
            return None, f"debe ser uno de: {', '.join(col['lista'])}"
        return texto, None
    if tipo == "lista_niveles":
        partes = [a_numero(p) for p in str(valor).replace(",", ".").split(";") if p.strip()]
        if not partes or any(p is None or p <= 0 for p in partes):
            return None, "debe ser una lista de alturas en metros separadas por ';' (ejemplo 0.4;0.4;0.5)"
        return ";".join(str(p) for p in partes), None
    if tipo == "fecha":
        if isinstance(valor, (datetime, date)):
            return pd.Timestamp(valor), None
        fecha = pd.to_datetime(str(valor), dayfirst=True, errors="coerce")
        if pd.isna(fecha):
            return None, "debe ser una fecha (dd/mm/aaaa o dd-mm-aaaa HH:MM)"
        return fecha, None
    return valor, None


def validar_plantilla(contenido, tipo_esperado):
    """Valida una plantilla llena fila por fila y celda por celda.

    Devuelve un diccionario con:
      - 'tablas': {hoja: DataFrame con valores convertidos}
      - 'errores': lista de {hoja, fila, columna, valor, mensaje}
      - 'avisos': lista de textos
      - 'rechazada': texto si el archivo no se puede usar en absoluto
    """
    resultado = {"tablas": {}, "errores": [], "avisos": [], "rechazada": None}
    try:
        libro = load_workbook(io.BytesIO(contenido), data_only=True)
    except Exception as error:
        resultado["rechazada"] = f"No se pudo abrir el archivo como Excel (.xlsx): {error}"
        return resultado
    if "INSTRUCCIONES" not in libro.sheetnames:
        resultado["rechazada"] = "El archivo no es una plantilla de Acomoda (falta la hoja INSTRUCCIONES)."
        return resultado
    version, tipo = _leer_version(libro)
    if tipo and tipo != tipo_esperado:
        resultado["rechazada"] = f"Esta es una plantilla de '{tipo}', pero aquí se espera la plantilla de '{tipo_esperado}'."
        return resultado
    if version != VERSION_PLANTILLA:
        resultado["rechazada"] = (f"La plantilla es de una versión antigua ({version or 'sin versión'}). "
                                  f"Descargue la plantilla nueva (versión {VERSION_PLANTILLA}) y copie sus datos en ella.")
        if tipo_esperado == "local":
            resultado["rechazada"] += " " + GUIA_MIGRACION_LOCAL
        return resultado

    for nombre_hoja, columnas in definicion(tipo_esperado).items():
        if nombre_hoja not in libro.sheetnames:
            if nombre_hoja in HOJAS_OPCIONALES:
                resultado["tablas"][nombre_hoja] = pd.DataFrame(columns=["fila_excel"] + [c["nombre"] for c in columnas])
                continue
            resultado["errores"].append({"hoja": nombre_hoja, "fila": "-", "columna": "-", "valor": "",
                                         "mensaje": f"falta la hoja {nombre_hoja}"})
            continue
        hoja = libro[nombre_hoja]
        encabezados = [str(c.value).strip() if c.value is not None else "" for c in hoja[1]]
        posiciones = {}
        for col in columnas:
            if col["nombre"] in encabezados:
                posiciones[col["nombre"]] = encabezados.index(col["nombre"])
            elif col["nivel"] == "obligatoria":
                resultado["errores"].append({"hoja": nombre_hoja, "fila": 1, "columna": col["nombre"], "valor": "",
                                             "mensaje": "falta el encabezado de esta columna obligatoria"})
        registros = []
        for numero_fila, fila in enumerate(hoja.iter_rows(min_row=2, values_only=True), start=2):
            if all(vacio(v) for v in fila):
                continue
            registro = {"fila_excel": numero_fila}
            for col in columnas:
                if col["nombre"] not in posiciones:
                    registro[col["nombre"]] = None
                    continue
                indice = posiciones[col["nombre"]]
                valor = fila[indice] if indice < len(fila) else None
                convertido, mensaje = _validar_celda(valor, col)
                if mensaje:
                    resultado["errores"].append({"hoja": nombre_hoja, "fila": numero_fila, "columna": col["nombre"],
                                                 "valor": "" if valor is None else str(valor), "mensaje": mensaje})
                registro[col["nombre"]] = convertido
            registros.append(registro)
        tabla = pd.DataFrame(registros, columns=["fila_excel"] + [c["nombre"] for c in columnas])
        resultado["tablas"][nombre_hoja] = tabla

    # Regla especial del catálogo: código de barras o SKU
    if tipo_esperado == "catalogo" and "DATOS" in resultado["tablas"]:
        resultado["errores"] = [e for e in resultado["errores"]
                                if not (e["columna"] == "codigo_barras" and e["mensaje"].startswith("es obligatoria"))]
        tabla = resultado["tablas"]["DATOS"]
        for fila in tabla.itertuples():
            if vacio(fila.codigo_barras) and vacio(fila.sku):
                resultado["errores"].append({"hoja": "DATOS", "fila": fila.fila_excel, "columna": "codigo_barras",
                                             "valor": "", "mensaje": "falta el código de barras y también el SKU (llene al menos uno)"})
        if len(tabla) == 0:
            resultado["errores"].append({"hoja": "DATOS", "fila": "-", "columna": "-", "valor": "",
                                         "mensaje": "la hoja DATOS no tiene productos"})
    return resultado


def describir_error(error):
    """Texto en español con la ubicación exacta del error."""
    return f"Hoja {error['hoja']}, fila {error['fila']}, columna `{error['columna']}`: {error['mensaje']}" + (
        f" (valor leído: '{error['valor']}')" if error.get("valor") else "")


def archivo_con_errores(contenido, errores):
    """Devuelve el mismo Excel con las celdas con error pintadas de rojo y un comentario."""
    libro = load_workbook(io.BytesIO(contenido))
    for error in errores:
        if error["hoja"] not in libro.sheetnames or error["fila"] == "-":
            continue
        hoja = libro[error["hoja"]]
        encabezados = [str(c.value).strip() if c.value is not None else "" for c in hoja[1]]
        if error["columna"] in encabezados:
            columna_num = encabezados.index(error["columna"]) + 1
        else:
            columna_num = 1
        celda = hoja.cell(row=int(error["fila"]), column=columna_num)
        celda.fill = PatternFill("solid", fgColor=COLOR_ERROR)
        celda.comment = Comment(f"ERROR: {error['mensaje']}", "Acomoda")
    salida = io.BytesIO()
    libro.save(salida)
    return salida.getvalue()
