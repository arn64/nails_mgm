from datetime import timedelta

from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase


class TestBeautyBooking(TransactionCase):
    def setUp(self):
        super().setUp()
        self.technician = self.env["beauty.technician"].create({"name": "Técnica web"})
        self.service = self.env["beauty.service"].create({
            "name": "Servicio web",
            "service_type": "nails",
            "list_price": 20.0,
            "duration": 1.0,
        })
        self.Appointment = self.env["beauty.appointment"]

    def _next_workday(self):
        day = self.Appointment._booking_tz().localize(
            __import__("datetime").datetime.now().replace(hour=12, minute=0, second=0, microsecond=0)
        )
        # Avanza hasta el próximo Lun-Vie con huecos.
        for _ in range(10):
            day += timedelta(days=1)
            if day.weekday() < 5:
                slots = self.Appointment.get_booking_day_slots(
                    day.date(), self.service.ids
                )
                if slots:
                    return day.date(), slots
        self.fail("Sin días laborables con huecos para el test")

    def test_day_slots_respect_hours_and_overlap(self):
        day, slots = self._next_workday()
        self.assertTrue(slots)
        # Todos los slots dentro de 9-17 hora local.
        for slot in slots:
            self.assertTrue(slot["label"] >= "09:00")
            self.assertTrue(slot["label"] < "17:00")
        # Reservar el primer hueco bloquea ese hueco.
        first = slots[0]
        appt = self.Appointment.create_public_booking(
            name="Ana", phone="600111222", email="",
            service_ids=self.service.ids,
            start_utc_str=first["start_utc"],
            technician_id=first["technician_id"],
        )
        self.assertEqual(appt.state, "confirmed")
        remaining = self.Appointment.get_booking_day_slots(
            day, self.service.ids, technician_id=first["technician_id"]
        )
        self.assertNotIn(first["start_utc"], [s["start_utc"] for s in remaining])

    def test_public_booking_validates_data(self):
        day, slots = self._next_workday()
        with self.assertRaises(ValidationError):
            self.Appointment.create_public_booking(
                name="", phone="600111222", email="",
                service_ids=self.service.ids,
                start_utc_str=slots[0]["start_utc"],
            )
        with self.assertRaises(ValidationError):
            self.Appointment.create_public_booking(
                name="Ana", phone="12", email="",
                service_ids=self.service.ids,
                start_utc_str=slots[0]["start_utc"],
            )
        with self.assertRaises(ValidationError):
            self.Appointment.create_public_booking(
                name="Ana", phone="600111222", email="no-es-email",
                service_ids=self.service.ids,
                start_utc_str=slots[0]["start_utc"],
            )

    def test_weekend_has_no_slots(self):
        from datetime import date as date_cls
        # Busca el próximo sábado.
        today = self.Appointment._booking_tz().localize(
            __import__("datetime").datetime.now()
        ).date()
        offset = 0
        saturday = None
        for i in range(1, 10):
            candidate = today + timedelta(days=i)
            if candidate.weekday() == 5:
                saturday = candidate
                break
        self.assertTrue(saturday)
        self.assertEqual(
            self.Appointment.get_booking_day_slots(saturday, self.service.ids), []
        )
