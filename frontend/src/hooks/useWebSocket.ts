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
        const ws = new WebSocket('ws://127.0.0.1:8000/ws');
        wsRef.current = ws;

        ws.onopen = () => {
            console.log('WS connected');
            // 初始同步 BLE 状态（避免刷新丢数据）
            fetch('/api/v1/ble/peers').then(r => r.json()).then(d => {
                const peers = d?.data?.peers ?? [];
                store.setBlePeers(peers);
            }).catch(() => { });
        };

        ws.onclose = (ev) => {
            store.setConnected(false);
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
                    // fall through to hydrate
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
                            const modes = ['INPUT', 'OUTPUT', 'INTERRUPT', 'ADC', 'SIGNAL'] as const;
                            const mc = msg.mode as number | undefined;
                            const u: Record<string, unknown> = { bound: (msg.in_use as number) === 1 };
                            if (mc != null && mc >= 0 && mc <= 4) { u.mode = modes[mc]; u.mode_code = mc; }
                            if (msg.value != null) u.value = msg.value as number;
                            store.updatePin(gpio, u as never);
                        }
                        break;
                    case 'gpio_value': {
                        const modes = ['INPUT', 'OUTPUT', 'INTERRUPT', 'ADC', 'SIGNAL'] as const;
                        const u: Record<string, unknown> = { value: msg.value as number };
                        const mc = msg.mode_code as number | undefined;
                        if (mc != null && mc >= 0 && mc <= 4) { u.mode = modes[mc]; u.mode_code = mc; }
                        if (msg.bound != null) u.bound = msg.bound as boolean;
                        store.updatePin(msg.gpio as number, u as never);
                        break;
                    }
                    case 'gpio_edge':
                        store.updatePin(msg.gpio as number, { edge: msg.edge_type as number } as never);
                        store.addEdgeEvent({ gpio: msg.gpio as number, edge_type: msg.edge_type as number, timestamp_us: msg.timestamp_us as number });
                        break;
                    case 'adc_value':
                        store.updatePin(msg.gpio as number, { adc_value: msg.value as number, adc_voltage_mv: msg.voltage_mv as number ?? Math.round((msg.value as number) / 4095 * 3300) } as never);
                        break;
                    case 'uart_rx':
                        store.addHistory({ time: new Date().toLocaleTimeString(), op: `UART${msg.uart_id} RX`, result: `← ${(msg.data_base64 as string)?.length ?? 0}B` });
                        break;
                    case 'error':
                        store.addHistory({ time: new Date().toLocaleTimeString(), op: 'Error', result: `✗ ${msg.message}` });
                        break;

                    // ── BLE events ──────────────────────────────
                    case 'ble_status': {
                        const s = msg as Record<string, unknown>;
                        store.setBleState({
                            pairingEnabled: (s.pairing_enabled as number) === 1,
                            scanEnabled: (s.scan_enabled as number) === 1,
                            peerCount: (s.peer_count as number) ?? 0,
                        });
                        break;
                    }
                    case 'ble_pairing_enabled': {
                        const pin = msg.pin_code as string ?? '';
                        if (pin) {
                            store.setBleState({ pairingEnabled: true, scanEnabled: store.bleState.scanEnabled, peerCount: store.bleState.peerCount });
                        }
                        break;
                    }
                    case 'ble_pairing_disabled':
                        store.setBleState({ pairingEnabled: false, scanEnabled: store.bleState.scanEnabled, peerCount: store.bleState.peerCount });
                        break;
                    case 'ble_peers_list': {
                        const peers = (msg.peers as Array<{ mac: string; rssi: number }>) ?? [];
                        store.setBlePeers(peers);
                        break;
                    }
                    case 'ble_peer_connected': {
                        const mac = msg.mac as string ?? '';
                        const rssi = msg.rssi as number ?? 0;
                        if (mac) store.upsertBlePeer(mac, rssi);
                        break;
                    }
                    case 'ble_peer_disconnected': {
                        const mac = msg.mac as string ?? '';
                        if (mac) store.removeBlePeer(mac);
                        break;
                    }
                    case 'ble_rssi': {
                        const mac = msg.mac as string ?? '';
                        const rssi = msg.rssi as number ?? 0;
                        if (mac && rssi != null) store.upsertBlePeer(mac, rssi);
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
