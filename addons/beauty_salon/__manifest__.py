# Part of Nails MGM. See LICENSE file for full copyright and licensing details.

{
    "name": "Salón de Belleza (Uñas y Cejas)",
    "version": "19.0.1.0.0",
    "summary": "Gestión de arreglos de uñas y cejas: servicios, citas, clientas y técnicas",
    "description": """
Salón de Belleza - Uñas y Cejas
===============================
Gestión sencilla para salones de uñas y cejas:

* Catálogo de servicios de uñas y cejas (precio y duración).
* Citas con clienta, servicios, técnica, fecha y estado.
* Ficha de clienta con alergias, preferencias e historial.
* Técnicas/empleadas con comisión estimada sobre servicios realizados.
* Control de solapamientos de citas confirmadas.
* Creación opcional de presupuesto/pedido de venta desde una cita confirmada o realizada.
    """,
    "author": "Nails MGM",
    "category": "Services/Beauty",
    "depends": ["base", "mail", "sale_management"],
    "data": [
        "security/ir.model.access.csv",
        "data/beauty_sequence.xml",
        "data/beauty_service_data.xml",
        "views/beauty_service_views.xml",
        "views/beauty_technician_views.xml",
        "views/beauty_appointment_views.xml",
        "views/res_partner_views.xml",
        "views/beauty_menus.xml",
    ],
    "demo": [
        "demo/beauty_demo.xml",
    ],
    "application": True,
    "installable": True,
    "license": "LGPL-3",
}
