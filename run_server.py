"""
Script para iniciar el servidor de Inventario QR con HTTPS
Ejecutar: python run_server.py
"""

import os
import sys
import socket

def obtener_ip_local():
    """Obtiene la IP local de la máquina."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return '127.0.0.1'


def generar_certificado_ssl():
    """Genera un certificado SSL auto-firmado si no existe."""
    cert_file = 'cert.pem'
    key_file = 'key.pem'

    if os.path.exists(cert_file) and os.path.exists(key_file):
        return cert_file, key_file

    print("  Generando certificado SSL...")

    try:
        from cryptography import x509
        from cryptography.x509.oid import NameOID
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.primitives import serialization
        import datetime

        # Generar clave privada
        key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
        )

        # Obtener IP local para el certificado
        ip_local = obtener_ip_local()

        # Crear certificado
        subject = issuer = x509.Name([
            x509.NameAttribute(NameOID.COUNTRY_NAME, "EC"),
            x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, "Ecuador"),
            x509.NameAttribute(NameOID.LOCALITY_NAME, "Local"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Sky Composite"),
            x509.NameAttribute(NameOID.COMMON_NAME, "Inventario QR"),
        ])

        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(issuer)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime.datetime.utcnow())
            .not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(days=365))
            .add_extension(
                x509.SubjectAlternativeName([
                    x509.DNSName("localhost"),
                    x509.DNSName("*.local"),
                    x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
                    x509.IPAddress(ipaddress.IPv4Address(ip_local)),
                ]),
                critical=False,
            )
            .sign(key, hashes.SHA256())
        )

        # Guardar clave privada
        with open(key_file, "wb") as f:
            f.write(key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption()
            ))

        # Guardar certificado
        with open(cert_file, "wb") as f:
            f.write(cert.public_bytes(serialization.Encoding.PEM))

        print("  Certificado SSL generado correctamente!")
        return cert_file, key_file

    except ImportError:
        # Si no tiene cryptography, usar OpenSSL via subprocess
        import subprocess

        ip_local = obtener_ip_local()

        # Crear configuración OpenSSL
        config_content = f"""
[req]
default_bits = 2048
prompt = no
default_md = sha256
distinguished_name = dn
x509_extensions = v3_req

[dn]
C = EC
ST = Ecuador
L = Local
O = Sky Composite
CN = Inventario QR

[v3_req]
subjectAltName = @alt_names

[alt_names]
DNS.1 = localhost
IP.1 = 127.0.0.1
IP.2 = {ip_local}
"""

        config_file = 'openssl.cnf'
        with open(config_file, 'w') as f:
            f.write(config_content)

        try:
            subprocess.run([
                'openssl', 'req', '-x509', '-nodes', '-days', '365',
                '-newkey', 'rsa:2048',
                '-keyout', key_file,
                '-out', cert_file,
                '-config', config_file
            ], check=True, capture_output=True)

            os.remove(config_file)
            print("  Certificado SSL generado correctamente!")
            return cert_file, key_file

        except (subprocess.CalledProcessError, FileNotFoundError):
            if os.path.exists(config_file):
                os.remove(config_file)
            return None, None


def main():
    # Cambiar al directorio del script
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    # Verificar dependencias
    try:
        from flask import Flask
        from flask_sqlalchemy import SQLAlchemy
        import qrcode
    except ImportError as e:
        print("=" * 50)
        print("ERROR: Faltan dependencias")
        print("=" * 50)
        print(f"\nError: {e}")
        print("\nPor favor ejecuta:")
        print("  pip install -r requirements.txt")
        print("")
        sys.exit(1)

    # Importar ipaddress para el certificado
    global ipaddress
    import ipaddress

    # Importar aplicación
    from app import app

    # Obtener IP
    ip_local = obtener_ip_local()
    puerto = 5000

    # Generar certificado SSL
    cert_file, key_file = generar_certificado_ssl()

    if not cert_file:
        print("")
        print("=" * 50)
        print("  ADVERTENCIA: No se pudo generar certificado SSL")
        print("  Instala 'cryptography': pip install cryptography")
        print("  O instala OpenSSL en tu sistema")
        print("=" * 50)
        print("")
        print("  Iniciando en modo HTTP (sin cámara en móvil)...")
        usar_https = False
    else:
        usar_https = True

    print("")
    print("=" * 50)
    print("  INVENTARIO QR - Sky Composite")
    print("=" * 50)
    print("")
    print("  Servidor iniciado con HTTPS!" if usar_https else "  Servidor iniciado (HTTP)")
    print("")
    print("  Acceso desde este PC:")
    print(f"    {'https' if usar_https else 'http'}://localhost:{puerto}")
    print("")
    print("  Acceso desde móvil (misma red WiFi):")
    print(f"    {'https' if usar_https else 'http'}://{ip_local}:{puerto}")
    print("")
    print("  Para escanear QR desde móvil:")
    print(f"    {'https' if usar_https else 'http'}://{ip_local}:{puerto}/scanner")
    print("")
    if usar_https:
        print("  NOTA: En el móvil aparecerá una advertencia de")
        print("  seguridad. Selecciona 'Avanzado' y luego")
        print("  'Continuar al sitio' para acceder.")
        print("")
    print("=" * 50)
    print("  Presiona Ctrl+C para detener")
    print("=" * 50)
    print("")

    # Iniciar servidor
    if usar_https:
        # Usar SSL con Flask directamente (más compatible)
        app.run(
            host='0.0.0.0',
            port=puerto,
            ssl_context=(cert_file, key_file),
            debug=False,
            threaded=True
        )
    else:
        try:
            from waitress import serve
            serve(app, host='0.0.0.0', port=puerto, threads=4)
        except ImportError:
            app.run(host='0.0.0.0', port=puerto, debug=True)


if __name__ == '__main__':
    main()
