import { createClient as createSupabaseClient } from "https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2/+esm";

const SVG_NS = "http://www.w3.org/2000/svg";
const BASE_VIEWBOX = { x: 0, y: 0, width: 1000, height: 720 };
const WA_BOUNDS = { west: 112.0, south: -36.0, east: 129.2, north: -13.0 };
const DEFAULT_TARGET_RADIUS_KM = 2;
const COORDINATE_INPUT_DECIMALS = 4;
const DEFAULT_MANUAL_REPEATER_NAME = "Manual repeater site";
const MIN_MAP_ZOOM = -6;
const MAX_MAP_ZOOM = 12;
const MAP_LONG_PRESS_MS = 650;
const MAP_LONG_PRESS_CANCEL_PX = 10;
const MAP_EXPORT_SIZE = "1400,1008";
const MAP_ASPECT_OVERVIEW = "xMidYMid meet";
const MAP_ASPECT_FILL = "xMidYMid slice";
const MGRS_BANDS = "CDEFGHJKLMNPQRSTUVWX";
const MGRS_COLUMN_SETS = ["ABCDEFGH", "JKLMNPQR", "STUVWXYZ"];
const MGRS_ROWS = "ABCDEFGHJKLMNPQRSTUV";
const WGS84_A = 6378137;
const WGS84_F = 1 / 298.257223563;
const UTM_K0 = 0.9996;
const SLIP_SERVICES = {
  aerial: {
    url: "https://services.slip.wa.gov.au/public/rest/services/SLIP_Public_Services/Locate/MapServer/export",
    layers: "show:4",
    format: "png32",
    transparent: true,
  },
  transport: {
    url: "https://services.slip.wa.gov.au/public/rest/services/SLIP_Public_Services/Transport/MapServer/export",
    layers: "show:17,18",
    format: "png32",
    transparent: true,
  },
};
let latestResult = null;
let latestManifest = null;
let selectedCandidateId = null;
let currentSession = null;
const expandedIncidentIds = new Set();
let mapZoomLevel = 0;
let mapViewCenter = defaultMapCenter();
let mapDrag = null;
const activeMapPointers = new Map();
let mapPinch = null;
let mapLongPress = null;
let imageryRefreshTimer = null;
let imageryRefreshToken = 0;
let suppressCandidateClickUntil = 0;
let candidateClickTimer = null;
let candidateLastClick = { candidateId: null, at: 0 };
let expandedCandidateIds = new Set();
let manualRepeaterSite = null;
let editingSavedManifest = null;
let contextMenuLocation = null;
let drawingCoverageArea = false;
let drawToolsExpanded = false;
let vertexDrag = null;
let draftCoveragePolygon = [];
let activeCoveragePolygonLl = [];
let measureToolsExpanded = false;
let measureMode = null;
let measurePoints = [];
const mobileMapQuery = window.matchMedia("(max-width: 760px)");
let mapToolsExpanded = !mobileMapQuery.matches;
let coverageOpacity = 0.48;
const mapLayerState = {
  aerial: true,
  terrain: false,
  contours: false,
  roads: true,
  "minor-roads": true,
  trails: true,
  "source-roads": false,
  coverage: true,
  target: true,
  candidates: true,
};
let mobileControlPanelOpen = false;
let mobileResultsPanelOpen = false;

const form = document.querySelector("#analysis-form");
const saveForm = document.querySelector("#save-form");
const authEmailForm = document.querySelector("#auth-email-form");
const authMessage = document.querySelector("#auth-message");
const authGoogleButton = document.querySelector("#auth-google");
const authMagicLinkButton = document.querySelector("#auth-magic-link");
const signOutButton = document.querySelector("#sign-out");
const sessionEmail = document.querySelector("#session-email");
const profileSelect = document.querySelector("#profile");
const frequencyInput = document.querySelector("#frequency");
const coordinateFormatSelect = document.querySelector("#coordinate-format");
const latLonFields = document.querySelector("#latlon-fields");
const mgrsField = document.querySelector("#mgrs-field");
const targetLatInput = form.elements.namedItem("target_lat");
const targetLonInput = form.elements.namedItem("target_lon");
const targetMgrsInput = form.elements.namedItem("target_mgrs");
const userRadioSelect = document.querySelector("select[name='user_radio']");
const serviceProfileSelect = document.querySelector("select[name='service_profile']");
const saveButton = document.querySelector("#save-result");
const saveStatus = document.querySelector("#save-status");
const savePanel = document.querySelector("#save-panel");
const openSavePanelButton = document.querySelector("#open-save-panel");
const closeSavePanelButton = document.querySelector("#close-save-panel");
const controlPanel = document.querySelector("#control-panel");
const resultsPanel = document.querySelector("#results-panel");
const controlPanelToggle = document.querySelector("#control-panel-toggle");
const resultsPanelToggle = document.querySelector("#results-panel-toggle");
const savedList = document.querySelector("#saved-list");
const busyOverlay = document.querySelector("#busy-overlay");
const busyMessage = document.querySelector("#busy-message");
const foldersToggle = document.querySelector("#folders-toggle");
const searchResultsToggle = document.querySelector("#search-results-toggle");
const layersToggle = document.querySelector("#layers-toggle");
const layerOptions = document.querySelector("#layer-options");
const mapSection = document.querySelector(".map-section");
const mapToolsToggle = document.querySelector("#map-tools-toggle");
const mapSvg = document.querySelector("#map");
const layerInputs = Array.from(document.querySelectorAll("[data-map-layer]"));
const coverageOpacityInput = document.querySelector("#coverage-opacity");
const coverageOpacityValue = document.querySelector("#coverage-opacity-value");
const loadMapButton = document.querySelector("#load-map");
const zoomInButton = document.querySelector("#zoom-in");
const zoomOutButton = document.querySelector("#zoom-out");
const zoomResetButton = document.querySelector("#zoom-reset");
const drawControl = document.querySelector("#draw-control");
const drawToolsToggle = document.querySelector("#draw-tools-toggle");
const drawToolsPanel = document.querySelector("#draw-tools");
const drawAreaButton = document.querySelector("#draw-area");
const finishAreaButton = document.querySelector("#finish-area");
const clearAreaButton = document.querySelector("#clear-area");
const drawStatus = document.querySelector("#draw-status");
const measureControl = document.querySelector("#measure-control");
const measureToolsToggle = document.querySelector("#measure-tools-toggle");
const measureToolsPanel = document.querySelector("#measure-tools");
const measureLineButton = document.querySelector("#measure-line");
const measureTrackButton = document.querySelector("#measure-track");
const finishMeasureButton = document.querySelector("#finish-measure");
const clearMeasureButton = document.querySelector("#clear-measure");
const measureStatus = document.querySelector("#measure-status");
const manualSiteStatus = document.querySelector("#manual-site-status");
const manualSiteStatusText = manualSiteStatus?.querySelector("span");
const clearManualSiteButton = document.querySelector("#clear-manual-site");
const renameManualSiteButton = document.querySelector("#rename-manual-site");
const mapContextMenu = document.querySelector("#map-context-menu");
const contextSetTargetButton = document.querySelector("#context-set-target");
const contextDropRepeaterButton = document.querySelector("#context-drop-repeater");
const contextClearRepeaterButton = document.querySelector("#context-clear-repeater");
const contextRenameRepeaterButton = document.querySelector("#context-rename-repeater");
const contextEditPolygonButton = document.querySelector("#context-edit-polygon");
const contextDeleteVertexButton = document.querySelector("#context-delete-vertex");
const supabaseClient = createAuthClient();

profileSelect.addEventListener("change", () => {
  frequencyInput.value = profileSelect.value === "VHF" ? "150" : "460";
});

userRadioSelect.addEventListener("change", () => {
  serviceProfileSelect.value = userRadioSelect.value === "portable" ? "operational_portable" : "vehicle_mobile";
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const hasDrawnTarget = targetPolygonForPayload().length >= 3;
  if (!syncCoordinateInputs(true, hasDrawnTarget)) return;
  if (mobileMapQuery.matches) {
    setMobilePanelOpen("left", false);
    setMobilePanelOpen("right", false);
  }
  await runAnalysis();
});

authGoogleButton.addEventListener("click", () => {
  signInWithOAuth("google");
});

authEmailForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  await signInWithPassword();
});

authMagicLinkButton.addEventListener("click", () => {
  sendMagicLink();
});

signOutButton.addEventListener("click", () => {
  signOut();
});

saveForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  await saveCurrentResult();
});

openSavePanelButton.addEventListener("click", () => {
  openSavePanelForCurrentResult();
});

closeSavePanelButton.addEventListener("click", () => {
  setSavePanelVisible(false);
  editingSavedManifest = null;
  updateSavePanelMode();
});

document.querySelector("#refresh-saved").addEventListener("click", () => {
  refreshSavedResults();
});

foldersToggle.addEventListener("click", () => {
  togglePanelSection(foldersToggle);
});

searchResultsToggle.addEventListener("click", () => {
  togglePanelSection(searchResultsToggle);
});

layersToggle.addEventListener("click", () => {
  toggleLayersPanel();
});

for (const input of layerInputs) {
  input.addEventListener("change", () => {
    mapLayerState[input.dataset.mapLayer] = input.checked;
    applyMapLayerVisibility();
  });
}

coverageOpacityInput?.addEventListener("input", () => {
  coverageOpacity = Number(coverageOpacityInput.value) / 100;
  updateCoverageOpacity();
});

coordinateFormatSelect.addEventListener("change", () => {
  updateCoordinateFields(true);
});

targetMgrsInput?.addEventListener("change", () => {
  syncCoordinateInputs(false, true);
});

loadMapButton.addEventListener("click", () => {
  loadTargetMap();
});

for (const name of ["target_lat", "target_lon", "search_radius_km"]) {
  const control = form.elements.namedItem(name);
  control?.addEventListener("change", () => {
    if (coordinateFormatSelect.value === "latlon" && (name === "target_lat" || name === "target_lon")) {
      normaliseCoordinateInput(control);
      updateMgrsFromLatLon();
    }
    if (latestResult) return;
    mapZoomLevel = 0;
    mapViewCenter = defaultMapCenter();
    renderEmptyMap();
  });
}

zoomInButton.addEventListener("click", () => {
  zoomMap(1);
});

zoomOutButton.addEventListener("click", () => {
  zoomMap(-1);
});

zoomResetButton.addEventListener("click", () => {
  mapZoomLevel = 0;
  mapViewCenter = defaultMapCenter();
  applyMapViewBox();
});

mapToolsToggle?.addEventListener("click", () => {
  setMapToolsExpanded(!mapToolsExpanded);
});

mobileMapQuery.addEventListener("change", () => {
  setMapToolsExpanded(!mobileMapQuery.matches);
  if (!mobileMapQuery.matches) {
    setMobilePanelOpen("left", false);
    setMobilePanelOpen("right", false);
  }
  updateMapAspectMode(latestResult ?? previewMapResult());
});

controlPanelToggle?.addEventListener("click", () => {
  setMobilePanelOpen("left", !mobileControlPanelOpen);
});

resultsPanelToggle?.addEventListener("click", () => {
  setMobilePanelOpen("right", !mobileResultsPanelOpen);
});

mapSvg.addEventListener("pointerdown", startMapPan);
mapSvg.addEventListener("pointermove", updateMapPan);
mapSvg.addEventListener("pointerup", finishMapPan);
mapSvg.addEventListener("pointercancel", finishMapPan);
mapSvg.addEventListener("lostpointercapture", finishMapPan);
mapSvg.addEventListener("wheel", handleMapWheel, { passive: false });
mapSvg.addEventListener("click", handleMapClick);
mapSvg.addEventListener("contextmenu", handleMapContextMenu);
mapSvg.addEventListener("dblclick", handleMapDoubleClick);

document.addEventListener("click", (event) => {
  if (!mapContextMenu?.hidden && !event.target.closest?.("#map-context-menu")) {
    hideMapContextMenu();
  }
});
window.addEventListener("resize", hideMapContextMenu);

contextSetTargetButton?.addEventListener("click", () => {
  if (!contextMenuLocation) return;
  setTargetCoordinates(contextMenuLocation.lat, contextMenuLocation.lon);
  hideMapContextMenu();
});

contextDropRepeaterButton?.addEventListener("click", () => {
  if (!contextMenuLocation) return;
  setManualRepeaterSite(contextMenuLocation.lat, contextMenuLocation.lon);
  hideMapContextMenu();
});

contextClearRepeaterButton?.addEventListener("click", () => {
  clearManualRepeaterSite();
  hideMapContextMenu();
});

contextRenameRepeaterButton?.addEventListener("click", () => {
  renameManualRepeaterSite();
  hideMapContextMenu();
});

contextEditPolygonButton?.addEventListener("click", () => {
  beginCoveragePolygonEdit();
  hideMapContextMenu();
});

contextDeleteVertexButton?.addEventListener("click", () => {
  deleteContextVertex();
  hideMapContextMenu();
});

clearManualSiteButton?.addEventListener("click", clearManualRepeaterSite);
renameManualSiteButton?.addEventListener("click", renameManualRepeaterSite);

drawToolsToggle.addEventListener("click", () => {
  setDrawToolsExpanded(!drawToolsExpanded);
});

drawAreaButton.addEventListener("click", () => {
  drawingCoverageArea = !drawingCoverageArea;
  if (drawingCoverageArea) {
    setMeasureMode(null);
  }
  updateDrawingControls();
});

finishAreaButton.addEventListener("click", () => {
  if (draftCoveragePolygon.length >= 3) {
    drawingCoverageArea = false;
    updateDrawingControls();
  }
});

clearAreaButton.addEventListener("click", () => {
  draftCoveragePolygon = [];
  activeCoveragePolygonLl = [];
  drawingCoverageArea = false;
  updateDrawingControls();
  renderCurrentMap();
});

measureToolsToggle.addEventListener("click", () => {
  setMeasureToolsExpanded(!measureToolsExpanded);
});

measureLineButton.addEventListener("click", () => {
  setMeasureMode(measureMode === "line" ? null : "line");
});

measureTrackButton.addEventListener("click", () => {
  setMeasureMode(measureMode === "track" ? null : "track");
});

finishMeasureButton.addEventListener("click", () => {
  setMeasureMode(null);
});

clearMeasureButton.addEventListener("click", () => {
  measureMode = null;
  measurePoints = [];
  updateMeasureControls();
  renderCurrentMap();
});

