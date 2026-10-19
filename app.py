"""IAQ Assessment Tool – funktionsfähiger Streamlit-Prototyp ohne Norm-Grenzwerte."""
import io
import json
from datetime import date, datetime
from uuid import uuid4

import pandas as pd
import streamlit as st

st.set_page_config(page_title="IAQ Assessment Tool", page_icon="🏢", layout="wide")

BASES = ["SIA 382/1:2025", "SECO / ArGV 3", "SN EN 16798-1", "Minergie-ECO", "Bachelor-Thesis – eigenes Bewertungsmodell"]
LEGACY_BASES = {"SIA 382/1": "SIA 382/1:2025"}
PROFILE_DESCRIPTIONS = {
    "SIA 382/1:2025": "Raumluftqualität und relevante Innenraumklimakriterien; Anwendbarkeit je Lüftungsart prüfen.",
    "SECO / ArGV 3": "Arbeitsplatzbezogene Anforderungen an die Innenraumluft und das Raumklima.",
    "SN EN 16798-1": "Kategorien der Innenraumqualität; Überschneidungen mit SIA transparent dokumentieren.",
    "Minergie-ECO": "Nur für die gewählten IAQ-Parameter relevante Kriterien; kein gesamtes Gebäudezertifikat.",
    "Bachelor-Thesis – eigenes Bewertungsmodell": "Eigenes Forschungsprofil: strengste fachlich vergleichbare und anwendbare Kriterien je Parameter; Herkunft dokumentieren. Noch keine automatische Kombination.",
}
PERIODS = ["Heizperiode", "Kühlperiode"]
VENTILATIONS = ["Mechanische Lüftung", "Natürliche Lüftung / Fensterlüftung", "Kombinierte / hybride Lüftung"]
STRATEGIES = ["Kontinuierliches Monitoring", "Temporäre Messkampagne", "Stichproben- / Kontrollmessung"]
PARAMETERS = ["CO₂", "Temperatur", "Relative Feuchte", "Luftgeschwindigkeit", "Weitere"]
UNITS = {"CO₂": "ppm", "Temperatur": "°C", "Relative Feuchte": "%", "Luftgeschwindigkeit": "m/s", "Weitere": ""}
PROFILE_IDS = {(b, p): id_ for b, stem in zip(BASES, ["S", "E", "N", "M", "BT"]) for p, id_ in zip(PERIODS, [stem+"H", stem+"K"])}
STEPS = [
    ("B", "Gebäudespezifikation", "Gebäudetyp auswählen und Erweiterbarkeit dokumentieren"),
    ("BD", "Gebäudeweite Stammdaten", "Objekt, Standort und Grundnutzung erfassen"),
    ("NU", "Nutzungsprofil", "Betriebszeiten und typische Belegung hinterlegen"),
    ("GV", "Gültigkeit der Gebäudedaten", "Vollständigkeit und Aktualität prüfen"),
    ("D", "Bewertungsgrundlage", "SIA, SECO, SN EN 16798-1, Minergie-ECO oder Bachelor-Thesis auswählen"),
    ("SS", "Heiz- / Kühlperiode", "Periode des Assessments auswählen"),
    ("RP", "Regelprofil", "Profil-ID aus Bewertungsgrundlage und Periode erzeugen; Grenzwerte später hinterlegen"),
    ("BT", "Bachelor-Thesis Bewertungsmodell", "Fachlich vergleichbare Kriterien nach dokumentierter Methodik kombinieren; noch nicht automatisiert"),
    ("R", "Raum auswählen / hinzufügen", "Beliebig viele Räume getrennt erfassen"),
    ("RD", "Raumspezifikation", "Raumgrösse, Nutzung und Belegung dokumentieren"),
    ("LA", "Lüftungsart je Raum", "Mechanisch, natürlich oder hybrid unterscheiden"),
    ("MV", "Messstrategie / Nachweiszweck", "Monitoring, Messkampagne oder Stichprobe definieren"),
    ("PF", "Pflichtdaten / optionale Daten", "Anforderungen je Profil zu einem späteren Zeitpunkt konfigurieren"),
    ("MD", "Messdaten", "Manuell erfassen oder CSV hochladen"),
    ("MG", "Messgerät (informativ)", "Geräteangaben dokumentieren, ohne das Regelprofil zu ändern"),
    ("Q", "Datenqualität", "Grundlegende Vollständigkeit und Plausibilität prüfen"),
    ("BW", "Bewertung", "Normbasierte Bewertung in einer späteren Version implementieren"),
    ("RE", "Raumergebnis", "Erfassungsstand und Qualität pro Raum zusammenfassen"),
    ("EX", "Gebäudeübersicht / Export", "Räume und Daten exportieren"),
]


