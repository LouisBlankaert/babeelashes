import os
import shutil
import subprocess
import uuid
from datetime import date, timedelta
from decimal import Decimal

import resend

from dotenv import load_dotenv
from flask import Flask, jsonify, redirect, render_template, request, send_from_directory, session, url_for
from functools import wraps
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import inspect
from PIL import Image, ImageOps
from werkzeug.utils import secure_filename

load_dotenv()

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-secret")
database_url = os.getenv("DATABASE_URL", "sqlite:///babelash.db")
if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)
app.config["SQLALCHEMY_DATABASE_URI"] = database_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
# Les vidéos filmées au téléphone pèsent vite 50-100 Mo
app.config["MAX_CONTENT_LENGTH"] = 300 * 1024 * 1024

db = SQLAlchemy(app)


# ── Model ────────────────────────────────────────────────────────
class Reservation(db.Model):
    __tablename__ = "reservations"
    id         = db.Column(db.Integer, primary_key=True)
    name       = db.Column(db.String(120), nullable=False)
    instagram  = db.Column(db.String(120), nullable=False)
    phone      = db.Column(db.String(30),  nullable=True)
    email      = db.Column(db.String(120), nullable=True)
    date       = db.Column(db.Date,        nullable=False)
    time_slot  = db.Column(db.String(10),  nullable=False)
    price      = db.Column(db.Numeric(6, 2), nullable=False)
    teinture   = db.Column(db.Boolean, default=False, nullable=True)
    paid       = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, server_default=db.func.now())


class UnavailableDay(db.Model):
    __tablename__ = "unavailable_days"
    id   = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False, unique=True)


class UnavailableSlot(db.Model):
    """Un seul créneau bloqué (ex. le 14/10 à 15:00), le reste de la journée reste ouvert."""
    __tablename__ = "unavailable_slots"
    __table_args__ = (db.UniqueConstraint("date", "time_slot"),)
    id        = db.Column(db.Integer, primary_key=True)
    date      = db.Column(db.Date, nullable=False)
    time_slot = db.Column(db.String(10), nullable=False)


class Media(db.Model):
    """Photo ou vidéo du carrousel de la page d'accueil, gérée depuis /admin/medias."""
    __tablename__ = "media"
    id         = db.Column(db.Integer, primary_key=True)
    filename   = db.Column(db.String(255), nullable=False, unique=True)
    position   = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, server_default=db.func.now())

    @property
    def ext(self):
        return os.path.splitext(self.filename)[1].lower().lstrip(".")

    @property
    def is_video(self):
        return self.ext in VIDEO_EXTS

    @property
    def url(self):
        return url_for("media_file", filename=self.filename)


class Promotion(db.Model):
    """Prix spécial sur une période (Halloween, Noël…), créé par la cliente dans /admin/promos.
    S'applique aux rendez-vous dont la date tombe entre start_date et end_date inclus."""
    __tablename__ = "promotions"
    id                 = db.Column(db.Integer, primary_key=True)
    name               = db.Column(db.String(80), nullable=False)
    price              = db.Column(db.Numeric(6, 2), nullable=False)
    start_date         = db.Column(db.Date, nullable=False)
    end_date           = db.Column(db.Date, nullable=False)
    teinture_included  = db.Column(db.Boolean, default=False, nullable=False)

    def to_dict(self):
        return {
            "id": self.id, "name": self.name, "price": short_amount(self.price),
            "start_date": self.start_date.isoformat(), "end_date": self.end_date.isoformat(),
            "teinture_included": self.teinture_included,
        }


# ── Config ───────────────────────────────────────────────────────
OPEN_HOUR     = 11
CLOSE_HOUR    = 18
SLOT_DURATION = 90
SLOTS         = ["11:00", "12:15", "13:30", "15:00", "16:15", "17:30"]
PRICE_WEEK    = Decimal("45.00")
PRICE_WEEKEND = Decimal("50.00")
DEPOSIT         = Decimal("10.00")
PRICE_TEINTURE  = Decimal("5.00")
BANK_IBAN        = os.getenv("BANK_IBAN", "BE58 6503 2990 2279")
BANK_NAME        = os.getenv("BANK_NAME", "Babeelashes")
ADMIN_PASSWORD   = os.getenv("ADMIN_PASSWORD", "admin")
ADMIN_EMAIL      = os.getenv("ADMIN_EMAIL", "")
resend.api_key   = os.getenv("RESEND_API_KEY", "")

