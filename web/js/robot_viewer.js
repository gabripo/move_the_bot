class RobotViewer {
  constructor(containerId) {
    this.container = document.getElementById(containerId);
    this.sceneObjects = [];
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

    const gripper = new THREE.Mesh(
      new THREE.BoxGeometry(0.08, 0.03, 0.03),
      new THREE.MeshStandardMaterial({ color: 0xcccc33 })
    );
    gripper.position.set(0, 0.25, 0);
    this.forearmGroup.add(gripper);

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

  spawnObject(name, modelPath, x, y, z) {
    // Remove existing instance of the same object type
    for (let i = this.sceneObjects.length - 1; i >= 0; i--) {
      if (this.sceneObjects[i].name === name) {
        this.scene.remove(this.sceneObjects[i].mesh);
        this.scene.remove(this.sceneObjects[i].label);
        this.sceneObjects.splice(i, 1);
        break;
      }
    }

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

    const label = this.createLabel(name, x, y, z);
    this.scene.add(mesh);
    this.scene.add(label);
    this.sceneObjects.push({ mesh, label, name });
  }

  resetEnvironment() {
    for (const obj of this.sceneObjects) {
      this.scene.remove(obj.mesh);
      this.scene.remove(obj.label);
    }
    this.sceneObjects = [];
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
    this.controls.update();
    this.renderer.render(this.scene, this.camera);
  }
}