def new_project():
    return {
        "schema_version": 2,
        "building": {"name": "", "object_id": "", "location": "", "building_type": "Büro- / Dienstleistungsgebäude (Raumnutzung 3)",
                     "use": "Büro / Dienstleistung", "operating_hours": "Mo–Fr, 08:00–17:00", "occupancy": None,
                     "notes": "", "confirmed": False},
        "assessment": {"basis": BASES[0], "period": PERIODS[0], "purpose": "", "notes": "", "thesis_method": "", "thesis_sources": ""},
        "rooms": [], "step_notes": {},
    }


def new_room():
    return {"id": str(uuid4())[:8], "name": "Neuer Raum", "floor": "", "use": "Büro", "area_m2": None,
            "height_m": None, "occupancy": None, "ventilation": VENTILATIONS[0], "ventilation_notes": "",
            "ventilation_mode": "", "strategy": STRATEGIES[0], "purpose": "", "start_date": "", "end_date": "",
            "usage_times": "", "measurement_position": "", "conditions": "", "required_notes": "", "optional_notes": "",
            "device_manufacturer": "", "device_model": "", "device_id": "", "calibration": "",
            "measurements": [], "notes": ""}


def safe_number(value):
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def quality(room):
    items = []
    if not room.get("name", "").strip():
        items.append("Raumbezeichnung fehlt")
    if room.get("area_m2") is None or room["area_m2"] <= 0:
        items.append("Raumfläche fehlt / ungültig")
    if room.get("occupancy") is None:
        items.append("Belegung fehlt")
    if not room.get("ventilation"):
        items.append("Lüftungsart fehlt")
    if not room.get("strategy"):
        items.append("Messstrategie fehlt")
    if not room.get("measurements"):
        items.append("Keine Messdaten hinterlegt")
    for j, m in enumerate(room.get("measurements", []), 1):
        if m.get("parameter") not in PARAMETERS or safe_number(m.get("value")) is None:
            items.append(f"Messwert {j}: Parameter oder Zahlenwert unklar")
    return items


def number_input_nullable(label, value, key, min_value=0.0, step=1.0, fmt="%.1f"):
    # Ein leeres Feld bleibt bewusst unbekannt statt automatisch 0 zu werden.
    previous = "" if value is None else str(value)
    entry = st.text_input(label, value=previous, key=key)
    if not entry.strip():
        return None
    converted = safe_number(entry.replace(",", "."))
    if converted is None or converted < min_value:
        st.warning(f"Bitte bei «{label}» eine Zahl ≥ {min_value} angeben.")
        return None
    return converted


def get_room(room_id):
    return next((r for r in st.session_state.project["rooms"] if r["id"] == room_id), None)


def profile_summary():
    a = st.session_state.project["assessment"]
    return PROFILE_IDS[(a["basis"], a["period"])]


if "project" not in st.session_state:
    st.session_state.project = new_project()

st.markdown("""<style>
.block-container{padding-top:1.3rem;max-width:1280px}
[data-testid='stMetricValue']{font-size:1.55rem}
.smallnote{color:#64748b;font-size:.88rem}
</style>""", unsafe_allow_html=True)

