# SignalForge (Akai MPK mini mkIV)

Turn your Akai MPK mini mkIV into a live instrument + soundboard that Discord
hears as a single microphone — alongside your real voice.

---

## 🚀 Install (quick start)

**1. Install the prerequisites**
- **Python 3.11 or 3.12** — https://www.python.org/downloads/
  ⚠️ During install, tick **"Add Python to PATH"**.
- **VB-Audio Virtual Cable** (free) — https://vb-audio.com/Cable/ → install → **reboot**.

**2. Get the code**
```bash
git clone https://github.com/MrRaaja/Signal-forge.git
cd Signal-forge
```
(Or download the ZIP from GitHub: **Code → Download ZIP**, then extract.)

**3. Run it**
- **Windows:** double-click **`run.bat`**. The first run auto-creates a virtual
  environment and installs dependencies (~2–4 min); every run after is instant.
- **Manual / other shells:**
  ```bash
  python -m venv .venv
  .venv\Scripts\activate        # Windows  (use: source .venv/bin/activate on macOS/Linux)
  pip install -r requirements.txt
  python main.py
  ```

**4. First-time setup in the app** — see [§3 First-time setup](#3-first-time-setup)
below: pick your MIDI keyboard, mic, headphones, and the VB-Cable output, then in
Discord set your input device to **"CABLE Output (VB-Audio Virtual Cable)"**.

> **Note:** there's also a **Casio CT-S300 edition** for keyboards without pads/knobs.
> It's the same app with a different `core/branding.py` (controller name + the
> pads/knobs panels collapsed by default).

You play keys → the app makes synth/piano sounds, plays them in your headphones,
mixes them with your microphone and your pad samples, and sends the combined
signal into a virtual audio cable. In Discord you pick that cable as your mic.

```
 MPK mini ──MIDI──► [ App: synth + pads + mic mixer ] ──► Headphones (you hear it)
   keys/pads/knobs                                    └──► CABLE Input ──► Discord mic
        ▲                                                     (VB-Audio Virtual Cable)
     your mic ───────────────────────────────────────┘
```

---

## 1. Stack comparison (why Python)

You asked for a recommendation before coding. Here's the honest trade-off for
*this* job: low-latency Windows audio + MIDI + a mixer UI + easy `.exe`.

| Stack | Latency / realtime | Audio routing | Dev speed | Packaging | Verdict |
|---|---|---|---|---|---|
| **Python** (PySide6 + sounddevice/PortAudio + mido/rtmidi + numpy) | Good. ~5–12 ms with WASAPI at 256 frames. The GIL is the main risk, mitigated by keeping the synth fully vectorised in numpy. | Excellent — PortAudio enumerates every WASAPI/MME/ASIO device and lets you open arbitrary inputs/outputs (incl. the virtual cable). | Fastest | Easy with PyInstaller | **Chosen for the MVP** |
| **C#/.NET + NAudio** | Best. Native, no GIL, WASAPI/ASIO exclusive mode, sample-accurate mixing. | Excellent (WASAPI/ASIO). | Slower, more boilerplate | Easy (`dotnet publish`) | Best if you hit a latency/glitch wall and want to go pro. |
| **Electron/Tauri** | Weakest for this. Web Audio can't freely route to an arbitrary OS output device like the cable; device selection and exclusive-mode latency are awkward. | Poor for this use case | Fast UI | Heavy | **Not recommended.** |

**Recommendation:** Python for the MVP. It matches a fast iteration loop, gives
full device routing, packages cleanly, and the latency is good enough — Discord
itself adds compression + network latency, so the mixer is not your bottleneck
for the Discord feed. The path that *does* matter for latency is **monitoring**
(hearing yourself), which is why the engine makes your monitor output the master
clock. If monitoring latency ever feels too high, the upgrade path is WASAPI
exclusive / ASIO, or porting the synth to C#/NAudio behind the same interface.

---

## 2. Architecture

Clean module separation (each file has a top-of-file docstring):

```
midi_discord_mixer/
├── main.py                     entry point
├── core/
│   ├── midi_input.py           MIDI device handling (mido + rtmidi callback)
│   ├── synth.py                vectorised polyphonic synth + ADSR
│   ├── soundboard.py           pad sample loading + playback (oneshot/hold/toggle)
│   ├── mixer.py                AudioEngine: ring buffers, mic capture, mixing, routing
│   └── settings.py             JSON persistence (%APPDATA%)
├── ui/
│   ├── main_window.py          window, wiring, MIDI routing, MIDI-learn
│   ├── keyboard_widget.py      painted keyboard w/ active-note highlight
│   ├── pads_widget.py          2×4 pad grid w/ flash feedback
│   ├── knobs_widget.py         8 knobs w/ learn + target dropdown
│   ├── mixer_widget.py         4 faders + mutes
│   ├── soundboard_widget.py    per-pad assign/clear/stop/mode/volume/note
│   └── styles.py               dark MPK-inspired theme
├── requirements.txt
├── build.bat                   one-click PyInstaller build
└── README.md
```

**Routing model (important):** up to three independent audio streams, each with
its own clock, bridged by ring buffers:

* **Master output** = your *monitor* (headphones). Its callback renders the
  synth + pads, mixes in the mic, applies the faders/mutes, and writes to your
  headphones — lowest latency where it matters most.
* **Secondary output** = the *virtual cable* (→ Discord), fed from a ring buffer.
  Discord tolerates a little extra latency/jitter far better than your ears do.
* **Mic input** fills a ring buffer the master callback reads from.

If you select only a cable (no monitor), the cable becomes the master.

---

## 3. First-time setup

### Step 1 — Install VB-Audio Virtual Cable (required, external)
Download from **https://vb-audio.com/Cable/** → run the installer → reboot.
This adds two Windows devices: **CABLE Input** (an output you send audio *to*)
and **CABLE Output** (an input Discord reads *from*).

