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
        # Etiquetas en hora normal con am/pm y dentro de las ventanas.
        in_morning = lambda label: label in ("10:00 am", "10:30 am")  # servicio de 1h
        in_afternoon = lambda label: label in (
            "1:30 pm", "2:00 pm", "2:30 pm", "3:00 pm", "3:30 pm", "4:00 pm",
        )
        for slot in slots:
            self.assertTrue(
                in_morning(slot["label"]) or in_afternoon(slot["label"]),
                slot["label"],
            )
        # La pausa del mediodía no ofrece huecos de 1h.
        self.assertNotIn("12:00 pm", [s["label"] for s in slots])
        self.assertNotIn("9:00 am", [s["label"] for s in slots])
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

    def test_booking_outside_windows_is_rejected(self):
        day, slots = self._next_workday()
        tz = self.Appointment._booking_tz()
        noon_local = tz.localize(
            __import__("datetime").datetime(
                day.year, day.month, day.day, 12, 0, 0
            )
        )
        noon_utc = noon_local.astimezone(__import__("pytz").utc).replace(tzinfo=None)
        with self.assertRaises(ValidationError):
            self.Appointment.create_public_booking(
                name="Ana", phone="600111222", email="",
                service_ids=self.service.ids,
                start_utc_str=noon_utc.strftime("%Y-%m-%d %H:%M:%S"),
            )

    def test_confirm_notifies_technician_by_email(self):
        self.technician.email = "tecnica@test.local"
        day, slots = self._next_workday()
        appt = self.Appointment.create_public_booking(
            name="Ana", phone="600111222", email="ana@test.local",
            service_ids=self.service.ids,
            start_utc_str=slots[0]["start_utc"],
            technician_id=self.technician.id,
        )
        self.assertEqual(appt.state, "confirmed")
        self.assertIn("Servicio web", appt.service_names_display)
        mail = self.env["mail.mail"].search([
            ("model", "=", "beauty.appointment"),
            ("res_id", "=", appt.id),
        ], limit=1)
        self.assertTrue(mail, "Debe encolarse el aviso a la técnica")
        self.assertIn("tecnica@test.local", mail.email_to)

    def test_slots_follow_service_schedule(self):
        morning_service = self.env["beauty.service"].create({
            "name": "Servicio de mañana",
            "service_type": "nails",
            "list_price": 10.0,
            "duration": 0.5,
            "schedule": "morning",
        })
        afternoon_service = self.env["beauty.service"].create({
            "name": "Servicio de tarde",
            "service_type": "brows",
            "list_price": 10.0,
            "duration": 0.5,
            "schedule": "afternoon",
        })
        day, _ = self._next_workday()
        morning_slots = self.Appointment.get_booking_day_slots(
            day, morning_service.ids
        )
        self.assertTrue(morning_slots)
        for slot in morning_slots:
            self.assertTrue(slot["label"].endswith("am"), slot["label"])
        afternoon_slots = self.Appointment.get_booking_day_slots(
            day, afternoon_service.ids
        )
        self.assertTrue(afternoon_slots)
        for slot in afternoon_slots:
            self.assertTrue(slot["label"].endswith("pm"), slot["label"])
