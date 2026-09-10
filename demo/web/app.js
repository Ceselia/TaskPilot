/* 「一句话代办」Demo 前端（P0 + P1 + P2）：
   WebSocket 订阅流式事件，驱动三栏联动渲染。 */
const $ = (s) => document.querySelector(s);

const PHASE2STAGE = {
  RECEIVED: 0, CLARIFYING: 1, PLANNING: 2, PLAN_REVIEW: 3, BACKUP: 4,
  EXECUTING: 5, GATE: 6, REPORTING: 7, FEEDBACK: 8,
};

let ws = null;
let started = false;
let awaitingAnswer = false;
let curBubble = null;
let prevFs = null;
let mailState = null;
let activeTab = "inbox";
let activeMailId = null;
let injectOn = false;

/* ---------------- WebSocket ---------------- */
function connect() {
  ws = new WebSocket(`ws://${location.host}/ws`);
  ws.onmessage = (e) => handle(JSON.parse(e.data));
  ws.onclose = () => setTimeout(connect, 1000);
}

async function post(path, body) {
  const r = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  }).catch(() => null);
  if (r && !r.ok) {
    const e = await r.json().catch(() => ({}));
    toast(e.detail || "请求失败");
  }
}

/* ---------------- 事件分发 ---------------- */
function handle(m) {
  switch (m.type) {
    case "hello":
    case "phase": setPhase(m.phase); break;
    case "user_said": addUserMsg(m.text); break;
    case "thought_start": startBotMsg(); break;
    case "thought":
      if (!curBubble) startBotMsg();
      curBubble.insertBefore(document.createTextNode(m.chunk), curBubble.lastChild);
      scrollChat();
      break;
    case "thought_end": endBotMsg(); break;
    case "question":
      awaitingAnswer = true;
      showQuick(m.quick);
      setInputMode("answer");
      break;
    case "auth_ask":                      // P1：通讯录授权弹窗
      showAuthModal();
      setInputMode("busy");
      break;
    case "plan": addPlanCard(m, false); break;
    case "plan_auto": addPlanCard(m, true); break;   // P1：信任递进
    case "gate": addGateCard(m); break;
    case "help": addHelpCard(); break;               // P1：N4 求助
    case "self_edit": activateSelfEdit(m.draft); break;  // P1：路径 B
    case "steps": renderSteps(m.steps); break;
    case "fs": renderFs(m.fs); break;
    case "mail": renderMail(m.mail); break;
    case "report": addReportCard(m); break;
    case "stats": addStatsCard(m); break;
    case "inject_state": setInjectUI(m.on); break;
    case "finished":
      started = false;
      awaitingAnswer = false;
      hideQuick();
      setInputMode("idle");
      break;
    case "reset": location.reload(); break;
  }
}

function setPhase(p) {
  const idx = PHASE2STAGE[p];
  document.querySelectorAll(".stage").forEach((el, i) =>
    el.classList.toggle("active", i === idx));
}

/* ---------------- 聊天流 ---------------- */
function addUserMsg(text) {
  const d = document.createElement("div");
  d.className = "msg user";
  d.textContent = text;
  $("#chat").appendChild(d);
  scrollChat();
}

function startBotMsg() {
  const d = document.createElement("div");
  d.className = "msg bot";
  const caret = document.createElement("span");
  caret.className = "caret";
  d.appendChild(caret);
  $("#chat").appendChild(d);
  curBubble = d;
  scrollChat();
}

function endBotMsg() {
  if (curBubble) {
    const caret = curBubble.querySelector(".caret");
    if (caret) caret.remove();
  }
  curBubble = null;
}

function scrollChat() {
  const c = $("#chat");
  c.scrollTop = c.scrollHeight;
}

/* ---------------- 步骤面板 ---------------- */
const ICON = { pending: "·", running: "▶", done: "✓", failed: "✗" };
function renderSteps(steps) {
  $("#steps").innerHTML = (steps || []).map((s) =>
    `<span class="step ${s.status}"><span class="num">${ICON[s.status]}</span>${s.name}</span>`
  ).join("");
}