st.title("IAQ Assessment Tool")
st.caption("Funktionsprototyp · Schwerpunkt Innenraumluftqualität · **ohne normative Grenzwerte und ohne Konformitätsentscheid**")

with st.sidebar:
    st.subheader("Navigation")
    page = st.radio("Bereich", ["Übersicht", "1 · Gebäude", "2 · Bewertungsprofil", "3 · Räume & Lüftung", "4 · Messdaten", "5 · Qualitätsprüfung", "6 · Export", "Funktionskatalog"], label_visibility="collapsed")
    st.divider()
    st.caption("Aktives Profil")
    st.info(f"{st.session_state.project['assessment']['basis']}\n\n{st.session_state.project['assessment']['period']} · {profile_summary()}")
    st.caption(f"Erfasste Räume: {len(st.session_state.project['rooms'])}")

p = st.session_state.project
b = p["building"]
a = p["assessment"]

if page == "Übersicht":
    st.subheader("Projektstatus")
    cols = st.columns(4)
    cols[0].metric("Räume", len(p["rooms"]))
    cols[1].metric("Messwerte", sum(len(r["measurements"]) for r in p["rooms"]))
    cols[2].metric("Profil", profile_summary())
    cols[3].metric("Räume ohne Hinweise", sum(not quality(r) for r in p["rooms"]))
    st.markdown("**Bearbeitungsablauf**")
    st.markdown("Gebäude → Bewertungsgrundlage → Heiz-/Kühlperiode → Raum → Lüftungsart → Messstrategie → Messdaten → Qualitätsprüfung → Export")
    st.info("Die zehn Regelprofile sind strukturell vorbereitet. Es werden **keine Grenzwerte angewendet**, keine Ampelbewertung berechnet und keine Einhaltung einer Norm bestätigt.")
    if not p["rooms"]:
        st.warning("Noch keine Räume angelegt. Öffne «3 · Räume & Lüftung».")
    else:
        st.dataframe(pd.DataFrame([{"Raum": r["name"], "Lüftungsart": r["ventilation"], "Messstrategie": r["strategy"], "Messwerte": len(r["measurements"]), "Hinweise": len(quality(r))} for r in p["rooms"]]), use_container_width=True, hide_index=True)

elif page == "1 · Gebäude":
    st.subheader("Gebäudespezifikation und Stammdaten")
    st.selectbox("Gebäudetyp", [b["building_type"]], disabled=True, help="Weitere Gebäudetypen können in späteren Versionen ergänzt werden.")
    c1, c2 = st.columns(2)
    with c1:
        b["name"] = st.text_input("Gebäudebezeichnung", b["name"])
        b["object_id"] = st.text_input("Objekt-ID", b["object_id"])
        b["location"] = st.text_input("Standort", b["location"])
        b["use"] = st.text_input("Übergeordnete Nutzung", b["use"])
    with c2:
        b["operating_hours"] = st.text_input("Typische Betriebszeiten", b["operating_hours"])
        b["occupancy"] = number_input_nullable("Typische Gesamtbelegung (Personen)", b["occupancy"], "building_occ", fmt="%.0f")
        b["notes"] = st.text_area("Gebäudeweite Besonderheiten", b["notes"])
    st.markdown("**Gültigkeit der Stammdaten**")
    b["confirmed"] = st.checkbox("Gebäudedaten sind geprüft und aktuell", b["confirmed"])
    if not b["name"] or not b["location"]:
        st.warning("Für einen nachvollziehbaren Nachweis bitte Gebäudebezeichnung und Standort erfassen.")
    elif b["confirmed"]:
        st.success("Gebäudedaten wurden als geprüft markiert (Selbstauskunft, keine externe Validierung).")

