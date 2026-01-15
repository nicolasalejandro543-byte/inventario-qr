import os
from datetime import datetime
from flask import Flask, render_template, request, jsonify, send_file, redirect
from models import db, Etapa, Coche, Movimiento, Lote, Bloque, ProcesoLote, Contenedor, contenedor_bloques, lote_coches, init_etapas, ESPESORES, LARGOS, LARGOS_PRODUCCION, LARGOS_CONTENEDOR
from qr_service import generar_codigo_unico, generar_codigo_lote, generar_codigo_bloque, generar_codigo_contenedor, generar_imagen_qr
from config import get_config
import io

app = Flask(__name__)

# Configuracion desde config.py (soporta SQLite local y PostgreSQL en Railway)
app.config.from_object(get_config())

# Inicializar base de datos
db.init_app(app)

with app.app_context():
    db.create_all()
    init_etapas()


# ==================== RUTAS WEB ====================

@app.route('/etapa/<int:etapa_id>')
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
def scanner():
    """Página del scanner QR para móviles."""
    etapas = Etapa.query.order_by(Etapa.orden).all()
    return render_template('scanner.html', etapas=etapas)


@app.route('/recepcion')
def recepcion_madera():
    """Página de Recepción de Madera Verde."""
    return render_template('recepcion_madera.html')


@app.route('/')
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


@app.route('/nuevo')
def nuevo_coche_form():
    """Formulario para crear nuevo coche."""
    etapas = Etapa.query.order_by(Etapa.orden).all()
    espesores = ESPESORES
    largos = LARGOS
    return render_template('nuevo_coche.html', etapas=etapas, espesores=espesores, largos=largos)


@app.route('/produccion')
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
def lotes_finalizados():
    """Vista de lotes finalizados."""
    lotes = Lote.query.filter_by(estado='finalizado').order_by(Lote.fecha_finalizado.desc()).all()
    return render_template('finalizados.html', lotes=lotes)


@app.route('/finalizado/<int:lote_id>')
def detalle_lote_finalizado(lote_id):
    """Vista de detalle de un lote finalizado."""
    lote = Lote.query.get_or_404(lote_id)
    if lote.estado != 'finalizado':
        return redirect('/finalizados')
    return render_template('detalle_lote_finalizado.html', lote=lote, now=datetime.now())


@app.route('/bloques/presentados')
def bloques_presentados():
    """Vista de bloques presentados con filtros."""
    bloques = Bloque.query.filter_by(estado='presentado').order_by(Bloque.created_at.desc()).all()

    # Obtener valores únicos para filtros
    secuencias_raw = list(set(b.secuencia for b in bloques if b.secuencia))
    # Ordenar secuencias de mayor a menor (intentar orden numerico, sino alfabetico inverso)
    try:
        secuencias = sorted(secuencias_raw, key=lambda x: int(x) if x.isdigit() else x, reverse=True)
    except:
        secuencias = sorted(secuencias_raw, reverse=True)
    turnos = list(set(b.turno for b in bloques if b.turno))
    calidades = list(set(b.calidad for b in bloques if b.calidad))
    # Usar todos los largos de produccion, ordenados de mayor a menor
    largos = sorted(LARGOS_PRODUCCION, reverse=True)

    return render_template('bloques_presentados.html',
                          bloques=bloques,
                          secuencias=secuencias,
                          turnos=turnos,
                          calidades=calidades,
                          largos=largos,
                          largos_produccion=LARGOS_PRODUCCION)


@app.route('/bloques/encolados')
def bloques_encolados():
    """Vista de bloques encolados con filtros."""
    bloques = Bloque.query.filter_by(estado='encolado').order_by(Bloque.fecha_encolado.desc()).all()

    # Obtener valores únicos para filtros
    secuencias_raw = list(set(b.secuencia for b in bloques if b.secuencia))
    # Ordenar secuencias de mayor a menor (intentar orden numerico, sino alfabetico inverso)
    try:
        secuencias = sorted(secuencias_raw, key=lambda x: int(x) if x.isdigit() else x, reverse=True)
    except:
        secuencias = sorted(secuencias_raw, reverse=True)
    turnos = list(set(b.turno for b in bloques if b.turno))
    calidades = list(set(b.calidad for b in bloques if b.calidad))
    # Usar todos los largos de produccion, ordenados de mayor a menor
    largos = sorted(LARGOS_PRODUCCION, reverse=True)

    return render_template('bloques_encolados.html',
                          bloques=bloques,
                          secuencias=secuencias,
                          turnos=turnos,
                          calidades=calidades,
                          largos=largos,
                          largos_produccion=LARGOS_PRODUCCION)


