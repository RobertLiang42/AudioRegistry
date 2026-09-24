from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from .i18n import t

AUDIO_FILETYPES = [
    (t("dialogs.audio_files"), "*.wav *.flac *.mp3 *.m4a *.aac *.ogg *.opus"),
    (t("dialogs.all_files"), "*.*"),
]
AUDIO_SUFFIXES = {".wav", ".flac", ".mp3", ".m4a", ".aac", ".ogg", ".opus"}
SUBTITLE_FILETYPES = [
    (t("dialogs.subtitle_files"), "*.srt *.vtt *.ass *.ssa"),
    (t("dialogs.all_files"), "*.*"),
]


@dataclass(frozen=True, slots=True)
class ProcessDialogResult:
    project_name: str
    audio: Path
    language: str
    start_padding: float
    end_padding: float
    subtitle: Path | None = None


@dataclass(frozen=True, slots=True)
class DatabasePanel:
    refresh: Callable[[Iterable[str]], None]
    selected_names: Callable[[], list[str]]


def _root():
    import tkinter as tk

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    root.update()
    return root


def choose_output_directory(title: str | None = None) -> Path | None:
    from tkinter import filedialog

    root = _root()
    try:
        selected = filedialog.askdirectory(title=title or t("dialogs.select_output_folder"), parent=root)
        return Path(selected).resolve() if selected else None
    finally:
        root.destroy()


def choose_audio_variants(project_name: str, *, relocate_path: str | None = None) -> list[Path]:
    from tkinter import filedialog

    root = _root()
    try:
        if relocate_path is not None:
            original = Path(relocate_path)
            options = {"initialdir": str(original.parent)} if original.parent.is_dir() else {}
            selected = filedialog.askopenfilename(
                title=t("dialogs.relocate_audio_title", project=project_name, audio=original.name),
                filetypes=AUDIO_FILETYPES, parent=root, **options,
            )
            return [Path(selected).resolve()] if selected else []
        selected = filedialog.askopenfilenames(
            title=t("dialogs.add_comparison_audio", project=project_name),
            filetypes=AUDIO_FILETYPES,
            parent=root,
        )
        return [Path(value).resolve() for value in selected]
    finally:
        root.destroy()


