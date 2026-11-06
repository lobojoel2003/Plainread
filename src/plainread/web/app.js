/* Plainread web app. Plain JavaScript, no external code, no tracking.
 * Letter text is untrusted: everything is rendered with textContent. */
"use strict";

(() => {
  const $ = (sel) => document.querySelector(sel);
  const state = {
    lang: "en",
    strings: {},
    languages: [],
    health: null,
    files: [],
    result: null,
    lastRequest: null,
    speaking: false,
  };

  // ---------------------------------------------------------------- i18n --

  function lookup(key) {
    return key.split(".").reduce((node, part) => (node && typeof node === "object" ? node[part] : undefined), state.strings);
  }

  function t(key, values = {}) {
    let text = lookup(key);
    if (typeof text !== "string") return key;
    return text.replace(/\{(\w+)\}/g, (m, name) => (name in values ? String(values[name]) : m));
  }

  function tn(key, count, values = {}) {
    return t(`${key}_${count === 1 ? "one" : "other"}`, { count, ...values });
  }

  function applyStrings() {
    const meta = state.strings._meta || {};
    document.documentElement.lang = meta.code || state.lang;
    document.documentElement.dir = meta.dir || "ltr";
    document.querySelectorAll("[data-i18n]").forEach((el) => {
      el.textContent = t(el.dataset.i18n);
    });
    document.querySelectorAll("[data-i18n-placeholder]").forEach((el) => {
      el.setAttribute("placeholder", t(el.dataset.i18nPlaceholder));
    });
    updateAiStatus();
    updatePages();
    if (state.health) $("#version").textContent = versionText();
  }

  async function loadLanguage(code) {
    const response = await fetch(`/api/i18n/${encodeURIComponent(code)}`);
    state.strings = await response.json();
    state.lang = state.strings._meta.code;
    try { localStorage.setItem("plainread.lang", state.lang); } catch (_) { /* private mode */ }
    applyStrings();
  }

  function pickLanguage() {
    let saved = null;
    try { saved = localStorage.getItem("plainread.lang"); } catch (_) { /* ignore */ }
    const codes = state.languages.map((l) => l.code);
    if (saved && codes.includes(saved)) return saved;
    for (const tag of navigator.languages || [navigator.language || "en"]) {
      const base = tag.toLowerCase().split("-")[0];
      const match = tag.toLowerCase() === "fil" ? "tl" : base;
      if (codes.includes(match)) return match;
    }
    return "en";
  }

  // ----------------------------------------------------------- helpers --

  function el(tag, attrs = {}, ...children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs)) {
      if (value === null || value === undefined || value === false) continue;
      if (key === "class") node.className = value;
      else if (key === "text") node.textContent = value;
      else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
      else node.setAttribute(key, value === true ? "" : value);
    }
    for (const child of children.flat()) {
      if (child === null || child === undefined || child === false) continue;
      node.append(child instanceof Node ? child : document.createTextNode(String(child)));
    }
    return node;
  }

  function icon(name, cls = "icon") {
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("class", cls);
    svg.setAttribute("aria-hidden", "true");
    const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
    use.setAttribute("href", `#i-${name}`);
    svg.append(use);
    return svg;
  }

  const squash = (s) => String(s || "").replace(/\s+/g, " ").trim();

  function show(view) {
    for (const id of ["start", "working", "results"]) $(`#${id}`).hidden = id !== view;
  }

  function versionText() {
    const h = state.health;
    const build = h.build === "dev" ? "dev" : `build ${h.build}`;
    return `${t("ui.version", { version: h.version })} (${build})`;
  }

  function showError(message) {
    const box = $("#start-error");
    box.textContent = message;
    box.hidden = !message;
  }

  // ------------------------------------------------------------- input --

  function addFiles(list) {
    for (const file of list) {
      const ok = /^image\//.test(file.type) || file.type === "application/pdf" || /\.(pdf|txt|jpe?g|png|webp|heic|tiff?)$/i.test(file.name);
      if (!ok) { showError(t("ui.error_type")); continue; }
      const maxMb = state.health ? state.health.max_upload_mb : 25;
      if (file.size > maxMb * 1024 * 1024) { showError(t("ui.error_too_big")); continue; }
      state.files.push({ file, url: /^image\//.test(file.type) ? URL.createObjectURL(file) : null });
      showError("");
    }
    updatePages();
  }

  function updatePages() {
    const list = $("#page-list");
    list.replaceChildren();
    $("#pages").hidden = state.files.length === 0;
    $("#pages-count").textContent = state.files.length ? tn("ui.pages_added", state.files.length) : "";
    state.files.forEach((entry, index) => {
      const preview = entry.url
        ? el("img", { src: entry.url, alt: entry.file.name })
        : el("div", { class: "page-file" }, icon("file", "icon icon--big"));
      const remove = el("button", {
        class: "btn btn--small", type: "button", text: t("ui.remove"),
        "aria-label": `${t("ui.remove")}: ${entry.file.name}`,
        onclick: () => {
          if (entry.url) URL.revokeObjectURL(entry.url);
          state.files.splice(index, 1);
          updatePages();
        },
      });
      list.append(el("li", {}, preview, el("span", { text: entry.file.name }), remove));
    });
  }

  function togglePaste(open) {
    const area = $("#paste-area");
    const willOpen = open ?? area.hidden;
    area.hidden = !willOpen;
    $("#paste-toggle").setAttribute("aria-expanded", String(willOpen));
    if (willOpen) $("#letter-text").focus();
  }

  function updateAiStatus() {
    const box = $("#use-ai");
    const status = $("#ai-status");
    if (!state.health) return;
    const ai = state.health.ai;
    box.disabled = !ai.available;
    if (!ai.available) box.checked = false;
    status.textContent = ai.available ? t("ui.ai_ready", { model: ai.model }) : t("ui.ai_unavailable");
  }

  // ----------------------------------------------------------- explain --

  async function explain() {
    const text = $("#letter-text").value.trim();
    if (!state.files.length && !text) {
      showError(t("ui.error_empty"));
      return;
    }
    showError("");
    state.lastRequest = { files: state.files.map((f) => f.file), text, useAi: $("#use-ai").checked };
    await runRequest();
  }

  async function runRequest() {
    const req = state.lastRequest;
    const form = new FormData();
    for (const file of req.files) form.append("files", file, file.name);
    if (!req.files.length) form.append("text", req.text);
    form.append("language", state.lang);
    form.append("use_ai", req.useAi ? "true" : "false");
    const today = new URLSearchParams(location.search).get("today");
    if (today && /^\d{4}-\d{2}-\d{2}$/.test(today)) form.append("today", today);
    stopSpeaking();
    show("working");
    $("#working").focus?.();
    try {
      const response = await fetch("/api/explain", { method: "POST", body: form });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : t("ui.error_generic"));
      state.result = data;
      renderResult(data);
      show("results");
      window.scrollTo({ top: 0 });
      $("#main").focus();
    } catch (err) {
      show("start");
      showError(err.message || t("ui.error_generic"));
    }
  }

  // ------------------------------------------------------------ render --

  function quoteBlock(quote, text) {
    const same = squash(quote.text).toLowerCase() === squash(text).toLowerCase();
    const body = el("div", { class: "quote__body" });
    if (!same) {
      body.append(el("span", { class: "quote__label", text: t("ui.letter_says") + " " }), `“${squash(quote.text)}”`);
    }
    body.append(
      el("div", { class: "quote__actions" },
        el("span", { class: "verified" }, icon("check"), t("ui.found_in_letter")),
        el("button", {
          class: "linkbtn", type: "button", text: t("ui.show_in_letter"),
          onclick: () => revealQuote(quote.start),
        }),
      ),
    );
    return el("div", { class: "quote" }, icon("quote"), body);
  }

  function section(key, items, renderItem, extraClass = "") {
    const title = t(`sections.${key}`);
    const body = items.length ? renderItem(items) : el("p", { class: "empty", text: t("ui.nothing_found") });
    const card = el("section", { class: `card ${extraClass}`.trim(), "aria-label": title });
    const speakText = () => [title, ...speechFor(key, items)].join(". ");
    card.append(
      el("div", { class: "section-head" },
        el("h2", { text: title }),
        items.length ? speakButton(speakText) : null,
      ),
      body,
    );
    return card;
  }

  function speakButton(getText) {
    return el("button", {
      class: "btn btn--small speak", type: "button", "aria-label": t("ui.read_aloud"),
      title: t("ui.read_aloud"), onclick: () => speak(getText()),
    }, icon("speak"));
  }

  function pointList(items, checklist = false) {
    const list = el(checklist ? "ol" : "ul", { class: checklist ? "checklist" : "points" });
    items.forEach((p, i) => {
      const id = `chk-${checklist ? "a" : "p"}-${i}-${p.quote.start}`;
      const main = el("div", { class: "item__main" },
        el(checklist ? "label" : "p", { class: "item__text", for: checklist ? id : null, text: p.text }),
        p.source === "ai" ? el("span", { class: "ai-tag", text: "AI" }) : null,
        quoteBlock(p.quote, p.text),
      );
      const row = checklist
        ? el("li", { class: "item" }, el("input", { type: "checkbox", id }), main)
        : el("li", { class: "item" }, main);
      list.append(row);
    });
    return list;
  }

  function dateCard(d) {
    const date = new Date(`${d.date}T12:00:00`);
    const month = (state.strings.months || [])[date.getMonth()] || "";
    const days = d.days_left ?? 0;
    const rel = days === 0 ? t("relative.today") : days === 1 ? t("relative.tomorrow") : days === -1 ? t("relative.yesterday")
      : days > 0 ? tn("relative.in_days", days) : tn("relative.days_ago", -days);
    return el("li", { class: "item date" },
      el("div", { class: "date__cal", "aria-hidden": "true" },
        el("div", { class: "date__month", text: month.slice(0, 12) }),
        el("div", { class: "date__day", text: String(date.getDate()) }),
      ),
      el("p", { class: "date__when", text: `${d.date_text} · ${rel}` }),
      el("div", { class: "chips" },
        el("span", { class: `chip chip--${d.urgency}`, text: t(`urgency.${d.urgency}`) }),
        el("span", { class: "chip chip--kind", text: d.label }),
        d.calculated ? el("span", { class: "chip chip--kind", text: t("ui.calculated") }) : null,
      ),
      el("div", {},
        el("p", { class: "item__text", text: d.description }),
        d.note ? el("p", { class: "note", text: d.note }) : null,
        quoteBlock(d.quote, d.description),
      ),
    );
  }

  function facts(items, renderValue) {
    const list = el("dl", { class: "facts" });
    for (const item of items) list.append(el("div", { class: "fact" }, el("dt", { text: item.label }), el("dd", {}, renderValue(item))));
    return list;
  }

  function copyButton(value) {
    return el("button", {
      class: "btn btn--small", type: "button", text: t("ui.copy"),
      onclick: async (event) => {
        try {
          await navigator.clipboard.writeText(value);
          event.target.textContent = t("ui.copied");
          setTimeout(() => { event.target.textContent = t("ui.copy"); }, 1600);
        } catch (_) { /* clipboard blocked */ }
      },
    });
  }

  function renderResult(r) {
    const root = $("#result-body");
    root.replaceChildren();

    // What is this letter?
    const intro = el("section", { class: "card", "aria-label": t("sections.what_is_this") });
    intro.append(
      el("div", { class: "section-head" }, el("h2", { text: t("sections.what_is_this") }),
        speakButton(() => [t("sections.what_is_this"), ...r.summary, ...r.key_points.map((p) => p.text)].join(". "))),
      el("p", { class: "lead-type" }, el("span", { class: "badge", text: r.letter_type_label })),
      el("ul", { class: "summary" }, r.summary.map((line) => el("li", { text: line }))),
      ...r.key_points.map((p) => el("div", { class: "keypoint" },
        el("span", { class: "keypoint__label", text: t("summary.key_point") }),
        el("p", { class: "item__text", text: p.text }),
        quoteBlock(p.quote, p.text))),
    );
    root.append(intro);

    if (r.warnings.length) {
      root.append(el("section", { class: "card warnings", role: "note" },
        el("div", { class: "section-head" }, el("h2", {}, icon("warn"), " ", t("sections.warnings"))),
        el("ul", {}, r.warnings.map((w) => el("li", { text: w })))));
    }

    root.append(section("important_dates", r.dates, (items) => el("ul", { class: "points" }, items.map(dateCard))));
    root.append(section("what_to_do", r.actions, (items) => pointList(items, true)));
    root.append(section("consequences", r.consequences, (items) => pointList(items)));
    root.append(section("rights", r.rights, (items) => pointList(items)));
    if (r.amounts.length) {
      root.append(section("money", r.amounts, (items) => facts(items, (a) => el("span", { class: "money", text: a.display }))));
    }
    if (r.contacts.length) {
      root.append(section("contacts", r.contacts, (items) => facts(items, (c) => {
        const external = c.kind === "website";
        return c.href
          ? el("a", { href: c.href, rel: external ? "noopener noreferrer" : null, target: external ? "_blank" : null },
            c.kind === "phone" || c.kind === "tty" ? icon("phone") : null, c.value)
          : c.value;
      })));
    }
    if (r.references.length) {
      root.append(section("numbers", r.references, (items) => facts(items, (ref) => [el("span", { text: ref.value }), copyButton(ref.value)])));
    }
    if (r.glossary.length) {
      root.append(section("words", r.glossary, (items) => el("dl", { class: "words" },
        items.flatMap((g) => [el("dt", { text: g.term }), el("dd", { text: g.meaning })]))));
    }

    root.append(letterCard(r));

    const meta = el("section", { class: "card meta" });
    if (r.reading_level_text) meta.append(el("p", { text: r.reading_level_text }));
    meta.append(el("p", { text: r.disclaimer }));
    const engine = r.engine === "rules" ? t("ui.engine_rules") : t("ui.engine_ai", { model: r.engine.split(":").slice(2).join(":") });
    meta.append(el("p", { text: engine }));
    root.append(meta);

    $("#calendar").disabled = r.dates.length === 0;
    updateSpeechButtons();
  }

  // Read-aloud buttons only appear when this device has a voice for the language.
  function updateSpeechButtons() {
    const available = Boolean(voiceFor(state.lang));
    $("#read-all").hidden = !available;
    document.querySelectorAll(".speak").forEach((b) => { b.hidden = !available; });
  }

  function letterCard(r) {
    const text = r.source_text;
    const ranges = [];
    const quotes = [r.sender_quote, ...r.key_points.map((p) => p.quote), ...r.dates.map((d) => d.quote),
      ...r.actions.map((p) => p.quote), ...r.consequences.map((p) => p.quote), ...r.rights.map((p) => p.quote)].filter(Boolean);
    for (const q of quotes) ranges.push([q.start, q.end]);
    ranges.sort((a, b) => a[0] - b[0]);
    const merged = [];
    for (const [s, e] of ranges) {
      const last = merged[merged.length - 1];
      if (last && s <= last[1]) last[1] = Math.max(last[1], e);
      else merged.push([s, e]);
    }
    const pre = el("div", { class: "letter__text", tabindex: "0" });
    let pos = 0;
    for (const [s, e] of merged) {
      if (s > pos) pre.append(text.slice(pos, s));
      pre.append(el("mark", { "data-start": String(s), "data-end": String(e), tabindex: "-1", text: text.slice(s, e) }));
      pos = e;
    }
    if (pos < text.length) pre.append(text.slice(pos));
    const details = el("details", { class: "letter", id: "full-letter" },
      el("summary", { text: t("ui.show_full_letter") }), pre);
    details.addEventListener("toggle", () => {
      details.querySelector("summary").textContent = details.open ? t("ui.hide_full_letter") : t("ui.show_full_letter");
    });
    return el("section", { class: "card", "aria-label": t("sections.full_letter") }, el("h2", { text: t("sections.full_letter") }), details);
  }

  function revealQuote(start) {
    const details = $("#full-letter");
    if (!details) return;
    details.open = true;
    const marks = [...details.querySelectorAll("mark")];
    const mark = marks.find((m) => Number(m.dataset.start) <= start && start < Number(m.dataset.end));
    if (!mark) return;
    marks.forEach((m) => m.classList.remove("flash"));
    mark.classList.add("flash");
    mark.scrollIntoView({ behavior: "smooth", block: "center" });
    mark.focus({ preventScroll: true });
    setTimeout(() => mark.classList.remove("flash"), 3500);
  }

  // ------------------------------------------------------------ speech --

  function speechFor(key, items) {
    switch (key) {
      case "important_dates": return items.map((d) => `${d.label}: ${d.date_text}. ${d.description}`);
      case "money": return items.map((a) => `${a.label}: ${a.display}`);
      case "contacts": return items.map((c) => `${c.label}: ${c.value.split("").join(" ")}`);
      case "numbers": return items.map((r) => `${r.label}: ${r.value.split("").join(" ")}`);
      case "words": return items.map((g) => `${g.term}: ${g.meaning}`);
      default: return items.map((p) => p.text);
    }
  }

  function voiceFor(lang) {
    if (!("speechSynthesis" in window)) return null;
    const tag = ((state.strings._meta && state.strings._meta.speech) || lang).toLowerCase();
    const base = tag.split("-")[0];
    // Only on-device voices: some browsers' online voices send text to a server.
    const voices = speechSynthesis.getVoices().filter((v) => v.localService);
    return voices.find((v) => v.lang.toLowerCase() === tag)
      || voices.find((v) => v.lang.toLowerCase().split(/[-_]/)[0] === base)
      || null;
  }

  function speak(text) {
    stopSpeaking();
    const voice = voiceFor(state.lang);
    if (!voice) return;
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.voice = voice;
    utterance.lang = voice.lang;
    utterance.rate = 0.9;
    utterance.onend = () => setSpeaking(false);
    utterance.onerror = () => setSpeaking(false);
    setSpeaking(true);
    speechSynthesis.speak(utterance);
  }

  function setSpeaking(on) {
    state.speaking = on;
    const label = $("#read-all span");
    if (label) label.textContent = on ? t("ui.stop_reading") : t("ui.read_aloud");
  }

  function stopSpeaking() {
    if ("speechSynthesis" in window) speechSynthesis.cancel();
    setSpeaking(false);
  }

  function readAll() {
    if (state.speaking) { stopSpeaking(); return; }
    const r = state.result;
    if (!r) return;
    const parts = [...r.summary, ...r.key_points.map((p) => p.text)];
    const add = (key, items) => { if (items.length) parts.push(t(`sections.${key}`), ...speechFor(key, items)); };
    add("important_dates", r.dates);
    add("what_to_do", r.actions);
    add("consequences", r.consequences);
    add("rights", r.rights);
    add("money", r.amounts);
    speak(parts.join(". "));
  }

  // ---------------------------------------------------------- calendar --

  async function downloadCalendar() {
    const r = state.result;
    if (!r || !r.dates.length) return;
    const response = await fetch("/api/calendar", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ dates: r.dates, sender: r.sender }),
    });
    if (!response.ok) return;
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = el("a", { href: url, download: "plainread-dates.ics" });
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 2000);
  }

  // ------------------------------------------------------------- reset --

  function reset() {
    stopSpeaking();
    state.files.forEach((f) => f.url && URL.revokeObjectURL(f.url));
    state.files = [];
    state.result = null;
    state.lastRequest = null;
    $("#letter-text").value = "";
    $("#sample-select").value = "";
    $("#result-body").replaceChildren();
    togglePaste(false);
    updatePages();
    show("start");
    window.scrollTo({ top: 0 });
  }

  // -------------------------------------------------------------- init --

  async function loadSamples() {
    try {
      const samples = await (await fetch("/api/samples")).json();
      const select = $("#sample-select");
      for (const s of samples) select.append(el("option", { value: s.id, text: s.title }));
    } catch (_) { /* optional */ }
  }

  async function init() {
    const [health, languages] = await Promise.all([
      fetch("/api/health").then((r) => r.json()),
      fetch("/api/languages").then((r) => r.json()),
    ]);
    state.health = health;
    state.languages = languages;
    const select = $("#language");
    for (const lang of languages) {
      const label = lang.native_name === lang.name ? lang.name : `${lang.native_name} — ${lang.name}`;
      select.append(el("option", { value: lang.code, text: label, lang: lang.code, dir: lang.dir }));
    }
    const lang = pickLanguage();
    select.value = lang;
    await loadLanguage(lang);
    loadSamples();

    select.addEventListener("change", async () => {
      await loadLanguage(select.value);
      if (state.lastRequest && !$("#results").hidden) await runRequest();
    });
    $("#camera-input").addEventListener("change", (e) => { addFiles(e.target.files); e.target.value = ""; });
    $("#file-input").addEventListener("change", (e) => { addFiles(e.target.files); e.target.value = ""; });
    $("#paste-toggle").addEventListener("click", () => togglePaste());
    $("#explain").addEventListener("click", explain);
    $("#again").addEventListener("click", reset);
    $("#print").addEventListener("click", () => window.print());
    $("#calendar").addEventListener("click", downloadCalendar);
    $("#read-all").addEventListener("click", readAll);
    $("#sample-select").addEventListener("change", async (e) => {
      if (!e.target.value) return;
      const today = new URLSearchParams(location.search).get("today");
      const query = today ? `?today=${encodeURIComponent(today)}` : "";
      const sample = await (await fetch(`/api/samples/${encodeURIComponent(e.target.value)}${query}`)).json();
      $("#letter-text").value = sample.text;
      togglePaste(true);
    });

    const zone = $("#dropzone");
    ["dragenter", "dragover"].forEach((type) => document.addEventListener(type, (e) => {
      e.preventDefault();
      zone.classList.add("is-over");
    }));
    ["dragleave", "drop"].forEach((type) => document.addEventListener(type, (e) => {
      e.preventDefault();
      if (type === "drop" || e.target === zone) zone.classList.remove("is-over");
    }));
    document.addEventListener("drop", (e) => { if (e.dataTransfer?.files?.length) addFiles(e.dataTransfer.files); });
    document.addEventListener("paste", (e) => {
      const files = [...(e.clipboardData?.files || [])];
      if (files.length && document.activeElement !== $("#letter-text")) addFiles(files);
    });
    if ("speechSynthesis" in window) speechSynthesis.addEventListener?.("voiceschanged", () => {
      if (state.result) updateSpeechButtons();
    });
  }

  init().catch(() => showError("Plainread could not start. Is the server running?"));
})();
