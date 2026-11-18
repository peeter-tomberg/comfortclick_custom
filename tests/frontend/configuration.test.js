/* Open configuration.test.html in a browser; results are exposed as testResults. */
window.testResults = [];
const labels = { options: { step: {
  init: { title: "Configuration", menu_options: { fans: "Fans", utilities: "Meters", connection: "Connection", done: "Done" } },
  mapping: { title: "{category}" }, remove_mapping: { title: "Remove fan" },
  fan: { title: "Fan" }, confirm_remove: { title: "Remove fan?" },
  utilities: { title: "Meters", menu_options: { meter_heating: "Heating" } },
  utility: { title: "Heating" }, connection: { title: "Connection" },
}, error: { required: "Enter a value." } } };
window.fetch = async () => ({ ok: true, json: async () => labels });

function assert(condition, message) { if (!condition) throw new Error(message); }
async function idle(panel) {
  for (let i = 0; i < 100; i++) {
    await new Promise((resolve) => setTimeout(resolve, 0));
    if (!panel._busy) return;
  }
  throw new Error("Editor did not become idle");
}
function button(panel, label) {
  const result = [...panel.shadowRoot.querySelectorAll("button")].find((node) => node.textContent.replace(/›$/, "").trim() === label);
  assert(result, `Missing button: ${label}`);
  return result;
}
async function click(panel, label) { button(panel, label).click(); await idle(panel); }

async function editor({ admin = true, extraEntry = false } = {}) {
  const calls = [];
  const flows = new Map();
  let sequence = 0;
  const root = (id, saved = false) => ({ type: "menu", step_id: "init", flow_id: id,
    menu_options: ["fans", "utilities", "connection", "done"], description_placeholders: saved ? { saved: "true" } : {} });
  const mapping = (id) => ({ type: "menu", step_id: "mapping", flow_id: id,
    menu_options: { edit_fan: "Bedroom <img src=x onerror=alert(1)>", add_mapping: "Add fan", remove_mapping: "Remove fan", init: "Back" },
    description_placeholders: { category: "Fans" } });
  const path = { name: "fan_id", required: true, selector: { select: { options: ["cached"], custom_value: true } }, description: { suggested_value: " Old\\Fan " } };
  const api = async (method, url, data) => {
    calls.push({ method, url, data: data && structuredClone(data) });
    if (method === "DELETE") { flows.delete(url.split("/").at(-1)); return {}; }
    if (url.endsWith("/flow")) {
      const id = `flow-${++sequence}`;
      flows.set(id, "init");
      return root(id);
    }
    const id = url.split("/").at(-1);
    assert(flows.has(id), "Request used an aborted flow");
    const action = data.next_step_id;
    let result;
    if (action === "fans" || action === "mapping") result = mapping(id);
    else if (action === "remove_mapping") result = { type: "menu", step_id: action, flow_id: id, menu_options: { remove_fan: "Bedroom", mapping: "Back" } };
    else if (action === "remove_fan") result = { type: "form", step_id: "confirm_remove", flow_id: id, data_schema: [{ name: "confirm", type: "boolean", required: true, default: false }] };
    else if (action === "edit_fan" || action === "add_mapping") result = { type: "form", step_id: "fan", flow_id: id, data_schema: [
      { name: "name", type: "string", required: true, description: { suggested_value: "Bedroom" } }, path,
      { name: "area_id", selector: { area: {} }, description: { suggested_value: "bedroom" } },
      { name: "min_temp", required: true, default: 18.5, selector: { number: { mode: "box", step: "any" } } },
    ] };
    else if (action === "utilities") result = { type: "menu", step_id: action, flow_id: id, menu_options: ["meter_heating", "init"] };
    else if (action === "meter_heating") result = { type: "form", step_id: "utility", flow_id: id, data_schema: [{ ...path, name: "id", required: false },
      { name: "unit", required: true, default: "MWh", selector: { select: { options: ["kWh", "MWh"] } } }] };
    else if (action === "connection") result = { type: "form", step_id: action, flow_id: id, data_schema: [
      { name: "username", type: "string", default: "user" },
      { name: "password", default: "must-not-render", description: { suggested_value: "must-not-render" }, selector: { text: { type: "password" } } },
      { name: "verify_ssl", type: "boolean", required: true, default: false },
    ] };
    else if (action === "done") { flows.delete(id); return { type: "create_entry", flow_id: id }; }
    else if (flows.get(id) === "confirm_remove" && !data.confirm) result = mapping(id);
    else result = root(id, true);
    flows.set(id, result.step_id);
    return result;
  };
  const panel = document.createElement("comfortclick-configuration");
  document.body.append(panel);
  panel.hass = { user: { is_admin: admin }, callApi: api, callWS: async (data) => {
    calls.push({ ws: data });
    if (data.type === "config/area_registry/list") return [{ area_id: "bedroom", name: "Bedroom" }];
    assert(data.domain === "comfortclick_custom", "Entry request must use domain filter");
    return [{ domain: "comfortclick_custom", entry_id: "one", title: "Home" },
      { domain: "other", entry_id: "unrelated", title: "Unrelated" },
      ...(extraEntry ? [{ domain: "comfortclick_custom", entry_id: "two", title: "Other hub" }] : [])];
  } };
  await idle(panel);
  return { panel, calls, flows };
}

