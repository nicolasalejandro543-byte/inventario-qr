// ============ CONFIGURACIÓN Y CONSTANTES ============
const CONFIG = {
    espesoresAceptada: [4, 3.5, 3, 2],
    espesoresRebajadoLargo: [4, 3.5, 3, 2.5],
    espesoresRebajadoEspesor: [4, 3.5, 3, 2.5],
    espesoresRechazo: [4, 3.5, 3, 2.5],
    largos: [1, 1.5, 2, 2.5, 3, 4],
    largosRebajadoEspesor: [1.5, 2, 2.5, 3, 4],
    defectos: [
        "Corcho", "Rajaduras", "Falla de Largo", "Polillas",
        "Manchas azules", "Ojo de pájaro", "Manchas minerales", "Falla de espesor",
        "Nudo", "Corazón de agua", "Pudrición", "Puntas Negras", "Menguas", "Médulas"
    ],
    claveAdmin: "admin1"
};

const appState = {
    plantillas: { aceptada: {}, rebajadoLargo: {}, rebajadoEspesor: {}, rechazo: {} },
    validadores: JSON.parse(localStorage.getItem('validadores') || '[]'),
    validacionesActuales: [],
    validacionesConfirmadas: [false, false, false],
    selectedValidadorId: null,
    recepcionActualId: null
};

// ============ SISTEMA TOTP ============
class TOTP {
    constructor(secret, digits = 6, interval = 30) {
        this.secret = secret; this.digits = digits; this.interval = interval;
    }
    static generateSecret(length = 32) {
        const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';
        let secret = '';
        for (let i = 0; i < length; i++) secret += alphabet[Math.floor(Math.random() * alphabet.length)];
        return secret;
    }
    _base32Decode(secret) {
        const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';
        let bits = '';
        for (const char of secret.toUpperCase()) {
            const val = alphabet.indexOf(char);
            if (val === -1) continue;
            bits += val.toString(2).padStart(5, '0');
        }
        const bytes = [];
        for (let i = 0; i + 8 <= bits.length; i += 8) bytes.push(parseInt(bits.substr(i, 8), 2));
        return new Uint8Array(bytes);
    }
    _getTimecode(timestamp = null) {
        if (timestamp === null) timestamp = Date.now() / 1000;
        return Math.floor(timestamp / this.interval);
    }
    async generate(timestamp = null) {
        const timecode = this._getTimecode(timestamp);
        const key = this._base32Decode(this.secret);
        const msg = new Uint8Array(8);
        let tc = timecode;
        for (let i = 7; i >= 0; i--) { msg[i] = tc & 0xff; tc = Math.floor(tc / 256); }
        const cryptoKey = await crypto.subtle.importKey('raw', key, { name: 'HMAC', hash: 'SHA-1' }, false, ['sign']);
        const signature = await crypto.subtle.sign('HMAC', cryptoKey, msg);
        const hmac = new Uint8Array(signature);
        const offset = hmac[hmac.length - 1] & 0x0f;
        let code = ((hmac[offset] & 0x7f) << 24) | ((hmac[offset + 1] & 0xff) << 16) | ((hmac[offset + 2] & 0xff) << 8) | (hmac[offset + 3] & 0xff);
        code = code % Math.pow(10, this.digits);
        return code.toString().padStart(this.digits, '0');
    }
    async verify(code, window = 1) {
        code = code.toString().padStart(this.digits, '0');
        const currentTime = Date.now() / 1000;
        for (let i = -window; i <= window; i++) {
            const checkTime = currentTime + (i * this.interval);
            const generated = await this.generate(checkTime);
            if (generated === code) return true;
        }
        return false;
    }
    getProvisioningUri(name, issuer = "SkyComposite") {
        const params = new URLSearchParams({ secret: this.secret, issuer: issuer, algorithm: 'SHA1', digits: this.digits.toString(), period: this.interval.toString() });
        const label = encodeURIComponent(`${issuer}:${name}`);
        return `otpauth://totp/${label}?${params.toString()}`;
    }
}

// ============ INICIALIZACIÓN ============
document.addEventListener('DOMContentLoaded', () => {
    initTabs(); initTables(); initDefects(); initValidadores(); setDefaultDates();
});

function setDefaultDates() {
    const today = new Date().toISOString().split('T')[0];
    document.getElementById('fechaAserrado').value = today;
    document.getElementById('fechaIngreso').value = today;
    document.getElementById('fechaMedicion').value = today;
}

// ============ TABS ============
function initTabs() {
    const tabBtns = document.querySelectorAll('.tab-btn');
    tabBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            tabBtns.forEach(b => b.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
            btn.classList.add('active');
            const tabId = btn.dataset.tab;
            document.getElementById(`tab-${tabId}`).classList.add('active');
            if (tabId === 'resumen') actualizarResumen();
        });
    });
}

// ============ TABLAS DE PLANTILLAS ============
function initTables() {
    crearTablaPlantillas('tabla-aceptada', CONFIG.espesoresAceptada, CONFIG.largos, 'aceptada');
    crearTablaPlantillas('tabla-rebajado-largo', CONFIG.espesoresRebajadoLargo, CONFIG.largos, 'rebajadoLargo');
    crearTablaPlantillas('tabla-rebajado-espesor', CONFIG.espesoresRebajadoEspesor, CONFIG.largosRebajadoEspesor, 'rebajadoEspesor');
    crearTablaPlantillas('tabla-rechazo', CONFIG.espesoresRechazo, CONFIG.largos, 'rechazo');
}

function crearTablaPlantillas(containerId, espesores, largos, tipo) {
    const container = document.getElementById(containerId);
    let html = `<table class="plantilla-table"><thead><tr><th class="corner" rowspan="2">Espesor / Largo</th>`;
    largos.forEach(largo => { html += `<th colspan="2">${largo}'</th>`; });
    html += `</tr><tr>`;
    largos.forEach(() => { html += `<th class="subheader">Plant.</th><th class="subheader">BFT</th>`; });
    html += `</tr></thead><tbody>`;
    espesores.forEach(espesor => {
        html += `<tr><td class="espesor-label">${espesor}"</td>`;
        largos.forEach(largo => {
            const key = `${espesor}-${largo}`;
            appState.plantillas[tipo][key] = 0;
            html += `<td><input type="number" id="${tipo}-${key}" value="0" min="0" step="0.5" onchange="actualizarBFT('${tipo}', ${espesor}, ${largo})"></td><td><span class="bft-display" id="${tipo}-bft-${key}">0</span></td>`;
        });
        html += `</tr>`;
    });
    html += `<tr class="subtotal-row"><td>Subtotal BFT:</td>`;
    largos.forEach(largo => { html += `<td colspan="2" class="subtotal-cell"><span id="${tipo}-subtotal-${largo}">0</span></td>`; });
    html += `</tr></tbody></table>`;
    container.innerHTML = html;
}

