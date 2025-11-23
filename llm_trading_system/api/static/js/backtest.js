/**
 * Backtest Results Page JavaScript
 *
 * Usage: Set window.BACKTEST_CONFIG before loading this script:
 *   window.BACKTEST_CONFIG = { strategyName: 'my-strategy', symbol: 'BTCUSDT' };
 */

// =============================================================================
// Utility Functions
// =============================================================================

/**
 * Generic fetch wrapper with error handling
 * @param {string} url - URL to fetch
 * @param {Object} options - fetch options
 * @param {Object} config - additional config { expectSuccess: boolean }
 * @returns {Promise<Object>} - parsed JSON response
 */
async function fetchJson(url, options = {}, { expectSuccess = false } = {}) {
    const response = await fetch(url, options);
    if (!response.ok) {
        let msg = `Request failed: ${response.status}`;
        try {
            const errData = await response.json();
            if (errData.detail) msg = errData.detail;
        } catch (_) {}
        throw new Error(msg);
    }
    const data = await response.json();
    if (expectSuccess && data.success === false) {
        throw new Error('Operation failed');
    }
    return data;
}

/**
 * Get CSRF token from cookie
 * @returns {string}
 */
function getCsrfToken() {
    const value = `; ${document.cookie}`;
    const parts = value.split(`; csrf_token=`);
    if (parts.length === 2) return parts.pop().split(';').shift();
    return '';
}

/**
 * Format Unix timestamp to readable date
 * @param {number} timestamp - Unix timestamp in seconds
 * @returns {string}
 */
function formatDateTime(timestamp) {
    if (!timestamp) return '-';
    const date = new Date(timestamp * 1000);
    return date.toLocaleString('en-US', {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit'
    });
}

// =============================================================================
// Global State
// =============================================================================

let priceChartInstance = null;
let volumeChartInstance = null;
let candlestickSeries = null;
let volumeSeries = null;
let chartData = null;
let tradesData = null;
let currentFilter = 'all';
let currentSort = { column: 'index', direction: 'asc' };
let currentParams = null;

// Get config from window object (set by template)
const config = window.BACKTEST_CONFIG || {};
const strategyName = config.strategyName || '';
const strategySymbol = config.symbol || '';

// =============================================================================
// Chart Functions
// =============================================================================

/**
 * Load chart and trades data from API
 */
async function loadChartData() {
    try {
        const data = await fetchJson(`/ui/backtest/${strategyName}/chart-data`);
        chartData = data;
        tradesData = data.trades || [];

        document.getElementById('chart-loading').style.display = 'none';
        initializeChart(data.ohlcv, data.trades);
        renderTradesTable(tradesData);
    } catch (error) {
        console.error('Failed to load chart data:', error);
        const loadingEl = document.getElementById('chart-loading');
        const errorDiv = document.createElement('div');
        errorDiv.className = 'error';
        errorDiv.textContent = 'Failed to load chart data: ' + error.message;
        loadingEl.innerHTML = '';
        loadingEl.appendChild(errorDiv);
    }
}

/**
 * Initialize Lightweight Charts
 * @param {Array} ohlcv - OHLCV data
 * @param {Array} trades - Trades data
 */
