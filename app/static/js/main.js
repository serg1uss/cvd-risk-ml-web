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

  function renderHistoryPage() {
    const root = document.getElementById("history-root");
    if (!root) return;
    const emptyEl = document.getElementById("history-empty");
    const tableWrap = document.getElementById("history-table");
    const chartWrap = document.getElementById("history-chart-wrap");
    const clearBtn = document.getElementById("history-clear");
    const unavailableEl = document.getElementById("history-unavailable");

    if (!storageAvailable()) {
      if (unavailableEl) unavailableEl.classList.remove("d-none");
      if (emptyEl) emptyEl.classList.add("d-none");
      if (tableWrap) tableWrap.classList.add("d-none");
      if (chartWrap) chartWrap.classList.add("d-none");
      if (clearBtn) clearBtn.disabled = true;
      return;
    }

    const items = loadHistory();
    if (!items.length) {
      if (emptyEl) emptyEl.classList.remove("d-none");
      if (tableWrap) tableWrap.classList.add("d-none");
      if (chartWrap) chartWrap.classList.add("d-none");
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

  document.addEventListener("DOMContentLoaded", function () {
    readFromResultPage();
    bindHistoryPage();
    renderHistoryPage();
  });
})();
