# Original Author: Daniel Stoynev
# Copyright (c) 2025 SNS Software Ltd. All rights reserved.
# This module extends Odoo's payment framework.
# Odoo is a trademark of Odoo S.A.

import base64
import binascii
import json
import hashlib
import hmac
import logging
import pprint
import re
import requests
import time
import uuid
from decimal import Decimal
from odoo.http import request
from odoo import _, http, fields, sql_db
from contextlib import closing
from odoo.exceptions import ValidationError
from datetime import datetime
from werkzeug import urls

_logger = logging.getLogger(__name__)


class NeatWorldpayController(http.Controller):

    result_action = "/neatworldpay/result"
    _allowed_ips = [
        '34.246.73.11', '52.215.22.123', '52.31.61.0', '18.130.125.132',
        '35.176.91.145', '52.56.235.128', '18.185.7.67', '18.185.134.117',
        '18.185.158.215', '52.48.6.187', '34.243.65.63', '3.255.13.18',
        '3.251.36.74', '63.32.208.6', '52.19.45.138', '3.11.50.124',
        '3.11.213.43', '3.14.190.43', '3.121.172.32', '3.125.11.252',
        '3.126.98.120', '3.139.153.185', '3.139.255.63', '13.200.51.10',
        '13.200.56.25', '13.232.151.127', '34.236.63.10', '34.253.172.98',
        '35.170.209.108', '35.177.246.6', '52.4.68.25', '52.51.12.88',
        '108.129.30.203'
    ]

    def _get_link_signing_secret(self):
        return (request.env['ir.config_parameter'].sudo().get_param('database.secret') or '').encode()

    def _build_link_payload(self, link_rec):
        payload_data = {
            'link_id': link_rec.id,
            'reference': link_rec.reference,
            'provider_id': link_rec.provider_id.id,
        }
        payload_json = json.dumps(payload_data, separators=(',', ':')).encode()
        encoded_payload = base64.urlsafe_b64encode(payload_json).decode().rstrip('=')
        signature = hmac.new(self._get_link_signing_secret(), encoded_payload.encode(), hashlib.sha256).hexdigest()
        return f'{encoded_payload}.{signature}'

    def _parse_link_payload(self, payload):
        try:
            encoded_payload, signature = payload.split('.', 1)
            expected_signature = hmac.new(self._get_link_signing_secret(), encoded_payload.encode(), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(signature, expected_signature):
                return None
            padding = '=' * (-len(encoded_payload) % 4)
            data = json.loads(base64.urlsafe_b64decode((encoded_payload + padding).encode()).decode())
            return data
        except Exception:
            return None

    def _is_guid_reference(self, reference):
        if (reference or '').startswith('pl/'):
            return True
        try:
            uuid.UUID(reference or "")
            return True
        except Exception:
            return False

    def _is_virtual_payment_reference(self, reference):
        return (reference or '').startswith('vt/')

    def _confirm_sale_orders(self, orders):
        orders = orders.filtered(lambda o: o.state in ('draft', 'sent'))
        for order in orders:
            order.action_confirm()

    def _schedule_multi_order_failure_activity(self, orders, reference, fallback_user_id=False):
        for order in orders:
            user_id = order.user_id.id if order.user_id else (int(fallback_user_id) if fallback_user_id else None)
            order.activity_schedule(
                act_type_xmlid='mail.mail_activity_data_todo',
                user_id=user_id,
                date_deadline=fields.Date.today(),
                summary="Payment Failed - Action Required",
                note=f"The payment failed after initial confirmation {reference}. Please review and take action."
            )

    def _schedule_multi_invoice_failure_activity(self, invoices, reference, fallback_user_id=False):
        for invoice in invoices:
            user_id = invoice.user_id.id if invoice.user_id else (int(fallback_user_id) if fallback_user_id else None)
            invoice.activity_schedule(
                act_type_xmlid='mail.mail_activity_data_todo',
                user_id=user_id,
                date_deadline=fields.Date.today(),
                summary="Payment Failed - Action Required",
                note=f"The payment failed after initial confirmation {reference}. Please review and take action."
            )
            _logger.info(f"\n Invoice Found for cancelled transaction creating activity {reference} {invoice} \n")

    def _handle_guid_link_invoices(self, reference, result_state):
        link_rec = request.env['worldpay.payment.link'].sudo().search([('reference', '=', reference)], limit=1)
        if not link_rec:
            return False
        target_status = 'paid' if result_state == 'done' else result_state
        if link_rec.status == 'paid' and result_state in ('cancel', 'error'):
            return True
        if link_rec.status == target_status:
            return True
        if link_rec.status == 'paid' and target_status in ('pending', 'cancel', 'error'):
            return True

        if result_state in ('pending', 'cancel', 'error'):
            link_rec.sudo().write({'status': result_state})

        if link_rec.sale_order_ids:
            orders = link_rec.sale_order_ids.filtered(lambda o: o.state in ('draft', 'sent'))
            order_names = ', '.join(link_rec.sale_order_ids.mapped('name'))
            if result_state == 'done' and orders:
                self._confirm_sale_orders(orders)
                note_body = (
                    f"Payment was made for reference {reference}. "
                    f"Multiple sales orders were paid together. "
                    f"Sales orders in this payment link: {order_names}"
                )
                admin_user = request.env.ref('base.user_admin')
                for order in link_rec.sale_order_ids:
                    order.with_user(admin_user).sudo().message_post(
                        body=note_body,
                        message_type='comment',
                        subtype_xmlid='mail.mt_note',
                    )
                link_rec.sudo().write({'status': 'paid'})
            elif result_state == 'done':
                link_rec.sudo().write({'status': 'paid'})
            return True

        invoices = link_rec.invoice_ids.filtered(lambda m: m.state == 'posted' and m.payment_state != 'paid')
        invoice_names = ', '.join(link_rec.invoice_ids.mapped('name'))
        if result_state == 'done' and invoices:
            wizard_ctx = {
                'active_model': 'account.move',
                'active_ids': invoices.ids,
                'active_id': invoices.ids[0]
            }
            register_wizard_vals = {}
            if link_rec.provider_id.journal_id:
                register_wizard_vals['journal_id'] = link_rec.provider_id.journal_id.id
            register_wizard_vals['group_payment'] = True
            register_wizard = request.env['account.payment.register'].sudo().with_context(**wizard_ctx).create(register_wizard_vals)
            payments = register_wizard._create_payments()

            note_body = (
                f"Payment was made for reference {reference}. "
                f"Multiple invoices were paid together. "
                f"Invoices in this payment link: {invoice_names}"
            )
            admin_user = request.env.ref('base.user_admin')
            for invoice in link_rec.invoice_ids:
                invoice.with_user(admin_user).sudo().message_post(
                    body=note_body,
                    message_type='comment',
                    subtype_xmlid='mail.mt_note',
                )
            link_rec.sudo().write({'status': 'paid'})
        elif result_state == 'done':
            link_rec.sudo().write({'status': 'paid'})
        return True

    def _handle_virtual_payment_invoices(self, reference, result_state):
        try:
            payment = request.env['worldpay.virtual.payment'].sudo().search([('reference', '=', reference)], limit=1)
        except Exception:
            return False
        if not payment:
            return False
        target_status = 'paid' if result_state == 'done' else result_state
        if payment.status == 'paid' and result_state in ('cancel', 'error'):
            return True
        if payment.status == target_status:
            return True
        if payment.status == 'paid' and target_status in ('pending', 'cancel', 'error'):
            return True

        if result_state in ('pending', 'cancel', 'error'):
            payment.sudo().write({'status': result_state})

        if payment.sale_order_ids:
            orders = payment.sale_order_ids.filtered(lambda o: o.state in ('draft', 'sent'))
            order_names = ', '.join(payment.sale_order_ids.mapped('name'))
            if result_state == 'done' and orders:
                self._confirm_sale_orders(orders)
                note_body = (
                    f"Payment was made for reference {reference}. "
                    f"Multiple sales orders were paid together. "
                    f"Sales orders in this virtual terminal payment: {order_names}"
                )
                admin_user = request.env.ref('base.user_admin')
                for order in payment.sale_order_ids:
                    order.with_user(admin_user).sudo().message_post(
                        body=note_body,
                        message_type='comment',
                        subtype_xmlid='mail.mt_note',
                    )
                payment.sudo().write({'status': 'paid'})
            elif result_state == 'done':
                payment.sudo().write({'status': 'paid'})
            return True

        invoices = payment.invoice_ids.filtered(lambda m: m.state == 'posted' and m.payment_state != 'paid')
        invoice_names = ', '.join(payment.invoice_ids.mapped('name'))
        if result_state == 'done' and invoices:
            wizard_ctx = {
                'active_model': 'account.move',
                'active_ids': invoices.ids,
                'active_id': invoices.ids[0],
            }
            register_wizard_vals = {}
            if payment.provider_id.journal_id:
                register_wizard_vals['journal_id'] = payment.provider_id.journal_id.id
            register_wizard_vals['group_payment'] = True
            register_wizard = request.env['account.payment.register'].sudo().with_context(**wizard_ctx).create(register_wizard_vals)
            register_wizard._create_payments()

            note_body = (
                f"Payment was made for reference {reference}. "
                f"Multiple invoices were paid together. "
                f"Invoices in this virtual terminal payment: {invoice_names}"
            )
            admin_user = request.env.ref('base.user_admin')
            for invoice in payment.invoice_ids:
                invoice.with_user(admin_user).sudo().message_post(
                    body=note_body,
                    message_type='comment',
                    subtype_xmlid='mail.mt_note',
                )
            payment.sudo().write({'status': 'paid'})
        elif result_state == 'done':
            payment.sudo().write({'status': 'paid'})
        return True

    def _get_link_processing_values(self, link_rec, payload_provider_id=None):
        link_rec = link_rec.sudo()
        if link_rec.sale_order_ids:
            if not link_rec.sale_order_ids.filtered(lambda o: o.state in ('draft', 'sent')):
                return {'error': 'No quotations available for payment.'}
        else:
            invoices = link_rec.invoice_ids.filtered(lambda m: m.state == 'posted' and m.payment_state != 'paid')
            if not invoices:
                return {'error': 'No unpaid invoices available for payment.'}

        provider = None
        if payload_provider_id:
            _logger.info(f"\n Payload Provider ID {payload_provider_id} \n")
            provider = request.env['payment.provider'].sudo().browse(payload_provider_id).exists()
        if not provider:
            _logger.info(f"\n No Provider Found \n")
            provider = link_rec.provider_id.sudo()
        if not provider or provider.code != 'neatworldpay' or provider.state == 'disabled':
            return {'error': 'Worldpay provider is not configured.'}

        return link_rec.neatworldpay_get_processing_values(
            provider=provider,
            result_action=NeatWorldpayController.result_action,
        )

    @http.route('/.well-known/apple-developer-merchantid-domain-association', type='http', auth='public', csrf=False)
    def apple_pay_association(self, **kwargs):
        file_path = "/payment_neatworldpay/static/.well-known/apple-developer-merchantid-domain-association"
        return request.make_response(
            request.env['ir.qweb']._render(file_path),
            [('Content-Type', 'text/plain')]
        )
        
    @http.route(
        "/neatworldpay/wh", type="http", auth="public", csrf=False, methods=["POST", "GET"]
    )
    def neatworldpay_wh(self, **kwargs):
        client_ip = request.httprequest.remote_addr
        _logger.info(f"\n Client IP {client_ip} \n")
        if client_ip not in self._allowed_ips:
            return request.make_json_response({
                'error': 'Forbidden',
                'message': 'Forbidden'
            }, status=403)

        response = request.get_json_data()
        _logger.info(f"\n WH Response {response} \n")
        try:
            if response.get("eventDetails", False):
                event_details = response.get("eventDetails")
                wp_reference = event_details.get("transactionReference", False)
                wp_state = event_details.get("type", False)
                result_state = 'error'
                if wp_state == "sentForAuthorization":
                    result_state = 'pending'
                elif wp_state == "authorized":
                    result_state = "done"
                elif wp_state == "cancelled":
                    result_state = 'cancel'
                if (wp_reference or '').startswith('pl/'):
                    if wp_state in ("sentForAuthorization", "sentForSettlement"):
                        _logger.info(f"\n Ignoring {wp_state} for payment link multi payment {wp_reference} \n")
                        return request.make_json_response({
                            'error': 'OK',
                            'message': 'OK'
                        }, status=200)
                    link_rec = request.env['worldpay.payment.link'].sudo().search([('reference', '=', wp_reference)], limit=1)
                    if link_rec and link_rec.status == 'paid' and wp_state == "authorized":
                        _logger.info(f"\n Link already paid and received authorized again {wp_reference} \n")
                        return request.make_json_response({
                            'error': 'OK',
                            'message': 'OK'
                        }, status=200)
                    if wp_state == "authorized":
                        count = 0
                        while count < 30:
                            if not link_rec or link_rec.status in ('pending', 'cancel', 'error'):
                                _logger.info(f"\n Link Record not found or status is {(link_rec.status if link_rec else 'not_found')} {wp_reference} \n")
                                break
                            _logger.info(f"\n Link Record found and status is {(link_rec.status if link_rec else 'not_found')} {wp_reference} \n")
                            time.sleep(1)
                            request.env.cr.commit()
                            link_rec = request.env['worldpay.payment.link'].sudo().search([('reference', '=', wp_reference)], limit=1)
                            count += 1
                    if link_rec and link_rec.status == 'paid' and result_state in ('cancel', 'error'):
                        if link_rec.sale_order_ids:
                            self._schedule_multi_order_failure_activity(
                                link_rec.sale_order_ids,
                                wp_reference,
                                link_rec.provider_id.neatworldpay_fallback_user_id
                            )
                        else:
                            self._schedule_multi_invoice_failure_activity(
                                link_rec.invoice_ids,
                                wp_reference,
                                link_rec.provider_id.neatworldpay_fallback_user_id
                            )
                        return request.make_json_response({
                            'error': 'OK',
                            'message': 'OK'
                        }, status=200)
                    _logger.info(f"\n Link Record not found or status is {(link_rec.status if link_rec else 'not_found')} {wp_reference} \n")
                    if not link_rec or link_rec.status in ('paid', 'cancel', 'error'):
                        _logger.info(f"\n Link Record not found or status is {(link_rec.status if link_rec else 'not_found')} {wp_reference} \n")
                        return request.make_json_response({
                            'error': 'OK',
                            'message': 'OK'
                        }, status=200)
                    self._handle_guid_link_invoices(wp_reference, result_state)
                    return request.make_json_response({
                        'error': 'OK',
                        'message': 'OK'
                    }, status=200)
                if self._is_virtual_payment_reference(wp_reference):
                    if wp_state in ("sentForAuthorization", "sentForSettlement"):
                        _logger.info(f"\n Ignoring {wp_state} for VT multi payment {wp_reference} \n")
                        return request.make_json_response({
                            'error': 'OK',
                            'message': 'OK'
                        }, status=200)
                    virtual_payment = request.env['worldpay.virtual.payment'].sudo().search([('reference', '=', wp_reference)], limit=1)
                    if virtual_payment and virtual_payment.status == 'paid' and wp_state == "authorized":
                        _logger.info(f"\n Virtual payment already paid and received authorized again {wp_reference} \n")
                        return request.make_json_response({
                            'error': 'OK',
                            'message': 'OK'
                        }, status=200)
                    if wp_state == "authorized":
                        count = 0
                        while count < 30:
                            if not virtual_payment or virtual_payment.status in ('pending', 'cancel', 'error'):
                                _logger.info(f"\n Virtual Payment not found or status is {(virtual_payment.status if virtual_payment else 'not_found')} {wp_reference} \n")
                                break
                            _logger.info(f"\n Virtual Payment found and status is {(virtual_payment.status if virtual_payment else 'not_found')} {wp_reference} \n")
                            time.sleep(1)
                            request.env.cr.commit()
                            virtual_payment = request.env['worldpay.virtual.payment'].sudo().search([('reference', '=', wp_reference)], limit=1)
                            count += 1
                    if virtual_payment and virtual_payment.status == 'paid' and result_state in ('cancel', 'error'):
                        if virtual_payment.sale_order_ids:
                            self._schedule_multi_order_failure_activity(
                                virtual_payment.sale_order_ids,
                                wp_reference,
                                virtual_payment.provider_id.neatworldpay_fallback_user_id
                            )
                        else:
                            self._schedule_multi_invoice_failure_activity(
                                virtual_payment.invoice_ids,
                                wp_reference,
                                virtual_payment.provider_id.neatworldpay_fallback_user_id
                            )
                        return request.make_json_response({
                            'error': 'OK',
                            'message': 'OK'
                        }, status=200)
                    _logger.info(f"\n Virtual Payment not found or status is {(virtual_payment.status if virtual_payment else 'not_found')} {wp_reference} \n")
                    if not virtual_payment or virtual_payment.status in ('paid', 'cancel', 'error'):
                        _logger.info(f"\n Virtual Payment not found or status is {(virtual_payment.status if virtual_payment else 'not_found')} {wp_reference} \n")
                        return request.make_json_response({
                            'error': 'OK',
                            'message': 'OK'
                        }, status=200)
                    self._handle_virtual_payment_invoices(wp_reference, result_state)
                    return request.make_json_response({
                        'error': 'OK',
                        'message': 'OK'
                    }, status=200)


                res = (
                    request.env["payment.transaction"]
                    .sudo()
                    .search([
                        ("reference", "=", event_details.get("transactionReference", False)),
                        ("provider_code", "in", ["neatworldpayvt", "neatworldpay"]),
                        ("state", "not in", ["cancel", "error"])
                    ], limit=1)
                )

                if res:
                    state = event_details.get("type", False)
                    tokenization = event_details.get("tokenPaymentInstrument", False)
                    if state and state != "sentForAuthorization" and state != "sentForSettlement":
                        if state == "authorized":
                            count = 0
                            _logger.info(f"\n WH State is Authorized {res.reference} \n")
                            while count < 30:
                                if not res or res.state == "done":
                                    _logger.info(f"\n Transaction was finished while waiting for pending status {res.reference} \n")
                                    return request.make_json_response({
                                        'error': 'OK',
                                        'message': 'OK'
                                    }, status=200)

                                _logger.info(f"\n Current RES State is {res.state} {res.reference} \n")
                                if res.state == "pending":
                                    break

                                time.sleep(1)
                                request.env.cr.commit()
                                res = (
                                    request.env["payment.transaction"]
                                    .sudo()
                                    .search([
                                        ("reference", "=", event_details.get("transactionReference", False)),
                                        ("provider_code", "in", ["neatworldpayvt", "neatworldpay"]),
                                        ("state", "not in", ["done", "cancel", "error"])
                                    ], limit=1)
                                )

                                count+=1

                        if state == "sentForAuthorization":
                            state = 'pending'
                        elif state == "authorized":
                            state = "done"
                        elif state == "cancelled":
                            state = 'cancel'
                        else:
                            state = 'error'
                        if res.state == "done" and (state == 'cancel' or state == 'error'):
                            sale_order_ref = res.reference.split("-")[0]
                            _logger.info(f"\n Transaction Cancelled after done {sale_order_ref} \n")
                            target_record = request.env["sale.order"].sudo().search([("name", "=", sale_order_ref)], limit=1)
                            record_label = 'sale order'
                            if not target_record:
                                target_record = (
                                    request.env["account.move"]
                                    .sudo()
                                    .search([
                                        '|',
                                        ('name', '=', sale_order_ref),
                                        ('invoice_origin', '=', sale_order_ref)
                                    ], limit=1)
                                )
                                record_label = 'invoice' if target_record else None
                            if target_record:
                                _logger.info(f"\n {record_label.title()} Found for cancelled transaction creating activity {sale_order_ref} {target_record} \n")
                                user_id = None
                                if target_record.user_id:
                                    user_id = target_record.user_id.id
                                elif res.provider_id.neatworldpay_fallback_user_id:
                                    user_id = int(res.provider_id.neatworldpay_fallback_user_id)
                                target_record.activity_schedule(
                                    act_type_xmlid='mail.mail_activity_data_todo',
                                    user_id=user_id,
                                    date_deadline=fields.Date.today(),
                                    summary="Payment Failed - Action Required",
                                    note=f"The payment failed after initial confirmation {res.reference}. Please review and take action."
                                )
                            return request.make_json_response({
                                'error': 'OK',
                                'message': 'OK'
                            }, status=200)

                        data = {
                            'reference': event_details.get("transactionReference", False),
                            'result_state': state
                        }
                        res.sudo()._handle_notification_data(
                            "neatworldpay", data
                        )
                    elif not state and tokenization:
                        token = tokenization.get("href", False)
                        expiry = event_details.get("tokenExpiryDateTime", False)
                        payment_details = event_details.get("paymentInstrument", False)
                        card_number = ""
                        if payment_details:
                            card_number = payment_details.get("cardNumber", False)
                            card_number = card_number[-4:]
                        _logger.info(f"\n Tokenization Entered token: {token} expiry: {expiry} \n")
                        if token and expiry:
                            expiry_date = datetime.strptime(expiry, "%Y-%m-%dT%H:%M:%SZ")
                            res.sudo().neat_worldpay_save_token(token, expiry_date, card_number)
            else:
                return request.make_json_response({
                    'error': 'Bad Request',
                    'message': 'Bad Request'
                }, status=400)
        except ValidationError:
            return request.make_json_response({
                'error': 'Bad Request',
                'message': 'Bad Request'
            }, status=400)

        return request.make_json_response({
            'error': 'OK',
            'message': 'OK'
        }, status=200)

    @http.route('/neatworldpay/payment_link/<string:payload>', type='http', auth='public', website=True, csrf=False)
    def payment_link_page(self, payload, **kwargs):
        data = self._parse_link_payload(payload)
        _logger.info(f"\n Data {data} \n")
        if not data:
            return request.not_found()

        link_rec = request.env['worldpay.payment.link'].sudo().browse(data.get('link_id')).exists()
        if not link_rec or link_rec.reference != data.get('reference'):
            return request.not_found()

        sale_orders = link_rec.sale_order_ids
        order_pay_lines = []
        if sale_orders:
            currency_symbol = sale_orders[:1].currency_id.symbol if sale_orders else ''
            for order in sale_orders:
                g = getattr(order, 'get_portal_url', None)
                portal_url = g() if callable(g) else None
                order_pay_lines.append({
                    'name': order.name,
                    'amount': order.amount_total,
                    'portal_url': portal_url or ('/web#id=%s&model=sale.order&view_type=form' % order.id),
                })
            amount_total = sum(order['amount'] for order in order_pay_lines)
            link_is_paid = all(o.state not in ('draft', 'sent') for o in sale_orders)
            invoices = request.env['account.move']
        else:
            invoices = link_rec.invoice_ids.filtered(lambda m: m.state == 'posted')
            amount_total = sum(invoices.mapped('amount_total'))
            currency_symbol = invoices[:1].currency_id.symbol if invoices else ''
            link_is_paid = bool(invoices) and all(inv.payment_state == 'paid' for inv in invoices)
        if link_is_paid and link_rec.status != 'paid':
            link_rec.sudo().write({'status': 'paid'})
        processing_values = self._get_link_processing_values(
            link_rec, payload_provider_id=data.get('provider_id')
        ) if not link_is_paid else {}
        values = {
            'invoices': invoices,
            'sale_orders': sale_orders,
            'order_pay_lines': order_pay_lines,
            'amount_total': amount_total,
            'currency_symbol': currency_symbol,
            'payload': payload,
            'reference': link_rec.reference,
            'link_is_paid': link_is_paid,
            'status': kwargs.get('status'),
            'link_status': link_rec.status,
            'payment_url': processing_values.get('payment_url'),
            'neatworldpay_use_iframe': processing_values.get('neatworldpay_use_iframe'),
            'payment_error': processing_values.get('error'),
        }
        return request.render('payment_neatworldpay.worldpay_payment_link_page', values)


    @http.route(
        result_action + "/<string:status>/<string:transaction_key>",
        type="http",
        auth="public",
        csrf=False,
        save_session=False,
    )
    def worldpay_result(self, status, transaction_key, **kwargs):
        _logger.info(f"\n Status {status} \n")
        _logger.info(f"\n Redirect Path {request.httprequest.path} \n")
        _logger.info(f"\n Kwargs {kwargs} \n")
        result_reference = kwargs.get("reference", False)
        if self._is_guid_reference(result_reference):
            link_rec = request.env['worldpay.payment.link'].sudo().search([('reference', '=', result_reference)], limit=1)
            if status == 'success':
                if not link_rec or not link_rec.neatworldpay_validation_hash or not link_rec.neatworldpay_validate_transaction_key(transaction_key):
                    return request.redirect("/payment/status")
            elif status == 'failure':
                if not link_rec or not link_rec.neatworldpay_failure_validation_hash or not link_rec.neatworldpay_validate_failure_transaction_key(transaction_key):
                    return request.redirect("/payment/status")
            result_state = 'cancel'
            if status == 'failure':
                result_state = 'error'
            elif status == 'success':
                result_state = 'done'
            elif status == 'pending':
                result_state = 'pending'
            else:
                result_state = 'cancel'
            self._handle_guid_link_invoices(result_reference, result_state)
            if link_rec:
                payload = self._build_link_payload(link_rec)
                return request.redirect(f"/neatworldpay/payment_link/{payload}?status={status}")
            return request.redirect("/payment/status")

        res = (
        request.env["payment.transaction"]
            .sudo()
            .search([
                ("reference", "=", kwargs.get("reference", False)),
                ("provider_code", "=", "neatworldpay"),
                ("state", "in", ["draft", "pending", "done"])
            ], limit=1)
        )
        if res:
            if status == 'success':
                if not res.neatworldpay_validation_hash or not res.neatworldpay_validate_transaction_key(transaction_key):
                    return request.redirect("/payment/status")
            elif status == 'failure':
                if not res.neatworldpay_failure_validation_hash or not res.neatworldpay_validate_failure_transaction_key(transaction_key):
                    return request.redirect("/payment/status")
            if res.state == "done" and (status == "failure" or status == "cancel"):
                sale_order_ref = res.reference.split("-")[0]
                _logger.info(f"\n Transaction Cancelled after done {sale_order_ref} \n")
                target_record = request.env["sale.order"].sudo().search([("name", "=", sale_order_ref)], limit=1)
                record_label = 'sale order'
                if not target_record:
                    target_record = (
                        request.env["account.move"]
                        .sudo()
                        .search([
                            '|',
                            ('name', '=', sale_order_ref),
                            ('invoice_origin', '=', sale_order_ref)
                        ], limit=1)
                    )
                    record_label = 'invoice' if target_record else None
                if target_record:
                    _logger.info(f"\n {record_label.title()} Found for cancelled transaction creating activity {sale_order_ref} {target_record} \n")
                    user_id = None
                    if target_record.user_id:
                        user_id = target_record.user_id.id
                    elif res.provider_id.neatworldpay_fallback_user_id:
                        user_id = int(res.provider_id.neatworldpay_fallback_user_id)
                    target_record.activity_schedule(
                        act_type_xmlid='mail.mail_activity_data_todo',
                        user_id=user_id,
                        date_deadline=fields.Date.today(),
                        summary="Payment Failed - Action Required",
                        note=f"The payment failed after initial confirmation {res.reference}. Please review and take action."
                    )
                return request.redirect("/payment/status")
                
            result_state = 'cancel'
            if status == 'failure':
                result_state = 'error'
            elif status == 'success':
                result_state = 'done'
            elif status == 'pending':
                result_state = 'pending'

            data = {
                'reference': kwargs.get("reference", False),
                'result_state': result_state
            }
            try:
                res.sudo()._handle_notification_data(
                    "neatworldpay", data
                )
            except Exception as e:
                _logger.error(f"Error handling notification data for transaction {res.reference}: {e}")

        return request.redirect("/payment/status")
