"use strict";
const test = require("node:test");
const assert = require("node:assert");
const { saveDialogOptions, attach } = require("../downloads");

test("every download gets a Save As window with a sensible default name", () => {
  const o = saveDialogOptions("My Video.mp4", "/home/me/Downloads");
  assert.match(o.defaultPath, /My Video\.mp4$/);
  assert.strictEqual(o.filters[0].extensions[0], "mp4");
  assert.ok(o.title);
});

test("a path in the file name cannot escape the downloads folder", () => {
  const o = saveDialogOptions("../../evil.mp4", "/home/me/Downloads");
  assert.ok(o.defaultPath.endsWith("evil.mp4") && !o.defaultPath.includes(".."));
});

test("attach sets the dialog options and never a silent save path", () => {
  let handler;
  attach({ on: (_n, fn) => { handler = fn; } }, () => "/d");
  const item = { getFilename: () => "a.mp4", setSaveDialogOptions(o) { this.opts = o; }, setSavePath() { throw new Error("silent save"); } };
  handler({}, item);
  assert.ok(item.opts.defaultPath.endsWith("a.mp4"));
});
