import math
from datetime import datetime
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

# Espesores disponibles (en pulgadas)
ESPESORES = ['1', '1.5', '2', '2.5', '3', '4']

# Largos disponibles (en pies)
LARGOS = ['4', '3.5', '3', '2']


class Etapa(db.Model):
    __tablename__ = 'etapas'

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(50), unique=True, nullable=False)
    orden = db.Column(db.Integer, nullable=False)
    color = db.Column(db.String(20), default='#6c757d')
    icono = db.Column(db.String(50), default='box')

    def to_dict(self):
        return {
            'id': self.id,
            'nombre': self.nombre,
            'orden': self.orden,
            'color': self.color,
            'icono': self.icono
        }


class Coche(db.Model):
    __tablename__ = 'coches'

    id = db.Column(db.Integer, primary_key=True)
    codigo_qr = db.Column(db.String(50), unique=True, nullable=False, index=True)

    # Datos generales
    registrador = db.Column(db.String(100))
    proveedor = db.Column(db.String(100))
    numero_viaje = db.Column(db.String(50))
    camara = db.Column(db.Integer)  # 1 al 15
    lote_secado = db.Column(db.String(50))  # Numero de lote de secado

    # Fila 1
    espesor_1 = db.Column(db.String(10))
    largo_1 = db.Column(db.String(10))
    plantillas_1 = db.Column(db.Float, default=0)  # Permitir decimales
    bft_1 = db.Column(db.Float, default=0)

    # Fila 2
    espesor_2 = db.Column(db.String(10))
    largo_2 = db.Column(db.String(10))
    plantillas_2 = db.Column(db.Float, default=0)  # Permitir decimales
    bft_2 = db.Column(db.Float, default=0)

    # Fila 3
    espesor_3 = db.Column(db.String(10))
    largo_3 = db.Column(db.String(10))
    plantillas_3 = db.Column(db.Float, default=0)  # Permitir decimales
    bft_3 = db.Column(db.Float, default=0)

    # Total
    total_bft = db.Column(db.Float, default=0)

    # Relaciones
    etapa_actual_id = db.Column(db.Integer, db.ForeignKey('etapas.id'), nullable=False)
    notas = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    etapa_actual = db.relationship('Etapa', backref='coches')
    movimientos = db.relationship('Movimiento', backref='coche', lazy='dynamic',
                                   order_by='desc(Movimiento.timestamp)')

    def calcular_bft(self):
        """Calcula los BFT de cada fila y el total."""
        self.bft_1 = self._calcular_bft_fila(self.largo_1, self.espesor_1, self.plantillas_1)
        self.bft_2 = self._calcular_bft_fila(self.largo_2, self.espesor_2, self.plantillas_2)
        self.bft_3 = self._calcular_bft_fila(self.largo_3, self.espesor_3, self.plantillas_3)
        self.total_bft = self.bft_1 + self.bft_2 + self.bft_3
        return self.total_bft

    def _calcular_bft_fila(self, largo, espesor, plantillas):
        """Calcula BFT: ROUNDDOWN((Largo * Espesor * Plantillas * 45) / 12, 0)"""
        if not largo or not espesor or not plantillas:
            return 0
        try:
            l = float(largo) if largo else 0
            e = float(espesor) if espesor else 0
            p = float(plantillas) if plantillas else 0  # Permitir decimales
            # Formula: floor((largo * espesor * plantillas * 45) / 12)
            return math.floor((l * e * p * 45) / 12)
        except (ValueError, TypeError):
            return 0

    def mover_a_etapa(self, nueva_etapa_id, usuario=None, notas=None):
        """Mueve el coche a una nueva etapa y registra el movimiento."""
        etapa_origen_id = self.etapa_actual_id
        self.etapa_actual_id = nueva_etapa_id
        self.updated_at = datetime.now()

        movimiento = Movimiento(
            coche_id=self.id,
            etapa_origen_id=etapa_origen_id,
            etapa_destino_id=nueva_etapa_id,
            usuario=usuario,
            notas=notas
        )
        db.session.add(movimiento)
        return movimiento

    def to_dict(self):
        return {
            'id': self.id,
            'codigo_qr': self.codigo_qr,
            'registrador': self.registrador,
            'proveedor': self.proveedor,
            'numero_viaje': self.numero_viaje,
            'camara': self.camara,
            'lote_secado': self.lote_secado,
            'espesor_1': self.espesor_1,
            'largo_1': self.largo_1,
            'plantillas_1': self.plantillas_1,
            'bft_1': self.bft_1,
            'espesor_2': self.espesor_2,
            'largo_2': self.largo_2,
            'plantillas_2': self.plantillas_2,
            'bft_2': self.bft_2,
            'espesor_3': self.espesor_3,
            'largo_3': self.largo_3,
            'plantillas_3': self.plantillas_3,
            'bft_3': self.bft_3,
            'total_bft': self.total_bft,
            'etapa_actual_id': self.etapa_actual_id,
            'etapa_actual': self.etapa_actual.to_dict() if self.etapa_actual else None,
            'notas': self.notas,
            'created_at': self.created_at.strftime('%d/%m/%Y %H:%M') if self.created_at else None,
            'updated_at': self.updated_at.strftime('%d/%m/%Y %H:%M') if self.updated_at else None
        }


