import json
import os
from abc import ABC, abstractmethod
from typing import List, Any
from warnings import warn
from pathlib import Path
from os import PathLike

import torch
from tqdm import tqdm
from transformers import AutoTokenizer
from vllm import LLM, SamplingParams



EOS = [
    "<|endoftext|>",
    "<|endofmask|>",
#    "</s>",
]

# Additional EOS tokens for instruct models
INSTRUCT_EOS = [
#    "<|im_end|>",  # ChatML format
#    "[/INST]",     # Llama-style
]


def extra_eos_for_direct_completion(dataset) -> List[str]:
    """Return system EOS tokens only"""
    return EOS.copy()


def is_instruct_model(tokenizer: AutoTokenizer) -> bool:
    """Check if model is an instruction-tuned model based on tokenizer capabilities"""
    return hasattr(tokenizer, "apply_chat_template") and tokenizer.chat_template is not None


def make_raw_chat_prompt(prompt: Any, tokenizer: AutoTokenizer, max_tokens: int = 1900) -> str:
    """Convert prompt to chat format if tokenizer supports it, with truncation support.
    
    Args:
        prompt: Input prompt (string or list of messages)
        tokenizer: Tokenizer to use
        max_tokens: Maximum tokens allowed (default 1900 to leave buffer for generation)
    """
    def truncate_content(content: str, max_len: int) -> str:
        """Truncate content from the right to fit within max_len tokens."""
        tokens = tokenizer.encode(content, add_special_tokens=False)
        if len(tokens) <= max_len:
            return content
        
        print(f"Warning: Content ({len(tokens)} tokens) exceeds max_len ({max_len}). Truncating from right.")
        truncated_tokens = tokens[:max_len]
        return tokenizer.decode(truncated_tokens, skip_special_tokens=False)
    
    if hasattr(tokenizer, "apply_chat_template") and tokenizer.chat_template:
        messages = prompt if isinstance(prompt, list) else [{"role": "user", "content": str(prompt)}]
        
        # Pre-truncate individual message contents if they're too long
        truncated_messages = []
        for msg in messages:
            if isinstance(msg, dict) and "content" in msg:
                # Reserve some tokens for chat template formatting
                max_content_tokens = max_tokens - 100  # Reserve 100 tokens for template overhead
                truncated_content = truncate_content(str(msg["content"]), max_content_tokens)
                truncated_msg = msg.copy()
                truncated_msg["content"] = truncated_content
                truncated_messages.append(truncated_msg)
            else:
                truncated_messages.append(msg)
        
        try:
            # Apply chat template with pre-truncated content
            chat_prompt = tokenizer.apply_chat_template(truncated_messages, tokenize=False, add_generation_prompt=True)
            
            # Final safety check - if still too long, do hard truncation
            tokens = tokenizer.encode(chat_prompt, add_special_tokens=False)
            if len(tokens) > max_tokens:
                print(f"Warning: Final chat prompt ({len(tokens)} tokens) still exceeds max_tokens ({max_tokens}). Hard truncating.")
                truncated_tokens = tokens[:max_tokens]
                chat_prompt = tokenizer.decode(truncated_tokens, skip_special_tokens=False)
            
            return chat_prompt
            
        except Exception as e:
            print(f"Chat template failed: {e}, using raw text")
            # Fall through to raw text handling

    # Fallback to raw text with truncation
    raw_prompt = str(prompt)
    return truncate_content(raw_prompt, max_tokens)


