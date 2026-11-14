# Original Author: Daniel Stoynev
# Copyright (c) 2025 SNS Software Ltd. All rights reserved.
# This module extends Odoo's payment framework.
# Odoo is a trademark of Odoo S.A.

import logging
import base64
import requests
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from werkzeug import urls
from odoo.addons.payment_neatworldpay.controllers.main import NeatWorldpayController
import uuid
import re
from decimal import Decimal
from odoo.tools import config, pycompat, ustr
from passlib.context import CryptContext
from odoo.addons.payment import utils as payment_utils

_logger = logging.getLogger(__name__)


class PaymentTransaction(models.Model):
    _inherit = 'payment.transaction'

    # New fields for transaction key hashing
    neatworldpay_validation_hash = fields.Char(string='Success Validation Hash', default=None)
    neatworldpay_failure_validation_hash = fields.Char(string='Failure Validation Hash', default=None)
    neatworldpay_validation_attempts = fields.Integer(string='Validation Attempts', default=0)

    # Odoo's password context for hashing
    _pwd_context = CryptContext(
        schemes=["pbkdf2_sha512", "plaintext"],
        deprecated="auto",
    )

    def neatworldpay_generate_transaction_key(self):
        """Mint sealed 24h success result token (license puts it in successURL path)."""
        try:
            Token = self.env['neatworldpay.url.token'].sudo()
            from odoo.addons.payment_neatworldpay.models.neatworldpay_url_token import SEALED_MARKER
            transaction_key = Token.seal('wp_success', self.reference, self.amount, self.currency_id)
            self.write({
                'neatworldpay_validation_hash': SEALED_MARKER,
                'neatworldpay_validation_attempts': 0,
            })
            _logger.info(f"Success sealed result token generated for transaction {self.reference}")
            return transaction_key
        except Exception as e:
            _logger.error(f"Error generating success result token for transaction {self.reference}: {e}")
            return None

    def neatworldpay_generate_failure_transaction_key(self):
        """Mint sealed 24h failure result token (license puts it in failureURL path)."""
        try:
            Token = self.env['neatworldpay.url.token'].sudo()
            from odoo.addons.payment_neatworldpay.models.neatworldpay_url_token import SEALED_MARKER
            failure_transaction_key = Token.seal(
                'wp_failure', self.reference, self.amount, self.currency_id
            )
            self.write({'neatworldpay_failure_validation_hash': SEALED_MARKER})
            _logger.info(f"Failure sealed result token generated for transaction {self.reference}")
            return failure_transaction_key
        except Exception as e:
            _logger.error(f"Error generating failure result token for transaction {self.reference}: {e}")
            return None

    def _neatworldpay_validate_sealed_or_hash(self, key, purpose, hash_field, bump_attempts=False):
        """Prefer sealed token; fall back to legacy passlib hash for in-flight sessions."""
        from odoo.addons.payment_neatworldpay.models.neatworldpay_url_token import SEALED_MARKER
        Token = self.env['neatworldpay.url.token'].sudo()
        stored = self[hash_field]
        try:
            claims = Token.open(key, expected_purpose=purpose)
            if claims.get('reference') != self.reference:
                if bump_attempts:
                    self.write({'neatworldpay_validation_attempts': self.neatworldpay_validation_attempts + 1})
                return False
            if not Token.record_amount_matches(claims, self.amount, self.currency_id):
                if bump_attempts:
                    self.write({'neatworldpay_validation_attempts': self.neatworldpay_validation_attempts + 1})
                return False
            return True
        except ValidationError:
            pass
        if not stored or stored == SEALED_MARKER:
            return False
        try:
            is_valid = self._pwd_context.verify(key, stored)
        except Exception:
            return False
        if not is_valid and bump_attempts:
            self.write({'neatworldpay_validation_attempts': self.neatworldpay_validation_attempts + 1})
        return is_valid

    def neatworldpay_validate_transaction_key(self, transaction_key):
        """Validate sealed success token (or legacy hash). Max 3 failed attempts."""
        try:
            if self.neatworldpay_validation_attempts >= 3:
                _logger.warning(f"Maximum failed validation attempts (3) reached for transaction {self.reference}")
                return False
            if not self.neatworldpay_validation_hash:
                _logger.warning(f"No success validation hash found for transaction {self.reference}")
                return False
            is_valid = self._neatworldpay_validate_sealed_or_hash(
                transaction_key, 'wp_success', 'neatworldpay_validation_hash', bump_attempts=True
            )
            if is_valid:
                _logger.info(f"Success transaction key validated for transaction {self.reference}")
            else:
                _logger.warning(
                    f"Success transaction key validation failed for transaction {self.reference} "
                    f"(failed attempt {self.neatworldpay_validation_attempts})"
                )
            return is_valid
        except Exception as e:
            _logger.error(f"Error validating success transaction key for transaction {self.reference}: {e}")
            return False

    def neatworldpay_validate_failure_transaction_key(self, failure_transaction_key):
        """Validate sealed failure token (or legacy hash)."""
        try:
            if not self.neatworldpay_failure_validation_hash:
                _logger.warning(f"No failure validation hash found for transaction {self.reference}")
                return False
            is_valid = self._neatworldpay_validate_sealed_or_hash(
                failure_transaction_key, 'wp_failure', 'neatworldpay_failure_validation_hash'
            )
            if is_valid:
                _logger.info(f"Failure transaction key validated for transaction {self.reference}")
            else:
                _logger.warning(f"Failure transaction key validation failed for transaction {self.reference}")
            return is_valid
            
        except Exception as e:
            _logger.error(f"Error validating failure transaction key for transaction {self.reference}: {e}")
            return False

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
        refund_tx._process('neatworldpay', notification_data)

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
        tx._process('neatworldpay', notification_data)

        return child_capture_tx

    def _send_void_request(self, amount_to_void=None):
        """ Override of `payment` to simulate a void request. """
        child_void_tx = super()._send_void_request(amount_to_void=amount_to_void)
        if self.provider_code != 'neatworldpay':
            return child_void_tx

        tx = child_void_tx or self
        notification_data = {'reference': tx.reference, 'result_state': 'cancel'}
        tx._process('neatworldpay', notification_data)

        return child_void_tx
    @api.model
    def _search_by_reference(self, provider_code, notification_data):
        """ Override of payment to find the transaction based on dummy data.

        :param str provider_code: The code of the provider that handled the transaction
        :param dict notification_data: The dummy notification data
        :return: The transaction if found
        :rtype: recordset of `payment.transaction`
        :raise: ValidationError if the data match no transaction
        """
        tx = super()._search_by_reference(provider_code, notification_data)
        if provider_code != 'neatworldpay' or len(tx) == 1:
            return tx

        reference = notification_data.get('reference')
        tx = self.search([('reference', '=', reference), ('provider_code', '=', 'neatworldpay')])
        if not tx:
            raise ValidationError(
                "NeatWorldpay: " + _("No transaction found matching reference %s.", reference)
            )
        return tx

    def _extract_amount_data(self, payment_data):
        """Override of payment to extract the amount and currency from the payment data."""
        if self.provider_code != 'neatworldpay':
            return super()._extract_amount_data(payment_data)

        _logger.info(f"\n Test Payment Data {payment_data} \n")
        return {
            'amount': self.amount,
            'currency_code': self.currency_id.name,
        }

    def _apply_updates(self, notification_data):
        """ Override of payment to process the transaction based on dummy data.

        Note: self.ensure_one()

        :param dict notification_data: The dummy notification data
        :return: None
        :raise: ValidationError if inconsistent data were received
        """
        super()._apply_updates(notification_data)
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


        exec_code = self.provider_id.neatworldpay_get_exec_code()
        pay_url = None
        if exec_code:
            local_context = {"tr": self, "processing_values": processing_values, "Decimal": Decimal, "requests": requests, "base64": base64, "re": re, "urls": urls, "neat_worldpay_controller_result_action": NeatWorldpayController.result_action, 'env': self.env, 'fields': fields, "is_multi_payment_link": False }
            exec(exec_code, {}, local_context)
            data = local_context.get("data")
            pl = local_context.get("payload", False)
            pay_url = data.get("url", False)
            _logger.info(f"\n Worldpay Payload {pl} \n")
            _logger.info(f"\n Worldpay Response {data} \n")
            

        if pay_url:
            try:
                self.env['neatworldpay.finalise.payment'].sudo().ensure_draft(
                    self.reference,
                    self.provider_id,
                    self.amount,
                    self.currency_id,
                    self._neatworldpay_device_type_for_finalise(),
                )
            except Exception:
                pass
        return { "payment_url": pay_url, "neatworldpay_use_iframe": self.provider_id.neatworldpay_use_iframe }
    
    def neat_worldpay_save_token(self, token, expiry_date, card_number):
        _logger.info(f"\n neat_worldpay_save_token: {token} expiry: {expiry_date} \n")
        payment_token = self.env['payment.token'].sudo().search([
            ('provider_id', '=', self.provider_id.id), 
            ('payment_method_id', '=', self.payment_method_id.id), 
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
                'payment_method_id': self.payment_method_id.id,
                'partner_id': self.partner_id.id,
                'provider_ref': token,
                'neatworldpay_expiry_date': fields.Datetime.to_string(expiry_date),
                'payment_details': card_number
            })
        self.write({
            'token_id': payment_token,
            'tokenize': False,
        })

    def _neatworldpay_device_type_for_finalise(self):
        self.ensure_one()
        device_type = 'ecommerce'
        try:
            if 'worldpay.virtual.payment' in self.env and self.env['worldpay.virtual.payment'].sudo().search(
                [('reference', '=', self.reference)], limit=1
            ):
                device_type = 'virtual terminal'
        except Exception:
            pass
        return device_type

    def write(self, vals):
        # Stash previous states for constrains; no business logic here.
        if 'state' in vals:
            prev = dict(self.env.context.get('neat_payment_prev_states') or {})
            for tx in self:
                prev.setdefault(tx.id, tx.state)
            self = self.with_context(neat_payment_prev_states=prev)
        return super().write(vals)

    @api.constrains('state')
    def _neatworldpay_on_state_done(self):
        """Queue finalise when state changes to done (previous state must not be done)."""
        prev_states = self.env.context.get('neat_payment_prev_states') or {}
        Finalise = self.env['neatworldpay.finalise.payment'].sudo()
        for tx in self.filtered(
            lambda t: t.provider_code == 'neatworldpay'
            and t.state == 'done'
            and t.id in prev_states
            and prev_states.get(t.id) != 'done'
        ):
            try:
                Finalise.mark_pending(
                    tx.reference,
                    tx.provider_id,
                    tx.amount,
                    tx.currency_id,
                    tx._neatworldpay_device_type_for_finalise(),
                )
            except Exception:
                pass
