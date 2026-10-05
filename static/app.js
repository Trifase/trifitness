// State
let recipes = [];
let knownIngredients = [];
let plan = { weeks: [] };
let shoppingList = {};
let mealPrep = { week1_prep: [], week2_prep: [] };

function escapeHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function escapeRegExp(str) {
  return str.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}
let weights = [];
let activities = [];
let activityPresets = [];
let stravaConfig = { client_id: '', client_secret: '', refresh_token: '', is_configured: false };
let stravaActivitiesList = [];
let parsedFileActivity = null;
let activeActivityPeriod = 'rolling7'; // Default: Ultimi 7 Giorni (include sessioni recenti senza azzerare il lunedì)
let activeWeekView = 'w1'; // Default: Settimana 1
let activeShoppingWeek = '1'; // Default: Settimana 1 (Spesa della Domenica)
let currentSlotContext = null; // { week_number, day_index, slot_name, current_recipe_id }
let currentSlotModalServings = 1;
let currentViewRecipe = null;
let currentViewServings = 1;
let currentViewSlotContext = null; // { weekNum, dayIdx, slotName, servings }

const SLOT_LABELS = {
  colazione: { label: "Colazione", icon: "☕" },
  merenda_mattina: { label: "Spuntino Matt.", icon: "🥜" },
  pranzo: { label: "Pranzo 1", icon: "🍝" },
  pranzo_2: { label: "Pranzo 2", icon: "🍝" },
  merenda_pomeriggio: { label: "Spuntino Pom.", icon: "🍎" },
  cena: { label: "Cena 1", icon: "🍽️" },
  cena_2: { label: "Cena 2", icon: "🍽️" }
};

const CATEGORY_ICONS = {
  "Ortofrutta": "🥬",
  "Macellaio sotto casa": "🥩",
  "Banco Frigo & Latticini": "🧀",
  "Banco Frigo & Latticini (Senza Lattosio)": "🧀",
  "Surgelati": "❄️",
  "Dispensa, Scatolame & Secco": "🥫",
  "Pizzeria / Forno": "🍕",
  "Altro": "📦"
};

// Initialize
document.addEventListener('DOMContentLoaded', async () => {
  setupNavigation();
  setupEventListeners();
  await loadAllData();

  const urlParams = new URLSearchParams(window.location.search);
  const requestedTab = urlParams.get('tab') || window.location.hash.replace('#', '');
  if (requestedTab && requestedTab !== 'calendar') {
    await activateTab(requestedTab);
  }

  const recipeId = urlParams.get('recipe');
  if (recipeId) {
    const targetRec = recipes.find(r => r.id === recipeId);
    if (targetRec) {
      openRecipeViewModal(targetRec);
    }
  }
});

// Load all API data
async function loadAllData() {
  try {
    const [recRes, planRes, weightRes, presetRes, ingRes] = await Promise.all([
      fetch('/api/recipes'),
      fetch('/api/plan'),
      fetch('/api/weight'),
      fetch('/api/activity-presets'),
      fetch('/api/ingredients')
    ]);
    recipes = await recRes.json();
    plan = await planRes.json();
    weights = await weightRes.json();
    activityPresets = await presetRes.json();
    if (ingRes.ok) {
      knownIngredients = await ingRes.json();
    } else {
      buildIngredientsFallback();
    }
    renderCalendar();
    renderRecipes();
    renderActivityPresets();
  } catch (err) {
    console.error("Errore caricamento dati:", err);
  }
}

function buildIngredientsFallback() {
  const map = new Map();
  recipes.forEach(r => {
    (r.ingredients || []).forEach(ing => {
      const name = (ing.name || '').trim();
      if (!name) return;
      const key = name.toLowerCase();
      if (!map.has(key)) {
        map.set(key, {
          name: name,
          unit: ing.unit || 'g',
          category: ing.category || 'Altro',
          count: 0
        });
      }
      map.get(key).count++;
    });
  });
  knownIngredients = Array.from(map.values()).sort((a, b) => b.count - a.count);
}

async function loadIngredientsData() {
  try {
    const res = await fetch('/api/ingredients');
    if (res.ok) {
      knownIngredients = await res.json();
      return;
    }
  } catch (err) {
    console.warn("Fallback ingredienti:", err);
  }
  buildIngredientsFallback();
}

// Navigation Tabs
async function activateTab(target) {
  const tabs = document.querySelectorAll('.nav-tab');
  const tab = document.querySelector(`.nav-tab[data-tab="${target}"]`);
  if (!tab) return;
  tabs.forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));

  tab.classList.add('active');
  const targetContent = document.getElementById(`tab-${target}`);
  if (targetContent) targetContent.classList.add('active');

  if (target === 'shopping') {
    await loadShoppingList(activeShoppingWeek);
  } else if (target === 'mealprep') {
    await loadMealPrep();
  } else if (target === 'weight') {
    await loadWeightData();
  } else if (target === 'activities') {
    await loadActivitiesData();
    await loadActivityPresets();
  }
}

function setupNavigation() {
  const tabs = document.querySelectorAll('.nav-tab');
  tabs.forEach(tab => {
    tab.addEventListener('click', async () => {
      await activateTab(tab.dataset.tab);
    });
  });
}

function setupEventListeners() {
  // Calendar Week View buttons
  document.getElementById('btn-view-w1').addEventListener('click', (e) => setWeekView('w1', e.target));
  document.getElementById('btn-view-w2').addEventListener('click', (e) => setWeekView('w2', e.target));
  document.getElementById('btn-view-both').addEventListener('click', (e) => setWeekView('both', e.target));

  // Copy Week 1 to Week 2
  document.getElementById('btn-copy-w1-to-w2').addEventListener('click', async () => {
    if (confirm("Vuoi duplicare tutti i pasti della Settimana 1 sulla Settimana 2?")) {
      const res = await fetch('/api/plan/copy-week', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ source_week: 1, target_week: 2 })
      });
      if (res.ok) {
        await loadAllData();
        alert("Settimana 1 copiata con successo su Settimana 2!");
      }
    }
  });

  // Shopping Week Selector buttons
  document.getElementById('btn-shop-w1').addEventListener('click', (e) => setShoppingWeek('1', e.target));
  document.getElementById('btn-shop-w2').addEventListener('click', (e) => setShoppingWeek('2', e.target));
  document.getElementById('btn-shop-both').addEventListener('click', (e) => setShoppingWeek('both', e.target));

  // Shopping List buttons
  document.getElementById('btn-copy-shopping-whatsapp').addEventListener('click', copyShoppingToWhatsApp);
  document.getElementById('btn-refresh-shopping').addEventListener('click', () => loadShoppingList(activeShoppingWeek));

  // Recipe search & filter
  document.getElementById('recipe-search').addEventListener('input', renderRecipes);
  document.querySelectorAll('.category-pills .pill').forEach(pill => {
    pill.addEventListener('click', (e) => {
      document.querySelectorAll('.category-pills .pill').forEach(p => p.classList.remove('active'));
      e.target.classList.add('active');
      renderRecipes();
    });
  });

  // Recipe View Modal (Porzioni Scalabili)
  document.getElementById('btn-close-view-recipe-modal').addEventListener('click', closeRecipeViewModal);
  document.getElementById('btn-close-view-bottom').addEventListener('click', closeRecipeViewModal);
  document.getElementById('btn-scale-minus').addEventListener('click', () => changeViewServings(-1));
  document.getElementById('btn-scale-plus').addEventListener('click', () => changeViewServings(1));
  document.getElementById('btn-open-edit-from-view').addEventListener('click', () => {
    const r = currentViewRecipe;
    closeRecipeViewModal();
    if (r) openRecipeModal(r);
  });

  // Recipe Create / Edit Modal
  document.getElementById('btn-open-new-recipe-modal').addEventListener('click', () => openRecipeModal());
  document.getElementById('btn-close-recipe-modal').addEventListener('click', closeRecipeModal);
  document.getElementById('btn-cancel-recipe').addEventListener('click', closeRecipeModal);
  document.getElementById('btn-add-ingredient-row').addEventListener('click', () => addIngredientRow());
  document.getElementById('btn-add-mealprep-step').addEventListener('click', () => addMealPrepStepRow());
  document.getElementById('recipe-is-mealprep').addEventListener('change', (e) => {
    document.getElementById('mealprep-details-fields').classList.toggle('hidden', !e.target.checked);
  });
  document.getElementById('form-recipe').addEventListener('submit', handleSaveRecipe);

  // Slot Modal
  document.getElementById('btn-close-slot-modal').addEventListener('click', closeSlotModal);
  document.getElementById('btn-clear-slot').addEventListener('click', clearCurrentSlot);
  document.getElementById('slot-modal-search').addEventListener('input', renderSlotRecipeOptions);
  document.getElementById('btn-slot-scale-minus').addEventListener('click', () => changeSlotModalServings(-1));
  document.getElementById('btn-slot-scale-plus').addEventListener('click', () => changeSlotModalServings(1));
  document.getElementById('btn-edit-slot-recipe').addEventListener('click', () => {
    if (!currentSlotContext || !currentSlotContext.currentRecipeId) return;
    const r = recipes.find(x => x.id === currentSlotContext.currentRecipeId);
    if (r) {
      closeSlotModal();
      openRecipeModal(r);
    }
  });

  // Weight Modal & Bioimpedance
  document.getElementById('btn-open-weight-modal').addEventListener('click', () => openWeightModal());
  document.getElementById('btn-close-weight-modal').addEventListener('click', closeWeightModal);
  document.getElementById('btn-cancel-weight').addEventListener('click', closeWeightModal);
  document.getElementById('btn-toggle-bioimpedance').addEventListener('click', toggleBioimpedanceFields);
  document.getElementById('form-weight').addEventListener('submit', handleSaveWeight);

  // Activities Modal
  document.getElementById('btn-open-activity-modal').addEventListener('click', () => openActivityModal());
  document.getElementById('btn-close-activity-modal').addEventListener('click', closeActivityModal);
  document.getElementById('btn-cancel-activity').addEventListener('click', closeActivityModal);
  document.getElementById('act-auto-calories').addEventListener('change', updateModalCalories);
  document.getElementById('act-duration').addEventListener('input', updateModalCalories);
  document.getElementById('act-speed').addEventListener('input', updateModalCalories);
  document.getElementById('act-distance').addEventListener('input', () => {
    document.getElementById('act-distance').dataset.auto = 'false';
  });
  document.getElementById('act-type').addEventListener('change', updateModalCalories);
  document.getElementById('form-activity').addEventListener('submit', handleSaveActivity);

  // Presets Modal
  document.getElementById('btn-open-presets-modal').addEventListener('click', openPresetsModal);
  document.getElementById('btn-close-presets-modal').addEventListener('click', closePresetsModal);
  document.getElementById('btn-cancel-presets').addEventListener('click', closePresetsModal);
  document.getElementById('btn-add-preset-row').addEventListener('click', () => addPresetEditorRow());
  document.getElementById('btn-reset-presets').addEventListener('click', resetPresetsToDefaults);
  document.getElementById('btn-save-presets').addEventListener('click', savePresetsFromEditor);

  // Import Modal
  document.getElementById('btn-open-import-modal').addEventListener('click', openImportModal);
  document.getElementById('btn-close-import-modal').addEventListener('click', closeImportModal);
  document.getElementById('btn-close-import-bottom').addEventListener('click', closeImportModal);
  document.getElementById('btn-tab-strava').addEventListener('click', () => switchImportTab('strava'));
  document.getElementById('btn-tab-file').addEventListener('click', () => switchImportTab('file'));
  document.getElementById('btn-toggle-strava-config').addEventListener('click', toggleStravaConfig);
  document.getElementById('btn-save-strava-config').addEventListener('click', handleSaveStravaConfig);
  document.getElementById('btn-fetch-strava').addEventListener('click', fetchStravaActivities);
  document.getElementById('strava-select-all').addEventListener('change', toggleStravaSelectAll);
  document.getElementById('btn-import-selected-strava').addEventListener('click', handleImportSelectedStrava);
  document.getElementById('btn-browse-file').addEventListener('click', () => document.getElementById('fitness-file-input').click());
  document.getElementById('fitness-file-input').addEventListener('change', (e) => {
    if (e.target.files && e.target.files.length) {
      handleFitnessFiles(e.target.files);
    }
    e.target.value = '';
  });
  document.getElementById('btn-save-file-activity').addEventListener('click', handleSaveFileActivity);
  document.getElementById('file-batch-select-all').addEventListener('change', toggleBatchFileSelectAll);
  document.getElementById('btn-save-batch-activities').addEventListener('click', handleSaveBatchFileActivities);
  setupFileDropzone();

  // Rename Ingredient Modal
  document.getElementById('btn-close-rename-modal').addEventListener('click', closeRenameIngredientModal);
  document.getElementById('btn-cancel-rename').addEventListener('click', closeRenameIngredientModal);
  document.getElementById('btn-confirm-rename').addEventListener('click', handleConfirmRenameIngredient);
  document.getElementById('rename-new-name').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      handleConfirmRenameIngredient();
    } else if (e.key === 'Escape') {
      closeRenameIngredientModal();
    }
  });

  // Activity Period Filter buttons
  document.querySelectorAll('#activity-period-filter button').forEach(btn => {
    btn.addEventListener('click', (e) => {
      document.querySelectorAll('#activity-period-filter button').forEach(b => b.classList.remove('active'));
      e.target.classList.add('active');
      activeActivityPeriod = e.target.dataset.period;
      renderActivitiesKPIs();
    });
  });
}

function setWeekView(view, targetBtn) {
  activeWeekView = view;
  document.querySelectorAll('.week-filter-group .btn').forEach(b => b.classList.remove('active'));
  targetBtn.classList.add('active');
  renderCalendar();
}

function setShoppingWeek(week, targetBtn) {
  activeShoppingWeek = week;
  document.querySelectorAll('.shopping-week-selector .btn').forEach(b => b.classList.remove('active'));
  targetBtn.classList.add('active');
  loadShoppingList(activeShoppingWeek);
}