document.querySelector("#export-json").addEventListener("click", () => {
  if (!latestResult) return;
  const blob = new Blob([JSON.stringify(latestResult, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "rf-repeater-mvp-analysis.json";
  link.click();
  URL.revokeObjectURL(url);
});

function savePayload() {
  const data = new FormData(saveForm);
  return {
    incident_number: String(data.get("incident_number") || "").trim(),
    name: String(data.get("name") || "").trim(),
    location: String(data.get("location") || "").trim(),
    description: String(data.get("description") || "").trim(),
    result: latestResult,
  };
}

function savedMetadataPayload() {
  const data = new FormData(saveForm);
  const payload = {
    incident_number: String(data.get("incident_number") || "").trim(),
    name: String(data.get("name") || "").trim(),
    location: String(data.get("location") || "").trim(),
    description: String(data.get("description") || "").trim(),
  };
  if (latestResult && editingSavedManifest?.analysis_id === latestManifest?.analysis_id) {
    payload.result = latestResult;
  }
  return payload;
}

function formPayload() {
  const data = new FormData(form);
  const targetPolygon = targetPolygonForPayload();
  const targetCoords = targetCoordinatesFromData(data);
  const targetCenter = targetCoords ?? polygonCentroidLatLon(targetPolygon);
  if (!targetCenter) {
    throw new Error("Enter target coordinates or draw the required coverage area before running analysis.");
  }
  const payload = {
    profile: data.get("profile"),
    frequency_mhz: Number(data.get("frequency_mhz")),
    target_lat: targetCenter.lat,
    target_lon: targetCenter.lon,
    target_radius_km: DEFAULT_TARGET_RADIUS_KM,
    target_area_sq_km: targetAreaSqKm(targetPolygon, DEFAULT_TARGET_RADIUS_KM),
    search_radius_km: Number(data.get("search_radius_km")),
    repeater_power_w: Number(data.get("repeater_power_w")),
    tx_height_m: Number(data.get("tx_height_m")),
    antenna_gain_dbi: Number(data.get("antenna_gain_dbi")),
    deployment_profile: data.get("deployment_profile"),
    user_radio: data.get("user_radio"),
    service_profile: data.get("service_profile"),
    noise_environment: data.get("noise_environment"),
    site_preference: data.get("site_preference"),
    coordinate_format: data.get("coordinate_format"),
    include_uplink: data.get("include_uplink") === "on",
  };
  if (targetPolygon.length >= 3) {
    payload.target_polygon_ll = targetPolygon;
  }
  if (manualRepeaterSite) {
    payload.manual_repeater_site = {
      lat: manualRepeaterSite.lat,
      lon: manualRepeaterSite.lon,
      name: manualRepeaterSite.name || DEFAULT_MANUAL_REPEATER_NAME,
    };
  }
  return payload;
}

function formValues() {
  const data = new FormData(form);
  const targetCoords = targetCoordinatesFromData(data, { allowInvalid: true });
  return {
    profile: data.get("profile"),
    frequency_mhz: Number(data.get("frequency_mhz")),
    target_lat: targetCoords?.lat ?? null,
    target_lon: targetCoords?.lon ?? null,
    target_radius_km: DEFAULT_TARGET_RADIUS_KM,
    search_radius_km: Number(data.get("search_radius_km")),
    repeater_power_w: Number(data.get("repeater_power_w")),
    tx_height_m: Number(data.get("tx_height_m")),
    antenna_gain_dbi: Number(data.get("antenna_gain_dbi")),
    deployment_profile: data.get("deployment_profile"),
    user_radio: data.get("user_radio"),
    service_profile: data.get("service_profile"),
    noise_environment: data.get("noise_environment"),
    site_preference: data.get("site_preference"),
    coordinate_format: data.get("coordinate_format"),
    include_uplink: data.get("include_uplink") === "on",
  };
}

function targetCoordinatesFromData(data, options = {}) {
  const rawLat = String(data.get("target_lat") ?? "").trim();
  const rawLon = String(data.get("target_lon") ?? "").trim();
  if (!rawLat && !rawLon) return null;
  const lat = Number(rawLat);
  const lon = Number(rawLon);
  const valid = Number.isFinite(lat)
    && Number.isFinite(lon)
    && lat >= WA_BOUNDS.south
    && lat <= WA_BOUNDS.north
    && lon >= WA_BOUNDS.west
    && lon <= WA_BOUNDS.east;
  if (!valid) {
    if (options.allowInvalid) return null;
    throw new Error("Enter target latitude/longitude within Western Australia, or draw a required coverage area.");
  }
  return {
    lat: truncateCoordinate(lat),
    lon: truncateCoordinate(lon),
  };
}

function hasTargetCoordinates(values = formValues()) {
  return values.target_lat !== null
    && values.target_lat !== undefined
    && values.target_lon !== null
    && values.target_lon !== undefined
    && Number.isFinite(Number(values.target_lat))
    && Number.isFinite(Number(values.target_lon));
}

function apiBaseUrl() {
  const configured = window.__RF_SITE_FINDER_CONFIG__?.apiBaseUrl?.trim();
  if (configured) return configured.replace(/\/$/, "");
  if (
    window.location.hostname === "service.example.invalid"
    || window.location.hostname === "rf-repeater-site-tool.vercel.app"
    || window.location.hostname.endsWith("-anthonypococks-projects.vercel.app")
  ) {
    return "https://service.example.invalid";
  }
  if (window.location.hostname === "service.example.invalid") {
    return "https://service.example.invalid";
  }
  return "";
}

function apiUrl(path) {
  return `${apiBaseUrl()}${path}`;
}

function authConfig() {
  return window.__RF_SITE_FINDER_CONFIG__ ?? {};
}

function authMode() {
  const configured = String(authConfig().authMode || "").trim().toLowerCase();
  if (configured) return configured;
  return window.location.hostname === "service.example.invalid" ? "entra-edge" : "supabase";
}

function isEntraEdgeAuth() {
  return authMode() === "entra-edge";
}

function authEnabled() {
  if (isEntraEdgeAuth()) return true;
  const configured = authConfig().authEnabled === true;
  const localHostnames = new Set(["localhost", "127.0.0.1", "0.0.0.0"]);
  return configured && !localHostnames.has(window.location.hostname);
}

function createAuthClient() {
  const config = authConfig();
  if (!authEnabled() || isEntraEdgeAuth()) return null;
  if (!config.supabaseUrl || !config.supabasePublishableKey) return null;
  return createSupabaseClient(config.supabaseUrl, config.supabasePublishableKey, {
    auth: {
      detectSessionInUrl: true,
      persistSession: true,
      autoRefreshToken: true,
      flowType: "pkce",
    },
  });
}

function authRedirectUrl() {
  return `${window.location.origin}${window.location.pathname}`;
}

async function initialiseAuth() {
  if (isEntraEdgeAuth()) {
    // Entra/oauth2-proxy authenticates the browser session at the edge. The
    // API receives the gateway secret and forwarded email from Caddy; this
    // browser request must not carry either value or a Supabase bearer token.
    showAuthenticated(null);
    try {
      const response = await apiFetch("/api/whoami");
      if (!response.ok) {
        showEdgeAuthUnavailable("The Entra session could not be verified.");
        return true;
      }
      const payload = await response.json();
      sessionEmail.textContent = String(payload.email || "").trim() || "Entra session";
    } catch (error) {
      console.warn("Unable to load the Entra session identity.", error);
      sessionEmail.textContent = "Entra session";
    }
    return true;
  }
  if (!authEnabled()) {
    showAuthenticated(null);
    return true;
  }
  if (!supabaseClient) {
    showSignedOut("Authentication is not configured for this deployment.", true);
    return false;
  }

  supabaseClient.auth.onAuthStateChange((_event, session) => {
    if (session) {
      showAuthenticated(session);
      if (!latestResult) {
        renderEmptyMap();
        refreshSavedResults();
      }
    } else {
      showSignedOut();
    }
  });

  const { data, error } = await supabaseClient.auth.getSession();
  if (error) {
    showSignedOut(error.message, true);
    return false;
  }
  if (!data.session) {
    showSignedOut();
    return false;
  }
  showAuthenticated(data.session);
  return true;
}

function showAuthenticated(session) {
  currentSession = session;
  document.body.classList.remove("auth-loading", "auth-signed-out");
  document.body.classList.add("auth-ready");
  sessionEmail.textContent = session?.user?.email ?? "";
  setAuthMessage("");
}

function showEdgeAuthUnavailable(message) {
  currentSession = null;
  sessionEmail.textContent = "Entra session unavailable";
  setStatus("auth required", "entra-edge");
  setHeaderSummary(message);
}

function showSignedOut(message = "Sign in to continue.", isError = false) {
  currentSession = null;
  latestResult = null;
  latestManifest = null;
  editingSavedManifest = null;
  selectedCandidateId = null;
  setSavePanelVisible(false);
  activeCoveragePolygonLl = [];
  draftCoveragePolygon = [];
  manualRepeaterSite = null;
  drawingCoverageArea = false;
  document.body.classList.remove("auth-loading", "auth-ready");
  document.body.classList.add("auth-signed-out");
  setStatus("waiting", "local");
  setAuthMessage(message, isError);
}

function setAuthMessage(message, isError = false, isOk = false) {
  authMessage.textContent = message;
  authMessage.classList.toggle("error", isError);
  authMessage.classList.toggle("ok", isOk);
}

async function signInWithOAuth(provider) {
  if (!supabaseClient) return;
  authGoogleButton.disabled = true;
  setAuthMessage("Redirecting to sign in...", false, true);
  const { error } = await supabaseClient.auth.signInWithOAuth({
    provider,
    options: {
      redirectTo: authRedirectUrl(),
      queryParams: { prompt: "select_account" },
    },
  });
  if (error) {
    authGoogleButton.disabled = false;
    setAuthMessage(error.message, true);
  }
}

async function signInWithPassword() {
  if (!supabaseClient) return;
  const formData = new FormData(authEmailForm);
  const email = String(formData.get("email") || "").trim();
  const password = String(formData.get("password") || "");
  if (!email || !password) {
    setAuthMessage("Enter your email and password, or send a sign-in link.", true);
    return;
  }
  setAuthMessage("Signing in...", false, true);
  const { data, error } = await supabaseClient.auth.signInWithPassword({ email, password });
  if (error) {
    setAuthMessage(error.message, true);
    return;
  }
  showAuthenticated(data.session);
}

async function sendMagicLink() {
  if (!supabaseClient) return;
  const formData = new FormData(authEmailForm);
  const email = String(formData.get("email") || "").trim();
  if (!email) {
    setAuthMessage("Enter your email first.", true);
    return;
  }
  authMagicLinkButton.disabled = true;
  setAuthMessage("Sending sign-in link...", false, true);
  const { error } = await supabaseClient.auth.signInWithOtp({
    email,
    options: { emailRedirectTo: authRedirectUrl() },
  });
  authMagicLinkButton.disabled = false;
  if (error) {
    setAuthMessage(error.message, true);
    return;
  }
  setAuthMessage(`Check ${email} for a sign-in link.`, false, true);
}

async function signOut() {
  if (isEntraEdgeAuth()) {
    const configuredUrl = String(authConfig().signOutUrl || "").trim();
    if (!configuredUrl) {
      setHeaderSummary("Sign-out is managed by the Entra edge.");
      return;
    }
    const separator = configuredUrl.includes("?") ? "&" : "?";
    const returnPath = `${window.location.pathname}${window.location.search}`;
    window.location.assign(`${configuredUrl}${separator}rd=${encodeURIComponent(returnPath)}`);
    return;
  }
  if (supabaseClient) {
    await supabaseClient.auth.signOut();
  }
  showSignedOut("Signed out.");
}

async function authHeaders(headers = {}) {
  const nextHeaders = { ...headers };
  if (isEntraEdgeAuth()) {
    // Caddy injects the gateway credential server-side. Explicitly remove
    // bearer headers too, so a stale Supabase token cannot cross this boundary.
    delete nextHeaders.Authorization;
    delete nextHeaders.authorization;
    return nextHeaders;
  }
  if (!authEnabled()) return nextHeaders;
  const token = currentSession?.access_token ?? (await supabaseClient?.auth.getSession())?.data?.session?.access_token;
  if (!token) {
    showSignedOut("Your session has expired. Sign in again.", true);
    throw new Error("Missing Supabase session.");
  }
  nextHeaders.Authorization = `Bearer ${token}`;
  return nextHeaders;
}

async function apiFetch(path, options = {}) {
  const response = await fetch(apiUrl(path), {
    ...options,
    credentials: "include",
    headers: await authHeaders(options.headers ?? {}),
  });
  if (response.status === 401 && authEnabled()) {
    if (isEntraEdgeAuth()) {
      showEdgeAuthUnavailable("The Entra session could not be verified. Refresh or sign in at the edge.");
    } else {
      showSignedOut("Your session could not be verified. Sign in again.", true);
    }
  }
  return response;
}

function applyQueryParams() {
  const params = new URLSearchParams(window.location.search);
  const allowed = [
    "profile",
    "frequency_mhz",
    "coordinate_format",
    "target_lat",
    "target_lon",
    "target_mgrs",
    "search_radius_km",
    "repeater_power_w",
    "tx_height_m",
    "antenna_gain_dbi",
    "deployment_profile",
    "user_radio",
    "service_profile",
    "noise_environment",
    "site_preference",
  ];
  for (const name of allowed) {
    if (!params.has(name)) continue;
    const control = form.elements.namedItem(name);
    if (control) control.value = params.get(name);
  }
  const includeUplink = form.elements.namedItem("include_uplink");
  if (params.has("include_uplink")) {
    includeUplink.checked = params.get("include_uplink") !== "false";
  }
}

function waitForAnalysisPoll() {
  return new Promise((resolve) => window.setTimeout(resolve, 750));
}

async function runAnalysis() {
  let payload;
  try {
    payload = formPayload();
  } catch (error) {
    setStatus("waiting", "local");
    setFailedSummary(error);
    return;
  }
  setStatus("running", "local");
  setBusy(true, "Analysis running");
  setRunningSummary(payload);
  const runButton = form.querySelector("button[type='submit']");
  runButton.disabled = true;
  try {
    const response = await apiFetch("/api/run-analysis", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!response.ok) {
      setStatus("failed", "local");
      throw new Error(`Analysis failed: ${response.status}`);
    }
    const acceptedJob = await response.json();
    if (!acceptedJob.job_id) {
      throw new Error("Analysis did not return a job id.");
    }
    let job = acceptedJob;
    while (job.status !== "complete") {
      if (job.status === "failed") {
        throw new Error(job.error || "Analysis failed.");
      }
      setBusy(true, job.status === "running" ? "Analysis running" : "Analysis queued");
      await waitForAnalysisPoll();
      const jobResponse = await apiFetch(`/api/jobs/${encodeURIComponent(acceptedJob.job_id)}`);
      if (!jobResponse.ok) {
        throw new Error(`Analysis status failed: ${jobResponse.status}`);
      }
      job = await jobResponse.json();
    }
    latestResult = job.result;
    latestManifest = null;
    editingSavedManifest = null;
    expandedCandidateIds = new Set();
    mapZoomLevel = 0;
    mapViewCenter = defaultMapCenter();
    activeCoveragePolygonLl = normalisePolygonLl(payload.target_polygon_ll);
    if (activeCoveragePolygonLl.length < 3) {
      activeCoveragePolygonLl = resultPolygonLl(latestResult);
    }
    draftCoveragePolygon = [];
    drawingCoverageArea = false;
    setDrawToolsExpanded(false);
    selectedCandidateId = latestResult.coverage_candidate_id ?? latestResult.candidates?.[0]?.candidate_id ?? null;
    manualRepeaterSite = manualRepeaterSiteFromResult(latestResult) ?? manualRepeaterSite;
    render(latestResult);
    primeSaveForm(latestResult);
    updateResultActions();
    setStatus("complete", latestResult.mode);
  } catch (error) {
    setStatus("failed", "local");
    setFailedSummary(error);
    console.error(error);
  } finally {
    runButton.disabled = false;
    setBusy(false);
  }
}

async function saveCurrentResult() {
  if (editingSavedManifest) {
    await updateSavedResultMetadata(editingSavedManifest);
    return;
  }
  if (!latestResult) return;
  saveButton.disabled = true;
  saveStatus.textContent = "Saving...";
  try {
    const response = await apiFetch("/api/saved-results", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(savePayload()),
    });
    if (!response.ok) {
      throw new Error(`Save failed: ${response.status}`);
    }
    const payload = await response.json();
    latestManifest = payload.manifest ?? null;
    editingSavedManifest = null;
    saveStatus.textContent = latestManifest ? `Saved under ${latestManifest.relative_path}` : "Saved";
    if (latestManifest?.incident_id) {
      expandedIncidentIds.add(String(latestManifest.incident_id));
    }
    await refreshSavedResults();
  } catch (error) {
    saveStatus.textContent = "Save failed";
    console.error(error);
  } finally {
    saveButton.disabled = false;
  }
}

async function updateSavedResultMetadata(manifest) {
  saveButton.disabled = true;
  saveStatus.textContent = "Updating...";
  try {
    const path = `/api/saved-results/${encodeURIComponent(manifest.incident_id)}/${encodeURIComponent(manifest.analysis_id)}`;
    const response = await apiFetch(path, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(savedMetadataPayload()),
    });
    if (!response.ok) {
      if (response.status === 405 || response.status === 501) {
        latestManifest = await replaceSavedResultViaCreateDelete(manifest);
        editingSavedManifest = latestManifest;
        if (latestManifest?.incident_id) {
          expandedIncidentIds.add(String(latestManifest.incident_id));
        }
        saveStatus.textContent = latestManifest ? `Updated ${latestManifest.relative_path}` : "Updated";
        await refreshSavedResults();
        updateSavePanelMode();
        return;
      }
      throw new Error(`Update failed: ${response.status}`);
    }
    const payload = await response.json();
    latestManifest = payload.manifest ?? latestManifest;
    editingSavedManifest = latestManifest;
    if (latestManifest?.incident_id) {
      expandedIncidentIds.add(String(latestManifest.incident_id));
    }
    saveStatus.textContent = latestManifest ? `Updated ${latestManifest.relative_path}` : "Updated";
    await refreshSavedResults();
    updateSavePanelMode();
  } catch (error) {
    saveStatus.textContent = "Update failed";
    console.error(error);
  } finally {
    saveButton.disabled = false;
  }
}

async function replaceSavedResultViaCreateDelete(manifest) {
  let result = latestResult && manifest.analysis_id === latestManifest?.analysis_id
    ? latestResult
    : null;
  if (!result) {
    const loadPath = `/api/saved-results/${encodeURIComponent(manifest.incident_id)}/${encodeURIComponent(manifest.analysis_id)}`;
    const loadResponse = await apiFetch(loadPath);
    if (!loadResponse.ok) {
      throw new Error(`Load for update failed: ${loadResponse.status}`);
    }
    const loaded = await loadResponse.json();
    result = loaded.result;
  }
  const data = new FormData(saveForm);
  const createResponse = await apiFetch("/api/saved-results", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      incident_number: String(data.get("incident_number") || "").trim(),
      name: String(data.get("name") || "").trim(),
      location: String(data.get("location") || "").trim(),
      description: String(data.get("description") || "").trim(),
      result,
    }),
  });
  if (!createResponse.ok) {
    throw new Error(`Fallback update save failed: ${createResponse.status}`);
  }
  const created = await createResponse.json();
  const deletePath = `/api/saved-results/${encodeURIComponent(manifest.incident_id)}/${encodeURIComponent(manifest.analysis_id)}`;
  const deleteResponse = await apiFetch(deletePath, { method: "DELETE" });
  if (!deleteResponse.ok) {
    throw new Error(`Fallback update cleanup failed: ${deleteResponse.status}`);
  }
  return created.manifest ?? null;
}

async function deleteSavedResult(manifest) {
  const name = manifest.name || "this saved analysis";
  if (!window.confirm(`Delete "${name}"? This cannot be undone.`)) return;
  saveStatus.textContent = "";
  try {
    const path = `/api/saved-results/${encodeURIComponent(manifest.incident_id)}/${encodeURIComponent(manifest.analysis_id)}`;
    const response = await apiFetch(path, { method: "DELETE" });
    if (!response.ok) {
      throw new Error(`Delete failed: ${response.status}`);
    }
    if (latestManifest?.analysis_id === manifest.analysis_id) {
      latestManifest = null;
    }
    if (editingSavedManifest?.analysis_id === manifest.analysis_id) {
      editingSavedManifest = null;
      setSavePanelVisible(false);
      updateSavePanelMode();
    }
    await refreshSavedResults();
  } catch (error) {
    saveStatus.textContent = "Delete failed";
    console.error(error);
  }
}

async function refreshSavedResults() {
  savedList.textContent = "Loading saved analyses...";
  try {
    const response = await apiFetch("/api/saved-results");
    if (!response.ok) {
      throw new Error(`Saved list failed: ${response.status}`);
    }
    const payload = await response.json();
    renderSavedResults(payload);
  } catch (error) {
    savedList.textContent = "Saved analyses unavailable.";
    console.error(error);
  }
}

