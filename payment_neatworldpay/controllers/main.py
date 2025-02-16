# Part of Odoo. See LICENSE file for full copyright and licensing details.

import base64
import binascii
import hashlib
import hmac
import logging
import pprint
from odoo.http import request

from odoo import _, http

_logger = logging.getLogger(__name__)


class NeatWorldpayController(http.Controller):

    _simulation_url = '/payment/demo/simulate_payment'

    @http.route(_simulation_url, type='json', auth='public')
    def demo_simulate_payment(self, **data):
        """ Simulate the response of a payment request.

        :param dict data: The simulated notification data.
        :return: None
        """
        request.env['payment.transaction'].sudo()._handle_notification_data('demo', data)
