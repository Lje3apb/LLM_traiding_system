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
let wsHeartbeatInterval = null;  // Global reference to heartbeat interval
let priceChartInstance = null;
let volumeChartInstance = null;
let chartResizeHandler = null;  // Global reference to resize handler
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
let chartBars = [];

const INITIAL_BAR_FETCH_LIMIT = 50;
const MAX_BAR_HISTORY = 500;
const INDICATOR_DEFAULTS = {
    rsiLength: 14,
    emaLength: 21,
    bbLength: 20,
    bbStdDev: 2
};

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
    document.getElementById('toggle-indicators-rsi').addEventListener('change', (event) =>
        setRSIEnabled(event.target.checked)
    );
    document.getElementById('toggle-indicators-bb').addEventListener('change', (event) =>
        setBBEnabled(event.target.checked)
    );
    document.getElementById('toggle-indicators-ema').addEventListener('change', (event) =>
        setEMAEnabled(event.target.checked)
    );
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

/**
 * Fetch with timeout to prevent hanging requests
 * @param {string} url - The URL to fetch
 * @param {object} options - Fetch options
 * @param {number} timeout - Timeout in milliseconds (default 10000ms)
 * @returns {Promise<Response>}
 */
async function fetchWithTimeout(url, options = {}, timeout = 10000) {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), timeout);

    try {
        const response = await fetch(url, {
            ...options,
            signal: controller.signal
        });
        clearTimeout(timeoutId);
        return response;
    } catch (error) {
        clearTimeout(timeoutId);
        if (error.name === 'AbortError') {
            throw new Error(`Request timeout after ${timeout}ms`);
        }
        throw error;
    }
}

async function fetchLiveBalance() {
    const depositInput = document.getElementById('initial-deposit');
    depositInput.value = '';
    depositInput.placeholder = 'Loading...';

    try {
        // Try to get balance from current session if exists
        if (currentSessionId) {
            const response = await fetchWithTimeout(
                `/api/live/sessions/${currentSessionId}/account`,
                {},
                5000
            );

            if (response.ok) {
                const data = await response.json();

                // Validate response structure
                if (!data || typeof data.balance !== 'number') {
                    throw new Error('Invalid response format: balance missing or not a number');
                }

                if (data.balance < 0) {
                    throw new Error('Invalid balance: cannot be negative');
                }

                depositInput.value = parseFloat(data.balance).toFixed(2);
                depositInput.placeholder = '';
                return;
            }
        }

        // Otherwise try to fetch from exchange directly
        const response = await fetchWithTimeout('/api/exchange/account', {}, 5000);

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }

        const data = await response.json();

        // Validate response
        if (!data || typeof data.balance !== 'number' || data.balance < 0) {
            throw new Error('Invalid balance data from exchange');
        }

        depositInput.value = parseFloat(data.balance).toFixed(2);
        depositInput.placeholder = '';

    } catch (error) {
        console.error('Failed to fetch live balance:', error);
        showError(`Unable to fetch balance: ${error.message}`);
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

    // Validate deposit input
    const depositStr = depositInput.value?.trim();
    if (!depositStr) {
        showError('Initial deposit is required');
        return;
    }

    const depositValue = parseFloat(depositStr);
    if (isNaN(depositValue) || depositValue < 10) {
        showError('Initial deposit must be at least $10');
        return;
    }

    if (depositValue > 1000000) {
        showError('Initial deposit cannot exceed $1,000,000');
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
        const response = await fetchWithTimeout('/api/live/sessions', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(config)
        }, 15000);  // 15 second timeout for session creation

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
        const response = await fetchWithTimeout(`/api/live/sessions/${currentSessionId}/start`, {
            method: 'POST'
        }, 10000);  // 10 second timeout

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
        const response = await fetchWithTimeout(`/api/live/sessions/${currentSessionId}/stop`, {
            method: 'POST'
        }, 10000);  // 10 second timeout

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

    // Check if authentication token is available
    if (!window.WS_AUTH_TOKEN) {
        console.error('WebSocket authentication token not available');
        showError('Cannot connect to real-time updates: authentication token missing');
        return;
    }

    // Clean up existing connection
    disconnectWebSocket();

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    // Add authentication token as query parameter
    const wsUrl = `${protocol}//${window.location.host}/ws/live/${currentSessionId}?token=${encodeURIComponent(window.WS_AUTH_TOKEN)}`;

    console.log('Connecting to WebSocket:', wsUrl.replace(/token=[^&]+/, 'token=***'));
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

        // Check for authentication failure (close code 4401)
        if (event.code === 4401) {
            console.error('WebSocket authentication failed:', event.reason);
            showError('WebSocket authentication failed. Please refresh the page and try again.');
            addLogEntry('WebSocket connection rejected: Invalid or expired authentication token', 'error');
            return; // Do not attempt reconnection
        }

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
    // Store interval globally to prevent memory leaks on reconnection
    wsHeartbeatInterval = setInterval(() => {
        if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: 'ping' }));
        }
    }, 30000);
}