async function loadSavedResult(manifest) {
  setStatus("loading", "local");
  setBusy(true, "Loading saved analysis");
  try {
    const path = `/api/saved-results/${encodeURIComponent(manifest.incident_id)}/${encodeURIComponent(manifest.analysis_id)}`;
    const response = await apiFetch(path);
    if (!response.ok) {
      throw new Error(`Load failed: ${response.status}`);
    }
    const payload = await response.json();
    latestManifest = payload.manifest ?? manifest;
    latestResult = payload.result;
    editingSavedManifest = null;
    expandedCandidateIds = new Set();
    mapZoomLevel = 0;
    mapViewCenter = defaultMapCenter();
    activeCoveragePolygonLl = resultPolygonLl(latestResult);
    draftCoveragePolygon = [];
    drawingCoverageArea = false;
    setDrawToolsExpanded(false);
    selectedCandidateId = latestResult.coverage_candidate_id ?? latestResult.candidates?.[0]?.candidate_id ?? null;
    manualRepeaterSite = manualRepeaterSiteFromResult(latestResult);
    if (latestManifest?.incident_id) {
      expandedIncidentIds.add(String(latestManifest.incident_id));
    }
    applyResultToForm(latestResult);
    primeSaveForm(latestResult, latestManifest);
    render(latestResult);
    updateResultActions();
    await refreshSavedResults();
    saveStatus.textContent = `Loaded ${latestManifest.name}`;
    setStatus("loaded", latestResult.mode);
  } catch (error) {
    setStatus("failed", "local");
    console.error(error);
  } finally {
    setBusy(false);
  }
}

function setStatus(engine, mode) {
  document.querySelector("#engine-status").textContent = engine;
  document.querySelector("#mode").textContent = mode;
}

function setBusy(isBusy, message = "Analysis running") {
  if (busyMessage && isBusy) {
    busyMessage.textContent = message;
  }
  busyOverlay.hidden = !isBusy;
}

function setHeaderSummary(meta, assessment = "", coverage = "", state = "neutral") {
  document.querySelector("#meta-summary").textContent = meta;
  const assessmentNode = document.querySelector("#assessment-summary");
  assessmentNode.textContent = assessment;
  assessmentNode.classList.toggle("assessment-ok", state === "ok");
  assessmentNode.classList.toggle("assessment-warn", state === "warn");
  document.querySelector("#coverage-summary").textContent = coverage;
}

function setRecommendationPolicy(policy) {
  const panel = document.querySelector("#recommendation-panel");
  if (!panel) return;
  if (!policy) {
    panel.hidden = true;
    return;
  }
  document.querySelector("#recommendation-label").textContent =
    policy.label ?? "best available — verify";
  document.querySelector("#recommendation-warning").textContent =
    policy.warning ?? "Field verification required.";
  panel.hidden = false;
}

function setRunningSummary(payload) {
  const areaText = Array.isArray(payload.target_polygon_ll) && payload.target_polygon_ll.length >= 3
    ? `${payload.target_polygon_ll.length}-point drawn target area`
    : `target centred on ${formatCoordinate(payload.target_lat)}, ${formatCoordinate(payload.target_lon)}`;
  const areaSqKm = Number(payload.target_area_sq_km);
  const areaSummary = Number.isFinite(areaSqKm) ? ` Required coverage area ${formatMetric(areaSqKm, "km2", 2)}.` : "";
  setHeaderSummary(
    `Running ${payload.profile} ${payload.frequency_mhz} MHz analysis for ${areaText}.${areaSummary} Search radius ${formatMetric(payload.search_radius_km, "km", 1)}.`,
    "Analysis running; previous recommendation summary cleared.",
  );
  setRecommendationPolicy(null);
  renderEmptySearchResults("Analysis running...");
}

function setFailedSummary(error) {
  setHeaderSummary(
    "Analysis failed before a new result was returned.",
    error instanceof Error ? error.message : "Analysis failed.",
    "",
    "warn",
  );
  setRecommendationPolicy(null);
}

function updateResultActions() {
  saveButton.disabled = !latestResult && !editingSavedManifest;
  openSavePanelButton.disabled = !latestResult;
  if (!latestResult) {
    setSavePanelVisible(false);
  }
  updateSavePanelMode();
}

function setSavePanelVisible(visible) {
  savePanel.hidden = !visible;
  openSavePanelButton.setAttribute("aria-expanded", String(visible));
}

function openSavePanelForCurrentResult() {
  if (!latestResult) return;
  editingSavedManifest = latestManifest;
  primeSaveForm(latestResult, latestManifest);
  updateSavePanelMode();
  setSavePanelVisible(true);
}

function beginEditSavedResult(manifest) {
  editingSavedManifest = manifest;
  primeSaveForm(latestResult ?? { rf_profile: {} }, manifest);
  updateSavePanelMode();
  setSavePanelVisible(true);
  if (manifest?.incident_id) {
    expandedIncidentIds.add(String(manifest.incident_id));
  }
}

function updateSavePanelMode() {
  const heading = document.querySelector("#save-heading");
  if (!heading || !saveButton) return;
  const isEditing = Boolean(editingSavedManifest);
  heading.textContent = isEditing ? "Edit Saved Result" : "Save Result";
  saveButton.disabled = !latestResult && !isEditing;
  saveButton.replaceChildren();
  saveButton.append(saveIcon(), isEditing ? "Update saved result" : "Save current result");
}

function loadTargetMap() {
  if (!syncCoordinateInputs(true, true)) return;
  const values = formValues();
  latestResult = null;
  latestManifest = null;
  editingSavedManifest = null;
  selectedCandidateId = null;
  drawingCoverageArea = false;
  mapZoomLevel = 0;
  mapViewCenter = defaultMapCenter();
  saveStatus.textContent = "";
  setStatus("waiting", "local");
  if (hasTargetCoordinates(values)) {
    renderEmptyMap(
      `Map loaded for ${formatCoordinate(values.target_lat)}, ${formatCoordinate(values.target_lon)}. Zoom or pan to frame the required coverage area, draw it, then run analysis.`,
    );
  } else {
    renderEmptyMap("Western Australia overview loaded. Zoom or pan to the incident area, then draw the required coverage area or enter coordinates.");
  }
}

function setTargetCoordinates(lat, lon) {
  const nextLat = Number(lat);
  const nextLon = Number(lon);
  if (!Number.isFinite(nextLat) || !Number.isFinite(nextLon)) return;
  coordinateFormatSelect.value = "latlon";
  updateCoordinateFields(false);
  targetLatInput.value = formatCoordinateInput(nextLat);
  targetLonInput.value = formatCoordinateInput(nextLon);
  updateMgrsFromLatLon();
  latestResult = null;
  latestManifest = null;
  editingSavedManifest = null;
  selectedCandidateId = null;
  expandedCandidateIds = new Set();
  mapZoomLevel = 0;
  mapViewCenter = defaultMapCenter();
  setStatus("waiting", "local");
  renderEmptyMap(`Target coordinates set to ${formatCoordinate(nextLat)}, ${formatCoordinate(nextLon)}. Draw a required coverage area or run a circular target analysis.`);
}

function setManualRepeaterSite(lat, lon, name = manualRepeaterSite?.name || DEFAULT_MANUAL_REPEATER_NAME) {
  const nextLat = Number(lat);
  const nextLon = Number(lon);
  if (!Number.isFinite(nextLat) || !Number.isFinite(nextLon)) return;
  manualRepeaterSite = {
    lat: truncateCoordinate(nextLat, 6),
    lon: truncateCoordinate(nextLon, 6),
    name: cleanDisplayName(name, DEFAULT_MANUAL_REPEATER_NAME),
  };
  updateManualSiteStatus();
  renderCurrentMap();
}

function clearManualRepeaterSite() {
  manualRepeaterSite = null;
  updateManualSiteStatus();
  renderCurrentMap();
}

function renameManualRepeaterSite() {
  if (!manualRepeaterSite) return;
  const nextName = window.prompt("Repeater site name", manualRepeaterSite.name || DEFAULT_MANUAL_REPEATER_NAME);
  if (nextName === null) return;
  manualRepeaterSite = {
    ...manualRepeaterSite,
    name: cleanDisplayName(nextName, DEFAULT_MANUAL_REPEATER_NAME),
  };
  if (latestResult?.rf_profile?.manual_repeater_site) {
    latestResult.rf_profile.manual_repeater_site.name = manualRepeaterSite.name;
  }
  const manualCandidate = latestResult?.candidates?.find((candidate) => candidate.candidate_id === "manual_001");
  if (manualCandidate) {
    manualCandidate.name = manualRepeaterSite.name;
  }
  updateManualSiteStatus();
  renderCurrentMap();
}

function manualRepeaterSiteFromResult(result) {
  const site = result?.rf_profile?.manual_repeater_site;
  if (!site) return null;
  const lat = Number(site.lat);
  const lon = Number(site.lon);
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) return null;
  return {
    lat: truncateCoordinate(lat, 6),
    lon: truncateCoordinate(lon, 6),
    name: cleanDisplayName(site.name, DEFAULT_MANUAL_REPEATER_NAME),
  };
}

function renameCandidate(candidateId) {
  if (!latestResult) return;
  const candidate = latestResult.candidates?.find((item) => item.candidate_id === candidateId);
  if (!candidate) return;
  const nextName = window.prompt("Repeater site name", candidate.name || DEFAULT_MANUAL_REPEATER_NAME);
  if (nextName === null) return;
  const cleaned = cleanDisplayName(nextName, candidate.name || DEFAULT_MANUAL_REPEATER_NAME);
  candidate.name = cleaned;
  if (candidate.candidate_id === "manual_001") {
    manualRepeaterSite = manualRepeaterSite ? { ...manualRepeaterSite, name: cleaned } : manualRepeaterSiteFromResult(latestResult);
    if (manualRepeaterSite) manualRepeaterSite.name = cleaned;
    if (latestResult.rf_profile?.manual_repeater_site) {
      latestResult.rf_profile.manual_repeater_site.name = cleaned;
    }
    updateManualSiteStatus();
  }
  if (latestManifest?.analysis_id) {
    saveStatus.textContent = "Site name changed locally. Open save and update the saved result to keep it.";
  }
  updateCoverageSummary(latestResult);
  renderMap(latestResult);
  renderCandidates(latestResult.candidates);
}

function manualSiteMatchesResult(result) {
  if (!manualRepeaterSite) return true;
  const resultSite = manualRepeaterSiteFromResult(result);
  if (!resultSite) return false;
  return Math.abs(resultSite.lat - manualRepeaterSite.lat) < 0.00001
    && Math.abs(resultSite.lon - manualRepeaterSite.lon) < 0.00001;
}

function updateManualSiteStatus() {
  if (!manualSiteStatus || !manualSiteStatusText) return;
  manualSiteStatus.hidden = !manualRepeaterSite;
  if (manualRepeaterSite) {
    manualSiteStatusText.textContent = `${manualRepeaterSite.name || DEFAULT_MANUAL_REPEATER_NAME} ${manualRepeaterSite.lat.toFixed(5)}, ${manualRepeaterSite.lon.toFixed(5)}`;
  }
}

function togglePanelSection(toggle) {
  setPanelSectionExpanded(toggle, toggle.getAttribute("aria-expanded") !== "true");
}

function setPanelSectionExpanded(toggle, expanded) {
  const controls = toggle.getAttribute("aria-controls");
  const content = controls ? document.getElementById(controls) : null;
  if (!content) return;
  toggle.setAttribute("aria-expanded", String(expanded));
  content.hidden = !expanded;
  const section = toggle.closest(".panel-section");
  section?.classList.toggle("collapsed", !expanded);
}

function setMapToolsExpanded(expanded) {
  mapToolsExpanded = Boolean(expanded);
  updateMapToolsControls();
}

function updateMapToolsControls() {
  if (!mapSection || !mapToolsToggle) return;
  mapSection.classList.toggle("map-tools-hidden", !mapToolsExpanded);
  mapToolsToggle.setAttribute("aria-expanded", String(mapToolsExpanded));
  const label = mapToolsToggle.querySelector("span");
  if (label) {
    label.textContent = mapToolsExpanded ? "Hide tools" : "Map tools";
  }
}

function setMobilePanelOpen(side, open) {
  const nextOpen = Boolean(open) && mobileMapQuery.matches;
  if (side === "left") {
    mobileControlPanelOpen = nextOpen;
    if (nextOpen) {
      mobileResultsPanelOpen = false;
    }
  } else {
    mobileResultsPanelOpen = nextOpen;
    if (nextOpen) {
      mobileControlPanelOpen = false;
    }
  }
  updateMobilePanelControls();
}

function updateMobilePanelControls() {
  document.body.classList.toggle("mobile-control-panel-open", mobileControlPanelOpen);
  document.body.classList.toggle("mobile-results-panel-open", mobileResultsPanelOpen);
  controlPanelToggle?.setAttribute("aria-expanded", String(mobileControlPanelOpen));
  resultsPanelToggle?.setAttribute("aria-expanded", String(mobileResultsPanelOpen));
  controlPanel?.setAttribute("aria-hidden", String(mobileMapQuery.matches && !mobileControlPanelOpen));
  resultsPanel?.setAttribute("aria-hidden", String(mobileMapQuery.matches && !mobileResultsPanelOpen));
}

function toggleLayersPanel() {
  const expanded = layersToggle.getAttribute("aria-expanded") !== "true";
  layersToggle.setAttribute("aria-expanded", String(expanded));
  layerOptions.hidden = !expanded;
  layersToggle.closest(".layer-control")?.classList.toggle("collapsed", !expanded);
}

function renderSavedResults(payload) {
  const incidents = normaliseSavedIncidents(payload);
  savedList.replaceChildren();
  if (!incidents.length) {
    const empty = document.createElement("p");
    empty.className = "saved-empty";
    empty.textContent = "No saved analyses yet.";
    savedList.append(empty);
    return;
  }

  if (latestManifest?.incident_id) {
    expandedIncidentIds.add(String(latestManifest.incident_id));
  }

  for (const incident of incidents) {
    const incidentId = String(incident.incident_id || "unfiled");
    const analyses = Array.isArray(incident.analyses) ? incident.analyses : [];
    const isExpanded = expandedIncidentIds.has(incidentId);
    const folder = document.createElement("section");
    folder.className = `incident-folder${isExpanded ? " expanded" : ""}`;

    const analysesId = domId(`incident-${incidentId}-analyses`);
    const toggle = document.createElement("button");
    toggle.type = "button";
    toggle.className = "incident-toggle";
    toggle.setAttribute("aria-expanded", String(isExpanded));
    toggle.setAttribute("aria-controls", analysesId);
    toggle.addEventListener("click", () => {
      if (expandedIncidentIds.has(incidentId)) {
        expandedIncidentIds.delete(incidentId);
      } else {
        expandedIncidentIds.add(incidentId);
      }
      renderSavedResults({ incidents });
    });

    const chevron = el("svg", { class: "folder-chevron", viewBox: "0 0 24 24", "aria-hidden": "true" });
    chevron.append(el("path", { d: "m9 18 6-6-6-6" }));

    const icon = el("svg", { class: "folder-icon", viewBox: "0 0 24 24", "aria-hidden": "true" });
    icon.append(el("path", { d: "M3 7a2 2 0 0 1 2-2h5l2 2h7a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z" }));

    const label = document.createElement("span");
    label.className = "incident-label";
    const title = document.createElement("strong");
    title.textContent = incident.incident_number || "Unfiled";
    const count = document.createElement("small");
    count.textContent = `${analyses.length} ${analyses.length === 1 ? "analysis" : "analyses"}`;
    label.append(title, count);

    toggle.append(chevron, icon, label);
    folder.append(toggle);

    const contents = document.createElement("div");
    contents.id = analysesId;
    contents.className = "incident-analyses";
    contents.hidden = !isExpanded;

    for (const manifest of analyses) {
      contents.append(savedAnalysisButton(manifest));
    }

    folder.append(contents);
    savedList.append(folder);
  }
}

function normaliseSavedIncidents(payload) {
  if (Array.isArray(payload?.incidents)) {
    return payload.incidents.map((incident) => ({
      ...incident,
      analyses: Array.isArray(incident.analyses) ? incident.analyses : [],
    }));
  }
  return groupResultsByIncident(Array.isArray(payload) ? payload : payload?.results ?? []);
}

function groupResultsByIncident(results) {
  const incidents = new Map();
  for (const manifest of results) {
    const incidentId = String(manifest.incident_id || "unfiled");
    if (!incidents.has(incidentId)) {
      incidents.set(incidentId, {
        incident_id: incidentId,
        incident_number: manifest.incident_number || "Unfiled",
        analyses: [],
      });
    }
    incidents.get(incidentId).analyses.push(manifest);
  }
  return Array.from(incidents.values());
}

function savedAnalysisButton(manifest) {
  const item = document.createElement("div");
  item.className = "saved-item";
  if (latestManifest?.analysis_id === manifest.analysis_id) {
    item.classList.add("active");
  }

  const loadButton = document.createElement("button");
  loadButton.type = "button";
  loadButton.className = "saved-item-load";
  loadButton.addEventListener("click", () => loadSavedResult(manifest));

  const title = document.createElement("strong");
  title.textContent = manifest.name || "Saved analysis";
  const location = document.createElement("span");
  location.textContent = manifest.location || "No location recorded";
  const created = document.createElement("small");
  created.textContent = formatTimestamp(manifest.created_at);

  loadButton.append(title, location, created);

  const editButton = document.createElement("button");
  editButton.type = "button";
  editButton.className = "saved-edit icon-button";
  editButton.title = "Edit saved analysis";
  editButton.setAttribute("aria-label", `Edit ${manifest.name || "saved analysis"}`);
  editButton.append(pencilIcon());
  editButton.addEventListener("click", () => beginEditSavedResult(manifest));

  const deleteButton = document.createElement("button");
  deleteButton.type = "button";
  deleteButton.className = "saved-delete icon-button";
  deleteButton.title = "Delete saved analysis";
  deleteButton.setAttribute("aria-label", `Delete ${manifest.name || "saved analysis"}`);
  deleteButton.append(trashIcon());
  deleteButton.addEventListener("click", () => deleteSavedResult(manifest));

  item.append(loadButton, editButton, deleteButton);
  return item;
}

