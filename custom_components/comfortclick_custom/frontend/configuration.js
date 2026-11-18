/* ComfortClick editor. All changes use Home Assistant's standard options flow. */
const FLOW_API = "config/config_entries/options/flow";
const DOMAIN = "comfortclick_custom";
const STALE = Symbol("stale operation");

const STYLE = `
  :host { display:block; height:100%; overflow:auto; color:var(--primary-text-color);
    background:var(--primary-background-color); font:14px var(--paper-font-body1_-_font-family,Roboto,Arial,sans-serif); }
  * { box-sizing:border-box; }
  header { display:flex; align-items:center; gap:12px; min-height:64px; padding:8px 20px;
    border-bottom:1px solid var(--divider-color); background:var(--app-header-background-color,var(--card-background-color));
    color:var(--app-header-text-color,var(--primary-text-color)); }
  header strong { font-size:20px; font-weight:500; }
  main { width:min(100%,760px); margin:0 auto; padding:24px 20px 48px; }
  nav { display:flex; align-items:center; gap:12px; margin-bottom:20px; }
  button,input,select { font:inherit; }
  button { cursor:pointer; min-height:40px; padding:8px 14px; border:1px solid var(--divider-color);
    border-radius:8px; background:var(--card-background-color); color:var(--primary-text-color); }
  button:hover { background:var(--secondary-background-color); }
  button:disabled { opacity:.55; cursor:default; }
  button:focus-visible,input:focus-visible,select:focus-visible,a:focus-visible {
    outline:2px solid var(--primary-color); outline-offset:3px; }
  .text-button { border:0; background:transparent; color:var(--primary-color); padding:8px 4px; }
  .menu-toggle { border:0; background:transparent; color:inherit; font-size:22px; padding:4px 8px; }
  .card { padding:24px; border:1px solid var(--divider-color); border-radius:14px; background:var(--card-background-color); }
  h1 { margin:0 0 10px; font-size:24px; font-weight:500; line-height:1.3; }
  p { line-height:1.5; margin:0 0 20px; white-space:pre-line; overflow-wrap:anywhere; }
  .description,.hint { color:var(--secondary-text-color); }
  .menu { display:grid; gap:8px; margin-top:24px; }
  .menu-row { display:flex; justify-content:space-between; align-items:center; text-align:left; gap:16px; padding:14px 16px; }
  .chevron { color:var(--secondary-text-color); font-size:20px; }
  form { display:grid; gap:20px; margin-top:24px; }
  .field { display:grid; gap:7px; min-width:0; }
  label { font-weight:500; line-height:1.4; }
  input:not([type=checkbox]),select { width:100%; min-height:44px; border:1px solid var(--divider-color);
    border-radius:7px; padding:10px 12px; background:var(--primary-background-color); color:var(--primary-text-color); }
  input[type=checkbox] { width:19px; height:19px; accent-color:var(--primary-color); flex:none; }
  .check { display:flex; align-items:center; gap:10px; }
  .hint { font-size:12px; line-height:1.4; }
  .error { color:var(--error-color,#db4437); font-size:13px; line-height:1.4; }
  [aria-invalid=true] { border-color:var(--error-color,#db4437) !important; }
  .actions { display:flex; justify-content:flex-end; gap:12px; padding-top:4px; }
  .primary { color:var(--text-primary-color,#fff); background:var(--primary-color); border-color:var(--primary-color); }
  .primary:hover { opacity:.9; background:var(--primary-color); }
  .status { padding:0 2px; min-height:26px; line-height:1.5; margin-bottom:10px; color:var(--secondary-text-color); }
  .status.error { color:var(--error-color,#db4437); }
  .hub { display:grid; gap:7px; margin-bottom:20px; }
  a { color:var(--primary-color); }
  @media(max-width:600px) { main { padding:16px 12px 32px; } .card { padding:20px 16px; } header { padding:8px 12px; } }
`;

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined && text !== null) node.textContent = String(text);
  if (className) node.className = className;
  return node;
}