// CALENDAR RENDERING (PULITO, COMPATTO, SENZA COMMENTI)
function renderCalendar() {
  const container = document.getElementById('calendar-grid');
  container.innerHTML = '';

  const recipeMap = new Map(recipes.map(r => [r.id, r]));

  plan.weeks.forEach(week => {
    if (activeWeekView === 'w1' && week.week_number !== 1) return;
    if (activeWeekView === 'w2' && week.week_number !== 2) return;

    const weekBlock = document.createElement('div');
    weekBlock.className = 'week-block';

    weekBlock.innerHTML = `
      <div class="week-title-bar">
        <h3>🗓️ ${week.title}</h3>
        <span class="badge badge-prep">${week.days.length} Giorni</span>
      </div>
      <div class="days-row">
        ${week.days.map(day => renderDayCard(week.week_number, day, recipeMap)).join('')}
      </div>
    `;

    container.appendChild(weekBlock);
  });

  // Attach slot click events (cambio ricetta nello slot)
  document.querySelectorAll('.slot-item').forEach(el => {
    el.addEventListener('click', (e) => {
      if (e.target.closest('.btn-view-recipe-slot')) return;

      const weekNum = parseInt(el.dataset.week);
      const dayIdx = parseInt(el.dataset.day);
      const slotName = el.dataset.slot;
      const currentRecipeId = el.dataset.recipeId;
      openSlotModal(weekNum, dayIdx, slotName, currentRecipeId);
    });
  });

  // Attach view recipe click events (pulsante 📖 per aprire la ricetta con porzioni scalabili)
  document.querySelectorAll('.btn-view-recipe-slot').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const recipeId = btn.dataset.recipeId;
      const weekNum = parseInt(btn.dataset.week);
      const dayIdx = parseInt(btn.dataset.day);
      const slotName = btn.dataset.slot;
      const servings = parseInt(btn.dataset.servings) || 1;

      const r = recipes.find(x => x.id === recipeId);
      if (r) {
        openRecipeViewModal(r, { weekNum, dayIdx, slotName, servings });
      }
    });
  });
}

function renderDayCard(weekNum, day, recipeMap) {
  const jsDay = new Date().getDay();
  const todayDayIndex = (jsDay === 0) ? 6 : jsDay - 1;
  const isToday = (day.day_index === todayDayIndex);

  const slotKeys = ['colazione', 'merenda_mattina', 'pranzo', 'pranzo_2', 'merenda_pomeriggio', 'cena', 'cena_2'];

  const slotsHtml = slotKeys.map(key => {
    const rId = day.slots ? day.slots[key] : null;
    const r = rId ? recipeMap.get(rId) : null;
    const info = SLOT_LABELS[key];
    const slotServings = (day.slot_servings && day.slot_servings[key]) ? day.slot_servings[key] : 1;

    let contentHtml = `<span class="slot-empty">+ Aggiungi</span>`;
    let badgesHtml = '';
    let viewIconHtml = '';

    if (r) {
      contentHtml = `<div class="slot-recipe-title" title="${r.title}">${r.title}</div>`;
      badgesHtml = `
        <div class="slot-badges">
          <span class="badge badge-time">${r.prep_time_minutes}m</span>
          ${slotServings > 1 ? `<span class="badge badge-servings" title="${slotServings} porzioni pianificate">👥 ${slotServings}</span>` : ''}
          ${r.meal_prep && r.meal_prep.is_prep ? `<span class="badge badge-prep">Prep</span>` : ''}
        </div>
      `;
      viewIconHtml = `
        <button type="button" class="btn-view-recipe-slot" 
          data-recipe-id="${rId}" 
          data-week="${weekNum}" 
          data-day="${day.day_index}" 
          data-slot="${key}" 
          data-servings="${slotServings}" 
          title="Apri ricetta (${slotServings} ${slotServings === 1 ? 'persona' : 'persone'})">
          📖
        </button>
      `;
    }

    return `
      <div class="slot-item slot-${key}" data-week="${weekNum}" data-day="${day.day_index}" data-slot="${key}" data-recipe-id="${rId || ''}">
        <div class="slot-label">
          <span>${info.icon} ${info.label}</span>
          ${viewIconHtml}
        </div>
        <div class="slot-body">
          ${contentHtml}
        </div>
        ${badgesHtml ? badgesHtml : '<div class="slot-badges-empty"></div>'}
      </div>
    `;
  }).join('');

  return `
    <div class="day-card ${isToday ? 'is-today' : ''}">
      <div class="day-header">
        <div class="day-name">
          ${day.day_name}
          ${isToday ? '<span class="today-tag">Oggi</span>' : ''}
        </div>
      </div>
      ${slotsHtml}
    </div>
  `;
}

// RECIPE VIEW MODAL WITH DYNAMIC SERVINGS SCALER
function openRecipeViewModal(recipe, slotContext = null) {
  currentViewRecipe = recipe;
  currentViewSlotContext = slotContext;
  currentViewServings = slotContext ? (slotContext.servings || 1) : (recipe.servings || 1);

  document.getElementById('view-recipe-title').textContent = recipe.title;

  // Normalize meal prep list
  const prepList = Array.isArray(recipe.meal_prep)
    ? recipe.meal_prep.filter(m => m && m.is_prep)
    : (recipe.meal_prep && recipe.meal_prep.is_prep ? [recipe.meal_prep] : []);

  const hasFreeze = prepList.some(m => m.can_freeze);

  // Badges
  const badgesContainer = document.getElementById('view-recipe-badges');
  badgesContainer.innerHTML = `
    <span class="badge badge-time">⏱️ ${recipe.prep_time_minutes} min</span>
    <span class="badge badge-time">🍽️ ${recipe.category.toUpperCase()}</span>
    ${prepList.length > 0 ? `<span class="badge badge-prep">🍳 Meal Prep (${prepList.length})</span>` : ''}
    ${hasFreeze ? `<span class="badge badge-prep">🧊 Congelabile</span>` : ''}
  `;

  const baseServings = recipe.servings || 1;
  document.getElementById('view-recipe-base-info').textContent = `Base ricetta: ${baseServings} ${baseServings === 1 ? 'porzione' : 'porzioni'}`;

  // Render scaled ingredients
  renderScaledIngredients();

  // Meal prep section
  const prepBox = document.getElementById('view-recipe-mealprep-box');
  const prepListContainer = document.getElementById('view-recipe-mealprep-list');
  if (prepList.length > 0) {
    prepBox.classList.remove('hidden');
    prepBox.style.display = 'block';
    prepListContainer.innerHTML = prepList.map(step => `
      <div class="view-prep-step-card">
        <div class="view-prep-step-title">
          <span>🍳 <strong>${step.batch_title || 'Step Preparazione'}</strong></span>
          <span class="badge badge-prep" style="font-size: 10px;">${step.can_freeze ? '🧊 Freezer OK' : '🥗 Frigo (3-4gg)'}</span>
        </div>
        <div class="view-prep-step-desc">${step.instructions || 'Nessuna istruzione inserita.'}</div>
      </div>
    `).join('');
  } else {
    prepBox.classList.add('hidden');
    prepBox.style.display = 'none';
    if (prepListContainer) prepListContainer.innerHTML = '';
  }

  // Notes section
  const notesBox = document.getElementById('view-recipe-notes-box');
  const notesText = document.getElementById('view-recipe-notes-text');
  if (recipe.notes && recipe.notes.trim()) {
    notesBox.classList.remove('hidden');
    notesBox.style.display = 'block';
    notesText.textContent = recipe.notes;
  } else {
    notesBox.classList.add('hidden');
    notesBox.style.display = 'none';
    notesText.textContent = '';
  }

  document.getElementById('modal-view-recipe').classList.remove('hidden');
}

function closeRecipeViewModal() {
  document.getElementById('modal-view-recipe').classList.add('hidden');
  const prepListContainer = document.getElementById('view-recipe-mealprep-list');
  if (prepListContainer) prepListContainer.innerHTML = '';
  document.getElementById('view-recipe-notes-text').textContent = '';
  currentViewRecipe = null;
  currentViewSlotContext = null;
}

async function changeViewServings(delta) {
  if (!currentViewRecipe) return;
  const newServings = currentViewServings + delta;
  if (newServings < 1 || newServings > 20) return;
  currentViewServings = newServings;
  renderScaledIngredients();

  if (currentViewSlotContext) {
    currentViewSlotContext.servings = currentViewServings;
    await saveSlotServings(
      currentViewSlotContext.weekNum,
      currentViewSlotContext.dayIdx,
      currentViewSlotContext.slotName,
      currentViewServings
    );
  }
}

async function saveSlotServings(weekNum, dayIdx, slotName, servings) {
  try {
    const res = await fetch('/api/plan/slot', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        week_number: weekNum,
        day_index: dayIdx,
        slot_name: slotName,
        servings: servings
      })
    });
    if (res.ok) {
      const w = plan.weeks.find(x => x.week_number === weekNum);
      if (w) {
        const d = w.days.find(x => x.day_index === dayIdx);
        if (d) {
          if (!d.slot_servings) d.slot_servings = {};
          d.slot_servings[slotName] = servings;
        }
      }
      renderCalendar();
      loadShoppingList(activeShoppingWeek);
    }
  } catch (err) {
    console.error("Errore salvataggio porzioni:", err);
  }
}

function renderScaledIngredients() {
  if (!currentViewRecipe) return;

  const countEl = document.getElementById('view-recipe-servings-count');
  countEl.textContent = `${currentViewServings} ${currentViewServings === 1 ? 'persona' : 'persone'}`;

  const list = document.getElementById('view-recipe-ingredients-list');
  list.innerHTML = '';

  const baseServings = currentViewRecipe.servings || 1;
  const multiplier = currentViewServings / baseServings;

  if (!currentViewRecipe.ingredients || currentViewRecipe.ingredients.length === 0) {
    list.innerHTML = `<li style="padding: 8px; color: #94a3b8; font-style: italic;">Nessun ingrediente specifico richiesto (es. pasto fuori casa).</li>`;
    return;
  }

  currentViewRecipe.ingredients.forEach(ing => {
    const rawScaled = ing.quantity * multiplier;
    const formattedQty = (rawScaled % 1 !== 0) ? rawScaled.toFixed(1) : Math.round(rawScaled);

    const li = document.createElement('li');
    li.className = 'view-ingredient-item';
    li.innerHTML = `
      <span><strong>${ing.name}</strong> <span style="font-size: 11px; color: #64748b;">(${ing.category})</span></span>
      <span class="ing-qty-tag">${formattedQty} ${ing.unit}</span>
    `;
    list.appendChild(li);
  });
}

// SLOT MODAL
function openSlotModal(weekNum, dayIdx, slotName, currentRecipeId) {
  currentSlotContext = { weekNum, dayIdx, slotName, currentRecipeId };
  const modal = document.getElementById('modal-select-recipe');
  const info = SLOT_LABELS[slotName];

  let dayName = "Giorno";
  const w = plan.weeks.find(x => x.week_number === weekNum);
  if (w) {
    const d = w.days.find(x => x.day_index === dayIdx);
    if (d) {
      dayName = d.day_name;
      currentSlotModalServings = (d.slot_servings && d.slot_servings[slotName]) ? d.slot_servings[slotName] : 1;
    } else {
      currentSlotModalServings = 1;
    }
  } else {
    currentSlotModalServings = 1;
  }

  const countEl = document.getElementById('slot-modal-servings-count');
  if (countEl) countEl.textContent = currentSlotModalServings;

  const btnEdit = document.getElementById('btn-edit-slot-recipe');
  if (btnEdit) {
    if (currentRecipeId) {
      btnEdit.style.display = 'inline-flex';
      const r = recipes.find(x => x.id === currentRecipeId);
      btnEdit.textContent = '✏️ Modifica Ricetta';
      btnEdit.title = r ? `Modifica "${r.title}" nel ricettario` : 'Modifica Ricetta';
    } else {
      btnEdit.style.display = 'none';
    }
  }

  document.getElementById('modal-slot-title').textContent = `${info.icon} ${info.label} (${dayName} - W${weekNum})`;
  document.getElementById('slot-modal-search').value = '';
  renderSlotRecipeOptions();
  modal.classList.remove('hidden');
}

function closeSlotModal() {
  document.getElementById('modal-select-recipe').classList.add('hidden');
  currentSlotContext = null;
}

async function changeSlotModalServings(delta) {
  const newVal = currentSlotModalServings + delta;
  if (newVal < 1 || newVal > 20) return;
  currentSlotModalServings = newVal;
  const countEl = document.getElementById('slot-modal-servings-count');
  if (countEl) countEl.textContent = currentSlotModalServings;

  if (currentSlotContext) {
    await saveSlotServings(
      currentSlotContext.weekNum,
      currentSlotContext.dayIdx,
      currentSlotContext.slotName,
      currentSlotModalServings
    );
  }
}

function renderSlotRecipeOptions() {
  const query = document.getElementById('slot-modal-search').value.toLowerCase();
  const list = document.getElementById('slot-recipes-list');
  list.innerHTML = '';

  const { slotName, currentRecipeId } = currentSlotContext;
  const baseSlot = (slotName === 'pranzo_2') ? 'pranzo' : (slotName === 'cena_2') ? 'cena' : slotName;

  const filtered = recipes.filter(r => {
    const slotMatches = (r.allowed_slots && (r.allowed_slots.includes(slotName) || r.allowed_slots.includes(baseSlot))) ||
                        r.category === slotName || r.category === baseSlot;
    const searchMatches = !query || r.title.toLowerCase().includes(query) || (r.notes && r.notes.toLowerCase().includes(query));
    return slotMatches && searchMatches;
  });

  if (filtered.length === 0) {
    list.innerHTML = `<p style="padding: 10px; color: #94a3b8; text-align: center; font-size: 12px;">Nessuna ricetta per questo slot. Cerca dal ricettario.</p>`;
    return;
  }

  filtered.forEach(r => {
    const el = document.createElement('div');
    el.className = `slot-recipe-option ${r.id === currentRecipeId ? 'selected' : ''}`;
    const sCount = r.servings || 1;
    el.innerHTML = `
      <div style="flex: 1; min-width: 0;">
        <div style="font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">${r.title}</div>
        <div style="font-size: 11px; color: #64748b;">⏱️ ${r.prep_time_minutes} min • ${(r.ingredients ? r.ingredients.length : 0)} ingr. • ${sCount} ${sCount === 1 ? 'persona' : 'persone'}</div>
      </div>
      <div style="display: flex; align-items: center; gap: 6px;">
        ${r.meal_prep && r.meal_prep.is_prep ? `<span class="badge badge-prep">Meal Prep</span>` : ''}
        <button type="button" class="btn-option-edit" data-id="${r.id}" title="Modifica questa ricetta nel ricettario">✏️</button>
      </div>
    `;
    const editBtn = el.querySelector('.btn-option-edit');
    if (editBtn) {
      editBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        closeSlotModal();
        openRecipeModal(r);
      });
    }
    el.addEventListener('click', () => selectRecipeForSlot(r.id));
    list.appendChild(el);
  });
}