class Movimiento(db.Model):
    __tablename__ = 'movimientos'

    id = db.Column(db.Integer, primary_key=True)
    coche_id = db.Column(db.Integer, db.ForeignKey('coches.id'), nullable=False)
    etapa_origen_id = db.Column(db.Integer, db.ForeignKey('etapas.id'))
    etapa_destino_id = db.Column(db.Integer, db.ForeignKey('etapas.id'), nullable=False)
    usuario = db.Column(db.String(100))
    timestamp = db.Column(db.DateTime, default=datetime.now)
    notas = db.Column(db.Text)

    etapa_origen = db.relationship('Etapa', foreign_keys=[etapa_origen_id])
    etapa_destino = db.relationship('Etapa', foreign_keys=[etapa_destino_id])

    def to_dict(self):
        return {
            'id': self.id,
            'coche_id': self.coche_id,
            'etapa_origen': self.etapa_origen.to_dict() if self.etapa_origen else None,
            'etapa_destino': self.etapa_destino.to_dict() if self.etapa_destino else None,
            'usuario': self.usuario,
            'timestamp': self.timestamp.strftime('%d/%m/%Y %H:%M') if self.timestamp else None,
            'notas': self.notas
        }


# Tabla intermedia para relación Lote-Coche
lote_coches = db.Table('lote_coches',
    db.Column('lote_id', db.Integer, db.ForeignKey('lotes.id'), primary_key=True),
    db.Column('coche_id', db.Integer, db.ForeignKey('coches.id'), primary_key=True)
)


