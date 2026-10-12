# Part of Nails MGM. See LICENSE file for full copyright and licensing details.

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
        values = self._booking_values(
            service_ids=_to_int_list(kw.get("service_ids")),
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
        return request.render("beauty_salon.beauty_booking_ok", {
            "appointment": appointment,
            "services": appointment.service_ids,
        })
