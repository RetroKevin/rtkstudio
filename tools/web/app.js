"use strict";

const $ = (id) => document.getElementById(id);
const PAGE = 200;

const state = {
  offset: 0, total: 0, key: null, mod: null, palettes: [], palette: "",
  character: "James", anim: null, characters: [],
  kit: {}, weapon: "", shield: "", sheathed: false,
  regions: {
    head: { length: 1, width: 1 },
    torso: { length: 1, width: 1 },
    arms: { length: 1, width: 1 },
    legs: { length: 1, width: 1 },
  },
  pickRegion: null, pickJoint: "",
  itemScale: { length: 1, width: 1 }, itemSlot: "",
  bgColor: "#0d0e11", bgScene: "", backdrop: "", backdrops: null,
};

// --- helpers -------------------------------------------------------------

function toast(message, bad) {
  const el = $("toast");
  el.textContent = message;
  el.classList.toggle("bad", !!bad);
  el.classList.remove("hidden");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => el.classList.add("hidden"), bad ? 9000 : 4000);
}

async function api(path, options) {
  const res = await fetch(path, options);
  const body = await res.json();
  if (!res.ok) throw new Error(body.error || res.statusText);
  return body;
}

const bytes = (n) =>
  n < 1024 ? n + " B"
  : n < 1048576 ? (n / 1024).toFixed(1) + " KB"
  : (n / 1048576).toFixed(1) + " MB";

const esc = (s) => String(s).replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));

// --- the asset list ------------------------------------------------------

function query(offset) {
  const p = new URLSearchParams({
    q: ($("q") && $("q").value) || state.assetQ || "",
    kind: ($("kind") && $("kind").value) || state.assetKind || "",
    source: ($("source") && $("source").value) || state.assetSource || "",
    offset: offset, limit: PAGE,
  });
  return "/api/search?" + p;
}

function rememberAssetFilters() {
  if ($("q")) state.assetQ = $("q").value;
  if ($("kind")) state.assetKind = $("kind").value;
  if ($("source")) state.assetSource = $("source").value;
  if ($("scope")) state.assetScope = $("scope").value;
}

function assetScope() {
  return ($("scope") && $("scope").value) || state.assetScope || "files";
}

function toggleAssetScope() {
  const scope = assetScope();
  state.assetScope = scope;
  const files = scope === "files";
  const binary = scope === "binary";
  if ($("filefilters")) $("filefilters").classList.toggle("hidden", !files);
  if ($("findreplacebox")) $("findreplacebox").classList.toggle("hidden", files || binary);
  if ($("q")) {
    $("q").placeholder = files
      ? "Search files…"
      : (binary ? "Text or hex:4d65…" : "Name, text, or number…");
  }
}

async function loadRecordHits() {
  const list = $("list");
  if (!list) return;
  const q = ($("q") && $("q").value || "").trim();
  const scope = assetScope();
  rememberAssetFilters();
  if (q.length < 2 && !/^\d$/.test(q)) {
    list.innerHTML = "";
    state.findHits = [];
    if ($("count")) $("count").textContent = "Type at least 2 characters";
    if ($("more")) $("more").classList.add("hidden");
    return;
  }
  if ($("count")) $("count").textContent = "Searching…";
  try {
    const doc = await api("/api/find?q=" + encodeURIComponent(q) +
      "&kind=" + encodeURIComponent(scope === "records" ? "" : scope));
    state.findHits = doc.hits || [];
    list.innerHTML = "";
    state.findHits.forEach((h, i) => {
      const li = document.createElement("li");
      li.dataset.hit = String(i);
      li.innerHTML = `<span class="key">${esc(h.label || h.name)}</span>` +
        `<span class="kind">${esc(h.kind)}</span>`;
      li.onclick = () => showFindHit(h, li);
      li.ondblclick = () => jumpToHit(h);
      list.appendChild(li);
    });
    const extra = doc.mode === "binary" && doc.scanned ? " · scanned " + doc.scanned : "";
    if ($("count")) {
      $("count").textContent = doc.total + " match" + (doc.total === 1 ? "" : "es") +
        (doc.total > state.findHits.length ? " (showing " + state.findHits.length + ")" : "") +
        extra;
    }
    if ($("more")) $("more").classList.add("hidden");
    const pane = $("assetpane");
    if (pane && !state.findHits.length) {
      pane.innerHTML = `<div class="empty"><p>No matches.</p></div>`;
    }
  } catch (e) {
    if ($("count")) $("count").textContent = e.message;
  }
}

function showFindHit(hit, li) {
  const list = $("list");
  if (list) {
    for (const child of list.children) child.classList.toggle("on", child === li);
  }
  const pane = $("assetpane");
  if (!pane) return;
  const bits = [hit.kind, hit.snippet || ""].filter(Boolean);
  pane.innerHTML = `<h2>${esc(hit.label || hit.name)}</h2>
    <p class="note">${esc(bits.join(" · "))}</p>
    <button type="button" class="primary" id="findopen">${hit.kind === "binary" ? "Show file" : "Open"}</button>
    <p class="note">${hit.kind === "binary"
      ? "Hex needs spaces or a hex: prefix. This opens the file in the list."
      : "Opens the studio for this record. Double-click the row to jump straight there."}</p>`;
  $("findopen").onclick = () => jumpToHit(hit);
}

async function replaceRecordText() {
  const scope = assetScope();
  if (scope === "files" || scope === "binary") {
    toast("Replace works on characters, items, dialog, scenes, and shops", true);
    return;
  }
  const find = ($("q") && $("q").value || "").trim();
  const repl = $("findrepl") ? $("findrepl").value : "";
  if (!find) { toast("Type the text to find", true); return; }
  const btn = $("findreplace");
  if (btn) btn.disabled = true;
  try {
    const doc = await api("/api/find/replace", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        find,
        replace: repl == null ? "" : repl,
        kind: scope === "records" ? "" : scope,
      }),
    });
    toast("Replaced " + doc.fields + " field" + (doc.fields === 1 ? "" : "s") +
      " in " + doc.files + " file" + (doc.files === 1 ? "" : "s"));
    await refreshMod();
    await loadRecordHits();
  } catch (e) {
    toast("Could not replace: " + e.message, true);
  }
  if ($("findreplace")) $("findreplace").disabled = false;
}

async function loadList(append) {
  const list = $("list");
  if (!list) return;
  if (assetScope() !== "files") return loadRecordHits();
  rememberAssetFilters();
  state.offset = append ? state.offset + PAGE : 0;
  const data = await api(query(state.offset));
  state.total = data.total;
  if (!append) list.innerHTML = "";
  for (const a of data.items) {
    const li = document.createElement("li");
    li.className = a.modified ? "mod" : "";
    li.dataset.key = a.key;
    li.innerHTML = `<span class="key">${esc(a.key)}</span>` +
                   `<span class="kind">${esc(a.kind)} &middot; ${bytes(a.size)}</span>`;
    li.onclick = () => select(a.key);
    list.appendChild(li);
  }
  if ($("count")) {
    $("count").textContent =
      `${data.total.toLocaleString()} match${data.total === 1 ? "" : "es"}` +
      (data.total > state.offset + PAGE ? ` (showing ${state.offset + data.items.length})` : "");
  }
  if ($("more")) $("more").classList.toggle("hidden", state.offset + PAGE >= data.total);
  if (state.key) highlight(state.key);
}

function highlight(key) {
  const list = $("list");
  if (!list) return;
  for (const li of list.children) li.classList.toggle("on", li.dataset.key === key);
}

function paneTarget() {
  return $("assetpane") || $("detail");
}

// --- the detail pane -----------------------------------------------------

async function select(key) {
  state.key = key;
  highlight(key);
  const p = new URLSearchParams({ key });
  if (state.palette) p.set("palette", state.palette);
  const meta = await api("/api/asset?" + p);
  render(meta);
}

function previewUrl(key, palette) {
  const p = new URLSearchParams({ key, t: Date.now() });
  if (palette) p.set("palette", palette);
  return "/api/preview?" + p;
}

function render(meta) {
  const key = meta.key, ct = meta.content_type || "";
  const skip = new Set(["key", "content_type", "text", "asset", "mode", "editable", "modified"]);
  const facts = Object.entries(meta)
    .filter(([k, v]) => !skip.has(k) && v !== null && v !== "")
    .map(([k, v]) => `<span>${esc(k)} <b>${esc(k === "size" ? bytes(v) : v)}</b></span>`)
    .join("");

  const kind = (meta.asset && meta.asset.kind) || meta.kind || "";
  const is3d = kind === "anim" || kind === "rig";

  let stage;
  if (is3d) {
    stage = pane3d(meta);
  } else if (ct.startsWith("image/")) {
    stage = `<div class="stage"><img src="${previewUrl(key, state.palette)}" alt=""></div>`;
  } else if (ct.startsWith("audio/")) {
    stage = `<div class="stage media">
      <audio controls preload="auto" src="${previewUrl(key)}"></audio>
      ${meta.preview ? `<p class="note">${esc(meta.preview)}</p>` : ""}
    </div>`;
  } else if (ct.startsWith("video/")) {
    stage = `<div class="stage media">
      <video controls playsinline preload="auto" src="${previewUrl(key)}"></video>
      <p class="note">${esc(meta.preview || "First play transcodes the XviD cutscene.")}</p>
    </div>`;
  } else {
    stage = `<div class="stage"><pre>${esc(meta.text || "")}</pre></div>`;
  }

  // The server reports which palette it actually used; show that one as
  // selected rather than letting the browser default to the first option.
  const shown = state.palette || meta.palette || "";
  const why = { "screen map": "from the screen that draws it",
                "engine default": "engine default \u2014 no screen palette found",
                "chosen": "you picked this" }[meta.palette_source] || "";
  const paletteSel = ct.startsWith("image/") && meta.palette && state.palettes.length
    ? `<label class="small muted">palette
         <select id="pal">${state.palettes.map((n) =>
           `<option${n === shown ? " selected" : ""}>${esc(n)}</option>`).join("")}</select>
       </label><span class="small muted">${esc(why)}</span>` : "";

  paneTarget().innerHTML = `
    <h2>${esc(key)} ${meta.modified ? '<span class="pill dirty">edited</span>' : ""}</h2>
    <div class="facts">${facts}</div>
    <div class="tools">
      ${paletteSel}
      <a href="/api/download?key=${encodeURIComponent(key)}"><button>Download raw</button></a>
      ${meta.modified ? '<button id="revert">Revert edit</button>' : ""}
      ${canDiff(meta) ? '<button id="compare" type="button">Compare with install</button>' : ""}
    </div>
    <div id="diffbox"></div>
    ${stage}
    ${editor(meta)}`;

  if ($("pal")) $("pal").onchange = (e) => { state.palette = e.target.value; select(key); };
  if ($("revert")) $("revert").onclick = () => revert(key);
  if ($("compare")) $("compare").onclick = () => showDiff(key);
  if (is3d) wire3d(meta);
  else if (typeof RTKViewer !== "undefined") RTKViewer.unmount();
  wireEditor(meta);
}

