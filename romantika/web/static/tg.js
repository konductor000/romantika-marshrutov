// Shared Telegram Mini App plumbing: expand, theme, links, and the API helper.
(function () {
  const RM = (window.RM = window.RM || {});

  function tgReady(cb) {
    let tries = 0;
    (function poll() {
      const tg = window.Telegram && window.Telegram.WebApp;
      if (tg) return cb(tg);
      if (tries++ < 25) return setTimeout(poll, 120);
      cb(null);
    })();
  }

  RM.initData = function () {
    const tg = window.Telegram && window.Telegram.WebApp;
    if (tg && tg.initData) return tg.initData;
    const params = new URLSearchParams(location.search);
    return params.get("init") || "";
  };

  RM.api = async function (path, options) {
    const opts = Object.assign({ headers: {} }, options || {});
    opts.headers = Object.assign({ "X-Telegram-Init-Data": RM.initData() }, opts.headers);
    if (opts.body && typeof opts.body !== "string") {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(opts.body);
    }
    opts.credentials = "same-origin";
    const response = await fetch(path, opts);
    if (response.status === 204) return null;
    const text = await response.text();
    let data = null;
    try { data = text ? JSON.parse(text) : null; } catch (e) { data = { detail: text }; }
    if (!response.ok) {
      const err = new Error((data && data.detail) ? (typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail)) : response.statusText);
      err.status = response.status;
      throw err;
    }
    return data;
  };

  // The cookie lets <img src="/media/..."> load without custom headers.
  RM.openSession = async function () {
    const init = RM.initData();
    if (!init) return null;
    try { return await RM.api("/api/session", { method: "POST", body: { init_data: init } }); } catch (e) { return null; }
  };

  RM.escape = function (s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  };

  RM.levelName = { tourist: "Турист", traveler: "Путешественник", resident: "Резидент" };
  RM.stateMark = { stamped: "✅", current: "▸", frozen: "❄️", missed: "◦", before_join: "◦", locked: "🔒" };
  RM.freezeReason = { word: "за своё слово в словарике", max: "за первый максимум", comment: "за комментарий", meetup: "за встречу", friend: "за приведённого друга", manual: "от Милы" };

  RM.tabs = function (container, onSelect) {
    const buttons = container.querySelectorAll("button[data-tab]");
    buttons.forEach((b) => b.addEventListener("click", () => {
      buttons.forEach((x) => x.classList.toggle("active", x === b));
      document.querySelectorAll(".tab").forEach((s) => (s.hidden = s.id !== b.dataset.tab));
      if (onSelect) onSelect(b.dataset.tab);
    }));
  };

  RM.toast = function (text) {
    const el = document.getElementById("toast");
    if (!el) return;
    el.textContent = text;
    el.hidden = false;
    clearTimeout(el._t);
    el._t = setTimeout(() => (el.hidden = true), 2200);
  };

  tgReady(function (tg) {
    if (!tg) return;
    try {
      tg.ready();
      tg.expand();
      if (tg.disableVerticalSwipes) tg.disableVerticalSwipes();
      const dark = document.body.classList.contains("night");
      tg.setHeaderColor(dark ? "#0C1D22" : "#fbf6ee");
      tg.setBackgroundColor(dark ? "#0C1D22" : "#fbf6ee");
    } catch (e) { /* older clients */ }
    document.documentElement.classList.add("in-telegram");
    document.addEventListener("click", (event) => {
      const a = event.target.closest && event.target.closest('a[href^="https://t.me/"]');
      if (a && tg.openTelegramLink) { event.preventDefault(); tg.openTelegramLink(a.href); }
    });
  });
})();
