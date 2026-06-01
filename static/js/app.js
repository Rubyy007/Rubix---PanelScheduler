/* ==========================================
   GLOBAL APP UTILITIES & INTERFACES
   ========================================== */

const API_BASE = "/api";

/**
 * Display a premium banner alert inside a designated container.
 */
function showAlert(containerId, message, type = "success") {
    const container = document.getElementById(containerId);
    if (!container) return;
    
    const cssClass = type === "success" ? "alert-success" : "alert-error";
    const icon = type === "success" ? "✓" : "⚠";
    
    container.innerHTML = `
        <div class="alert ${cssClass}">
            <span style="font-weight: bold; font-size: 1.1rem; margin-right: 0.25rem;">${icon}</span>
            <span>${message}</span>
        </div>
    `;
    
    // Auto-scroll to alert
    container.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

/**
 * Reset and clear any banner alerts.
 */
function clearAlert(containerId) {
    const container = document.getElementById(containerId);
    if (container) {
        container.innerHTML = "";
    }
}

/**
 * Format datetime ISO strings to localized dates (YYYY-MM-DD HH:MM).
 */
function formatDateTime(isoString) {
    if (!isoString) return "";
    try {
        const dt = new Date(isoString);
        if (isNaN(dt.getTime())) return isoString;
        const pad = (num) => String(num).padStart(2, '0');
        return `${dt.getFullYear()}-${pad(dt.getMonth() + 1)}-${pad(dt.getDate())} ${pad(dt.getHours())}:${pad(dt.getMinutes())}`;
    } catch {
        return isoString;
    }
}

/**
 * Formats a duration in minutes to a readable string (e.g. 1h 30m).
 */
function formatDuration(minutes) {
    if (minutes < 60) return `${minutes} min`;
    const hrs = Math.floor(minutes / 60);
    const mins = minutes % 60;
    return mins > 0 ? `${hrs}h ${mins}m` : `${hrs}h`;
}
