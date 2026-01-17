import qrcode
import io
import uuid
from datetime import datetime


def generar_codigo_coche_consecutivo(numero_secuencial: int):
    """Genera un código consecutivo para coches.
    Formato: FJA001, FJA002, FJA003...
    """
    return f"FJA{numero_secuencial:03d}"


def generar_codigo_lote():
    """Genera un código único para el QR de lotes/turnos de producción."""
    timestamp = datetime.now().strftime('%Y%m%d')
    unique_id = uuid.uuid4().hex[:6].upper()
    return f"PRO-{timestamp}-{unique_id}"


def generar_codigo_bloque():
    """Genera un código único para el QR de bloques de producción."""
    timestamp = datetime.now().strftime('%Y%m%d')
    unique_id = uuid.uuid4().hex[:6].upper()
    return f"BLQ-{timestamp}-{unique_id}"


def generar_codigo_contenedor(numero_secuencial: int):
    """Genera un código único para contenedores de embarque.
    Formato: SC-B-000-XX donde XX es el número secuencial.
    """
    return f"SC-B-000-{numero_secuencial:02d}"


def generar_imagen_qr(codigo: str, size: int = 10) -> bytes:
    """Genera la imagen QR como bytes PNG."""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=size,
        border=4,
    )
    qr.add_data(codigo)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")

    buffer = io.BytesIO()
    img.save(buffer, format='PNG')
    buffer.seek(0)
    return buffer.getvalue()