### Step 2 — Run the app
From source:
```bat
pip install -r requirements.txt
python main.py
```
Or build the `.exe` (see §6) and run `MidiDiscordMixer.exe`.

### Step 3 — Choose devices in the app
In **Devices & routing**:
1. **MIDI input** → your *MPK mini mkIV* → click **Connect MIDI**.
2. **Microphone input** → your real mic (e.g. Focusrite/Scarlett).
3. **Monitor output** → your headphones / interface (so you hear yourself).
4. **Virtual output** → **CABLE Input (VB-Audio Virtual Cable)**.
5. Click **Start Audio**.

> Tip: prefer the device entries labelled **[Windows WASAPI]** for lowest latency.

### Step 4 — Configure Discord
Discord → *User Settings* → *Voice & Video* → **Input Device** = **CABLE Output
(VB-Audio Virtual Cable)**. Turn **off** Noise Suppression / Echo Cancellation /
Automatic Gain Control there (they mangle instrument audio). Use push-to-talk or
raise the input-sensitivity threshold.

You should now hear yourself + your playing in your headphones, and your Discord
friends hear the same mix.

---

## 4. Mapping pads & knobs (MPK mini mkIV)

The exact note numbers your pads send and the CC numbers your knobs send depend
on the controller's **active program/preset**, so the app does **not** hardcode
them. It ships with best-effort defaults and lets you correct them live:

* Watch the **MIDI debug log** at the bottom — every incoming message is shown.
* **Pads:** in the Soundboard panel click a pad's **`note --`** button, then hit
  the physical pad. The note is captured and saved.
* **Knobs:** click **Learn** under a knob, then turn the physical knob. The CC is
  captured. Set each knob's **target** dropdown (instrument / pad / mic / master).
  Defaults: K1→instrument, K2→pads, K3→mic, K4→master volume.

Anything you map is saved automatically.

---

## 5. Features → where they live

* **MIDI input + debug log** — `core/midi_input.py`, log panel in the UI.
* **Synth/piano engine** — `core/synth.py` (polyphonic, velocity, ADSR). SoundFont
  support can be added later behind the same `note_on/note_off/render` API.
* **Monitoring + per-channel volume/mute** — `mixer_widget.py` + `AudioEngine`.
* **Mic mixing → virtual output** — `AudioEngine` master callback.
* **Soundboard pads** — WAV/FLAC/OGG always; MP3 if your `libsndfile` build
  supports it (most recent ones do). Modes: one-shot / hold / toggle, per-pad
  volume, Stop, Clear, visual flash.
* **Knob mapping** — `knobs_widget.py` + learn logic in `main_window.py`.
* **Settings persistence** — `core/settings.py`, auto-saved to
  `%APPDATA%\MidiDiscordMixer\settings.json` and restored on launch.

---

## 6. Packaging to a standalone `.exe`

```bat
build.bat
```
This creates a virtual env, installs everything, and runs PyInstaller in
`--onedir --windowed` mode. Output: **`dist\MidiDiscordMixer\`** — copy the whole
folder to another PC and run `MidiDiscordMixer.exe`.

`--onedir` is recommended over `--onefile` for audio apps: faster startup and far
fewer DLL-bundling problems with PortAudio/rtmidi/libsndfile. The build script
already uses `--collect-all` for `sounddevice`, `soundfile`, and `rtmidi` so their
native DLLs are bundled.

> The target PC still needs **VB-Audio Virtual Cable** installed (it's a system
> audio driver and can't be bundled into the app).

---

## 7. Known limitations & honest caveats

* **Clock drift.** The mic-in, monitor-out and cable-out clocks aren't
  synchronised; ring buffers absorb the drift (silence on underrun, drop on
  overrun). Stable for long sessions, but not sample-accurate. True sync needs
  adaptive resampling — deliberately out of MVP scope.
* **GIL / glitches under load.** The synth is vectorised to keep the audio
  callback cheap, but very high polyphony + many overlapping pad hits on a slow
  CPU could cause occasional clicks. Raise the block size (e.g. 512) in
  `settings.json` if so — more latency, more stability.
* **WASAPI shared mode** is the pragmatic default. For the tightest monitoring
  latency, exclusive mode or ASIO is better but can lock the device so nothing
  else can use it. Not wired into the MVP UI.
* **MP3** depends on your `libsndfile` version. If an MP3 fails to load, convert
  it to WAV. WAV is the guaranteed format.
* **MPK mini mkIV mappings** vary by preset — use MIDI-learn + the log (see §4).
* This was written and unit-tested for its DSP/routing/persistence logic, but the
  live audio/MIDI paths need a real Windows machine with the hardware to verify
  end-to-end. Start audio with headphones at low volume the first time.

---

## 8. MVP acceptance checklist

| # | Criterion | Status |
|---|---|---|
| 1 | Open the app | ✅ `python main.py` / `.exe` |
| 2 | Select MPK mini mkIV | ✅ MIDI dropdown + Connect |
| 3 | Keys play synth/piano | ✅ `synth.py` |
| 4 | Hear notes in headphones | ✅ monitor output = master |
| 5 | Select main microphone | ✅ mic dropdown |
| 6 | Mix mic + MIDI | ✅ AudioEngine |
| 7 | Send mix to virtual cable | ✅ secondary output |
| 8 | Discord uses the cable | ✅ setup guide §3 |
| 9 | 8 pads trigger WAV samples | ✅ `soundboard.py` |
| 10 | UI shows keyboard/pads/knobs/mixer/routing | ✅ |
| 11 | Saves & restores settings | ✅ `settings.py` |
| 12 | Builds to a Windows `.exe` | ✅ `build.bat` |
