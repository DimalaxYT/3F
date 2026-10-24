// G36E — preview temps réel (three.js vendorisé, aucune dépendance réseau)
import * as THREE from 'three';
import { OrbitControls } from './vendor/OrbitControls.js';
import { GLTFLoader } from './vendor/GLTFLoader.js';
import { RoomEnvironment } from './vendor/RoomEnvironment.js';

const BASE = '/exports/g36_rifle/';
const GLB = {
  0: BASE + 'g36_rifle_game.glb',
  1: BASE + 'g36_rifle_LOD1.glb',
  2: BASE + 'g36_rifle_LOD2.glb',
};
const COLLIDERS = BASE + 'g36_rifle_colliders.glb';
const MANIFEST = BASE + 'game_manifest.json';

const $ = (id) => document.getElementById(id);
const canvas = $('view');

// filet de sécurité : une erreur JS s'affiche à l'écran au lieu de laisser une page vide
addEventListener('error', (e) => {
  const b = document.createElement('pre');
  b.style.cssText = 'position:fixed;left:16px;bottom:16px;z-index:99;max-width:60ch;'
    + 'margin:0;padding:12px 14px;border-radius:8px;background:#3a1414;color:#ffb3a7;'
    + 'font:12px/1.5 ui-monospace,monospace;white-space:pre-wrap';
  b.textContent = 'Erreur : ' + (e.message || e.error);
  document.body.appendChild(b);
  document.getElementById('loader')?.classList.add('gone');
});

/* ------------------------------------------------------------------ rendu */
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.05;

const scene = new THREE.Scene();

// environnement doux : donne des reflets crédibles au phosphaté et au polymère
const pmrem = new THREE.PMREMGenerator(renderer);
scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;

scene.add(new THREE.HemisphereLight(0xbfd4e6, 0x1a1f24, 0.5));

const key = new THREE.DirectionalLight(0xfff2e0, 2.4);
key.position.set(2.2, 3.4, 1.6);
scene.add(key);

const rim = new THREE.DirectionalLight(0x8fd4ff, 1.6);
rim.position.set(-2.6, 1.4, -2.4);
scene.add(rim);

const fill = new THREE.DirectionalLight(0xffffff, 0.45);
fill.position.set(-1.5, -1.0, 2.0);
scene.add(fill);

// sol + grille (masqués par défaut)
const ground = new THREE.Group();
const grid = new THREE.GridHelper(2.4, 48, 0x2b343d, 0x1b2229);
grid.material.transparent = true;
grid.material.opacity = 0.85;
const disc = new THREE.Mesh(
  new THREE.CircleGeometry(0.62, 64),
  new THREE.MeshBasicMaterial({ color: 0x0b0f13, transparent: true, opacity: 0.7 })
);
disc.rotation.x = -Math.PI / 2;
disc.position.y = -0.0015;
ground.add(grid, disc);
ground.visible = false;
scene.add(ground);

/* ----------------------------------------------------------------- caméras */
const persp = new THREE.PerspectiveCamera(38, 1, 0.01, 60);
const ortho = new THREE.OrthographicCamera(-1, 1, 1, -1, 0.01, 60);
let activeCam = persp;
let mode = 'persp';

const controls = new OrbitControls(persp, canvas);
controls.enableDamping = true;
controls.dampingFactor = 0.075;
controls.minDistance = 0.3;
controls.maxDistance = 6;
controls.autoRotate = true;
controls.autoRotateSpeed = 0.85;
controls.target.set(0, 0.15, 0);

/* ------------------------------------------------------------------ modèle */
const root = new THREE.Group();
root.rotation.x = -Math.PI / 2; // GLB en Z-up -> Y-up
scene.add(root);

const socketGroup = new THREE.Group();
const colliderGroup = new THREE.Group();
const edgeGroup = new THREE.Group();
root.add(socketGroup, colliderGroup);
scene.add(edgeGroup);

const loader = new GLTFLoader();
const lodCache = new Map();
const box = new THREE.Box3();
let modelRoot = null;
let currentLod = 0;

const loadGLB = (url) =>
  new Promise((res, rej) => loader.load(url, res, undefined, rej));

