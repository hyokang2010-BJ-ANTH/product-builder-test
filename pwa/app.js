// VAPID Public Key: scripts/generate_vapid_keys.py 실행 후 출력된 Public Key를 여기에 붙여넣으세요.
const VAPID_PUBLIC_KEY = "";

function urlBase64ToUint8Array(base64String) {
  const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
  const rawData = atob(base64);
  return Uint8Array.from([...rawData].map((c) => c.charCodeAt(0)));
}

async function loadContent() {
  const res = await fetch("./data/latest.json", { cache: "no-store" });
  if (!res.ok) throw new Error("데이터 없음");
  return res.json();
}

function renderContent(data) {
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
  pptxLink.href = `./data/latest/${data.assets.pptx}`;

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
  addImg(`./data/latest/${data.assets.paper_card}`, "표지 카드");
  (data.assets.frames || []).forEach((f, i) => addImg(`./data/latest/${f}`, `씬 ${i + 1}`));
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
});
