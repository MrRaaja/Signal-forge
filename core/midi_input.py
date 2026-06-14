"""
midi_input.py
-------------
MIDI input handling via `mido` with the `python-rtmidi` backend.

The Akai MPK mini mkIV sends:
  * keyboard keys  -> Note On / Note Off
  * drum pads      -> Note On / Note Off (on note numbers that depend on the
                      active program/preset)
  * knobs          -> Control Change (CC)

We do NOT hardcode which note is a pad or which CC is a knob -- the exact
numbers depend on the controller's current preset. Instead we forward every
message to the app, which decides routing using the (editable, learnable) maps
in settings, and logs everything to the debug panel so you can see real values.

Callbacks are invoked on rtmidi's background thread. Anything touching Qt must
be marshalled to the GUI thread by the caller (we do that with Qt signals).
"""

from __future__ import annotations

from typing import Callable

try:
    import mido
    mido.set_backend("mido.backends.rtmidi")
except Exception:  # pragma: no cover
    mido = None


class MidiInput:
    def __init__(self):
        self._port = None
        self.on_note_on: Callable[[int, int], None] | None = None   # (note, vel)
        self.on_note_off: Callable[[int], None] | None = None        # (note)
        self.on_cc: Callable[[int, int], None] | None = None         # (cc, value)
        self.on_pitch: Callable[[int], None] | None = None           # (-8192..8191)
        self.on_message: Callable[[str], None] | None = None         # raw log line

    @staticmethod
    def available() -> bool:
        return mido is not None

    @staticmethod
    def list_inputs() -> list[str]:
        if mido is None:
            return []
        try:
            return list(mido.get_input_names())
        except Exception:
            return []

    @property
    def is_open(self) -> bool:
        return self._port is not None

    def open(self, name: str) -> None:
        """Open input port `name`. Raises RuntimeError on failure."""
        if mido is None:
            raise RuntimeError("mido / python-rtmidi is not installed.")
        self.close()
        try:
            self._port = mido.open_input(name, callback=self._dispatch)
        except Exception as e:
            raise RuntimeError(f"Could not open MIDI device '{name}': {e}") from e

    def close(self) -> None:
        if self._port is not None:
            try:
                self._port.close()
            except Exception:
                pass
            self._port = None

    # --------------------------------------------------------------- dispatch
    def _dispatch(self, msg) -> None:
        try:
            if self.on_message:
                self.on_message(str(msg))
            if msg.type == "note_on":
                if msg.velocity > 0:
                    if self.on_note_on:
                        self.on_note_on(msg.note, msg.velocity)
                else:  # note_on with velocity 0 == note_off
                    if self.on_note_off:
                        self.on_note_off(msg.note)
            elif msg.type == "note_off":
                if self.on_note_off:
                    self.on_note_off(msg.note)
            elif msg.type == "control_change":
                if self.on_cc:
                    self.on_cc(msg.control, msg.value)
            elif msg.type == "pitchwheel":
                if self.on_pitch:
                    self.on_pitch(msg.pitch)
        except Exception:
            # Never let an exception escape into the rtmidi thread.
            pass
