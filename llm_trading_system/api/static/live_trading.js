/**
 * Live Trading UI Controller
 * Manages real-time trading session, WebSocket updates, and chart visualization
 */

// ============================================================================
// Global State
// ============================================================================

let currentSessionId = null;
let currentMode = 'paper';
let ws = null;
let wsReconnectAttempts = 0;
let wsReconnectTimer = null;
let chartInstance = null;
let candlestickSeries = null;
let volumeSeries = null;
let rsiSeries = null;
let bbUpperSeries = null;
let bbMiddleSeries = null;
let bbLowerSeries = null;
let emaSeries = null;
let tradeMarkers = [];
let sessionStatus = 'none';
let isLoading = false;
let sessionStartTime = null;
let sessionConfig = null;
let durationTimer = null;
let initialDeposit = 0;

// ============================================================================
// Initialization
// ============================================================================

document.addEventListener('DOMContentLoaded', function() {
    setupEventListeners();
    updateUIState();
    updateModeBadge();
    prefillFormFromURL();
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

    // Chart indicator controls
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
    const depositHelp = document.getElementById('deposit-help');
    const refreshBtn = document.getElementById('refresh-balance-btn');

    if (currentMode === 'paper') {
        // Paper mode: editable deposit field
        depositInput.removeAttribute('readonly');
        depositInput.disabled = false;
        depositLabel.textContent = 'Initial Deposit (USDT)';
        refreshBtn.style.display = 'none';
        depositHelp.textContent = 'Enter your simulated starting balance for paper trading';

        // Restore default value if not already set by user
        if (!depositInput.value || depositInput.value === '0') {
            depositInput.value = depositInput.getAttribute('data-default') || '10000';
        }
    } else {
        // Real mode: readonly, fetch live balance
        depositInput.setAttribute('readonly', 'readonly');
        depositInput.disabled = true;
        depositLabel.textContent = 'Live Balance (USDT)';
        refreshBtn.style.display = 'inline-block';
        depositHelp.textContent = 'Balance will be fetched from exchange. Click Refresh to update.';

        // Show confirmation warning for real trading
        if (!currentSessionId) {
            showInfo('⚠️ Real trading mode enabled. Trades will execute on the exchange. Make sure you understand the risks.');
        }

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
    const depositInput = document.getElementById('initial-deposit');
    depositInput.value = '';
    depositInput.placeholder = 'Loading...';

    try {
        // Try to get balance from current session if exists
        if (currentSessionId) {
            const response = await fetch(`/api/live/sessions/${currentSessionId}/account`);
            if (response.ok) {
                const data = await response.json();
                depositInput.value = data.balance.toFixed(2);
                depositInput.placeholder = '';
                return;
            }
        }

        // Otherwise try to fetch from exchange directly
        // Note: This endpoint may not exist yet, handle gracefully
        const response = await fetch('/api/exchange/account');
        if (response.ok) {
            const data = await response.json();
            depositInput.value = data.balance.toFixed(2);
        } else {
            depositInput.value = '0';
            depositInput.placeholder = 'Unable to fetch balance';
        }
    } catch (error) {
        console.error('Failed to fetch live balance:', error);
        depositInput.value = '0';
        depositInput.placeholder = 'Error fetching balance';
    }
}

async function refreshBalance() {
    await fetchLiveBalance();
}

// ============================================================================
// Session Management
// ============================================================================

async function createSession() {
    if (isLoading) return;

    const strategySelect = document.getElementById('strategy-select');
    const symbolSelect = document.getElementById('symbol-select');
    const timeframeSelect = document.getElementById('timeframe-select');
    const depositInput = document.getElementById('initial-deposit');

    // Validation
    if (!strategySelect.value) {
        showError('Please select a strategy');
        return;
    }

    const depositValue = parseFloat(depositInput.value);
    if (!depositValue || depositValue < 10) {
        showError('Initial deposit must be at least $10');
        return;
    }

    // Show confirmation for real trading
    if (currentMode === 'real') {
        const confirmed = confirm(
            '⚠️ WARNING: You are about to create a REAL trading session.\n\n' +
            'Trades will be executed on the exchange with real money.\n' +
            `Strategy: ${strategySelect.value}\n` +
            `Symbol: ${symbolSelect.value}\n` +
            `Timeframe: ${timeframeSelect.value}\n\n` +
            'Are you sure you want to continue?'
        );
        if (!confirmed) {
            return;
        }
    }

    const config = {
        mode: currentMode,
        symbol: symbolSelect.value,
        timeframe: timeframeSelect.value,
        strategy_config: strategySelect.value,
        initial_deposit: depositValue,
        llm_enabled: false,  // TODO: Add LLM toggle when available
        fee_rate: 0.0005,
        slippage_bps: 1.0,
        poll_interval: 1.0
    };

    setLoading(true);
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
        updateSessionSummary(config, null);

        addLogEntry(`Session created: ${currentSessionId.substring(0, 12)}...`, 'success');
        addLogEntry(`Mode: ${currentMode.toUpperCase()} | Strategy: ${config.strategy_config} | Symbol: ${config.symbol} ${config.timeframe}`, 'info');
        showSuccess(`Session created successfully: ${currentSessionId.substring(0, 8)}...`);
        console.log('Session created:', currentSessionId);
    } catch (error) {
        console.error('Failed to create session:', error);
        showError(`Failed to create session: ${error.message}`);
    } finally {
        setLoading(false);
    }
}

async function startSession() {
    if (!currentSessionId || isLoading) {
        return;
    }

    // Additional confirmation for real trading
    if (currentMode === 'real') {
        const confirmed = confirm(
            '⚠️ FINAL WARNING: Starting REAL trading session.\n\n' +
            'The strategy will start executing real trades on the exchange.\n\n' +
            'Continue?'
        );
        if (!confirmed) {
            return;
        }
    }

    setLoading(true);
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

        // Start duration timer
        startDurationTimer();

        // Connect WebSocket for real-time updates
        connectWebSocket();

        // Load initial data
        await loadInitialBars();
        await loadInitialTrades();

        addLogEntry('Trading session started', 'success');
        addLogEntry('WebSocket connected, receiving real-time updates', 'info');
        showSuccess('Trading session started');
        console.log('Session started:', currentSessionId);
    } catch (error) {
        console.error('Failed to start session:', error);
        showError(`Failed to start session: ${error.message}`);
    } finally {
        setLoading(false);
    }
}

