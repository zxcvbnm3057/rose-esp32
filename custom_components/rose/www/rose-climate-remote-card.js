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

  static getStubConfig(hass) {
    return {
      entity: Object.keys(hass.states).find((id) => id.startsWith("climate.")),
      name: "TCL空调遥控器",
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

  _cycle(attribute, values, service, field) {
    const state = this._state();
    if (!state) return;
    const current = attribute === "hvac_mode" ? state.state : state.attributes[attribute];
    const index = Math.max(0, values.indexOf(current));
    this._call("climate", service, { [field]: values[(index + 1) % values.length] });
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

    this.shadowRoot.innerHTML = `<style>
      :host { display:block; --accent:var(--primary-color,#03a9f4); --ink:var(--primary-text-color,#202124); }
      ha-card { position:relative; overflow:visible; color:var(--ink); font-family:var(--paper-font-body1_-_font-family,"Microsoft YaHei",sans-serif); }
      .remote { padding:20px 18px 18px; box-sizing:border-box; }
      .header { height:34px; display:flex; align-items:center; justify-content:center; position:relative; font-size:22px; font-weight:500; }
      .more { position:absolute; right:-4px; top:-8px; width:44px; height:44px; border:0; background:transparent; color:var(--secondary-text-color,#666); cursor:pointer; border-radius:50%; }
      .more ha-icon { --mdc-icon-size:28px; }
      .dial-wrap { height:390px; display:grid; place-items:center; position:relative; }
      .dial { width:min(370px,78vw); height:min(370px,78vw); border-radius:50%; background:conic-gradient(from 225deg,#e8e8e8 0deg 270deg,transparent 270deg); position:relative; display:grid; place-items:center; }
      .dial::after { content:""; position:absolute; inset:28px; border-radius:50%; background:var(--ha-card-background,var(--card-background-color,#fff)); }
      .dial-center { position:relative; z-index:1; text-align:center; }
      .dial-state { font-size:52px; line-height:1.1; }
      .dial-temp { margin-top:18px; display:grid; justify-items:center; gap:7px; font-size:21px; font-weight:600; }
      .dial-temp span { display:flex; align-items:center; white-space:nowrap; }
      .under-dial { margin:-34px 12px 20px; position:relative; z-index:2; }
      .swing-status { display:grid; grid-template-columns:1fr 1fr; gap:34px; color:var(--secondary-text-color,#777); text-align:center; }
      .swing-status span { display:flex; align-items:center; justify-content:center; gap:7px; min-width:0; font-size:15px; }
      .swing-status ha-icon { --mdc-icon-size:23px; }
      .temperature-adjust { display:grid; grid-template-columns:1fr 1fr; gap:34px; align-items:center; margin-top:14px; }
      .temperature-adjust button { justify-self:center; width:72px; height:58px; border:0; background:transparent; color:var(--ink); display:grid; place-items:center; cursor:pointer; }
      .temperature-adjust button ha-icon { --mdc-icon-size:44px; }
      .temperature-adjust button:disabled { opacity:.3; cursor:not-allowed; }
      .mode-strip { height:64px; display:grid; grid-template-columns:repeat(5,1fr); border-radius:18px; overflow:hidden; background:var(--secondary-background-color,#f2f2f2); }
      .mode-button { border:0; background:transparent; color:var(--ink); cursor:pointer; display:grid; place-items:center; }
      .mode-button ha-icon { --mdc-icon-size:28px; }
      .mode-button.active { color:#fff; background:var(--accent); border-radius:18px; }
      .row { width:100%; height:64px; margin-top:18px; padding:0 18px; border:0; border-radius:18px; background:var(--secondary-background-color,#f2f2f2); color:var(--ink); display:flex; align-items:center; gap:14px; font-size:20px; cursor:pointer; }
      .row ha-icon { --mdc-icon-size:28px; }
      .row .value { flex:1; text-align:left; }
      .row .chevron { --mdc-icon-size:22px; }
      .menu { position:absolute; z-index:10; top:58px; right:12px; width:min(310px,calc(100% - 24px)); padding:8px; border-radius:12px; background:var(--ha-card-background,var(--card-background-color,#fff)); box-shadow:0 6px 24px rgba(0,0,0,.24); display:${this._menuOpen ? "grid" : "none"}; }
      .menu-item { height:50px; border:0; border-radius:8px; padding:0 10px; background:transparent; color:var(--ink); display:grid; grid-template-columns:32px 1fr 38px; align-items:center; gap:8px; text-align:left; font-size:16px; cursor:pointer; }
      .menu-item:hover { background:var(--secondary-background-color,#f2f2f2); }
      .menu-item ha-icon { --mdc-icon-size:23px; }
      .menu-item .toggle { width:34px; height:20px; border-radius:10px; background:#bbb; position:relative; }
      .menu-item .toggle::after { content:""; position:absolute; width:16px; height:16px; left:2px; top:2px; border-radius:50%; background:#fff; transition:left .15s; }
      .menu-item.active .toggle { background:var(--accent); }
      .menu-item.active .toggle::after { left:16px; }
      .menu-item:disabled { opacity:.4; cursor:not-allowed; }
      @media (max-width:600px) {
        .remote { padding:16px 12px; }
        .dial-wrap { height:350px; }
        .dial { width:min(330px,88vw); height:min(330px,88vw); }
        .dial-state { font-size:46px; }
        .under-dial { margin:-34px 2px 16px; }
        .swing-status { gap:18px; }
        .temperature-adjust { gap:18px; }
      }
    </style>
    <ha-card>
      <div class="remote">
        <div class="header">${this._config.name || attributes.friendly_name || "空调"}<button class="more" data-action="menu" title="扩展控制"><ha-icon icon="mdi:dots-vertical"></ha-icon></button></div>
        <div class="dial-wrap">
          <div class="dial">
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
        <button class="row" data-action="fan"><ha-icon icon="${fanIcon}"></ha-icon><span class="value">${fan}</span><ha-icon class="chevron" icon="mdi:chevron-down"></ha-icon></button>
        <button class="row" data-action="timer-details" ${this._available(this._entities.timer) ? "" : "disabled"}><ha-icon icon="mdi:timer-outline"></ha-icon><span class="value">${timerMinutes ? `${timerMinutes} 分钟` : "关闭"}</span><ha-icon class="chevron" icon="mdi:chevron-down"></ha-icon></button>
        <div class="menu">
          ${this._menuItem("上下风向", "mdi:swap-vertical", "swing-vertical", ["vertical","both"].includes(attributes.swing_mode))}
          ${this._menuItem("左右风向", "mdi:swap-horizontal", "swing-horizontal", ["horizontal","both"].includes(attributes.swing_mode))}
          ${this._menuItem("强力模式", "mdi:weather-windy", "turbo", active("turbo"), enabled("turbo"))}
          ${this._menuItem("睡眠模式", "mdi:sleep", "sleep", active("sleep"), enabled("sleep"))}
          ${this._menuItem("灯光开关", active("light") ? "mdi:lightbulb" : "mdi:lightbulb-outline", "light", active("light"), enabled("light"))}
          ${this._menuItem("辅热开关", active("aux_heat") ? "mdi:radiator" : "mdi:radiator-off", "aux_heat", active("aux_heat"), enabled("aux_heat"))}
          ${this._menuItem("经济省电", "mdi:leaf", "econo", active("econo"), enabled("econo"))}
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
        else if (action === "fan") this._cycle("fan_mode", FANS.map(([value]) => value), "set_fan_mode", "fan_mode");
        else if (action === "swing-vertical") this._call("climate", "set_swing_mode", { swing_mode: attributes.swing_mode === "both" ? "horizontal" : attributes.swing_mode === "vertical" ? "off" : attributes.swing_mode === "horizontal" ? "both" : "vertical" });
        else if (action === "swing-horizontal") this._call("climate", "set_swing_mode", { swing_mode: attributes.swing_mode === "both" ? "vertical" : attributes.swing_mode === "horizontal" ? "off" : attributes.swing_mode === "vertical" ? "both" : "horizontal" });
        else if (action === "timer-details") this.dispatchEvent(new CustomEvent("hass-more-info", {
          bubbles: true,
          composed: true,
          detail: { entityId: this._entities.timer },
        }));
        else { this._toggle(this._entities[action]); this._menuOpen = false; }
      });
    });
    this.shadowRoot.querySelectorAll("[data-mode]").forEach((element) => {
      element.addEventListener("click", (event) => {
        event.stopPropagation();
        this._call("climate", "set_hvac_mode", { hvac_mode: element.dataset.mode });
      });
    });
  }
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