def analyze_token_counts(input_file: str, tokenizer_name: str = None) -> dict:
    """
    Analyze token counts from the input JSONL file
    Returns dict with statistics for reference only
    """
    token_counts = []
    total_items = 0
    
    # Use the same tokenizer as the model
    if tokenizer_name:
        try:
            from transformers import AutoTokenizer
            tokenizer = AutoTokenizer.from_pretrained(tokenizer_name)
            print(f"Using model tokenizer: {tokenizer_name}")
            is_transformers_tokenizer = True
        except Exception as e:
            print(f"Warning: Could not load model tokenizer {tokenizer_name}: {e}")
            print("Falling back to tiktoken GPT-4o tokenizer")
            try:
                import tiktoken
                tokenizer = tiktoken.encoding_for_model("gpt-4o")
                is_transformers_tokenizer = False
            except:
                import tiktoken
                tokenizer = tiktoken.encoding_for_model("gpt-4")
                is_transformers_tokenizer = False
    else:
        # Fallback to tiktoken if no model specified
        try:
            import tiktoken
            tokenizer = tiktoken.encoding_for_model("gpt-4o")
            is_transformers_tokenizer = False
        except:
            import tiktoken
            tokenizer = tiktoken.encoding_for_model("gpt-4")
            is_transformers_tokenizer = False
    
    try:
        with open(input_file, 'r', encoding='utf-8') as f:
            print ("start counter.....[1]", tokenizer_name)
            for line in f:
                try:
                    data = json.loads(line.strip())
                    if 'token_count' in data:
                        # If token_count already exists, use it
                        token_counts.append(data['token_count'])
                    elif 'prompt' in data:
                        # Recalculate token count using the model's tokenizer
                        prompt = data['prompt']
                        if isinstance(prompt, list):
                            # Calculate tokens for content fields in messages
                            total_tokens = 0
                            for message in prompt:
                                if 'content' in message:
                                    content = str(message['content'])
                                    if is_transformers_tokenizer:
                                        total_tokens += len(tokenizer.encode(content, add_special_tokens=False))
                                    else:  # tiktoken tokenizer
                                        total_tokens += len(tokenizer.encode(content))
                            token_counts.append(total_tokens)
                        else:
                            # Single prompt string
                            content = str(prompt)
                            if is_transformers_tokenizer:
                                token_counts.append(len(tokenizer.encode(content, add_special_tokens=False)))
                            else:  # tiktoken tokenizer
                                token_counts.append(len(tokenizer.encode(content)))
                    
                    total_items += 1
                except json.JSONDecodeError:
                    continue
            print ("start counter.....[2]",tokenizer_name)
    except FileNotFoundError:
        print(f"Warning: Token count file {input_file} not found.")
        return {"max_tokens": 0, "stats": {}}
    
    if not token_counts:
        print("Warning: No token_count field found in input file.")
        return {"max_tokens": 0, "stats": {}}
    
    max_tokens = max(token_counts)
    avg_tokens = sum(token_counts) / len(token_counts)
    percentile_95 = sorted(token_counts)[int(len(token_counts) * 0.95)] if token_counts else 0
    
    stats = {
        "total_items": total_items,
        "items_with_tokens": len(token_counts),
        "max_tokens": max_tokens,
        "avg_tokens": round(avg_tokens, 2),
        "95th_percentile": percentile_95,
        "tokenizer_used": tokenizer_name if tokenizer_name else "tiktoken-gpt4o"
    }
    
    return {
        "max_tokens": max_tokens,
        "stats": stats
    }


class DecoderBase(ABC):

    def __init__(
        self,
        name: str,
        batch_size: int = 1,
        temperature: float = 0.8,
        max_new_tokens: int = 768,
        dtype: str = "bfloat16",  # default
        trust_remote_code: bool = True,
    ) -> None:
        print("Initializing a decoder model: {} ...".format(name))
        self.name = name
        self.batch_size = batch_size
        self.temperature = temperature
        self.eos = EOS
        self.skip_special_tokens = False
        self.max_new_tokens = max_new_tokens
        self.dtype = dtype
        self.trust_remote_code = trust_remote_code

    @abstractmethod
    def codegen(self, prompt: str, do_sample: bool = True, num_samples: int = 200) -> tuple[List[str], List[str]]:
        pass

    @abstractmethod
    def is_direct_completion(self) -> bool:
        pass

    def __repr__(self) -> str:
        return self.name

    def __str__(self) -> str:
        return self.name


