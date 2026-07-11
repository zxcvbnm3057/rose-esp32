import { create } from 'zustand';
import { api } from '../services/api';
import type { HardwareConfig, PinState, UartState } from '../types';

export interface UartGpioInfo {
    uart_id: number;
    role: 'tx' | 'rx';
}

export interface BleDevice {
    mac: string;
    rssi: number;
}

export interface BleState {
    pairingEnabled: boolean;
    scanEnabled: boolean;
    deviceCount: number;
}

export interface EdgeEvent {
    gpio: number;
    edge_type: number;
    timestamp_us: number;
}

interface DeviceStore {
    // Hardware config
    hardwareConfig: HardwareConfig | null;
    setHardwareConfig: (c: HardwareConfig) => void;

    // Connection
    connected: boolean;
    setConnected: (v: boolean) => void;
    syncing: boolean;
    setSyncing: (v: boolean) => void;

    // IO states: gpio → PinState
    pinStates: Record<number, PinState>;
    updatePin: (gpio: number, partial: Partial<PinState>) => void;
    hydrateStates: (states: PinState[]) => void;

    // UART states: uart_id → UartState
    uartStates: Record<number, UartState>;
    updateUart: (uart_id: number, partial: Partial<UartState>) => void;
    hydrateUarts: (states: UartState[]) => void;

    // Selected IO for editing
    selectedGpio: number | null;
    selectGpio: (gpio: number | null) => void;

    // Command history
    history: { time: string; op: string; result: string }[];
    addHistory: (entry: { time: string; op: string; result: string }) => void;

    // Edge events
    edgeEvents: EdgeEvent[];
    addEdgeEvent: (e: EdgeEvent) => void;
    clearEdgeEvents: () => void;
    monitoredPins: Set<number>;
    toggleMonitoredPin: (gpio: number) => void;

    // Mismatched pins (user's custom hardware config vs actual)
    mismatchPins: Set<number>;
    setPinMismatch: (gpio: number, v: boolean) => void;

    // Locked pins (prevent auto-assignment by UART etc.)
    lockedPins: Set<number>;
    toggleLock: (gpio: number) => void;

    // UART pin picker (when user is selecting TX/RX on chip)
    uartPinPicker: { uart_id: number; role: 'tx' | 'rx'; onPick: (gpio: number) => void } | null;
    setUartPinPicker: (p: { uart_id: number; role: 'tx' | 'rx'; onPick: (gpio: number) => void } | null) => void;

    // UART message log
    uartMessages: Array<{ uart_id: number; data: number[]; dir: 'rx' | 'tx'; timestamp: number }>;
    addUartMessage: (msg: { uart_id: number; data: number[]; dir: 'rx' | 'tx'; timestamp: number }) => void;
    clearUartMessages: () => void;

    // BLE
    bleState: BleState;
    setBleState: (partial: Partial<BleState>) => void;
    bleDevices: BleDevice[];
    setBleDevices: (devices: BleDevice[]) => void;
    upsertBleDevice: (mac: string, rssi: number) => void;
    removeBleDevice: (mac: string) => void;

    // Expected state from user config (persisted via API)
    expectedGpios: { gpio: number; locked: boolean; expected_mode?: number; expected_value?: number }[];
    setExpectedGpios: (gpios: { gpio: number; locked: boolean; expected_mode?: number; expected_value?: number }[]) => void;
    expectedUarts: { uart_id: number; baudrate: number; tx_gpio: number; rx_gpio: number }[];
    setExpectedUarts: (uarts: { uart_id: number; baudrate: number; tx_gpio: number; rx_gpio: number }[]) => void;
    runMismatchCheck: () => void;
    loadLocks: (gpios: number[]) => void;

    // Heartbeat / connection health
    lastHeartbeat: number;
    setLastHeartbeat: (ts: number) => void;
}

