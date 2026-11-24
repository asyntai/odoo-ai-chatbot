# -*- coding: utf-8 -*-
# Asyntai - AI Chatbot for Odoo
# Copyright (c) 2025 Asyntai
# License: MIT License
"""The settings screen's calls, the connect handshake, and the two feeds.

The handshake, in order:
  1. "Get started" calls prepare. Python makes a feed token and parks it at
     Asyntai under a one-time state token. No account exists yet, so nothing
     is linked to anybody.
  2. The browser opens the Asyntai sign-in window with that same state token.
  3. The browser polls THIS server, which asks Asyntai for the state token.
     Once the owner has signed in, the answer carries their site id.

Every call from the settings screen lands on this server. Nothing is fetched
from Asyntai as a script, so no code from another server runs in the backend.

The two feeds are what Asyntai reads afterwards: the published products, and
the published pages and blog posts. Both are read-only, both refuse a call
that is not signed with the feed token, and both send only what a visitor of
the website can already see.
"""
import hashlib
import hmac
import html as html_module
import json
import logging
import re
import secrets
import time
from urllib.parse import urlencode

import werkzeug.exceptions

from odoo import fields, http, release
from odoo.http import request

_logger = logging.getLogger(__name__)

# Odoo 19 renamed the JSON-RPC route type and warns about the old name on
# every start. One source serves every version, so the name is picked here.
JSON_ROUTE = 'jsonrpc' if release.version_info[0] >= 19 else 'json'

DEFAULT_SCRIPT_URL = 'https://asyntai.com/static/js/chat-widget.js'

# How long a handshake token stays valid, in seconds.
STATE_TTL = 900

# Records per feed page, and the most a hand-made request may ask for.
PAGE_SIZE = 100
MAX_PAGE_SIZE = 250

# How far a signed feed request's clock may drift, in seconds.
CLOCK_SKEW = 300

# Layers of escaping undone before tags are removed. Real data has one or two.
MAX_DECODE_PASSES = 5

# A tag only when "<" is followed by a letter or "/", so "5 < 10 cm" keeps
# its words once the text has been decoded.
TAG_RE = re.compile(r'</?[a-zA-Z][^<>]*>')
OPEN_TAG_AT_END_RE = re.compile(r'</?[a-zA-Z][^<>]*$')
SCRIPT_RE = re.compile(r'<(script|style)\b[\s\S]*?(?:</\1\s*>|$)', re.I)
COMMENT_RE = re.compile(r'<!--[\s\S]*?(?:-->|$)')
SPACE_RE = re.compile(r'[\s ]+')
SITE_ID_RE = re.compile(r'^[A-Za-z0-9_-]{6,64}$')


def _is_admin():
    return request.env.user.has_group('base.group_system')


def _require_admin():
    """Administrators only. auth='user' lets any employee in; this does not."""
    if not _is_admin():
        raise werkzeug.exceptions.Forbidden('Administrators only.')


def _plain(value):
    """HTML reduced to the words a visitor would read. Nothing is cut.

    Entities are decoded FIRST, until nothing changes, and tags are removed
    after that. In the other order an escaped value ("&lt;b&gt;") comes back
    as live markup once the strip is done.
    """
    text = str(value or '')
    for _ in range(MAX_DECODE_PASSES):
        decoded = html_module.unescape(text)
        if decoded == text:
            break
        text = decoded

    # Until nothing changes: removing one tag can join the pieces around it
    # into another ("<scr<b>ipt>").
    for _ in range(MAX_DECODE_PASSES):
        before = text
        text = SCRIPT_RE.sub(' ', text)
        text = COMMENT_RE.sub(' ', text)
        text = TAG_RE.sub(' ', text)
        text = OPEN_TAG_AT_END_RE.sub(' ', text)
        if text == before:
            break

    return SPACE_RE.sub(' ', text).strip()