async function stopSession() {
    if (!currentSessionId || isLoading) {
        return;
    }

    const confirmed = confirm('Stop trading session? Current positions will be maintained.');
    if (!confirmed) {
        return;
    }

    setLoading(true);
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
        stopDurationTimer();

        addLogEntry('Trading session stopped', 'warning');
        addLogEntry('WebSocket disconnected', 'info');
        showSuccess('Trading session stopped');
        console.log('Session stopped:', currentSessionId);
    } catch (error) {
        console.error('Failed to stop session:', error);
        showError(`Failed to stop session: ${error.message}`);
    } finally {
        setLoading(false);
    }
}

// ============================================================================
// WebSocket Real-time Updates
// ============================================================================

function connectWebSocket() {
    if (!currentSessionId) return;

    // Clean up existing connection
    disconnectWebSocket();

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws/live/${currentSessionId}`;

    console.log('Connecting to WebSocket:', wsUrl);
    ws = new WebSocket(wsUrl);

    ws.onopen = function() {
        console.log('WebSocket connected');
        wsReconnectAttempts = 0;
        showInfo('Real-time updates connected');
    };

    ws.onmessage = function(event) {
        try {
            const message = JSON.parse(event.data);
            handleWebSocketMessage(message);
        } catch (error) {
            console.error('Failed to parse WebSocket message:', error);
        }
    };

    ws.onerror = function(error) {
        console.error('WebSocket error:', error);
    };

    ws.onclose = function(event) {
        console.log('WebSocket disconnected', event.code, event.reason);
        ws = null;

        // Attempt reconnection if session is still running
        if (sessionStatus === 'running' && wsReconnectAttempts < 5) {
            wsReconnectAttempts++;
            const delay = Math.min(1000 * Math.pow(2, wsReconnectAttempts), 30000);
            console.log(`Reconnecting in ${delay}ms (attempt ${wsReconnectAttempts}/5)...`);

            wsReconnectTimer = setTimeout(() => {
                connectWebSocket();
            }, delay);
        }
    };

    // Send ping every 30 seconds to keep connection alive
    const pingInterval = setInterval(() => {
        if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: 'ping' }));
        } else {
            clearInterval(pingInterval);
        }
    }, 30000);
}

function disconnectWebSocket() {
    if (wsReconnectTimer) {
        clearTimeout(wsReconnectTimer);
        wsReconnectTimer = null;
    }

    if (ws) {
        ws.close();
        ws = null;
    }

    wsReconnectAttempts = 0;
}

function handleWebSocketMessage(message) {
    switch (message.type) {
        case 'state_update':
            updateSessionDisplay({ last_state: message.payload });
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
            showError(`Trading error: ${message.message}`);
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
    if (sessionData.session_id) {
        document.getElementById('session-id-display').textContent =
            `Session: ${sessionData.session_id.substring(0, 8)}...`;
    }

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
        updateSessionSummary(null, sessionData.last_state);

        if (sessionData.last_state.recent_trades) {
            updateTradesTable(sessionData.last_state.recent_trades);
        }

        if (sessionData.last_state.last_bar) {
            updateChart(sessionData.last_state.last_bar);
        }

        // Update LLM regime if available
        if (sessionData.last_state.llm_regime) {
            updateLLMRegime(sessionData.last_state.llm_regime);
        }
    }
}

function updateAccountMetrics(state) {
    document.getElementById('account-equity').textContent = `$${state.equity.toFixed(2)}`;
    document.getElementById('account-balance').textContent = `$${state.balance.toFixed(2)}`;

    const realizedPnlElem = document.getElementById('account-realized-pnl');
    realizedPnlElem.textContent = formatPnL(state.realized_pnl);
    realizedPnlElem.className = state.realized_pnl >= 0 ? 'metric-value positive' : 'metric-value negative';

    if (state.position && state.position.size !== 0) {
        document.getElementById('account-position-size').textContent = state.position.size.toFixed(4);
        document.getElementById('account-entry-price').textContent =
            state.position.avg_price ? `$${state.position.avg_price.toFixed(2)}` : '-';

        const unrealizedPnlElem = document.getElementById('account-unrealized-pnl');
        unrealizedPnlElem.textContent = formatPnL(state.position.unrealized_pnl || 0);
        unrealizedPnlElem.className = (state.position.unrealized_pnl || 0) >= 0 ? 'metric-value positive' : 'metric-value negative';
    } else {
        document.getElementById('account-position-size').textContent = '0.0000';
        document.getElementById('account-entry-price').textContent = '-';
        document.getElementById('account-unrealized-pnl').textContent = '$0.00';
        document.getElementById('account-unrealized-pnl').className = 'metric-value';
    }
}

function updateLLMRegime(regimeData) {
    const regimeLabel = document.getElementById('regime-label');

    if (!regimeData || !regimeData.regime) {
        regimeLabel.textContent = 'Not Available';
        regimeLabel.className = 'regime-label neutral';
        document.getElementById('regime-prob-bull').textContent = '-';
        document.getElementById('regime-prob-bear').textContent = '-';
        document.getElementById('regime-k-long').textContent = '-';
        document.getElementById('regime-k-short').textContent = '-';
        return;
    }

    // Update regime label
    const regime = regimeData.regime.toLowerCase();
    regimeLabel.textContent = regime.toUpperCase();
    regimeLabel.className = `regime-label ${regime}`;

    // Update probabilities
    document.getElementById('regime-prob-bull').textContent =
        regimeData.prob_bull ? `${(regimeData.prob_bull * 100).toFixed(1)}%` : '-';
    document.getElementById('regime-prob-bear').textContent =
        regimeData.prob_bear ? `${(regimeData.prob_bear * 100).toFixed(1)}%` : '-';

    // Update multipliers
    document.getElementById('regime-k-long').textContent =
        regimeData.k_long ? regimeData.k_long.toFixed(2) : '-';
    document.getElementById('regime-k-short').textContent =
        regimeData.k_short ? regimeData.k_short.toFixed(2) : '-';
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
        const sideClass = trade.side.toLowerCase() === 'buy' ? 'long' : 'short';

        return `
            <tr class="${rowClass}">
                <td>${idx + 1}</td>
                <td>${formatDateTime(trade.timestamp)}</td>
                <td class="trade-type-${sideClass}">${trade.side.toUpperCase()}</td>
                <td>${trade.quantity.toFixed(4)}</td>
                <td>$${trade.price.toFixed(2)}</td>
                <td class="${pnlClass}">${formatPnL(pnl)}</td>
            </tr>
        `;
    }).join('');
}

function handleNewTrade(trade) {
    console.log('New trade:', trade);

    // Log the trade
    const tradeMsg = `${trade.side.toUpperCase()} ${trade.quantity.toFixed(4)} @ $${trade.price.toFixed(2)}`;
    const pnl = trade.pnl || 0;
    const pnlMsg = pnl !== 0 ? ` | P&L: ${pnl >= 0 ? '+' : ''}$${pnl.toFixed(2)}` : '';
    addLogEntry(`Trade executed: ${tradeMsg}${pnlMsg}`, 'trade');

    // Add trade marker to chart if enabled
    if (document.getElementById('toggle-trades').checked && candlestickSeries) {
        addTradeMarker(trade);
    }

    // Refresh full session status to get updated trades table
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
        createBtn.disabled = isLoading;
        startBtn.disabled = true;
        stopBtn.disabled = true;
    } else if (sessionStatus === 'created' || sessionStatus === 'stopped') {
        createBtn.disabled = true;
        startBtn.disabled = isLoading;
        stopBtn.disabled = true;
    } else if (sessionStatus === 'running') {
        createBtn.disabled = true;
        startBtn.disabled = true;
        stopBtn.disabled = isLoading;
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
            sessionStatus = data.status;
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
}

async function loadInitialBars() {
    if (!currentSessionId || !candlestickSeries) return;

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
                }));

                candlestickSeries.setData(bars);

                const volumeData = data.bars.map(b => ({
                    time: new Date(b.timestamp).getTime() / 1000,
                    value: b.volume || 0,
                    color: b.close >= b.open ? 'rgba(16, 185, 129, 0.3)' : 'rgba(239, 68, 68, 0.3)'
                }));
                volumeSeries.setData(volumeData);

                chartInstance.timeScale().fitContent();

                console.log(`Loaded ${bars.length} bars`);
            }
        }
    } catch (error) {
        console.error('Failed to load bars:', error);
    }
}

async function loadInitialTrades() {
    if (!currentSessionId) return;

    try {
        const response = await fetch(`/api/live/sessions/${currentSessionId}/trades?limit=50`);
        if (response.ok) {
            const data = await response.json();
            if (data.trades && data.trades.length > 0) {
                updateTradesTable(data.trades);

                // Add trade markers if enabled
                if (document.getElementById('toggle-trades').checked && candlestickSeries) {
                    data.trades.forEach(trade => addTradeMarker(trade));
                }

                console.log(`Loaded ${data.trades.length} trades`);
            }
        }
    } catch (error) {
        console.error('Failed to load trades:', error);
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
    };

    candlestickSeries.update(barData);

    volumeSeries.update({
        time: barData.time,
        value: bar.volume || 0,
        color: barData.close >= barData.open ? 'rgba(16, 185, 129, 0.3)' : 'rgba(239, 68, 68, 0.3)'
    });
}

function addTradeMarker(trade) {
    if (!candlestickSeries) return;

    const marker = {
        time: new Date(trade.timestamp).getTime() / 1000,
        position: trade.side.toLowerCase() === 'buy' ? 'belowBar' : 'aboveBar',
        color: trade.side.toLowerCase() === 'buy' ? '#10b981' : '#ef4444',
        shape: trade.side.toLowerCase() === 'buy' ? 'arrowUp' : 'arrowDown',
        text: `${trade.side.toUpperCase()} @${trade.price.toFixed(2)}`
    };

    tradeMarkers.push(marker);
    candlestickSeries.setMarkers(tradeMarkers);
}

// ============================================================================
// Chart Controls (Indicators)
// ============================================================================

function toggleRSI(event) {
    const enabled = event.target.checked;

    if (enabled && !rsiSeries) {
        // Create RSI series
        rsiSeries = chartInstance.addLineSeries({
            color: '#9333ea',
            lineWidth: 2,
            priceScaleId: 'rsi',
            scaleMargins: {
                top: 0.9,
                bottom: 0,
            },
        });

        // TODO: Fetch RSI data from backend or calculate client-side
        console.log('RSI indicator enabled (data loading not yet implemented)');
    } else if (!enabled && rsiSeries) {
        // Remove RSI series
        chartInstance.removeSeries(rsiSeries);
        rsiSeries = null;
        console.log('RSI indicator disabled');
    }
}

function toggleBB(event) {
    const enabled = event.target.checked;

    if (enabled && !bbUpperSeries) {
        // Create Bollinger Bands series
        bbUpperSeries = chartInstance.addLineSeries({
            color: '#3b82f6',
            lineWidth: 1,
            lineStyle: 2, // Dashed
        });

        bbMiddleSeries = chartInstance.addLineSeries({
            color: '#3b82f6',
            lineWidth: 1,
        });

        bbLowerSeries = chartInstance.addLineSeries({
            color: '#3b82f6',
            lineWidth: 1,
            lineStyle: 2, // Dashed
        });

        // TODO: Fetch BB data from backend or calculate client-side
        console.log('Bollinger Bands enabled (data loading not yet implemented)');
    } else if (!enabled && bbUpperSeries) {
        // Remove BB series
        chartInstance.removeSeries(bbUpperSeries);
        chartInstance.removeSeries(bbMiddleSeries);
        chartInstance.removeSeries(bbLowerSeries);
        bbUpperSeries = null;
        bbMiddleSeries = null;
        bbLowerSeries = null;
        console.log('Bollinger Bands disabled');
    }
}

function toggleEMA(event) {
    const enabled = event.target.checked;

    if (enabled && !emaSeries) {
        // Create EMA series
        emaSeries = chartInstance.addLineSeries({
            color: '#f59e0b',
            lineWidth: 2,
        });

        // TODO: Fetch EMA data from backend or calculate client-side
        console.log('EMA indicator enabled (data loading not yet implemented)');
    } else if (!enabled && emaSeries) {
        // Remove EMA series
        chartInstance.removeSeries(emaSeries);
        emaSeries = null;
        console.log('EMA indicator disabled');
    }
}

function toggleTrades(event) {
    const enabled = event.target.checked;

    if (enabled) {
        // Reload trade markers
        loadInitialTrades();
    } else {
        // Clear trade markers
        tradeMarkers = [];
        if (candlestickSeries) {
            candlestickSeries.setMarkers([]);
        }
    }
}

// ============================================================================
// Session Summary Management
// ============================================================================

function updateSessionSummary(config, state) {
    const summaryBlock = document.getElementById('session-summary');

    if (!currentSessionId) {
        summaryBlock.classList.remove('visible');
        return;
    }

    summaryBlock.classList.add('visible');

    // Update basic info
    if (config) {
        sessionConfig = config;
        document.getElementById('summary-strategy').textContent = config.strategy_config || '-';
        document.getElementById('summary-symbol').textContent = config.symbol || '-';
        document.getElementById('summary-timeframe').textContent = config.timeframe || '-';
        document.getElementById('summary-session-id').textContent =
            currentSessionId ? currentSessionId.substring(0, 12) + '...' : '-';

        const modeBadge = document.getElementById('summary-mode-badge');
        modeBadge.textContent = config.mode === 'paper' ? 'Paper' : 'Real';
        modeBadge.className = `mode-badge ${config.mode}`;

        initialDeposit = config.initial_deposit || 0;
    }

    // Update metrics from state
    if (state) {
        // Calculate return %
        if (initialDeposit > 0) {
            const returnPct = ((state.equity - initialDeposit) / initialDeposit) * 100;
            const returnElem = document.getElementById('summary-return-pct');
            returnElem.textContent = `${returnPct >= 0 ? '+' : ''}${returnPct.toFixed(2)}%`;
            returnElem.style.color = returnPct >= 0 ? '#10b981' : '#ef4444';
        }

        // Update trades count
        const tradesCount = state.recent_trades ? state.recent_trades.length : 0;
        document.getElementById('summary-trades-count').textContent = tradesCount;

        // Calculate winrate
        if (state.recent_trades && state.recent_trades.length > 0) {
            const winningTrades = state.recent_trades.filter(t => (t.pnl || 0) > 0).length;
            const winrate = (winningTrades / state.recent_trades.length) * 100;
            document.getElementById('summary-winrate').textContent = `${winrate.toFixed(1)}%`;
        } else {
            document.getElementById('summary-winrate').textContent = '-';
        }
    }
}

function startDurationTimer() {
    sessionStartTime = new Date();
    updateDuration();

    // Update duration every second
    if (durationTimer) {
        clearInterval(durationTimer);
    }
    durationTimer = setInterval(updateDuration, 1000);
}

function stopDurationTimer() {
    if (durationTimer) {
        clearInterval(durationTimer);
        durationTimer = null;
    }
}

function updateDuration() {
    if (!sessionStartTime) {
        document.getElementById('summary-duration').textContent = '-';
        return;
    }

    const now = new Date();
    const diffMs = now - sessionStartTime;
    const diffSec = Math.floor(diffMs / 1000);
    const hours = Math.floor(diffSec / 3600);
    const minutes = Math.floor((diffSec % 3600) / 60);
    const seconds = diffSec % 60;

    const durationText = `${hours.toString().padStart(2, '0')}:${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;
    document.getElementById('summary-duration').textContent = durationText;
}

// ============================================================================
// Activity Log Management
// ============================================================================

function addLogEntry(message, type = 'info') {
    const container = document.getElementById('activity-log-container');

    // Clear initial "waiting" message if present
    if (container.children.length === 1 && container.children[0].textContent.includes('Waiting')) {
        container.innerHTML = '';
    }

    const now = new Date();
    const timeStr = now.toLocaleTimeString('en-US', { hour12: false });

    const entry = document.createElement('div');
    entry.className = `log-entry ${type}`;
    entry.innerHTML = `
        <span class="log-time">${timeStr}</span>
        <span class="log-message">${message}</span>
    `;

    container.appendChild(entry);

    // Auto-scroll to bottom
    container.scrollTop = container.scrollHeight;

    // Limit to 100 entries
    while (container.children.length > 100) {
        container.removeChild(container.firstChild);
    }
}

// ============================================================================
// UX Helpers
// ============================================================================

function setLoading(loading) {
    isLoading = loading;
    updateUIState();

    // Could add spinner visualization here
    if (loading) {
        console.log('Loading...');
    }
}

function showSuccess(message) {
    console.log('✓', message);
    addLogEntry(message, 'success');
}

function showError(message) {
    console.error('✗', message);
    addLogEntry(message, 'error');
    alert(message);
}

function showInfo(message) {
    console.log('ℹ', message);
    addLogEntry(message, 'info');
}

// ============================================================================
// Utility Functions
// ============================================================================

function formatPnL(value) {
    if (value === null || value === undefined || isNaN(value)) return '$0.00';
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
        minute: '2-digit',
        second: '2-digit'
    });
}

