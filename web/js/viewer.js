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

    // A faint 5 cm grid, and the part of the table the arm can reach.
    const grid = new THREE.GridHelper(1.0, 20, 0xc9c2b4, 0xd6d0c3);
    grid.rotation.x = Math.PI / 2;
    grid.position.set(0.2, 0, -0.0021);
    grid.material.transparent = true;
    grid.material.opacity = 0.6;
    this.scene.add(grid);

    const reach = new THREE.Mesh(
      new THREE.RingGeometry(0.10, 0.33, 96, 1, -Math.PI / 2 + 0.25, Math.PI - 0.5),
      new THREE.MeshBasicMaterial({ color: 0x0ea5e9, transparent: true, opacity: 0.10, side: THREE.DoubleSide }));
    reach.position.set(0.0388, 0, -0.0018);
    this.scene.add(reach);
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
        const scale = o.model.includes("/builtin/")
          ? sz / (size.y || 1)
          : Math.min(sx / (size.x || 1), sz / (size.y || 1), sy / (size.z || 1));
        model.position.sub(centre);
        holder.scale.setScalar(scale);
        model.traverse((m) => { if (m.isMesh) m.castShadow = m.receiveShadow = true; });
        group.remove(shape);
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