function actualizarBFT(tipo, espesor, largo) {
    const key = `${espesor}-${largo}`;
    const input = document.getElementById(`${tipo}-${key}`);
    const plantillas = parseFloat(input.value) || 0;
    appState.plantillas[tipo][key] = plantillas;
    const bft = calcularBFTValor(largo, espesor, plantillas, tipo);
    document.getElementById(`${tipo}-bft-${key}`).textContent = bft;
    actualizarSubtotales(tipo);
}

function calcularBFTValor(largo, espesor, plantillas, tipo) {
    if (plantillas === 0) return 0;
    let bft = 0;
    if (tipo === 'aceptada' || tipo === 'rechazo') {
        bft = Math.round((largo * espesor * plantillas * 45) / 12);
    } else if (tipo === 'rebajadoLargo') {
        let espesorAjustado = espesor >= 3 ? espesor - 1 : espesor - 0.5;
        bft = Math.round((largo * espesorAjustado * plantillas * 45) / 12);
    } else if (tipo === 'rebajadoEspesor') {
        let largoAjustado = largo === 4 ? 3 : largo - 0.5;
        bft = Math.round((largoAjustado * espesor * plantillas * 45) / 12);
    }
    return bft;
}

function actualizarSubtotales(tipo) {
    let espesores, largos;
    if (tipo === 'aceptada') { espesores = CONFIG.espesoresAceptada; largos = CONFIG.largos; }
    else if (tipo === 'rebajadoLargo') { espesores = CONFIG.espesoresRebajadoLargo; largos = CONFIG.largos; }
    else if (tipo === 'rebajadoEspesor') { espesores = CONFIG.espesoresRebajadoEspesor; largos = CONFIG.largosRebajadoEspesor; }
    else { espesores = CONFIG.espesoresRechazo; largos = CONFIG.largos; }

    let totalGeneral = 0;
    largos.forEach(largo => {
        let subtotal = 0;
        espesores.forEach(espesor => {
            const bftEl = document.getElementById(`${tipo}-bft-${espesor}-${largo}`);
            if (bftEl) subtotal += parseInt(bftEl.textContent) || 0;
        });
        const subtotalEl = document.getElementById(`${tipo}-subtotal-${largo}`);
        if (subtotalEl) subtotalEl.textContent = subtotal;
        totalGeneral += subtotal;
    });
    document.getElementById(`total-${tipo === 'rebajadoLargo' ? 'rebajado-largo' : tipo === 'rebajadoEspesor' ? 'rebajado-espesor' : tipo}`).textContent = `${totalGeneral.toLocaleString()} BFT`;
}

// ============ DEFECTOS ============
function initDefects() {
    const container = document.getElementById('defectos-grid');
    let html = '';
    CONFIG.defectos.forEach((defecto, i) => {
        html += `<label class="defect-checkbox"><input type="checkbox" id="defecto-${i}" value="${defecto}"><span>${defecto}</span></label>`;
    });
    container.innerHTML = html;
}

function obtenerDefectosSeleccionados() {
    const defectos = [];
    CONFIG.defectos.forEach((defecto, i) => { if (document.getElementById(`defecto-${i}`).checked) defectos.push(defecto); });
    const otros = document.getElementById('defectosOtros').value.trim();
    if (otros) defectos.push(`Otros: ${otros}`);
    return defectos;
}

// ============ CÁLCULOS ============
function calcularVolumen() {
    const largo = parseFloat(document.getElementById('largoCamion').value) || 0;
    const alto = parseFloat(document.getElementById('altoCamion').value) || 0;
    const ancho = parseFloat(document.getElementById('anchoCamion').value) || 0;
    const volumenBFT = Math.round((largo * alto * ancho) * 423.7 * 0.5);
    document.getElementById('volumenEstimado').textContent = `${volumenBFT.toLocaleString()} BFT`;
}

function obtenerTotales() {
    const getTotalFromElement = (id) => { const text = document.getElementById(id).textContent; return parseInt(text.replace(/[^\d]/g, '')) || 0; };
    return { aceptada: getTotalFromElement('total-aceptada'), rebajadoLargo: getTotalFromElement('total-rebajado-largo'), rebajadoEspesor: getTotalFromElement('total-rebajado-espesor'), rechazo: getTotalFromElement('total-rechazo') };
}

function calcularVolumenPorLargo(largo) {
    let vol = 0;
    ['aceptada', 'rebajadoLargo', 'rebajadoEspesor'].forEach(tipo => {
        const espesores = tipo === 'aceptada' ? CONFIG.espesoresAceptada : tipo === 'rebajadoLargo' ? CONFIG.espesoresRebajadoLargo : CONFIG.espesoresRebajadoEspesor;
        const largos = tipo === 'rebajadoEspesor' ? CONFIG.largosRebajadoEspesor : CONFIG.largos;
        if (largos.includes(largo)) {
            espesores.forEach(espesor => {
                const bftEl = document.getElementById(`${tipo}-bft-${espesor}-${largo}`);
                if (bftEl) vol += parseInt(bftEl.textContent) || 0;
            });
        }
    });
    return vol;
}

function calcularPlantillasEfectivas(largo) {
    let p4 = 0, p3 = 0;
    const getPlantilla = (tipo, espesor, l) => { const inputEl = document.getElementById(`${tipo}-${espesor}-${l}`); return inputEl ? (parseFloat(inputEl.value) || 0) : 0; };
    const sumarEspesor4 = (tipo, l) => getPlantilla(tipo, 4, l) + getPlantilla(tipo, 3.5, l);
    const sumarEspesor3 = (tipo, l) => getPlantilla(tipo, 3, l) + getPlantilla(tipo, 2.5, l) + getPlantilla(tipo, 2, l);

    if (largo === 1) { p4 = sumarEspesor4('aceptada', 1); }
    else { p4 = sumarEspesor4('aceptada', largo); if (CONFIG.largosRebajadoEspesor.includes(largo)) p4 += sumarEspesor4('rebajadoEspesor', largo); }

    if (largo === 1) { p3 = sumarEspesor3('aceptada', 1) + sumarEspesor4('rebajadoLargo', 1); }
    else { p3 = sumarEspesor3('aceptada', largo) + sumarEspesor4('rebajadoLargo', largo); if (CONFIG.largosRebajadoEspesor.includes(largo)) p3 += sumarEspesor3('rebajadoEspesor', largo); }

    return { p4, p3 };
}

