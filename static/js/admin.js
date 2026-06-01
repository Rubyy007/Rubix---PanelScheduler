/* ==========================================
   ADMIN PORTAL PAGE CONTROLLER
   ========================================== */

document.addEventListener("DOMContentLoaded", () => {
    // 1. Setup Admin Tabs
    const tabs = document.querySelectorAll(".tab");
    tabs.forEach(tab => {
        tab.addEventListener("click", () => {
            tabs.forEach(t => t.classList.remove("active"));
            tab.classList.add("active");
            
            // Hide all tab panes
            const panes = document.querySelectorAll(".tab-pane");
            panes.forEach(p => p.style.display = "none");
            
            // Show selected pane
            const activePaneId = tab.dataset.pane;
            const activePane = document.getElementById(activePaneId);
            if (activePane) {
                activePane.style.display = "block";
            }
            
            // Perform pane-specific loads
            if (activePaneId === "auditPane") {
                loadAuditLogs();
            } else if (activePaneId === "panelPane") {
                loadPanelsConfig();
            } else if (activePaneId === "overridePane") {
                loadOverrideDropdowns();
            } else if (activePaneId === "configPane") {
                loadSystemConfig();
            }
        });
    });

    // 2. Initial load: System config tab is active
    loadSystemConfig();

    // 3. Manual override panel move form submission
    const moveForm = document.getElementById("movePanelForm");
    if (moveForm) {
        moveForm.addEventListener("submit", async (e) => {
            e.preventDefault();
            clearAlert("adminAlertContainer");
            
            const bookingId = document.getElementById("override_booking").value;
            const targetPanel = document.getElementById("override_target_panel").value;
            const reason = document.getElementById("override_reason").value.trim();
            
            if (!bookingId || !targetPanel || !reason) {
                showAlert("adminAlertContainer", "All override fields are required.", "error");
                return;
            }
            
            try {
                const response = await fetch(`${API_BASE}/admin/move-panel/${bookingId}`, {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json"
                    },
                    body: JSON.stringify({
                        performed_by: "Admin",
                        target_panel: targetPanel,
                        reason: reason
                    })
                });
                
                const data = await response.json();
                if (!response.ok) {
                    throw new Error(data.detail || "Failed to manually override booking panel.");
                }
                
                showAlert("adminAlertContainer", `Success! Booking ${bookingId} has been moved to ${targetPanel}.`, "success");
                moveForm.reset();
                loadOverrideDropdowns(); // Refresh lists
                
            } catch (err) {
                showAlert("adminAlertContainer", err.message, "error");
            }
        });
    }
});

/**
 * Fetch and load system configurations in read-only mode to demonstrate CONFIG sheet syncing.
 */
async function loadSystemConfig() {
    try {
        const response = await fetch(`${API_BASE}/admin/dashboard`);
        if (!response.ok) throw new Error("Could not fetch configurations.");
        const data = await response.json();
        
        document.getElementById("cfg_hours").value = `${data.config.working_hours_start} - ${data.config.working_hours_end}`;
        document.getElementById("cfg_slot").value = `${data.config.slot_duration} minutes`;
        document.getElementById("cfg_range").value = `${data.config.min_duration} to ${data.config.max_duration} minutes`;
        document.getElementById("cfg_promote").value = data.config.auto_promote_waitlist ? "Enabled (Automatic)" : "Disabled (Manual)";
        
        // Render panels quick check
        const pList = document.getElementById("cfg_panels_list");
        if (pList) {
            pList.innerHTML = "";
            for (const [panel, enabled] of Object.entries(data.config.panel_enabled_flags)) {
                const badge = enabled ? 
                    `<span class="badge badge-completed">Enabled</span>` : 
                    `<span class="badge badge-cancelled">Disabled</span>`;
                pList.innerHTML += `<div style="display:flex; justify-content:space-between; margin-bottom:0.5rem; padding:0.5rem; background:rgba(255,255,255,0.02); border-radius:4px;">
                    <strong>${panel}</strong>
                    ${badge}
                </div>`;
            }
        }
    } catch (err) {
        console.error(err);
    }
}

/**
 * Fetch panel statuses and render enable/disable toggles.
 */
async function loadPanelsConfig() {
    const listContainer = document.getElementById("panelsConfigList");
    if (!listContainer) return;
    
    try {
        const response = await fetch(`${API_BASE}/admin/panels`);
        if (!response.ok) throw new Error("Could not fetch panel details.");
        const panels = await response.json();
        
        listContainer.innerHTML = "";
        
        panels.forEach(p => {
            const card = document.createElement("div");
            card.className = "glass-card";
            card.style.padding = "1.5rem";
            card.style.display = "flex";
            card.style.justifyContent = "space-between";
            card.style.alignItems = "center";
            card.style.marginBottom = "1rem";
            
            const badgeClass = p.enabled ? "badge-completed" : "badge-cancelled";
            const stateText = p.enabled ? "ACTIVE" : "DISABLED";
            const btnText = p.enabled ? "Disable Panel" : "Enable Panel";
            const btnClass = p.enabled ? "btn-danger" : "btn-primary";
            
            card.innerHTML = `
                <div>
                    <h3 style="font-family: 'Space Grotesk', sans-serif; font-size: 1.25rem;">${p.panel_name}</h3>
                    <div style="margin-top: 0.25rem; display: flex; gap: 1rem; font-size: 0.85rem; color: var(--text-secondary);">
                        <span>Status: <span class="badge ${badgeClass}">${stateText}</span></span>
                        <span>Active Allocations: <strong>${p.allocation_count}</strong></span>
                    </div>
                </div>
                <button class="btn ${btnClass}" style="padding: 0.5rem 1rem; font-size: 0.85rem;" onclick="togglePanelState('${p.panel_name}', ${p.enabled})">
                    ${btnText}
                </button>
            `;
            listContainer.appendChild(card);
        });
    } catch (err) {
        showAlert("adminAlertContainer", err.message, "error");
    }
}