function disconnectWebSocket() {
    if (wsReconnectTimer) {
        clearTimeout(wsReconnectTimer);
        wsReconnectTimer = null;
    }

    // Clear heartbeat interval to prevent memory leak
    if (wsHeartbeatInterval) {
        clearInterval(wsHeartbeatInterval);
        wsHeartbeatInterval = null;
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

    // Update status badge - use safe DOM methods to prevent XSS
    const statusBadge = document.getElementById('session-status-badge');
    const statusText = sessionData.status || 'created';

    // Clear and rebuild safely
    statusBadge.innerHTML = '';

    const indicator = document.createElement('span');
    indicator.className = 'status-indicator';
    statusBadge.appendChild(indicator);

    const textSpan = document.createElement('span');
    textSpan.textContent = statusText.charAt(0).toUpperCase() + statusText.slice(1);
    statusBadge.appendChild(textSpan);

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

    // Clear table and rebuild safely to prevent XSS
    tbody.innerHTML = '';

    trades.forEach((trade, idx) => {
        const pnl = trade.pnl || 0;
        const pnlClass = pnl >= 0 ? 'pnl-positive' : 'pnl-negative';
        const rowClass = pnl >= 0 ? 'profit' : 'loss';

        // Validate trade.side to prevent class injection
        const validSides = ['buy', 'sell', 'long', 'short'];
        const sideLower = (trade.side || '').toLowerCase();
        const sideClass = validSides.includes(sideLower) ?
            (sideLower === 'buy' ? 'long' : 'short') : 'unknown';

        const tr = document.createElement('tr');
        tr.className = rowClass;

        // Index
        const tdIdx = document.createElement('td');
        tdIdx.textContent = idx + 1;
        tr.appendChild(tdIdx);

        // Timestamp
        const tdTime = document.createElement('td');
        tdTime.textContent = formatDateTime(trade.timestamp);
        tr.appendChild(tdTime);

        // Side
        const tdSide = document.createElement('td');
        tdSide.className = `trade-type-${sideClass}`;
        tdSide.textContent = trade.side.toUpperCase();
        tr.appendChild(tdSide);

        // Quantity
        const tdQty = document.createElement('td');
        tdQty.textContent = trade.quantity.toFixed(4);
        tr.appendChild(tdQty);

        // Price
        const tdPrice = document.createElement('td');
        tdPrice.textContent = `$${trade.price.toFixed(2)}`;
        tr.appendChild(tdPrice);

        // PnL
        const tdPnl = document.createElement('td');
        tdPnl.className = pnlClass;
        tdPnl.textContent = formatPnL(pnl);
        tr.appendChild(tdPnl);

        tbody.appendChild(tr);
    });
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
        const response = await fetchWithTimeout(
            `/api/live/sessions/${currentSessionId}`,
            {},
            5000  // 5 second timeout
        );

        if (!response.ok) {
            throw new Error(`Failed to fetch session: ${response.status}`);
        }

        const data = await response.json();

        if (!data || !data.status) {
            throw new Error('Invalid session data');
        }

        sessionStatus = data.status;
        updateSessionDisplay(data);

    } catch (error) {
        console.error('Failed to fetch session status:', error);
        // Optional: Show warning if this is a persistent issue
        if (sessionStatus === 'running') {
            console.warn('Session status update failed - data may be stale');
        }
    }
}

// ============================================================================
// Chart Management
// ============================================================================
// Live Trading uses TWO separate charts (similar to Backtest):
//   1. Price Chart (top): Candlesticks + indicators + trade markers
//   2. Volume Chart (bottom): Volume histogram with synchronized time scale

