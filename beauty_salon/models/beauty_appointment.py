# Part of Nails MGM. See LICENSE file for full copyright and licensing details.

import logging
from datetime import datetime, timedelta

import pytz
import requests
from markupsafe import Markup

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class BeautyAppointment(models.Model):
    _name = "beauty.appointment"
    _description = "Cita de uñas / cejas"
    _order = "create_date desc, id desc"
    _inherit = ["mail.thread", "mail.activity.mixin"]

    name = fields.Char(
        string="Referencia",
        default="Nuevo", required=True, copy=False, readonly=True, tracking=True
    )
    partner_id = fields.Many2one(
        "res.partner",
        string="Clienta",
        required=True,
        tracking=True,
        domain=[("is_company", "=", False)],
    )
    partner_phone = fields.Char(string="Teléfono", related="partner_id.phone", readonly=True)
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
        help="Precio actual del catálogo en borrador; después, precio acordado de la cita.",
    )
    price_locked = fields.Boolean(string="Precio acordado fijado", readonly=True, copy=False)
    price_line_ids = fields.One2many(
        "beauty.appointment.line", "appointment_id", string="Precios acordados", copy=False
    )
    payment_ids = fields.One2many(
        "beauty.appointment.payment", "appointment_id", string="Cobros y devoluciones", copy=False
    )
    amount_paid = fields.Monetary(
        string="Cobrado neto", compute="_compute_payment_amounts", store=True,
        currency_field="currency_id",
    )
    amount_due = fields.Monetary(
        string="Pendiente de cobro", compute="_compute_payment_amounts", store=True,
        currency_field="currency_id",
    )
    amount_not_refunded = fields.Monetary(
        string="Cobrado no devuelto", compute="_compute_payment_amounts", store=True,
        currency_field="currency_id",
    )
    currency_id = fields.Many2one(
        "res.currency", related="company_id.currency_id", store=True
    )
    state = fields.Selection(
        [
            ("draft", "Borrador"),
            ("to_confirm", "Por confirmar"),
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
    active = fields.Boolean(string="Activo", default=True)
    service_type_display = fields.Char(compute="_compute_service_type_display")
    service_names_display = fields.Char(
        string="Servicios (texto)", compute="_compute_service_names_display"
    )
    booking_local_display = fields.Char(
        string="Horario (zona de la técnica)",
        compute="_compute_booking_local_display",
    )
    technician_notify_email = fields.Char(
        string="Email de aviso",
        compute="_compute_technician_notify_email",
        help="Email de la técnica o, si no tiene, de su usuario vinculado.",
    )

    @api.depends(
        "service_ids", "service_ids.list_price", "price_locked",
        "price_line_ids", "price_line_ids.price_unit",
    )
    def _compute_amount_total(self):
        for appt in self:
            amount = sum(
                appt.price_line_ids.mapped("price_unit")
                if appt.price_locked else appt.service_ids.mapped("list_price")
            )
            appt.amount_total = appt.currency_id.round(amount) if appt.currency_id else amount

    @api.depends("payment_ids", "payment_ids.signed_amount", "amount_total", "state")
    def _compute_payment_amounts(self):
        for appt in self:
            paid = sum(appt.payment_ids.mapped("signed_amount"))
            appt.amount_paid = appt.currency_id.round(paid) if appt.currency_id else paid
            due = max(appt.amount_total - appt.amount_paid, 0.0)
            appt.amount_due = (
                (appt.currency_id.round(due) if appt.currency_id else due)
                if appt.state in ("confirmed", "done") else 0.0
            )
            appt.amount_not_refunded = (
                max(appt.amount_paid, 0.0) if appt.state == "cancelled" else 0.0
            )

    @api.depends("service_ids")
    def _compute_service_type_display(self):
        labels = dict(self.env["beauty.service"]._fields["service_type"].selection)
        for appt in self:
            types = sorted({labels.get(s.service_type, "") for s in appt.service_ids})
            appt.service_type_display = ", ".join(t for t in types if t)

    @api.depends(
        "service_ids", "service_ids.name", "price_locked",
        "price_line_ids", "price_line_ids.name",
    )
    def _compute_service_names_display(self):
        for appt in self:
            appt.service_names_display = ", ".join(
                appt.price_line_ids.mapped("name")
                if appt.price_locked else appt.service_ids.mapped("name")
            )

    @api.depends("start_datetime", "end_datetime", "technician_id", "technician_id.tz")
    def _compute_booking_local_display(self):
        for appt in self:
            if not appt.start_datetime:
                appt.booking_local_display = ""
                continue
            tz = appt._booking_tz_for_technician(appt.technician_id)
            start = pytz.utc.localize(appt.start_datetime).astimezone(tz)
            end = (
                pytz.utc.localize(appt.end_datetime).astimezone(tz)
                if appt.end_datetime else None
            )

            def fmt(dt):
                suffix = "am" if dt.hour < 12 else "pm"
                return f"{dt.hour % 12 or 12}:{dt.minute:02d} {suffix}"

            text = f"{start.strftime('%d/%m/%Y')} {fmt(start)}"
            if end:
                text += f" – {fmt(end)}"
            appt.booking_local_display = f"{text}"

    @api.depends("technician_id", "technician_id.email", "technician_id.user_id.email")
    def _compute_technician_notify_email(self):
        for appt in self:
            appt.technician_notify_email = (
                appt.technician_id.email or appt.technician_id.user_id.email or False
            )

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

    @api.constrains("start_datetime", "technician_id", "state")
    def _check_booking_hours(self):
        """El inicio debe caer en horario del salón (también manual).

        Evita citas de madrugada por error. Solo se exige el inicio en
        ventana (el fin puede extenderse a criterio del personal).
        """
        for appt in self:
            if appt.state == "cancelled" or not appt.start_datetime:
                continue
            tz = appt._booking_tz_for_technician(appt.technician_id)
            local = pytz.utc.localize(appt.start_datetime).astimezone(tz)
            start_min = local.hour * 60 + local.minute
            if not any(w0 <= start_min <= w1 for w0, w1 in self.BOOKING_WINDOWS):
                raise ValidationError(
                    f"El inicio debe estar en el horario del salón ({self.BOOKING_HOURS_LABEL})."
                )

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
            if vals.get("price_locked") or vals.get("price_line_ids"):
                raise UserError("El precio acordado se fija al solicitar o confirmar la cita.")
            vals.pop("price_locked", None)
            vals.pop("price_line_ids", None)
            if vals.get("name", "Nuevo") == "Nuevo":
                vals["name"] = (
                    self.env["ir.sequence"].next_by_code("beauty.appointment") or "Nuevo"
                )
        appointments = super().create(vals_list)
        if any(not appt.service_ids for appt in appointments):
            raise ValidationError("La cita debe tener al menos un servicio.")
        appointments.filtered(
            lambda appt: appt.state in ("to_confirm", "confirmed", "done", "cancelled")
        )._lock_agreed_prices()
        return appointments

    def write(self, vals):
        if "price_locked" in vals or "price_line_ids" in vals:
            raise UserError("El precio acordado se fija al solicitar o confirmar la cita.")
        if "service_ids" in vals and any(appt.price_locked for appt in self):
            raise UserError("Los servicios de una cita con precio acordado no se pueden cambiar.")
        if "company_id" in vals and any(appt.price_locked for appt in self):
            raise UserError("No se puede cambiar la compañía de una cita con precio acordado.")
        result = super().write(vals)
        if vals.get("state") in ("to_confirm", "confirmed", "done"):
            self.filtered(lambda appt: not appt.price_locked)._lock_agreed_prices()
        return result

    def _lock_agreed_prices(self):
        for appt in self.filtered(lambda appt: not appt.price_locked):
            if not appt.service_ids:
                raise ValidationError("La cita debe tener al menos un servicio.")
            lines = [fields.Command.create({
                "service_id": service.id,
                "name": service.name,
                "price_unit": service.list_price,
            }) for service in appt.service_ids]
            super(BeautyAppointment, appt.sudo()).write({
                "price_line_ids": lines,
                "price_locked": True,
            })

    # --- Botones de estado ---
    # Flujo: borrador -> por confirmar (reserva del cliente) -> confirmada
    # (solo la confirma la técnica) o cancelada. Por atajo interno también
    # se puede confirmar directo desde borrador.
    def action_request_confirmation(self):
        if any(appt.state != "draft" for appt in self):
            raise UserError("Solo se puede solicitar confirmación en borrador.")
        self.write({"state": "to_confirm"})
        self._notify_technician_email()
        self._notify_technician_internal(
            "Nueva solicitud de reserva",
            "Hay una nueva reserva por revisar y confirmar.",
            with_activity=False,
        )

    def action_confirm(self):
        if any(appt.state not in ("draft", "to_confirm") for appt in self):
            raise UserError("Solo se pueden confirmar citas pendientes.")
        self.write({"state": "confirmed"})
        self._notify_technician_internal(
            "Cita confirmada",
            "La cita quedó confirmada. Revisa los detalles.",
        )
        self._send_whatsapp_confirmation()

    def _notify_technician_email(self):
        """Avisa por correo a la técnica al confirmar la cita.

        Nunca bloquea la confirmación: sin email de técnica o sin
        servidor configurado, la cita queda confirmada igual.
        """
        template = self.env.ref(
            "beauty_salon.beauty_appointment_technician_email",
            raise_if_not_found=False,
        )
        if not template:
            return
        for appt in self.sudo():
            if not appt.technician_notify_email:
                _logger.debug("Aviso técnica omitido %s: sin email", appt.name)
                continue
            try:
                mail_id = template.send_mail(appt.id, force_send=False)
                _logger.info("Aviso técnica %s: mail %s", appt.name, mail_id)
            except Exception as err:  # noqa: BLE001 - el aviso no bloquea
                _logger.warning("No se pudo avisar a la técnica %s: %s", appt.name, err)

    @api.model
    def cron_mark_past_done(self):
        """Marca como realizadas las citas confirmadas ya finalizadas."""
        past = self.search([
            ("state", "=", "confirmed"),
            ("end_datetime", "<", fields.Datetime.now()),
        ])
        if past:
            past.write({"state": "done"})
            _logger.info("Citas marcadas como realizadas: %s", past.mapped("name"))
        return past

    def _notify_technician_internal(self, title="Cita confirmada",
                                     intro="La cita quedó confirmada. Revisa los detalles.",
                                     with_activity=True):
        """Notificación en Odoo a la técnica (+ actividad opcional)."""
        for appt in self:
            partners = appt.technician_id.user_id.partner_id
            appt.message_post(
                body=Markup(
                    f"<b>{title}:</b> {intro}<br/>"
                    f"<b>{appt.service_names_display}</b> "
                    f"para <b>{appt.partner_id.name}</b> "
                    f"({appt.booking_local_display})."
                ),
                partner_ids=partners.ids if partners else [],
                subtype_xmlid="mail.mt_comment",
            )
            if not with_activity:
                continue
            responsible = appt.technician_id.user_id or appt.user_id
            try:
                appt.activity_schedule(
                    "mail.mail_activity_data_call",
                    date_deadline=appt.start_datetime.date()
                    if appt.start_datetime else False,
                    summary=f"Atender cita {appt.name} – {appt.partner_id.name}",
                    note=(
                        f"Servicios: {appt.service_names_display}\n"
                        f"Horario: {appt.booking_local_display}\n"
                        f"Teléfono: {appt.partner_id.phone or '-'}"
                    ),
                    user_id=responsible.id if responsible else False,
                )
            except Exception as err:  # noqa: BLE001 - no bloquea
                _logger.warning(
                    "No se pudo crear la actividad de %s: %s", appt.name, err
                )

    @api.model
    def _booking_local_display_short(self, display):
        """Horario sin la zona entre paréntesis (para mensajes cortos)."""
        import re

        return re.sub(r"\s*\([^)]*\)$", "", display or "")

    @api.model
    def _whatsapp_digits(self, phone):
        """Dígitos para wa.me / API. En Cuba el móvil local de 8 dígitos
        que empieza por 5 se completa con el código 53."""
        digits = "".join(c for c in (phone or "") if c.isdigit())
        if len(digits) == 8 and digits.startswith("5"):
            digits = "53" + digits
        return digits

    def _send_whatsapp_confirmation(self):
        """Envía por WhatsApp (API de Meta) el aviso de cita confirmada.

        Requiere configurar en Parámetros del sistema:
        beauty_salon.whatsapp_token y beauty_salon.whatsapp_phone_id.
        Sin configuración se omite en silencio. Nunca bloquea.
        """
        params = self.env["ir.config_parameter"].sudo()
        token = (params.get_param("beauty_salon.whatsapp_token", "") or "").strip()
        phone_id = (params.get_param("beauty_salon.whatsapp_phone_id", "") or "").strip()
        if not token or not phone_id:
            _logger.debug("WhatsApp sin configurar; aviso omitido.")
            return
        for appt in self:
            digits = self._whatsapp_digits(appt.partner_id.phone)
            if len(digits) < 10:
                _logger.warning("WhatsApp omitido %s: teléfono inválido.", appt.name)
                continue
            text = (
                f"Hola {appt.partner_id.name}, tu cita {appt.name} de "
                f"{appt.service_names_display} quedó confirmada: "
                f"{self._booking_local_display_short(appt.booking_local_display)}. "
                f"¡Te esperamos!"
            )
            try:
                response = requests.post(
                    f"https://graph.facebook.com/v22.0/{phone_id}/messages",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "messaging_product": "whatsapp",
                        "to": digits,
                        "type": "text",
                        "text": {"body": text},
                    },
                    timeout=15,
                )
                if response.status_code >= 400:
                    _logger.warning(
                        "WhatsApp falló %s: %s %s",
                        appt.name, response.status_code, response.text[:200],
                    )
                else:
                    _logger.info("WhatsApp enviado %s.", appt.name)
                    appt.message_post(
                        body="Aviso de confirmación enviado por WhatsApp.",
                        subtype_xmlid="mail.mt_note",
                    )
            except Exception as err:  # noqa: BLE001 - no bloquea
                _logger.warning("WhatsApp error %s: %s", appt.name, err)

    def action_done(self):
        if any(appt.state != "confirmed" for appt in self):
            raise UserError("Solo se pueden realizar citas confirmadas.")
        self.write({"state": "done"})

    def action_cancel(self):
        if any(appt.state not in ("draft", "to_confirm", "confirmed") for appt in self):
            raise UserError("Solo se pueden cancelar citas pendientes.")
        self.write({"state": "cancelled"})

    def action_draft(self):
        if any(appt.state != "cancelled" for appt in self):
            raise UserError("Solo se pueden reabrir citas canceladas.")
        self.write({"state": "draft"})

    def _action_register_payment(self, kind):
        self.ensure_one()
        if kind == "payment" and self.state not in ("confirmed", "done"):
            raise UserError("Confirma la cita antes de registrar un cobro.")
        if kind == "refund" and self.amount_paid <= 0:
            raise UserError("Esta cita no tiene un cobro pendiente de devolver.")
        return {
            "type": "ir.actions.act_window",
            "name": "Registrar cobro" if kind == "payment" else "Registrar devolución",
            "res_model": "beauty.appointment.payment",
            "view_mode": "form",
            "view_id": self.env.ref("beauty_salon.view_beauty_appointment_payment_form").id,
            "target": "new",
            "context": {
                "default_appointment_id": self.id,
                "default_kind": kind,
                "default_amount": self.amount_due if kind == "payment" else self.amount_paid,
            },
        }

    def action_register_payment(self):
        return self._action_register_payment("payment")

    def action_register_refund(self):
        return self._action_register_payment("refund")

    # --- Facturación ---
    def _create_sale_order(self):
        self.ensure_one()
        if self.sale_order_id:
            return self.sale_order_id
        if not self.service_ids:
            raise UserError("Añade al menos un servicio antes de crear el pedido.")
        if not self.price_locked:
            self._lock_agreed_prices()
        order_lines = []
        for line in self.price_line_ids:
            service = line.service_id
            product = service._get_sale_product()
            order_lines.append((0, 0, {
                "product_id": product.id,
                "product_uom_id": product.uom_id.id,
                "product_uom_qty": 1.0,
                "price_unit": line.price_unit,
                "name": line.name,
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

    # --- WhatsApp (gratuito, un clic) ---
    def action_open_whatsapp(self):
        """Abre el chat de WhatsApp con la clienta con texto ya redactado."""
        self.ensure_one()
        from urllib.parse import quote

        digits = self._whatsapp_digits(self.partner_id.phone)
        if len(digits) < 6:
            raise UserError("La clienta no tiene un teléfono válido para WhatsApp.")
        text = (
            f"Hola {self.partner_id.name}, te escribimos de "
            f"{self.company_id.name or 'el salón'} por tu reserva {self.name} "
            f"de {self.service_names_display} "
            f"({self._booking_local_display_short(self.booking_local_display)})."
        )
        return {
            "type": "ir.actions.act_url",
            "url": f"https://wa.me/{digits}?text={quote(text)}",
            "target": "new",
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
    # Horario del salón (hora local). Ventanas en minutos desde medianoche.
    # Mañana 10:00-11:30 am y tarde 1:00-5:00 pm. Ajusta aquí si cambia.
    BOOKING_TZ = "America/Havana"
    BOOKING_WINDOWS = [(10 * 60, 11 * 60 + 30), (13 * 60, 17 * 60)]
    BOOKING_HOURS_LABEL = "10:00–11:30 am y 1:00–5:00 pm"
    # Ventana 0 = mañana, ventana 1 = tarde (índices de BOOKING_WINDOWS).
    BOOKING_SCHEDULE_WINDOWS = {"morning": (0,), "afternoon": (1,), "both": (0, 1)}
    BOOKING_SLOT_MINUTES = 30
    BOOKING_DAYS_AHEAD = 14
    BOOKING_MIN_ANTICIPATION_MINUTES = 60

    @api.model
    def _booking_windows_for_services(self, services):
        """Ventanas permitidas según el turno de los servicios elegidos.

        Si solo se elige un servicio de mañana, no se muestra la tarde
        y viceversa. Con varios servicios se unen los turnos.
        """
        indexes = set()
        for service in services:
            indexes.update(self.BOOKING_SCHEDULE_WINDOWS.get(service.schedule or "both", (0, 1)))
        return [self.BOOKING_WINDOWS[i] for i in sorted(indexes)] or list(self.BOOKING_WINDOWS)

    @api.model
    def _booking_format_label(self, hour, minute):
        """Hora normal 12h con am/pm: 10:00 am, 1:30 pm."""
        suffix = "am" if hour < 12 else "pm"
        hour12 = hour % 12 or 12
        return f"{hour12}:{minute:02d} {suffix}"

    @api.model
    def _booking_slot_in_hours(self, start_minutes, duration, services=None):
        end_minutes = start_minutes + duration * 60
        windows = (
            self._booking_windows_for_services(services)
            if services else self.BOOKING_WINDOWS
        )
        return any(
            win_start <= start_minutes and end_minutes <= win_end + 1e-6
            for win_start, win_end in windows
        )

    @api.model
    def _booking_tz(self):
        return pytz.timezone(self.BOOKING_TZ)

    @api.model
    def _booking_tz_for_technician(self, technician):
        """Zona horaria de la técnica (o la del salón si no tiene)."""
        name = (technician.tz if technician else None) or self.BOOKING_TZ
        try:
            return pytz.timezone(name)
        except pytz.UnknownTimeZoneError:
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
        services = self.env["beauty.service"].browse(service_ids).exists()
        if not services:
            return []
        duration = self._booking_duration_for_services(services)
        technicians = self._booking_active_technicians(technician_id)
        if not technicians:
            return []

        if technician_id and len(technicians) == 1:
            tz = self._booking_tz_for_technician(technicians[:1])
        else:
            tz = self._booking_tz()
        now_utc = datetime.now(pytz.utc).replace(tzinfo=None)
        min_start = now_utc + timedelta(minutes=self.BOOKING_MIN_ANTICIPATION_MINUTES)

        slots = []
        step = self.BOOKING_SLOT_MINUTES
        for win_start, win_end in self._booking_windows_for_services(services):
            cursor_minutes = win_start
            while cursor_minutes * 1.0 + duration * 60 <= win_end + 1e-6:
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
                            "label": self._booking_format_label(hour, minute),
                            "technician_id": chosen.id,
                            "technician_name": chosen.name,
                        })
                cursor_minutes += step
        slots.sort(key=lambda s: s["start_utc"])
        return slots

    @api.model
    def get_booking_available_days(self, service_ids, technician_id=None, days_ahead=None):
        """Próximos días con al menos un hueco libre, incluidos fines de semana."""
        days_ahead = days_ahead or self.BOOKING_DAYS_AHEAD
        today = datetime.now(self._booking_tz()).date()
        result = []
        offset = 0
        while len(result) < days_ahead and offset < days_ahead + 14:
            day = today + timedelta(days=offset)
            offset += 1
            slots = self.get_booking_day_slots(day, service_ids, technician_id)
            if slots:
                result.append({
                    "date": day.isoformat(),
                    "label": day.strftime("%d/%m"),
                    "weekday": ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"][day.weekday()],
                    "is_weekend": day.weekday() >= 5,
                    "slots_count": len(slots),
                })
        return result

    @api.model
    def create_public_booking(self, name, phone, email, service_ids,
                              start_utc_str, technician_id=None):
        """Crea una solicitud de cita desde la web pública. Devuelve la cita."""
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

        # No permitir pasado ni fuera de horario (se valida en la zona
        # de la técnica una vez asignada).
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

        # Ventanas en la zona horaria de la técnica asignada.
        tz = self._booking_tz_for_technician(chosen)
        local_start = pytz.utc.localize(start_utc).astimezone(tz)
        start_minutes = local_start.hour * 60 + local_start.minute
        if not self._booking_slot_in_hours(start_minutes, duration, services):
            raise ValidationError(
                f"Ese horario está fuera del horario del salón ({self.BOOKING_HOURS_LABEL})."
            )

        # Reutiliza la ficha solo si coincide nombre y teléfono: con el mismo
        # teléfono pero otro nombre se crea una ficha nueva para no renombrar
        # (y con ello "cambiar el nombre" de) las citas de otra clienta.
        Partner = self.env["res.partner"].sudo()
        candidates = Partner.search(
            [("phone", "ilike", phone), ("is_company", "=", False)]
        ).filtered(
            lambda p: "".join(c for c in (p.phone or "") if c.isdigit()) == digits
        )
        same = candidates.filtered(
            lambda p: (p.name or "").strip().casefold() == name.casefold()
        )
        if same:
            partner = same[0]
            if email and partner.email != email:
                partner.write({"email": email})
        else:
            partner = Partner.create({
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
        # La reserva web queda "por confirmar": solo la técnica la confirma.
        try:
            appointment.action_request_confirmation()
        except (UserError, ValidationError):
            appointment.sudo().unlink()
            raise ValidationError("No se pudo registrar tu reserva. Inténtalo de nuevo.")
        return appointment
