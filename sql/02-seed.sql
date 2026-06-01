-- =============================================================================
-- MissionControl - Mail Server Manager
-- Copyright (c) 2026 Your Net Tech
-- Developed by Jose Rinaldi
-- All rights reserved.
-- Unauthorized use, reproduction, or distribution is strictly prohibited
-- without written permission from Your Net Tech.
-- =============================================================================

-- ============================================================================
-- MissionControl Seed Data
-- ============================================================================

USE missioncontrol;

-- ----------------------------------------------------------------------------
-- Admin user
-- Password hash placeholder — replace on deploy.
-- Generate with: python -c "from passlib.hash import bcrypt; print(bcrypt.using(rounds=12).hash('CHANGE_ME'))"
-- ----------------------------------------------------------------------------
INSERT INTO users (username, email, hashed_password, full_name, is_active, is_superadmin)
VALUES (
    'admin',
    'admin@mail.example.com',
    'PLACEHOLDER_BCRYPT_HASH_CHANGED_ON_DEPLOY',
    'System Administrator',
    1,
    1
);

-- ----------------------------------------------------------------------------
-- Default roles
-- ----------------------------------------------------------------------------
INSERT INTO roles (name, description) VALUES
    ('admin', 'System administrator with full access'),
    ('operator', 'Operator with limited management access'),
    ('user', 'Standard end user');

-- ----------------------------------------------------------------------------
-- Assign admin user to admin role
-- ----------------------------------------------------------------------------
INSERT INTO user_roles (user_id, role_id)
SELECT u.id, r.id FROM users u, roles r
WHERE u.username = 'admin' AND r.name = 'admin';

-- ----------------------------------------------------------------------------
-- Default quota template
-- ----------------------------------------------------------------------------
INSERT INTO quota_templates (name, mailbox_limit_mb, storage_limit_mb, max_mailboxes, description, is_default)
VALUES (
    'default',
    1024,
    10240,
    50,
    'Default quota template: 1 GB per mailbox, 10 GB total storage, 50 mailboxes max',
    1
);

-- ----------------------------------------------------------------------------
-- Test domain
-- ----------------------------------------------------------------------------
INSERT INTO domains (domain_name, status, dkim_selector, dns_verified, quota_template_id)
SELECT 'example.org', 'active', 'default', 0, id FROM quota_templates WHERE name = 'default';

-- ----------------------------------------------------------------------------
-- Test mailbox
-- ----------------------------------------------------------------------------
INSERT INTO mailboxes (email, domain_id, password_hash, quota_limit_mb, is_active)
SELECT
    'postmaster@example.org',
    d.id,
    'PLACEHOLDER_BCRYPT_HASH_CHANGED_ON_DEPLOY',
    1024,
    1
FROM domains d WHERE d.domain_name = 'example.org';