function canDiff(meta) {
  const kind = (meta.asset && meta.asset.kind) || meta.kind || "";
  return !!(meta.modified && (kind === "text" || kind === "script" ||
    kind === "image" || kind === "depth" || kind === "palette"));
}

function diffLines(original, modified) {
  const left = (original || "").split("\n");
  const right = (modified || "").split("\n");
  const n = Math.min(Math.max(left.length, right.length), 2500);
  const rows = [];
  let changed = 0;
  for (let i = 0; i < n; i++) {
    const a = left[i] == null ? "" : left[i];
    const b = right[i] == null ? "" : right[i];
    const cls = a === b ? "" : " chg";
    if (cls) changed += 1;
    rows.push(`<div class="diffrow${cls}"><pre>${esc(a)}</pre><pre>${esc(b)}</pre></div>`);
  }
  const more = Math.max(left.length, right.length) > n
    ? `<p class="note">Showing the first ${n} lines.</p>` : "";
  return { html: rows.join("") + more, changed };
}

async function showDiff(key) {
  const box = $("diffbox");
  if (!box) return;
  box.innerHTML = `<p class="note">Comparing…</p>`;
  try {
    const doc = await api("/api/diff?key=" + encodeURIComponent(key));
    if (doc.mode === "image") {
      const pal = state.palette ? "&palette=" + encodeURIComponent(state.palette) : "";
      box.innerHTML = `<div class="diffpair">
        <div><h3>Install</h3><img alt="" src="/api/preview?key=${encodeURIComponent(key)}&original=1${pal}"></div>
        <div><h3>Mod</h3><img alt="" src="${previewUrl(key, state.palette)}"></div>
      </div>`;
      return;
    }
    if (doc.mode !== "text") {
      box.innerHTML = `<p class="note">This asset has no text or picture to compare.</p>`;
      return;
    }
    const view = diffLines(doc.original, doc.modified);
    box.innerHTML = `<p class="note">${view.changed} line${view.changed === 1 ? "" : "s"} differ${doc.truncated ? " · truncated" : ""}.</p>
      <div class="diffhead"><span>Install</span><span>Mod</span></div>
      <div class="difflines">${view.html}</div>`;
  } catch (e) {
    box.innerHTML = `<p class="note">${esc(e.message)}</p>`;
  }
}

function pane3d(meta) {
  const kind = meta.asset && meta.asset.kind;
  if (kind === "anim") state.anim = meta.key;
  return `
    <div class="stage stage3d">
      <div class="animbar">
        <label>character <select id="charpick"></select></label>
        <label>animation <select id="animpick"></select></label>
        <span id="armorslots"></span>
        <label>weapon <select id="weaponpick"></select></label>
        <label>shield <select id="shieldpick"></select></label>
        <label class="small muted"><input type="checkbox" id="sheathed"> sheathed</label>
        <button id="play3d">Pause</button>
        <input type="range" id="scrub" min="0" max="0" value="0">
        <span id="framehint" class="small muted">0 / 0</span>
        <label class="small muted"><input type="checkbox" id="showbones"> joints</label>
        <label class="small muted"><input type="checkbox" id="showwire"> wireframe</label>
        <label class="small muted"><input type="checkbox" id="showcol"> collision</label>
        <label>bg <input type="color" id="bgcolor" value="${esc(state.bgColor || "#0d0e11")}"></label>
        <label>scene <select id="bgscene"></select></label>
        <label>view <select id="bgview"></select></label>
        <span class="small muted">click a body part or use the sliders on the left · drag to rotate · orbit: alt-drag · pan: WASD · zoom: wheel</span>
      </div>
      <div class="stage3d-body">
        <div id="partpanel" class="partpanel">
          <h3>Size &amp; shape</h3>
          <p class="note">Length moves bones. Width is girth. Click the model to highlight a group.</p>
          ${["head","torso","arms","legs"].map((id) => {
            const lab = { head: "Head", torso: "Torso", arms: "Arms", legs: "Legs" }[id];
            const rec = (state.regions && state.regions[id]) || { length: 1, width: 1 };
            const ln = (+rec.length || 1).toFixed(2);
            const wd = (+rec.width || 1).toFixed(2);
            return `<div class="partblock" data-region="${id}">
              <h4>${lab}</h4>
              <label class="pslider">Length
                <input type="range" min="0.25" max="3" step="0.01" data-region="${id}" data-axis="length" value="${ln}">
                <span class="cval">${ln}</span>
              </label>
              <label class="pslider">Width
                <input type="range" min="0.25" max="3" step="0.01" data-region="${id}" data-axis="width" value="${wd}">
                <span class="cval">${wd}</span>
              </label>
              <button type="button" data-act="sprites" data-region="${id}">Edit sprites</button>
            </div>`;
          }).join("")}
          <div class="creator-tools" style="margin-top:10px">
            <button type="button" class="primary" id="savesizes"${state.mod ? "" : " disabled"}>Save sizes</button>
          </div>
        </div>
        <canvas id="view3d"></canvas>
      </div>
      <div id="creator" class="creator hidden"></div>
      <div class="animbar trs">
        <label>joint <select id="jointpick"></select></label>
        <label>rot°
          <input id="rx" type="number" step="0.1">
          <input id="ry" type="number" step="0.1">
          <input id="rz" type="number" step="0.1">
        </label>
        <label>pos
          <input id="tx" type="number" step="0.01">
          <input id="ty" type="number" step="0.01">
          <input id="tz" type="number" step="0.01">
        </label>
        <button class="primary" id="saveanim"${state.mod ? "" : " disabled"}>Save</button>
        <input id="newstem" maxlength="7" placeholder="TKMOD01" ${state.mod ? "" : "disabled"}>
        <button id="dupanim"${state.mod ? "" : " disabled"}>Duplicate as new</button>
      </div>
      <p class="note">Conversation tracks are not bound to one character —
        the default (and last pick) is <b>${esc(state.character)}</b>.
        Saved edits go to the mod, never the install.
        <code>.trx</code> lip-sync is a separate text file;
        40 archived tracks have no recovered rig;
        the 4 twenty-joint loose tracks are missing their 3 shadow helpers.</p>
    </div>`;
}

function wireSizePanel(remount) {
  const panel = $("partpanel");
  if (!panel) return;
  let timer = 0;
  panel.querySelectorAll("input[type=range][data-region]").forEach((sl) => {
    sl.oninput = () => {
      const rid = sl.dataset.region;
      const axis = sl.dataset.axis;
      const v = +sl.value;
      const label = sl.parentElement && sl.parentElement.querySelector(".cval");
      if (label) label.textContent = v.toFixed(2);
      state.regions = state.regions || {};
      state.regions[rid] = state.regions[rid] || { length: 1, width: 1 };
      if (typeof state.regions[rid] !== "object") {
        const s = +state.regions[rid] || 1;
        state.regions[rid] = { length: s, width: s };
      }
      state.regions[rid][axis] = v;
      state.pickRegion = rid;
      panel.querySelectorAll(".partblock").forEach((b) => {
        b.classList.toggle("on", b.dataset.region === rid);
      });
      clearTimeout(timer);
      timer = setTimeout(() => remount && remount(), 120);
    };
  });
  panel.querySelectorAll("[data-act=sprites]").forEach((btn) => {
    btn.onclick = () => {
      state.pickRegion = btn.dataset.region;
      if (window.RTKCreator && RTKCreator._opts) {
        RTKCreator.selectPart({ region: btn.dataset.region, joint: state.pickJoint });
        if (!RTKCreator._editing) RTKCreator._toggleEditor();
      } else {
        toast("Sprite editor is still loading. Wait a moment and try again.", true);
      }
    };
  });
  const save = $("savesizes");
  if (save) {
    save.onclick = async () => {
      try {
        const r = await api("/api/character/kit", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ character: state.character, regions: state.regions }),
        });
        state.regions = r.regions;
        toast("Saved body sizes into the mod.");
        await refreshMod();
      } catch (e) {
        toast("Could not save sizes: " + e.message, true);
      }
    };
  }
}

function readItemScale() {
  const ln = $("itlen") ? +$("itlen").value : ((state.itemScale && state.itemScale.length) || 1);
  const wd = $("itwid") ? +$("itwid").value : ((state.itemScale && state.itemScale.width) || 1);
  state.itemScale = { length: ln || 1, width: wd || 1 };
  return state.itemScale;
}

function armorSlots(pv) {
  if (pv && pv.slots && pv.slots.length) return pv.slots.slice();
  return pv && pv.slot ? [pv.slot] : [];
}

function lookCode(label) {
  const m = String(label || "").match(/(\d+)$/);
  return m ? parseInt(m[1], 10) : null;
}

