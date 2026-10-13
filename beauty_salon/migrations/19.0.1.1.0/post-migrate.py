"""Corrige citas creadas con la zona antigua (Madrid) a hora de Cuba.

Desplaza +6h las citas pendientes cuya hora habanera queda fuera de las
ventanas pero encajaría con +6h. Es autolimitada: tras aplicarse, la cita
ya queda dentro de horario y no vuelve a moverse.
"""
import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    Appointment = env["beauty.appointment"]
    windows = Appointment.BOOKING_WINDOWS
    to_fix = Appointment.search([
        ("state", "in", ("draft", "to_confirm", "confirmed")),
    ])
    fixed = 0
    for appt in to_fix:
        def in_windows(start_utc):
            import pytz

            tz = appt._booking_tz_for_technician(appt.technician_id)
            local = pytz.utc.localize(start_utc).astimezone(tz)
            if local.weekday() >= 5:
                return False
            start_min = local.hour * 60 + local.minute
            # Basta el inicio en ventana (citas largas pueden extenderse).
            return any(w0 <= start_min <= w1 for w0, w1 in windows)

        if appt.start_datetime and not in_windows(appt.start_datetime):
            from datetime import timedelta

            shifted = appt.start_datetime + timedelta(hours=6)
            if in_windows(shifted):
                appt.write({
                    "start_datetime": shifted,
                    "end_datetime": appt.end_datetime + timedelta(hours=6)
                    if appt.end_datetime else False,
                })
                appt.message_post(
                    body="Ajuste automático de zona horaria a Cuba.",
                    subtype_xmlid="mail.mt_note",
                )
                _logger.info("Cita %s ajustada a hora de Cuba.", appt.name)
                fixed += 1
    _logger.info("Migración de zona horaria: %s citas ajustadas.", fixed)
