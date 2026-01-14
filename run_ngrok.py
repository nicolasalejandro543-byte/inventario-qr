"""
Iniciar servidor con ngrok (túnel HTTPS público)
Ejecutar: python run_ngrok.py
"""

import os
import sys
import threading
import time

os.chdir(os.path.dirname(os.path.abspath(__file__)))

def iniciar_flask():
    from app import app
    app.run(host='127.0.0.1', port=5000, debug=False, use_reloader=False)

def main():
    from pyngrok import ngrok

    print("")
    print("=" * 50)
    print("  INVENTARIO QR - Sky Composite")
    print("  (con túnel HTTPS ngrok)")
    print("=" * 50)
    print("")
    print("  Iniciando servidor...")

    # Iniciar Flask en hilo separado
    flask_thread = threading.Thread(target=iniciar_flask, daemon=True)
    flask_thread.start()
    time.sleep(2)

    # Crear túnel ngrok
    print("  Creando túnel HTTPS...")
    tunnel = ngrok.connect(5000)
    url = tunnel.public_url

    print("")
    print("  ¡LISTO!")
    print("")
    print("  Abre esta URL en tu celular:")
    print(f"    {url}")
    print("")
    print(f"  Para el scanner:")
    print(f"    {url}/scanner")
    print("")
    print("=" * 50)
    print("  Presiona Ctrl+C para detener")
    print("=" * 50)
    print("")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n  Cerrando...")
        ngrok.kill()

if __name__ == '__main__':
    main()
