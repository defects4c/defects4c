import signal
import time
from typing import Dict

import openai
from openai.types.chat import ChatCompletion
# from openai.types.chat import ChatCompletion


def make_request(
    client: openai.Client,
    message: str,
    model: str,
    max_tokens: int = 512,
    temperature: float = 1,
    n: int = 1,
    **kwargs
) -> ChatCompletion:
    # print ("model", model , message , "messages" )
    return client.chat.completions.create(
        # engine="xms2instruct",
        
        model=model,
        messages=[
            {
                "role": "system",
                "content": "You are a helpful assistant designed to output JSON.",
            },
            {"role": "user", "content": message},
        ] if type(message)==str else message ,
        max_tokens=max_tokens,
        temperature=temperature,
        n=n,
        **kwargs
    )

def make_request_cmp(
    client: openai.Client,
    message: str,
    model: str,
    max_tokens: int = 2048,
    temperature: float = 1,
    n: int = 1,
    **kwargs
) :
    x_message ="".join(  [x["content"] for x in message ] ) if type(message)!=str else message
    # print ("model", model , message , "messages" )
    # print ("kwargs", "------>"*8, kwargs )
    return client.completions.create(
        # engine="xms2instruct",
        model=model,
        prompt=x_message, 
        max_tokens=max_tokens,
        temperature=temperature,
        # n=n,
        **kwargs
    )


def handler(signum, frame):
    # swallow signum and frame
    raise Exception("end of time")


def make_auto_request(*args, **kwargs) -> ChatCompletion:
    ret = None
    while ret is None:
        try:
            signal.signal(signal.SIGALRM, handler)
            signal.alarm(100)
            ret = make_request(*args, **kwargs)
            signal.alarm(0)
        except openai.RateLimitError:
            print("Rate limit exceeded. Waiting...")
            signal.alarm(0)
            time.sleep(5)
        except openai.APIConnectionError:
            print("API connection error. Waiting...")
            signal.alarm(0)
            time.sleep(5)
        # except openai.APIError as e:
        #     print(e,"openai.APIError--->")
        #     signal.alarm(0)
        # except Exception as e:
        #     print("Unknown error. Waiting...")
        #     print(e)
        #     signal.alarm(0)
        #     time.sleep(1)
    return ret


def make_auto_request_cmp(*args, **kwargs) -> ChatCompletion:
    ret = None
    while ret is None:
        try:
            signal.signal(signal.SIGALRM, handler)
            signal.alarm(100)
            ret = make_request_cmp(*args, **kwargs)
            signal.alarm(0)
        except openai.RateLimitError:
            print("Rate limit exceeded. Waiting...")
            signal.alarm(0)
            time.sleep(5)
        except openai.APIConnectionError:
            print("API connection error. Waiting...")
            signal.alarm(0)
            time.sleep(5)
        # except openai.APIError as e:
        #     print(e,"openai.APIError--->")
        #     signal.alarm(0)
        # except Exception as e:
        #     print("Unknown error. Waiting...")
        #     print(e)
        #     signal.alarm(0)
        #     time.sleep(1)
    return ret