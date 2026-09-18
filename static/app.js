const $ = (id) => document.getElementById(id);
const defaults = {
  ...window.ADVANCED.defaults,
  exposure: 0,
  contrast: 0,
  highlights: 0,
  shadows: 0,
  whites: 0,
  blacks: 0,
  temperature: 0,
  tint: 0,
  vibrance: 0,
  saturation: 0,
  clarity: 0,
  sharpness: 0,
  vignette: 0,
  rotation: 0,
  crop: "original",
  monochrome: false,
};
let photos = [],
  current = null,
  settings = { ...defaults },
  history = [],
  future = [],
  previewVersion = 0,
  previewURL = null,
  before = false,
  timer,
  toastTimer,
  saveChain = Promise.resolve();
let custom = [];
try {
  custom = JSON.parse(localStorage.getItem("lightloom-presets") || "[]");
} catch {}
const builtins = [
  {
    name: "내추럴 라이트",
    sub: "Natural · 부드럽고 자연스럽게",
    colors: ["#a8b8b0", "#82725b"],
    settings: { exposure: 0.15, highlights: -25, shadows: 20, vibrance: 12 },
  },
  {
    name: "골든 아워",
    sub: "Warm · 따뜻한 오후의 빛",
    colors: ["#d1ab74", "#866644"],
    settings: {
      temperature: 28,
      tint: 5,
      highlights: -30,
      shadows: 12,
      vibrance: 15,
    },
  },
  {
    name: "시네마틱",
    sub: "Cinema · 깊이 있는 순간",
    colors: ["#7f9697", "#304c4d"],
    settings: {
      contrast: 25,
      temperature: -12,
      highlights: -30,
      shadows: 10,
      saturation: -18,
      vignette: -24,
    },
  },
  {
    name: "소프트 필름",
    sub: "Film · 은은한 아날로그 감성",
    colors: ["#b5aa9b", "#777c69"],
    settings: {
      contrast: -15,
      blacks: 22,
      highlights: -25,
      saturation: -12,
      temperature: 10,
    },
  },
  {
    name: "포레스트",
    sub: "Nature · 차분한 녹색의 결",
    colors: ["#849583", "#344e3d"],
    settings: {
      temperature: -10,
      tint: -18,
      contrast: 12,
      highlights: -20,
      vibrance: 20,
    },
  },
  {
    name: "모노크롬",
    sub: "B&W · 빛과 그림자의 이야기",
    colors: ["#b0b0ae", "#454b4b"],
    settings: { monochrome: true, contrast: 22, highlights: -20, blacks: -10 },
  },
];
const groups = [
  [
    "빛",
    [
      ["exposure", "노출", -5, 5, 0.05],
      ["contrast", "대비"],
      ["highlights", "밝은 영역"],
      ["shadows", "어두운 영역"],
      ["whites", "흰색 계열"],
      ["blacks", "검정 계열"],
    ],
  ],
  [
    "색상",
    [
      ["temperature", "색온도"],
      ["tint", "색조"],
      ["vibrance", "생동감"],
      ["saturation", "채도"],
    ],
  ],
  [
    "효과 및 디테일",
    [
      ["clarity", "부분 대비"],
      ["sharpness", "선명도", 0, 150, 1],
      ["vignette", "비네팅"],
    ],
  ],
];
groups.push(...window.ADVANCED.groups);
function toast(text, action) {
  $("toastText").textContent = text;
  const button = $("toastAction");
  button.hidden = !action;
  if (action) {
    button.textContent = action.label;
    button.onclick = () => {
      hideToast();
      action.run();
    };
  }
  $("toast").hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(hideToast, action ? 12000 : 6500);
}
function hideToast() {
  clearTimeout(toastTimer);
  $("toast").hidden = true;
}
$("toastClose").onclick = hideToast;