function matchArmorLook(options, subcategory, preferCode) {
  if (!options || !options.length) return 0;
  const coded = options.map((o) => ({ i: o.i, c: lookCode(o.label) }));
  const pick = (want) => {
    if (want == null) return null;
    const exact = coded.find((x) => x.c === want);
    if (exact) return exact.i;
    if (want >= 10) {
      const ones = Math.floor(want / 10);
      const byOnes = coded.find((x) => x.c === ones);
      if (byOnes) return byOnes.i;
      const byTens = coded.find((x) => x.c != null && Math.floor(x.c / 10) === ones);
      if (byTens) return byTens.i;
    } else if (want) {
      const tensEquiv = want * 10;
      const byTens = coded.find((x) => x.c === tensEquiv);
      if (byTens) return byTens.i;
      const byGroup = coded.find((x) => x.c != null && Math.floor(x.c / 10) === want);
      if (byGroup) return byGroup.i;
    }
    return null;
  };
  let hit = pick(preferCode);
  if (hit != null) return hit;
  const sub = String(subcategory || "").toLowerCase();
  const table = [
    ["leather", [10, 1]],
    ["chainmail", [20, 2]],
    ["chain", [20, 2]],
    ["plate", [30, 3]],
  ];
  for (let t = 0; t < table.length; t++) {
    if (sub.indexOf(table[t][0]) >= 0) {
      for (let w = 0; w < table[t][1].length; w++) {
        hit = pick(table[t][1][w]);
        if (hit != null) return hit;
      }
      break;
    }
  }
  return options[0].i;
}

function kitSnapshot(it) {
  return armorSlots((it && it.preview) || {}).map((s) =>
    s + "=" + ((state.kit && state.kit[s]) != null ? state.kit[s] : "")
  ).join(",");
}

function syncArmorKit(it, preferCode) {
  const pv = (it && it.preview) || {};
  state.kit = state.kit || {};
  const slots = armorSlots(pv);
  const gearSlots = (state._gear && state._gear.slots) || [];
  const byId = {};
  gearSlots.forEach((s) => { byId[s.id] = s; });
  const want = (preferCode != null) ? preferCode : state._armorLookCode;
  slots.forEach((id) => {
    const rec = byId[id];
    if (!rec) return;
    state.kit[id] = matchArmorLook(rec.options, it.subcategory, want);
  });
  const primary = slots[0];
  if (primary && byId[primary]) {
    const opt = (byId[primary].options || []).find((o) => o.i === state.kit[primary]);
    const landed = lookCode(opt && opt.label);
    if (landed != null) state._armorLookCode = landed;
    else if (preferCode != null) state._armorLookCode = preferCode;
  }
  return slots;
}

function refreshItlook(it) {
  const pv = (it && it.preview) || {};
  if (pv.kind !== "armor") return;
  const primary = armorSlots(pv)[0] || pv.slot;
  const looks = armorLooks(primary);
  const cur = (primary && state.kit && state.kit[primary] != null) ? state.kit[primary] : 0;
  const sel = $("itlook");
  if (sel) {
    sel.innerHTML = looks.map((o) =>
      `<option value="${o.i}"${o.i === cur ? " selected" : ""}>${esc(o.label)}</option>`
    ).join("");
  }
  const hint = $("itlookhint");
  if (hint) hint.hidden = looks.length > 0;
}

function itemOverlays(it) {
  const ch = state.character || "James";
  return ((it && it.paper_doll) || []).filter((d) =>
    d && d.key && (!d.character || d.character === ch));
}

function applyItemPreview(it, preferCode) {
  const pv = (it && it.preview) || {};
  const mesh = $("itmesh") ? $("itmesh").value : (pv.gear || "");
  state.itemSlot = "";
  state.overlays = itemOverlays(it);
  if (pv.kind === "weapon" || pv.kind === "wand" || pv.hold) {
    state.weapon = mesh;
    state.shield = "";
  } else if (pv.kind === "potion") {
    state.weapon = mesh || "objpotion";
    state.shield = "";
  } else if (pv.kind === "shield") {
    state.shield = mesh;
    state.weapon = "";
  } else if (pv.kind === "armor") {
    state.weapon = "";
    state.shield = "";
    const slots = syncArmorKit(it, preferCode);
    state.itemSlot = slots.join(",");
  } else {
    state.weapon = "";
    state.shield = "";
  }
  readItemScale();
  if (state._remount3d) return state._remount3d();
}

function armorLooks(slot) {
  const slots = (state._gear && state._gear.slots) || [];
  const rec = slots.find((s) => s.id === slot);
  return (rec && rec.options) || [];
}

function modifierGroups(extra) {
  const cats = state.itemModifiers || [];
  const by = {};
  const order = [];
  cats.forEach((m) => {
    if (!by[m.group]) {
      by[m.group] = [];
      order.push(m.group);
    }
    by[m.group].push(m);
  });
  (extra || []).forEach((name) => {
    if (!name || cats.some((m) => m.name === name)) return;
    if (!by.Other) {
      by.Other = [];
      order.push("Other");
    }
    by.Other.push({ name, group: "Other", modify: "Value", value: "1" });
  });
  return order.filter((g) => by[g] && by[g].length).map((g) => ({ group: g, items: by[g] }));
}

function modifierOptions(selected) {
  return modifierGroups(selected ? [selected] : []).map((g) =>
    `<optgroup label="${esc(g.group)}">${g.items.map((m) =>
      `<option value="${esc(m.name)}"${m.name === selected ? " selected" : ""}>${esc(m.name)}</option>`
    ).join("")}</optgroup>`
  ).join("");
}

function bonusRowHtml(mod) {
  const name = (mod && mod.name) || "";
  const how = (mod && mod.modify) || "Value";
  const val = (mod && mod.value) != null ? mod.value : "";
  return `<div class="itemmod">
    <select class="itmodname">${modifierOptions(name)}</select>
    <select class="itmodhow">
      <option value="Value"${how === "Ratio" ? "" : " selected"}>Value</option>
      <option value="Ratio"${how === "Ratio" ? " selected" : ""}>Ratio</option>
    </select>
    <input class="itmodval" value="${esc(val)}">
    <button type="button" class="itmoddel">Remove</button>
  </div>`;
}

function readMods(boxId) {
  const mods = [];
  document.querySelectorAll("#" + boxId + " .itemmod").forEach((row) => {
    const name = row.querySelector(".itmodname");
    const how = row.querySelector(".itmodhow");
    const val = row.querySelector(".itmodval");
    if (name && name.value) {
      mods.push({
        name: name.value,
        modify: how ? how.value : "Value",
        value: val ? val.value : "0",
      });
    }
  });
  return mods;
}

function readReadyEffect() {
  if (!$("itmods") && !$("itfxdesc")) return undefined;
  return {
    desc: $("itfxdesc") ? $("itfxdesc").value : "",
    modifiers: readMods("itmods"),
  };
}

function readUseEffect() {
  if (!$("itusdesc") && !$("itusspell") && !$("itusemods")) return undefined;
  const prev = (state._lastItem && state._lastItem.use) || {};
  const casts = $("itusmax") ? $("itusmax").value : "";
  const spell = $("itusspell") ? $("itusspell").value.trim() : "";
  return {
    desc: $("itusdesc") ? $("itusdesc").value : "",
    spell,
    magic: ($("itusmagic") && $("itusmagic").value) || prev.magic || "CastOnUse",
    cast_max: casts,
    cast_limit: (casts && casts !== "-1") ? "Limited" : (prev.cast_limit || "Unlimited"),
    noncombat: ($("itusnc") && $("itusnc").checked) ? "1" : "0",
    modifiers: readMods("itusemods"),
  };
}

function wireModList(box, pick, plus) {
  if (!box) return;
  box.onclick = (ev) => {
    const btn = ev.target.closest(".itmoddel");
    if (btn && btn.closest(".itemmod")) btn.closest(".itemmod").remove();
  };
  box.onchange = (ev) => {
    if (!ev.target.classList.contains("itmodname")) return;
    const rec = (state.itemModifiers || []).find((m) => m.name === ev.target.value);
    const row = ev.target.closest(".itemmod");
    if (rec && row) {
      const how = row.querySelector(".itmodhow");
      const val = row.querySelector(".itmodval");
      if (how) how.value = rec.modify;
      if (val) val.value = rec.value;
    }
  };
  if (plus) {
    plus.onclick = () => {
      const name = pick ? pick.value : "";
      if (!name) return;
      const rec = (state.itemModifiers || []).find((m) => m.name === name)
        || { name, modify: "Value", value: "1" };
      box.insertAdjacentHTML("beforeend", bonusRowHtml(rec));
    };
  }
}

function wireBonusEditor() {
  wireModList($("itmods"), $("itmodadd"), $("itmodplus"));
  wireModList($("itusemods"), $("ituseadd"), $("ituseplus"));
}

function meshLabel(id) {
  const all = [].concat(
    (state._gear && state._gear.weapons) || [],
    (state._gear && state._gear.shields) || []);
  const hit = all.find((g) => g.id === id);
  return hit ? hit.name : id;
}

