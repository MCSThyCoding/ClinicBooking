/* ClinicBook — front-end interactions (vanilla JS, no build step) */

const state = { doctorId: null, doctorName: "", fee: 0, date: null, time: null };

// ---------- tabs ----------
function activateTab(name) {
  document.querySelectorAll(".tab").forEach((b) =>
    b.classList.toggle("active", b.dataset.tab === name));
  document.querySelectorAll(".tab-pane").forEach((p) =>
    p.classList.toggle("hidden", p.id !== "tab-" + name));
  sessionStorage.setItem("tab", name);
}
document.querySelectorAll(".tab").forEach((btn) => {
  btn.addEventListener("click", () => activateTab(btn.dataset.tab));
});
// restore last-used tab after reload
const savedTab = sessionStorage.getItem("tab");
if (savedTab && document.getElementById("tab-" + savedTab)) activateTab(savedTab);

// ---------- booking flow ----------
const slotGrid = document.getElementById("slotGrid");
const btnContinue = document.getElementById("btnContinue");

function refreshContinue() {
  btnContinue.disabled = !(state.doctorId && state.date && state.time);
}

document.querySelectorAll(".doctor-card").forEach((card) => {
  card.addEventListener("click", () => {
    document.querySelectorAll(".doctor-card").forEach((c) => c.classList.remove("selected"));
    card.classList.add("selected");
    state.doctorId = card.dataset.id;
    state.doctorName = card.dataset.name;
    state.fee = parseFloat(card.dataset.fee);
    state.time = null;
    loadSlots();
    refreshContinue();
  });
});

document.querySelectorAll(".date-chip").forEach((chip) => {
  chip.addEventListener("click", () => {
    document.querySelectorAll(".date-chip").forEach((c) => c.classList.remove("selected"));
    chip.classList.add("selected");
    state.date = chip.dataset.date;
    state.time = null;
    loadSlots();
    refreshContinue();
  });
});

async function loadSlots() {
  slotGrid.innerHTML = '<p class="muted slot-hint">Loading times…</p>';
  if (!state.doctorId || !state.date) {
    slotGrid.innerHTML = '<p class="muted slot-hint">Pick a doctor and date to see times.</p>';
    return;
  }
  const res = await fetch(`/api/doctors/${state.doctorId}/slots?date=${state.date}`);
  const slots = await res.json();
  slotGrid.innerHTML = "";
  if (!slots.length) {
    slotGrid.innerHTML = '<p class="muted slot-hint">The doctor does not work this day.</p>';
    return;
  }
  slots.forEach((s) => {
    const b = document.createElement("button");
    b.className = "slot" + (s.available ? "" : " taken");
    b.textContent = s.time;
    if (s.available) {
      b.addEventListener("click", () => {
        document.querySelectorAll(".slot").forEach((x) => x.classList.remove("selected"));
        b.classList.add("selected");
        state.time = s.time;
        refreshContinue();
      });
    }
    slotGrid.appendChild(b);
  });
}

// ---------- deposit modal ----------
const payModal = document.getElementById("payModal");
let pendingApptId = null;

btnContinue?.addEventListener("click", async () => {
  btnContinue.disabled = true;
  const res = await fetch("/api/appointments", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ doctor_id: state.doctorId, date: state.date, time: state.time }),
  });
  const data = await res.json();
  if (!res.ok) {
    alert(data.error || "Booking failed");
    refreshContinue();
    return;
  }
  pendingApptId = data.appointment.id;
  const est = Math.round(state.fee * 0.5 * 100) / 100;
  document.getElementById("paySummary").textContent =
    `${state.doctorName} · ${state.date} at ${state.time}`;
  document.getElementById("payAmount").textContent = `$${est.toFixed(2)} deposit`;
  payModal.classList.remove("hidden");
});

document.getElementById("payCancel")?.addEventListener("click", () => {
  payModal.classList.add("hidden");
  location.reload();
});

document.getElementById("payConfirm")?.addEventListener("click", async () => {
  if (!pendingApptId) return;
  const res = await fetch(`/api/appointments/${pendingApptId}/pay`, { method: "POST" });
  const data = await res.json();
  if (res.ok) {
    alert(`Deposit of $${data.deposit.toFixed(2)} received. See you soon!`);
  }
  location.reload();
});

// ---------- my bookings: pay / cancel ----------
document.querySelectorAll(".btn-pay").forEach((btn) => {
  btn.addEventListener("click", async () => {
    const res = await fetch(`/api/appointments/${btn.dataset.id}/pay`, { method: "POST" });
    if (res.ok) location.reload();
    else alert("Payment failed");
  });
});
document.querySelectorAll(".btn-cancel").forEach((btn) => {
  btn.addEventListener("click", async () => {
    if (!confirm("Cancel this appointment?")) return;
    await fetch(`/api/appointments/${btn.dataset.id}/cancel`, { method: "POST" });
    location.reload();
  });
});

// ---------- doctor queue: status buttons ----------
document.querySelectorAll("[data-status]").forEach((btn) => {
  btn.addEventListener("click", async () => {
    const row = btn.closest("tr");
    await fetch(`/api/appointments/${row.dataset.id}/status`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status: btn.dataset.status }),
    });
    location.reload();
  });
});

// ---------- medical records ----------
document.querySelectorAll(".record-box").forEach((box) => {
  box.querySelector(".btn-save-rec").addEventListener("click", async () => {
    const statusEl = box.querySelector(".rec-status");
    statusEl.textContent = "Saving…";
    const res = await fetch("/api/records", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        appointment_id: box.dataset.appt,
        diagnosis: box.querySelector(".rec-diagnosis").value,
        prescription: box.querySelector(".rec-prescription").value,
        attachment_url: box.querySelector(".rec-attachment").value,
      }),
    });
    statusEl.textContent = res.ok ? "Saved ✓" : "Save failed";
    statusEl.classList.toggle("saved", res.ok);
  });
});
