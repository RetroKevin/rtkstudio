"use strict";

function el(id) {
  return document.getElementById(id);
}

function studioShell(title, note, body) {
  return `<h2>${title}</h2>
    <div class="facts"><span>${note}</span></div>
    ${body}`;
}

function layerChecks(ids) {
  return ids.map(([id, label, on]) =>
    `<label class="layerchk"><input type="checkbox" id="${id}"${on ? " checked" : ""}> ${label}</label>`
  ).join("");
}

// --- Scene studio -------------------------------------------------------

const sceneState = {
  chapter: "", scene: "", view: "", doc: null, pick: null, drag: null,
};

function openScenes() {
  if (typeof RTKViewer !== "undefined" && RTKViewer.unmount) RTKViewer.unmount();
  el("detail").innerHTML = studioShell(
    "Scene studio",
    "Chapter → scene → view. Walk-into CamPoly footprints are screen transitions; Teleport plates are exits. Drag to move, then save into the mod.",
    `<div class="studio scenestudio layout3" id="studiolayout" data-studio="openscenes">
      <div class="studio-side">
        <label>chapter <select id="scchapter"></select></label>
        <label>scene <select id="scscene"></select></label>
        <label>view <select id="scview"></select></label>
        <div class="layerbar" id="sclayers">
          ${layerChecks([
            ["lybackdrop", "backdrop", true],
            ["lydepth", "depth", true],
            ["lygrid", "walk grid", true],
            ["lyworld", "world", false],
            ["lyactors", "actors", true],
            ["lyplates", "plates", true],
            ["lytrans", "transitions", true],
            ["lyexits", "exits", true],
            ["lycombat", "combat (read-only)", true],
          ])}
        </div>
        <h3>Hierarchy</h3>
        <div id="schier" class="schier"><p class="note">Loading…</p></div>
      </div>
      <div class="split" data-edge="side" title="Drag to resize the list"></div>
      <div class="studio-stage">
        <canvas id="scenecanvas" width="640" height="480"></canvas>
        <p class="note sc-hint">Purple diamonds are Teleport exits. Warm outlines are other views you can walk into. Double-click to go there.</p>
        <div class="tools">
          <button type="button" id="scplay">Play modded game</button>
        </div>
        <p class="note">Builds the modded copy, turns the developer flag on in that copy, and launches at this chapter and scene.</p>
        <p class="note" id="scstatus">Loading scenes…</p>
      </div>
      <div class="split" data-edge="inspector" title="Drag to resize the inspector"></div>
      <div class="studio-inspector">
        <div id="scprops" class="proppanel"><p class="note">Select an object in the hierarchy or on the painting.</p></div>
      </div>
    </div>`);
  wireLayout(el("studiolayout"));
  wireSceneStudio();
}

async function wireSceneStudio() {
  let catalog;
  try {
    catalog = await api("/api/scenes");
  } catch (e) {
    el("scstatus").textContent = "Could not load scenes: " + e.message;
    return;
  }
  const chSel = el("scchapter");
  (catalog.chapters || []).forEach((ch) => {
    chSel.add(new Option("Chapter " + ch.id + " (" + ch.folder + ")", String(ch.id)));
  });
  sceneState.catalog = catalog;
  chSel.onchange = () => fillScenes();
  el("scscene").onchange = () => fillViews();
  el("scview").onchange = () => loadSceneView();
  el("sclayers").onchange = () => drawScene();
  if (el("scplay")) el("scplay").onclick = () => {
    if (typeof playGame === "function") playGame(sceneLaunchTarget());
  };
  const canvas = el("scenecanvas");
  canvas.onmousedown = onSceneDown;
  canvas.onmousemove = onSceneMove;
  canvas.onmouseup = onSceneUp;
  canvas.onmouseleave = onSceneUp;
  canvas.ondblclick = onSceneDblClick;
  fillScenes();
  const jump = window.rtkJump;
  if (jump && jump.kind === "scene") {
    window.rtkJump = null;
    if (jump.chapter != null && jump.chapter !== "") el("scchapter").value = String(jump.chapter);
    fillScenes(false);
    if (jump.scene) el("scscene").value = jump.scene;
    fillViews(false);
    if (jump.view) el("scview").value = jump.view;
    loadSceneView();
  }
}

function currentChapter() {
  const id = Number(el("scchapter").value);
  return (sceneState.catalog.chapters || []).find((c) => c.id === id);
}

function fillScenes(load) {
  const ch = currentChapter();
  const sel = el("scscene");
  sel.innerHTML = "";
  (ch && ch.scenes || []).forEach((s) => {
    sel.add(new Option(s.id + (s.desc ? " — " + s.desc.slice(0, 48) : ""), s.id));
  });
  fillViews(load);
}

function fillViews(load) {
  const ch = currentChapter();
  const sid = el("scscene").value;
  const scene = (ch && ch.scenes || []).find((s) => s.id === sid);
  const sel = el("scview");
  sel.innerHTML = "";
  (scene && scene.views || []).forEach((v) => {
    sel.add(new Option(v.id + (v.bg ? " (" + v.bg + ")" : ""), v.id));
  });
  if (load !== false) loadSceneView();
}

async function loadSceneView() {
  const ch = el("scchapter").value;
  const scene = el("scscene").value;
  const view = el("scview").value;
  if (!ch || !scene || !view) return;
  el("scstatus").textContent = "Loading " + scene + " / " + view + "…";
  try {
    sceneState.doc = await api(
      "/api/scenes/view?chapter=" + encodeURIComponent(ch) +
      "&scene=" + encodeURIComponent(scene) +
      "&view=" + encodeURIComponent(view));
    sceneState.pick = null;
    sceneState.drag = null;
    fillSceneLists();
    el("scprops").innerHTML = `<p class="note">${esc(sceneState.doc.desc || scene)}</p>`;
    await drawScene();
    const d = sceneState.doc;
    const exits = collectExits(d);
    const trans = (d.views || []).filter((v) => !v.current && (v.screen || []).length >= 2);
    el("scstatus").textContent =
      (d.backdrop ? "backdrop " + d.backdrop.name : "no backdrop") +
      (d.overlay ? " · ovx " + d.overlay.name : " · no ovx") +
      (d.mab && !d.mab.error ? " · grid " + d.mab.cols + "×" + d.mab.rows : " · no mab") +
      (d.world ? " · world " + (d.world.objects || []).length + " objects" : "") +
      " · " + (d.actors || []).length + " actors" +
      " · " + trans.length + " transitions" +
      " · " + exits.length + " exits" +
      (d.world && d.world.note ? " · " + d.world.note : "");
  } catch (e) {
    el("scstatus").textContent = e.message;
  }
}

function loadPreview(key) {
  return new Promise((resolve) => {
    if (!key) { resolve(null); return; }
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => resolve(null);
    img.src = "/api/preview?key=" + encodeURIComponent(key) + "&v=" + Date.now();
  });
}

function drawBackdrop(ctx, img) {
  // .di_ previews are stored for the 3D plane (flipY = false). Canvas
  // drawImage treats row 0 as the top, so flip them to match the game.
  ctx.save();
  ctx.translate(0, 480);
  ctx.scale(1, -1);
  ctx.drawImage(img, 0, 0, 640, 480);
  ctx.restore();
}

function tileColor(ch) {
  const code = (ch || "?").charCodeAt(0);
  if (ch === "@") return "rgba(80,180,90,0.35)";
  if (code & 0x20) return "rgba(200,60,50,0.45)";
  if (ch === "?" || ch === " ") return "rgba(40,40,48,0.25)";
  const klass = code & 0x1f;
  const h = 30 + klass * 8;
  return "hsla(" + h + ",70%,45%,0.35)";
}

function actorKey(a) {
  return [a.kind, a.group || "", a.formation || "", a.name].join("\0");
}

function pickIs(a) {
  const p = sceneState.pick;
  return p && p.type === "actor" && actorKey(p.actor) === actorKey(a);
}

function collectExits(d) {
  const out = [];
  (d.actors || []).forEach((a) => {
    const exits = a.exits || [];
    if (exits.length) {
      exits.forEach((ex, i) => out.push({ actor: a, exit: ex, index: i }));
    } else if (a.is_exit) {
      out.push({ actor: a, exit: null, index: 0 });
    }
  });
  (d.scene_exits || []).forEach((ex, i) => {
    out.push({ actor: null, exit: ex, index: i, sceneScript: true });
  });
  return out;
}

function actorToken(a) {
  const list = (sceneState.doc && sceneState.doc.actors) || [];
  const i = list.indexOf(a);
  return "actor:" + (i < 0 ? "" : i);
}

function pickToken(p) {
  if (!p) return "";
  if (p.type === "view" && p.view) return "view:" + p.view.id;
  if (p.type === "actor" && p.actor) return actorToken(p.actor);
  if (p.type === "scene-exit") return "sexit:" + (p.index || 0);
  return "";
}

function hierGroup(title, buttons) {
  if (!buttons) return "";
  return `<details open><summary>${esc(title)}</summary>${buttons}</details>`;
}

function hierButton(token, label) {
  const on = pickToken(sceneState.pick) === token ? " on" : "";
  return `<button type="button" class="${on.trim()}" data-pick="${esc(token)}">${esc(label)}</button>`;
}

function fillSceneLists() {
  const d = sceneState.doc;
  const box = el("schier");
  if (!box || !d) return;
  const views = (d.views || []).map((v) => {
    const bits = [v.id];
    if (v.current) bits.push("current");
    else if (v.linked) bits.push("linked");
    if ((v.screen || []).length < 2) bits.push("off-screen");
    return hierButton("view:" + v.id, bits.join(" · "));
  }).join("");
  const actors = (d.actors || []).filter((a) => a.kind === "npc");
  const plates = (d.actors || []).filter((a) => a.kind === "touch" || a.kind === "plate");
  const combat = (d.actors || []).filter((a) => a.kind === "combat" || a.kind === "combatant");
  const exits = collectExits(d);
  const trans = (d.views || []).filter((v) => !v.current && (v.screen || []).length >= 2);
  const actorBtns = actors.map((a) => hierButton(actorToken(a), a.name)).join("");
  const plateBtns = plates.map((a) => hierButton(actorToken(a), a.kind + " " + a.name)).join("");
  const combatBtns = combat.map((a) => hierButton(actorToken(a), a.kind + " " + a.name)).join("");
  const exitBtns = exits.map((row, i) => {
    const src = row.sceneScript ? "scene script" : (row.actor && row.actor.name) || "?";
    const dest = (row.exit && (row.exit.label || (row.exit.scene + "/" + row.exit.view))) || src;
    const token = row.actor ? actorToken(row.actor) : ("sexit:" + i);
    return hierButton(token, src + " → " + dest);
  }).join("");
  const transBtns = trans.map((v) => hierButton("view:" + v.id, v.id)).join("");
  box.innerHTML = [
    hierGroup("Views", views || `<p class="note">No views.</p>`),
    hierGroup("Actors", actorBtns || `<p class="note">None.</p>`),
    hierGroup("Plates", plateBtns || `<p class="note">None.</p>`),
    hierGroup("Exits", exitBtns || `<p class="note">No Teleport exits.</p>`),
    hierGroup("Transitions", transBtns || `<p class="note">None on this view.</p>`),
    hierGroup("Combat", combatBtns || `<p class="note">None.</p>`),
  ].join("");
  box.querySelectorAll("button[data-pick]").forEach((btn) => {
    btn.onclick = () => selectHierarchy(btn.dataset.pick);
  });
}

function selectHierarchy(token) {
  const d = sceneState.doc;
  if (!d || !token) return;
  if (token.indexOf("view:") === 0) {
    selectViewFootprint(token.slice(5), false);
    return;
  }
  if (token.indexOf("sexit:") === 0) {
    const row = collectExits(d)[Number(token.slice(6))];
    if (!row || !row.exit) return;
    sceneState.pick = { type: "scene-exit", exit: row.exit, index: row.index };
    renderSceneExitProps(row.exit);
    drawScene();
    return;
  }
  if (token.indexOf("actor:") === 0) {
    const actor = (d.actors || [])[Number(token.slice(6))];
    if (!actor) return;
    sceneState.pick = { type: "actor", actor };
    renderActorProps(actor);
    drawScene();
  }
}

function markSceneTree() {
  const box = el("schier");
  if (!box) return;
  const token = pickToken(sceneState.pick);
  box.querySelectorAll("button[data-pick]").forEach((btn) => {
    btn.classList.toggle("on", btn.dataset.pick === token);
  });
}

function validateField(inp) {
  const kind = inp.dataset.validate || "";
  const v = inp.value || "";
  let ok = true;
  if (kind === "number") ok = v.trim() !== "" && Number.isFinite(Number(v));
  if (kind === "number?") ok = v.trim() === "" || Number.isFinite(Number(v));
  if (kind === "int") ok = /^-?\d+$/.test(v.trim());
  if (kind === "char") ok = Array.from(v).length === 1;
  if (kind === "name") ok = v.trim().length > 0;
  inp.classList.toggle("bad", !ok);
  return ok;
}

function wireInspector(root) {
  if (!root) return;
  root.querySelectorAll("[data-validate]").forEach((inp) => {
    inp.addEventListener("input", () => validateField(inp));
    validateField(inp);
  });
}

function inspectorOk(root) {
  let ok = true;
  if (!root) return false;
  root.querySelectorAll("[data-validate]").forEach((inp) => {
    if (!validateField(inp)) ok = false;
  });
  return ok;
}

function inspectorControl(f) {
  const validate = f.validate ? ` data-validate="${esc(f.validate)}"` : "";
  const field = f.field ? ` data-field="${esc(f.field)}"` : "";
  const id = f.id ? ` id="${esc(f.id)}"` : "";
  if (f.type === "check") {
    return `<label class="layerchk"><input type="checkbox"${id}${field}${f.checked ? " checked" : ""}> ${esc(f.label || "")}</label>`;
  }
  if (f.type === "select") {
    const opts = (f.options || []).map((o) => {
      const value = o.value == null ? "" : String(o.value);
      return `<option value="${esc(value)}"${value === String(f.value == null ? "" : f.value) ? " selected" : ""}>${esc(o.label || value)}</option>`;
    }).join("");
    return `<label>${esc(f.label || "")} <select${id}${field}${validate}>${opts}</select></label>`;
  }
  if (f.type === "textarea") {
    return `<label>${esc(f.label || "")} <textarea${id}${field}${validate} rows="${f.rows || 4}">${esc(f.value || "")}</textarea></label>`;
  }
  const type = f.type === "number" ? "number" : "text";
  const placeholder = f.placeholder ? ` placeholder="${esc(f.placeholder)}"` : "";
  return `<label>${esc(f.label || "")} <input type="${type}"${id}${field}${validate}${placeholder} value="${esc(f.value == null ? "" : f.value)}"></label>`;
}

function mountInspector(root, spec) {
  if (!root || !spec) return;
  const notes = (spec.notes || []).map((n) => `<p class="note">${esc(n)}</p>`).join("");
  const fields = (spec.fields || []).map(inspectorControl).join("");
  const actions = spec.actions ? `<div class="tools">${spec.actions}</div>` : "";
  root.innerHTML = `${spec.title ? `<h3>${esc(spec.title)}</h3>` : ""}
    ${notes}${fields}${spec.extra || ""}${actions}`;
  wireInspector(root);
}

function selectViewFootprint(viewId, jump) {
  const d = sceneState.doc;
  const view = (d.views || []).find((v) => v.id === viewId);
  if (!view) return;
  if (jump && !view.current) {
    el("scview").value = view.id;
    loadSceneView();
    return;
  }
  sceneState.pick = { type: "view", view };
  renderViewProps(view);
  drawScene();
}

function jumpToDest(dest) {
  if (!dest) return;
  const catalog = sceneState.catalog;
  const sceneNum = dest.scene_num != null ? dest.scene_num : dest.scene;
  const viewNum = dest.view_num != null ? dest.view_num : dest.view;
  let chapter = dest.chapter;
  let sceneId = dest.scene;
  if (typeof sceneId === "number" || (catalog && sceneNum != null)) {
    for (const ch of (catalog && catalog.chapters) || []) {
      for (const s of ch.scenes || []) {
        if (s.num === Number(sceneNum)) {
          chapter = ch.id;
          sceneId = s.id;
          el("scchapter").value = String(ch.id);
          fillScenes(false);
          el("scscene").value = s.id;
          fillViews(false);
          const v = (s.views || []).find((vw) => vw.num === Number(viewNum));
          if (v) el("scview").value = v.id;
          loadSceneView();
          return;
        }
      }
    }
  }
  if (chapter != null && sceneId) {
    el("scchapter").value = String(chapter);
    fillScenes(false);
    el("scscene").value = sceneId;
    fillViews(false);
    if (dest.view) el("scview").value = dest.view;
    loadSceneView();
    return;
  }
  toast("Scene " + sceneNum + " is not in the catalog", true);
}

function _vsub(a, b) { return [a[0] - b[0], a[1] - b[1], a[2] - b[2]]; }
function _vadd(a, b) { return [a[0] + b[0], a[1] + b[1], a[2] + b[2]]; }
function _vmul(a, s) { return [a[0] * s, a[1] * s, a[2] * s]; }
function _vdot(a, b) { return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]; }
function _vcross(a, b) {
  return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
}
function _vlen(a) { return Math.sqrt(_vdot(a, a)) || 1; }
function _vnorm(a) { const n = _vlen(a); return [a[0] / n, a[1] / n, a[2] / n]; }

function cameraBasis(cam) {
  const fw = _vnorm(_vsub(cam.aim, cam.origin));
  let right = _vcross(fw, [0, 0, 1]);
  if (_vlen(right) < 1e-6) right = _vcross(fw, [0, 1, 0]);
  right = _vnorm(right);
  const up = _vcross(right, fw);
  return { fw, right, up };
}

function projectWorld(cam, p) {
  if (!cam) return null;
  const { fw, right, up } = cameraBasis(cam);
  const rel = _vsub(p, cam.origin);
  const z = _vdot(rel, fw);
  if (z <= 1) return null;
  const half = Math.tan(((cam.field || 63) * Math.PI / 180) * 0.5) || 1e-6;
  return {
    x: 320 + (_vdot(rel, right) / z) * (320 / half),
    y: 240 - (_vdot(rel, up) / z) * (320 / half),
    z,
  };
}

function unprojectWorld(cam, sx, sy, planeZ) {
  if (!cam) return null;
  const { fw, right, up } = cameraBasis(cam);
  const half = Math.tan(((cam.field || 63) * Math.PI / 180) * 0.5) || 1e-6;
  const xz = (sx - 320) / (320 / half);
  const yz = (240 - sy) / (320 / half);
  const dir = _vadd(_vadd(_vmul(right, xz), _vmul(up, yz)), fw);
  if (Math.abs(dir[2]) < 1e-8) return null;
  const t = (planeZ - cam.origin[2]) / dir[2];
  if (t <= 0) return null;
  return [cam.origin[0] + t * dir[0], cam.origin[1] + t * dir[1], planeZ];
}

function projectPoly(cam, pts) {
  return (pts || []).map((p) => projectWorld(cam, p)).filter(Boolean);
}

function pointInPoly(x, y, pts) {
  let inside = false;
  for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) {
    const xi = pts[i].x, yi = pts[i].y, xj = pts[j].x, yj = pts[j].y;
    if (((yi > y) !== (yj > y)) &&
        (x < (xj - xi) * (y - yi) / ((yj - yi) || 1e-9) + xi)) {
      inside = !inside;
    }
  }
  return inside;
}

function strokePoly(ctx, pts, fill, stroke, alpha) {
  if (!pts || pts.length < 2) return;
  ctx.beginPath();
  ctx.moveTo(pts[0].x, pts[0].y);
  pts.slice(1).forEach((p) => ctx.lineTo(p.x, p.y));
  ctx.closePath();
  if (fill) {
    ctx.globalAlpha = alpha == null ? 0.16 : alpha;
    ctx.fillStyle = fill;
    ctx.fill();
    ctx.globalAlpha = 1;
  }
  if (stroke) {
    ctx.strokeStyle = stroke;
    ctx.lineWidth = 2;
    ctx.stroke();
  }
}

