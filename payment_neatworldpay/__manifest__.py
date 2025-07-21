{
    'name': 'Payment Provider: Worldpay',
    'version': '2.0',
    'category': 'Accounting/Payment Providers',
    'sequence': 350,
    'summary': "Worldpay online payments integration by SNS.",
    'description': """
        Worldpay online payments integration for Odoo.
        Original Author: Daniel Stoynev
        
        This module extends Odoo's payment framework.
        Odoo is a trademark of Odoo S.A.
        
        LICENSE: This module is licensed under LGPL-3.
        See LICENSE file for complete terms.
    """,
    'author': 'SNS Software',
    'maintainer': 'SNS Software',
    'website': 'https://www.sns-software.com',
    'depends': ['payment'],
    'images': ['static/description/main.gif'],
    'data': [
        'views/payment_provider_views.xml',
        'views/payment_neatworldpay_templates.xml',
        'views/payment_form_templates.xml',

        'data/payment_provider_data.xml'
    ],
    'post_init_hook': 'post_init_hook',
    'uninstall_hook': 'uninstall_hook',
    'assets': {
        'web.assets_frontend': [
            'payment_neatworldpay/static/src/js/payment_form.js'
        ],
        'web.assets_backend': [
            'payment_neatworldpay/static/src/css/neatworldpay.css',
            'payment_neatworldpay/static/src/js/neatworldpay.js',
        ]
    },
    'license': 'LGPL-3',
}