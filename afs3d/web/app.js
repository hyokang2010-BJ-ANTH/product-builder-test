/* AFS 3D 스튜디오 — 업로드 → 진행 상황 → 3D 결과 */
"use strict";

const $ = (id) => document.getElementById(id);
const ALLOWED = /\.(jpe?g|png|tiff?|bmp|csv|zip)$/i;
const IMAGE = /\.(jpe?g|png|tiff?|bmp)$/i;
const STEPS = ["전처리", "특징점 추출", "사진 간 매칭", "카메라 위치 추정", "모델 정리", "조밀 재구성 (깊이 추정)", "메쉬 생성", "탈모 면적 분석", "완료"];
const STATUS = { uploading: "업로드 중", queued: "대기 중", running: "처리 중", done: "완료", failed: "실패", cancelled: "취소됨" };

let picked = [];          // 선택된 File 목록
let currentJob = null;    // 보고 있는 작업 id
let pollTimer = null;
let viewer = null;

// ---------------- API ----------------
async function api(path, opts = {}) {
  const res = await fetch(path, { credentials: "same-origin", ...opts });
  const ct = res.headers.get("content-type") || "";
  const body = ct.includes("json") ? await res.json() : await res.text();
  if (!res.ok) throw new Error((body && body.error) || `요청 실패 (${res.status})`);
  return body;
}

// ---------------- 목록 ----------------
function fmtDate(t) {
  const d = new Date(t * 1000);
  return d.toLocaleString("ko-KR", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

async function refreshList() {
  let jobs = [];
  try { jobs = await api("/api/jobs"); } catch (e) { return; }
  const ul = $("jobList");
  ul.innerHTML = "";
  if (!jobs.length) { ul.innerHTML = '<li class="empty">아직 작업이 없습니다.</li>'; return; }
  for (const j of jobs) {
    const li = document.createElement("li");
    const b = document.createElement("button");
    b.setAttribute("aria-current", String(j.id === currentJob));
    const name = j.options.label || j.id;
    b.innerHTML = `<span class="jl-top"><span class="jl-name"></span><span class="pill ${j.status}">${STATUS[j.status] || j.status}</span></span>
      <span class="jl-sub">${fmtDate(j.created)} · 사진 ${j.n_images}장${j.status === "running" ? " · " + j.progress + "%" : ""}</span>`;
    b.querySelector(".jl-name").textContent = name;
    b.onclick = () => { location.hash = "#/job/" + j.id; };
    li.appendChild(b);
    ul.appendChild(li);
  }
}

// ---------------- 파일 고르기 ----------------
async function entriesToFiles(entry, out) {
  if (entry.isFile) {
    await new Promise((res) => entry.file((f) => { out.push(f); res(); }, res));
  } else if (entry.isDirectory) {
    const reader = entry.createReader();
    let batch;
    do {
      batch = await new Promise((res) => reader.readEntries(res, () => res([])));
      for (const e of batch) await entriesToFiles(e, out);
    } while (batch.length);
  }
}

function addFiles(files) {
  const seen = new Set(picked.map((f) => f.name + f.size));
  for (const f of files) {
    if (!ALLOWED.test(f.name) || f.name.startsWith(".")) continue;
    if (seen.has(f.name + f.size)) continue;
    seen.add(f.name + f.size);
    picked.push(f);
  }
  picked.sort((a, b) => a.name.localeCompare(b.name, undefined, { numeric: true }));
  renderPicked();
}

function renderPicked() {
  const imgs = picked.filter((f) => IMAGE.test(f.name));
  const manifest = picked.some((f) => /\.csv$/i.test(f.name));
  const zips = picked.filter((f) => /\.zip$/i.test(f.name));
  const size = picked.reduce((s, f) => s + f.size, 0);
  $("picked").hidden = picked.length === 0;
  $("pickedCount").textContent = `사진 ${imgs.length}장` + (zips.length ? ` + ZIP ${zips.length}개` : "");
  $("pickedMeta").textContent = `${(size / 1048576).toFixed(0)} MB` + (manifest ? " · 촬영 각도 파일(manifest.csv) 포함" : "");
  const thumbs = $("thumbs");
  thumbs.querySelectorAll("img").forEach((i) => URL.revokeObjectURL(i.src));
  thumbs.innerHTML = "";
  const MAX = 40;
  imgs.slice(0, MAX).forEach((f) => {
    const img = document.createElement("img");
    img.loading = "lazy"; img.alt = f.name; img.title = f.name;
    if (!/\.tiff?$/i.test(f.name)) img.src = URL.createObjectURL(f);
    thumbs.appendChild(img);
  });
  if (imgs.length > MAX) {
    const m = document.createElement("div"); m.className = "more"; m.textContent = `+${imgs.length - MAX}`;
    thumbs.appendChild(m);
  }
  const enough = imgs.length >= 3 || zips.length > 0;
  $("submitBtn").disabled = !enough;
  $("uploadStatus").textContent = !picked.length ? "" :
    (!enough ? "사진이 3장 이상 필요합니다." : imgs.length && imgs.length < 40 ? "사진이 적으면 일부 각도가 비어 모델이 불완전할 수 있습니다 (권장 60장 이상)." : "");
}

function setupDrop() {
  const drop = $("drop");
  ["dragenter", "dragover"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); }));
  ["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, () => drop.classList.remove("over")));
  drop.addEventListener("drop", async (e) => {
    e.preventDefault();
    const items = [...(e.dataTransfer.items || [])];
    const out = [];
    if (items.length && items[0].webkitGetAsEntry) {
      const entries = items.map((i) => i.webkitGetAsEntry()).filter(Boolean);
      for (const en of entries) await entriesToFiles(en, out);
    } else {
      out.push(...e.dataTransfer.files);
    }
    addFiles(out);
  });
  drop.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); $("fileInput").click(); } });
  $("fileInput").onchange = (e) => { addFiles([...e.target.files]); e.target.value = ""; };
  $("dirInput").onchange = (e) => { addFiles([...e.target.files]); e.target.value = ""; };
  $("clearBtn").onclick = () => { picked = []; renderPicked(); };
  // 페이지 다른 곳에 떨어뜨려도 브라우저가 파일을 열어버리지 않게
  window.addEventListener("dragover", (e) => e.preventDefault());
  window.addEventListener("drop", (e) => e.preventDefault());
}

