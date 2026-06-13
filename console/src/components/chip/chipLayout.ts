// Chip layout utilities — grouping & fixed-pin detection.
// Visual layout: CSS Grid with rotation via pin-slot reassignment.

import type { PinConfig } from '../../types';

export const PAD_W = 56;
export const PAD_H = 36;

export interface PinGroup {
    top: PinConfig[];
    bottom: PinConfig[];
    left: PinConfig[];
    right: PinConfig[];
}

/** Group and sort pins by original side+order */
export function groupPins(pins: PinConfig[]): PinGroup {
    const g: PinGroup = { top: [], bottom: [], left: [], right: [] };
    for (const p of pins) {
        (g[p.side] ??= []).push(p);
    }
    for (const s of Object.keys(g) as (keyof PinGroup)[]) {
        g[s].sort((a, b) => a.order - b.order);
    }
    return g;
}

/** Map original side → grid slot for a given rotation (clockwise).
 *  Grid positions: left → top → right → bottom (clockwise).
 *  At 90°: original-left → bottom, original-bottom → right, etc.
 *  Formula: original side shifts by (4 - rotation/90) steps clockwise to grid position. */
export function rotateLayout(original: PinGroup, rotation: number): PinGroup {
    const order: (keyof PinGroup)[] = ['left', 'top', 'right', 'bottom'];
    const steps = (4 - Math.round(rotation / 90)) % 4;
    const map: Record<string, keyof PinGroup> = {};
    for (let i = 0; i < 4; i++) {
        map[order[i]] = order[(i + steps) % 4];
    }
    return {
        left: original[map.left],
        right: original[map.right],
        top: original[map.top],
        bottom: original[map.bottom],
    };
}

/** Check if a pin is a fixed/non-programmable pin (GND, VCC, etc.) */
export function isFixedPin(pin: PinConfig): boolean {
    return pin.gpio < 0 || pin.default_mode === 'fixed' ||
        (pin.reserved && !pin.capabilities?.input && !pin.capabilities?.output && !pin.capabilities?.adc && !pin.capabilities?.signal);
}
