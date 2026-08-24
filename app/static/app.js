"use strict";

function renderMarkdown(md) {
  const lines = String(md || "").replace(/\r\n/g, "\n").split("\n");
  let html = "";
  let i = 0;

  const inline = (text) =>
    text
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      .replace(/\*([^*]+)\*/g, "<em>$1</em>");

  while (i < lines.length) {
    const line = lines[i];
    if (line.startsWith("```")) {
      let code = "";
      i += 1;
      while (i < lines.length && !lines[i].startsWith("```")) {
        code += lines[i] + "\n";
        i += 1;
      }
      i += 1;
      html += "<pre><code>" + code.replace(/</g, "&lt;") + "</code></pre>";
      continue;
    }

    const hdr = line.match(/^(#{1,4})\s+(.*)$/);
    if (hdr) {
      const depth = hdr[1].length;
      html += `<h${depth}>${inline(hdr[2])}</h${depth}>`;
      i += 1;
      continue;
    }

    if (/^\s*([-*]|\d+\.)\s+/.test(line)) {
      const ordered = /^\s*\d+\.\s+/.test(line);
      const tag = ordered ? "ol" : "ul";
      html += `<${tag}>`;
      while (i < lines.length && /^\s*([-*]|\d+\.)\s+/.test(lines[i])) {
        html += "<li>" + inline(lines[i].replace(/^\s*([-*]|\d+\.)\s+/, "")) + "</li>";
        i += 1;
      }
      html += `</${tag}>`;
      continue;
    }

    if (line.trim() === "") {
      i += 1;
      continue;
    }

    html += "<p>" + inline(line) + "</p>";
    i += 1;
  }
  return html;
}

function showError(target, msg) {
  const el = document.getElementById(target);
  if (!el) return;
  el.textContent = String(msg || "Unknown error");
}

function showJSON(target, value) {
  const el = document.getElementById(target);
  if (!el) return;
  el.textContent = JSON.stringify(value, null, 2);
}

async function api(path, body) {
  const resp = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  const data = await resp.json();
  if (!resp.ok) throw new Error(data.error || "Request failed");
  return data;
}

function setBadge(id, text, on) {
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent = text;
  el.classList.toggle("on", !!on);
  el.classList.toggle("off", !on);
}

document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
    document.querySelectorAll(".panel").forEach((p) => p.classList.remove("active"));
    tab.classList.add("active");
    const panel = document.getElementById("tab-" + tab.dataset.tab);
    if (panel) panel.classList.add("active");

    if (tab.dataset.tab === "kb") {
      loadKB();
    }
  });
});

async function refreshSession() {
  try {
    const me = await (await fetch("/api/me")).json();
    const name = me.authenticated ? me.username || "signed in" : "not authenticated";
    const target = document.getElementById("account-name");
    if (target) target.textContent = name;
    setBadge("badge-auth", "auth: " + (me.authenticated ? "ready" : "off"), !!me.authenticated);
  } catch (_e) {
    setBadge("badge-auth", "auth: unknown", false);
  }
}

async function loadHealth() {
  try {
    const h = await (await fetch("/api/health")).json();
    setBadge("badge-mode", "mode: " + h.mode, h.mode === "llm");
    setBadge("badge-llm", "LLM: " + (h.llm_enabled ? "on" : "off"), h.llm_enabled);
    setBadge("badge-kb", "KB entries: " + h.kb_entries, true);
  } catch (_e) {
    setBadge("badge-mode", "mode: unknown", false);
  }
}

async function loadBugScoutStatus() {
  try {
    const data = await (await fetch("/api/bugscout/features")).json();
    const avail = data.available || {};
    const ok = avail.crashdump && avail.handbook_rag && avail.log_search && avail.live_debug;
    setBadge("badge-bugscout", "BugScout bridge: " + (ok ? "ready" : "partial"), !!ok);
  } catch (_e) {
    setBadge("badge-bugscout", "BugScout bridge: unavailable", false);
  }
}