function initializeChart(ohlcv, trades) {
    const priceContainer = document.getElementById('price-chart');
    const volumeContainer = document.getElementById('volume-chart');

    // Remove existing chart instances
    if (priceChartInstance) {
        try { priceChartInstance.remove(); } catch (e) { console.warn('Error removing price chart:', e); }
        priceChartInstance = null;
        candlestickSeries = null;
    }

    if (volumeChartInstance) {
        try { volumeChartInstance.remove(); } catch (e) { console.warn('Error removing volume chart:', e); }
        volumeChartInstance = null;
        volumeSeries = null;
    }

    priceContainer.innerHTML = '';
    volumeContainer.innerHTML = '';

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

    candlestickSeries = priceChartInstance.addCandlestickSeries({
        upColor: '#10b981',
        downColor: '#ef4444',
        borderUpColor: '#10b981',
        borderDownColor: '#ef4444',
        wickUpColor: '#10b981',
        wickDownColor: '#ef4444',
    });

    candlestickSeries.setData(ohlcv);

    // Create volume chart
    volumeChartInstance = LightweightCharts.createChart(volumeContainer, {
        width: volumeContainer.clientWidth,
        height: 150,
        ...commonOptions,
    });

    volumeSeries = volumeChartInstance.addHistogramSeries({
        color: '#9ca3af',
        priceFormat: { type: 'volume' },
    });

    const volumeData = ohlcv.map(d => ({
        time: d.time,
        value: d.volume || 0,
        color: d.close >= d.open ? 'rgba(16, 185, 129, 0.5)' : 'rgba(239, 68, 68, 0.5)'
    }));
    volumeSeries.setData(volumeData);

    // Add trade markers
    updateTradeMarkers(trades);

    // Synchronize time scales
    let isSyncing = false;

	const priceTimeScale = priceChartInstance.timeScale();
	const volumeTimeScale = volumeChartInstance.timeScale();

	priceTimeScale.subscribeVisibleLogicalRangeChange((logicalRange) => {
		if (!logicalRange || isSyncing) return;

		isSyncing = true;
		volumeTimeScale.setVisibleLogicalRange(logicalRange);
		isSyncing = false;
	});

	volumeTimeScale.subscribeVisibleLogicalRangeChange((logicalRange) => {
		if (!logicalRange || isSyncing) return;

		isSyncing = true;
		priceTimeScale.setVisibleLogicalRange(logicalRange);
		isSyncing = false;
	});

    // Auto-resize
    window.addEventListener('resize', () => {
        priceChartInstance.applyOptions({ width: priceContainer.clientWidth });
        volumeChartInstance.applyOptions({ width: volumeContainer.clientWidth });
    });

    priceChartInstance.timeScale().fitContent();
    volumeChartInstance.timeScale().fitContent();
}

/**
 * Update trade markers on chart
 * @param {Array} trades - Trades data
 */
function updateTradeMarkers(trades) {
    if (!candlestickSeries || !trades) return;

    const markers = [];

    trades.forEach(trade => {
        const isLong = trade.side.toUpperCase() === 'LONG';

        markers.push({
            time: trade.entry_time,
            position: isLong ? 'belowBar' : 'aboveBar',
            color: isLong ? '#10b981' : '#ef4444',
            shape: isLong ? 'arrowUp' : 'arrowDown',
            text: `${trade.side} Entry`,
        });

        if (trade.exit_time) {
            markers.push({
                time: trade.exit_time,
                position: isLong ? 'aboveBar' : 'belowBar',
                color: isLong ? '#10b981' : '#ef4444',
                shape: isLong ? 'arrowDown' : 'arrowUp',
                text: `${trade.side} Exit`,
            });
        }
    });

    candlestickSeries.setMarkers(markers);
}

/**
 * Apply time range filter to charts
 * @param {string} range - Time range ('1d', '7d', '1m', 'all')
 */
function applyTimeRange(range) {
    if (!priceChartInstance || !volumeChartInstance || !chartData) return;

    const now = Date.now() / 1000;
    let from;

    switch (range) {
        case '1d': from = now - 86400; break;
        case '7d': from = now - 7 * 86400; break;
        case '1m': from = now - 30 * 86400; break;
        case 'all':
        default:
            priceChartInstance.timeScale().fitContent();
            volumeChartInstance.timeScale().fitContent();
            return;
    }

    const timeRange = { from, to: now };
    priceChartInstance.timeScale().setVisibleRange(timeRange);
    volumeChartInstance.timeScale().setVisibleRange(timeRange);
}

// =============================================================================
// Trades Table Functions
// =============================================================================

/**
 * Render trades table
 * @param {Array} trades - Trades data
 */