export const useDeviceStore = create<DeviceStore>((set) => ({
    hardwareConfig: null,
    setHardwareConfig: (c) => set({ hardwareConfig: c }),

    connected: false,
    setConnected: (v) => set({ connected: v }),

    syncing: true,
    setSyncing: (v) => set({ syncing: v }),

    pinStates: {},
    updatePin: (gpio, partial) =>
        set((s) => ({
            pinStates: {
                ...s.pinStates,
                [gpio]: { ...s.pinStates[gpio], ...partial } as PinState,
            },
        })),
    hydrateStates: (states) => {
        const map: Record<number, PinState> = {};
        states.forEach((s) => (map[s.gpio] = s));
        set({ pinStates: map });
    },

    uartStates: {},
    updateUart: (uart_id, partial) =>
        set((s) => ({
            uartStates: {
                ...s.uartStates,
                [uart_id]: { ...s.uartStates[uart_id], ...partial } as UartState,
            },
        })),
    hydrateUarts: (states) => {
        const map: Record<number, UartState> = {};
        states.forEach((s) => (map[s.uart_id] = s));
        set({ uartStates: map });
    },

    selectedGpio: null,
    selectGpio: (gpio) => set({ selectedGpio: gpio }),

    history: [],
    addHistory: (entry) =>
        set((s) => ({ history: [entry, ...s.history].slice(0, 50) })),

    edgeEvents: [],
    addEdgeEvent: (e) =>
        set((s) => ({ edgeEvents: [...s.edgeEvents.slice(-99), e] })),
    clearEdgeEvents: () => set({ edgeEvents: [] }),
    monitoredPins: new Set<number>(),
    toggleMonitoredPin: (gpio) =>
        set((s) => {
            const next = new Set(s.monitoredPins);
            if (next.has(gpio)) next.delete(gpio);
            else next.add(gpio);
            return { monitoredPins: next };
        }),

    mismatchPins: new Set<number>(),
    setPinMismatch: (gpio, v) =>
        set((s) => {
            const next = new Set(s.mismatchPins);
            if (v) next.add(gpio); else next.delete(gpio);
            return { mismatchPins: next };
        }),

    lockedPins: new Set<number>(),
    toggleLock: (gpio) =>
        set((s) => {
            const next = new Set(s.lockedPins);
            const wasLocked = next.has(gpio);
            if (wasLocked) {
                next.delete(gpio);
                api.unlockPin(gpio).catch(() => { });
            } else {
                next.add(gpio);
                api.lockPin(gpio).catch(() => { });
            }
            return { lockedPins: next };
        }),

    uartPinPicker: null,
    setUartPinPicker: (p) => set({ uartPinPicker: p }),

    uartMessages: [],
    addUartMessage: (msg) =>
        set((s) => ({ uartMessages: [...s.uartMessages.slice(-199), msg] })),
    clearUartMessages: () => set({ uartMessages: [] }),

    // BLE
    bleState: { pairingEnabled: false, scanEnabled: false, deviceCount: 0 },
    setBleState: (partial) =>
        set((s) => ({ bleState: { ...s.bleState, ...partial } })),
    bleDevices: [],
    setBleDevices: (devices) => set({ bleDevices: devices }),
    upsertBleDevice: (mac, rssi) =>
        set((s) => {
            const idx = s.bleDevices.findIndex((p) => p.mac === mac);
            if (idx >= 0) {
                const updated = [...s.bleDevices];
                updated[idx] = { mac, rssi };
                return { bleDevices: updated };
            }
            return { bleDevices: [...s.bleDevices, { mac, rssi }] };
        }),
    removeBleDevice: (mac) =>
        set((s) => ({ bleDevices: s.bleDevices.filter((p) => p.mac !== mac) })),

    // Expected state + mismatch
    expectedGpios: [],
    setExpectedGpios: (gpios) => set({ expectedGpios: gpios }),
    expectedUarts: [],
    setExpectedUarts: (uarts) => set({ expectedUarts: uarts }),
    runMismatchCheck: () => {
        const { expectedGpios, expectedUarts, pinStates, uartStates } = useDeviceStore.getState();
        const mismatches = new Set<number>();
        for (const e of expectedGpios) {
            const actual = pinStates[e.gpio];
            if (!actual) continue;
            if (e.expected_mode != null && actual.mode_code !== e.expected_mode) mismatches.add(e.gpio);
            if (e.expected_value != null && actual.value !== e.expected_value) mismatches.add(e.gpio);
        }
        for (const e of expectedUarts) {
            const actual = uartStates[e.uart_id];
            if (!actual) { mismatches.add(e.tx_gpio); mismatches.add(e.rx_gpio); continue; }
            if (e.baudrate !== actual.baudrate) { mismatches.add(e.tx_gpio); mismatches.add(e.rx_gpio); }
            if (e.tx_gpio !== actual.tx_gpio) mismatches.add(e.tx_gpio);
            if (e.rx_gpio !== actual.rx_gpio) mismatches.add(e.rx_gpio);
        }
        set({ mismatchPins: mismatches });
    },
    loadLocks: (gpios) => set({ lockedPins: new Set(gpios) }),

    lastHeartbeat: 0,
    setLastHeartbeat: (ts) => set({ lastHeartbeat: ts }),
}));

/** 查询某个 GPIO 是否被 UART 占用，返回 UART 信息 */
export function getUartForGpio(
    uartStates: Record<number, UartState>,
    gpio: number,
): UartGpioInfo | null {
    for (const [id, u] of Object.entries(uartStates)) {
        if (u.tx_gpio === gpio) return { uart_id: Number(id), role: 'tx' };
        if (u.rx_gpio === gpio) return { uart_id: Number(id), role: 'rx' };
    }
    return null;
}

/** 获取所有可分配给 UART 的 GPIO（未被其他 UART 占用 + 非保留） */
export function getAvailableUartPins(
    config: HardwareConfig | null,
    uartStates: Record<number, UartState>,
    excludeUartId?: number,
): number[] {
    if (!config) return [];
    const used = new Set<number>();
    for (const [id, u] of Object.entries(uartStates)) {
        if (excludeUartId != null && Number(id) === excludeUartId) continue;
        used.add(u.tx_gpio);
        used.add(u.rx_gpio);
    }
    return config.pins
        .filter((p) => !p.reserved && !used.has(p.gpio))
        .map((p) => p.gpio);
}
