import os
import urllib.parse
from datetime import date, timedelta
from decimal import Decimal

import stripe
from dotenv import load_dotenv
from flask import Flask, jsonify, redirect, render_template, request, session, url_for
from functools import wraps
from flask_sqlalchemy import SQLAlchemy

load_dotenv()

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-secret")
database_url = os.getenv("DATABASE_URL", "sqlite:///babelash.db")
if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)
app.config["SQLALCHEMY_DATABASE_URI"] = database_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_PUBLIC_KEY = os.getenv("STRIPE_PUBLIC_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")


# ── Model ────────────────────────────────────────────────────────
class Reservation(db.Model):
    __tablename__ = "reservations"
    id               = db.Column(db.Integer, primary_key=True)
    name             = db.Column(db.String(120), nullable=False)
    phone            = db.Column(db.String(30),  nullable=False)
    email            = db.Column(db.String(120), nullable=True)
    date             = db.Column(db.Date,        nullable=False)
    time_slot        = db.Column(db.String(10),  nullable=False)
    price            = db.Column(db.Numeric(6, 2), nullable=False)
    stripe_session_id = db.Column(db.String(200), nullable=True, unique=True)
    paid             = db.Column(db.Boolean, default=False, nullable=False)
    created_at       = db.Column(db.DateTime, server_default=db.func.now())


# ── Config ───────────────────────────────────────────────────────
OPEN_HOUR     = 10
CLOSE_HOUR    = 18
SLOT_DURATION = 90
PRICE_WEEK    = Decimal("35.00")
PRICE_WEEKEND = Decimal("40.00")
PRICE_PROMO   = Decimal("20.00")
DEPOSIT       = Decimal("10.00")
PROMO_UNTIL   = date(2026, 4, 30)
WHATSAPP_NUMBER = os.getenv("WHATSAPP_NUMBER", "32XXXXXXXXX")
ADMIN_PASSWORD  = os.getenv("ADMIN_PASSWORD", "admin")


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("admin_logged_in"):
            return redirect(url_for("admin_login"))
        return f(*args, **kwargs)
    return decorated


def get_price(booking_date: date) -> Decimal:
    if booking_date <= PROMO_UNTIL:
        return PRICE_PROMO
    return PRICE_WEEKEND if booking_date.weekday() == 6 else PRICE_WEEK


def generate_slots():
    slots = []
    hour, minute = OPEN_HOUR, 0
    while True:
        slots.append(f"{hour:02d}:{minute:02d}")
        minute += SLOT_DURATION
        if minute >= 60:
            hour += minute // 60
            minute = minute % 60
        if hour >= CLOSE_HOUR:
            break
    return slots


TIME_SLOTS = generate_slots()


# ── Routes ───────────────────────────────────────────────────────
@app.route("/")
def index():
    img_dir = os.path.join(app.static_folder, "img")
    VIDEO_EXTS = {".mp4", ".mov", ".webm"}
    all_files = [f for f in os.listdir(img_dir)
                 if f.lower().endswith((".jpg", ".jpeg", ".png", ".webp", ".mp4", ".mov", ".webm"))]
    media = sorted(all_files, key=lambda f: (0 if os.path.splitext(f)[1].lower() in VIDEO_EXTS else 1, f))
    return render_template("index.html", media=media)


@app.route("/booking", methods=["GET", "POST"])
def booking():
    errors = {}
    form_data = {}

    if request.method == "POST":
        name      = request.form.get("name", "").strip()
        phone     = request.form.get("phone", "").strip()
        email     = request.form.get("email", "").strip()
        date_str  = request.form.get("date", "")
        time_slot = request.form.get("time_slot", "")

        form_data = {"name": name, "phone": phone, "email": email,
                     "date": date_str, "time_slot": time_slot}

        if not name:
            errors["name"] = "Nom requis"
        if not phone:
            errors["phone"] = "Téléphone requis"
        if not date_str:
            errors["date"] = "Date requise"
        else:
            try:
                booking_date = date.fromisoformat(date_str)
                if booking_date < date.today():
                    errors["date"] = "La date doit être dans le futur"
            except ValueError:
                errors["date"] = "Date invalide"
        if not time_slot or time_slot not in TIME_SLOTS:
            errors["time_slot"] = "Créneau invalide"

        if not errors:
            price    = get_price(booking_date)
            existing = Reservation.query.filter_by(date=booking_date, time_slot=time_slot, paid=True).first()
            if existing:
                errors["time_slot"] = "Ce créneau est déjà pris"
            else:
                # Store pending booking in session before Stripe redirect
                session["pending_booking"] = {
                    "name": name, "phone": phone, "email": email or "",
                    "date": date_str, "time_slot": time_slot, "price": str(price),
                }
                return redirect(url_for("create_checkout_session"))

    return render_template(
        "booking.html",
        slots=TIME_SLOTS, errors=errors, form_data=form_data,
        min_date=date.today().isoformat(),
        max_date=(date.today() + timedelta(days=60)).isoformat(),
        price_week=PRICE_WEEK, price_weekend=PRICE_WEEKEND,
        price_promo=PRICE_PROMO, promo_until=PROMO_UNTIL,
    )


@app.route("/create-checkout-session")
def create_checkout_session():
    pending = session.get("pending_booking")
    if not pending:
        return redirect(url_for("booking"))

    base_url = request.host_url.rstrip("/")
    try:
        checkout = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{
                "price_data": {
                    "currency": "eur",
                    "product_data": {
                        "name": "Acompte réservation — Babelash",
                        "description": f"Extensions de cils · {pending['date']} à {pending['time_slot']}",
                    },
                    "unit_amount": int(DEPOSIT * 100),
                },
                "quantity": 1,
            }],
            mode="payment",
            customer_email=pending["email"] or None,
            success_url=f"{base_url}/payment-success?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{base_url}/payment-cancel",
        )
        return redirect(checkout.url, code=303)
    except stripe.error.StripeError as e:
        return render_template("payment_error.html", error=str(e)), 500


