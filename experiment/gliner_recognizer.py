"""English GLiNER recognition with overlapping, token-budgeted text chunks."""

import re

from presidio_analyzer.chunkers.base_chunker import BaseTextChunker, TextChunk
from presidio_analyzer.predefined_recognizers import GLiNERRecognizer

from .common import ROOT, read_json
from .reproducibility import seed_local


MODEL_ID = "urchade/gliner_medium-v2.1"
MODEL_REVISION = "40ec419335d09393f298636f471328b722c6da9e"
MODEL_PATH = ROOT / "models/gliner_medium-v2.1"
ENTITY_MAPPING = {
    "person": "PERSON",
    "organization": "ORGANIZATION",
    "location": "LOCATION",
    "date": "DATE_TIME",
    "time": "DATE_TIME",
    "nationality": "NRP",
    "religious group": "NRP",
    "political group": "NRP",
    "flight number": "FLIGHT_NUMBER",
    "train number": "TRAIN_NUMBER",
    "booking reference": "BOOKING_REFERENCE",
    "reservation number": "BOOKING_REFERENCE",
}
GLINER_THRESHOLD = 0.4
TOKEN_BUDGET = 384
OVERLAP_WORDS = 32
TRAVEL_ENTITIES = {"FLIGHT_NUMBER", "TRAIN_NUMBER", "BOOKING_REFERENCE"}
IDENTIFIER_CUE = re.compile(
    r"^(?:(?:flight|train|booking|reservation|confirmation)(?:\s+(?:number|reference|code|id))?|number|reference|code|id)[\s:#-]+",
    re.I,
)


class TokenBudgetChunker(BaseTextChunker):
    def __init__(self, model, labels, prefix=""):
        self.processor = model.data_processor
        self.labels = labels
        self.prefix_words = [word[0] for word in self.processor.words_splitter(prefix)]
        self.token_budget = min(TOKEN_BUDGET, model.config.max_len, self.processor.transformer_tokenizer.model_max_length)
        self.overlap_words = OVERLAP_WORDS
        self.last_chunks = []

    def input_length(self, words):
        # 复用 GLiNER 的标签前缀格式，计入标签与特殊 token 的编码开销。
        inputs, _ = self.processor.prepare_inputs([self.prefix_words + words], [self.labels])
        encoded = self.processor.transformer_tokenizer(
            inputs[0], is_split_into_words=True, truncation=False,
            return_attention_mask=False, verbose=False,
        )
        return len(encoded["input_ids"])

    def chunk(self, text):
        words = list(self.processor.words_splitter(text))
        chunks = []
        self.last_chunks = []
        start = 0
        while start < len(words):
            lower, upper = start + 1, min(len(words), start + self.token_budget)
            end = start
            while lower <= upper:
                middle = (lower + upper) // 2
                if self.input_length([word[0] for word in words[start:middle]]) <= self.token_budget:
                    end, lower = middle, middle + 1
                else:
                    upper = middle - 1
            if end == start:
                raise ValueError("A GLiNER word and its label prefix exceed the token budget")
            char_start = words[start][1] if start else 0
            char_end = words[end][1] if end < len(words) else len(text)
            chunks.append(TextChunk(text[char_start:char_end], char_start, char_end))
            self.last_chunks.append({
                "chunk_id": len(chunks), "start": char_start, "end": char_end,
                "word_count": end - start,
                "input_token_count": self.input_length([word[0] for word in words[start:end]]),
            })
            if end == len(words):
                break
            # 重叠保留跨边界实体的上下文，坐标始终指向完整原字段。
            start = max(start + 1, end - self.overlap_words)
        return chunks


class EnglishGLiNERRecognizer(GLiNERRecognizer):
    def __init__(self):
        seed_local()
        super().__init__(
            name="GLiNERRecognizer", model_name=str(MODEL_PATH),
            entity_mapping=ENTITY_MAPPING, supported_language="en",
            map_location="cpu", threshold=GLINER_THRESHOLD,
            flat_ner=True, multi_label=False, local_files_only=True,
        )
        self.text_chunker = TokenBudgetChunker(self.gliner, self.gliner_labels)

    def analyze(self, text, entities, nlp_artifacts=None):
        # 结构化实体交由各自识别器处理，模型标签与分块预算保持一致。
        requested = [entity for entity in entities if entity in self.supported_entities]
        findings = super().analyze(text, requested, nlp_artifacts)
        for finding in findings:
            if finding.entity_type in TRAVEL_ENTITIES:
                surface = text[finding.start:finding.end]
                cue = IDENTIFIER_CUE.match(surface)
                if cue:
                    # 模型片段可能包含 Flight 等引导词；实际操作只替换编号。
                    finding.recognition_metadata = {
                        "model_span": {"start": finding.start, "end": finding.end, "text": surface},
                    }
                    finding.start += cue.end()
        return findings

    def configuration(self):
        return {
            "model_id": MODEL_ID, "model_path": MODEL_PATH.relative_to(ROOT).as_posix(),
            "source": read_json(MODEL_PATH / "source.json"),
            "device": "cpu", "threshold": GLINER_THRESHOLD,
            "entity_mapping": ENTITY_MAPPING, "flat_ner": True, "multi_label": False,
            "identifier_span_policy": "preserve leading identifier cues; audit the original model span",
            "chunking": {
                "strategy": "GLiNER word boundaries with full encoder-input token budget",
                "token_budget": self.text_chunker.token_budget,
                "overlap_words": OVERLAP_WORDS,
                "label_prefix_included": True,
                "offsets": "original field Python character indices [start, end)",
                "deduplication": "Presidio BaseTextChunker same-type overlap, highest score first",
            },
        }