function actualizarResumen() {
    const totales = obtenerTotales();
    const totalBFT = totales.aceptada + totales.rebajadoLargo + totales.rebajadoEspesor;
    const totalConRechazo = totalBFT + totales.rechazo;

    document.getElementById('res-aceptada').textContent = totales.aceptada.toLocaleString();
    document.getElementById('res-reb-largo').textContent = totales.rebajadoLargo.toLocaleString();
    document.getElementById('res-reb-espesor').textContent = totales.rebajadoEspesor.toLocaleString();
    document.getElementById('res-rechazo').textContent = totales.rechazo.toLocaleString();
    document.getElementById('res-total-bft').textContent = totalBFT.toLocaleString();

    const pctRechazo = totalConRechazo > 0 ? (totales.rechazo / totalConRechazo * 100) : 0;
    document.getElementById('res-pct-rechazo').textContent = `${pctRechazo.toFixed(2)}%`;

    const largoCamion = parseFloat(document.getElementById('largoCamion').value) || 0;
    const altoCamion = parseFloat(document.getElementById('altoCamion').value) || 0;
    const anchoCamion = parseFloat(document.getElementById('anchoCamion').value) || 0;
    const volumenBase = (largoCamion * altoCamion * anchoCamion) * 423.7;
    const rendimiento = volumenBase > 0 ? (totalBFT / volumenBase) * 100 : 0;
    document.getElementById('res-rendimiento').textContent = `${rendimiento.toFixed(2)}%`;

    CONFIG.largos.forEach(largo => {
        const vol = calcularVolumenPorLargo(largo);
        const { p4, p3 } = calcularPlantillasEfectivas(largo);
        const pct = totalBFT > 0 ? (vol / totalBFT * 100) : 0;
        document.getElementById(`vol-${largo}`).textContent = vol;
        document.getElementById(`p4-${largo}`).textContent = Number.isInteger(p4) ? p4 : p4.toFixed(1);
        document.getElementById(`p3-${largo}`).textContent = Number.isInteger(p3) ? p3 : p3.toFixed(1);
        document.getElementById(`pct-${largo}`).textContent = `${pct.toFixed(1)}%`;
        const barFill = document.getElementById(`bar-${largo}`);
        const barVal = document.getElementById(`bar-val-${largo}`);
        if (barFill && barVal) { barFill.style.width = `${pct}%`; barVal.textContent = `${pct.toFixed(1)}%`; }
    });

    const precio = parseFloat(document.getElementById('precioBft').value) || 0;
    const subtotal = totalBFT * precio;
    const iva = subtotal * 0.15;
    const totalFactura = subtotal + iva;
    const retFte = subtotal * 0.0175;
    const retIva = iva;
    const totalPagar = totalFactura - retFte - retIva;
    const anticipo = parseFloat(document.getElementById('anticipo').value) || 0;
    const totalRecibir = totalPagar - anticipo;

    document.getElementById('fact-bft').textContent = totalBFT.toLocaleString();
    document.getElementById('fact-precio').textContent = `$${precio.toFixed(2)}`;
    document.getElementById('fact-subtotal').textContent = `$${subtotal.toFixed(2)}`;
    document.getElementById('fact-iva').textContent = `$${iva.toFixed(2)}`;
    document.getElementById('fact-total').textContent = `$${totalFactura.toFixed(2)}`;
    document.getElementById('fact-ret-fte').textContent = `$${retFte.toFixed(2)}`;
    document.getElementById('fact-ret-iva').textContent = `$${retIva.toFixed(2)}`;
    document.getElementById('fact-total-pagar').textContent = `$${totalPagar.toFixed(2)}`;
    document.getElementById('fact-total-recibir').textContent = `$${totalRecibir.toFixed(2)}`;
}

// ============ VALIDADORES ============
function initValidadores() { crearInputsValidacion(); actualizarListaValidadores(); }

function crearInputsValidacion() {
    const container = document.getElementById('validadores-inputs');
    let html = '';
    for (let i = 0; i < 3; i++) {
        html += `<div class="validator-row" id="validator-row-${i}"><label>Validador ${i + 1}:</label><select id="validador-select-${i}"><option value="">-- Seleccionar --</option></select><span>OTP:</span><input type="text" id="validador-otp-${i}" maxlength="6" placeholder="000000"><button class="btn btn-primary" onclick="validarOTPIndividual(${i})">Validar</button><span class="validation-status status-pending" id="validador-status-${i}">Pendiente</span></div>`;
    }
    container.innerHTML = html;
    actualizarCombosValidacion();
}

function actualizarCombosValidacion() {
    const validadoresActivos = appState.validadores.filter(v => v.activo !== false);
    for (let i = 0; i < 3; i++) {
        const select = document.getElementById(`validador-select-${i}`);
        if (!select) continue;
        const currentValue = select.value;
        select.innerHTML = '<option value="">-- Seleccionar --</option>';
        validadoresActivos.forEach(v => {
            const option = document.createElement('option');
            option.value = v.id;
            option.textContent = `${v.nombre} - ${v.cargo}`;
            select.appendChild(option);
        });
        if (currentValue) select.value = currentValue;
    }
}

function actualizarListaValidadores() {
    const tbody = document.querySelector('#tabla-validadores tbody');
    tbody.innerHTML = '';
    appState.validadores.forEach(v => {
        const tr = document.createElement('tr');
        tr.dataset.id = v.id;
        tr.onclick = () => seleccionarValidador(v.id);
        tr.innerHTML = `<td>${v.id}</td><td>${v.nombre}</td><td>${v.cargo}</td><td>${v.fechaRegistro}</td><td>${v.activo !== false ? 'Activo' : 'Inactivo'}</td>`;
        tbody.appendChild(tr);
    });
    actualizarCombosValidacion();
    guardarValidadores();
}

function seleccionarValidador(id) {
    document.querySelectorAll('#tabla-validadores tbody tr').forEach(tr => { tr.classList.toggle('selected', parseInt(tr.dataset.id) === id); });
    appState.selectedValidadorId = id;
}

