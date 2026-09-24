import os
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import yaml

import audio_registry
from audio_registry.assembly_webui.server import AssemblyApplication, choose_audio_variants_isolated
from audio_registry.config import load_config, local_config_path, update_local_config
from audio_registry.i18n import t
from audio_registry.models import Segment
from audio_registry.review import build_review_document

ASSET_DIR = Path(__file__).parents[1] / "src/audio_registry/assembly_webui/assets"


class AssemblyWebUiTests(unittest.TestCase):
    def test_row_tag_edits_and_saves_preserve_deep_scroll_position(self):
        script = (ASSET_DIR / "app.js").read_text(encoding="utf-8")
        tag_change = script[script.index("if (event.target.dataset.field === 'tag')"):script.index("if (event.target.dataset.field === 'speaker')")]
        self.assertNotIn("resetLimits()", tag_change)
        self.assertIn("renderAtCurrentScroll()", tag_change)
        self.assertIn("const previousLimits = preservePosition ? new Map(model.rowLimits) : null", script)
        self.assertIn("Math.max(120, previousLimits?.get(project.project_name) || 0)", script)
        self.assertIn("if (audioChanged) await loadState([...model.selectedProjects], false, true, true)", script)
        self.assertIn("else {\n        model.projects.forEach", script)

    def test_filter_summary_labels_match_webui1(self):
        html = (ASSET_DIR / "index.html").read_text(encoding="utf-8")
        script = (ASSET_DIR / "app.js").read_text(encoding="utf-8")
        self.assertIn('id="speaker-summary" data-i18n="filter.speaker"', html)
        self.assertIn('id="tag-summary" data-i18n="filter.tag"', html)
        self.assertIn("selectedCount === speakers.length ? t('filter.speaker')", script)
        self.assertIn("selectedCount === tags.length ? t('filter.tag')", script)

    def test_unbound_project_keeps_text_and_can_save_without_audio(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "config.yaml"
            config_path.write_text("paths:\n  output_dir: output\n", encoding="utf-8")
            app = AssemblyApplication(load_config(config_path))
            app.database.import_review(build_review_document(None, [Segment(2, 4, "角色", "文字")]), project_name="unbound")
            project = app.state(["unbound"])["projects"][0]
            self.assertEqual(project["variants"], [])
            row = project["segments"][0]
            self.assertIsNone(row["selected_variant_id"])
            app.save({"projects":[{"project_name":"unbound", "revision":project["revision"], "tags":project["tags"],
                "items":[dict(row, text="修改文字", note="备注")] }]})
            saved = app.state(["unbound"])["projects"][0]
            self.assertEqual(saved["segments"][0]["text"], "修改文字")
            self.assertEqual(saved["segments"][0]["note"], "备注")
            self.assertEqual(saved["variants"], [])
        script = (ASSET_DIR / "app.js").read_text(encoding="utf-8")
        self.assertIn("const hasVariants = project.variants.length > 0", script)
        self.assertIn("const audioContent = hasVariants ?", script)
        self.assertIn("missingSelections().filter(item => item.project.variants.length)", script)
        self.assertNotIn("项目“${emptyProjects.join", script)

    def test_relocate_audio_picker_cancellation_and_rebinding(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "config.yaml"
            config_path.write_text("paths:\n  output_dir: output\n", encoding="utf-8")
            app = AssemblyApplication(load_config(config_path))
            original = root / "old.wav"
            replacement = root / "new.wav"
            original.touch()
            replacement.touch()
            app.database.create_review("movie", original, [Segment(0, 1)])
            asset_id = app.state(["movie"])["projects"][0]["variants"][0]["id"]
            payload = {"project_name":"movie", "asset_id":asset_id}
            original.unlink()
            self.assertFalse(app.state(["movie"])["projects"][0]["variants"][0]["available"])
            counters = app.database.project_update_counters(["movie"])
            with patch("audio_registry.assembly_webui.server.choose_audio_variants_isolated", return_value=[]) as picker:
                self.assertEqual(app.relocate_audio(payload), {"relocated":False})
                picker.assert_called_once_with("movie", relocate_path=str(original.resolve()))
            self.assertEqual(app.database.project_update_counters(["movie"]), counters)
            with patch("audio_registry.assembly_webui.server.choose_audio_variants_isolated", return_value=[replacement]), \
                 patch("audio_registry.assembly_webui.server._audio_duration_seconds", return_value=10):
                relocated = app.relocate_audio(payload)
                self.assertTrue(relocated["relocated"])
                self.assertEqual(relocated["asset"]["audio_path"], str(replacement.resolve()))
            staged_state = app.state(["movie"])["projects"][0]
            self.assertFalse(staged_state["variants"][0]["available"])
            self.assertEqual(app.database.project_update_counters(["movie"]), counters)
            app.save({"projects":[{
                "project_name":"movie", "revision":staged_state["revision"], "tags":staged_state["tags"],
                "relocated_audio":[{"id":asset_id, "audio_path":str(replacement), "duration_seconds":10}],
                "offsets":{asset_id:0}, "items":staged_state["segments"],
            }]})
            state = app.state(["movie"])["projects"][0]
            self.assertTrue(state["variants"][0]["available"])
            self.assertEqual(state["segments"][0]["selected_variant_id"], asset_id)
            self.assertEqual(app.audio_path(asset_id), replacement.resolve())
            with self.assertRaises(ValueError):
                app.relocate_audio({"project_name":"other", "asset_id":asset_id})
        script = (ASSET_DIR / "app.js").read_text(encoding="utf-8")
        self.assertIn('data-action="relocate-audio"', script)
        self.assertIn("/api/relocate-audio", script)
        self.assertIn("ui.audio.removeAttribute('src'); ui.audio.load()", script)
        self.assertIn("t('runtime.audio_relocated')", script)
        self.assertNotIn("model.dirty && !await save()", script)

    def test_relocate_picker_passes_original_path_to_isolated_process(self):
        with patch("audio_registry.assembly_webui.server.subprocess.run", return_value=SimpleNamespace(stdout="[]")) as run:
            self.assertEqual(choose_audio_variants_isolated("movie", relocate_path="old.wav"), [])
        self.assertEqual(run.call_args.args[0][-2:], ["movie", "old.wav"])

    def test_export_settings_are_local_and_do_not_change_project_counter(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "config.yaml"
            config_path.write_text("paths:\n  output_dir: output\n", encoding="utf-8")
            update_local_config(config_path, {"process":{"end_padding":0.35}})
            app = AssemblyApplication(load_config(config_path))
            audio = root / "source.wav"
            audio.touch()
            app.database.create_review("movie", audio, [Segment(0, 1)])
            counters = app.database.project_update_counters(["movie"])
            saved = app.save_export_settings({"convert_format":True, "loudness_balance":True,
                                              "target_lufs":-23, "normalization_strength":0.6,
                                              "gain_limit_db":7, "true_peak_ceiling_dbtp":-2})
            reloaded = load_config(config_path)
            self.assertEqual(saved["clip_export"], asdict(reloaded.clip_export))
            self.assertEqual(app.state(["movie"])["clip_export"], saved["clip_export"])
            self.assertEqual(app.database.project_update_counters(["movie"]), counters)
            self.assertEqual(reloaded.process.end_padding, 0.35)
            local = yaml.safe_load(local_config_path(config_path).read_text(encoding="utf-8"))
            self.assertEqual(local["clip_export"]["normalization_strength"], 0.6)
            with self.assertRaises(ValueError):
                app.save_export_settings({"gain_limit_db":-8})

    def test_list_only_export_is_independent_of_clip_processing_options(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "config.yaml"
            config_path.write_text("{}", encoding="utf-8")
            app = AssemblyApplication(load_config(config_path))
            for mode in ("clips", "list"):
                with patch("audio_registry.assembly_webui.server.threading.Thread") as thread, \
                     patch("audio_registry.assembly_webui.server.export_assembly_selection") as export:
                    app.start_export({"mode":mode, "projects":["movie"], "selected_speakers":[],
                                      "selected_tags":[], "clip_export":{"convert_format":True,"loudness_balance":True}})
                    thread.call_args.kwargs["target"]()
                    if mode == "clips":
                        self.assertTrue(export.call_args.kwargs["export_settings"].convert_format)
                        self.assertTrue(export.call_args.kwargs["export_settings"].loudness_balance)
                    else:
                        self.assertNotIn("export_settings", export.call_args.kwargs)
                        self.assertIsNone(app.export_status["clips"])
                    self.assertEqual(export.call_args.kwargs["write_list"], mode == "list")

    def test_table_export_chooses_a_folder_and_uses_current_filters(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "config.yaml"
            config_path.write_text("{}", encoding="utf-8")
            app = AssemblyApplication(load_config(config_path))
            completed = SimpleNamespace(path=root / "筛选结果.xlsx", count=3)
            with patch("audio_registry.assembly_webui.server.choose_output_directory_isolated", return_value=root) as picker, \
                 patch("audio_registry.assembly_webui.server.export_assembly_spreadsheet", return_value=completed) as export, \
                 patch("audio_registry.assembly_webui.server.threading.Thread") as thread:
                started = app.start_export({
                    "mode":"table", "projects":["甲", "乙"],
                    "selected_speakers":["角色"], "selected_tags":["1训练集"],
                })
                self.assertEqual(started["mode"], "table")
                thread.call_args.kwargs["target"]()
            picker.assert_called_once_with(t("backend.table_folder"))
            self.assertEqual(export.call_args.args[1:3], (["甲", "乙"], root))
            self.assertEqual(export.call_args.kwargs["selected_speakers"], ["角色"])
            self.assertEqual(export.call_args.kwargs["selected_tags"], ["1训练集"])
            self.assertEqual(app.export_status["table"], str(completed.path))
            self.assertEqual(app.export_status["message"], t("backend.table_complete", count=3))

            with patch("audio_registry.assembly_webui.server.choose_output_directory_isolated", return_value=None), \
                 patch("audio_registry.assembly_webui.server.threading.Thread") as cancelled_thread:
                cancelled = app.start_export({
                    "mode":"table", "projects":["甲"],
                    "selected_speakers":[], "selected_tags":[],
                })
            self.assertTrue(cancelled["cancelled"])
            cancelled_thread.assert_not_called()

    def test_export_menu_has_optional_steps_and_local_numeric_settings(self):
        html = (ASSET_DIR / "index.html").read_text(encoding="utf-8")
        script = (ASSET_DIR / "app.js").read_text(encoding="utf-8")
        self.assertIn('id="export"', html)
        self.assertIn('id="export-menu"', html)
        self.assertIn('data-i18n="assembly.export_clips">Export clips</button>', html)
        self.assertIn('id="export-table"', html)
        self.assertIn('data-i18n="assembly.export_table">Export spreadsheet</button>', html)
        self.assertIn('id="convert-format" type="checkbox"', html)
        self.assertIn('id="loudness-balance" type="checkbox"', html)
        for field in ("target-lufs", "normalization-strength", "gain-limit", "true-peak-ceiling"):
            self.assertIn(f'id="{field}" type="number"', html)
        self.assertIn("'/api/export-settings'", script)
        self.assertIn("clip_export:settings", script)
        self.assertIn("mode === 'clips' ? exportSettings() : undefined", script)
        self.assertIn("startExport('table', ui.exportTable)", script)

    def test_save_refresh_colors_and_project_counter_checks_match_review_ui(self):
        script = (ASSET_DIR / "app.js").read_text(encoding="utf-8")
        styles = (ASSET_DIR / "styles.css").read_text(encoding="utf-8")
        review_styles = (ASSET_DIR.parents[1] / "webui/assets/styles.css").read_text(encoding="utf-8")
        for rule in styles.splitlines():
            if rule.startswith("#save"):
                self.assertIn(rule, review_styles)
        self.assertIn("ui.save.classList.toggle('primary', value)", script)
        self.assertIn("ui.refresh.classList.toggle('primary', model.remoteChanged)", script)
        self.assertIn("ui.refresh.disabled = !model.remoteChanged || !model.projects.length || model.loading", script)
        self.assertNotIn("ui.refresh.disabled = !model.projects.length;", script)
        self.assertIn("#save:not(.primary), #refresh:not(.primary) { opacity: .42; }", styles)
        self.assertIn("setInterval(checkDatabaseChanges, 3000)", script)
        self.assertIn("/api/update-counters?", script)
        self.assertIn("selection !== selectionKey(model.selectedProjects)", script)

    def test_audio_picker_is_isolated_from_the_web_server_process(self):
        fake = SimpleNamespace(stdout='["D:\\\\audio\\\\movie.wav"]')
        with patch("audio_registry.assembly_webui.server.subprocess.run", return_value=fake) as run:
            selected = choose_audio_variants_isolated("movie")
        self.assertEqual(selected, [Path("D:/audio/movie.wav").resolve()])
        self.assertIn("audio_picker_process.py", str(run.call_args.args[0][1]))
        self.assertTrue(run.call_args.kwargs["check"])
        source_root = Path(audio_registry.__file__).resolve().parents[1]
        child_pythonpath = run.call_args.kwargs["env"]["PYTHONPATH"].split(os.pathsep)[0]
        self.assertEqual(Path(child_pythonpath).resolve(), source_root)

    def test_audio_picker_reports_child_process_error_details(self):
        error = __import__("subprocess").CalledProcessError(
            1, ["python", "audio_picker_process.py"], stderr="picker traceback"
        )
        with patch("audio_registry.assembly_webui.server.subprocess.run", side_effect=error):
            with self.assertRaisesRegex(RuntimeError, "picker traceback"):
                choose_audio_variants_isolated("movie")

    def test_blank_start_project_and_excel_style_speaker_filters_exist(self):
        html = (ASSET_DIR / "index.html").read_text(encoding="utf-8")
        script = (ASSET_DIR / "app.js").read_text(encoding="utf-8")
        self.assertIn('id="empty-state"', html)
        self.assertIn('id="project-filter"', html)
        self.assertIn('id="speaker-search"', html)
        self.assertIn("launchParameters.has('initial_project')", script)
        self.assertIn("launchParameters.has('initial_blank')", script)
        self.assertIn("loadState(initialProjects, false, false)", script)

    def test_speakers_can_be_managed_globally_and_changed_per_row(self):
        html = (ASSET_DIR / "index.html").read_text(encoding="utf-8")
        script = (ASSET_DIR / "app.js").read_text(encoding="utf-8")
        styles = (ASSET_DIR / "styles.css").read_text(encoding="utf-8")
        self.assertLess(html.index('id="project-filter"'), html.index('class="top-actions"'))
        self.assertIn('id="speaker-add"', html)
        self.assertIn('data-field="speaker"', script)
        self.assertIn('data-action="rename-speaker"', script)
        self.assertIn('data-action="delete-speaker"', script)
        self.assertIn('speaker:row.speaker', script)
        self.assertIn('missing-speaker', script)
        self.assertIn('.speaker-select.missing-speaker', styles)
        self.assertIn('#speaker-filter .filter-options { max-height: 220px; }', styles)
        self.assertIn("const sortSpeakerNames = names =>", script)
        self.assertIn("/^speaker/i.test(left)", script)
        self.assertIn("t('runtime.speaker_merge_confirm'", script)
        self.assertIn('mergingProjects', script)

    def test_tag_multiselect_filters_rows_and_current_export_scope(self):
        html = (ASSET_DIR / "index.html").read_text(encoding="utf-8")
        script = (ASSET_DIR / "app.js").read_text(encoding="utf-8")
        styles = (ASSET_DIR / "styles.css").read_text(encoding="utf-8")
        self.assertIn('id="tag-filter"', html)
        self.assertIn('id="tag-options"', html)
        self.assertIn('id="tag-add"', html)
        self.assertIn("model.selectedTags.has(row.tag)", script)
        self.assertIn("selected_tags:[...model.selectedTags]", script)
        self.assertIn("selected_speakers:[...model.selectedSpeakers]", script)
        self.assertIn("const availableTags = allTags()", script)
        self.assertIn("const options = availableTags.map(tag => tagOption(tag, row.tag === tag))", script)
        self.assertIn("if (!project.tags.includes(row.tag)) project.tags = sortTagNames([...project.tags, row.tag])", script)
        self.assertIn('data-action="rename-tag"', script)
        self.assertIn('data-action="delete-tag"', script)
        self.assertIn("function renameTag(", script)
        self.assertIn("function deleteTag(", script)
        self.assertIn("t('runtime.tag_merge_confirm'", script)
        self.assertIn("const mergesExistingTag = allTags().includes(newName)", script)
        self.assertIn("project.segments.filter(row => row.tag === oldName).length", script)
        self.assertIn("mergesExistingTag", script)
        self.assertIn("project.tags = sortTagNames(", script)
        self.assertIn("t(mergesExistingTag ? 'runtime.merged' : 'runtime.renamed'", script)
        tag_rename = script.split("function renameTag(", 1)[1].split("function beginTagRename(", 1)[0]
        self.assertNotIn("mergingProjects", tag_rename)
        self.assertIn("missing-tag", script)
        self.assertIn("t('runtime.missing_tags_save'", script)
        self.assertIn(".tag-select.missing-tag", styles)

    def test_tags_use_fixed_palette_with_first_tag_reserved_green(self):
        script = (ASSET_DIR / "app.js").read_text(encoding="utf-8")
        styles = (ASSET_DIR / "styles.css").read_text(encoding="utf-8")
        self.assertIn("const firstTagColor = '#71d47f'", script)
        self.assertIn("const tagPalette = palette.filter(color => color !== firstTagColor)", script)
        self.assertIn("const tagColors = new Map()", script)
        self.assertIn("tagPalette[tagColorCursor % tagPalette.length]", script)
        self.assertIn("syncTagColors(tags)", script)
        self.assertIn('style="--tag-color:${tagColor(name)}"', script)
        self.assertIn('style="--tag-color:${tagColor(row.tag)}"', script)
        self.assertIn(".tag-select.tag-colored:not(.missing-tag)", styles)
        self.assertIn("const tagOption = (tag, selected = false) =>", script)
        self.assertIn("availableTags.map(tag => tagOption(tag, row.tag === tag))", script)
        self.assertIn(".tag-select option.tag-option", styles)

    def test_speaker_colors_are_stable_for_the_page_and_avoid_adjacent_collisions(self):
        script = (ASSET_DIR / "app.js").read_text(encoding="utf-8")
        self.assertIn("const speakerColors = new Map()", script)
        self.assertIn("let speakerColorCursor = 0", script)
        self.assertIn("function assignSpeakerColors(speakers)", script)
        self.assertIn("speakerColors.get(speakers[index - 1])", script)
        self.assertIn("speakerColors.get(speakers[index + 1])", script)
        self.assertIn("if (!adjacentColors.has(candidate))", script)
        self.assertIn("assignSpeakerColors(speakers)", script)
        self.assertIn("speakerColors.set(newName, speakerColors.get(oldName))", script)
        self.assertNotIn("Math.abs(hash) % palette.length", script)

    def test_tag_options_use_derived_name_sorting_without_manual_order(self):
        script = (ASSET_DIR / "app.js").read_text(encoding="utf-8")
        styles = (ASSET_DIR / "styles.css").read_text(encoding="utf-8")
        self.assertIn("const sortTagNames = names =>", script)
        self.assertIn("const allTags = () => sortTagNames(", script)
        self.assertNotIn('tag-drag-handle', script)
        self.assertNotIn("ui.tagOptions.addEventListener('dragstart'", script)
        self.assertNotIn(".tag-filter-option.drop-before", styles)

    def test_transcript_notes_tags_and_manual_database_sync_exist(self):
        script = (ASSET_DIR / "app.js").read_text(encoding="utf-8")
        self.assertIn("data-field=\"text\"", script)
        self.assertIn("data-field=\"note\"", script)
        self.assertIn("t('review.new_tag')", script)
        self.assertIn("/api/save", script)
        self.assertIn("t('runtime.discard_refresh')", script)

    def test_candidate_buttons_have_stable_size_and_coordinates_are_not_editable(self):
        html = (ASSET_DIR / "index.html").read_text(encoding="utf-8")
        script = (ASSET_DIR / "app.js").read_text(encoding="utf-8")
        styles = (ASSET_DIR / "styles.css").read_text(encoding="utf-8")
        self.assertIn("width: 78px; height: 32px", styles)
        self.assertIn('class="offset-unit">${escapeHtml(t(\'runtime.second\'))}', script)
        self.assertIn("t('runtime.offset')", script)
        self.assertNotIn("开始时间", html)
        self.assertNotIn("结束时间", html)

    def test_large_projects_are_rendered_with_progressive_infinite_scrolling(self):
        script = (ASSET_DIR / "app.js").read_text(encoding="utf-8")
        self.assertIn("rowLimits: new Map()", script)
        self.assertIn("IntersectionObserver", script)
        self.assertIn("rows.slice(0, limit)", script)

    def test_toolbar_controls_dock_individually_without_sticky_rows(self):
        html = (ASSET_DIR / "index.html").read_text(encoding="utf-8")
        script = (ASSET_DIR / "app.js").read_text(encoding="utf-8")
        styles = (ASSET_DIR / "styles.css").read_text(encoding="utf-8")
        self.assertIn('id="save-slot"', html)
        self.assertIn('id="refresh-slot"', html)
        self.assertIn('id="speaker-filter-slot"', html)
        self.assertIn('id="tag-filter-slot"', html)
        self.assertIn("filters: document.querySelector('.filters')", script)
        self.assertIn(".topbar { position: relative;", styles)
        self.assertIn(".filters { position: relative;", styles)
        self.assertIn(".sticky-control-slot[hidden] { display: none; }", styles)
        self.assertIn(".sticky-floating-control { position: fixed !important;", styles)
        self.assertIn("function updateStickyControls()", script)
        self.assertIn("const measurements = stickyControls.map", script)
        self.assertIn("slotRect.top <= dockTop", script)
        self.assertIn("window.addEventListener('scroll', scheduleStickyUpdate", script)

    def test_project_tabs_float_collapse_and_preserve_their_viewport_position(self):
        html = (ASSET_DIR / "index.html").read_text(encoding="utf-8")
        script = (ASSET_DIR / "app.js").read_text(encoding="utf-8")
        styles = (ASSET_DIR / "styles.css").read_text(encoding="utf-8")
        self.assertNotIn('id="active-project-tab"', html)
        self.assertNotIn("activeProjectTab", script)
        self.assertNotIn("updateActiveProjectTab", script)
        self.assertIn('<div class="project-tab-slot"><header class="project-tab"><button class="project-collapse"', script)
        self.assertIn('aria-expanded="${!collapsed}"', script)
        self.assertIn('<div class="project-panel" ${collapsed ? \'hidden\' : \'\'}>', script)
        self.assertLess(script.index('class="project-panel"'), script.index('class="project-audio"'))
        self.assertLess(script.index('class="project-audio"'), script.index('class="group-body"'))
        self.assertNotIn("${rows.length}/${project.segments.length} 条", script)
        self.assertIn(".project-tab-slot { height: 44px;", styles)
        self.assertIn("border-radius: 9px 9px 0 0;", styles)
        self.assertIn(".project-tab-floating { position: fixed !important;", styles)
        self.assertIn("height: var(--project-tab-height) !important; border-radius: 9px;", styles)
        self.assertIn(".project-group.collapsed .project-tab { border-radius: 9px; }", styles)
        self.assertIn("top: calc(var(--floating-controls-bottom) + 8px)", styles)
        self.assertIn(".project-collapse { width: 36px; height: 34px;", styles)
        self.assertIn(".project-panel[hidden] { display: none; }", styles)
        self.assertIn("function updateProjectTab(floatingBottom)", script)
        self.assertIn("function updateStickyLayout()", script)
        self.assertIn("let projectAnchorFrame = 0", script)
        self.assertIn("function scheduleProjectAnchor(group, anchorTop)", script)
        self.assertIn("cancelAnimationFrame(projectAnchorFrame)", script)
        self.assertIn("projectAnchorFrame = requestAnimationFrame", script)
        self.assertIn("window.scrollTo({top:Math.max(0, targetTop), behavior:'auto'})", script)
        self.assertIn("expanded:!group.classList.contains('collapsed')", script)
        self.assertIn("if (expanded && slotRect.top <= dockTop)", script)
        self.assertIn("measurements[activeIndex].groupRect.bottom <= dockTop", script)
        self.assertIn("tab.classList.add('project-tab-floating')", script)
        self.assertIn("group.querySelector('.project-panel').hidden = collapsed", script)
        self.assertIn("group.classList.toggle('collapsed', collapsed)", script)
        self.assertIn("const anchorTop = group.querySelector('.project-tab').getBoundingClientRect().top", script)
        self.assertIn("scheduleProjectAnchor(group, anchorTop)", script)
        self.assertNotIn("group-header", script)

    def test_custom_dropdowns_close_on_outside_pointer_press(self):
        script = (ASSET_DIR / "app.js").read_text(encoding="utf-8")
        self.assertIn("document.querySelectorAll('details[open]')", script)
        self.assertIn("if (!menu.contains(event.target)) menu.open = false", script)

    def test_project_multiselect_stays_open_while_loading_each_choice(self):
        script = (ASSET_DIR / "app.js").read_text(encoding="utf-8")
        self.assertIn("await loadState(checked)", script)
        self.assertNotIn("ui.projectFilter.open = false; await loadState(checked)", script)

    def test_project_speaker_and_tag_filters_survive_button_and_page_refresh(self):
        script = (ASSET_DIR / "app.js").read_text(encoding="utf-8")
        self.assertIn("localStorage.setItem(UI_STATE_KEY", script)
        self.assertIn("restoredView(projectNames, speakers, tags)", script)
        self.assertIn("selectedProjects: projectNames", script)
        self.assertIn("selectedTags: [...model.selectedTags]", script)
        self.assertIn("allTagsSelected:", script)
        self.assertIn("loadState(initialProjects, false, false)", script)
        self.assertIn("speakerSearch: ui.speakerSearch.value", script)
        self.assertIn("collapsedByProject:Object.fromEntries(collapsedByProject)", script)
        self.assertIn("projectNames.filter(name => state.collapsedByProject?.[name] === true)", script)
        self.assertNotIn("collapsedProjects: [...model.collapsed]", script)
        self.assertIn(".slice(32)", script)
        self.assertNotIn("scrollY: Math.max(0, window.scrollY || 0)", script)

    def test_audio_paths_can_be_deleted_and_missing_choices_are_highlighted(self):
        html = (ASSET_DIR / "index.html").read_text(encoding="utf-8")
        script = (ASSET_DIR / "app.js").read_text(encoding="utf-8")
        styles = (ASSET_DIR / "styles.css").read_text(encoding="utf-8")
        self.assertNotIn("request('/api/delete-audio'", script)
        self.assertIn("deleted_audio_ids:[...(project.deleted_audio_ids || [])]", script)
        self.assertIn("t('runtime.audio_delete_staged')", script)
        self.assertIn("missing-selection", script)
        self.assertIn("t('runtime.missing_audio_save'", script)
        self.assertIn(".audio-cell.missing-selection", styles)
        self.assertNotIn("确定删除项目", script)
        self.assertLess(html.index('id="save"'), html.index('id="refresh"'))

    def test_audio_deletion_is_staged_until_assembly_save(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "config.yaml"
            config_path.write_text("paths:\n  output_dir: output\n", encoding="utf-8")
            app = AssemblyApplication(load_config(config_path))
            audio = root / "source.wav"
            audio.touch()
            app.database.create_review("movie", audio, [Segment(0, 1)])
            project = app.state(["movie"])["projects"][0]
            asset_id = project["variants"][0]["id"]
            self.assertEqual(len(app.state(["movie"])["projects"][0]["variants"]), 1)
            app.save({"projects":[{
                "project_name":"movie", "revision":project["revision"], "tags":project["tags"],
                "deleted_audio_ids":[asset_id], "offsets":{},
                "items":[{**row, "selected_variant_id":None} for row in project["segments"]],
            }]})
            saved = app.state(["movie"])["projects"][0]
            self.assertEqual(saved["variants"], [])
            self.assertIsNone(saved["segments"][0]["selected_variant_id"])

    def test_audio_addition_is_staged_until_assembly_save(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "config.yaml"
            config_path.write_text("paths:\n  output_dir: output\n", encoding="utf-8")
            app = AssemblyApplication(load_config(config_path))
            original, added = root / "source.wav", root / "added.wav"
            original.touch()
            added.touch()
            app.database.create_review("movie", original, [Segment(0, 1)])
            project = app.state(["movie"])["projects"][0]
            counters = app.database.project_update_counters(["movie"])
            with patch("audio_registry.assembly_webui.server.choose_audio_variants_isolated", return_value=[added]), \
                 patch("audio_registry.assembly_webui.server._audio_duration_seconds", return_value=8):
                staged = app.add_audio({"project_name":"movie"})
            self.assertEqual(staged["count"], 1)
            pending = staged["assets"][0]
            self.assertTrue(pending["id"].startswith("pending:"))
            self.assertEqual(len(app.state(["movie"])["projects"][0]["variants"]), 1)
            self.assertEqual(app.database.project_update_counters(["movie"]), counters)
            app.save({"projects":[{
                "project_name":"movie", "revision":project["revision"], "tags":project["tags"],
                "added_audio":[pending], "offsets":{pending["id"]:0.25},
                "items":[{**row, "selected_variant_id":pending["id"]} for row in project["segments"]],
            }]})
            saved = app.state(["movie"])["projects"][0]
            self.assertEqual(len(saved["variants"]), 2)
            self.assertEqual(saved["variants"][1]["audio_path"], str(added.resolve()))
            self.assertEqual(saved["variants"][1]["offset_seconds"], 0.25)
            self.assertEqual(saved["segments"][0]["selected_variant_id"], saved["variants"][1]["id"])

    def test_last_staged_deletion_does_not_block_adding_audio_again(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "config.yaml"
            config_path.write_text("paths:\n  output_dir: output\n", encoding="utf-8")
            app = AssemblyApplication(load_config(config_path))
            audio = root / "source.wav"
            audio.touch()
            app.database.create_review("movie", audio, [Segment(0, 1)])
            project = app.state(["movie"])["projects"][0]
            asset_id = project["variants"][0]["id"]
            counters = app.database.project_update_counters(["movie"])
            with patch("audio_registry.assembly_webui.server.choose_audio_variants_isolated", return_value=[audio]), \
                 patch("audio_registry.assembly_webui.server._audio_duration_seconds", return_value=5):
                result = app.add_audio({"project_name":"movie", "active_asset_ids":[], "deleted_audio_ids":[asset_id]})
            self.assertEqual(result["count"], 1)
            pending = result["assets"][0]
            self.assertTrue(pending["id"].startswith("pending:"))
            self.assertEqual(app.database.project_update_counters(["movie"]), counters)
            app.save({"projects":[{
                "project_name":"movie", "revision":project["revision"], "tags":project["tags"],
                "deleted_audio_ids":[asset_id], "added_audio":[pending],
                "offsets":{pending["id"]:0},
                "items":[{**row, "selected_variant_id":pending["id"]} for row in project["segments"]],
            }]})
            saved = app.state(["movie"])["projects"][0]
            self.assertEqual(len(saved["variants"]), 1)
            self.assertNotEqual(saved["variants"][0]["id"], asset_id)
            self.assertEqual(saved["segments"][0]["selected_variant_id"], saved["variants"][0]["id"])
            script = (ASSET_DIR / "app.js").read_text(encoding="utf-8")
            self.assertIn("active_asset_ids:project.variants.map(item => item.id)", script)
            self.assertIn("if (!hadVariants && project.variants.length)", script)


if __name__ == "__main__":
    unittest.main()
