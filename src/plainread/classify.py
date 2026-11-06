"""Work out what kind of letter this is and who sent it."""

from __future__ import annotations

import re

from plainread.text import Segment

# (pattern, weight). Weights are rough evidence strengths; the top score wins.
_TYPE_CUES: dict[str, list[tuple[str, float]]] = {
    "court": [
        (
            r"\bsuperior court\b|\bdistrict court\b|\bcircuit court\b|\bmunicipal court\b|\bsmall claims\b",
            4,
        ),
        (r"\btraffic court\b|\bcourt of\b|\bcounty court\b|\bclerk of (?:the )?court\b", 4),
        (r"\bplaintiff\b|\bdefendant\b|\bsummons\b|\bdocket\b|\bcourtroom\b|\bjudge\b", 2),
        (r"\bjury\b|\bjuror\b|\bcitation\b|\barraignment\b|\bviolation\b", 2),
    ],
    "housing": [
        (r"\btenant\b|\blandlord\b|\blease\b|\brent\b|\bevict", 2),
        (
            r"\bnotice to (?:quit|vacate|pay)\b|\bhousing authority\b|\bpublic housing\b|\bhousing choice\b",
            4,
        ),
        (r"\brecertification\b|\bunit\b|\bapartment\b|\bproperty management\b", 1),
    ],
    "medical_bill": [
        (r"\bstatement\b|\bamount due\b|\bpatient (?:account|balance)\b|\bguarantor\b", 2),
        (r"\bhospital\b|\bmedical center\b|\bfinancial assistance\b|\bcharity care\b", 2),
        (r"\bdate of service\b|\bdates of service\b|\bitemized\b", 2),
    ],
    "health_insurance": [
        (
            r"\bexplanation of benefits\b|\bprior authorization\b|\bin-network\b|\bout-of-network\b",
            4,
        ),
        (
            r"\bhealth plan\b|\bmember id\b|\bmember services\b|\bdeductible\b|\bcoinsurance\b|\bcopay",
            3,
        ),
        (r"\bmedically necessary\b|\bexternal review\b|\bclaim\b|\bdenied\b|\bprovider\b", 1),
    ],
    "insurance": [
        (
            r"\bauto (?:insurance|policy)\b|\bhomeowners?\b|\brenters insurance\b|\bpolicyholder\b",
            4,
        ),
        (r"\bpolicy number\b|\bpremium\b|\bcancell?ation\b|\binsured\b|\bvehicle\b", 2),
        (r"\bcoverage\b", 1),
    ],
    "benefits": [
        (r"\bdepartment of (?:human|social|health and human) services\b|\bsocial services\b", 6),
        (
            r"\bcaseworker\b|\beligibility determination\b|\bfair hearing\b|\bhealth ?care program\b",
            3,
        ),
        (
            r"\bfood assistance\b|\bnutrition assistance\b|\bcash assistance\b|\bhealth coverage program\b",
            4,
        ),
        (
            r"\bbenefits?\b|\beligibility\b|\brenewal\b|\bcase number\b|\bhousehold\b|\bcaseworker\b",
            1.5,
        ),
        (r"\bretirement\b|\bdisability\b|\bpension\b|\bmonthly benefit\b|\bannuity\b", 2),
    ],
    "tax": [
        (
            r"\bdepartment of (?:revenue|taxation|finance)\b|\btax(?:es)?\b|\btaxpayer\b|\btax year\b",
            3,
        ),
        (r"\bpenalty\b|\binterest\b|\bassessment\b|\breturn\b|\brefund\b", 1),
    ],
    "utility": [
        (r"\belectric\b|\bgas\b|\bwater\b|\bpower\b|\butility\b|\benergy\b", 2),
        (r"\bdisconnect|\bshut ?off\b|\bservice address\b|\bmeter\b|\bkwh\b", 3),
    ],
    "debt": [
        (r"\bdebt collector\b|\bcollection agency\b|\bthis is an attempt to collect a debt\b", 5),
        (r"\boriginal creditor\b|\bcreditor\b|\bvalidation\b|\bdispute (?:the|this|all|any)\b", 3),
        (
            r"\bstudent loans?\b|\bloan servic\w+\b|\bborrower\b|\bdelinquen\w+\b|\bdefault(?:ed)?\b",
            3,
        ),
        (r"\bgarnish", 3),
    ],
    "immigration": [
        (r"\bimmigration\b|\bbiometrics?\b|\bapplication support center\b|\breceipt number\b", 4),
        (r"\bpetition\b|\bvisa\b|\bnaturali[sz]ation\b|\bpermanent resident\b|\bwork permit\b", 3),
    ],
    "school": [
        (r"\bschool district\b|\belementary\b|\bmiddle school\b|\bhigh school\b|\bprincipal\b", 4),
        (r"\battendance\b|\btruan|\bstudent\b|\bparent\b|\bguardian\b|\babsences?\b", 2),
    ],
    "employment": [
        (r"\bunemployment\b|\bworkforce\b|\bemployment security\b|\bclaimant\b", 4),
        (
            r"\bworkers'? comp(?:ensation)?\b|\bwork(?:place)? injury\b|\binjured worker\b|\bon the job\b",
            5,
        ),
        (r"\bemployer\b|\bwages\b|\bweekly benefit\b|\bseparation\b", 2),
    ],
    "general": [
        (
            r"\bbank\b|\bcredit union\b|\bchecking\b|\bsavings\b|\bdebit card\b|\baccount ending\b",
            2,
        ),
        (
            r"\baddress (?:change|update)\b|\bchange of address\b|\bno action is needed\b|\bdo not need to (?:do|take)\b",
            3,
        ),
    ],
    "medical": [
        (r"\bclinic\b|\bprocedure\b|\bcolonoscopy\b|\bappointment\b|\bpatient\b|\bphysician\b", 2),
        (r"\bprep(?:aration)?\b|\bsedation\b|\bclear liquids\b|\bcheck-in\b|\barrive\b", 2),
    ],
}

