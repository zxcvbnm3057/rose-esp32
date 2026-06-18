import type { PinState } from '../../types';

export interface Colors {
    border: string;
    fill: string;
    text: string;
}

export function getPinColors(
    state?: PinState,
    isReserved = false,
    uartRole?: 'tx' | 'rx' | null,
): Colors {
    if (isReserved) {
        return { border: '#374151', fill: '#111827', text: '#6b7280' };
    }

    // UART pins get special colors regardless of underlying GPIO mode
    if (uartRole === 'tx') {
        return { border: '#0ea5e9', fill: '#0c2d48', text: '#7dd3fc' };   // sky blue
    }
    if (uartRole === 'rx') {
        return { border: '#f97316', fill: '#3d1a00', text: '#fdba74' };   // orange
    }

    if (!state || state.mode === 'UNCONFIGURED') {
        return { border: '#4b5563', fill: '#1f2937', text: '#9ca3af' };
    }
    switch (state.mode) {
        case 'INPUT':
            return { border: '#3b82f6', fill: '#1e3a5f', text: '#93c5fd' };
        case 'OUTPUT':
            if (state.value === 1) return { border: '#22c55e', fill: '#14532d', text: '#86efac' };
            return { border: '#6b7280', fill: '#374151', text: '#9ca3af' };
        case 'INPUT_OUTPUT':
            if (state.value === 1) return { border: '#10b981', fill: '#064e3b', text: '#a7f3d0' };
            return { border: '#14b8a6', fill: '#134e4a', text: '#99f6e4' };
        case 'INTERRUPT':
            return { border: '#eab308', fill: '#422006', text: '#fde047' };
        case 'ADC':
            return { border: '#a855f7', fill: '#3b0764', text: '#d8b4fe' };
        case 'SIGNAL':
            return { border: '#ef4444', fill: '#450a0a', text: '#fca5a5' };
        default:
            return { border: '#4b5563', fill: '#1f2937', text: '#9ca3af' };
    }
}

export function getModeLabel(mode?: string): string {
    switch (mode) {
        case 'INPUT': return 'IN';
        case 'OUTPUT': return 'OUT';
        case 'INPUT_OUTPUT': return 'IO';
        case 'INTERRUPT': return 'INT';
        case 'ADC': return 'ADC';
        case 'SIGNAL': return 'SIG';
        default: return '';
    }
}