async function loadProducts() {
  const sel = document.getElementById("bl_product");
  if (!sel) return;
  try {
    const data = await (await fetch("/api/products")).json();
    const keys = Object.keys(data || {}).sort();
    keys.forEach((k) => {
      const opt = document.createElement("option");
      const info = data[k] || {};
      const mq = (info.master_queries || []).length;
      opt.value = k;
      opt.textContent = `${k} - ${info.display || k} (${mq} master queries)`;
      sel.appendChild(opt);
    });
  } catch (_e) {
    // Keep manual query entry usable even if products fail to load.
  }
}

const analyseForm = document.getElementById("analyse-form");
if (analyseForm) {
  analyseForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = document.getElementById("run-btn");
    const report = document.getElementById("report");
    const meta = document.getElementById("meta");
    if (btn) {
      btn.disabled = true;
      btn.textContent = "Analysing...";
    }
    if (report) report.innerHTML = "";
    if (meta) {
      meta.classList.add("hidden");
      meta.innerHTML = "";
    }

    try {
      const data = await api("/api/analyze", {
        hsd_id: document.getElementById("hsd_id").value,
        symptoms: document.getElementById("symptoms").value,
        log_text: document.getElementById("log_text").value || null,
        fetch_attachments: document.getElementById("fetch_attachments").checked,
      });

      if (meta) {
        meta.classList.remove("hidden");
        meta.innerHTML =
          `<span><b>Mode:</b> ${data.mode}</span>` +
          `<span><b>KB Recall:</b> ${data.kb_recall.confidence} (${data.kb_recall.best_score})</span>` +
          `<span><b>KB Action:</b> ${data.kb_action.action}</span>` +
          `<span><b>Platform:</b> ${data.family || "n/a"}</span>` +
          (data.saved_path ? `<span><b>Saved MD:</b> ${data.saved_path}</span>` : "") +
          (data.saved_html_path ? `<span><b>Saved HTML:</b> ${data.saved_html_path}</span>` : "");
      }
      if (report) {
        report.innerHTML = renderMarkdown(data.report_markdown || "No report returned.");
      }
      loadHealth();
      loadKB();
    } catch (err) {
      if (report) {
        report.innerHTML = `<p class="error">${String(err)}</p>`;
      }
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.textContent = "Run Analysis";
      }
    }
  });
}

const logFileEl = document.getElementById("log_file");
if (logFileEl) {
  logFileEl.addEventListener("change", (e) => {
    const file = e.target.files && e.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      const txt = document.getElementById("log_text");
      if (txt) txt.value = String(reader.result || "").slice(0, 2000000);
    };
    reader.readAsText(file);
  });
}

const liveDebugForm = document.getElementById("live-debug-form");
if (liveDebugForm) {
  liveDebugForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = document.getElementById("ld-btn");
    if (btn) {
      btn.disabled = true;
      btn.textContent = "Initializing...";
    }
    try {
      const data = await api("/api/bugscout/live-debug-init", {
        hsd_id: document.getElementById("ld_hsd_id").value,
        execution_mode: document.getElementById("ld_mode").value,
        server: document.getElementById("ld_server").value,
        ssh_user: document.getElementById("ld_user").value,
        max_iterations: Number(document.getElementById("ld_max").value || 10),
        initial_logs_json: document.getElementById("ld_logs").value || null,
      });
      showJSON("live-debug-output", data);
    } catch (err) {
      showError("live-debug-output", err);
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.textContent = "Initialize Session";
      }
    }
  });
}

const liveDebugReportForm = document.getElementById("live-debug-report-form");
if (liveDebugReportForm) {
  liveDebugReportForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = document.getElementById("ldr-btn");
    if (btn) {
      btn.disabled = true;
      btn.textContent = "Rendering...";
    }
    try {
      const data = await api("/api/bugscout/live-debug-report", {
        session_id: document.getElementById("ldr_session_id").value,
      });
      showJSON("live-debug-output", data);
    } catch (err) {
      showError("live-debug-output", err);
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.textContent = "Render Session Reports";
      }
    }
  });
}

