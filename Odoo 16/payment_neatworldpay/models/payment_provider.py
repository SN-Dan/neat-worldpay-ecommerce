# Original Author: Daniel Stoynev
# Copyright (c) 2025 SNS Software Ltd. All rights reserved.
# This module extends Odoo's payment framework.
# Odoo is a trademark of Odoo S.A.

import json
import logging
from datetime import timedelta

import re
import requests

from odoo.addons.payment_neatworldpay import const
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from odoo.addons.payment import utils as payment_utils

_logger = logging.getLogger(__name__)


class PaymentProvider(models.Model):
    _inherit = 'payment.provider'
    code = fields.Selection(
        selection_add=[('neatworldpay', "WorldPay")], ondelete={'neatworldpay': 'set default'})
    neatworldpay_entity = fields.Char(
        string="Entity",
        help="Worldpay Entity",
        required_if_provider='neatworldpay', groups='base.group_system')
    neatworldpay_username = fields.Char(
        string="Username", help="Worldpay username", required_if_provider='neatworldpay',
        groups='base.group_system')
    neatworldpay_password = fields.Char(
        string="Password", help="Worldpay password",
        required_if_provider='neatworldpay')
    neatworldpay_activation_code = fields.Char(
        string="Activation Code", help="Contact us to receive a free activation code.")
    neatworldpay_cached_code = fields.Char(
        string="Cached Code", help="Cached Code")
    neatworldpay_cached_code_checked_at = fields.Datetime(
        string="Cached Code Last Check",
        help="When the license cache was last successfully refreshed or checked.",
        copy=False,
    )
    neatworldpay_use_iframe = fields.Boolean(string="Use iFrame", help="iFrame allows you to process the payment on your Odoo web page instead of being redirected to a Worldpay website. It provides a more seamless user experience.", default=True)
    neatworldpay_reset_code = fields.Boolean(string="Update Module Cache", help="If set to true it will update the module cache", default=False)
    
    def _default_neatworldpay_connection_url(self):
        """Set the default connection URL to the company's website URL."""
        return self.env.company.website or ""

    neatworldpay_connection_url = fields.Char(
        string="Odoo Connection URL",
        default=_default_neatworldpay_connection_url,
        help="Odoo URL used for payment communications",
        required_if_provider='neatworldpay',
        groups='base.group_system'
    )
    
    @api.model
    def _get_all_users(self):
        """Fetch all users and return them as selection options."""
        users = self.env['res.users'].search([])  # Get all users
        return [(str(user.id), user.name) for user in users]  # Store ID as string, show name

    neatworldpay_fallback_user_id = fields.Selection(
        selection=_get_all_users,
        string='Fallback Failure User',
        help='Select a user who will receive an activity if a transaction fails for a sale order that does not have a salesperson.'
    )


    def neatworldpay_get_code(self, activation_code):
        """ Get code. """
        try:
            headers = {
                "Referer": self.company_id.website,
                "Authorization": activation_code
            }
            response = requests.get("https://api.sns-software.com/api/AcquirerLicense/code?version=v5-16", headers=headers, timeout=10)
            
            if response.status_code == 200:
                return response.text
                
            else:
                _logger.error(f"Failed to fetch activation code: {response.status_code} - {response.text}")
        except requests.RequestException as e:
            _logger.error(f"Request error: {e}")
        
        return None


    def neatworldpay_get_exec_code(self):
        """Return cached license exec code, with at-most-once-per-24h OTA refresh.

        Runs entirely in the current request thread (Odoo.sh-safe).
        If a cache already exists it is used for this request even when a refresh
        is attempted. The cache is updated only on a successful API response.
        """
        self.ensure_one()
        cached = self.neatworldpay_cached_code
        now = fields.Datetime.now()
        checked_at = self.neatworldpay_cached_code_checked_at
        is_stale = not checked_at or checked_at < now - timedelta(hours=24)
        activation = self.neatworldpay_activation_code

        if cached and not is_stale:
            return cached

        if not activation:
            return cached or None

        new_code = None
        try:
            new_code = self.neatworldpay_get_code(activation)
        except ValidationError:
            if not cached:
                raise
            _logger.warning(
                "%s OTA cache refresh skipped due to validation error; using existing cache.",
                "neatworldpay",
            )
        except Exception:
            if not cached:
                raise
            _logger.exception(
                "%s OTA cache refresh failed; using existing cache.",
                "neatworldpay",
            )

        if new_code:
            self.write({
                "neatworldpay_cached_code": new_code,
                "neatworldpay_cached_code_checked_at": now,
            })
            return new_code

        if cached:
            # Failed refresh: keep cache, stamp check time so we retry in 24h.
            self.write({"neatworldpay_cached_code_checked_at": now})
            return cached
        return None


    @api.model
    def create(self, vals):
        # Check if 'code' is 'neatworldpay' and activation code is being provided or changed
        _logger.info(f"neatworldpay_activation_code {vals.get('neatworldpay_activation_code')}")
        if vals.get('neatworldpay_activation_code'):
            _logger.info(f"old neatworldpay_activation_code {self.neatworldpay_activation_code}")
            if vals.get('neatworldpay_activation_code') != self.neatworldpay_activation_code or vals.get('neatworldpay_reset_code'):
                _logger.info(f"Before code")
                vals['neatworldpay_reset_code'] = False
                code = self.neatworldpay_get_code(vals['neatworldpay_activation_code'])
                _logger.info(f"Code: {code != None}")
                if code:
                    vals['neatworldpay_cached_code'] = code
                    vals['neatworldpay_cached_code_checked_at'] = fields.Datetime.now()
                else:
                    _logger.info(f"Raised error for code")
                    raise ValidationError(_("The activation code is invalid. Please check and try again."))
        elif vals.get('neatworldpay_reset_code'):
            _logger.info(f"Before code")
            vals['neatworldpay_reset_code'] = False
            code = self.neatworldpay_get_code(self.neatworldpay_activation_code)
            _logger.info(f"Code: {code}")
            if code:
                vals['neatworldpay_cached_code'] = code
                vals['neatworldpay_cached_code_checked_at'] = fields.Datetime.now()
            else:
                _logger.info(f"Raised error for code")
                raise ValidationError(_("The activation code is invalid. Please check and try again."))
        return super(PaymentProvider, self).create(vals)

    def write(self, vals):
        # Check if 'code' is 'neatworldpay' and activation code is being updated
        _logger.info(f"neatworldpay_activation_code {vals.get('neatworldpay_activation_code')}")
        if vals.get('neatworldpay_activation_code'):
            _logger.info(f"old neatworldpay_activation_code {self.neatworldpay_activation_code}")
            if vals.get('neatworldpay_activation_code') != self.neatworldpay_activation_code or vals.get('neatworldpay_reset_code'):
                _logger.info(f"Before code")
                vals['neatworldpay_reset_code'] = False
                code = self.neatworldpay_get_code(vals['neatworldpay_activation_code'])
                _logger.info(f"Code: {code}")
                if code:
                    vals['neatworldpay_cached_code'] = code
                    vals['neatworldpay_cached_code_checked_at'] = fields.Datetime.now()
                else:
                    _logger.info(f"Raised error for code")
                    raise ValidationError(_("The activation code is invalid. Please check and try again."))
        elif vals.get('neatworldpay_reset_code'):
            _logger.info(f"Before code")
            vals['neatworldpay_reset_code'] = False
            code = self.neatworldpay_get_code(self.neatworldpay_activation_code)
            _logger.info(f"Code: {code}")
            if code:
                vals['neatworldpay_cached_code'] = code
                vals['neatworldpay_cached_code_checked_at'] = fields.Datetime.now()
            else:
                _logger.info(f"Raised error for code")
                raise ValidationError(_("The activation code is invalid. Please check and try again."))
        return super(PaymentProvider, self).write(vals)

    def _compute_feature_support_fields(self):
        """ Override of `payment` to enable additional features. """
        super()._compute_feature_support_fields()
        self.filtered(lambda p: p.code == 'neatworldpay').update({
            'support_manual_capture': 'partial',
            'support_refund': 'partial',
            'support_tokenization': True,
        })

    def _get_default_payment_method_codes(self):
        """ Override of `payment` to return the default payment method codes. """
        default_codes = super()._get_default_payment_method_codes()
        if self.code != 'stripe':
            return default_codes
        return const.DEFAULT_PAYMENT_METHODS_CODES