# Fichiers envoyés depuis l'admin. En prod, UPLOAD_DIR pointe sur un volume
# persistant, sinon chaque redéploiement effacerait les photos.
UPLOAD_DIR  = os.getenv("UPLOAD_DIR", os.path.join(app.instance_path, "uploads"))
IMAGE_EXTS  = {"jpg", "jpeg", "png", "webp", "gif"}
VIDEO_EXTS  = {"mp4", "mov", "webm"}
MAX_SIDE    = 1600   # px, côté le plus long des photos après envoi


def optimize_image(src, dest):
    """Photo de téléphone (4000 px, 5 Mo) → JPEG 1600 px léger, remis à l'endroit."""
    with Image.open(src) as img:
        img = ImageOps.exif_transpose(img).convert("RGB")
        img.thumbnail((MAX_SIDE, MAX_SIDE))
        img.save(dest, "JPEG", quality=85, optimize=True)


def convert_video(src, dest):
    """Vidéo iPhone (HEVC, illisible sur Chrome/Android) → MP4 H.264 lu partout.
    Sans le son : le carrousel joue les vidéos en muet."""
    scale = "scale='if(gt(iw,ih),min(1280,iw),-2)':'if(gt(iw,ih),-2,min(1280,ih))'"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", src, "-an",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "24", "-pix_fmt", "yuv420p",
         "-vf", scale, "-movflags", "+faststart", dest],
        check=True, timeout=280,
    )




def short_amount(amount):
    """Decimal("40.00") → "40", Decimal("39.50") → "39.5" """
    return f"{Decimal(amount).normalize():f}"


MOIS_FR = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet",
           "août", "septembre", "octobre", "novembre", "décembre"]


@app.context_processor
def inject_promos():
    """Bandeau promo en haut de toutes les pages publiques."""
    return {"promos": visible_promos(), "tomorrow": date.today() + timedelta(days=1)}


@app.template_filter("date_fr")
def date_fr(d):
    """date(2026, 10, 30) → « 30 octobre »"""
    return f"{d.day} {MOIS_FR[d.month - 1]}"


@app.template_filter("euros")
def euros(amount):
    """Decimal("40.00") → « 40€ », Decimal("39.50") → « 39,50€ »"""
    return short_amount(amount).replace(".", ",") + "€"


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("admin_logged_in"):
            return redirect(url_for("admin_login"))
        return f(*args, **kwargs)
    return decorated


def send_booking_notification(name, instagram, phone, email, booking_date, time_slot, price, teinture):
    if not ADMIN_EMAIL or not resend.api_key:
        return
    promo = get_promo(booking_date)
    teinture_line = ""
    if teinture:
        extra = "incluse dans la promo" if promo and promo.teinture_included else "+5€"
        teinture_line = f"<br><strong>Teinture :</strong> Oui ({extra})"
    if promo:
        teinture_line += f"<br><strong>Promo :</strong> {promo.name}"
    phone_line = f"<br><strong>Téléphone :</strong> {phone}" if phone else ""
    email_line = f"<br><strong>Email :</strong> {email}" if email else ""
    try:
        resend.Emails.send({
            "from": "onboarding@resend.dev",
            "to": ADMIN_EMAIL,
            "subject": f"Nouveau RDV — {name} le {booking_date.strftime('%d/%m/%Y')} à {time_slot}",
            "html": f"""
            <h2>Nouveau rendez-vous Babelash</h2>
            <p>
              <strong>Nom :</strong> {name}<br>
              <strong>Instagram :</strong> @{instagram}{phone_line}{email_line}<br>
              <strong>Date :</strong> {booking_date.strftime('%d/%m/%Y')}<br>
              <strong>Heure :</strong> {time_slot}{teinture_line}<br>
              <strong>Prix total :</strong> {price}€<br>
              <strong>Acompte attendu :</strong> 10€ — IBAN {BANK_IBAN}
            </p>
            """,
        })
    except Exception:
        pass


