import logging
import base64
import requests
from odoo import _, fields, models
from odoo.exceptions import UserError, ValidationError
from werkzeug import urls
from odoo.addons.payment_neatworldpay.controllers.main import NeatWorldpayController
import uuid

_logger = logging.getLogger(__name__)


class PaymentTransaction(models.Model):
    _inherit = 'payment.transaction'


    #=== BUSINESS METHODS ===#
    def _send_payment_request(self):
        """ Override of payment to simulate a payment request.

        Note: self.ensure_one()

        :return: None
        """
        super()._send_payment_request()
        if self.provider_code != 'neatworldpay':
            return

        if not self.token_id:
            raise UserError("NEATWorldpay: " + _("The transaction is not linked to a token."))

        state = self.token_id.state
        notification_data = {'reference': self.reference, 'result_state': state}
        self._handle_notification_data('neatworldpay', notification_data)

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
        elif state == "cancel":
            self._set_canceled()
        elif state == "error":
            self._set_error("Received an error from Worldpay")


    def _get_specific_processing_values(self, processing_values):
        """Injects Worldpay-specific values into the payment form."""
        self.ensure_one()
        if self.provider_code != "neatworldpay":
            return super()._get_specific_processing_values(processing_values)

        basicTokenUnencoded = self.provider_id.neatworldpay_username + ":" + self.provider_id.neatworldpay_password
        basicToken = base64.b64encode(basicTokenUnencoded.encode("utf-8")).decode()

        headers = {
            "Authorization": "Basic " + basicToken,
            "Content-Type": "application/vnd.worldpay.payment_pages-v1.hal+json",
            "Accept": "application/vnd.worldpay.payment_pages-v1.hal+json",
            "User-Agent": "neatapps"
        }

        odoo_url = self.provider_id.neatworldpay_connection_url
        result_url = str(urls.url_join(odoo_url, NeatWorldpayController.result_action)) + "?ref=" + processing_values.get("reference") 

        payload = {
            "transactionReference": processing_values.get("reference"),
            "merchant": {
                "entity": self.provider_id.neatworldpay_entity
            },
            "narrative": {
                "line1": self.company_id.name
            },
            "value": {
                "currency": self.currency_id.name,
                "amount": self.amount
            },
            "billingAddressName": self.partner_address,
            "billingAddress": {
                "address1": self.partner_id.street or "",
                "address2": self.partner_id.street2 or "",
                "postalCode": self.partner_zip or "",
                "city": self.partner_city or "",
                "state": self.partner_state_id.name or "",
                "countryCode": self.partner_country_id.code or ""
            },
            "resultURLs": {
                "successURL": result_url + "&status=success",
                "pendingURL": result_url + "&status=pending",
                "failureURL": result_url + "&status=failure",
                "errorURL": result_url + "&status=error",
                "cancelURL": result_url + "&status=cancel",
                "expiryURL": result_url + "&status=expiry",
            },
            "expiry": "2592000"
        }
        _logger.info(f"\n Request {payload} \n")
        _logger.info(f"\n Worldpay URL {self.provider_id.neatworldpay_connection_url} \n")
        worldpay_url = "https://try.access.worldpay.com/payment_pages"
        if self.provider_id.state == "enabled":
            worldpay_url = "https://access.worldpay.com/payment_pages"
        response = requests.post(worldpay_url, json=payload, headers=headers)
        data = response.json()
        _logger.info(f"\n Worldpay Response {data} \n")
        return { "payment_url": data.get("url", False), "neatworldpay_use_iframe": self.provider_id.neatworldpay_use_iframe }