/* ---------------- 中栏：虚拟文件系统 ---------------- */
function fileChips(names, prev) {
  if (!names.length) return `<span class="empty">（空）</span>`;
  return names.map((n) =>
    `<span class="file${prev && !prev.includes(n) ? " fresh" : ""}">${n}</span>`).join("");
}

function renderFs(fs) {
  $("#fs-download").innerHTML = fileChips(fs.download, prevFs && prevFs.download);
  $("#count-download").textContent = `${fs.download.length} 项`;

  const months = Object.keys(fs.archive).sort();
  $("#fs-archive").innerHTML = months.length
    ? months.map((mo) =>
        `<div class="month">📁 ${mo}</div><div class="files">${fileChips(fs.archive[mo], prevFs && prevFs.archive[mo])}</div>`
      ).join("")
    : `<span class="empty">（尚未归档）</span>`;
  $("#count-archive").textContent =
    `${months.reduce((a, m) => a + fs.archive[m].length, 0)} 项`;

  $("#fs-backup").innerHTML = fileChips(fs.backup, prevFs && prevFs.backup);
  $("#count-backup").textContent = `${fs.backup.length} 项`;

  $("#fs-artifacts").innerHTML = fs.summary
    ? `<span class="file artifact fresh">📊 ${fs.summary}</span>`
    : `<span class="empty">（暂无产物）</span>`;

  prevFs = JSON.parse(JSON.stringify(fs));
}

/* ---------------- 右栏：虚拟邮件 ---------------- */
function renderMail(mail) {
  mailState = mail;
  $("#n-inbox").textContent = mail.inbox.length;
  $("#n-drafts").textContent = mail.drafts.length;
  $("#n-sent").textContent = mail.sent.length;
  renderMailList();
}

function renderMailList() {
  const items = mailState ? mailState[activeTab] : [];
  $("#mail-list").innerHTML = items.length
    ? items.map((m) => {
        const who = m.frm || `收件人：${m.to}`;
        const selfTag = m.self_sent ? " · ✋本人发送" : "";
        const att = m.attachments && m.attachments.length
          ? ` · 📎 ${m.attachments.length} 个附件` : "";
        return `<div class="mail-item${m.id === activeMailId ? " active" : ""}" data-id="${m.id}">
          <div class="subj">${m.subject}</div>
          <div class="from">${who}${att}${selfTag}</div>
        </div>`;
      }).join("")
    : `<div class="detail-empty" style="margin-top:10px">（${tabName(activeTab)}为空）</div>`;
}

function tabName(t) {
  return { inbox: "收件箱", drafts: "草稿", sent: "已发送" }[t];
}

function esc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;")
    .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

function showMailDetail(id) {
  if (!mailState) return;
  const item = mailState[activeTab].find((m) => m.id === id);
  if (!item) return;
  activeMailId = id;
  renderMailList();
  const who = item.frm || item.to;
  const atts = (item.attachments || []).length
    ? `<div class="detail-kv">附件（${item.attachments.length}）</div>
       <div class="detail-atts">${item.attachments.map((a) => `<span class="file">${a}</span>`).join("")}</div>`
    : "";
  const selfTag = item.self_sent ? `（由用户自主修改后发送 · 路径 B）` : "";
  $("#mail-detail").innerHTML = `
    <div class="detail-head">${esc(item.subject)}</div>
    <div class="detail-kv">${item.frm ? "发件人" : "收件人"}：<b>${esc(who)}</b>${selfTag}</div>
    ${atts}
    <div class="detail-body">${esc(item.body)}</div>`;
}

function switchTab(t) {
  activeTab = t;
  activeMailId = null;
  document.querySelectorAll(".tab").forEach((el) =>
    el.classList.toggle("active", el.dataset.tab === t));
  renderMailList();
  $("#mail-detail").innerHTML = `<div class="detail-empty">点击邮件查看详情</div>`;
}