async function selectRecipeForSlot(recipeId) {
  if (!currentSlotContext) return;
  const { weekNum, dayIdx, slotName } = currentSlotContext;
  const chosenServings = recipeId ? currentSlotModalServings : null;

  try {
    const res = await fetch('/api/plan/slot', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        week_number: weekNum,
        day_index: dayIdx,
        slot_name: slotName,
        recipe_id: recipeId,
        servings: chosenServings
      })
    });
    if (res.ok) {
      const w = plan.weeks.find(x => x.week_number === weekNum);
      if (w) {
        const d = w.days.find(x => x.day_index === dayIdx);
        if (d) {
          if (!d.slots) d.slots = {};
          d.slots[slotName] = recipeId;
          if (!d.slot_servings) d.slot_servings = {};
          if (recipeId) {
            d.slot_servings[slotName] = chosenServings;
          } else {
            delete d.slot_servings[slotName];
          }
        }
      }
      closeSlotModal();
      renderCalendar();
    }
  } catch (err) {
    alert("Errore salvataggio slot");
  }
}

async function clearCurrentSlot() {
  if (!currentSlotContext) return;
  await selectRecipeForSlot(null);
}

// SHOPPING LIST
async function loadShoppingList(week = activeShoppingWeek) {
  try {
    const res = await fetch(`/api/shopping-list?week=${week}`);
    shoppingList = await res.json();
    renderShoppingList();
  } catch (err) {
    console.error("Errore lista spesa:", err);
  }
}

function renderShoppingList() {
  const container = document.getElementById('shopping-categories-container');
  container.innerHTML = '';

  const checkedState = JSON.parse(localStorage.getItem('checked_shopping_items') || '{}');

  const categories = Object.keys(shoppingList);
  if (categories.length === 0) {
    container.innerHTML = `<p style="grid-column: 1/-1; text-align: center; color: #94a3b8; padding: 30px;">Nessun pasto pianificato nella settimana selezionata. Riempi gli slot nel calendario per generare la spesa.</p>`;
    return;
  }

  categories.forEach(cat => {
    const items = shoppingList[cat];
    const icon = CATEGORY_ICONS[cat] || "📦";

    const card = document.createElement('div');
    card.className = 'category-card';

    const itemsHtml = items.map((item) => {
      const itemKey = `${activeShoppingWeek}__${cat}__${item.name}`;
      const isChecked = checkedState[itemKey] || false;

      // Link cliccabili per ciascuna ricetta (aprono la Recipe View Modal)
      const recipeLinks = item.recipes.map(recipeTitle => {
        const rObj = recipes.find(r => r.title === recipeTitle);
        const rId = rObj ? rObj.id : '';
        return `<span class="recipe-link-badge" data-recipe-id="${rId}" title="Clicca per aprire la ricetta con dosi">${recipeTitle}</span>`;
      }).join(', ');

      return `
        <li class="shopping-item-row ${isChecked ? 'checked' : ''}" data-key="${itemKey}">
          <input type="checkbox" ${isChecked ? 'checked' : ''} class="shopping-checkbox">
          <div class="shopping-item-name">
            <div class="shopping-item-header">
              <span class="shopping-item-title">${escapeHtml(item.name)}</span>
              <button type="button" class="btn-rename-ingredient" data-name="${escapeHtml(item.name)}" title="Rinomina '${escapeHtml(item.name)}' in tutte le ricette">✏️</button>
            </div>
            <div class="shopping-item-usages">Usato in: ${recipeLinks} (${item.occurrences}x)</div>
          </div>
          <div class="shopping-item-qty">${item.quantity} ${item.unit}</div>
        </li>
      `;
    }).join('');

    card.innerHTML = `
      <div class="category-card-header">
        <span>${icon} ${cat}</span>
        <span class="badge badge-time">${items.length} articoli</span>
      </div>
      <ul class="category-items-list">
        ${itemsHtml}
      </ul>
    `;

    container.appendChild(card);
  });

  // Checkbox interactions
  document.querySelectorAll('.shopping-checkbox').forEach(cb => {
    cb.addEventListener('change', (e) => {
      const row = e.target.closest('.shopping-item-row');
      const key = row.dataset.key;
      const checked = e.target.checked;
      row.classList.toggle('checked', checked);

      const state = JSON.parse(localStorage.getItem('checked_shopping_items') || '{}');
      state[key] = checked;
      localStorage.setItem('checked_shopping_items', JSON.stringify(state));
    });
  });

  // Rename ingredient buttons click -> open rename modal
  document.querySelectorAll('.btn-rename-ingredient').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const ingName = btn.dataset.name;
      openRenameIngredientModal(ingName);
    });
  });

  // Recipe link badges click -> open recipe view modal
  document.querySelectorAll('.recipe-link-badge').forEach(badge => {
    badge.addEventListener('click', (e) => {
      e.stopPropagation();
      const rId = badge.dataset.recipeId;
      const r = recipes.find(x => x.id === rId);
      if (r) {
        openRecipeViewModal(r);
      }
    });
  });
}

// RENAME INGREDIENT ACROSS ALL RECIPES
function openRenameIngredientModal(oldName) {
  const modal = document.getElementById('modal-rename-ingredient');
  document.getElementById('rename-old-name').value = oldName;
  const newNameInput = document.getElementById('rename-new-name');
  newNameInput.value = oldName;
  modal.classList.remove('hidden');
  setTimeout(() => {
    newNameInput.focus();
    newNameInput.select();
  }, 50);
}

function closeRenameIngredientModal() {
  document.getElementById('modal-rename-ingredient').classList.add('hidden');
}

async function handleConfirmRenameIngredient() {
  const oldName = document.getElementById('rename-old-name').value.trim();
  const newName = document.getElementById('rename-new-name').value.trim();

  if (!newName) {
    alert("Inserisci un nuovo nome per l'ingrediente!");
    return;
  }

  if (oldName.toLowerCase() === newName.toLowerCase() && oldName === newName) {
    closeRenameIngredientModal();
    return;
  }

  try {
    const res = await fetch('/api/ingredients/rename', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ old_name: oldName, new_name: newName })
    });

    const data = await res.json();
    if (!res.ok) {
      alert("Errore durante la ridenominazione: " + (data.detail || "Errore sconosciuto"));
      return;
    }

    closeRenameIngredientModal();

    // Reload all data so recipes, ingredients, calendar, and shopping list are kept in sync
    await loadAllData();
    await loadShoppingList(activeShoppingWeek);

    alert(`✅ Ingrediente "${oldName}" rinominato in "${newName}" in ${data.updated_recipes_count} ricett${data.updated_recipes_count === 1 ? 'a' : 'e'}!`);
  } catch (err) {
    console.error("Errore ridenominazione:", err);
    alert("Errore di rete durante la ridenominazione.");
  }
}

function copyShoppingToWhatsApp() {
  const weekLabel = activeShoppingWeek === 'both' ? 'PER 2 SETTIMANE' : `SETTIMANALE (Settimana ${activeShoppingWeek})`;
  let text = `🛒 *LISTA DELLA SPESA ${weekLabel} (Pianificazione Famiglia)*\n`;
  text += `_Spesa domenicale calcolata dal nostro piano pasti_\n\n`;

  for (const [cat, items] of Object.entries(shoppingList)) {
    const icon = CATEGORY_ICONS[cat] || "📦";
    text += `*${icon} ${cat.toUpperCase()}*\n`;
    items.forEach(item => {
      text += `• ${item.name}: *${item.quantity} ${item.unit}*\n`;
    });
    text += "\n";
  }

  text += "🥑 _Piano Pasti & Nutrizione Sana • Fatto Insieme!_";

  navigator.clipboard.writeText(text).then(() => {
    alert("✅ Lista della spesa copiata negli appunti! Ora puoi incollarla su WhatsApp.");
  }).catch(() => {
    prompt("Copia manualmente il testo per WhatsApp:", text);
  });
}

// RECIPES TAB
function renderRecipes() {
  const container = document.getElementById('recipes-grid');
  container.innerHTML = '';

  const query = document.getElementById('recipe-search').value.toLowerCase();
  const activePill = document.querySelector('.category-pills .pill.active').dataset.cat;

  const filtered = recipes.filter(r => {
    const matchesSearch = !query || r.title.toLowerCase().includes(query) ||
      r.ingredients.some(i => i.name.toLowerCase().includes(query));

    let matchesCat = true;
    if (activePill === 'meal_prep') {
      matchesCat = r.meal_prep && r.meal_prep.is_prep;
    } else if (activePill !== 'all') {
      matchesCat = r.category === activePill;
    }

    return matchesSearch && matchesCat;
  });

  filtered.forEach(r => {
    const card = document.createElement('div');
    card.className = 'recipe-card';

    const ingredientsHtml = (r.ingredients && r.ingredients.length > 0)
      ? r.ingredients.map(i => `<li><strong>${i.name}:</strong> ${i.quantity} ${i.unit}</li>`).join('')
      : '<li style="color: #94a3b8; font-style: italic;">Nessun ingrediente specifico (es. pasto libero o fuori casa)</li>';

    card.innerHTML = `
      <div class="recipe-card-content" data-id="${r.id}" style="cursor: pointer;">
        <div class="recipe-card-header">
          <div class="recipe-card-title">${r.title}</div>
        </div>
        <div class="recipe-card-badges">
          <span class="badge badge-time">⏱️ ${r.prep_time_minutes} min</span>
          <span class="badge badge-time">👥 ${r.servings || 1} ${(r.servings || 1) === 1 ? 'Persona' : 'Persone'} (Scalabile)</span>
          ${r.meal_prep && r.meal_prep.is_prep ? `<span class="badge badge-prep">🍳 Meal Prep</span>` : ''}
          ${r.meal_prep && r.meal_prep.can_freeze ? `<span class="badge badge-prep">🧊 Congelabile</span>` : ''}
        </div>

        <div class="recipe-ingredients-preview">
          <strong>Ingredienti (base ${r.servings || 1} ${(r.servings || 1) === 1 ? 'porzione' : 'porzioni'}):</strong>
          <ul>${ingredientsHtml}</ul>
        </div>

        ${r.meal_prep && r.meal_prep.is_prep ? `
          <div class="recipe-prep-info">
            <strong>🍳 Meal Prep (${r.meal_prep.prep_day}):</strong> ${r.meal_prep.instructions}
          </div>
        ` : ''}

        ${r.notes ? `<div class="recipe-notes">💡 ${r.notes}</div>` : ''}
      </div>

      <div class="recipe-actions">
        <button class="btn btn-sm btn-primary btn-view-recipe" data-id="${r.id}">🔍 Dosi & Porzioni</button>
        <button class="btn btn-sm btn-outline btn-edit-recipe" data-id="${r.id}">✏️ Modifica</button>
        <button class="btn btn-sm btn-outline text-danger btn-delete-recipe" data-id="${r.id}">🗑️ Elimina</button>
      </div>
    `;

    container.appendChild(card);
  });

  // Click on card body or "Dosi & Porzioni" button -> opens Recipe View Modal
  document.querySelectorAll('.recipe-card-content, .btn-view-recipe').forEach(el => {
    el.addEventListener('click', (e) => {
      e.stopPropagation();
      const id = el.dataset.id;
      const r = recipes.find(x => x.id === id);
      if (r) openRecipeViewModal(r);
    });
  });

  document.querySelectorAll('.btn-edit-recipe').forEach(b => {
    b.addEventListener('click', (e) => {
      e.stopPropagation();
      const id = b.dataset.id;
      const r = recipes.find(x => x.id === id);
      if (r) openRecipeModal(r);
    });
  });

  document.querySelectorAll('.btn-delete-recipe').forEach(b => {
    b.addEventListener('click', async (e) => {
      e.stopPropagation();
      const id = b.dataset.id;
      if (confirm("Vuoi davvero eliminare questa ricetta?")) {
        await fetch(`/api/recipes/${id}`, { method: 'DELETE' });
        await loadAllData();
      }
    });
  });
}

// RECIPE MODAL (CREATE / EDIT)
function openRecipeModal(recipe = null) {
  const modal = document.getElementById('modal-edit-recipe');
  const titleEl = document.getElementById('recipe-modal-title');
  const ingredientsList = document.getElementById('ingredients-form-list');
  const prepStepsList = document.getElementById('mealprep-steps-list');
  ingredientsList.innerHTML = '';
  if (prepStepsList) prepStepsList.innerHTML = '';

  if (recipe) {
    titleEl.textContent = "Modifica Ricetta";
    document.getElementById('edit-recipe-id').value = recipe.id;
    document.getElementById('recipe-title').value = recipe.title;
    document.getElementById('recipe-category').value = recipe.category;
    document.getElementById('recipe-servings').value = recipe.servings || 1;
    document.getElementById('recipe-prep-time').value = recipe.prep_time_minutes;
    document.getElementById('recipe-notes').value = recipe.notes || '';

    // Allowed slots
    document.querySelectorAll('input[name="allowed_slots"]').forEach(cb => {
      cb.checked = recipe.allowed_slots && recipe.allowed_slots.includes(cb.value);
    });

    // Meal prep
    const prepList = Array.isArray(recipe.meal_prep)
      ? recipe.meal_prep.filter(m => m && m.is_prep)
      : (recipe.meal_prep && recipe.meal_prep.is_prep ? [recipe.meal_prep] : []);

    const isPrep = prepList.length > 0;
    document.getElementById('recipe-is-mealprep').checked = isPrep;
    document.getElementById('mealprep-details-fields').classList.toggle('hidden', !isPrep);

    if (isPrep) {
      prepList.forEach(step => addMealPrepStepRow(step));
    } else {
      addMealPrepStepRow();
    }

    // Ingredients
    recipe.ingredients.forEach(ing => addIngredientRow(ing));
  } else {
    titleEl.textContent = "Nuova Ricetta";
    document.getElementById('edit-recipe-id').value = '';
    document.getElementById('recipe-title').value = '';
    document.getElementById('recipe-category').value = 'pranzo';
    document.getElementById('recipe-servings').value = '1';
    document.getElementById('recipe-prep-time').value = '8';
    document.getElementById('recipe-notes').value = '';

    document.querySelectorAll('input[name="allowed_slots"]').forEach(cb => {
      cb.checked = cb.value === 'pranzo' || cb.value === 'cena';
    });

    document.getElementById('recipe-is-mealprep').checked = false;
    document.getElementById('mealprep-details-fields').classList.add('hidden');
    addMealPrepStepRow();

    // Add 2 empty ingredient rows
    addIngredientRow();
    addIngredientRow();
  }

  modal.classList.remove('hidden');
}

