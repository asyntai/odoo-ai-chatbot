# -*- coding: utf-8 -*-
# Asyntai - AI Chatbot for Odoo
# Copyright (c) 2025 Asyntai
# License: LGPL-3
"""What the module remembers for content sharing, and how it talks to Asyntai.

The connection itself (site id, script address, account email) stays in
ir.config_parameter, where version 1.0 put it, so a site connected under 1.0
stays connected after the update and its widget keeps loading.

The feed token is kept in a small table of this module's own instead. It is a
secret, and ir.config_parameter is listed for every administrator under
Technical > System Parameters, where a secret has no place.
"""
import hashlib
import hmac
import json
import logging
import time

import requests

from odoo import api, fields, models
from odoo.tools import sql as sql_tools

_logger = logging.getLogger(__name__)

DEFAULT_ORIGIN = 'https://asyntai.com'
DEFAULT_SCRIPT_URL = 'https://asyntai.com/static/js/chat-widget.js'


def get_param(env, key, default=''):
    """A system parameter as a string, on every Odoo version.

    Odoo 20 replaced get_param with typed getters (get_str and friends).
    """
    params = env['ir.config_parameter'].sudo()
    if hasattr(params, 'get_str'):
        value = params.get_str(key, default)
    else:
        value = params.get_param(key, default)
    return value if isinstance(value, str) else default


def set_param(env, key, value):
    """Store a system parameter as a string, on every Odoo version."""
    params = env['ir.config_parameter'].sudo()
    if hasattr(params, 'set_str'):
        params.set_str(key, value)
    else:
        params.set_param(key, value)


def current_website(env):
    """The website a request is for, on every Odoo version.

    Odoo 20 removed website.get_current_website(); the website is now
    env.website, which is empty outside a website request (the settings
    screen, a cron). Then the first website is used, as older Odoo did.
    """
    Website = env['website']
    if hasattr(Website, 'get_current_website'):
        return Website.get_current_website()
    website = getattr(env, 'website', None) or Website.browse()
    if not website and env.context.get('host_id'):
        website = Website.browse(env.context['host_id'])
    if not website:
        website = Website.sudo().search([], limit=1)
    return website


class AsyntaiChatbotState(models.Model):
    """One row per key. Read and written only through AsyntaiChatbot below."""
    _name = 'asyntai.chatbot.state'
    _description = 'Asyntai AI Chatbot state'
    _log_access = False
    _rec_name = 'key'

    key = fields.Char(required=True, index=True)
    value = fields.Text()

    def init(self):
        # One row per key, enforced by the database. Made here rather than
        # with _sql_constraints, which Odoo 19 no longer reads, or with
        # models.Constraint, which Odoo 16 to 18 do not have. Odoo 19 also
        # folded create_unique_index into create_index(unique=True).
        name = 'asyntai_chatbot_state_key_unique'
        try:
            sql_tools.create_index(self.env.cr, name, self._table, ['key'], unique=True)
        except TypeError:
            sql_tools.create_unique_index(self.env.cr, name, self._table, ['key'])


