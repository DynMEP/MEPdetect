#!/bin/bash
# Complete Database Setup for Messaging & Email System

echo "=========================================="
echo "Setting up Messaging Database Tables"
echo "=========================================="
echo ""

docker exec -i mepdetect-postgres psql -U mepdetect -d mepdetect << 'EOSQL'

-- ============================================================================
-- 1. Fix contact_messages table (add missing columns)
-- ============================================================================

ALTER TABLE contact_messages 
ADD COLUMN IF NOT EXISTS user_id INTEGER,
ADD COLUMN IF NOT EXISTS subject VARCHAR(500),
ADD COLUMN IF NOT EXISTS status VARCHAR(50) DEFAULT 'new',
ADD COLUMN IF NOT EXISTS priority VARCHAR(20) DEFAULT 'normal',
ADD COLUMN IF NOT EXISTS admin_reply TEXT,
ADD COLUMN IF NOT EXISTS replied_by INTEGER,
ADD COLUMN IF NOT EXISTS replied_at TIMESTAMP,
ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT NOW();

-- Add foreign keys
DO $$ 
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'contact_messages_user_id_fkey') THEN
        ALTER TABLE contact_messages ADD CONSTRAINT contact_messages_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'contact_messages_replied_by_fkey') THEN
        ALTER TABLE contact_messages ADD CONSTRAINT contact_messages_replied_by_fkey FOREIGN KEY (replied_by) REFERENCES users(id);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_messages_status ON contact_messages(status);
CREATE INDEX IF NOT EXISTS idx_messages_user ON contact_messages(user_id);
CREATE INDEX IF NOT EXISTS idx_messages_created ON contact_messages(created_at DESC);

-- ============================================================================
-- 2. Create email_verifications table
-- ============================================================================

CREATE TABLE IF NOT EXISTS email_verifications (
    id SERIAL PRIMARY KEY,
    user_id INTEGER UNIQUE REFERENCES users(id),
    token VARCHAR(100) UNIQUE NOT NULL,
    verified BOOLEAN DEFAULT false,
    verified_at TIMESTAMP,
    expires_at TIMESTAMP NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_email_token ON email_verifications(token);
CREATE INDEX IF NOT EXISTS idx_email_user ON email_verifications(user_id);

-- ============================================================================
-- 3. Create email_logs table
-- ============================================================================

CREATE TABLE IF NOT EXISTS email_logs (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id),
    to_email VARCHAR(255) NOT NULL,
    subject VARCHAR(500),
    email_type VARCHAR(50),
    status VARCHAR(50) DEFAULT 'pending',
    error_message TEXT,
    sent_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_email_logs_user ON email_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_email_logs_type ON email_logs(email_type);

-- ============================================================================
-- 4. Add email verification columns to users table
-- ============================================================================

DO $$ 
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'users' AND column_name = 'email_verified') THEN
        ALTER TABLE users ADD COLUMN email_verified BOOLEAN DEFAULT false;
    END IF;
    
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'users' AND column_name = 'email_verified_at') THEN
        ALTER TABLE users ADD COLUMN email_verified_at TIMESTAMP;
    END IF;
END $$;

-- Set existing users as verified (grandfathered in)
UPDATE users SET email_verified = true WHERE email_verified IS NULL OR email_verified = false;

-- ============================================================================
-- Show results
-- ============================================================================

\echo ''
\echo '✅ contact_messages columns:'
SELECT column_name, data_type 
FROM information_schema.columns 
WHERE table_name = 'contact_messages'
ORDER BY ordinal_position;

\echo ''
\echo '✅ Tables created:'
SELECT tablename FROM pg_tables 
WHERE schemaname = 'public' 
AND tablename IN ('contact_messages', 'email_verifications', 'email_logs')
ORDER BY tablename;

\echo ''
\echo '✅ Users email verification:'
SELECT email_verified, COUNT(*) FROM users GROUP BY email_verified;

EOSQL

echo ""
echo "=========================================="
echo "✅ Database Setup Complete!"
echo "=========================================="
echo ""
echo "Created/Updated:"
echo "  ✅ contact_messages table (with all columns)"
echo "  ✅ email_verifications table"
echo "  ✅ email_logs table"
echo "  ✅ users.email_verified column"
echo ""
echo "Now restart the API:"
echo "  cd /opt/MEPdetector/mepdetect-user-api"
echo "  docker-compose restart mepdetect-user-api"
echo ""
