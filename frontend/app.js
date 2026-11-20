// FridgeToDinner front end — plain JS, no build step.
const $ = (id) => document.getElementById(id);

const state = {
  appliances: [],      // selected appliance keys
  ingredients: [],     // {name, quantity, confidence, expiring}
  priorities: ["speed", "filling", "use_expiring", "healthy"],
  lastMeals: [],
  options: { appliances: {}, priorities: {} },
};

const store = {
  get(k, fallback) { try { return JSON.parse(localStorage.getItem(k)) ?? fallback; } catch { return fallback; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* storage unavailable */ } },
};

async function api(path, opts = {}) {
  const res = await fetch(path, opts);
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(typeof body.detail === "string" ? body.detail : `Request failed (${res.status})`);
  return body;
}

// ---------- Step 1: appliances ----------
function renderAppliances() {
  const box = $("appliance-list");
  box.innerHTML = "";
  for (const [key, label] of Object.entries(state.options.appliances)) {
    const id = `ap-${key}`;
    const wrap = document.createElement("label");
    wrap.className = "chip";
    wrap.innerHTML = `<input type="checkbox" id="${id}" ${state.appliances.includes(key) ? "checked" : ""}/> ${label}`;
    wrap.querySelector("input").addEventListener("change", (e) => {
      state.appliances = e.target.checked
        ? [...state.appliances, key]
        : state.appliances.filter((a) => a !== key);
      store.set("appliances", state.appliances);
    });
    box.appendChild(wrap);
  }
}

// ---------- Step 2: photo ----------
$("photo-input").addEventListener("change", () => {
  const file = $("photo-input").files[0];
  $("detect-btn").disabled = !file;
  if (file) {
    const img = $("photo-preview");
    img.src = URL.createObjectURL(file);
    img.hidden = false;
  }
});

$("detect-btn").addEventListener("click", async () => {
  const file = $("photo-input").files[0];
  if (!file) return;
  setStatus("detect-status", "Looking in your fridge…");
  $("detect-btn").disabled = true;
  try {
    const fd = new FormData();
    fd.append("photo", file);
    const data = await api("/api/detect", { method: "POST", body: fd });
    state.ingredients = data.ingredients.map((i) => ({ ...i, expiring: false }));
    setStatus("detect-status", `Found ${state.ingredients.length} items.`);
    renderIngredients();
    show("step-review"); show("step-priorities");
    $("step-review").scrollIntoView({ behavior: "smooth" });
  } catch (err) {
    setStatus("detect-status", err.message, true);
  } finally {
    $("detect-btn").disabled = false;
  }
});

// ---------- Step 3: review ----------
function renderIngredients() {
  const ul = $("ingredient-list");
  ul.innerHTML = "";
  state.ingredients.forEach((ing, idx) => {
    const li = document.createElement("li");
    const low = ing.confidence < 0.6;
    li.className = low ? "low" : "";
    li.innerHTML = `
      <span class="name">${escapeHtml(ing.name)}${ing.quantity ? ` <small>(${escapeHtml(ing.quantity)})</small>` : ""}
        ${low ? '<small class="warn" title="The AI was unsure about this one">unsure?</small>' : ""}</span>
      <label class="exp"><input type="checkbox" ${ing.expiring ? "checked" : ""}/> expiring</label>
      <button class="icon" aria-label="Remove ${escapeHtml(ing.name)}">✕</button>`;
    li.querySelector("input").addEventListener("change", (e) => { ing.expiring = e.target.checked; });
    li.querySelector("button").addEventListener("click", () => { state.ingredients.splice(idx, 1); renderIngredients(); });
    ul.appendChild(li);
  });
}

$("add-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const name = $("add-input").value.trim().toLowerCase();
  if (!name) return;
  state.ingredients.push({ name, quantity: "", confidence: 1, expiring: false });
  $("add-input").value = "";
  renderIngredients();
  show("step-priorities");
});

// ---------- Step 4: priorities ----------
function renderPriorities() {
  const ol = $("priority-list");
  ol.innerHTML = "";
  state.priorities.forEach((p, i) => {
    const li = document.createElement("li");
    li.innerHTML = `<span>${state.options.priorities[p]}</span>
      <span><button class="icon" ${i === 0 ? "disabled" : ""} aria-label="Move up">▲</button>
      <button class="icon" ${i === state.priorities.length - 1 ? "disabled" : ""} aria-label="Move down">▼</button></span>`;
    const [up, down] = li.querySelectorAll("button");
    up.addEventListener("click", () => move(i, -1));
    down.addEventListener("click", () => move(i, 1));
    ol.appendChild(li);
  });
}
function move(i, d) {
  const p = state.priorities;
  [p[i], p[i + d]] = [p[i + d], p[i]];
  store.set("priorities", p);
  renderPriorities();
}

