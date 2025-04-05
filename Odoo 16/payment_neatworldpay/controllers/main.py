import base64
import binascii
import hashlib
import hmac
import logging
import pprint
import time
from odoo.http import request
from odoo import _, http, fields
from odoo.exceptions import ValidationError

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

    @http.route('/.well-known/apple-developer-merchantid-domain-association', type='http', auth='public', csrf=False)
    def apple_pay_association(self, **kwargs):
        file_path = "/your_module_name/static/.well-known/apple-developer-merchantid-domain-association"
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
                res = (
                    request.env["payment.transaction"]
                    .sudo()
                    .search([
                        ("reference", "=", event_details.get("transactionReference", False)),
                        ("provider_code", "=", "neatworldpay"),
                        ("state", "not in", ["cancel", "error"])
                    ], limit=1)
                )

                if res:
                    state = event_details.get("type", False)
                    if state != "sentForAuthorization" and state != "sentForSettlement":
                        if state == "authorized":
                            count = 0
                            _logger.info(f"\n WH State is Authorized {res.reference} \n")
                            while count < 30:
                                time.sleep(1)
                                request.env.cr.commit()
                                res = (
                                    request.env["payment.transaction"]
                                    .sudo()
                                    .search([
                                        ("reference", "=", event_details.get("transactionReference", False)),
                                        ("provider_code", "=", "neatworldpay"),
                                        ("state", "not in", ["done", "cancel", "error"])
                                    ], limit=1)
                                )

                                if not res or res.state == "done":
                                    _logger.info(f"\n Transaction was finished while waiting for pending status {res.reference} \n")
                                    return request.make_json_response({
                                        'error': 'OK',
                                        'message': 'OK'
                                    }, status=200)

                                _logger.info(f"\n Current RES State is {res.state} {res.reference} \n")
                                if res.state == "pending":
                                    break

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
                            sale_order = request.env["sale.order"].sudo().search([("name", "=", sale_order_ref)], limit=1)
                            if sale_order:
                                _logger.info(f"\n Sale Order Found for cancelled transaction creating activity {sale_order_ref} {sale_order} \n")
                                user_id = None
                                if sale_order.user_id:
                                    user_id = sale_order.user_id.id
                                elif res.provider_id.neatworldpay_fallback_user_id:
                                    user_id = int(res.provider_id.neatworldpay_fallback_user_id)
                                
                                sale_order.activity_schedule(
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


    @http.route(
        result_action + "/<string:status>",
        type="http",
        auth="public",
        csrf=False,
        save_session=False,
    )
    def worldpay_result(self, status, **kwargs):
        _logger.info(f"\n Status {status} \n")
        _logger.info(f"\n Redirect Path {request.httprequest.path} \n")
        _logger.info(f"\n Kwargs {kwargs} \n")
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
            if res.state == "done" and (status == "failure" or status == "cancel"):
                sale_order_ref = res.reference.split("-")[0]
                _logger.info(f"\n Transaction Cancelled after done {sale_order_ref} \n")
                sale_order = request.env["sale.order"].sudo().search([("name", "=", sale_order_ref)], limit=1)
                if sale_order:
                    _logger.info(f"\n Sale Order Found for cancelled transaction creating activity {sale_order_ref} {sale_order} \n")
                    user_id = None
                    if sale_order.user_id:
                        user_id = sale_order.user_id.id
                    elif res.provider_id.neatworldpay_fallback_user_id:
                        user_id = int(res.provider_id.neatworldpay_fallback_user_id)
                    
                    sale_order.activity_schedule(
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
            elif status == 'success' or status == 'pending':
                result_state = 'pending'
            data = {
                'reference': kwargs.get("reference", False),
                'result_state': result_state
            }
            res.sudo()._handle_notification_data(
                "neatworldpay", data
            )

        return request.redirect("/payment/status")