@app.route('/bloque/<int:bloque_id>')
def detalle_bloque(bloque_id):
    """Página de detalle de un bloque."""
    bloque = Bloque.query.get_or_404(bloque_id)
    return render_template('detalle_bloque.html', bloque=bloque, largos_produccion=LARGOS_PRODUCCION)


@app.route('/coche/<int:coche_id>')
def detalle_coche(coche_id):
    """Página de detalle de un coche."""
    coche = Coche.query.get_or_404(coche_id)
    etapas = Etapa.query.order_by(Etapa.orden).all()
    historial = Movimiento.query.filter_by(coche_id=coche_id).order_by(Movimiento.timestamp.desc()).all()
    return render_template('detalle_coche.html', coche=coche, etapas=etapas, historial=historial)


@app.route('/lotes')
def ver_lotes():
    """Página para ver todos los lotes."""
    lotes = Lote.query.order_by(Lote.created_at.desc()).all()
    return render_template('lotes.html', lotes=lotes)


@app.route('/lote/<int:lote_id>')
def detalle_lote(lote_id):
    """Página de detalle de un lote."""
    lote = Lote.query.get_or_404(lote_id)
    return render_template('detalle_lote.html', lote=lote)


# ==================== API REST ====================

@app.route('/api/coches', methods=['GET'])
def listar_coches():
    """Lista todos los coches."""
    coches = Coche.query.all()
    return jsonify([c.to_dict() for c in coches])


@app.route('/api/coches', methods=['POST'])
def crear_coche():
    """Crea un nuevo coche. Siempre inicia en Madera Verde (etapa 1)."""
    data = request.get_json()

    # Generar código QR único
    codigo_qr = generar_codigo_unico()

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
def obtener_coche_por_qr(codigo_qr):
    """Obtiene un coche por su código QR."""
    coche = Coche.query.filter_by(codigo_qr=codigo_qr).first()

    if not coche:
        return jsonify({'error': 'Coche no encontrado', 'codigo': codigo_qr}), 404

    return jsonify(coche.to_dict())


@app.route('/api/coches/<int:coche_id>', methods=['PUT'])
def editar_coche(coche_id):
    """Edita un coche existente. Solo permitido en Madera Verde."""
    coche = Coche.query.get_or_404(coche_id)
    data = request.get_json()

    # Solo permitir edicion en Madera Verde (orden 1)
    if coche.etapa_actual.orden != 1:
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
def eliminar_coche(coche_id):
    """Elimina un coche. Solo permitido en Madera Verde."""
    coche = Coche.query.get_or_404(coche_id)

    # Solo permitir eliminacion en Madera Verde (orden 1)
    if coche.etapa_actual.orden != 1:
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
def cambiar_camara(coche_id):
    """Permite cambiar de camara cuando esta en Secado (emergencia: horno danado)."""
    coche = Coche.query.get_or_404(coche_id)
    data = request.get_json()

    nueva_camara = data.get('camara')
    usuario = data.get('usuario', 'Anonimo')
    motivo = data.get('motivo', 'Cambio de camara')

    # Verificar que esta en Secado (orden 2)
    if coche.etapa_actual.orden != 2:
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
        if coche.etapa_actual.orden != 2:
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
def obtener_historial(coche_id):
    """Obtiene el historial de movimientos de un coche."""
    movimientos = Movimiento.query.filter_by(coche_id=coche_id).order_by(Movimiento.timestamp.desc()).all()
    return jsonify([m.to_dict() for m in movimientos])


@app.route('/api/etapas', methods=['GET'])
def listar_etapas():
    """Lista todas las etapas."""
    etapas = Etapa.query.order_by(Etapa.orden).all()
    return jsonify([e.to_dict() for e in etapas])


@app.route('/api/secado/camara/<int:camara>/lote/<lote_secado>')
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
def listar_lotes():
    """Lista todos los lotes."""
    lotes = Lote.query.order_by(Lote.created_at.desc()).all()
    return jsonify([l.to_dict() for l in lotes])