function wireItemPanel() {
  const kindSel = $("itemkind");
  const pick = $("itempick");
  const search = $("itemq");
  const form = $("itemform");
  if (!kindSel || !pick || !form) return;

  const loadList = async () => {
    const p = new URLSearchParams({ q: search.value || "" });
    if (kindSel.value) p.set("kind", kindSel.value);
    try {
      const doc = await api("/api/items?" + p.toString());
      if (doc.modifiers && doc.modifiers.length) state.itemModifiers = doc.modifiers;
      if (doc.icons && doc.icons.length) state.itemIcons = doc.icons;
      if (doc.kind_groups && doc.kind_groups.length) {
        fillKindGroups(kindSel, doc.kind_groups, kindSel.value);
      }
      const items = doc.items || [];
      const cur = state.itemName;
      pick.innerHTML = items.map((it) =>
        `<option value="${esc(it.name)}"${it.name === cur ? " selected" : ""}>${esc(it.label)} (${esc(it.quality || it.subcategory)})</option>`
      ).join("");
      if (!items.length) {
        form.innerHTML = `<p class="note">No items in this filter.</p>`;
        return;
      }
      if (!cur || !items.some((it) => it.name === cur)) {
        state.itemName = items[0].name;
        pick.value = state.itemName;
      }
      await loadItem(state.itemName);
    } catch (e) {
      form.innerHTML = `<p class="note">Could not load items: ${esc(e.message)}</p>`;
    }
  };

  const loadItem = async (name) => {
    if (!name) return;
    state.itemName = name;
    state._lastItem = null;
    let it;
    try {
      it = await api("/api/items/item?name=" + encodeURIComponent(name));
    } catch (e) {
      form.innerHTML = `<p class="note">${esc(e.message)}</p>`;
      return;
    }
    const dmg = it.kind === "weapon";
    const quals = (it.qualities || []).map((q) =>
      `<option${q === it.quality ? " selected" : ""}>${esc(q)}</option>`).join("");
    if (it.modifiers && it.modifiers.length) state.itemModifiers = it.modifiers;
    const ready = it.ready || { desc: "", modifiers: [] };
    const use = it.use || { desc: "", modifiers: [], spell: "" };
    const bonusRows = (ready.modifiers || []).map((m) => bonusRowHtml(m)).join("");
    const useRows = (use.modifiers || []).map((m) => bonusRowHtml(m)).join("");
    const addOpts = modifierOptions("");
    let fx = "";
    if (it.edit_ready) {
      fx += `<div class="itemfx">
      <h4>Bonuses when worn</h4>
      <p class="note">Any worn item can take these. Ratio 125 is +25% of the live stat. A name the exe does not know becomes an attack bonus.</p>
      <label>Summary <textarea id="itfxdesc" rows="2">${esc(ready.desc || "")}</textarea></label>
      <div id="itmods">${bonusRows}</div>
      <div class="itemmodadd">
        <select id="itmodadd">${addOpts}</select>
        <button type="button" id="itmodplus">Add bonus</button>
      </div>
    </div>`;
    }
    if (it.edit_use) {
      const useNote = {
        potion: "Drink, oil, resin, or grease. Spell names are MagicResult tokens.",
        scroll: "Reading this casts or teaches. Spell names are MagicResult tokens.",
        wand: "A held cast. Spell names are MagicResult tokens.",
        book: "Study. Spell names are MagicResult tokens.",
        recipe: "Learn this formula at the bench.",
        amulet: "Some necklaces also fire a Use cast.",
      }[it.kind] || "Spell names are MagicResult tokens. Leave the spell blank for modifier-only uses such as resins.";
      const casts = (use.cast_max != null && use.cast_max !== "") ? use.cast_max : "";
      const ncOn = String(use.noncombat) === "1";
      fx += `<div class="itemfx">
      <h4>On use</h4>
      <p class="note">${esc(useNote)}</p>
      <label>Summary <textarea id="itusdesc" rows="2">${esc(use.desc || "")}</textarea></label>
      <div class="itemrow">
        <label>Spell <input id="itusspell" value="${esc(use.spell || "")}"></label>
        <label>Magic <select id="itusmagic">
          ${["CastOnUse", "WhenWearing", "WhenRead"].map((m) =>
            `<option${m === (use.magic || "CastOnUse") ? " selected" : ""}>${m}</option>`
          ).join("")}
        </select></label>
      </div>
      <div class="itemrow">
        <label>Casts <input id="itusmax" type="number" value="${esc(casts)}"></label>
        <label class="small muted"><input type="checkbox" id="itusnc"${ncOn ? " checked" : ""}> usable on the map</label>
      </div>
      <div id="itusemods">${useRows}</div>
      <div class="itemmodadd">
        <select id="ituseadd">${addOpts}</select>
        <button type="button" id="ituseplus">Add use bonus</button>
      </div>
    </div>`;
    }
    const pv = it.preview || {};
    const curMesh = pv.gear || (pv.kind === "shield" ? state.shield : state.weapon) || "";
    const meshes = pv.gears || [];
    if (pv.kind === "armor") state._armorLookCode = null;
    const lookSlots = armorSlots(pv);
    const primarySlot = lookSlots[0] || pv.slot;
    if (pv.kind === "armor") syncArmorKit(it);
    const looks = armorLooks(primarySlot);
    const curLook = (primarySlot && state.kit && state.kit[primarySlot] != null)
      ? state.kit[primarySlot] : 0;
    let previewBits = "";
    if (it.preview_3d) {
      if (meshes.length) {
        previewBits += `<label>3D mesh <select id="itmesh">${meshes.map((id) =>
          `<option value="${esc(id)}"${id === curMesh ? " selected" : ""}>${esc(meshLabel(id))}</option>`
        ).join("")}</select></label>`;
        if (pv.kind === "shield") {
          previewBits += `<p class="note">Three skins ship in Chars.t3d: wood, rune, and gold. Pixel art below shows all three.</p>`;
        }
      } else if (pv.kind === "ring" || pv.kind === "amulet") {
        previewBits += `<p class="note">No 3D mesh. The inventory paper-doll picture is hung on this character's ${pv.kind === "amulet" ? "neck" : "hands"}.</p>`;
      } else if (pv.kind === "weapon" || pv.kind === "shield" || pv.kind === "wand") {
        previewBits += `<p class="note">No 3D prop is mapped for this row — stats only.</p>`;
      }
      if (pv.kind === "armor") {
        previewBits += `<label id="itlookwrap">Preview look on ${esc(state.character || "this character")}
          <select id="itlook">${looks.map((o) =>
            `<option value="${o.i}"${o.i === curLook ? " selected" : ""}>${esc(o.label)}</option>`
          ).join("")}</select></label>
          <p class="note" id="itlookhint"${looks.length ? " hidden" : ""}>This character has no ${esc(pv.slot || "armor")} artwork to swap.</p>`;
      }
      const canScale = !!(meshes.length || (pv.kind === "armor" && (looks.length || pv.slot)));
      const sc = it.mesh_scale || state.itemScale || { length: 1, width: 1 };
      const ln = (+sc.length || 1).toFixed(2);
      const wd = (+sc.width || 1).toFixed(2);
      state.itemScale = { length: +ln, width: +wd };
      if (canScale) {
        previewBits += `<div class="itemmesh">
          <h4>Mesh size</h4>
          <p class="note">Length is the long axis. Width is girth. The grip stays in the hand. Pixel art is under the model.</p>
          <label class="pslider">Length
            <input id="itlen" type="range" min="0.25" max="3" step="0.01" value="${ln}">
            <span class="cval">${ln}</span>
          </label>
          <label class="pslider">Width
            <input id="itwid" type="range" min="0.25" max="3" step="0.01" value="${wd}">
            <span class="cval">${wd}</span>
          </label>
        </div>`;
      }
    } else {
      previewBits = `<p class="note">${esc(ITEM_KIND_HINTS[it.kind] || "No 3D mesh. Edit the catalog fields.")}</p>`;
    }
    const users = it.users || {};
    const userClasses = users.classes || [];
    const userParty = users.party || [];
    let userBits = "";
    if (userClasses.length) {
      const party = userParty.length ? userParty.join(", ") : "";
      userBits = `<div class="itemusers">
        <h4>Who can equip</h4>
        <p>Users : ${esc(userClasses.join(", "))}</p>
        ${party ? `<p class="small muted">${esc(party)}</p>` : ""}
        <p class="note">Same list the inventory shows. It comes from the item's family, not a separate field.</p>
      </div>`;
    }
    const slots = (it.slots || []).slice();
    if (it.active && slots.indexOf(it.active) < 0) slots.unshift(it.active);
    const slotOpts = slots.map((s) =>
      `<option${s === (it.active || "") ? " selected" : ""}>${esc(s)}</option>`).join("");
    let uidNote = `UniqueID ${esc(it.unique_id || "—")}`;
    if (String(it.unique_id) === "0") uidNote += " — the gold purse";
    if (String(it.unique_id) === "223") uidNote += " — the lockpick the lock screen looks for";
    if (String(it.unique_id) === "999") uidNote += " — creature / drop skip";
    const icon = it.icon && it.icon.key ? it.icon : null;
    const iconPick = (state.itemIcons || []).map((ic) =>
      `<option value="${esc(ic.key)}"${icon && ic.key === icon.key ? " selected" : ""}>${esc(ic.name)}</option>`
    ).join("");
    const dollNote = (it.paper_doll && it.paper_doll.length)
      ? " Also drawn on the inventory paper doll (not the 3D mesh)."
      : "";
    const iconBits = `<div class="itemfx itemicon">
      <h4>Inventory icon</h4>
      ${icon ? `<div class="fxgallery">
        <button type="button" class="fxthumb" id="iticonthumb">
          <img src="/api/preview?key=${encodeURIComponent(icon.key)}&t=${Date.now()}" alt="${esc(icon.name)}">
          <span>${esc(icon.name)}</span>
        </button>
      </div>
      <p class="note">Bag picture. UniqueID ${esc(it.unique_id)} is cell ${esc(icon.cell)} of sInventoryItem.${dollNote}</p>
      <label>Replace with <select id="iticonpick">${iconPick}</select></label>
      <div class="creator-tools">
        <button type="button" id="iticoncopy"${state.mod ? "" : " disabled"}>Use this icon</button>
      </div>` : `<p class="note">No bag picture for UniqueID ${esc(it.unique_id)}.</p>`}
    </div>`;
    form.innerHTML = `
      <p class="small muted">${esc(it.kind)} · ${esc(it.category || it.subcategory)} · ${esc(it.subcategory)} · ${esc(it.classification)}</p>
      ${userBits}
      ${iconBits}
      ${previewBits}
      <label>Assessed name <input id="itas" value="${esc(it.as_tag)}"></label>
      <label>Unassessed name <input id="itua" value="${esc(it.ua_tag)}"></label>
      <label>Description <textarea id="itdesc">${esc(it.description)}</textarea></label>
      <div class="itemrow">
        <label>Quality <select id="itqual">${quals}</select></label>
        <label>Price <input id="itprice" type="number" min="0" value="${esc(it.price)}"></label>
      </div>
      <div class="itemrow">
        <label>Weight <input id="itenc" type="number" min="0" step="0.05" value="${esc(it.encumbrance)}"></label>
        ${dmg ? `<label>Damage
          <span style="display:flex;gap:6px">
            <input id="itdmin" type="number" min="0" value="${it.damage_min != null ? it.damage_min : 1}">
            <input id="itdmax" type="number" min="0" value="${it.damage_max != null ? it.damage_max : 2}">
          </span></label>` : `<span></span>`}
      </div>
      <div class="itemrow">
        <label>Slot <select id="itslot">${slotOpts}</select></label>
        <label class="small muted"><input type="checkbox" id="itagg"${it.aggregate ? " checked" : ""}> stack</label>
      </div>
      <p class="small muted">${uidNote}</p>
      ${fx}
      <div class="creator-tools" style="margin-top:10px">
        <button type="button" class="primary" id="saveitem"${state.mod ? "" : " disabled"}>Save item</button>
      </div>`;
    const save = $("saveitem");
    if (save) save.onclick = () => saveItem(it.name);
    wireBonusEditor();
    if ($("itmesh")) $("itmesh").onchange = () => { applyItemPreview(it); loadItemArt(it); };
    if ($("itlook")) $("itlook").onchange = () => {
      const opt = $("itlook").selectedOptions[0];
      applyItemPreview(it, lookCode(opt && opt.textContent));
      loadItemArt(it);
    };
    let timer = 0;
    ["itlen", "itwid"].forEach((id) => {
      const sl = $(id);
      if (!sl) return;
      sl.oninput = () => {
        const label = sl.parentElement && sl.parentElement.querySelector(".cval");
        if (label) label.textContent = (+sl.value).toFixed(2);
        readItemScale();
        clearTimeout(timer);
        timer = setTimeout(() => state._remount3d && state._remount3d(), 80);
      };
    });
    state._lastItem = it;
    state._reloadItemArt = loadItemArt;
    const studio = document.querySelector(".itemstudio");
    if (studio) studio.classList.toggle("no3d", !it.preview_3d);
    if ($("creator")) $("creator").hidden = false;
    if ($("iticonthumb")) $("iticonthumb").onclick = () => loadItemArt(it);
    if ($("iticoncopy")) $("iticoncopy").onclick = () => copyItemIcon(it);
    loadItemArt(it);
    await applyItemPreview(it);
  };

  const saveItem = async (name) => {
    const fields = {
      AS_Tag: $("itas") ? $("itas").value : "",
      UA_Tag: $("itua") ? $("itua").value : "",
      Description: $("itdesc") ? $("itdesc").value : "",
      Quality_Original: $("itqual") ? $("itqual").value : "",
      Price: $("itprice") ? $("itprice").value : "",
      Encumbrance: $("itenc") ? $("itenc").value : "",
    };
    if ($("itdmin")) {
      fields.Weapon_Damage_min = $("itdmin").value;
      fields.Weapon_Damage_max = $("itdmax").value;
    }
    if ($("itslot")) fields.Location_Active = $("itslot").value;
    if ($("itagg")) fields.Aggregate = $("itagg").checked ? "True" : "False";
    try {
      const r = await api("/api/items/item", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name, fields,
          ready_effect: readReadyEffect(),
          use_effect: readUseEffect(),
          mesh_scale: readItemScale(),
        }),
      });
      toast("Saved " + name + " into the mod.");
      await refreshMod();
      await loadItem(r.item ? r.item.name : name);
    } catch (e) {
      toast("Could not save item: " + e.message, true);
    }
  };

  kindSel.onchange = () => { state.itemName = ""; loadList(); };
  search.oninput = () => { clearTimeout(search._t); search._t = setTimeout(loadList, 180); };
  pick.onchange = () => loadItem(pick.value);
  state._reloadItems = loadList;
  loadList().then(() => consumeItemJump());
}

