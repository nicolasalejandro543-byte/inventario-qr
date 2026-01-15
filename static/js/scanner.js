// Scanner QR para móviles
let scanner = null;
let cocheActual = null;

document.addEventListener('DOMContentLoaded', function() {
    const btnIniciar = document.getElementById('btn-iniciar');
    const btnDetener = document.getElementById('btn-detener');
    const btnBuscarManual = document.getElementById('btn-buscar-manual');
    const codigoManual = document.getElementById('codigo-manual');
    const btnContinuar = document.getElementById('btn-continuar');

    // Iniciar scanner
    btnIniciar.addEventListener('click', iniciarScanner);

    // Detener scanner
    btnDetener.addEventListener('click', detenerScanner);

    // Búsqueda manual
    btnBuscarManual.addEventListener('click', function() {
        const codigo = codigoManual.value.trim();
        if (codigo) {
            buscarCoche(codigo);
        }
    });

    // Enter en input manual
    codigoManual.addEventListener('keypress', function(e) {
        if (e.key === 'Enter') {
            const codigo = codigoManual.value.trim();
            if (codigo) {
                buscarCoche(codigo);
            }
        }
    });

    // Continuar escaneando
    btnContinuar.addEventListener('click', function() {
        ocultarResultado();
        if (scanner) {
            scanner.resume();
        }
    });

    // Botones de etapa
    document.querySelectorAll('.btn-etapa').forEach(btn => {
        btn.addEventListener('click', function() {
            if (cocheActual) {
                const etapaId = parseInt(this.dataset.etapaId);
                moverCocheAEtapa(etapaId);
            }
        });
    });
});

async function iniciarScanner() {
    const btnIniciar = document.getElementById('btn-iniciar');
    const btnDetener = document.getElementById('btn-detener');

    try {
        scanner = new Html5Qrcode('qr-reader');

        const config = {
            fps: 10,
            qrbox: { width: 250, height: 250 },
            aspectRatio: 1.0
        };

        await scanner.start(
            { facingMode: 'environment' },
            config,
            onScanSuccess,
            onScanError
        );

        btnIniciar.style.display = 'none';
        btnDetener.style.display = 'block';

    } catch (err) {
        console.error('Error al iniciar cámara:', err);
        alert('No se pudo acceder a la cámara. Verifica los permisos del navegador.');
    }
}

async function detenerScanner() {
    const btnIniciar = document.getElementById('btn-iniciar');
    const btnDetener = document.getElementById('btn-detener');

    if (scanner) {
        try {
            await scanner.stop();
            scanner = null;
        } catch (err) {
            console.error('Error al detener scanner:', err);
        }
    }

    btnIniciar.style.display = 'block';
    btnDetener.style.display = 'none';
}

function onScanSuccess(decodedText) {
    // Pausar scanner
    if (scanner) {
        scanner.pause();
    }

    // Beep de confirmación
    reproducirBeep();

    // Buscar coche
    buscarCoche(decodedText);
}

function onScanError(errorMessage) {
    // Ignorar errores de escaneo continuo
}

async function buscarCoche(codigo) {
    ocultarError();

    try {
        const response = await fetch('/api/scan', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ codigo_qr: codigo })
        });

        const data = await response.json();

        if (response.ok) {
            cocheActual = data.coche;
            mostrarResultado(data.coche);
        } else {
            mostrarError(data.error || 'Coche no encontrado');
            // Reanudar scanner después de error
            setTimeout(() => {
                if (scanner) scanner.resume();
            }, 2000);
        }
    } catch (error) {
        mostrarError('Error de conexión: ' + error.message);
    }
}

function mostrarResultado(coche) {
    const panel = document.getElementById('resultado-panel');
    const info = document.getElementById('coche-info');

    info.innerHTML = `
        <div class="mb-3">
            <span class="badge fs-5" style="background-color: ${coche.etapa_actual.color};">
                ${coche.etapa_actual.nombre}
            </span>
        </div>
        <h5 class="text-primary">${coche.codigo_qr}</h5>
        <p class="mb-1"><strong>Total BFT:</strong> ${coche.total_bft || 0}</p>
        ${coche.proveedor ? `<p class="mb-1"><strong>Proveedor:</strong> ${coche.proveedor}</p>` : ''}
        ${coche.registrador ? `<p class="mb-1"><strong>Registrador:</strong> ${coche.registrador}</p>` : ''}
        ${coche.notas ? `<p class="mb-1"><strong>Notas:</strong> ${coche.notas}</p>` : ''}
    `;

    // Actualizar estado de botones de etapa
    document.querySelectorAll('.btn-etapa').forEach(btn => {
        const etapaId = parseInt(btn.dataset.etapaId);
        if (etapaId === coche.etapa_actual.id) {
            btn.classList.remove('btn-outline-secondary');
            btn.classList.add('btn-secondary', 'disabled');
            btn.innerHTML = btn.innerHTML.replace('</i>', '</i>') + ' <span class="badge bg-dark">Actual</span>';
        } else {
            btn.classList.remove('btn-secondary', 'disabled');
            btn.classList.add('btn-outline-secondary');
            // Remover badge "Actual" si existe
            btn.innerHTML = btn.innerHTML.replace(/<span class="badge bg-dark">Actual<\/span>/g, '');
        }
    });

    panel.style.display = 'block';
    panel.scrollIntoView({ behavior: 'smooth' });
}

function ocultarResultado() {
    document.getElementById('resultado-panel').style.display = 'none';
    cocheActual = null;
}

function mostrarError(mensaje) {
    const panel = document.getElementById('error-panel');
    document.getElementById('error-mensaje').textContent = mensaje;
    panel.style.display = 'block';

    // Ocultar después de 3 segundos
    setTimeout(ocultarError, 3000);
}

function ocultarError() {
    document.getElementById('error-panel').style.display = 'none';
}

async function moverCocheAEtapa(etapaId) {
    if (!cocheActual) return;

    // No mover si ya está en esa etapa
    if (cocheActual.etapa_actual.id === etapaId) {
        alert('El coche ya está en esa etapa');
        return;
    }

    const usuario = document.getElementById('usuario-nombre').value || 'Anónimo';

    try {
        const response = await fetch(`/api/coches/${cocheActual.id}/mover`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                etapa_id: etapaId,
                usuario: usuario
            })
        });

        const data = await response.json();

        if (response.ok) {
            // Beep de éxito
            reproducirBeep(1000);

            // Actualizar vista
            cocheActual = data.coche;
            mostrarResultado(data.coche);

            // Mostrar confirmación
            alert(data.mensaje);
        } else {
            alert('Error: ' + data.error);
        }
    } catch (error) {
        alert('Error de conexión: ' + error.message);
    }
}

function reproducirBeep(frecuencia = 800) {
    try {
        const audioContext = new (window.AudioContext || window.webkitAudioContext)();
        const oscillator = audioContext.createOscillator();
        const gainNode = audioContext.createGain();

        oscillator.type = 'sine';
        oscillator.frequency.setValueAtTime(frecuencia, audioContext.currentTime);
        oscillator.connect(gainNode);
        gainNode.connect(audioContext.destination);

        gainNode.gain.setValueAtTime(0.3, audioContext.currentTime);

        oscillator.start();
        oscillator.stop(audioContext.currentTime + 0.15);
    } catch (e) {
        // Ignorar si no hay soporte de audio
    }
}