// ---------------- 업로드 ----------------
function putFile(jobId, file, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("PUT", `/api/jobs/${jobId}/files/${encodeURIComponent(file.name)}`);
    xhr.upload.onprogress = (e) => onProgress(e.loaded);
    xhr.onload = () => {
      let body = {};
      try { body = JSON.parse(xhr.responseText); } catch (_) {}
      xhr.status < 300 ? resolve(body) : reject(new Error(body.error || `업로드 실패 (${xhr.status})`));
    };
    xhr.onerror = () => reject(new Error("네트워크 오류로 업로드하지 못했습니다"));
    xhr.send(file);
  });
}

async function submitJob(e) {
  e.preventDefault();
  const btn = $("submitBtn");
  btn.disabled = true;
  const status = $("uploadStatus");
  const bar = $("uploadBar");
  bar.hidden = false;
  const opts = {
    label: $("label").value.trim(),
    rig_radius_mm: $("radius").value || null,
    mode: document.querySelector('input[name="mode"]:checked').value,
    mask: $("mask").checked,
    dense: $("dense").checked,
    drop_flagged: $("dropFlagged").checked,
    gray_backdrop: $("mask").checked && $("grayBackdrop").checked,
  };
  let job;
  try {
    job = await api("/api/jobs", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(opts) });
    const total = picked.reduce((s, f) => s + f.size, 0) || 1;
    const loaded = new Array(picked.length).fill(0);
    let next = 0, done = 0;
    const update = () => {
      const pct = Math.round(loaded.reduce((a, b) => a + b, 0) / total * 100);
      bar.firstElementChild.style.width = pct + "%";
      status.textContent = `업로드 중 ${done}/${picked.length} (${pct}%)`;
    };
    const worker = async () => {
      while (next < picked.length) {
        const i = next++;
        await putFile(job.id, picked[i], (b) => { loaded[i] = b; update(); });
        loaded[i] = picked[i].size; done++; update();
      }
    };
    await Promise.all([worker(), worker(), worker()]);
    status.textContent = "업로드 완료 · 처리를 시작합니다";
    await api(`/api/jobs/${job.id}/start`, { method: "POST" });
    picked = []; renderPicked(); $("optForm").reset(); bar.hidden = true; bar.firstElementChild.style.width = "0";
    location.hash = "#/job/" + job.id;
  } catch (err) {
    status.textContent = err.message + (job ? " — 목록에서 해당 작업을 삭제한 뒤 다시 시도하세요." : "");
    btn.disabled = false;
  }
  refreshList();
}