function initializeChart() {
    cleanupChart();
    const priceContainer = document.getElementById('live-price-chart');
    const volumeContainer = document.getElementById('live-volume-chart');

    // Clear empty state messages
    priceContainer.innerHTML = '';
    volumeContainer.innerHTML = '';

    chartBars = [];
    tradeMarkers = [];

    // Common chart options
    const commonOptions = {
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
    };

    // Create price chart
    priceChartInstance = LightweightCharts.createChart(priceContainer, {
        width: priceContainer.clientWidth,
        height: 350,
        ...commonOptions,
    });

    // Add candlestick series to price chart
    candlestickSeries = priceChartInstance.addCandlestickSeries({
        upColor: '#10b981',
        downColor: '#ef4444',
        borderUpColor: '#10b981',
        borderDownColor: '#ef4444',
        wickUpColor: '#10b981',
        wickDownColor: '#ef4444',
    });

    // Create volume chart
    volumeChartInstance = LightweightCharts.createChart(volumeContainer, {
        width: volumeContainer.clientWidth,
        height: 150,
        ...commonOptions,
    });

    // Add volume series to volume chart
    volumeSeries = volumeChartInstance.addHistogramSeries({
        color: '#9ca3af',
        priceFormat: {
            type: 'volume',
        },
    });

    // Synchronize time scales between price and volume charts
    // This ensures that zooming/panning one chart automatically syncs the other
    // The isSyncing flag prevents infinite loops when setting ranges
    let isSyncing = false;

    priceChartInstance.timeScale().subscribeVisibleTimeRangeChange((timeRange) => {
        if (timeRange && !isSyncing) {
            isSyncing = true;
            volumeChartInstance.timeScale().setVisibleRange(timeRange);
            isSyncing = false;
        }
    });

    volumeChartInstance.timeScale().subscribeVisibleTimeRangeChange((timeRange) => {
        if (timeRange && !isSyncing) {
            isSyncing = true;
            priceChartInstance.timeScale().setVisibleRange(timeRange);
            isSyncing = false;
        }
    });

    // Auto-resize - remove old listener first to prevent memory leak
    if (chartResizeHandler) {
        window.removeEventListener('resize', chartResizeHandler);
    }

    chartResizeHandler = () => {
        if (priceChartInstance && volumeChartInstance) {
            priceChartInstance.applyOptions({
                width: priceContainer.clientWidth
            });
            volumeChartInstance.applyOptions({
                width: volumeContainer.clientWidth
            });
        }
    };

    window.addEventListener('resize', chartResizeHandler);

    // Re-apply indicator visibility if user left toggles enabled
    restoreIndicatorState();
}

async function loadInitialBars() {
    if (!currentSessionId || !candlestickSeries) return;

    try {
        const response = await fetchWithTimeout(
            `/api/live/sessions/${currentSessionId}/bars?limit=${INITIAL_BAR_FETCH_LIMIT}`,
            {},
            10000  // 10 second timeout for historical dataset
        );

        if (response.ok) {
            const data = await response.json();
            if (Array.isArray(data.bars) && data.bars.length > 0) {
                const sortedBars = [...data.bars].sort(
                    (a, b) => new Date(a.timestamp) - new Date(b.timestamp)
                );
                const limitedBars = sortedBars.slice(-MAX_BAR_HISTORY);

                // Prepare candlestick data for price chart
                chartBars = limitedBars.map(b => ({
                    time: new Date(b.timestamp).getTime() / 1000,
                    open: b.open,
                    high: b.high,
                    low: b.low,
                    close: b.close,
                }));

                candlestickSeries.setData(chartBars);

                // Prepare volume data for volume chart (with color based on bar direction)
                const volumeData = limitedBars.map(b => ({
                    time: new Date(b.timestamp).getTime() / 1000,
                    value: b.volume || 0,
                    color: b.close >= b.open
                        ? 'rgba(16, 185, 129, 0.5)'
                        : 'rgba(239, 68, 68, 0.5)'
                }));
                volumeSeries.setData(volumeData);

                priceChartInstance.timeScale().fitContent();
                volumeChartInstance.timeScale().fitContent();
                refreshIndicators();

                console.log(`Loaded ${chartBars.length} bars`);
            } else {
                console.log('No historical bars returned for session.');
            }
        }
    } catch (error) {
        console.error('Failed to load bars:', error);
    }
}

