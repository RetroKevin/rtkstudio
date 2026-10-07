"use strict";

const RTKCreator = {
  _opts: null,
  _kit: null,
  _sheet: null,
  _pixels: null,
  _width: 0,
  _height: 0,
  _palette: [],
  _index: 1,
  _tool: "pencil",
  _brush: 1,
  _zoom: 4,
  _palettes: [],
  _palSwap: "",
  _sheetPal: null,
  _lastX: 0,
  _lastY: 0,
  _dirtySheet: false,
  _dirtyPal: false,
  _drawing: false,
  _scaleTimer: 0,
  _gen: 0,
  _region: null,
  _joint: "",
  _editing: false,

  attach(opts) {
    this._opts = opts;
    this._renderPanel();
  },

  async loadArt(doc, opts) {
    if (!this._opts) return;
    if (this._dirtySheet && this._sheet) {
      if (!confirm("Discard unsaved pixels on this sheet?")) return;
    }
    const title = (opts && opts.title) || "Item";
    const sheets = (doc && doc.sheets) || [];
    sheets.forEach((s) => { if (!s.region) s.region = "item"; });
    this._kit = {
      sheets,
      palette: (doc && doc.palette) || [],
      palette_key: (doc && doc.palette_key) || "",
      region_defs: [{ id: "item", label: title }],
    };
    if (doc && doc.palette && doc.palette.length) {
      this._palette = doc.palette.map((c) => [c[0], c[1], c[2]]);
    }
    this._region = "item";
    this._editing = true;
    this._dirtySheet = false;
    await this._renderEditor();
  },

  async reload() {
    if (!this._opts) return;
    const gen = ++this._gen;
    let ctx = this._opts.getContext();
    const q = new URLSearchParams({ name: ctx.character || "James" });
    const kit = ctx.kit || {};
    Object.keys(kit).forEach((slot) => {
      if (kit[slot] != null && kit[slot] !== "") q.set("armor_" + slot, String(kit[slot]));
    });
    let doc;
    try {
      doc = await this._opts.api("/api/character/kit?" + q.toString());
    } catch (e) {
      return;
    }
    if (gen !== this._gen) return;
    this._kit = doc;
    if (doc.palette && doc.palette.length) {
      this._palette = doc.palette.map((c) => [c[0], c[1], c[2]]);
    }
    ctx = this._opts.getContext();
    if (!ctx.regions) this._opts.setRegions(cloneRegions(doc.regions));
    if (ctx.pickRegion) this._region = ctx.pickRegion;
    if (ctx.pickJoint) this._joint = ctx.pickJoint;
    this._renderPanel();
    if (this._editing) this._renderEditor();
    else this._hideEditor();
  },

  selectPart(hit) {
    this._region = hit && hit.region;
    this._joint = (hit && hit.joint) || "";
    this._renderPanel();
    if (this._editing) this._renderEditor();
  },

  _regionDef(rid) {
    const defs = (this._kit && this._kit.region_defs) || [];
    return defs.find((d) => d.id === rid) || { id: rid, label: rid || "Part" };
  },

  _lw(rid) {
    const ctx = this._opts.getContext();
    const rec = (ctx.regions && ctx.regions[rid]) || (this._kit && this._kit.regions && this._kit.regions[rid]);
    if (rec && typeof rec === "object") {
      return { length: +rec.length || 1, width: +rec.width || 1 };
    }
    const s = rec != null ? +rec : 1;
    return { length: s, width: s };
  },

  _sheetsFor(rid) {
    return ((this._kit && this._kit.sheets) || []).filter((s) => s.region === rid);
  },

  _panel() {
    const p = this._opts && this._opts.panel;
    if (typeof p === "function") return p();
    return p || document.getElementById("partpanel");
  },

  _renderPanel() {
    const el = this._panel();
    if (!el) return;
    if (el.querySelector("input[data-axis]")) {
      el.querySelectorAll(".partblock").forEach((b) => {
        b.classList.toggle("on", b.dataset.region === this._region);
      });
      return;
    }
    const can = this._opts.canEdit;
    const defs = (this._kit && this._kit.region_defs) || [
      { id: "head", label: "Head" },
      { id: "torso", label: "Torso" },
      { id: "arms", label: "Arms" },
      { id: "legs", label: "Legs" },
    ];
    const blocks = defs.map((def) => {
      const lw = this._lw(def.id);
      const on = this._region === def.id ? " on" : "";
      const n = this._sheetsFor(def.id).length;
      return `<div class="partblock${on}" data-region="${escHtml(def.id)}">
        <h4>${escHtml(def.label)}</h4>
        <label class="pslider">Length
          <input type="range" min="0.25" max="3" step="0.01"
                 data-region="${escHtml(def.id)}" data-axis="length" value="${lw.length}">
          <span class="cval">${lw.length.toFixed(2)}</span>
        </label>
        <label class="pslider">Width
          <input type="range" min="0.25" max="3" step="0.01"
                 data-region="${escHtml(def.id)}" data-axis="width" value="${lw.width}">
          <span class="cval">${lw.width.toFixed(2)}</span>
        </label>
        <button type="button" data-act="sprites" data-region="${escHtml(def.id)}">
          ${this._editing && this._region === def.id ? "Hide sprites" : "Edit sprites"} (${n})
        </button>
      </div>`;
    }).join("");
    el.innerHTML = `
      <h3>Size &amp; shape</h3>
      <p class="note">Click the model or drag a slider. Length moves bones; width is girth.</p>
      ${blocks}
      <div class="creator-tools" style="margin-top:10px">
        <button type="button" class="primary" data-act="save"${can ? "" : " disabled"}>Save sizes</button>
      </div>`;
    el.querySelectorAll("input[type=range]").forEach((sl) => {
      sl.oninput = () => this._slide(sl);
    });
    const save = el.querySelector("[data-act=save]");
    if (save) save.onclick = () => this._saveRegions();
    el.querySelectorAll("[data-act=sprites]").forEach((btn) => {
      btn.onclick = () => {
        const rid = btn.dataset.region;
        if (this._editing && this._region === rid) {
          this._editing = false;
          this._renderPanel();
          this._hideEditor();
          return;
        }
        this._region = rid;
        this._editing = true;
        this._renderPanel();
        this._renderEditor();
      };
    });
  },

  _toggleEditor() {
    this._editing = !this._editing;
    this._renderPanel();
    if (this._editing) this._renderEditor();
    else this._hideEditor();
  },

  _hideEditor() {
    if (this._opts.el) {
      this._opts.el.classList.add("hidden");
      this._opts.el.innerHTML = "";
    }
  },

  async _renderEditor() {
    const el = this._opts.el;
    if (!el) return;
    el.classList.remove("hidden");
    const kit = this._kit || {};
    const can = this._opts.canEdit;
    const rid = this._region;
    const sheets = rid ? this._sheetsFor(rid) : (kit.sheets || []);
    const pal = this._palette.length ? this._palette : (kit.palette || []);
    const remap = kit.palette_key
      ? "&remap=" + encodeURIComponent(kit.palette_key) : "";
    const bust = Date.now();
    const def = this._regionDef(rid);
    if (!this._palettes.length) {
      try {
        const doc = await this._opts.api("/api/palettes");
        this._palettes = doc.names || [];
      } catch (e) {
        this._palettes = [];
      }
    }
    const palOpts = [`<option value="">Sheet colours</option>`]
      .concat(this._palettes.map((n) =>
        `<option value="${escHtml(n)}"${n === this._palSwap ? " selected" : ""}>${escHtml(n)}</option>`))
      .join("");
    el.innerHTML = `
      <div class="creator-head">
        <h3>${escHtml(def.label)} - pixel art</h3>
        <span class="muted small">Index 0 is the eraser / magenta. Wheel zooms the sheet.</span>
      </div>
      <div class="creator-grid">
        <div class="creator-sheets" id="csheets">
          ${sheets.map((s) => `
            <button type="button" class="cthumb${this._sheet && this._sheet.key === s.key ? " on" : ""}"
                    data-key="${escHtml(s.key)}" title="${escHtml(s.name)}">
              <img src="/api/preview?key=${encodeURIComponent(s.key)}&transparent=1${remap}&t=${bust}"
                   alt="${escHtml(s.name)}">
              <span>${escHtml(s.label)}</span>
            </button>`).join("") || `<span class="muted small">No sheets on this part.</span>`}
        </div>
        <div class="creator-edit">
          <div class="creator-tools">
            <button type="button" data-tool="pencil">Pencil</button>
            <button type="button" data-tool="circle">Circle</button>
            <button type="button" data-tool="eraser">Eraser</button>
            <button type="button" data-tool="fill">Fill</button>
            <button type="button" data-tool="eyedrop">Eyedropper</button>
            <label class="small muted">size
              <select id="cbrush">
                <option value="1">1x1</option>
                <option value="2">2x2</option>
                <option value="4">4x4</option>
                <option value="8">8x8</option>
              </select>
            </label>
            <span class="cswatch" id="cswatch"></span>
            <span class="small muted" id="cindex">#1</span>
            <button type="button" class="primary" id="csavesheet"${can ? "" : " disabled"}>Save sheet</button>
          </div>
          <div class="creator-tools">
            <button type="button" id="czoomin">Zoom +</button>
            <button type="button" id="czoomout">Zoom -</button>
            <span class="small muted" id="czoomhint">${this._zoom}x</span>
            <button type="button" id="cfocus">Focus in view</button>
          </div>
          <div class="cpixwrap" id="cpixwrap"><canvas id="cpix"></canvas></div>
        </div>
        <div class="creator-side">
          <div class="creator-pal" id="cpal">${this._palHtml(pal)}</div>
          <div class="creator-tools">
            <input type="color" id="cpick" value="#000000" ${can ? "" : "disabled"}>
            <button type="button" class="primary" id="csavepal"${can && kit.palette_key ? "" : " disabled"}>Save palette</button>
          </div>
          <label class="small muted">In-game palette
            <select id="cpalswap">${palOpts}</select>
          </label>
          <p class="note">Swap keeps pixel indices and only changes the colours. Live in the 3D view; save to keep.</p>
        </div>
      </div>`;
    el.querySelectorAll(".cthumb").forEach((btn) => {
      btn.onclick = () => this.openSheet(btn.dataset.key);
    });
    el.querySelectorAll("[data-tool]").forEach((btn) => {
      btn.onclick = () => this._setTool(btn.dataset.tool);
    });
    this._setTool(this._tool);
    if ($id("cbrush")) {
      $id("cbrush").value = String(this._brush || 1);
      $id("cbrush").onchange = () => { this._brush = +$id("cbrush").value || 1; };
    }
    const pix = $id("cpix");
    if (pix) {
      pix.onpointerdown = (e) => this._ptr(e, true);
      pix.onpointermove = (e) => this._ptr(e, false);
      pix.onpointerup = pix.onpointerleave = () => { this._drawing = false; };
    }
    const wrap = $id("cpixwrap");
    if (wrap) {
      wrap.onwheel = (e) => {
        e.preventDefault();
        this._nudgeZoom(e.deltaY < 0 ? 1 : -1);
      };
    }
    if ($id("czoomin")) $id("czoomin").onclick = () => this._nudgeZoom(1);
    if ($id("czoomout")) $id("czoomout").onclick = () => this._nudgeZoom(-1);
    if ($id("cfocus")) $id("cfocus").onclick = () => this._focusView();
    if ($id("cpick")) $id("cpick").oninput = () => this._editColor($id("cpick").value);
    if ($id("csavesheet")) $id("csavesheet").onclick = () => this._saveSheet();
    if ($id("csavepal")) $id("csavepal").onclick = () => this._savePalette();
    if ($id("cpalswap")) $id("cpalswap").onchange = () => this._swapPalette($id("cpalswap").value);
    this._bindPal();
    this._paintSwatch();
    this._markPal();
    const keep = this._sheet && sheets.some((s) => s.key === this._sheet.key)
      ? this._sheet.key : (sheets[0] && sheets[0].key);
    if (keep) await this.openSheet(keep);
    else this._drawEmpty();
  },

  _palHtml(pal) {
    return pal.map((c, i) => {
      const shown = rtkDisplayRgb(c);
      const rgb = `rgb(${shown[0]},${shown[1]},${shown[2]})`;
      const authored = `rgb(${c[0]|0},${c[1]|0},${c[2]|0})`;
      return `<button type="button" class="csw${i === this._index ? " on" : ""}"
                      data-i="${i}" style="background:${rgb}" title="#${i} ${authored}"></button>`;
    }).join("");
  },

  async openSheet(key) {
    if (this._dirtySheet && this._sheet && this._sheet.key !== key) {
      if (!confirm("Discard unsaved pixels on this sheet?")) return;
    }
    const kit = this._kit || {};
    const q = new URLSearchParams({ key });
    if (kit.palette_key) q.set("remap", kit.palette_key);
    let doc;
    try {
      doc = await this._opts.api("/api/character/pixels?" + q.toString());
    } catch (e) {
      if (this._opts.toast) this._opts.toast("Could not load sheet: " + e.message, true);
      return;
    }
    this._sheet = (kit.sheets || []).find((s) => s.key === key) || { key, name: key, label: key };
    this._width = doc.width;
    this._height = doc.height;
    this._pixels = Uint8Array.from(doc.pixels || []);
    if (doc.palette && doc.palette.length) {
      this._palette = doc.palette.map((c) => [c[0], c[1], c[2]]);
      this._sheetPal = this._palette.map((c) => [c[0], c[1], c[2]]);
    }
    this._dirtySheet = false;
    this._palSwap = "";
    if ($id("cpalswap")) $id("cpalswap").value = "";
    const wrap = this._opts.el && this._opts.el.querySelector("#csheets");
    if (wrap) {
      wrap.querySelectorAll(".cthumb").forEach((b) => b.classList.toggle("on", b.dataset.key === key));
    }
    const palEl = $id("cpal");
    if (palEl) palEl.innerHTML = this._palHtml(this._palette);
    this._bindPal();
    this._redraw();
    this._applyZoom();
    this._paintSwatch();
    this._markPal();
    if (this._dirtySheet) this._previewLive();
    if (this._region === "item") this._focusView();
  },

  _bindPal() {
    const palEl = $id("cpal");
    if (!palEl) return;
    palEl.querySelectorAll(".csw").forEach((btn) => {
      btn.onclick = () => {
        this._index = +btn.dataset.i;
        this._paintSwatch();
        this._markPal();
        const c = this._palette[this._index] || [0, 0, 0];
        const pick = $id("cpick");
        if (pick) pick.value = rgbHex(c);
      };
    });
  },

  _setTool(tool) {
    this._tool = tool;
    if (!this._opts.el) return;
    this._opts.el.querySelectorAll("[data-tool]").forEach((b) => {
      b.classList.toggle("on", b.dataset.tool === tool);
    });
  },

  _nudgeZoom(dir) {
    const steps = [1, 2, 3, 4, 6, 8, 12, 16];
    let i = 0;
    let best = 0;
    steps.forEach((z, n) => {
      if (Math.abs(z - (this._zoom || 4)) <= Math.abs(steps[best] - (this._zoom || 4))) best = n;
    });
    i = Math.max(0, Math.min(steps.length - 1, best + dir));
    this._zoom = steps[i];
    this._applyZoom();
  },

  _applyZoom() {
    const canvas = $id("cpix");
    const hint = $id("czoomhint");
    const z = this._zoom || 4;
    if (canvas && this._width) {
      canvas.style.width = (this._width * z) + "px";
      canvas.style.height = (this._height * z) + "px";
    }
    if (hint) hint.textContent = z + "x";
  },

  _focusView() {
    if (typeof RTKViewer === "undefined" || !this._sheet) return;
    RTKViewer.frameTexture(this._sheet.key);
  },

  async _swapPalette(name) {
    this._palSwap = name || "";
    if (!name) {
      if (this._sheetPal && this._sheetPal.length) {
        this._palette = this._sheetPal.map((c) => [c[0], c[1], c[2]]);
      }
    } else {
      try {
        const doc = await this._opts.api("/api/palettes/table?name=" + encodeURIComponent(name));
        this._palette = (doc.palette || []).map((c) => [c[0], c[1], c[2]]);
      } catch (e) {
        this._opts.toast("Could not load palette: " + e.message, true);
        return;
      }
    }
    this._dirtyPal = true;
    const palEl = $id("cpal");
    if (palEl) palEl.innerHTML = this._palHtml(this._palette);
    this._bindPal();
    this._redraw();
    this._paintSwatch();
    this._markPal();
    this._previewLive();
  },

  _ptr(e, down) {
    const canvas = $id("cpix");
    if (!canvas || !this._pixels) return;
    const r = canvas.getBoundingClientRect();
    const x = Math.floor((e.clientX - r.left) * this._width / r.width);
    const y = Math.floor((e.clientY - r.top) * this._height / r.height);
    if (x < 0 || y < 0 || x >= this._width || y >= this._height) return;
    const i = y * this._width + x;
    if (this._tool === "eyedrop" || e.altKey) {
      this._index = this._pixels[i];
      this._paintSwatch();
      this._markPal();
      return;
    }
    if (this._tool === "fill") {
      if (!down) return;
      this._flood(x, y, this._index);
      return;
    }
    if (down) {
      canvas.setPointerCapture(e.pointerId);
      this._drawing = true;
      this._lastX = x;
      this._lastY = y;
      this._stamp(x, y);
      return;
    }
    if (!this._drawing) return;
    this._stroke(this._lastX, this._lastY, x, y);
    this._lastX = x;
    this._lastY = y;
  },

  _stroke(x0, y0, x1, y1) {
    let dx = Math.abs(x1 - x0), dy = Math.abs(y1 - y0);
    const sx = x0 < x1 ? 1 : -1, sy = y0 < y1 ? 1 : -1;
    let err = dx - dy, x = x0, y = y0;
    while (true) {
      this._stamp(x, y);
      if (x === x1 && y === y1) break;
      const e2 = 2 * err;
      if (e2 > -dy) { err -= dy; x += sx; }
      if (e2 < dx) { err += dx; y += sy; }
    }
  },

  _stamp(cx, cy) {
    const next = this._tool === "eraser" ? 0 : this._index;
    const size = this._brush || 1;
    const circle = this._tool === "circle";
    const r = size / 2;
    const x0 = cx - Math.floor((size - 1) / 2);
    const y0 = cy - Math.floor((size - 1) / 2);
    for (let y = y0; y < y0 + size; y++) {
      for (let x = x0; x < x0 + size; x++) {
        if (x < 0 || y < 0 || x >= this._width || y >= this._height) continue;
        if (circle) {
          const dx = (x + 0.5) - (cx + 0.5);
          const dy = (y + 0.5) - (cy + 0.5);
          if (dx * dx + dy * dy > r * r + 0.01) continue;
        }
        const i = y * this._width + x;
        if (this._pixels[i] === next) continue;
        this._pixels[i] = next;
        this._dirtySheet = true;
        this._put(x, y, next);
        this._previewPut(x, y, next);
      }
    }
  },

  _flood(sx, sy, next) {
    const w = this._width, h = this._height;
    const target = this._pixels[sy * w + sx];
    if (target === next) return;
    const stack = [sx, sy];
    let n = 0;
    while (stack.length) {
      const y = stack.pop();
      const x = stack.pop();
      if (x < 0 || y < 0 || x >= w || y >= h) continue;
      const i = y * w + x;
      if (this._pixels[i] !== target) continue;
      this._pixels[i] = next;
      this._put(x, y, next);
      n += 1;
      stack.push(x + 1, y, x - 1, y, x, y + 1, x, y - 1);
    }
    if (n) {
      this._dirtySheet = true;
      this._previewLive();
    }
  },

  _put(x, y, idx) {
    const canvas = $id("cpix");
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    const c = rtkDisplayRgb(this._palette[idx] || [0, 0, 0]);
    ctx.fillStyle = `rgb(${c[0]},${c[1]},${c[2]})`;
    ctx.fillRect(x, y, 1, 1);
  },

  _redraw() {
    const canvas = $id("cpix");
    if (!canvas || !this._pixels) return;
    canvas.width = this._width;
    canvas.height = this._height;
    const ctx = canvas.getContext("2d");
    const img = ctx.createImageData(this._width, this._height);
    const d = img.data;
    for (let i = 0; i < this._pixels.length; i++) {
      const c = rtkDisplayRgb(this._palette[this._pixels[i]] || [0, 0, 0]);
      const o = i * 4;
      d[o] = c[0]; d[o + 1] = c[1]; d[o + 2] = c[2]; d[o + 3] = 255;
    }
    ctx.putImageData(img, 0, 0);
  },

  _drawEmpty() {
    const canvas = $id("cpix");
    if (!canvas) return;
    canvas.width = 128;
    canvas.height = 128;
    canvas.getContext("2d").clearRect(0, 0, 128, 128);
  },

  _paintSwatch() {
    const el = $id("cswatch");
    const hint = $id("cindex");
    const c = this._palette[this._index] || [0, 0, 0];
    const shown = rtkDisplayRgb(c);
    if (el) el.style.background = `rgb(${shown[0]},${shown[1]},${shown[2]})`;
    if (hint) hint.textContent = "#" + this._index;
    const pick = $id("cpick");
    if (pick) pick.value = rgbHex(c);
  },

  _markPal() {
    const palEl = $id("cpal");
    if (!palEl) return;
    palEl.querySelectorAll(".csw").forEach((b) => {
      b.classList.toggle("on", +b.dataset.i === this._index);
    });
  },

  _editColor(hex) {
    const rgb = hexRgb(hex);
    if (!this._palette[this._index]) return;
    this._palette[this._index] = rgb;
    this._dirtyPal = true;
    const btn = this._opts.el && this._opts.el.querySelector(`.csw[data-i="${this._index}"]`);
    if (btn) {
      const shown = rtkDisplayRgb(rgb);
      btn.style.background = `rgb(${shown[0]},${shown[1]},${shown[2]})`;
      btn.title = `#${this._index} rgb(${rgb[0]},${rgb[1]},${rgb[2]})`;
    }
    this._paintSwatch();
    this._redraw();
    this._previewLive();
  },

  _slide(sl) {
    const axis = sl.dataset.axis;
    const v = +sl.value;
    const label = sl.parentElement.querySelector(".cval");
    if (label) label.textContent = v.toFixed(2);
    const rid = sl.dataset.region || this._region;
    if (!rid) return;
    this._region = rid;
    const cur = cloneRegions((this._opts.getContext().regions) || (this._kit && this._kit.regions) || {});
    cur[rid] = cur[rid] || { length: 1, width: 1 };
    if (typeof cur[rid] !== "object") cur[rid] = { length: +cur[rid] || 1, width: +cur[rid] || 1 };
    cur[rid][axis] = v;
    this._opts.setRegions(cur);
    clearTimeout(this._scaleTimer);
    this._scaleTimer = setTimeout(() => this._opts.remount(), 120);
  },

  async _saveSheet() {
    if (!this._sheet || !this._pixels) return;
    try {
      const r = await this._opts.api("/api/character/sheet", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          key: this._sheet.key,
          width: this._width,
          height: this._height,
          pixels: Array.from(this._pixels),
          palette: this._palette,
        }),
      });
      this._dirtySheet = false;
      this._opts.toast(`Saved sheet ${this._sheet.name || this._sheet.key} (${r.bytes} bytes).`);
      await this._opts.refreshMod();
      this._opts.remount();
      if (this._opts.el) {
        this._opts.el.querySelectorAll(".cthumb").forEach((btn) => {
          if (btn.dataset.key !== this._sheet.key) return;
          const img = btn.querySelector("img");
          if (img) img.src = img.src.replace(/&t=\d+/, "&t=" + Date.now());
        });
      }
    } catch (e) {
      this._opts.toast("Could not save sheet: " + e.message, true);
    }
  },

  async _savePalette() {
    const key = this._kit && this._kit.palette_key;
    if (!key) {
      this._opts.toast("This item uses the sheet's own colours. Save sheet writes those.", true);
      return;
    }
    try {
      const r = await this._opts.api("/api/character/palette", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ key, palette: this._palette }),
      });
      this._dirtyPal = false;
      this._opts.toast(`Saved palette (${r.bytes} bytes).`);
      await this._opts.refreshMod();
      this._opts.remount();
      if (this._opts.el) {
        this._opts.el.querySelectorAll(".cthumb img").forEach((img) => {
          img.src = img.src.replace(/&t=\d+/, "&t=" + Date.now());
        });
      }
    } catch (e) {
      this._opts.toast("Could not save palette: " + e.message, true);
    }
  },

  async _saveRegions() {
    const ctx = this._opts.getContext();
    try {
      const r = await this._opts.api("/api/character/kit", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          character: ctx.character,
          regions: ctx.regions || (this._kit && this._kit.regions) || {},
        }),
      });
      this._opts.setRegions(r.regions);
      this._opts.toast("Saved body sizes into the mod.");
      await this._opts.refreshMod();
    } catch (e) {
      this._opts.toast("Could not save sizes: " + e.message, true);
    }
  },

  _previewLive() {
    if (typeof RTKViewer === "undefined" || !this._sheet || !this._pixels) return;
    RTKViewer.applyLiveSheet(
      this._sheet.key, this._width, this._height, this._pixels, this._palette);
  },

  _previewPut(x, y, idx) {
    if (typeof RTKViewer === "undefined" || !this._sheet) return;
    if (!RTKViewer.putLivePixel(this._sheet.key, x, y, idx, this._palette)) {
      this._previewLive();
    }
  },
};

function $id(id) {
  return document.getElementById(id);
}

function cloneRegions(src) {
  const out = {};
  Object.keys(src || {}).forEach((k) => {
    const v = src[k];
    out[k] = v && typeof v === "object" ? { length: +v.length || 1, width: +v.width || 1 } : v;
  });
  return out;
}

function escHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

function rgbHex(c) {
  const h = (n) => ("0" + (n | 0).toString(16)).slice(-2);
  return "#" + h(c[0]) + h(c[1]) + h(c[2]);
}

function hexRgb(hex) {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex || "");
  if (!m) return [0, 0, 0];
  const n = parseInt(m[1], 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

window.RTKCreator = RTKCreator;