async function showLod(n) {
  if (!lodCache.has(n)) lodCache.set(n, (await loadGLB(GLB[n])).scene);
  if (modelRoot) root.remove(modelRoot);
  modelRoot = lodCache.get(n);
  modelRoot.traverse((o) => {
    if (!o.isMesh) return;
    o.frustumCulled = false;
    for (const m of (Array.isArray(o.material) ? o.material : [o.material])) {
      if (m) { m.envMapIntensity = 1.15; m.needsUpdate = true; }
    }
  });
  root.add(modelRoot);
  currentLod = n;
  scene.updateMatrixWorld(true);
  rebuildEdges();
  updateStats();
  document.querySelectorAll('#lodBtns button')
    .forEach((b) => b.classList.toggle('on', +b.dataset.lod === n));
}

/* arêtes franches : la signature du hard-surface, on doit pouvoir les montrer */
function rebuildEdges() {
  edgeGroup.clear();
  if (!modelRoot || !$('tgEdges').checked) return;
  scene.updateMatrixWorld(true);
  modelRoot.traverse((o) => {
    if (!o.isMesh) return;
    const line = new THREE.LineSegments(
      new THREE.EdgesGeometry(o.geometry, 24),
      new THREE.LineBasicMaterial({ color: 0x7fe3ff, transparent: true, opacity: 0.3 })
    );
    line.applyMatrix4(o.matrixWorld);
    edgeGroup.add(line);
  });
}

/* ----------------------------------------------------------------- sockets */
const SOCKET_COLORS = { muzzle: 0xff5a4a, grip: 0x62e08a, optic: 0x62c8ff, mag: 0xffc247 };
const socketLabels = [];

function socketLabelSprite(text) {
  const c = document.createElement('canvas');
  c.width = 512; c.height = 96;
  const g = c.getContext('2d');
  g.font = '600 40px ui-sans-serif, system-ui, sans-serif';
  const w = Math.min(480, g.measureText(text).width + 36);
  g.fillStyle = 'rgba(8,14,18,.85)';
  g.beginPath();
  if (g.roundRect) g.roundRect((512 - w) / 2, 16, w, 64, 14);
  else g.rect((512 - w) / 2, 16, w, 64);
  g.fill();
  g.fillStyle = '#bfe9ff';
  g.textAlign = 'center';
  g.textBaseline = 'middle';
  g.fillText(text, 256, 49);
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  const sp = new THREE.Sprite(
    new THREE.SpriteMaterial({ map: tex, depthTest: false, transparent: true })
  );
  sp.scale.set(0.24, 0.045, 1);
  sp.renderOrder = 999;
  return sp;
}

async function buildSockets() {
  let man;
  try {
    man = await (await fetch(MANIFEST, { cache: 'no-store' })).json();
  } catch { return; }

  socketGroup.clear();
  socketLabels.length = 0;

  for (const [name, s] of Object.entries(man.sockets || {})) {
    const short = name.replace('SOCKET_', '').toLowerCase();
    const col = SOCKET_COLORS[short] || 0x8fa2b3;
    const p = new THREE.Vector3().fromArray(s.position);

    const dot = new THREE.Mesh(
      new THREE.SphereGeometry(0.0042, 12, 10),
      new THREE.MeshBasicMaterial({ color: col, depthTest: false, transparent: true })
    );
    dot.position.copy(p);
    dot.renderOrder = 998;

    const ring = new THREE.Mesh(
      new THREE.RingGeometry(0.0064, 0.0082, 22),
      new THREE.MeshBasicMaterial({
        color: col, transparent: true, opacity: 0.5,
        side: THREE.DoubleSide, depthTest: false,
      })
    );
    ring.position.copy(p);
    ring.renderOrder = 998;

    const label = socketLabelSprite(name.replace('SOCKET_', ''));
    label.position.copy(p).add(new THREE.Vector3(0, 0.032, 0));

    socketGroup.add(dot, ring, label);
    socketLabels.push(label);
  }
  socketGroup.visible = $('tgSockets').checked;
}

async function buildColliders() {
  try {
    const gltf = await loadGLB(COLLIDERS);
    colliderGroup.clear();
    gltf.scene.traverse((o) => {
      if (!o.isMesh) return;
      colliderGroup.add(new THREE.LineSegments(
        new THREE.EdgesGeometry(o.geometry, 18),
        new THREE.LineBasicMaterial({ color: 0xff6b5a, transparent: true, opacity: 0.5 })
      ));
    });
  } catch { /* optionnel */ }
  colliderGroup.visible = $('tgColliders').checked;
}

/* ------------------------------------------------------------------- stats */
const nf = (n) => n.toLocaleString('fr-FR').replace(/\u202f|\u00a0/g, ' ');
const mm = (v) => Math.round(v * 1000);

