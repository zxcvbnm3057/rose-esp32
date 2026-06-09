import { create } from 'zustand';
import type { HardwareConfig, PinState, UartState } from '../types';

export interface UartGpioInfo {
    uart_id: number;
    role: 'tx' | 'rx';
}

interface DeviceStore {
    // Hardware config
    hardwareConfig: HardwareConfig | null;
    setHardwareConfig: (c: HardwareConfig) => void;

    // Connection
    connected: boolean;
    setConnected: (v: boolean) => void;

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
}

export const useDeviceStore = create<DeviceStore>((set) => ({
    hardwareConfig: null,
    setHardwareConfig: (c) => set({ hardwareConfig: c }),

    connected: false,
    setConnected: (v) => set({ connected: v }),

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