const tests = [
  ["Back discards invalid drafts and replays only menu actions", async () => {
    const { panel, calls } = await editor();
    try {
      await click(panel, "Fans");
      assert(!panel.shadowRoot.querySelector("img"), "Menu label was interpreted as HTML");
      await click(panel, "Add fan");
      panel.shadowRoot.querySelector('[name="name"]').value = "";
      panel.shadowRoot.querySelector('[name="fan_id"]').value = "";
      const before = calls.length;
      await click(panel, "← Back");
      const navigation = calls.slice(before);
      assert(navigation[0].method === "DELETE", "Back did not abort draft");
      assert(navigation[1].data.handler === "one", "Back did not start a new flow");
      assert(navigation.length === 3 && navigation[2].data.next_step_id === "fans", "Back replayed more than parent menu navigation");
      assert(panel._result.step_id === "mapping", "Back missed parent menu");
    } finally { panel.remove(); }
  }],
  ["Remove-menu Back and declined removal retain the correct parent", async () => {
    const { panel } = await editor();
    try {
      await click(panel, "Fans"); await click(panel, "Remove fan"); await click(panel, "Back");
      await click(panel, "Bedroom <img src=x onerror=alert(1)>"); await click(panel, "← Back");
      assert(panel._result.step_id === "mapping", "Back returned to removal chooser");
      await click(panel, "Remove fan"); await click(panel, "Bedroom"); await click(panel, "Save");
      await click(panel, "Bedroom <img src=x onerror=alert(1)>"); await click(panel, "← Back");
      assert(panel._result.step_id === "mapping", "Declining removal corrupted parent history");
      await click(panel, "← Back"); assert(panel._result.step_id === "init", "Category Back missed root");
    } finally { panel.remove(); }
  }],
  ["Cancel skips invalid-field validation and discards changes without submitting", async () => {
    const { panel, calls } = await editor();
    try {
      await click(panel, "Fans"); await click(panel, "Add fan");
      panel.shadowRoot.querySelector('[name="name"]').value = "";
      panel.shadowRoot.querySelector('[name="fan_id"]').value = "unsaved-manual-path";
      const actions = [...panel.shadowRoot.querySelectorAll(".actions button")];
      assert(actions[0].textContent === "Cancel" && actions[0].type === "button", "Cancel is not a non-submit button before Save");
      assert(actions[1].textContent === "Save", "Save no longer follows Cancel");
      const before = calls.length;
      await click(panel, "Cancel");
      const navigation = calls.slice(before);
      assert(navigation.length === 3 && navigation[0].method === "DELETE", "Cancel did not discard the current flow");
      assert(navigation[1].data.handler === "one" && navigation[2].data.next_step_id === "fans", "Cancel sent form data instead of menu navigation");
      assert(panel._result.step_id === "mapping", "Cancel missed the parent menu");
      await click(panel, "Add fan");
      assert(panel.shadowRoot.querySelector('[name="fan_id"]').value === " Old\\Fan ", "Cancelled draft was replayed");
    } finally { panel.remove(); }
  }],
  ["Save preserves raw paths, numbers and room clearing, then stays at root", async () => {
    const { panel, calls } = await editor();
    try {
      await click(panel, "Fans"); await click(panel, "Add fan");
      panel.shadowRoot.querySelector('[name="fan_id"]').value = " Room\\Manual path ";
      panel.shadowRoot.querySelector('[name="min_temp"]').value = "18.75";
      panel.shadowRoot.querySelector('[name="area_id"]').value = "";
      await click(panel, "Save");
      const saved = calls.at(-1).data;
      assert(saved.fan_id === " Room\\Manual path ", "Path was trimmed or altered");
      assert(saved.min_temp === 18.75 && saved.area_id === "", "Typed field values changed");
      assert(panel._result.step_id === "init" && panel._status === "Saved.", "Save closed editor or omitted feedback");
    } finally { panel.remove(); }
  }],
  ["Passwords never prefill and false remains a valid boolean", async () => {
    const { panel, calls } = await editor();
    try {
      await click(panel, "Connection");
      const password = panel.shadowRoot.querySelector('[name="password"]');
      assert(password.type === "password" && password.value === "", "Password was exposed");
      assert(!panel.shadowRoot.textContent.includes("must-not-render"), "Password leaked in text");
      await click(panel, "Save");
      assert(calls.at(-1).data.verify_ssl === false && calls.at(-1).data.password === "", "False/empty credential submission changed");
    } finally { panel.remove(); }
  }],
  ["Root navigation skips validation and controller selection stays scoped", async () => {
    const { panel, calls } = await editor({ extraEntry: true });
    try {
      assert(panel.shadowRoot.querySelector("#controller").options.length === 2, "Unrelated integration exposed");
      await click(panel, "Fans"); await click(panel, "Add fan");
      panel.shadowRoot.querySelector('[name="name"]').value = "";
      const before = calls.length;
      await click(panel, "Configuration");
      assert(calls.length === before + 2 && panel._result.step_id === "init", "Root submitted or replayed a form");
      const select = panel.shadowRoot.querySelector("#controller");
      select.value = "two"; select.dispatchEvent(new Event("change")); await idle(panel);
      assert(calls.at(-1).data.handler === "two", "Wrong controller selected");
    } finally { panel.remove(); }
  }],
  ["Non-admin views do not make configuration API calls", async () => {
    const { panel, calls } = await editor({ admin: false });
    try { assert(calls.length === 0 && panel.shadowRoot.textContent.includes("Administrator access"), "Non-admin accessed configuration"); }
    finally { panel.remove(); }
  }],
];

window.testsFinished = (async () => {
  for (const [name, test] of tests) {
    try { await test(); window.testResults.push({ name, passed: true }); }
    catch (error) { window.testResults.push({ name, passed: false, error: error.message }); }
  }
  return window.testResults;
})();
