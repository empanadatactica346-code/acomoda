"""Funciones pequeñas que usan todos los módulos: rutas, lectura de configuración,
normalización de textos y códigos, y registro del acta de confirmaciones."""

import json
import os
import re
import unicodedata
from datetime import datetime
from pathlib import Path

# Carpeta raíz del programa (la que contiene app.py)
RAIZ = Path(__file__).resolve().parent.parent
CARPETA_CONFIGURACION = RAIZ / "configuracion"
CARPETA_NORMATIVAS = RAIZ / "normativas"
# Donde se escribe (el ejecutable la fija junto a Acomoda.exe)
RAIZ_DATOS = Path(os.environ.get("ACOMODA_DATOS") or RAIZ)
CARPETA_PLANTILLAS = RAIZ_DATOS / "plantillas_generadas"
CARPETA_ENTRADA = RAIZ / "datos_entrada"
CARPETA_PROCESADOS = RAIZ_DATOS / "datos_procesados"
CARPETA_RESULTADOS = RAIZ_DATOS / "resultados"

for _carpeta in (CARPETA_PLANTILLAS, CARPETA_ENTRADA, CARPETA_PROCESADOS, CARPETA_RESULTADOS):
    _carpeta.mkdir(parents=True, exist_ok=True)


def cargar_json(ruta):
    """Lee un archivo JSON con tildes."""
    with open(ruta, encoding="utf-8") as archivo:
        return json.load(archivo)


def guardar_json(datos, ruta):
    """Guarda un diccionario como JSON legible."""
    with open(ruta, "w", encoding="utf-8") as archivo:
        json.dump(datos, archivo, ensure_ascii=False, indent=2, default=str)


def cargar_ajustes():
    return cargar_json(CARPETA_CONFIGURACION / "ajustes.json")


def cargar_normativas():
    return cargar_json(CARPETA_NORMATIVAS / "normativas.json")


def cargar_perfiles():
    return cargar_json(CARPETA_NORMATIVAS / "perfiles_rubro.json")


def sin_tildes(texto):
    """Quita tildes y pasa a mayúsculas: 'Categoría' -> 'CATEGORIA'. La Ñ se conserva."""
    if texto is None:
        return ""
    texto = str(texto).upper().replace("Ñ", "\0")
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return texto.replace("\0", "Ñ").strip()


def nombre_columna_simple(texto):
    """Convierte un encabezado en una clave comparable: 'CÓDIGO DE BARRA' -> 'CODIGODEBARRA'."""
    return re.sub(r"[^A-ZÑ0-9]", "", sin_tildes(texto))


def normalizar_codigo(valor):
    """Código de barras como texto limpio: sin espacios, comillas ni '.0' final."""
    if valor is None:
        return ""
    texto = str(valor).strip()
    if texto.lower() in ("", "nan", "none", "nat"):
        return ""
    texto = texto.replace('"', "").replace("'", "").replace(" ", "")
    texto = re.sub(r"\.0+$", "", texto)
    # Números grandes que Excel guardó en notación científica (7.75E+12)
    if re.fullmatch(r"\d+(\.\d+)?[eE]\+\d+", texto):
        texto = str(int(float(texto)))
    return texto


def a_numero(valor):
    """Convierte a número aceptando coma decimal. Devuelve None si no se puede."""
    if valor is None:
        return None
    if isinstance(valor, (int, float)):
        if valor != valor:  # NaN
            return None
        return float(valor)
    texto = str(valor).strip().replace(" ", "")
    if texto == "" or texto.lower() in ("nan", "none"):
        return None
    if texto.count(",") == 1 and texto.count(".") == 0:
        texto = texto.replace(",", ".")
    elif texto.count(",") >= 1 and texto.count(".") == 1:
        texto = texto.replace(",", "")
    try:
        return float(texto)
    except ValueError:
        return None


def a_si_no(valor):
    """Convierte respuestas variadas a 'si', 'no' o '' (vacío)."""
    texto = sin_tildes(valor).lower()
    if texto in ("si", "s", "true", "verdadero", "1", "x", "yes"):
        return "si"
    if texto in ("no", "n", "false", "falso", "0"):
        return "no"
    return ""


def vacio(valor):
    if valor is None:
        return True
    try:
        if valor != valor:  # NaN
            return True
    except Exception:
        pass
    return str(valor).strip() == "" or str(valor).strip().lower() in ("nan", "none", "nat")


def formato_soles(valor):
    return f"S/ {valor:,.2f}"


def formato_numero(valor, decimales=0):
    texto = f"{valor:,.{decimales}f}"
    # Estilo peruano: coma de miles se deja, punto decimal
    return texto


def ruta_acta():
    return CARPETA_RESULTADOS / "acta_confirmaciones.json"


def registrar_acta(paso, responsable, confirmado, detalle=None, sesion=None):
    """Agrega una entrada al acta (archivo JSON en resultados/). Devuelve la entrada."""
    entrada = {
        "fecha": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "paso": paso,
        "responsable": responsable or "(sin nombre)",
        "confirmado": confirmado,
        "detalle": detalle or {},
        "sesion": sesion or "",
    }
    ruta = ruta_acta()
    acta = cargar_json(ruta) if ruta.exists() else []
    acta.append(entrada)
    guardar_json(acta, ruta)
    return entrada


def leer_acta(sesion=None):
    """Entradas del acta; con `sesion`, solo las de ese levantamiento."""
    ruta = ruta_acta()
    acta = cargar_json(ruta) if ruta.exists() else []
    if sesion:
        acta = [e for e in acta if e.get("sesion") == sesion]
    return acta


# --------------------------------------------------------------------------------------
# Compuertas del flujo de 8 pasos
# --------------------------------------------------------------------------------------

PASOS = {
    1: "Catálogo con magnitudes",
    2: "Plano o medidas del local",
    3: "Reporte de ventas",
    4: "Normativas consideradas",
    5: "Diseñar y optimizar",
    6: "Resultados",
    7: "Evidencia",
    8: "Costeo y entregables",
}


def puede_abrir_paso(paso, confirmados):
    """Un paso solo se abre si TODOS los anteriores están confirmados."""
    return all(confirmados.get(anterior, False) for anterior in range(1, paso))


def pasos_a_invalidar(paso_cambiado):
    """Si cambia un paso, se deben volver a confirmar él y todos los siguientes."""
    return [p for p in PASOS if p >= paso_cambiado]