async function loadInitialTrades() {
    if (!currentSessionId) return;

    try {
        const response = await fetchWithTimeout(
            `/api/live/sessions/${currentSessionId}/trades?limit=50`,
            {},
            5000  // 5 second timeout
        );

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
    // Ensure both chart series are initialized before updating
    if (!candlestickSeries || !volumeSeries) {
        console.warn('Chart series not initialized, skipping update');
        return;
    }

    const barData = {
        time: new Date(bar.timestamp).getTime() / 1000,
        open: bar.open,
        high: bar.high,
        low: bar.low,
        close: bar.close,
    };

    // Update price chart (candlesticks)
    candlestickSeries.update(barData);

    // Update volume chart with color based on bar direction
    volumeSeries.update({
        time: barData.time,
        value: bar.volume || 0,
        color: barData.close >= barData.open ? 'rgba(16, 185, 129, 0.5)' : 'rgba(239, 68, 68, 0.5)'
    });

    upsertChartBar(barData);
    refreshIndicators();
}

function upsertChartBar(barData) {
    const index = chartBars.findIndex(existing => existing.time === barData.time);

    if (index !== -1) {
        chartBars[index] = barData;
    } else {
        chartBars.push(barData);
    }

    chartBars.sort((a, b) => a.time - b.time);
    if (chartBars.length > MAX_BAR_HISTORY) {
        chartBars = chartBars.slice(-MAX_BAR_HISTORY);
    }
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

    // Limit to last 100 markers to prevent unbounded memory growth
    if (tradeMarkers.length > 100) {
        tradeMarkers = tradeMarkers.slice(-100);
    }

    candlestickSeries.setMarkers(tradeMarkers);
}

// ============================================================================
// Chart Controls (Indicators)
// ============================================================================

function setRSIEnabled(enabled, options = {}) {
    const { notifyOnInsufficientData = true } = options;
    const checkbox = document.getElementById('toggle-indicators-rsi');

    if (!priceChartInstance) {
        if (enabled) {
            showError('Chart not initialized');
        }
        checkbox.checked = false;
        return;
    }

    if (enabled) {
        if (!rsiSeries) {
            try {
                rsiSeries = priceChartInstance.addLineSeries({
                    color: '#9333ea',
                    lineWidth: 2,
                    priceScaleId: 'rsi',
                    priceFormat: { precision: 2, minMove: 0.1 },
                });
                priceChartInstance.priceScale('rsi').applyOptions({
                    scaleMargins: { top: 0.8, bottom: 0.02 },
                    borderVisible: false,
                });
            } catch (error) {
                console.error('Failed to create RSI series:', error);
                checkbox.checked = false;
                showError('Failed to enable RSI indicator');
                return;
            }
        }
        updateRsiSeriesData({ notifyOnInsufficientData });
    } else if (rsiSeries) {
        priceChartInstance.removeSeries(rsiSeries);
        rsiSeries = null;
    }
}

function setBBEnabled(enabled, options = {}) {
    const { notifyOnInsufficientData = true } = options;
    const checkbox = document.getElementById('toggle-indicators-bb');

    if (!priceChartInstance) {
        if (enabled) {
            showError('Chart not initialized');
        }
        checkbox.checked = false;
        return;
    }

    if (enabled) {
        if (!bbUpperSeries) {
            try {
                bbUpperSeries = priceChartInstance.addLineSeries({
                    color: '#3b82f6',
                    lineWidth: 1,
                    lineStyle: 2,
                });
                bbMiddleSeries = priceChartInstance.addLineSeries({
                    color: '#3b82f6',
                    lineWidth: 1,
                });
                bbLowerSeries = priceChartInstance.addLineSeries({
                    color: '#3b82f6',
                    lineWidth: 1,
                    lineStyle: 2,
                });
            } catch (error) {
                console.error('Failed to create BB series:', error);
                checkbox.checked = false;
                showError('Failed to enable Bollinger Bands');
                return;
            }
        }
        updateBollingerSeriesData({ notifyOnInsufficientData });
    } else if (bbUpperSeries) {
        priceChartInstance.removeSeries(bbUpperSeries);
        priceChartInstance.removeSeries(bbMiddleSeries);
        priceChartInstance.removeSeries(bbLowerSeries);
        bbUpperSeries = null;
        bbMiddleSeries = null;
        bbLowerSeries = null;
    }
}

function setEMAEnabled(enabled, options = {}) {
    const { notifyOnInsufficientData = true } = options;
    const checkbox = document.getElementById('toggle-indicators-ema');

    if (!priceChartInstance) {
        if (enabled) {
            showError('Chart not initialized');
        }
        checkbox.checked = false;
        return;
    }

    if (enabled) {
        if (!emaSeries) {
            try {
                emaSeries = priceChartInstance.addLineSeries({
                    color: '#f59e0b',
                    lineWidth: 2,
                });
            } catch (error) {
                console.error('Failed to create EMA series:', error);
                checkbox.checked = false;
                showError('Failed to enable EMA indicator');
                return;
            }
        }
        updateEmaSeriesData({ notifyOnInsufficientData });
    } else if (emaSeries) {
        priceChartInstance.removeSeries(emaSeries);
        emaSeries = null;
    }
}

function updateRsiSeriesData(options = {}) {
    const { notifyOnInsufficientData = false } = options;
    if (!rsiSeries) return;

    const data = calculateRSI(chartBars, INDICATOR_DEFAULTS.rsiLength);
    rsiSeries.setData(data);

    if (notifyOnInsufficientData && data.length === 0) {
        showInfo(`Need at least ${INDICATOR_DEFAULTS.rsiLength + 1} bars to plot RSI`);
    }
}

function updateBollingerSeriesData(options = {}) {
    const { notifyOnInsufficientData = false } = options;
    if (!bbUpperSeries || !bbMiddleSeries || !bbLowerSeries) return;

    const bands = calculateBollingerBands(
        chartBars,
        INDICATOR_DEFAULTS.bbLength,
        INDICATOR_DEFAULTS.bbStdDev
    );

    bbUpperSeries.setData(bands.upper);
    bbMiddleSeries.setData(bands.middle);
    bbLowerSeries.setData(bands.lower);

    if (notifyOnInsufficientData && bands.upper.length === 0) {
        showInfo(`Need at least ${INDICATOR_DEFAULTS.bbLength} bars to plot Bollinger Bands`);
    }
}

function updateEmaSeriesData(options = {}) {
    const { notifyOnInsufficientData = false } = options;
    if (!emaSeries) return;

    const data = calculateEMA(chartBars, INDICATOR_DEFAULTS.emaLength);
    emaSeries.setData(data);

    if (notifyOnInsufficientData && data.length === 0) {
        showInfo(`Need at least ${INDICATOR_DEFAULTS.emaLength} bars to plot EMA`);
    }
}

function refreshIndicators(options = {}) {
    const { notifyOnInsufficientData = false } = options;

    if (rsiSeries) {
        updateRsiSeriesData({ notifyOnInsufficientData });
    }
    if (bbUpperSeries) {
        updateBollingerSeriesData({ notifyOnInsufficientData });
    }
    if (emaSeries) {
        updateEmaSeriesData({ notifyOnInsufficientData });
    }
}

function restoreIndicatorState() {
    setRSIEnabled(document.getElementById('toggle-indicators-rsi').checked, {
        notifyOnInsufficientData: false
    });
    setBBEnabled(document.getElementById('toggle-indicators-bb').checked, {
        notifyOnInsufficientData: false
    });
    setEMAEnabled(document.getElementById('toggle-indicators-ema').checked, {
        notifyOnInsufficientData: false
    });
}

function calculateRSI(bars, length) {
    if (!Array.isArray(bars) || bars.length <= length) {
        return [];
    }

    const closes = bars.map(bar => bar.close);
    let gains = 0;
    let losses = 0;

    for (let i = 1; i <= length; i++) {
        const change = closes[i] - closes[i - 1];
        if (change >= 0) {
            gains += change;
        } else {
            losses -= change;
        }
    }

    let avgGain = gains / length;
    let avgLoss = losses / length;
    const data = [];

    const calcValue = () => {
        if (avgLoss === 0) {
            return 100;
        }
        const rs = avgGain / avgLoss;
        return 100 - 100 / (1 + rs);
    };

    data.push({ time: bars[length].time, value: calcValue() });

    for (let i = length + 1; i < closes.length; i++) {
        const change = closes[i] - closes[i - 1];
        if (change >= 0) {
            avgGain = ((avgGain * (length - 1)) + change) / length;
            avgLoss = ((avgLoss * (length - 1))) / length;
        } else {
            const loss = Math.abs(change);
            avgGain = ((avgGain * (length - 1))) / length;
            avgLoss = ((avgLoss * (length - 1)) + loss) / length;
        }
        data.push({ time: bars[i].time, value: calcValue() });
    }

    return data;
}

function calculateBollingerBands(bars, length, stdDevMultiplier) {
    if (!Array.isArray(bars) || bars.length < length) {
        return { upper: [], middle: [], lower: [] };
    }

    const upper = [];
    const middle = [];
    const lower = [];

    for (let i = length - 1; i < bars.length; i++) {
        const window = bars.slice(i - length + 1, i + 1);
        const closes = window.map(bar => bar.close);
        const mean = closes.reduce((sum, value) => sum + value, 0) / length;
        const variance = closes.reduce((sum, value) => sum + Math.pow(value - mean, 2), 0) / length;
        const stdDev = Math.sqrt(variance);
        const time = bars[i].time;

        middle.push({ time, value: mean });
        upper.push({ time, value: mean + stdDevMultiplier * stdDev });
        lower.push({ time, value: mean - stdDevMultiplier * stdDev });
    }

    return { upper, middle, lower };
}

function calculateEMA(bars, length) {
    if (!Array.isArray(bars) || bars.length < length) {
        return [];
    }

    const closes = bars.map(bar => bar.close);
    const multiplier = 2 / (length + 1);
    let ema = closes.slice(0, length).reduce((sum, value) => sum + value, 0) / length;
    const data = [{ time: bars[length - 1].time, value: ema }];

    for (let i = length; i < closes.length; i++) {
        ema = (closes[i] - ema) * multiplier + ema;
        data.push({ time: bars[i].time, value: ema });
    }

    return data;
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

        // Update chart symbol label
        const symbolLabel = document.getElementById('chart-symbol-label');
        if (symbolLabel && config.symbol) {
            symbolLabel.textContent = `(${config.symbol})`;
        }

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

    // Create safe log entry to prevent XSS
    const entry = document.createElement('div');
    entry.className = `log-entry ${type}`;

    const timeSpan = document.createElement('span');
    timeSpan.className = 'log-time';
    timeSpan.textContent = timeStr;  // textContent escapes HTML

    const msgSpan = document.createElement('span');
    msgSpan.className = 'log-message';
    msgSpan.textContent = message;  // textContent escapes HTML

    entry.appendChild(timeSpan);
    entry.appendChild(msgSpan);
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
// Cleanup Functions
// ============================================================================

/**
 * Clean up chart resources to prevent memory leaks
 * Removes both price and volume chart instances and all series
 */
function cleanupChart() {
    // Remove resize listener
    if (chartResizeHandler) {
        window.removeEventListener('resize', chartResizeHandler);
        chartResizeHandler = null;
    }

    // Clear all series references (price chart indicators + volume)
    candlestickSeries = null;
    volumeSeries = null;
    rsiSeries = null;
    bbUpperSeries = null;
    bbMiddleSeries = null;
    bbLowerSeries = null;
    emaSeries = null;
    tradeMarkers = [];
    chartBars = [];

    // Remove price chart instance (top panel)
    if (priceChartInstance) {
        try {
            priceChartInstance.remove?.();
        } catch (e) {
            console.warn('Error removing price chart:', e);
        }
        priceChartInstance = null;
    }

    // Remove volume chart instance (bottom panel)
    if (volumeChartInstance) {
        try {
            volumeChartInstance.remove?.();
        } catch (e) {
            console.warn('Error removing volume chart:', e);
        }
        volumeChartInstance = null;
    }
}

/**
 * Clean up all resources when page is unloaded
 */
function cleanupOnUnload() {
    // Close WebSocket connection
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.close();
    }

    // Clear all timers
    if (wsReconnectTimer) {
        clearTimeout(wsReconnectTimer);
    }

    if (wsHeartbeatInterval) {
        clearInterval(wsHeartbeatInterval);
    }

    if (durationTimer) {
        clearInterval(durationTimer);
    }

    // Clean up chart
    cleanupChart();
}

// Add page unload handler
window.addEventListener('beforeunload', function(e) {
    cleanupOnUnload();

    // Warn user if session is running
    if (sessionStatus === 'running') {
        e.preventDefault();
        e.returnValue = 'Trading session is still active. Are you sure you want to leave?';
        return e.returnValue;
    }
});

// Handle tab visibility changes
document.addEventListener('visibilitychange', function() {
    if (document.hidden) {
        // Page is hidden - session continues running
        console.log('Page hidden - session continues running');
    } else {
        // Page is visible again - refresh data
        console.log('Page visible - refreshing data');
        if (currentSessionId && sessionStatus === 'running') {
            fetchSessionStatus();
        }
    }
});

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