function updateStats() {
  if (!modelRoot) return;
  box.setFromObject(root);
  const size = box.getSize(new THREE.Vector3());
  let tris = 0, meshes = 0;
  modelRoot.traverse((o) => {
    if (!o.isMesh) return;
    meshes++;
    const g = o.geometry;
    tris += g.index ? g.index.count / 3 : g.attributes.position.count / 3;
  });
  tris = Math.round(tris);
  const len = Math.max(size.x, size.y, size.z);
  $('stats').innerHTML = `
    <dt>Longueur</dt><dd>${mm(len)} mm</dd>
    <dt>Hauteur</dt><dd>${mm(size.y)} mm</dd>
    <dt>Largeur</dt><dd>${mm(size.x)} mm</dd>
    <dt>Triangles</dt><dd>${nf(tris)}</dd>
    <dt>Maillages</dt><dd>${meshes}</dd>`;
  $('subtitle').textContent = `${mm(len)} mm · ${nf(tris)} tris · LOD${currentLod}`;
  document.title = `G36E — ${mm(len)} mm · ${nf(tris)} tris`;
}

/* ------------------------------------------------------------------ cadrage */
function centerOf() {
  box.setFromObject(root);
  return { c: box.getCenter(new THREE.Vector3()), s: box.getSize(new THREE.Vector3()) };
}

function framePerspective(view) {
  const { c, s } = centerOf();
  const d = Math.max(s.x, s.y, s.z) * 1.25;
  // le canon pointe vers -Z une fois le modèle passé en Y-up
  const pos = {
    quart: [c.x - d * 0.78, c.y + s.y * 1.5, c.z - d * 0.72],
    dessus: [c.x + 0.0005, c.y + d * 1.35, c.z],
    face: [c.x, c.y + s.y * 0.35, c.z - d * 1.25],
    arriere: [c.x - d * 0.55, c.y + s.y * 1.1, c.z + d],
  }[view] || [c.x - d * 0.8, c.y + s.y * 1.4, c.z - d * 0.7];

  controls.target.copy(c);
  persp.position.set(...pos);
  persp.lookAt(c);
  controls.update();
}

function setOrthoProfile() {
  const { c, s } = centerOf();
  ortho.left = -s.z / 2;
  ortho.right = s.z / 2;
  ortho.top = s.y / 2;
  ortho.bottom = -s.y / 2;
  ortho.position.set(c.x - Math.max(s.x, s.y, s.z) * 2, c.y, c.z);
  ortho.up.set(0, 1, 0);
  ortho.lookAt(c);
  ortho.updateProjectionMatrix();
}

function setMode(next, viewKey) {
  mode = next;
  activeCam = next === 'ortho' ? ortho : persp;
  controls.enabled = next === 'persp';
  if (next === 'ortho') setOrthoProfile();
  if (viewKey) {
    document.querySelectorAll('#viewBtns button')
      .forEach((b) => b.classList.toggle('on', b.dataset.view === viewKey));
  }
}

/* ---------------------------------------------------------------------- UI */
function buildButtons() {
  const views = [
    ['quart', '3/4'], ['profil', 'Profil'], ['dessus', 'Dessus'],
    ['face', 'Face'], ['arriere', 'Arrière'],
  ];
  const vc = $('viewBtns');
  for (const [k, lbl] of views) {
    const b = document.createElement('button');
    b.textContent = lbl;
    b.dataset.view = k;
    b.onclick = () => {
      if (k === 'profil') {
        setMode('ortho', 'profil');
      } else {
        setMode('persp', k);
        framePerspective(k);
      }
    };
    vc.appendChild(b);
  }

  const lc = $('lodBtns');
  for (const n of [0, 1, 2]) {
    const b = document.createElement('button');
    b.textContent = `LOD${n}`;
    b.dataset.lod = n;
    b.onclick = () => showLod(n).catch(console.error);
    lc.appendChild(b);
  }
}

$('tgSpin').onchange = (e) => { controls.autoRotate = e.target.checked; };
$('tgEdges').onchange = rebuildEdges;
$('tgWire').onchange = (e) => {
  if (!modelRoot) return;
  modelRoot.traverse((o) => {
    if (!o.isMesh) return;
    for (const m of (Array.isArray(o.material) ? o.material : [o.material])) {
      if (m) m.wireframe = e.target.checked;
    }
  });
};
$('tgSockets').onchange = (e) => { socketGroup.visible = e.target.checked; };
$('tgColliders').onchange = (e) => { colliderGroup.visible = e.target.checked; };
$('tgGrid').onchange = (e) => { ground.visible = e.target.checked; };

