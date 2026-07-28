-- ============================================
-- Add drawings_limit column to plans table
-- ============================================

-- Check if column exists first
DO $$ 
BEGIN
    IF NOT EXISTS (
        SELECT 1 
        FROM information_schema.columns 
        WHERE table_name = 'plans' 
        AND column_name = 'drawings_limit'
    ) THEN
        -- Add the column with default value 5
        ALTER TABLE plans ADD COLUMN drawings_limit INTEGER DEFAULT 5;
        
        -- Update existing plans with appropriate values
        -- Basic/Free plan: 5 drawings
        UPDATE plans SET drawings_limit = 5 WHERE plan_key = 'free' OR plan_key = 'basic';
        
        -- Professional plan: unlimited (-1)
        UPDATE plans SET drawings_limit = -1 WHERE plan_key = 'pro' OR plan_key = 'professional';
        
        -- Enterprise plan: unlimited (-1)
        UPDATE plans SET drawings_limit = -1 WHERE plan_key = 'enterprise';
        
        RAISE NOTICE 'Column drawings_limit added successfully';
    ELSE
        RAISE NOTICE 'Column drawings_limit already exists';
    END IF;
END $$;

-- Verify the column was added
SELECT column_name, data_type, column_default 
FROM information_schema.columns 
WHERE table_name = 'plans' AND column_name = 'drawings_limit';

-- Show current values
SELECT id, plan_key, name, drawings_limit FROM plans ORDER BY id;
