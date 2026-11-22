# WE-SELL — runnable full-stack website

A Python Flask + SQLite starter application for the WE-SELL vehicle referral marketplace. Includes responsive homepage, vehicle search and details, buyer signup/login, dealer login, inventory creation and hiding, lead coordination, appointment proposals and acceptance, sale reporting, admin verification, and a $25 gift-card eligibility ledger.

## Quick start

Requires Python 3.10+. From this folder:

```bash
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -r requirements.txt
export SECRET_KEY="replace-with-a-long-random-secret"
export WESELL_SEED_DEMO=1
python app.py
```

Open http://127.0.0.1:5000

**Demo accounts (ONLY when WESELL_SEED_DEMO=1 on first startup):**

- Admin: `admin@wesell.local` / `AdminDemo123!`
- Dealer: `dealer@wesell.local` / `DealerDemo123!`
- Buyer: `buyer@wesell.local` / `BuyerDemo123!`

All vehicles, dealer names, prices, and images are illustrative seed data. Replace with authorized real inventory before launch. The seed accounts use known passwords and MUST be removed or changed before deployment.

## Test the end-to-end flow

1. Sign in as a buyer, open a vehicle, select a gas station, and request an appointment.
2. Sign in as the dealer and open the new lead; propose an available time.
3. Sign in as the buyer and accept the appointment.
4. Sign in as the dealer and report a completed sale.
5. Sign in as admin and verify the sale; this creates a **pending** $25 reward.
6. Only after actually sending the gift card externally, admin marks it issued.

## Important production work before going live

- Add proper admin dealer onboarding and approvals, password reset, email verification, account deletion, rate limiting, and audit logs.
- Integrate transactional email/SMS (e.g. SendGrid/Twilio) and background jobs. Currently messages and status changes are stored in the site, not sent by SMS/email.
- Integrate dealership inventory feeds (DealerCenter or other approved provider); manual vehicle entry works now.
- Integrate actual gift card provider and purchase verification. No gift cards are purchased or delivered automatically in this version.
- Add privacy policy, terms, California privacy compliance, consent to SMS/email, dealership agreements, reward rules, and legal review.
- Deploy behind HTTPS with a stable SECRET_KEY, COOKIE_SECURE=1, proper monitoring, backups, database migration strategy, and a production WSGI server (e.g. gunicorn). Do not run Flask development server in production.
- Replace SQLite with managed PostgreSQL for higher-volume deployment; add background queue and robust permission checks.
- Implement a formal dealer/customer contact-release policy; the dealer dashboard intentionally does not show buyer email/phone.
- Pricing and payment collection for dealer referrals have not been finalized and are not implemented.

This is an operational local MVP, **not a deployed public site**.