async function validarOTPIndividual(index) {
    const select = document.getElementById(`validador-select-${index}`);
    const otpInput = document.getElementById(`validador-otp-${index}`);
    const statusEl = document.getElementById(`validador-status-${index}`);
    const validadorId = parseInt(select.value);
    const codigo = otpInput.value.trim();

    if (!validadorId) { showToast('Seleccione un validador', 'error'); return; }
    if (codigo.length !== 6 || !/^\d+$/.test(codigo)) { showToast('El código debe ser de 6 dígitos', 'error'); return; }

    for (let i = 0; i < 3; i++) {
        if (i !== index && appState.validacionesConfirmadas[i]) {
            const otherSelect = document.getElementById(`validador-select-${i}`);
            if (parseInt(otherSelect.value) === validadorId) { showToast('Este validador ya fue utilizado', 'error'); return; }
        }
    }

    const validador = appState.validadores.find(v => v.id === validadorId);
    if (!validador) { showToast('Validador no encontrado', 'error'); return; }

    const totp = new TOTP(validador.secret);
    const isValid = await totp.verify(codigo);

    if (isValid) {
        appState.validacionesConfirmadas[index] = true;
        appState.validacionesActuales[index] = { id: validador.id, nombre: validador.nombre, cargo: validador.cargo, timestamp: new Date().toISOString() };
        statusEl.textContent = 'Válido'; statusEl.className = 'validation-status status-valid';
        select.disabled = true; otpInput.disabled = true;
        showToast(`Validación de ${validador.nombre} exitosa`, 'success');
    } else {
        statusEl.textContent = 'Inválido'; statusEl.className = 'validation-status status-invalid';
        showToast('Código OTP inválido', 'error');
    }
    actualizarEstadoValidacion();
}

function actualizarEstadoValidacion() {
    const confirmadas = appState.validacionesConfirmadas.filter(Boolean).length;
    document.getElementById('estado-validacion').textContent = `Validaciones: ${confirmadas}/3`;
    document.getElementById('btn-exportar-validado').disabled = confirmadas < 3;
}

function reiniciarValidaciones() {
    appState.validacionesConfirmadas = [false, false, false];
    appState.validacionesActuales = [];
    for (let i = 0; i < 3; i++) {
        const select = document.getElementById(`validador-select-${i}`);
        const otpInput = document.getElementById(`validador-otp-${i}`);
        const statusEl = document.getElementById(`validador-status-${i}`);
        select.disabled = false; select.value = ''; otpInput.disabled = false; otpInput.value = '';
        statusEl.textContent = 'Pendiente'; statusEl.className = 'validation-status status-pending';
    }
    actualizarEstadoValidacion();
    showToast('Validaciones reiniciadas', 'success');
}

function agregarValidador() {
    solicitarClaveAdmin(() => {
        const nombre = document.getElementById('nuevoValidadorNombre').value.trim();
        const cargo = document.getElementById('nuevoValidadorCargo').value.trim();
        if (!nombre || !cargo) { showToast('Complete nombre y cargo', 'error'); return; }
        const secret = TOTP.generateSecret();
        const nuevoId = appState.validadores.length > 0 ? Math.max(...appState.validadores.map(v => v.id)) + 1 : 1;
        const validador = { id: nuevoId, nombre, cargo, secret, activo: true, fechaRegistro: new Date().toLocaleString('es-EC') };
        appState.validadores.push(validador);
        actualizarListaValidadores();
        document.getElementById('nuevoValidadorNombre').value = '';
        document.getElementById('nuevoValidadorCargo').value = '';
        mostrarQRNuevoValidador(validador);
        showToast('Validador agregado exitosamente', 'success');
    });
}

function mostrarQRValidador() {
    if (!appState.selectedValidadorId) { showToast('Seleccione un validador de la lista', 'error'); return; }
    const validador = appState.validadores.find(v => v.id === appState.selectedValidadorId);
    if (validador) mostrarQRNuevoValidador(validador);
}

function mostrarQRNuevoValidador(validador) {
    const modal = document.getElementById('qr-modal');
    const body = document.getElementById('qr-body');
    const totp = new TOTP(validador.secret);
    const uri = totp.getProvisioningUri(validador.nombre);
    body.innerHTML = `<div class="qr-container"><h3>${validador.nombre}</h3><p style="color: var(--color-text-muted);">${validador.cargo}</p><div id="qr-code" style="margin: 20px auto; display: inline-block;"></div><h4>Código Secreto:</h4><div class="secret-display">${validador.secret}</div><button class="btn btn-primary" onclick="copiarSecreto('${validador.secret}')">Copiar Secreto</button><div class="instructions" style="margin-top: 20px; text-align: left;"><h4>Pasos para configurar:</h4><ol><li>Abra Google Authenticator o similar en su teléfono</li><li>Agregue una nueva cuenta manualmente</li><li>Ingrese el nombre y pegue el código secreto</li><li>La app generará códigos de 6 dígitos cada 30 segundos</li></ol></div></div>`;
    modal.classList.add('active');
    new QRCode(document.getElementById('qr-code'), { text: uri, width: 180, height: 180 });
}

function copiarSecreto(secret) { navigator.clipboard.writeText(secret).then(() => { showToast('Código secreto copiado', 'success'); }); }
function cerrarQRModal() { document.getElementById('qr-modal').classList.remove('active'); }

function probarOTPValidador() {
    if (!appState.selectedValidadorId) { showToast('Seleccione un validador de la lista', 'error'); return; }
    const validador = appState.validadores.find(v => v.id === appState.selectedValidadorId);
    if (!validador) return;
    const modal = document.getElementById('otp-modal');
    const body = document.getElementById('otp-body');
    body.innerHTML = `<div style="text-align: center;"><h3>${validador.nombre}</h3><p style="margin-bottom: 20px;">Ingrese el código de 6 dígitos:</p><input type="text" id="test-otp-input" maxlength="6" style="font-size: 1.5rem; text-align: center; width: 150px; padding: 12px; letter-spacing: 4px;"><div class="btn-group" style="justify-content: center; margin-top: 20px;"><button class="btn btn-primary" onclick="verificarOTPTest(${validador.id})">Verificar</button><button class="btn btn-secondary" onclick="cerrarOTPModal()">Cancelar</button></div></div>`;
    modal.classList.add('active');
    document.getElementById('test-otp-input').focus();
}

