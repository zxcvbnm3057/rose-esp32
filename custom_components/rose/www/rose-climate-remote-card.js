const MODES = [
  ["auto", "自动", "mdi:autorenew"],
  ["cool", "制冷", "mdi:snowflake"],
  ["heat", "制热", "mdi:fire"],
  ["dry", "除湿", "mdi:water-percent"],
  ["fan_only", "送风", "mdi:fan"],
];
const FANS = [
  ["auto", "自动"], ["min", "静音"], ["low", "低"], ["medium", "中"], ["high", "高"],
];
const MODE_ORDER = ["cool", "dry", "fan_only", "heat"];
const FAN_ICONS = {
  auto: "mdi:fan-auto",
  min: "mdi:fan-speed-1",
  low: "mdi:fan-speed-1",
  medium: "mdi:fan-speed-2",
  high: "mdi:fan-speed-3",
};
const MODE_COLORS = {
  cool: "#2196f3",
  dry: "#ffb300",
  fan_only: "#26a69a",
  heat: "#ef5350",
  off: "#9e9e9e",
};
const TIMER_OPTIONS = [0, 10, 30, 60, 90, 120, 180, 240, 360, 480];

class RoseClimateRemoteCardEditor extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
  }

  setConfig(config) {
    this._config = { ...config };
    this._render();
  }

  set hass(value) {
    this._hass = value;
    this._render();
  }

  _updateConfig(key, value) {
    const config = { ...this._config };
    if (key === "name" && !value.trim()) delete config.name;
    else config[key] = value;
    this._config = config;
    this.dispatchEvent(new CustomEvent("config-changed", {
      bubbles: true,
      composed: true,
      detail: { config },
    }));
  }

  _render() {
    if (!this.shadowRoot || !this._config || !this._hass) return;
    this.shadowRoot.innerHTML = `<style>
      .editor { display:grid; gap:16px; padding:8px 0; }
      ha-entity-picker, ha-textfield { width:100%; }
    </style>
    <div class="editor">
      <ha-entity-picker label="空调实体" allow-custom-entity></ha-entity-picker>
      <ha-textfield label="标题名称" placeholder="留空则使用实体名称"></ha-textfield>
    </div>`;

    const entityPicker = this.shadowRoot.querySelector("ha-entity-picker");
    entityPicker.hass = this._hass;
    entityPicker.value = this._config.entity || "";
    entityPicker.includeDomains = ["climate"];
    entityPicker.addEventListener("value-changed", (event) => {
      const value = event.detail?.value ?? event.target.value;
      if (value) this._updateConfig("entity", value);
    });

    const nameField = this.shadowRoot.querySelector("ha-textfield");
    nameField.value = this._config.name || "";
    nameField.addEventListener("change", (event) => {
      this._updateConfig("name", event.target.value || "");
    });
  }
}

class RoseClimateRemoteCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._registry = null;
    this._entities = {};
    this._menuOpen = false;
  }

  setConfig(config) {
    if (!config.entity || !config.entity.startsWith("climate.")) {
      throw new Error("Rose Climate Remote requires a climate entity");
    }
    this._config = config;
    this._loadRegistry();
    this._render();
  }

  set hass(value) {
    this._hass = value;
    this._loadRegistry();
    this._render();
  }

  getCardSize() { return 8; }

  static async getConfigElement() {
    return document.createElement("rose-climate-remote-card-editor");
  }

  static getStubConfig(hass) {
    return {
      entity: Object.keys(hass.states).find((id) => id.startsWith("climate.")),
    };
  }

  async _loadRegistry() {
    if (!this._hass || !this._config || this._registryLoading || this._registry) return;
    this._registryLoading = true;
    try {
      this._registry = await this._hass.callWS({ type: "config/entity_registry/list" });
      const main = this._registry.find((entry) => entry.entity_id === this._config.entity);
      const prefix = main?.unique_id?.startsWith("rose_climate_")
        ? main.unique_id
        : null;
      if (prefix) {
        const suffixes = ["econo", "health", "turbo", "light", "aux_heat", "sleep"];
        for (const suffix of suffixes) {
          this._entities[suffix] = this._registry.find(
            (entry) => entry.unique_id === `${prefix}_${suffix}`
          )?.entity_id;
        }
        this._entities.timer = this._registry.find(
          (entry) => entry.unique_id === `${prefix}_timer`
        )?.entity_id;
      }
    } catch (error) {
      console.warn("Rose climate card could not load entity registry", error);
    } finally {
      this._registryLoading = false;
      this._render();
    }
  }

  _state(entityId = this._config?.entity) {
    return entityId ? this._hass?.states?.[entityId] : undefined;
  }

  _available(entityId) {
    const state = this._state(entityId);
    return Boolean(state && !["unavailable", "unknown"].includes(state.state));
  }

  _call(domain, service, data = {}, entityId = this._config.entity) {
    if (!this._hass || !entityId) return;
    this._hass.callService(domain, service, { entity_id: entityId, ...data });
  }

  _toggle(entityId) {
    if (this._available(entityId)) this._call("homeassistant", "toggle", {}, entityId);
  }

  async _setMode(mode) {
    const active = (key) => this._state(this._entities[key])?.state === "on";
    const incompatible = [];
    if (mode !== "heat" && active("aux_heat")) incompatible.push("aux_heat");
    if (mode !== "cool" && active("econo")) incompatible.push("econo");
    if (!["cool", "heat"].includes(mode) && active("turbo")) incompatible.push("turbo");
    if (!["cool", "dry", "heat"].includes(mode) && active("sleep")) incompatible.push("sleep");
    await Promise.all(incompatible.map((key) => this._hass.callService(
      "homeassistant", "turn_off", { entity_id: this._entities[key] }
    )));
    this._call("climate", "set_hvac_mode", { hvac_mode: mode });
  }

  async _toggleExtended(action, conflicts = []) {
    const entityId = this._entities[action];
    if (!this._available(entityId)) return;
    if (this._state(entityId)?.state !== "on") {
      await Promise.all(conflicts.filter((key) => this._state(this._entities[key])?.state === "on")
        .map((key) => this._hass.callService(
          "homeassistant", "turn_off", { entity_id: this._entities[key] }
        )));
    }
    this._toggle(entityId);
  }

  _menuItem(label, icon, action, active = false, enabled = true) {
    return `<button class="menu-item${active ? " active" : ""}" ${enabled ? "" : "disabled"} data-action="${action}">
      <ha-icon icon="${icon}"></ha-icon><span>${label}</span><span class="toggle"></span>
    </button>`;
  }

  _render() {
    if (!this.shadowRoot || !this._config) return;
    const state = this._state();
    const attributes = state?.attributes || {};
    const power = state && state.state !== "off" && state.state !== "unavailable";
    const temperature = Math.round(attributes.temperature ?? 26);
    const currentTemperature = Number(attributes.current_temperature);
    const hasCurrentTemperature = attributes.current_temperature != null
      && Number.isFinite(currentTemperature);
    const humidityValue = attributes.current_humidity ?? attributes.humidity;
    const currentHumidity = Number(humidityValue);
    const hasCurrentHumidity = humidityValue != null && Number.isFinite(currentHumidity);
    const environmentReadings = [
      hasCurrentTemperature
        ? `<span><ha-icon icon="mdi:home-thermometer-outline"></ha-icon> ${Math.round(currentTemperature)} °C</span>`
        : "",
      hasCurrentHumidity
        ? `<span><ha-icon icon="mdi:water-percent"></ha-icon> ${Math.round(currentHumidity)}%</span>`
        : "",
    ].filter(Boolean).join("");
    const fan = FANS.find(([value]) => value === attributes.fan_mode)?.[1] || attributes.fan_mode || "--";
    const fanIcon = FAN_ICONS[attributes.fan_mode] || "mdi:fan";
    const ext = (key) => this._state(this._entities[key]);
    const active = (key) => ext(key)?.state === "on";
    const enabled = (key) => this._available(this._entities[key]);
    const timerState = this._state(this._entities.timer);
    const timerMinutes = Math.round(Number(timerState?.state) || 0);
    const timerOptions = [...new Set([...TIMER_OPTIONS, timerMinutes])].sort((left, right) => left - right);
    const minimumTemperature = Number(attributes.min_temp) || 16;
    const maximumTemperature = Number(attributes.max_temp) || 31;
    const temperatureSweep = (value) => Math.max(0, Math.min(270,
      ((value - minimumTemperature) / (maximumTemperature - minimumTemperature)) * 270
    ));
    const targetSweep = temperatureSweep(temperature);
    const markerPosition = (value) => {
      const radians = (225 + temperatureSweep(value)) * Math.PI / 180;
      return {
        left: 50 + 43.5 * Math.sin(radians),
        top: 50 - 43.5 * Math.cos(radians),
      };
    };
    const targetPosition = markerPosition(temperature);
    const currentPosition = hasCurrentTemperature ? markerPosition(currentTemperature) : null;
    const modeColor = MODE_COLORS[power ? state.state : "off"] || MODE_COLORS.off;
    const turboEnabled = enabled("turbo") && power && ["cool", "heat"].includes(state?.state) && !active("econo");
    const sleepEnabled = enabled("sleep") && power && ["cool", "dry", "heat"].includes(state?.state) && !active("turbo");
    const auxHeatEnabled = enabled("aux_heat") && power && state?.state === "heat";
    const econoEnabled = enabled("econo") && power && state?.state === "cool" && !active("turbo");

    this.shadowRoot.innerHTML = `<style>
      :host { display:block; container-type:inline-size; --accent:${modeColor}; --ink:var(--primary-text-color,#202124); }
      ha-card { position:relative; overflow:visible; color:var(--ink); font-family:var(--paper-font-body1_-_font-family,"Microsoft YaHei",sans-serif); }
      .remote { width:100%; min-width:0; padding:clamp(12px,3.2cqw,20px) clamp(10px,3cqw,18px) clamp(12px,3cqw,18px); box-sizing:border-box; }
      .header { min-height:34px; display:flex; align-items:center; justify-content:center; position:relative; padding-inline:44px; font-size:clamp(17px,4cqw,22px); font-weight:500; overflow-wrap:anywhere; text-align:center; }
      .more { position:absolute; right:-4px; top:-8px; width:44px; height:44px; border:0; background:transparent; color:var(--secondary-text-color,#666); cursor:pointer; border-radius:50%; }
      .more ha-icon { --mdc-icon-size:28px; }
      .dial-wrap { width:100%; display:grid; place-items:center; position:relative; padding-block:clamp(12px,4cqw,24px); }
      .dial { width:min(100%,420px); aspect-ratio:1; border-radius:50%; background:conic-gradient(from 225deg,var(--accent) 0deg ${power ? targetSweep : 0}deg,#e8e8e8 ${power ? targetSweep : 0}deg 270deg,transparent 270deg); position:relative; display:grid; place-items:center; }
      .dial::after { content:""; position:absolute; inset:clamp(18px,7%,30px); border-radius:50%; background:var(--ha-card-background,var(--card-background-color,#fff)); }
      .temperature-marker { position:absolute; z-index:3; transform:translate(-50%,-50%); width:clamp(14px,4.2cqw,18px); height:clamp(14px,4.2cqw,18px); border:3px solid var(--ha-card-background,var(--card-background-color,#fff)); border-radius:50%; background:var(--accent); box-shadow:0 0 0 2px var(--accent); }
      .temperature-marker.current { width:clamp(12px,3.5cqw,15px); height:clamp(12px,3.5cqw,15px); background:var(--ha-card-background,var(--card-background-color,#fff)); }
      .temperature-marker span { position:absolute; left:50%; bottom:clamp(18px,5cqw,22px); transform:translateX(-50%); padding:2px 6px; border-radius:8px; color:var(--ink); background:var(--ha-card-background,var(--card-background-color,#fff)); font-size:clamp(10px,2.8cqw,12px); font-weight:600; white-space:nowrap; box-shadow:0 1px 4px rgba(0,0,0,.16); }
      .temperature-marker.current span { top:20px; bottom:auto; }
      .dial-center { position:relative; z-index:1; text-align:center; }
      .dial-state { font-size:clamp(38px,11cqw,58px); line-height:1.1; }
      .dial-temp { margin-top:clamp(10px,3.5cqw,18px); display:grid; justify-items:center; gap:clamp(4px,1.5cqw,7px); font-size:clamp(15px,4cqw,21px); font-weight:600; }
      .dial-temp span { display:flex; align-items:center; white-space:nowrap; }
      .under-dial { width:min(100%,420px); margin:clamp(-42px,-7cqw,-24px) auto clamp(12px,3.5cqw,20px); position:relative; z-index:2; }
      .swing-status { display:grid; grid-template-columns:minmax(0,1fr) minmax(0,1fr); gap:clamp(10px,5cqw,34px); color:var(--secondary-text-color,#777); text-align:center; }
      .swing-status span { display:flex; align-items:center; justify-content:center; gap:clamp(3px,1.5cqw,7px); min-width:0; font-size:clamp(12px,3.2cqw,15px); white-space:nowrap; }
      .swing-status ha-icon { --mdc-icon-size:clamp(19px,5cqw,23px); }
      .temperature-adjust { display:grid; grid-template-columns:minmax(0,1fr) minmax(0,1fr); gap:clamp(10px,5cqw,34px); align-items:center; margin-top:clamp(8px,2.8cqw,14px); }
      .temperature-adjust button { justify-self:center; width:clamp(52px,16cqw,72px); height:clamp(48px,13cqw,58px); border:0; background:transparent; color:var(--ink); display:grid; place-items:center; cursor:pointer; }
      .temperature-adjust button ha-icon { --mdc-icon-size:clamp(34px,10cqw,44px); }
      .temperature-adjust button:disabled { opacity:.3; cursor:not-allowed; }
      .mode-strip { height:clamp(52px,14cqw,64px); display:grid; grid-template-columns:repeat(5,minmax(0,1fr)); border-radius:clamp(12px,4cqw,18px); overflow:hidden; background:var(--secondary-background-color,#f2f2f2); }
      .mode-button { border:0; background:transparent; color:var(--ink); cursor:pointer; display:grid; place-items:center; }
      .mode-button ha-icon { --mdc-icon-size:clamp(23px,6cqw,28px); }
      .mode-button.active { color:#fff; background:var(--accent); border-radius:18px; }
      .row { width:100%; height:clamp(52px,14cqw,64px); margin-top:clamp(10px,3cqw,18px); padding:0 clamp(12px,3.5cqw,18px); border:0; border-radius:clamp(12px,4cqw,18px); background:var(--secondary-background-color,#f2f2f2); color:var(--ink); display:flex; align-items:center; gap:clamp(8px,3cqw,14px); font-size:clamp(16px,4cqw,20px); }
      .row ha-icon { --mdc-icon-size:clamp(23px,6cqw,28px); }
      .row select { flex:1; min-width:0; height:100%; border:0; outline:0; appearance:auto; background:transparent; color:var(--ink); font:inherit; cursor:pointer; }
      .menu { position:absolute; z-index:10; top:clamp(50px,12cqw,58px); right:clamp(6px,2cqw,12px); width:min(310px,calc(100% - 12px)); max-height:min(420px,calc(100vh - 100px)); overflow-y:auto; padding:8px; border-radius:12px; background:var(--ha-card-background,var(--card-background-color,#fff)); box-shadow:0 6px 24px rgba(0,0,0,.24); display:${this._menuOpen ? "grid" : "none"}; }
      .menu-item { height:50px; border:0; border-radius:8px; padding:0 10px; background:transparent; color:var(--ink); display:grid; grid-template-columns:32px 1fr 38px; align-items:center; gap:8px; text-align:left; font-size:16px; cursor:pointer; }
      .menu-item:hover { background:var(--secondary-background-color,#f2f2f2); }
      .menu-item ha-icon { --mdc-icon-size:23px; }
      .menu-item .toggle { width:34px; height:20px; border-radius:10px; background:#bbb; position:relative; }
      .menu-item .toggle::after { content:""; position:absolute; width:16px; height:16px; left:2px; top:2px; border-radius:50%; background:#fff; transition:left .15s; }
      .menu-item.active .toggle { background:var(--accent); }
      .menu-item.active .toggle::after { left:16px; }
      .menu-item:disabled { opacity:.4; cursor:not-allowed; }
      @container (max-width:320px) {
        .remote { padding-inline:8px; }
        .header { padding-inline:38px; }
        .temperature-marker span { display:none; }
        .swing-status span { white-space:normal; line-height:1.15; }
        .menu-item { grid-template-columns:28px minmax(0,1fr) 34px; padding-inline:6px; font-size:14px; }
      }
    </style>
    <ha-card>
      <div class="remote">
        <div class="header">${this._config.name || attributes.friendly_name || "空调"}<button class="more" data-action="menu" title="扩展控制"><ha-icon icon="mdi:dots-vertical"></ha-icon></button></div>
        <div class="dial-wrap">
          <div class="dial">
            ${power ? `<div class="temperature-marker target" style="left:${targetPosition.left}%;top:${targetPosition.top}%"><span>设定 ${temperature}°</span></div>` : ""}
            ${power && currentPosition ? `<div class="temperature-marker current" style="left:${currentPosition.left}%;top:${currentPosition.top}%"><span>当前 ${Math.round(currentTemperature)}°</span></div>` : ""}
            <div class="dial-center">
              <div class="dial-state">${power ? `${temperature}°` : "关闭"}</div>
              ${environmentReadings ? `<div class="dial-temp">${environmentReadings}</div>` : ""}
            </div>
          </div>
        </div>
        <div class="under-dial">
          <div class="swing-status">
            <span><ha-icon icon="mdi:swap-vertical"></ha-icon>${["vertical","both"].includes(attributes.swing_mode) ? "上下风向" : "上下固定"}</span>
            <span><ha-icon icon="mdi:swap-horizontal"></ha-icon>${["horizontal","both"].includes(attributes.swing_mode) ? "左右风向" : "左右固定"}</span>
          </div>
          <div class="temperature-adjust">
            <button data-action="temp-down" title="降低设定温度" aria-label="降低设定温度" ${power ? "" : "disabled"}><ha-icon icon="mdi:minus"></ha-icon></button>
            <button data-action="temp-up" title="提高设定温度" aria-label="提高设定温度" ${power ? "" : "disabled"}><ha-icon icon="mdi:plus"></ha-icon></button>
          </div>
        </div>
        <div class="mode-strip">
          <button class="mode-button${!power ? " active" : ""}" data-action="power" title="关闭"><ha-icon icon="mdi:power"></ha-icon></button>
          ${MODE_ORDER.map((value) => MODES.find(([mode]) => mode === value)).map(([value, label, icon]) => `<button class="mode-button${state?.state === value ? " active" : ""}" data-mode="${value}" title="${label}" aria-label="${label}"><ha-icon icon="${icon}"></ha-icon></button>`).join("")}
        </div>
        <label class="row"><ha-icon icon="${fanIcon}"></ha-icon><select data-select="fan" aria-label="风速">${FANS.map(([value, label]) => `<option value="${value}" ${attributes.fan_mode === value ? "selected" : ""}>${label}</option>`).join("")}</select></label>
        <label class="row"><ha-icon icon="mdi:timer-outline"></ha-icon><select data-select="timer" aria-label="定时" ${this._available(this._entities.timer) ? "" : "disabled"}>${timerOptions.map((value) => `<option value="${value}" ${timerMinutes === value ? "selected" : ""}>${value ? `${value} 分钟` : "关闭"}</option>`).join("")}</select></label>
        <div class="menu">
          ${this._menuItem("上下风向", "mdi:swap-vertical", "swing-vertical", ["vertical","both"].includes(attributes.swing_mode))}
          ${this._menuItem("左右风向", "mdi:swap-horizontal", "swing-horizontal", ["horizontal","both"].includes(attributes.swing_mode))}
          ${this._menuItem("强力模式", "mdi:weather-windy", "turbo", active("turbo"), turboEnabled || active("turbo"))}
          ${this._menuItem("睡眠模式", "mdi:sleep", "sleep", active("sleep"), sleepEnabled || active("sleep"))}
          ${this._menuItem("灯光开关", active("light") ? "mdi:lightbulb" : "mdi:lightbulb-outline", "light", active("light"), enabled("light"))}
          ${this._menuItem("辅热开关", active("aux_heat") ? "mdi:radiator" : "mdi:radiator-off", "aux_heat", active("aux_heat"), auxHeatEnabled || active("aux_heat"))}
          ${this._menuItem("经济省电", "mdi:leaf", "econo", active("econo"), econoEnabled || active("econo"))}
        </div>
      </div>
    </ha-card>`;

    this.shadowRoot.querySelectorAll("[data-action]").forEach((element) => {
      element.addEventListener("click", (event) => {
        event.stopPropagation();
        const action = element.dataset.action;
        if (action === "menu") { this._menuOpen = !this._menuOpen; this._render(); }
        else if (action === "power") this._call("climate", power ? "turn_off" : "turn_on");
        else if (action === "temp-down") this._call("climate", "set_temperature", { temperature: temperature - 1 });
        else if (action === "temp-up") this._call("climate", "set_temperature", { temperature: temperature + 1 });
        else if (action === "swing-vertical") this._call("climate", "set_swing_mode", { swing_mode: attributes.swing_mode === "both" ? "horizontal" : attributes.swing_mode === "vertical" ? "off" : attributes.swing_mode === "horizontal" ? "both" : "vertical" });
        else if (action === "swing-horizontal") this._call("climate", "set_swing_mode", { swing_mode: attributes.swing_mode === "both" ? "vertical" : attributes.swing_mode === "horizontal" ? "off" : attributes.swing_mode === "vertical" ? "both" : "horizontal" });
        else if (action === "turbo") this._toggleExtended("turbo", ["econo", "sleep"]);
        else if (action === "econo") this._toggleExtended("econo", ["turbo"]);
        else if (action === "sleep") this._toggleExtended("sleep", ["turbo"]);
        else this._toggleExtended(action);
      });
    });
    this.shadowRoot.querySelectorAll("[data-select]").forEach((element) => {
      element.addEventListener("change", (event) => {
        event.stopPropagation();
        if (element.dataset.select === "fan") {
          this._call("climate", "set_fan_mode", { fan_mode: element.value });
        } else {
          this._call("number", "set_value", { value: Number(element.value) }, this._entities.timer);
        }
      });
    });
    this.shadowRoot.querySelectorAll("[data-mode]").forEach((element) => {
      element.addEventListener("click", (event) => {
        event.stopPropagation();
        this._setMode(element.dataset.mode);
      });
    });
  }
}

if (!customElements.get("rose-climate-remote-card-editor")) {
  customElements.define("rose-climate-remote-card-editor", RoseClimateRemoteCardEditor);
}

if (!customElements.get("rose-climate-remote-card")) {
  customElements.define("rose-climate-remote-card", RoseClimateRemoteCard);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "rose-climate-remote-card",
    name: "Rose Climate Remote",
    description: "Rose air-conditioner remote control",
    preview: true,
  });
}
