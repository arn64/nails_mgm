# Part of Nails MGM. See LICENSE file for full copyright and licensing details.

from datetime import timedelta

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