class Lote(db.Model):
    """Modelo para agrupar múltiples coches en un solo lote para Ingreso a Taller."""
    __tablename__ = 'lotes'

    id = db.Column(db.Integer, primary_key=True)
    codigo_qr = db.Column(db.String(50), unique=True, nullable=False, index=True)

    # Total BFT del lote (suma de coches)
    total_bft = db.Column(db.Float, default=0)

    # BFT usado en produccion (plantillas + bloques)
    bft_usado = db.Column(db.Float, default=0)

    # Cantidad de coches en el lote
    cantidad_coches = db.Column(db.Integer, default=0)

    # Estado del lote: disponible, en_proceso, finalizado
    estado = db.Column(db.String(20), default='disponible')

    # Turno: Diurno o Nocturno
    turno = db.Column(db.String(20), default='Diurno')

    # Usuario que creó el lote
    creado_por = db.Column(db.String(100))

    # Notas adicionales
    notas = db.Column(db.Text)

    # Desperdicio final (cuando se finaliza)
    desperdicio_bft = db.Column(db.Float, default=0)
    desperdicio_porcentaje = db.Column(db.Float, default=0)

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.now)
    fecha_inicio_proceso = db.Column(db.DateTime)
    fecha_finalizado = db.Column(db.DateTime)

    # Relación con coches
    coches = db.relationship('Coche', secondary=lote_coches, backref='lotes')

    @property
    def bft_disponible(self):
        """BFT disponible = total - usado."""
        return (self.total_bft or 0) - (self.bft_usado or 0)

    def calcular_total_bft(self):
        """Calcula el total de BFT sumando los BFT de todos los coches."""
        self.total_bft = sum(c.total_bft or 0 for c in self.coches)
        self.cantidad_coches = len(self.coches)
        return self.total_bft

    def usar_bft(self, cantidad):
        """Registra BFT usado en produccion."""
        self.bft_usado = (self.bft_usado or 0) + cantidad
        return self.bft_disponible

    def iniciar_proceso(self):
        """Mueve el lote a estado en_proceso."""
        self.estado = 'en_proceso'
        self.fecha_inicio_proceso = datetime.now()
        return self

    def finalizar(self):
        """Finaliza el lote y calcula desperdicio."""
        self.estado = 'finalizado'
        self.fecha_finalizado = datetime.now()
        self.desperdicio_bft = self.bft_disponible
        if self.total_bft and self.total_bft > 0:
            self.desperdicio_porcentaje = (self.desperdicio_bft / self.total_bft) * 100
        return self

    def to_dict(self):
        return {
            'id': self.id,
            'codigo_qr': self.codigo_qr,
            'total_bft': self.total_bft,
            'bft_usado': self.bft_usado or 0,
            'bft_disponible': self.bft_disponible,
            'cantidad_coches': self.cantidad_coches,
            'estado': self.estado or 'disponible',
            'turno': self.turno,
            'creado_por': self.creado_por,
            'notas': self.notas,
            'desperdicio_bft': self.desperdicio_bft or 0,
            'desperdicio_porcentaje': round(self.desperdicio_porcentaje, 1) if self.desperdicio_porcentaje else 0,
            'created_at': self.created_at.strftime('%d/%m/%Y %H:%M') if self.created_at else None,
            'fecha_inicio_proceso': self.fecha_inicio_proceso.strftime('%d/%m/%Y %H:%M') if self.fecha_inicio_proceso else None,
            'fecha_finalizado': self.fecha_finalizado.strftime('%d/%m/%Y %H:%M') if self.fecha_finalizado else None,
            'coches': [{'id': c.id, 'codigo_qr': c.codigo_qr, 'total_bft': c.total_bft} for c in self.coches]
        }


# Largos disponibles para Producción (en pulgadas)
LARGOS_PRODUCCION = [25, 24, 23, 22, 21, 20, 18, 16, 15, 14, 12, 10, 8, 6]

# Opciones de calidad para producción
CALIDADES_PRODUCCION = ['R8 Estándar', 'R9 Pesada', 'R11 Liviana', 'Madera Corta']

# Mapeo de calidad a forma corta
CALIDAD_CORTA = {
    'R8 Estándar': 'R8',
    'R9 Pesada': 'R9',
    'R11 Liviana': 'R11',
    'Madera Corta': 'MC',
    # Mantener compatibilidad con valores antiguos
    'Estándar': 'R8',
    'Liviano': 'R11'
}

def get_calidad_corta(calidad):
    """Devuelve la forma corta de la calidad."""
    return CALIDAD_CORTA.get(calidad, calidad or '-')