/* ---------------- P1：路径 B 自主编辑发送 ---------------- */
function activateSelfEdit(draft) {
  switchTab("drafts");
  $("#mail-detail").innerHTML = `
    <div class="detail-head">✏️ 自主编辑草稿（路径 B · P1）</div>
    <div class="mail-form">
      <label>收件人</label>
      <input id="ed-to" value="${esc(draft.to)}">
      <label>主题</label>
      <input id="ed-subject" value="${esc(draft.subject)}">
      <label>正文</label>
      <textarea id="ed-body">${esc(draft.body)}</textarea>
      <div class="kv-mini">附件 ${draft.attachments.length} 个将随草稿一起发送</div>
      <button class="btn primary" id="ed-send">发送（由你亲自发送）</button>
    </div>`;
  $("#ed-send").onclick = () => {
    const payload = {
      to: $("#ed-to").value.trim(),
      subject: $("#ed-subject").value,
      body: $("#ed-body").value,
    };
    $("#ed-send").disabled = true;
    $("#ed-send").textContent = "已发送…";
    post("/api/mail/send", payload);
    toast("已发送，助手将自动检测并继续收尾");
  };
}

/* ---------------- 卡片 ---------------- */
function addPlanCard(m, auto) {
  const tmpl = m.template === "ARCHIVE" ? "仅整理归档（第 2 类模板 · 不发送）"
    : "整理汇总并发送（标准模板）";
  const title = auto ? "执行计划（信任递进 · 已自动确认，P1）" : "执行计划（N2 · 请确认）";
  const btns = auto ? "" : `
    <div class="btn-row">
      <button class="btn primary" data-act="ok">确认执行</button>
      <button class="btn ghost" data-act="cancel">取消任务</button>
    </div>`;
  const card = document.createElement("div");
  card.className = "card";
  card.innerHTML = `
    <div class="card-title">${title}</div>
    <div class="kv">模板：<b>${tmpl}</b>${m.recipient ? ` · 收件人：<b>${esc(m.recipient)}</b>` : ""} · 共 ${m.steps.length} 步</div>
    <table>
      <thead><tr><th>#</th><th>步骤</th><th>完成断言</th></tr></thead>
      <tbody>
        ${m.steps.map((s) => `<tr><td>${s.id}</td><td>${s.name}</td><td>${s.assertion}</td></tr>`).join("")}
      </tbody>
    </table>
    ${btns}`;
  card.querySelectorAll("button").forEach((b) => {
    b.onclick = () => {
      card.querySelectorAll("button").forEach((x) => (x.disabled = true));
      post("/api/plan", { agree: b.dataset.act === "ok" });
      if (b.dataset.act === "ok") b.classList.add("done");
    };
  });
  $("#chat").appendChild(card);
  scrollChat();
}

function addGateCard(m) {
  const card = document.createElement("div");
  card.className = "card";
  card.innerHTML = `
    <div class="card-title">发送闸门（N3 · 逐项核对）</div>
    <div class="kv">收件人：<b>${esc(m.to)}</b></div>
    <div class="kv">主题：${esc(m.subject)}</div>
    <div class="kv">附件（${m.attachments.length} 个）：</div>
    <div class="attach-list">${m.attachments.map(esc).join("\n")}</div>
    <pre>${esc(m.body)}</pre>
    <div class="btn-row">
      <button class="btn primary" data-act="send">确认发送（助手代发 · 路径 A）</button>
      <button class="btn ghost" data-act="self">我要自己改（路径 B · P1）</button>
    </div>`;
  card.querySelectorAll("button").forEach((b) => {
    b.onclick = () => {
      card.querySelectorAll("button").forEach((x) => (x.disabled = true));
      if (b.dataset.act === "send") {
        b.classList.add("done");
        b.textContent = "已确认，正在发送…";
        post("/api/gate", { mode: "send" });
      } else {
        b.textContent = "已转交草稿，请在右侧编辑…";
        post("/api/gate", { mode: "self" });
      }
    };
  });
  $("#chat").appendChild(card);
  scrollChat();
}

