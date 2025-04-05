{
    'name': 'Payment Provider: Worldpay',
    'version': '2.0',
    'category': 'Accounting/Payment Providers',
    'sequence': 350,
    'summary': "Worldpay online payments integration by SNS.",
    'description': " ",
    'depends': ['payment'],
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