// Fold A2 poker room client: setup, lobby, and the table. Polls /api/state.
const $ = (id) => document.getElementById(id);
const SUIT = { s: "♠", h: "♥", d: "♦", c: "♣" };
let catalog = [];
let session = null;        // {room, token}
let state = null;
let lastVersion = -1;
let pollTimer = null;
let sending = false;
let nextDeadline = 0;

// ------------------------------------------------------------ helpers
function show(id) {
  for (const s of document.querySelectorAll(".screen")) s.classList.add("hidden");
  $(id).classList.remove("hidden");
}
function seg(id, onChange) {
  const el = $(id);
  el.addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    for (const x of el.querySelectorAll("button")) x.classList.toggle("on", x === b);
    onChange && onChange(b.dataset.v);
  });
}
const segVal = (id) => $(id).querySelector("button.on").dataset.v;
async function api(path, body) {
  const r = await fetch(path, body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {});
  const j = await r.json();
  if (!r.ok) throw new Error(j.error || r.statusText);
  return j;
}
function cardEl(c, small) {
  const d = document.createElement("div");
  d.className = "card" + (small ? " sm" : "");
  if (!c) { d.classList.add("back"); return d; }
  const r = c[0] === "T" ? "10" : c[0], s = c[1];
  if (s === "h" || s === "d") d.classList.add("red");
  d.innerHTML = `<span class="r">${r}</span><span class="s">${SUIT[s]}</span>`;
  return d;
}
function saveSession(s) {
  session = s;
  try { localStorage.setItem("fa2-session", JSON.stringify(s)); } catch (e) {}
  history.replaceState(null, "", "?room=" + s.room);
}
function loadSession(room) {
  const t = new URLSearchParams(location.hash.slice(1)).get("t");  // "#t=<token>" reopens a seat in another browser
  if (t) return { room, token: t };
  try {
    const s = JSON.parse(localStorage.getItem("fa2-session") || "null");
    if (s && s.room === room) return s;
  } catch (e) {}
  return null;
}

// ------------------------------------------------------------ setup
function botSeats() { return +segVal("seats") - (segVal("mode") === "multi" ? +segVal("humans") : 1); }
function renderHumans() {
  const n = +segVal("seats"), cur = $("humans").querySelector("button.on");
  const keep = cur ? +cur.dataset.v : 2;
  $("humans").innerHTML = "";
  for (let h = 2; h <= Math.min(n - 1, 6); h++) {
    const b = document.createElement("button");
    b.dataset.v = h; b.textContent = h;
    if (h === Math.min(keep, n - 1)) b.classList.add("on");
    $("humans").appendChild(b);
  }
}
function renderCustom() {
  const box = $("custom");
  if (segVal("preset") !== "custom") { box.classList.add("hidden"); return; }
  box.classList.remove("hidden");
  const prev = [...box.querySelectorAll("select")].map((s) => s.value);
  box.innerHTML = "";
  for (let i = 0; i < botSeats(); i++) {
    const l = document.createElement("label");
    l.textContent = `Bot seat ${i + 1}`;
    const sel = document.createElement("select");
    for (const b of catalog) { const o = document.createElement("option"); o.value = b.id; o.textContent = b.label; sel.appendChild(o); }
    sel.value = prev[i] || "v4";
    l.appendChild(sel); box.appendChild(l);
  }
}
function lineup() {
  const n = botSeats(), p = segVal("preset");
  const clones = catalog.filter((b) => b.id.startsWith("clone:")).map((b) => b.id);
  const pool = clones.length ? clones : catalog.filter((b) => b.id.startsWith("house:")).map((b) => b.id);
  const shuffled = [...pool].sort(() => Math.random() - 0.5);
  if (p === "custom") return [...$("custom").querySelectorAll("select")].map((s) => s.value);
  if (p === "v4") return Array(n).fill("v4");
  if (p === "ladder") return Array.from({ length: n }, (_, i) => shuffled[i % shuffled.length]);
  // mix: our two bots first, then ladder copies
  const out = ["v4", "v35"];
  for (let i = 0; out.length < n; i++) out.push(shuffled[i % shuffled.length]);
  return out.slice(0, n);
}
async function createRoom() {
  $("setup-err").textContent = "";
  const multi = segVal("mode") === "multi";
  try {
    const r = await api("/api/create", {
      name: $("name").value.trim() || "You",
      seats: +segVal("seats"),
      humans: multi ? +segVal("humans") : 1,
      hands: +segVal("hands"),
      mode: segVal("gametype"),
      start_stack: +segVal("stack"),
      level_hands: +segVal("levels"),
      bot_delay: +segVal("speed"),
      auto_next: multi ? 6 : 4,
      turn_limit: multi ? 45 : 0,
      lineup: lineup(),
    });
    saveSession({ room: r.room, token: r.token });
    startPolling();
  } catch (e) { $("setup-err").textContent = e.message; }
}

