-- disable stripe payment provider
UPDATE payment_provider
   SET neatworldpay_entity = NULL,
       neatworldpay_connection_url = NULL,
       neatworldpay_username = NULL,
       neatworldpay_password = NULL;