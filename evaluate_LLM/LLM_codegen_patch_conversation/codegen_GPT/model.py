import json
import os
from abc import ABC, abstractmethod
from typing import List
from warnings import warn

# Communism
#os.environ["HF_HOME"] = os.environ.get("HF_HOME", "/JawTitan/huggingface/")

import openai


from .api_request import make_auto_request, make_auto_request_cmp


class DecoderBase(ABC):
    def __init__(
        self,
        name: str,
        batch_size: int = 1,
        temperature: float = 0.8,
        # max_new_tokens: int = 512,
        max_new_tokens: int = 1024,
        conversational: bool = False,
        max_conversational_new_tokens: int = 4096,
    ) -> None:
        print("Initializing a decoder model: {} ...".format(name))
        self.name = name
        self.batch_size = batch_size
        self.temperature = temperature
        self.skip_special_tokens = False
        self.max_new_tokens = (
            max_conversational_new_tokens if conversational else max_new_tokens
        )
        self.conversational = conversational

    @abstractmethod
    def codegen(
        self, prompt: str, do_sample: bool = True, num_samples: int = 200
    ) -> List[str]:
        pass

    def __repr__(self) -> str:
        return self.name

    def __str__(self) -> str:
        return self.name


class OpenAIChatDecoder(DecoderBase):
    def __init__(self, name: str, **kwargs) -> None:
        super().__init__(name, **kwargs)
        # add by kjl
        # batch_size
        # self.batch_size = 5
        self.client = openai.OpenAI()

    def codegen(
        self, prompt: str, do_sample: bool = True, num_samples: int = 200
    ) -> List[str]:
        if do_sample:
            assert self.temperature > 0, "Temperature must be positive for sampling"

        batch_size = min(self.batch_size, num_samples)
        assert batch_size <= 20, "Use larger batch size could blow up the memory!"

        # construct prompt
        fmt = "json_object" if self.name == "gpt-4-1106-preview" else "text"

        ret = make_auto_request(
            self.client,
            message=prompt,
            model=self.name,
            # max_tokens=self.max_new_tokens,
            temperature=self.temperature,
            n=batch_size,
            # response_format={"type": fmt},
        )
        


        outputs = []
        for item in ret.choices:
            content = item.message.content
            # if json serializable
            if fmt == "json_object":
                try:
                    json_data = json.loads(content)
                    if json_data.get("code", None) is not None:
                        outputs.append(prompt + "\n" + json_data["code"])
                        continue

                    print(f"'code' field not found in: {json_data}")
                except Exception as e:
                    print(e)
            outputs.append(content)

        return outputs

class XOpenAIChatDecoder(DecoderBase):
    def __init__(self, name: str, **kwargs) -> None:
        super().__init__(name, **kwargs)
        self.client = openai.OpenAI()

    def codegen(
        self, prompt: str, do_sample: bool = True, num_samples: int = 200
    ) -> List[str]:
        if do_sample:
            assert self.temperature > 0, "Temperature must be positive for sampling"

        print (prompt , "type", type(prompt) )
        prompt = [x["content"] for x in prompt if x["role"]=="user"]
        prompt = "".join(prompt)
        
        prompt = f"""Below is an instruction that describes a task. Write a response that appropriately completes request.

### Instruction:
Create a patch to fix script for this problem:
{prompt}
### Response:
```cpp
"""

        batch_size = min(self.batch_size, num_samples)
        assert batch_size <= 20, "Use larger batch size could blow up the memory!"


        ret = make_auto_request_cmp(
            self.client,
            message=prompt,
            model=self.name,
            # max_tokens=self.max_new_tokens,
            temperature=self.temperature,
            n=batch_size,
            # response_format={"type": fmt},
        )
        

        outputs = []
        for item in ret.choices:
            content = item.text 
            # if json serializable
            outputs.append(content)

        return outputs


def make_model(name: str, batch_size: int = 1, temperature: float = 0.8):
    if "wizard" not in name.lower() :
        return OpenAIChatDecoder(
            batch_size=batch_size,
            name=name,
            temperature=temperature,
            conversational=True,
        )
    else :
        return XOpenAIChatDecoder(
            batch_size=batch_size,
            name=name,
            temperature=temperature,
            conversational=True,
        )
    raise ValueError(f"Invalid model name: {name}")