class VllmDecoder(DecoderBase):

    def __init__(self, name: str, dataset: str, tp: int, input_file: str = None, force_base_prompt: bool = False, max_model_len: int = 4096, **kwargs) -> None:
        super().__init__(name, **kwargs)

        # Analyze token counts from input file for reference only
        token_analysis = {"stats": {}}
        if input_file:
            token_analysis = analyze_token_counts(input_file, self.name)
            print(f"Token analysis results:")
            for key, value in token_analysis["stats"].items():
                print(f"  {key}: {value}")

        kwargs_vllm = {
            "tensor_parallel_size": int(os.getenv("VLLM_N_GPUS", tp)),
            "dtype": self.dtype,
            "trust_remote_code": self.trust_remote_code,
        }

        self.force_base_prompt = force_base_prompt
        self.tokenizer = AutoTokenizer.from_pretrained(self.name)
        
        if self.is_direct_completion():
            self.eos += extra_eos_for_direct_completion(dataset)
        else:
            self.eos += ["\n```\n"]
        
        # Use configurable max_model_len
        print(f"Using max_model_len: {max_model_len}")
        self.llm = LLM(model=name, max_model_len=max_model_len, **kwargs_vllm)
        print (self.llm)

    def is_direct_completion(self) -> bool:
        # Match the reference implementation logic
        return self.force_base_prompt or self.tokenizer.chat_template is None

    def codegen(self, prompt: str, do_sample: bool = True, num_samples: int = 200) -> tuple[List[str], List[str]]:
        if do_sample:
            assert self.temperature > 0, "Temperature must be greater than 0!"
        
        batch_size = min(self.batch_size, num_samples)

        # Calculate safe max tokens (leave buffer for generation)
        safe_max_tokens = 1900  # Conservative limit, well below 2048
        
        # Format prompt based on model type with aggressive truncation
        if self.is_direct_completion():
            formatted_prompt = prompt
            # Check for truncation in direct completion mode
            tokens = self.tokenizer.encode(formatted_prompt, add_special_tokens=False)
            if len(tokens) > safe_max_tokens:
                print(f"Warning: Direct completion prompt ({len(tokens)} tokens) exceeds {safe_max_tokens} tokens. Truncating from right.")
                truncated_tokens = tokens[:safe_max_tokens]
                formatted_prompt = self.tokenizer.decode(truncated_tokens, skip_special_tokens=False)
        else:
            formatted_prompt = make_raw_chat_prompt(prompt, self.tokenizer, max_tokens=safe_max_tokens)

        # Final safety check before sending to vLLM
        final_tokens = self.tokenizer.encode(formatted_prompt, add_special_tokens=False)
        if len(final_tokens) > safe_max_tokens:
            print(f"EMERGENCY TRUNCATION: Final prompt ({len(final_tokens)} tokens) still too long. Hard truncating to {safe_max_tokens}.")
            truncated_tokens = final_tokens[:safe_max_tokens]
            formatted_prompt = self.tokenizer.decode(truncated_tokens, skip_special_tokens=False)

        print(f"Final prompt length: {len(self.tokenizer.encode(formatted_prompt, add_special_tokens=False))} tokens")

        # Generate with vLLM
        vllm_outputs = self.llm.generate(
            [formatted_prompt] * batch_size,
            SamplingParams(
                temperature=self.temperature,
                max_tokens=self.max_new_tokens,
                top_p=0.95 if do_sample else 1.0,
                stop=self.eos,
                # Remove truncate_prompt_tokens since we handle truncation manually
            ),
            use_tqdm=False,
        )

        # Extract generated text and stop reasons
        gen_strs = []
        stop_reasons = []
        
        for output in vllm_outputs:
            completion = output.outputs[0]
            text = completion.text.replace("\t", "    ")
            # Extract stop_reason or finish_reason
            stop_reason = getattr(completion, "finish_reason", getattr(completion, "stop_reason", None))
            
            gen_strs.append(text)
            stop_reasons.append(stop_reason)
        
        return gen_strs, stop_reasons


