"""Recorrido de bienvenida (primera vez que se abre), manual exportable en Word y estilo visual de Acomoda."""

import io
import re
from datetime import date

from modulos.comun import CARPETA_PROCESADOS, RAIZ

MARCA_BIENVENIDA = CARPETA_PROCESADOS / "bienvenida_vista.txt"

# Cada diapositiva: (icono, título, texto, lista de "qué hace cada botón / sección")
RECORRIDO = [
    ("📦", "Bienvenido a Acomoda",
     "Acomoda diseña los estantes de su almacén o tienda y decide **dónde poner cada producto** con un modelo de "
     "optimización. Al final le dice con cifras **si conviene hacerlo o no** y le entrega el informe gerencial y el "
     "borrador de su artículo. Este recorrido dura 1 minuto.",
     [("Todo es local", "Sus datos se quedan en esta computadora. No necesita internet."),
      ("Se guarda solo", "Puede cerrar y volver: continúa donde se quedó.")]),
    ("🧭", "La barra lateral (izquierda)",
     "Es su panel de control. Desde aquí se mueve entre los 8 pasos y configura el proyecto.",
     [("📘 Tutorial paso a paso", "Abre la guía completa dentro de la app."),
      ("🎓 Ver recorrido", "Vuelve a mostrar esta presentación."),
      ("⬇️ Manual (Word)", "Descarga el manual detallado del software para imprimir o compartir."),
      ("Responsable", "Su nombre: queda registrado en el acta de cada confirmación."),
      ("Perfil de rubro", "Precarga normas, medidas típicas y reglas de su tipo de negocio."),
      ("Modo", "Almacén = caminar menos al armar pedidos. Tienda = más margen en la zona más visible."),
      ("Botones 1 a 8", "✅ listo · ⚠️ con advertencias · ⏳ pendiente · 🔒 bloqueado hasta terminar el anterior."),
      ("Nuevo proyecto / Reiniciar", "Abre un proyecto vacío o borra el actual.")]),
    ("📥", "Pasos 1 a 3 · Sus datos",
     "Usted entrega tres cosas. Cada paso le muestra lo que entendió y le pide confirmar antes de seguir.",
     [("1. Catálogo", "Suba su lista de productos con medidas (o la plantilla). Botón «Usar el catálogo de prueba» para practicar."),
      ("2. Local", "Plantilla Excel, plano DXF, dibujo sobre una foto o el local de ejemplo. Vea el plano 2D y 3D."),
      ("3. Ventas", "Suba el reporte de su sistema de facturación; el asistente reconoce las columnas solo."),
      ("Índice de confiabilidad", "Arriba a la derecha: qué tan reales son los datos (0–100 %).")]),
    ("⚙️", "Pasos 4 y 5 · Normas y optimización",
     "Acomoda aplica las normas peruanas (pasillos, evacuación, cargas) y calcula el mejor diseño.",
     [("4. Normativas", "Semáforo de cada norma sobre su local. Confirme las que se aplicarán."),
      ("5. Propuesta rápida", "Resultado en segundos (heurística) para ver una primera idea."),
      ("5. Propuesta completa", "Modelo de optimización exacto; muestra barra de progreso."),
      ("Deslizador λ", "Equilibra recorrido contra otros objetivos.")]),
    ("📊", "Pasos 6 a 8 · Decidir y entregar",
     "Aquí está lo más importante para la gerencia: evidencia clara y entregables listos.",
     [("6. Resultados", "Vista 3D, plano, antes/después, escenarios y sensibilidad."),
      ("7. Evidencia · 🎯 Decisión", "Qué hacer, por qué, cuatro cifras clave y el veredicto con semáforo."),
      ("8. Costeo", "Inversión, ahorro y retorno, editable con sus cotizaciones."),
      ("8. Entregables", "Informe gerencial Word/Excel, borrador del artículo, lista de compra y de reubicación.")]),
    ("🚀", "¡Listo para empezar!",
     "Empiece por el **Paso 1**. Si solo quiere probar, use los datos de prueba y el local de ejemplo. "
     "Puede volver a ver este recorrido cuando quiera con **🎓 Ver recorrido**.",
     []),
]


