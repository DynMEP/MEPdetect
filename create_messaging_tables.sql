-- Complete Messaging and Email System Schema

-- 1. Contact Messages Table
CREATE TABLE IF NOT EXISTS contact_messages (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id),
    name VARCHAR(200) NOT NULL,
    email VARCHAR(255) NOT NULL,
    subject VARCHAR(500),
    message TEXT NOT NULL,
    status VARCHAR(50) DEFAULT 'new',  -- new, read, replied, closed
    priority VARCHAR(20) DEFAULT 'normal',  -- low, normal, high, urgent
    admin_reply TEXT,
    replied_by INTEGER REFERENCES users(id),
    replied_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_messages_status ON contact_messages(status);
CREATE INDEX IF NOT EXISTS idx_messages_user ON contact_messages(user_id);
CREATE INDEX IF NOT EXISTS idx_messages_created ON contact_messages(created_at DESC);

-- 2. Email Verification Tokens
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

-- 3. Email Log (track all sent emails)
CREATE TABLE IF NOT EXISTS email_logs (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id),
    to_email VARCHAR(255) NOT NULL,
    subject VARCHAR(500),
    email_type VARCHAR(50),  -- verification, welcome, password_reset, message_reply
    status VARCHAR(50) DEFAULT 'pending',  -- pending, sent, failed
    error_message TEXT,
    sent_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_email_logs_user ON email_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_email_logs_type ON email_logs(email_type);

-- 4. Add email_verified column to users table if not exists
DO $$ 
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'users' AND column_name = 'email_verified'
    ) THEN
        ALTER TABLE users ADD COLUMN email_verified BOOLEAN DEFAULT false;
        ALTER TABLE users ADD COLUMN email_verified_at TIMESTAMP;
    END IF;
END $$;

-- 5. Update existing users to verified (grandfathered)
UPDATE users SET email_verified = true WHERE email_verified IS NULL OR email_verified = false;

-- Display tables
SELECT 'contact_messages table:' as info;
SELECT COUNT(*) as total_messages FROM contact_messages;

SELECT 'email_verifications table:' as info;
SELECT COUNT(*) as total_verifications FROM email_verifications;

SELECT 'email_logs table:' as info;
SELECT COUNT(*) as total_emails FROM email_logs;

SELECT 'Users email verification status:' as info;
SELECT email_verified, COUNT(*) FROM users GROUP BY email_verified;
