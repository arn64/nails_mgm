# Part of Nails MGM. See LICENSE file for full copyright and licensing details.

from datetime import datetime, timedelta

import pytz

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError


class BeautyAppointment(models.Model):
    _name = "beauty.appointment"
    _description = "Cita de uñas / cejas"
    _order = "start_datetime desc"
    _inherit = ["mail.thread", "mail.activity.mixin"]

    name = fields.Char(
        default="Nuevo", required=True, copy=False, readonly=True, tracking=True
    )
    partner_id = fields.Many2one(
        "res.partner",
        string="Clienta",
        required=True,
        tracking=True,
        domain=[("is_company", "=", False)],
    )
    partner_phone = fields.Char(related="partner_id.phone", readonly=True)
    service_ids = fields.Many2many(
        "beauty.service",
        "beauty_appointment_service_rel",
        "appointment_id",
        "service_id",
        string="Servicios",
        required=True,
    )
    technician_id = fields.Many2one(
        "beauty.technician", string="Técnica", required=True, tracking=True, index=True
    )
    start_datetime = fields.Datetime(string="Inicio", required=True, tracking=True)
    duration = fields.Float(
        string="Duración (horas)",
        default=1.0,
        help="Se propone automáticamente sumando los servicios, pero se puede ajustar.",
    )
    end_datetime = fields.Datetime(
        string="Fin", compute="_compute_end_datetime", inverse="_inverse_end_datetime", store=True
    )
    amount_total = fields.Monetary(
        string="Subtotal de servicios",
        compute="_compute_amount_total",
        store=True,
        currency_field="currency_id",
    )
    currency_id = fields.Many2one(
        "res.currency", related="company_id.currency_id", store=True
    )
    state = fields.Selection(
        [
            ("draft", "Borrador"),
            ("confirmed", "Confirmada"),
            ("done", "Realizada"),
            ("cancelled", "Cancelada"),
        ],
        default="draft",
        required=True,
        tracking=True,
        index=True,
    )
    notes = fields.Text(string="Notas")
    sale_order_id = fields.Many2one("sale.order", string="Pedido de venta", readonly=True, copy=False)
    company_id = fields.Many2one(
        "res.company", default=lambda self: self.env.company, required=True
    )
    user_id = fields.Many2one(
        "res.users", default=lambda self: self.env.user, string="Responsable"
    )
    active = fields.Boolean(default=True)
    service_type_display = fields.Char(compute="_compute_service_type_display")

    @api.depends("service_ids", "service_ids.list_price")
    def _compute_amount_total(self):
        for appt in self:
            appt.amount_total = sum(appt.service_ids.mapped("list_price"))

    @api.depends("service_ids")
    def _compute_service_type_display(self):
        labels = dict(self.env["beauty.service"]._fields["service_type"].selection)
        for appt in self:
            types = sorted({labels.get(s.service_type, "") for s in appt.service_ids})
            appt.service_type_display = ", ".join(t for t in types if t)

    @api.depends("start_datetime", "duration")
    def _compute_end_datetime(self):
        for appt in self:
            if appt.start_datetime and appt.duration:
                appt.end_datetime = appt.start_datetime + timedelta(hours=appt.duration)
            else:
                appt.end_datetime = appt.start_datetime

    def _inverse_end_datetime(self):
        for appt in self:
            if appt.start_datetime and appt.end_datetime:
                delta = appt.end_datetime - appt.start_datetime
                appt.duration = max(delta.total_seconds() / 3600.0, 0.0)

    @api.onchange("service_ids")
    def _onchange_service_ids(self):
        self.duration = sum(self.service_ids.mapped("duration")) or 1.0

    @api.constrains(
        "service_ids", "start_datetime", "duration", "end_datetime", "technician_id", "state"
    )
    def _check_schedule(self):
        for appt in self:
            if not appt.service_ids:
                raise ValidationError("La cita debe tener al menos un servicio.")
            if appt.duration <= 0:
                raise ValidationError("La duración de la cita debe ser mayor que cero.")
            if appt.state not in ("confirmed", "done"):
                continue
            if self.search_count([
                ("id", "!=", appt.id),
                ("technician_id", "=", appt.technician_id.id),
                ("state", "in", ("confirmed", "done")),
                ("start_datetime", "<", appt.end_datetime),
                ("end_datetime", ">", appt.start_datetime),
            ]):
                raise ValidationError(
                    "La técnica ya tiene otra cita confirmada o realizada en ese horario."
                )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "Nuevo") == "Nuevo":
                vals["name"] = (
                    self.env["ir.sequence"].next_by_code("beauty.appointment") or "Nuevo"
                )
        appointments = super().create(vals_list)
        if any(not appt.service_ids for appt in appointments):
            raise ValidationError("La cita debe tener al menos un servicio.")
        return appointments

    # --- Botones de estado ---
    def action_confirm(self):
        if any(appt.state != "draft" for appt in self):
            raise UserError("Solo se pueden confirmar citas en borrador.")
        self.write({"state": "confirmed"})

    def action_done(self):
        if any(appt.state != "confirmed" for appt in self):
            raise UserError("Solo se pueden realizar citas confirmadas.")
        self.write({"state": "done"})

    def action_cancel(self):
        if any(appt.state not in ("draft", "confirmed") for appt in self):
            raise UserError("Solo se pueden cancelar citas pendientes.")
        self.write({"state": "cancelled"})

    def action_draft(self):
        if any(appt.state != "cancelled" for appt in self):
            raise UserError("Solo se pueden reabrir citas canceladas.")
        self.write({"state": "draft"})

    # --- Facturación ---
    def _create_sale_order(self):
        self.ensure_one()
        if self.sale_order_id:
            return self.sale_order_id
        if not self.service_ids:
            raise UserError("Añade al menos un servicio antes de crear el pedido.")
        order_lines = []
        for service in self.service_ids:
            product = service._get_sale_product()
            order_lines.append((0, 0, {
                "product_id": product.id,
                "product_uom_id": product.uom_id.id,
                "product_uom_qty": 1.0,
                "price_unit": service.list_price,
                "name": service.name,
            }))
        order = self.env["sale.order"].with_company(self.company_id).create(
            {
                "partner_id": self.partner_id.id,
                "company_id": self.company_id.id,
                "origin": self.name,
                "order_line": order_lines,
            }
        )
        self.sale_order_id = order.id
        self.message_post(body=f"Pedido de venta creado: {order.name}")
        return order

    def action_create_sale_order(self):
        self.ensure_one()
        if self.state not in ("confirmed", "done"):
            raise UserError("Confirma la cita antes de crear el pedido.")
        if self.sale_order_id:
            return self.action_view_sale_order()
        order = self._create_sale_order()
        return {
            "type": "ir.actions.act_window",
            "name": "Pedido de venta",
            "res_model": "sale.order",
            "view_mode": "form",
            "res_id": order.id,
        }

    def action_view_sale_order(self):
        self.ensure_one()
        if not self.sale_order_id:
            raise UserError("Esta cita aún no tiene pedido de venta.")
        return {
            "type": "ir.actions.act_window",
            "name": "Pedido de venta",
            "res_model": "sale.order",
            "view_mode": "form",
            "res_id": self.sale_order_id.id,
        }

    # --- Reserva web pública ---
    # Horario del salón (hora local). Ajusta aquí si cambia el horario.
    BOOKING_TZ = "Europe/Madrid"
    BOOKING_OPEN_HOUR = 9
    BOOKING_CLOSE_HOUR = 17
    BOOKING_SLOT_MINUTES = 30
    BOOKING_DAYS_AHEAD = 14
    BOOKING_MIN_ANTICIPATION_MINUTES = 60

    @api.model
    def _booking_tz(self):
        return pytz.timezone(self.BOOKING_TZ)

    @api.model
    def _booking_duration_for_services(self, services):
        duration = sum(services.mapped("duration")) if services else 0.0
        return duration or 1.0

    @api.model
    def _booking_active_technicians(self, technician_id=None):
        domain = [("active", "=", True)]
        if technician_id:
            domain.append(("id", "=", technician_id))
        return self.env["beauty.technician"].search(domain, order="name")

    def _booking_slot_is_free(self, technician, start_utc, end_utc):
        """True si la técnica no tiene citas (borrador/confirmada/realizada) que solapen."""
        return not self.search_count([
            ("id", "!=", False),
            ("technician_id", "=", technician.id),
            ("state", "in", ("draft", "confirmed", "done")),
            ("start_datetime", "<", end_utc),
            ("end_datetime", ">", start_utc),
        ])

    @api.model
    def get_booking_day_slots(self, day_date, service_ids, technician_id=None):
        """Huecos libres de un día (date) para unos servicios.

        Devuelve lista de dicts: {"start_utc": "YYYY-MM-DD HH:MM:SS",
        "label": "HH:MM", "technician_id": int, "technician_name": str}.
        Horas mostradas en hora local del salón.
        """
        if isinstance(day_date, str):
            day_date = datetime.strptime(day_date, "%Y-%m-%d").date()
        if day_date.weekday() >= 5:  # Lun-Vie
            return []
        services = self.env["beauty.service"].browse(service_ids).exists()
        if not services:
            return []
        duration = self._booking_duration_for_services(services)
        technicians = self._booking_active_technicians(technician_id)
        if not technicians:
            return []

        tz = self._booking_tz()
        now_utc = datetime.now(pytz.utc).replace(tzinfo=None)
        min_start = now_utc + timedelta(minutes=self.BOOKING_MIN_ANTICIPATION_MINUTES)

        slots = []
        cursor_minutes = self.BOOKING_OPEN_HOUR * 60
        close_minutes = self.BOOKING_CLOSE_HOUR * 60
        step = self.BOOKING_SLOT_MINUTES
        while cursor_minutes * 1.0 + duration * 60 <= close_minutes + 1e-6:
            hour, minute = divmod(cursor_minutes, 60)
            local_dt = tz.localize(datetime(
                day_date.year, day_date.month, day_date.day, hour, minute
            ))
            start_utc = local_dt.astimezone(pytz.utc).replace(tzinfo=None)
            end_utc = start_utc + timedelta(hours=duration)
            if start_utc >= min_start:
                chosen = None
                for tech in technicians:
                    if self._booking_slot_is_free(tech, start_utc, end_utc):
                        chosen = tech
                        break
                if chosen:
                    slots.append({
                        "start_utc": start_utc.strftime("%Y-%m-%d %H:%M:%S"),
                        "label": f"{hour:02d}:{minute:02d}",
                        "technician_id": chosen.id,
                        "technician_name": chosen.name,
                    })
            cursor_minutes += step
        return slots

    @api.model
    def get_booking_available_days(self, service_ids, technician_id=None, days_ahead=None):
        """Próximos días laborables con al menos un hueco libre."""
        from datetime import date as date_cls

        days_ahead = days_ahead or self.BOOKING_DAYS_AHEAD
        today = datetime.now(self._booking_tz()).date()
        result = []
        offset = 0
        while len(result) < days_ahead and offset < days_ahead + 14:
            day = today + timedelta(days=offset)
            offset += 1
            if day.weekday() >= 5:
                continue
            slots = self.get_booking_day_slots(day, service_ids, technician_id)
            if slots:
                result.append({
                    "date": day.isoformat(),
                    "label": day.strftime("%d/%m"),
                    "weekday": ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"][day.weekday()],
                    "slots_count": len(slots),
                })
        return result

    @api.model
    def create_public_booking(self, name, phone, email, service_ids,
                              start_utc_str, technician_id=None):
        """Crea y confirma una cita desde la web pública. Devuelve la cita."""
        name = (name or "").strip()
        phone = (phone or "").strip()
        email = (email or "").strip() or False
        if not name:
            raise ValidationError("Indica tu nombre.")
        digits = "".join(c for c in phone if c.isdigit())
        if len(digits) < 6:
            raise ValidationError("Indica un teléfono válido.")
        if email and ("@" not in email or "." not in email):
            raise ValidationError("El correo electrónico no es válido.")
        services = self.env["beauty.service"].browse(service_ids).exists()
        if not services:
            raise ValidationError("Elige al menos un servicio.")
        try:
            start_utc = datetime.strptime(start_utc_str, "%Y-%m-%d %H:%M:%S")
        except (ValueError, TypeError):
            raise ValidationError("El horario elegido no es válido.")
        duration = self._booking_duration_for_services(services)
        end_utc = start_utc + timedelta(hours=duration)

        # No permitir pasado ni fuera de horario Lun-Vie 9-17 (hora local).
        tz = self._booking_tz()
        local_start = pytz.utc.localize(start_utc).astimezone(tz)
        if local_start.weekday() >= 5:
            raise ValidationError("Solo reservamos de lunes a viernes.")
        open_minutes = self.BOOKING_OPEN_HOUR * 60
        close_minutes = self.BOOKING_CLOSE_HOUR * 60
        start_minutes = local_start.hour * 60 + local_start.minute
        if not (open_minutes <= start_minutes
                and start_minutes + duration * 60 <= close_minutes + 1e-6):
            raise ValidationError("Ese horario está fuera del horario del salón (9:00-17:00).")
        if start_utc < datetime.now(pytz.utc).replace(tzinfo=None) + timedelta(
                minutes=self.BOOKING_MIN_ANTICIPATION_MINUTES) - timedelta(minutes=1):
            raise ValidationError("Ese horario ya no está disponible.")

        technicians = self._booking_active_technicians(technician_id)
        if not technicians:
            raise ValidationError("Ahora mismo no hay técnicas disponibles.")
        chosen = None
        if technician_id:
            tech = technicians[:1]
            if tech and self._booking_slot_is_free(tech, start_utc, end_utc):
                chosen = tech
        else:
            for tech in technicians:
                if self._booking_slot_is_free(tech, start_utc, end_utc):
                    chosen = tech
                    break
        if not chosen:
            raise ValidationError("Ese hueco acaba de ocuparse. Elige otro horario.")

        partner = self.env["res.partner"].sudo().search(
            [("phone", "=", phone), ("is_company", "=", False)], limit=1
        )
        if not partner:
            partner = self.env["res.partner"].sudo().search(
                [("phone", "ilike", phone), ("is_company", "=", False)], limit=1
            )
        if partner:
            partner.sudo().write({"name": name, "phone": phone, "email": email or partner.email})
        else:
            partner = self.env["res.partner"].sudo().create({
                "name": name, "phone": phone, "email": email,
                "is_company": False,
            })

        appointment = self.sudo().create({
            "partner_id": partner.id,
            "technician_id": chosen.id,
            "service_ids": [(6, 0, services.ids)],
            "start_datetime": start_utc_str,
            "duration": duration,
        })
        try:
            appointment.action_confirm()
        except (UserError, ValidationError):
            appointment.sudo().unlink()
            raise ValidationError("Ese hueco acaba de ocuparse. Elige otro horario.")
        return appointment
