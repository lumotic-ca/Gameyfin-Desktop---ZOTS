"use strict";

function api() {
  return window.pywebview && window.pywebview.api ? window.pywebview.api : null;
}

function setErr(msg) {
  var el = document.getElementById("err");
  el.textContent = msg || "";
}

async function init() {
  var a = api();
  if (!a) {
    setTimeout(init, 50);
    return;
  }
  try {
    var raw = await a.get_settings();
    var s = JSON.parse(raw);
    var input = document.getElementById("server-url");
    if (s.GF_URL) input.value = s.GF_URL;
    input.focus();
    input.select();
  } catch (e) {
    console.error(e);
  }
}

document.getElementById("setup-form").addEventListener("submit", async function (e) {
  e.preventDefault();
  setErr("");
  var a = api();
  if (!a) {
    setErr("Application bridge not ready.");
    return;
  }
  var url = document.getElementById("server-url").value.trim();
  var btn = document.getElementById("btn-connect");
  btn.disabled = true;
  try {
    var res = JSON.parse(await a.complete_server_setup(url));
    if (!res.ok) setErr(res.error || "Could not connect.");
  } catch (err) {
    setErr(String(err));
  } finally {
    btn.disabled = false;
  }
});

document.getElementById("btn-panel").addEventListener("click", async function () {
  var a = api();
  if (a && a.show_panel) await a.show_panel();
});

window.addEventListener("pywebviewready", init);
if (window.pywebview) init();
