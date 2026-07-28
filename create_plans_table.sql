-- Create plans table for subscription plan management

CREATE TABLE IF NOT EXISTS plans (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    plan_key VARCHAR(50) UNIQUE NOT NULL,
    display_name VARCHAR(100) NOT NULL,
    description TEXT,
    price DECIMAL(10, 2) NOT NULL DEFAULT 0.00,
    billing_period VARCHAR(20) NOT NULL DEFAULT 'monthly', -- 'monthly', 'yearly', 'one-time'
    api_calls_limit INTEGER NOT NULL DEFAULT 100,
    storage_limit_gb DECIMAL(10, 2),
    custom_models_limit INTEGER,
    stripe_price_id VARCHAR(100),
    features TEXT, -- Comma-separated list of features
    is_active BOOLEAN DEFAULT TRUE,
    is_featured BOOLEAN DEFAULT FALSE,
    is_popular BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Create indexes on plan_key for faster lookups
CREATE INDEX IF NOT EXISTS idx_plans_plan_key ON plans(plan_key);
CREATE INDEX IF NOT EXISTS idx_plans_is_active ON plans(is_active);

-- Insert default plans
INSERT INTO plans (name, plan_key, display_name, description, price, billing_period, api_calls_limit, storage_limit_gb, custom_models_limit, features, is_active, is_featured, is_popular)
VALUES 
    ('Free', 'free', 'Free Plan', 'Perfect for getting started with basic MEP symbol detection', 0.00, 'monthly', 100, 1.0, 0, 
     'Up to 100 API calls per month,1GB storage,Standard detection models,Email support', 
     TRUE, FALSE, FALSE),
    
    ('Pro', 'pro', 'Professional Plan', 'For professionals who need more power and flexibility', 29.99, 'monthly', 5000, 10.0, 3, 
     'Up to 5,000 API calls per month,10GB storage,All detection models,Custom model training,Priority email support,API access', 
     TRUE, FALSE, TRUE),
    
    ('Enterprise', 'enterprise', 'Enterprise Plan', 'For teams and businesses with high-volume needs', 99.99, 'monthly', 50000, 100.0, 20, 
     'Up to 50,000 API calls per month,100GB storage,All detection models,Unlimited custom models,Priority support,Dedicated account manager,SLA guarantee,Custom integrations', 
     TRUE, TRUE, FALSE)
ON CONFLICT (plan_key) DO NOTHING;

-- Add trigger to update updated_at timestamp
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
