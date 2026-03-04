const authSection = document.getElementById("auth-section");
const appSection = document.getElementById("app-section");
const form = document.getElementById("search-form");
const input = document.getElementById("playlist-url");
const btn = document.getElementById("search-btn");
const status = document.getElementById("status");
const results = document.getElementById("results");
const tbody = document.getElementById("results-body");

let total = 0;
let found = 0;

// Check auth status on load
async function checkAuth() {
  try {
    const res = await fetch("/api/auth/status");
    const data = await res.json();
    if (data.logged_in) {
      authSection.classList.add("hidden");
      appSection.classList.remove("hidden");
    } else {
      authSection.classList.remove("hidden");
      appSection.classList.add("hidden");
    }
  } catch {
    authSection.classList.remove("hidden");
    appSection.classList.add("hidden");
  }
}

checkAuth();

form.addEventListener("submit", (e) => {
  e.preventDefault();
  const url = input.value.trim();
  if (!url) return;

  if (!url.match(/spotify\.com\/playlist\//)) {
    status.textContent = "Please enter a valid Spotify playlist URL.";
    return;
  }

  // Reset
  tbody.innerHTML = "";
  results.classList.remove("hidden");
  btn.disabled = true;
  btn.textContent = "Searching...";
  total = 0;
  found = 0;
  status.textContent = "Connecting...";

  const encoded = encodeURIComponent(url);
  const source = new EventSource(`/api/search?playlist_url=${encoded}`);

  source.addEventListener("total", (e) => {
    const data = JSON.parse(e.data);
    total = data.total;
    status.textContent = `Found ${total} tracks. Searching Bandcamp...`;
  });

  source.addEventListener("track", (e) => {
    const data = JSON.parse(e.data);
    if (data.link) found++;
    status.textContent = `Searching ${data.index}/${total}... (${found} found)`;

    const row = document.createElement("tr");
    const linkCell = data.link
      ? `<a href="${escapeAttr(data.link)}" target="_blank" rel="noopener">${escapeHtml(data.link)}</a>`
      : `<span class="not-found">Not found</span>`;

    row.innerHTML = `
      <td>${data.index}</td>
      <td>${escapeHtml(data.artist)}</td>
      <td>${escapeHtml(data.track)}</td>
      <td>${linkCell}</td>
    `;
    tbody.appendChild(row);
  });

  source.addEventListener("done", () => {
    source.close();
    btn.disabled = false;
    btn.textContent = "Search";
    status.textContent = `Done! Found ${found}/${total} tracks on Bandcamp.`;
  });

  source.addEventListener("error", () => {
    source.close();
    btn.disabled = false;
    btn.textContent = "Search";
    status.textContent = "Error connecting to server.";
  });
});

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

function escapeAttr(text) {
  return text.replace(/&/g, "&amp;").replace(/"/g, "&quot;");
}