class AsyntaiChatbot(models.AbstractModel):
    _name = 'asyntai.chatbot'
    _description = 'Asyntai AI Chatbot'

    # -----------------------------------------------------------------
    # Where Asyntai is
    # -----------------------------------------------------------------

    @api.model
    def origin(self):
        """Where this server's Python talks to Asyntai.

        Overridable through a system parameter so a staging copy can point at
        a test server. There is deliberately no field for it on the screen.
        """
        value = self._param('asyntai_chatbot.origin', '')
        return value.rstrip('/') if value else DEFAULT_ORIGIN

    # -----------------------------------------------------------------
    # Storage
    # -----------------------------------------------------------------

    @api.model
    def _param(self, key, default=''):
        return get_param(self.env, key, default)

    @api.model
    def widget_config(self):
        """What the website template needs to load the chat widget."""
        return {
            'site_id': self._param('asyntai_chatbot.site_id', '').strip(),
            'script_url': self._param('asyntai_chatbot.script_url', '') or DEFAULT_SCRIPT_URL,
        }

    @api.model
    def get(self, key, default=''):
        row = self.env['asyntai.chatbot.state'].sudo().search([('key', '=', key)], limit=1)
        if not row or row.value is None or row.value is False:
            return default
        return row.value

    @api.model
    def set(self, key, value):
        rows = self.env['asyntai.chatbot.state'].sudo()
        row = rows.search([('key', '=', key)], limit=1)
        if row:
            row.write({'value': str(value)})
        else:
            rows.create({'key': key, 'value': str(value)})

    @api.model
    def forget(self, key):
        self.env['asyntai.chatbot.state'].sudo().search([('key', '=', key)]).unlink()

    # -----------------------------------------------------------------
    # The connection
    # -----------------------------------------------------------------

    @api.model
    def site_id(self):
        return self._param('asyntai_chatbot.site_id', '').strip()

    @api.model
    def feed_token(self):
        return self.get('feed_token', '').strip()

    @api.model
    def sharing(self):
        """Whether Asyntai may read the pages and products. On unless the
        owner switched it off."""
        return self.get('share', '1') != '0'

    @api.model
    def site_url(self):
        """The public address of this site.

        The website's own domain when the owner set one, otherwise the address
        Odoo last saw itself at. Both are what a visitor would type.
        """
        website = current_website(self.env)
        domain = (website.domain or '').strip().rstrip('/')
        if domain and not domain.startswith('http'):
            domain = 'https://' + domain
        if not domain:
            domain = self._param('web.base.url', '').rstrip('/')
        return domain

    @api.model
    def installed(self, module_name):
        module = self.env['ir.module.module'].sudo().search(
            [('name', '=', module_name), ('state', '=', 'installed')], limit=1)
        return bool(module)

    @api.model
    def shop_installed(self):
        return self.installed('website_sale')

    @api.model
    def blog_installed(self):
        return self.installed('website_blog')

    # -----------------------------------------------------------------
    # Asking Asyntai to read again
    # -----------------------------------------------------------------

    @api.model
    def request_sync(self):
        """Ask Asyntai to read the pages and products again now.

        Signed with the feed token, so only this site can ask. Returns
        (ok, message). Never raises.
        """
        site_id = self.site_id()
        token = self.feed_token()
        if not site_id or not token:
            return False, 'Connect your site first.'

        ts = str(int(time.time()))
        sig = hmac.new(token.encode('utf-8'),
                       ('changed:%s:%s' % (site_id, ts)).encode('utf-8'),
                       hashlib.sha256).hexdigest()
        try:
            response = requests.post(
                self.origin() + '/api/v1/store-feed/changed/',
                json={'site_id': site_id, 'ts': ts, 'sig': sig}, timeout=10,
                headers={'Accept': 'application/json',
                         'User-Agent': 'Asyntai-Odoo-Chatbot/1.1'},
            )
        except requests.RequestException as e:
            _logger.info('Asyntai AI Chatbot: sync request failed: %s', e)
            return False, ('Could not reach Asyntai. Check that this server can '
                           'make outgoing HTTPS requests.')

        if response.status_code in (200, 202):
            return True, 'Asyntai is reading your site again. This takes a few minutes.'
        if response.status_code == 403:
            return False, ('Asyntai did not accept the request. Press Connect again '
                           'to share your pages and products.')
        return False, 'Asyntai answered %s. Please try again later.' % response.status_code

    @api.model
    def status(self):
        """What Asyntai last read, or None when it cannot say."""
        site_id = self.site_id()
        if not site_id:
            return None
        body = self.http_get(self.origin() + '/api/v1/search-widget/status/',
                             {'widget_id': site_id})
        if body is None:
            return None
        try:
            decoded = json.loads(body)
        except ValueError:
            return None
        return decoded if isinstance(decoded, dict) else None

    # -----------------------------------------------------------------
    # HTTP
    # -----------------------------------------------------------------

    @api.model
    def http_get(self, url, params=None, timeout=10):
        """Body of a GET, or None on any failure."""
        try:
            response = requests.get(
                url, params=params or {}, timeout=timeout,
                headers={'Accept': 'application/json',
                         'User-Agent': 'Asyntai-Odoo-Chatbot/1.1'},
            )
        except requests.RequestException as e:
            _logger.info('Asyntai AI Chatbot: GET %s failed: %s', url, e)
            return None
        if response.status_code < 200 or response.status_code > 299:
            return None
        return response.text

    @api.model
    def http_post_json(self, url, payload, timeout=15):
        """Body of a JSON POST, or None on any failure."""
        try:
            response = requests.post(
                url, json=payload, timeout=timeout,
                headers={'Accept': 'application/json',
                         'User-Agent': 'Asyntai-Odoo-Chatbot/1.1'},
            )
        except requests.RequestException as e:
            _logger.info('Asyntai AI Chatbot: POST %s failed: %s', url, e)
            return None
        if response.status_code < 200 or response.status_code > 299:
            return None
        return response.text
