# Salón de Belleza (Odoo 19)

El módulo gestiona servicios de uñas y cejas, clientas, técnicas y citas desde el menú **Salón de Belleza**.

## Flujo de trabajo

1. Revise precios y duraciones en **Servicios** y registre las técnicas y su porcentaje de comisión.
2. Cree una cita con clienta, técnica, fecha y uno o más servicios. La duración se propone desde el catálogo y se puede ajustar.
3. Confirme la cita. Odoo rechaza otra cita confirmada o realizada de la misma técnica que se solape en horario. Las citas consecutivas son válidas.
4. Marque la cita como realizada o cancélela. El historial de la clienta y las estadísticas de la técnica se actualizan.
5. Si necesita cobrar mediante Ventas, pulse **Crear pedido** en una cita confirmada o realizada. Cada servicio genera una línea con su precio actual. Un servicio sin producto vinculado crea automáticamente un producto de tipo servicio; el pedido queda enlazado a la cita. La creación del pedido requiere permisos de Ventas.

La cifra de la cita es el subtotal de los precios actuales del catálogo. Los impuestos y descuentos se gestionan en el pedido de venta.

La reserva web está disponible todos los días de 10:00 a 11:30 am y de 1:00 a 5:00 pm. Los sábados y domingos aparecen en amarillo y las solicitudes quedan pendientes de confirmación de la técnica.

## Verificación

Con PostgreSQL disponible, desde la carpeta raíz del proyecto:

```bash
/Volumes/ExtWorkPro/Work/odoo/odoo_19/odoo/venv_19/bin/python \
  /Volumes/ExtWorkPro/Work/odoo/odoo_19/odoo/odoo-bin \
  -c odoo.conf -d nails_mgm_19 -i beauty_salon \
  --test-enable --test-tags /beauty_salon --stop-after-init --no-http
```

Para una base que ya tenga el módulo instalado, sustituya `-i` por `-u`.
