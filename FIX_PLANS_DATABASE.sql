-- Fix plan values to match specifications

UPDATE plans SET 
    api_calls_limit = 100,
    custom_models_limit = 0
WHERE plan_key = 'free';

UPDATE plans SET 
    api_calls_limit = 10000,
    custom_models_limit = 5
WHERE plan_key = 'pro';

UPDATE plans SET 
    api_calls_limit = 999999,
    custom_models_limit = -1
WHERE plan_key = 'enterprise';

-- Verify the updates
SELECT name, price, api_calls_limit, custom_models_limit, billing_period 
FROM plans 
ORDER BY 
    CASE 
        WHEN plan_key = 'free' THEN 1
        WHEN plan_key = 'pro' THEN 2
        WHEN plan_key = 'enterprise' THEN 3
    END;
