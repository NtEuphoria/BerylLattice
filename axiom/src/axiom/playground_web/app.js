import { getExamples, runDemo } from "./transport.js";

(() => {
  const $ = (id) => document.getElementById(id);
  const ui = {
    source: $("source"), examples: $("examples"), retry: $("retry-examples"),
    description: $("example-description"), mode: $("input-mode"), custom: $("custom-input"),
    customArea: $("custom-input-area"), run: $("run"), runLabel: $("run-label"), reset: $("reset"),
    download: $("download"), status: $("status"), statusTitle: $("status-title"),
    statusDetail: $("status-detail"), statusSymbol: $("status-symbol"),
    diagnostic: $("diagnostic"), empty: $("empty-state"), content: $("result-content"),
    selection: $("selection-summary"), candidates: $("candidate-rows"),
    outputSection: $("output-section"), output: $("output-grid"), input: $("input-grid"),
    results: document.querySelector(".results-panel"),
  };
  const schedules = {
    "inline-v1": { title: "Recompute inline", description: "Recalculates values when needed, using no temporary plan storage." },
    "rows2-v1": { title: "Retain two rows", description: "Keeps two rows of calculated values to reuse in the next step." },
    "materialize-v1": { title: "Store all intermediates", description: "Calculates each intermediate value once and stores the whole grid." },
  };
  const exampleCopy = {
    "balanced": { title: "Fewer calculations", description: "Allow 64 bytes of temporary storage and prefer fewer multiplications." },
    "no-scratch": { title: "No temporary storage", description: "Allow no temporary storage. beryl must recalculate values instead of saving them." },
    "small-memory": { title: "Least storage", description: "Allow up to 64 bytes, but prefer the plan that uses the least temporary storage." },
  };
  let examples = [];
  let requestId = 0;
  let activeController = null;
  let currentReport = null;
  let loadingExamples = true;
  const inBrowser = document.documentElement.dataset.runtime === "browser";
  $("runtime-label").textContent = inBrowser ? "Runs in your browser" : "Local Python runtime";
  $("release-links").hidden = !inBrowser;

  function setStatus(kind, title, detail) {
    ui.status.className = `status status-${kind}`;
    ui.statusSymbol.textContent = { idle: "○", loading: "◌", success: "✓", error: "!", warning: "↻" }[kind] || "○";
    ui.statusTitle.textContent = title;
    ui.statusDetail.textContent = detail;
  }

  function clearResult() {
    currentReport = null;
    ui.download.disabled = true;
    ui.content.hidden = true;
    ui.diagnostic.hidden = true;
    ui.empty.hidden = false;
    ui.candidates.replaceChildren();
    ui.output.replaceChildren();
    ui.input.replaceChildren();
    ui.selection.hidden = true;
    ui.outputSection.hidden = true;
  }

  function setRunning(running) {
    ui.results.setAttribute("aria-busy", String(running));
    ui.runLabel.textContent = running ? "Running…" : "Run computation";
    ui.run.disabled = running || loadingExamples || !ui.source.value.trim();
    ui.reset.disabled = loadingExamples || examples.length === 0;
  }

  function updateExampleSelection() {
    let selected = null;
    for (const button of ui.examples.querySelectorAll("button")) {
      const example = examples.find((item) => item.id === button.dataset.example);
      const matches = example?.source === ui.source.value;
      button.setAttribute("aria-pressed", String(matches));
      if (matches) selected = example;
    }
    ui.description.textContent = selected ? (exampleCopy[selected.id]?.description || selected.description) : "Edited example. Run it to check your code and constraints.";
  }

  function invalidate() {
    requestId += 1;
    if (activeController) activeController.abort();
    activeController = null;
    clearResult();
    setRunning(false);
    updateExampleSelection();
    setStatus("idle", "Changes ready to run", "Run again to see the result for your current code and inputs.");
  }

  function resetExample() {
    if (ui.reset.disabled) return;
    ui.source.value = examples[0].source;
    ui.mode.value = "ramp";
    ui.custom.value = "";
    ui.customArea.hidden = true;
    // Use the same cancellation and stale-result guard as editing a request.
    invalidate();
    setStatus("idle", "Ready to run", "The default example and increasing numbers are restored. Run it to see a new result.");
  }

  function showDiagnostic(code, message, offset = null) {
    ui.diagnostic.hidden = false;
    $("diagnostic-code").textContent = `${code}${Number.isInteger(offset) ? ` · source byte ${offset}` : ""}`;
    $("diagnostic-message").textContent = message;
  }

  function scheduleTitle(planId) {
    return schedules[planId]?.title || planId;
  }

  function cell(tag, text) {
    const node = document.createElement(tag);
    node.textContent = String(text);
    return node;
  }

  function formatCount(value, unit = "") {
    return Number.isInteger(value) ? `${value.toLocaleString()}${unit}` : "—";
  }

  function renderCandidates(result) {
    ui.candidates.replaceChildren();
    for (const attempt of result.attempts || []) {
      const row = document.createElement("tr");
      const selected = attempt.plan_id === result.selected?.plan_id;
      if (selected) row.className = "selected-row";
      row.append(cell("td", scheduleTitle(attempt.plan_id)));
      row.append(cell("td", formatCount(attempt.workspace_bytes, " B")));
      row.append(cell("td", formatCount(attempt.multiplication_ops)));
      const decision = cell("td", selected ? "Selected" : attempt.eligible ? "Also fits" : "Not available");
      if (selected) decision.className = "decision-selected";
      const reasonText = attempt.constraint_status === "violated" ? "Exceeds storage limit"
        : attempt.constraint_status === "unknown" ? "Constraint not established"
        : attempt.semantic_status === "unknown" ? "Validity not established"
        : attempt.reason;
      if (!attempt.eligible && reasonText) {
        const reason = cell("span", reasonText);
        reason.className = "candidate-reason";
        decision.append(reason);
      }
      row.append(decision);
      ui.candidates.append(row);
    }
  }

  function renderMatrix(container, values, height, width, label) {
    container.replaceChildren();
    if (!Array.isArray(values) || !Number.isInteger(height) || !Number.isInteger(width) || height < 1 || width < 1 || height * width > 256 || values.length !== height * width) return;
    const table = document.createElement("table");
    table.className = "matrix-table";
    const caption = cell("caption", `${label}: ${height} rows by ${width} columns. Indices begin at zero.`);
    caption.className = "sr-only";
    table.append(caption);
    const head = document.createElement("thead");
    const headingRow = document.createElement("tr");
    const corner = cell("th", "r / c");
    corner.scope = "col";
    headingRow.append(corner);
    for (let column = 0; column < width; column += 1) {
      const th = cell("th", column);
      th.scope = "col";
      headingRow.append(th);
    }
    head.append(headingRow);
    table.append(head);
    const body = document.createElement("tbody");
    for (let rowIndex = 0; rowIndex < height; rowIndex += 1) {
      const row = document.createElement("tr");
      const labelCell = cell("th", rowIndex);
      labelCell.scope = "row";
      row.append(labelCell);
      for (let column = 0; column < width; column += 1) row.append(cell("td", values[rowIndex * width + column]));
      body.append(row);
    }
    table.append(body);
    container.append(table);
  }

  function renderDetails(result) {
    const details = $("run-details");
    details.replaceChildren();
    const fields = [
      ["Execution", result.backend], ["Objective", result.objective],
      ["Compilation", result.timings ? (result.timings.reused_compilation ? `${result.timings.initial_compilation_ms.toFixed(2)} ms once; reused` : `${result.timings.compilation_ms.toFixed(2)} ms`) : null],
      ["Compiled execution", result.timings ? `${result.timings.execution_ms.toFixed(3)} ms` : null],
      ["Independent comparison", result.timings ? `${result.timings.verification_ms.toFixed(2)} ms` : null],
      ["Scratch limit", result.workspace_cap == null ? "None declared" : `${result.workspace_cap} bytes`],
      ["Search stopped", result.search?.termination_reason], ["Search work", result.search?.work_used],
      ["Source digest", result.source_digest], ["Plan digest", result.selected?.plan_digest],
    ];
    for (const [name, value] of fields) {
      if (value != null) details.append(cell("dt", name), cell("dd", value));
    }
  }

  function renderResult(result) {
    if (!result || result.schema_version !== 1 || !["success", "input_precondition_failed", "no_eligible_plan", "error"].includes(result.status)) throw new Error("The server returned an unrecognized result. No execution result is shown.");
    if (result.status === "success" && (!result.selected || !result.shape || !Array.isArray(result.output) || result.comparison?.matches !== true || result.comparison.cells_compared !== result.output.length || result.output.length !== result.shape.height * result.shape.width)) throw new Error("The server returned an incomplete comparison. No successful result is shown.");
    ui.empty.hidden = true;
    ui.content.hidden = !Array.isArray(result.attempts);
    if (result.diagnostic) showDiagnostic(result.diagnostic.code, result.diagnostic.message, result.diagnostic.offset);
    if (result.status === "success") {
      setStatus("success", "Run complete", `All ${result.comparison.cells_compared} output values match a separate calculation of the source.`);
    } else if (result.status === "input_precondition_failed") {
      setStatus("warning", "Input rejected", `Input at index ${result.first_bad_index ?? "unknown"} is outside the allowed range. The plan did not run; the output buffer is unchanged.`);
    } else if (result.status === "no_eligible_plan") {
      setStatus("warning", "No plan fits these constraints", "None of the checked plans meets this request within the search budget. Nothing was run.");
    } else {
      setStatus("error", "This request could not be completed", "Read the diagnostic, adjust the source or inputs, and run again.");
    }
    if (result.selected && result.shape) {
      ui.selection.hidden = false;
      $("selected-name").textContent = scheduleTitle(result.selected.plan_id);
      const preference = result.objective === "multiplication_ops" ? "fewer multiplications" : "less temporary storage";
      const limit = result.workspace_cap == null ? "no storage limit declared" : `a ${result.workspace_cap}-byte storage limit`;
      $("selected-explanation").textContent = `${schedules[result.selected.plan_id]?.description || "Selected from the checked plans."} Your request prefers ${preference}, with ${limit}.`;
      $("selected-workspace").textContent = formatCount(result.selected.workspace_bytes, " B");
      $("selected-multiplications").textContent = formatCount(result.selected.multiplication_ops);
      $("selected-shape").textContent = `${result.shape.height} × ${result.shape.width}`;
    }
    $("objective-label").textContent = result.objective === "multiplication_ops" ? "Preference: fewer multiplications" : result.objective === "plan_workspace_bytes" ? "Preference: less temporary storage" : "";
    renderCandidates(result);
    if (result.shape && Array.isArray(result.output)) {
      ui.outputSection.hidden = false;
      ui.outputSection.classList.toggle("output-unverified", result.status !== "success");
      $("output-heading").textContent = result.status === "input_precondition_failed" ? "Unchanged output buffer" : "Output";
      $("comparison-label").textContent = result.status === "success" ? `${result.comparison.cells_compared} values checked` : "The plan did not run";
      renderMatrix(ui.output, result.output, result.shape.height, result.shape.width, "Output");
    }
    $("input-details").hidden = !(result.shape && Array.isArray(result.input));
    if (result.shape && Array.isArray(result.input)) {
      $("input-shape-label").textContent = `${result.shape.input_height} × ${result.shape.input_width}`;
      renderMatrix(ui.input, result.input, result.shape.input_height, result.shape.input_width, "Input");
    }
    renderDetails(result);
    currentReport = result;
    ui.download.disabled = false;
  }

  async function run() {
    if (ui.run.disabled) return;
    const id = ++requestId;
    if (activeController) activeController.abort();
    clearResult();
    const request = { source: ui.source.value, input_mode: ui.mode.value };
    if (request.input_mode === "custom") {
      try {
        request.inputs = JSON.parse(ui.custom.value);
        if (!Array.isArray(request.inputs)) throw new Error("Use a flat JSON array of integers.");
      } catch (error) {
        setStatus("error", "Custom input is not a JSON array", "Correct the input array and run again.");
        showDiagnostic("CUSTOM_INPUT_JSON", error.message);
        ui.custom.focus();
        return;
      }
    }
    activeController = new AbortController();
    const controller = activeController;
    let timedOut = false;
    const timeout = window.setTimeout(() => { timedOut = true; controller.abort(); }, 15000);
    setRunning(true);
    setStatus("loading", "Running your computation…", "beryl prepares the program when the source changes, then runs it and independently checks the result.");
    try {
      const result = await runDemo(request, { signal: controller.signal });
      if (id !== requestId) return;
      renderResult(result);
    } catch (error) {
      if (id !== requestId) return;
      clearResult();
      setStatus("error", timedOut ? "The run took too long" : "Could not complete this run", timedOut ? "The client stopped waiting after 15 seconds. Try the request again." : inBrowser ? "No current result is available. Try again, or reload the page to restart the browser runtime." : "No current result is available. Check that the local playground server is still running.");
      showDiagnostic(timedOut ? "CLIENT_TIMEOUT" : "REQUEST_FAILED", timedOut ? "No execution result was accepted." : error.message);
    } finally {
      window.clearTimeout(timeout);
      if (id === requestId) {
        activeController = null;
        setRunning(false);
      }
    }
  }

  async function loadExamples() {
    loadingExamples = true;
    ui.examples.setAttribute("aria-busy", "true");
    ui.retry.hidden = true;
    const loadingCopy = cell("p", "Loading examples…");
    loadingCopy.className = "loading-copy";
    ui.examples.replaceChildren(loadingCopy);
    setRunning(Boolean(activeController));
    const initialSource = ui.source.value;
    const initialRequestId = requestId;
    const initializing = !initialSource.trim() && !currentReport && !activeController;
    if (initializing) setStatus("loading", inBrowser ? "Preparing the beryl runtime…" : "Loading the examples…", inBrowser ? "The first visit downloads the Python runtime. Computations then run in this browser." : "Connecting to the local Python runtime.");
    try {
      const data = await getExamples();
      if (!Array.isArray(data.examples) || data.examples.length === 0 || data.examples.some((item) => !item || ["id", "title", "description", "source"].some((key) => typeof item[key] !== "string"))) throw new Error("Invalid example response");
      examples = data.examples;
      ui.examples.replaceChildren();
      for (const example of examples) {
        const button = cell("button", exampleCopy[example.id]?.title || example.title);
        button.type = "button";
        button.className = "example-button";
        button.dataset.example = example.id;
        button.setAttribute("aria-pressed", "false");
        button.addEventListener("click", () => { ui.source.value = example.source; invalidate(); });
        ui.examples.append(button);
      }
      if (!initialSource && !ui.source.value) ui.source.value = examples[0].source;
      updateExampleSelection();
      if (initializing && requestId === initialRequestId) setStatus("idle", "Ready to run", "An example is loaded. Run it to see the output and the plan beryl chooses.");
    } catch (error) {
      const failureCopy = cell("p", "Examples could not be loaded.");
      failureCopy.className = "loading-copy";
      ui.examples.replaceChildren(failureCopy);
      ui.retry.hidden = false;
      if (initializing && requestId === initialRequestId) setStatus("error", "The examples are unavailable", inBrowser ? "The browser runtime could not load. Check your connection and retry, or reload this page." : "Check that the local playground server is running, then retry. You can also enter source yourself.");
    } finally {
      loadingExamples = false;
      ui.examples.setAttribute("aria-busy", "false");
      setRunning(Boolean(activeController));
    }
  }

  ui.source.addEventListener("input", invalidate);
  ui.custom.addEventListener("input", invalidate);
  ui.mode.addEventListener("change", () => { ui.customArea.hidden = ui.mode.value !== "custom"; invalidate(); });
  ui.run.addEventListener("click", run);
  ui.reset.addEventListener("click", resetExample);
  ui.retry.addEventListener("click", loadExamples);
  document.addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key === "Enter") { event.preventDefault(); run(); }
  });
  ui.download.addEventListener("click", () => {
    if (!currentReport) return;
    const url = URL.createObjectURL(new Blob([`${JSON.stringify(currentReport, null, 2)}\n`], { type: "application/json" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = "beryl-result.json";
    document.body.append(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  });
  loadExamples();
})();