async function consumeItemJump() {
  const jump = window.rtkJump;
  if (!jump || jump.kind !== "item") return;
  window.rtkJump = null;
  if (jump.itemKind && $("itemkind")) $("itemkind").value = jump.itemKind;
  if ($("itemq")) $("itemq").value = "";
  state.itemName = jump.name;
  if (state._reloadItems) await state._reloadItems();
}

function paneItemPreview() {
  return `
    <div class="itemstudio-preview">
      <div class="animbar">
        <label>character <select id="charpick"></select></label>
        <label>animation <select id="animpick"></select></label>
        <label class="small muted"><input type="checkbox" id="sheathed"> sheathed</label>
        <button id="play3d">Pause</button>
        <input type="range" id="scrub" min="0" max="0" value="0">
        <span id="framehint" class="small muted">0 / 0</span>
        <label class="small muted"><input type="checkbox" id="showbones"> joints</label>
        <label class="small muted"><input type="checkbox" id="showwire"> wireframe</label>
        <label class="small muted"><input type="checkbox" id="showcol"> collision</label>
        <label>bg <input type="color" id="bgcolor" value="${esc(state.bgColor || "#0d0e11")}"></label>
        <label>scene <select id="bgscene"></select></label>
        <label>view <select id="bgview"></select></label>
      </div>
      <canvas id="view3d"></canvas>
      <p class="note">Switch character to see this item on any model in the game.</p>
    </div>`;
}

function fillKindGroups(sel, groups, current) {
  if (!sel || !(groups || []).length) return;
  const cur = current || sel.value || "weapon";
  sel.innerHTML = groups.map((g) =>
    `<optgroup label="${esc(g.label)}">${(g.kinds || []).map((k) =>
      `<option value="${esc(k.id)}"${k.id === cur ? " selected" : ""}>${esc(k.label)} (${k.count})</option>`
    ).join("")}</optgroup>`
  ).join("");
}

const ITEM_KIND_HINTS = {
  weapon: "Swung, shot, or a creature attack.",
  shield: "Three skins in Chars.t3d: wood, rune, and gold.",
  armor: "Worn leather, chain, or plate.",
  ring: "Finger slot. Paper-doll rings hang on this character's hands.",
  amulet: "Neck slot. The paper-doll necklace hangs on this character's neck.",
  wand: "Held in the hand. Chars.t3d has one wand mesh.",
  potion: "Previewed as the handheld flask prop.",
  scroll: "A cast or a permanent path bonus.",
  wand: "A held cast.",
  book: "Path books and Golden Grimoire volumes.",
  recipe: "A formula scroll for the alchemy bench.",
  potion: "A drink, resin, oil, grease, or the catalyst.",
  reagent: "Alchemy ingredients. Most are stacks.",
  tool: "Brewing bench gear.",
  money: "Gold and cash gems. UniqueID 0 is the coin purse.",
  gem: "Plot stones and flawed gems. Not the cash gems.",
  key: "Lock tokens. The inventory Users line lists Thief.",
  picks: "The lock screen looks for UniqueID 223.",
  document: "Plot papers.",
};

function markStudio(which) {
  document.querySelectorAll(".studioswitch button").forEach((b) => {
    b.classList.toggle("on", b.id === which);
  });
}

function openAssets() {
  markStudio("openassets");
  const c = state.counts || { total: 0, by_kind: {}, by_source: {} };
  const total = c.total || 0;
  $("detail").innerHTML = `
    <div class="assetstudio">
      <div class="assetstudio-side">
        <div class="filters">
          <input id="q" type="search" placeholder="Search ${total.toLocaleString()} assets&hellip;"
                 value="${esc(state.assetQ || "")}" autocomplete="off">
          <label class="small muted">look in
            <select id="scope">
              <option value="files">Files</option>
              <option value="records">Records</option>
              <option value="character">Characters</option>
              <option value="item">Items</option>
              <option value="dialog">Dialog</option>
              <option value="scene">Scenes</option>
              <option value="model">Models</option>
              <option value="shop">Shops</option>
              <option value="binary">Text bytes / hex</option>
            </select>
          </label>
          <div class="row" id="filefilters">
            <select id="kind"><option value="">any kind</option></select>
            <select id="source"><option value="">any source</option></select>
          </div>
          <div id="findreplacebox" class="hidden">
            <input id="findrepl" placeholder="Replace with…">
            <button type="button" id="findreplace">Replace text fields</button>
            <p class="note">MenuText, JournalText, item tags, scene descriptions, shop cities, and nationality. Names stay put. One undo step.</p>
          </div>
        </div>
        <div id="count" class="muted small"></div>
        <ul id="list"></ul>
        <button id="more" class="hidden">Load more</button>
      </div>
      <div id="assetpane" class="assetstudio-pane">
        <div class="empty"><p>Pick an asset from the list.</p></div>
      </div>
    </div>`;
  const kind = $("kind");
  const source = $("source");
  for (const [k, v] of Object.entries(c.by_kind || {})) {
    kind.add(new Option(`${k} (${v.toLocaleString()})`, k));
  }
  for (const [k, v] of Object.entries(c.by_source || {})) {
    source.add(new Option(`${k} (${v.toLocaleString()})`, k));
  }
  if (state.assetKind) kind.value = state.assetKind;
  if (state.assetSource) source.value = state.assetSource;
  if ($("scope")) $("scope").value = state.assetScope || "files";
  toggleAssetScope();
  let timer;
  $("q").oninput = () => { clearTimeout(timer); timer = setTimeout(() => loadList(false), 180); };
  kind.onchange = source.onchange = () => loadList(false);
  $("scope").onchange = () => { toggleAssetScope(); loadList(false); };
  if ($("findreplace")) $("findreplace").onclick = replaceRecordText;
  $("more").onclick = () => loadList(true);
  loadList(false).then(() => {
    if (state.key && assetScope() === "files") select(state.key);
  });
}

