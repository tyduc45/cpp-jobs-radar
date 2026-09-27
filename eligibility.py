"""Exclude explicit citizenship/residency/clearance restrictions in full JDs.

This is a text filter, not a determination of anyone's immigration or work rights.
No personal nationality, visa, or other applicant profile is stored here.
"""
import re
import unicodedata

SCREENING_VERSION = 1
NATIONALITY = (r"(?:US|UK|EU|UAE|United States|United Kingdom|American|Australian|British|Canadian|"
               r"European|New Zealand|German|French|Dutch|Swiss|Indian|Chinese|Japanese|Korean|Singaporean|Emirati|Saudi)")
IDENTITY = (r"(?:\bcitizen(?:ship|s)?\b|\bnationalit(?:y|ies)\b|\bnationals\b|"
            r"\bpermanent[ ,\-]+residen(?:t|ts|ce|cy)\b|\bgreen[ -]?card\b|"
            rf"\b(?:US|United States)[ -]+persons?\b|\b{NATIONALITY}\s+(?:national|passports?)\b|\bnational of\b)")
NECESSITY = (r"(?:\bmust\b|\brequir(?:e[ds]?|ement[s]?)\b|\bmandatory\b|\bessential\b|"
             r"\bonly\b|\blimited to\b|\brestricted to\b|\bcondition of employment\b)")
CLEARANCE = r"(?:security clearances?|(?:secret|top[ -]secret|TS(?:/SCI)?|NV1|NV2|SC|DV|baseline)\s+(?:security\s+)?clearances?)"
RULES = [
    ("citizenship_or_residency", rf"{NECESSITY}[^.!?;]{{0,180}}{IDENTITY}"),
    ("citizenship_or_residency", rf"{IDENTITY}[^.!?;]{{0,110}}{NECESSITY}"),
    ("citizenship_or_residency", rf"\b(?:hold|possess|have|proof of)\b[^.!?;]{{0,65}}{IDENTITY}"),
    ("citizenship_or_residency", rf"\b(?:eligible|eligibility|ineligible|ineligibility|excluded|not eligible)\b[^.!?;]{{0,200}}{IDENTITY}"),
    ("citizenship_or_residency", rf"{IDENTITY}[^.!?;]{{0,100}}\b(?:ineligible|not eligible|not accepted|not considered)\b"),
    ("nationality_restriction", r"\bnationality (?:checks?|restrictions?|requirements?|eligibility)\b"),
    ("nationality_restriction", rf"\b(?:citizenship|nationality)\s*:\s*{NATIONALITY}\b"),
    ("nationality_restriction", r"\b(?:citizens?|nationals?|passport holders?) of\b[^.!?;]{0,120}\b(?:only|eligible|ineligible|cannot|unable|not eligible)\b"),
    ("security_clearance", rf"{NECESSITY}[^.!?;]{{0,120}}{CLEARANCE}"),
    ("security_clearance", rf"{CLEARANCE}[^.!?;]{{0,100}}{NECESSITY}"),
    ("security_clearance", rf"\b(?:eligible|eligibility|ability|able|obtain|maintain|hold|possess)\b[^.!?;]{{0,100}}{CLEARANCE}"),
    ("security_clearance", rf"{CLEARANCE}\s+(?:or\s+)?(?:ability|eligible|eligibility|must|is required)\b"),
    ("security_clearance", rf"\b(?:active|current)\b[^.!?;]{{0,85}}{CLEARANCE}"),
    ("citizenship_or_residency", r"(?:必须|须|仅限|限于|要求|需具备|需持有)[^。；!?]{0,35}(?:国籍|公民|永久居留|永居|绿卡)"),
    ("citizenship_or_residency", r"(?:国籍|公民|永久居留|永居|绿卡)[^。；!?]{0,25}(?:要求|必须|限定|仅限)"),
    ("citizenship_or_residency", r"(?:citoyennet[eé]|nationalit[eé]|r[eé]sidence permanente)[^.!?;]{0,60}(?:requise|obligatoire|exig[eé]e)"),
    ("citizenship_or_residency", r"(?:staatsb[uü]rgerschaft|staatsangeh[oö]rigkeit)[^.!?;]{0,60}(?:erforderlich|voraussetzung)"),
]
COMPILED_RULES = [(reason, re.compile(pattern, re.I)) for reason, pattern in RULES]
NEGATED = [
    r"\bfirst[ -]class citizens?\b",
    r"\bDepending on your nationality and country of residence[^.!?;]*[.!?;]",
    rf"{IDENTITY}\s+(?:is |are )?(?:not required|not necessary|not mandatory)",
    rf"\b(?:no|without)\s+{IDENTITY}\s+(?:requirement|restriction)s?",
    rf"\b(?:not required|do not need|don't need)\s+to\s+(?:be|have|hold)\s+(?:a\s+)?(?:US\s+|Australian\s+|British\s+)?{IDENTITY}",
    rf"\bno\s+{CLEARANCE}\s+(?:is\s+)?required",
    rf"{CLEARANCE}\s+(?:is\s+)?(?:not required|not necessary)",
]


