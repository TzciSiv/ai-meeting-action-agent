from datasets import load_dataset

from .config import SUMMARIZATION_NAME_MAPPING


def load_raw_datasets(data_args, model_args):
    if data_args.dataset_name is not None:
        return load_dataset(
            data_args.dataset_name,
            data_args.dataset_config_name,
            cache_dir=model_args.cache_dir,
            token=model_args.token,
            trust_remote_code=model_args.trust_remote_code,
        )

    data_files = {}
    extension = None
    if data_args.train_file is not None:
        data_files["train"] = data_args.train_file
        extension = data_args.train_file.split(".")[-1]
    if data_args.validation_file is not None:
        data_files["validation"] = data_args.validation_file
        extension = data_args.validation_file.split(".")[-1]
    if data_args.test_file is not None:
        data_files["test"] = data_args.test_file
        extension = data_args.test_file.split(".")[-1]

    return load_dataset(extension, data_files=data_files, cache_dir=model_args.cache_dir, token=model_args.token)


def get_active_column_names(raw_datasets, training_args):
    if training_args.do_train:
        if "train" not in raw_datasets:
            raise ValueError("--do_train requires a train dataset")
        return raw_datasets["train"].column_names
    if training_args.do_eval:
        if "validation" not in raw_datasets:
            raise ValueError("--do_eval requires a validation dataset")
        return raw_datasets["validation"].column_names
    if training_args.do_predict:
        if "test" not in raw_datasets:
            raise ValueError("--do_predict requires a test dataset")
        return raw_datasets["test"].column_names
    return None


def get_text_and_summary_columns(data_args, column_names):
    dataset_columns = SUMMARIZATION_NAME_MAPPING.get(data_args.dataset_name)

    if data_args.text_column is None:
        text_column = dataset_columns[0] if dataset_columns is not None else column_names[0]
    else:
        text_column = data_args.text_column
        if text_column not in column_names:
            raise ValueError(f"--text_column value '{text_column}' needs to be one of: {', '.join(column_names)}")

    if data_args.summary_column is None:
        summary_column = dataset_columns[1] if dataset_columns is not None else column_names[1]
    else:
        summary_column = data_args.summary_column
        if summary_column not in column_names:
            raise ValueError(f"--summary_column value '{summary_column}' needs to be one of: {', '.join(column_names)}")

    return text_column, summary_column