function renderTradesTable(trades) {
    const tbody = document.getElementById('trades-table-body');

    if (!trades || trades.length === 0) {
        tbody.innerHTML = '<tr><td colspan="10" style="text-align: center; color: #6b7280;">No trades to display</td></tr>';
        return;
    }

    let filteredTrades = filterTrades(trades, currentFilter);
    filteredTrades = sortTrades(filteredTrades, currentSort.column, currentSort.direction);

    tbody.innerHTML = filteredTrades.map((trade, idx) => {
        const pnlPct = ((trade.exit_price - trade.entry_price) / trade.entry_price * 100) * (trade.side.toUpperCase() === 'LONG' ? 1 : -1);
        const pnlAbs = trade.pnl || 0;
        const isProfit = pnlAbs > 0;
        const size = trade.size || 0;

        return `
            <tr class="${isProfit ? 'profit' : 'loss'}" data-trade-index="${idx}">
                <td>${idx + 1}</td>
                <td class="trade-type-${trade.side.toLowerCase()}">${trade.side.toUpperCase()}</td>
                <td>${formatDateTime(trade.entry_time)}</td>
                <td>$${trade.entry_price.toFixed(2)}</td>
                <td>${formatDateTime(trade.exit_time)}</td>
                <td>$${trade.exit_price.toFixed(2)}</td>
                <td>${(size * 100).toFixed(1)}%</td>
                <td class="${isProfit ? 'pnl-positive' : 'pnl-negative'}">${pnlPct >= 0 ? '+' : ''}${pnlPct.toFixed(2)}%</td>
                <td class="${isProfit ? 'pnl-positive' : 'pnl-negative'}">${pnlAbs >= 0 ? '+' : ''}$${pnlAbs.toFixed(2)}</td>
                <td>${trade.bars_held || '-'}</td>
            </tr>
        `;
    }).join('');
}

/**
 * Filter trades by type/result
 * @param {Array} trades - Trades data
 * @param {string} filter - Filter type
 * @returns {Array}
 */
function filterTrades(trades, filter) {
    switch (filter) {
        case 'long': return trades.filter(t => t.side.toUpperCase() === 'LONG');
        case 'short': return trades.filter(t => t.side.toUpperCase() === 'SHORT');
        case 'profit': return trades.filter(t => (t.pnl || 0) > 0);
        case 'loss': return trades.filter(t => (t.pnl || 0) < 0);
        default: return trades;
    }
}

/**
 * Sort trades by column
 * @param {Array} trades - Trades data
 * @param {string} column - Column to sort by
 * @param {string} direction - Sort direction ('asc' or 'desc')
 * @returns {Array}
 */
function sortTrades(trades, column, direction) {
    return [...trades].sort((a, b) => {
        let aVal, bVal;

        switch (column) {
            case 'type': aVal = a.side; bVal = b.side; break;
            case 'entry_time': aVal = new Date(a.entry_time).getTime(); bVal = new Date(b.entry_time).getTime(); break;
            case 'exit_time': aVal = new Date(a.exit_time).getTime(); bVal = new Date(b.exit_time).getTime(); break;
            case 'entry_price': aVal = a.entry_price; bVal = b.entry_price; break;
            case 'exit_price': aVal = a.exit_price; bVal = b.exit_price; break;
            case 'size': aVal = a.size || 0; bVal = b.size || 0; break;
            case 'pnl_pct':
                aVal = ((a.exit_price - a.entry_price) / a.entry_price) * (a.side.toUpperCase() === 'LONG' ? 1 : -1);
                bVal = ((b.exit_price - b.entry_price) / b.entry_price) * (b.side.toUpperCase() === 'LONG' ? 1 : -1);
                break;
            case 'pnl_abs': aVal = a.pnl || 0; bVal = b.pnl || 0; break;
            case 'bars': aVal = a.bars_held || 0; bVal = b.bars_held || 0; break;
            default: return 0;
        }

        if (aVal < bVal) return direction === 'asc' ? -1 : 1;
        if (aVal > bVal) return direction === 'asc' ? 1 : -1;
        return 0;
    });
}

// =============================================================================
// Modal Functions
// =============================================================================

/**
 * Setup modal drag & drop functionality
 */
