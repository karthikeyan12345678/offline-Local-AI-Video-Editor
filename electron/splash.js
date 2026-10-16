"use strict";
const $ = (id) => document.getElementById(id);
window.splash.onStatus((s) => {
  $("fail").hidden = !s.error;
  $("bar").hidden = !!s.error;
  $("first").hidden = !s.firstRun || !!s.error;
  if (s.error) { $("stage").textContent = "Setup stopped"; $("err").textContent = s.error; $("detail").textContent = ""; return; }
  $("stage").textContent = s.stage || "Starting…";
  $("detail").textContent = s.detail || "";
  const bar = $("bar");
  if (typeof s.fraction === "number") {
    bar.classList.remove("progress--indeterminate");
    bar.firstElementChild.style.width = Math.round(s.fraction * 100) + "%";
    bar.setAttribute("aria-valuenow", String(Math.round(s.fraction * 100)));
  } else {
    bar.classList.add("progress--indeterminate");
    bar.firstElementChild.style.width = "";
  }
});
$("retry").addEventListener("click", () => window.splash.retry());
$("log").addEventListener("click", () => window.splash.openLog());
$("quit").addEventListener("click", () => window.splash.quit());