elif page == "2 · Bewertungsprofil":
    st.subheader("Bewertungsgrundlage und Periode")
    c1, c2 = st.columns(2)
    with c1:
        a["basis"] = st.selectbox("Bewertungsgrundlage", BASES, index=BASES.index(a["basis"]))
    with c2:
        a["period"] = st.radio("Saison", PERIODS, index=PERIODS.index(a["period"]), horizontal=True)
    st.info(f"Aktiver Regelprofil-Schlüssel: **{profile_summary()}** · {a['basis']} · {a['period']}")
    a["purpose"] = st.text_area("Ziel / Nachweiszweck der Gesamtbewertung", a["purpose"])
    a["notes"] = st.text_area("Anmerkungen zur Wahl der Grundlage", a["notes"])
    st.markdown("**Vorgesehene zehn Regelprofile**")
    st.caption(PROFILE_DESCRIPTIONS[a["basis"]])
    if a["basis"] == BASES[4]:
        st.warning("Dieses Profil ist ein eigenständig entwickeltes Modell und keine amtliche Norm. Vergleichbarkeit und Anwendbarkeit jedes Kriteriums müssen vor einer automatischen Auswahl begründet werden.")
        a["thesis_method"] = st.text_area("Methodik / Auswahl der strengsten vergleichbaren Anforderungen", a.get("thesis_method", ""))
        a["thesis_sources"] = st.text_area("Herkunft der Kriterien / Normstellen", a.get("thesis_sources", ""))
    st.dataframe(pd.DataFrame([{"Kürzel": code, "Grundlage": base, "Periode": period, "Grenzwerte": "Noch nicht hinterlegt", "Pflichtfeldregeln": "Noch festzulegen", "Geltungsbereich": PROFILE_DESCRIPTIONS[base]} for (base, period), code in PROFILE_IDS.items()]), use_container_width=True, hide_index=True)
    st.caption("Die Wahl des Regelprofils wird im Projekt gespeichert. Sie löst aktuell noch keine automatische normative Entscheidung aus. Die Heiz-/Kühlperiode ist vorbereitet, ohne saisonale Unterschiede zu behaupten.")

