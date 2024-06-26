#from loguru import logger

class ChatParser:

    def __init__(self, parser:str):
        self._parser = parser
        if self._parser not in ['simple', 'complex']:
            #logger.error('Unsupported parser mode: {}', self._parser)
            raise KeyError()

    @staticmethod
    def _complex_chatgpt_parse(gen_body, suffix, prefix):
        if "```" in gen_body:
            func = gen_body.split("```")[1]
            func = "\n".join(func.split("\n")[1:]).strip()
            strip_suffix = "".join(suffix.split())
            strip_prefix = "".join(prefix.split())

            # check if some suffix is overlapped
            index, found = 2, False
            while index <= len(func):
                if strip_suffix.startswith("".join(func[-index:].split())):
                    found = True
                    break
                index += 1

            if found and not len("".join(func[-index:].split())) * "}" == "".join(func[-index:].split()):
                func = func[:len(func) - index].strip()
            # check if some prefix is overlapped
            index, found = 1, False
            while index <= len(func):
                if strip_prefix.endswith("".join(func[:index].split())):
                    found = True
                    break
                index += 1
            if found and index != 1:
                func = func[index:].strip()
            # basically saves previous history up until the last
            pre_history_list = gen_body.split("```")[:2]
            # revisionist history :p
            pre_history_list[1] = func
            pre_history = "```\n".join(pre_history_list) + "\n```"
        else:
            func, pre_history = "", ""
        return func.strip(), pre_history

    @staticmethod
    def _simple_chatgpt_parse(gen_body, lang="python"):
        # first check if its a code block
        if "```" in gen_body:
            func = gen_body.split("```")[1]
            func = "\n".join(func.split("\n")[1:])
            # basically saves previous history up until the last
            pre_history = "```".join(gen_body.split("```")[:2]) + "```"
        else:
            func, pre_history = "", ""
        return func, pre_history

    def chatgpt_parse(self, gen_body, lang="cpp", suffix=None, prefix=None) -> tuple:
        if self._parser == 'simple':
            return self._simple_chatgpt_parse(gen_body, lang)
        elif self._parser == 'complex':
            return self._complex_chatgpt_parse(gen_body, suffix, prefix)
        else:
            #logger.error('Unsupported parser mode: {}', self._parser)
            raise KeyError()
