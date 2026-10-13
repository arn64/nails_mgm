"""Reubica citas pendientes fuera de horario a huecos válidos.

Mueve el inicio al próximo comienzo de ventana libre (misma duración),
misma técnica, buscando hasta 7 días laborables. Si no hay hueco, la deja
y la registra para moverla a mano. Anota cada cambio en el chatter.
"""
import logging
from datetime import datetime, timedelta

import pytz

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    Appointment = env["beauty.appointment"]
    windows = Appointment.BOOKING_WINDOWS
    moved, skipped = 0, []
    pending = Appointment.search([("state", "in", ("draft", "to_confirm", "confirmed"))])
    for appt in pending:
        if not appt.start_datetime:
            continue
        tz = appt._booking_tz_for_technician(appt.technician_id)
        local = pytz.utc.localize(appt.start_datetime).astimezone(tz)
        start_min = local.hour * 60 + local.minute
        if local.weekday() < 5 and any(w0 <= start_min <= w1 for w0, w1 in windows):
            continue
        duration = appt.duration or 1.0
        new_start = None
        day = local.date()
        for _ in range(8):
            if day.weekday() < 5:
                for w0, w1 in windows:
                    candidate_local = tz.localize(
                        datetime(day.year, day.month, day.day, w0 // 60, w0 % 60)
                    )
                    candidate_utc = candidate_local.astimezone(pytz.utc).replace(tzinfo=None)
                    candidate_end = candidate_utc + timedelta(hours=duration)
                    if candidate_utc > appt.start_datetime and appt._booking_slot_is_free(
                        appt.technician_id, candidate_utc, candidate_end
                    ):
                        new_start, new_end = candidate_utc, candidate_end
                        break
                if new_start:
                    break
            day += timedelta(days=1)
        if not new_start:
            skipped.append(appt.name)
            continue
        appt.write({"start_datetime": new_start, "end_datetime": new_end})
        appt.message_post(
            body=f"Reubicada automáticamente a horario válido: {new_start}.",
            subtype_xmlid="mail.mt_note",
        )
        _logger.info("Cita %s reubicada a %s.", appt.name, new_start)
        moved += 1
    if skipped:
        _logger.warning("Citas sin hueco libre (mover a mano): %s", skipped)
    _logger.info("Migración de reubicación: %s movidas, %s pendientes.", moved, len(skipped))
