// Shared helpers for the Solstice pages: API calls, session token, safe message rendering.

const Solstice = (() => {
  function tokenKey(page) { return `solstice.${page}.token`; }

  function getToken(page) {
    try { return sessionStorage.getItem(tokenKey(page)); } catch { return null; }
  }
  function setToken(page, token) {
    try { token ? sessionStorage.setItem(tokenKey(page), token) : sessionStorage.removeItem(tokenKey(page)); } catch {}
  }

  async function api(path, { method = "GET", body, token, timeoutMs = 30000 } = {}) {
    const headers = { "Content-Type": "application/json" };
    if (token) headers.Authorization = `Bearer ${token}`;
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), timeoutMs);
    let res;
    try {
      res = await fetch(path, { method, headers, body: body ? JSON.stringify(body) : undefined, signal: ctrl.signal });
    } catch (e) {
      const err = new Error(e.name === "AbortError"
        ? "That's taking longer than expected. Please try again in a moment."
        : "We couldn't reach the concierge. Please check your connection and try again.");
      err.status = e.name === "AbortError" ? "timeout" : "network";
      throw err;
    } finally { clearTimeout(timer); }
    let data = null;
    try { data = await res.json(); } catch {}
    if (!res.ok) {
      const err = new Error((data && data.detail) || `Request failed (${res.status})`);
      err.status = res.status;
      throw err;
    }
    return data;
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  // Minimal, safe markdown: escape everything first, then allow **bold** and "- " bullet lists.
  function renderText(text) {
    // [[Suggested reply]] markers become one-tap buttons under the message (max 4), not inline text.
    const suggestions = [];
    text = (text || "").replace(/\[\[(.+?)\]\]/g, (_, t) => { t = t.trim(); if (t && !suggestions.includes(t)) suggestions.push(t); return ""; });
    const lines = escapeHtml(text).split(/\r?\n/);
    let html = "", inList = false, para = [];
    const inline = s => s.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
    const flushPara = () => { if (para.length) { html += `<p>${inline(para.join("<br>"))}</p>`; para = []; } };
    const isRow = l => /^\s*\|.*\|\s*$/.test(l);
    const cells = l => l.trim().replace(/^\||\|$/g, "").split("|").map(c => c.trim());
    const isSep = l => isRow(l) && cells(l).every(c => /^:?-{2,}:?$/.test(c));
    const table = rows => {
      const hasHead = rows.length > 1 && isSep(rows[1]);
      const body = rows.filter((r, i) => !(hasHead && i === 1) && !(hasHead && i === 0));
      const cell = (tag, c) => `<${tag}>${inline(c)}</${tag}>`;
      return '<div class="tablewrap"><table>' +
        (hasHead ? `<thead><tr>${cells(rows[0]).map(c => cell("th", c)).join("")}</tr></thead>` : "") +
        `<tbody>${body.map(r => {
          const cs = cells(r);   // a leading record id (INQ-2004, R55004) makes the row clickable on pages that opt in
          const key = /^[A-Z]{1,6}-?\d{2,}$/.test(cs[0]) ? ` data-key="${cs[0]}" tabindex="0"` : "";
          return `<tr${key}>${cs.map(c => cell("td", c)).join("")}</tr>`;
        }).join("")}</tbody></table></div>`;
    };
    for (let i = 0; i < lines.length; i++) {
      const line = lines[i].trimEnd();
      if (isRow(line)) {   // a run of | a | b | lines is a table
        flushPara();
        if (inList) { html += "</ul>"; inList = false; }
        const rows = [line];
        while (i + 1 < lines.length && isRow(lines[i + 1])) rows.push(lines[++i].trimEnd());
        html += table(rows);
        continue;
      }
      const bullet = line.match(/^\s*[-*•]\s+(.*)$/);
      if (bullet) {
        flushPara();
        if (!inList) { html += "<ul>"; inList = true; }
        html += `<li>${inline(bullet[1])}</li>`;
      } else {
        if (inList) { html += "</ul>"; inList = false; }
        if (line.trim() === "") flushPara(); else para.push(line);
      }
    }
    flushPara();
    if (inList) html += "</ul>";
    if (suggestions.length) {
      html += '<div class="replies">' + suggestions.slice(0, 4).map(t =>
        `<button type="button" class="reply-chip" data-send="${escapeHtml(t)}">${escapeHtml(t)}</button>`).join("") + "</div>";
    }
    return html;
  }

  function el(tag, attrs = {}, html = "") {
    const e = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
    if (html) e.innerHTML = html;
    return e;
  }

  // Chat replies can include a cold start (the app scales to zero) plus several model calls. The server
  // stops itself well before this (settings.yaml -> agent.turn_deadline_s), so it always answers first.
  const CHAT_TIMEOUT_MS = 150000;
  const SLOW_HINT_MS = 8000;

  // A chat box bound to elements on the page. onReply(reply, userText) lets pages add extras.
  // onExpired() is called on a 401. If it resolves to true (a new session was started), the
  // message is sent again once on that session, so the guest never has to retype it.
  function chat({ messagesEl, inputEl, sendBtn, getSessionToken, onReply, onExpired, rowPrompt, leadPrompt }) {
    let busy = false;

    // rowPrompt(id) -> text: clicking (or Enter on) a table row loads that text into the message box.
    // It isn't sent, so the user can edit it first.
    if (rowPrompt) {
      messagesEl.classList.add("clickable-rows");
      const load = e => {
        const tr = e.target.closest("tr[data-key]");
        if (!tr || !messagesEl.contains(tr)) return;
        inputEl.value = rowPrompt(tr.dataset.key);
        inputEl.dispatchEvent(new Event("input"));
        inputEl.focus();
      };
      messagesEl.addEventListener("click", load);
      messagesEl.addEventListener("keydown", e => { if (e.key === "Enter") load(e); });
    }

    // leadPrompt(label) -> text | {text, send:false} | null. The bold lead-in of a bullet ("**Policies:** ...")
    // becomes a button. A plain string is sent at once; {text, send:false} is loaded into the message box
    // for the user to finish (e.g. it still needs an ID). null leaves the label as plain text.
    // It is evaluated again at click time, so it can use whatever the conversation has mentioned since.
    const leadLabel = st => st.textContent.replace(/[:\s]+$/, "");
    function decorateLeads(m) {
      m.querySelectorAll("li > strong:first-child").forEach(st => {
        if (!leadPrompt(leadLabel(st))) return;
        st.classList.add("clickable-lead");
        st.tabIndex = 0; st.setAttribute("role", "button"); st.title = "Click to ask";
      });
    }
    if (leadPrompt) {
      const fire = e => {
        const st = e.target.closest(".clickable-lead");
        if (!st || !messagesEl.contains(st)) return;
        e.preventDefault();
        const r = leadPrompt(leadLabel(st));
        if (!r) return;
        const text = typeof r === "string" ? r : r.text;
        if (typeof r === "string" || r.send !== false) { send(text); return; }
        inputEl.value = text;
        inputEl.dispatchEvent(new Event("input"));
        inputEl.focus();
        inputEl.setSelectionRange(text.length, text.length);
      };
      messagesEl.addEventListener("click", fire);
      messagesEl.addEventListener("keydown", e => { if (e.key === "Enter" || e.key === " ") fire(e); });
    }

    // Suggested-reply buttons: send that text, then retire the buttons so old offers don't pile up.
    messagesEl.addEventListener("click", e => {
      const b = e.target.closest(".reply-chip");
      if (!b || !messagesEl.contains(b) || busy) return;
      b.closest(".replies").remove();
      send(b.dataset.send);
    });

    function add(role, html, extraClass = "") {
      const m = el("div", { class: `msg ${role} ${extraClass}`.trim() }, html);
      if (leadPrompt && role === "agent") decorateLeads(m);
      messagesEl.appendChild(m);
      messagesEl.scrollTop = messagesEl.scrollHeight;
      return m;
    }

    async function send(text) {
      text = (text || "").trim();
      if (!text || busy) return;
      busy = true; sendBtn.disabled = true;
      add("user", escapeHtml(text));
      inputEl.value = ""; inputEl.style.height = "";
      const typing = el("div", { class: "typing" }, "Assistant is typing<span>.</span><span>.</span><span>.</span>");
      messagesEl.appendChild(typing);
      messagesEl.scrollTop = messagesEl.scrollHeight;
      const slow = setTimeout(() => {
        typing.innerHTML = "Still working on it<span>.</span><span>.</span><span>.</span>";
      }, SLOW_HINT_MS);
      const post = () => api("/api/chat", { method: "POST", body: { message: text }, token: getSessionToken(),
                                            timeoutMs: CHAT_TIMEOUT_MS });
      try {
        let r;
        try {
          r = await post();
        } catch (e) {
          if (e.status !== 401 || !onExpired) throw e;
          // Session lost (e.g. the server restarted). Start a new one and resend once.
          if (!(await onExpired())) { typing.remove(); return; }
          messagesEl.appendChild(typing);
          r = await post();
        }
        typing.remove();
        add("agent", renderText(r.text), r.degraded ? "degraded" : "");
        if (onReply) onReply(r, text);
      } catch (e) {
        typing.remove();
        add("agent", escapeHtml(e.message || "Something went wrong. Please try again."), "degraded");
      } finally {
        clearTimeout(slow);
        busy = false; sendBtn.disabled = false; inputEl.focus();
      }
    }

    sendBtn.addEventListener("click", () => send(inputEl.value));
    inputEl.addEventListener("keydown", e => {
      if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(inputEl.value); }
    });
    inputEl.addEventListener("input", () => {
      inputEl.style.height = "auto";
      inputEl.style.height = Math.min(inputEl.scrollHeight, 140) + "px";
    });
    return { send, add, clear: () => { messagesEl.innerHTML = ""; } };
  }

  // Demo mode is a UI switch, not a security boundary (staff/admin stay PIN-gated server-side).
  //   ?demo=on turns it on (1, true, yes or a bare ?demo also work), ?demo=off turns it off (0, false, no). It sticks for the browser tab
  //   so moving between guest, staff and admin keeps it; no parameter and nothing stored = off.
  //   When an admin has turned on demo open access (Admin -> Access, stamped on <html> by the server), every page
  //   is in demo mode for everyone, whatever the URL or tab says: blank-PIN sign-in is a demo, so the UI says so.
  const demo = (() => {
    const KEY = "solstice.demo";
    let chosen = false;   // what this tab asked for via ?demo
    try {
      const q = new URLSearchParams(location.search).get("demo");
      if (q !== null) {
        chosen = !["0", "off", "false", "no"].includes(q.trim().toLowerCase());
        chosen ? sessionStorage.setItem(KEY, "1") : sessionStorage.removeItem(KEY);
      } else {
        chosen = sessionStorage.getItem(KEY) === "1";
      }
      if (chosen && q === null) history.replaceState(null, "", "?demo=on" + location.hash);  // keep the URL honest
    } catch { /* storage blocked: the query parameter alone decides */ }
    const byAdmin = () => document.documentElement.dataset.openAccess === "true";
    const isOn = () => chosen || byAdmin();
    let page = null;      // [viewLabel, current] from init(), so refresh() can redraw

    // Header view switcher, always visible (also on the sign-in screens). Demo mode shows all three
    // views; outside demo mode staff/admin pages still get a way back to the concierge.
    function nav(current) {
      const on = isOn(), q = chosen ? "?demo=on" : "";
      const views = [["guest", "Concierge", "/" + q], ["staff", "Staff chat", "/staff" + q], ["admin", "Admin", "/admin" + q]]
        .filter(([key]) => on || key === "guest");
      if (!on && current === "guest") return;
      const n = el("nav", { class: "viewnav", "aria-label": "Switch view" },
        views.map(([key, label, href]) =>
          `<a href="${href}"${key === current ? ' class="active" aria-current="page"' : ""}>${label}</a>`).join(""));
      const top = document.querySelector(".topbar");
      if (top) top.insertBefore(n, top.querySelector(".actions"));
    }

    // Adds the view switcher and (in demo mode) the notice bar under the header.
    function init(viewLabel, current) {
      page = [viewLabel, current];
      nav(current);
      if (!isOn()) return;
      // Admin-wide demo can't be left from one tab, so it says who turned it on instead of offering "Exit demo".
      const tail = byAdmin() ? "Turned on by an admin (blank-PIN sign-in is on)."
                             : `<a href="/?demo=off">Exit demo</a>`;
      const bar = el("div", { class: "demo-banner", role: "status" },
        `<strong>Demo mode</strong>${viewLabel ? " · " + escapeHtml(viewLabel) : ""} · Sample data, not live guest traffic. ` + tail);
      const top = document.querySelector(".topbar");
      top ? top.after(bar) : document.body.prepend(bar);
    }

    // Redraw after the admin switch changes on this page (admin.html), without a reload.
    function refresh(openAccess) {
      if (openAccess) document.documentElement.dataset.openAccess = "true";
      else delete document.documentElement.dataset.openAccess;
      document.querySelectorAll(".viewnav, .demo-banner").forEach(n => n.remove());
      if (page) init(...page);
    }
    return { get on() { return isOn(); }, init, refresh };
  })();

  // Demo open access: the server stamps data-open-access on <html> when the PIN may be left blank
  // (an admin switch in Admin -> Access, see open_access.py). The server still decides; this only stops the form
  // insisting on a PIN and says so. Pass the PIN <input> of a sign-in form.
  function relaxPin(input) {
    if (document.documentElement.dataset.openAccess !== "true") return;
    input.required = false;
    input.placeholder = "Leave blank in demo";
    const note = el("div", { class: "demo-note" }, "<strong>Demo open access is on.</strong> Sign in with the PIN field empty.");
    input.closest(".field").after(note);
  }

  return { api, getToken, setToken, renderText, escapeHtml, el, chat, demo, relaxPin };
})();