// ---------------- 작업 상세 ----------------
function showView(name) {
  $("newView").hidden = name !== "new";
  $("jobView").hidden = name !== "job";
}

// 서버가 보고하는 세부 단계 → 화면의 단계 이름
const STEP_OF = { "시작": "전처리", "전처리 중 (색·노출 보정, 배경 제거)": "전처리", "전처리 완료": "특징점 추출", "3D 점 삼각측량": "카메라 위치 추정", "조밀 재구성 준비": "조밀 재구성 (깊이 추정)", "점군 융합": "조밀 재구성 (깊이 추정)" };

function renderSteps(job) {
  const ol = $("steps");
  const steps = STEPS.filter((s) => job.options.dense || !["조밀 재구성 (깊이 추정)", "메쉬 생성", "탈모 면적 분석"].includes(s));
  const idx = job.status === "done" ? steps.length : steps.indexOf(STEP_OF[job.stage] || job.stage);
  ol.innerHTML = "";
  steps.forEach((s, i) => {
    const li = document.createElement("li");
    li.textContent = s;
    if (i < idx) li.className = "done";
    else if (i === idx && job.status === "running") li.className = "now";
    ol.appendChild(li);
  });
}

async function loadJob(id) {
  clearTimeout(pollTimer);
  let job;
  try { job = await api(`/api/jobs/${id}`); } catch (e) { location.hash = "#/new"; return; }
  if (currentJob !== id) { currentJob = id; if (viewer) { viewer.dispose(); viewer = null; } $("resultBox").hidden = true; }
  showView("job");
  $("jobId").textContent = job.id;
  $("jobTitle").textContent = job.options.label || "이름 없는 케이스";
  const o = job.options;
  $("jobMeta").textContent = [
    fmtDate(job.created), `사진 ${job.n_images}장`, job.has_manifest ? "각도 파일 있음" : null,
    o.mode === "rig" ? "장비 각도값 사용" : "사진으로 위치 추정", o.rig_radius_mm ? `반경 ${o.rig_radius_mm} mm` : null,
    o.dense ? "메쉬+분석" : "점군까지",
  ].filter(Boolean).join(" · ");
  const pill = $("jobPill"); pill.className = "pill " + job.status; pill.textContent = STATUS[job.status] || job.status;
  const active = job.status === "running" || job.status === "queued";
  $("cancelBtn").hidden = !active;
  $("retryBtn").hidden = !["failed", "cancelled", "done"].includes(job.status);
  $("retryBtn").textContent = job.status === "done" ? "다시 처리" : "다시 시작";

  $("progressBox").hidden = job.status === "done";
  $("stageName").textContent = job.status === "queued" ? "앞 작업이 끝나기를 기다리는 중" : job.stage;
  $("stagePct").textContent = job.progress + "%";
  $("stageBar").style.width = job.progress + "%";
  renderSteps(job);

  $("errorBox").hidden = !job.error;
  $("errorBox").textContent = job.error ? "처리하지 못했습니다: " + job.error + adviceFor(job) : "";
  const warns = [];
  const s = job.summary || {};
  if (s.dense_skipped) warns.push("이 PC 의 COLMAP 은 GPU(CUDA)를 쓸 수 없어 메쉬와 탈모 면적 분석을 건너뛰었습니다. 3D 점군과 카메라 위치까지만 표시합니다.");
  if (s.n_registered && s.n_input && s.n_registered / s.n_input < 0.9) warns.push(`사진 ${s.n_input}장 중 ${s.n_registered}장만 3D 에 쓰였습니다. 흔들림·반사광·배경을 확인하세요.`);
  if (job.status === "done" && !s.scale_mm_per_unit) warns.push("촬영 반경을 입력하지 않아 실제 크기(mm) 없이 상대 크기로 표시됩니다.");
  (s.report?.notes || []).forEach((n) => warns.push(n));
  $("warnBox").hidden = !warns.length;
  $("warnBox").innerHTML = warns.map((w) => `<div>${escapeHtml(w)}</div>`).join("");

  $("logBox").textContent = (job.log || []).join("\n");

  if (job.status === "done" && $("resultBox").hidden) renderResult(job);
  if (active) pollTimer = setTimeout(() => loadJob(id), 2000);
  refreshList();
}

