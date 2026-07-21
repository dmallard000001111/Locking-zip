"""tkinter/ttk GUI: drag a file or folder in, set a password, get a password-
protected zip out -- or drag a protected zip in and unlock it.

Uses tkinterdnd2 for real OS-level drag-and-drop. Its `tkdnd` Tcl extension is
loaded at runtime by TkinterDnD.Tk() (not at `import tkinterdnd2` time), so a
frozen PyInstaller build can still fail here even though the import above
succeeded -- see main_gui.py's --selftest, which instantiates a real
TkinterDnD.Tk() specifically to catch that.

Rule: `password` is never passed to print(), logging, an exception message, a
filename, or a window title -- only ever to core.encrypt_to_zip()/extract_zip().
"""
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Optional

from locking_zip import core, fsutil, gui_logic, theme

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    _HAS_DND = True
except ImportError:
    _HAS_DND = False

APP_NAME = "Zip Lock"


class PasswordDialog(tk.Toplevel):
    """Modal dialog collecting a password + confirmation + encryption mode.
    Sets self.result to the password string and self.mode to core.MODE_STANDARD
    / core.MODE_AES on OK, or self.result = None on Cancel/close."""

    def __init__(self, parent, palette: dict):
        super().__init__(parent)
        self._p = palette
        self.result: Optional[str] = None
        self.mode: str = core.MODE_STANDARD
        self.title("Set Password")
        self.configure(bg=palette["bg"])
        self.transient(parent)
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)

        ttk.Label(self, text="🔒 Set a password", style="Title.TLabel").grid(
            row=0, column=0, columnspan=2, sticky="w", padx=20, pady=(20, 12)
        )

        ttk.Label(self, text="Password").grid(row=1, column=0, sticky="w", padx=20)
        self._pw_var = tk.StringVar()
        self._pw_entry = ttk.Entry(self, textvariable=self._pw_var, show="•", width=30)
        self._pw_entry.grid(row=2, column=0, columnspan=2, sticky="ew", padx=20)

        ttk.Label(self, text="Confirm password").grid(row=3, column=0, sticky="w", padx=20, pady=(10, 0))
        self._confirm_var = tk.StringVar()
        self._confirm_entry = ttk.Entry(self, textvariable=self._confirm_var, show="•", width=30)
        self._confirm_entry.grid(row=4, column=0, columnspan=2, sticky="ew", padx=20)

        self._show_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            self, text="Show password", variable=self._show_var, command=self._toggle_show
        ).grid(row=5, column=0, columnspan=2, sticky="w", padx=18, pady=(8, 0))

        self._strength_label = ttk.Label(self, text="", style="Muted.TLabel")
        self._strength_label.grid(row=6, column=0, columnspan=2, sticky="w", padx=20, pady=(6, 0))

        ttk.Label(self, text="Protection level", style="Muted.TLabel").grid(
            row=7, column=0, columnspan=2, sticky="w", padx=20, pady=(12, 2)
        )
        self._mode_var = tk.StringVar(value=core.MODE_STANDARD)
        ttk.Radiobutton(
            self,
            text="Standard — opens everywhere, no extra software needed",
            variable=self._mode_var,
            value=core.MODE_STANDARD,
        ).grid(row=8, column=0, columnspan=2, sticky="w", padx=20)
        ttk.Radiobutton(
            self,
            text="AES-256 — stronger, needs 7-Zip (Windows) or Keka (Mac) to open",
            variable=self._mode_var,
            value=core.MODE_AES,
        ).grid(row=9, column=0, columnspan=2, sticky="w", padx=20, pady=(2, 0))

        self._error_label = ttk.Label(self, text="", style="Error.TLabel")
        self._error_label.grid(row=10, column=0, columnspan=2, sticky="w", padx=20, pady=(8, 0))

        btn_frame = ttk.Frame(self)
        btn_frame.grid(row=11, column=0, columnspan=2, pady=(14, 20), padx=20, sticky="e")
        ttk.Button(btn_frame, text="Cancel", style="Secondary.TButton", command=self._on_cancel).pack(
            side="left", padx=(0, 8)
        )
        self._ok_btn = ttk.Button(
            btn_frame, text="Create Zip", style="Accent.TButton", command=self._on_ok, state="disabled"
        )
        self._ok_btn.pack(side="left")

        self._pw_var.trace_add("write", self._on_input_changed)
        self._confirm_var.trace_add("write", self._on_input_changed)
        self.bind("<Return>", lambda _e: self._on_ok())

        self._pw_entry.focus_set()
        self.grab_set()
        self.wait_window(self)

    def _toggle_show(self):
        show = "" if self._show_var.get() else "•"
        self._pw_entry.config(show=show)
        self._confirm_entry.config(show=show)

    def _on_input_changed(self, *_args):
        password = self._pw_var.get()
        confirm = self._confirm_var.get()
        strength = gui_logic.estimate_strength(password)
        self._strength_label.config(text=f"Password strength: {strength}" if strength else "")

        if not password:
            self._error_label.config(text="")
            self._ok_btn.config(state="disabled")
            return

        if confirm and not gui_logic.passwords_match(password, confirm):
            self._error_label.config(text="Passwords do not match.")
            self._ok_btn.config(state="disabled")
            return

        self._error_label.config(text="")
        valid = gui_logic.passwords_match(password, confirm)
        self._ok_btn.config(state="normal" if valid else "disabled")

    def _on_ok(self):
        password = self._pw_var.get()
        confirm = self._confirm_var.get()
        if not gui_logic.passwords_match(password, confirm):
            self._error_label.config(text="Passwords do not match.")
            return
        self.result = password
        self.mode = self._mode_var.get()
        self.destroy()

    def _on_cancel(self):
        self.result = None
        self.destroy()