@app.route('/api/lotes', methods=['POST'])
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

    # Generar código único para el lote
    codigo_lote = generar_codigo_lote()

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
def obtener_lote(lote_id):
    """Obtiene un lote por su ID."""
    lote = Lote.query.get_or_404(lote_id)
    return jsonify(lote.to_dict())


@app.route('/api/lotes/<codigo_qr>', methods=['GET'])
def obtener_lote_por_qr(codigo_qr):
    """Obtiene un lote por su código QR."""
    lote = Lote.query.filter_by(codigo_qr=codigo_qr).first()

    if not lote:
        return jsonify({'error': 'Lote no encontrado', 'codigo': codigo_qr}), 404

    return jsonify(lote.to_dict())


@app.route('/api/lotes/<int:lote_id>/qr', methods=['GET'])
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
def listar_bloques():
    """Lista todos los bloques."""
    estado = request.args.get('estado')
    if estado:
        bloques = Bloque.query.filter_by(estado=estado).order_by(Bloque.created_at.desc()).all()
    else:
        bloques = Bloque.query.order_by(Bloque.created_at.desc()).all()
    return jsonify([b.to_dict() for b in bloques])


@app.route('/api/bloques', methods=['POST'])
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

    # Generar código QR único
    codigo_qr = generar_codigo_bloque()

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
def obtener_bloque(bloque_id):
    """Obtiene un bloque por su ID."""
    bloque = Bloque.query.get_or_404(bloque_id)
    return jsonify(bloque.to_dict())


@app.route('/api/bloques/<int:bloque_id>/qr', methods=['GET'])
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
def listar_procesos():
    """Lista todos los procesos de lotes."""
    procesos = ProcesoLote.query.order_by(ProcesoLote.created_at.desc()).all()
    return jsonify([p.to_dict() for p in procesos])


@app.route('/api/proceso', methods=['POST'])
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
def obtener_proceso(proceso_id):
    """Obtiene un proceso por su ID."""
    proceso = ProcesoLote.query.get_or_404(proceso_id)
    return jsonify(proceso.to_dict())


@app.route('/api/lotes-taller', methods=['GET'])
def listar_lotes_taller():
    """Lista lotes disponibles en Ingreso a Taller."""
    lotes = Lote.query.order_by(Lote.created_at.desc()).all()
    return jsonify([l.to_dict() for l in lotes])


@app.route('/api/lotes/<int:lote_id>/iniciar', methods=['POST'])
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
def editar_lote_finalizado(lote_id):
    """Edita un lote finalizado con verificacion de contraseña."""
    data = request.json
    password = data.get('password', '')

    # Verificar contraseña
    if password != 'admin1208':
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


# ==================== CONTENEDORES (EMBARQUE) ====================

@app.route('/contenedores')
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
def listar_contenedores():
    """Lista todos los contenedores."""
    contenedores = Contenedor.query.order_by(Contenedor.created_at.desc()).all()
    return jsonify([c.to_dict() for c in contenedores])


@app.route('/api/contenedores', methods=['POST'])
def crear_contenedor():
    """Crea un nuevo contenedor de embarque."""
    data = request.get_json()

    # Obtener el siguiente número secuencial
    ultimo = Contenedor.query.order_by(Contenedor.id.desc()).first()
    siguiente_num = (ultimo.id + 1) if ultimo else 1

    codigo = generar_codigo_contenedor(siguiente_num)

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
def obtener_contenedor(contenedor_id):
    """Obtiene un contenedor por ID."""
    contenedor = Contenedor.query.get_or_404(contenedor_id)
    return jsonify(contenedor.to_dict())


@app.route('/api/contenedores/<int:contenedor_id>', methods=['PUT'])
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
def listar_bloques_encolados_disponibles():
    """Lista bloques encolados que no están asignados a ningún contenedor."""
    bloques_encolados = Bloque.query.filter_by(estado='encolado').all()
    bloques_disponibles = [b.to_dict() for b in bloques_encolados if len(b.contenedores) == 0]
    return jsonify(bloques_disponibles)


if __name__ == '__main__':
    # Solo para desarrollo local
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=True, host='0.0.0.0', port=port)