function closeRecipeModal() {
  document.getElementById('modal-edit-recipe').classList.add('hidden');
}

function addMealPrepStepRow(data = null) {
  const container = document.getElementById('mealprep-steps-list');
  if (!container) return;

  const card = document.createElement('div');
  card.className = 'mealprep-step-card';

  const defaultTitle = data && data.batch_title ? data.batch_title : '';
  const defaultInst = data && data.instructions ? data.instructions : '';
  const defaultFreeze = data ? (data.can_freeze !== false) : true;

  card.innerHTML = `
    <button type="button" class="btn btn-sm btn-outline text-danger btn-remove-step" title="Rimuovi step">&times;</button>
    <div class="form-group" style="margin-bottom: 6px; margin-right: 32px;">
      <label style="font-size: 11px; font-weight: 600;">Titolo Step / Ingrediente da preparare</label>
      <input type="text" class="form-input prep-step-title" placeholder="Es. Lessatura Riso Venere, Ragù Magro..." value="${defaultTitle}">
    </div>
    <div class="form-group" style="margin-bottom: 6px;">
      <label style="font-size: 11px; font-weight: 600;">Istruzioni Preparazione Anticipata</label>
      <textarea class="form-input prep-step-instructions" rows="2" placeholder="Come cucinare la base domenica, raffreddare o conservare...">${defaultInst}</textarea>
    </div>
    <label class="checkbox-inline" style="font-size: 11px;">
      <input type="checkbox" class="prep-step-freeze" ${defaultFreeze ? 'checked' : ''}>
      <span>Può essere congelato in freezer per le settimane successive</span>
    </label>
  `;

  card.querySelector('.btn-remove-step').addEventListener('click', () => {
    const totalSteps = container.querySelectorAll('.mealprep-step-card').length;
    if (totalSteps > 1) {
      card.remove();
    } else {
      card.querySelector('.prep-step-title').value = '';
      card.querySelector('.prep-step-instructions').value = '';
      card.querySelector('.prep-step-freeze').checked = true;
    }
  });

  container.appendChild(card);
}

function addIngredientRow(data = null) {
  const list = document.getElementById('ingredients-form-list');
  const row = document.createElement('div');
  row.className = 'ingredient-row';

  const categories = [
    "Ortofrutta",
    "Macellaio sotto casa",
    "Banco Frigo & Latticini",
    "Surgelati",
    "Dispensa, Scatolame & Secco",
    "Pizzeria / Forno",
    "Altro"
  ];

  let currentCat = data ? data.category : "Ortofrutta";
  if (currentCat.includes("Senza Lattosio")) {
    currentCat = "Banco Frigo & Latticini";
  }

  const catOptions = categories.map(c =>
    `<option value="${c}" ${currentCat === c ? 'selected' : ''}>${c}</option>`
  ).join('');

  row.innerHTML = `
    <div class="ing-name-wrapper">
      <input type="text" placeholder="Ingrediente (es. Pasta...)" class="form-input ing-name" value="${data ? data.name : ''}" autocomplete="off">
      <div class="ing-suggestions-dropdown hidden"></div>
    </div>
    <input type="number" step="any" placeholder="Qtà" class="form-input ing-qty" value="${data ? data.quantity : ''}">
    <input type="text" placeholder="Unità" class="form-input ing-unit" value="${data ? data.unit : 'g'}">
    <select class="form-input ing-cat">${catOptions}</select>
    <button type="button" class="btn btn-sm btn-outline text-danger btn-remove-ing">&times;</button>
  `;

  const nameInput = row.querySelector('.ing-name');
  const qtyInput = row.querySelector('.ing-qty');
  const unitInput = row.querySelector('.ing-unit');
  const catSelect = row.querySelector('.ing-cat');
  const dropdown = row.querySelector('.ing-suggestions-dropdown');

  let activeIndex = -1;

  function renderSuggestions(query) {
    if (!query) {
      dropdown.classList.add('hidden');
      dropdown.innerHTML = '';
      activeIndex = -1;
      return;
    }

    const q = query.toLowerCase();
    const matches = knownIngredients.filter(item => item.name.toLowerCase().includes(q)).slice(0, 8);

    if (matches.length === 0) {
      dropdown.innerHTML = `<div class="suggestion-item suggestion-new">➕ Nuovo ingrediente: "<strong>${escapeHtml(query)}</strong>"</div>`;
      dropdown.classList.remove('hidden');
      activeIndex = -1;
      return;
    }

    activeIndex = -1;
    dropdown.innerHTML = matches.map((item, idx) => {
      const icon = CATEGORY_ICONS[item.category] || '📦';
      const reg = new RegExp(`(${escapeRegExp(query)})`, 'gi');
      const highlightedName = item.name.replace(reg, '<b>$1</b>');

      return `
        <div class="suggestion-item" data-index="${idx}">
          <div class="suggestion-name">${highlightedName}</div>
          <div class="suggestion-meta">
            <span class="suggestion-cat">${icon} ${item.category}</span>
            <span class="suggestion-unit">${item.unit}</span>
          </div>
        </div>
      `;
    }).join('');

    dropdown.classList.remove('hidden');

    dropdown.querySelectorAll('.suggestion-item').forEach((itemEl, idx) => {
      itemEl.addEventListener('mousedown', (e) => {
        e.preventDefault();
        selectItem(matches[idx]);
      });
    });
  }

  function selectItem(item) {
    nameInput.value = item.name;
    if (item.unit) unitInput.value = item.unit;
    if (item.category) {
      let cat = item.category;
      if (cat.includes("Senza Lattosio")) cat = "Banco Frigo & Latticini";
      catSelect.value = cat;
    }
    dropdown.classList.add('hidden');
    dropdown.innerHTML = '';
    activeIndex = -1;
    qtyInput.focus();
  }

  nameInput.addEventListener('input', (e) => {
    renderSuggestions(e.target.value.trim());
  });

  nameInput.addEventListener('focus', () => {
    if (nameInput.value.trim().length >= 2) {
      renderSuggestions(nameInput.value.trim());
    }
  });

  nameInput.addEventListener('blur', () => {
    setTimeout(() => {
      dropdown.classList.add('hidden');
    }, 180);

    const val = nameInput.value.trim().toLowerCase();
    if (val) {
      const exact = knownIngredients.find(x => x.name.toLowerCase() === val);
      if (exact) {
        nameInput.value = exact.name;
        if (exact.unit) unitInput.value = exact.unit;
        if (exact.category) {
          let cat = exact.category;
          if (cat.includes("Senza Lattosio")) cat = "Banco Frigo & Latticini";
          catSelect.value = cat;
        }
      }
    }
  });

  nameInput.addEventListener('keydown', (e) => {
    const items = dropdown.querySelectorAll('.suggestion-item:not(.suggestion-new)');
    if (dropdown.classList.contains('hidden') || items.length === 0) return;

    if (e.key === 'ArrowDown') {
      e.preventDefault();
      activeIndex = (activeIndex + 1) % items.length;
      updateActiveItem(items);
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      activeIndex = (activeIndex - 1 + items.length) % items.length;
      updateActiveItem(items);
    } else if (e.key === 'Enter') {
      if (activeIndex >= 0 && activeIndex < items.length) {
        e.preventDefault();
        const q = nameInput.value.trim().toLowerCase();
        const matches = knownIngredients.filter(item => item.name.toLowerCase().includes(q)).slice(0, 8);
        if (matches[activeIndex]) {
          selectItem(matches[activeIndex]);
        }
      }
    } else if (e.key === 'Escape') {
      dropdown.classList.add('hidden');
    }
  });

  function updateActiveItem(items) {
    items.forEach((el, i) => {
      el.classList.toggle('active', i === activeIndex);
      if (i === activeIndex) el.scrollIntoView({ block: 'nearest' });
    });
  }

  row.querySelector('.btn-remove-ing').addEventListener('click', () => row.remove());
  list.appendChild(row);
}