async function verificarOTPTest(validadorId) {
    const codigo = document.getElementById('test-otp-input').value.trim();
    if (codigo.length !== 6 || !/^\d+$/.test(codigo)) { showToast('El código debe ser de 6 dígitos', 'error'); return; }
    const validador = appState.validadores.find(v => v.id === validadorId);
    const totp = new TOTP(validador.secret);
    const isValid = await totp.verify(codigo);
    if (isValid) { showToast('Código OTP válido!', 'success'); cerrarOTPModal(); }
    else { showToast('Código OTP inválido', 'error'); }
}

function cerrarOTPModal() { document.getElementById('otp-modal').classList.remove('active'); }

function eliminarValidador() {
    if (!appState.selectedValidadorId) { showToast('Seleccione un validador de la lista', 'error'); return; }
    solicitarClaveAdmin(() => {
        if (confirm('¿Está seguro de eliminar este validador?')) {
            appState.validadores = appState.validadores.filter(v => v.id !== appState.selectedValidadorId);
            appState.selectedValidadorId = null;
            actualizarListaValidadores();
            showToast('Validador eliminado', 'success');
        }
    });
}

function solicitarClaveAdmin(callback) {
    const modal = document.getElementById('admin-modal');
    const input = document.getElementById('admin-password');
    const btn = document.getElementById('admin-confirm-btn');
    input.value = ''; modal.classList.add('active'); input.focus();
    btn.onclick = () => {
        if (input.value === CONFIG.claveAdmin) { modal.classList.remove('active'); callback(); }
        else { showToast('Clave de administrador incorrecta', 'error'); }
    };
}

function cerrarAdminModal() { document.getElementById('admin-modal').classList.remove('active'); }
function guardarValidadores() { localStorage.setItem('validadores', JSON.stringify(appState.validadores)); }

// ============ GUARDAR/CARGAR ============
function guardarRecepcion() {
    const datos = recopilarDatos();
    let historial = JSON.parse(localStorage.getItem('historialRecepciones') || '[]');
    if (appState.recepcionActualId) {
        const index = historial.findIndex(r => r.id === appState.recepcionActualId);
        if (index !== -1) historial[index] = { ...datos, id: appState.recepcionActualId };
    } else {
        const nuevoId = Date.now();
        historial.push({ ...datos, id: nuevoId });
        appState.recepcionActualId = nuevoId;
    }
    localStorage.setItem('historialRecepciones', JSON.stringify(historial));
    showToast('Recepción guardada exitosamente', 'success');
}

function recopilarDatos() {
    actualizarResumen();
    const totales = obtenerTotales();
    return {
        fecha: new Date().toISOString(), proveedor: document.getElementById('proveedor').value,
        fechaAserrado: document.getElementById('fechaAserrado').value, fechaIngreso: document.getElementById('fechaIngreso').value,
        fechaMedicion: document.getElementById('fechaMedicion').value, viajeProveedor: document.getElementById('viajeProveedor').value,
        guiaForestal: document.getElementById('guiaForestal').value, viajeCons: document.getElementById('viajeCons').value,
        ticket: document.getElementById('ticket').value, placa: document.getElementById('placa').value,
        largoCamion: document.getElementById('largoCamion').value, altoCamion: document.getElementById('altoCamion').value,
        anchoCamion: document.getElementById('anchoCamion').value, precioBft: document.getElementById('precioBft').value,
        anticipo: document.getElementById('anticipo').value, plantillas: JSON.parse(JSON.stringify(appState.plantillas)),
        defectos: obtenerDefectosSeleccionados(), totales, totalBFT: totales.aceptada + totales.rebajadoLargo + totales.rebajadoEspesor
    };
}

function verHistorial() {
    const historial = JSON.parse(localStorage.getItem('historialRecepciones') || '[]');
    const body = document.getElementById('historial-body');
    if (historial.length === 0) {
        body.innerHTML = '<p style="text-align: center; color: var(--color-text-muted);">No hay recepciones guardadas.</p>';
    } else {
        let html = '<div class="table-container"><table class="validators-table"><thead><tr><th>Fecha</th><th>Proveedor</th><th>Guía</th><th>Total BFT</th><th>Acciones</th></tr></thead><tbody>';
        historial.reverse().forEach(r => {
            html += `<tr><td>${new Date(r.fecha).toLocaleDateString('es-EC')}</td><td>${r.proveedor || '-'}</td><td>${r.guiaForestal || '-'}</td><td>${r.totalBFT?.toLocaleString() || '0'}</td><td><button class="btn btn-primary" style="padding: 6px 12px; font-size: 0.8rem;" onclick="cargarRecepcion(${r.id})">Cargar</button><button class="btn btn-danger" style="padding: 6px 12px; font-size: 0.8rem;" onclick="eliminarRecepcion(${r.id})">Eliminar</button></td></tr>`;
        });
        html += '</tbody></table></div>';
        body.innerHTML = html;
    }
    document.getElementById('historial-modal').classList.add('active');
}

function cerrarHistorial() { document.getElementById('historial-modal').classList.remove('active'); }

function cargarRecepcion(id) {
    const historial = JSON.parse(localStorage.getItem('historialRecepciones') || '[]');
    const recepcion = historial.find(r => r.id === id);
    if (!recepcion) { showToast('Recepción no encontrada', 'error'); return; }

    document.getElementById('proveedor').value = recepcion.proveedor || '';
    document.getElementById('fechaAserrado').value = recepcion.fechaAserrado || '';
    document.getElementById('fechaIngreso').value = recepcion.fechaIngreso || '';
    document.getElementById('fechaMedicion').value = recepcion.fechaMedicion || '';
    document.getElementById('viajeProveedor').value = recepcion.viajeProveedor || '';
    document.getElementById('guiaForestal').value = recepcion.guiaForestal || '';
    document.getElementById('viajeCons').value = recepcion.viajeCons || '';
    document.getElementById('ticket').value = recepcion.ticket || '';
    document.getElementById('placa').value = recepcion.placa || '';
    document.getElementById('largoCamion').value = recepcion.largoCamion || 0;
    document.getElementById('altoCamion').value = recepcion.altoCamion || 0;
    document.getElementById('anchoCamion').value = recepcion.anchoCamion || 0;
    document.getElementById('precioBft').value = recepcion.precioBft || 0.49;
    document.getElementById('anticipo').value = recepcion.anticipo || 0;

    if (recepcion.plantillas) {
        Object.keys(recepcion.plantillas).forEach(tipo => {
            Object.keys(recepcion.plantillas[tipo]).forEach(key => {
                const input = document.getElementById(`${tipo}-${key}`);
                if (input) { input.value = recepcion.plantillas[tipo][key]; const [espesor, largo] = key.split('-').map(Number); actualizarBFT(tipo, espesor, largo); }
            });
        });
    }

    CONFIG.defectos.forEach((defecto, i) => { document.getElementById(`defecto-${i}`).checked = recepcion.defectos?.includes(defecto) || false; });

    appState.recepcionActualId = id;
    calcularVolumen(); actualizarResumen(); cerrarHistorial();
    showToast('Recepción cargada', 'success');
}

