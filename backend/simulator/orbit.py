"""
AERO-ASTRA Physics Simulator — Orbit/Eclipse Clock

Simple repeating time-based cycle approximating a LEO orbit.
No external orbital-mechanics library required — pure arithmetic.

The clock is fully deterministic: the same simulation time t always
returns the same eclipse state. Random noise belongs in noise.py, not here.

Eclipse occupies the back portion of each orbit period. Sunlight factor
uses a cosine taper near the eclipse entry/exit boundaries to eliminate
step-function discontinuities that would otherwise cause abrupt jumps in
EPS solar current and TCS panel temperature.
"""

from __future__ import annotations

import math

# ─────────────────────────────────────────────────────────────────────────────
# Default orbit parameters (tunable at construction time)
# ─────────────────────────────────────────────────────────────────────────────

ORBIT_PERIOD_S: float = 5400.0   # ~90-minute LEO orbit
ECLIPSE_FRACTION: float = 0.35   # 35% of each orbit in eclipse (realistic LEO)
TAPER_FRACTION: float = 0.05     # 5% of orbit period used for cosine fade

# Ground contact: one window per orbit, 10 minutes
CONTACT_DURATION_S: float = 600.0


class OrbitClock:
    """
    Deterministic repeating eclipse/sunlight cycle for a LEO satellite.

    Primary consumers:
        - EPS transition: solar_array_current ∝ sunlight_factor
        - TCS transition: equilibrium panel temperature depends on eclipse state
        - TT&C transition: ground_contact_remaining counts down per pass
    """

    def __init__(
        self,
        period_s: float = ORBIT_PERIOD_S,
        eclipse_fraction: float = ECLIPSE_FRACTION,
        taper_fraction: float = TAPER_FRACTION,
        contact_duration_s: float = CONTACT_DURATION_S,
    ) -> None:
        self.period_s = period_s
        self.eclipse_fraction = eclipse_fraction
        self._sunlight_fraction = 1.0 - eclipse_fraction
        self._taper = taper_fraction
        self.contact_duration_s = contact_duration_s

    # ── Core timing ──────────────────────────────────────────────────────────

    def phase(self, t: float) -> float:
        """Normalized orbital phase in [0, 1) for simulation time t."""
        return (t % self.period_s) / self.period_s

    def is_in_eclipse(self, t: float) -> bool:
        """True if the satellite is in eclipse at simulation time t."""
        return self.phase(t) >= self._sunlight_fraction

    # ── Smooth solar illumination ─────────────────────────────────────────────

    def sunlight_factor(self, t: float) -> float:
        """
        Smooth solar illumination factor in [0, 1].
        1.0 = full sunlight; 0.0 = full eclipse.

        Uses a cosine taper (width = taper_fraction × period) near each
        eclipse boundary. This prevents step-function jumps in EPS/TCS
        while preserving the sharp day/night cycle character otherwise.
        """
        p = self.phase(t)
        sun_end = self._sunlight_fraction  # phase where eclipse begins
        taper = self._taper

        if p < sun_end:
            # ── In sunlight ──────────────────────────────────────────────────
            if p > sun_end - taper:
                # Approaching eclipse — cosine fade to 0
                frac = (sun_end - p) / taper
                return 0.5 * (1.0 - math.cos(math.pi * frac))
            return 1.0
        else:
            # ── In eclipse ───────────────────────────────────────────────────
            progress = p - sun_end
            if progress < taper:
                # Just entered eclipse — cosine fade from 1 to 0
                frac = progress / taper
                return 0.5 * (1.0 - math.cos(math.pi * (1.0 - frac)))
            remaining = self.eclipse_fraction - progress
            if remaining < taper and remaining >= 0:
                # About to exit eclipse — cosine fade from 0 to 1
                frac = remaining / taper
                return 0.5 * (1.0 - math.cos(math.pi * (1.0 - frac)))
            return 0.0

    # ── Ground contact window ─────────────────────────────────────────────────

    def ground_contact_remaining(self, t: float) -> float:
        """
        Seconds remaining in the current ground contact window.

        Contact window is modeled as occurring at the start of each orbit
        (phase 0 → contact_duration_s / period_s). This is a simplification
        of a real pass schedule but produces realistic countdown behavior.
        """
        p = self.phase(t)
        contact_phase = self.contact_duration_s / self.period_s
        if p < contact_phase:
            remaining_phase = contact_phase - p
            return remaining_phase * self.period_s
        return 0.0
