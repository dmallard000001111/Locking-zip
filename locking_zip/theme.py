"""A single deliberate dark theme for the whole app -- no OS-default colors
leaking through, which is what caused the original low-contrast look (plain
tk widgets picking up whatever black-on-white or white-on-white the host OS
felt like handing back). Every color used anywhere in gui.py comes from
PALETTE; nothing is hardcoded inline.
"""
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

PALETTE = {
    "bg": "#0f1117",
    "surface": "#171a23",
    "surface_hover": "#1f2333",
    "border": "#2a2f3d",
    "border_hover": "#7c5cff",
    "entry_bg": "#1c202c",
    "text": "#eef0f6",
    "text_muted": "#9298ab",
    "accent": "#7c5cff",
    "accent_hover": "#9177ff",
    "accent_pressed": "#6647e0",
    "accent_disabled": "#413a63",
    "success": "#2dd4bf",
    "error": "#ff6b81",
}

_PREFERRED_FAMILIES = ["SF Pro Text", "Segoe UI", "Helvetica Neue", "Helvetica", "Arial"]


def resolve_font_family(root: tk.Misc) -> str:
    available = set(tkfont.families(root))
    for name in _PREFERRED_FAMILIES:
        if name in available:
            return name
    return "TkDefaultFont"


def apply_theme(root: tk.Tk) -> dict:
    """Configure ttk styles + root window colors. Returns PALETTE for callers
    that need to color plain (non-ttk) widgets directly."""
    p = PALETTE
    family = resolve_font_family(root)

    root.configure(bg=p["bg"])

    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    style.configure(".", background=p["bg"], foreground=p["text"], font=(family, 11))

    style.configure("TFrame", background=p["bg"])
    style.configure("Card.TFrame", background=p["surface"])

    style.configure("TLabel", background=p["bg"], foreground=p["text"])
    style.configure("Card.TLabel", background=p["surface"], foreground=p["text"])
    style.configure("Muted.TLabel", background=p["bg"], foreground=p["text_muted"])
    style.configure("CardMuted.TLabel", background=p["surface"], foreground=p["text_muted"])
    style.configure(
        "Title.TLabel", background=p["bg"], foreground=p["text"], font=(family, 18, "bold")
    )
    style.configure(
        "Link.TLabel", background=p["surface"], foreground=p["accent"], font=(family, 10, "underline")
    )
    style.map("Link.TLabel", foreground=[("active", p["accent_hover"])])
    style.configure("Error.TLabel", background=p["bg"], foreground=p["error"])
    style.configure("CardError.TLabel", background=p["surface"], foreground=p["error"])
    style.configure("Success.TLabel", background=p["surface"], foreground=p["success"])

    style.configure(
        "Accent.TButton",
        background=p["accent"],
        foreground="#ffffff",
        borderwidth=0,
        focusthickness=0,
        padding=(16, 9),
        font=(family, 11, "bold"),
    )
    style.map(
        "Accent.TButton",
        background=[
            ("disabled", p["accent_disabled"]),
            ("pressed", p["accent_pressed"]),
            ("active", p["accent_hover"]),
        ],
        foreground=[("disabled", p["text_muted"])],
    )

    style.configure(
        "Secondary.TButton",
        background=p["surface"],
        foreground=p["text"],
        borderwidth=1,
        bordercolor=p["border"],
        focusthickness=0,
        padding=(14, 8),
        font=(family, 11),
    )
    style.map(
        "Secondary.TButton",
        background=[("disabled", p["bg"]), ("pressed", p["bg"]), ("active", p["surface_hover"])],
        foreground=[("disabled", p["text_muted"])],
        bordercolor=[("disabled", p["border"])],
    )

    style.configure(
        "TEntry",
        fieldbackground=p["entry_bg"],
        foreground=p["text"],
        insertcolor=p["text"],
        bordercolor=p["border"],
        lightcolor=p["border"],
        darkcolor=p["border"],
        padding=6,
    )
    style.map(
        "TEntry",
        bordercolor=[("focus", p["accent"])],
        lightcolor=[("focus", p["accent"])],
        darkcolor=[("focus", p["accent"])],
    )

    style.configure(
        "TCheckbutton",
        background=p["bg"],
        foreground=p["text"],
        font=(family, 10),
    )
    style.map("TCheckbutton", background=[("active", p["bg"])])

    style.configure(
        "TRadiobutton",
        background=p["bg"],
        foreground=p["text"],
        font=(family, 10),
    )
    style.map("TRadiobutton", background=[("active", p["bg"])])

    # Segmented Lock/Unlock switch: two buttons, one styled "active" (filled
    # accent) and the other "inactive" (flat, muted) depending on which mode
    # is selected -- swapped live by the caller, not via ttk state maps, since
    # this needs to persist as a selection rather than a hover/press state.
    style.configure(
        "Segment.TButton",
        background=p["surface"],
        foreground=p["text_muted"],
        borderwidth=0,
        focusthickness=0,
        padding=(18, 8),
        font=(family, 11, "bold"),
    )
    style.map(
        "Segment.TButton",
        background=[("active", p["surface_hover"])],
        foreground=[("active", p["text"])],
    )
    style.configure(
        "SegmentActive.TButton",
        background=p["accent"],
        foreground="#ffffff",
        borderwidth=0,
        focusthickness=0,
        padding=(18, 8),
        font=(family, 11, "bold"),
    )
    style.map("SegmentActive.TButton", background=[("active", p["accent_hover"])])

    style.configure(
        "Accent.Horizontal.TProgressbar",
        troughcolor=p["surface"],
        background=p["accent"],
        bordercolor=p["surface"],
        lightcolor=p["accent"],
        darkcolor=p["accent"],
        thickness=8,
    )

    return p