elif page == "3 · Räume & Lüftung":
    st.subheader("Raumspezifikation")
    if st.button("+ Neuen Raum anlegen", type="primary"):
        p["rooms"].append(new_room())
        st.rerun()
    if not p["rooms"]:
        st.info("Lege zuerst einen Raum an.")
    else:
        ids = [r["id"] for r in p["rooms"]]
        selected = st.selectbox("Raum", ids, format_func=lambda rid: f"{get_room(rid)['name']} · {rid}", key="room_selector")
        r = get_room(selected)
        with st.expander("Raum löschen"):
            st.warning("Der Raum inklusive seiner Messdaten wird entfernt.")
            if st.button("Ausgewählten Raum endgültig löschen", key="delete_room"):
                p["rooms"] = [q for q in p["rooms"] if q["id"] != selected]
                st.session_state.pop("room_selector", None)
                st.rerun()
        c1, c2 = st.columns(2)
        with c1:
            r["name"] = st.text_input("Raumbezeichnung", r["name"], key=f"name_{selected}")
            r["floor"] = st.text_input("Etage / Lage", r["floor"], key=f"floor_{selected}")
            r["use"] = st.text_input("Konkrete Raumnutzung", r["use"], key=f"use_{selected}")
            r["area_m2"] = number_input_nullable("Raumfläche (m²)", r["area_m2"], f"area_{selected}")
            r["height_m"] = number_input_nullable("Raumhöhe (m)", r["height_m"], f"height_{selected}")
            r["occupancy"] = number_input_nullable("Typische Belegung (Personen)", r["occupancy"], f"occ_{selected}", fmt="%.0f")
        with c2:
            r["ventilation"] = st.radio("Lüftungsart dieses Raums", VENTILATIONS, index=VENTILATIONS.index(r["ventilation"]), key=f"vent_{selected}")
            r["ventilation_notes"] = st.text_area("Lüftungsbetrieb / Fensteröffnungen", r["ventilation_notes"], key=f"vn_{selected}")
            if r["ventilation"] == VENTILATIONS[2]:
                r["ventilation_mode"] = st.text_input("Aktiver Betriebsmodus / Wechsel der Betriebsmodi", r["ventilation_mode"], key=f"vm_{selected}")
            r["notes"] = st.text_area("Weitere raumspezifische Informationen", r["notes"], key=f"rn_{selected}")
        st.divider()
        st.markdown("**Messstrategie und Nachweiszweck**")
        r["strategy"] = st.selectbox("Messsituation", STRATEGIES, index=STRATEGIES.index(r["strategy"]), key=f"strategy_{selected}")
        r["purpose"] = st.text_area("Nachweiszweck", r["purpose"], key=f"purpose_{selected}")
        c3, c4 = st.columns(2)
        r["start_date"] = c3.text_input("Messbeginn (JJJJ-MM-TT)", r["start_date"], key=f"begin_{selected}")
        r["end_date"] = c4.text_input("Messende (JJJJ-MM-TT)", r["end_date"], key=f"end_{selected}")
        r["usage_times"] = st.text_input("Relevante Nutzungs-/Messzeiten", r["usage_times"], key=f"usage_{selected}")
        r["measurement_position"] = st.text_input("Messposition / Messhöhe", r["measurement_position"], key=f"position_{selected}")
        r["conditions"] = st.text_area("Rahmenbedingungen (Belegung, Lüftungszustand, Besonderheiten)", r["conditions"], key=f"conditions_{selected}")
        st.divider()
        st.markdown("**Anforderungsfelder – inhaltlich vorbereitet**")
        st.caption("Hier werden später die regelprofilabhängigen Pflicht- und optionalen Felder definiert.")
        r["required_notes"] = st.text_area("Notizen zu späteren Pflichtdaten", r["required_notes"], key=f"required_{selected}")
        r["optional_notes"] = st.text_area("Notizen zu optionalen Daten", r["optional_notes"], key=f"optional_{selected}")

