// VAPID Public Key: scripts/generate_vapid_keys.py 실행 후 출력된 Public Key를 여기에 붙여넣으세요.
const VAPID_PUBLIC_KEY = "";

function urlBase64ToUint8Array(base64String) {
  const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
  const rawData = atob(base64);
  return Uint8Array.from([...rawData].map((c) => c.charCodeAt(0)));
}

// 지난 아티클은 Pages 배포 시 archive/ 아래에 올라간다 (pages.yml 참고)
const ARCHIVE_BASE = "./archive/";

async function loadContent() {
  const res = await fetch("./data/latest.json", { cache: "no-store" });
  if (!res.ok) throw new Error("데이터 없음");
  return res.json();
}

async function loadArchiveIndex() {
  // 배포본은 archive/index.json, 로컬 개발 시에는 data/index.json을 쓴다
  for (const url of [ARCHIVE_BASE + "index.json", "./data/index.json"]) {
    try {
      const res = await fetch(url, { cache: "no-store" });
      if (res.ok) return await res.json();
    } catch (e) {
      /* 다음 경로 시도 */
    }
  }
  throw new Error("아카이브 없음");
}

function renderContent(data, baseOverride) {
  // 오늘 자료는 data/latest/, 지난 자료는 archive/<날짜>/ 에서 읽는다
  const base = baseOverride || "./data/latest/";
  document.getElementById("status").style.display = "none";
  document.getElementById("content").style.display = "block";

  document.getElementById("date").textContent = data.date;
  document.getElementById("title").textContent = data.topic.title;
  document.getElementById("source-link").href = data.topic.url;
  document.getElementById("source-type").textContent =
    data.topic.source_type === "paper" ? "📄 논문" : "📰 뉴스";
  document.getElementById("hook").textContent = data.script.hook;
  document.getElementById("script").textContent = data.script.full_script;

  const pptxLink = document.getElementById("pptx-link");
  pptxLink.href = `${base}${data.assets.pptx}`;

  const gallery = document.getElementById("gallery");
  gallery.innerHTML = "";
  const addImg = (src, label) => {
    const wrap = document.createElement("div");
    wrap.className = "thumb";
    const img = document.createElement("img");
    img.src = src;
    img.loading = "lazy";
    img.alt = label;
    const cap = document.createElement("span");
    cap.textContent = label;
    wrap.appendChild(img);
    wrap.appendChild(cap);
    gallery.appendChild(wrap);
  };
  addImg(`${base}${data.assets.paper_card}`, "표지 카드");
  (data.assets.frames || []).forEach((f, i) => addImg(`${base}${f}`, `씬 ${i + 1}`));

  // 논문 본문에서 가져온 그림·표가 있으면 따로 보여준다
  const paperBox = document.getElementById("paper-assets");
  const figs = (data.assets && data.assets.paper_figures) || [];
  const tbls = (data.assets && data.assets.paper_tables) || [];
  if (paperBox) {
    if (figs.length || tbls.length) {
      paperBox.style.display = "block";
      const g = document.getElementById("paper-gallery");
      g.innerHTML = "";
      figs.forEach((f) => {
        const wrap = document.createElement("div");
        wrap.className = "thumb";
        const img = document.createElement("img");
        img.src = `${base}${f.path}`;
        img.loading = "lazy";
        img.style.aspectRatio = "auto";
        const cap = document.createElement("span");
        cap.textContent = f.label || "Figure";
        wrap.appendChild(img);
        wrap.appendChild(cap);
        g.appendChild(wrap);
      });
      document.getElementById("paper-tables").textContent = tbls.length
        ? tbls.map((t) => `${t.label}: ${t.caption || ""}`).join("\n")
        : "";
    } else {
      const why = data.assets && data.assets.paper_skip_reason;
      if (why) {
        paperBox.style.display = "block";
        document.getElementById("paper-gallery").innerHTML = "";
        document.getElementById("paper-tables").textContent =
          `이 논문의 그림·표는 쓰지 않았습니다 - ${why}`;
      } else {
        paperBox.style.display = "none";
      }
    }
  }
}

function renderArchive(index, filter) {
  const list = document.getElementById("archive-list");
  const q = (filter || "").trim().toLowerCase();
  const items = (index.items || []).filter(
    (it) =>
      !q ||
      (it.title || "").toLowerCase().includes(q) ||
      (it.journal || "").toLowerCase().includes(q)
  );

  document.getElementById("archive-count").textContent =
    q ? `${items.length}건 (전체 ${index.count}건)` : `전체 ${index.count}건`;

  list.innerHTML = "";
  if (!items.length) {
    list.innerHTML = '<div style="color:var(--muted);font-size:13px;padding:20px 0;">검색 결과가 없습니다.</div>';
    return;
  }

  items.forEach((it) => {
    const row = document.createElement("div");
    row.className = "arch-item";

    const img = document.createElement("img");
    img.src = ARCHIVE_BASE + it.thumb;
    img.loading = "lazy";
    img.alt = "";
    img.onerror = () => {
      img.style.visibility = "hidden";
    };

    const meta = document.createElement("div");
    meta.className = "arch-meta";
    const badge = it.has_paper_figures ? '<span class="arch-badge">논문 그림</span>' : "";
    const accent = it.hook_accent ? `<span class="arch-accent">${it.hook_accent}</span>` : "";
    meta.innerHTML =
      `<div class="arch-date">${it.date}${accent}${badge}</div>` +
      `<div class="arch-title">${it.title || "(제목 없음)"}</div>` +
      `<div class="arch-journal">${it.journal || ""}</div>`;

    row.appendChild(img);
    row.appendChild(meta);
    row.addEventListener("click", () => openArchiveItem(it));
    list.appendChild(row);
  });
}