def primera_vez():
    return not MARCA_BIENVENIDA.exists()


def marcar_vista():
    try:
        MARCA_BIENVENIDA.write_text(date.today().isoformat())
    except OSError:
        pass


# --------------------------------------------------------------------------------------
# Manual en Word
# --------------------------------------------------------------------------------------

def _texto_con_negritas(parrafo, texto):
    texto = re.sub(r"`([^`]*)`", r"\1", texto)
    texto = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", texto)
    for i, trozo in enumerate(re.split(r"\*\*(.+?)\*\*", texto)):
        if trozo:
            parrafo.add_run(trozo).bold = i % 2 == 1


def _markdown_a_docx(documento, texto):
    tabla = []

    def volcar_tabla():
        filas = [f for f in tabla if not re.match(r"^\s*\|?\s*:?-{2,}", f)]
        if filas:
            celdas = [[c.strip() for c in f.strip().strip("|").split("|")] for f in filas]
            ancho = max(len(c) for c in celdas)
            t = documento.add_table(rows=len(celdas), cols=ancho)
            t.style = "Light Grid Accent 1"
            for r, fila in enumerate(celdas):
                for c, valor in enumerate(fila):
                    _texto_con_negritas(t.cell(r, c).paragraphs[0], valor)
        tabla.clear()

    en_codigo = False
    for linea in texto.splitlines():
        if linea.strip().startswith("```"):
            en_codigo = not en_codigo
            continue
        if en_codigo:
            documento.add_paragraph(linea, style="No Spacing")
            continue
        if linea.strip().startswith("|"):
            tabla.append(linea)
            continue
        if tabla:
            volcar_tabla()
        s = linea.strip()
        if not s or s == "---":
            continue
        encabezado = re.match(r"^(#{1,4})\s+(.*)", s)
        if encabezado:
            documento.add_heading(re.sub(r"\*\*", "", encabezado.group(2)), level=min(len(encabezado.group(1)), 3))
        elif re.match(r"^[-*]\s+", s):
            _texto_con_negritas(documento.add_paragraph(style="List Bullet"), re.sub(r"^[-*]\s+", "", s))
        elif re.match(r"^\d+\.\s+", s):
            _texto_con_negritas(documento.add_paragraph(style="List Number"), re.sub(r"^\d+\.\s+", "", s))
        elif s.startswith(">"):
            p = documento.add_paragraph(style="Intense Quote")
            _texto_con_negritas(p, s.lstrip("> "))
        else:
            _texto_con_negritas(documento.add_paragraph(), s)
    if tabla:
        volcar_tabla()


def manual_docx():
    """Manual detallado: recorrido de botones y secciones + tutorial + guía técnica completa."""
    from docx import Document
    from docx.shared import Pt, RGBColor

    documento = Document()
    documento.styles["Normal"].font.name = "Calibri"
    documento.styles["Normal"].font.size = Pt(11)
    titulo = documento.add_heading("Manual de usuario de Acomoda", 0)
    titulo.runs[0].font.color.rgb = RGBColor(0x1D, 0x6F, 0x66)
    documento.add_paragraph(f"Diseño de racks y ubicación óptima de productos · Versión local · {date.today():%d/%m/%Y}")

    documento.add_heading("1. Qué hace cada botón y cada sección", 1)
    for icono, nombre, texto, elementos in RECORRIDO:
        documento.add_heading(f"{icono} {nombre}", 2)
        _texto_con_negritas(documento.add_paragraph(), texto)
        for etiqueta, explicacion in elementos:
            p = documento.add_paragraph(style="List Bullet")
            p.add_run(f"{etiqueta}: ").bold = True
            p.add_run(explicacion)

    for numero, (archivo, nombre) in enumerate((("TUTORIAL.md", "Tutorial paso a paso"),
                                                 ("LEEME.md", "Guía técnica completa")), start=2):
        ruta = RAIZ / archivo
        if ruta.exists():
            documento.add_page_break()
            documento.add_heading(f"{numero}. {nombre}", 1)
            _markdown_a_docx(documento, ruta.read_text(encoding="utf-8"))

    salida = io.BytesIO()
    documento.save(salida)
    return salida.getvalue()


