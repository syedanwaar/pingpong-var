const stream = document.getElementById("stream");
const canvas = document.getElementById("overlay");
const ctx = canvas.getContext("2d");
const hint = document.getElementById("hint");
const callBanner = document.getElementById("callBanner");
const scoreline = document.getElementById("scoreline");
const statusPill = document.getElementById("statusPill");
const replayList = document.getElementById("replayList");
const replayPlayer = document.getElementById("replayPlayer");
const timelineEl = document.getElementById("timeline");
const reviewCard = document.getElementById("reviewCard");
const summaryCard = document.getElementById("summaryCard");
const endsBar = document.getElementById("endsBar");
const liveMeta = document.getElementById("liveMeta");

let corners = [];
let calibrating = true;
let lastCallShown = null;
let pendingReviewPointId = null;

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

function mapClickToImage(evt) {
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
  if (x < 0 || y < 0 || x > natW || y > natH) return null;
  return { x, y, natW, natH };
}

document.querySelector(".video-wrap").addEventListener("click", async (evt) => {
  if (!calibrating && corners.length === 4) {
    const pts = mapClickToImage(evt);
    if (!pts) return;
    const res = await api("/api/call/manual", { x: pts.x, y: pts.y });
    showCall(res.call);
    refreshReplays();
    return;
  }
  if (!calibrating) return;
  const pts = mapClickToImage(evt);
  if (!pts) return;
  corners.push([pts.x, pts.y]);
  canvas.width = pts.natW;
  canvas.height = pts.natH;
  drawCorners();
  if (corners.length === 4) {
    await api("/api/table/corners", { corners });
    calibrating = false;
    hint.textContent = "Table locked. Click feed to force an IN/OUT call.";
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
  if (!res.ok) {
    let msg = await res.text();
    try {
      const j = JSON.parse(msg);
      msg = j.detail || msg;
    } catch (_) {}
    throw new Error(msg);
  }
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

function renderTimeline(items) {
  timelineEl.innerHTML = "";
  const list = [...(items || [])].reverse();
  for (const t of list) {
    const li = document.createElement("li");
    const when = t.timestamp ? new Date(t.timestamp).toLocaleTimeString() : "";
    li.innerHTML = `
      <strong>Game ${t.game_number} · Point ${t.point_number || "—"}</strong><br/>
      Awarded: ${t.awarded_to} · Score: ${t.score_after}<br/>
      <span class="meta">Server: ${t.server_before} · ${t.source} · ${when}</span><br/>
      <span class="meta">Review: ${t.review_status} · ${t.final_decision}${t.replay_available ? " · replay" : ""}</span>
    `;
    timelineEl.appendChild(li);
  }
}

function renderMatch(s) {
  const m = s.match || {};
  const pa = m.player_a || {};
  const pb = m.player_b || {};
  const status = m.match_status || "not_started";

  if (status === "not_started") {
    scoreline.textContent = "Start a match to begin";
    liveMeta.textContent = "No match in progress";
    endsBar.textContent = "";
    document.getElementById("pointA").disabled = true;
    document.getElementById("pointB").disabled = true;
    summaryCard.hidden = true;
  } else {
    scoreline.textContent =
      `${pa.name || "A"}  ${pa.games || 0} (${pa.points || 0})  —  (${pb.points || 0}) ${pb.games || 0}  ${pb.name || "B"}` +
      `   · serve ${m.current_server} · G${m.current_game} · BO${m.best_of}`;
    liveMeta.textContent =
      `Status: ${status}` +
      (m.winner ? ` · winner ${m.winner}` : "") +
      (m.pending_review_point_id ? " · REVIEW PENDING" : "") +
      (m.is_deciding_game ? " · deciding game" : "");
    endsBar.innerHTML = `
      <span>LEFT: ${pa.physical_end === "left" ? pa.name : pb.name}</span>
      <span>RIGHT: ${pb.physical_end === "right" ? pb.name : pa.name}</span>
    `;
    const locked = status === "completed" || !!m.pending_review_point_id;
    document.getElementById("pointA").disabled = locked;
    document.getElementById("pointB").disabled = locked;
    document.getElementById("pointA").textContent = `+ ${pa.name || "A"}`;
    document.getElementById("pointB").textContent = `+ ${pb.name || "B"}`;
  }

  renderTimeline(s.timeline || m.timeline || []);

  if (status === "completed" && s.summary) {
    summaryCard.hidden = false;
    const sum = s.summary;
    const games = (sum.game_scores || [])
      .map((g) => `G${g.game_number}: ${g.score_a}–${g.score_b} (${g.winner})`)
      .join("<br/>");
    const mins = sum.duration_seconds != null ? Math.round(sum.duration_seconds / 60) : "—";
    document.getElementById("summaryBody").innerHTML = `
      <div class="stat"><strong>Winner:</strong> ${sum.winner_name || sum.winner}</div>
      <div class="stat"><strong>Games:</strong> ${sum.games_a}–${sum.games_b}</div>
      <div class="stat">${games}</div>
      <div class="stat"><strong>Duration:</strong> ${mins} min</div>
      <div class="stat"><strong>Points:</strong> ${sum.total_points}</div>
      <div class="stat"><strong>Reviews:</strong> ${sum.reviewed_points} (overturned ${sum.overturned_calls})</div>
    `;
  } else if (status !== "completed") {
    summaryCard.hidden = true;
  }
}

async function refreshStatus() {
  const s = await fetch("/api/status").then((r) => r.json());
  statusPill.textContent = `${s.state || "?"} · ${s.source || "cam"}`;
  if (s.last_call && s.last_call !== lastCallShown) showCall(s.last_call);
  document.getElementById("autoCall").checked = !!s.auto_call;
  if (s.config?.camera_url) {
    const el = document.getElementById("cameraUrl");
    if (!el.value) el.value = s.config.camera_url;
  }
  renderMatch(s);
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
    btn.textContent = "Play";
    btn.onclick = () => {
      replayPlayer.src = c.url;
      replayPlayer.play();
    };
    li.appendChild(btn);
    replayList.appendChild(li);
  }
}

document.getElementById("startMatch").onclick = async () => {
  await api("/api/match/start", {
    player_a: document.getElementById("nameA").value,
    player_b: document.getElementById("nameB").value,
    best_of: +document.getElementById("bestOf").value,
    first_server: document.getElementById("firstServer").value,
  });
  reviewCard.hidden = true;
  refreshStatus();
};

async function newMatch() {
  await api("/api/match/new");
  reviewCard.hidden = true;
  pendingReviewPointId = null;
  refreshStatus();
}
document.getElementById("newMatch").onclick = newMatch;
document.getElementById("newMatchFromSummary").onclick = newMatch;

document.querySelectorAll("[data-side]").forEach((btn) => {
  btn.addEventListener("click", async () => {
    try {
      await api("/api/score/point", { side: btn.dataset.side });
      refreshStatus();
    } catch (e) {
      alert(e.message);
    }
  });
});

document.getElementById("undo").onclick = async () => {
  await api("/api/score/undo");
  reviewCard.hidden = true;
  refreshStatus();
};

document.getElementById("reviewBtn").onclick = async () => {
  try {
    const res = await api("/api/review/request");
    pendingReviewPointId = res.point_id;
    reviewCard.hidden = false;
    document.getElementById("reviewMessage").textContent =
      res.message || "Review the latest point.";
    const e = res.entry || {};
    document.getElementById("reviewDetails").innerHTML = `
      <div>Game ${e.game_number} · awarded to ${e.awarded_to} · score ${e.score_after}</div>
    `;
    const player = document.getElementById("reviewPlayer");
    if (res.clip_url) {
      player.src = res.clip_url;
      player.play().catch(() => {});
    } else {
      player.removeAttribute("src");
    }
    refreshStatus();
  } catch (err) {
    alert(err.message);
  }
};

async function resolveReview(decision) {
  try {
    await api("/api/review/resolve", {
      decision,
      point_id: pendingReviewPointId,
    });
    reviewCard.hidden = true;
    pendingReviewPointId = null;
    refreshStatus();
  } catch (e) {
    alert(e.message);
  }
}
document.getElementById("upholdBtn").onclick = () => resolveReview("uphold");
document.getElementById("overturnBtn").onclick = () => resolveReview("overturn");
document.getElementById("voidBtn").onclick = () => resolveReview("void");

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

setInterval(refreshStatus, 1000);
setInterval(refreshReplays, 4000);
refreshStatus();
refreshReplays();