function saveIcon() {
  const svg = el("svg", { viewBox: "0 0 24 24", "aria-hidden": "true" });
  svg.append(el("path", { d: "M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2Z" }));
  svg.append(el("path", { d: "M17 21v-8H7v8" }));
  svg.append(el("path", { d: "M7 3v5h8" }));
  return svg;
}

function pencilIcon() {
  const svg = el("svg", { viewBox: "0 0 24 24", "aria-hidden": "true" });
  svg.append(el("path", { d: "M12 20h9" }));
  svg.append(el("path", { d: "M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z" }));
  return svg;
}

function trashIcon() {
  const svg = el("svg", { viewBox: "0 0 24 24", "aria-hidden": "true" });
  svg.append(el("path", { d: "M3 6h18" }));
  svg.append(el("path", { d: "M8 6V4h8v2" }));
  svg.append(el("path", { d: "M19 6l-1 14H6L5 6" }));
  svg.append(el("path", { d: "M10 11v5" }));
  svg.append(el("path", { d: "M14 11v5" }));
  return svg;
}

function domId(value) {
  return String(value).replace(/[^a-zA-Z0-9_-]+/g, "-");
}

function renderEmptyMap(summary = "Western Australia overview loaded. Zoom or pan to the incident area, draw the required coverage area, enter coordinates, or load a saved result.") {
  document.querySelector("#region-label").textContent = "Western Australia";
  setHeaderSummary(summary);
  renderEmptySearchResults("No search results loaded.");
  renderMap(previewMapResult());
  updateResultActions();
  updateDrawingControls();
  updateManualSiteStatus();
}

function primeSaveForm(result, manifest = null) {
  const rf = result.rf_profile ?? {};
  const candidate = selectedCandidate(result);
  const incidentInput = saveForm.elements.namedItem("incident_number");
  const nameInput = saveForm.elements.namedItem("name");
  const locationInput = saveForm.elements.namedItem("location");
  const descriptionInput = saveForm.elements.namedItem("description");

  if (manifest) {
    incidentInput.value = manifest.incident_number ?? "";
    nameInput.value = manifest.name ?? "";
    locationInput.value = manifest.location ?? "";
    descriptionInput.value = manifest.description ?? "";
    return;
  }

  if (!nameInput.value.trim()) {
    nameInput.value = candidate?.name ?? `${rf.profile ?? "RF"} analysis`;
  }
  if (!locationInput.value.trim() && Number.isFinite(Number(rf.target_lat)) && Number.isFinite(Number(rf.target_lon))) {
    locationInput.value = `${Number(rf.target_lat).toFixed(5)}, ${Number(rf.target_lon).toFixed(5)}`;
  }
}

function applyResultToForm(result) {
  const rf = result.rf_profile ?? {};
  setControlValue("profile", rf.profile);
  setControlValue("frequency_mhz", rf.frequency_mhz);
  setControlValue("target_lat", rf.target_lat);
  setControlValue("target_lon", rf.target_lon);
  setControlValue("search_radius_km", rf.search_radius_km);
  setControlValue("repeater_power_w", rf.repeater_power_w);
  setControlValue("tx_height_m", rf.tx_height_m);
  setControlValue("antenna_gain_dbi", rf.antenna_gain_dbi);
  setControlValue("deployment_profile", rf.deployment_profile);
  setControlValue("user_radio", rf.user_radio);
  setControlValue("service_profile", rf.service_profile);
  setControlValue("noise_environment", rf.noise_environment);
  setControlValue("site_preference", rf.site_preference);
  manualRepeaterSite = manualRepeaterSiteFromResult(result);
  const includeUplink = form.elements.namedItem("include_uplink");
  if (includeUplink) includeUplink.checked = Boolean(rf.include_uplink);
  updateMgrsFromLatLon();
  updateCoordinateFields(false);
}

function setControlValue(name, value) {
  if (value === undefined || value === null) return;
  const control = form.elements.namedItem(name);
  if (!control) return;
  if (name === "target_lat" || name === "target_lon") {
    control.value = formatCoordinateInput(value);
    return;
  }
  control.value = value;
}

function renderCurrentMap() {
  if (latestResult) {
    renderMap(latestResult);
    renderCandidates(latestResult.candidates);
    updateCoverageSummary(latestResult);
    return;
  }
  renderEmptyMap();
}

function currentMapBounds() {
  return latestResult?.metadata?.region_bounds ?? previewBoundsFromForm();
}

function previewMapResult() {
  const rf = formValues();
  const bounds = previewBoundsFromForm(rf);
  const drawnPolygon = targetPolygonForPayload();
  const targetCenter = hasTargetCoordinates(rf)
    ? { lat: rf.target_lat, lon: rf.target_lon }
    : polygonCentroidLatLon(drawnPolygon);
  const targetPolygonLl = drawnPolygon.length >= 3
    ? drawnPolygon.map(([lat, lon]) => ({ lat, lon }))
    : targetCenter
      ? circlePolygon(targetCenter.lat, targetCenter.lon, rf.target_radius_km, 40)
      : [];
  const targetPolygon = targetPolygonLl.map((point) => {
    const mapPoint = latLonToMapPoint(point.lat, point.lon, bounds);
    return [mapPoint.x, mapPoint.y];
  });
  const targetCenterPoint = targetCenter ? latLonToMapPoint(targetCenter.lat, targetCenter.lon, bounds) : null;
  const overview = !targetCenter && drawnPolygon.length < 3;
  return {
    metadata: {
      region_bounds: bounds,
      overview,
      target_area: {
        type: drawnPolygon.length >= 3 ? "polygon" : targetCenter ? "circle" : "none",
        area_sq_km: targetCenter || drawnPolygon.length >= 3 ? targetAreaSqKm(drawnPolygon, rf.target_radius_km) : null,
      },
    },
    target_polygon: targetPolygon,
    target_center: targetCenterPoint ? {
      ...targetCenterPoint,
      elevation_m: "preview",
    } : null,
    terrain_cells: [],
    roads: [],
    display_roads: [],
    coverage: [],
    candidates: [],
  };
}

function previewBoundsFromForm(values = formValues()) {
  const drawnPolygon = normalisePolygonLl(activeCoveragePolygonLl);
  if (drawnPolygon.length >= 3) {
    return viewportForBounds({
      west: Math.min(...drawnPolygon.map((point) => point[1])),
      south: Math.min(...drawnPolygon.map((point) => point[0])),
      east: Math.max(...drawnPolygon.map((point) => point[1])),
      north: Math.max(...drawnPolygon.map((point) => point[0])),
    });
  }
  if (!hasTargetCoordinates(values)) {
    return viewportForBounds(WA_BOUNDS);
  }
  const lat = clamp(Number(values.target_lat), WA_BOUNDS.south, WA_BOUNDS.north);
  const lon = clamp(Number(values.target_lon), WA_BOUNDS.west, WA_BOUNDS.east);
  const radius = Math.max(3, Number(values.search_radius_km) || 3);
  const latDelta = radius / 110.574;
  const lonDelta = radius / Math.max(25, 111.320 * Math.cos(toRadians(lat)));
  const bbox = {
    west: clamp(lon - lonDelta, WA_BOUNDS.west, WA_BOUNDS.east),
    south: clamp(lat - latDelta, WA_BOUNDS.south, WA_BOUNDS.north),
    east: clamp(lon + lonDelta, WA_BOUNDS.west, WA_BOUNDS.east),
    north: clamp(lat + latDelta, WA_BOUNDS.south, WA_BOUNDS.north),
  };
  return viewportForBounds(bbox);
}

function viewportForBounds(bounds) {
  const width = bounds.east - bounds.west;
  const height = bounds.north - bounds.south;
  const padX = Math.max(width * 0.05, 0.01);
  const padY = Math.max(height * 0.05, 0.01);
  return {
    crs: "EPSG:4326",
    west: bounds.west - padX,
    south: bounds.south - padY,
    east: bounds.east + padX,
    north: bounds.north + padY,
  };
}

function latLonToMapPoint(lat, lon, bounds = currentMapBounds()) {
  const x = (Number(lon) - Number(bounds.west)) / Math.max(1e-9, Number(bounds.east) - Number(bounds.west));
  const y = (Number(lat) - Number(bounds.south)) / Math.max(1e-9, Number(bounds.north) - Number(bounds.south));
  return { x: clamp(x, 0, 1), y: clamp(y, 0, 1) };
}

function mapPointToLatLon(point, bounds = currentMapBounds()) {
  const x = point.x / BASE_VIEWBOX.width;
  const y = 1 - point.y / BASE_VIEWBOX.height;
  return {
    lat: Number(bounds.south) + y * (Number(bounds.north) - Number(bounds.south)),
    lon: Number(bounds.west) + x * (Number(bounds.east) - Number(bounds.west)),
  };
}

function updateCoordinateFields(syncValues = false) {
  const isMgrs = coordinateFormatSelect.value === "mgrs";
  latLonFields.hidden = isMgrs;
  mgrsField.hidden = !isMgrs;
  if (syncValues && isMgrs) {
    updateMgrsFromLatLon();
  } else if (syncValues) {
    syncCoordinateInputs(false);
  }
}

function syncCoordinateInputs(reportErrors = false, allowBlank = false) {
  if (coordinateFormatSelect.value !== "mgrs") {
    targetMgrsInput?.setCustomValidity("");
    return true;
  }
  if (!String(targetMgrsInput.value || "").trim()) {
    targetMgrsInput.setCustomValidity(allowBlank ? "" : "Enter a valid MGRS coordinate or draw the required coverage area.");
    if (reportErrors && !allowBlank) {
      targetMgrsInput.reportValidity();
    }
    return allowBlank;
  }
  try {
    const converted = mgrsToLatLon(String(targetMgrsInput.value || ""));
    targetLatInput.value = formatCoordinateInput(converted.lat);
    targetLonInput.value = formatCoordinateInput(converted.lon);
    targetMgrsInput.setCustomValidity("");
    return true;
  } catch (error) {
    targetMgrsInput.setCustomValidity(error instanceof Error ? error.message : "Enter a valid MGRS coordinate.");
    if (reportErrors) {
      targetMgrsInput.reportValidity();
    }
    return false;
  }
}

function updateMgrsFromLatLon() {
  if (!targetMgrsInput) return;
  const rawLat = String(targetLatInput.value || "").trim();
  const rawLon = String(targetLonInput.value || "").trim();
  if (!rawLat || !rawLon) {
    targetMgrsInput.value = "";
    targetMgrsInput.setCustomValidity("");
    return;
  }
  const lat = Number(rawLat);
  const lon = Number(rawLon);
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) {
    targetMgrsInput.value = "";
    return;
  }
  try {
    targetMgrsInput.value = latLonToMgrs(lat, lon);
    targetMgrsInput.setCustomValidity("");
  } catch {
    targetMgrsInput.value = "";
  }
}

function latLonToMgrs(lat, lon) {
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) {
    throw new Error("Enter valid latitude and longitude values.");
  }
  if (lat < -80 || lat > 84) {
    throw new Error("MGRS supports latitudes from 80S to 84N.");
  }
  const utm = latLonToUtm(lat, lon);
  const band = latitudeBand(lat);
  const columnSet = MGRS_COLUMN_SETS[(utm.zone - 1) % 3];
  const columnIndex = Math.floor(utm.easting / 100000) - 1;
  const column = columnSet[columnIndex];
  const row = MGRS_ROWS[(Math.floor(utm.northing / 100000) + mgrsRowOffset(utm.zone)) % MGRS_ROWS.length];
  if (!column || !row) {
    throw new Error("Coordinate could not be converted to MGRS.");
  }
  const easting = String(Math.floor(utm.easting % 100000)).padStart(5, "0");
  const northing = String(Math.floor(utm.northing % 100000)).padStart(5, "0");
  return `${utm.zone}${band} ${column}${row} ${easting} ${northing}`;
}

function mgrsToLatLon(value) {
  const text = String(value || "").toUpperCase().replace(/\s+/g, "");
  const match = text.match(/^(\d{1,2})([C-HJ-NP-X])([A-HJ-NP-Z]{2})(\d*)$/);
  if (!match) {
    throw new Error("Enter MGRS like 50J MK 12345 67890.");
  }
  const zone = Number(match[1]);
  const band = match[2];
  const square = match[3];
  const digits = match[4] ?? "";
  if (zone < 1 || zone > 60 || digits.length % 2 !== 0 || digits.length > 10) {
    throw new Error("Enter a valid MGRS grid zone and even easting/northing digits.");
  }
  const columnSet = MGRS_COLUMN_SETS[(zone - 1) % 3];
  const columnIndex = columnSet.indexOf(square[0]);
  const rowIndex = MGRS_ROWS.indexOf(square[1]);
  if (columnIndex < 0 || rowIndex < 0) {
    throw new Error("Enter a valid MGRS 100 km square.");
  }
  const precision = digits.length / 2;
  const scale = 10 ** (5 - precision);
  const eastingDigits = digits.slice(0, precision);
  const northingDigits = digits.slice(precision);
  const offset = precision < 5 ? scale / 2 : 0;
  const easting = (columnIndex + 1) * 100000
    + (eastingDigits ? Number(eastingDigits.padEnd(5, "0")) : 0)
    + offset;
  let northing = ((rowIndex - mgrsRowOffset(zone) + MGRS_ROWS.length) % MGRS_ROWS.length) * 100000
    + (northingDigits ? Number(northingDigits.padEnd(5, "0")) : 0)
    + offset;
  const bandSouth = latitudeBandSouth(band);
  const bandNorthing = latLonToUtm(bandSouth, zoneCentralMeridian(zone)).northing;
  while (northing < bandNorthing) {
    northing += 2000000;
  }
  return utmToLatLon(zone, easting, northing, band >= "N");
}

function latitudeBand(lat) {
  const index = Math.min(MGRS_BANDS.length - 1, Math.max(0, Math.floor((lat + 80) / 8)));
  return MGRS_BANDS[index];
}

function latitudeBandSouth(band) {
  const index = MGRS_BANDS.indexOf(band);
  if (index < 0) throw new Error("Enter a valid MGRS latitude band.");
  return band === "X" ? 72 : -80 + index * 8;
}

function mgrsRowOffset(zone) {
  return zone % 2 === 0 ? 5 : 0;
}

function zoneCentralMeridian(zone) {
  return (zone - 1) * 6 - 180 + 3;
}

function latLonToUtm(lat, lon) {
  const e2 = WGS84_F * (2 - WGS84_F);
  const ep2 = e2 / (1 - e2);
  const zone = Math.floor((lon + 180) / 6) + 1;
  const latRad = toRadians(lat);
  const lonRad = toRadians(lon);
  const lonOriginRad = toRadians(zoneCentralMeridian(zone));
  const sinLat = Math.sin(latRad);
  const cosLat = Math.cos(latRad);
  const tanLat = Math.tan(latRad);
  const n = WGS84_A / Math.sqrt(1 - e2 * sinLat * sinLat);
  const t = tanLat * tanLat;
  const c = ep2 * cosLat * cosLat;
  const a = cosLat * (lonRad - lonOriginRad);
  const m = WGS84_A * (
    (1 - e2 / 4 - 3 * e2 ** 2 / 64 - 5 * e2 ** 3 / 256) * latRad
    - (3 * e2 / 8 + 3 * e2 ** 2 / 32 + 45 * e2 ** 3 / 1024) * Math.sin(2 * latRad)
    + (15 * e2 ** 2 / 256 + 45 * e2 ** 3 / 1024) * Math.sin(4 * latRad)
    - (35 * e2 ** 3 / 3072) * Math.sin(6 * latRad)
  );
  const easting = UTM_K0 * n * (
    a
    + (1 - t + c) * a ** 3 / 6
    + (5 - 18 * t + t * t + 72 * c - 58 * ep2) * a ** 5 / 120
  ) + 500000;
  let northing = UTM_K0 * (
    m + n * tanLat * (
      a * a / 2
      + (5 - t + 9 * c + 4 * c * c) * a ** 4 / 24
      + (61 - 58 * t + t * t + 600 * c - 330 * ep2) * a ** 6 / 720
    )
  );
  if (lat < 0) northing += 10000000;
  return { zone, easting, northing };
}

function utmToLatLon(zone, easting, northing, northernHemisphere) {
  const e2 = WGS84_F * (2 - WGS84_F);
  const ep2 = e2 / (1 - e2);
  const e1 = (1 - Math.sqrt(1 - e2)) / (1 + Math.sqrt(1 - e2));
  const x = easting - 500000;
  const y = northernHemisphere ? northing : northing - 10000000;
  const m = y / UTM_K0;
  const mu = m / (WGS84_A * (1 - e2 / 4 - 3 * e2 ** 2 / 64 - 5 * e2 ** 3 / 256));
  const fp = mu
    + (3 * e1 / 2 - 27 * e1 ** 3 / 32) * Math.sin(2 * mu)
    + (21 * e1 ** 2 / 16 - 55 * e1 ** 4 / 32) * Math.sin(4 * mu)
    + (151 * e1 ** 3 / 96) * Math.sin(6 * mu)
    + (1097 * e1 ** 4 / 512) * Math.sin(8 * mu);
  const sinFp = Math.sin(fp);
  const cosFp = Math.cos(fp);
  const tanFp = Math.tan(fp);
  const c1 = ep2 * cosFp * cosFp;
  const t1 = tanFp * tanFp;
  const n1 = WGS84_A / Math.sqrt(1 - e2 * sinFp * sinFp);
  const r1 = WGS84_A * (1 - e2) / ((1 - e2 * sinFp * sinFp) ** 1.5);
  const d = x / (n1 * UTM_K0);
  const lat = fp - (n1 * tanFp / r1) * (
    d * d / 2
    - (5 + 3 * t1 + 10 * c1 - 4 * c1 * c1 - 9 * ep2) * d ** 4 / 24
    + (61 + 90 * t1 + 298 * c1 + 45 * t1 * t1 - 252 * ep2 - 3 * c1 * c1) * d ** 6 / 720
  );
  const lonOrigin = toRadians(zoneCentralMeridian(zone));
  const lon = lonOrigin + (
    d
    - (1 + 2 * t1 + c1) * d ** 3 / 6
    + (5 - 2 * c1 + 28 * t1 - 3 * c1 * c1 + 8 * ep2 + 24 * t1 * t1) * d ** 5 / 120
  ) / cosFp;
  return {
    lat: toDegrees(lat),
    lon: toDegrees(lon),
  };
}

