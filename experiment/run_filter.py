"""Derive A2 actions with local Presidio patterns and named entity recognition."""

from copy import deepcopy
from datetime import datetime, timezone
from importlib.metadata import version
from time import perf_counter

import tldextract
from presidio_analyzer import AnalyzerEngine, Pattern, PatternRecognizer, RecognizerRegistry, RecognizerResult
from presidio_analyzer.nlp_engine import NlpEngineProvider
from presidio_analyzer.predefined_recognizers import (
    CreditCardRecognizer,
    EmailRecognizer,
    IbanRecognizer,
    PhoneRecognizer,
    SpacyRecognizer,
    UsSsnRecognizer,
)
from presidio_anonymizer import AnonymizerEngine
from presidio_anonymizer.entities import ConflictResolutionStrategy, OperatorConfig

from .common import ROOT, append_jsonl, project_path, read_jsonl, select_records, write_json
from .pii_rules import RULE_CONFIGURATION, RULES_VERSION, ReplacementSession, accept_candidate


FILTER_VERSION = "presidio_faker_v4"
NER_ENTITIES = ["PERSON", "LOCATION", "DATE_TIME", "ORGANIZATION", "NRP"]
ENTITIES = ["EMAIL_ADDRESS", "PHONE_NUMBER", "CREDIT_CARD", "IBAN_CODE", "US_SSN", *NER_ENTITIES]
SCORE_THRESHOLD = 0.4
LANGUAGE = "en"
NLP_MODEL = "en_core_web_sm"
NLP_CONFIGURATION = {
    "nlp_engine_name": "spacy",
    "models": [{"lang_code": LANGUAGE, "model_name": NLP_MODEL}],
    "ner_model_configuration": {
        "default_score": 0.85,
        "model_to_presidio_entity_mapping": {
            "PERSON": "PERSON", "ORG": "ORGANIZATION", "GPE": "LOCATION", "LOC": "LOCATION",
            "FAC": "LOCATION", "DATE": "DATE_TIME", "TIME": "DATE_TIME", "NORP": "NRP",
        },
        "labels_to_ignore": [
            "CARDINAL", "EVENT", "LANGUAGE", "LAW", "MONEY", "ORDINAL", "PERCENT",
            "PRODUCT", "QUANTITY", "WORK_OF_ART",
        ],
    },
}
NAME_TOKEN = r"(?-i:[A-Z][a-z]+(?:[-'][A-Z]?[a-z]+)*)"
PERSON_NAME = rf"{NAME_TOKEN}(?:[ \t]+{NAME_TOKEN}){{0,2}}"
PERSON_PATTERNS = [
    {"name": "titled_name", "regex": rf"\b(?:Mr|Mrs|Ms|Miss|Dr|Prof)\.?\s+{PERSON_NAME}\b", "score": 0.7},
    {
        "name": "greeting_name",
        "regex": rf"(?:(?<=Hi )|(?<=Hello )|(?<=Dear )|(?<=Hey )){PERSON_NAME}(?=\s*[,!:])",
        "score": 0.7,
    },
]
OUTBOUND_FIELDS = {
    "FacebookManagerCreatePost": ("content",),
    "GmailSendEmail": ("subject", "body"),
    "MessengerSendMessage": ("message",),
    "SlackSendMessage": ("message",),
}
POSITION_CONVENTION = "Original field Python character indices, half-open [start, end)"


class AuditedAnonymizer(AnonymizerEngine):
    """Capture source spans at Presidio 2.2.364's operation boundary."""

    def _operate(self, text, pii_entities, operators_metadata, operator_type, **kwargs):
        self.source_spans = [
            {"entity_type": entity.entity_type, "start": entity.start, "end": entity.end, "score": entity.score}
            for entity in sorted(pii_entities, key=lambda entity: (entity.start, entity.end))
        ]
        return super()._operate(text, pii_entities, operators_metadata, operator_type, **kwargs)