// The native shell exposes file dialogs and Finder/Explorer through this bridge.
const shell = { api: null };
function attachShell() {
  if (shell.api || !window.pywebview?.api) return;
  shell.api = window.pywebview.api;
  document.body.classList.add("desktop");
}
window.addEventListener("pywebviewready", attachShell);
attachShell();
async function api(url, options = {}) {
  const res = await fetch(url, options);
  if (!res.ok) {
    let msg;
    try {
      msg = (await res.json()).detail;
    } catch {
      msg = "요청을 처리하지 못했습니다.";
    }
    throw Error(typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  return res;
}
const json = (method, body) => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});
function busy(on, text = "사진을 현상하고 있습니다") {
  $("loading").hidden = !on;
  $("loadingText").textContent = text;
  for (const id of [
    "importTop",
    "emptyImport",
    "addPhoto",
    "importPreset",
    "xmpButton",
  ])
    $(id).disabled = on;
}
for (const [name, rows] of groups) {
  const details = document.createElement("details");
  details.open = ["빛", "색상", "효과 및 디테일"].includes(name);
  const summary = document.createElement("summary");
  summary.textContent = name;
  details.append(summary);
  for (const [key, label, min = -100, max = 100, step = 1] of rows) {
    const div = document.createElement("div");
    div.className = `slider ${key}`;
    div.innerHTML = `<label for="s-${key}">${label}<output id="v-${key}">0</output></label><input type="range" id="s-${key}" min="${min}" max="${max}" step="${step}" value="0" title="두 번 클릭하면 기본값으로 되돌립니다">`;
    details.append(div);
    const input = div.querySelector("input");
    input.addEventListener("pointerdown", () => checkpoint());
    input.addEventListener("keydown", (e) => {
      if (e.key.startsWith("Arrow")) checkpoint();
    });
    input.addEventListener("input", () => {
      if (!current) return;
      settings[key] = Number(input.value);
      constrainAdjustment(key);
      before = false;
      $("compare").classList.remove("active");
      syncControls();
      schedulePreview();
    });
    input.addEventListener("change", () => persist());
    input.addEventListener("dblclick", () => {
      if (!current) return;
      checkpoint();
      settings[key] = defaults[key];
      constrainAdjustment(key);
      changed();
    });
  }
  $("controls").append(details);
}
function constrainAdjustment(key) {
  // Preserve ordered ranges while dragging related controls.
  if (key === "shadow_split")
    settings[key] = Math.min(settings[key], settings.midtone_split - 1);
  if (key === "midtone_split")
    settings[key] = Math.max(
      settings.shadow_split + 1,
      Math.min(settings[key], settings.highlight_split - 1),
    );
  if (key === "highlight_split")
    settings[key] = Math.max(settings[key], settings.midtone_split + 1);
  for (const color of ["purple", "green"]) {
    if (key === `defringe_${color}_lo`)
      settings[key] = Math.min(
        settings[key],
        settings[`defringe_${color}_hi`] - 1,
      );
    if (key === `defringe_${color}_hi`)
      settings[key] = Math.max(
        settings[key],
        settings[`defringe_${color}_lo`] + 1,
      );
  }
}
function syncControls() {
  syncCurve();
  for (const [key, value] of Object.entries(settings)) {
    if ($("s-" + key)) {
      $("s-" + key).value = value;
      $("v-" + key).textContent =
        key === "exposure"
          ? (value > 0 ? "+" : "") + value.toFixed(2)
          : (value > 0 ? "+" : "") + Number(value.toFixed(1));
      if (key === "vignette_style")
        $("v-" + key).textContent = ["명부 우선", "색상 우선", "페인트"][
          Math.round(value)
        ];
    }
  }
  $("crop").value = settings.crop;
  $("mono").textContent = settings.monochrome ? "흑백 · sRGB" : "컬러 · sRGB";
  $("mono").setAttribute("aria-pressed", String(settings.monochrome));
  $("compare").setAttribute("aria-pressed", String(before));
  $("undo").disabled = !history.length;
  $("redo").disabled = !future.length;
  document
    .querySelectorAll("#controls input")
    .forEach((i) => (i.disabled = !current));
  for (const id of [
    "rotate",
    "crop",
    "mono",
    "reset",
    "compare",
    "exportTop",
    "zoom",
    "fit",
    "zoomIn",
    "zoomOut",
    "infoButton",
  ])
    $(id).disabled = !current;
  markTouchedPanels();
}
function sameValue(a, b) {
  return Array.isArray(a) ? JSON.stringify(a) === JSON.stringify(b) : a === b;
}
// A dot on a collapsed panel shows it still holds edits.
function markTouchedPanels() {
  for (const panel of document.querySelectorAll("#controls > details")) {
    const keys = [...panel.querySelectorAll("input[id^='s-']")].map((i) =>
      i.id.slice(2),
    );
    if (panel.id === "curvePanel")
      keys.push(...Object.keys(defaults).filter((k) => k.startsWith("curve_")));
    panel.classList.toggle(
      "touched",
      !!current && keys.some((k) => !sameValue(settings[k], defaults[k])),
    );
  }
}
function checkpoint() {
  if (!current) return;
  history.push({ ...settings });
  if (history.length > 80) history.shift();
  future = [];
}
function changed() {
  before = false;
  $("compare").classList.remove("active");
  syncControls();
  schedulePreview();
  persist();
}
function persist() {
  if (!current) return;
  const pid = current.id,
    snapshot = { ...settings };
  current.settings = snapshot;
  $("saveStatus").textContent = "보정값 저장 중…";
  saveChain = saveChain
    .catch(() => {})
    .then(async () => {
      await api(`/api/photos/${pid}/settings`, json("PUT", snapshot));
      if (current?.id === pid && current.settings === snapshot)
        $("saveStatus").textContent = "✓ 모든 변경 사항 저장됨";
    })
    .catch((e) => {
      $("saveStatus").textContent = "저장 실패";
      toast(e.message);
    });
}
function schedulePreview() {
  previewVersion++;
  clearTimeout(timer);
  timer = setTimeout(() => updatePreview(), 140);
}
async function updatePreview() {
  if (!current) return;
  const version = ++previewVersion,
    pid = current.id;
  try {
    const res = await api(
      `/api/photos/${pid}/preview`,
      json("POST", before ? defaults : settings),
    );
    const blob = await res.blob();
    if (version !== previewVersion || pid !== current?.id) return;
    const next = URL.createObjectURL(blob),
      img = new Image();
    img.onload = () => {
      if (version !== previewVersion) {
        URL.revokeObjectURL(next);
        return;
      }
      if (previewURL) URL.revokeObjectURL(previewURL);
      previewURL = next;
      $("preview").src = next;
      $("preview").hidden = false;
      $("beforeBadge").hidden = !before;
      applyZoom();
      histogram(img);
    };
    img.src = next;
  } catch (e) {
    toast(e.message);
  }
}
function histogram(img) {
  const c = document.createElement("canvas");
  c.width = 240;
  c.height = 160;
  const cx = c.getContext("2d");
  cx.drawImage(img, 0, 0, 240, 160);
  const data = cx.getImageData(0, 0, 240, 160).data,
    bins = Array.from({ length: 3 }, () => Array(64).fill(0));
  for (let i = 0; i < data.length; i += 4)
    for (let ch = 0; ch < 3; ch++) bins[ch][data[i + ch] >> 2]++;
  const h = $("histogram"),
    ctx = h.getContext("2d");
  ctx.clearRect(0, 0, h.width, h.height);
  const peak = Math.max(...bins.flat());
  ctx.globalCompositeOperation = "screen";
  bins.forEach((bin, ch) => {
    ctx.fillStyle = ["#bf746c66", "#90b99a66", "#789eae88"][ch];
    ctx.beginPath();
    ctx.moveTo(0, h.height);
    bin.forEach((n, x) =>
      ctx.lineTo(
        (x * h.width) / 63,
        h.height - Math.sqrt(n / peak) * (h.height - 9),
      ),
    );
    ctx.lineTo(h.width, h.height);
    ctx.fill();
  });
  ctx.globalCompositeOperation = "source-over";
}
function presetButtons() {
  $("customGroup").hidden = !custom.length;
  $("customCount").textContent = custom.length;
  for (const [id, list] of [
    ["presets", builtins],
    ["customPresets", custom],
  ]) {
    $(id).replaceChildren();
    list.forEach((p, i) => {
      const b = document.createElement("button");
      b.className = "preset";
      const swatch = document.createElement("span");
      swatch.className = "preset-swatch";
      if (p.colors)
        swatch.style.background = `linear-gradient(150deg,${p.colors[0]} 0 45%,${p.colors[1]} 46%)`;
      const text = document.createElement("span");
      text.textContent = p.name;
      const small = document.createElement("small");
      small.textContent = p.sub || "IMPORTED · XMP 프리셋";
      text.append(small);
      b.append(swatch, text);
      b.onclick = () => {
        if (!current) return toast("사진을 먼저 불러오세요.");
        checkpoint();
        settings = {
          ...defaults,
          rotation: settings.rotation,
          crop: settings.crop,
          ...p.settings,
        };
        changed();
        document
          .querySelectorAll(".preset")
          .forEach((el) => el.classList.remove("active"));
        b.classList.add("active");
        if (p.engine_version || p.unsupported) showPresetReport(p);
        toast(
          `${p.name} · ${p.partial || p.unsupported?.length ? "일부 적용" : "적용됨"}`,
        );
      };
      $(id).append(b);
    });
  }
}
function renderStrip() {
  $("photoCount").textContent = photos.length;
  $("stripCount").textContent = photos.length + "장의 사진";
  document.querySelectorAll(".thumb").forEach((el) => el.remove());
  for (const p of photos) {
    const b = document.createElement("button");
    b.className = "thumb" + (p.id === current?.id ? " active" : "");
    const img = document.createElement("img");
    img.src = `/api/photos/${p.id}/thumb`;
    img.alt = p.name;
    img.loading = "lazy";
    img.draggable = false;
    b.title = p.name;
    const name = document.createElement("span");
    name.textContent = p.name;
    b.append(img, name);
    b.onclick = () => {
      select(p);
      setView(false);
    };
    $("thumbnails").insertBefore(b, $("addPhoto"));
  }
}
function select(photo) {
  clearTimeout(timer);
  previewVersion++;
  current = photo;
  settings = { ...defaults, ...photo.settings };
  history = [];
  future = [];
  before = false;
  $("compare").classList.remove("active");
  $("beforeBadge").hidden = true;
  $("preview").hidden = true;
  $("empty").hidden = true;
  $("currentName").textContent = photo.name;
  $("fileType").textContent = photo.raw
    ? "RAW"
    : photo.name.split(".").pop().toUpperCase();
  $("dimensions").textContent =
    `${photo.width.toLocaleString()} × ${photo.height.toLocaleString()} px · ${photo.raw ? "RAW 현상" : "sRGB"}`;
  $("photoInfo").textContent =
    `${photo.name}\n${photo.width} × ${photo.height} px\n${(photo.size / 1024 / 1024).toFixed(1)} MB · ${photo.raw ? "RAW · 16비트 디코딩" : "래스터 이미지"}\n원본 보존 · 보정값 별도 저장`;
  $("saveStatus").textContent = "✓ 모든 변경 사항 저장됨";
  $("photoInfo").hidden = true;
  $("infoButton").setAttribute("aria-pressed", "false");
  document.title = `${photo.name} — 나만의빛`;
  zoomMode = "fit";
  syncControls();
  applyZoom();
  renderStrip();
  updatePreview();
}
function step(offset) {
  if (!photos.length) return;
  const index = photos.findIndex((p) => p.id === current?.id);
  const next = photos[(index + offset + photos.length) % photos.length];
  if (next && next.id !== current?.id) select(next);
}
async function importPhotos(files) {
  const list = [...files];
  if (!list.length) return;
  busy(true);
  let imported = 0;
  try {
    for (let i = 0; i < list.length; i++) {
      busy(true, `사진 불러오는 중 · ${i + 1} / ${list.length}`);
      const form = new FormData();
      form.append("file", list[i]);
      try {
        const p = await (
          await api("/api/photos", { method: "POST", body: form })
        ).json();
        photos.push(p);
        select(p);
        imported++;
      } catch (e) {
        toast(`${list[i].name}: ${e.message}`);
      }
    }
    if (imported) setView(false);
  } finally {
    busy(false);
    $("photoInput").value = "";
  }
}
for (const id of ["importTop", "emptyImport", "addPhoto"])
  $(id).onclick = () => $("photoInput").click();
