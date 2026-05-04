"""
Парсер UN Security Council Consolidated List XML.
Структура: <CONSOLIDATED_LIST> → <INDIVIDUALS>/<ENTITIES> → <INDIVIDUAL>/<ENTITY>
Без namespace.
"""
import logging
from datetime import date
from xml.etree import ElementTree as ET

from app.models import Entry

logger = logging.getLogger("garudar_api")


def _txt(el, tag: str) -> str | None:
    child = el.find(tag)
    if child is None or not child.text:
        return None
    v = child.text.strip()
    return v if v else None


def _truncate(s: str | None, n: int) -> str | None:
    if s is None:
        return None
    return s[:n] if len(s) > n else s


def _parse_individual(el) -> Entry:
    # --- full name from name parts ---
    parts = [_txt(el, k) for k in ("FIRST_NAME", "SECOND_NAME", "THIRD_NAME", "FOURTH_NAME")]
    parts = [p for p in parts if p]
    full_name = " ".join(parts) if parts else None

    # --- aliases ---
    aliases = []
    for alias_el in el.findall("INDIVIDUAL_ALIAS"):
        name = _txt(alias_el, "ALIAS_NAME")
        if name:
            aliases.append(name)

    alias_str = "; ".join(aliases) if aliases else None
    name1 = full_name
    name2 = aliases[0] if len(aliases) > 0 else None
    name3 = aliases[1] if len(aliases) > 1 else None
    name4 = aliases[2] if len(aliases) > 2 else None

    # --- DOB ---
    dob = None
    for dob_el in el.findall("INDIVIDUAL_DATE_OF_BIRTH"):
        date_val = _txt(dob_el, "DATE") or _txt(dob_el, "YEAR")
        from_yr = _txt(dob_el, "FROM_YEAR")
        to_yr = _txt(dob_el, "TO_YEAR")
        if date_val:
            dob = date_val
            break
        if from_yr and to_yr:
            dob = f"{from_yr}-{to_yr}"
            break
        if from_yr:
            dob = from_yr
            break

    # --- POB ---
    pob_parts = []
    pob_el = el.find("INDIVIDUAL_PLACE_OF_BIRTH")
    if pob_el is not None:
        for tag in ("CITY", "STATE_PROVINCE", "COUNTRY"):
            v = _txt(pob_el, tag)
            if v:
                pob_parts.append(v)
    pob = ", ".join(pob_parts) if pob_parts else None

    # --- nationality ---
    nat_el = el.find("NATIONALITY")
    nationality = _txt(nat_el, "VALUE") if nat_el is not None else None

    # --- documents ---
    passport_no = None
    identity_no = None
    for doc_el in el.findall("INDIVIDUAL_DOCUMENT"):
        doc_type = _txt(doc_el, "TYPE_OF_DOCUMENT") or ""
        number = _txt(doc_el, "NUMBER")
        if not number:
            continue
        if "passport" in doc_type.lower():
            passport_no = passport_no or number
        else:
            identity_no = identity_no or number

    # --- address ---
    addr_parts = []
    for addr_el in el.findall("INDIVIDUAL_ADDRESS"):
        seg = []
        for tag in ("STREET", "CITY", "STATE_PROVINCE", "COUNTRY"):
            v = _txt(addr_el, tag)
            if v:
                seg.append(v)
        if seg:
            addr_parts.append(", ".join(seg))
    address = "; ".join(addr_parts) if addr_parts else None

    # --- job title (DESIGNATION) ---
    job_parts = []
    for des_el in el.findall("DESIGNATION"):
        for val in des_el.findall("VALUE"):
            if val.text and val.text.strip():
                job_parts.append(val.text.strip())
    job_title = "; ".join(job_parts) if job_parts else None

    # --- additional info ---
    additional_info = _txt(el, "COMMENTS1")

    return Entry(
        source_list="UN-SC",
        entry_type="Individual",
        full_name=_truncate(full_name, 255),
        name1=_truncate(name1, 255),
        name2=_truncate(name2, 255),
        name3=_truncate(name3, 255),
        name4=_truncate(name4, 255),
        tittle=_truncate(_txt(el, "REFERENCE_NUMBER"), 255),
        alias=_truncate(alias_str, 1024),
        dob=_truncate(dob, 255),
        pob=_truncate(pob, 255),
        nationality=_truncate(nationality, 255),
        passport_no=_truncate(passport_no, 255),
        identity_no=_truncate(identity_no, 255),
        address=_truncate(address, 4096),
        job_title=_truncate(job_title, 2048),
        additional_info=_truncate(additional_info, 4096),
        load_date=date.today(),
    )


def _parse_entity(el) -> Entry:
    full_name = _txt(el, "FIRST_NAME")

    aliases = []
    for alias_el in el.findall("ENTITY_ALIAS"):
        name = _txt(alias_el, "ALIAS_NAME")
        if name:
            aliases.append(name)

    alias_str = "; ".join(aliases) if aliases else None
    name1 = full_name
    name2 = aliases[0] if len(aliases) > 0 else None
    name3 = aliases[1] if len(aliases) > 1 else None
    name4 = aliases[2] if len(aliases) > 2 else None

    addr_parts = []
    for addr_el in el.findall("ENTITY_ADDRESS"):
        seg = []
        for tag in ("STREET", "CITY", "STATE_PROVINCE", "COUNTRY"):
            v = _txt(addr_el, tag)
            if v:
                seg.append(v)
        if seg:
            addr_parts.append(", ".join(seg))
    address = "; ".join(addr_parts) if addr_parts else None

    additional_info = _txt(el, "COMMENTS1")

    return Entry(
        source_list="UN-SC",
        entry_type="Entity",
        full_name=_truncate(full_name, 255),
        name1=_truncate(name1, 255),
        name2=_truncate(name2, 255),
        name3=_truncate(name3, 255),
        name4=_truncate(name4, 255),
        tittle=_truncate(_txt(el, "REFERENCE_NUMBER"), 255),
        alias=_truncate(alias_str, 1024),
        address=_truncate(address, 4096),
        additional_info=_truncate(additional_info, 4096),
        load_date=date.today(),
    )


def parse_un_xml(xml_bytes: bytes) -> list[Entry]:
    """Парсит UN SC Consolidated List XML, возвращает список Entry."""
    root = ET.fromstring(xml_bytes)
    entries = []

    individuals_el = root.find("INDIVIDUALS")
    if individuals_el is not None:
        for ind in individuals_el.findall("INDIVIDUAL"):
            try:
                entries.append(_parse_individual(ind))
            except Exception as e:
                ref = _txt(ind, "REFERENCE_NUMBER") or "?"
                logger.warning(f"Failed to parse UN individual {ref}: {e}")

    entities_el = root.find("ENTITIES")
    if entities_el is not None:
        for ent in entities_el.findall("ENTITY"):
            try:
                entries.append(_parse_entity(ent))
            except Exception as e:
                ref = _txt(ent, "REFERENCE_NUMBER") or "?"
                logger.warning(f"Failed to parse UN entity {ref}: {e}")

    logger.info(f"Parsed {len(entries)} entries from UN SC Consolidated List")
    return entries