async function openArchiveItem(item) {
  try {
    const res = await fetch(`${ARCHIVE_BASE}${item.dir}/result.json`, { cache: "no-store" });
    if (!res.ok) throw new Error("불러오기 실패");
    const data = await res.json();
    renderContent(data, `${ARCHIVE_BASE}${item.dir}/`);
    showTab("today", { keepArchive: true });
    const back = document.getElementById("back-to-archive");
    if (back) back.style.display = "block";
    window.scrollTo(0, 0);
  } catch (e) {
    alert("이 날짜의 상세 자료를 불러오지 못했습니다. (아직 배포되지 않았을 수 있어요)");
  }
}

function showTab(which, opts) {
  const isToday = which === "today";
  document.getElementById("tab-today").classList.toggle("active", isToday);
  document.getElementById("tab-archive").classList.toggle("active", !isToday);
  document.getElementById("content").style.display = isToday ? "block" : "none";
  document.getElementById("archive-view").style.display = isToday ? "none" : "block";
  document.getElementById("status").style.display = "none";
  if (!(opts && opts.keepArchive)) {
    const back = document.getElementById("back-to-archive");
    if (back) back.style.display = "none";
  }
}

function checkForNewContentAndNotify(data) {
  let lastSeen = null;
  try {
    lastSeen = localStorage.getItem("lastSeenDate");
  } catch (e) {
    /* 프라이빗 모드 등에서 접근 불가할 수 있음 */
  }
  if (lastSeen !== data.date) {
    try {
      localStorage.setItem("lastSeenDate", data.date);
    } catch (e) {
      /* ignore */
    }
    if (lastSeen && "Notification" in window && Notification.permission === "granted") {
      try {
        new Notification("오늘의 탈모 콘텐츠가 준비됐어요", {
          body: data.topic.title,
          icon: "./icons/icon-192.png",
        });
      } catch (e) {
        /* ignore */
      }
    }
  }
}

async function subscribePush() {
  const box = document.getElementById("subscription-box");
  if (!("Notification" in window)) {
    alert("이 브라우저는 알림을 지원하지 않습니다.");
    return;
  }
  const permission = await Notification.requestPermission();
  if (permission !== "granted") {
    alert("알림 권한이 거부되었습니다. 설정에서 다시 허용해주세요.");
    return;
  }

  if (!("serviceWorker" in navigator) || !("PushManager" in window)) {
    alert(
      "실시간 푸시는 이 환경에서 지원되지 않습니다.\niOS의 경우 Safari 공유 버튼 → '홈 화면에 추가'로 설치한 뒤, 홈 화면 아이콘으로 앱을 실행한 상태에서 다시 시도하세요."
    );
    return;
  }

  const reg = await navigator.serviceWorker.ready;
  if (!VAPID_PUBLIC_KEY) {
    alert("알림 권한이 켜졌습니다. (실시간 원격 푸시는 관리자가 VAPID 키 설정을 완료해야 동작합니다 - README 참고)");
    return;
  }

  try {
    const sub = await reg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(VAPID_PUBLIC_KEY),
    });
    document.getElementById("subscription-json").textContent = JSON.stringify(sub.toJSON(), null, 2);
    box.style.display = "block";
  } catch (e) {
    alert("구독 생성에 실패했습니다: " + e.message);
  }
}

window.addEventListener("load", async () => {
  if ("serviceWorker" in navigator) {
    try {
      await navigator.serviceWorker.register("./service-worker.js");
    } catch (e) {
      console.warn("서비스워커 등록 실패", e);
    }
  }

  try {
    const data = await loadContent();
    renderContent(data);
    checkForNewContentAndNotify(data);
  } catch (e) {
    document.getElementById("status").textContent =
      "아직 생성된 콘텐츠가 없습니다. 첫 자동 실행(매일 오전 10시 KST) 이후 표시됩니다.";
  }

  document.getElementById("subscribe-btn").addEventListener("click", subscribePush);

  // 지난 아티클 탭
  let archiveIndex = null;
  const loadAndRenderArchive = async () => {
    if (!archiveIndex) {
      try {
        archiveIndex = await loadArchiveIndex();
      } catch (e) {
        document.getElementById("archive-list").innerHTML =
          '<div style="color:var(--muted);font-size:13px;padding:20px 0;">아직 쌓인 아티클이 없습니다.</div>';
        return;
      }
    }
    renderArchive(archiveIndex, document.getElementById("archive-search").value);
  };

  document.getElementById("tab-archive").addEventListener("click", async () => {
    showTab("archive");
    await loadAndRenderArchive();
  });
  document.getElementById("tab-today").addEventListener("click", async () => {
    showTab("today");
    try {
      renderContent(await loadContent());
    } catch (e) {
      /* 오늘 자료가 없으면 그대로 둔다 */
    }
  });
  document.getElementById("archive-search").addEventListener("input", () => {
    if (archiveIndex) renderArchive(archiveIndex, document.getElementById("archive-search").value);
  });
  const back = document.getElementById("back-to-archive");
  if (back) {
    back.addEventListener("click", async () => {
      showTab("archive");
      await loadAndRenderArchive();
    });
  }
});
