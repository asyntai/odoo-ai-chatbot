# -*- coding: utf-8 -*-
# Asyntai - AI Chatbot for Odoo
# Copyright (c) 2025 Asyntai
# License: MIT License

import json
import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class AsyntaiController(http.Controller):

    @http.route('/asyntai/api/save', type='jsonrpc', auth='user', methods=['POST'], csrf=False)
    def save_settings(self, **kwargs):
        """Save Asyntai connection settings."""
        try:
            # Get data from JSON-RPC request
            data = request.jsonrequest if hasattr(request, 'jsonrequest') else kwargs

            site_id = data.get('site_id', '').strip()
            script_url = data.get('script_url', '').strip()
            account_email = data.get('account_email', '').strip()

            if not site_id:
                return {'success': False, 'error': 'missing site_id'}

            # Check if user has admin rights
            if not request.env.user.has_group('base.group_system'):
                return {'success': False, 'error': 'Access denied'}

            ICP = request.env['ir.config_parameter'].sudo()
            ICP.set_param('asyntai_chatbot.site_id', site_id)
            ICP.set_param('asyntai_chatbot.script_url', script_url or 'https://asyntai.com/static/js/chat-widget.js')
            ICP.set_param('asyntai_chatbot.account_email', account_email)

            return {
                'success': True,
                'saved': {
                    'site_id': site_id,
                    'script_url': script_url or 'https://asyntai.com/static/js/chat-widget.js',
                    'account_email': account_email,
                }
            }
        except Exception as e:
            _logger.exception('Asyntai save error')
            return {'success': False, 'error': str(e)}

    @http.route('/asyntai/api/reset', type='jsonrpc', auth='user', methods=['POST'], csrf=False)
    def reset_settings(self, **kwargs):
        """Reset Asyntai connection settings."""
        try:
            # Check if user has admin rights
            if not request.env.user.has_group('base.group_system'):
                return {'success': False, 'error': 'Access denied'}

            ICP = request.env['ir.config_parameter'].sudo()
            ICP.set_param('asyntai_chatbot.site_id', '')
            ICP.set_param('asyntai_chatbot.script_url', 'https://asyntai.com/static/js/chat-widget.js')
            ICP.set_param('asyntai_chatbot.account_email', '')

            return {'success': True}
        except Exception as e:
            _logger.exception('Asyntai reset error')
            return {'success': False, 'error': str(e)}

    @http.route('/asyntai/api/status', type='jsonrpc', auth='user', methods=['POST'], csrf=False)
    def get_status(self, **kwargs):
        """Get current Asyntai connection status."""
        try:
            ICP = request.env['ir.config_parameter'].sudo()
            site_id = ICP.get_param('asyntai_chatbot.site_id', default='')
            script_url = ICP.get_param('asyntai_chatbot.script_url', default='https://asyntai.com/static/js/chat-widget.js')
            account_email = ICP.get_param('asyntai_chatbot.account_email', default='')

            return {
                'success': True,
                'data': {
                    'site_id': site_id,
                    'script_url': script_url,
                    'account_email': account_email,
                    'connected': bool(site_id),
                }
            }
        except Exception as e:
            _logger.exception('Asyntai status error')
            return {'success': False, 'error': str(e)}
