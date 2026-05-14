import argparse
import json
from dataclasses import dataclass
from pathlib import Path


try:
    from transformers import MBart50Tokenizer, MBart50TokenizerFast, MBartTokenizer, MBartTokenizerFast

    MULTILINGUAL_TOKENIZERS = [
        MBartTokenizer,
        MBartTokenizerFast,
        MBart50Tokenizer,
        MBart50TokenizerFast,
    ]
except ImportError:
    MULTILINGUAL_TOKENIZERS = []


SUMMARIZATION_NAME_MAPPING = {
    "amazon_reviews_multi": ("review_body", "review_title"),
    "big_patent": ("description", "abstract"),
    "cnn_dailymail": ("article", "highlights"),
    "orange_sum": ("text", "summary"),
    "pn_summary": ("article", "summary"),
    "psc": ("extract_text", "summary_text"),
    "knkarthick/samsum": ("dialogue", "summary"),
    "samsum": ("dialogue", "summary"),
    "thaisum": ("body", "summary"),
    "xglue": ("news_body", "news_title"),
    "xsum": ("document", "summary"),
    "wiki_summary": ("article", "highlights"),
    "multi_news": ("document", "summary"),
}


@dataclass
class ModelConfig:
    model_name_or_path: str
    config_name: str | None = None
    tokenizer_name: str | None = None
    cache_dir: str | None = None
    use_fast_tokenizer: bool = True
    model_revision: str = "main"
    token: str | None = None
    trust_remote_code: bool = False
    resize_position_embeddings: bool | None = None


@dataclass
class DataConfig:
    lang: str | None = None
    dataset_name: str | None = "knkarthick/samsum"
    dataset_config_name: str | None = None
    text_column: str | None = "dialogue"
    summary_column: str | None = "summary"
    train_file: str | None = None
    validation_file: str | None = None
    test_file: str | None = None
    overwrite_cache: bool = False
    preprocessing_num_workers: int | None = None
    max_source_length: int = 1024
    max_target_length: int = 128
    val_max_target_length: int | None = None
    pad_to_max_length: bool = False
    max_train_samples: int | None = None
    max_eval_samples: int | None = None
    max_predict_samples: int | None = None
    num_beams: int | None = 4
    ignore_pad_token_for_loss: bool = True
    source_prefix: str | None = "summarize: "
    forced_bos_token: str | None = None

    def __post_init__(self) -> None:
        has_dataset = self.dataset_name is not None
        has_file = any([self.train_file, self.validation_file, self.test_file])
        if not has_dataset and not has_file:
            raise ValueError("Need either a dataset name or a train/validation/test file.")

        for file_path in [self.train_file, self.validation_file, self.test_file]:
            if file_path is not None:
                extension = file_path.split(".")[-1]
                assert extension in ["csv", "json"], "Data files should be csv or json files."

        if self.val_max_target_length is None:
            self.val_max_target_length = self.max_target_length


config_args = argparse.ArgumentParser(description="Train a local meeting summarization model.")

# ----------------------------------- Dataset Configs ----------------------------------- #
config_args.add_argument("--dataset_name", type=str, default="knkarthick/samsum", help="Hugging Face dataset name")
config_args.add_argument("--dataset_config_name", type=str, default=None, help="Hugging Face dataset config name")
config_args.add_argument("--text_column", type=str, default="dialogue", help="Dataset column containing source text")
config_args.add_argument("--summary_column", type=str, default="summary", help="Dataset column containing target summary")
config_args.add_argument("--train_file", type=str, default=None, help="Optional local CSV/JSON training file")
config_args.add_argument("--validation_file", type=str, default=None, help="Optional local CSV/JSON validation file")
config_args.add_argument("--test_file", type=str, default=None, help="Optional local CSV/JSON test file")
config_args.add_argument("--cache_dir", type=str, default=None, help="Cache directory for datasets and models")
config_args.add_argument("--token", type=str, default=None, help="Hugging Face token for gated/private datasets")

