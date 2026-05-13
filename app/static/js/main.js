(function () {
  const STORAGE_KEY = "cvd_history";
  const SCHEMA_VERSION = 1;
  const MAX_ENTRIES = 100;

  const RISK_NUMERIC = { LOW: 1, INTERMEDIARY: 2, HIGH: 3 };
  const RISK_LABEL = { LOW: "Low", INTERMEDIARY: "Medium", HIGH: "High" };
  const RISK_BADGE = {
    LOW: "bg-success",
    INTERMEDIARY: "bg-warning text-dark",
    HIGH: "bg-danger",
  };
  const RISK_COLOR = { LOW: "#198754", INTERMEDIARY: "#ffc107", HIGH: "#dc3545" };

  function storageAvailable() {
    try {
      const probe = "__cvd_probe__";
      window.localStorage.setItem(probe, "1");
      window.localStorage.removeItem(probe);
      return true;
    } catch (e) {
      return false;
    }
  }

  function loadHistory() {
    if (!storageAvailable()) return [];
    try {
      const raw = window.localStorage.getItem(STORAGE_KEY);
      if (!raw) return [];
      const parsed = JSON.parse(raw);
      if (parsed && Array.isArray(parsed.items)) return parsed.items;
      return [];
    } catch (e) {
      return [];
    }
  }

  function saveHistory(items) {
    if (!storageAvailable()) return;
    const payload = JSON.stringify({ v: SCHEMA_VERSION, items: items });
    try {
      window.localStorage.setItem(STORAGE_KEY, payload);
    } catch (e) {
      // Quota exceeded — drop oldest half and try once more.
      try {
        const trimmed = items.slice(0, Math.floor(items.length / 2));
        window.localStorage.setItem(
          STORAGE_KEY,
          JSON.stringify({ v: SCHEMA_VERSION, items: trimmed })
        );
      } catch (e2) {
        /* give up silently */
      }
    }
  }

  function hashId(entry) {
    const key = [
      entry.age,
      entry.height,
      entry.weight,
      entry.activity,
      entry.smoking,
      entry.family,
      entry.bmi,
      entry.risk_class,
      entry.confidence,
    ].join("|");
    let h = 0;
    for (let i = 0; i < key.length; i++) {
      h = (h * 31 + key.charCodeAt(i)) | 0;
    }
    return Math.abs(h).toString(36);
  }

  function addEntry(entry) {
    entry.id = hashId(entry);
    const items = loadHistory();
    if (items.some(function (e) { return e.id === entry.id; })) return false;
    items.push(entry);
    items.sort(function (a, b) { return b.ts - a.ts; });
    if (items.length > MAX_ENTRIES) items.length = MAX_ENTRIES;
    saveHistory(items);
    return true;
  }

  function removeEntry(id) {
    const items = loadHistory().filter(function (e) { return e.id !== id; });
    saveHistory(items);
  }

  function clearHistory() {
    saveHistory([]);
  }

  function readFromResultPage() {
    const node = document.getElementById("history-source");
    if (!node) return;
    const d = node.dataset;
    const entry = {
      ts: Date.now(),
      age: Number(d.age),
      height: Number(d.height),
      weight: Number(d.weight),
      activity: d.activity || "",
      smoking: d.smoking || "",
      family: d.family || "",
      bmi: d.bmi ? Number(d.bmi) : null,
      risk_class: (d.riskClass || "").toUpperCase(),
      confidence: d.confidence !== "" && d.confidence != null ? Number(d.confidence) : null,
    };
    addEntry(entry);
  }

  function formatDate(ts) {
    try {
      return new Date(ts).toLocaleString();
    } catch (e) {
      return String(ts);
    }
  }

  function riskBadge(rc) {
    const label = RISK_LABEL[rc] || rc || "—";
    const cls = RISK_BADGE[rc] || "bg-secondary";
    return '<span class="badge rounded-pill ' + cls + '">' + escapeHtml(label) + "</span>";
  }

  function escapeHtml(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function renderTable(items) {
    if (!items.length) return "";
    const rows = items.map(function (e) {
      const bmi = e.bmi != null ? e.bmi.toFixed(1) : "—";
      const conf = e.confidence != null ? (e.confidence * 100).toFixed(1) + "%" : "—";
      return (
        "<tr>" +
        '<td class="text-nowrap small">' + escapeHtml(formatDate(e.ts)) + "</td>" +
        "<td>" + escapeHtml(e.age) + "</td>" +
        "<td>" + escapeHtml(e.height) + "</td>" +
        "<td>" + escapeHtml(e.weight) + "</td>" +
        "<td>" + bmi + "</td>" +
        "<td>" + escapeHtml(e.activity) + "</td>" +
        "<td>" + escapeHtml(e.smoking) + "</td>" +
        "<td>" + escapeHtml(e.family) + "</td>" +
        "<td>" + riskBadge(e.risk_class) + "</td>" +
        "<td>" + conf + "</td>" +
        '<td><button type="button" class="btn btn-sm btn-outline-secondary" data-remove-id="' +
        escapeHtml(e.id) + '" aria-label="Remove entry">&times;</button></td>' +
        "</tr>"
      );
    }).join("");
    return (
      '<div class="table-responsive">' +
      '<table class="table table-sm align-middle mb-0">' +
      "<thead><tr>" +
      "<th>Date</th><th>Age</th><th>H (cm)</th><th>W (kg)</th><th>BMI</th>" +
      "<th>Activity</th><th>Smoke</th><th>Family</th><th>Risk</th><th>Conf.</th><th></th>" +
      "</tr></thead>" +
      "<tbody>" + rows + "</tbody>" +
      "</table></div>"
    );
  }

  let chartInstance = null;

  function renderChart(items) {
    const canvas = document.getElementById("history-chart");
    if (!canvas) return;
    if (chartInstance) {
      chartInstance.destroy();
      chartInstance = null;
    }
    if (!items.length || typeof Chart === "undefined") return;

    const sorted = items.slice().sort(function (a, b) { return a.ts - b.ts; });
    const labels = sorted.map(function (e) { return new Date(e.ts).toLocaleDateString(); });
    const bmiData = sorted.map(function (e) { return e.bmi; });
    const riskData = sorted.map(function (e) { return RISK_NUMERIC[e.risk_class] || null; });
    const pointColors = sorted.map(function (e) { return RISK_COLOR[e.risk_class] || "#6c757d"; });

    chartInstance = new Chart(canvas.getContext("2d"), {
      type: "line",
      data: {
        labels: labels,
        datasets: [
          {
            label: "BMI",
            data: bmiData,
            yAxisID: "y",
            borderColor: "#0d6efd",
            backgroundColor: "#0d6efd",
            tension: 0.2,
            spanGaps: true,
          },
          {
            label: "Risk level",
            data: riskData,
            yAxisID: "y1",
            borderColor: "#6c757d",
            backgroundColor: pointColors,
            pointBackgroundColor: pointColors,
            pointRadius: 5,
            tension: 0,
            stepped: true,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        plugins: {
          tooltip: {
            callbacks: {
              label: function (ctx) {
                if (ctx.dataset.yAxisID === "y1") {
                  const labelMap = { 1: "Low", 2: "Medium", 3: "High" };
                  return "Risk: " + (labelMap[ctx.parsed.y] || "—");
                }
                return "BMI: " + (ctx.parsed.y != null ? ctx.parsed.y.toFixed(1) : "—");
              },
            },
          },
        },
        scales: {
          y: {
            type: "linear",
            position: "left",
            title: { display: true, text: "BMI" },
          },
          y1: {
            type: "linear",
            position: "right",
            min: 0.5,
            max: 3.5,
            ticks: {
              stepSize: 1,
              callback: function (v) { return ({ 1: "Low", 2: "Med", 3: "High" })[v] || ""; },
            },
            grid: { drawOnChartArea: false },
            title: { display: true, text: "Risk" },
          },
        },
      },
    });
  }

  function renderTrend(items) {
    const target = document.getElementById("history-trend");
    if (!target) return;
    target.innerHTML = "";
    if (items.length < 3) return;

    const sorted = items.slice().sort(function (a, b) { return a.ts - b.ts; });
    const first = sorted[0];
    const last = sorted[sorted.length - 1];

    const firstRank = RISK_NUMERIC[first.risk_class] || 0;
    const lastRank = RISK_NUMERIC[last.risk_class] || 0;
    const rankDelta = lastRank - firstRank;
    const bmiDelta = (first.bmi != null && last.bmi != null) ? (last.bmi - first.bmi) : 0;

    let trendText;
    let alertClass;
    if (rankDelta <= -1) {
      trendText = "Your risk has trended down from " + (RISK_LABEL[first.risk_class] || first.risk_class) +
        " to " + (RISK_LABEL[last.risk_class] || last.risk_class) +
        " over the last " + items.length + " tests.";
      alertClass = "alert-success";
    } else if (rankDelta >= 1) {
      trendText = "Your risk has trended up from " + (RISK_LABEL[first.risk_class] || first.risk_class) +
        " to " + (RISK_LABEL[last.risk_class] || last.risk_class) +
        " over the last " + items.length + " tests.";
      alertClass = "alert-warning";
    } else if (Math.abs(bmiDelta) < 1.5) {
      trendText = "Your profile has been stable across the last " + items.length + " tests.";
      alertClass = "alert-light border";
    } else {
      trendText = "Your risk class hasn't changed across the last " + items.length + " tests.";
      alertClass = "alert-light border";
    }

    const notes = [];
    if (first.bmi != null && last.bmi != null && Math.abs(bmiDelta) >= 1.5) {
      const dir = bmiDelta < 0 ? "drop" : "rise";
      notes.push("This coincides with a BMI " + dir + " from " + first.bmi.toFixed(1) +
        " to " + last.bmi.toFixed(1) + ".");
    }
    const lifestyle = [];
    if (first.smoking !== last.smoking && last.smoking === "N") lifestyle.push("quitting smoking");
    if (first.activity !== last.activity && last.activity === "High") lifestyle.push("switching to high activity");
    if (lifestyle.length) {
      notes.push("You also reported " + lifestyle.join(" and ") + ".");
    }

    target.innerHTML = '<div class="alert ' + alertClass + ' small mb-3">' +
      escapeHtml(trendText) + (notes.length ? " " + escapeHtml(notes.join(" ")) : "") + "</div>";
  }

  function renderHistoryPage() {
    const root = document.getElementById("history-root");
    if (!root) return;
    const emptyEl = document.getElementById("history-empty");
    const tableWrap = document.getElementById("history-table");
    const chartWrap = document.getElementById("history-chart-wrap");
    const trendEl = document.getElementById("history-trend");
    const clearBtn = document.getElementById("history-clear");
    const unavailableEl = document.getElementById("history-unavailable");

    if (!storageAvailable()) {
      if (unavailableEl) unavailableEl.classList.remove("d-none");
      if (emptyEl) emptyEl.classList.add("d-none");
      if (tableWrap) tableWrap.classList.add("d-none");
      if (chartWrap) chartWrap.classList.add("d-none");
      if (trendEl) trendEl.innerHTML = "";
      if (clearBtn) clearBtn.disabled = true;
      return;
    }

    const items = loadHistory();
    if (!items.length) {
      if (emptyEl) emptyEl.classList.remove("d-none");
      if (tableWrap) tableWrap.classList.add("d-none");
      if (chartWrap) chartWrap.classList.add("d-none");
      if (trendEl) trendEl.innerHTML = "";
      if (clearBtn) clearBtn.disabled = true;
      return;
    }

    if (emptyEl) emptyEl.classList.add("d-none");
    if (chartWrap) chartWrap.classList.remove("d-none");
    if (tableWrap) {
      tableWrap.classList.remove("d-none");
      tableWrap.innerHTML = renderTable(items);
    }
    if (clearBtn) clearBtn.disabled = false;
    renderTrend(items);
    renderChart(items);
  }

  function bindHistoryPage() {
    const root = document.getElementById("history-root");
    if (!root) return;

    const clearBtn = document.getElementById("history-clear");
    if (clearBtn) {
      clearBtn.addEventListener("click", function () {
        if (window.confirm("Clear all history? This cannot be undone.")) {
          clearHistory();
          renderHistoryPage();
        }
      });
    }

    root.addEventListener("click", function (e) {
      const t = e.target.closest("[data-remove-id]");
      if (!t) return;
      const id = t.getAttribute("data-remove-id");
      if (window.confirm("Remove this entry?")) {
        removeEntry(id);
        renderHistoryPage();
      }
    });
  }

  function initWhatIf() {
    const card = document.getElementById("whatif-card");
    const source = document.getElementById("history-source");
    if (!card || !source) return;

    const apiUrl = source.dataset.apiUrl || "/api/predict";
    const original = {
      age: Number(source.dataset.age),
      height: Number(source.dataset.height),
      weight: Number(source.dataset.weight),
      activity: source.dataset.activity || "Moderate",
      smoking: source.dataset.smoking || "N",
      family: source.dataset.family || "N",
      risk_class: (source.dataset.riskClass || "").toUpperCase(),
      confidence: source.dataset.confidence !== "" && source.dataset.confidence != null
        ? Number(source.dataset.confidence) : null,
    };

    if (!isFinite(original.weight) || !isFinite(original.height)) return;

    const weightSlider = document.getElementById("whatif-weight");
    const weightDisp = document.getElementById("whatif-weight-display");
    const bmiDisp = document.getElementById("whatif-bmi-display");
    const resetBtn = document.getElementById("whatif-reset");
    const resultEl = document.getElementById("whatif-result");
    const errorEl = document.getElementById("whatif-error");

    const activityRadios = document.querySelectorAll('input[name="whatif-activity-radio"]');
    const smokingRadios = document.querySelectorAll('input[name="whatif-smoking-radio"]');

    const weightMin = Math.max(40, Math.floor(original.weight - 20));
    const weightMax = Math.min(200, Math.ceil(original.weight + 20));
    weightSlider.min = String(weightMin);
    weightSlider.max = String(weightMax);
    weightSlider.step = "0.5";
    weightSlider.value = String(original.weight);

    function setRadio(name, value) {
      const el = document.querySelector('input[name="' + name + '"][value="' + value + '"]');
      if (el) el.checked = true;
    }
    setRadio("whatif-activity-radio", original.activity);
    setRadio("whatif-smoking-radio", original.smoking);

    function computeBmi(weight) {
      const hM = original.height / 100;
      return hM > 0 ? weight / (hM * hM) : null;
    }

    function getInputs() {
      const checkedAct = document.querySelector('input[name="whatif-activity-radio"]:checked');
      const checkedSmk = document.querySelector('input[name="whatif-smoking-radio"]:checked');
      return {
        weight: Number(weightSlider.value),
        activity: checkedAct ? checkedAct.value : original.activity,
        smoking: checkedSmk ? checkedSmk.value : original.smoking,
      };
    }

    function isChanged(inputs) {
      return (
        Math.abs(inputs.weight - original.weight) > 1e-9 ||
        inputs.activity !== original.activity ||
        inputs.smoking !== original.smoking
      );
    }

    function classBadge(rc) {
      const labels = { LOW: "Low", INTERMEDIARY: "Medium", HIGH: "High" };
      const cls = { LOW: "bg-success", INTERMEDIARY: "bg-warning text-dark", HIGH: "bg-danger" };
      const key = (rc || "").toUpperCase();
      return '<span class="badge ' + (cls[key] || "bg-secondary") + '">' + (labels[key] || rc || "—") + "</span>";
    }

    function probBars(proba) {
      if (!Array.isArray(proba)) return "";
      const cls = { LOW: "bg-success", INTERMEDIARY: "bg-warning", HIGH: "bg-danger" };
      const labels = { LOW: "Low", INTERMEDIARY: "Medium", HIGH: "High" };
      return proba.map(function (item) {
        const key = (item.class || "").toUpperCase();
        const label = labels[key] || item.class;
        const pct = (item.p * 100).toFixed(1);
        return (
          '<div class="mb-1">' +
            '<div class="d-flex justify-content-between small"><span>' + label + '</span>' +
            '<span class="text-muted">' + pct + '%</span></div>' +
            '<div class="progress" style="height: 6px;">' +
              '<div class="progress-bar ' + (cls[key] || "bg-secondary") + '" style="width: ' + pct + '%"></div>' +
            "</div>" +
          "</div>"
        );
      }).join("");
    }

    function renderResult(data) {
      const newClass = (data.pred_class_name || "").toUpperCase();

      let deltaHtml = "";
      if (Array.isArray(data.proba) && original.confidence != null && original.risk_class) {
        const matched = data.proba.find(function (p) {
          return (p.class || "").toUpperCase() === original.risk_class;
        });
        if (matched) {
          const deltaPp = (matched.p - original.confidence) * 100;
          const labels = { LOW: "Low", INTERMEDIARY: "Medium", HIGH: "High" };
          const lbl = labels[original.risk_class] || original.risk_class;
          if (Math.abs(deltaPp) < 0.05) {
            deltaHtml = '<span class="text-muted">no change</span> for ' + lbl + " probability";
          } else {
            const down = deltaPp < 0;
            const arrow = down ? "&#9660;" : "&#9650;";
            const color = down ? "text-success" : "text-danger";
            deltaHtml = '<span class="' + color + '">' + arrow + " " + Math.abs(deltaPp).toFixed(1) +
              "pp</span> for " + lbl + " probability";
          }
        }
      }

      resultEl.classList.remove("text-muted");
      resultEl.innerHTML =
        '<div class="d-flex align-items-center gap-3 flex-wrap mb-2">' +
          '<div><div class="text-muted small">Current</div>' + classBadge(original.risk_class) + "</div>" +
          '<div class="text-muted">&rarr;</div>' +
          '<div><div class="text-muted small">If changed</div>' + classBadge(newClass) + "</div>" +
          (deltaHtml ? '<div class="ms-auto small">' + deltaHtml + "</div>" : "") +
        "</div>" +
        probBars(data.proba);
    }

    function renderIdle() {
      resultEl.classList.add("text-muted");
      resultEl.innerHTML = "Adjust controls to see how the estimate would change.";
    }

    function renderLoading() {
      resultEl.classList.add("text-muted");
      resultEl.innerHTML = '<span class="spinner-border spinner-border-sm me-2" role="status"></span>Computing...';
    }

    let debounceTimer = null;
    let currentController = null;

    async function runRequest(inputs) {
      if (currentController) currentController.abort();
      currentController = new AbortController();
      errorEl.classList.add("d-none");

      const payload = {
        "Age": original.age,
        "Height (cm)": original.height,
        "Weight (kg)": inputs.weight,
        "Physical Activity Level": inputs.activity,
        "Smoking Status": inputs.smoking,
        "Family History of CVD": original.family,
      };

      try {
        const resp = await fetch(apiUrl, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
          signal: currentController.signal,
        });
        if (!resp.ok) throw new Error("HTTP " + resp.status);
        const data = await resp.json();
        renderResult(data);
      } catch (e) {
        if (e && e.name === "AbortError") return;
        errorEl.classList.remove("d-none");
        renderIdle();
      }
    }

    function scheduleUpdate() {
      const inputs = getInputs();
      weightDisp.textContent = inputs.weight.toFixed(1) + " kg";
      const bmi = computeBmi(inputs.weight);
      bmiDisp.textContent = bmi != null ? bmi.toFixed(1) : "—";

      if (!isChanged(inputs)) {
        if (debounceTimer) clearTimeout(debounceTimer);
        if (currentController) currentController.abort();
        renderIdle();
        return;
      }

      renderLoading();
      if (debounceTimer) clearTimeout(debounceTimer);
      debounceTimer = setTimeout(function () { runRequest(inputs); }, 200);
    }

    weightSlider.addEventListener("input", scheduleUpdate);
    activityRadios.forEach(function (r) { r.addEventListener("change", scheduleUpdate); });
    smokingRadios.forEach(function (r) { r.addEventListener("change", scheduleUpdate); });

    if (resetBtn) {
      resetBtn.addEventListener("click", function () {
        weightSlider.value = String(original.weight);
        setRadio("whatif-activity-radio", original.activity);
        setRadio("whatif-smoking-radio", original.smoking);
        scheduleUpdate();
      });
    }

    // Initial display (no fetch since nothing has changed yet).
    scheduleUpdate();
  }

  document.addEventListener("DOMContentLoaded", function () {
    readFromResultPage();
    bindHistoryPage();
    renderHistoryPage();
    initWhatIf();
  });
})();
