# AutoPause — Kodi Service Addon

**AutoPause** is a Kodi service addon that automatically pauses video playback for a configurable number of seconds whenever a video starts. Its primary purpose is to give a projector time to adjust to a new resolution, dynamic range (HDR/SDR), and refresh rate before the content actually plays.

---

## What It Does and Why

Modern projectors (and some TVs) take a few seconds to switch display modes when they receive a new signal. Without a pause, the opening frames of a movie or show are lost during the black-screen or "searching for signal" period. AutoPause solves this by:

1. Detecting that a video has started (`onAVStarted`).
2. Immediately pausing playback.
3. Showing a countdown progress bar (*"Resuming in 4s…"*).
4. Automatically resuming once the configured time has elapsed.

---

## Kodi Compatibility

**Kodi 21 "Omega"** (`xbmc.python 3.0.0`). The addon uses only stable APIs available in Omega and later.

---

## Installation

### Manual (ZIP)
1. Download or clone this repository and zip the folder, **or** download the release ZIP.
2. In Kodi, go to **Add-ons → Install from ZIP file** and select the ZIP.
3. Kodi will install the addon and start it automatically.

### Repository
If a Kodi repository hosts this addon, you can install it via **Add-ons → Install from repository**.

---

## Settings

Open **Add-ons → AutoPause → Configure** (or Settings → Add-ons → AutoPause) to adjust:

| Setting | Default | Description |
|---------|---------|-------------|
| **Pause duration (seconds)** | `5` | How long to pause playback after a video starts. Range: 1–60 s. |
| **Min interval between pauses (seconds)** | `10` | Minimum time that must elapse between two consecutive pauses triggered by stream changes. Prevents spurious re-pauses from audio-track switches. Range: 5–300 s. |
| **Pause on stream change (inputstream.adaptive)** | Enabled | Whether to also pause when an adaptive stream changes internally (e.g. recap → main content). |
| **Show countdown progress** | Enabled | Display a background progress bar counting down to resume. |

---

## How inputstream.adaptive Recap Detection Works

Some streaming addons (e.g. Netflix, Disney+, Amazon Prime via Kodi addons) deliver a **recap or pre-roll clip** as a separate adaptive stream before the main content stream. When the recap ends and the main stream begins, Kodi fires `onAVChange`.

AutoPause intercepts `onAVChange` and checks whether the current playback looks like an adaptive stream by inspecting the file path for known extensions and keywords:

- Extensions: `.mpd`, `.m3u8`, `.ism`, `.isml`, `.cmaf`
- Keywords: `manifest`, `playlist.m3u8`

If an adaptive stream is detected **and** the minimum interval since the last pause has elapsed, the same pause-and-resume sequence runs again so your projector can re-adjust for the main content (which may have a different resolution or frame rate than the recap).

### Minimum-interval guard

The guard prevents the addon from pausing repeatedly if `onAVChange` fires many times in quick succession (e.g. when switching audio tracks or subtitles). A fresh video start (`onAVStarted`) always resets the guard, ensuring the very first pause always happens regardless of timing.

---

## File Structure

```
service.autopause/
├── addon.xml
├── service.py
├── changelog.txt
├── README.md
└── resources/
    ├── settings.xml
    └── language/
        └── resource.language.en_gb/
            └── strings.po
```

---

## License

GPL-2.0-only — see [LICENSE](https://www.gnu.org/licenses/old-licenses/gpl-2.0.html).