elif page == "4 · Messdaten":
    st.subheader("Messwerte und Gerätedokumentation")
    if not p["rooms"]:
        st.warning("Bitte zuerst einen Raum anlegen.")
    else:
        r_id = st.selectbox("Raum auswählen", [r["id"] for r in p["rooms"]], format_func=lambda rid: get_room(rid)["name"], key="measurement_room")
        r = get_room(r_id)
        st.markdown("**Messwert manuell erfassen**")
        with st.form(f"new_measurement_{r_id}", clear_on_submit=True):
            c1, c2, c3 = st.columns(3)
            parameter = c1.selectbox("Messgrösse", PARAMETERS)
            value = c2.text_input("Messwert")
            timestamp = c3.text_input("Zeitpunkt (optional, ISO)", placeholder="2026-10-19 10:30")
            c4, c5 = st.columns(2)
            unit = c4.text_input("Einheit (bei Standardparametern automatisch)", placeholder="z. B. ppm")
            note = c5.text_input("Bemerkung")
            add = st.form_submit_button("Messwert hinzufügen", type="primary")
        if add:
            num = safe_number(value.replace(",", "."))
            if num is None:
                st.error("Bitte einen gültigen numerischen Messwert eingeben.")
            else:
                r["measurements"].append({"timestamp": timestamp, "parameter": parameter, "value": num, "unit": unit or UNITS[parameter], "note": note})
                st.success("Messwert erfasst.")
        st.markdown("**CSV-Messdatenimport**")
        st.caption("Spalten: `timestamp`, `parameter`, `value`, `unit`, `note`. Spalten `timestamp`, `unit` und `note` sind optional. Dezimaltrennzeichen: Punkt oder Komma.")
        example = pd.DataFrame([{"timestamp": "2026-10-19 09:00", "parameter": "CO₂", "value": 850, "unit": "ppm", "note": "Beispieldaten"}])
        st.download_button("CSV-Vorlage herunterladen", example.to_csv(index=False).encode("utf-8-sig"), file_name="iaq_messdaten_vorlage.csv", mime="text/csv")
        upload = st.file_uploader("CSV-Datei auswählen", type=["csv"], key=f"csv_{r_id}")
        if upload is not None:
            try:
                raw = upload.getvalue()
                df = pd.read_csv(io.BytesIO(raw), sep=None, engine="python", encoding="utf-8-sig")
                df.columns = [x.strip().lower() for x in df.columns]
                if not {"parameter", "value"}.issubset(df.columns):
                    st.error("Die Spalten `parameter` und `value` sind erforderlich.")
                else:
                    st.dataframe(df.head(15), hide_index=True, use_container_width=True)
                    if st.button("Angezeigte CSV dem Raum hinzufügen", key=f"import_{r_id}"):
                        entries = []
                        invalid = 0
                        for item in df.fillna("").to_dict("records"):
                            param = str(item["parameter"]).strip()
                            v = safe_number(str(item["value"]).replace(",", "."))
                            if not param or v is None:
                                invalid += 1
                                continue
                            entries.append({"timestamp": str(item.get("timestamp", "")), "parameter": param, "value": v, "unit": str(item.get("unit", "")) or UNITS.get(param, ""), "note": str(item.get("note", ""))})
                        r["measurements"].extend(entries)
                        st.success(f"{len(entries)} Messwerte übernommen. {invalid} ungültige Zeilen übersprungen.")
            except (ValueError, UnicodeError, pd.errors.ParserError) as exc:
                st.error(f"CSV konnte nicht gelesen werden: {exc}")
        st.markdown("**Erfasste Messwerte**")
        if r["measurements"]:
            st.dataframe(pd.DataFrame(r["measurements"]), use_container_width=True, hide_index=True)
            if st.button("Messwerte dieses Raums löschen", key=f"clear_{r_id}"):
                r["measurements"] = []
                st.rerun()
        else:
            st.info("Noch keine Messwerte erfasst.")
        with st.expander("Messgerät (nur Dokumentation, ohne Einfluss auf Bewertung)"):
            for field, label in [("device_manufacturer", "Hersteller"), ("device_model", "Modell"), ("device_id", "Geräte-ID"), ("calibration", "Kalibrierung / Geräteprüfung")]:
                r[field] = st.text_input(label, r[field], key=f"{field}_{r_id}")

elif page == "5 · Qualitätsprüfung":
    st.subheader("Vollständigkeit und Plausibilität")
    st.warning("Diese Prüfung ist eine **technische Vorprüfung**, keine normative Bewertung. Messunsicherheit, zeitliche Repräsentativität und normbezogene Vollständigkeit sind noch nicht automatisiert.")
    building_issues = []
    if not b["name"].strip(): building_issues.append("Gebäudebezeichnung fehlt")
    if not b["location"].strip(): building_issues.append("Standort fehlt")
    if not b["confirmed"]: building_issues.append("Gebäudedaten nicht als geprüft markiert")
    if building_issues:
        st.warning("Gebäude: " + "; ".join(building_issues))
    else:
        st.success("Gebäude: grundlegende Angaben vorhanden.")
    if not p["rooms"]:
        st.info("Noch keine Räume vorhanden.")
    for r in p["rooms"]:
        issues = quality(r)
        with st.expander(f"{r['name']} · {'Hinweise: ' + str(len(issues)) if issues else 'Grundprüfung vollständig'}", expanded=True):
            st.write(f"Lüftung: {r['ventilation']} · Messstrategie: {r['strategy']} · Messwerte: {len(r['measurements'])}")
            if issues:
                for issue in issues: st.markdown(f"- {issue}")
            else:
                st.success("Grundprüfung bestanden. Keine Aussage über Einhaltung von Normen.")
    st.divider()
    st.subheader("Normbewertung")
    st.info("Noch nicht implementiert: Grenzwerte, Klassierungslogik, anwendungsbezogene Pflichtfelder, Messunsicherheit und Bestehen/Nichtbestehen.")