const batchLearnForm = document.getElementById("batch-learn-form");
if (batchLearnForm) {
  batchLearnForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = document.getElementById("bl-btn");
    if (btn) {
      btn.disabled = true;
      btn.textContent = "Learning...";
    }
    try {
      const ids = String(document.getElementById("bl_ids").value || "")
        .split(",")
        .map((x) => x.trim())
        .filter(Boolean);
      const data = await api("/api/batch_learn", {
        product: document.getElementById("bl_product").value || null,
        query_id: document.getElementById("bl_query").value || null,
        hsd_ids: ids.length ? ids : null,
        limit: Number(document.getElementById("bl_limit").value || 100),
      });
      showJSON("batch-learn-output", data);
      loadKB();
      loadHealth();
    } catch (err) {
      showError("batch-learn-output", err);
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.textContent = "Run Batch Learn";
      }
    }
  });
}

const bbPrepareForm = document.getElementById("bb-prepare-form");
if (bbPrepareForm) {
  bbPrepareForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = document.getElementById("bb-prepare-btn");
    if (btn) {
      btn.disabled = true;
      btn.textContent = "Preparing...";
    }
    try {
      const data = await api("/api/bugscout/batch-prepare", {
        input_csv: document.getElementById("bb_prepare_csv").value,
      });
      showJSON("bugbatch-output", data);
      loadBugScoutRuns();
    } catch (err) {
      showError("bugbatch-output", err);
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.textContent = "Prepare Prompts";
      }
    }
  });
}

const bbFinalizeForm = document.getElementById("bb-finalize-form");
if (bbFinalizeForm) {
  bbFinalizeForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = document.getElementById("bb-finalize-btn");
    if (btn) {
      btn.disabled = true;
      btn.textContent = "Finalizing...";
    }
    try {
      const data = await api("/api/bugscout/batch-finalize", {
        responses_jsonl: document.getElementById("bb_responses_jsonl").value,
        output_dir: document.getElementById("bb_finalize_run").value || null,
      });
      showJSON("bugbatch-output", data);
      loadBugScoutRuns();
    } catch (err) {
      showError("bugbatch-output", err);
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.textContent = "Finalize CSV";
      }
    }
  });
}

const bbReportForm = document.getElementById("bb-report-form");
if (bbReportForm) {
  bbReportForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = document.getElementById("bb-report-btn");
    if (btn) {
      btn.disabled = true;
      btn.textContent = "Generating...";
    }
    try {
      const data = await api("/api/bugscout/batch-report", {
        input_csv: document.getElementById("bb_report_csv").value,
        output_dir: document.getElementById("bb_report_run").value || null,
      });
      showJSON("bugbatch-output", data);
      loadBugScoutRuns();
    } catch (err) {
      showError("bugbatch-output", err);
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.textContent = "Generate HTML Report";
      }
    }
  });
}

async function loadBugScoutRuns() {
  try {
    const data = await (await fetch("/api/bugscout/runs")).json();
    showJSON("bugbatch-runs", data);
  } catch (err) {
    showError("bugbatch-runs", err);
  }
}

document.getElementById("bb-refresh-runs")?.addEventListener("click", loadBugScoutRuns);

const crashdumpForm = document.getElementById("crashdump-form");
if (crashdumpForm) {
  crashdumpForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = document.getElementById("cd-btn");
    if (btn) {
      btn.disabled = true;
      btn.textContent = "Parsing...";
    }
    try {
      const data = await api("/api/bugscout/crashdump", {
        input_path: document.getElementById("cd_input").value,
        output_dir: document.getElementById("cd_output").value || null,
      });
      showJSON("crashdump-output", data);
    } catch (err) {
      showError("crashdump-output", err);
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.textContent = "Parse Crashdump";
      }
    }
  });
}

