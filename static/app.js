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
  crop_x: 0,
  crop_y: 0,
  crop_w: 1,
  crop_h: 1,
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
let selected = new Set();
let lastClicked = null;
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
function busy(
  on,
  text = "사진을 현상하고 있습니다",
  progress = null,
  note = "",
) {
  $("loading").hidden = !on;
  $("loadingText").textContent = text;
  $("loadingNote").textContent = note;
  $("loadingTrack").hidden = progress === null;
  if (progress !== null)
    $("loadingBar").style.width = Math.round(progress * 100) + "%";
  for (const id of [
    "importTop",
    "emptyImport",
    "addPhoto",
    "importPreset",
    "xmpButton",
  ])
    $(id).disabled = on;
}
// A yes/no the page can await, so deletions always ask first.
function confirmAction(title, body, label = "삭제") {
  return new Promise((resolve) => {
    $("confirmTitle").textContent = title;
    $("confirmBody").textContent = body;
    $("confirmOk").textContent = label;
    const finish = (answer) => {
      $("confirmDialog").close();
      $("confirmOk").onclick = $("confirmCancel").onclick = null;
      resolve(answer);
    };
    $("confirmOk").onclick = () => finish(true);
    $("confirmCancel").onclick = () => finish(false);
    $("confirmDialog").showModal();
  });
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
  if (!cropping) $("crop").value = settings.crop;
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
    "zoom",
    "fit",
    "zoomIn",
    "zoomOut",
    "infoButton",
    "cropTool",
    "deletePhoto",
  ])
    $(id).disabled = !current;
  $("exportTop").disabled = !photos.length;
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
      `/api/photos/${pid}/${cropping ? "frame" : "preview"}`,
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
      layoutCropBox();
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
function togglePick(id) {
  selected.has(id) ? selected.delete(id) : selected.add(id);
  lastClicked = id;
  renderStrip();
}
function pickRange(id) {
  const from = photos.findIndex((p) => p.id === (lastClicked ?? id));
  const to = photos.findIndex((p) => p.id === id);
  for (const p of photos.slice(Math.min(from, to), Math.max(from, to) + 1))
    selected.add(p.id);
  renderStrip();
}
function renderStrip() {
  selected = new Set(
    [...selected].filter((id) => photos.some((p) => p.id === id)),
  );
  $("photoCount").textContent = photos.length;
  $("stripCount").textContent =
    selected.size > 1
      ? `${photos.length}장 중 ${selected.size}장 선택`
      : photos.length + "장의 사진";
  const grid = document
    .querySelector(".workspace")
    .classList.contains("grid-mode");
  $("selectAll").hidden = !grid || !photos.length;
  $("selectNone").hidden = !grid || selected.size < 2;
  $("deleteSelected").hidden = !grid || selected.size < 2;
  $("selectAll").textContent = `모두 선택 (${photos.length})`;
  $("deleteSelected").textContent = `선택 삭제 (${selected.size})`;
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
    b.classList.toggle("picked", selected.has(p.id));
    b.onclick = (e) => {
      const grid = document
        .querySelector(".workspace")
        .classList.contains("grid-mode");
      if (grid && (e.metaKey || e.ctrlKey)) return togglePick(p.id);
      if (grid && e.shiftKey) return pickRange(p.id);
      selected = new Set([p.id]);
      lastClicked = p.id;
      select(p);
      if (!grid) setView(false);
      else renderStrip();
    };
    b.ondblclick = () => {
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
  if (!selected.has(photo.id) || selected.size <= 1)
    selected = new Set([photo.id]);
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
async function removePhotos(ids, prompt) {
  if (!ids.length) return;
  if (!(await confirmAction("사진을 삭제할까요?", prompt))) return;
  busy(true, "사진을 삭제하고 있습니다");
  const gone = [];
  try {
    for (const id of ids) {
      try {
        await api(`/api/photos/${id}`, { method: "DELETE" });
        gone.push(id);
      } catch (e) {
        toast(e.message);
      }
    }
  } finally {
    busy(false);
  }
  if (!gone.length) return;
  const removing = new Set(gone);
  const index = photos.findIndex((p) => p.id === current?.id);
  photos = photos.filter((p) => !removing.has(p.id));
  for (const id of gone) selected.delete(id);
  if (current && removing.has(current.id)) {
    const next = photos[Math.min(index, photos.length - 1)];
    if (next) select(next);
    else clearCurrent();
  }
  renderStrip();
  toast(`${gone.length}장을 삭제했습니다. 원본 파일은 그대로 있습니다.`);
}
function clearCurrent() {
  current = null;
  settings = { ...defaults };
  history = [];
  future = [];
  if (cropping) leaveCrop();
  $("preview").hidden = true;
  $("empty").hidden = false;
  $("photoInfo").hidden = true;
  $("currentName").textContent = "새로운 작업";
  $("fileType").textContent = "STUDIO";
  $("dimensions").textContent = "원본을 보존하는 비파괴 편집";
  $("saveStatus").textContent = "편집할 사진을 불러오세요";
  document.title = "나만의빛 — 로컬 사진 스튜디오";
  syncControls();
}
$("deletePhoto").onclick = () =>
  current &&
  removePhotos(
    [current.id],
    `${current.name} 파일을 라이브러리에서 지웁니다. 원본은 그대로 남습니다.`,
  );
$("deleteSelected").onclick = () =>
  removePhotos(
    [...selected],
    `선택한 ${selected.size}장을 라이브러리에서 지웁니다. 원본은 그대로 남습니다.`,
  );
$("selectAll").onclick = () => {
  selected = new Set(photos.map((p) => p.id));
  renderStrip();
};
$("selectNone").onclick = () => {
  selected = new Set(current ? [current.id] : []);
  renderStrip();
};

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
  if (cropping) {
    settings.rotation = (settings.rotation + 1) % 4;
    cropRect = { x: 0, y: 0, w: 1, h: 1 };
    updatePreview().then(layoutCropBox);
    return;
  }
  checkpoint();
  settings.rotation = (settings.rotation + 1) % 4;
  changed();
};
// --- crop ---------------------------------------------------------------------
// The rectangle is stored as fractions of the rotated frame, so it survives
// rotation, zoom and window resizes.
let cropping = false;
let cropRect = { x: 0, y: 0, w: 1, h: 1 };
let cropBefore = null;
let cropDrag = null;

function frameSize() {
  if (!current) return { w: 1, h: 1 };
  const turned = settings.rotation % 2 === 1;
  return turned
    ? { w: current.height, h: current.width }
    : { w: current.width, h: current.height };
}
// Fraction-space width per unit of height for a pixel aspect ratio.
function lockedRatio() {
  const name = $("crop").value;
  if (name === "free" || name === "custom") return null;
  // Fraction space is already frame-relative, so the frame's own ratio is 1.
  if (name === "original") return 1;
  const frame = frameSize();
  const [a, b] = name.split(":").map(Number);
  return (a / b) * (frame.h / frame.w);
}
function centredRect(name) {
  if (name === "free" || name === "custom") return { ...cropRect };
  const k = name === "original" ? 1 : lockedRatio();
  const w = Math.min(1, k),
    h = Math.min(1, 1 / k);
  return { x: (1 - w) / 2, y: (1 - h) / 2, w, h };
}
function rectFromSettings() {
  return {
    x: settings.crop_x,
    y: settings.crop_y,
    w: settings.crop_w,
    h: settings.crop_h,
  };
}
function applyRect(rect) {
  settings.crop_x = Math.max(0, Math.min(1, rect.x));
  settings.crop_y = Math.max(0, Math.min(1, rect.y));
  settings.crop_w = Math.min(1 - settings.crop_x, rect.w);
  settings.crop_h = Math.min(1 - settings.crop_y, rect.h);
}
function layoutCropBox() {
  if (!cropping) return;
  const img = $("preview").getBoundingClientRect(),
    stage = $("dropZone").getBoundingClientRect(),
    box = $("cropBox");
  box.style.left = img.left - stage.left + cropRect.x * img.width + "px";
  box.style.top = img.top - stage.top + cropRect.y * img.height + "px";
  box.style.width = cropRect.w * img.width + "px";
  box.style.height = cropRect.h * img.height + "px";
}
async function enterCrop() {
  if (!current || cropping) return;
  cropping = true;
  cropBefore = { ...settings };
  cropRect = rectFromSettings();
  setZoom("fit");
  $("cropTool").classList.add("active");
  $("cropTool").setAttribute("aria-pressed", "true");
  $("cropBar").hidden = false;
  $("cropOverlay").hidden = false;
  document.body.classList.add("cropping");
  await updatePreview();
  layoutCropBox();
}
function leaveCrop() {
  cropping = false;
  cropDrag = null;
  $("cropTool").classList.remove("active");
  $("cropTool").setAttribute("aria-pressed", "false");
  $("cropBar").hidden = true;
  $("cropOverlay").hidden = true;
  document.body.classList.remove("cropping");
}
$("cropTool").onclick = () => (cropping ? $("cropApply").click() : enterCrop());
$("cropApply").onclick = () => {
  if (!cropping) return;
  const previous = cropBefore;
  leaveCrop();
  settings = { ...previous };
  checkpoint();
  applyRect(cropRect);
  if ($("crop").value === "free" && !isFullFrame(cropRect))
    settings.crop = "free";
  changed();
};
$("cropCancel").onclick = () => {
  if (!cropping) return;
  const previous = cropBefore;
  leaveCrop();
  settings = { ...previous };
  syncControls();
  updatePreview();
};
$("cropReset").onclick = () => {
  if (!cropping) return;
  $("crop").value = "free";
  cropRect = { x: 0, y: 0, w: 1, h: 1 };
  layoutCropBox();
};
function isFullFrame(r) {
  return r.x === 0 && r.y === 0 && r.w === 1 && r.h === 1;
}
$("crop").onchange = (e) => {
  const name = e.target.value;
  if (cropping) {
    if (name !== "free") cropRect = centredRect(name);
    layoutCropBox();
    return;
  }
  checkpoint();
  settings.crop = name;
  const rect = name === "free" ? rectFromSettings() : centredRect(name);
  applyRect(rect);
  changed();
};

// Dragging: a handle resizes from its own edge, the inside moves the whole box.
$("cropOverlay").addEventListener("pointerdown", (e) => {
  if (!cropping) return;
  const handle = e.target.closest(".crop-handle");
  const inside = e.target.closest("#cropBox");
  if (!handle && !inside) return;
  e.preventDefault();
  const img = $("preview").getBoundingClientRect();
  cropDrag = {
    handle: handle ? handle.dataset.handle : "move",
    x: e.clientX,
    y: e.clientY,
    start: { ...cropRect },
    img,
  };
  $("cropOverlay").setPointerCapture(e.pointerId);
});
$("cropOverlay").addEventListener("pointermove", (e) => {
  if (!cropDrag) return;
  const { handle, start, img } = cropDrag;
  const dx = (e.clientX - cropDrag.x) / img.width;
  const dy = (e.clientY - cropDrag.y) / img.height;
  const min = 0.05;
  let { x, y, w, h } = start;
  if (handle === "move") {
    x = Math.max(0, Math.min(1 - w, x + dx));
    y = Math.max(0, Math.min(1 - h, y + dy));
  } else {
    if (handle.includes("w")) {
      const nx = Math.max(0, Math.min(x + w - min, x + dx));
      w += x - nx;
      x = nx;
    }
    if (handle.includes("e")) w = Math.max(min, Math.min(1 - x, w + dx));
    if (handle.includes("n")) {
      const ny = Math.max(0, Math.min(y + h - min, y + dy));
      h += y - ny;
      y = ny;
    }
    if (handle.includes("s")) h = Math.max(min, Math.min(1 - y, h + dy));
    const k = lockedRatio();
    if (k && $("crop").value !== "free") {
      // Keep the locked ratio by giving up whichever side has room.
      if (handle === "n" || handle === "s") w = Math.min(1 - x, k * h);
      else h = Math.min(1 - y, w / k);
      if (handle.includes("w")) x = Math.min(x, start.x + start.w - w);
      if (handle.includes("n")) y = Math.min(y, start.y + start.h - h);
    }
  }
  cropRect = { x, y, w, h };
  layoutCropBox();
});
for (const type of ["pointerup", "pointercancel"])
  $("cropOverlay").addEventListener(type, () => (cropDrag = null));
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
const ZOOM_MIN = 0.05;
const ZOOM_MAX = 8;
let zoomMode = "fit";
let gestureUntil = 0;
function viewport() {
  const box = $("canvasScroll"),
    style = getComputedStyle(box);
  return {
    w:
      box.clientWidth -
      parseFloat(style.paddingLeft) -
      parseFloat(style.paddingRight),
    h:
      box.clientHeight -
      parseFloat(style.paddingTop) -
      parseFloat(style.paddingBottom),
  };
}
// What "화면 맞춤" resolves to right now. The fitted view never upscales, which
// is why 1 is the ceiling here.
function fitScale() {
  const img = $("preview");
  if (!img.naturalWidth) return 1;
  const { w, h } = viewport();
  return Math.min(1, w / img.naturalWidth, h / img.naturalHeight) || 1;
}
function currentScale() {
  return zoomMode === "fit" ? fitScale() : zoomMode;
}
function updateZoomChrome() {
  const img = $("preview");
  const show = (scale) =>
    ($("zoomLevel").textContent = scale
      ? Math.round(scale * 100) + "%"
      : "맞춤");
  if (zoomMode === "fit")
    // The fit ratio is only known once the browser has laid the image out.
    requestAnimationFrame(() => {
      if (zoomMode !== "fit") return;
      show(
        img.naturalWidth
          ? img.getBoundingClientRect().width / img.naturalWidth
          : 0,
      );
    });
  else show(zoomMode);
  $("fit").classList.toggle("active", zoomMode === "fit");
  $("zoom").classList.toggle(
    "active",
    zoomMode !== "fit" && Math.abs(zoomMode - 1) < 0.005,
  );
  $("zoomIn").disabled =
    !current || (zoomMode !== "fit" && zoomMode >= ZOOM_MAX);
  $("zoomOut").disabled = !current || zoomMode === "fit";
}
function applyZoom(pointer) {
  const img = $("preview"),
    scroll = $("canvasScroll");
  const anchored =
    pointer && img.naturalWidth ? img.getBoundingClientRect() : null;
  const ratioX = anchored?.width
    ? (pointer.clientX - anchored.left) / anchored.width
    : 0.5;
  const ratioY = anchored?.height
    ? (pointer.clientY - anchored.top) / anchored.height
    : 0.5;
  const centre = {
    left:
      (scroll.scrollLeft + scroll.clientWidth / 2) / (scroll.scrollWidth || 1),
    top:
      (scroll.scrollTop + scroll.clientHeight / 2) / (scroll.scrollHeight || 1),
  };
  if (zoomMode === "fit") {
    img.classList.remove("zoomed");
    img.style.width = img.style.height = "";
  } else {
    img.classList.add("zoomed");
    img.style.width = Math.round((img.naturalWidth || 0) * zoomMode) + "px";
    img.style.height = "auto";
  }
  updateZoomChrome();
  if (zoomMode === "fit") return;
  if (anchored) {
    // Pin whatever sat under the cursor so zooming tracks where you are looking.
    const after = img.getBoundingClientRect();
    scroll.scrollLeft += after.left + ratioX * after.width - pointer.clientX;
    scroll.scrollTop += after.top + ratioY * after.height - pointer.clientY;
    return;
  }
  scroll.scrollLeft = centre.left * scroll.scrollWidth - scroll.clientWidth / 2;
  scroll.scrollTop = centre.top * scroll.scrollHeight - scroll.clientHeight / 2;
}
function setZoom(next, pointer) {
  if (!current) return;
  zoomMode = next;
  applyZoom(pointer);
}
// Below the fitted ratio there is only empty canvas, so snap back to 화면 맞춤.
function clampZoom(scale, pointer) {
  const fit = fitScale();
  const next = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, scale));
  setZoom(next <= fit + 1e-4 ? "fit" : next, pointer);
}
function zoomBy(factor, pointer) {
  if (!current || !$("preview").naturalWidth) return;
  clampZoom(currentScale() * factor, pointer);
}
function stepZoom(direction, pointer) {
  if (!current) return;
  const fit = fitScale(),
    scale = currentScale();
  const next =
    direction > 0
      ? ZOOM_STEPS.find((z) => z > scale + 0.001)
      : [...ZOOM_STEPS].reverse().find((z) => z < scale - 0.001);
  if (direction < 0 && (!next || next <= fit)) return setZoom("fit");
  if (!next) return;
  setZoom(next, pointer);
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
  resizeTimer = setTimeout(() => {
    applyZoom();
    layoutCropBox();
  }, 120);
});
// Wheel and two-finger scroll zoom the photo, the way Lightroom's develop view
// does; panning is a drag. A trackpad pinch arrives either as gesture events
// (WebKit) or as a wheel event with ctrlKey set (Chromium/Edge), so both paths
// are handled and the gesture one wins while it is running.
function wheelPixels(e) {
  const perUnit = e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? 100 : 1;
  return e.deltaY * perUnit;
}
$("canvasScroll").addEventListener(
  "wheel",
  (e) => {
    if (!current || !$("preview").naturalWidth) return;
    e.preventDefault();
    if (Date.now() < gestureUntil) return;
    const pinch = e.ctrlKey || e.metaKey;
    const delta = Math.max(-120, Math.min(120, wheelPixels(e)));
    zoomBy(Math.exp(-delta / (pinch ? 120 : 400)), e);
  },
  { passive: false },
);
let gestureBase = 1;
$("canvasScroll").addEventListener("gesturestart", (e) => {
  if (!current || !$("preview").naturalWidth) return;
  e.preventDefault();
  gestureUntil = Infinity;
  gestureBase = currentScale();
});
$("canvasScroll").addEventListener("gesturechange", (e) => {
  if (gestureUntil !== Infinity) return;
  e.preventDefault();
  clampZoom(gestureBase * e.scale, e);
});
for (const type of ["gestureend", "gesturecancel"])
  $("canvasScroll").addEventListener(type, (e) => {
    if (gestureUntil !== Infinity) return;
    e.preventDefault();
    // WebKit trails a pinch with wheel events; ignore those for a moment.
    gestureUntil = Date.now() + 250;
  });
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
  if (library && cropping) $("cropCancel").click();
  renderStrip();
  if (!library) applyZoom();
}
$("libraryTab").onclick = () => setView(true);
$("allPhotos").onclick = () => setView(true);
$("editTab").onclick = () => setView(false);
$("exportTop").onclick = () => {
  if (!photos.length) return toast("내보낼 사진이 없습니다.");
  $("exportScope").value = current ? "current" : "all";
  syncExportScope();
  syncQualityLabel();
  $("exportDialog").showModal();
};
$("cancelExport").onclick = () => $("exportDialog").close();
$("quality").oninput = (e) => ($("qualityValue").textContent = e.target.value);
// WebP is lossy too, so it gets the same quality slider — with its own name.
function syncQualityLabel() {
  const format = $("exportFormat").value;
  $("qualityLabel").hidden = !["jpeg", "webp"].includes(format);
  $("qualityLabel").firstChild.textContent =
    (format === "webp" ? "WebP" : "JPEG") + " 품질 ";
}
$("exportFormat").onchange = syncQualityLabel;
function exportSuffix(format) {
  return format === "jpeg" ? ".jpg" : format === "tiff" ? ".tif" : "." + format;
}
function exportFilename(photo, format) {
  return (
    photo.name.replace(/\.[^.]+$/, "") + "-나만의빛" + exportSuffix(format)
  );
}
function exportTargets() {
  const scope = $("exportScope").value;
  if (scope === "all") return photos;
  if (scope === "selected") return photos.filter((p) => selected.has(p.id));
  return current ? [current] : [];
}
function syncExportScope() {
  const picked = photos.filter((p) => selected.has(p.id)).length;
  $("exportScope").options[1].textContent = `선택한 사진 (${picked}장)`;
  $("exportScope").options[1].disabled = picked === 0;
  $("exportScope").options[2].textContent = `전체 사진 (${photos.length}장)`;
  $("exportScope").options[2].disabled = photos.length === 0;
  if (!current && $("exportScope").value === "current")
    $("exportScope").value = photos.length ? "all" : "current";
  const count = exportTargets().length;
  $("exportNote").textContent =
    count > 1
      ? `${count}장을 폴더에 저장합니다 · sRGB 색상 프로필 포함 · 각 사진의 저장된 보정값 적용`
      : "sRGB 색상 프로필 포함 · 현재 보정 및 자르기 적용";
  $("download").disabled = count === 0;
}
$("exportScope").onchange = syncExportScope;

