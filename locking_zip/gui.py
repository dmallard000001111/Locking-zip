"""tkinter/ttk GUI: drag a file or folder in, set a password, get a password-
protected zip out.

Uses tkinterdnd2 for real OS-level drag-and-drop. Its `tkdnd` Tcl extension is
loaded at runtime by TkinterDnD.Tk() (not at `import tkinterdnd2` time), so a
frozen PyInstaller build can still fail here even though the import above
succeeded -- see main_gui.py's --selftest, which instantiates a real
TkinterDnD.Tk() specifically to catch that.

Rule: `password` is never passed to print(), logging, an exception message, a
filename, or a window title -- only ever to core.encrypt_to_zip().
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


class PasswordDialog(tk.Toplevel):
    """Modal dialog collecting a password + confirmation. Sets self.result to
    the password string on OK, or None on Cancel/close."""

    def __init__(self, parent, palette: dict):
        super().__init__(parent)
        self._p = palette
        self.result: Optional[str] = None
        self.title("Set Password")
        self.configure(bg=palette["bg"])
        self.transient(parent)
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)

        pad = {"padx": 20, "pady": 6}

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

        self._error_label = ttk.Label(self, text="", style="Error.TLabel")
        self._error_label.grid(row=7, column=0, columnspan=2, sticky="w", padx=20)

        btn_frame = ttk.Frame(self)
        btn_frame.grid(row=8, column=0, columnspan=2, pady=(14, 20), padx=20, sticky="e")
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
        self._strength_label.config(text=f"Strength: {strength}" if strength else "")

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
        self.destroy()

    def _on_cancel(self):
        self.result = None
        self.destroy()


class LockingZipApp:
    def __init__(self, root: tk.Tk, palette: dict):
        self.root = root
        self._p = palette
        self.root.title("Locking Zip")
        self.root.geometry("560x460")
        self.root.minsize(480, 400)

        self._source: Optional[Path] = None
        self._cancel_event: Optional[threading.Event] = None

        self._build_ui()

    def _build_ui(self) -> None:
        p = self._p
        outer = ttk.Frame(self.root, padding=24)
        outer.pack(fill="both", expand=True)

        header = ttk.Frame(outer)
        header.pack(fill="x", pady=(0, 18))
        ttk.Label(header, text="🔒 Locking Zip", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            header,
            text="Drop a file or folder, set a password, get a zip anyone can open.",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(2, 0))

        # Drop zone: a plain tk.Frame (not ttk) so its border color can be
        # flipped live on drag-enter/leave -- ttk styles are static per-widget-
        # class and can't be swapped per-instance the way this needs.
        self._drop_frame = tk.Frame(
            outer,
            bg=p["surface"],
            highlightthickness=2,
            highlightbackground=p["border"],
            highlightcolor=p["border"],
        )
        self._drop_frame.pack(fill="both", expand=True)

        drop_inner = tk.Frame(self._drop_frame, bg=p["surface"])
        drop_inner.place(relx=0.5, rely=0.5, anchor="center")

        self._drop_icon = tk.Label(drop_inner, text="📂", bg=p["surface"], font=("", 32))
        self._drop_icon.pack(pady=(0, 6))

        self._drop_label = tk.Label(
            drop_inner,
            text="Drag & drop a file or folder here",
            bg=p["surface"],
            fg=p["text"],
            font=("", 13, "bold"),
            justify="center",
        )
        self._drop_label.pack()

        links = tk.Frame(drop_inner, bg=p["surface"])
        links.pack(pady=(10, 0))
        self._file_link = ttk.Label(links, text="choose a file", style="Link.TLabel", cursor="hand2")
        self._file_link.pack(side="left")
        tk.Label(links, text="   ·   ", bg=p["surface"], fg=p["text_muted"]).pack(side="left")
        self._folder_link = ttk.Label(links, text="choose a folder", style="Link.TLabel", cursor="hand2")
        self._folder_link.pack(side="left")
        self._file_link.bind("<Button-1>", lambda _e: self._on_browse_file())
        self._folder_link.bind("<Button-1>", lambda _e: self._on_browse_folder())

        self._source_label = ttk.Label(
            outer, text="No file or folder selected.", style="Muted.TLabel", wraplength=500
        )
        self._source_label.pack(fill="x", pady=(14, 8))

        self._progress = ttk.Progressbar(outer, mode="determinate", style="Accent.Horizontal.TProgressbar")
        self._progress.pack(fill="x", pady=(0, 4))
        self._progress_label = ttk.Label(outer, text="", style="Muted.TLabel")
        self._progress_label.pack(fill="x")

        action_frame = ttk.Frame(outer)
        action_frame.pack(fill="x", pady=(14, 0))
        self._encrypt_btn = ttk.Button(
            action_frame,
            text="Encrypt…",
            style="Accent.TButton",
            command=self._on_encrypt_clicked,
            state="disabled",
        )
        self._encrypt_btn.pack(side="left")
        self._cancel_btn = ttk.Button(
            action_frame,
            text="Cancel",
            style="Secondary.TButton",
            command=self._on_cancel_clicked,
            state="disabled",
        )
        self._cancel_btn.pack(side="left", padx=(8, 0))

        footer = ttk.Label(
            outer,
            text="Uses standard zip password protection — the result opens with any unzip tool.",
            style="Muted.TLabel",
            wraplength=500,
        )
        footer.pack(fill="x", pady=(16, 0))

        if _HAS_DND:
            try:
                for widget in (self._drop_frame, drop_inner, self._drop_icon, self._drop_label):
                    widget.drop_target_register(DND_FILES)
                    widget.dnd_bind("<<DropEnter>>", self._on_drag_enter)
                    widget.dnd_bind("<<DropLeave>>", self._on_drag_leave)
                    widget.dnd_bind("<<Drop>>", self._on_drop)
            except tk.TclError:
                self._drop_label.config(text="Drag & drop unavailable here — use the links below.")
        else:
            self._drop_label.config(text="Drag & drop unavailable here — use the links below.")

    def _on_drag_enter(self, _event) -> None:
        p = self._p
        self._drop_frame.config(highlightbackground=p["border_hover"], highlightcolor=p["border_hover"])

    def _on_drag_leave(self, _event) -> None:
        p = self._p
        self._drop_frame.config(highlightbackground=p["border"], highlightcolor=p["border"])

    def _on_drop(self, event) -> None:
        self._on_drag_leave(event)
        paths = gui_logic.parse_dropped_paths(event.data, self.root.tk.splitlist)
        if not paths:
            return
        self._set_source(Path(paths[0]))

    def _on_browse_file(self) -> None:
        chosen = filedialog.askopenfilename(title="Choose a file to encrypt")
        if chosen:
            self._set_source(Path(chosen))

    def _on_browse_folder(self) -> None:
        chosen = filedialog.askdirectory(title="Choose a folder to encrypt")
        if chosen:
            self._set_source(Path(chosen))

    def _set_source(self, path: Path) -> None:
        error = gui_logic.validate_source(path)
        if error:
            messagebox.showerror("Locking Zip", error)
            return
        self._source = path
        kind = "📁 Folder" if path.is_dir() else "📄 File"
        self._source_label.config(text=f"{kind} selected: {path}", style="TLabel")
        self._encrypt_btn.config(state="normal")

    def _on_encrypt_clicked(self) -> None:
        if self._source is None:
            return

        entries, skipped = fsutil.collect_entries(self._source)
        if skipped:
            proceed = messagebox.askyesno(
                "Locking Zip",
                f"{len(skipped)} symbolic link(s) will be skipped and not included. Continue?",
            )
            if not proceed:
                return

        if not entries:
            proceed = messagebox.askyesno(
                "Locking Zip",
                "This folder contains no files. Create an empty encrypted zip anyway?",
            )
            if not proceed:
                return

        dialog = PasswordDialog(self.root, self._p)
        password = dialog.result
        if not password:
            return

        default_name = gui_logic.suggest_dest_name(self._source)
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
        self._progress.config(mode="determinate", maximum=max(total_size, 1), value=0)
        self._progress_label.config(text="Encrypting…")
        self._encrypt_btn.config(state="disabled")
        self._cancel_btn.config(state="normal")

        thread = threading.Thread(
            target=self._run_encryption_worker,
            args=(entries, dest, password, total_size),
            daemon=True,
        )
        thread.start()

    def _on_cancel_clicked(self) -> None:
        if self._cancel_event is not None:
            self._cancel_event.set()

    def _run_encryption_worker(self, entries, dest: Path, password: str, total_size: int) -> None:
        def progress_cb(done: int, total: int, name: str) -> None:
            self.root.after(0, self._update_progress, done, total, name)

        try:
            core.encrypt_to_zip(
                entries,
                dest,
                password,
                total_size=total_size,
                overwrite=True,
                progress_cb=progress_cb,
                cancel_event=self._cancel_event,
            )
        except core.CancelledError:
            self.root.after(0, self._on_cancelled)
        except core.OutputExistsError:
            self.root.after(0, self._on_error, "That file already exists.")
        except core.PermissionDeniedError as e:
            self.root.after(
                0, self._on_error, f"Permission denied — check access to {e} and that it isn't open elsewhere."
            )
        except core.DiskFullError:
            self.root.after(0, self._on_error, "Not enough disk space to finish. Free up space and try again.")
        except core.EncryptionError as e:
            self.root.after(0, self._on_error, f"Encryption failed: {e}")
        except Exception as e:
            self.root.after(0, self._on_error, f"An unexpected error occurred: {type(e).__name__}.")
        else:
            self.root.after(0, self._on_success, dest)

    def _update_progress(self, done: int, total: int, name: str) -> None:
        self._progress.config(value=done)
        self._progress_label.config(text=f"Encrypting {name}…")

    def _reset_controls(self) -> None:
        self._cancel_event = None
        self._encrypt_btn.config(state="normal" if self._source else "disabled")
        self._cancel_btn.config(state="disabled")
        self._progress.config(value=0)

    def _on_success(self, dest: Path) -> None:
        self._progress_label.config(text="Done.")
        self._reset_controls()
        messagebox.showinfo("Locking Zip", f"Created encrypted zip:\n{dest}")

    def _on_cancelled(self) -> None:
        self._progress_label.config(text="Cancelled.")
        self._reset_controls()
        messagebox.showinfo("Locking Zip", "Encryption cancelled.")

    def _on_error(self, message: str) -> None:
        self._progress_label.config(text="Failed.")
        self._reset_controls()
        messagebox.showerror("Locking Zip", message)


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