function openItems() {
  markStudio("openitems");
  $("detail").innerHTML = `
    <h2>Item editor</h2>
    <div class="facts"><span>Every family in <code>MagicInvItem.txt</code>.
      Bag icons come from <code>sInventoryItem</code> (UniqueID is the
      cell). Wands and potions hang on the 3D model; rings and amulets
      use the inventory paper-doll picture on the neck or hands.
      Saves go into the mod, never the install.</span></div>
    <div class="itemstudio">
      <div class="itemstudio-list">
        <label>kind <select id="itemkind">
          <option value="weapon">Weapons</option>
          <option value="shield">Shields</option>
          <option value="armor">Armor</option>
          <option value="ring">Rings</option>
          <option value="amulet">Amulets</option>
        </select></label>
        <input id="itemq" type="search" placeholder="Search items&hellip;" autocomplete="off">
        <select id="itempick" size="18"></select>
      </div>
      ${paneItemPreview()}
      <div class="itemstudio-form">
        <div id="itemform"><p class="note">Pick an item.</p></div>
      </div>
    </div>
    <div id="creator" class="creator">
      <p class="note">Pick an item to edit its pixel art.</p>
    </div>`;
  wireItemCreator();
  wire3d({ asset: { kind: "rig" }, mode: "item" });
  wireItemPanel();
}

function wireItemCreator() {
  if (!window.RTKCreator || !$("creator")) return;
  RTKCreator.attach({
    el: $("creator"),
    panel: () => null,
    canEdit: !!state.mod,
    getContext: () => ({
      character: state.character,
      kit: state.kit || {},
      regions: state.regions,
    }),
    setRegions: () => {},
    remount: () => state._remount3d && state._remount3d(),
    toast,
    api,
    refreshMod,
  });
}

async function copyItemIcon(it) {
  const icon = it && it.icon;
  const src = $("iticonpick") ? $("iticonpick").value : "";
  if (!icon || !icon.key) {
    toast("This row has no bag icon to replace.", true);
    return;
  }
  if (!src || src === icon.key) {
    toast("Already using " + icon.name);
    return;
  }
  try {
    const doc = await api("/api/character/pixels?key=" + encodeURIComponent(src));
    await api("/api/character/sheet", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        key: icon.key,
        width: doc.width,
        height: doc.height,
        pixels: doc.pixels,
        palette: doc.palette,
      }),
    });
    toast("Copied " + src.split("_").pop() + " onto " + icon.name);
    await refreshMod();
    if (state._reloadItems) await state._reloadItems();
  } catch (e) {
    toast("Could not copy icon: " + e.message, true);
  }
}

async function loadItemArt(it) {
  const box = $("creator");
  if (!box) return;
  if (!window.RTKCreator) {
    box.innerHTML = `<p class="note">Pixel editor script did not load. Hard-refresh the page.</p>`;
    return;
  }
  if (!RTKCreator._opts) wireItemCreator();
  if (!RTKCreator._opts) {
    box.innerHTML = `<p class="note">Pixel editor did not attach.</p>`;
    return;
  }
  const pv = (it && it.preview) || {};
  const mesh = $("itmesh") ? $("itmesh").value : (pv.gear || "");
  const q = new URLSearchParams({ name: state.character || "James" });
  if (it && it.name) q.set("item", it.name);
  if (pv.kind === "armor" && (pv.slot || (pv.slots && pv.slots.length))) {
    const slots = syncArmorKit(it);
    const wanted = slots.length ? slots : armorSlots(pv);
    q.set("slot", wanted.join(","));
    if (it.subcategory) q.set("sub", it.subcategory);
    if (state._armorLookCode != null) q.set("look", String(state._armorLookCode));
    wanted.forEach((slot) => {
      if (state.kit[slot] != null && state.kit[slot] !== "") {
        q.set("armor_" + slot, String(state.kit[slot]));
      }
    });
  } else if (mesh || (pv.gears && pv.gears.length)) {
    const gears = (pv.kind === "shield" && pv.gears && pv.gears.length)
      ? pv.gears : [mesh];
    q.set("gear", gears.filter(Boolean).join(","));
  }
  try {
    const doc = await api("/api/items/art?" + q.toString());
    if (!(doc.sheets || []).length) {
      $("creator").innerHTML = `<p class="note">No bag icon or pixel sheets for this row.</p>`;
      return;
    }
    await RTKCreator.loadArt(doc, { title: (it && (it.label || it.as_tag || it.name)) || "Item" });
  } catch (e) {
    $("creator").innerHTML = `<p class="note">Could not load pixel art: ${esc(e.message)}</p>`;
  }
}

function openCharacters() {
  markStudio("openchars");
  $("detail").innerHTML = `
    <h2>Character creator</h2>
    <div class="facts"><span>Click a body part on the model. Length and width
      sliders are on the left; Edit sprites opens that part&rsquo;s
      pixel art. Saves go into the mod, never the install.</span></div>
    ${pane3d({ asset: { kind: "rig" } })}`;
  wire3d({ asset: { kind: "rig" } });
}

