class RobotViewer {
  constructor(containerId) {
    this.container = document.getElementById(containerId);
    this.sceneObjects = [];
    this.modelCache = new Map();
    this.markers = new Map();
    this.markerReceivedAt = new Map();
    this.setupScene();
    this.buildArm();
    this.animate();
  }

  setupScene() {
    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0x1a1a2e);

    const w = this.container.clientWidth;
    const h = this.container.clientHeight;
    this.camera = new THREE.PerspectiveCamera(45, w / h, 0.1, 10);
    this.camera.position.set(0.8, 0.5, 0.8);

    this.renderer = new THREE.WebGLRenderer({ antialias: true });
    this.renderer.setSize(w, h);
    this.renderer.setPixelRatio(window.devicePixelRatio);
    this.container.appendChild(this.renderer.domElement);

    this.controls = new THREE.OrbitControls(this.camera, this.renderer.domElement);
    this.controls.target.set(0.2, 0.1, 0);
    this.controls.update();

    const ambient = new THREE.AmbientLight(0x404040);
    this.scene.add(ambient);
    const dirLight = new THREE.DirectionalLight(0xffffff, 1);
    dirLight.position.set(1, 2, 1);
    this.scene.add(dirLight);
    const fillLight = new THREE.DirectionalLight(0x8888ff, 0.3);
    fillLight.position.set(-1, 0.5, -1);
    this.scene.add(fillLight);

    const grid = new THREE.GridHelper(1, 10, 0x888888, 0x444444);
    this.scene.add(grid);