function setupModalDrag() {
    const modalContent = document.querySelector('.modal-content');
    const modalHeader = document.querySelector('.modal-header');

    if (!modalContent || !modalHeader) return;

    let isDragging = false;
    let initialX, initialY;

    modalHeader.addEventListener('mousedown', function(e) {
        if (e.target.closest('.modal-close') || e.target.closest('button')) return;
        initialX = e.clientX - (modalContent.offsetLeft || 0);
        initialY = e.clientY - (modalContent.offsetTop || 0);
        isDragging = true;
    });

    document.addEventListener('mousemove', function(e) {
        if (!isDragging) return;
        e.preventDefault();

        let currentX = e.clientX - initialX;
        let currentY = e.clientY - initialY;

        const maxX = window.innerWidth - modalContent.offsetWidth;
        const maxY = window.innerHeight - modalContent.offsetHeight;

        currentX = Math.max(0, Math.min(currentX, maxX));
        currentY = Math.max(0, Math.min(currentY, maxY));

        modalContent.style.left = currentX + 'px';
        modalContent.style.top = currentY + 'px';
        modalContent.style.transform = 'none';
    });

    document.addEventListener('mouseup', function() {
        isDragging = false;
    });
}

/**
 * Close modal and reset position
 */
function closeModal() {
    const modal = document.getElementById('params-modal');
    const modalContent = document.querySelector('.modal-content');
    const modalStatus = document.getElementById('modal-status');

    modal.classList.remove('active');
    if (modalStatus) {
        modalStatus.textContent = '';
        modalStatus.className = 'modal-status';
    }

    modalContent.style.left = '50%';
    modalContent.style.top = '50px';
    modalContent.style.transform = 'translateX(-50%)';
}

/**
 * Set modal status message
 * @param {string} message - Status message
 * @param {string} type - Status type ('loading', 'success', 'error', '')
 */
function setModalStatus(message, type = '') {
    const modalStatus = document.getElementById('modal-status');
    modalStatus.textContent = message;
    modalStatus.className = 'modal-status';
    if (type) modalStatus.classList.add(type);
}

/**
 * Toggle visibility of conditional settings
 */
function toggleModalCheckboxSettings() {
    const toggleSetting = (checkboxId, settingsId) => {
        const checkbox = document.getElementById(checkboxId);
        const settings = document.getElementById(settingsId);
        if (checkbox && settings) {
            settings.style.display = checkbox.checked ? 'block' : 'none';
        }
    };

    toggleSetting('param_use_martingale', 'param_martingale_settings');
    toggleSetting('param_use_tp_sl', 'param_tp_sl_settings');
    toggleSetting('param_time_filter_enabled', 'param_time_filter_settings');
}

/**
 * Populate form with parameters
 * @param {Object} params - Strategy parameters
 */
function populateForm(params) {
    const setValue = (id, value, defaultVal) => {
        const el = document.getElementById(id);
        if (el) el.value = value !== undefined ? value : defaultVal;
    };

    const setChecked = (id, value, defaultVal = false) => {
        const el = document.getElementById(id);
        if (el) el.checked = value !== undefined ? value : defaultVal;
    };

    // Strategy Type & Mode
    setValue('param_strategy_type', params.strategy_type, 'indicator');
    setValue('param_mode', params.mode, 'quant_only');
    setValue('param_symbol', params.symbol, 'BTCUSDT');

    // Indicator Parameters
    setValue('param_rsi_len', params.rsi_len, 14);
    setValue('param_rsi_ovb', params.rsi_ovb, 70);
    setValue('param_rsi_ovs', params.rsi_ovs, 30);
    setValue('param_bb_len', params.bb_len, 20);
    setValue('param_bb_mult', params.bb_mult, 2.0);
    setValue('param_ema_fast_len', params.ema_fast_len, 12);
    setValue('param_ema_slow_len', params.ema_slow_len, 26);
    setValue('param_atr_len', params.atr_len, 14);
    setValue('param_adx_len', params.adx_len, 14);
    setValue('param_vol_ma_len', params.vol_ma_len, 21);
    setValue('param_vol_mult', params.vol_mult, 0.5);

    // Position & Risk Management
    setValue('param_base_position_pct', params.base_position_pct, 10.0);
    setValue('param_pyramiding', params.pyramiding, 1);
    setValue('param_martingale_mult', params.martingale_mult, 1.5);
    setValue('param_max_position_size', params.max_position_size, 0.25);
    setChecked('param_allow_long', params.allow_long !== false, true);
    setChecked('param_allow_short', params.allow_short !== false, true);
    setChecked('param_use_martingale', params.use_martingale);

    // TP/SL
    setChecked('param_use_tp_sl', params.use_tp_sl);
    setValue('param_tp_long_pct', params.tp_long_pct, 2.0);
    setValue('param_sl_long_pct', params.sl_long_pct, 2.0);
    setValue('param_tp_short_pct', params.tp_short_pct, 2.0);
    setValue('param_sl_short_pct', params.sl_short_pct, 2.0);

    // Time Filter
    setChecked('param_time_filter_enabled', params.time_filter_enabled);
    setValue('param_time_filter_start_hour', params.time_filter_start_hour, 0);
    setValue('param_time_filter_end_hour', params.time_filter_end_hour, 23);

    // LLM Parameters
    setValue('param_k_max', params.k_max, 2.0);
    setValue('param_llm_horizon_hours', params.llm_horizon_hours, 24);
    setValue('param_llm_min_prob_edge', params.llm_min_prob_edge, 0.55);
    setValue('param_llm_min_trend_strength', params.llm_min_trend_strength, 0.6);
    setValue('param_llm_refresh_interval_bars', params.llm_refresh_interval_bars, 60);

    // Trading Rules
    const rulesEl = document.getElementById('param_rules');
    if (rulesEl) rulesEl.value = JSON.stringify(params.rules || {}, null, 2);

    toggleModalCheckboxSettings();
}

