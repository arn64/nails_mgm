/** Muestra fechas-horas del backend con am/pm y corrige el tzdata cubano obsoleto.
 *
 * Odoo guarda los datetimes en UTC y el navegador los convierte con su propia
 * base IANA. La corrección se aplica en la zona de Luxon para que abarque tanto
 * la lectura como la edición del campo, sin tocar el UTC persistido.
 */
import { patch } from "@web/core/utils/patch";
import { registry } from "@web/core/registry";
import { session } from "@web/session";
import { DateTimeField } from "@web/views/fields/datetime/datetime_field";
import { formatDate } from "@web/views/fields/formatters";

const CUBA_TIMEZONES = new Set(["cuba", "america/havana"]);
// Cuba stays at UTC-04 while old browser tzdata falls back to UTC-05.
// These are the corresponding transition instants in UTC.
const CUBA_CORRECTION_START = Date.UTC(2026, 10, 1, 5);
const CUBA_CORRECTION_END = Date.UTC(2027, 10, 7, 5);

class CubaCorrectedSystemZone extends luxon.Zone {
    constructor(systemZone) {
        super();
        this.systemZone = systemZone;
    }

    get type() {
        // A custom zone makes Luxon format using its own offset calculation,
        // instead of asking Intl to apply the stale Cuba rule a second time.
        return "cuba-corrected";
    }

    get name() {
        return this.systemZone.name;
    }

    get isUniversal() {
        return false;
    }

    get isValid() {
        return this.systemZone.isValid;
    }

    offset(timestamp) {
        const offset = this.systemZone.offset(timestamp);
        if (
            timestamp >= CUBA_CORRECTION_START &&
            timestamp < CUBA_CORRECTION_END &&
            offset === -300
        ) {
            return -240;
        }
        return offset;
    }

    offsetName(timestamp, options) {
        return luxon.FixedOffsetZone.instance(this.offset(timestamp)).offsetName(
            timestamp,
            options
        );
    }

    formatOffset(timestamp, format) {
        return luxon.FixedOffsetZone.instance(this.offset(timestamp)).formatOffset(
            timestamp,
            format
        );
    }

    equals(otherZone) {
        return otherZone instanceof CubaCorrectedSystemZone && otherZone.name === this.name;
    }
}

const systemZone = luxon.SystemZone.instance;
if (
    session.beauty_salon_cuba_tz_display_correction &&
    CUBA_TIMEZONES.has(systemZone.name.toLowerCase())
) {
    luxon.Settings.defaultZone = new CubaCorrectedSystemZone(systemZone);
}

/** Convierte una hora 24h al final del texto a 12h con am/pm. */
function to12h(text) {
    if (!text) {
        return text;
    }
    return text.replace(/(\d{1,2}):(\d{2})(?::(\d{2}))?\s*$/, (match, h, m, s) => {
        const hour = parseInt(h, 10);
        const suffix = hour < 12 ? "am" : "pm";
        const h12 = hour % 12 || 12;
        return `${h12}:${m}${s ? `:${s}` : ""} ${suffix}`;
    });
}

function hasMeridiem(text) {
    return /(am|pm|a\.\s?m\.|p\.\s?m\.)\s*$/i.test(text || "");
}

patch(DateTimeField.prototype, {
    getFormattedValue(valueIndex, numeric = this.props.numeric) {
        if (numeric) {
            return super.getFormattedValue(valueIndex, numeric);
        }
        const values = this.values;
        const value = values[valueIndex];
        if (!value || this.field.type === "date") {
            return super.getFormattedValue(valueIndex, numeric);
        }
        const { showSeconds, showTime } = this.props;
        const showDate =
            !showTime || valueIndex !== 1 || !values[0] || !values[0].hasSame(value, "day");
        const parts = [];
        if (showDate) {
            parts.push(formatDate(value, {}));
        }
        if (showTime !== false) {
            parts.push(value.toFormat(showSeconds ? "h:mm:ss a" : "h:mm a"));
        }
        return parts.join(", ");
    },
});

const formatters = registry.category("formatters");
const datetimeFormatter = formatters.get("datetime");
function beautyDatetimeFormatter(value, options) {
    const text = datetimeFormatter(value, options);
    if (!value || (options && options.showTime === false) || hasMeridiem(text)) {
        return text;
    }
    return to12h(text);
}
beautyDatetimeFormatter.extractOptions = datetimeFormatter.extractOptions;
formatters.add("datetime", beautyDatetimeFormatter, { force: true });
