/* ==========================================
   LIVE DASHBOARD PAGE CONTROLLER
   ========================================== */

let currentSelectedDate = new Date().toISOString().split('T')[0];
let activeRescheduleId = null;

document.addEventListener("DOMContentLoaded", () => {
    // 1. Hook up date filter
    const gridDateInput = document.getElementById("gridDateFilter");
    if (gridDateInput) {
        gridDateInput.value = currentSelectedDate;
        gridDateInput.addEventListener("change", (e) => {
            currentSelectedDate = e.target.value;
            loadDashboardData(currentSelectedDate);
        });
    }

    // 2. Load dashboard data initially
    loadDashboardData(currentSelectedDate);

    // 3. Setup reschedule form modal listeners
    const modal = document.getElementById("rescheduleModal");
    const closeBtn = document.querySelector(".close-modal");
    if (closeBtn && modal) {
        closeBtn.addEventListener("click", () => {
            modal.classList.remove("active");
        });
    }

    const rescheduleForm = document.getElementById("rescheduleForm");
    if (rescheduleForm) {
        rescheduleForm.addEventListener("submit", async (e) => {
            e.preventDefault();
            if (!activeRescheduleId) return;

            const date = document.getElementById("new_date").value;
            const start = document.getElementById("new_start").value;
            const end = document.getElementById("new_end").value;
            const reason = document.getElementById("reschedule_reason").value.trim();
            const notes = document.getElementById("reschedule_notes").value.trim();

            if (!date || !start || !end || !reason) {
                alert("Please fill in all required reschedule fields.");
                return;
            }

            try {
                const response = await fetch(`${API_BASE}/bookings/${activeRescheduleId}/reschedule`, {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json"
                    },
                    body: JSON.stringify({
                        interview_date: date,
                        start_time: start,
                        end_time: end,
                        reason: reason,
                        notes: notes,
                        performed_by: "Admin"
                    })
                });

                const data = await response.json();
                if (!response.ok) {
                    throw new Error(data.detail || "Failed to reschedule booking.");
                }

                modal.classList.remove("active");
                rescheduleForm.reset();
                showAlert("dashboardAlertContainer", `Booking successfully rescheduled! New Booking ID: ${data.BookingID}`, "success");
                loadDashboardData(currentSelectedDate);

            } catch (err) {
                alert(err.message);
            }
        });
    }
});

/**
 * Fetch and populate dashboard data.
 */
async function loadDashboardData(dateStr) {
    try {
        const response = await fetch(`${API_BASE}/admin/dashboard?date=${dateStr}`);
        if (!response.ok) {
            throw new Error("Failed to load dashboard payload.");
        }
        const data = await response.json();
        
        // 1. Populate stats cards
        document.getElementById("statTotal").innerText = data.stats.total;
        document.getElementById("statBooked").innerText = data.stats.booked;
        document.getElementById("statWaitlisted").innerText = data.stats.waitlisted;
        document.getElementById("statCompleted").innerText = data.stats.completed;
        document.getElementById("statCancelled").innerText = data.stats.cancelled;
        document.getElementById("statNoShow").innerText = data.stats.noshow;

        // 2. Render Panel visual Grid
        renderPanelGrid(data.panel_grid_headers, data.panel_grid_rows);

        // 3. Render Bookings Detailed Table
        renderBookingsTable(data.bookings);

    } catch (err) {
        console.error(err);
        showAlert("dashboardAlertContainer", "Error loading real-time dashboard data from sheets: " + err.message, "error");
    }
}

/**
 * Renders the visual schedule grid timetable.
 */
function renderPanelGrid(headers, rows) {
    const tableHeader = document.getElementById("gridTableHeader");
    const tableBody = document.getElementById("gridTableBody");
    
    if (!tableHeader || !tableBody) return;
    
    // Clear
    tableHeader.innerHTML = "";
    tableBody.innerHTML = "";
    
    if (headers.length === 0) {
        tableHeader.innerHTML = "<tr><th>No active panels</th></tr>";
        return;
    }
    
    // Render headers
    const headerRow = document.createElement("tr");
    headers.forEach(h => {
        const th = document.createElement("th");
        th.innerText = h;
        headerRow.appendChild(th);
    });
    tableHeader.appendChild(headerRow);
    
    // Render rows
    rows.forEach(r => {
        const rowTr = document.createElement("tr");
        
        // Time slot cell
        const timeTd = document.createElement("td");
        timeTd.className = "slot-time";
        timeTd.innerText = r[0];
        rowTr.appendChild(timeTd);
        
        // Panel cells
        for (let i = 1; i < r.length; i++) {
            const td = document.createElement("td");
            const val = r[i];
            
            if (val === "####") {
                td.className = "slot-continuation";
                td.innerText = "####";
            } else if (val) {
                td.className = "slot-occupied";
                td.innerHTML = `<strong>${val}</strong>`;
            } else {
                td.className = "slot-free";
                td.innerText = "-";
            }
            rowTr.appendChild(td);
        }
        tableBody.appendChild(rowTr);
    });
}

/**
 * Renders the detailed bookings list.
 */
