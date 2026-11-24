# Construir:  pyinstaller empaquetado/acomoda.spec --noconfirm   (desde la carpeta acomoda)
import os
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, copy_metadata

RAIZ = Path(SPECPATH).parent
datas, binaries, hidden = [], [], []
for paquete in ("streamlit", "pulp", "plotly", "streamlit_drawable_canvas", "ezdxf", "pymupdf", "python_calamine", "docx"):
    d, b, h = collect_all(paquete)
    datas += d; binaries += b; hidden += h
for paquete in ("streamlit", "pandas", "numpy", "pyarrow", "plotly", "pulp", "altair", "openpyxl", "pillow",
                "scipy", "matplotlib", "python-docx", "ezdxf", "pymupdf", "streamlit-drawable-canvas"):
    try:
        datas += copy_metadata(paquete)
    except Exception:
        pass
datas += [(str(RAIZ / "app.py"), "."), (str(RAIZ / "TUTORIAL.md"), "."), (str(RAIZ / "LEEME.md"), "."),
          (str(RAIZ / "modulos"), "modulos"), (str(RAIZ / "configuracion"), "configuracion"),
          (str(RAIZ / "normativas"), "normativas"), (str(RAIZ / ".streamlit"), ".streamlit")]
# Datos de prueba (catálogo/ventas reales): solo si se pide con ACOMODA_INCLUIR_PRUEBA=1
if os.environ.get("ACOMODA_INCLUIR_PRUEBA") == "1" and (RAIZ / "datos_entrada").exists():
    datas += [(str(RAIZ / "datos_entrada"), "datos_entrada")]

a = Analysis([str(RAIZ / "empaquetado" / "lanzador.py")], pathex=[str(RAIZ)], binaries=binaries, datas=datas,
             hiddenimports=hidden + ["app", "scipy.sparse.csgraph", "matplotlib.backends.backend_agg"],
             excludes=["psycopg", "pytest", "tkinter", "IPython", "jupyter", "notebook", "torch", "tensorflow"])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="Acomoda", console=True, upx=False)
coll = COLLECT(exe, a.binaries, a.datas, name="Acomoda", upx=False)
