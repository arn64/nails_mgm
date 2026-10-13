# Part of Nails MGM. See LICENSE file for full copyright and licensing details.

import base64
from urllib.parse import quote

from odoo import http
from odoo.exceptions import ValidationError
from odoo.http import request


def _to_int_list(values):
    if not values:
        return []
    if isinstance(values, str):
        values = [values]
    result = []
    for value in values:
        try:
            result.append(int(value))
        except (ValueError, TypeError):
            continue
    return result


class BeautyBookingController(http.Controller):

    def _booking_values(self, service_ids=None, technician_id=None,
                        day=None, start_utc=None, name="", phone="", email=""):
        Appointment = request.env["beauty.appointment"].sudo()
        Service = request.env["beauty.service"].sudo()
        Technician = request.env["beauty.technician"].sudo()
        services = Service.search([("active", "=", True)], order="service_type, name")
        technicians = Technician.search([("active", "=", True)], order="name")
        service_ids = [s for s in (service_ids or []) if s in services.ids]
        if technician_id and technician_id not in technicians.ids:
            technician_id = None

        days, slots, selected_services = [], [], Service.browse(service_ids)
        if service_ids:
            days = Appointment.get_booking_available_days(service_ids, technician_id)
            if day:
                slots = Appointment.get_booking_day_slots(day, service_ids, technician_id)
            elif days:
                day = days[0]["date"]
                slots = Appointment.get_booking_day_slots(day, service_ids, technician_id)

        duration = (
            Appointment._booking_duration_for_services(selected_services)
            if service_ids else 0.0
        )
        return {
            "services": services,
            "technicians": technicians,
            "service_ids": service_ids,
            "technician_id": technician_id,
            "days": days,
            "day": day,
            "slots": slots,
            "start_utc": start_utc,
            "duration": duration,
            "booking_name": name,
            "booking_phone": phone,
            "booking_email": email,
            "error": None,
        }

    @http.route("/reservar", type="http", auth="public", website=True, methods=["GET"])
    def booking_page(self, **kw):
        raw_ids = request.httprequest.args.getlist("service_ids") or kw.get("service_ids")
        values = self._booking_values(
            service_ids=_to_int_list(raw_ids),
            technician_id=int(kw["technician_id"]) if str(kw.get("technician_id") or "").isdigit() else None,
            day=kw.get("day"),
            start_utc=kw.get("start_utc"),
            name=kw.get("name", ""),
            phone=kw.get("phone", ""),
            email=kw.get("email", ""),
        )
        return request.render("beauty_salon.beauty_booking_page", values)

    @http.route("/reservar/huecos", type="jsonrpc", auth="public", website=True, methods=["POST"])
    def booking_slots(self, service_ids=None, technician_id=None, day=None):
        service_ids = _to_int_list(service_ids)
        if technician_id:
            try:
                technician_id = int(technician_id)
            except (ValueError, TypeError):
                technician_id = None
        Appointment = request.env["beauty.appointment"].sudo()
        if not service_ids:
            return {"days": [], "slots": [], "day": day}
        days = Appointment.get_booking_available_days(service_ids, technician_id)
        if not days:
            return {"days": [], "slots": [], "day": day}
        if not day or not any(d["date"] == day for d in days):
            # Sin día (primera selección de servicio) o día ya sin huecos:
            # posicionarse en el primer día con disponibilidad.
            day = days[0]["date"]
        slots = Appointment.get_booking_day_slots(day, service_ids, technician_id)
        return {"days": days, "slots": slots, "day": day}

    @http.route("/reservar/confirmar", type="http", auth="public", website=True,
                methods=["POST"], csrf=True)
    def booking_confirm(self, **post):
        service_ids = _to_int_list(post.get("service_ids"))
        technician_id = (
            int(post["technician_id"])
            if str(post.get("technician_id") or "").isdigit() else None
        )
        values = self._booking_values(
            service_ids=service_ids,
            technician_id=technician_id,
            day=post.get("day"),
            start_utc=post.get("start_utc"),
            name=post.get("name", ""),
            phone=post.get("phone", ""),
            email=post.get("email", ""),
        )
        if not service_ids:
            values["error"] = "Elige al menos un servicio."
            return request.render("beauty_salon.beauty_booking_page", values)
        if not post.get("start_utc"):
            values["error"] = "Elige un día y una hora disponibles."
            return request.render("beauty_salon.beauty_booking_page", values)
        try:
            appointment = request.env["beauty.appointment"].sudo().create_public_booking(
                name=post.get("name", ""),
                phone=post.get("phone", ""),
                email=post.get("email", ""),
                service_ids=service_ids,
                start_utc_str=post.get("start_utc"),
                technician_id=technician_id,
            )
        except ValidationError as err:
            values["error"] = str(err).replace("None - ", "")
            return request.render("beauty_salon.beauty_booking_page", values)
        salon_number = "".join(
            c for c in (
                request.env["ir.config_parameter"].sudo().get_param(
                    "beauty_salon.whatsapp_number", ""
                ) or ""
            ) if c.isdigit()
        )
        whatsapp_url = None
        if salon_number:
            text = (
                f"Hola {appointment.company_id.name or 'salón'}, "
                f"soy {appointment.partner_id.name} y confirmo mi reserva "
                f"{appointment.name} de {appointment.service_names_display}."
            )
            whatsapp_url = f"https://wa.me/{salon_number}?text={quote(text)}"
        return request.render("beauty_salon.beauty_booking_ok", {
            "appointment": appointment,
            "services": appointment.service_ids,
            "whatsapp_url": whatsapp_url,
        })

    @http.route("/reservar/catalogo", type="http", auth="public", website=True, methods=["GET"])
    def booking_catalog(self, **kw):
        """Dosier de servicios con foto y descripción."""
        Service = request.env["beauty.service"].sudo()
        services = Service.search([("active", "=", True)], order="service_type, name")
        raw_ids = request.httprequest.args.getlist("service_ids") or kw.get("service_ids")
        service_ids = [s for s in _to_int_list(raw_ids) if s in services.ids]
        back_url = "/reservar" + "".join(
            f"{'?' if i == 0 else '&'}service_ids={s}"
            for i, s in enumerate(service_ids)
        )
        return request.render("beauty_salon.beauty_booking_catalog", {
            "services": services,
            "service_ids": service_ids,
            "back_url": back_url,
        })

    @http.route("/reservar/mis-reservas", type="http", auth="public", website=True, methods=["GET"])
    def booking_mine(self, **kw):
        """Consulta de reservas por teléfono (campo obligatorio)."""
        phone = (kw.get("phone") or "").strip()
        digits = "".join(c for c in phone if c.isdigit())
        appointments, error = [], None
        if "phone" in kw:
            if len(digits) < 6:
                error = "Indica un teléfono válido para buscar tus reservas."
            else:
                Partner = request.env["res.partner"].sudo()
                partners = Partner.search(
                    [("is_company", "=", False), ("phone", "!=", False)]
                ).filtered(
                    lambda p: "".join(c for c in (p.phone or "") if c.isdigit()) == digits
                    or digits in "".join(c for c in (p.phone or "") if c.isdigit())
                )
                if not partners:
                    error = "No encontramos reservas con ese teléfono."
                else:
                    appointments = request.env["beauty.appointment"].sudo().search(
                        [("partner_id", "in", partners.ids)],
                        order="start_datetime desc",
                        limit=50,
                    )
                    if not appointments:
                        error = "No encontramos reservas con ese teléfono."
        return request.render("beauty_salon.beauty_booking_mine", {
            "phone": phone,
            "appointments": appointments,
            "error": error,
        })

    @http.route("/reservar/servicio/<int:service_id>/imagen", type="http", auth="public")
    def booking_service_image(self, service_id):
        """Foto del servicio; si no tiene, imagen por defecto del salón."""
        service = request.env["beauty.service"].sudo().browse(service_id).exists()
        if service and service.image:
            raw = base64.b64decode(service.image)
            ctype = "image/jpeg" if raw[:2] == b"\xff\xd8" else "image/png"
            return request.make_response(
                raw,
                headers=[("Content-Type", ctype), ("Cache-Control", "public, max-age=86400")],
            )
        return request.redirect("/beauty_salon/static/src/img/logo-256.png", code=302)
