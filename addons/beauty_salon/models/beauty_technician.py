# Part of Nails MGM. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models
from odoo.exceptions import ValidationError


class BeautyTechnician(models.Model):
    _name = "beauty.technician"
    _description = "Técnica / Empleada del salón"
    _order = "name"

    name = fields.Char(required=True)
    phone = fields.Char()
    email = fields.Char()
    user_id = fields.Many2one("res.users", string="Usuario vinculado")
    commission_rate = fields.Float(
        string="Comisión (%)",
        default=0.0,
        help="Porcentaje de comisión sobre los servicios realizados.",
    )
    active = fields.Boolean(default=True)
    color = fields.Integer()
    notes = fields.Text(string="Notas")

    appointment_ids = fields.One2many("beauty.appointment", "technician_id")
    appointment_count = fields.Integer(compute="_compute_appointment_count")
    done_amount_total = fields.Monetary(
        string="Total realizado", compute="_compute_done_amount", currency_field="currency_id"
    )
    commission_amount = fields.Monetary(
        string="Comisión estimada", compute="_compute_done_amount", currency_field="currency_id"
    )
    currency_id = fields.Many2one(
        "res.currency", default=lambda self: self.env.company.currency_id
    )

    @api.constrains("commission_rate")
    def _check_commission_rate(self):
        for tech in self:
            if not 0 <= tech.commission_rate <= 100:
                raise ValidationError("La comisión debe estar entre 0 y 100 %.")

    @api.depends("appointment_ids")
    def _compute_appointment_count(self):
        for tech in self:
            tech.appointment_count = len(tech.appointment_ids)

    @api.depends("appointment_ids.state", "appointment_ids.amount_total", "commission_rate")
    def _compute_done_amount(self):
        for tech in self:
            tech.done_amount_total = sum(
                tech.appointment_ids.filtered(lambda a: a.state == "done").mapped(
                    "amount_total"
                )
            )
            tech.commission_amount = tech.done_amount_total * tech.commission_rate / 100.0

    def action_view_appointments(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Citas",
            "res_model": "beauty.appointment",
            "view_mode": "list,form,calendar,kanban",
            "domain": [("technician_id", "=", self.id)],
            "context": {"default_technician_id": self.id},
        }
