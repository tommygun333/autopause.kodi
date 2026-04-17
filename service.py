"""
service.autopause — Kodi service addon
=======================================
Automatically pauses video playback for a configurable number of seconds
whenever a video starts (or an inputstream.adaptive stream changes), giving
a projector time to adjust to the new resolution, dynamic range, and refresh
rate before content actually plays.

Kodi 21 "Omega" / xbmc.python 3.0.0
"""

import json
import threading
import time

import xbmc
import xbmcaddon
import xbmcgui

ADDON = xbmcaddon.Addon()
ADDON_NAME = ADDON.getAddonInfo('name')

LOG_PREFIX = '[service.autopause]'


def _log(msg, level=xbmc.LOGINFO):
    """Write a prefixed message to the Kodi log."""
    xbmc.log(f'{LOG_PREFIX} {msg}', level)


class AutoPausePlayer(xbmc.Player):
    """
    Kodi Player subclass that intercepts AV events and triggers the
    auto-pause sequence.

    Lifecycle
    ---------
    onAVStarted     → always pause (fresh video start)
    onAVChange      → pause only for adaptive streams (recap → main content)
    onPlayBack*     → reset internal state
    """

    # Extensions and keywords that identify an inputstream.adaptive stream.
    ADAPTIVE_EXTENSIONS = ('.mpd', '.m3u8', '.ism', '.isml', '.cmaf')
    ADAPTIVE_KEYWORDS = ('manifest', '.mpd', 'playlist.m3u8')

    def __init__(self):
        super().__init__()
        self._lock = threading.Lock()
        # Timestamp of the last completed pause; 0 means "never" (always pause).
        self._last_pause_time = 0.0
        # True while a pause sequence is in progress.
        self._pausing = False

    # ------------------------------------------------------------------
    # Kodi callback overrides
    # ------------------------------------------------------------------

    def onAVStarted(self):
        """
        Called by Kodi when audio/video data starts flowing.  More reliable
        than onPlayBackStarted because it fires after buffering completes.
        A fresh video start always bypasses the minimum-interval guard.
        """
        _log('onAVStarted fired', xbmc.LOGDEBUG)
        with self._lock:
            # Reset the guard so the interval check is always skipped for a
            # brand-new video, regardless of how recently a previous pause ran.
            self._last_pause_time = 0.0
        self._trigger_pause(source='new_video')

    def onAVChange(self):
        """
        Called by Kodi when the active AV stream changes (e.g. recap → main
        content for inputstream.adaptive titles).  Only acts when the current
        stream looks adaptive and the minimum interval has elapsed.
        """
        _log('onAVChange fired', xbmc.LOGDEBUG)
        if not ADDON.getSettingBool('handle_av_change'):
            return
        if self._is_adaptive_stream():
            _log('Adaptive stream detected on AV change', xbmc.LOGDEBUG)
            self._trigger_pause(source='stream_change')

    def onPlayBackStopped(self):
        """Reset state when playback is stopped by the user."""
        _log('Playback stopped — resetting state', xbmc.LOGDEBUG)
        self._reset()

    def onPlayBackEnded(self):
        """Reset state when playback reaches the end of the file."""
        _log('Playback ended — resetting state', xbmc.LOGDEBUG)
        self._reset()

    def onPlayBackError(self):
        """Reset state on a playback error."""
        _log('Playback error — resetting state', xbmc.LOGDEBUG)
        self._reset()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _reset(self):
        """Clear pause-tracking state under the lock."""
        with self._lock:
            self._last_pause_time = 0.0
            self._pausing = False

    def _is_adaptive_stream(self):
        """
        Heuristically determine whether the currently playing item is served
        by inputstream.adaptive.

        Strategy
        --------
        1. Ask Kodi for the current filename/path via an infolabel (fast, no
           RPC round-trip).
        2. Fall back to a JSON-RPC Player.GetItem call if the infolabel is
           empty (e.g. some addon streams hide the path from infolabels).
        3. Check the path for known adaptive file extensions and keywords.

        Returns True if the stream appears to be adaptive, False otherwise.
        """
        path = xbmc.getInfoLabel('Player.FilenameAndPath').lower()

        if not path:
            # Fallback: JSON-RPC
            try:
                response = xbmc.executeJSONRPC(json.dumps({
                    'jsonrpc': '2.0',
                    'method': 'Player.GetItem',
                    'params': {'playerid': 1, 'properties': ['file']},
                    'id': 1,
                }))
                data = json.loads(response)
                path = data.get('result', {}).get('item', {}).get('file', '').lower()
            except Exception as exc:  # noqa: BLE001
                _log(f'JSON-RPC fallback failed: {exc}', xbmc.LOGWARNING)

        if not path:
            return False

        for ext in self.ADAPTIVE_EXTENSIONS:
            if path.endswith(ext):
                return True
        for kw in self.ADAPTIVE_KEYWORDS:
            if kw in path:
                return True
        return False

    def _trigger_pause(self, source):
        """
        Spawn a daemon background thread to run the pause sequence so that
        the Kodi callback returns immediately.

        Parameters
        ----------
        source : str
            ``'new_video'`` or ``'stream_change'`` — passed to the sequence
            so the interval guard can distinguish fresh starts from changes.
        """
        thread = threading.Thread(
            target=self._pause_sequence,
            args=(source,),
            daemon=True,
        )
        thread.start()

    def _pause_sequence(self, source):
        """
        Gate-keeper that enforces mutual exclusion and the minimum-interval
        guard before delegating to :meth:`_do_pause`.

        Parameters
        ----------
        source : str
            ``'new_video'`` skips the interval check; ``'stream_change'``
            respects it.
        """
        with self._lock:
            now = time.monotonic()
            min_interval = ADDON.getSettingInt('min_interval')

            if source != 'new_video':
                elapsed = now - self._last_pause_time
                if self._last_pause_time > 0 and elapsed < min_interval:
                    _log(
                        f'Skipping pause ({source}): only {elapsed:.1f}s since last pause '
                        f'(min {min_interval}s)',
                        xbmc.LOGDEBUG,
                    )
                    return

            if self._pausing:
                _log('Skipping pause: already pausing', xbmc.LOGDEBUG)
                return

            self._pausing = True
            self._last_pause_time = now

        try:
            self._do_pause(source)
        finally:
            with self._lock:
                self._pausing = False

    def _do_pause(self, source):
        """
        Perform the actual pause → wait → resume sequence.

        Steps
        -----
        1. Sleep 150 ms so the player has settled after the AV event.
        2. Verify that video is still playing; bail out silently if not.
        3. Pause playback.
        4. Show the countdown progress dialog (or just sleep).
        5. Resume if Kodi is still in the paused state when the timer expires.

        Parameters
        ----------
        source : str
            Used for log messages only.
        """
        pause_seconds = ADDON.getSettingInt('pause_seconds')
        _log(f'Starting pause sequence ({source}), duration={pause_seconds}s')

        # Let the player settle.
        time.sleep(0.15)

        if not self.isPlayingVideo():
            _log('No video playing — aborting pause sequence', xbmc.LOGDEBUG)
            return

        _log('Pausing playback')
        self.pause()

        if ADDON.getSettingBool('show_progress'):
            self._show_progress_and_wait(pause_seconds)
        else:
            xbmc.sleep(pause_seconds * 1000)

        # Only resume if Kodi is still paused (user may have manually resumed).
        if self.isPlayingVideo() and self.isPlaying():
            # isPlaying() returns True for both playing and paused; check
            # the paused state via the info label.
            if xbmc.getCondVisibility('Player.Paused'):
                _log('Resuming playback')
                self.pause()
            else:
                _log('Player is no longer paused — not sending resume', xbmc.LOGDEBUG)
        else:
            _log('Video stopped during wait — not sending resume', xbmc.LOGDEBUG)

    def _show_progress_and_wait(self, pause_seconds):
        """
        Display a background progress dialog counting down to resume.

        The bar updates every 100 ms so the countdown feels smooth.  The
        dialog is always closed in the ``finally`` block to avoid a stale
        overlay if an exception occurs.

        Parameters
        ----------
        pause_seconds : int
            Total number of seconds to wait before resuming.
        """
        dialog = xbmcgui.DialogProgressBG()
        dialog.create(ADDON_NAME, f'Resuming in {pause_seconds}s\u2026')
        try:
            total_steps = pause_seconds * 10  # one step per 100 ms
            for step in range(total_steps):
                remaining = pause_seconds - (step // 10)
                percent = int((step / total_steps) * 100)
                dialog.update(percent, message=f'Resuming in {remaining}s\u2026')
                xbmc.sleep(100)
            dialog.update(100, message='Resuming\u2026')
        finally:
            dialog.close()


class AutoPauseService(xbmc.Monitor):
    """
    Kodi Monitor subclass used as the service entry point.

    Keeps the addon alive via ``waitForAbort`` so that the
    :class:`AutoPausePlayer` instance remains registered for the full Kodi
    session.
    """

    def __init__(self):
        super().__init__()

    def run(self):
        """Start the player listener and block until Kodi shuts down."""
        _log('Service starting')
        player = AutoPausePlayer()  # noqa: F841 — must be kept alive

        while not self.abortRequested():
            self.waitForAbort(1)

        _log('Service stopping')


if __name__ == '__main__':
    AutoPauseService().run()
