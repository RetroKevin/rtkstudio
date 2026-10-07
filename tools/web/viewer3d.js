"use strict";

/* global THREE */

// Same expansion as tools/preview.py display_rgb: the 565 sprite blit
// (red mask 0xF800) with the packed bits replicated into the low bits.
function rtkDisplayRgb(rgb) {
  const r = (rgb[0] | 0) & 255, g = (rgb[1] | 0) & 255, b = (rgb[2] | 0) & 255;
  const r5 = r >> 3, g6 = g >> 2, b5 = b >> 3;
  return [(r5 << 3) | (r5 >> 2), (g6 << 2) | (g6 >> 4), (b5 << 3) | (b5 >> 2)];
}

const RTKViewer = {
  _raf: 0,
  _renderer: null,
  _scene: null,
  _camera: null,
  _controls: null,
  _bones: [],
  _meshes: [],
  _data: null,
  _frame: 0,
  _playing: true,
  _last: 0,
  _sel: null,
  _dirty: {},
  _bgColor: "#0d0e11",
  _bgKey: "",
  _bgMesh: null,
  _bgTex: null,
  _live: {},

  async mount(canvas, opts) {
    this.unmount();
    this._dirty = {};
    const char = opts.character || "James";
    const anim = opts.anim || "";
    const qs = new URLSearchParams({ name: char });
    if (anim) qs.set("anim", anim);
    const kit = opts.kit || {};
    Object.keys(kit).forEach((slot) => {
      if (kit[slot] != null && kit[slot] !== "") qs.set("armor_" + slot, String(kit[slot]));
    });
    if (opts.weapon) qs.set("weapon", opts.weapon);
    if (opts.shield) qs.set("shield", opts.shield);
    if (opts.palette) qs.set("palette", opts.palette);
    if (opts.faceExpr != null && opts.faceExpr !== "") qs.set("face_expr", String(opts.faceExpr));
    if (opts.sheathed) qs.set("sheathed", "1");
    if (opts.itemSlot) qs.set("item_slot", opts.itemSlot);
    const isc = opts.itemScale;
    if (isc && typeof isc === "object") {
      if (isc.length != null) qs.set("iscale", String(isc.length));
      if (isc.width != null) qs.set("iscale_w", String(isc.width));
    }
    const regions = opts.regions || {};
    Object.keys(regions).forEach((rid) => {
      const rec = regions[rid];
      if (rec == null || rec === "") return;
      if (typeof rec === "object") {
        if (rec.length != null) qs.set("scale_" + rid, String(rec.length));
        if (rec.width != null) qs.set("scale_" + rid + "_w", String(rec.width));
      } else {
        qs.set("scale_" + rid, String(rec));
      }
    });
    const sceneDoc = await (await fetch(
      "/api/character/scene?" + qs.toString()
    )).json();
    if (sceneDoc.error) throw new Error(sceneDoc.error);
    this._data = sceneDoc;
    this._frame = 0;
    this._playing = true;
    this._sel = null;

    const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: false });
    renderer.setPixelRatio(window.devicePixelRatio || 1);
    renderer.setSize(canvas.clientWidth || 640, canvas.clientHeight || 420, false);
    renderer.setClearColor(
      (opts.bgColor != null && opts.bgColor !== "")
        ? this._parseColor(opts.bgColor) : 0x0d0e11, 1);
    const scene = new THREE.Scene();
    const aspect = (canvas.clientWidth || 640) / Math.max(canvas.clientHeight || 420, 1);
    const camera = new THREE.PerspectiveCamera(40, aspect, 0.1, 100000);
    camera.position.set(8, 6, 14);
    scene.add(camera);
    const controls = new THREE.OrbitControls(camera, canvas);
    controls.target.set(0, 4, 0);
    controls.enablePan = true;
    controls.screenSpacePanning = true;
    controls.panSpeed = 1.2;
    controls.enableZoom = true;
    controls.zoomSpeed = 1.1;
    controls.minDistance = 0.2;
    controls.maxDistance = 50000;
    controls.enableRotate = false;
    controls.update();
    canvas.tabIndex = 0;
    scene.add(new THREE.AmbientLight(0xffffff, 0.7));
    const key = new THREE.DirectionalLight(0xffffff, 0.6);
    key.position.set(2, 4, 3);
    scene.add(key);

    // Engine is Z-up; three.js is Y-up. Same wrapper as export_gltf.py.
    const spin = new THREE.Group();
    spin.rotation.order = "YXZ";
    spin.rotation.y = this._spinY || 0;
    spin.rotation.x = this._spinX || 0;
    const root = new THREE.Group();
    root.rotation.x = -Math.PI / 2;
    spin.add(root);
    scene.add(spin);

    const nodes = sceneDoc.nodes.map(() => new THREE.Group());
    const byIndex = {};
    sceneDoc.nodes.forEach((n, i) => {
      nodes[i].name = n.joint || n.name;
      nodes[i].position.fromArray(n.translation || [0, 0, 0]);
      nodes[i].quaternion.fromArray(n.rotation || [0, 0, 0, 1]);
      const s = n.scale || 1;
      nodes[i].scale.set(s, s, s);
      byIndex[n.i] = nodes[i];
    });
    sceneDoc.nodes.forEach((n, i) => {
      if (n.parent == null) root.add(nodes[i]);
      else (byIndex[n.parent] || nodes[n.parent]).add(nodes[i]);
    });

    const loader = new THREE.TextureLoader();
    const meshes = [];
    for (const m of sceneDoc.meshes) {
      const geo = new THREE.BufferGeometry();
      geo.setAttribute("position", new THREE.Float32BufferAttribute(m.positions, 3));
      if (m.uvs && m.uvs.length) {
        geo.setAttribute("uv", new THREE.Float32BufferAttribute(m.uvs, 2));
      }
      geo.setIndex(m.indices);
      geo.computeVertexNormals();
      const mat = new THREE.MeshBasicMaterial({
        color: 0xffffff,
        side: THREE.DoubleSide,
        transparent: true,
        alphaTest: 0.05,
        depthWrite: true,
      });
      if (m.color && m.color.length >= 3) {
        const shown = rtkDisplayRgb(m.color);
        mat.color.setRGB(shown[0] / 255, shown[1] / 255, shown[2] / 255);
      }
      if (m.texture) {
        let url = "/api/preview?key=" + encodeURIComponent(m.texture) + "&transparent=1";
        if (m.remap) url += "&remap=" + encodeURIComponent(m.remap);
        url += "&t=" + (opts.bust || Date.now());
        const tex = loader.load(url);
        tex.flipY = true;
        tex.magFilter = THREE.NearestFilter;
        tex.minFilter = THREE.NearestFilter;
        tex.wrapS = THREE.RepeatWrapping;
        tex.wrapT = THREE.RepeatWrapping;
        mat.map = tex;
        mat.color.set(0xffffff);
      }
      const mesh = new THREE.Mesh(geo, mat);
      const node = sceneDoc.nodes.find((n) => n.joint === m.joint);
      const region = m.region || (node && node.region) || null;
      mesh.userData = {
        joint: m.joint || "",
        region,
        texture: m.texture || "",
        baseColor: mat.color.getHex(),
      };
      if (node) (byIndex[node.i] || nodes[node.i]).add(mesh);
      meshes.push(mesh);
    }
    this._attachOverlays(opts.overlays || [], sceneDoc.nodes, nodes, byIndex, loader);

    const collision = [];
    const addSphere = (parent, col) => {
      if (!col || !(col.radius > 0) || !parent) return;
      const geo = new THREE.SphereGeometry(col.radius, 20, 12);
      const mat = new THREE.MeshBasicMaterial({
        color: 0x6ec8ff, wireframe: true, depthTest: true,
      });
      const sphere = new THREE.Mesh(geo, mat);
      const c = col.center || [0, 0, 0];
      sphere.position.set(c[0], c[1], c[2]);
      sphere.visible = !!opts.showCollision;
      parent.add(sphere);
      collision.push(sphere);
    };
    const seenJoint = {};
    for (const m of sceneDoc.meshes) {
      if (!m.collision) continue;
      const key = (m.joint || "") + ":" + m.collision.radius;
      if (seenJoint[key]) continue;
      seenJoint[key] = true;
      const node = sceneDoc.nodes.find((n) => n.joint === m.joint);
      addSphere(node ? (byIndex[node.i] || nodes[node.i]) : root, m.collision);
    }
    addSphere(root, sceneDoc.collision);

    const bones = [];
    const bmat = new THREE.LineBasicMaterial({ color: 0xc9a227 });
    sceneDoc.nodes.forEach((n) => {
      if (n.parent == null) return;
      const geo = new THREE.BufferGeometry().setFromPoints([
        new THREE.Vector3(), new THREE.Vector3(),
      ]);
      const line = new THREE.Line(geo, bmat);
      line.visible = !!opts.showBones;
      line.userData = { child: n.i, parent: n.parent };
      scene.add(line);
      bones.push(line);
    });

    this._renderer = renderer;
    this._scene = scene;
    this._camera = camera;
    this._controls = controls;
    this._root = root;
    this._spin = spin;
    this._nodes = nodes;
    this._meshes = meshes;
    this._bones = bones;
    this._collision = collision;
    if (opts.showWire) this.showWire(true);
    this._canvas = canvas;

    const tick = (now) => {
      this._raf = requestAnimationFrame(tick);
      const anim = this._data && this._data.anim;
      if (this._playing && anim && anim.frames > 1) {
        if (!this._last) this._last = now;
        if (now - this._last >= (anim.interval_ms || 33)) {
          this._last = now;
          this._frame = (this._frame + 1) % anim.frames;
          this._applyFrame();
          if (opts.onFrame) opts.onFrame(this._frame, anim.frames);
        }
      }
      this._updateBones();
      this._controls.update();
      this._fitBgPlane();
      this._renderer.render(this._scene, this._camera);
    };
    this._applyFrame();
    this._frameCamera();
    this._bindMoveKeys(canvas);
    this._bindModelRotate(canvas);
    this._onPick = opts.onPick || null;
    if (opts.pickRegion) this.highlightRegion(opts.pickRegion);
    this.applyBackground({ color: opts.bgColor, backdrop: opts.backdrop || "" });
    this._rebindLive();
    this._raf = requestAnimationFrame(tick);
    return sceneDoc;
  },

  applyLiveSheet(key, width, height, pixels, palette) {
    if (!key || !pixels || !width || !height) return;
    this._live = this._live || {};
    let rec = this._live[key];
    if (!rec || rec.width !== width || rec.height !== height) {
      const data = new Uint8Array(width * height * 4);
      const tex = new THREE.DataTexture(data, width, height, THREE.RGBAFormat);
      tex.flipY = true;
      tex.magFilter = THREE.NearestFilter;
      tex.minFilter = THREE.NearestFilter;
      tex.wrapS = THREE.RepeatWrapping;
      tex.wrapT = THREE.RepeatWrapping;
      tex.needsUpdate = true;
      rec = { width, height, tex, data };
      this._live[key] = rec;
    }
    const data = rec.data;
    const n = Math.min(pixels.length, width * height);
    for (let i = 0; i < n; i++) {
      const idx = pixels[i];
      const c = rtkDisplayRgb((palette && palette[idx]) || [0, 0, 0]);
      const o = i * 4;
      if (idx === 0) {
        data[o] = data[o + 1] = data[o + 2] = data[o + 3] = 0;
      } else {
        data[o] = c[0]; data[o + 1] = c[1]; data[o + 2] = c[2]; data[o + 3] = 255;
      }
    }
    rec.tex.needsUpdate = true;
    this._bindLive(key, rec.tex);
  },

  putLivePixel(key, x, y, idx, palette) {
    const rec = this._live && this._live[key];
    if (!rec) return false;
    if (x < 0 || y < 0 || x >= rec.width || y >= rec.height) return false;
    const i = y * rec.width + x;
    const c = rtkDisplayRgb((palette && palette[idx]) || [0, 0, 0]);
    const o = i * 4;
    if (idx === 0) {
      rec.data[o] = rec.data[o + 1] = rec.data[o + 2] = rec.data[o + 3] = 0;
    } else {
      rec.data[o] = c[0]; rec.data[o + 1] = c[1]; rec.data[o + 2] = c[2]; rec.data[o + 3] = 255;
    }
    rec.tex.needsUpdate = true;
    return true;
  },

  _bindLive(key, tex) {
    for (const mesh of this._meshes || []) {
      if (!mesh.material || mesh.userData.texture !== key) continue;
      if (mesh.material.map !== tex) {
        mesh.material.map = tex;
        mesh.material.needsUpdate = true;
      }
    }
  },

  _rebindLive() {
    const live = this._live || {};
    Object.keys(live).forEach((key) => this._bindLive(key, live[key].tex));
  },

  _frameCamera() {
    if (!this._camera || !this._controls || !this._root) return;
    this._root.updateWorldMatrix(true, true);
    const box = new THREE.Box3();
    for (const mesh of this._meshes) {
      mesh.updateWorldMatrix(true, false);
      box.expandByObject(mesh);
    }
    if (box.isEmpty() && this._nodes) {
      const p = new THREE.Vector3();
      for (const n of this._nodes) {
        n.getWorldPosition(p);
        box.expandByPoint(p);
      }
    }
    this._frameBox(box, 1.35);
  },

  frameTexture(key) {
    if (!this._camera || !this._controls) return;
    const box = new THREE.Box3();
    for (const mesh of this._meshes || []) {
      if (!key || mesh.userData.texture !== key) continue;
      mesh.updateWorldMatrix(true, false);
      box.expandByObject(mesh);
    }
    if (box.isEmpty()) {
      this._frameCamera();
      return;
    }
    this._frameBox(box, 0.85);
  },

  _frameBox(box, pull) {
    if (!this._camera || !this._controls || !box || box.isEmpty()) return;
    const size = box.getSize(new THREE.Vector3());
    const center = box.getCenter(new THREE.Vector3());
    const radius = Math.max(size.length() * 0.5, 0.4);
    const fov = this._camera.fov * Math.PI / 180;
    const dist = (radius / Math.tan(fov / 2)) * (pull || 1.35);
    this._camera.near = Math.max(0.05, radius / 500);
    this._camera.far = Math.max(100000, dist * 200);
    this._camera.updateProjectionMatrix();
    this._camera.position.set(
      center.x + dist * 0.45,
      center.y + radius * 0.2,
      center.z + dist
    );
    this._controls.target.copy(center);
    this._controls.minDistance = Math.max(0.2, radius * 0.05);
    this._controls.maxDistance = Math.max(20000, radius * 80);
    this._controls.update();
    this._moveStep = Math.max(0.15, radius * 0.08);
  },

  _bindMoveKeys(canvas) {
    if (this._onKey) {
      window.removeEventListener("keydown", this._onKey);
    }
    this._onKey = (e) => {
      if (!this._camera || !this._controls) return;
      const tag = (e.target && e.target.tagName) || "";
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
      const step = (e.shiftKey ? 3 : 1) * (this._moveStep || 1);
      const cam = this._camera;
      const target = this._controls.target;
      const forward = new THREE.Vector3();
      cam.getWorldDirection(forward);
      const worldUp = new THREE.Vector3(0, 1, 0);
      const right = new THREE.Vector3().crossVectors(forward, worldUp);
      if (right.lengthSq() < 1e-8) right.set(1, 0, 0);
      else right.normalize();
      const flat = forward.clone();
      flat.y = 0;
      if (flat.lengthSq() < 1e-8) flat.copy(forward);
      else flat.normalize();
      const delta = new THREE.Vector3();
      const k = e.key;
      if (e.key === "Alt") {
        this._controls.enableRotate = true;
        return;
      }
      if (k === "w" || k === "W" || k === "ArrowUp") delta.sub(flat);
      else if (k === "s" || k === "S" || k === "ArrowDown") delta.add(flat);
      else if (k === "a" || k === "A" || k === "ArrowLeft") delta.add(right);
      else if (k === "d" || k === "D" || k === "ArrowRight") delta.sub(right);
      else if (k === "q" || k === "Q" || k === "PageDown") delta.y -= 1;
      else if (k === "e" || k === "E" || k === "PageUp") delta.y += 1;
      else if (k === "z" || k === "Z") {
        this._yawModel(step * 0.12);
        e.preventDefault();
        return;
      } else if (k === "c" || k === "C") {
        this._yawModel(-step * 0.12);
        e.preventDefault();
        return;
      } else return;
      e.preventDefault();
      delta.multiplyScalar(step);
      cam.position.add(delta);
      target.add(delta);
      this._controls.update();
    };
    this._onKeyUp = (e) => {
      if (e.key === "Alt" && this._controls) this._controls.enableRotate = false;
    };
    window.addEventListener("keydown", this._onKey);
    window.addEventListener("keyup", this._onKeyUp);
  },

  _yawModel(radians) {
    if (!this._spin) return;
    this._spin.rotation.y += radians;
  },

  _bindModelRotate(canvas) {
    const onDown = (e) => {
      if (e.button !== 0 || e.altKey) return;
      this._drag = { x: e.clientX, y: e.clientY, moved: false };
    };
    const onMove = (e) => {
      if (!this._drag || !this._spin) return;
      const dx = e.clientX - this._drag.x;
      const dy = e.clientY - this._drag.y;
      if (Math.abs(dx) + Math.abs(dy) > 4) this._drag.moved = true;
      if (!this._drag.moved) return;
      this._drag.x = e.clientX;
      this._drag.y = e.clientY;
      this._spin.rotation.y -= dx * 0.008;
      this._spin.rotation.x -= dy * 0.008;
      const lim = Math.PI / 2 - 0.05;
      this._spin.rotation.x = Math.max(-lim, Math.min(lim, this._spin.rotation.x));
    };
    const onUp = (e) => {
      const drag = this._drag;
      this._drag = null;
      if (!drag || drag.moved || e.button !== 0 || e.altKey) return;
      this._pickAt(e.clientX, e.clientY);
    };
    canvas.addEventListener("pointerdown", onDown);
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    this._onPtr = { onDown, onMove, onUp, canvas };
    canvas.style.cursor = "pointer";
  },

  _pickAt(cx, cy) {
    if (!this._camera || !this._canvas || !this._meshes.length) return;
    const rect = this._canvas.getBoundingClientRect();
    const mouse = new THREE.Vector2(
      ((cx - rect.left) / Math.max(rect.width, 1)) * 2 - 1,
      -((cy - rect.top) / Math.max(rect.height, 1)) * 2 + 1
    );
    const ray = new THREE.Raycaster();
    ray.setFromCamera(mouse, this._camera);
    const hits = ray.intersectObjects(this._meshes, false);
    const hit = hits.find((h) => h.object.userData && h.object.userData.region);
    const info = hit ? {
      joint: hit.object.userData.joint,
      region: hit.object.userData.region,
    } : null;
    this.highlightRegion(info && info.region);
    if (info && info.joint) this.selectJoint(info.joint);
    if (typeof this._onPick === "function") this._onPick(info);
  },

  highlightRegion(rid) {
    this._pickRegion = rid || null;
    for (const mesh of this._meshes) {
      const on = rid && mesh.userData.region === rid;
      const base = mesh.userData.baseColor != null ? mesh.userData.baseColor : 0xffffff;
      if (on) mesh.material.color.setHex(0xffe08a);
      else mesh.material.color.setHex(base);
      mesh.material.opacity = !rid || on ? 1 : 0.38;
      mesh.material.transparent = true;
    }
  },

  _applyFrame() {
    const anim = this._data && this._data.anim;
    if (!anim) return;
    const f = this._frame;
    this._data.nodes.forEach((n, i) => {
      const ch = anim.joints[n.joint];
      if (!ch) return;
      const r = ch.r[Math.min(f, ch.r.length - 1)];
      const t = ch.t[Math.min(f, ch.t.length - 1)];
      if (r) this._nodes[i].quaternion.fromArray(r);
      if (t) this._nodes[i].position.fromArray(t);
    });
  },

  _updateBones() {
    const tmp = new THREE.Vector3();
    for (const line of this._bones) {
      const c = this._nodes[line.userData.child];
      const p = this._nodes[line.userData.parent];
      const pos = line.geometry.attributes.position;
      p.getWorldPosition(tmp);
      pos.setXYZ(0, tmp.x, tmp.y, tmp.z);
      c.getWorldPosition(tmp);
      pos.setXYZ(1, tmp.x, tmp.y, tmp.z);
      pos.needsUpdate = true;
    }
  },

  setFrame(i) {
    const anim = this._data && this._data.anim;
    if (!anim) return;
    this._frame = Math.max(0, Math.min(anim.frames - 1, i | 0));
    this._applyFrame();
  },

  play(v) { this._playing = !!v; this._last = 0; },

  showBones(v) {
    for (const b of this._bones || []) b.visible = !!v;
  },

  showWire(v) {
    this._wire = !!v;
    for (const mesh of this._meshes || []) {
      if (mesh.material) mesh.material.wireframe = !!v;
    }
  },

  showCollision(v) {
    for (const sphere of this._collision || []) sphere.visible = !!v;
  },

  selectJoint(name) {
    this._sel = name;
    return this.currentTRS();
  },

  currentTRS() {
    if (!this._sel || !this._data || !this._data.anim) return null;
    const ch = this._data.anim.joints[this._sel];
    if (!ch) return null;
    const f = Math.min(this._frame, ch.r.length - 1);
    const q = ch.r[f];
    const e = new THREE.Euler().setFromQuaternion(new THREE.Quaternion().fromArray(q), "XYZ");
    return {
      joint: this._sel, frame: f,
      t: ch.t[f].slice(),
      e: [e.x, e.y, e.z].map((v) => v * 180 / Math.PI),
      q: q.slice(),
    };
  },

  writeTRS(t, eulerDeg) {
    if (!this._sel || !this._data || !this._data.anim) return;
    const ch = this._data.anim.joints[this._sel];
    if (!ch) return;
    const f = Math.min(this._frame, ch.r.length - 1);
    if (t) ch.t[f] = t.slice();
    if (eulerDeg) {
      const e = new THREE.Euler(
        eulerDeg[0] * Math.PI / 180,
        eulerDeg[1] * Math.PI / 180,
        eulerDeg[2] * Math.PI / 180, "XYZ");
      const q = new THREE.Quaternion().setFromEuler(e);
      ch.r[f] = [q.x, q.y, q.z, q.w];
    }
    const q = ch.r[f];
    this._dirty[this._sel] = this._dirty[this._sel] || {};
    // Engine stores wxyz.
    this._dirty[this._sel][f] = { q: [q[3], q[0], q[1], q[2]], t: ch.t[f].slice() };
    this._applyFrame();
  },

  payload() {
    const frames = {};
    for (const [joint, byF] of Object.entries(this._dirty)) {
      const ch = this._data.anim.joints[joint];
      frames[joint] = ch.t.map((_, i) => {
        if (byF[i]) return byF[i];
        const q = ch.r[i];
        return { q: [q[3], q[0], q[1], q[2]], t: ch.t[i] };
      });
    }
    return { anim: this._data.anim.key, frames };
  },

  _parseColor(value) {
    if (value == null || value === "") return 0;
    if (typeof value === "number") return value;
    const s = String(value).trim();
    if (s.charAt(0) === "#" && (s.length === 7 || s.length === 4)) {
      const hex = s.length === 4
        ? s[1] + s[1] + s[2] + s[2] + s[3] + s[3]
        : s.slice(1);
      const n = parseInt(hex, 16);
      return Number.isNaN(n) ? 0 : n;
    }
    return 0;
  },

  applyBackground(opts) {
    opts = opts || {};
    if (!this._renderer || !this._camera) return;
    if (opts.color != null && opts.color !== "") {
      this._bgColor = opts.color;
      this._renderer.setClearColor(this._parseColor(opts.color), 1);
      if (this._canvas) this._canvas.style.background = opts.color;
    }
    if (!("backdrop" in opts)) {
      this._fitBgPlane();
      return;
    }
    this._bgKey = opts.backdrop || "";
    if (!this._bgKey) {
      this._setBgMap(null);
      return;
    }
    const key = this._bgKey;
    const loader = new THREE.TextureLoader();
    const url = "/api/preview?key=" + encodeURIComponent(key);
    loader.load(url, (tex) => {
      if (!this._camera || this._bgKey !== key) {
        tex.dispose();
        return;
      }
      tex.flipY = false;
      tex.magFilter = THREE.LinearFilter;
      tex.minFilter = THREE.LinearFilter;
      this._setBgMap(tex);
    }, undefined, () => {
      console.error("backdrop failed", url);
    });
  },

  _setBgMap(tex) {
    if (this._bgTex && this._bgTex !== tex) this._bgTex.dispose();
    this._bgTex = tex;
    if (!tex) {
      if (this._bgMesh) this._bgMesh.visible = false;
      return;
    }
    const mesh = this._ensureBgMesh();
    if (mesh.material.map && mesh.material.map !== tex) mesh.material.map.dispose();
    mesh.material.map = tex;
    mesh.material.needsUpdate = true;
    mesh.visible = true;
    this._fitBgPlane();
  },

  _ensureBgMesh() {
    if (this._bgMesh) return this._bgMesh;
    const Geo = THREE.PlaneGeometry || THREE.PlaneBufferGeometry;
    const geo = new Geo(1, 1);
    const mat = new THREE.MeshBasicMaterial({
      depthTest: false,
      depthWrite: false,
      fog: false,
    });
    const mesh = new THREE.Mesh(geo, mat);
    mesh.frustumCulled = false;
    mesh.renderOrder = -1000;
    this._camera.add(mesh);
    if (this._scene && !this._camera.parent) this._scene.add(this._camera);
    this._bgMesh = mesh;
    return mesh;
  },

  _fitBgPlane() {
    const mesh = this._bgMesh;
    const cam = this._camera;
    if (!mesh || !cam) return;
    const dist = Math.max(cam.near * 2, 0.15);
    const viewH = 2 * Math.tan((cam.fov * Math.PI) / 360) * dist;
    const viewW = viewH * cam.aspect;
    const target = 4 / 3;
    let w = viewW, h = viewH;
    if (viewW / viewH > target) w = viewH * target;
    else h = viewW / target;
    mesh.position.set(0, 0, -dist);
    mesh.scale.set(w, h, 1);
  },

  resize() {
    if (!this._renderer || !this._canvas) return;
    const w = this._canvas.clientWidth, h = this._canvas.clientHeight;
    this._camera.aspect = w / Math.max(h, 1);
    this._camera.updateProjectionMatrix();
    this._renderer.setSize(w, h, false);
    this._fitBgPlane();
  },

  _overlayJointName(nodes, slot) {
    const names = (nodes || []).map((n) => n.joint || "").filter(Boolean);
    const find = (re) => names.find((n) => re.test(n));
    if (slot === "Neck") return find(/NECK/i) || find(/HEAD/i);
    if (slot === "LeftRing") {
      return find(/L[-_]?HAN/i) || find(/LEFT.*HAN/i) || find(/HAN.*L/i);
    }
    if (slot === "RightRing") {
      return find(/R[-_]?HAN/i) || find(/RIGHT.*HAN/i) || find(/HAN.*R/i);
    }
    return null;
  },

  _attachOverlays(overlays, sceneNodes, nodes, byIndex, loader) {
    (overlays || []).forEach((ov) => {
      if (!ov || !ov.key) return;
      const joint = this._overlayJointName(sceneNodes, ov.slot);
      const rec = sceneNodes.find((n) => n.joint === joint);
      const parent = rec ? (byIndex[rec.i] || nodes[rec.i]) : null;
      if (!parent) return;
      const url = "/api/preview?key=" + encodeURIComponent(ov.key)
        + "&transparent=1&t=" + Date.now();
      const tex = loader.load(url);
      tex.flipY = true;
      tex.magFilter = THREE.NearestFilter;
      tex.minFilter = THREE.NearestFilter;
      const mat = new THREE.SpriteMaterial({
        map: tex,
        transparent: true,
        depthTest: true,
        alphaTest: 0.05,
      });
      const sprite = new THREE.Sprite(mat);
      const neck = ov.slot === "Neck";
      const s = neck ? 1.15 : 0.42;
      sprite.scale.set(s, s, 1);
      sprite.position.set(0, neck ? 0.05 : 0.08, neck ? 0.22 : 0.12);
      sprite.renderOrder = 4;
      sprite.userData = { joint: joint || "", region: "item", overlay: ov.slot };
      parent.add(sprite);
    });
  },

  unmount() {
    if (this._raf) cancelAnimationFrame(this._raf);
    this._raf = 0;
    if (this._spin) {
      this._spinY = this._spin.rotation.y;
      this._spinX = this._spin.rotation.x;
    }
    if (this._onKey) {
      window.removeEventListener("keydown", this._onKey);
      this._onKey = null;
    }
    if (this._onKeyUp) {
      window.removeEventListener("keyup", this._onKeyUp);
      this._onKeyUp = null;
    }
    if (this._onPtr) {
      this._onPtr.canvas.removeEventListener("pointerdown", this._onPtr.onDown);
      window.removeEventListener("pointermove", this._onPtr.onMove);
      window.removeEventListener("pointerup", this._onPtr.onUp);
      this._onPtr = null;
    }
    this._drag = null;
    if (this._bgMesh) {
      if (this._bgMesh.parent) this._bgMesh.parent.remove(this._bgMesh);
      this._bgMesh.geometry.dispose();
      if (this._bgMesh.material) this._bgMesh.material.dispose();
      this._bgMesh = null;
    }
    if (this._bgTex) {
      this._bgTex.dispose();
      this._bgTex = null;
    }
    this._bgKey = "";
    if (this._canvas) this._canvas.style.backgroundImage = "";
    if (this._renderer) this._renderer.dispose();
    this._renderer = this._scene = this._camera = this._controls = null;
    this._nodes = [];
    this._data = null;
  },
};

window.RTKViewer = RTKViewer;
