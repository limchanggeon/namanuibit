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
w.fetch = async (url, opts = {}) => {
  calls.push({ url, ...opts });
  return {
    ok: true,
    json: async () =>
      url === "/api/photos"
        ? [photo]
        : { path: "/Users/me/Pictures/test-나만의빛.jpg" },
    blob: async () => new w.Blob(["test"]),
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
  w.document.getElementById("download").click();
  await wait(40);
  assert.deepEqual(asked, { name: "test-나만의빛.jpg", format: "jpeg" });
  const exported = calls.filter((c) => c.url.endsWith("/export")).at(-1);
  assert.equal(
    JSON.parse(exported.body).dest,
    "/Users/me/Pictures/test-나만의빛.jpg",
  );
  w.document.getElementById("toastAction").click();
  assert.equal(revealed, "/Users/me/Pictures/test-나만의빛.jpg");

  await wait(220);
  console.log(
    "PASS: photo selection, preset apply, autosave, undo/redo, rotate/crop, original comparison, reset, panel markers, control search, zoom, native export",
  );
  w.close();
})().catch((e) => {
  console.error(e);
  w.close();
  process.exitCode = 1;
});
