import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';

var container = document.getElementById('vrmContainer');
if (!container) {
    console.error('[PRAVAHA] vrmContainer not found');
    throw new Error('vrmContainer not found');
}

function getSize() {
    var w = container.clientWidth;
    var h = container.clientHeight;
    if (w === 0 || h === 0) {
        var parent = container.parentElement;
        if (parent) {
            w = parent.clientWidth;
            h = parent.clientHeight;
        }
    }
    return { w: Math.max(w, 320), h: Math.max(h, 400) };
}

var sz = getSize();
console.log('[PRAVAHA] 3D container size:', sz.w, 'x', sz.h);

var scene = new THREE.Scene();

var camera = new THREE.PerspectiveCamera(30, sz.w / sz.h, 0.1, 20);
camera.position.set(0, 0.8, 4.5);
camera.lookAt(0, 0.5, 0);

var renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true });
renderer.setSize(sz.w, sz.h);
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
try { renderer.toneMapping = THREE.ACESFilmicToneMapping; } catch (e) { renderer.toneMapping = THREE.ReinhardToneMapping; }
renderer.toneMappingExposure = 1.2;
renderer.outputColorSpace = THREE.SRGBColorSpace;
container.appendChild(renderer.domElement);

console.log('[PRAVAHA] Three.js renderer created, canvas:', renderer.domElement);

// ── Lights (optimized: 4 lights for performance) ──
scene.add(new THREE.AmbientLight(0x403828, 0.5));

var key = new THREE.DirectionalLight(0xffffff, 2.0);
key.position.set(2, 3, 4);
scene.add(key);

scene.add(new THREE.HemisphereLight(0xe0d0b0, 0x333328, 0.4));

var neon = new THREE.PointLight(0xFF9933, 12, 8, 1.5);
neon.position.set(0, 0.8, 1.8);
scene.add(neon);

// ── Debug helper (removed when model loads) ──
var debugGroup = new THREE.Group();
var cubeGeo = new THREE.BoxGeometry(0.1, 0.1, 0.1);
var cubeMat = new THREE.MeshBasicMaterial({ color: 0x7EC8E3, wireframe: true });
var debugCube = new THREE.Mesh(cubeGeo, cubeMat);
debugGroup.add(debugCube);
var gridHelper = new THREE.GridHelper(4, 8, 0x7EC8E3, 0x333355);
gridHelper.position.y = -1;
debugGroup.add(gridHelper);
scene.add(debugGroup);

// ── Model state ──
var model = null;
var mixer = null;
var materials = [];
var centerY = 0;
var baseScale = 1;
var modelLoaded = false;

// ── Mouth & hand state ──
var mouthMesh = null;
var mouthIndex = -1;
var mouthInfluence = 0;
var mouthBone = null;
var mouthBoneRot = 0;
var blinkMesh = null;
var blinkIndex = -1;
var blinkInfluence = 0;
var blinkTarget = 0;
var leftHandBones = [];
var rightHandBones = [];
var handBonePhases = [];

