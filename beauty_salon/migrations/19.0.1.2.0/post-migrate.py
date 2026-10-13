"""Español con AM/PM en fecha/hora (evita confusiones del formato 24h)."""
import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    langs = env["res.lang"].search([("code", "=like", "es\\_%")])
    langs.write({"time_format": "%I:%M:%S %p"})
    _logger.info("Formato 12h aplicado a: %s", langs.mapped("code"))