function draftPolygonLatLon() {
  if (draftCoveragePolygon.length < 3) return [];
  return draftCoveragePolygon.map((point) => {
    const latLon = mapPointToLatLon(point);
    return [
      Number(clamp(latLon.lat, WA_BOUNDS.south, WA_BOUNDS.north).toFixed(6)),
      Number(clamp(latLon.lon, WA_BOUNDS.west, WA_BOUNDS.east).toFixed(6)),
    ];
  });
}

function targetPolygonForPayload() {
  const draftPolygon = draftPolygonLatLon();
  if (draftPolygon.length >= 3) return draftPolygon;
  return normalisePolygonLl(activeCoveragePolygonLl);
}

function targetAreaSqKm(polygon, radiusKm = DEFAULT_TARGET_RADIUS_KM) {
  const points = normalisePolygonLl(polygon);
  if (points.length >= 3) {
    return Number(polygonAreaSqKm(points).toFixed(3));
  }
  return Number((Math.PI * Number(radiusKm) * Number(radiusKm)).toFixed(3));
}

function polygonAreaSqKm(points) {
  if (!points.length) return 0;
  const origin = points[0];
  const projected = points.map(([lat, lon]) => projectLatLonKm(lat, lon, origin[0], origin[1]));
  let area = 0;
  for (let index = 0; index < projected.length; index += 1) {
    const [x1, y1] = projected[index];
    const [x2, y2] = projected[(index + 1) % projected.length];
    area += x1 * y2 - x2 * y1;
  }
  return Math.abs(area) / 2;
}

function projectLatLonKm(lat, lon, originLat, originLon) {
  const radius = 6371.0088;
  return [
    toRadians(Number(lon) - Number(originLon)) * Math.cos(toRadians(originLat)) * radius,
    toRadians(Number(lat) - Number(originLat)) * radius,
  ];
}

function measurementDistanceKm() {
  if (measurePoints.length < 2) return 0;
  let total = 0;
  for (let index = 1; index < measurePoints.length; index += 1) {
    const previous = mapPointToLatLon(measurePoints[index - 1]);
    const current = mapPointToLatLon(measurePoints[index]);
    total += haversineDistanceKm(previous.lat, previous.lon, current.lat, current.lon);
  }
  return total;
}

function haversineDistanceKm(lat1, lon1, lat2, lon2) {
  const radius = 6371.0088;
  const phi1 = toRadians(lat1);
  const phi2 = toRadians(lat2);
  const dPhi = toRadians(Number(lat2) - Number(lat1));
  const dLambda = toRadians(Number(lon2) - Number(lon1));
  const a = Math.sin(dPhi / 2) ** 2
    + Math.cos(phi1) * Math.cos(phi2) * Math.sin(dLambda / 2) ** 2;
  return 2 * radius * Math.asin(Math.sqrt(a));
}

function niceScaleDistanceKm(rawKm) {
  const value = Number(rawKm);
  if (!Number.isFinite(value) || value <= 0) return 0;
  const exponent = Math.floor(Math.log10(value));
  const base = 10 ** exponent;
  for (const multiplier of [1, 2, 5, 10]) {
    const candidate = multiplier * base;
    if (candidate >= value) {
      return candidate;
    }
  }
  return base * 10;
}

function polygonCentroidLatLon(polygon) {
  const points = normalisePolygonLl(polygon);
  if (points.length < 3) return null;
  let signedArea = 0;
  let centroidLat = 0;
  let centroidLon = 0;
  for (let index = 0; index < points.length; index += 1) {
    const [lat1, lon1] = points[index];
    const [lat2, lon2] = points[(index + 1) % points.length];
    const cross = lon1 * lat2 - lon2 * lat1;
    signedArea += cross;
    centroidLon += (lon1 + lon2) * cross;
    centroidLat += (lat1 + lat2) * cross;
  }
  if (Math.abs(signedArea) < 1e-12) {
    const average = points.reduce((total, [lat, lon]) => ({
      lat: total.lat + lat,
      lon: total.lon + lon,
    }), { lat: 0, lon: 0 });
    return {
      lat: Number((average.lat / points.length).toFixed(6)),
      lon: Number((average.lon / points.length).toFixed(6)),
    };
  }
  const scale = 1 / (3 * signedArea);
  return {
    lat: Number((centroidLat * scale).toFixed(6)),
    lon: Number((centroidLon * scale).toFixed(6)),
  };
}

function resultPolygonLl(result) {
  if (result?.rf_profile?.target_area_type !== "polygon") return [];
  return normalisePolygonLl(result.target_polygon_ll);
}

function normalisePolygonLl(polygon) {
  if (!Array.isArray(polygon) || polygon.length < 3) return [];
  const normalised = [];
  for (const rawPoint of polygon) {
    if (!Array.isArray(rawPoint) || rawPoint.length < 2) continue;
    const lat = Number(rawPoint[0]);
    const lon = Number(rawPoint[1]);
    if (!Number.isFinite(lat) || !Number.isFinite(lon)) continue;
    normalised.push([Number(lat.toFixed(6)), Number(lon.toFixed(6))]);
  }
  return normalised.length >= 3 ? normalised : [];
}

function circlePolygon(lat, lon, radiusKm, count) {
  const points = [];
  for (let index = 0; index < count; index += 1) {
    points.push(destinationPoint(lat, lon, radiusKm, index * 360 / count));
  }
  return points;
}

function destinationPoint(lat, lon, distanceKm, bearingDeg) {
  const radius = 6371.0088;
  const bearing = toRadians(bearingDeg);
  const phi1 = toRadians(Number(lat));
  const lambda1 = toRadians(Number(lon));
  const delta = Number(distanceKm) / radius;
  const phi2 = Math.asin(Math.sin(phi1) * Math.cos(delta) + Math.cos(phi1) * Math.sin(delta) * Math.cos(bearing));
  const lambda2 = lambda1 + Math.atan2(
    Math.sin(bearing) * Math.sin(delta) * Math.cos(phi1),
    Math.cos(delta) - Math.sin(phi1) * Math.sin(phi2),
  );
  return { lat: toDegrees(phi2), lon: toDegrees(lambda2) };
}

function eventMapPoint(event) {
  return clientToMapPoint(event.clientX, event.clientY);
}

function clientToMapPoint(clientX, clientY, options = {}) {
  const point = clientToSvgPoint(clientX, clientY);
  if (!point) return { x: 0, y: 0 };
  if (options.clamp === false) return point;
  const viewBox = currentMapViewBox();
  return {
    x: clamp(point.x, viewBox.x, viewBox.x + viewBox.width),
    y: clamp(point.y, viewBox.y, viewBox.y + viewBox.height),
  };
}

function clientToSvgPoint(clientX, clientY) {
  const matrix = mapSvg.getScreenCTM?.();
  if (matrix) {
    const point = mapSvg.createSVGPoint();
    point.x = Number(clientX);
    point.y = Number(clientY);
    const transformed = point.matrixTransform(matrix.inverse());
    return { x: transformed.x, y: transformed.y };
  }
  const rect = mapSvg.getBoundingClientRect();
  const viewBox = currentMapViewBox();
  const x = viewBox.x + ((clientX - rect.left) / Math.max(1, rect.width)) * viewBox.width;
  const y = viewBox.y + ((clientY - rect.top) / Math.max(1, rect.height)) * viewBox.height;
  return { x, y };
}

function clientToMapRatio(clientX, clientY) {
  const point = clientToMapPoint(clientX, clientY);
  const viewBox = currentMapViewBox();
  return {
    x: clamp((point.x - viewBox.x) / Math.max(1, viewBox.width), 0, 1),
    y: clamp((point.y - viewBox.y) / Math.max(1, viewBox.height), 0, 1),
  };
}

function mapUnitsPerScreenPixel(viewBox = currentMapViewBox()) {
  const rect = mapSvg.getBoundingClientRect();
  const xScale = rect.width / Math.max(1, viewBox.width);
  const yScale = rect.height / Math.max(1, viewBox.height);
  const preserveAspectRatio = mapSvg.getAttribute("preserveAspectRatio") ?? "";
  const screenScale = preserveAspectRatio.includes("slice")
    ? Math.max(xScale, yScale)
    : Math.min(xScale, yScale);
  return screenScale > 0 ? 1 / screenScale : viewBox.width / Math.max(1, rect.width);
}

function toRadians(value) {
  return Number(value) * Math.PI / 180;
}

function toDegrees(value) {
  return Number(value) * 180 / Math.PI;
}

function clamp(value, low, high) {
  return Math.max(low, Math.min(high, Number(value)));
}

function truncateCoordinate(value, decimals = COORDINATE_INPUT_DECIMALS) {
  if (value === null || value === undefined || value === "") return null;
  const number = Number(value);
  if (!Number.isFinite(number)) return null;
  const factor = 10 ** decimals;
  return Math.trunc(number * factor) / factor;
}

function formatCoordinateInput(value) {
  const truncated = truncateCoordinate(value);
  return truncated === null ? "" : truncated.toFixed(COORDINATE_INPUT_DECIMALS);
}

function normaliseCoordinateInput(control) {
  if (!control || !String(control.value || "").trim()) return;
  const formatted = formatCoordinateInput(control.value);
  if (formatted) {
    control.value = formatted;
  }
}

function cleanDisplayName(value, fallback) {
  const text = String(value ?? "").trim().replace(/\s+/g, " ");
  return text || fallback;
}