// ---------- Step 5: meals ----------
async function generate(regenerate = false) {
  if (!state.appliances.length) return setStatus("generate-status", "Pick at least one appliance in step 1.", true);
  if (!state.ingredients.length) return setStatus("generate-status", "Add at least one ingredient.", true);
  setStatus("generate-status", "Thinking up meals…");
  $("generate-btn").disabled = $("regen-btn").disabled = true;
  try {
    const data = await api("/api/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ingredients: state.ingredients,
        appliances: state.appliances,
        priorities: state.priorities,
        max_prep_minutes: Number($("max-time").value),
        allergies: $("allergies").value,
        exclude_meals: regenerate ? state.lastMeals : [],
      }),
    });
    state.lastMeals = data.meals.map((m) => m.name);
    renderMeals(data);
    setStatus("generate-status", "");
    show("step-meals");
    $("step-meals").scrollIntoView({ behavior: "smooth" });
  } catch (err) {
    setStatus("generate-status", err.message, true);
  } finally {
    $("generate-btn").disabled = $("regen-btn").disabled = false;
  }
}

function renderMeals(data) {
  const box = $("meal-list");
  box.innerHTML = "";
  const flagged = new Set(data.remaining_violations.map((v) => v.meal));
  for (const m of data.meals) {
    const card = document.createElement("details");
    card.className = "meal" + (flagged.has(m.name) ? " flagged" : "");
    card.innerHTML = `
      <summary><strong>${escapeHtml(m.name)}</strong> <span class="time">${m.prep_minutes} min</span>
        <small>${escapeHtml(m.why || "")}</small></summary>
      <p><b>Uses:</b> ${m.ingredients.map((i) => escapeHtml(i.amount ? `${i.name} (${i.amount})` : i.name)).join(", ")}</p>
      <p><b>Appliances:</b> ${m.appliances_used.length ? m.appliances_used.map((a) => state.options.appliances[a] || a).join(", ") : "none"}</p>
      <ol>${m.steps.map((s) => `<li>${escapeHtml(s)}</li>`).join("")}</ol>
      ${m.safety_note ? `<p class="safety">⚠ ${escapeHtml(m.safety_note)}</p>` : ""}
      ${flagged.has(m.name) ? '<p class="warn">This one did not pass every check — try Regenerate.</p>' : ""}`;
    box.appendChild(card);
  }
  $("debug-out").textContent = JSON.stringify({
    attempts: data.attempts,
    first_try_valid: data.first_try_valid,
    violations_fixed: data.violations_fixed,
    remaining_violations: data.remaining_violations,
    usage: data.usage,
    mock: data.mock,
  }, null, 2);
}

$("generate-btn").addEventListener("click", () => generate(false));
$("regen-btn").addEventListener("click", () => generate(true));

// ---------- helpers ----------
function show(id) { $(id).hidden = false; pinned = null; updateStepsNav(); }

// ---------- step tabs: lock hidden steps, highlight the one in view ----------
const stepLinks = [...document.querySelectorAll(".steps-nav a")];
function updateStepsNav() {
  const marker = window.innerHeight * 0.35;
  let current = stepLinks[0];
  for (const a of stepLinks) {
    const sec = $(a.dataset.step);
    a.classList.toggle("locked", sec.hidden);
    if (!sec.hidden && sec.getBoundingClientRect().top <= marker) current = a;
  }
  const atBottom = window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 4;
  if (atBottom) current = stepLinks.filter((a) => !$(a.dataset.step).hidden).at(-1) || current;
  if (pinned && !$(pinned.dataset.step).hidden) current = pinned;
  const idx = stepLinks.indexOf(current);
  stepLinks.forEach((a, i) => {
    a.classList.toggle("active", a === current);
    a.classList.toggle("done", i < idx);
    if (a === current) a.setAttribute("aria-current", "step"); else a.removeAttribute("aria-current");
  });
}
// a clicked tab stays highlighted until the user scrolls on their own
let pinned = null;
stepLinks.forEach((a) => a.addEventListener("click", () => { pinned = a; updateStepsNav(); }));
["wheel", "touchmove", "keydown"].forEach((ev) => window.addEventListener(ev, () => { pinned = null; }, { passive: true }));
let navTick = false;
window.addEventListener("scroll", () => {
  if (navTick) return;
  navTick = true;
  requestAnimationFrame(() => { updateStepsNav(); navTick = false; });
}, { passive: true });
window.addEventListener("resize", updateStepsNav);
function setStatus(id, msg, isErr = false) { const el = $(id); el.textContent = msg; el.classList.toggle("error", isErr); }
function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// ---------- boot ----------
(async function init() {
  try {
    const [opts, health] = await Promise.all([api("/api/options"), api("/api/health")]);
    state.options = opts;
    state.appliances = store.get("appliances", ["microwave"]);
    const saved = store.get("priorities", null);
    if (Array.isArray(saved) && saved.length === 4) state.priorities = saved;
    renderAppliances();
    renderPriorities();
    updateStepsNav();
    if (health.mock_mode) {
      const b = $("mode-badge");
      b.textContent = "Mock mode"; b.title = "No API key set, so the AI responses are canned";
      b.hidden = false;
    }
  } catch (err) {
    document.body.insertAdjacentHTML("afterbegin", `<p class="status error">Could not reach the server: ${escapeHtml(err.message)}</p>`);
  }
})();