$("photoInput").onchange = (e) => importPhotos(e.target.files);
for (const id of ["importPreset", "xmpButton"])
  $(id).onclick = () => $("presetInput").click();
$("presetInput").onchange = async (e) => {
  for (const file of e.target.files) {
    const form = new FormData();
    form.append("file", file);
    try {
      const p = await (
        await api("/api/presets/import", { method: "POST", body: form })
      ).json();
      const existing = custom.findIndex((item) => item.name === p.name);
      if (existing >= 0) custom[existing] = p;
      else custom.push(p);
      localStorage.setItem("lightloom-presets", JSON.stringify(custom));
      presetButtons();
      if (current) {
        checkpoint();
        settings = {
          ...defaults,
          rotation: settings.rotation,
          crop: settings.crop,
          ...p.settings,
        };
        changed();
      }
      showPresetReport(p);
      toast(
        `${p.name} · ${p.partial ? "일부 적용" : "보정값 가져오기 완료"} (${p.applied_count}개)\n적용 내역에서 호환 범위를 확인할 수 있습니다.`,
      );
    } catch (error) {
      toast(error.message);
    }
  }
  e.target.value = "";
};
let dragDepth = 0;
function showDrop(on) {
  dragDepth = on ? dragDepth : 0;
  $("dropZone").classList.toggle("drag", on);
  $("dropHint").hidden = !on;
}
// Without a window-level guard a stray drop would navigate the webview away.
for (const type of ["dragenter", "dragover", "drop"])
  window.addEventListener(type, (e) => e.preventDefault());
