"""
Iniciar servidor con tunel HTTPS via localhost.run
Ejecutar: python run_https.py

Requiere: SSH instalado (viene por defecto en Windows 10/11)
"""

import os
import sys
import subprocess
import threading
import time
import re

os.chdir(os.path.dirname(os.path.abspath(__file__)))

def iniciar_tunel():
    """Inicia el tunel SSH a localhost.run"""
    print("  Iniciando tunel HTTPS...")
    print("  (Puede tomar unos segundos)")
    print("")

    try:
        # Ejecutar SSH tunnel
        proceso = subprocess.Popen(
            ['ssh', '-R', '80:localhost:5000', 'localhost.run', '-o', 'StrictHostKeyChecking=no'],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )

        # Leer output para obtener la URL
        for linea in proceso.stdout:
            print(f"  {linea.strip()}")
            # Buscar la URL en el output
            if 'https://' in linea and 'localhost.run' in linea:
                match = re.search(r'https://[^\s]+', linea)
                if match:
                    url = match.group()
                    print("")
                    print("=" * 50)
                    print(f"  URL HTTPS: {url}")
                    print(f"  Scanner:   {url}/scanner")
                    print("=" * 50)
                    print("")

    except FileNotFoundError:
        print("  ERROR: SSH no encontrado")
        print("  Instala OpenSSH o usa run_tunnel.py")
        return False
    except Exception as e:
        print(f"  Error: {e}")
        return False

    return True


def iniciar_servidor():
    """Inicia el servidor Flask"""
    from app import app
    app.run(host='127.0.0.1', port=5000, debug=False, threaded=True)


if __name__ == '__main__':
    print("")
    print("=" * 50)
    print("  INVENTARIO QR - Sky Composite")
    print("  (HTTPS via localhost.run)")
    print("=" * 50)
    print("")

    # Iniciar servidor en thread separado
    servidor_thread = threading.Thread(target=iniciar_servidor, daemon=True)
    servidor_thread.start()

    # Esperar a que el servidor inicie
    time.sleep(2)

    # Iniciar tunel
    iniciar_tunel()
