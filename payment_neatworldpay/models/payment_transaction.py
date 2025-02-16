import logging
import base64
import requests
from odoo import _, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class PaymentTransaction(models.Model):
    _inherit = 'payment.transaction'
    #=== BUSINESS METHODS ===#
    def _process_notification_data(self, notification_data):
        """ Override of `payment` to process the transaction based on Stripe data.

        Note: self.ensure_one()

        :param dict notification_data: The notification data build from information passed to the
                                       return route. Depending on the operation of the transaction,
                                       the entries with the keys 'payment_intent', 'setup_intent'
                                       and 'payment_method' can be populated with their
                                       corresponding Stripe API objects.
        :return: None
        :raise: ValidationError if inconsistent data were received
        """
        _logger.info(f"\n _process_notification_data {notification_data} \n")
        super()._process_notification_data(notification_data)

    def _send_payment_request(self):
        """ Override of payment to send a payment request to Stripe with a confirmed PaymentIntent.

        Note: self.ensure_one()

        :return: None
        :raise: UserError if the transaction is not linked to a token
        """

        _logger.info(f"\n _send_payment_request \n")
        super()._send_payment_request()

    def _send_capture_request(self, amount_to_capture=None):
        """ Override of `payment` to send a capture request to Stripe. """

        child_capture_tx = super()._send_capture_request(amount_to_capture=amount_to_capture)
        _logger.info(f"\n _send_capture_request {amount_to_capture} {child_capture_tx} \n")
        return child_capture_tx

    def _get_tx_from_notification_data(self, provider_code, notification_data):
        """ Override of payment to find the transaction based on Stripe data.

        :param str provider_code: The code of the provider that handled the transaction
        :param dict notification_data: The notification data sent by the provider
        :return: The transaction if found
        :rtype: recordset of `payment.transaction`
        :raise: ValidationError if inconsistent data were received
        :raise: ValidationError if the data match no transaction
        """
        tx = super()._get_tx_from_notification_data(provider_code, notification_data)
        _logger.info(f"\n _get_tx_from_notification_data {provider_code} {notification_data} {tx} \n")
        return tx
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
            "address1": self.partner_id.street,
            "address2": self.partner_id.street2,
            "postalCode": self.partner_zip,
            "city": self.partner_city,
            "state": self.partner_state_id.name,
            "countryCode": self.partner_country_id.code
          },
          "account": {
            "previousSuspiciousActivity": False,
            "email": self.partner_email
          }
        }
        _logger.info(f"\n Request {payload} \n")
        response = requests.post(self.provider_id.neatworldpay_connection_url, json=payload, headers=headers)
        data = response.json()
        _logger.info(f"\n Worldpay Response {data} \n")
        return { "payment_url": data.get("url", False), "test": "test" }