var loader = new GLTFLoader();
console.log('[PRAVAHA] Loading model from /models/shree_krishna.glb');
loader.load('./models/shree_krishna.glb', function (gltf) {
    model = gltf.scene;
    scene.add(model);

    var box = new THREE.Box3().setFromObject(model);
    var center = box.getCenter(new THREE.Vector3());
    var size = box.getSize(new THREE.Vector3());
    var maxDim = Math.max(size.x, size.y, size.z);
    var scale = 5.0 / maxDim;
    model.scale.set(scale, scale, scale);
    model.position.y = -center.y * scale - 1.0;
    centerY = center.y * scale + 1.0;
    baseScale = scale;
    model.rotation.y = 0;

    var matCount = 0;
    model.traverse(function (node) {
        if (!node.isMesh) return;
        var mats = Array.isArray(node.material) ? node.material : [node.material];
        mats.forEach(function (m) {
            if (m.isMeshStandardMaterial || m.isMeshPhysicalMaterial) {
                materials.push(m);
                matCount++;
                m.emissiveIntensity = 0.05;
            }
        });
        // Check for mouth morph targets
        if (node.morphTargetDictionary && node.morphTargetInfluences && mouthIndex < 0) {
            var mouthKeys = ['mouthOpen', 'jawOpen', 'mouth_A', 'mouth_O', 'MouthOpen', 'JawOpen'];
            for (var k = 0; k < mouthKeys.length; k++) {
                var idx = node.morphTargetDictionary[mouthKeys[k]];
                if (idx !== undefined) {
                    mouthMesh = node;
                    mouthIndex = idx;
                    console.log('[PRAVAHA] Found mouth morph:', mouthKeys[k], 'on', node.name || 'unnamed');
                    break;
                }
            }
        }
        // Check for eye blink morph targets
        if (node.morphTargetDictionary && node.morphTargetInfluences && blinkIndex < 0) {
            var eyeKeys = ['blink', 'eyeBlink', 'blink_L', 'blink_R', 'EyeBlink', 'Blink', 'eye_close', 'eyeClose'];
            for (var e = 0; e < eyeKeys.length; e++) {
                var eidx = node.morphTargetDictionary[eyeKeys[e]];
                if (eidx !== undefined) {
                    blinkIndex = eidx;
                    blinkMesh = node;
                    console.log('[PRAVAHA] Found blink morph:', eyeKeys[e], 'on', node.name || 'unnamed');
                    break;
                }
            }
        }
    });

    if (gltf.animations && gltf.animations.length) {
        mixer = new THREE.AnimationMixer(model);
        gltf.animations.forEach(function (clip) { mixer.clipAction(clip).play(); });
    }

    modelLoaded = true;
    console.log('[PRAVAHA] Model loaded OK | size:', size, 'center:', center, 'scale:', scale, 'position:', model.position, 'materials:', matCount, 'animations:', gltf.animations ? gltf.animations.length : 0, 'mouthMorph:', mouthIndex >= 0);

    // Show model info in status pill
    var pill = document.getElementById('orbStatusText');
    if (pill) pill.textContent = 'PRAVAHA ● H:' + size.y.toFixed(2) + ' Y:' + model.position.y.toFixed(2);

    // Fallback: try jaw bone if no morph target
    if (mouthIndex < 0) {
        model.traverse(function (node) {
            if (node.isBone && /jaw|chin/i.test(node.name)) {
                mouthBone = node;
                mouthBoneRot = node.rotation.x;
                console.log('[PRAVAHA] Found jaw bone:', node.name);
            }
        });
    }

    // Hand bone detection
    model.traverse(function (node) {
        if (!node.isBone) return;
        var n = node.name.toLowerCase();
        if (!/hand|wrist|finger|arm_ik/i.test(n)) return;
        if (/left|_l$/i.test(n)) {
            leftHandBones.push(node);
        } else if (/right|_r$/i.test(n)) {
            rightHandBones.push(node);
        }
    });
    var allHands = leftHandBones.concat(rightHandBones);
    handBonePhases = allHands.map(function () { return Math.random() * 6.28; });
    console.log('[PRAVAHA] Hand bones - left:', leftHandBones.length, 'right:', rightHandBones.length);

    // Remove debug helper
    scene.remove(debugGroup);
}, function (xhr) {
    var pct = Math.round(xhr.loaded / xhr.total * 100);
    if (pct % 25 === 0) console.log('[PRAVAHA] Model loading:', pct + '%');
}, function (err) {
    console.error('[PRAVAHA] Model load error:', err);
});

// ── Animation loop ──
var time = 0;
var blinkHold = 0;
var nextBlinkTime = 3 + Math.random() * 4;
var lastSpeakingState = null;
function ensureSpeakingDriver() {
    if (window.__pravahaState === 'speaking' && !window.__pravahaSpeakingFallback) {
        window.__pravahaSpeakingFallback = {
            phase: Math.random() * 6.28,
            speed: 0.08 + Math.random() * 0.18,
            amp: 0.22 + Math.random() * 0.38
        };
    }
}
function updateSpeakingFallback() {
    if (!window.__pravahaSpeakingFallback) return;
    window.__pravahaSpeakingFallback.phase += window.__pravahaSpeakingFallback.speed;
    var fallbackLevel = (Math.sin(window.__pravahaSpeakingFallback.phase) * 0.5 + 0.5) * window.__pravahaSpeakingFallback.amp;
    var current = typeof window.__pravahaLevel === 'number' ? window.__pravahaLevel : 0;
    window.__pravahaLevel = Math.max(current, fallbackLevel);
}

