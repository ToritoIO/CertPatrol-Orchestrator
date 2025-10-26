// Global utility functions for CertPatrol Orchestrator

// Format date consistently
function formatDate(dateString) {
    const date = new Date(dateString);
    return date.toLocaleString();
}

// Show toast notification (if we add a notification system later)
function showNotification(message, type = 'info') {
    console.log(`[${type.toUpperCase()}] ${message}`);
    // Can be extended with a proper toast notification UI
}

// Confirm action
function confirmAction(message) {
    return confirm(message);
}

// Handle API errors consistently
function handleApiError(error, context = '') {
    console.error(`API Error ${context}:`, error);
    alert(`Error: ${error.message || error}`);
}

// Auto-refresh manager
class AutoRefresh {
    constructor(callback, interval = 5000) {
        this.callback = callback;
        this.interval = interval;
        this.timerId = null;
    }
    
    start() {
        if (this.timerId) return;
        this.timerId = setInterval(this.callback, this.interval);
    }
    
    stop() {
        if (this.timerId) {
            clearInterval(this.timerId);
            this.timerId = null;
        }
    }
}

// Export for use in other scripts
window.CertPatrolManager = {
    formatDate,
    showNotification,
    confirmAction,
    handleApiError,
    AutoRefresh
};