// ============================================================================
// URL Parameters Prefill
// ============================================================================

function prefillFormFromURL() {
    const urlParams = new URLSearchParams(window.location.search);

    // Prefill strategy
    const strategy = urlParams.get('strategy');
    if (strategy) {
        const strategySelect = document.getElementById('strategy-select');
        const option = Array.from(strategySelect.options).find(opt => opt.value === strategy);
        if (option) {
            strategySelect.value = strategy;
            addLogEntry(`Pre-filled strategy: ${strategy}`, 'info');
        }
    }

    // Prefill symbol
    const symbol = urlParams.get('symbol');
    if (symbol) {
        const symbolSelect = document.getElementById('symbol-select');
        const option = Array.from(symbolSelect.options).find(opt => opt.value === symbol);
        if (option) {
            symbolSelect.value = symbol;
            addLogEntry(`Pre-filled symbol: ${symbol}`, 'info');
        }
    }

    // Prefill timeframe
    const timeframe = urlParams.get('timeframe');
    if (timeframe) {
        const timeframeSelect = document.getElementById('timeframe-select');
        const option = Array.from(timeframeSelect.options).find(opt => opt.value === timeframe);
        if (option) {
            timeframeSelect.value = timeframe;
            addLogEntry(`Pre-filled timeframe: ${timeframe}`, 'info');
        }
    }

    // Prefill mode
    const mode = urlParams.get('mode');
    if (mode && (mode === 'paper' || mode === 'real')) {
        const modeRadio = document.querySelector(`input[name="trading-mode"][value="${mode}"]`);
        if (modeRadio && !modeRadio.disabled) {
            modeRadio.checked = true;
            // Trigger mode change handler
            handleModeChange({ target: modeRadio });
            addLogEntry(`Pre-filled mode: ${mode.toUpperCase()}`, 'info');
        }
    }

    // Prefill deposit (only for paper mode)
    const deposit = urlParams.get('deposit');
    if (deposit && currentMode === 'paper') {
        const depositInput = document.getElementById('initial-deposit');
        depositInput.value = deposit;
        addLogEntry(`Pre-filled initial deposit: $${deposit}`, 'info');
    }
}
