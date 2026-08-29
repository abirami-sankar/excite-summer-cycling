"""
overlay.py -- transparent, click-through, always-on-top overlay for Rouvy.

A passive HUD layer drawn ON TOP of the Rouvy window: text prompts, virtual
signs, and status messages for the ride experience (companion prompts, landmark
signs, artifact-discovery cards). It is DISPLAY-ONLY and fully click-through --
every mouse/keyboard event passes through to Rouvy, so the overlay can never
disrupt the ride.

Windows-specific (uses tkinter's `-transparentcolor` colorkey plus the Win32
`WS_EX_TRANSPARENT` extended style via ctypes), which is where the capture
pipeline runs anyway. Zero extra dependencies -- tkinter and ctypes are stdlib.

Positioning: the overlay is pinned to a monitor REGION (`left, top, width,
height`) -- the same region dict `live_source` uses -- so it lines up with the
Rouvy monitor. As with screen capture, Rouvy must run windowed/borderless (NOT
exclusive fullscreen) for anything to sit on top of it.

Design boundary (mirrors hud_reader): this module only knows how to DRAW on a
region. It knows nothing about the ride, OCR, or timing -- a caller decides what
to show and when (see demo_overlay.py) -- so the same overlay is reusable
whether driven by a script, the live OCR position stream, or the artifacts POC.

Why solid boxes (not text straight onto the transparent color): tkinter's
`-transparentcolor` is an all-or-nothing colorkey, so anti-aliased text drawn
directly on the key color leaves faint colored halos. Drawing each prompt/sign
as a SOLID filled rectangle with text on top avoids that and reads like a clean
sign floating over the ride. (Per-pixel/semi-transparent signs would need a
different toolkit, e.g. PyQt -- out of scope for this prototype.)
"""

import sys
import tkinter as tk
from tkinter import font as tkfont

# A color the ride content is unlikely to need; every pixel of EXACTLY this
# color becomes fully transparent + click-through. Kept off pure black/white so
# it doesn't collide with common UI colors.
TRANSPARENT_KEY = "#0b0b0c"

# Win32 extended-style bits for a layered, input-transparent (click-through)
# window, so ALL pixels pass input through -- not just the transparent ones.
_GWL_EXSTYLE = -20
_WS_EX_LAYERED = 0x00080000
_WS_EX_TRANSPARENT = 0x00000020
_WS_EX_TOOLWINDOW = 0x00000080  # keep the overlay off the taskbar / alt-tab


def _make_click_through(root):
    """Make the whole window pass mouse/keyboard through to whatever's beneath.

    We OR the click-through bits onto the EXISTING extended style (rather than
    replacing it) so tkinter's own layered + colorkey setup for
    `-transparentcolor` is preserved. Windows-only; a no-op elsewhere.
    """
    if sys.platform != "win32":
        return
    import ctypes
    hwnd = root.winfo_id()
    # tkinter's colorkey lives on the top-level frame, which is the PARENT of
    # the widget hwnd; fall back to the widget itself if there's no parent.
    parent = ctypes.windll.user32.GetParent(hwnd)
    target = parent or hwnd
    styles = ctypes.windll.user32.GetWindowLongW(target, _GWL_EXSTYLE)
    styles |= _WS_EX_LAYERED | _WS_EX_TRANSPARENT | _WS_EX_TOOLWINDOW
    ctypes.windll.user32.SetWindowLongW(target, _GWL_EXSTYLE, styles)


