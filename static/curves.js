// Curve points are replaced immutably so undo snapshots never share mutations.
let curveChannel = "rgb",
  curveSelection = 0;
function initCurveEditor() {
  const panel = document.createElement("details");
  panel.id = "curvePanel";
  panel.innerHTML = `<summary>포인트 톤 커브</summary>
    <div class="curve-channels" role="group" aria-label="커브 채널">
    ${[
      ["rgb", "RGB"],
      ["red", "R"],
      ["green", "G"],
      ["blue", "B"],
    ]
      .map(
        ([key, label]) =>
          `<button data-channel="${key}" class="${key === "rgb" ? "active" : ""}">${label}</button>`,
      )
      .join("")}</div>
    <canvas id="curveCanvas" width="480" height="360" aria-label="포인트 톤 커브. 아래 입력과 출력 좌표로도 편집할 수 있습니다."></canvas>
    <p class="control-help">클릭해 점 추가 · 드래그해 이동</p>
    <div class="curve-coordinates"><label>입력 <input id="curveX" type="number" min="0" max="255" step="1"></label><label>출력 <input id="curveY" type="number" min="0" max="255" step="1"></label></div>
    <div class="curve-actions"><button id="curveAdd">＋ 점 추가</button><button id="curveDelete">점 삭제</button><button id="curveReset">채널 초기화</button></div>`;
  $("controls").insertBefore(panel, $("controls").children[2]);
  panel.querySelectorAll("[data-channel]").forEach(
    (b) =>
      (b.onclick = () => {
        curveChannel = b.dataset.channel;
        curveSelection = 0;
        syncCurve();
      }),
  );
  const points = () => settings["curve_" + curveChannel];
  const replace = (next) => {
    settings["curve_" + curveChannel] = next;
    changed();
  };
  $("curveX").onchange = () => editCoordinate(0);
  $("curveY").onchange = () => editCoordinate(1);
  function editCoordinate(axis) {
    if (!current) return;
    const p = points().map((p) => [...p]);
    curveSelection = Math.min(curveSelection, p.length - 1);
    const value = Number($(axis ? "curveY" : "curveX").value);
    if (!Number.isFinite(value)) return syncCurve();
    const low = axis ? 0 : curveSelection ? p[curveSelection - 1][0] + 0.1 : 0;
    const high = axis
      ? 255
      : curveSelection < p.length - 1
        ? p[curveSelection + 1][0] - 0.1
        : 255;
    checkpoint();
    p[curveSelection][axis] = Math.max(low, Math.min(high, value));
    replace(p);
  }
  $("curveAdd").onclick = () => {
    if (!current || points().length >= 32) return;
    const p = points().map((p) => [...p]);
    let gap = 0,
      index = 0;
    for (let i = 0; i < p.length - 1; i++)
      if (p[i + 1][0] - p[i][0] > gap) {
        gap = p[i + 1][0] - p[i][0];
        index = i;
      }
    if (gap < 1) return;
    checkpoint();
    const next = [
      (p[index][0] + p[index + 1][0]) / 2,
      (p[index][1] + p[index + 1][1]) / 2,
    ];
    p.splice(index + 1, 0, next);
    curveSelection = index + 1;
    replace(p);
  };
  $("curveDelete").onclick = () => {
    if (!current || points().length <= 2) return;
    checkpoint();
    const p = points().filter((_, i) => i !== curveSelection);
    curveSelection = Math.max(0, curveSelection - 1);
    replace(p);
  };
  $("curveReset").onclick = () => {
    if (!current) return;
    checkpoint();
    curveSelection = 0;
    replace([
      [0, 0],
      [255, 255],
    ]);
  };
  const canvas = $("curveCanvas");
  let dragging = false;
  function position(e) {
    const b = canvas.getBoundingClientRect();
    return [
      Math.max(0, Math.min(255, ((e.clientX - b.left) / b.width) * 255)),
      Math.max(0, Math.min(255, 255 - ((e.clientY - b.top) / b.height) * 255)),
    ];
  }
  canvas.onpointerdown = (e) => {
    if (!current) return;
    e.preventDefault();
    const pos = position(e),
      p = points().map((p) => [...p]);
    let distance = Infinity,
      index = 0;
    p.forEach((point, i) => {
      const d = Math.hypot(point[0] - pos[0], point[1] - pos[1]);
      if (d < distance) {
        distance = d;
        index = i;
      }
    });
    checkpoint();
    if (
      distance > 16 &&
      p.length < 32 &&
      !p.some((point) => Math.abs(point[0] - pos[0]) < 1)
    ) {
      p.push(pos);
      p.sort((a, b) => a[0] - b[0]);
      index = p.indexOf(pos);
      settings["curve_" + curveChannel] = p;
    }
    curveSelection = index;
    dragging = true;
    canvas.setPointerCapture(e.pointerId);
    syncCurve();
  };
  canvas.onpointermove = (e) => {
    if (!dragging) return;
    const p = points().map((p) => [...p]),
      pos = position(e);
    const lo = curveSelection ? p[curveSelection - 1][0] + 0.1 : 0,
      hi = curveSelection < p.length - 1 ? p[curveSelection + 1][0] - 0.1 : 255;
    p[curveSelection] = [Math.max(lo, Math.min(hi, pos[0])), pos[1]];
    settings["curve_" + curveChannel] = p;
    before = false;
    $("compare").classList.remove("active");
    syncCurve();
    schedulePreview();
  };
  canvas.onpointerup = () => {
    if (dragging) {
      dragging = false;
      changed();
    }
  };
  canvas.onpointercancel = () => {
    if (dragging) {
      dragging = false;
      changed();
    }
  };
}
function syncCurve() {
  const canvas = $("curveCanvas");
  if (!canvas) return;
  const p = settings["curve_" + curveChannel] || [
    [0, 0],
    [255, 255],
  ];
  curveSelection = Math.min(curveSelection, p.length - 1);
  const ctx = canvas.getContext("2d");
  if (ctx) {
    const w = canvas.width,
      h = canvas.height;
    ctx.clearRect(0, 0, w, h);
    ctx.strokeStyle = "#41484a";
    ctx.lineWidth = 1;
    ctx.beginPath();
    for (let i = 0; i <= 4; i++) {
      ctx.moveTo((w * i) / 4, 0);
      ctx.lineTo((w * i) / 4, h);
      ctx.moveTo(0, (h * i) / 4);
      ctx.lineTo(w, (h * i) / 4);
    }
    ctx.stroke();
    ctx.strokeStyle = "#647070";
    ctx.beginPath();
    ctx.moveTo(0, h);
    ctx.lineTo(w, 0);
    ctx.stroke();
    ctx.strokeStyle = {
      rgb: "#d6b88b",
      red: "#e8877e",
      green: "#97c6a1",
      blue: "#89b3e1",
    }[curveChannel];
    ctx.lineWidth = 3;
    ctx.beginPath();
    ctx.moveTo(0, h - (p[0][1] / 255) * h);
    p.forEach(([x, y]) => ctx.lineTo((x / 255) * w, h - (y / 255) * h));
    ctx.lineTo(w, h - (p.at(-1)[1] / 255) * h);
    ctx.stroke();
    p.forEach(([x, y], i) => {
      ctx.beginPath();
      ctx.arc(
        (x / 255) * w,
        h - (y / 255) * h,
        i === curveSelection ? 7 : 5,
        0,
        Math.PI * 2,
      );
      ctx.fillStyle = i === curveSelection ? "#fff" : ctx.strokeStyle;
      ctx.fill();
    });
  }
  $("curveX").value = Math.round(p[curveSelection][0] * 10) / 10;
  $("curveY").value = Math.round(p[curveSelection][1] * 10) / 10;
  $("curveX").disabled = $("curveY").disabled = !current;
  $("curveAdd").disabled = !current || p.length >= 32;
  $("curveDelete").disabled = !current || p.length <= 2;
  $("curveReset").disabled = !current;
  document
    .querySelectorAll("[data-channel]")
    .forEach((b) =>
      b.classList.toggle("active", b.dataset.channel === curveChannel),
    );
}