/**
 * Action to toggle a panel's enabled state.
 */
async function togglePanelState(panelName, currentEnabledState) {
    const actionWord = currentEnabledState ? "disable" : "enable";
    const reason = prompt(`Enter reason to ${actionWord} ${panelName}:`);
    if (reason === null) return; // Cancelled
    
    if (reason.trim().length < 3) {
        alert("A valid reason (minimum 3 characters) is required to toggle panel states.");
        return;
    }
    
    try {
        const response = await fetch(`${API_BASE}/admin/disable-panel`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({
                performed_by: "Admin",
                panel_name: panelName,
                disabled: currentEnabledState, // If currently enabled, we set disabled=true
                reason: reason
            })
        });
        
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || "Failed to toggle panel.");
        
        showAlert("adminAlertContainer", data.message || `Successfully toggled state for ${panelName}.`, "success");
        loadPanelsConfig();
    } catch (err) {
        alert(err.message);
    }
}

/**
 * Fetch and load active bookings and target panels into dropdowns for the manual override form.
 */
async function loadOverrideDropdowns() {
    const bookingSelect = document.getElementById("override_booking");
    const panelSelect = document.getElementById("override_target_panel");
    
    if (!bookingSelect || !panelSelect) return;
    
    // Clear dropdowns
    bookingSelect.innerHTML = '<option value="">-- Select Booking --</option>';
    panelSelect.innerHTML = '<option value="">-- Select Target Panel --</option>';
    
    try {
        // Fetch dashboard data
        const response = await fetch(`${API_BASE}/admin/dashboard`);
        if (!response.ok) throw new Error("Could not fetch override data options.");
        const data = await response.json();
        
        // 1. Populate Bookings dropdown (only BOOKED active bookings)
        const activeBookings = data.bookings.filter(b => b.status === "BOOKED");
        activeBookings.forEach(b => {
            const opt = document.createElement("option");
            opt.value = b.booking_id;
            opt.innerText = `${b.booking_id} | ${b.student_name} (${b.interview_date} ${b.start_time} [${b.allocated_panel}])`;
            bookingSelect.appendChild(opt);
        });
        
        // 2. Populate Panels dropdown (only active panels)
        const activePanels = Object.entries(data.config.panel_enabled_flags)
            .filter(([_, enabled]) => enabled)
            .map(([name, _]) => name);
            
        activePanels.forEach(p => {
            const opt = document.createElement("option");
            opt.value = p;
            opt.innerText = p;
            panelSelect.appendChild(opt);
        });
        
    } catch (err) {
        console.error(err);
    }
}

/**
 * Fetch and load audit logs.
 */
async function loadAuditLogs() {
    const container = document.getElementById("auditLogsList");
    if (!container) return;
    
    container.innerHTML = "<p style='text-align:center; color:var(--text-secondary);'>Loading audit trails from sheets...</p>";
    
    try {
        const response = await fetch(`${API_BASE}/admin/audit`);
        if (!response.ok) throw new Error("Could not fetch audit trail.");
        const logs = await response.json();
        
        container.innerHTML = "";
        
        if (logs.length === 0) {
            container.innerHTML = "<p style='text-align:center; color:var(--text-secondary);'>No audit records exist.</p>";
            return;
        }
        
        logs.forEach(l => {
            const item = document.createElement("div");
            item.className = "audit-item";
            
            // Format action styling
            let actionStyle = "var(--accent-purple)";
            if (l.action.includes("CANCEL")) actionStyle = "var(--danger)";
            if (l.action.includes("CREATE")) actionStyle = "var(--accent-blue)";
            if (l.action.includes("COMPLETE")) actionStyle = "var(--success)";
            
            item.innerHTML = `
                <div class="audit-header">
                    <span class="audit-action" style="color: ${actionStyle}">${l.action}</span>
                    <span class="audit-time">${formatDateTime(l.timestamp)}</span>
                </div>
                <div class="audit-body">
                    Target Booking: <strong style="font-family: monospace; color: var(--text-primary);">${l.booking_id}</strong>
                </div>
                <div class="audit-changes">
                    <div><span style="color: var(--danger)">- Before:</span> ${l.old_value || 'None'}</div>
                    <div><span style="color: var(--success)">+ After:</span> ${l.new_value || 'None'}</div>
                </div>
                <div class="audit-meta">
                    <span>Performed By: <strong>${l.performed_by}</strong></span>
                    <span>Reason: <em>${l.reason || 'None'}</em></span>
                </div>
            `;
            container.appendChild(item);
        });
    } catch (err) {
        container.innerHTML = `<p style='text-align:center; color:var(--danger);'>Error: ${err.message}</p>`;
    }
}
