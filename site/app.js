/* Legacy to Lakehouse: cutover readiness board. Reads data/run.json written by `python -m lakehouse`. */
(function () {
  "use strict";
  var app = document.getElementById("app");
  var VIEWS = [["cutover", "Cutover readiness"], ["loads", "Nightly loads"], ["recalls", "Recall completion"], ["pipeline", "Pipeline"]];
  var state = { run: null, view: viewFromHash(), open: {}, recallsTab: "campaigns", pipelineTab: "layers", flash: null };
  var REPO = document.body.getAttribute("data-repo");

  function el(tag, attrs, children) {
    var n = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      var v = attrs[k];
      if (v === null || v === undefined || v === false) return;
      if (k === "text") n.textContent = v;
      else if (k === "class") n.className = v;
      else if (k.indexOf("on") === 0) n.addEventListener(k.slice(2), v);
      else n.setAttribute(k, v === true ? "" : v);
    });
    (children || []).forEach(function (c) {
      if (c === null || c === undefined || c === false) return;
      n.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
    });
    return n;
  }
  function fmt(n) { return n === null || n === undefined ? "-" : Number(n).toLocaleString("en-US"); }
  function pct(x) { return (Math.round(x * 1000) / 10).toFixed(1) + "%"; }
  function bar(fraction, light) {
    return el("div", { class: "bar" + (light ? " light" : ""), role: "img", "aria-label": pct(fraction) },
      [el("span", { style: "width:" + Math.max(0, Math.min(100, fraction * 100)).toFixed(1) + "%" })]);
  }
  function numCell(n) { return el("td", { class: "num" + (n === 0 ? " zero" : ""), text: fmt(n) }); }
  function table(head, rows, numericCols) {
    numericCols = numericCols || [];
    return el("div", { class: "grid-wrap" }, [el("table", { class: "grid" }, [
      el("thead", {}, [el("tr", {}, head.map(function (h, i) {
        return el("th", { class: numericCols.indexOf(i) >= 0 ? "num" : null, text: h, scope: "col" });
      }))]),
      el("tbody", {}, rows)])]);
  }
  function insetTabs(key, options) {
    return el("div", { class: "inset", role: "tablist" }, options.map(function (o) {
      return el("button", { type: "button", role: "tab", "aria-selected": state[key] === o[0] ? "true" : "false",
        onclick: function () { state[key] = o[0]; render(); }, text: o[1] });
    }));
  }
  function blockedTables() { return state.run.reconciliation.filter(function (r) { return r.status !== "ready"; }); }

  /* Routing: side nav + breadcrumb, driven by the URL hash */
  function viewFromHash() {
    var h = (location.hash || "").replace("#", "");
    return VIEWS.some(function (v) { return v[0] === h; }) ? h : "cutover";
  }
  function go(view, openKey) {
    if (openKey) { state.open[openKey] = true; state.flash = openKey; }
    if (location.hash.replace("#", "") !== view) { state.view = view; history.pushState(null, "", "#" + view); }
    else state.view = view;
    render(true);
    var n = openKey && document.getElementById("row-" + openKey);
    if (n) n.scrollIntoView({ behavior: "smooth", block: "center" });
    else window.scrollTo({ top: 0 });
  }
  window.addEventListener("popstate", function () { state.view = viewFromHash(); render(true); });

  function renderNav() {
    var nav = document.getElementById("nav");
    nav.innerHTML = "";
    var anyBlocked = state.run && blockedTables().length > 0;
    VIEWS.forEach(function (v) {
      nav.appendChild(el("a", { href: "#" + v[0], "aria-current": state.view === v[0] ? "page" : null,
        onclick: function (e) { e.preventDefault(); go(v[0]); } },
        [v[1], v[0] === "cutover" && anyBlocked ? el("span", { class: "flag", "aria-label": "has blocked tables" }) : null]));
    });
    var crumbs = document.getElementById("crumbs");
    crumbs.innerHTML = "";
    crumbs.appendChild(el("li", { text: "Recall operations DB → Databricks lakehouse" }));
    crumbs.appendChild(el("li", { "aria-current": "page", text: VIEWS.filter(function (v) { return v[0] === state.view; })[0][1] }));
  }

  /* Overflow menu: every secondary action lives here */
  function renderMenu() {
    var wrap = document.getElementById("more");
    wrap.innerHTML = "";
    if (!state.run) return;
    var menu, btn;
    function close(focusBtn) { if (menu) { menu.remove(); menu = null; btn.setAttribute("aria-expanded", "false"); if (focusBtn) btn.focus(); } }
    function item(label, fn) {
      return el("button", { type: "button", role: "menuitem", tabindex: "-1", text: label,
        onclick: function () { close(false); fn(); } });
    }
    function open() {
      var b = blockedTables()[0];
      var items = [el("div", { class: "group", text: "Guided tour" })];
      if (b) items.push(item("Why " + b.table + " is blocked", function () { go("cutover", b.table); }));
      items.push(item("Nightly load vs. full reload", function () { go("loads"); }));
      items.push(item("Recalls with the fewest repairs done", function () { state.recallsTab = "campaigns"; go("recalls"); }));
      items.push(item("Dealer history kept as SCD Type 2", function () { state.pipelineTab = "history"; go("pipeline"); }));
      items.push(el("div", { class: "sep" }));
      items.push(item("About this data", about));
      items.push(item("Reload latest run", load));
      items.push(el("a", { role: "menuitem", tabindex: "-1", href: REPO, target: "_blank", rel: "noopener", text: "Source code on GitHub ↗" }));
      menu = el("div", { class: "menu", role: "menu", "aria-label": "More actions",
        onkeydown: function (e) {
          var list = Array.prototype.slice.call(menu.querySelectorAll('[role="menuitem"]'));
          var i = list.indexOf(document.activeElement);
          if (e.key === "ArrowDown") { e.preventDefault(); list[(i + 1) % list.length].focus(); }
          else if (e.key === "ArrowUp") { e.preventDefault(); list[(i - 1 + list.length) % list.length].focus(); }
          else if (e.key === "Escape") { e.preventDefault(); close(true); }
          else if (e.key === "Tab") close(false);
        } }, items);
      wrap.appendChild(menu);
      btn.setAttribute("aria-expanded", "true");
      menu.querySelector('[role="menuitem"]').focus();
    }
    btn = el("button", { type: "button", class: "dots", "aria-label": "More actions", "aria-haspopup": "menu", "aria-expanded": "false",
      text: "···", onclick: function () { menu ? close(false) : open(); } });
    wrap.appendChild(btn);
    closeMenu = function (e) { if (menu && !wrap.contains(e.target)) close(false); };
  }
  var closeMenu = null;
  document.addEventListener("mousedown", function (e) { if (closeMenu) closeMenu(e); });

  function about() {
    var d = document.getElementById("about");
    var s = state.run.summary;
    d.innerHTML = "";
    d.appendChild(el("button", { type: "button", class: "dots close", "aria-label": "Close", text: "✕", onclick: function () { d.close(); } }));
    d.appendChild(el("h2", { id: "aboutTitle", text: "About this data" }));
    [
      "Recalls and complaints are real NHTSA data for GM vehicles, model years 2021 to 2025. Dealers, owners and repair orders are synthetic and every person is fictional.",
      s.nights + " nightly loads were simulated after the initial full load. 8 bad repair orders were planted in the legacy data on purpose.",
      "Legacy SQLite database → nightly watermark extract to the landing zone → PySpark bronze, silver and gold → reconciliation against a key-and-hash snapshot of the legacy system. Spark " + state.run.spark_version + ".",
      "Bronze holds raw text exactly as landed, with batch id, file and load time, and is access-restricted because it holds raw PII. Silver is typed, validated, deduplicated and merged, with PII hashed, bad rows quarantined and dealer history kept as SCD Type 2. Gold holds the business tables for recall operations and product safety.",
      "Each night only rows whose updated_at changed are extracted and merged. Rows processed is what drives cloud compute cost at scale; at this demo's size, Spark's fixed start-up work keeps the time difference small.",
      "Recall completion covers every registered vehicle under a recall and whether the repair is done. Campaign rankings include recalls with 20 or more vehicles."
    ].forEach(function (t) { d.appendChild(el("p", { text: t })); });
    d.showModal();
  }

  function kpis() {
    var s = state.run.summary;
    var blocked = s.tables - s.tables_ready;
    function kpi(label, value, of) {
      return el("div", { class: "kpi" }, [el("div", { class: "label", text: label }), value, of ? el("div", { class: "of", text: of }) : null]);
    }
    return el("section", { class: "kpis", "aria-label": "Migration status" }, [
      kpi("Tables ready for cutover", el("div", { class: "value" + (blocked ? " alert" : "") }, [String(s.tables_ready), el("small", { text: " / " + s.tables })]), null),
      kpi("Legacy rows matched", el("div", { class: "value", text: (Math.floor(s.rows_matched / s.rows_legacy * 10000) / 100).toFixed(2) + "%" }),
          fmt(s.rows_matched) + " of " + fmt(s.rows_legacy)),
      kpi("Rows per nightly load", el("div", { class: "value", text: fmt(s.nightly_rows_avg) }),
          s.rows_saved_pct + "% fewer than a full reload"),
      kpi("PII columns hashed", el("div", { class: "value", text: String(s.pii_columns_hashed) }), "before silver")
    ]);
  }

  function cutover() {
    var rec = state.run.reconciliation;
    var contracts = state.run.contracts;
    var rows = [];
    rec.forEach(function (r) {
      var open = !!state.open[r.table];
      var toggle = function () { state.open[r.table] = !open; render(); };
      var blocked = r.status !== "ready";
      rows.push(el("tr", { id: "row-" + r.table, class: "row click" + (state.flash === r.table ? " flash" : ""), onclick: toggle }, [
        el("td", { class: "key" }, [r.table, el("div", { class: "sub", text: contracts[r.table].source })]),
        numCell(r.legacy_rows), numCell(r.lakehouse_rows), numCell(r.missing), numCell(r.extra), numCell(r.changed),
        el("td", {}, [el("span", { class: "status" + (blocked ? " blocked" : ""), text: blocked ? "Blocked" : "Ready" })]),
        el("td", { style: "text-align:right;width:32px" }, [el("button", { type: "button", class: "chev", "aria-expanded": open ? "true" : "false",
          "aria-label": (open ? "Hide details for " : "Show details for ") + r.table, text: "▸",
          onclick: function (e) { e.stopPropagation(); toggle(); } })])
      ]));
      if (open) rows.push(el("tr", { class: "detail" }, [el("td", { colspan: "8" }, [detail(r, contracts[r.table])])]));
    });
    state.flash = null;
    return el("section", { "aria-label": "Cutover readiness" }, [
      table(["Table", "Legacy rows", "Lakehouse rows", "Missing", "Extra", "Changed", "Status", ""], rows, [1, 2, 3, 4, 5])
    ]);
  }

  function detail(r, c) {
    var left = [];
    if (r.status !== "ready") {
      var reasons = [];
      if (r.missing) reasons.push(fmt(r.missing) + " legacy rows are not in the lakehouse" +
        (r.quarantine_reasons.length ? ". They were quarantined for breaking: " + r.quarantine_reasons.map(function (q) { return q.rule + " (" + q.rows + ")"; }).join(", ") + "." : "."));
      if (r.extra) reasons.push(fmt(r.extra) + " lakehouse rows no longer exist in the legacy system.");
      if (r.changed) reasons.push(fmt(r.changed) + " rows have different values in the two systems.");
      var sql = "SELECT * FROM workspace.l2l_silver.quarantine WHERE table_name = '" + r.table + "'";
      var facts = [el("dt", { text: "Blocked by" }), el("dd", {}, reasons.map(function (t) { return el("div", { text: t }); }))];
      Object.keys(r.samples).forEach(function (k) {
        facts.push(el("dt", { text: "Example " + k }), el("dd", {}, [el("code", { text: r.samples[k].join(", ") })]));
      });
      facts.push(el("dt", { text: "Next step" }), el("dd", { text: "Fix these rows in the legacy system, or agree a rule change with the data owner. The next nightly load picks them up." }));
      var copyBtn = el("button", { type: "button", class: "copy", text: "Copy", onclick: function (e) {
        e.stopPropagation();
        var done = function () { copyBtn.textContent = "Copied"; setTimeout(function () { copyBtn.textContent = "Copy"; }, 1400); };
        if (navigator.clipboard) navigator.clipboard.writeText(sql).then(done, function () {}); } });
      facts.push(el("dt", { text: "Inspect" }), el("dd", {}, [el("div", { class: "query" }, [el("pre", { text: sql }), copyBtn])]));
      left.push(el("dl", { class: "facts" }, facts));
    } else {
      left.push(el("dl", { class: "facts" }, [el("dt", { text: "Reconciled" }),
        el("dd", { text: "Every legacy key is in the lakehouse with the same row hash." })]));
    }
    var contract = el("dl", { class: "facts" }, [
      el("dt", { text: "Primary key" }), el("dd", {}, [el("code", { text: c.primary_key.join(", ") })]),
      el("dt", { text: "Incremental by" }), el("dd", {}, [el("code", { text: c.watermark }), el("div", { class: "sub", text: "Last value " + (r.watermark || "-") })]),
      el("dt", { text: "PII hashed" }), el("dd", { text: c.pii.length ? c.pii.join(", ") + " (SHA-256)" : "None" }),
      c.scd2.length ? el("dt", { text: "SCD Type 2" }) : null, c.scd2.length ? el("dd", { text: c.scd2.join(", ") }) : null,
      el("dt", { text: "Quality rules" }), el("dd", { text: c.expectations.length ? c.expectations.join(", ") : "None" })
    ]);
    return el("div", { class: "detail-grid", onclick: function (e) { e.stopPropagation(); } }, [el("div", {}, left), contract]);
  }

  function loads() {
    var s = state.run.summary;
    var maxRows = Math.max(s.full_reload_rows, s.nightly_rows_avg);
    var maxSec = Math.max(s.full_reload_seconds, s.nightly_load_seconds_avg);
    var compare = el("div", { class: "compare", role: "group", "aria-label": "Nightly load compared with a full reload" }, [
      el("div", { class: "grp", text: "Rows processed" }),
      el("span", { text: "Nightly incremental" }), bar(s.nightly_rows_avg / maxRows), el("span", { class: "num", text: fmt(s.nightly_rows_avg) }),
      el("span", { text: "Full reload" }), bar(s.full_reload_rows / maxRows, true), el("span", { class: "num", text: fmt(s.full_reload_rows) }),
      el("div", { class: "grp", text: "Load time, seconds" }),
      el("span", { text: "Nightly incremental" }), bar(s.nightly_load_seconds_avg / maxSec), el("span", { class: "num", text: s.nightly_load_seconds_avg.toFixed(1) }),
      el("span", { text: "Full reload" }), bar(s.full_reload_seconds / maxSec, true), el("span", { class: "num", text: s.full_reload_seconds.toFixed(1) })
    ]);
    var rows = state.run.batches.map(function (b) {
      var sum = function (k) { return b.tables.reduce(function (a, t) { return a + (t[k] || 0); }, 0); };
      return el("tr", { class: "row" }, [
        el("td", { class: "key", text: b.batch_id === 0 ? "Initial" : "Night " + b.batch_id }),
        el("td", { class: "sub", text: b.mode }),
        numCell(b.rows_processed), numCell(sum("inserted")), numCell(sum("updated")), numCell(sum("deleted")), numCell(sum("quarantined")),
        el("td", { class: "num", text: b.load_seconds.toFixed(1) }),
        el("td", { class: "num", text: b.reconcile_seconds.toFixed(1) })
      ]);
    });
    return el("section", { "aria-label": "Nightly loads" }, [
      compare,
      table(["Load", "Type", "Rows landed", "Inserted", "Updated", "Deleted", "Quarantined", "Load s", "Reconcile s"], rows, [2, 3, 4, 5, 6, 7, 8])
    ]);
  }

  function recalls() {
    var g = state.run.gold;
    var s = state.run.summary;
    var body;
    if (state.recallsTab === "campaigns") {
      var rows = g.lowest_completion_campaigns.map(function (c) {
        return el("tr", { class: "row" }, [
          el("td", { class: "key" }, [c.campaign_number, el("div", { class: "sub", text: "Reported " + c.reported })]),
          el("td", {}, [c.component_group, c.park_it ? el("div", { class: "status blocked", style: "margin-top:4px;font-size:12px", text: "Park it" }) : null]),
          el("td", { style: "max-width:400px" }, [el("span", { class: "sub", text: c.summary + (c.summary.length >= 240 ? "…" : "") })]),
          numCell(c.vehicles_affected), numCell(c.vehicles_repaired),
          el("td", { style: "min-width:120px" }, [bar(c.completion_rate), el("div", { class: "pct", text: pct(c.completion_rate) })])
        ]);
      });
      body = rows.length ? table(["Campaign", "Component", "Defect", "Vehicles", "Repaired", "Completion"], rows, [3, 4]) : el("p", { class: "empty", text: "No recall campaigns in this run." });
    } else {
      var drows = g.lowest_completion_dealers.map(function (d) {
        return el("tr", { class: "row" }, [
          el("td", { class: "key", text: d.dealer_code }),
          el("td", {}, [d.dealer_name || "", el("div", { class: "sub", text: ((d.city || "") + " " + (d.state || "")).trim() })]),
          el("td", { text: d.region || "" }),
          el("td", { class: d.status === "active" ? "sub" : "", text: d.status }),
          numCell(d.open_recall_repairs_needed),
          el("td", { style: "min-width:120px" }, [bar(d.completion_rate), el("div", { class: "pct", text: pct(d.completion_rate) })])
        ]);
      });
      body = drows.length ? table(["Dealer", "Name and location", "Region", "Status", "Recall repairs", "Completion"], drows, [4]) : el("p", { class: "empty", text: "No dealers in this run." });
    }
    return el("section", { "aria-label": "Recall completion" }, [
      el("div", { class: "view-head" }, [insetTabs("recallsTab", [["campaigns", "Campaigns"], ["dealers", "Dealers"]]),
        el("span", { class: "aside", text: fmt(s.recall_repairs_done) + " of " + fmt(s.recall_vehicles) + " repairs done" })]),
      body
    ]);
  }

  function pipeline() {
    var L = state.run.layers;
    var body;
    if (state.pipelineTab === "layers") {
      var names = ["bronze", "silver", "gold"];
      body = el("div", { class: "flow" }, names.map(function (layer, i) {
        return el("div", { class: "layer" }, [
          el("h2", {}, [layer, i < names.length - 1 ? el("span", { class: "to", "aria-hidden": "true", text: "→" }) : null]),
          el("table", {}, [el("tbody", {}, Object.keys(L[layer]).map(function (t) {
            return el("tr", {}, [el("td", { text: t }), el("td", { class: "num", text: fmt(L[layer][t]) })]);
          }))])]);
      }));
    } else {
      var hist = state.run.dealer_history.map(function (h) {
        return el("tr", { class: "row" }, [el("td", { class: "key", text: h.dealer_code }), el("td", { text: h.region }), el("td", { text: h.status }),
          el("td", { class: "mono", style: "font-size:12px", text: String(h.valid_from).slice(0, 16) }),
          el("td", { class: "mono", style: "font-size:12px", text: h.valid_to ? String(h.valid_to).slice(0, 16) : "-" }),
          el("td", { class: h.is_current ? "" : "sub", text: h.is_current ? "Current" : "History" })]);
      });
      body = hist.length ? table(["Dealer", "Region", "Status", "Valid from", "Valid to", "Version"], hist) : el("p", { class: "empty", text: "No dealer changes yet." });
    }
    return el("section", { "aria-label": "Pipeline" }, [insetTabs("pipelineTab", [["layers", "Layers"], ["history", "Dealer history"]]), body]);
  }

  function render() {
    renderNav();
    if (!state.run) return;
    var y = window.scrollY;
    app.innerHTML = "";
    var blocked = blockedTables()[0];
    app.appendChild(el("h1", { class: "lead", text: "Check that every legacy table matches its lakehouse copy before you switch the legacy system off." }));
    app.appendChild(el("div", { class: "primary-row" }, [blocked
      ? el("button", { type: "button", class: "btn", text: "See why " + blocked.table + " is blocked", onclick: function () { go("cutover", blocked.table); } })
      : el("span", { class: "ok-line", text: "Every table matches. Ready for cutover." })]));
    app.appendChild(kpis());
    app.appendChild({ cutover: cutover, loads: loads, recalls: recalls, pipeline: pipeline }[state.view]());
    app.appendChild(el("p", { class: "foot", text: "Recalls are real NHTSA data. Dealers, owners and repairs are synthetic." }));
    window.scrollTo(0, y);
  }

  function load() {
    app.innerHTML = "";
    app.appendChild(el("p", { class: "state loading", text: "Loading the latest pipeline run…" }));
    fetch("data/run.json", { cache: "no-store" })
      .then(function (r) { if (!r.ok) throw new Error("The server answered " + r.status + " for data/run.json."); return r.json(); })
      .then(function (run) {
        if (!run || !run.reconciliation || !run.summary) throw new Error("run.json is not a Legacy to Lakehouse pipeline run.");
        state.run = run;
        document.getElementById("scannedLabel").textContent = "Last run " + new Date(run.generated_at).toLocaleString("en-US",
          { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
        renderMenu();
        render();
      })
      .catch(function (e) {
        renderNav();
        app.innerHTML = "";
        app.appendChild(el("section", { class: "state error", role: "alert" }, [
          el("h1", { text: "The pipeline run could not be loaded." }),
          el("p", { text: navigator.onLine === false ? "You are offline. Reconnect and try again." :
            e.message + " If you opened index.html from disk, run: python -m http.server -d site 8000" }),
          el("button", { type: "button", class: "btn", onclick: load, text: "Try again" })]));
      });
  }
  function online() { document.getElementById("offline").hidden = navigator.onLine !== false; }
  window.addEventListener("online", online);
  window.addEventListener("offline", online);
  online();
  renderNav();
  load();
})();