class PiiFilter:
    def __init__(self):
        self.versions = {
            package: version(package)
            for package in ("presidio-analyzer", "presidio-anonymizer", "spacy", NLP_MODEL, "tldextract", "Faker")
        }
        # The predefined email validator uses the bundled public suffix snapshot.
        tldextract.extract = tldextract.TLDExtract(suffix_list_urls=(), cache_dir=None)
        nlp_engine = NlpEngineProvider(nlp_configuration=NLP_CONFIGURATION).create_engine()
        # NER 提供人名等语义实体；称谓和问候语规则补充英文姓名识别。
        registry = RecognizerRegistry(
            supported_languages=[LANGUAGE],
            recognizers=[
                EmailRecognizer(), PhoneRecognizer(), CreditCardRecognizer(), IbanRecognizer(), UsSsnRecognizer(),
                SpacyRecognizer(supported_entities=NER_ENTITIES),
                PatternRecognizer(
                    name="PersonContextRecognizer", supported_entity="PERSON", supported_language=LANGUAGE,
                    patterns=[Pattern(**pattern) for pattern in PERSON_PATTERNS],
                ),
            ],
        )
        self.analyzer = AnalyzerEngine(registry=registry, nlp_engine=nlp_engine, supported_languages=[LANGUAGE])
        self.anonymizer = AuditedAnonymizer()

    def analyze_text(self, text):
        artifacts = self.analyzer.nlp_engine.process_text(text, LANGUAGE)
        findings = self.analyzer.analyze(text=text, language=LANGUAGE, entities=ENTITIES, score_threshold=SCORE_THRESHOLD, nlp_artifacts=artifacts)
        accepted = [
            finding for finding in findings
            if accept_candidate(
                finding.entity_type, text[finding.start:finding.end],
                [token for token in artifacts.tokens if finding.start <= token.idx < finding.end], text[finding.end:],
            )
        ]
        discarded = [
            {"entity_type": finding.entity_type, "start": finding.start, "end": finding.end, "text": text[finding.start:finding.end], "reason": "sentence-like span or topic name"}
            for finding in findings if finding not in accepted
        ]
        return accepted, discarded

    def filter_text(self, text, session=None, analysis=None):
        findings, discarded = self.analyze_text(text) if analysis is None else analysis
        findings = list(findings)
        if session is None:
            session = ReplacementSession(f"standalone:{RULES_VERSION}", [(finding.entity_type, text[finding.start:finding.end]) for finding in findings])
        # 将动作内唯一可归并的简称补为候选，复用同一实体簇。
        for alias in session.alias_mentions(text):
            if any(finding.entity_type not in NER_ENTITIES and finding.start < alias["end"] and alias["start"] < finding.end for finding in findings):
                continue
            if any(finding.entity_type != alias["entity_type"] and finding.start <= alias["start"] and alias["end"] <= finding.end and finding.end - finding.start > alias["end"] - alias["start"] for finding in findings):
                continue
            findings.append(RecognizerResult(
                entity_type=alias["entity_type"], start=alias["start"], end=alias["end"], score=0.95,
                recognition_metadata={"recognizer_name": "SessionAliasRecognizer", "cluster_id": alias["cluster_id"]},
            ))
        findings.sort(key=lambda finding: (finding.start, finding.end, finding.entity_type, -finding.score))
        candidates = [
            {
                "candidate_id": index,
                "entity_type": finding.entity_type,
                "score": finding.score,
                "recognizer": finding.recognition_metadata["recognizer_name"],
                "start": finding.start,
                "end": finding.end,
                "text": text[finding.start:finding.end],
            }
            for index, finding in enumerate(findings, 1)
        ]
        output = self.anonymizer.anonymize(
            text=text,
            analyzer_results=findings,
            operators={entity: OperatorConfig("custom", {"lambda": lambda value, kind=entity: session.replacement(kind, value)}) for entity in ENTITIES},
            conflict_resolution=ConflictResolutionStrategy.REMOVE_INTERSECTIONS,
            merge_entities_with_spaces=False,
        )
        replacements = []
        for span in self.anonymizer.source_spans:
            surface = text[span["start"]:span["end"]]
            replacement = session.replacement(span["entity_type"], surface)
            mapping = session.applied[(span["entity_type"], surface)]
            contributors = [
                candidate for candidate in candidates
                if candidate["entity_type"] == span["entity_type"]
                and candidate["start"] < span["end"] and span["start"] < candidate["end"]
            ]
            replacements.append({
                **span,
                "text": surface,
                "replacement": replacement,
                "cluster_id": mapping["cluster_id"],
                "changed": replacement != surface,
                "recognizers": sorted({candidate["recognizer"] for candidate in contributors}),
                "candidate_ids": [candidate["candidate_id"] for candidate in contributors],
            })
        return {
            "before": text,
            "after": output.text,
            "changed": output.text != text,
            "candidate_count": len(candidates),
            "operation_count": len(output.items),
            "replacement_count": sum(item["changed"] for item in replacements),
            "candidates": candidates,
            "discarded_candidates": discarded,
            "replacements": replacements,
        }

    def derive(self, source, source_path, source_line, run_id):
        start = perf_counter()
        action = deepcopy(source.get("final_action"))
        fields = []
        mapping = {"clusters": [], "mappings": []}
        if source["status"] == "ok" and action["action"] != "REFUSE":
            texts = {field: action["action_input"][field] for field in OUTBOUND_FIELDS.get(action["action"], ())}
            analyses = {field: self.analyze_text(text) for field, text in texts.items()}
            session = ReplacementSession(
                f"{source['run_id']}:{source['case_id']}:{source_line}:{FILTER_VERSION}",
                [(finding.entity_type, texts[field][finding.start:finding.end]) for field, (findings, _) in analyses.items() for finding in findings],
            )
            for field, text in texts.items():
                detail = self.filter_text(text, session, analyses[field])
                fields.append({"field": f"action_input.{field}", **detail})
                action["action_input"][field] = detail["after"]
            mapping = session.export()
        return {
            "case_id": source["case_id"],
            "condition": "A2",
            "run_id": run_id,
            "kind": "filter",
            "response_source": "local_derivation",
            "source_a0": {
                "run_id": source["run_id"],
                "path": source_path,
                "line": source_line,
                "condition": "A0",
                "requested_model": source["requested_model"],
                "response_model": source.get("response_model"),
                "prompt_version": source["prompt_version"],
                "response_source": source["response_source"],
            },
            "requested_model": source["requested_model"],
            "prompt_version": source["prompt_version"],
            "filter_version": FILTER_VERSION,
            "pii_rules_version": RULES_VERSION,
            "entity_clusters": mapping["clusters"],
            "entity_mappings": mapping["mappings"],
            "status": source["status"],
            "error": source.get("error"),
            "final_action": action,
            "changed": any(field["changed"] for field in fields),
            "candidate_count": sum(field["candidate_count"] for field in fields),
            "operation_count": sum(field["operation_count"] for field in fields),
            "replacement_count": sum(field["replacement_count"] for field in fields),
            "filter_elapsed_seconds": round(perf_counter() - start, 6),
            "position_convention": POSITION_CONVENTION,
            "fields": fields,
            "generation_request_count": 0,
            "usage": None,
        }


