const stream = document.getElementById("stream");
const canvas = document.getElementById("overlay");
const ctx = canvas.getContext("2d");
const hint = document.getElementById("hint");
const callBanner = document.getElementById("callBanner");
const scoreline = document.getElementById("scoreline");
const statusPill = document.getElementById("statusPill");
const replayList = document.getElementById("replayList");
const replayPlayer = document.getElementById("replayPlayer");

let corners = [];
let calibrating = true;
let lastCallShown = null;

function resizeCanvas() {
  const rect = stream.getBoundingClientRect();
  canvas.width = stream.naturalWidth || rect.width;
  canvas.height = stream.naturalHeight || rect.height;
  canvas.style.width = rect.width + "px";
  canvas.style.height = rect.height + "px";
  drawCorners();
}
window.addEventListener("resize", resizeCanvas);
stream.addEventListener("load", resizeCanvas);

function toImageCoords(evt) {
  const rect = canvas.getBoundingClientRect();
  const x = ((evt.clientX - rect.left) / rect.width) * canvas.width;
  const y = ((evt.clientY - rect.top) / rect.height) * canvas.height;
  return [x, y];
}

function drawCorners() {
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  corners.forEach((p, i) => {
    ctx.beginPath();
    ctx.arc(p[0], p[1], 6, 0, Math.PI * 2);
    ctx.fillStyle = "#9dff57";
    ctx.fill();
    ctx.fillStyle = "#fff";
    ctx.font = "14px sans-serif";
    ctx.fillText(String(i + 1), p[0] + 8, p[1] - 8);
  });
  if (corners.length >= 2) {
    ctx.beginPath();
    ctx.moveTo(corners[0][0], corners[0][1]);
    for (let i = 1; i < corners.length; i++) ctx.lineTo(corners[i][0], corners[i][1]);
    if (corners.length === 4) ctx.closePath();
    ctx.strokeStyle = "rgba(157,255,87,0.9)";
    ctx.lineWidth = 2;
    ctx.stroke();
  }
}

canvas.parentElement.classList.toggle("calibrating", true);

canvas.addEventListener("click", async (evt) => {
  // when calibrating, clicks go to canvas; otherwise enable pointer on wrap via class
});

document.querySelector(".video-wrap").addEventListener("click", async (evt) => {
  if (!calibrating && corners.length === 4) {
    // map click for manual call using displayed img size vs natural
    const img = stream;
    const rect = img.getBoundingClientRect();
    const scaleX = (img.naturalWidth || canvas.width) / rect.width;
    const scaleY = (img.naturalHeight || canvas.height) / rect.height;
    // account for object-fit: contain letterboxing
    const natW = img.naturalWidth || rect.width;
    const natH = img.naturalHeight || rect.height;
    const fit = Math.min(rect.width / natW, rect.height / natH);
    const dispW = natW * fit;
    const dispH = natH * fit;
    const offX = (rect.width - dispW) / 2;
    const offY = (rect.height - dispH) / 2;
    const x = (evt.clientX - rect.left - offX) / fit;
    const y = (evt.clientY - rect.top - offY) / fit;
    if (x < 0 || y < 0 || x > natW || y > natH) return;
    const res = await api("/api/call/manual", { x, y });
    showCall(res.call);
    refreshReplays();
    return;
  }

  if (!calibrating) return;
  const img = stream;
  const rect = img.getBoundingClientRect();
  const natW = img.naturalWidth || rect.width;
  const natH = img.naturalHeight || rect.height;
  const fit = Math.min(rect.width / natW, rect.height / natH);
  const dispW = natW * fit;
  const dispH = natH * fit;
  const offX = (rect.width - dispW) / 2;
  const offY = (rect.height - dispH) / 2;
  const x = (evt.clientX - rect.left - offX) / fit;
  const y = (evt.clientY - rect.top - offY) / fit;
  if (x < 0 || y < 0 || x > natW || y > natH) return;

  corners.push([x, y]);
  canvas.width = natW;
  canvas.height = natH;
  drawCorners();

  if (corners.length === 4) {
    await api("/api/table/corners", { corners });
    calibrating = false;
    hint.textContent = "Table locked. Click feed to force an IN/OUT call. Auto-calls fire on bounce.";
  } else {
    hint.textContent = `Corner ${corners.length}/4 set (TL → TR → BR → BL)`;
  }
});

