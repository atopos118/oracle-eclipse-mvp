import * as THREE from "./assets/vendor/three.module.min.js";

const canvas = document.querySelector("#eclipse-canvas");
const stage = document.querySelector("#eclipse-stage");
const lab = document.querySelector("#eclipse-lab");
const offsetInput = document.querySelector("#orbit-offset");
const fallbackNotice = document.querySelector("#eclipse-webgl-notice");

if (canvas && stage && lab && offsetInput) initializeEclipseLab();

function initializeEclipseLab() {
  let renderer;
  try {
    renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: false, powerPreference: "high-performance" });
  } catch (error) {
    fallbackNotice.hidden = false;
    canvas.hidden = true;
    console.error("Three.js eclipse scene unavailable", error);
    return;
  }

  const prefersReducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x03110e);
  scene.fog = new THREE.FogExp2(0x03110e, 0.017);

  const camera = new THREE.PerspectiveCamera(38, 1, 0.1, 130);
  const cameraTarget = new THREE.Vector3(0, 0, 0);
  const desiredCamera = new THREE.Vector3(0, 7.4, 25.5);
  const desiredTarget = new THREE.Vector3(0, 0, 0);
  camera.position.copy(desiredCamera);
  camera.lookAt(cameraTarget);

  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.08;
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.75));

  const world = new THREE.Group();
  scene.add(world);

  const ambient = new THREE.HemisphereLight(0x88bfb6, 0x06100d, 0.42);
  scene.add(ambient);

  const sunGroup = createSun();
  sunGroup.position.set(-8.8, 0, 0);
  world.add(sunGroup);

  const sunlight = new THREE.PointLight(0xffd58a, 280, 42, 1.35);
  sunlight.position.copy(sunGroup.position);
  world.add(sunlight);

  const moonGroup = createMoon();
  moonGroup.position.set(-0.35, 0, 0);
  world.add(moonGroup);

  const earthGroup = createEarth();
  earthGroup.position.set(8.25, 0, 0);
  world.add(earthGroup);

  const stars = createStars();
  scene.add(stars);

  const eclipticPlane = new THREE.GridHelper(28, 28, 0x315c50, 0x19392f);
  eclipticPlane.position.y = -2.35;
  eclipticPlane.material.transparent = true;
  eclipticPlane.material.opacity = 0.2;
  world.add(eclipticPlane);

  const orbitLine = createOrbitLine();
  world.add(orbitLine);

  const lightField = createCone(5.1, 2.35, 16.1, 0xd8a93f, 0.045, THREE.AdditiveBlending);
  lightField.position.set(-0.7, 0, 0);
  world.add(lightField);

  const shadowGroup = new THREE.Group();
  shadowGroup.position.set(3.95, 0, 0);
  const penumbra = createCone(2.25, 0.82, 8.35, 0xb5964d, 0.085, THREE.NormalBlending);
  const umbra = createCone(0.1, 0.72, 8.25, 0x000000, 0.72, THREE.NormalBlending);
  shadowGroup.add(penumbra, umbra);
  world.add(shadowGroup);

  const totalImpactTexture = createRadialTexture([
    [0, "rgba(0,0,0,.95)"],
    [0.36, "rgba(0,0,0,.82)"],
    [0.7, "rgba(22,42,36,.3)"],
    [1, "rgba(22,42,36,0)"]
  ]);
  const annularImpactTexture = createRadialTexture([
    [0, "rgba(216,169,63,0)"],
    [0.34, "rgba(216,169,63,.05)"],
    [0.55, "rgba(255,215,122,.95)"],
    [0.7, "rgba(216,169,63,.08)"],
    [1, "rgba(216,169,63,0)"]
  ]);
  const impactMaterial = new THREE.SpriteMaterial({ map: totalImpactTexture, transparent: true, depthWrite: false });
  const impact = new THREE.Sprite(impactMaterial);
  impact.position.set(8.25, 0, 2.12);
  impact.scale.set(2.2, 2.2, 1);
  world.add(impact);

  const state = {
    view: "orbit",
    type: document.querySelector(".type-tab.is-active")?.dataset.type || "total",
    offset: Number(offsetInput.value) || 0,
    yaw: 0,
    pitch: 0,
    dragging: false,
    pointerX: 0,
    pointerY: 0,
    visible: true,
    dirty: true
  };
  lab.dataset.view = state.view;

  function createSun() {
    const group = new THREE.Group();
    const surface = new THREE.Mesh(
      new THREE.SphereGeometry(3.05, 56, 40),
      new THREE.MeshBasicMaterial({ color: 0xf1a92f })
    );
    const innerGlow = new THREE.Sprite(new THREE.SpriteMaterial({
      map: createRadialTexture([[0, "rgba(255,232,160,1)"], [0.32, "rgba(245,180,59,.72)"], [1, "rgba(245,180,59,0)"]]),
      transparent: true,
      blending: THREE.AdditiveBlending,
      depthWrite: false
    }));
    innerGlow.scale.set(9.8, 9.8, 1);
    const corona = new THREE.Sprite(new THREE.SpriteMaterial({
      map: createRadialTexture([[0, "rgba(255,222,132,.2)"], [0.4, "rgba(216,169,63,.13)"], [1, "rgba(216,169,63,0)"]]),
      transparent: true,
      blending: THREE.AdditiveBlending,
      depthWrite: false
    }));
    corona.scale.set(14, 14, 1);
    group.add(corona, innerGlow, surface);
    return group;
  }

  function createMoon() {
    const group = new THREE.Group();
    const surface = new THREE.Mesh(
      new THREE.IcosahedronGeometry(0.78, 5),
      new THREE.MeshStandardMaterial({ color: 0x69736f, roughness: 0.96, metalness: 0 })
    );
    surface.rotation.set(0.12, -0.28, 0.05);
    const rim = new THREE.Mesh(
      new THREE.SphereGeometry(0.81, 30, 22),
      new THREE.MeshBasicMaterial({ color: 0x9eb1aa, transparent: true, opacity: 0.12, wireframe: true })
    );
    group.add(surface, rim);
    return group;
  }

  function createEarth() {
    const group = new THREE.Group();
    const surface = new THREE.Mesh(
      new THREE.SphereGeometry(2.05, 56, 40),
      new THREE.MeshStandardMaterial({ color: 0x2f766f, roughness: 0.78, metalness: 0.04 })
    );
    surface.rotation.z = -0.41;
    const atmosphere = new THREE.Mesh(
      new THREE.SphereGeometry(2.14, 44, 30),
      new THREE.MeshBasicMaterial({ color: 0x92d2c8, transparent: true, opacity: 0.12, side: THREE.BackSide })
    );
    const equator = new THREE.Mesh(
      new THREE.TorusGeometry(2.08, 0.012, 8, 96),
      new THREE.MeshBasicMaterial({ color: 0xb7e4dc, transparent: true, opacity: 0.34 })
    );
    equator.rotation.x = Math.PI / 2;
    const axisGeometry = new THREE.BufferGeometry().setFromPoints([
      new THREE.Vector3(0, -2.75, 0),
      new THREE.Vector3(0, 2.75, 0)
    ]);
    const axis = new THREE.Line(axisGeometry, new THREE.LineBasicMaterial({ color: 0xd8a93f, transparent: true, opacity: 0.58 }));
    axis.rotation.z = -0.41;
    group.add(surface, atmosphere, equator, axis);
    return group;
  }

  function createStars() {
    const positions = [];
    let seed = 41287;
    const random = () => {
      seed = (seed * 16807) % 2147483647;
      return (seed - 1) / 2147483646;
    };
    for (let index = 0; index < 820; index += 1) {
      const radius = 38 + random() * 58;
      const theta = random() * Math.PI * 2;
      const phi = Math.acos(2 * random() - 1);
      positions.push(
        radius * Math.sin(phi) * Math.cos(theta),
        radius * Math.cos(phi),
        radius * Math.sin(phi) * Math.sin(theta)
      );
    }
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
    return new THREE.Points(geometry, new THREE.PointsMaterial({ color: 0xc9ded8, size: 0.11, transparent: true, opacity: 0.72, sizeAttenuation: true }));
  }

  function createOrbitLine() {
    const points = [];
    for (let index = 0; index <= 128; index += 1) {
      const angle = (index / 128) * Math.PI * 2;
      points.push(new THREE.Vector3(8.25 + Math.cos(angle) * 8.6, Math.sin(angle) * 2.5 - 0.15, -0.7));
    }
    return new THREE.Line(
      new THREE.BufferGeometry().setFromPoints(points),
      new THREE.LineBasicMaterial({ color: 0xd8a93f, transparent: true, opacity: 0.24 })
    );
  }

  function createCone(radiusTop, radiusBottom, length, color, opacity, blending) {
    const mesh = new THREE.Mesh(
      new THREE.CylinderGeometry(radiusTop, radiusBottom, length, 36, 1, true),
      new THREE.MeshBasicMaterial({ color, transparent: true, opacity, side: THREE.DoubleSide, depthWrite: false, blending })
    );
    mesh.rotation.z = Math.PI / 2;
    return mesh;
  }

  function createRadialTexture(stops) {
    const textureCanvas = document.createElement("canvas");
    textureCanvas.width = 256;
    textureCanvas.height = 256;
    const context = textureCanvas.getContext("2d");
    const gradient = context.createRadialGradient(128, 128, 0, 128, 128, 128);
    stops.forEach(([position, color]) => gradient.addColorStop(position, color));
    context.fillStyle = gradient;
    context.fillRect(0, 0, 256, 256);
    const texture = new THREE.CanvasTexture(textureCanvas);
    texture.colorSpace = THREE.SRGBColorSpace;
    return texture;
  }

  function setView(view) {
    state.view = view === "observer" ? "observer" : "orbit";
    lab.dataset.view = state.view;
    document.querySelectorAll("[data-scene-view]").forEach((button) => {
      const active = button.dataset.sceneView === state.view;
      button.classList.toggle("is-active", active);
      button.setAttribute("aria-pressed", String(active));
    });
    if (state.view === "observer") {
      desiredCamera.set(11.5, 0.25, 0.16);
      desiredTarget.set(-5.5, 0, 0);
    } else {
      desiredCamera.set(Math.sin(state.yaw) * 25.5, 7.4 + state.pitch * 10, Math.cos(state.yaw) * 25.5);
      desiredTarget.set(0, 0, 0);
    }
    state.dirty = true;
  }

  function setType(type, synchronizeControl = true) {
    state.type = ["total", "annular", "partial"].includes(type) ? type : "total";
    if (synchronizeControl) {
      const nextOffset = state.type === "partial" ? 2.1 : 0;
      if (Math.abs(Number(offsetInput.value) - nextOffset) > 0.01) {
        offsetInput.value = String(nextOffset);
        offsetInput.dispatchEvent(new Event("input", { bubbles: true }));
      }
    }
    impactMaterial.map = state.type === "annular" ? annularImpactTexture : totalImpactTexture;
    impactMaterial.needsUpdate = true;
    const detail = document.querySelector("#alignment-detail");
    if (detail && state.type === "annular" && Math.abs(state.offset) <= 1.1) detail.textContent = "本影锥未到达地表，伪本影经过";
    state.dirty = true;
  }

  function setOffset(offset) {
    state.offset = Number(offset) || 0;
    state.dirty = true;
  }

  function updateScene(time) {
    const moonY = state.offset * 0.39;
    const shadowY = state.offset * 0.72;
    const observerScale = state.view === "observer" ? (state.type === "annular" ? 1.58 : 1.9) : 1;
    const typeScale = state.view === "orbit" && state.type === "annular" ? 0.77 : 1;
    const targetScale = observerScale * typeScale;

    moonGroup.position.y += (moonY - moonGroup.position.y) * 0.08;
    moonGroup.scale.lerp(new THREE.Vector3(targetScale, targetScale, targetScale), 0.08);
    shadowGroup.position.y += ((moonY + shadowY) * 0.5 - shadowGroup.position.y) * 0.08;
    shadowGroup.rotation.z += (-Math.atan2(shadowY - moonY, 8.4) - shadowGroup.rotation.z) * 0.08;

    impact.position.y += (shadowY - impact.position.y) * 0.1;
    impact.visible = state.view === "orbit" && Math.abs(state.offset) < 3.25;
    impact.scale.setScalar(state.type === "partial" ? 1.55 : 2.2);
    impact.scale.z = 1;

    const observerView = state.view === "observer";
    earthGroup.visible = !observerView;
    eclipticPlane.visible = !observerView;
    orbitLine.visible = !observerView;
    lightField.visible = !observerView;
    shadowGroup.visible = !observerView;
    stars.material.opacity = observerView ? 0.9 : 0.72;

    if (!prefersReducedMotion) {
      sunGroup.rotation.y = time * 0.000035;
      earthGroup.rotation.y = time * 0.00008;
      stars.rotation.y = time * 0.000004;
    }

    camera.position.lerp(desiredCamera, 0.065);
    cameraTarget.lerp(desiredTarget, 0.065);
    camera.lookAt(cameraTarget);
  }

  function resize() {
    const width = Math.max(1, stage.clientWidth);
    const height = Math.max(1, stage.clientHeight);
    renderer.setSize(width, height, false);
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
    state.dirty = true;
  }

  document.querySelectorAll("[data-scene-view]").forEach((button) => {
    button.addEventListener("click", () => setView(button.dataset.sceneView));
  });

  offsetInput.addEventListener("input", (event) => setOffset(event.target.value));
  window.addEventListener("eclipse:alignmentchange", (event) => setOffset(event.detail?.offset));
  window.addEventListener("eclipse:typechange", (event) => setType(event.detail?.type));

  canvas.addEventListener("pointerdown", (event) => {
    if (state.view !== "orbit") return;
    state.dragging = true;
    state.pointerX = event.clientX;
    state.pointerY = event.clientY;
    canvas.setPointerCapture(event.pointerId);
  });
  canvas.addEventListener("pointermove", (event) => {
    if (!state.dragging || state.view !== "orbit") return;
    const deltaX = event.clientX - state.pointerX;
    const deltaY = event.clientY - state.pointerY;
    state.pointerX = event.clientX;
    state.pointerY = event.clientY;
    state.yaw = THREE.MathUtils.clamp(state.yaw - deltaX * 0.0045, -0.55, 0.55);
    state.pitch = THREE.MathUtils.clamp(state.pitch + deltaY * 0.0025, -0.28, 0.32);
    desiredCamera.set(Math.sin(state.yaw) * 25.5, 7.4 + state.pitch * 10, Math.cos(state.yaw) * 25.5);
    state.dirty = true;
  });
  const endDrag = (event) => {
    if (!state.dragging) return;
    state.dragging = false;
    if (canvas.hasPointerCapture(event.pointerId)) canvas.releasePointerCapture(event.pointerId);
  };
  canvas.addEventListener("pointerup", endDrag);
  canvas.addEventListener("pointercancel", endDrag);

  const resizeObserver = new ResizeObserver(resize);
  resizeObserver.observe(stage);
  const visibilityObserver = new IntersectionObserver(([entry]) => {
    state.visible = entry.isIntersecting;
    if (state.visible) state.dirty = true;
  }, { rootMargin: "180px 0px" });
  visibilityObserver.observe(stage);

  document.addEventListener("visibilitychange", () => { state.visible = !document.hidden; });
  setOffset(offsetInput.value);
  setType(state.type, false);
  setView("orbit");
  resize();

  function animate(time) {
    requestAnimationFrame(animate);
    if (!state.visible || document.hidden) return;
    if (prefersReducedMotion && !state.dirty) return;
    updateScene(time);
    renderer.render(scene, camera);
    state.dirty = false;
  }
  requestAnimationFrame(animate);
}