function eliminarRecepcion(id) {
    if (!confirm('¿Está seguro de eliminar esta recepción?')) return;
    let historial = JSON.parse(localStorage.getItem('historialRecepciones') || '[]');
    historial = historial.filter(r => r.id !== id);
    localStorage.setItem('historialRecepciones', JSON.stringify(historial));
    verHistorial();
    showToast('Recepción eliminada', 'success');
}

function limpiarTodo() {
    if (!confirm('¿Está seguro de limpiar todos los datos?')) return;
    document.getElementById('proveedor').value = '';
    document.getElementById('viajeProveedor').value = '';
    document.getElementById('guiaForestal').value = '';
    document.getElementById('viajeCons').value = '';
    document.getElementById('ticket').value = '';
    document.getElementById('placa').value = '';
    document.getElementById('largoCamion').value = 0;
    document.getElementById('altoCamion').value = 0;
    document.getElementById('anchoCamion').value = 0;
    document.getElementById('anticipo').value = 0;
    document.getElementById('defectosOtros').value = '';

    ['aceptada', 'rebajadoLargo', 'rebajadoEspesor', 'rechazo'].forEach(tipo => {
        Object.keys(appState.plantillas[tipo]).forEach(key => {
            const input = document.getElementById(`${tipo}-${key}`);
            if (input) input.value = 0;
        });
    });
    CONFIG.defectos.forEach((_, i) => { document.getElementById(`defecto-${i}`).checked = false; });

    appState.recepcionActualId = null;
    initTables(); calcularVolumen(); actualizarResumen(); setDefaultDates();
    showToast('Datos limpiados', 'success');
}

// ============ EXPORTAR ============
function exportarExcel() {
    actualizarResumen();
    const datos = recopilarDatos();
    const totales = obtenerTotales();
    const wb = XLSX.utils.book_new();

    const resumenData = [
        ['SKY COMPOSITE - RECEPCIÓN DE MADERA VERDE'], [''],
        ['DATOS GENERALES'], ['Proveedor:', datos.proveedor], ['Guía Forestal:', datos.guiaForestal],
        ['Fecha Ingreso:', datos.fechaIngreso], ['Placa:', datos.placa], [''],
        ['RESUMEN DE VOLÚMENES (BFT)'], ['Total Aceptada:', totales.aceptada],
        ['Total Rebajado Largo:', totales.rebajadoLargo], ['Total Rebajado Espesor:', totales.rebajadoEspesor],
        ['Total Rechazo:', totales.rechazo], ['TOTAL BFT:', datos.totalBFT], [''],
        ['FACTURACIÓN'], ['Precio BFT:', `$${datos.precioBft}`],
        ['Subtotal:', `$${(datos.totalBFT * datos.precioBft).toFixed(2)}`], [''],
        ['DEFECTOS:', datos.defectos.join(', ') || 'Ninguno']
    ];

    const wsResumen = XLSX.utils.aoa_to_sheet(resumenData);
    XLSX.utils.book_append_sheet(wb, wsResumen, 'Resumen');

    ['aceptada', 'rebajadoLargo', 'rebajadoEspesor', 'rechazo'].forEach(tipo => {
        const tipoConfig = {
            aceptada: { espesores: CONFIG.espesoresAceptada, largos: CONFIG.largos, nombre: 'Aceptada' },
            rebajadoLargo: { espesores: CONFIG.espesoresRebajadoLargo, largos: CONFIG.largos, nombre: 'Rebajado Largo' },
            rebajadoEspesor: { espesores: CONFIG.espesoresRebajadoEspesor, largos: CONFIG.largosRebajadoEspesor, nombre: 'Rebajado Espesor' },
            rechazo: { espesores: CONFIG.espesoresRechazo, largos: CONFIG.largos, nombre: 'Rechazo' }
        }[tipo];
        const data = [['Espesor \\ Largo', ...tipoConfig.largos.map(l => `${l}'`)]];
        tipoConfig.espesores.forEach(espesor => {
            const row = [`${espesor}"`];
            tipoConfig.largos.forEach(largo => {
                const input = document.getElementById(`${tipo}-${espesor}-${largo}`);
                row.push(input ? parseFloat(input.value) || 0 : 0);
            });
            data.push(row);
        });
        const ws = XLSX.utils.aoa_to_sheet(data);
        XLSX.utils.book_append_sheet(wb, ws, tipoConfig.nombre);
    });

    XLSX.writeFile(wb, `Recepcion_${datos.proveedor || 'madera'}_${new Date().toISOString().split('T')[0]}.xlsx`);
    showToast('Excel exportado', 'success');
}

function exportarPDF() { generarPDF(false); }
function exportarPDFValidado() {
    if (appState.validacionesConfirmadas.filter(Boolean).length < 3) { showToast('Se requieren 3 validaciones', 'error'); return; }
    generarPDF(true);
}

