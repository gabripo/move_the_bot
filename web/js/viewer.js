// The 3D view. Everything is drawn in the robot's own coordinates (metres, x forward, y left,
// z up), so numbers on screen match the numbers in ROS.

import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { CSS2DObject, CSS2DRenderer } from "three/addons/renderers/CSS2DRenderer.js";
import { mergeVertices, toCreasedNormals } from "three/addons/utils/BufferGeometryUtils.js";
import URDFLoader from "urdf-loader";

THREE.Object3D.DEFAULT_UP.set(0, 0, 1);

// Camera presets. "operator" looks from behind the robot and a little from its right, so the arm's
// left is still the screen's left (hand control feels natural) but the arm does not hide the objects
// on the table; "side" and "front" are nicer for watching.
export const VIEWS = {
  operator: { position: [-0.34, -0.3, 0.64], target: [0.24, 0.02, 0.05] },
  side: { position: [-0.18, -0.56, 0.52], target: [0.2, 0.0, 0.06] },
  front: { position: [0.66, -0.42, 0.46], target: [0.18, 0.0, 0.06] },
  top: { position: [0.2, -0.001, 1.0], target: [0.2, 0.0, 0.0] },
  // Like "operator", from a little further back: the whole desk fits a portrait recording.
  desk: { position: [-0.4, -0.4, 0.8], target: [0.26, 0.0, 0.03] },
};

export class Viewer {
  constructor(container) {
    this.container = container;
    this.objects = new Map();          // name -> {group, key}
    this.gltf = new GLTFLoader();
    this.robot = null;

    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0x10151c);
    this.scene.fog = new THREE.Fog(0x10151c, 1.6, 3.2);

    this.camera = new THREE.PerspectiveCamera(42, 1, 0.01, 20);
    this.camera.position.set(...VIEWS.operator.position);

