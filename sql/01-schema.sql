-- =============================================================================
-- MissionControl - Mail Server Manager
-- Copyright (c) 2026 Your Net Tech
-- Developed by Jose Rinaldi (joserinaldi-l)
-- All rights reserved.
-- Unauthorized use, reproduction, or distribution is strictly prohibited
-- without written permission from Your Net Tech.
-- =============================================================================

-- ============================================================================
-- MissionControl Database Schema
-- Generated from SQLAlchemy models on 2026-06-01
-- Target: MySQL / MariaDB
-- Engine: InnoDB, Charset: utf8mb4
-- ============================================================================

CREATE DATABASE IF NOT EXISTS missioncontrol
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

USE missioncontrol;

-- ----------------------------------------------------------------------------
-- Roles
-- ----------------------------------------------------------------------------
CREATE TABLE roles (
    id          INT             NOT NULL AUTO_INCREMENT,
    name        VARCHAR(50)     NOT NULL,
    description TEXT            NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_roles_name (name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ----------------------------------------------------------------------------
-- Users
-- ----------------------------------------------------------------------------
CREATE TABLE users (
    id              INT             NOT NULL AUTO_INCREMENT,
    username        VARCHAR(150)    NOT NULL,
    email           VARCHAR(255)    NOT NULL,
    hashed_password VARCHAR(255)    NOT NULL,
    full_name       VARCHAR(255)    NULL,
    is_active       TINYINT(1)      NOT NULL DEFAULT 1,
    is_superadmin   TINYINT(1)      NOT NULL DEFAULT 0,
    totp_secret     VARCHAR(64)     NULL,
    created_at      DATETIME(6)     NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at      DATETIME(6)     NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    PRIMARY KEY (id),
    UNIQUE KEY uq_users_username (username),
    UNIQUE KEY uq_users_email (email),
    INDEX ix_users_username (username),
    INDEX ix_users_email (email)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ----------------------------------------------------------------------------
-- User-Role Association (many-to-many)
-- ----------------------------------------------------------------------------
CREATE TABLE user_roles (
    user_id INT NOT NULL,
    role_id INT NOT NULL,
    PRIMARY KEY (user_id, role_id),
    CONSTRAINT fk_user_roles_user FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
    CONSTRAINT fk_user_roles_role FOREIGN KEY (role_id) REFERENCES roles (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ----------------------------------------------------------------------------
-- Quota Templates
-- ----------------------------------------------------------------------------
CREATE TABLE quota_templates (
    id                INT             NOT NULL AUTO_INCREMENT,
    name              VARCHAR(100)    NOT NULL,
    mailbox_limit_mb  INT             NOT NULL DEFAULT 0 COMMENT '0=unlimited',
    storage_limit_mb  INT             NOT NULL DEFAULT 0 COMMENT '0=unlimited',
    max_mailboxes     INT             NOT NULL DEFAULT 0 COMMENT '0=unlimited',
    description       TEXT            NULL,
    is_default        TINYINT(1)      NOT NULL DEFAULT 0,
    PRIMARY KEY (id),
    UNIQUE KEY uq_quota_templates_name (name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ----------------------------------------------------------------------------
-- Domains
-- ----------------------------------------------------------------------------
CREATE TABLE domains (
    id                  INT             NOT NULL AUTO_INCREMENT,
    domain_name         VARCHAR(255)    NOT NULL,
    status              VARCHAR(20)     NOT NULL DEFAULT 'pending' COMMENT 'active|inactive|pending',
    quota_template_id   INT             NULL,
    cloudflare_zone_id  VARCHAR(255)    NULL,
    dkim_selector       VARCHAR(100)    NOT NULL DEFAULT 'default',
    dkim_private_key    TEXT            NULL,
    created_at          DATETIME(6)     NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    expires_at          DATETIME(6)     NULL,
    dns_verified        TINYINT(1)      NOT NULL DEFAULT 0,
    registrobr_status   TEXT            NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_domains_domain_name (domain_name),
    INDEX ix_domains_domain_name (domain_name),
    CONSTRAINT fk_domains_quota_template FOREIGN KEY (quota_template_id) REFERENCES quota_templates (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ----------------------------------------------------------------------------
-- Mailboxes
-- ----------------------------------------------------------------------------
CREATE TABLE mailboxes (
    id                      INT             NOT NULL AUTO_INCREMENT,
    email                   VARCHAR(255)    NOT NULL,
    domain_id               INT             NOT NULL,
    password_hash           VARCHAR(255)    NOT NULL,
    password_encrypted      TEXT            NULL,
    quota_limit_mb          INT             NOT NULL DEFAULT 0 COMMENT '0=unlimited',
    quota_used_mb           BIGINT          NOT NULL DEFAULT 0,
    is_active               TINYINT(1)      NOT NULL DEFAULT 1,
    forward_to              TEXT            NULL,
    auto_responder_enabled  TINYINT(1)      NOT NULL DEFAULT 0,
    auto_responder_subject  VARCHAR(255)    NULL,
    auto_responder_body     TEXT            NULL,
    last_login              DATETIME(6)     NULL,
    created_at              DATETIME(6)     NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (id),
    UNIQUE KEY uq_mailboxes_email (email),
    INDEX ix_mailboxes_email (email),
    CONSTRAINT fk_mailboxes_domain FOREIGN KEY (domain_id) REFERENCES domains (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ----------------------------------------------------------------------------
-- Email Aliases
-- ----------------------------------------------------------------------------
CREATE TABLE email_aliases (
    id              INT             NOT NULL AUTO_INCREMENT,
    source_email    VARCHAR(255)    NOT NULL,
    domain_id       INT             NOT NULL,
    destinations    TEXT            NOT NULL COMMENT 'Comma-separated destination emails',
    description     TEXT            NULL,
    is_active       TINYINT(1)      NOT NULL DEFAULT 1,
    created_at      DATETIME(6)     NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (id),
    INDEX ix_email_aliases_source_email (source_email),
    CONSTRAINT fk_email_aliases_domain FOREIGN KEY (domain_id) REFERENCES domains (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ----------------------------------------------------------------------------
-- Contact Groups
-- ----------------------------------------------------------------------------
CREATE TABLE contact_groups (
    id          INT             NOT NULL AUTO_INCREMENT,
    user_id     INT             NOT NULL,
    name        VARCHAR(255)    NOT NULL,
    color       VARCHAR(7)      NOT NULL DEFAULT '#3B82F6',
    created_at  DATETIME(6)     NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (id),
    INDEX ix_contact_groups_user_id (user_id),
    CONSTRAINT fk_contact_groups_user FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ----------------------------------------------------------------------------
-- Contacts
-- ----------------------------------------------------------------------------
CREATE TABLE contacts (
    id          INT             NOT NULL AUTO_INCREMENT,
    user_id     INT             NOT NULL,
    group_id    INT             NULL,
    name        VARCHAR(255)    NOT NULL,
    email       VARCHAR(255)    NOT NULL,
    phone       VARCHAR(50)     NULL,
    company     VARCHAR(255)    NULL,
    job_title   VARCHAR(255)    NULL,
    notes       TEXT            NULL,
    photo_url   VARCHAR(500)    NULL,
    extra_data  JSON            NULL COMMENT 'Extra fields like address, birthday, etc.',
    is_favorite TINYINT(1)      NOT NULL DEFAULT 0,
    created_at  DATETIME(6)     NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at  DATETIME(6)     NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    PRIMARY KEY (id),
    INDEX ix_contacts_user_id (user_id),
    CONSTRAINT fk_contacts_user FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
    CONSTRAINT fk_contacts_group FOREIGN KEY (group_id) REFERENCES contact_groups (id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ----------------------------------------------------------------------------
-- Calendars
-- ----------------------------------------------------------------------------
CREATE TABLE calendars (
    id          INT             NOT NULL AUTO_INCREMENT,
    user_id     INT             NOT NULL,
    name        VARCHAR(255)    NOT NULL,
    color       VARCHAR(7)      NOT NULL DEFAULT '#3B82F6',
    is_default  TINYINT(1)      NOT NULL DEFAULT 0,
    created_at  DATETIME(6)     NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (id),
    INDEX ix_calendars_user_id (user_id),
    CONSTRAINT fk_calendars_user FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ----------------------------------------------------------------------------
-- Calendar Events
-- ----------------------------------------------------------------------------
CREATE TABLE calendar_events (
    id               INT             NOT NULL AUTO_INCREMENT,
    calendar_id      INT             NOT NULL,
    user_id          INT             NOT NULL,
    title            VARCHAR(500)    NOT NULL,
    description      TEXT            NULL,
    location         VARCHAR(500)    NULL,
    all_day          TINYINT(1)      NOT NULL DEFAULT 0,
    start_time       DATETIME(6)     NOT NULL,
    end_time         DATETIME(6)     NOT NULL,
    timezone         VARCHAR(50)     NOT NULL DEFAULT 'UTC',
    recurrence_rule  VARCHAR(500)    NULL COMMENT 'RRULE string',
    color            VARCHAR(7)      NULL,
    is_cancelled     TINYINT(1)      NOT NULL DEFAULT 0,
    created_at       DATETIME(6)     NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at       DATETIME(6)     NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    PRIMARY KEY (id),
    INDEX ix_calendar_events_calendar_id (calendar_id),
    INDEX ix_calendar_events_user_id (user_id),
    CONSTRAINT fk_calendar_events_calendar FOREIGN KEY (calendar_id) REFERENCES calendars (id) ON DELETE CASCADE,
    CONSTRAINT fk_calendar_events_user FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ----------------------------------------------------------------------------
-- Tasks
-- ----------------------------------------------------------------------------
CREATE TABLE tasks (
    id              INT             NOT NULL AUTO_INCREMENT,
    user_id         INT             NOT NULL,
    calendar_id     INT             NULL,
    title           VARCHAR(500)    NOT NULL,
    description     TEXT            NULL,
    due_date        DATETIME(6)     NULL,
    completed       TINYINT(1)      NOT NULL DEFAULT 0,
    completed_at    DATETIME(6)     NULL,
    priority        INT             NOT NULL DEFAULT 0 COMMENT '0=normal, 1=low, 2=medium, 3=high',
    color           VARCHAR(7)      NULL,
    created_at      DATETIME(6)     NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at      DATETIME(6)     NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    PRIMARY KEY (id),
    INDEX ix_tasks_user_id (user_id),
    CONSTRAINT fk_tasks_user FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
    CONSTRAINT fk_tasks_calendar FOREIGN KEY (calendar_id) REFERENCES calendars (id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ----------------------------------------------------------------------------
-- Email Templates
-- ----------------------------------------------------------------------------
CREATE TABLE email_templates (
    id          INT             NOT NULL AUTO_INCREMENT,
    user_id     INT             NOT NULL,
    name        VARCHAR(255)    NOT NULL,
    subject     VARCHAR(500)    NOT NULL,
    body        TEXT            NULL,
    created_at  DATETIME(6)     NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (id),
    INDEX ix_email_templates_user_id (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ----------------------------------------------------------------------------
-- Undo Send
-- ----------------------------------------------------------------------------
CREATE TABLE undo_send (
    id            INT             NOT NULL AUTO_INCREMENT,
    user_id       INT             NOT NULL,
    message_id    VARCHAR(255)    NOT NULL,
    to_addrs      JSON            NULL,
    cc_addrs      JSON            NULL,
    bcc_addrs     JSON            NULL,
    subject       VARCHAR(500)    NULL,
    body_text     TEXT            NULL,
    body_html     TEXT            NULL,
    scheduled_at  DATETIME(6)     NOT NULL,
    expires_at    DATETIME(6)     NOT NULL,
    status        VARCHAR(20)     NOT NULL DEFAULT 'pending',
    PRIMARY KEY (id),
    UNIQUE KEY uq_undo_send_message_id (message_id),
    INDEX ix_undo_send_user_id (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ----------------------------------------------------------------------------
-- Snoozed Messages
-- ----------------------------------------------------------------------------
CREATE TABLE snoozed_messages (
    id            INT             NOT NULL AUTO_INCREMENT,
    user_id       INT             NOT NULL,
    message_uid   VARCHAR(50)     NOT NULL,
    mailbox       VARCHAR(255)    NOT NULL DEFAULT 'INBOX',
    snooze_until  DATETIME(6)     NOT NULL,
    created_at    DATETIME(6)     NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (id),
    INDEX ix_snoozed_messages_user_id (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ----------------------------------------------------------------------------
-- Audit Logs
-- ----------------------------------------------------------------------------
CREATE TABLE audit_logs (
    id            INT             NOT NULL AUTO_INCREMENT,
    user_id       INT             NULL,
    action        VARCHAR(100)    NOT NULL,
    resource_type VARCHAR(100)    NULL,
    resource_id   VARCHAR(100)    NULL,
    details       JSON            NULL,
    ip_address    VARCHAR(45)     NULL,
    user_agent    VARCHAR(500)    NULL,
    created_at    DATETIME(6)     NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (id),
    INDEX ix_audit_logs_user_id (user_id),
    INDEX ix_audit_logs_action (action),
    INDEX ix_audit_logs_created_at (created_at),
    CONSTRAINT fk_audit_logs_user FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
