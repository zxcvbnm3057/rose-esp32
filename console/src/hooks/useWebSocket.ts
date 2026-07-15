import { useEffect, useRef, useCallback } from 'react';
import { useDeviceStore } from '../stores/deviceStore';
import type { HardwareConfig, UartState } from '../types';

export function useWebSocket() {
    const wsRef = useRef<WebSocket | null>(null);
    const reconnectTimer = useRef<ReturnType<typeof setTimeout>>();
    const mountedRef = useRef(true);
    const store = useDeviceStore();

    const connect = useCallback(() => {
        if (!mountedRef.current) return;
        const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const ws = new WebSocket(`${wsProtocol}//${window.location.host}/ws?role=console`);
        wsRef.current = ws;

        ws.onopen = () => {
            console.log('WS connected');
        };

        ws.onclose = (ev) => {
            // Connection_change from bridge monitor is the primary source,
            // but as a fallback: if WS drops unexpectedly, mark disconnected.
            if (ev.code !== 4001) {
                store.setConnected(false);
            }
            if (mountedRef.current && ev.code !== 4001 && wsRef.current === ws) {
                clearTimeout(reconnectTimer.current);
                reconnectTimer.current = setTimeout(connect, 3000);
            }
        };

        ws.onmessage = (e) => {
            try {
                const msg = JSON.parse(e.data);
                switch (msg.type) {
                    case 'hardware_config':
                        store.setHardwareConfig(msg.data as HardwareConfig);
                        store.setSyncing(false);
                        break;
                    case 'device_state':
                        store.setSyncing(false);
                        // duplicate hydrate logic (avoid TS fallthrough error)
                        {
                            const d = msg.data as { gpios?: unknown[]; uarts?: UartState[] };
                            if (d.gpios) store.hydrateStates(d.gpios as Parameters<typeof store.hydrateStates>[0]);
                            if (d.uarts) store.hydrateUarts(d.uarts);
                        }
                        break;
                    case 'device_state_hydrate': {
                        const d = msg.data as { gpios?: unknown[]; uarts?: UartState[] };
                        if (d.gpios) store.hydrateStates(d.gpios as Parameters<typeof store.hydrateStates>[0]);
                        if (d.uarts) store.hydrateUarts(d.uarts);
                        break;
                    }
                    case 'connection_change':
                        store.setConnected(msg.connected as boolean);
                        break;
                    case 'kicked':
                        store.setConnected(false);
                        ws.close(4001);
                        break;
                    case 'port_status':
                        store.setSyncing(false);
                        if ((msg.resource_type as number) === 0) {
                            const gpio = msg.id as number;
                            const modes = ['INPUT', 'OUTPUT', 'INTERRUPT', 'ADC', 'SIGNAL', 'INPUT_OUTPUT'] as const;
                            const pulls = ['NONE', 'DOWN', 'UP'] as const;
                            const mc = msg.mode as number | undefined;
                            const pc = msg.pull as number | undefined;
                            const u: Record<string, unknown> = { bound: (msg.in_use as number) === 1 };
                            if (mc != null && mc >= 0 && mc <= 5) { u.mode = modes[mc]; u.mode_code = mc; }
                            if (pc != null && pc >= 0 && pc <= 2) { u.pull = pulls[pc]; u.pull_code = pc; }
                            if (msg.edge != null) u.edge = msg.edge as number;
                            if (msg.value != null) u.value = msg.value as number;
                            store.updatePin(gpio, u as never);
                        } else if ((msg.resource_type as number) === 1) {
                            const uid = msg.id as number;
                            store.updateUart(uid, {
                                uart_id: uid, bound: true,
                                baudrate: (msg.baudrate as number) ?? 115200,
                                tx_gpio: msg.tx_gpio as number,
                                rx_gpio: msg.rx_gpio as number,
                            });
                        }
                        break;
                    case 'gpio_value': {
                        const modes = ['INPUT', 'OUTPUT', 'INTERRUPT', 'ADC', 'SIGNAL', 'INPUT_OUTPUT'] as const;
                        const pulls = ['NONE', 'DOWN', 'UP'] as const;
                        const u: Record<string, unknown> = { value: msg.value as number };
                        const mc = msg.mode_code as number | undefined;
                        const pc = msg.pull_code as number | undefined;
                        if (mc != null && mc >= 0 && mc <= 5) { u.mode = modes[mc]; u.mode_code = mc; }
                        if (pc != null && pc >= 0 && pc <= 2) { u.pull = pulls[pc]; u.pull_code = pc; }
                        if (msg.edge != null) u.edge = msg.edge as number;
                        if (msg.bound != null) u.bound = msg.bound as boolean;
                        store.updatePin(msg.gpio as number, u as never);
                        break;
                    }
                    case 'gpio_edge':
                        store.addEdgeEvent({ gpio: msg.gpio as number, edge_type: msg.edge_type as number, timestamp_us: msg.timestamp_us as number });
                        break;
                    case 'adc_value':
                        store.updatePin(msg.gpio as number, { adc_value: msg.value as number, adc_voltage_mv: msg.voltage_mv as number ?? Math.round((msg.value as number) / 4095 * 3300) } as never);
                        break;
                    case 'uart_rx': {
                        const uid = msg.uart_id as number;
                        const raw = msg.data_base64 as string | undefined;
                        const bytes = raw ? Array.from(atob(raw), (c) => c.charCodeAt(0)) : [];
                        store.addUartMessage({ uart_id: uid, dir: 'rx', data: bytes, timestamp: Date.now() });
                        store.addHistory({ time: new Date().toLocaleTimeString(), op: `UART${uid} RX`, result: `← ${bytes.length}B` });
                        break;
                    }
                    case 'error':
                        store.addHistory({ time: new Date().toLocaleTimeString(), op: 'Error', result: `✗ ${msg.message}` });
                        break;

                    // ── BLE events ──────────────────────────────
                    case 'ble_status': {
                        const s = msg as Record<string, unknown>;
                        store.setBleState({
                            pairingEnabled: (s.pairing_enabled as number) === 1,
                            scanEnabled: (s.scan_enabled as number) === 1,
                            deviceCount: (s.device_count as number) ?? 0,
                        });
                        break;
                    }
                    case 'ble_pairing_enabled': {
                        const pin = msg.pin_code as string ?? '';
                        if (pin) {
                            store.setBleState({ pairingEnabled: true, scanEnabled: store.bleState.scanEnabled, deviceCount: store.bleState.deviceCount });
                        }
                        break;
                    }
                    case 'ble_pairing_disabled':
                        store.setBleState({ pairingEnabled: false, scanEnabled: store.bleState.scanEnabled, deviceCount: store.bleState.deviceCount });
                        break;
                    case 'ble_in_range_list': {
                        const devices = (msg.devices as Array<{ mac: string; rssi: number }>) ?? [];
                        store.setBleDevices(devices);
                        store.setBleState({ deviceCount: devices.length });
                        break;
                    }
                    case 'ble_device_in_range': {
                        const mac = msg.mac as string ?? '';
                        const rssi = msg.rssi as number ?? 0;
                        if (mac) {
                            store.upsertBleDevice(mac, rssi);
                            // Update deviceCount from actual devices array length
                            const currentDevices = useDeviceStore.getState().bleDevices;
                            store.setBleState({ deviceCount: currentDevices.length });
                        }
                        break;
                    }
                    case 'ble_device_out_of_range': {
                        const mac = msg.mac as string ?? '';
                        if (mac) {
                            store.removeBleDevice(mac);
                            // Update deviceCount from actual devices array length
                            const currentDevices = useDeviceStore.getState().bleDevices;
                            store.setBleState({ deviceCount: currentDevices.length });
                        }
                        break;
                    }
                    case 'ble_rssi': {
                        const mac = msg.mac as string ?? '';
                        const rssi = msg.rssi as number ?? 0;
                        if (mac && rssi != null) store.upsertBleDevice(mac, rssi);
                        break;
                    }

                    // ── Sync status events ────────────────────────
                    case 'gpio_status': {
                        const g = msg.gpio as number;
                        const modes = ['INPUT', 'OUTPUT', 'INTERRUPT', 'ADC', 'SIGNAL', 'INPUT_OUTPUT'] as const;
                        const pulls = ['NONE', 'DOWN', 'UP'] as const;
                        const mc = msg.mode as number | undefined;
                        const pc = msg.pull as number | undefined;
                        const u: Record<string, unknown> = {
                            value: msg.value as number,
                            bound: (msg.in_use as number) === 1,
                            edge: msg.edge as number,
                        };
                        if (mc != null && mc >= 0 && mc <= 5) { u.mode = modes[mc]; u.mode_code = mc; }
                        if (pc != null && pc >= 0 && pc <= 2) { u.pull = pulls[pc]; u.pull_code = pc; }
                        if (msg.adc_raw != null) u.adc_value = msg.adc_raw as number;
                        if (msg.adc_mv != null) u.adc_voltage_mv = msg.adc_mv as number;
                        store.updatePin(g, u as never);
                        break;
                    }
                    case 'uart_status': {
                        const uid = msg.uart_id as number;
                        store.updateUart(uid, {
                            uart_id: uid,
                            bound: (msg.in_use as number) === 1,
                            baudrate: (msg.baudrate as number) ?? 115200,
                            tx_gpio: msg.tx_gpio as number,
                            rx_gpio: msg.rx_gpio as number,
                            data_bits: msg.data_bits as number,
                            parity: msg.parity as number,
                            stop_bits: msg.stop_bits as number,
                        });
                        break;
                    }
                    case 'expected_state': {
                        const d = msg.data as { gpios?: { gpio: number; locked: boolean; expected_mode?: number; expected_value?: number }[]; uarts?: { uart_id: number; baudrate: number; tx_gpio: number; rx_gpio: number }[] };
                        if (d.gpios) {
                            store.setExpectedGpios(d.gpios);
                            store.loadLocks(d.gpios.filter((g) => g.locked).map((g) => g.gpio));
                        }
                        if (d.uarts) store.setExpectedUarts(d.uarts);
                        store.runMismatchCheck();
                        break;
                    }
                    case 'heartbeat':
                        store.setLastHeartbeat(msg.timestamp as number ?? Date.now());
                        break;
                    case 'signal_captured': {
                        const g = msg.gpio as number;
                        const edges = msg.edges as Array<{ level: number; duration_us: number }> | undefined;
                        store.addHistory({
                            time: new Date().toLocaleTimeString(),
                            op: `Signal@GPIO${g}`,
                            result: `captured ${msg.edge_count ?? (edges?.length ?? 0)} edges`,
                        });
                        break;
                    }
                }
            } catch { /* ignore */ }
        };
    }, []);

    useEffect(() => {
        mountedRef.current = true;
        connect();
        return () => {
            mountedRef.current = false;
            clearTimeout(reconnectTimer.current);
            const ws = wsRef.current;
            if (ws) { ws.onclose = null; wsRef.current = null; ws.close(); }
        };
    }, [connect]);

    const sendCommand = useCallback((op: string, params: Record<string, unknown>) => {
        if (wsRef.current?.readyState === WebSocket.OPEN) wsRef.current.send(JSON.stringify({ type: 'cmd', op, ...params }));
    }, []);

    return { sendCommand };
}
