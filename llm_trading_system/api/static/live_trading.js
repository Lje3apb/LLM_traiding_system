/**
 * Live Trading UI Controller
 * Manages real-time trading session, WebSocket updates, and chart visualization
 */

// Global state
let currentSessionId = null;
let currentMode = 'paper';
let ws = null;
let chartInstance = null;
let candlestickSeries = null;
let volumeSeries = null;
let sessionStatus = 'none';

// Initialize on page load
document.addEventListener('DOMContentLoaded', function() {
    setupEventListeners();
    updateUIState();
});

// ============================================================================
// Event Listeners
// ============================================================================

function setupEventListeners() {
    // Mode selector
    document.querySelectorAll('input[name="trading-mode"]').forEach(radio => {
        radio.addEventListener('change', handleModeChange);
    });

    // Control buttons
    document.getElementById('create-session-btn').addEventListener('click', createSession);
    document.getElementById('start-session-btn').addEventListener('click', startSession);
    document.getElementById('stop-session-btn').addEventListener('click', stopSession);
    document.getElementById('refresh-balance-btn').addEventListener('click', refreshBalance);

    // Chart controls
    document.getElementById('toggle-indicators-rsi').addEventListener('change', toggleRSI);
    document.getElementById('toggle-indicators-bb').addEventListener('change', toggleBB);
    document.getElementById('toggle-indicators-ema').addEventListener('change', toggleEMA);
    document.getElementById('toggle-trades').addEventListener('change', toggleTrades);
}

// ============================================================================
// Mode Handling
// ============================================================================

function handleModeChange(event) {
    currentMode = event.target.value;
    const depositInput = document.getElementById('initial-deposit');
    const depositLabel = document.getElementById('deposit-label');
    const refreshBtn = document.getElementById('refresh-balance-btn');

    if (currentMode === 'paper') {
        depositInput.disabled = false;
        depositLabel.textContent = 'Initial Deposit (USDT)';
        refreshBtn.style.display = 'none';
    } else {
        depositInput.disabled = true;
        depositLabel.textContent = 'Live Balance (USDT)';
        refreshBtn.style.display = 'inline-block';
        // Fetch live balance from exchange
        fetchLiveBalance();
    }

    updateModeBadge();
}

function updateModeBadge() {
    const badge = document.getElementById('mode-badge');
    badge.textContent = currentMode === 'paper' ? 'Paper' : 'Real';
    badge.className = `mode-badge ${currentMode}`;

    const accountBadge = document.getElementById('account-mode-indicator');
    accountBadge.textContent = currentMode === 'paper' ? 'Paper' : 'Real';
    accountBadge.className = `mode-badge ${currentMode}`;
}

async function fetchLiveBalance() {
    // This would query the exchange API for live balance
    // For now, just show placeholder
    const depositInput = document.getElementById('initial-deposit');
    depositInput.value = '0';
    depositInput.placeholder = 'Loading...';

    // TODO: Implement actual API call
    // const response = await fetch('/api/exchange/balance');
    // const data = await response.json();
    // depositInput.value = data.balance;
}

async function refreshBalance() {
    await fetchLiveBalance();
}

// ============================================================================
// Session Management
// ============================================================================

async function createSession() {
    const strategySelect = document.getElementById('strategy-select');
    const symbolSelect = document.getElementById('symbol-select');
    const timeframeSelect = document.getElementById('timeframe-select');
    const depositInput = document.getElementById('initial-deposit');

    if (!strategySelect.value) {
        alert('Please select a strategy');
        return;
    }

    const config = {
        mode: currentMode,
        symbol: symbolSelect.value,
        timeframe: timeframeSelect.value,
        strategy_config: strategySelect.value,  // Strategy name to load
        initial_deposit: parseFloat(depositInput.value),
        llm_enabled: false,  // TODO: Add LLM toggle
        fee_rate: 0.0005,
        slippage_bps: 1.0,
        poll_interval: 1.0
    };

    try {
        const response = await fetch('/api/live/sessions', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(config)
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to create session');
        }

        const data = await response.json();
        currentSessionId = data.session_id;
        sessionStatus = data.status;

        updateSessionDisplay(data);
        updateUIState();
        initializeChart();

        console.log('Session created:', currentSessionId);
    } catch (error) {
        console.error('Failed to create session:', error);
        alert(`Failed to create session: ${error.message}`);
    }
}

