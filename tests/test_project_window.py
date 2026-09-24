import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from tkinter import ttk
from unittest.mock import patch

from audio_registry.database import ProjectDatabase
from audio_registry.i18n import get_locale, set_locale, t
from audio_registry.project_window import show_project_dialog


class ProjectWindowTests(unittest.TestCase):
    def test_next_uses_current_database_selection(self):
        previous_locale = get_locale()
        set_locale("zh-CN")
        try:
            with tempfile.TemporaryDirectory() as directory:
                database = ProjectDatabase(Path(directory) / "registry.sqlite3")
                audio = Path(directory) / "sample.wav"
                audio.write_bytes(b"RIFF")
                database.create_project("existing", audio)
                errors: list[BaseException] = []
                real_tk = tk.Tk

                def open_window(*args, **kwargs):
                    root = real_tk(*args, **kwargs)

                    def descendants(widget):
                        for child in widget.winfo_children():
                            yield child
                            yield from descendants(child)

                    def button(key):
                        return next(
                            widget for widget in descendants(root)
                            if isinstance(widget, ttk.Button) and widget.cget("text") == t(key)
                        )

                    def database_tree():
                        return next(
                            widget for widget in descendants(root)
                            if isinstance(widget, ttk.Treeview) and "segment_count" in widget.cget("columns")
                        )

                    def click_project(name):
                        tree = database_tree()
                        tree.see(name)
                        root.update_idletasks()
                        x, y, _width, height = tree.bbox(name, "#0")
                        tree.event_generate("<Button-1>", x=x + 8, y=y + height // 2)

                    def enter(name):
                        audio_entry, project_entry = (
                            widget for widget in descendants(root) if isinstance(widget, ttk.Entry)
                        )
                        audio_entry.delete(0, "end")
                        audio_entry.insert(0, str(audio))
                        project_entry.delete(0, "end")
                        project_entry.insert(0, name)

                    def interact():
                        try:
                            enter("new_single")
                            button("dialogs.create_project").invoke()
                            tree = database_tree()
                            self.assertEqual(root.title(), "AudioRegistry")
                            self.assertEqual(tree.heading("#0", "text"), t("dialogs.project_name"))
                            self.assertEqual(tree.heading("segment_count", "text"), t("dialogs.project_segment_count"))
                            self.assertNotEqual(tree.item("new_single", "image"), tree.item("existing", "image"))
                            root.update_idletasks()
                            name_width = tree.column("#0", "width")
                            count_width = tree.column("segment_count", "width")
                            separator = next(
                                x for x in range(name_width - 8, name_width + 9)
                                if tree.identify_region(x, 8) == "separator"
                            )
                            tree.event_generate("<ButtonPress-1>", x=separator, y=8)
                            tree.event_generate("<B1-Motion>", x=separator - 100, y=8)
                            tree.event_generate("<ButtonRelease-1>", x=separator - 100, y=8)
                            root.update_idletasks()
                            self.assertLess(tree.column("#0", "width"), name_width)
                            self.assertGreater(tree.column("segment_count", "width"), count_width)

                            for name in ("new_batch_one", "new_batch_two"):
                                enter(name)
                                button("dialogs.save_queue").invoke()
                            button("dialogs.create_batch").invoke()
                            style = ttk.Style(root)
                            self.assertEqual(style.lookup("Database.Treeview", "background"), "#ffffff")
                            self.assertEqual(tree.item("new_batch_one", "values"), ("0",))
                            self.assertEqual(tree.item("new_batch_one", "image"), tree.item("new_single", "image"))
                            click_project("new_single")
                            click_project("new_batch_two")
                            click_project("existing")
                            button("dialogs.next_step").invoke()
                        except BaseException as error:
                            errors.append(error)
                            root.destroy()

                    root.after(100, interact)
                    return root

                try:
                    with patch.object(tk, "Tk", side_effect=open_window):
                        selected = show_project_dialog(database, advance=True)
                except tk.TclError as error:
                    self.skipTest(f"Tk display unavailable: {error}")
                if errors:
                    raise errors[0]
                self.assertEqual(selected, ["existing", "new_batch_one"])
        finally:
            set_locale(previous_locale)


if __name__ == "__main__":
    unittest.main()