async function api(url, body, method = "POST") {
  const opts = { method };
  if (body !== undefined) {
    opts.headers = { "Content-Type": "application/json" };
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(url, opts);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

function showCall(call) {
  if (!call || call === "UNKNOWN") return;
  callBanner.hidden = false;
  callBanner.textContent = call;
  callBanner.className = "call-banner " + call.toLowerCase();
  lastCallShown = call;
  setTimeout(() => {
    if (lastCallShown === call) callBanner.hidden = true;
  }, 2500);
}

async function refreshStatus() {
  const s = await fetch("/api/status").then((r) => r.json());
  const sc = s.score;
  scoreline.textContent = `${sc.player_a}  ${sc.games_a} (${sc.a})  —  (${sc.b}) ${sc.games_b}  ${sc.player_b}   · serve ${sc.serving}`;
  statusPill.textContent = `${s.state || "?"} · ${s.source || "cam"}`;
  if (s.last_call && s.last_call !== lastCallShown) showCall(s.last_call);
  document.getElementById("autoCall").checked = !!s.auto_call;
  if (s.config?.camera_url) {
    const el = document.getElementById("cameraUrl");
    if (!el.value) el.value = s.config.camera_url;
  }
}

async function refreshReplays() {
  const data = await fetch("/api/replays").then((r) => r.json());
  replayList.innerHTML = "";
  for (const c of data.clips || []) {
    const li = document.createElement("li");
    const when = new Date(c.created_at * 1000).toLocaleTimeString();
    li.innerHTML = `<span>${c.label} · ${when}</span>`;
    const btn = document.createElement("button");
    btn.className = "link";
    btn.textContent = "Review";
    btn.onclick = () => {
      replayPlayer.src = c.url;
      replayPlayer.play();
    };
    li.appendChild(btn);
    replayList.appendChild(li);
  }
}

document.querySelectorAll("[data-side]").forEach((btn) => {
  btn.addEventListener("click", async () => {
    await api("/api/score/point", { side: btn.dataset.side });
    refreshStatus();
  });
});

document.getElementById("undo").onclick = async () => {
  await api("/api/score/undo");
  refreshStatus();
};
document.getElementById("resetGame").onclick = async () => {
  await api("/api/score/reset-game");
  refreshStatus();
};
document.getElementById("resetMatch").onclick = async () => {
  await api("/api/score/reset-match");
  refreshStatus();
};
document.getElementById("saveNames").onclick = async () => {
  await api("/api/score/names", {
    player_a: document.getElementById("nameA").value,
    player_b: document.getElementById("nameB").value,
  });
  refreshStatus();
};
document.getElementById("autoCall").onchange = async (e) => {
  await fetch(`/api/auto-call?enabled=${e.target.checked}`, { method: "POST" });
};
document.getElementById("calibrate").onclick = () => {
  corners = [];
  calibrating = true;
  drawCorners();
  hint.textContent = "Click 4 table corners: TL → TR → BR → BL";
};
document.getElementById("clearTable").onclick = async () => {
  corners = [];
  calibrating = true;
  drawCorners();
  await fetch("/api/table/clear", { method: "POST" });
  hint.textContent = "Recalibrate: click 4 corners TL → TR → BR → BL";
};
document.getElementById("saveCamera").onclick = async () => {
  const camera_url = document.getElementById("cameraUrl").value.trim();
  const res = await api("/api/camera", { camera_url, prefer_phone: true });
  statusPill.textContent = res.ok ? `phone · ${res.source}` : res.error || "camera fail";
};
document.getElementById("saveHsv").onclick = async () => {
  await api("/api/hsv", {
    lower: [
      +document.getElementById("hLo").value,
      +document.getElementById("sLo").value,
      +document.getElementById("vLo").value,
    ],
    upper: [
      +document.getElementById("hHi").value,
      +document.getElementById("sHi").value,
      +document.getElementById("vHi").value,
    ],
  });
};
document.getElementById("saveReplay").onclick = async () => {
  await fetch("/api/replay/save?label=challenge", { method: "POST" });
  refreshReplays();
};

setInterval(refreshStatus, 800);
setInterval(refreshReplays, 4000);
refreshStatus();
refreshReplays();