function drawDiamond(ctx, x, y, r, color) {
  ctx.fillStyle = color;
  ctx.beginPath();
  ctx.moveTo(x, y - r);
  ctx.lineTo(x + r, y);
  ctx.lineTo(x, y + r);
  ctx.lineTo(x - r, y);
  ctx.closePath();
  ctx.fill();
}

function drawChevron(ctx, x, y, picked) {
  const ang = Math.atan2(y - 240, x - 320);
  ctx.save();
  ctx.translate(x, y);
  ctx.rotate(ang);
  ctx.fillStyle = "#d27bff";
  ctx.beginPath();
  ctx.moveTo(10, 0);
  ctx.lineTo(-7, 8);
  ctx.lineTo(-7, -8);
  ctx.closePath();
  ctx.fill();
  if (picked) {
    ctx.strokeStyle = "#fff";
    ctx.lineWidth = 2;
    ctx.stroke();
  }
  ctx.restore();
}

function polyCentroid(pts) {
  if (!pts || !pts.length) return null;
  let x = 0, y = 0;
  pts.forEach((p) => { x += p.x; y += p.y; });
  return { x: x / pts.length, y: y / pts.length };
}

const SCENE_W = 640;
const SCENE_H = 480;

function sceneContext(canvas) {
  const dpr = window.devicePixelRatio || 1;
  const bw = Math.round(SCENE_W * dpr);
  const bh = Math.round(SCENE_H * dpr);
  if (canvas.width !== bw || canvas.height !== bh) {
    canvas.width = bw;
    canvas.height = bh;
  }
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  return ctx;
}

let sceneDrawGen = 0;

async function drawScene() {
  const canvas = el("scenecanvas");
  const d = sceneState.doc;
  if (!canvas || !d) return;
  const gen = ++sceneDrawGen;
  const wantBackdrop = el("lybackdrop") && el("lybackdrop").checked && d.backdrop;
  const wantDepth = el("lydepth") && el("lydepth").checked && d.overlay;
  const backdropImg = wantBackdrop ? await loadPreview(d.backdrop.key) : null;
  if (gen !== sceneDrawGen) return;
  const overlayImg = wantDepth ? await loadPreview(d.overlay.key) : null;
  if (gen !== sceneDrawGen) return;
  const ctx = sceneContext(canvas);
  ctx.fillStyle = "#0d0e11";
  ctx.fillRect(0, 0, SCENE_W, SCENE_H);
  if (backdropImg) drawBackdrop(ctx, backdropImg);
  if (overlayImg) {
    ctx.globalAlpha = 0.45;
    ctx.drawImage(overlayImg, 0, 0, SCENE_W, SCENE_H);
    ctx.globalAlpha = 1;
  }
  if (el("lygrid").checked) {
    (d.mab_cells || []).forEach((c) => {
      ctx.fillStyle = tileColor(c.ch);
      ctx.fillRect(c.sx - 3, c.sy - 3, 6, 6);
    });
  }
  if (el("lyworld").checked) {
    ctx.strokeStyle = "rgba(120,180,255,0.45)";
    ctx.lineWidth = 1;
    (d.world_screen || []).forEach((line) => {
      const pts = line.points || [];
      if (pts.length < 2) return;
      ctx.beginPath();
      ctx.moveTo(pts[0].x, pts[0].y);
      pts.slice(1).forEach((p) => ctx.lineTo(p.x, p.y));
      ctx.stroke();
    });
  }
  if (el("lytrans") && el("lytrans").checked) {
    (d.views || []).forEach((v) => {
      const pts = v.screen || [];
      if (pts.length < 2) return;
      const picked = sceneState.pick && sceneState.pick.type === "view" &&
        sceneState.pick.view.id === v.id;
      const fill = v.current ? "#6ec8ff" : (v.linked ? "#ffb14a" : "#d27bff");
      strokePoly(ctx, pts, fill, picked ? "#fff" : fill, v.current ? 0.08 : 0.18);
      const c = polyCentroid(pts);
      if (c) {
        ctx.fillStyle = "#fff";
        ctx.font = "11px Segoe UI";
        ctx.fillText(v.current ? v.id + " (this view)" : "→ " + v.id, c.x - 18, c.y);
      }
      if (picked) {
        pts.forEach((p) => {
          ctx.fillStyle = "#fff";
          ctx.fillRect(p.x - 4, p.y - 4, 8, 8);
          ctx.strokeStyle = fill;
          ctx.strokeRect(p.x - 4, p.y - 4, 8, 8);
        });
      }
    });
  }
  const show = {
    npc: el("lyactors").checked,
    combatant: el("lycombat").checked,
    combat: el("lycombat").checked,
    touch: el("lyplates").checked,
    plate: el("lyplates").checked,
    exit: el("lyexits").checked,
  };
  const colors = {
    npc: "#e6c15a", combatant: "#d4663f", combat: "#ff7a4a",
    touch: "#6ec8ff", plate: "#8adf8a", exit: "#d27bff",
  };
  (d.actors || []).forEach((a) => {
    const pts = a.poly_screen || [];
    if ((a.kind === "touch" || a.kind === "plate") && show[a.kind] && pts.length >= 2) {
      strokePoly(ctx, pts, colors[a.kind], colors[a.kind], a.is_exit ? 0.22 : 0.12);
    }
    if (a.kind === "combat" && show.combat && a.arena) {
      const arena = projectPoly(d.camera, a.arena);
      strokePoly(ctx, arena, "#ff7a4a", "rgba(212,102,63,0.85)", 0.12);
    }
    const exitOn = el("lyexits").checked && (a.is_exit || (a.exits || []).length);
    if (exitOn && a.screen) {
      const picked = pickIs(a);
      if (a.screen.offscreen) drawChevron(ctx, a.screen.x, a.screen.y, picked);
      else drawDiamond(ctx, a.screen.x, a.screen.y, picked ? 8 : 6, "#d27bff");
      const label = (a.exits && a.exits[0] && a.exits[0].label) || a.name;
      const tag = a.screen.offscreen ? label + " (off this view)" : "→ " + label;
      ctx.fillStyle = "#f3d6ff";
      ctx.font = "10px Segoe UI";
      const lx = Math.min(620, Math.max(8, a.screen.x + (a.screen.offscreen ? -4 : 8)));
      const ly = Math.min(472, Math.max(12, a.screen.y - 4));
      ctx.fillText(tag, lx, ly);
    }
    if (!show[a.kind] || !a.screen) return;
    if (exitOn && (a.kind === "touch" || a.kind === "plate" || a.kind === "exit")) return;
    const picked = pickIs(a);
    ctx.fillStyle = colors[a.kind] || "#ccc";
    ctx.beginPath();
    ctx.arc(a.screen.x, a.screen.y, picked ? 7 : 4, 0, Math.PI * 2);
    ctx.fill();
    if (picked || a.kind === "combat") {
      ctx.fillStyle = "#fff";
      ctx.font = "10px Segoe UI";
      ctx.fillText(a.name, a.screen.x + 6, a.screen.y - 4);
    }
  });
}

function sceneCanvasXY(ev) {
  const canvas = el("scenecanvas");
  const r = canvas.getBoundingClientRect();
  return {
    x: (ev.clientX - r.left) * (SCENE_W / r.width),
    y: (ev.clientY - r.top) * (SCENE_H / r.height),
  };
}

function hitScene(mx, my) {
  const d = sceneState.doc;
  if (!d) return null;
  const pick = sceneState.pick;
  if (pick && pick.type === "view" && (pick.view.screen || []).length) {
    let bestV = 10, vert = null;
    (pick.view.screen || []).forEach((p, i) => {
      const dist = Math.hypot(p.x - mx, p.y - my);
      if (dist < bestV) { bestV = dist; vert = i; }
    });
    if (vert != null) return { type: "vertex", view: pick.view, index: vert };
  }
  let best = null, bestD = 14;
  (d.actors || []).forEach((a) => {
    if (!a.screen) return;
    const dist = Math.hypot(a.screen.x - mx, a.screen.y - my);
    if (dist < bestD) { bestD = dist; best = { type: "actor", actor: a }; }
  });
  if (best) return best;
  if (el("lytrans") && el("lytrans").checked) {
    const hits = (d.views || []).filter((v) => (v.screen || []).length >= 3 &&
      pointInPoly(mx, my, v.screen));
    if (hits.length) {
      hits.sort((a, b) => (a.current ? 1 : 0) - (b.current ? 1 : 0));
      return { type: "view", view: hits[0] };
    }
  }
  let tile = null, td = 10;
  (d.mab_cells || []).forEach((c) => {
    const dist = Math.hypot(c.sx - mx, c.sy - my);
    if (dist < td) { td = dist; tile = c; }
  });
  return tile ? { type: "tile", tile } : null;
}

function onSceneDown(ev) {
  const { x, y } = sceneCanvasXY(ev);
  const hit = hitScene(x, y);
  sceneState.drag = hit ? { hit, x, y, moved: false } : null;
}

function onSceneMove(ev) {
  const drag = sceneState.drag;
  if (!drag || !sceneState.doc) return;
  const { x, y } = sceneCanvasXY(ev);
  if (!drag.moved && Math.hypot(x - drag.x, y - drag.y) < 4) return;
  drag.moved = true;
  const cam = sceneState.doc.camera;
  const canvas = el("scenecanvas");
  if (canvas) canvas.classList.add("grab");
  if (drag.hit.type === "actor" && drag.hit.actor.movable && cam) {
    const a = drag.hit.actor;
    const planeZ = (a.xyz && a.xyz[2]) || 0;
    const world = unprojectWorld(cam, x, y, planeZ);
    if (world) {
      a.xyz = world;
      a.screen = projectWorld(cam, world);
      if (a.poly && a.poly.length) {
        const origin = a.poly.reduce((s, p) => [s[0] + p[0], s[1] + p[1], s[2] + p[2]], [0, 0, 0])
          .map((n) => n / a.poly.length);
        const delta = [world[0] - origin[0], world[1] - origin[1], world[2] - origin[2]];
        a.poly = a.poly.map((p) => [p[0] + delta[0], p[1] + delta[1], p[2] + delta[2]]);
        a.poly_screen = projectPoly(cam, a.poly);
      }
      drawScene();
    }
  } else if (drag.hit.type === "vertex" && cam) {
    const view = drag.hit.view;
    const old = view.poly[drag.hit.index];
    const world = unprojectWorld(cam, x, y, old[2]);
    if (world) {
      view.poly[drag.hit.index] = world;
      view.screen = projectPoly(cam, view.poly);
      drawScene();
    }
  }
}

async function onSceneUp(ev) {
  const canvas = el("scenecanvas");
  if (canvas) canvas.classList.remove("grab");
  const drag = sceneState.drag;
  sceneState.drag = null;
  if (!drag) return;
  if (drag.moved) {
    if (drag.hit.type === "actor" && drag.hit.actor.movable) {
      await saveActorMove(drag.hit.actor);
    } else if (drag.hit.type === "vertex") {
      await saveViewPoly(drag.hit.view);
    }
    return;
  }
  const hit = drag.hit;
  if (hit.type === "actor") {
    sceneState.pick = { type: "actor", actor: hit.actor };
    renderActorProps(hit.actor);
    drawScene();
  } else if (hit.type === "view") {
    sceneState.pick = { type: "view", view: hit.view };
    renderViewProps(hit.view);
    drawScene();
  } else if (hit.type === "vertex") {
    sceneState.pick = { type: "view", view: hit.view };
    renderViewProps(hit.view);
    drawScene();
  } else if (hit.type === "tile") {
    sceneState.pick = null;
    renderTileProps(hit.tile);
    drawScene();
  }
}

function onSceneDblClick(ev) {
  const { x, y } = sceneCanvasXY(ev);
  const hit = hitScene(x, y);
  if (!hit) return;
  ev.preventDefault();
  if (hit.type === "view" && !hit.view.current) {
    el("scview").value = hit.view.id;
    loadSceneView();
  } else if (hit.type === "actor" && hit.actor.exits && hit.actor.exits[0]) {
    jumpToDest(hit.actor.exits[0].dest || hit.actor.exits[0]);
  }
}

async function saveActorMove(a) {
  const d = sceneState.doc;
  if (!d || !a.source_key) return;
  try {
    await api("/api/scenes/move", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        key: a.source_key,
        actor: {
          kind: a.kind,
          name: a.name,
          block_kind: a.block_kind,
          block_name: a.block_name,
          parent_kind: a.parent_kind,
          parent_name: a.parent_name,
          group: a.group,
          formation: a.formation,
          facing: a.facing,
          poly: a.poly,
        },
        xyz: a.xyz,
      }),
    });
    toast("Moved " + a.name);
    await refreshMod();
  } catch (e) {
    toast("Could not move: " + e.message, true);
    loadSceneView();
  }
}

async function saveViewPoly(view) {
  const d = sceneState.doc;
  if (!d || !d.loc_key) return;
  try {
    await api("/api/scenes/viewsave", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        key: d.loc_key, scene: d.scene, view: view.id, poly: view.poly,
      }),
    });
    toast("Saved " + view.id + " CamPoly");
    await refreshMod();
  } catch (e) {
    toast("Could not save CamPoly: " + e.message, true);
    loadSceneView();
  }
}

function renderViewProps(v) {
  const d = sceneState.doc;
  mountInspector(el("scprops"), {
    title: "View " + v.id,
    notes: [
      (v.current ? "Current camera." : "Walk into this CamPoly to switch views.") +
        (v.linked ? " Overlaps this view." : "") +
        (v.num != null ? " id " + v.num : ""),
      (v.poly || []).length + " CamPoly vertices — drag the white handles.",
    ],
    fields: [{ label: "Active", field: "Active", value: v.active || "" }],
    actions: `${v.current ? "" : `<button id="scgoview">Go to view</button>`}
      <button class="primary" id="scsaveview">Save view</button>`,
  });
  const go = el("scgoview");
  if (go) go.onclick = () => { el("scview").value = v.id; loadSceneView(); };
  markSceneTree();
  el("scsaveview").onclick = async () => {
    if (!inspectorOk(el("scprops"))) { toast("Fix the highlighted fields", true); return; }
    const fields = {};
    el("scprops").querySelectorAll("[data-field]").forEach((inp) => {
      fields[inp.dataset.field] = inp.value;
    });
    try {
      await api("/api/scenes/viewsave", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          key: d.loc_key, scene: d.scene, view: v.id, fields,
        }),
      });
      toast("Saved " + v.id);
      await refreshMod();
      loadSceneView();
    } catch (e) {
      toast("Could not save view: " + e.message, true);
    }
  };
}

function renderSceneExitProps(ex) {
  mountInspector(el("scprops"), {
    title: "Scene script teleport",
    notes: ["OnEnter / scene-level " + (ex.label || (ex.scene + "/" + ex.view))],
    actions: `<button id="scgodest">Go to destination</button>`,
  });
  el("scgodest").onclick = () => jumpToDest(ex.dest || ex);
  markSceneTree();
}

function teleportEditor(a) {
  const exits = a.exits || [];
  const rows = exits.map((ex, i) => `
    <div class="sc-teleport" data-index="${i}">
      <label>scene # <input data-tp="scene" data-validate="int" value="${esc(ex.scene)}"></label>
      <label>view # <input data-tp="view" data-validate="int" value="${esc(ex.view)}"></label>
      <label class="layerchk"><input type="checkbox" data-tp="fade"${ex.fade ? " checked" : ""}> fade</label>
      <p class="note">${esc(ex.label || "")}</p>
    </div>`).join("");
  const empty = `
    <div class="sc-teleport" data-index="0" data-add="1">
      <label>scene # <input data-tp="scene" data-validate="int" value=""></label>
      <label>view # <input data-tp="view" data-validate="int" value="1"></label>
      <label class="layerchk"><input type="checkbox" data-tp="fade"> fade</label>
    </div>`;
  return `<h4>Teleport</h4>
    ${rows || empty}
    <div class="tools">
      <button class="primary" id="sctpsave">${exits.length ? "Save teleport" : "Add teleport"}</button>
      ${exits.length ? `<button id="scgodest">Go to destination</button>` : ""}
    </div>`;
}

function renderActorProps(a) {
  const fields = [];
  const notes = [];
  const editable = !a.readonly && a.source_key && a.block_kind;
  const show = ["active", "behavior", "desc", "range", "nav", "music"];
  show.forEach((k) => {
    if (a[k] == null || a[k] === "") return;
    if (editable && (k === "active" || k === "behavior" || k === "desc" || k === "range")) {
      const fname = { active: "Active", behavior: "Behavior", desc: "Desc", range: "Range" }[k];
      fields.push({
        label: k, field: fname, value: a[k],
        validate: fname === "Range" ? "number?" : "",
      });
    } else {
      notes.push(k + " " + String(a[k]));
    }
  });
  if (a.xyz) {
    notes.push("xyz " + a.xyz.map((n) => Number(n).toFixed(1)).join(", ") +
      (a.movable ? " · drag on the painting to move" : ""));
  }
  if (a.members && a.members.length) notes.push("members " + a.members.join(" · "));
  if (a.readonly) notes.push("Read-only marker. Edit in Combat / Trap studios.");
  const canTeleport = editable && (a.kind === "touch" || a.kind === "plate" ||
    a.kind === "exit" || a.kind === "npc");
  const extra = [
    canTeleport ? teleportEditor(a) : (a.exits && a.exits.length
      ? `<p class="note">teleport ${a.exits.map((e) => esc(e.label || (e.scene + "/" + e.view))).join(", ")}</p>`
      : ""),
    a.script ? `<pre class="tiny">${esc(a.script.slice(0, 800))}</pre>` : "",
  ].join("");
  mountInspector(el("scprops"), {
    title: a.kind + " " + a.name,
    notes,
    fields,
    extra,
    actions: editable ? `<button class="primary" id="scsave">Save fields</button>` : "",
  });
  markSceneTree();
  const btn = el("scsave");
  if (btn) {
    btn.onclick = async () => {
      if (!inspectorOk(el("scprops"))) { toast("Fix the highlighted fields", true); return; }
      const fields = {};
      el("scprops").querySelectorAll("[data-field]").forEach((inp) => {
        fields[inp.dataset.field] = inp.value;
      });
      try {
        await api("/api/scenes/save", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            key: a.source_key, kind: a.block_kind, name: a.block_name, fields,
            parent_kind: a.parent_kind, parent_name: a.parent_name,
          }),
        });
        toast("Saved " + a.name);
        await refreshMod();
        loadSceneView();
      } catch (e) {
        toast("Could not save: " + e.message, true);
      }
    };
  }
  const tp = el("sctpsave");
  if (tp) {
    tp.onclick = async () => {
      const box = el("scprops").querySelector(".sc-teleport");
      if (!box) return;
      if (!inspectorOk(box)) { toast("Scene and view must be whole numbers", true); return; }
      const scene = Number(box.querySelector("[data-tp=scene]").value);
      const view = Number(box.querySelector("[data-tp=view]").value);
      const fade = box.querySelector("[data-tp=fade]").checked;
      if (!scene || !view) { toast("Need scene and view numbers", true); return; }
      try {
        await api("/api/scenes/teleport", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            key: a.source_key, kind: a.block_kind, name: a.block_name,
            parent_kind: a.parent_kind, parent_name: a.parent_name,
            index: Number(box.dataset.index || 0),
            scene, view, fade,
            add: box.dataset.add === "1" || !(a.exits || []).length,
          }),
        });
        toast("Saved teleport on " + a.name);
        await refreshMod();
        loadSceneView();
      } catch (e) {
        toast("Could not save teleport: " + e.message, true);
      }
    };
  }
  const go = el("scgodest");
  if (go && a.exits && a.exits[0]) {
    go.onclick = () => jumpToDest(a.exits[0].dest || a.exits[0]);
  }
}

