"""Lanzador de Acomoda.exe: arranca la app en esta computadora y abre el navegador. Nada sale a internet."""

import os
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

if getattr(sys, "frozen", False):
    BASE = Path(sys._MEIPASS)                    # archivos del programa (solo lectura)
    DATOS = Path(sys.executable).parent / "Acomoda_datos"   # proyectos y resultados del usuario
else:
    BASE = Path(__file__).resolve().parent.parent
    DATOS = BASE
DATOS.mkdir(parents=True, exist_ok=True)
os.environ["ACOMODA_DATOS"] = str(DATOS)
os.chdir(BASE)
sys.path.insert(0, str(BASE))

if os.environ.get("ACOMODA_ANALIZAR_IMPORTS"):  # nunca se ejecuta: le dice a PyInstaller qué incluir
    import app  # noqa: F401


def puerto_libre(preferido=8501):
    for puerto in [preferido] + list(range(8502, 8600)):
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", puerto)) != 0:
                return puerto
    return preferido


def abrir_cuando_listo(puerto):
    for _ in range(240):
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", puerto)) == 0:
                webbrowser.open(f"http://localhost:{puerto}")
                return
        time.sleep(0.25)


def main():
    puerto = puerto_libre()
    print("=" * 60)
    print("  ACOMODA se está abriendo en su navegador...")
    print(f"  Si no se abre, entre a: http://localhost:{puerto}")
    print(f"  Sus proyectos se guardan en: {DATOS}")
    print("  Para cerrar Acomoda, cierre esta ventana.")
    print("=" * 60)
    threading.Thread(target=abrir_cuando_listo, args=(puerto,), daemon=True).start()
    from streamlit.web import cli as stcli
    sys.argv = ["streamlit", "run", str(BASE / "app.py"), "--global.developmentMode=false",
                "--server.headless=true", f"--server.port={puerto}", "--server.address=127.0.0.1",
                "--browser.gatherUsageStats=false", "--server.fileWatcherType=none", "--server.runOnSave=false"]
    sys.exit(stcli.main())


if __name__ == "__main__":
    main()
