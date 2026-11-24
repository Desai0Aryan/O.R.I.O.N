const $ = (id) => document.getElementById(id);

chrome.storage.local.get({ port: 8765, token: "" }).then((c) => {
  $("token").value = c.token;
  $("port").value = c.port;
});

$("save").addEventListener("click", async () => {
  const token = $("token").value.trim();
  const port = parseInt($("port").value, 10) || 8765;
  await chrome.storage.local.set({ token, port });
  try {
    const r = await fetch(`http://127.0.0.1:${port}/ping`, { headers: { "X-Orion-Token": token } });
    $("msg").textContent = r.ok ? "Connected to Orion." : r.status === 401 ? "Orion says that token is wrong." : "Orion answered with an error.";
    $("msg").style.color = r.ok ? "#6df0b0" : "#ff9a9a";
  } catch (e) {
    $("msg").textContent = "Can't reach Orion. Is it running?";
    $("msg").style.color = "#ff9a9a";
  }
});
