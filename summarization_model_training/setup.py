import logging
import sys

import datasets
import nltk
import transformers
from filelock import FileLock
from huggingface_hub import is_offline_mode
from transformers.utils import check_min_version
from transformers.utils.versions import require_version

logger = logging.getLogger(__name__)


def check_dependencies() -> None:
    check_min_version("4.57.0")
    require_version("datasets>=1.8.0", "To fix: pip install -r requirements.txt")


def ensure_nltk_data() -> None:
    required_packages = [
        ("tokenizers/punkt", "punkt"),
        ("tokenizers/punkt_tab/english", "punkt_tab"),
    ]
    missing_packages = []

    for resource_path, package_name in required_packages:
        try:
            nltk.data.find(resource_path)
        except (LookupError, OSError):
            missing_packages.append(package_name)

    if not missing_packages:
        return

    if is_offline_mode():
        raise LookupError("Offline mode: run without TRANSFORMERS_OFFLINE first to download nltk data files")

    with FileLock(".lock"):
        for package_name in missing_packages:
            nltk.download(package_name, quiet=True)


def configure_logging(training_args) -> None:
    logging.basicConfig(
        format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
        datefmt="%m/%d/%Y %H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    if training_args.should_log:
        transformers.utils.logging.set_verbosity_info()

    log_level = training_args.get_process_log_level()
    logger.setLevel(log_level)
    datasets.utils.logging.set_verbosity(log_level)
    transformers.utils.logging.set_verbosity(log_level)
    transformers.utils.logging.enable_default_handler()
    transformers.utils.logging.enable_explicit_format()

    logger.warning(
        f"Process rank: {training_args.local_process_index}, device: {training_args.device}, "
        f"n_gpu: {training_args.n_gpu}, distributed training: "
        f"{training_args.parallel_mode.value == 'distributed'}, 16-bits training: {training_args.fp16}"
    )
    logger.info(f"Training/evaluation parameters {training_args}")
