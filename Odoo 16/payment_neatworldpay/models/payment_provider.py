import json
import logging
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
        selection_add=[('neatworldpay', "Neat WorldPay")], ondelete={'neatworldpay': 'set default'})
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
    neatworldpay_use_iframe = fields.Boolean(string="Use iFrame", required_if_provider='neatworldpay', help="iFrame allows you to process the payment on your Odoo web page instead of being redirected to a Worldpay website. It provides a more seamless user experience.", default=True)
    neatworldpay_connection_url = fields.Char(
        string="Odoo Connection URL", default="", help="Odoo URL used for payment connunications", required_if_provider='neatworldpay',
        groups='base.group_system')
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

