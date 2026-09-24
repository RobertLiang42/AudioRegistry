import json
import re
import shutil
import subprocess
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from audio_registry.config import load_config
from audio_registry.database import ProjectDatabase, database_path_for
from audio_registry.i18n import t
from audio_registry.models import Segment
from audio_registry.review import build_review_document
from audio_registry.webui.server import (
    ReviewApplication,
    ReviewServer,
    _audition_decimal_time,
    _srt_time,
    choose_output_directory_isolated,
)

ASSET_DIR = Path(__file__).parents[1] / "src/audio_registry/webui/assets"


class FakeReviewAsr:
    def __init__(self):
        self.calls = 0

    def transcribe_segments(self, audio, segments):
        self.calls += 1
        return [segment.with_text(f"识别结果 {self.calls}") for segment in segments]

    def close(self):
        pass


class WebUiTests(unittest.TestCase):
    def test_filter_summary_labels_are_consistent(self):
        html = (ASSET_DIR / "index.html").read_text(encoding="utf-8")
        script = (ASSET_DIR / "app.js").read_text(encoding="utf-8")
        self.assertIn('id="speaker-filter-summary" data-i18n="filter.speaker"', html)
        self.assertIn('id="tag-filter-summary" data-i18n="filter.tag"', html)
        self.assertIn("selectedCount === model.speakers.length ? t('filter.speaker')", script)
        self.assertIn("selectedCount === model.tags.length ? t('filter.tag')", script)

    def test_duration_menu_layout_and_runtime_matching(self):
        html = (ASSET_DIR / "index.html").read_text(encoding="utf-8")
        script = (ASSET_DIR / "app.js").read_text(encoding="utf-8")
        styles = (ASSET_DIR / "styles.css").read_text(encoding="utf-8")
        self.assertIn('<summary data-i18n="review.filter">Filter</summary>', html)
        self.assertIn('class="filter-menu duration-menu toolbar-filter-menu"', html)
        self.assertIn('data-i18n="filter.dim_unfiltered">Dim unfiltered markers</span>', html)
        self.assertGreater(html.index('id="duration-filter-menu"'), html.index('id="delete"'))
        self.assertGreater(html.index('id="show-hidden"'), html.index('id="duration-filter-menu"'))
        self.assertLess(html.index('id="show-hidden"'), html.index('id="play-time"'))
        self.assertIn('id="duration-empty-only"', html)
        empty_only_style = re.search(r"\.duration-empty-only \{([^}]+)\}", styles).group(1)
        self.assertIn('display: inline-flex', empty_only_style)
        self.assertIn('width: fit-content', empty_only_style)
        self.assertIn('id="duration-hide"', html)
        self.assertIn('id="duration-hide" class="button duration-hide primary"', html)
        self.assertIn("t(model.durationFilterEnabled ? 'review.hidden' : 'review.hide')", script)
        self.assertIn("ui.durationHide.addEventListener('click', toggleDurationFilter)", script)
        self.assertIn('id="duration-delete"', html)
        self.assertLess(html.index('id="filter-count"'), html.index('id="audio-offset"'))
        self.assertNotIn('未筛选内容不会被修改', script)
        self.assertIn('active().filter(row => matchesDurationFilter(row, criteria.threshold, criteria.emptyOnly))', script)
        self.assertIn('deleteRows(rows)', script)
        node = shutil.which("node")
        if node is None:
            self.skipTest("Node unavailable for frontend predicate check")
        predicate = re.search(r"const matchesDurationFilter = .*?;", script).group(0)
        code = "const assert=require('node:assert/strict'); const durationOf=row=>row.end-row.start; " + predicate + """
          const row=(duration,text)=>({start:0,end:duration,text});
          assert.equal(matchesDurationFilter(row(.4,''),.5,false),true);
          assert.equal(matchesDurationFilter(row(.4,'文字'),.5,false),true);
          assert.equal(matchesDurationFilter(row(.4,'文字'),.5,true),false);
          assert.equal(matchesDurationFilter(row(.4,' \\n '),.5,true),true);
          assert.equal(matchesDurationFilter(row(.5,''),.5,false),false);
          assert.equal(matchesDurationFilter(row(.6,''),.5,true),false);
          assert.equal(matchesDurationFilter(row(.1,''),0,false),false);
        """
        subprocess.run([node, "-e", code], check=True, capture_output=True)

        remember = re.search(r"function rememberDurationCriteria\(criteria\) \{.*?\n  \}", script, re.S).group(0)
        toggle = re.search(r"function toggleDurationFilter\(\) \{.*?\n  \}", script, re.S).group(0)
        subprocess.run([node, "-e", """
          const assert=require('node:assert/strict');
          const model={durationFilterEnabled:true,minDuration:4,minDurationEmptyOnly:true};
          const ui={durationMenu:{open:true}};
          let saves=0,renders=0;
          const durationCriteria=()=>({threshold:.5,emptyOnly:false});
          const clearNewSegmentPins=()=>{};
          const persistGlobalPreferences=()=>saves++;
          const renderAll=()=>renders++;
        """ + remember + toggle + """
          toggleDurationFilter();
          assert.equal(model.durationFilterEnabled,false);
          assert.equal(model.minDuration,.5);
          assert.equal(model.minDurationEmptyOnly,false);
          assert.equal(ui.durationMenu.open,true);
          toggleDurationFilter();
          assert.equal(model.durationFilterEnabled,true);
          assert.equal(model.minDuration,.5);
          assert.equal(model.minDurationEmptyOnly,false);
          assert.equal(ui.durationMenu.open,true);
          assert.equal(saves,2); assert.equal(renders,2);
        """], check=True, capture_output=True)
        self.assertEqual(script.count("rememberDurationCriteria(criteria);"), 2)
        self.assertIn('!model.durationFilterEnabled || !matchesDurationFilter', script)
        self.assertIn('min_duration: model.durationFilterEnabled ? model.minDuration : 0', script)
        deletion = re.search(r"function deleteRows\(rows\) \{.*?\n  \}", script, re.S).group(0)
        code += """
          let changes=0, snapshots=[];
          const model={segments:[{id:'a',start:0,end:.2,text:''},{id:'b',start:1,end:2,text:'keep'}],selectedIds:new Set(['b']),selectedId:'b'};
          const active=()=>model.segments.filter(row=>!row.deleted);
          const snapshot=()=>snapshots.push(JSON.parse(JSON.stringify(model.segments)));
          const changed=()=>changes++;
          const toast=()=>{};
          const t=()=>'';
          const setSingleSelection=id=>{model.selectedId=id; model.selectedIds=new Set(id?[id]:[]);};
        """ + deletion + """
          deleteRows(active().filter(row=>matchesDurationFilter(row,.5,true)));
          assert.equal(model.segments[0].deleted,true);
          assert.equal(model.segments[1].deleted,undefined);
          assert.equal(model.selectedId,'b');
          assert.deepEqual([...model.selectedIds],['b']);
          assert.equal(changes,1);
          assert.equal(snapshots.length,1);
          assert.equal(snapshots[0][0].deleted,undefined);
        """
        subprocess.run([node, "-e", code], check=True, capture_output=True)

    def test_empty_only_filter_is_local_and_audition_keeps_short_transcribed_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            app = self.make_app(Path(directory))
            counters = app.database.project_update_counters(["movie"])
            settings = app.save_global_ui_preferences({"min_duration":.5, "min_duration_empty_only":True})
            self.assertTrue(settings["min_duration_empty_only"])
            self.assertTrue(load_config(app.config.config_path).webui.min_duration_empty_only)
            settings = app.save_global_ui_preferences({"duration_filter_enabled":False})
            self.assertFalse(settings["duration_filter_enabled"])
            self.assertEqual(settings["min_duration"], .5)
            self.assertFalse(load_config(app.config.config_path).webui.duration_filter_enabled)
            self.assertEqual(app.database.project_update_counters(["movie"]), counters)
            document = app.state()
            original = document["segments"][0]
            document["segments"].extend([
                {**original,"id":"SHORT-TEXT","start":3,"end":3.25,"text":"短句"},
                {**original,"id":"SHORT-EMPTY","start":4,"end":4.25,"text":"  "},
                {**original,"id":"EQUAL-EMPTY","start":5,"end":5.5,"text":""},
            ])
            app.save({"revision":document["revision"],"segments":document["segments"]})
            result = app.export_audition_markers({"selected_speakers":["Speaker_1"],"min_duration":.5,"min_duration_empty_only":True})
            self.assertEqual(result["count"], 3)
            content = Path(result["path"]).read_text(encoding="utf-8-sig")
            self.assertIn("短句",content)
            self.assertNotIn("0:04.000",content)
            self.assertIn("0:05.000",content)

    def test_unbound_project_opens_and_saves_without_audio_or_peak_requests(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "config.yaml"
            config_path.write_text("paths:\n  output_dir: output\n", encoding="utf-8")
            config = load_config(config_path)
            database = ProjectDatabase(database_path_for(config.paths.data_dir, legacy_directories=(config.paths.output_dir,)))
            database.import_review(build_review_document(None, [Segment(2, 4, "角色", "文字")]), project_name="unbound")
            with patch("audio_registry.webui.server.PeakCache") as peaks:
                app = ReviewApplication(None, config, project_name="unbound")
                state = app.state()
                self.assertEqual(state["audio_path"], "")
                self.assertEqual(state["audio_variants"], [])
                self.assertIsNone(state["selected_audio_id"])
                self.assertIsNone(state["alignment_warning"])
                self.assertEqual(state["duration"], 0)
                state["segments"][0]["text"] = "修改文字"
                saved = app.save({"revision": state["revision"], "segments": state["segments"], "tags": state["tags"]})
                self.assertEqual(saved["segments"][0]["text"], "修改文字")
                self.assertEqual(saved["audio_path"], "")
                self.assertIsNone(app.peaks)
                peaks.assert_not_called()
            with self.assertRaises(ValueError):
                app.retranscribe({"id": state["segments"][0]["id"]})
        script = (ASSET_DIR / "app.js").read_text(encoding="utf-8")
        self.assertIn("ui.reviewContent.hidden = !hasProject", script)
        self.assertIn("ui.retranscribe.disabled = ui.playSegment.disabled = !row || !hasAudio()", script)
        self.assertIn("ui.exportClip.disabled = !row || !hasAudio() || model.quickExportRunning", script)
        self.assertIn("if (!hasAudio()) { drawPeaks(context, width, height, null); return; }", script)
        self.assertIn("renderAll();\n    if (hasAudio()) await Promise.all", script)

    def test_blank_start_and_project_audio_menus_exist(self):
        html = (ASSET_DIR / "index.html").read_text(encoding="utf-8")
        script = (ASSET_DIR / "app.js").read_text(encoding="utf-8")
        self.assertIn('id="empty-state"', html)
        self.assertIn('id="project-menu"', html)
        self.assertIn('id="audio-menu"', html)
        self.assertIn("t('runtime.add_audio')", script)
        self.assertIn("t('runtime.create_project')", script)
        self.assertIn("add.dataset.action = 'create-projects'", script)
        self.assertIn("/api/create-projects", script)
        self.assertIn("if (model.dirty && !confirm(t('runtime.discard_switch'))) return", script)
        self.assertIn("deleted_audio_ids:", script)
        self.assertIn("t('runtime.audio_added'", script)
        self.assertIn('id="min-duration" type="number" min="0" step="0.1" value="0"', html)
        self.assertIn("minDuration: 0", script)
        self.assertIn("/api/global-ui-preferences", script)
        self.assertIn("persistGlobalPreferences(0)", script)

    def test_create_projects_from_webui_selects_the_new_empty_project(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            app = self.make_app(root)
            audio = root / "new.wav"
            audio.touch()

            def create(_config_path):
                app.database.create_project("new", audio)
                return ["new"]

            with (
                patch("audio_registry.webui.server.create_projects_isolated", side_effect=create),
                patch("audio_registry.webui.server._audio_duration_seconds", return_value=12),
            ):
                result = app.create_projects()
            self.assertEqual(result["count"], 1)
            self.assertEqual(result["created"], ["new"])
            self.assertEqual(result["state"]["project_name"], "new")
            self.assertEqual(result["state"]["segments"], [])
            self.assertEqual(len(result["state"]["audio_variants"]), 1)
            app.close()

    def test_header_uses_matching_save_then_refresh_controls(self):
        html = (ASSET_DIR / "index.html").read_text(encoding="utf-8")
        script = (ASSET_DIR / "app.js").read_text(encoding="utf-8")
        save = '<button id="save" class="button" type="button" disabled data-i18n="common.save">Save</button>'
        refresh = '<button id="refresh" class="button" type="button" disabled data-i18n="common.refresh">Refresh</button>'
        export_button = '<button id="export" class="button export-button" type="button" aria-expanded="false" aria-controls="export-menu" disabled data-i18n="common.export">Export ▾</button>'
        export_subtitles = '<button id="export-subtitles" class="button primary export-action" type="button" disabled data-i18n="review.export_subtitles">Export subtitles</button>'
        export_au = '<button id="export-au" class="button primary export-action" type="button" disabled data-i18n="review.export_audition">Export AU markers</button>'
        self.assertIn(save, html)
        self.assertIn(refresh, html)
        self.assertIn(export_subtitles, html)
        self.assertIn(export_au, html)
        self.assertIn(export_button, html)
        self.assertLess(html.index(save), html.index(refresh))
        self.assertLess(html.index(refresh), html.index(export_button))
        self.assertLess(html.index(export_subtitles), html.index(export_au))
        self.assertIn("t('runtime.discard_refresh')", script)
        self.assertIn("ui.refresh.addEventListener('click', () => loadState(true))", script)
        self.assertIn("/api/export-audition", script)
        self.assertIn("/api/export-subtitles", script)
        self.assertNotIn("保存校对", html + script)

    def test_export_menu_matches_assembly_menu_interactions(self):
        html = (ASSET_DIR / "index.html").read_text(encoding="utf-8")
        script = (ASSET_DIR / "app.js").read_text(encoding="utf-8")
        styles = (ASSET_DIR / "styles.css").read_text(encoding="utf-8")
        self.assertIn('id="export-menu" class="export-popover" role="dialog" data-i18n-aria-label="common.export" hidden', html)
        self.assertIn("ui.export.disabled = !ready; if (!ready) closeExportMenu()", script)
        self.assertIn("ui.exportMenu.hidden = !ui.exportMenu.hidden", script)
        self.assertIn("ui.export.setAttribute('aria-expanded', String(!ui.exportMenu.hidden))", script)
        self.assertIn("if (!ui.export.parentElement.contains(event.target)) closeExportMenu()", script)
        self.assertIn("if (event.key === 'Escape') closeExportMenu()", script)
        self.assertIn(".export-popover[hidden] { display: none; }", styles)
        self.assertIn("display: flex; flex-direction: column; gap: 10px", styles)

    def test_save_button_tracks_only_project_data_changes(self):
        script = (ASSET_DIR / "app.js").read_text(encoding="utf-8")
        self.assertNotIn("currentViewState", script)
        self.assertIn("const modified = Boolean(model.projectName && model.dirty)", script)
        self.assertIn("if (!model.dirty) return true", script)
        self.assertNotIn("payload.ui_preferences", script)
        self.assertIn("ui.save.disabled = !modified || busy", script)
        self.assertIn("ui.save.classList.toggle('primary', modified)", script)
        self.assertIn("finally { model.saving = false; updateDirtyIndicator(); updateRefreshIndicator(); }", script)
        self.assertNotIn("finally { ui.save.disabled = false", script)

    def test_refresh_checks_small_metadata_without_overwriting_edits(self):
        script = (ASSET_DIR / "app.js").read_text(encoding="utf-8")
        styles = (ASSET_DIR / "styles.css").read_text(encoding="utf-8")
        self.assertIn("#save:not(.primary), #refresh:not(.primary) { opacity: .42; }", styles)
        self.assertIn("setInterval(checkDatabaseChanges, 3000)", script)
        self.assertIn("document.hidden", script)
        self.assertIn("baseline !== model.updateCounters", script)
        self.assertIn("ui.refresh.classList.toggle('primary', model.remoteChanged)", script)
        self.assertIn("ui.refresh.disabled = !model.remoteChanged || !model.projectName", script)
        self.assertNotIn("ui.refresh.disabled = !model.projectName;", script)

    def test_project_counter_detects_content_audio_and_deletion(self):
        with tempfile.TemporaryDirectory() as directory:
            app = self.make_app(Path(directory))
            database = app.database
            original = database.project_update_counters(["movie"])
            self.assertEqual(original, app.state()["update_counters"])
            self.assertEqual(original, database.project_update_counters(["movie"]))
            asset = database.list_audio_assets("movie")[0]
            database.set_audio_offset("movie", asset["audio_path"], 0.2)
            audio_changed = database.project_update_counters(["movie"])
            self.assertNotEqual(original, audio_changed)
            document = app.state()
            document["segments"][0]["text"] = "新文字"
            app.save({"revision": document["revision"], "segments": document["segments"]})
            self.assertNotEqual(audio_changed, database.project_update_counters(["movie"]))
            database.delete_projects(["movie"])
            self.assertIsNone(database.project_update_counters(["movie"])["movie"])
            app.close()

    def test_project_counters_are_isolated_noop_safe_and_transactional(self):
        with tempfile.TemporaryDirectory() as directory:
            app = self.make_app(Path(directory))
            database = app.database
            database.create_review("other", Path(directory) / "movie.wav", [Segment(1, 2, "Speaker_1", "文字")])
            original = database.project_update_counters(["movie", "other"])
            with database._connection() as connection:
                connection.execute("UPDATE segments SET text=text")
                connection.commit()
            self.assertEqual(original, database.project_update_counters(["movie", "other"]))
            with database._connection() as connection:
                connection.execute("UPDATE segments SET text='回滚'")
                connection.rollback()
            self.assertEqual(original, database.project_update_counters(["movie", "other"]))
            with database._connection() as connection:
                connection.execute("UPDATE segments SET text='修改' WHERE source_id=(SELECT id FROM sources WHERE project_name='other')")
                connection.commit()
            changed = database.project_update_counters(["movie", "other"])
            self.assertEqual(original["movie"], changed["movie"])
            self.assertNotEqual(original["other"], changed["other"])
            exported = database.export_projects(["movie"], Path(directory) / "export")[0]
            database.import_project_file(exported, replace=True)
            self.assertNotEqual(original["movie"], database.project_update_counters(["movie"])["movie"])
            app.close()

    def test_review_uses_shared_speaker_tag_filters_and_row_annotations(self):
        html = (ASSET_DIR / "index.html").read_text(encoding="utf-8")
        script = (ASSET_DIR / "app.js").read_text(encoding="utf-8")
        styles = (ASSET_DIR / "styles.css").read_text(encoding="utf-8")
        self.assertIn('id="speaker-filter"', html)
        self.assertIn('id="speaker-search"', html)
        self.assertIn('id="tag-filter"', html)
        self.assertIn('id="segment-tag"', html)
        self.assertIn('id="segment-note"', html)
        self.assertIn('data-i18n="review.retranscribe">Retranscribe</button>', html)
        self.assertIn("ui.retranscribe.textContent = t('review.retranscribe')", script)
        self.assertIn("ui.retranscribe.textContent = t('runtime.retranscribing')", script)
        self.assertNotIn("本地重新识别本条", script)
        self.assertIn("if (event.target === ui.asrDialog) ui.asrDialog.close();", script)
        self.assertIn('selected_tags: [...model.selectedTags]', script)
        self.assertIn("function deleteSpeaker(", script)
        self.assertIn("function deleteTag(", script)
        self.assertLess(html.index('id="speaker"'), html.index('id="selected-id"'))
        self.assertIn('.inspector .inspector-meta select { width: 50%; }', styles)
        self.assertIn('.inspector-meta { height: 52px; min-height: 52px;', styles)
        self.assertIn('.panel-heading { height: 52px; min-height: 52px;', styles)
        self.assertIn('#speaker-filter .filter-options { max-height: 220px; }', styles)
        self.assertIn("const sortSpeakerNames = names =>", script)
        self.assertIn("/^speaker/i.test(left)", script)
        self.assertIn("t('runtime.speaker_merge_confirm'", script)
        self.assertIn("'runtime.merged'", script)

    def test_future_custom_dropdowns_close_on_outside_pointer_press(self):
        script = (ASSET_DIR / "app.js").read_text(encoding="utf-8")
        self.assertIn("document.querySelectorAll('details[open]')", script)
        self.assertIn("if (!menu.contains(event.target)) menu.open = false", script)

    def test_overview_uses_immediate_primary_pointer_positioning_and_is_named_full_timeline(self):
        html = (ASSET_DIR / "index.html").read_text(encoding="utf-8")
        script = (ASSET_DIR / "app.js").read_text(encoding="utf-8")
        self.assertIn('data-i18n="review.full_timeline">Full timeline</span>', html)
        self.assertNotIn('<span>整部电影</span>', html)
        self.assertIn("ui.overview.addEventListener('pointerdown'", script)
        self.assertIn("if (event.button !== 0 || !hasAudio()) return;", script)
        self.assertEqual(script.count("ui.overview.addEventListener("), 1)
        self.assertNotIn("ui.overview.addEventListener('click'", script)

    def test_detail_drag_pans_except_for_selected_segment_edges(self):
        script = (ASSET_DIR / "app.js").read_text(encoding="utf-8")
        styles = (ASSET_DIR / "styles.css").read_text(encoding="utf-8")
        self.assertIn("const edgeTolerancePixels = 12;", script)
        self.assertIn("function hitSelectedDetailEdge(clientX)", script)
        self.assertIn("const row = selected();", script)
        self.assertIn("const edge = hitSelectedDetailEdge(event.clientX);", script)
        self.assertIn("kind: 'pan', pointerStartX:", script)
        self.assertNotIn("'moving-marker'", script)
        self.assertNotIn("kind: hit.mode || 'move'", script)
        self.assertNotIn("cycleOverlap", script)
        self.assertIn("'resizing-marker'", script)
        self.assertIn("'edge-hover'", script)
        self.assertIn("#detail.panning { cursor: grabbing; }", styles)
        self.assertNotIn("moving-marker", styles)
        self.assertIn("#detail.edge-hover, #detail.resizing-marker { cursor: col-resize; }", styles)

    def test_detail_click_selects_segment_without_restoring_segment_drag(self):
        script = (ASSET_DIR / "app.js").read_text(encoding="utf-8")
        self.assertIn("function hitDetailSegment(clientX)", script)
        self.assertIn("clickedRowId: hitDetailSegment(event.clientX)?.id || null", script)
        self.assertIn("else if (clickedRowId) { toggle ? toggleSelection(clickedRowId) : setSingleSelection(clickedRowId); renderAll(); }", script)
        self.assertNotIn("kind: hit.mode || 'move'", script)

    def test_zoom_control_displays_custom_current_value_without_resizing(self):
        html = (ASSET_DIR / "index.html").read_text(encoding="utf-8")
        script = (ASSET_DIR / "app.js").read_text(encoding="utf-8")
        self.assertIn('id="zoom-current" value="" hidden', html)
        self.assertIn("function syncZoomControl()", script)
        self.assertIn("function stabilizeZoomControlWidth()", script)
        self.assertIn("ui.zoom.style.width = `${width}px`", script)
        self.assertNotIn("ui.zoom.value = [...ui.zoom.options].some", script)

    def test_audio_offset_is_per_asset_and_does_not_rewrite_project_coordinates(self):
        html = (ASSET_DIR / "index.html").read_text(encoding="utf-8")
        script = (ASSET_DIR / "app.js").read_text(encoding="utf-8")
        self.assertIn('id="audio-offset"', html)
        self.assertIn('data-i18n-aria-label="review.audio_offset"', html)
        self.assertIn('<span data-i18n="common.seconds">seconds</span>', html)
        self.assertIn("const toAudioTime = projectTime => projectTime + model.audioOffset", script)
        self.assertIn("const toProjectTime = audioTime => audioTime - model.audioOffset", script)
        self.assertIn("audio_offsets:", script)
        self.assertIn("selected_audio_id: model.selectedAudioId", script)

    def test_transcript_edits_sync_immediately_without_full_rerender(self):
        script = (ASSET_DIR / "app.js").read_text(encoding="utf-8")
        self.assertIn("ui.transcript.addEventListener('input'", script)
        self.assertIn("function updateTranscriptMirrors(row)", script)
        self.assertIn("button.dataset.segmentId = row.id;", script)
        self.assertIn("updateTranscriptMirrors(row); updateDirtyIndicator();", script)
        self.assertIn("if (!transcriptHistoryRecorded)", script)
        self.assertIn("resetTranscriptEditSession();", script)
        self.assertNotIn("editField(ui.transcript", script)

    def test_play_label_and_segment_playback_reset_are_present(self):
        html = (ASSET_DIR / "index.html").read_text(encoding="utf-8")
        script = (ASSET_DIR / "app.js").read_text(encoding="utf-8")
        self.assertIn('<span class="transport-label" data-i18n="review.play">Play</span>', html)
        self.assertIn('id="audio-status" class="audio-status"', html)
        self.assertIn("setAudioStatus(t('runtime.audio_seeking'), 'seeking')", script)
        self.assertIn("setAudioStatus(t('runtime.audio_loading'), 'waiting')", script)
        self.assertNotIn("playLabel.textContent = '正在定位…'", script)
        self.assertNotIn("playLabel.textContent = '正在读取音频…'", script)
        self.assertIn("model.segmentPlayback = null;", script)
        self.assertNotIn("从播放头播放", html + script)

    def test_segment_playback_button_toggles_pause_without_resizing(self):
        script = (ASSET_DIR / "app.js").read_text(encoding="utf-8")
        styles = (ASSET_DIR / "styles.css").read_text(encoding="utf-8")
        self.assertIn("model.playMode === 'segment' && !ui.audio.paused", script)
        self.assertIn("? t('runtime.pause_segment') : t('review.play_segment')", script)
        self.assertIn("function stabilizePlaybackButtonSizes()", script)
        self.assertIn("function lockControlSize(", script)
        self.assertIn("control.style.height = `${Math.ceil(height)}px`", script)
        self.assertIn("[t('review.play_segment'), t('runtime.pause_segment')]", script)
        self.assertIn(".transport-icon", styles)
        self.assertIn("height: 1.25em", styles)
        self.assertIn("line-height: 1", styles)
        self.assertIn(".audio-status.visible", styles)

    def test_sidebar_selection_while_playing_stops_at_selected_row_end(self):
        script = (ASSET_DIR / "app.js").read_text(encoding="utf-8")
        select_row = script[script.index("function selectRow("):script.index("async function centerOnSelected(")]
        self.assertIn("const wasPlaying = !ui.audio.paused;", select_row)
        self.assertIn("if (wasPlaying && row)", select_row)
        self.assertIn("model.playMode = 'segment';", select_row)
        self.assertIn("end: toAudioTime(row.end)", select_row)
        self.assertIn("allowLoop: false", select_row)
        self.assertIn("monitorSegmentBoundary();", select_row)
        self.assertIn("model.playMode = 'continuous';", select_row)

        overview_mouse = script[script.index("ui.overview.addEventListener('pointerdown'"):]
        overview_mouse = overview_mouse[:overview_mouse.index("ui.detail.addEventListener('pointerdown'")]
        self.assertIn("model.playMode = 'continuous';", overview_mouse)

    def test_cutting_and_list_export_are_removed_from_review_webui(self):
        html = (ASSET_DIR / "index.html").read_text(encoding="utf-8")
        script = (ASSET_DIR / "app.js").read_text(encoding="utf-8")
        self.assertNotIn('id="finalize"', html)
        self.assertNotIn('id="export-list"', html)
        self.assertNotIn("/api/finalize", script)
        self.assertNotIn("/api/gpt-sovits", script)

    def test_context_is_a_scrollable_full_timeline_that_centers_selection(self):
        html = (ASSET_DIR / "index.html").read_text(encoding="utf-8")
        script = (ASSET_DIR / "app.js").read_text(encoding="utf-8")
        self.assertIn('data-i18n="review.complete_timeline"', html)
        self.assertIn("rows.forEach(row =>", script)
        self.assertIn("function centerListRow(container, selector)", script)
        self.assertIn("centerListRow(ui.navigatorList, '.nav-row.primary')", script)
        self.assertIn("centerListRow(ui.contextList, '.context-row.current')", script)
        self.assertIn("currentRect.top - containerRect.top", script)
        self.assertIn("container.scrollTop = Math.max", script)

    def test_filtered_list_keeps_its_viewport_when_context_selection_is_not_filtered(self):
        script = (ASSET_DIR / "app.js").read_text(encoding="utf-8")
        styles = (ASSET_DIR / "styles.css").read_text(encoding="utf-8")
        self.assertIn("function captureListAnchor(container, selector, availableIds)", script)
        self.assertIn("const anchor = chosen < 0 ? captureListAnchor(ui.navigatorList, '.nav-row', rowIds) : null;", script)
        self.assertIn("anchorIndex >= 0 ? anchorIndex - anchor.renderedIndex : 0", script)
        self.assertIn("if (model.contextNeedsCenter && chosen >= 0)", script)
        self.assertIn("restoreListAnchor(ui.navigatorList, '.nav-row', anchor)", script)
        self.assertIn("container.querySelector(selector)", script)
        self.assertIn("overflow-y: auto", styles)
        self.assertNotIn("for (let offset = -3; offset <= 3; offset++)", script)

    def test_navigator_and_context_share_the_same_row_presentation(self):
        script = (ASSET_DIR / "app.js").read_text(encoding="utf-8")
        self.assertEqual(script.count("fillTimelineRow(button, row);"), 2)
        self.assertIn("who.style.color = speakerColor", script)
        self.assertNotIn("`${row.speaker || 'Unassigned'} · ${row.text", script)

    def test_desktop_sidebars_are_symmetric_around_wider_editor(self):
        styles = (ASSET_DIR / "styles.css").read_text(encoding="utf-8")
        self.assertIn(
            "grid-template-columns: minmax(260px, .75fr) minmax(400px, 1.4fr) minmax(260px, .75fr)",
            styles,
        )

    def test_sidebars_fill_editor_height_and_clamp_text(self):
        styles = (ASSET_DIR / "styles.css").read_text(encoding="utf-8")
        self.assertIn(".navigator, .context-panel { display: flex; flex-direction: column", styles)
        self.assertIn(".navigator-list, .context-list { flex: 1 1 0", styles)
        self.assertIn("overflow-x: hidden; overflow-y: auto", styles)
        self.assertIn(".row-text { white-space: normal", styles)
        self.assertIn("-webkit-line-clamp: 2", styles)
        self.assertIn(".nav-row, .context-row { display: block", styles)
        self.assertNotIn(".context-list { position: relative; display: grid", styles)

    def test_backspace_deletes_only_outside_editors_and_dialogs(self):
        html = (ASSET_DIR / "index.html").read_text(encoding="utf-8")
        script = (ASSET_DIR / "app.js").read_text(encoding="utf-8")
        self.assertIn('id="delete" class="button danger" type="button" data-i18n="common.delete">Delete</button>', html)
        self.assertIn("event.key === 'Backspace'", script)
        self.assertIn("!event.repeat", script)
        self.assertIn("!editing", script)
        self.assertIn("!document.querySelector('dialog[open]')", script)
        self.assertIn("ui.delete.click()", script)

    def test_delete_button_deletes_all_selected_rows_as_one_action(self):
        script = (ASSET_DIR / "app.js").read_text(encoding="utf-8")
        self.assertIn("const rows = active().filter(row => model.selectedIds.has(row.id));", script)
        self.assertIn("rows.forEach(row => { row.deleted = true; });", script)
        self.assertIn("deleteCount > 1 ? t('runtime.delete_count'", script)
        self.assertIn("t('runtime.rows_deleted'", script)

    def test_existing_tag_name_can_be_confirmed_and_merged(self):
        script = (ASSET_DIR / "app.js").read_text(encoding="utf-8")
        self.assertIn("t('runtime.tag_merge_confirm'", script)
        self.assertIn("model.tags = sortTagNames(", script)
        self.assertIn("t(merging ? 'runtime.merged' : 'runtime.renamed'", script)

    def test_tags_use_fixed_palette_with_first_tag_reserved_green(self):
        script = (ASSET_DIR / "app.js").read_text(encoding="utf-8")
        styles = (ASSET_DIR / "styles.css").read_text(encoding="utf-8")
        self.assertIn("const firstTagColor = '#71d47f'", script)
        self.assertIn("const tagPalette = palette.filter(color => color !== firstTagColor)", script)
        self.assertIn("const tagColors = new Map()", script)
        self.assertIn("tagPalette[tagColorCursor % tagPalette.length]", script)
        self.assertIn("syncTagColors(model.tags)", script)
        self.assertIn('style="--tag-color:${tagColor(name)}"', script)
        self.assertIn("ui.segmentTag.style.setProperty('--tag-color', tagColor(row.tag))", script)
        self.assertIn(".tag-select.tag-colored:not(.missing-value)", styles)
        self.assertIn("function createTagOption(name, selected = false)", script)
        self.assertIn("option.style.setProperty('--tag-color', color)", script)
        self.assertIn(".tag-select option.tag-option", styles)

    def test_tag_options_use_derived_name_sorting_without_manual_order(self):
        script = (ASSET_DIR / "app.js").read_text(encoding="utf-8")
        styles = (ASSET_DIR / "styles.css").read_text(encoding="utf-8")
        self.assertIn("const sortTagNames = names =>", script)
        self.assertIn("model.tags = sortTagNames(", script)
        self.assertNotIn('tag-drag-handle', script)
        self.assertNotIn("ui.tagOptions.addEventListener('dragstart'", script)
        self.assertNotIn(".managed-filter-option.drop-before", styles)

    def test_only_visible_selected_segment_edges_are_detail_timeline_mouse_targets(self):
        script = (ASSET_DIR / "app.js").read_text(encoding="utf-8")
        self.assertIn(
            "if (!row || (!isFiltered(row) && !model.showHidden)) return {...position, row: null, mode: null};",
            script,
        )
        self.assertNotIn("const candidates =", script)
        self.assertNotIn("const pool =", script)

    def make_app(self, root: Path):
        audio = root / "movie.wav"
        audio.write_bytes(bytes(range(256)) * 8)
        config_file = root / "config.yaml"
        config_file.write_text("paths:\n  output_dir: output\n", encoding="utf-8")
        config = load_config(config_file)
        ProjectDatabase(database_path_for(config.paths.data_dir, legacy_directories=(config.paths.output_dir,))).create_review(
            "movie", audio, [Segment(1, 2, "Speaker_1", "旧文字")]
        )
        with patch("audio_registry.webui.server._audio_duration_seconds", return_value=10):
            return ReviewApplication(audio, config, project_name="movie")

    def test_state_and_save(self):
        with tempfile.TemporaryDirectory() as directory:
            app = self.make_app(Path(directory))
            self.assertEqual(app.state()["audio_name"], "movie.wav")
            document = app.state()
            document["segments"][0]["text"] = "人工文字"
            saved = app.save({"revision": 1, "segments": document["segments"]})
            self.assertEqual(saved["revision"], 2)
            self.assertEqual(saved["segments"][0]["text"], "人工文字")

    def test_review_saves_tag_note_and_speaker_to_shared_database(self):
        with tempfile.TemporaryDirectory() as directory:
            app = self.make_app(Path(directory))
            document = app.state()
            row = document["segments"][0]
            row.update({"speaker": "角色甲", "tag": "精选", "note": "保留这条"})
            saved = app.save({
                "revision": document["revision"], "segments": document["segments"],
                "tags": ["训练集", "精选"],
            })
            self.assertEqual(saved["segments"][0]["speaker"], "角色甲")
            self.assertEqual(saved["segments"][0]["tag"], "精选")
            self.assertEqual(saved["segments"][0]["note"], "保留这条")

    def test_single_clip_export_chooses_directory_and_uses_webui2_processing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            app = self.make_app(root)
            destination = root / "chosen"
            destination.mkdir()
            output = destination / "movie-00.00.01.125-00.00.02.125.wav"
            completed = Segment(1, 2, "Speaker_1", "文字", str(output))
            state = app.state()
            row = state["segments"][0]
            with patch("audio_registry.webui.server.choose_output_directory_isolated", return_value=destination), \
                 patch("audio_registry.webui.server.export_audio_clip", return_value=completed) as export:
                result = app.export_clip({**row, "id": "UNSAVED-ROW", "audio_offset": 0.125})
            self.assertFalse(result["cancelled"])
            self.assertEqual(result["path"], str(output.resolve()))
            self.assertEqual(export.call_args.kwargs["output_dir"], destination)
            self.assertEqual(export.call_args.kwargs["time_offset"], 0.125)
            self.assertEqual(export.call_args.kwargs["export_settings"], load_config(app.config.config_path).clip_export)
            self.assertEqual(export.call_args.args[2], Segment(1, 2, "Speaker_1", "旧文字"))
            with patch("audio_registry.webui.server.choose_output_directory_isolated", return_value=None), \
                 patch("audio_registry.webui.server.export_audio_clip") as cancelled_export:
                self.assertEqual(app.export_clip({**row, "audio_offset": 0}), {"cancelled": True})
            cancelled_export.assert_not_called()

    def test_single_clip_directory_picker_is_isolated(self):
        with tempfile.TemporaryDirectory() as directory:
            selected = Path(directory).resolve()
            with patch("audio_registry.webui.server.subprocess.run", return_value=SimpleNamespace(stdout=json.dumps(str(selected)))) as run:
                self.assertEqual(choose_output_directory_isolated(), selected)
            self.assertIn("directory_picker_process.py", str(run.call_args.args[0][1]))
            self.assertTrue(run.call_args.kwargs["check"])

    def test_single_clip_button_is_beside_retranscribe_and_uses_picker_endpoint(self):
        html = (ASSET_DIR / "index.html").read_text(encoding="utf-8")
        script = (ASSET_DIR / "app.js").read_text(encoding="utf-8")
        self.assertIn('<button id="export-clip" class="button" type="button" data-i18n="review.clip">Clip</button>', html)
        self.assertLess(html.index('id="retranscribe"'), html.index('id="export-clip"'))
        self.assertIn("'/api/export-clip'", script)
        self.assertIn("audio_offset:model.audioOffset", script)
        self.assertIn("result.cancelled ? t('runtime.clip_cancelled')", script)
        self.assertIn("ui.exportClip.textContent = t('runtime.clipping')", script)
        self.assertIn("ui.exportClip.textContent = t('review.clip')", script)

    def test_blank_application_selects_default_audio_and_stages_audio_changes_until_save(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            configured = self.make_app(root)
            config = configured.config
            configured.close()
            database = ProjectDatabase(database_path_for(config.paths.data_dir, legacy_directories=(config.paths.output_dir,)))
            original = root / "movie.wav"
            replacement = root / "movie-clean.wav"
            replacement.write_bytes(b"replacement")
            app = ReviewApplication(None, config)
            blank = app.state()
            self.assertIsNone(blank["project_name"])
            self.assertEqual([row["project_name"] for row in blank["available_projects"]], ["movie"])
            with patch("audio_registry.webui.server._audio_duration_seconds", return_value=10):
                selected = app.select("movie")
                self.assertTrue(Path(selected["audio_variants"][0]["audio_path"]).samefile(original))
                with patch("audio_registry.webui.server.choose_audio_variants_isolated", return_value=[replacement]):
                    staged = app.add_audio()["state"]
            self.assertEqual(len(database.list_audio_assets("movie")), 1)
            pending = next(row for row in staged["audio_variants"] if row["pending"])
            saved = app.save({
                "revision": staged["revision"], "segments": staged["segments"],
                "selected_audio_id": pending["id"],
                "deleted_audio_ids": [selected["selected_audio_id"]],
                "audio_offsets": {pending["id"]: 0.25},
            })
            self.assertEqual(len(database.list_audio_assets("movie")), 1)
            self.assertTrue(Path(saved["audio_variants"][0]["audio_path"]).samefile(replacement))
            self.assertEqual(saved["audio_offset"], 0.25)

    def test_filter_preferences_are_not_saved_with_the_review(self):
        with tempfile.TemporaryDirectory() as directory:
            app = self.make_app(Path(directory))
            preferences = {
                "selected_speakers": ["角色甲"],
                "min_duration": 1.25,
                "show_hidden": False,
            }
            document = app.state()
            document["segments"][0]["speaker"] = "角色甲"
            saved = app.save(
                {
                    "revision": 1,
                    "segments": document["segments"],
                    "ui_preferences": preferences,
                }
            )
            self.assertNotIn("ui_preferences", saved)
            self.assertNotIn("ui_preferences", app.state())
            self.assertEqual(app.state()["speakers"], ["角色甲"])

    def test_selected_segments_and_filters_are_saved_and_restored_locally(self):
        script = (ASSET_DIR / "app.js").read_text(encoding="utf-8")
        self.assertIn("selected_segment_ids: [...model.selectedIds]", script)
        self.assertIn("primary_segment_id: model.selectedId", script)
        self.assertIn("localStorage.setItem(REVIEW_VIEW_KEY + model.projectName", script)
        self.assertIn("const preferences = readReviewView(model.projectName)", script)
        self.assertNotIn("data.ui_preferences", script)
        self.assertIn("preferences?.selected_segment_ids", script)
        self.assertIn("preferences?.primary_segment_id", script)
        self.assertIn("if (model.selectedId) model.selectedIds.add(model.selectedId);", script)
        self.assertIn("centerOnSelected(false)", script)

    def test_audio_offset_is_saved_per_asset_without_changing_segment_times(self):
        with tempfile.TemporaryDirectory() as directory:
            app = self.make_app(Path(directory))
            document = app.state()
            saved = app.save(
                {
                    "revision": document["revision"],
                    "segments": document["segments"],
                    "audio_offset": 0.125,
                }
            )
            self.assertEqual(saved["segments"][0]["start"], 1)
            self.assertEqual(app.state()["audio_offset"], 0.125)
            self.assertEqual(app.state()["segments"][0]["start"], 1)

    def test_audition_export_uses_current_filters_and_offset_in_tab_delimited_csv(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            app = self.make_app(root)
            document = app.state()
            document["segments"].extend([
                {**document["segments"][0], "id": "SAME", "start": 2.1, "end": 2.8},
                {**document["segments"][0], "id": "SHORT", "start": 3, "end": 3.25},
                {**document["segments"][0], "id": "OTHER", "start": 4, "end": 5, "speaker": "Speaker_2"},
            ])
            app.save({
                "revision": document["revision"], "segments": document["segments"],
                "audio_offset": 0.125,
            })
            result = app.export_audition_markers({
                "selected_speakers": ["Speaker_1", "Speaker_2"], "min_duration": 0.5,
                "audio_offset": 0.125,
            })
            output = Path(result["path"])
            self.assertEqual(output.name, t("backend.audition_filename", stem="movie"))
            self.assertEqual(result["count"], 3)
            raw = output.read_bytes()
            self.assertTrue(raw.startswith(b"\xef\xbb\xbf"))
            content = raw.decode("utf-8-sig")
            self.assertIn("Name\tStart\tDuration\tTime Format\tType\tDescription\r\n", content)
            self.assertIn("旧文字\t0:01.125\t0:01.000\tdecimal\tCue\tSpeaker_1 · 旧文字\r\n", content)
            self.assertIn("旧文字\t0:02.225\t0:00.700\tdecimal\tCue\tSpeaker_1 · 旧文字\r\n", content)
            self.assertIn("旧文字\t0:04.125\t0:01.000\tdecimal\tCue\tSpeaker_2 · 旧文字\r\n", content)
            self.assertLess(content.index("0:01.125"), content.index("0:02.225"))
            self.assertLess(content.index("0:02.225"), content.index("0:04.125"))
            self.assertNotIn("SHORT", content)
            self.assertNotIn("OTHER", content)

    def test_audition_decimal_time_keeps_minutes_and_milliseconds(self):
        self.assertEqual(_audition_decimal_time(450.385), "7:30.385")

    def test_subtitle_export_uses_current_filters_offset_and_standard_srt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            app = self.make_app(root)
            document = app.state()
            document["segments"].extend([
                {**document["segments"][0], "id": "SECOND", "start": 2.1, "end": 2.8, "text": "第二句\n下一行"},
                {**document["segments"][0], "id": "SHORT", "start": 3, "end": 3.25, "text": "过短"},
                {**document["segments"][0], "id": "OTHER", "start": 4, "end": 5, "speaker": "Speaker_2", "text": "其他人"},
                {**document["segments"][0], "id": "EMPTY", "start": 6, "end": 7, "text": "  "},
            ])
            app.save({"revision": document["revision"], "segments": document["segments"], "audio_offset": 0.125})
            result = app.export_subtitles({
                "selected_speakers": ["Speaker_1"], "min_duration": 0.5,
                "audio_offset": 0.125,
            })
            output = Path(result["path"])
            self.assertEqual(output.name, t("backend.subtitle_filename", stem="movie"))
            self.assertEqual(result["count"], 2)
            raw = output.read_bytes()
            self.assertTrue(raw.startswith(b"\xef\xbb\xbf"))
            content = raw.decode("utf-8-sig")
            self.assertIn("1\r\n00:00:01,125 --> 00:00:02,125\r\n旧文字\r\n\r\n", content)
            self.assertIn("2\r\n00:00:02,225 --> 00:00:02,925\r\n第二句\r\n下一行\r\n\r\n", content)
            self.assertNotIn("过短", content)
            self.assertNotIn("其他人", content)

    def test_srt_time_keeps_hours_and_milliseconds(self):
        self.assertEqual(_srt_time(4500.385), "01:15:00,385")

    def test_speakers_with_no_active_rows_are_hidden(self):
        with tempfile.TemporaryDirectory() as directory:
            app = self.make_app(Path(directory))
            document = app.state()
            document["segments"].append(
                {
                    "id": "SEG-DELETED",
                    "start": 3,
                    "end": 4,
                    "speaker": "已清空角色",
                    "text": "",
                    "deleted": True,
                    "manual_text": False,
                    "needs_asr": False,
                    "origin_ids": [],
                }
            )
            app.save({"revision": 1, "segments": document["segments"]})
            self.assertEqual(app.state()["speakers"], ["Speaker_1"])

    def test_manual_retranscription_reuses_one_backend(self):
        with tempfile.TemporaryDirectory() as directory:
            app = self.make_app(Path(directory))
            backend = FakeReviewAsr()
            with patch("audio_registry.webui.server.create_asr_backend", return_value=backend) as factory:
                first = app.retranscribe({"start": 1, "end": 2, "speaker": "Speaker_1"})
                second = app.retranscribe({"start": 2, "end": 3, "speaker": "Speaker_1"})
            factory.assert_called_once()
            self.assertEqual(first["text"], "识别结果 1")
            self.assertEqual(second["text"], "识别结果 2")
            app.close()

    def test_http_audio_range_and_state(self):
        with tempfile.TemporaryDirectory() as directory:
            app = self.make_app(Path(directory))
            server = ReviewServer(("127.0.0.1", 0), app)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base = f"http://127.0.0.1:{server.server_port}"
                with urllib.request.urlopen(base + "/api/state") as response:
                    state = json.load(response)
                self.assertEqual(state["duration"], 10)
                with patch.object(app, "state", side_effect=AssertionError("Must not load full state")):
                    with urllib.request.urlopen(base + "/api/update-counters?project=movie") as response:
                        self.assertEqual(json.load(response)["update_counters"], state["update_counters"])
                    with urllib.request.urlopen(base + "/api/update-counters?project=missing") as response:
                        self.assertIsNone(json.load(response)["update_counters"]["missing"])
                settings_request = urllib.request.Request(
                    base + "/api/global-ui-preferences",
                    data=json.dumps({"min_duration": 0.25, "show_hidden": False}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(settings_request) as response:
                    settings = json.load(response)
                self.assertEqual(settings, {"min_duration": 0.25, "show_hidden": False, "min_duration_empty_only": False, "duration_filter_enabled": True})
                self.assertEqual(app.state()["global_ui_preferences"], settings)
                self.assertTrue((Path(directory) / "config.local.yaml").is_file())
                request = urllib.request.Request(base + "/api/audio", headers={"Range": "bytes=10-19"})
                with urllib.request.urlopen(request) as response:
                    self.assertEqual(response.status, 206)
                    self.assertEqual(len(response.read()), 10)
            finally:
                server.shutdown()
                server.server_close()
                app.close()
                thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