class UnlockPasswordDialog(tk.Toplevel):
    """Single-field password prompt for unlocking. `error` pre-populates the
    error label, used to loop on a wrong password without restarting the whole
    unlock flow (source file and destination stay chosen)."""

    def __init__(self, parent, palette: dict, error: Optional[str] = None):
        super().__init__(parent)
        self._p = palette
        self.result: Optional[str] = None
        self.title("Enter Password")
        self.configure(bg=palette["bg"])
        self.transient(parent)
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)

        ttk.Label(self, text="🔓 Enter password", style="Title.TLabel").grid(
            row=0, column=0, columnspan=2, sticky="w", padx=20, pady=(20, 12)
        )

        ttk.Label(self, text="Password").grid(row=1, column=0, sticky="w", padx=20)
        self._pw_var = tk.StringVar()
        self._pw_entry = ttk.Entry(self, textvariable=self._pw_var, show="•", width=30)
        self._pw_entry.grid(row=2, column=0, columnspan=2, sticky="ew", padx=20)

        self._show_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            self, text="Show password", variable=self._show_var, command=self._toggle_show
        ).grid(row=3, column=0, columnspan=2, sticky="w", padx=18, pady=(8, 0))

        self._error_label = ttk.Label(self, text=error or "", style="Error.TLabel")
        self._error_label.grid(row=4, column=0, columnspan=2, sticky="w", padx=20, pady=(6, 0))

        btn_frame = ttk.Frame(self)
        btn_frame.grid(row=5, column=0, columnspan=2, pady=(14, 20), padx=20, sticky="e")
        ttk.Button(btn_frame, text="Cancel", style="Secondary.TButton", command=self._on_cancel).pack(
            side="left", padx=(0, 8)
        )
        self._ok_btn = ttk.Button(
            btn_frame, text="Unlock", style="Accent.TButton", command=self._on_ok, state="disabled"
        )
        self._ok_btn.pack(side="left")

        self._pw_var.trace_add("write", self._on_input_changed)
        self.bind("<Return>", lambda _e: self._on_ok())

        self._pw_entry.focus_set()
        self.grab_set()
        self.wait_window(self)

    def _toggle_show(self):
        self._pw_entry.config(show="" if self._show_var.get() else "•")

    def _on_input_changed(self, *_args):
        self._ok_btn.config(state="normal" if self._pw_var.get() else "disabled")

    def _on_ok(self):
        if not self._pw_var.get():
            return
        self.result = self._pw_var.get()
        self.destroy()

    def _on_cancel(self):
        self.result = None
        self.destroy()


