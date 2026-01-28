import os
import re
from datetime import datetime
from functools import wraps
from flask import Flask, render_template, request, jsonify, send_file, redirect, url_for, session
from models import db, Etapa, Coche, Movimiento, Lote, Bloque, ProcesoLote, Contenedor, contenedor_bloques, lote_coches, init_etapas, ESPESORES, LARGOS, LARGOS_PRODUCCION, LARGOS_CONTENEDOR
from qr_service import (
    generar_codigo_coche_consecutivo, extraer_numero_coche,
    generar_codigo_lote_consecutivo, extraer_numero_lote,
    generar_codigo_bloque_consecutivo, extraer_numero_bloque,
    generar_codigo_contenedor_consecutivo, extraer_numero_contenedor,
    generar_imagen_qr
)
from config import get_config
import io

# Credenciales de acceso (pueden configurarse via variables de entorno)
ADMIN_USERNAME = os.environ.get('ADMIN_USERNAME', 'admin')
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'skycomposite2024')
EDIT_LOTE_PASSWORD = os.environ.get('EDIT_LOTE_PASSWORD', 'admin1208')
RESET_DB_PASSWORD = os.environ.get('RESET_DB_PASSWORD', 'resetdb2024')

app = Flask(__name__)

# Configuracion desde config.py (soporta SQLite local y PostgreSQL en Railway)
app.config.from_object(get_config())

# Inicializar base de datos
db.init_app(app)

with app.app_context():
    db.create_all()
    init_etapas()

    # Migración: agregar columna calidad a proceso_lotes si no existe
    try:
        from sqlalchemy import inspect, text
        inspector = inspect(db.engine)
        columns = [col['name'] for col in inspector.get_columns('proceso_lotes')]
        if 'calidad' not in columns:
            db.session.execute(text("ALTER TABLE proceso_lotes ADD COLUMN calidad VARCHAR(20) DEFAULT 'R8 Estándar'"))
            db.session.commit()
            print("Migración: columna 'calidad' agregada a proceso_lotes")
    except Exception as e:
        print(f"Migración calidad: {e}")


# ==================== AUTENTICACION ====================

