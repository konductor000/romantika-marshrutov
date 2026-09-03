// «Мой журнал» Mini App: passport, weeks, reports with photos, dictionary, PDF.
(async function () {
  const RM = window.RM;
  const esc = RM.escape;
  const $ = (id) => document.getElementById(id);
  const fail = (message) => { $("error").textContent = message; $("error").hidden = false; $("subtitle").textContent = ""; };

  await RM.openSession();
  let journal;
  try {
    journal = await RM.api("/api/journal");
  } catch (e) {
    if (e.status === 401) return fail("Открой эту страницу из бота: Telegram передаёт, кто ты, только внутри приложения.");
    if (e.status === 404) return fail("Сезон ещё не начался.");
    return fail("Не удалось загрузить журнал: " + e.message);
  }

  const p = journal.passport;
  $("title").textContent = "Журнал · " + journal.season.title;
  $("subtitle").textContent = `${journal.user.first_name || ""} · ${fmt(journal.season.starts_on)} — ${fmt(journal.season.ends_on)}`;

  $("passport").innerHTML = `
    <div class="tile"><div class="big">${p.stamps} <span class="muted">/ ${p.weeks_total}</span></div><div class="label">штампов${p.stamps_max ? " · ⭐ " + p.stamps_max : ""}</div></div>
    <div class="tile"><div class="big">${esc(RM.levelName[p.level] || "Ещё в пути")}</div><div class="label">статус</div></div>
    <div class="tile"><div class="big">${p.freezes_left} <span class="muted">/ ${p.freezes_total}</span></div><div class="label">заморозок осталось</div></div>
    <div class="tile"><div class="big">${p.current_streak}</div><div class="label">недель подряд сейчас · лучшая ${p.best_streak}</div></div>`;
  $("passport").hidden = false;

  $("weeks").innerHTML = '<ul class="weeklist">' + journal.weeks.map((w) => {
    const mark = w.state === "stamped" ? (w.level === "max" ? "⭐" : "✅") : (RM.stateMark[w.state] || "·");
    const sub = w.state === "locked" ? "откроется " + fmt(w.starts_on)
      : w.state === "frozen" ? "пропуск закрыт заморозкой — цепочка не рвётся"
      : w.state === "missed" ? "пропущена"
      : w.state === "before_join" ? "до тебя"
      : w.state === "current" ? "идёт сейчас · до " + fmt(w.ends_on)
      : (w.level === "max" ? "максимум" : "минимум");
    const task = w.state !== "locked" && w.task_min ? `<div class="sub">Минимум: ${esc(w.task_min)}${w.task_max ? " · Максимум: " + esc(w.task_max) : ""}</div>` : "";
    return `<li><span class="mark">${mark}</span><span><div class="title">${w.number}. ${esc(w.title)}</div><div class="sub">${esc(sub)}</div>${task}</span></li>`;
  }).join("") + "</ul>";

  const reports = journal.reports.filter((r) => r.week_number !== null);
  $("reports").innerHTML = reports.length ? reports.map((r) => `
    <article class="report">
      <div class="meta">Неделя ${r.week_number} · ${fmt(r.created_at)} · ${r.level === "max" ? "⭐ максимум" : "✅ минимум"}</div>
      ${r.text ? `<div>${esc(r.text)}</div>` : ""}
      ${r.media.map((m) => m.mime && m.mime.startsWith("image/") && m.downloaded ? `<img src="${m.url}" alt="" loading="lazy">` : (m.downloaded ? `<a class="btn ghost small" href="${m.url}">Открыть файл</a>` : `<span class="muted">файл ещё скачивается</span>`)).join("")}
    </article>`).join("") : '<p class="muted">Пока пусто — здесь появятся твои недели и твои же слова о них.</p>';

  $("words").innerHTML = `
    ${journal.season_words.length ? `<h2>Слова сезона</h2><ul class="weeklist">${journal.season_words.map((w) => `<li><span class="mark">📖</span><span><div class="title">${esc(w.word)}</div><div class="sub">${esc(w.meaning)}</div></span></li>`).join("")}</ul>` : ""}
    ${journal.words.length ? `<h2 style="margin-top:14px">Твои слова</h2><div class="chips">${journal.words.map((w) => `<span class="chip">${esc(w.word)}${w.meaning ? " — " + esc(w.meaning) : ""}</span>`).join("")}</div>` : '<p class="muted">Своих слов пока нет — добавь через «📖 Словарь» в боте.</p>'}`;

  $("more").innerHTML = `
    ${journal.achievements.length ? `<h2>Ачивки</h2><div class="chips">${journal.achievements.map((a) => `<span class="chip">${esc(a)}</span>`).join("")}</div>` : ""}
    ${p.freeze_reasons.length ? `<p class="note">Заработанные заморозки: ${p.freeze_reasons.map((r) => esc(RM.freezeReason[r] || r)).join(", ")}</p>` : ""}
    ${journal.wish ? `<h2 style="margin-top:14px">От Милы</h2><p><i>${esc(journal.wish)}</i></p>` : ""}
    ${journal.facts.length ? `<h2 style="margin-top:14px">Что мы узнали про ${esc(journal.season.title_accusative || journal.season.title)}</h2><ol>${journal.facts.map((f) => `<li>${esc(f)}</li>`).join("")}</ol>` : ""}
    <h2 style="margin-top:14px">Журнал в PDF</h2>
    <p class="muted">Соберу твой журнал целиком — недели, фото, ачивки, словарь — и пришлю файлом в бота.</p>
    <div class="row"><button class="btn" id="pdf">Собрать PDF</button><span id="pdf-status" class="muted"></span></div>`;

  $("tabs").hidden = false;
  RM.tabs($("tabs"));
  $("weeks").hidden = false;

  $("pdf").addEventListener("click", async () => {
    const button = $("pdf"), status = $("pdf-status");
    button.disabled = true;
    status.textContent = "Собираю…";
    try {
      const job = await RM.api("/api/journal/pdf", { method: "POST", body: {} });
      let tries = 0;
      const poll = async () => {
        const state = await RM.api(`/api/journal/pdf/${job.job_id}`);
        if (state.status === "done") {
          status.innerHTML = `Готово — <a href="${state.url}">открыть PDF</a>. Файл ушёл и в бота.`;
          button.disabled = false;
        } else if (state.status === "failed") {
          status.textContent = "Не получилось: " + (state.error || "ошибка"); button.disabled = false;
        } else if (tries++ < 60) {
          setTimeout(poll, 2000);
        } else {
          status.textContent = "Долго собирается — файл придёт в бота, когда будет готов."; button.disabled = false;
        }
      };
      setTimeout(poll, 1500);
    } catch (e) {
      status.textContent = "Не получилось: " + e.message; button.disabled = false;
    }
  });

  function fmt(iso) {
    const d = new Date(iso);
    return isNaN(d) ? iso : `${String(d.getDate()).padStart(2, "0")}.${String(d.getMonth() + 1).padStart(2, "0")}`;
  }
})();
