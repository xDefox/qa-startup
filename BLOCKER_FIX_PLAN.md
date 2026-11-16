# Plan to Fix 4 Main Blockers

## Blocker 1: CSP Header + inline styles/scripts
**Files**: `base.html`, `landing.html`, `oneshot.html`, `app.py`, static CSS/JS
**Status**: CSP middleware exists in enforce mode. Need to verify:
- All inline styles/scripts moved to static files ✅ (base.css, base.js exist)
- Landing page uses external CSS/JS ✅ (landing.css, landing.js)
- CSP allows Chart.js from cdn.jsdelivr.net ✅ (already in policy)
- No inline event handlers in templates
- CSP working in production

**Actions**:
1. Verify no inline styles/scripts in any template
2. Test CSP in browser dev tools
3. Ensure `unsafe-inline` not needed

## Blocker 2: CTA in Hero on `/`
**Files**: `index.html`, `base.css`
**Issue**: Form input doesn't look like primary CTA
**Actions**:
1. Make "Проверить сайт бесплатно" button prominent in hero section
2. Style the form submit as primary CTA
3. Add visual hierarchy: hero CTA → form as secondary

## Blocker 3: Watchdog hidden in Settings / no onboarding
**Files**: `settings.html`, `landing.html`, `base.css`, `settings.js`
**Issue**: Watchdog section at bottom of settings, no tooltip/onboarding
**Actions**:
1. Add tooltip/onboarding for Watchdog in settings
2. Add Watchdog CTA on landing page (highlight in pricing/plans)
3. Show Watchdog status more prominently

## Blocker 4: Billing/Alerts not fully connected
**Files**: `billing.py`, `stripe_integration.py`, `yookassa_integration.py`, `alerts.py`, `routes/api.py`, `storage.py`
**Issue**: Webhook handlers have TODOs, billing not fully wired
**Actions**:
1. Complete Stripe webhook handlers (checkout.session.completed, subscription.updated, etc.)
2. Complete ЮKassa webhook handlers
3. Wire billing limits to scan execution
4. Test email/Telegram alerts end-to-end
5. Connect scan_packages to billing flow
