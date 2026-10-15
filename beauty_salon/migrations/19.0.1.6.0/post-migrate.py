"""Fija una referencia de precio para las citas históricas ya solicitadas o cerradas."""

import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    appointments = env["beauty.appointment"].with_context(active_test=False).search([
        ("state", "in", ("to_confirm", "confirmed", "done", "cancelled")),
        ("price_locked", "=", False),
    ])
    locked = 0
    for appointment in appointments:
        if not appointment.service_ids:
            _logger.warning("Cita %s sin servicios: no se pudo fijar su precio", appointment.name)
            continue
        appointment._lock_agreed_prices()
        locked += 1
    _logger.info("Precios de citas históricas fijados: %s", locked)
