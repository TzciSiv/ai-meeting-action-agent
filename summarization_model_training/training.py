import logging
import os
import csv

import numpy as np
from transformers import DataCollatorForSeq2Seq, Seq2SeqTrainer

from .metrics import build_compute_metrics

logger = logging.getLogger(__name__)


CSV_OUTPUT_FILES = [
    "train_results.csv",
    "eval_results.csv",
    "predict_results.csv",
    "all_results.csv",
    "training_log.csv",
]

LEGACY_JSON_OUTPUT_FILES = [
    "train_results.json",
    "eval_results.json",
    "predict_results.json",
    "all_results.json",
    "trainer_state.json",
]


def normalize_csv_value(value):
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, (list, tuple, dict)):
        return str(value)
    return value


def reset_csv_outputs(output_dir: str) -> None:
    os.makedirs(output_dir, exist_ok=True)
    for filename in CSV_OUTPUT_FILES + LEGACY_JSON_OUTPUT_FILES:
        path = os.path.join(output_dir, filename)
        if os.path.exists(path):
            os.remove(path)


def write_metrics_csv(output_dir: str, split: str, metrics: dict) -> None:
    os.makedirs(output_dir, exist_ok=True)
    metrics = {key: normalize_csv_value(value) for key, value in metrics.items()}

    result_path = os.path.join(output_dir, f"{split}_results.csv")
    with open(result_path, "w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=sorted(metrics))
        writer.writeheader()
        writer.writerow(metrics)

    all_results_path = os.path.join(output_dir, "all_results.csv")
    should_write_header = not os.path.exists(all_results_path)
    with open(all_results_path, "a", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=["split", "metric", "value"])
        if should_write_header:
            writer.writeheader()
        for metric, value in sorted(metrics.items()):
            writer.writerow({"split": split, "metric": metric, "value": value})


def write_training_log_csv(trainer: Seq2SeqTrainer, output_dir: str) -> None:
    rows = trainer.state.log_history
    if not rows:
        return

    fieldnames = sorted({key for row in rows for key in row})
    preferred_order = ["step", "epoch", "loss", "eval_loss", "learning_rate", "grad_norm"]
    ordered_fieldnames = [name for name in preferred_order if name in fieldnames]
    ordered_fieldnames.extend(name for name in fieldnames if name not in ordered_fieldnames)

    log_path = os.path.join(output_dir, "training_log.csv")
    with open(log_path, "w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=ordered_fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: normalize_csv_value(row.get(key, "")) for key in ordered_fieldnames})


def build_trainer(model, tokenizer, training_args, data_args, model_args, train_dataset, eval_dataset):
    label_pad_token_id = -100 if data_args.ignore_pad_token_for_loss else tokenizer.pad_token_id
    data_collator = DataCollatorForSeq2Seq(
        tokenizer,
        model=model,
        label_pad_token_id=label_pad_token_id,
        pad_to_multiple_of=8 if training_args.fp16 else None,
    )

    training_args.generation_max_length = (
        training_args.generation_max_length
        if training_args.generation_max_length is not None
        else data_args.val_max_target_length
    )
    training_args.generation_num_beams = (
        data_args.num_beams if data_args.num_beams is not None else training_args.generation_num_beams
    )

    compute_metrics = build_compute_metrics(tokenizer, cache_dir=model_args.cache_dir)

    return Seq2SeqTrainer(
        model=model,
        args=training_args,
        train_dataset=train_dataset if training_args.do_train else None,
        eval_dataset=eval_dataset if training_args.do_eval else None,
        processing_class=tokenizer,
        data_collator=data_collator,
        compute_metrics=compute_metrics if training_args.predict_with_generate else None,
    )


def run_training(trainer, training_args, data_args, train_dataset):
    if not training_args.do_train:
        return

    checkpoint = training_args.resume_from_checkpoint
    if trainer.is_world_process_zero() and checkpoint is None:
        reset_csv_outputs(training_args.output_dir)

    train_result = trainer.train(resume_from_checkpoint=checkpoint)
    trainer.save_model()

    metrics = train_result.metrics
    max_train_samples = data_args.max_train_samples if data_args.max_train_samples is not None else len(train_dataset)
    metrics["train_samples"] = min(max_train_samples, len(train_dataset))

    trainer.log_metrics("train", metrics)
    if trainer.is_world_process_zero():
        write_metrics_csv(training_args.output_dir, "train", metrics)
        write_training_log_csv(trainer, training_args.output_dir)


def run_evaluation(trainer, training_args, data_args, eval_dataset):
    if not training_args.do_eval:
        return

    logger.info("*** Evaluate ***")
    if isinstance(eval_dataset, dict):
        metrics = {}
        for eval_ds_name, eval_ds in eval_dataset.items():
            metrics.update(trainer.evaluate(eval_dataset=eval_ds, metric_key_prefix=f"eval_{eval_ds_name}"))
    else:
        metrics = trainer.evaluate(metric_key_prefix="eval")

    max_eval_samples = data_args.max_eval_samples if data_args.max_eval_samples is not None else len(eval_dataset)
    metrics["eval_samples"] = min(max_eval_samples, len(eval_dataset))

    trainer.log_metrics("eval", metrics)
    if trainer.is_world_process_zero():
        write_metrics_csv(training_args.output_dir, "eval", metrics)
        write_training_log_csv(trainer, training_args.output_dir)


def run_prediction(trainer, tokenizer, training_args, data_args, predict_dataset):
    if not training_args.do_predict:
        return

    logger.info("*** Predict ***")
    predict_results = trainer.predict(predict_dataset, metric_key_prefix="predict")
    metrics = predict_results.metrics
    max_predict_samples = data_args.max_predict_samples if data_args.max_predict_samples is not None else len(predict_dataset)
    metrics["predict_samples"] = min(max_predict_samples, len(predict_dataset))

    trainer.log_metrics("predict", metrics)
    if trainer.is_world_process_zero():
        write_metrics_csv(training_args.output_dir, "predict", metrics)
        write_training_log_csv(trainer, training_args.output_dir)

    if trainer.is_world_process_zero() and training_args.predict_with_generate:
        predictions = np.where(predict_results.predictions != -100, predict_results.predictions, tokenizer.pad_token_id)
        predictions = tokenizer.batch_decode(predictions, skip_special_tokens=True, clean_up_tokenization_spaces=True)
        predictions = [pred.strip() for pred in predictions]
        output_prediction_file = os.path.join(training_args.output_dir, "generated_predictions.txt")
        with open(output_prediction_file, "w", encoding="utf-8") as writer:
            writer.write("\n".join(predictions))


def create_or_push_model_card(trainer, model_args, data_args, training_args):
    kwargs = {"finetuned_from": model_args.model_name_or_path, "tasks": "summarization"}
    if data_args.dataset_name is not None:
        kwargs["dataset_tags"] = data_args.dataset_name
        if data_args.dataset_config_name is not None:
            kwargs["dataset_args"] = data_args.dataset_config_name
            kwargs["dataset"] = f"{data_args.dataset_name} {data_args.dataset_config_name}"
        else:
            kwargs["dataset"] = data_args.dataset_name

    if data_args.lang is not None:
        kwargs["language"] = data_args.lang

    if training_args.push_to_hub:
        trainer.push_to_hub(**kwargs)
    else:
        trainer.create_model_card(**kwargs)