async function wire3d(meta) {
  const itemMode = meta && meta.mode === "item";
  state._3dgen = (state._3dgen || 0) + 1;
  const gen = state._3dgen;
  const canvas = $("view3d");
  if (!canvas || typeof RTKViewer === "undefined" || typeof THREE === "undefined") {
    toast("3D viewer needs the local three.js files and a live studio server.", true);
    return;
  }
  if (!state.characters.length) {
    try {
      const doc = await api("/api/character");
      state.characters = (doc.characters || []).filter((c) => c.has_rig);
      if (!state.character) state.character = doc.default || "James";
    } catch (e) {
      toast("Could not list characters: " + e.message, true);
      return;
    }
  }
  if (!state.backdrops) {
    try {
      const doc = await api("/api/backdrops");
      state.backdrops = doc.scenes || [];
    } catch (e) {
      state.backdrops = [];
      toast("Could not list backdrops: " + e.message, true);
    }
  }
  const kind = meta.asset && meta.asset.kind;
  if (kind === "rig") {
    const hit = state.characters.find((c) =>
      meta.asset.name && c.adf.toLowerCase() === meta.asset.name.toLowerCase());
    if (hit) {
      if (hit.name !== state.character) state.anim = null;
      state.character = hit.name;
    }
  }
  if (kind === "anim") state.anim = meta.key;

  const charSel = $("charpick");
  charSel.innerHTML = state.characters.map((c) =>
    `<option value="${esc(c.name)}"${c.name === state.character ? " selected" : ""}>${esc(c.name)}</option>`
  ).join("");

  const loadAnims = async () => {
    toast("Loading compatible animations\u2026");
    const doc = await api("/api/character/anims?name=" + encodeURIComponent(state.character));
    const anims = doc.anims || [];
    if (state.anim && !anims.some((a) => a.key === state.anim)) {
      state.anim = null;
    }
    if (state.anim == null) {
      if (doc.conversation_bind) {
        const prefer = anims.find((a) => /TK0005M\.trk$/i.test(a.key));
        state.anim = prefer ? prefer.key : "";
      } else {
        state.anim = "";
      }
    }
    $("animpick").innerHTML =
      `<option value=""${state.anim ? "" : " selected"}>Rest pose</option>` +
      anims.map((a) =>
        `<option value="${esc(a.key)}"${a.key === state.anim ? " selected" : ""}>${esc(a.name)} (${a.frames}f)</option>`
      ).join("");
    return anims;
  };

  const fillJoints = (scene) => {
    if (!$("jointpick")) return;
    const names = scene.nodes.map((n) => n.joint).filter(Boolean);
    $("jointpick").innerHTML = names.map((n) => `<option>${esc(n)}</option>`).join("");
  };

  const showTRS = () => {
    if (!$("rx")) return;
    const trs = RTKViewer.currentTRS();
    if (!trs) return;
    $("rx").value = trs.e[0].toFixed(2);
    $("ry").value = trs.e[1].toFixed(2);
    $("rz").value = trs.e[2].toFixed(2);
    $("tx").value = trs.t[0].toFixed(4);
    $("ty").value = trs.t[1].toFixed(4);
    $("tz").value = trs.t[2].toFixed(4);
  };

  const mount = async () => {
    const gen = state._3dgen;
    try {
      const scene = await RTKViewer.mount(canvas, {
        character: state.character,
        anim: state.anim,
        kit: state.kit || {},
        regions: state.regions || null,
        pickRegion: state.pickRegion || null,
        weapon: state.weapon || "",
        shield: state.shield || "",
        sheathed: !!state.sheathed,
        itemScale: itemMode ? (state.itemScale || null) : null,
        itemSlot: itemMode ? (state.itemSlot || "") : "",
        overlays: state.overlays || [],
        bgColor: state.bgColor || "#0d0e11",
        backdrop: state.backdrop || "",
        bust: Date.now(),
        showBones: $("showbones") && $("showbones").checked,
        showWire: $("showwire") && $("showwire").checked,
        showCollision: $("showcol") && $("showcol").checked,
        onPick: (hit) => {
          state.pickRegion = hit && hit.region;
          state.pickJoint = (hit && hit.joint) || "";
          const panel = $("partpanel");
          if (panel) {
            panel.querySelectorAll(".partblock").forEach((b) => {
              b.classList.toggle("on", !!(hit && b.dataset.region === hit.region));
            });
          }
          if (!itemMode && window.RTKCreator) RTKCreator.selectPart(hit);
          if (hit && hit.joint && $("jointpick")) {
            $("jointpick").value = hit.joint;
            RTKViewer.selectJoint(hit.joint);
            try { showTRS(); } catch (e) { /* rest pose has no TRS */ }
          }
        },
        onFrame: (f, n) => {
          $("scrub").max = Math.max(0, n - 1);
          $("scrub").value = f;
          $("framehint").textContent = f + " / " + n;
          if (!$("play3d").dataset.playing) return;
          showTRS();
        },
      });
      $("play3d").dataset.playing = "1";
      $("play3d").textContent = "Pause";
      if (scene.anim) {
        $("scrub").max = Math.max(0, scene.anim.frames - 1);
        $("framehint").textContent = "0 / " + scene.anim.frames;
        if (!state.anim) state.anim = scene.anim.key;
      }
      if (state._3dgen !== gen) return;
      fillGear(scene);
      fillJoints(scene);
      RTKViewer.resize();
      if (namesFirst(scene)) RTKViewer.selectJoint(namesFirst(scene));
      showTRS();
    } catch (e) {
      if (state._3dgen === gen) toast("Could not load 3D scene: " + e.message, true);
    }
  };

  const namesFirst = (scene) => {
    const n = scene.nodes.find((x) => x.joint);
    return n ? n.joint : null;
  };

  const fillGear = (scene) => {
    const g = (scene && scene.gear) || { slots: [], weapons: [], shields: [] };
    state._gear = g;
    const slots = g.slots || [];
    state.kit = state.kit || {};
    if (itemMode && state._lastItem && state._lastItem.preview
        && state._lastItem.preview.kind === "armor") {
      const before = kitSnapshot(state._lastItem);
      syncArmorKit(state._lastItem);
      refreshItlook(state._lastItem);
      if (before !== kitSnapshot(state._lastItem)) {
        if (state._reloadItemArt) state._reloadItemArt(state._lastItem);
        if (!state._armorLookMount && state._remount3d) {
          state._armorLookMount = true;
          Promise.resolve().then(() => {
            state._armorLookMount = false;
            state._remount3d();
          });
        }
      }
    }
    if (!$("armorslots")) return;
    $("armorslots").innerHTML = slots.map((s) => {
      if (state.kit[s.id] == null || !s.options.some((o) => o.i === state.kit[s.id])) {
        state.kit[s.id] = 0;
      }
      const opts = (s.options || []).map((o) =>
        `<option value="${o.i}"${o.i === state.kit[s.id] ? " selected" : ""}>${esc(o.label)}</option>`
      ).join("");
      return `<label>${esc(s.label)} <select data-slot="${esc(s.id)}">${opts}</select></label>`;
    }).join("");
    $("armorslots").querySelectorAll("select").forEach((sel) => {
      sel.onchange = async () => {
        state.kit = state.kit || {};
        state.kit[sel.dataset.slot] = +sel.value || 0;
        await mount();
        if (window.RTKCreator) RTKCreator.reload();
      };
    });
    const wnone = `<option value="">none</option>`;
    const weapons = g.weapons || [];
    if (!itemMode && state.weapon && !weapons.some((w) => w.id === state.weapon)) state.weapon = "";
    if ($("weaponpick")) {
      $("weaponpick").innerHTML = wnone + weapons.map((w) =>
        `<option value="${esc(w.id)}"${w.id === state.weapon ? " selected" : ""}>${esc(w.name)}</option>`
      ).join("");
    }
    const shields = g.shields || [];
    if (!itemMode && state.shield && !shields.some((s) => s.id === state.shield)) state.shield = "";
    if ($("shieldpick")) {
      $("shieldpick").innerHTML = wnone + shields.map((s) =>
        `<option value="${esc(s.id)}"${s.id === state.shield ? " selected" : ""}>${esc(s.name)}</option>`
      ).join("");
    }
    if ($("sheathed")) $("sheathed").checked = !!state.sheathed;
  };

  const fillBackdropSelects = () => {
    const scenes = state.backdrops || [];
    const none = `<option value="">none</option>`;
    $("bgscene").innerHTML = none + scenes.map((s) =>
      `<option value="${esc(s.id)}"${s.id === state.bgScene ? " selected" : ""}>${esc(s.label)}</option>`
    ).join("");
    const scene = scenes.find((s) => s.id === state.bgScene);
    const views = (scene && scene.views) || [];
    if (state.backdrop && !views.some((v) => v.key === state.backdrop)) state.backdrop = "";
    $("bgview").innerHTML = none + views.map((v) =>
      `<option value="${esc(v.key)}"${v.key === state.backdrop ? " selected" : ""}>${esc(v.label)}</option>`
    ).join("");
    $("bgview").disabled = !scene;
    $("bgcolor").value = state.bgColor || "#0d0e11";
  };
  fillBackdropSelects();

  charSel.onchange = async () => {
    state.character = charSel.value;
    state.regions = {
      head: { length: 1, width: 1 },
      torso: { length: 1, width: 1 },
      arms: { length: 1, width: 1 },
      legs: { length: 1, width: 1 },
    };
    state.anim = null;
    state.pickRegion = null;
    state.pickJoint = "";
    await loadAnims();
    await mount();
    if (!itemMode && window.RTKCreator) RTKCreator.reload();
    if (itemMode && state._lastItem) {
      const prefer = state._armorLookCode;
      if (state._lastItem.preview && state._lastItem.preview.kind === "armor") {
        syncArmorKit(state._lastItem, prefer);
        refreshItlook(state._lastItem);
      }
      await applyItemPreview(state._lastItem, prefer);
      if (state._reloadItemArt) await state._reloadItemArt(state._lastItem);
    }
  };
  $("animpick").onchange = async () => {
    state.anim = $("animpick").value;
    await mount();
  };
  if ($("weaponpick")) $("weaponpick").onchange = async () => {
    state.weapon = $("weaponpick").value;
    await mount();
  };
  if ($("shieldpick")) $("shieldpick").onchange = async () => {
    state.shield = $("shieldpick").value;
    await mount();
  };
  if ($("sheathed")) $("sheathed").onchange = async () => {
    state.sheathed = $("sheathed").checked;
    await mount();
  };
  $("play3d").onclick = () => {
    const on = $("play3d").dataset.playing === "1";
    RTKViewer.play(!on);
    $("play3d").dataset.playing = on ? "" : "1";
    $("play3d").textContent = on ? "Play" : "Pause";
  };
  $("scrub").oninput = () => {
    RTKViewer.play(false);
    $("play3d").dataset.playing = "";
    $("play3d").textContent = "Play";
    RTKViewer.setFrame(+$("scrub").value);
    $("framehint").textContent = $("scrub").value + " / " + ((+$("scrub").max) + 1);
    showTRS();
  };
  $("showbones").onchange = () => RTKViewer.showBones($("showbones").checked);
  if ($("showwire")) $("showwire").onchange = () => RTKViewer.showWire($("showwire").checked);
  if ($("showcol")) $("showcol").onchange = () => RTKViewer.showCollision($("showcol").checked);
  $("bgcolor").oninput = () => {
    state.bgColor = $("bgcolor").value || "#0d0e11";
    RTKViewer.applyBackground({ color: state.bgColor });
  };
  $("bgscene").onchange = () => {
    state.bgScene = $("bgscene").value;
    const scene = (state.backdrops || []).find((s) => s.id === state.bgScene);
    state.backdrop = scene && scene.views && scene.views[0] ? scene.views[0].key : "";
    fillBackdropSelects();
    RTKViewer.applyBackground({ backdrop: state.backdrop });
  };
  $("bgview").onchange = () => {
    state.backdrop = $("bgview").value;
    RTKViewer.applyBackground({ backdrop: state.backdrop });
  };
  if ($("jointpick")) $("jointpick").onchange = () => {
    RTKViewer.selectJoint($("jointpick").value);
    showTRS();
  };
  const write = () => {
    if (!$("tx") || !$("rx")) return;
    RTKViewer.writeTRS(
      [+$("tx").value, +$("ty").value, +$("tz").value],
      [+$("rx").value, +$("ry").value, +$("rz").value]);
  };
  ["rx", "ry", "rz", "tx", "ty", "tz"].forEach((id) => {
    if (!$(id)) return;
    $(id).onchange = write;
    $(id).oninput = write;
  });
  if ($("saveanim")) $("saveanim").onclick = async () => {
    try {
      const r = await api("/api/character/save", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(RTKViewer.payload()),
      });
      toast(`Saved ${r.key} (${bytes(r.bytes)}) into the mod.`);
      await refreshMod();
    } catch (e) {
      toast("Could not save animation: " + e.message, true);
    }
  };
  if ($("dupanim")) $("dupanim").onclick = async () => {
    const stem = ($("newstem").value || "TKMOD01").toUpperCase().padEnd(7).slice(0, 7);
    try {
      const r = await api("/api/character/duplicate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ anim: state.anim, stem }),
      });
      toast(`Duplicated as ${r.key} (stem ${r.stem}). ConversationTracks.tbl is unchanged — register it there if the game should play this as dialogue.`);
      state.anim = r.key;
      await refreshMod();
      await loadAnims();
      await mount();
    } catch (e) {
      toast("Could not duplicate: " + e.message, true);
    }
  };
  window.addEventListener("resize", () => RTKViewer.resize());

  state._remount3d = mount;
  if (!itemMode) wireSizePanel(mount);
  if (!itemMode && window.RTKCreator && $("creator")) {
    RTKCreator.attach({
      el: $("creator"),
      panel: () => $("partpanel"),
      canEdit: !!state.mod,
      getContext: () => ({
        character: state.character,
        kit: state.kit || {},
        regions: state.regions,
        pickRegion: state.pickRegion,
        pickJoint: state.pickJoint,
      }),
      setRegions: (regions) => { state.regions = regions; },
      remount: () => state._remount3d && state._remount3d(),
      toast,
      api,
      refreshMod,
    });
  }

  try {
    await loadAnims();
    if (state._3dgen !== gen) return;
    await mount();
    if (!itemMode && window.RTKCreator) await RTKCreator.reload();
  } catch (e) {
    if (state._3dgen === gen) toast("Could not load animations: " + e.message, true);
  }
}

