"""
Парсер OFAC SDN Enhanced ZIP/XML.
Структура: <sanctionsData> → <entity id="..."> (все записи, Individual и Entity)
Namespace: https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/ENHANCED_XML
"""
import logging
import zipfile
from datetime import date
from io import BytesIO
from xml.etree import ElementTree as ET

from app.models import Entry

logger = logging.getLogger("garudar_api")

NS = "https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/ENHANCED_XML"
_NS = f"{{{NS}}}"


def _tag(name: str) -> str:
    return f"{_NS}{name}"


def _txt(el, tag: str) -> str | None:
    child = el.find(_tag(tag))
    if child is None or not child.text:
        return None
    v = child.text.strip()
    return v if v else None


def _truncate(s: str | None, n: int) -> str | None:
    if s is None:
        return None
    return s[:n] if len(s) > n else s


def _parse_entity(el) -> Entry | None:
    entity_id = el.get("id", "")

    # --- entry_type ---
    general_el = el.find(_tag("generalInfo"))
    entity_type_el = general_el.find(_tag("entityType")) if general_el is not None else None
    entity_type_text = entity_type_el.text.strip() if (entity_type_el is not None and entity_type_el.text) else "Entity"
    entry_type = "Individual" if "individual" in entity_type_text.lower() else "Entity"

    # --- names (primary + aliases) ---
    full_name = None
    aliases = []
    names_el = el.find(_tag("names"))
    if names_el is not None:
        for name_el in names_el.findall(_tag("name")):
            is_primary_el = name_el.find(_tag("isPrimary"))
            is_primary = (is_primary_el is not None and is_primary_el.text and is_primary_el.text.strip().lower() == "true")

            # Get formatted name from first translation
            formatted = None
            trans_el = name_el.find(f".//{_tag('formattedFullName')}")
            if trans_el is None:
                trans_el = name_el.find(f".//{_tag('formattedLastName')}")
            if trans_el is not None and trans_el.text:
                formatted = trans_el.text.strip()

            if not formatted:
                # Fallback: combine nameParts
                parts = []
                for np in name_el.findall(f".//{_tag('namePart')}"):
                    val_el = np.find(_tag("value"))
                    if val_el is not None and val_el.text:
                        parts.append(val_el.text.strip())
                if parts:
                    formatted = " ".join(parts)

            if not formatted:
                continue

            if is_primary and full_name is None:
                full_name = formatted
            elif not is_primary:
                aliases.append(formatted)

    if not full_name and aliases:
        full_name = aliases.pop(0)

    alias_str = "; ".join(aliases) if aliases else None
    name1 = full_name
    name2 = aliases[0] if len(aliases) > 0 else None
    name3 = aliases[1] if len(aliases) > 1 else None
    name4 = aliases[2] if len(aliases) > 2 else None

    # --- address ---
    addr_parts = []
    addrs_el = el.find(_tag("addresses"))
    if addrs_el is not None:
        for addr_el in addrs_el.findall(_tag("address")):
            seg = []
            country_el = addr_el.find(_tag("country"))
            if country_el is not None and country_el.text:
                seg.append(country_el.text.strip())
            # addressParts
            for ap in addr_el.findall(f".//{_tag('addressPart')}"):
                val_el = ap.find(_tag("value"))
                if val_el is not None and val_el.text:
                    seg.append(val_el.text.strip())
            if seg:
                addr_parts.append(", ".join(seg))
    address = "; ".join(addr_parts) if addr_parts else None

    # --- features (DOB=8, POB=9, Nationality=10/11) ---
    dob = None
    pob = None
    nationality = None
    features_el = el.find(_tag("features"))
    if features_el is not None:
        for feat_el in features_el.findall(_tag("feature")):
            ftype_id = feat_el.get("featureTypeId", "")
            # Find versionDetail text value
            vd = feat_el.find(f".//{_tag('versionDetail')}")
            vd_text = (vd.text.strip() if vd is not None and vd.text else None)
            if not vd_text:
                continue
            if ftype_id == "8" and dob is None:
                dob = vd_text
            elif ftype_id == "9" and pob is None:
                pob = vd_text
            elif ftype_id in ("10", "11") and nationality is None:
                nationality = vd_text

    # --- identity documents ---
    passport_no = None
    identity_no = None
    docs_el = el.find(_tag("idRegDocuments"))
    if docs_el is not None:
        for doc_el in docs_el.findall(_tag("idRegDocument")):
            doc_type_el = doc_el.find(_tag("documentType"))
            doc_type = (doc_type_el.text.strip().lower() if doc_type_el is not None and doc_type_el.text else "")
            num_el = doc_el.find(_tag("registrationNumber"))
            number = (num_el.text.strip() if num_el is not None and num_el.text else None)
            if not number:
                continue
            if "passport" in doc_type and passport_no is None:
                passport_no = number
            elif identity_no is None:
                identity_no = number

    # --- sanctions programs as additional info ---
    programs = []
    progs_el = el.find(_tag("sanctionsPrograms"))
    if progs_el is not None:
        for prog_el in progs_el.findall(_tag("sanctionsProgram")):
            if prog_el.text:
                programs.append(prog_el.text.strip())
    additional_info = "Programs: " + ", ".join(programs) if programs else None

    return Entry(
        source_list="OFAC-SDN",
        entry_type=entry_type,
        full_name=_truncate(full_name, 255),
        name1=_truncate(name1, 255),
        name2=_truncate(name2, 255),
        name3=_truncate(name3, 255),
        name4=_truncate(name4, 255),
        tittle=_truncate(entity_id, 255),
        alias=_truncate(alias_str, 1024),
        dob=_truncate(dob, 255),
        pob=_truncate(pob, 255),
        nationality=_truncate(nationality, 255),
        passport_no=_truncate(passport_no, 255),
        identity_no=_truncate(identity_no, 255),
        address=_truncate(address, 4096),
        additional_info=_truncate(additional_info, 4096),
        load_date=date.today(),
    )


def parse_ofac_zip(file_bytes: bytes) -> list[Entry]:
    """Парсит OFAC SDN Enhanced ZIP файл, возвращает список Entry.

    Использует iterparse для потокового парсинга — не загружает весь XML в память,
    каждый обработанный <entity> очищается (el.clear()) для освобождения RAM.
    """
    entity_tag = _tag("entity")
    entries = []

    with zipfile.ZipFile(BytesIO(file_bytes)) as zf:
        xml_name = next((n for n in zf.namelist() if n.lower().endswith(".xml")), None)
        if not xml_name:
            logger.error("No XML file found inside OFAC ZIP")
            return []

        logger.info(f"Streaming XML from ZIP: {xml_name}")
        with zf.open(xml_name) as xml_stream:
            for event, el in ET.iterparse(xml_stream, events=("end",)):
                if el.tag != entity_tag:
                    continue
                try:
                    entry = _parse_entity(el)
                    if entry and entry.full_name:
                        entries.append(entry)
                except Exception as e:
                    eid = el.get("id", "?")
                    logger.warning(f"Failed to parse OFAC entity id={eid}: {e}")
                finally:
                    el.clear()  # освобождаем RAM сразу после обработки элемента

    logger.info(f"Parsed {len(entries)} entries from OFAC SDN Enhanced")
    return entries
