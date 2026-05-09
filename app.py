import os
from datetime import date, timedelta
from decimal import Decimal

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


# ── Model ────────────────────────────────────────────────────────
class Reservation(db.Model):
    __tablename__ = "reservations"
    id         = db.Column(db.Integer, primary_key=True)
    name       = db.Column(db.String(120), nullable=False)
    phone      = db.Column(db.String(30),  nullable=False)
    email      = db.Column(db.String(120), nullable=True)
    date       = db.Column(db.Date,        nullable=False)
    time_slot  = db.Column(db.String(10),  nullable=False)
    price      = db.Column(db.Numeric(6, 2), nullable=False)
    teinture   = db.Column(db.Boolean, default=False, nullable=True)
    paid       = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, server_default=db.func.now())


# ── Config ───────────────────────────────────────────────────────
OPEN_HOUR     = 10
CLOSE_HOUR    = 18
SLOT_DURATION = 90
PRICE_WEEK    = Decimal("35.00")
PRICE_WEEKEND = Decimal("40.00")
PRICE_PROMO   = Decimal("20.00")
DEPOSIT         = Decimal("10.00")
PRICE_TEINTURE  = Decimal("5.00")
PROMO_UNTIL     = date(2026, 4, 30)
BANK_IBAN        = os.getenv("BANK_IBAN", "BE94 3632 6175 1914")
BANK_NAME        = os.getenv("BANK_NAME", "Babeelashes")
ADMIN_PASSWORD   = os.getenv("ADMIN_PASSWORD", "admin")




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
    promo_active = date.today() <= PROMO_UNTIL
    return render_template("index.html", media=media, promo_active=promo_active)


@app.route("/contact")
def contact():
    return render_template("contact.html")


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
                if booking_date <= date.today():
                    errors["date"] = "La réservation doit être effectuée au moins 24h à l'avance"
            except ValueError:
                errors["date"] = "Date invalide"
        if not time_slot or time_slot not in TIME_SLOTS:
            errors["time_slot"] = "Créneau invalide"

        if not errors:
            teinture = request.form.get("teinture") == "1"
            price    = get_price(booking_date) + (PRICE_TEINTURE if teinture else Decimal("0"))
            existing = Reservation.query.filter_by(date=booking_date, time_slot=time_slot, paid=True).first()
            if existing:
                errors["time_slot"] = "Ce créneau est déjà pris"
            else:
                db.session.add(Reservation(
                    name=name, phone=phone, email=email or None,
                    date=booking_date, time_slot=time_slot, price=price,
                    teinture=teinture, paid=True,
                ))
                db.session.commit()
                return redirect(url_for("confirmation",
                                        name=name, date=date_str,
                                        time=time_slot, price=str(price),
                                        teinture="1" if teinture else "0"))

    return render_template(
        "booking.html",
        slots=TIME_SLOTS, errors=errors, form_data=form_data,
        min_date=(date.today() + timedelta(days=1)).isoformat(),
        max_date=(date.today() + timedelta(days=60)).isoformat(),
        price_week=PRICE_WEEK, price_weekend=PRICE_WEEKEND,
    )


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
        from zoneinfo import ZoneInfo
        BRUSSELS = ZoneInfo("Europe/Brussels")
        now_brussels = datetime.now(BRUSSELS)
        today_brussels = now_brussels.date()

        booking_date = date.fromisoformat(request.args.get("date", ""))
        taken = {r.time_slot for r in Reservation.query.filter_by(date=booking_date, paid=True).all()}

        def is_available(slot):
            if slot in taken:
                return False
            if booking_date == today_brussels:
                h, m = map(int, slot.split(":"))
                if (now_brussels.hour, now_brussels.minute) >= (h, m):
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
    teinture     = request.args.get("teinture") == "1"

    try:
        remaining = f"{Decimal(price) - DEPOSIT:.2f}"
    except Exception:
        remaining = price

    return render_template("confirmation.html",
                           name=name, booking_date=booking_date,
                           time=time, price=price, remaining=remaining,
                           iban=BANK_IBAN, bank_name=BANK_NAME,
                           deposit=str(DEPOSIT), teinture=teinture)


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
            "teinture":  bool(r.teinture),
        } for r in reservations])
    except (ValueError, TypeError):
        return jsonify({"error": "Invalid params"}), 400


@app.route("/api/admin/reservations/<int:reservation_id>", methods=["PATCH"])
@login_required
def api_admin_update(reservation_id):
    r = Reservation.query.get_or_404(reservation_id)
    data      = request.get_json()
    new_date  = data.get("date", "")
    new_slot  = data.get("time_slot", "")
    try:
        booking_date = date.fromisoformat(new_date)
    except ValueError:
        return jsonify({"error": "Date invalide"}), 400
    if new_slot not in TIME_SLOTS:
        return jsonify({"error": "Créneau invalide"}), 400
    conflict = Reservation.query.filter(
        Reservation.date == booking_date,
        Reservation.time_slot == new_slot,
        Reservation.paid == True,
        Reservation.id != reservation_id,
    ).first()
    if conflict:
        return jsonify({"error": "Ce créneau est déjà pris"}), 409
    r.date      = booking_date
    r.time_slot = new_slot
    db.session.commit()
    return jsonify({"ok": True})


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
