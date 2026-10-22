"""Action-scoped pseudonyms, unambiguous name aliases and coarse descriptions."""

import hashlib
import re
import unicodedata
from collections import Counter, defaultdict

from faker import Faker


RULES_VERSION = "consistent_surrogates_v1"
RULE_CONFIGURATION = {
    "scope": "one A0 action, shared by all outbound fields",
    "seed": "BLAKE2b of source scope, entity type and canonical surface",
    "person_aliases": "unique full name, given name, surname and titled surname",
    "gender": "honorific, then exclusive Faker English name-list hint, otherwise unknown",
    "locales": {"default": "en_US", "CJK": "zh_CN"},
    "temporal_policy": "coarse periods and month-level descriptions",
    "organization_policy": "synthetic names with recognizable organization suffixes",
    "location_policy": "coarse areas; explicit Chinese city/district suffixes retain the city",
}
TITLE = re.compile(r"^(Mr\.?|Mrs\.?|Ms\.?|Miss|Dr\.?|Prof\.?)\s+", re.I)
CJK = re.compile(r"[\u3400-\u9fff]")
ZH_TITLE = re.compile(r"(先生|女士|小姐|总|经理|博士|教授)$")
COMPOUND_SURNAMES = ("欧阳", "司马", "诸葛", "上官", "夏侯", "司徒", "司空", "皇甫", "尉迟", "公孙", "慕容", "令狐")
ORG_SUFFIXES = {
    "bank": "Bank", "airlines": "Airlines", "airline": "Airlines", "hotel": "Hotel",
    "hotels": "Hotels", "hospital": "Hospital", "university": "University", "solutions": "Solutions",
    "inc": "Inc.", "ltd": "Ltd.", "corp": "Corp.", "corporation": "Corporation", "company": "Company",
}
MONTHS = "January February March April May June July August September October November December".split()


def normalize(text):
    return " ".join(unicodedata.normalize("NFKC", text).split()).casefold()


def person_parts(text):
    text = text.strip()
    title = TITLE.match(text)
    zh_title = ZH_TITLE.search(text)
    prefix = title.group() if title else ""
    suffix = zh_title.group() if zh_title else ""
    bare = text[len(prefix):len(text) - len(suffix) if suffix else None]
    if CJK.search(bare):
        last = next((name for name in COMPOUND_SURNAMES if bare.startswith(name)), bare[:1])
        first = bare[len(last):]
    else:
        tokens = bare.split()
        first, last = (tokens[0], tokens[-1]) if len(tokens) > 1 else (bare, bare)
    gender = "male" if normalize(prefix).rstrip(".") == "mr" or suffix == "先生" else "female" if normalize(prefix).rstrip(".") in ("mrs", "ms", "miss") or suffix in ("女士", "小姐") else "unknown"
    return {"bare": bare, "first": first, "last": last, "prefix": prefix, "suffix": suffix, "gender": gender}


def generalize(entity_type, text):
    """Use literal suffixes and time formats to retain a coarser description."""
    if entity_type == "LOCATION" and CJK.search(text):
        city = re.match(r"(.+?市).+(?:区|县)", text)
        if city:
            return city[1] + "某区"
    if entity_type == "ORGANIZATION" and CJK.search(text):
        for suffix in ("银行", "医院", "大学", "公司"):
            if suffix in text:
                return "某" + suffix
    if entity_type != "DATE_TIME":
        return None
    clock = re.fullmatch(r"(\d{1,2})(?::\d{2})?\s*(AM|PM)?", text, re.I)
    if clock:
        hour = int(clock[1]) % 12 + (12 if (clock[2] or "").upper() == "PM" else 0) if clock[2] else int(clock[1])
        return "a morning hour" if 5 <= hour < 12 else "an afternoon hour" if 12 <= hour < 18 else "an evening hour" if 18 <= hour < 23 else "a late-night hour"
    for month in MONTHS:
        if re.search(rf"\b{month}\b", text, re.I):
            year = re.search(r"\b(?:19|20)\d{2}\b", text)
            return f"some days in {month}" + (f" {year[0]}" if year else "")
    if re.fullmatch(r"\d{1,2}(?:st|nd|rd|th)", text, re.I):
        return "another day that month"
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return f"some days in {MONTHS[int(text[5:7]) - 1]} {text[:4]}"
    # 已经宽泛的时间词保留其粒度，精确但未解析的表达使用自然概括。
    if normalize(text) in {"night", "day", "morning", "afternoon", "evening", "today", "tomorrow", "yesterday", "next week", "this week", "last week", "next month", "this month", "last month"}:
        return text
    if normalize(text) in {"monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"}:
        return "a weekday" if normalize(text) not in {"saturday", "sunday"} else "a weekend day"
    return "an unspecified date"