/**
 * Collect form parameters
 * @returns {Object} - Collected parameters
 */
function collectFormParams() {
    const getInt = (id, def) => parseInt(document.getElementById(id)?.value) || def;
    const getFloat = (id, def) => parseFloat(document.getElementById(id)?.value) || def;
    const getString = (id, def) => document.getElementById(id)?.value || def;
    const getBool = (id) => document.getElementById(id)?.checked || false;

    const params = {
        // Strategy Type & Mode
        strategy_type: getString('param_strategy_type', 'indicator'),
        mode: getString('param_mode', 'quant_only'),
        symbol: getString('param_symbol', 'BTCUSDT'),

        // Indicator Parameters
        rsi_len: getInt('param_rsi_len', 14),
        rsi_ovb: getInt('param_rsi_ovb', 70),
        rsi_ovs: getInt('param_rsi_ovs', 30),
        bb_len: getInt('param_bb_len', 20),
        bb_mult: getFloat('param_bb_mult', 2.0),
        ema_fast_len: getInt('param_ema_fast_len', 12),
        ema_slow_len: getInt('param_ema_slow_len', 26),
        atr_len: getInt('param_atr_len', 14),
        adx_len: getInt('param_adx_len', 14),
        vol_ma_len: getInt('param_vol_ma_len', 21),
        vol_mult: getFloat('param_vol_mult', 0.5),

        // Position & Risk Management
        base_position_pct: getFloat('param_base_position_pct', 10.0),
        pyramiding: getInt('param_pyramiding', 1),
        allow_long: getBool('param_allow_long'),
        allow_short: getBool('param_allow_short'),
        use_martingale: getBool('param_use_martingale'),
        martingale_mult: getFloat('param_martingale_mult', 1.5),
        max_position_size: getFloat('param_max_position_size', 0.25),

        // TP/SL
        use_tp_sl: getBool('param_use_tp_sl'),
        tp_long_pct: getFloat('param_tp_long_pct', 2.0),
        sl_long_pct: getFloat('param_sl_long_pct', 2.0),
        tp_short_pct: getFloat('param_tp_short_pct', 2.0),
        sl_short_pct: getFloat('param_sl_short_pct', 2.0),

        // Time Filter
        time_filter_enabled: getBool('param_time_filter_enabled'),
        time_filter_start_hour: getInt('param_time_filter_start_hour', 0),
        time_filter_end_hour: getInt('param_time_filter_end_hour', 23),

        // LLM Parameters
        k_max: getFloat('param_k_max', 2.0),
        llm_horizon_hours: getInt('param_llm_horizon_hours', 24),
        llm_min_prob_edge: getFloat('param_llm_min_prob_edge', 0.55),
        llm_min_trend_strength: getFloat('param_llm_min_trend_strength', 0.6),
        llm_refresh_interval_bars: getInt('param_llm_refresh_interval_bars', 60),
    };

    // Parse rules JSON
    try {
        const rulesText = document.getElementById('param_rules')?.value?.trim();
        params.rules = rulesText ? JSON.parse(rulesText) : (currentParams?.rules || {});
    } catch (e) {
        throw new Error('Invalid JSON in trading rules: ' + e.message);
    }

    return params;
}