function generarPDF(incluirValidacion) {
    actualizarResumen();
    const { jsPDF } = window.jspdf;
    const doc = new jsPDF('p', 'mm', 'a4');
    const datos = recopilarDatos();
    const totales = obtenerTotales();
    const pageWidth = 210, margin = 10, contentWidth = pageWidth - (margin * 2);

    // Header
    doc.setFillColor(37, 150, 190); doc.rect(0, 0, pageWidth, 20, 'F');
    doc.setTextColor(255, 255, 255); doc.setFontSize(14); doc.setFont('helvetica', 'bold');
    doc.text('SKY COMPOSITE - Recepción de Madera Verde', margin, 9);
    doc.setFontSize(9);
    doc.text(new Date().toLocaleDateString('es-EC') + ' ' + new Date().toLocaleTimeString('es-EC', {hour: '2-digit', minute: '2-digit'}), pageWidth - margin, 9, { align: 'right' });
    if (datos.guiaForestal) { doc.setFontSize(10); doc.text(`Guía Forestal: ${datos.guiaForestal}`, pageWidth - margin, 16, { align: 'right' }); }

    doc.setTextColor(0, 0, 0);
    let y = 26;

    // Datos Generales
    doc.setFillColor(37, 150, 190); doc.rect(margin, y, contentWidth, 6, 'F');
    doc.setTextColor(255, 255, 255); doc.setFontSize(9); doc.setFont('helvetica', 'bold');
    doc.text('DATOS GENERALES', margin + 2, y + 4.2);
    doc.setTextColor(0, 0, 0); y += 10;

    doc.setFontSize(7);
    const col1X = margin, col1ValX = margin + 28, col2X = margin + 95, col2ValX = margin + 123;
    const datosGen = [
        ['Proveedor:', datos.proveedor || '-', 'Placa:', datos.placa || '-'],
        ['Fecha Aserrado:', datos.fechaAserrado || '-', 'Ticket:', datos.ticket || '-'],
        ['Fecha Ingreso:', datos.fechaIngreso || '-', '# Viaje Prov.:', datos.viajeProveedor || '-'],
        ['Fecha Medición:', datos.fechaMedicion || '-', '# Viaje Cons.:', datos.viajeCons || '-'],
    ];
    datosGen.forEach(row => {
        doc.setFont('helvetica', 'bold'); doc.text(row[0], col1X, y);
        doc.setFont('helvetica', 'normal'); doc.text(row[1], col1ValX, y);
        doc.setFont('helvetica', 'bold'); doc.text(row[2], col2X, y);
        doc.setFont('helvetica', 'normal'); doc.text(row[3], col2ValX, y);
        y += 4;
    });

    const largoCamion = datos.largoCamion || 0, altoCamion = datos.altoCamion || 0, anchoCamion = datos.anchoCamion || 0;
    const volEstimado = Math.round((largoCamion * altoCamion * anchoCamion) * 423.7 * 0.5);
    doc.setFont('helvetica', 'bold'); doc.text('Medidas Camión:', col1X, y);
    doc.setFont('helvetica', 'normal'); doc.text(`${largoCamion}m x ${altoCamion}m x ${anchoCamion}m`, col1ValX, y);
    doc.setFont('helvetica', 'bold'); doc.text('Vol. Estimado:', col2X, y);
    doc.setFont('helvetica', 'normal'); doc.text(`${volEstimado.toLocaleString()} BFT`, col2ValX, y);
    y += 4;

    // Tablas de plantillas
    const crearTablaMini = (titulo, tipo, espesores, largos, startY, color) => {
        doc.setFillColor(...color); doc.rect(margin, startY, contentWidth, 5, 'F');
        doc.setTextColor(255, 255, 255); doc.setFontSize(8); doc.setFont('helvetica', 'bold');
        doc.text(titulo, margin + 2, startY + 3.6);
        doc.setTextColor(0, 0, 0);
        const tableData = [], headers = ['Esp.', ...largos.map(l => `${l}'`), 'Total'];
        espesores.forEach(esp => {
            const row = [`${esp}"`]; let rowTotal = 0;
            largos.forEach(largo => {
                const inputEl = document.getElementById(`${tipo}-${esp}-${largo}`);
                const val = inputEl ? (parseFloat(inputEl.value) || 0) : 0;
                row.push(val > 0 ? val.toString() : '-'); rowTotal += val;
            });
            row.push(rowTotal > 0 ? rowTotal.toString() : '-');
            tableData.push(row);
        });
        doc.autoTable({
            startY: startY + 5, head: [headers], body: tableData, theme: 'grid',
            styles: { fontSize: 6, cellPadding: 1.5, halign: 'center', valign: 'middle' },
            headStyles: { fillColor: color, fontSize: 6, halign: 'center', valign: 'middle' },
            columnStyles: { 0: { cellWidth: 12 } }, margin: { left: margin, right: margin }, tableWidth: contentWidth
        });
        return doc.lastAutoTable.finalY;
    };

    y = crearTablaMini('ACEPTADA', 'aceptada', CONFIG.espesoresAceptada, CONFIG.largos, y, [39, 174, 96]); y += 2;
    y = crearTablaMini('REBAJADO EN LARGO', 'rebajadoLargo', CONFIG.espesoresRebajadoLargo, CONFIG.largos, y, [230, 126, 34]); y += 2;
    y = crearTablaMini('REBAJADO EN ESPESOR', 'rebajadoEspesor', CONFIG.espesoresRebajadoEspesor, CONFIG.largosRebajadoEspesor, y, [155, 89, 182]); y += 2;
    y = crearTablaMini('RECHAZO', 'rechazo', CONFIG.espesoresRechazo, CONFIG.largos, y, [192, 57, 43]); y += 4;

    // Resumen por largo
    doc.setFillColor(52, 152, 219); doc.rect(margin, y, contentWidth, 5, 'F');
    doc.setTextColor(255, 255, 255); doc.setFontSize(8); doc.setFont('helvetica', 'bold');
    doc.text('RESUMEN POR LARGO', margin + 2, y + 3.6);
    doc.setTextColor(0, 0, 0); y += 5;

    const resumenHeaders = ['', ...CONFIG.largos.map(l => `${l}'`)];
    const resumenData = [
        ['Volumen', ...CONFIG.largos.map(l => calcularVolumenPorLargo(l).toString())],
        ['Plant. 4"', ...CONFIG.largos.map(l => { const {p4} = calcularPlantillasEfectivas(l); return Number.isInteger(p4) ? p4.toString() : p4.toFixed(1); })],
        ['Plant. 3"', ...CONFIG.largos.map(l => { const {p3} = calcularPlantillasEfectivas(l); return Number.isInteger(p3) ? p3.toString() : p3.toFixed(1); })],
        ['%', ...CONFIG.largos.map(l => { const vol = calcularVolumenPorLargo(l); const pct = datos.totalBFT > 0 ? (vol / datos.totalBFT * 100) : 0; return `${pct.toFixed(1)}%`; })]
    ];
    doc.autoTable({
        startY: y, head: [resumenHeaders], body: resumenData, theme: 'grid',
        styles: { fontSize: 6, cellPadding: 1.5, halign: 'center', valign: 'middle' },
        headStyles: { fillColor: [52, 152, 219], fontSize: 6, halign: 'center' },
        columnStyles: { 0: { cellWidth: 22, halign: 'left' } }, margin: { left: margin, right: margin }, tableWidth: contentWidth
    });
    y = doc.lastAutoTable.finalY + 3;

    // Resumen y Facturación
    const halfWidth = (contentWidth - 6) / 2;
    const precio = parseFloat(datos.precioBft) || 0, subtotal = datos.totalBFT * precio, iva = subtotal * 0.15;
    const totalFactura = subtotal + iva, retFte = subtotal * 0.0175, retIva = iva;
    const totalPagar = totalFactura - retFte - retIva, anticipo = parseFloat(datos.anticipo) || 0, totalRecibir = totalPagar - anticipo;
    const volBase = (largoCamion * altoCamion * anchoCamion) * 423.7;
    const rendimiento = volBase > 0 ? (datos.totalBFT / volBase * 100) : 0;
    const pctRechazo = (datos.totalBFT + totales.rechazo) > 0 ? (totales.rechazo / (datos.totalBFT + totales.rechazo) * 100) : 0;

    const resumenTableData = [
        ['Aceptada:', `${totales.aceptada.toLocaleString()} BFT`], ['Reb. Largo:', `${totales.rebajadoLargo.toLocaleString()} BFT`],
        ['Reb. Espesor:', `${totales.rebajadoEspesor.toLocaleString()} BFT`], ['Rechazo:', `${totales.rechazo.toLocaleString()} BFT`],
        ['TOTAL BFT:', `${datos.totalBFT.toLocaleString()} BFT`], ['% Rechazo:', `${pctRechazo.toFixed(2)}%`], ['Rendimiento:', `${rendimiento.toFixed(2)}%`]
    ];
    doc.autoTable({
        startY: y, head: [['RESUMEN VOLÚMENES', '']], body: resumenTableData, theme: 'plain',
        styles: { fontSize: 5.5, cellPadding: 1 }, headStyles: { fillColor: [41, 128, 185], textColor: 255, fontSize: 6, fontStyle: 'bold' },
        columnStyles: { 0: { cellWidth: 28 }, 1: { cellWidth: halfWidth - 30, halign: 'right' } },
        margin: { left: margin }, tableWidth: halfWidth,
        didParseCell: function(data) { if (data.row.index === 4 && data.section === 'body') data.cell.styles.fontStyle = 'bold'; }
    });
    const resumenEndY = doc.lastAutoTable.finalY;

    const factTableData = [
        ['BFT Total:', datos.totalBFT.toLocaleString()], ['Precio BFT:', `$${precio.toFixed(2)}`],
        ['Subtotal:', `$${subtotal.toFixed(2)}`], ['IVA 15%:', `$${iva.toFixed(2)}`],
        ['Total Fact.:', `$${totalFactura.toFixed(2)}`], ['Ret. Fte 1.75%:', `$${retFte.toFixed(2)}`],
        ['Ret. IVA:', `$${retIva.toFixed(2)}`], ['Total Pagar:', `$${totalPagar.toFixed(2)}`],
        ['Anticipo:', `$${anticipo.toFixed(2)}`], ['A RECIBIR:', `$${totalRecibir.toFixed(2)}`]
    ];
    doc.autoTable({
        startY: y, head: [['FACTURACIÓN', '']], body: factTableData, theme: 'plain',
        styles: { fontSize: 5.5, cellPadding: 1 }, headStyles: { fillColor: [41, 128, 185], textColor: 255, fontSize: 6, fontStyle: 'bold' },
        columnStyles: { 0: { cellWidth: 28 }, 1: { cellWidth: halfWidth - 30, halign: 'right' } },
        margin: { left: margin + halfWidth + 6 }, tableWidth: halfWidth,
        didParseCell: function(data) { if ((data.row.index === 7 || data.row.index === 9) && data.section === 'body') data.cell.styles.fontStyle = 'bold'; }
    });
    y = Math.max(resumenEndY, doc.lastAutoTable.finalY) + 3;

    // Defectos
    const defectos = obtenerDefectosSeleccionados();
    doc.setFontSize(6); doc.setFont('helvetica', 'bold');
    doc.text('DEFECTOS:', margin, y);
    doc.setFont('helvetica', 'normal');
    const defectosText = defectos.length > 0 ? defectos.join(', ') : 'Ninguno';
    doc.text(defectosText, margin + 18, y, { maxWidth: contentWidth - 18 });
    const defectosEndY = y;

    // Sello de validación
    if (incluirValidacion && appState.validacionesActuales.length >= 3) {
        const hashData = `${datos.proveedor}${datos.guiaForestal}${datos.totalBFT}`;
        const codigoSello = 'SKY-' + btoa(hashData).substring(0, 12).toUpperCase();
        const pageHeight = 297, selloWidth = 120, selloHeight = 12, bottomMargin = 10;
        const availableSpace = pageHeight - bottomMargin - defectosEndY - 5;
        const selloY = defectosEndY + 5 + (availableSpace - selloHeight) / 2;
        const selloX = (pageWidth - selloWidth) / 2;
        doc.setFillColor(232, 245, 233); doc.setDrawColor(26, 95, 42); doc.setLineWidth(0.3);
        doc.roundedRect(selloX, selloY, selloWidth, selloHeight, 1, 1, 'FD');
        doc.setTextColor(26, 95, 42); doc.setFontSize(8); doc.setFont('helvetica', 'bold');
        doc.text('DOCUMENTO VALIDADO', pageWidth / 2, selloY + 4, { align: 'center' });
        doc.setFontSize(6); doc.setFont('helvetica', 'normal');
        const validadores = appState.validacionesActuales.map(v => v.nombre).join(' | ');
        doc.text(`${codigoSello}  •  ${validadores}  •  ${new Date().toLocaleDateString('es-EC')}`, pageWidth / 2, selloY + 9, { align: 'center' });
    }

    const filename = incluirValidacion ? `Recepcion_VALIDADO_${datos.proveedor || 'madera'}_${datos.guiaForestal || ''}.pdf` : `Recepcion_${datos.proveedor || 'madera'}_${datos.guiaForestal || ''}.pdf`;
    doc.save(filename);
    showToast(`PDF ${incluirValidacion ? 'validado ' : ''}exportado`, 'success');
}

// ============ UTILIDADES ============
function showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = message;
    container.appendChild(toast);
    setTimeout(() => toast.remove(), 3000);
}
