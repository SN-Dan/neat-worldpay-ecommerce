# Part of Odoo. See LICENSE file for full copyright and licensing details.

import logging
import pprint

from odoo import _, fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class PaymentToken(models.Model):
    _inherit = 'payment.token'

    neatworldpay_expiry_date = fields.Datetime(
        string="Expiry Datetime",
        required=False,
        help="The expiration date and time of the payment token."
    )