async function handleSaveRecipe(e) {
  e.preventDefault();

  const id = document.getElementById('edit-recipe-id').value;
  const title = document.getElementById('recipe-title').value;
  const category = document.getElementById('recipe-category').value;
  const servings = parseInt(document.getElementById('recipe-servings').value) || 1;
  const prepTime = parseInt(document.getElementById('recipe-prep-time').value) || 5;
  const notes = document.getElementById('recipe-notes').value;

  const allowedSlots = Array.from(document.querySelectorAll('input[name="allowed_slots"]:checked')).map(cb => cb.value);

  // Ingredients
  const rows = document.querySelectorAll('.ingredient-row');
  const ingredients = [];
  rows.forEach(r => {
    const name = r.querySelector('.ing-name').value.trim();
    const qty = parseFloat(r.querySelector('.ing-qty').value) || 1;
    const unit = r.querySelector('.ing-unit').value.trim() || 'g';
    let cat = r.querySelector('.ing-cat').value;
    if (cat.includes("Senza Lattosio")) {
      cat = "Banco Frigo & Latticini";
    }
    if (name) {
      ingredients.push({ name, quantity: qty, unit, category: cat });
    }
  });

  if (ingredients.length === 0) {
    const proceed = confirm("Attenzione: nessun ingrediente inserito per questa ricetta.\n\nVuoi salvarla comunque (es. pasto libero o fuori casa)?");
    if (!proceed) {
      return;
    }
  }

  // Meal prep (multiple steps)
  const isPrep = document.getElementById('recipe-is-mealprep').checked;
  let mealPrepInfo = null;
  if (isPrep) {
    const stepCards = document.querySelectorAll('.mealprep-step-card');
    const steps = [];
    stepCards.forEach(c => {
      const bTitle = c.querySelector('.prep-step-title').value.trim();
      const bInst = c.querySelector('.prep-step-instructions').value.trim();
      const bFreeze = c.querySelector('.prep-step-freeze').checked;
      if (bTitle || bInst) {
        steps.push({
          is_prep: true,
          prep_day: "Domenica",
          batch_title: bTitle || title,
          instructions: bInst,
          can_freeze: bFreeze
        });
      }
    });
    if (steps.length === 1) {
      mealPrepInfo = steps[0];
    } else if (steps.length > 1) {
      mealPrepInfo = steps;
    }
  }

  const recipePayload = {
    title,
    category,
    allowed_slots: allowedSlots,
    servings,
    prep_time_minutes: prepTime,
    ingredients,
    meal_prep: mealPrepInfo,
    notes
  };

  try {
    let res;
    if (id) {
      res = await fetch(`/api/recipes/${id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(recipePayload)
      });
    } else {
      res = await fetch('/api/recipes', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(recipePayload)
      });
    }

    if (res.ok) {
      closeRecipeModal();
      await loadAllData();
    } else {
      alert("Errore salvataggio ricetta");
    }
  } catch (err) {
    alert("Errore di rete");
  }
}

// MEAL PREP TAB
async function loadMealPrep() {
  try {
    const res = await fetch('/api/meal-prep');
    mealPrep = await res.json();
    renderMealPrep();
  } catch (err) {
    console.error("Errore meal prep:", err);
  }
}

function renderMealPrep() {
  const w1List = document.getElementById('mealprep-w1-list');
  const w2List = document.getElementById('mealprep-w2-list');

  w1List.innerHTML = renderPrepTasks(mealPrep.week1_prep, 'w1');
  w2List.innerHTML = renderPrepTasks(mealPrep.week2_prep, 'w2');

  // Checkbox listener
  document.querySelectorAll('.prep-checkbox').forEach(cb => {
    cb.addEventListener('change', (e) => {
      const card = e.target.closest('.prep-item-card');
      const key = card.dataset.key;
      const checked = e.target.checked;
      card.style.opacity = checked ? '0.5' : '1';

      const state = JSON.parse(localStorage.getItem('checked_prep_items') || '{}');
      state[key] = checked;
      localStorage.setItem('checked_prep_items', JSON.stringify(state));
    });
  });
}

function renderPrepTasks(tasks, weekKey) {
  if (!tasks || tasks.length === 0) {
    return `<p style="color: #94a3b8; font-style: italic; padding: 8px; font-size: 11.5px;">Nessuna preparazione richiesta per questa settimana.</p>`;
  }

  const prepState = JSON.parse(localStorage.getItem('checked_prep_items') || '{}');

  return tasks.map((t) => {
    const key = `${weekKey}__${t.batch_title}`;
    const isChecked = prepState[key] || false;

    return `
      <div class="prep-item-card" data-key="${key}" style="${isChecked ? 'opacity: 0.5;' : ''}">
        <div class="prep-item-title">
          <label style="display: flex; align-items: center; gap: 6px; cursor: pointer;">
            <input type="checkbox" class="prep-checkbox" ${isChecked ? 'checked' : ''}>
            <span>${t.batch_title}</span>
          </label>
          ${t.can_freeze ? `<span class="badge badge-prep">🧊 Freezer OK</span>` : ''}
        </div>
        <div class="prep-item-desc">${t.instructions}</div>
        <div class="prep-item-needed">Necessario per: <strong>${t.needed_for.join(', ')}</strong></div>
      </div>
    `;
  }).join('');
}

/* ==========================================================================
   WEIGHT & BIOIMPEDANCE TRACKING LOGIC
   ========================================================================== */

async function loadWeightData() {
  try {
    const res = await fetch('/api/weight');
    weights = await res.json();
    weights.sort((a, b) => new Date(a.date) - new Date(b.date));

    computeMovingAverages();
    renderWeightKPIs();
    renderWeightChart();
    renderWeightTable();
  } catch (err) {
    console.error("Errore caricamento dati peso:", err);
  }
}

function computeMovingAverages() {
  for (let i = 0; i < weights.length; i++) {
    const currentDate = new Date(weights[i].date + 'T00:00:00');
    const windowEntries = weights.filter(w => {
      const d = new Date(w.date + 'T00:00:00');
      const diffDays = (currentDate - d) / (1000 * 60 * 60 * 24);
      return diffDays >= 0 && diffDays <= 6;
    });

    const sum = windowEntries.reduce((acc, curr) => acc + curr.weight, 0);
    weights[i].movingAvg = sum / windowEntries.length;
  }
}

function renderWeightKPIs() {
  const kpiCurrent = document.getElementById('kpi-current-weight');
  const kpiDelta = document.getElementById('kpi-weight-delta');
  const kpiMA = document.getElementById('kpi-moving-avg');
  const kpiLossRate = document.getElementById('kpi-loss-rate');
  const kpiLossSub = document.getElementById('kpi-loss-sub');
  const kpiBodyComp = document.getElementById('kpi-body-comp');
  const kpiBodyCompSub = document.getElementById('kpi-body-comp-sub');
  const countBadge = document.getElementById('weight-history-count');

  if (countBadge) countBadge.textContent = `${weights.length} registrazioni`;

  if (!weights || weights.length === 0) {
    if (kpiCurrent) kpiCurrent.textContent = "-- kg";
    if (kpiDelta) kpiDelta.textContent = "Nessuna misurazione";
    if (kpiMA) kpiMA.textContent = "-- kg";
    if (kpiLossRate) kpiLossRate.textContent = "-- kg/sett.";
    if (kpiBodyComp) kpiBodyComp.textContent = "-- cm";
    return;
  }

  const latest = weights[weights.length - 1];
  const first = weights[0];

  if (kpiCurrent) kpiCurrent.textContent = `${latest.weight.toFixed(1)} kg`;

  if (kpiDelta) {
    if (weights.length > 1) {
      const totalDelta = latest.weight - first.weight;
      const sign = totalDelta > 0 ? "+" : "";
      kpiDelta.innerHTML = `<span class="${totalDelta <= 0 ? 'delta-down' : 'delta-up'}">${sign}${totalDelta.toFixed(1)} kg</span> da inizio (${formatDateDisplay(first.date)})`;
    } else {
      kpiDelta.textContent = "Valore iniziale di base";
    }
  }

  if (kpiMA) {
    kpiMA.textContent = latest.movingAvg ? `${latest.movingAvg.toFixed(1)} kg` : `${latest.weight.toFixed(1)} kg`;
  }

  // Loss Rate Estimation (kg / week)
  if (kpiLossRate && kpiLossSub) {
    if (weights.length >= 2) {
      const dFirst = new Date(first.date + 'T00:00:00');
      const dLast = new Date(latest.date + 'T00:00:00');
      const daysDiff = (dLast - dFirst) / (1000 * 60 * 60 * 24);

      if (daysDiff >= 1) {
        const deltaWeight = latest.weight - first.weight;
        const ratePerWeek = (deltaWeight / daysDiff) * 7;
        const sign = ratePerWeek > 0 ? "+" : "";
        kpiLossRate.textContent = `${sign}${ratePerWeek.toFixed(2)} kg/sett.`;

        if (ratePerWeek <= -0.4 && ratePerWeek >= -1.1) {
          kpiLossSub.textContent = "Target ideale (0.5 - 1.0 kg/sett.) ✨";
          kpiLossSub.className = "metric-sub text-success";
        } else if (ratePerWeek < -1.1) {
          kpiLossSub.textContent = "Calo rapido (proteggi la massa magra)";
          kpiLossSub.className = "metric-sub text-warning";
        } else if (ratePerWeek > 0) {
          kpiLossSub.textContent = "Leggero incremento o ritenzione";
          kpiLossSub.className = "metric-sub text-muted";
        } else {
          kpiLossSub.textContent = "Stabile / ritmo iniziale costante";
          kpiLossSub.className = "metric-sub text-muted";
        }
      } else {
        kpiLossRate.textContent = "-- kg/sett.";
        kpiLossSub.textContent = "Inserisci pesate in giorni differenti";
      }
    } else {
      kpiLossRate.textContent = "-- kg/sett.";
      kpiLossSub.textContent = "Serve almeno una seconda pesata";
    }
  }

  // Body Composition KPI
  if (kpiBodyComp && kpiBodyCompSub) {
    let compParts = [];
    if (latest.body_fat) compParts.push(`Grasso: ${latest.body_fat}%`);
    if (latest.visceral_fat) compParts.push(`Visc: ${latest.visceral_fat}`);
    if (latest.muscle) compParts.push(`Muscolo: ${latest.muscle}kg`);

    if (latest.waist) {
      kpiBodyComp.textContent = `${latest.waist} cm`;
      kpiBodyCompSub.textContent = compParts.length > 0 ? compParts.join(' • ') : "Girovita rilevato";
    } else if (latest.body_fat) {
      kpiBodyComp.textContent = `${latest.body_fat}%`;
      kpiBodyCompSub.textContent = compParts.length > 0 ? compParts.join(' • ') : "Massa grassa stimata";
    } else {
      kpiBodyComp.textContent = "-- cm";
      kpiBodyCompSub.textContent = "Nessun dato di circonferenza";
    }
  }
}

function renderWeightChart() {
  const container = document.getElementById('weight-chart-container');
  if (!container) return;

  if (!weights || weights.length === 0) {
    container.innerHTML = `<p style="text-align: center; color: #94a3b8; padding: 60px 0; font-size: 13px;">Nessun dato registrato. Clicca su '+ Registra Peso' per visualizzare il grafico.</p>`;
    return;
  }

  const width = 720;
  const height = 240;
  const padLeft = 45;
  const padRight = 30;
  const padTop = 20;
  const padBottom = 35;
  const plotWidth = width - padLeft - padRight;
  const plotHeight = height - padTop - padBottom;

  const allValues = [];
  weights.forEach(w => {
    allValues.push(w.weight);
    if (w.movingAvg) allValues.push(w.movingAvg);
  });

  let minVal = Math.min(...allValues);
  let maxVal = Math.max(...allValues);

  const range = maxVal - minVal;
  const buffer = range > 2 ? range * 0.15 : 1.5;
  minVal = Math.floor(minVal - buffer);
  maxVal = Math.ceil(maxVal + buffer);
  if (maxVal <= minVal) maxVal = minVal + 3;

  const getY = (val) => padTop + (1 - (val - minVal) / (maxVal - minVal)) * plotHeight;
  const getX = (idx) => {
    if (weights.length === 1) return padLeft + plotWidth / 2;
    return padLeft + (idx / (weights.length - 1)) * plotWidth;
  };

  // Horizontal Grid Lines & Y labels
  const steps = 4;
  let gridLines = '';
  for (let s = 0; s <= steps; s++) {
    const yVal = minVal + (s / steps) * (maxVal - minVal);
    const yPos = getY(yVal);
    gridLines += `
      <line x1="${padLeft}" y1="${yPos}" x2="${width - padRight}" y2="${yPos}" stroke="#f1f5f9" stroke-width="1" />
      <text x="${padLeft - 8}" y="${yPos + 4}" font-size="10" fill="#94a3b8" text-anchor="end">${yVal.toFixed(1)}</text>
    `;
  }

  // Weight Points & Moving Avg Lines
  let weightPoints = [];
  let avgPoints = [];
  let dots = '';
  let xLabels = '';

  const labelStep = Math.max(1, Math.ceil(weights.length / 8));

  weights.forEach((w, i) => {
    const x = getX(i);
    const yW = getY(w.weight);
    weightPoints.push(`${x},${yW}`);

    if (w.movingAvg) {
      const yAvg = getY(w.movingAvg);
      avgPoints.push(`${x},${yAvg}`);
    }

    const tooltip = `${formatDateDisplay(w.date)}: ${w.weight.toFixed(1)} kg${w.movingAvg ? ' (MA: ' + w.movingAvg.toFixed(1) + ')' : ''}${w.waist ? ' • Girovita: ' + w.waist + ' cm' : ''}`;
    dots += `
      <circle cx="${x}" cy="${yW}" r="4" fill="#2563eb" stroke="#ffffff" stroke-width="1.5">
        <title>${tooltip}</title>
      </circle>
    `;

    if (i % labelStep === 0 || i === weights.length - 1) {
      const dateParts = w.date.split('-');
      const shortDate = `${dateParts[2]}/${dateParts[1]}`;
      xLabels += `<text x="${x}" y="${height - 10}" font-size="10.5" fill="#64748b" text-anchor="middle">${shortDate}</text>`;
    }
  });

  const weightPolyline = weightPoints.length > 1
    ? `<polyline points="${weightPoints.join(' ')}" fill="none" stroke="#93c5fd" stroke-width="1.5" stroke-dasharray="3 3" />`
    : '';

  const avgPolyline = avgPoints.length > 1
    ? `<polyline points="${avgPoints.join(' ')}" fill="none" stroke="#10b981" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" />`
    : '';

  const svg = `
    <svg viewBox="0 0 ${width} ${height}" class="chart-svg" xmlns="http://www.w3.org/2000/svg">
      ${gridLines}
      ${weightPolyline}
      ${avgPolyline}
      ${dots}
      ${xLabels}
    </svg>
  `;

  container.innerHTML = svg;
}

function renderWeightTable() {
  const tbody = document.getElementById('weight-history-tbody');
  if (!tbody) return;

  if (!weights || weights.length === 0) {
    tbody.innerHTML = `<tr><td colspan="10" style="text-align: center; color: #94a3b8; padding: 24px;">Nessuna misurazione presente.</td></tr>`;
    return;
  }

  const sorted = [...weights].reverse();

  tbody.innerHTML = sorted.map((entry) => {
    const origIdx = weights.findIndex(w => w.id === entry.id);
    let deltaHtml = `<span class="delta-eq">-</span>`;
    if (origIdx > 0) {
      const prev = weights[origIdx - 1];
      const delta = entry.weight - prev.weight;
      if (delta < 0) {
        deltaHtml = `<span class="delta-down">${delta.toFixed(1)} kg</span>`;
      } else if (delta > 0) {
        deltaHtml = `<span class="delta-up">+${delta.toFixed(1)} kg</span>`;
      } else {
        deltaHtml = `<span class="delta-eq">0.0 kg</span>`;
      }
    }

    return `
      <tr>
        <td><strong>${formatDateDisplay(entry.date)}</strong></td>
        <td><strong style="color: var(--primary);">${entry.weight.toFixed(1)} kg</strong></td>
        <td>${deltaHtml}</td>
        <td>${entry.movingAvg ? entry.movingAvg.toFixed(1) + ' kg' : '-'}</td>
        <td>${entry.body_fat ? entry.body_fat.toFixed(1) + '%' : '-'}</td>
        <td>${entry.muscle ? entry.muscle.toFixed(1) + ' kg' : '-'}</td>
        <td>${entry.visceral_fat ? entry.visceral_fat : '-'}</td>
        <td>${entry.waist ? entry.waist + ' cm' : '-'}</td>
        <td style="color: var(--text-muted); font-size: 11px; max-width: 180px; overflow: hidden; text-overflow: ellipsis;">${entry.notes || '-'}</td>
        <td style="text-align: right; white-space: nowrap;">
          <button class="btn btn-sm btn-outline btn-edit-weight" data-id="${entry.id}" title="Modifica misurazione">✏️</button>
          <button class="btn btn-sm btn-outline text-danger btn-del-weight" data-id="${entry.id}" title="Elimina misurazione">🗑️</button>
        </td>
      </tr>
    `;
  }).join('');

  document.querySelectorAll('.btn-edit-weight').forEach(btn => {
    btn.addEventListener('click', (e) => {
      const id = e.currentTarget.dataset.id;
      const entry = weights.find(w => w.id === id);
      if (entry) openWeightModal(entry);
    });
  });

  document.querySelectorAll('.btn-del-weight').forEach(btn => {
    btn.addEventListener('click', async (e) => {
      const id = e.currentTarget.dataset.id;
      if (confirm("Vuoi davvero eliminare questa misurazione del peso?")) {
        const res = await fetch(`/api/weight/${id}`, { method: 'DELETE' });
        if (res.ok) {
          await loadWeightData();
        }
      }
    });
  });
}

function openWeightModal(entry = null) {
  const modal = document.getElementById('modal-add-weight');
  const titleEl = document.getElementById('weight-modal-title');
  if (titleEl) {
    titleEl.textContent = entry ? "✏️ Modifica Misurazione Peso" : "⚖️ Registra Misurazione Peso";
  }

  document.getElementById('edit-weight-id').value = entry ? entry.id : '';
  document.getElementById('weight-date').value = entry ? entry.date : new Date().toISOString().split('T')[0];
  document.getElementById('weight-val').value = entry ? entry.weight : '';
  document.getElementById('weight-body-fat').value = entry && entry.body_fat ? entry.body_fat : '';
  document.getElementById('weight-muscle').value = entry && entry.muscle ? entry.muscle : '';
  document.getElementById('weight-visceral').value = entry && entry.visceral_fat ? entry.visceral_fat : '';
  document.getElementById('weight-water').value = entry && entry.water ? entry.water : '';
  document.getElementById('weight-waist').value = entry && entry.waist ? entry.waist : '';
  document.getElementById('weight-hips').value = entry && entry.hips ? entry.hips : '';
  document.getElementById('weight-notes').value = entry && entry.notes ? entry.notes : '';

  const hasBio = entry && (entry.body_fat || entry.muscle || entry.visceral_fat || entry.waist);
  const bioFields = document.getElementById('bioimpedance-fields');
  const arrow = document.getElementById('arrow-bioimpedance');
  if (hasBio) {
    bioFields.classList.remove('hidden');
    arrow.classList.add('open');
  } else {
    bioFields.classList.add('hidden');
    arrow.classList.remove('open');
  }

  modal.classList.remove('hidden');
  document.getElementById('weight-val').focus();
}

function closeWeightModal() {
  document.getElementById('modal-add-weight').classList.add('hidden');
}

function toggleBioimpedanceFields() {
  const fields = document.getElementById('bioimpedance-fields');
  const arrow = document.getElementById('arrow-bioimpedance');
  fields.classList.toggle('hidden');
  arrow.classList.toggle('open');
}

async function handleSaveWeight(e) {
  e.preventDefault();
  const id = document.getElementById('edit-weight-id').value;
  const date = document.getElementById('weight-date').value;
  const weightVal = parseFloat(document.getElementById('weight-val').value);

  const getNumOrNull = (id) => {
    const val = document.getElementById(id).value;
    return val !== '' ? parseFloat(val) : null;
  };

  const payload = {
    id: id || undefined,
    date: date,
    weight: weightVal,
    body_fat: getNumOrNull('weight-body-fat'),
    muscle: getNumOrNull('weight-muscle'),
    visceral_fat: getNumOrNull('weight-visceral'),
    water: getNumOrNull('weight-water'),
    waist: getNumOrNull('weight-waist'),
    hips: getNumOrNull('weight-hips'),
    notes: document.getElementById('weight-notes').value.trim()
  };

  try {
    const res = await fetch('/api/weight', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    if (res.ok) {
      closeWeightModal();
      await loadWeightData();
    } else {
      const err = await res.json();
      alert(`Errore: ${err.detail || 'Impossibile salvare la misurazione'}`);
    }
  } catch (err) {
    console.error("Errore salvataggio peso:", err);
  }
}

/* ==========================================================================
   PHYSICAL ACTIVITIES & TREADMILL TRACKING LOGIC
   ========================================================================== */

async function loadActivitiesData() {
  try {
    const res = await fetch('/api/activities');
    activities = await res.json();
    renderActivitiesKPIs();
    renderActivitiesList();
  } catch (err) {
    console.error("Errore caricamento attività:", err);
  }
}

function calculateEstimatedCalories(durationMinutes, speedKmh) {
  const userWeight = (weights && weights.length > 0) ? weights[weights.length - 1].weight : 105.0;
  const durationHours = (parseFloat(durationMinutes) || 0) / 60;
  const speed = parseFloat(speedKmh) || 4.0;
  const cals = durationHours * speed * userWeight * 0.75;
  return Math.round(cals * 10) / 10;
}

function updateModalCalories() {
  const autoChecked = document.getElementById('act-auto-calories').checked;
  const calInput = document.getElementById('act-calories');
  const distInput = document.getElementById('act-distance');
  const dur = parseFloat(document.getElementById('act-duration').value) || 0;
  const spd = parseFloat(document.getElementById('act-speed').value) || 0;

  if (distInput && (distInput.dataset.auto !== 'false' || !distInput.value)) {
    const calcDist = ((dur / 60) * spd).toFixed(2);
    distInput.value = calcDist;
    distInput.dataset.auto = 'true';
  }

  if (autoChecked) {
    const est = calculateEstimatedCalories(dur, spd);
    calInput.value = est;
    calInput.setAttribute('readonly', 'true');
    calInput.style.backgroundColor = '#f1f5f9';
  } else {
    calInput.removeAttribute('readonly');
    calInput.style.backgroundColor = '#ffffff';
  }
}

function renderActivitiesKPIs() {
  const kpiMinutes = document.getElementById('kpi-act-minutes');
  const kpiCalories = document.getElementById('kpi-act-calories');
  const kpiSessions = document.getElementById('kpi-act-sessions');
  const kpiAvgSpeed = document.getElementById('kpi-act-avg-speed');
  const kpiStatus = document.getElementById('kpi-act-status');
  const progressFill = document.getElementById('act-progress-fill');
  const progressText = document.getElementById('act-progress-text');
  const countBadge = document.getElementById('activities-history-count');

  if (countBadge) countBadge.textContent = `${activities.length} sessioni`;

  const now = new Date();
  let start = new Date(now);
  let end = new Date(now);
  let labelPeriod = "Ultimi 7gg";
  let targetDesc = "target OMS 7gg";

  if (activeActivityPeriod === 'rolling7') {
    start.setDate(now.getDate() - 6);
    start.setHours(0, 0, 0, 0);
    end.setHours(23, 59, 59, 999);
    labelPeriod = "Ultimi 7gg";
    targetDesc = "target OMS 7gg";
  } else if (activeActivityPeriod === 'this_week') {
    const dayOfWeek = (now.getDay() + 6) % 7; // Monday = 0
    start.setDate(now.getDate() - dayOfWeek);
    start.setHours(0, 0, 0, 0);
    end = new Date(start);
    end.setDate(start.getDate() + 6);
    end.setHours(23, 59, 59, 999);
    labelPeriod = "Questa Settimana";
    targetDesc = "target settimanale";
  } else if (activeActivityPeriod === 'last_week') {
    const dayOfWeek = (now.getDay() + 6) % 7;
    const thisMonday = new Date(now);
    thisMonday.setDate(now.getDate() - dayOfWeek);
    thisMonday.setHours(0, 0, 0, 0);
    start = new Date(thisMonday);
    start.setDate(thisMonday.getDate() - 7);
    start.setHours(0, 0, 0, 0);
    end = new Date(start);
    end.setDate(start.getDate() + 6);
    end.setHours(23, 59, 59, 999);
    labelPeriod = "Settimana Scorsa";
    targetDesc = "target sett. scorsa";
  } else if (activeActivityPeriod === 'all') {
    start = new Date(0);
    end = new Date(8640000000000000);
    labelPeriod = "Tutte";
    targetDesc = "totale cumulativo";
  }

  const lblMin = document.getElementById('lbl-act-minutes');
  const lblCal = document.getElementById('lbl-act-calories');
  if (lblMin) lblMin.textContent = `Minuti (${labelPeriod})`;
  if (lblCal) lblCal.textContent = `Calorie (${labelPeriod})`;

  const filteredActs = activities.filter(a => {
    if (!a.date) return false;
    const cleanDateStr = a.date.includes('T') ? a.date : `${a.date}T12:00:00`;
    const d = new Date(cleanDateStr);
    return d >= start && d <= end;
  });

  const totalMin = filteredActs.reduce((sum, a) => sum + (parseFloat(a.duration_minutes) || 0), 0);
  const totalCal = filteredActs.reduce((sum, a) => sum + (parseFloat(a.calories) || 0), 0);
  const totalKm = filteredActs.reduce((sum, a) => {
    const d = a.distance_km != null
      ? parseFloat(a.distance_km)
      : ((parseFloat(a.duration_minutes) || 0) / 60) * (parseFloat(a.speed_kmh) || 0);
    return sum + (isNaN(d) ? 0 : d);
  }, 0);
  const sessionCount = filteredActs.length;

  let totalSpeedWeighted = 0;
  filteredActs.forEach(a => {
    totalSpeedWeighted += (parseFloat(a.speed_kmh) || 4.0) * (parseFloat(a.duration_minutes) || 0);
  });
  const avgSpeed = totalMin > 0 ? (totalSpeedWeighted / totalMin) : 0;

  if (kpiMinutes) kpiMinutes.textContent = `${(totalMin % 1 === 0) ? totalMin : totalMin.toFixed(1)} min`;
  if (kpiCalories) kpiCalories.textContent = `${Math.round(totalCal)} kcal`;
  if (kpiSessions) kpiSessions.textContent = `${sessionCount} sessioni`;
  if (kpiAvgSpeed) kpiAvgSpeed.textContent = sessionCount > 0 ? `Distanza: ${totalKm.toFixed(2)} km • Media: ${avgSpeed.toFixed(1)} km/h` : "Distanza: 0.00 km • Media: -- km/h";

  const targetMin = 150;
  const pct = Math.min(100, Math.round((totalMin / targetMin) * 100));
  if (progressFill) progressFill.style.width = `${pct}%`;
  if (progressText) progressText.textContent = `${Math.round(totalMin)} / ${targetMin} min (${pct}% ${targetDesc})`;

  if (kpiStatus) {
    if (totalMin >= 150) {
      kpiStatus.textContent = "Obiettivo Raggiunto! 🏆";
      kpiStatus.className = "metric-value text-accent";
    } else if (totalMin >= 90) {
      kpiStatus.textContent = "Ottimo Ritmo! 💪";
      kpiStatus.className = "metric-value text-accent";
    } else if (totalMin >= 30) {
      kpiStatus.textContent = "Buon Inizio 🔥";
      kpiStatus.className = "metric-value text-accent";
    } else {
      kpiStatus.textContent = sessionCount > 0 ? "Movimento Avviato ⚡" : "Nessuna Attività 💤";
      kpiStatus.className = "metric-value";
    }
  }
}

function renderActivitiesList() {
  const listContainer = document.getElementById('activities-history-list');
  if (!listContainer) return;

  if (!activities || activities.length === 0) {
    listContainer.innerHTML = `<p style="color: #94a3b8; font-style: italic; padding: 24px; text-align: center; font-size: 12px;">Nessuna attività registrata. Clicca sui preset rapidi sopra o su '+ Nuova Attività'.</p>`;
    return;
  }

  const typeIcons = {
    walking_pad: "🚶",
    outdoor_walking: "🌲",
    cyclette: "🚴",
    other: "⚡"
  };

  const typeNames = {
    walking_pad: "Walking Pad (Tapis)",
    outdoor_walking: "Camminata Aperto",
    cyclette: "Cyclette",
    other: "Attività"
  };

  listContainer.innerHTML = activities.map(act => {
    const icon = typeIcons[act.activity_type] || "🚶";
    const typeLabel = typeNames[act.activity_type] || act.activity_type;
    const title = act.description || typeLabel;
    const dt = new Date(act.date);
    const dateFormatted = !isNaN(dt.getTime())
      ? `${formatDateDisplay(act.date.split('T')[0])} ${act.date.includes('T') ? act.date.split('T')[1].substring(0, 5) : ''}`
      : act.date;

    let distVal = null;
    if (act.distance_km != null) {
      distVal = parseFloat(act.distance_km).toFixed(2);
    } else if (act.duration_minutes && act.speed_kmh) {
      distVal = ((parseFloat(act.duration_minutes) / 60) * parseFloat(act.speed_kmh)).toFixed(2);
    }

    return `
      <div class="activity-card">
        <div class="act-left">
          <div class="act-icon">${icon}</div>
          <div class="act-info">
            <span class="act-title">${title}</span>
            <div class="act-meta">
              <span>📅 ${dateFormatted}</span>
              <span>•</span>
              <span class="badge badge-prep">${typeLabel}</span>
              ${act.avg_hr ? `<span class="badge badge-hr">❤️ ${Math.round(act.avg_hr)} bpm</span>` : ''}
              ${act.strava_id ? `<span class="badge" style="background: #ffedd5; color: #ea580c; border: 1px solid #fed7aa; font-size: 10px;">Strava ⚡</span>` : ''}
              ${act.notes ? `<span>• <em>${act.notes}</em></span>` : ''}
            </div>
          </div>
        </div>
        <div class="act-right">
          <div class="act-stat">
            <div class="act-stat-val">⏱️ ${(parseFloat(act.duration_minutes) % 1 === 0) ? act.duration_minutes : parseFloat(act.duration_minutes).toFixed(1)} min</div>
            <div class="act-stat-sub">${distVal ? '📍 ' + distVal + ' km • ' : ''}💨 ${act.speed_kmh ? act.speed_kmh + ' km/h' : '-'}</div>
          </div>
          <div class="act-stat">
            <div class="act-stat-val" style="color: var(--accent);">🔥 ${Math.round(act.calories || 0)} kcal</div>
            <div class="act-stat-sub">${act.auto_calories ? 'Auto' : 'Manuale'}</div>
          </div>
          <div style="display: flex; gap: 4px;">
            <button class="btn btn-sm btn-outline btn-edit-act" data-id="${act.id}" title="Modifica attività">✏️</button>
            <button class="btn btn-sm btn-outline text-danger btn-del-act" data-id="${act.id}" title="Elimina attività">🗑️</button>
          </div>
        </div>
      </div>
    `;
  }).join('');

  document.querySelectorAll('.btn-edit-act').forEach(btn => {
    btn.addEventListener('click', (e) => {
      const id = e.currentTarget.dataset.id;
      const act = activities.find(a => a.id === id);
      if (act) openActivityModal(act);
    });
  });

  document.querySelectorAll('.btn-del-act').forEach(btn => {
    btn.addEventListener('click', async (e) => {
      const id = e.currentTarget.dataset.id;
      if (confirm("Vuoi davvero eliminare questa attività?")) {
        const res = await fetch(`/api/activities/${id}`, { method: 'DELETE' });
        if (res.ok) {
          await loadActivitiesData();
        }
      }
    });
  });
}

function openActivityModal(entryOrPreset = null) {
  const modal = document.getElementById('modal-add-activity');
  const titleEl = document.getElementById('activity-modal-title');

  const isEdit = entryOrPreset && entryOrPreset.id && entryOrPreset.id.startsWith('act_');
  if (titleEl) {
    titleEl.textContent = isEdit ? "✏️ Modifica Attività Fisica" : "🏃 Registra Attività Fisica";
  }

  document.getElementById('edit-activity-id').value = isEdit ? entryOrPreset.id : '';

  if (entryOrPreset && entryOrPreset.date) {
    document.getElementById('act-datetime').value = entryOrPreset.date.length === 16 ? entryOrPreset.date : entryOrPreset.date.substring(0, 16);
  } else {
    const now = new Date();
    const year = now.getFullYear();
    const month = String(now.getMonth() + 1).padStart(2, '0');
    const day = String(now.getDate()).padStart(2, '0');
    const hours = String(now.getHours()).padStart(2, '0');
    const minutes = String(now.getMinutes()).padStart(2, '0');
    document.getElementById('act-datetime').value = `${year}-${month}-${day}T${hours}:${minutes}`;
  }

  const dur = entryOrPreset && (entryOrPreset.duration_minutes || entryOrPreset.duration) ? (entryOrPreset.duration_minutes || entryOrPreset.duration) : 20;
  const spd = entryOrPreset && (entryOrPreset.speed_kmh || entryOrPreset.speed) ? (entryOrPreset.speed_kmh || entryOrPreset.speed) : 4.0;
  document.getElementById('act-type').value = entryOrPreset && (entryOrPreset.activity_type || entryOrPreset.type) ? (entryOrPreset.activity_type || entryOrPreset.type) : 'walking_pad';
  document.getElementById('act-duration').value = dur;
  document.getElementById('act-speed').value = spd;

  const distInput = document.getElementById('act-distance');
  if (entryOrPreset && (entryOrPreset.distance_km != null || entryOrPreset.distance != null)) {
    distInput.value = entryOrPreset.distance_km != null ? entryOrPreset.distance_km : entryOrPreset.distance;
    distInput.dataset.auto = 'false';
  } else {
    distInput.value = ((dur / 60) * spd).toFixed(2);
    distInput.dataset.auto = 'true';
  }

  document.getElementById('act-description').value = entryOrPreset && entryOrPreset.description ? entryOrPreset.description : '';
  document.getElementById('act-notes').value = entryOrPreset && entryOrPreset.notes ? entryOrPreset.notes : '';

  const autoCal = entryOrPreset && entryOrPreset.auto_calories !== undefined ? entryOrPreset.auto_calories : true;
  document.getElementById('act-auto-calories').checked = autoCal;
  if (!autoCal && entryOrPreset && entryOrPreset.calories) {
    document.getElementById('act-calories').value = Math.round(entryOrPreset.calories);
  }

  updateModalCalories();
  modal.classList.remove('hidden');
}

function closeActivityModal() {
  document.getElementById('modal-add-activity').classList.add('hidden');
}

async function handleSaveActivity(e) {
  e.preventDefault();
  const id = document.getElementById('edit-activity-id').value;
  const datetime = document.getElementById('act-datetime').value;
  const actType = document.getElementById('act-type').value;
  const duration = parseFloat(document.getElementById('act-duration').value);
  const speed = parseFloat(document.getElementById('act-speed').value) || 4.0;
  const distVal = document.getElementById('act-distance').value !== '' ? parseFloat(document.getElementById('act-distance').value) : null;
  const autoCals = document.getElementById('act-auto-calories').checked;
  const calories = parseFloat(document.getElementById('act-calories').value) || 0;
  const desc = document.getElementById('act-description').value.trim();
  const notes = document.getElementById('act-notes').value.trim();

  const payload = {
    id: id || undefined,
    date: datetime,
    activity_type: actType,
    description: desc,
    duration_minutes: duration,
    distance_km: distVal,
    speed_kmh: speed,
    calories: calories,
    auto_calories: autoCals,
    notes: notes
  };

  try {
    const res = await fetch('/api/activities', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    if (res.ok) {
      closeActivityModal();
      await loadActivitiesData();
    } else {
      const err = await res.json();
      alert(`Errore: ${err.detail || 'Impossibile salvare l\'attività'}`);
    }
  } catch (err) {
    console.error("Errore salvataggio attività:", err);
  }
}

// ACTIVITY PRESETS LOGIC
async function loadActivityPresets() {
  try {
    const res = await fetch('/api/activity-presets');
    activityPresets = await res.json();
    renderActivityPresets();
  } catch (err) {
    console.error("Errore caricamento preset attività:", err);
  }
}

function renderActivityPresets() {
  const container = document.getElementById('quick-presets-container');
  if (!container) return;

  if (!activityPresets || activityPresets.length === 0) {
    container.innerHTML = `<span class="text-muted" style="font-size: 11.5px; font-style: italic;">Nessun preset configurato. Clicca su 'Modifica Preset'.</span>`;
    return;
  }

  container.innerHTML = activityPresets.map(p => `
    <button type="button" class="btn btn-outline btn-preset" data-id="${p.id}" title="${p.description || p.label}">
      ${p.label}
    </button>
  `).join('');

  container.querySelectorAll('.btn-preset').forEach(btn => {
    btn.addEventListener('click', () => {
      const id = btn.dataset.id;
      const preset = activityPresets.find(p => p.id === id);
      if (preset) {
        openActivityModal(preset);
      }
    });
  });
}

function openPresetsModal() {
  const modal = document.getElementById('modal-edit-presets');
  renderPresetEditorRows();
  modal.classList.remove('hidden');
}

function closePresetsModal() {
  document.getElementById('modal-edit-presets').classList.add('hidden');
}

function renderPresetEditorRows() {
  const list = document.getElementById('presets-editor-list');
  if (!list) return;
  list.innerHTML = '';
  activityPresets.forEach((p, idx) => addPresetEditorRow(p, idx));
}

function addPresetEditorRow(preset = null, idx = 0) {
  const list = document.getElementById('presets-editor-list');
  const row = document.createElement('div');
  row.className = 'preset-editor-row';

  const label = preset ? preset.label : '⚡ Nuovo Preset';
  const type = preset ? preset.type : 'walking_pad';
  const duration = preset ? preset.duration : 20;
  const speed = preset ? preset.speed : 4.0;
  const distance = preset && preset.distance ? preset.distance : '';
  const description = preset ? preset.description : '';
  const id = preset ? preset.id : `preset_custom_${Date.now()}_${idx}`;

  row.dataset.id = id;
  row.innerHTML = `
    <div style="flex: 2; min-width: 170px;">
      <label style="font-size: 10.5px; font-weight: 600; display: block; margin-bottom: 2px;">Etichetta Pulsante</label>
      <input type="text" class="form-input p-label" value="${label}" required placeholder="Es. 🚶 20m @ 4.0 km/h">
    </div>
    <div style="flex: 1.5; min-width: 130px;">
      <label style="font-size: 10.5px; font-weight: 600; display: block; margin-bottom: 2px;">Tipo Attività</label>
      <select class="form-input p-type">
        <option value="walking_pad" ${type === 'walking_pad' ? 'selected' : ''}>🚶 Walking Pad</option>
        <option value="outdoor_walking" ${type === 'outdoor_walking' ? 'selected' : ''}>🌲 All'Aperto</option>
        <option value="cyclette" ${type === 'cyclette' ? 'selected' : ''}>🚴 Cyclette</option>
        <option value="other" ${type === 'other' ? 'selected' : ''}>⚡ Altro</option>
      </select>
    </div>
    <div style="width: 75px;">
      <label style="font-size: 10.5px; font-weight: 600; display: block; margin-bottom: 2px;">Minuti</label>
      <input type="number" class="form-input p-duration" value="${duration}" step="0.1" min="0.1" max="300" required>
    </div>
    <div style="width: 75px;">
      <label style="font-size: 10.5px; font-weight: 600; display: block; margin-bottom: 2px;">km/h</label>
      <input type="number" class="form-input p-speed" value="${speed}" step="0.1" min="0.5" max="30">
    </div>
    <div style="width: 80px;">
      <label style="font-size: 10.5px; font-weight: 600; display: block; margin-bottom: 2px;">Distanza</label>
      <input type="number" class="form-input p-distance" value="${distance}" step="0.01" placeholder="Auto">
    </div>
    <div style="flex: 2; min-width: 150px;">
      <label style="font-size: 10.5px; font-weight: 600; display: block; margin-bottom: 2px;">Descrizione / Obiettivo</label>
      <input type="text" class="form-input p-desc" value="${description}" placeholder="Es. Pad post-pranzo">
    </div>
    <div style="align-self: flex-end; padding-bottom: 2px;">
      <button type="button" class="btn btn-sm btn-outline text-danger btn-remove-preset" title="Elimina preset">&times;</button>
    </div>
  `;

  row.querySelector('.btn-remove-preset').addEventListener('click', () => row.remove());
  list.appendChild(row);
}

async function savePresetsFromEditor() {
  const rows = document.querySelectorAll('.preset-editor-row');
  const newPresets = [];
  rows.forEach((r, i) => {
    const label = r.querySelector('.p-label').value.trim();
    const type = r.querySelector('.p-type').value;
    const duration = parseFloat(r.querySelector('.p-duration').value) || 20;
    const speed = parseFloat(r.querySelector('.p-speed').value) || 4.0;
    const distVal = r.querySelector('.p-distance').value !== '' ? parseFloat(r.querySelector('.p-distance').value) : null;
    const description = r.querySelector('.p-desc').value.trim();
    const id = r.dataset.id || `preset_${Date.now()}_${i}`;

    if (label) {
      newPresets.push({
        id,
        label,
        type,
        duration,
        speed,
        distance: distVal,
        description
      });
    }
  });

  if (newPresets.length === 0) {
    alert("Inserisci almeno un preset!");
    return;
  }

  try {
    const res = await fetch('/api/activity-presets', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(newPresets)
    });
    if (res.ok) {
      activityPresets = await res.json();
      renderActivityPresets();
      closePresetsModal();
    } else {
      alert("Errore salvataggio preset.");
    }
  } catch (err) {
    console.error("Errore salvataggio preset:", err);
    alert("Errore di rete.");
  }
}

async function resetPresetsToDefaults() {
  if (confirm("Vuoi ripristinare i preset predefiniti consigliati?")) {
    const defaultList = [
      {
        id: "preset_postpranzo",
        label: "🚶 15 min @ 3.5 km/h (Post-Pranzo)",
        type: "walking_pad",
        duration: 15,
        speed: 3.5,
        distance: 0.88,
        description: "Pad Post-Pranzo (sensibilità insulinica)"
      },
      {
        id: "preset_stacco",
        label: "🚶 20 min @ 4.0 km/h (Stacco Serale)",
        type: "walking_pad",
        duration: 20,
        speed: 4.0,
        distance: 1.33,
        description: "Pad Decompressione (fine giornata)"
      },
      {
        id: "preset_lunga",
        label: "🚶 30 min @ 4.0 km/h (Sessione Lunga)",
        type: "walking_pad",
        duration: 30,
        speed: 4.0,
        distance: 2.0,
        description: "Sessione Lunga Walking Pad"
      },
      {
        id: "preset_outdoor",
        label: "🌲 45 min @ 4.5 km/h (Camminata Aperto)",
        type: "outdoor_walking",
        duration: 45,
        speed: 4.5,
        distance: 3.38,
        description: "Camminata aerobica all'aperto"
      }
    ];

    try {
      const res = await fetch('/api/activity-presets', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(defaultList)
      });
      if (res.ok) {
        activityPresets = await res.json();
        renderPresetEditorRows();
        renderActivityPresets();
      }
    } catch (e) {
      console.error(e);
    }
  }
}

// STRAVA & FILE IMPORT LOGIC
function openImportModal() {
  const modal = document.getElementById('modal-import-activities');
  switchImportTab('strava');
  loadStravaConfig();
  modal.classList.remove('hidden');
}

function closeImportModal() {
  document.getElementById('modal-import-activities').classList.add('hidden');
}

function switchImportTab(tab) {
  const btnStrava = document.getElementById('btn-tab-strava');
  const btnFile = document.getElementById('btn-tab-file');
  const tabStrava = document.getElementById('import-subtab-strava');
  const tabFile = document.getElementById('import-subtab-file');

  if (tab === 'strava') {
    btnStrava.classList.add('active');
    btnFile.classList.remove('active');
    tabStrava.classList.remove('hidden');
    tabFile.classList.add('hidden');
  } else {
    btnFile.classList.add('active');
    btnStrava.classList.remove('active');
    tabFile.classList.remove('hidden');
    tabStrava.classList.add('hidden');
  }
}

async function loadStravaConfig() {
  try {
    const res = await fetch('/api/strava/config');
    stravaConfig = await res.json();
    const badge = document.getElementById('strava-config-badge');
    const form = document.getElementById('strava-config-form');

    if (stravaConfig.is_configured) {
      badge.textContent = "✅ Configurato";
      badge.className = "badge badge-prep";
      badge.style.background = "#ecfdf5";
      badge.style.color = "#047857";
      form.classList.add('hidden');
    } else {
      badge.textContent = "⚠️ Non configurato";
      badge.className = "badge badge-prep";
      badge.style.background = "#fffbeb";
      badge.style.color = "#b45309";
      form.classList.remove('hidden');
    }

    document.getElementById('strava-client-id').value = stravaConfig.client_id || '';
    document.getElementById('strava-client-secret').value = stravaConfig.client_secret || '';
    document.getElementById('strava-refresh-token').value = stravaConfig.refresh_token || '';
  } catch (err) {
    console.error("Errore caricamento config Strava:", err);
  }
}

function toggleStravaConfig() {
  const form = document.getElementById('strava-config-form');
  form.classList.toggle('hidden');
}

async function handleSaveStravaConfig() {
  const clientId = document.getElementById('strava-client-id').value.trim();
  const clientSecret = document.getElementById('strava-client-secret').value.trim();
  const refreshToken = document.getElementById('strava-refresh-token').value.trim();

  try {
    const res = await fetch('/api/strava/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        client_id: clientId,
        client_secret: clientSecret,
        refresh_token: refreshToken
      })
    });
    if (res.ok) {
      alert("Credenziali Strava salvate!");
      await loadStravaConfig();
    } else {
      alert("Errore salvataggio credenziali Strava");
    }
  } catch (err) {
    console.error("Errore salvataggio config Strava:", err);
  }
}

