# Babelash - Site de réservation extensions de cils

## Business
- Nom : Babelash
- Service : allongement de cils uniquement
- Ville : Bruxelles
- Horaires : lundi au dimanche, 10h - 18h
- Durée par créneau : 1h30
- Créneaux : 10:00, 11:30, 13:00, 14:30, 16:00, 17:30
- Site pour un vrai client — tout est en production

## Prix
- Semaine (lundi-samedi) : 35€
- Dimanche : 40€
- Promotion en cours : 20€ jusqu'au 30 avril 2026

## Acompte Stripe
- Montant : 10€ (variable `DEPOSIT` dans app.py)
- Clés **live** du client dans Railway (ne jamais les mettre en local)
- Clés **test** en local dans `.env` pour développement
- Flow : booking form → session Flask → `/create-checkout-session` → Stripe Checkout → `/payment-success` → DB → `/confirmation`
- En cas d'annulation : `/payment-cancel`
- Webhook : `/webhook` · event `checkout.session.completed` · `STRIPE_WEBHOOK_SECRET` dans Railway

## Pages
- `/` → landing page
- `/booking` → calendrier custom + créneaux + formulaire
- `/create-checkout-session` → redirect Stripe Checkout
- `/payment-success?session_id=` → vérification paiement + save DB + redirect confirmation
- `/payment-cancel` → page annulation
- `/payment-error` → erreur Stripe
- `/confirmation` → résumé réservation
- `/admin` → dashboard admin (agenda mensuel, déplacement + suppression RDV)
- `/admin/login` → login admin
- `/webhook` → Stripe webhook (POST)

## Stack
- Python 3 + Flask + SQLAlchemy + Gunicorn
- SQLite en dev (`instance/babelash.db`), PostgreSQL en prod (Railway)
- Jinja2 + Tailwind CSS via CDN
- Google Fonts : Playfair Display + Inter
- Stripe 11.x

## Modèle Reservation
- Champs : id, name, phone, email, date, time_slot, price, stripe_session_id, paid, created_at
- `paid=True` requis pour qu'un créneau soit considéré occupé
- Les créneaux passés aujourd'hui sont grisés (fuseau Europe/Brussels via zoneinfo)

## Lancer le projet (dev)
```bash
cd ~/Desktop/babelash && source venv/bin/activate && python app.py
```
Ou directement :
```bash
venv/bin/python app.py
```
Site local : http://127.0.0.1:5000

## Installer les dépendances
```bash
venv/bin/pip install -r requirements.txt
```

## DB
- SQLite recrée automatiquement au lancement en dev
- Visualiser avec TablePlus → SQLite → `instance/babelash.db`
- En prod : PostgreSQL Railway (URL publique dans `DATABASE_URL`)

## Admin
- URL prod : https://www.babeelashes.be/admin
- URL local : http://127.0.0.1:5000/admin
- Mot de passe dans `.env` : `babeelash2026`
- Fonctions : voir RDV du mois, déplacer un RDV, supprimer un RDV

## Réseaux sociaux
- TikTok et Instagram affichés sur la landing page

## Production (tout est déployé)

### URLs
- Site : https://www.babeelashes.be
- Admin : https://www.babeelashes.be/admin
- Railway backup : https://web-production-67667.up.railway.app
- GitHub : https://github.com/LouisBlankaert/babeelashes

### Railway
- Service Flask : gunicorn sur port 8080
- Start command : `gunicorn app:app --bind 0.0.0.0:$PORT`
- Plugin PostgreSQL connecté via `DATABASE_URL` (URL publique Railway)
- Custom domain : `www.babeelashes.be` → port 8080
- Variables Railway : SECRET_KEY, WHATSAPP_NUMBER, ADMIN_PASSWORD, STRIPE_SECRET_KEY, STRIPE_PUBLIC_KEY, STRIPE_WEBHOOK_SECRET, DATABASE_URL, FLASK_ENV=production

### OVH DNS (babeelashes.be)
- `www CNAME → 2t9q5aw4.up.railway.app.`
- `_railway-verify.www TXT → railway-verify=...`
- SSL géré automatiquement par Railway

### Stripe (live)
- Compte Stripe du client avec IBAN belge
- Webhook configuré : https://www.babeelashes.be/webhook · event checkout.session.completed
- `STRIPE_WEBHOOK_SECRET` dans Railway

### Déploiement continu
- Push sur `main` → Railway redéploie automatiquement

## Instructions
- Use context7 for up to date documentation
- Use Magic MCP for complex UI components
- Use UI UX Pro Max design system
