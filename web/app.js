/* ============================================================
 * Céges Gépjármű Magyar Közlöny Riport — vanilla JS frontend
 * ============================================================ */

(function () {
  "use strict";

  // ---------- URL banner ----------
  const banner = document.getElementById("url-banner");
  if (banner) {
    banner.textContent = window.location.origin;
  }

  // ---------- small helpers ----------
  async function jget(path) {
    const r = await fetch(path, { cache: "no-store" });
    if (!r.ok) {
      throw new Error(`${path} -> HTTP ${r.status}`);
    }
    return r.json();
  }
  async function jpost(path, body) {
    const r = await fetch(path, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body || {}),
    });
    let data = null;
    try { data = await r.json(); } catch (_) { /* ignore */ }
    return { ok: r.ok, status: r.status, data };
  }
  function setText(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = value == null || value === "" ? "–" : String(value);
  }

  // ---------- 1. Status ----------
  async function refreshStatus() {
    try {
      const d = await jget("/api/health");
      setText("status-ok", d.status || "–");
      setText("status-vercel", d.vercel ? "igen" : "nem");
      setText("status-ver", d.ver || "–");
    } catch (e) {
      setText("status-ok", "❌ " + e.message);
    }
  }
  document.getElementById("btn-refresh-status").addEventListener("click", refreshStatus);

  // ---------- 2. Config ----------
  async function refreshConfig() {
    const pre = document.getElementById("config-content");
    try {
      const d = await jget("/api/config");
      pre.textContent = JSON.stringify(d, null, 2);
    } catch (e) {
      pre.textContent = "❌ " + e.message;
    }
  }
  document.getElementById("btn-refresh-config").addEventListener("click", refreshConfig);

  // ---------- 3. State ----------
  async function refreshState() {
    try {
      const d = await jget("/api/state");
      setText("state-dbpath", d.db_path || "–");
      setText("state-exists", d.exists ? "igen" : "nem");
      setText("state-last-run", (d.meta && d.meta.last_run) || "–");
      setText("state-total", d.total_reported || 0);
    } catch (e) {
      setText("state-dbpath", "❌ " + e.message);
    }
  }
  document.getElementById("btn-refresh-state").addEventListener("click", refreshState);

  document.getElementById("btn-init-db").addEventListener("click", async () => {
    const force = window.confirm(
      "Init/Reset DB: minden tárolt adat törlésre kerül a state DB-ben. Folytatod?"
    );
    const url = force ? "/api/init-db?force=true" : "/api/init-db";
    const r = await jpost(url, {});
    if (r.ok && r.data && r.data.ok) {
      window.alert(`OK: ${r.data.path}${force ? " (force)" : ""}`);
      refreshState();
    } else {
      window.alert("Hiba: " + JSON.stringify(r.data));
    }
  });

  // ---------- 4. Run ----------
  const form = document.getElementById("run-form");
  const btnRun = document.getElementById("btn-run");
  const progressBox = document.getElementById("run-progress");
  const progressText = document.getElementById("run-progress-text");

  let progressTimer = null;
  let runStartMs = 0;

  function startProgressUi() {
    runStartMs = Date.now();
    progressBox.classList.remove("hidden");
    progressText.textContent = "Indulás… (0s)";
    progressTimer = setInterval(() => {
      const s = Math.floor((Date.now() - runStartMs) / 1000);
      progressText.textContent = `Fut… (${s}s eltelt)`;
    }, 2000);
  }
  function stopProgressUi() {
    if (progressTimer) { clearInterval(progressTimer); progressTimer = null; }
    progressBox.classList.add("hidden");
  }

  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();

    const body = {
      seed: document.getElementById("opt-seed").checked,
      lookback_days: parseInt(document.getElementById("opt-lookback").value, 10) || 30,
      dry_run: document.getElementById("opt-dry-run").checked,
    };

    btnRun.disabled = true;
    startProgressUi();

    try {
      const r = await jpost("/api/run", body);
      if (!r.ok || (r.data && r.data.ok === false)) {
        const msg = r.data
          ? (r.data.error || JSON.stringify(r.data))
          : `HTTP ${r.status}`;
        showErrorPanel(msg, r.data && r.data.traceback);
        return;
      }
      showResult(r.data);
    } catch (e) {
      showErrorPanel("Hálózati hiba: " + e.message, null);
    } finally {
      stopProgressUi();
      btnRun.disabled = false;
      refreshState(); // last_run / total_reported may have changed
    }
  });

  // ---------- 5. Result panel ----------
  const resultCard = document.getElementById("result-card");
  const reportPre = document.getElementById("res-report");
  const warningsBox = document.getElementById("res-warnings");
  const errorsBox = document.getElementById("res-errors");

  function showErrorPanel(msg, trace) {
    resultCard.classList.remove("hidden");
    setText("res-new-items", "–");
    setText("res-issues", "–");
    setText("res-duration", "–");
    setText("res-email", "–");
    setText("res-filename", "–");
    reportPre.textContent = trace
      ? `❌ ${msg}\n\n${trace}`
      : `❌ ${msg}`;
    warningsBox.classList.add("hidden");
    errorsBox.classList.add("hidden");
    document.getElementById("btn-download-report").setAttribute("href", "#");
  }

  function showResult(data) {
    resultCard.classList.remove("hidden");
    setText("res-new-items", data.new_items_count);
    setText("res-issues", data.issues_scanned);
    setText("res-duration", `${data.duration_s}s`);
    setText("res-email", data.email_status);
    setText("res-filename", data.report_filename || "(nincs — dry run vagy üres)");

    // warnings
    if (data.warnings && data.warnings.length) {
      warningsBox.classList.remove("hidden");
      const ul = document.getElementById("res-warnings-list");
      ul.innerHTML = "";
      for (const w of data.warnings) {
        const li = document.createElement("li");
        li.textContent = w;
        ul.appendChild(li);
      }
    } else {
      warningsBox.classList.add("hidden");
    }

    // errors
    if (data.errors && data.errors.length) {
      errorsBox.classList.remove("hidden");
      const ul = document.getElementById("res-errors-list");
      ul.innerHTML = "";
      for (const e of data.errors) {
        const li = document.createElement("li");
        li.textContent = e;
        ul.appendChild(li);
      }
    } else {
      errorsBox.classList.add("hidden");
    }

    // report body
    reportPre.textContent = data.report_content || "(üres riport)";

    // download link
    const dl = document.getElementById("btn-download-report");
    if (data.report_filename) {
      dl.setAttribute("href", `/api/report?file=${encodeURIComponent(data.report_filename)}`);
    } else {
      dl.setAttribute("href", "#");
    }
  }

  // copy button
  document.getElementById("btn-copy-report").addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(reportPre.textContent || "");
      const btn = document.getElementById("btn-copy-report");
      const orig = btn.textContent;
      btn.textContent = "✓ Másolva";
      setTimeout(() => { btn.textContent = orig; }, 1500);
    } catch (e) {
      window.alert("Másolás sikertelen: " + e.message);
    }
  });

  // ---------- initial load ----------
  refreshStatus();
  refreshConfig();
  refreshState();
})();
