"""
branding.py
-----------
Single place that defines the app name and the target controller. Different
builds (e.g. the Casio CT-S300 edition) only need to change the values here.
"""

from __future__ import annotations

APP_NAME = "SignalForge"
# The MIDI controller this build is tuned for (shown in the window title).
CONTROLLER_NAME = "Akai MPK mini mkIV"
# Big header text in the main window.
TAGLINE = "SIGNALFORGE"

# Whether this controller has physical pads + knobs (MPK does; many keyboards
# like the Casio CT-S300 do not). When False, those panels start collapsed.
HAS_PADS_KNOBS = True

# Previous config-folder name to migrate settings from (keeps old users' setup).
LEGACY_APP_DIR_NAME = "MidiDiscordMixer"