function adviceFor(job) {
  const log = (job.log || []).join("\n");
  if (/COLMAP 실행 파일을 찾을 수 없습니다/.test(log)) return " — 이 PC 에 COLMAP 을 설치해야 합니다 (README 참고).";
  if (/모델을 만들지 못했습니다/.test(log)) return " — 사진 간 겹침이 부족하거나 질감이 약합니다. 촬영 조건을 확인하세요.";
  if (/focal_px/.test(log)) return " — '장비 각도값 사용' 모드는 manifest.csv 에 focal_px 가 필요합니다. '사진으로 추정' 으로 다시 시도하세요.";
  return "";
}

function escapeHtml(s) { return String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }

function fmt(n, d = 1) { return Number(n).toLocaleString("ko-KR", { minimumFractionDigits: d, maximumFractionDigits: d }); }

function renderResult(job) {
  $("resultBox").hidden = false;
  const s = job.summary || {};
  const r = s.report;
  const facts = [];
  if (s.n_registered != null) facts.push(["3D 에 쓰인 사진", `${s.n_registered} / ${s.n_input}`]);
  facts.push(["크기 기준", s.scale_mm_per_unit ? "실제 mm" : "상대 크기"]);
  if (r) {
    const u = r.units === "cm2" ? " cm²" : "";
    facts.push(["분석 영역", fmt(r.roi_area) + u]);
    facts.push(["노출 두피", fmt(r.exposed_area) + u, true]);
    facts.push(["노출 비율", fmt(r.exposed_ratio * 100) + "%", true]);
    for (const [k, v] of Object.entries(r.graft_estimates || {})) facts.push([`${k.split("_")[0]} FU/cm² 가정`, v.toLocaleString("ko-KR") + " FU"]);
  }
  $("facts").innerHTML = facts.map(([k, v, big]) => `<dt>${k}</dt><dd${big ? ' class="big"' : ""}>${v}</dd>`).join("");

  const base = `/api/jobs/${job.id}/results/`;
  const labels = { "coverage.ply": "분석 메쉬 (PLY)", "mesh.ply": "원본 메쉬 (PLY)", "sparse.ply": "3D 점군 (PLY)", "top_view.png": "정수리 지도 (PNG)", "report.json": "분석 수치 (JSON)", "reconstruction.json": "재구성 정보 (JSON)", "quality.csv": "사진 품질 (CSV)" };
  $("downloads").innerHTML = Object.keys(job.results || {}).map((k) => `<a class="btn small" href="${base}${k}" download>${labels[k] || k}</a>`).join("");

  $("topFig").hidden = !job.results["top_view.png"];
  if (job.results["top_view.png"]) $("topImg").src = base + "top_view.png";

  const views = [];
  if (job.results["coverage.ply"]) views.push(["coverage.ply", "탈모 분석"]);
  if (job.results["mesh.ply"]) views.push(["mesh.ply", "원본 메쉬"]);
  if (job.results["sparse.ply"]) views.push(["sparse.ply", "점군 + 카메라"]);
  const seg = $("viewSeg");
  seg.innerHTML = "";
  if (!views.length) { seg.hidden = true; return; }
  seg.hidden = false;
  viewer = viewer || createViewer($("stage"));
  views.forEach(([file, label], i) => {
    const b = document.createElement("button");
    b.textContent = label;
    b.onclick = () => {
      seg.querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
      viewer.show(base + file, file, s);
      setLegend(file);
    };
    seg.appendChild(b);
    if (i === 0) b.click();
  });
}

