# Original Author: Daniel Stoynev
# Copyright (c) 2025 SNS Software Ltd. All rights reserved.
# This module extends Odoo's payment framework.
# Odoo is a trademark of Odoo S.A.
from odoo import models


class PosSession(models.Model):
    _inherit = 'pos.session'

    def _loader_params_pos_payment_method(self):
        result = super()._loader_params_pos_payment_method()
        result['search_params']['fields'].append('neat_worldpay_terminal_device_code')
        result['search_params']['fields'].append('neat_worldpay_is_mobile')
        result['search_params']['fields'].append('neat_worldpay_is_terminal_printer_communication_allowed')
        result['search_params']['fields'].append('neat_worldpay_is_desktop_mode')
        result['search_params']['fields'].append('neat_worldpay_is_local_ws_server')
        result['search_params']['fields'].append('neat_worldpay_ws_url')
        result['search_params']['fields'].append('neat_worldpay_device_type')
        return result