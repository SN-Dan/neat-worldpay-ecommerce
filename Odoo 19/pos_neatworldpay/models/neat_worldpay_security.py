# Original Author: Daniel Stoynev
# Copyright (c) 2025 SNS Software Ltd. All rights reserved.
# This module extends Odoo's payment framework.
# Odoo is a trademark of Odoo S.A.
import logging
from odoo import fields, models, api, _
from cryptography.fernet import Fernet

_logger = logging.getLogger(__name__)

class PosPaymentMethod(models.Model):
    _name = 'neat.worldpay.security'
    _description = 'NEAT Worldpay Security'

    neat_worldpay_secret_key = fields.Char('Secret Key')

    def create(self, values_list):        
        for values in values_list:
            fernet_key = Fernet.generate_key()
            fernet_key_string = fernet_key.decode()
            values['neat_worldpay_secret_key'] = fernet_key_string
        
        return super(PosPaymentMethod, self).create(values_list)


    def write(self, values):
        if 'neat_worldpay_secret_key' in values:
            del values['neat_worldpay_secret_key']
        return super(PosPaymentMethod, self).write(values)

