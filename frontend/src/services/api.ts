const BASE = '/api/v1';

async function request<T>(url: string, options?: RequestInit): Promise<T> {
    const res = await fetch(`${BASE}${url}`, {
        headers: { 'Content-Type': 'application/json' },
        ...options,
    });
    if (!res.ok) {
        // 502/503 = device disconnected — update UI state
        if (res.status === 502 || res.status === 503) {
            try {
                const { useDeviceStore } = await import('../stores/deviceStore');
                useDeviceStore.getState().setConnected(false);
            } catch { /* ignore */ }
        }
        const body = await res.json().catch(() => ({}));
        const detail = body.error || body.detail || `HTTP ${res.status}`;
        throw new Error(detail);
    }
    return res.json();
}

export const api = {
    // ── Hardware ──────────────────────────────────────
    getHardwareConfig: () => request<unknown>('/hardware/config'),
    getDeviceStatus: () => request<unknown>('/device/status'),

    // ── GPIO ──────────────────────────────────────────
    gpioConfig: (gpio: number, mode: number, pull = 0, edge = 0) =>
        request('/gpio/' + gpio + '/config', { method: 'POST', body: JSON.stringify({ mode, pull, edge }) }),
    gpioSet: (gpio: number, value: number) =>
        request('/gpio/' + gpio + '/set', { method: 'POST', body: JSON.stringify({ value }) }),
    gpioGet: (gpio: number) =>
        request('/gpio/' + gpio + '/get'),
    gpioAdc: (gpio: number, samples = 1) =>
        request('/gpio/' + gpio + '/adc', { method: 'POST', body: JSON.stringify({ samples }) }),

    // ── Signal ────────────────────────────────────────
    signalTx: (gpio: number, signal: { level: number; duration_us: number }[], delay_us = 0) =>
        request('/gpio/' + gpio + '/signal/tx', { method: 'POST', body: JSON.stringify({ signal, delay_us }) }),
    signalRx: (gpio: number, timeout_us = 1_000_000, max_edges = 100) =>
        request('/gpio/' + gpio + '/signal/rx', { method: 'POST', body: JSON.stringify({ timeout_us, max_edges }) }),
    signalExchange: (
        gpio: number,
        tx_signal: { level: number; duration_us: number }[],
        delay_us = 0,
        rx_total_us = 500_000,
        rx_max_edges = 100,
        rx_resolution_us = 1,
    ) =>
        request('/gpio/' + gpio + '/signal/exchange', {
            method: 'POST',
            body: JSON.stringify({ tx_signal, delay_us, rx_total_us, rx_max_edges, rx_resolution_us }),
        }),

    // ── UART ──────────────────────────────────────────
    uartConfig: (
        uart_id: number,
        opts: {
            baudrate: number;
            tx_gpio: number;
            rx_gpio: number;
            data_bits?: number;
            parity?: number;
            stop_bits?: number;
        },
    ) =>
        request('/uart/' + uart_id + '/config', {
            method: 'POST',
            body: JSON.stringify({
                baudrate: opts.baudrate,
                data_bits: opts.data_bits ?? 8,
                parity: opts.parity ?? 0,
                stop_bits: opts.stop_bits ?? 1,
                tx_gpio: opts.tx_gpio,
                rx_gpio: opts.rx_gpio,
            }),
        }),
    uartSend: (uart_id: number, data: string) =>
        request('/uart/' + uart_id + '/send', { method: 'POST', body: JSON.stringify({ data }) }),
    uartSendHex: (uart_id: number, hexStr: string) => {
        const bytes = hexStr.split(/\s+/).filter(Boolean).map((h) => parseInt(h, 16));
        const base64 = btoa(String.fromCharCode(...bytes));
        return request('/uart/' + uart_id + '/send', { method: 'POST', body: JSON.stringify({ data_base64: base64 }) });
    },
    uartRead: (uart_id: number, length = 256, timeout_ms = 3000) =>
        request('/uart/' + uart_id + '/read?length=' + length + '&timeout_ms=' + timeout_ms),

    // ── Port ──────────────────────────────────────────
    portBind: (resource_type: number, id: number, owner_id = 1) =>
        request('/port/bind', { method: 'POST', body: JSON.stringify({ resource_type, id, owner_id }) }),
    portUnbind: (resource_type: number, id: number) =>
        request('/port/unbind', { method: 'POST', body: JSON.stringify({ resource_type, id }) }),
    portStatus: (resource_type: number, id: number) =>
        request('/port/status?resource_type=' + resource_type + '&id=' + id),

    // ── BLE ───────────────────────────────────────────
    blePairingEnable: (timeout_s = 60) =>
        request('/ble/pairing/enable', { method: 'POST', body: JSON.stringify({ timeout_s }) }),
    blePairingDisable: () =>
        request('/ble/pairing/disable', { method: 'POST' }),
    blePeers: () =>
        request('/ble/peers'),
    bleScanStart: (interval_s = 5) =>
        request('/ble/scan/start', { method: 'POST', body: JSON.stringify({ interval_s }) }),
    bleScanStop: () =>
        request('/ble/scan/stop', { method: 'POST' }),

    // ── BLE Device Names ──────────────────────────────
    listBleDeviceNames: () =>
        request<{ data: { names: { mac: string; name: string }[] } }>('/ble/device-names'),
    setBleDeviceName: (mac: string, name: string) =>
        request('/ble/device-names/' + encodeURIComponent(mac), {
            method: 'PUT',
            body: JSON.stringify({ name }),
        }),
    deleteBleDeviceName: (mac: string) =>
        request('/ble/device-names/' + encodeURIComponent(mac), { method: 'DELETE' }),

    // ── System ────────────────────────────────────────
    ping: () =>
        request('/system/ping', { method: 'POST' }),
    heartbeat: () =>
        request('/system/heartbeat', { method: 'POST' }),
    sync: () =>
        request('/system/sync', { method: 'POST' }),
    syncConfirm: (correlation_id: string, stage: number) =>
        request('/system/sync/confirm', { method: 'POST', body: JSON.stringify({ correlation_id, stage }) }),
    threadPassthrough: (device_id: string, correlation_id: string, payload: string) =>
        request('/thread/passthrough', { method: 'POST', body: JSON.stringify({ device_id, correlation_id, payload }) }),

    // ── Custom Commands ───────────────────────────────
    listCmds: () =>
        request<unknown>('/cmds'),
    createCmd: (data: Record<string, unknown>) =>
        request('/cmds', { method: 'POST', body: JSON.stringify(data) }),
    getCmd: (slug: string) =>
        request('/cmds/' + slug),
    updateCmd: (slug: string, data: Record<string, unknown>) =>
        request('/cmds/' + slug, { method: 'PUT', body: JSON.stringify(data) }),
    deleteCmd: (slug: string) =>
        request('/cmds/' + slug, { method: 'DELETE' }),
    executeCmd: (slug: string, params = {}) =>
        request('/cmds/' + slug + '/execute', { method: 'POST', body: JSON.stringify({ params }) }),

    // ── Pin lock & expected state ─────────────────────
    getLocks: () => request<{ data: { gpio: number; locked: boolean; expected_mode?: number; expected_value?: number }[] }>('/pins/locks'),
    lockPin: (gpio: number, expected_mode?: number, expected_value?: number) =>
        request('/pins/' + gpio + '/lock', { method: 'POST', body: JSON.stringify({ expected_mode, expected_value }) }),
    unlockPin: (gpio: number) =>
        request('/pins/' + gpio + '/lock', { method: 'DELETE' }),
    saveExpectedState: (gpio: number, body: { expected_mode?: number; expected_value?: number }) =>
        request('/pins/' + gpio + '/expected', { method: 'POST', body: JSON.stringify(body) }),
    saveUartConfig: (uart_id: number, body: { baudrate: number; tx_gpio: number; rx_gpio: number; data_bits?: number; parity?: number; stop_bits?: number }) =>
        request('/pins/uart/' + uart_id, { method: 'POST', body: JSON.stringify(body) }),
    deleteUartConfig: (uart_id: number) =>
        request('/pins/uart/' + uart_id, { method: 'DELETE' }),
};