def get_promo(booking_date: date):
    """Promo qui couvre cette date ; si deux se chevauchent, la moins chère."""
    return Promotion.query.filter(
        Promotion.start_date <= booking_date,
        Promotion.end_date >= booking_date,
    ).order_by(Promotion.price, Promotion.id).first()


def get_price(booking_date: date, teinture: bool = False) -> Decimal:
    """Prix total du rendez-vous, teinture comprise."""
    promo = get_promo(booking_date)
    if promo:
        base = promo.price
        if promo.teinture_included:
            return base
    else:
        base = PRICE_WEEKEND if booking_date.weekday() == 6 else PRICE_WEEK
    return base + (PRICE_TEINTURE if teinture else Decimal("0"))


JOURS_FR = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]


def next_free_slot():
    """Premier créneau libre à partir de demain, pour la page d'accueil. None si tout est pris."""
    start = date.today() + timedelta(days=1)
    end   = date.today() + timedelta(days=60)
    closed = {d.date for d in UnavailableDay.query.filter(UnavailableDay.date.between(start, end))}
    taken  = {(r.date, r.time_slot) for r in Reservation.query.filter(
        Reservation.date.between(start, end), Reservation.paid == True)}
    taken |= {(s.date, s.time_slot) for s in UnavailableSlot.query.filter(
        UnavailableSlot.date.between(start, end))}
    d = start
    while d <= end:
        if d not in closed:
            for slot in TIME_SLOTS:
                if (d, slot) not in taken:
                    day = "Demain" if d == start else f"{JOURS_FR[d.weekday()]} {d.day} {MOIS_FR[d.month - 1]}"
                    return f"{day} · {slot}"
        d += timedelta(days=1)
    return None


def visible_promos():
    """Promos à afficher sur la page d'accueil : celles qu'on peut encore réserver
    (dates de demain à +60 jours, comme le calendrier de réservation)."""
    tomorrow = date.today() + timedelta(days=1)
    return Promotion.query.filter(
        Promotion.end_date >= tomorrow,
        Promotion.start_date <= date.today() + timedelta(days=60),
    ).order_by(Promotion.start_date).all()


def generate_slots():
    return list(SLOTS)


TIME_SLOTS = generate_slots()


# ── Routes ───────────────────────────────────────────────────────
@app.route("/")
def index():
    media = Media.query.order_by(Media.position, Media.id).all()
    return render_template("index.html", media=media, next_slot=next_free_slot(),
                           price_week=PRICE_WEEK, price_weekend=PRICE_WEEKEND,
                           price_teinture=PRICE_TEINTURE, deposit=DEPOSIT)


@app.route("/media/<path:filename>")
def media_file(filename):
    return send_from_directory(UPLOAD_DIR, filename, max_age=60 * 60 * 24 * 30)


@app.route("/contact")
def contact():
    return render_template("contact.html")


