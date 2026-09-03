// Admin Mini App: weeks content, participants, weekly summary, facts, audit log.
(async function () {
  const RM = window.RM;
  const esc = RM.escape;
  const $ = (id) => document.getElementById(id);
  const fail = (message) => { $("error").textContent = message; $("error").hidden = false; $("subtitle").textContent = ""; };

  await RM.openSession();
  let me;
  try { me = await RM.api("/api/me"); } catch (e) { return fail(e.status === 401 ? "Открой админку из бота." : e.message); }
  if (!me.is_admin) return fail("Эта страница только для Милы.");

  let weeks = [], catalogue = [], participants = [];
  try {
    weeks = await RM.api("/api/admin/weeks");
    catalogue = await RM.api("/api/admin/achievement-types");
  } catch (e) { return fail(e.status === 404 ? "Активного сезона нет." : e.message); }
  $("subtitle").textContent = `${weeks.length} недель · ${catalogue.length} ачивок в каталоге`;
  $("tabs").hidden = false;
  RM.tabs($("tabs"), (tab) => { if (tab === "people") loadPeople(); if (tab === "summary") loadSummary(); if (tab === "facts") loadFacts(); if (tab === "audit") loadAudit(); });
  renderWeeks();
  $("weeks").hidden = false;

  const FIELDS = [["title", "Название"], ["intro", "Вступление"], ["task_min", "Минимум"], ["task_max", "Максимум"], ["word", "Слово"], ["word_ru", "Произношение"], ["word_meaning", "Значение слова"]];

  function renderWeeks() {
    $("weeks").innerHTML = weeks.map((w) => `
      <details class="card" ${w.state === "current" ? "open" : ""}>
        <summary><b>${w.number}. ${esc(w.title)}</b> <span class="muted">· ${w.starts_on}–${w.ends_on}${w.state === "current" ? " · идёт" : w.state === "locked" ? " · 🔒" : " · прошла"}</span></summary>
        <form class="stack" data-week="${w.id}">
          ${FIELDS.map(([f, label]) => `<label>${label}${f === "intro" || f === "task_min" || f === "task_max" || f === "word_meaning" ? `<textarea name="${f}">${esc(w[f])}</textarea>` : `<input name="${f}" value="${esc(w[f])}">`}</label>`).join("")}
          <div class="row"><button class="btn small" type="submit" ${w.state === "stamped" ? "disabled title='Прошедшие недели не меняем'" : ""}>Сохранить</button></div>
        </form>
      </details>`).join("");
    $("weeks").querySelectorAll("form").forEach((form) => form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const week = weeks.find((w) => String(w.id) === form.dataset.week);
      const body = {};
      FIELDS.forEach(([f]) => { const v = form.elements[f].value; if (v !== week[f]) body[f] = v; });
      if (!Object.keys(body).length) return RM.toast("Ничего не изменилось");
      try {
        const updated = await RM.api(`/api/admin/weeks/${week.id}`, { method: "PUT", body });
        Object.assign(week, updated);
        RM.toast("Сохранила");
      } catch (e) { RM.toast("Не сохранилось: " + e.message); }
    }));
  }

  async function loadPeople() {
    try { participants = await RM.api("/api/admin/participants"); } catch (e) { return RM.toast(e.message); }
    $("people").innerHTML = `<table class="grid"><thead><tr><th>Кто</th><th>Штампы</th><th>Статус</th><th>Цепочка</th></tr></thead><tbody>` +
      participants.map((p) => `<tr data-id="${p.id}" style="cursor:pointer"><td>${esc(name(p))}</td><td>${p.stamps}${p.stamps_max ? " ⭐" + p.stamps_max : ""}</td><td>${esc(RM.levelName[p.level] || "—")}</td><td>${p.current_streak} / ${p.best_streak}</td></tr>`).join("") +
      `</tbody></table><div id="person"></div>`;
    $("people").querySelectorAll("tr[data-id]").forEach((tr) => tr.addEventListener("click", () => openPerson(+tr.dataset.id)));
  }

  function name(p) { return [p.first_name, p.last_name].filter(Boolean).join(" ") + (p.username ? " (@" + p.username + ")" : "") || String(p.id); }

  async function openPerson(id) {
    let d;
    try { d = await RM.api(`/api/admin/participants/${id}`); } catch (e) { return RM.toast(e.message); }
    const box = $("person");
    box.innerHTML = `<div class="card">
      <h2>${esc(name(d.user))}</h2>
      <p class="muted">${d.passport.stamps} штампов · ${esc(RM.levelName[d.passport.level] || "ещё в пути")} · заморозок ${d.passport.freezes_left}/${d.passport.freezes_total}</p>
      <h3>Штампы</h3>
      <div class="stampbar">${d.weeks.map((w) => `<button data-week="${w.number}" class="${w.level || ""}" title="${esc(w.title)}">${w.number} ${w.state === "stamped" ? (w.level === "max" ? "⭐" : "✅") : (RM.stateMark[w.state] || "·")}</button>`).join("")}</div>
      <p class="note">Нажатие переключает: нет → минимум → максимум → нет.</p>
      <h3>Заморозка</h3>
      <div class="row"><select id="freeze-reason"><option value="comment">за комментарий</option><option value="meetup">за встречу</option><option value="friend">за друга</option><option value="manual">просто так</option></select><button class="btn small" id="freeze-btn">Дать</button></div>
      <h3>Ачивка</h3>
      <div class="row"><select id="badge-code">${catalogue.map((c) => `<option value="${esc(c.code)}">${esc(c.label)}</option>`).join("")}</select><input id="badge-free" placeholder="или своя, текстом"><button class="btn small" id="badge-btn">Выдать</button></div>
      <div class="chips">${d.achievements.map((a) => `<span class="chip">${esc(a)}</span>`).join("")}</div>
      <h3>Пожелание в журнал</h3>
      <div class="row"><textarea id="wish" style="flex:1">${esc(d.wish || "")}</textarea></div><div class="row"><button class="btn small" id="wish-btn">Сохранить</button></div>
      <h3>Отчёты</h3>
      ${d.reports.map((r) => `<article class="report"><div class="meta">${r.week_number ? "Неделя " + r.week_number : "вне недели"} · ${r.created_at.slice(0, 16).replace("T", " ")} · ${r.kind} · ${r.level}</div>${r.text ? `<div>${esc(r.text)}</div>` : ""}${r.media.map((m) => m.mime && m.mime.startsWith("image/") && m.downloaded ? `<img src="${m.url}" alt="" loading="lazy">` : (m.downloaded ? `<a class="btn ghost small" href="${m.url}">файл</a>` : "<span class='muted'>файл ещё не скачан</span>")).join("")}</article>`).join("") || '<p class="muted">Отчётов нет.</p>'}
    </div>`;
    box.scrollIntoView({ behavior: "smooth" });
    box.querySelectorAll(".stampbar button").forEach((b) => b.addEventListener("click", async () => {
      const week = d.weeks.find((w) => String(w.number) === b.dataset.week);
      const next = week.state !== "stamped" ? "min" : week.level === "min" ? "max" : null;
      try {
        await RM.api(`/api/admin/participants/${id}/stamps/${week.number}`, { method: "PUT", body: { level: next } });
        RM.toast(next ? "Штамп: " + next : "Штамп снят");
        openPerson(id);
      } catch (e) { RM.toast(e.message); }
    }));
    $("freeze-btn").addEventListener("click", async () => {
      try { const r = await RM.api(`/api/admin/participants/${id}/freezes`, { method: "POST", body: { reason: $("freeze-reason").value } }); RM.toast(r.granted ? "Выдала, всего " + r.freezes_total : "Уже потолок"); openPerson(id); } catch (e) { RM.toast(e.message); }
    });
    $("badge-btn").addEventListener("click", async () => {
      const code = $("badge-free").value.trim() || $("badge-code").value;
      try { const r = await RM.api(`/api/admin/participants/${id}/achievements`, { method: "POST", body: { code_or_text: code } }); RM.toast(r.created ? "Выдала " + r.label : "Такая уже есть"); openPerson(id); } catch (e) { RM.toast(e.message); }
    });
    $("wish-btn").addEventListener("click", async () => {
      try { await RM.api(`/api/admin/participants/${id}/wish`, { method: "PUT", body: { text: $("wish").value } }); RM.toast("Записала"); } catch (e) { RM.toast(e.message); }
    });
  }

  async function loadSummary(week) {
    let s;
    try { s = await RM.api("/api/admin/summary" + (week ? "?week=" + week : "")); } catch (e) { $("summary").innerHTML = `<p class="muted">${esc(e.message)}</p>` + weekPicker(); bindPicker(); return; }
    $("summary").innerHTML = weekPicker(s.week_number) + `<div class="card">
      <h2>Неделя ${s.week_number} · ${esc(s.week_title)}</h2>
      <p class="muted">В боте людей: ${s.members_total} · отчётов: ${s.reports_total} · ядро: ${s.core_best} (в строю ${s.core_current})</p>
      <p><b>Взялись (${s.took.length}):</b> ${s.took_names.map(esc).join(", ") || "пока никто"}</p>
      <p><b>Сдали (${s.submitted.length}):</b> ${s.submitted.map((x) => (x.level === "max" ? "⭐ " : "✅ ") + esc(x.name)).join(", ") || "пока никто"}</p>
      <p><b>Взялись, но не прислали:</b> ${s.took_not_submitted_names.map(esc).join(", ") || "—"}</p>
      <h3>Черновик «Привала»</h3><pre class="draft">${esc(s.draft_post)}</pre></div>`;
    bindPicker();
  }
  function weekPicker(selected) { return `<div class="row"><label>Неделя <select id="week-pick">${weeks.map((w) => `<option value="${w.number}" ${w.number === selected ? "selected" : ""}>${w.number}. ${esc(w.title)}</option>`).join("")}</select></label></div>`; }
  function bindPicker() { const el = $("week-pick"); if (el) el.addEventListener("change", () => loadSummary(el.value)); }

  async function loadFacts() {
    let facts;
    try { facts = await RM.api("/api/admin/facts"); } catch (e) { return RM.toast(e.message); }
    $("facts").innerHTML = `<form class="row" id="fact-form"><input id="fact-text" placeholder="Новый факт про страну" style="flex:1"><button class="btn small">Записать</button></form>` +
      (facts.length ? `<ul class="weeklist">${facts.map((f) => `<li><span class="mark">💡</span><span><div>${esc(f.text)}</div><div class="sub">${f.author_name ? esc(f.author_name) : "Мила"} · ${f.created_at.slice(0, 10)}</div></span><button class="btn ghost small" data-del="${f.id}">убрать</button></li>`).join("")}</ul>` : '<p class="muted">Фактов пока нет.</p>');
    $("fact-form").addEventListener("submit", async (e) => { e.preventDefault(); const text = $("fact-text").value.trim(); if (!text) return; try { await RM.api("/api/admin/facts", { method: "POST", body: { text } }); loadFacts(); } catch (err) { RM.toast(err.message); } });
    $("facts").querySelectorAll("[data-del]").forEach((b) => b.addEventListener("click", async () => { try { await RM.api(`/api/admin/facts/${b.dataset.del}`, { method: "DELETE" }); loadFacts(); } catch (err) { RM.toast(err.message); } }));
  }

  async function loadAudit() {
    let rows;
    try { rows = await RM.api("/api/admin/audit?limit=100"); } catch (e) { return RM.toast(e.message); }
    $("audit").innerHTML = rows.length ? `<table class="grid"><thead><tr><th>Когда</th><th>Что</th><th>Было → стало</th></tr></thead><tbody>${rows.map((r) => `<tr><td>${r.created_at.slice(0, 16).replace("T", " ")}</td><td>${esc(r.entity)} ${esc(r.entity_id || "")}<br><span class="muted">${esc(r.action)}</span></td><td><span class="muted">${esc(JSON.stringify(r.before))}</span><br>${esc(JSON.stringify(r.after))}</td></tr>`).join("")}</tbody></table>` : '<p class="muted">Изменений пока нет.</p>';
  }
})();