function renderTileProps(tile) {
  const code = (tile.ch || "?").charCodeAt(0);
  mountInspector(el("scprops"), {
    title: "Walk tile " + tile.x + "," + tile.y,
    notes: [
      "byte " + (tile.ch || "?") + " (" + code + ") · class " + (code & 0x1f) +
        (code & 0x20 ? " · blocked" : ""),
      "CostMap v2 · tile size 18. Writes the .mab override.",
    ],
    fields: [{ label: "set byte", id: "sctile", validate: "char", value: tile.ch || "" }],
    actions: `<button id="sctilefloor">Floor (@)</button>
      <button id="sctileblock">Block</button>
      <button class="primary" id="sctilesave">Save tile</button>`,
  });
  const tileInput = el("sctile");
  if (tileInput) tileInput.maxLength = 1;
  markSceneTree();
  const save = async (ch) => {
    const d = sceneState.doc;
    if (!d.mab || !d.mab.key) { toast("No .mab for this scene", true); return; }
    const tileInput = el("sctile");
    if (!ch && tileInput && !validateField(tileInput)) {
      toast("Tile byte must be one character", true);
      return;
    }
    const tileByte = (ch || el("sctile").value || "?").charCodeAt(0);
    try {
      await api("/api/scenes/mab", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          key: d.mab.key, x: tile.x, y: tile.y, tile: tileByte,
        }),
      });
      toast("Saved tile " + tile.x + "," + tile.y);
      await refreshMod();
      loadSceneView();
    } catch (e) {
      toast("Could not save tile: " + e.message, true);
    }
  };
  el("sctilefloor").onclick = () => save("@");
  el("sctileblock").onclick = () => save(" ");
  el("sctilesave").onclick = () => save();
}

// --- UI studio ----------------------------------------------------------

const CEL_LABELS = ["up", "hot", "disabled", "checked", "checked hot", "checked off"];
const uiImgCache = new Map();

function openUI() {
  stopUIQueue();
  el("detail").innerHTML = studioShell(
    "UI studio",
    "640×480 screens from FUN_004366c0. Click a control to see the dialog id and what the click does. Drag to move; queues and finish scripts are live game data.",
    `<div class="studio uistudio">
      <div class="studio-side">
        <label>screen <select id="uiscreen"></select></label>
        <div id="uiiface" class="proppanel"></div>
        <input id="uifilter" type="search" placeholder="Filter sprites…">
        <div class="layerbar">
          <label class="layerchk"><input type="checkbox" id="uishowall"> show all</label>
          <label class="layerchk"><input type="checkbox" id="uihidechrome"> hide chrome</label>
          <label class="layerchk"><input type="checkbox" id="uiclicksonly"> clicks only</label>
        </div>
        <h3 class="sc-lists">Clicks</h3>
        <div id="uiclicks" class="sc-list"></div>
        <select id="uisprites" size="10"></select>
        <div id="uiprops" class="proppanel"><p class="note">Click a control to see how it talks to the game.</p></div>
      </div>
      <div class="studio-stage">
        <canvas id="uicanvas" width="640" height="480"></canvas>
        <p class="note" id="uistatus"></p>
        <div id="uiart" class="creator hidden"></div>
      </div>
    </div>`);
  wireUIStudio();
}

async function wireUIStudio() {
  const data = await api("/api/ui");
  const sel = el("uiscreen");
  (data.screens || []).forEach((s) => {
    sel.add(new Option(s.id + " " + s.name + " (" + s.sprites + ")", s.id));
  });
  sel.onchange = () => loadUIScreen();
  el("uifilter").oninput = fillUISprites;
  el("uishowall").onchange = () => loadUIScreen();
  el("uihidechrome").onchange = () => { fillUIClicks(); drawUI(); };
  el("uiclicksonly").onchange = () => { fillUISprites(); drawUI(); };
  el("uisprites").onchange = () => pickUISprite();
  const canvas = el("uicanvas");
  canvas.onpointerdown = onUIPointerDown;
  canvas.onpointermove = onUIPointerMove;
  canvas.onpointerup = onUIPointerUp;
  canvas.onpointerleave = onUIPointerUp;
  loadUIScreen();
}

function uiPreviewUrl(s, bust) {
  const q = new URLSearchParams({ key: s.bitmap_key || s.key });
  if (s.palette) q.set("palette", s.palette);
  q.set("transparent", "1");
  q.set("v", String(bust || s._bust || 1));
  return "/api/preview?" + q.toString();
}

function uiSpriteVisible(s) {
  if (!s) return false;
  if (el("uihidechrome") && el("uihidechrome").checked) {
    const n = (s.name || "").toLowerCase();
    if (n.startsWith("smain_")) return false;
  }
  if (el("uiclicksonly") && el("uiclicksonly").checked) {
    if (!(s.action && s.action.clickable)) return false;
  }
  return true;
}

function hexCtrl(id) {
  if (id == null || id === "") return "";
  const n = Number(id);
  return Number.isFinite(n) ? "0x" + n.toString(16) : String(id);
}

function fillUIIface() {
  const box = el("uiiface");
  const doc = sceneState.ui;
  if (!box || !doc) return;
  const alias = (doc.aliases || []).length ? " Also " + doc.aliases.join(", ") + "." : "";
  box.innerHTML = `<p class="note"><strong>${esc(doc.id)}</strong> ${esc(doc.name)}
      ${doc.opener ? " · " + esc(doc.opener) : ""}${doc.proc ? " · " + esc(doc.proc) : ""}</p>
    <p class="note">${esc(doc.does || "")}${esc(alias)}</p>`;
}

function fillUIClicks() {
  const box = el("uiclicks");
  if (!box || !sceneState.ui) return;
  const pick = currentUISprite() && currentUISprite().name;
  box.innerHTML = (sceneState.ui.buttons || []).map((b) => {
    const cid = hexCtrl(b.control_id);
    const cls = b.name === pick ? "current" : "";
    return `<button type="button" data-name="${esc(b.name)}" class="${cls}">${cid ? cid + " " : ""}${esc(b.name)} · ${esc(b.kind || "")}</button>`;
  }).join("") || `<p class="note">No documented clicks on this screen.</p>`;
  box.querySelectorAll("button[data-name]").forEach((btn) => {
    btn.onclick = () => {
      const sprites = sceneState.ui.sprites || [];
      const i = sprites.findIndex((s) => s.name === btn.dataset.name);
      if (i < 0) return;
      el("uisprites").value = String(i);
      pickUISprite();
    };
  });
}

function fillUISprites() {
  const list = el("uisprites");
  if (!list || !sceneState.ui) return;
  const keep = list.value;
  const q = ((el("uifilter") && el("uifilter").value) || "").toLowerCase();
  list.innerHTML = "";
  (sceneState.ui.sprites || []).forEach((s, i) => {
    if (!uiSpriteVisible(s)) return;
    if (q && !s.name.toLowerCase().includes(q)) return;
    const act = s.action || {};
    const extra = (s.queues && s.queues.length) ? " ▸" : (act.clickable ? " •" : "");
    const cid = hexCtrl(act.control_id);
    list.add(new Option((cid ? cid + "  " : "") + s.name + "  " + s.w + "×" + s.h + extra, String(i)));
  });
  if (keep) list.value = keep;
}

async function loadUIScreen(keepName) {
  stopUIQueue();
  const id = el("uiscreen").value;
  const all = el("uishowall") && el("uishowall").checked ? "&all=1" : "";
  el("uistatus").textContent = "Composing " + id + "…";
  const doc = await api("/api/ui/screen?id=" + encodeURIComponent(id) + all);
  sceneState.ui = doc;
  sceneState.uiDrag = null;
  uiImgCache.clear();
  fillUISprites();
  fillUIIface();
  const sprites = doc.sprites || [];
  let pick = 0;
  if (keepName) {
    const i = sprites.findIndex((s) => s.name === keepName);
    if (i >= 0) pick = i;
  }
  if (el("uisprites").options.length) el("uisprites").value = String(pick);
  fillUIClicks();
  el("uistatus").textContent = sprites.length + " controls · " +
    (doc.palette || "") + " · drag to move · " + (doc.note || "");
  await drawUI();
  renderUIProps(sprites[pick] || null);
}

function uiLoadImage(s) {
  if (!s || !(s.bitmap_key || s.key)) return Promise.resolve(null);
  const url = uiPreviewUrl(s);
  if (uiImgCache.has(url)) return Promise.resolve(uiImgCache.get(url));
  return new Promise((resolve) => {
    const img = new Image();
    img.onload = () => { uiImgCache.set(url, img); resolve(img); };
    img.onerror = () => resolve(null);
    img.src = url;
  });
}

async function drawUI() {
  const canvas = el("uicanvas");
  if (!canvas || !sceneState.ui) return;
  const ctx = canvas.getContext("2d");
  ctx.fillStyle = "#0d0e11";
  ctx.fillRect(0, 0, 640, 480);
  const sprites = sceneState.ui.sprites || [];
  const pick = Number(el("uisprites") && el("uisprites").value);
  const images = await Promise.all(sprites.map((s) => uiLoadImage(s)));
  sprites.forEach((s, i) => {
    if (!uiSpriteVisible(s)) return;
    const img = images[i];
    if (!img) return;
    ctx.drawImage(img, s.x, s.y, s.w, s.h);
  });
  sprites.forEach((s) => {
    if (!uiSpriteVisible(s) || !(s.action && s.action.clickable)) return;
    ctx.strokeStyle = "rgba(210, 123, 255, 0.7)";
    ctx.lineWidth = 1;
    ctx.setLineDash([3, 3]);
    ctx.strokeRect(s.x + 0.5, s.y + 0.5, s.w, s.h);
    ctx.setLineDash([]);
  });
  if (sprites[pick] && uiSpriteVisible(sprites[pick])) {
    const s = sprites[pick];
    ctx.strokeStyle = "#fff";
    ctx.lineWidth = 2;
    ctx.strokeRect(s.x + 0.5, s.y + 0.5, s.w, s.h);
  }
}

function applyUICel(s, idx) {
  if (!s) return;
  const cells = s.cells || [];
  const i = Math.max(0, Math.min(intOr(idx, 0), Math.max(0, cells.length - 1)));
  s.cel = i;
  const cell = cells[i];
  if (cell && cell.bitmap_key) {
    s.bitmap_key = cell.bitmap_key;
    s.bitmap = cell.bitmap;
    if (cell.w) s.w = cell.w;
    if (cell.h) s.h = cell.h;
    if (cell.hot) s.hot = cell.hot;
  }
}

function intOr(v, fallback) {
  const n = Number(v);
  return Number.isFinite(n) ? n : fallback;
}

function currentUISprite() {
  const i = Number(el("uisprites") && el("uisprites").value);
  return (sceneState.ui && sceneState.ui.sprites || [])[i] || null;
}

function pickUISprite() {
  stopUIQueue();
  const s = currentUISprite();
  fillUIClicks();
  renderUIProps(s);
  drawUI();
}

function uiCanvasXY(ev) {
  const canvas = el("uicanvas");
  const r = canvas.getBoundingClientRect();
  return {
    x: (ev.clientX - r.left) * (canvas.width / r.width),
    y: (ev.clientY - r.top) * (canvas.height / r.height),
  };
}

function hitUISprite(mx, my) {
  const sprites = (sceneState.ui && sceneState.ui.sprites) || [];
  let hit = -1, area = 1e12;
  sprites.forEach((s, i) => {
    if (!uiSpriteVisible(s)) return;
    if (mx >= s.x && mx <= s.x + s.w && my >= s.y && my <= s.y + s.h) {
      const a = s.w * s.h;
      if (a <= area) { area = a; hit = i; }
    }
  });
  return hit;
}

function onUIPointerDown(ev) {
  const { x, y } = uiCanvasXY(ev);
  const hit = hitUISprite(x, y);
  if (hit < 0) return;
  el("uisprites").value = String(hit);
  const s = (sceneState.ui.sprites || [])[hit];
  sceneState.uiDrag = {
    i: hit, name: s.name, startX: x, startY: y, origX: s.x, origY: s.y, moved: false,
  };
  el("uicanvas").classList.add("grab");
  try { ev.currentTarget.setPointerCapture(ev.pointerId); } catch (e) {}
  renderUIProps(s);
  drawUI();
}

function onUIPointerMove(ev) {
  const { x, y } = uiCanvasXY(ev);
  const drag = sceneState.uiDrag;
  if (!drag) {
    el("uicanvas").style.cursor = hitUISprite(x, y) >= 0 ? "grab" : "crosshair";
    return;
  }
  const dx = Math.round(x - drag.startX);
  const dy = Math.round(y - drag.startY);
  if (Math.abs(dx) > 2 || Math.abs(dy) > 2) drag.moved = true;
  const s = (sceneState.ui.sprites || [])[drag.i];
  if (!s) return;
  s.x = drag.origX + dx;
  s.y = drag.origY + dy;
  const xEl = el("uix");
  const yEl = el("uiy");
  if (xEl) xEl.value = String(s.x);
  if (yEl) yEl.value = String(s.y);
  drawUI();
}

async function onUIPointerUp(ev) {
  const canvas = el("uicanvas");
  if (canvas) canvas.classList.remove("grab");
  const drag = sceneState.uiDrag;
  sceneState.uiDrag = null;
  if (!drag || !drag.moved) return;
  const s = (sceneState.ui.sprites || [])[drag.i];
  if (!s) return;
  await saveUILayout(s, { writeHot: el("uihotwrite") ? el("uihotwrite").checked : true });
}

async function saveUILayout(s, opts) {
  const options = opts || {};
  try {
    await api("/api/ui/layout", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: s.name,
        x: intOr(options.x, s.x),
        y: intOr(options.y, s.y),
        cel: options.cel != null ? options.cel : s.cel,
        write_hot: options.writeHot !== false,
      }),
    });
    toast("Moved " + s.name);
    await refreshMod();
  } catch (e) {
    toast("Could not save layout: " + e.message, true);
  }
}

function stopUIQueue() {
  sceneState.uiPlayGen = (sceneState.uiPlayGen || 0) + 1;
  if (sceneState.uiPlay) {
    clearTimeout(sceneState.uiPlay);
    sceneState.uiPlay = null;
  }
}

function playUISound(cmd) {
  const waves = ((currentUISprite() || {}).sounds || {}).waves || [];
  const name = (cmd && cmd.name || "").toLowerCase();
  const hit = waves.find((w) => {
    const stem = (w.name || "").toLowerCase();
    return name && (name.includes(stem.replace(/\.[^.]+$/, "")) ||
      stem.replace(/\.[^.]+$/, "").split(/[^a-z0-9]+/).some((p) => p.length > 3 && name.includes(p)));
  }) || waves[0];
  if (!hit) return;
  const audio = new Audio("/api/preview?key=" + encodeURIComponent(hit.key) + "&v=" + Date.now());
  audio.play().catch(() => {});
}

function playUIQueue(s, queue) {
  stopUIQueue();
  const cmds = (queue.commands || []).filter((c) => c.kind === "cels" || c.kind === "script");
  if (!cmds.length) {
    toast("Queue has no cel commands", true);
    return;
  }
  sceneState.uiPlayGen = (sceneState.uiPlayGen || 0) + 1;
  const gen = sceneState.uiPlayGen;
  const alive = () => sceneState.uiPlayGen === gen;
  let ci = 0;
  const run = () => {
    if (!alive()) return;
    while (ci < cmds.length && cmds[ci].kind === "script") {
      playUISound(cmds[ci]);
      ci += 1;
    }
    const cmd = cmds[ci];
    if (!cmd || cmd.kind !== "cels") {
      sceneState.uiPlay = null;
      applyUICel(s, 0);
      drawUI();
      return;
    }
    const dir = cmd.last >= cmd.first ? 1 : -1;
    let frame = cmd.first;
    const step = () => {
      if (!alive()) return;
      applyUICel(s, frame);
      drawUI();
      frame += dir;
      const done = dir > 0 ? frame > cmd.last : frame < cmd.last;
      if (done) {
        ci += 1;
        sceneState.uiPlay = setTimeout(run, Math.max(20, cmd.delay || 83));
        return;
      }
      sceneState.uiPlay = setTimeout(step, Math.max(20, cmd.delay || 83));
    };
    sceneState.uiPlay = setTimeout(step, 0);
  };
  run();
}

function openUIArt(s) {
  const box = el("uiart");
  if (!box) return;
  const key = s && (s.bitmap_key || s.key);
  if (!key) {
    box.classList.add("hidden");
    box.innerHTML = "";
    return;
  }
  box.classList.remove("hidden");
  if (!window.RTKCreator) {
    box.innerHTML = `<p class="note">Pixel editor script did not load.</p>`;
    return;
  }
  RTKCreator.attach({
    el: box,
    panel: () => null,
    api,
    toast,
    refreshMod: async () => {
      await refreshMod();
      if (s) s._bust = Date.now();
      uiImgCache.clear();
      drawUI();
    },
    remount: () => {},
    canEdit: !!(state && state.mod),
    getContext: () => ({ character: "James", kit: {}, regions: {} }),
    setRegions: () => {},
  });
  RTKCreator.loadArt({
    sheets: [{
      key, name: s.bitmap || s.name, label: s.bitmap || s.name,
      region: "item", slot: "ui", frame: 0, joint: "",
    }],
    palette: [],
    palette_key: "",
  }, { title: s.name });
}

