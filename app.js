(function() {
    'use strict';

    /* ═══════════════════════════════════════════════════════════════
        BACKGROUND: PRAVAHA dark scene with mountains
    ═══════════════════════════════════════════════════════════════ */
    (function initBackground() {
        const canvas = document.getElementById('bgCanvas');
        if (!canvas) return;
        const ctx = canvas.getContext('2d');

        function resize() {
            canvas.width = window.innerWidth;
            canvas.height = window.innerHeight;
        }
        resize();
        window.addEventListener('resize', resize);

        function drawMountains() {
            const w = canvas.width;
            const h = canvas.height;
            ctx.clearRect(0, 0, w, h);

            const sky = ctx.createLinearGradient(0, 0, 0, h);
            sky.addColorStop(0, '#05050f');
            sky.addColorStop(0.5, '#0a0a18');
            sky.addColorStop(1, '#0d0d20');
            ctx.fillStyle = sky;
            ctx.fillRect(0, 0, w, h);

            ctx.fillStyle = 'rgba(255,255,255,0.3)';
            for (let i = 0; i < 80; i++) {
                const sx = (Math.sin(i * 127.1) * 0.5 + 0.5) * w;
                const sy = (Math.sin(i * 311.7) * 0.5 + 0.5) * h * 0.5;
                const sr = Math.random() * 1.2 + 0.2;
                ctx.beginPath();
                ctx.arc(sx, sy, sr, 0, Math.PI * 2);
                ctx.fill();
            }

            const layers = [
                { color: 'rgba(20,30,60,0.8)', yBase: h * 0.55, amplitude: h * 0.2, freq: 0.003 },
                { color: 'rgba(12,18,38,0.9)', yBase: h * 0.62, amplitude: h * 0.15, freq: 0.005 },
                { color: 'rgba(8,12,28,1)', yBase: h * 0.72, amplitude: h * 0.1, freq: 0.008 },
            ];

            layers.forEach((layer, li) => {
                ctx.beginPath();
                ctx.moveTo(0, h);
                for (let x = 0; x <= w; x += 3) {
                    const noise = Math.sin(x * layer.freq + li * 1.5) * 0.5 +
                                  Math.sin(x * layer.freq * 2.3 + li * 3.1) * 0.3 +
                                  Math.sin(x * layer.freq * 0.5 + li * 0.7) * 0.2;
                    const y = layer.yBase - layer.amplitude * noise;
                    ctx.lineTo(x, y);
                }
                ctx.lineTo(w, h);
                ctx.closePath();
                ctx.fillStyle = layer.color;
                ctx.fill();
            });
        }

        drawMountains();
        window.addEventListener('resize', drawMountains);
    })();

    /* ═══════════════════════════════════════════════════════════════
       3D HOLOGRAPHIC SPHERE — VOLUMETRIC (particles with depth)
    ═══════════════════════════════════════════════════════════════ */
    let holoScene, holoCamera, holoRenderer;
    let vs1, vs2, vs3, coreSphere;
    let sphereTime = 0;
    let audioLevel = 0;
    let targetAudioLevel = 0;

    /* ── Per-particle volumetric: position + depth + phase + size ── */
    const VOL_VS = `
        attribute float aDepth;
        attribute float aPhase;
        attribute float aSize;
        varying float vDepth;
        varying float vPhase;
        uniform float uTime;
        uniform float uAudioLevel;

        void main() {
            vDepth = aDepth;
            vPhase = aPhase;

            // Gentle orbit inside the sphere volume
            float angle = uTime * 0.35 + aPhase * 6.2832;
            vec3 pos = position;
            pos.x += sin(angle * 1.7 + aDepth * 3.14) * 0.04 * aDepth;
            pos.y += cos(angle * 2.1 + aPhase * 6.2832) * 0.03 * aDepth;
            pos.z += sin(angle * 1.3 + aDepth * 2.71) * 0.035 * aDepth;

            // Audio pulse: expand slightly
            float scale = 1.0 + uAudioLevel * 0.2;
            pos *= scale;

            vec4 mvPos = modelViewMatrix * vec4(pos, 1.0);
            float distScale = 280.0 / -mvPos.z;
            gl_PointSize = aSize * (1.0 + uAudioLevel * 1.4) * distScale;
            gl_Position = projectionMatrix * mvPos;
        }
    `;

    /* ── Front-facing dot (subtle, not blinding) ── */
    const FRONT_FS = `
        varying float vDepth;
        varying float vPhase;
        uniform float uAudioLevel;

        void main() {
            vec2 c = gl_PointCoord - 0.5;
            float d = length(c);
            if (d > 0.5) discard;

            // Soft dot with gentle falloff
            float alpha = 1.0 - smoothstep(0.1, 0.5, d);
            alpha = pow(alpha, 1.5);

            // Depth-based fade — deeper = dimmer
            float depthFade = 0.25 + vDepth * 0.5;
            float audioBoost = 1.0 + uAudioLevel * 0.5;

            // Color: saffron→gold
            float t = 0.5 + 0.5 * sin(vPhase * 4.0);
            vec3 saffron = vec3(1.0, 0.6, 0.2);
            vec3 gold = vec3(1.0, 0.85, 0.0);
            vec3 col = mix(saffron, gold, t * 0.25);
            col *= depthFade * audioBoost;

            gl_FragColor = vec4(col, alpha * (0.45 + uAudioLevel * 0.2));
        }
    `;

    /* ── Back-facing dot (very faint glow) ── */
    const BACK_FS = `
        varying float vDepth;
        varying float vPhase;
        uniform float uAudioLevel;

        void main() {
            vec2 c = gl_PointCoord - 0.5;
            float d = length(c);
            if (d > 0.5) discard;

            float alpha = 1.0 - smoothstep(0.15, 0.5, d);
            alpha = pow(alpha, 2.0);

            float audioBoost = 1.0 + uAudioLevel * 0.4;
            float t = 0.5 + 0.5 * sin(vPhase * 3.0 + uTime * 0.5);
            vec3 col = mix(vec3(0.8, 0.4, 0.1), vec3(1.0, 0.75, 0.0), t * 0.2);
            col *= 0.25 * audioBoost;

            gl_FragColor = vec4(col, alpha * 0.2 * (0.4 + uAudioLevel));
        }
    `;

    /* ── Core inner sphere (gives solid volumetric center) ── */
    const CORE_VS = `
        varying vec3 vNormal;
        varying vec3 vWorldPos;
        void main() {
            vNormal = normalize(normalMatrix * normal);
            vWorldPos = (modelMatrix * vec4(position, 1.0)).xyz;
            gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
        }
    `;
    const CORE_FS = `
        varying vec3 vNormal;
        varying vec3 vWorldPos;
        uniform float uTime;
        uniform float uAudioLevel;
        void main() {
            vec3 viewDir = normalize(cameraPosition - vWorldPos);
            float rim = pow(1.0 - max(dot(vNormal, viewDir), 0.0), 2.5);
            float pulse = 0.6 + sin(uTime * 1.5) * 0.05 + uAudioLevel * 0.2;
            vec3 col = mix(vec3(0.6, 0.3, 0.05), vec3(1.0, 0.65, 0.15), rim);
            col = mix(col, vec3(1.0, 0.85, 0.0), rim * 0.25);
            float alpha = rim * 0.35 * pulse;
            gl_FragColor = vec4(col * pulse, alpha);
        }
    `;

    function initHoloSphere() {
        const canvas = document.getElementById('holoSphereCanvas');
        if (!canvas) return;
        const wrap = canvas.parentElement;
        const w = wrap.clientWidth || 400;
        const h = wrap.clientHeight || 300;

        holoScene = new THREE.Scene();
        holoCamera = new THREE.PerspectiveCamera(45, w / h, 0.1, 100);
        holoCamera.position.z = 4.5;

        holoRenderer = new THREE.WebGLRenderer({
            canvas, antialias: true, alpha: true, powerPreference: 'high-performance'
        });
        holoRenderer.setSize(w, h);
        holoRenderer.setClearColor(0x000000, 0);

        /* ── Build VOLUMETRIC particle cloud ──
           Particles distributed throughout the SPHERE VOLUME (not surface).
           Three layers at different depths create volumetric depth.
        */

        function buildVolumeLayer(count, rMin, rMax, dotSize) {
            const pos = new Float32Array(count * 3);
            const depth = new Float32Array(count);
            const phase = new Float32Array(count);
            const size = new Float32Array(count);

            for (let i = 0; i < count; i++) {
                // Random point in sphere (uniform volume distribution)
                const u = Math.random();
                const v = Math.random();
                const theta = 2 * Math.PI * u;
                const phi = Math.acos(2 * v - 1);
                const r = Math.cbrt(Math.random()) * (rMax - rMin) + rMin;

                pos[i * 3]     = r * Math.sin(phi) * Math.cos(theta);
                pos[i * 3 + 1] = r * Math.sin(phi) * Math.sin(theta);
                pos[i * 3 + 2] = r * Math.cos(phi);

                depth[i] = r / rMax;  // 0=center, 1=edge
                phase[i] = Math.random();
                size[i] = dotSize * (0.6 + Math.random() * 0.8);
            }

            const geo = new THREE.BufferGeometry();
            geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
            geo.setAttribute('aDepth',   new THREE.BufferAttribute(depth, 1));
            geo.setAttribute('aPhase',   new THREE.BufferAttribute(phase, 1));
            geo.setAttribute('aSize',    new THREE.BufferAttribute(size, 1));
            return geo;
        }

        // ── Layer 1: Inner dense core (closest to camera = brightest) ──
        const geo1 = buildVolumeLayer(1200, 0.0, 0.72, 1.8);
        const mat1 = new THREE.ShaderMaterial({
            vertexShader: VOL_VS, fragmentShader: FRONT_FS,
            uniforms: { uTime: { value: 0 }, uAudioLevel: { value: 0 } },
            transparent: true, blending: THREE.NormalBlending, depthWrite: false
        });
        vs1 = new THREE.Points(geo1, mat1);
        holoScene.add(vs1);

        // ── Layer 2: Mid volume ──
        const geo2 = buildVolumeLayer(900, 0.4, 1.1, 1.2);
        const mat2 = new THREE.ShaderMaterial({
            vertexShader: VOL_VS, fragmentShader: BACK_FS,
            uniforms: { uTime: { value: 0 }, uAudioLevel: { value: 0 } },
            transparent: true, blending: THREE.AdditiveBlending, depthWrite: false
        });
        vs2 = new THREE.Points(geo2, mat2);
        holoScene.add(vs2);

        // ── Layer 3: Outer atmosphere (faint, furthest) ──
        const geo3 = buildVolumeLayer(500, 0.7, 1.4, 0.8);
        const mat3 = new THREE.ShaderMaterial({
            vertexShader: VOL_VS, fragmentShader: BACK_FS,
            uniforms: { uTime: { value: 0 }, uAudioLevel: { value: 0 } },
            transparent: true, blending: THREE.AdditiveBlending, depthWrite: false
        });
        vs3 = new THREE.Points(geo3, mat3);
        holoScene.add(vs3);

        // ── Core sphere: solid inner glow ──
        const coreGeo = new THREE.SphereGeometry(0.9, 24, 24);
        const coreMat = new THREE.ShaderMaterial({
            vertexShader: CORE_VS, fragmentShader: CORE_FS,
            uniforms: { uTime: { value: 0 }, uAudioLevel: { value: 0 } },
            transparent: true, blending: THREE.AdditiveBlending, side: THREE.FrontSide, depthWrite: false
        });
        coreSphere = new THREE.Mesh(coreGeo, coreMat);
        holoScene.add(coreSphere);

        try { updateSphere(); } catch(e) {}

        new ResizeObserver(() => {
            if (!holoRenderer) return;
            const pw = wrap.clientWidth || 400;
            const ph = wrap.clientHeight || 300;
            holoRenderer.setSize(pw, ph);
            holoCamera.aspect = pw / ph;
            holoCamera.updateProjectionMatrix();
        }).observe(wrap);
    }

    function updateSphere() {
        sphereTime += 0.007;
        audioLevel += (targetAudioLevel - audioLevel) * 0.05;

        const t = sphereTime, al = audioLevel;

        [vs1, vs2, vs3].forEach((vs, i) => {
            if (!vs) return;
            vs.material.uniforms.uTime.value = t;
            vs.material.uniforms.uAudioLevel.value = al;
            vs.rotation.y = t * (0.04 + i * 0.01);
            vs.rotation.x = t * (0.015 + i * 0.005);
        });

        if (coreSphere) {
            coreSphere.material.uniforms.uTime.value = t;
            coreSphere.material.uniforms.uAudioLevel.value = al;
            coreSphere.rotation.y = t * 0.08;
        }

        holoRenderer?.render(holoScene, holoCamera);
    }

    try { initHoloSphere(); } catch (e) { console.warn('Sphere init failed:', e); }

    /* ═══════════════════════════════════════════════════════════════
       TERRAIN CHART
    ═══════════════════════════════════════════════════════════════ */
    var __terrainDraw = null;
    (function initTerrainChart() {
        const canvas = document.getElementById('terrainCanvas');
        if (!canvas) return;
        const ctx = canvas.getContext('2d');

        function resize() {
            const r = canvas.parentElement.getBoundingClientRect();
            canvas.width = r.width; canvas.height = 100;
        }
        resize();
        window.addEventListener('resize', resize);

        const PTS = 80;
        let terrain = Array.from({ length: PTS }, () => Math.random());

        __terrainDraw = function() {
            const w = canvas.width, h = canvas.height;
            ctx.clearRect(0, 0, w, h);

            terrain.shift();
            terrain.push(terrain[PTS - 1] * 0.7 + Math.random() * 0.3);

            const step = w / (PTS - 1);

            const grad = ctx.createLinearGradient(0, 0, 0, h);
            grad.addColorStop(0, 'rgba(255,153,51,0.12)');
            grad.addColorStop(0.5, 'rgba(255,200,80,0.06)');
            grad.addColorStop(1, 'rgba(200,140,20,0.02)');

            ctx.beginPath(); ctx.moveTo(0, h);
            for (let i = 0; i < PTS; i++) {
                const x = i * step;
                const y = h - terrain[i] * h * 0.85 - 5;
                i === 0 ? ctx.lineTo(x, y) : ctx.quadraticCurveTo((i - 1) * step, h - terrain[i - 1] * h * 0.85 - 5, x, y);
            }
            ctx.lineTo(w, h); ctx.closePath();
            ctx.fillStyle = grad; ctx.fill();

            ctx.beginPath();
            for (let i = 0; i < PTS; i++) {
                const x = i * step, y = h - terrain[i] * h * 0.85 - 5;
                i === 0 ? ctx.moveTo(x, y) : ctx.quadraticCurveTo((i - 1) * step, h - terrain[i - 1] * h * 0.85 - 5, x, y);
            }
            ctx.strokeStyle = 'rgba(255,153,51,0.5)'; ctx.lineWidth = 1.5; ctx.stroke();

            ctx.beginPath();
            for (let i = 0; i < PTS; i++) {
                const x = i * step, y = h - terrain[i] * h * 0.5 - 10;
                i === 0 ? ctx.moveTo(x, y) : ctx.quadraticCurveTo((i - 1) * step, h - terrain[i - 1] * h * 0.5 - 10, x, y);
            }
            ctx.strokeStyle = 'rgba(255,215,0,0.3)'; ctx.lineWidth = 1; ctx.stroke();

            ctx.strokeStyle = 'rgba(255,255,255,0.02)'; ctx.lineWidth = 0.5;
            for (let y = 0; y < h; y += 15) { ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke(); }
        };
    })();

    /* ═══════════════════════════════════════════════════════════════
       GAUGE — semi-circular
    ═══════════════════════════════════════════════════════════════ */
    var __gaugeDraw = null;
    (function initGauge() {
        const canvas = document.getElementById('gaugeCanvas');
        if (!canvas) return;
        const ctx = canvas.getContext('2d');
        const cx = 80, cy = 85, r = 65;
        let cur = 0, tgt = 7.11;

        __gaugeDraw = function() {
            ctx.clearRect(0, 0, 160, 90);
            ctx.beginPath(); ctx.arc(cx, cy, r, Math.PI, 0);
            ctx.strokeStyle = 'rgba(255,255,255,0.06)'; ctx.lineWidth = 8; ctx.lineCap = 'round'; ctx.stroke();

            cur += (tgt - cur) * 0.05;
            const pct = Math.min(cur / 15, 1);
            const valA = Math.PI + (0 - Math.PI) * pct;

            const grd = ctx.createLinearGradient(cx - r, cy, cx + r, cy);
            grd.addColorStop(0, '#FF9933'); grd.addColorStop(1, '#FFD700');
            ctx.beginPath(); ctx.arc(cx, cy, r, Math.PI, valA);
            ctx.strokeStyle = grd; ctx.lineWidth = 8; ctx.lineCap = 'round'; ctx.stroke();

            ctx.beginPath(); ctx.arc(cx, cy, r, Math.PI, valA);
            ctx.strokeStyle = 'rgba(255,153,51,0.2)'; ctx.lineWidth = 14; ctx.lineCap = 'round'; ctx.stroke();

            for (let i = 0; i <= 10; i++) {
                const a = Math.PI + (0 - Math.PI) * (i / 10);
                ctx.beginPath();
                ctx.moveTo(cx + (r - 10) * Math.cos(a), cy + (r - 10) * Math.sin(a));
                ctx.lineTo(cx + (r + 3) * Math.cos(a), cy + (r + 3) * Math.sin(a));
                ctx.strokeStyle = 'rgba(255,255,255,0.12)'; ctx.lineWidth = 1; ctx.stroke();
            }

            const gv = document.getElementById('gaugeVal');
            if (gv) gv.textContent = cur.toFixed(2);
        };
        __gaugeDraw();
        window.__setGauge = (v) => { tgt = v; };
    })();

    /* ═══════════════════════════════════════════════════════════════
       LINE CHART — scrolling throughput
    ═══════════════════════════════════════════════════════════════ */
    var __lineDraw = null;
    (function initLineChart() {
        const canvas = document.getElementById('lineChartCanvas');
        if (!canvas) return;
        const ctx = canvas.getContext('2d');

        function resize() {
            const r = canvas.parentElement.getBoundingClientRect();
            canvas.width = r.width || 180; canvas.height = r.height || 70;
        }
        resize();
        window.addEventListener('resize', resize);

        const MAX = 40;
        let cyan = Array.from({ length: MAX }, () => Math.random() * 0.6 + 0.2);
        let orange = Array.from({ length: MAX }, () => Math.random() * 0.4 + 0.1);

        __lineDraw = function() {
            const w = canvas.width, h = canvas.height;
            ctx.clearRect(0, 0, w, h);

            cyan.shift(); cyan.push(cyan[MAX - 1] * 0.8 + Math.random() * 0.2 + 0.05);
            orange.shift(); orange.push(orange[MAX - 1] * 0.8 + Math.random() * 0.15 + 0.02);

            ctx.strokeStyle = 'rgba(255,255,255,0.03)'; ctx.lineWidth = 0.5;
            for (let y = 0; y < h; y += h / 4) { ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke(); }

            const stepX = w / (MAX - 1);
            const drawLine = (pts, col) => {
                ctx.beginPath();
                for (let i = 0; i < pts.length; i++) {
                    i === 0 ? ctx.moveTo(i * stepX, h - pts[i] * h) : ctx.lineTo(i * stepX, h - pts[i] * h);
                }
                ctx.strokeStyle = col; ctx.lineWidth = 1.5; ctx.stroke();
            };

            drawLine(orange, 'rgba(255,180,0,0.5)');
            drawLine(cyan, '#FFD700');

            const grd = ctx.createLinearGradient(0, 0, 0, h);
            grd.addColorStop(0, 'rgba(255,215,0,0.08)'); grd.addColorStop(1, 'rgba(255,215,0,0)');
            ctx.lineTo(w, h); ctx.lineTo(0, h); ctx.closePath(); ctx.fillStyle = grd; ctx.fill();
        };
        __lineDraw();
    })();

    /* ═══════════════════════════════════════════════════════════════
       STATE MANAGEMENT
    ═══════════════════════════════════════════════════════════════ */
    var ambientTimer = null;
    var __lastActivity = Date.now();
    function resetAmbientTimer() {
        __lastActivity = Date.now();
        if (document.body.classList.contains('state-ambient')) {
            setState('idle');
        }
        if (ambientTimer) clearTimeout(ambientTimer);
        ambientTimer = setTimeout(function() {
            if (document.body.className === '' || document.body.classList.contains('state-idle')) {
                setState('ambient');
            }
        }, 25000);
    }
    resetAmbientTimer();

    function setState(state) {
        document.body.className = '';
        if (state === 'ambient') document.body.classList.add('state-ambient');
        else if (state !== 'idle') document.body.classList.add('state-' + state);

        // Clear transcript when back to idle
        if (state === 'idle') {
            var cd = document.getElementById('cdText');
            if (cd) cd.textContent = '';
        }

        const statusText = document.getElementById('sphereStatusText');
        const vbText = document.getElementById('vbText');
        const vbWaves = document.getElementById('vbWaves');
        const vbMic = document.getElementById('vbMic');

        switch (state) {
            case 'listening':
                targetAudioLevel = 1.0;
                if (statusText) statusText.textContent = 'LISTENING...';
                if (vbText) vbText.textContent = 'Listening for your command...';
                if (vbWaves) vbWaves.classList.add('active');
                if (vbMic) vbMic.classList.add('active');
                break;
            case 'processing':
                targetAudioLevel = 0.5;
                if (statusText) statusText.textContent = 'PROCESSING...';
                if (vbText) vbText.textContent = 'Analyzing command...';
                if (vbWaves) vbWaves.classList.remove('active');
                if (vbMic) vbMic.classList.remove('active');
                break;
            case 'speaking':
                targetAudioLevel = 0.6;
                if (statusText) statusText.textContent = 'RESPONDING...';
                if (vbText) vbText.textContent = 'Speaking response...';
                if (vbWaves) vbWaves.classList.add('active');
                if (vbMic) vbMic.classList.remove('active');
                break;
            default:
                targetAudioLevel = 0;
                if (statusText) statusText.textContent = 'AWAITING COMMAND';
                if (vbText) vbText.textContent = 'Say "Hey PRAVAHA" to activate...';
                if (vbWaves) vbWaves.classList.remove('active');
                if (vbMic) vbMic.classList.remove('active');
                resetAmbientTimer();
        }
    }

    /* ═══════════════════════════════════════════════════════════════
       TOAST LOG
    ═══════════════════════════════════════════════════════════════ */
    function addToast(message, type) {
        const c = document.getElementById('toastContainer');
        if (!c) return;
        const t = document.createElement('div');
        t.className = 'toast ' + (type || 'info');
        t.textContent = message;
        c.appendChild(t);
        setTimeout(() => t.remove(), 4000);
    }

    /* ═══════════════════════════════════════════════════════════════
       METRICS POLLING
    ═══════════════════════════════════════════════════════════════ */
    function pollMetrics() {
        fetch('/api/v1/metrics')
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (data.status === 'success') {
                    var cpu = data.cpu, mem = data.memory, disk = data.disk;
                    var el = document.getElementById.bind(document);
                    if (el('kpiCpu'))  el('kpiCpu').textContent  = (cpu / 10).toFixed(2);
                    if (el('kpiMem'))  el('kpiMem').textContent  = ((data.memory / 100) * 16).toFixed(2);
                    if (el('kpiDisk')) el('kpiDisk').textContent  = ((disk / 10) * 5).toFixed(2);
                    if (el('kpiNet'))  el('kpiNet').textContent  = Math.round(data.net_recv_mb * 10);
                    if (el('kpiUptime')) el('kpiUptime').textContent = data.uptime;

                    var donutFill = el('donutMiniFill');
                    if (donutFill) {
                        donutFill.style.strokeDashoffset = 150.8 - (cpu / 100) * 150.8;
                    }
                    var donutLbl = el('donutMiniLabel');
                    if (donutLbl) donutLbl.textContent = cpu.toFixed(1) + '%';

                    if (window.__setGauge) window.__setGauge((cpu / 100) * 15);

                    var bars = document.querySelectorAll('.wb-bar-fill');
                    if (bars.length >= 4) {
                        bars[0].style.width = cpu + '%';
                        bars[0].nextElementSibling.textContent = cpu + '%';
                        bars[1].style.width = mem + '%';
                        bars[1].nextElementSibling.textContent = mem + '%';
                        bars[2].style.width = disk + '%';
                        bars[2].nextElementSibling.textContent = disk + '%';
                        bars[3].style.width = Math.round((cpu + mem) / 2) + '%';
                        bars[3].nextElementSibling.textContent = Math.round((cpu + mem) / 2) + '%';
                    }
                }
            })
            .catch(function() {});
        setTimeout(pollMetrics, 2500);
    }
    pollMetrics();

    /* ═══════════════════════════════════════════════════════════════
       WEBSOCKET
    ═══════════════════════════════════════════════════════════════ */
    var ws = null;
    function connectWS() {
        var protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        ws = new WebSocket(protocol + '//' + window.location.host + '/ws');
        ws.onopen = function() { addToast('Neural link established', 'success'); };
        ws.onmessage = function(e) {
            try {
                var d = JSON.parse(e.data);
                if (d.type === 'wake_word') { setState('listening'); addToast('Wake word detected', 'success'); }
                if (d.type === 'response') showResponse(d.text, d.intent);
            } catch {}
        };
        ws.onclose = function() { setTimeout(connectWS, 3000); };
        ws.onerror = function() { setState('error'); ws.close(); };
    }
    setTimeout(connectWS, 1500);

    /* ═══════════════════════════════════════════════════════════════
       VOICE RECOGNITION
    ═══════════════════════════════════════════════════════════════ */
    var recognition;
    var voiceProcessing = false;
    var SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (SR) {
        recognition = new SR();
        recognition.continuous = true;
        recognition.interimResults = true;
        recognition.lang = 'en-US';

        var wakes = ['pravaha', 'hey pravaha', 'okay pravaha'];

        recognition.onresult = function(event) {
            var finalTranscript = '';
            var interimTranscript = '';
            for (var i = event.resultIndex; i < event.results.length; i++) {
                if (event.results[i].isFinal) {
                    finalTranscript += event.results[i][0].transcript;
                } else {
                    interimTranscript += event.results[i][0].transcript;
                }
            }

            var displayText = finalTranscript || interimTranscript;
            var cdText = document.getElementById('cdText');
            if (cdText) cdText.textContent = displayText.trim();

            var lower = displayText.toLowerCase();
            var isIdle = document.body.className === '' || document.body.classList.contains('state-idle');

            // Wake word detection from ambient or idle
            var ambient = document.body.classList.contains('state-ambient');
            if ((isIdle || ambient) && !voiceProcessing && wakes.some(function(w) { return lower.indexOf(w) !== -1; })) {
                setState('listening');
                addToast(ambient ? 'Pravaha online' : 'Pravaha activated', 'success');
                // Restart recognition to clear interim buffers
                try { recognition.stop(); } catch(e) {}
                return;
            }

            // Process command on final result while in listening state
            if (document.body.classList.contains('state-listening') && finalTranscript.trim() && !voiceProcessing) {
                var cmd = finalTranscript.replace(new RegExp(wakes.join('|'), 'gi'), '').trim();
                if (cmd) {
                    voiceProcessing = true;
                    processCommand(cmd);
                }
            }
        };

        recognition.onerror = function(e) {
            if (e.error !== 'no-speech') { addToast('Voice error: ' + e.error, 'error'); setState('error'); }
            if (e.error === 'not-allowed') addToast('Microphone permission denied. Allow mic access in browser settings.', 'error');
        };

        recognition.onend = function() {
            // Auto-restart for continuous wake word detection (unless processing)
            if (!voiceProcessing && !document.body.classList.contains('state-processing')) {
                var isAmbient = document.body.classList.contains('state-ambient');
                var isIdle = document.body.className === '' || document.body.classList.contains('state-idle');
                if (!isAmbient && !isIdle) {
                    try { recognition.start(); } catch(e) {}
                } else if (isAmbient) {
                    // Stay in ambient and keep listening
                    try { recognition.start(); } catch(e) {}
                } else {
                    setState('idle');
                    try { recognition.start(); } catch(e) {}
                }
            }
        };
    }

    /* ═══════════════════════════════════════════════════════════════
       AUDIO ANALYSER
    ═══════════════════════════════════════════════════════════════ */
    var audioCtx, analyser, __audioData;
    async function initAudio() {
        if (audioCtx) return;
        try {
            var stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            audioCtx = new (window.AudioContext || window.webkitAudioContext)();
            analyser = audioCtx.createAnalyser();
            analyser.fftSize = 256;
            __audioData = new Uint8Array(analyser.frequencyBinCount);
            var src = audioCtx.createMediaStreamSource(stream);
            src.connect(analyser);
        } catch {
            addToast('Microphone access denied', 'error');
        }
    }

    function updateAudioLevel() {
        if (!analyser) return;
        analyser.getByteFrequencyData(__audioData);
        var lvl = __audioData.reduce(function(a, b) { return a + b; }, 0) / __audioData.length / 255;
        if (document.body.classList.contains('state-listening')) {
            targetAudioLevel = Math.max(targetAudioLevel, lvl * 2.5);
        }
    }

    /* ═══════════════════════════════════════════════════════════════
       SINGLE MASTER RAF LOOP — replaces 6 concurrent loops
    ═══════════════════════════════════════════════════════════════ */
    var __lastTerrainTime = 0;
    var __lastChartTime = 0;
    function __masterLoop(now) {
        requestAnimationFrame(__masterLoop);

        // Holographic sphere — every frame (60fps)
        try { updateSphere(); } catch(e) {}

        // 3D character model — every frame (60fps)
        if (window.__pravahaRenderVrm) {
            try { window.__pravahaRenderVrm(); } catch(e) {}
        }

        // Audio analyser — every frame
        updateAudioLevel();

        // Terrain chart — throttled to ~12fps (every 80ms)
        if (now - __lastTerrainTime > 80 && __terrainDraw) {
            __lastTerrainTime = now;
            try { __terrainDraw(); } catch(e) {}
        }

        // Gauge + line chart — throttled to ~10fps (every 100ms)
        if (now - __lastChartTime > 100) {
            __lastChartTime = now;
            if (__gaugeDraw) try { __gaugeDraw(); } catch(e) {}
            if (__lineDraw) try { __lineDraw(); } catch(e) {}
        }
    }
    requestAnimationFrame(__masterLoop);

    /* ═══════════════════════════════════════════════════════════════
       COMMAND PROCESSING
    ═══════════════════════════════════════════════════════════════ */
    async function processCommand(text) {
        setState('processing');
        try {
            var res = await fetch('/api/v1/command', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ command: text, timestamp: new Date().toISOString() })
            });
            var data = await res.json();
            showResponse(data.response, data.intent);
        } catch {
            showResponse('Connection to neural core failed. Retrying...', 'error');
            setTimeout(function() { voiceProcessing = false; setState('idle'); }, 2000);
        }
    }

    /* ═══════════════════════════════════════════════════════════════
       HUMAN TTS — uses Google Web Speech API with natural voice
    ═══════════════════════════════════════════════════════════════ */
    function speakHuman(text, onEnd) {
        if (!window.speechSynthesis) {
            if (onEnd) onEnd();
            return;
        }
        window.speechSynthesis.cancel();
        var utt = new SpeechSynthesisUtterance(text);

        // Pick an authoritative warning-style voice
        var voices = window.speechSynthesis.getVoices();
        var preferred = voices.filter(function(v) {
            var name = (v.name || '').toLowerCase();
            var lang = v.lang || '';
            return (lang === 'en-US' || lang === 'en-GB' || lang.startsWith('en-')) &&
                   name.indexOf('zira') === -1 &&
                   name.indexOf('david') === -1 &&
                   name.indexOf('espeak') === -1;
        });

        var pick = null;
        if (preferred.length > 0) {
            var nice = preferred.find(function(v) {
                var n = v.name.toLowerCase();
                return n.indexOf('daniel') !== -1 ||
                       n.indexOf('tom') !== -1 ||
                       n.indexOf('alex') !== -1 ||
                       n.indexOf('fred') !== -1 ||
                       n.indexOf('google') !== -1 ||
                       n.indexOf('microsoft') !== -1 ||
                       n.indexOf('samantha') !== -1 ||
                       n.indexOf('karen') !== -1;
            });
            pick = nice || preferred[0];
        }

        if (pick) {
            utt.voice = pick;
        }

        utt.rate = 0.75;
        utt.pitch = 0.62;
        utt.volume = 1.0;

        utt.onend = function() {
            if (onEnd) onEnd();
        };
        utt.onerror = function() {
            if (onEnd) onEnd();
        };

        // Warning-style cue: short tone before speech
        try {
            var AC = window.AudioContext || window.webkitAudioContext;
            if (AC) {
                var ctx = new AC();
                var osc = ctx.createOscillator();
                var gain = ctx.createGain();
                osc.type = 'sawtooth';
                osc.frequency.value = 980;
                gain.gain.setValueAtTime(0.0001, ctx.currentTime);
                gain.gain.exponentialRampToValueAtTime(0.18, ctx.currentTime + 0.03);
                gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + 0.14);
                osc.connect(gain);
                gain.connect(ctx.destination);
                osc.start(ctx.currentTime);
                osc.stop(ctx.currentTime + 0.15);
            }
        } catch (e) { /* ignore audio cue */ }

        window.speechSynthesis.speak(utt);
    }

    // Ensure voices are loaded (they load async in some browsers)
    if (window.speechSynthesis) {
        window.speechSynthesis.onvoiceschanged = function() {
            window.speechSynthesis.getVoices();
        };
    }

    /* ─── MOUTH MOVEMENT DRIVER ─── */
    var __speechMouthTimer = null;
    var __speechMouthFallback = null;
    function startSpeechMouthDriver(){
        if (__speechMouthTimer) return;
        __speechMouthFallback = {
            phase: Math.random() * 6.28,
            speed: 0.08 + Math.random() * 0.18,
            amp: 0.18 + Math.random() * 0.35
        };
        __speechMouthTimer = setInterval(function(){
            if (!__speechMouthFallback) return;
            __speechMouthFallback.phase += __speechMouthFallback.speed;
            var fallbackLevel = (Math.sin(__speechMouthFallback.phase) * 0.5 + 0.5) * __speechMouthFallback.amp;
            var current = typeof window.__pravahaLevel === 'number' ? window.__pravahaLevel : 0;
            window.__pravahaLevel = Math.max(current, fallbackLevel);
        }, 50);
    }
    function stopSpeechMouthDriver(){
        if (__speechMouthTimer) { clearInterval(__speechMouthTimer); __speechMouthTimer = null; }
        __speechMouthFallback = null;
        if (typeof window.__pravahaLevel === 'number') window.__pravahaLevel = Math.max(0, (window.__pravahaLevel || 0) - 0.05);
    }

    function showResponse(text, intent) {
        setState('speaking');
        startSpeechMouthDriver();
        var roContent = document.getElementById('roContent');
        var roIntent = document.getElementById('roIntent');
        var overlay = document.getElementById('responseOverlay');
        if (roContent) roContent.textContent = text;
        if (roIntent) roIntent.textContent = intent || 'chat';
        if (overlay) overlay.classList.add('visible');
        addToast(text.substring(0, 60) + (text.length > 60 ? '...' : ''), 'success');

        speakHuman(text, function() {
            voiceProcessing = false;
            stopSpeechMouthDriver();
            setTimeout(function() {
                setState('idle');
                if (overlay) overlay.classList.remove('visible');
                if (recognition) { try { recognition.start(); } catch(e) {} }
            }, 1500);
        });

        // Fallback if onend never fires
        setTimeout(function() {
            voiceProcessing = false;
            stopSpeechMouthDriver();
            setState('idle');
            if (overlay) overlay.classList.remove('visible');
            if (recognition) { try { recognition.start(); } catch(e) {} }
        }, 8000);
    }

    /* ═══════════════════════════════════════════════════════════════
       EVENT LISTENERS
    ═══════════════════════════════════════════════════════════════ */
    document.getElementById('vbMic')?.addEventListener('click', activateVoice);
    document.getElementById('btnActivate')?.addEventListener('click', activateVoice);

    async function activateVoice() {
        if (document.body.classList.contains('state-ambient')) {
            setState('idle');
            return;
        }
        if (recognition) {
            try {
                await initAudio();
                voiceProcessing = false;
                recognition.start();
                setState('listening');
                addToast('Voice activated', 'success');
            } catch {
                setState('listening');
                setTimeout(function() { processCommand('show system status'); }, 1500);
            }
        } else {
            setState('listening');
            setTimeout(function() { processCommand('show system status'); }, 1500);
        }
    }

    document.addEventListener('keydown', function(e) {
        if (document.body.classList.contains('state-ambient') && (e.code === 'Escape' || e.code === 'Space')) {
            e.preventDefault();
            setState('idle');
            return;
        }
        if (e.code === 'Space' && !e.target.matches('input, textarea')) {
            e.preventDefault();
            activateVoice();
        }
        if (e.code === 'Escape') {
            var overlay = document.getElementById('responseOverlay');
            if (overlay) overlay.classList.remove('visible');
            voiceProcessing = false;
            setState('idle');
        }
    });

    document.body.addEventListener('click', function(e) {
        if (document.body.classList.contains('state-ambient') && !e.target.closest('input, textarea')) {
            setState('idle');
        }
    });

    var respOverlay = document.getElementById('responseOverlay');
    if (respOverlay) {
        respOverlay.addEventListener('click', function(e) {
            if (e.target === e.currentTarget) {
                e.currentTarget.classList.remove('visible');
                setState('idle');
            }
        });
    }

    document.querySelectorAll('.list-item').forEach(function(item) {
        item.addEventListener('click', function() {
            document.querySelectorAll('.list-item').forEach(function(i) { i.classList.remove('active'); });
            item.classList.add('active');
        });
    });

    /* ─── Tabs ─── */
    document.querySelectorAll('.nav-tab').forEach(function(tab) {
        tab.addEventListener('click', function() {
            var target = this.getAttribute('data-tab');
            document.querySelectorAll('.nav-tab').forEach(function(t) { t.classList.remove('active'); });
            document.querySelectorAll('.tab-panel').forEach(function(p) { p.classList.remove('active'); });
            this.classList.add('active');
            var panel = document.querySelector('.tab-panel[data-panel="' + target + '"]');
            if (panel) panel.classList.add('active');
        });
    });

    /* ─── Theme Switching ─── */
    (function initThemes() {
        var saved = localStorage.getItem('pravaha-theme') || '';
        if (saved) document.documentElement.setAttribute('data-theme', saved);

        document.querySelectorAll('.settings-swatch').forEach(function(btn) {
            if (saved === (btn.getAttribute('data-theme') || '')) {
                document.querySelectorAll('.settings-swatch').forEach(function(b) { b.classList.remove('active'); });
                btn.classList.add('active');
            }
            btn.addEventListener('click', function() {
                var theme = this.getAttribute('data-theme') || '';
                document.documentElement.setAttribute('data-theme', theme);
                localStorage.setItem('pravaha-theme', theme);
                document.querySelectorAll('.settings-swatch').forEach(function(b) { b.classList.remove('active'); });
                btn.classList.add('active');
            });
        });
    })();

    /* ─── Terminal ─── */
    var terminalOutput = document.getElementById('terminalOutput');
    var terminalInput = document.getElementById('terminalInput');
    var terminalHistory = [];
    var terminalHistoryIndex = -1;
    var terminalBadge = document.getElementById('terminalBadge');

    function terminalBoot() {
        if (!terminalOutput) return;
        var lines = [
            { text: 'PRAVAHA TERMINAL v1.0', cls: 'info' },
            { text: 'Type "help" for available commands.', cls: 'system' },
            { text: '', cls: '' },
            { text: 'System ready.', cls: 'success' }
        ];
        lines.forEach(function(l) {
            terminalPrint(l.text, l.cls);
        });
    }

    function terminalPrint(text, cls) {
        if (!terminalOutput) return;
        var line = document.createElement('p');
        line.className = 'terminal-line ' + (cls || '');
        line.textContent = text;
        terminalOutput.appendChild(line);
        terminalOutput.scrollTop = terminalOutput.scrollHeight;
    }

    var terminalCwd = '~';
    var terminalJobs = [];
    var terminalJobId = 1;

    function resolvePath(input) {
        if (!input || input === '~') return requirePath ? requirePath : '';
        if (input.startsWith('~/')) return (requirePath ? requirePath : '') + input.slice(2);
        if (input.startsWith('./')) return input;
        return input;
    }

    function terminalProcess(cmd) {
        var trimmed = (cmd || '').trim();
        if (!trimmed) return;
        terminalHistory.unshift(trimmed);
        terminalHistoryIndex = -1;
        terminalPrint('❯ ' + trimmed, 'info');

        var lower = trimmed.toLowerCase();
        var parts = trimmed.split(' ');
        var base = parts[0].toLowerCase();
        var arg = parts.slice(1).join(' ');

        if (lower === 'help') {
            terminalPrint('Available commands:', 'system');
            terminalPrint('  help        Show this help', '');
            terminalPrint('  clear       Clear terminal output', '');
            terminalPrint('  history     Show command history', '');
            terminalPrint('  status      Show system status', '');
            terminalPrint('  date        Show current date/time', '');
            terminalPrint('  neural      Check neural core link', '');
            terminalPrint('  ping        Connectivity check', '');
            terminalPrint('  ls [path]   List directory', '');
            terminalPrint('  cd <path>   Change directory', '');
            terminalPrint('  pwd         Print working directory', '');
            terminalPrint('  cat <file>  Read file contents', '');
            terminalPrint('  jobs        List background jobs', '');
            terminalPrint('  bg <cmd>    Run command in background', '');
            terminalPrint('  <command>   Execute via backend system controller', '');
            return;
        }
        if (lower === 'clear') {
            terminalOutput.innerHTML = '';
            return;
        }
        if (lower === 'history') {
            terminalHistory.slice(0, 20).forEach(function(h) {
                terminalPrint('  ' + h, 'system');
            });
            return;
        }
        if (base === 'ls') {
            var lsPath = resolvePath(arg || '~');
            if (terminalBadge) terminalBadge.textContent = 'REMOTE';
            terminalPrint('Executing: ls ' + lsPath, 'warn');
            fetch('/api/v1/system/execute', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ command: 'ls -la ' + lsPath, timestamp: new Date().toISOString() })
            }).then(function(r) { return r.json(); }).then(function(data) {
                if (terminalBadge) terminalBadge.textContent = 'LOCAL';
                terminalPrint(data && data.status === 'success' ? (data.response || '(empty)') : 'Command failed', data && data.status === 'success' ? 'success' : 'error');
            }).catch(function(e) {
                if (terminalBadge) terminalBadge.textContent = 'LOCAL';
                terminalPrint('Execution error: ' + e.message, 'error');
            });
            return;
        }
        if (base === 'cd') {
            var cdTarget = resolvePath(arg || '~');
            terminalCwd = cdTarget;
            terminalPrint('Changed directory to: ' + cdTarget, 'success');
            return;
        }
        if (base === 'pwd') {
            terminalPrint(terminalCwd, 'success');
            return;
        }
        if (base === 'cat') {
            if (!arg) {
                terminalPrint('Usage: cat <file>', 'error');
                return;
            }
            var catPath = resolvePath(arg);
            if (terminalBadge) terminalBadge.textContent = 'REMOTE';
            terminalPrint('Executing: cat ' + catPath, 'warn');
            fetch('/api/v1/system/execute', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ command: 'cat ' + catPath, timestamp: new Date().toISOString() })
            }).then(function(r) { return r.json(); }).then(function(data) {
                if (terminalBadge) terminalBadge.textContent = 'LOCAL';
                terminalPrint(data && data.status === 'success' ? (data.response || '(empty)') : 'Command failed', data && data.status === 'success' ? 'success' : 'error');
            }).catch(function(e) {
                if (terminalBadge) terminalBadge.textContent = 'LOCAL';
                terminalPrint('Execution error: ' + e.message, 'error');
            });
            return;
        }
        if (lower === 'jobs') {
            if (terminalJobs.length === 0) {
                terminalPrint('No background jobs.', 'system');
            } else {
                terminalJobs.forEach(function(job) {
                    terminalPrint('[' + job.id + '] ' + job.command + ' (' + job.status + ')', 'system');
                });
            }
            return;
        }
        if (base === 'bg') {
            var bgCmd = arg.trim();
            if (!bgCmd) {
                terminalPrint('Usage: bg <command>', 'error');
                return;
            }
            if (terminalBadge) terminalBadge.textContent = 'REMOTE';
            terminalPrint('Starting background: ' + bgCmd, 'warn');
            fetch('/api/v1/system/execute', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ command: 'bg ' + bgCmd, timestamp: new Date().toISOString() })
            }).then(function(r) { return r.json(); }).then(function(data) {
                if (terminalBadge) terminalBadge.textContent = 'LOCAL';
                terminalPrint(data && data.status === 'success' ? (data.response || '(no output)') : 'Command failed', data && data.status === 'success' ? 'success' : 'error');
            }).catch(function(e) {
                if (terminalBadge) terminalBadge.textContent = 'LOCAL';
                terminalPrint('Execution error: ' + e.message, 'error');
            });
            return;
        }

        if (lower === 'status') {
            terminalPrint('CPU: ' + (document.getElementById('perfCpu')?.textContent || '--'), '');
            terminalPrint('RAM: ' + (document.getElementById('perfRam')?.textContent || '--'), '');
            terminalPrint('Temp: ' + (document.getElementById('perfTemp')?.textContent || '--'), '');
            terminalPrint('Disk: ' + (document.getElementById('perfDisk')?.textContent || '--'), '');
            terminalPrint('Net: ' + (document.getElementById('perfNet')?.textContent || '--'), '');
            return;
        }
        if (lower === 'date' || lower === 'time') {
            terminalPrint(new Date().toString(), 'success');
            return;
        }
        if (lower === 'neural' || lower === 'core') {
            var wsState = typeof ws !== 'undefined' && ws ? (ws.readyState === 1 ? 'LINKED' : 'OFFLINE') : 'UNKNOWN';
            terminalPrint('Neural core: ' + wsState, wsState === 'LINKED' ? 'success' : 'warn');
            return;
        }
        if (lower === 'ping') {
            terminalPrint('Pinging local core...', 'system');
            fetch('/health').then(function(r) {
                return r.json().then(function(d) {
                    terminalPrint('Core response: ' + JSON.stringify(d), 'success');
                });
            }).catch(function() {
                terminalPrint('Core unreachable.', 'error');
            });
            return;
        }

        // Delegate unknown commands to backend
        if (terminalBadge) terminalBadge.textContent = 'REMOTE';
        terminalPrint('Executing: ' + trimmed, 'warn');
        fetch('/api/v1/system/execute', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ command: trimmed, timestamp: new Date().toISOString() })
        }).then(function(r) { return r.json(); }).then(function(data) {
            if (terminalBadge) terminalBadge.textContent = 'LOCAL';
            if (data && data.status === 'success') {
                terminalPrint(data.response || '(no output)', 'success');
            } else {
                terminalPrint(data ? (data.response || 'Command failed') : 'Invalid response', 'error');
            }
        }).catch(function(e) {
            if (terminalBadge) terminalBadge.textContent = 'LOCAL';
            terminalPrint('Execution error: ' + e.message, 'error');
        });
    }

    if (terminalInput) {
        terminalInput.addEventListener('keydown', function(e) {
            if (e.key === 'Enter') {
                var val = terminalInput.value;
                terminalInput.value = '';
                terminalProcess(val);
            } else if (e.key === 'ArrowUp') {
                e.preventDefault();
                if (terminalHistory.length > 0) {
                    terminalHistoryIndex = Math.min(terminalHistoryIndex + 1, terminalHistory.length - 1);
                    terminalInput.value = terminalHistory[terminalHistoryIndex];
                }
            } else if (e.key === 'ArrowDown') {
                e.preventDefault();
                if (terminalHistoryIndex > 0) {
                    terminalHistoryIndex -= 1;
                    terminalInput.value = terminalHistory[terminalHistoryIndex];
                } else {
                    terminalHistoryIndex = -1;
                    terminalInput.value = '';
                }
            }
        });
    }

    document.querySelectorAll('.qc').forEach(function(btn) {
        btn.addEventListener('click', function() {
            var cmd = this.getAttribute('data-cmd');
            if (cmd && terminalInput) {
                terminalInput.value = cmd;
                terminalProcess(cmd);
                terminalInput.value = '';
            }
        });
    });

    setTimeout(terminalBoot, 1200);

    setTimeout(function() { addToast('TERMINAL MODULE LOADED', 'success'); }, 1500);
    setTimeout(function() {
        if (recognition && !voiceProcessing) {
            initAudio().then(function() {
                try { recognition.start(); } catch(e) {}
            }).catch(function() {
                // Mic not available yet; user can click the mic button
            });
        }
    }, 2000);

    setState('idle');
    addToast('PRAVAHA CORE INITIALIZED', 'success');

    /* ─── Splash dismiss ─── */
    (function checkSplash(){
        var splash = document.getElementById('splash');
        if (!splash || splash.classList.contains('hidden')) return;
        var canvas = document.querySelector('#vrmContainer canvas');
        if (canvas) {
            setTimeout(function(){ splash.classList.add('hidden'); }, 400);
        } else {
            setTimeout(checkSplash, 300);
        }
    })();
    setTimeout(function(){
        var splash = document.getElementById('splash');
        if (splash && !splash.classList.contains('hidden')) splash.classList.add('hidden');
    }, 10000);

})();