// ------------------------------------------------------------ join / lobby
async function openJoin(room) {
  show("join");
  try {
    const info = await api("/api/room_info?room=" + encodeURIComponent(room));
    $("join-info").textContent = info.status !== "lobby" ? "This game has already started."
      : info.open ? `${info.seats_n}-player table, ${info.open} open seat${info.open > 1 ? "s" : ""}.` : "This table is full.";
    $("join-go").disabled = info.status !== "lobby" || !info.open;
  } catch (e) { $("join-info").textContent = "Room not found. It may have ended."; $("join-go").disabled = true; }
  $("join-go").onclick = async () => {
    try {
      const r = await api("/api/join", { room, name: $("join-name").value.trim() });
      saveSession({ room: r.room, token: r.token });
      startPolling();
    } catch (e) { $("join-err").textContent = e.message; }
  };
}
function renderLobby(s) {
  show("lobby");
  $("share").value = location.origin + "/?room=" + s.room;
  $("lobby-list").innerHTML = s.lobby.map((p) =>
    `<li><span>${esc(p.name)}${p.pid === s.me ? " (you)" : ""}</span><span class="tag ${p.kind === "bot" || p.joined ? "ok" : ""}">${
      p.kind === "bot" ? "bot" : p.joined ? "joined" : "waiting…"}</span></li>`).join("");
  const host = s.me === 0;
  $("start").classList.toggle("hidden", !host);
  $("lobby-wait").textContent = host ? "Open seats are filled by Fold-A2 v4.2 when you start." : "Waiting for the host to start…";
}

// ------------------------------------------------------------ polling
function startPolling() {
  clearInterval(pollTimer);
  lastVersion = -1;
  poll();
  pollTimer = setInterval(poll, 300);
}
async function poll() {
  if (!session) return;
  let s;
  try {
    s = await api(`/api/state?room=${encodeURIComponent(session.room)}&token=${encodeURIComponent(session.token)}`);
  } catch (e) {
    clearInterval(pollTimer);
    alert("This table is no longer available.");
    goHome();
    return;
  }
  if (s.version === lastVersion) { tickNext(); return; }
  const wasBetween = state && state.between_hands;
  lastVersion = s.version;
  state = s;
  if (s.status === "lobby") return renderLobby(s);
  show("game");
  if (s.between_hands && !wasBetween) nextDeadline = Date.now() + s.auto_next * 1000;
  renderGame(s);
}

// ------------------------------------------------------------ table
function esc(t) { return String(t).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }

// Draws seats around the table. model: {seats, n, mine, ko, me, cardsFor(p), live}
function drawSeats(layer, m) {
  layer.innerHTML = "";
  const narrow = window.innerWidth < 600;
  for (const p of m.seats) {
    const i = ((m.ko ? p.pos : p.seat) - m.mine + m.n) % m.n;
    const th = Math.PI / 2 + (i * 2 * Math.PI) / m.n;
    const x = 50 + (narrow ? 38 : 43) * Math.cos(th), y = 50 + (narrow ? 43 : 41) * Math.sin(th);
    const el = document.createElement("div");
    el.style.left = x + "%"; el.style.top = y + "%";
    if (p.out) {
      el.className = "seat out" + (p.pid === m.me ? " me" : "");
      el.innerHTML = `<div class="plate"><div class="name">${esc(p.name)}</div><div class="stack">Out · 0</div></div>`;
      layer.appendChild(el);
      continue;
    }
    el.className = "seat" + (p.pid === m.me ? " me" : "") + (p.acting ? " acting" : "") + (p.folded ? " folded" : "");
    const cards = document.createElement("div");
    cards.className = "cards";
    const known = m.cardsFor(p);
    if (known) for (const c of known) cards.appendChild(cardEl(c, p.pid !== m.me));
    else if (!p.folded && m.live) { cards.appendChild(cardEl(null, true)); cards.appendChild(cardEl(null, true)); }
    const badge = p.button ? '<span class="badge d">D</span>' : p.sb ? '<span class="badge sb">SB</span>' : p.bb ? '<span class="badge bb">BB</span>' : "";
    const delta = p.result != null && p.result !== 0
      ? `<div class="delta ${p.result > 0 ? "pos" : "neg"}">${p.result > 0 ? "+" : ""}${p.result}</div>` : "";
    el.innerHTML = `<div class="plate">${badge}<div class="name">${esc(p.name)}</div>
      <div class="stack">${p.allin && p.result == null ? "All-in" : p.stack}</div></div>
      <div class="last">${esc(p.last || "")}</div>${delta}${p.shown_hand ? `<div class="handname">${esc(p.shown_hand)}</div>` : ""}`;
    el.prepend(cards);
    layer.appendChild(el);
    if (p.bet > 0) {
      const b = document.createElement("div");
      b.className = "bet";
      b.style.left = 50 + (narrow ? 22 : 27) * Math.cos(th) + "%"; b.style.top = 50 + (narrow ? 27 : 24) * Math.sin(th) + "%";
      b.textContent = p.bet;
      layer.appendChild(b);
    }
  }
}
function drawBoard(boardEl, potEl, board, pot) {
  boardEl.innerHTML = "";
  for (const c of board) boardEl.appendChild(cardEl(c));
  potEl.textContent = pot ? `Pot ${pot}` : "";
}

function renderGame(s) {
  const ko = s.mode === "knockout";
  $("hand-no").textContent = s.status === "finished" ? "Finished"
    : ko ? `Hand ${Math.max(s.hand, 1)} · Blinds ${s.blinds[0]}/${s.blinds[1]}${s.next_level_in ? ` · up in ${s.next_level_in}` : ""}`
    : `Hand ${Math.max(s.hand, 1)} / ${s.num_hands}`;
  $("share-btn").classList.toggle("hidden", !s.lobby.some((p) => p.kind === "human" && p.pid !== s.me));
  $("replay-btn").classList.toggle("hidden", !s.history_n);
  drawBoard($("board"), $("pot"), s.board, s.pot);
  // knockout: everyone keeps a fixed place (pos) and the dealer button moves; tournament: seats rotate
  drawSeats($("seats-layer"), {
    seats: s.table, n: ko ? s.seats_n : s.table.length, mine: ko ? s.my_pos : (s.my_seat ?? 0), ko, me: s.me,
    cardsFor: (p) => p.cards, live: s.hand > 0,
  });
  $("banner").textContent = s.between_hands ? (s.result_lines || []).join(" · ") : "";
  renderControls(s);
  // standings: chips each player has left
  const fmt = (c) => ko ? `${c}` : `${c > 0 ? "+" : ""}${c}`;
  $("scores").innerHTML = s.scores.map((r) =>
    `<li class="${r.pid === s.me ? "me" : ""}${ko && r.chips <= 0 ? " out" : ""}"><span>${esc(r.name)}</span><span class="${
      ko ? "" : r.chips > 0 ? "pos" : r.chips < 0 ? "neg" : ""}">${fmt(r.chips)}</span></li>`).join("");
  const log = $("log");
  const atBottom = log.scrollTop + log.clientHeight >= log.scrollHeight - 20;
  log.innerHTML = s.log.map((l) => `<div class="${l.startsWith("—") ? "hd" : ""}">${esc(l)}</div>`).join("");
  if (atBottom) log.scrollTop = log.scrollHeight;
  // game over
  if (s.status === "finished" || s.status === "error") {
    $("final").classList.remove("hidden");
    const top = s.scores[0];
    $("final").querySelector("h2").textContent = top && top.pid === s.me ? "You finish on top! 🏆" : `Game over · ${top ? top.name : ""} finishes on top`;
    $("final-list").innerHTML = s.scores.map((r) =>
      `<li class="${r.pid === s.me ? "me" : ""}"><span>${esc(r.name)}</span><span>${fmt(r.chips)} chips</span></li>`).join("")
      + (s.status === "error" ? `<p class="err">${esc(s.log[s.log.length - 1] || "")}</p>` : "");
  }
}

