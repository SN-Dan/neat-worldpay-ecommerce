{
    'name': 'Neat Worldpay Online Payments',
    'version': '2.0',
    'category': 'Accounting/Payment Providers',
    'sequence': 350,
    'summary': "Neat Worldpay Integration for online payments.",
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
            'payment_neatworldpay/static/src/**/*',
            'https://payments.worldpay.com/resources/hpp/integrations/embedded/js/hpp-embedded-integration-library.js'
        ],
    },
    'license': 'LGPL-3',
}