function renderUIProps(s) {
  const box = el("uiprops");
  if (!box) return;
  if (!s) {
    box.innerHTML = `<p class="note">Click a control on the canvas.</p>`;
    const art = el("uiart");
    if (art) { art.classList.add("hidden"); art.innerHTML = ""; }
    return;
  }
  const cells = s.cells || [];
  const queues = s.queues || [];
  const texts = s.texts || [];
  const scripts = s.scripts || [];
  const sounds = s.sounds || {};
  const celBtns = cells.map((c, i) => {
    const label = CEL_LABELS[i] || ("cel " + i);
    return `<button type="button" class="uicel${i === (s.cel || 0) ? " on" : ""}"
                    data-i="${i}" title="${esc(c.name)}">${esc(label)}
              <img src="${uiPreviewUrl({ bitmap_key: c.bitmap_key, palette: s.palette, _bust: s._bust })}"
                   alt="${esc(c.name)}"></button>`;
  }).join("");
  const queueHtml = queues.map((q, qi) => {
    const cmds = (q.commands || []).map((cmd, ci) => {
      if (cmd.kind === "cels") {
        return `<div class="uiqcmd">
          <span>cels</span>
          <label>first <input id="uqf${qi}_${ci}" type="number" value="${cmd.first}"></label>
          <label>last <input id="uql${qi}_${ci}" type="number" value="${cmd.last}"></label>
          <label>ms <input id="uqd${qi}_${ci}" type="number" value="${cmd.delay}"></label>
          <button type="button" data-qi="${qi}" data-ci="${ci}" class="uiqsave">Save</button>
        </div>`;
      }
      return `<div class="uiqcmd">
          <span>script</span>
          <label>id <input id="uqs${qi}_${ci}" type="text" value="${cmd.script != null ? cmd.script : ""}"></label>
          <span class="note">${esc(cmd.name || "")}${cmd.sound ? " · sound" : ""}</span>
          <button type="button" data-qi="${qi}" data-ci="${ci}" class="uiqscript">Save script</button>
        </div>`;
    }).join("");
    return `<div class="uiqueue">
      <div class="tools">
        <strong>${esc(q.name)}</strong>
        <button type="button" class="uiqplay" data-qi="${qi}">Play</button>
        <button type="button" class="uiqstop">Stop</button>
      </div>
      ${cmds}
    </div>`;
  }).join("");
  const textHtml = texts.map((t, ti) => `<div class="uitext">
      <p class="note">${esc(t.name)} · 11 dwords (string table, not inline text)</p>
      <div class="uidwords">${(t.dwords || []).map((d, di) =>
        `<input class="uitd" data-ti="${ti}" data-di="${di}" type="number" value="${d}">`).join("")}</div>
      <button type="button" class="uitsave" data-ti="${ti}">Save TEXT</button>
    </div>`).join("");
  const waveHtml = (sounds.waves || []).map((w) => `<div class="uiwave">
      <audio controls preload="none" src="/api/preview?key=${encodeURIComponent(w.key)}"></audio>
      <span>${esc(w.name)}</span>
      <input type="file" class="uiwavfile" data-key="${esc(w.key)}" accept=".wav,audio/wav">
    </div>`).join("");
  const act = s.action || {};
  const kinds = (sceneState.ui && sceneState.ui.kinds) || [];
  const screens = (sceneState.ui && sceneState.ui.screens) || [];
  const kindOpts = kinds.map((k) =>
    `<option value="${k}"${k === (act.kind || "") ? " selected" : ""}>${k}</option>`).join("");
  const openOpts = [`<option value="">(none)</option>`].concat(screens.map((sc) =>
    `<option value="${esc(sc.id)}"${sc.id === (act.opens || "") ? " selected" : ""}>${esc(sc.id)} ${esc(sc.name)}</option>`)).join("");
  box.innerHTML = `<h3>${esc(s.name)}</h3>
    <p class="note">${esc(s.kind || "")} ${s.id} · ${esc(s.bitmap || "no bitmap")}
      · ${esc(s.pos_source || "")}${s.placed ? " · authored box" : ""}</p>
    <h3>What this does</h3>
    <p class="note">${esc(act.does || "No documented click.")}
      ${act.source ? " · " + esc(act.source) : ""}${act.queue ? " · " + esc(act.queue) : ""}${act.script ? " → " + esc(act.script) : ""}</p>
    <label>control id <input id="uicid" type="text" value="${esc(hexCtrl(act.control_id))}" placeholder="0x65"></label>
    <label>type <select id="uitype">
      <option value="0"${act.type === 0 ? " selected" : ""}>0 static</option>
      <option value="1"${act.type === 1 || act.type == null ? " selected" : ""}>1 push</option>
      <option value="3"${act.type === 3 ? " selected" : ""}>3 toggle</option>
      <option value="4"${act.type === 4 ? " selected" : ""}>4 push (doc)</option>
      <option value="5"${act.type === 5 ? " selected" : ""}>5 radio</option>
    </select></label>
    <label>kind <select id="uikindact">${kindOpts}</select></label>
    <label>does <textarea id="uidoes" rows="3">${esc(act.does || "")}</textarea></label>
    <label>opens screen <select id="uiopens">${openOpts}</select></label>
    <label>opens sprite <input id="uiopenspr" type="text" value="${esc(act.opens_sprite || "")}"></label>
    <label>enabled when <input id="uienable" type="text" value="${esc(act.enabled_when || "")}"></label>
    <p class="note">Control id and the dialog procedure live in the EXE. Save writes the mod overlay so this studio keeps your wiring. Finish scripts on a QUEUE below are live — they are what the game runs.</p>
    <div class="tools">
      <button class="primary" id="uiactsave">Save interface</button>
      ${act.opens ? `<button type="button" id="uigoto">Go to opened screen</button>` : ""}
    </div>
    <div class="ui-xy">
      <label>x <input id="uix" type="number" value="${s.x}"></label>
      <label>y <input id="uiy" type="number" value="${s.y}"></label>
    </div>
    <label class="layerchk"><input type="checkbox" id="uihotwrite" checked> write hotspot too</label>
    <div class="tools">
      <button class="primary" id="uimove">Save position</button>
    </div>
    <h3>Cels</h3>
    <div class="uicels">${celBtns || `<p class="note">No bitmap/CEL refs.</p>`}</div>
    <label>swap with <select id="uikind">
      <option value="BITMAP">BITMAP</option>
      <option value="CEL">CEL</option>
    </select></label>
    <input id="uicatq" type="search" placeholder="Search bitmaps / cels…">
    <select id="uicat" size="6"></select>
    <div class="tools">
      <button id="uiswap">Use on this cel</button>
    </div>
    <h3>Bitmap</h3>
    <div class="tools">
      <input type="file" id="uifile" accept="image/png,image/bmp">
      <button class="primary" id="uisavebmp" disabled>Replace file</button>
      <button type="button" id="uipaint">Edit pixels</button>
    </div>
    ${queueHtml ? `<h3>Queues</h3>${queueHtml}` : ""}
    ${scripts.length ? `<h3>Scripts</h3><ul class="tiny">${scripts.map((sc) =>
      `<li>${esc(sc.name)}${sc.sound ? " · sound" : ""}</li>`).join("")}</ul>` : ""}
    ${waveHtml ? `<h3>Sounds</h3>${waveHtml}` : (sounds.scripts || []).length
      ? `<p class="note">Scripts: ${esc((sounds.scripts || []).join(", "))}. No matching .wav in the index.</p>` : ""}
    ${textHtml ? `<h3>TEXT</h3>${textHtml}` : ""}`;
  wireUIProps(s);
}

function wireUIProps(s) {
  document.querySelectorAll(".uicel").forEach((btn) => {
    btn.onclick = async () => {
      applyUICel(s, Number(btn.dataset.i));
      document.querySelectorAll(".uicel").forEach((b) => b.classList.toggle("on", b === btn));
      drawUI();
      try {
        await api("/api/ui/layout", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name: s.name, cel: s.cel, write_hot: false }),
        });
      } catch (e) {
        toast("Could not remember cel: " + e.message, true);
      }
    };
  });
  if (el("uiactsave")) {
    el("uiactsave").onclick = async () => {
      try {
        await api("/api/ui/action", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            name: s.name,
            control_id: el("uicid").value,
            type: el("uitype").value,
            kind: el("uikindact").value,
            does: el("uidoes").value,
            opens: el("uiopens").value,
            opens_sprite: el("uiopenspr").value,
            enabled_when: el("uienable").value,
          }),
        });
        toast("Saved interface for " + s.name);
        await refreshMod();
        await loadUIScreen(s.name);
      } catch (e) {
        toast("Could not save interface: " + e.message, true);
      }
    };
  }
  if (el("uigoto") && el("uiopens") && el("uiopens").value) {
    el("uigoto").onclick = () => {
      el("uiscreen").value = el("uiopens").value;
      loadUIScreen();
    };
  }
  if (el("uimove")) {
    el("uimove").onclick = async () => {
      s.x = intOr(el("uix").value, s.x);
      s.y = intOr(el("uiy").value, s.y);
      await saveUILayout(s, { writeHot: el("uihotwrite").checked });
      drawUI();
    };
  }
  const search = async () => {
    const kind = el("uikind").value;
    const q = el("uicatq").value || "";
    const doc = await api("/api/ui/catalog?kind=" + encodeURIComponent(kind) +
      "&q=" + encodeURIComponent(q) + "&limit=60");
    const sel = el("uicat");
    sel.innerHTML = "";
    (doc.items || []).forEach((it) => {
      const dim = it.w ? " " + it.w + "×" + it.h : "";
      sel.add(new Option(it.name + dim + "  #" + it.id, String(it.id)));
    });
  };
  if (el("uicatq")) {
    let t = 0;
    el("uicatq").oninput = () => { clearTimeout(t); t = setTimeout(search, 200); };
    el("uikind").onchange = search;
  }
  if (el("uiswap")) {
    el("uiswap").onclick = async () => {
      const id = Number(el("uicat").value);
      if (!id) { toast("Pick a bitmap or cel first", true); return; }
      const cell = (s.cells || [])[s.cel || 0];
      try {
        if (cell && cell.kind === "CEL" && el("uikind").value === "BITMAP") {
          await api("/api/ui/cel", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ cel_key: cell.key, bitmap_id: id }),
          });
        } else {
          await api("/api/ui/ref", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              sprite_key: s.key,
              index: cell ? cell.ref : (s.cel || 0),
              new_id: id,
            }),
          });
        }
        toast("Swapped cel on " + s.name);
        await refreshMod();
        await loadUIScreen(s.name);
      } catch (e) {
        toast("Could not swap: " + e.message, true);
      }
    };
  }
  const file = el("uifile");
  const saveBmp = el("uisavebmp");
  if (file && saveBmp && (s.bitmap_key || s.key)) {
    file.onchange = () => { saveBmp.disabled = !file.files.length; };
    saveBmp.onclick = async () => {
      try {
        const p = new URLSearchParams({ key: s.bitmap_key || s.key });
        if (s.palette) p.set("palette", s.palette);
        await api("/api/override?" + p, { method: "POST", body: file.files[0] });
        toast("Saved " + (s.bitmap || s.name));
        s._bust = Date.now();
        await refreshMod();
        uiImgCache.clear();
        drawUI();
        openUIArt(s);
      } catch (e) {
        toast("Could not save: " + e.message, true);
      }
    };
  }
  if (el("uipaint")) el("uipaint").onclick = () => openUIArt(s);
  document.querySelectorAll(".uiqplay").forEach((btn) => {
    btn.onclick = () => playUIQueue(s, (s.queues || [])[Number(btn.dataset.qi)]);
  });
  document.querySelectorAll(".uiqstop").forEach((btn) => {
    btn.onclick = () => { stopUIQueue(); applyUICel(s, s.cel || 0); drawUI(); };
  });
  document.querySelectorAll(".uiqscript").forEach((btn) => {
    btn.onclick = async () => {
      const qi = Number(btn.dataset.qi);
      const ci = Number(btn.dataset.ci);
      const q = (s.queues || [])[qi];
      const cmd = q && (q.commands || [])[ci];
      if (!q || !cmd) return;
      const inp = el("uqs" + qi + "_" + ci);
      try {
        await api("/api/ui/queue", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            key: q.key,
            offset: cmd.offset,
            script: inp ? inp.value : cmd.script,
          }),
        });
        toast("Saved finish script on " + q.name);
        await refreshMod();
        await loadUIScreen(s.name);
      } catch (e) {
        toast("Could not save script: " + e.message, true);
      }
    };
  });
  document.querySelectorAll(".uiqsave").forEach((btn) => {
    btn.onclick = async () => {
      const qi = Number(btn.dataset.qi);
      const ci = Number(btn.dataset.ci);
      const q = (s.queues || [])[qi];
      const cmd = q && (q.commands || [])[ci];
      if (!q || !cmd) return;
      try {
        await api("/api/ui/queue", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            key: q.key,
            offset: cmd.offset,
            first: intOr(el("uqf" + qi + "_" + ci).value, cmd.first),
            last: intOr(el("uql" + qi + "_" + ci).value, cmd.last),
            delay: intOr(el("uqd" + qi + "_" + ci).value, cmd.delay),
          }),
        });
        toast("Saved " + q.name);
        await refreshMod();
        await loadUIScreen(s.name);
      } catch (e) {
        toast("Could not save queue: " + e.message, true);
      }
    };
  });
  document.querySelectorAll(".uitsave").forEach((btn) => {
    btn.onclick = async () => {
      const ti = Number(btn.dataset.ti);
      const t = (s.texts || [])[ti];
      if (!t) return;
      const dwords = Array.from(el("uiprops").querySelectorAll('.uitd[data-ti="' + ti + '"]'))
        .map((inp) => intOr(inp.value, 0));
      try {
        await api("/api/ui/text", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ key: t.key, dwords }),
        });
        toast("Saved " + t.name);
        await refreshMod();
      } catch (e) {
        toast("Could not save TEXT: " + e.message, true);
      }
    };
  });
  if (el("uicatq")) search();
  document.querySelectorAll(".uiwavfile").forEach((inp) => {
    inp.onchange = async () => {
      if (!inp.files.length) return;
      try {
        await api("/api/override?key=" + encodeURIComponent(inp.dataset.key), {
          method: "POST", body: inp.files[0],
        });
        toast("Replaced " + inp.dataset.key.split("/").pop());
        await refreshMod();
        await loadUIScreen(s.name);
      } catch (e) {
        toast("Could not replace wave: " + e.message, true);
      }
    };
  });
}

// --- Combat studio ------------------------------------------------------

function openCombat() {
  if (typeof RTKViewer !== "undefined" && RTKViewer.unmount) RTKViewer.unmount();
  el("detail").innerHTML = studioShell(
    "Combat + characters",
    "CombatDef is in-scene. CharacterDef in Chars.tbl is the sheet, model, and bag. Class bits are Warrior 1, Thief 2, LPMage 4, Priest 8 — a new class needs an exe change.",
    `<div class="studio combatstudio layout3" id="studiolayout" data-studio="opencombat">
      <div class="studio-side">
        <h3>Fights</h3>
        <input id="cbfq" type="search" placeholder="Filter fights…">
        <select id="cbfights" size="8"></select>
        <h3>Characters</h3>
        <input id="cbcq" type="search" placeholder="Filter characters…">
        <select id="cbchars" size="14"></select>
      </div>
      <div class="split" data-edge="side" title="Drag to resize the list"></div>
      <div class="studio-stage" id="cbeditor">
        <p class="note">Pick a character to preview the model.</p>
      </div>
      <div class="split" data-edge="inspector" title="Drag to resize the inspector"></div>
      <div class="studio-inspector">
        <div id="cbprops" class="proppanel"><p class="note">Pick a fight or a character.</p></div>
      </div>
    </div>`);
  wireLayout(el("studiolayout"));
  wireCombatStudio();
}

async function wireCombatStudio() {
  const fights = await api("/api/combat");
  sceneState.fights = fights.fights || [];
  const fillF = () => {
    const q = (el("cbfq").value || "").toLowerCase();
    const sel = el("cbfights");
    sel.innerHTML = "";
    sceneState.fights.filter((f) => !q || f.name.toLowerCase().includes(q) ||
      (f.scene || "").toLowerCase().includes(q)).forEach((f) => {
      sel.add(new Option(f.scene + " / " + f.name, f.name));
    });
  };
  fillF();
  el("cbfq").oninput = fillF;
  el("cbfights").onchange = async () => {
    const doc = await api("/api/combat/fight?name=" +
      encodeURIComponent(el("cbfights").value));
    mountInspector(el("cbprops"), {
      title: doc.name,
      notes: [
        "scene " + (doc.scene || "") + " · " + (doc.music || "no music"),
        "groups " + (doc.groups || []).join(", "),
      ].concat((doc.formations || []).map((f) =>
        f.name + " " + (f.members || []).map((m) =>
          m.name + " @ " + (m.xyz || []).map((n) => Number(n).toFixed(0)).join(",")
        ).join(" · ")
      )).concat(doc.arena && doc.arena.length ? ["arena " + doc.arena.length + " pts"] : []),
      extra: `<pre class="tiny">${esc((doc.script || "").slice(0, 900))}</pre>`,
      actions: `<button id="cbshowscene">Show on Scene</button>`,
    });
    el("cbshowscene").onclick = () => {
      openScenes();
      toast("Open the scene " + (doc.scene || "") + " to see this fight overlay.");
    };
  };
  el("cbcq").oninput = () => {
    clearTimeout(loadCombatChars.t);
    loadCombatChars.t = setTimeout(loadCombatChars, 160);
  };
  await loadCombatChars();
  el("cbchars").onchange = async () => {
    const c = await api("/api/combat/character?name=" +
      encodeURIComponent(el("cbchars").value));
    paintCombatChar(c);
  };
}

async function loadCombatChars() {
  const box = el("cbcq");
  const sel = el("cbchars");
  if (!sel) return;
  const doc = await api("/api/combat/classes?q=" + encodeURIComponent((box && box.value) || ""));
  const keep = sel.value;
  sel.innerHTML = "";
  (doc.characters || []).forEach((c) => {
    sel.add(new Option(c.name + " · " + (c.class_token || c.class || "") +
      (c.level != null ? " lv " + c.level : ""), c.name));
  });
  if (keep) sel.value = keep;
  const jump = window.rtkJump;
  if (!jump || (jump.kind !== "character" && jump.kind !== "model")) return;
  const want = jump.kind === "character" ? jump.name : (jump.character || "");
  if (want && ![...sel.options].some((o) => o.value === want)) {
    if (box && box.value) {
      box.value = "";
      return loadCombatChars();
    }
    window.rtkJump = null;
    return;
  }
  window.rtkJump = null;
  if (!want) {
    toast((jump.name || "That model") + " has no character sheet");
    return;
  }
  sel.value = want;
  const c = await api("/api/combat/character?name=" + encodeURIComponent(want));
  paintCombatChar(c);
  if (jump.kind === "model" && el("cbmodel")) {
    el("cbmodel").value = jump.name;
    if (el("cbmodel").value === jump.name && el("cbmodel").onchange) el("cbmodel").onchange();
  }
}

function combatGearOf(items, slot) {
  const hit = (items || []).find((it) => (it.location || "").toLowerCase() === slot.toLowerCase());
  if (!hit) return "";
  return (hit.preview && hit.preview.gear) || "";
}

function combatLookKit(look, faceExpr, stride) {
  const n = Number(look);
  if (!Number.isFinite(n) || n < 0) return {};
  const expr = Number(faceExpr) || 0;
  let step = Number(stride);
  if (!Number.isFinite(step) || step < 1) step = 7;
  return {
    torso: n, back: n, legs: n, arms: n, body: n,
    face: n * step + expr,
  };
}

function combatPaletteKey(c, name) {
  const hit = (c.palettes || []).find((p) => p.name === name);
  return (hit && hit.key) || (c.sprites && c.sprites.palette_key) || "";
}

async function mountCombatPreview(model, weapon, shield, opts) {
  opts = opts || {};
  const note = el("cbviewnote");
  const canvas = el("cbview");
  if (note) note.textContent = "";
  if (!canvas) return;
  if (typeof RTKViewer === "undefined" || typeof THREE === "undefined") {
    if (note) note.textContent = "3D viewer did not load.";
    return;
  }
  try {
    await RTKViewer.mount(canvas, {
      character: model || "James",
      weapon: weapon || "",
      shield: shield || "",
      kit: opts.kit || {},
      palette: opts.palette || "",
      faceExpr: opts.faceExpr,
      bgColor: "#0d0e11",
      showWire: el("cbwire") && el("cbwire").checked,
      showBones: el("cbbones") && el("cbbones").checked,
      showCollision: el("cbcollide") && el("cbcollide").checked,
    });
    if (RTKViewer.resize) RTKViewer.resize();
  } catch (e) {
    if (note) note.textContent = "No preview for " + (model || "?") + " — " + e.message;
  }
}

