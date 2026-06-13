// ── Hardware Config (from hardware_config.json) ─────────────

export interface ChipInfo {
    name: string;
    manufacturer: string;
    family: string;
}

export interface Capabilities {
    gpio: boolean;
    adc: boolean;
    signal: boolean;
    uart: boolean;
    uart_count: number;
    ble: boolean;
    thread: boolean;
    max_signal_edges: number;
    max_adc_samples: number;
}

export interface PinCapabilities {
    input: boolean;
    output: boolean;
    interrupt: boolean;
    adc: boolean;
    signal: boolean;
}

export interface PinConfig {
    gpio: number;
    label: string;
    side: 'top' | 'bottom' | 'left' | 'right';
    order: number;
    reserved: boolean;
    reserved_reason?: string | null;
    capabilities: PinCapabilities;
    adc_channel: number | null;
    default_mode: string;
    description: string;
}

export interface FeatureGroup {
    id: string;
    label: string;
    icon: string;
    enabled: boolean;
}

export interface HardwareConfig {
    chip: ChipInfo;
    capabilities: Capabilities;
    pins: PinConfig[];
    feature_groups: FeatureGroup[];
}

// ── IO State ────────────────────────────────────────────────

export interface PinState {
    gpio: number;
    mode: 'UNCONFIGURED' | 'INPUT' | 'OUTPUT' | 'INTERRUPT' | 'ADC' | 'SIGNAL';
    mode_code: number;
    value: number | null;
    adc_value: number | null;
    adc_voltage_mv: number | null;
    pull: 'NONE' | 'UP' | 'DOWN';
    pull_code: number;
    edge: number;
    bound: boolean;
    owner_id: number | null;
    timestamp_us: number;
}

export interface UartState {
    uart_id: number;
    bound: boolean;
    baudrate: number;
    tx_gpio: number;
    rx_gpio: number;
    data_bits?: number;
    parity?: number;
    stop_bits?: number;
}

export interface BleState {
    pairing_enabled: boolean;
    scan_enabled: boolean;
    peer_count: number;
}

// ── Custom Command ──────────────────────────────────────────

export interface CmdStep {
    step_type: string;
    config: Record<string, unknown>;
    delay_ms: number;
    on_error: 'abort' | 'continue';
}

export interface CustomCommand {
    id: number;
    slug: string;
    name: string;
    icon?: string;
    description: string;
    enabled: boolean;
    step_count: number;
    steps: CmdStep[];
    external_url: string;
    created_at: string | null;
    updated_at: string | null;
    last_executed_at: string | null;
    execution_count: number;
}

// ── API ─────────────────────────────────────────────────────

export interface ApiResponse<T = unknown> {
    success: boolean;
    data: T;
    error: string | null;
    timestamp: number;
}

export interface WsEvent {
    type: string;
    [key: string]: unknown;
}
