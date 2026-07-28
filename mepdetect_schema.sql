     table_name      |       column_name        |          data_type          | character_maximum_length |                 column_default                  | is_nullable 
---------------------+--------------------------+-----------------------------+--------------------------+-------------------------------------------------+-------------
 contact_messages    | id                       | integer                     |                          | nextval('contact_messages_id_seq'::regclass)    | NO
 contact_messages    | name                     | character varying           |                          |                                                 | YES
 contact_messages    | email                    | character varying           |                          |                                                 | YES
 contact_messages    | company                  | character varying           |                          |                                                 | YES
 contact_messages    | message                  | character varying           |                          |                                                 | YES
 contact_messages    | status                   | character varying           |                          |                                                 | YES
 contact_messages    | created_at               | timestamp with time zone    |                          | now()                                           | YES
 contact_messages    | user_id                  | integer                     |                          |                                                 | YES
 contact_messages    | subject                  | character varying           |                      500 |                                                 | YES
 contact_messages    | priority                 | character varying           |                       20 | 'normal'::character varying                     | YES
 contact_messages    | admin_reply              | text                        |                          |                                                 | YES
 contact_messages    | replied_by               | integer                     |                          |                                                 | YES
 contact_messages    | replied_at               | timestamp without time zone |                          |                                                 | YES
 contact_messages    | updated_at               | timestamp without time zone |                          | now()                                           | YES
 custom_models       | id                       | integer                     |                          | nextval('custom_models_id_seq'::regclass)       | NO
 custom_models       | user_id                  | integer                     |                          |                                                 | YES
 custom_models       | model_name               | character varying           |                          |                                                 | YES
 custom_models       | model_path               | character varying           |                          |                                                 | YES
 custom_models       | class_names              | json                        |                          |                                                 | YES
 custom_models       | is_active                | boolean                     |                          |                                                 | YES
 custom_models       | created_at               | timestamp with time zone    |                          | now()                                           | YES
 email_logs          | id                       | integer                     |                          | nextval('email_logs_id_seq'::regclass)          | NO
 email_logs          | user_id                  | integer                     |                          |                                                 | YES
 email_logs          | to_email                 | character varying           |                      255 |                                                 | NO
 email_logs          | subject                  | character varying           |                      500 |                                                 | YES
 email_logs          | email_type               | character varying           |                       50 |                                                 | YES
 email_logs          | status                   | character varying           |                       50 | 'pending'::character varying                    | YES
 email_logs          | error_message            | text                        |                          |                                                 | YES
 email_logs          | sent_at                  | timestamp without time zone |                          |                                                 | YES
 email_logs          | created_at               | timestamp without time zone |                          | now()                                           | YES
 email_verifications | id                       | integer                     |                          | nextval('email_verifications_id_seq'::regclass) | NO
 email_verifications | user_id                  | integer                     |                          |                                                 | YES
 email_verifications | token                    | character varying           |                      100 |                                                 | NO
 email_verifications | verified                 | boolean                     |                          | false                                           | YES
 email_verifications | verified_at              | timestamp without time zone |                          |                                                 | YES
 email_verifications | expires_at               | timestamp without time zone |                          |                                                 | NO
 email_verifications | created_at               | timestamp without time zone |                          | now()                                           | YES
 models              | id                       | integer                     |                          | nextval('models_id_seq'::regclass)              | NO
 models              | name                     | character varying           |                      100 |                                                 | NO
 models              | display_name             | character varying           |                      200 |                                                 | NO
 models              | description              | text                        |                          |                                                 | YES
 models              | file_path                | character varying           |                      500 |                                                 | NO
 models              | file_size                | bigint                      |                          |                                                 | YES
 models              | version                  | character varying           |                       50 |                                                 | YES
 models              | model_type               | character varying           |                       50 | 'yolo11'::character varying                     | YES
 models              | is_default               | boolean                     |                          | false                                           | YES
 models              | is_active                | boolean                     |                          | true                                            | YES
 models              | is_public                | boolean                     |                          | false                                           | YES
 models              | uploaded_by              | integer                     |                          |                                                 | YES
 models              | accuracy_metrics         | jsonb                       |                          |                                                 | YES
 models              | supported_classes        | jsonb                       |                          |                                                 | YES
 models              | training_data_info       | text                        |                          |                                                 | YES
 models              | created_at               | timestamp without time zone |                          | now()                                           | YES
 models              | updated_at               | timestamp without time zone |                          | now()                                           | YES
 orders              | id                       | integer                     |                          | nextval('orders_id_seq'::regclass)              | NO
 orders              | user_id                  | integer                     |                          |                                                 | YES
 orders              | order_number             | character varying           |                          |                                                 | YES
 orders              | description              | character varying           |                          |                                                 | YES
 orders              | amount                   | double precision            |                          |                                                 | YES
 orders              | currency                 | character varying           |                          |                                                 | YES
 orders              | status                   | character varying           |                          |                                                 | YES
 orders              | stripe_payment_intent_id | character varying           |                          |                                                 | YES
 orders              | invoice_url              | character varying           |                          |                                                 | YES
 orders              | paid_at                  | timestamp with time zone    |                          |                                                 | YES
 orders              | created_at               | timestamp with time zone    |                          | now()                                           | YES
 plans               | id                       | integer                     |                          | nextval('plans_id_seq'::regclass)               | NO
 plans               | name                     | character varying           |                      100 |                                                 | NO
 plans               | plan_key                 | character varying           |                       50 |                                                 | NO
 plans               | display_name             | character varying           |                      100 |                                                 | NO
 plans               | description              | text                        |                          |                                                 | YES
 plans               | price                    | numeric                     |                          | 0.00                                            | NO
 plans               | billing_period           | character varying           |                       20 | 'monthly'::character varying                    | NO
 plans               | api_calls_limit          | integer                     |                          | 100                                             | NO
 plans               | drawings_limit           | integer                     |                          |                                                 | YES
 plans               | storage_limit_gb         | numeric                     |                          |                                                 | YES
 plans               | custom_models_limit      | integer                     |                          |                                                 | YES
 plans               | stripe_price_id          | character varying           |                      100 |                                                 | YES
 plans               | features                 | text                        |                          |                                                 | YES
 plans               | is_active                | boolean                     |                          | true                                            | YES
 plans               | is_featured              | boolean                     |                          | false                                           | YES
 plans               | is_popular               | boolean                     |                          | false                                           | YES
 plans               | created_at               | timestamp without time zone |                          | now()                                           | YES
 plans               | updated_at               | timestamp without time zone |                          | now()                                           | YES
 subscriptions       | id                       | integer                     |                          | nextval('subscriptions_id_seq'::regclass)       | NO
 subscriptions       | user_id                  | integer                     |                          |                                                 | YES
 subscriptions       | plan_name                | character varying           |                          |                                                 | YES
 subscriptions       | status                   | USER-DEFINED                |                          |                                                 | YES
 subscriptions       | price                    | double precision            |                          |                                                 | YES
 subscriptions       | currency                 | character varying           |                          |                                                 | YES
 subscriptions       | billing_period           | character varying           |                          |                                                 | YES
 subscriptions       | stripe_subscription_id   | character varying           |                          |                                                 | YES
 subscriptions       | stripe_customer_id       | character varying           |                          |                                                 | YES
 subscriptions       | api_calls_limit          | integer                     |                          |                                                 | YES
 subscriptions       | storage_limit_gb         | double precision            |                          |                                                 | YES
 subscriptions       | custom_models_limit      | integer                     |                          |                                                 | YES
 subscriptions       | current_period_start     | timestamp with time zone    |                          |                                                 | YES
 subscriptions       | current_period_end       | timestamp with time zone    |                          |                                                 | YES
 subscriptions       | created_at               | timestamp with time zone    |                          | now()                                           | YES
 usage_logs          | id                       | integer                     |                          | nextval('usage_logs_id_seq'::regclass)          | NO
 usage_logs          | user_id                  | integer                     |                          |                                                 | YES
 usage_logs          | endpoint                 | character varying           |                          |                                                 | YES
 usage_logs          | file_count               | integer                     |                          |                                                 | YES
 usage_logs          | detections_count         | integer                     |                          |                                                 | YES
 usage_logs          | processing_time          | double precision            |                          |                                                 | YES
 usage_logs          | model_name               | character varying           |                          |                                                 | YES
 usage_logs          | credits_used             | integer                     |                          |                                                 | YES
 usage_logs          | created_at               | timestamp with time zone    |                          | now()                                           | YES
 usage_logs          | custom_model_id          | integer                     |                          |                                                 | YES
 users               | id                       | integer                     |                          | nextval('users_id_seq'::regclass)               | NO
 users               | email                    | character varying           |                          |                                                 | NO
 users               | hashed_password          | character varying           |                          |                                                 | NO
 users               | full_name                | character varying           |                          |                                                 | YES
 users               | company                  | character varying           |                          |                                                 | YES
 users               | phone                    | character varying           |                          |                                                 | YES
 users               | role                     | USER-DEFINED                |                          |                                                 | YES
 users               | is_active                | boolean                     |                          |                                                 | YES
 users               | is_verified              | boolean                     |                          |                                                 | YES
 users               | api_key                  | character varying           |                          |                                                 | YES
 users               | api_calls_count          | integer                     |                          |                                                 | YES
 users               | api_calls_limit          | integer                     |                          |                                                 | YES
 users               | created_at               | timestamp with time zone    |                          | now()                                           | YES
 users               | last_login               | timestamp with time zone    |                          |                                                 | YES
 users               | reset_token              | character varying           |                      255 |                                                 | YES
 users               | reset_token_expires      | timestamp without time zone |                          |                                                 | YES
 users               | email_verified           | boolean                     |                          | false                                           | YES
 users               | email_verified_at        | timestamp without time zone |                          |                                                 | YES
 users               | drawing_limit            | integer                     |                          |                                                 | YES
(127 rows)

