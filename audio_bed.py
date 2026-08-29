"""
audio_bed.py -- a small multi-channel audio manager for the ride experience.

The single music bed the audio tour first used ``pygame.mixer.music``, which
is ONE streaming channel: you cannot layer a second clip over it, and you cannot
fade two sounds independently. This module manages NAMED clips on the mixer's
multiple Sound channels so the experience can:

  * play several clips AT ONCE (layer) -- e.g. an ambient bed under a
    ghost-rider's voice line;
  * FADE each in / out independently (pygame's sample-accurate fades, not a
    hand-stepped volume ramp);
  * STOP any one clip smoothly (fade) or hard, without touching the others.

Design boundary (mirrors hud_reader / overlay): this only knows how to PLAY,
LAYER, FADE and STOP clips by name. It knows nothing about OCR, route position,
riders or timing -- a caller decides WHICH clip to play WHEN. Position-tied and
rider/bot-tied audio both reduce to "something reached a threshold -> play this
clip", so they share this one player.

Graceful degradation: with no audio device (headless CI, a locked-down box)
construction still succeeds with ``.available == False`` and every method is a
safe no-op -- exactly how the audio tour treats a missing mixer, so a silent
machine never crashes the ride.

Scope: ``pygame.mixer.Sound`` loads a whole clip into memory (unlike streaming
music), so this targets the SHORT clips this feature uses -- rider memories,
greetings, a ghost-rider's line. A long continuous soundtrack should stay on
``pygame.mixer.music``.
"""

try:
    import pygame
    PYGAME_AVAILABLE = True
except Exception:  # pragma: no cover - environment without pygame
    pygame = None
    PYGAME_AVAILABLE = False


def _clamp(v):
    return max(0.0, min(1.0, float(v)))


class AudioBed:
    """Play, layer, fade and stop short clips by a caller-chosen name (clip_id).

    Two notions of "playing" are deliberately distinct:
      * ``active_clips()`` -- clips the bed is MANAGING (started and not yet
        stopped or reaped). Stable the instant you call play()/stop().
      * ``is_playing(id)`` -- whether that clip is ACTUALLY producing sound
        right now (goes False the moment a fade-out completes, before update()
        reaps it).
    """

    def __init__(self, num_channels=16, *, init_mixer=True):
        self.available = False
        self._sounds = {}   # path -> Sound (each clip loaded from disk once)
        self._active = {}   # clip_id -> the Channel it's playing on
        if not PYGAME_AVAILABLE:
            return
        try:
            if init_mixer and not pygame.mixer.get_init():
                pygame.mixer.init()
            if pygame.mixer.get_init() is None:
                return
            pygame.mixer.set_num_channels(num_channels)
            self.available = True
        except Exception:  # pragma: no cover - no/locked audio device
            self.available = False

    # --- internals ---------------------------------------------------------
    def _load(self, path):
        snd = self._sounds.get(path)
        if snd is None:
            snd = pygame.mixer.Sound(path)
            self._sounds[path] = snd
        return snd

    def _free_channel(self):
        """A channel not currently assigned to a tracked clip and not busy.

        Picking an explicit free channel (rather than letting pygame auto-pick)
        keeps a NEW clip from stealing a channel we're still tracking for an
        existing one -- which is what makes layering reliable.
        """
        assigned = set(self._active.values())
        for i in range(pygame.mixer.get_num_channels()):
            ch = pygame.mixer.Channel(i)
            if ch not in assigned and not ch.get_busy():
                return ch
        return pygame.mixer.find_channel(force=True)  # all busy -> steal oldest

    # --- playback ----------------------------------------------------------
    def play(self, clip_id, path, *, loop=False, fade_ms=0, volume=1.0):
        """Start (or restart) a named clip on its own channel.

        Re-using an existing ``clip_id`` cleanly restarts that clip (no leak,
        no second channel). Returns True if it started playing.
        """
        if not self.available:
            return False
        try:
            snd = self._load(path)
        except Exception:
            return False
        self.stop(clip_id)                       # restart cleanly if re-used
        ch = self._free_channel()
        if ch is None:
            return False
        ch.set_volume(_clamp(volume))
        ch.play(snd, loops=-1 if loop else 0, fade_ms=int(fade_ms))
        self._active[clip_id] = ch
        return True

    def stop(self, clip_id, *, fade_ms=0):
        """Stop one clip -- smoothly if ``fade_ms`` > 0, else immediately.

        A faded stop leaves the clip tracked until the fade finishes; update()
        reaps it. A hard stop drops it from tracking at once.
        """
        if not self.available:
            return
        ch = self._active.get(clip_id)
        if ch is None:
            return
        if fade_ms > 0:
            ch.fadeout(int(fade_ms))             # reaped by update() when done
        else:
            ch.stop()
            del self._active[clip_id]

    def fade_out(self, clip_id, ms):
        """Readable alias for a smooth stop."""
        self.stop(clip_id, fade_ms=ms)

    def stop_all(self, *, fade_ms=0):
        for clip_id in list(self._active):
            self.stop(clip_id, fade_ms=fade_ms)

    def set_volume(self, clip_id, volume):
        if not self.available:
            return
        ch = self._active.get(clip_id)
        if ch is not None:
            ch.set_volume(_clamp(volume))

    # --- state -------------------------------------------------------------
    def get_volume(self, clip_id):
        if not self.available:
            return 0.0
        ch = self._active.get(clip_id)
        return ch.get_volume() if ch is not None else 0.0

    def is_playing(self, clip_id):
        if not self.available:
            return False
        ch = self._active.get(clip_id)
        return bool(ch is not None and ch.get_busy())

    def active_clips(self):
        """The clip_ids the bed is currently managing."""
        return set(self._active)

    def update(self):
        """Reap clips that finished on their own (or whose fade-out completed).

        Call once per loop tick. Cheap; safe to call when nothing is playing.
        """
        if not self.available:
            return
        for clip_id, ch in list(self._active.items()):
            if not ch.get_busy():
                del self._active[clip_id]

    def close(self):
        """Stop everything (does NOT quit the shared mixer)."""
        self.stop_all()
