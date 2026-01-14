"""
Iniciar servidor con Cloudflare Tunnel (HTTPS gratis, sin registro)
Ejecutar: python run_tunnel.py
"""

import os
os.chdir(os.path.dirname(os.path.abspath(__file__)))

from app import app
from flask_cloudflared import run_with_cloudflared

print("")
print("=" * 50)
print("  INVENTARIO QR - Sky Composite")
print("  (con túnel HTTPS Cloudflare)")
print("=" * 50)
print("")
print("  Iniciando... espera unos segundos")
print("  La URL aparecerá abajo")
print("")

run_with_cloudflared(app)
app.run(host='0.0.0.0', port=5000, debug=False)
