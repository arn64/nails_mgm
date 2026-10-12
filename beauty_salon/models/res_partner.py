# Part of Nails MGM. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    allergies = fields.Text(string="Alergias", groups="base.group_user")
    beauty_preferences = fields.Text(
        string="Preferencias de belleza", groups="base.group_user"
    )
    appointment_ids = fields.One2many(
        "beauty.appointment", "partner_id", string="Citas", groups="base.group_user"
    )
    appointment_count = fields.Integer(
        string="Nº citas", compute="_compute_beauty_stats", groups="base.group_user"
    )
    beauty_last_visit = fields.Datetime(
        string="Última visita", compute="_compute_beauty_stats", groups="base.group_user"
    )

    @api.depends("appointment_ids", "appointment_ids.start_datetime", "appointment_ids.state")
    def _compute_beauty_stats(self):
        for partner in self:
            appts = partner.appointment_ids.sorted("start_datetime", reverse=True)
            partner.appointment_count = len(appts)
            visits = appts.filtered(lambda a: a.state == "done")
            partner.beauty_last_visit = visits[:1].start_datetime if visits else False

    def action_view_beauty_appointments(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Citas",
            "res_model": "beauty.appointment",
            "view_mode": "list,form,calendar,kanban",
            "domain": [("partner_id", "=", self.id)],
            "context": {"default_partner_id": self.id},
        }