function paintCombatChar(c) {
  const preview = el("cbeditor");
  const sheet = el("cbprops");
  if (!preview || !sheet) return;
  const box = el("studiolayout") || preview;
  sceneState.combatChar = c;
  const attrs = c.attributes || {};
  const skills = c.skill_values || [];
  const atk = c.attack_fields || {};
  const models = (c.models || []).slice();
  const selectedModel = c.model_resolved || c.model || "";
  if (c.model && !models.some((m) => m.name === c.model)) {
    models.unshift({ name: c.model, has_rig: false });
  }
  const classOpts = (c.class_names || []).map((n) =>
    `<option value="${esc(n)}"${n === (c.class_token || "") ? " selected" : ""}>${n}</option>`).join("");
  const modelOpts = models.map((m) =>
    `<option value="${esc(m.name)}"${m.name === selectedModel || m.name === (c.model || "") ? " selected" : ""}>${esc(m.name)}${m.has_rig ? "" : (m.type === "prop" ? " (3D sprite)" : " (no rig)")}</option>`).join("");
  const spr = c.sprites || {};
  const palettes = c.palettes || [];
  const heads = c.head_sprites || [];
  const look0 = spr.look != null ? spr.look : -1;
  const stride = spr.face_stride || 7;
  const palOpts = palettes.map((p) =>
    `<option value="${esc(p.name)}"${p.name === (spr.palette || "") ? " selected" : ""}>${esc(p.name)}</option>`).join("");
  const headOpts = heads.map((h) => {
    const tag = h.tag || "";
    const sel = (!spr.head_sprite && !tag) || tag === (spr.head_sprite || "");
    return `<option value="${esc(tag)}"${sel ? " selected" : ""}>${esc(h.name)}</option>`;
  }).join("");
  const remapKey = combatPaletteKey(c, spr.palette || "");
  const remapQ = remapKey ? "&remap=" + encodeURIComponent(remapKey) : "";
  const spriteHtml = (spr.sheets || []).map((sh) => {
    const all = (sh.frames || []).map((f, i) => Object.assign({ index: i }, f)).filter((f) => f.key);
    const isFace = (sh.slot === "face") || /FACE/i.test(sh.name || "");
    let shown = all;
    if (isFace && stride > 1 && look0 >= 0 && all.length > stride) {
      const start = look0 * stride;
      shown = all.filter((f) => f.index >= start && f.index < start + stride);
    }
    const cur = isFace
      ? (look0 >= 0 ? look0 * stride : -1)
      : look0;
    return `<div class="cbsheet">
      <p class="note">${esc(sh.name)} · ${esc(sh.slot || sh.kind || "sprite")} · ${all.length} frame${all.length === 1 ? "" : "s"}${isFace ? " · expressions for look " + look0 : ""}</p>
      <div class="cbsprites">${shown.map((f) =>
        `<img class="cbsprite${f.index === cur || (isFace && look0 >= 0 && f.index === cur) ? " selected" : ""}" data-slot="${esc(sh.slot || "")}" data-i="${f.index}" src="/api/preview?key=${encodeURIComponent(f.key)}${remapQ}" title="${esc(f.name || "")} #${f.index}" alt="${esc(f.name || "")}">`
      ).join("")}</div>
    </div>`;
  }).join("");
  const attrHtml = (c.attr_fields || []).filter((f) => f.key !== "level").map((f) =>
    `<label>${esc(f.label)} <input class="cbattr" data-key="${esc(f.key)}" type="number" data-validate="number" value="${attrs[f.key] != null ? attrs[f.key] : 0}"></label>`
  ).join("");
  const skillGroups = [
    ["weapon", "Weapon skills"],
    ["general", "Defense and trades"],
    ["path", "Spell paths"],
  ];
  const skillHtml = skillGroups.map(([gid, title]) => {
    const rows = (c.skill_fields || []).filter((f) => (f.group || "general") === gid);
    if (!rows.length) return "";
    return `<h4>${esc(title)}</h4>
      <div class="cb-skills">${rows.map((f) =>
        `<label>${esc(f.label)} <span class="cbskillwho">${esc(f.who || "")}</span>
          <input class="cbskill" data-i="${f.id}" type="number" data-validate="number" value="${skills[f.id] != null ? skills[f.id] : 0}">
        </label>`
      ).join("")}</div>`;
  }).join("");
  const atkHtml = (c.attack_labels || []).map((f) =>
    `<label>${esc(f.label)} <input class="cbatk" data-key="${esc(f.key)}" type="text" value="${esc(atk[f.key] || "")}"></label>`
  ).join("");
  const equipHtml = (c.equip_slots || []).map((s) => {
    const it = (c.equipped || []).find((x) => (x.location || "") === s.id) || {};
    return `<label>${esc(s.label)}
      <input class="cbequip" data-slot="${esc(s.id)}" value="${esc(it.name || "")}" placeholder="catalog name">
    </label>`;
  }).join("");
  const lootHtml = (c.loot || []).map((it, i) =>
    `<div class="cblootrow">
      <input class="cblootname" data-i="${i}" value="${esc(it.name || "")}">
      <input class="cblootqty" data-i="${i}" value="${esc(it.quantity || "")}" placeholder="qty">
      <button type="button" class="cblootdel" data-i="${i}">Remove</button>
    </div>`).join("");
  preview.innerHTML = `<div class="cb-preview">
      <canvas id="cbview" width="360" height="320"></canvas>
      <p class="note" id="cbviewnote"></p>
      <label>model <select id="cbmodel">${modelOpts}</select></label>
      <label>Model_Type <input id="cbmtype" value="${esc(c.model_type || "")}"></label>
      <p class="note">${c.model_resolved && c.model_resolved !== c.model
        ? "Chars.tbl Model " + esc(c.model || "") + " maps to " + esc(c.model_resolved)
        : "Models.def row " + esc(selectedModel || c.model || "")}${spr.adf ? " · " + esc(spr.adf) : ""}${spr.kind ? " · " + esc(spr.kind) : ""}</p>
      <h3>Model sprites</h3>
      <p class="note">${spr.kind === "container"
        ? esc(spr.note || "Container2D has no sprite in its ADF — the picture is painted in the scene.")
        : "Shared meshes (Alan, goblin, …) pick a look frame and a *Palette.bmp. Save writes Models.def so you can clone a new enemy without a new ADF."}</p>
      <div class="cb-stats">
        <label>look <input id="cblook" type="number" data-validate="number" value="${look0}"></label>
        <label>face expr <input id="cbface" type="number" min="0" data-validate="number" value="0"></label>
        <label>palette <select id="cbpal">${palOpts || `<option value="${esc(spr.palette || "")}">${esc(spr.palette || "")}</option>`}</select></label>
        <label>head <select id="cbhead">${headOpts || `<option value="">NO_HEAD_SWAP</option>`}</select></label>
      </div>
      <div class="tools">
        <button type="button" id="cbpreview">Refresh preview</button>
        <button type="button" id="cbmodelsave">Save model sprites</button>
        <label class="layerchk"><input type="checkbox" id="cbwire"> wireframe</label>
        <label class="layerchk"><input type="checkbox" id="cbbones"> joints</label>
        <label class="layerchk"><input type="checkbox" id="cbcollide"> collision</label>
      </div>
      <label>new model name <input id="cbdupname" placeholder="Thug #5"></label>
      <div class="tools">
        <button type="button" id="cbmodeldup">Duplicate as new model</button>
      </div>
      ${spriteHtml ? `<div id="cbsheets">${spriteHtml}</div>` : `<p class="note">${spr.kind === "container" ? "No simple-sprite frames on Container2D.adf." : "No simple-sprite sheets on this ADF."}</p>`}
    </div>`;
  wireInspector(preview);
  mountInspector(sheet, {
    title: c.name,
    notes: [
      "bit " + (c.class_bit == null ? "—" : c.class_bit) +
        " · kill XP " + (c.kill_xp || 0) + " (level × (health + 2 × spell points))",
    ],
    extra: `<div class="cb-sheet">
      <div class="cb-stats">
        <label>class <select id="cbclstoken">${classOpts}</select></label>
        <label class="layerchk"><input type="checkbox" id="cbgeneric"${c.generic ? " checked" : ""}> Generic</label>
        <label>aggressive % <input id="cbagg" type="number" data-validate="number" value="${c.style_aggressive || 0}"></label>
        <label>defensive % <input id="cbdef" type="number" data-validate="number" value="${c.style_defensive || 0}"></label>
      </div>
      <h3>Level and experience</h3>
      <div class="cb-stats">
        <label>Level <input id="cblevel" type="number" data-validate="number" value="${c.level || 0}"></label>
        <label>Experience pool <input id="cbexp" type="number" data-validate="number" value="${c.experience || 0}"></label>
      </div>
      <p class="note" id="cbxpnote"></p>
      <h3>Attributes</h3>
      <p class="note">Level / health / spell points are indexes 0, 6, 7. The middle five follow the combat Strength / Agility / Stamina / Reason virtuals; Aura is the leftover slot.</p>
      <div class="cb-stats">${attrHtml}</div>
      <h3>AttackParam</h3>
      <div class="cb-stats">${atkHtml}</div>
      <label>Magic <input id="cbmagic" value="${esc(c.magic || "")}"></label>
      <label>ArmorParam <input id="cbarmor" value="${esc(c.armor || "")}"></label>
      <label>Nationality <input id="cbnat" value="${esc(c.nationality || "")}"></label>
      <label>Trap <input id="cbtrap" value="${esc(c.trap || "None")}"></label>
      <label>Chapter <input id="cbchapter" value="${esc(c.chapter || "")}"></label>
      <h3>Skills</h3>
      <p class="note">22 Skills-line values from combat.md §3. The sheet swaps Life and Change on buttons 18 and 20; this list is storage order.</p>
      ${skillHtml}
      <h3>Equipped</h3>
      <div class="cb-stats">${equipHtml}</div>
      <h3>Loot / bag</h3>
      <div id="cbloot">${lootHtml || `<p class="note">Empty bag.</p>`}</div>
      <div class="tools">
        <button type="button" id="cblootadd">Add loot row</button>
      </div>
      <label>add from catalog <input id="cbitq" type="search" placeholder="Search items…"></label>
      <select id="cbitpick" size="6"></select>
      <div class="tools">
        <label>slot <select id="cbitslot">
          <option value="Pack">Bag / loot</option>
          ${(c.equip_slots || []).map((s) =>
            `<option value="${esc(s.id)}">${esc(s.label)}</option>`).join("")}
        </select></label>
        <button type="button" id="cbituse">Add item</button>
      </div>
      <div class="tools">
        <button class="primary" id="cbcharsave">Save character</button>
      </div>
    </div>`,
  });
  const syncLevelField = () => {
    const lv = el("cblevel");
    const attrLv = box.querySelector('.cbattr[data-key="level"]');
    if (lv && attrLv && document.activeElement === lv) attrLv.value = lv.value;
    if (lv && attrLv && document.activeElement === attrLv) lv.value = attrLv.value;
  };
  if (el("cblevel")) el("cblevel").oninput = syncLevelField;
  const attrLv = box.querySelector('.cbattr[data-key="level"]');
  if (attrLv) attrLv.oninput = syncLevelField;
  const runXp = async () => {
    const cls = el("cbclstoken") ? el("cbclstoken").value : (c.class_token || "Thief");
    const pool = el("cbexp") ? el("cbexp").value : "0";
    try {
      const doc = await api("/api/combat/xp?class=" + encodeURIComponent(cls) +
        "&pool=" + encodeURIComponent(pool || "0"));
      if (el("cbxpnote")) {
        el("cbxpnote").textContent = "From this pool: level " + doc.level +
          " · next threshold " + doc.next +
          (doc.gains ? " · HP gain " + doc.gains.hp + (doc.gains.sp ? " · SP " + doc.gains.sp : "") : "") +
          (doc.note ? " · " + doc.note : "");
      }
    } catch (e) {
      if (el("cbxpnote")) el("cbxpnote").textContent = e.message;
    }
  };
  if (el("cbclstoken")) el("cbclstoken").onchange = runXp;
  if (el("cbexp")) el("cbexp").oninput = runXp;
  runXp();
  const catalog = Object.create(null);
  const rememberItem = (it) => {
    if (it && it.name) catalog[it.name] = it;
  };
  (c.equipped || []).concat(c.loot || []).forEach(rememberItem);
  const gearStem = (name) => {
    if (!name) return "";
    const hit = catalog[name] || (c.equipped || []).find((x) => x.name === name);
    return (hit && hit.preview && hit.preview.gear) || "";
  };
  const modelFields = () => {
    const look = el("cblook") ? Number(el("cblook").value) : look0;
    const face = el("cbface") ? Number(el("cbface").value) : 0;
    const palette = el("cbpal") ? el("cbpal").value : (spr.palette || "");
    const head = el("cbhead") ? el("cbhead").value : (spr.head_sprite || "");
    return { look, face, palette, head };
  };
  const previewNow = () => {
    const model = el("cbmodel") ? el("cbmodel").value : c.model;
    const hand = box.querySelector('.cbequip[data-slot="Hand"]');
    const sh = box.querySelector('.cbequip[data-slot="Shield"]');
    const f = modelFields();
    mountCombatPreview(model, gearStem(hand && hand.value), gearStem(sh && sh.value), {
      kit: combatLookKit(f.look, f.face, stride),
      palette: f.palette,
      faceExpr: f.face,
    });
  };
  const bindSpriteClicks = () => {
    box.querySelectorAll(".cbsprite").forEach((img) => {
      img.onclick = () => {
        const i = Number(img.dataset.i);
        const slot = img.dataset.slot || "";
        if (slot === "face" && stride > 0) {
          if (el("cblook")) el("cblook").value = String(Math.floor(i / stride));
          if (el("cbface")) el("cbface").value = String(i % stride);
        } else if (el("cblook")) {
          el("cblook").value = String(i);
        }
        refreshSheets();
        previewNow();
      };
    });
  };
  const refreshSheets = () => {
    const wrap = el("cbsheets");
    if (!wrap) return;
    const f = modelFields();
    const remap = combatPaletteKey(c, f.palette);
    const remapQ = remap ? "&remap=" + encodeURIComponent(remap) : "";
    wrap.innerHTML = (spr.sheets || []).map((sh) => {
      const all = (sh.frames || []).map((fr, i) => Object.assign({ index: i }, fr)).filter((fr) => fr.key);
      const isFace = (sh.slot === "face") || /FACE/i.test(sh.name || "");
      let shown = all;
      if (isFace && stride > 1 && f.look >= 0 && all.length > stride) {
        const start = f.look * stride;
        shown = all.filter((fr) => fr.index >= start && fr.index < start + stride);
      }
      const cur = isFace ? f.look * stride + f.face : f.look;
      return `<div class="cbsheet">
        <p class="note">${esc(sh.name)} · ${esc(sh.slot || sh.kind || "sprite")} · ${all.length} frame${all.length === 1 ? "" : "s"}${isFace ? " · expressions for look " + f.look : ""}</p>
        <div class="cbsprites">${shown.map((fr) =>
          `<img class="cbsprite${fr.index === cur ? " selected" : ""}" data-slot="${esc(sh.slot || "")}" data-i="${fr.index}" src="/api/preview?key=${encodeURIComponent(fr.key)}${remapQ}" title="${esc(fr.name || "")} #${fr.index}" alt="${esc(fr.name || "")}">`
        ).join("")}</div>
      </div>`;
    }).join("");
    bindSpriteClicks();
  };
  if (el("cbmodel")) el("cbmodel").onchange = async () => {
    const model = el("cbmodel").value;
    try {
      const doc = await api("/api/combat/sprites?name=" + encodeURIComponent(model));
      c.model = model;
      c.model_resolved = model;
      c.sprites = doc.sprites || {};
      c.palettes = doc.palettes || c.palettes;
      c.head_sprites = doc.head_sprites || c.head_sprites;
      paintCombatChar(c);
    } catch (e) {
      previewNow();
    }
  };
  if (el("cbpreview")) el("cbpreview").onclick = previewNow;
  const overlay = (id, fn) => {
    const box = el(id);
    if (!box) return;
    box.onchange = () => {
      if (typeof RTKViewer !== "undefined" && RTKViewer[fn]) RTKViewer[fn](box.checked);
    };
  };
  overlay("cbwire", "showWire");
  overlay("cbbones", "showBones");
  overlay("cbcollide", "showCollision");
  ["cblook", "cbface", "cbpal", "cbhead"].forEach((id) => {
    if (el(id)) el(id).onchange = () => { refreshSheets(); previewNow(); };
  });
  bindSpriteClicks();
  box.querySelectorAll(".cbequip").forEach((inp) => {
    inp.onchange = previewNow;
  });
  previewNow();
  const saveModelSprites = async (duplicate) => {
    const f = modelFields();
    const modelName = el("cbmodel") ? el("cbmodel").value : (c.model_resolved || c.model);
    const fields = {
      look: f.look,
      palette: f.palette,
      head_sprite: f.head,
    };
    try {
      let out;
      if (duplicate) {
        const neu = (el("cbdupname") && el("cbdupname").value || "").trim();
        if (!neu) { toast("Name the new model first", true); return; }
        out = await api("/api/combat/model/duplicate", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            source: modelName,
            name: neu,
            character: c.name,
            fields,
          }),
        });
        toast("Created " + neu + " and pointed " + c.name + " at it");
      } else {
        out = await api("/api/combat/model", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            name: modelName,
            character: c.name,
            fields,
          }),
        });
        toast("Saved model sprites for " + modelName);
      }
      await refreshMod();
      await loadCombatChars();
      if (out.character) paintCombatChar(out.character);
    } catch (e) {
      toast("Could not save model: " + e.message, true);
    }
  };
  if (el("cbmodelsave")) el("cbmodelsave").onclick = () => saveModelSprites(false);
  if (el("cbmodeldup")) el("cbmodeldup").onclick = () => saveModelSprites(true);
  const searchItems = async () => {
    const q = el("cbitq").value || "";
    const doc = await api("/api/items?q=" + encodeURIComponent(q));
    const sel = el("cbitpick");
    sel.innerHTML = "";
    (doc.items || []).slice(0, 80).forEach((it) => {
      rememberItem(it);
      sel.add(new Option((it.label || it.name) + " · " + (it.kind || ""), it.name));
    });
  };
  if (el("cbitq")) {
    let t = 0;
    el("cbitq").oninput = () => { clearTimeout(t); t = setTimeout(searchItems, 200); };
    searchItems();
  }
  if (el("cbituse")) {
    el("cbituse").onclick = () => {
      const name = el("cbitpick").value;
      if (!name) { toast("Pick an item first", true); return; }
      const slot = el("cbitslot").value || "Pack";
      if (slot === "Pack") {
        const wrap = el("cbloot");
        const i = wrap.querySelectorAll(".cblootrow").length;
        const row = document.createElement("div");
        row.className = "cblootrow";
        row.innerHTML = `<input class="cblootname" data-i="${i}" value="${esc(name)}">
          <input class="cblootqty" data-i="${i}" value="1" placeholder="qty">
          <button type="button" class="cblootdel">Remove</button>`;
        if (wrap.querySelector("p.note")) wrap.innerHTML = "";
        wrap.appendChild(row);
        row.querySelector(".cblootdel").onclick = () => row.remove();
      } else {
        const inp = box.querySelector('.cbequip[data-slot="' + slot + '"]');
        if (inp) {
          inp.value = name;
          previewNow();
        }
      }
    };
  }
  if (el("cblootadd")) {
    el("cblootadd").onclick = () => {
      const wrap = el("cbloot");
      if (wrap.querySelector("p.note")) wrap.innerHTML = "";
      const row = document.createElement("div");
      row.className = "cblootrow";
      row.innerHTML = `<input class="cblootname" value="">
        <input class="cblootqty" value="1" placeholder="qty">
        <button type="button" class="cblootdel">Remove</button>`;
      wrap.appendChild(row);
      row.querySelector(".cblootdel").onclick = () => row.remove();
    };
  }
  box.querySelectorAll(".cblootdel").forEach((btn) => {
    btn.onclick = () => btn.closest(".cblootrow").remove();
  });
  if (el("cbcharsave")) {
    el("cbcharsave").onclick = async () => {
      if (!inspectorOk(sheet) || !inspectorOk(preview)) {
        toast("Fix the highlighted fields", true);
        return;
      }
      const attributes = {};
      box.querySelectorAll(".cbattr").forEach((inp) => {
        attributes[inp.dataset.key] = Number(inp.value || 0);
      });
      if (el("cblevel")) attributes.level = Number(el("cblevel").value || 0);
      const skillVals = [];
      box.querySelectorAll(".cbskill").forEach((inp) => {
        skillVals[Number(inp.dataset.i)] = Number(inp.value || 0);
      });
      const attack = {};
      box.querySelectorAll(".cbatk").forEach((inp) => {
        attack[inp.dataset.key] = inp.value;
      });
      const inventory = [];
      box.querySelectorAll(".cbequip").forEach((inp) => {
        if (!inp.value.trim()) return;
        inventory.push({ name: inp.value.trim(), location: inp.dataset.slot, equipped: true });
      });
      box.querySelectorAll(".cblootrow").forEach((row) => {
        const name = (row.querySelector(".cblootname") || {}).value || "";
        if (!name.trim()) return;
        inventory.push({
          name: name.trim(),
          quantity: (row.querySelector(".cblootqty") || {}).value || "",
          location: "Pack",
          equipped: false,
        });
      });
      try {
        const out = await api("/api/combat/character", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            name: c.name,
            stats: {
              attributes,
              skills: skillVals,
              attack,
              class_token: el("cbclstoken").value,
              generic: el("cbgeneric").checked,
              style_aggressive: Number(el("cbagg").value || 0),
              style_defensive: Number(el("cbdef").value || 0),
              experience: Number(el("cbexp").value || 0),
              Model: el("cbmodel").value,
              Model_Type: el("cbmtype").value,
              Trap: el("cbtrap").value,
              Magic: el("cbmagic").value,
              ArmorParam: el("cbarmor").value,
              Nationality: el("cbnat").value,
              Chapter: el("cbchapter").value,
            },
            inventory,
          }),
        });
        toast("Saved " + c.name);
        await refreshMod();
        await loadCombatChars();
        if (out.character) paintCombatChar(out.character);
      } catch (e) {
        toast("Could not save: " + e.message, true);
      }
    };
  }
}

// --- Trap studio --------------------------------------------------------

function openTraps() {
  el("detail").innerHTML = studioShell(
    "Trap / lock studio",
    "Layout table DAT_00616f20 is in the exe. Edit CharacterDef.Trap and script SetTrapType. Interface 0x12 art is in the UI studio.",
    `<div class="studio studio-split">
      <div class="studio-side">
        <h3>Layouts</h3>
        <div id="trlayouts"></div>
        <p class="note" id="trnote"></p>
      </div>
      <div class="studio-side">
        <h3>Instances</h3>
        <input id="trq" type="search" placeholder="Filter…">
        <select id="trinst" size="16"></select>
        <div id="trprops" class="proppanel"></div>
      </div>
    </div>`);
  wireTrapStudio();
}

