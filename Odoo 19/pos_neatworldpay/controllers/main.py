# coding: utf-8
# Original Author: Daniel Stoynev
# Copyright (c) 2025 SNS Software Ltd. All rights reserved.
# This module extends Odoo's payment framework.
# Odoo is a trademark of Odoo S.A.
import logging
import pprint
import json
import uuid
from odoo import fields, http
from odoo.http import request
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
import werkzeug.wrappers
import time
from .config import timeout_delta
from cryptography.fernet import Fernet
from decimal import Decimal, getcontext
_logger = logging.getLogger(__name__)


class PosWorldpayController(http.Controller):
    def get_user_name(self, user_id):
        try:
            user = request.env['res.users'].browse(user_id)
            if user:
                return user.name
            return "Unknown"
        except Exception:
            return "Unknown"
    def get_refunds(self, refunded_order_line_id, amt):
        pos_orders = http.request.env['pos.order'].sudo().search([
            ('lines', 'in', refunded_order_line_id)
        ]).read(['pos_reference'])
        if len(pos_orders) == 0:
            return []
        order_id = pos_orders[0]['pos_reference']
        _logger.info('get_refunds pos_orders: %s, refunded_order_line_id: ', pos_orders, refunded_order_line_id)
        space_index = order_id.find(" ")
        if space_index != -1:
            order_id = order_id[space_index + 1:]
        paid_payments_ref = http.request.env['neat.worldpay.payment.request'].sudo().search(
            [('status', 'like', 'processed_%'), ('order_id', '=', order_id), ('amount', '>=', 0)])
        paid_payments = paid_payments_ref.read(['amount', 'refunded_amt', 'uncommited_refunded_amt', 'transaction_id', 'card_type', 'uti', 'rrn'])
        refunds = []
        covered_sum = 0
        _logger.info("get_refunds payments: %s", paid_payments)
        for payment in paid_payments:
            remainder = abs(abs(amt) - covered_sum)
            left_for_refund_amount = abs(payment['amount'] - payment['refunded_amt'])
            if left_for_refund_amount > 0:
                refund = {'transaction_id': payment['transaction_id'], 'card_type': payment['card_type'], 'uti': payment['uti'], 'rrn': payment['rrn']}
                refunds.append(refund)
                if remainder >= left_for_refund_amount:
                    refund['amount'] = left_for_refund_amount
                else:
                    refund['amount'] = remainder
                covered_sum = covered_sum + refund['amount']
                ramount = refund['amount']
                refund['amount'] = -1 * refund['amount']
                _logger.info("get_refunds payment: %s, refund: %s", payment, refund)
                if remainder - ramount == 0:
                    break

        return refunds
    def commit_refunds(self, refunded_order_line_id):
        pos_orders = http.request.env['pos.order'].sudo().search([
            ('lines', 'in', refunded_order_line_id)
        ]).read(['pos_reference'])
        if len(pos_orders) == 0:
            return []
        order_id = pos_orders[0]['pos_reference']
        space_index = order_id.find(" ")
        if space_index != -1:
            order_id = order_id[space_index + 1:]
        paid_payments_ref = http.request.env['neat.worldpay.payment.request'].sudo().search(
            [('status', 'like', 'processed_%'), ('order_id', '=', order_id)])
        for refund in paid_payments_ref:
            refund.sudo().write({'refunded_amt': refund['uncommited_refunded_amt']})
    def decrypt(self, token, fernet_key):
        fernet = Fernet(fernet_key)
        return fernet.decrypt(token.encode()).decode()

    def encrypt(self, message, fernet_key):
        fernet = Fernet(fernet_key)
        return fernet.encrypt(message.encode()).decode()
    def get_secret_key(self):
        sc_rows = request.env['neat.worldpay.security'].sudo().search([]).read(['neat_worldpay_secret_key'])
        if len(sc_rows) == 0:
            pr = request.env['neat.worldpay.security'].sudo().create({'neat_worldpay_secret_key': 'str'})
            secret_key = pr.neat_worldpay_secret_key
        else:
            secret_key = sc_rows[0]['neat_worldpay_secret_key']
        return secret_key

    def generate_tokens(self, device_code, amount, transaction_id, start_date, is_refund, is_from_initial_request):
        pos_payment_methods = http.request.env['pos.payment.method'].sudo().search(
            [('neat_worldpay_terminal_device_code', '=', device_code)]).read(['neat_worldpay_terminal_pass_uuid'])
        if len(pos_payment_methods) == 0:
            return {'status': 404}
        payload = {
            'device_code': device_code,
            'pass_uuid': pos_payment_methods[0]['neat_worldpay_terminal_pass_uuid'],
            'amount': amount,
            'transaction_id': transaction_id,
            'start_date': start_date.timestamp(),
            'is_refund': is_refund,
            'is_from_initial_request': is_from_initial_request
        }

        secret_key = self.get_secret_key()
        token = self.encrypt(str(json.dumps(payload)), secret_key)
        return { 'payment_token': token, 'refresh_token': self.generate_refresh_token(device_code) }
    def auth_payment_token(self, payment_token, tid, amt, is_old_payment_token):
        secret_key = self.get_secret_key()
        decoded_token = json.loads(self.decrypt(payment_token, secret_key))
        device_code = decoded_token.get('device_code')
        pass_uuid = decoded_token.get('pass_uuid')
        start_date = datetime.utcfromtimestamp(decoded_token.get('start_date'))
        amount = decoded_token.get('amount')
        is_refund = decoded_token.get('is_refund')
        transaction_id = decoded_token.get('transaction_id')
        if is_old_payment_token:
            if not decoded_token['is_from_initial_request']:
                return { 'authenticated': False }
        else:
            current_datetime = datetime.utcnow()
            max_delta = timeout_delta
            delta = current_datetime - start_date
            if delta > max_delta:
                return { 'authenticated': False }

        if tid != transaction_id:
            return {'authenticated': False}
        if amt != amount:
            return {'authenticated': False}
        search_domain = [('neat_worldpay_terminal_device_code', '=', device_code)]
        if not is_old_payment_token:
            search_domain.append(('neat_worldpay_terminal_pass_uuid', '=', pass_uuid))
        pos_payment_methods = http.request.env['pos.payment.method'].sudo().search(search_domain).read(['neat_worldpay_terminal_device_code'])
        if len(pos_payment_methods) == 0:
            return { 'authenticated': False }
        current_payment_requests = http.request.env['neat.worldpay.payment.request'].sudo().search(
            [('terminal_id', '=', device_code), ('transaction_id', '=', transaction_id), ('amount', '=', amount), ('status', 'not like', 'processed_%')]).read(['status'])
        if len(current_payment_requests) == 0:
            return { 'authenticated': False }

        return { 'authenticated': True, 'device_code': device_code, 'transaction_id': transaction_id, 'amount': amount, 'is_refund': is_refund }
    def generate_refresh_token(self, device_code):
        pos_payment_methods = http.request.env['pos.payment.method'].sudo().search(
            [('neat_worldpay_terminal_device_code', '=', device_code)]).read(['neat_worldpay_terminal_pass_uuid'])
        if len(pos_payment_methods) == 0:
            return {'status': 404}
        payload = {
            'device_code': device_code,
            'timestamp': datetime.utcnow().timestamp(),
            'pass_uuid': pos_payment_methods[0]['neat_worldpay_terminal_pass_uuid']
        }

        secret_key = self.get_secret_key()
        token = self.encrypt(str(json.dumps(payload)), secret_key)
        return token
    def auth_refresh_token(self, refresh_token):
        secret_key = self.get_secret_key()
        decoded_token = json.loads(self.decrypt(refresh_token, secret_key))
        device_code = decoded_token['device_code']
        timestamp = decoded_token['timestamp']
        pass_uuid = decoded_token['pass_uuid']
        pos_payment_methods = http.request.env['pos.payment.method'].sudo().search(
            [('neat_worldpay_terminal_device_code', '=', device_code), ('neat_worldpay_terminal_pass_uuid', '=', pass_uuid)]).read(['neat_worldpay_terminal_device_code'])
        if len(pos_payment_methods) == 0:
            return { 'authenticated': False }
        token_datetime = datetime.utcfromtimestamp(timestamp)
        current_datetime = datetime.utcnow()
        max_delta = timedelta(days=180)
        delta = current_datetime - token_datetime
        if delta <= max_delta:
            return { 'authenticated': True, 'device_code': device_code }
        else:
            return { 'authenticated': False, 'device_code': device_code }

    @http.route('/pos_worldpay/is_order_the_same', type='json', auth='user', methods=['POST'])
    def is_order_the_same(self, refunded_order_line_ids):
        pos_orders = http.request.env['pos.order'].sudo().search([
            ('lines', 'in', refunded_order_line_ids)
        ]).read(['pos_reference'])
        is_order_the_same = False
        if pos_orders:
            first_pos_reference = pos_orders[0]['pos_reference']
            all_same_pos_reference = all(order['pos_reference'] == first_pos_reference for order in pos_orders)
            is_order_the_same = all_same_pos_reference
        return {'status': 200, 'data': {'is_order_the_same': is_order_the_same }}

    @http.route('/pos_worldpay/create_payment_request', type='json', auth='user', methods=['POST'])
    def create_payment_request(self, terminal_id, order_id, amount, user_id, refunded_order_line_id=None):
        if amount is not None:
            decimal_amount = Decimal(str(amount)) * Decimal('100')
            amount = int(decimal_amount)
        if amount == 0:
            _logger.info("create_payment_request called for order_id: " + str(order_id) + " amount: " + str(amount) + " returning 400")
            return { 'status': 400 }
        log_is_refund = refunded_order_line_id is not None
        _logger.info("create_payment_request called for order_id: " + str(order_id) + " amount: " + str(amount) + " is_refund: " + str(log_is_refund))
        current_datetime = datetime.utcnow()
        two_minutes_ago = current_datetime - timeout_delta
        current_payment_requests_ref = http.request.env['neat.worldpay.payment.request'].search(
            [('terminal_id', '=', terminal_id), ('status', '=', 'pending'), ('start_date', '>=', two_minutes_ago)])
        current_payment_requests = current_payment_requests_ref.read(['id', 'user_id', 'order_id', 'start_date', 'transaction_id'])
        current_resent_requests_ref = http.request.env['neat.worldpay.payment.request'].search(
            [('terminal_id', '=', terminal_id), ('status', 'like', 'resent_%'), ('status', 'not like', 'processed_%'), ('start_date', '>=', two_minutes_ago)])
        current_resent_requests = current_resent_requests_ref.read(
            ['id', 'user_id', 'order_id', 'start_date', 'transaction_id'])
        new_refunded_order_line_id = refunded_order_line_id
        if amount >= 0:
            new_refunded_order_line_id = None
        if len(current_resent_requests) == 0:
            if len(current_payment_requests) > 0:
                current_payment_request = current_payment_requests[0]
                current_payment_request_ref = current_payment_requests_ref[0]
                if current_payment_request['user_id'] != user_id or current_payment_request['order_id'] != order_id:
                    _logger.info("create_payment_request called for order_id: " + str(order_id) + " amount: " + str(amount) + " user_id: " + str(user_id) + " returning 403 because user_id or order_id mismatch")
                    return {'status': 403}
                current_payment_request_ref.write({'status': 'cancelled'})
            transaction_id = uuid.uuid4()
            _logger.info("cancel_payment_request order_id: " + str(order_id) + " generated transaction_id: " + str(transaction_id))
            payment_request = {
                'terminal_id': terminal_id,
                'order_id': order_id,
                'amount': amount,
                'status': 'pending',
                'start_date': datetime.utcnow(),
                'user_id': user_id,
                'refunded_order_line_id': new_refunded_order_line_id,
                'refunded_amt': 0,
                'uncommited_refunded_amt': 0,
                'transaction_id': transaction_id,
            }
            request.env['neat.worldpay.payment.request'].create(payment_request)
            _logger.info("create_payment_request called for order_id: " + str(order_id) + " amount: " + str(amount) + " user_id: " + str(user_id) + " returning 201")
            return { 'status': 201, 'data': { 'transaction_id': transaction_id } }
        else:
            current_payment_request = current_resent_requests[0]
            current_payment_request_ref = current_resent_requests_ref[0]
            if current_payment_request['user_id'] != user_id:
                return { 'status': 403 }
            current_payment_request_ref.write({'start_date': datetime.utcnow(), 'order_id': order_id})
            if len(current_payment_requests_ref) > 0:
                current_payment_requests_ref[0].write({ 'status': 'cancelled' })
            _logger.info("create_payment_request called for order_id: " + str(order_id) + " amount: " + str(amount) + " user_id: " + str(user_id) + " returning 200")
            return {'status': 200, 'data': {'transaction_id': current_payment_request['transaction_id']}}

    @http.route('/pos_worldpay/cancel_payment_request', type='json', auth='user', methods=['POST'])
    def cancel_payment_request(self, terminal_id, order_id):
        current_datetime = datetime.utcnow()
        _logger.info("cancel_payment_request called for order_id: %s", str(order_id))
        two_minutes_ago = current_datetime - timeout_delta + timedelta(seconds=5)
        current_payment_requests = http.request.env['neat.worldpay.payment.request'].search(
            [('terminal_id', '=', terminal_id), ('order_id', '=', order_id), ('status', '=', 'pending'), ('start_date', '>=', two_minutes_ago)])
        _logger.info("cancel payment_requests: %s", current_payment_requests)
        current_resent_requests = http.request.env['neat.worldpay.payment.request'].search(
            [('terminal_id', '=', terminal_id), ('status', 'like', 'resent_%'), ('status', 'not like', 'processed_%'), ('start_date', '>=', two_minutes_ago)])
        _logger.info("cancel resent_requests: %s", current_payment_requests)
        if len(current_payment_requests) == 0 and len(current_resent_requests) == 0:
            _logger.info("cancel_payment_request called for order_id: " + str(order_id) + " returning 404 because no requests found")
            return { 'status': 404 }
        for crr in current_resent_requests:
            crr.write({'status': 'cancelled'})
        for cpr in current_payment_requests:
            cpr.write({'status': 'cancelled'})
        _logger.info("cancel_payment_request called for order_id: " + str(order_id) + " returning 200")
        return { 'status': 200 }

    @http.route('/pos_worldpay/check_request', type='json', auth='user', methods=['POST'])
    def check_request(self, terminal_id, transaction_id):
        current_datetime = datetime.utcnow()
        two_minutes_ago = current_datetime - timeout_delta
        _logger.info("check_request called for transaction_id: " + str(transaction_id))
        current_payment_requests = http.request.env['neat.worldpay.payment.request'].search(
            [('transaction_id', '=', transaction_id), ('terminal_id', '=', terminal_id), ('status', 'not like', 'processed_%'), ('start_date', '>=', two_minutes_ago)], limit=1, order='start_date desc')
        if len(current_payment_requests) == 0:
            _logger.info("check_request called for transaction_id: " + str(transaction_id) + " returning 404 because no requests found")
            return { 'status': 404 }
        elif len(current_payment_requests) > 0 and current_payment_requests[0]['status'] != 'pending':
            current_payment_request = current_payment_requests[0]
            _logger.info("check_request called for transaction_id: " + str(transaction_id) + " returning 200")
            return { 'status': 200, 'data': {
                    'status': current_payment_request['status'],
                    'transaction_id': current_payment_request['transaction_id'],
                    'card_type': current_payment_request['card_type'],
                    'cardholder_name': current_payment_request['cardholder_name'],
                    'refunded_amount': float(Decimal(str(current_payment_request['refunded_amt'])) / Decimal('100')),
                    'is_refund': current_payment_request['refunded_order_line_id'] != False,
                    'transaction_amount': float(Decimal(str(current_payment_request['amount'])) / Decimal('100'))
                }
            }
        else:
            _logger.info("check_request called for transaction_id: " + str(transaction_id) + " returning 200 with pending status")
            return {'status': 200, 'data': { 'status': 'pending' }}

    @http.route('/pos_worldpay/request_processed', type='json', auth='user', methods=['POST'])
    def request_processed(self, terminal_id, transaction_id):
        _logger.info("request_processed called for transaction_id: " + str(transaction_id))
        current_payment_requests = http.request.env['neat.worldpay.payment.request'].search(
            [('transaction_id', '=', transaction_id), ('terminal_id', '=', terminal_id)],
            limit=1, order='start_date desc')
        if len(current_payment_requests) == 0:
            _logger.info("check_request called for transaction_id: " + str(transaction_id) + " returning 404 because no requests found")
            return {'status': 404}
        cpr = current_payment_requests[0]
        if cpr['status'] != 'done' and cpr['status'] != 'refunded' and cpr['status'] != 'resent_refunded' and cpr['status'] != 'resent_done':
            _logger.info("request_processed called for transaction_id: " + str(transaction_id) + " returning 400 because status is not done, refunded, resent_refunded, or resent_done")
            return { 'status': 400 }
        if cpr['refunded_order_line_id']:
            self.commit_refunds(cpr['refunded_order_line_id'])
        cpr.write({ 'status': 'processed_' + cpr['status'] })
        _logger.info("request_processed called for transaction_id: " + str(transaction_id) + " returning 200")
        return { 'status': 200 }

    @http.route('/pos_worldpay/set_license_key',type='http', auth='public', methods=['POST'], csrf=False, cors='*')
    def set_license_key(self):
        r = json.loads(http.request.httprequest.data)
        refresh_token = r['refresh_token']
        res = self.auth_refresh_token(refresh_token)
        if not res['authenticated']:
            return json.dumps({'status': 401})

        user_settings = http.request.env['neat.worldpay.settings'].sudo().search([])
        if len(user_settings) > 0:
            user_settings.write({ 'promotion_displayed': True, 'license_key': r['license_key'] })
        else:
            request.env['neat.worldpay.settings'].sudo().create({ 'promotion_displayed': True, 'license_key': r['license_key'] })
        return json.dumps({ 'status': 200 })

    @http.route('/pos_worldpay/get_license_key',type='http', auth='public', methods=['POST'], csrf=False, cors='*')
    def get_license_key(self):
        r = json.loads(http.request.httprequest.data)
        refresh_token = r['refresh_token']
        res = self.auth_refresh_token(refresh_token)
        if not res['authenticated']:
            return json.dumps({'status': 401})
        user_settings = http.request.env['neat.worldpay.settings'].sudo().search([]).read(['license_key'])
        license_key = None
        if len(user_settings):
            license_key = user_settings[0]['license_key']
        return json.dumps({'status': 200, 'data': { 'license_key': license_key }})

    @http.route('/pos_worldpay/log_message',type='http', auth='public', methods=['POST'], csrf=False, cors='*')
    def log_message(self):
        r = json.loads(http.request.httprequest.data)
        refresh_token = r['refresh_token']
        res = self.auth_refresh_token(refresh_token)
        if not res['authenticated']:
            return json.dumps({'status': 401})

        log_type = r['type']
        message = r['message']

        if log_type == 'info' or log_type == 'error':
            _logger.info("Worldpay POS " + res['device_code'] + " Logged(" + str(log_type) + "): " + str(message))
            return json.dumps({ 'status': 200 })

        return json.dumps({ 'status': 400 })

    @http.route('/pos_worldpay/log_message_ui', type='json', auth='user', methods=['POST'])
    def log_message_ui(self, terminal_id, transaction_id, type, message):
        _logger.info("Worldpay POS UI TerminalId(" + terminal_id + ") TransactionId(" + str(transaction_id) + ") Logged(" + str(type) + "): " + str(message))
        return { 'status': 200 }

    @http.route('/pos_worldpay/poll_payment_request',type='http', auth='public', methods=['POST'], csrf=False, cors='*')
    def poll_payment_request(self):
        r = json.loads(http.request.httprequest.data)
        refresh_token = r['refresh_token']
        res = self.auth_refresh_token(refresh_token)
        if not res['authenticated']:
            _logger.info("poll_payment_request called returning 401 because not authenticated")
            return json.dumps({ 'status': 401 })

        while True:
            current_datetime = datetime.utcnow()
            two_minutes_ago = current_datetime - timeout_delta
            current_payment_requests = http.request.env['neat.worldpay.payment.request'].sudo().search(
                [('terminal_id', '=', res['device_code']), ('status', '=', 'pending'),
                 ('start_date', '>=', two_minutes_ago)])
            if len(current_payment_requests) > 0:
                read_request = current_payment_requests.read(['amount', 'order_id', 'start_date', 'transaction_id', 'refunded_order_line_id', 'refunded_amt'])[0]
                tokens = self.generate_tokens(res['device_code'], read_request['amount'], read_request['transaction_id'], read_request['start_date'], read_request['refunded_order_line_id'] != False, True)
                if read_request['refunded_order_line_id']:
                    refunds = self.get_refunds(read_request['refunded_order_line_id'], read_request['amount'])
                    if len(refunds) == 0:
                        _logger.info("poll_payment_request called for transaction_id: " + str(read_request['transaction_id']) + " returning 404 because no refunds found")
                        return json.dumps({ 'status': 404 })
                    current_payment_requests[0].write({'start_date': datetime.utcnow() })
                    _logger.info("poll_payment_request found payment for transaction_id: " + str(read_request['transaction_id']))
                    return json.dumps({'status': 200, 'data': {'transaction_id': read_request['transaction_id'],
                                                               'refunds': refunds,
                                                               'amount': read_request['amount'],
                                                               'tokens': tokens}})
                current_payment_requests[0].write({'start_date': datetime.utcnow()})
                _logger.info("poll_payment_request found payment for transaction_id: " + str(read_request['transaction_id']))
                return json.dumps({ 'status': 200, 'data': { 'transaction_id': read_request['transaction_id'], 'amount': read_request['amount'], 'tokens': tokens } })
            time.sleep(1)

    @http.route('/pos_worldpay/notify_payment_request',type='http', auth='public', methods=['POST'], csrf=False, cors='*')
    def notify_payment_request(self):
        r = json.loads(http.request.httprequest.data)
        refresh_token = r['refresh_token']
        res = self.auth_refresh_token(refresh_token)
        if not res['authenticated']:
            return json.dumps({ 'status': 401 })

        current_datetime = datetime.utcnow()
        two_minutes_ago = current_datetime - timeout_delta
        current_payment_requests = http.request.env['neat.worldpay.payment.request'].sudo().search(
            [('terminal_id', '=', res['device_code']), ('status', '=', 'pending'),
                ('start_date', '>=', two_minutes_ago)])
                
        return json.dumps({ 'status': 200, 'data': { 'payment_request_found': len(current_payment_requests) > 0 } })

    @http.route('/pos_worldpay/complete',type='http', auth='public', methods=['POST'], csrf=False, cors='*')
    def complete(self):
        r = json.loads(http.request.httprequest.data)
        payment_token = r['payment_token']
        amt = r['amt']
        status = r['status']
        refunds = r.get('refunds', None)
        uti = r.get('uti', None)
        rrn = r.get('rrn', None)
        logs = r.get('logs', "")

        transaction_id = r.get('transaction_id', None)
        if status != 'done' and status != 'failed' and status != 'cancelled' and status != 'refunded' and status != 'resent_done' and status != 'resent_refunded':
            _logger.info("complete called for transaction_id: " + str(transaction_id) + " returning 400 because status is not done, failed, cancelled, refunded, resent_done, or resent_refunded")
            return json.dumps({ 'status': 400 })
        card_type = None
        if 'card_type' in r:
            card_type = r['card_type']
        cardholder_name = "Not Specified"
        _logger.info("complete payment for transaction_id: " + str(transaction_id) + " status: " + str(status) + " logs: " + str(logs))
        res = self.auth_payment_token(payment_token, transaction_id, amt, False)
        if not res['authenticated']:
            _logger.info("complete called for transaction_id: " + str(transaction_id) + " returning 401 because not authenticated")
            return json.dumps({'status': 401})
        if status == "resent_done" or status == "resent_refunded":
            current_payment_requests = http.request.env['neat.worldpay.payment.request'].sudo().search(
                [('terminal_id', '=', res['device_code']), ('transaction_id', '=', transaction_id),
                 ('status', 'not like', 'processed_%')])
        else:
            current_datetime = datetime.utcnow()
            two_minutes_ago = current_datetime - timeout_delta
            current_payment_requests = http.request.env['neat.worldpay.payment.request'].sudo().search(
                [('terminal_id', '=', res['device_code']), ('transaction_id', '=', transaction_id), ('status', '=', 'pending'),
                 ('start_date', '>=', two_minutes_ago)])
        if len(current_payment_requests) == 0:
            _logger.info("complete called for transaction_id: " + str(transaction_id) + " returning 404 because no requests found")
            return json.dumps({ 'status': 404 })
        total_refunded_amount = 0
        if res['is_refund']:
            if refunds == None:
                _logger.info("complete called for transaction_id: " + str(transaction_id) + " returning 400 because refunds is None")
                return json.dumps({ 'status': 400 })
            tids = list(map(lambda x : x['transaction_id'], refunds))
            refunded_payment_refs = http.request.env['neat.worldpay.payment.request'].sudo().search([('transaction_id', 'in', tids), ('amount', '>=', 0)])
            refunded_payments = refunded_payment_refs.read(['refunded_amt', 'transaction_id'])
            if len(refunded_payments) == 0:
                _logger.info("complete called for transaction_id: " + str(transaction_id) + " returning 404 because no refunded payments found")
                return json.dumps({ 'status': 404 })
            index = 0
            for payment in refunded_payments:
                ramount = payment['refunded_amt']
                refund = next(filter(lambda x: x['transaction_id'] == payment['transaction_id'], refunds), None)
                if refund and refund['status'] == 'refunded':
                    curr_ramount = abs(refund['amount'])
                    total_refunded_amount = total_refunded_amount + curr_ramount
                    new_refunded_amount = ramount + curr_ramount
                    refunded_payment_refs[index].write({ 'uncommited_refunded_amt': new_refunded_amount })
                index+=1
        if status == 'done' or status == "resent_done":
            pr = {
                'card_type': card_type,
                'cardholder_name': cardholder_name,
                'status': status,
                'refunded_amt': total_refunded_amount,
                'start_date': datetime.utcnow(),
                'uti': uti,
                'rrn': rrn
            }
        else:
            pr = {
                'status': status,
                'refunded_amt': total_refunded_amount,
                'start_date': datetime.utcnow()
            }

        current_payment_requests[0].write(pr)
        _logger.info("complete called for transaction_id: " + str(transaction_id) + " returning 200")
        return json.dumps({ 'status': 200 })

    @http.route('/pos_worldpay/validate_connection', type='http', auth='public', methods=['POST'], csrf=False, cors='*')
    def validate_connection(self):
        r = json.loads(http.request.httprequest.data)
        device_code = r['device_code']
        master_password = r['master_password']
        refresh_token = r.get('refresh_token', None)
        if refresh_token:
            auth_result = self.auth_refresh_token(refresh_token)
            if auth_result['device_code'] != device_code:
                return json.dumps({'status': 403})
        pos_payment_methods = http.request.env['pos.payment.method'].sudo().search([('neat_worldpay_terminal_device_code', '=', device_code)]).read(['name', 'neat_worldpay_terminal_master_pwd'])
        if len(pos_payment_methods) == 0:
            return json.dumps({ 'status': 404 })

        if not check_password_hash(pos_payment_methods[0]['neat_worldpay_terminal_master_pwd'], master_password):
            return json.dumps({ 'status': 401 })
        token = self.generate_refresh_token(device_code)
        return json.dumps({ 'status': 200, 'data': { 'refresh_token': token } })

    @http.route('/pos_worldpay/payment_history', type='http', auth='public', methods=['POST'], csrf=False, cors='*')
    def payment_history(self):
        request_data = json.loads(http.request.httprequest.data)
        refresh_token = request_data.get('refresh_token')
        start_date_text = request_data.get('start_date')
        end_date_text = request_data.get('end_date')
        page = request_data.get('page') or 1
        filter_value = request_data.get('filter', '')

        date_format = "%Y-%m-%d"
        start_date = datetime.strptime(start_date_text, date_format)
        end_date = datetime.strptime(end_date_text, date_format)
        auth_result = self.auth_refresh_token(refresh_token)
        if not auth_result['authenticated']:
            return json.dumps({'status': 401})

        terminal_id = auth_result['device_code']
        per_page = 20
        offset = (page - 1) * per_page

        if filter_value != '':
            domain = [
                ('terminal_id', '=', terminal_id),
                ('start_date', '>=', start_date),
                ('start_date', '<=', end_date),
                '|',
                ('order_id', 'ilike', filter_value),
                ('transaction_id', 'ilike', filter_value),
            ]
        else:
            domain = [
                ('terminal_id', '=', terminal_id),
                ('start_date', '>=', start_date),
                ('start_date', '<=', end_date)
            ]

        total_records = http.request.env['neat.worldpay.payment.request'].sudo().search_count(domain)
        results = http.request.env['neat.worldpay.payment.request'].sudo().search(domain, offset=offset, limit=per_page, order='start_date desc').read(['create_date', 'order_id', 'user_id', 'transaction_id', 'amount', 'status', 'refunded_order_line_id', 'card_type'])
        final_results = []
        for result in results:
            date_format = "%Y-%m-%dT%H:%M:%S.%fZ"  # Use the desired format
            create_date = result['create_date'].strftime(date_format)
            if result['refunded_order_line_id']:
                refunds = self.get_refunds(result['refunded_order_line_id'], result['amount'])
                if len(refunds) > 0:
                    user_name = self.get_user_name(result['user_id'])
                    final_result = {**result, 'create_date': create_date, 'user_name': user_name, 'amount': result['amount'], 'refunds': refunds}
                    del final_result['refunded_order_line_id']
                    del final_result['user_id']
                    final_results.append(final_result)
            else:
                user_name = self.get_user_name(result['user_id'])
                final_result = {**result, 'create_date': create_date, 'user_name': user_name, 'amount': result['amount']}
                del final_result['refunded_order_line_id']
                del final_result['user_id']
                final_results.append(final_result)

        # Calculate the total number of pages
        total_pages = -(-total_records // per_page)  # Ceiling division to ensure we get the correct number of pages

        # Return the results with pagination information
        response_data = {
            'status': 200,
            'data': {
                'results': final_results,
                'page': page,
                'total_pages': total_pages,
            },
        }

        return json.dumps(response_data)

    @http.route('/pos_worldpay/resend_intent',type='http', auth='public', methods=['POST'], csrf=False, cors='*')
    def resend_intent(self):
        r = json.loads(http.request.httprequest.data)
        refresh_token = r['refresh_token']
        transaction_id = r['transaction_id']
        amt = r['amt']
        old_payment_token = r['old_payment_token']
        res = self.auth_refresh_token(refresh_token)
        if not res['authenticated']:
            return json.dumps({ 'status': 401 })
        old_payment_res = self.auth_payment_token(old_payment_token, transaction_id, amt, True)
        if not old_payment_res['authenticated']:
            return json.dumps({'status': 401})
        current_payment_requests = http.request.env['neat.worldpay.payment.request'].sudo().search(
            [('terminal_id', '=', res['device_code']), ('transaction_id', '=', transaction_id)])
        if len(current_payment_requests) > 0:
            read_request = current_payment_requests.read(['amount', 'refunded_order_line_id', 'refunded_amt', 'uncommited_refunded_amt'])[0]
            _logger.info('resend_intent: %s', read_request)
            tokens = self.generate_tokens(res['device_code'], read_request['amount'], transaction_id, datetime.utcnow(), read_request['refunded_order_line_id'] != False, False)
            return json.dumps({ 'status': 200, 'data': { 'tokens': tokens } })

        return json.dumps({ 'status': 404 })

    @http.route('/pos_worldpay/override_intent', type='http', auth='public', methods=['POST'], csrf=False, cors='*')
    def override_intent(self):
        r = json.loads(http.request.httprequest.data)
        username = r['username']
        password = r['password']
        refresh_token = r['refresh_token']
        transaction_id = r['transaction_id']
        amt = r['amt']
        res = self.auth_refresh_token(refresh_token)
        if not res['authenticated']:
            return json.dumps({ 'status': 401 })
        current_payment_requests = http.request.env['neat.worldpay.payment.request'].sudo().search(
            [('terminal_id', '=', res['device_code']), ('transaction_id', '=', transaction_id)])
        if len(current_payment_requests) > 0:
            read_request = current_payment_requests.read(['amount', 'refunded_order_line_id', 'refunded_amt', 'transaction_id'])[0]
            if read_request['amount'] != amt:
                return json.dumps({ 'status': 403 })
            dbname = http.request.httprequest.environ.get('HTTP_DBNAME')
            user_id = http.request.env['res.users'].sudo().with_context(http.request.env.context).authenticate(dbname, {'login': username, 'password': password, 'type': 'password'}, { 'interactive': False })
            _logger.info('user_id from override: %s', user_id)
            if user_id:
                user_id = user_id['uid']
            else:
                return json.dumps({'status': 403})
            user = http.request.env['res.users'].sudo().browse(user_id)
            if user:
                payment_methods = http.request.env['pos.payment.method'].sudo().search(
                    [('neat_worldpay_terminal_device_code', '=', res['device_code'])]).read(['neat_worldpay_terminal_manager_group_selection'])
                if len(payment_methods) == 0:
                    return json.dumps({ 'status': 401 })
                is_manager = user.has_group(payment_methods[0]['neat_worldpay_terminal_manager_group_selection'])
                if not is_manager:
                    return json.dumps({ 'status': 403 })

                tokens = self.generate_tokens(res['device_code'], read_request['amount'],
                                              read_request['transaction_id'], datetime.utcnow(),
                                              read_request['refunded_order_line_id'] != False, False)
                return json.dumps({ 'status': 200, 'data': { 'tokens': tokens } })
            else:
                return json.dumps({ 'status': 403 })
        return json.dumps({ 'status': 404 })

    @http.route('/pos_worldpay/info',type='http', auth='public', methods=['POST'], csrf=False, cors='*')
    def info(self):
        r = json.loads(http.request.httprequest.data)
        refresh_token = r['refresh_token']
        res = self.auth_refresh_token(refresh_token)
        if not res['authenticated']:
            return json.dumps({ 'status': 401 })
        pos_payment_method = http.request.env['pos.payment.method'].sudo().search(
            [('neat_worldpay_terminal_device_code', '=', res['device_code'])])
        if len(pos_payment_method) == 0:
            return json.dumps({ 'status': 404 })

        return json.dumps({ 
            'status': 200, 
            'data': { 
                'name': pos_payment_method[0].name, 
                'url': pos_payment_method[0].company_id.website,
                'ws_url': pos_payment_method[0].neat_worldpay_ws_url,
                'is_desktop_mode': pos_payment_method[0].neat_worldpay_is_desktop_mode,
                'is_local_ws_server': pos_payment_method[0].neat_worldpay_is_local_ws_server,
                'self_signed_certificates': pos_payment_method[0].neat_worldpay_self_signed_certificates
            } 
        })






