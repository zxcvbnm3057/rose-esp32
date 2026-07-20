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
const SWINGS = [
  ["off", "关闭"], ["vertical", "上下"], ["horizontal", "左右"], ["both", "全向"],
];

class RoseClimateRemoteCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._registry = null;
    this._entities = {};
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

  getCardSize() { return 10; }

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

  _button(label, icon, action, active = false, enabled = true, wide = false) {
    return `<button class="key${active ? " active" : ""}${wide ? " wide" : ""}" ${enabled ? "" : "disabled"} data-action="${action}">
      ${icon ? `<ha-icon icon="${icon}"></ha-icon>` : ""}<span>${label}</span>
    </button>`;
  }

  _render() {
    if (!this.shadowRoot || !this._config) return;
    const state = this._state();
    const attributes = state?.attributes || {};
    const power = state && state.state !== "off" && state.state !== "unavailable";
    const temperature = Math.round(attributes.temperature ?? 26);
    const mode = MODES.find(([value]) => value === state?.state) || [state?.state || "off", power ? "运行" : "关闭", "mdi:power"];
    const fan = FANS.find(([value]) => value === attributes.fan_mode)?.[1] || attributes.fan_mode || "--";
    const swing = SWINGS.find(([value]) => value === attributes.swing_mode)?.[1] || attributes.swing_mode || "--";
    const ext = (key) => this._state(this._entities[key]);
    const active = (key) => ext(key)?.state === "on";
    const enabled = (key) => this._available(this._entities[key]);
    const timerState = this._state(this._entities.timer);
    const timerMinutes = Math.round(Number(timerState?.state) || 0);
    const timerStep = Number(timerState?.attributes?.step) || 10;
    const timerMin = Number(timerState?.attributes?.min) || 0;
    const timerMax = Number(timerState?.attributes?.max) || 1440;

    this.shadowRoot.innerHTML = `<style>
      :host { display:block; --accent:#09b9c3; --ink:#151515; }
      ha-card { overflow:hidden; border-radius:0; background:#f4f4f6; color:var(--ink); font-family:"STKaiti","KaiTi","Noto Serif SC",serif; box-shadow:none; }
      .remote { min-height:640px; padding:18px 18px 28px; box-sizing:border-box; }
      .hero { height:280px; display:flex; flex-direction:column; align-items:center; justify-content:center; }
      .temperature { position:relative; font-family:"Bodoni 72","Times New Roman",serif; font-size:112px; line-height:.95; font-weight:400; }
      .temperature small { position:absolute; left:100%; top:-16px; margin-left:8px; font-size:42px; white-space:nowrap; }
      .mode { margin-top:30px; display:flex; align-items:center; gap:13px; color:#858589; font-size:28px; }
      .mode ha-icon { --mdc-icon-size:39px; }
      .status { display:flex; flex-wrap:wrap; justify-content:center; gap:8px 16px; color:#858589; font-family:Arial,sans-serif; font-size:13px; margin-top:15px; }
      .status span { display:flex; align-items:center; gap:4px; }
      .status ha-icon { --mdc-icon-size:16px; }
      .panel { display:grid; grid-template-columns:repeat(6,minmax(0,1fr)); gap:12px; min-width:0; }
      .key { grid-column:span 2; min-width:0; height:108px; border:0; border-radius:24px; background:#fff; color:#171717; display:flex; align-items:center; justify-content:flex-start; gap:12px; padding:0 25px; font:28px/1.2 "STKaiti","KaiTi","Noto Serif SC",serif; cursor:pointer; overflow:hidden; box-shadow:0 1px 0 rgba(0,0,0,.02); transition:transform .12s,background .12s,color .12s; }
      .key:hover { transform:translateY(-1px); } .key:active { transform:scale(.98); }
      .key ha-icon { --mdc-icon-size:31px; }
      .key.wide { grid-column:span 3; }
      .key.active { color:#fff; background:var(--accent); }
      .key:disabled { color:#aaa; background:#f8f8f9; cursor:not-allowed; transform:none; }
      .power { justify-content:space-between; }
      .power ha-icon { --mdc-icon-size:46px; color:var(--accent); }
      .temp-control { justify-content:space-between; font-family:"Bodoni 72","Times New Roman",serif; }
      .temp-control .round { width:54px; height:54px; border:0; border-radius:12px; color:var(--accent); background:#ddf7f9; font-size:39px; line-height:1; cursor:pointer; }
      .temp-control strong { font-size:34px; font-weight:500; }
      .timer-control { grid-column:span 6; height:84px; justify-content:space-between; padding:0 18px; }
      .timer-control .timer-label { display:flex; align-items:center; gap:10px; min-width:90px; }
      .timer-control .timer-value { border:0; background:transparent; color:inherit; font:24px/1.2 "STKaiti","KaiTi","Noto Serif SC",serif; cursor:pointer; }
      .timer-control .round { width:48px; height:48px; border:0; border-radius:12px; color:var(--accent); background:#ddf7f9; font-size:32px; line-height:1; cursor:pointer; }
      .timer-control .round:disabled { color:#aaa; background:#eee; cursor:not-allowed; }
      .meta { font-family:Arial,sans-serif; font-size:12px; opacity:.55; }
      @media (max-width:600px) {
        .remote { padding:14px 12px 22px; min-height:100vh; }
        .hero { height:250px; }
        .temperature { font-size:96px; }
        .temperature small { font-size:35px; }
        .mode { font-size:23px; }
        .status { gap:6px 10px; font-size:12px; }
        .panel { gap:9px; }
        .key { height:94px; border-radius:20px; padding:0 14px; gap:7px; font-size:22px; }
        .temp-control { padding:0 8px; }
        .temp-control .round { width:42px; height:48px; font-size:32px; }
        .temp-control strong { font-size:27px; }
        .timer-control { height:76px; padding:0 12px; }
        .timer-control .timer-label { min-width:72px; gap:6px; }
        .timer-control .timer-value { font-size:20px; }
        .timer-control .round { width:42px; height:44px; }
      }
    </style>
    <ha-card>
      <div class="remote">
        <div class="hero">
          <div class="temperature">${temperature}<small>°C</small></div>
          <div class="mode"><ha-icon icon="${mode[2]}"></ha-icon><span>${mode[1]}</span></div>
          <div class="status">
            <span><ha-icon icon="mdi:fan"></ha-icon>${fan}</span>
            <span><ha-icon icon="mdi:swap-vertical"></ha-icon>${swing === "上下" || swing === "全向" ? "上下扫风" : "上下固定"}</span>
            <span><ha-icon icon="mdi:swap-horizontal"></ha-icon>${swing === "左右" || swing === "全向" ? "左右扫风" : "左右固定"}</span>
          </div>
        </div>
        <div class="panel">
          <button class="key wide power" data-action="power"><span>空调开关<br><small class="meta">${power ? "已开启" : "已关闭"}</small></span><ha-icon icon="mdi:power"></ha-icon></button>
          <div class="key wide temp-control"><button class="round" data-action="temp-down">−</button><strong>${temperature}°C</strong><button class="round" data-action="temp-up">+</button></div>
          ${this._button("模式", "mdi:air-conditioner", "mode", false, true, true)}
          ${this._button("风速", "mdi:fan", "fan", false, true, true)}
          ${this._button("扫风", "mdi:swap-vertical", "swing-vertical", ["vertical","both"].includes(attributes.swing_mode))}
          ${this._button("左右风向", "mdi:swap-horizontal", "swing-horizontal", ["horizontal","both"].includes(attributes.swing_mode))}
          ${this._button("强力", "mdi:rocket-launch", "turbo", active("turbo"), enabled("turbo"))}
          ${this._button("健康", "mdi:air-filter", "health", active("health"), enabled("health"))}
          ${this._button("灯光", "mdi:lightbulb", "light", active("light"), enabled("light"))}
          ${this._button("辅热", "mdi:radiator", "aux_heat", active("aux_heat"), enabled("aux_heat"))}
          ${this._button("睡眠", "mdi:sleep", "sleep", active("sleep"), enabled("sleep"), true)}
          ${this._button("经济省电", "mdi:leaf", "econo", active("econo"), enabled("econo"), true)}
          <div class="key timer-control">
            <span class="timer-label"><ha-icon icon="mdi:timer-outline"></ha-icon><span>定时</span></span>
            <button class="round" data-action="timer-down" ${this._available(this._entities.timer) && timerMinutes > timerMin ? "" : "disabled"}>−</button>
            <button class="timer-value" data-action="timer-details" ${this._available(this._entities.timer) ? "" : "disabled"}>${timerMinutes ? `${timerMinutes} 分钟` : "关闭"}</button>
            <button class="round" data-action="timer-up" ${this._available(this._entities.timer) && timerMinutes < timerMax ? "" : "disabled"}>+</button>
          </div>
        </div>
      </div>
    </ha-card>`;

    this.shadowRoot.querySelectorAll("[data-action]").forEach((element) => {
      element.addEventListener("click", (event) => {
        event.stopPropagation();
        const action = element.dataset.action;
        if (action === "power") this._call("climate", power ? "turn_off" : "turn_on");
        else if (action === "temp-down") this._call("climate", "set_temperature", { temperature: temperature - 1 });
        else if (action === "temp-up") this._call("climate", "set_temperature", { temperature: temperature + 1 });
        else if (action === "mode") this._cycle("hvac_mode", MODES.map(([value]) => value), "set_hvac_mode", "hvac_mode");
        else if (action === "fan") this._cycle("fan_mode", FANS.map(([value]) => value), "set_fan_mode", "fan_mode");
        else if (action === "swing-vertical") this._call("climate", "set_swing_mode", { swing_mode: attributes.swing_mode === "both" ? "horizontal" : attributes.swing_mode === "vertical" ? "off" : attributes.swing_mode === "horizontal" ? "both" : "vertical" });
        else if (action === "swing-horizontal") this._call("climate", "set_swing_mode", { swing_mode: attributes.swing_mode === "both" ? "vertical" : attributes.swing_mode === "horizontal" ? "off" : attributes.swing_mode === "vertical" ? "both" : "horizontal" });
        else if (action === "timer-down") this._call("number", "set_value", { value: Math.max(timerMin, timerMinutes - timerStep) }, this._entities.timer);
        else if (action === "timer-up") this._call("number", "set_value", { value: Math.min(timerMax, timerMinutes + timerStep) }, this._entities.timer);
        else if (action === "timer-details") this.dispatchEvent(new CustomEvent("hass-more-info", {
          bubbles: true,
          composed: true,
          detail: { entityId: this._entities.timer },
        }));
        else this._toggle(this._entities[action]);
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
