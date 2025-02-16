# Part of Odoo. See LICENSE file for full copyright and licensing details.

{
    'name': 'NeatApps Worldpay Integration',
    'version': '2.0',
    'category': 'Accounting/Payment Providers',
    'sequence': 350,
    'summary': "NeatApps Worldpay Integration for online payments.",
    'description': " ",  # Non-empty string to avoid loading the README file.
    'depends': ['payment'],
    'data': [
        'views/payment_provider_views.xml',
        'views/payment_neatworldpay_templates.xml',
        'views/payment_form_templates.xml',  # Only load the SDK on pages with a payment form.

        'data/payment_provider_data.xml'
    ],
    'post_init_hook': 'post_init_hook',
    'uninstall_hook': 'uninstall_hook',
    'assets': {
        'web.assets_frontend': [
            'payment_neatworldpay/static/src/**/*',
        ],
    },
    'license': 'LGPL-3',
}