async function fetchStravaActivities() {
  const statusEl = document.getElementById('strava-fetch-status');
  const tbody = document.getElementById('strava-activities-tbody');
  const importBtn = document.getElementById('btn-import-selected-strava');

  statusEl.textContent = "⏳ Connessione a Strava in corso...";
  statusEl.style.color = "var(--primary)";

  try {
    const res = await fetch('/api/strava/activities');
    if (!res.ok) {
      const err = await res.json();
      statusEl.textContent = `❌ ${err.detail || 'Errore recupero attività'}`;
      statusEl.style.color = "var(--danger)";
      tbody.innerHTML = `<tr><td colspan="9" style="text-align: center; color: var(--danger); padding: 24px;">${err.detail || 'Errore connessione a Strava. Verifica le credenziali.'}</td></tr>`;
      return;
    }

    stravaActivitiesList = await res.json();
    statusEl.textContent = `✅ Trovate ${stravaActivitiesList.length} attività recenti`;
    statusEl.style.color = "var(--accent)";

    if (stravaActivitiesList.length === 0) {
      tbody.innerHTML = `<tr><td colspan="9" style="text-align: center; color: var(--text-muted); padding: 24px;">Nessuna attività trovata su Strava.</td></tr>`;
      importBtn.disabled = true;
      return;
    }

    tbody.innerHTML = stravaActivitiesList.map((act, idx) => {
      const dtParts = act.date.split('T');
      const dateDisp = `${formatDateDisplay(dtParts[0])} ${dtParts[1] ? dtParts[1].substring(0, 5) : ''}`;
      const isImported = act.is_imported;

      return `
        <tr style="${isImported ? 'opacity: 0.6; background: #f8fafc;' : ''}">
          <td style="text-align: center;">
            <input type="checkbox" class="strava-row-chk" data-idx="${idx}" ${isImported ? 'disabled' : 'checked'}>
          </td>
          <td><strong>${dateDisp}</strong></td>
          <td style="font-weight: 500;">${act.description}</td>
          <td>
            <select class="form-input strava-type-sel" data-idx="${idx}" style="font-size: 11px; padding: 2px 4px; height: 26px;" ${isImported ? 'disabled' : ''}>
              <option value="walking_pad" ${act.activity_type === 'walking_pad' ? 'selected' : ''}>🚶 Tapis</option>
              <option value="outdoor_walking" ${act.activity_type === 'outdoor_walking' ? 'selected' : ''}>🌲 Aperto</option>
              <option value="cyclette" ${act.activity_type === 'cyclette' ? 'selected' : ''}>🚴 Cyclette</option>
              <option value="other" ${act.activity_type === 'other' ? 'selected' : ''}>⚡ Altro</option>
            </select>
          </td>
          <td>${act.duration_minutes} min</td>
          <td>${act.distance_km ? act.distance_km.toFixed(2) + ' km' : '-'}</td>
          <td>${act.avg_hr ? `<span class="badge badge-hr">❤️ ${Math.round(act.avg_hr)} bpm</span>` : '-'}</td>
          <td>${act.calories ? Math.round(act.calories) + ' kcal' : '-'}</td>
          <td>
            ${isImported ? `<span class="badge badge-prep" style="background: #e2e8f0; color: #475569;">✅ Già presente</span>` : `<span class="badge badge-prep" style="background: #ecfdf5; color: #047857;">Pronta</span>`}
          </td>
        </tr>
      `;
    }).join('');

    updateStravaImportBtn();

    document.querySelectorAll('.strava-row-chk').forEach(chk => {
      chk.addEventListener('change', updateStravaImportBtn);
    });

    document.querySelectorAll('.strava-type-sel').forEach(sel => {
      sel.addEventListener('change', (e) => {
        const idx = parseInt(e.target.dataset.idx);
        if (stravaActivitiesList[idx]) {
          stravaActivitiesList[idx].activity_type = e.target.value;
        }
      });
    });

  } catch (err) {
    console.error("Errore fetch Strava:", err);
    statusEl.textContent = "❌ Errore durante la richiesta a Strava";
    statusEl.style.color = "var(--danger)";
  }
}