async function wireTrapStudio() {
  const layouts = await api("/api/traps");
  el("trnote").textContent = layouts.note || "";
  el("trlayouts").innerHTML = `<table class="tiny"><thead><tr><th>id</th><th>name</th><th>mech</th></tr></thead>
    <tbody>${(layouts.layouts || []).map((r) =>
      `<tr><td>${r.id}</td><td>${esc(r.name)}</td><td>${esc(r.mechanism)}</td></tr>`
    ).join("")}</tbody></table>
    <p class="note">tools ${(layouts.tools || []).map((t) => t.name).join(", ")}</p>`;
  const load = async () => {
    const doc = await api("/api/traps/instances?q=" + encodeURIComponent(el("trq").value || ""));
    sceneState.traps = doc.instances || [];
    const sel = el("trinst");
    sel.innerHTML = "";
    sceneState.traps.forEach((r, i) => {
      sel.add(new Option(
        (r.scene ? r.scene + " / " : "") + r.name + " · " + (r.trap || ""),
        String(i)));
    });
  };
  el("trq").oninput = () => { clearTimeout(load.t); load.t = setTimeout(load, 160); };
  await load();
  el("trinst").onchange = () => {
    const r = sceneState.traps[Number(el("trinst").value)];
    if (!r) return;
    const opts = ["None"].concat((layouts.layouts || []).map((l) => l.label));
    el("trprops").innerHTML = `<h3>${esc(r.name)}</h3>
      <p class="note">${esc(r.source || "")} ${esc(r.kind || "")} · ${esc(r.key || "")}</p>
      <label>Trap <select id="trval">${opts.map((o) =>
        `<option${o === (r.layout && r.layout.label) || o === r.trap ? " selected" : ""}>${esc(o)}</option>`
      ).join("")}</select></label>
      <button class="primary" id="trsave">Save</button>
      ${r.script ? `<pre class="tiny">${esc(r.script.slice(0, 700))}</pre>` : ""}`;
    el("trsave").onclick = async () => {
      try {
        await api("/api/traps/instance", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            key: r.key, kind: r.block_kind, name: r.block_name,
            trap: el("trval").value,
          }),
        });
        toast("Saved trap on " + r.name);
        await refreshMod();
        load();
      } catch (e) {
        toast("Could not save: " + e.message, true);
      }
    };
  };
}

// --- FX studio ----------------------------------------------------------

function openFx(pendingSpell) {
  if (pendingSpell) sceneState.pendingSpell = pendingSpell;
  el("detail").innerHTML = studioShell(
    "Magic + combat effects",
    "Spell and skill pictures are .bex graphs that swap FX.t3d sprites. Edit the 8-bit sheets or point a set_sprite node at another sprite. Behavior_File plays only in a fight.",
    `<div class="studio studio-split">
      <div class="studio-side">
        <h3>Spells</h3>
        <input id="fxsq" type="search" placeholder="Filter spells…">
        <select id="fxspells" size="10"></select>
        <h3>.bex graphs</h3>
        <input id="fxbq" type="search" placeholder="Filter .bex…">
        <select id="fxbex" size="8"></select>
        <h3>CastOnUse / LaunchFX / tracks</h3>
        <input id="fxiq" type="search" placeholder="Filter items…">
        <select id="fxitems" size="5"></select>
        <input id="fxlq" type="search" placeholder="Filter launches…">
        <select id="fxlaunches" size="5"></select>
        <input id="fxq" type="search" placeholder="Filter tracks…">
        <select id="fxtracks" size="5"></select>
        <div id="fxtrackinfo" class="proppanel"></div>
        <div id="fxspellinfo" class="proppanel"><p class="note">Pick a spell to edit its numbers. Pictures are on the right.</p></div>
      </div>
      <div class="studio-side">
        <div id="fxbexinfo" class="proppanel"><p class="note">Pick a spell or a .bex to see its sprites.</p></div>
        <div id="fxart" class="creator hidden"></div>
      </div>
    </div>`);
  wireFxStudio();
}

function fxThumbUrl(key) {
  return "/api/preview?key=" + encodeURIComponent(key) + "&transparent=1&t=" + Date.now();
}