function humanize(value) {
  const text = String(value || "").replaceAll("_", " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function menuChoices(result) {
  const options = result?.menu_options || [];
  return Array.isArray(options) ? options : Object.keys(options);
}

class ComfortClickConfiguration extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._epoch = 0;
    this._busy = false;
    this._initialized = false;
    this._flowId = null;
    this._result = null;
    this._trail = [];
    this._backTrail = [];
    this._menuPaths = new Map();
    this._entries = [];
    this._areas = [];
    this._strings = {};
    this._status = "";
    this._render();
  }

  set hass(value) {
    this._hass = value;
    this._startWhenReady();
  }

  get hass() { return this._hass; }

  set panel(value) { this._panel = value; }

  connectedCallback() { this._startWhenReady(); }

  disconnectedCallback() {
    this._epoch += 1;
    this._initialized = false;
    this._busy = false;
    const flowId = this._flowId;
    this._flowId = null;
    for (const input of this.shadowRoot.querySelectorAll('input[type="password"]')) input.value = "";
    if (flowId) void this._discard(flowId).catch(() => {});
  }

  _startWhenReady() {
    if (!this.isConnected || !this._hass || this._initialized) return;
    this._initialized = true;
    if (!this._hass.user?.is_admin) {
      this._status = "Administrator access is required.";
      this._render();
      return;
    }
    void this._run(async () => {
      const epoch = this._epoch;
      const [entries, labels, areas] = await Promise.all([
        this._hass.callWS({ type: "config_entries/get", domain: DOMAIN }),
        fetch(this._panel?.config?.strings_url || `/${DOMAIN}/strings.json`, {
          credentials: "same-origin", cache: "no-store",
        }).then((response) => {
          if (!response.ok) throw new Error("Labels unavailable");
          return response.json();
        }),
        this._hass.callWS({ type: "config/area_registry/list" }).catch(() => null),
      ]);
      if (epoch !== this._epoch) throw STALE;
      this._entries = entries.filter((entry) => entry.domain === DOMAIN);
      this._entriesLoaded = true;
      this._strings = labels;
      this._areas = areas || [];
      this._areasAvailable = areas !== null;
      this._entryId = this._entries.some((entry) => entry.entry_id === this._entryId)
        ? this._entryId : this._entries[0]?.entry_id;
      if (this._entryId) await this._restart([]);
      else this._render();
    });
  }

  async _run(operation) {
    if (this._busy || !this._hass?.user?.is_admin) return;
    const epoch = this._epoch;
    this._busy = true;
    this._setBusy();
    try {
      await operation();
    } catch (error) {
      if (error !== STALE && epoch === this._epoch) {
        this._setStatus(
          "Unable to complete this request. Your form is still here. Use Configuration to reopen the latest settings.",
          true,
        );
      }
    } finally {
      if (epoch === this._epoch) {
        this._busy = false;
        this._setBusy();
      }
    }
  }

  async _request(method, path, data) {
    const epoch = this._epoch;
    const result = await this._hass.callApi(method, path, data);
    if (epoch !== this._epoch) {
      if (result?.flow_id) void this._discard(result.flow_id).catch(() => {});
      throw STALE;
    }
    return result;
  }

  async _discard(flowId) {
    try {
      await this._hass.callApi("DELETE", `${FLOW_API}/${encodeURIComponent(flowId)}`);
    } catch (error) {
      // A completed or already-aborted flow has nothing left to discard.
      if (error?.status_code !== 404 && error?.status !== 404) throw error;
    }
  }

  async _restart(path) {
    const epoch = this._epoch;
    if (this._flowId) await this._discard(this._flowId);
    if (epoch !== this._epoch) throw STALE;
    this._flowId = null;
    this._trail = [];
    this._backTrail = [];
    this._menuPaths.clear();
    let result = await this._request("POST", FLOW_API, { handler: this._entryId });
    this._flowId = result.flow_id;
    if (result.type === "menu") this._rememberMenu(result);
    for (const action of path) {
      // Only replay observed menu choices. Never store/replay submitted forms.
      if (result.type !== "menu" || !menuChoices(result).includes(action)) break;
      const previous = [...this._trail];
      result = await this._request("POST", `${FLOW_API}/${encodeURIComponent(this._flowId)}`, {
        next_step_id: action,
      });
      this._backTrail = previous;
      if (result.type === "menu") this._rememberMenu(result, action);
      else break;
    }
    this._accept(result);
    this._setStatus("");
  }

  _accept(result, menuAction) {
    this._result = result;
    this._flowId = ["form", "menu"].includes(result.type) ? result.flow_id : null;
    if (result.type === "menu") this._rememberMenu(result, menuAction);
    else if (menuAction) this._backTrail = [...this._trail];
    this._render();
  }

  _rememberMenu(result, menuAction) {
    if (result.step_id === "init") {
      this._trail = [];
      this._backTrail = [];
      this._menuPaths.clear();
    } else if (this._menuPaths.has(result.step_id)) {
      // A menu may itself offer Back, or a declined confirmation may return
      // to an ancestor. Preserve that menu's original path, not the detour.
      this._trail = [...this._menuPaths.get(result.step_id)];
    } else if (menuAction) this._trail.push(menuAction);
    this._menuPaths.set(result.step_id, [...this._trail]);
    this._backTrail = this._trail.slice(0, -1);
  }

  _choose(action) {
    if (!menuChoices(this._result).includes(action)) return;
    void this._run(async () => {
      if (action === "init") {
        await this._restart([]);
        return;
      }
      const result = await this._request("POST", `${FLOW_API}/${encodeURIComponent(this._flowId)}`, {
        next_step_id: action,
      });
      this._accept(result, action);
      this._setStatus("");
    });
  }

  _submit(form, fields) {
    if (!form.reportValidity()) return;
    const data = {};
    for (const { schema, control, kind } of fields) {
      if (kind === "boolean") data[schema.name] = control.checked;
      else if (kind === "number") {
        if (control.value !== "") data[schema.name] = control.valueAsNumber;
      } else data[schema.name] = control.value;
    }
    void this._run(async () => {
      const result = await this._request("POST", `${FLOW_API}/${encodeURIComponent(this._flowId)}`, data);
      this._accept(result);
      this._setStatus(result.description_placeholders?.saved === "true" ? "Saved." : "");
    });
  }

  _text(value) {
    if (typeof value !== "string") return "";
    const placeholders = this._result?.description_placeholders || {};
    return value.replace(/\{([^{}]+)\}/g, (match, name) => String(placeholders[name] ?? match));
  }

  _button(label, action, className) {
    const button = element("button", label, className);
    button.type = "button";
    button.addEventListener("click", action);
    return button;
  }

  _setBusy() {
    for (const control of this.shadowRoot.querySelectorAll("button,input,select")) {
      control.disabled = this._busy || control.dataset.unavailable === "true";
    }
    this.shadowRoot.querySelector("main")?.setAttribute("aria-busy", String(this._busy));
  }

  _setStatus(message, error = false) {
    this._status = message;
    this._statusError = error;
    const status = this.shadowRoot.querySelector(".status");
    if (status) {
      status.textContent = message;
      status.className = error ? "status error" : "status";
    }
  }

  _render() {
    const style = element("style", STYLE);
    const header = element("header");
    const toggle = this._button("☰", () => this.dispatchEvent(new CustomEvent("hass-toggle-menu", {
      bubbles: true, composed: true,
    })), "menu-toggle");
    toggle.setAttribute("aria-label", "Toggle sidebar");
    header.append(toggle, element("strong", "ComfortClick"));
    const main = element("main");
    const nav = element("nav");
    if (this._result && this._result.step_id !== "init") {
      nav.append(this._button("← Back", () => void this._run(() => this._restart([...this._backTrail]))));
    }
    const root = this._button("Configuration", () => {
      if (this._entryId) void this._run(() => this._restart([]));
      else { this._initialized = false; this._startWhenReady(); }
    }, "text-button");
    root.setAttribute("aria-label", "Return to configuration");
    nav.append(root);
    main.append(nav);
    if (this._entries.length > 1) {
      const hub = element("div", null, "hub");
      const label = element("label", "Controller");
      label.htmlFor = "controller";
      const select = element("select");
      select.id = "controller";
      for (const entry of this._entries) {
        const option = element("option", entry.title || "ComfortClick controller");
        option.value = entry.entry_id;
        select.append(option);
      }
      select.value = this._entryId;
      select.addEventListener("change", () => void this._run(async () => {
        const selected = select.value;
        if (this._flowId) await this._discard(this._flowId);
        this._flowId = null;
        this._entryId = selected;
        await this._restart([]);
      }));
      hub.append(label, select);
      main.append(hub);
    }
    const status = element("div", this._status, this._statusError ? "status error" : "status");
    status.setAttribute("role", "status");
    status.setAttribute("aria-live", "polite");
    main.append(status);
    const card = element("section", null, "card");
    const result = this._result;
    const translation = this._strings.options?.step?.[result?.step_id] || {};
    card.append(element("h1", this._text(translation.title) || "Configuration"));
    if (translation.description) card.append(element("p", this._text(translation.description), "description"));
    if (!this._hass?.user?.is_admin) {
      card.append(element("p", this._hass ? "Administrator access is required." : "Loading…", "description"));
    } else if (!result) {
      card.append(element("p", this._entriesLoaded && !this._entries.length
        ? "No ComfortClick controller is configured." : "Loading configuration…", "description"));
    } else if (result.type === "menu") this._renderMenu(card, translation);
    else if (result.type === "form") this._renderForm(card, translation);
    else if (result.type === "abort") {
      card.append(element("p", this._text(this._strings.options?.abort?.[result.reason]) || "This configuration session has ended."));
      card.append(this._button("Return to configuration", () => void this._run(() => this._restart([])), "primary"));
    } else if (result.type === "create_entry") {
      card.append(element("p", "Configuration closed. Your saved settings are available whenever you need them."));
      card.append(this._button("Open configuration", () => void this._run(() => this._restart([])), "primary"));
    } else card.append(element("p", "This step is not supported here. Use Configuration to start again."));
    main.append(card);
    this.shadowRoot.replaceChildren(style, header, main);
    this._setBusy();
  }

  _renderMenu(card, translation) {
    const menu = element("div", null, "menu");
    for (const action of menuChoices(this._result)) {
      if (action === "init") continue; // The persistent header provides navigation.
      const directLabel = !Array.isArray(this._result.menu_options) ? this._result.menu_options[action] : null;
      const label = directLabel || translation.menu_options?.[action] || humanize(action);
      const button = this._button(this._text(label), () => this._choose(action), "menu-row");
      const arrow = element("span", "›", "chevron");
      arrow.setAttribute("aria-hidden", "true");
      button.append(arrow);
      menu.append(button);
    }
    card.append(menu);
  }

  _error(code) { return this._text(this._strings.options?.error?.[code]) || "Check this value."; }

  _renderForm(card, translation) {
    const result = this._result;
    const form = element("form");
    const fields = [];
    const errors = result.errors || {};
    if (errors.base) {
      const error = element("div", this._error(errors.base), "error");
      error.setAttribute("role", "alert");
      form.append(error);
    }
    for (const schema of result.data_schema || []) {
      const field = this._field(schema, translation, errors[schema.name]);
      fields.push(field);
      form.append(field.wrapper);
    }
    const actions = element("div", null, "actions");
    const selecting = ["edit_mapping", "remove_mapping"].includes(result.step_id);
    const informational = !fields.length;
    if (!informational) {
      actions.append(this._button("Cancel", () => void this._run(() => this._restart([...this._backTrail]))));
    }
    if (!informational || !errors.base) {
      const submit = element("button", selecting ? "Continue" : informational ? "Return to configuration" : "Save", "primary");
      submit.type = "submit";
      actions.append(submit);
    }
    form.append(actions);
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      if (informational) void this._run(() => this._restart([]));
      else this._submit(form, fields);
    });
    card.append(form);
  }

  _field(schema, translation, errorCode) {
    const wrapper = element("div", null, "field");
    const selector = schema.selector || {};
    const id = `field-${schema.name}`;
    const label = element("label", translation.data?.[schema.name] || humanize(schema.name));
    label.htmlFor = id;
    const isPassword = schema.name === "password" || selector.text?.type === "password";
    const value = isPassword ? "" : (schema.description?.suggested_value ?? schema.default ?? "");
    let control;
    let kind = "string";
    if (schema.type === "boolean" || selector.boolean) {
      kind = "boolean";
      control = element("input");
      control.type = "checkbox";
      control.checked = value === true;
      const check = element("div", null, "check");
      check.append(control, label);
      wrapper.append(check);
    } else {
      wrapper.append(label);
      if (selector.area) {
        control = element("select");
        this._addOptions(control, [{ value: "", label: "No room" }, ...this._areas.map((area) => ({ value: area.area_id, label: area.name }))]);
        if (value && !this._areas.some((area) => area.area_id === value)) {
          this._addOptions(control, [{ value, label: "Current room (unavailable)" }]);
        }
        if (!this._areasAvailable) wrapper.append(element("span", "Rooms could not be loaded. The current room is preserved.", "hint"));
      } else if (selector.select || schema.type === "select") {
        const config = selector.select || schema;
        const choices = (config.options || []).map((choice) => {
          if (Array.isArray(choice)) return { value: choice[0], label: choice[1] };
          if (typeof choice === "object") return choice;
          return { value: choice, label: this._strings.selector?.[config.translation_key]?.options?.[choice] || choice };
        });
        if (config.custom_value) {
          control = element("input");
          control.type = "text";
          control.autocomplete = "off";
          const list = element("datalist");
          list.id = `${id}-choices`;
          this._addOptions(list, choices);
          control.setAttribute("list", list.id);
          wrapper.append(list);
        } else {
          control = element("select");
          if (!choices.some((choice) => String(choice.value) === String(value))) this._addOptions(control, [{ value: "", label: "Choose…" }]);
          this._addOptions(control, choices);
        }
      } else {
        control = element("input");
        if (selector.number || ["integer", "float", "number"].includes(schema.type)) {
          kind = "number";
          control.type = "number";
          control.step = selector.number?.step ?? (schema.type === "integer" ? "1" : "any");
          for (const limit of ["min", "max"]) {
            const bound = selector.number?.[limit] ?? schema[limit];
            if (bound !== undefined) control[limit] = bound;
          }
        } else {
          control.type = isPassword ? "password" : "text";
          control.autocomplete = isPassword ? "new-password" : "off";
        }
      }
      control.value = String(value);
      control.required = Boolean(schema.required);
      wrapper.append(control);
    }
    control.id = id;
    control.name = schema.name;
    const description = translation.data_description?.[schema.name];
    const unit = selector.number?.unit_of_measurement;
    if (description || unit) {
      const hint = element("span", this._text(description) || unit, "hint");
      hint.id = `${id}-hint`;
      control.setAttribute("aria-describedby", hint.id);
      wrapper.append(hint);
    }
    if (errorCode) {
      const error = element("span", this._error(errorCode), "error");
      error.id = `${id}-error`;
      error.setAttribute("role", "alert");
      control.setAttribute("aria-invalid", "true");
      control.setAttribute("aria-describedby", `${control.getAttribute("aria-describedby") || ""} ${error.id}`.trim());
      wrapper.append(error);
    }
    return { schema, control, wrapper, kind };
  }

  _addOptions(select, choices) {
    for (const choice of choices) {
      const option = element("option", choice.label ?? choice.value);
      option.value = String(choice.value);
      select.append(option);
    }
  }
}

if (!customElements.get("comfortclick-configuration")) {
  customElements.define("comfortclick-configuration", ComfortClickConfiguration);
}
