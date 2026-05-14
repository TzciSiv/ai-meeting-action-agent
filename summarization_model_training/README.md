# Summarization Model Training

This folder contains the local deep learning summarization model code.

## Files

- `main.py` - command-line entrypoint for training
- `config.py` - parser arguments, dataset mappings, and tokenizer constants
- `data.py` - dataset loading
- `modeling.py` - model/tokenizer loading
- `preprocessing.py` - tokenization and preprocessing
- `metrics.py` - ROUGE metrics
- `training.py` - trainer, evaluation, prediction, and save logic
- `setup.py` - dependency checks and logging setup
- `configs/samsum_t5_small.json` - ready-to-run SAMSum config

## Train On SAMSum

```bash
python -m summarization_model_training.main summarization_model_training/configs/samsum_t5_small.json
```

The config uses:

- dataset: `knkarthick/samsum`
- input column: `dialogue`
- target column: `summary`
- base model: `google-t5/t5-small`
- output folder: `models/meeting-summarizer`

Training metrics are saved as CSV files in the output folder:

- `train_results.csv`
- `eval_results.csv`
- `predict_results.csv` when prediction is enabled
- `all_results.csv`
- `training_log.csv`

If Hugging Face asks for authentication, run:

```bash
huggingface-cli login
```

## Use The Trained Model

The main app loads the saved model from `models/meeting-summarizer` through `backend/local_model.py`.

You can also run a quick command-line inference check:

```bash
python -m summarization_model_training.inference --transcript transcript.txt --model-dir models/meeting-summarizer --output summary.json
```

