-- Drop and recreate plans table with drawings_limit field

DROP TABLE IF EXISTS plans CASCADE;

CREATE TABLE plans (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    plan_key VARCHAR(50) UNIQUE NOT NULL,
    display_name VARCHAR(100) NOT NULL,
    description TEXT,
    price DECIMAL(10, 2) NOT NULL DEFAULT 0.00,
    billing_period VARCHAR(20) NOT NULL DEFAULT 'monthly',
    api_calls_limit INTEGER NOT NULL DEFAULT 100,
    drawings_limit INTEGER, -- -1 = unlimited, NULL = not applicable, N = specific limit
    storage_limit_gb DECIMAL(10, 2),
    custom_models_limit INTEGER,
    stripe_price_id VARCHAR(100),
    features TEXT, -- Comma-separated features
    is_active BOOLEAN DEFAULT TRUE,
    is_featured BOOLEAN DEFAULT FALSE,
    is_popular BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_plans_plan_key ON plans(plan_key);
CREATE INDEX idx_plans_is_active ON plans(is_active);

-- Insert the 3 correct plans
INSERT INTO plans (name, plan_key, display_name, description, price, billing_period, 
                   api_calls_limit, drawings_limit, storage_limit_gb, custom_models_limit, 
                   features, is_active, is_featured, is_popular)
VALUES 
    -- Basic Plan (Free)
    ('Basic', 'free', 'Basic', 'Forever free', 0.00, 'monthly', 
     100, 5, 1.0, 0,
     '5 drawings per month,Standard MEP symbols,PDF & image support,CSV export',
     TRUE, FALSE, FALSE),
    
    -- Professional Plan (Most Popular)
    ('Professional', 'pro', 'Professional', 'Most popular plan', 49.00, 'monthly',
     10000, -1, 50.0, 5,
     'Unlimited drawings,All MEP symbol libraries,Batch processing,Excel CSV JSON ANNOTATE export,Netlist generation,Priority email support,Revit & BIM integration',
     TRUE, FALSE, TRUE),
    
    -- Enterprise Plan (Featured, Custom pricing)
    ('Enterprise', 'enterprise', 'Enterprise', 'For large teams', 0.00, 'custom',
     999999, -1, 500.0, -1,
     'Everything in Professional,Custom symbol training,Custom AI model training,API access,White-label options,Dedicated account manager,SLA guarantee,On-premise deployment,24/7 support',
     TRUE, TRUE, FALSE);

-- Update trigger
CREATE OR REPLACE FUNCTION update_plans_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_update_plans_updated_at
    BEFORE UPDATE ON plans
    FOR EACH ROW
    EXECUTE FUNCTION update_plans_updated_at();
