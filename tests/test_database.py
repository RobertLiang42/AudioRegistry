import json
import re
import sqlite3
import tempfile
import unittest
from pathlib import Path

from audio_registry.database import ProjectDatabase, database_path_for, project_workspace_for
from audio_registry.i18n import t
from audio_registry.models import Segment


class ProjectDatabaseTests(unittest.TestCase):
    def test_project_can_be_renamed_without_losing_related_data(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audio = root / "movie.wav"
            audio.touch()
            database = ProjectDatabase(root / "output/project.sqlite3")
            database.create_review("旧项目", audio, [Segment(1, 2, "角色甲", "台词")])
            project = database.load_assembly(["旧项目"])["projects"][0]
            row = project["segments"][0]
            database.save_assembly([{
                "project_name": "旧项目", "revision": project["revision"],
                "tags": ["训练集", "精选"], "offsets": {},
                "items": [{"id": row["id"], "text": row["text"], "tag": "精选",
                           "note": "保留备注", "selected_variant_id": row["selected_variant_id"]}],
            }])

            self.assertEqual(database.rename_project("旧项目", "新项目"), "新项目")
            self.assertFalse(database.has_project("旧项目"))
            renamed = database.load_assembly(["新项目"])["projects"][0]
            self.assertEqual(renamed["segments"][0]["text"], "台词")
            self.assertEqual(renamed["segments"][0]["tag"], "精选")
            self.assertEqual(renamed["segments"][0]["note"], "保留备注")
            self.assertEqual(database.project_name_for_audio(audio), "新项目")

    def test_project_rename_rejects_an_existing_name(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = ProjectDatabase(root / "output/project.sqlite3")
            for name in ("A", "B"):
                audio = root / f"{name}.wav"
                audio.touch()
                database.create_review(name, audio, [Segment(0, 1)])
            with self.assertRaises(FileExistsError):
                database.rename_project("A", "B")
            self.assertEqual([row["project_name"] for row in database.list_projects()], ["A", "B"])

    def test_round_trip_preserves_review_fields_without_browser_preferences(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audio = root / "movie.wav"
            audio.write_bytes(b"audio")
            database = ProjectDatabase(database_path_for(root / "output"))
            document = database.create_review(
                "S01E01", audio,
                [Segment(1.25, 2.75, "角色甲", "原文字")],
            )
            document["segments"][0].update(
                text="校对文字",
                manual_text=True,
                origin_ids=["OLD-1"],
            )
            document["ui_preferences"] = {
                "selected_speakers": ["角色甲"],
                "selected_segment_ids": [document["segments"][0]["id"]],
                "primary_segment_id": document["segments"][0]["id"],
                "min_duration": 0.5,
                "show_hidden": True,
            }
            saved = database.save_review("S01E01", document, expected_revision=1)
            loaded = database.load_review("S01E01")
            self.assertEqual(loaded, saved)
            self.assertNotIn("ui_preferences", loaded)
            self.assertEqual(loaded["segments"][0]["origin_ids"], ["OLD-1"])
            self.assertEqual(database.snapshot_count(audio), 1)

            connection = sqlite3.connect(database.path)
            try:
                stored = connection.execute("SELECT ui_preferences_json FROM sources").fetchone()[0]
                snapshots = [row[0] for row in connection.execute(
                    "SELECT document_json FROM review_snapshots"
                ).fetchall()]
            finally:
                connection.close()
            self.assertIsNone(stored)
            self.assertTrue(all("ui_preferences" not in value for value in snapshots))

    def test_optimistic_revision_check_rejects_stale_save(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audio = root / "movie.wav"
            audio.touch()
            database = ProjectDatabase(root / "output/project.sqlite3")
            document = database.create_review("movie", audio, [Segment(0, 1)])
            document["segments"][0]["text"] = "changed"
            database.save_review("movie", document, expected_revision=1)
            with self.assertRaisesRegex(
                ValueError, re.escape(t("errors.revision_conflict", expected=1, actual=2))
            ):
                database.save_review("movie", document, expected_revision=1)

    def test_browser_preferences_only_save_does_not_change_project_counter(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audio = root / "movie.wav"
            audio.touch()
            database = ProjectDatabase(root / "project.sqlite3")
            document = database.create_review("movie", audio, [Segment(0, 1)])
            counters = database.project_update_counters(["movie"])
            document["ui_preferences"] = {"selected_speakers": [], "selected_tags": []}
            saved = database.save_review("movie", document, expected_revision=1)
            self.assertNotIn("ui_preferences", saved)
            self.assertEqual(saved["revision"], 1)
            self.assertEqual(database.snapshot_count("movie"), 0)
            self.assertEqual(database.project_update_counters(["movie"]), counters)

    def test_legacy_browser_preferences_are_cleaned_without_counter_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audio = root / "movie.wav"
            audio.touch()
            database = ProjectDatabase(root / "project.sqlite3")
            document = database.create_review("movie", audio, [Segment(0, 1)])
            document["ui_preferences"] = {"selected_speakers": [], "show_hidden": True}
            with database._connection() as connection:
                source_id = connection.execute("SELECT id FROM sources").fetchone()[0]
                connection.execute("UPDATE sources SET ui_preferences_json=?", (json.dumps(document["ui_preferences"]),))
                connection.execute("INSERT INTO review_snapshots VALUES (?, ?, ?, ?)",
                                   (source_id, 1, document["updated_at"], json.dumps(document)))
                connection.commit()
            counters = database.project_update_counters(["movie"])
            reopened = ProjectDatabase(database.path)
            self.assertEqual(reopened.project_update_counters(["movie"]), counters)
            with reopened._connection() as connection:
                self.assertIsNone(connection.execute("SELECT ui_preferences_json FROM sources").fetchone()[0])
                snapshot = json.loads(connection.execute("SELECT document_json FROM review_snapshots").fetchone()[0])
                self.assertNotIn("ui_preferences", snapshot)

    def test_reanalysis_replaces_rows_and_snapshots_previous_review(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audio = root / "movie.wav"
            audio.touch()
            database = ProjectDatabase(root / "output/project.sqlite3")
            database.create_review("movie", audio, [Segment(0, 1, "A", "old")])
            database.create_review("movie", audio, [Segment(2, 3, "B", "new")])
            loaded = database.load_review("movie")
            self.assertEqual(loaded["segments"][0]["text"], "new")
            self.assertEqual(len(database.list_projects()), 1)
            self.assertEqual(database.snapshot_count(audio), 1)

    def test_empty_project_can_bind_audio_before_segmentation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audio = root / "movie.wav"
            audio.touch()
            database = ProjectDatabase(root / "project.sqlite3")
            document = database.create_project("movie", audio)
            self.assertEqual(document["segments"], [])
            assets = database.list_audio_assets("movie")
            self.assertEqual(len(assets), 1)
            self.assertTrue(Path(assets[0]["audio_path"]).samefile(audio))
            with self.assertRaises(FileExistsError):
                database.create_project("movie", audio)

    def test_processing_uses_the_chosen_bound_audio_for_new_segments(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = root / "original.wav"
            processed = root / "processed.wav"
            original.touch()
            processed.touch()
            database = ProjectDatabase(root / "project.sqlite3")
            database.create_project("movie", original)
            database.register_audio_asset("movie", processed)
            database.create_review("movie", processed, [Segment(1, 2, "A", "text")])
            project = database.load_assembly(["movie"])["projects"][0]
            chosen = next(
                row for row in project["variants"]
                if Path(row["audio_path"]).samefile(processed)
            )
            self.assertEqual(project["segments"][0]["selected_variant_id"], chosen["id"])

    def test_project_identity_is_independent_from_audio_asset_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = root / "S01E01-raw.wav"
            processed = root / "elsewhere/S01E01-process.wav"
            original.write_bytes(b"raw")
            processed.parent.mkdir()
            processed.write_bytes(b"processed")
            database = ProjectDatabase(root / "output/project.sqlite3")
            database.create_review("S01E01", original, [Segment(1, 2, "A", "text")])
            asset = database.register_audio_asset("S01E01", processed, duration_seconds=10)
            updated = database.set_audio_offset("S01E01", processed, 0.125)
            self.assertEqual(database.load_review("S01E01")["segments"][0]["start"], 1)
            self.assertEqual(updated["id"], asset["id"])
            self.assertEqual(updated["offset_seconds"], 0.125)
            self.assertEqual(database.project_name_for_audio(processed), "S01E01")

    def test_source_audio_can_be_reused_by_projects_with_different_timelines(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audio = root / "movie.wav"
            audio.touch()
            database = ProjectDatabase(root / "output/project.sqlite3")
            database.create_review("版本一", audio, [Segment(0, 1, "A", "第一版")])
            database.create_review("版本二", audio, [Segment(2, 4, "B", "第二版")])
            self.assertEqual(database.load_review("版本一")["segments"][0]["text"], "第一版")
            self.assertEqual(database.load_review("版本二")["segments"][0]["start"], 2)
            self.assertEqual(
                [row["project_name"] for row in database.list_projects()], ["版本一", "版本二"]
            )
            with self.assertRaises(ValueError):
                database.project_name_for_audio(audio)

    def test_assembly_tags_are_derived_from_item_text_and_choices_default_to_first_audio(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = ProjectDatabase(root / "main.sqlite3")
            for name in ("A", "B"):
                audio = root / f"{name}.wav"
                audio.write_bytes(name.encode())
                database.create_review(name, audio, [Segment(1, 3, "同名角色", f"{name}文字")])
            state = database.load_assembly(["A", "B"])
            self.assertEqual(state["projects"][0]["tags"], ["1"])
            self.assertTrue(Path(state["projects"][0]["variants"][0]["audio_path"]).samefile(root / "A.wav"))
            self.assertEqual(
                state["projects"][0]["segments"][0]["selected_variant_id"],
                state["projects"][0]["variants"][0]["id"],
            )
            project = state["projects"][0]
            row = project["segments"][0]
            database.save_assembly([{
                "project_name": "A", "revision": project["revision"], "offsets": {},
                "items": [{"id": row["id"], "text": row["text"], "tag": "噪音", "note": "只属于 A", "selected_variant_id": row["selected_variant_id"]}],
            }])
            reloaded = database.load_assembly(["A", "B"])["projects"]
            self.assertEqual(reloaded[0]["tags"], ["噪音"])
            self.assertEqual(reloaded[0]["segments"][0]["note"], "只属于 A")
            self.assertEqual(reloaded[1]["tags"], ["1"])

    def test_relocating_two_audio_bindings_preserves_choices_and_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = root / "A.wav"
            second = root / "B.wav"
            moved_a = root / "new-A.wav"
            moved_b = root / "new-B.wav"
            for audio in (original, second, moved_a, moved_b):
                audio.touch()
            database = ProjectDatabase(root / "main.sqlite3")
            database.create_review("movie", original, [Segment(0, 1, "A", "one"), Segment(2, 3, "B", "two")])
            b = database.register_audio_asset("movie", second, duration_seconds=10)
            database.set_audio_offset("movie", second, 0.375)
            project = database.load_assembly(["movie"])["projects"][0]
            a = project["variants"][0]
            rows = project["segments"]
            database.save_assembly([{
                "project_name": "movie", "revision": project["revision"],
                "tags": ["训练集", "精选"], "offsets": {},
                "items": [
                    {"id": rows[0]["id"], "text": "one", "tag": "精选", "note": "keep A", "selected_variant_id": a["id"]},
                    {"id": rows[1]["id"], "text": "two", "tag": "训练集", "note": "keep B", "selected_variant_id": b["id"]},
                ],
            }])
            before = database.load_assembly(["movie"])["projects"][0]
            counters = database.project_update_counters(["movie"])
            original.unlink()
            second.unlink()
            database.relocate_audio_asset("movie", a["id"], moved_a, duration_seconds=20)
            database.relocate_audio_asset("movie", b["id"], moved_b, duration_seconds=30)
            after = database.load_assembly(["movie"])["projects"][0]
            self.assertEqual(after["segments"], before["segments"])
            self.assertEqual(after["tags"], before["tags"])
            self.assertEqual([v["id"] for v in after["variants"]], [a["id"], b["id"]])
            self.assertEqual([v["name"] for v in after["variants"]], [v["name"] for v in before["variants"]])
            self.assertEqual(after["variants"][1]["offset_seconds"], 0.375)
            self.assertEqual(after["variants"][1]["duration_seconds"], 30)
            self.assertEqual(database.load_review("movie")["audio_path"], str(moved_a.resolve()))
            self.assertNotEqual(database.project_update_counters(["movie"]), counters)
            # Available bindings can also be relocated; shared paths across projects remain legal.
            database.create_review("other", moved_b, [])
            database.relocate_audio_asset("movie", b["id"], moved_b)
            with self.assertRaises(ValueError):
                database.relocate_audio_asset("movie", a["id"], moved_b)
            with self.assertRaises(FileNotFoundError):
                database.relocate_audio_asset("other", a["id"], moved_a)
            with self.assertRaises(FileNotFoundError):
                database.relocate_audio_asset("movie", a["id"], original)
            self.assertEqual(database.load_assembly(["movie"])["projects"][0]["segments"], before["segments"])

    def test_deleting_selected_audio_preserves_metadata_and_marks_row_unassigned(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first_audio = root / "movie-A.wav"
            second_audio = root / "movie-B.wav"
            third_audio = root / "movie-C.wav"
            for audio in (first_audio, second_audio, third_audio):
                audio.touch()
            database = ProjectDatabase(root / "main.sqlite3")
            database.create_review(
                "movie",
                first_audio,
                [Segment(0, 1, "A", "one"), Segment(2, 3, "A", "two")],
            )
            second = database.register_audio_asset("movie", second_audio, duration_seconds=10)
            third = database.register_audio_asset("movie", third_audio, duration_seconds=10)
            database.set_audio_offset("movie", second_audio, 0.375)
            project = database.load_assembly(["movie"])["projects"][0]
            rows = project["segments"]
            database.save_assembly([{
                "project_name": "movie", "revision": project["revision"],
                "tags": ["训练集", "精选"], "offsets": {},
                "items": [
                    {"id": rows[0]["id"], "text": rows[0]["text"], "tag": "精选", "note": "keep", "selected_variant_id": second["id"]},
                    {"id": rows[1]["id"], "text": rows[1]["text"], "tag": "训练集", "note": "other", "selected_variant_id": third["id"]},
                ],
            }])

            database.delete_audio_asset("movie", second["id"])
            reloaded = database.load_assembly(["movie"])["projects"][0]
            self.assertNotIn(second["id"], {variant["id"] for variant in reloaded["variants"]})
            self.assertIsNone(reloaded["segments"][0]["selected_variant_id"])
            self.assertEqual((reloaded["segments"][0]["tag"], reloaded["segments"][0]["note"]), ("精选", "keep"))
            self.assertEqual(reloaded["segments"][1]["selected_variant_id"], third["id"])

    def test_deleting_implicit_first_audio_does_not_silently_choose_new_first(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first_audio = root / "movie-A.wav"
            second_audio = root / "movie-B.wav"
            first_audio.touch()
            second_audio.touch()
            database = ProjectDatabase(root / "main.sqlite3")
            database.create_review(
                "movie", first_audio,
                [Segment(0, 1, "A", "one"), Segment(2, 3, "A", "two")],
            )
            database.register_audio_asset("movie", second_audio, duration_seconds=10)
            project = database.load_assembly(["movie"])["projects"][0]
            first_id = project["variants"][0]["id"]
            self.assertTrue(all(row["selected_variant_id"] == first_id for row in project["segments"]))

            database.delete_audio_asset("movie", first_id)
            reloaded = database.load_assembly(["movie"])["projects"][0]
            self.assertEqual(len(reloaded["variants"]), 1)
            self.assertTrue(all(row["selected_variant_id"] is None for row in reloaded["segments"]))

    def test_assembly_text_save_increments_revision_and_rejects_stale_page(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audio = root / "movie.wav"
            audio.touch()
            database = ProjectDatabase(root / "main.sqlite3")
            database.create_review("movie", audio, [Segment(0, 1, "A", "old")])
            project = database.load_assembly(["movie"])["projects"][0]
            row = project["segments"][0]
            payload = {"project_name":"movie", "revision":project["revision"], "tags":["训练集"], "offsets":{}, "items":[{"id":row["id"], "text":"new", "tag":"训练集", "note":"", "selected_variant_id":row["selected_variant_id"]}]}
            revisions = database.save_assembly([payload])
            self.assertEqual(revisions["movie"], 2)
            self.assertEqual(database.load_review("movie")["segments"][0]["text"], "new")
            with self.assertRaises(ValueError):
                database.save_assembly([payload])

    def test_assembly_speaker_save_updates_review_and_revision(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audio = root / "audio.wav"
            audio.touch()
            database = ProjectDatabase(root / "projects.sqlite3")
            database.create_review("movie", audio, [Segment(0, 1, "Speaker_01", "text")])
            assembly = database.load_assembly(["movie"])["projects"][0]
            row = assembly["segments"][0]
            revisions = database.save_assembly([{
                "project_name": "movie", "revision": assembly["revision"],
                "tags": assembly["tags"], "offsets": {},
                "items": [{**row, "speaker": "角色甲"}],
            }])
            self.assertEqual(revisions["movie"], 2)
            self.assertEqual(database.load_review("movie")["segments"][0]["speaker"], "角色甲")

    def test_assembly_tags_can_be_renamed_and_deleted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audio = root / "movie.wav"
            audio.touch()
            database = ProjectDatabase(root / "main.sqlite3")
            database.create_review("movie", audio, [Segment(0, 1, "A", "text")])
            project = database.load_assembly(["movie"])["projects"][0]
            row = project["segments"][0]
            database.save_assembly([{
                "project_name":"movie", "revision":project["revision"], "tags":["训练集", "噪音"], "offsets":{},
                "items":[{"id":row["id"], "text":"text", "tag":"噪音", "note":"", "selected_variant_id":row["selected_variant_id"]}],
            }])
            current = database.load_assembly(["movie"])["projects"][0]
            database.save_assembly([{
                "project_name":"movie", "revision":current["revision"], "tags":["精选"], "offsets":{},
                "items":[{"id":current["segments"][0]["id"], "text":"text", "tag":"精选", "note":"", "selected_variant_id":current["segments"][0]["selected_variant_id"]}],
            }])
            reloaded = database.load_assembly(["movie"])["projects"][0]
            self.assertEqual(reloaded["tags"], ["精选"])
            self.assertEqual(reloaded["segments"][0]["tag"], "精选")

    def test_review_boundary_save_preserves_assembly_metadata_for_stable_id(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audio = root / "movie.wav"
            audio.touch()
            database = ProjectDatabase(root / "main.sqlite3")
            database.create_review("movie", audio, [Segment(0, 1, "A", "text")])
            project = database.load_assembly(["movie"])["projects"][0]
            row = project["segments"][0]
            database.save_assembly([{"project_name":"movie", "revision":1, "tags":["训练集", "保留"], "offsets":{}, "items":[{"id":row["id"], "text":"text", "tag":"保留", "note":"memo", "selected_variant_id":row["selected_variant_id"]}]}])
            review = database.load_review("movie")
            review["segments"][0]["end"] = 2
            database.save_review("movie", review, expected_revision=1)
            restored = database.load_assembly(["movie"])["projects"][0]["segments"][0]
            self.assertEqual((restored["duration"], restored["tag"], restored["note"]), (2, "保留", "memo"))

    def test_current_schema_removes_unused_legacy_tables(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "main.sqlite3"
            ProjectDatabase(path)
            connection = sqlite3.connect(path)
            try:
                tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                version = connection.execute("SELECT version FROM schema_info").fetchone()[0]
            finally:
                connection.close()
            self.assertEqual(version, 9)
            for name in (
                "global_speakers",
                "source_speaker_mappings",
                "segment_candidates",
                "training_items",
                "project_tags",
            ):
                self.assertNotIn(name, tables)
            connection = sqlite3.connect(path)
            try:
                table_info = {
                    row[1]: row for row in connection.execute("PRAGMA table_info(assembly_items)")
                }
            finally:
                connection.close()
            self.assertIn("tag", table_info)
            self.assertNotIn("tag_id", table_info)
            self.assertEqual(table_info["tag"][4], "'1'")

    def test_v6_tag_entities_migrate_to_item_text_without_losing_annotations(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "main.sqlite3"
            audio = root / "movie.wav"
            audio.touch()
            database = ProjectDatabase(path)
            database.create_review("movie", audio, [Segment(0, 1, "角色", "文字")])
            with database._connection() as connection:
                source_id = connection.execute("SELECT id FROM sources").fetchone()[0]
                segment_id = connection.execute("SELECT segment_id FROM segments").fetchone()[0]
                variant_id = connection.execute("SELECT id FROM audio_variants").fetchone()[0]
                connection.execute("PRAGMA foreign_keys=OFF")
                connection.executescript(
                    """
                    DROP TABLE assembly_items;
                    CREATE TABLE project_tags (
                        id TEXT PRIMARY KEY,
                        source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
                        name TEXT NOT NULL,
                        ordinal INTEGER NOT NULL,
                        created_at TEXT NOT NULL,
                        UNIQUE (source_id, name)
                    );
                    CREATE TABLE assembly_items (
                        source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
                        segment_id TEXT NOT NULL,
                        selected_variant_id TEXT REFERENCES audio_variants(id) ON DELETE SET NULL,
                        tag_id TEXT NOT NULL REFERENCES project_tags(id) ON DELETE RESTRICT,
                        note TEXT NOT NULL DEFAULT '',
                        updated_at TEXT NOT NULL,
                        PRIMARY KEY (source_id, segment_id)
                    );
                    UPDATE schema_info SET version=6;
                    """
                )
                connection.execute(
                    "INSERT INTO project_tags VALUES ('tag-1', ?, '精选', 0, 'now')", (source_id,)
                )
                connection.execute(
                    "INSERT INTO assembly_items VALUES (?, ?, ?, 'tag-1', '备注', 'now')",
                    (source_id, segment_id, variant_id),
                )
                connection.commit()

            migrated = ProjectDatabase(path).load_assembly(["movie"])["projects"][0]
            self.assertEqual(migrated["tags"], ["精选"])
            self.assertEqual(migrated["segments"][0]["tag"], "精选")
            self.assertEqual(migrated["segments"][0]["note"], "备注")
            self.assertEqual(migrated["segments"][0]["selected_variant_id"], variant_id)
            connection = sqlite3.connect(path)
            try:
                tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            finally:
                connection.close()
            self.assertNotIn("project_tags", tables)

    def test_each_exported_database_contains_exactly_one_project(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first_audio = root / "first.wav"
            second_audio = root / "second.wav"
            first_audio.write_bytes(b"first")
            second_audio.write_bytes(b"second")
            database = ProjectDatabase(root / "main.sqlite3")
            database.create_review("项目一", first_audio, [Segment(1, 2, "甲", "第一条")])
            database.create_review("项目二", second_audio, [Segment(3, 4, "乙", "第二条")])

            paths = database.export_projects(["项目一", "项目二"], root / "exports")

            self.assertEqual([path.name for path in paths], ["项目一.sqlite3", "项目二.sqlite3"])
            for expected, path in zip(("项目一", "项目二"), paths, strict=False):
                metadata = ProjectDatabase.inspect_project_file(path)
                self.assertEqual(metadata["project_name"], expected)
                self.assertEqual(metadata["segment_count"], 1)

    def test_export_import_round_trip_and_delete_are_project_scoped(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audio = root / "movie.wav"
            processed = root / "movie-clean.wav"
            audio.write_bytes(b"audio")
            processed.write_bytes(b"clean")
            source = ProjectDatabase(root / "source.sqlite3")
            document = source.create_review("movie", audio, [Segment(1, 2, "角色", "新转录文字")])
            document["segments"][0]["text"] = "人工校对文字"
            source.save_review("movie", document, expected_revision=1)
            source.register_audio_asset("movie", processed, duration_seconds=10)
            source.set_audio_offset("movie", processed, 0.125)
            assembly = source.load_assembly(["movie"])["projects"][0]
            assembly_row = assembly["segments"][0]
            source.save_assembly([{
                "project_name":"movie", "revision":assembly["revision"], "tags":["训练集", "精选"], "offsets":{},
                "items":[{"id":assembly_row["id"], "text":assembly_row["text"], "tag":"精选", "note":"portable", "selected_variant_id":assembly["variants"][1]["id"]}],
            }])
            exported = source.export_projects(["movie"], root / "exports")[0]

            target = ProjectDatabase(root / "target.sqlite3")
            self.assertEqual(target.import_project_file(exported), "movie")
            loaded = target.load_review("movie")
            self.assertEqual(loaded["segments"][0]["text"], "人工校对文字")
            self.assertEqual(target.get_audio_asset("movie", processed)["offset_seconds"], 0.125)
            imported_assembly = target.load_assembly(["movie"])["projects"][0]
            self.assertEqual(imported_assembly["segments"][0]["tag"], "精选")
            self.assertEqual(imported_assembly["segments"][0]["note"], "portable")
            with self.assertRaises(FileExistsError):
                target.import_project_file(exported)

            workspace = root / "movie-cache"
            workspace.mkdir()
            (workspace / "review-peaks-audio-id.npz").touch()
            self.assertEqual(target.delete_projects(["movie"]), 1)
            self.assertFalse(target.has_project("movie"))
            self.assertTrue(workspace.is_dir())

    def test_export_stays_database_only_and_delete_removes_project_runtime_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "output"
            audio = root / "movie.wav"
            audio.write_bytes(b"audio")
            database = ProjectDatabase(database_path_for(output))
            database.create_review("movie", audio, [Segment(1, 2, "角色", "台词")])

            workspace = project_workspace_for("movie", output)
            workspace.mkdir()
            (workspace / "review-peaks.npz").write_bytes(b"legacy")
            (workspace / "review-peaks-audio-id.npz").write_bytes(b"current")
            nested = workspace / "future-runtime-files"
            nested.mkdir()
            (nested / "pending.cache").write_bytes(b"pending")
            global_export = output / "slicer_opt"
            global_export.mkdir()
            (global_export / "clip.wav").write_bytes(b"clip")

            export_directory = root / "exports"
            exported = database.export_projects(["movie"], export_directory)
            self.assertEqual([path.name for path in exported], ["movie.sqlite3"])
            self.assertFalse((export_directory / "movie").exists())
            self.assertEqual([path.name for path in export_directory.iterdir()], ["movie.sqlite3"])

            self.assertEqual(database.delete_projects(["movie"]), 1)
            self.assertFalse(workspace.exists())
            self.assertTrue(audio.exists())
            self.assertTrue((global_export / "clip.wav").exists())

    def test_import_rejects_database_with_multiple_projects(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = ProjectDatabase(root / "invalid.sqlite3")
            for name in ("one", "two"):
                audio = root / f"{name}.wav"
                audio.touch()
                database.create_review(name, audio, [Segment(0, 1)])
            with self.assertRaises(ValueError):
                ProjectDatabase.inspect_project_file(database.path)

    def test_manager_rejects_overwriting_or_importing_the_live_database(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audio = root / "audio.wav"
            audio.touch()
            database = ProjectDatabase(root / "audio-registry.sqlite3")
            database.create_review("audio-registry", audio, [Segment(0, 1)])
            with self.assertRaises(ValueError):
                database.export_projects(["audio-registry"], root, overwrite=True)
            with self.assertRaises(ValueError):
                database.import_project_file(database.path, replace=True)


if __name__ == "__main__":
    unittest.main()
