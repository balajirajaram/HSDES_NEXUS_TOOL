"use strict";

const TOKEN_KEY = "hsdes_token";
function getToken() {
  return localStorage.getItem(TOKEN_KEY) || "";
}

// ---- Minimal offline Markdown renderer (headings, bold, code, lists, tables) ----
function renderMarkdown(md) {
  const lines = md.replace(/\r\n/g, "\n").split("\n");
  let html = "";
  let i = 0;

  const inline = (t) =>
    t
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      .replace(/\*([^*]+)\*/g, "<em>$1</em>");

  while (i < lines.length) {
    let line = lines[i];

    // fenced code
    if (line.startsWith("```")) {
      let code = "";
      i++;
      while (i < lines.length && !lines[i].startsWith("```")) {
        code += lines[i] + "\n";
        i++;
      }
      i++;
      html += "<pre><code>" + code.replace(/</g, "&lt;") + "</code></pre>";
      continue;
    }

    // table
    if (line.includes("|") && i + 1 < lines.length && /^\s*\|?[\s:|-]+\|?\s*$/.test(lines[i + 1])) {
      const parseRow = (r) => r.replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
      const header = parseRow(line);
      i += 2;
      let rows = [];
      while (i < lines.length && lines[i].includes("|")) {
        rows.push(parseRow(lines[i]));
        i++;
      }
      html += "<table><thead><tr>";
      header.forEach((h) => (html += "<th>" + inline(h) + "</th>"));
      html += "</tr></thead><tbody>";
      rows.forEach((r) => {
        html += "<tr>";
        r.forEach((c) => (html += "<td>" + inline(c) + "</td>"));
        html += "</tr>";
      });
      html += "</tbody></table>";
      continue;
    }

    // headings
    let m;
    if ((m = line.match(/^(#{1,4})\s+(.*)$/))) {
      const lvl = m[1].length;
      html += `<h${lvl}>${inline(m[2])}</h${lvl}>`;
      i++;
      continue;
    }

    // blockquote
    if (line.startsWith(">")) {
      let q = "";
      while (i < lines.length && lines[i].startsWith(">")) {
        q += lines[i].replace(/^>\s?/, "") + " ";
        i++;
      }
      html += "<blockquote>" + inline(q) + "</blockquote>";
      continue;
    }

    // lists (ordered or unordered)
    if (/^\s*([-*]|\d+\.)\s+/.test(line)) {
      const ordered = /^\s*\d+\.\s+/.test(line);
      const tag = ordered ? "ol" : "ul";
      html += `<${tag}>`;
      while (i < lines.length && /^\s*([-*]|\d+\.)\s+/.test(lines[i])) {
        const item = lines[i].replace(/^\s*([-*]|\d+\.)\s+/, "");
        html += "<li>" + inline(item) + "</li>";
        i++;
      }
      html += `</${tag}>`;
      continue;
    }

    // blank / paragraph
    if (line.trim() === "") {
      i++;
      continue;
    }
    html += "<p>" + inline(line) + "</p>";
    i++;
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

// ---- Health / status badges ----
async function loadHealth() {
  try {
    const r = await fetch("/api/health");
    const h = await r.json();
    setBadge("badge-mode", "mode: " + h.mode, h.mode === "llm");
    const hasToken = !!getToken();
    setBadge("badge-hsdes", "HSDES: " + (hasToken ? "your token" : (h.server_hsdes_fallback ? "server" : "off")), hasToken || h.server_hsdes_fallback);
    setBadge("badge-llm", "LLM: " + (h.llm_enabled ? "on" : "off"), h.llm_enabled);
    setBadge("badge-kb", "KB: " + h.kb_entries + " entries", true);
  } catch (e) {
    /* ignore */
  }
}

function setBadge(id, text, on) {
  const el = document.getElementById(id);
  el.textContent = text;
  el.classList.toggle("on", !!on);
  el.classList.toggle("off", !on);
}

// ---- Analyse ----
document.getElementById("analyse-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const btn = document.getElementById("run-btn");
  const report = document.getElementById("report");
  const meta = document.getElementById("meta");
  btn.disabled = true;
  btn.textContent = "Analysing…";
  report.innerHTML = "";
  meta.classList.add("hidden");

  try {
    const r = await fetch("/api/analyze", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(getToken() ? { "X-HSDES-Token": getToken() } : {}),
      },
      body: JSON.stringify({
        hsd_id: document.getElementById("hsd_id").value,
        symptoms: document.getElementById("symptoms").value,
      }),
    });
    const data = await r.json();
    if (!r.ok) {
      report.innerHTML = `<p class="error">${data.error || "Request failed"}</p>`;
      return;
    }
    meta.classList.remove("hidden");
    meta.innerHTML =
      `<span><span class="k">Mode:</span> ${data.mode}</span>` +
      `<span><span class="k">KB recall:</span> ${data.kb_recall.confidence} ` +
      `(${data.kb_recall.best_score})</span>` +
      `<span><span class="k">KB write-back:</span> ${data.kb_action.action}</span>` +
      `<span><span class="k">Family:</span> ${data.family || "n/a"}</span>`;
    report.innerHTML = renderMarkdown(data.report_markdown || "*No report returned.*");
    loadHealth();
  } catch (err) {
    report.innerHTML = `<p class="error">${err}</p>`;
  } finally {
    btn.disabled = false;
    btn.textContent = "Analyse";
  }
});

// ---- KB browser ----
async function loadKB() {
  const list = document.getElementById("kb-list");
  list.innerHTML = "Loading…";
  const r = await fetch("/api/kb");
  const data = await r.json();
  if (!data.entries.length) {
    list.innerHTML = "<p>No learned cases yet. Run an analysis to seed the KB.</p>";
    return;
  }
  list.innerHTML = "";
  data.entries.forEach((e) => {
    const card = document.createElement("div");
    card.className = "kb-card";
    card.innerHTML =
      `<div class="sig">${e.sig_key}</div>` +
      `<div>Root cause: ${e.root_cause || "—"} ` +
      `<span class="tag">${e.root_cause_confidence}</span>` +
      `<span class="tag">${e.confidence_tag}</span></div>` +
      `<div>Resolution: ${e.resolution || "—"} ` +
      (e.source_hsd ? `(src ${e.source_hsd})` : "") +
      `</div>` +
      `<div style="color:var(--muted)">updated ${e.updated_at} · hits ${e.hits}</div>`;
    list.appendChild(card);
  });
}

document.getElementById("refresh-kb").addEventListener("click", loadKB);

// ---- Settings: per-user token (browser-only) ----
function renderTokenState() {
  const el = document.getElementById("token-state");
  el.textContent = getToken() ? "Token saved in this browser." : "No token set (OFFLINE mode).";
}
document.getElementById("save-token").addEventListener("click", () => {
  const v = document.getElementById("hsdes-token").value.trim();
  if (v) localStorage.setItem(TOKEN_KEY, v);
  document.getElementById("hsdes-token").value = "";
  renderTokenState();
  loadHealth();
});
document.getElementById("clear-token").addEventListener("click", () => {
  localStorage.removeItem(TOKEN_KEY);
  renderTokenState();
  loadHealth();
});
renderTokenState();

loadHealth();