// ------------------------------------------------------------ replays
let rp = null;  // {data, i, timer}
async function openReplays() {
  $("replay").classList.remove("hidden");
  const list = await api(`/api/history?room=${encodeURIComponent(session.room)}&token=${encodeURIComponent(session.token)}`);
  $("rp-list").innerHTML = list.slice().reverse().map((h) =>
    `<li data-h="${h.hand}"><b>Hand ${h.hand}</b><span class="${h.delta > 0 ? "pos" : h.delta < 0 ? "neg" : ""}">${
      h.delta == null ? "" : (h.delta > 0 ? "+" : "") + h.delta}</span><small>${esc(h.lines.join(" · "))}</small></li>`).join("")
    || "<li class=\"muted\">No finished hands yet.</li>";
  if (list.length && !rp) loadReplay(list[list.length - 1].hand);
}
async function loadReplay(hand) {
  stopReplay();
  const d = await api(`/api/replay?room=${encodeURIComponent(session.room)}&token=${encodeURIComponent(session.token)}&hand=${hand}`);
  rp = { data: d, i: 0, timer: null };
  for (const li of $("rp-list").querySelectorAll("li")) li.classList.toggle("on", +li.dataset.h === hand);
  drawReplay();
}
function drawReplay() {
  if (!rp) return;
  const d = rp.data, f = d.frames[rp.i];
  const ko = d.mode === "knockout";
  drawBoard($("rp-board"), $("rp-pot"), f.board, f.pot);
  drawSeats($("rp-seats"), {
    seats: f.seats, n: ko ? d.n : f.seats.length, mine: ko ? d.my_pos : (f.seats.find((p) => p.pid === d.me) || { seat: 0 }).seat,
    ko, me: d.me, cardsFor: (p) => d.holes[p.pid] || null, live: true,
  });
  $("rp-caption").textContent = f.caption || "";
  $("rp-title").textContent = `Hand ${d.hand} · step ${rp.i + 1} / ${d.frames.length}`;
}
function stepReplay(k) {
  if (!rp) return;
  rp.i = Math.max(0, Math.min(rp.data.frames.length - 1, k));
  drawReplay();
}
function stopReplay() { if (rp && rp.timer) { clearInterval(rp.timer); rp.timer = null; } $("rp-play").textContent = "▶ Play"; }
function playReplay() {
  if (!rp) return;
  if (rp.timer) return stopReplay();
  if (rp.i >= rp.data.frames.length - 1) rp.i = 0;
  $("rp-play").textContent = "❚❚ Pause";
  rp.timer = setInterval(() => {
    if (rp.i >= rp.data.frames.length - 1) return stopReplay();
    stepReplay(rp.i + 1);
  }, 900);
}