async function pollExport(job, total) {
  // The render runs in another process, so this stays responsive while it works.
  for (;;) {
    await new Promise((r) => setTimeout(r, 350));
    const state = await (await api(`/api/export/${job}`)).json();
    const done = Math.min(state.done, total);
    $("exportBar").style.width = Math.round((done / total) * 100) + "%";
    $("exportProgressText").textContent =
      total > 1
        ? `${done} / ${total}장 · ${state.current ?? "마무리 중"}`
        : state.current
          ? `${state.current} 현상 중…`
          : "마무리 중…";
    $("exportElapsed").textContent = `${state.elapsed.toFixed(0)}초 경과`;
    if (total > 1)
      busy(true, "사진을 내보내는 중", done / total, state.current ?? "");
    if (state.finished) return state;
  }
}

$("download").onclick = async () => {
  const targets = exportTargets();
  if (!targets.length) return;
  const format = $("exportFormat").value,
    size = Number($("exportSize").value),
    many = targets.length > 1;
  let dest = null,
    folder = null;
  if (shell.api) {
    try {
      dest = many
        ? null
        : await shell.api.save_dialog(
            exportFilename(targets[0], format),
            format,
          );
      folder = many ? await shell.api.folder_dialog() : null;
    } catch {
      dest = folder = null;
    }
    if (many ? !folder : !dest) return; // the native panel was cancelled
  }
  $("download").disabled = $("cancelExport").disabled = true;
  $("exportProgress").hidden = false;
  $("exportBar").style.width = "0%";
  $("exportProgressText").textContent = many
    ? `0 / ${targets.length}장`
    : size
      ? `긴 변 ${size.toLocaleString()} px로 현상 중…`
      : "원본 크기로 현상 중… 큰 RAW는 시간이 걸립니다";
  if (many) busy(true, "사진을 내보내는 중", 0);
  try {
    const started = await (
      await api(
        "/api/export",
        json("POST", {
          photos: targets.map((p) => ({
            id: p.id,
            settings: p.id === current?.id ? settings : p.settings,
          })),
          format,
          quality: Number($("quality").value),
          long_edge: size,
          dest,
          folder,
        }),
      )
    ).json();
    const state = await pollExport(started.job, targets.length);
    $("exportDialog").close();
    if (state.failed.length)
      toast(
        `${state.written.length}장 저장, ${state.failed.length}장 실패\n` +
          state.failed
            .slice(0, 5)
            .map((f) => `${f.name}: ${f.error}`)
            .join("\n"),
      );
    if (!shell.api) {
      // Browser mode hands back one rendered image to download.
      const blob = await (await api(`/api/export/${started.job}/file`)).blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = exportFilename(targets[0], format);
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 60000);
      if (!state.failed.length) toast("보정된 사진을 내보냈습니다.");
    } else if (!state.failed.length) {
      const where = folder ?? dest;
      toast(
        many
          ? `${state.written.length}장을 저장했습니다.`
          : `저장했습니다 · ${String(where).split(/[\\/]/).pop()}`,
        {
          label: "폴더에서 보기",
          run: () => shell.api?.reveal(state.written[0] ?? where),
        },
      );
    }
  } catch (e) {
    toast(e.message);
  } finally {
    $("download").disabled = $("cancelExport").disabled = false;
    $("exportProgress").hidden = true;
    busy(false);
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
  ["휠 · 트랙패드 핀치", "커서 위치 기준 확대 · 축소"],
  ["드래그", "확대했을 때 사진 옮기기"],
  ["R", "오른쪽 90° 회전"],
  ["I", "사진 정보"],
  ["C", "자르기 도구 열기 · 적용"],
  ["⌫", "선택한 사진 삭제"],
  [`${MOD} ⇧ A`, "라이브러리에서 모두 선택"],
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
    if (e.shiftKey && e.key.toLowerCase() === "a")
      return (e.preventDefault(), $("selectAll").click());
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
  if (e.key.toLowerCase() === "c") $("cropTool").click();
  if (e.key === "Escape" && cropping) $("cropCancel").click();
  if (e.key === "Enter" && cropping) $("cropApply").click();
  if (e.key === "Delete" || e.key === "Backspace") {
    e.preventDefault();
    selected.size > 1 ? $("deleteSelected").click() : $("deletePhoto").click();
  }
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
