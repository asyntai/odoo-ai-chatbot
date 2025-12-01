# -*- coding: utf-8 -*-
# Asyntai - AI Chatbot for Odoo
# Copyright (c) 2025 Asyntai
# License: MIT License

from odoo import api, fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    asyntai_site_id = fields.Char(
        string='Site ID',
        config_parameter='asyntai_chatbot.site_id',
        help='Your Asyntai Site ID'
    )
    asyntai_script_url = fields.Char(
        string='Script URL',
        config_parameter='asyntai_chatbot.script_url',
        default='https://asyntai.com/static/js/chat-widget.js',
        help='Asyntai widget script URL'
    )
    asyntai_account_email = fields.Char(
        string='Account Email',
        config_parameter='asyntai_chatbot.account_email',
        help='Your Asyntai account email'
    )

    @api.model
    def get_values(self):
        res = super(ResConfigSettings, self).get_values()
        ICP = self.env['ir.config_parameter'].sudo()
        res.update(
            asyntai_site_id=ICP.get_param('asyntai_chatbot.site_id', default=''),
            asyntai_script_url=ICP.get_param('asyntai_chatbot.script_url', default='https://asyntai.com/static/js/chat-widget.js'),
            asyntai_account_email=ICP.get_param('asyntai_chatbot.account_email', default=''),
        )
        return res

    def set_values(self):
        super(ResConfigSettings, self).set_values()
        ICP = self.env['ir.config_parameter'].sudo()
        ICP.set_param('asyntai_chatbot.site_id', self.asyntai_site_id or '')
        ICP.set_param('asyntai_chatbot.script_url', self.asyntai_script_url or 'https://asyntai.com/static/js/chat-widget.js')
        ICP.set_param('asyntai_chatbot.account_email', self.asyntai_account_email or '')