@app.route("/booking", methods=["GET", "POST"])
def booking():
    errors = {}
    form_data = {}

    if request.method == "POST":
        name      = request.form.get("name", "").strip()
        instagram = request.form.get("instagram", "").strip().lstrip("@")
        phone     = request.form.get("phone", "").strip()
        email     = request.form.get("email", "").strip()
        date_str  = request.form.get("date", "")
        time_slot = request.form.get("time_slot", "")

        form_data = {"name": name, "instagram": instagram, "phone": phone, "email": email,
                     "date": date_str, "time_slot": time_slot}

        if not name:
            errors["name"] = "Nom requis"
        if not instagram:
            errors["instagram"] = "Pseudo Instagram requis"
        if not date_str:
            errors["date"] = "Date requise"
        else:
            try:
                booking_date = date.fromisoformat(date_str)
                if booking_date <= date.today():
                    errors["date"] = "La réservation doit être effectuée au moins 24h à l'avance"
                elif UnavailableDay.query.filter_by(date=booking_date).first():
                    errors["date"] = "Cette journée n'est pas disponible"
            except ValueError:
                errors["date"] = "Date invalide"
        if not time_slot or time_slot not in TIME_SLOTS:
            errors["time_slot"] = "Créneau invalide"
        elif "date" not in errors and UnavailableSlot.query.filter_by(date=booking_date, time_slot=time_slot).first():
            errors["time_slot"] = "Ce créneau n'est pas disponible"

        if not errors:
            promo    = get_promo(booking_date)
            teinture = request.form.get("teinture") == "1" or bool(promo and promo.teinture_included)
            price    = get_price(booking_date, teinture)
            existing = Reservation.query.filter_by(date=booking_date, time_slot=time_slot, paid=True).first()
            if existing:
                errors["time_slot"] = "Ce créneau est déjà pris"
            else:
                db.session.add(Reservation(
                    name=name, instagram=instagram, phone=phone or None, email=email or None,
                    date=booking_date, time_slot=time_slot, price=price,
                    teinture=teinture, paid=True,
                ))
                db.session.commit()
                send_booking_notification(name, instagram, phone, email, booking_date, time_slot, price, teinture)
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
        promo = get_promo(booking_date)
        return jsonify({
            "price": str(get_price(booking_date)),
            "is_promo": promo is not None,
            "promo_name": promo.name if promo else None,
            "teinture_included": bool(promo and promo.teinture_included),
        })
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
        if UnavailableDay.query.filter_by(date=booking_date).first():
            return jsonify({slot: False for slot in TIME_SLOTS})
        taken = {r.time_slot for r in Reservation.query.filter_by(date=booking_date, paid=True).all()}
        taken |= {s.time_slot for s in UnavailableSlot.query.filter_by(date=booking_date).all()}

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
    try:
        promo = get_promo(date.fromisoformat(booking_date))
    except ValueError:
        promo = None

    return render_template("confirmation.html",
                           name=name, booking_date=booking_date,
                           time=time, price=price, remaining=remaining,
                           iban=BANK_IBAN, bank_name=BANK_NAME,
                           deposit=str(DEPOSIT), teinture=teinture, promo=promo)


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
    return render_template("admin/dashboard.html", slots=TIME_SLOTS)


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
            "instagram": r.instagram,
            "phone":     r.phone or "",
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


@app.route("/api/admin/unavailable")
@login_required
def api_admin_unavailable_get():
    month = request.args.get("month")
    year  = request.args.get("year")
    try:
        from calendar import monthrange
        y, m = int(year), int(month)
        _, days_in_month = monthrange(y, m)
        days = UnavailableDay.query.filter(
            UnavailableDay.date >= date(y, m, 1),
            UnavailableDay.date <= date(y, m, days_in_month),
        ).all()
        return jsonify([d.date.isoformat() for d in days])
    except (ValueError, TypeError):
        return jsonify({"error": "Invalid params"}), 400


@app.route("/api/admin/unavailable", methods=["POST"])
@login_required
def api_admin_unavailable_add():
    data = request.get_json()
    try:
        d = date.fromisoformat(data.get("date", ""))
    except (ValueError, AttributeError):
        return jsonify({"error": "Date invalide"}), 400
    if not UnavailableDay.query.filter_by(date=d).first():
        db.session.add(UnavailableDay(date=d))
        db.session.commit()
    return jsonify({"ok": True})


@app.route("/api/admin/unavailable/<date_str>", methods=["DELETE"])
@login_required
def api_admin_unavailable_delete(date_str):
    try:
        d = date.fromisoformat(date_str)
    except ValueError:
        return jsonify({"error": "Date invalide"}), 400
    row = UnavailableDay.query.filter_by(date=d).first()
    if row:
        db.session.delete(row)
        db.session.commit()
    return jsonify({"ok": True})


@app.route("/api/admin/unavailable-slots")
@login_required
def api_admin_unavailable_slots_get():
    month = request.args.get("month")
    year  = request.args.get("year")
    try:
        from calendar import monthrange
        y, m = int(year), int(month)
        _, days_in_month = monthrange(y, m)
        slots = UnavailableSlot.query.filter(
            UnavailableSlot.date >= date(y, m, 1),
            UnavailableSlot.date <= date(y, m, days_in_month),
        ).all()
        return jsonify([{"date": s.date.isoformat(), "time_slot": s.time_slot} for s in slots])
    except (ValueError, TypeError):
        return jsonify({"error": "Invalid params"}), 400