window.addEventListener("dragenter", () => showDrop(++dragDepth > 0));
window.addEventListener("dragleave", () => {
  if (--dragDepth <= 0) showDrop(false);
});
window.addEventListener("drop", (e) => {
  showDrop(false);
  if (e.dataTransfer?.files?.length) importPhotos(e.dataTransfer.files);
});
$("undo").onclick = () => {
  if (!history.length) return;
  future.push({ ...settings });
  settings = history.pop();
  changed();
};
$("redo").onclick = () => {
  if (!future.length) return;
  history.push({ ...settings });
  settings = future.pop();
  changed();
};
$("reset").onclick = () => {
  if (!current) return;
  checkpoint();
  settings = { ...defaults };
  changed();
  document
    .querySelectorAll(".preset")
    .forEach((el) => el.classList.remove("active"));
};
$("rotate").onclick = () => {
  if (!current) return;
  checkpoint();
  settings.rotation = (settings.rotation + 1) % 4;
  changed();
};
$("crop").onchange = (e) => {
  checkpoint();
  settings.crop = e.target.value;
  changed();
};
$("mono").onclick = () => {
  if (!current) return;
  checkpoint();
  settings.monochrome = !settings.monochrome;
  changed();
};
$("compare").onclick = () => {
  if (!current) return;
  before = !before;
  $("compare").classList.toggle("active", before);
  updatePreview();
};
$("infoButton").onclick = () => {
  if (!current) return;
  $("photoInfo").hidden = !$("photoInfo").hidden;
  $("infoButton").setAttribute("aria-pressed", String(!$("photoInfo").hidden));
};
// --- zoom and pan ------------------------------------------------------------
// Scale is relative to the preview proxy (long edge 1,600 px), not the original.
const ZOOM_STEPS = [0.25, 0.33, 0.5, 0.67, 1, 1.5, 2, 3, 4];
let zoomMode = "fit";
function applyZoom(anchor) {
  const img = $("preview"),
    scroll = $("canvasScroll");
  const previous = {
    left:
      (scroll.scrollLeft + scroll.clientWidth / 2) / (scroll.scrollWidth || 1),
    top:
      (scroll.scrollTop + scroll.clientHeight / 2) / (scroll.scrollHeight || 1),
  };
  if (zoomMode === "fit") {
    img.classList.remove("zoomed");
    img.style.width = img.style.height = "";
    // The fit ratio is only known once the browser has laid the image out.
    requestAnimationFrame(() => {
      if (zoomMode !== "fit") return;
      $("zoomLevel").textContent = img.naturalWidth
        ? Math.round(
            (img.getBoundingClientRect().width / img.naturalWidth) * 100,
          ) + "%"
        : "맞춤";
    });
  } else {
    img.classList.add("zoomed");
    img.style.width = Math.round((img.naturalWidth || 0) * zoomMode) + "px";
    img.style.height = "auto";
    $("zoomLevel").textContent = Math.round(zoomMode * 100) + "%";
  }
  $("fit").classList.toggle("active", zoomMode === "fit");
  $("zoom").classList.toggle("active", zoomMode === 1);
  $("zoomIn").disabled = !current || zoomMode === ZOOM_STEPS.at(-1);
  $("zoomOut").disabled = !current || zoomMode === "fit";
  if (zoomMode === "fit") return;
  const point = anchor || previous;
  scroll.scrollLeft = point.left * scroll.scrollWidth - scroll.clientWidth / 2;
  scroll.scrollTop = point.top * scroll.scrollHeight - scroll.clientHeight / 2;
}
function setZoom(next) {
  if (!current) return;
  zoomMode = next;
  applyZoom();
}
function stepZoom(direction) {
  if (!current) return;
  const img = $("preview"),
    scroll = $("canvasScroll");
  const fitScale = img.naturalWidth
    ? img.getBoundingClientRect().width / img.naturalWidth
    : 1;
  const currentScale = zoomMode === "fit" ? fitScale : zoomMode;
  const next =
    direction > 0
      ? ZOOM_STEPS.find((z) => z > currentScale + 0.001)
      : [...ZOOM_STEPS].reverse().find((z) => z < currentScale - 0.001);
  if (direction < 0 && (!next || next <= fitScale)) return setZoom("fit");
  if (!next) return;
  setZoom(next);
  scroll.scrollTo({ left: scroll.scrollWidth / 2 - scroll.clientWidth / 2 });
}
$("fit").onclick = () => setZoom("fit");
$("zoom").onclick = () => {
  setZoom(1);
  toast("미리보기 픽셀 기준 100% (긴 변 최대 1,600 px)");
};
$("zoomIn").onclick = () => stepZoom(1);
$("zoomOut").onclick = () => stepZoom(-1);
let resizeTimer;
window.addEventListener("resize", () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => applyZoom(), 120);
});
$("canvasScroll").addEventListener(
  "wheel",
  (e) => {
    if (!current || !(e.ctrlKey || e.metaKey)) return;
    e.preventDefault();
    stepZoom(e.deltaY < 0 ? 1 : -1);
  },
  { passive: false },
);
// Grab-to-pan once the image is larger than the viewport.
let panning = null;
$("canvasScroll").addEventListener("pointerdown", (e) => {
  const scroll = $("canvasScroll");
  if (zoomMode === "fit" || e.button !== 0) return;
  if (
    scroll.scrollWidth <= scroll.clientWidth &&
    scroll.scrollHeight <= scroll.clientHeight
  )
    return;
  panning = {
    x: e.clientX,
    y: e.clientY,
    left: scroll.scrollLeft,
    top: scroll.scrollTop,
  };
  scroll.setPointerCapture(e.pointerId);
  scroll.classList.add("panning");
});
$("canvasScroll").addEventListener("pointermove", (e) => {
  if (!panning) return;
  const scroll = $("canvasScroll");
  scroll.scrollLeft = panning.left - (e.clientX - panning.x);
  scroll.scrollTop = panning.top - (e.clientY - panning.y);
});
for (const type of ["pointerup", "pointercancel"])
  $("canvasScroll").addEventListener(type, () => {
    panning = null;
    $("canvasScroll").classList.remove("panning");
  });
