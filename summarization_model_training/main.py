#!/usr/bin/env python
import logging
import os
import sys

from transformers import set_seed

from .config import build_argument_objects, parse_config
from .data import get_active_column_names, get_text_and_summary_columns, load_raw_datasets
from .modeling import load_model_and_tokenizer, prepare_model
from .preprocessing import (
    build_preprocess_function,
    configure_multilingual_tokenizer,
    preprocess_datasets,
)
from .setup import check_dependencies, configure_logging, ensure_nltk_data
from .training import (
    build_trainer,
    create_or_push_model_card,
    run_evaluation,
    run_prediction,
    run_training,
)


logger = logging.getLogger(__name__)


def parse_args():
    namespace = parse_config(sys.argv[1:])
    if namespace.device_name:
        os.environ["CUDA_VISIBLE_DEVICES"] = namespace.device_name
    return namespace, *build_argument_objects(namespace)


def report_device():
    import torch

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Your model is running on {device}...\n")
    if device.type == "cuda":
        print(f"CUDA device: {torch.cuda.get_device_name(0)}\n")
    return device


def main():
    check_dependencies()
    ensure_nltk_data()

    args, model_args, data_args, training_args = parse_args()
    report_device()
    configure_logging(training_args)

    if data_args.source_prefix is None and model_args.model_name_or_path in [
        "google-t5/t5-small",
        "google-t5/t5-base",
        "google-t5/t5-large",
        "google-t5/t5-3b",
        "google-t5/t5-11b",
    ]:
        logger.warning("T5 models usually need --source_prefix 'summarize: '")

    set_seed(training_args.seed)

    raw_datasets = load_raw_datasets(data_args, model_args)
    model, tokenizer = load_model_and_tokenizer(model_args)
    model = prepare_model(model, tokenizer, model_args, data_args)

    column_names = get_active_column_names(raw_datasets, training_args)
    if column_names is None:
        logger.info("There is nothing to do. Please pass --do_train, --do_eval, and/or --do_predict.")
        return {}

    configure_multilingual_tokenizer(tokenizer, model, data_args)
    text_column, summary_column = get_text_and_summary_columns(data_args, column_names)
    preprocess_function = build_preprocess_function(tokenizer, data_args, text_column, summary_column)
    train_dataset, eval_dataset, predict_dataset = preprocess_datasets(
        raw_datasets, training_args, data_args, column_names, preprocess_function
    )

    trainer = build_trainer(model, tokenizer, training_args, data_args, model_args, train_dataset, eval_dataset)

    run_training(trainer, training_args, data_args, train_dataset)
    run_evaluation(trainer, training_args, data_args, eval_dataset)
    run_prediction(trainer, tokenizer, training_args, data_args, predict_dataset)
    create_or_push_model_card(trainer, model_args, data_args, training_args)
    return {}


def _mp_fn(index):
    # For xla_spawn / TPU usage.
    main()


if __name__ == "__main__":
    main()
