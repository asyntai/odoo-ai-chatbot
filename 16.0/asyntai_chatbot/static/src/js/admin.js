/** @odoo-module **/
/**
 * Asyntai Chatbot Admin JavaScript
 *
 * @category  Asyntai
 * @package   asyntai_chatbot
 * @author    Asyntai <hello@asyntai.com>
 * @copyright Copyright (c) 2025 Asyntai
 * @license   MIT License
 */

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, onMounted, useState } from "@odoo/owl";

// Asyntai Admin module for settings page
const AsyntaiAdmin = {
    currentState: null,
    isInitialized: false,
    lastSettingsWrap: null,

    showAlert: function(msg, ok) {
        const el = document.getElementById('asyntai-alert');
        if (!el) return;
        el.style.display = 'block';
        el.className = 'alert mb-3 ' + (ok ? 'alert-success' : 'alert-danger');
        el.textContent = msg;
    },

    generateState: function() {
        return 'odoo_' + Math.random().toString(36).substr(2, 9);
    },

    updateFallbackLink: function() {
        const fallbackLink = document.getElementById('asyntai-fallback-link');
        if (fallbackLink && this.currentState) {
            fallbackLink.href = 'https://asyntai.com/wp-auth?platform=odoo&state=' + encodeURIComponent(this.currentState);
        }
    },

    updateStatusDisplay: function(siteId, accountEmail) {
        const statusText = document.getElementById('asyntai-status-text');
        const connectedBox = document.getElementById('asyntai-connected-box');
        const popupWrap = document.getElementById('asyntai-popup-wrap');
        const statusContainer = document.getElementById('asyntai-status');

        if (statusText) {
            if (siteId) {
                statusText.innerHTML = '<span style="color:#28a745;font-weight:600;">Connected</span>';
                if (accountEmail) {
                    statusText.innerHTML += ' as ' + accountEmail;
                }
                if (statusContainer && !document.getElementById('asyntai-reset')) {
                    const resetBtn = document.createElement('button');
                    resetBtn.type = 'button';
                    resetBtn.id = 'asyntai-reset';
                    resetBtn.className = 'btn btn-secondary btn-sm ms-2';
                    resetBtn.textContent = 'Reset';
                    resetBtn.style.marginLeft = '12px';
                    statusContainer.appendChild(resetBtn);
                }
            } else {
                statusText.innerHTML = '<span style="color:#dc3545;font-weight:600;">Not connected</span>';
            }
        }

        if (connectedBox) {
            connectedBox.style.display = siteId ? 'block' : 'none';
        }

        if (popupWrap) {
            popupWrap.style.display = siteId ? 'none' : 'block';
        }
    },

    getInitialStatus: function() {
        const self = this;
        fetch('/asyntai/api/status', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                jsonrpc: '2.0',
                method: 'call',
                params: {},
                id: Math.floor(Math.random() * 1000000000)
            })
        })
        .then(r => r.json())
        .then(response => {
            if (response.result && response.result.success && response.result.data) {
                const data = response.result.data;
                self.updateStatusDisplay(data.site_id, data.account_email);
            } else {
                self.updateStatusDisplay('', '');
            }
        })
        .catch(err => {
            console.error('Failed to get Asyntai status:', err);
            self.updateStatusDisplay('', '');
        });
    },

    openPopup: function() {
        const self = this;
        this.currentState = this.generateState();
        this.updateFallbackLink();
        const base = 'https://asyntai.com/wp-auth?platform=odoo';
        const url = base + '&state=' + encodeURIComponent(this.currentState);
        const w = 800, h = 720;
        const y = window.top.outerHeight / 2 + window.top.screenY - (h / 2);
        const x = window.top.outerWidth / 2 + window.top.screenX - (w / 2);
        const pop = window.open(url, 'asyntai_connect', 'toolbar=no,location=no,status=no,menubar=no,scrollbars=yes,resizable=yes,width=' + w + ',height=' + h + ',top=' + y + ',left=' + x);

        setTimeout(() => {
            if (!pop || pop.closed || typeof pop.closed == 'undefined') {
                self.showAlert('Popup blocked. Please allow popups or use the link below.', false);
                return;
            }
            self.pollForConnection(self.currentState);
        }, 100);
    },

    pollForConnection: function(state) {
        const self = this;
        let attempts = 0;
        function check() {
            if (attempts++ > 60) return;
            const script = document.createElement('script');
            const cb = 'asyntai_cb_' + Date.now();
            script.src = 'https://asyntai.com/connect-status.js?state=' + encodeURIComponent(state) + '&cb=' + cb;
            window[cb] = function(data) {
                try { delete window[cb]; } catch (e) { }
                if (data && data.site_id) {
                    self.saveConnection(data);
                    return;
                }
                setTimeout(check, 500);
            };
            script.onerror = function() {
                setTimeout(check, 1000);
            };
            document.head.appendChild(script);
        }
        setTimeout(check, 800);
    },

    saveConnection: function(data) {
        const self = this;
        this.showAlert('Asyntai connected. Saving...', true);
        const payload = {
            site_id: data.site_id || '',
            script_url: data.script_url || 'https://asyntai.com/static/js/chat-widget.js',
            account_email: data.account_email || ''
        };

        fetch('/asyntai/api/save', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                jsonrpc: '2.0',
                method: 'call',
                params: payload,
                id: Math.floor(Math.random() * 1000000000)
            })
        })
        .then(r => r.json())
        .then(response => {
            if (response.error) {
                throw new Error(response.error.data ? response.error.data.message : response.error.message || 'Unknown error');
            }
            const json = response.result;
            if (!json || !json.success) {
                throw new Error(json && json.error || 'Save failed');
            }
            self.showAlert('Asyntai connected. Chatbot enabled on all pages.', true);
            self.updateStatusDisplay(payload.site_id, payload.account_email);
        })
        .catch(err => {
            self.showAlert('Could not save settings: ' + (err && err.message || err), false);
        });
    },

    resetConnection: function() {
        const self = this;
        if (!confirm('Are you sure you want to reset the Asyntai connection?')) {
            return;
        }

        fetch('/asyntai/api/reset', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                jsonrpc: '2.0',
                method: 'call',
                params: { action: 'reset' },
                id: Math.floor(Math.random() * 1000000000)
            })
        })
        .then(r => r.json())
        .then(response => {
            if (response.error) {
                throw new Error(response.error.data ? response.error.data.message : 'Reset failed');
            }
            if (response.result && response.result.success) {
                window.location.reload();
            } else {
                throw new Error('Reset failed');
            }
        })
        .catch(err => {
            self.showAlert('Reset failed: ' + (err && err.message || err), false);
        });
    },

    init: function() {
        const settingsWrap = document.getElementById('asyntai-settings-wrap');
        if (!settingsWrap) return;

        // Check if this is a new/different settings wrap (tab switch)
        if (this.lastSettingsWrap === settingsWrap && this.isInitialized) {
            return;
        }

        // Reset for new wrap
        this.lastSettingsWrap = settingsWrap;
        this.isInitialized = true;
        const self = this;

        this.currentState = this.generateState();
        this.updateFallbackLink();
        this.getInitialStatus();
    },

    setupEventListeners: function() {
        const self = this;

        // Only setup once
        if (this.eventListenersSetup) return;
        this.eventListenersSetup = true;

        // Event delegation for clicks
        document.addEventListener('click', function(ev) {
            const t = ev.target;
            if (t && (t.id === 'asyntai-connect-btn' || t.closest('#asyntai-connect-btn'))) {
                ev.preventDefault();
                ev.stopPropagation();
                self.openPopup();
            }
            if (t && (t.id === 'asyntai-reset' || t.closest('#asyntai-reset'))) {
                ev.preventDefault();
                ev.stopPropagation();
                self.resetConnection();
            }
            if (t && (t.id === 'asyntai-fallback-link' || t.closest('#asyntai-fallback-link'))) {
                self.currentState = self.generateState();
                self.updateFallbackLink();
                setTimeout(() => { self.pollForConnection(self.currentState); }, 1000);
            }
        }, true);
    }
};