    this.renderer = new THREE.WebGLRenderer({ antialias: true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    container.appendChild(this.renderer.domElement);

    this.labels = new CSS2DRenderer();
    this.labels.domElement.className = "labels";
    container.appendChild(this.labels.domElement);

    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.target.set(...VIEWS.operator.target);
    this.controls.enableDamping = true;
    this.controls.maxPolarAngle = Math.PI / 2 - 0.02;
    this.controls.minDistance = 0.25;
    this.controls.maxDistance = 2.0;

    this._lights();
    this._table();
    this._handMarker();

    new ResizeObserver(() => this.resize()).observe(container);
    this.resize();
    this.renderer.setAnimationLoop(() => {
      this.controls.update();
      this.renderer.render(this.scene, this.camera);
      this.labels.render(this.scene, this.camera);
    });
  }

  // Glide to a camera preset.
  setView(name) {
    const view = VIEWS[name];
    if (!view) return;
    const fromP = this.camera.position.clone(), fromT = this.controls.target.clone();
    const toP = new THREE.Vector3(...view.position), toT = new THREE.Vector3(...view.target);
    const start = performance.now();
    const step = () => {
      const t = Math.min(1, (performance.now() - start) / 500), k = t * t * (3 - 2 * t);
      this.camera.position.lerpVectors(fromP, toP, k);
      this.controls.target.lerpVectors(fromT, toT, k);
      if (t < 1) requestAnimationFrame(step);
    };
    step();
  }

  resize() {
    const w = this.container.clientWidth || 1, h = this.container.clientHeight || 1;
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(w, h);
    this.labels.setSize(w, h);
  }

  _lights() {
    this.scene.add(new THREE.HemisphereLight(0xffffff, 0x39424e, 1.1));
    const sun = new THREE.DirectionalLight(0xffffff, 2.2);
    sun.position.set(-0.3, -0.5, 1.2);
    sun.castShadow = true;
    sun.shadow.mapSize.set(2048, 2048);
    Object.assign(sun.shadow.camera, { left: -0.7, right: 0.7, top: 0.7, bottom: -0.7, near: 0.1, far: 3 });
    sun.shadow.bias = -0.0005;
    this.scene.add(sun);
    const fill = new THREE.DirectionalLight(0xbcd4ff, 0.5);
    fill.position.set(0.8, 0.6, 0.5);
    this.scene.add(fill);
  }

  _table() {
    const top = new THREE.Mesh(
      new THREE.BoxGeometry(1.0, 1.0, 0.03),
      new THREE.MeshStandardMaterial({ color: 0xe9e4da, roughness: 0.85 }));
    top.position.set(0.2, 0, -0.0174);
    top.receiveShadow = true;
    this.scene.add(top);
    this.tableTop = top;

    // A faint 5 cm grid, and the part of the table the arm can reach.
    const grid = new THREE.GridHelper(1.0, 20, 0xc9c2b4, 0xd6d0c3);
    grid.rotation.x = Math.PI / 2;
    grid.position.set(0.2, 0, -0.0021);
    grid.material.transparent = true;
    grid.material.opacity = 0.6;
    this.scene.add(grid);
    this.grid = grid;

    const reach = new THREE.Mesh(
      new THREE.RingGeometry(0.10, 0.33, 96, 1, -Math.PI / 2 + 0.25, Math.PI - 0.5),
      new THREE.MeshBasicMaterial({ color: 0x0ea5e9, transparent: true, opacity: 0.10, side: THREE.DoubleSide }));
    reach.position.set(0.0388, 0, -0.0018);
    this.scene.add(reach);
  }

  // A working desk: wooden top and a few things that belong on a desk. They are only drawn,
  // not obstacles for MoveIt, so they all stand outside the arm's reach.
  setDesk(on) {
    this.tableTop.material.color.set(on ? 0xb68a62 : 0xe9e4da);
    this.tableTop.material.roughness = on ? 0.6 : 0.85;
    this.grid.visible = !on;
    if (!this.desk) this.desk = this._deskProps();
    this.desk.visible = on;
  }

  _deskProps() {
    const group = new THREE.Group();
    const box = (size, color, position, extra = {}) => {
      const mesh = new THREE.Mesh(new THREE.BoxGeometry(...size),
        new THREE.MeshStandardMaterial({ color, roughness: 0.55, ...extra }));
      mesh.position.set(...position);
      mesh.castShadow = mesh.receiveShadow = true;
      return mesh;
    };
    const cylinder = (radius, height, color, position) => {
      const mesh = new THREE.Mesh(new THREE.CylinderGeometry(radius, radius * 0.92, height, 32),
        new THREE.MeshStandardMaterial({ color, roughness: 0.6 }));
      mesh.rotation.x = Math.PI / 2;           // cylinders stand on the table (z is up)
      mesh.position.set(...position);
      mesh.castShadow = mesh.receiveShadow = true;
      return mesh;
    };

    // An open laptop at the far side, its screen turned towards the arm.
    const laptop = new THREE.Group();
    laptop.add(box([0.22, 0.31, 0.012], 0x30353d, [0, 0, 0.006]));
    laptop.add(box([0.12, 0.26, 0.002], 0x22262c, [-0.03, 0, 0.013]));             // keyboard
    const lid = new THREE.Group();
    lid.add(box([0.008, 0.31, 0.21], 0x30353d, [0, 0, 0.105]));
    lid.add(box([0.002, 0.29, 0.18], 0x10233d, [-0.005, 0, 0.11], { emissive: 0x1d4ed8, emissiveIntensity: 0.35 }));
    lid.position.set(0.11, 0, 0.012);
    lid.rotation.y = 0.32;                       // leaning back, away from the keyboard
    laptop.add(lid);
    laptop.position.set(0.56, 0.22, 0);
    laptop.rotation.z = -0.35;
    group.add(laptop);

    // A notebook with a pen on it, and a cup of pens.
    const notebook = box([0.15, 0.21, 0.012], 0x1e3a5f, [0.47, -0.34, 0.006]);
    notebook.rotation.z = 0.35;
    group.add(notebook);
    const pen = cylinder(0.004, 0.14, 0x111827, [0.47, -0.34, 0.016]);
    pen.rotation.set(0, 0, 0.9);                // lying flat (a cylinder's axis is y)
    group.add(pen);
    group.add(cylinder(0.035, 0.1, 0x475569, [0.18, -0.42, 0.05]));
    [[0.008, 0.006, 0x2563eb], [-0.01, 0.004, 0xdc2626], [0.002, -0.01, 0x111827]].forEach(([dx, dy, color], i) => {
      const p = cylinder(0.004, 0.14, color, [0.18 + dx, -0.42 + dy, 0.09 + 0.01 * i]);
      p.rotation.set(Math.PI / 2 + dx * 8, dy * 8, 0);
      group.add(p);
    });

    // A plant in a pot on the left.
    group.add(cylinder(0.05, 0.08, 0xe7e5e4, [-0.12, 0.4, 0.04]));
    const leaves = new THREE.MeshStandardMaterial({ color: 0x2f7d32, roughness: 0.8 });
    [[0, 0, 0.13, 0.055], [0.03, 0.02, 0.17, 0.04], [-0.025, -0.02, 0.16, 0.042]].forEach(([dx, dy, z, r]) => {
      const leaf = new THREE.Mesh(new THREE.SphereGeometry(r, 20, 16), leaves);
      leaf.position.set(-0.12 + dx, 0.4 + dy, z);
      leaf.castShadow = true;
      group.add(leaf);
    });

    this.scene.add(group);
    return group;
  }

  _handMarker() {
    this.hand = new THREE.Mesh(
      new THREE.SphereGeometry(0.012, 24, 16),
      new THREE.MeshBasicMaterial({ color: 0x38bdf8, transparent: true, opacity: 0.55 }));
    this.hand.visible = false;
    this.scene.add(this.hand);
    const drop = new THREE.Mesh(
      new THREE.RingGeometry(0.014, 0.018, 32),
      new THREE.MeshBasicMaterial({ color: 0x38bdf8, transparent: true, opacity: 0.6, side: THREE.DoubleSide }));
    this.handShadow = drop;
    drop.visible = false;
    this.scene.add(drop);
  }

  setHand(position) {
    const visible = Array.isArray(position);
    this.hand.visible = this.handShadow.visible = visible;
    if (visible) {
      this.hand.position.set(position[0], position[1], position[2]);
      this.handShadow.position.set(position[0], position[1], -0.0015);
    }
  }

  // ------------------------------------------------------------------ robot

  loadRobot(urdfUrl) {
    return new Promise((resolve, reject) => {
      const loader = new URDFLoader();
      // package://move_the_bot/robot/... -> <this page's folder>/robot/...
      loader.packages = { move_the_bot: new URL(".", location.href).href.replace(/\/$/, "") };
      loader.load(urdfUrl, (robot) => {
        this.robot = robot;
        this.scene.add(robot);
        // Meshes arrive after the robot itself; keep switching shadows on until they are there.
        const shadows = () => robot.traverse((o) => {
          if (o.isMesh && !o.userData.tuned) {
            o.userData.tuned = true;
            o.castShadow = o.receiveShadow = true;
            // STL files have one normal per triangle; smooth the curved parts, keep sharp edges.
            const merged = mergeVertices(o.geometry.clone().deleteAttribute("normal"), 1e-5);
            o.geometry = toCreasedNormals(merged, THREE.MathUtils.degToRad(38));
            const dark = o.material.color.getHSL({}).l < 0.3;
            o.material = new THREE.MeshStandardMaterial({
              color: dark ? 0x23272e : 0xf2b632, roughness: dark ? 0.45 : 0.62, metalness: dark ? 0.25 : 0.0 });
          }
        });
        shadows();
        [300, 1000, 2500, 6000].forEach((ms) => setTimeout(shadows, ms));
        resolve(robot);
      }, undefined, reject);
    });
  }

  setJoints(names, positions) {
    if (!this.robot) return;
    for (let i = 0; i < names.length; i++) {
      if (this.robot.joints[names[i]]) this.robot.setJointValue(names[i], positions[i]);
    }
  }

  // ---------------------------------------------------------------- objects

  setObjects(list) {
    const seen = new Set();
    for (const o of list) {
      seen.add(o.name);
      const key = [o.kind, o.model, o.color, o.size.join(",")].join("|");
      let entry = this.objects.get(o.name);
      if (!entry || entry.key !== key) {
        if (entry) this._dispose(entry);
        entry = { key, group: this._build(o) };
        this.objects.set(o.name, entry);
        this.scene.add(entry.group);
        entry.group.scale.setScalar(0.01);        // pop in
        entry.born = performance.now();
        this._grow(entry);
      }
      entry.group.position.set(o.position[0], o.position[1], o.position[2]);
      entry.group.quaternion.set(o.quaternion[0], o.quaternion[1], o.quaternion[2], o.quaternion[3]);
      entry.group.userData.label.element.classList.toggle("held", !!o.held);
    }
    for (const [name, entry] of this.objects) {
      if (!seen.has(name)) {
        this._dispose(entry);
        this.objects.delete(name);
      }
    }
  }

  _grow(entry) {
    const t = Math.min(1, (performance.now() - entry.born) / 220);
    entry.group.scale.setScalar(0.01 + 0.99 * (1 - Math.pow(1 - t, 3)));
    if (t < 1) requestAnimationFrame(() => this._grow(entry));
  }

  // The average of the darker half of a point cloud's colours.
  _darkColour(geometry) {
    const colour = geometry.getAttribute("color");
    if (!colour) return new THREE.Color(0x202020);
    const n = colour.count, lum = new Float32Array(n);
    for (let i = 0; i < n; i++) lum[i] = 0.2126 * colour.getX(i) + 0.7152 * colour.getY(i) + 0.0722 * colour.getZ(i);
    const median = Float32Array.from(lum).sort()[n >> 1];
    const sum = [0, 0, 0];
    let count = 0;
    for (let i = 0; i < n; i++) {
      if (lum[i] > median) continue;
      sum[0] += colour.getX(i); sum[1] += colour.getY(i); sum[2] += colour.getZ(i);
      count++;
    }
    // Darker still: the brightest of these are highlights and reflections, not the material.
    return new THREE.Color().setRGB(sum[0] / count, sum[1] / count, sum[2] / count).multiplyScalar(0.45);
  }

  _dispose(entry) {
    entry.group.remove(entry.group.userData.label);
    this.scene.remove(entry.group);
  }

  _build(o) {
    const group = new THREE.Group();
    const [sx, sy, sz] = o.size;
    const material = new THREE.MeshStandardMaterial({ color: o.color, roughness: 0.5, metalness: 0.05 });
    let shape;
    if (o.shape === "sphere") {
      shape = new THREE.Mesh(new THREE.SphereGeometry(Math.min(sx, sy, sz) / 2, 40, 28), material);
    } else if (o.shape === "cylinder") {
      shape = new THREE.Mesh(new THREE.CylinderGeometry(Math.min(sx, sy) / 2, Math.min(sx, sy) / 2, sz, 48), material);
      shape.rotation.x = Math.PI / 2;
    } else {
      shape = new THREE.Mesh(new THREE.BoxGeometry(sx, sy, sz), material);
    }
    shape.castShadow = shape.receiveShadow = true;
    group.add(shape);

    if (o.model) {
      // A detailed model replaces the basic shape once it has loaded, scaled to the same size.
      this.gltf.load(o.model, (gltf) => {
        const model = gltf.scene;
        const holder = new THREE.Group();
        holder.rotation.x = Math.PI / 2;            // glTF is y-up, the robot world is z-up
        holder.add(model);
        const box = new THREE.Box3().setFromObject(model);
        const size = box.getSize(new THREE.Vector3());
        const centre = box.getCenter(new THREE.Vector3());
        // Our own models are made to size (a mug's handle may stick out); downloaded ones
        // can be any size and shape, so they are fitted inside the object's box.
        const scale = o.model.includes("/builtin/") || o.model.includes("/local/")
          ? sz / (size.y || 1)
          : Math.min(sx / (size.x || 1), sz / (size.y || 1), sy / (size.z || 1));
        model.position.sub(centre);
        holder.scale.setScalar(scale);
        let points = null;
        model.traverse((m) => {
          if (m.isMesh) m.castShadow = m.receiveShadow = true;
          if (m.isPoints) {
            // A point cloud (such as a Gaussian splat turned into points): dots about 2 mm wide.
            points = m;
            m.material.size = 0.002;
            m.material.sizeAttenuation = true;
          }
        });
        if (points) {
          // Points leave gaps and cast no shadow. The basic shape stays inside them, a little
          // smaller, in the model's darkest colour: the gaps show the object, not the table.
          shape.scale.setScalar(0.93);
          shape.material.color.copy(this._darkColour(points.geometry));
          shape.material.roughness = 0.35;
        } else {
          group.remove(shape);
        }
        group.add(holder);
      }, undefined, () => {});
    }

    const element = document.createElement("div");
    element.className = "object-label";
    element.textContent = o.name;
    const label = new CSS2DObject(element);
    label.position.set(0, 0, sz / 2 + 0.022);
    group.add(label);
    group.userData.label = label;
    return group;
  }
}