function formatTimestamp(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleString([], {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function render(result) {
  document.querySelector("#region-label").textContent = "Western Australia";
  const roadCount = result.metadata.roads?.count ?? 0;
  const tileCount = result.metadata.terrain_tiles?.length ?? 0;
  const deployment = result.deployment_profile?.name ?? "deployment profile";
  const service = result.service_profile?.name ?? "service profile";
  const loss = result.service_profile?.user_losses_db ?? result.rf_profile.user_losses_db;
  const fade = result.service_profile?.fade_margin_db ?? result.rf_profile.fade_margin_db;
  const diagnosticNote = result.service_profile?.id === "engineering_sensitivity" ? " Diagnostic comparison only, not field assurance." : "";
  const roadDataset = result.metadata.roads?.dataset ?? "road/track data";
  const noiseEnvironment = result.metadata.analysis_preferences?.noise_environment;
  const sitePreference = sitePreferenceLabel(
    result.metadata.analysis_preferences?.site_preference?.id ?? result.rf_profile.site_preference,
  );
  const noiseLabel = noiseEnvironment
    ? `${noiseEnvironment.name} ${formatMetric(noiseEnvironment.noise_floor_dbm, "dBm", 0)}`
    : `${formatMetric(result.rf_profile.noise_floor_dbm, "dBm", 0)}`;
  const rxThresholds = result.metadata?.analysis_preferences?.rx_thresholds ?? result.rf_profile?.rx_thresholds;
  const downlinkGate = rxThresholds?.portable_rx?.threshold_dbm;
  const talkbackGate = rxThresholds?.repeater_rx?.threshold_dbm;
  const thresholdText =
    Number.isFinite(Number(downlinkGate)) && Number.isFinite(Number(talkbackGate))
      ? ` RX gates: downlink/portable RX ${formatMetric(downlinkGate, "dBm", 0)}, talkback/repeater RX ${formatMetric(talkbackGate, "dBm", 0)}.`
      : "";
  const targetArea = Number(result.metadata?.target_area?.area_sq_km ?? result.rf_profile?.target_area_sq_km);
  const areaText = Number.isFinite(targetArea) ? ` Required coverage area ${formatMetric(targetArea, "km2", 2)}.` : "";
  document.querySelector("#meta-summary").textContent =
    `${result.metadata.region_description}. ${result.rf_profile.profile} ${result.rf_profile.frequency_mhz} MHz, ${result.rf_profile.repeater_power_w} W repeater, ${result.rf_profile.tx_height_m} m mast, ${deployment}. ${service}: ${fade} dB fade, ${loss} dB local loss, ${noiseLabel} noise floor.${thresholdText} Site selection: ${sitePreference}.${areaText}${diagnosticNote} Display uses Landgate/SLIP aerial imagery and transport roads/trails; candidate screening used ${roadCount} ${roadDataset} features and ${tileCount} HGT tiles.`;
  const assessment = document.querySelector("#assessment-summary");
  assessment.textContent = result.assessment?.message ?? "";
  assessment.classList.toggle("assessment-ok", (result.assessment?.ok_candidate_count ?? 0) > 0);
  assessment.classList.toggle("assessment-warn", (result.assessment?.ok_candidate_count ?? 0) === 0);
  setRecommendationPolicy(
    result.recommendation ?? {
      label: result.assessment?.recommendation_label ?? "best available — verify",
      warning: result.assessment?.field_verification_warning ?? "Field verification required.",
    },
  );
  updateCoverageSummary(result);
  renderMap(result);
  renderCandidates(result.candidates);
  updateManualSiteStatus();
}

function selectCandidate(candidateId) {
  if (!latestResult) return;
  selectedCandidateId = candidateId;
  const candidate = selectedCandidate(latestResult);
  if (candidate && mapZoomLevel > 0) {
    centerMapOnCandidate(candidate);
  }
  updateCoverageSummary(latestResult);
  renderMap(latestResult);
  renderCandidates(latestResult.candidates);
}

function zoomToCandidate(candidateId) {
  if (!latestResult) return;
  selectedCandidateId = candidateId;
  const candidate = selectedCandidate(latestResult);
  if (!candidate) return;
  mapZoomLevel = MAX_MAP_ZOOM;
  centerMapOnCandidate(candidate);
  updateCoverageSummary(latestResult);
  renderMap(latestResult);
  renderCandidates(latestResult.candidates);
}

function handleCandidatePointerClick(candidateId, event) {
  event.preventDefault();
  event.stopPropagation();
  if (Date.now() < suppressCandidateClickUntil) return;
  const now = window.performance.now();
  const isSameCandidateDoubleClick =
    candidateLastClick.candidateId === candidateId && now - candidateLastClick.at <= 420;
  window.clearTimeout(candidateClickTimer);
  if (event.detail >= 2 || isSameCandidateDoubleClick) {
    candidateLastClick = { candidateId: null, at: 0 };
    candidateClickTimer = null;
    zoomToCandidate(candidateId);
    return;
  }
  candidateLastClick = { candidateId, at: now };
  candidateClickTimer = window.setTimeout(() => {
    selectCandidate(candidateId);
    candidateClickTimer = null;
    candidateLastClick = { candidateId: null, at: 0 };
  }, 420);
}

function selectedCandidate(result) {
  const candidates = result.candidates ?? [];
  return candidates.find((candidate) => candidate.candidate_id === selectedCandidateId) ?? candidates[0];
}

function updateCoverageSummary(result) {
  const coverageSummary = document.querySelector("#coverage-summary");
  const candidate = selectedCandidate(result);
  if (!candidate) {
    coverageSummary.textContent = "";
    return;
  }
  coverageSummary.textContent =
    `Coverage shown: ${candidate.rank}. ${candidate.name} · two-way ${candidate.coverage_pct}% · talkback ${candidate.uplink_coverage_pct}%`;
}

function renderMap(result) {
  const svg = mapSvg;
  updateMapAspectMode(result);
  svg.replaceChildren();
  addDefs(svg);
  addTopo(svg);
  const aerialLayer = addLayerGroup(svg, "aerial");
  addSlipImageLayer(aerialLayer, result, "aerial", "slip-aerial-image");

  const terrainLayer = addLayerGroup(svg, "terrain");
  renderTerrain(terrainLayer, result.terrain_cells ?? []);

  const contourLayer = addLayerGroup(svg, "contours");
  renderContours(contourLayer, result.terrain_cells ?? []);

  const roadLayer = addLayerGroup(svg, "roads");
  addSlipImageLayer(roadLayer, result, "transport", "slip-transport-image");

  const minorRoadLayer = addLayerGroup(svg, "minor-roads");
  const trailLayer = addLayerGroup(svg, "trails");
  renderDisplayRoads(result.display_roads ?? [], minorRoadLayer, trailLayer);

  const sourceRoadLayer = addLayerGroup(svg, "source-roads");
  for (const road of result.roads ?? []) {
    addPolyline(sourceRoadLayer, road, "source-road-shadow");
    addPolyline(sourceRoadLayer, road, "source-road");
  }

  const selected = selectedCandidate(result);
  const coverageLayer = addLayerGroup(svg, "coverage");
  renderCoverage(coverageLayer, selected?.coverage_cells ?? result.coverage);

  const targetLayer = addLayerGroup(svg, "target");
  addPolygon(targetLayer, result.target_polygon, "target");
  if (result.target_center) {
    addTargetCenter(targetLayer, result.target_center);
  }
  renderDraftCoverageArea(targetLayer);

  const candidateLayer = addLayerGroup(svg, "candidates");
  for (const candidate of result.candidates ?? []) {
    addCandidate(candidateLayer, candidate, candidate.candidate_id === selected?.candidate_id);
  }
  if (!manualSiteMatchesResult(result)) {
    addManualRepeaterMarker(candidateLayer, result);
  }

  const measureLayer = addLayerGroup(svg, "measure");
  renderMeasurement(measureLayer);

  updateCoverageOpacity();
  applyMapLayerVisibility();
  applyMapViewBox();
}

function updateMapAspectMode(result = latestResult ?? previewMapResult()) {
  const isOverview = Boolean(result?.metadata?.overview);
  const aspectMode = mobileMapQuery.matches && !isOverview ? MAP_ASPECT_FILL : MAP_ASPECT_OVERVIEW;
  mapSvg.setAttribute("preserveAspectRatio", aspectMode);
}

function updateCoverageOpacity() {
  mapSvg.style.setProperty("--rf-coverage-opacity", String(coverageOpacity));
  if (coverageOpacityValue) {
    coverageOpacityValue.textContent = `${Math.round(coverageOpacity * 100)}%`;
  }
}

function addLayerGroup(svg, layerName) {
  const group = el("g", { "data-layer": layerName, class: `map-layer map-layer-${layerName}` });
  svg.append(group);
  return group;
}

function addSlipImageLayer(svg, result, serviceKey, className) {
  const viewBox = currentMapViewBox();
  const href = slipExportUrl(result, serviceKey, viewBox);
  if (!href) return;
  const image = el("image", {
    x: viewBox.x,
    y: viewBox.y,
    width: viewBox.width,
    height: viewBox.height,
    href,
    class: className,
    "data-slip-service": serviceKey,
    preserveAspectRatio: "none",
  });
  svg.append(image);
}

function slipExportUrl(result, serviceKey, viewBox = currentMapViewBox()) {
  const service = SLIP_SERVICES[serviceKey];
  const bounds = mapBoundsForViewBox(result, viewBox);
  if (!service || !bounds) return "";
  const values = [bounds.west, bounds.south, bounds.east, bounds.north];
  if (values.some((value) => !Number.isFinite(value))) return "";
  const params = new URLSearchParams({
    bbox: values.map((value) => value.toFixed(6)).join(","),
    bboxSR: "7844",
    imageSR: "7844",
    size: MAP_EXPORT_SIZE,
    format: service.format,
    transparent: String(service.transparent),
    layers: service.layers,
    f: "image",
  });
  return `${service.url}?${params.toString()}`;
}

function mapBoundsForViewBox(result, viewBox) {
  const bounds = result?.metadata?.region_bounds ?? currentMapBounds();
  if (!bounds) return null;
  const west = Number(bounds.west);
  const south = Number(bounds.south);
  const east = Number(bounds.east);
  const north = Number(bounds.north);
  if ([west, south, east, north].some((value) => !Number.isFinite(value))) return null;
  const lonSpan = east - west;
  const latSpan = north - south;
  return {
    west: west + (viewBox.x / BASE_VIEWBOX.width) * lonSpan,
    east: west + ((viewBox.x + viewBox.width) / BASE_VIEWBOX.width) * lonSpan,
    north: north - (viewBox.y / BASE_VIEWBOX.height) * latSpan,
    south: north - ((viewBox.y + viewBox.height) / BASE_VIEWBOX.height) * latSpan,
  };
}

function applyMapLayerVisibility() {
  for (const [layerName, visible] of Object.entries(mapLayerState)) {
    const layer = mapSvg.querySelector(`[data-layer="${layerName}"]`);
    if (!layer) continue;
    layer.hidden = !visible;
    layer.style.display = visible ? "" : "none";
  }
}

function zoomMap(delta, options = {}) {
  const previousViewBox = currentMapViewBox();
  const nextZoomLevel = Math.max(MIN_MAP_ZOOM, Math.min(MAX_MAP_ZOOM, mapZoomLevel + delta));
  if (nextZoomLevel === mapZoomLevel) return;

  if (options.anchorPoint) {
    const anchorRatio = options.anchorRatio ?? {
      x: (options.anchorPoint.x - previousViewBox.x) / Math.max(1, previousViewBox.width),
      y: (options.anchorPoint.y - previousViewBox.y) / Math.max(1, previousViewBox.height),
    };
    const nextSize = mapViewBoxSize(nextZoomLevel);
    mapZoomLevel = nextZoomLevel;
    mapViewCenter = clampMapCenter(
      {
        x: options.anchorPoint.x + (0.5 - anchorRatio.x) * nextSize.width,
        y: options.anchorPoint.y + (0.5 - anchorRatio.y) * nextSize.height,
      },
      nextSize.width,
      nextSize.height,
    );
    applyMapViewBox();
    return;
  }

  if (delta > 0 && mapZoomLevel === 0) {
    const candidate = latestResult ? selectedCandidate(latestResult) : null;
    if (candidate) {
      centerMapOnCandidate(candidate);
    }
  }
  mapZoomLevel = nextZoomLevel;
  applyMapViewBox();
}

function applyMapViewBox() {
  const viewBox = currentMapViewBox();
  mapViewCenter = { x: viewBox.x + viewBox.width / 2, y: viewBox.y + viewBox.height / 2 };
  mapSvg.setAttribute("viewBox", `${viewBox.x} ${viewBox.y} ${viewBox.width} ${viewBox.height}`);
  updateFixedMapSymbols();
  updateScaleBar();
  scheduleSlipImageRefresh(viewBox);
  zoomOutButton.disabled = mapZoomLevel <= MIN_MAP_ZOOM;
  zoomInButton.disabled = mapZoomLevel >= MAX_MAP_ZOOM;
  zoomResetButton.disabled = Math.abs(mapZoomLevel) < 0.001 && isDefaultMapCenter(mapViewCenter);
}

function updateScaleBar() {
  mapSvg.querySelectorAll(".scale-bar").forEach((node) => node.remove());
  renderScaleBar(mapSvg, latestResult ?? previewMapResult());
}

function currentMapViewBox() {
  const { width, height } = mapViewBoxSize(mapZoomLevel);
  const center = clampMapCenter(mapViewCenter, width, height);
  return {
    x: center.x - width / 2,
    y: center.y - height / 2,
    width,
    height,
  };
}

function mapViewBoxSize(zoomLevel) {
  const scale = 1 / Math.pow(1.45, zoomLevel);
  return {
    width: BASE_VIEWBOX.width * scale,
    height: BASE_VIEWBOX.height * scale,
  };
}

function clampMapCenter(center, width, height) {
  const limits = mapPanLimits(width, height);
  return {
    x: Math.max(limits.x.min, Math.min(limits.x.max, center.x)),
    y: Math.max(limits.y.min, Math.min(limits.y.max, center.y)),
  };
}

function mapPanLimits(width, height) {
  const bounds = currentMapBounds();
  if (!bounds) {
    return {
      x: centerLimitsForEdges(BASE_VIEWBOX.x, BASE_VIEWBOX.x + BASE_VIEWBOX.width, width),
      y: centerLimitsForEdges(BASE_VIEWBOX.y, BASE_VIEWBOX.y + BASE_VIEWBOX.height, height),
    };
  }
  const west = Number(bounds.west);
  const south = Number(bounds.south);
  const east = Number(bounds.east);
  const north = Number(bounds.north);
  const lonSpan = east - west;
  const latSpan = north - south;
  if ([west, south, east, north, lonSpan, latSpan].some((value) => !Number.isFinite(value)) || lonSpan <= 0 || latSpan <= 0) {
    return {
      x: centerLimitsForEdges(BASE_VIEWBOX.x, BASE_VIEWBOX.x + BASE_VIEWBOX.width, width),
      y: centerLimitsForEdges(BASE_VIEWBOX.y, BASE_VIEWBOX.y + BASE_VIEWBOX.height, height),
    };
  }
  const minX = ((WA_BOUNDS.west - west) / lonSpan) * BASE_VIEWBOX.width;
  const maxX = ((WA_BOUNDS.east - west) / lonSpan) * BASE_VIEWBOX.width;
  const minY = ((north - WA_BOUNDS.north) / latSpan) * BASE_VIEWBOX.height;
  const maxY = ((north - WA_BOUNDS.south) / latSpan) * BASE_VIEWBOX.height;
  return {
    x: centerLimitsForEdges(minX, maxX, width),
    y: centerLimitsForEdges(minY, maxY, height),
  };
}

function centerLimitsForEdges(minEdge, maxEdge, viewSize) {
  const minCenter = minEdge + viewSize / 2;
  const maxCenter = maxEdge - viewSize / 2;
  if (minCenter <= maxCenter) {
    return { min: minCenter, max: maxCenter };
  }
  return {
    min: maxEdge - viewSize / 2,
    max: minEdge + viewSize / 2,
  };
}

function defaultMapCenter() {
  return {
    x: BASE_VIEWBOX.x + BASE_VIEWBOX.width / 2,
    y: BASE_VIEWBOX.y + BASE_VIEWBOX.height / 2,
  };
}

function isDefaultMapCenter(center) {
  const defaultCenter = defaultMapCenter();
  return Math.abs(Number(center.x) - defaultCenter.x) < 0.001
    && Math.abs(Number(center.y) - defaultCenter.y) < 0.001;
}

function symbolScale() {
  return currentMapViewBox().width / BASE_VIEWBOX.width;
}

function updateFixedMapSymbols() {
  const scale = symbolScale();
  for (const symbol of mapSvg.querySelectorAll("[data-fixed-symbol='true']")) {
    const x = Number(symbol.dataset.x);
    const y = Number(symbol.dataset.y);
    if (!Number.isFinite(x) || !Number.isFinite(y)) continue;
    symbol.setAttribute("transform", `translate(${x} ${y}) scale(${scale})`);
  }
}

function updateSlipImageElementGeometry(image, viewBox) {
  image.setAttribute("x", viewBox.x);
  image.setAttribute("y", viewBox.y);
  image.setAttribute("width", viewBox.width);
  image.setAttribute("height", viewBox.height);
}

function scheduleSlipImageRefresh(viewBox) {
  if (!currentMapBounds()) return;
  const refreshToken = ++imageryRefreshToken;
  window.clearTimeout(imageryRefreshTimer);
  imageryRefreshTimer = window.setTimeout(() => {
    const sourceResult = latestResult ?? previewMapResult();
    for (const image of mapSvg.querySelectorAll("[data-slip-service]")) {
      const serviceKey = image.getAttribute("data-slip-service");
      const href = slipExportUrl(sourceResult, serviceKey, viewBox);
      if (!href) continue;
      if (!image.isConnected) continue;
      if (image.getAttribute("href") === href) {
        if (refreshToken === imageryRefreshToken) {
          updateSlipImageElementGeometry(image, viewBox);
        }
        continue;
      }
      preloadImage(href)
        .then(() => {
          if (refreshToken !== imageryRefreshToken || !image.isConnected) return;
          image.setAttribute("href", href);
          updateSlipImageElementGeometry(image, viewBox);
        })
        .catch(() => {
          if (refreshToken === imageryRefreshToken) {
            console.warn(`Map image failed to refresh for ${serviceKey}.`);
          }
        });
    }
  }, 80);
}

function preloadImage(src) {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve(src);
    image.onerror = reject;
    image.src = src;
  });
}

function centerMapOnCandidate(candidate) {
  if (!candidate) return;
  const x = Number(candidate.x) * BASE_VIEWBOX.width;
  const y = (1 - Number(candidate.y)) * BASE_VIEWBOX.height;
  if (!Number.isFinite(x) || !Number.isFinite(y)) return;
  const viewBox = currentMapViewBox();
  mapViewCenter = clampMapCenter({ x, y }, viewBox.width, viewBox.height);
}

function startMapPinch() {
  const touches = Array.from(activeMapPointers.values()).slice(0, 2);
  if (touches.length < 2) return;
  const center = midpoint(touches[0], touches[1]);
  mapPinch = {
    startDistance: Math.max(1, pointerDistance(touches[0], touches[1])),
    startZoom: mapZoomLevel,
    anchorPoint: clientToMapPoint(center.clientX, center.clientY),
  };
}

function updateMapPinch() {
  const touches = Array.from(activeMapPointers.values()).slice(0, 2);
  if (touches.length < 2 || !mapPinch) return;
  const center = midpoint(touches[0], touches[1]);
  const distance = Math.max(1, pointerDistance(touches[0], touches[1]));
  const nextZoomLevel = clamp(
    mapPinch.startZoom + Math.log(distance / mapPinch.startDistance) / Math.log(1.45),
    MIN_MAP_ZOOM,
    MAX_MAP_ZOOM,
  );
  const nextSize = mapViewBoxSize(nextZoomLevel);
  const anchorRatio = clientToMapRatio(center.clientX, center.clientY);
  mapZoomLevel = nextZoomLevel;
  mapViewCenter = clampMapCenter(
    {
      x: mapPinch.anchorPoint.x + (0.5 - anchorRatio.x) * nextSize.width,
      y: mapPinch.anchorPoint.y + (0.5 - anchorRatio.y) * nextSize.height,
    },
    nextSize.width,
    nextSize.height,
  );
  applyMapViewBox();
}

function pointerDistance(a, b) {
  return Math.hypot(Number(a.clientX) - Number(b.clientX), Number(a.clientY) - Number(b.clientY));
}

function midpoint(a, b) {
  return {
    clientX: (Number(a.clientX) + Number(b.clientX)) / 2,
    clientY: (Number(a.clientY) + Number(b.clientY)) / 2,
  };
}

function startMapPan(event) {
  hideMapContextMenu();
  if (event.button !== undefined && event.button !== 0) return;
  const vertex = event.target.closest?.(".target-draft-vertex");
  if (vertex) {
    startVertexDrag(event, vertex);
    return;
  }
  if (drawingCoverageArea || isInteractiveMapTarget(event.target)) return;
  activeMapPointers.set(event.pointerId, { clientX: event.clientX, clientY: event.clientY });
  if (mapSvg.setPointerCapture) {
    mapSvg.setPointerCapture(event.pointerId);
  }
  if (activeMapPointers.size === 2) {
    mapDrag = null;
    clearMapLongPress();
    startMapPinch();
    mapSvg.classList.add("is-panning");
    event.preventDefault();
    return;
  }
  if (activeMapPointers.size > 2) {
    event.preventDefault();
    return;
  }
  const viewBox = currentMapViewBox();
  mapDrag = {
    pointerId: event.pointerId,
    startX: event.clientX,
    startY: event.clientY,
    center: { ...mapViewCenter },
    viewBox,
    unitsPerPx: mapUnitsPerScreenPixel(viewBox),
    moved: false,
  };
  scheduleMapLongPress(event);
  mapSvg.classList.add("is-panning");
}

function isInteractiveMapTarget(target) {
  return Boolean(target?.closest?.(".candidate-marker, .target-draft-vertex"));
}

function updateMapPan(event) {
  if (vertexDrag && vertexDrag.pointerId === event.pointerId) {
    updateVertexDrag(event);
    return;
  }
  if (activeMapPointers.has(event.pointerId)) {
    activeMapPointers.set(event.pointerId, { clientX: event.clientX, clientY: event.clientY });
  }
  if (mapPinch && activeMapPointers.size >= 2) {
    updateMapPinch();
    event.preventDefault();
    return;
  }
  if (!mapDrag || mapDrag.pointerId !== event.pointerId) return;
  const dx = event.clientX - mapDrag.startX;
  const dy = event.clientY - mapDrag.startY;
  if (Math.hypot(dx, dy) > 3) {
    mapDrag.moved = true;
  }
  if (Math.hypot(dx, dy) > MAP_LONG_PRESS_CANCEL_PX) {
    clearMapLongPress(event.pointerId);
  }
  mapViewCenter = clampMapCenter(
    {
      x: mapDrag.center.x - dx * mapDrag.unitsPerPx,
      y: mapDrag.center.y - dy * mapDrag.unitsPerPx,
    },
    mapDrag.viewBox.width,
    mapDrag.viewBox.height,
  );
  applyMapViewBox();
  event.preventDefault();
}

function finishMapPan(event) {
  if (vertexDrag && vertexDrag.pointerId === event.pointerId) {
    finishVertexDrag(event);
    return;
  }
  const wasTracked = activeMapPointers.delete(event.pointerId);
  const wasPinching = Boolean(mapPinch);
  const longPressFired = Boolean(mapLongPress?.pointerId === event.pointerId && mapLongPress.fired);
  const moved = Boolean(mapDrag?.moved || wasPinching || longPressFired);
  clearMapLongPress(event.pointerId);
  if (mapDrag && mapDrag.pointerId === event.pointerId) {
    mapDrag = null;
  }
  if (activeMapPointers.size < 2) {
    mapPinch = null;
  }
  if (!wasTracked && !moved) return;
  if (moved) {
    suppressCandidateClickUntil = Date.now() + 250;
  }
  if (mapSvg.hasPointerCapture(event.pointerId)) {
    mapSvg.releasePointerCapture(event.pointerId);
  }
  if (activeMapPointers.size === 0) {
    mapSvg.classList.remove("is-panning");
  }
  scheduleSlipImageRefresh(currentMapViewBox());
}

function handleMapWheel(event) {
  if (!latestResult && !currentMapBounds()) return;
  hideMapContextMenu();
  event.preventDefault();
  zoomMap(event.deltaY < 0 ? 1 : -1, {
    anchorPoint: eventMapPoint(event),
    anchorRatio: clientToMapRatio(event.clientX, event.clientY),
  });
}

function startVertexDrag(event, vertex) {
  const index = Number(vertex.dataset.vertexIndex);
  if (!Number.isInteger(index) || index < 0 || index >= draftCoveragePolygon.length) return;
  vertexDrag = {
    pointerId: event.pointerId,
    index,
    moved: false,
  };
  vertex.classList.add("is-dragging");
  mapSvg.setPointerCapture(event.pointerId);
  event.preventDefault();
  event.stopPropagation();
}

function updateVertexDrag(event) {
  const point = eventMapPoint(event);
  draftCoveragePolygon[vertexDrag.index] = point;
  vertexDrag.moved = true;
  renderCurrentMap();
  event.preventDefault();
}

function finishVertexDrag(event) {
  if (mapSvg.hasPointerCapture(event.pointerId)) {
    mapSvg.releasePointerCapture(event.pointerId);
  }
  vertexDrag = null;
  suppressCandidateClickUntil = Date.now() + 250;
  updateDrawingControls();
  renderCurrentMap();
}

function scheduleMapLongPress(event) {
  if (event.pointerType !== "touch" && event.pointerType !== "pen") return;
  clearMapLongPress();
  mapLongPress = {
    pointerId: event.pointerId,
    clientX: event.clientX,
    clientY: event.clientY,
    target: event.target,
    fired: false,
    timer: window.setTimeout(() => {
      if (!mapLongPress || mapLongPress.pointerId !== event.pointerId || !activeMapPointers.has(event.pointerId)) return;
      if (activeMapPointers.size !== 1 || mapPinch) return;
      mapLongPress.fired = true;
      mapDrag = null;
      mapSvg.classList.remove("is-panning");
      suppressCandidateClickUntil = Date.now() + 500;
      openMapContextMenu(event.clientX, event.clientY, clientToMapPoint(event.clientX, event.clientY), event.target);
    }, MAP_LONG_PRESS_MS),
  };
}

function clearMapLongPress(pointerId = null) {
  if (!mapLongPress) return;
  if (pointerId !== null && mapLongPress.pointerId !== pointerId) return;
  window.clearTimeout(mapLongPress.timer);
  mapLongPress = null;
}

function handleMapContextMenu(event) {
  event.preventDefault();
  openMapContextMenu(event.clientX, event.clientY, eventMapPoint(event), event.target);
}

function openMapContextMenu(clientX, clientY, point, target) {
  const latLon = mapPointToLatLon(point);
  const vertex = target.closest?.(".target-draft-vertex");
  const vertexIndex = vertex ? Number(vertex.dataset.vertexIndex) : null;
  const clickedPolygon = Boolean(target.closest?.(".target, .target-draft, .target-draft-line"));
  contextMenuLocation = {
    lat: Number(clamp(latLon.lat, WA_BOUNDS.south, WA_BOUNDS.north).toFixed(6)),
    lon: Number(clamp(latLon.lon, WA_BOUNDS.west, WA_BOUNDS.east).toFixed(6)),
    vertexIndex: Number.isInteger(vertexIndex) ? vertexIndex : null,
    clickedPolygon,
  };
  contextClearRepeaterButton.hidden = !manualRepeaterSite;
  contextRenameRepeaterButton.hidden = !manualRepeaterSite;
  contextEditPolygonButton.hidden = !(clickedPolygon || targetPolygonForPayload().length >= 3);
  contextDeleteVertexButton.hidden = !Number.isInteger(contextMenuLocation.vertexIndex);
  showMapContextMenu(clientX, clientY);
}

function handleMapDoubleClick(event) {
  if (drawingCoverageArea || measureMode || isInteractiveMapTarget(event.target) || Date.now() < suppressCandidateClickUntil) return;
  event.preventDefault();
  const latLon = mapPointToLatLon(eventMapPoint(event));
  setManualRepeaterSite(latLon.lat, latLon.lon);
}

function showMapContextMenu(clientX, clientY) {
  if (!mapContextMenu) return;
  const sectionRect = mapSvg.closest(".map-section")?.getBoundingClientRect();
  if (!sectionRect) return;
  mapContextMenu.hidden = false;
  const left = clientX - sectionRect.left;
  const top = clientY - sectionRect.top;
  const maxLeft = Math.max(0, sectionRect.width - mapContextMenu.offsetWidth - 8);
  const maxTop = Math.max(0, sectionRect.height - mapContextMenu.offsetHeight - 8);
  mapContextMenu.style.left = `${Math.max(8, Math.min(maxLeft, left))}px`;
  mapContextMenu.style.top = `${Math.max(8, Math.min(maxTop, top))}px`;
}

function hideMapContextMenu() {
  if (mapContextMenu) {
    mapContextMenu.hidden = true;
  }
}

function beginCoveragePolygonEdit() {
  const sourcePolygon = draftCoveragePolygon.length >= 3
    ? draftPolygonLatLon()
    : normalisePolygonLl(activeCoveragePolygonLl).length >= 3
      ? normalisePolygonLl(activeCoveragePolygonLl)
      : resultPolygonLl(latestResult);
  if (sourcePolygon.length < 3) return;
  draftCoveragePolygon = sourcePolygon.map(([lat, lon]) => {
    const point = latLonToMapPoint(lat, lon);
    return {
      x: point.x * BASE_VIEWBOX.width,
      y: (1 - point.y) * BASE_VIEWBOX.height,
    };
  });
  drawingCoverageArea = false;
  setDrawToolsExpanded(true);
  updateDrawingControls();
  renderCurrentMap();
}

function deleteContextVertex() {
  if (!Number.isInteger(contextMenuLocation?.vertexIndex)) return;
  if (draftCoveragePolygon.length <= 3) {
    window.alert("A required coverage area needs at least 3 points. Use Clear to remove the whole area.");
    return;
  }
  draftCoveragePolygon.splice(contextMenuLocation.vertexIndex, 1);
  updateDrawingControls();
  renderCurrentMap();
}

function addDefs(svg) {
  const defs = el("defs");
  const pattern = el("pattern", { id: "grid", width: "40", height: "40", patternUnits: "userSpaceOnUse" });
  pattern.append(el("path", { d: "M 40 0 L 0 0 0 40", fill: "none", stroke: "#cfdae0", "stroke-width": "1" }));
  defs.append(pattern);
  svg.append(defs);
}

function addTopo(svg) {
  svg.append(el("rect", { x: 0, y: 0, width: 1000, height: 720, fill: "#dfe8e4" }));
  svg.append(el("rect", { x: 0, y: 0, width: 1000, height: 720, fill: "url(#grid)", opacity: 0.36 }));
}

function renderTerrain(svg, cells) {
  for (const cell of cells) {
    const x = cell.x * 1000;
    const y = (1 - cell.y) * 720;
    const shade = Math.max(0, Math.min(1, Number(cell.shade)));
    const color = terrainColor(shade);
    svg.append(el("rect", {
      x: x - 18,
      y: y - 17,
      width: 36,
      height: 34,
      fill: color,
      opacity: 0.52,
    }));
  }
}

function renderContours(svg, cells) {
  const grid = terrainGrid(cells);
  if (!grid) return;
  const elevations = cells.map((cell) => Number(cell.elevation_m)).filter(Number.isFinite);
  if (!elevations.length) return;
  const low = Math.min(...elevations);
  const high = Math.max(...elevations);
  const interval = contourInterval(high - low);
  const start = Math.ceil(low / interval) * interval;
  for (let level = start; level <= high; level += interval) {
    renderContourLevel(svg, grid, level);
  }
}

function terrainGrid(cells) {
  if (!cells?.length) return null;
  const xs = Array.from(new Set(cells.map((cell) => Number(cell.x)).filter(Number.isFinite))).sort((a, b) => a - b);
  const ys = Array.from(new Set(cells.map((cell) => Number(cell.y)).filter(Number.isFinite))).sort((a, b) => a - b);
  if (xs.length < 2 || ys.length < 2) return null;
  const byPoint = new Map();
  for (const cell of cells) {
    byPoint.set(`${Number(cell.x).toFixed(6)}:${Number(cell.y).toFixed(6)}`, cell);
  }
  const rows = ys.map((y) => xs.map((x) => byPoint.get(`${x.toFixed(6)}:${y.toFixed(6)}`)));
  if (rows.some((row) => row.some((cell) => !cell))) return null;
  return { xs, ys, rows };
}

function contourInterval(range) {
  if (range <= 80) return 10;
  if (range <= 220) return 25;
  return 50;
}

function renderContourLevel(svg, grid, level) {
  for (let row = 0; row < grid.rows.length - 1; row += 1) {
    for (let col = 0; col < grid.xs.length - 1; col += 1) {
      const corners = [
        grid.rows[row][col],
        grid.rows[row][col + 1],
        grid.rows[row + 1][col + 1],
        grid.rows[row + 1][col],
      ];
      const points = contourCrossings(corners, level);
      if (points.length < 2) continue;
      for (let index = 0; index + 1 < points.length; index += 2) {
        svg.append(el("line", {
          class: "contour-line",
          x1: points[index][0],
          y1: points[index][1],
          x2: points[index + 1][0],
          y2: points[index + 1][1],
        }));
      }
    }
  }
}

function contourCrossings(corners, level) {
  const points = [];
  const edges = [[0, 1], [1, 2], [2, 3], [3, 0]];
  for (const [start, end] of edges) {
    const a = corners[start];
    const b = corners[end];
    const aElevation = Number(a.elevation_m);
    const bElevation = Number(b.elevation_m);
    if (!Number.isFinite(aElevation) || !Number.isFinite(bElevation) || aElevation === bElevation) continue;
    if ((level < Math.min(aElevation, bElevation)) || (level > Math.max(aElevation, bElevation))) continue;
    const ratio = (level - aElevation) / (bElevation - aElevation);
    const x = (Number(a.x) + (Number(b.x) - Number(a.x)) * ratio) * 1000;
    const y = (1 - (Number(a.y) + (Number(b.y) - Number(a.y)) * ratio)) * 720;
    points.push([x, y]);
  }
  return points;
}

function renderCoverage(svg, cells) {
  for (const cell of cells) {
    const x = cell.x * 1000;
    const y = (1 - cell.y) * 720;
    const color = marginColor(cell.margin_db);
    svg.append(el("rect", {
      class: "coverage-cell",
      x: x - 13,
      y: y - 13,
      width: 26,
      height: 26,
      fill: color,
      rx: 2,
    }));
  }
}

function renderMeasurement(svg) {
  if (!measurePoints.length) return;
  if (measurePoints.length >= 2) {
    addPolyline(svg, measurePoints.map((point) => [point.x / BASE_VIEWBOX.width, 1 - point.y / BASE_VIEWBOX.height]), "measure-line");
  }
  for (const [index, point] of measurePoints.entries()) {
    const group = el("g", {
      class: "measure-point",
      "data-fixed-symbol": "true",
      "data-x": point.x,
      "data-y": point.y,
      transform: `translate(${point.x} ${point.y}) scale(${symbolScale()})`,
    });
    group.append(el("circle", { cx: 0, cy: 0, r: 5 }));
    const text = el("text", { x: 9, y: -8 });
    text.textContent = index + 1;
    group.append(text);
    svg.append(group);
  }
  if (measurePoints.length >= 2) {
    const last = measurePoints[measurePoints.length - 1];
    const label = el("text", {
      class: "measure-label",
      "data-fixed-symbol": "true",
      "data-x": last.x,
      "data-y": last.y,
      transform: `translate(${last.x} ${last.y}) scale(${symbolScale()})`,
      x: 12,
      y: 18,
    });
    label.textContent = formatMetric(measurementDistanceKm(), "km", 2);
    svg.append(label);
  }
}

function renderScaleBar(svg, result) {
  const viewBox = currentMapViewBox();
  const bounds = mapBoundsForViewBox(result, viewBox);
  if (!bounds) return;
  const yRatio = 0.92;
  const centerLat = (bounds.north + bounds.south) / 2;
  const visibleWidthKm = haversineDistanceKm(centerLat, bounds.west, centerLat, bounds.east);
  const targetKm = niceScaleDistanceKm(visibleWidthKm / 4);
  if (!Number.isFinite(targetKm) || targetKm <= 0) return;
  const barWidth = viewBox.width * (targetKm / Math.max(0.001, visibleWidthKm));
  const x = viewBox.x + viewBox.width * 0.06;
  const y = viewBox.y + viewBox.height * yRatio;
  const group = el("g", { class: "scale-bar" });
  group.append(el("line", { x1: x, y1: y, x2: x + barWidth, y2: y }));
  group.append(el("line", { x1: x, y1: y - 5 * symbolScale(), x2: x, y2: y + 5 * symbolScale() }));
  group.append(el("line", { x1: x + barWidth, y1: y - 5 * symbolScale(), x2: x + barWidth, y2: y + 5 * symbolScale() }));
  const text = el("text", {
    x: x + barWidth / 2,
    y: y - 10 * symbolScale(),
    "font-size": 12 * symbolScale(),
    "text-anchor": "middle",
  });
  text.textContent = targetKm < 1 ? `${Math.round(targetKm * 1000)} m` : `${formatMetric(targetKm, "km", targetKm < 10 ? 1 : 0)}`;
  group.append(text);
  svg.append(group);
}

function renderDisplayRoads(roads, minorRoadLayer, trailLayer) {
  for (const road of roads) {
    const points = road.points ?? [];
    if (points.length < 2) continue;
    if (road.kind === "trail") {
      addRoadVector(trailLayer, points, "trail-road-shadow");
      addRoadVector(trailLayer, points, "trail-road", road.name);
      continue;
    }
    if (road.kind === "minor") {
      addRoadVector(minorRoadLayer, points, "minor-road-shadow");
      addRoadVector(minorRoadLayer, points, road.highway === "track" ? "track-road" : "minor-road", road.name);
    }
  }
}

function handleMapClick(event) {
  if (Date.now() < suppressCandidateClickUntil) return;
  if (measureMode) {
    if (event.target.closest?.(".map-controls")) return;
    addMeasurePoint(eventMapPoint(event));
    return;
  }
  if (!drawingCoverageArea) return;
  if (event.target.closest?.(".map-controls")) return;
  draftCoveragePolygon.push(eventMapPoint(event));
  updateDrawingControls();
  renderCurrentMap();
}

function setDrawToolsExpanded(expanded) {
  drawToolsExpanded = Boolean(expanded);
  if (drawToolsExpanded && mobileMapQuery.matches) {
    setMapToolsExpanded(true);
  }
  if (!drawToolsExpanded) {
    drawingCoverageArea = false;
  }
  updateDrawingControls();
}

function setMeasureToolsExpanded(expanded) {
  measureToolsExpanded = Boolean(expanded);
  if (measureToolsExpanded && mobileMapQuery.matches) {
    setMapToolsExpanded(true);
  }
  if (!measureToolsExpanded) {
    measureMode = null;
  }
  updateMeasureControls();
}

function setMeasureMode(mode) {
  measureMode = mode;
  if (measureMode) {
    drawingCoverageArea = false;
    setMeasureToolsExpanded(true);
  }
  updateDrawingControls();
  updateMeasureControls();
}

function addMeasurePoint(point) {
  if (!measureMode) return;
  if (measureMode === "line" && measurePoints.length >= 2) {
    measurePoints = [];
  }
  measurePoints.push(point);
  if (measureMode === "line" && measurePoints.length >= 2) {
    measureMode = null;
  }
  updateMeasureControls();
  renderCurrentMap();
}

function updateMeasureControls() {
  if (!measureToolsToggle || !measureToolsPanel || !measureControl) return;
  measureToolsToggle.setAttribute("aria-expanded", String(measureToolsExpanded));
  measureToolsPanel.hidden = !measureToolsExpanded;
  measureControl.classList.toggle("collapsed", !measureToolsExpanded);
  measureLineButton?.classList.toggle("active", measureMode === "line");
  measureTrackButton?.classList.toggle("active", measureMode === "track");
  const hasPoints = measurePoints.length > 0;
  if (finishMeasureButton) finishMeasureButton.disabled = !measureMode;
  if (clearMeasureButton) clearMeasureButton.disabled = !hasPoints && !measureMode;
  if (!measureStatus) return;
  const distance = measurementDistanceKm();
  if (measureMode === "line") {
    measureStatus.textContent = measurePoints.length === 0
      ? "Click start and end points"
      : measurePoints.length === 1
        ? "Click end point"
        : `Line ${formatMetric(distance, "km", 2)}`;
  } else if (measureMode === "track") {
    measureStatus.textContent = measurePoints.length <= 1
      ? `${measurePoints.length} point`
      : `Track ${formatMetric(distance, "km", 2)} across ${measurePoints.length} points`;
  } else if (measurePoints.length >= 2) {
    measureStatus.textContent = `${measurePoints.length === 2 ? "Line" : "Track"} ${formatMetric(distance, "km", 2)}`;
  } else {
    measureStatus.textContent = "No measurement";
  }
}

function updateDrawingControls() {
  drawToolsToggle.setAttribute("aria-expanded", String(drawToolsExpanded));
  drawToolsPanel.hidden = !drawToolsExpanded;
  drawControl.classList.toggle("collapsed", !drawToolsExpanded);
  drawAreaButton.classList.toggle("active", drawingCoverageArea);
  drawAreaButton.textContent = "";
  drawAreaButton.append(toolIcon("polygon"));
  drawAreaButton.append(drawingCoverageArea ? " Drawing" : " Draw area");
  finishAreaButton.disabled = draftCoveragePolygon.length < 3;
  clearAreaButton.disabled = draftCoveragePolygon.length === 0 && activeCoveragePolygonLl.length < 3;
  const pointCount = draftCoveragePolygon.length;
  if (drawingCoverageArea) {
    const areaText = pointCount >= 3 ? ` · ${formatMetric(targetAreaSqKm(draftPolygonLatLon()), "km2", 2)}` : "";
    drawStatus.textContent = `${pointCount} ${pointCount === 1 ? "point" : "points"}${areaText}`;
  } else if (pointCount >= 3) {
    drawStatus.textContent = `${pointCount}-point target area · ${formatMetric(targetAreaSqKm(draftPolygonLatLon()), "km2", 2)}`;
  } else if (activeCoveragePolygonLl.length >= 3) {
    drawStatus.textContent = `${activeCoveragePolygonLl.length}-point target area active · ${formatMetric(targetAreaSqKm(activeCoveragePolygonLl), "km2", 2)}`;
  } else {
    drawStatus.textContent = "No drawn area";
  }
}

function toolIcon(type) {
  const svg = el("svg", { viewBox: "0 0 24 24", "aria-hidden": "true" });
  if (type === "polygon") {
    svg.append(el("path", { d: "M5 6l6-3 8 5-2 9-9 3-5-7Z" }));
    svg.append(el("path", { d: "M5 6l3 14" }));
    svg.append(el("path", { d: "M19 8l-11 12" }));
  }
  return svg;
}

function addRoadVector(svg, points, className, label = "") {
  const pointsText = points.map(([x, y]) => `${x * 1000},${(1 - y) * 720}`).join(" ");
  const attrs = { points: pointsText, class: className };
  if (label) attrs["aria-label"] = label;
  svg.append(el("polyline", attrs));
}

function addPolyline(svg, points, className) {
  const pointsText = points.map(([x, y]) => `${x * 1000},${(1 - y) * 720}`).join(" ");
  svg.append(el("polyline", { points: pointsText, class: className }));
}

function addPolygon(svg, polygon, className) {
  if (!Array.isArray(polygon) || polygon.length < 3) return;
  const pointsText = polygon.map(([x, y]) => `${x * 1000},${(1 - y) * 720}`).join(" ");
  svg.append(el("polygon", { points: pointsText, class: className }));
}

function renderDraftCoverageArea(svg) {
  if (!draftCoveragePolygon.length) return;
  const points = draftCoveragePolygon.map((point) => [point.x / BASE_VIEWBOX.width, 1 - point.y / BASE_VIEWBOX.height]);
  if (points.length >= 3) {
    addPolygon(svg, points, "target-draft");
  }
  if (points.length >= 2) {
    addPolyline(svg, points, "target-draft-line");
  }
  for (const [index, point] of draftCoveragePolygon.entries()) {
    const vertex = el("g", {
      class: "target-draft-vertex",
      "data-fixed-symbol": "true",
      "data-vertex-index": index,
      "data-x": point.x,
      "data-y": point.y,
      transform: `translate(${point.x} ${point.y}) scale(${symbolScale()})`,
    });
    vertex.append(el("circle", { cx: 0, cy: 0, r: 5 }));
    svg.append(vertex);
  }
}

function addCandidate(svg, candidate, isSelected) {
  const x = candidate.x * 1000;
  const y = (1 - candidate.y) * 720;
  const group = el("g", {
    class: `candidate-marker${isSelected ? " selected" : ""}`,
    "data-fixed-symbol": "true",
    "data-x": x,
    "data-y": y,
    transform: `translate(${x} ${y}) scale(${symbolScale()})`,
    tabindex: "0",
    role: "button",
    "aria-label": `Show coverage for ${candidate.name}`,
  });
  group.addEventListener("click", (event) => {
    handleCandidatePointerClick(candidate.candidate_id, event);
  });
  group.addEventListener("pointerdown", (event) => {
    event.stopPropagation();
  });
  group.addEventListener("dblclick", (event) => {
    event.preventDefault();
    event.stopPropagation();
    window.clearTimeout(candidateClickTimer);
    candidateClickTimer = null;
    zoomToCandidate(candidate.candidate_id);
  });
  group.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      selectCandidate(candidate.candidate_id);
    }
  });
  group.append(el("circle", {
    class: "candidate-hit-target",
    cx: 0,
    cy: 0,
    r: 30,
    fill: "transparent",
    "pointer-events": "all",
    "aria-hidden": "true",
  }));
  group.append(el("circle", { cx: 0, cy: 0, r: isSelected ? 20 : 17, fill: "#18323d", stroke: "#fff", "stroke-width": 3 }));
  const text = el("text", { x: 0, y: 4, "text-anchor": "middle", fill: "#fff", "font-size": "13", "font-weight": "800" });
  text.textContent = candidate.rank;
  group.append(text);
  const label = el("text", { x: 22, y: -18, fill: "#172126", "font-size": "12", "font-weight": "750" });
  label.textContent = candidate.name;
  group.append(label);
  svg.append(group);
}

