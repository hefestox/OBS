// ==================== CONFIG ====================
const API_BASE = 'http://localhost:5000/api';
const REFRESH_INTERVAL = 5000; // 5 segundos

// ==================== TAB NAVIGATION ====================
function showTab(tabName) {
    // Ocultar todos
    const tabs = document.querySelectorAll('.tab-content');
    tabs.forEach(tab => tab.classList.remove('active'));

    // Remover active dos botões
    const buttons = document.querySelectorAll('.nav-btn');
    buttons.forEach(btn => btn.classList.remove('active'));

    // Mostrar selecionado
    document.getElementById(tabName).classList.add('active');
    event.target.classList.add('active');
}

// ==================== HEALTH CHECK ====================
function checkHealth() {
    fetch(`${API_BASE}/health`)
        .then(res => res.json())
        .then(data => {
            const status = document.getElementById('status');
            const statusText = document.getElementById('status-text');
            const apiStatus = document.getElementById('api-status');

            if (data.status === 'healthy') {
                status.classList.add('connected');
                status.classList.remove('disconnected');
                statusText.textContent = 'Conectado';
                apiStatus.innerHTML = '✅ API Operacional';
            } else {
                status.classList.add('disconnected');
                statusText.textContent = 'Desconectado';
                apiStatus.innerHTML = '❌ API Indisponível';
            }
        })
        .catch(err => {
            console.error('Erro ao verificar saúde:', err);
            document.getElementById('status').classList.add('disconnected');
            document.getElementById('status-text').textContent = 'Erro';
            document.getElementById('api-status').innerHTML = '❌ Erro de Conexão';
        });
}

// ==================== PREÇOS ====================
function getPriceData() {
    const symbol = document.getElementById('symbol-input').value || 'BTCUSDT';
    const result = document.getElementById('price-result');

    result.innerHTML = '⏳ Carregando...';

    fetch(`${API_BASE}/prices?symbol=${symbol}`)
        .then(res => res.json())
        .then(data => {
            if (data.error) {
                result.innerHTML = `❌ Erro: ${data.error}`;
            } else {
                result.innerHTML = `
                    <h4>${data.symbol}</h4>
                    <p><strong>Preço:</strong> $${parseFloat(data.data.price).toFixed(2)}</p>
                    <p><strong>Bid:</strong> $${parseFloat(data.data.bid).toFixed(2)}</p>
                    <p><strong>Ask:</strong> $${parseFloat(data.data.ask).toFixed(2)}</p>
                    <p><strong>Timestamp:</strong> ${new Date(data.timestamp).toLocaleString('pt-BR')}</p>
                `;
            }
        })
        .catch(err => {
            result.innerHTML = `❌ Erro: ${err.message}`;
        });
}

// ==================== PUMPS ====================
function loadPumps() {
    const list = document.getElementById('pumps-list');
    const count = document.getElementById('pump-count');

    list.innerHTML = '⏳ Carregando pumps...';

    fetch(`${API_BASE}/pumps`)
        .then(res => res.json())
        .then(data => {
            count.textContent = data.count;

            if (data.pumps.length === 0) {
                list.innerHTML = '<p>Nenhum pump detectado no momento</p>';
                return;
            }

            list.innerHTML = data.pumps.map(pump => `
                <div class="list-item">
                    <div class="list-item-header">
                        <span class="list-item-title">🔥 ${pump.symbol}</span>
                        <span class="list-item-subtitle">${pump.status}</span>
                    </div>
                    <div class="list-item-value">
                        <span style="color: #fca5a5; font-size: 18px; font-weight: bold;">+${pump.change_percent}%</span>
                        <span class="badge ${pump.risk_level.toLowerCase()}">${pump.risk_level}</span>
                        <span style="font-size: 11px; color: #94a3b8;">Vol: $${Math.round(pump.volume)}</span>
                    </div>
                </div>
            `).join('');
        })
        .catch(err => {
            list.innerHTML = `❌ Erro: ${err.message}`;
        });
}

// ==================== ANÁLISE IA ====================
function analyzeSymbol() {
    const symbol = document.getElementById('analyze-symbol').value || 'BTCUSDT';
    const result = document.getElementById('analysis-result');

    result.innerHTML = '⏳ Analisando com IA... Por favor aguarde...';

    fetch(`${API_BASE}/analyze`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbol: symbol })
    })
        .then(res => res.json())
        .then(data => {
            if (data.error) {
                result.innerHTML = `❌ Erro: ${data.error}`;
            } else {
                result.innerHTML = `
                    <h4>Análise de ${data.symbol}</h4>
                    <p><strong>IA:</strong> ${data.model}</p>
                    <hr>
                    ${data.analysis}
                    <hr>
                    <p style="font-size: 11px; color: #94a3b8;">Atualizado em: ${new Date(data.timestamp).toLocaleString('pt-BR')}</p>
                `;
            }
        })
        .catch(err => {
            result.innerHTML = `❌ Erro: ${err.message}`;
        });
}

// ==================== ALERTAS ====================
function loadAlerts() {
    const list = document.getElementById('alerts-list');

    list.innerHTML = '⏳ Carregando alertas...';

    fetch(`${API_BASE}/alerts`)
        .then(res => res.json())
        .then(data => {
            if (data.total === 0) {
                list.innerHTML = '<p>Nenhum alerta no momento</p>';
                return;
            }

            let html = '';

            if (data.alerts.pump_detected && data.alerts.pump_detected.length > 0) {
                html += '<h4>⚡ Pumps Detectados</h4>';
                html += data.alerts.pump_detected.map(alert => `
                    <div class="list-item">
                        <span>${alert}</span>
                        <span class="badge high">Crítico</span>
                    </div>
                `).join('');
            }

            if (data.alerts.high_volatility && data.alerts.high_volatility.length > 0) {
                html += '<h4>📈 Alta Volatilidade</h4>';
                html += data.alerts.high_volatility.map(alert => `
                    <div class="list-item">
                        <span>${alert}</span>
                        <span class="badge medium">Atenção</span>
                    </div>
                `).join('');
            }

            if (html === '') {
                html = '<p>Nenhum alerta no momento</p>';
            }

            list.innerHTML = html;
        })
        .catch(err => {
            list.innerHTML = `❌ Erro: ${err.message}`;
        });
}

// ==================== INITIALIZATION ====================
window.addEventListener('load', () => {
    console.log('🚀 PUMPS Dashboard inicializado');

    // Check health
    checkHealth();

    // Atualizar a cada 5 segundos
    setInterval(checkHealth, REFRESH_INTERVAL);

    // Carregar dados iniciais
    setTimeout(() => {
        getPriceData();
        loadPumps();
        loadAlerts();
    }, 1000);
});
