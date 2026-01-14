import os
from flask import Flask, render_template, request, jsonify, send_file
from models import db, Etapa, Coche, Movimiento, Lote, init_etapas, ESPESORES, LARGOS
from qr_service import generar_codigo_unico, generar_codigo_lote, generar_imagen_qr
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
    total_bft = sum(c.total_bft or 0 for c in coches)

    # Si es Secado (orden 2), agrupar por cámara
    coches_por_camara = {}
    if etapa.orden == 2:
        for coche in coches:
            camara = coche.camara or 0  # 0 para coches sin cámara asignada
            if camara not in coches_por_camara:
                coches_por_camara[camara] = {
                    'coches': [],
                    'total_bft': 0,
                    'count': 0
                }
            coches_por_camara[camara]['coches'].append(coche)
            coches_por_camara[camara]['total_bft'] += coche.total_bft or 0
            coches_por_camara[camara]['count'] += 1
        # Ordenar por número de cámara
        coches_por_camara = dict(sorted(coches_por_camara.items()))

    # Si es Ingreso a Taller (orden 4), obtener lotes
    lotes = []
    if etapa.orden == 4:
        lotes = Lote.query.order_by(Lote.created_at.desc()).all()

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
    """Dashboard principal - Resumen."""
    etapas = Etapa.query.order_by(Etapa.orden).all()

    # Obtener estadísticas por etapa
    stats_por_etapa = {}
    for etapa in etapas:
        coches = Coche.query.filter_by(etapa_actual_id=etapa.id).all()
        total_coches = len(coches)
        total_bft = sum(c.total_bft or 0 for c in coches)
        stats_por_etapa[etapa.id] = {
            'total_coches': total_coches,
            'total_bft': total_bft,
            'coches': coches
        }

    # Últimos movimientos
    ultimos_movimientos = Movimiento.query.order_by(Movimiento.timestamp.desc()).limit(10).all()

    return render_template('dashboard.html',
                          etapas=etapas,
                          stats_por_etapa=stats_por_etapa,
                          ultimos_movimientos=ultimos_movimientos)


@app.route('/nuevo')
def nuevo_coche_form():
    """Formulario para crear nuevo coche."""
    etapas = Etapa.query.order_by(Etapa.orden).all()
    espesores = ESPESORES
    largos = LARGOS
    return render_template('nuevo_coche.html', etapas=etapas, espesores=espesores, largos=largos)


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


@app.route('/api/dashboard/resumen', methods=['GET'])
def resumen_dashboard():
    """Obtiene resumen para el dashboard."""
    etapas = Etapa.query.order_by(Etapa.orden).all()

    resumen = []
    for etapa in etapas:
        coches = Coche.query.filter_by(etapa_actual_id=etapa.id).all()
        total_bft = sum(c.total_bft or 0 for c in coches)
        resumen.append({
            'etapa': etapa.to_dict(),
            'cantidad': len(coches),
            'total_bft': total_bft
        })

    return jsonify(resumen)


@app.route('/api/scan', methods=['POST'])
def escanear_qr():
    """Procesa un escaneo QR desde móvil. Busca tanto coches como lotes."""
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


if __name__ == '__main__':
    # Solo para desarrollo local
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=True, host='0.0.0.0', port=port)