function renderBookingsTable(bookings) {
    const tbody = document.getElementById("bookingsTableBody");
    if (!tbody) return;
    
    tbody.innerHTML = "";
    
    if (bookings.length === 0) {
        tbody.innerHTML = `<tr><td colspan="8" style="text-align: center; color: var(--text-muted);">No bookings found in database.</td></tr>`;
        return;
    }
    
    // Sort bookings: newest created first
    const sorted = [...bookings].sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
    
    sorted.forEach(b => {
        const tr = document.createElement("tr");
        
        const statusBadge = `<span class="badge badge-${b.status.toLowerCase()}">${b.status}</span>`;
        
        // Disable action buttons based on state
        const isBooked = b.status === "BOOKED";
        
        const completeBtn = isBooked ? 
            `<button class="btn btn-secondary" style="padding: 0.35rem 0.65rem; font-size: 0.8rem;" onclick="triggerComplete('${b.booking_id}')">Complete</button>` : '';
        const noshowBtn = isBooked ? 
            `<button class="btn btn-secondary" style="padding: 0.35rem 0.65rem; font-size: 0.8rem;" onclick="triggerNoShow('${b.booking_id}')">No-Show</button>` : '';
        const rescheduleBtn = (b.status === "BOOKED" || b.status === "WAITLISTED") ? 
            `<button class="btn btn-secondary" style="padding: 0.35rem 0.65rem; font-size: 0.8rem;" onclick="openRescheduleModal('${b.booking_id}', '${b.interview_date}', '${b.start_time}', '${b.end_time}')">Reschedule</button>` : '';
        const cancelBtn = (b.status === "BOOKED" || b.status === "WAITLISTED") ? 
            `<button class="btn btn-danger" style="padding: 0.35rem 0.65rem; font-size: 0.8rem;" onclick="triggerCancel('${b.booking_id}')">Cancel</button>` : '';
            
        tr.innerHTML = `
            <td style="font-family: monospace; font-weight: bold; color: var(--accent-purple);">${b.booking_id}</td>
            <td>${b.interview_date}</td>
            <td><strong>${b.student_name}</strong></td>
            <td>${b.company}</td>
            <td>${b.start_time} - ${b.end_time} (${formatDuration(b.duration)})</td>
            <td>${b.allocated_panel || '<em style="color: var(--text-muted)">None</em>'}</td>
            <td>${statusBadge}</td>
            <td style="font-size: 0.85rem; max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" title="${b.notes || ''}">${b.notes || '-'}</td>
            <td>
                <div style="display: flex; gap: 0.5rem; flex-wrap: wrap;">
                    ${completeBtn}
                    ${noshowBtn}
                    ${rescheduleBtn}
                    ${cancelBtn}
                </div>
            </td>
        `;
        tbody.appendChild(tr);
    });
}

// --- BOOKING ACTION FUNCTIONS ---

async function triggerComplete(id) {
    const reason = prompt("Enter completion notes (optional):");
    if (reason === null) return; // cancelled
    
    try {
        const response = await fetch(`${API_BASE}/bookings/${id}/complete`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ performed_by: "Admin", reason: reason })
        });
        if (!response.ok) {
            const data = await response.json();
            throw new Error(data.detail || "Failed to mark booking completed.");
        }
        showAlert("dashboardAlertContainer", `Booking ${id} marked COMPLETED successfully.`, "success");
        loadDashboardData(currentSelectedDate);
    } catch (err) {
        alert(err.message);
    }
}

async function triggerNoShow(id) {
    if (!confirm(`Are you sure you want to mark booking ${id} as a NO-SHOW? This cannot be undone.`)) return;
    
    try {
        const response = await fetch(`${API_BASE}/bookings/${id}/noshow`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ performed_by: "Admin", reason: "Student did not show up." })
        });
        if (!response.ok) {
            const data = await response.json();
            throw new Error(data.detail || "Failed to mark booking no-show.");
        }
        showAlert("dashboardAlertContainer", `Booking ${id} marked NO-SHOW successfully.`, "success");
        loadDashboardData(currentSelectedDate);
    } catch (err) {
        alert(err.message);
    }
}

async function triggerCancel(id) {
    const reason = prompt("Enter reason for cancellation:");
    if (reason === null) return; // cancelled prompt
    
    try {
        const response = await fetch(`${API_BASE}/bookings/${id}?performed_by=Admin&reason=${encodeURIComponent(reason)}`, {
            method: "DELETE"
        });
        if (!response.ok) {
            const data = await response.json();
            throw new Error(data.detail || "Failed to cancel booking.");
        }
        showAlert("dashboardAlertContainer", `Booking ${id} cancelled successfully and panel slots released.`, "success");
        loadDashboardData(currentSelectedDate);
    } catch (err) {
        alert(err.message);
    }
}

function openRescheduleModal(id, date, start, end) {
    activeRescheduleId = id;
    
    document.getElementById("rescheduleTitle").innerText = `Reschedule Booking: ${id}`;
    
    // Autofill fields
    document.getElementById("new_date").value = date;
    document.getElementById("new_date").min = new Date().toISOString().split('T')[0];
    document.getElementById("new_start").value = start;
    document.getElementById("new_end").value = end;
    document.getElementById("reschedule_reason").value = "";
    document.getElementById("reschedule_notes").value = "";
    
    // Open modal overlay
    document.getElementById("rescheduleModal").classList.add("active");
}