function addManualRepeaterMarker(svg, result) {
  if (!manualRepeaterSite) return;
  const bounds = result?.metadata?.region_bounds ?? currentMapBounds();
  if (!bounds) return;
  const point = latLonToMapPoint(manualRepeaterSite.lat, manualRepeaterSite.lon, bounds);
  const x = point.x * 1000;
  const y = (1 - point.y) * 720;
  const group = el("g", {
    class: "manual-marker",
    "data-fixed-symbol": "true",
    "data-x": x,
    "data-y": y,
    transform: `translate(${x} ${y}) scale(${symbolScale()})`,
  });
  group.append(el("circle", { cx: 0, cy: 0, r: 15 }));
  group.append(el("path", { d: "M-9 0H9M0 -9V9" }));
  const label = el("text", { x: 19, y: -15 });
  label.textContent = manualRepeaterSite.name || DEFAULT_MANUAL_REPEATER_NAME;
  group.append(label);
  svg.append(group);
}

function addTargetCenter(svg, target) {
  const x = target.x * 1000;
  const y = (1 - target.y) * 720;
  const group = el("g", {
    class: "target-center",
    "data-fixed-symbol": "true",
    "data-x": x,
    "data-y": y,
    transform: `translate(${x} ${y}) scale(${symbolScale()})`,
  });
  group.append(el("circle", { cx: 0, cy: 0, r: 8 }));
  group.append(el("path", { d: "M-16 0H16M0 -16V16" }));
  const label = el("text", { x: 14, y: 22, "font-size": "12", "font-weight": "800" });
  const elevation = Number(target.elevation_m);
  label.textContent = Number.isFinite(elevation) ? `target ${elevation.toFixed(0)} m` : "target";
  group.append(label);
  svg.append(group);
}

