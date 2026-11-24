/** @odoo-module **/
/**
 * Asyntai Chatbot Admin JavaScript
 *
 * Every call goes to this Odoo server. The server talks to Asyntai, so no
 * script from another server is loaded into the Odoo backend.
 *
 * @category  Asyntai
 * @package   asyntai_chatbot
 * @author    Asyntai <hello@asyntai.com>
 * @copyright Copyright (c) 2025 Asyntai
 * @license   MIT License
 */

const POLL_EVERY_MS = 1500;
const POLL_FOR_MS = 15 * 60 * 1000;
const POPUP_FEATURES = 'toolbar=no,location=no,status=no,menubar=no,scrollbars=yes,resizable=yes';

function rpc(route, params) {
    return fetch(route, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            jsonrpc: '2.0',
            method: 'call',
            params: params || {},
            id: Math.floor(Math.random() * 1000000000),
        }),
    })
        .then((r) => r.json())
        .then((response) => {
            if (response.error) {
                const data = response.error.data;
                throw new Error((data && data.message) || response.error.message || 'Unknown error');
            }
            return response.result;
        });
}

function byId(id) {
    return document.getElementById(id);
}

function show(id, visible) {
    const el = byId(id);
    if (el) {
        el.style.display = visible ? 'block' : 'none';
    }
}

