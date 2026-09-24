from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path

from .dialogs import SUBTITLE_FILETYPES, ProcessDialogResult
from .i18n import t


def _new_root(title: str, minimum: tuple[int, int]):
    import tkinter as tk

    root = tk.Tk()
    root.title(title)
    root.attributes("-topmost", True)
    root.resizable(True, True)
    root.minsize(*minimum)
    return root


def show_segment_dialog(
    assets: Iterable[Mapping[str, object]],
    *,
    preferred_projects: Iterable[str] = (),
    initial_language: str = "auto",
    initial_start_padding: float = 0.0,
    initial_end_padding: float = 0.2,
    initial_subtitle: str | Path | None = None,
    on_defaults_change: Callable[[str, float, float], object] | None = None,
) -> list[ProcessDialogResult] | None:
    """Choose existing project/audio pairs for optional segmentation and transcription."""
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    from faster_whisper.tokenizer import _LANGUAGE_CODES

    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    for raw in assets:
        row = dict(raw)
        grouped[str(row["project_name"])].append(row)

    root = _new_root(t("dialogs.segment_window"), (760, 560))
    result: list[ProcessDialogResult] | None = None
    preferred = {name.casefold() for name in preferred_projects}
    enabled: dict[str, tk.BooleanVar] = {}
    selected_audio: dict[str, tk.StringVar] = {}
    audio_maps: dict[str, dict[str, dict[str, object]]] = {}

    language = tk.StringVar(value=initial_language)
    start_padding = tk.StringVar(value=f"{initial_start_padding:g}")
    end_padding = tk.StringVar(value=f"{initial_end_padding:g}")
    subtitle = tk.StringVar(
        value=str(Path(initial_subtitle).resolve()) if initial_subtitle else ""
    )
    persist_timer: str | None = None

    def persist_valid_defaults() -> None:
        nonlocal persist_timer
        persist_timer = None
        if on_defaults_change is None:
            return
        try:
            language_code = language.get().strip().casefold()
            start = float(start_padding.get())
            end = float(end_padding.get())
            if language_code != "auto" and language_code not in _LANGUAGE_CODES:
                return
            if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end < 0:
                return
        except ValueError:
            return
        on_defaults_change(language_code, start, end)

    def schedule_defaults(*_args) -> None:
        nonlocal persist_timer
        if persist_timer is not None:
            root.after_cancel(persist_timer)
        persist_timer = root.after(350, persist_valid_defaults)

    for variable in (language, start_padding, end_padding):
        variable.trace_add("write", schedule_defaults)

    body = ttk.Frame(root, padding=20)
    body.pack(fill="both", expand=True)
    body.columnconfigure(0, weight=1)
    body.rowconfigure(1, weight=1)
    ttk.Label(
        body, text=t("dialogs.segment_title"), font=("Microsoft YaHei UI", 14, "bold")
    ).grid(row=0, column=0, sticky="w", pady=(0, 12))

    list_frame = ttk.LabelFrame(body, text=t("dialogs.segment_projects"), padding=8)
    list_frame.grid(row=1, column=0, sticky="nsew", pady=(0, 12))
    list_frame.columnconfigure(0, weight=1)
    list_frame.rowconfigure(0, weight=1)
    canvas = tk.Canvas(list_frame, highlightthickness=0)
    scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=canvas.yview)
    rows_frame = ttk.Frame(canvas)
    window = canvas.create_window((0, 0), window=rows_frame, anchor="nw")
    canvas.configure(yscrollcommand=scrollbar.set)
    canvas.grid(row=0, column=0, sticky="nsew")
    scrollbar.grid(row=0, column=1, sticky="ns")
    rows_frame.columnconfigure(1, weight=1)
    rows_frame.bind(
        "<Configure>", lambda _event: canvas.configure(scrollregion=canvas.bbox("all"))
    )
    canvas.bind("<Configure>", lambda event: canvas.itemconfigure(window, width=event.width))

    for row_index, project_name in enumerate(sorted(grouped, key=str.casefold)):
        available = [
            row for row in grouped[project_name] if Path(str(row["audio_path"])).is_file()
        ]
        display_map: dict[str, dict[str, object]] = {}
        for asset in available:
            display = f'{asset.get("name") or Path(str(asset["audio_path"])).stem} — {asset["audio_path"]}'
            display_map[display] = asset
        audio_maps[project_name] = display_map
        enabled[project_name] = tk.BooleanVar(
            value=bool(display_map) and project_name.casefold() in preferred
        )
        selected_audio[project_name] = tk.StringVar(
            value=next(iter(display_map), "")
        )
        check = ttk.Checkbutton(
            rows_frame, text=project_name, variable=enabled[project_name]
        )
        check.grid(row=row_index, column=0, sticky="w", padx=(4, 12), pady=5)
        if not display_map:
            check.state(["disabled"])
        combo = ttk.Combobox(
            rows_frame,
            textvariable=selected_audio[project_name],
            values=tuple(display_map),
            state="readonly" if display_map else "disabled",
        )
        combo.grid(row=row_index, column=1, sticky="ew", pady=5)

    if not grouped:
        ttk.Label(rows_frame, text=t("dialogs.no_segment_projects")).grid(
            row=0, column=0, columnspan=2, sticky="w", padx=8, pady=12
        )

    shortcuts = ttk.Frame(list_frame)
    shortcuts.grid(row=1, column=0, columnspan=2, sticky="w", pady=(8, 0))
    ttk.Button(
        shortcuts,
        text=t("common.all"),
        command=lambda: [variable.set(True) for name, variable in enabled.items() if audio_maps[name]],
    ).pack(side="left")
    ttk.Button(
        shortcuts,
        text=t("common.none"),
        command=lambda: [variable.set(False) for variable in enabled.values()],
    ).pack(side="left", padx=(8, 0))

    parameters = ttk.LabelFrame(body, text=t("dialogs.segment_settings"), padding=10)
    parameters.grid(row=2, column=0, sticky="ew")
    parameters.columnconfigure(1, weight=1)
    ttk.Label(parameters, text=t("dialogs.transcription_language")).grid(
        row=0, column=0, sticky="w", padx=(0, 12), pady=6
    )
    ttk.Combobox(
        parameters, textvariable=language, values=("auto", "zh", "en", "ja", "ko"), width=14
    ).grid(row=0, column=1, sticky="w", pady=6)
    ttk.Label(parameters, text=t("dialogs.padding")).grid(
        row=1, column=0, sticky="w", padx=(0, 12), pady=6
    )
    padding_row = ttk.Frame(parameters)
    padding_row.grid(row=1, column=1, sticky="w", pady=6)
    ttk.Entry(padding_row, textvariable=start_padding, width=10).pack(side="left")
    ttk.Label(padding_row, text=f" {t('dialogs.seconds')}   /   ").pack(side="left")
    ttk.Entry(padding_row, textvariable=end_padding, width=10).pack(side="left")
    ttk.Label(padding_row, text=f" {t('dialogs.seconds')}").pack(side="left")
    ttk.Label(parameters, text=t("dialogs.subtitle_optional")).grid(
        row=2, column=0, sticky="w", padx=(0, 12), pady=6
    )
    ttk.Entry(parameters, textvariable=subtitle).grid(row=2, column=1, sticky="ew", pady=6)

    def browse_subtitle() -> None:
        selected = filedialog.askopenfilename(
            title=t("dialogs.select_subtitle"), filetypes=SUBTITLE_FILETYPES, parent=root
        )
        if selected:
            subtitle.set(str(Path(selected).resolve()))

    ttk.Button(parameters, text=t("dialogs.browse"), command=browse_subtitle).grid(
        row=2, column=2, padx=(8, 0), pady=6
    )
    ttk.Label(parameters, text=t("dialogs.segment_help"), foreground="#555555").grid(
        row=3, column=0, columnspan=3, sticky="w", pady=(8, 0)
    )

    buttons = ttk.Frame(body)
    buttons.grid(row=3, column=0, sticky="e", pady=(12, 0))

    def finish(skip: bool = False) -> None:
        nonlocal result
        if skip:
            persist_valid_defaults()
            result = []
            root.destroy()
            return
        try:
            language_code = language.get().strip().casefold()
            if language_code != "auto" and language_code not in _LANGUAGE_CODES:
                raise ValueError(t("dialogs.language_invalid"))
            start = float(start_padding.get())
            end = float(end_padding.get())
            if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end < 0:
                raise ValueError(t("dialogs.padding_invalid"))
            selected_rows: list[tuple[str, dict[str, object]]] = []
            for project_name, variable in enabled.items():
                if not variable.get():
                    continue
                asset = audio_maps[project_name].get(selected_audio[project_name].get())
                if asset is not None:
                    selected_rows.append((project_name, asset))
            subtitle_text = subtitle.get().strip()
            subtitle_path = Path(subtitle_text).resolve() if subtitle_text else None
            if subtitle_path is not None:
                if len(selected_rows) != 1:
                    raise ValueError(t("dialogs.subtitle_single_project"))
                if not subtitle_path.is_file():
                    raise ValueError(t("dialogs.subtitle_missing"))
                if subtitle_path.suffix.casefold() not in {".srt", ".vtt", ".ass", ".ssa"}:
                    raise ValueError(t("dialogs.subtitle_unsupported"))
        except (OSError, ValueError) as error:
            messagebox.showerror(t("dialogs.invalid_parameters"), str(error), parent=root)
            return
        if persist_timer is not None:
            root.after_cancel(persist_timer)
        if on_defaults_change is not None:
            on_defaults_change(language_code, start, end)
        result = [
            ProcessDialogResult(
                project_name,
                Path(str(asset["audio_path"])).resolve(),
                language_code,
                start,
                end,
                subtitle_path,
            )
            for project_name, asset in selected_rows
        ]
        root.destroy()

    ttk.Button(buttons, text=t("dialogs.skip_segment"), command=lambda: finish(True)).pack(
        side="left"
    )
    ttk.Button(buttons, text=t("dialogs.start_segment"), command=finish).pack(
        side="left", padx=(8, 0)
    )
    root.protocol("WM_DELETE_WINDOW", root.destroy)
    root.mainloop()
    return result
