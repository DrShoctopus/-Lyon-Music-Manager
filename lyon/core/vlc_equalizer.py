"""Shared libVLC equalizer fade controller."""
from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

from .equalizer import EQ_BAND_COUNT, normalize_equalizer_bands

LOG = logging.getLogger(__name__)

EQ_FADE_STEPS = 16
EQ_FADE_INTERVAL_MS = 16


class VlcEqualizerController:
    """Owns libVLC equalizer state and smooth gain transitions."""

    def __init__(
        self,
        vlc_module: Any,
        player: Any,
        band_indexes: Sequence[int] | None = None,
        *,
        context: str = "VLC equalizer",
    ) -> None:
        self._vlc = vlc_module
        self._player = player
        self._band_indexes = tuple(band_indexes or range(EQ_BAND_COUNT))
        self._context = context
        self._equalizer: Any = None
        self._live_bands: list[float] = [0.0] * EQ_BAND_COUNT
        self._live_preamp: float = 0.0
        self._fade_start_bands: list[float] = [0.0] * EQ_BAND_COUNT
        self._fade_start_preamp: float = 0.0
        self._fade_target_bands: list[float] = [0.0] * EQ_BAND_COUNT
        self._fade_target_preamp: float = 0.0
        self._remove_after_fade: bool = False
        self._fade_steps_left: int = 0

    @property
    def equalizer(self) -> Any:
        return self._equalizer

    def attach_to_player(self) -> None:
        """Reapply the active equalizer after a media/player output change."""
        if self._equalizer is None:
            return
        try:
            self._player.set_equalizer(self._equalizer)
        except (AttributeError, OSError, RuntimeError) as exc:
            LOG.debug("Could not reapply %s: %s", self._context, exc)

    def apply(self, enabled: bool, bands: list[int], preamp: int = 0) -> bool:
        """Configure targets. Return True when the caller should start its timer."""
        if not enabled:
            if self._equalizer is None:
                return False
            self._fade_start_bands = list(self._live_bands)
            self._fade_start_preamp = self._live_preamp
            self._fade_target_bands = [0.0] * EQ_BAND_COUNT
            self._fade_target_preamp = 0.0
            self._remove_after_fade = True
            self._fade_steps_left = EQ_FADE_STEPS
            return True

        try:
            normalized = [float(b) for b in normalize_equalizer_bands(bands)]
            try:
                target_preamp = float(preamp)
            except (TypeError, ValueError):
                target_preamp = 0.0
            if self._equalizer is None:
                eq = self._vlc.AudioEqualizer()
                if eq is None:
                    raise RuntimeError("VLC did not create an AudioEqualizer instance")
                eq.set_preamp(0.0)
                for vlc_index in self._band_indexes:
                    eq.set_amp_at_index(0.0, vlc_index)
                self._player.set_equalizer(eq)
                self._equalizer = eq
                self._live_bands = [0.0] * EQ_BAND_COUNT
                self._live_preamp = 0.0

            self._fade_start_bands = list(self._live_bands)
            self._fade_start_preamp = self._live_preamp
            self._fade_target_bands = normalized
            self._fade_target_preamp = target_preamp
            self._remove_after_fade = False
            if (
                self._fade_start_bands == self._fade_target_bands
                and self._fade_start_preamp == self._fade_target_preamp
            ):
                return False
            self._fade_steps_left = EQ_FADE_STEPS
            return True
        except (AttributeError, OSError, RuntimeError) as exc:
            self.clear()
            LOG.warning("Could not apply %s; continuing with flat playback: %s", self._context, exc)
            return False

    def fade_step(self) -> bool:
        """Apply one fade tick. Return True while more ticks remain."""
        if self._equalizer is None:
            return False

        self._fade_steps_left -= 1
        t = 1.0 - self._fade_steps_left / EQ_FADE_STEPS
        try:
            new_preamp = (
                self._fade_start_preamp
                + (self._fade_target_preamp - self._fade_start_preamp) * t
            )
            new_bands = [
                self._fade_start_bands[i]
                + (self._fade_target_bands[i] - self._fade_start_bands[i]) * t
                for i in range(EQ_BAND_COUNT)
            ]
            self._equalizer.set_preamp(new_preamp)
            for i, gain in enumerate(new_bands):
                self._equalizer.set_amp_at_index(gain, self._band_indexes[i])
            self._player.set_equalizer(self._equalizer)
            self._live_preamp = new_preamp
            self._live_bands = new_bands
        except (AttributeError, OSError, RuntimeError) as exc:
            LOG.warning("%s fade step failed: %s", self._context, exc)
            return False

        if self._fade_steps_left > 0:
            return True
        if self._remove_after_fade:
            self.clear()
        return False

    def clear(self) -> None:
        try:
            self._player.set_equalizer(None)
        except (AttributeError, OSError, RuntimeError) as exc:
            LOG.debug("Could not clear %s: %s", self._context, exc)
        self._equalizer = None
        self._live_bands = [0.0] * EQ_BAND_COUNT
        self._live_preamp = 0.0