@app.route("/payment-success")
def payment_success():
    session_id = request.args.get("session_id", "")
    pending    = session.pop("pending_booking", None)

    if not session_id or not pending:
        return redirect(url_for("booking"))

    # Verify payment with Stripe
    try:
        checkout = stripe.checkout.Session.retrieve(session_id)
        if checkout.payment_status != "paid":
            return redirect(url_for("booking"))
    except stripe.error.StripeError:
        return redirect(url_for("booking"))

    booking_date = date.fromisoformat(pending["date"])
    price        = Decimal(pending["price"])

    # Avoid duplicate saves if webhook already ran
    existing = Reservation.query.filter_by(stripe_session_id=session_id).first()
    if not existing:
        db.session.add(Reservation(
            name=pending["name"],
            phone=pending["phone"],
            email=pending["email"] or None,
            date=booking_date,
            time_slot=pending["time_slot"],
            price=price,
            stripe_session_id=session_id,
            paid=True,
        ))
        db.session.commit()

    return redirect(url_for("confirmation",
                            name=pending["name"],
                            date=pending["date"],
                            time=pending["time_slot"],
                            price=str(price)))


@app.route("/payment-cancel")
def payment_cancel():
    return render_template("payment_cancel.html")


@app.route("/webhook", methods=["POST"])
def stripe_webhook():
    payload = request.get_data()
    sig     = request.headers.get("Stripe-Signature", "")

    try:
        event = stripe.Webhook.construct_event(payload, sig, STRIPE_WEBHOOK_SECRET)
    except (ValueError, stripe.error.SignatureVerificationError):
        return "", 400

    if event["type"] == "checkout.session.completed":
        checkout  = event["data"]["object"]
        session_id = checkout["id"]
        meta      = checkout.get("metadata", {})

        # Only process if not already saved via success redirect
        if not Reservation.query.filter_by(stripe_session_id=session_id).first():
            pass  # pending_booking is in Flask session — can't access it in webhook

    return "", 200


@app.route("/api/price")
def api_price():
    try:
        booking_date = date.fromisoformat(request.args.get("date", ""))
        price = get_price(booking_date)
        return jsonify({"price": str(price), "is_promo": booking_date <= PROMO_UNTIL})
    except ValueError:
        return jsonify({"error": "Invalid date"}), 400


@app.route("/api/availability")
def api_availability():
    try:
        from datetime import datetime
        booking_date = date.fromisoformat(request.args.get("date", ""))
        taken = {r.time_slot for r in Reservation.query.filter_by(date=booking_date, paid=True).all()}
        now = datetime.now()
        def is_available(slot):
            if slot in taken:
                return False
            if booking_date == date.today():
                h, m = map(int, slot.split(":"))
                if (now.hour, now.minute) >= (h, m):
                    return False
            return True
        return jsonify({slot: is_available(slot) for slot in TIME_SLOTS})
    except ValueError:
        return jsonify({"error": "Invalid date"}), 400


@app.route("/confirmation")
def confirmation():
    name         = request.args.get("name", "")
    booking_date = request.args.get("date", "")
    time         = request.args.get("time", "")
    price        = request.args.get("price", "")

    message = (f"Bonjour, je viens de réserver chez Babelash.\n"
               f"Nom : {name}\nDate : {booking_date}\nHeure : {time}\n"
               f"Montant : {price}€\n\nMerci de confirmer ma réservation !")
    wa_url = f"https://wa.me/{WHATSAPP_NUMBER}?text={urllib.parse.quote(message)}"

    try:
        remaining = f"{Decimal(price) - DEPOSIT:.2f}"
    except Exception:
        remaining = price

    return render_template("confirmation.html", name=name, booking_date=booking_date,
                           time=time, price=price, remaining=remaining, wa_url=wa_url)


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    error = None
    if request.method == "POST":
        if request.form.get("password") == ADMIN_PASSWORD:
            session["admin_logged_in"] = True
            return redirect(url_for("admin_dashboard"))
        error = "Mot de passe incorrect"
    return render_template("admin/login.html", error=error)


@app.route("/admin/logout")
def admin_logout():
    session.clear()
    return redirect(url_for("admin_login"))


@app.route("/admin")
@login_required
def admin_dashboard():
    return render_template("admin/dashboard.html")


@app.route("/api/admin/reservations")
@login_required
def api_admin_reservations():
    month = request.args.get("month")
    year  = request.args.get("year")
    try:
        y, m = int(year), int(month)
        from calendar import monthrange
        _, days_in_month = monthrange(y, m)
        start = date(y, m, 1)
        end   = date(y, m, days_in_month)
        reservations = Reservation.query.filter(
            Reservation.date >= start,
            Reservation.date <= end,
            Reservation.paid == True,
        ).order_by(Reservation.date, Reservation.time_slot).all()
        return jsonify([{
            "id":        r.id,
            "name":      r.name,
            "phone":     r.phone,
            "email":     r.email or "",
            "date":      r.date.isoformat(),
            "time_slot": r.time_slot,
            "price":     str(r.price),
        } for r in reservations])
    except (ValueError, TypeError):
        return jsonify({"error": "Invalid params"}), 400


@app.route("/api/admin/reservations/<int:reservation_id>", methods=["DELETE"])
@login_required
def api_admin_delete(reservation_id):
    r = Reservation.query.get_or_404(reservation_id)
    db.session.delete(r)
    db.session.commit()
    return jsonify({"ok": True})


with app.app_context():
    db.create_all()

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=os.getenv("FLASK_ENV") != "production")