class LockingZipApp:
    def __init__(self, root: tk.Tk, palette: dict):
        self.root = root
        self._p = palette
        self.root.title(APP_NAME)
        self.root.geometry("560x520")
        self.root.minsize(480, 460)

        self._lock_source: Optional[Path] = None
        self._unlock_source: Optional[Path] = None
        self._cancel_event: Optional[threading.Event] = None
        self._mode = "lock"

        self._build_ui()

    # ---- shared chrome ----------------------------------------------------

    def _build_ui(self) -> None:
        p = self._p
        outer = ttk.Frame(self.root, padding=24)
        outer.pack(fill="both", expand=True)

        header = ttk.Frame(outer)
        header.pack(fill="x", pady=(0, 14))
        ttk.Label(header, text=f"🔒 {APP_NAME}", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            header,
            text="Password-protect a file or folder, or unlock one you already have.",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(2, 0))

        switch = ttk.Frame(outer)
        switch.pack(fill="x", pady=(0, 16))
        self._lock_tab_btn = ttk.Button(switch, text="Lock", command=lambda: self._switch_mode("lock"))
        self._lock_tab_btn.pack(side="left")
        self._unlock_tab_btn = ttk.Button(switch, text="Unlock", command=lambda: self._switch_mode("unlock"))
        self._unlock_tab_btn.pack(side="left", padx=(6, 0))

        self._content = ttk.Frame(outer)
        self._content.pack(fill="both", expand=True)

        self._lock_frame = self._build_lock_ui(self._content)
        self._unlock_frame = self._build_unlock_ui(self._content)

        self._switch_mode("lock")

    def _switch_mode(self, mode: str) -> None:
        self._mode = mode
        if mode == "lock":
            self._unlock_frame.pack_forget()
            self._lock_frame.pack(fill="both", expand=True)
            self._lock_tab_btn.configure(style="SegmentActive.TButton")
            self._unlock_tab_btn.configure(style="Segment.TButton")
        else:
            self._lock_frame.pack_forget()
            self._unlock_frame.pack(fill="both", expand=True)
            self._unlock_tab_btn.configure(style="SegmentActive.TButton")
            self._lock_tab_btn.configure(style="Segment.TButton")

    def _build_drop_card(
        self, parent, *, icon: str, title: str, link1_text: str, on_link1, link2_text=None, on_link2=None
    ):
        """Builds the reusable drop-zone visual (used by both Lock and Unlock)
        and wires drag-and-drop with live hover feedback. Returns
        (card_frame, drop_label) -- callers bind their own <<Drop>> handler."""
        p = self._p
        card = tk.Frame(
            parent,
            bg=p["surface"],
            highlightthickness=2,
            highlightbackground=p["border"],
            highlightcolor=p["border"],
        )

        inner = tk.Frame(card, bg=p["surface"])
        inner.place(relx=0.5, rely=0.5, anchor="center")

        tk.Label(inner, text=icon, bg=p["surface"], font=("", 32)).pack(pady=(0, 6))
        drop_label = tk.Label(
            inner, text=title, bg=p["surface"], fg=p["text"], font=("", 13, "bold"), justify="center"
        )
        drop_label.pack()

        links = tk.Frame(inner, bg=p["surface"])
        links.pack(pady=(10, 0))
        link1 = ttk.Label(links, text=link1_text, style="Link.TLabel", cursor="hand2")
        link1.pack(side="left")
        link1.bind("<Button-1>", lambda _e: on_link1())
        if link2_text:
            tk.Label(links, text="   ·   ", bg=p["surface"], fg=p["text_muted"]).pack(side="left")
            link2 = ttk.Label(links, text=link2_text, style="Link.TLabel", cursor="hand2")
            link2.pack(side="left")
            link2.bind("<Button-1>", lambda _e: on_link2())

        return card, inner, drop_label

    def _wire_dnd(self, widgets, on_drop) -> bool:
        if not _HAS_DND:
            return False
        card = widgets[0]
        try:
            for widget in widgets:
                widget.drop_target_register(DND_FILES)
                widget.dnd_bind(
                    "<<DropEnter>>",
                    lambda _e, c=card: c.config(
                        highlightbackground=self._p["border_hover"], highlightcolor=self._p["border_hover"]
                    ),
                )
                widget.dnd_bind(
                    "<<DropLeave>>",
                    lambda _e, c=card: c.config(
                        highlightbackground=self._p["border"], highlightcolor=self._p["border"]
                    ),
                )
                widget.dnd_bind("<<Drop>>", on_drop)
            return True
        except tk.TclError:
            return False

    # ---- Lock UI ------------------------------------------------------------

    def _build_lock_ui(self, parent) -> ttk.Frame:
        frame = ttk.Frame(parent)

        card, inner, drop_label = self._build_drop_card(
            frame,
            icon="📂",
            title="Drag & drop a file or folder here",
            link1_text="choose a file",
            on_link1=self._on_browse_file,
            link2_text="choose a folder",
            on_link2=self._on_browse_folder,
        )
        card.pack(fill="both", expand=True)
        self._lock_card = card

        def on_drop(event):
            paths = gui_logic.parse_dropped_paths(event.data, self.root.tk.splitlist)
            if paths:
                self._set_lock_source(Path(paths[0]))

        if not self._wire_dnd([card, inner, drop_label], on_drop):
            drop_label.config(text="Drag & drop unavailable here — use the links below.")

        self._lock_source_label = ttk.Label(
            frame, text="No file or folder selected.", style="Muted.TLabel", wraplength=500
        )
        self._lock_source_label.pack(fill="x", pady=(14, 8))

        self._lock_progress = ttk.Progressbar(frame, mode="determinate", style="Accent.Horizontal.TProgressbar")
        self._lock_progress.pack(fill="x", pady=(0, 4))
        self._lock_progress_label = ttk.Label(frame, text="", style="Muted.TLabel")
        self._lock_progress_label.pack(fill="x")

        action_frame = ttk.Frame(frame)
        action_frame.pack(fill="x", pady=(14, 0))
        self._encrypt_btn = ttk.Button(
            action_frame, text="Encrypt…", style="Accent.TButton", command=self._on_encrypt_clicked, state="disabled"
        )
        self._encrypt_btn.pack(side="left")
        self._lock_cancel_btn = ttk.Button(
            action_frame, text="Cancel", style="Secondary.TButton", command=self._on_lock_cancel_clicked, state="disabled"
        )
        self._lock_cancel_btn.pack(side="left", padx=(8, 0))

        ttk.Label(
            frame,
            text="Uses standard zip password protection by default — the result opens with any unzip tool. AES-256 is available for stronger protection.",
            style="Muted.TLabel",
            wraplength=500,
        ).pack(fill="x", pady=(16, 0))

        return frame

    def _on_browse_file(self) -> None:
        chosen = filedialog.askopenfilename(title="Choose a file to encrypt")
        if chosen:
            self._set_lock_source(Path(chosen))

    def _on_browse_folder(self) -> None:
        chosen = filedialog.askdirectory(title="Choose a folder to encrypt")
        if chosen:
            self._set_lock_source(Path(chosen))

    def _set_lock_source(self, path: Path) -> None:
        error = gui_logic.validate_source(path)
        if error:
            messagebox.showerror(APP_NAME, error)
            return
        self._lock_source = path
        kind = "📁 Folder" if path.is_dir() else "📄 File"
        self._lock_source_label.config(text=f"{kind} selected: {path}", style="TLabel")
        self._encrypt_btn.config(state="normal")

    def _on_encrypt_clicked(self) -> None:
        if self._lock_source is None:
            return

        entries, skipped = fsutil.collect_entries(self._lock_source)
        if skipped:
            if not messagebox.askyesno(
                APP_NAME, f"{len(skipped)} symbolic link(s) will be skipped and not included. Continue?"
            ):
                return

        if not entries:
            if not messagebox.askyesno(
                APP_NAME, "This folder contains no files. Create an empty encrypted zip anyway?"
            ):
                return

        dialog = PasswordDialog(self.root, self._p)
        password = dialog.result
        if not password:
            return
        mode = dialog.mode

        default_name = gui_logic.suggest_dest_name(self._lock_source)
        dest_str = filedialog.asksaveasfilename(
            title="Save encrypted zip as",
            defaultextension=".zip",
            initialfile=default_name,
            filetypes=[("Zip archive", "*.zip")],
        )
        if not dest_str:
            return
        dest = Path(dest_str)

        total_size = fsutil.compute_total_size(entries)
        self._cancel_event = threading.Event()
        self._lock_progress.config(mode="determinate", maximum=max(total_size, 1), value=0)
        self._lock_progress_label.config(text="Encrypting…")
        self._encrypt_btn.config(state="disabled")
        self._lock_cancel_btn.config(state="normal")

        thread = threading.Thread(
            target=self._run_encryption_worker,
            args=(entries, dest, password, mode, total_size),
            daemon=True,
        )
        thread.start()

    def _on_lock_cancel_clicked(self) -> None:
        if self._cancel_event is not None:
            self._cancel_event.set()

    def _run_encryption_worker(self, entries, dest: Path, password: str, mode: str, total_size: int) -> None:
        def progress_cb(done: int, total: int, name: str) -> None:
            self.root.after(0, self._update_lock_progress, done, total, name)

        try:
            core.encrypt_to_zip(
                entries,
                dest,
                password,
                mode=mode,
                total_size=total_size,
                overwrite=True,
                progress_cb=progress_cb,
                cancel_event=self._cancel_event,
            )
        except core.CancelledError:
            self.root.after(0, self._on_lock_cancelled)
        except core.OutputExistsError:
            self.root.after(0, self._on_lock_error, "That file already exists.")
        except core.PermissionDeniedError as e:
            self.root.after(
                0, self._on_lock_error, f"Permission denied — check access to {e} and that it isn't open elsewhere."
            )
        except core.DiskFullError:
            self.root.after(0, self._on_lock_error, "Not enough disk space to finish. Free up space and try again.")
        except core.EncryptionError as e:
            self.root.after(0, self._on_lock_error, f"Encryption failed: {e}")
        except Exception as e:
            self.root.after(0, self._on_lock_error, f"An unexpected error occurred: {type(e).__name__}.")
        else:
            self.root.after(0, self._on_lock_success, dest)

    def _update_lock_progress(self, done: int, total: int, name: str) -> None:
        self._lock_progress.config(value=done)
        self._lock_progress_label.config(text=f"Encrypting {name}…")

    def _reset_lock_controls(self) -> None:
        self._cancel_event = None
        self._encrypt_btn.config(state="normal" if self._lock_source else "disabled")
        self._lock_cancel_btn.config(state="disabled")
        self._lock_progress.config(value=0)

    def _on_lock_success(self, dest: Path) -> None:
        self._lock_progress_label.config(text="Done.")
        self._reset_lock_controls()
        messagebox.showinfo(APP_NAME, f"Created encrypted zip:\n{dest}")

    def _on_lock_cancelled(self) -> None:
        self._lock_progress_label.config(text="Cancelled.")
        self._reset_lock_controls()
        messagebox.showinfo(APP_NAME, "Encryption cancelled.")

    def _on_lock_error(self, message: str) -> None:
        self._lock_progress_label.config(text="Failed.")
        self._reset_lock_controls()
        messagebox.showerror(APP_NAME, message)

    # ---- Unlock UI ----------------------------------------------------------

    def _build_unlock_ui(self, parent) -> ttk.Frame:
        frame = ttk.Frame(parent)

        card, inner, drop_label = self._build_drop_card(
            frame,
            icon="🔓",
            title="Drag & drop a password-protected zip here",
            link1_text="choose a zip file",
            on_link1=self._on_browse_unlock_file,
        )
        card.pack(fill="both", expand=True)
        self._unlock_card = card

        def on_drop(event):
            paths = gui_logic.parse_dropped_paths(event.data, self.root.tk.splitlist)
            if paths:
                self._set_unlock_source(Path(paths[0]))

        if not self._wire_dnd([card, inner, drop_label], on_drop):
            drop_label.config(text="Drag & drop unavailable here — use the link below.")

        self._unlock_source_label = ttk.Label(
            frame, text="No zip file selected.", style="Muted.TLabel", wraplength=500
        )
        self._unlock_source_label.pack(fill="x", pady=(14, 8))

        self._unlock_progress = ttk.Progressbar(frame, mode="determinate", style="Accent.Horizontal.TProgressbar")
        self._unlock_progress.pack(fill="x", pady=(0, 4))
        self._unlock_progress_label = ttk.Label(frame, text="", style="Muted.TLabel")
        self._unlock_progress_label.pack(fill="x")

        action_frame = ttk.Frame(frame)
        action_frame.pack(fill="x", pady=(14, 0))
        self._unlock_btn = ttk.Button(
            action_frame, text="Unlock…", style="Accent.TButton", command=self._on_unlock_clicked, state="disabled"
        )
        self._unlock_btn.pack(side="left")
        self._unlock_cancel_btn = ttk.Button(
            action_frame, text="Cancel", style="Secondary.TButton", command=self._on_unlock_cancel_clicked, state="disabled"
        )
        self._unlock_cancel_btn.pack(side="left", padx=(8, 0))

        ttk.Label(
            frame,
            text="Works on zips this app made (either protection level) and most password-protected zips from other tools.",
            style="Muted.TLabel",
            wraplength=500,
        ).pack(fill="x", pady=(16, 0))

        return frame

    def _on_browse_unlock_file(self) -> None:
        chosen = filedialog.askopenfilename(
            title="Choose a zip file to unlock", filetypes=[("Zip archive", "*.zip"), ("All files", "*")]
        )
        if chosen:
            self._set_unlock_source(Path(chosen))

    def _set_unlock_source(self, path: Path) -> None:
        error = gui_logic.validate_source(path)
        if error:
            messagebox.showerror(APP_NAME, error)
            return
        self._unlock_source = path
        self._unlock_source_label.config(text=f"🗜️ Zip selected: {path}", style="TLabel")
        self._unlock_btn.config(state="normal")

    def _on_unlock_clicked(self) -> None:
        if self._unlock_source is None:
            return

        suggested = gui_logic.suggest_extract_dir(self._unlock_source)
        dest_str = filedialog.askdirectory(
            title="Extract to folder", initialdir=str(suggested.parent), mustexist=False
        )
        if not dest_str:
            return
        dest_dir = Path(dest_str) / suggested.name

        self._prompt_unlock_password_and_run(dest_dir, error=None)

    def _prompt_unlock_password_and_run(self, dest_dir: Path, error: Optional[str]) -> None:
        dialog = UnlockPasswordDialog(self.root, self._p, error=error)
        password = dialog.result
        if not password:
            return

        self._cancel_event = threading.Event()
        self._unlock_progress.config(mode="determinate", value=0)
        self._unlock_progress_label.config(text="Unlocking…")
        self._unlock_btn.config(state="disabled")
        self._unlock_cancel_btn.config(state="normal")

        thread = threading.Thread(
            target=self._run_extraction_worker,
            args=(self._unlock_source, dest_dir, password),
            daemon=True,
        )
        thread.start()

    def _on_unlock_cancel_clicked(self) -> None:
        if self._cancel_event is not None:
            self._cancel_event.set()

    def _run_extraction_worker(self, source_zip: Path, dest_dir: Path, password: str) -> None:
        def progress_cb(done: int, total: int, name: str) -> None:
            self.root.after(0, self._update_unlock_progress, done, total, name)

        try:
            core.extract_zip(
                source_zip, dest_dir, password, progress_cb=progress_cb, cancel_event=self._cancel_event
            )
        except core.CancelledError:
            self.root.after(0, self._on_unlock_cancelled)
        except core.WrongPasswordError:
            self.root.after(0, self._on_unlock_wrong_password, dest_dir)
        except core.UnsafePathError:
            self.root.after(
                0, self._on_unlock_error, "This zip contains unsafe file paths and was not extracted."
            )
        except core.PermissionDeniedError as e:
            self.root.after(
                0, self._on_unlock_error, f"Permission denied — check access to {e} and that it isn't open elsewhere."
            )
        except core.DiskFullError:
            self.root.after(0, self._on_unlock_error, "Not enough disk space to finish. Free up space and try again.")
        except core.EncryptionError as e:
            self.root.after(0, self._on_unlock_error, f"Unlock failed: {e}")
        except Exception as e:
            self.root.after(0, self._on_unlock_error, f"An unexpected error occurred: {type(e).__name__}.")
        else:
            self.root.after(0, self._on_unlock_success, dest_dir)

    def _update_unlock_progress(self, done: int, total: int, name: str) -> None:
        self._unlock_progress.config(maximum=max(total, 1), value=done)
        self._unlock_progress_label.config(text=f"Extracting {name}…")

    def _reset_unlock_controls(self) -> None:
        self._cancel_event = None
        self._unlock_btn.config(state="normal" if self._unlock_source else "disabled")
        self._unlock_cancel_btn.config(state="disabled")
        self._unlock_progress.config(value=0)

    def _on_unlock_success(self, dest_dir: Path) -> None:
        self._unlock_progress_label.config(text="Done.")
        self._reset_unlock_controls()
        messagebox.showinfo(APP_NAME, f"Extracted to:\n{dest_dir}")

    def _on_unlock_cancelled(self) -> None:
        self._unlock_progress_label.config(text="Cancelled.")
        self._reset_unlock_controls()
        messagebox.showinfo(APP_NAME, "Unlock cancelled.")

    def _on_unlock_wrong_password(self, dest_dir: Path) -> None:
        self._unlock_progress_label.config(text="")
        self._reset_unlock_controls()
        self._prompt_unlock_password_and_run(dest_dir, error="Incorrect password. Try again.")

    def _on_unlock_error(self, message: str) -> None:
        self._unlock_progress_label.config(text="Failed.")
        self._reset_unlock_controls()
        messagebox.showerror(APP_NAME, message)


def main() -> None:
    if _HAS_DND:
        try:
            root = TkinterDnD.Tk()
        except Exception:
            root = tk.Tk()
    else:
        root = tk.Tk()

    palette = theme.apply_theme(root)
    app = LockingZipApp(root, palette)
    root.mainloop()


if __name__ == "__main__":
    main()