/* ------------------------------------------------------------ comparaison */
const layer = $('compareLayer');
const photo = $('refPhoto');
const handle = $('splitHandle');
let compareOn = false;

function applyCompare() {
  const op = +$('rgOpacity').value / 100;
  photo.style.opacity = op;
  if ($('tgBlend').checked) {
    photo.style.clipPath = 'none';
    handle.style.display = 'none';
    $('compareTag3d').style.display = 'none';
    $('compareTagRef').textContent = 'PHOTO + 3D';
  } else {
    const sp = +$('rgSplit').value;
    photo.style.clipPath = `inset(0 ${100 - sp}% 0 0)`;
    handle.style.display = '';
    handle.style.left = sp + '%';
    $('compareTag3d').style.display = '';
    $('compareTagRef').textContent = 'PHOTO';
  }
}

$('btnCompare').onclick = () => {
  compareOn = !compareOn;
  layer.classList.toggle('hidden', !compareOn);
  $('compareCtl').classList.toggle('hidden', !compareOn);
  $('btnCompare').classList.toggle('on', compareOn);
  $('btnCompare').textContent = compareOn
    ? 'Masquer la photo'
    : 'Superposer la photo de référence';
  if (compareOn) {
    setMode('ortho', 'profil');
    controls.autoRotate = false;
    $('tgSpin').checked = false;
    applyCompare();
  }
};
['rgOpacity', 'rgSplit', 'tgBlend'].forEach((id) =>
  $(id).addEventListener('input', applyCompare));

let dragging = false;
handle.addEventListener('pointerdown', (e) => {
  dragging = true;
  handle.setPointerCapture(e.pointerId);
});
handle.addEventListener('pointermove', (e) => {
  if (!dragging) return;
  const r = layer.getBoundingClientRect();
  const pct = Math.min(100, Math.max(0, ((e.clientX - r.left) / r.width) * 100));
  $('rgSplit').value = pct;
  applyCompare();
});
handle.addEventListener('pointerup', () => { dragging = false; });
handle.addEventListener('pointercancel', () => { dragging = false; });

window.addEventListener('keydown', (e) => {
  const k = e.key.toLowerCase();
  if (k === 'r') {
    setMode('persp', 'quart');
    framePerspective('quart');
    controls.autoRotate = true;
    $('tgSpin').checked = true;
  }
  const map = { 1: 'quart', 2: 'profil', 3: 'dessus', 4: 'face', 5: 'arriere' };
  if (map[k]) document.querySelector(`#viewBtns button[data-view="${map[k]}"]`)?.click();
});

/* ------------------------------------------------------------------ resize */
function resize() {
  const r = canvas.parentElement.getBoundingClientRect();
  const w = Math.max(1, r.width);
  const h = Math.max(1, r.height);
  renderer.setSize(w, h, false);
  persp.aspect = w / h;
  persp.updateProjectionMatrix();
  if (mode === 'ortho') setOrthoProfile();
}
new ResizeObserver(resize).observe(canvas.parentElement);
addEventListener('resize', resize);

/* ------------------------------------------------------------------ boucle */
const clock = new THREE.Clock();
const focus = new THREE.Vector3();
renderer.setAnimationLoop(() => {
  const dt = clock.getDelta();
  if (mode === 'persp') controls.update(dt);
  if (socketLabels.length) {
    const near = activeCam.position.distanceTo(focus) < 2.2;
    socketLabels.forEach((s) => { s.visible = near; });
  }
  renderer.render(scene, activeCam);
});

/* --------------------------------------------------------------- démarrage */
(async function init() {
  buildButtons();
  resize();
  try {
    await showLod(0);
  } catch (err) {
    console.error(err);
    $('loader').innerHTML =
      `<p style="max-width:440px;text-align:center;line-height:1.7">
         GLB introuvable dans <code>exports/g36_rifle/</code>.<br>
         Génère-le d'abord :<br>
         <code style="font-size:11px;color:#8fd4ff">python3 scripts/turbo_forge.py g36 -o exports/g36</code>
       </p>`;
    return;
  }
  setMode('persp', 'quart');
  framePerspective('quart');
  updateStats();
  $('loader').classList.add('gone');

  buildSockets().catch(() => {});
  buildColliders().catch(() => {});
})();
