-- Add missing columns to contact_messages table

ALTER TABLE contact_messages 
ADD COLUMN IF NOT EXISTS user_id INTEGER,
ADD COLUMN IF NOT EXISTS subject VARCHAR(500),
ADD COLUMN IF NOT EXISTS status VARCHAR(50) DEFAULT 'new',
ADD COLUMN IF NOT EXISTS priority VARCHAR(20) DEFAULT 'normal',
ADD COLUMN IF NOT EXISTS admin_reply TEXT,
ADD COLUMN IF NOT EXISTS replied_by INTEGER,
ADD COLUMN IF NOT EXISTS replied_at TIMESTAMP,
ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT NOW();

-- Add foreign key constraints if they don't exist
DO $$ 
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'contact_messages_user_id_fkey'
    ) THEN
        ALTER TABLE contact_messages 
        ADD CONSTRAINT contact_messages_user_id_fkey 
        FOREIGN KEY (user_id) REFERENCES users(id);
    END IF;
    
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'contact_messages_replied_by_fkey'
    ) THEN
        ALTER TABLE contact_messages 
        ADD CONSTRAINT contact_messages_replied_by_fkey 
        FOREIGN KEY (replied_by) REFERENCES users(id);
    END IF;
END $$;

-- Create indexes for better performance
CREATE INDEX IF NOT EXISTS idx_messages_status ON contact_messages(status);
CREATE INDEX IF NOT EXISTS idx_messages_user ON contact_messages(user_id);
CREATE INDEX IF NOT EXISTS idx_messages_created ON contact_messages(created_at DESC);

-- Show table structure
SELECT column_name, data_type, is_nullable 
FROM information_schema.columns 
WHERE table_name = 'contact_messages'
ORDER BY ordinal_position;
