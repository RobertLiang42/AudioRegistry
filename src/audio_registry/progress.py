"""Terminal progress: use counts only when the backend supplies real counts."""
from contextlib import contextmanager
from time import perf_counter

from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)

from .i18n import t


@contextmanager
def timed_stage(description):
    console = Console(stderr=True)
    started = perf_counter()
    console.print(f"{description}...")
    with console.status(description, spinner="line"):
        yield
    console.print(t("progress.done", description=description, seconds=f"{perf_counter() - started:.2f}"))


class DiarizationProgress:
    def __enter__(self):
        self.progress = Progress(
            SpinnerColumn("line"), TextColumn("{task.description}"), BarColumn(),
            TaskProgressColumn(), TimeElapsedColumn(), TimeRemainingColumn(),
        )
        self.progress.start()
        self.task = self.progress.add_task(t("progress.speaker_loading"), total=None)
        self.stage = None
        return self

    def __call__(self, step_name, step_artifact=None, *, file=None, total=None, completed=None):
        labels = {"segmentation": t("progress.segmentation"),
                  "embeddings": t("progress.embeddings")}
        if total is not None and completed is not None:
            if self.stage != step_name:
                self.progress.reset(self.task, total=total, description=labels.get(step_name, step_name))
                self.stage = step_name
            self.progress.update(self.task, completed=completed, total=total)
        else:
            next_stage = {
                "segmentation": t("progress.counting"),
                "speaker_counting": t("progress.embedding_prepare"),
                "embeddings": t("progress.clustering"),
                "discrete_diarization": t("progress.finalizing"),
            }.get(step_name, step_name)
            # Rich.reset(total=None) retains the previous total. A new task
            # is required for an honestly indeterminate clustering stage.
            self.progress.remove_task(self.task)
            self.task = self.progress.add_task(next_stage, total=None)
            self.stage = next_stage

    def __exit__(self, exc_type, exc_value, traceback):
        if exc_type is None:
            self.progress.update(self.task, description=t("progress.diarization_complete"), total=1, completed=1)
        else:
            self.progress.update(self.task, description=t("progress.diarization_failed"))
        self.progress.stop()
