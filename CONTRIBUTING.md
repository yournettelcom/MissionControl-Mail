<!--
  MissionControl - Mail Server Manager
  Copyright (c) 2026 Your Net Tech
  Developed by Jose Rinaldi
  All rights reserved.
  Unauthorized use, reproduction, or distribution is strictly prohibited
  without written permission from Your Net Tech.
-->

# Contributing to MissionControl

Thanks for your interest in contributing! We welcome bug reports, feature suggestions, documentation improvements, and code changes.

---

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [How to Contribute](#how-to-contribute)
- [Reporting Issues](#reporting-issues)
- [Feature Requests](#feature-requests)
- [Pull Requests](#pull-requests)
- [Development Setup](#development-setup)
- [Project Structure](#project-structure)
- [Coding Guidelines](#coding-guidelines)
- [Testing](#testing)
- [Commit Messages](#commit-messages)

---

## Code of Conduct

All participants in this project are expected to act respectfully and professionally. Harassment, trolling, and personal attacks will not be tolerated.

In short: **be excellent to each other.**

---

## How to Contribute

1. **Fork** the repository
2. **Create a branch** for your change (`git checkout -b feat/my-feature`)
3. **Make your changes** following the guidelines below
4. **Test** your changes
5. **Submit a pull request**

---

## Reporting Issues

When opening an issue, please include:

- **Bug reports**: Steps to reproduce, expected behavior, actual behavior, server OS, browser (if UI-related), and any relevant logs.
- **Feature requests**: A clear description of what you want to accomplish and why. Mockups or examples help.

---

## Feature Requests

We track feature requests via GitHub Issues. Before submitting:

- Search existing issues to avoid duplicates
- Explain the use case and why it matters
- Be specific about what the feature should do

---

## Pull Requests

1. **Keep PRs focused** — one feature or fix per PR. Large changes should be discussed in an issue first.
2. **Write tests** for new functionality.
3. **Update documentation** if you change behavior or add features.
4. **Ensure all tests pass** before requesting review.
5. **Reference the issue** number in the PR description (e.g., `Closes #123`).

### PR Checklist

- [ ] Code compiles and runs without errors
- [ ] New tests pass
- [ ] Existing tests pass
- [ ] Documentation updated (if applicable)
- [ ] Commit messages follow the convention (see below)

---

## Development Setup

### Prerequisites

- Debian 12+ or Ubuntu 22+
- Python 3.11+
- MariaDB 10.11+
- Redis 7+
- Node.js 18+ (if you modify the React frontend)

### Backend

```bash
git clone <your-fork> missioncontrol
cd missioncontrol/backend

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Copy and edit config
cp .env.example .env
# Fill in DATABASE_URL, SECRET_KEY, etc.

uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Frontend

The current frontend is distributed as a pre-compiled SPA. If you want to modify it:

```bash
cd frontend
npm install
npm run dev     # development server at :5173
npm run build   # production build → assets/
```

### Database

```bash
mysql -u root < sql/01-schema.sql
mysql -u root < sql/02-seed.sql  # creates admin user + test domain
```

---

## Project Structure

```
backend/
├── app/
│   ├── api/          # REST endpoints (19 routers)
│   ├── core/         # Config, database, security
│   ├── models/       # SQLAlchemy models
│   └── services/     # Business logic
├── requirements.txt
└── .env.example

frontend/
├── assets/           # Compiled SPA (do not edit directly)
├── index.html
└── src/              # React source (if available)

configs/
├── postfix/
├── dovecot/
├── apache/
└── rspamd/

sql/
├── 01-schema.sql     # DDL (16 tables)
├── 02-seed.sql       # Initial data
└── 03-reset.sql      # Cleanup

tests/                # Test scripts
deploy.sh             # Single-command deploy
```

---

## Coding Guidelines

### Python (Backend)

- **Style**: Follow [PEP 8](https://peps.python.org/pep-0008/)
- **Type hints**: Use them for all function signatures
- **Async**: Use `async/await` for I/O operations. Avoid `asyncio.run()` inside async functions
- **Imports**: Group as standard lib, third-party, local (separated by blank lines)
- **Error handling**: Use specific exceptions, not bare `except:`

```python
# Good
async def get_user(user_id: int) -> User | None:
    async with session() as db:
        return await db.get(User, user_id)

# Avoid
async def get_user(id):
    return await db.query(...)
```

### JavaScript / React (Frontend)

- Use functional components with hooks
- Follow the existing component patterns
- Keep i18n strings (if any) in a single locale file
- Format with Prettier (default config)

### Configuration Files (Postfix, Dovecot, etc.)

- Keep them idempotent — `deploy.sh` should be re-runnable
- Use `PLACEHOLDER_*` for values that must be replaced at deploy time
- Comment non-obvious settings

---

## Testing

```bash
# Run the full test suite
bash tests/run-all-tests.sh

# Individual tests
bash tests/01-test-smtp.sh
bash tests/02-test-imap.sh
bash tests/03-test-api.sh
bash tests/05-test-dns.sh
```

### What the tests cover

| Test | Scope |
|------|-------|
| SMTP | Port connectivity, STARTTLS, EHLO, message delivery |
| IMAP | Port connectivity, STARTTLS, login, folder operations |
| API  | 20+ REST endpoints (auth, domains, mailboxes, metrics, etc.) |
| DNS  | MX, SPF, DKIM, DMARC record verification |

### Writing new tests

- Add test scripts to `tests/` following the `NN-test-name.sh` convention
- Source `tests/test-config.sh` for shared variables
- Use `pass`/`fail` functions for consistent output
- Tests should be idempotent and non-destructive

---

## Commit Messages

Follow the [Conventional Commits](https://www.conventionalcommits.org/) format:

```
<type>: <short description>

[optional body]
[optional footer]
```

### Types

| Type     | Usage |
|----------|-------|
| `feat`   | New feature |
| `fix`    | Bug fix |
| `docs`   | Documentation |
| `refactor` | Code change that neither fixes nor adds |
| `test`   | Adding or updating tests |
| `chore`  | Build, CI, dependencies |
| `perf`   | Performance improvement |
| `style`  | Formatting (no logic change) |

### Examples

```
feat: add DKIM key rotation endpoint
fix: handle empty mailbox on IMAP login
docs: add production SSL instructions
test: cover alias CRUD edge cases
```

---

## Getting Help

- Open a [GitHub Discussion](https://github.com/your-org/missioncontrol/discussions)
- Check existing issues and PRs before asking

---

*Thank you for contributing to MissionControl!*
