// Run: NODE_PATH=/tmp/lightloom-testdeps/node_modules node tests/frontend.cjs
const { JSDOM } = require("jsdom");
const fs = require("node:fs");
const assert = require("node:assert/strict");
const calls = [];
const photo = {
  id: "fixture",
  name: "test.nef",
  width: 6000,
  height: 4000,
  size: 24000000,
  raw: true,
  settings: { exposure: 0 },
};
const dom = new JSDOM(fs.readFileSync("static/index.html", "utf8"), {
  url: "http://localhost",
  runScripts: "outside-only",
  pretendToBeVisual: true,
});
const w = dom.window;
const SAVED = "/Users/me/Pictures/test-나만의빛.jpg";
let jobPolls = 0;
w.fetch = async (url, opts = {}) => {
  calls.push({ url, ...opts });
  const body = () => {
    if (url === "/api/photos") return [photo];
    if (url === "/api/export") return { job: "job1", total: 1 };
    if (url.startsWith("/api/export/job1")) {
      // Report one unfinished poll first so the progress path is exercised.
      jobPolls++;
      return {
        id: "job1",
        total: 1,
        done: jobPolls > 1 ? 1 : 0,
        current: jobPolls > 1 ? null : photo.name,
        written: jobPolls > 1 ? [SAVED] : [],
        failed: [],
        finished: jobPolls > 1,
        elapsed: 0.4 * jobPolls,
      };
    }
    return { path: SAVED };
  };
  return {
    ok: true,
    json: async () => body(),
    blob: async () => new w.Blob(["x"]),
  };
};
w.URL.createObjectURL = () => "blob:test";
w.URL.revokeObjectURL = () => {};
const { execFileSync } = require("node:child_process");
w.ADVANCED = JSON.parse(
  execFileSync(
    ".venv/bin/python",
    [
      "-c",
      "import json;from adjustments import ui_config;print(json.dumps(ui_config()))",
    ],
    { encoding: "utf8" },
  ),
);
w.HTMLCanvasElement.prototype.getContext = () => null;
// jsdom 29 ships <dialog> without its methods.
for (const dialog of w.document.querySelectorAll("dialog")) {
  dialog.showModal = () => dialog.setAttribute("open", "");
  dialog.close = () => dialog.removeAttribute("open");
}
const vm = require("node:vm");
vm.runInContext(
  fs.readFileSync("static/curves.js", "utf8"),
  dom.getInternalVMContext(),
);
vm.runInContext(
  fs.readFileSync("static/app.js", "utf8"),
  dom.getInternalVMContext(),
);
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
(async () => {
  await wait(20);
  assert.equal(
    w.document.getElementById("currentName").textContent,
    "test.nef",
  );
  assert.equal(w.document.querySelectorAll(".thumb").length, 1);
  w.document.querySelectorAll("#presets .preset")[1].click();
  assert.equal(w.document.getElementById("s-temperature").value, "28");
  await wait(20);
  assert(
    calls.some(
      (c) => c.method === "PUT" && JSON.parse(c.body).temperature === 28,
    ),
  );
  w.document.getElementById("undo").click();
  assert.equal(w.document.getElementById("s-temperature").value, "0");
  w.document.getElementById("redo").click();
  assert.equal(w.document.getElementById("s-temperature").value, "28");
  w.document.getElementById("rotate").click();
  const crop = w.document.getElementById("crop");
  crop.value = "1:1";
  crop.dispatchEvent(new w.Event("change"));
  await wait(20);
  assert(
    calls.some(
      (c) =>
        c.method === "PUT" &&
        JSON.parse(c.body).crop === "1:1" &&
        JSON.parse(c.body).rotation === 1,
    ),
  );
  w.document.getElementById("compare").click();
  await wait(20);
  const last = calls.filter((c) => c.url.endsWith("/preview")).at(-1);
  assert.equal(JSON.parse(last.body).temperature, 0);
  w.document.getElementById("curveAdd").click();
  const output = w.document.getElementById("curveY");
  output.value = "190";
  output.dispatchEvent(new w.Event("change"));
  await wait(20);
  assert(
    calls.some(
      (c) =>
        c.method === "PUT" &&
        JSON.parse(c.body).curve_rgb.some((p) => p[1] === 190),
    ),
  );
  w.document.getElementById("undo").click();
  assert.equal(w.document.getElementById("curveY").value, "127.5");
  const radius = w.document.getElementById("s-sharpen_radius");
  radius.value = "2.5";
  radius.dispatchEvent(new w.Event("input"));
  radius.dispatchEvent(new w.Event("change"));
  assert.equal(
    w.document.getElementById("v-sharpen_radius").textContent,
    "+2.5",
  );
  const search = w.document.getElementById("controlSearch");
  search.value = "노이즈";
  search.dispatchEvent(new w.Event("input"));
  assert(
    [...w.document.querySelectorAll("#controls>details")]
      .filter((p) => !p.hidden)
      .every((p) => p.textContent.includes("노이즈")),
  );
  // A panel keeps a marker while it still holds edits.
  const light = [...w.document.querySelectorAll("#controls>details")].find(
    (p) => p.querySelector("#s-exposure"),
  );
  const exposure = w.document.getElementById("s-exposure");
  exposure.value = "1";
  exposure.dispatchEvent(new w.Event("input"));
  assert(light.classList.contains("touched"));

  w.document.getElementById("reset").click();
  assert.equal(w.document.getElementById("s-temperature").value, "0");
  assert(!light.classList.contains("touched"));

  // Searching for something absent explains itself instead of showing nothing.
  search.value = "존재하지않는보정";
  search.dispatchEvent(new w.Event("input"));
  assert.equal(w.document.getElementById("searchEmpty").hidden, false);
  search.value = "";
  search.dispatchEvent(new w.Event("input"));
  assert.equal(w.document.getElementById("searchEmpty").hidden, true);

  // Zoom: fit by default, then an explicit 100% that scrolls the proxy.
  assert(w.document.getElementById("fit").classList.contains("active"));
  w.document.getElementById("zoom").click();
  assert(w.document.getElementById("preview").classList.contains("zoomed"));
  assert.equal(w.document.getElementById("zoomLevel").textContent, "100%");
  w.document.getElementById("fit").click();
  assert(!w.document.getElementById("preview").classList.contains("zoomed"));

  // Wheel and trackpad pinch zoom around the cursor; jsdom has no layout, so
  // the preview reports a size the way a loaded image would.
  const preview = w.document.getElementById("preview");
  for (const [prop, value] of [
    ["naturalWidth", 1600],
    ["naturalHeight", 1067],
  ])
    Object.defineProperty(preview, prop, { value, configurable: true });
  const canvas = w.document.getElementById("canvasScroll");
  const wheel = (init) =>
    canvas.dispatchEvent(
      new w.WheelEvent("wheel", {
        cancelable: true,
        clientX: 400,
        clientY: 300,
        ...init,
      }),
    );

  wheel({ deltaY: -120 });
  assert(preview.classList.contains("zoomed"));
  const zoomedIn = Number(
    w.document.getElementById("zoomLevel").textContent.replace("%", ""),
  );
  assert(zoomedIn > 100, `wheel up should zoom in, got ${zoomedIn}%`);

  // A pinch moves faster than the same wheel delta.
  w.document.getElementById("fit").click();
  wheel({ deltaY: -120, ctrlKey: true });
  const pinched = Number(
    w.document.getElementById("zoomLevel").textContent.replace("%", ""),
  );
  assert(pinched > zoomedIn, `pinch should outpace the wheel, got ${pinched}%`);

  // Zooming back out past the fitted ratio returns to 화면 맞춤.
  for (let i = 0; i < 20 && preview.classList.contains("zoomed"); i++)
    wheel({ deltaY: 120 });
  assert(!preview.classList.contains("zoomed"));
  assert(w.document.getElementById("fit").classList.contains("active"));

  // WebKit's own pinch events carry an absolute scale.
  const gesture = (type, scale) => {
    const event = new w.Event(type, { cancelable: true });
    Object.assign(event, { scale, clientX: 400, clientY: 300 });
    canvas.dispatchEvent(event);
  };
  gesture("gesturestart", 1);
  gesture("gesturechange", 2.5);
  assert.equal(w.document.getElementById("zoomLevel").textContent, "250%");
  gesture("gestureend", 2.5);
  // Trailing wheel events right after a pinch are ignored.
  wheel({ deltaY: -120 });
  assert.equal(w.document.getElementById("zoomLevel").textContent, "250%");
  w.document.getElementById("fit").click();

  // Desktop shell: export asks for a path and posts it instead of downloading.
  let asked = null;
  let revealed = null;
  w.pywebview = {
    api: {
      save_dialog: async (name, format) => {
        asked = { name, format };
        return "/Users/me/Pictures/test-나만의빛.jpg";
      },
      reveal: (path) => (revealed = path),
    },
  };
  w.dispatchEvent(new w.Event("pywebviewready"));
  assert(w.document.body.classList.contains("desktop"));
  w.document.getElementById("exportTop").click();
  w.document.getElementById("download").click();
  await wait(1200);
  assert.deepEqual(asked, { name: "test-나만의빛.jpg", format: "jpeg" });
  const exported = calls.filter((c) => c.url === "/api/export").at(-1);
  const sent = JSON.parse(exported.body);
  assert.equal(sent.dest, SAVED);
  assert.equal(sent.photos.length, 1);
  assert.equal(sent.photos[0].id, photo.id);
  assert(
    jobPolls >= 2,
    `job should be polled until finished, polled ${jobPolls}`,
  );
  w.document.getElementById("toastAction").click();
  assert.equal(revealed, SAVED);

  // WebP joins the format list and keeps the quality slider, named for it.
  const fmt = w.document.getElementById("exportFormat");
  assert([...fmt.options].some((o) => o.value === "webp"));
  const qualityLabel = w.document.getElementById("qualityLabel");
  for (const [format, visible, name] of [
    ["webp", true, "WebP 품질 "],
    ["png", false, null],
    ["jpeg", true, "JPEG 품질 "],
  ]) {
    fmt.value = format;
    fmt.dispatchEvent(new w.Event("change"));
    assert.equal(qualityLabel.hidden, !visible, `${format} quality visibility`);
    if (name) assert.equal(qualityLabel.firstChild.textContent, name);
  }

  // The crop tool works on fractions of the frame and survives apply.
  w.document.getElementById("cropTool").click();
  await wait(60);
  assert.equal(w.document.getElementById("cropOverlay").hidden, false);
  const ratio = w.document.getElementById("crop");
  ratio.value = "1:1";
  ratio.dispatchEvent(new w.Event("change"));
  w.document.getElementById("cropApply").click();
  await wait(60);
  const cropped = calls
    .filter((c) => c.method === "PUT")
    .map((c) => JSON.parse(c.body))
    .at(-1);
  // A 6000x4000 frame squared off leaves two thirds of the width, centred.
  assert(
    Math.abs(cropped.crop_w - 2 / 3) < 0.01,
    `crop_w was ${cropped.crop_w}`,
  );
  assert.equal(cropped.crop_h, 1);
  assert(
    Math.abs(cropped.crop_x - 1 / 6) < 0.01,
    `crop_x was ${cropped.crop_x}`,
  );
  assert.equal(w.document.getElementById("cropOverlay").hidden, true);

  // Deleting asks first, then drops the photo from the library.
  w.document.getElementById("deletePhoto").click();
  await wait(30);
  assert.equal(
    w.document.getElementById("confirmDialog").hasAttribute("open"),
    true,
  );
  w.document.getElementById("confirmOk").click();
  await wait(60);
  assert(
    calls.some(
      (c) => c.method === "DELETE" && c.url === `/api/photos/${photo.id}`,
    ),
  );
  assert.equal(w.document.querySelectorAll(".thumb").length, 0);
  assert.equal(
    w.document.getElementById("currentName").textContent,
    "새로운 작업",
  );

  await wait(220);
  console.log(
    "PASS: selection, presets, autosave, undo/redo, rotate, compare, reset, panel markers, search, zoom (buttons, wheel, pinch), crop tool, batch export with progress, webp, delete",
  );
  w.close();
})().catch((e) => {
  console.error(e);
  w.close();
  process.exitCode = 1;
});