function setLegend(file) {
  $("legend").innerHTML = file === "coverage.ply"
    ? '<span><i class="sw" style="background:var(--exposed)"></i>노출 두피</span><span><i class="sw" style="background:var(--hair)"></i>모발</span>'
    : file === "sparse.ply"
      ? '<span><i class="sw" style="background:var(--accent)"></i>추정된 카메라 위치</span><span><i class="sw" style="background:#c9a58e"></i>3D 점 (사진 색)</span>'
      : "";
}

// ---------------- 3D 뷰어 ----------------
function createViewer(stage) {
  if (!window.THREE) {
    stage.insertAdjacentHTML("beforeend", '<p class="muted small" style="padding:60px 16px">3D 라이브러리를 불러오지 못했습니다.</p>');
    return { show() {}, dispose() {} };
  }
  let renderer;
  try { renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true }); }
  catch (e) {
    stage.insertAdjacentHTML("beforeend", '<p class="muted small" style="padding:60px 16px">이 브라우저에서 WebGL 을 쓸 수 없어 3D 를 표시하지 못했습니다. 아래 파일 받기로 PLY 를 내려받아 다른 프로그램에서 여세요.</p>');
    return { show() {}, dispose() {} };
  }
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  stage.appendChild(renderer.domElement);
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(38, 1, 0.01, 1e6);
  const controls = new THREE.OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  scene.add(new THREE.HemisphereLight(0xffffff, 0x556066, 1.0));
  const key = new THREE.DirectionalLight(0xffffff, 0.6); scene.add(key);
  const accent = new THREE.Color(getComputedStyle(document.documentElement).getPropertyValue("--accent").trim());
  const loader = new THREE.PLYLoader();
  const cache = {};
  let current = null;

  function orient(summary) {
    // 재구성 좌표의 '위쪽'을 화면의 +Y 로, 크기를 mm 로
    const g = new THREE.Group();
    const up = summary.up ? new THREE.Vector3(...summary.up).normalize() : new THREE.Vector3(0, 0, 1);
    g.quaternion.setFromUnitVectors(up, new THREE.Vector3(0, 1, 0));
    const s = summary.scale_mm_per_unit || 1;
    g.scale.setScalar(s);
    return g;
  }

  function build(geom, file, summary) {
    const root = orient(summary);
    if (geom.index) {
      geom.computeVertexNormals();
      const hasColor = !!geom.getAttribute("color");
      root.add(new THREE.Mesh(geom, new THREE.MeshStandardMaterial({ vertexColors: hasColor, color: hasColor ? 0xffffff : 0xc9a58e, roughness: 0.9, side: THREE.DoubleSide })));
    } else {
      // 점 크기는 물체 배율과 무관한 월드 단위라, 장면 크기에 비례해 정한다
      geom.computeBoundingSphere();
      const sc = summary.scale_mm_per_unit || 1;
      const cams = summary.camera_centers || [];
      let r = geom.boundingSphere.radius * 0.5;
      const c = new THREE.Vector3();
      if (cams.length) {
        // 머리 중심 = 카메라들이 놓인 구의 중심 (평균 위치는 위쪽 링 쪽으로 치우친다)
        if (summary.rig_center) c.set(...summary.rig_center);
        else { cams.forEach((p) => c.add(new THREE.Vector3(...p))); c.divideScalar(cams.length); }
        r = cams.reduce((a, p) => a + new THREE.Vector3(...p).distanceTo(c), 0) / cams.length;
      }
      root.add(new THREE.Points(geom, new THREE.PointsMaterial({ size: r * sc * 0.009, vertexColors: !!geom.getAttribute("color") })));
      if (cams.length) {
        const coneGeo = new THREE.ConeGeometry(r * 0.02, r * 0.045, 4); coneGeo.rotateX(Math.PI / 2);
        const mat = new THREE.MeshBasicMaterial({ color: accent });
        const lines = [];
        cams.forEach((p) => {
          const m = new THREE.Mesh(coneGeo, mat); m.position.set(...p); m.lookAt(c); m.rotateY(Math.PI); root.add(m);
          const q = new THREE.Vector3(...p).lerp(c, 0.28); lines.push(...p, q.x, q.y, q.z);
        });
        root.userData.rig = { center: c.clone(), radius: r };
        const lg = new THREE.BufferGeometry(); lg.setAttribute("position", new THREE.Float32BufferAttribute(lines, 3));
        root.add(new THREE.LineSegments(lg, new THREE.LineBasicMaterial({ color: accent, transparent: true, opacity: 0.2 })));
      }
    }
    return root;
  }

  function frame(obj, file) {
    obj.updateMatrixWorld(true);
    let center, size, dist;
    const rig = obj.userData.rig;
    if (rig) {
      // 점군에는 멀리 떠 있는 잡음 점이 섞여 있어, 상자 대신 카메라 링(머리 중심·촬영 반경)으로 맞춘다
      center = obj.localToWorld(rig.center.clone());
      size = rig.radius * obj.scale.x * 2;
      dist = size * 1.1;
    } else {
      const box = new THREE.Box3().setFromObject(obj);
      size = box.getSize(new THREE.Vector3()).length();
      center = box.getCenter(new THREE.Vector3());
      dist = size * 1.1;
    }
    controls.target.copy(center);
    camera.position.copy(center).add(new THREE.Vector3(0.55, 0.45, 0.7).normalize().multiplyScalar(dist));
    camera.near = size / 1000; camera.far = size * 50; camera.updateProjectionMatrix();
  }

  function show(url, file, summary) {
    const put = (geom) => {
      if (current) scene.remove(current);
      current = build(geom, file, summary);
      scene.add(current);
      frame(current, file);
    };
    if (cache[url]) return put(cache[url]);
    loader.load(url, (geom) => { cache[url] = geom; put(geom); });
  }

  function resize() {
    const w = stage.clientWidth, h = stage.clientHeight;
    renderer.setSize(w, h, false); camera.aspect = w / h; camera.updateProjectionMatrix();
  }
  const ro = new ResizeObserver(resize); ro.observe(stage); resize();
  renderer.setAnimationLoop(() => { controls.update(); key.position.copy(camera.position); renderer.render(scene, camera); });
  return {
    show,
    dispose() { renderer.setAnimationLoop(null); ro.disconnect(); renderer.dispose(); renderer.domElement.remove(); },
  };
}

// ---------------- 라우팅 ----------------
function route() {
  const m = location.hash.match(/^#\/job\/([\w-]+)/);
  if (m) return loadJob(m[1]);
  clearTimeout(pollTimer);
  currentJob = null;
  showView("new");
  refreshList();
}

$("newJobBtn").onclick = () => { location.hash = "#/new"; };
$("optForm").addEventListener("submit", submitJob);
$("cancelBtn").onclick = async () => { await api(`/api/jobs/${currentJob}/cancel`, { method: "POST" }); loadJob(currentJob); };
$("retryBtn").onclick = async () => {
  try { await api(`/api/jobs/${currentJob}/start`, { method: "POST" }); } catch (e) { alert(e.message); }
  if (viewer) { viewer.dispose(); viewer = null; }
  $("resultBox").hidden = true;
  loadJob(currentJob);
};
$("deleteBtn").onclick = async () => {
  if (!confirm("이 작업의 사진과 결과를 이 PC 에서 완전히 지웁니다. 계속할까요?")) return;
  await api(`/api/jobs/${currentJob}`, { method: "DELETE" });
  location.hash = "#/new";
};
setupDrop();
window.addEventListener("hashchange", route);
setInterval(refreshList, 5000);
route();