def normalized(text):
    text = unicodedata.normalize("NFKC", str(text or ""))
    text = text.replace("’", "'").replace("–", "-").replace("—", "-")
    text = re.sub(r"\bU\.\s*S\.(?:\s*A\.)?", "US", text, flags=re.I)
    text = re.sub(r"\bU\.\s*K\.", "UK", text, flags=re.I)
    text = re.sub(r"\b(?:e\.g\.|i\.e\.)", "for example", text, flags=re.I)
    return re.sub(r"\s+", " ", text).strip()


def screen_job(title, description):
    """Return evidence and a version; missing full descriptions stay unreviewed."""
    text = normalized(title + ". " + description)
    for pattern in NEGATED:
        text = re.sub(pattern, " [explicitly not required] ", text, flags=re.I)
    reasons, evidence = [], []
    for reason, pattern in COMPILED_RULES:
        for match in pattern.finditer(text):
            fragment = match.group()
            # A negative EEO statement or optional clearance is not a requirement.
            before = text[max(0, match.start() - 110):match.start()]
            after = text[match.end():match.end() + 55]
            if re.search(r"without regard|regardless of|do not discriminate|not discriminate|not be influenced|irrespective of", fragment, re.I):
                continue
            if re.search(r"(?:without regard|regardless of|irrespective of|do not discriminate|not discriminate)[^.!?;]*$", before, re.I) and not re.match(NECESSITY, fragment, re.I):
                continue
            if reason == "security_clearance":
                # A following PREFERRED QUALIFICATIONS heading starts a new section;
                # it must never make the preceding mandatory bullet look optional.
                if re.search(r"\b(?:is preferred|is desirable|a plus|not required)\b", fragment, re.I):
                    continue
                if re.match(r"\s+(?:(?:is|are|would be)\s+)?(?:preferred(?!\s+(?:qualifications|requirements))|desirable|a plus|not required)\b", after, re.I):
                    continue
                if re.search(r"(?:preferred qualifications|nice to have|nice-to-have|desirable qualifications)\s*:?[^.!?;]*$", before, re.I) and not re.search(NECESSITY, fragment, re.I):
                    continue
            if reason not in reasons:
                reasons.append(reason)
                evidence.append(text[max(0, match.start() - 30):match.end() + 80][:320])
            break
    return {"version": SCREENING_VERSION if description.strip() else 0,
            "excluded": bool(reasons), "reasons": reasons, "evidence": evidence}


def passes_screening(job):
    screening = job.get("screening") or {}
    return screening.get("version") == SCREENING_VERSION and screening.get("excluded") is False


def is_visible(job):
    return job.get("active", False) and passes_screening(job)