function renderBexGraphics(doc, opts) {
  opts = opts || {};
  const prefix = opts.prefix || "fx";
  const infoId = opts.info || "fxbexinfo";
  const artId = opts.art || "fxart";
  const nodeId = prefix + "node";
  const pickId = prefix + "sprpick";
  const saveId = prefix + "sprsave";
  const info = el(infoId);
  if (!info) return;
  sceneState.bex = doc;
  const names = doc.sprite_names || [];
  const setSprite = (doc.entries || []).filter((e) => e.type === 9);
  const rows = (doc.entries || []).map((e) => {
    const p = e.params || {};
    const pic = p.sprite || p.fx_file || "";
    const extra = [p.dag_name, p.selector_name, p.duration_ms != null ? (p.duration_ms + "ms") : ""]
      .filter(Boolean).join(" ");
    return `<tr data-id="${e.id}" class="${e.type === 9 ? "fxrow-sprite" : ""}">
      <td>${e.id}${e.active ? " *" : ""}</td>
      <td>${esc(e.type_name)}</td>
      <td>${esc(e.name || "")}</td>
      <td>${esc(pic)}</td>
      <td>${esc(extra)}</td>
      <td>${(e.activate || []).join(",")}</td>
    </tr>`;
  }).join("");
  const gallery = (doc.sprites || []).map((s) => {
    const sheet = (s.sheets || [])[0];
    const img = sheet
      ? `<img src="${fxThumbUrl(sheet.key)}" alt="${esc(s.used_as || s.name)}">`
      : `<span class="muted">no sheet</span>`;
    return `<button type="button" class="fxthumb" data-sprite="${esc(s.used_as || s.name)}">
      ${img}<span>${esc(s.used_as || s.name)}</span></button>`;
  }).join("");
  const swap = setSprite.length
    ? `<label>set_sprite node
        <select id="${nodeId}">${setSprite.map((e) =>
          `<option value="${e.id}">#${e.id} ${(e.params && e.params.sprite) || e.name || ""}</option>`
        ).join("")}</select>
      </label>
      <label>sprite
        <select id="${pickId}">${names.map((n) =>
          `<option value="${esc(n)}">${esc(n)}</option>`
        ).join("")}</select>
      </label>
      <button class="primary" type="button" id="${saveId}">Save sprite on node</button>`
    : "<p class=\"note\">This graph has no set_sprite nodes.</p>";
  info.innerHTML = `<h3>${esc(doc.name || doc.key || ".bex")}</h3>
    <p class="note">${doc.count} nodes · ${esc(doc.note || "")}</p>
    <div class="fxgallery">${gallery || "<p class=\"note\">No FX sprites on this graph.</p>"}</div>
    <div class="tools">${swap}</div>
    <table class="tiny"><thead><tr><th>#</th><th>type</th><th>name</th><th>picture</th><th></th><th>on</th></tr></thead>
    <tbody>${rows}</tbody></table>`;
  if (opts.autoArt !== false) {
    const first = (doc.sprites || []).find((s) => (s.sheets || []).length);
    if (first) openFxArt(first, artId);
  }
  info.querySelectorAll(".fxthumb").forEach((btn) => {
    btn.onclick = () => {
      const rec = (doc.sprites || []).find((s) => (s.used_as || s.name) === btn.dataset.sprite);
      if (rec) openFxArt(rec, artId);
    };
  });
  if (el(nodeId) && el(pickId)) {
    const applyPick = () => {
      const id = Number(el(nodeId).value);
      const e = setSprite.find((x) => x.id === id);
      if (e && e.params && e.params.sprite) el(pickId).value = e.params.sprite;
    };
    el(nodeId).onchange = applyPick;
    applyPick();
  }
  if (el(saveId)) {
    el(saveId).onclick = async () => {
      try {
        const out = await api("/api/fx/bex", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            key: doc.key,
            entry_id: Number(el(nodeId).value),
            sprite: el(pickId).value,
          }),
        });
        toast("Saved sprite on " + (doc.name || "graph"));
        await refreshMod();
        const fresh = out.bex || await api("/api/fx/bex?key=" + encodeURIComponent(doc.key));
        renderBexGraphics(fresh, opts);
      } catch (e) {
        toast("Could not save: " + e.message, true);
      }
    };
  }
}

function openFxArt(sprite, artId) {
  const box = el(artId || "fxart");
  if (!box) return;
  box.classList.remove("hidden");
  const sheets = (sprite.sheets || []).map((s) => ({
    key: s.key,
    name: s.name,
    label: s.name,
    region: "item",
    slot: "fx",
    frame: 0,
    joint: "",
  }));
  if (!window.RTKCreator) {
    box.innerHTML = `<p class="note">Pixel editor script did not load.</p>`;
    return;
  }
  if (!sheets.length) {
    box.innerHTML = `<p class="note">${esc(sprite.name || "PARENT")} is not an FX.t3d sprite.</p>`;
    return;
  }
  RTKCreator.attach({
    el: box,
    panel: () => null,
    api,
    toast,
    refreshMod,
    remount: () => {},
    canEdit: !!(state && state.mod),
    getContext: () => ({ character: "James", kit: {}, regions: {} }),
    setRegions: () => {},
  });
  RTKCreator.loadArt({ sheets, palette: [], palette_key: "" }, { title: sprite.used_as || sprite.name });
}

function selectBexByName(name) {
  if (!name) return;
  const want = name.toLowerCase();
  const box = el("fxbex");
  if (!box) return;
  for (let i = 0; i < box.options.length; i++) {
    const opt = box.options[i];
    if (opt.text.toLowerCase() === want || opt.value.toLowerCase().endsWith("/" + want)) {
      box.selectedIndex = i;
      box.onchange();
      return;
    }
  }
}

const POTION_EFFECT_KEYS = [
  "Effect_AttrType", "Effect_AttrMod", "Effect_AttrValue",
  "Effect_AttrLevel", "Effect_Result", "Effect_Check",
  "Effect_Object", "Effect_SubObject", "Effect_Resist",
];
const POTION_SPELL_FIELDS = [
  "Spell_Type", "Duration", "Duration_Value", "Target_of_Spell",
  "Number_to_Effect", "Behavior_File",
];

function effectKeys(eff) {
  const seen = {};
  const keys = [];
  Object.keys(eff || {}).concat(POTION_EFFECT_KEYS).forEach((k) => {
    if (!seen[k]) { seen[k] = 1; keys.push(k); }
  });
  return keys.length ? keys : POTION_EFFECT_KEYS.slice();
}

function effectBlocksHtml(effects, cls) {
  return (effects && effects.length ? effects : [{}]).map((eff, i) => {
    const keys = effectKeys(eff);
    const rows = keys.map((k) =>
      `<label>${esc(k)} <input class="${cls}k" data-k="${esc(k)}" value="${esc(eff[k] || "")}"></label>`
    ).join("");
    const sum = [eff.Effect_AttrType, eff.Effect_AttrMod, eff.Effect_AttrValue, eff.Effect_Check]
      .filter(Boolean).join(" ");
    return `<div class="${cls}">
      <h3>${esc(sum || ("Effect " + (i + 1)))}
        <button type="button" class="${cls}del" data-i="${i}">Remove</button></h3>
      ${rows}
      <label>add field
        <span class="row">
          <input class="${cls}newk" placeholder="Effect_Resist">
          <input class="${cls}newv" placeholder="value">
        </span>
      </label>
    </div>`;
  }).join("");
}

function collectEffectBlocks(cls) {
  const blocks = [];
  document.querySelectorAll("." + cls).forEach((box) => {
    const rec = {};
    box.querySelectorAll("." + cls + "k").forEach((inp) => {
      if (inp.dataset.k && inp.value !== "") rec[inp.dataset.k] = inp.value;
    });
    const nk = box.querySelector("." + cls + "newk");
    const nv = box.querySelector("." + cls + "newv");
    if (nk && nk.value.trim() && nv) rec[nk.value.trim()] = nv.value;
    blocks.push(rec);
  });
  return blocks;
}

function collectSpellEffects() {
  return collectEffectBlocks("fxeff");
}

function renderSpellEditor(s) {
  sceneState.spell = s;
  const ed = s.editable || {};
  const fields = Object.keys(ed).map((k) =>
    `<label>${esc(k)} <input class="fxfield" data-k="${esc(k)}" value="${esc(ed[k] || "")}"></label>`
  ).join("");
  const effects = effectBlocksHtml(s.effects || [], "fxeff");
  const pic = s.combat_only_picture
    ? "Behavior_File is set — FUN_004a5207 plays it only in a fight."
    : "No Behavior_File — the numbers apply with no picture.";
  el("fxspellinfo").innerHTML = `<p class="note">${esc(s.name || "")} · ${esc(s.klass || "")} ${esc(s.path || "")}</p>
    <p class="note">${esc(pic)}</p>
    ${fields}
    <label>Description <textarea id="fxdesc" rows="3">${esc(s.description || "")}</textarea></label>
    ${effects || "<p class=\"note\">No effect blocks.</p>"}
    <div class="tools">
      <button type="button" id="fxaddeff">Add effect</button>
      <button class="primary" type="button" id="fxsave">Save spell</button>
    </div>
    <p class="note">${esc(s.note || "")}</p>`;
  if (s.behavior) {
    selectBexByName(s.behavior);
    const box = el("fxbex");
    if (box && box.value) box.onchange();
  }
  el("fxaddeff").onclick = () => {
    const next = Object.assign({}, s, {
      effects: (s.effects || []).concat([{}]),
    });
    renderSpellEditor(next);
  };
  document.querySelectorAll(".fxeffdel").forEach((btn) => {
    btn.onclick = () => {
      const i = Number(btn.dataset.i);
      const next = Object.assign({}, s, {
        effects: (s.effects || []).filter((_, n) => n !== i),
      });
      renderSpellEditor(next);
    };
  });
  el("fxsave").onclick = async () => {
    const fieldsOut = {};
    document.querySelectorAll(".fxfield").forEach((inp) => {
      fieldsOut[inp.dataset.k] = inp.value;
    });
    if (el("fxdesc")) fieldsOut.Description = el("fxdesc").value;
    try {
      await api("/api/fx/spell", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: s.name,
          fields: fieldsOut,
          effects: collectSpellEffects(),
        }),
      });
      toast("Saved " + s.name);
      await refreshMod();
      const fresh = await api("/api/fx/spell?name=" + encodeURIComponent(s.name));
      renderSpellEditor(fresh);
    } catch (e) {
      toast("Could not save: " + e.message, true);
    }
  };
}

async function wireFxStudio() {
  const fillTracks = async () => {
    const doc = await api("/api/fx/tracks?q=" + encodeURIComponent(el("fxq").value || ""));
    const sel = el("fxtracks");
    sel.innerHTML = "";
    (doc.tracks || []).forEach((t) => {
      sel.add(new Option(t.file + " — " + (t.label || ""), t.file));
    });
    sceneState.tracks = doc.tracks || [];
  };
  const fillBex = async () => {
    const doc = await api("/api/fx/bex?q=" + encodeURIComponent(el("fxbq").value || ""));
    const sel = el("fxbex");
    sel.innerHTML = "";
    (doc.files || []).forEach((f) => sel.add(new Option(f.name, f.key)));
  };
  const fillSpells = async () => {
    const doc = await api("/api/fx/spells?q=" + encodeURIComponent(el("fxsq").value || ""));
    const sel = el("fxspells");
    const keep = el("fxspells").value;
    sel.innerHTML = "";
    (doc.spells || []).forEach((s) => {
      const mark = s.behavior ? " · " + s.behavior : " · silent";
      sel.add(new Option((s.name || "?") + mark, s.name));
    });
    sceneState.spells = doc.spells || [];
    if (keep) sel.value = keep;
  };
  const fillItems = async () => {
    const doc = await api("/api/fx/items?q=" + encodeURIComponent(el("fxiq").value || ""));
    const sel = el("fxitems");
    sel.innerHTML = "";
    (doc.items || []).forEach((it) => {
      sel.add(new Option((it.label || it.name) + " → " + (it.resolved || it.spell || ""), it.resolved || it.spell));
    });
    sceneState.itemCasts = doc.items || [];
  };
  const fillLaunches = async () => {
    const doc = await api("/api/fx/launches?q=" + encodeURIComponent(el("fxlq").value || ""));
    const sel = el("fxlaunches");
    sel.innerHTML = "";
    (doc.launches || []).forEach((r, i) => {
      const label = r.file + " · " + (r.chapter || "") +
        (r.source ? " ← " + r.source : "");
      sel.add(new Option(label, String(i)));
    });
    sceneState.launches = doc.launches || [];
  };
  el("fxq").oninput = () => { clearTimeout(fillTracks.t); fillTracks.t = setTimeout(fillTracks, 160); };
  el("fxbq").oninput = () => { clearTimeout(fillBex.t); fillBex.t = setTimeout(fillBex, 160); };
  el("fxsq").oninput = () => { clearTimeout(fillSpells.t); fillSpells.t = setTimeout(fillSpells, 160); };
  el("fxiq").oninput = () => { clearTimeout(fillItems.t); fillItems.t = setTimeout(fillItems, 160); };
  el("fxlq").oninput = () => { clearTimeout(fillLaunches.t); fillLaunches.t = setTimeout(fillLaunches, 160); };
  await fillTracks();
  await fillBex();
  await fillSpells();
  await fillItems();
  await fillLaunches();
  el("fxtracks").onchange = () => {
    const t = (sceneState.tracks || []).find((x) => x.file === el("fxtracks").value);
    if (!t) return;
    el("fxtrackinfo").innerHTML = `<p class="note">${esc(t.label)} · mask ${esc(t.mask || "")}</p>
      <p class="note">${t.key ? esc(t.key) : "track file not in the index"}</p>
      ${t.key ? `<button id="fxpreview">Preview on James</button>` : ""}`;
    const btn = el("fxpreview");
    if (btn) {
      btn.onclick = () => {
        state.anim = t.key;
        openCharacters();
        toast("Character studio — pick anim " + t.file + " if it is compatible.");
      };
    }
  };
  el("fxbex").onchange = async () => {
    const doc = await api("/api/fx/bex?key=" + encodeURIComponent(el("fxbex").value));
    renderBexGraphics(doc);
  };
  el("fxspells").onchange = async () => {
    const name = el("fxspells").value;
    if (!name) return;
    const s = await api("/api/fx/spell?name=" + encodeURIComponent(name));
    renderSpellEditor(s);
  };
  el("fxitems").onchange = async () => {
    const name = el("fxitems").value;
    if (!name) return;
    el("fxspells").value = name;
    try {
      const s = await api("/api/fx/spell?name=" + encodeURIComponent(name));
      renderSpellEditor(s);
    } catch (e) {
      toast("No MagicResult row named " + name + " — " + e.message, true);
    }
  };
  el("fxlaunches").onchange = () => {
    const i = Number(el("fxlaunches").value);
    const r = (sceneState.launches || [])[i];
    if (r) selectBexByName(r.file);
  };
  const pending = sceneState.pendingSpell;
  sceneState.pendingSpell = "";
  if (pending) {
    el("fxspells").value = pending;
    if (el("fxspells").value === pending) el("fxspells").onchange();
  }
}

// --- Alchemy studio -----------------------------------------------------

function openAlchemy() {
  el("detail").innerHTML = studioShell(
    "Alchemy bench",
    "Forty ROM formulas at 0x612e28. Every potion has a bag icon in RTKRES (weak and strong share one). Combat .bex pictures are separate and only play in a fight.",
    `<div class="studio studio-split">
      <div class="studio-side">
        <h3>Formulas</h3>
        <input id="alq" type="search" placeholder="Filter formulas…">
        <select id="allist" size="16"></select>
        <div id="albench" class="proppanel"></div>
      </div>
      <div class="studio-side">
        <div id="alform" class="proppanel"><p class="note">Pick a formula.</p></div>
        <div id="albrew" class="proppanel"></div>
      </div>
    </div>`);
  wireAlchemyStudio();
}

function renderBrew(odds, disaster, states) {
  const o = odds || {};
  const d = disaster || {};
  el("albrew").innerHTML = `<h3>Brew roll (FUN_00556840)</h3>
    <label>Alchemy skill <input id="alskill" type="number" min="0" max="200" value="${esc(o.skill || 0)}"></label>
    <label class="layerchk"><input id="alring" type="checkbox"> Alchemist Ring (+35)</label>
    <label>Formula state
      <select id="alstate">
        <option value="1">1 — recipe / starter, no roll</option>
        <option value="2">2 — discovered, disaster 0.1</option>
        <option value="3">3 — blank page, disaster 0.2</option>
      </select>
    </label>
    <label>Disaster table roll (1–100) <input id="alroll" type="number" min="1" max="100" value="${esc(d.roll || 1)}"></label>
    <p class="note">success ${esc(o.success || "—")} · fail ${esc(o.plain_fail || "—")} · disaster ${esc(o.disaster || "—")}</p>
    <p class="note">${esc(o.note || "")}</p>
    <p class="note">If disaster, destroy: ${(d.tools || []).map(esc).join(", ") || "—"}</p>
    <p class="note">${esc((states && states[o.state]) || "")}</p>`;
}

async function refreshBrew() {
  const skill = el("alskill") ? el("alskill").value : "50";
  const ring = el("alring") && el("alring").checked ? "35" : "0";
  const state = el("alstate") ? el("alstate").value : "3";
  const roll = el("alroll") ? el("alroll").value : "1";
  const keepRing = el("alring") && el("alring").checked;
  const keepState = state;
  const keepRoll = roll;
  const keepSkill = skill;
  const doc = await api(
    "/api/alchemy/odds?skill=" + encodeURIComponent(skill) +
    "&state=" + encodeURIComponent(state) +
    "&ring=" + encodeURIComponent(ring) +
    "&roll=" + encodeURIComponent(roll));
  renderBrew(doc.odds, doc.disaster, doc.states);
  if (el("alskill")) el("alskill").value = keepSkill;
  if (el("alring")) el("alring").checked = keepRing;
  if (el("alstate")) el("alstate").value = keepState;
  if (el("alroll")) el("alroll").value = keepRoll;
  ["alskill", "alring", "alstate", "alroll"].forEach((id) => {
    const node = el(id);
    if (!node) return;
    node.onchange = node.oninput = () => {
      clearTimeout(refreshBrew.t);
      refreshBrew.t = setTimeout(refreshBrew, 120);
    };
  });
}

async function wireAlchemyStudio() {
  let catalog;
  try {
    catalog = await api("/api/alchemy");
  } catch (e) {
    el("alform").innerHTML = `<p class="note">Could not load alchemy: ${esc(e.message)}</p>`;
    return;
  }
  sceneState.formulas = catalog.formulas || [];
  sceneState.alchemyIcons = catalog.icons || [];
  const bench = catalog.bench || {};
  const fillList = () => {
    const q = (el("alq").value || "").toLowerCase();
    const sel = el("allist");
    sel.innerHTML = "";
    sceneState.formulas.forEach((f) => {
      const blob = (f.name + " " + (f.reagents || []).join(" ")).toLowerCase();
      if (q && blob.indexOf(q) < 0) return;
      const tag = f.starter ? " ★" : "";
      const sum = (f.item && f.item.effect_summary) ? " · " + f.item.effect_summary : "";
      const pic = (f.item && f.item.behavior) ? " · " + f.item.behavior : "";
      sel.add(new Option(
        f.id + "  " + f.name + "  lv" + f.level + tag + pic + sum, String(f.id)));
    });
  };
  el("alq").oninput = fillList;
  fillList();
  el("albench").innerHTML = `<h3>Bench</h3>
    <p class="note">${esc(bench.note || "")} Skill index ${esc(String(bench.skill_index))} · ${esc(bench.class_bit || "")}.</p>
    <p class="note">Starters: ${(bench.starters || []).map(esc).join(", ")}</p>
    <p class="note">Flask ${esc((bench.flask && bench.flask.name) || "Flask")} is not a reagent slot.</p>
    <table class="tiny"><thead><tr><th>#</th><th>reagent</th><th>tool</th></tr></thead>
    <tbody>${(bench.reagents || []).map((r) =>
      `<tr><td>${r.slot}</td><td>${esc(r.name)}</td><td>${esc(r.tool)}</td></tr>`
    ).join("")}</tbody></table>
    <table class="tiny"><thead><tr><th>tool</th><th>catalog</th></tr></thead>
    <tbody>${(bench.tools || []).map((t) =>
      `<tr><td>${esc(t.name)}</td><td>${esc(t.catalog)}</td></tr>`
    ).join("")}</tbody></table>
    <p class="note">Recipes: ${(bench.recipes || []).map((r) => esc(r.name || r.label)).join(", ") || "none"}</p>`;
  await refreshBrew();
  const paintFormula = (rec) => {
    const it = rec.item || {};
    const spell = rec.spell || null;
    const ed = (spell && spell.editable) || {};
    const spellFields = POTION_SPELL_FIELDS.map((k) =>
      `<label>${esc(k)} <input class="alspfield" data-k="${esc(k)}" value="${esc(ed[k] || "")}"></label>`
    ).join("");
    const icon = (it && it.icon) || null;
    const iconPick = (sceneState.alchemyIcons || []).map((ic) =>
      `<option value="${esc(ic.key)}"${icon && ic.key === icon.key ? " selected" : ""}>${esc(ic.name)}</option>`
    ).join("");
    el("alform").innerHTML = `<h3>${esc(rec.name)}</h3>
      <p class="note">ROM rec ${rec.id} · level ${rec.level} · list price ${rec.price}${rec.starter ? " · starter" : ""}</p>
      <h3>Inventory icon</h3>
      <div id="aliconbox">${icon
        ? `<div class="fxgallery">
            <button type="button" class="fxthumb" id="aliconthumb">
              <img src="${fxThumbUrl(icon.key)}" alt="${esc(icon.name)}">
              <span>${esc(icon.name)}</span>
            </button>
          </div>
          <p class="note">RTKRES ${esc(icon.name)} (${icon.id}). Weak and strong of a family share this bitmap.</p>
          <label>Replace with
            <select id="aliconpick">${iconPick}</select>
          </label>
          <div class="tools">
            <button type="button" id="aliconcopy">Use this icon</button>
          </div>
          <div id="aliconart" class="creator"></div>`
        : `<p class="note">No inventory bitmap matched this formula.</p>`}</div>
      <p class="note">${esc(rec.note || "")}</p>
      <p class="note">Reagents: ${(rec.reagents || []).map(esc).join(", ")}</p>
      <p class="note">Tools: ${(rec.tools || []).map(esc).join(", ")}</p>
      ${it.name ? `<label>Catalog name <input id="alitname" value="${esc(it.name)}" readonly></label>
        <label>Price <input id="alitprice" value="${esc(it.price || "")}"></label>
        <label>Classification <input id="alitclass" value="${esc(it.classification || "")}"></label>
        <h3>Item Use</h3>
        <label>Effect_Desc <input id="alitdesc" value="${esc(it.effect_desc || "")}"></label>
        <label>Effect_Spell <input id="alitspell" value="${esc(it.effect_spell || "")}"></label>
        <label>Effect_NonCombat <input id="alitnc" value="${esc(it.effect_noncombat || "")}"></label>
        <label>Effect_CastMax <input id="alitcast" value="${esc(it.effect_cast_max || "")}"></label>
        <p class="note">${it.magic_result ? "MagicResult " + esc(it.magic_result) : "No MagicResult row — item modifiers only."}</p>`
        : `<p class="note">No MagicInvItem row matched this formula name.</p>`}
      ${spell ? `<h3>Spell ${esc(spell.name)}</h3>
        <p class="note">${spell.combat_only_picture
          ? "Behavior_File plays only in a fight."
          : "No Behavior_File — numbers apply with no picture."}</p>
        ${spellFields}
        <label>Description <textarea id="alspdesc" rows="3">${esc(spell.description || "")}</textarea></label>
        <h3>Combat picture</h3>
        <div id="alpic"></div>
        <div id="alart" class="creator hidden"></div>
        ${effectBlocksHtml(spell.effects || [], "aleff")}
        <div class="tools">
          <button type="button" id="aladdeff">Add effect</button>
        </div>`
        : `<p class="note">This potion has no spell record. Weak Abjuration is the known case — only the item Use block applies.</p>`}
      <div class="tools">
        <button class="primary" id="alsave">Save effects</button>
        ${spell ? `<button type="button" id="alspell">Open in Effects</button>` : ""}
      </div>`;
    sceneState.alchemyRec = rec;
    if (el("aladdeff")) {
      el("aladdeff").onclick = () => {
        const next = Object.assign({}, rec, {
          spell: Object.assign({}, spell, {
            effects: (spell.effects || []).concat([{}]),
          }),
        });
        paintFormula(next);
      };
    }
    document.querySelectorAll(".aleffdel").forEach((btn) => {
      btn.onclick = () => {
        const i = Number(btn.dataset.i);
        const next = Object.assign({}, rec, {
          spell: Object.assign({}, spell, {
            effects: (spell.effects || []).filter((_, n) => n !== i),
          }),
        });
        paintFormula(next);
      };
    });
    if (el("alsave")) {
      el("alsave").onclick = async () => {
        const fieldsOut = {};
        document.querySelectorAll(".alspfield").forEach((inp) => {
          fieldsOut[inp.dataset.k] = inp.value;
        });
        if (el("alspdesc")) fieldsOut.Description = el("alspdesc").value;
        try {
          await api("/api/alchemy/item", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              name: it.name,
              fields: it.name ? {
                Price: el("alitprice").value,
                Classification: el("alitclass").value,
              } : undefined,
              effect_fields: it.name ? {
                Effect_Desc: el("alitdesc").value,
                Effect_Spell: el("alitspell").value,
                Effect_NonCombat: el("alitnc").value,
                Effect_CastMax: el("alitcast").value,
              } : undefined,
              spell: spell ? {
                name: spell.name,
                fields: fieldsOut,
                effects: collectEffectBlocks("aleff"),
              } : undefined,
            }),
          });
          toast("Saved " + (it.name || rec.name));
          await refreshMod();
          const cat = await api("/api/alchemy");
          sceneState.formulas = cat.formulas || [];
          const keep = String(rec.id);
          fillList();
          if (el("allist")) el("allist").value = keep;
          const fresh = await api("/api/alchemy/formula?id=" + encodeURIComponent(keep));
          paintFormula(fresh);
        } catch (e) {
          toast("Could not save: " + e.message, true);
        }
      };
    }
    if (el("alspell")) {
      el("alspell").onclick = () => openFx(it.magic_result || it.effect_spell);
    }
    if (icon) {
      const openIcon = () => openFxArt({
        name: icon.name,
        used_as: icon.name,
        sheets: [{ key: icon.key, name: icon.name }],
      }, "aliconart");
      if (el("aliconthumb")) el("aliconthumb").onclick = openIcon;
      openIcon();
      if (el("aliconcopy")) {
        el("aliconcopy").onclick = async () => {
          const src = el("aliconpick") && el("aliconpick").value;
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
            const fresh = await api("/api/alchemy/formula?id=" + encodeURIComponent(String(rec.id)));
            paintFormula(fresh);
          } catch (e) {
            toast("Could not copy icon: " + e.message, true);
          }
        };
      }
    }
    if (el("alpic")) {
      if (rec.picture && rec.picture.key) {
        renderBexGraphics(rec.picture, {
          prefix: "al", info: "alpic", art: "alart", autoArt: false,
        });
      } else {
        el("alpic").innerHTML = `<p class="note">No picture on this potion. Set Behavior_File to a .bex (for example zpotfoil.bex), save, then you can swap or edit its sprites here.</p>`;
      }
    }
  };
  el("allist").onchange = async () => {
    const rec = await api("/api/alchemy/formula?id=" + encodeURIComponent(el("allist").value));
    paintFormula(rec);
  };
}

// --- Shops / loadout ----------------------------------------------------

function openShops() {
  el("detail").innerHTML = studioShell(
    "Shops + starting inventories",
    "Shop defs and Chars.tbl InventoryItems. Catalog, mesh, and pixels stay in the Item editor.",
    `<div class="studio studio-split">
      <div class="studio-side">
        <h3>Shops</h3>
        <input id="shq" type="search" placeholder="Filter shops…">
        <select id="shlist" size="12"></select>
        <div id="shform" class="proppanel"></div>
      </div>
      <div class="studio-side">
        <h3>Starting loadouts</h3>
        <input id="loq" type="search" placeholder="Filter characters…">
        <select id="lolist" size="12"></select>
        <div id="loform" class="proppanel"></div>
      </div>
    </div>`);
  wireShopStudio();
}

async function wireShopStudio() {
  const fillShops = async () => {
    const doc = await api("/api/shops?q=" + encodeURIComponent(el("shq").value || ""));
    const sel = el("shlist");
    sel.innerHTML = "";
    (doc.shops || []).forEach((s) => {
      sel.add(new Option(s.name + " · " + (s.city || "") + " (" + s.items + ")", s.name));
    });
  };
  const fillLoad = async () => {
    const doc = await api("/api/shops/loadouts?q=" + encodeURIComponent(el("loq").value || ""));
    const sel = el("lolist");
    sel.innerHTML = "";
    (doc.loadouts || []).forEach((r) => {
      sel.add(new Option(r.name + " · " + (r.class || "") + " (" + r.items + ")", r.name));
    });
  };
  el("shq").oninput = () => { clearTimeout(fillShops.t); fillShops.t = setTimeout(fillShops, 160); };
  el("loq").oninput = () => { clearTimeout(fillLoad.t); fillLoad.t = setTimeout(fillLoad, 160); };
  await fillShops();
  await fillLoad();
  el("shlist").onchange = async () => {
    const s = await api("/api/shops/shop?name=" + encodeURIComponent(el("shlist").value));
    const items = (s.items || []).map((it) =>
      it.name + ", " + (it.markup == null ? "" : it.markup) + ", " +
      (it.quantity == null ? "" : it.quantity)).join("\n");
    el("shform").innerHTML = `<label>Gold <input id="shgold" value="${esc((s.fields || {}).Gold || "")}"></label>
      <label>HaggleVar <input id="shhaggle" value="${esc((s.fields || {}).HaggleVar || "")}"></label>
      <label>City <input id="shcity" value="${esc((s.fields || {}).City || "")}"></label>
      <label>StoreItems <textarea id="shitems" rows="14">${esc(items)}</textarea></label>
      <div class="tools">
        <button id="shsavefields">Save fields</button>
        <button class="primary" id="shsaveitems">Save stock</button>
      </div>`;
    el("shsavefields").onclick = async () => {
      try {
        for (const [field, id] of [["Gold", "shgold"], ["HaggleVar", "shhaggle"], ["City", "shcity"]]) {
          await api("/api/shops/shop", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ name: s.name, field, value: el(id).value }),
          });
        }
        toast("Saved shop fields");
        await refreshMod();
      } catch (e) {
        toast("Could not save: " + e.message, true);
      }
    };
    el("shsaveitems").onclick = async () => {
      try {
        await api("/api/shops/shop", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            name: s.name,
            items: el("shitems").value.split(/\r?\n/).map((l) => l.trim()).filter(Boolean),
          }),
        });
        toast("Saved shop stock");
        await refreshMod();
      } catch (e) {
        toast("Could not save: " + e.message, true);
      }
    };
  };
  el("lolist").onchange = async () => {
    const r = await api("/api/shops/loadout?name=" + encodeURIComponent(el("lolist").value));
    const lines = (r.items || []).map((it) => it.raw || it.name).join("\n");
    el("loform").innerHTML = `<p class="note">${esc(r.class || "")} · ${esc(r.model || "")}</p>
      <label>InventoryItems <textarea id="loitems" rows="14">${esc(lines)}</textarea></label>
      <button class="primary" id="losave">Save loadout</button>
      <p class="note">One item per line. Compact rows like <code>Lockpicks</code> or <code>Antidote - Weak,1,1</code>.</p>`;
    el("losave").onclick = async () => {
      try {
        await api("/api/shops/loadout", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            name: r.name,
            items: el("loitems").value.split(/\r?\n/).map((l) => l.trim()).filter(Boolean),
          }),
        });
        toast("Saved loadout for " + r.name);
        await refreshMod();
      } catch (e) {
        toast("Could not save: " + e.message, true);
      }
    };
  };
  const jump = window.rtkJump;
  if (jump && jump.kind === "shop") {
    window.rtkJump = null;
    const sel = el("shlist");
    if (sel && [...sel.options].some((o) => o.value === jump.name)) {
      sel.value = jump.name;
      sel.onchange();
    }
  }
}

// --- Dialog studio ------------------------------------------------------

const DLG_EVENTS = ["OnCanPlay", "Display", "OnStart", "OnEnd", "OnCancel"];

function openDialog() {
  if (typeof RTKViewer !== "undefined" && RTKViewer.unmount) RTKViewer.unmount();
  el("detail").innerHTML = studioShell(
    "Dialog",
    "ConversationDef trees in ChapterN.def. MenuText is the choice label. The wav is a mix — spoken words are not stored. A child needs OnCanPlay; return 2 plays it immediately.",
    `<div class="studio dialogstudio layout3" id="studiolayout" data-studio="opendialog">
      <div class="studio-side">
        <label>chapter <select id="dlgch"></select></label>
        <label>scene <select id="dlgsc"><option value="">All scenes</option></select></label>
        <label>role <select id="dlgroles">
          <option value="">All roles</option>
          <option value="root">ROOT menu</option>
          <option value="form">FORM choice</option>
          <option value="voiced">Voiced TK</option>
          <option value="node">Other</option>
        </select></label>
        <input id="dlgq" type="search" placeholder="Filter name or MenuText…">
        <select id="dlglist" size="18"></select>
        <h3>Add node</h3>
        <label>name <input id="dlgnewname" placeholder="C10110FORM or TK0123M"></label>
        <label>MenuText <input id="dlgnewmenu" placeholder="choice label"></label>
        <div class="tools">
          <button type="button" id="dlgadd">Add in this scene</button>
        </div>
      </div>
      <div class="split" data-edge="side" title="Drag to resize the list"></div>
      <div class="studio-stage" id="dlgeditor">
        <p class="note">Pick a conversation node. The sheet is in the inspector.</p>
      </div>
      <div class="split" data-edge="inspector" title="Drag to resize the inspector"></div>
      <div class="studio-inspector">
        <div id="dlgprops" class="proppanel"><p class="note">Pick a node.</p></div>
      </div>
    </div>`);
  wireLayout(el("studiolayout"));
  wireDialogStudio();
}

async function wireDialogStudio() {
  const boot = await api("/api/dialog");
  const chSel = el("dlgch");
  chSel.innerHTML = `<option value="">All chapters</option>` +
    (boot.chapters || []).map((n) => `<option value="${n}">Chapter ${n}</option>`).join("");
  const fillScenes = async () => {
    const doc = await api("/api/dialog?chapter=" + encodeURIComponent(el("dlgch").value || ""));
    const keep = el("dlgsc").value;
    el("dlgsc").innerHTML = `<option value="">All scenes</option>` +
      (doc.scenes || []).map((s) => `<option value="${esc(s)}">${esc(s)}</option>`).join("");
    if (keep) el("dlgsc").value = keep;
  };
  el("dlgch").onchange = async () => { await fillScenes(); loadDialogList(); };
  el("dlgsc").onchange = loadDialogList;
  el("dlgroles").onchange = loadDialogList;
  el("dlgq").oninput = () => {
    clearTimeout(loadDialogList.t);
    loadDialogList.t = setTimeout(loadDialogList, 160);
  };
  el("dlglist").onchange = async () => {
    const rec = await api("/api/dialog/node?id=" + encodeURIComponent(el("dlglist").value));
    paintDialogNode(rec);
  };
  if (el("dlgadd")) {
    el("dlgadd").onclick = async () => {
      const name = (el("dlgnewname").value || "").trim();
      if (!name) { toast("Name the new node", true); return; }
      const chapter = el("dlgch").value;
      if (chapter === "") { toast("Pick a chapter first", true); return; }
      let scene = el("dlgsc").value;
      const cur = sceneState.dialogNode;
      if (!scene && cur) scene = cur.scene;
      if (!scene) { toast("Pick a scene or open a node in that scene", true); return; }
      try {
        const out = await api("/api/dialog/add", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            chapter: Number(chapter),
            scene,
            name,
            parent: cur && cur.scene === scene ? cur.id : "",
            fields: { MenuText: el("dlgnewmenu").value || "" },
          }),
        });
        toast("Added " + name);
        await refreshMod();
        await loadDialogList();
        if (out.id) {
          el("dlglist").value = out.id;
          const rec = out.node || await api("/api/dialog/node?id=" + encodeURIComponent(out.id));
          paintDialogNode(rec);
        }
      } catch (e) {
        toast("Could not add: " + e.message, true);
      }
    };
  }
  await fillScenes();
  await loadDialogList();
  const jump = window.rtkJump;
  if (jump && jump.kind === "dialog") {
    window.rtkJump = null;
    if (jump.chapter != null && jump.chapter !== "") el("dlgch").value = String(jump.chapter);
    await fillScenes();
    if (jump.scene && el("dlgsc")) el("dlgsc").value = jump.scene;
    if (el("dlgroles")) el("dlgroles").value = "";
    if (el("dlgq")) el("dlgq").value = "";
    await loadDialogList();
    if (jump.id && el("dlglist")) {
      el("dlglist").value = jump.id;
      if (el("dlglist").value === jump.id) {
        const rec = await api("/api/dialog/node?id=" + encodeURIComponent(jump.id));
        paintDialogNode(rec);
      }
    }
  }
}

async function loadDialogList() {
  const sel = el("dlglist");
  if (!sel) return;
  const q = new URLSearchParams({
    q: (el("dlgq") && el("dlgq").value) || "",
    chapter: (el("dlgch") && el("dlgch").value) || "",
    scene: (el("dlgsc") && el("dlgsc").value) || "",
    role: (el("dlgroles") && el("dlgroles").value) || "",
  });
  const doc = await api("/api/dialog?" + q.toString());
  const keep = sel.value;
  sel.innerHTML = "";
  (doc.nodes || []).forEach((n) => {
    const label = n.name + " · " + n.role +
      (n.menu_text ? " — " + n.menu_text : "");
    sel.add(new Option(label, n.id));
  });
  if (keep) sel.value = keep;
}

function dialogEvent(events, name) {
  return (events || []).find((e) => (e.name || "").toLowerCase() === name.toLowerCase()) || {};
}

function paintDialogNode(c) {
  const box = el("dlgeditor");
  const props = el("dlgprops");
  if (!box || !props) return;
  sceneState.dialogNode = c;
  const events = c.events || [];
  const extra = events.filter((e) => !DLG_EVENTS.some((n) => n.toLowerCase() === (e.name || "").toLowerCase()));
  const destHtml = (c.children || []).map((d) =>
    `<button type="button" class="dlgdest" data-id="${esc(d.id || "")}" ${d.id ? "" : "disabled"}>${esc(d.name)}${d.menu_text ? " — " + esc(d.menu_text) : ""}</button>`
  ).join("") || `<p class="note">No PotentialDest children.</p>`;
  const parentHtml = (c.parents || []).map((d) =>
    `<button type="button" class="dlgdest" data-id="${esc(d.id || "")}">${esc(d.name)}</button>`
  ).join("") || `<p class="note">No parent menus point here.</p>`;
  const linkHtml = (c.links || []).map((ln, i) =>
    `<div class="dlglink">
      <input class="dlglslot" data-i="${i}" value="${esc(ln.slot != null ? ln.slot : i)}" title="slot">
      <input class="dlglgroup" data-i="${i}" value="${esc(ln.group || "")}" placeholder="group">
      <input class="dlglmember" data-i="${i}" value="${esc(ln.member || "")}" placeholder="member">
      <input class="dlglchar" data-i="${i}" value="${esc(ln.character || "")}" placeholder="character">
      <button type="button" class="dlgldel">Remove</button>
    </div>`).join("");
  const formHtml = (c.formations || []).map((f, i) =>
    `<div class="dlgform" data-i="${i}">
      <label>group <input class="dlgformg" value="${esc(f.group || "")}"></label>
      <textarea class="dlgformm" rows="4">${esc((f.members || []).map((m) =>
        (m.name || "") + " : " + (m.raw || ((m.xyz || []).join(", ") + ", " + (m.facing || 0)))
      ).join("\n"))}</textarea>
      <button type="button" class="dlgformdel">Remove formation</button>
    </div>`).join("");
  const extraHtml = extra.map((e, i) =>
    `<label>${esc(e.kind || "Event")} <input class="dlgexname" data-i="${i}" value="${esc(e.name || "")}">
      <textarea class="dlgexbody" data-i="${i}" rows="5">${esc(e.body || "")}</textarea>
    </label>`).join("");
  const wav = c.wav_key
    ? `<audio id="dlgwav" controls src="/api/preview?key=${encodeURIComponent(c.wav_key)}"></audio>
       <p class="note">${esc((c.audio && c.audio.path) || "")} · ${esc(c.wav_key)}</p>`
    : `<p class="note">${c.role === "voiced" ? "No wav in the index for this name." : "No performance wav (ROOT / FORM)."}</p>`;
  box.innerHTML = `<div class="dlg-editor">
    <h3>${esc(c.name)} <span class="pill">${esc(c.role)}</span></h3>
    <p class="note">chapter ${c.chapter} · scene ${esc(c.scene || "")} · OnCanPlay ${esc(c.on_can_play || "")}</p>
    <h3>Tree</h3>
    <p class="note">Parents</p>
    <div class="dlgdests">${parentHtml}</div>
    <p class="note">PotentialDest</p>
    <div class="dlgdests">${destHtml}</div>
    <h3>Performance</h3>
    ${wav}
    <p class="note">track ${esc((c.track && c.track.file) || "—")} · trx ${esc(c.trx_key || "—")}</p>
    <h3>Speakers</h3>
    <p class="note">slot, group, member, character. Character is the performance name (can differ from the member).</p>
    <div id="dlglinks">${linkHtml || `<p class="note">No links.</p>`}</div>
    <div class="tools"><button type="button" id="dlgladd">Add speaker</button></div>
    <h3>Formations</h3>
    <div id="dlgforms">${formHtml || `<p class="note">No marks.</p>`}</div>
    <div class="tools"><button type="button" id="dlgformadd">Add formation</button></div>
    <h3>Script events</h3>
    <p class="note">Missing OnCanPlay on a child is return 3 (skipped). return 2 enters this child and drops the menu.</p>
    ${DLG_EVENTS.map((n) => {
      const ev = dialogEvent(events, n);
      return `<label>${n} <textarea class="dlgev" data-name="${n}" rows="6">${esc(ev.body || "")}</textarea></label>`;
    }).join("")}
    ${extraHtml ? `<h3>Other events</h3>${extraHtml}` : ""}
    <div class="tools"><button type="button" id="dlgexadd">Add Frame / Message</button></div>
    <div id="dlgexmore"></div>
  </div>`;
  mountInspector(props, {
    title: c.name,
    notes: [c.role + " · chapter " + c.chapter + " · " + (c.scene || "")],
    fields: [
      { label: "MenuText", id: "dlgmenu", value: c.menu_text || "" },
      { label: "JournalText", id: "dlgjournal", value: c.journal_text || "" },
      { type: "check", id: "dlgaddj", label: "AddToJournal", checked: !!Number(c.add_to_journal) },
      { type: "check", id: "dlgdis", label: "DisableWhenPlayed", checked: !!Number(c.disable_when_played) },
      { type: "check", id: "dlgnav", label: "EnterNavMode", checked: !!Number(c.enter_nav_mode) },
      { type: "check", id: "dlgignf", label: "IgnoreFormations", checked: !!Number(c.ignore_formations) },
      { type: "check", id: "dlgrunf", label: "RunToFormations", checked: !!Number(c.run_to_formations) },
      { type: "check", id: "dlgigno", label: "Ignore other on move", checked: !!Number(c.ignore_other_on_move) },
      { label: "PotentialDest", id: "dlgdest", value: (c.potential_dest || []).join(", ") },
      { label: "UseCameras", id: "dlgcam", value: c.use_cameras || "" },
      { label: "Groups", id: "dlggroups", value: (c.groups || []).join(", "), placeholder: "Party, DyingTalia" },
    ],
    actions: `<button class="primary" id="dlgsave">Save conversation</button>
      <button type="button" id="dlgscene">Show on Scene</button>`,
  });
  box.querySelectorAll(".dlgdest").forEach((btn) => {
    btn.onclick = async () => {
      if (!btn.dataset.id) return;
      const rec = await api("/api/dialog/node?id=" + encodeURIComponent(btn.dataset.id));
      if (el("dlglist")) el("dlglist").value = rec.id;
      paintDialogNode(rec);
    };
  });
  const addLinkRow = (slot, group, member, character) => {
    const wrap = el("dlglinks");
    if (wrap.querySelector("p.note")) wrap.innerHTML = "";
    const i = wrap.querySelectorAll(".dlglink").length;
    const row = document.createElement("div");
    row.className = "dlglink";
    row.innerHTML = `<input class="dlglslot" value="${esc(slot != null ? String(slot) : String(i))}">
      <input class="dlglgroup" value="${esc(group || "")}" placeholder="group">
      <input class="dlglmember" value="${esc(member || "")}" placeholder="member">
      <input class="dlglchar" value="${esc(character || "")}" placeholder="character">
      <button type="button" class="dlgldel">Remove</button>`;
    wrap.appendChild(row);
    row.querySelector(".dlgldel").onclick = () => row.remove();
  };
  box.querySelectorAll(".dlgldel").forEach((btn) => {
    btn.onclick = () => btn.closest(".dlglink").remove();
  });
  if (el("dlgladd")) el("dlgladd").onclick = () => addLinkRow();
  if (el("dlgformadd")) {
    el("dlgformadd").onclick = () => {
      const wrap = el("dlgforms");
      if (wrap.querySelector("p.note")) wrap.innerHTML = "";
      const row = document.createElement("div");
      row.className = "dlgform";
      row.innerHTML = `<label>group <input class="dlgformg" value=""></label>
        <textarea class="dlgformm" rows="4" placeholder="James_m0 : 0, 0, 0, 0"></textarea>
        <button type="button" class="dlgformdel">Remove formation</button>`;
      wrap.appendChild(row);
      row.querySelector(".dlgformdel").onclick = () => row.remove();
    };
  }
  box.querySelectorAll(".dlgformdel").forEach((btn) => {
    btn.onclick = () => btn.closest(".dlgform").remove();
  });
  if (el("dlgexadd")) {
    el("dlgexadd").onclick = () => {
      const wrap = el("dlgexmore");
      const row = document.createElement("label");
      row.innerHTML = `Message <input class="dlgexname" value="Frame0">
        <textarea class="dlgexbody" rows="5"></textarea>`;
      wrap.appendChild(row);
    };
  }
  if (el("dlgscene")) {
    el("dlgscene").onclick = () => {
      openScenes();
      toast("Open scene " + (c.scene || "") + " to see this conversation overlay.");
    };
  }
  if (el("dlgsave")) {
    el("dlgsave").onclick = async () => {
      const links = [];
      box.querySelectorAll(".dlglink").forEach((row) => {
        const character = (row.querySelector(".dlglchar") || {}).value || "";
        const group = (row.querySelector(".dlglgroup") || {}).value || "";
        const member = (row.querySelector(".dlglmember") || {}).value || "";
        if (!character && !group && !member) return;
        links.push({
          slot: (row.querySelector(".dlglslot") || {}).value || "",
          group, member, character,
        });
      });
      const formations = [];
      box.querySelectorAll(".dlgform").forEach((row) => {
        const group = ((row.querySelector(".dlgformg") || {}).value || "").trim();
        if (!group) return;
        const members = [];
        ((row.querySelector(".dlgformm") || {}).value || "").split(/\r?\n/).forEach((line) => {
          const m = line.match(/^([^:]+):\s*(.*)$/);
          if (!m) return;
          members.push({ name: m[1].trim(), raw: m[2].trim() });
        });
        formations.push({ group, members });
      });
      const events = [];
      box.querySelectorAll(".dlgev").forEach((ta) => {
        if (!(ta.value || "").trim()) return;
        events.push({ kind: "Event", name: ta.dataset.name, body: ta.value });
      });
      box.querySelectorAll(".dlgexname").forEach((inp) => {
        const name = (inp.value || "").trim();
        if (!name) return;
        const body = (inp.parentElement.querySelector(".dlgexbody") || {}).value || "";
        const kind = /^frame/i.test(name) ? "Message" : "Event";
        events.push({ kind, name, body });
      });
      try {
        const out = await api("/api/dialog/node", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            id: c.id,
            fields: {
              MenuText: el("dlgmenu").value,
              JournalText: el("dlgjournal").value,
              AddToJournal: el("dlgaddj").checked ? "1" : "0",
              DisableWhenPlayed: el("dlgdis").checked ? "1" : "0",
              EnterNavMode: el("dlgnav").checked ? "1" : "0",
              IgnoreFormations: el("dlgignf").checked ? "1" : "0",
              RunToFormations: el("dlgrunf").checked ? "1" : "0",
              IgnoreOtherGroupMembersOnMoveToFormation: el("dlgigno").checked ? "1" : "0",
              PotentialDest: el("dlgdest").value,
              UseCameras: el("dlgcam").value,
            },
            groups: (el("dlggroups").value || "").split(",").map((s) => s.trim()).filter(Boolean),
            links,
            formations,
            events,
          }),
        });
        toast("Saved " + c.name);
        await refreshMod();
        await loadDialogList();
        if (out.node) paintDialogNode(out.node);
      } catch (e) {
        toast("Could not save: " + e.message, true);
      }
    };
  }
}

function sceneLaunchTarget() {
  const ch = el("scchapter");
  const sc = el("scscene");
  if (!ch || !sc || !ch.value || !sc.value || !sceneState.catalog) return {};
  let num = null;
  for (const c of sceneState.catalog.chapters || []) {
    if (String(c.id) !== String(ch.value)) continue;
    for (const s of c.scenes || []) {
      if (s.id === sc.value && s.num != null) num = s.num;
    }
  }
  const body = { chapter: Number(ch.value) };
  if (num != null) body.scene = Number(num);
  return body;
}

function jumpToHit(hit) {
  window.rtkJump = hit;
  const mark = {
    dialog: "opendialog", item: "openitems", character: "opencombat",
    model: "opencombat", scene: "openscenes", shop: "openshops", binary: "openassets",
  }[hit.kind];
  if (mark && typeof markStudio === "function") markStudio(mark);
  if (hit.kind === "dialog") openDialog();
  else if (hit.kind === "item") openItems();
  else if (hit.kind === "character" || hit.kind === "model") openCombat();
  else if (hit.kind === "scene") openScenes();
  else if (hit.kind === "shop") openShops();
  else if (hit.kind === "binary") {
    state.key = hit.id;
    state.assetScope = "files";
    state.assetQ = hit.name || "";
    openAssets();
  }
}

window.openScenes = openScenes;
window.openUI = openUI;
window.openCombat = openCombat;
window.openTraps = openTraps;
window.openFx = openFx;
window.openAlchemy = openAlchemy;
window.openShops = openShops;
window.openDialog = openDialog;
const LAYOUT_BUILTIN = {
  Map: { studio: "openscenes", side: 240, inspector: 280 },
  Dialog: { studio: "opendialog", side: 280, inspector: 340 },
  Combat: { studio: "opencombat", side: 260, inspector: 420 },
};

function layoutCustom() {
  try { return JSON.parse(localStorage.getItem("rtk-layouts") || "{}"); }
  catch (e) { return {}; }
}

function layoutStore() {
  return Object.assign({}, LAYOUT_BUILTIN, layoutCustom());
}

function paneMemory() {
  try { return JSON.parse(localStorage.getItem("rtk-panes") || "{}"); }
  catch (e) { return {}; }
}

function readPane(root, edge) {
  const prop = edge === "side" ? "--pane-side" : "--pane-insp";
  const n = parseInt((root.style.getPropertyValue(prop) || "").trim(), 10);
  if (Number.isFinite(n) && n > 0) return n;
  const hit = Object.values(LAYOUT_BUILTIN).find((p) => p.studio === root.dataset.studio);
  return edge === "side" ? (hit ? hit.side : 240) : (hit ? hit.inspector : 280);
}

function applyPaneVars(root) {
  if (!root) return;
  const mem = paneMemory()[root.dataset.studio];
  const builtin = Object.values(LAYOUT_BUILTIN).find((p) => p.studio === root.dataset.studio) ||
    { side: 240, inspector: 280 };
  const widths = mem || builtin;
  root.style.setProperty("--pane-side", Math.round(widths.side) + "px");
  root.style.setProperty("--pane-insp", Math.round(widths.inspector) + "px");
}

function rememberPanes(root) {
  if (!root || !root.dataset.studio) return;
  const mem = paneMemory();
  mem[root.dataset.studio] = {
    side: readPane(root, "side"),
    inspector: readPane(root, "inspector"),
  };
  localStorage.setItem("rtk-panes", JSON.stringify(mem));
}

function wireLayout(root) {
  if (!root) return;
  applyPaneVars(root);
  root.querySelectorAll(".split").forEach((bar) => {
    bar.onpointerdown = (ev) => {
      if (ev.button !== 0) return;
      ev.preventDefault();
      bar.setPointerCapture(ev.pointerId);
      const edge = bar.dataset.edge;
      const startX = ev.clientX;
      const start = readPane(root, edge);
      const move = (e) => {
        const dx = e.clientX - startX;
        const next = edge === "side"
          ? Math.min(560, Math.max(180, start + dx))
          : Math.min(720, Math.max(220, start - dx));
        root.style.setProperty(edge === "side" ? "--pane-side" : "--pane-insp", Math.round(next) + "px");
      };
      const up = () => {
        bar.removeEventListener("pointermove", move);
        bar.removeEventListener("pointerup", up);
        rememberPanes(root);
      };
      bar.addEventListener("pointermove", move);
      bar.addEventListener("pointerup", up);
    };
  });
}

function fillLayoutSelect() {
  const sel = el("uilayout");
  if (!sel) return;
  const store = layoutStore();
  const names = Object.keys(LAYOUT_BUILTIN).concat(
    Object.keys(store).filter((n) => !Object.prototype.hasOwnProperty.call(LAYOUT_BUILTIN, n)).sort()
  );
  const cur = localStorage.getItem("rtk-layout") || "Map";
  sel.innerHTML = "";
  names.forEach((n) => sel.add(new Option(n, n)));
  if (store[cur]) sel.value = cur;
}

function applyNamedLayout(name) {
  const preset = layoutStore()[name];
  if (!preset) return;
  localStorage.setItem("rtk-layout", name);
  const mem = paneMemory();
  mem[preset.studio] = { side: preset.side, inspector: preset.inspector };
  localStorage.setItem("rtk-panes", JSON.stringify(mem));
  if (el("layoutname")) el("layoutname").value = name;
  if (typeof markStudio === "function") markStudio(preset.studio);
  const open = {
    openscenes: openScenes,
    opendialog: openDialog,
    opencombat: openCombat,
  }[preset.studio];
  if (open) open();
}

function saveNamedLayout() {
  const root = el("studiolayout");
  if (!root) {
    toast("Open Scene, Dialog, or Combat, then save the layout", true);
    return;
  }
  const name = ((el("layoutname") && el("layoutname").value) ||
    (el("uilayout") && el("uilayout").value) || "").trim();
  if (!name) { toast("Name the layout", true); return; }
  const custom = layoutCustom();
  custom[name] = {
    studio: root.dataset.studio,
    side: readPane(root, "side"),
    inspector: readPane(root, "inspector"),
  };
  localStorage.setItem("rtk-layouts", JSON.stringify(custom));
  localStorage.setItem("rtk-layout", name);
  rememberPanes(root);
  fillLayoutSelect();
  if (el("uilayout")) el("uilayout").value = name;
  toast("Saved layout " + name);
}

function wireLayoutChrome() {
  fillLayoutSelect();
  const sel = el("uilayout");
  if (sel) sel.onchange = () => applyNamedLayout(sel.value);
  const btn = el("layoutsave");
  if (btn) btn.onclick = saveNamedLayout;
  if (el("layoutname") && el("uilayout")) el("layoutname").value = el("uilayout").value || "";
}

wireLayoutChrome();

window.openSearch = function () {
  state.assetScope = state.assetScope && state.assetScope !== "files" ? state.assetScope : "records";
  openAssets();
};