/**
 * Update summary metrics on page
 * @param {Object} summary - Summary data
 */
function updateSummary(summary) {
    const metricsGrid = document.querySelector('.results-summary .metrics-grid');
    if (!metricsGrid) return;

    const metricElements = {
        'Symbol': summary.symbol,
        'Bars': summary.bars,
        'Trades': summary.trades,
        'P&L': `${summary.pnl_pct >= 0 ? '+' : ''}${summary.pnl_pct.toFixed(2)}%`,
        'P&L (Absolute)': `$${summary.pnl_abs.toFixed(2)}`,
        'Max Drawdown': `${summary.max_drawdown.toFixed(2)}%`,
        'Win Rate': `${summary.win_rate.toFixed(1)}%`,
        'Avg Trade P&L': `$${summary.avg_trade_pnl.toFixed(2)}`,
        'Final Equity': `$${summary.final_equity.toFixed(2)}`
    };

    metricsGrid.querySelectorAll('.metric').forEach(metric => {
        const label = metric.querySelector('.metric-label')?.textContent;
        const valueEl = metric.querySelector('.metric-value');

        if (metricElements[label] !== undefined && valueEl) {
            valueEl.textContent = metricElements[label];
            valueEl.classList.remove('positive', 'negative');

            if (label === 'P&L' || label === 'P&L (Absolute)') {
                valueEl.classList.add(summary.pnl_pct >= 0 || summary.pnl_abs >= 0 ? 'positive' : 'negative');
            } else if (label === 'Avg Trade P&L') {
                valueEl.classList.add(summary.avg_trade_pnl >= 0 ? 'positive' : 'negative');
            }
        }
    });
}

// =============================================================================
// Event Listeners Setup
// =============================================================================

function setupEventListeners() {
    // Time range buttons
    document.querySelectorAll('.time-range-btn').forEach(btn => {
        btn.addEventListener('click', function() {
            document.querySelectorAll('.time-range-btn').forEach(b => b.classList.remove('active'));
            this.classList.add('active');
            applyTimeRange(this.dataset.range);
        });
    });

    // Toggle trades checkbox
    const toggleTrades = document.getElementById('toggle-trades');
    if (toggleTrades) {
        toggleTrades.addEventListener('change', function() {
            if (this.checked) {
                updateTradeMarkers(tradesData);
            } else {
                candlestickSeries?.setMarkers([]);
            }
        });
    }

    // Trade filter buttons
    document.querySelectorAll('.filter-btn').forEach(btn => {
        btn.addEventListener('click', function() {
            document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
            this.classList.add('active');
            currentFilter = this.dataset.filter;
            renderTradesTable(tradesData);
        });
    });

    // Table sorting
    document.querySelectorAll('.trades-table th.sortable').forEach(th => {
        th.addEventListener('click', function() {
            const column = this.dataset.sort;

            if (currentSort.column === column) {
                currentSort.direction = currentSort.direction === 'asc' ? 'desc' : 'asc';
            } else {
                currentSort.column = column;
                currentSort.direction = 'asc';
            }

            document.querySelectorAll('.trades-table th').forEach(h => {
                h.classList.remove('sort-asc', 'sort-desc');
            });
            this.classList.add(`sort-${currentSort.direction}`);
            renderTradesTable(tradesData);
        });
    });

    // Trade row click - highlight on chart
    document.getElementById('trades-table-body')?.addEventListener('click', function(e) {
        const row = e.target.closest('tr[data-trade-index]');
        if (row) {
            const idx = parseInt(row.dataset.tradeIndex);
            const trade = tradesData[idx];
            if (trade && priceChartInstance && volumeChartInstance) {
                const timeRange = {
                    from: trade.entry_time - 86400,
                    to: (trade.exit_time || trade.entry_time) + 86400
                };
                priceChartInstance.timeScale().setVisibleRange(timeRange);
                volumeChartInstance.timeScale().setVisibleRange(timeRange);
            }
        }
    });

    // Modal event listeners
    setupModalEventListeners();
}