function candidateOperationalCall(candidate) {
  if (candidate.service_ok) {
    return candidate.service_status;
  }
  if (candidate.uplink_status === "poor") {
    return `Do not rely on ${talkbackRadioLabel().toLowerCase()} talkback`;
  }
  return candidate.service_status || "field verification required";
}

function candidateAccessSummary(candidate) {
  const accessRoad = candidate.road_name && candidate.road_name !== "unknown" ? candidate.road_name : `${candidate.road_class} road/track`;
  const referenceRoad = candidate.reference_road_name && !/^unnamed|mapped access|roads unavailable$/i.test(candidate.reference_road_name)
    ? candidate.reference_road_name
    : "";
  const location = referenceRoad && referenceRoad !== accessRoad
    ? `Near ${referenceRoad}; mapped access is ${accessRoad}`
    : `Near ${accessRoad}`;
  const surface = candidate.surface && candidate.surface !== "unknown" ? `, ${candidate.surface} surface` : ", surface unknown";
  const edgeDistance = Number(candidate.target_edge_distance_km);
  const edgeText = Number.isFinite(edgeDistance)
    ? candidate.target_inside_area
      ? " Inside required coverage area."
      : ` ${formatMetric(edgeDistance, "km")} from target edge.`
    : "";
  return `${sentenceCase(candidate.access_class)}.${edgeText} ${location} (${candidate.road_class}${surface}).`;
}

function candidateTerrainSummary(candidate) {
  return `${terrainType(candidate)}: ${formatMetric(candidate.elevation_m, "m")} AMSL, ${formatSignedMetric(candidate.height_above_target_m, "m")} vs target, ${formatMetric(candidate.local_relief_m, "m")} local relief, ${formatMetric(candidate.slope_deg, "deg")} slope.`;
}

function candidateDeploymentChecks(candidate) {
  const checks = latestResult?.deployment_profile?.site_checks ?? [];
  const checkText = checks.slice(0, 4).join(", ");
  if (!checkText) return candidate.deployment_warning || "Confirm site access, setup area, and safety controls.";
  return `${candidate.deployment_warning || "Field verification required."} Check: ${checkText}.`;
}

function candidateDataBasis(candidate) {
  const terrain = latestResult?.metadata?.terrain ?? "terrain data";
  const roads = latestResult?.metadata?.roads?.dataset ?? "road/track data";
  return `${candidate.confidence} confidence. ${roads}; ${terrain}.`;
}

function targetAreaForResult(result = latestResult) {
  const area = Number(result?.metadata?.target_area?.area_sq_km ?? result?.rf_profile?.target_area_sq_km);
  return Number.isFinite(area) ? area : null;
}

function terrainType(candidate) {
  const relief = Number(candidate.local_relief_m);
  const slope = Number(candidate.slope_deg);
  if (!Number.isFinite(relief) || !Number.isFinite(slope)) return "Terrain type unknown";
  if (relief >= 40 && slope <= 6) return "High ground / broad ridge";
  if (relief >= 25 && slope <= 10) return "Rising high ground";
  if (slope >= 15) return "Steep hillside";
  if (slope >= 8) return "Moderate slope";
  return "Gentle ground";
}

function talkbackRadioLabel() {
  return latestResult?.rf_profile?.user_radio === "mobile" ? "Mobile" : "Portable";
}

function sitePreferenceLabel(value) {
  if (value === "favour_inside_area") return "inside area, fallback outside";
  return "edge / outside area";
}

function statusClass(value) {
  return value === "ok" ? "ok" : "warn";
}

function formatMetric(value, unit, decimals = 1) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "n/a";
  if (unit === "deg") return `${number.toFixed(decimals)}°`;
  if (unit === "dB") return `${number.toFixed(decimals)} dB`;
  if (unit === "%") return `${number.toFixed(decimals)}%`;
  if (unit === "km2") return `${number.toFixed(decimals)} sq km`;
  return `${number.toFixed(decimals)} ${unit}`;
}

function formatCoordinate(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number.toFixed(4) : "n/a";
}

function formatSignedMetric(value, unit, decimals = 1) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "n/a";
  const sign = number > 0 ? "+" : "";
  return `${sign}${formatMetric(number, unit, decimals)}`;
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    "\"": "&quot;",
    "'": "&#39;",
  }[char]));
}

function sentenceCase(value) {
  const text = String(value ?? "").trim();
  if (!text) return "";
  return `${text.charAt(0).toUpperCase()}${text.slice(1)}`;
}

function renderCandidates(candidates) {
  const list = document.querySelector("#candidate-list");
  list.replaceChildren();
  if (!candidates?.length) {
    renderEmptySearchResults("No candidate sites returned.");
    return;
  }
  for (const candidate of candidates ?? []) {
    const item = document.createElement("article");
    const isSelected = candidate.candidate_id === selectedCandidateId;
    item.className = `candidate${isSelected ? " selected" : ""}`;
    item.tabIndex = 0;
    item.setAttribute("role", "button");
    item.setAttribute("aria-label", `Show coverage for ${candidate.name}`);
    const operationalCall = candidateOperationalCall(candidate);
    const isExpanded = expandedCandidateIds.has(candidate.candidate_id);
    const targetArea = targetAreaForResult();
    item.innerHTML = `
      <div class="candidate-head">
        <div>
          <span class="rank">${escapeHtml(candidate.rank)}</span>
          <div class="candidate-title-row">
            <h3>${escapeHtml(candidate.name)}</h3>
            <button class="candidate-rename icon-button" type="button" title="Rename repeater site" aria-label="Rename ${escapeHtml(candidate.name)}">
              <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 20h9" /><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z" /></svg>
            </button>
          </div>
          <small>${escapeHtml(candidate.lat)}, ${escapeHtml(candidate.lon)} · ${escapeHtml(formatMetric(candidate.elevation_m, "m"))} AMSL</small>
        </div>
        <div class="score" title="Suitability score">${escapeHtml(candidate.suitability_score)}</div>
      </div>
      <button class="service-status candidate-expand ${candidate.service_ok ? "ok" : "warn"}" type="button" aria-expanded="${isExpanded}" aria-label="${isExpanded ? "Collapse" : "Expand"} details for ${escapeHtml(candidate.name)}">
        <span>${escapeHtml(operationalCall)}</span>
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m9 18 6-6-6-6" /></svg>
      </button>
      <div class="candidate-expanded" ${isExpanded ? "" : "hidden"}>
        <div class="candidate-brief">
          <section>
            <h4>Access & terrain</h4>
            <p>${escapeHtml(candidateAccessSummary(candidate))}</p>
            <p>${escapeHtml(candidateTerrainSummary(candidate))}</p>
          </section>
          <section>
            <h4>Deployment checks</h4>
            <p>${escapeHtml(candidateDeploymentChecks(candidate))}</p>
          </section>
        </div>
        <div class="metric-grid operational-metrics">
          <div class="metric"><span>Two-way area</span><strong>${escapeHtml(formatMetric(candidate.coverage_pct, "%"))}</strong></div>
          <div class="metric"><span>Required area</span><strong>${escapeHtml(targetArea === null ? "n/a" : formatMetric(targetArea, "km2", 2))}</strong></div>
          <div class="metric"><span>${escapeHtml(talkbackRadioLabel())} talkback</span><strong>${escapeHtml(formatMetric(candidate.uplink_coverage_pct, "%"))}</strong></div>
          <div class="metric"><span>Strong area</span><strong>${escapeHtml(formatMetric(candidate.strong_signal_pct, "%"))}</strong></div>
          <div class="metric"><span>Weak / unusable</span><strong>${escapeHtml(formatMetric((Number(candidate.weak_signal_pct) || 0) + (Number(candidate.unusable_signal_pct) || 0), "%"))}</strong></div>
          <div class="metric"><span>Talkback margin</span><strong>${escapeHtml(formatMetric(candidate.uplink_median_margin_db, "dB"))}</strong></div>
          <div class="metric"><span>Downlink margin</span><strong>${escapeHtml(formatMetric(candidate.downlink_median_margin_db, "dB"))}</strong></div>
        </div>
        <div class="tags">
          <span class="tag caution">${escapeHtml(candidate.recommendation_label ?? "best available — verify")}</span>
          <span class="tag ${candidate.confidence === "low" ? "caution" : ""}">${escapeHtml(candidate.confidence)} confidence</span>
          <span class="tag ${candidate.service_profile === "Engineering sensitivity" ? "caution" : ""}">${escapeHtml(candidate.service_profile)}</span>
          <span class="tag">${escapeHtml(candidate.target_inside_area ? "inside area" : "edge/outside")}</span>
          <span class="tag ${statusClass(candidate.downlink_status)}">downlink ${escapeHtml(candidate.downlink_status)}</span>
          <span class="tag ${statusClass(candidate.uplink_status)}">talkback ${escapeHtml(candidate.uplink_status)}</span>
        </div>
        <details class="candidate-details">
          <summary>Assumptions and cautions</summary>
          <p>${escapeHtml(candidate.warnings || "Field verification required.")}</p>
          <p>${escapeHtml(candidateDataBasis(candidate))}</p>
          <p>${escapeHtml((candidate.explanation ?? []).join(" "))}</p>
        </details>
      </div>
    `;
    const expandButton = item.querySelector(".candidate-expand");
    const renameButton = item.querySelector(".candidate-rename");
    renameButton?.addEventListener("click", (event) => {
      event.stopPropagation();
      renameCandidate(candidate.candidate_id);
    });
    renameButton?.addEventListener("dblclick", (event) => {
      event.stopPropagation();
    });
    expandButton?.addEventListener("click", (event) => {
      event.stopPropagation();
      toggleCandidateExpanded(candidate.candidate_id);
    });
    expandButton?.addEventListener("dblclick", (event) => {
      event.stopPropagation();
    });
    item.addEventListener("click", () => selectCandidate(candidate.candidate_id));
    item.addEventListener("dblclick", () => zoomToCandidate(candidate.candidate_id));
    item.addEventListener("keydown", (event) => {
      if (event.target.closest?.(".candidate-expand")) return;
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        selectCandidate(candidate.candidate_id);
      }
    });
    list.append(item);
  }
}

function toggleCandidateExpanded(candidateId) {
  if (expandedCandidateIds.has(candidateId)) {
    expandedCandidateIds.delete(candidateId);
  } else {
    expandedCandidateIds.add(candidateId);
  }
  renderCandidates(latestResult?.candidates ?? []);
}

function renderEmptySearchResults(message) {
  const list = document.querySelector("#candidate-list");
  list.replaceChildren();
  const empty = document.createElement("p");
  empty.className = "search-empty";
  empty.textContent = message;
  list.append(empty);
}

function marginColor(margin) {
  if (margin < 0) return "#c34f3f";
  if (margin < 8) return "#414487";
  if (margin < 18) return "#2a788e";
  return "#7ad151";
}

function terrainColor(shade) {
  if (shade < 0.2) return "#cddfd5";
  if (shade < 0.4) return "#b9d0bf";
  if (shade < 0.6) return "#a9bd9f";
  if (shade < 0.8) return "#b5ae86";
  return "#9d9675";
}

function el(name, attrs = {}) {
  const node = document.createElementNS(SVG_NS, name);
  for (const [key, value] of Object.entries(attrs)) {
    node.setAttribute(key, value);
  }
  return node;
}

applyQueryParams();
if (coordinateFormatSelect.value === "mgrs" && targetMgrsInput.value.trim()) {
  syncCoordinateInputs(false);
} else {
  normaliseCoordinateInput(targetLatInput);
  normaliseCoordinateInput(targetLonInput);
  updateMgrsFromLatLon();
}
updateCoordinateFields(false);
updateMapToolsControls();
updateMobilePanelControls();
initialiseAuth().then((authenticated) => {
  if (!authenticated) return;
  renderEmptyMap();
  refreshSavedResults();
}).catch((error) => {
  console.error(error);
  showSignedOut("Authentication failed to initialize.", true);
});