async function startSession() {
    if (!currentSessionId) {
        alert('Please create a session first');
        return;
    }

    try {
        const response = await fetch(`/api/live/sessions/${currentSessionId}/start`, {
            method: 'POST'
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to start session');
        }

        const data = await response.json();
        sessionStatus = data.status;

        updateSessionDisplay(data);
        updateUIState();
        connectWebSocket();

        console.log('Session started:', currentSessionId);
    } catch (error) {
        console.error('Failed to start session:', error);
        alert(`Failed to start session: ${error.message}`);
    }
}

async function stopSession() {
    if (!currentSessionId) {
        return;
    }

    try {
        const response = await fetch(`/api/live/sessions/${currentSessionId}/stop`, {
            method: 'POST'
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to stop session');
        }

        const data = await response.json();
        sessionStatus = data.status;

        updateSessionDisplay(data);
        updateUIState();
        disconnectWebSocket();

        console.log('Session stopped:', currentSessionId);
    } catch (error) {
        console.error('Failed to stop session:', error);
        alert(`Failed to stop session: ${error.message}`);
    }
}

// ============================================================================
// WebSocket Real-time Updates
// ============================================================================

function connectWebSocket() {
    if (!currentSessionId) return;

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws/live/${currentSessionId}`;

    ws = new WebSocket(wsUrl);

    ws.onopen = function() {
        console.log('WebSocket connected');
    };

    ws.onmessage = function(event) {
        const message = JSON.parse(event.data);
        handleWebSocketMessage(message);
    };

    ws.onerror = function(error) {
        console.error('WebSocket error:', error);
    };

    ws.onclose = function() {
        console.log('WebSocket disconnected');
        // Attempt reconnection if session is still running
        if (sessionStatus === 'running') {
            setTimeout(connectWebSocket, 5000);
        }
    };

    // Send ping every 30 seconds to keep connection alive
    setInterval(() => {
        if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send('ping');
        }
    }, 30000);
}

function disconnectWebSocket() {
    if (ws) {
        ws.close();
        ws = null;
    }
}

function handleWebSocketMessage(message) {
    switch (message.type) {
        case 'state_update':
            updateSessionDisplay(message.payload);
            break;
        case 'trade':
            handleNewTrade(message.payload);
            break;
        case 'bar':
            handleNewBar(message.payload);
            break;
        case 'pong':
            // Keepalive response
            break;
        case 'error':
            console.error('WebSocket error:', message.message);
            break;
        default:
            console.log('Unknown message type:', message.type);
    }
}

// ============================================================================
// UI Updates
// ============================================================================

function updateSessionDisplay(sessionData) {
    // Update session ID display
    document.getElementById('session-id-display').textContent =
        sessionData.session_id ? `Session: ${sessionData.session_id.substring(0, 8)}...` : '';

    // Update status badge
    const statusBadge = document.getElementById('session-status-badge');
    const statusText = sessionData.status || 'created';
    statusBadge.innerHTML = `
        <span class="status-indicator"></span>
        <span>${statusText.charAt(0).toUpperCase() + statusText.slice(1)}</span>
    `;
    statusBadge.className = `status-badge ${statusText}`;

    // Update account metrics if last_state is available
    if (sessionData.last_state) {
        updateAccountMetrics(sessionData.last_state);
        updateTradesTable(sessionData.last_state.recent_trades);

        if (sessionData.last_state.last_bar) {
            updateChart(sessionData.last_state.last_bar);
        }
    }
}

function updateAccountMetrics(state) {
    document.getElementById('account-equity').textContent = `$${state.equity.toFixed(2)}`;
    document.getElementById('account-balance').textContent = `$${state.balance.toFixed(2)}`;
    document.getElementById('account-realized-pnl').textContent = formatPnL(state.realized_pnl);

    if (state.position) {
        document.getElementById('account-position-size').textContent = state.position.size.toFixed(4);
        document.getElementById('account-entry-price').textContent = state.position.avg_price ?
            `$${state.position.avg_price.toFixed(2)}` : '-';
        document.getElementById('account-unrealized-pnl').textContent = formatPnL(state.position.unrealized_pnl);
    } else {
        document.getElementById('account-position-size').textContent = '0.0000';
        document.getElementById('account-entry-price').textContent = '-';
        document.getElementById('account-unrealized-pnl').textContent = '$0.00';
    }
}

function updateTradesTable(trades) {
    const tbody = document.getElementById('trades-table-body');

    if (!trades || trades.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" class="empty-state">No trades yet</td></tr>';
        return;
    }

    tbody.innerHTML = trades.map((trade, idx) => {
        const pnl = trade.pnl || 0;
        const pnlClass = pnl >= 0 ? 'pnl-positive' : 'pnl-negative';
        const rowClass = pnl >= 0 ? 'profit' : 'loss';

        return `
            <tr class="${rowClass}">
                <td>${idx + 1}</td>
                <td>${formatDateTime(trade.timestamp)}</td>
                <td class="trade-type-${trade.side.toLowerCase()}">${trade.side.toUpperCase()}</td>
                <td>${trade.quantity.toFixed(4)}</td>
                <td>$${trade.price.toFixed(2)}</td>
                <td class="${pnlClass}">${formatPnL(pnl)}</td>
            </tr>
        `;
    }).join('');
}

function handleNewTrade(trade) {
    console.log('New trade:', trade);
    // Refresh trades table
    fetchSessionStatus();
}

function handleNewBar(bar) {
    console.log('New bar:', bar);
    updateChart(bar);
}

function updateUIState() {
    const createBtn = document.getElementById('create-session-btn');
    const startBtn = document.getElementById('start-session-btn');
    const stopBtn = document.getElementById('stop-session-btn');

    if (!currentSessionId) {
        createBtn.disabled = false;
        startBtn.disabled = true;
        stopBtn.disabled = true;
    } else if (sessionStatus === 'created' || sessionStatus === 'stopped') {
        createBtn.disabled = true;
        startBtn.disabled = false;
        stopBtn.disabled = true;
    } else if (sessionStatus === 'running') {
        createBtn.disabled = true;
        startBtn.disabled = true;
        stopBtn.disabled = false;
    } else {
        createBtn.disabled = true;
        startBtn.disabled = true;
        stopBtn.disabled = true;
    }
}

async function fetchSessionStatus() {
    if (!currentSessionId) return;

    try {
        const response = await fetch(`/api/live/sessions/${currentSessionId}`);
        if (response.ok) {
            const data = await response.json();
            updateSessionDisplay(data);
        }
    } catch (error) {
        console.error('Failed to fetch session status:', error);
    }
}

// ============================================================================
// Chart Management
// ============================================================================

function initializeChart() {
    const container = document.getElementById('live-chart-container');
    container.innerHTML = ''; // Clear empty state

    chartInstance = LightweightCharts.createChart(container, {
        width: container.clientWidth,
        height: 500,
        layout: {
            background: { color: '#ffffff' },
            textColor: '#333',
        },
        grid: {
            vertLines: { color: '#f0f0f0' },
            horzLines: { color: '#f0f0f0' },
        },
        crosshair: {
            mode: LightweightCharts.CrosshairMode.Normal,
        },
        rightPriceScale: {
            borderColor: '#e0e0e0',
        },
        timeScale: {
            borderColor: '#e0e0e0',
            timeVisible: true,
            secondsVisible: false,
        },
    });

    // Add candlestick series
    candlestickSeries = chartInstance.addCandlestickSeries({
        upColor: '#10b981',
        downColor: '#ef4444',
        borderUpColor: '#10b981',
        borderDownColor: '#ef4444',
        wickUpColor: '#10b981',
        wickDownColor: '#ef4444',
    });

    // Add volume series
    volumeSeries = chartInstance.addHistogramSeries({
        color: '#9ca3af',
        priceFormat: {
            type: 'volume',
        },
        priceScaleId: '',
        scaleMargins: {
            top: 0.8,
            bottom: 0,
        },
    });

    // Auto-resize
    window.addEventListener('resize', () => {
        if (chartInstance) {
            chartInstance.applyOptions({
                width: container.clientWidth
            });
        }
    });

    // Load initial bars from session
    loadInitialBars();
}

async function loadInitialBars() {
    if (!currentSessionId) return;

    try {
        const response = await fetch(`/api/live/sessions/${currentSessionId}/bars?limit=500`);
        if (response.ok) {
            const data = await response.json();
            if (data.bars && data.bars.length > 0) {
                const bars = data.bars.map(b => ({
                    time: new Date(b.timestamp).getTime() / 1000,
                    open: b.open,
                    high: b.high,
                    low: b.low,
                    close: b.close,
                    volume: b.volume
                }));

                candlestickSeries.setData(bars);

                const volumeData = bars.map(b => ({
                    time: b.time,
                    value: b.volume,
                    color: b.close >= b.open ? 'rgba(16, 185, 129, 0.3)' : 'rgba(239, 68, 68, 0.3)'
                }));
                volumeSeries.setData(volumeData);

                chartInstance.timeScale().fitContent();
            }
        }
    } catch (error) {
        console.error('Failed to load bars:', error);
    }
}

function updateChart(bar) {
    if (!candlestickSeries || !volumeSeries) return;

    const barData = {
        time: new Date(bar.timestamp).getTime() / 1000,
        open: bar.open,
        high: bar.high,
        low: bar.low,
        close: bar.close,
        volume: bar.volume
    };

    candlestickSeries.update(barData);
    volumeSeries.update({
        time: barData.time,
        value: barData.volume,
        color: barData.close >= barData.open ? 'rgba(16, 185, 129, 0.3)' : 'rgba(239, 68, 68, 0.3)'
    });
}

// ============================================================================
// Chart Controls
// ============================================================================

function toggleRSI(event) {
    // TODO: Implement RSI indicator overlay
    console.log('Toggle RSI:', event.target.checked);
}

function toggleBB(event) {
    // TODO: Implement Bollinger Bands overlay
    console.log('Toggle BB:', event.target.checked);
}

function toggleEMA(event) {
    // TODO: Implement EMA/MA overlay
    console.log('Toggle EMA:', event.target.checked);
}

function toggleTrades(event) {
    // TODO: Implement trade markers on chart
    console.log('Toggle Trades:', event.target.checked);
}

// ============================================================================
// Utility Functions
// ============================================================================

function formatPnL(value) {
    if (value === null || value === undefined) return '$0.00';
    const sign = value >= 0 ? '+' : '';
    return `${sign}$${value.toFixed(2)}`;
}

function formatDateTime(timestamp) {
    if (!timestamp) return '-';
    const date = new Date(timestamp);
    return date.toLocaleString('en-US', {
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit'
    });
}
