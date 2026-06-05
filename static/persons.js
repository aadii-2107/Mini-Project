const contentEl = document.getElementById("content");
const searchInputEl = document.getElementById("searchInput");
let allPersons = [];

function renderPersons(persons) {
  if (!Array.isArray(persons) || persons.length === 0) {
    contentEl.innerHTML = '<p class="muted">No registered people found.</p>';
    return;
  }
  contentEl.innerHTML = persons.map((p) => `
    <div class="panel" id="person-${p.id}" style="margin-bottom:12px;">
      <div class="row" style="justify-content:space-between;flex-wrap:wrap;gap:8px;">
        <div>
          <strong style="font-size:1.05rem;">${p.name ?? ""}</strong>
          <span class="muted" style="margin-left:8px;font-size:0.88rem;">ID ${p.id} · ${p.photo_count ?? 0} photo(s)</span>
        </div>
        <div style="display:flex;gap:8px;flex-wrap:wrap;">
          <a class="btn" href="/collect?name=${encodeURIComponent(p.name ?? "")}">Collect 10+ Photos</a>
          <a class="btn btn-secondary" href="/upload?name=${encodeURIComponent(p.name ?? "")}">+ Add Photos</a>
          <button class="btn" style="background:#374151;" onclick="togglePhotos(${p.id})">🖼 View Photos</button>
          <button class="btn" style="background:#dc2626;" onclick="deletePerson(${p.id},'${(p.name??'').replace(/'/g,"\\'")}')">🗑 Delete Person</button>
        </div>
      </div>
      <div id="photos-${p.id}" style="display:none;margin-top:12px;"></div>
    </div>
  `).join("");
}

async function togglePhotos(personId) {
  const el = document.getElementById(`photos-${personId}`);
  if (el.style.display !== "none") { el.style.display = "none"; return; }
  el.style.display = "block";
  el.innerHTML = '<span class="muted">Loading photos...</span>';
  try {
    const res = await fetch(`/api/persons/${personId}/photos`);
    if (res.status === 401) { window.location.href = "/login"; return; }
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Failed");
    if (!data.photos || data.photos.length === 0) {
      el.innerHTML = '<span class="muted">No photos uploaded yet.</span>';
      return;
    }
    el.innerHTML = `
  <div style="display:flex;flex-wrap:wrap;gap:12px;">
    ${data.photos.map((name) => `
      <div style="background:#1f2937;border-radius:10px;overflow:hidden;width:150px;flex-shrink:0;">
        <img
          src="/api/persons/${personId}/photo/${encodeURIComponent(name)}"
          alt="${name}"
          style="width:150px;height:150px;object-fit:cover;display:block;"
          onerror="this.style.display='none';this.nextElementSibling.style.display='flex';"
        />
        <div style="display:none;width:150px;height:150px;align-items:center;justify-content:center;color:#6b7280;font-size:0.8rem;">No preview</div>
        <div style="padding:6px 8px;font-size:0.78rem;color:#94a3b8;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;" title="${name}">${name}</div>
        <div style="padding:0 8px 8px;">
          <button onclick="deletePhoto(${personId},'${name.replace(/'/g,"\\'")}', this)" style="width:100%;background:#dc2626;color:#fff;border:none;border-radius:6px;padding:5px 0;cursor:pointer;font-size:0.82rem;">🗑 Delete</button>
        </div>
      </div>
    `).join("")}
  </div>
`;
  } catch (err) {
    el.innerHTML = `<span class="err">Error: ${err.message}</span>`;
  }
}

async function deletePerson(id, name) {
  if (!confirm(`Delete "${name}" and ALL their photos? This cannot be undone.`)) return;
  try {
    const res = await fetch(`/api/persons/${id}`, { method: "DELETE" });
    if (res.status === 401) { window.location.href = "/login"; return; }
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Failed");
    document.getElementById(`person-${id}`)?.remove();
    allPersons = allPersons.filter((p) => p.id !== id);
  } catch (err) {
    alert("Delete failed: " + err.message);
  }
}

async function deletePhoto(personId, photoName, btn) {
  if (!confirm(`Delete photo "${photoName}"?`)) return;
  btn.disabled = true;
  btn.textContent = "Deleting...";
  try {
    const res = await fetch(`/api/persons/${personId}/photo/${encodeURIComponent(photoName)}`, { method: "DELETE" });
    if (res.status === 401) { window.location.href = "/login"; return; }
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Failed");
    btn.closest("div[style]").parentElement.remove();
    const badge = document.querySelector(`#person-${personId} .muted`);
    if (badge) {
      const match = badge.textContent.match(/(\d+) photo/);
      if (match) badge.textContent = badge.textContent.replace(/\d+ photo/, `${Math.max(0, parseInt(match[1]) - 1)} photo`);
    }
  } catch (err) {
    btn.disabled = false;
    btn.textContent = "🗑 Delete";
    alert("Delete failed: " + err.message);
  }
}

function applySearch() {
  const query = String(searchInputEl.value || "").trim().toLowerCase();
  renderPersons(query ? allPersons.filter((p) =>
    String(p.name || "").toLowerCase().includes(query) || String(p.id || "").includes(query)
  ) : allPersons);
}

async function loadPersons() {
  try {
    const res = await fetch("/api/persons");
    if (res.status === 401) { window.location.href = "/login"; return; }
    const persons = await res.json();
    if (!res.ok) throw new Error(persons.error || "Unable to load");
    allPersons = Array.isArray(persons) ? persons : [];
    applySearch();
  } catch (err) {
    contentEl.textContent = "Failed to load: " + err.message;
  }
}

searchInputEl.addEventListener("input", applySearch);
loadPersons();
