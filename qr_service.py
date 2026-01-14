import qrcode
import io
import uuid
from datetime import datetime


def generar_codigo_unico():
    """Genera un código único para el QR de coches."""
    timestamp = datetime.now().strftime('%Y%m%d')
    unique_id = uuid.uuid4().hex[:6].upper()
    return f"COC-{timestamp}-{unique_id}"


def generar_codigo_lote():
    """Genera un código único para el QR de lotes."""
    timestamp = datetime.now().strftime('%Y%m%d')
    unique_id = uuid.uuid4().hex[:6].upper()
    return f"LOT-{timestamp}-{unique_id}"


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
