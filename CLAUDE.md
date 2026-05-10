# Babelash - Site de réservation extensions de cils

## Business
- Nom : Babelash
- Service : rehaussement de cils uniquement
- Ville : Bruxelles
- Horaires : lundi au dimanche, 10h - 18h
- Durée par créneau : 1h
- Créneaux : 10:00, 11:30, 13:00, 14:30, 16:00, 17:30
- Site pour un vrai client — tout est en production

## Prix
- Semaine (lundi-samedi) : 35€
- Dimanche : 40€
- Option teinture : +5€ (sélectionnable dans le formulaire de réservation)
- Promotion **expirée** : 20€ était valable jusqu'au 30 avril 2026 (plus affichée)
- Logique : `promo_active = date.today() <= PROMO_UNTIL` passé au template

## Acompte virement bancaire
- Montant : 10€ (variable `DEPOSIT` dans app.py)
- IBAN : BE94 3632 6175 1914 (variable `BANK_IBAN`)
- Flow : booking form → sauvegarde directe en DB (`paid=True`) → `/confirmation` avec IBAN
- Communication demandée : "Babeelashes + nom de la cliente"
- La propriétaire vérifie manuellement les virements sur son compte
- Stripe entièrement supprimé

## Option teinture
- Prix : +5€ (variable `PRICE_TEINTURE` dans app.py)
- Toggle dans le formulaire étape 4
- Champ `teinture` (boolean) dans le modèle Reservation
- Affiché dans la confirmation et dans l'admin (modal + pilule calendrier "· T")
- **Migration Railway déjà faite** : `ALTER TABLE reservations ADD COLUMN teinture BOOLEAN DEFAULT FALSE`

## Notifications
- **À faire** : mettre en place une notification email ou autre quand un RDV est enregistré
- Outlook SMTP testé mais bloqué (SmtpClientAuthentication disabled)
- Solution recommandée : Gmail avec mot de passe d'application
- Le code de notification a été supprimé — à réimplémenter quand prêt

## Pages
- `/` → landing page
- `/booking` → calendrier custom + créneaux + formulaire → sauvegarde directe en DB
- `/contact` → page contact avec lien Instagram DM (@babeelashes)
- `/confirmation` → résumé RDV + IBAN pour virement acompte 10€
- `/admin` → dashboard admin (agenda mensuel, déplacement + suppression RDV)
- `/admin/login` → login admin

## Stack
- Python 3 + Flask + SQLAlchemy + Gunicorn
- SQLite en dev (`instance/babelash.db`), PostgreSQL en prod (Railway)
- Jinja2 + Tailwind CSS via CDN
- Google Fonts : Playfair Display + Inter

## Modèle Reservation
- Champs : id, name, phone, email, date, time_slot, price, teinture, paid, created_at
- `paid=True` mis automatiquement à la sauvegarde (pas de paiement en ligne)
- Les créneaux passés aujourd'hui sont grisés (fuseau Europe/Brussels via zoneinfo)

## Modèle UnavailableDay
- Table `unavailable_days` : id, date (unique)
- Créée automatiquement via `db.create_all()` — **migration Railway nécessaire** : `CREATE TABLE IF NOT EXISTS unavailable_days (id SERIAL PRIMARY KEY, date DATE NOT NULL UNIQUE);`
- Permet à l'admin de bloquer des journées entières
- Impact : `/api/availability` retourne tous les créneaux à `false`, `/booking` refuse la date, calendrier booking grise le jour

## Lancer le projet (dev)
```bash
venv/bin/python app.py
```
Site local : http://127.0.0.1:5000
- Si port 5000 occupé : désactiver AirPlay Receiver dans Réglages système → Général → AirDrop et Handoff

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
- Fonctions : voir RDV du mois, déplacer un RDV, supprimer un RDV, bloquer/débloquer une journée
- Les RDV avec teinture affichent "· T" sur la pilule et un badge dans le modal
- Jours bloqués : fond rouge pâle + badge "Indisponible" + icône cadenas (visible au survol, toujours visible si bloqué)
- Cliquer sur le cadenas d'un jour le ferme (confirmation si RDV existants) ou le réouvre

## Réseaux sociaux
- TikTok et Instagram affichés sur la landing page
- Lien "Contact" dans la nav → `/contact` (page dédiée avec bouton DM Instagram)
- Instagram : https://instagram.com/babeelashes · TikTok : https://tiktok.com/@babeelashes

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
- Variables Railway actives : SECRET_KEY, ADMIN_PASSWORD, BANK_IBAN, BANK_NAME, DATABASE_URL, FLASK_ENV=production
- Variables à supprimer si pas encore fait : STRIPE_SECRET_KEY, STRIPE_PUBLIC_KEY, STRIPE_WEBHOOK_SECRET, WHATSAPP_NUMBER, ADMIN_EMAIL, MAIL_PASSWORD

### OVH DNS (babeelashes.be)
- `www CNAME → 2t9q5aw4.up.railway.app.`
- `_railway-verify.www TXT → railway-verify=...`
- SSL géré automatiquement par Railway

### Déploiement continu
- Push sur `main` → Railway redéploie automatiquement

## À faire (prochaine session)
- Notification automatique à la propriétaire lors d'un nouveau RDV
  - Outlook SMTP bloqué (SmtpClientAuthentication disabled)
  - → Créer un compte Gmail et utiliser SMTP Gmail avec mot de passe d'application
  - Variables à ajouter : `ADMIN_EMAIL`, `MAIL_PASSWORD`
- **Migration Railway** pour la table `unavailable_days` :
  ```sql
  CREATE TABLE IF NOT EXISTS unavailable_days (id SERIAL PRIMARY KEY, date DATE NOT NULL UNIQUE);
  ```

## Instructions
- Use context7 for up to date documentation
- Use Magic MCP for complex UI components
- Use UI UX Pro Max design system