class GeneralVllmDecoder(VllmDecoder):

    def __init__(self, name: str, no_batching: bool, input_file: str = None, max_model_len: int = 4096, **kwargs) -> None:
        super().__init__(name, input_file=input_file, max_model_len=max_model_len, **kwargs)
        self.no_batching = no_batching
        print(f"EOS strings: {self.eos}")


def make_model(
    model: str,
    backend: str = "vllm",
    batch_size: int = 1,
    temperature: float = 0.0,
    tp=1,
    no_batching=False,
    input_file: str = None,
    force_base_prompt: bool = False,
    max_model_len: int = 4096,
):
    dataset = "dummy"  # dummy dataset since we're reading from jsonl
    if backend == "vllm":
        return GeneralVllmDecoder(
            name=model,
            batch_size=batch_size,
            temperature=temperature,
            dataset=dataset,
            tp=tp,
            no_batching=no_batching,
            input_file=input_file,
            force_base_prompt=force_base_prompt,
            max_model_len=max_model_len,
        )
    else:
        raise ValueError(f"Unsupported backend: {backend}")


def build_output_filename(input_file: str, model: str, temperature: float, n_samples: int) -> str:
    """
    Build output filename from input file, model name, temperature, and n_samples
    Example: single_function_allinone.saved.jsonl -> single_function_allinone.saved_deepseek-ai_deepseek-coder-6.7b-instruct_temp0_n1.jsonl
    """
    input_path = Path(input_file)
    base_name = input_path.stem  # removes .jsonl extension
    
    # Clean model name (replace / with _ for file system compatibility)
    clean_model = model.replace("/", "_")
    
    # Format temperature (remove decimal if it's a whole number)
    temp_str = f"temp{int(temperature)}" if temperature == int(temperature) else f"temp{temperature}"
    
    output_name = f"{base_name}_{clean_model}_{temp_str}_n{n_samples}.jsonl"
    output_path = input_path.parent / output_name
    
    return str(output_path)

base_prefix = ", donot explain, only reply the corrected code, you can startwith \n```cpp\n "

def codegen(
    input_file: PathLike,
    target_file: PathLike,
    model: DecoderBase,
    greedy=False,
    n_samples=1,
    no_new_line_at_last=False,
    resume=True,
):
    """
    Generate code completions from JSONL input file - fixed resume logic following paste-2.txt
    """
    
    # Read prompts from JSONL file
    task_ids, prompts, original_prompts = [], [], []
    with open(input_file, 'r') as f:
        for line in f:
            data = json.loads(line.strip())
            task_ids.append(data.get("idx", len(task_ids)))  # Use index if no task_id
            prompt = data["prompt"]
            
            if type(prompt) == list:
                prompt = "\n".join([x["content"] for x in prompt])
            
            original_prompts.append(prompt)  # Store original prompt
            
            if model.is_direct_completion():
                prompt += base_prefix

            if not no_new_line_at_last:  # qwen, +\n
                prompts.append(prompt.strip() + "\n")
            else:  # no_new_line_at_last, strip it
                prompts.append(prompt.strip())

    print(f"Loaded {len(prompts)} prompts from {input_file}")

    # Fixed resume logic following paste-2.txt pattern
    task2nexist = {}
    output_file = Path(target_file)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    
    if resume and output_file.exists():
        print(f"Resume mode: counting existing completions in {target_file}")
        with open(output_file, 'r') as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                    task_id = data["task_id"]
                    task2nexist[task_id] = task2nexist.get(task_id, 0) + 1
                except json.JSONDecodeError:
                    continue
        
        total_existing = sum(task2nexist.values())
        print(f"Found {total_existing} existing completions for {len(task2nexist)} tasks")

    print(f"Saving results to => {target_file}")
    
    # Process each task following the paste-2.txt pattern
    with open(target_file, "a") as f:
        for i, (task_id, prompt, original_prompt) in enumerate(tqdm(zip(task_ids, prompts, original_prompts), 
                                                                     desc="Processing tasks", 
                                                                     total=len(task_ids))):
            
            n_more_samples = n_samples
            log = f"Codegen: {task_id} @ {model}"
            if resume and task2nexist.get(task_id, 0) > 0:
                log += f" (resuming from {task2nexist[task_id]})"
                n_more_samples -= task2nexist[task_id]

            print(log)
            
            # Skip if already complete
            if n_more_samples <= 0:
                continue

            sidx = n_samples - n_more_samples
            while sidx < n_samples:
                # Generate remaining samples
                outputs, stop_reasons = model.codegen(
                    prompt, 
                    do_sample=not greedy, 
                    num_samples=n_more_samples,
                )
                
                assert outputs, f"No outputs from model for task {task_id}!"
                
                # Save each completion with stop reason
                for impl, stop_reason in zip(outputs, stop_reasons):
                    if model.is_direct_completion():
                        solution = base_prefix + impl
                    else:
                        solution = impl
                        
                    completion_data = {
                        "task_id": task_id, 
                        "sample_idx": sidx,
                        "stop": stop_reason,
                        "completion": solution,
                    }

                    json.dump(completion_data, f, indent=None, ensure_ascii=False)
                    f.write("\n")
                    f.flush()  # Ensure immediate write to disk
                    
                    sidx += 1
                    if sidx >= n_samples:
                        break


