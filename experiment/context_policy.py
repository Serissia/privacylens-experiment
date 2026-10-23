"""Span-scoped keep/protect labels and deterministic disclosure decisions."""

import json
import re

from presidio_analyzer import RecognizerResult

from .gliner_recognizer import GLINER_THRESHOLD, TokenBudgetChunker


POLICY_VERSION = "context_labels_v1"
KEEP_THRESHOLD = 0.6
KEEP_LABELS = {
    "message recipient name": {"PERSON"},
    "message sender name": {"PERSON"},
    "public figure": {"PERSON"},
    "celebrity": {"PERSON"},
    "famous landmark": {"LOCATION", "ORGANIZATION"},
    "travel destination": {"LOCATION"},
    "job application company": {"ORGANIZATION"},
    "public event": {"ORGANIZATION", "LOCATION"},
    "public event date": {"DATE_TIME"},
    "public event time": {"DATE_TIME"},
}
PROTECT_LABELS = {
    "private person": "PERSON",
    "home address": "PRIVATE_ADDRESS",
    "private residence": "PRIVATE_ADDRESS",
    "medical condition": "PRIVATE_FACT",
    "private family problem": "PRIVATE_FACT",
    "private appointment date": "DATE_TIME",
}
LABELS = [*KEEP_LABELS, *PROTECT_LABELS]
GENERALIZATIONS = {"PRIVATE_ADDRESS": "[private location]", "PRIVATE_FACT": "[private information]"}
STRUCTURED = {"EMAIL_ADDRESS", "PHONE_NUMBER", "CREDIT_CARD", "IBAN_CODE", "US_SSN", "FLIGHT_NUMBER", "TRAIN_NUMBER", "BOOKING_REFERENCE"}
NAME = r"(?:(?:Mr|Mrs|Ms|Dr|Prof)\.?[ \t]+)?[A-Z][a-z]+(?:[-'][A-Z]?[a-z]+)*(?:[ \t]+[A-Z][a-z]+(?:[-'][A-Z]?[a-z]+)*){0,2}"
GREETING = re.compile(rf"\A\s*(?:Hi|Hello|Dear|Hey)\s+(?P<name>{NAME})(?=\s*[,!:])")
SIGNATURE = re.compile(rf"(?:^|\n)(?:Best regards|Kind regards|Regards|Sincerely|Best|Thanks|Thank you|Cheers)[,!]?[ \t]*\n[ \t]*(?P<name>{NAME})(?=[ \t]*(?:\n|$))")


def overlaps(left, right):
    return left["start"] < right["end"] and right["start"] < left["end"]