function renderControls(s) {
  const t = s.my_turn;
  const mc = $("my-controls"), nc = $("next-controls");
  mc.classList.toggle("hidden", !t);
  nc.classList.toggle("hidden", !(s.between_hands && !t && s.status === "playing"));
  const acting = s.table.find((p) => p.acting);
  $("wait-msg").textContent = t ? "" : s.my_place && s.status === "playing" ? "You're out of chips. Watching the rest of the game…"
    : s.between_hands ? "" : acting ? `${acting.name} is thinking…` : s.status === "playing" ? "Dealing…" : "";
  if (!t) return;
  sending = false;
  for (const b of mc.querySelectorAll("button")) b.disabled = false;
  $("b-call").innerHTML = (t.to_call === 0 ? "Check" : t.to_call >= t.stack ? `Call all-in ${t.to_call}` : `Call ${t.to_call}`) + " <kbd>C</kbd>";
  $("b-fold").classList.toggle("hidden", t.to_call === 0);
  const canRaise = t.can_raise && t.max_raise_to > t.my_bet + t.to_call;
  $("b-raise").classList.toggle("hidden", !canRaise);
  document.querySelector(".raise-box").classList.toggle("hidden", !canRaise);
  if (!canRaise) return;
  const sl = $("r-slider"), amt = $("r-amt");
  sl.min = amt.min = t.min_raise_to; sl.max = amt.max = t.max_raise_to; sl.step = 1;
  const def = clampRaise(t, t.my_bet + t.to_call + Math.round(0.66 * (t.pot + t.to_call)));
  sl.value = amt.value = def;
  updateRaiseLabel();
}
function ordinal(n) { const v = n % 100; return n + (v >= 11 && v <= 13 ? "th" : ({ 1: "st", 2: "nd", 3: "rd" }[n % 10] || "th")); }
function clampRaise(t, v) { return Math.max(t.min_raise_to, Math.min(t.max_raise_to, Math.round(v))); }
function updateRaiseLabel() {
  const t = state && state.my_turn; if (!t) return;
  const v = +$("r-amt").value;
  const isBet = t.to_call === 0 && state.street !== "preflop";
  $("b-raise").innerHTML = (v >= t.max_raise_to ? `All-in ${v}` : `${isBet ? "Bet" : "Raise to"} ${v}`) + " <kbd>R</kbd>";
}
async function act(action, amount) {
  if (sending || !state || !state.my_turn) return;
  sending = true;
  for (const b of $("my-controls").querySelectorAll("button")) b.disabled = true;
  try { await api("/api/act", { room: session.room, token: session.token, action, amount }); }
  catch (e) { sending = false; }
  poll();
}
function tickNext() {
  if (!state || !state.between_hands || !state.auto_next) { $("next-timer").textContent = ""; return; }
  const left = Math.max(0, Math.ceil((nextDeadline - Date.now()) / 1000));
  $("next-timer").textContent = left ? `next hand in ${left}s` : "";
}
function goHome() {
  clearInterval(pollTimer);
  session = null; state = null;
  try { localStorage.removeItem("fa2-session"); } catch (e) {}
  history.replaceState(null, "", "/");
  $("final").classList.add("hidden");
  show("setup");
}