def build_database_panel(
    parent, database, root, *,
    on_added: Callable[[list[str]], None] | None = None,
    on_renamed: Callable[[str, str], None] | None = None,
    on_deleted: Callable[[list[str]], None] | None = None,
) -> DatabasePanel:
    """Build project management controls inside the shared project window."""
    import tkinter as tk
    from tkinter import filedialog, messagebox, simpledialog, ttk

    ttk.Label(parent, text=t("dialogs.database_projects"), font=("Microsoft YaHei UI", 14, "bold")).pack(
        anchor="w", padx=12, pady=(8, 8)
    )

    container = ttk.Frame(parent)
    container.pack(fill="both", expand=True, padx=12)
    viewport = tk.Frame(container, bg="#202020", padx=1, pady=1)
    viewport.pack(fill="both", expand=True)
    scale = root.winfo_fpixels("1i") / 96
    indicator_size = round(19 * scale)
    style = ttk.Style(root)
    style.configure(
        "Database.Treeview", background="#ffffff", fieldbackground="#ffffff",
        foreground="#000000", rowheight=indicator_size + round(10 * scale),
    )
    style.map("Database.Treeview", background=[("selected", "#ffffff")], foreground=[("selected", "#000000")])
    style.configure("Database.Treeview.Heading", background="#f1f1f1", foreground="#000000", bordercolor="#202020")
    tree = ttk.Treeview(
        viewport, columns=("segment_count",), show="tree headings", selectmode="none",
        height=5, style="Database.Treeview",
    )
    tree.heading("#0", text=t("dialogs.project_name"), anchor="w")
    tree.heading("segment_count", text=t("dialogs.project_segment_count"), anchor="center")
    tree.column("#0", width=round(500 * scale), minwidth=round(120 * scale), stretch=True)
    tree.column("segment_count", width=round(130 * scale), minwidth=round(75 * scale), stretch=True, anchor="center")
    scrollbar = ttk.Scrollbar(viewport, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=scrollbar.set)
    tree.pack(side="left", fill="both", expand=True)
    scrollbar.pack(side="right", fill="y")
    selected: set[str] = set()
    empty_row_id: str | None = None
    last_snapshot: tuple[tuple[str, int, int], ...] = ()

    def checkbox_image(checked: bool):
        image = tk.PhotoImage(master=root, width=indicator_size, height=indicator_size)
        image.put("#1688ff" if checked else "#ffffff", to=(0, 0, indicator_size, indicator_size))
        for start, end in ((0, 1), (indicator_size - 1, indicator_size)):
            image.put("#202020", to=(start, 0, end, indicator_size))
            image.put("#202020", to=(0, start, indicator_size, end))
        if checked:
            points = (
                ((0.20, 0.52), (0.40, 0.72)),
                ((0.40, 0.72), (0.80, 0.28)),
            )
            stroke = max(2, round(2 * scale))
            for (x0, y0), (x1, y1) in points:
                steps = indicator_size
                for step in range(steps + 1):
                    fraction = step / steps
                    x = round((x0 + (x1 - x0) * fraction) * indicator_size)
                    y = round((y0 + (y1 - y0) * fraction) * indicator_size)
                    image.put(
                        "#000000", to=(max(1, x - stroke // 2), max(1, y - stroke // 2),
                                       min(indicator_size - 1, x + stroke // 2 + 1),
                                       min(indicator_size - 1, y + stroke // 2 + 1)),
                    )
        return image

    unchecked_image = checkbox_image(False)
    checked_image = checkbox_image(True)

    def scroll_projects(event) -> str:
        if getattr(event, "num", None) in (4, 5):
            direction = -1 if event.num == 4 else 1
        else:
            direction = -1 if event.delta > 0 else 1
        tree.yview_scroll(direction * 3, "units")
        return "break"

    for widget in (tree, scrollbar):
        widget.bind("<MouseWheel>", scroll_projects)
        widget.bind("<Button-4>", scroll_projects)
        widget.bind("<Button-5>", scroll_projects)

    def selected_names() -> list[str]:
        return [name for name in tree.get_children() if name in selected]

    def toggle(name: str) -> None:
        if name not in tree.get_children():
            return
        if name in selected:
            selected.remove(name)
        else:
            selected.add(name)
        tree.item(name, image=checked_image if name in selected else unchecked_image)

    def click_row(event):
        if tree.identify_region(event.x, event.y) in {"heading", "separator", "nothing"}:
            return None
        name = tree.identify_row(event.y)
        if name in tree.get_children() and name != empty_row_id:
            toggle(name)
            tree.focus_set()
            tree.focus(name)
            return "break"
        return None

    def toggle_focused(_event) -> str:
        name = tree.focus()
        if name and name != empty_row_id:
            toggle(name)
        return "break"

    tree.bind("<Button-1>", click_row)
    tree.bind("<space>", toggle_focused)

    def require_selection() -> list[str]:
        names = selected_names()
        if not names:
            messagebox.showinfo(t("common.select_project"), t("dialogs.select_one_or_more"), parent=root)
        return names

    def refresh(select: Iterable[str] = ()) -> None:
        nonlocal empty_row_id, last_snapshot
        newly_selected = tuple(select)
        remembered = set(selected_names()) | set(newly_selected)
        for child in tree.get_children():
            tree.delete(child)
        empty_row_id = None
        selected.clear()
        projects = database.list_projects()
        last_snapshot = tuple(
            (str(project["project_name"]), int(project["segment_count"]), int(project["revision"]))
            for project in projects
        )
        if not projects:
            empty_row_id = tree.insert("", "end", text=t("dialogs.database_empty"))
        for project in projects:
            name = str(project["project_name"])
            if name in remembered:
                selected.add(name)
            tree.insert(
                "", "end", iid=name, text=name, values=(project["segment_count"],),
                image=checked_image if name in selected else unchecked_image,
            )
        for name in reversed(newly_selected):
            if tree.exists(name):
                tree.see(name)
                break

    def import_projects() -> None:
        selected = filedialog.askopenfilenames(
            title=t("dialogs.select_project_databases"),
            filetypes=(("AudioRegistry SQLite", "*.sqlite3"),),
            parent=root,
        )
        if not selected:
            return
        try:
            inspected = [(Path(path).resolve(), database.inspect_project_file(path)) for path in selected]
            names = [str(metadata["project_name"]) for _, metadata in inspected]
            if len({name.casefold() for name in names}) != len(names):
                raise ValueError(t("dialogs.duplicate_import_names"))
            imported_names: list[str] = []
            skipped: list[str] = []
            for path, metadata in inspected:
                name = str(metadata["project_name"])
                replace = False
                if database.has_project(name):
                    replace = messagebox.askyesno(
                        t("dialogs.project_exists"),
                        t("dialogs.overwrite_project", name=name, file=path.name),
                        parent=root,
                    )
                    if not replace:
                        skipped.append(name)
                        continue
                imported_names.append(database.import_project_file(path, replace=replace))
            refresh()
            if on_added and imported_names:
                on_added(imported_names)
            detail = t("dialogs.import_count", count=len(imported_names))
            if skipped:
                detail += t("dialogs.import_skipped", names=", ".join(skipped))
            messagebox.showinfo(t("dialogs.import_complete"), detail, parent=root)
        except (OSError, ValueError, FileExistsError) as error:
            messagebox.showerror(t("dialogs.import_failed"), str(error), parent=root)

    def export_projects() -> None:
        names = require_selection()
        if not names:
            return
        directory = filedialog.askdirectory(title=t("dialogs.select_export_folder"), parent=root)
        if not directory:
            return
        destination = Path(directory).resolve()
        conflicts = [name for name in names if (destination / f"{name}.sqlite3").exists()]
        overwrite = False
        if conflicts:
            overwrite = messagebox.askyesno(
                t("dialogs.files_exist"),
                t("dialogs.overwrite_files", names="\n".join(f"{name}.sqlite3" for name in conflicts)),
                parent=root,
            )
            if not overwrite:
                return
        try:
            paths = database.export_projects(names, destination, overwrite=overwrite)
            messagebox.showinfo(
                t("dialogs.export_complete"),
                t("dialogs.export_count", count=len(paths), path=destination),
                parent=root,
            )
        except (OSError, ValueError, FileExistsError) as error:
            messagebox.showerror(t("dialogs.export_failed"), str(error), parent=root)

    def rename_project() -> None:
        names = selected_names()
        if len(names) != 1:
            messagebox.showinfo(t("dialogs.select_one_project"), t("dialogs.rename_one_detail"), parent=root)
            return
        old_name = names[0]
        new_name = simpledialog.askstring(
            t("dialogs.rename_project"),
            t("dialogs.rename_prompt", name=old_name),
            initialvalue=old_name,
            parent=root,
        )
        if new_name is None:
            return
        try:
            from .database import project_workspace_for, validate_project_name

            validated = validate_project_name(new_name)
            old_workspace = project_workspace_for(old_name, database.path.parent)
            new_workspace = project_workspace_for(validated, database.path.parent)
            move_workspace = old_workspace != new_workspace and old_workspace.exists()
            if move_workspace and new_workspace.exists():
                raise FileExistsError(t("dialogs.cache_exists", path=new_workspace))
            renamed = database.rename_project(old_name, validated)
            workspace_warning = ""
            if move_workspace:
                try:
                    old_workspace.rename(new_workspace)
                except OSError as error:
                    workspace_warning = t("dialogs.cache_move_failed", error=error)
            refresh([renamed])
            if on_renamed:
                on_renamed(old_name, renamed)
            messagebox.showinfo(
                t("dialogs.rename_complete"),
                t("dialogs.rename_complete_detail", old=old_name, new=renamed, warning=workspace_warning),
                parent=root,
            )
        except (OSError, ValueError, FileExistsError) as error:
            messagebox.showerror(t("dialogs.rename_failed"), str(error), parent=root)

    def delete_projects() -> None:
        names = require_selection()
        if not names:
            return
        if not messagebox.askyesno(
            t("dialogs.confirm_delete"),
            t("dialogs.delete_detail", names="\n".join(names)),
            icon="warning",
            parent=root,
        ):
            return
        try:
            count = database.delete_projects(names)
            refresh()
            if on_deleted:
                on_deleted(names)
            messagebox.showinfo(
                t("dialogs.delete_complete"),
                t("dialogs.delete_count", count=count),
                parent=root,
            )
        except (OSError, ValueError) as error:
            messagebox.showerror(t("dialogs.delete_failed"), str(error), parent=root)

    buttons = ttk.Frame(parent)
    buttons.pack(fill="x", padx=12, pady=10)
    ttk.Button(buttons, text=t("dialogs.import"), command=import_projects).pack(side="left")
    ttk.Button(buttons, text=t("common.export"), command=export_projects).pack(side="left", padx=(8, 0))
    ttk.Button(buttons, text=t("dialogs.rename_button"), command=rename_project).pack(side="left", padx=(8, 0))
    ttk.Button(buttons, text=t("common.delete"), command=delete_projects).pack(side="left", padx=(8, 0))
    refresh()

    poll_id: str | None = None

    def poll_changes() -> None:
        nonlocal poll_id
        current = tuple(
            (str(project["project_name"]), int(project["segment_count"]), int(project["revision"]))
            for project in database.list_projects()
        )
        if current != last_snapshot:
            refresh()
        poll_id = root.after(1200, poll_changes)

    def stop_polling(event) -> None:
        if event.widget is root and poll_id is not None:
            root.after_cancel(poll_id)

    root.bind("<Destroy>", stop_polling, add="+")
    poll_id = root.after(1200, poll_changes)
    return DatabasePanel(refresh=refresh, selected_names=selected_names)
