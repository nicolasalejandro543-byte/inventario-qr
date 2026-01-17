import qrcode
import io
from datetime import datetime


def _generar_codigo_consecutivo(prefijo: str, numero_secuencial: int):
    """Genera un codigo consecutivo con 4 letras + 4 numeros.
    Formato: PREFIJO-YYYYMMDD-AAAA0001, AAAA0002... AAAA9999, AAAB0001...
    Total combinaciones: 26^4 * 9999 = 4,569,760,974 codigos posibles (4.5+ mil millones)

    Args:
        prefijo: Prefijo del codigo (COC, PRO, BLQ, CON)
        numero_secuencial: Numero secuencial (1, 2, 3...)

    Returns:
        Codigo formateado: PREFIJO-YYYYMMDD-AAAA0001
    """
    timestamp = datetime.now().strftime('%Y%m%d')

    # Cada grupo de letras tiene 9999 numeros (0001-9999)
    grupo = (numero_secuencial - 1) // 9999  # Que grupo de letras (0 = AAAA, 1 = AAAB, etc.)
    numero = ((numero_secuencial - 1) % 9999) + 1  # Numero dentro del grupo (1-9999)

    # Convertir el grupo a 4 letras (AAAA, AAAB, AAAC... AAAZ, AABA, AABB... ZZZZ)
    letra1 = chr(65 + (grupo // (26 * 26 * 26)) % 26)  # Primera letra (A-Z)
    letra2 = chr(65 + (grupo // (26 * 26)) % 26)        # Segunda letra (A-Z)
    letra3 = chr(65 + (grupo // 26) % 26)               # Tercera letra (A-Z)
    letra4 = chr(65 + grupo % 26)                       # Cuarta letra (A-Z)

    letras = f"{letra1}{letra2}{letra3}{letra4}"

    return f"{prefijo}-{timestamp}-{letras}{numero:04d}"


def _extraer_numero_secuencial(codigo: str, prefijo: str):
    """Extrae el numero secuencial de un codigo existente.

    Args:
        codigo: Codigo completo (ej: COC-20260117-AAAA0001)
        prefijo: Prefijo esperado (COC, PRO, BLQ, CON)

    Returns:
        Numero secuencial o None si no coincide el formato
    """
    import re

    # Buscar formato nuevo: PREFIJO-YYYYMMDD-AAAA0001
    pattern = rf'{prefijo}-\d{{8}}-([A-Z]{{4}})(\d{{4}})'
    match = re.search(pattern, codigo)
    if match:
        letras = match.group(1)
        numero = int(match.group(2))
        # Convertir letras a grupo: AAAA=0, AAAB=1, AAAC=2... AABA=26...
        grupo = ((ord(letras[0]) - 65) * 26 * 26 * 26 +
                 (ord(letras[1]) - 65) * 26 * 26 +
                 (ord(letras[2]) - 65) * 26 +
                 (ord(letras[3]) - 65))
        return grupo * 9999 + numero

    # Buscar formato anterior con 3 letras: PREFIJO-YYYYMMDD-AAA001
    pattern_old = rf'{prefijo}-\d{{8}}-([A-Z]{{3}})(\d{{3}})'
    match_old = re.search(pattern_old, codigo)
    if match_old:
        letras = match_old.group(1)
        numero = int(match_old.group(2))
        grupo = ((ord(letras[0]) - 65) * 26 * 26 +
                 (ord(letras[1]) - 65) * 26 +
                 (ord(letras[2]) - 65))
        return grupo * 999 + numero

    return None


# ==================== COCHES ====================

def generar_codigo_coche_consecutivo(numero_secuencial: int):
    """Genera un codigo consecutivo para coches.
    Formato: COC-YYYYMMDD-AAAA0001
    """
    return _generar_codigo_consecutivo('COC', numero_secuencial)


def extraer_numero_coche(codigo: str):
    """Extrae el numero secuencial de un codigo de coche."""
    import re

    # Formato nuevo
    result = _extraer_numero_secuencial(codigo, 'COC')
    if result:
        return result

    # Formato antiguo FJA###
    match = re.search(r'FJA(\d+)', codigo)
    if match:
        return int(match.group(1))

    return None


# ==================== LOTES ====================

def generar_codigo_lote_consecutivo(numero_secuencial: int):
    """Genera un codigo consecutivo para lotes de produccion.
    Formato: PRO-YYYYMMDD-AAAA0001
    """
    return _generar_codigo_consecutivo('PRO', numero_secuencial)


def extraer_numero_lote(codigo: str):
    """Extrae el numero secuencial de un codigo de lote."""
    # Formato nuevo
    result = _extraer_numero_secuencial(codigo, 'PRO')
    if result:
        return result

    # Formato antiguo PRO-YYYYMMDD-XXXXXX (aleatorio)
    # No tiene numero secuencial, retornar None
    return None


# ==================== BLOQUES ====================

def generar_codigo_bloque_consecutivo(numero_secuencial: int):
    """Genera un codigo consecutivo para bloques.
    Formato: BLQ-YYYYMMDD-AAAA0001
    """
    return _generar_codigo_consecutivo('BLQ', numero_secuencial)


def extraer_numero_bloque(codigo: str):
    """Extrae el numero secuencial de un codigo de bloque."""
    # Formato nuevo
    result = _extraer_numero_secuencial(codigo, 'BLQ')
    if result:
        return result

    # Formato antiguo BLQ-YYYYMMDD-XXXXXX (aleatorio)
    return None


# ==================== CONTENEDORES ====================

def generar_codigo_contenedor_consecutivo(numero_secuencial: int):
    """Genera un codigo consecutivo para contenedores.
    Formato: CON-YYYYMMDD-AAAA0001
    """
    return _generar_codigo_consecutivo('CON', numero_secuencial)


def extraer_numero_contenedor(codigo: str):
    """Extrae el numero secuencial de un codigo de contenedor."""
    import re

    # Formato nuevo
    result = _extraer_numero_secuencial(codigo, 'CON')
    if result:
        return result

    # Formato antiguo SC-B-000-XX
    match = re.search(r'SC-B-000-(\d+)', codigo)
    if match:
        return int(match.group(1))

    return None


# ==================== FUNCIONES LEGACY (compatibilidad) ====================

def generar_codigo_lote():
    """DEPRECATED: Usar generar_codigo_lote_consecutivo()"""
    from datetime import datetime
    import uuid
    timestamp = datetime.now().strftime('%Y%m%d')
    unique_id = uuid.uuid4().hex[:6].upper()
    return f"PRO-{timestamp}-{unique_id}"


def generar_codigo_bloque():
    """DEPRECATED: Usar generar_codigo_bloque_consecutivo()"""
    from datetime import datetime
    import uuid
    timestamp = datetime.now().strftime('%Y%m%d')
    unique_id = uuid.uuid4().hex[:6].upper()
    return f"BLQ-{timestamp}-{unique_id}"


def generar_codigo_contenedor(numero_secuencial: int):
    """DEPRECATED: Usar generar_codigo_contenedor_consecutivo()"""
    return f"SC-B-000-{numero_secuencial:02d}"


# ==================== QR IMAGE ====================

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