@app.route("/api/admin/unavailable-slots", methods=["POST"])
@login_required
def api_admin_unavailable_slot_add():
    data = request.get_json() or {}
    try:
        d = date.fromisoformat(data.get("date", ""))
    except ValueError:
        return jsonify({"error": "Date invalide"}), 400
    slot = data.get("time_slot", "")
    if slot not in TIME_SLOTS:
        return jsonify({"error": "Créneau invalide"}), 400
    if not UnavailableSlot.query.filter_by(date=d, time_slot=slot).first():
        db.session.add(UnavailableSlot(date=d, time_slot=slot))
        db.session.commit()
    return jsonify({"ok": True})


@app.route("/api/admin/unavailable-slots", methods=["DELETE"])
@login_required
def api_admin_unavailable_slot_delete():
    data = request.get_json() or {}
    try:
        d = date.fromisoformat(data.get("date", ""))
    except ValueError:
        return jsonify({"error": "Date invalide"}), 400
    row = UnavailableSlot.query.filter_by(date=d, time_slot=data.get("time_slot", "")).first()
    if row:
        db.session.delete(row)
        db.session.commit()
    return jsonify({"ok": True})


@app.route("/api/unavailable-days")
def api_unavailable_days():
    month = request.args.get("month")
    year  = request.args.get("year")
    try:
        from calendar import monthrange
        y, m = int(year), int(month)
        _, days_in_month = monthrange(y, m)
        days = UnavailableDay.query.filter(
            UnavailableDay.date >= date(y, m, 1),
            UnavailableDay.date <= date(y, m, days_in_month),
        ).all()
        return jsonify([d.date.isoformat() for d in days])
    except (ValueError, TypeError):
        return jsonify({"error": "Invalid params"}), 400


@app.route("/admin/medias")
@login_required
def admin_medias():
    return render_template("admin/medias.html")


@app.route("/api/admin/media")
@login_required
def api_admin_media_list():
    media = Media.query.order_by(Media.position, Media.id).all()
    return jsonify([{"id": m.id, "url": m.url, "is_video": m.is_video} for m in media])


@app.route("/api/admin/media", methods=["POST"])
@login_required
def api_admin_media_upload():
    file = request.files.get("file")
    if not file or not file.filename:
        return jsonify({"error": "Aucun fichier reçu"}), 400
    ext = os.path.splitext(file.filename)[1].lower().lstrip(".")
    if ext not in IMAGE_EXTS | VIDEO_EXTS:
        return jsonify({"error": f"Format .{ext} non accepté (photos JPG/PNG/WEBP, vidéos MP4/MOV)"}), 400

    # Nom unique : deux « IMG_0001.jpg » venant de deux téléphones ne s'écrasent pas
    base = secure_filename(os.path.splitext(file.filename)[0])[:60] or "media"
    stem = f"{uuid.uuid4().hex[:8]}-{base}"
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    raw = os.path.join(UPLOAD_DIR, f".tmp-{stem}.{ext}")
    file.save(raw)

    is_video = ext in VIDEO_EXTS
    filename = f"{stem}.{'mp4' if is_video else 'jpg'}"
    try:
        (convert_video if is_video else optimize_image)(raw, os.path.join(UPLOAD_DIR, filename))
    except Exception:
        app.logger.exception("Conversion impossible de %s", file.filename)
        return jsonify({"error": "Ce fichier n'a pas pu être lu"}), 400
    finally:
        os.remove(raw)

    last = db.session.query(db.func.max(Media.position)).scalar()
    m = Media(filename=filename, position=(last or 0) + 1)
    db.session.add(m)
    db.session.commit()
    return jsonify({"id": m.id, "url": m.url, "is_video": m.is_video})


@app.route("/api/admin/media/order", methods=["POST"])
@login_required
def api_admin_media_order():
    ids = (request.get_json() or {}).get("ids", [])
    media = {m.id: m for m in Media.query.all()}
    for position, media_id in enumerate(ids):
        if media_id in media:
            media[media_id].position = position
    db.session.commit()
    return jsonify({"ok": True})