function addHelpCard() {
  const card = document.createElement("div");
  card.className = "card";
  card.innerHTML = `
    <div class="card-title">异常求助（N4 · 请选择处理方式）</div>
    <div class="kv">原件与隔离备份均完好，最坏情况只损失时间。</div>
    <div class="btn-row">
      <button class="btn primary" data-act="degrade">降级：跳过损坏文件继续</button>
      <button class="btn ghost" data-act="abort">安全中止</button>
    </div>`;
  card.querySelectorAll("button").forEach((b) => {
    b.onclick = () => {
      card.querySelectorAll("button").forEach((x) => (x.disabled = true));
      b.classList.add("done");
      post("/api/help", { choice: b.dataset.act });
    };
  });
  $("#chat").appendChild(card);
  scrollChat();
}

function addReportCard(m) {
  const card = document.createElement("div");
  card.className = "card";
  card.innerHTML = `
    <div class="card-title">任务完成 · 结果汇报</div>
    <div class="kv">${esc(m.text)}</div>
    <div class="btn-row">
      <button class="btn" data-act="table">查看汇总表</button>
      <button class="btn" data-act="mail">查看已发送邮件</button>
    </div>
    <div class="btn-row">
      <button class="btn ghost" data-act="good">👍 满意</button>
      <button class="btn ghost" data-act="bad">👎 不满意</button>
    </div>`;
  card.querySelectorAll("button").forEach((b) => {
    b.onclick = () => {
      const act = b.dataset.act;
      if (act === "table") {
        openSummaryModal(m.table, m.summary_name);
      } else if (act === "mail") {
        switchTab("sent");
        if (mailState && mailState.sent.length) {
          showMailDetail(mailState.sent[mailState.sent.length - 1].id);
        }
      } else {
        card.querySelectorAll("[data-act=good],[data-act=bad]").forEach((x) => (x.disabled = true));
        b.classList.add("done");
        post("/api/feedback", { kind: act });
      }
    };
  });
  $("#chat").appendChild(card);
  scrollChat();
}

function addStatsCard(m) {
  const trustLine = (m.trust != null && m.template === "ARCHIVE")
    ? ` · 信任递进：归档类任务累计成功 <b>${m.trust} 次</b>${m.trust >= 3 ? "（下次 N2 自动确认）" : "（满 3 次后 N2 免确认）"}` : "";
  const card = document.createElement("div");
  card.className = "card";
  card.innerHTML = `
    <div class="card-title">执行留痕 · 本次任务统计</div>
    <div class="stat-line">总耗时 <b>${m.duration_s}s</b> · ${m.steps} 步 ·
      用户干预 <b>${m.interventions} 次</b>${trustLine}</div>
    <table>
      <thead><tr><th>#</th><th>步骤</th><th>断言</th><th>结果</th><th>耗时</th></tr></thead>
      <tbody>
        ${m.record.map((r) =>
          `<tr><td>${r.step}</td><td>${esc(r.action)}</td><td>${esc(r.assertion)}</td><td>${r.result}</td><td>${r.ms}ms</td></tr>`
        ).join("")}
      </tbody>
    </table>`;
  $("#chat").appendChild(card);
  scrollChat();
}

/* ---------------- 汇总表弹窗 ---------------- */
function openSummaryModal(rows, name) {
  $("#modal-title").textContent = `📊 ${name}（${rows.length} 行）`;
  $("#modal-body").innerHTML = `
    <table>
      <thead><tr><th>日期</th><th>对方单位</th><th>金额</th><th>源文件</th></tr></thead>
      <tbody>
        ${rows.map((r) =>
          `<tr><td class="num">${r["日期"]}</td><td>${r["对方单位"]}</td>
           <td class="num">¥${Number(r["金额"]).toLocaleString()}</td>
           <td class="num">${r["文件名"]}</td></tr>`).join("")}
      </tbody>
    </table>`;
  $("#modal").classList.add("open");
}

/* ---------------- P1：授权弹窗 ---------------- */
function showAuthModal() {
  $("#auth-modal").classList.add("open");
}

