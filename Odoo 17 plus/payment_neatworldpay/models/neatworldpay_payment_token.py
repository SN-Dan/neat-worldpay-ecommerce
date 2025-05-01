# -*- coding: utf-8 -*-
import logging
import uuid
from odoo import api, fields, models, _

_logger = logging.getLogger(__name__)

class NeatWorldpayPaymentToken(models.Model):
    _name = 'neatworldpay.payment.token'
    _description = 'NEAT Worldpay Payment Token'

    token = fields.Text('Token', required=True, readonly=False, store=True)
    provider_id = fields.Integer('Provider ID', required=False, readonly=False, store=True)
    payment_method_id = fields.Integer('Payment Method ID', required=False, readonly=False, store=True)
    partner_id = fields.Integer('Payment Method ID', required=False, readonly=False, store=True)
    expiry_date = fields.Datetime(
        string="Expiry Datetime",
        required=False,
        help="The expiration date and time of the payment token."
    )