    this.buildAxes();
    this.loader = new THREE.GLTFLoader();
  }

  buildAxes() {
    const len = 0.35;
    const headLen = 0.07;
    const headWid = 0.035;

    this.scene.add(new THREE.ArrowHelper(
      new THREE.Vector3(1, 0, 0), new THREE.Vector3(0, 0, 0),
      len, 0xff4444, headLen, headWid
    ));
    this.scene.add(new THREE.ArrowHelper(
      new THREE.Vector3(0, 1, 0), new THREE.Vector3(0, 0, 0),
      len, 0x44ff44, headLen, headWid
    ));
    this.scene.add(new THREE.ArrowHelper(
      new THREE.Vector3(0, 0, 1), new THREE.Vector3(0, 0, 0),
      len, 0x4488ff, headLen, headWid
    ));

    const makeLabel = (text, x, y, z) => {
      const c = document.createElement("canvas");
      c.width = 64; c.height = 64;
      const ctx = c.getContext("2d");
      ctx.fillStyle = "#ffffff";
      ctx.font = "bold 32px sans-serif";
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText(text, 32, 32);
      const tex = new THREE.CanvasTexture(c);
      const mat = new THREE.SpriteMaterial({ map: tex, depthTest: false, transparent: true });
      const spr = new THREE.Sprite(mat);
      spr.position.set(x, y, z);
      spr.scale.set(0.05, 0.05, 1);
      this.scene.add(spr);
    };
    makeLabel("X", len + 0.04, 0, 0);
    makeLabel("Y", 0, len + 0.04, 0);
    makeLabel("Z", 0, 0, len + 0.04);
  }

  buildArm() {
    this.base = new THREE.Mesh(
      new THREE.BoxGeometry(0.15, 0.05, 0.15),
      new THREE.MeshStandardMaterial({ color: 0x888888 })
    );
    this.base.position.y = 0.025;
    this.scene.add(this.base);

    this.shoulderGroup = new THREE.Group();
    this.shoulderGroup.position.set(0, 0.05, 0);
    this.scene.add(this.shoulderGroup);

    const shoulder = new THREE.Mesh(
      new THREE.BoxGeometry(0.06, 0.20, 0.06),
      new THREE.MeshStandardMaterial({ color: 0x3355cc })
    );
    shoulder.position.y = 0.10;
    this.shoulderGroup.add(shoulder);

    this.upperArmGroup = new THREE.Group();
    this.upperArmGroup.position.set(0, 0.15, 0);
    this.shoulderGroup.add(this.upperArmGroup);

    const upperArm = new THREE.Mesh(
      new THREE.BoxGeometry(0.05, 0.25, 0.05),
      new THREE.MeshStandardMaterial({ color: 0xcc3333 })
    );
    upperArm.position.y = 0.125;
    this.upperArmGroup.add(upperArm);

    this.forearmGroup = new THREE.Group();
    this.forearmGroup.position.set(0, 0.25, 0);
    this.upperArmGroup.add(this.forearmGroup);

    const forearm = new THREE.Mesh(
      new THREE.BoxGeometry(0.04, 0.25, 0.04),
      new THREE.MeshStandardMaterial({ color: 0x33cc33 })
    );
    forearm.position.y = 0.125;
    this.forearmGroup.add(forearm);

    const gripMat = new THREE.MeshStandardMaterial({ color: 0xcccc33 });
    this.gripperLeft = new THREE.Mesh(
      new THREE.BoxGeometry(0.01, 0.03, 0.04),
      gripMat
    );
    this.gripperLeft.position.set(-0.03, 0.25, 0);
    this.forearmGroup.add(this.gripperLeft);

    this.gripperRight = new THREE.Mesh(
      new THREE.BoxGeometry(0.01, 0.03, 0.04),
      gripMat
    );
    this.gripperRight.position.set(0.03, 0.25, 0);
    this.forearmGroup.add(this.gripperRight);

    // End-effector indicator in world space
    const sphere = new THREE.Mesh(
      new THREE.SphereGeometry(0.018, 10, 10),
      new THREE.MeshStandardMaterial({ color: 0xffdd44, emissive: 0x885500 })
    );
    sphere.position.set(0, 0.25, 0);
    this.forearmGroup.add(sphere);
  }

  updateJoints(positions) {
    if (positions.length < 4) return;
    const th1 = positions[0], th2 = positions[1], th3 = positions[2];
    this.shoulderGroup.rotation.y = th1;
    this.upperArmGroup.rotation.x = th2;
    this.forearmGroup.rotation.x = th3;

    // Forward kinematics (IK frame → Three.js frame)
    const L0 = 0.20, L1 = 0.25, L2 = 0.25;
    const r = L1 * Math.sin(th2) + L2 * Math.sin(th2 + th3);
    const zIK = L0 + L1 * Math.cos(th2) + L2 * Math.cos(th2 + th3);
    const xIK = r * Math.cos(th1);
    const yIK = r * Math.sin(th1);

    if (positions.length > 3 && this.gripperLeft && this.gripperRight) {
      const grip = positions[3];
      const spread = 0.03 - grip * 0.4;
      this.gripperLeft.position.x = -spread;
      this.gripperRight.position.x = spread;
    }

    const [ex, ey, ez] = ik_to_threejs(xIK, yIK, zIK);

    if (!this.eeLabel) {
      this.eeLabel = this._makeStaticLabel("EE", 0xffdd44);
      this.scene.add(this.eeLabel);
    }
    this.eeLabel.position.set(ex, ey + 0.05, ez);
  }

  _makeStaticLabel(text, colorHex) {
    const c = document.createElement("canvas");
    c.width = 128; c.height = 48;
    const ctx = c.getContext("2d");
    ctx.fillStyle = "rgba(0,0,0,0.7)";
    ctx.roundRect(0, 0, 128, 48, 6);
    ctx.fill();
    ctx.fillStyle = "#" + colorHex.toString(16).padStart(6, "0");
    ctx.font = "bold 24px sans-serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(text, 64, 26);
    const tex = new THREE.CanvasTexture(c);
    const mat = new THREE.SpriteMaterial({ map: tex, depthTest: false });
    const spr = new THREE.Sprite(mat);
    spr.scale.set(0.08, 0.03, 1);
    return spr;
  }

  spawnObject(name, modelPath, x, y, z, scale) {
    for (let i = this.sceneObjects.length - 1; i >= 0; i--) {
      if (this.sceneObjects[i].name === name) {
        this.scene.remove(this.sceneObjects[i].mesh);
        this.scene.remove(this.sceneObjects[i].label);
        this.sceneObjects.splice(i, 1);
        break;
      }
    }

    const label = this.createLabel(name, x, y, z);
    const modelUrl = modelPath || this._resolveModelUrl(name);

    if (modelUrl) {
      this._addModel(name, modelUrl, x, y, z, label, scale);
    } else {
      const mesh = this._makeSphere(x, y, z);
      this.scene.add(mesh);
      this.scene.add(label);
      this.sceneObjects.push({ mesh, label, name });
    }
  }

  _resolveModelUrl(name) {
    const MODEL_MAP = {
      "apple": "apple.glb",
      "mug": "mug.glb", "coffee mug": "mug.glb", "coffee": "mug.glb",
      "bottle": "bottle.glb", "water bottle": "bottle.glb",
      "cube": "cube.glb", "box": "cube.glb",
      "sphere": "sphere.glb", "ball": "sphere.glb",
      "cylinder": "cylinder.glb",
      "can": "can.glb", "soda can": "can.glb",
      "table": "table.glb",
    };
    const filename = MODEL_MAP[name.trim().toLowerCase()];
    return filename ? `/models/builtin/${filename}` : null;
  }

  _addModel(name, url, x, y, z, label, scale) {
    if (this.modelCache.has(url)) {
      this._instantiateModel(name, url, x, y, z, label, scale);
      return;
    }

    const fallback = this._makeSphere(x, y, z);
    this.scene.add(fallback);
    this.scene.add(label);
    const entry = { mesh: fallback, label, name };
    this.sceneObjects.push(entry);

    const s = scale || 1.0;
    this.loader.load(url, (gltf) => {
      this.modelCache.set(url, gltf.scene);
      const clone = gltf.scene.clone();
      clone.position.set(x, y, z);
      clone.scale.setScalar(s);
      this.scene.remove(entry.mesh);
      this.scene.add(clone);
      entry.mesh = clone;
    }, undefined, () => {
      console.warn(`Failed to load GLB: ${url}, keeping sphere`);
    });
  }

  _instantiateModel(name, url, x, y, z, label, scale) {
    const cached = this.modelCache.get(url);
    const clone = cached.clone();
    clone.position.set(x, y, z);
    clone.scale.setScalar(scale || 1.0);
    this.scene.add(clone);
    this.scene.add(label);
    this.sceneObjects.push({ mesh: clone, label, name });
  }

  _makeSphere(x, y, z) {
    const color = new THREE.Color(
      Math.random() * 0.8 + 0.2,
      Math.random() * 0.8 + 0.2,
      Math.random() * 0.8 + 0.2
    );
    const mesh = new THREE.Mesh(
      new THREE.SphereGeometry(0.04, 12, 12),
      new THREE.MeshStandardMaterial({ color, metalness: 0.3, roughness: 0.6 })
    );
    mesh.position.set(x, y, z);
    return mesh;
  }

  updateMarkers(markers) {
    for (const m of markers) {
      // Skip arm markers — the scene-graph arm already visualizes links
      if (m.ns === "arm_links" || m.ns === "arm" || m.ns === "arm_joints") continue;
      if (m.action === 2) {
        this._removeNamespace(m.ns);
        continue;
      }
      if (m.action === 1) {
        this._removeMarker(m.ns, m.id);
        continue;
      }
      if (m.action !== 0) continue;

      this._removeMarker(m.ns, m.id);

      const [tx, ty, tz] = ik_to_threejs(m.pose.position.x, m.pose.position.y, m.pose.position.z);
      const key = `${m.ns}:${m.id}`;
      const color = new THREE.Color(m.color.r, m.color.g, m.color.b);
      // Convert ROS quaternion (x,y,z,w) → Three.js (y,z,x,w) to match ik_to_threejs axis permutation
      const qx = m.pose.orientation.y;
      const qy = m.pose.orientation.z;
      const qz = m.pose.orientation.x;
      const qw = m.pose.orientation.w;
      // Convert ROS scale (sx,sy,sz) → Three.js (sy,sz,sx)
      const sx = m.scale.y, sy = m.scale.z, sz = m.scale.x;
      let obj = null;

      switch (m.type) {
        case 1: {
          const g = new THREE.BoxGeometry(sx, sy, sz);
          const mat = new THREE.MeshStandardMaterial({ color, transparent: m.color.a < 1, opacity: m.color.a });
          obj = new THREE.Mesh(g, mat);
          obj.position.set(tx, ty, tz);
          obj.quaternion.set(qx, qy, qz, qw);
          break;
        }
        case 2: {
          const radius = Math.max(sx, sy, sz) / 2;
          const g = new THREE.SphereGeometry(radius, 16, 16);
          const mat = new THREE.MeshStandardMaterial({ color, transparent: m.color.a < 1, opacity: m.color.a });
          obj = new THREE.Mesh(g, mat);
          obj.position.set(tx, ty, tz);
          break;
        }
        case 3: {
          const r = sx / 2;
          const g = new THREE.CylinderGeometry(r, r, sy, 16);
          const mat = new THREE.MeshStandardMaterial({ color, transparent: m.color.a < 1, opacity: m.color.a });
          obj = new THREE.Mesh(g, mat);
          obj.position.set(tx, ty, tz);
          obj.quaternion.set(qx, qy, qz, qw);
          break;
        }
        case 4: {
          const pts = m.points.map(p => {
            const [px, py, pz] = ik_to_threejs(p.x, p.y, p.z);
            return new THREE.Vector3(px, py, pz);
          });
          const g = new THREE.BufferGeometry().setFromPoints(pts);
          const mat = new THREE.LineBasicMaterial({ color, transparent: m.color.a < 1, opacity: m.color.a });
          obj = new THREE.Line(g, mat);
          break;
        }
        case 9: {
          const canvas = document.createElement("canvas");
          canvas.width = 256;
          canvas.height = 64;
          const ctx = canvas.getContext("2d");
          ctx.fillStyle = "rgba(0,0,0,0.6)";
          ctx.roundRect(0, 0, 256, 64, 8);
          ctx.fill();
          ctx.fillStyle = "#" + color.getHexString();
          ctx.font = "bold 28px sans-serif";
          ctx.textAlign = "center";
          ctx.fillText(m.text, 128, 42);
          const tex = new THREE.CanvasTexture(canvas);
          const spriteMat = new THREE.SpriteMaterial({ map: tex, depthTest: false, transparent: true, opacity: m.color.a });
          obj = new THREE.Sprite(spriteMat);
          obj.position.set(tx, ty, tz);
          obj.scale.set(0.12, 0.03, 1);
          break;
        }
      }

      if (obj) {
        const lifetime = m.lifetime ? m.lifetime.sec + m.lifetime.nanosec / 1e9 : 0;
        obj.userData = { ns: m.ns, id: m.id, lifetime };
        this.scene.add(obj);
        this.markers.set(key, obj);
        this.markerReceivedAt.set(key, performance.now());
      }
    }
  }

  _removeMarker(ns, id) {
    const key = `${ns}:${id}`;
    const obj = this.markers.get(key);
    if (obj) {
      this.scene.remove(obj);
      this.markers.delete(key);
      this.markerReceivedAt.delete(key);
    }
  }

  _removeNamespace(ns) {
    for (const [key, obj] of this.markers) {
      if (obj.userData.ns === ns) {
        this.scene.remove(obj);
        this.markers.delete(key);
        this.markerReceivedAt.delete(key);
      }
    }
  }

  _cleanExpiredMarkers() {
    const now = performance.now();
    for (const [key, obj] of this.markers) {
      const lifetime = obj.userData.lifetime;
      if (lifetime <= 0) continue;
      const received = this.markerReceivedAt.get(key) || 0;
      if (now - received > lifetime * 1000) {
        this.scene.remove(obj);
        this.markers.delete(key);
        this.markerReceivedAt.delete(key);
      }
    }
  }

  resetEnvironment() {
    for (const obj of this.sceneObjects) {
      this.scene.remove(obj.mesh);
      this.scene.remove(obj.label);
    }
    this.sceneObjects = [];
    this._removeNamespace("trajectory_waypoints");
    this._removeNamespace("trajectory_path");
    this._removeNamespace("trajectory_goal");
  }

  createLabel(text, x, y, z) {
    const canvas = document.createElement("canvas");
    canvas.width = 256;
    canvas.height = 64;
    const ctx = canvas.getContext("2d");
    ctx.fillStyle = "rgba(0,0,0,0.6)";
    ctx.roundRect(0, 0, 256, 64, 8);
    ctx.fill();
    ctx.fillStyle = "#ffffff";
    ctx.font = "bold 28px sans-serif";
    ctx.textAlign = "center";
    ctx.fillText(text, 128, 42);

    const texture = new THREE.CanvasTexture(canvas);
    const spriteMat = new THREE.SpriteMaterial({ map: texture, depthTest: false });
    const sprite = new THREE.Sprite(spriteMat);
    sprite.position.set(x, y + 0.06, z);
    sprite.scale.set(0.12, 0.03, 1);
    return sprite;
  }

  animate() {
    requestAnimationFrame(() => this.animate());
    this._cleanExpiredMarkers();
    this.controls.update();
    this.renderer.render(this.scene, this.camera);
  }
}