function setupModalEventListeners() {
    const modal = document.getElementById('params-modal');
    const editParamsBtn = document.getElementById('edit-params-btn');
    const modalCloseBtn = document.getElementById('modal-close-btn');
    const modalCancelBtn = document.getElementById('modal-cancel-btn');
    const recalculateBtn = document.getElementById('recalculate-btn');
    const saveParamsBtn = document.getElementById('save-params-btn');

    // Open modal
    editParamsBtn?.addEventListener('click', async () => {
        try {
            setModalStatus('Loading parameters...', 'loading');
            const data = await fetchJson(`/ui/strategies/${strategyName}/params`, {}, { expectSuccess: true });
            currentParams = data.params;
            populateForm(currentParams);
            modal.classList.add('active');
            setModalStatus('', '');
        } catch (error) {
            console.error('Failed to load parameters:', error);
            alert('Failed to load parameters: ' + error.message);
        }
    });

    // Close modal
    modalCloseBtn?.addEventListener('click', closeModal);
    modalCancelBtn?.addEventListener('click', closeModal);

    modal?.addEventListener('click', (e) => {
        if (e.target === modal) closeModal();
    });

    // Checkbox settings toggle
    ['param_use_martingale', 'param_use_tp_sl', 'param_time_filter_enabled'].forEach(id => {
        document.getElementById(id)?.addEventListener('change', toggleModalCheckboxSettings);
    });

    // Recalculate button
    recalculateBtn?.addEventListener('click', async () => {
        try {
            const params = collectFormParams();
            recalculateBtn.disabled = true;
            saveParamsBtn.disabled = true;
            setModalStatus('Recalculating backtest...', 'loading');

            const data = await fetchJson(`/ui/strategies/${strategyName}/recalculate`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ csrf_token: getCsrfToken(), params })
            }, { expectSuccess: true });

            updateSummary(data.summary);
            await loadChartData();
            setModalStatus('Backtest recalculated successfully!', 'success');
            currentParams = params;
        } catch (error) {
            console.error('Recalculate failed:', error);
            setModalStatus('Error: ' + error.message, 'error');
        } finally {
            recalculateBtn.disabled = false;
            saveParamsBtn.disabled = false;
        }
    });

    // Save button
    saveParamsBtn?.addEventListener('click', async () => {
        try {
            const params = collectFormParams();
            saveParamsBtn.disabled = true;
            recalculateBtn.disabled = true;

            // Step 1: Recalculate
            setModalStatus('Recalculating backtest...', 'loading');
            const recalcData = await fetchJson(`/ui/strategies/${strategyName}/recalculate`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ csrf_token: getCsrfToken(), params })
            }, { expectSuccess: true });

            updateSummary(recalcData.summary);

            // Step 2: Reload chart
            setModalStatus('Updating chart...', 'loading');
            await loadChartData();

            // Step 3: Save to disk
            setModalStatus('Saving parameters...', 'loading');
            await fetchJson(`/ui/strategies/${strategyName}/save-params`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ csrf_token: getCsrfToken(), params })
            }, { expectSuccess: true });

            currentParams = params;
            setModalStatus('Parameters saved and backtest recalculated successfully!', 'success');
            setTimeout(closeModal, 1500);
        } catch (error) {
            console.error('Save failed:', error);
            setModalStatus('Error: ' + error.message, 'error');
        } finally {
            saveParamsBtn.disabled = false;
            recalculateBtn.disabled = false;
        }
    });
}

// =============================================================================
// Initialize on DOM Ready
// =============================================================================

document.addEventListener('DOMContentLoaded', async function() {
    if (!strategyName) {
        console.error('BACKTEST_CONFIG.strategyName is not set');
        return;
    }
    await loadChartData();
    setupEventListeners();
    setupModalDrag();
});