@app.route("/api/admin/media/<int:media_id>", methods=["DELETE"])
@login_required
def api_admin_media_delete(media_id):
    m = Media.query.get_or_404(media_id)
    path = os.path.join(UPLOAD_DIR, m.filename)
    db.session.delete(m)
    db.session.commit()
    if os.path.exists(path):
        os.remove(path)
    return jsonify({"ok": True})


@app.route("/admin/promos")
@login_required
def admin_promos():
    return render_template("admin/promos.html", price_week=short_amount(PRICE_WEEK),
                           price_weekend=short_amount(PRICE_WEEKEND), today=date.today().isoformat())


def promo_from_json(promo, data):
    """Remplit une promo depuis le formulaire de l'admin ; renvoie un message d'erreur ou None."""
    name = (data.get("name") or "").strip()
    if not name:
        return "Donne un nom à la promo (ex. Halloween)"
    try:
        price = Decimal(str(data.get("price", "")).replace(",", "."))
    except Exception:
        return "Prix invalide"
    if not Decimal("0") < price < Decimal("1000"):
        return "Prix invalide"
    try:
        start = date.fromisoformat(data.get("start_date", ""))
        end   = date.fromisoformat(data.get("end_date", ""))
    except (ValueError, TypeError):
        return "Dates invalides"
    if end < start:
        return "La date de fin est avant la date de début"
    promo.name, promo.price = name[:80], price
    promo.start_date, promo.end_date = start, end
    promo.teinture_included = bool(data.get("teinture_included"))
    return None


@app.route("/api/admin/promos")
@login_required
def api_admin_promos():
    promos = Promotion.query.order_by(Promotion.start_date.desc()).all()
    return jsonify([p.to_dict() for p in promos])


@app.route("/api/admin/promos", methods=["POST"])
@login_required
def api_admin_promo_add():
    promo = Promotion()
    error = promo_from_json(promo, request.get_json() or {})
    if error:
        return jsonify({"error": error}), 400
    db.session.add(promo)
    db.session.commit()
    return jsonify(promo.to_dict())


@app.route("/api/admin/promos/<int:promo_id>", methods=["PUT"])
@login_required
def api_admin_promo_update(promo_id):
    promo = Promotion.query.get_or_404(promo_id)
    error = promo_from_json(promo, request.get_json() or {})
    if error:
        db.session.rollback()
        return jsonify({"error": error}), 400
    db.session.commit()
    return jsonify(promo.to_dict())


@app.route("/api/admin/promos/<int:promo_id>", methods=["DELETE"])
@login_required
def api_admin_promo_delete(promo_id):
    db.session.delete(Promotion.query.get_or_404(promo_id))
    db.session.commit()
    return jsonify({"ok": True})


@app.errorhandler(413)
def too_large(_):
    return jsonify({"error": "Fichier trop lourd (300 Mo maximum)"}), 413


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


def seed_media():
    """Premier lancement : reprend les photos/vidéos de static/img dans le carrousel géré."""
    src_dir = os.path.join(app.static_folder, "img")
    files = [f for f in os.listdir(src_dir)
             if os.path.splitext(f)[1].lower().lstrip(".") in IMAGE_EXTS | VIDEO_EXTS]
    # Même ordre qu'avant : vidéos d'abord, puis photos, par nom
    files.sort(key=lambda f: (0 if os.path.splitext(f)[1].lower().lstrip(".") in VIDEO_EXTS else 1, f))
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    for position, f in enumerate(files):
        shutil.copy2(os.path.join(src_dir, f), os.path.join(UPLOAD_DIR, f))
        db.session.add(Media(filename=f, position=position))
    db.session.commit()


with app.app_context():
    first_run = not inspect(db.engine).has_table("media")
    no_promos_yet = not inspect(db.engine).has_table("promotions")
    db.create_all()
    if first_run:
        seed_media()
    if no_promos_yet:
        # Première promo, demandée avant que la page Promos existe
        db.session.add(Promotion(name="Halloween", price=Decimal("40.00"),
                                 start_date=date(2026, 10, 16), end_date=date(2026, 10, 30),
                                 teinture_included=True))
        db.session.commit()
    # Gunicorn --preload : les workers ne doivent pas hériter des connexions du process parent
    db.engine.dispose()

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=os.getenv("FLASK_ENV") != "production")