class Bloque(db.Model):
    """Modelo para bloques de producción con código QR."""
    __tablename__ = 'bloques'

    id = db.Column(db.Integer, primary_key=True)
    codigo_qr = db.Column(db.String(50), unique=True, nullable=False, index=True)

    # Relación con lote (opcional, para tracking de producción)
    lote_id = db.Column(db.Integer, db.ForeignKey('lotes.id'), nullable=True)

    # Datos del bloque
    fecha = db.Column(db.Date, default=lambda: datetime.now().date())
    turno = db.Column(db.String(20), default='Diurno')  # Diurno / Nocturno
    calidad = db.Column(db.String(20), default='R8 Estándar')  # R8 Estándar, R9 Pesada, R11 Liviana, Madera Corta
    secuencia = db.Column(db.String(50))  # Ingreso manual

    # Dimensiones y cálculos
    largo = db.Column(db.Integer)  # En pulgadas (de la lista LARGOS_PRODUCCION)
    peso = db.Column(db.Float)  # En kg
    densidad = db.Column(db.Float)  # Calculada automáticamente
    bft = db.Column(db.Float)  # Largo * 8

    # Bloque empatado
    empatado = db.Column(db.Boolean, default=False)

    # Estado: presentado o encolado
    estado = db.Column(db.String(20), default='presentado')

    # Peso y densidad cuando se encola (para mantener historial)
    peso_encolado = db.Column(db.Float)
    densidad_encolado = db.Column(db.Float)

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)
    fecha_encolado = db.Column(db.DateTime)

    # Notas
    notas = db.Column(db.Text)

    # Relación con lote
    lote = db.relationship('Lote', backref='bloques')

    def calcular_densidad_presentado(self):
        """Calcula la densidad para bloque presentado."""
        if not self.largo or not self.peso:
            return 0
        # Fórmula: (25 x 2.54) x (49.5 x 2.54) x ((Largo+0.75) x 2.54) = volumen en cm³
        # Dividir por 1,000,000 para convertir a m³
        # Densidad = Peso / Volumen
        ancho_cm = 25 * 2.54
        alto_cm = 49.5 * 2.54
        largo_cm = (self.largo + 0.75) * 2.54
        volumen_m3 = (ancho_cm * alto_cm * largo_cm) / 1000000
        self.densidad = self.peso / volumen_m3 if volumen_m3 > 0 else 0
        return self.densidad

    def calcular_densidad_encolado(self):
        """Calcula la densidad para bloque encolado."""
        peso = self.peso_encolado or self.peso
        if not self.largo or not peso:
            return 0
        # Fórmula: (24.75 x 2.54) x (48.75 x 2.54) x ((Largo+0.75) x 2.54) = volumen en cm³
        # Dividir por 1,000,000 para convertir a m³
        # Densidad = Peso / Volumen
        ancho_cm = 24.75 * 2.54
        alto_cm = 48.75 * 2.54
        largo_cm = (self.largo + 0.75) * 2.54
        volumen_m3 = (ancho_cm * alto_cm * largo_cm) / 1000000
        self.densidad_encolado = peso / volumen_m3 if volumen_m3 > 0 else 0
        return self.densidad_encolado

    def calcular_bft(self):
        """Calcula el BFT: Largo * 8."""
        if not self.largo:
            return 0
        self.bft = self.largo * 8
        return self.bft

    def encolar(self, nuevo_peso):
        """Mueve el bloque a estado encolado con nuevo peso."""
        self.estado = 'encolado'
        self.peso_encolado = nuevo_peso
        self.fecha_encolado = datetime.now()
        self.calcular_densidad_encolado()
        return self

    def to_dict(self):
        return {
            'id': self.id,
            'codigo_qr': self.codigo_qr,
            'lote_id': self.lote_id,
            'fecha': self.fecha.strftime('%d/%m/%Y') if self.fecha else None,
            'turno': self.turno,
            'calidad': self.calidad,
            'secuencia': self.secuencia,
            'largo': self.largo,
            'peso': self.peso,
            'densidad': round(self.densidad, 4) if self.densidad else None,
            'bft': self.bft,
            'empatado': self.empatado,
            'estado': self.estado,
            'peso_encolado': self.peso_encolado,
            'densidad_encolado': round(self.densidad_encolado, 4) if self.densidad_encolado else None,
            'fecha_encolado': self.fecha_encolado.strftime('%d/%m/%Y %H:%M') if self.fecha_encolado else None,
            'created_at': self.created_at.strftime('%d/%m/%Y %H:%M') if self.created_at else None,
            'updated_at': self.updated_at.strftime('%d/%m/%Y %H:%M') if self.updated_at else None,
            'notas': self.notas
        }