function toggleStravaSelectAll(e) {
  const checked = e.target.checked;
  document.querySelectorAll('.strava-row-chk:not(:disabled)').forEach(chk => {
    chk.checked = checked;
  });
  updateStravaImportBtn();
}

function updateStravaImportBtn() {
  const selected = document.querySelectorAll('.strava-row-chk:checked');
  const btn = document.getElementById('btn-import-selected-strava');
  if (selected.length > 0) {
    btn.disabled = false;
    btn.textContent = `📥 Importa Selezionate (${selected.length}) in Trifitness`;
  } else {
    btn.disabled = true;
    btn.textContent = `📥 Importa Selezionate in Trifitness`;
  }
}

async function handleImportSelectedStrava() {
  const selectedChks = document.querySelectorAll('.strava-row-chk:checked');
  if (selectedChks.length === 0) return;

  const toImport = [];
  selectedChks.forEach(chk => {
    const idx = parseInt(chk.dataset.idx);
    if (stravaActivitiesList[idx]) {
      const act = stravaActivitiesList[idx];
      toImport.push({
        date: act.date,
        activity_type: act.activity_type,
        description: act.description,
        duration_minutes: act.duration_minutes,
        distance_km: act.distance_km,
        speed_kmh: act.speed_kmh,
        calories: act.calories,
        auto_calories: act.auto_calories,
        strava_id: act.strava_id,
        avg_hr: act.avg_hr,
        notes: "Importata da Strava"
      });
    }
  });

  try {
    const res = await fetch('/api/strava/import', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ activities: toImport })
    });
    if (res.ok) {
      const data = await res.json();
      alert(`Importate con successo ${data.imported_count} attività!`);
      closeImportModal();
      await loadActivitiesData();
    } else {
      alert("Errore durante l'importazione delle attività");
    }
  } catch (err) {
    console.error("Errore importazione Strava:", err);
    alert("Errore di rete");
  }
}

