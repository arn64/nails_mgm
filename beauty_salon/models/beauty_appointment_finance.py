# Part of Nails MGM. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare


class BeautyAppointmentLine(models.Model):
    _name = "beauty.appointment.line"
    _description = "Precio acordado de un servicio de la cita"
    _order = "id"

    appointment_id = fields.Many2one(
        "beauty.appointment", required=True, ondelete="cascade", index=True
    )
    service_id = fields.Many2one("beauty.service", required=True, ondelete="restrict")
    name = fields.Char(string="Servicio acordado", required=True)
    price_unit = fields.Monetary(
        string="Precio acordado", required=True, currency_field="currency_id"
    )
    currency_id = fields.Many2one(
        "res.currency", related="appointment_id.currency_id", store=True
    )

    @api.constrains("price_unit")
    def _check_price_unit(self):
        for line in self:
            if line.price_unit < 0:
                raise ValidationError("El precio acordado no puede ser negativo.")


class BeautyAppointmentPayment(models.Model):
    _name = "beauty.appointment.payment"
    _description = "Cobro o devolución de una cita"
    _rec_name = "appointment_id"
    _order = "payment_date desc, id desc"

    appointment_id = fields.Many2one(
        "beauty.appointment", string="Cita", required=True, ondelete="restrict", index=True
    )
    payment_date = fields.Date(
        string="Fecha", required=True, default=fields.Date.context_today, index=True
    )
    kind = fields.Selection(
        [("payment", "Cobro"), ("refund", "Devolución")],
        string="Tipo", required=True, default="payment", index=True,
    )
    state = fields.Selection(
        [("posted", "Registrado"), ("void", "Anulado")],
        string="Estado", required=True, default="posted", readonly=True, index=True,
    )
    method = fields.Selection(
        [("cash", "Efectivo"), ("card", "Tarjeta"),
         ("transfer", "Transferencia"), ("other", "Otro")],
        string="Método", required=True, default="cash", index=True,
    )
    amount = fields.Monetary(
        string="Importe", required=True, currency_field="currency_id"
    )
    signed_amount = fields.Monetary(
        string="Cobrado neto", compute="_compute_signed_amount", store=True,
        currency_field="currency_id",
    )
    reference = fields.Char(string="Referencia")
    void_date = fields.Datetime(string="Anulado el", readonly=True, copy=False)
    void_user_id = fields.Many2one(
        "res.users", string="Anulado por", readonly=True, copy=False
    )
    currency_id = fields.Many2one(
        "res.currency", related="appointment_id.currency_id", store=True
    )
    company_id = fields.Many2one(
        "res.company", related="appointment_id.company_id", store=True
    )
    partner_id = fields.Many2one(
        "res.partner", related="appointment_id.partner_id", store=True
    )
    technician_id = fields.Many2one(
        "beauty.technician", related="appointment_id.technician_id", store=True
    )
    appointment_state = fields.Selection(
        related="appointment_id.state", string="Estado de la cita", store=True
    )

    @api.depends("kind", "amount", "state")
    def _compute_signed_amount(self):
        for payment in self:
            if payment.state == "void":
                payment.signed_amount = 0.0
            elif payment.kind == "refund":
                payment.signed_amount = -payment.amount
            else:
                payment.signed_amount = payment.amount

    def action_void(self):
        self.check_access("read")
        for appointment in self.mapped("appointment_id").sorted("id"):
            self.env.cr.execute(
                "SELECT id FROM beauty_appointment WHERE id = %s FOR UPDATE",
                [appointment.id],
            )
            self.invalidate_recordset(["state"])
            if any(payment.state != "posted" for payment in self):
                raise UserError("Solo se pueden anular movimientos registrados.")
            remaining = self.search([
                ("appointment_id", "=", appointment.id),
                ("state", "=", "posted"),
                ("id", "not in", self.ids),
            ])
            balance = sum(remaining.mapped("signed_amount"))
            rounding = appointment.currency_id.rounding
            if float_compare(balance, 0.0, precision_rounding=rounding) < 0:
                raise ValidationError(
                    "La anulación dejaría devoluciones sin cobros suficientes."
                )
        self.sudo().write({
            "state": "void",
            "void_date": fields.Datetime.now(),
            "void_user_id": self.env.user.id,
        })

    @api.model_create_multi
    def create(self, vals_list):
        balances = {}
        for vals in vals_list:
            if ("signed_amount" in vals or "void_date" in vals or "void_user_id" in vals
                    or vals.get("state") not in (None, "posted")):
                raise ValidationError("El estado y el cobrado neto se calculan automáticamente.")
            vals.pop("state", None)
            vals.setdefault("appointment_id", self.env.context.get("default_appointment_id"))
            vals.setdefault("kind", self.env.context.get("default_kind", "payment"))
            if not vals["appointment_id"]:
                raise ValidationError("Selecciona una cita válida.")
            appointment = self.env["beauty.appointment"].browse(
                vals["appointment_id"]
            ).exists()
            if not appointment:
                raise ValidationError("Selecciona una cita válida.")
            if not appointment.price_locked and appointment.state in ("confirmed", "done"):
                appointment._lock_agreed_prices()

            kind = vals.get("kind")
            amount = appointment.currency_id.round(vals.get("amount") or 0.0)
            vals["amount"] = amount
            rounding = appointment.currency_id.rounding
            if kind not in ("payment", "refund"):
                raise ValidationError("El tipo de movimiento no es válido.")
            if float_compare(amount, 0.0, precision_rounding=rounding) <= 0:
                raise ValidationError("El importe debe ser mayor que cero.")

            if appointment.id not in balances:
                self.env.cr.execute(
                    "SELECT id FROM beauty_appointment WHERE id = %s FOR UPDATE",
                    [appointment.id],
                )
                appointment.invalidate_recordset(["state"])
                balances[appointment.id] = sum(
                    self.search([("appointment_id", "=", appointment.id)]).mapped(
                        "signed_amount"
                    )
                )
            balance = balances[appointment.id]
            if kind == "payment":
                if appointment.state not in ("confirmed", "done"):
                    raise UserError("Solo se pueden cobrar citas confirmadas o realizadas.")
                balances[appointment.id] += amount
            else:
                if float_compare(amount, balance, precision_rounding=rounding) > 0:
                    raise ValidationError("La devolución supera el importe cobrado neto.")
                balances[appointment.id] -= amount
        return super().create(vals_list)