elif page == "6 · Export":
    st.subheader("Projektdaten sichern und übertragen")
    st.caption("Es gibt noch keine Datenbank. Änderungen werden in der aktuellen Browser-Sitzung gehalten. Regelmässig als JSON exportieren!")
    payload = json.dumps(p, ensure_ascii=False, indent=2).encode("utf-8")
    st.download_button("Gesamtes Projekt als JSON speichern", payload, file_name="iaq_projekt.json", mime="application/json", type="primary")
    all_rows = []
    for r in p["rooms"]:
        for m in r["measurements"]:
            all_rows.append({"gebaeude": b["name"], "raum_id": r["id"], "raum": r["name"], "lueftungsart": r["ventilation"], "bewertungsgrundlage": a["basis"], "periode": a["period"], **m})
    if all_rows:
        df = pd.DataFrame(all_rows)
        st.download_button("Alle Messwerte als CSV exportieren", df.to_csv(index=False).encode("utf-8-sig"), file_name="iaq_messwerte.csv", mime="text/csv")
    st.divider()
    st.subheader("Projekt aus Sicherungsdatei laden")
    uploaded_json = st.file_uploader("Zuvor exportierte JSON-Datei", type=["json"])
    if uploaded_json is not None and st.button("Projekt aus Datei ersetzen"):
        try:
            imported = json.loads(uploaded_json.getvalue().decode("utf-8"))
            if not isinstance(imported, dict) or not all(k in imported for k in ("building", "assessment", "rooms", "step_notes")):
                raise ValueError("Die Datei entspricht nicht dem erwarteten Projektformat.")
            imported["assessment"]["basis"] = LEGACY_BASES.get(imported["assessment"].get("basis"), imported["assessment"].get("basis"))
            if not isinstance(imported["rooms"], list) or imported["assessment"].get("basis") not in BASES or imported["assessment"].get("period") not in PERIODS:
                raise ValueError("Ungültige Projektstruktur oder unbekanntes Profil.")
            st.session_state.project = imported
            for key in list(st.session_state.keys()):
                if key not in ("project",):
                    del st.session_state[key]
            st.rerun()
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            st.error(f"Projekt konnte nicht geladen werden: {exc}")

elif page == "Funktionskatalog":
    st.subheader("Beschreibungen der Flussdiagramm-Kästen")
    st.caption("Hier kannst du zu jedem Kasten den späteren fachlichen Einfluss, Regeln und Quellen ergänzen – ohne den eigentlichen Programmablauf zu verändern.")
    for node, title, purpose in STEPS:
        with st.expander(f"{node} · {title}"):
            st.caption(purpose)
            note = p["step_notes"].setdefault(node, {"impact": "", "required": "", "optional": "", "source": "", "open": ""})
            note["impact"] = st.text_area("Einfluss / Softwarefunktion", note.get("impact", ""), key=f"impact_{node}")
            note["required"] = st.text_area("Spätere Pflichtfelder / Gültigkeit", note.get("required", ""), key=f"required_step_{node}")
            note["optional"] = st.text_area("Optionale Angaben", note.get("optional", ""), key=f"optional_step_{node}")
            note["source"] = st.text_input("Quelle / Normstelle (vorläufig)", note.get("source", ""), key=f"source_{node}")
            note["open"] = st.text_area("Offene Fragen", note.get("open", ""), key=f"open_{node}")

st.divider()
st.caption("IAQ Assessment Tool · Bachelorarbeit · Prototyp ohne normative Freigabe · Die Nutzungsart «Raumnutzung 3» ist als Projektannahme übernommen und fachlich noch zu verifizieren.")