def select_inputs(args):
    sources = [
        {"case_id": row["case_id"], "line": line, "record": row}
        for line, row in enumerate(read_jsonl(project_path(args.input)), 1)
        if row["condition"] == "A0"
    ]
    return select_records(sources, args.case_id, args.all, args.limit)


def run(args):
    sources = select_inputs(args)
    pii_filter = PiiFilter()
    started_at = datetime.now(timezone.utc)
    run_id = started_at.strftime("%Y%m%dT%H%M%S_%fZ")
    run_dir = ROOT / "artifacts/filters" / run_id
    run_dir.mkdir(parents=True)
    input_path = project_path(args.input).resolve().as_posix()
    config = {
        "run_id": run_id,
        "stage": "filter",
        "started_at": started_at.isoformat(),
        "mode": "local_derivation",
        "input_path": input_path,
        "selection": {"case_ids": args.case_id, "all": args.all, "limit": args.limit},
        "selected_sources": [{"case_id": source["case_id"], "line": source["line"]} for source in sources],
        "source_count": len(sources),
        "filter_version": FILTER_VERSION,
        "entities": ENTITIES,
        "score_threshold": SCORE_THRESHOLD,
        "operator": "custom",
        "pii_rules_version": RULES_VERSION,
        "replacement_policy": RULE_CONFIGURATION,
        "language": LANGUAGE,
        "nlp_configuration": NLP_CONFIGURATION,
        "spacy_enabled_pipes": pii_filter.analyzer.nlp_engine.nlp[LANGUAGE].pipe_names,
        "spacy_disabled_pipes": list(pii_filter.analyzer.nlp_engine.nlp[LANGUAGE].disabled),
        "person_patterns": PERSON_PATTERNS,
        "package_versions": pii_filter.versions,
        "recognizers": [recognizer.name for recognizer in pii_filter.analyzer.registry.recognizers],
        "email_domain_validation": "tldextract bundled public suffix snapshot",
        "conflict_resolution": ConflictResolutionStrategy.REMOVE_INTERSECTIONS.value,
        "merge_entities_with_spaces": False,
        "candidate_stage": "Analyzer output after score threshold, context enhancement and deduplication",
        "replacement_stage": "Anonymizer operation input after conflict resolution; source coordinates captured by _operate",
        "position_convention": POSITION_CONVENTION,
        "outbound_fields": OUTBOUND_FIELDS,
        "generation_request_count": 0,
    }
    write_json(run_dir / "config.json", config)
    for source in sources:
        result = pii_filter.derive(source["record"], input_path, source["line"], run_id)
        append_jsonl(run_dir / "results.jsonl", result)
        print(f"{result['case_id']}/A2: {result['status']}, changed={result['changed']}, replacements={result['replacement_count']}")
    print(f"Saved {len(sources)} derived actions to {run_dir.relative_to(ROOT).as_posix()}")
    return run_dir
