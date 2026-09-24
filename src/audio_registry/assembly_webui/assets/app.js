window.AudioRegistryI18n.ready.then(() => {
  'use strict';

  const t = window.AudioRegistryI18n.t;

  const el = id => document.getElementById(id);
  const ui = {
    app: el('app'), status: el('status'), refresh: el('refresh'), save: el('save'), cut: el('cut'), exportList: el('export-list'), exportTable: el('export-table'),
    export: el('export'), exportMenu: el('export-menu'), convertFormat: el('convert-format'), loudnessBalance: el('loudness-balance'),
    targetLufs: el('target-lufs'), normalizationStrength: el('normalization-strength'), gainLimit: el('gain-limit'), truePeakCeiling: el('true-peak-ceiling'),
    saveSlot: el('save-slot'), refreshSlot: el('refresh-slot'), speakerFilterSlot: el('speaker-filter-slot'), tagFilterSlot: el('tag-filter-slot'),
    projectSummary: el('project-summary'), projectOptions: el('project-options'),
    speakerFilter: el('speaker-filter'), speakerSummary: el('speaker-summary'), speakerSearch: el('speaker-search'),
    speakerAll: el('speaker-all'), speakerNone: el('speaker-none'), speakerOptions: el('speaker-options'), speakerAdd: el('speaker-add'),
    tagFilter: el('tag-filter'), tagSummary: el('tag-summary'), tagAll: el('tag-all'), tagNone: el('tag-none'), tagOptions: el('tag-options'), tagAdd: el('tag-add'),
    summary: el('summary'), filters: document.querySelector('.filters'), empty: el('empty-state'), groups: el('project-groups'), audio: el('audio'),
    tagDialog: el('tag-dialog'), tagForm: el('tag-form'), tagName: el('tag-name'), tagCancel: el('tag-cancel'), tagDialogHelp: el('tag-dialog-help'),
    speakerDialog: el('speaker-dialog'), speakerForm: el('speaker-form'), speakerName: el('speaker-name'), speakerCancel: el('speaker-cancel'), speakerDialogHelp: el('speaker-dialog-help'), toast: el('toast')
  };
  const palette = ['#56d6c2', '#7fa5ff', '#d68cf0', '#f0b862', '#ff7d8b', '#71d47f', '#56bee8', '#d6d06d'];
  const model = {
    availableProjects: [], projects: [], selectedProjects: new Set(), selectedSpeakers: new Set(), selectedTags: new Set(),
    collapsed: new Set(), rowLimits: new Map(), dirty: false, loading: false, exportRunning: false, updateCounters: null, remoteChanged: false, playing: null, stopTimer: null, tagTarget: null, speakerTarget: null
  };
  const UI_STATE_KEY = 'audio-registry.assembly-ui.v1';
  const LEGACY_UI_STATE_KEY = 'voice-segmenter.assembly-ui.v1';

  const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const variantLabel = index => {
    let value = index + 1, label = '';
    while (value) { const remainder = (value - 1) % 26; label = String.fromCharCode(65 + remainder) + label; value = Math.floor((value - 1) / 26); }
    return label;
  };
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
    const name = String(tag ?? ''), tags = allTags().map(item => String(item ?? ''));
    if (name === String(tags[0] ?? '')) return firstTagColor;
    return tags.includes(name) ? sequentialTagColor(name) : tagPalette[0];
  };
  const tagOption = (tag, selected = false) => {
    return `<option class="tag-option" style="--tag-color:${tagColor(tag)}" value="${escapeHtml(tag)}" ${selected ? 'selected' : ''}>${escapeHtml(tag)}</option>`;
  };
  const speakerColors = new Map();
  let speakerColorCursor = 0;
  function assignSpeakerColors(speakers) {
    speakers.forEach((speaker, index) => {
      if (speakerColors.has(speaker)) return;
      const adjacentColors = new Set([
        speakerColors.get(speakers[index - 1]),
        speakerColors.get(speakers[index + 1]),
      ].filter(Boolean));
      let color = palette[speakerColorCursor % palette.length];
      for (let offset = 0; offset < palette.length; offset += 1) {
        const candidate = palette[(speakerColorCursor + offset) % palette.length];
        if (!adjacentColors.has(candidate)) { color = candidate; break; }
      }
      speakerColors.set(speaker, color);
      speakerColorCursor = (palette.indexOf(color) + 1) % palette.length;
    });
  }
  const speakerColor = speaker => {
    if (!speakerColors.has(speaker)) assignSpeakerColors([speaker]);
    return speakerColors.get(speaker);
  };
  const sortSpeakerNames = names => [...new Set(names)].sort((left, right) => {
    const leftGenerated = /^speaker/i.test(left), rightGenerated = /^speaker/i.test(right);
    return Number(leftGenerated) - Number(rightGenerated) || left.localeCompare(right, 'zh-CN', {numeric:true});
  });
  const sortTagNames = names => [...new Set(names)].sort((left, right) => left.localeCompare(right, 'zh-CN', {numeric:true}));
  const allSpeakers = () => sortSpeakerNames(model.projects.flatMap(project => project.speakers || []));
  const allTags = () => sortTagNames(model.projects.flatMap(project => project.tags || []));
  const matchesCurrentFilters = (project, row) => (model.selectedSpeakers.has(row.speaker) || !project.speakers.includes(row.speaker)) && (model.selectedTags.has(row.tag) || !project.tags.includes(row.tag));
  const selectionKey = projectNames => [...projectNames].sort((a, b) => a.localeCompare(b, 'zh-CN')).join('\u001f');
  function readUiState() {
    try {
      const value = JSON.parse(localStorage.getItem(UI_STATE_KEY) || localStorage.getItem(LEGACY_UI_STATE_KEY) || sessionStorage.getItem(UI_STATE_KEY) || '{}');
      if (!value || typeof value !== 'object' || Array.isArray(value)) return {};
      if (!value.collapsedByProject || typeof value.collapsedByProject !== 'object' || Array.isArray(value.collapsedByProject)) {
        // Migrate combination-based memories, using each project's newest state.
        const collapsedByProject = new Map();
        Object.entries(value.viewsBySelection || {})
          .sort((left, right) => Number(left[1]?.updatedAt || 0) - Number(right[1]?.updatedAt || 0))
          .forEach(([key, view]) => {
            if (!Array.isArray(view?.collapsedProjects)) return;
            const collapsed = new Set(view.collapsedProjects);
            key.split('\u001f').filter(Boolean).forEach(name => collapsedByProject.set(name, collapsed.has(name)));
          });
        value.collapsedByProject = Object.fromEntries(collapsedByProject);
      }
      for (const view of Object.values(value.viewsBySelection || {})) {
        if (view && typeof view === 'object') delete view.collapsedProjects;
      }
      return value;
    } catch (_) { return {}; }
  }
  function persistUiState() {
    const projectNames = [...model.selectedProjects];
    const state = readUiState();
    const collapsedByProject = new Map(Object.entries(state.collapsedByProject || {}));
    projectNames.forEach(name => collapsedByProject.set(name, model.collapsed.has(name)));
    const viewsBySelection = state.viewsBySelection && typeof state.viewsBySelection === 'object' ? state.viewsBySelection : {};
    viewsBySelection[selectionKey(projectNames)] = {
      selectedSpeakers: [...model.selectedSpeakers],
      allSpeakersSelected: allSpeakers().every(name => model.selectedSpeakers.has(name)),
      selectedTags: [...model.selectedTags],
      allTagsSelected: allTags().every(name => model.selectedTags.has(name)),
      speakerSearch: ui.speakerSearch.value,
      updatedAt: Date.now(),
    };
    Object.keys(viewsBySelection)
      .sort((left, right) => Number(viewsBySelection[right]?.updatedAt || 0) - Number(viewsBySelection[left]?.updatedAt || 0))
      .slice(32)
      .forEach(key => delete viewsBySelection[key]);
    try {
      localStorage.setItem(UI_STATE_KEY, JSON.stringify({selectedProjects: projectNames, viewsBySelection, collapsedByProject:Object.fromEntries(collapsedByProject)}));
      localStorage.removeItem(LEGACY_UI_STATE_KEY);
    } catch (_) {}
  }
  function restoredView(projectNames, availableSpeakers, availableTags) {
    const state = readUiState();
    const saved = state.viewsBySelection?.[selectionKey(projectNames)] || {};
    const selectedSpeakers = saved.selectedSpeakers;
    const available = new Set(availableSpeakers);
    const availableTagSet = new Set(availableTags);
    return {
      selectedSpeakers: saved.allSpeakersSelected || !Array.isArray(selectedSpeakers) ? new Set(availableSpeakers) : new Set(selectedSpeakers.filter(name => available.has(name))),
      selectedTags: saved.allTagsSelected || !Array.isArray(saved.selectedTags) ? new Set(availableTags) : new Set(saved.selectedTags.filter(name => availableTagSet.has(name))),
      speakerSearch: typeof saved.speakerSearch === 'string' ? saved.speakerSearch : '',
      collapsedProjects: new Set(projectNames.filter(name => state.collapsedByProject?.[name] === true)),
    };
  }
  const formatDuration = seconds => t('runtime.duration_value', {value:Math.max(0, Number(seconds) || 0).toFixed(3)});
  const request = async (url, options) => {
    const response = await fetch(url, options);
    let data = {}; try { data = await response.json(); } catch (_) {}
    if (!response.ok) throw new Error(data.error || t('runtime.request_failed', {status:response.status}));
    return data;
  };
  function toast(message) {
    ui.toast.textContent = message; ui.toast.classList.add('visible'); clearTimeout(toast.timer);
    toast.timer = setTimeout(() => ui.toast.classList.remove('visible'), 4000);
  }
  function setDirty(value = true) {
    model.dirty = value; ui.save.disabled = !value || model.loading;
    ui.save.classList.toggle('primary', value);
    ui.status.textContent = value ? t('runtime.unsaved') : (model.projects.length ? t('runtime.synced') : t('common.select_project'));
    updateExportAvailability();
  }

  async function loadState(projectNames = [...model.selectedProjects], confirmDirty = false, rememberCurrent = true, preservePosition = false) {
    if (confirmDirty && model.dirty && !confirm(t('runtime.discard_refresh'))) return;
    const previousLimits = preservePosition ? new Map(model.rowLimits) : null;
    const previousScrollY = preservePosition ? window.scrollY : null;
    if (rememberCurrent) persistUiState();
    stopPlayback(); model.loading = true; ui.app.setAttribute('aria-busy', 'true'); ui.status.textContent = t('assembly.loading_database'); ui.save.disabled = true; updateRefreshIndicator();
    try {
      const query = projectNames.map(name => `project=${encodeURIComponent(name)}`).join('&');
      const data = await request(`/api/state${query ? `?${query}` : ''}`);
      model.availableProjects = data.available_projects || []; model.projects = data.projects || [];
      model.projects.forEach(project => { project.deleted_audio_ids = []; });
      applyExportSettings(data.clip_export);
      model.updateCounters = JSON.stringify(data.update_counters || {}); model.remoteChanged = false; updateRefreshIndicator();
      model.projects.forEach(project => {
        project.speakers = sortSpeakerNames(project.speakers || []);
        project.tags = sortTagNames(project.tags || ['1']);
      });
      model.selectedProjects = new Set(projectNames);
      const speakers = allSpeakers(), tags = allTags(), view = restoredView(projectNames, speakers, tags);
      model.selectedSpeakers = view.selectedSpeakers;
      model.selectedTags = view.selectedTags;
      model.collapsed = view.collapsedProjects;
      model.rowLimits = new Map(model.projects.map(project => [project.project_name, Math.max(120, previousLimits?.get(project.project_name) || 0)]));
      ui.speakerSearch.value = view.speakerSearch;
      renderProjectFilter(); renderSpeakerFilter(); renderTagFilter(); render(); setDirty(false);
      if (previousScrollY != null) {
        window.scrollTo({top:previousScrollY, behavior:'auto'});
        requestAnimationFrame(() => window.scrollTo({top:previousScrollY, behavior:'auto'}));
      }
      persistUiState();
    } catch (error) { toast(error.message); ui.status.textContent = t('runtime.load_failed'); }
    finally { model.loading = false; ui.app.setAttribute('aria-busy', 'false'); ui.save.disabled = !model.dirty; updateRefreshIndicator(); updateExportAvailability(); }
  }

  function updateRefreshIndicator() {
    ui.refresh.disabled = !model.remoteChanged || !model.projects.length || model.loading;
    ui.refresh.classList.toggle('primary', model.remoteChanged);
    ui.refresh.title = t(model.remoteChanged ? 'runtime.refresh_changed' : 'runtime.refresh_project');
  }
  let checkingDatabase = false;
  async function checkDatabaseChanges() {
    if (checkingDatabase || document.hidden || !model.projects.length || model.loading || (ui.save.disabled && model.dirty)) return;
    const projects = [...model.selectedProjects], baseline = model.updateCounters;
    const selection = selectionKey(projects);
    checkingDatabase = true;
    try {
      const query = projects.map(name => `project=${encodeURIComponent(name)}`).join('&');
      const data = await request(`/api/update-counters?${query}`);
      if (model.loading || selection !== selectionKey(model.selectedProjects) || baseline !== model.updateCounters || (ui.save.disabled && model.dirty)) return;
      model.remoteChanged = JSON.stringify(data.update_counters || {}) !== baseline;
      updateRefreshIndicator();
    } catch (_) { /* A temporary connection failure is not a database change. */ }
    finally { checkingDatabase = false; }
  }

  function renderProjectFilter() {
    ui.projectOptions.innerHTML = model.availableProjects.map(project => {
      const name = project.project_name; return `<label class="filter-option"><input type="checkbox" value="${escapeHtml(name)}" ${model.selectedProjects.has(name) ? 'checked' : ''}><span>${escapeHtml(name)}</span><small>${escapeHtml(t('runtime.rows', {count:project.segment_count}))}</small></label>`;
    }).join('') || `<div class="no-rows">${escapeHtml(t('runtime.no_projects'))}</div>`;
    const count = model.selectedProjects.size;
    ui.projectSummary.textContent = count ? t('runtime.projects_selected', {count}) : t('common.select_project');
  }
  function renderSpeakerFilter() {
    const query = ui.speakerSearch.value.trim().toLocaleLowerCase();
    const speakers = allSpeakers();
    assignSpeakerColors(speakers);
    ui.speakerOptions.innerHTML = speakers.filter(name => name.toLocaleLowerCase().includes(query)).map(name =>
      `<div class="filter-option managed-filter-option" data-speaker="${escapeHtml(name)}"><input type="checkbox" value="${escapeHtml(name)}" ${model.selectedSpeakers.has(name) ? 'checked' : ''}><span class="speaker-dot" style="--speaker-color:${speakerColor(name)}"></span><button class="managed-filter-name" data-action="rename-speaker" type="button" title="${escapeHtml(t('runtime.rename', {name}))}">${escapeHtml(name)}</button><button class="managed-filter-delete" data-action="delete-speaker" type="button">${escapeHtml(t('common.delete'))}</button></div>`
    ).join('') || `<div class="no-rows">${escapeHtml(t('runtime.no_speaker_match'))}</div>`;
    ui.speakerFilter.hidden = !model.projects.length;
    ui.speakerFilterSlot.hidden = ui.speakerFilter.hidden;
    const selectedCount = speakers.filter(name => model.selectedSpeakers.has(name)).length;
    ui.speakerSummary.textContent = selectedCount === speakers.length ? t('filter.speaker') : t('runtime.selected_fraction', {label:t('common.speaker'), selected:selectedCount, total:speakers.length});
  }
  function renderTagFilter() {
    const tags = allTags();
    syncTagColors(tags);
    ui.tagOptions.innerHTML = tags.map(name =>
      `<div class="filter-option tag-filter-option" data-tag="${escapeHtml(name)}" style="--tag-color:${tagColor(name)}"><input type="checkbox" value="${escapeHtml(name)}" ${model.selectedTags.has(name) ? 'checked' : ''}><button class="tag-filter-name tag-colored" data-action="rename-tag" type="button" title="${escapeHtml(t('runtime.rename', {name}))}">${escapeHtml(name)}</button><button class="tag-filter-delete" data-action="delete-tag" type="button">${escapeHtml(t('common.delete'))}</button></div>`
    ).join('') || `<div class="no-rows">${escapeHtml(t('runtime.no_tags'))}</div>`;
    ui.tagFilter.hidden = !model.projects.length;
    ui.tagFilterSlot.hidden = ui.tagFilter.hidden;
    const selectedCount = tags.filter(name => model.selectedTags.has(name)).length;
    ui.tagSummary.textContent = selectedCount === tags.length ? t('filter.tag') : t('runtime.selected_fraction', {label:t('common.tag'), selected:selectedCount, total:tags.length});
  }
  function render() {
    const hasProjects = model.projects.length > 0; ui.empty.hidden = hasProjects; ui.groups.hidden = !hasProjects;
    if (!hasProjects) { ui.groups.innerHTML = ''; ui.summary.textContent = t('assembly.nothing_selected'); scheduleStickyUpdate(); return; }
    const availableTags = allTags();
    let visible = 0;
    ui.groups.innerHTML = model.projects.map(project => {
      const rows = project.segments.filter(row => matchesCurrentFilters(project, row)); visible += rows.length;
      const limit = model.rowLimits.get(project.project_name) || 120, shownRows = rows.slice(0, limit);
      const collapsed = model.collapsed.has(project.project_name);
      const variants = project.variants.map(variant => `<div class="variant-chip ${variant.available ? '' : 'missing'}" title="${escapeHtml(variant.audio_path)}"><div class="variant-identity"><span class="variant-letter">${variant.label}</span><span class="variant-name">${escapeHtml(variant.name)}</span></div><div class="variant-controls"><label>${escapeHtml(t('runtime.offset'))} <input class="offset-input" data-action="offset" data-project="${escapeHtml(project.project_name)}" data-variant="${variant.id}" type="number" step="0.001" value="${Number(variant.offset_seconds || 0)}"><span class="offset-unit">${escapeHtml(t('runtime.second'))}</span></label><div class="variant-path-actions"><button class="variant-relocate" data-action="relocate-audio" data-variant="${variant.id}" type="button" title="${escapeHtml(t('runtime.relocate_help'))}">${escapeHtml(t('runtime.relocate'))}</button><button class="variant-delete" data-action="delete-audio" data-variant="${variant.id}" type="button" title="${escapeHtml(t('runtime.delete_audio_help'))}">${escapeHtml(t('common.delete'))}</button></div></div></div>`).join('');
      return `<section class="project-group ${collapsed ? 'collapsed' : ''}" data-project="${escapeHtml(project.project_name)}">
        <div class="project-tab-slot"><header class="project-tab"><button class="project-collapse" data-action="collapse" type="button" aria-expanded="${!collapsed}" aria-label="${escapeHtml(t(collapsed ? 'runtime.expand' : 'runtime.collapse'))} ${escapeHtml(project.project_name)}">${collapsed ? '▸' : '▾'}</button><strong title="${escapeHtml(project.project_name)}">${escapeHtml(project.project_name)}</strong></header></div>
        <div class="project-panel" ${collapsed ? 'hidden' : ''}>
          <div class="project-audio"><div class="variant-toolbar">${variants}<button class="mini-button variant-add-card" data-action="add-audio">＋ ${escapeHtml(t('runtime.add_audio'))}</button></div></div>
          <div class="group-body"><div class="column-head"><span>${escapeHtml(t('runtime.annotation_column'))}</span><span>${escapeHtml(t('runtime.audio_column'))}</span></div>${rows.length ? shownRows.map(row => renderRow(project, row, availableTags)).join('') : `<div class="no-rows">${escapeHtml(t('runtime.no_project_rows'))}</div>`}${rows.length > shownRows.length ? `<button class="load-more" data-action="load-more">${escapeHtml(t('runtime.load_more', {count:rows.length - shownRows.length}))}</button>` : ''}</div>
        </div>
      </section>`;
    }).join('');
    ui.summary.textContent = t('runtime.visible_summary', {projects:model.projects.length, rows:visible});
    observeLoadMore();
    scheduleStickyUpdate();
  }
  const stickyControls = [
    {slot:ui.saveSlot, control:ui.save},
    {slot:ui.refreshSlot, control:ui.refresh},
    {slot:ui.speakerFilterSlot, control:ui.speakerFilter},
    {slot:ui.tagFilterSlot, control:ui.tagFilter},
  ];
  function releaseStickyControl(control) {
    control.classList.remove('sticky-floating-control');
    control.style.removeProperty('--sticky-control-left');
    control.style.removeProperty('--sticky-control-width');
    control.style.removeProperty('--sticky-control-height');
  }
  function updateStickyControls() {
    const dockTop = Number.parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--sticky-control-top')) || 12;
    let floatingBottom = 0;
    const measurements = stickyControls.map(({slot, control}) => ({
      slot,
      control,
      slotRect: slot.getBoundingClientRect(),
      controlRect: control.getBoundingClientRect(),
      wasFloating: control.classList.contains('sticky-floating-control'),
    }));
    measurements.forEach(({slot, control, slotRect, controlRect, wasFloating}) => {
      if (slot.hidden || control.hidden) {
        releaseStickyControl(control); slot.style.removeProperty('width'); slot.style.removeProperty('height'); return;
      }
      if (slotRect.top <= dockTop) {
        const width = wasFloating ? slotRect.width : controlRect.width;
        const height = wasFloating ? slotRect.height : controlRect.height;
        slot.style.width = `${width}px`; slot.style.height = `${height}px`;
        control.style.setProperty('--sticky-control-left', `${slotRect.left}px`);
        control.style.setProperty('--sticky-control-width', `${width}px`);
        control.style.setProperty('--sticky-control-height', `${height}px`);
        control.classList.add('sticky-floating-control');
        floatingBottom = Math.max(floatingBottom, dockTop + height);
      } else {
        releaseStickyControl(control);
        slot.style.removeProperty('width');
        slot.style.removeProperty('height');
      }
    });
    document.documentElement.style.setProperty('--floating-controls-bottom', `${floatingBottom}px`);
    return floatingBottom;
  }
  function releaseProjectTab(tab) {
    tab.classList.remove('project-tab-floating');
    tab.style.removeProperty('--project-tab-left');
    tab.style.removeProperty('--project-tab-width');
    tab.style.removeProperty('--project-tab-height');
  }
  function updateProjectTab(floatingBottom) {
    const dockTop = floatingBottom + 8;
    const measurements = [...ui.groups.querySelectorAll('.project-group')].map(group => {
      const slot = group.querySelector('.project-tab-slot');
      const tab = group.querySelector('.project-tab');
      return {group, slot, tab, expanded:!group.classList.contains('collapsed'), groupRect:group.getBoundingClientRect(), slotRect:slot.getBoundingClientRect(), tabRect:tab.getBoundingClientRect()};
    });
    let activeIndex = -1;
    measurements.forEach(({expanded, slotRect}, index) => { if (expanded && slotRect.top <= dockTop) activeIndex = index; });
    if (activeIndex >= 0 && measurements[activeIndex].groupRect.bottom <= dockTop) activeIndex = -1;
    measurements.forEach(({slotRect, tab, tabRect}, index) => {
      if (index !== activeIndex) { releaseProjectTab(tab); return; }
      tab.style.setProperty('--project-tab-left', `${slotRect.left}px`);
      tab.style.setProperty('--project-tab-width', `${tabRect.width}px`);
      tab.style.setProperty('--project-tab-height', `${tabRect.height}px`);
      tab.classList.add('project-tab-floating');
    });
  }
  let stickyFrame = 0;
  let projectAnchorFrame = 0;
  function updateStickyLayout() {
    updateProjectTab(updateStickyControls());
  }
  function scheduleStickyUpdate() {
    cancelAnimationFrame(stickyFrame);
    stickyFrame = requestAnimationFrame(() => {
      stickyFrame = 0;
      updateStickyLayout();
    });
  }
  function scheduleProjectAnchor(group, anchorTop) {
    cancelAnimationFrame(projectAnchorFrame);
    projectAnchorFrame = requestAnimationFrame(() => {
      projectAnchorFrame = 0;
      const slot = group.querySelector('.project-tab-slot');
      const targetTop = window.scrollY + slot.getBoundingClientRect().top - anchorTop;
      window.scrollTo({top:Math.max(0, targetTop), behavior:'auto'});
      updateStickyLayout();
    });
  }
  function observeLoadMore() {
    if (!('IntersectionObserver' in window)) return;
    const observer = new IntersectionObserver(entries => { for (const entry of entries) if (entry.isIntersecting) { observer.disconnect(); loadMore(entry.target); break; } }, {rootMargin:'500px'});
    ui.groups.querySelectorAll('.load-more').forEach(button => observer.observe(button));
  }
  function loadMore(target) { const {project} = findContext(target); if (!project) return; model.rowLimits.set(project.project_name, (model.rowLimits.get(project.project_name) || 120) + 120); render(); }
  function renderRow(project, row, availableTags) {
    const multiple = project.variants.length > 1;
    const missingSelection = !row.selected_variant_id || !project.variants.some(variant => variant.id === row.selected_variant_id);
    const missingTag = !availableTags.includes(row.tag);
    const missingTagOption = missingTag ? `<option value="__missing__" selected disabled>${escapeHtml(t('runtime.deleted_value', {name:row.tag}))}</option>` : '';
    const options = availableTags.map(tag => tagOption(tag, row.tag === tag)).join('');
    const missingSpeaker = !project.speakers.includes(row.speaker);
    const missingSpeakerOption = missingSpeaker ? `<option value="__missing__" selected disabled>${escapeHtml(t('runtime.deleted_value', {name:row.speaker}))}</option>` : '';
    const speakerOptions = project.speakers.map(name => `<option value="${escapeHtml(name)}" ${row.speaker === name ? 'selected' : ''}>${escapeHtml(name)}</option>`).join('');
    const candidates = project.variants.map(variant => {
      const selected = row.selected_variant_id === variant.id;
      return `<div class="candidate ${selected ? 'selected' : ''} ${variant.available ? '' : 'missing'}"><div class="candidate-head"><input data-action="variant" type="radio" name="variant-${escapeHtml(project.id)}-${escapeHtml(row.id)}" value="${variant.id}" ${selected ? 'checked' : ''} ${!multiple || !variant.available ? 'disabled' : ''}><span class="variant-letter">${variant.label}</span><span class="candidate-name" title="${escapeHtml(variant.audio_path)}">${escapeHtml(variant.name)}</span></div><div class="candidate-actions"><button class="play-button" data-action="play" data-variant="${variant.id}" ${variant.available ? '' : 'disabled'}>${escapeHtml(t('runtime.play'))}</button></div></div>`;
    }).join('');
    const hasVariants = project.variants.length > 0;
    const audioContent = hasVariants ? `<div class="duration">${missingSelection ? `<strong>${escapeHtml(t('runtime.no_audio_selected'))}</strong>` : ''}${escapeHtml(t('review.duration'))} ${formatDuration(row.duration)}</div><div class="candidate-list">${candidates}</div>` : '';
    return `<article class="assembly-row" data-segment="${escapeHtml(row.id)}"><div class="text-cell"><div class="row-meta"><select class="speaker-select ${missingSpeaker ? 'missing-speaker' : ''}" data-field="speaker" title="${missingSpeaker ? escapeHtml(t('runtime.missing_speaker_help')) : ''}">${missingSpeakerOption}${speakerOptions}<option value="__new__">＋ ${escapeHtml(t('review.new_speaker'))}</option></select><span class="project-label">${escapeHtml(row.id)}</span></div><textarea class="transcript" data-field="text">${escapeHtml(row.text)}</textarea><div class="annotation-row"><select class="tag-select tag-colored ${missingTag ? 'missing-tag' : ''}" style="--tag-color:${tagColor(row.tag)}" data-field="tag" title="${missingTag ? escapeHtml(t('runtime.missing_tag_help')) : ''}">${missingTagOption}${options}<option value="__new__">＋ ${escapeHtml(t('review.new_tag'))}</option></select><textarea class="note" data-field="note" maxlength="10000" placeholder="${escapeHtml(t('common.notes'))}">${escapeHtml(row.note)}</textarea></div></div><div class="audio-cell ${hasVariants && missingSelection ? 'missing-selection' : ''}">${audioContent}</div></article>`;
  }

  const findContext = target => {
    const group = target.closest('.project-group'), article = target.closest('.assembly-row');
    if (!group) return {};
    const project = model.projects.find(item => item.project_name === group.dataset.project);
    const row = article && project?.segments.find(item => item.id === article.dataset.segment);
    return {project, row, group, article};
  };
  ui.projectOptions.addEventListener('change', async event => {
    const checked = [...ui.projectOptions.querySelectorAll('input:checked')].map(input => input.value);
    if (model.dirty && !confirm(t('runtime.discard_switch'))) { renderProjectFilter(); return; }
    await loadState(checked);
  });
  document.addEventListener('pointerdown', event => {
    document.querySelectorAll('details[open]').forEach(menu => {
      if (!menu.contains(event.target)) menu.open = false;
    });
  });
  document.addEventListener('toggle', event => {
    if (!(event.target instanceof HTMLDetailsElement) || !event.target.open) return;
    document.querySelectorAll('details[open]').forEach(menu => { if (menu !== event.target) menu.open = false; });
  }, true);
  function resetLimits() { model.projects.forEach(project => model.rowLimits.set(project.project_name, 120)); }
  function renderAtCurrentScroll() {
    const scrollY = window.scrollY;
    render();
    window.scrollTo({top:scrollY, behavior:'auto'});
    requestAnimationFrame(() => window.scrollTo({top:scrollY, behavior:'auto'}));
  }
  ui.speakerOptions.addEventListener('change', event => { event.target.checked ? model.selectedSpeakers.add(event.target.value) : model.selectedSpeakers.delete(event.target.value); persistUiState(); resetLimits(); renderSpeakerFilter(); render(); });
  ui.speakerSearch.addEventListener('input', () => { persistUiState(); renderSpeakerFilter(); });
  ui.speakerAll.addEventListener('click', () => { model.selectedSpeakers = new Set(allSpeakers()); persistUiState(); resetLimits(); renderSpeakerFilter(); render(); });
  ui.speakerNone.addEventListener('click', () => { model.selectedSpeakers.clear(); persistUiState(); resetLimits(); renderSpeakerFilter(); render(); });
  ui.speakerAdd.addEventListener('click', () => openSpeakerDialog({kind:'filter'}));
  function renameSpeaker(oldName, requestedName) {
    const newName = requestedName.trim();
    if (!newName) { toast(t('runtime.speaker_empty')); renderSpeakerFilter(); return; }
    if (newName.length > 100) { toast(t('runtime.name_too_long')); renderSpeakerFilter(); return; }
    if (newName === oldName) { renderSpeakerFilter(); return; }
    const mergingProjects = model.projects.filter(project => project.speakers.includes(oldName) && project.speakers.includes(newName));
    if (mergingProjects.length && !confirm(t('runtime.speaker_merge_confirm', {newName, oldName}))) { renderSpeakerFilter(); return; }
    model.projects.forEach(project => {
      project.speakers = sortSpeakerNames(project.speakers.map(name => name === oldName ? newName : name));
      project.segments.forEach(row => { if (row.speaker === oldName) row.speaker = newName; });
    });
    const oldSelected = model.selectedSpeakers.delete(oldName);
    if (oldSelected || model.selectedSpeakers.has(newName)) model.selectedSpeakers.add(newName);
    if (!mergingProjects.length && speakerColors.has(oldName) && !speakerColors.has(newName)) speakerColors.set(newName, speakerColors.get(oldName));
    speakerColors.delete(oldName);
    setDirty(); persistUiState(); resetLimits(); renderSpeakerFilter(); render();
    toast(t(mergingProjects.length ? 'runtime.merged' : 'runtime.renamed', {oldName, newName}));
  }
  function beginManagedRename(button, oldName, commit, rerender) {
    const input = document.createElement('input'); input.type = 'text'; input.className = 'managed-name-editor'; input.maxLength = 100; input.value = oldName;
    button.replaceWith(input); input.focus(); input.select(); let cancelled = false;
    input.addEventListener('keydown', event => { if (event.key === 'Enter') { event.preventDefault(); input.blur(); } if (event.key === 'Escape') { event.preventDefault(); cancelled = true; rerender(); } });
    input.addEventListener('blur', () => { if (!cancelled) commit(oldName, input.value); }, {once:true});
  }
  function deleteSpeaker(name) {
    const affected = model.projects.filter(project => project.speakers.includes(name));
    if (affected.some(project => project.speakers.length <= 1)) { toast(t('runtime.keep_one_speaker')); return; }
    affected.forEach(project => { project.speakers = project.speakers.filter(speaker => speaker !== name); });
    model.selectedSpeakers.delete(name); setDirty(); persistUiState(); resetLimits(); renderSpeakerFilter(); render();
  }
  ui.speakerOptions.addEventListener('click', event => {
    const button = event.target.closest('button'); if (!button) return;
    const option = button.closest('[data-speaker]'), name = option?.dataset.speaker; if (!name) return;
    if (button.dataset.action === 'rename-speaker') beginManagedRename(button, name, renameSpeaker, renderSpeakerFilter);
    if (button.dataset.action === 'delete-speaker') deleteSpeaker(name);
  });
  ui.tagOptions.addEventListener('change', event => { event.target.checked ? model.selectedTags.add(event.target.value) : model.selectedTags.delete(event.target.value); persistUiState(); resetLimits(); renderTagFilter(); render(); });
  ui.tagAll.addEventListener('click', () => { model.selectedTags = new Set(allTags()); persistUiState(); resetLimits(); renderTagFilter(); render(); });
  ui.tagNone.addEventListener('click', () => { model.selectedTags.clear(); persistUiState(); resetLimits(); renderTagFilter(); render(); });
  ui.tagAdd.addEventListener('click', () => { model.tagTarget = {kind:'filter'}; ui.tagName.value = ''; ui.tagDialogHelp.textContent = t('runtime.tag_filter_add_help'); ui.tagDialog.showModal(); ui.tagName.focus(); });
  function renameTag(oldName, requestedName) {
    const newName = requestedName.trim();
    if (!newName || newName.length > 100) { toast(t('runtime.tag_invalid')); renderTagFilter(); return; }
    if (newName === oldName) { renderTagFilter(); return; }
    const mergesExistingTag = allTags().includes(newName);
    const affectedRows = model.projects.reduce((count, project) => count + project.segments.filter(row => row.tag === oldName).length, 0);
    if (mergesExistingTag && !confirm(t('runtime.tag_merge_confirm', {newName, oldName, count:affectedRows}))) { renderTagFilter(); return; }
    model.projects.forEach(project => {
      project.tags = sortTagNames(project.tags.map(name => name === oldName ? newName : name));
      project.segments.forEach(row => { if (row.tag === oldName) row.tag = newName; });
    });
    const oldSelected = model.selectedTags.delete(oldName);
    if (oldSelected || model.selectedTags.has(newName)) model.selectedTags.add(newName);
    setDirty(); persistUiState(); resetLimits(); renderTagFilter(); render();
    toast(t(mergesExistingTag ? 'runtime.merged' : 'runtime.renamed', {oldName, newName}));
  }
  function beginTagRename(button, oldName) {
    beginManagedRename(button, oldName, renameTag, renderTagFilter);
  }
  function deleteTag(name) {
    const affected = model.projects.filter(project => project.tags.includes(name));
    if (affected.some(project => project.tags.length <= 1)) { toast(t('runtime.keep_one_tag')); return; }
    affected.forEach(project => { project.tags = project.tags.filter(tag => tag !== name); });
    model.selectedTags.delete(name); setDirty(); persistUiState(); resetLimits(); renderTagFilter(); render();
  }
  ui.tagOptions.addEventListener('click', event => {
    const button = event.target.closest('button'); if (!button) return;
    const option = button.closest('[data-tag]'), name = option?.dataset.tag; if (!name) return;
    if (button.dataset.action === 'rename-tag') beginTagRename(button, name);
    if (button.dataset.action === 'delete-tag') deleteTag(name);
  });
  ui.groups.addEventListener('input', event => {
    const {project, row} = findContext(event.target); if (!project) return;
    if (event.target.dataset.action === 'offset') { const variant = project.variants.find(item => item.id === event.target.dataset.variant); if (variant) { variant.offset_seconds = Number(event.target.value) || 0; setDirty(); } }
    if (row && event.target.dataset.field === 'text') { row.text = event.target.value; setDirty(); }
    if (row && event.target.dataset.field === 'note') { row.note = event.target.value; setDirty(); }
  });
  ui.groups.addEventListener('change', event => {
    const {project, row} = findContext(event.target); if (!project || !row) return;
    if (event.target.dataset.field === 'tag') {
      if (event.target.value === '__new__') { event.target.value = row.tag; model.tagTarget = {kind:'row', project, row, includeNewTag:allTags().every(name => model.selectedTags.has(name))}; ui.tagName.value = ''; ui.tagDialogHelp.textContent = t('runtime.tag_row_add_help'); ui.tagDialog.showModal(); ui.tagName.focus(); }
      else {
        row.tag = event.target.value;
        if (!project.tags.includes(row.tag)) project.tags = sortTagNames([...project.tags, row.tag]);
        setDirty(); renderTagFilter(); renderAtCurrentScroll();
      }
    }
    if (event.target.dataset.field === 'speaker') {
      if (event.target.value === '__new__') { event.target.value = row.speaker; openSpeakerDialog({kind:'row', project, row, includeNewSpeaker:allSpeakers().every(name => model.selectedSpeakers.has(name))}); }
      else { row.speaker = event.target.value; setDirty(); renderSpeakerFilter(); renderAtCurrentScroll(); }
    }
    if (event.target.dataset.action === 'variant') { row.selected_variant_id = event.target.value; setDirty(); renderAtCurrentScroll(); }
  });
  ui.groups.addEventListener('click', async event => {
    const button = event.target.closest('button'); if (!button) return;
    const {project, row, group} = findContext(button); if (!project) return;
    if (button.dataset.action === 'collapse') {
      const anchorTop = group.querySelector('.project-tab').getBoundingClientRect().top;
      const collapsed = !model.collapsed.has(project.project_name);
      if (collapsed) model.collapsed.add(project.project_name);
      else model.collapsed.delete(project.project_name);
      group.classList.toggle('collapsed', collapsed);
      group.querySelector('.project-panel').hidden = collapsed;
      button.textContent = collapsed ? '▸' : '▾';
      button.setAttribute('aria-expanded', String(!collapsed));
      button.setAttribute('aria-label', `${t(collapsed ? 'runtime.expand' : 'runtime.collapse')} ${project.project_name}`);
      persistUiState();
      scheduleProjectAnchor(group, anchorTop);
    }
    if (button.dataset.action === 'load-more') loadMore(button);
    if (button.dataset.action === 'play' && row) play(project, row, button.dataset.variant);
    if (button.dataset.action === 'add-audio') {
      const hadVariants = project.variants.length > 0;
      button.disabled = true; ui.status.textContent = `${t('common.select_audio')}…`;
      try {
        const result = await request('/api/add-audio', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({project_name:project.project_name, active_asset_ids:project.variants.map(item => item.id), deleted_audio_ids:[...(project.deleted_audio_ids || [])]})});
        if (result.count) {
          (result.assets || []).forEach(asset => project.variants.push({...asset, label:variantLabel(project.variants.length), pending:true}));
          if (!hadVariants && project.variants.length) {
            project.segments.forEach(row => { if (!row.selected_variant_id) row.selected_variant_id = project.variants[0].id; });
          }
          setDirty(); render(); toast(t('runtime.audio_added', {count:result.count}));
        } else ui.status.textContent = model.dirty ? t('runtime.unsaved') : t('runtime.export_cancelled');
      }
      catch (error) { toast(error.message); } finally { button.disabled = false; }
    }
    if (button.dataset.action === 'relocate-audio') {
      const variant = project.variants.find(item => item.id === button.dataset.variant); if (!variant) return;
      stopPlayback(); button.disabled = true; ui.status.textContent = t('runtime.audio_relocate_prompt');
      try {
        const result = await request('/api/relocate-audio', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({project_name:project.project_name, asset_id:variant.id})});
        if (result.relocated) {
          Object.assign(variant, result.asset, {label:variant.label, pending:Boolean(variant.pending), relocated:!variant.pending});
          ui.audio.removeAttribute('src'); ui.audio.load(); setDirty(); render(); toast(t('runtime.audio_relocated'));
        } else ui.status.textContent = model.dirty ? t('runtime.unsaved') : t('runtime.export_cancelled');
      } catch (error) { toast(error.message); } finally { button.disabled = false; }
    }
    if (button.dataset.action === 'delete-audio') {
      const variant = project.variants.find(item => item.id === button.dataset.variant); if (!variant) return;
      if (model.playing?.project === project.project_name && model.playing?.variant === variant.id) stopPlayback();
      if (!variant.pending) project.deleted_audio_ids = [...new Set([...(project.deleted_audio_ids || []), variant.id])];
      project.variants = project.variants.filter(item => item.id !== variant.id);
      project.segments.forEach(row => { if (row.selected_variant_id === variant.id) row.selected_variant_id = null; });
      setDirty(); render(); toast(t('runtime.audio_delete_staged'));
    }
  });
  window.addEventListener('scroll', scheduleStickyUpdate, {passive:true});
  window.addEventListener('resize', scheduleStickyUpdate);

  async function play(project, row, variantId) {
    const variant = project.variants.find(item => item.id === variantId); if (!variant?.available) return;
    if (model.playing?.project === project.project_name && model.playing?.row === row.id && model.playing?.variant === variantId && !ui.audio.paused) { ui.audio.pause(); updatePlayButtons(); return; }
    stopPlayback(); model.playing = {project:project.project_name, row:row.id, variant:variantId, end:row.end + Number(variant.offset_seconds || 0)};
    ui.audio.src = `/api/audio?id=${encodeURIComponent(variantId)}`; ui.audio.currentTime = Math.max(0, row.start + Number(variant.offset_seconds || 0));
    try { await ui.audio.play(); ui.status.textContent = t('runtime.playing', {project:project.project_name, variant:variant.label}); updatePlayButtons(); model.stopTimer = setInterval(() => { if (model.playing && ui.audio.currentTime >= model.playing.end - .005) stopPlayback(); }, 20); }
    catch (error) { stopPlayback(); toast(t('runtime.play_failed', {error:error.message})); }
  }
  function stopPlayback() { clearInterval(model.stopTimer); model.stopTimer = null; if (!ui.audio.paused) ui.audio.pause(); model.playing = null; updatePlayButtons(); if (!model.dirty) ui.status.textContent = model.projects.length ? t('runtime.synced') : t('common.select_project'); }
  function updatePlayButtons() { ui.groups.querySelectorAll('[data-action="play"]').forEach(button => { const {project, row} = findContext(button); const playing = model.playing && project?.project_name === model.playing.project && row?.id === model.playing.row && button.dataset.variant === model.playing.variant && !ui.audio.paused; button.textContent = t(playing ? 'runtime.pause' : 'runtime.play'); }); }
  ui.audio.addEventListener('ended', stopPlayback); ui.audio.addEventListener('pause', updatePlayButtons);

  ui.tagCancel.addEventListener('click', () => { model.tagTarget = null; ui.tagDialog.close(); });
  ui.tagDialog.addEventListener('cancel', () => { model.tagTarget = null; });
  ui.tagForm.addEventListener('submit', event => {
    event.preventDefault(); const target = model.tagTarget, name = ui.tagName.value.trim(); if (!target || !name) { toast(t('runtime.enter_tag')); return; }
    if (name.length > 100) { toast(t('runtime.name_too_long')); return; }
    const filterLevel = target.kind === 'filter';
    if (target.kind === 'filter') {
      if (model.projects.every(project => project.tags.includes(name))) { toast(t('runtime.tag_exists', {name})); return; }
      model.projects.forEach(project => { if (!project.tags.includes(name)) project.tags = sortTagNames([...project.tags, name]); }); model.selectedTags.add(name);
    } else {
      if (!target.project.tags.includes(name)) target.project.tags = sortTagNames([...target.project.tags, name]); target.row.tag = name; if (target.includeNewTag) model.selectedTags.add(name);
    }
    model.tagTarget = null; ui.tagDialog.close(); setDirty(); persistUiState(); if (filterLevel) resetLimits(); renderTagFilter(); filterLevel ? render() : renderAtCurrentScroll();
  });

  function openSpeakerDialog(target) {
    model.speakerTarget = target; ui.speakerName.value = '';
    ui.speakerDialogHelp.textContent = target.kind === 'filter'
      ? t('runtime.speaker_filter_add_help')
      : t('runtime.speaker_row_add_help');
    ui.speakerDialog.showModal(); ui.speakerName.focus();
  }
  function nextSpeakerName(names) {
    const numbered = names.map(name => { const match = String(name).match(/^(.*?)(\d+)$/); return match ? {prefix:match[1], number:Number(match[2]), width:match[2].length} : null; }).filter(Boolean);
    if (!numbered.length) return `Speaker_${String(names.length + 1).padStart(2, '0')}`;
    const highest = numbered.reduce((best, item) => item.number > best.number ? item : best), next = highest.number + 1;
    return `${highest.prefix}${String(next).padStart(Math.max(highest.width, String(next).length), '0')}`;
  }
  ui.speakerCancel.addEventListener('click', () => { model.speakerTarget = null; ui.speakerDialog.close(); render(); });
  ui.speakerDialog.addEventListener('cancel', () => { model.speakerTarget = null; });
  ui.speakerForm.addEventListener('submit', event => {
    event.preventDefault(); const target = model.speakerTarget; if (!target) return;
    const names = target.kind === 'filter' ? allSpeakers() : target.project.speakers;
    const name = ui.speakerName.value.trim() || nextSpeakerName(names);
    const filterLevel = target.kind === 'filter';
    if (name.length > 100) { toast(t('runtime.name_too_long')); return; }
    if (target.kind === 'filter') {
      if (model.projects.every(project => project.speakers.includes(name))) { toast(t('runtime.speaker_exists', {name})); return; }
      model.projects.forEach(project => { if (!project.speakers.includes(name)) project.speakers = sortSpeakerNames([...project.speakers, name]); }); model.selectedSpeakers.add(name);
    } else {
      if (!target.project.speakers.includes(name)) target.project.speakers = sortSpeakerNames([...target.project.speakers, name]);
      target.row.speaker = name; if (target.includeNewSpeaker) model.selectedSpeakers.add(name);
    }
    model.speakerTarget = null; ui.speakerDialog.close(); setDirty(); persistUiState(); if (filterLevel) resetLimits(); renderSpeakerFilter(); filterLevel ? render() : renderAtCurrentScroll();
  });

  function payload() { return {projects:model.projects.map(project => ({project_name:project.project_name, revision:project.revision, deleted_audio_ids:[...(project.deleted_audio_ids || [])], added_audio:project.variants.filter(v => v.pending).map(v => ({id:v.id, name:v.name, audio_path:v.audio_path, duration_seconds:v.duration_seconds})), relocated_audio:project.variants.filter(v => v.relocated && !v.pending).map(v => ({id:v.id, audio_path:v.audio_path, duration_seconds:v.duration_seconds})), offsets:Object.fromEntries(project.variants.map(v => [v.id, Number(v.offset_seconds || 0)])), items:project.segments.map(row => ({id:row.id, speaker:row.speaker, text:row.text, tag:row.tag, note:row.note, selected_variant_id:row.selected_variant_id}))}))}; }
  function missingSelections() { return model.projects.flatMap(project => project.segments.filter(row => !row.selected_variant_id || !project.variants.some(variant => variant.id === row.selected_variant_id)).map(row => ({project, row}))); }
  async function save() {
    if (!model.dirty) return true; ui.save.disabled = true; ui.status.textContent = t('runtime.saving');
    const missingSpeakers = model.projects.flatMap(project => project.segments.filter(row => !project.speakers.includes(row.speaker)).map(row => ({project, row})));
    if (missingSpeakers.length) {
      if (!confirm(t('runtime.missing_speakers_save', {count:missingSpeakers.length}))) { ui.save.disabled = false; ui.status.textContent = t('runtime.unsaved'); return false; }
      missingSpeakers.forEach(({project, row}) => { row.speaker = project.speakers[0]; }); render();
    }
    const missingTags = model.projects.flatMap(project => project.segments.filter(row => !project.tags.includes(row.tag)).map(row => ({project, row})));
    if (missingTags.length) {
      if (!confirm(t('runtime.missing_tags_save', {count:missingTags.length}))) { ui.save.disabled = false; ui.status.textContent = t('runtime.unsaved'); return false; }
      missingTags.forEach(({project, row}) => { row.tag = project.tags[0]; }); render();
    }
    const missing = missingSelections().filter(item => item.project.variants.length);
    if (missing.length) {
      if (!confirm(t('runtime.missing_audio_save', {count:missing.length}))) { ui.save.disabled = false; ui.status.textContent = t('runtime.unsaved'); return false; }
      missing.forEach(({project, row}) => { row.selected_variant_id = project.variants[0].id; }); render();
    }
    try {
      const savePayload = payload();
      const audioChanged = savePayload.projects.some(project => project.deleted_audio_ids.length || project.added_audio.length || project.relocated_audio.length);
      const data = await request('/api/save', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(savePayload)});
      if (audioChanged) await loadState([...model.selectedProjects], false, true, true);
      else {
        model.projects.forEach(project => { if (data.revisions?.[project.project_name] != null) project.revision = data.revisions[project.project_name]; });
        model.updateCounters = JSON.stringify(data.update_counters || {}); model.remoteChanged = false; updateRefreshIndicator(); setDirty(false);
      }
      toast(t('runtime.database_saved')); return true;
    }
    catch (error) { ui.save.disabled = false; ui.status.textContent = t('runtime.save_failed'); toast(error.message); return false; }
  }
  ui.save.addEventListener('click', save); ui.refresh.addEventListener('click', () => loadState([...model.selectedProjects], true));
  function applyExportSettings(settings = {}) {
    ui.convertFormat.checked = Boolean(settings.convert_format);
    ui.loudnessBalance.checked = Boolean(settings.loudness_balance);
    ui.targetLufs.value = settings.target_lufs ?? -24;
    ui.normalizationStrength.value = (settings.normalization_strength ?? 0.7) * 100;
    ui.gainLimit.value = settings.gain_limit_db ?? 8;
    ui.truePeakCeiling.value = settings.true_peak_ceiling_dbtp ?? -1.5;
  }
  function exportSettings() {
    const numbers = [ui.targetLufs, ui.normalizationStrength, ui.gainLimit, ui.truePeakCeiling];
    if (numbers.some(input => !input.value.trim() || !input.checkValidity())) throw new Error(t('runtime.invalid_loudness'));
    return {convert_format:ui.convertFormat.checked, loudness_balance:ui.loudnessBalance.checked,
      target_lufs:Number(ui.targetLufs.value), normalization_strength:Number(ui.normalizationStrength.value) / 100,
      gain_limit_db:Number(ui.gainLimit.value), true_peak_ceiling_dbtp:Number(ui.truePeakCeiling.value)};
  }
  let exportSettingsTimer = null, savingExportSettings = false, exportSettingsPending = false;
  async function persistExportSettings() {
    exportSettingsPending = true;
    if (savingExportSettings) return;
    savingExportSettings = true;
    try {
      while (exportSettingsPending) {
        exportSettingsPending = false;
        const settings = exportSettings();
        await request('/api/export-settings', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(settings)});
      }
    } catch (error) { toast(t('runtime.export_settings_failed', {error:error.message})); }
    finally { savingExportSettings = false; }
  }
  ui.exportMenu.addEventListener('input', event => {
    if (!event.target.matches('input')) return;
    clearTimeout(exportSettingsTimer);
    exportSettingsTimer = setTimeout(() => { try { exportSettings(); persistExportSettings(); } catch (_) {} }, 300);
  });
  ui.export.addEventListener('click', () => {
    ui.exportMenu.hidden = !ui.exportMenu.hidden;
    ui.export.setAttribute('aria-expanded', String(!ui.exportMenu.hidden));
  });
  function closeExportMenu() { ui.exportMenu.hidden = true; ui.export.setAttribute('aria-expanded', 'false'); }
  document.addEventListener('pointerdown', event => { if (!ui.export.parentElement.contains(event.target)) closeExportMenu(); });
  document.addEventListener('keydown', event => { if (event.key === 'Escape') closeExportMenu(); });
  function updateExportAvailability() {
    const unavailable = model.dirty || model.loading || model.exportRunning || !model.projects.length;
    ui.cut.disabled = unavailable; ui.exportList.disabled = unavailable; ui.exportTable.disabled = unavailable;
    ui.export.disabled = model.loading || !model.projects.length;
    ui.exportMenu.querySelectorAll('input').forEach(input => { input.disabled = model.exportRunning; });
  }
  async function startExport(mode, button) {
    if (model.exportRunning) return;
    if (model.dirty) { toast(t('runtime.save_before_export')); return; }
    try {
      const settings = mode === 'clips' ? exportSettings() : undefined;
      model.exportRunning = true; updateExportAvailability(); button.classList.add('progressing'); button.style.setProperty('--progress', '0%');
      const started = await request('/api/export', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({mode, projects:[...model.selectedProjects], selected_speakers:[...model.selectedSpeakers], selected_tags:[...model.selectedTags], clip_export:settings})});
      if (started.cancelled) { resetExportButtons(); toast(started.message || t('runtime.export_cancelled')); return; }
      pollExport(button);
    } catch (error) { resetExportButtons(); toast(error.message); }
  }
  async function pollExport(button) {
    try {
      const state = await request('/api/export'); const percent = Number(state.progress || 0); button.style.setProperty('--progress', `${percent}%`); button.textContent = state.state === 'running' ? `${percent}%` : exportButtonLabel(state.mode); ui.export.textContent = state.state === 'running' ? t('runtime.export_progress', {percent}) : t('common.export'); ui.status.textContent = state.message || '';
      if (state.state === 'running') { setTimeout(() => pollExport(button), 400); return; }
      resetExportButtons(); toast(state.message || t(state.state === 'complete' ? 'runtime.export_complete' : 'runtime.export_failed'));
    } catch (error) { resetExportButtons(); toast(error.message); }
  }
  function exportButtonLabel(mode) { return t(mode === 'table' ? 'assembly.export_table' : (mode === 'list' ? 'assembly.export_list' : 'assembly.export_clips')); }
  function resetExportButtons() { model.exportRunning = false; [ui.cut, ui.exportList, ui.exportTable].forEach(button => { button.classList.remove('progressing'); button.style.removeProperty('--progress'); }); ui.cut.textContent = t('assembly.export_clips'); ui.exportList.textContent = t('assembly.export_list'); ui.exportTable.textContent = t('assembly.export_table'); ui.export.textContent = t('common.export'); updateExportAvailability(); if (!model.dirty) ui.status.textContent = model.projects.length ? t('runtime.synced') : t('common.select_project'); }
  ui.cut.addEventListener('click', () => startExport('clips', ui.cut)); ui.exportList.addEventListener('click', () => startExport('list', ui.exportList)); ui.exportTable.addEventListener('click', () => startExport('table', ui.exportTable));
  window.addEventListener('beforeunload', event => { persistUiState(); if (model.dirty) { event.preventDefault(); event.returnValue = ''; } });
  const initialUiState = readUiState();
  const launchParameters = new URLSearchParams(location.search);
  const hasLaunchSelection = launchParameters.has('initial_project') || launchParameters.has('initial_blank');
  const launchedProjects = launchParameters.getAll('initial_project').filter(name => name);
  const initialProjects = hasLaunchSelection
    ? launchedProjects
    : (Array.isArray(initialUiState.selectedProjects) ? initialUiState.selectedProjects.filter(name => typeof name === 'string') : []);
  if (hasLaunchSelection) history.replaceState({}, '', `${location.pathname}${location.hash}`);
  setInterval(checkDatabaseChanges, 3000);
  document.addEventListener('visibilitychange', checkDatabaseChanges);
  window.addEventListener('focus', checkDatabaseChanges);
  loadState(initialProjects, false, false);
});