class AsyntaiController(http.Controller):

    # -----------------------------------------------------------------
    # Version 1.0 calls, kept so a settings screen still open in a browser
    # tab from before the update keeps working.
    # -----------------------------------------------------------------

    @http.route('/asyntai/api/save', type=JSON_ROUTE, auth='user', methods=['POST'], csrf=False)
    def save_settings(self, site_id='', script_url='', account_email='', **kwargs):
        """Save the connection the sign-in window handed back."""
        try:
            if not _is_admin():
                return {'success': False, 'error': 'Access denied'}

            site_id = (site_id or '').strip()
            if not SITE_ID_RE.match(site_id):
                return {'success': False, 'error': 'missing site_id'}

            script_url = (script_url or '').strip()
            if not script_url.startswith(('https://', 'http://')):
                script_url = DEFAULT_SCRIPT_URL

            ICP = request.env['ir.config_parameter'].sudo()
            ICP.set_param('asyntai_chatbot.site_id', site_id)
            ICP.set_param('asyntai_chatbot.script_url', script_url)
            ICP.set_param('asyntai_chatbot.account_email', (account_email or '').strip()[:255])

            model = request.env['asyntai.chatbot'].sudo()
            model.forget('state')
            model.forget('state_at')

            return {
                'success': True,
                'saved': {
                    'site_id': site_id,
                    'script_url': script_url,
                    'account_email': (account_email or '').strip()[:255],
                },
            }
        except Exception as e:
            _logger.exception('Asyntai save error')
            return {'success': False, 'error': str(e)}

    @http.route('/asyntai/api/reset', type=JSON_ROUTE, auth='user', methods=['POST'], csrf=False)
    def reset_settings(self, **kwargs):
        """Forget the connection. The feed token goes with it: a token kept
        after a disconnect can only ever sign a request nobody should make."""
        try:
            if not _is_admin():
                return {'success': False, 'error': 'Access denied'}

            ICP = request.env['ir.config_parameter'].sudo()
            ICP.set_param('asyntai_chatbot.site_id', '')
            ICP.set_param('asyntai_chatbot.script_url', DEFAULT_SCRIPT_URL)
            ICP.set_param('asyntai_chatbot.account_email', '')

            model = request.env['asyntai.chatbot'].sudo()
            for key in ('feed_token', 'share', 'state', 'state_at'):
                model.forget(key)

            return {'success': True}
        except Exception as e:
            _logger.exception('Asyntai reset error')
            return {'success': False, 'error': str(e)}

    @http.route('/asyntai/api/status', type=JSON_ROUTE, auth='user', methods=['POST'], csrf=False)
    def get_status(self, **kwargs):
        """The connection, as the settings screen shows it."""
        try:
            if not _is_admin():
                return {'success': False, 'error': 'Access denied'}

            ICP = request.env['ir.config_parameter'].sudo()
            site_id = ICP.get_param('asyntai_chatbot.site_id', default='')
            return {
                'success': True,
                'data': {
                    'site_id': site_id,
                    'script_url': ICP.get_param('asyntai_chatbot.script_url',
                                                default=DEFAULT_SCRIPT_URL),
                    'account_email': ICP.get_param('asyntai_chatbot.account_email', default=''),
                    'connected': bool(site_id),
                },
            }
        except Exception as e:
            _logger.exception('Asyntai status error')
            return {'success': False, 'error': str(e)}

    # -----------------------------------------------------------------
    # Handshake
    # -----------------------------------------------------------------

    @http.route('/asyntai/api/prepare', type=JSON_ROUTE, auth='user', methods=['POST'], csrf=False)
    def prepare(self, **kwargs):
        """Park a fresh feed token at Asyntai and hand the browser the sign-in
        address."""
        _require_admin()
        model = request.env['asyntai.chatbot'].sudo()

        state = 'odoo_' + secrets.token_hex(12)
        # Signs the calls Asyntai makes back to the two feeds. Sent once, in
        # this request body, which is the only hop that never passes through a
        # browser, and never printed into a page.
        feed_token = secrets.token_hex(32)
        site_url = model.site_url()

        body = model.http_post_json(model.origin() + '/api/v1/wp-search/stage/', {
            'state': state,
            'site_url': site_url,
            'platform': 'odoo',
            # Which product is connecting. A chatbot install must not unlock
            # the paid AI Search bar.
            'product': 'chat',
            'feed_token': feed_token,
            'feed_url': site_url + '/asyntai/feed',
        })
        if body is None:
            return {'ok': False, 'error': 'Could not reach Asyntai. Check that this '
                                          'server can make outgoing HTTPS requests.'}

        # Kept only after Asyntai accepted it, so a failed handshake cannot
        # leave this site signing with a token nobody on the other side knows.
        model.set('feed_token', feed_token)
        model.set('state', state)
        model.set('state_at', str(int(time.time())))

        query = {
            'state': state,
            'site_url': site_url,
            'platform': 'odoo',
            'product': 'chat',
            'wp_email': request.env.user.email or '',
            'lang': (request.env.user.lang or 'en')[:2],
        }
        return {'ok': True, 'state': state,
                'url': model.origin() + '/wp-auth?' + urlencode(query)}

    @http.route('/asyntai/api/poll', type=JSON_ROUTE, auth='user', methods=['POST'], csrf=False)
    def poll(self, state='', **kwargs):
        """Has the owner finished signing in?"""
        _require_admin()
        model = request.env['asyntai.chatbot'].sudo()

        state = (state or '').strip()
        # Only the token this site just made is ever polled, so a guessed or
        # replayed token cannot read somebody else's handshake.
        if not state or state != model.get('state', ''):
            return {'ok': False, 'error': 'Unknown handshake. Press Get started again.'}

        try:
            started = int(model.get('state_at', '0') or 0)
        except ValueError:
            started = 0
        if int(time.time()) - started > STATE_TTL:
            return {'ok': False, 'error': 'This connection attempt has expired. '
                                          'Please press Get started again.'}

        body = model.http_get(model.origin() + '/api/v1/wp-search/connect-status/',
                              {'state': state})
        try:
            decoded = json.loads(body) if body else None
        except ValueError:
            decoded = None

        data = decoded.get('data') if isinstance(decoded, dict) else None
        if not isinstance(decoded, dict) or not decoded.get('ready') \
                or not isinstance(data, dict) or not data.get('site_id'):
            return {'ok': True, 'ready': False}

        return {
            'ok': True,
            'ready': True,
            'site_id': str(data.get('site_id')),
            'script_url': str(data.get('script_url') or ''),
            'account_email': str(data.get('account_email') or ''),
        }

    # -----------------------------------------------------------------
    # Content sharing, as the settings screen shows it
    # -----------------------------------------------------------------

    @http.route('/asyntai/api/sharing', type=JSON_ROUTE, auth='user', methods=['POST'], csrf=False)
    def sharing(self, **kwargs):
        """Whether pages and products are shared, and what Asyntai last read."""
        _require_admin()
        model = request.env['asyntai.chatbot'].sudo()

        out = {
            'ok': True,
            'connected': bool(model.site_id()),
            # A site connected under 1.0 has no feed token: 1.0 never made one.
            'available': bool(model.feed_token()),
            'enabled': model.sharing(),
            'shop': model.shop_installed(),
            'blog': model.blog_installed(),
            'sync': None,
            'products': 0,
        }
        if out['connected'] and out['available']:
            status = model.status() or {}
            sync = status.get('sync')
            out['sync'] = sync if isinstance(sync, dict) else None
            try:
                out['products'] = int(status.get('products') or 0)
            except (TypeError, ValueError):
                out['products'] = 0
        return out

    @http.route('/asyntai/api/share', type=JSON_ROUTE, auth='user', methods=['POST'], csrf=False)
    def share(self, enabled=True, **kwargs):
        """Switch sharing on or off, then ask Asyntai to read again at once,
        so switching off removes what was read and switching on brings it
        back without waiting for the daily read."""
        _require_admin()
        model = request.env['asyntai.chatbot'].sudo()
        model.set('share', '1' if enabled else '0')
        ok, message = model.request_sync()
        return {'ok': True, 'enabled': bool(enabled), 'synced': ok, 'message': message}

    @http.route('/asyntai/api/sync', type=JSON_ROUTE, auth='user', methods=['POST'], csrf=False)
    def sync(self, **kwargs):
        """Ask Asyntai to read the pages and products again now."""
        _require_admin()
        ok, message = request.env['asyntai.chatbot'].sudo().request_sync()
        return {'ok': ok, 'message': message}

    # -----------------------------------------------------------------
    # The feeds
    # -----------------------------------------------------------------

    @http.route('/asyntai/feed', type='http', auth='public', methods=['GET'],
                website=True, multilang=False, sitemap=False, csrf=False)
    def feed(self, **query):
        """The published products, the way a shopper sees them.

        Same shape as the catalogue feed of the Asyntai OpenCart extension,
        so Asyntai reads it with the same reader. Prices come from the
        website's pricelist and tax setting, in the website's currency.
        """
        status, body = self._products(query)
        return self._json(status, body)

    @http.route('/asyntai/feed/pages', type='http', auth='public', methods=['GET'],
                website=True, multilang=False, sitemap=False, csrf=False)
    def feed_pages(self, **query):
        """The published, public website pages and blog posts."""
        status, body = self._pages(query)
        return self._json(status, body)

    @staticmethod
    def _json(status, body):
        return request.make_json_response(
            body, status=status,
            headers=[('Cache-Control', 'no-store'), ('X-Robots-Tag', 'noindex')],
        )

    def _verify(self, query):
        """None when the call is signed with this site's feed token, else
        the (status, body) to refuse it with.

        The token alone is the proof, not the site id. Asyntai starts reading
        the moment the owner signs in, which is before this server has polled
        for the site id, and a feed that refused that first read would be
        marked disconnected for good.
        """
        token = request.env['asyntai.chatbot'].sudo().feed_token()
        if not token:
            return 403, {'ok': False, 'error': 'This site is not connected to Asyntai.'}

        ts = str(query.get('ts', ''))
        sig = str(query.get('sig', ''))
        # The signature covers the values AS SENT, so the string signed by
        # Asyntai is the string checked here.
        signed = 'page=%s&limit=%s&ids=%s&ts=%s' % (
            query.get('page', ''), query.get('limit', ''), query.get('ids', ''), ts)

        if not ts.isdigit():
            return 403, {'ok': False, 'error': 'Missing timestamp.'}
        # A replayed request is worth little here, but a signature with no
        # expiry is a credential that never dies.
        if abs(int(time.time()) - int(ts)) > CLOCK_SKEW:
            return 403, {'ok': False, 'error': 'The request has expired.'}

        expected = hmac.new(token.encode('utf-8'), signed.encode('utf-8'),
                            hashlib.sha256).hexdigest()
        if not sig or not hmac.compare_digest(expected, sig):
            return 403, {'ok': False, 'error': 'Bad signature.'}
        return None

    def _paging(self, query):
        raw_page = str(query.get('page', ''))
        raw_limit = str(query.get('limit', ''))
        page = int(raw_page) if raw_page.isdigit() and int(raw_page) > 0 else 1
        limit = int(raw_limit) if raw_limit.isdigit() else PAGE_SIZE
        if limit < 1 or limit > MAX_PAGE_SIZE:
            limit = PAGE_SIZE
        return page, limit

    def _store(self, website):
        model = request.env['asyntai.chatbot'].sudo()
        site_url = model.site_url()
        return {
            'name': website.name or request.env.company.name or '',
            'url': site_url,
            'currency': self._currency(website),
            'platform': 'odoo',
            'version': 'Odoo %s' % release.version.split('+')[0],
            # Where the pages are. Asyntai reads it from here, and only on
            # the host it read this answer from.
            'pages_url': site_url + '/asyntai/feed/pages',
        }

    # -- products ------------------------------------------------------

    def _products(self, query):
        refused = self._verify(query)
        if refused:
            return refused

        model = request.env['asyntai.chatbot'].sudo()
        website = request.env['website'].get_current_website()
        store = self._store(website)
        empty = {'ok': True, 'store': store, 'page': 1, 'pages': 1,
                 'total': 0, 'products': []}

        # Switched off, or no shop: an empty catalogue, so Asyntai drops
        # what it read before rather than keeping it.
        if not model.sharing() or not model.shop_installed():
            return 200, empty

        templates = request.env['product.template'].sudo().with_context(
            website_id=website.id, lang=website.default_lang_id.code)

        # What the shop itself shows: published, for sale, on this website.
        domain = [('sale_ok', '=', True), ('is_published', '=', True),
                  ('website_id', 'in', (False, website.id))]

        ids = str(query.get('ids', ''))
        if ids:
            wanted = []
            for piece in ids.split(','):
                piece = piece.strip()
                if piece.isdigit() and int(piece) not in wanted:
                    wanted.append(int(piece))
                if len(wanted) >= 50:
                    break
            rows = templates.search(domain + [('id', 'in', wanted)], order='id')
            products = [p for p in (self._product(t, website) for t in rows) if p]
            return 200, dict(empty, total=len(products), products=products)

        page, limit = self._paging(query)
        total = templates.search_count(domain)
        # Ordered by id rather than by name, so a rename between two pages
        # cannot make a product appear twice or not at all.
        rows = templates.search(domain, order='id', limit=limit, offset=(page - 1) * limit)
        products = [p for p in (self._product(t, website) for t in rows) if p]
        return 200, dict(empty, page=page, pages=max(1, -(-total // limit)),
                         total=total, products=products)

    def _currency(self, website):
        try:
            return website.currency_id.name or ''
        except Exception:
            try:
                return request.env.company.currency_id.name or ''
            except Exception:
                return ''

    def _product(self, template, website):
        """One product, as a shopper would see it, or None."""
        name = _plain(template.name or '')
        if not name:
            return None

        out = {'id': template.id, 'name': name}

        description = _plain(
            getattr(template, 'description_ecommerce', None)
            or template.description_sale
            or getattr(template, 'description', None) or '')
        if description:
            out['description'] = description

        if template.default_code:
            out['sku'] = template.default_code
        if template.barcode:
            out['ean'] = template.barcode

        price, special, currency = self._price(template)
        if price is not None:
            out['price'] = price
        if special is not None:
            out['special'] = special
        out['currency'] = currency or self._currency(website)
        quantity, in_stock = self._stock(template, website)
        if quantity is not None:
            out['quantity'] = quantity
        if in_stock is not None:
            out['stock_status'] = 'In stock' if in_stock else 'Out of stock'

        categories = []
        for category in getattr(template, 'public_categ_ids', []):
            label = (category.display_name or category.name or '').strip()
            if label and label not in categories:
                categories.append(label)
        if categories:
            out['categories'] = categories

        base = self._base_url(website)
        path = template.website_url or ('/shop/%d' % template.id)
        out['url'] = base + path if path.startswith('/') else path

        if template.image_1920:
            out['image_url'] = base + website.image_url(template, 'image_512')

        return out

    def _stock(self, template, website):
        """(quantity, in_stock) for one product, each None when unknown.

        Read per variant, the way the shop page reads it: the template-level
        combination info answers 0 for every product once Inventory is
        installed, because a template is not a variant. Products Inventory
        does not count give (None, None): the shop always sells them. A
        counted product at 0 that the shop still sells gives (None, True).
        """
        try:
            variants = template.product_variant_ids
            if not variants or 'free_qty' not in variants._fields:
                return None, None  # Inventory is not installed

            if 'is_storable' in template._fields:  # 18 and later
                storable = bool(template.is_storable)
            else:  # 16 and 17
                storable = (getattr(template, 'detailed_type', None) or template.type) == 'product'
            if not storable:
                return None, None

            total = 0.0
            for variant in variants.sudo():
                if hasattr(website, '_get_product_available_qty'):
                    free = website._get_product_available_qty(variant)
                elif hasattr(website, '_get_warehouse_available'):
                    free = variant.with_context(warehouse=website._get_warehouse_available()).free_qty
                else:
                    free = variant.free_qty
                total += max(0.0, float(free or 0))

            quantity = int(total)
            if quantity <= 0 and getattr(template, 'allow_out_of_stock_order', False):
                return None, True
            return quantity, quantity > 0
        except Exception as e:
            _logger.info('Asyntai AI Chatbot: stock of %s unknown: %s', template.id, e)
            return None, None

    def _price(self, template):
        """(price, special, currency) with the website's pricelist and tax
        display applied. The catalogue price when that fails."""
        try:
            info = template._get_combination_info(only_template=True)
            currency = info.get('currency')
            currency = currency.name if currency is not None and hasattr(currency, 'name') else ''
            price = info.get('price')
            list_price = info.get('list_price')
            special = None
            if info.get('has_discounted_price') and list_price is not None \
                    and price is not None and float(price) < float(list_price):
                special, price = price, list_price
            return self._money(price), self._money(special), currency
        except Exception as e:
            _logger.info('Asyntai AI Chatbot: price of %s fell back: %s', template.id, e)
            return self._money(template.list_price), None, ''

    @staticmethod
    def _money(value):
        if value is None:
            return None
        try:
            return '%.4f' % float(value)
        except (TypeError, ValueError):
            return None

    def _base_url(self, website):
        try:
            base = website.get_base_url()
        except Exception:
            base = ''
        if not base:
            base = request.env['asyntai.chatbot'].sudo().site_url()
        return (base or '').rstrip('/')

    # -- pages and blog posts ------------------------------------------

    def _pages(self, query):
        refused = self._verify(query)
        if refused:
            return refused

        model = request.env['asyntai.chatbot'].sudo()
        website = request.env['website'].get_current_website()
        store = self._store(website)
        empty = {'ok': True, 'store': store, 'page': 1, 'pages': 1,
                 'total': 0, 'items': []}

        # Switched off: no pages, so Asyntai drops what it read before.
        if not model.sharing():
            return 200, empty

        records = [('page', pid) for pid in self._page_ids(website)]
        if model.blog_installed():
            records += [('post', pid) for pid in self._post_ids(website)]

        page, limit = self._paging(query)
        total = len(records)
        window = records[(page - 1) * limit:page * limit]

        lang = website.default_lang_id.code
        base = self._base_url(website)
        page_ids = [rid for kind, rid in window if kind == 'page']
        post_ids = [rid for kind, rid in window if kind == 'post']
        pages = {p.id: p for p in request.env['website.page'].sudo().with_context(
            lang=lang).browse(page_ids)}
        posts = {p.id: p for p in request.env['blog.post'].sudo().with_context(
            lang=lang).browse(post_ids)} if post_ids else {}

        items = []
        for kind, rid in window:
            item = self._page_item(pages[rid], base) if kind == 'page' \
                else self._post_item(posts[rid], base)
            if item:
                items.append(item)

        return 200, dict(empty, page=page, pages=max(1, -(-total // limit)),
                         total=total, items=items)

    def _page_ids(self, website):
        """Ids of the pages any visitor can open, one per address.

        A page shared by every website and a copy made for this website can
        sit at the same address; the copy is what this website shows.
        """
        Page = request.env['website.page'].sudo()
        domain = [('is_published', '=', True),
                  ('website_id', 'in', (False, website.id))]
        rows = Page.search(domain, order='id')

        chosen = {}
        for page in rows:
            # Pages for signed-in users, for a group, or behind a password
            # are not public, so they are never sent.
            if getattr(page, 'visibility', False):
                continue
            # A page the owner keeps out of search engines (a thank-you
            # page after a form, for example) is kept out of here as well.
            if 'website_indexed' in page._fields and not page.website_indexed:
                continue
            url = page.url or ''
            if not url:
                continue
            current = chosen.get(url)
            if current is None or (page.website_id and not current.website_id):
                chosen[url] = page
        return sorted(p.id for p in chosen.values())

    def _post_ids(self, website):
        Post = request.env['blog.post'].sudo()
        domain = [('is_published', '=', True),
                  ('website_id', 'in', (False, website.id))]
        if 'post_date' in Post._fields:
            # A post scheduled for later is published but not visible yet.
            domain.append(('post_date', '<=', fields.Datetime.now()))
        return Post.search(domain, order='id').ids

    def _page_item(self, page, base):
        title = _plain(page.name or '')
        try:
            content = _plain(page.view_id.arch or '')
        except Exception as e:
            _logger.info('Asyntai AI Chatbot: page %s unreadable: %s', page.id, e)
            content = ''
        if not title or not content:
            return None
        item = {'type': 'page', 'id': page.id, 'title': title, 'content': content}
        url = page.url or ''
        if url.startswith('/'):
            item['url'] = base + url
        summary = _plain(getattr(page, 'website_meta_description', '') or '')
        if summary:
            item['summary'] = summary
        return item

    def _post_item(self, post, base):
        title = _plain(post.name or '')
        content = _plain(post.content or '')
        if not title or not content:
            return None
        item = {'type': 'post', 'id': post.id, 'title': title, 'content': content}
        try:
            blog = _plain(post.blog_id.name or '')
        except Exception:
            blog = ''
        if blog:
            item['blog'] = blog
        url = getattr(post, 'website_url', '') or ''
        if url.startswith('/'):
            item['url'] = base + url
        summary = _plain(getattr(post, 'subtitle', '') or '') \
            or _plain(getattr(post, 'website_meta_description', '') or '')
        if summary:
            item['summary'] = summary
        return item
