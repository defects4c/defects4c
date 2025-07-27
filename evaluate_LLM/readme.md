
# Single Round LLM Evaluation

This guide walks you through evaluating large language models (LLMs) for code generation in a single round evaluation setup.

## Prerequisites

Ensure you have the necessary dependencies installed and your environment set up properly before running the evaluation.

## Step 1: Generate LLM Responses

Generate responses from your chosen LLM (e.g., CodeLlama-7B) for all prompts in the dataset.

```bash
cd LLM_codegen_single_round
bash run.sh
```

This will process all prompts and save the generated responses to the `output` directory.

## Step 2: Preprocess Generated Responses

Once the LLM responses are generated and saved in the `output` directory, preprocess them for evaluation:

```bash
mkdir -p local_results
python pipeline_fix_jsonl_test.py output_dir/single_function_allinone.saved_deepseek-ai_deepseek-coder-6.7b-base_temp0.2_n100.jsonl
ls local_results
```

**Expected output:**
```
single_function_allinone.saved_deepseek-ai_deepseek-coder-6.7b-base_temp0.2_n100.jsonl.result.jsonl
```

## Step 3: Calculate Pass@K Metrics

Evaluate the model's performance by calculating the pass@100 metric:

```bash
python get_pass_k.py local_results/single_function_allinone.saved_deepseek-ai_deepseek-coder-6.7b-base_temp0.2_n100.jsonl.result.jsonl
```

This will output the pass@100 score, indicating how often the model generates at least one correct solution out of 100 attempts.

## File Structure

- `LLM_codegen_single_round/` - Main evaluation directory
- `output/` - Generated LLM responses
- `local_results/` - Preprocessed results ready for evaluation
- `pipeline_fix_jsonl_test.py` - Preprocessing script
- `get_pass_k.py` - Pass@K calculation script

## Notes

- Replace the model name in file paths with your specific model (e.g., `deepseek-ai/deepseek-coder-6.7b-base`)
- Temperature and sample count can be adjusted based on your evaluation requirements
- The pass@K metric measures the probability that at least one out of K generated samples passes the test cases