// Initialize after DOM mutations (for Odoo's dynamic loading)
function tryInit() {
    const settingsWrap = document.getElementById('asyntai-settings-wrap');
    if (settingsWrap) {
        AsyntaiAdmin.setupEventListeners();
        AsyntaiAdmin.init();
    }
}

// Reset isInitialized when the settings wrap changes
function checkForNewWrap() {
    const settingsWrap = document.getElementById('asyntai-settings-wrap');
    if (settingsWrap && settingsWrap !== AsyntaiAdmin.lastSettingsWrap) {
        AsyntaiAdmin.isInitialized = false;
        tryInit();
    }
}

// Multiple initialization attempts for Odoo's dynamic content
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', tryInit);
} else {
    tryInit();
}

setTimeout(tryInit, 500);
setTimeout(tryInit, 1000);
setTimeout(tryInit, 2000);
setTimeout(tryInit, 3000);

// MutationObserver for dynamic content - handles tab switches
const observer = new MutationObserver(function(mutations) {
    // Check if asyntai settings wrap exists and needs init
    checkForNewWrap();
});

if (document.body) {
    observer.observe(document.body, { childList: true, subtree: true });
} else {
    document.addEventListener('DOMContentLoaded', function() {
        observer.observe(document.body, { childList: true, subtree: true });
    });
}

// Export for potential use by other modules
export default AsyntaiAdmin;