def accept_candidate(entity_type, text, tokens=(), following_text=""):
    # 句式标题与长段落按正文处理，机构名采用短命名片段。
    if entity_type == "PERSON" and any(token.pos_ in ("VERB", "AUX") and token.text.islower() for token in tokens):
        return False
    if entity_type == "ORGANIZATION" and text.split()[-1].lower().rstrip(".") not in ORG_SUFFIXES and re.match(r"\s+(?:campaign|project|course|seminar)\b", following_text, re.I):
        return False
    return entity_type != "ORGANIZATION" or (len(text.split()) <= 8 and not re.search(r"[:\n!?]", text))


class ReplacementSession:
    def __init__(self, scope, detected):
        self.scope = scope
        self.clusters = []
        self.aliases = defaultdict(set)
        self.surfaces = defaultdict(set)
        self.lookup = {}
        self.counts = Counter()
        self.used_names = set()
        self.realized = {}
        self.applied = {}
        self.original_words = {
            normalize(word) for kind, text in detected if kind == "PERSON"
            for parts in [person_parts(text)]
            for word in (parts["bare"], parts["first"], parts["last"], *parts["bare"].split()) if word
        }
        # 先登记长姓名与机构名，再将唯一可匹配的简称归入已有簇。
        def order(item):
            kind, text = item
            bare = person_parts(text)["bare"] if kind == "PERSON" else text
            full_person = len(bare.split()) > 1 or (CJK.search(bare) and len(bare) > 2)
            return (0 if kind == "PERSON" and full_person else 1 if kind == "PERSON" else 2 if kind == "ORGANIZATION" else 3, -len(bare), text, kind)

        ordered = sorted(set(detected), key=order)
        for kind, text in ordered:
            self.cluster_for(kind, text)

    def alias_key(self, kind, text):
        if kind in ("PHONE_NUMBER", "CREDIT_CARD", "US_SSN", "IBAN_CODE"):
            return kind, re.sub(r"\W", "", text).casefold()
        return kind, normalize(person_parts(text)["bare"] if kind == "PERSON" else text)

    def cluster_for(self, kind, text):
        key = self.alias_key(kind, text)
        if key in self.lookup:
            cluster = self.clusters[self.lookup[key]]
        else:
            candidates = self.aliases[key]
            if kind == "NRP":
                candidates = candidates | self.aliases[("ORGANIZATION", normalize(text))]
            if len(candidates) == 1:
                cluster = self.clusters[next(iter(candidates))]
            else:
                self.counts[kind] += 1
                cluster = {
                    "index": len(self.clusters), "cluster_id": f"{kind}_{self.counts[kind]}",
                    "entity_type": kind, "canonical": person_parts(text)["bare"] if kind == "PERSON" else text,
                    "surfaces": [], "genders": set(), "ambiguous_alias": len(candidates) > 1,
                }
                self.clusters.append(cluster)
            self.lookup[key] = cluster["index"]
        if text not in cluster["surfaces"]:
            cluster["surfaces"].append(text)
        if kind == "PERSON":
            cluster["genders"].add(person_parts(text)["gender"])
        self.register_aliases(cluster, text)
        return cluster

    def register_aliases(self, cluster, text):
        kind = cluster["entity_type"]
        aliases = {text, cluster["canonical"]}
        if kind == "PERSON":
            parts = person_parts(cluster["canonical"])
            aliases.update((parts["first"], parts["last"]))
        elif kind == "ORGANIZATION":
            tokens = cluster["canonical"].split()
            if len(tokens) > 1 and tokens[-1].lower().rstrip(".") in ORG_SUFFIXES:
                aliases.add(" ".join(tokens[:-1]))
        for alias in aliases - {""}:
            key = self.alias_key(kind, alias)
            self.aliases[key].add(cluster["index"])
            self.surfaces[key].add(alias)

    def alias_mentions(self, text):
        mentions = []
        for key, indices in self.aliases.items():
            if key[0] not in ("PERSON", "ORGANIZATION") or len(indices) != 1:
                continue
            cluster = self.clusters[next(iter(indices))]
            for alias in self.surfaces[key]:
                bare = person_parts(alias)["bare"] if key[0] == "PERSON" else alias
                prefix = r"(?:(?i:Mr\.?|Mrs\.?|Ms\.?|Miss|Dr\.?|Prof\.?)\s+)?" if key[0] == "PERSON" else ""
                suffix = r"(?:先生|女士|小姐|总|经理|博士|教授)?" if key[0] == "PERSON" and CJK.search(bare) else ""
                left, right = (r"(?<![A-Za-z0-9])", r"(?![A-Za-z0-9])") if CJK.search(bare) else (r"(?<!\w)", r"(?!\w)")
                if key[0] == "PERSON" and CJK.search(bare) and len(bare) <= 2 and bare == person_parts(cluster["canonical"])["last"]:
                    suffix = r"(?:先生|女士|小姐|总|经理|博士|教授)"
                for match in re.finditer(rf"{left}{prefix}{re.escape(bare)}{suffix}{right}", text):
                    mentions.append({"start": match.start(), "end": match.end(), "entity_type": cluster["entity_type"], "cluster_id": cluster["cluster_id"]})
        return mentions

    def fake_for(self, cluster):
        locale = "zh_CN" if CJK.search(cluster["canonical"]) else "en_US"
        fake = Faker(locale)
        seed_text = f"{self.scope}|{cluster['entity_type']}|{normalize(cluster['canonical'])}"
        fake.seed_instance(int.from_bytes(hashlib.blake2b(seed_text.encode(), digest_size=8).digest(), "big"))
        return fake, locale

    def identity(self, cluster):
        cluster_id = cluster["cluster_id"]
        if cluster_id not in self.realized:
            fake, locale = self.fake_for(cluster)
            genders = cluster["genders"] - {"unknown"}
            gender = next(iter(genders)) if len(genders) == 1 else "unknown"
            gender_basis = "honorific" if gender != "unknown" else "unknown"
            if cluster["entity_type"] == "PERSON" and not genders and locale == "en_US":
                provider = fake.first_name.__self__
                first_name = normalize(person_parts(cluster["canonical"])["first"])
                male = first_name in {normalize(name) for name in provider.first_names_male}
                female = first_name in {normalize(name) for name in provider.first_names_female}
                if male != female:
                    gender, gender_basis = ("male" if male else "female"), "Faker_name_list_hint"
            if cluster["entity_type"] == "PERSON":
                while True:
                    first = fake.first_name_male() if gender == "male" else fake.first_name_female() if gender == "female" else fake.first_name()
                    last = fake.last_name()
                    names = {normalize(first), normalize(last)}
                    if not names & (self.original_words | self.used_names):
                        self.used_names.update(names)
                        break
                value = {"first": first, "last": last, "full": last + first if locale == "zh_CN" else f"{first} {last}"}
            else:
                value = {"full": self.make_value(cluster, fake)}
            coarse = generalize(cluster["entity_type"], cluster["canonical"])
            strategy = "faker_person" if cluster["entity_type"] == "PERSON" else "generalization" if coarse is not None or cluster["entity_type"] == "LOCATION" else "faker"
            self.realized[cluster_id] = {**value, "locale": locale, "gender": gender, "gender_basis": gender_basis, "strategy": strategy}
        return self.realized[cluster_id]

    def make_value(self, cluster, fake):
        kind, text = cluster["entity_type"], cluster["canonical"]
        coarse = generalize(kind, text)
        if coarse is not None:
            return coarse
        if kind == "ORGANIZATION":
            suffix = ORG_SUFFIXES.get(text.split()[-1].lower().rstrip("."))
            return f"{fake.last_name()} {suffix}" if suffix else fake.company()
        if kind == "LOCATION":
            number = int(cluster["cluster_id"].rsplit("_", 1)[1])
            ordinal = {1: "first", 2: "second", 3: "third"}.get(number, f"{number}th")
            return "the area" if self.counts[kind] == 1 else f"the {ordinal} area"
        if kind == "EMAIL_ADDRESS":
            return fake.user_name() + "@example.invalid"
        if kind in ("PHONE_NUMBER", "CREDIT_CARD", "US_SSN", "IBAN_CODE"):
            return fake.bothify(re.sub(r"[A-Za-z]", "?", re.sub(r"\d", "#", text)), letters="ABCDEFGHIJKLMNOPQRSTUVWXYZ")
        return "a community"

    def replacement(self, kind, text):
        cluster = self.cluster_for(kind, text)
        identity = self.identity(cluster)
        value = identity["full"]
        if kind in ("PHONE_NUMBER", "CREDIT_CARD", "US_SSN", "IBAN_CODE"):
            characters = iter(re.sub(r"\W", "", value))
            value = "".join(next(characters) if character.isalnum() else character for character in text)
        if cluster["entity_type"] == "PERSON":
            parts = person_parts(text)
            original = person_parts(cluster["canonical"])
            if parts["prefix"] or parts["suffix"]:
                value = identity["full"] if len(parts["bare"].split()) > 1 and not CJK.search(parts["bare"]) else identity["last"]
            elif normalize(parts["bare"]) != normalize(cluster["canonical"]):
                value = identity["first"] if normalize(parts["bare"]) == normalize(original["first"]) else identity["last"]
            elif len(parts["bare"].split()) == 1 and not CJK.search(parts["bare"]):
                value = identity["last"] if any(person_parts(surface)["prefix"] for surface in cluster["surfaces"]) else identity["first"]
            value = parts["prefix"] + value + parts["suffix"]
        self.applied[(kind, text)] = {"cluster_id": cluster["cluster_id"], "text": text, "replacement": value, "entity_type": cluster["entity_type"]}
        return value

    def export(self):
        return {
            "clusters": [
                {"cluster_id": cluster["cluster_id"], "entity_type": cluster["entity_type"], "canonical": cluster["canonical"], "surfaces": cluster["surfaces"], "ambiguous_alias": cluster["ambiguous_alias"], **self.realized[cluster["cluster_id"]]}
                for cluster in self.clusters if cluster["cluster_id"] in self.realized
            ],
            "mappings": list(self.applied.values()),
        }
