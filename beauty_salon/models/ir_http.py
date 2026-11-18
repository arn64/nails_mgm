# Part of Nails MGM. See LICENSE file for full copyright and licensing details.

from odoo import api, models


class IrHttp(models.AbstractModel):
    _inherit = "ir.http"

    @api.model
    def session_info(self):
        info = super().session_info()
        value = self.env["ir.config_parameter"].sudo().get_param(
            "beauty_salon.cuba_tz_display_correction", default="True"
        )
        info["beauty_salon_cuba_tz_display_correction"] = (
            str(value).strip().lower() in {"1", "true", "yes", "on"}
        )
        return info
