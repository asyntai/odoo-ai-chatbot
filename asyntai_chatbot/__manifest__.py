# -*- coding: utf-8 -*-
# Asyntai - AI Chatbot for Odoo
# Copyright (c) 2025 Asyntai
# License: LGPL-3

{
    'name': 'Asyntai - AI Chatbot',
    'version': '19.0.1.0.0',
    'category': 'Website',
    'summary': 'AI assistant / chatbot – Provides instant answers to your website visitors',
    'description': """
Asyntai - AI Chatbot for Odoo
=============================

Create and launch AI assistant/chatbot for your Odoo website in minutes.
It talks to your visitors, helps, explains, never misses a chat and can
increase conversion rates! All while knowing your website, customized
just for you. Your Odoo website can now talk.

Features:
---------
* Instant, human-like replies keep visitors engaged
* AI replies day and night, even when your team is offline
* Customized just for you; it follows your instructions
* Automatically detects and answers in the visitor's language
* Fast responses within seconds

Configuration:
--------------
Click on Asyntai AI Chatbot in the app switcher to connect your account.
    """,
    'author': 'Asyntai',
    'website': 'https://asyntai.com',
    'license': 'LGPL-3',
    'depends': ['base', 'website'],
    'data': [
        'security/ir.model.access.csv',
        'views/menu_views.xml',
        'views/res_config_settings_views.xml',
        'views/website_templates.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'asyntai_chatbot/static/src/css/admin.css',
            'asyntai_chatbot/static/src/js/admin.js',
        ],
    },
    'images': [
        'static/description/ai-chatbot-for-websites-1.png',
        'static/description/ai-chatbot-for-websites-2.png',
        'static/description/ai-chatbot-for-websites-3.png',
        'static/description/ai-chatbot-for-websites-4.png',
        'static/description/ai-chatbot-for-websites-5.png',
    ],
    'installable': True,
    'auto_install': False,
    'application': True,
}
