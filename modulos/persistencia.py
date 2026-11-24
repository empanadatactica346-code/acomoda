"""Guarda el progreso de cada proyecto en el servidor para que recargar la página (F5, Ctrl+Shift+R) no lo borre.

Cada proyecto tiene un código que va en el enlace (…/?p=CODIGO). Mientras el usuario use ese enlace, al recargar se
recupera todo: archivos cargados, confirmaciones, diseño, evidencia y costeo. Quien tenga el enlace ve el proyecto,
por eso la app recomienda no compartirlo.

Dónde se guarda: solo en esta computadora (carpeta datos_procesados/proyectos). Nada sale a internet.
"""

import os
import pickle
import re
import secrets
import shutil
import time
import zlib
from pathlib import Path

import pandas as pd

from modulos.comun import CARPETA_PROCESADOS

CARPETA_PROYECTOS = CARPETA_PROCESADOS / "proyectos"
CARPETA_PROYECTOS.mkdir(parents=True, exist_ok=True)
DIAS_CONSERVAR = int(os.environ.get("ACOMODA_DIAS_CONSERVAR", "3650"))
_PATRON = re.compile(r"^[a-z0-9]{8,32}$")
# Objetos grandes: se guardan aparte y solo cuando cambian (así guardar no hace lenta la app)
_GRANDES = (pd.DataFrame, pd.Series)


def codigo_valido(codigo):
    return bool(codigo) and bool(_PATRON.match(str(codigo)))


def nuevo_codigo():
    return secrets.token_hex(6)


def carpeta(codigo):
    return CARPETA_PROYECTOS / codigo


def _escribir(codigo, nombre, datos):
    datos = zlib.compress(datos, 1)
    destino = carpeta(codigo)
    destino.mkdir(parents=True, exist_ok=True)
    ruta = destino / f"{nombre}.pkl"
    temporal = ruta.with_suffix(".tmp")
    temporal.write_bytes(datos)
    os.replace(temporal, ruta)  # escritura atómica: si el servidor se corta a la mitad, no queda un archivo roto


def _leer(codigo, nombre):
    ruta = carpeta(codigo) / f"{nombre}.pkl"
    datos = ruta.read_bytes() if ruta.exists() else None
    return None if datos is None else zlib.decompress(datos)


def existe(codigo):
    if not codigo_valido(codigo):
        return False
    return (carpeta(codigo) / "estado.pkl").exists()


def guardar(codigo, estado, firmas):
    """Guarda `estado` (dict). `firmas` se reutiliza entre ejecuciones para no reescribir lo grande que no cambió."""
    if not codigo_valido(codigo):
        return
    pequenos, grandes = {}, []
    for clave, valor in estado.items():
        if _es_grande(valor):
            grandes.append(clave)
            firma = (id(valor), len(valor) if hasattr(valor, "__len__") else 0)
            if firmas.get(clave) != firma:
                try:
                    _escribir(codigo, f"g_{_nombre(clave)}", pickle.dumps(_plano(valor), protocol=pickle.HIGHEST_PROTOCOL))
                    firmas[clave] = firma
                except Exception:
                    pass
        else:
            try:
                # Cada valor se guarda por separado: si uno no se puede recuperar, los demás sí
                datos = pickle.dumps(_plano(valor), protocol=pickle.HIGHEST_PROTOCOL)
                pickle.loads(datos)
                pequenos[clave] = datos
            except Exception:  # objetos que no se pueden guardar (hilos, archivos abiertos): se omiten
                pass
    pequenos["__grandes__"] = grandes
    datos = pickle.dumps(pequenos, protocol=pickle.HIGHEST_PROTOCOL)
    if firmas.get("__estado__") != hash(datos):  # no reescribir si nada cambió (ahorra tráfico a la base)
        _escribir(codigo, "estado", datos)
        firmas["__estado__"] = hash(datos)


def cargar(codigo):
    """Devuelve el dict guardado, o None si no existe o está dañado."""
    if not existe(codigo):
        return None
    try:
        estado = pickle.loads(_leer(codigo, "estado"))
    except Exception:
        return None
    grandes = estado.pop("__grandes__", [])
    recuperado = {}
    for clave, datos in estado.items():
        try:
            recuperado[clave] = pickle.loads(datos)
        except Exception:
            pass
    for clave in grandes:
        try:
            recuperado[clave] = pickle.loads(_leer(codigo, f"g_{_nombre(clave)}"))
        except Exception:
            pass
    return recuperado


def borrar(codigo):
    if not codigo_valido(codigo):
        return
    shutil.rmtree(carpeta(codigo), ignore_errors=True)


def limpiar_antiguos():
    """Borra proyectos que nadie abrió en DIAS_CONSERVAR días (para no llenar el disco o la base)."""
    limite = time.time() - DIAS_CONSERVAR * 86400
    for proyecto in CARPETA_PROYECTOS.iterdir():
        try:
            if proyecto.is_dir() and (proyecto / "estado.pkl").stat().st_mtime < limite:
                shutil.rmtree(proyecto, ignore_errors=True)
        except OSError:
            pass


def donde_se_guarda():
    return f"carpeta {CARPETA_PROYECTOS}"


def _es_grande(valor):
    if isinstance(valor, _GRANDES) or hasattr(valor, "to_plotly_json"):
        return True
    if isinstance(valor, (bytes, bytearray)):
        return len(valor) > 200_000
    if type(valor) is dict and valor:
        return any(isinstance(v, _GRANDES + (bytes, bytearray)) or hasattr(v, "to_plotly_json")
                   for v in list(valor.values())[:50])
    return False


def _plano(valor):
    """Los estados de widgets de Streamlit son dict de solo lectura que no se pueden volver a cargar: se copian como dict."""
    if isinstance(valor, dict) and type(valor) is not dict:
        return {k: _plano(v) for k, v in valor.items()}
    return valor


def _nombre(clave):
    return re.sub(r"[^A-Za-z0-9_]", "_", str(clave))[:80]


def _ruta_ultimo():
    return CARPETA_PROYECTOS / "ultimo.txt"


def recordar_ultimo(codigo):
    """En la versión local, al volver a abrir Acomoda se continúa el último proyecto."""
    try:
        if codigo_valido(codigo) and (not _ruta_ultimo().exists() or _ruta_ultimo().read_text().strip() != codigo):
            _ruta_ultimo().write_text(codigo)
    except OSError:
        pass


def ultimo():
    try:
        codigo = _ruta_ultimo().read_text().strip()
        return codigo if existe(codigo) else None
    except OSError:
        return None