function setView(library) {
  document.querySelector(".workspace").classList.toggle("grid-mode", library);
  $("libraryTab").classList.toggle("active", library);
  $("editTab").classList.toggle("active", !library);
  $("stripTitle").firstChild.textContent = library
    ? "라이브러리 "
    : "필름 스트립 ";
  if (!library) applyZoom();
}
$("libraryTab").onclick = () => setView(true);
$("allPhotos").onclick = () => setView(true);
$("editTab").onclick = () => setView(false);
$("exportTop").onclick = () => {
  if (current) $("exportDialog").showModal();
};
$("cancelExport").onclick = () => $("exportDialog").close();
$("quality").oninput = (e) => ($("qualityValue").textContent = e.target.value);
$("exportFormat").onchange = (e) =>
  ($("qualityLabel").hidden = e.target.value !== "jpeg");
function exportFilename(photo, format) {
  return (
    photo.name.replace(/\.[^.]+$/, "") +
    "-나만의빛." +
    (format === "jpeg" ? "jpg" : format === "tiff" ? "tif" : format)
  );
}
$("download").onclick = async () => {
  if (!current) return;
  const photo = current,
    format = $("exportFormat").value,
    size = Number($("exportSize").value);
  let dest = null;
  if (shell.api) {
    try {
      dest = await shell.api.save_dialog(exportFilename(photo, format), format);
    } catch {
      dest = null;
    }
    if (!dest) return; // the native save panel was cancelled
  }
  $("download").disabled = $("cancelExport").disabled = true;
  $("exportProgress").hidden = false;
  $("exportProgressText").textContent = size
    ? `긴 변 ${size.toLocaleString()} px로 현상 중…`
    : "원본 크기로 현상 중… 큰 RAW는 시간이 걸립니다";
  try {
    const res = await api(
      `/api/photos/${photo.id}/export`,
      json("POST", {
        settings,
        format,
        quality: Number($("quality").value),
        long_edge: size,
        dest,
      }),
    );
    if (dest) {
      const saved = await res.json();
      $("exportDialog").close();
      toast(`저장했습니다 · ${dest.split(/[\\/]/).pop()}`, {
        label: "폴더에서 보기",
        run: () => shell.api?.reveal(saved.path),
      });
    } else {
      const url = URL.createObjectURL(await res.blob());
      const link = document.createElement("a");
      link.href = url;
      link.download = exportFilename(photo, format);
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 60000);
      $("exportDialog").close();
      toast("보정된 사진을 내보냈습니다.");
    }
  } catch (e) {
    toast(e.message);
  } finally {
    $("download").disabled = $("cancelExport").disabled = false;
    $("exportProgress").hidden = true;
  }
};
// --- keyboard ----------------------------------------------------------------
const MOD = navigator.platform?.startsWith("Mac") === false ? "Ctrl" : "⌘";
const SHORTCUTS = [
  [`${MOD} O`, "사진 불러오기"],
  [`${MOD} E`, "내보내기"],
  [`${MOD} Z · ⇧${MOD} Z`, "실행 취소 · 다시 실행"],
  ["\\", "원본과 비교"],
  ["← →", "이전 · 다음 사진"],
  [`${MOD} 0`, "화면 맞춤"],
  [`${MOD} 1`, "100% 보기"],
  [`${MOD} + · ${MOD} −`, "확대 · 축소"],
  ["R", "오른쪽 90° 회전"],
  ["I", "사진 정보"],
  [`${MOD} /`, "이 창 열기"],
  ["슬라이더 더블클릭", "해당 보정만 기본값으로"],
];
for (const [keys, label] of SHORTCUTS) {
  const dt = document.createElement("dt"),
    dd = document.createElement("dd");
  dt.textContent = keys;
  dd.textContent = label;
  $("shortcutList").append(dt, dd);
}
$("shortcutsButton").onclick = () => $("shortcuts").showModal();
$("closeShortcuts").onclick = () => $("shortcuts").close();