# --------------------------------------------------------------------------------------
# Estilo visual
# --------------------------------------------------------------------------------------

CSS = """
<style>
:root { --ac-1:#1d6f66; --ac-2:#2a9d8f; --ac-3:#e9c46a; --ac-bg:#f6faf9; }
.stApp { background: linear-gradient(180deg, #f6faf9 0%, #ffffff 260px); }
.block-container { padding-top: 1.6rem; max-width: 1400px; }
h1, h2, h3 { letter-spacing: -0.01em; }
h1 { color: var(--ac-1); font-weight: 800; }
section[data-testid="stSidebar"] { background: linear-gradient(180deg, #12423d 0%, #1d6f66 100%); }
section[data-testid="stSidebar"] * { color: #eef7f5; }
section[data-testid="stSidebar"] input, section[data-testid="stSidebar"] [data-baseweb="select"] * { color: #12423d !important; }
section[data-testid="stSidebar"] .stButton button { background: rgba(255,255,255,.08); border: 1px solid rgba(255,255,255,.18);
  color: #fff; text-align: left; justify-content: flex-start; border-radius: 10px; transition: all .15s ease; }
section[data-testid="stSidebar"] .stButton button:hover { background: rgba(255,255,255,.2); transform: translateX(3px); }
section[data-testid="stSidebar"] .stButton button[kind="primary"] { background: var(--ac-3); color: #12423d; border: none; font-weight: 700; }
section[data-testid="stSidebar"] .stButton button[kind="primary"] * { color: #12423d; }
section[data-testid="stSidebar"] .stDownloadButton button { background: var(--ac-3); color:#12423d; border:none; border-radius:10px; }
section[data-testid="stSidebar"] .stDownloadButton button * { color:#12423d; }
section[data-testid="stSidebar"] code { background: rgba(0,0,0,.25); color: #fff; }
.stButton button, .stDownloadButton button { border-radius: 10px; transition: transform .12s ease, box-shadow .12s ease; }
.stButton button:hover, .stDownloadButton button:hover { transform: translateY(-1px); box-shadow: 0 4px 14px rgba(29,111,102,.18); }
div[data-testid="stMetric"] { background: #fff; border: 1px solid #e3eeec; border-radius: 14px; padding: 14px 16px;
  box-shadow: 0 2px 10px rgba(18,66,61,.06); }
div[data-testid="stMetricValue"] { color: var(--ac-1); font-weight: 800; }
div[data-testid="stExpander"] { border-radius: 12px; border: 1px solid #e3eeec; background:#fff; }
div[data-testid="stTabs"] button[aria-selected="true"] { color: var(--ac-1); }
.ac-progreso { display:flex; gap:6px; margin: 4px 0 18px 0; }
.ac-progreso div { flex:1; height:8px; border-radius:6px; background:#e3eeec; }
.ac-progreso div.ok { background: var(--ac-2); } .ac-progreso div.act { background: var(--ac-3); }
.ac-sub { color:#5b7470; margin-top:-10px; margin-bottom: 4px; }
.ac-tarjeta { background:#fff; border:1px solid #e3eeec; border-left: 5px solid var(--ac-2); border-radius:12px;
  padding: 10px 14px; margin: 6px 0; }
.ac-tarjeta b { color: var(--ac-1); }
.ac-icono { font-size: 54px; text-align:center; margin: 4px 0; }
.ac-puntos { text-align:center; color:#9db3af; letter-spacing: 6px; font-size: 18px; }
.ac-puntos span.act { color: var(--ac-2); }
</style>
"""


def barra_progreso(paso, confirmados, total=8):
    celdas = "".join(f'<div class="{"ok" if i in confirmados else "act" if i == paso else ""}"></div>'
                     for i in range(1, total + 1))
    return f'<div class="ac-progreso">{celdas}</div>'