function setupFileDropzone() {
  const dropzone = document.getElementById('file-dropzone');
  if (!dropzone) return;

  ['dragenter', 'dragover'].forEach(eventName => {
    dropzone.addEventListener(eventName, (e) => {
      e.preventDefault();
      dropzone.classList.add('dragover');
    });
  });

  ['dragleave', 'drop'].forEach(eventName => {
    dropzone.addEventListener(eventName, (e) => {
      e.preventDefault();
      dropzone.classList.remove('dragover');
    });
  });

  dropzone.addEventListener('drop', (e) => {
    if (e.dataTransfer.files && e.dataTransfer.files.length) {
      handleFitnessFiles(e.dataTransfer.files);
    }
  });
}

let batchParsedActivities = [];

function readFileAsText(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(reader.error);
    reader.readAsText(file);
  });
}

async function handleFitnessFiles(files) {
  if (!files || files.length === 0) return;
  batchParsedActivities = [];
  const fileList = Array.from(files);

  const loader = document.getElementById('file-loading-indicator');
  const loaderText = document.getElementById('file-loading-text');
  if (loader) {
    loader.classList.remove('hidden');
    loaderText.textContent = `Caricamento e analisi di ${fileList.length} file in corso...`;
  }

  let processedCount = 0;
  const parsePromises = fileList.map(async (file) => {
    try {
      const content = await readFileAsText(file);
      const res = await fetch('/api/activities/parse-file', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ filename: file.name, content: content })
      });
      processedCount++;
      if (loaderText) {
        loaderText.textContent = `Analisi in corso: ${processedCount} di ${fileList.length} file completati...`;
      }
      if (res.ok) {
        return await res.json();
      } else {
        const err = await res.json();
        console.warn(`Errore file ${file.name}:`, err.detail);
        return null;
      }
    } catch (err) {
      console.error("Errore lettura file:", file.name, err);
      return null;
    }
  });

  const results = await Promise.all(parsePromises);
  if (loader) loader.classList.add('hidden');

  for (const parsed of results) {
    if (!parsed) continue;
    if (Array.isArray(parsed)) {
      batchParsedActivities.push(...parsed);
    } else {
      batchParsedActivities.push(parsed);
    }
  }

  if (batchParsedActivities.length === 0) {
    alert("Nessun dato attività valido trovato nei file selezionati.");
    return;
  }

  // Sort descending by date
  batchParsedActivities.sort((a, b) => (b.date || '').localeCompare(a.date || ''));

  if (batchParsedActivities.length === 1 && !fileList[0].name.toLowerCase().endsWith('.csv')) {
    document.getElementById('file-batch-card').classList.add('hidden');
    parsedFileActivity = batchParsedActivities[0];
    showFilePreview(parsedFileActivity);
  } else {
    document.getElementById('file-preview-card').classList.add('hidden');
    showBatchFilePreview(batchParsedActivities);
  }
}

function cleanActivityTitle(name) {
  if (!name) return 'Attività';
  let clean = name.replace(/\.[a-zA-Z0-9]+$/, '');
  clean = clean.replace(/[_-]+/g, ' ');
  clean = clean.replace(/\s*\(\d+\)\s*/g, ' ');
  return clean.replace(/\s+/g, ' ').trim();
}

function showBatchFilePreview(acts) {
  const card = document.getElementById('file-batch-card');
  const tbody = document.getElementById('file-batch-tbody');
  const titleEl = document.getElementById('file-batch-title');
  card.classList.remove('hidden');

  acts.forEach(act => {
    act.description = cleanActivityTitle(act.description);
    if (!act.calories || act.calories === 0) {
      act.calories = calculateEstimatedCalories(act.duration_minutes, act.speed_kmh);
      act.auto_calories = true;
    }
  });

  const existingStravaIds = new Set(activities.filter(a => a.strava_id).map(a => Number(a.strava_id)));
  const existingDates = new Set(activities.filter(a => a.date).map(a => a.date.substring(0, 16)));

  const importedCount = acts.filter(act => 
    (act.strava_id && existingStravaIds.has(Number(act.strava_id))) || 
    (act.date && existingDates.has(act.date.substring(0, 16)))
  ).length;
  const newCount = acts.length - importedCount;

  titleEl.textContent = `📋 ${acts.length} Attività Rilevate nei File (${newCount} nuove, ${importedCount} già salvate):`;

  tbody.innerHTML = acts.map((act, idx) => {
    const dtParts = (act.date || '').split('T');
    const dateDisp = `${formatDateDisplay(dtParts[0])} ${dtParts[1] ? dtParts[1].substring(0, 5) : ''}`;
    const isImported = (act.strava_id && existingStravaIds.has(Number(act.strava_id))) || 
                       (act.date && existingDates.has(act.date.substring(0, 16)));

    return `
      <tr style="${isImported ? 'opacity: 0.6; background: #f8fafc;' : ''}">
        <td style="text-align: center;">
          <input type="checkbox" class="file-batch-chk" data-idx="${idx}" ${isImported ? 'disabled' : 'checked'}>
        </td>
        <td><strong>${dateDisp}</strong></td>
        <td style="font-weight: 500;">${act.description || 'Attività senza nome'}</td>
        <td>
          <select class="form-input file-batch-type-sel" data-idx="${idx}" style="font-size: 11px; padding: 2px 4px; height: 26px;" ${isImported ? 'disabled' : ''}>
            <option value="walking_pad" ${act.activity_type === 'walking_pad' ? 'selected' : ''}>🚶 Tapis</option>
            <option value="outdoor_walking" ${act.activity_type === 'outdoor_walking' ? 'selected' : ''}>🌲 Aperto</option>
            <option value="cyclette" ${act.activity_type === 'cyclette' ? 'selected' : ''}>🚴 Cyclette</option>
            <option value="other" ${act.activity_type === 'other' ? 'selected' : ''}>⚡ Altro</option>
          </select>
        </td>
        <td>${(parseFloat(act.duration_minutes) % 1 === 0) ? act.duration_minutes : parseFloat(act.duration_minutes).toFixed(1)} min</td>
        <td>${act.distance_km ? act.distance_km.toFixed(2) + ' km' : '-'}</td>
        <td>${act.avg_hr ? `<span class="badge badge-hr">❤️ ${Math.round(act.avg_hr)} bpm</span>` : '-'}</td>
        <td>${act.calories ? Math.round(act.calories) + ' kcal' : '-'}</td>
        <td>
          ${isImported ? `<span class="badge badge-prep" style="background: #e2e8f0; color: #475569;">✅ Già presente</span>` : `<span class="badge badge-prep" style="background: #ecfdf5; color: #047857;">Pronta</span>`}
        </td>
      </tr>
    `;
  }).join('');

  document.querySelectorAll('.file-batch-type-sel').forEach(sel => {
    sel.addEventListener('change', (e) => {
      const idx = parseInt(e.target.dataset.idx);
      if (batchParsedActivities[idx]) {
        batchParsedActivities[idx].activity_type = e.target.value;
      }
    });
  });

  updateBatchImportBtn();
  document.querySelectorAll('.file-batch-chk').forEach(chk => {
    chk.addEventListener('change', updateBatchImportBtn);
  });
}

function toggleBatchFileSelectAll(e) {
  const checked = e.target.checked;
  document.querySelectorAll('.file-batch-chk:not(:disabled)').forEach(chk => {
    chk.checked = checked;
  });
  updateBatchImportBtn();
}

function updateBatchImportBtn() {
  const selected = document.querySelectorAll('.file-batch-chk:checked');
  const btn = document.getElementById('btn-save-batch-activities');
  if (selected.length > 0) {
    btn.disabled = false;
    btn.textContent = `📥 Importa Selezionate (${selected.length}) in Trifitness`;
  } else {
    btn.disabled = true;
    btn.textContent = `📥 Importa Selezionate in Trifitness`;
  }
}

async function handleSaveBatchFileActivities() {
  const selectedChks = document.querySelectorAll('.file-batch-chk:checked');
  if (selectedChks.length === 0) return;

  const toImport = [];
  selectedChks.forEach(chk => {
    const idx = parseInt(chk.dataset.idx);
    if (batchParsedActivities[idx]) {
      const act = batchParsedActivities[idx];
      toImport.push({
        date: act.date,
        activity_type: act.activity_type,
        description: cleanActivityTitle(act.description),
        duration_minutes: act.duration_minutes,
        distance_km: act.distance_km,
        speed_kmh: act.speed_kmh,
        calories: act.calories,
        auto_calories: act.auto_calories,
        strava_id: act.strava_id,
        avg_hr: act.avg_hr,
        notes: "Importata da file / archivio"
      });
    }
  });

  try {
    const res = await fetch('/api/strava/import', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ activities: toImport })
    });
    if (res.ok) {
      const data = await res.json();
      alert(`Importate con successo ${data.imported_count} attività!`);
      closeImportModal();
      document.getElementById('file-batch-card').classList.add('hidden');
      await loadActivitiesData();
    } else {
      alert("Errore durante l'importazione");
    }
  } catch (err) {
    console.error("Errore salvataggio batch:", err);
    alert("Errore di rete");
  }
}

function showFilePreview(act) {
  const card = document.getElementById('file-preview-card');
  card.classList.remove('hidden');

  if (!act.calories || act.calories === 0) {
    act.calories = calculateEstimatedCalories(act.duration_minutes, act.speed_kmh);
    act.auto_calories = true;
  }

  document.getElementById('prev-file-date').value = act.date || '';
  document.getElementById('prev-file-type').value = act.activity_type || 'outdoor_walking';
  document.getElementById('prev-file-duration').value = act.duration_minutes || '';
  document.getElementById('prev-file-distance').value = act.distance_km || '';
  document.getElementById('prev-file-speed').value = act.speed_kmh || '';
  document.getElementById('prev-file-hr').value = act.avg_hr || '';
  document.getElementById('prev-file-calories').value = act.calories ? Math.round(act.calories) : '';
  document.getElementById('prev-file-desc').value = cleanActivityTitle(act.description) || '';
}

async function handleSaveFileActivity() {
  if (!parsedFileActivity) return;

  const date = document.getElementById('prev-file-date').value;
  const type = document.getElementById('prev-file-type').value;
  const duration = parseFloat(document.getElementById('prev-file-duration').value) || 0;
  const dist = parseFloat(document.getElementById('prev-file-distance').value) || null;
  const speed = parseFloat(document.getElementById('prev-file-speed').value) || 4.0;
  const hr = document.getElementById('prev-file-hr').value !== '' ? parseFloat(document.getElementById('prev-file-hr').value) : null;
  const calories = parseFloat(document.getElementById('prev-file-calories').value) || 0;
  const desc = document.getElementById('prev-file-desc').value.trim();

  const payload = {
    date: date,
    activity_type: type,
    description: desc,
    duration_minutes: duration,
    distance_km: dist,
    speed_kmh: speed,
    calories: calories,
    auto_calories: calories === 0,
    avg_hr: hr,
    notes: "Importata da file"
  };

  try {
    const res = await fetch('/api/activities', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    if (res.ok) {
      alert("Attività salvata con successo!");
      closeImportModal();
      document.getElementById('file-preview-card').classList.add('hidden');
      await loadActivitiesData();
    } else {
      const err = await res.json();
      alert(`Errore: ${err.detail || 'Impossibile salvare l\'attività'}`);
    }
  } catch (err) {
    console.error("Errore salvataggio file attività:", err);
  }
}

function formatDateDisplay(isoDate) {
  if (!isoDate) return '-';
  const parts = isoDate.split('-');
  if (parts.length === 3) {
    return `${parts[2]}/${parts[1]}/${parts[0]}`;
  }
  return isoDate;
}