const AsyntaiAdmin = {
    isInitialized: false,
    lastSettingsWrap: null,
    pollTimer: null,
    connecting: false,

    showAlert(msg, ok) {
        const el = byId('asyntai-alert');
        if (!el) return;
        el.style.display = 'block';
        el.className = 'alert mb-3 ' + (ok ? 'alert-success' : 'alert-danger');
        el.textContent = msg;
    },

    hideAlert() {
        show('asyntai-alert', false);
    },

    updateStatusDisplay(siteId, accountEmail) {
        const statusText = byId('asyntai-status-text');
        const statusContainer = byId('asyntai-status');

        if (statusText) {
            statusText.textContent = '';
            const label = document.createElement('span');
            label.style.fontWeight = '600';
            if (siteId) {
                label.style.color = '#28a745';
                label.textContent = 'Connected';
                statusText.appendChild(label);
                if (accountEmail) {
                    statusText.appendChild(document.createTextNode(' as ' + accountEmail));
                }
                if (statusContainer && !byId('asyntai-reset')) {
                    const resetBtn = document.createElement('button');
                    resetBtn.type = 'button';
                    resetBtn.id = 'asyntai-reset';
                    resetBtn.className = 'btn btn-secondary btn-sm ms-2';
                    resetBtn.textContent = 'Reset';
                    resetBtn.style.marginLeft = '12px';
                    statusContainer.appendChild(resetBtn);
                }
            } else {
                label.style.color = '#dc3545';
                label.textContent = 'Not connected';
                statusText.appendChild(label);
            }
        }

        show('asyntai-connected-box', !!siteId);
        show('asyntai-popup-wrap', !siteId);

        if (siteId) {
            this.loadSharing();
        }
    },

    getInitialStatus() {
        rpc('/asyntai/api/status')
            .then((result) => {
                if (result && result.success && result.data) {
                    this.updateStatusDisplay(result.data.site_id, result.data.account_email);
                } else {
                    this.updateStatusDisplay('', '');
                }
            })
            .catch(() => this.updateStatusDisplay('', ''));
    },

    // ---------------------------------------------------------------
    // Connecting
    // ---------------------------------------------------------------

    /**
     * The window is opened FIRST, while the click still counts as a user
     * action. Opened after the server call it would be blocked as a pop-up.
     */
    connect(asTab) {
        if (this.connecting) return;
        this.connecting = true;
        this.hideAlert();

        let win = null;
        try {
            if (asTab) {
                win = window.open('about:blank', '_blank');
            } else {
                const w = 800, h = 720;
                const y = window.top.outerHeight / 2 + window.top.screenY - (h / 2);
                const x = window.top.outerWidth / 2 + window.top.screenX - (w / 2);
                win = window.open('about:blank', 'asyntai_connect',
                    POPUP_FEATURES + ',width=' + w + ',height=' + h + ',top=' + y + ',left=' + x);
            }
        } catch (e) {
            win = null;
        }

        rpc('/asyntai/api/prepare')
            .then((result) => {
                if (!result || !result.ok) {
                    throw new Error((result && result.error) || 'Could not start the connection.');
                }
                const link = byId('asyntai-fallback-link');
                if (link) link.href = result.url;

                if (win && !win.closed) {
                    win.location.href = result.url;
                } else {
                    this.showAlert('Your browser blocked the sign-in window. Use the link "open the connect window" below.', false);
                    if (link) link.setAttribute('data-ready', '1');
                }
                this.poll(result.state);
            })
            .catch((err) => {
                this.connecting = false;
                if (win && !win.closed) win.close();
                this.showAlert(err && err.message ? err.message : String(err), false);
            });
    },

    poll(state) {
        const started = Date.now();
        clearTimeout(this.pollTimer);

        const check = () => {
            if (Date.now() - started > POLL_FOR_MS) {
                this.connecting = false;
                this.showAlert('The connection attempt has expired. Please press Get started again.', false);
                return;
            }
            rpc('/asyntai/api/poll', { state })
                .then((result) => {
                    if (result && result.ok === false) {
                        this.connecting = false;
                        this.showAlert(result.error || 'The connection failed.', false);
                        return;
                    }
                    if (result && result.ready) {
                        this.saveConnection(result);
                        return;
                    }
                    this.pollTimer = setTimeout(check, POLL_EVERY_MS);
                })
                .catch(() => {
                    this.pollTimer = setTimeout(check, POLL_EVERY_MS * 2);
                });
        };
        this.pollTimer = setTimeout(check, POLL_EVERY_MS);
    },

    saveConnection(data) {
        this.showAlert('Asyntai connected. Saving...', true);
        const payload = {
            site_id: data.site_id || '',
            script_url: data.script_url || '',
            account_email: data.account_email || '',
        };
        rpc('/asyntai/api/save', payload)
            .then((result) => {
                this.connecting = false;
                if (!result || !result.success) {
                    throw new Error((result && result.error) || 'Save failed');
                }
                this.showAlert('Asyntai connected. Chatbot enabled on all pages.', true);
                this.updateStatusDisplay(payload.site_id, payload.account_email);
            })
            .catch((err) => {
                this.connecting = false;
                this.showAlert('Could not save settings: ' + (err && err.message || err), false);
            });
    },

    resetConnection() {
        if (!confirm('Are you sure you want to reset the Asyntai connection?')) {
            return;
        }
        rpc('/asyntai/api/reset', { action: 'reset' })
            .then((result) => {
                if (result && result.success) {
                    window.location.reload();
                } else {
                    throw new Error('Reset failed');
                }
            })
            .catch((err) => {
                this.showAlert('Reset failed: ' + (err && err.message || err), false);
            });
    },

    // ---------------------------------------------------------------
    // Pages and products
    // ---------------------------------------------------------------

    loadSharing() {
        rpc('/asyntai/api/sharing')
            .then((result) => {
                if (!result || !result.ok || !result.connected) {
                    show('asyntai-share-box', false);
                    return;
                }
                show('asyntai-share-box', true);
                show('asyntai-share-on', !!result.available);
                show('asyntai-share-upgrade', !result.available);

                const box = byId('asyntai-share');
                if (box) box.checked = !!result.enabled;
                show('asyntai-sync-now', !!result.enabled);

                const text = byId('asyntai-sync-text');
                if (text) text.textContent = this.syncText(result);
            })
            .catch(() => show('asyntai-share-box', false));
    },

    syncText(result) {
        if (!result.enabled) {
            return 'Sharing is off. The AI learns your site from its public pages only.';
        }
        const sync = result.sync;
        if (!sync) {
            return 'Asyntai reads your site a few minutes after you connect, then once a day.';
        }
        if (sync.status === 'syncing') {
            return 'Asyntai is reading your site now.';
        }
        if (sync.status === 'failed') {
            return 'The last read failed: ' + (sync.error || 'unknown error') + '.';
        }
        if (result.shop) {
            return 'Asyntai has read your site. Products indexed: ' + (result.products || 0) + '.';
        }
        return 'Asyntai has read your pages and blog posts.';
    },

    setSharing(enabled) {
        rpc('/asyntai/api/share', { enabled })
            .then((result) => {
                this.showAlert(result && result.message ? result.message : 'Saved.', !!(result && result.synced));
                this.loadSharing();
            })
            .catch((err) => this.showAlert(err && err.message ? err.message : String(err), false));
    },

    syncNow() {
        rpc('/asyntai/api/sync')
            .then((result) => {
                this.showAlert(result && result.message ? result.message : 'Done.', !!(result && result.ok));
                setTimeout(() => this.loadSharing(), 3000);
            })
            .catch((err) => this.showAlert(err && err.message ? err.message : String(err), false));
    },

    // ---------------------------------------------------------------
    // Wiring
    // ---------------------------------------------------------------

    init() {
        const settingsWrap = byId('asyntai-settings-wrap');
        if (!settingsWrap) return;
        if (this.lastSettingsWrap === settingsWrap && this.isInitialized) {
            return;
        }
        this.lastSettingsWrap = settingsWrap;
        this.isInitialized = true;
        this.getInitialStatus();
    },

    setupEventListeners() {
        if (this.eventListenersSetup) return;
        this.eventListenersSetup = true;

        document.addEventListener('click', (ev) => {
            const t = ev.target;
            if (!t || !t.closest) return;

            if (t.closest('#asyntai-connect-btn') || t.closest('#asyntai-reconnect')) {
                ev.preventDefault();
                ev.stopPropagation();
                this.connect(false);
                return;
            }
            const link = t.closest('#asyntai-fallback-link');
            if (link) {
                // Once a sign-in address is in place, the link simply opens
                // it and the poll that is already running finishes the job.
                if (link.getAttribute('data-ready') === '1') {
                    return;
                }
                ev.preventDefault();
                ev.stopPropagation();
                this.connecting = false;
                this.connect(true);
                return;
            }
            if (t.closest('#asyntai-reset')) {
                ev.preventDefault();
                ev.stopPropagation();
                this.resetConnection();
                return;
            }
            if (t.closest('#asyntai-share-label')) {
                const box = byId('asyntai-share');
                if (box) {
                    box.checked = !box.checked;
                    this.setSharing(box.checked);
                }
                return;
            }
            if (t.closest('#asyntai-sync-now')) {
                ev.preventDefault();
                ev.stopPropagation();
                this.syncNow();
            }
        }, true);

        document.addEventListener('change', (ev) => {
            const t = ev.target;
            if (t && t.id === 'asyntai-share') {
                this.setSharing(!!t.checked);
            }
        }, true);
    },
};

// Initialize after DOM mutations (for Odoo's dynamic loading)
function tryInit() {
    if (byId('asyntai-settings-wrap')) {
        AsyntaiAdmin.setupEventListeners();
        AsyntaiAdmin.init();
    }
}

// A new settings wrap appears on every tab switch.
function checkForNewWrap() {
    const settingsWrap = byId('asyntai-settings-wrap');
    if (settingsWrap && settingsWrap !== AsyntaiAdmin.lastSettingsWrap) {
        AsyntaiAdmin.isInitialized = false;
        tryInit();
    }
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', tryInit);
} else {
    tryInit();
}

setTimeout(tryInit, 500);
setTimeout(tryInit, 1000);
setTimeout(tryInit, 2000);
setTimeout(tryInit, 3000);

const observer = new MutationObserver(checkForNewWrap);

if (document.body) {
    observer.observe(document.body, { childList: true, subtree: true });
} else {
    document.addEventListener('DOMContentLoaded', function () {
        observer.observe(document.body, { childList: true, subtree: true });
    });
}

export default AsyntaiAdmin;
