"""Download pinned GLiNER weights and the matching local encoder configuration."""

import json
import os

from .common import ROOT, read_json, write_json


ENCODER_ID = "microsoft/deberta-v3-base"
ENCODER_REVISION = "8ccc9b6f36199bec6961081d44eb72fb3f7353f3"


def export_onnx():
    """Export the pinned local span model with dynamic text and label axes."""
    import torch
    from gliner import GLiNER
    from .gliner_recognizer import MODEL_PATH

    class SpanExport(torch.nn.Module):
        def __init__(self, model):
            super().__init__()
            self.model = model

        def forward(self, input_ids, attention_mask, words_mask, text_lengths, span_idx, span_mask):
            return self.model(
                input_ids=input_ids, attention_mask=attention_mask, words_mask=words_mask,
                text_lengths=text_lengths, span_idx=span_idx, span_mask=span_mask,
            ).logits

    model = GLiNER.from_pretrained(str(MODEL_PATH), local_files_only=True, load_tokenizer=True)
    inputs, _ = model.prepare_model_inputs(["Alice works at Acme in London."], ["person", "organization", "location"])
    names = ["input_ids", "attention_mask", "words_mask", "text_lengths", "span_idx", "span_mask"]
    axes = {name: {0: "batch", 1: "sequence"} for name in names[:3]}
    axes.update({"text_lengths": {0: "batch"}, "span_idx": {0: "batch", 1: "spans"},
                 "span_mask": {0: "batch", 1: "spans"}, "logits": {0: "batch", 1: "words", 3: "labels"}})
    with torch.no_grad():
        torch.onnx.export(
            SpanExport(model.model).eval(), tuple(inputs[name] for name in names),
            str(MODEL_PATH / "model.onnx"), input_names=names, output_names=["logits"],
            dynamic_axes=axes, opset_version=17, dynamo=False,
        )
    source = read_json(MODEL_PATH / "source.json")
    source.update({"onnx_model_file": "model.onnx", "onnx_opset": 17,
                   "onnx_source": "local export of pinned model.safetensors"})
    write_json(MODEL_PATH / "source.json", source)


def run():
    os.chdir(ROOT)
    os.environ["HF_HUB_DISABLE_XET"] = "1"
    from .gliner_recognizer import MODEL_ID, MODEL_PATH, MODEL_REVISION
    from huggingface_hub import snapshot_download
    from transformers import AutoTokenizer

    snapshot_download(
        MODEL_ID, revision=MODEL_REVISION, local_dir=MODEL_PATH,
        allow_patterns=["gliner_config.json", "model.safetensors", "README.md"],
    )
    encoder_path = MODEL_PATH / "encoder"
    snapshot_download(
        ENCODER_ID, revision=ENCODER_REVISION, local_dir=encoder_path,
        allow_patterns=["config.json", "tokenizer_config.json", "spm.model"],
    )
    # SentencePiece 使用英文相对路径读取词表，fast tokenizer 随权重保存在本地。
    tokenizer = AutoTokenizer.from_pretrained(
        encoder_path.relative_to(ROOT).as_posix(), local_files_only=True, from_slow=True,
    )
    tokenizer.init_kwargs["from_slow"] = False
    tokenizer.model_max_length = read_json(encoder_path / "config.json")["max_position_embeddings"]
    tokenizer.save_pretrained(MODEL_PATH)
    config = read_json(MODEL_PATH / "gliner_config.json")
    config["model_name"] = str(encoder_path.resolve())
    # 上游按系统默认编码读取配置；ASCII 转义兼容 Windows 下的中文目录。
    with (MODEL_PATH / "gliner_config.json").open("w", encoding="ascii", newline="\n") as file:
        json.dump(config, file, ensure_ascii=True, indent=2)
        file.write("\n")
    write_json(MODEL_PATH / "source.json", {
        "model_id": MODEL_ID, "revision": MODEL_REVISION,
        "encoder_id": ENCODER_ID, "encoder_revision": ENCODER_REVISION,
        "encoder_path": "encoder", "weight_file": "model.safetensors",
        "tokenizer": "local fast tokenizer converted from the encoder SentencePiece vocabulary",
        "configuration": "model_name points to the local encoder directory",
        "model_license": "Apache-2.0",
    })
    export_onnx()
    print(f"GLiNER model, ONNX weights and tokenizer saved to {MODEL_PATH}")