# ----------------------------------- Model Configs ----------------------------------- #
config_args.add_argument("--model_name_or_path", type=str, default="google-t5/t5-small", help="Base model or local model path")
config_args.add_argument("--config_name", type=str, default=None, help="Optional config name/path")
config_args.add_argument("--tokenizer_name", type=str, default=None, help="Optional tokenizer name/path")
config_args.add_argument("--model_revision", type=str, default="main", help="Model branch, tag, or commit id")
config_args.add_argument("--use_fast_tokenizer", action=argparse.BooleanOptionalAction, default=True, help="Use fast tokenizer")
config_args.add_argument("--trust_remote_code", action=argparse.BooleanOptionalAction, default=False, help="Allow custom Hub code")
config_args.add_argument("--resize_position_embeddings", action=argparse.BooleanOptionalAction, default=None, help="Resize position embeddings")

# ----------------------------------- Preprocessing Configs ----------------------------------- #
config_args.add_argument("--seed", type=int, default=42, help="Seed for reproducibility")
config_args.add_argument("--lang", type=str, default=None, help="Language id for multilingual tokenizers")
config_args.add_argument("--source_prefix", type=str, default="summarize: ", help="Prefix for models such as T5")
config_args.add_argument("--max_source_length", type=int, default=1024, help="Max input token length")
config_args.add_argument("--max_target_length", type=int, default=128, help="Max target token length")
config_args.add_argument("--val_max_target_length", type=int, default=None, help="Max generated length for validation")
config_args.add_argument("--pad_to_max_length", action=argparse.BooleanOptionalAction, default=False, help="Pad to max length")
config_args.add_argument("--overwrite_cache", action=argparse.BooleanOptionalAction, default=False, help="Overwrite cached preprocessing")
config_args.add_argument("--preprocessing_num_workers", type=int, default=None, help="Number of preprocessing workers")
config_args.add_argument("--ignore_pad_token_for_loss", action=argparse.BooleanOptionalAction, default=True, help="Ignore pad token loss")
config_args.add_argument("--forced_bos_token", type=str, default=None, help="Forced BOS token for multilingual models")

# ----------------------------------- Training Configs ----------------------------------- #
config_args.add_argument("--output_dir", type=str, default="models/meeting-summarizer", help="Output model directory")
config_args.add_argument("--overwrite_output_dir", action=argparse.BooleanOptionalAction, default=True, help="Overwrite output dir")
config_args.add_argument("--do_train", action=argparse.BooleanOptionalAction, default=True, help="Run training")
config_args.add_argument("--do_eval", action=argparse.BooleanOptionalAction, default=True, help="Run evaluation")
config_args.add_argument("--do_predict", action=argparse.BooleanOptionalAction, default=False, help="Run prediction")
config_args.add_argument("--predict_with_generate", action=argparse.BooleanOptionalAction, default=True, help="Generate summaries for metrics")
config_args.add_argument("--num_train_epochs", "--epochs", dest="num_train_epochs", type=float, default=3, help="# of epochs")
config_args.add_argument("--per_device_train_batch_size", "--batch", dest="per_device_train_batch_size", type=int, default=2, help="Train batch size")
config_args.add_argument("--per_device_eval_batch_size", type=int, default=2, help="Eval batch size")
config_args.add_argument("--learning_rate", "--lr", dest="learning_rate", type=float, default=5e-5, help="Learning rate")
config_args.add_argument("--num_beams", type=int, default=4, help="Beam search size")
config_args.add_argument("--max_train_samples", type=int, default=None, help="Limit train samples for debugging")
config_args.add_argument("--max_eval_samples", type=int, default=None, help="Limit eval samples for debugging")
config_args.add_argument("--max_predict_samples", type=int, default=None, help="Limit predict samples for debugging")
config_args.add_argument("--logging_steps", type=int, default=50, help="Logging interval")
config_args.add_argument("--eval_strategy", type=str, default="epoch", help="Evaluation strategy")
config_args.add_argument("--save_strategy", type=str, default="epoch", help="Save strategy")
config_args.add_argument("--save_total_limit", type=int, default=2, help="Max checkpoints to keep")
config_args.add_argument("--resume_from_checkpoint", type=str, default=None, help="Checkpoint path")
config_args.add_argument("--fp16", action=argparse.BooleanOptionalAction, default=False, help="Use fp16 training")
config_args.add_argument("--push_to_hub", action=argparse.BooleanOptionalAction, default=False, help="Push model to Hugging Face Hub")
config_args.add_argument("--device_name", type=str, default=None, help="CUDA_VISIBLE_DEVICES value")