/* ---------------- 快捷回复 / 输入 ---------------- */
function showQuick(quick) {
  const q = $("#quick");
  q.innerHTML = "";
  const list = Array.isArray(quick) ? quick : [quick];
  list.forEach((text) => {
    const b = document.createElement("button");
    b.className = "chip";
    b.textContent = text;
    b.onclick = () => {
      addUserMsg(text);
      post("/api/answer", { text });
      hideQuick();
      awaitingAnswer = false;
      setInputMode("busy");
    };
    q.appendChild(b);
  });
  q.classList.add("show");
}

function hideQuick() {
  const q = $("#quick");
  q.classList.remove("show");
  q.innerHTML = "";
}

function setInputMode(mode) {
  const input = $("#input"), send = $("#send");
  if (mode === "idle") {
    input.disabled = false; send.disabled = false;
    input.placeholder = "输入一句话指令…";
    $("#preset").style.display = "flex";
  } else if (mode === "answer") {
    input.disabled = false; send.disabled = false;
    input.placeholder = "输入回复（或点击上方快捷回复）…";
    $("#preset").style.display = "none";
  } else {
    input.disabled = true; send.disabled = true;
    input.placeholder = "任务执行中，可随时暂停 / 加速…";
    input.value = "";
    $("#preset").style.display = "none";
  }
}

function sendInput() {
  const input = $("#input");
  const v = input.value.trim();
  if (!v) return;
  if (!started) {
    addUserMsg(v);
    post("/api/command", { text: v });
    started = true;
    setInputMode("busy");
  } else if (awaitingAnswer) {
    addUserMsg(v);
    post("/api/answer", { text: v });
    awaitingAnswer = false;
    hideQuick();
    setInputMode("busy");
  }
  input.value = "";
}

/* ---------------- Toast / 故障注入 ---------------- */
let toastTimer = null;
function toast(text) {
  const t = $("#toast");
  t.textContent = text;
  t.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove("show"), 2500);
}

function setInjectUI(on) {
  injectOn = on;
  const b = $("#btn-inject");
  if (!b) return;
  b.textContent = on ? "故障注入：开" : "故障注入：关";
  b.classList.toggle("active", on);
}

/* ---------------- 初始化 ---------------- */
function init() {
  connect();

  $("#send").onclick = sendInput;
  $("#input").addEventListener("keydown", (e) => {
    if (e.key === "Enter") sendInput();
  });

  $("#preset-cmd").onclick = () => {
    $("#input").value = $("#preset-cmd").textContent;
    $("#input").focus();
  };

  $("#btn-pause").onclick = () => {
    const btn = $("#btn-pause");
    const paused = btn.classList.toggle("active");
    btn.textContent = paused ? "继续" : "暂停";
    post("/api/control", { action: paused ? "pause" : "resume" });
  };

  $("#btn-speed").onclick = () => {
    const btn = $("#btn-speed");
    const fast = btn.classList.toggle("active");
    btn.textContent = fast ? "常速 ×1" : "加速 ×3";
    post("/api/control", { action: "speed" });
  };

  $("#btn-inject").onclick = () => {   // P1：故障注入开关
    const on = !injectOn;
    setInjectUI(on);
    post("/api/inject", { on });
    toast(on ? "故障注入已开启：下一次任务将模拟 1 个损坏文件" : "故障注入已关闭");
  };

  $("#btn-reset").onclick = () => post("/api/reset");

  $("#auth-allow").onclick = () => {   // P1：通讯录授权
    $("#auth-modal").classList.remove("open");
    post("/api/auth", { grant: true });
  };
  $("#auth-deny").onclick = () => {
    $("#auth-modal").classList.remove("open");
    post("/api/auth", { grant: false });
  };

  document.querySelectorAll(".tab").forEach((el) => {
    el.onclick = () => switchTab(el.dataset.tab);
  });

  $("#mail-list").addEventListener("click", (e) => {
    const item = e.target.closest(".mail-item");
    if (item) showMailDetail(Number(item.dataset.id));
  });

  $("#modal-close").onclick = () => $("#modal").classList.remove("open");
  $("#modal").addEventListener("click", (e) => {
    if (e.target.id === "modal") $("#modal").classList.remove("open");
  });

  setInputMode("idle");
}

init();