function editor(meta) {
  const kind = (meta.asset && meta.asset.kind) || meta.kind || "";
  if (kind === "anim" || kind === "rig") return "";
  if (!state.mod) {
    return `<p class="note">Read-only: restart the viewer with <code>--mod DIR</code> to edit.</p>`;
  }
  const mode = meta.mode;
  if (mode === "text") {
    return `<div class="edit"><h3>Edit text</h3>
      <textarea class="editor" id="text">${esc(meta.text || "")}</textarea>
      <div class="tools" style="margin-top:8px">
        <button class="primary" id="save">Save to mod</button>
      </div>
      <p class="note">Saved back into this asset's own container format; the
         install is never written to.</p></div>`;
  }
  const accept = mode === "image" ? ".png" : mode === "audio" ? ".wav" : "*";
  const hint = mode === "image"
    ? "Upload an indexed PNG. It is encoded back to the game's format, indexed against " +
      (meta.palette ? "the palette shown above (" + esc(meta.palette) + ")." : "this asset's own palette.")
    : mode === "audio"
    ? "Upload a RIFF/WAVE file. Keep the original sample rate and channel count."
    : "Upload replacement bytes. They are stored verbatim.";
  return `<div class="edit"><h3>Replace</h3>
    <div class="tools">
      <input type="file" id="file" accept="${accept}">
      <button class="primary" id="save" disabled>Save to mod</button>
    </div>
    <p class="note">${hint}</p></div>`;
}

function wireEditor(meta) {
  const save = $("save");
  if (!save) return;
  if (meta.mode === "text") {
    save.onclick = () => store(meta.key, new Blob([$("text").value]), true);
    return;
  }
  const file = $("file");
  file.onchange = () => { save.disabled = !file.files.length; };
  // Save against the palette on screen, so what you edited is what you get.
  const pal = $("pal") ? $("pal").value : null;
  save.onclick = () => store(meta.key, file.files[0], false, pal);
}

async function store(key, blob, asText, palette) {
  const p = new URLSearchParams({ key });
  if (asText) p.set("text", "1");
  if (palette) p.set("palette", palette);
  try {
    const r = await api("/api/override?" + p, { method: "POST", body: blob });
    toast(`Saved ${key} (${bytes(r.bytes)}) into the mod.`);
    await refreshMod();
    await loadList(false);
    await select(key);
  } catch (e) {
    toast("Could not save: " + e.message, true);
  }
}

async function revert(key) {
  await api("/api/revert?key=" + encodeURIComponent(key), { method: "POST" });
  toast("Reverted " + key);
  await refreshMod();
  await loadList(false);
  await select(key);
}

// --- the mod bar ---------------------------------------------------------

function applyChrome() {
  const theme = localStorage.getItem("rtk-theme") || "dark";
  const scale = localStorage.getItem("rtk-scale") || "1";
  document.documentElement.setAttribute("data-theme", theme);
  document.documentElement.style.zoom = scale;
  if ($("uitheme")) $("uitheme").value = theme;
  if ($("uiscale")) $("uiscale").value = scale;
}

function paintHistoryButtons(mod) {
  const undo = $("histundo");
  const redo = $("histredo");
  if (undo) undo.disabled = !(mod && mod.undo);
  if (redo) redo.disabled = !(mod && mod.redo);
}

function paintHistory(doc) {
  const panel = $("histpanel");
  if (!panel) return;
  const rows = [`<button type="button" data-cursor="-1"${doc.cursor < 0 ? ' class="on"' : ""}>Original</button>`];
  (doc.entries || []).forEach((e) => {
    rows.push(`<button type="button" data-cursor="${e.i}"${e.current ? ' class="on"' : ""}>${esc(e.time || "")} ${esc(e.label || e.keys && e.keys[0] || "edit")}</button>`);
  });
  panel.innerHTML = rows.join("") || `<p class="note">No edits yet.</p>`;
  panel.querySelectorAll("button[data-cursor]").forEach((btn) => {
    btn.onclick = () => jumpHistory(Number(btn.dataset.cursor));
  });
  paintHistoryButtons({ undo: doc.can_undo, redo: doc.can_redo });
}

async function afterHistory(doc) {
  if (doc && doc.label) {
    const verb = doc.action === "redo" ? "Redid" : (doc.action === "jump" ? "History" : "Undid");
    toast(verb + " " + doc.label);
  }
  await refreshMod();
  if (doc) paintHistory(doc);
  if (document.getElementById("scenecanvas") && typeof loadSceneView === "function") {
    loadSceneView();
  }
}

async function undoHist() {
  try {
    const doc = await api("/api/history/undo", { method: "POST" });
    await afterHistory(doc);
  } catch (e) {
    toast(e.message, true);
  }
}

async function redoHist() {
  try {
    const doc = await api("/api/history/redo", { method: "POST" });
    await afterHistory(doc);
  } catch (e) {
    toast(e.message, true);
  }
}

async function jumpHistory(cursor) {
  try {
    const doc = await api("/api/history/jump", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ cursor }),
    });
    await afterHistory(doc);
  } catch (e) {
    toast(e.message, true);
  }
}

async function toggleHistory() {
  const panel = $("histpanel");
  if (!panel) return;
  if (!panel.classList.contains("hidden")) {
    panel.classList.add("hidden");
    return;
  }
  const doc = await api("/api/history");
  paintHistory(doc);
  panel.classList.remove("hidden");
}

async function refreshMod() {
  const c = await api("/api/counts");
  state.mod = c.mod;
  if (!c.mod) return;
  $("modbar").classList.remove("hidden");
  $("modname").textContent = c.mod.name + " " + c.mod.version;
  const pill = $("modcount");
  pill.textContent = c.mod.overrides + (c.mod.overrides === 1 ? " edit" : " edits");
  pill.classList.toggle("dirty", c.mod.overrides > 0);
  paintHistoryButtons(c.mod);
}

async function build() {
  $("build").disabled = true;
  toast("Building a modded copy. Copying ~900 MB, this takes a moment\u2026");
  try {
    const r = await api("/api/build", { method: "POST" });
    toast(`Built into ${r.output}\n${r.copied} files copied, ` +
          `${r.regenerated} regenerated, ${Object.keys(r.containers).length} containers rebuilt.`);
  } catch (e) {
    toast("Build failed: " + e.message, true);
  }
  $("build").disabled = false;
}

async function playGame(where) {
  const target = (where && where.chapter != null) ? where
    : (typeof sceneLaunchTarget === "function" ? sceneLaunchTarget() : {});
  const buttons = [$("play"), $("scplay")].filter(Boolean);
  buttons.forEach((b) => { b.disabled = true; });
  const whereTxt = target && target.scene != null
    ? " at chapter " + target.chapter + " scene " + target.scene
    : "";
  toast("Building the modded copy, then launching" + whereTxt + "\u2026");
  try {
    const r = await api("/api/play", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(target || {}),
    });
    toast("Launched " + r.exe + (r.args && r.args.length ? " " + r.args.join(" ") : "") +
      "\n" + (r.note || ""));
  } catch (e) {
    toast("Could not launch: " + e.message, true);
  }
  buttons.forEach((b) => { b.disabled = false; });
}

async function patch() {
  try {
    const r = await api("/api/patch", { method: "POST" });
    toast(`Patch written to ${r.patch} (${r.entries} assets, ${bytes(r.bytes)}).`);
  } catch (e) {
    toast("Export failed: " + e.message, true);
  }
}

// --- boot ----------------------------------------------------------------

async function init() {
  const c = await api("/api/counts");
  state.counts = c;
  state.palettes = c.palettes || [];
  state.mod = c.mod;
  $("summary").textContent =
    `${c.total.toLocaleString()} assets \u00b7 ` +
    Object.entries(c.by_source).map(([k, v]) => `${v.toLocaleString()} ${k}`).join(" \u00b7 ");
  applyChrome();
  await refreshMod();

  $("build").onclick = build;
  if ($("play")) $("play").onclick = playGame;
  $("patch").onclick = patch;
  if ($("histundo")) $("histundo").onclick = undoHist;
  if ($("histredo")) $("histredo").onclick = redoHist;
  if ($("histhist")) $("histhist").onclick = toggleHistory;
  if ($("uitheme")) $("uitheme").onchange = () => {
    localStorage.setItem("rtk-theme", $("uitheme").value);
    applyChrome();
  };
  if ($("uiscale")) $("uiscale").onchange = () => {
    localStorage.setItem("rtk-scale", $("uiscale").value);
    applyChrome();
  };
  document.addEventListener("keydown", (ev) => {
    const key = (ev.key || "").toLowerCase();
    if (!(ev.ctrlKey || ev.metaKey) || ev.altKey) return;
    const tag = (ev.target && ev.target.tagName) || "";
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
    if (key === "z" && !ev.shiftKey) { ev.preventDefault(); undoHist(); }
    if (key === "y" || (key === "z" && ev.shiftKey)) { ev.preventDefault(); redoHist(); }
  });
  if ($("openassets")) $("openassets").onclick = openAssets;
  if ($("openassets2")) $("openassets2").onclick = openAssets;
  if ($("openchars")) $("openchars").onclick = openCharacters;
  if ($("openchars2")) $("openchars2").onclick = openCharacters;
  if ($("openitems")) $("openitems").onclick = openItems;
  if ($("openitems2")) $("openitems2").onclick = openItems;
  const studios = [
    ["openscenes", "openScenes"], ["openscenes2", "openScenes"],
    ["openui", "openUI"], ["openui2", "openUI"],
    ["opendialog", "openDialog"], ["opendialog2", "openDialog"],
    ["opencombat", "openCombat"], ["opencombat2", "openCombat"],
    ["opentraps", "openTraps"], ["opentraps2", "openTraps"],
    ["openfx", "openFx"], ["openfx2", "openFx"],
    ["openalchemy", "openAlchemy"], ["openalchemy2", "openAlchemy"],
    ["openshops", "openShops"], ["openshops2", "openShops"],
  ];
  studios.forEach(([id, fn]) => {
    const btn = $(id);
    if (btn) btn.onclick = () => {
      markStudio(id.replace(/2$/, ""));
      window[fn] && window[fn]();
    };
  });
}

init().catch((e) => {
  $("summary").textContent = "could not reach the viewer";
  toast("Startup failed: " + e.message +
        "\nThe page has to be served by python tools/viewer.py " +
        "(http://127.0.0.1:8765/), not opened as a file.", true);
});