class ProcesoLote(db.Model):
    """Modelo para el cálculo de madera plantillada en proceso."""
    __tablename__ = 'proceso_lotes'

    id = db.Column(db.Integer, primary_key=True)

    # Referencia al lote de origen (Ingreso a Taller)
    lote_id = db.Column(db.Integer, db.ForeignKey('lotes.id'))

    # Datos para cálculo de madera plantillada
    largo = db.Column(db.Integer)  # En pulgadas (de la lista LARGOS_PRODUCCION)
    ancho = db.Column(db.Float, default=24)  # Fijo 24 pulgadas
    alto = db.Column(db.Float)  # Ingreso manual con decimal

    # BFT calculado (con 10% reducción en alto)
    bft_calculado = db.Column(db.Float)

    # Calidad
    calidad = db.Column(db.String(20), default='R8 Estándar')  # R8 Estándar, R9 Pesada, R11 Liviana, Madera Corta

    # Usuario que procesó
    procesado_por = db.Column(db.String(100))

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.now)

    # Notas
    notas = db.Column(db.Text)

    # Relación con lote
    lote = db.relationship('Lote', backref='procesos')

    def calcular_bft(self):
        """Calcula el BFT: (Largo × Ancho × (Alto × 0.90)) / 144."""
        if not self.largo or not self.alto:
            return 0
        alto_reducido = self.alto * 0.90  # 10% de reducción
        self.bft_calculado = (self.largo * self.ancho * alto_reducido) / 144
        return self.bft_calculado

    def to_dict(self):
        return {
            'id': self.id,
            'lote_id': self.lote_id,
            'lote': self.lote.to_dict() if self.lote else None,
            'largo': self.largo,
            'ancho': self.ancho,
            'alto': self.alto,
            'bft_calculado': round(self.bft_calculado, 2) if self.bft_calculado else None,
            'calidad': self.calidad,
            'procesado_por': self.procesado_por,
            'created_at': self.created_at.strftime('%d/%m/%Y %H:%M') if self.created_at else None,
            'notas': self.notas
        }


# Largos disponibles para Contenedores/Embarque (en pulgadas)
LARGOS_CONTENEDOR = [6, 8, 10, 12, 14, 15, 16, 18, 20, 22, 23, 24, 25]


# Tabla intermedia para relación Contenedor-Bloque
contenedor_bloques = db.Table('contenedor_bloques',
    db.Column('contenedor_id', db.Integer, db.ForeignKey('contenedores.id'), primary_key=True),
    db.Column('bloque_id', db.Integer, db.ForeignKey('bloques.id'), primary_key=True)
)