// ------------------------------------------------------------ wiring
seg("seats", () => { renderHumans(); renderCustom(); });
seg("mode", (v) => { $("humans-field").classList.toggle("hidden", v !== "multi"); renderHumans(); renderCustom(); });
seg("humans", renderCustom);
seg("preset", renderCustom);
seg("hands"); seg("speed"); seg("stack"); seg("levels");
seg("gametype", (v) => {
  $("ko-opts").classList.toggle("hidden", v !== "knockout");
  $("hands-field").classList.toggle("hidden", v === "knockout");
  $("gametype-help").textContent = v === "knockout"
    ? "Stacks carry over, the button and blinds move round the table, blinds go up over time, and busted players are out. Last player standing wins."
    : "Same as the MAC tournament: 200-chip stacks reset every hand, blinds 1/2, everyone moves one seat each hand, most chips after N hands wins.";
});
$("hands-field").classList.add("hidden");
$("go").onclick = createRoom;
$("start").onclick = () => api("/api/start", session).catch((e) => alert(e.message));
$("copy").onclick = () => { $("share").select(); navigator.clipboard && navigator.clipboard.writeText($("share").value); };
$("share-btn").onclick = () => { const u = location.origin + "/?room=" + session.room; navigator.clipboard && navigator.clipboard.writeText(u); alert("Invite link copied:\n" + u); };
$("leave").onclick = async () => { if (!confirm("Leave this table? The game ends for everyone.")) return; try { await api("/api/leave", session); } catch (e) {} goHome(); };
$("again").onclick = goHome;
$("replay-btn").onclick = openReplays;
$("final-replay").onclick = () => { $("final").classList.add("hidden"); openReplays(); };
$("rp-close").onclick = () => { stopReplay(); rp = null; $("replay").classList.add("hidden"); if (state && state.status === "finished") $("final").classList.remove("hidden"); };
$("rp-list").onclick = (e) => { const li = e.target.closest("li[data-h]"); if (li) loadReplay(+li.dataset.h); };
$("rp-first").onclick = () => { stopReplay(); stepReplay(0); };
$("rp-prev").onclick = () => { stopReplay(); stepReplay(rp.i - 1); };
$("rp-next").onclick = () => { stopReplay(); stepReplay(rp.i + 1); };
$("rp-last").onclick = () => { stopReplay(); stepReplay(1e9); };
$("rp-play").onclick = playReplay;
$("b-fold").onclick = () => act("fold");
$("b-call").onclick = () => act(state.my_turn.to_call === 0 ? "check" : "call");
$("b-raise").onclick = () => act("raise", +$("r-amt").value);
$("b-next").onclick = () => api("/api/next", session).catch(() => {});
$("r-slider").oninput = () => { $("r-amt").value = $("r-slider").value; updateRaiseLabel(); };
$("r-amt").oninput = () => { $("r-slider").value = $("r-amt").value; updateRaiseLabel(); };
document.querySelector(".presets").onclick = (e) => {
  const b = e.target.closest("button"); const t = state && state.my_turn; if (!b || !t) return;
  const f = b.dataset.f;
  const v = f === "min" ? t.min_raise_to : f === "allin" ? t.max_raise_to : clampRaise(t, t.my_bet + t.to_call + +f * (t.pot + t.to_call));
  $("r-amt").value = $("r-slider").value = v; updateRaiseLabel();
};
document.addEventListener("keydown", (e) => {
  if (e.target.tagName === "INPUT" && e.target.type !== "range") return;
  if (!$("replay").classList.contains("hidden")) {
    if (e.key === "ArrowRight") { stopReplay(); stepReplay(rp.i + 1); }
    else if (e.key === "ArrowLeft") { stopReplay(); stepReplay(rp.i - 1); }
    else if (e.key === " ") { e.preventDefault(); playReplay(); }
    else if (e.key === "Escape") $("rp-close").click();
    return;
  }
  if (!state || $("game").classList.contains("hidden")) return;
  const t = state.my_turn, k = e.key.toLowerCase();
  if (t) {
    if (k === "f" && t.to_call > 0) act("fold");
    else if (k === "c") act(t.to_call === 0 ? "check" : "call");
    else if (k === "r" && !$("b-raise").classList.contains("hidden")) act("raise", +$("r-amt").value);
  } else if (k === " " && state.between_hands) { e.preventDefault(); api("/api/next", session).catch(() => {}); }
});

(async function init() {
  catalog = await api("/api/bots");
  renderHumans();
  const room = new URLSearchParams(location.search).get("room");
  if (room) {
    const s = loadSession(room);
    if (s) { session = s; startPolling(); } else openJoin(room);
  }
})();
