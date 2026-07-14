"use strict";

// ---- Minimal offline Markdown renderer (headings, bold, code, lists, tables) ----
function renderMarkdown(md) {
  const lines = md.replace(/\r\n/g, "\n").split("\n");
  let html = "";
  let i = 0;
  const inline = (t) =>
    t.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
     .replace(/`([^`]+)`/g, "<code>$1</code>")
     .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
     .replace(/\*([^*]+)\*/g, "<em>$1</em>");
  while (i < lines.length) {
    let line = lines[i];
    if (line.startsWith("```")) {
      let code = ""; i++;
      while (i < lines.length && !lines[i].startsWith("```")) { code += lines[i] + "\n"; i++; }
      i++; html += "<pre><code>" + code.replace(/</g, "&lt;") + "</code></pre>"; continue;
    }
    if (line.includes("|") && i + 1 < lines.length && /^\s*\|?[\s:|-]+\|?\s*$/.test(lines[i + 1])) {
      const parseRow = (r) => r.replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
      const header = parseRow(line); i += 2; let rows = [];
      while (i < lines.length && lines[i].includes("|")) { rows.push(parseRow(lines[i])); i++; }
      html += "<table><thead><tr>";
      header.forEach((h) => (html += "<th>" + inline(h) + "</th>"));
      html += "</tr></thead><tbody>";
      rows.forEach((r) => { html += "<tr>"; r.forEach((c) => (html += "<td>" + inline(c) + "</td>")); html += "</tr>"; });
      html += "</tbody></table>"; continue;
    }
    let m;
    if ((m = line.match(/^(#{1,4})\s+(.*)$/))) { const l = m[1].length; html += `<h${l}>${inline(m[2])}</h${l}>`; i++; continue; }
    if (line.startsWith(">")) {
      let q = ""; while (i < lines.length && lines[i].startsWith(">")) { q += lines[i].replace(/^>\s?/, "") + " "; i++; }
      html += "<blockquote>" + inline(q) + "</blockquote>"; continue;
    }
    if (/^\s*([-*]|\d+\.)\s+/.test(line)) {
      const ordered = /^\s*\d+\.\s+/.test(line); const tag = ordered ? "ol" : "ul"; html += `<${tag}>`;
      while (i < lines.length && /^\s*([-*]|\d+\.)\s+/.test(lines[i])) { html += "<li>" + inline(lines[i].replace(/^\s*([-*]|\d+\.)\s+/, "")) + "</li>"; i++; }
      html += `</${tag}>`; continue;
    }
    if (line.trim() === "") { i++; continue; }
    html += "<p>" + inline(line) + "</p>"; i++;
  }
  return html;
}

// ---- Tabs ----
document.querySelectorAll(".tab").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((b) => b.classList.remove("active"));
    document.querySelectorAll(".panel").forEach((p) => p.classList.remove("active"));
    btn.classList.add("active");
    document.getElementById("tab-" + btn.dataset.tab).classList.add("active");
    if (btn.dataset.tab === "kb") loadKB();
  });
});

function setBadge(id, text, on) {
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent = text;
  el.classList.toggle("on", !!on);
  el.classList.toggle("off", !on);
}

// ---- Session / auth ----
let signedIn = false;
async function refreshSession() {
  try {
    const me = await (await fetch("/api/me")).json();
    signedIn = !!me.authenticated;
    document.getElementById("account-name").textContent =
      signedIn ? (me.username || "signed in") : "not signed in";
    document.getElementById("logout-btn").classList.toggle("hidden", !signedIn);
    document.getElementById("login-overlay").classList.toggle("hidden", signedIn);
    setBadge("badge-auth", "auth: " + (signedIn ? "signed in" : "sign in"), signedIn);
  } catch (e) { /* ignore */ }
}

async function loadHealth() {
  try {
    const h = await (await fetch("/api/health")).json();
    setBadge("badge-mode", "mode: " + h.mode, h.mode === "llm");
    setBadge("badge-llm", "LLM: " + (h.llm_enabled ? "on" : "off"), h.llm_enabled);
    setBadge("badge-kb", "KB: " + h.kb_entries + " entries", true);
  } catch (e) { /* ignore */ }
}

// ---- Login ----
document.getElementById("login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const btn = document.getElementById("login-submit");
  const err = document.getElementById("login-error");
  err.textContent = ""; btn.disabled = true; btn.textContent = "Signing in…";
  try {
    const r = await fetch("/api/login", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        username: document.getElementById("login-user").value,
        password: document.getElementById("login-pass").value,
      }),
    });
    const d = await r.json();
    if (!r.ok) { err.textContent = d.error || "Sign-in failed"; return; }
    document.getElementById("login-pass").value = "";
    await refreshSession();
  } catch (ex) { err.textContent = String(ex); }
  finally { btn.disabled = false; btn.textContent = "Sign in"; }
});

document.getElementById("logout-btn").addEventListener("click", async () => {
  await fetch("/api/logout", { method: "POST" });
  await refreshSession();
});

// ---- Analyse ----
document.getElementById("analyse-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const btn = document.getElementById("run-btn");
  const report = document.getElementById("report");
  const meta = document.getElementById("meta");
  btn.disabled = true; btn.textContent = "Analysing…"; report.innerHTML = ""; meta.classList.add("hidden");
  try {
    const r = await fetch("/api/analyze", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        hsd_id: document.getElementById("hsd_id").value,
        symptoms: document.getElementById("symptoms").value,
      }),
    });
    if (r.status === 401) {
      document.getElementById("login-overlay").classList.remove("hidden");
      report.innerHTML = `<p class="error">Please sign in first.</p>`; return;
    }
    const data = await r.json();
    if (!r.ok) { report.innerHTML = `<p class="error">${data.error || "Request failed"}</p>`; return; }
    meta.classList.remove("hidden");
    meta.innerHTML =
      `<span><span class="k">Mode:</span> ${data.mode}</span>` +
      `<span><span class="k">KB recall:</span> ${data.kb_recall.confidence} (${data.kb_recall.best_score})</span>` +
      `<span><span class="k">KB write-back:</span> ${data.kb_action.action}</span>` +
      `<span><span class="k">Platform:</span> ${data.family || "n/a"}</span>`;
    report.innerHTML = renderMarkdown(data.report_markdown || "*No report returned.*");
    loadHealth();
  } catch (err) { report.innerHTML = `<p class="error">${err}</p>`; }
  finally { btn.disabled = false; btn.textContent = "Analyse"; }
});

// ---- KB browser ----
async function loadKB() {
  const list = document.getElementById("kb-list");
  list.innerHTML = "Loading…";
  const data = await (await fetch("/api/kb")).json();
  if (!data.entries || !data.entries.length) {
    list.innerHTML = "<p>No learned cases yet. Run an analysis to seed the KB.</p>"; return;
  }
  list.innerHTML = "";
  data.entries.forEach((e) => {
    const card = document.createElement("div");
    card.className = "kb-card";
    card.innerHTML =
      `<div class="sig">${e.sig_key}</div>` +
      `<div>Root cause: ${e.root_cause || "—"} <span class="tag">${e.root_cause_confidence}</span>` +
      `<span class="tag">${e.confidence_tag}</span></div>` +
      `<div>Resolution: ${e.resolution || "—"} ` + (e.source_hsd ? `(src ${e.source_hsd})` : "") + `</div>` +
      `<div style="color:var(--muted)">updated ${e.updated_at} · hits ${e.hits}</div>`;
    list.appendChild(card);
  });
}
document.getElementById("refresh-kb").addEventListener("click", loadKB);

refreshSession();
loadHealth();
