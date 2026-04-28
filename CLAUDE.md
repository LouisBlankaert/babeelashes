# Babelash - Site de réservation extensions de cils

## Business
- Nom : Babelash
- Service : allongement de cils uniquement
- Ville : Bruxelles
- Horaires : lundi au dimanche, 10h - 18h
- Durée par créneau : 1h30
- Créneaux : 10:00, 11:30, 13:00, 14:30, 16:00, 17:30
- Site pour un vrai client — tout doit être en production

## Prix
- Semaine (lundi-samedi) : 35€
- Dimanche : 40€
- Promotion en cours : 20€ jusqu'au 30 avril 2026

## Acompte Stripe
- Montant : 10€ (variable `DEPOSIT` dans app.py)
- Flow : booking form → session Flask → Stripe Checkout → /payment-success → DB → /confirmation
- En cas d'annulation : /payment-cancel (aucun débit, bouton retour booking)
- Clés dans `.env` : `STRIPE_SECRET_KEY`, `STRIPE_PUBLIC_KEY`, `STRIPE_WEBHOOK_SECRET`
- Webhook Stripe : POST /webhook (vérification signature)
- Les créneaux passés aujourd'hui sont automatiquement grisés (comparaison heure courante)

## Pages
- `/` → landing page
- `/booking` → calendrier custom + créneaux + formulaire
- `/create-checkout-session` → redirect vers Stripe Checkout (GET, données en session Flask)
- `/payment-success?session_id=` → vérification paiement + save DB + redirect confirmation
- `/payment-cancel` → page annulation, bouton retour booking
- `/payment-error` → erreur Stripe
- `/confirmation` → résumé réservation + WhatsApp auto
- `/admin` → dashboard admin (agenda mensuel, suppression RDV)
- `/admin/login` → login admin (mot de passe : `.env` → ADMIN_PASSWORD)
- `/webhook` → Stripe webhook (POST)

## Stack
- Python 3 + Flask + SQLAlchemy
- SQLite en dev (`instance/babelash.db`), PostgreSQL en prod (Railway)
- Jinja2 + Tailwind CSS via CDN
- Google Fonts : Playfair Display + Inter
- Stripe 11.x (acompte 10€ via Checkout Sessions)

## Modèle Reservation
- Champs : id, name, phone, email, date, time_slot, price, stripe_session_id, paid, created_at
- `paid=True` requis pour qu'un créneau soit considéré occupé (API availability + admin)

## Lancer le projet (dev)
```bash
cd ~/Desktop/babelash && source venv/bin/activate && python app.py
```
Ou directement :
```bash
venv/bin/python app.py
```
Site : http://127.0.0.1:5000

## DB
- SQLite en dev (recrée automatiquement au lancement)
- PostgreSQL en prod via Railway (variable `DATABASE_URL` injectée automatiquement)
- Visualiser dev avec TablePlus → SQLite → `instance/babelash.db`

## Admin
- URL : http://127.0.0.1:5000/admin
- Mot de passe dans `.env` : `babeelash2026`
- N'affiche que les réservations `paid=True`

## Réseaux sociaux
- TikTok et Instagram affichés sur la landing page

## Déploiement production (checklist complète)

### 1. Stripe du client
- Le client crée son propre compte Stripe (stripe.com) avec son IBAN belge
- Il active son compte (vérification identité + coordonnées bancaires)
- Dashboard Stripe → Developers → API Keys → copier les clés **live** (`pk_live_...`, `sk_live_...`)
- Après déploiement Railway : ajouter le webhook `https://ton-app.railway.app/webhook` dans Stripe Dashboard → Webhooks → event `checkout.session.completed`
- Copier le `STRIPE_WEBHOOK_SECRET` généré

### 2. Railway (hébergement + DB)
- railway.app → nouveau projet → Deploy from GitHub
- Ajouter un plugin **PostgreSQL** → Railway injecte `DATABASE_URL` automatiquement
- Variables d'environnement à configurer dans Railway :
  - `DATABASE_URL` → auto (PostgreSQL Railway)
  - `SECRET_KEY` → générer une vraie clé longue et aléatoire
  - `WHATSAPP_NUMBER` → numéro réel du client (ex: 32XXXXXXXXX)
  - `ADMIN_PASSWORD` → mot de passe admin du client
  - `STRIPE_SECRET_KEY` → clé live du client (`sk_live_...`)
  - `STRIPE_PUBLIC_KEY` → clé live du client (`pk_live_...`)
  - `STRIPE_WEBHOOK_SECRET` → secret webhook Stripe
- Procfile à créer : `web: python app.py`
- `app.py` : en prod, `app.run()` doit écouter sur `0.0.0.0` et le port `PORT` de Railway

### 3. Nom de domaine
- Acheter un domaine (ex: babelash.be sur OVH, Namecheap, Google Domains)
- Dans Railway → Settings → Custom Domain → ajouter le domaine
- Chez le registrar : ajouter un CNAME qui pointe vers l'URL Railway
- Railway gère le SSL automatiquement (HTTPS)

### 4. Avant de passer live
- Remplacer les clés Stripe test par les clés live dans Railway
- Tester un vrai paiement de 10€ (sera remboursé depuis le Dashboard Stripe)
- Vérifier le webhook dans Stripe Dashboard → Webhooks → onglet événements

## Instructions
- Use context7 for up to date documentation
- Use Magic MCP for complex UI components
- Use UI UX Pro Max design system
