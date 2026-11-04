/* Legacy to Lakehouse: cutover readiness board. Reads data/run.json written by `python -m lakehouse`. */
(function () {
  "use strict";
  var app = document.getElementById("app");
  var state = { run: null, tab: "cutover", open: {} };
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
  function bar(fraction, muted) {
    return el("div", { class: "bar" + (muted ? " muted" : ""), role: "img", "aria-label": pct(fraction) },
      [el("span", { style: "width:" + Math.max(0, Math.min(100, fraction * 100)).toFixed(1) + "%" })]);
  }
  function tag(kind, text) { return el("span", { class: "tag " + kind, text: text }); }
  function table(head, rows) {
    return el("div", { class: "grid-wrap" }, [el("table", { class: "grid" }, [
      el("thead", {}, [el("tr", {}, head.map(function (h) { return el("th", { text: h }); }))]),
      el("tbody", {}, rows)])]);
  }
  function jump(tab, openKey) {
    state.tab = tab;
    if (openKey) state.open[openKey] = true;
    render();
    var n = openKey && document.getElementById("row-" + openKey);
    if (n) { n.scrollIntoView({ behavior: "smooth", block: "center" }); }
  }

  function kpis() {
    var s = state.run.summary;
    function kpi(label, value, note) {
      return el("div", { class: "kpi" }, [el("div", { class: "label", text: label }), value, el("div", { class: "note", text: note })]);
    }
    return el("section", { class: "kpis", "aria-label": "Migration status" }, [
      kpi("Tables ready for cutover", el("div", { class: "value" }, [String(s.tables_ready), el("small", { text: " of " + s.tables })]),
          "Lakehouse copy matches the legacy system"),
      kpi("Rows matched", el("div", { class: "value", text: (Math.floor(s.rows_matched / s.rows_legacy * 10000) / 100).toFixed(2) + "%" }),
          fmt(s.rows_matched) + " of " + fmt(s.rows_legacy) + " legacy rows"),
      kpi("Rows per nightly load", el("div", { class: "value", text: fmt(s.nightly_rows_avg) }),
          s.rows_saved_pct + "% fewer than a full reload (" + fmt(s.full_reload_rows) + ")"),
      kpi("PII columns hashed", el("div", { class: "value", text: String(s.pii_columns_hashed) }),
          "Raw values never leave the bronze layer")
    ]);
  }

  function tabs() {
    var t = [["cutover", "Cutover readiness"], ["loads", "Nightly loads"], ["recalls", "Recall completion"], ["pipeline", "Pipeline"]];
    return el("div", { class: "tabs", role: "tablist" }, t.map(function (x) {
      return el("button", { class: "tab", role: "tab", type: "button", id: "tab-" + x[0], "aria-selected": state.tab === x[0] ? "true" : "false",
        onclick: function () { state.tab = x[0]; render(); }, text: x[1] });
    }));
  }

  function cutover() {
    var rec = state.run.reconciliation;
    var contracts = state.run.contracts;
    var rows = [];
    rec.forEach(function (r) {
      var open = !!state.open[r.table];
      var issues = r.missing + r.extra + r.changed;
      rows.push(el("tr", { id: "row-" + r.table }, [
        el("td", { class: "mono" }, [r.table, el("div", { class: "subtle", text: contracts[r.table].source })]),
        el("td", { class: "num", text: fmt(r.legacy_rows) }),
        el("td", { class: "num", text: fmt(r.lakehouse_rows) }),
        el("td", { class: "num", text: fmt(r.missing) }),
        el("td", { class: "num", text: fmt(r.extra) }),
        el("td", { class: "num", text: fmt(r.changed) }),
        el("td", {}, [r.status === "ready" ? tag("ok", "Ready") : tag("missing", "Blocked")]),
        el("td", {}, [el("button", { type: "button", class: "link", "aria-expanded": open ? "true" : "false",
          onclick: function () { state.open[r.table] = !open; render(); }, text: open ? "Hide" : (issues ? "Why blocked" : "Details") })])
      ]));
      if (open) rows.push(el("tr", { class: "why" }, [el("td", { colspan: "8" }, [detail(r, contracts[r.table])])]));
    });
    var blocked = rec.filter(function (r) { return r.status !== "ready"; });
    return el("section", { role: "tabpanel", "aria-labelledby": "tab-cutover" }, [
      el("p", { class: "section-note", text: blocked.length
        ? blocked.length + (blocked.length === 1 ? " table is" : " tables are") + " blocked. Every legacy row must be in the lakehouse with the same values before the legacy table can be switched off."
        : "Every table matches the legacy system. The migration is ready for cutover." }),
      table(["Table", "Legacy rows", "Lakehouse rows", "Missing", "Extra", "Changed", "Status", ""], rows)
    ]);
  }

  function detail(r, c) {
    var parts = [];
    if (r.status !== "ready") {
      parts.push(el("h3", { text: "Why it is blocked" }));
      var li = [];
      if (r.missing) li.push(el("li", {}, [fmt(r.missing) + " legacy rows are not in the lakehouse. ",
        r.quarantine_reasons.length ? "They were quarantined because they broke these rules: " + r.quarantine_reasons.map(function (q) { return q.rule + " (" + q.rows + ")"; }).join(", ") + "." : ""]));
      if (r.extra) li.push(el("li", { text: fmt(r.extra) + " lakehouse rows no longer exist in the legacy system." }));
      if (r.changed) li.push(el("li", { text: fmt(r.changed) + " rows have different values in the two systems." }));
      parts.push(el("ul", {}, li));
      Object.keys(r.samples).forEach(function (k) {
        parts.push(el("p", {}, ["Example " + k + " keys: ", el("code", { text: r.samples[k].join(", ") })]));
      });
      parts.push(el("p", {}, ["Next step: fix these rows in the legacy system (or agree a rule change with the data owner). The next nightly load picks them up. To see them: ",
        el("code", { text: "SELECT * FROM workspace.l2l_silver.quarantine WHERE table_name = '" + r.table + "'" })]));
    }
    parts.push(el("h3", { text: "Data contract" }));
    parts.push(el("ul", {}, [
      el("li", {}, ["Primary key: ", el("code", { text: c.primary_key.join(", ") })]),
      el("li", {}, ["Incremental by: ", el("code", { text: c.watermark }), ". Last value loaded: " + (r.watermark || "-")]),
      el("li", { text: c.pii.length ? "PII hashed with SHA-256: " + c.pii.join(", ") : "No PII columns" }),
      c.scd2.length ? el("li", { text: "History kept (SCD Type 2) for: " + c.scd2.join(", ") }) : null,
      el("li", { text: c.expectations.length ? "Quality rules: " + c.expectations.join(", ") : "No quality rules" })
    ]));
    return el("div", {}, parts);
  }

  function loads() {
    var s = state.run.summary;
    var maxRows = Math.max(s.full_reload_rows, s.nightly_rows_avg);
    var maxSec = Math.max(s.full_reload_seconds, s.nightly_load_seconds_avg);
    var compare = el("div", { class: "compare", "aria-label": "Nightly load compared with a full reload" }, [
      el("strong", { text: "Rows processed" }), el("span"), el("span"),
      el("span", { text: "Nightly incremental" }), bar(s.nightly_rows_avg / maxRows), el("span", { class: "num", text: fmt(s.nightly_rows_avg) }),
      el("span", { text: "Full reload" }), bar(s.full_reload_rows / maxRows, true), el("span", { class: "num", text: fmt(s.full_reload_rows) }),
      el("strong", { text: "Load time (seconds)" }), el("span"), el("span"),
      el("span", { text: "Nightly incremental" }), bar(s.nightly_load_seconds_avg / maxSec), el("span", { class: "num", text: s.nightly_load_seconds_avg.toFixed(1) }),
      el("span", { text: "Full reload" }), bar(s.full_reload_seconds / maxSec, true), el("span", { class: "num", text: s.full_reload_seconds.toFixed(1) })
    ]);
    var rows = [];
    state.run.batches.forEach(function (b) {
      var sum = function (k) { return b.tables.reduce(function (a, t) { return a + (t[k] || 0); }, 0); };
      rows.push(el("tr", {}, [
        el("td", { class: "mono", text: b.batch_id === 0 ? "Initial" : "Night " + b.batch_id }),
        el("td", { text: b.mode }),
        el("td", { class: "num", text: fmt(b.rows_processed) }),
        el("td", { class: "num", text: fmt(sum("inserted")) }),
        el("td", { class: "num", text: fmt(sum("updated")) }),
        el("td", { class: "num", text: fmt(sum("deleted")) }),
        el("td", { class: "num", text: fmt(sum("quarantined")) }),
        el("td", { class: "num", text: b.load_seconds.toFixed(1) }),
        el("td", { class: "num", text: b.reconcile_seconds.toFixed(1) })
      ]));
    });
    return el("section", { role: "tabpanel", "aria-labelledby": "tab-loads" }, [
      el("p", { class: "section-note", text: "Each night only rows whose updated_at changed are extracted and merged. Rows processed is what drives cloud compute cost at scale; at this demo's size, Spark's fixed start-up work keeps the time difference small." }),
      compare,
      table(["Load", "Type", "Rows landed", "Inserted", "Updated", "Deleted", "Quarantined", "Load s", "Reconcile s"], rows)
    ]);
  }

  function recalls() {
    var g = state.run.gold;
    var s = state.run.summary;
    var rows = g.lowest_completion_campaigns.map(function (c) {
      return el("tr", {}, [
        el("td", { class: "mono" }, [c.campaign_number, el("div", { class: "subtle", text: "reported " + c.reported })]),
        el("td", {}, [c.component_group, c.park_it ? el("div", {}, [tag("missing", "Park it")]) : null]),
        el("td", { style: "max-width:420px" }, [el("span", { class: "subtle", text: c.summary + (c.summary.length >= 240 ? "…" : "") })]),
        el("td", { class: "num", text: fmt(c.vehicles_affected) }),
        el("td", { class: "num", text: fmt(c.vehicles_repaired) }),
        el("td", {}, [bar(c.completion_rate), el("div", { class: "subtle", text: pct(c.completion_rate) })])
      ]);
    });
    var drows = g.lowest_completion_dealers.map(function (d) {
      return el("tr", {}, [
        el("td", { class: "mono", text: d.dealer_code }),
        el("td", { text: (d.dealer_name || "") + ", " + (d.city || "") + " " + (d.state || "") }),
        el("td", { text: d.region || "" }),
        el("td", {}, [d.status === "active" ? tag("ok", "active") : tag("warn", d.status)]),
        el("td", { class: "num", text: fmt(d.open_recall_repairs_needed) }),
        el("td", {}, [bar(d.completion_rate), el("div", { class: "subtle", text: pct(d.completion_rate) })])
      ]);
    });
    return el("section", { role: "tabpanel", "aria-labelledby": "tab-recalls" }, [
      el("p", { class: "section-note", text: "Gold table built from silver: every registered vehicle covered by a recall, and whether the repair is done. " +
        fmt(s.recall_repairs_done) + " of " + fmt(s.recall_vehicles) + " recall repairs are complete. Recall campaigns are real NHTSA data; owners and repairs are synthetic." }),
      el("h3", { text: "Recalls with the lowest repair completion (20+ vehicles)" }),
      table(["Campaign", "Component", "Defect", "Vehicles", "Repaired", "Completion"], rows),
      el("h3", { text: "Dealers furthest behind on recall repairs", style: "margin-top:20px" }),
      table(["Dealer", "Name and location", "Region", "Status", "Recall repairs", "Completion"], drows)
    ]);
  }

  function pipeline() {
    var L = state.run.layers;
    var desc = { bronze: "Raw text exactly as landed, with batch id, file and load time. Access restricted: holds raw PII.",
                 silver: "Typed, validated, deduplicated and merged. PII hashed. Bad rows go to quarantine; dealer history kept as SCD Type 2.",
                 gold: "Business tables for recall operations and product safety." };
    var cards = ["bronze", "silver", "gold"].map(function (layer) {
      return el("div", { class: "layer" }, [el("h3", { text: layer }), el("p", { text: desc[layer] }),
        el("table", {}, Object.keys(L[layer]).map(function (t) {
          return el("tr", {}, [el("td", { class: "mono-inline", text: t }), el("td", { class: "num", text: fmt(L[layer][t]) })]);
        }))]);
    });
    var hist = state.run.dealer_history.map(function (h) {
      return el("tr", {}, [el("td", { class: "mono", text: h.dealer_code }), el("td", { text: h.region }), el("td", { text: h.status }),
        el("td", { class: "mono", text: String(h.valid_from).slice(0, 16) }), el("td", { class: "mono", text: h.valid_to ? String(h.valid_to).slice(0, 16) : "-" }),
        el("td", {}, [h.is_current ? tag("ok", "current") : tag("plain", "history")])]);
    });
    return el("section", { role: "tabpanel", "aria-labelledby": "tab-pipeline" }, [
      el("p", { class: "section-note", text: "Legacy SQLite database → nightly watermark extract to the landing zone → PySpark bronze, silver and gold → reconciliation against a key-and-hash snapshot of the legacy system. Spark " + state.run.spark_version + "." }),
      el("div", { class: "layers" }, cards),
      el("h3", { text: "Dealer history (SCD Type 2): region and status changes keep their past values" }),
      hist.length ? table(["Dealer", "Region", "Status", "Valid from", "Valid to", ""], hist) : el("p", { class: "subtle", text: "No dealer changes yet." })
    ]);
  }

  function render() {
    if (!state.run) return;
    var y = window.scrollY;
    app.innerHTML = "";
    var blocked = state.run.reconciliation.filter(function (r) { return r.status !== "ready"; })[0];
    app.appendChild(el("h1", { class: "lead", text: "Check that every legacy table matches its lakehouse copy before you switch the legacy system off, and see what each nightly load processed." }));
    var tryLinks = ["Try it: "];
    if (blocked) tryLinks.push(el("a", { tabindex: "0", text: "see why " + blocked.table + " is blocked", onclick: function () { jump("cutover", blocked.table); },
      onkeydown: function (e) { if (e.key === "Enter") jump("cutover", blocked.table); } }), " · ");
    tryLinks.push(el("a", { tabindex: "0", text: "compare a nightly load with a full reload", onclick: function () { jump("loads"); },
      onkeydown: function (e) { if (e.key === "Enter") jump("loads"); } }), " · ");
    tryLinks.push(el("a", { tabindex: "0", text: "find the recalls with the fewest repairs done", onclick: function () { jump("recalls"); },
      onkeydown: function (e) { if (e.key === "Enter") jump("recalls"); } }));
    app.appendChild(el("p", { class: "try" }, tryLinks));
    app.appendChild(kpis());
    app.appendChild(tabs());
    app.appendChild({ cutover: cutover, loads: loads, recalls: recalls, pipeline: pipeline }[state.tab]());
    app.appendChild(el("footer", { class: "sources", id: "sources" }, [
      el("strong", { text: "Data" }),
      el("p", { text: "Recalls and complaints: real NHTSA data for GM vehicles, model years 2021 to 2025. Dealers, owners and repair orders are synthetic and every person is fictional. " +
        state.run.summary.nights + " nightly loads simulated after the initial full load; 8 bad repair orders were planted in the legacy data on purpose." }),
      el("p", {}, ["Source code, Databricks notebook and tests: ", el("a", { href: REPO, text: REPO.replace("https://", "") })])
    ]));
    window.scrollTo(0, y);
  }

  function load() {
    app.innerHTML = "";
    app.appendChild(el("p", { class: "state", text: "Loading the latest pipeline run…" }));
    fetch("data/run.json", { cache: "no-store" })
      .then(function (r) { if (!r.ok) throw new Error("The server answered " + r.status + " for data/run.json."); return r.json(); })
      .then(function (run) {
        if (!run || !run.reconciliation || !run.summary) throw new Error("run.json is not a Legacy to Lakehouse pipeline run.");
        state.run = run;
        document.getElementById("scannedLabel").textContent = "Last run " + new Date(run.generated_at).toLocaleString("en-US",
          { month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit" });
        render();
      })
      .catch(function (e) {
        app.innerHTML = "";
        app.appendChild(el("section", { class: "state error", role: "alert" }, [
          el("h2", { text: "The pipeline run could not be loaded." }),
          el("p", { text: navigator.onLine === false ? "You are offline. Reconnect and try again." :
            e.message + " If you opened index.html from disk, run: python -m http.server -d site 8000" }),
          el("button", { type: "button", class: "btn", onclick: load, text: "Try again" })]));
      });
  }
  function online() { document.getElementById("offline").hidden = navigator.onLine !== false; }
  window.addEventListener("online", online);
  window.addEventListener("offline", online);
  online();
  load();
})();