class Contenedor(db.Model):
    """Modelo para contenedores de embarque de bloques encolados."""
    __tablename__ = 'contenedores'

    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(50), unique=True, nullable=False, index=True)  # SC-B-000-XX

    # Información principal
    cliente = db.Column(db.String(200))
    numero_contenedor = db.Column(db.String(100))
    fecha_carga = db.Column(db.Date)
    fecha_zarpe = db.Column(db.Date)

    # Número de tally sheet
    tally_sheet = db.Column(db.String(50))

    # Códigos de seguros (3 campos)
    seguro_1 = db.Column(db.String(100))
    seguro_2 = db.Column(db.String(100))
    seguro_3 = db.Column(db.String(100))

    # Estado: abierto, cerrado, embarcado
    estado = db.Column(db.String(20), default='abierto')

    # Totales calculados
    total_bloques = db.Column(db.Integer, default=0)
    total_bft = db.Column(db.Float, default=0)
    total_m3 = db.Column(db.Float, default=0)

    # Usuario que creó
    creado_por = db.Column(db.String(100))

    # Notas
    notas = db.Column(db.Text)

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)
    fecha_cierre = db.Column(db.DateTime)

    # Relación con bloques (solo encolados)
    bloques = db.relationship('Bloque', secondary=contenedor_bloques, backref='contenedores')

    def calcular_totales(self):
        """Calcula los totales del contenedor."""
        self.total_bloques = len(self.bloques)
        self.total_bft = sum(b.bft or 0 for b in self.bloques)
        # Volumen en m³: ((largo + 0.75) * 24.75 * 48.75 * 2.54³) / 1000000000
        self.total_m3 = sum(
            (((b.largo + 0.75) * 24.75 * 48.75 * (2.54 ** 3)) / 1000000000)
            for b in self.bloques if b.largo
        )
        return self

    def obtener_conteo_por_largo(self):
        """Obtiene el conteo de bloques agrupados por largo."""
        conteo = {}
        for largo in LARGOS_CONTENEDOR:
            conteo[largo] = {
                'cantidad': 0,
                'bft': largo * 8,
                'mm': round(largo * 25.4, 2),
                'm3': round((((largo + 0.75) * 24.75 * 48.75 * (2.54 ** 3)) / 1000000000), 4)
            }

        for bloque in self.bloques:
            if bloque.largo in conteo:
                conteo[bloque.largo]['cantidad'] += 1

        # Calcular totales por fila
        for largo in conteo:
            qty = conteo[largo]['cantidad']
            conteo[largo]['total_bft'] = qty * conteo[largo]['bft']
            conteo[largo]['total_m3'] = round(qty * conteo[largo]['m3'], 4)

        return conteo

    def cerrar(self):
        """Cierra el contenedor (no se pueden agregar más bloques)."""
        self.estado = 'cerrado'
        self.fecha_cierre = datetime.now()
        self.calcular_totales()
        return self

    def embarcar(self):
        """Marca el contenedor como embarcado."""
        self.estado = 'embarcado'
        return self

    def to_dict(self):
        return {
            'id': self.id,
            'codigo': self.codigo,
            'cliente': self.cliente,
            'numero_contenedor': self.numero_contenedor,
            'fecha_carga': self.fecha_carga.strftime('%d/%m/%Y') if self.fecha_carga else None,
            'fecha_zarpe': self.fecha_zarpe.strftime('%d/%m/%Y') if self.fecha_zarpe else None,
            'tally_sheet': self.tally_sheet,
            'seguro_1': self.seguro_1,
            'seguro_2': self.seguro_2,
            'seguro_3': self.seguro_3,
            'estado': self.estado,
            'total_bloques': self.total_bloques,
            'total_bft': self.total_bft,
            'total_m3': round(self.total_m3, 4) if self.total_m3 else 0,
            'creado_por': self.creado_por,
            'notas': self.notas,
            'created_at': self.created_at.strftime('%d/%m/%Y %H:%M') if self.created_at else None,
            'fecha_cierre': self.fecha_cierre.strftime('%d/%m/%Y %H:%M') if self.fecha_cierre else None,
            'bloques': [{'id': b.id, 'codigo_qr': b.codigo_qr, 'largo': b.largo, 'bft': b.bft} for b in self.bloques],
            'conteo_por_largo': self.obtener_conteo_por_largo()
        }


def init_etapas():
    """Inicializa las etapas por defecto si no existen."""
    etapas_default = [
        {'nombre': 'Madera Verde', 'orden': 1, 'color': '#28a745', 'icono': 'tree'},
        {'nombre': 'Secado', 'orden': 2, 'color': '#ffc107', 'icono': 'sun'},
        {'nombre': 'Stock Secado', 'orden': 3, 'color': '#17a2b8', 'icono': 'archive'},
        {'nombre': 'Ingreso a Taller', 'orden': 4, 'color': '#6f42c1', 'icono': 'tools'}
    ]

    # Renombrar etapa antigua si existe (migracion) - hacer ANTES de crear nuevas
    etapa_antigua = Etapa.query.filter_by(nombre='Ingresa a Taller').first()
    etapa_nueva = Etapa.query.filter_by(nombre='Ingreso a Taller').first()
    if etapa_antigua and not etapa_nueva:
        etapa_antigua.nombre = 'Ingreso a Taller'
        db.session.commit()

    for etapa_data in etapas_default:
        if not Etapa.query.filter_by(nombre=etapa_data['nombre']).first():
            etapa = Etapa(**etapa_data)
            db.session.add(etapa)

    db.session.commit()
