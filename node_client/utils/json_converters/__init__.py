import orjson

from node_client.utils.json_converters.conf2json import ConfConverter


class FileConverter:
    """
    Базовый формат для конвертации - json

    1. Конвертация из PythonDict
    - Контент будущего файла каждой функции(результат конвертации) отдаётся в БАЙТАХ(bytes)

    2. Конвертация файла в PythonDict
    - На вход any2json file_content должен быть таким, каким требуется в конвертор-функции конкретного формата файла
    - Требование к функциям-конвертерам из json/в json: Лучше это будет str
    """

    f_formats_map = {
        1: 'json',
        3: 'conf',
        2: 'yml/yaml',
    }
    dict_to_any = {
        1: lambda x: orjson.dumps(x, option=orjson.OPT_INDENT_2),
        2: ConfConverter.json2conf,
    }
    any_to_dict = {
        1: orjson.loads,
        2: ConfConverter.conf2json,
    }

    @classmethod
    def json2any(cls, content: dict, file_format: int):
        res = cls.dict_to_any[file_format](content)
        if not isinstance(res, bytes):
            res = res.encode('utf-8')
        return res


    @classmethod
    def any2json(cls, file_content, file_format):
        return cls.any_to_dict[file_format](file_content)
