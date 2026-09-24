window.AudioRegistryI18n.ready.then(() => {
  'use strict';

  const t = window.AudioRegistryI18n.t;

  const el = id => document.getElementById(id);
  const ui = {
    app: el('app'), audio: el('audio'), overview: el('overview'), detail: el('detail'),
    overviewLoading: el('overview-loading'), detailLoading: el('detail-loading'),
    projectMenu: el('project-menu'), projectSummary: el('project-summary'), projectOptions: el('project-options'), audioMenu: el('audio-menu'), audioSummary: el('audio-summary'), audioOptions: el('audio-options'),
    emptyState: el('empty-state'), reviewFilters: el('review-filters'), reviewContent: el('review-content'), reviewStatusbar: el('review-statusbar'), overviewRange: el('overview-range'), detailRange: el('detail-range'),
    speakerFilterSummary: el('speaker-filter-summary'), speakerFilters: el('speaker-filters'), speakerSearch: el('speaker-search'), speakerAll: el('speaker-all'), speakerNone: el('speaker-none'), speakerFilterAdd: el('speaker-filter-add'),
    tagFilterSummary: el('tag-filter-summary'), tagOptions: el('tag-options'), tagAll: el('tag-all'), tagNone: el('tag-none'), tagFilterAdd: el('tag-filter-add'), minDuration: el('min-duration'), durationMenu: el('duration-filter-menu'), durationEmptyOnly: el('duration-empty-only'), durationHide: el('duration-hide'), durationDelete: el('duration-delete'), showHidden: el('show-hidden'), audioOffset: el('audio-offset'), alignmentWarning: el('alignment-warning'), filterCount: el('filter-count'),
    navigatorList: el('navigator-list'), navigatorCount: el('navigator-count'), contextList: el('context-list'), contextCount: el('context-count'),
    selectedId: el('selected-id'), start: el('start-time'), end: el('end-time'), duration: el('segment-duration'), speaker: el('speaker'), transcript: el('transcript'), segmentTag: el('segment-tag'), segmentNote: el('segment-note'),
    save: el('save'), refresh: el('refresh'), export: el('export'), exportMenu: el('export-menu'), exportSubtitles: el('export-subtitles'), exportAu: el('export-au'), undo: el('undo'), redo: el('redo'), play: el('play'), playSegment: el('play-segment'), loop: el('loop'), add: el('add'), split: el('split'), merge: el('merge'), delete: el('delete'), retranscribe: el('retranscribe'), exportClip: el('export-clip'),
    playTime: el('play-time'), audioStatus: el('audio-status'), zoom: el('zoom'), zoomCurrent: el('zoom-current'), saveState: el('save-state'), validationState: el('validation-state'),
    asrDialog: el('asr-dialog'), asrOld: el('asr-old'), asrNew: el('asr-new'), acceptAsr: el('accept-asr'),
    speakerDialog: el('speaker-dialog'), newSegmentSpeaker: el('new-segment-speaker'), assignSpeaker: el('assign-speaker'),
    speakerNameDialog: el('speaker-name-dialog'), newSpeakerName: el('new-speaker-name'), cancelNewSpeaker: el('cancel-new-speaker'),
    tagNameDialog: el('tag-name-dialog'), newTagName: el('new-tag-name'), cancelNewTag: el('cancel-new-tag'),
    toast: el('toast')
  };

  const model = {
    revision: 0, duration: 0, segments: [], speakers: [], selectedId: null, selectedIds: new Set(),
    selectedSpeakers: new Set(), tags: [], selectedTags: new Set(), minDuration: 0, minDurationEmptyOnly: false, durationFilterEnabled: true, showHidden: true,
    viewStart: 0, viewDuration: 30, overviewPeaks: null, detailPeaks: null,
    history: [], future: [], dirty: false, saving: false, viewReady: false, updateCounters: null, remoteChanged: false, createMode: false, drag: null, playMode: 'continuous',
    filterPinnedIds: new Set(), pendingSpeakerId: null, pendingSpeakerCreate: null, newSegmentSpeakerPrevious: '',
    peakRequest: 0, colors: new Map(),
    segmentPlayback: null, segmentStopTimer: null, contextNeedsCenter: true,
    projectName: '', availableProjects: [], audioVariants: [], selectedAudioId: null, deletedAudioIds: new Set(), audioOffset: 0, alignmentWarning: '', pendingTagCreate: null, quickExportRunning: false
  };

  const palette = ['#56d6c2', '#7fa5ff', '#d68cf0', '#f0b862', '#ff7d8b', '#71d47f', '#56bee8', '#d6d06d'];
  document.addEventListener('pointerdown', event => {
    document.querySelectorAll('details[open]').forEach(menu => {
      if (!menu.contains(event.target)) menu.open = false;
    });
  });
  document.addEventListener('toggle', event => {
    if (!(event.target instanceof HTMLDetailsElement) || !event.target.open) return;
    document.querySelectorAll('details[open]').forEach(menu => { if (menu !== event.target) menu.open = false; });
  }, true);
  const cloneSegments = () => JSON.parse(JSON.stringify(model.segments));
  const active = () => model.segments.filter(row => !row.deleted).sort((a, b) => a.start - b.start || a.end - b.end || a.id.localeCompare(b.id));
  const selected = () => model.segments.find(row => row.id === model.selectedId && !row.deleted) || null;
  const durationOf = row => row.end - row.start;
  const sortSpeakerNames = names => [...new Set(names)].sort((left, right) => {
    const leftGenerated = /^speaker/i.test(left), rightGenerated = /^speaker/i.test(right);
    return Number(leftGenerated) - Number(rightGenerated) || left.localeCompare(right, 'zh-CN', {numeric:true});
  });
  const sortTagNames = names => [...new Set(names)].sort((left, right) => left.localeCompare(right, 'zh-CN', {numeric:true}));
  const toAudioTime = projectTime => projectTime + model.audioOffset;
  const toProjectTime = audioTime => audioTime - model.audioOffset;
  const matchesDurationFilter = (row, threshold, emptyOnly) => durationOf(row) < threshold - 1e-9 && (!emptyOnly || !String(row.text || '').trim());
  const matchesFilter = row => (model.selectedSpeakers.has(row.speaker || 'Unassigned') || !model.speakers.includes(row.speaker || 'Unassigned')) && (model.selectedTags.has(row.tag || model.tags[0]) || !model.tags.includes(row.tag || model.tags[0])) && (!model.durationFilterEnabled || !matchesDurationFilter(row, model.minDuration, model.minDurationEmptyOnly));
  const isFiltered = row => model.filterPinnedIds.has(row.id) || matchesFilter(row);
  const filtered = () => active().filter(isFiltered);
  const speakerColor = speaker => {
    if (!model.colors.has(speaker)) model.colors.set(speaker, palette[model.colors.size % palette.length]);
    return model.colors.get(speaker);
  };

  function formatTime(seconds) {
    seconds = Math.max(0, Number(seconds) || 0);
    let millis = Math.round(seconds * 1000);
    const hours = Math.floor(millis / 3600000); millis %= 3600000;
    const minutes = Math.floor(millis / 60000); millis %= 60000;
    const secs = Math.floor(millis / 1000); millis %= 1000;
    return `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(secs).padStart(2, '0')}.${String(millis).padStart(3, '0')}`;
  }

  function parseTime(value) {
    const text = String(value).trim();
    if (/^\d+(\.\d+)?$/.test(text)) return Number(text);
    const match = text.match(/^(?:(\d+):)?(\d{1,2}):(\d{1,2})(?:[.,](\d{1,3}))?$/);
    if (!match) throw new Error(t('runtime.time_format'));
    const [, h = '0', m, s, ms = '0'] = match;
    if (Number(m) > 59 || Number(s) > 59) throw new Error(t('runtime.minute_limit'));
    return Number(h) * 3600 + Number(m) * 60 + Number(s) + Number(ms.padEnd(3, '0')) / 1000;
  }

  function formatZoomWindow(seconds) {
    const value = seconds < 60 ? seconds : seconds / 60;
    const unit = seconds < 60 ? t('runtime.second') : t('runtime.minute');
    return `${Number(value.toFixed(1))} ${unit}`;
  }

  function syncZoomControl() {
    const preset = [...ui.zoom.options].find(option => option !== ui.zoomCurrent && Math.abs(Number(option.value) - model.viewDuration) < 1e-9);
    if (preset) { ui.zoom.value = preset.value; return; }
    ui.zoomCurrent.value = String(model.viewDuration);
    ui.zoomCurrent.textContent = formatZoomWindow(model.viewDuration);
    ui.zoomCurrent.selected = true;
  }

  function stabilizeZoomControlWidth() {
    const probe = ui.zoom.cloneNode(true);
    probe.removeAttribute('id');
    [`000.0 ${t('runtime.second')}`, `10.0 ${t('runtime.minute')}`].forEach(label => { const option = document.createElement('option'); option.textContent = label; probe.append(option); });
    Object.assign(probe.style, {position: 'fixed', visibility: 'hidden', pointerEvents: 'none', width: 'auto', left: '-10000px', top: '-10000px'});
    document.body.append(probe);
    const width = Math.ceil(probe.getBoundingClientRect().width);
    probe.remove();
    if (width > 0) ui.zoom.style.width = `${width}px`;
  }

  function lockControlSize(control, variants, applyVariant) {
    const probe = control.cloneNode(true);
    probe.removeAttribute('id');
    Object.assign(probe.style, {position: 'fixed', visibility: 'hidden', pointerEvents: 'none', width: 'auto', height: 'auto', left: '-10000px', top: '-10000px'});
    document.body.append(probe);
    let width = 0; let height = 0;
    variants.forEach(variant => {
      applyVariant(probe, variant);
      const rect = probe.getBoundingClientRect(); width = Math.max(width, rect.width); height = Math.max(height, rect.height);
    });
    probe.remove();
    if (width > 0) control.style.width = `${Math.ceil(width)}px`;
    if (height > 0) control.style.height = `${Math.ceil(height)}px`;
  }

  function stabilizePlaybackButtonSizes() {
    lockControlSize(ui.play, [{icon: '▶', label: t('review.play')}, {icon: '❚❚', label: t('runtime.pause')}], (button, state) => {
      button.querySelector('.transport-icon').textContent = state.icon;
      button.querySelector('.transport-label').textContent = state.label;
    });
    lockControlSize(ui.playSegment, [t('review.play_segment'), t('runtime.pause_segment')], (button, label) => { button.textContent = label; });
  }

  async function request(url, options = {}) {
    const response = await fetch(url, {cache: 'no-store', ...options});
    const text = await response.text();
    let payload;
    try { payload = JSON.parse(text); }
    catch (_error) {
      throw new Error(response.ok
        ? t('runtime.invalid_response')
        : t('runtime.unsupported_request', {status: response.status}));
    }
    if (!response.ok) throw new Error(payload.error || t('runtime.request_failed', {status: response.status}));
    return payload;
  }

  let globalPreferencesTimer = null;
  function persistGlobalPreferences(delay = 400) {
    clearTimeout(globalPreferencesTimer);
    globalPreferencesTimer = setTimeout(async () => {
      try {
        await request('/api/global-ui-preferences', {
          method: 'POST', headers: {'Content-Type':'application/json'},
          body: JSON.stringify({min_duration:model.minDuration, min_duration_empty_only:model.minDurationEmptyOnly, duration_filter_enabled:model.durationFilterEnabled, show_hidden:model.showHidden}),
        });
      } catch (error) { toast(t('runtime.settings_save_failed', {error: error.message})); }
    }, delay);
  }

  function renderSourceMenus() {
    ui.projectSummary.textContent = model.projectName || t('common.select_project');
    ui.projectOptions.replaceChildren(...model.availableProjects.map(project => {
      const button = document.createElement('button'); button.type = 'button'; button.className = `source-option ${project.project_name === model.projectName ? 'selected' : ''}`;
      button.dataset.action = 'select-project'; button.dataset.project = project.project_name;
      const name = document.createElement('span'); name.className = 'option-name'; name.textContent = project.project_name;
      const count = document.createElement('small'); count.textContent = t('runtime.rows', {count: project.segment_count});
      button.append(name, count); return button;
    }), (() => { const add = document.createElement('button'); add.type = 'button'; add.className = 'source-option source-add'; add.dataset.action = 'create-projects'; add.textContent = `＋ ${t('runtime.create_project')}`; return add; })());
    ui.audioMenu.hidden = !model.projectName;
    const visibleAudio = model.audioVariants.filter(asset => !model.deletedAudioIds.has(String(asset.id)));
    const current = visibleAudio.find(asset => String(asset.id) === String(model.selectedAudioId));
    ui.audioSummary.textContent = current?.name || t('common.select_audio');
    ui.audioOptions.replaceChildren(...visibleAudio.map(asset => {
      const row = document.createElement('div'); row.className = `source-option ${String(asset.id) === String(model.selectedAudioId) ? 'selected' : ''}`;
      const choose = document.createElement('button'); choose.type = 'button'; choose.className = 'option-main'; choose.dataset.action = 'select-audio'; choose.dataset.asset = asset.id; choose.disabled = asset.available === false; choose.setAttribute('aria-label', t('runtime.select_audio_named', {name:asset.name}));
      const name = document.createElement('span'); name.className = 'option-name'; name.textContent = `${asset.name}${asset.pending ? t('runtime.pending_save') : ''}${asset.available === false ? t('runtime.file_missing') : ''}`; choose.append(name);
      const remove = document.createElement('button'); remove.type = 'button'; remove.className = 'source-delete'; remove.dataset.action = 'delete-audio'; remove.dataset.asset = asset.id; remove.title = t('runtime.delete_audio_path', {name:asset.name}); remove.setAttribute('aria-label', remove.title); remove.textContent = t('common.delete');
      row.append(choose, remove); return row;
    }), (() => { const add = document.createElement('button'); add.type = 'button'; add.className = 'source-option source-add'; add.dataset.action = 'add-audio'; add.textContent = `＋ ${t('runtime.add_audio')}`; return add; })());
  }

  function showWorkspace(message = '') {
    const ready = Boolean(model.projectName && model.selectedAudioId && model.duration > 0);
    const hasProject = Boolean(model.projectName);
    ui.emptyState.hidden = hasProject; ui.reviewFilters.hidden = !hasProject; ui.reviewContent.hidden = !hasProject; ui.reviewStatusbar.hidden = !hasProject;
    updateDirtyIndicator(); updateRefreshIndicator(); ui.exportSubtitles.disabled = ui.exportAu.disabled = !ready;
    ui.export.disabled = !ready; if (!ready) closeExportMenu();
    [ui.play, ui.loop, ui.add, ui.zoom, ui.audioOffset].forEach(control => control.disabled = !ready);
    if (!ready) {
      ui.overviewLoading.hidden = ui.detailLoading.hidden = false;
      ui.overviewLoading.textContent = ui.detailLoading.textContent = hasProject ? t('runtime.no_audio') : '';
      ui.overviewRange.textContent = ui.detailRange.textContent = '—';
    }
    const strong = ui.emptyState.querySelector('strong'), detail = ui.emptyState.querySelector('span');
    if (!model.projectName) { strong.textContent = t('review.empty_title'); detail.textContent = t('review.empty_help'); }
  }

  async function applyState(data, preserveReview = false) {
    persistReviewView(); model.viewReady = false;
    const sameProject = preserveReview && model.projectName && model.projectName === data.project_name;
    const preserved = sameProject ? {segments:model.segments, speakers:model.speakers, selectedSpeakers:model.selectedSpeakers, tags:model.tags, selectedTags:model.selectedTags, selectedId:model.selectedId, selectedIds:model.selectedIds, history:model.history, future:model.future, dirty:model.dirty, offsets:new Map(model.audioVariants.map(asset => [String(asset.id), asset.offset_seconds]))} : null;
    ui.audio.pause(); stopSegmentMonitor(); model.segmentPlayback = null;
    model.availableProjects = data.available_projects || [];
    model.projectName = data.project_name || '';
    if (!preserved) { model.updateCounters = JSON.stringify(data.update_counters || {}); model.remoteChanged = false; }
    model.audioVariants = data.audio_variants || [];
    if (preserved) model.audioVariants.forEach(asset => { if (preserved.offsets.has(String(asset.id))) asset.offset_seconds = preserved.offsets.get(String(asset.id)); });
    model.selectedAudioId = data.selected_audio_id || null;
    if (!sameProject) model.deletedAudioIds = new Set();
    renderSourceMenus();
    if (!model.projectName) { model.segments = []; model.speakers = []; model.tags = []; model.selectedTags.clear(); showWorkspace(); return; }
    model.revision = data.revision;
    model.duration = Number(data.duration) || 0;
    model.audioOffset = Number(data.audio_offset) || 0;
    model.alignmentWarning = data.alignment_warning || '';
    model.segments = preserved?.segments || data.segments || [];
    model.speakers = sortSpeakerNames(preserved?.speakers || data.speakers || []);
    model.tags = sortTagNames(preserved?.tags || data.tags || ['1']);
    model.history = preserved?.history || []; model.future = preserved?.future || []; model.dirty = preserved?.dirty || false; model.filterPinnedIds.clear(); model.createMode = false; model.drag = null; model.contextNeedsCenter = true;
    const preferences = readReviewView(model.projectName);
    const globalPreferences = data.global_ui_preferences || {min_duration:0, show_hidden:true};
    if (preserved) { model.selectedSpeakers = preserved.selectedSpeakers; model.selectedTags = preserved.selectedTags; }
    else if (preferences) {
      const savedSpeakers = new Set(preferences.selected_speakers || []);
      model.selectedSpeakers = new Set(model.speakers.filter(name => preferences.all_speakers_selected || savedSpeakers.has(name)));
      const savedTags = new Set(preferences.selected_tags || model.tags);
      model.selectedTags = new Set(model.tags.filter(name => preferences.all_tags_selected || savedTags.has(name)));
    } else { model.selectedSpeakers = new Set(model.speakers); model.selectedTags = new Set(model.tags); }
    if (!preserved) ui.speakerSearch.value = preferences?.speaker_search || '';
    if (!preserved) {
      model.minDuration = Math.max(0, Number(globalPreferences.min_duration) || 0);
      model.minDurationEmptyOnly = Boolean(globalPreferences.min_duration_empty_only);
      model.durationFilterEnabled = globalPreferences.duration_filter_enabled !== false;
      model.showHidden = Boolean(globalPreferences.show_hidden);
    }
    ui.minDuration.value = String(model.minDuration); ui.showHidden.checked = model.showHidden;
    ui.durationEmptyOnly.checked = model.minDurationEmptyOnly;
    const activeIds = new Set(active().map(row => row.id));
    const savedSelectedIds = new Set((preferences?.selected_segment_ids || []).filter(id => activeIds.has(id)));
    const savedPrimaryId = activeIds.has(preferences?.primary_segment_id) ? preferences.primary_segment_id : null;
    model.selectedId = preserved?.selectedId || savedPrimaryId || [...savedSelectedIds].at(-1) || filtered()[0]?.id || active()[0]?.id || null;
    model.selectedIds = preserved?.selectedIds || (savedSelectedIds.size ? savedSelectedIds : new Set(model.selectedId ? [model.selectedId] : []));
    if (model.selectedId) model.selectedIds.add(model.selectedId);
    model.viewReady = true;
    ui.audioOffset.value = String(model.audioOffset); ui.alignmentWarning.textContent = model.alignmentWarning;
    ui.overviewRange.textContent = `00:00:00.000 — ${formatTime(model.duration)}`;
    if (model.selectedAudioId) { ui.audio.src = `/api/audio?v=${encodeURIComponent(model.selectedAudioId)}`; ui.audio.load(); }
    else { ui.audio.removeAttribute('src'); ui.audio.load(); }
    showWorkspace(); renderSpeakerFilters();
    renderAll();
    if (hasAudio()) await Promise.all([loadOverviewPeaks(), centerOnSelected(false)]);
  }

  async function loadState(confirmDirty = false) {
    if (confirmDirty && model.dirty && !confirm(t('runtime.discard_refresh'))) return false;
    ui.save.disabled = true; ui.refresh.disabled = true; ui.app.setAttribute('aria-busy', 'true');
    try {
      const data = model.projectName
        ? await request('/api/select', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({project_name:model.projectName, asset_id:model.selectedAudioId, discard_pending:true})})
        : await request('/api/state');
      await applyState(data, false); return true;
    } catch (error) { toast(error.message); return false; }
    finally { ui.app.setAttribute('aria-busy', 'false'); showWorkspace(); }
  }

  function rememberCurrentOffset() {
    const asset = model.audioVariants.find(item => String(item.id) === String(model.selectedAudioId));
    if (asset) asset.offset_seconds = Number(model.audioOffset) || 0;
  }

  async function selectProject(projectName) {
    if (projectName === model.projectName) { ui.projectMenu.open = false; return; }
    if (model.dirty && !confirm(t('runtime.discard_switch'))) return;
    ui.projectMenu.open = false;
    try {
      const data = await request('/api/select', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({project_name:projectName, discard_pending:true})});
      await applyState(data, false);
    } catch (error) { toast(error.message); }
  }

  async function selectAudio(assetId) {
    if (String(assetId) === String(model.selectedAudioId)) { ui.audioMenu.open = false; return; }
    rememberCurrentOffset(); ui.audioMenu.open = false;
    try {
      const data = await request('/api/select', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({project_name:model.projectName, asset_id:assetId})});
      await applyState(data, true);
    } catch (error) { toast(error.message); }
  }

  async function addAudio() {
    try {
      ui.audioSummary.textContent = `${t('common.select_audio')}…`;
      const result = await request('/api/add-audio', {method:'POST', headers:{'Content-Type':'application/json'}, body:'{}'});
      if (result.count) { await applyState(result.state, true); model.dirty = true; updateDirtyIndicator(); renderSourceMenus(); toast(t('runtime.audio_added', {count:result.count})); }
      else renderSourceMenus();
      ui.audioMenu.open = false;
    } catch (error) { renderSourceMenus(); toast(error.message); }
  }

  async function deleteAudio(assetId) {
    rememberCurrentOffset(); model.deletedAudioIds.add(String(assetId)); model.dirty = true;
    const remaining = model.audioVariants.filter(asset => !model.deletedAudioIds.has(String(asset.id)) && asset.available !== false);
    if (String(model.selectedAudioId) === String(assetId)) {
      if (remaining.length) await selectAudio(remaining[0].id);
      else {
        ui.audio.pause(); ui.audio.removeAttribute('src'); ui.audio.load(); model.selectedAudioId = null; model.duration = 0; model.audioOffset = 0; model.overviewPeaks = null; model.detailPeaks = null; showWorkspace();
      }
    }
    renderSourceMenus(); updateDirtyIndicator();
  }

  async function createProjects() {
    if (model.dirty && !confirm(t('runtime.discard_switch'))) return;
    try {
      ui.projectSummary.textContent = `${t('runtime.create_project')}…`;
      const result = await request('/api/create-projects', {method:'POST', headers:{'Content-Type':'application/json'}, body:'{}'});
      if (result.count) { await applyState(result.state, false); toast(t('runtime.projects_created', {count:result.count})); }
      else renderSourceMenus();
      ui.projectMenu.open = false;
    } catch (error) { renderSourceMenus(); toast(error.message); }
  }

  ui.projectOptions.addEventListener('click', event => {
    const target = event.target.closest('[data-action]'); if (!target) return;
    if (target.dataset.action === 'select-project') selectProject(target.dataset.project);
    if (target.dataset.action === 'create-projects') createProjects();
  });
  ui.audioOptions.addEventListener('click', event => {
    const target = event.target.closest('[data-action]'); if (!target) return;
    if (target.dataset.action === 'select-audio') selectAudio(target.dataset.asset);
    if (target.dataset.action === 'add-audio') addAudio();
    if (target.dataset.action === 'delete-audio') deleteAudio(target.dataset.asset);
  });

  function renderSpeakerFilters() {
    const query = ui.speakerSearch.value.trim().toLocaleLowerCase();
    ui.speakerFilters.innerHTML = model.speakers.filter(name => name.toLocaleLowerCase().includes(query)).map(name => `<div class="filter-option managed-filter-option" data-speaker="${escapeHtml(name)}"><input type="checkbox" value="${escapeHtml(name)}" ${model.selectedSpeakers.has(name) ? 'checked' : ''}><span class="speaker-dot" style="--speaker-color:${speakerColor(name)}"></span><button class="managed-filter-name" data-action="rename-speaker" type="button">${escapeHtml(name)}</button><button class="managed-filter-delete" data-action="delete-speaker" type="button">${escapeHtml(t('common.delete'))}</button></div>`).join('') || `<div class="filter-empty">${escapeHtml(t('runtime.no_speaker_match'))}</div>`;
    const selectedCount = model.speakers.filter(name => model.selectedSpeakers.has(name)).length;
    ui.speakerFilterSummary.textContent = selectedCount === model.speakers.length ? t('filter.speaker') : t('runtime.selected_fraction', {label:t('common.speaker'), selected:selectedCount, total:model.speakers.length});
    renderTagFilters(); renderInspectorSelects();
  }

  const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const firstTagColor = '#71d47f';
  const tagPalette = palette.filter(color => color !== firstTagColor);
  const tagColors = new Map();
  let tagColorCursor = 0;
  const syncTagColors = tags => {
    const activeTags = new Set(tags.slice(1).map(name => String(name ?? '')));
    for (const name of tagColors.keys()) if (!activeTags.has(name)) tagColors.delete(name);
  };
  const sequentialTagColor = tag => {
    const name = String(tag ?? '');
    if (!tagColors.has(name)) {
      tagColors.set(name, tagPalette[tagColorCursor % tagPalette.length]);
      tagColorCursor += 1;
    }
    return tagColors.get(name);
  };
  const tagColor = tag => {
    const name = String(tag ?? ''), tags = model.tags.map(item => String(item ?? ''));
    if (name === String(tags[0] ?? '')) return firstTagColor;
    return tags.includes(name) ? sequentialTagColor(name) : tagPalette[0];
  };
  function createTagOption(name, selected = false) {
    const option = new Option(name, name, false, selected), color = tagColor(name);
    option.className = 'tag-option'; option.style.setProperty('--tag-color', color);
    return option;
  }
  function renderTagFilters() {
    syncTagColors(model.tags);
    ui.tagOptions.innerHTML = model.tags.map(name => `<div class="filter-option managed-filter-option" data-tag="${escapeHtml(name)}" style="--tag-color:${tagColor(name)}"><input type="checkbox" value="${escapeHtml(name)}" ${model.selectedTags.has(name) ? 'checked' : ''}><button class="managed-filter-name tag-colored" data-action="rename-tag" type="button">${escapeHtml(name)}</button><button class="managed-filter-delete" data-action="delete-tag" type="button">${escapeHtml(t('common.delete'))}</button></div>`).join('');
    const selectedCount = model.tags.filter(name => model.selectedTags.has(name)).length;
    ui.tagFilterSummary.textContent = selectedCount === model.tags.length ? t('filter.tag') : t('runtime.selected_fraction', {label:t('common.tag'), selected:selectedCount, total:model.tags.length});
  }
  function renderInspectorSelects() {
    const row = selected();
    ui.speaker.replaceChildren(...(!row || model.speakers.includes(row.speaker) ? [] : [new Option(t('runtime.deleted_value', {name:row.speaker}), '__missing__', true, true)]), ...model.speakers.map(name => new Option(name, name, false, row?.speaker === name)), new Option(`＋ ${t('review.new_speaker')}`, '__new__'));
    ui.speaker.classList.toggle('missing-value', Boolean(row && !model.speakers.includes(row.speaker)));
    ui.segmentTag.replaceChildren(...(!row || model.tags.includes(row.tag) ? [] : [new Option(t('runtime.deleted_value', {name:row.tag}), '__missing__', true, true)]), ...model.tags.map(name => createTagOption(name, row?.tag === name)), new Option(`＋ ${t('review.new_tag')}`, '__new__'));
    ui.segmentTag.classList.toggle('missing-value', Boolean(row && !model.tags.includes(row.tag)));
    ui.segmentTag.classList.toggle('tag-colored', Boolean(row));
    row ? ui.segmentTag.style.setProperty('--tag-color', tagColor(row.tag)) : ui.segmentTag.style.removeProperty('--tag-color');
  }

  function beginSpeakerRename(button, oldName) {
    const editor = document.createElement('input'); editor.type = 'text'; editor.className = 'speaker-name-editor'; editor.value = oldName; editor.setAttribute('aria-label', t('runtime.rename', {name:oldName}));
    let finished = false;
    const finish = commit => {
      if (finished) return;
      finished = true;
      if (commit) renameSpeaker(oldName, editor.value); else renderSpeakerFilters();
    };
    editor.addEventListener('keydown', event => {
      event.stopPropagation();
      if (event.key === 'Enter') { event.preventDefault(); finish(true); }
      if (event.key === 'Escape') { event.preventDefault(); finish(false); }
    });
    editor.addEventListener('blur', () => finish(true));
    button.replaceWith(editor); editor.focus(); editor.select();
  }

  function renameSpeaker(oldName, requestedName) {
    const newName = String(requestedName).trim();
    if (!newName) { toast(t('runtime.speaker_empty')); renderSpeakerFilters(); return; }
    if (newName === oldName) { renderSpeakerFilters(); return; }
    const merging = model.speakers.includes(newName);
    if (merging && !confirm(t('runtime.speaker_merge_confirm', {oldName, newName}))) { renderSpeakerFilters(); return; }
    snapshot();
    model.segments.forEach(row => { if ((row.speaker || 'Unassigned') === oldName) row.speaker = newName; });
    model.speakers = sortSpeakerNames(model.speakers.map(name => name === oldName ? newName : name));
    const oldSelected = model.selectedSpeakers.delete(oldName);
    if (oldSelected || model.selectedSpeakers.has(newName)) model.selectedSpeakers.add(newName);
    if (!merging && model.colors.has(oldName)) model.colors.set(newName, model.colors.get(oldName));
    model.colors.delete(oldName);
    renderSpeakerFilters(); changed(); toast(t(merging ? 'runtime.merged' : 'runtime.renamed', {oldName, newName}));
  }

  function deleteSpeaker(name) {
    if (model.speakers.length <= 1) return toast(t('runtime.keep_one_speaker'));
    snapshot(); model.speakers = model.speakers.filter(value => value !== name); model.selectedSpeakers.delete(name); changed(); renderSpeakerFilters();
  }
  function renameTag(oldName, requestedName) {
    const newName = String(requestedName).trim();
    if (!newName || newName.length > 100) { toast(t('runtime.tag_invalid')); renderTagFilters(); return; }
    if (newName === oldName) return renderTagFilters();
    const merging = model.tags.includes(newName);
    if (merging && !confirm(t('runtime.tag_merge_confirm', {oldName, newName}))) { renderTagFilters(); return; }
    snapshot(); model.tags = sortTagNames(model.tags.map(name => name === oldName ? newName : name)); model.segments.forEach(row => { if (row.tag === oldName) row.tag = newName; });
    const oldSelected = model.selectedTags.delete(oldName);
    if (oldSelected || model.selectedTags.has(newName)) model.selectedTags.add(newName);
    changed(); renderSpeakerFilters(); toast(t(merging ? 'runtime.merged' : 'runtime.renamed', {oldName, newName}));
  }
  function deleteTag(name) {
    if (model.tags.length <= 1) return toast(t('runtime.keep_one_tag'));
    snapshot(); model.tags = model.tags.filter(value => value !== name); model.selectedTags.delete(name); changed(); renderSpeakerFilters();
  }
  function beginManagedRename(button, oldName, commit, rerender) {
    const editor = document.createElement('input'); editor.type = 'text'; editor.className = 'managed-name-editor'; editor.maxLength = 100; editor.value = oldName;
    button.replaceWith(editor); editor.focus(); editor.select(); let cancelled = false;
    editor.addEventListener('keydown', event => { event.stopPropagation(); if (event.key === 'Enter') { event.preventDefault(); editor.blur(); } if (event.key === 'Escape') { event.preventDefault(); cancelled = true; rerender(); } });
    editor.addEventListener('blur', () => { if (!cancelled) commit(oldName, editor.value); }, {once:true});
  }
  ui.speakerFilters.addEventListener('change', event => { if (event.target.type !== 'checkbox') return; clearNewSegmentPins(); event.target.checked ? model.selectedSpeakers.add(event.target.value) : model.selectedSpeakers.delete(event.target.value); renderSpeakerFilters(); renderAll(); });
  ui.speakerFilters.addEventListener('click', event => { const button = event.target.closest('button'), name = button?.closest('[data-speaker]')?.dataset.speaker; if (!name) return; if (button.dataset.action === 'rename-speaker') beginSpeakerRename(button, name); if (button.dataset.action === 'delete-speaker') deleteSpeaker(name); });
  ui.speakerSearch.addEventListener('input', () => { renderSpeakerFilters(); persistReviewView(); });
  ui.speakerAll.addEventListener('click', () => { clearNewSegmentPins(); model.selectedSpeakers = new Set(model.speakers); renderSpeakerFilters(); renderAll(); });
  ui.speakerNone.addEventListener('click', () => { clearNewSegmentPins(); model.selectedSpeakers.clear(); renderSpeakerFilters(); renderAll(); });
  ui.speakerFilterAdd.addEventListener('click', () => openSpeakerNaming('filter'));
  ui.tagOptions.addEventListener('change', event => { if (event.target.type !== 'checkbox') return; clearNewSegmentPins(); event.target.checked ? model.selectedTags.add(event.target.value) : model.selectedTags.delete(event.target.value); renderTagFilters(); renderAll(); });
  ui.tagOptions.addEventListener('click', event => { const button = event.target.closest('button'), name = button?.closest('[data-tag]')?.dataset.tag; if (!name) return; if (button.dataset.action === 'rename-tag') beginManagedRename(button, name, renameTag, renderTagFilters); if (button.dataset.action === 'delete-tag') deleteTag(name); });
  ui.tagAll.addEventListener('click', () => { clearNewSegmentPins(); model.selectedTags = new Set(model.tags); renderTagFilters(); renderAll(); });
  ui.tagNone.addEventListener('click', () => { clearNewSegmentPins(); model.selectedTags.clear(); renderTagFilters(); renderAll(); });
  ui.tagFilterAdd.addEventListener('click', () => openTagNaming('filter'));

  function renderAll() {
    ui.durationHide.classList.toggle('primary', model.durationFilterEnabled);
    ui.durationHide.setAttribute('aria-pressed', String(model.durationFilterEnabled));
    ui.durationHide.textContent = t(model.durationFilterEnabled ? 'review.hidden' : 'review.hide');
    renderNavigator(); renderContext(); renderInspector(); drawOverview(); drawDetail(); validateTimeline();
    syncPlaybackButtons();
    ui.undo.disabled = model.history.length === 0; ui.redo.disabled = model.future.length === 0;
    const mergeCount = active().filter(row => model.selectedIds.has(row.id)).length;
    ui.merge.disabled = mergeCount < 2;
    ui.merge.classList.toggle('primary', mergeCount >= 2);
    ui.merge.title = mergeCount >= 2 ? t('runtime.merge_selected', {count:mergeCount}) : t('review.merge_help');
    updateDirtyIndicator();
  }

  const REVIEW_VIEW_KEY = 'audio-registry.review-ui.v1:';
  const LEGACY_REVIEW_VIEW_KEY = 'voice-segmenter.review-ui.v1:';
  const storedViews = new Map();
  function readReviewView(projectName) {
    try {
      const value = JSON.parse(localStorage.getItem(REVIEW_VIEW_KEY + projectName) || localStorage.getItem(LEGACY_REVIEW_VIEW_KEY + projectName) || 'null');
      return value && typeof value === 'object' && !Array.isArray(value) ? value : null;
    } catch (_) { return null; }
  }
  function persistReviewView() {
    if (!model.projectName || !model.viewReady) return;
    const value = JSON.stringify({
      selected_speakers: [...model.selectedSpeakers], selected_tags: [...model.selectedTags],
      all_speakers_selected: model.speakers.every(name => model.selectedSpeakers.has(name)),
      all_tags_selected: model.tags.every(name => model.selectedTags.has(name)),
      selected_segment_ids: [...model.selectedIds], primary_segment_id: model.selectedId,
      speaker_search: ui.speakerSearch.value,
    });
    if (storedViews.get(model.projectName) === value) return;
    try {
      localStorage.setItem(REVIEW_VIEW_KEY + model.projectName, value);
      localStorage.removeItem(LEGACY_REVIEW_VIEW_KEY + model.projectName);
      storedViews.set(model.projectName, value);
    } catch (_) {}
  }

  function updateRefreshIndicator() {
    ui.refresh.disabled = !model.remoteChanged || !model.projectName || model.saving || ui.app.getAttribute('aria-busy') === 'true';
    ui.refresh.classList.toggle('primary', model.remoteChanged);
    ui.refresh.title = t(model.remoteChanged ? 'runtime.refresh_changed' : 'runtime.refresh_project');
  }

  let checkingDatabase = false;
  async function checkDatabaseChanges() {
    if (checkingDatabase || document.hidden || !model.projectName || model.saving || ui.app.getAttribute('aria-busy') === 'true') return;
    const project = model.projectName, baseline = model.updateCounters;
    checkingDatabase = true;
    try {
      const data = await request(`/api/update-counters?project=${encodeURIComponent(project)}`);
      if (project !== model.projectName || baseline !== model.updateCounters || model.saving) return;
      model.remoteChanged = JSON.stringify(data.update_counters || {}) !== baseline;
      updateRefreshIndicator();
    } catch (_) { /* A temporary connection failure is not a database change. */ }
    finally { checkingDatabase = false; }
  }

  function updateDirtyIndicator() {
    persistReviewView();
    const modified = Boolean(model.projectName && model.dirty);
    const busy = model.saving || ui.app.getAttribute('aria-busy') === 'true';
    ui.save.disabled = !modified || busy;
    ui.save.classList.toggle('primary', modified);
    ui.saveState.textContent = model.saving ? t('runtime.saving') : modified ? t('runtime.unsaved') : t('runtime.saved_version', {revision:model.revision});
  }

  function centerListRow(container, selector) {
    const current = container.querySelector(selector);
    if (!current) return;
    const containerRect = container.getBoundingClientRect();
    const currentRect = current.getBoundingClientRect();
    const itemTop = container.scrollTop + currentRect.top - containerRect.top;
    container.scrollTop = Math.max(0, itemTop - (container.clientHeight - currentRect.height) / 2);
  }

  function captureListAnchor(container, selector, availableIds) {
    const containerTop = container.getBoundingClientRect().top;
    const items = [...container.querySelectorAll(selector)];
    const renderedIndex = items.findIndex(item => item.getBoundingClientRect().bottom > containerTop && availableIds.has(item.dataset.segmentId));
    if (renderedIndex < 0) return null;
    const item = items[renderedIndex];
    return {id: item.dataset.segmentId, renderedIndex, offset: item.getBoundingClientRect().top - containerTop};
  }

  function restoreListAnchor(container, selector, anchor) {
    if (!anchor) return;
    const item = [...container.querySelectorAll(selector)].find(node => node.dataset.segmentId === anchor.id);
    if (!item) return;
    const offset = item.getBoundingClientRect().top - container.getBoundingClientRect().top;
    container.scrollTop += offset - anchor.offset;
  }

  function renderNavigator() {
    const rows = filtered();
    const rowIds = new Set(rows.map(row => row.id));
    const chosen = rows.findIndex(row => row.id === model.selectedId);
    const anchor = chosen < 0 ? captureListAnchor(ui.navigatorList, '.nav-row', rowIds) : null;
    ui.filterCount.textContent = t('runtime.filtered_rows', {count:rows.length});
    ui.navigatorCount.textContent = t('runtime.rows', {count:rows.length});
    ui.navigatorList.replaceChildren();
    const anchorIndex = anchor ? rows.findIndex(row => row.id === anchor.id) : -1;
    const first = Math.max(0, chosen >= 0 ? chosen - 50 : anchorIndex >= 0 ? anchorIndex - anchor.renderedIndex : 0);
    const visible = rows.slice(first, first + 120);
    if (!visible.length) {
      const empty = document.createElement('p'); empty.className = 'inspector-note'; empty.textContent = t('runtime.no_filtered_rows'); ui.navigatorList.append(empty); return;
    }
    visible.forEach(row => {
      const isSelected = model.selectedIds.has(row.id);
      const button = document.createElement('button'); button.type = 'button'; button.className = `nav-row${isSelected ? ' selected' : ''}${row.id === model.selectedId ? ' primary' : ''}`;
      fillTimelineRow(button, row);
      button.addEventListener('click', event => selectRow(row.id, true, event.ctrlKey || event.metaKey)); ui.navigatorList.append(button);
    });
    if (rows.length > visible.length) {
      const note = document.createElement('p'); note.className = 'inspector-note'; note.textContent = t('runtime.nearby_rows', {count:visible.length}); ui.navigatorList.append(note);
    }
    if (model.contextNeedsCenter && chosen >= 0) {
      requestAnimationFrame(() => {
        centerListRow(ui.navigatorList, '.nav-row.primary');
      });
    } else if (anchor) {
      requestAnimationFrame(() => restoreListAnchor(ui.navigatorList, '.nav-row', anchor));
    }
  }

  function fillTimelineRow(button, row) {
    button.dataset.segmentId = row.id;
    const top = document.createElement('span'); top.className = 'row-top';
    const who = document.createElement('span'); who.textContent = row.speaker || 'Unassigned'; who.style.color = speakerColor(row.speaker || 'Unassigned');
    const time = document.createElement('span'); time.className = 'row-time'; time.textContent = `${formatTime(row.start)} · ${durationOf(row).toFixed(3)}s`;
    top.append(who, time);
    const text = document.createElement('span'); text.className = 'row-text'; text.textContent = row.text || t('runtime.no_transcript');
    button.append(top, text);
  }

  function renderContext() {
    const rows = active();
    ui.contextList.replaceChildren();
    ui.contextCount.textContent = t('runtime.context_rows', {count:rows.length});
    rows.forEach(row => {
      const current = row.id === model.selectedId;
      const button = document.createElement('button'); button.type = 'button'; button.className = `context-row${current ? ' current' : ''}${model.selectedIds.has(row.id) ? ' multi-selected' : ''}`;
      fillTimelineRow(button, row);
      button.addEventListener('click', event => selectRow(row.id, true, event.ctrlKey || event.metaKey)); ui.contextList.append(button);
    });
    if (model.contextNeedsCenter) {
      model.contextNeedsCenter = false;
      requestAnimationFrame(() => {
        centerListRow(ui.contextList, '.context-row.current');
      });
    }
  }

  function renderInspector() {
    const row = selected(); const controls = [ui.start, ui.end, ui.speaker, ui.segmentTag, ui.segmentNote, ui.transcript, ui.retranscribe, ui.exportClip, ui.delete, ui.split, ui.playSegment];
    controls.forEach(control => control.disabled = !row);
    ui.retranscribe.disabled = ui.playSegment.disabled = !row || !hasAudio();
    ui.exportClip.disabled = !row || !hasAudio() || model.quickExportRunning;
    const deleteCount = active().filter(item => model.selectedIds.has(item.id)).length;
    ui.delete.textContent = deleteCount > 1 ? t('runtime.delete_count', {count:deleteCount}) : t('common.delete');
    ui.delete.title = deleteCount > 1 ? t('runtime.delete_selected', {count:deleteCount}) : t('runtime.delete_current');
    renderInspectorSelects();
    if (!row) { ui.selectedId.textContent = t('review.unselected'); ui.start.value = ui.end.value = ui.duration.value = ui.transcript.value = ui.segmentNote.value = ''; return; }
    ui.selectedId.textContent = row.id;
    ui.start.value = formatTime(row.start); ui.end.value = formatTime(row.end); ui.duration.value = t('runtime.duration_value', {value:durationOf(row).toFixed(3)}); ui.speaker.value = row.speaker || 'Unassigned'; ui.transcript.value = row.text || '';
    ui.segmentTag.value = model.tags.includes(row.tag) ? row.tag : '__missing__'; ui.segmentNote.value = row.note || '';
  }

  function setSingleSelection(id) {
    model.contextNeedsCenter = true;
    model.selectedId = id || null;
    model.selectedIds = new Set(id ? [id] : []);
  }

  function toggleSelection(id) {
    model.contextNeedsCenter = true;
    if (model.selectedIds.has(id)) {
      model.selectedIds.delete(id);
      if (model.selectedId === id) model.selectedId = [...model.selectedIds].at(-1) || null;
    } else {
      model.selectedIds.add(id);
      model.selectedId = id;
    }
  }

  function selectRow(id, center = true, additive = false) {
    const wasPlaying = !ui.audio.paused;
    stopSegmentMonitor();
    additive ? toggleSelection(id) : setSingleSelection(id);
    const row = selected();
    if (wasPlaying && row) {
      model.playMode = 'segment';
      model.segmentPlayback = {rowId: row.id, start: toAudioTime(row.start), end: toAudioTime(row.end), allowLoop: false};
    } else {
      model.playMode = 'continuous';
      model.segmentPlayback = null;
    }
    renderAll(); if (center && model.selectedId) centerOnSelected();
    syncPlaybackButtons();
    if (wasPlaying && row) monitorSegmentBoundary();
  }

  function hasAudio() { return Boolean(model.selectedAudioId && model.duration > 0); }

  async function centerOnSelected(load = true) {
    if (!hasAudio()) return;
    const row = selected(); if (!row) return;
    model.viewStart = Math.max(0, Math.min(model.duration - model.viewDuration, (toAudioTime(row.start) + toAudioTime(row.end)) / 2 - model.viewDuration / 2));
    ui.audio.currentTime = Math.max(0, Math.min(model.duration, toAudioTime(row.start))); updateRangeLabels();
    if (load) await loadDetailPeaks(); else await loadDetailPeaks();
  }

  function updateRangeLabels() {
    const end = Math.min(model.duration, model.viewStart + model.viewDuration);
    ui.detailRange.textContent = `${formatTime(model.viewStart)} — ${formatTime(end)}`;
  }

  async function loadOverviewPeaks() {
    if (!hasAudio()) return;
    ui.overviewLoading.hidden = false;
    ui.overviewLoading.textContent = t('review.loading_overview');
    try { model.overviewPeaks = await request(`/api/peaks?start=0&end=${model.duration}&points=2400`); ui.overviewLoading.hidden = true; drawOverview(); }
    catch (error) { ui.overviewLoading.textContent = error.message; }
  }

  async function loadDetailPeaks() {
    if (!hasAudio()) return;
    const token = ++model.peakRequest; ui.detailLoading.hidden = false; updateRangeLabels(); drawDetail();
    ui.detailLoading.textContent = t('review.loading_detail');
    try {
      const end = Math.min(model.duration, model.viewStart + model.viewDuration);
      const peaks = await request(`/api/peaks?start=${model.viewStart}&end=${end}&points=2400`);
      if (token !== model.peakRequest) return;
      model.detailPeaks = peaks; ui.detailLoading.hidden = true; drawDetail();
    } catch (error) { if (token === model.peakRequest) ui.detailLoading.textContent = error.message; }
  }

  function canvasContext(canvas) {
    const rect = canvas.getBoundingClientRect(); const ratio = window.devicePixelRatio || 1;
    const width = Math.max(1, Math.round(rect.width * ratio)); const height = Math.max(1, Math.round(rect.height * ratio));
    if (canvas.width !== width || canvas.height !== height) { canvas.width = width; canvas.height = height; }
    const context = canvas.getContext('2d'); context.setTransform(ratio, 0, 0, ratio, 0, 0); return {context, width: rect.width, height: rect.height};
  }

  function drawPeaks(context, width, height, peaks, offsetX = 0, widthScale = 1) {
    context.fillStyle = '#090c11'; context.fillRect(0, 0, width, height);
    context.strokeStyle = '#2b3441'; context.lineWidth = 1;
    for (let i = 1; i < 8; i++) { const x = i * width / 8; context.beginPath(); context.moveTo(x, 0); context.lineTo(x, height); context.stroke(); }
    context.strokeStyle = '#7f8b9b'; context.lineWidth = 1;
    if (!peaks?.minimum?.length) { context.beginPath(); context.moveTo(0, height / 2); context.lineTo(width, height / 2); context.stroke(); return; }
    const n = peaks.minimum.length; const mid = height / 2; const scale = height * .43;
    context.beginPath();
    for (let i = 0; i < n; i++) { const x = offsetX + i * width * widthScale / Math.max(1, n - 1); context.moveTo(x, mid + peaks.minimum[i] * scale); context.lineTo(x, mid + peaks.maximum[i] * scale); }
    context.stroke();
  }

  function drawOverview() {
    const {context, width, height} = canvasContext(ui.overview); drawPeaks(context, width, height, hasAudio() ? model.overviewPeaks : null);
    if (!model.duration) return;
    active().forEach(row => {
      const match = isFiltered(row); if (!match && !model.showHidden) return;
      const x = toAudioTime(row.start) / model.duration * width; const w = Math.max(1, durationOf(row) / model.duration * width);
      context.globalAlpha = match ? .62 : .13; context.fillStyle = speakerColor(row.speaker || 'Unassigned'); context.fillRect(x, 4, w, height - 8);
    });
    active().filter(row => model.selectedIds.has(row.id)).forEach(row => {
      const x = toAudioTime(row.start) / model.duration * width; const w = Math.max(2, durationOf(row) / model.duration * width);
      context.globalAlpha = 1; context.strokeStyle = row.id === model.selectedId ? '#ffffff' : speakerColor(row.speaker || 'Unassigned'); context.lineWidth = 2; context.strokeRect(x, 3, w, height - 6);
    });
    context.globalAlpha = 1;
    const x = model.viewStart / model.duration * width; const w = Math.max(4, model.viewDuration / model.duration * width);
    context.fillStyle = 'rgba(86,214,194,.10)'; context.fillRect(x, 1, w, height - 2); context.strokeStyle = '#56d6c2'; context.lineWidth = 2; context.strokeRect(x + 1, 2, Math.max(1, w - 2), height - 4);
    const playX = ui.audio.currentTime / model.duration * width; context.strokeStyle = '#ffffff'; context.lineWidth = 1; context.beginPath(); context.moveTo(playX, 0); context.lineTo(playX, height); context.stroke();
  }

  function drawDetail() {
    const {context, width, height} = canvasContext(ui.detail);
    if (!hasAudio()) { drawPeaks(context, width, height, null); return; }
    const peakStart = Number(model.detailPeaks?.start ?? model.viewStart);
    const peakEnd = Number(model.detailPeaks?.end ?? (peakStart + model.viewDuration));
    const peakOffset = (peakStart - model.viewStart) / model.viewDuration * width;
    const peakScale = Math.max(0, peakEnd - peakStart) / model.viewDuration;
    drawPeaks(context, width, height, model.detailPeaks, peakOffset, peakScale);
    const end = model.viewStart + model.viewDuration;
    active().filter(row => toAudioTime(row.end) >= model.viewStart && toAudioTime(row.start) <= end).sort((left, right) => {
      const selectedOrder = Number(model.selectedIds.has(left.id)) - Number(model.selectedIds.has(right.id));
      if (selectedOrder) return selectedOrder;
      return Number(left.id === model.selectedId) - Number(right.id === model.selectedId);
    }).forEach(row => {
      const match = isFiltered(row); if (!match && !model.showHidden) return;
      const x = (toAudioTime(row.start) - model.viewStart) / model.viewDuration * width; const right = (toAudioTime(row.end) - model.viewStart) / model.viewDuration * width; const w = Math.max(2, right - x);
      const isSelected = model.selectedIds.has(row.id); const isPrimary = row.id === model.selectedId;
      const color = speakerColor(row.speaker || 'Unassigned'); context.globalAlpha = match ? .28 : .08; context.fillStyle = color; context.fillRect(x, 3, w, height - 6);
      context.globalAlpha = isSelected ? 1 : match ? .7 : .2; context.strokeStyle = isSelected ? (isPrimary ? '#ffffff' : color) : color; context.lineWidth = isPrimary ? 4 : isSelected ? 3 : 1; context.strokeRect(x, 3, w, height - 6);
      if (isPrimary) { context.fillStyle = color; context.fillRect(x - 3, 3, 6, height - 6); context.fillRect(right - 3, 3, 6, height - 6); }
      if (w > 54 && match) { context.globalAlpha = .95; context.fillStyle = '#eaf0f7'; context.font = '13px Microsoft YaHei UI'; context.fillText(row.speaker || 'Unassigned', Math.max(5, x + 7), 21, Math.max(20, w - 12)); }
    });
    if (model.drag?.kind === 'create') {
      const projectEnd = toProjectTime(model.duration);
      const start = Math.max(0, Math.min(projectEnd, Math.min(model.drag.start, model.drag.current)));
      const end = Math.max(0, Math.min(projectEnd, Math.max(model.drag.start, model.drag.current)));
      const x = (toAudioTime(start) - model.viewStart) / model.viewDuration * width;
      const right = (toAudioTime(end) - model.viewStart) / model.viewDuration * width;
      const w = Math.max(2, right - x);
      const label = t('runtime.new_segment', {value:(end - start).toFixed(3)});
      context.save();
      context.globalAlpha = 1;
      context.fillStyle = 'rgba(86, 214, 194, .28)'; context.fillRect(x, 3, w, height - 6);
      context.strokeStyle = '#8ff0df'; context.lineWidth = 2; context.setLineDash([8, 5]); context.strokeRect(x, 3, w, height - 6);
      context.setLineDash([]); context.fillStyle = '#8ff0df'; context.fillRect(x - 3, 3, 6, height - 6); context.fillRect(right - 3, 3, 6, height - 6);
      context.font = '600 13px Microsoft YaHei UI';
      const labelWidth = context.measureText(label).width + 14;
      const labelX = Math.max(5, Math.min(width - labelWidth - 5, x + 7));
      context.fillStyle = 'rgba(7, 20, 17, .92)'; context.fillRect(labelX, 9, labelWidth, 25);
      context.fillStyle = '#b9fff3'; context.fillText(label, labelX + 7, 27);
      context.restore();
    }
    context.globalAlpha = 1;
    const playX = (ui.audio.currentTime - model.viewStart) / model.viewDuration * width;
    if (playX >= 0 && playX <= width) { context.strokeStyle = '#ffffff'; context.lineWidth = 1; context.beginPath(); context.moveTo(playX, 0); context.lineTo(playX, height); context.stroke(); }
  }

  function detailPosition(clientX) {
    const rect = ui.detail.getBoundingClientRect(); const x = clientX - rect.left; const audioTime = model.viewStart + x / rect.width * model.viewDuration;
    return {rect, time: toProjectTime(audioTime), audioTime};
  }

  function hitSelectedDetailEdge(clientX) {
    const position = detailPosition(clientX);
    const edgeTolerancePixels = 12;
    const tolerance = edgeTolerancePixels / position.rect.width * model.viewDuration;
    const row = selected();
    if (!row || (!isFiltered(row) && !model.showHidden)) return {...position, row: null, mode: null};
    const startDistance = Math.abs(position.time - row.start);
    const endDistance = Math.abs(position.time - row.end);
    const nearestDistance = Math.min(startDistance, endDistance);
    if (nearestDistance > tolerance) return {...position, row: null, mode: null};
    return {...position, row, mode: startDistance <= endDistance ? 'start' : 'end'};
  }

  function hitDetailSegment(clientX) {
    const {time} = detailPosition(clientX);
    const rows = active()
      .filter(row => time >= row.start && time <= row.end && (isFiltered(row) || model.showHidden))
      .sort((left, right) => durationOf(left) - durationOf(right) || right.start - left.start || left.id.localeCompare(right.id));
    if (!rows.length) return null;
    const selectedIndex = rows.findIndex(row => row.id === model.selectedId);
    return selectedIndex >= 0 && rows.length > 1 ? rows[(selectedIndex + 1) % rows.length] : rows[0];
  }

  function clearDetailDragCursor() {
    ui.detail.classList.remove('panning', 'resizing-marker', 'edge-hover');
  }

  function captureState(segments = cloneSegments()) { return {segments, selectedId: model.selectedId, selectedIds: [...model.selectedIds], speakers: [...model.speakers], selectedSpeakers: [...model.selectedSpeakers], tags:[...model.tags], selectedTags:[...model.selectedTags]}; }
  function snapshot() { model.history.push(captureState()); if (model.history.length > 60) model.history.shift(); model.future = []; }
  function changed() { model.dirty = true; renderAll(); }

  function restore(stackFrom, stackTo) {
    if (!stackFrom.length) return;
    resetTranscriptEditSession();
    stackTo.push(captureState()); const state = stackFrom.pop(); model.segments = state.segments; model.selectedId = state.selectedId;
    model.selectedIds = new Set(state.selectedIds || (state.selectedId ? [state.selectedId] : []));
    if (state.speakers) model.speakers = [...state.speakers];
    if (state.selectedSpeakers) model.selectedSpeakers = new Set(state.selectedSpeakers);
    if (state.tags) model.tags = [...state.tags];
    if (state.selectedTags) model.selectedTags = new Set(state.selectedTags);
    model.dirty = true; model.contextNeedsCenter = true; renderSpeakerFilters(); renderAll();
  }

  function nextId() { return `NEW-${crypto.randomUUID().slice(0, 8).toUpperCase()}`; }

  function clearNewSegmentPins() { model.filterPinnedIds.clear(); }

  function nextSpeakerName() {
    const numbered = model.speakers.map(name => {
      const match = String(name).match(/^(.*?)(\d+)$/);
      return match ? {prefix: match[1], number: Number(match[2]), width: match[2].length} : null;
    }).filter(Boolean);
    if (!numbered.length) return `Speaker_${String(model.speakers.length + 1).padStart(2, '0')}`;
    const highest = numbered.reduce((best, item) => item.number > best.number ? item : best);
    const next = highest.number + 1;
    return `${highest.prefix}${String(next).padStart(Math.max(highest.width, String(next).length), '0')}`;
  }

  function openSpeakerNaming(kind, rowId = null, previousValue = '') {
    model.pendingSpeakerCreate = {kind, rowId, previousValue, state: captureState()};
    ui.newSpeakerName.value = '';
    ui.speakerNameDialog.showModal();
    setTimeout(() => ui.newSpeakerName.focus(), 0);
  }

  function cancelSpeakerNaming() {
    const pending = model.pendingSpeakerCreate;
    model.pendingSpeakerCreate = null;
    ui.speakerNameDialog.close();
    if (pending?.kind === 'assignment') ui.newSegmentSpeaker.value = pending.previousValue || '';
    else renderInspector();
  }

  function openTagNaming(kind, rowId = null) {
    model.pendingTagCreate = {kind, rowId, state:captureState()}; ui.newTagName.value = '';
    ui.tagNameDialog.showModal(); setTimeout(() => ui.newTagName.focus(), 0);
  }

  function openSpeakerAssignment(row) {
    const checked = [...model.selectedSpeakers];
    const defaultSpeaker = checked.length === 1 ? checked[0] : '';
    const placeholder = new Option(t('runtime.select_speaker'), '', true, !defaultSpeaker); placeholder.disabled = true;
    const options = model.speakers.map(name => new Option(name, name, false, name === defaultSpeaker));
    const createOption = new Option(`＋ ${t('review.new_speaker')}`, '__new__');
    ui.newSegmentSpeaker.replaceChildren(placeholder, ...options, createOption);
    ui.newSegmentSpeaker.value = defaultSpeaker;
    model.newSegmentSpeakerPrevious = defaultSpeaker;
    model.pendingSpeakerId = row.id;
    ui.speakerDialog.showModal();
  }

  function addAt(start, end) {
    snapshot();
    const projectEnd = toProjectTime(model.duration);
    const row = {id: nextId(), start: Math.max(0, start), end: Math.min(projectEnd, end), speaker: 'Unassigned', text: '', tag:model.tags[0] || '1', note:'', selected_variant_id:model.selectedAudioId, deleted: false, manual_text: false, needs_asr: false, origin_ids: []};
    if (row.end <= row.start) row.end = Math.min(projectEnd, row.start + 1);
    model.segments.push(row); setSingleSelection(row.id); model.filterPinnedIds.add(row.id); model.createMode = false; ui.add.classList.remove('primary'); changed(); centerOnSelected(); openSpeakerAssignment(row);
  }

  function validateTimeline() {
    if (!hasAudio()) { ui.validationState.textContent = t('runtime.no_audio_editable'); ui.validationState.className = ''; return true; }
    const outside = active().filter(row => toAudioTime(row.start) < 0 || toAudioTime(row.end) > model.duration);
    ui.validationState.textContent = outside.length ? t('runtime.outside_audio', {count:outside.length}) : t('runtime.offset_valid');
    ui.validationState.className = outside.length ? 'warning' : '';
    return true;
  }

  async function saveReview() {
    if (!model.projectName || model.saving) return false;
    if (!model.dirty) return true;
    model.saving = true;
    updateRefreshIndicator();
    try {
      updateDirtyIndicator();
      const missingSpeakers = active().filter(row => !model.speakers.includes(row.speaker));
      if (missingSpeakers.length) {
        if (!confirm(t('runtime.missing_speakers_save', {count:missingSpeakers.length}))) return false;
        missingSpeakers.forEach(row => { row.speaker = model.speakers[0]; });
      }
      const missingTags = active().filter(row => !model.tags.includes(row.tag));
      if (missingTags.length) {
        if (!confirm(t('runtime.missing_tags_save', {count:missingTags.length}))) return false;
        missingTags.forEach(row => { row.tag = model.tags[0]; });
      }
      rememberCurrentOffset();
      const payload = {
        revision: model.revision, segments: model.segments,
        selected_audio_id: model.selectedAudioId,
        deleted_audio_ids: [...model.deletedAudioIds],
        audio_offsets: Object.fromEntries(model.audioVariants.map(asset => [asset.id, Number(asset.offset_seconds) || 0])),
      };
      const data = await request('/api/review', {method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)});
      await applyState(data, false); model.dirty = false; model.deletedAudioIds = new Set(); renderSourceMenus(); updateDirtyIndicator(); toast(t('runtime.review_saved')); return true;
    } catch (error) { toast(error.message); return false; }
    finally { model.saving = false; updateDirtyIndicator(); updateRefreshIndicator(); }
  }

  function durationCriteria() {
    const threshold = Number(ui.minDuration.value);
    if (!ui.minDuration.value.trim() || !Number.isFinite(threshold) || threshold < 0) { toast(t('runtime.duration_invalid')); return null; }
    return {threshold, emptyOnly:ui.durationEmptyOnly.checked};
  }
  function rememberDurationCriteria(criteria) {
    model.minDuration = criteria.threshold; model.minDurationEmptyOnly = criteria.emptyOnly;
    persistGlobalPreferences(0);
  }
  function toggleDurationFilter() {
    const criteria = durationCriteria(); if (!criteria) return;
    clearNewSegmentPins(); model.durationFilterEnabled = !model.durationFilterEnabled;
    rememberDurationCriteria(criteria); renderAll();
  }
  ui.durationHide.addEventListener('click', toggleDurationFilter);
  ui.durationDelete.addEventListener('click', () => {
    const criteria = durationCriteria(); if (!criteria) return;
    rememberDurationCriteria(criteria);
    const rows = active().filter(row => matchesDurationFilter(row, criteria.threshold, criteria.emptyOnly));
    if (!rows.length) return toast(t('runtime.no_matching_rows'));
    if (!confirm(t('runtime.delete_filtered_confirm', {count:rows.length}))) return;
    ui.durationMenu.open = false; deleteRows(rows);
  });
  document.addEventListener('pointerdown', event => { if (!ui.durationMenu.contains(event.target)) ui.durationMenu.open = false; });
  document.addEventListener('keydown', event => { if (event.key === 'Escape') ui.durationMenu.open = false; });
  ui.showHidden.addEventListener('change', () => { model.showHidden = ui.showHidden.checked; persistGlobalPreferences(0); renderAll(); });
  ui.audioOffset.addEventListener('input', () => {
    const value = Number(ui.audioOffset.value);
    if (!Number.isFinite(value)) return;
    model.audioOffset = value;
    model.dirty = true;
    const outside = active().some(row => toAudioTime(row.start) < 0 || toAudioTime(row.end) > model.duration);
    ui.alignmentWarning.textContent = outside ? t('runtime.alignment_warning') : '';
    renderAll();
  });
  ui.zoom.addEventListener('change', () => { model.viewDuration = Math.min(model.duration, Number(ui.zoom.value)); syncZoomControl(); centerOnSelected(); });
  ui.undo.addEventListener('click', () => restore(model.history, model.future)); ui.redo.addEventListener('click', () => restore(model.future, model.history));
  ui.save.addEventListener('click', () => saveReview());
  ui.refresh.addEventListener('click', () => loadState(true));
  ui.export.addEventListener('click', () => {
    ui.exportMenu.hidden = !ui.exportMenu.hidden;
    ui.export.setAttribute('aria-expanded', String(!ui.exportMenu.hidden));
  });
  function closeExportMenu() { ui.exportMenu.hidden = true; ui.export.setAttribute('aria-expanded', 'false'); }
  document.addEventListener('pointerdown', event => { if (!ui.export.parentElement.contains(event.target)) closeExportMenu(); });
  document.addEventListener('keydown', event => { if (event.key === 'Escape') closeExportMenu(); });
  function currentTextExportPayload() {
    return {
      selected_speakers: [...model.selectedSpeakers],
      selected_tags: [...model.selectedTags],
      min_duration: model.durationFilterEnabled ? model.minDuration : 0,
      min_duration_empty_only: model.minDurationEmptyOnly,
      audio_offset: model.audioOffset,
    };
  }
  async function runTextExport(button, endpoint, label) {
    closeExportMenu();
    if (!model.projectName || !model.selectedAudioId) return;
    if (model.dirty) { toast(t('runtime.save_before_export')); return; }
    button.disabled = true;
    try {
      const result = await request(endpoint, {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(currentTextExportPayload()),
      });
      toast(t('runtime.exported', {count:result.count, label, path:result.path}));
    } catch (error) { toast(error.message); }
    finally { button.disabled = !(model.projectName && model.selectedAudioId && model.duration > 0); }
  }
  ui.exportSubtitles.addEventListener('click', () => runTextExport(ui.exportSubtitles, '/api/export-subtitles', t('runtime.subtitle')));
  ui.exportAu.addEventListener('click', () => runTextExport(ui.exportAu, '/api/export-audition', t('runtime.audition_markers')));

  ui.overview.addEventListener('pointerdown', event => {
    if (event.button !== 0 || !hasAudio()) return;
    const rect = ui.overview.getBoundingClientRect(); const time = Math.max(0, Math.min(model.duration, (event.clientX - rect.left) / rect.width * model.duration)); const projectTime = toProjectTime(time);
    const rows = active(); const row = rows.find(item => projectTime >= item.start && projectTime < item.end) || rows.reduce((best, item) => !best || Math.abs(item.start - projectTime) < Math.abs(best.start - projectTime) ? item : best, null);
    if (row) (event.ctrlKey || event.metaKey) ? toggleSelection(row.id) : setSingleSelection(row.id);
    model.playMode = 'continuous';
    model.viewStart = Math.max(0, Math.min(model.duration - model.viewDuration, time - model.viewDuration / 2)); ui.audio.currentTime = time; renderAll(); loadDetailPeaks();
  });

  ui.detail.addEventListener('wheel', event => {
    if (!hasAudio()) return;
    event.preventDefault(); const rect = ui.detail.getBoundingClientRect(); const anchor = model.viewStart + (event.clientX - rect.left) / rect.width * model.viewDuration;
    const factor = event.deltaY > 0 ? 1.25 : .8; const next = Math.max(5, Math.min(600, model.viewDuration * factor));
    model.viewStart = Math.max(0, Math.min(model.duration - next, anchor - (event.clientX - rect.left) / rect.width * next)); model.viewDuration = next; syncZoomControl(); loadDetailPeaks(); drawOverview();
  }, {passive: false});

  ui.detail.addEventListener('pointerdown', event => {
    if (event.button !== 0 || !hasAudio()) return;
    const position = detailPosition(event.clientX);
    const time = Math.max(0, Math.min(model.duration, position.audioTime));
    const previousPlayTime = ui.audio.currentTime;
    model.playMode = 'continuous'; ui.audio.currentTime = time; ui.playTime.textContent = formatTime(time);
    if (model.createMode) { model.drag = {kind: 'create', start: position.time, current: position.time}; ui.detail.setPointerCapture(event.pointerId); drawOverview(); drawDetail(); return; }
    const edge = hitSelectedDetailEdge(event.clientX);
    if (edge.row) {
      snapshot(); model.drag = {kind: edge.mode, rowId: edge.row.id, pointerStart: edge.time, start: edge.row.start, end: edge.row.end};
      clearDetailDragCursor(); ui.detail.classList.add('resizing-marker'); ui.detail.setPointerCapture(event.pointerId); drawOverview(); drawDetail(); return;
    }
    model.drag = {
      kind: 'pan', pointerStartX: event.clientX, viewStart: model.viewStart, playTime: previousPlayTime, moved: false,
      clickedRowId: hitDetailSegment(event.clientX)?.id || null, toggleSelection: event.ctrlKey || event.metaKey,
    };
    clearDetailDragCursor(); ui.detail.classList.add('panning'); ui.detail.setPointerCapture(event.pointerId);
    drawOverview(); drawDetail();
  });

  ui.detail.addEventListener('pointermove', event => {
    if (!hasAudio()) return;
    if (!model.drag) {
      const mode = model.createMode ? null : hitSelectedDetailEdge(event.clientX).mode;
      ui.detail.classList.toggle('edge-hover', mode === 'start' || mode === 'end');
      return;
    }
    if (model.drag.kind === 'pan') {
      const rect = ui.detail.getBoundingClientRect(); const deltaX = event.clientX - model.drag.pointerStartX;
      if (!model.drag.moved && Math.abs(deltaX) < 2) return;
      if (!model.drag.moved) { model.drag.moved = true; ui.audio.currentTime = model.drag.playTime; ui.playTime.textContent = formatTime(model.drag.playTime); }
      model.viewStart = Math.max(0, Math.min(Math.max(0, model.duration - model.viewDuration), model.drag.viewStart - deltaX / rect.width * model.viewDuration));
      updateRangeLabels(); drawOverview(); drawDetail(); return;
    }
    const position = detailPosition(event.clientX);
    if (model.drag.kind === 'create') { model.drag.current = position.time; drawDetail(); return; }
    const row = model.segments.find(item => item.id === model.drag.rowId); if (!row) return;
    const delta = position.time - model.drag.pointerStart;
    const projectEnd = toProjectTime(model.duration);
    if (model.drag.kind === 'start') row.start = Math.max(0, Math.min(row.end - .001, Math.round((model.drag.start + delta) * 1000) / 1000));
    else if (model.drag.kind === 'end') row.end = Math.min(projectEnd, Math.max(row.start + .001, Math.round((model.drag.end + delta) * 1000) / 1000));
    model.dirty = true; updateDirtyIndicator(); renderInspector(); drawDetail(); validateTimeline();
  });

  ui.detail.addEventListener('pointerup', event => {
    if (!model.drag) return;
    if (model.drag.kind === 'pan') {
      const {moved, clickedRowId, toggleSelection: toggle} = model.drag; model.drag = null; clearDetailDragCursor();
      if (moved) loadDetailPeaks();
      else if (clickedRowId) { toggle ? toggleSelection(clickedRowId) : setSingleSelection(clickedRowId); renderAll(); }
      else { drawOverview(); drawDetail(); }
      return;
    }
    if (model.drag.kind === 'create') { const a = Math.min(model.drag.start, model.drag.current), b = Math.max(model.drag.start, model.drag.current); model.drag = null; clearDetailDragCursor(); if (b - a >= .001) addAt(a, b); else addAt(a, Math.min(model.duration, a + 1)); return; }
    model.drag = null; clearDetailDragCursor(); changed();
  });

  ui.detail.addEventListener('pointercancel', () => {
    if (!model.drag) return;
    const drag = model.drag; model.drag = null; clearDetailDragCursor();
    if (drag.kind === 'pan') { if (drag.moved) loadDetailPeaks(); else { drawOverview(); drawDetail(); } return; }
    if (drag.kind === 'create') { drawOverview(); drawDetail(); return; }
    changed();
  });

  ui.detail.addEventListener('pointerleave', () => { if (!model.drag) ui.detail.classList.remove('edge-hover'); });

  ui.add.addEventListener('click', () => { model.createMode = !model.createMode; ui.add.classList.toggle('primary', model.createMode); toast(t(model.createMode ? 'runtime.create_hint' : 'runtime.create_cancelled')); });
  function deleteRows(rows) {
    if (!rows.length) return;
    const nextStart = Math.min(...rows.map(row => row.start));
    snapshot();
    rows.forEach(row => { row.deleted = true; });
    const remaining = active();
    model.selectedIds = new Set([...model.selectedIds].filter(id => remaining.some(row => row.id === id)));
    if (!remaining.some(row => row.id === model.selectedId)) setSingleSelection(remaining.find(row => row.start >= nextStart)?.id || remaining.at(-1)?.id || null);
    changed();
    toast(t('runtime.rows_deleted', {count:rows.length}));
  }
  ui.delete.addEventListener('click', () => deleteRows(active().filter(row => model.selectedIds.has(row.id))));
  ui.split.addEventListener('click', () => {
    const row = selected(); if (!row) return; const projectPlayTime = toProjectTime(ui.audio.currentTime); const at = projectPlayTime > row.start && projectPlayTime < row.end ? projectPlayTime : (row.start + row.end) / 2;
    if (at - row.start < .001 || row.end - at < .001) return toast(t('runtime.split_inside'));
    snapshot(); row.deleted = true;
    const left = {...row, id: nextId(), end: at, deleted: false, needs_asr: false, origin_ids: [row.id]};
    const right = {...row, id: nextId(), start: at, text: '', deleted: false, manual_text: false, needs_asr: false, origin_ids: [row.id]};
    model.segments.push(left, right); setSingleSelection(left.id); changed();
  });
  ui.merge.addEventListener('click', () => {
    const rows = active().filter(row => model.selectedIds.has(row.id));
    if (rows.length < 2) return;
    const base = rows[0];
    snapshot();
    base.start = Math.min(...rows.map(row => row.start));
    base.end = Math.max(...rows.map(row => row.end));
    base.text = rows.map(row => row.text).filter(Boolean).join(' ');
    base.manual_text = rows.some(row => row.manual_text);
    base.needs_asr = false;
    base.origin_ids = [...new Set(rows.flatMap(row => [...(row.origin_ids || []), ...(row.id === base.id ? [] : [row.id])]))];
    rows.slice(1).forEach(row => { row.deleted = true; });
    setSingleSelection(base.id); changed(); centerOnSelected();
  });

  function editField(field, apply) {
    let before = null;
    field.addEventListener('focus', () => { before = cloneSegments(); });
    field.addEventListener('change', () => {
      const row = selected(); if (!row) return;
      try { model.history.push(captureState(before || cloneSegments())); model.future = []; apply(row, field.value); changed(); }
      catch (error) { toast(error.message); renderInspector(); }
    });
  }
  editField(ui.start, (row, value) => { const time = parseTime(value); if (time < 0 || time >= row.end) throw new Error(t('runtime.start_before_end')); row.start = time; });
  editField(ui.end, (row, value) => { const time = parseTime(value); if (time <= row.start) throw new Error(t('runtime.end_after_start')); row.end = time; });
  ui.speaker.addEventListener('change', () => {
    const row = selected(); if (!row) return;
    if (ui.speaker.value === '__new__') { openSpeakerNaming('inspector', row.id, row.speaker || 'Unassigned'); return; }
    if (ui.speaker.value === '__missing__') return;
    snapshot(); row.speaker = ui.speaker.value; changed();
  });
  ui.segmentTag.addEventListener('change', () => {
    const row = selected(); if (!row) return;
    if (ui.segmentTag.value === '__new__') { openTagNaming('inspector', row.id); return; }
    if (ui.segmentTag.value === '__missing__') return;
    snapshot(); row.tag = ui.segmentTag.value; changed();
  });
  let noteBefore = null, noteHistoryRecorded = false;
  ui.segmentNote.addEventListener('focus', () => { noteBefore = cloneSegments(); noteHistoryRecorded = false; });
  ui.segmentNote.addEventListener('input', () => {
    const row = selected(); if (!row) return;
    if (!noteHistoryRecorded) { model.history.push(captureState(noteBefore || cloneSegments())); model.future = []; noteHistoryRecorded = true; }
    row.note = ui.segmentNote.value; model.dirty = true; updateDirtyIndicator(); ui.undo.disabled = false; ui.redo.disabled = true;
  });
  ui.segmentNote.addEventListener('blur', () => { noteBefore = null; noteHistoryRecorded = false; });
  let transcriptBefore = null;
  let transcriptHistoryRecorded = false;
  function resetTranscriptEditSession() { transcriptBefore = null; transcriptHistoryRecorded = false; }
  function updateTranscriptMirrors(row) {
    const selector = `[data-segment-id="${CSS.escape(row.id)}"] .row-text`;
    document.querySelectorAll(selector).forEach(node => { node.textContent = row.text || t('runtime.no_transcript'); });
  }
  ui.transcript.addEventListener('focus', () => { transcriptBefore = cloneSegments(); transcriptHistoryRecorded = false; });
  ui.transcript.addEventListener('input', () => {
    const row = selected(); if (!row) return;
    if (!transcriptHistoryRecorded) {
      model.history.push(captureState(transcriptBefore || cloneSegments()));
      if (model.history.length > 60) model.history.shift();
      model.future = []; transcriptHistoryRecorded = true;
    }
    row.text = ui.transcript.value; row.manual_text = true; row.needs_asr = false; model.dirty = true;
    updateTranscriptMirrors(row); updateDirtyIndicator(); ui.undo.disabled = false; ui.redo.disabled = true;
  });
  ui.transcript.addEventListener('blur', resetTranscriptEditSession);

  ui.play.addEventListener('click', () => {
    if (!hasAudio()) return;
    if (!ui.audio.paused) { ui.audio.pause(); return; }
    model.playMode = 'continuous';
    stopSegmentMonitor();
    ui.audio.play().catch(error => toast(error.message));
  });
  ui.playSegment.addEventListener('click', () => {
    if (!hasAudio()) return;
    if (model.playMode === 'segment' && !ui.audio.paused) { ui.audio.pause(); return; }
    const row = selected(); if (!row) return;
    model.playMode = 'segment';
    model.segmentPlayback = {rowId: row.id, start: toAudioTime(row.start), end: toAudioTime(row.end)};
    ui.audio.currentTime = Math.max(0, Math.min(model.duration, toAudioTime(row.start)));
    syncPlaybackButtons();
    ui.audio.play().then(monitorSegmentBoundary).catch(error => { model.segmentPlayback = null; toast(error.message); });
  });

  function stopSegmentMonitor() {
    clearTimeout(model.segmentStopTimer);
    model.segmentStopTimer = null;
  }

  function segmentLoopEnabled() {
    return ui.loop.checked && model.segmentPlayback?.allowLoop !== false;
  }

  function enforceSegmentBoundary() {
    const target = model.segmentPlayback;
    if (model.playMode !== 'segment' || !target || ui.audio.currentTime < target.end) return false;
    if (segmentLoopEnabled()) {
      ui.audio.currentTime = target.start;
    } else {
      model.playMode = 'continuous';
      model.segmentPlayback = null;
      ui.audio.pause();
      ui.audio.currentTime = target.end;
      ui.playTime.textContent = formatTime(target.end);
      drawOverview(); drawDetail();
    }
    return true;
  }

  function monitorSegmentBoundary() {
    stopSegmentMonitor();
    if (model.playMode !== 'segment' || !model.segmentPlayback || ui.audio.paused) return;
    if (enforceSegmentBoundary()) {
      if (segmentLoopEnabled() && !ui.audio.paused) model.segmentStopTimer = setTimeout(monitorSegmentBoundary, 0);
      return;
    }
    const remaining = (model.segmentPlayback.end - ui.audio.currentTime) / Math.max(.01, ui.audio.playbackRate);
    model.segmentStopTimer = setTimeout(monitorSegmentBoundary, Math.max(1, Math.min(40, remaining * 1000)));
  }

  const playIcon = ui.play.querySelector('.transport-icon');
  const playLabel = ui.play.querySelector('.transport-label');
  function syncPlaybackButtons() {
    const playing = !ui.audio.paused;
    playIcon.textContent = playing ? '❚❚' : '▶';
    playLabel.textContent = playing ? t('runtime.pause') : t('review.play');
    ui.playSegment.textContent = playing && model.playMode === 'segment' ? t('runtime.pause_segment') : t('review.play_segment');
  }
  let audioStatusKind = '';
  function setAudioStatus(message = '', kind = '') {
    audioStatusKind = kind;
    ui.audioStatus.textContent = message;
    ui.audioStatus.classList.toggle('visible', Boolean(message));
  }
  ui.audio.addEventListener('play', () => { syncPlaybackButtons(); monitorSegmentBoundary(); });
  ui.audio.addEventListener('playing', () => { setAudioStatus(); syncPlaybackButtons(); });
  ui.audio.addEventListener('pause', () => { stopSegmentMonitor(); setAudioStatus(); syncPlaybackButtons(); });
  ui.audio.addEventListener('ended', () => { setAudioStatus(); syncPlaybackButtons(); });
  ui.audio.addEventListener('ratechange', monitorSegmentBoundary);
  ui.audio.addEventListener('waiting', () => { setAudioStatus(t('runtime.audio_loading'), 'waiting'); });
  ui.audio.addEventListener('seeking', () => { setAudioStatus(t('runtime.audio_seeking'), 'seeking'); });
  ui.audio.addEventListener('seeked', () => { if (audioStatusKind === 'seeking') setAudioStatus(); });
  ui.audio.addEventListener('timeupdate', () => {
    enforceSegmentBoundary();
    ui.playTime.textContent = formatTime(ui.audio.currentTime); drawOverview(); drawDetail();
  });

  ui.retranscribe.addEventListener('click', async () => {
    if (!hasAudio()) return;
    const row = selected(); if (!row) return;
    try {
      ui.retranscribe.disabled = true; ui.retranscribe.textContent = t('runtime.retranscribing');
      const result = await request('/api/retranscribe', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({id: row.id, start: row.start, end: row.end, speaker: row.speaker})});
      ui.asrOld.value = row.text || ''; ui.asrNew.value = result.text || ''; ui.asrDialog.showModal();
    } catch (error) { toast(error.message); }
    finally { ui.retranscribe.disabled = false; ui.retranscribe.textContent = t('review.retranscribe'); }
  });
  ui.exportClip.addEventListener('click', async () => {
    if (!hasAudio() || model.quickExportRunning) return;
    const row = selected(); if (!row) return;
    model.quickExportRunning = true; ui.exportClip.textContent = t('runtime.clipping'); renderInspector();
    try {
      const result = await request('/api/export-clip', {
        method: 'POST', headers: {'Content-Type':'application/json'},
        body: JSON.stringify({id:row.id, start:row.start, end:row.end, speaker:row.speaker, text:row.text, audio_offset:model.audioOffset}),
      });
      toast(result.cancelled ? t('runtime.clip_cancelled') : t('runtime.clip_exported', {name:result.name}));
    } catch (error) { toast(t('runtime.clip_failed', {error:error.message})); }
    finally { model.quickExportRunning = false; ui.exportClip.textContent = t('review.clip'); renderInspector(); }
  });
  ui.asrDialog.addEventListener('click', event => {
    if (event.target === ui.asrDialog) ui.asrDialog.close();
  });
  ui.acceptAsr.addEventListener('click', event => { event.preventDefault(); const row = selected(); if (!row) return; snapshot(); row.text = ui.asrNew.value; row.manual_text = false; row.needs_asr = false; ui.asrDialog.close(); changed(); });

  ui.speakerDialog.addEventListener('cancel', event => { event.preventDefault(); toast(t('runtime.assign_speaker_first')); });
  ui.speakerDialog.querySelector('form').addEventListener('submit', event => { event.preventDefault(); ui.assignSpeaker.click(); });
  ui.newSegmentSpeaker.addEventListener('focus', () => { model.newSegmentSpeakerPrevious = ui.newSegmentSpeaker.value; });
  ui.newSegmentSpeaker.addEventListener('change', () => {
    if (ui.newSegmentSpeaker.value === '__new__') {
      openSpeakerNaming('assignment', model.pendingSpeakerId, model.newSegmentSpeakerPrevious);
    } else {
      model.newSegmentSpeakerPrevious = ui.newSegmentSpeaker.value;
    }
  });
  ui.assignSpeaker.addEventListener('click', () => {
    const value = ui.newSegmentSpeaker.value;
    if (!value) return toast(t('runtime.select_speaker'));
    if (value === '__new__') { openSpeakerNaming('assignment', model.pendingSpeakerId, model.newSegmentSpeakerPrevious); return; }
    const row = model.segments.find(item => item.id === model.pendingSpeakerId && !item.deleted);
    if (!row) { model.pendingSpeakerId = null; ui.speakerDialog.close(); return; }
    row.speaker = value; model.pendingSpeakerId = null; ui.speakerDialog.close(); changed();
  });

  ui.cancelNewSpeaker.addEventListener('click', cancelSpeakerNaming);
  ui.speakerNameDialog.addEventListener('cancel', event => { event.preventDefault(); cancelSpeakerNaming(); });
  ui.speakerNameDialog.querySelector('form').addEventListener('submit', event => {
    event.preventDefault();
    const pending = model.pendingSpeakerCreate; if (!pending) return;
    const speaker = ui.newSpeakerName.value.trim() || nextSpeakerName();
    if (model.speakers.includes(speaker)) { toast(t('runtime.speaker_exists', {name:speaker})); ui.newSpeakerName.focus(); ui.newSpeakerName.select(); return; }
    model.speakers = sortSpeakerNames([...model.speakers, speaker]); model.selectedSpeakers.add(speaker);
    model.pendingSpeakerCreate = null; ui.speakerNameDialog.close();
    if (pending.kind === 'filter') { renderSpeakerFilters(); changed(); return; }
    if (pending.kind === 'assignment') {
      const createIndex = Math.max(0, ui.newSegmentSpeaker.options.length - 1);
      ui.newSegmentSpeaker.add(new Option(speaker, speaker), createIndex);
      ui.newSegmentSpeaker.value = speaker; model.newSegmentSpeakerPrevious = speaker;
      renderSpeakerFilters();
      return;
    }
    const row = model.segments.find(item => item.id === pending.rowId && !item.deleted);
    if (!row) { model.speakers = model.speakers.filter(name => name !== speaker); model.selectedSpeakers.delete(speaker); renderSpeakerFilters(); return; }
    model.history.push(pending.state); if (model.history.length > 60) model.history.shift(); model.future = [];
    row.speaker = speaker; renderSpeakerFilters(); changed();
  });

  ui.cancelNewTag.addEventListener('click', () => { model.pendingTagCreate = null; ui.tagNameDialog.close(); renderInspector(); });
  ui.tagNameDialog.addEventListener('cancel', () => { model.pendingTagCreate = null; });
  ui.tagNameDialog.querySelector('form').addEventListener('submit', event => {
    event.preventDefault(); const pending = model.pendingTagCreate, name = ui.newTagName.value.trim();
    if (!pending || !name) return toast(t('runtime.enter_tag'));
    if (model.tags.includes(name)) return toast(t('runtime.tag_exists', {name}));
    model.tags = sortTagNames([...model.tags, name]); model.selectedTags.add(name); model.pendingTagCreate = null; ui.tagNameDialog.close();
    if (pending.kind === 'inspector') { const row = model.segments.find(item => item.id === pending.rowId && !item.deleted); if (row) row.tag = name; }
    model.history.push(pending.state); model.future = []; changed(); renderSpeakerFilters();
  });

  function toast(message) { ui.toast.textContent = message; ui.toast.classList.add('show'); clearTimeout(toast.timer); toast.timer = setTimeout(() => ui.toast.classList.remove('show'), 4200); }

  function registerWebMcp() {
    const context = document.modelContext;
    if (!context?.registerTool) return;
    const register = tool => { try { Promise.resolve(context.registerTool(tool)).catch(() => {}); } catch (_) {} };
    register({
      name: 'read_current_review_segment', title: t('runtime.tool_read_title'),
      description: t('runtime.tool_read_description'),
      inputSchema: {type: 'object', properties: {}, additionalProperties: false},
      annotations: {readOnlyHint: true, untrustedContentHint: true},
      execute() {
        const rows = active(), index = rows.findIndex(row => row.id === model.selectedId);
        return {current: selected(), context: index < 0 ? [] : rows.slice(Math.max(0, index - 3), index + 4)};
      }
    });
    register({
      name: 'stage_current_review_segment_update', title: t('runtime.tool_stage_title'),
      description: t('runtime.tool_stage_description'),
      inputSchema: {
        type: 'object', additionalProperties: false,
        properties: {start: {type: 'number', minimum: 0}, end: {type: 'number', exclusiveMinimum: 0}, speaker: {type: 'string'}, text: {type: 'string'}}
      },
      annotations: {readOnlyHint: false, untrustedContentHint: false},
      execute(input) {
        const row = selected(); if (!row) throw new Error(t('runtime.no_selected_segment'));
        const start = input.start ?? row.start, end = input.end ?? row.end;
        if (!(Number.isFinite(start) && Number.isFinite(end) && start >= 0 && start < end && (!hasAudio() || end <= model.duration))) throw new Error(t('runtime.invalid_time_range'));
        snapshot(); row.start = start; row.end = end;
        if (input.speaker !== undefined) row.speaker = input.speaker;
        if (input.text !== undefined) { row.text = input.text; row.manual_text = true; row.needs_asr = false; }
        changed(); return {id: row.id, staged: true, start: row.start, end: row.end, speaker: row.speaker, text: row.text};
      }
    });
  }
  window.addEventListener('resize', () => { drawOverview(); drawDetail(); });
  window.addEventListener('beforeunload', event => {
    persistReviewView();
    if (!model.dirty) return;
    event.preventDefault();
    event.returnValue = '';
  });
  window.addEventListener('keydown', event => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') { event.preventDefault(); saveReview(); }
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'z') { event.preventDefault(); event.shiftKey ? restore(model.future, model.history) : restore(model.history, model.future); }
    if (event.code === 'Space' && !['INPUT','TEXTAREA','SELECT'].includes(document.activeElement?.tagName)) { event.preventDefault(); ui.play.click(); }
    const editing = ['INPUT','TEXTAREA','SELECT'].includes(document.activeElement?.tagName) || document.activeElement?.isContentEditable;
    if (event.key === 'Backspace' && !event.repeat && !editing && !document.querySelector('dialog[open]')) { event.preventDefault(); ui.delete.click(); }
  });
  registerWebMcp();
  syncZoomControl();
  stabilizeZoomControlWidth();
  syncPlaybackButtons();
  stabilizePlaybackButtonSizes();
  setInterval(checkDatabaseChanges, 3000);
  document.addEventListener('visibilitychange', checkDatabaseChanges);
  window.addEventListener('focus', checkDatabaseChanges);
  loadState();
});
