// Participant Mini App: the whole bot on one screen set — task and intent, reports with photos,
// passport, journal with PDF, dictionary, facts, a letter to Mila, help. Rules and texts come
// from the API (the same services and `texts/ru.py` the bot uses); this file only draws.
(function () {
  const RM = window.RM;
  const esc = RM.escape, html = RM.html, fmt = RM.fmtDate;
  const $ = (id) => document.getElementById(id);
  const app = $("app"), screen = $("screen"), tabbar = $("tabbar");
  const state = { tab: app.dataset.tab || "today", home: null, journal: null, dictionary: null, facts: null, files: [], sent: null };

  boot();

  async function boot() {
    await RM.openSession();
    try {
      state.home = await RM.api("/api/home");
    } catch (e) {
      return fatal(e);
    }
    tabbar.hidden = false;
    tabbar.querySelectorAll("button").forEach((b) => b.addEventListener("click", () => go(b.dataset.tab)));
    $("sheet-close").addEventListener("click", closeSheet);
    $("sheet").addEventListener("click", (e) => { if (e.target === $("sheet")) closeSheet(); });
    go(state.tab);
  }

  function fatal(e) {
    const bot = app.dataset.bot;
    let text, hint = "";
    if (e.status === 401) {
      text = "Открой приложение из бота";
      hint = "Telegram передаёт, кто ты, только внутри самого Telegram: нажми кнопку «Открыть» в чате с ботом" + (bot ? ` <a href="https://t.me/${esc(bot)}">@${esc(bot)}</a>` : "") + ".";
    } else if (e.status === 404) {
      text = "Сезон ещё не начался";
      hint = "Как только рандомайзер выберет страну, здесь появится задание.";
    } else {
      text = "Не получилось загрузить";
      hint = esc(e.message) + ". Попробуй закрыть и открыть приложение ещё раз.";
    }
    screen.innerHTML = `<div class="empty"><div class="big">🧭</div><h2>${text}</h2><p class="muted">${hint}</p></div>`;
  }

  function go(tab) {
    state.tab = tab;
    tabbar.querySelectorAll("button").forEach((b) => b.classList.toggle("active", b.dataset.tab === tab));
    window.scrollTo(0, 0);
    RM.haptic("light");
    render();
  }

  async function refreshHome() {
    try { state.home = await RM.api("/api/home"); } catch (e) { /* keep what we have */ }
  }

  function render() {
    closeSheet();
    ({ today: renderToday, passport: renderPassport, journal: renderJournal, words: renderWords, more: renderMore })[state.tab]();
  }

  // --- Сегодня -------------------------------------------------------------------------

  function renderToday() {
    const h = state.home, w = h.week, t = h.today;
    const dateTitle = new Date(t.date + "T12:00:00").toLocaleDateString("ru-RU", { day: "numeric", month: "long", weekday: "long" });
    const status = w ? `Неделя ${w.number} из ${h.passport.weeks_total} · дедлайн ${esc(w.deadline)}` : h.next_week_starts_on ? `Между неделями · следующая с ${fmt(h.next_week_starts_on)}` : "Сезон завершён";
    let out = `<header class="screen-head"><p class="eyebrow">Романтика маршрутов · ${esc(h.season.title)}</p><h1>${esc(capital(dateTitle))}</h1><p class="muted">${status}</p></header>`;

    if (w) {
      out += `<div class="card current">
        <p class="eyebrow">Задание недели</p>
        <h2>${w.number}. ${esc(w.title)}</h2>
        ${w.intro ? `<p>${esc(w.intro)}</p>` : ""}
        <div class="kv">
          <div><div class="k">Минимум ✅ · на пять минут</div><div class="v">${esc(w.task_min)}</div></div>
          ${w.task_max ? `<div><div class="k">Максимум ⭐ · на вечер</div><div class="v">${esc(w.task_max)}</div></div>` : ""}
        </div>
        ${w.word ? `<div class="divider"></div><div class="k" style="font-size:12px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted)">Слово недели</div><div class="wordline">${esc(w.word)}${w.word_ru ? ` <span class="ru">· ${esc(w.word_ru)}</span>` : ""}</div>${w.word_meaning ? `<div class="muted"><i>${esc(w.word_meaning)}</i></div>` : ""}` : ""}
        <h3>Берёшься?</h3>
        <div class="segment" id="intent">${["take", "try", "skip"].map((c) => `<button data-choice="${c}" class="${w.intent === c ? "active" : ""}">${RM.intentName[c]}</button>`).join("")}</div>
        <p class="note" id="intent-note">${w.intent ? intentNote(w.intent) : "Напоминания приходят только тем, кто нажал «Берусь» или «Попробую»."}</p>
      </div>`;
      out += `<div class="card composer" id="composer">${composerHtml(w)}</div>`;
    } else {
      out += `<div class="card"><h2>Сейчас неделя не идёт</h2><p class="muted">${h.next_week_starts_on ? `Ближайшее задание откроется ${fmt(h.next_week_starts_on)}, в понедельник.` : "Сезон завершён — спасибо, что был в нём."}</p></div>`;
      out += `<div class="card composer" id="composer">${composerHtml(null)}</div>`;
    }

    out += dayCard(t);
    screen.innerHTML = out;

    if (w) bindIntent(w);
    bindComposer(w);
  }

  function capital(s) { return s.charAt(0).toUpperCase() + s.slice(1); }

  function dayCard(t) {
    if (!t.tzolkin && !t.word && !t.memory) return "";
    const tz = t.tzolkin;
    return `<div class="card day tight">
      ${tz ? `<div class="row between"><b>🌤 ${tz.number} ${esc(tz.sign_name)} ${esc(tz.sign_symbol)}</b>${t.calendar_url ? `<a class="btn link small" href="${esc(t.calendar_url)}" id="calendar-link">Календарь →</a>` : ""}</div><p class="advice">${esc(tz.day_advice)}</p>` : ""}
      ${t.word ? `<div class="kv"><div><div class="k">Слово недели</div><div class="wordline">${esc(t.word.word)}${t.word.word_ru ? ` <span class="ru">· ${esc(t.word.word_ru)}</span>` : ""}</div>${t.word.meaning ? `<div class="muted"><i>${esc(t.word.meaning)}</i></div>` : ""}</div></div>` : ""}
      ${t.memory ? `<div class="kv" style="margin-top:8px"><div><div class="k">А помнишь?</div><div class="wordline">${esc(t.memory.word)}${t.memory.word_ru ? ` <span class="ru">· ${esc(t.memory.word_ru)}</span>` : ""}</div>${t.memory.meaning ? `<div class="muted"><i>${esc(t.memory.meaning)}</i></div>` : ""}</div></div>` : ""}
      ${t.note ? `<p class="note" style="margin:10px 0 0"><i>${esc(t.note)}</i></p>` : ""}
    </div>`;
  }

  function intentNote(choice) {
    return { take: "Записала: берёшься 💪 Как сделаешь — пришли отчёт ниже.", try: "Записала: попробуешь. Даже минимум на пять минут — полноценный штамп.", skip: "Хорошо, неделя может не задаться. Напоминаний не будет." }[choice];
  }

  function bindIntent(w) {
    $("intent").querySelectorAll("button").forEach((b) => b.addEventListener("click", async () => {
      const choice = b.dataset.choice;
      $("intent").querySelectorAll("button").forEach((x) => (x.disabled = true));
      try {
        const r = await RM.api("/api/intent", { method: "POST", body: { week_number: w.number, choice } });
        w.intent = choice;
        $("intent").querySelectorAll("button").forEach((x) => { x.classList.toggle("active", x.dataset.choice === choice); x.disabled = false; });
        $("intent-note").textContent = intentNote(choice);
        RM.haptic("success");
        RM.toast(r.hint.split("\n")[0]);
      } catch (e) {
        $("intent").querySelectorAll("button").forEach((x) => (x.disabled = false));
        RM.toast("Не записалось: " + e.message);
      }
    }));
  }

  function stampChip(w) {
    if (!w) return "";
    if (w.level === "max") return `<span class="chip star">⭐ максимум</span>`;
    if (w.level === "min") return `<span class="chip ok">✅ минимум</span>`;
    return `<span class="chip">пока без штампа</span>`;
  }

  function composerHtml(w) {
    const title = w ? "Сдать отчёт" : "Написать Миле";
    const note = w
      ? "Текст засчитается как минимум ✅, фото или видео — как максимум ⭐. Даже одно слово — уже отчёт, а дослать можно сколько угодно раз."
      : "Штамп сейчас не ставится, но сообщение сохранится и уйдёт Миле.";
    return `<div class="row between"><h2 style="margin:0">${title}</h2>${stampChip(w)}</div>
      <p class="note">${note}</p>
      <textarea id="report-text" placeholder="${w ? "Что сделал на этой неделе?" : "Что хочешь сказать?"}"></textarea>
      <div class="attach"><label class="btn soft small" for="report-files">📷 Фото или видео</label><input id="report-files" type="file" accept="image/*,video/*" multiple><span class="muted small" id="files-count"></span></div>
      <div class="previews" id="previews" hidden></div>
      <div class="bar" id="bar" hidden><i></i></div>
      <button class="btn block" id="send" style="margin-top:12px">Отправить</button>`;
  }

  function bindComposer(w) {
    state.files = [];
    const input = $("report-files");
    input.addEventListener("change", () => {
      for (const f of input.files) if (state.files.length < 10) state.files.push(f);
      input.value = "";
      renderPreviews();
    });
    $("send").addEventListener("click", () => sendReport(w));
  }

  function renderPreviews() {
    const box = $("previews");
    box.hidden = state.files.length === 0;
    $("files-count").textContent = state.files.length ? `${state.files.length} ${RM.plural(state.files.length, "файл", "файла", "файлов")}` : "";
    box.innerHTML = state.files.map((f, i) => {
      const url = URL.createObjectURL(f);
      const media = f.type.startsWith("image/") ? `<img src="${url}" alt="">` : f.type.startsWith("video/") ? `<video src="${url}" muted></video>` : esc(f.name);
      return `<div class="pv">${media}<button class="x" data-i="${i}" aria-label="Убрать">✕</button></div>`;
    }).join("");
    box.querySelectorAll(".x").forEach((b) => b.addEventListener("click", () => { state.files.splice(+b.dataset.i, 1); renderPreviews(); }));
  }

  async function sendReport(w) {
    const text = $("report-text").value.trim();
    if (!text && !state.files.length) return RM.toast("Напиши хотя бы слово или добавь фото");
    const button = $("send"), bar = $("bar");
    button.disabled = true;
    button.textContent = "Отправляю…";
    const form = new FormData();
    form.append("text", text);
    state.files.forEach((f) => form.append("files", f, f.name));
    if (state.files.length) bar.hidden = false;
    try {
      const r = await RM.upload("/api/reports", form, (p) => { bar.querySelector("i").style.width = Math.round(p * 100) + "%"; });
      RM.haptic("success");
      state.sent = r;
      await refreshHome();
      showResult(r);
    } catch (e) {
      RM.haptic("error");
      button.disabled = false;
      button.textContent = "Отправить";
      bar.hidden = true;
      RM.toast("Не отправилось: " + e.message, 4000);
    }
  }

  function showResult(r) {
    const box = $("composer");
    const w = state.home.week;
    const other = r.stamp_level === "max" ? "min" : "max";
    box.innerHTML = `<div class="row between"><h2 style="margin:0">${r.out_of_week ? "Передала" : "Принято"}</h2>${stampChip(w)}</div>
      <div class="result ${r.out_of_week ? "" : "ok"}"><div class="rich">${html(r.message)}</div></div>
      <div class="row" style="margin-top:12px">
        ${!r.out_of_week ? `<button class="btn soft small" id="fix-level">Это был ${other === "max" ? "максимум" : "минимум"}</button>` : ""}
        <button class="btn ghost small" id="not-report">✉️ Это не отчёт, а сообщение Миле</button>
      </div>
      <button class="btn link" id="again" style="margin-top:8px">Отправить ещё</button>`;
    if ($("fix-level")) $("fix-level").addEventListener("click", async () => {
      try {
        const res = await RM.api(`/api/weeks/${r.week_number}/level`, { method: "POST", body: { level: other } });
        RM.alert(res.message.replace(/<[^>]+>/g, ""));
        if (res.ok) { r.stamp_level = res.stamp_level; await refreshHome(); showResult(r); }
      } catch (e) { RM.toast(e.message); }
    });
    $("not-report").addEventListener("click", async () => {
      try {
        const res = await RM.api(`/api/reports/${r.report_id}/cancel`, { method: "POST", body: {} });
        RM.alert(res.message.replace(/<[^>]+>/g, ""));
        await refreshHome();
        renderToday();
      } catch (e) { RM.toast(e.message); }
    });
    $("again").addEventListener("click", () => { box.innerHTML = composerHtml(w); bindComposer(w); });
  }

  // --- Паспорт -------------------------------------------------------------------------

  function renderPassport() {
    const h = state.home, p = h.passport;
    const level = RM.levelName[p.level] || "Ещё не в пути";
    let out = `<header class="screen-head"><p class="eyebrow">Паспорт сезона</p><h1>${esc(h.season.title)}</h1><p class="muted">${esc(h.user.first_name || "")} · ${fmt(h.season.starts_on)} — ${fmt(h.season.ends_on)}</p></header>
      <div class="tiles">
        <div class="tile"><div class="big">${p.stamps} <span class="muted">/ ${p.weeks_total}</span></div><div class="label">${RM.plural(p.stamps, "штамп", "штампа", "штампов")}${p.stamps_max ? ` · ⭐ ${p.stamps_max}` : ""}</div></div>
        <div class="tile"><div class="big">${esc(level)}</div><div class="label">статус</div></div>
        <div class="tile"><div class="big">${p.freezes_left} <span class="muted">/ ${p.freezes_total}</span></div><div class="label">заморозок осталось</div></div>
        <div class="tile"><div class="big">${p.current_streak}</div><div class="label">${RM.plural(p.current_streak, "неделя", "недели", "недель")} подряд · лучшая ${p.best_streak}</div></div>
      </div>
      <div class="card"><h3 style="margin-top:0">Недели</h3><div class="stamps">${h.weeks.map(stampHtml).join("")}</div>
        <p class="note" style="margin:10px 0 0">⭐ максимум · ✅ минимум · ❄️ пропуск закрыт заморозкой · 🔒 откроется в понедельник. Нажми на неделю — откроется задание.</p></div>`;
    if (h.achievements.length) out += `<div class="card"><h3 style="margin-top:0">Ачивки</h3><div class="chips">${h.achievements.map((a) => `<span class="chip star">${esc(a)}</span>`).join("")}</div><p class="note" style="margin:8px 0 0">Не за посещаемость, а за поступок. Останутся в журнале сезона.</p></div>`;
    out += `<div class="card"><h3 style="margin-top:0">Заморозки</h3>
      <p>Пропущенная неделя тратит одну заморозку, но цепочка не рвётся. Базовых две, накопить можно пять: +1 за своё слово в словарике, +1 за первый максимум, +1 от Милы за комментарий, встречу или приведённого друга.</p>
      ${p.freeze_reasons.length ? `<p class="muted small">Заработано: ${p.freeze_reasons.map((r) => esc(RM.freezeReason[r] || r)).join(", ")}.</p>` : ""}
      ${p.freezes_left === 0 ? `<p class="muted small">Заморозки кончились. Статус «Резидент» больше недоступен, но участие продолжается — это главное.</p>` : ""}
    </div>`;
    if (h.wish) out += `<div class="card accent"><h3 style="margin-top:0">От Милы</h3><p><i>${esc(h.wish)}</i></p></div>`;
    out += `<details class="card"><summary>Что будет в конце сезона</summary><div class="content helptext">${html(h.texts.end_of_season)}</div></details>`;
    screen.innerHTML = out;
    screen.querySelectorAll(".stamp").forEach((b) => b.addEventListener("click", () => openWeek(+b.dataset.n)));
  }

  function stampHtml(w) {
    const cls = w.state === "stamped" ? w.level : w.state;
    const mark = w.state === "stamped" ? (w.level === "max" ? "⭐" : "✅") : w.state === "current" ? "▸" : RM.stateMark[w.state] || "·";
    return `<button class="stamp ${cls}" data-n="${w.number}"><span class="n">${w.number}</span><span class="m">${mark}</span><span class="t">${esc(w.state === "locked" ? fmt(w.starts_on) : w.title)}</span></button>`;
  }

  function openWeek(n) {
    const w = state.home.weeks.find((x) => x.number === n);
    if (!w) return;
    const status = w.state === "locked" ? `Откроется ${fmt(w.starts_on)}` : w.state === "current" ? "Идёт сейчас" : w.state === "stamped" ? (w.level === "max" ? "⭐ Максимум" : "✅ Минимум") : w.state === "frozen" ? "❄️ Закрыта заморозкой — цепочка не порвалась" : w.state === "before_join" ? "Была до тебя" : "Пропущена";
    const body = w.state === "locked"
      ? `<p class="muted">${fmt(w.starts_on)} — ${fmt(w.ends_on)}</p><p>Задание появится в понедельник. Недели открываются по одной за раз.</p>`
      : `<p class="muted">${fmt(w.starts_on)} — ${fmt(w.ends_on)} · ${status}</p>
         ${w.intro ? `<p>${esc(w.intro)}</p>` : ""}
         <div class="kv"><div><div class="k">Минимум ✅</div><div class="v">${esc(w.task_min)}</div></div>${w.task_max ? `<div><div class="k">Максимум ⭐</div><div class="v">${esc(w.task_max)}</div></div>` : ""}</div>
         ${w.word ? `<div class="divider"></div><div class="wordline">${esc(w.word)}${w.word_ru ? ` <span class="ru">· ${esc(w.word_ru)}</span>` : ""}</div>${w.word_meaning ? `<div class="muted"><i>${esc(w.word_meaning)}</i></div>` : ""}` : ""}
         ${w.state === "current" ? `<button class="btn block" id="sheet-report" style="margin-top:14px">Сдать отчёт</button>` : ""}`;
    openSheet(`Неделя ${w.number} · ${w.title}`, body, () => { if ($("sheet-report")) $("sheet-report").addEventListener("click", () => go("today")); });
  }

  // --- Журнал --------------------------------------------------------------------------

  async function renderJournal() {
    screen.innerHTML = loading();
    try { state.journal = await RM.api("/api/journal"); } catch (e) { return (screen.innerHTML = errorBox(e)); }
    const j = state.journal, p = j.passport;
    const live = j.reports.filter((r) => r.week_number !== null);
    const letters = j.reports.filter((r) => r.week_number === null);
    const byWeek = new Map();
    live.forEach((r) => { if (!byWeek.has(r.week_number)) byWeek.set(r.week_number, []); byWeek.get(r.week_number).push(r); });
    const weeksDone = [...byWeek.keys()].sort((a, b) => b - a);
    let out = `<header class="screen-head"><p class="eyebrow">Мой журнал · ${esc(j.season.title)}</p><h1>${esc(j.user.first_name || "Журнал")}</h1><p class="muted">${weeksDone.length} ${RM.plural(weeksDone.length, "неделя", "недели", "недель")} из ${p.weeks_total} · ${esc(RM.levelName[p.level] || "ещё в пути")}</p></header>`;
    out += `<div class="card accent tight"><div class="row between"><div><b>Журнал в PDF</b><div class="muted small">Недели, фото, ачивки, словарь — одним файлом в бота.</div></div><button class="btn small" id="pdf">Собрать</button></div><p class="muted small" id="pdf-status" style="margin:6px 0 0"></p></div>`;
    if (!weeksDone.length) out += `<div class="empty"><div class="big">📔</div><h2>Пока пусто</h2><p class="muted">${esc(j.season.title)}: здесь появятся твои недели и твои же слова о них. ${esc(state.home.texts.journal_now)}</p></div>`;
    weeksDone.forEach((n) => {
      const week = j.weeks.find((w) => w.number === n) || { title: "" };
      const rs = byWeek.get(n);
      const level = week.level === "max" ? "⭐" : "✅";
      out += `<div class="card"><h2>${level} Неделя ${n} · ${esc(week.title)}</h2>${rs.map(reportHtml).join("")}</div>`;
    });
    if (letters.length) out += `<details class="card"><summary>Сообщения вне недель (${letters.length})</summary><div class="content">${letters.map(reportHtml).join("")}</div></details>`;
    screen.innerHTML = out;
    screen.querySelectorAll("[data-cancel]").forEach((b) => b.addEventListener("click", async () => {
      if (!confirm("Пометить как не отчёт? Штамп за неделю пересчитается, а текст уйдёт Миле как сообщение.")) return;
      try { const res = await RM.api(`/api/reports/${b.dataset.cancel}/cancel`, { method: "POST", body: {} }); RM.toast(res.message.replace(/<[^>]+>/g, "")); await refreshHome(); renderJournal(); } catch (e) { RM.toast(e.message); }
    }));
    $("pdf").addEventListener("click", requestPdf);
  }

  function reportHtml(r) {
    const images = r.media.filter((m) => m.mime && m.mime.startsWith("image/") && m.downloaded);
    const others = r.media.filter((m) => !images.includes(m));
    return `<article class="report">
      <div class="meta">${RM.fmtDateTime(r.created_at)} · ${r.level === "max" ? "⭐ максимум" : "✅ минимум"} · ${kindName(r.kind)}</div>
      ${r.text ? `<div class="text">${esc(r.text)}</div>` : ""}
      ${images.length ? `<div class="gallery">${images.map((m) => `<a href="${m.url}" target="_blank"><img src="${m.url}" alt="" loading="lazy"></a>`).join("")}</div>` : ""}
      ${others.map((m) => m.downloaded ? `<a class="btn ghost small" href="${m.url}" target="_blank" style="margin-top:8px">Открыть файл</a>` : `<span class="muted small">файл ещё скачивается</span>`).join(" ")}
      <button class="btn link small" data-cancel="${r.id}">Это не отчёт</button>
    </article>`;
  }

  function kindName(kind) {
    return { text: "текст", photo: "фото", video: "видео", video_note: "кружок", voice: "голосовое", audio: "аудио", document: "файл", other: "сообщение" }[kind] || kind;
  }

  async function requestPdf() {
    const button = $("pdf"), status = $("pdf-status");
    button.disabled = true;
    status.textContent = "Собираю… обычно это меньше минуты.";
    try {
      const job = await RM.api("/api/journal/pdf", { method: "POST", body: {} });
      let tries = 0;
      const poll = async () => {
        let st;
        try { st = await RM.api(`/api/journal/pdf/${job.job_id}`); } catch (e) { status.textContent = e.message; button.disabled = false; return; }
        if (st.status === "done") { status.innerHTML = `Готово — <a href="${st.url}" target="_blank">открыть PDF</a>. Файл ушёл и в чат с ботом.`; button.disabled = false; RM.haptic("success"); }
        else if (st.status === "failed") { status.textContent = "Не получилось: " + (st.error || "ошибка"); button.disabled = false; }
        else if (tries++ < 60) setTimeout(poll, 2000);
        else { status.textContent = "Долго собирается — файл придёт в бота, когда будет готов."; button.disabled = false; }
      };
      setTimeout(poll, 1500);
    } catch (e) { status.textContent = "Не получилось: " + e.message; button.disabled = false; }
  }

  // --- Словарь -------------------------------------------------------------------------

  async function renderWords() {
    screen.innerHTML = loading();
    try { state.dictionary = await RM.api("/api/dictionary"); } catch (e) { return (screen.innerHTML = errorBox(e)); }
    const d = state.dictionary;
    let out = `<header class="screen-head"><p class="eyebrow">Словарик сезона</p><h1>${esc(d.about)}</h1><p class="muted">К концу сезона соберём из этого общий словарь — твои слова будут там с твоим именем.</p></header>`;
    out += `<div class="card composer"><h2>Добавить своё слово</h2><p class="note">Слово и что оно значит, одной строкой. За первое слово — ❄️ +1 заморозка.</p>
      <input id="word-text" placeholder="sobremesa — время за столом уже после еды"><button class="btn block" id="word-send" style="margin-top:10px">Записать</button></div>`;
    out += `<h3>Слова недель</h3>`;
    out += d.week_words.length ? `<ul class="list">${d.week_words.map((w) => `<li><span class="mark">📖</span><span class="body"><div class="title">${esc(w.word)}${w.word_ru ? ` <span class="muted" style="font-weight:400">· ${esc(w.word_ru)}</span>` : ""}</div>${w.meaning ? `<div>${esc(w.meaning)}</div>` : ""}<div class="sub">неделя ${w.week_number} · ${esc(w.title)}</div></span></li>`).join("")}</ul>` : `<p class="muted">Слова недели появятся вместе с заданиями.</p>`;
    out += `<h3>Ваши слова</h3>`;
    out += d.user_words.length ? `<ul class="list">${d.user_words.map((w) => `<li class="${w.mine ? "mine" : ""}"><span class="mark">${w.mine ? "✍️" : "💬"}</span><span class="body"><div class="title">${esc(w.word)}</div>${w.meaning ? `<div>${esc(w.meaning)}</div>` : ""}<div class="sub">${w.mine ? "ты" : esc(w.author)}</div></span></li>`).join("")}</ul>` : `<p class="muted">Пока никто не добавил — будь первым.</p>`;
    screen.innerHTML = out;
    $("word-send").addEventListener("click", async () => {
      const text = $("word-text").value.trim();
      if (!text) return RM.toast("Напиши слово и значение");
      $("word-send").disabled = true;
      try {
        const r = await RM.api("/api/words", { method: "POST", body: { text } });
        RM.haptic("success");
        RM.alert(r.message.replace(/<[^>]+>/g, ""));
        await refreshHome();
        renderWords();
      } catch (e) { $("word-send").disabled = false; RM.toast(e.message); }
    });
  }

  // --- Ещё -----------------------------------------------------------------------------

  async function renderMore() {
    screen.innerHTML = loading();
    try { state.facts = await RM.api("/api/facts"); } catch (e) { return (screen.innerHTML = errorBox(e)); }
    const h = state.home, f = state.facts;
    let out = `<header class="screen-head"><p class="eyebrow">Романтика маршрутов</p><h1>Ещё</h1></header>`;
    out += `<div class="card"><h2>💡 Что мы узнали про ${esc(f.about)}</h2>
      ${f.facts.length ? `<ol style="padding-left:20px;margin:0 0 10px">${f.facts.map((x) => `<li${x.mine ? ' style="font-weight:600"' : ""}>${esc(x.text)}${x.author ? ` <span class="muted small">— ${esc(x.author)}</span>` : ""}</li>`).join("")}</ol>` : `<p class="muted">Пока пусто — что зацепило из постов или что раскопал сам?</p>`}
      <div class="row"><input id="fact-text" placeholder="Ацтеки называли себя мешика — отсюда «Мексика»" style="flex:1"><button class="btn small" id="fact-send">Записать</button></div>
      <p class="note" style="margin:8px 0 0">Попадёт в общий список и в журнал сезона, с твоим именем.</p></div>`;
    out += `<div class="card composer"><h2>✉️ Написать Миле</h2><p class="note helptext">${html(h.texts.write_prompt)}</p><textarea id="letter-text" placeholder="Это обычное сообщение, не отчёт"></textarea><button class="btn block" id="letter-send" style="margin-top:10px">Отправить</button></div>`;
    out += `<details class="card"><summary>❔ Если что-то пошло не так</summary><div class="content helptext">${html(h.texts.help)}</div></details>`;
    out += `<details class="card"><summary>О клубе</summary><div class="content helptext">${html(h.texts.greeting)}</div></details>`;
    const links = [];
    if (h.links.channel_url) links.push(`<a class="btn soft" href="${esc(h.links.channel_url)}">📣 Канал клуба</a>`);
    if (h.today.calendar_url) links.push(`<a class="btn soft" href="${esc(h.today.calendar_url)}">☀️ Календарь цолькин</a>`);
    if (h.links.admin_app) links.push(`<a class="btn" href="/app/admin${location.hash}">🛠 Админка</a>`);
    if (links.length) out += `<div class="actions" style="margin-top:4px">${links.join("")}</div>`;
    out += `<p class="muted small" style="margin-top:20px;text-align:center">Бот${h.links.bot_username ? ` @${esc(h.links.bot_username)}` : ""} умеет то же самое: просто пришли ему текст или фото.</p>`;
    screen.innerHTML = out;
    $("fact-send").addEventListener("click", async () => {
      const text = $("fact-text").value.trim();
      if (!text) return RM.toast("Напиши факт");
      $("fact-send").disabled = true;
      try { const r = await RM.api("/api/facts", { method: "POST", body: { text } }); RM.haptic("success"); RM.toast(r.message.replace(/<[^>]+>/g, "")); renderMore(); }
      catch (e) { $("fact-send").disabled = false; RM.toast(e.message); }
    });
    $("letter-send").addEventListener("click", async () => {
      const text = $("letter-text").value.trim();
      if (!text) return RM.toast("Пустое письмо не отправлю");
      $("letter-send").disabled = true;
      try { const r = await RM.api("/api/letters", { method: "POST", body: { text } }); RM.haptic("success"); $("letter-text").value = ""; RM.alert(r.message); }
      catch (e) { RM.toast(e.message); }
      $("letter-send").disabled = false;
    });
  }

  // --- helpers -------------------------------------------------------------------------

  function loading() { return `<div class="loading"><div class="spinner"></div><p class="muted">Загружаю…</p></div>`; }
  function errorBox(e) { return `<div class="empty"><div class="big">🙈</div><h2>Не получилось</h2><p class="muted">${esc(e.message)}</p><button class="btn soft" onclick="location.reload()">Обновить</button></div>`; }

  function openSheet(title, body, bind) {
    $("sheet-title").textContent = title;
    $("sheet-body").innerHTML = body;
    $("sheet").hidden = false;
    document.body.style.overflow = "hidden";
    RM.onBack(closeSheet);
    if (bind) bind();
  }
  function closeSheet() {
    if ($("sheet").hidden) return;
    $("sheet").hidden = true;
    document.body.style.overflow = "";
    RM.onBack(null);
  }
})();