const logIndexForm = document.getElementById("log-index-form");
if (logIndexForm) {
  logIndexForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = document.getElementById("ls-index-btn");
    if (btn) {
      btn.disabled = true;
      btn.textContent = "Indexing...";
    }
    try {
      const data = await api("/api/bugscout/log-index", {
        file_path: document.getElementById("ls_file").value,
      });
      showJSON("logsearch-output", data);
    } catch (err) {
      showError("logsearch-output", err);
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.textContent = "Index Log";
      }
    }
  });
}

const logSearchForm = document.getElementById("log-search-form");
if (logSearchForm) {
  logSearchForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = document.getElementById("ls-search-btn");
    if (btn) {
      btn.disabled = true;
      btn.textContent = "Searching...";
    }

    try {
      const keys = String(document.getElementById("ls_keys").value || "")
        .split(",")
        .map((k) => k.trim())
        .filter(Boolean);

      const data = await api("/api/bugscout/log-search", {
        file_path: document.getElementById("ls_file").value,
        keywords: keys,
        lines: Number(document.getElementById("ls_lines").value || 60),
        section: document.getElementById("ls_section").value || null,
      });
      showJSON("logsearch-output", data);
    } catch (err) {
      showError("logsearch-output", err);
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.textContent = "Search Indexed Log";
      }
    }
  });
}

const handbookForm = document.getElementById("handbook-form");
if (handbookForm) {
  handbookForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = document.getElementById("hb-btn");
    const list = document.getElementById("handbook-results");
    if (btn) {
      btn.disabled = true;
      btn.textContent = "Retrieving...";
    }
    if (list) list.innerHTML = "";

    try {
      const data = await api("/api/bugscout/handbook-search", {
        query: document.getElementById("hb_query").value,
        top_k: Number(document.getElementById("hb_topk").value || 4),
      });

      if (list) {
        if (!data.matches || !data.matches.length) {
          list.innerHTML = "<p>No handbook matches found.</p>";
        } else {
          data.matches.forEach((m) => {
            const card = document.createElement("div");
            card.className = "kb-card";
            card.innerHTML =
              `<div class="sig">#${m.rank} ${m.title}</div>` +
              `<div><b>Source:</b> ${m.source_file} | <b>Score:</b> ${m.score}</div>` +
              `<div>${String(m.content_preview || "").replace(/</g, "&lt;")}</div>`;
            list.appendChild(card);
          });
        }
      }
    } catch (err) {
      if (list) list.innerHTML = `<p class="error">${String(err)}</p>`;
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.textContent = "Retrieve";
      }
    }
  });
}

async function loadKB() {
  const list = document.getElementById("kb-list");
  if (!list) return;
  list.innerHTML = "Loading KB...";
  try {
    const data = await (await fetch("/api/kb")).json();
    const entries = data.entries || [];
    if (!entries.length) {
      list.innerHTML = "<p>No learned cases yet.</p>";
      return;
    }

    list.innerHTML = "";
    entries.forEach((entry) => {
      const card = document.createElement("div");
      card.className = "kb-card";
      card.innerHTML =
        `<div class="sig">${entry.sig_key}</div>` +
        `<div><b>Root cause:</b> ${entry.root_cause || "-"} <span class="tag">${entry.root_cause_confidence || "hypothesis"}</span></div>` +
        `<div><b>Resolution:</b> ${entry.resolution || "-"}</div>` +
        `<div class="muted">Source HSD: ${entry.source_hsd || "-"} | Updated: ${entry.updated_at || "-"} | Hits: ${entry.hits || 0}</div>`;
      list.appendChild(card);
    });
  } catch (err) {
    list.innerHTML = `<p class="error">${String(err)}</p>`;
  }
}

document.getElementById("refresh-kb")?.addEventListener("click", loadKB);

document.getElementById("refresh-cache")?.addEventListener("click", async () => {
  try {
    const data = await (await fetch("/api/bugscout/log-cache")).json();
    showJSON("cache-output", data);
  } catch (err) {
    showError("cache-output", err);
  }
});

refreshSession();
loadHealth();
loadBugScoutStatus();
loadProducts();
loadKB();
loadBugScoutRuns();