document.addEventListener("keydown", (e) => {
  const mod = e.metaKey || e.ctrlKey;
  if (mod && e.key === "/") {
    e.preventDefault();
    return document.querySelector("dialog[open]")
      ? document.querySelector("dialog[open]").close()
      : $("shortcuts").showModal();
  }
  if (document.querySelector("dialog[open]")) return;
  if (mod) {
    const zooms = { 0: () => setZoom("fit"), 1: () => setZoom(1) };
    if (e.key.toLowerCase() === "o")
      return (e.preventDefault(), $("photoInput").click());
    if (e.key.toLowerCase() === "e")
      return (e.preventDefault(), $("exportTop").click());
    if (e.key === "=" || e.key === "+")
      return (e.preventDefault(), stepZoom(1));
    if (e.key === "-") return (e.preventDefault(), stepZoom(-1));
    if (zooms[e.key]) return (e.preventDefault(), zooms[e.key]());
  }
  if (["INPUT", "SELECT", "TEXTAREA"].includes(e.target.tagName)) return;
  if (mod && e.key.toLowerCase() === "z") {
    e.preventDefault();
    return $(e.shiftKey ? "redo" : "undo").click();
  }
  if (mod) return;
  if (e.key === "\\") $("compare").click();
  if (e.key === "ArrowLeft") (e.preventDefault(), step(-1));
  if (e.key === "ArrowRight") (e.preventDefault(), step(1));
  if (e.key.toLowerCase() === "r") $("rotate").click();
  if (e.key.toLowerCase() === "i") $("infoButton").click();
});
initCurveEditor();
presetButtons();
syncControls();
api("/api/photos")
  .then((r) => r.json())
  .then((list) => {
    photos = list;
    renderStrip();
    if (photos.length) select(photos[0]);
  })
  .catch((e) => toast(e.message));

