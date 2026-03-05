const authSection = document.getElementById("auth-section");
const appSection = document.getElementById("app-section");
const form = document.getElementById("search-form");
const input = document.getElementById("playlist-url");
const btn = document.getElementById("search-btn");
const statusEl = document.getElementById("status");
const resultsSection = document.getElementById("results-section");
const resultsCount = document.getElementById("results-count");
const tbody = document.getElementById("results-body");
const progressBar = document.getElementById("progress-bar");
const progressFill = document.getElementById("progress-fill");
const copyLinksBtn = document.getElementById("copy-links-btn");

let total = 0;
let found = 0;
let source = null;
let allLinks = [];

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

function resetButtons() {
  btn.disabled = false;
  btn.textContent = "Search";
}

function showError(msg) {
  statusEl.textContent = msg;
  statusEl.classList.add("status-error");
}

form.addEventListener("submit", (e) => {
  e.preventDefault();
  const url = input.value.trim();
  if (!url) return;

  if (!url.match(/spotify\.com\/playlist\//)) {
    showError("Please enter a valid Spotify playlist URL.");
    return;
  }

  // Reset
  tbody.innerHTML = "";
  resultsSection.classList.remove("hidden");
  btn.disabled = true;
  btn.textContent = "Searching...";
  total = 0;
  found = 0;
  allLinks = [];
  copyLinksBtn.classList.add("hidden");
  resultsCount.textContent = "";
  statusEl.textContent = "Connecting...";
  statusEl.classList.remove("status-error");
  progressBar.classList.remove("hidden");
  progressFill.style.width = "0%";

  const encoded = encodeURIComponent(url);
  source = new EventSource(`/api/search?playlist_url=${encoded}`);

  source.addEventListener("total", (e) => {
    const data = JSON.parse(e.data);
    total = data.total;
    statusEl.textContent = `Found ${total} tracks. Searching Bandcamp & Beatport...`;
  });

  source.addEventListener("track", (e) => {
    const data = JSON.parse(e.data);
    if (data.bandcamp_link) {
      found++;
      allLinks.push(data.bandcamp_link);
    }
    if (data.beatport_link) {
      if (!data.bandcamp_link) found++;
      allLinks.push(data.beatport_link);
    }
    statusEl.textContent = `Searching ${data.index} of ${total}...`;
    resultsCount.textContent = `${found} found`;
    if (total > 0) {
      progressFill.style.width = `${(data.index / total) * 100}%`;
    }

    const row = document.createElement("tr");
    const bcCell = data.bandcamp_link
      ? `<a href="${escapeAttr(data.bandcamp_link)}" target="_blank" rel="noopener">${escapeHtml(data.bandcamp_link)}</a>`
      : `<span class="not-found">Not found</span>`;
    const bpCell = data.beatport_link
      ? `<a href="${escapeAttr(data.beatport_link)}" target="_blank" rel="noopener" class="beatport-link">${escapeHtml(data.beatport_link)}</a>`
      : `<span class="not-found">Not found</span>`;

    row.innerHTML = `
      <td>${data.index}</td>
      <td>${escapeHtml(data.artist)}</td>
      <td>${escapeHtml(data.track)}</td>
      <td>${bcCell}</td>
      <td>${bpCell}</td>
    `;
    tbody.appendChild(row);
  });

  source.addEventListener("done", () => {
    source.close();
    source = null;
    resetButtons();
    progressFill.style.width = "100%";
    statusEl.textContent = `Done! ${found}/${total} tracks found.`;
    resultsCount.textContent = `${found} of ${total} found`;
    if (allLinks.length > 0) {
      copyLinksBtn.classList.remove("hidden");
    }
  });

  source.addEventListener("search_error", (e) => {
    source.close();
    source = null;
    resetButtons();
    const data = JSON.parse(e.data);
    showError(data.message || "An error occurred during search.");
  });

  source.addEventListener("error", () => {
    source.close();
    source = null;
    resetButtons();
    showError("Error connecting to server.");
  });
});

copyLinksBtn.addEventListener("click", () => {
  navigator.clipboard.writeText(allLinks.join("\n")).then(() => {
    copyLinksBtn.textContent = "Copied!";
    copyLinksBtn.classList.add("copied");
    setTimeout(() => {
      copyLinksBtn.textContent = "Copy all links";
      copyLinksBtn.classList.remove("copied");
    }, 2000);
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
