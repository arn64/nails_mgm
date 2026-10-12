# Part of Nails MGM. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models
from odoo.exceptions import ValidationError


class BeautyService(models.Model):
    _name = "beauty.service"
    _description = "Servicio de belleza (uñas y cejas)"
    _order = "service_type, name"

    name = fields.Char(required=True, translate=True)
    service_type = fields.Selection(
        [("nails", "Uñas"), ("brows", "Cejas"), ("combo", "Combinado")],
        required=True,
        default="nails",
        index=True,
    )
    schedule = fields.Selection(
        [
            ("morning", "Mañana (10:00–11:30 am)"),
            ("afternoon", "Tarde (1:30–5:00 pm)"),
            ("both", "Mañana y tarde"),
        ],
        string="Turno",
        required=True,
        default="both",
        index=True,
        help="Turnos en los que se puede reservar este servicio desde la web.",
    )
    list_price = fields.Monetary(
        string="Precio", required=True, default=0.0, currency_field="currency_id"
    )
    duration = fields.Float(
        string="Duración (horas)",
        default=1.0,
        help="Duración estimada del servicio en horas. Ej.: 1.5 = 1h30.",
    )
    description = fields.Text(string="Descripción", translate=True)
    product_id = fields.Many2one(
        "product.product",
        string="Producto vinculado",
        domain="[('type', '=', 'service')]",
        help="Producto de servicio usado al crear el pedido. Si está vacío se crea uno automáticamente.",
    )
    active = fields.Boolean(string="Activo", default=True)
    color = fields.Integer(string="Color")
    image = fields.Image(max_width=512, max_height=512)
    appointment_ids = fields.Many2many(
        "beauty.appointment",
        "beauty_appointment_service_rel",
        "service_id",
        "appointment_id",
        string="Citas",
    )

    currency_id = fields.Many2one(
        "res.currency",
        default=lambda self: self.env.company.currency_id,
    )

    appointment_count = fields.Integer(
        string="Nº citas", compute="_compute_appointment_count"
    )

    _name_type_uniq = models.Constraint(
        "UNIQUE(name, service_type)", "Ya existe un servicio con ese nombre y tipo."
    )

    @api.constrains("list_price", "duration", "product_id")
    def _check_service_values(self):
        for service in self:
            if service.list_price < 0:
                raise ValidationError("El precio del servicio no puede ser negativo.")
            if service.duration <= 0:
                raise ValidationError("La duración del servicio debe ser mayor que cero.")
            if service.product_id and service.product_id.type != "service":
                raise ValidationError("El producto vinculado debe ser de tipo servicio.")

    def _get_sale_product(self):
        self.ensure_one()
        if not self.product_id:
            self.product_id = self.env["product.product"].sudo().create(
                {"name": self.name, "type": "service", "list_price": self.list_price}
            )
        if self.product_id.type != "service":
            raise ValidationError("El producto vinculado debe ser de tipo servicio.")
        return self.product_id

    @api.depends("appointment_ids")
    def _compute_appointment_count(self):
        for service in self:
            service.appointment_count = len(service.appointment_ids)

    def action_view_appointments(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Citas",
            "res_model": "beauty.appointment",
            "view_mode": "list,form,calendar,kanban",
            "domain": [("service_ids", "in", self.id)],
            "context": {"default_service_ids": [(6, 0, self.ids)]},
        }