class ContextPolicy:
    def __init__(self, model):
        self.model = model

    def configuration(self):
        return {
            "version": POLICY_VERSION,
            "keep_labels": {label: sorted(kinds) for label, kinds in KEEP_LABELS.items()},
            "protect_labels": PROTECT_LABELS,
            "keep_threshold": KEEP_THRESHOLD, "protect_threshold": GLINER_THRESHOLD,
            "private_appointment_threshold": 0.65,
            "private_address_threshold": 0.6,
            "flat_ner": False, "multi_label": True,
            "context_fields": ["user_name", "user_instruction", "action", "recipient"],
            "context_limits": {"user_name_words": 8, "instruction_words": 40, "recipient_words": 8},
            "precedence": ["private address/fact", "structured identifiers", "anchored greeting/signature", "private appointment", "public/task label", "default entity replacement"],
            "generalizations": GENERALIZATIONS,
            "label_scope": "body spans; anchored correspondence roles; repeated task targets; dates within a public event clause",
        }

    def analyze(self, text, context, action):
        arguments = action.get("action_input", {})
        recipient = arguments.get("to", arguments.get("recipient_id", arguments.get("channel_id", arguments.get("channel", arguments.get("privacy_setting", "")))))
        task = {
            "sender": " ".join(context.get("user_name", "").split()[:8]),
            "task": " ".join(context.get("user_instruction", "").split()[:40]),
            "tool": action.get("action", ""),
            "recipient": " ".join(str(recipient).split()[:8]),
        }
        prefix = "Task context: " + json.dumps(task, ensure_ascii=False) + "\nOutgoing text:\n"
        chunker = TokenBudgetChunker(self.model, LABELS, prefix)
        signals = {}
        for chunk in chunker.chunk(text):
            for prediction in self.model.predict_entities(
                prefix + chunk.text, LABELS, threshold=GLINER_THRESHOLD, flat_ner=False, multi_label=True,
            ):
                if prediction["start"] < len(prefix):
                    continue
                label = prediction["label"]
                if label in KEEP_LABELS and prediction["score"] < KEEP_THRESHOLD:
                    continue
                if label == "private appointment date" and prediction["score"] < 0.65:
                    continue
                if PROTECT_LABELS.get(label) == "PRIVATE_ADDRESS" and prediction["score"] < 0.6:
                    continue
                start = chunk.start + prediction["start"] - len(prefix)
                end = chunk.start + prediction["end"] - len(prefix)
                signal = {"label": label, "start": start, "end": end, "text": text[start:end], "score": prediction["score"], "source": "GLiNERContextLabels"}
                key = (label, start, end)
                if key not in signals or signal["score"] > signals[key]["score"]:
                    signals[key] = signal
        # 称呼与落款保留规则限定在相应位置，重复姓名仍由各自上下文判断。
        for pattern, label in [(GREETING, "anchored greeting"), (SIGNATURE, "anchored signature")]:
            match = pattern.search(text)
            if match:
                start, end = match.span("name")
                signals[label, start, end] = {"label": label, "start": start, "end": end, "text": text[start:end], "score": 1.0, "source": "CorrespondencePositionRule"}
        return {
            "context": task,
            "signals": sorted(signals.values(), key=lambda s: (s["start"], s["end"], s["label"])),
            "chunks": chunker.last_chunks,
        }

    def candidates(self, signals):
        return [RecognizerResult(
            entity_type=PROTECT_LABELS[signal["label"]], start=signal["start"], end=signal["end"], score=signal["score"],
            recognition_metadata={"recognizer_name": "GLiNERContextLabels", "policy_label": signal["label"]},
        ) for signal in signals if signal["label"] in PROTECT_LABELS]

    def decide(self, candidates, signals, text, context=None):
        instruction = (context or {}).get("task", "").casefold()
        targets = {}
        for candidate in candidates:
            surface = text[candidate["start"]:candidate["end"]]
            if candidate["entity_type"] not in {"ORGANIZATION", "LOCATION"} or not re.search(rf"(?<!\w){re.escape(surface.casefold())}(?!\w)", instruction):
                continue
            evidence = [s for s in signals if s["label"] in {"job application company", "travel destination", "famous landmark", "public event"} and s["start"] <= candidate["start"] and candidate["end"] <= s["end"]]
            if evidence:
                targets[candidate["entity_type"], surface.casefold()] = evidence
        decisions = []
        for candidate in candidates:
            kind = candidate["entity_type"]
            matched = [signal for signal in signals if overlaps(candidate, signal)]
            strong = [s for s in matched if PROTECT_LABELS.get(s["label"]) in GENERALIZATIONS]
            anchors = [s for s in matched if s["label"].startswith("anchored ") and s["start"] <= candidate["start"] and candidate["end"] <= s["end"]]
            # 同一分句的私人预约日期约束其时刻，避免日期被遮盖而时间被公开标签放行。
            left = max((match.end() for match in re.finditer(r"[.!?;\n]", text[:candidate["start"]])), default=0)
            boundary = re.search(r"[.!?;\n]", text[candidate["end"]:])
            right = candidate["end"] + boundary.start() if boundary else len(text)
            appointment = [s for s in signals if s["label"] == "private appointment date" and left <= s["start"] and s["end"] <= right]
            private_date = bool(appointment)
            if kind == "DATE_TIME":
                matched += [s for s in appointment if s not in matched]
                event = [s for s in signals if s["label"] == "public event" and left <= s["start"] and s["end"] <= right]
                matched += [s for s in event if s not in matched]
            else:
                event = []
            target = targets.get((kind, text[candidate["start"]:candidate["end"]].casefold()), [])
            matched += [s for s in target if s not in matched]
            keep = [s for s in matched if kind in KEEP_LABELS.get(s["label"], set()) and s["start"] <= candidate["start"] and candidate["end"] <= s["end"] and s["label"] not in {"message recipient name", "message sender name"}]
            if kind in GENERALIZATIONS:
                decision, reason = "GENERALIZE", "private address or fact label"
            elif strong:
                decision, reason = "COVERED", "handled by overlapping private address or fact span"
            elif kind in STRUCTURED:
                decision, reason = "REPLACE", "structured identifier"
            elif kind == "PERSON" and anchors:
                decision, reason = "KEEP", "anchored correspondence role"
            elif kind == "DATE_TIME" and private_date:
                decision, reason = "REPLACE", "private appointment overrides public date label"
            elif keep or target or event:
                decision, reason = "KEEP", "public or task entity label, repeated task target, or public event date"
            else:
                decision, reason = "REPLACE", "private or unexempted entity"
            decisions.append({"candidate_id": candidate["candidate_id"], "decision": decision, "reason": reason, "signal_ids": [signals.index(s) + 1 for s in matched]})
        return decisions