_ORG_WORDS = re.compile(
    r"\b(?:court|department|dept|office|hospital|health|medical|clinic|center|centre|insurance|"
    r"assurance|mutual|agency|services|authority|bank|credit|union|company|cooperative|co-op|"
    r"utilit(?:y|ies)|electric|energy|water|gas|power|school|district|academy|university|county|"
    r"state|city|commonwealth|commission|administration|bureau|board|division|program|partners|"
    r"llc|inc|corp|corporation|associates|law|group|collections?|recovery|financial|management|"
    r"properties|realty|apartments|housing|revenue|treasury|workforce|security|plan)\b",
    re.IGNORECASE,
)
_NOT_SENDER = re.compile(
    r"^(?:re|subject|date|to|dear|notice|page|case|account|claim|member|policy|regarding|attn)\b"
    r"|\d{3}[\s.\-]\d{4}|@|www\.|https?://",
    re.IGNORECASE,
)


def classify(text: str) -> str:
    lowered = text.lower()
    scores: dict[str, float] = {}
    for letter_type, cues in _TYPE_CUES.items():
        score = 0.0
        for pattern, weight in cues:
            hits = len(re.findall(pattern, lowered))
            score += weight * min(hits, 4)
        scores[letter_type] = score
    best = max(scores, key=lambda k: scores[k])
    if scores[best] < 4:
        return "general"
    return best


_FIRM = re.compile(
    r"&|\b(?:p\.?c\.?|l\.?l\.?p\.?|p\.?a\.?|llc|inc\.?|ltd\.?)(?:\W|$)", re.IGNORECASE
)
_JURISDICTION = re.compile(
    r"^(?:the\s+)?(?:state|county|city|commonwealth|town|village|republic)\s+of\b", re.I
)


def _org_like(line: str) -> bool:
    if _NOT_SENDER.search(line) or len(line) > 80 or len(line) < 3:
        return False
    if re.match(r"^[^:]{2,45}:\s*\S", line):
        return False  # "Employer: ...", "Plaintiff (landlord): ..."
    if re.search(r"\d", line) and not _ORG_WORDS.search(line):
        return False
    return bool(_ORG_WORDS.search(line) or _FIRM.search(line))


def find_sender(segments: list[Segment]) -> Segment | None:
    """The organisation in the letterhead (or, failing that, the signature).

    When the letterhead starts with a jurisdiction ("STATE OF WESTMARA") or a
    firm name followed by a department or description, both lines are used.
    """
    head = [s for s in segments[:8] if s.is_line or s.words <= 10]
    for i, seg in enumerate(head):
        if not _org_like(seg.clean):
            continue
        nxt = head[i + 1] if i + 1 < len(head) else None
        if (
            nxt is not None
            and nxt.block == seg.block
            and _org_like(nxt.clean)
            and (_JURISDICTION.match(seg.clean) or _FIRM.search(seg.clean) or seg.clean.isupper())
            and not re.search(r"\d", nxt.clean)
        ):
            return Segment(seg.start, nxt.end, seg.text + "\n" + nxt.text, seg.block, True)
        return seg
    # Signature block: the line after "Sincerely," that names an organisation.
    for i, seg in enumerate(segments):
        if re.match(r"^(?:sincerely|respectfully|regards|thank you)", seg.clean, re.I):
            for nxt in segments[i + 1 : i + 5]:
                if _ORG_WORDS.search(nxt.clean) and not _NOT_SENDER.search(nxt.clean):
                    return nxt
    for seg in head:
        if not _NOT_SENDER.search(seg.clean) and not re.search(r"\d", seg.clean):
            return seg
    return None
