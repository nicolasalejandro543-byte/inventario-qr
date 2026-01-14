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

    # Fila 1
    espesor_1 = db.Column(db.String(10))
    largo_1 = db.Column(db.String(10))
    plantillas_1 = db.Column(db.Integer, default=0)
    bft_1 = db.Column(db.Float, default=0)

    # Fila 2
    espesor_2 = db.Column(db.String(10))
    largo_2 = db.Column(db.String(10))
    plantillas_2 = db.Column(db.Integer, default=0)
    bft_2 = db.Column(db.Float, default=0)

    # Fila 3
    espesor_3 = db.Column(db.String(10))
    largo_3 = db.Column(db.String(10))
    plantillas_3 = db.Column(db.Integer, default=0)
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
            p = int(plantillas) if plantillas else 0
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

    # Cantidad de coches en el lote
    cantidad_coches = db.Column(db.Integer, default=0)

    # Turno: Diurno o Nocturno
    turno = db.Column(db.String(20), default='Diurno')

    # Usuario que creó el lote
    creado_por = db.Column(db.String(100))

    # Notas adicionales
    notas = db.Column(db.Text)

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.now)

    # Relación con coches
    coches = db.relationship('Coche', secondary=lote_coches, backref='lotes')

    def calcular_total_bft(self):
        """Calcula el total de BFT sumando los BFT de todos los coches."""
        self.total_bft = sum(c.total_bft or 0 for c in self.coches)
        self.cantidad_coches = len(self.coches)
        return self.total_bft

    def to_dict(self):
        return {
            'id': self.id,
            'codigo_qr': self.codigo_qr,
            'total_bft': self.total_bft,
            'cantidad_coches': self.cantidad_coches,
            'turno': self.turno,
            'creado_por': self.creado_por,
            'notas': self.notas,
            'created_at': self.created_at.strftime('%d/%m/%Y %H:%M') if self.created_at else None,
            'coches': [{'id': c.id, 'codigo_qr': c.codigo_qr, 'total_bft': c.total_bft} for c in self.coches]
        }


def init_etapas():
    """Inicializa las etapas por defecto si no existen."""
    etapas_default = [
        {'nombre': 'Madera Verde', 'orden': 1, 'color': '#28a745', 'icono': 'tree'},
        {'nombre': 'Secado', 'orden': 2, 'color': '#ffc107', 'icono': 'sun'},
        {'nombre': 'Stock Secado', 'orden': 3, 'color': '#17a2b8', 'icono': 'archive'},
        {'nombre': 'Ingresa a Taller', 'orden': 4, 'color': '#6f42c1', 'icono': 'tools'}
    ]

    for etapa_data in etapas_default:
        if not Etapa.query.filter_by(nombre=etapa_data['nombre']).first():
            etapa = Etapa(**etapa_data)
            db.session.add(etapa)

    db.session.commit()