def _load_json_args(path: str) -> argparse.Namespace:
    namespace = config_args.parse_args([])
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    for key, value in data.items():
        setattr(namespace, key, value)
    return namespace


def parse_config(argv: list[str] | None = None) -> argparse.Namespace:
    argv = list(argv or [])
    if len(argv) == 1 and argv[0].endswith(".json"):
        return _load_json_args(argv[0])
    return config_args.parse_args(argv)


def build_argument_objects(namespace: argparse.Namespace):
    import inspect

    from transformers import Seq2SeqTrainingArguments

    if namespace.device_name:
        import os

        os.environ["CUDA_VISIBLE_DEVICES"] = namespace.device_name

    model_args = ModelConfig(
        model_name_or_path=namespace.model_name_or_path,
        config_name=namespace.config_name,
        tokenizer_name=namespace.tokenizer_name,
        cache_dir=namespace.cache_dir,
        use_fast_tokenizer=namespace.use_fast_tokenizer,
        model_revision=namespace.model_revision,
        token=namespace.token,
        trust_remote_code=namespace.trust_remote_code,
        resize_position_embeddings=namespace.resize_position_embeddings,
    )
    data_args = DataConfig(
        lang=namespace.lang,
        dataset_name=namespace.dataset_name,
        dataset_config_name=namespace.dataset_config_name,
        text_column=namespace.text_column,
        summary_column=namespace.summary_column,
        train_file=namespace.train_file,
        validation_file=namespace.validation_file,
        test_file=namespace.test_file,
        overwrite_cache=namespace.overwrite_cache,
        preprocessing_num_workers=namespace.preprocessing_num_workers,
        max_source_length=namespace.max_source_length,
        max_target_length=namespace.max_target_length,
        val_max_target_length=namespace.val_max_target_length,
        pad_to_max_length=namespace.pad_to_max_length,
        max_train_samples=namespace.max_train_samples,
        max_eval_samples=namespace.max_eval_samples,
        max_predict_samples=namespace.max_predict_samples,
        num_beams=namespace.num_beams,
        ignore_pad_token_for_loss=namespace.ignore_pad_token_for_loss,
        source_prefix=namespace.source_prefix,
        forced_bos_token=namespace.forced_bos_token,
    )

    training_kwargs = {
        "output_dir": namespace.output_dir,
        "overwrite_output_dir": namespace.overwrite_output_dir,
        "do_train": namespace.do_train,
        "do_eval": namespace.do_eval,
        "do_predict": namespace.do_predict,
        "predict_with_generate": namespace.predict_with_generate,
        "num_train_epochs": namespace.num_train_epochs,
        "per_device_train_batch_size": namespace.per_device_train_batch_size,
        "per_device_eval_batch_size": namespace.per_device_eval_batch_size,
        "learning_rate": namespace.learning_rate,
        "seed": namespace.seed,
        "logging_steps": namespace.logging_steps,
        "eval_strategy": namespace.eval_strategy,
        "save_strategy": namespace.save_strategy,
        "save_total_limit": namespace.save_total_limit,
        "resume_from_checkpoint": namespace.resume_from_checkpoint,
        "fp16": namespace.fp16,
        "push_to_hub": namespace.push_to_hub,
        "generation_num_beams": namespace.num_beams,
        "generation_max_length": data_args.val_max_target_length,
        "report_to": [],
    }
    valid_training_args = set(inspect.signature(Seq2SeqTrainingArguments.__init__).parameters)
    if "eval_strategy" not in valid_training_args and "evaluation_strategy" in valid_training_args:
        training_kwargs["evaluation_strategy"] = training_kwargs.pop("eval_strategy")

    training_kwargs = {key: value for key, value in training_kwargs.items() if key in valid_training_args}
    training_args = Seq2SeqTrainingArguments(**training_kwargs)
    training_args.resume_from_checkpoint = namespace.resume_from_checkpoint
    return model_args, data_args, training_args
