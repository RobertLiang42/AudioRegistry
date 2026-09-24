"""Shared project creation and database management window."""

from __future__ import annotations

import sys
from pathlib import Path

from .dialogs import AUDIO_FILETYPES, AUDIO_SUFFIXES, bind_two_column_resize, build_database_panel
from .i18n import t


def _enable_windows_dpi_awareness() -> None:
    """Let Tk render at the monitor's real resolution instead of bitmap scaling."""
    if sys.platform != "win32":
        return
    import ctypes

    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except AttributeError:
        ctypes.windll.user32.SetProcessDPIAware()


def show_project_dialog(
    database,
    *,
    initial_project: str = "",
    initial_audio: str | Path | None = None,
    advance: bool = False,
) -> list[str] | None:
    """Create projects immediately; return names added during this visit."""
    _enable_windows_dpi_awareness()
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    from .database import validate_project_name

    root = tk.Tk()
    root.title(t("dialogs.new_project_window"))
    root.configure(background="#f5f9ff")
    scale = root.winfo_fpixels("1i") / 96
    min_width, min_height = round(900 * scale), round(540 * scale)
    root.minsize(min_width, min_height)
    width = max(min_width, min(round(1000 * scale), root.winfo_screenwidth() - round(80 * scale)))
    height = max(min_height, min(round(550 * scale), root.winfo_screenheight() - round(80 * scale)))
    root.geometry(f"{width}x{height}")
    root.resizable(True, True)

    style = ttk.Style(root)
    if "clam" in style.theme_names():
        style.theme_use("clam")
    style.configure("TFrame", background="#ffffff")
    style.configure("TLabel", background="#ffffff", foreground="#000000", font=("Microsoft YaHei UI", 10))
    style.configure("CardTitle.TLabel", background="#ffffff", foreground="#000000", font=("Microsoft YaHei UI", 15, "bold"))
    style.configure("Hint.TLabel", background="#ffffff", foreground="#000000")
    style.configure("QueueHint.TLabel", background="#ffffff", foreground="#777777", font=("Microsoft YaHei UI", 9))
    style.configure("TButton", background="#ffffff", foreground="#000000", bordercolor="#202020", lightcolor="#202020", darkcolor="#202020", relief="solid", borderwidth=1, padding=(10, 7))
    style.map("TButton", background=[("pressed", "#d8eaff"), ("active", "#e9f4ff")], bordercolor=[("active", "#202020")])
    style.configure("Accent.TButton", background="#1688ff", foreground="#000000", bordercolor="#202020", lightcolor="#202020", darkcolor="#202020", padding=(14, 8), font=("Microsoft YaHei UI", 10, "bold"))
    style.map("Accent.TButton", background=[("pressed", "#77bcff"), ("active", "#a2d2ff")], bordercolor=[("active", "#202020")], foreground=[("active", "#000000")])
    style.configure("Queue.TButton", font=("Microsoft YaHei UI", 9), padding=(3, 5))
    style.configure("TEntry", fieldbackground="#ffffff", foreground="#000000", bordercolor="#a5cafa", lightcolor="#a5cafa", darkcolor="#a5cafa", padding=5)
    style.map("TEntry", bordercolor=[("focus", "#1688ff")])
    style.configure("Treeview", rowheight=28, background="#ffffff", fieldbackground="#ffffff", foreground="#000000", bordercolor="#202020", lightcolor="#202020", darkcolor="#202020")
    style.map("Treeview", background=[("selected", "#c7e3ff")], foreground=[("selected", "#000000")])
    style.configure("Treeview.Heading", background="#f1f1f1", foreground="#000000", bordercolor="#202020", font=("Microsoft YaHei UI", 9, "bold"))
    style.map("Treeview.Heading", background=[("active", "#e0e0e0")])
    style.configure("Vertical.TScrollbar", background="#d6d6d6", troughcolor="#f2f2f2", arrowcolor="#000000", bordercolor="#202020", lightcolor="#eeeeee", darkcolor="#777777")
    style.map("Vertical.TScrollbar", background=[("active", "#bcbcbc")])

    jobs: list[tuple[str, Path]] = []
    added: list[str] = []
    result: list[str] | None = None
    selected_index: int | None = None
    loading = False
    dirty = False
    project = tk.StringVar(value=initial_project)
    audio = tk.StringVar(value=str(Path(initial_audio).resolve()) if initial_audio else "")
    queue_status = tk.StringVar()

    def remember(names: list[str]) -> None:
        for name in names:
            if name not in added:
                added.append(name)

    def renamed(old: str, new: str) -> None:
        added[:] = [new if name.casefold() == old.casefold() else name for name in added]

    def deleted(names: list[str]) -> None:
        removed = {name.casefold() for name in names}
        added[:] = [name for name in added if name.casefold() not in removed]

    def changed(*_args) -> None:
        nonlocal dirty
        if not loading:
            dirty = True

    project.trace_add("write", changed)
    audio.trace_add("write", changed)

    body = tk.Frame(root, bg="#f5f9ff", padx=18, pady=16)
    body.pack(fill="both", expand=True)
    body.columnconfigure(0, weight=3, uniform="top")
    body.columnconfigure(1, weight=2, uniform="top")
    body.rowconfigure(0, weight=1, uniform="sections")
    body.rowconfigure(1, weight=1, uniform="sections")

    editor_outline = tk.Frame(body, bg="#2692ff", padx=3, pady=3)
    editor_outline.grid(row=0, column=0, sticky="nsew", padx=(0, 9), pady=(0, 9))
    editor = tk.Frame(editor_outline, bg="#ffffff", padx=18, pady=16)
    editor.pack(fill="both", expand=True)
    editor.columnconfigure(1, weight=1)
    editor.rowconfigure(3, weight=1)
    ttk.Label(editor, text=t("dialogs.new_project"), style="CardTitle.TLabel").grid(row=0, column=0, columnspan=3, sticky="w")
    ttk.Label(editor, text=t("dialogs.audio_file")).grid(row=1, column=0, sticky="w", padx=(0, 10), pady=7)
    audio_entry = ttk.Entry(editor, textvariable=audio)
    audio_entry.grid(row=1, column=1, sticky="ew", pady=7)

    def browse_audio() -> None:
        selected = filedialog.askopenfilename(title=t("dialogs.select_audio"), filetypes=AUDIO_FILETYPES, parent=root)
        if selected:
            path = Path(selected).resolve()
            audio.set(str(path))
            if not project.get().strip():
                project.set(path.stem)

    ttk.Button(editor, text=t("dialogs.browse"), command=browse_audio).grid(row=1, column=2, padx=(8, 0), pady=7)
    ttk.Label(editor, text=t("dialogs.project_name")).grid(row=2, column=0, sticky="w", padx=(0, 10), pady=7)
    project_entry = ttk.Entry(editor, textvariable=project)
    project_entry.grid(row=2, column=1, columnspan=2, sticky="ew", pady=7)
    editor_buttons = ttk.Frame(editor)
    editor_buttons.grid(row=4, column=0, columnspan=3, sticky="sw", pady=(16, 0))

    queue_outline = tk.Frame(body, bg="#202020", padx=1, pady=1)
    queue_outline.grid(row=0, column=1, sticky="nsew", padx=(9, 0), pady=(0, 9))
    queue_card = tk.Frame(queue_outline, bg="#ffffff", padx=14, pady=16)
    queue_card.pack(fill="both", expand=True)
    queue_card.columnconfigure(0, weight=1)
    queue_card.rowconfigure(1, weight=1)
    queue_header = ttk.Frame(queue_card)
    queue_header.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 10))
    queue_header.columnconfigure(1, weight=1)
    ttk.Label(queue_header, text=t("dialogs.project_queue"), style="CardTitle.TLabel").grid(row=0, column=0, sticky="w")
    ttk.Label(queue_header, text=t("dialogs.project_queue_help"), style="QueueHint.TLabel").grid(row=0, column=1, sticky="e")
    queue = ttk.Treeview(queue_card, columns=("project", "audio"), show="headings", selectmode="browse", height=5)
    queue.heading("project", text=t("dialogs.project_name"))
    queue.heading("audio", text=t("dialogs.audio_file"))
    queue.column("project", width=round(140 * scale), minwidth=round(110 * scale), stretch=True)
    queue.column("audio", width=round(220 * scale), minwidth=round(130 * scale), stretch=True)
    bind_two_column_resize(queue, "project", "audio")
    queue.grid(row=1, column=0, sticky="nsew")
    scrollbar = ttk.Scrollbar(queue_card, orient="vertical", command=queue.yview)
    scrollbar.grid(row=1, column=1, sticky="ns")
    queue.configure(yscrollcommand=scrollbar.set)

    def scroll_queue(event) -> str:
        if getattr(event, "num", None) in (4, 5):
            direction = -1 if event.num == 4 else 1
        else:
            direction = -1 if event.delta > 0 else 1
        queue.yview_scroll(direction * 3, "units")
        return "break"

    for widget in (queue, scrollbar):
        widget.bind("<MouseWheel>", scroll_queue)
        widget.bind("<Button-4>", scroll_queue)
        widget.bind("<Button-5>", scroll_queue)
    queue_buttons = ttk.Frame(queue_card)
    queue_buttons.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(8, 0))
    ttk.Label(queue_buttons, textvariable=queue_status, style="Hint.TLabel").pack(side="left")
    queue_actions = ttk.Frame(queue_card)
    queue_actions.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(8, 0))
    for column in range(4):
        queue_actions.columnconfigure(column, weight=1, uniform="queue_buttons")

    database_outline = tk.Frame(body, bg="#202020", padx=1, pady=1)
    database_outline.grid(row=1, column=0, columnspan=2, sticky="nsew", pady=(9, 0))
    database_card = tk.Frame(database_outline, bg="#ffffff", padx=8, pady=4)
    database_card.pack(fill="both", expand=True)
    database_panel = build_database_panel(
        database_card, database, root, on_added=remember, on_renamed=renamed, on_deleted=deleted,
    )

    def read_editor() -> tuple[str, Path] | None:
        try:
            name = validate_project_name(project.get())
            path = Path(audio.get().strip()).resolve()
            if not path.is_file():
                raise ValueError(t("dialogs.audio_required"))
            if path.suffix.casefold() not in AUDIO_SUFFIXES:
                raise ValueError(t("dialogs.audio_unsupported"))
            if name.casefold() in {str(row["project_name"]).casefold() for row in database.list_projects()}:
                raise ValueError(t("errors.project_exists", name=name))
            if any(job[0].casefold() == name.casefold() for index, job in enumerate(jobs) if index != selected_index):
                raise ValueError(t("dialogs.duplicate_project_detail", name=name))
            return name, path
        except (OSError, ValueError) as error:
            messagebox.showerror(t("dialogs.invalid_parameters"), str(error), parent=root)
            return None

    def refresh_queue(select: int | None = None) -> None:
        children = queue.get_children()
        if children:
            queue.delete(*children)
        for index, (name, path) in enumerate(jobs):
            queue.insert("", "end", iid=str(index), values=(name, str(path)))
        queue_status.set(t("dialogs.queue_count", count=len(jobs)))
        if select is not None and 0 <= select < len(jobs):
            queue.selection_set(str(select))
            queue.focus(str(select))
            queue.see(str(select))

    def load(index: int | None) -> None:
        nonlocal selected_index, loading, dirty
        selected_index = index
        loading = True
        try:
            name, path = jobs[index] if index is not None else ("", "")
            project.set(name)
            audio.set(str(path))
        finally:
            loading = False
            dirty = False

    def save_to_queue() -> None:
        nonlocal selected_index, dirty
        job = read_editor()
        if job is None:
            return
        if selected_index is None:
            jobs.append(job)
        else:
            jobs[selected_index] = job
        selected_index = None
        dirty = False
        refresh_queue()
        load(None)
        audio_entry.focus_set()

    def create_current() -> None:
        job = read_editor()
        if job is None:
            return
        try:
            database.create_project(*job)
        except (OSError, ValueError) as error:
            messagebox.showerror(t("dialogs.invalid_parameters"), str(error), parent=root)
            return
        remember([job[0]])
        if selected_index is not None:
            jobs.pop(selected_index)
        refresh_queue()
        load(None)
        database_panel.refresh([job[0]])

    def create_all() -> None:
        if dirty or not jobs:
            save_to_queue()
            if dirty or not jobs:
                return
        created_names: list[str] = []
        while jobs:
            name, path = jobs[0]
            try:
                database.create_project(name, path)
            except (OSError, ValueError) as error:
                messagebox.showerror(t("dialogs.invalid_parameters"), str(error), parent=root)
                break
            remember([name])
            created_names.append(name)
            jobs.pop(0)
        refresh_queue()
        load(None)
        database_panel.refresh(created_names)

    def new_project() -> None:
        queue.selection_remove(*queue.selection())
        load(None)
        audio_entry.focus_set()

    def remove_selected() -> None:
        if selected_index is None:
            return
        jobs.pop(selected_index)
        refresh_queue()
        load(None)

    def add_audio_batch() -> None:
        selected = filedialog.askopenfilenames(title=t("dialogs.select_audio_batch"), filetypes=AUDIO_FILETYPES, parent=root)
        if not selected:
            return
        used = {str(row["project_name"]).casefold() for row in database.list_projects()}
        used.update(name.casefold() for name, _path in jobs)
        skipped: list[str] = []
        for value in selected:
            path = Path(value).resolve()
            try:
                name = validate_project_name(path.stem)
                if path.suffix.casefold() not in AUDIO_SUFFIXES or name.casefold() in used:
                    raise ValueError
            except (OSError, ValueError):
                skipped.append(path.name)
                continue
            used.add(name.casefold())
            jobs.append((name, path))
        refresh_queue(len(jobs) - 1 if jobs else None)
        if jobs:
            load(len(jobs) - 1)
        if skipped:
            messagebox.showwarning(t("dialogs.files_skipped"), t("dialogs.files_skipped_detail", names="\n".join(skipped)), parent=root)

    def select_queue_item(_event=None) -> None:
        selection = queue.selection()
        if selection:
            load(int(selection[0]))

    ttk.Button(editor_buttons, text=t("dialogs.save_queue"), command=save_to_queue).pack(side="left")
    ttk.Button(editor_buttons, text=t("dialogs.create_project"), command=create_current, style="Accent.TButton").pack(side="left", padx=(8, 0))
    ttk.Button(queue_actions, text=t("dialogs.new_project"), command=new_project, style="Queue.TButton").grid(row=0, column=0, sticky="ew", padx=2)
    ttk.Button(queue_actions, text=t("dialogs.remove_selected"), command=remove_selected, style="Queue.TButton").grid(row=0, column=1, sticky="ew", padx=2)
    ttk.Button(queue_actions, text=t("dialogs.add_audio_batch"), command=add_audio_batch, style="Queue.TButton").grid(row=0, column=2, sticky="ew", padx=2)
    ttk.Button(queue_actions, text=t("dialogs.create_batch"), command=create_all, style="Queue.TButton").grid(row=0, column=3, sticky="ew", padx=2)
    queue.bind("<<TreeviewSelect>>", select_queue_item)

    footer = tk.Frame(root, bg="#f5f9ff", padx=18, pady=10)
    footer.pack(fill="x")

    def finish(next_step: bool = False) -> None:
        nonlocal result
        if next_step and (jobs or dirty) and not messagebox.askyesno(
            t("dialogs.pending_queue_title"), t("dialogs.pending_queue_detail"), parent=root,
        ):
            return
        result = database_panel.selected_names() if next_step else (list(added) if not advance else None)
        root.destroy()

    ttk.Button(footer, text=t("dialogs.close"), command=finish).pack(side="right")
    if advance:
        ttk.Button(footer, text=t("dialogs.next_step"), command=lambda: finish(True), style="Accent.TButton").pack(side="right", padx=(0, 10))
    root.protocol("WM_DELETE_WINDOW", finish)
    refresh_queue()
    (project_entry if audio.get() else audio_entry).focus_set()
    root.mainloop()
    return result
