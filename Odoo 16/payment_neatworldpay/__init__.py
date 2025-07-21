# -*- coding: utf-8 -*-
# Original Author: Daniel Stoynev
# Copyright (c) 2025 SNS Software Ltd. All rights reserved.
# This module extends Odoo's payment framework.
# Odoo is a trademark of Odoo S.A.
from . import models
from . import controllers

from odoo.addons.payment import setup_provider, reset_payment_provider


def post_init_hook(cr, registry):
    setup_provider(cr, registry, 'neatworldpay')


def uninstall_hook(cr, registry):
    reset_payment_provider(cr, registry, 'neatworldpay')