def login_required(f):
    """Decorador para proteger rutas que requieren autenticacion."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function


@app.route('/login', methods=['GET', 'POST'])
def login():
    """Pagina de login."""
    error = None
    if request.method == 'POST':
        username = request.form.get('username', '')
        password = request.form.get('password', '')

        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session['logged_in'] = True
            session['username'] = username
            return redirect(url_for('dashboard'))
        else:
            error = 'Usuario o contraseña incorrectos'

    return render_template('login.html', error=error)


@app.route('/logout')
def logout():
    """Cerrar sesion."""
    session.clear()
    return redirect(url_for('login'))


# ==================== RUTAS WEB ====================

@app.route('/etapa/<int:etapa_id>')
@login_required
def ver_etapa(etapa_id):
    """Ver coches de una etapa específica."""
    etapa = Etapa.query.get_or_404(etapa_id)
    coches = Coche.query.filter_by(etapa_actual_id=etapa_id).order_by(Coche.created_at.desc()).all()

    # Si es Ingreso a Taller (orden 4), filtrar coches que estan en lotes en_proceso o finalizado
    lotes = []
    if etapa.orden == 4:
        # Solo mostrar lotes disponibles (no en_proceso ni finalizado)
        lotes = Lote.query.filter(
            (Lote.estado == 'disponible') | (Lote.estado == None)
        ).order_by(Lote.created_at.desc()).all()

        # Obtener IDs de coches que estan en lotes en_proceso o finalizado
        lotes_en_uso = Lote.query.filter(
            Lote.estado.in_(['en_proceso', 'finalizado'])
        ).all()
        coches_en_uso_ids = set()
        for lote in lotes_en_uso:
            for coche in lote.coches:
                coches_en_uso_ids.add(coche.id)

        # Filtrar coches que NO estan en lotes en uso
        coches = [c for c in coches if c.id not in coches_en_uso_ids]

    total_bft = sum(c.total_bft or 0 for c in coches)

    # Si es Secado (orden 2), agrupar por cámara y lote_secado
    coches_por_camara = {}
    if etapa.orden == 2:
        for coche in coches:
            camara = coche.camara or 0  # 0 para coches sin cámara asignada
            lote_sec = coche.lote_secado or 'Sin Lote'
            if camara not in coches_por_camara:
                coches_por_camara[camara] = {
                    'coches': [],
                    'total_bft': 0,
                    'count': 0,
                    'lotes_secado': {}
                }
            coches_por_camara[camara]['coches'].append(coche)
            coches_por_camara[camara]['total_bft'] += coche.total_bft or 0
            coches_por_camara[camara]['count'] += 1
            # Agrupar por lote_secado
            if lote_sec not in coches_por_camara[camara]['lotes_secado']:
                coches_por_camara[camara]['lotes_secado'][lote_sec] = {
                    'coches': [],
                    'total_bft': 0,
                    'count': 0
                }
            coches_por_camara[camara]['lotes_secado'][lote_sec]['coches'].append(coche)
            coches_por_camara[camara]['lotes_secado'][lote_sec]['total_bft'] += coche.total_bft or 0
            coches_por_camara[camara]['lotes_secado'][lote_sec]['count'] += 1
        # Ordenar por número de cámara
        coches_por_camara = dict(sorted(coches_por_camara.items()))

    return render_template('etapa.html',
                          etapa=etapa,
                          coches=coches,
                          total_bft=total_bft,
                          coches_por_camara=coches_por_camara,
                          lotes=lotes)


@app.route('/scanner')
@login_required
def scanner():
    """Página del scanner QR para móviles."""
    etapas = Etapa.query.order_by(Etapa.orden).all()
    return render_template('scanner.html', etapas=etapas)


@app.route('/recepcion')
@login_required
def recepcion_madera():
    """Página de Recepción de Madera Verde."""
    return render_template('recepcion_madera.html')


@app.route('/')
@login_required
def dashboard():
    """Dashboard principal - Resumen con Inventario y Produccion."""
    etapas = Etapa.query.order_by(Etapa.orden).all()

    # Obtener IDs de coches que estan en lotes en_proceso o finalizado (para filtrar en Ingreso a Taller)
    lotes_en_uso = Lote.query.filter(
        Lote.estado.in_(['en_proceso', 'finalizado'])
    ).all()
    coches_en_lotes_usados_ids = set()
    for lote in lotes_en_uso:
        for coche in lote.coches:
            coches_en_lotes_usados_ids.add(coche.id)

    # Obtener estadísticas por etapa
    stats_por_etapa = {}
    for etapa in etapas:
        coches = Coche.query.filter_by(etapa_actual_id=etapa.id).all()

        # Si es Ingreso a Taller (orden 4), filtrar coches que estan en lotes en uso
        if etapa.orden == 4:
            coches = [c for c in coches if c.id not in coches_en_lotes_usados_ids]

        total_coches = len(coches)
        total_bft = sum(c.total_bft or 0 for c in coches)
        stats_por_etapa[etapa.id] = {
            'total_coches': total_coches,
            'total_bft': total_bft,
            'coches': coches
        }

    # Crear lista unificada de actividades recientes
    actividades = []

    # 1. Movimientos de coches
    movimientos_coches = Movimiento.query.order_by(Movimiento.timestamp.desc()).limit(15).all()
    for mov in movimientos_coches:
        actividades.append({
            'tipo': 'coche',
            'timestamp': mov.timestamp,
            'codigo': mov.coche.codigo_qr if mov.coche else 'N/A',
            'id': mov.coche_id,
            'origen': mov.etapa_origen.nombre if mov.etapa_origen else 'Nuevo',
            'origen_color': mov.etapa_origen.color if mov.etapa_origen else '#6c757d',
            'destino': mov.etapa_destino.nombre if mov.etapa_destino else '',
            'destino_color': mov.etapa_destino.color if mov.etapa_destino else '#6c757d'
        })

    # 2. Bloques encolados recientemente
    bloques_encolados_recientes = Bloque.query.filter(Bloque.fecha_encolado.isnot(None)).order_by(Bloque.fecha_encolado.desc()).limit(10).all()
    for bloque in bloques_encolados_recientes:
        actividades.append({
            'tipo': 'bloque_encolado',
            'timestamp': bloque.fecha_encolado,
            'codigo': bloque.codigo_qr,
            'id': bloque.id,
            'origen': 'Presentado',
            'origen_color': '#f59e0b',
            'destino': 'Encolado',
            'destino_color': '#10b981'
        })

    # 3. Bloques creados recientemente
    bloques_nuevos = Bloque.query.order_by(Bloque.created_at.desc()).limit(10).all()
    for bloque in bloques_nuevos:
        actividades.append({
            'tipo': 'bloque_nuevo',
            'timestamp': bloque.created_at,
            'codigo': bloque.codigo_qr,
            'id': bloque.id,
            'origen': 'Nuevo',
            'origen_color': '#6c757d',
            'destino': 'Presentado',
            'destino_color': '#f59e0b'
        })

    # 4. Lotes finalizados
    lotes_finalizados_recientes = Lote.query.filter(Lote.fecha_finalizado.isnot(None)).order_by(Lote.fecha_finalizado.desc()).limit(10).all()
    for lote in lotes_finalizados_recientes:
        actividades.append({
            'tipo': 'lote_finalizado',
            'timestamp': lote.fecha_finalizado,
            'codigo': lote.codigo_qr,
            'id': lote.id,
            'origen': 'En Proceso',
            'origen_color': '#e83e8c',
            'destino': 'Finalizado',
            'destino_color': '#20c997'
        })

    # Ordenar todas las actividades por timestamp descendente y tomar las primeras 15
    actividades.sort(key=lambda x: x['timestamp'] if x['timestamp'] else datetime.min, reverse=True)
    ultimas_actividades = actividades[:15]

    # Lotes por estado
    lotes_en_proceso = Lote.query.filter_by(estado='en_proceso').order_by(Lote.fecha_inicio_proceso.desc()).all()
    lotes_finalizados = Lote.query.filter_by(estado='finalizado').order_by(Lote.fecha_finalizado.desc()).all()

    # Bloques
    bloques_presentados = Bloque.query.filter_by(estado='presentado').order_by(Bloque.created_at.desc()).all()
    bloques_encolados = Bloque.query.filter_by(estado='encolado').order_by(Bloque.fecha_encolado.desc()).all()

    # Contenedores
    contenedores_abiertos = Contenedor.query.filter_by(estado='abierto').all()
    contenedores_total = Contenedor.query.count()

    # Filtrar etapas para no mostrar "Ingreso a Taller" (orden=4)
    etapas_visibles = [e for e in etapas if e.orden != 4]

    return render_template('dashboard.html',
                          etapas=etapas_visibles,
                          stats_por_etapa=stats_por_etapa,
                          ultimas_actividades=ultimas_actividades,
                          lotes_en_proceso=lotes_en_proceso,
                          lotes_finalizados=lotes_finalizados,
                          bloques_presentados=bloques_presentados,
                          bloques_encolados=bloques_encolados,
                          contenedores_abiertos=contenedores_abiertos,
                          contenedores_total=contenedores_total,
                          largos_produccion=LARGOS_PRODUCCION)


@app.route('/api/dashboard/stats')
@login_required
def dashboard_stats_api():
    """API para obtener estadísticas del dashboard filtradas por fecha."""
    from datetime import datetime, timedelta

    fecha_desde = request.args.get('desde')
    fecha_hasta = request.args.get('hasta')

    # Parsear fechas
    desde = None
    hasta = None
    if fecha_desde:
        try:
            desde = datetime.strptime(fecha_desde, '%Y-%m-%d')
        except:
            pass
    if fecha_hasta:
        try:
            hasta = datetime.strptime(fecha_hasta, '%Y-%m-%d')
            # Incluir todo el día hasta
            hasta = hasta + timedelta(days=1)
        except:
            pass

    etapas = Etapa.query.order_by(Etapa.orden).all()

    # Stats por etapa (filtrar por fecha de creación del coche)
    lotes_en_uso = Lote.query.filter(
        Lote.estado.in_(['en_proceso', 'finalizado'])
    ).all()
    coches_en_lotes_usados_ids = set()
    for lote in lotes_en_uso:
        for coche in lote.coches:
            coches_en_lotes_usados_ids.add(coche.id)

    stats_por_etapa = {}
    for etapa in etapas:
        query = Coche.query.filter_by(etapa_actual_id=etapa.id)
        if desde:
            query = query.filter(Coche.created_at >= desde)
        if hasta:
            query = query.filter(Coche.created_at < hasta)
        coches = query.all()

        if etapa.orden == 4:
            coches = [c for c in coches if c.id not in coches_en_lotes_usados_ids]

        total_coches = len(coches)
        total_bft = sum(c.total_bft or 0 for c in coches)
        stats_por_etapa[etapa.id] = {
            'total_coches': total_coches,
            'total_bft': round(total_bft, 1)
        }

    # Lotes en proceso
    query_en_proceso = Lote.query.filter_by(estado='en_proceso')
    if desde:
        query_en_proceso = query_en_proceso.filter(Lote.fecha_inicio_proceso >= desde)
    if hasta:
        query_en_proceso = query_en_proceso.filter(Lote.fecha_inicio_proceso < hasta)
    lotes_en_proceso = query_en_proceso.all()
    lotes_en_proceso_count = len(lotes_en_proceso)
    lotes_en_proceso_bft = sum(l.bft_disponible or 0 for l in lotes_en_proceso)

    # Lotes finalizados
    query_finalizados = Lote.query.filter_by(estado='finalizado')
    if desde:
        query_finalizados = query_finalizados.filter(Lote.fecha_finalizado >= desde)
    if hasta:
        query_finalizados = query_finalizados.filter(Lote.fecha_finalizado < hasta)
    lotes_finalizados = query_finalizados.all()
    lotes_finalizados_count = len(lotes_finalizados)
    lotes_finalizados_bft = sum(l.bft_usado or 0 for l in lotes_finalizados)

    # Bloques presentados
    query_presentados = Bloque.query.filter_by(estado='presentado')
    if desde:
        query_presentados = query_presentados.filter(Bloque.created_at >= desde)
    if hasta:
        query_presentados = query_presentados.filter(Bloque.created_at < hasta)
    bloques_presentados = query_presentados.all()
    bloques_presentados_count = len(bloques_presentados)
    bloques_presentados_bft = sum(b.bft or 0 for b in bloques_presentados)

    # Bloques encolados
    query_encolados = Bloque.query.filter_by(estado='encolado')
    if desde:
        query_encolados = query_encolados.filter(Bloque.fecha_encolado >= desde)
    if hasta:
        query_encolados = query_encolados.filter(Bloque.fecha_encolado < hasta)
    bloques_encolados = query_encolados.all()
    bloques_encolados_count = len(bloques_encolados)
    bloques_encolados_bft = sum(b.bft or 0 for b in bloques_encolados)

    # Contenedores
    query_contenedores_abiertos = Contenedor.query.filter_by(estado='abierto')
    if desde:
        query_contenedores_abiertos = query_contenedores_abiertos.filter(Contenedor.created_at >= desde)
    if hasta:
        query_contenedores_abiertos = query_contenedores_abiertos.filter(Contenedor.created_at < hasta)
    contenedores_abiertos_count = query_contenedores_abiertos.count()

    query_contenedores_total = Contenedor.query
    if desde:
        query_contenedores_total = query_contenedores_total.filter(Contenedor.created_at >= desde)
    if hasta:
        query_contenedores_total = query_contenedores_total.filter(Contenedor.created_at < hasta)
    contenedores_total = query_contenedores_total.count()

    return jsonify({
        'stats_por_etapa': stats_por_etapa,
        'produccion': {
            'count': lotes_en_proceso_count,
            'bft': round(lotes_en_proceso_bft, 1)
        },
        'finalizados': {
            'count': lotes_finalizados_count,
            'bft': round(lotes_finalizados_bft, 1)
        },
        'bloques_presentados': {
            'count': bloques_presentados_count,
            'bft': round(bloques_presentados_bft, 1)
        },
        'bloques_encolados': {
            'count': bloques_encolados_count,
            'bft': round(bloques_encolados_bft, 1)
        },
        'contenedores': {
            'abiertos': contenedores_abiertos_count,
            'total': contenedores_total
        }
    })


@app.route('/nuevo')
@login_required
def nuevo_coche_form():
    """Formulario para crear nuevo coche."""
    etapas = Etapa.query.order_by(Etapa.orden).all()
    espesores = ESPESORES
    largos = LARGOS
    return render_template('nuevo_coche.html', etapas=etapas, espesores=espesores, largos=largos)


@app.route('/produccion')
@login_required
def produccion():
    """Vista de producción - seleccionar lote disponible para procesar."""
    # Lotes disponibles en Ingreso a Taller (estado disponible o sin estado)
    lotes_disponibles = Lote.query.filter(
        (Lote.estado == 'disponible') | (Lote.estado == None)
    ).order_by(Lote.created_at.desc()).all()

    # Lotes en proceso
    lotes_en_proceso = Lote.query.filter_by(estado='en_proceso').order_by(Lote.fecha_inicio_proceso.desc()).all()

    # Coches disponibles en Stock Secado (etapa orden=3) sin lote asignado
    etapa_stock_secado = Etapa.query.filter_by(orden=3).first()
    if etapa_stock_secado:
        # Filtrar coches que NO estan en ningun lote
        coches_stock_secado = Coche.query.filter_by(etapa_actual_id=etapa_stock_secado.id).filter(
            ~Coche.id.in_(db.session.query(lote_coches.c.coche_id))
        ).order_by(Coche.codigo_qr).all()
    else:
        coches_stock_secado = []

    return render_template('produccion.html',
                          lotes_disponibles=lotes_disponibles,
                          lotes_en_proceso=lotes_en_proceso,
                          coches_stock_secado=coches_stock_secado,
                          largos_produccion=LARGOS_PRODUCCION)


@app.route('/produccion/<int:lote_id>')
@login_required
def produccion_lote(lote_id):
    """Vista de trabajo de un lote en producción."""
    lote = Lote.query.get_or_404(lote_id)

    # Si el lote aún está disponible, iniciarlo
    if lote.estado == 'disponible' or lote.estado is None:
        lote.iniciar_proceso()
        db.session.commit()

    # Obtener coches disponibles en Stock Secado (etapa orden=3) para agregar al lote
    etapa_stock_secado = Etapa.query.filter_by(orden=3).first()
    if etapa_stock_secado:
        # Filtrar coches que NO estan en ningun lote
        coches_disponibles = Coche.query.filter_by(etapa_actual_id=etapa_stock_secado.id).filter(
            ~Coche.id.in_(db.session.query(lote_coches.c.coche_id))
        ).order_by(Coche.codigo_qr).all()
    else:
        coches_disponibles = []

    # Obtener bloques ya guardados del lote
    bloques_guardados = Bloque.query.filter_by(lote_id=lote_id).order_by(Bloque.created_at.desc()).all()

    # Obtener plantillas (procesos) ya guardadas del lote
    plantillas_guardadas = ProcesoLote.query.filter_by(lote_id=lote_id).order_by(ProcesoLote.created_at.desc()).all()

    return render_template('produccion_lote.html',
                          lote=lote,
                          largos_produccion=LARGOS_PRODUCCION,
                          coches_disponibles=coches_disponibles,
                          bloques_guardados=bloques_guardados,
                          plantillas_guardadas=plantillas_guardadas)


@app.route('/finalizados')
@login_required
def lotes_finalizados():
    """Vista de lotes finalizados."""
    lotes = Lote.query.filter_by(estado='finalizado').order_by(Lote.fecha_finalizado.desc()).all()
    return render_template('finalizados.html', lotes=lotes)


@app.route('/finalizado/<int:lote_id>')
@login_required
def detalle_lote_finalizado(lote_id):
    """Vista de detalle de un lote finalizado."""
    lote = Lote.query.get_or_404(lote_id)
    if lote.estado != 'finalizado':
        return redirect('/finalizados')
    return render_template('detalle_lote_finalizado.html', lote=lote, now=datetime.now())


@app.route('/bloques/presentados')
@login_required
def bloques_presentados():
    """Vista de bloques presentados con filtros, agrupados por calidad."""
    bloques = Bloque.query.filter_by(estado='presentado').order_by(Bloque.created_at.desc()).all()

    # Agrupar bloques por calidad
    bloques_por_calidad = {}
    orden_calidades = ['R8 Estándar', 'R9 Pesada', 'R11 Liviana', 'Madera Corta']
    calidad_corta = {
        'R8 Estándar': 'R8', 'R9 Pesada': 'R9', 'R11 Liviana': 'R11', 'Madera Corta': 'MC',
        'Estándar': 'R8', 'Estandar': 'R8', 'Liviano': 'R11'
    }

    for bloque in bloques:
        cal = bloque.calidad or 'Sin Calidad'
        if cal not in bloques_por_calidad:
            bloques_por_calidad[cal] = {
                'bloques': [],
                'count': 0,
                'total_bft': 0,
                'calidad_corta': calidad_corta.get(cal, cal)
            }
        bloques_por_calidad[cal]['bloques'].append(bloque)
        bloques_por_calidad[cal]['count'] += 1
        bloques_por_calidad[cal]['total_bft'] += bloque.bft or 0

    # Ordenar calidades según el orden definido
    bloques_por_calidad_ordenado = {}
    for cal in orden_calidades:
        if cal in bloques_por_calidad:
            bloques_por_calidad_ordenado[cal] = bloques_por_calidad[cal]
    # Agregar calidades no contempladas al final
    for cal in bloques_por_calidad:
        if cal not in bloques_por_calidad_ordenado:
            bloques_por_calidad_ordenado[cal] = bloques_por_calidad[cal]

    # Obtener valores únicos para filtros
    secuencias_raw = list(set(b.secuencia for b in bloques if b.secuencia))
    try:
        secuencias = sorted(secuencias_raw, key=lambda x: int(x) if x.isdigit() else x, reverse=True)
    except:
        secuencias = sorted(secuencias_raw, reverse=True)
    turnos = list(set(b.turno for b in bloques if b.turno))
    calidades = list(set(b.calidad for b in bloques if b.calidad))
    largos = sorted(LARGOS_PRODUCCION, reverse=True)

    return render_template('bloques_presentados.html',
                          bloques=bloques,
                          bloques_por_calidad=bloques_por_calidad_ordenado,
                          secuencias=secuencias,
                          turnos=turnos,
                          calidades=calidades,
                          largos=largos,
                          largos_produccion=LARGOS_PRODUCCION)


@app.route('/bloques/encolados')
@login_required
def bloques_encolados():
    """Vista de bloques encolados con filtros, agrupados por calidad."""
    bloques_todos = Bloque.query.filter_by(estado='encolado').order_by(Bloque.fecha_encolado.desc()).all()
    # Filtrar bloques que no estan asignados a ningun contenedor
    bloques = [b for b in bloques_todos if len(b.contenedores) == 0]

    # Agrupar bloques por calidad
    bloques_por_calidad = {}
    orden_calidades = ['R8 Estándar', 'R9 Pesada', 'R11 Liviana', 'Madera Corta']
    calidad_corta = {
        'R8 Estándar': 'R8', 'R9 Pesada': 'R9', 'R11 Liviana': 'R11', 'Madera Corta': 'MC',
        'Estándar': 'R8', 'Estandar': 'R8', 'Liviano': 'R11'
    }

    for bloque in bloques:
        cal = bloque.calidad or 'Sin Calidad'
        if cal not in bloques_por_calidad:
            bloques_por_calidad[cal] = {
                'bloques': [],
                'count': 0,
                'total_bft': 0,
                'calidad_corta': calidad_corta.get(cal, cal)
            }
        bloques_por_calidad[cal]['bloques'].append(bloque)
        bloques_por_calidad[cal]['count'] += 1
        bloques_por_calidad[cal]['total_bft'] += bloque.bft or 0

    # Ordenar calidades según el orden definido
    bloques_por_calidad_ordenado = {}
    for cal in orden_calidades:
        if cal in bloques_por_calidad:
            bloques_por_calidad_ordenado[cal] = bloques_por_calidad[cal]
    # Agregar calidades no contempladas al final
    for cal in bloques_por_calidad:
        if cal not in bloques_por_calidad_ordenado:
            bloques_por_calidad_ordenado[cal] = bloques_por_calidad[cal]

    # Obtener valores únicos para filtros
    secuencias_raw = list(set(b.secuencia for b in bloques if b.secuencia))
    try:
        secuencias = sorted(secuencias_raw, key=lambda x: int(x) if x.isdigit() else x, reverse=True)
    except:
        secuencias = sorted(secuencias_raw, reverse=True)
    turnos = list(set(b.turno for b in bloques if b.turno))
    calidades = list(set(b.calidad for b in bloques if b.calidad))
    largos = sorted(LARGOS_PRODUCCION, reverse=True)

    return render_template('bloques_encolados.html',
                          bloques=bloques,
                          bloques_por_calidad=bloques_por_calidad_ordenado,
                          secuencias=secuencias,
                          turnos=turnos,
                          calidades=calidades,
                          largos=largos,
                          largos_produccion=LARGOS_PRODUCCION)


@app.route('/bloque/<int:bloque_id>')
@login_required
def detalle_bloque(bloque_id):
    """Página de detalle de un bloque."""
    bloque = Bloque.query.get_or_404(bloque_id)
    return render_template('detalle_bloque.html', bloque=bloque, largos_produccion=LARGOS_PRODUCCION)


@app.route('/coche/<int:coche_id>')
@login_required
def detalle_coche(coche_id):
    """Página de detalle de un coche."""
    coche = Coche.query.get_or_404(coche_id)
    etapas = Etapa.query.order_by(Etapa.orden).all()
    historial = Movimiento.query.filter_by(coche_id=coche_id).order_by(Movimiento.timestamp.desc()).all()
    return render_template('detalle_coche.html', coche=coche, etapas=etapas, historial=historial)


@app.route('/lotes')
@login_required
def ver_lotes():
    """Página para ver todos los lotes."""
    lotes = Lote.query.order_by(Lote.created_at.desc()).all()
    return render_template('lotes.html', lotes=lotes)


@app.route('/lote/<int:lote_id>')
@login_required
def detalle_lote(lote_id):
    """Página de detalle de un lote."""
    lote = Lote.query.get_or_404(lote_id)
    return render_template('detalle_lote.html', lote=lote)


# ==================== API REST ====================

@app.route('/api/coches', methods=['GET'])
@login_required
def listar_coches():
    """Lista todos los coches."""
    coches = Coche.query.all()
    return jsonify([c.to_dict() for c in coches])


@app.route('/api/coches', methods=['POST'])
@login_required
def crear_coche():
    """Crea un nuevo coche. Siempre inicia en Madera Verde (etapa 1)."""
    data = request.get_json()

    # Generar codigo consecutivo (COC-YYYYMMDD-AAAA0001...)
    # Buscar el numero secuencial mas alto existente
    siguiente_num = 1
    for c in Coche.query.all():
        num = extraer_numero_coche(c.codigo_qr)
        if num and num >= siguiente_num:
            siguiente_num = num + 1

    codigo_qr = generar_codigo_coche_consecutivo(siguiente_num)

    # Verificar unicidad
    while Coche.query.filter_by(codigo_qr=codigo_qr).first():
        siguiente_num += 1
        codigo_qr = generar_codigo_coche_consecutivo(siguiente_num)

    # Etapa inicial SIEMPRE es Madera Verde (orden 1)
    etapa_inicial = Etapa.query.filter_by(orden=1).first()
    if not etapa_inicial:
        return jsonify({'error': 'No existe la etapa inicial'}), 500

    coche = Coche(
        codigo_qr=codigo_qr,
        registrador=data.get('registrador', ''),
        proveedor=data.get('proveedor', ''),
        numero_viaje=data.get('numero_viaje', ''),
        camara=None,  # La camara se asigna cuando pasa a Secado
        espesor_1=data.get('espesor_1'),
        largo_1=data.get('largo_1'),
        plantillas_1=data.get('plantillas_1', 0),
        espesor_2=data.get('espesor_2'),
        largo_2=data.get('largo_2'),
        plantillas_2=data.get('plantillas_2', 0),
        espesor_3=data.get('espesor_3'),
        largo_3=data.get('largo_3'),
        plantillas_3=data.get('plantillas_3', 0),
        etapa_actual_id=etapa_inicial.id,
        notas=data.get('notas', '')
    )

    # Calcular BFT
    coche.calcular_bft()

    db.session.add(coche)
    db.session.flush()

    # Registrar movimiento de creación
    movimiento = Movimiento(
        coche_id=coche.id,
        etapa_origen_id=None,
        etapa_destino_id=etapa_inicial.id,
        usuario=data.get('registrador', 'Sistema'),
        notas='Coche creado'
    )
    db.session.add(movimiento)
    db.session.commit()

    return jsonify({
        'success': True,
        'coche': coche.to_dict(),
        'mensaje': f'Coche {codigo_qr} creado exitosamente'
    }), 201


@app.route('/api/coches/<codigo_qr>', methods=['GET'])
@login_required
def obtener_coche_por_qr(codigo_qr):
    """Obtiene un coche por su código QR."""
    coche = Coche.query.filter_by(codigo_qr=codigo_qr).first()

    if not coche:
        return jsonify({'error': 'Coche no encontrado', 'codigo': codigo_qr}), 404

    return jsonify(coche.to_dict())


@app.route('/api/coches/<int:coche_id>', methods=['PUT'])
@login_required
def editar_coche(coche_id):
    """Edita un coche existente. Solo permitido en Madera Verde."""
    coche = Coche.query.get_or_404(coche_id)
    data = request.get_json() or {}

    # Solo permitir edicion en Madera Verde (orden 1)
    if not coche.etapa_actual or coche.etapa_actual.orden != 1:
        return jsonify({'error': 'Solo se pueden editar coches en Madera Verde'}), 400

    # Actualizar campos
    if 'registrador' in data:
        coche.registrador = data['registrador']
    if 'proveedor' in data:
        coche.proveedor = data['proveedor']
    if 'numero_viaje' in data:
        coche.numero_viaje = data['numero_viaje']
    if 'espesor_1' in data:
        coche.espesor_1 = data['espesor_1']
    if 'largo_1' in data:
        coche.largo_1 = data['largo_1']
    if 'plantillas_1' in data:
        coche.plantillas_1 = data['plantillas_1']
    if 'espesor_2' in data:
        coche.espesor_2 = data['espesor_2']
    if 'largo_2' in data:
        coche.largo_2 = data['largo_2']
    if 'plantillas_2' in data:
        coche.plantillas_2 = data['plantillas_2']
    if 'espesor_3' in data:
        coche.espesor_3 = data['espesor_3']
    if 'largo_3' in data:
        coche.largo_3 = data['largo_3']
    if 'plantillas_3' in data:
        coche.plantillas_3 = data['plantillas_3']
    if 'notas' in data:
        coche.notas = data['notas']

    # Recalcular BFT
    coche.calcular_bft()
    coche.updated_at = datetime.now()

    db.session.commit()

    return jsonify({
        'success': True,
        'coche': coche.to_dict(),
        'mensaje': f'Coche {coche.codigo_qr} actualizado'
    })


@app.route('/api/coches/<int:coche_id>', methods=['DELETE'])
@login_required
def eliminar_coche(coche_id):
    """Elimina un coche. Solo permitido en Madera Verde."""
    coche = Coche.query.get_or_404(coche_id)

    # Solo permitir eliminacion en Madera Verde (orden 1)
    if not coche.etapa_actual or coche.etapa_actual.orden != 1:
        return jsonify({'error': 'Solo se pueden eliminar coches en Madera Verde'}), 400

    codigo_qr = coche.codigo_qr

    # Eliminar movimientos asociados
    Movimiento.query.filter_by(coche_id=coche_id).delete()

    # Eliminar el coche
    db.session.delete(coche)
    db.session.commit()

    return jsonify({
        'success': True,
        'mensaje': f'Coche {codigo_qr} eliminado'
    })


@app.route('/api/coches/<int:coche_id>/mover', methods=['POST'])
@login_required
def mover_coche(coche_id):
    """Mueve un coche a una nueva etapa. Flujo: Madera Verde -> Secado -> Stock Secado -> Taller"""
    coche = Coche.query.get_or_404(coche_id)
    data = request.get_json()

    nueva_etapa_id = data.get('etapa_id')
    usuario = data.get('usuario', 'Anonimo')
    notas = data.get('notas', '')
    camara = data.get('camara')
    lote_secado = data.get('lote_secado')

    if not nueva_etapa_id:
        return jsonify({'error': 'Se requiere etapa_id'}), 400

    # Verificar que la etapa existe
    nueva_etapa = Etapa.query.get(nueva_etapa_id)
    if not nueva_etapa:
        return jsonify({'error': 'Etapa no valida'}), 400

    etapa_actual = coche.etapa_actual

    # Verificar que no está ya en esa etapa
    if coche.etapa_actual_id == nueva_etapa_id:
        return jsonify({'error': 'El coche ya esta en esa etapa'}), 400

    # Ingreso a Taller (orden 4) solo acepta lotes, no coches individuales
    if nueva_etapa.orden == 4:
        return jsonify({'error': 'Ingreso a Taller solo acepta lotes de produccion, no coches individuales'}), 400

    # Si va a Secado (orden 2), requiere camara y lote_secado
    if nueva_etapa.orden == 2:
        if not camara:
            return jsonify({'error': 'Se requiere seleccionar una camara para Secado'}), 400
        if not lote_secado:
            return jsonify({'error': 'Se requiere ingresar el numero de lote de secado'}), 400
        coche.camara = int(camara)
        coche.lote_secado = lote_secado
        notas = f'Camara {camara}, Lote {lote_secado}. {notas}' if notas else f'Camara {camara}, Lote {lote_secado}'

    # Mover el coche
    coche.mover_a_etapa(nueva_etapa_id, usuario, notas)
    db.session.commit()

    return jsonify({
        'success': True,
        'coche': coche.to_dict(),
        'mensaje': f'Coche movido a {nueva_etapa.nombre}'
    })


@app.route('/api/coches/mover-multiple', methods=['POST'])
@login_required
def mover_coches_multiple():
    """Mueve múltiples coches a una nueva etapa."""
    data = request.get_json()

    coche_ids = data.get('coche_ids', [])
    nueva_etapa_id = data.get('etapa_id')
    usuario = data.get('usuario', 'Anonimo')
    notas = data.get('notas', '')
    camara = data.get('camara')
    lote_secado = data.get('lote_secado')

    if not coche_ids:
        return jsonify({'error': 'Se requiere al menos un coche'}), 400

    if not nueva_etapa_id:
        return jsonify({'error': 'Se requiere etapa_id'}), 400

    # Verificar que la etapa existe
    nueva_etapa = Etapa.query.get(nueva_etapa_id)
    if not nueva_etapa:
        return jsonify({'error': 'Etapa no valida'}), 400

    # Ingreso a Taller (orden 4) solo acepta lotes, no coches individuales
    if nueva_etapa.orden == 4:
        return jsonify({'error': 'Ingreso a Taller solo acepta lotes de produccion, no coches individuales'}), 400

    # Procesar cada coche
    resultados = {
        'exitos': [],
        'errores': []
    }

    for coche_id in coche_ids:
        coche = Coche.query.get(coche_id)
        if not coche:
            resultados['errores'].append({
                'coche_id': coche_id,
                'error': 'Coche no encontrado'
            })
            continue

        etapa_actual = coche.etapa_actual

        # Verificar que no está ya en esa etapa
        if coche.etapa_actual_id == nueva_etapa_id:
            resultados['errores'].append({
                'coche_id': coche_id,
                'codigo_qr': coche.codigo_qr,
                'error': 'El coche ya esta en esa etapa'
            })
            continue

        # Si va a Secado (orden 2), requiere camara y lote_secado
        notas_mov = notas
        if nueva_etapa.orden == 2:
            if not camara:
                resultados['errores'].append({
                    'coche_id': coche_id,
                    'codigo_qr': coche.codigo_qr,
                    'error': 'Se requiere seleccionar una camara para Secado'
                })
                continue
            if not lote_secado:
                resultados['errores'].append({
                    'coche_id': coche_id,
                    'codigo_qr': coche.codigo_qr,
                    'error': 'Se requiere ingresar el numero de lote de secado'
                })
                continue
            coche.camara = int(camara)
            coche.lote_secado = lote_secado
            notas_mov = f'Camara {camara}, Lote {lote_secado}. {notas}' if notas else f'Camara {camara}, Lote {lote_secado}'

        # Mover el coche
        coche.mover_a_etapa(nueva_etapa_id, usuario, notas_mov)
        resultados['exitos'].append({
            'coche_id': coche_id,
            'codigo_qr': coche.codigo_qr
        })

    db.session.commit()

    return jsonify({
        'success': len(resultados['exitos']) > 0,
        'total_movidos': len(resultados['exitos']),
        'total_errores': len(resultados['errores']),
        'resultados': resultados,
        'mensaje': f'{len(resultados["exitos"])} coches movidos a {nueva_etapa.nombre}'
    })


@app.route('/api/coches/<int:coche_id>/cambiar-camara', methods=['POST'])
@login_required
def cambiar_camara(coche_id):
    """Permite cambiar de camara cuando esta en Secado (emergencia: horno danado)."""
    coche = Coche.query.get_or_404(coche_id)
    data = request.get_json()

    nueva_camara = data.get('camara')
    usuario = data.get('usuario', 'Anonimo')
    motivo = data.get('motivo', 'Cambio de camara')

    # Verificar que esta en Secado (orden 2)
    if not coche.etapa_actual or coche.etapa_actual.orden != 2:
        return jsonify({'error': 'Solo se puede cambiar camara cuando esta en Secado'}), 400

    if not nueva_camara:
        return jsonify({'error': 'Se requiere especificar la nueva camara'}), 400

    camara_anterior = coche.camara
    coche.camara = int(nueva_camara)

    # Registrar el cambio como un movimiento especial (mismo origen y destino)
    movimiento = Movimiento(
        coche_id=coche.id,
        etapa_origen_id=coche.etapa_actual_id,
        etapa_destino_id=coche.etapa_actual_id,
        usuario=usuario,
        notas=f'Cambio de Camara {camara_anterior} a Camara {nueva_camara}. Motivo: {motivo}'
    )
    db.session.add(movimiento)
    db.session.commit()

    return jsonify({
        'success': True,
        'coche': coche.to_dict(),
        'mensaje': f'Camara cambiada de {camara_anterior} a {nueva_camara}'
    })


@app.route('/api/coches/cambiar-camara-multiple', methods=['POST'])
@login_required
def cambiar_camara_multiple():
    """Permite cambiar de camara a multiples coches en Secado."""
    data = request.get_json()

    coche_ids = data.get('coche_ids', [])
    nueva_camara = data.get('camara')
    usuario = data.get('usuario', 'Anonimo')
    motivo = data.get('motivo', 'Cambio de camara masivo')

    if not coche_ids:
        return jsonify({'error': 'Se requiere al menos un coche'}), 400

    if not nueva_camara:
        return jsonify({'error': 'Se requiere especificar la nueva camara'}), 400

    resultados = {
        'exitos': [],
        'errores': []
    }

    for coche_id in coche_ids:
        coche = Coche.query.get(coche_id)
        if not coche:
            resultados['errores'].append({
                'coche_id': coche_id,
                'error': 'Coche no encontrado'
            })
            continue

        # Verificar que esta en Secado (orden 2)
        if not coche.etapa_actual or coche.etapa_actual.orden != 2:
            resultados['errores'].append({
                'coche_id': coche_id,
                'codigo_qr': coche.codigo_qr,
                'error': 'El coche no esta en Secado'
            })
            continue

        # Verificar que no esta ya en esa camara
        if coche.camara == int(nueva_camara):
            resultados['errores'].append({
                'coche_id': coche_id,
                'codigo_qr': coche.codigo_qr,
                'error': f'El coche ya esta en Camara {nueva_camara}'
            })
            continue

        camara_anterior = coche.camara
        coche.camara = int(nueva_camara)

        # Registrar el cambio
        movimiento = Movimiento(
            coche_id=coche.id,
            etapa_origen_id=coche.etapa_actual_id,
            etapa_destino_id=coche.etapa_actual_id,
            usuario=usuario,
            notas=f'Cambio de Camara {camara_anterior} a Camara {nueva_camara}. {motivo}'
        )
        db.session.add(movimiento)

        resultados['exitos'].append({
            'coche_id': coche_id,
            'codigo_qr': coche.codigo_qr,
            'camara_anterior': camara_anterior
        })

    db.session.commit()

    return jsonify({
        'success': len(resultados['exitos']) > 0,
        'total_movidos': len(resultados['exitos']),
        'total_errores': len(resultados['errores']),
        'resultados': resultados,
        'mensaje': f'{len(resultados["exitos"])} coches movidos a Camara {nueva_camara}'
    })


@app.route('/api/coches/<int:coche_id>/qr', methods=['GET'])
@login_required
def obtener_qr_imagen(coche_id):
    """Devuelve la imagen QR de un coche."""
    coche = Coche.query.get_or_404(coche_id)

    qr_bytes = generar_imagen_qr(coche.codigo_qr)

    return send_file(
        io.BytesIO(qr_bytes),
        mimetype='image/png',
        as_attachment=False,
        download_name=f'{coche.codigo_qr}.png'
    )


@app.route('/api/coches/<int:coche_id>/historial', methods=['GET'])
@login_required
def obtener_historial(coche_id):
    """Obtiene el historial de movimientos de un coche."""
    movimientos = Movimiento.query.filter_by(coche_id=coche_id).order_by(Movimiento.timestamp.desc()).all()
    return jsonify([m.to_dict() for m in movimientos])


@app.route('/api/etapas', methods=['GET'])
@login_required
def listar_etapas():
    """Lista todas las etapas."""
    etapas = Etapa.query.order_by(Etapa.orden).all()
    return jsonify([e.to_dict() for e in etapas])


@app.route('/api/secado/camara/<int:camara>/lote/<lote_secado>')
@login_required
def obtener_lote_secado(camara, lote_secado):
    """Obtiene información de un lote de secado para impresión."""
    etapa_secado = Etapa.query.filter_by(orden=2).first()
    if not etapa_secado:
        return jsonify({'error': 'Etapa de secado no encontrada'}), 404

    coches = Coche.query.filter_by(
        etapa_actual_id=etapa_secado.id,
        camara=camara,
        lote_secado=lote_secado
    ).order_by(Coche.created_at).all()

    if not coches:
        return jsonify({'error': 'No se encontraron coches para este lote'}), 404

    # Calcular resumen por espesor
    resumen_espesor = {}
    total_bft = 0

    for coche in coches:
        for i in range(1, 4):
            espesor = getattr(coche, f'espesor_{i}')
            bft = getattr(coche, f'bft_{i}') or 0
            if espesor and bft > 0:
                if espesor not in resumen_espesor:
                    resumen_espesor[espesor] = 0
                resumen_espesor[espesor] += bft
                total_bft += bft

    # Calcular porcentajes
    resumen_con_porcentaje = []
    for espesor in sorted(resumen_espesor.keys(), key=lambda x: float(x) if x else 0):
        vol = resumen_espesor[espesor]
        porcentaje = (vol / total_bft * 100) if total_bft > 0 else 0
        resumen_con_porcentaje.append({
            'espesor': espesor,
            'volumen': vol,
            'porcentaje': round(porcentaje, 1)
        })

    # Obtener fechas
    fechas = [c.created_at for c in coches if c.created_at]
    fecha_inicial = min(fechas).strftime('%d/%m/%y') if fechas else ''
    fecha_final = max(fechas).strftime('%d/%m/%y') if fechas else ''

    return jsonify({
        'success': True,
        'camara': camara,
        'lote_secado': lote_secado,
        'fecha_inicial': fecha_inicial,
        'fecha_final': fecha_final,
        'total_coches': len(coches),
        'total_bft': total_bft,
        'resumen_espesor': resumen_con_porcentaje,
        'coches': [{
            'id': c.id,
            'codigo_qr': c.codigo_qr,
            'fecha_llegada': c.created_at.strftime('%d/%m/%y') if c.created_at else '',
            'proveedor': c.proveedor or '-',
            'numero_viaje': c.numero_viaje or '-',
            'espesor_1': c.espesor_1,
            'largo_1': c.largo_1,
            'plantillas_1': c.plantillas_1 or 0,
            'bft_1': c.bft_1 or 0,
            'espesor_2': c.espesor_2,
            'largo_2': c.largo_2,
            'plantillas_2': c.plantillas_2 or 0,
            'bft_2': c.bft_2 or 0,
            'espesor_3': c.espesor_3,
            'largo_3': c.largo_3,
            'plantillas_3': c.plantillas_3 or 0,
            'bft_3': c.bft_3 or 0,
            'total_bft': c.total_bft or 0
        } for c in coches]
    })


@app.route('/api/recepcion/resumen-compras', methods=['GET'])
@login_required
def resumen_compras():
    """Obtiene resumen de compras por rango de fechas."""
    from datetime import datetime, timedelta

    fecha_inicio = request.args.get('fecha_inicio')
    fecha_fin = request.args.get('fecha_fin')

    # Si no se proporcionan fechas, usar el mes actual
    if not fecha_inicio:
        fecha_inicio = datetime.now().replace(day=1).strftime('%Y-%m-%d')
    if not fecha_fin:
        fecha_fin = datetime.now().strftime('%Y-%m-%d')

    try:
        fecha_inicio_dt = datetime.strptime(fecha_inicio, '%Y-%m-%d')
        fecha_fin_dt = datetime.strptime(fecha_fin, '%Y-%m-%d') + timedelta(days=1)
    except ValueError:
        return jsonify({'error': 'Formato de fecha invalido. Use YYYY-MM-DD'}), 400

    # Obtener coches en el rango de fechas (Madera Verde = orden 1)
    etapa_verde = Etapa.query.filter_by(orden=1).first()
    if not etapa_verde:
        return jsonify({'error': 'Etapa Madera Verde no encontrada'}), 404

    # Buscar todos los coches creados en ese rango
    coches = Coche.query.filter(
        Coche.created_at >= fecha_inicio_dt,
        Coche.created_at < fecha_fin_dt
    ).order_by(Coche.created_at).all()

    # Agrupar por proveedor
    por_proveedor = {}
    total_bft = 0
    total_coches = len(coches)

    for coche in coches:
        prov = coche.proveedor or 'Sin Proveedor'
        if prov not in por_proveedor:
            por_proveedor[prov] = {
                'coches': 0,
                'bft': 0,
                'viajes': set()
            }
        por_proveedor[prov]['coches'] += 1
        por_proveedor[prov]['bft'] += coche.total_bft or 0
        if coche.numero_viaje:
            por_proveedor[prov]['viajes'].add(coche.numero_viaje)
        total_bft += coche.total_bft or 0

    # Convertir sets a listas para JSON
    resumen_proveedores = []
    for prov, datos in sorted(por_proveedor.items()):
        resumen_proveedores.append({
            'proveedor': prov,
            'coches': datos['coches'],
            'bft': datos['bft'],
            'viajes': len(datos['viajes'])
        })

    # Agrupar por espesor
    por_espesor = {}
    for coche in coches:
        for i in range(1, 4):
            espesor = getattr(coche, f'espesor_{i}')
            bft = getattr(coche, f'bft_{i}') or 0
            if espesor and bft > 0:
                if espesor not in por_espesor:
                    por_espesor[espesor] = 0
                por_espesor[espesor] += bft

    resumen_espesores = []
    for esp in sorted(por_espesor.keys(), key=lambda x: float(x) if x else 0):
        porcentaje = (por_espesor[esp] / total_bft * 100) if total_bft > 0 else 0
        resumen_espesores.append({
            'espesor': esp,
            'bft': por_espesor[esp],
            'porcentaje': round(porcentaje, 1)
        })

    return jsonify({
        'success': True,
        'fecha_inicio': fecha_inicio,
        'fecha_fin': fecha_fin,
        'total_coches': total_coches,
        'total_bft': total_bft,
        'por_proveedor': resumen_proveedores,
        'por_espesor': resumen_espesores
    })


@app.route('/api/dashboard/resumen', methods=['GET'])
@login_required
def resumen_dashboard():
    """Obtiene resumen para el dashboard."""
    etapas = Etapa.query.order_by(Etapa.orden).all()

    # Obtener IDs de coches que estan en lotes en_proceso o finalizado
    lotes_en_uso = Lote.query.filter(
        Lote.estado.in_(['en_proceso', 'finalizado'])
    ).all()
    coches_en_lotes_usados_ids = set()
    for lote in lotes_en_uso:
        for coche in lote.coches:
            coches_en_lotes_usados_ids.add(coche.id)

    resumen = []
    for etapa in etapas:
        coches = Coche.query.filter_by(etapa_actual_id=etapa.id).all()

        # Si es Ingreso a Taller (orden 4), filtrar coches en lotes en uso
        if etapa.orden == 4:
            coches = [c for c in coches if c.id not in coches_en_lotes_usados_ids]

        total_bft = sum(c.total_bft or 0 for c in coches)
        resumen.append({
            'etapa': etapa.to_dict(),
            'cantidad': len(coches),
            'total_bft': total_bft
        })

    return jsonify(resumen)


@app.route('/api/scan', methods=['POST'])
@login_required
def escanear_qr():
    """Procesa un escaneo QR desde móvil. Busca coches, lotes y bloques."""
    data = request.get_json()
    codigo_qr = data.get('codigo_qr', '').strip()

    if not codigo_qr:
        return jsonify({'error': 'Código QR vacío'}), 400

    etapas = Etapa.query.order_by(Etapa.orden).all()

    # Primero buscar en coches
    coche = Coche.query.filter_by(codigo_qr=codigo_qr).first()
    if coche:
        return jsonify({
            'tipo': 'coche',
            'coche': coche.to_dict(),
            'etapas': [e.to_dict() for e in etapas]
        })

    # Si no es coche, buscar en lotes
    lote = Lote.query.filter_by(codigo_qr=codigo_qr).first()
    if lote:
        return jsonify({
            'tipo': 'lote',
            'lote': lote.to_dict(),
            'etapas': [e.to_dict() for e in etapas]
        })

    # Si no es lote, buscar en bloques
    bloque = Bloque.query.filter_by(codigo_qr=codigo_qr).first()
    if bloque:
        return jsonify({
            'tipo': 'bloque',
            'bloque': bloque.to_dict(),
            'etapas': [e.to_dict() for e in etapas]
        })

    return jsonify({'error': 'Código no encontrado', 'codigo': codigo_qr}), 404


# ==================== API LOTES ====================

@app.route('/api/lotes', methods=['GET'])
@login_required
def listar_lotes():
    """Lista todos los lotes."""
    lotes = Lote.query.order_by(Lote.created_at.desc()).all()
    return jsonify([l.to_dict() for l in lotes])


@app.route('/api/lotes', methods=['POST'])
@login_required
def crear_lote():
    """Crea un nuevo lote combinando coches de Stock Seco y los mueve a Ingreso a Taller."""
    data = request.get_json()

    coche_ids = data.get('coche_ids', [])
    usuario = data.get('usuario', 'Anonimo')
    notas = data.get('notas', '')
    turno = data.get('turno', 'Diurno')  # Diurno o Nocturno

    if not coche_ids:
        return jsonify({'error': 'Se requiere al menos un coche para crear el lote'}), 400

    # Verificar que la etapa Stock Seco existe
    etapa_stock_seco = Etapa.query.filter_by(orden=3).first()
    etapa_taller = Etapa.query.filter_by(orden=4).first()

    if not etapa_stock_seco or not etapa_taller:
        return jsonify({'error': 'Error de configuración de etapas'}), 500

    # Obtener y validar coches
    coches = []
    errores = []

    for coche_id in coche_ids:
        coche = Coche.query.get(coche_id)
        if not coche:
            errores.append({'coche_id': coche_id, 'error': 'Coche no encontrado'})
            continue
        if coche.etapa_actual_id != etapa_stock_seco.id:
            errores.append({
                'coche_id': coche_id,
                'codigo_qr': coche.codigo_qr,
                'error': 'El coche no está en Stock Seco'
            })
            continue
        coches.append(coche)

    if not coches:
        return jsonify({
            'error': 'Ningún coche válido para crear el lote',
            'errores': errores
        }), 400

    # Generar codigo consecutivo para el lote (PRO-YYYYMMDD-AAAA0001...)
    siguiente_num = 1
    for l in Lote.query.all():
        num = extraer_numero_lote(l.codigo_qr)
        if num and num >= siguiente_num:
            siguiente_num = num + 1

    codigo_lote = generar_codigo_lote_consecutivo(siguiente_num)

    # Verificar unicidad
    while Lote.query.filter_by(codigo_qr=codigo_lote).first():
        siguiente_num += 1
        codigo_lote = generar_codigo_lote_consecutivo(siguiente_num)

    # Crear el lote
    lote = Lote(
        codigo_qr=codigo_lote,
        turno=turno,
        creado_por=usuario,
        notas=notas
    )

    # Agregar coches al lote y moverlos a Ingreso a Taller
    codigos_coches = []
    for coche in coches:
        lote.coches.append(coche)
        codigos_coches.append(coche.codigo_qr)
        # Mover el coche a Ingreso a Taller
        coche.mover_a_etapa(
            etapa_taller.id,
            usuario,
            f'Agregado al lote {codigo_lote}'
        )

    # Calcular totales
    lote.calcular_total_bft()

    db.session.add(lote)
    db.session.commit()

    return jsonify({
        'success': True,
        'lote': lote.to_dict(),
        'mensaje': f'Lote {codigo_lote} creado con {len(coches)} coches',
        'coches_incluidos': codigos_coches,
        'errores': errores if errores else None
    }), 201


@app.route('/api/lotes/<int:lote_id>/agregar-coches', methods=['POST'])
@login_required
def agregar_coches_lote(lote_id):
    """Agrega coches a un lote existente (no finalizado)."""
    try:
        lote = Lote.query.get(lote_id)
        if not lote:
            return jsonify({'error': 'Lote no encontrado'}), 404

        data = request.get_json(silent=True) or {}

        if lote.estado == 'finalizado':
            return jsonify({'error': 'No se pueden agregar coches a un lote finalizado'}), 400

        # Aceptar ambos nombres de parametro para compatibilidad
        coche_ids = data.get('coches_ids', data.get('coche_ids', []))
        usuario = data.get('usuario', 'Anonimo')

        if not coche_ids:
            return jsonify({'error': 'Se requiere al menos un coche'}), 400

        etapa_stock_seco = Etapa.query.filter_by(orden=3).first()
        etapa_taller = Etapa.query.filter_by(orden=4).first()

        if not etapa_stock_seco or not etapa_taller:
            return jsonify({'error': 'No se encontraron las etapas necesarias'}), 500

        coches_agregados = []
        errores = []

        for coche_id in coche_ids:
            coche = Coche.query.get(coche_id)
            if not coche:
                errores.append({'coche_id': coche_id, 'error': 'Coche no encontrado'})
                continue
            if coche.etapa_actual_id != etapa_stock_seco.id:
                errores.append({'coche_id': coche_id, 'error': 'El coche no esta en Stock Secado'})
                continue
            if coche in lote.coches:
                errores.append({'coche_id': coche_id, 'error': 'El coche ya esta en el lote'})
                continue

            lote.coches.append(coche)
            coche.mover_a_etapa(etapa_taller.id, usuario, f'Agregado al lote {lote.codigo_qr}')
            coches_agregados.append(coche.codigo_qr)

        lote.calcular_total_bft()
        db.session.commit()

        return jsonify({
            'success': True,
            'mensaje': f'{len(coches_agregados)} coche(s) agregado(s) al lote',
            'lote': lote.to_dict(),
            'coches_agregados': coches_agregados,
            'errores': errores if errores else None
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Error interno: {str(e)}'}), 500


@app.route('/api/lotes/<int:lote_id>/quitar-coche/<int:coche_id>', methods=['POST'])
@login_required
def quitar_coche_lote(lote_id, coche_id):
    """Quita un coche del lote y lo devuelve a Stock Secado."""
    try:
        lote = Lote.query.get(lote_id)
        if not lote:
            return jsonify({'error': 'Lote no encontrado'}), 404

        coche = Coche.query.get(coche_id)
        if not coche:
            return jsonify({'error': 'Coche no encontrado'}), 404

        data = request.get_json(silent=True) or {}

        if lote.estado == 'finalizado':
            return jsonify({'error': 'No se pueden quitar coches de un lote finalizado'}), 400

        # Refrescar la relacion para asegurar datos actualizados
        db.session.refresh(lote)

        # Verificar con consulta directa a la tabla de relacion
        coche_en_lote = db.session.query(lote_coches).filter_by(lote_id=lote_id, coche_id=coche_id).first()
        if not coche_en_lote:
            return jsonify({'error': 'El coche no pertenece a este lote'}), 400

        # Verificar que el lote no quede vacio
        cantidad_coches = db.session.query(lote_coches).filter_by(lote_id=lote_id).count()
        if cantidad_coches <= 1:
            return jsonify({'error': 'El lote debe tener al menos 1 coche. No se puede quitar el ultimo coche.'}), 400

        usuario = data.get('usuario', 'Anonimo')
        etapa_stock_seco = Etapa.query.filter_by(orden=3).first()

        if not etapa_stock_seco:
            return jsonify({'error': 'No se encontro la etapa Stock Secado'}), 500

        # Quitar coche del lote
        lote.coches.remove(coche)

        # Mover coche a Stock Secado
        coche.mover_a_etapa(etapa_stock_seco.id, usuario, f'Removido del lote {lote.codigo_qr}')

        # Recalcular totales del lote
        lote.calcular_total_bft()
        db.session.commit()

        return jsonify({
            'success': True,
            'mensaje': f'Coche {coche.codigo_qr} removido del lote y devuelto a Stock Secado',
            'lote': lote.to_dict()
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Error interno: {str(e)}'}), 500


@app.route('/api/lotes/<int:lote_id>', methods=['GET'])
@login_required
def obtener_lote(lote_id):
    """Obtiene un lote por su ID."""
    lote = Lote.query.get_or_404(lote_id)
    return jsonify(lote.to_dict())


@app.route('/api/lotes/<codigo_qr>', methods=['GET'])
@login_required
def obtener_lote_por_qr(codigo_qr):
    """Obtiene un lote por su código QR."""
    lote = Lote.query.filter_by(codigo_qr=codigo_qr).first()

    if not lote:
        return jsonify({'error': 'Lote no encontrado', 'codigo': codigo_qr}), 404

    return jsonify(lote.to_dict())


@app.route('/api/lotes/<int:lote_id>/qr', methods=['GET'])
@login_required
def obtener_qr_lote(lote_id):
    """Devuelve la imagen QR de un lote."""
    lote = Lote.query.get_or_404(lote_id)

    qr_bytes = generar_imagen_qr(lote.codigo_qr)

    return send_file(
        io.BytesIO(qr_bytes),
        mimetype='image/png',
        as_attachment=False,
        download_name=f'{lote.codigo_qr}.png'
    )


# ==================== API PRODUCCION - BLOQUES ====================

@app.route('/api/bloques', methods=['GET'])
@login_required
def listar_bloques():
    """Lista todos los bloques."""
    estado = request.args.get('estado')
    if estado:
        bloques = Bloque.query.filter_by(estado=estado).order_by(Bloque.created_at.desc()).all()
    else:
        bloques = Bloque.query.order_by(Bloque.created_at.desc()).all()
    return jsonify([b.to_dict() for b in bloques])


@app.route('/api/bloques', methods=['POST'])
@login_required
def crear_bloque():
    """Crea un nuevo bloque presentado con código QR."""
    data = request.get_json()

    # Validar campos requeridos
    largo = data.get('largo')
    peso = data.get('peso')
    lote_id = data.get('lote_id')

    if not largo:
        return jsonify({'error': 'Se requiere el largo del bloque'}), 400
    if not peso:
        return jsonify({'error': 'Se requiere el peso del bloque'}), 400

    # Generar codigo consecutivo para el bloque (BLQ-YYYYMMDD-AAAA0001...)
    siguiente_num = 1
    for b in Bloque.query.all():
        num = extraer_numero_bloque(b.codigo_qr)
        if num and num >= siguiente_num:
            siguiente_num = num + 1

    codigo_qr = generar_codigo_bloque_consecutivo(siguiente_num)

    # Verificar unicidad
    while Bloque.query.filter_by(codigo_qr=codigo_qr).first():
        siguiente_num += 1
        codigo_qr = generar_codigo_bloque_consecutivo(siguiente_num)

    # Parsear fecha si viene
    fecha = data.get('fecha')
    if fecha:
        try:
            fecha = datetime.strptime(fecha, '%Y-%m-%d').date()
        except ValueError:
            fecha = datetime.now().date()
    else:
        fecha = datetime.now().date()

    bloque = Bloque(
        codigo_qr=codigo_qr,
        lote_id=lote_id,
        fecha=fecha,
        turno=data.get('turno', 'Diurno'),
        calidad=data.get('calidad', 'Estándar'),
        secuencia=data.get('secuencia', ''),
        largo=int(largo),
        peso=float(peso),
        empatado=data.get('empatado', False),
        estado='presentado',
        notas=data.get('notas', '')
    )

    # Calcular BFT y densidad
    bloque.calcular_bft()
    bloque.calcular_densidad_presentado()

    db.session.add(bloque)

    # Si hay lote_id, sumar BFT al lote
    lote_bft_usado = None
    if lote_id:
        lote = Lote.query.get(lote_id)
        if lote:
            lote.usar_bft(bloque.bft)
            lote_bft_usado = lote.bft_usado

    db.session.commit()

    response = {
        'success': True,
        'bloque': bloque.to_dict(),
        'mensaje': f'Bloque {codigo_qr} creado exitosamente'
    }

    if lote_bft_usado is not None:
        response['lote_bft_usado'] = lote_bft_usado

    return jsonify(response), 201


@app.route('/api/bloques/<int:bloque_id>', methods=['GET'])
@login_required
def obtener_bloque(bloque_id):
    """Obtiene un bloque por su ID."""
    bloque = Bloque.query.get_or_404(bloque_id)
    return jsonify(bloque.to_dict())


@app.route('/api/bloques/<int:bloque_id>/qr', methods=['GET'])
@login_required
def obtener_qr_bloque(bloque_id):
    """Devuelve la imagen QR de un bloque."""
    bloque = Bloque.query.get_or_404(bloque_id)

    qr_bytes = generar_imagen_qr(bloque.codigo_qr)

    return send_file(
        io.BytesIO(qr_bytes),
        mimetype='image/png',
        as_attachment=False,
        download_name=f'{bloque.codigo_qr}.png'
    )


@app.route('/api/bloques/<int:bloque_id>/encolar', methods=['POST'])
@login_required
def encolar_bloque(bloque_id):
    """Mueve un bloque de presentado a encolado, actualizando el peso."""
    bloque = Bloque.query.get_or_404(bloque_id)
    data = request.get_json()

    if bloque.estado != 'presentado':
        return jsonify({'error': 'El bloque ya está encolado'}), 400

    nuevo_peso = data.get('peso')
    if not nuevo_peso:
        return jsonify({'error': 'Se requiere el nuevo peso para encolar'}), 400

    # Encolar el bloque
    bloque.encolar(float(nuevo_peso))
    db.session.commit()

    return jsonify({
        'success': True,
        'bloque': bloque.to_dict(),
        'mensaje': f'Bloque {bloque.codigo_qr} encolado exitosamente'
    })


@app.route('/api/bloques/encolar-multiple', methods=['POST'])
@login_required
def encolar_bloques_multiple():
    """Encola múltiples bloques a la vez."""
    data = request.get_json()

    bloques_data = data.get('bloques', [])  # Lista de {bloque_id, peso}

    if not bloques_data:
        return jsonify({'error': 'Se requiere al menos un bloque'}), 400

    resultados = {
        'exitos': [],
        'errores': []
    }

    for item in bloques_data:
        bloque_id = item.get('bloque_id')
        nuevo_peso = item.get('peso')

        bloque = Bloque.query.get(bloque_id)
        if not bloque:
            resultados['errores'].append({
                'bloque_id': bloque_id,
                'error': 'Bloque no encontrado'
            })
            continue

        if bloque.estado != 'presentado':
            resultados['errores'].append({
                'bloque_id': bloque_id,
                'codigo_qr': bloque.codigo_qr,
                'error': 'El bloque ya está encolado'
            })
            continue

        if not nuevo_peso:
            resultados['errores'].append({
                'bloque_id': bloque_id,
                'codigo_qr': bloque.codigo_qr,
                'error': 'Se requiere el peso'
            })
            continue

        bloque.encolar(float(nuevo_peso))
        resultados['exitos'].append({
            'bloque_id': bloque_id,
            'codigo_qr': bloque.codigo_qr
        })

    db.session.commit()

    return jsonify({
        'success': len(resultados['exitos']) > 0,
        'total_encolados': len(resultados['exitos']),
        'total_errores': len(resultados['errores']),
        'resultados': resultados,
        'mensaje': f'{len(resultados["exitos"])} bloques encolados'
    })


# ==================== API PRODUCCION - PROCESO ====================

@app.route('/api/proceso', methods=['GET'])
@login_required
def listar_procesos():
    """Lista todos los procesos de lotes."""
    procesos = ProcesoLote.query.order_by(ProcesoLote.created_at.desc()).all()
    return jsonify([p.to_dict() for p in procesos])


@app.route('/api/proceso', methods=['POST'])
@login_required
def crear_proceso():
    """Crea un nuevo proceso de lote (cálculo de madera plantillada)."""
    data = request.get_json()

    lote_id = data.get('lote_id')
    largo = data.get('largo')
    alto = data.get('alto')
    usuario = data.get('usuario', 'Anónimo')

    if not lote_id:
        return jsonify({'error': 'Se requiere el ID del lote'}), 400
    if not largo:
        return jsonify({'error': 'Se requiere el largo'}), 400
    if not alto:
        return jsonify({'error': 'Se requiere el alto'}), 400

    # Verificar que el lote existe
    lote = Lote.query.get(lote_id)
    if not lote:
        return jsonify({'error': 'Lote no encontrado'}), 404

    proceso = ProcesoLote(
        lote_id=lote_id,
        largo=int(largo),
        ancho=24,  # Fijo
        alto=float(alto),
        calidad=data.get('calidad', 'R8 Estándar'),
        procesado_por=usuario,
        notas=data.get('notas', '')
    )

    # Calcular BFT
    bft_plantilla = proceso.calcular_bft()

    # Registrar BFT usado en el lote
    lote.usar_bft(bft_plantilla)

    db.session.add(proceso)
    db.session.commit()

    return jsonify({
        'success': True,
        'proceso': proceso.to_dict(),
        'bft_usado': bft_plantilla,
        'lote_bft_usado': lote.bft_usado,
        'lote_bft_disponible': lote.bft_disponible,
        'mensaje': f'Proceso creado para lote {lote.codigo_qr}'
    }), 201


@app.route('/api/proceso/<int:proceso_id>', methods=['GET'])
@login_required
def obtener_proceso(proceso_id):
    """Obtiene un proceso por su ID."""
    proceso = ProcesoLote.query.get_or_404(proceso_id)
    return jsonify(proceso.to_dict())


@app.route('/api/proceso/<int:proceso_id>', methods=['DELETE'])
@login_required
def eliminar_proceso(proceso_id):
    """Elimina una plantilla/proceso por su ID."""
    proceso = ProcesoLote.query.get_or_404(proceso_id)
    lote = proceso.lote

    # No permitir eliminar si el lote está finalizado
    if lote and lote.estado == 'finalizado':
        return jsonify({'error': 'No se puede eliminar de un lote finalizado'}), 400

    # Revertir el BFT usado del lote
    if lote and proceso.bft_calculado:
        lote.bft_usado = max(0, (lote.bft_usado or 0) - proceso.bft_calculado)

    db.session.delete(proceso)
    db.session.commit()

    return jsonify({
        'success': True,
        'mensaje': f'Plantilla eliminada correctamente'
    })


@app.route('/api/bloques/<int:bloque_id>', methods=['DELETE'])
@login_required
def eliminar_bloque(bloque_id):
    """Elimina un bloque por su ID."""
    bloque = Bloque.query.get_or_404(bloque_id)
    lote = bloque.lote

    # No permitir eliminar si el lote está finalizado
    if lote and lote.estado == 'finalizado':
        return jsonify({'error': 'No se puede eliminar de un lote finalizado'}), 400

    # No permitir eliminar si el bloque ya fue encolado o está en un contenedor
    if bloque.estado != 'presentado':
        return jsonify({'error': f'No se puede eliminar un bloque en estado {bloque.estado}'}), 400

    # Revertir el BFT usado del lote
    if lote and bloque.bft:
        lote.bft_usado = max(0, (lote.bft_usado or 0) - bloque.bft)

    db.session.delete(bloque)
    db.session.commit()

    return jsonify({
        'success': True,
        'mensaje': f'Bloque {bloque.codigo_qr} eliminado correctamente'
    })


@app.route('/api/lotes-taller', methods=['GET'])
@login_required
def listar_lotes_taller():
    """Lista lotes disponibles en Ingreso a Taller."""
    lotes = Lote.query.order_by(Lote.created_at.desc()).all()
    return jsonify([l.to_dict() for l in lotes])


@app.route('/api/lotes/<int:lote_id>/iniciar', methods=['POST'])
@login_required
def iniciar_lote(lote_id):
    """Inicia el proceso de un lote (lo mueve a producción)."""
    lote = Lote.query.get_or_404(lote_id)

    if lote.estado == 'en_proceso':
        return jsonify({'error': 'El lote ya está en proceso'}), 400
    if lote.estado == 'finalizado':
        return jsonify({'error': 'El lote ya está finalizado'}), 400

    lote.iniciar_proceso()
    db.session.commit()

    return jsonify({
        'success': True,
        'lote': lote.to_dict(),
        'mensaje': f'Lote {lote.codigo_qr} iniciado en producción'
    })


@app.route('/api/lotes/<int:lote_id>/finalizar', methods=['POST'])
@login_required
def finalizar_lote(lote_id):
    """Finaliza el proceso de un lote."""
    lote = Lote.query.get_or_404(lote_id)

    if lote.estado == 'finalizado':
        return jsonify({'error': 'El lote ya está finalizado'}), 400
    if lote.estado != 'en_proceso':
        return jsonify({'error': 'El lote no está en proceso'}), 400

    lote.finalizar()
    db.session.commit()

    return jsonify({
        'success': True,
        'lote': lote.to_dict(),
        'mensaje': f'Lote {lote.codigo_qr} finalizado con {lote.desperdicio_porcentaje:.1f}% de desperdicio'
    })


@app.route('/api/lotes/<int:lote_id>/editar-finalizado', methods=['POST'])
@login_required
def editar_lote_finalizado(lote_id):
    """Edita un lote finalizado con verificacion de contraseña."""
    data = request.get_json() or {}
    password = data.get('password', '')

    # Verificar contraseña
    if password != EDIT_LOTE_PASSWORD:
        return jsonify({'error': 'Contraseña incorrecta'}), 403

    lote = Lote.query.get_or_404(lote_id)

    if lote.estado != 'finalizado':
        return jsonify({'error': 'Este lote no está finalizado'}), 400

    # Actualizar campos editables
    if 'bft_usado' in data:
        lote.bft_usado = float(data['bft_usado'])
        # Recalcular desperdicio
        lote.desperdicio_bft = lote.total_bft - lote.bft_usado
        if lote.total_bft > 0:
            lote.desperdicio_porcentaje = (lote.desperdicio_bft / lote.total_bft) * 100
        else:
            lote.desperdicio_porcentaje = 0

    if 'notas' in data:
        lote.notas = data['notas']

    if 'turno' in data:
        lote.turno = data['turno']

    db.session.commit()

    return jsonify({
        'success': True,
        'lote': lote.to_dict(),
        'mensaje': f'Lote {lote.codigo_qr} actualizado correctamente'
    })


@app.route('/api/lotes/<int:lote_id>/reabrir', methods=['POST'])
@login_required
def reabrir_lote_finalizado(lote_id):
    """Reabre un lote finalizado para editarlo en producción."""
    data = request.get_json() or {}
    password = data.get('password', '')

    # Verificar contraseña
    if password != EDIT_LOTE_PASSWORD:
        return jsonify({'error': 'Contraseña incorrecta'}), 403

    lote = Lote.query.get_or_404(lote_id)

    if lote.estado != 'finalizado':
        return jsonify({'error': 'Este lote no está finalizado'}), 400

    # Cambiar estado a en_proceso para poder editarlo
    lote.estado = 'en_proceso'
    lote.fecha_finalizado = None
    db.session.commit()

    return jsonify({
        'success': True,
        'mensaje': f'Lote {lote.codigo_qr} reabierto para edición',
        'redirect_url': f'/produccion/{lote.id}'
    })


# ==================== CONTENEDORES (EMBARQUE) ====================

@app.route('/contenedores')
@login_required
def ver_contenedores():
    """Vista principal de contenedores de embarque."""
    contenedores_abiertos = Contenedor.query.filter_by(estado='abierto').order_by(Contenedor.created_at.desc()).all()
    contenedores_cerrados = Contenedor.query.filter(Contenedor.estado.in_(['cerrado', 'embarcado'])).order_by(Contenedor.created_at.desc()).all()

    # Obtener bloques encolados disponibles (no asignados a ningún contenedor)
    bloques_encolados = Bloque.query.filter_by(estado='encolado').all()
    bloques_disponibles = [b for b in bloques_encolados if len(b.contenedores) == 0]

    return render_template('contenedores.html',
                           contenedores_abiertos=contenedores_abiertos,
                           contenedores_cerrados=contenedores_cerrados,
                           bloques_disponibles=bloques_disponibles,
                           largos_contenedor=LARGOS_CONTENEDOR)


@app.route('/contenedor/<int:contenedor_id>')
@login_required
def ver_contenedor(contenedor_id):
    """Vista detalle de un contenedor."""
    contenedor = Contenedor.query.get_or_404(contenedor_id)

    # Obtener bloques encolados disponibles
    bloques_encolados = Bloque.query.filter_by(estado='encolado').all()
    bloques_disponibles = [b for b in bloques_encolados if len(b.contenedores) == 0]

    return render_template('detalle_contenedor.html',
                           contenedor=contenedor,
                           bloques_disponibles=bloques_disponibles,
                           largos_contenedor=LARGOS_CONTENEDOR)


@app.route('/api/contenedores', methods=['GET'])
@login_required
def listar_contenedores():
    """Lista todos los contenedores."""
    contenedores = Contenedor.query.order_by(Contenedor.created_at.desc()).all()
    return jsonify([c.to_dict() for c in contenedores])


@app.route('/api/contenedores', methods=['POST'])
@login_required
def crear_contenedor():
    """Crea un nuevo contenedor de embarque."""
    data = request.get_json()

    # Generar codigo consecutivo para el contenedor (CON-YYYYMMDD-AAAA0001...)
    siguiente_num = 1
    for c in Contenedor.query.all():
        num = extraer_numero_contenedor(c.codigo)
        if num and num >= siguiente_num:
            siguiente_num = num + 1

    codigo = generar_codigo_contenedor_consecutivo(siguiente_num)

    # Verificar unicidad
    while Contenedor.query.filter_by(codigo=codigo).first():
        siguiente_num += 1
        codigo = generar_codigo_contenedor_consecutivo(siguiente_num)

    # Parsear fechas si vienen
    fecha_carga = None
    fecha_zarpe = None
    if data.get('fecha_carga'):
        try:
            fecha_carga = datetime.strptime(data['fecha_carga'], '%Y-%m-%d').date()
        except:
            pass
    if data.get('fecha_zarpe'):
        try:
            fecha_zarpe = datetime.strptime(data['fecha_zarpe'], '%Y-%m-%d').date()
        except:
            pass

    contenedor = Contenedor(
        codigo=codigo,
        cliente=data.get('cliente', ''),
        numero_contenedor=data.get('numero_contenedor', ''),
        fecha_carga=fecha_carga,
        fecha_zarpe=fecha_zarpe,
        tally_sheet=data.get('tally_sheet', ''),
        creado_por=data.get('creado_por', 'Anonimo'),
        notas=data.get('notas', '')
    )

    db.session.add(contenedor)
    db.session.commit()

    return jsonify({
        'success': True,
        'contenedor': contenedor.to_dict(),
        'mensaje': f'Contenedor {codigo} creado exitosamente'
    })


@app.route('/api/contenedores/<int:contenedor_id>', methods=['GET'])
@login_required
def obtener_contenedor(contenedor_id):
    """Obtiene un contenedor por ID."""
    contenedor = Contenedor.query.get_or_404(contenedor_id)
    return jsonify(contenedor.to_dict())


@app.route('/api/contenedores/<int:contenedor_id>', methods=['PUT'])
@login_required
def actualizar_contenedor(contenedor_id):
    """Actualiza información de un contenedor."""
    contenedor = Contenedor.query.get_or_404(contenedor_id)
    data = request.get_json()

    if contenedor.estado != 'abierto':
        return jsonify({'error': 'Solo se pueden editar contenedores abiertos'}), 400

    if 'cliente' in data:
        contenedor.cliente = data['cliente']
    if 'numero_contenedor' in data:
        contenedor.numero_contenedor = data['numero_contenedor']
    if 'tally_sheet' in data:
        contenedor.tally_sheet = data['tally_sheet']
    if 'seguro_1' in data:
        contenedor.seguro_1 = data['seguro_1']
    if 'seguro_2' in data:
        contenedor.seguro_2 = data['seguro_2']
    if 'seguro_3' in data:
        contenedor.seguro_3 = data['seguro_3']
    if 'notas' in data:
        contenedor.notas = data['notas']

    # Parsear fechas
    if 'fecha_carga' in data and data['fecha_carga']:
        try:
            contenedor.fecha_carga = datetime.strptime(data['fecha_carga'], '%Y-%m-%d').date()
        except:
            pass
    if 'fecha_zarpe' in data and data['fecha_zarpe']:
        try:
            contenedor.fecha_zarpe = datetime.strptime(data['fecha_zarpe'], '%Y-%m-%d').date()
        except:
            pass

    contenedor.updated_at = datetime.now()
    db.session.commit()

    return jsonify({
        'success': True,
        'contenedor': contenedor.to_dict(),
        'mensaje': 'Contenedor actualizado'
    })


@app.route('/api/contenedores/<int:contenedor_id>/agregar-bloque', methods=['POST'])
@login_required
def agregar_bloque_contenedor(contenedor_id):
    """Agrega un bloque encolado al contenedor."""
    contenedor = Contenedor.query.get_or_404(contenedor_id)
    data = request.get_json()

    if contenedor.estado != 'abierto':
        return jsonify({'error': 'El contenedor no está abierto'}), 400

    bloque_id = data.get('bloque_id')
    if not bloque_id:
        return jsonify({'error': 'Se requiere bloque_id'}), 400

    bloque = Bloque.query.get(bloque_id)
    if not bloque:
        return jsonify({'error': 'Bloque no encontrado'}), 404

    if bloque.estado != 'encolado':
        return jsonify({'error': 'Solo se pueden agregar bloques encolados'}), 400

    if bloque in contenedor.bloques:
        return jsonify({'error': 'El bloque ya está en este contenedor'}), 400

    # Verificar que el bloque no esté en otro contenedor
    if len(bloque.contenedores) > 0:
        return jsonify({'error': 'El bloque ya está asignado a otro contenedor'}), 400

    contenedor.bloques.append(bloque)
    contenedor.calcular_totales()
    db.session.commit()

    return jsonify({
        'success': True,
        'contenedor': contenedor.to_dict(),
        'mensaje': f'Bloque {bloque.codigo_qr} agregado al contenedor'
    })


@app.route('/api/contenedores/<int:contenedor_id>/agregar-bloques', methods=['POST'])
@login_required
def agregar_bloques_contenedor(contenedor_id):
    """Agrega múltiples bloques encolados al contenedor."""
    contenedor = Contenedor.query.get_or_404(contenedor_id)
    data = request.get_json()

    if contenedor.estado != 'abierto':
        return jsonify({'error': 'El contenedor no está abierto'}), 400

    bloque_ids = data.get('bloque_ids', [])
    if not bloque_ids:
        return jsonify({'error': 'Se requiere al menos un bloque_id'}), 400

    agregados = 0
    errores = []

    for bloque_id in bloque_ids:
        bloque = Bloque.query.get(bloque_id)
        if not bloque:
            errores.append(f'Bloque {bloque_id} no encontrado')
            continue
        if bloque.estado != 'encolado':
            errores.append(f'Bloque {bloque.codigo_qr} no está encolado')
            continue
        if bloque in contenedor.bloques:
            continue
        if len(bloque.contenedores) > 0:
            errores.append(f'Bloque {bloque.codigo_qr} ya asignado a otro contenedor')
            continue

        contenedor.bloques.append(bloque)
        agregados += 1

    contenedor.calcular_totales()
    db.session.commit()

    return jsonify({
        'success': True,
        'contenedor': contenedor.to_dict(),
        'agregados': agregados,
        'errores': errores,
        'mensaje': f'{agregados} bloques agregados al contenedor'
    })


@app.route('/api/contenedores/<int:contenedor_id>/remover-bloque', methods=['POST'])
@login_required
def remover_bloque_contenedor(contenedor_id):
    """Remueve un bloque del contenedor."""
    contenedor = Contenedor.query.get_or_404(contenedor_id)
    data = request.get_json()

    if contenedor.estado != 'abierto':
        return jsonify({'error': 'El contenedor no está abierto'}), 400

    bloque_id = data.get('bloque_id')
    if not bloque_id:
        return jsonify({'error': 'Se requiere bloque_id'}), 400

    bloque = Bloque.query.get(bloque_id)
    if not bloque:
        return jsonify({'error': 'Bloque no encontrado'}), 404

    if bloque not in contenedor.bloques:
        return jsonify({'error': 'El bloque no está en este contenedor'}), 400

    contenedor.bloques.remove(bloque)
    contenedor.calcular_totales()
    db.session.commit()

    return jsonify({
        'success': True,
        'contenedor': contenedor.to_dict(),
        'mensaje': f'Bloque {bloque.codigo_qr} removido del contenedor'
    })


@app.route('/api/contenedores/<int:contenedor_id>/cerrar', methods=['POST'])
@login_required
def cerrar_contenedor(contenedor_id):
    """Cierra un contenedor (no se pueden agregar más bloques)."""
    contenedor = Contenedor.query.get_or_404(contenedor_id)

    if contenedor.estado != 'abierto':
        return jsonify({'error': 'El contenedor no está abierto'}), 400

    if len(contenedor.bloques) == 0:
        return jsonify({'error': 'El contenedor no tiene bloques'}), 400

    contenedor.cerrar()
    db.session.commit()

    return jsonify({
        'success': True,
        'contenedor': contenedor.to_dict(),
        'mensaje': f'Contenedor {contenedor.codigo} cerrado con {contenedor.total_bloques} bloques'
    })


@app.route('/api/contenedores/<int:contenedor_id>/embarcar', methods=['POST'])
@login_required
def embarcar_contenedor(contenedor_id):
    """Marca un contenedor como embarcado."""
    contenedor = Contenedor.query.get_or_404(contenedor_id)

    if contenedor.estado == 'abierto':
        return jsonify({'error': 'Primero debe cerrar el contenedor'}), 400

    if contenedor.estado == 'embarcado':
        return jsonify({'error': 'El contenedor ya está embarcado'}), 400

    contenedor.embarcar()
    db.session.commit()

    return jsonify({
        'success': True,
        'contenedor': contenedor.to_dict(),
        'mensaje': f'Contenedor {contenedor.codigo} marcado como embarcado'
    })


@app.route('/api/bloques-encolados-disponibles', methods=['GET'])
@login_required
def listar_bloques_encolados_disponibles():
    """Lista bloques encolados que no están asignados a ningún contenedor."""
    bloques_encolados = Bloque.query.filter_by(estado='encolado').all()
    bloques_disponibles = [b.to_dict() for b in bloques_encolados if len(b.contenedores) == 0]
    return jsonify(bloques_disponibles)


@app.route('/api/reset-database', methods=['POST'])
@login_required
def reset_database():
    """Resetea la base de datos - SOLO PARA DESARROLLO."""
    data = request.json
    password = data.get('password', '')

    # Contraseña de seguridad
    if password != RESET_DB_PASSWORD:
        return jsonify({'error': 'Contraseña incorrecta'}), 403

    try:
        # Eliminar todos los datos en orden correcto (por dependencias)
        db.session.execute(contenedor_bloques.delete())
        db.session.execute(lote_coches.delete())
        Movimiento.query.delete()
        ProcesoLote.query.delete()
        Bloque.query.delete()
        Contenedor.query.delete()
        Lote.query.delete()
        Coche.query.delete()
        db.session.commit()

        return jsonify({
            'success': True,
            'mensaje': 'Base de datos reseteada correctamente. Las etapas se mantienen.'
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@app.route('/reset-db')
@login_required
def reset_db_page():
    """Página para resetear la base de datos."""
    return '''
    <!DOCTYPE html>
    <html>
    <head>
        <title>Reset Database</title>
        <style>
            body { font-family: Arial; max-width: 500px; margin: 50px auto; padding: 20px; }
            .warning { background: #fee; border: 2px solid #f00; padding: 20px; border-radius: 8px; margin-bottom: 20px; }
            input { width: 100%; padding: 10px; margin: 10px 0; box-sizing: border-box; }
            button { background: #dc3545; color: white; padding: 12px 24px; border: none; border-radius: 4px; cursor: pointer; width: 100%; }
            button:hover { background: #c82333; }
            .result { margin-top: 20px; padding: 15px; border-radius: 8px; }
            .success { background: #d4edda; color: #155724; }
            .error { background: #f8d7da; color: #721c24; }
        </style>
    </head>
    <body>
        <h1>⚠️ Reset Database</h1>
        <div class="warning">
            <strong>ADVERTENCIA:</strong> Esta acción eliminará TODOS los datos:
            <ul>
                <li>Coches</li>
                <li>Lotes</li>
                <li>Bloques</li>
                <li>Contenedores</li>
                <li>Movimientos</li>
                <li>Procesos/Plantillas</li>
            </ul>
            <p>Las etapas (Madera Verde, Secado, etc.) se mantienen.</p>
        </div>
        <input type="password" id="password" placeholder="Ingrese la contraseña">
        <button onclick="resetDB()">🗑️ BORRAR TODA LA BASE DE DATOS</button>
        <div id="result"></div>
        <script>
            async function resetDB() {
                const password = document.getElementById('password').value;
                if (!password) { alert('Ingrese la contraseña'); return; }
                if (!confirm('¿ESTÁ SEGURO? Esta acción NO se puede deshacer.')) return;

                try {
                    const response = await fetch('/api/reset-database', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ password: password })
                    });
                    const data = await response.json();
                    const resultDiv = document.getElementById('result');

                    if (data.success) {
                        resultDiv.className = 'result success';
                        resultDiv.innerHTML = '✅ ' + data.mensaje + '<br><br><a href="/">Ir al Dashboard</a>';
                    } else {
                        resultDiv.className = 'result error';
                        resultDiv.innerHTML = '❌ Error: ' + data.error;
                    }
                } catch (error) {
                    document.getElementById('result').className = 'result error';
                    document.getElementById('result').innerHTML = '❌ Error: ' + error.message;
                }
            }
        </script>
    </body>
    </html>
    '''


# ==================== ACCESO MAESTRO - DATOS HISTORICOS ====================

@app.route('/maestro')
@login_required
def acceso_maestro():
    """Página de acceso maestro para ingreso masivo de datos históricos."""
    etapas = Etapa.query.order_by(Etapa.orden).all()
    fecha_hoy = datetime.now().strftime('%Y-%m-%d')

    return render_template('maestro.html',
                           etapas=etapas,
                           fecha_hoy=fecha_hoy,
                           espesores=ESPESORES,
                           largos=LARGOS,
                           largos_produccion=LARGOS_PRODUCCION)


@app.route('/api/maestro/coches', methods=['POST'])
@login_required
def maestro_crear_coches():
    """Crea múltiples coches masivamente para datos históricos."""
    data = request.get_json()

    cantidad = data.get('cantidad', 1)
    if cantidad > 200:
        cantidad = 200

    fecha_str = data.get('fecha_creacion')
    if fecha_str:
        try:
            fecha_creacion = datetime.strptime(fecha_str, '%Y-%m-%d')
        except:
            fecha_creacion = datetime.now()
    else:
        fecha_creacion = datetime.now()

    etapa_destino_id = data.get('etapa_destino_id')
    if etapa_destino_id:
        etapa = Etapa.query.get(etapa_destino_id)
        if not etapa:
            return jsonify({'success': False, 'error': 'Etapa no válida'}), 400
    else:
        etapa = Etapa.query.filter_by(orden=1).first()
        if not etapa:
            return jsonify({'success': False, 'error': 'No existe la etapa Madera Verde'}), 500

    proveedor = data.get('proveedor', '')
    camara = data.get('camara')
    if camara == '':
        camara = None
    elif camara:
        camara = int(camara)
    lote_secado = data.get('lote_secado', '')

    espesor_1 = data.get('espesor_1')
    largo_1 = data.get('largo_1')
    plantillas_1 = data.get('plantillas_1', 0)

    coches_creados = []
    total_bft = 0

    # Obtener siguiente número
    siguiente_num = 1
    for c in Coche.query.all():
        num = extraer_numero_coche(c.codigo_qr)
        if num and num >= siguiente_num:
            siguiente_num = num + 1

    for i in range(cantidad):
        codigo_qr = generar_codigo_coche_consecutivo(siguiente_num)
        while Coche.query.filter_by(codigo_qr=codigo_qr).first():
            siguiente_num += 1
            codigo_qr = generar_codigo_coche_consecutivo(siguiente_num)

        coche = Coche(
            codigo_qr=codigo_qr,
            registrador='Maestro',
            proveedor=proveedor,
            camara=camara,
            lote_secado=lote_secado,
            espesor_1=espesor_1 if espesor_1 else None,
            largo_1=largo_1 if largo_1 else None,
            plantillas_1=float(plantillas_1) if plantillas_1 else 0,
            etapa_actual_id=etapa.id,
            created_at=fecha_creacion
        )
        coche.calcular_bft()
        total_bft += coche.total_bft or 0

        db.session.add(coche)
        db.session.flush()

        # Registrar movimiento
        movimiento = Movimiento(
            coche_id=coche.id,
            etapa_origen_id=None,
            etapa_destino_id=etapa.id,
            usuario='Maestro',
            notas='Creado vía Acceso Maestro',
            timestamp=fecha_creacion
        )
        db.session.add(movimiento)

        coches_creados.append(codigo_qr)
        siguiente_num += 1

    db.session.commit()

    return jsonify({
        'success': True,
        'total_creados': len(coches_creados),
        'total_bft': total_bft,
        'mensaje': f'{len(coches_creados)} coches creados exitosamente'
    })


@app.route('/api/maestro/lotes', methods=['POST'])
@login_required
def maestro_crear_lote():
    """Crea un lote con coches generados automáticamente."""
    data = request.get_json()

    fecha_str = data.get('fecha_creacion')
    if fecha_str:
        try:
            fecha_creacion = datetime.strptime(fecha_str, '%Y-%m-%d')
        except:
            fecha_creacion = datetime.now()
    else:
        fecha_creacion = datetime.now()

    turno = data.get('turno', 'Diurno')
    cantidad_coches = data.get('cantidad_coches', 5)
    bft_por_coche = data.get('bft_por_coche', 500)

    # Generar código de lote
    siguiente_num = 1
    for l in Lote.query.all():
        num = extraer_numero_lote(l.codigo_qr)
        if num and num >= siguiente_num:
            siguiente_num = num + 1

    codigo_lote = generar_codigo_lote_consecutivo(siguiente_num)
    while Lote.query.filter_by(codigo_qr=codigo_lote).first():
        siguiente_num += 1
        codigo_lote = generar_codigo_lote_consecutivo(siguiente_num)

    # Crear el lote
    lote = Lote(
        codigo_qr=codigo_lote,
        turno=turno,
        estado='disponible',
        total_bft=cantidad_coches * bft_por_coche,
        created_at=fecha_creacion
    )
    db.session.add(lote)
    db.session.flush()

    # Obtener etapa de producción (orden 4)
    etapa_produccion = Etapa.query.filter_by(orden=4).first()
    if not etapa_produccion:
        etapa_produccion = Etapa.query.first()

    # Crear coches para el lote
    siguiente_num_coche = 1
    for c in Coche.query.all():
        num = extraer_numero_coche(c.codigo_qr)
        if num and num >= siguiente_num_coche:
            siguiente_num_coche = num + 1

    for i in range(cantidad_coches):
        codigo_coche = generar_codigo_coche_consecutivo(siguiente_num_coche)
        while Coche.query.filter_by(codigo_qr=codigo_coche).first():
            siguiente_num_coche += 1
            codigo_coche = generar_codigo_coche_consecutivo(siguiente_num_coche)

        coche = Coche(
            codigo_qr=codigo_coche,
            registrador='Maestro',
            etapa_actual_id=etapa_produccion.id,
            created_at=fecha_creacion
        )
        # Asignar BFT fijo
        coche.total_bft = bft_por_coche

        db.session.add(coche)
        db.session.flush()

        lote.coches.append(coche)
        siguiente_num_coche += 1

    db.session.commit()

    return jsonify({
        'success': True,
        'codigo': codigo_lote,
        'total_bft': lote.total_bft,
        'mensaje': f'Lote {codigo_lote} creado con {cantidad_coches} coches'
    })


@app.route('/api/maestro/bloques-presentados', methods=['POST'])
@login_required
def maestro_crear_bloques_presentados():
    """Crea múltiples bloques presentados masivamente."""
    data = request.get_json()

    cantidad = data.get('cantidad', 10)
    if cantidad > 100:
        cantidad = 100

    fecha_str = data.get('fecha')
    if fecha_str:
        try:
            fecha = datetime.strptime(fecha_str, '%Y-%m-%d').date()
        except:
            fecha = datetime.now().date()
    else:
        fecha = datetime.now().date()

    turno = data.get('turno', 'Diurno')
    calidad = data.get('calidad', 'R8 Estándar')
    largo = data.get('largo', 96)
    peso = data.get('peso', 45)
    secuencia_inicial = data.get('secuencia_inicial', 1)
    empatado = data.get('empatado', False)

    # Obtener siguiente número
    siguiente_num = 1
    for b in Bloque.query.all():
        num = extraer_numero_bloque(b.codigo_qr)
        if num and num >= siguiente_num:
            siguiente_num = num + 1

    bloques_creados = []
    total_bft = 0

    for i in range(cantidad):
        codigo_qr = generar_codigo_bloque_consecutivo(siguiente_num)
        while Bloque.query.filter_by(codigo_qr=codigo_qr).first():
            siguiente_num += 1
            codigo_qr = generar_codigo_bloque_consecutivo(siguiente_num)

        bloque = Bloque(
            codigo_qr=codigo_qr,
            fecha=fecha,
            turno=turno,
            calidad=calidad,
            secuencia=str(secuencia_inicial + i),
            largo=int(largo),
            peso=float(peso),
            empatado=empatado,
            estado='presentado',
            created_at=datetime.combine(fecha, datetime.min.time())
        )
        bloque.calcular_bft()
        bloque.calcular_densidad_presentado()
        total_bft += bloque.bft or 0

        db.session.add(bloque)
        bloques_creados.append(codigo_qr)
        siguiente_num += 1

    db.session.commit()

    return jsonify({
        'success': True,
        'total_creados': len(bloques_creados),
        'total_bft': total_bft,
        'mensaje': f'{len(bloques_creados)} bloques presentados creados'
    })


@app.route('/api/maestro/bloques-encolados', methods=['POST'])
@login_required
def maestro_crear_bloques_encolados():
    """Crea múltiples bloques ya encolados masivamente."""
    data = request.get_json()

    cantidad = data.get('cantidad', 10)
    if cantidad > 100:
        cantidad = 100

    fecha_pres_str = data.get('fecha_presentado')
    fecha_enc_str = data.get('fecha_encolado')

    if fecha_pres_str:
        try:
            fecha_presentado = datetime.strptime(fecha_pres_str, '%Y-%m-%d').date()
        except:
            fecha_presentado = datetime.now().date()
    else:
        fecha_presentado = datetime.now().date()

    if fecha_enc_str:
        try:
            fecha_encolado = datetime.strptime(fecha_enc_str, '%Y-%m-%d')
        except:
            fecha_encolado = datetime.now()
    else:
        fecha_encolado = datetime.now()

    turno = data.get('turno', 'Diurno')
    calidad = data.get('calidad', 'R8 Estándar')
    largo = data.get('largo', 96)
    peso = data.get('peso', 44)
    secuencia_inicial = data.get('secuencia_inicial', 1)

    # Obtener siguiente número
    siguiente_num = 1
    for b in Bloque.query.all():
        num = extraer_numero_bloque(b.codigo_qr)
        if num and num >= siguiente_num:
            siguiente_num = num + 1

    bloques_creados = []
    total_bft = 0

    for i in range(cantidad):
        codigo_qr = generar_codigo_bloque_consecutivo(siguiente_num)
        while Bloque.query.filter_by(codigo_qr=codigo_qr).first():
            siguiente_num += 1
            codigo_qr = generar_codigo_bloque_consecutivo(siguiente_num)

        bloque = Bloque(
            codigo_qr=codigo_qr,
            fecha=fecha_presentado,
            turno=turno,
            calidad=calidad,
            secuencia=str(secuencia_inicial + i),
            largo=int(largo),
            peso=float(peso) + 1,  # Peso presentado un poco mayor
            peso_encolado=float(peso),
            empatado=False,
            estado='encolado',
            fecha_encolado=fecha_encolado,
            created_at=datetime.combine(fecha_presentado, datetime.min.time())
        )
        bloque.calcular_bft()
        bloque.calcular_densidad_presentado()
        bloque.calcular_densidad_encolado()
        total_bft += bloque.bft or 0

        db.session.add(bloque)
        bloques_creados.append(codigo_qr)
        siguiente_num += 1

    db.session.commit()

    return jsonify({
        'success': True,
        'total_creados': len(bloques_creados),
        'total_bft': total_bft,
        'mensaje': f'{len(bloques_creados)} bloques encolados creados'
    })


@app.route('/api/maestro/contenedores', methods=['POST'])
@login_required
def maestro_crear_contenedor():
    """Crea un contenedor y asigna bloques encolados disponibles."""
    data = request.get_json()

    fecha_str = data.get('fecha')
    if fecha_str:
        try:
            fecha = datetime.strptime(fecha_str, '%Y-%m-%d').date()
        except:
            fecha = datetime.now().date()
    else:
        fecha = datetime.now().date()

    nombre = data.get('nombre', '')
    cantidad_bloques = data.get('cantidad_bloques', 50)
    estado = data.get('estado', 'abierto')

    # Generar código
    siguiente_num = 1
    for c in Contenedor.query.all():
        num = extraer_numero_contenedor(c.codigo)
        if num and num >= siguiente_num:
            siguiente_num = num + 1

    codigo = generar_codigo_contenedor_consecutivo(siguiente_num)
    while Contenedor.query.filter_by(codigo=codigo).first():
        siguiente_num += 1
        codigo = generar_codigo_contenedor_consecutivo(siguiente_num)

    contenedor = Contenedor(
        codigo=codigo,
        cliente=nombre,
        fecha_carga=fecha,
        estado=estado,
        creado_por='Maestro',
        created_at=datetime.combine(fecha, datetime.min.time())
    )
    db.session.add(contenedor)
    db.session.flush()

    # Buscar bloques encolados disponibles
    bloques_disponibles = Bloque.query.filter_by(estado='encolado').all()
    bloques_sin_contenedor = [b for b in bloques_disponibles if len(b.contenedores) == 0]

    bloques_asignados = 0
    for bloque in bloques_sin_contenedor[:cantidad_bloques]:
        contenedor.bloques.append(bloque)
        bloques_asignados += 1

    contenedor.calcular_totales()
    db.session.commit()

    return jsonify({
        'success': True,
        'codigo': codigo,
        'total_creados': 1,
        'bloques_asignados': bloques_asignados,
        'mensaje': f'Contenedor {codigo} creado con {bloques_asignados} bloques'
    })


# ==================== SISTEMA DE BACKUP ====================

import json
import csv
import zipfile
from io import StringIO, BytesIO

# Carpeta de OneDrive para backups (configurable via variable de entorno)
BACKUP_ONEDRIVE_PATH = os.environ.get('BACKUP_ONEDRIVE_PATH',
    r'C:\Users\nicol\OneDrive\Documents\Dashboards Proyectos\Sky Composite\Backups')


@app.route('/backup')
@login_required
def backup_page():
    """Página de gestión de backups."""
    return render_template('backup.html')


@app.route('/api/backup/completo')
@login_required
def backup_completo_json():
    """
    Genera un JSON completo con TODA la estructura de la base de datos.
    Este archivo permite restaurar/migrar la BD completa a otro servidor.
    """
    backup_data = {
        'metadata': {
            'version': '1.0',
            'fecha_backup': datetime.now().isoformat(),
            'descripcion': 'Backup completo de Sky Composite - Inventario QR',
            'tablas': ['etapas', 'coches', 'movimientos', 'lotes', 'lote_coches',
                      'bloques', 'proceso_lotes', 'contenedores', 'contenedor_bloques']
        },
        'etapas': [],
        'coches': [],
        'movimientos': [],
        'lotes': [],
        'lote_coches': [],  # Relación muchos a muchos
        'bloques': [],
        'proceso_lotes': [],
        'contenedores': [],
        'contenedor_bloques': []  # Relación muchos a muchos
    }

    # Etapas
    for e in Etapa.query.all():
        backup_data['etapas'].append({
            'id': e.id,
            'nombre': e.nombre,
            'orden': e.orden,
            'color': e.color,
            'icono': e.icono
        })

    # Coches (con todos los campos)
    for c in Coche.query.all():
        backup_data['coches'].append({
            'id': c.id,
            'codigo_qr': c.codigo_qr,
            'registrador': c.registrador,
            'proveedor': c.proveedor,
            'numero_viaje': c.numero_viaje,
            'camara': c.camara,
            'lote_secado': c.lote_secado,
            'espesor_1': c.espesor_1,
            'largo_1': c.largo_1,
            'plantillas_1': c.plantillas_1,
            'bft_1': c.bft_1,
            'espesor_2': c.espesor_2,
            'largo_2': c.largo_2,
            'plantillas_2': c.plantillas_2,
            'bft_2': c.bft_2,
            'espesor_3': c.espesor_3,
            'largo_3': c.largo_3,
            'plantillas_3': c.plantillas_3,
            'bft_3': c.bft_3,
            'total_bft': c.total_bft,
            'etapa_actual_id': c.etapa_actual_id,
            'notas': c.notas,
            'created_at': c.created_at.isoformat() if c.created_at else None,
            'updated_at': c.updated_at.isoformat() if c.updated_at else None
        })

    # Movimientos
    for m in Movimiento.query.all():
        backup_data['movimientos'].append({
            'id': m.id,
            'coche_id': m.coche_id,
            'etapa_origen_id': m.etapa_origen_id,
            'etapa_destino_id': m.etapa_destino_id,
            'usuario': m.usuario,
            'timestamp': m.timestamp.isoformat() if m.timestamp else None,
            'notas': m.notas
        })

    # Lotes
    for l in Lote.query.all():
        backup_data['lotes'].append({
            'id': l.id,
            'codigo_qr': l.codigo_qr,
            'total_bft': l.total_bft,
            'bft_usado': l.bft_usado,
            'cantidad_coches': l.cantidad_coches,
            'estado': l.estado,
            'turno': l.turno,
            'creado_por': l.creado_por,
            'notas': l.notas,
            'desperdicio_bft': l.desperdicio_bft,
            'desperdicio_porcentaje': l.desperdicio_porcentaje,
            'created_at': l.created_at.isoformat() if l.created_at else None,
            'fecha_inicio_proceso': l.fecha_inicio_proceso.isoformat() if l.fecha_inicio_proceso else None,
            'fecha_finalizado': l.fecha_finalizado.isoformat() if l.fecha_finalizado else None
        })

    # Relación Lote-Coches
    for l in Lote.query.all():
        for c in l.coches:
            backup_data['lote_coches'].append({
                'lote_id': l.id,
                'coche_id': c.id
            })

    # Bloques
    for b in Bloque.query.all():
        backup_data['bloques'].append({
            'id': b.id,
            'codigo_qr': b.codigo_qr,
            'lote_id': b.lote_id,
            'fecha': b.fecha.isoformat() if b.fecha else None,
            'turno': b.turno,
            'calidad': b.calidad,
            'secuencia': b.secuencia,
            'largo': b.largo,
            'peso': b.peso,
            'densidad': b.densidad,
            'bft': b.bft,
            'empatado': b.empatado,
            'estado': b.estado,
            'peso_encolado': b.peso_encolado,
            'densidad_encolado': b.densidad_encolado,
            'created_at': b.created_at.isoformat() if b.created_at else None,
            'updated_at': b.updated_at.isoformat() if b.updated_at else None,
            'fecha_encolado': b.fecha_encolado.isoformat() if b.fecha_encolado else None,
            'notas': b.notas
        })

    # Proceso Lotes
    for p in ProcesoLote.query.all():
        backup_data['proceso_lotes'].append({
            'id': p.id,
            'lote_id': p.lote_id,
            'largo': p.largo,
            'ancho': p.ancho,
            'alto': p.alto,
            'bft_calculado': p.bft_calculado,
            'calidad': p.calidad,
            'procesado_por': p.procesado_por,
            'created_at': p.created_at.isoformat() if p.created_at else None,
            'notas': p.notas
        })

    # Contenedores
    for cont in Contenedor.query.all():
        backup_data['contenedores'].append({
            'id': cont.id,
            'codigo': cont.codigo,
            'cliente': cont.cliente,
            'numero_contenedor': cont.numero_contenedor,
            'fecha_carga': cont.fecha_carga.isoformat() if cont.fecha_carga else None,
            'fecha_zarpe': cont.fecha_zarpe.isoformat() if cont.fecha_zarpe else None,
            'tally_sheet': cont.tally_sheet,
            'seguro_1': cont.seguro_1,
            'seguro_2': cont.seguro_2,
            'seguro_3': cont.seguro_3,
            'estado': cont.estado,
            'total_bloques': cont.total_bloques,
            'total_bft': cont.total_bft,
            'total_m3': cont.total_m3,
            'creado_por': cont.creado_por,
            'notas': cont.notas,
            'created_at': cont.created_at.isoformat() if cont.created_at else None,
            'updated_at': cont.updated_at.isoformat() if cont.updated_at else None,
            'fecha_cierre': cont.fecha_cierre.isoformat() if cont.fecha_cierre else None
        })

    # Relación Contenedor-Bloques
    for cont in Contenedor.query.all():
        for b in cont.bloques:
            backup_data['contenedor_bloques'].append({
                'contenedor_id': cont.id,
                'bloque_id': b.id
            })

    # Agregar estadísticas
    backup_data['estadisticas'] = {
        'total_etapas': len(backup_data['etapas']),
        'total_coches': len(backup_data['coches']),
        'total_movimientos': len(backup_data['movimientos']),
        'total_lotes': len(backup_data['lotes']),
        'total_bloques': len(backup_data['bloques']),
        'total_proceso_lotes': len(backup_data['proceso_lotes']),
        'total_contenedores': len(backup_data['contenedores']),
        'bft_total_coches': sum(c['total_bft'] or 0 for c in backup_data['coches']),
        'bft_total_bloques': sum(b['bft'] or 0 for b in backup_data['bloques'])
    }

    # Generar archivo JSON
    json_content = json.dumps(backup_data, indent=2, ensure_ascii=False)

    response = app.response_class(
        response=json_content,
        status=200,
        mimetype='application/json'
    )
    fecha_str = datetime.now().strftime('%Y%m%d_%H%M%S')
    response.headers['Content-Disposition'] = f'attachment; filename=backup_completo_{fecha_str}.json'

    return response


@app.route('/api/backup/csv')
@login_required
def backup_csv_zip():
    """
    Genera un ZIP con archivos CSV de todas las tablas.
    Ideal para revisar datos en Excel/Power BI.
    Incluye campos de fecha separados para facilitar análisis.
    """
    memoria_zip = BytesIO()

    with zipfile.ZipFile(memoria_zip, 'w', zipfile.ZIP_DEFLATED) as zf:

        # CSV de Etapas (catálogo)
        etapas_csv = StringIO()
        writer = csv.writer(etapas_csv)
        writer.writerow(['ID', 'Nombre', 'Orden', 'Color', 'Icono'])
        for e in Etapa.query.order_by(Etapa.orden).all():
            writer.writerow([e.id, e.nombre, e.orden, e.color, e.icono])
        zf.writestr('etapas.csv', etapas_csv.getvalue())

        # CSV de Coches (Recepción completa)
        coches_csv = StringIO()
        writer = csv.writer(coches_csv)
        writer.writerow(['ID', 'Código QR', 'Registrador', 'Proveedor', 'Número Viaje', 'Cámara', 'Lote Secado',
                        'Espesor 1', 'Largo 1', 'Plantillas 1', 'BFT 1',
                        'Espesor 2', 'Largo 2', 'Plantillas 2', 'BFT 2',
                        'Espesor 3', 'Largo 3', 'Plantillas 3', 'BFT 3',
                        'Total BFT', 'Etapa Actual ID', 'Etapa Actual', 'Notas',
                        'Fecha Creación', 'Año', 'Mes', 'Día', 'Hora',
                        'Fecha Actualización'])
        for c in Coche.query.all():
            etapa_nombre = c.etapa_actual.nombre if c.etapa_actual else ''
            fecha_c = c.created_at
            writer.writerow([
                c.id, c.codigo_qr, c.registrador, c.proveedor, c.numero_viaje, c.camara, c.lote_secado,
                c.espesor_1, c.largo_1, c.plantillas_1, c.bft_1,
                c.espesor_2, c.largo_2, c.plantillas_2, c.bft_2,
                c.espesor_3, c.largo_3, c.plantillas_3, c.bft_3,
                c.total_bft, c.etapa_actual_id, etapa_nombre, c.notas,
                fecha_c.strftime('%Y-%m-%d %H:%M:%S') if fecha_c else '',
                fecha_c.year if fecha_c else '',
                fecha_c.month if fecha_c else '',
                fecha_c.day if fecha_c else '',
                fecha_c.strftime('%H:%M') if fecha_c else '',
                c.updated_at.strftime('%Y-%m-%d %H:%M:%S') if c.updated_at else ''
            ])
        zf.writestr('coches.csv', coches_csv.getvalue())

        # CSV de Lotes
        lotes_csv = StringIO()
        writer = csv.writer(lotes_csv)
        writer.writerow(['ID', 'Código QR', 'Total BFT', 'BFT Usado', 'BFT Disponible', 'Cantidad Coches',
                        'Estado', 'Turno', 'Creado Por', 'Desperdicio BFT', 'Desperdicio %',
                        'Fecha Creación', 'Año', 'Mes', 'Día',
                        'Fecha Inicio Proceso', 'Fecha Finalizado', 'Notas'])
        for l in Lote.query.all():
            fecha_c = l.created_at
            writer.writerow([
                l.id, l.codigo_qr, l.total_bft, l.bft_usado, l.bft_disponible, l.cantidad_coches,
                l.estado, l.turno, l.creado_por, l.desperdicio_bft, l.desperdicio_porcentaje,
                fecha_c.strftime('%Y-%m-%d %H:%M:%S') if fecha_c else '',
                fecha_c.year if fecha_c else '',
                fecha_c.month if fecha_c else '',
                fecha_c.day if fecha_c else '',
                l.fecha_inicio_proceso.strftime('%Y-%m-%d %H:%M:%S') if l.fecha_inicio_proceso else '',
                l.fecha_finalizado.strftime('%Y-%m-%d %H:%M:%S') if l.fecha_finalizado else '',
                l.notas
            ])
        zf.writestr('lotes.csv', lotes_csv.getvalue())

        # CSV de Lote-Coches (relación para Power BI)
        lote_coches_csv = StringIO()
        writer = csv.writer(lote_coches_csv)
        writer.writerow(['Lote ID', 'Lote Código', 'Coche ID', 'Coche Código', 'Coche BFT'])
        for l in Lote.query.all():
            for c in l.coches:
                writer.writerow([l.id, l.codigo_qr, c.id, c.codigo_qr, c.total_bft])
        zf.writestr('lote_coches.csv', lote_coches_csv.getvalue())

        # CSV de Bloques
        bloques_csv = StringIO()
        writer = csv.writer(bloques_csv)
        writer.writerow(['ID', 'Código QR', 'Lote ID', 'Lote Código', 'Fecha', 'Año', 'Mes', 'Día',
                        'Turno', 'Calidad', 'Secuencia', 'Largo (pulg)', 'Peso (kg)', 'Densidad', 'BFT',
                        'Empatado', 'Estado', 'Peso Encolado', 'Densidad Encolado', 'Fecha Encolado',
                        'Fecha Creación', 'Notas'])
        for b in Bloque.query.all():
            lote_codigo = b.lote.codigo_qr if b.lote else ''
            fecha_b = b.fecha
            writer.writerow([
                b.id, b.codigo_qr, b.lote_id, lote_codigo,
                fecha_b.strftime('%Y-%m-%d') if fecha_b else '',
                fecha_b.year if fecha_b else '',
                fecha_b.month if fecha_b else '',
                fecha_b.day if fecha_b else '',
                b.turno, b.calidad, b.secuencia, b.largo, b.peso, b.densidad, b.bft,
                'Sí' if b.empatado else 'No', b.estado, b.peso_encolado, b.densidad_encolado,
                b.fecha_encolado.strftime('%Y-%m-%d %H:%M:%S') if b.fecha_encolado else '',
                b.created_at.strftime('%Y-%m-%d %H:%M:%S') if b.created_at else '',
                b.notas
            ])
        zf.writestr('bloques.csv', bloques_csv.getvalue())

        # CSV de Contenedores
        contenedores_csv = StringIO()
        writer = csv.writer(contenedores_csv)
        writer.writerow(['ID', 'Código', 'Cliente', 'Número Contenedor', 'Fecha Carga', 'Año Carga', 'Mes Carga',
                        'Fecha Zarpe', 'Tally Sheet', 'Seguro 1', 'Seguro 2', 'Seguro 3', 'Estado',
                        'Total Bloques', 'Total BFT', 'Total M³', 'Creado Por', 'Fecha Creación', 'Fecha Cierre', 'Notas'])
        for cont in Contenedor.query.all():
            fecha_carga = cont.fecha_carga
            writer.writerow([
                cont.id, cont.codigo, cont.cliente, cont.numero_contenedor,
                fecha_carga.strftime('%Y-%m-%d') if fecha_carga else '',
                fecha_carga.year if fecha_carga else '',
                fecha_carga.month if fecha_carga else '',
                cont.fecha_zarpe.strftime('%Y-%m-%d') if cont.fecha_zarpe else '',
                cont.tally_sheet, cont.seguro_1, cont.seguro_2, cont.seguro_3, cont.estado,
                cont.total_bloques, cont.total_bft, cont.total_m3, cont.creado_por,
                cont.created_at.strftime('%Y-%m-%d %H:%M:%S') if cont.created_at else '',
                cont.fecha_cierre.strftime('%Y-%m-%d %H:%M:%S') if cont.fecha_cierre else '',
                cont.notas
            ])
        zf.writestr('contenedores.csv', contenedores_csv.getvalue())

        # CSV de Contenedor-Bloques (relación para Power BI)
        contenedor_bloques_csv = StringIO()
        writer = csv.writer(contenedor_bloques_csv)
        writer.writerow(['Contenedor ID', 'Contenedor Código', 'Bloque ID', 'Bloque Código', 'Bloque Largo', 'Bloque BFT'])
        for cont in Contenedor.query.all():
            for b in cont.bloques:
                writer.writerow([cont.id, cont.codigo, b.id, b.codigo_qr, b.largo, b.bft])
        zf.writestr('contenedor_bloques.csv', contenedor_bloques_csv.getvalue())

        # CSV de Movimientos (historial de cambios de etapa)
        movimientos_csv = StringIO()
        writer = csv.writer(movimientos_csv)
        writer.writerow(['ID', 'Coche ID', 'Coche Código', 'Etapa Origen ID', 'Etapa Origen',
                        'Etapa Destino ID', 'Etapa Destino', 'Usuario', 'Fecha', 'Año', 'Mes', 'Día', 'Hora', 'Notas'])
        for m in Movimiento.query.all():
            coche_codigo = m.coche.codigo_qr if m.coche else ''
            origen = m.etapa_origen.nombre if m.etapa_origen else 'Nuevo'
            destino = m.etapa_destino.nombre if m.etapa_destino else ''
            fecha_m = m.timestamp
            writer.writerow([
                m.id, m.coche_id, coche_codigo,
                m.etapa_origen_id, origen,
                m.etapa_destino_id, destino,
                m.usuario,
                fecha_m.strftime('%Y-%m-%d %H:%M:%S') if fecha_m else '',
                fecha_m.year if fecha_m else '',
                fecha_m.month if fecha_m else '',
                fecha_m.day if fecha_m else '',
                fecha_m.strftime('%H:%M') if fecha_m else '',
                m.notas
            ])
        zf.writestr('movimientos.csv', movimientos_csv.getvalue())

        # CSV de Proceso Lotes (Madera Plantillada)
        proceso_csv = StringIO()
        writer = csv.writer(proceso_csv)
        writer.writerow(['ID', 'Lote ID', 'Lote Código', 'Largo', 'Ancho', 'Alto', 'BFT Calculado',
                        'Calidad', 'Procesado Por', 'Fecha', 'Año', 'Mes', 'Día', 'Notas'])
        for p in ProcesoLote.query.all():
            lote_codigo = p.lote.codigo_qr if p.lote else ''
            fecha_p = p.created_at
            writer.writerow([
                p.id, p.lote_id, lote_codigo, p.largo, p.ancho, p.alto, p.bft_calculado,
                p.calidad, p.procesado_por,
                fecha_p.strftime('%Y-%m-%d %H:%M:%S') if fecha_p else '',
                fecha_p.year if fecha_p else '',
                fecha_p.month if fecha_p else '',
                fecha_p.day if fecha_p else '',
                p.notas
            ])
        zf.writestr('proceso_lotes.csv', proceso_csv.getvalue())

        # CSV Resumen General
        resumen_csv = StringIO()
        writer = csv.writer(resumen_csv)
        writer.writerow(['Tabla', 'Total Registros', 'BFT Total'])
        writer.writerow(['Etapas', Etapa.query.count(), '-'])
        writer.writerow(['Coches', Coche.query.count(), sum(c.total_bft or 0 for c in Coche.query.all())])
        writer.writerow(['Lotes', Lote.query.count(), sum(l.total_bft or 0 for l in Lote.query.all())])
        writer.writerow(['Bloques Total', Bloque.query.count(), sum(b.bft or 0 for b in Bloque.query.all())])
        writer.writerow(['Bloques Presentados', Bloque.query.filter_by(estado='presentado').count(),
                        sum(b.bft or 0 for b in Bloque.query.filter_by(estado='presentado').all())])
        writer.writerow(['Bloques Encolados', Bloque.query.filter_by(estado='encolado').count(),
                        sum(b.bft or 0 for b in Bloque.query.filter_by(estado='encolado').all())])
        writer.writerow(['Contenedores', Contenedor.query.count(), sum(c.total_bft or 0 for c in Contenedor.query.all())])
        writer.writerow(['Movimientos', Movimiento.query.count(), '-'])
        writer.writerow(['Proceso Lotes', ProcesoLote.query.count(), sum(p.bft_calculado or 0 for p in ProcesoLote.query.all())])
        writer.writerow([])
        writer.writerow(['Fecha Backup', datetime.now().strftime('%Y-%m-%d %H:%M:%S'), ''])
        zf.writestr('_RESUMEN.csv', resumen_csv.getvalue())

        # CSV de Coches por Etapa (útil para dashboard)
        etapa_resumen_csv = StringIO()
        writer = csv.writer(etapa_resumen_csv)
        writer.writerow(['Etapa', 'Orden', 'Cantidad Coches', 'Total BFT'])
        for e in Etapa.query.order_by(Etapa.orden).all():
            coches_etapa = Coche.query.filter_by(etapa_actual_id=e.id).all()
            writer.writerow([e.nombre, e.orden, len(coches_etapa), sum(c.total_bft or 0 for c in coches_etapa)])
        zf.writestr('resumen_por_etapa.csv', etapa_resumen_csv.getvalue())

    memoria_zip.seek(0)

    fecha_str = datetime.now().strftime('%Y%m%d_%H%M%S')
    response = send_file(
        memoria_zip,
        mimetype='application/zip',
        as_attachment=True,
        download_name=f'backup_csv_{fecha_str}.zip'
    )

    return response


@app.route('/api/backup/auto', methods=['POST'])
def backup_automatico():
    """
    Endpoint para backup automático (llamado por Task Scheduler).
    Guarda archivos en la carpeta de OneDrive configurada.
    Requiere token de seguridad.
    """
    # Token de seguridad para backups automáticos
    token = request.headers.get('X-Backup-Token') or request.args.get('token')
    expected_token = os.environ.get('BACKUP_TOKEN', 'skycomposite_backup_2024')

    if token != expected_token:
        return jsonify({'error': 'Token inválido'}), 403

    try:
        # Crear carpeta si no existe
        if not os.path.exists(BACKUP_ONEDRIVE_PATH):
            os.makedirs(BACKUP_ONEDRIVE_PATH)

        fecha_str = datetime.now().strftime('%Y%m%d_%H%M%S')
        momento = 'AM' if datetime.now().hour < 12 else 'PM'

        # Generar backup JSON
        backup_data = generar_backup_data()
        json_path = os.path.join(BACKUP_ONEDRIVE_PATH, f'backup_{fecha_str}_{momento}.json')
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(backup_data, f, indent=2, ensure_ascii=False)

        # Generar CSVs
        csv_folder = os.path.join(BACKUP_ONEDRIVE_PATH, f'csv_{fecha_str}_{momento}')
        os.makedirs(csv_folder, exist_ok=True)
        generar_csvs_en_carpeta(csv_folder)

        # Limpiar backups antiguos (mantener últimos 30 días)
        limpiar_backups_antiguos(BACKUP_ONEDRIVE_PATH, dias=30)

        return jsonify({
            'success': True,
            'mensaje': f'Backup guardado en OneDrive',
            'json_path': json_path,
            'csv_folder': csv_folder,
            'estadisticas': backup_data.get('estadisticas', {})
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


def generar_backup_data():
    """Genera el diccionario de backup completo."""
    backup_data = {
        'metadata': {
            'version': '1.0',
            'fecha_backup': datetime.now().isoformat(),
            'descripcion': 'Backup completo de Sky Composite - Inventario QR'
        },
        'etapas': [{'id': e.id, 'nombre': e.nombre, 'orden': e.orden, 'color': e.color, 'icono': e.icono} for e in Etapa.query.all()],
        'coches': [],
        'movimientos': [],
        'lotes': [],
        'lote_coches': [],
        'bloques': [],
        'proceso_lotes': [],
        'contenedores': [],
        'contenedor_bloques': []
    }

    for c in Coche.query.all():
        backup_data['coches'].append({
            'id': c.id, 'codigo_qr': c.codigo_qr, 'registrador': c.registrador, 'proveedor': c.proveedor,
            'numero_viaje': c.numero_viaje, 'camara': c.camara, 'lote_secado': c.lote_secado,
            'espesor_1': c.espesor_1, 'largo_1': c.largo_1, 'plantillas_1': c.plantillas_1, 'bft_1': c.bft_1,
            'espesor_2': c.espesor_2, 'largo_2': c.largo_2, 'plantillas_2': c.plantillas_2, 'bft_2': c.bft_2,
            'espesor_3': c.espesor_3, 'largo_3': c.largo_3, 'plantillas_3': c.plantillas_3, 'bft_3': c.bft_3,
            'total_bft': c.total_bft, 'etapa_actual_id': c.etapa_actual_id, 'notas': c.notas,
            'created_at': c.created_at.isoformat() if c.created_at else None,
            'updated_at': c.updated_at.isoformat() if c.updated_at else None
        })

    for m in Movimiento.query.all():
        backup_data['movimientos'].append({
            'id': m.id, 'coche_id': m.coche_id, 'etapa_origen_id': m.etapa_origen_id,
            'etapa_destino_id': m.etapa_destino_id, 'usuario': m.usuario,
            'timestamp': m.timestamp.isoformat() if m.timestamp else None, 'notas': m.notas
        })

    for l in Lote.query.all():
        backup_data['lotes'].append({
            'id': l.id, 'codigo_qr': l.codigo_qr, 'total_bft': l.total_bft, 'bft_usado': l.bft_usado,
            'cantidad_coches': l.cantidad_coches, 'estado': l.estado, 'turno': l.turno,
            'creado_por': l.creado_por, 'notas': l.notas, 'desperdicio_bft': l.desperdicio_bft,
            'desperdicio_porcentaje': l.desperdicio_porcentaje,
            'created_at': l.created_at.isoformat() if l.created_at else None,
            'fecha_inicio_proceso': l.fecha_inicio_proceso.isoformat() if l.fecha_inicio_proceso else None,
            'fecha_finalizado': l.fecha_finalizado.isoformat() if l.fecha_finalizado else None
        })
        for c in l.coches:
            backup_data['lote_coches'].append({'lote_id': l.id, 'coche_id': c.id})

    for b in Bloque.query.all():
        backup_data['bloques'].append({
            'id': b.id, 'codigo_qr': b.codigo_qr, 'lote_id': b.lote_id,
            'fecha': b.fecha.isoformat() if b.fecha else None, 'turno': b.turno, 'calidad': b.calidad,
            'secuencia': b.secuencia, 'largo': b.largo, 'peso': b.peso, 'densidad': b.densidad,
            'bft': b.bft, 'empatado': b.empatado, 'estado': b.estado, 'peso_encolado': b.peso_encolado,
            'densidad_encolado': b.densidad_encolado, 'notas': b.notas,
            'created_at': b.created_at.isoformat() if b.created_at else None,
            'updated_at': b.updated_at.isoformat() if b.updated_at else None,
            'fecha_encolado': b.fecha_encolado.isoformat() if b.fecha_encolado else None
        })

    for p in ProcesoLote.query.all():
        backup_data['proceso_lotes'].append({
            'id': p.id, 'lote_id': p.lote_id, 'largo': p.largo, 'ancho': p.ancho, 'alto': p.alto,
            'bft_calculado': p.bft_calculado, 'calidad': p.calidad, 'procesado_por': p.procesado_por,
            'created_at': p.created_at.isoformat() if p.created_at else None, 'notas': p.notas
        })

    for cont in Contenedor.query.all():
        backup_data['contenedores'].append({
            'id': cont.id, 'codigo': cont.codigo, 'cliente': cont.cliente,
            'numero_contenedor': cont.numero_contenedor,
            'fecha_carga': cont.fecha_carga.isoformat() if cont.fecha_carga else None,
            'fecha_zarpe': cont.fecha_zarpe.isoformat() if cont.fecha_zarpe else None,
            'tally_sheet': cont.tally_sheet, 'seguro_1': cont.seguro_1, 'seguro_2': cont.seguro_2,
            'seguro_3': cont.seguro_3, 'estado': cont.estado, 'total_bloques': cont.total_bloques,
            'total_bft': cont.total_bft, 'total_m3': cont.total_m3, 'creado_por': cont.creado_por,
            'notas': cont.notas,
            'created_at': cont.created_at.isoformat() if cont.created_at else None,
            'updated_at': cont.updated_at.isoformat() if cont.updated_at else None,
            'fecha_cierre': cont.fecha_cierre.isoformat() if cont.fecha_cierre else None
        })
        for b in cont.bloques:
            backup_data['contenedor_bloques'].append({'contenedor_id': cont.id, 'bloque_id': b.id})

    backup_data['estadisticas'] = {
        'total_coches': len(backup_data['coches']),
        'total_lotes': len(backup_data['lotes']),
        'total_bloques': len(backup_data['bloques']),
        'total_contenedores': len(backup_data['contenedores'])
    }

    return backup_data


def generar_csvs_en_carpeta(carpeta):
    """Genera archivos CSV en la carpeta especificada."""
    # Coches
    with open(os.path.join(carpeta, 'coches.csv'), 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['ID', 'Código QR', 'Registrador', 'Proveedor', 'Viaje', 'Cámara', 'Lote Secado',
                        'Espesor 1', 'Largo 1', 'Plantillas 1', 'BFT 1', 'Espesor 2', 'Largo 2', 'Plantillas 2', 'BFT 2',
                        'Espesor 3', 'Largo 3', 'Plantillas 3', 'BFT 3', 'Total BFT', 'Etapa', 'Fecha'])
        for c in Coche.query.all():
            writer.writerow([c.id, c.codigo_qr, c.registrador, c.proveedor, c.numero_viaje, c.camara, c.lote_secado,
                           c.espesor_1, c.largo_1, c.plantillas_1, c.bft_1, c.espesor_2, c.largo_2, c.plantillas_2, c.bft_2,
                           c.espesor_3, c.largo_3, c.plantillas_3, c.bft_3, c.total_bft,
                           c.etapa_actual.nombre if c.etapa_actual else '',
                           c.created_at.strftime('%d/%m/%Y %H:%M') if c.created_at else ''])

    # Lotes
    with open(os.path.join(carpeta, 'lotes.csv'), 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['ID', 'Código', 'Total BFT', 'BFT Usado', 'Estado', 'Turno', 'Desperdicio BFT', 'Desperdicio %', 'Fecha'])
        for l in Lote.query.all():
            writer.writerow([l.id, l.codigo_qr, l.total_bft, l.bft_usado, l.estado, l.turno,
                           l.desperdicio_bft, l.desperdicio_porcentaje,
                           l.created_at.strftime('%d/%m/%Y %H:%M') if l.created_at else ''])

    # Bloques
    with open(os.path.join(carpeta, 'bloques.csv'), 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['ID', 'Código', 'Lote', 'Fecha', 'Turno', 'Calidad', 'Largo', 'Peso', 'BFT', 'Estado', 'Peso Encolado'])
        for b in Bloque.query.all():
            writer.writerow([b.id, b.codigo_qr, b.lote.codigo_qr if b.lote else '',
                           b.fecha.strftime('%d/%m/%Y') if b.fecha else '', b.turno, b.calidad,
                           b.largo, b.peso, b.bft, b.estado, b.peso_encolado])

    # Contenedores
    with open(os.path.join(carpeta, 'contenedores.csv'), 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['ID', 'Código', 'Cliente', 'Fecha Carga', 'Estado', 'Total Bloques', 'Total BFT', 'Total M³'])
        for cont in Contenedor.query.all():
            writer.writerow([cont.id, cont.codigo, cont.cliente,
                           cont.fecha_carga.strftime('%d/%m/%Y') if cont.fecha_carga else '',
                           cont.estado, cont.total_bloques, cont.total_bft, cont.total_m3])


def limpiar_backups_antiguos(carpeta, dias=30):
    """Elimina backups más antiguos que X días."""
    import glob
    from datetime import timedelta

    fecha_limite = datetime.now() - timedelta(days=dias)

    for archivo in glob.glob(os.path.join(carpeta, 'backup_*.json')):
        fecha_archivo = datetime.fromtimestamp(os.path.getmtime(archivo))
        if fecha_archivo < fecha_limite:
            os.remove(archivo)

    for carpeta_csv in glob.glob(os.path.join(carpeta, 'csv_*')):
        if os.path.isdir(carpeta_csv):
            fecha_carpeta = datetime.fromtimestamp(os.path.getmtime(carpeta_csv))
            if fecha_carpeta < fecha_limite:
                import shutil
                shutil.rmtree(carpeta_csv)


@app.route('/api/backup/restaurar', methods=['POST'])
@login_required
def restaurar_backup():
    """
    Restaura la base de datos desde un archivo JSON de backup.
    ADVERTENCIA: Esto reemplaza TODOS los datos actuales.
    """
    data = request.get_json() or {}
    password = data.get('password', '')

    # Requiere contraseña de administrador
    if password != RESET_DB_PASSWORD:
        return jsonify({'error': 'Contraseña incorrecta'}), 403

    if 'file' not in request.files and 'backup_data' not in data:
        return jsonify({'error': 'Se requiere archivo de backup o datos JSON'}), 400

    try:
        if 'backup_data' in data:
            backup_data = data['backup_data']
        else:
            file = request.files['file']
            backup_data = json.load(file)

        # Validar estructura
        required_keys = ['etapas', 'coches', 'lotes', 'bloques', 'contenedores']
        for key in required_keys:
            if key not in backup_data:
                return jsonify({'error': f'Falta la tabla {key} en el backup'}), 400

        # Limpiar tablas en orden (por foreign keys)
        db.session.execute(contenedor_bloques.delete())
        db.session.execute(lote_coches.delete())
        ProcesoLote.query.delete()
        Bloque.query.delete()
        Movimiento.query.delete()
        Contenedor.query.delete()
        Lote.query.delete()
        Coche.query.delete()
        Etapa.query.delete()
        db.session.commit()

        # Restaurar Etapas
        for e in backup_data['etapas']:
            etapa = Etapa(id=e['id'], nombre=e['nombre'], orden=e['orden'],
                         color=e.get('color'), icono=e.get('icono'))
            db.session.add(etapa)
        db.session.commit()

        # Restaurar Coches
        for c in backup_data['coches']:
            coche = Coche(
                id=c['id'], codigo_qr=c['codigo_qr'], registrador=c.get('registrador'),
                proveedor=c.get('proveedor'), numero_viaje=c.get('numero_viaje'),
                camara=c.get('camara'), lote_secado=c.get('lote_secado'),
                espesor_1=c.get('espesor_1'), largo_1=c.get('largo_1'), plantillas_1=c.get('plantillas_1'), bft_1=c.get('bft_1'),
                espesor_2=c.get('espesor_2'), largo_2=c.get('largo_2'), plantillas_2=c.get('plantillas_2'), bft_2=c.get('bft_2'),
                espesor_3=c.get('espesor_3'), largo_3=c.get('largo_3'), plantillas_3=c.get('plantillas_3'), bft_3=c.get('bft_3'),
                total_bft=c.get('total_bft'), etapa_actual_id=c['etapa_actual_id'], notas=c.get('notas'),
                created_at=datetime.fromisoformat(c['created_at']) if c.get('created_at') else None,
                updated_at=datetime.fromisoformat(c['updated_at']) if c.get('updated_at') else None
            )
            db.session.add(coche)
        db.session.commit()

        # Restaurar Lotes
        for l in backup_data['lotes']:
            lote = Lote(
                id=l['id'], codigo_qr=l['codigo_qr'], total_bft=l.get('total_bft'),
                bft_usado=l.get('bft_usado'), cantidad_coches=l.get('cantidad_coches'),
                estado=l.get('estado'), turno=l.get('turno'), creado_por=l.get('creado_por'),
                notas=l.get('notas'), desperdicio_bft=l.get('desperdicio_bft'),
                desperdicio_porcentaje=l.get('desperdicio_porcentaje'),
                created_at=datetime.fromisoformat(l['created_at']) if l.get('created_at') else None,
                fecha_inicio_proceso=datetime.fromisoformat(l['fecha_inicio_proceso']) if l.get('fecha_inicio_proceso') else None,
                fecha_finalizado=datetime.fromisoformat(l['fecha_finalizado']) if l.get('fecha_finalizado') else None
            )
            db.session.add(lote)
        db.session.commit()

        # Restaurar relación Lote-Coches
        for lc in backup_data.get('lote_coches', []):
            db.session.execute(lote_coches.insert().values(lote_id=lc['lote_id'], coche_id=lc['coche_id']))
        db.session.commit()

        # Restaurar Movimientos
        for m in backup_data.get('movimientos', []):
            mov = Movimiento(
                id=m['id'], coche_id=m['coche_id'], etapa_origen_id=m.get('etapa_origen_id'),
                etapa_destino_id=m['etapa_destino_id'], usuario=m.get('usuario'),
                timestamp=datetime.fromisoformat(m['timestamp']) if m.get('timestamp') else None,
                notas=m.get('notas')
            )
            db.session.add(mov)
        db.session.commit()

        # Restaurar Bloques
        for b in backup_data['bloques']:
            bloque = Bloque(
                id=b['id'], codigo_qr=b['codigo_qr'], lote_id=b.get('lote_id'),
                fecha=datetime.fromisoformat(b['fecha']).date() if b.get('fecha') else None,
                turno=b.get('turno'), calidad=b.get('calidad'), secuencia=b.get('secuencia'),
                largo=b.get('largo'), peso=b.get('peso'), densidad=b.get('densidad'),
                bft=b.get('bft'), empatado=b.get('empatado'), estado=b.get('estado'),
                peso_encolado=b.get('peso_encolado'), densidad_encolado=b.get('densidad_encolado'),
                notas=b.get('notas'),
                created_at=datetime.fromisoformat(b['created_at']) if b.get('created_at') else None,
                updated_at=datetime.fromisoformat(b['updated_at']) if b.get('updated_at') else None,
                fecha_encolado=datetime.fromisoformat(b['fecha_encolado']) if b.get('fecha_encolado') else None
            )
            db.session.add(bloque)
        db.session.commit()

        # Restaurar Proceso Lotes
        for p in backup_data.get('proceso_lotes', []):
            proceso = ProcesoLote(
                id=p['id'], lote_id=p.get('lote_id'), largo=p.get('largo'),
                ancho=p.get('ancho'), alto=p.get('alto'), bft_calculado=p.get('bft_calculado'),
                calidad=p.get('calidad'), procesado_por=p.get('procesado_por'),
                created_at=datetime.fromisoformat(p['created_at']) if p.get('created_at') else None,
                notas=p.get('notas')
            )
            db.session.add(proceso)
        db.session.commit()

        # Restaurar Contenedores
        for cont in backup_data['contenedores']:
            contenedor = Contenedor(
                id=cont['id'], codigo=cont['codigo'], cliente=cont.get('cliente'),
                numero_contenedor=cont.get('numero_contenedor'),
                fecha_carga=datetime.fromisoformat(cont['fecha_carga']).date() if cont.get('fecha_carga') else None,
                fecha_zarpe=datetime.fromisoformat(cont['fecha_zarpe']).date() if cont.get('fecha_zarpe') else None,
                tally_sheet=cont.get('tally_sheet'), seguro_1=cont.get('seguro_1'),
                seguro_2=cont.get('seguro_2'), seguro_3=cont.get('seguro_3'),
                estado=cont.get('estado'), total_bloques=cont.get('total_bloques'),
                total_bft=cont.get('total_bft'), total_m3=cont.get('total_m3'),
                creado_por=cont.get('creado_por'), notas=cont.get('notas'),
                created_at=datetime.fromisoformat(cont['created_at']) if cont.get('created_at') else None,
                updated_at=datetime.fromisoformat(cont['updated_at']) if cont.get('updated_at') else None,
                fecha_cierre=datetime.fromisoformat(cont['fecha_cierre']) if cont.get('fecha_cierre') else None
            )
            db.session.add(contenedor)
        db.session.commit()

        # Restaurar relación Contenedor-Bloques
        for cb in backup_data.get('contenedor_bloques', []):
            db.session.execute(contenedor_bloques.insert().values(contenedor_id=cb['contenedor_id'], bloque_id=cb['bloque_id']))
        db.session.commit()

        return jsonify({
            'success': True,
            'mensaje': 'Base de datos restaurada exitosamente',
            'estadisticas': {
                'etapas': len(backup_data['etapas']),
                'coches': len(backup_data['coches']),
                'lotes': len(backup_data['lotes']),
                'bloques': len(backup_data['bloques']),
                'contenedores': len(backup_data['contenedores'])
            }
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Error al restaurar: {str(e)}'}), 500


# ==================== GOOGLE DRIVE BACKUP ====================

# Configuración de Google Drive (via variables de entorno)
GOOGLE_DRIVE_FOLDER_ID = os.environ.get('GOOGLE_DRIVE_FOLDER_ID', '')
GOOGLE_SERVICE_ACCOUNT_JSON = os.environ.get('GOOGLE_SERVICE_ACCOUNT_JSON', '')


def get_google_drive_service():
    """Obtiene el servicio de Google Drive usando cuenta de servicio."""
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        if not GOOGLE_SERVICE_ACCOUNT_JSON:
            return None, "No se ha configurado GOOGLE_SERVICE_ACCOUNT_JSON"

        # Las credenciales pueden venir como JSON string o como path a archivo
        # Usamos scope 'drive' para poder acceder a carpetas compartidas
        SCOPES = ['https://www.googleapis.com/auth/drive']

        if GOOGLE_SERVICE_ACCOUNT_JSON.startswith('{'):
            import json as json_lib
            credentials_info = json_lib.loads(GOOGLE_SERVICE_ACCOUNT_JSON)
            credentials = service_account.Credentials.from_service_account_info(
                credentials_info,
                scopes=SCOPES
            )
        else:
            credentials = service_account.Credentials.from_service_account_file(
                GOOGLE_SERVICE_ACCOUNT_JSON,
                scopes=SCOPES
            )

        service = build('drive', 'v3', credentials=credentials)
        return service, None
    except ImportError:
        return None, "Librerías de Google no instaladas (google-api-python-client, google-auth)"
    except Exception as e:
        return None, str(e)


@app.route('/api/backup/drive/status')
@login_required
def drive_status():
    """Verifica el estado de la conexión con Google Drive."""
    if not GOOGLE_DRIVE_FOLDER_ID:
        return jsonify({
            'connected': False,
            'error': 'GOOGLE_DRIVE_FOLDER_ID no configurado'
        })

    service, error = get_google_drive_service()
    if error:
        return jsonify({
            'connected': False,
            'error': error
        })

    try:
        # Verificar acceso a la carpeta
        folder = service.files().get(fileId=GOOGLE_DRIVE_FOLDER_ID).execute()
        return jsonify({
            'connected': True,
            'folder_name': folder.get('name', 'Carpeta de Backups'),
            'folder_id': GOOGLE_DRIVE_FOLDER_ID
        })
    except Exception as e:
        return jsonify({
            'connected': False,
            'error': f'No se puede acceder a la carpeta: {str(e)}'
        })


@app.route('/api/backup/drive/subir', methods=['POST'])
@login_required
def subir_backup_drive():
    """Sube un backup completo a Google Drive."""
    service, error = get_google_drive_service()
    if error:
        return jsonify({'success': False, 'error': error}), 400

    if not GOOGLE_DRIVE_FOLDER_ID:
        return jsonify({'success': False, 'error': 'GOOGLE_DRIVE_FOLDER_ID no configurado'}), 400

    try:
        from googleapiclient.http import MediaInMemoryUpload

        fecha_str = datetime.now().strftime('%Y%m%d_%H%M%S')
        momento = 'AM' if datetime.now().hour < 12 else 'PM'

        # Generar backup JSON
        backup_data = generar_backup_data()
        json_content = json.dumps(backup_data, indent=2, ensure_ascii=False)

        # Subir JSON a Drive
        json_metadata = {
            'name': f'backup_{fecha_str}_{momento}.json',
            'parents': [GOOGLE_DRIVE_FOLDER_ID],
            'mimeType': 'application/json'
        }
        json_media = MediaInMemoryUpload(
            json_content.encode('utf-8'),
            mimetype='application/json'
        )
        json_file = service.files().create(
            body=json_metadata,
            media_body=json_media,
            fields='id, name, webViewLink',
            supportsAllDrives=True
        ).execute()

        # Generar y subir ZIP con CSVs
        memoria_zip = BytesIO()
        with zipfile.ZipFile(memoria_zip, 'w', zipfile.ZIP_DEFLATED) as zf:
            # CSV de Coches
            coches_csv = StringIO()
            writer = csv.writer(coches_csv)
            writer.writerow(['ID', 'Código QR', 'Registrador', 'Proveedor', 'Cámara', 'Lote Secado',
                           'Espesor 1', 'Largo 1', 'Plantillas 1', 'BFT 1',
                           'Espesor 2', 'Largo 2', 'Plantillas 2', 'BFT 2',
                           'Espesor 3', 'Largo 3', 'Plantillas 3', 'BFT 3',
                           'Total BFT', 'Etapa', 'Fecha'])
            for c in Coche.query.all():
                writer.writerow([c.id, c.codigo_qr, c.registrador, c.proveedor, c.camara, c.lote_secado,
                               c.espesor_1, c.largo_1, c.plantillas_1, c.bft_1,
                               c.espesor_2, c.largo_2, c.plantillas_2, c.bft_2,
                               c.espesor_3, c.largo_3, c.plantillas_3, c.bft_3,
                               c.total_bft, c.etapa_actual.nombre if c.etapa_actual else '',
                               c.created_at.strftime('%d/%m/%Y %H:%M') if c.created_at else ''])
            zf.writestr('coches.csv', coches_csv.getvalue())

            # CSV de Lotes
            lotes_csv = StringIO()
            writer = csv.writer(lotes_csv)
            writer.writerow(['ID', 'Código', 'Total BFT', 'BFT Usado', 'Estado', 'Turno', 'Fecha'])
            for l in Lote.query.all():
                writer.writerow([l.id, l.codigo_qr, l.total_bft, l.bft_usado, l.estado, l.turno,
                               l.created_at.strftime('%d/%m/%Y %H:%M') if l.created_at else ''])
            zf.writestr('lotes.csv', lotes_csv.getvalue())

            # CSV de Bloques
            bloques_csv = StringIO()
            writer = csv.writer(bloques_csv)
            writer.writerow(['ID', 'Código', 'Lote', 'Fecha', 'Turno', 'Calidad', 'Largo', 'Peso', 'BFT', 'Estado'])
            for b in Bloque.query.all():
                writer.writerow([b.id, b.codigo_qr, b.lote.codigo_qr if b.lote else '',
                               b.fecha.strftime('%d/%m/%Y') if b.fecha else '',
                               b.turno, b.calidad, b.largo, b.peso, b.bft, b.estado])
            zf.writestr('bloques.csv', bloques_csv.getvalue())

            # CSV de Contenedores
            contenedores_csv = StringIO()
            writer = csv.writer(contenedores_csv)
            writer.writerow(['ID', 'Código', 'Cliente', 'Fecha Carga', 'Estado', 'Total Bloques', 'Total BFT'])
            for cont in Contenedor.query.all():
                writer.writerow([cont.id, cont.codigo, cont.cliente,
                               cont.fecha_carga.strftime('%d/%m/%Y') if cont.fecha_carga else '',
                               cont.estado, cont.total_bloques, cont.total_bft])
            zf.writestr('contenedores.csv', contenedores_csv.getvalue())

        memoria_zip.seek(0)

        # Subir ZIP a Drive
        zip_metadata = {
            'name': f'backup_csv_{fecha_str}_{momento}.zip',
            'parents': [GOOGLE_DRIVE_FOLDER_ID],
            'mimeType': 'application/zip'
        }
        zip_media = MediaInMemoryUpload(
            memoria_zip.read(),
            mimetype='application/zip'
        )
        zip_file = service.files().create(
            body=zip_metadata,
            media_body=zip_media,
            fields='id, name, webViewLink',
            supportsAllDrives=True
        ).execute()

        # Limpiar backups antiguos (más de 30 días)
        limpiar_backups_drive(service, GOOGLE_DRIVE_FOLDER_ID, dias=30)

        return jsonify({
            'success': True,
            'mensaje': 'Backup subido a Google Drive',
            'archivos': {
                'json': {
                    'nombre': json_file.get('name'),
                    'id': json_file.get('id'),
                    'link': json_file.get('webViewLink')
                },
                'csv_zip': {
                    'nombre': zip_file.get('name'),
                    'id': zip_file.get('id'),
                    'link': zip_file.get('webViewLink')
                }
            },
            'estadisticas': backup_data.get('estadisticas', {})
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


def limpiar_backups_drive(service, folder_id, dias=30):
    """Elimina backups antiguos de Google Drive."""
    try:
        from datetime import timedelta

        fecha_limite = datetime.now() - timedelta(days=dias)
        fecha_limite_str = fecha_limite.isoformat() + 'Z'

        # Buscar archivos de backup antiguos
        query = f"'{folder_id}' in parents and (name contains 'backup_') and createdTime < '{fecha_limite_str}'"
        results = service.files().list(
            q=query,
            fields='files(id, name, createdTime)'
        ).execute()

        archivos = results.get('files', [])
        for archivo in archivos:
            service.files().delete(fileId=archivo['id']).execute()

        return len(archivos)
    except Exception as e:
        print(f"Error limpiando backups antiguos: {e}")
        return 0


@app.route('/api/backup/drive/auto', methods=['POST'])
def backup_automatico_drive():
    """
    Endpoint para backup automático a Google Drive.
    Llamado por un cron job o scheduler externo.
    Requiere token de seguridad.
    """
    token = request.headers.get('X-Backup-Token') or request.args.get('token')
    expected_token = os.environ.get('BACKUP_TOKEN', 'skycomposite_backup_2024')

    if token != expected_token:
        return jsonify({'error': 'Token inválido'}), 403

    # Verificar si Drive está configurado
    if not GOOGLE_DRIVE_FOLDER_ID or not GOOGLE_SERVICE_ACCOUNT_JSON:
        return jsonify({
            'success': False,
            'error': 'Google Drive no configurado. Configura GOOGLE_DRIVE_FOLDER_ID y GOOGLE_SERVICE_ACCOUNT_JSON'
        }), 400

    # Reutilizar la lógica de subir_backup_drive pero sin login_required
    service, error = get_google_drive_service()
    if error:
        return jsonify({'success': False, 'error': error}), 400

    try:
        from googleapiclient.http import MediaInMemoryUpload

        fecha_str = datetime.now().strftime('%Y%m%d_%H%M%S')
        momento = 'AM' if datetime.now().hour < 12 else 'PM'

        backup_data = generar_backup_data()
        json_content = json.dumps(backup_data, indent=2, ensure_ascii=False)

        # Subir JSON
        json_metadata = {
            'name': f'auto_backup_{fecha_str}_{momento}.json',
            'parents': [GOOGLE_DRIVE_FOLDER_ID]
        }
        json_media = MediaInMemoryUpload(json_content.encode('utf-8'), mimetype='application/json')
        json_file = service.files().create(body=json_metadata, media_body=json_media, fields='id, name', supportsAllDrives=True).execute()

        # Limpiar antiguos
        eliminados = limpiar_backups_drive(service, GOOGLE_DRIVE_FOLDER_ID, dias=30)

        return jsonify({
            'success': True,
            'mensaje': f'Backup automático completado',
            'archivo': json_file.get('name'),
            'estadisticas': backup_data.get('estadisticas', {}),
            'backups_eliminados': eliminados
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


if __name__ == '__main__':
    # Solo para desarrollo local
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=True, host='0.0.0.0', port=port)