def main(
    input_file: str,
    model: str,
    bs: int = 1,
    n_samples: int = 1,
    temperature: float = 0.0,
    greedy: bool = False,
    backend: str = "vllm",
    no_batching: bool = False,
    tp: int = 1,
    no_new_line_at_last: bool = False,
    output_file: str = None,
    resume: bool = True,
    force_base_prompt: bool = False,
    max_len: int = 4096,
):
    """
    Main function for code generation from JSONL input
    
    Args:
        input_file: Path to input JSONL file containing prompts
        model: Model name/path
        bs: Batch size
        n_samples: Number of samples per prompt
        temperature: Sampling temperature
        greedy: Use greedy decoding
        backend: Backend to use ('vllm')
        no_batching: Disable continuous batching in vLLM
        tp: Tensor parallelism degree
        no_new_line_at_last: Strip newlines from prompts
        output_file: Optional output file path (auto-generated if not provided)
        resume: Whether to resume from existing completions (default: True)
        force_base_prompt: Force base prompt format even for instruct models
        max_len: Maximum model context length (default: 4096)
    """
    
    if greedy and (temperature != 0 or bs != 1 or n_samples != 1):
        temperature = 0.0
        bs = 1
        n_samples = 1
        print("Greedy decoding ON (--greedy): setting bs=1, n_samples=1, temperature=0")

    # Model creation with input_file for token analysis
    model_runner = make_model(
        model=model,
        backend=backend,
        batch_size=bs,
        temperature=temperature,
        tp=tp,
        no_batching=no_batching,
        input_file=input_file,
        force_base_prompt=force_base_prompt,
        max_model_len=max_len,
    )

    # Auto-generate output filename if not provided
    if output_file is None:
        output_file = build_output_filename(input_file, model, temperature, n_samples)
    output_file = os.path.join("outputs", output_file)

    print(f"Generation will => {output_file}")
    print(f"{no_new_line_at_last = }")
    print(f"Model type: {'Direct completion' if model_runner.is_direct_completion() else 'Chat/Instruct'}")
    
    codegen(
        input_file=input_file,
        target_file=output_file,
        model=model_runner,
        greedy=greedy,
        n_samples=n_samples,
        no_new_line_at_last=no_new_line_at_last,
        resume=resume,
    )

    print(f"------ END OF Generation ------")


if __name__ == "__main__":
    from fire import Fire
    Fire(main)