function animate() {
    time += 0.016;

    var state = window.__pravahaState || 'idle';
    if (lastSpeakingState !== 'speaking' && state === 'speaking') ensureSpeakingDriver();
    if (state === 'speaking') updateSpeakingFallback();
    else window.__pravahaSpeakingFallback = null;
    lastSpeakingState = state;

    var level = window.__pravahaLevel || 0;
    var isActive = state === 'listening' || state === 'speaking';

    if (model) {
        var floatY = Math.sin(time * 1.2) * 0.04;
        var swayX = Math.sin(time * 0.7) * 0.01;
        var swayZ = Math.sin(time * 0.9) * 0.012;
        var breath = 1 + Math.sin(time * 0.8) * 0.004;

        var bounce = 0, lean = 0, pulse = 0, headTiltX = 0, headTiltZ = 0;
        if (isActive && level > 0.03) {
            bounce = level * 0.03;
            lean = level * 0.025;
            pulse = level * 0.006;
            headTiltX = Math.sin(time * 2.4) * level * 0.03;
            headTiltZ = Math.cos(time * 2.1) * level * 0.02;
        }

        model.position.y = -centerY + floatY + bounce;
        model.rotation.x = swayX + lean * 0.5 + headTiltX;
        model.rotation.y = 0;
        model.rotation.z = swayZ + lean + headTiltZ;
        model.scale.setScalar(baseScale * (breath + pulse));

        if (mixer) mixer.update(0.016);

        var targetEmissive = isActive && level > 0.05 ? Math.min(0.35, level * 0.4) : 0;
        materials.forEach(function (m) {
            m.emissiveIntensity += (targetEmissive - m.emissiveIntensity) * 0.06;
        });

        // Mouth movement from audio
        var targetMouth = 0;
        if (window.__pravahaState === 'speaking') {
            var level = typeof window.__pravahaLevel === 'number' ? window.__pravahaLevel : 0;
            if (level > 0.05) {
                targetMouth = Math.min(1, level * 2.5);
            } else if (!window.__pravahaSpeakingFallback) {
                window.__pravahaSpeakingFallback = {
                    phase: Math.random() * 6.28,
                    speed: 0.06 + Math.random() * 0.14,
                    amp: 0.18 + Math.random() * 0.35
                };
            }
            if (window.__pravahaSpeakingFallback) {
                window.__pravahaSpeakingFallback.phase += window.__pravahaSpeakingFallback.speed;
                targetMouth = Math.max(targetMouth, (Math.sin(window.__pravahaSpeakingFallback.phase) * 0.5 + 0.5) * window.__pravahaSpeakingFallback.amp);
            }
        } else {
            window.__pravahaSpeakingFallback = null;
        }
        mouthInfluence += (targetMouth - mouthInfluence) * 0.2;
        if (mouthMesh && mouthIndex >= 0) {
            mouthMesh.morphTargetInfluences[mouthIndex] = mouthInfluence;
        } else if (mouthBone) {
            mouthBone.rotation.x = mouthBoneRot - mouthInfluence * 0.12;
        }

        // Blink animation
        if (blinkIndex >= 0) {
            nextBlinkTime -= 0.016;
            if (nextBlinkTime <= 0 && blinkTarget === 0 && blinkHold <= 0) {
                blinkTarget = 1;
                blinkHold = 0.14;
                nextBlinkTime = 2.2 + Math.random() * 4.2;
                if (isActive) nextBlinkTime *= 0.7;
            }
            if (blinkTarget === 1) {
                blinkInfluence += (1 - blinkInfluence) * 0.35;
                if (blinkInfluence > 0.85) {
                    blinkTarget = 0;
                    blinkHold = 0.06;
                }
            } else if (blinkHold > 0) {
                blinkHold -= 0.016;
            } else {
                blinkInfluence += (0 - blinkInfluence) * 0.28;
            }
            if (blinkMesh && blinkIndex >= 0) {
                blinkMesh.morphTargetInfluences[blinkIndex] = blinkInfluence;
            }
        }

        // Hand animation
        var handSway = Math.sin(time * 0.6) * 0.025;
        var handGesture = isActive && level > 0.05 ? level * 0.06 : 0;
        leftHandBones.forEach(function (b, i) {
            var p = handBonePhases[i] || 0;
            b.rotation.z = handSway + Math.sin(time * 0.8 + p) * 0.015 + handGesture;
            b.rotation.x = Math.sin(time * 0.5 + p) * 0.008;
        });
        rightHandBones.forEach(function (b, i) {
            var p = handBonePhases[(leftHandBones.length + i)] || 0;
            b.rotation.z = -handSway + Math.sin(time * 0.9 + p) * 0.015 - handGesture;
            b.rotation.x = Math.cos(time * 0.55 + p) * 0.008;
        });
    }

    renderer.render(scene, camera);
}

window.__pravahaRenderVrm = animate;

// ── Zoom controls ──
var baseCameraZ = camera.position.z;
var zoomFactor = 1;
var zoomMin = 0.3;
var zoomMax = 2.5;

window.__zoomIn = function () {
    zoomFactor = Math.max(zoomMin, zoomFactor * 0.85);
    camera.position.z = baseCameraZ * zoomFactor;
};
window.__zoomOut = function () {
    zoomFactor = Math.min(zoomMax, zoomFactor / 0.85);
    camera.position.z = baseCameraZ * zoomFactor;
};
window.__zoomReset = function () {
    zoomFactor = 1;
    camera.position.z = baseCameraZ;
};

// ── Resize ──
function onResize() {
    sz = getSize();
    if (sz.w > 0 && sz.h > 0) {
        camera.aspect = sz.w / sz.h;
        camera.updateProjectionMatrix();
        renderer.setSize(sz.w, sz.h);
    }
}
window.addEventListener('resize', onResize);

if (window.ResizeObserver) {
    var ro = new ResizeObserver(function () { onResize(); });
    ro.observe(container);
}

console.log('[PRAVAHA] 3D module initialized');