function showPresetReport(p) {
  $("presetReportButton").hidden = false;
  $("presetReportTitle").textContent = p.name;
  const old = !p.engine_version;
  $("presetReportSummary").textContent = old
    ? "이전 버전에서 가져온 프리셋입니다. XMP를 다시 가져오면 새 보정 기능을 적용할 수 있습니다."
    : `${p.partial ? "일부 적용" : "지원 보정값 적용"} · ${p.applied_count}개 항목`;
  $("presetReportNote").textContent =
    p.note ||
    "이전 프리셋에는 원본 XMP가 저장되어 있지 않아 다시 가져와야 합니다.";
  const list = $("presetReportDetails");
  list.replaceChildren();
  for (const [title, items] of [
    ["미지원 효과", p.unsupported],
    ["잘못된 값", p.invalid],
    ["범위에 맞게 조정", p.adjusted],
    ["영향 없는 비활성 항목", p.neutral],
    ["관리용 정보", p.ignored],
  ]) {
    if (!items?.length) continue;
    const d = document.createElement("details"),
      summary = document.createElement("summary"),
      body = document.createElement("p");
    summary.textContent = `${title} · ${items.length}개`;
    body.textContent = items.join(", ");
    d.append(summary, body);
    list.append(d);
  }
}
$("presetReportButton").onclick = () => $("presetReport").showModal();
$("closePresetReport").onclick = () => $("presetReport").close();
if (custom.length) showPresetReport(custom.at(-1));

$("controlSearch").oninput = (e) => {
  const query = e.target.value.toLowerCase().trim();
  let matches = 0;
  document.querySelectorAll("#controls > details").forEach((panel) => {
    const match = panel.textContent.toLowerCase().includes(query);
    panel.hidden = !match;
    matches += match ? 1 : 0;
    if (query && match) panel.open = true;
  });
  $("searchEmpty").hidden = !query || matches > 0;
};