class RideOverlay:
    """A transparent, click-through overlay pinned to a monitor region.

    Element kinds:
      * status  -- a small persistent chip (top-left); set_status() replaces it.
      * banner  -- a wide prompt strip across the upper-center (companion voice
                   captions, "landmark ahead", artifact cards).
      * sign    -- a virtual road sign placed at a fractional (x, y) position.
    Banners and signs are "transient": clear_transient() wipes them; the status
    chip persists until replaced.
    """

    def __init__(self, region, transparent_key=TRANSPARENT_KEY):
        self.region = region
        self.key = transparent_key

        self.root = tk.Tk()
        self.root.overrideredirect(True)                      # borderless
        self.root.attributes("-topmost", True)                # always on top
        self.root.attributes("-transparentcolor", self.key)   # see-through bg
        self.root.geometry(
            f"{region['width']}x{region['height']}+{region['left']}+{region['top']}")

        self.canvas = tk.Canvas(self.root, highlightthickness=0, bd=0,
                                bg=self.key,
                                width=region["width"], height=region["height"])
        self.canvas.pack(fill="both", expand=True)

        self.root.update_idletasks()
        _make_click_through(self.root)

        self._transient = []   # canvas ids for prompts/signs
        self._status = []      # canvas ids for the persistent status chip
        self._bubble = []      # canvas ids for a speech bubble (own lifetime)
        self._alive = True
        self._keep_top()

    # --- window management -------------------------------------------------
    def _keep_top(self):
        # Re-assert topmost + pinned geometry periodically: if Rouvy raises
        # itself the overlay would otherwise slip behind, and this also keeps
        # the position correct if anything nudged it.
        if not self._alive:
            return
        self.root.attributes("-topmost", True)
        self.root.geometry(
            f"{self.region['width']}x{self.region['height']}"
            f"+{self.region['left']}+{self.region['top']}")
        self.root.after(1000, self._keep_top)

    # --- drawing helpers ---------------------------------------------------
    def _draw_box(self, cx, cy, text, *, fill, fg, size, pad, store, anchor_nw=None):
        f = tkfont.Font(family="Segoe UI", size=size, weight="bold")
        tw, th = f.measure(text), f.metrics("linespace")
        if anchor_nw is not None:
            x, y = anchor_nw
            rid = self.canvas.create_rectangle(
                x, y, x + tw + 2 * pad, y + th + 2 * pad, fill=fill, outline="")
            tid = self.canvas.create_text(
                x + pad, y + pad, text=text, fill=fg, font=f, anchor="nw")
        else:
            rid = self.canvas.create_rectangle(
                cx - tw / 2 - pad, cy - th / 2 - pad,
                cx + tw / 2 + pad, cy + th / 2 + pad, fill=fill, outline="")
            tid = self.canvas.create_text(cx, cy, text=text, fill=fg, font=f)
        store.extend([rid, tid])
        return rid, tid

    def show_banner(self, text, *, fill="#111827", fg="#ffffff", size=34):
        """A wide prompt strip across the upper-center."""
        self._draw_box(self.region["width"] / 2, self.region["height"] * 0.16,
                       text, fill=fill, fg=fg, size=size, pad=26,
                       store=self._transient)

    def show_sign(self, text, x_frac=0.5, y_frac=0.5, *,
                  fill="#1d4ed8", fg="#ffffff", size=26):
        """A virtual road sign at a fractional position on the monitor."""
        self._draw_box(self.region["width"] * x_frac,
                       self.region["height"] * y_frac, text,
                       fill=fill, fg=fg, size=size, pad=18, store=self._transient)

    def set_status(self, text, *, fill="#065f46", fg="#d1fae5", size=16):
        """A small persistent status chip on the LEFT EDGE, vertically centred
        (kept clear of Rouvy's top-left rider panel); replaces the old one."""
        for i in self._status:
            self.canvas.delete(i)
        self._status = []
        self._draw_box(0, 0, text, fill=fill, fg=fg, size=size, pad=10,
                       store=self._status,
                       anchor_nw=(24, int(self.region["height"] * 0.5) - 20))

    def clear_status(self):
        """Remove the status chip entirely (e.g. on Rouvy's main screen)."""
        for i in self._status:
            self.canvas.delete(i)
        self._status = []

    def clear_transient(self):
        """Remove all banners/signs (leaves the status chip AND bubble in place)."""
        for i in self._transient:
            self.canvas.delete(i)
        self._transient = []

    def show_speech_bubble(self, text, x, y, *, max_width=340, fill="#1e293b",
                           fg="#ffffff", size=17, tail="left"):
        """A wrapped speech bubble with a tail, e.g. next to the rider panel.

        Kept in its OWN element list (not `_transient`) so it survives the
        ambient banner/sign cycling and lives for exactly as long as the
        caller wants (call clear_bubble() when its hold time is up).
        """
        self.clear_bubble()
        f = tkfont.Font(family="Segoe UI", size=size)
        pad = 14
        # text first (auto-wrapped to max_width), then size the box to its bbox
        tid = self.canvas.create_text(x + pad, y + pad, text=text, width=max_width,
                                      anchor="nw", fill=fg, font=f, justify="left")
        bx1, by1, bx2, by2 = self.canvas.bbox(tid)
        rid = self.canvas.create_rectangle(bx1 - pad, by1 - pad, bx2 + pad, by2 + pad,
                                           fill=fill, outline="")
        self.canvas.tag_lower(rid, tid)
        self._bubble = [rid, tid]
        if tail == "left":
            ty = (by1 + by2) / 2
            tri = self.canvas.create_polygon(bx1 - pad, ty - 12, bx1 - pad, ty + 12,
                                             bx1 - pad - 20, ty, fill=fill, outline="")
            self.canvas.tag_lower(tri, tid)
            self._bubble.append(tri)

    def clear_bubble(self):
        for i in self._bubble:
            self.canvas.delete(i)
        self._bubble = []

    # --- lifecycle ---------------------------------------------------------
    def update(self):
        """Pump one round of GUI events -- call this from an external loop
        (e.g. alongside the OCR read loop) instead of run()."""
        if self._alive:
            self.root.update_idletasks()
            self.root.update()

    def run(self):
        """Block on tkinter's own event loop (for a self-driving demo)."""
        self.root.mainloop()

    def close(self):
        self._alive = False
        try:
            self.root.destroy()
        except tk.TclError:
            pass
